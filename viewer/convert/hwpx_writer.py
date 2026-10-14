# -*- coding: utf-8 -*-
"""한글 HWPX 쓰기 (형식 변환 SOT §1, 261014-14) — python-hwpx(Apache-2.0, 고정 판 의존성 §4.2).

- 편집 가능: 쪽마다 문단(이은 줄)·표·그림을 읽는 차례로. 제목 줄은 '개요 1'. 쪽 사이는 쪽 나눔.
- 모양 그대로(배치 쓰기): 쪽마다 구역 하나(쪽 크기 = PDF 쪽, 여백 0). 원본 줄마다 문단 — 왼쪽 여백·위 간격·글자 크기·굵기·
  자간을 원본에 맞춘다. 그림·표는 쪽에 띄워 원본 자리에(글의 흐름을 밀지 않는다).
단위는 HWPUNIT(1 pt = 100).
"""
from __future__ import annotations

from pathlib import Path

from viewer.convert import layout

HWPUNIT_PER_PT = 100
TITLE_STYLE = "개요 1"     # 한글 기본 스타일 이름(문서 안의 스타일 키 — 화면 문구가 아니다)
EDIT_TEXT_W_PT = 425       # 기본 쪽(A4, 좌우 여백 30 mm)의 글 너비 — 편집 가능의 그림을 이 너비에 맞춘다
LINE_PCT = 100             # 모양 그대로의 줄 간격(%) — 줄 높이 = 글자 크기 × LINE_PCT / 100
SPACING_MIN, SPACING_MAX = -50, 50      # 한글 자간 범위(%)
ANCHOR_PT = 1.0            # 띄운 그림·표를 붙든 문단(쪽의 첫 문단)의 글자 크기 — 줄 높이를 거의 차지하지 않게
GAP_SPACES_MAX = 60        # 나란한 줄 사이를 벌리는 빈칸 수 상한


def _u(pt: float) -> int:
    return max(1, int(round(pt * HWPUNIT_PER_PT)))


def _u0(pt: float) -> int:
    return max(0, int(round(pt * HWPUNIT_PER_PT)))


def _pic(doc, val, sec=None, **kw):
    """그림 블록 → python-hwpx 그림. jpg·png 가 아니면 PNG 로."""
    data, fmt = val["data"], val["fmt"]
    if fmt not in ("png", "jpg"):
        data, fmt = _to_png(data), "png"
        if data is None:
            return None
    x0, y0, x1, y1 = val["rect"]
    return data, fmt, (x1 - x0), (y1 - y0)


def _to_png(data: bytes):
    """jpg·png 가 아닌 그림(jpx·jbig2 …)은 PNG 로 — 한글이 받는 형식으로."""
    try:
        import fitz
        return fitz.Pixmap(data).tobytes("png")
    except Exception:
        return None


def _fill_table(t, rows) -> None:
    for ri, r in enumerate(rows):
        for ci, c in enumerate(r):
            if c:
                t.set_cell_text(ri, ci, str(c))


# ---- 편집 가능 -------------------------------------------------------------
def write_hwpx_edit(ps, pages, dst: Path, tick) -> None:
    from hwpx import HwpxDocument
    doc = HwpxDocument.new()
    for i, pg in enumerate(pages):
        tick(i, len(pages), f"p.{pg + 1}")
        first_on_page = i > 0
        for b in layout.page_blocks(ps, pg, join=True):
            brk = {"pageBreak": "1"} if first_on_page else {}
            if b["kind"] == "line":
                if b.get("style") == "title":
                    try:
                        doc.add_paragraph(b["text"], style=TITLE_STYLE, **brk)
                    except Exception:
                        doc.add_paragraph(b["text"], **brk)
                else:
                    doc.add_paragraph(b["text"], **brk)
            elif b["kind"] == "table":
                if brk:
                    doc.add_paragraph("", **brk)
                rows = b["rows"]
                _fill_table(doc.add_table(len(rows), max(len(r) for r in rows)), rows)
            else:
                got = _pic(doc, b)
                if got is None:
                    continue
                data, fmt, w, h = got
                if w > EDIT_TEXT_W_PT:                    # 글 너비를 넘으면 비율대로 줄인다
                    w, h = EDIT_TEXT_W_PT, h * EDIT_TEXT_W_PT / w
                if brk:
                    doc.add_paragraph("", **brk)
                doc.add_picture(data, fmt, width=_u(w), height=_u(h))
            first_on_page = False
        if first_on_page:                       # 빈 쪽이어도 쪽은 나눈다
            doc.add_paragraph("", pageBreak="1")
    tick(len(pages), len(pages), "")
    doc.save_to_path(str(dst))


