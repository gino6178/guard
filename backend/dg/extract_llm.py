"""LLM-assisted extraction, item-name canonicalisation and semantic equivalence judgement.

The model only proposes facts; every proposed quote is re-anchored to the source segment and
discarded if it cannot be found there, so no finding can rest on text the model invented.
"""
from __future__ import annotations

import asyncio
import json
import re

from rapidfuzz import fuzz

from .extract_rules import RawFact, normalize_value
from .fields import FIELDS
from .llm import LLM
from .normalize import norm_text

_FIELD_GUIDE = "\n".join(
    f"- {k}: {f.label}" + ("（需填 item=品項名稱）" if f.per_item else "")
    for k, f in FIELDS.items() if k != "version_ref"
)

EXTRACT_SYSTEM = f"""你是專案文件的事實抽取器。從使用者提供的文件段落中，抽出可用於跨文件比對的事實。
可用欄位：
{_FIELD_GUIDE}
規則：
1. 只抽取文件中明確寫出的事實，不推論、不補完、不計算。
2. quote 必須是該段落原文中「連續且逐字相同」的片段，需包含欄位名稱或足以辨識語境的文字，長度 4–80 字。
3. value 填原文中的值（金額保留原寫法與含稅/未稅字樣、日期保留原格式）。
4. 交付項目、數量、單價、規格、責任歸屬須填 item（品項或工作項目名稱，用文件中的稱呼）。
5. 規格(spec) 的 value 為該品項的規格描述；責任歸屬(responsibility) 的 value 為負責的一方。
6. 會議紀錄中「決議」「變更」的內容也要抽取；只是提問或討論而未決定的不要抽。
6a. total_amount 只抽整份文件／合約的總價；營業稅額、未含稅前的單項小計、單價都不是總金額。
7. 為節省篇幅，每筆事實以陣列輸出：[段落編號, "欄位", "item", "value", "quote"]。
輸出 JSON：{{"facts":[[12,"delivery_date","","2026/09/30","交付日期：2026/09/30"]]}}，沒有就輸出 {{"facts":[]}}。"""


_VERSION_ONLY = re.compile(r"^\s*(?:依|按|參照)?\s*(?:[一-鿿]{2,6}書|報價單|清單)?\s*(?:第\s*)?[vV](?:er\.?)?\s*\d+(?:\.\d+)?\s*(?:版)?\s*$")
_GENERIC_ITEM = re.compile(r"^(各項|各個|所有|全部|其他|其餘|上述|以上|本案|本專案|整體|相關)")

DATE_KEYWORDS = {
    "sign_date": ("簽約", "簽訂", "立約", "簽署"),
    "start_date": ("開始", "啟動", "開工", "起始"),
    "delivery_date": ("交付", "交貨", "交期", "完成", "上線", "結案", "履約"),
    "acceptance_date": ("驗收",),
    "quote_valid_until": ("有效",),
}


def _chunks(segs: list[tuple[int, str, str]], limit: int = 5000) -> list[list[tuple[int, str, str]]]:
    out, cur, size = [], [], 0
    for s in segs:
        if cur and size + len(s[2]) > limit:
            out.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += len(s[2]) + 12
    if cur:
        out.append(cur)
    return out


def anchor_quote(quote: str, text: str) -> str | None:
    """Return the exact substring of text matching quote, or None."""
    q = quote.strip().strip("「」\"'")
    if not q:
        return None
    if q in text:
        return q
    # tolerate whitespace and full-/half-width colon differences
    m = re.search(r"\s*".join(re.escape(c) if c not in "：:" else "[：:]" for c in re.sub(r"\s+", "", q)), text)
    if m:
        return m.group(0)
    al = fuzz.partial_ratio_alignment(q, text)
    if al and al.score >= 92 and (al.dest_end - al.dest_start) >= 4:
        return text[al.dest_start:al.dest_end]
    return None


