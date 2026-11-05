"""Consistency rules over the fact master. Produces findings, each with source evidence.

Finding kinds: contradiction (直接矛盾), omission (遺漏), outdated (疑似過期/引用舊版).
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field

from . import normalize as N
from .fields import AUTHORITY, ENUMERATING_TYPES, FIELDS
from .versioning import DOC_TYPE_LABELS


@dataclass
class DocInfo:
    id: int
    filename: str
    doc_type: str
    version_label: str
    version_key: list
    is_latest: bool
    version_group: str


@dataclass
class FV:
    """A fact joined with its document and segment, as seen by the checks."""
    id: int
    doc: DocInfo
    field: str
    item: str  # canonical item
    item_raw: str
    value_raw: str
    value_norm: str
    unit: str
    quote: str
    page: int | None
    locator: str
    seg_text: str
    source: str


@dataclass
class Draft:
    kind: str
    severity: str
    field: str
    item: str
    title: str
    detail: str
    evidence: list[dict]
    detector: str
    needs_judge: dict | None = None  # semantic check pending LLM verdict
    meta: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        docs = sorted({e["doc_id"] for e in self.evidence})
        raw = f"{self.kind}|{self.field}|{self.item}|{docs}|{self.detector}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


def ev(f: FV, note: str = "") -> dict:
    return {"doc_id": f.doc.id, "filename": f.doc.filename, "doc_type": DOC_TYPE_LABELS.get(f.doc.doc_type, f.doc.doc_type),
            "version": f.doc.version_label, "page": f.page, "locator": f.locator, "quote": f.quote,
            "text": f.seg_text, "value": f.value_raw, "note": note}


def _auth_rank(d: DocInfo) -> int:
    return AUTHORITY.index(d.doc_type) if d.doc_type in AUTHORITY else len(AUTHORITY)


def fmt_value(field: str, v: str, unit: str = "") -> str:
    kind = FIELDS[field].kind
    if kind == "amount":
        return N.fmt_amount(int(float(v))) + ("（含稅）" if field == "total_amount" else "")
    if kind == "duration":
        return f"{float(v):g} 個月"
    if kind == "quantity":
        return f"{float(v):g}{unit}"
    return v


def _equal(field: str, a: FV, b: FV) -> bool | None:
    """True/False when decidable by rules; None when semantic judgement is needed."""
    kind = FIELDS[field].kind
    if a.value_norm == b.value_norm:
        return True
    if kind in ("amount", "date", "duration", "org"):
        return False
    if kind == "quantity":
        return float(a.value_norm) == float(b.value_norm)
    x, y = (re.sub(r"(?<=\d),(?=\d{3})", "", v.value_norm) for v in (a, b))
    if x == y or (min(len(x), len(y)) >= 4 and (x in y or y in x)):
        return True
    # numbers with the same unit that differ are a definite conflict (e.g. 500萬畫素 vs 300萬畫素)
    nx = dict((u, v) for v, u in re.findall(r"(\d+(?:\.\d+)?)\s*([a-z%一-鿿]{1,4})", x))
    ny = dict((u, v) for v, u in re.findall(r"(\d+(?:\.\d+)?)\s*([a-z%一-鿿]{1,4})", y))
    if any(u in ny and float(nx[u]) != float(ny[u]) for u in nx):
        return False
    return None


def _cluster(field: str, facts: list[FV]) -> list[list[FV]]:
    """Group facts whose values are rule-equal."""
    clusters: list[list[FV]] = []
    for f in facts:
        for c in clusters:
            if _equal(field, c[0], f) is True:
                c.append(f)
                break
        else:
            clusters.append([f])
    return clusters


def check_values(latest: list[FV], older: list[FV]) -> list[Draft]:
    """Cross-document value comparison for single-valued and per-item fields."""
    drafts: list[Draft] = []
    groups: dict[tuple[str, str], list[FV]] = defaultdict(list)
    for f in latest:
        if f.field in ("deliverable", "version_ref"):
            continue
        groups[(f.field, f.item)].append(f)
    old_by_key: dict[tuple[str, str], list[FV]] = defaultdict(list)
    for f in older:
        old_by_key[(f.field, f.item)].append(f)
    latest_by_group: dict[tuple[str, str, str], list[FV]] = defaultdict(list)
    for f in latest:
        latest_by_group[(f.field, f.item, f.doc.version_group)].append(f)

    for (fld, item), facts in groups.items():
        if len({f.doc.id for f in facts}) < 2:
            continue
        clusters = _cluster(fld, facts)
        if len(clusters) < 2:
            continue
        clusters.sort(key=lambda c: (min(_auth_rank(f.doc) for f in c), -len(c)))
        ref = clusters[0]
        fdef = FIELDS[fld]
        label = fdef.label + (f"（{item}）" if item else "")
        for other in clusters[1:]:
            a, b = ref[0], other[0]
            evidence = [ev(x) for x in _one_per_doc(ref)] + [ev(x) for x in _one_per_doc(other)]
            rule_eq = _equal(fld, a, b)
            title = f"{label}不一致：{_docs(ref)} 為「{_short(a, fld)}」，{_docs(other)} 為「{_short(b, fld)}」"
            # stale: the deviating value equals an older version of an authoritative document
            # stale: another document repeats a value that its source changed in a newer version
            stale = []
            for side, other_side in ((other, ref), (ref, other)):
                for o in old_by_key.get((fld, item), []):
                    newer = latest_by_group.get((fld, item, o.doc.version_group), [])
                    if (newer and any(_equal(fld, o, n) is False for n in newer)
                            and any(_equal(fld, o, x) is True and x.doc.version_group != o.doc.version_group for x in side)):
                        stale.append((o, newer[0], [x for x in side if _equal(fld, o, x) is True]))
                if stale:
                    break
            if stale:
                o, n, users = stale[0]
                drafts.append(Draft(
                    "outdated", "high" if fdef.severity == "high" else "medium", fld, item,
                    f"{_docs(users)} 的{label}疑似沿用舊版：與 {o.doc.filename}（{o.doc.version_label}）相同，"
                    f"但 {n.doc.filename}（{n.doc.version_label}）已改為「{_short(n, fld)}」",
                    "差異值與舊版文件一致，可能未隨版本更新。",
                    [ev(x) for x in _one_per_doc(users)] + [ev(n, "最新版"), ev(o, "舊版來源")], "rule:stale_value"))
                continue
            d = Draft("contradiction", fdef.severity, fld, item, title,
                      f"同一{label}在不同文件的記載不同。", evidence, "rule:value_mismatch")
            if rule_eq is None:
                d.detector = "semantic:value_mismatch"
                d.needs_judge = {"field_label": label, "item": item,
                                 "values": [{"doc": x.doc.filename, "value": x.value_raw} for x in (a, b)]}
            drafts.append(d)
    return drafts


def check_capital_amounts(latest: list[FV]) -> list[Draft]:
    """Arabic amount vs 中文大寫 written side by side in the same sentence."""
    drafts = []
    seen = set()
    for f in latest:
        if FIELDS[f.field].kind != "amount" or (f.doc.id, f.seg_text) in seen:
            continue
        seen.add((f.doc.id, f.seg_text))
        t = f.seg_text.replace(",", "")
        for m in re.finditer(r"(\d{4,})\s*元?\s*[（(]\s*(?:新[臺台]幣)?\s*([" + N.CN_NUM_CHARS + r"]{2,})\s*元", t):
            a, c = int(m.group(1)), N.cn_to_int(m.group(2))
            if c is not None and a != c:
                drafts.append(Draft("contradiction", "high", f.field, f.item,
                                    f"{f.doc.filename} 金額大小寫不符：{N.fmt_amount(a)} vs 大寫 {N.fmt_amount(c)}",
                                    "同一句中阿拉伯數字與中文大寫金額不一致。", [ev(f)], "rule:capital_amount"))
    return drafts


def check_arithmetic(latest: list[FV]) -> list[Draft]:
    drafts = []
    by_doc: dict[int, list[FV]] = defaultdict(list)
    for f in latest:
        by_doc[f.doc.id].append(f)
    for facts in by_doc.values():
        rows: dict[str, dict[str, FV]] = defaultdict(dict)
        for f in facts:
            if f.field in ("quantity", "unit_price", "line_total") and f.source == "rule":
                rows[f.item].setdefault(f.field, f)
        line_sum = 0
        for item, r in rows.items():
            if {"quantity", "unit_price"} <= r.keys():
                # a wrong line total is reported once below; the sum uses quantity x unit price
                line_sum += int(round(float(r["quantity"].value_norm) * int(r["unit_price"].value_norm)))
            elif "line_total" in r:
                line_sum += int(r["line_total"].value_norm)
            if {"quantity", "unit_price", "line_total"} <= r.keys():
                q, u, t = float(r["quantity"].value_norm), int(r["unit_price"].value_norm), int(r["line_total"].value_norm)
                if abs(q * u - t) > 1:
                    drafts.append(Draft("contradiction", "high", "line_total", item,
                                        f"{r['line_total'].doc.filename}「{item}」小計錯誤：{q:g} × {N.fmt_amount(u)} ≠ {N.fmt_amount(t)}",
                                        f"數量乘以單價應為 {N.fmt_amount(int(q * u))}。", [ev(r["line_total"])], "rule:arithmetic"))
        totals = [f for f in facts if f.field == "total_amount"]
        if line_sum and totals:
            ok = False
            for t in totals:
                raw = N.parse_amount(t.value_raw) or 0
                if t.unit == "未稅":
                    ok |= abs(raw - line_sum) <= 1
                elif t.unit == "含稅":
                    ok |= abs(raw - N.amount_to_taxed(line_sum, "未稅")) <= 1
                else:
                    ok |= abs(raw - line_sum) <= 1 or abs(raw - N.amount_to_taxed(line_sum, "未稅")) <= 1
            if not ok:
                t = totals[0]
                drafts.append(Draft("contradiction", "high", "total_amount", "",
                                    f"{t.doc.filename} 明細加總 {N.fmt_amount(line_sum)}（未稅）與總金額「{t.value_raw}」不符",
                                    "各項小計加總（含/未稅換算後）與總金額不一致。", [ev(t)], "rule:arithmetic_total"))
    return drafts


def check_omissions(latest: list[FV]) -> list[Draft]:
    items_by_doc: dict[int, dict[str, FV]] = defaultdict(dict)
    docs: dict[int, DocInfo] = {}
    for f in latest:
        if f.field == "deliverable" and f.doc.doc_type in ENUMERATING_TYPES:
            items_by_doc[f.doc.id].setdefault(f.item, f)
            docs[f.doc.id] = f.doc
    enumerating = {d: its for d, its in items_by_doc.items() if len(its) >= 2}
    if len(enumerating) < 2:
        return []
    drafts = []
    all_items = {i for its in enumerating.values() for i in its}
    for item in sorted(all_items):
        have = [d for d, its in enumerating.items() if item in its]
        missing = [d for d in enumerating if d not in have]
        if not missing or not have:
            continue
        holders = [enumerating[d][item] for d in have]
        names = "、".join(docs[d].filename for d in missing)
        evidence = [ev(h) for h in holders] + [
            {"doc_id": d, "filename": docs[d].filename, "doc_type": DOC_TYPE_LABELS.get(docs[d].doc_type, ""),
             "version": docs[d].version_label, "page": None, "locator": "全文", "quote": "", "text": "",
             "value": "", "note": "未列此項"} for d in missing]
        drafts.append(Draft("omission", "medium", "deliverable", item,
                            f"交付項目「{item}」出現在 {_docs(holders)}，但 {names} 未列出",
                            "列舉交付項目的文件之間項目不一致，可能遺漏或範圍變更未同步。", evidence, "rule:omission"))
    return drafts


def check_versions(latest: list[FV], docs: list[DocInfo]) -> list[Draft]:
    """A document cites a version of another document that is not the latest one."""
    drafts = []
    latest_by_type: dict[str, DocInfo] = {}
    for d in docs:
        if d.is_latest and (d.doc_type not in latest_by_type or d.version_key > latest_by_type[d.doc_type].version_key):
            latest_by_type[d.doc_type] = d
    for f in latest:
        if f.field != "version_ref":
            continue
        target = latest_by_type.get(f.item)
        if not target or target.id == f.doc.id:
            continue
        cited = re.findall(r"\d+", f.value_norm)
        cur = target.version_key[:2] if target.version_key else []
        if not cited or not cur or cur[0] == 0:
            continue
        cited_key = [int(cited[0]), int(cited[1]) if len(cited) > 1 else 0]
        if cited_key != cur:
            drafts.append(Draft("outdated", "medium", "version_ref", f.item,
                                f"{f.doc.filename} 引用 {DOC_TYPE_LABELS.get(f.item, f.item)} {f.value_raw}，但最新版為 {target.version_label}（{target.filename}）",
                                "引用的版本非最新版，內容可能已變更。",
                                [ev(f), {"doc_id": target.id, "filename": target.filename,
                                         "doc_type": DOC_TYPE_LABELS.get(target.doc_type, ""), "version": target.version_label,
                                         "page": None, "locator": "文件版本", "quote": "", "text": "", "value": target.version_label,
                                         "note": "最新版"}], "rule:version_ref"))
    return drafts


def check_dates(latest: list[FV]) -> list[Draft]:
    """Date logic: quote expiry vs signing, delivery before signing / start."""
    drafts = []
    first: dict[str, FV] = {}
    for f in sorted(latest, key=lambda f: _auth_rank(f.doc)):
        if FIELDS[f.field].kind == "date":
            first.setdefault(f.field, f)
    q, s, dl, st = (first.get(k) for k in ("quote_valid_until", "sign_date", "delivery_date", "start_date"))
    if q and s and q.value_norm < s.value_norm:
        drafts.append(Draft("outdated", "medium", "quote_valid_until", "",
                            f"報價有效期限 {q.value_norm} 早於簽約日期 {s.value_norm}，簽約時報價已過期",
                            "合約所依據之報價已逾有效期限，價格條件可能需重新確認。", [ev(q), ev(s)], "rule:quote_expired"))
    for early, late, msg in ((s, dl, "交付日期早於簽約日期"), (st, dl, "交付日期早於開始日期")):
        if early and late and late.value_norm < early.value_norm:
            drafts.append(Draft("contradiction", "high", late.field, "",
                                f"{msg}：{late.value_norm} < {early.value_norm}", "日期先後順序不合理。",
                                [ev(late), ev(early)], "rule:date_order"))
    return drafts


def _one_per_doc(facts: list[FV]) -> list[FV]:
    seen, out = set(), []
    for f in facts:
        if f.doc.id not in seen:
            seen.add(f.doc.id)
            out.append(f)
    return out


def _docs(facts: list[FV]) -> str:
    return "、".join(dict.fromkeys(f.doc.filename for f in facts))


def _short(f: FV, fld: str) -> str:
    try:
        return fmt_value(fld, f.value_norm, f.unit) if FIELDS[fld].kind in ("amount", "duration", "quantity") else f.value_raw
    except ValueError:
        return f.value_raw
