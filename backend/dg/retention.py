"""Retention: projects past retain_until are purged together with their stored originals."""
from __future__ import annotations

import os
import shutil
import stat

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .db import Approval, AuditLog, DeidToken, Fact, Finding, Project, utcnow


def purge_project(s: Session, p: Project) -> None:
    s.execute(delete(Fact).where(Fact.project_id == p.id))
    for f in s.scalars(select(Finding).where(Finding.project_id == p.id)):
        s.delete(f)
    s.execute(delete(DeidToken).where(DeidToken.project_id == p.id))
    for a in s.scalars(select(Approval).where(Approval.project_id == p.id)):
        s.delete(a)
    s.delete(p)
    d = settings.files_dir / str(p.id)
    if d.exists():
        for f in d.iterdir():
            os.chmod(f, stat.S_IWUSR | stat.S_IRUSR)
        shutil.rmtree(d)


def purge_expired(s: Session) -> int:
    now = utcnow()
    expired = [p for p in s.scalars(select(Project)) if p.retain_until.replace(tzinfo=now.tzinfo) < now]
    for p in expired:
        s.add(AuditLog(action="retention.expired", project_id=p.id, target=p.name))
        purge_project(s, p)
    s.commit()
    return len(expired)
