"""Document type classification and version identification.

Versions are inferred from (in order of strength) the filename, an explicit "版本/版次" line in the
content, and the file's revision / modified metadata. Documents of the same type with similar base
names form a version group; only the latest of each group takes part in cross-document comparison,
while older versions are kept to detect stale references.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

DOC_TYPES: list[tuple[str, str, tuple[str, ...]]] = [
    # (key, label, keywords) — first match wins, so specific types come first
    ("minutes", "會議紀錄", ("會議紀錄", "會議記錄", "minutes", "會議")),
    ("acceptance", "驗收清單", ("驗收", "acceptance")),
    ("quotation", "報價單", ("報價", "估價", "quotation", "quote")),
    ("contract", "合約", ("合約", "契約", "contract", "協議書")),
    ("spec", "規格書", ("規格", "spec", "需求說明", "技術說明")),
    ("slides", "簡報", ("簡報", "slides", "presentation", "說明會")),
    ("proposal", "提案書", ("提案", "建議書", "proposal", "企劃")),
    ("sow", "工作說明書", ("工作說明", "sow", "statement of work")),
]
DOC_TYPE_LABELS = {k: label for k, label, _ in DOC_TYPES} | {"other": "其他"}

_V_PATTERNS = [
    re.compile(r"(?i)(?:^|[^a-z])v(?:er(?:sion)?)?[\s._-]?(\d+)(?:[._](\d{1,2})(?!\d))?"),
    re.compile(r"(?i)rev(?:ision)?[\s._-]?(\d+)(?:[._](\d+))?"),
    re.compile(r"第\s*(\d+)\s*版"),
    re.compile(r"修訂\s*(\d+)"),
    re.compile(r"(?i)(?:^|[^a-z])r(\d+)(?![a-z0-9])"),
]
_FINAL = re.compile(r"(?i)final|定稿|正式版|簽署版|簽約版")
_DRAFT = re.compile(r"(?i)draft|初稿|草案|草稿")
_DATE_IN_NAME = re.compile(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})")
_CONTENT_VERSION = re.compile(r"(?:版本|版次|文件版本|Version)\s*[:：]?\s*((?:v|V|Rev|rev)?\s*\d+(?:\.\d+)?)")


def classify(filename: str, title: str, head_text: str, fmt: str) -> str:
    hay_name = f"{Path(filename).stem} {title}".lower()
    for key, _, kws in DOC_TYPES:
        if any(k.lower() in hay_name for k in kws):
            return key
    head = head_text[:400].lower()
    for key, _, kws in DOC_TYPES:
        if any(k.lower() in head for k in kws):
            return key
    return "slides" if fmt == "pptx" else "other"


def detect_version(filename: str, segments_text: list[str], meta: dict) -> tuple[str, list]:
    """Return (label, sortable key). Key = [major, minor, final_flag, yyyymmdd, revision]."""
    stem = Path(filename).stem
    label, major, minor = "", 0, 0
    for pat in _V_PATTERNS:
        m = pat.search(stem)
        if m:
            major = int(m.group(1))
            minor = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else 0
            label = f"v{major}.{minor}" if minor else f"v{major}"
            break
    if not label:
        for t in segments_text[:30]:
            m = _CONTENT_VERSION.search(t)
            if m:
                nums = re.findall(r"\d+", m.group(1))
                major = int(nums[0])
                minor = int(nums[1]) if len(nums) > 1 else 0
                label = f"v{major}.{minor}" if minor else f"v{major}"
                break
    final = 1 if _FINAL.search(stem) else (-1 if _DRAFT.search(stem) else 0)
    if final == 1:
        label = (label + " 定稿").strip()
    elif final == -1:
        label = (label + " 草稿").strip()
    dm = _DATE_IN_NAME.search(stem)
    date_num = int("".join(dm.groups())) if dm else 0
    mod = meta.get("modified")
    if not date_num and isinstance(mod, datetime):
        date_num = int(mod.strftime("%Y%m%d"))
    rev = meta.get("revision")
    rev_num = int(rev) if isinstance(rev, int) or (isinstance(rev, str) and rev.isdigit()) else 0
    return label or "未標示", [major, minor, final, date_num, rev_num]


def base_name(filename: str) -> str:
    s = Path(filename).stem
    s = _DATE_IN_NAME.sub("", s)
    for pat in _V_PATTERNS:
        s = pat.sub("", s)
    s = _FINAL.sub("", s)
    s = _DRAFT.sub("", s)
    return re.sub(r"[\s._\-()（）\[\]]+", "", s)


def assign_groups(docs: list) -> None:
    """Set version_group and is_latest on a project's documents (mutates ORM objects)."""
    groups: list[tuple[str, str, list]] = []  # (doc_type, base, members)
    for d in docs:
        b = base_name(d.filename)
        for g in groups:
            if g[0] == d.doc_type and fuzz.ratio(g[1], b) >= 70:
                g[2].append(d)
                break
        else:
            groups.append((d.doc_type, b, [d]))
    for dtype, b, members in groups:
        members.sort(key=lambda d: (list(d.version_key or []), d.uploaded_at.timestamp() if d.uploaded_at else 0))
        gname = f"{dtype}:{b}"
        for i, d in enumerate(members):
            d.version_group = gname
            d.is_latest = i == len(members) - 1
