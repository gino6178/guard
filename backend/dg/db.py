"""Persistence layer: SQLAlchemy models for projects, documents, facts, findings and audit."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


# Classification levels; a user may see a project only if clearance >= classification.
CLASSIFICATIONS = {0: "公開", 1: "內部", 2: "機密", 3: "極機密"}
ROLES = ("admin", "handler", "reviewer", "manager", "legal")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16))
    clearance: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    scenario: Mapped[str] = mapped_column(String(32))  # sales | rnd
    classification: Mapped[int] = mapped_column(Integer, default=1)
    deid_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_check: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    docs_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    documents: Mapped[list["Document"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    filename: Mapped[str] = mapped_column(String(512))
    fmt: Mapped[str] = mapped_column(String(8))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(1024))
    doc_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(512), default="")
    version_label: Mapped[str] = mapped_column(String(64), default="")
    version_key: Mapped[list[Any]] = mapped_column(JSON, default=list)
    version_group: Mapped[str] = mapped_column(String(256), default="")
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)
    doc_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    ocr_pages: Mapped[int] = mapped_column(Integer, default=0)
    ocr_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    parse_warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="parsed")
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    project: Mapped[Project] = relationship(back_populates="documents")
    segments: Mapped[list["Segment"]] = relationship(cascade="all, delete-orphan", order_by="Segment.seq")


class Segment(Base):
    """A citable unit of text: a paragraph, table row, slide shape, sheet row or PDF line block."""
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    seq: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    locator: Mapped[str] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text)
    ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # uncorrected OCR output


class Fact(Base):
    __tablename__ = "facts"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    doc_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"))
    field: Mapped[str] = mapped_column(String(64))
    item: Mapped[str] = mapped_column(String(256), default="")
    value_raw: Mapped[str] = mapped_column(Text)
    value_norm: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32), default="")
    quote: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))  # rule | llm
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    run_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # contradiction | omission | outdated
    severity: Mapped[str] = mapped_column(String(8))  # high | medium | low
    field: Mapped[str] = mapped_column(String(64))
    item: Mapped[str] = mapped_column(String(256), default="")
    title: Mapped[str] = mapped_column(String(512))
    detail: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[Any]] = mapped_column(JSON)
    detector: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|confirmed|dismissed|disputed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviews: Mapped[list["Review"]] = relationship(cascade="all, delete-orphan", order_by="Review.id")


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(16))  # confirm | dismiss
    final: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeidToken(Base):
    """Mapping from a de-identification placeholder to the original value (admin-only)."""
    __tablename__ = "deid_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    token: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    original: Mapped[str] = mapped_column(Text)


class WorkflowTemplate(Base):
    """A sign-off flow: ordered nodes, each with approvers and an optional condition."""
    __tablename__ = "workflow_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    scenario: Mapped[str] = mapped_column(String(32), default="")  # "" = any scenario
    # [{"name", "assignee_type": "role"|"users", "role", "users": [ids], "condition": {"type", "value"}}]
    nodes: Mapped[list[Any]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    """One submission of a project's deliverable set for sign-off, frozen as a snapshot."""
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    template_id: Mapped[int] = mapped_column(ForeignKey("workflow_templates.id"))
    template_name: Mapped[str] = mapped_column(String(128))
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="in_progress")  # in_progress|approved|rejected|withdrawn|invalidated
    status_reason: Mapped[str] = mapped_column(Text, default="")
    nodes: Mapped[list[Any]] = mapped_column(JSON)  # resolved nodes incl. skipped flag and reason
    current: Mapped[int] = mapped_column(Integer, default=0)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    steps: Mapped[list["ApprovalStep"]] = relationship(cascade="all, delete-orphan", order_by="ApprovalStep.id")


class ApprovalStep(Base):
    __tablename__ = "approval_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id"))
    node_index: Mapped[int] = mapped_column(Integer)
    node_name: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(16))  # approve | reject | comment
    comment: Mapped[str] = mapped_column(Text, default="")
    signature: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target: Mapped[str] = mapped_column(String(256), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


engine = None
SessionLocal: sessionmaker[Session] | None = None


def init_db(url: str | None = None) -> None:
    global engine, SessionLocal
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.files_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url or settings.db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):  # noqa: ANN001
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    _add_missing_columns()
    SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_session() -> Session:
    assert SessionLocal is not None, "init_db() not called"
    return SessionLocal()


def _add_missing_columns() -> None:
    """Lightweight migration: add columns introduced after a database was created (all nullable)."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = col.type.compile(dialect=engine.dialect)
                    default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                    dflt = f" DEFAULT {int(default) if isinstance(default, bool) else repr(default)}" if default is not None else ""
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}{dflt}'))
