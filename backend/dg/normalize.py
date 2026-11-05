"""Value normalisation: amounts (incl. 中文大寫), dates (incl. 民國), quantities, durations, names."""
from __future__ import annotations

import re
from datetime import date

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "貳": 2, "兩": 2, "三": 3, "參": 3, "叁": 3,
              "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陸": 6, "七": 7, "柒": 7, "八": 8, "捌": 8,
              "九": 9, "玖": 9}
_CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CN_BIG = {"萬": 10_000, "億": 100_000_000}
CN_NUM_CHARS = "".join(_CN_DIGITS) + "".join(_CN_UNITS) + "".join(_CN_BIG)


def cn_to_int(s: str) -> int | None:
    s = s.strip()
    if not s or any(c not in CN_NUM_CHARS for c in s):
        return None
    total, section, num = 0, 0, 0
    for c in s:
        if c in _CN_DIGITS:
            num = _CN_DIGITS[c]
        elif c in _CN_UNITS:
            section += (num or 1) * _CN_UNITS[c]
            num = 0
        else:
            section += num
            total += (section or 1) * _CN_BIG[c]
            section, num = 0, 0
    return total + section + num


_AMOUNT = re.compile(
    r"(?:NT\$|NTD|新[臺台]幣|台幣|\$)?\s*([0-9][0-9,]*(?:\.\d+)?)\s*(億|萬|千)?\s*(?:元|NTD)?")


def parse_amount(s: str) -> int | None:
    """'NT$1,250,000' / '125萬元' / '新台幣壹佰貳拾伍萬元整' -> 1250000."""
    t = s.replace("，", ",").replace(" ", "")
    m = re.search(f"[{CN_NUM_CHARS}]{{2,}}", t)
    if m and not re.search(r"\d", t[: m.start()]):
        v = cn_to_int(m.group(0))
        if v is not None and v >= 100:
            return v
    m = _AMOUNT.search(t)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    mult = {"億": 100_000_000, "萬": 10_000, "千": 1_000}.get(m.group(2) or "", 1)
    return int(round(num * mult))


def tax_basis(s: str) -> str:
    if re.search(r"未稅|不含稅|稅前|未含稅", s):
        return "未稅"
    if re.search(r"含稅|含營業稅|稅後", s):
        return "含稅"
    return ""


VAT = 0.05


def amount_to_taxed(v: int, basis: str) -> int:
    return int(round(v * (1 + VAT))) if basis == "未稅" else v


_DATE_PATTERNS = [
    re.compile(r"(?:民國\s*)?(\d{2,4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
    re.compile(r"(?<!\d)(\d{2,4})[/.\-](\d{1,2})[/.\-](\d{1,2})(?!\d)"),
]


def parse_date(s: str) -> str | None:
    """Return ISO yyyy-mm-dd; 3-digit or explicit 民國 years are ROC years."""
    for pat in _DATE_PATTERNS:
        m = pat.search(s)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            if y < 1911:
                y += 1911
            try:
                return date(y, mo, d).isoformat()
            except ValueError:
                return None
    return None


def find_dates(s: str) -> list[tuple[str, int, int]]:
    out = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(s):
            iso = parse_date(m.group(0))
            if iso:
                out.append((iso, m.start(), m.end()))
    return out


def parse_quantity(s: str) -> tuple[float, str] | None:
    m = re.search(r"([0-9][0-9,]*(?:\.\d+)?)\s*(台|臺|組|套|個|件|式|批|支|片|顆|人月|小時|份|座|張|只|pcs|PCS|set|sets)?", s)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v, (m.group(2) or "").replace("臺", "台")


def parse_duration_months(s: str) -> float | None:
    m = re.search(r"([0-9]+(?:\.\d+)?|[" + CN_NUM_CHARS + r"]+)\s*(年|個月|月|週|天|日)", s)
    if not m:
        return None
    raw = m.group(1)
    v = float(raw) if raw[0].isdigit() else float(cn_to_int(raw) or 0)
    return {"年": v * 12, "個月": v, "月": v, "週": v / 4.345, "天": v / 30, "日": v / 30}[m.group(2)]


_ORG_SUFFIX = re.compile(r"(股份有限公司|有限公司|公司|股份|Co\.,?\s*Ltd\.?|Inc\.?|Corp\.?)$", re.I)


def norm_name(s: str) -> str:
    s = re.sub(r"\s+", "", s)
    s = s.replace("臺", "台").replace("（", "(").replace("）", ")")
    s = re.sub(r"\(.*?\)", "", s)
    return s.strip("：:，,。；; ")


def norm_org(s: str) -> str:
    return _ORG_SUFFIX.sub("", norm_name(s))


def norm_text(s: str) -> str:
    s = s.replace("臺", "台").replace("（", "(").replace("）", ")").replace("：", ":")
    s = re.sub(r"\s+", "", s)
    return s.lower()


def fmt_amount(v: int) -> str:
    return f"NT${v:,}"
