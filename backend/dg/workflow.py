"""Sign-off workflow (交付簽核): gates, configurable node templates, snapshot and invalidation.

A project can be submitted only when its latest check covers the current documents, no finding is
pending, and no confirmed high-severity problem remains. Submission freezes a snapshot (document
hashes + check result); any later document change invalidates in-progress and approved sign-offs.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import Approval, ApprovalStep, Document, Finding, Project, User, WorkflowTemplate, utcnow
from .normalize import fmt_amount
from .versioning import DOC_TYPE_LABELS

ROLE_LABELS = {"admin": "管理員", "handler": "承辦人", "reviewer": "覆核者", "manager": "主管", "legal": "法務"}
CONDITIONS = {
    "always": "一律",
    "amount_gte": "總金額（含稅）≥ 門檻",
    "has_doc_type": "文件包含指定類型",
    "has_high": "曾有高嚴重度警示（已確認並修正）",
}

DEFAULT_TEMPLATES = [
    {"name": "業務接案交付簽核", "scenario": "sales", "nodes": [
        {"name": "專案主管核准", "assignee_type": "role", "role": "manager", "users": [], "condition": {"type": "always"}},
        {"name": "法務審閱合約", "assignee_type": "role", "role": "legal", "users": [], "condition": {"type": "has_doc_type", "value": "contract"}},
        {"name": "部門主管核准（高金額）", "assignee_type": "role", "role": "admin", "users": [],
         "condition": {"type": "amount_gte", "value": 3_000_000}},
    ]},
    {"name": "研發成果交付簽核", "scenario": "rnd", "nodes": [
        {"name": "技術覆核", "assignee_type": "role", "role": "reviewer", "users": [], "condition": {"type": "always"}},
        {"name": "計畫主管核准", "assignee_type": "role", "role": "manager", "users": [], "condition": {"type": "always"}},
    ]},
]


def seed_templates(s: Session) -> None:
    if s.scalar(select(WorkflowTemplate.id).limit(1)):
        return
    for t in DEFAULT_TEMPLATES:
        s.add(WorkflowTemplate(name=t["name"], scenario=t["scenario"], nodes=t["nodes"]))
    s.commit()


# ------------------------------------------------------------------ facts used by gates and conditions
def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def project_total(s: Session, project_id: int) -> int | None:
    from .engine import fact_master
    for row in fact_master(s, project_id):
        if row["field"] == "total_amount" and row["reference"]:
            cells = row["values"].get(str(row["reference"]["doc_id"])) or []
            if cells:
                try:
                    return int(float(cells[0]["norm"]))
                except ValueError:
                    return None
    return None


def gates(s: Session, p: Project) -> list[dict]:
    """Submission checklist; each item {key, ok, label, detail}."""
    fs = list(s.scalars(select(Finding).where(Finding.project_id == p.id)))
    pending = [f for f in fs if f.status in ("open", "disputed")]
    high = [f for f in fs if f.status == "confirmed" and f.severity == "high"]
    docs = list(s.scalars(select(Document).where(Document.project_id == p.id)))
    checked_at = _as_aware(datetime.fromisoformat(p.last_check["at"])) if p.last_check else None
    changed_at = _as_aware(p.docs_changed_at)
    fresh = bool(checked_at) and (changed_at is None or changed_at <= checked_at)
    return [
        {"key": "documents", "ok": bool(docs), "label": "已上傳交付文件", "detail": f"{len(docs)} 份文件"},
        {"key": "checked", "ok": fresh, "label": "檢核涵蓋目前所有文件",
         "detail": "最近一次檢核晚於最後一次文件變動" if fresh else ("尚未執行檢核" if not checked_at else "檢核後文件有變動，請重新檢核")},
        {"key": "pending", "ok": not pending, "label": "所有警示均已處理",
         "detail": "無待處理或爭議警示" if not pending else f"尚有 {len(pending)} 項待處理（含爭議）"},
        {"key": "high", "ok": not high, "label": "無未修正的高嚴重度問題",
         "detail": "無" if not high else f"{len(high)} 項已確認的高嚴重度問題仍被偵測到，請上傳修正版並重新檢核"},
    ]


def _condition_met(cond: dict, ctx: dict) -> tuple[bool, str]:
    t = (cond or {}).get("type", "always")
    v = (cond or {}).get("value")
    if t == "amount_gte":
        amt = ctx.get("amount")
        if amt is None:
            return True, "無法判讀總金額，保守納入"
        return amt >= int(v or 0), f"總金額 {fmt_amount(amt)} {'≥' if amt >= int(v or 0) else '<'} {fmt_amount(int(v or 0))}"
    if t == "has_doc_type":
        ok = v in ctx["doc_types"]
        return ok, f"{'含' if ok else '不含'}{DOC_TYPE_LABELS.get(v, v)}"
    if t == "has_high":
        return ctx["had_high"], "曾有高嚴重度警示" if ctx["had_high"] else "無高嚴重度警示"
    return True, ""


def resolve_nodes(s: Session, p: Project, tpl: WorkflowTemplate) -> list[dict]:
    docs = list(s.scalars(select(Document).where(Document.project_id == p.id)))
    fs = list(s.scalars(select(Finding).where(Finding.project_id == p.id)))
    ctx = {"amount": project_total(s, p.id), "doc_types": {d.doc_type for d in docs},
           "had_high": any(f.severity == "high" for f in fs)}
    users = {u.id: u for u in s.scalars(select(User))}
    out = []
    for n in tpl.nodes:
        met, why = _condition_met(n.get("condition", {}), ctx)
        if n.get("assignee_type") == "users":
            who = "、".join(users[i].display_name for i in n.get("users", []) if i in users) or "（未指定）"
        else:
            who = ROLE_LABELS.get(n.get("role", ""), n.get("role", ""))
        out.append({**n, "skipped": not met, "reason": why, "assignee_label": who})
    return out


def can_act(user: User, node: dict) -> bool:
    if node.get("assignee_type") == "users":
        return user.id in node.get("users", [])
    return user.role == node.get("role")


def _first_active(nodes: list[dict], start: int) -> int:
    i = start
    while i < len(nodes) and nodes[i]["skipped"]:
        i += 1
    return i


# ------------------------------------------------------------------ actions
def snapshot_of(s: Session, p: Project) -> dict:
    docs = list(s.scalars(select(Document).where(Document.project_id == p.id).order_by(Document.id)))
    fs = list(s.scalars(select(Finding).where(Finding.project_id == p.id)))
    return {
        "project": p.name, "check": p.last_check,
        "documents": [{"id": d.id, "filename": d.filename, "doc_type": DOC_TYPE_LABELS.get(d.doc_type, d.doc_type),
                       "version": d.version_label, "latest": d.is_latest, "sha256": d.sha256} for d in docs],
        "findings": {"confirmed": sum(f.status == "confirmed" for f in fs), "dismissed": sum(f.status == "dismissed" for f in fs),
                     "items": [{"id": f.id, "status": f.status, "severity": f.severity, "title": f.title} for f in fs]},
        "total_amount": project_total(s, p.id),
    }


def _sign(*parts: str) -> str:
    return hmac.new(settings.secret_key.encode(), "|".join(parts).encode(), hashlib.sha256).hexdigest()


def submit(s: Session, p: Project, tpl: WorkflowTemplate, user: User, note: str) -> Approval:
    blockers = [g for g in gates(s, p) if not g["ok"]]
    if blockers:
        raise ValueError("尚未符合送簽條件：" + "；".join(f"{g['label']}（{g['detail']}）" for g in blockers))
    if s.scalar(select(Approval.id).where(Approval.project_id == p.id, Approval.status == "in_progress")):
        raise ValueError("此專案已有簽核進行中")
    nodes = resolve_nodes(s, p, tpl)
    if all(n["skipped"] for n in nodes):
        raise ValueError("此範本的所有節點條件皆不成立，請選擇其他範本")
    snap = snapshot_of(s, p)
    snap_hash = hashlib.sha256(json.dumps(snap, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    a = Approval(project_id=p.id, template_id=tpl.id, template_name=tpl.name, note=note, nodes=nodes,
                 current=_first_active(nodes, 0), snapshot=snap, snapshot_hash=snap_hash, submitted_by=user.id)
    s.add(a)
    s.flush()
    return a


def act(s: Session, a: Approval, user: User, action: str, comment: str) -> Approval:
    if a.status != "in_progress":
        raise ValueError("此簽核已結束")
    node = a.nodes[a.current]
    if action != "comment":
        if user.id == a.submitted_by:
            raise PermissionError("送簽人不可簽核自己送出的案件")
        if not can_act(user, node):
            raise PermissionError(f"此關卡由「{node['assignee_label']}」簽核")
        if user.id in {st.user_id for st in a.steps if st.action == "approve"}:
            raise PermissionError("同一人不可簽核兩個關卡")
    if action == "reject" and not comment.strip():
        raise ValueError("退回需填寫理由")
    ts = utcnow()
    a.steps.append(ApprovalStep(node_index=a.current, node_name=node["name"], user_id=user.id, action=action,
                                comment=comment, created_at=ts,
                                signature=_sign(a.snapshot_hash, str(a.current), str(user.id), action, ts.isoformat())))
    if action == "approve":
        a.current = _first_active(a.nodes, a.current + 1)
        if a.current >= len(a.nodes):
            a.status, a.completed_at = "approved", ts
    elif action == "reject":
        a.status, a.completed_at, a.status_reason = "rejected", ts, comment
    return a


def withdraw(a: Approval, user: User) -> None:
    if a.status != "in_progress":
        raise ValueError("此簽核已結束")
    if user.id != a.submitted_by and user.role != "admin":
        raise PermissionError("只有送簽人可撤回")
    a.status, a.completed_at, a.status_reason = "withdrawn", utcnow(), "送簽人撤回"


def documents_changed(s: Session, project_id: int, reason: str) -> int:
    """Record a document change; invalidate sign-offs whose snapshot no longer matches."""
    p = s.get(Project, project_id)
    p.docs_changed_at = utcnow()
    n = 0
    for a in s.scalars(select(Approval).where(Approval.project_id == project_id,
                                              Approval.status.in_(("in_progress", "approved")))):
        a.status, a.completed_at, a.status_reason = "invalidated", utcnow(), f"送簽後文件變動：{reason}"
        n += 1
    return n


def approval_state(s: Session, project_id: int) -> dict | None:
    a = s.scalar(select(Approval).where(Approval.project_id == project_id).order_by(Approval.id.desc()).limit(1))
    return {"id": a.id, "status": a.status} if a else None


# ------------------------------------------------------------------ sign-off form
STATUS = {"in_progress": "簽核中", "approved": "已核准，可對外交付", "rejected": "已退回", "withdrawn": "已撤回",
          "invalidated": "已失效"}


def form_docx(a: Approval, users: dict[int, User]) -> bytes:
    from docx import Document as Docx
    from docx.shared import Pt

    d = Docx()
    d.styles["Normal"].font.size = Pt(10.5)
    snap = a.snapshot
    d.add_heading(f"交付簽核單：{snap['project']}", 0)
    sub = users.get(a.submitted_by)
    d.add_paragraph(f"簽核編號：DG-{a.id:05d}　流程：{a.template_name}　狀態：{STATUS.get(a.status, a.status)}")
    d.add_paragraph(f"送簽人：{sub.display_name if sub else a.submitted_by}　送簽時間：{a.submitted_at:%Y-%m-%d %H:%M} UTC")
    if a.note:
        d.add_paragraph(f"送簽說明：{a.note}")
    if a.status_reason:
        d.add_paragraph(f"狀態說明：{a.status_reason}")
    d.add_paragraph(f"內容指紋（SHA-256）：{a.snapshot_hash}")

    d.add_heading("簽核關卡", 1)
    t = d.add_table(rows=1, cols=5)
    t.style = "Light Grid Accent 1"
    for c, h in zip(t.rows[0].cells, ("關卡", "簽核人", "結果", "時間", "意見")):
        c.text = h
    for i, n in enumerate(a.nodes):
        steps = [st for st in a.steps if st.node_index == i and st.action != "comment"]
        r = t.add_row().cells
        r[0].text = n["name"]
        if n["skipped"]:
            r[1].text, r[2].text, r[4].text = "—", "免簽", n["reason"]
        elif steps:
            st = steps[-1]
            u = users.get(st.user_id)
            r[1].text = u.display_name if u else str(st.user_id)
            r[2].text = "核准" if st.action == "approve" else "退回"
            r[3].text = f"{st.created_at:%Y-%m-%d %H:%M}"
            r[4].text = st.comment
        else:
            r[1].text, r[2].text = n["assignee_label"], "待簽" if i == a.current and a.status == "in_progress" else "—"

    d.add_heading("交付文件（送簽時快照）", 1)
    t = d.add_table(rows=1, cols=4)
    t.style = "Light Grid Accent 1"
    for c, h in zip(t.rows[0].cells, ("檔名", "類型", "版本", "SHA-256")):
        c.text = h
    for doc in snap["documents"]:
        r = t.add_row().cells
        r[0].text, r[1].text = doc["filename"], doc["doc_type"]
        r[2].text = doc["version"] + ("" if doc["latest"] else "（舊版）")
        r[3].text = doc["sha256"][:16] + "…"
    chk = snap.get("check") or {}
    d.add_heading("檢核結果", 1)
    d.add_paragraph(f"檢核時間：{chk.get('at', '')}　事實數：{chk.get('facts', '')}　"
                    f"警示：已確認 {snap['findings']['confirmed']}、已排除 {snap['findings']['dismissed']}")
    if snap.get("total_amount"):
        d.add_paragraph(f"總金額（含稅，依合約／報價）：{fmt_amount(snap['total_amount'])}")
    for f in snap["findings"]["items"]:
        d.add_paragraph(f"#{f['id']} [{'已確認' if f['status'] == 'confirmed' else '已排除'}] {f['title']}", style="List Bullet")
    d.add_heading("簽章紀錄", 1)
    for st in a.steps:
        u = users.get(st.user_id)
        d.add_paragraph(f"{st.created_at:%Y-%m-%d %H:%M:%S} {u.display_name if u else st.user_id} "
                        f"{ {'approve': '核准', 'reject': '退回', 'comment': '留言'}[st.action]}「{st.node_name}」 簽章 {st.signature[:24]}…")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