async def extract_doc(llm: LLM, doc_label: str, segs: list[tuple[int, str, str]]) -> list[RawFact]:
    """segs: (index_in_doc, locator, text). Returns anchored facts with seg_index into the doc."""
    by_idx = {i: t for i, _, t in segs}

    async def run(chunk):  # noqa: ANN001
        body = "\n".join(f"[S{i}] ({loc}) {t}" for i, loc, t in chunk)
        data = await llm.chat_json(EXTRACT_SYSTEM, f"文件：{doc_label}\n段落：\n{body}", max_tokens=3000)
        return (data or {}).get("facts", []) if isinstance(data, dict) else []

    results = await asyncio.gather(*(run(c) for c in _chunks(segs)), return_exceptions=True)
    facts: list[RawFact] = []
    for res in results:
        if isinstance(res, BaseException):
            continue
        for f in res:
            if isinstance(f, list) and len(f) >= 5:
                f = dict(zip(("seg", "field", "item", "value", "quote"), f))
            if not isinstance(f, dict):
                continue
            try:
                seg = int(str(f.get("seg", "")).lstrip("S"))
                field = str(f.get("field", ""))
                value = str(f.get("value", "")).strip()
                item = str(f.get("item", "") or "").strip()
            except (ValueError, AttributeError):
                continue
            if field not in FIELDS or field == "version_ref" or seg not in by_idx or not value:
                continue
            if FIELDS[field].per_item and not item:
                continue
            quote = anchor_quote(str(f.get("quote", "")), by_idx[seg]) or anchor_quote(value, by_idx[seg])
            if not quote:
                continue  # unverifiable -> dropped
            if field == "total_amount" and re.search(r"營業稅|稅額|稅金", by_idx[seg]) and not re.search(r"總|合計", by_idx[seg]):
                continue  # a tax line is not a total
            if field == "spec" and _VERSION_ONLY.match(value):
                continue  # "依規格書 v2 執行" is a version reference, not a specification
            if FIELDS[field].per_item and _GENERIC_ITEM.match(item):
                continue  # "各項交付物" etc. refer to all items, not one
            if FIELDS[field].per_item and fuzz.partial_ratio(norm_text(item), norm_text(by_idx[seg])) < 90:
                continue  # an item attribute must come from a segment that names the item
            kws = DATE_KEYWORDS.get(field)
            if kws and not any(k in quote for k in kws):
                continue  # a date without its field keyword (e.g. the meeting date) is not that field
            nv = normalize_value(field, value, by_idx[seg])
            if nv is None:
                continue
            facts.append(RawFact(seg, field, item if FIELDS[field].per_item else "", value, nv[0], nv[1],
                                 quote, source="llm", confidence=0.8))
    return facts


CANON_SYSTEM = """你負責把不同文件中對同一個品項/工作項目的不同稱呼歸為一組。
只有確定指同一個東西才歸為同一組（例如「工業相機模組」與「工業用相機模組」）；
規格不同但名稱相同的品項仍屬同一組。不同的東西不可合併（例如「相機」與「鏡頭」）。
輸出 JSON：{"groups":[["名稱A","名稱B"],["名稱C"]]}，每個輸入名稱恰好出現一次。"""


