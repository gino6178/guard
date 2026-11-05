"""Document intake: read-only storage, parsing, de-identification, classification and versioning."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import DeidToken, Document, Project, Segment
from .deid import Deidentifier
from .parsing import parse_file
from .versioning import assign_groups, classify, detect_version
from .normalize import find_dates


def _store(project_id: int, sha: str, filename: str, data: bytes) -> Path:
    d = settings.files_dir / str(project_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{sha[:16]}{Path(filename).suffix.lower()}"
    if not p.exists():
        p.write_bytes(data)
        # originals are never modified by the system
        os.chmod(p, stat.S_IRUSR | stat.S_IRGRP)
    return p


def _deidentifier(s: Session, project_id: int) -> Deidentifier:
    rows = s.scalars(select(DeidToken).where(DeidToken.project_id == project_id))
    return Deidentifier({r.original: (r.token, r.kind) for r in rows})


def _save_tokens(s: Session, project_id: int, de: Deidentifier, before: set[str]) -> None:
    for orig, (tok, kind) in de.map.items():
        if orig not in before:
            s.add(DeidToken(project_id=project_id, token=tok, kind=kind, original=orig))


def ingest(s: Session, project: Project, filename: str, data: bytes, user_id: int,
           doc_type: str | None = None) -> Document:
    sha = hashlib.sha256(data).hexdigest()
    dup = s.scalar(select(Document).where(Document.project_id == project.id, Document.sha256 == sha))
    if dup:
        raise ValueError(f"相同內容的檔案已上傳過：{dup.filename}")
    parsed = parse_file(filename, data)
    path = _store(project.id, sha, filename, data)

    texts = [g.text for g in parsed.segments]
    if project.deid_enabled:
        de = _deidentifier(s, project.id)
        before = set(de.map)
        texts = [de.apply(t) for t in texts]
        _save_tokens(s, project.id, de, before)

    head = " ".join(texts[:8])
    dtype = doc_type or classify(filename, parsed.meta.get("title", ""), head, parsed.fmt)
    vlabel, vkey = detect_version(filename, texts, parsed.meta)
    doc_date = next((d for t in texts[:15] for d, _, _ in find_dates(t)), None)

    doc = Document(project_id=project.id, filename=filename, fmt=parsed.fmt, sha256=sha, size=len(data),
                   storage_path=str(path), doc_type=dtype, title=parsed.meta.get("title", "") or "",
                   version_label=vlabel, version_key=vkey, doc_date=doc_date, pages=parsed.pages,
                   ocr_pages=parsed.ocr_pages, parse_warnings=parsed.warnings, uploaded_by=user_id)
    s.add(doc)
    s.flush()
    for i, (g, t) in enumerate(zip(parsed.segments, texts)):
        s.add(Segment(doc_id=doc.id, seq=i, page=g.page, locator=g.locator, text=t, ocr=g.ocr))
    s.flush()
    regroup(s, project.id)
    return doc


def regroup(s: Session, project_id: int) -> None:
    docs = list(s.scalars(select(Document).where(Document.project_id == project_id)))
    assign_groups(docs)


def delete_document(s: Session, doc: Document) -> None:
    from .db import Fact
    s.query(Fact).filter(Fact.doc_id == doc.id).delete()
    p = Path(doc.storage_path)
    pid = doc.project_id
    s.delete(doc)
    s.flush()
    # remove the stored original only if no other document row references it
    if p.exists() and not s.scalar(select(Document.id).where(Document.storage_path == str(p))):
        os.chmod(p, stat.S_IWUSR | stat.S_IRUSR)
        p.unlink()
    regroup(s, pid)
