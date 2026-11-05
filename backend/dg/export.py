"""Export the reviewed conflict list (XLSX) and a review report (DOCX)."""
from __future__ import annotations

import io

from .db import Finding, Project, User

KIND = {"contradiction": "直接矛盾", "omission": "遺漏", "outdated": "疑似過期"}
SEV = {"high": "高", "medium": "中", "low": "低"}
STATUS = {"open": "待確認", "confirmed": "已確認", "dismissed": "已排除", "disputed": "爭議待覆核"}


def _ev_text(e: dict) -> str:
    loc = e.get("locator") or ""
    q = e.get("quote") or e.get("note") or ""
    return f"{e['filename']}（{e.get('version', '')}）{loc}：{q}"


def _reviews(f: Finding, users: dict[int, User]) -> str:
    return "；".join(f"{users[r.user_id].display_name if r.user_id in users else r.user_id}"
                     f" {'確認' if r.decision == 'confirm' else '排除'}"
                     + (f"（{r.comment}）" if r.comment else "") for r in f.reviews)


def findings_xlsx(project: Project, findings: list[Finding], users: dict[int, User]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "衝突清單"
    head = ["編號", "類型", "嚴重度", "欄位", "品項", "說明", "細節", "證據（文件/位置/原句）", "狀態", "覆核紀錄", "偵測方式"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F4858")
    for f in findings:
        ws.append([f.id, KIND.get(f.kind, f.kind), SEV.get(f.severity, f.severity), f.field, f.item, f.title,
                   f.detail, "\n".join(_ev_text(e) for e in f.evidence), STATUS.get(f.status, f.status),
                   _reviews(f, users), f.detector])
    for col, w in zip("ABCDEFGHIJK", (6, 10, 8, 14, 16, 50, 36, 70, 12, 30, 22)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    info = wb.create_sheet("專案資訊")
    for k, v in (("專案", project.name), ("機密等級", project.classification), ("最後檢核", str(project.last_check or "")),
                 ("說明", "本清單由 Deliverable Guard 產生，僅標示差異與證據，不自動修改文件、不作法律判斷。")):
        info.append([k, v])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def report_docx(project: Project, findings: list[Finding], users: dict[int, User], docs: list) -> bytes:
    from docx import Document
    from docx.shared import Pt

    d = Document()
    d.styles["Normal"].font.size = Pt(10.5)
    d.add_heading(f"跨文件一致性檢核報告：{project.name}", 0)
    lc = project.last_check or {}
    d.add_paragraph(f"檢核時間：{lc.get('at', '')}　文件數：{lc.get('documents', len(docs))}　"
                    f"事實數：{lc.get('facts', '')}　警示數：{len(findings)}")
    d.add_paragraph("本報告僅標示文件間的差異並附原文證據，不自動修改文件，亦不構成法律判斷；"
                    "所有警示須經承辦人確認。")
    d.add_heading("文件清單", 1)
    t = d.add_table(rows=1, cols=4)
    t.style = "Light Grid Accent 1"
    for c, h in zip(t.rows[0].cells, ("檔名", "類型", "版本", "是否最新版")):
        c.text = h
    for doc in docs:
        r = t.add_row().cells
        r[0].text, r[1].text, r[2].text, r[3].text = doc.filename, doc.doc_type, doc.version_label, "是" if doc.is_latest else "否"
    for status in ("confirmed", "disputed", "open", "dismissed"):
        group = [f for f in findings if f.status == status]
        if not group:
            continue
        d.add_heading(f"{STATUS[status]}（{len(group)}）", 1)
        for f in group:
            d.add_heading(f"#{f.id} [{KIND.get(f.kind)}/{SEV.get(f.severity)}] {f.title}", 2)
            d.add_paragraph(f.detail)
            for e in f.evidence:
                d.add_paragraph(_ev_text(e), style="List Bullet")
            if f.reviews:
                d.add_paragraph("覆核：" + _reviews(f, users))
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
