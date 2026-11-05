"""De-identification of personal data before text is stored for analysis or sent to the model.

Company names, amounts and dates are business facts under check and are kept; personal identifiers
(ID numbers, phones, e-mails, bank accounts, names of contact persons) are replaced with stable
per-project placeholders. The placeholder -> original mapping is stored separately (admin only).
"""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("身分證", re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?!\d)")),
    ("Email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("手機", re.compile(r"(?<!\d)09\d{2}[- ]?\d{3}[- ]?\d{3}(?!\d)")),
    ("電話", re.compile(r"(?<!\d)\(?0\d{1,2}\)?[- ]?\d{3,4}[- ]?\d{4}(?:\s*(?:#|分機)\s*\d+)?(?!\d)")),
    ("帳號", re.compile(r"(?:帳號|帳戶)\s*[:：]?\s*(\d[\d-]{8,}\d)")),
]
_PERSON = re.compile(
    r"(?P<label>聯絡人|承辦人|經辦人|聯絡窗口|窗口|代表人|負責人|專案經理|專案負責人|簽約代表|紀錄|記錄|主席|出席人員|與會人員)"
    r"\s*[:：]\s*(?P<names>(?:[一-鿿]{2,4}(?:\s*(?:先生|小姐|經理|主任|博士|副理|協理))?[、,，\s]*)+)")
_TITLE = re.compile(r"(先生|小姐|經理|主任|博士|副理|協理)$")
_NOT_NAMES = {"甲方", "乙方", "雙方", "客戶", "廠商", "本公司", "公司", "先生", "小姐", "經理", "主任", "博士", "副理", "協理"}


class Deidentifier:
    def __init__(self, existing: dict[str, tuple[str, str]] | None = None):
        # original -> (token, kind)
        self.map: dict[str, tuple[str, str]] = dict(existing or {})
        self.counts: dict[str, int] = {}
        for tok, kind in self.map.values():
            self.counts[kind] = max(self.counts.get(kind, 0), int(tok.rsplit("_", 1)[1].rstrip("]")))

    def _token(self, original: str, kind: str) -> str:
        if original not in self.map:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.map[original] = (f"[{kind}_{self.counts[kind]}]", kind)
        return self.map[original][0]

    def apply(self, text: str) -> str:
        for kind, pat in PATTERNS:
            if pat.groups:
                text = pat.sub(lambda m, k=kind: m.group(0).replace(m.group(1), self._token(m.group(1), k)), text)
            else:
                text = pat.sub(lambda m, k=kind: self._token(m.group(0), k), text)

        def mask_name(n: str) -> str:
            core = _TITLE.sub("", n)
            if len(core) < 2 or core in _NOT_NAMES or core.endswith(("公司", "單位", "部", "處", "組")):
                return n
            return self._token(core, "人名") + n[len(core):]

        def person(m: re.Match) -> str:
            names = re.sub(r"[一-鿿]+", lambda n: mask_name(n.group(0)), m.group("names"))
            return m.group(0).replace(m.group("names"), names)

        text = _PERSON.sub(person, text)
        # names seen before are masked wherever they appear later (e.g. in action items)
        for orig, (tok, kind) in self.map.items():
            if kind == "人名" and orig in text:
                text = text.replace(orig, tok)
        return text
