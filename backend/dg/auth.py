"""Local accounts, roles and clearance-based access control."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .db import AuditLog, Project, User, get_session, utcnow

# capability -> roles allowed
PERMS = {
    "project.create": {"admin", "handler"},
    "doc.upload": {"admin", "handler"},
    "doc.delete": {"admin", "handler"},
    "check.run": {"admin", "handler"},
    "finding.review": {"admin", "handler", "reviewer"},
    "export": {"admin", "handler", "reviewer", "manager", "legal"},
    "approval.submit": {"admin", "handler"},
    "workflow.manage": {"admin"},
    "user.manage": {"admin"},
    "audit.read": {"admin"},
    "retention.manage": {"admin"},
    "deid.reveal": {"admin"},
}


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(pw, bytes.fromhex(salt)).split("$")[2], dk)


def make_token(user: User) -> str:
    payload = {"sub": str(user.id), "role": user.role, "exp": utcnow() + timedelta(hours=settings.token_hours)}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def db() -> Session:
    s = get_session()
    try:
        yield s
    finally:
        s.close()


def current_user(request: Request, s: Session = Depends(db)) -> User:
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("token", "")
    if not token:
        raise HTTPException(401, "未登入")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "登入已失效")
    user = s.get(User, int(payload["sub"]))
    if not user or not user.active:
        raise HTTPException(401, "帳號無效")
    return user


def require(user: User, perm: str) -> None:
    if user.role not in PERMS[perm]:
        raise HTTPException(403, "權限不足")


def project_for(s: Session, user: User, project_id: int) -> Project:
    p = s.get(Project, project_id)
    if not p or p.classification > user.clearance:
        # do not reveal existence of projects above the user's clearance
        raise HTTPException(404, "找不到專案")
    return p


def audit(s: Session, user: User | None, action: str, project_id: int | None = None, target: str = "",
          **detail) -> None:
    s.add(AuditLog(user_id=user.id if user else None, username=user.username if user else "",
                   action=action, project_id=project_id, target=target, detail=detail))
