"""Multi-format parsing into citable segments (DOCX / PDF / XLSX / PPTX, with OCR for scanned PDF pages).

Every segment carries a page number (DOCX: counted from explicit/rendered page breaks; XLSX: sheet index;
PPTX: slide number) and a human-readable locator so each finding can point back to its source.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SUPPORTED = {".docx": "docx", ".pdf": "pdf", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pptx": "pptx"}


@dataclass
class Seg:
    page: int | None
    locator: str
    text: str
    ocr: bool = False


@dataclass
class Parsed:
    fmt: str
    segments: list[Seg] = field(default_factory=list)
    pages: int = 0
    ocr_pages: int = 0
    meta: dict = field(default_factory=dict)  # title, revision, modified, created
    warnings: list[str] = field(default_factory=list)


def _clean(s: str) -> str:
    s = s.replace("　", " ").replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _row_text(headers: list[str], cells: list[str]) -> str:
    """Render a table row; label cells with their header so the row is self-describing."""
    parts = []
    for i, c in enumerate(cells):
        if not c:
            continue
        h = headers[i] if i < len(headers) else ""
        parts.append(f"{h}：{c}" if h and h != c else c)
    return " | ".join(parts)


def _dedupe_cells(cells: list[str]) -> list[str]:
    # merged cells repeat their text in python-docx/pptx; keep the first occurrence of a run
    out: list[str] = []
    for c in cells:
        if out and c == out[-1] and c:
            out.append("")
        else:
            out.append(c)
    return out


# ---------------------------------------------------------------- DOCX
def parse_docx(data: bytes) -> Parsed:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    p = Parsed("docx")
    cp = doc.core_properties
    p.meta = {"title": cp.title or "", "revision": cp.revision, "modified": cp.modified, "created": cp.created}

    page, para_no, table_no = 1, 0, 0

    def breaks_in(el) -> int:  # noqa: ANN001
        n = 0
        for br in el.iter(qn("w:br")):
            if br.get(qn("w:type")) == "page":
                n += 1
        n += len(list(el.iter(qn("w:lastRenderedPageBreak"))))
        if el.find(f"{qn('w:pPr')}/{qn('w:pageBreakBefore')}") is not None:
            n += 1
        return n

    for el in doc.element.body.iterchildren():
        if el.tag == qn("w:p"):
            para = Paragraph(el, doc)
            # page breaks before this paragraph's text start a new page for it
            page += breaks_in(el)
            text = _clean(para.text)
            if text:
                para_no += 1
                p.segments.append(Seg(page, f"第{page}頁 第{para_no}段", text))
        elif el.tag == qn("w:tbl"):
            table_no += 1
            tbl = Table(el, doc)
            headers: list[str] = []
            for r, row in enumerate(tbl.rows):
                cells = _dedupe_cells([_clean(c.text) for c in row.cells])
                if r == 0:
                    headers = cells
                text = " | ".join(c for c in cells if c) if r == 0 else _row_text(headers, cells)
                if text:
                    p.segments.append(Seg(page, f"第{page}頁 表{table_no} 第{r + 1}列", text))
        elif el.tag == qn("w:sectPr"):
            continue
    p.pages = page
    return p


# ---------------------------------------------------------------- PDF
_ocr_engine = None


def _ocr(png: bytes) -> list[tuple[float, str]]:
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        from .config import settings
        if settings.ocr_rec_model and Path(settings.ocr_rec_model).exists():
            # fine-tuned Traditional-Chinese recogniser (see infra/ocr-train)
            _ocr_engine = RapidOCR(rec_model_path=settings.ocr_rec_model, rec_keys_path=settings.ocr_rec_keys)
        else:
            _ocr_engine = RapidOCR()
    result, _ = _ocr_engine(png)
    # result: [[box, text, score], ...]; return (top_y, text) for line grouping
    return [(min(pt[1] for pt in box), txt) for box, txt, score in (result or []) if float(score) > 0.5]


# a line starting like this begins a new statement even if the previous line reached the margin
_NEW_LINE = re.compile(r"^\s*(?:[^\s：:|，。]{1,8}[：:]|第.{1,3}[條章節項]|[一二三四五六七八九十]+、|\d+[.、]|[•·\-])")


def parse_pdf(data: bytes) -> Parsed:
    import pymupdf as fitz

    p = Parsed("pdf")
    doc = fitz.open(stream=data, filetype="pdf")
    md = doc.metadata or {}
    p.meta = {"title": md.get("title", ""), "modified": _pdf_date(md.get("modDate")),
              "created": _pdf_date(md.get("creationDate")), "revision": None}
    p.pages = doc.page_count
    for pno, page in enumerate(doc, start=1):
        blocks = [b for b in page.get_text("blocks") if b[6] == 0]
        text_len = sum(len(b[4].strip()) for b in blocks)
        if text_len < 20 and (page.get_images() or text_len == 0):
            pix = page.get_pixmap(dpi=300)
            lines = _ocr(pix.tobytes("png"))
            if not lines:
                p.warnings.append(f"第{pno}頁無可辨識文字")
                continue
            p.ocr_pages += 1
            for i, txt in enumerate(_merge_ocr_lines(lines), start=1):
                p.segments.append(Seg(pno, f"第{pno}頁 OCR第{i}行", _clean(ocr_cleanup(txt)), ocr=True))
            continue
        # one segment per visual line; a line that runs to the right margin continues on the next line
        n, buf, prev_full = 0, "", False
        right = page.rect.width * 0.78
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                t = "".join(sp["text"] for sp in line["spans"])
                if not t.strip():
                    continue
                if buf and prev_full and (buf.rstrip().endswith("|") or not _NEW_LINE.match(t)):
                    buf += t
                else:
                    if buf.strip():
                        n += 1
                        p.segments.append(Seg(pno, f"第{pno}頁 第{n}行", _clean(buf)))
                    buf = t
                prev_full = line["bbox"][2] >= right
        if buf.strip():
            n += 1
            p.segments.append(Seg(pno, f"第{pno}頁 第{n}行", _clean(buf)))
    if p.ocr_pages:
        p.warnings.append(f"{p.ocr_pages} 頁以 OCR 辨識，請留意辨識誤差")
    return p


_s2t = None


def ocr_cleanup(t: str) -> str:
    """Fix systematic OCR confusions: simplified glyphs, table bars, 〇/O inside numbers."""
    global _s2t
    if _s2t is None:
        from opencc import OpenCC
        _s2t = OpenCC("s2tw")
    t = _s2t.convert(t)
    t = re.sub(r"\s*[丨｜|]\s*", " | ", t)
    prev = None
    while prev != t:  # 〇/O touching digits or thousands separators are zeros: 1,2〇〇 -> 1,200
        prev, t = t, re.sub(r"(?<=[\d,])[〇oO]|[〇oO](?=[\d,])", "0", t)
    t = re.sub(r"(?<=\d)[lI](?=\d)", "1", t)
    t = t.replace("：:", "：").replace(":", "：")
    return t


def _merge_ocr_lines(lines: list[tuple[float, str]], tol: float = 12) -> list[str]:
    lines.sort(key=lambda t: t[0])
    out: list[list] = []
    for y, t in lines:
        if out and abs(out[-1][0] - y) < tol:
            out[-1][1] += " " + t
        else:
            out.append([y, t])
    return [t for _, t in out]


def _pdf_date(s: str | None) -> datetime | None:
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", s or "")
    if not m:
        return None
    y, mo, d, h, mi = (int(x) if x else 0 for x in m.groups())
    return datetime(y, mo, d, h, mi)


# ---------------------------------------------------------------- XLSX
def parse_xlsx(data: bytes) -> Parsed:
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=False)
    p = Parsed("xlsx")
    pr = wb.properties
    p.meta = {"title": pr.title or "", "modified": pr.modified, "created": pr.created, "revision": pr.revision}
    for sidx, ws in enumerate(wb.worksheets, start=1):
        headers: list[str] = []
        for row in ws.iter_rows():
            cells = [_fmt_cell(c.value) for c in row]
            if not any(cells):
                continue
            r = row[0].row
            last = max(i for i, c in enumerate(cells) if c) + 1
            loc = f"工作表「{ws.title}」{get_column_letter(1)}{r}:{get_column_letter(last)}{r}"
            # first row with >= 3 non-empty short cells is treated as the header row
            if not headers and sum(1 for c in cells if c) >= 3 and all(len(c) < 20 for c in cells if c):
                headers = cells
                p.segments.append(Seg(sidx, loc, " | ".join(c for c in cells if c)))
                continue
            filled = [i for i, c in enumerate(cells) if c]
            if len(filled) == 2 and filled[1] == filled[0] + 1 and len(cells[filled[0]]) <= 12:
                # "label | value" pair in adjacent cells (header block above or below a table)
                text = f"{cells[filled[0]].rstrip('：:')}：{cells[filled[1]]}"
            else:
                text = _row_text(headers, cells) if headers else " | ".join(c for c in cells if c)
            p.segments.append(Seg(sidx, loc, text))
    p.pages = len(wb.worksheets)
    return p


def _fmt_cell(v) -> str:  # noqa: ANN001
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return _clean(str(v))


# ---------------------------------------------------------------- PPTX
def parse_pptx(data: bytes) -> Parsed:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    p = Parsed("pptx")
    cp = prs.core_properties
    p.meta = {"title": cp.title or "", "revision": cp.revision, "modified": cp.modified, "created": cp.created}
    for sno, slide in enumerate(prs.slides, start=1):
        n = 0
        for shape in _iter_shapes(slide.shapes):
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = _clean("".join(r.text for r in para.runs))
                    if text:
                        n += 1
                        p.segments.append(Seg(sno, f"第{sno}張投影片 第{n}段", text))
            if getattr(shape, "has_table", False) and shape.has_table:
                headers: list[str] = []
                for r, row in enumerate(shape.table.rows):
                    cells = _dedupe_cells([_clean(c.text) for c in row.cells])
                    if r == 0:
                        headers = cells
                    text = " | ".join(c for c in cells if c) if r == 0 else _row_text(headers, cells)
                    if text:
                        p.segments.append(Seg(sno, f"第{sno}張投影片 表格第{r + 1}列", text))
        if slide.has_notes_slide:
            notes = _clean(slide.notes_slide.notes_text_frame.text)
            if notes:
                p.segments.append(Seg(sno, f"第{sno}張投影片 備忘稿", notes))
    p.pages = len(prs.slides)
    return p


def _iter_shapes(shapes):  # noqa: ANN001
    for s in shapes:
        if s.shape_type == 6:  # group
            yield from _iter_shapes(s.shapes)
        else:
            yield s


PARSERS = {"docx": parse_docx, "pdf": parse_pdf, "xlsx": parse_xlsx, "pptx": parse_pptx}


def parse_file(filename: str, data: bytes) -> Parsed:
    fmt = SUPPORTED.get(Path(filename).suffix.lower())
    if not fmt:
        raise ValueError(f"不支援的檔案格式：{filename}")
    return PARSERS[fmt](data)
