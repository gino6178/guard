"""HTTP API (FastAPI). Serves the React build from frontend/dist when present."""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import retention, workflow as W
from .auth import audit, current_user, db, hash_password, make_token, project_for, require, verify_password
from .config import settings
from .db import (CLASSIFICATIONS, ROLES, Approval, AuditLog, DeidToken, Document, Finding, Project, Review, Segment,
                 User, WorkflowTemplate, get_session, init_db, utcnow)
from .engine import fact_master, run_check
from .export import findings_xlsx, report_docx
from .ingest import delete_document, ingest, regroup
from .llm import LLM
from .parsing import SUPPORTED
from .versioning import DOC_TYPE_LABELS

log = logging.getLogger("dg")
app = FastAPI(title="Deliverable Guard", version="0.1.0")
llm = LLM()
_jobs: dict[int, dict] = {}


# ------------------------------------------------------------------ lifecycle
DEMO_USERS = (("admin", "系統管理員", "admin", 3), ("handler", "承辦人（示範）", "handler", 2),
              ("reviewer", "覆核者（示範）", "reviewer", 2), ("manager", "專案主管（示範）", "manager", 2),
              ("legal", "法務（示範）", "legal", 2))


def _seed_users() -> None:
    """Create any missing demo accounts; their random passwords are appended to initial_passwords.txt."""
    with get_session() as s:
        have = set(s.scalars(select(User.username)))
        lines = []
        for username, name, role, clr in DEMO_USERS:
            if username in have:
                continue
            pw = secrets.token_urlsafe(9)
            s.add(User(username=username, display_name=name, password_hash=hash_password(pw), role=role, clearance=clr))
            lines.append(f"{username}\t{pw}\t{role}")
        s.commit()
        W.seed_templates(s)
        if lines:
            p = settings.data_dir / "initial_passwords.txt"
            with p.open("a") as f:
                f.write("\n".join(lines) + "\n")
            p.chmod(0o600)
            log.warning("Initial accounts written to %s", p)


@app.on_event("startup")
async def _startup() -> None:
    init_db()
    _seed_users()

    async def purge_loop() -> None:
        while True:
            with get_session() as s:
                n = retention.purge_expired(s)
                if n:
                    log.info("retention purge removed %d project(s)", n)
            await asyncio.sleep(3600)

    asyncio.create_task(purge_loop())


# ------------------------------------------------------------------ schemas
class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str
    display_name: str
    password: str | None = None
    role: str
    clearance: int = 1
    active: bool = True


class ProjectIn(BaseModel):
    name: str
    scenario: str = "sales"
    classification: int = 1
    retention_days: int | None = None
    deid_enabled: bool = True


class ProjectPatch(BaseModel):
    name: str | None = None
    retention_days: int | None = None
    classification: int | None = None


class DocPatch(BaseModel):
    doc_type: str | None = None
    version_label: str | None = None
    version_major: int | None = None


class ReviewIn(BaseModel):
    decision: str  # confirm | dismiss
    comment: str = ""
    final: bool = False  # reviewer/admin ruling that settles a disputed finding


def _user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role,
            "clearance": u.clearance, "active": u.active}


def _project_out(s: Session, p: Project) -> dict:
    docs = list(s.scalars(select(Document).where(Document.project_id == p.id)))
    fs = list(s.scalars(select(Finding).where(Finding.project_id == p.id)))
    pending = [f for f in fs if f.status in ("open", "disputed")]
    return {"id": p.id, "name": p.name, "scenario": p.scenario, "classification": p.classification,
            "classification_label": CLASSIFICATIONS.get(p.classification), "deid_enabled": p.deid_enabled,
            "retain_until": p.retain_until.isoformat(), "created_at": p.created_at.isoformat(),
            "last_check": p.last_check, "documents": len(docs),
            "doc_types": sorted({d.doc_type for d in docs}),
            "findings": {st: sum(1 for f in fs if f.status == st) for st in ("open", "confirmed", "dismissed", "disputed")},
            "pending_by_kind": {k: sum(1 for f in pending if f.kind == k) for k in ("contradiction", "omission", "outdated")},
            "pending_by_severity": {k: sum(1 for f in pending if f.severity == k) for k in ("high", "medium", "low")},
            "approval": W.approval_state(s, p.id)}


