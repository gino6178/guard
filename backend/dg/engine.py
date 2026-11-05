"""Check pipeline: extract facts -> canonicalise items -> build fact master -> run rules + semantic judge.

Re-running a check preserves review decisions on findings whose fingerprint is unchanged.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import checks as C
from .db import Document, Fact, Finding, Project, Segment, utcnow
from .extract_llm import canonical_items, correct_ocr, extract_doc, judge_pairs
from .extract_rules import RawFact, extract
from .fields import FIELDS
from .llm import LLM, LLMUnavailable
from .normalize import norm_text
from .versioning import DOC_TYPE_LABELS

log = logging.getLogger(__name__)


def _merge(rule: list[RawFact], llm: list[RawFact]) -> list[RawFact]:
    """Rule facts win; LLM facts are added when they say something new (field/item/value not yet seen).

    Where a rule already read a field from a segment, the model's reading of that same segment is ignored.
    """
    seen = {(f.seg_index, f.field, norm_text(f.item), f.value_norm) for f in rule}
    seen_fv = {(f.field, norm_text(f.item), f.value_norm) for f in rule}
    ruled = {(f.seg_index, f.field) for f in rule}
    out = list(rule)
    for f in llm:
        key = (f.seg_index, f.field, norm_text(f.item), f.value_norm)
        if key in seen or (f.field, norm_text(f.item), f.value_norm) in seen_fv or (f.seg_index, f.field) in ruled:
            continue
        seen.add(key)
        out.append(f)
    return out


async def extract_facts(doc: Document, llm: LLM | None) -> list[RawFact]:
    segs = list(doc.segments)
    rule = extract([g.text for g in segs])
    llm_facts: list[RawFact] = []
    if llm:
        label = f"{doc.filename}（{DOC_TYPE_LABELS.get(doc.doc_type, doc.doc_type)}，{doc.version_label}）"
        try:
            llm_facts = await extract_doc(llm, label, [(i, g.locator, g.text) for i, g in enumerate(segs)])
        except LLMUnavailable:
            log.warning("LLM extraction failed for %s; using rule facts only", doc.filename)
    return _merge(rule, llm_facts)


def save_facts(s: Session, doc: Document, facts: list[RawFact], used_llm: bool) -> None:
    segs = list(doc.segments)
    s.execute(delete(Fact).where(Fact.doc_id == doc.id))
    for f in facts:
        seg = segs[f.seg_index]
        s.add(Fact(project_id=doc.project_id, doc_id=doc.id, segment_id=seg.id, field=f.field, item=f.item,
                   value_raw=f.value_raw, value_norm=f.value_norm, unit=f.unit, quote=f.quote,
                   source=f.source, confidence=f.confidence))
    doc.status = "extracted" if used_llm else "extracted_rules"


def _glossary(docs: list[Document]) -> list[str]:
    """Vocabulary from the project's machine-readable documents, used to repair OCR text."""
    words: dict[str, None] = {}
    for d in docs:
        if d.ocr_pages:
            continue
        for f in extract([g.text for g in d.segments]):
            if f.field in ("deliverable", "project_name", "client_name", "vendor_name"):
                words[f.value_raw if f.field != "deliverable" else f.item] = None
    words.update(dict.fromkeys(DOC_TYPE_LABELS.values()))
    words.update(dict.fromkeys(["決議事項", "工作項目", "負責單位", "交付日期", "驗收", "確認", "會議"]))
    return list(words)[:200]


async def correct_ocr_segments(docs: list[Document], llm: LLM) -> None:
    pending = [d for d in docs if d.ocr_pages and not d.ocr_corrected]
    if not pending:
        return
    glossary = _glossary(docs)
    for d in pending:
        segs = [g for g in d.segments if g.ocr]
        try:
            fixed = await correct_ocr(llm, [g.text for g in segs], glossary)
        except LLMUnavailable:
            continue
        n = 0
        for g, t in zip(segs, fixed):
            if t != g.text:
                g.raw_text, g.text = g.text, t
                n += 1
        d.ocr_corrected = True
        d.status = "parsed"  # re-extract from corrected text
        d.parse_warnings = [*(d.parse_warnings or []), f"已依專案詞彙校正 {n} 行 OCR 文字（數字不變），原始辨識結果可對照"]


