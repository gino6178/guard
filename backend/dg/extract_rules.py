"""Deterministic fact extraction: 'label：value' lines and item tables (品名/數量/單價/規格...).

Each fact carries the exact substring of its segment as the quote, so evidence is always verifiable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import normalize as N
from .fields import (FIELDS, ITEM_HEADERS, LINE_TOTAL_HEADERS, QTY_HEADERS, RESP_HEADERS, SPEC_HEADERS,
                     UNIT_PRICE_HEADERS)


@dataclass
class RawFact:
    seg_index: int
    field: str
    item: str
    value_raw: str
    value_norm: str
    unit: str
    quote: str
    source: str = "rule"
    confidence: float = 0.9


def normalize_value(field: str, raw: str, context: str = "") -> tuple[str, str] | None:
    """Return (value_norm, unit) or None when the value cannot be interpreted for that field."""
    kind = FIELDS[field].kind
    if kind == "amount":
        v = N.parse_amount(raw)
        if v is None:
            return None
        basis = N.tax_basis(raw) or N.tax_basis(context)
        return str(N.amount_to_taxed(v, basis) if field == "total_amount" else v), basis
    if kind == "date":
        iso = N.parse_date(raw)
        return (iso, "") if iso else None
    if kind == "quantity":
        q = N.parse_quantity(raw)
        return (f"{q[0]:g}", q[1]) if q else None
    if kind == "duration":
        m = N.parse_duration_months(raw)
        return (f"{m:g}", "月") if m is not None else None
    if kind == "org":
        v = N.norm_org(raw)
        return (v, "") if len(v) >= 2 else None
    if kind == "ref":
        return raw.strip(), ""
    v = N.norm_text(raw)
    return (v, "") if v else None


# Label-value pairs. Value runs until a separator (|, ；, 。, ，followed by another label) or end of text.
_SEP = r"(?:\s*\|\s*|；|;|。|$)"


def _label_regex(labels: tuple[str, ...]) -> re.Pattern:
    alts = "|".join(sorted((re.escape(l) for l in labels), key=len, reverse=True))
    return re.compile(rf"(?P<label>{alts})\s*(?:\((?:[^)]*)\)|（[^）]*）)?\s*[:：]\s*(?P<value>[^|；;。\n]+?){_SEP}")


_LABEL_RES = {k: _label_regex(f.labels) for k, f in FIELDS.items() if f.labels}

_VERSION_REF = re.compile(
    r"(?P<quote>(?:依據|依|參照|參考|根據|引用|詳見|如)\s*(?:附件[一二三四五六七八九十\d]*\s*)?[「『《]?(?P<doc>[^，。；\s「」『』《》]{0,12}?(?P<type>報價單|規格書|合約|契約|提案書|建議書|簡報|驗收清單|工作說明書))[」』》]?\s*(?:之|的)?\s*(?P<ver>(?:v|V|Rev|rev|√)\s?\d+(?:\.\d+)?|第\s*\d+\s*版|\d{1,2}(?=\s*(?:版|之|的))))")

_TYPE_WORD = {"報價單": "quotation", "規格書": "spec", "合約": "contract", "契約": "contract", "提案書": "proposal",
              "建議書": "proposal", "簡報": "slides", "驗收清單": "acceptance", "工作說明書": "sow"}


_TOTAL_ROW = re.compile(r"(未稅|含稅|稅前|稅後)?\s*(合計|總計|小計|總價|總金額)\s*[（(]?(未稅|含稅)?[)）]?|稅額|營業稅.*")


def _split_cells(text: str) -> dict[str, str]:
    cells = {}
    for part in text.split(" | "):
        if "：" in part:
            h, v = part.split("：", 1)
            cells[h.strip()] = v.strip()
    return cells


def _pick(cells: dict[str, str], headers: tuple[str, ...]) -> tuple[str, str] | None:
    for h in headers:
        if h in cells and cells[h]:
            return h, cells[h]
    for h in headers:  # tolerant: header contains the word, e.g. "單價(未稅)"
        for k, v in cells.items():
            if h in k and v:
                return k, v
    return None


def extract(segments: list[str]) -> list[RawFact]:
    facts: list[RawFact] = []
    for i, text in enumerate(segments):
        cells = _split_cells(text)
        item_cell = _pick(cells, ITEM_HEADERS) if len(cells) >= 2 else None
        if item_cell and _TOTAL_ROW.fullmatch(item_cell[1]):
            # totals row of an item table: only rows with an explicit tax basis are a total amount
            amt = _pick(cells, LINE_TOTAL_HEADERS)
            basis = N.tax_basis(item_cell[1])
            if amt and basis and "稅額" not in item_cell[1] and "營業稅" not in item_cell[1]:
                v = N.parse_amount(amt[1])
                if v is not None:
                    facts.append(RawFact(i, "total_amount", "", f"{amt[1]}（{basis}）", str(N.amount_to_taxed(v, basis)),
                                         basis, f"{item_cell[0]}：{item_cell[1]} | {amt[0]}：{amt[1]}"))
            continue
        if item_cell:
            facts.extend(_item_row(i, text, cells, item_cell))
            continue
        for field, rx in _LABEL_RES.items():
            for m in rx.finditer(text):
                val = m.group("value").strip()
                # a value that is itself another label line belongs to that other field
                if not val or len(val) > 80:
                    continue
                nv = normalize_value(field, val, m.group(0))
                if nv is None:
                    continue
                facts.append(RawFact(i, field, "", val, nv[0], nv[1], m.group(0).strip(" |；;。")))
        for m in _VERSION_REF.finditer(text):
            ver = re.sub(r"\s", "", m.group("ver")).lower().replace("rev", "v")
            vm = re.search(r"\d+(?:\.\d+)?", ver)
            ver = f"v{vm.group(0)}" if vm else ver
            dtype = _TYPE_WORD[m.group("type")]
            facts.append(RawFact(i, "version_ref", dtype, m.group("ver"), ver, "", m.group("quote").strip()))
    for f in facts:  # evidence guarantee: a quote is always a verbatim substring of its segment
        if f.quote not in segments[f.seg_index]:
            f.quote = segments[f.seg_index]
    return facts


def _item_row(i: int, text: str, cells: dict[str, str], item_cell: tuple[str, str]) -> list[RawFact]:
    out: list[RawFact] = []
    item = item_cell[1]
    item_quote = f"{item_cell[0]}：{item}"
    out.append(RawFact(i, "deliverable", item, item, N.norm_text(item), "", item_quote))
    for field, headers in (("quantity", QTY_HEADERS), ("unit_price", UNIT_PRICE_HEADERS),
                           ("line_total", LINE_TOTAL_HEADERS), ("spec", SPEC_HEADERS),
                           ("responsibility", RESP_HEADERS)):
        hit = _pick(cells, headers)
        if not hit:
            continue
        h, v = hit
        unit = cells.get("單位", "")
        nv = normalize_value(field, v + (unit if field == "quantity" and unit else ""), h)
        if nv is None:
            continue
        out.append(RawFact(i, field, item, v, nv[0], nv[1], f"{h}：{v}"))
    return out