def _doc_out(d: Document) -> dict:
    return {"id": d.id, "filename": d.filename, "fmt": d.fmt, "size": d.size, "doc_type": d.doc_type,
            "doc_type_label": DOC_TYPE_LABELS.get(d.doc_type, d.doc_type), "version_label": d.version_label,
            "version_group": d.version_group, "is_latest": d.is_latest, "doc_date": d.doc_date, "pages": d.pages,
            "ocr_pages": d.ocr_pages, "warnings": d.parse_warnings, "status": d.status,
            "uploaded_at": d.uploaded_at.isoformat(), "sha256": d.sha256}


def _finding_out(f: Finding, users: dict[int, User]) -> dict:
    return {"id": f.id, "kind": f.kind, "severity": f.severity, "field": f.field, "item": f.item, "title": f.title,
            "detail": f.detail, "evidence": f.evidence, "detector": f.detector, "status": f.status,
            "created_at": f.created_at.isoformat(),
            "reviews": [{"user": users[r.user_id].display_name if r.user_id in users else str(r.user_id),
                         "role": users[r.user_id].role if r.user_id in users else "", "decision": r.decision,
                         "final": r.final, "comment": r.comment, "at": r.created_at.isoformat()} for r in f.reviews]}


def _users(s: Session) -> dict[int, User]:
    return {u.id: u for u in s.scalars(select(User))}


# ------------------------------------------------------------------ auth & users
@app.post("/api/auth/login")
def login(body: LoginIn, s: Session = Depends(db)) -> dict:
    u = s.scalar(select(User).where(User.username == body.username))
    if settings.open_login:
        u = u or s.scalar(select(User).where(User.username == "admin"))
        audit(s, u, "login.open", target=body.username)
        s.commit()
        return {"token": make_token(u), "user": _user_out(u)}
    if not u or not u.active or not verify_password(body.password, u.password_hash):
        audit(s, None, "login.failed", target=body.username)
        s.commit()
        raise HTTPException(401, "帳號或密碼錯誤")
    audit(s, u, "login")
    s.commit()
    return {"token": make_token(u), "user": _user_out(u)}


@app.get("/api/me")
def me(user: User = Depends(current_user)) -> dict:
    return _user_out(user)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "llm": await llm.health(), "llm_model": settings.llm_model, "open_login": settings.open_login,
            "formats": sorted(set(SUPPORTED.values())), "classifications": CLASSIFICATIONS,
            "doc_types": DOC_TYPE_LABELS}


@app.get("/api/users")
def list_users(user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict]:
    require(user, "user.manage")
    return [_user_out(u) for u in s.scalars(select(User).order_by(User.id))]


@app.post("/api/users")
def create_user(body: UserIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "user.manage")
    if body.role not in ROLES:
        raise HTTPException(400, "角色無效")
    if s.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(400, "帳號已存在")
    if not body.password or len(body.password) < 8:
        raise HTTPException(400, "密碼至少 8 碼")
    u = User(username=body.username, display_name=body.display_name, password_hash=hash_password(body.password),
             role=body.role, clearance=body.clearance, active=body.active)
    s.add(u)
    audit(s, user, "user.create", target=body.username, role=body.role, clearance=body.clearance)
    s.commit()
    return _user_out(u)