async def run_check(s: Session, project: Project, llm: LLM | None, force: bool = False) -> dict:
    t0 = time.perf_counter()
    run_id = uuid.uuid4().hex[:12]
    docs = list(s.scalars(select(Document).where(Document.project_id == project.id)))
    if llm and not await llm.health():
        llm = None
    # 1. extraction (cached per document unless forced or the cached result was rules-only and LLM is up)
    if llm:
        await correct_ocr_segments(docs, llm)
    todo = [d for d in docs if force or (llm and d.status != "extracted")
            or not s.scalar(select(Fact.id).where(Fact.doc_id == d.id).limit(1))]
    # LLM calls for all documents run concurrently (bounded by the client's semaphore)
    results = await asyncio.gather(*(extract_facts(d, llm) for d in todo))
    for d, facts in zip(todo, results):
        save_facts(s, d, facts, bool(llm))
    n_extracted = len(todo)
    s.flush()
    t_extract = time.perf_counter() - t0

    # 2. join facts with documents & segments
    rows = s.execute(select(Fact, Segment).join(Segment, Fact.segment_id == Segment.id)
                     .where(Fact.project_id == project.id)).all()
    infos = {d.id: C.DocInfo(d.id, d.filename, d.doc_type, d.version_label, list(d.version_key or []),
                             d.is_latest, d.version_group) for d in docs}
    names = [f.item for f, _ in rows if f.item and FIELDS[f.field].per_item and f.field != "version_ref"]
    docs_of: dict[str, set[int]] = defaultdict(set)
    for f, _ in rows:
        if f.field == "deliverable":
            docs_of[f.item].add(f.doc_id)
    canon = await canonical_items(llm, names, docs_of) if names else {}
    fvs = [C.FV(f.id, infos[f.doc_id], f.field, canon.get(f.item, f.item) if f.field != "version_ref" else f.item,
                f.item, f.value_raw, f.value_norm, f.unit, f.quote, g.page, g.locator, g.text, f.source)
           for f, g in rows]
    latest = [f for f in fvs if f.doc.is_latest]
    older = [f for f in fvs if not f.doc.is_latest]

    # 3. rules
    drafts: list[C.Draft] = []
    drafts += C.check_values(latest, older)
    drafts += C.check_capital_amounts(latest)
    drafts += C.check_arithmetic(latest)
    drafts += C.check_omissions(latest)
    drafts += C.check_versions(latest, list(infos.values()))
    drafts += C.check_dates(latest)

    # 4. semantic judgement for text values the rules could not decide
    pending = [d for d in drafts if d.needs_judge]
    if pending:
        if llm:
            qs = [{"id": i, **d.needs_judge} for i, d in enumerate(pending)]
            try:
                verdicts = await judge_pairs(llm, qs)
            except LLMUnavailable:
                verdicts = {}
            for i, d in enumerate(pending):
                verdict, reason = verdicts.get(i, ("unclear", ""))
                if verdict == "consistent":
                    drafts.remove(d)
                else:
                    d.detail = f"語意比對判定：{'矛盾' if verdict == 'conflict' else '無法確定，請人工確認'}。{reason}"
                    if verdict != "conflict":
                        d.severity = "low"
        else:
            for d in pending:
                d.severity = "low"
                d.detail += "（語意模型未連線，以文字差異列出，請人工確認）"

    # 5. persist with review carry-over
    drafts = _dedupe(drafts)
    existing = {f.fingerprint: f for f in s.scalars(select(Finding).where(Finding.project_id == project.id))}
    keep = set()
    for d in drafts:
        fp = d.fingerprint()
        keep.add(fp)
        if fp in existing:
            f = existing[fp]
            f.run_id, f.title, f.detail, f.evidence, f.severity = run_id, d.title, d.detail, d.evidence, d.severity
        else:
            s.add(Finding(project_id=project.id, run_id=run_id, kind=d.kind, severity=d.severity, field=d.field,
                          item=d.item, title=d.title, detail=d.detail, evidence=d.evidence, detector=d.detector,
                          fingerprint=fp))
    for fp, f in existing.items():
        if fp not in keep:
            s.delete(f)
    summary = {
        "run_id": run_id, "at": utcnow().isoformat(), "llm": bool(llm), "documents": len(docs),
        "extracted": n_extracted, "facts": len(fvs), "findings": len(drafts),
        "by_kind": {k: sum(1 for d in drafts if d.kind == k) for k in ("contradiction", "omission", "outdated")},
        "seconds": round(time.perf_counter() - t0, 2), "extract_seconds": round(t_extract, 2),
        "llm_calls": llm.calls if llm else 0,
    }
    project.last_check = summary
    s.commit()
    return summary


def _dedupe(drafts: list[C.Draft]) -> list[C.Draft]:
    out, seen = [], set()
    for d in drafts:
        fp = d.fingerprint()
        if fp not in seen:
            seen.add(fp)
            out.append(d)
    return out


def fact_master(s: Session, project_id: int) -> list[dict]:
    """Fact master table: one row per field(+item), one cell per document, with the reference value."""
    rows = s.execute(select(Fact, Document, Segment).join(Document, Fact.doc_id == Document.id)
                     .join(Segment, Fact.segment_id == Segment.id).where(Fact.project_id == project_id)).all()
    names = [f.item for f, _, _ in rows if f.item and f.field != "version_ref"]
    from .extract_llm import fuzzy_groups  # local import keeps module import light
    canon = {n: min(g, key=len) for g in fuzzy_groups(sorted(set(names))) for n in g}
    table: dict[tuple[str, str], dict] = {}
    for f, d, g in rows:
        if f.field == "version_ref":
            continue
        item = canon.get(f.item, f.item)
        key = (f.field, item)
        row = table.setdefault(key, {"field": f.field, "label": FIELDS[f.field].label, "item": item,
                                     "values": defaultdict(list), "reference": None})
        row["values"][d.id].append({"value": f.value_raw, "norm": f.value_norm, "quote": f.quote, "page": g.page,
                                    "locator": g.locator, "source": f.source, "latest": d.is_latest})
    docs = {d.id: d for d in s.scalars(select(Document).where(Document.project_id == project_id))}
    out = []
    order = list(FIELDS)
    for (fld, item), row in sorted(table.items(), key=lambda kv: (order.index(kv[0][0]), kv[0][1])):
        latest_docs = [i for i in row["values"] if docs[i].is_latest]
        if latest_docs:
            best = min(latest_docs, key=lambda i: C.AUTHORITY.index(docs[i].doc_type)
                       if docs[i].doc_type in C.AUTHORITY else 99)
            v = row["values"][best][0]
            row["reference"] = {"doc_id": best, "value": v["value"]}
        distinct = {v["norm"] for i in latest_docs for v in row["values"][i]}
        row["consistent"] = len(distinct) <= 1
        row["values"] = {str(k): v for k, v in row["values"].items()}
        out.append(row)
    return out