# ---- 모양 그대로(배치 쓰기) ---------------------------------------------------
class _Styles:
    """문단·글자 속성 id 를 만들고 되쓴다(같은 값이면 같은 id)."""

    def __init__(self, doc):
        self.doc = doc
        self.hdr = doc.parts.headers[0]
        # 바탕 문단 속성: 왼쪽 맞춤, 줄 간격 LINE_PCT, 격자 맞춤 끔, 줄 나눔 없음(넘치면 자간을 줄여 한 줄 — SQUEEZE).
        # next=1 은 기본 서식과 똑같아져 그것을 고쳐 버리지 않게 하는 표시(0.01 pt)
        self.base = self.hdr.ensure_paragraph_format(
            alignment="LEFT", line_spacing_percent=LINE_PCT,
            margins={"intent": 0, "left": 0, "right": 0, "prev": 0, "next": 1})
        el = self._para_el(self.base)
        if el is not None:
            el.set("snapToGrid", "0")
            for e in el.iter():
                if e.tag.endswith("}breakSetting"):
                    e.set("lineWrap", "SQUEEZE")
                    e.set("widowOrphan", "0")
        self._base_el = el
        self._parent = self.hdr._para_properties_element(create=True)
        self._next = 1 + max((int(e.get("id")) for e in self._parent if str(e.get("id", "")).isdigit()), default=0)
        self._para = {}
        self._run = {}

    def _para_el(self, pid):
        for e in self.hdr.element.iter():
            if e.tag.endswith("}paraPr") and e.get("id") == str(pid):
                return e
        return None

    def para(self, left_pt: float, prev_pt: float) -> str:
        key = (_u0(left_pt) // 50 * 50, _u0(prev_pt) // 10 * 10)
        if key not in self._para:
            # 바탕을 복제해 직접 붙인다 — python-hwpx 의 `ensure_paragraph_format` 은 만들 때마다 있는 것 전부와
            # 구조를 비교해(같은 것 되쓰기) 줄이 많은 문서에서 O(n²)이다(실측 10쪽 4.3초). 같은 값은 위 사전이 되쓴다.
            from copy import deepcopy
            el = deepcopy(self._base_el)
            self.hdr._apply_paragraph_margins(el, {"left": key[0], "prev": key[1]})
            pid = str(self._next)
            self._next += 1
            el.set("id", pid)
            self._parent.append(el)
            self._para[key] = pid
        return self._para[key]

    def finish(self) -> None:
        self.hdr._update_item_count(self._parent, self._base_el.tag)
        self.hdr.mark_dirty()

    def run(self, size: float, spacing: int, bold: bool, serif: bool) -> str:
        key = (round(size * 2) / 2, int(spacing), bool(bold), bool(serif))
        if key not in self._run:
            self._run[key] = self.doc.styles.ensure_run(
                size=key[0], letter_spacing=key[1], bold=key[2],
                font=layout.SERIF_FACE if key[3] else layout.SANS_FACE)
        return self._run[key]


def _float(el, x_pt: float, y_pt: float) -> None:
    """그림·표를 쪽(종이) 기준 자리에 띄운다 — 글 앞으로, 글의 흐름을 밀지 않는다."""
    el.set("textWrap", "IN_FRONT_OF_TEXT")
    for e in el:
        if e.tag.endswith("}pos"):
            e.set("treatAsChar", "0")
            e.set("affectLSpacing", "0")
            e.set("flowWithText", "0")
            e.set("allowOverlap", "1")
            e.set("vertRelTo", "PAPER")
            e.set("horzRelTo", "PAPER")
            e.set("vertAlign", "TOP")
            e.set("horzAlign", "LEFT")
            e.set("vertOffset", str(_u0(y_pt)))
            e.set("horzOffset", str(_u0(x_pt)))
            break


def _bands(lines) -> list:
    """같은 높이에 나란히 놓인 줄을 한 묶음으로(2단·칸 맞춤). 위에서 아래 차례."""
    pos = sorted((b for b in lines if b.get("rect")), key=lambda b: ((b["rect"][1] + b["rect"][3]) / 2, b["rect"][0]))
    bands = []
    for b in pos:
        cy = (b["rect"][1] + b["rect"][3]) / 2
        if bands:
            last = bands[-1]
            lcy = (last[0]["rect"][1] + last[0]["rect"][3]) / 2
            tol = 0.4 * min(b["size"], last[0]["size"])
            if abs(cy - lcy) <= tol and all(b["rect"][0] >= q["rect"][2] - 1 or b["rect"][2] <= q["rect"][0] + 1 for q in last):
                last.append(b)
                continue
        bands.append([b])
    for band in bands:
        band.sort(key=lambda q: q["rect"][0])
    return bands


def _band_text(band):
    """묶음 → (글, 왼쪽 x, 원본 너비, 크기, 굵음, 세리프). 사이 빈 곳은 빈칸으로."""
    size = max(q["size"] for q in band)
    serif = band[0]["serif"]
    text = band[0]["text"]
    for prev, q in zip(band, band[1:]):
        gap = q["rect"][0] - prev["rect"][2]
        sp = layout.measure(" ", size, serif) or size * 0.3
        text += " " * max(1, min(GAP_SPACES_MAX, int(round(gap / max(0.5, sp))))) + q["text"]
    bold = sum(len(q["text"]) for q in band if q["bold"]) * 2 >= sum(len(q["text"]) for q in band)
    return text, band[0]["rect"][0], band[-1]["rect"][2] - band[0]["rect"][0], size, bold, serif


def _spacing(text: str, width: float, size: float, serif: bool) -> int:
    """원본 줄 너비에 맞춘 자간(%) — (원본 너비 − 잰 너비) ÷ 글자 수 ÷ 크기. 못 재면 0."""
    n = len(text)
    m = layout.measure(text, size, serif)
    if m is None or n < 2 or width <= 0:
        return 0
    sp = (width - m) / n / size * 100.0
    return int(max(SPACING_MIN, min(SPACING_MAX, round(sp))))


def write_hwpx_shape(ps, pages, dst: Path, tick) -> None:
    from hwpx import HwpxDocument
    doc = HwpxDocument.new()
    st = _Styles(doc)
    anchor_para = st.para(0, 0)
    anchor_run = st.run(ANCHOR_PT, 0, False, True)
    for i, pg in enumerate(pages):
        tick(i, len(pages), f"p.{pg + 1}")
        page = ps.doc.load_page(int(pg))
        w, h = page.rect.width, page.rect.height
        sec = doc.sections[0] if i == 0 else doc.add_section()
        doc.page.set_size(width=_u(w), height=_u(h), section=sec)
        doc.page.set_margins(left=0, right=0, top=0, bottom=0, header=0, footer=0, gutter=0, section=sec)
        # 구역의 첫 문단(구역 설정을 든 것)이 그림·표를 붙든다 — 글자를 아주 작게 해 줄 높이를 거의 차지하지 않게
        head = sec.paragraphs[0]
        head.element.set("paraPrIDRef", str(anchor_para))
        for r in head.element:
            if r.tag.endswith("}run"):
                r.set("charPrIDRef", str(anchor_run))
        cur = ANCHOR_PT * LINE_PCT / 100.0
        blocks = layout.page_blocks(ps, pg, join=False)
        for b in blocks:
            if b["kind"] == "image":
                got = _pic(doc, b)
                if got is None:
                    continue
                data, fmt, bw, bh = got
                from hwpx._document.media import add_image      # 그림 바이트를 문서에 넣는 python-hwpx 6.6 의 기본 함수
                bid = str(add_image(doc, data, fmt))
                obj = head.add_picture(bid, width=_u(bw), height=_u(bh), treat_as_char=False,
                                       text_wrap="IN_FRONT_OF_TEXT", char_pr_id_ref=anchor_run)
                _float(obj.element, b["rect"][0], b["rect"][1])
            elif b["kind"] == "table":
                rows = b["rows"]
                x0, y0, x1, y1 = b["rect"]
                t = head.add_table(len(rows), max(len(r) for r in rows), width=_u(x1 - x0), height=_u(y1 - y0),
                                   char_pr_id_ref=anchor_run)
                _fill_table(t, rows)
                _float(t.element, x0, y0)
        for band in _bands([b for b in blocks if b["kind"] == "line"]):
            text, x0, width, size, bold, serif = _band_text(band)
            lh = size * LINE_PCT / 100.0
            cy = sum((q["rect"][1] + q["rect"][3]) / 2 for q in band) / len(band)
            top = cy - lh / 2
            prev = max(0.0, top - cur)
            cur = max(cur, top) + lh
            doc.add_paragraph(text, section=sec, para_pr_id_ref=st.para(x0, prev),
                              char_pr_id_ref=st.run(size, _spacing(text, width, size, serif), bold, serif))
        for b in blocks:                           # 자리 없는 줄(좌표 없는 OCR) — 뒤에 이어서
            if b["kind"] == "line" and not b.get("rect"):
                doc.add_paragraph(b["text"], section=sec, para_pr_id_ref=st.para(0, 0),
                                  char_pr_id_ref=st.run(b["size"], 0, b["bold"], b["serif"]))
    st.finish()
    tick(len(pages), len(pages), "")
    doc.save_to_path(str(dst))