@app.patch("/api/users/{uid}")
def update_user(uid: int, body: UserIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "user.manage")
    u = s.get(User, uid)
    if not u:
        raise HTTPException(404, "找不到使用者")
    if body.role not in ROLES:
        raise HTTPException(400, "角色無效")
    u.display_name, u.role, u.clearance, u.active = body.display_name, body.role, body.clearance, body.active
    if body.password:
        if len(body.password) < 8:
            raise HTTPException(400, "密碼至少 8 碼")
        u.password_hash = hash_password(body.password)
    audit(s, user, "user.update", target=u.username, role=u.role, clearance=u.clearance, active=u.active,
          password_changed=bool(body.password))
    s.commit()
    return _user_out(u)


# ------------------------------------------------------------------ projects
@app.get("/api/projects")
def list_projects(user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict]:
    ps = s.scalars(select(Project).where(Project.classification <= user.clearance).order_by(Project.id.desc()))
    return [_project_out(s, p) for p in ps]


@app.post("/api/projects")
def create_project(body: ProjectIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "project.create")
    if body.classification > user.clearance:
        raise HTTPException(400, "不可建立高於本身權限等級的專案")
    days = body.retention_days or settings.default_retention_days
    p = Project(name=body.name, scenario=body.scenario, classification=body.classification,
                deid_enabled=body.deid_enabled, retain_until=utcnow() + timedelta(days=days), created_by=user.id)
    s.add(p)
    s.flush()
    audit(s, user, "project.create", p.id, body.name, classification=body.classification, retention_days=days)
    s.commit()
    return _project_out(s, p)