def fuzzy_groups(names: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    for n in names:
        nn = norm_text(n)
        for g in groups:
            gn = norm_text(g[0])
            if nn == gn or (min(len(nn), len(gn)) >= 4 and (nn in gn or gn in nn)) or fuzz.ratio(nn, gn) >= 88:
                g.append(n)
                break
        else:
            groups.append([n])
    return groups


async def canonical_items(llm: LLM | None, names: list[str], docs_of: dict[str, set[int]] | None = None) -> dict[str, str]:
    """Map every item name to a canonical group name.

    names may repeat (one entry per fact); the most frequent spelling becomes the canonical name.
    docs_of: name -> documents listing it; two names listed in the same document are distinct items,
    so a model-proposed merge of such names is rejected.
    """
    freq: dict[str, int] = {}
    for n in names:
        freq[n] = freq.get(n, 0) + 1
    docs_of = docs_of or {}
    uniq = sorted(freq, key=lambda s: (-freq[s], len(s), s))

    def compatible(group: list[str]) -> bool:
        seen: set[int] = set()
        for n in group:
            d = docs_of.get(n, set())
            if seen & d:
                return False
            seen |= d
        return True

    groups = [g for fg in fuzzy_groups(uniq) for g in ([fg] if compatible(fg) else [[n] for n in fg])]
    if llm and len(groups) > 1:
        try:
            data = await llm.chat_json(CANON_SYSTEM, json.dumps([g[0] for g in groups], ensure_ascii=False), 2000)
            reps = {g[0]: g for g in groups}
            merged: list[list[str]] = []
            seen: set[str] = set()
            for grp in (data or {}).get("groups", []):
                members = [x for x in grp if x in reps and x not in seen]
                if not members:
                    continue
                cand = [m for x in members for m in reps[x]]
                if compatible(cand):
                    seen.update(members)
                    merged.append(cand)
            merged.extend(reps[r] for r in reps if r not in seen)
            groups = merged
        except Exception:  # noqa: BLE001 — fall back to fuzzy grouping
            pass
    out = {}
    for g in groups:
        canon = min(g, key=lambda s: (-freq.get(s, 0), len(s), s))
        for n in g:
            out[n] = canon
    return out


JUDGE_SYSTEM = """你是跨文件一致性審查員。每一題給你同一欄位在不同文件的寫法，請判斷它們是否互相矛盾。
- consistent：意思相同或可同時成立（同義改寫、單位換算後相同、一方較詳細但不衝突）。
- conflict：不可能同時成立（數值、等級、型號、負責方、條件不同）。
- unclear：資訊不足以判斷。
輸出 JSON：{"results":[{"id":題號,"verdict":"consistent|conflict|unclear","reason":"20字內理由"}]}"""


async def judge_pairs(llm: LLM, questions: list[dict]) -> dict[int, tuple[str, str]]:
    """questions: [{id, field_label, item, values:[{doc, value}]}] -> {id: (verdict, reason)}"""
    out: dict[int, tuple[str, str]] = {}

    async def run(batch):  # noqa: ANN001
        data = await llm.chat_json(JUDGE_SYSTEM, json.dumps(batch, ensure_ascii=False), 2000)
        for r in (data or {}).get("results", []):
            try:
                out[int(r["id"])] = (str(r.get("verdict", "unclear")), str(r.get("reason", "")))
            except (KeyError, ValueError, TypeError):
                continue

    batches = [questions[i:i + 12] for i in range(0, len(questions), 12)]
    await asyncio.gather(*(run(b) for b in batches), return_exceptions=True)
    return out


OCR_SYSTEM = """你是繁體中文 OCR 校正員。輸入為掃描文件逐行 OCR 結果（可能有漏字、錯字、簡體字），並附上本專案其他文件中出現過的詞彙。
請依上下文與詞彙表修正明顯的辨識錯誤，輸出繁體中文。嚴格規則：
1. 不可新增、刪除或改動任何數字、日期、金額、英文字母代號；不確定的字保持原樣。
2. 方括號代碼（如 [人名_1]）是去識別化標記，必須原樣保留。
3. 漏字時優先以詞彙表中的詞補全（例如「格書」→詞彙表有「規格書」則補為「規格書」）。
4. 不可合併或拆分行，行數必須相同。
5. 只輸出 JSON：{"lines":["校正後第1行","校正後第2行",...]}"""


def _digits(s: str) -> str:
    return "".join(re.findall(r"\d", s))


def _tokens(s: str) -> list[str]:
    return sorted(re.findall(r"\[[^\]]{1,12}_\d+\]", s))


async def correct_ocr(llm: LLM, lines: list[str], glossary: list[str] | None = None) -> list[str]:
    """Return corrected lines; a line whose digits or de-id placeholders changed keeps its OCR text."""
    out = list(lines)
    gl = "、".join(glossary or [])
    for start in range(0, len(lines), 40):
        batch = lines[start:start + 40]
        user = json.dumps({"glossary": gl, "lines": batch}, ensure_ascii=False)
        data = await llm.chat_json(OCR_SYSTEM, user, 4000)
        fixed = (data or {}).get("lines") if isinstance(data, dict) else None
        if not isinstance(fixed, list) or len(fixed) != len(batch):
            continue
        for i, (a, b) in enumerate(zip(batch, fixed)):
            if (isinstance(b, str) and b.strip() and _digits(a) == _digits(b) and _tokens(a) == _tokens(b)
                    and len(b) <= len(a) * 1.5 + 4):
                out[start + i] = b.strip()
    return out