@app.get("/api/projects/{pid}")
def get_project(pid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    return _project_out(s, project_for(s, user, pid))


@app.patch("/api/projects/{pid}")
def patch_project(pid: int, body: ProjectPatch, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    p = project_for(s, user, pid)
    require(user, "project.create")
    if body.name:
        p.name = body.name
    if body.retention_days is not None:
        require(user, "retention.manage")
        p.retain_until = utcnow() + timedelta(days=body.retention_days)
    if body.classification is not None:
        if body.classification > user.clearance:
            raise HTTPException(400, "不可高於本身權限等級")
        p.classification = body.classification
    audit(s, user, "project.update", p.id, p.name, **body.model_dump(exclude_none=True))
    s.commit()
    return _project_out(s, p)


@app.delete("/api/projects/{pid}")
def delete_project(pid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "retention.manage")
    p = project_for(s, user, pid)
    retention.purge_project(s, p)
    audit(s, user, "project.delete", pid, p.name)
    s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ documents
@app.get("/api/projects/{pid}/documents")
def list_docs(pid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict]:
    project_for(s, user, pid)
    docs = s.scalars(select(Document).where(Document.project_id == pid).order_by(Document.doc_type, Document.id))
    return [_doc_out(d) for d in docs]


@app.post("/api/projects/{pid}/documents")
async def upload(pid: int, files: list[UploadFile] = File(...), doc_type: str | None = Form(None),
                 user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "doc.upload")
    p = project_for(s, user, pid)
    ok, errors = [], []
    for f in files:
        data = await f.read()
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            errors.append({"filename": f.filename, "error": f"超過 {settings.max_upload_mb}MB"})
            continue
        try:
            d = await asyncio.to_thread(_ingest_one, p.id, f.filename or "file", data, user.id, doc_type)
            ok.append(d)
        except ValueError as e:
            errors.append({"filename": f.filename, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            log.exception("parse failed")
            errors.append({"filename": f.filename, "error": f"解析失敗：{e}"})
    return {"uploaded": ok, "errors": errors}


def _ingest_one(pid: int, filename: str, data: bytes, uid: int, doc_type: str | None) -> dict:
    with get_session() as s:
        p = s.get(Project, pid)
        u = s.get(User, uid)
        d = ingest(s, p, filename, data, uid, doc_type)
        audit(s, u, "doc.upload", pid, filename, sha256=d.sha256, size=d.size, doc_type=d.doc_type,
              invalidated=W.documents_changed(s, pid, f"上傳 {filename}"))
        s.commit()
        return _doc_out(d)


def _doc_for(s: Session, user: User, did: int) -> Document:
    d = s.get(Document, did)
    if not d:
        raise HTTPException(404, "找不到文件")
    project_for(s, user, d.project_id)
    return d


@app.patch("/api/documents/{did}")
def patch_doc(did: int, body: DocPatch, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "doc.upload")
    d = _doc_for(s, user, did)
    if body.doc_type:
        if body.doc_type not in DOC_TYPE_LABELS:
            raise HTTPException(400, "文件類型無效")
        d.doc_type = body.doc_type
    if body.version_major is not None:
        key = list(d.version_key or [0, 0, 0, 0, 0])
        key[0] = body.version_major
        d.version_key = key
        d.version_label = body.version_label or f"v{body.version_major}"
    regroup(s, d.project_id)
    audit(s, user, "doc.update", d.project_id, d.filename, **body.model_dump(exclude_none=True),
          invalidated=W.documents_changed(s, d.project_id, f"修改 {d.filename} 屬性"))
    s.commit()
    return _doc_out(d)


@app.delete("/api/documents/{did}")
def remove_doc(did: int, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "doc.delete")
    d = _doc_for(s, user, did)
    audit(s, user, "doc.delete", d.project_id, d.filename, sha256=d.sha256,
          invalidated=W.documents_changed(s, d.project_id, f"刪除 {d.filename}"))
    delete_document(s, d)
    s.commit()
    return {"ok": True}


@app.get("/api/documents/{did}/segments")
def segments(did: int, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    d = _doc_for(s, user, did)
    audit(s, user, "doc.view", d.project_id, d.filename)
    s.commit()
    segs = s.scalars(select(Segment).where(Segment.doc_id == did).order_by(Segment.seq))
    return {"document": _doc_out(d), "segments": [{"id": g.id, "page": g.page, "locator": g.locator, "text": g.text,
                                                    "ocr": g.ocr, "raw_text": g.raw_text} for g in segs]}


@app.get("/api/documents/{did}/original")
def original(did: int, user: User = Depends(current_user), s: Session = Depends(db)) -> FileResponse:
    require(user, "doc.upload")
    d = _doc_for(s, user, did)
    audit(s, user, "doc.download", d.project_id, d.filename)
    s.commit()
    return FileResponse(d.storage_path, filename=d.filename)


# ------------------------------------------------------------------ checks, facts, findings
@app.post("/api/projects/{pid}/check")
async def start_check(pid: int, force: bool = False, user: User = Depends(current_user),
                      s: Session = Depends(db)) -> dict:
    require(user, "check.run")
    p = project_for(s, user, pid)
    job = _jobs.get(pid)
    if job and job["state"] == "running":
        return job
    _jobs[pid] = job = {"state": "running", "started": utcnow().isoformat(), "summary": None, "error": None}
    audit(s, user, "check.start", pid, p.name, force=force)
    s.commit()

    async def work() -> None:
        try:
            with get_session() as s2:
                job["summary"] = await run_check(s2, s2.get(Project, pid), llm if settings.llm_enabled else None, force)
            job["state"] = "done"
        except Exception as e:  # noqa: BLE001
            log.exception("check failed")
            job.update(state="error", error=str(e))

    asyncio.create_task(work())
    return job


@app.get("/api/projects/{pid}/check")
def check_status(pid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    p = project_for(s, user, pid)
    return _jobs.get(pid) or {"state": "idle", "summary": p.last_check}


@app.get("/api/projects/{pid}/facts")
def facts(pid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    project_for(s, user, pid)
    docs = s.scalars(select(Document).where(Document.project_id == pid).order_by(Document.doc_type, Document.id))
    return {"documents": [_doc_out(d) for d in docs], "rows": fact_master(s, pid)}


@app.get("/api/projects/{pid}/findings")
def findings(pid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict]:
    project_for(s, user, pid)
    users = _users(s)
    order = {"high": 0, "medium": 1, "low": 2}
    fs = sorted(s.scalars(select(Finding).where(Finding.project_id == pid)),
                key=lambda f: (order.get(f.severity, 3), f.kind, f.id))
    return [_finding_out(f, users) for f in fs]


def resolve_status(f: Finding) -> str:
    """Two-person rule: agreement settles; disagreement is 'disputed' until a reviewer/admin rules (final)."""
    finals = [r for r in f.reviews if r.final]
    if finals:
        return "confirmed" if finals[-1].decision == "confirm" else "dismissed"
    latest: dict[int, Review] = {}
    for r in f.reviews:
        latest[r.user_id] = r
    if not latest:
        return "open"
    decisions = {r.decision for r in latest.values()}
    if len(decisions) == 1:
        return "confirmed" if decisions == {"confirm"} else "dismissed"
    return "disputed"


@app.post("/api/findings/{fid}/review")
def review(fid: int, body: ReviewIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "finding.review")
    if body.decision not in ("confirm", "dismiss"):
        raise HTTPException(400, "decision 須為 confirm 或 dismiss")
    f = s.get(Finding, fid)
    if not f:
        raise HTTPException(404, "找不到警示")
    project_for(s, user, f.project_id)
    if body.decision == "dismiss" and not body.comment.strip():
        raise HTTPException(400, "排除警示需填寫理由")
    if body.final and user.role not in ("reviewer", "admin"):
        raise HTTPException(403, "僅覆核者可做最終裁定")
    f.reviews.append(Review(user_id=user.id, decision=body.decision, comment=body.comment, final=body.final))
    s.flush()
    users = _users(s)
    f.status = resolve_status(f)
    audit(s, user, "finding.review", f.project_id, f"finding#{f.id}", decision=body.decision,
          comment=body.comment, final=body.final, status=f.status)
    s.commit()
    return _finding_out(f, users)


# ------------------------------------------------------------------ sign-off workflow
class TemplateIn(BaseModel):
    name: str
    scenario: str = ""
    nodes: list[dict]
    active: bool = True


class SubmitIn(BaseModel):
    template_id: int
    note: str = ""


class ActIn(BaseModel):
    action: str  # approve | reject | comment
    comment: str = ""


def _template_out(t: WorkflowTemplate) -> dict:
    return {"id": t.id, "name": t.name, "scenario": t.scenario, "nodes": t.nodes, "active": t.active}


def _approval_out(a: Approval, users: dict[int, User], viewer: User) -> dict:
    node = a.nodes[a.current] if a.status == "in_progress" and a.current < len(a.nodes) else None
    return {"id": a.id, "project_id": a.project_id, "template_name": a.template_name, "note": a.note, "status": a.status,
            "status_label": W.STATUS.get(a.status, a.status), "status_reason": a.status_reason, "nodes": a.nodes,
            "current": a.current, "snapshot": a.snapshot, "snapshot_hash": a.snapshot_hash,
            "submitted_by": users[a.submitted_by].display_name if a.submitted_by in users else "",
            "submitted_at": a.submitted_at.isoformat(), "completed_at": a.completed_at.isoformat() if a.completed_at else None,
            "can_act": bool(node) and viewer.id != a.submitted_by and W.can_act(viewer, node)
            and viewer.id not in {st.user_id for st in a.steps if st.action == "approve"},
            "can_withdraw": a.status == "in_progress" and (viewer.id == a.submitted_by or viewer.role == "admin"),
            "steps": [{"node_index": st.node_index, "node_name": st.node_name, "action": st.action, "comment": st.comment,
                       "user": users[st.user_id].display_name if st.user_id in users else str(st.user_id),
                       "role": users[st.user_id].role if st.user_id in users else "",
                       "at": st.created_at.isoformat(), "signature": st.signature} for st in a.steps]}


def _validate_nodes(nodes: list[dict]) -> list[dict]:
    if not nodes:
        raise HTTPException(400, "至少需要一個節點")
    out = []
    for n in nodes:
        if not str(n.get("name", "")).strip():
            raise HTTPException(400, "節點名稱不可空白")
        at = n.get("assignee_type", "role")
        if at == "role" and n.get("role") not in ROLES:
            raise HTTPException(400, f"節點「{n['name']}」的角色無效")
        if at == "users" and not n.get("users"):
            raise HTTPException(400, f"節點「{n['name']}」需指定簽核人")
        cond = n.get("condition") or {"type": "always"}
        if cond.get("type") not in W.CONDITIONS:
            raise HTTPException(400, "條件類型無效")
        out.append({"name": n["name"].strip(), "assignee_type": at, "role": n.get("role", ""),
                    "users": [int(u) for u in n.get("users", [])], "condition": cond})
    return out


@app.get("/api/workflows")
def list_templates(user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    return {"templates": [_template_out(t) for t in s.scalars(select(WorkflowTemplate).order_by(WorkflowTemplate.id))],
            "roles": W.ROLE_LABELS, "conditions": W.CONDITIONS,
            "users": [{"id": u.id, "name": u.display_name, "role": u.role} for u in s.scalars(select(User)) if u.active]}


@app.post("/api/workflows")
def create_template(body: TemplateIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "workflow.manage")
    t = WorkflowTemplate(name=body.name, scenario=body.scenario, nodes=_validate_nodes(body.nodes), active=body.active)
    s.add(t)
    s.flush()
    audit(s, user, "workflow.create", target=body.name, nodes=t.nodes)
    s.commit()
    return _template_out(t)


@app.put("/api/workflows/{tid}")
def update_template(tid: int, body: TemplateIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "workflow.manage")
    t = s.get(WorkflowTemplate, tid)
    if not t:
        raise HTTPException(404, "找不到範本")
    t.name, t.scenario, t.nodes, t.active = body.name, body.scenario, _validate_nodes(body.nodes), body.active
    audit(s, user, "workflow.update", target=body.name, nodes=t.nodes, active=body.active)
    s.commit()
    return _template_out(t)


@app.get("/api/projects/{pid}/approval/precheck")
def precheck(pid: int, template_id: int | None = None, user: User = Depends(current_user),
             s: Session = Depends(db)) -> dict:
    p = project_for(s, user, pid)
    tpls = [t for t in s.scalars(select(WorkflowTemplate).where(WorkflowTemplate.active)) if t.scenario in ("", p.scenario)]
    tpl = next((t for t in tpls if t.id == template_id), tpls[0] if tpls else None)
    gs = W.gates(s, p)
    return {"gates": gs, "ok": all(g["ok"] for g in gs), "templates": [_template_out(t) for t in tpls],
            "template_id": tpl.id if tpl else None, "nodes": W.resolve_nodes(s, p, tpl) if tpl else [],
            "amount": W.project_total(s, p.id)}


@app.get("/api/projects/{pid}/approvals")
def list_approvals(pid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict]:
    project_for(s, user, pid)
    users = _users(s)
    return [_approval_out(a, users, user) for a in
            s.scalars(select(Approval).where(Approval.project_id == pid).order_by(Approval.id.desc()))]


@app.post("/api/projects/{pid}/approvals")
def submit_approval(pid: int, body: SubmitIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "approval.submit")
    p = project_for(s, user, pid)
    tpl = s.get(WorkflowTemplate, body.template_id)
    if not tpl or not tpl.active:
        raise HTTPException(400, "簽核範本無效")
    try:
        a = W.submit(s, p, tpl, user, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit(s, user, "approval.submit", pid, f"DG-{a.id:05d}", template=tpl.name, snapshot=a.snapshot_hash)
    s.commit()
    return _approval_out(a, _users(s), user)


def _approval_for(s: Session, user: User, aid: int) -> Approval:
    a = s.get(Approval, aid)
    if not a:
        raise HTTPException(404, "找不到簽核")
    project_for(s, user, a.project_id)
    return a


@app.post("/api/approvals/{aid}/act")
def act_approval(aid: int, body: ActIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    if body.action not in ("approve", "reject", "comment"):
        raise HTTPException(400, "動作無效")
    a = _approval_for(s, user, aid)
    try:
        W.act(s, a, user, body.action, body.comment)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit(s, user, f"approval.{body.action}", a.project_id, f"DG-{a.id:05d}", comment=body.comment, status=a.status)
    s.commit()
    return _approval_out(a, _users(s), user)


@app.post("/api/approvals/{aid}/withdraw")
def withdraw_approval(aid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    a = _approval_for(s, user, aid)
    try:
        W.withdraw(a, user)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit(s, user, "approval.withdraw", a.project_id, f"DG-{a.id:05d}")
    s.commit()
    return _approval_out(a, _users(s), user)


@app.get("/api/approvals/inbox")
def inbox(user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict]:
    users = _users(s)
    out = []
    for a in s.scalars(select(Approval).where(Approval.status == "in_progress").order_by(Approval.submitted_at)):
        p = s.get(Project, a.project_id)
        if p.classification > user.clearance:
            continue
        o = _approval_out(a, users, user)
        if o["can_act"]:
            out.append({**o, "project_name": p.name})
    return out


@app.get("/api/approvals/{aid}/form.docx")
def approval_form(aid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> Response:
    a = _approval_for(s, user, aid)
    data = W.form_docx(a, _users(s))
    audit(s, user, "approval.form", a.project_id, f"DG-{a.id:05d}")
    s.commit()
    name = f"交付簽核單_DG-{a.id:05d}.docx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


# ------------------------------------------------------------------ export, audit, admin
def _export_name(p: Project, ext: str) -> dict:
    name = f"{p.name}_衝突清單.{ext}"
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"}


@app.get("/api/projects/{pid}/export.xlsx")
def export_xlsx(pid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> Response:
    require(user, "export")
    p = project_for(s, user, pid)
    fs = list(s.scalars(select(Finding).where(Finding.project_id == pid).order_by(Finding.id)))
    data = findings_xlsx(p, fs, _users(s))
    audit(s, user, "export.xlsx", pid, p.name, findings=len(fs))
    s.commit()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers=_export_name(p, "xlsx"))


@app.get("/api/projects/{pid}/report.docx")
def export_docx(pid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> Response:
    require(user, "export")
    p = project_for(s, user, pid)
    fs = list(s.scalars(select(Finding).where(Finding.project_id == pid).order_by(Finding.id)))
    docs = list(s.scalars(select(Document).where(Document.project_id == pid)))
    data = report_docx(p, fs, _users(s), docs)
    audit(s, user, "export.docx", pid, p.name, findings=len(fs))
    s.commit()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers=_export_name(p, "docx"))


@app.get("/api/audit")
def audit_log(project_id: int | None = None, limit: int = 300, user: User = Depends(current_user),
              s: Session = Depends(db)) -> list[dict]:
    require(user, "audit.read")
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 2000))
    if project_id:
        q = q.where(AuditLog.project_id == project_id)
    return [{"id": a.id, "ts": a.ts.isoformat(), "user": a.username, "action": a.action, "project_id": a.project_id,
             "target": a.target, "detail": a.detail} for a in s.scalars(q)]


@app.get("/api/projects/{pid}/deid")
def deid_tokens(pid: int, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict]:
    require(user, "deid.reveal")
    project_for(s, user, pid)
    audit(s, user, "deid.reveal", pid)
    s.commit()
    return [{"token": t.token, "kind": t.kind, "original": t.original}
            for t in s.scalars(select(DeidToken).where(DeidToken.project_id == pid))]


@app.post("/api/admin/purge")
def purge(user: User = Depends(current_user), s: Session = Depends(db)) -> dict:
    require(user, "retention.manage")
    n = retention.purge_expired(s)
    audit(s, user, "retention.purge", removed=n)
    s.commit()
    return {"removed": n}


_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        f = _dist / path
        return FileResponse(f if path and f.is_file() else _dist / "index.html")
