# -*- coding: utf-8 -*-
"""260908-2: 텍스트 창이 보여 줄 **쪽 → 줄 목록** (텍스트 창 SOT §3).

한 줄은 dict 다.
    {"text": 글, "style": "title"|"body", "rect": (x0,y0,x1,y1)|None, "kind": "text"|"table"}

- `rect` 는 PDF 좌표(pt). 본문 뷰어에 되비추는 데 쓴다(SOT §4 '텍스트 창에서 고른 줄을
  본문에서 강조'). OCR 폴백에는 좌표가 없으므로 None.
- 표는 **한 행을 한 줄**로 잇는다(SOT §3.3). 표와 겹치는 본문 줄은 뺀다 — 같은 글이 두 번
  나오면 읽기도 고치기도 헷갈린다.
- 제목/내용은 **그 쪽 글자 크기의 중앙값**으로 가른다(SOT §3.4). 평균은 큰 제목 하나에
  끌려가므로 쓰지 않는다.

유료 API 를 쓰지 않는다 — PyMuPDF 와 pdfplumber(좌표 기반)만으로 판단한다(SOT §1).
"""
from __future__ import annotations

TITLE_RATIO = 1.15          # 중앙값 대비 이 배 이상이면 제목
TABLE_OMIT_FMT = "[표 {cols}열 × {rows}행]"


def _line_items(page):
    """PyMuPDF 줄 → [(rect, 글, 대표크기)] — 빈 줄 제외, 블록 읽기 순서."""
    try:
        d = page.get_text("dict")
    except Exception:
        return []
    blocks = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:                  # 0=텍스트
            continue
        lines = []
        for ln in b.get("lines", []):
            spans = ln.get("spans", []) or []
            txt = "".join(sp.get("text", "") for sp in spans)
            if not txt.strip():
                continue
            size = max((float(sp.get("size", 0) or 0) for sp in spans), default=0.0)
            x0, y0, x1, y1 = ln.get("bbox", (0, 0, 0, 0))
            lines.append(((x0, y0, x1, y1), txt, size))
        if lines:
            bb = b.get("bbox", (0, 0, 0, 0))
            blocks.append((bb, lines))
    if not blocks:
        return []
    # 읽기 순서: 번역·요약과 같은 규칙(2단이면 좌측 먼저)
    try:
        from viewer.study.pdf_extract import _order_reading
        packed = [(bb[0], bb[1], bb[2], bb[3], "") for bb, _l in blocks]
        order = _order_reading(packed, page.rect)
        index = {(round(p[0], 2), round(p[1], 2)): i for i, p in enumerate(order)}
        blocks.sort(key=lambda t: index.get((round(t[0][0], 2), round(t[0][1], 2)), 1 << 30))
    except Exception:
        blocks.sort(key=lambda t: (t[0][1], t[0][0]))
    out = []
    for _bb, lines in blocks:
        out.extend(lines)
    return out


# 260908-3(응답성 SOT §4 ⑥, 감사에서 발견): **pdfplumber 핸들을 재사용한다.**
#   쪽을 넘길 때마다 `pdfplumber.open()` 을 새로 하면 그 문서를 처음부터 다시 뜯는다 —
#   실측 348쪽 61MB 문서에서 **쪽당 8.5~17초**(응답 없음 문턱의 두세 배)였다.
#   같은 핸들을 쓰면 쪽당 29~192ms 다. 파일이 바뀌거나 수정되면 새로 연다.
_PLUMB = {"key": None, "pdf": None}
_TCACHE = {}          # (파일키, 쪽) -> [(bbox, rows)]
_TCACHE_MAX = 64


def _plumber(pdf_path):
    import os
    try:
        key = (str(pdf_path), os.path.getmtime(pdf_path))
    except Exception:
        return None
    if _PLUMB["key"] == key and _PLUMB["pdf"] is not None:
        return _PLUMB["pdf"]
    close_cache()
    try:
        import pdfplumber
        _PLUMB["pdf"] = pdfplumber.open(str(pdf_path))
        _PLUMB["key"] = key
    except Exception:
        _PLUMB["key"] = None
        _PLUMB["pdf"] = None
    return _PLUMB["pdf"]


def close_cache() -> None:
    """열어 둔 핸들·표 결과를 놓는다. 파일을 지우거나 덮어쓰기 전에 부른다."""
    pdf = _PLUMB.get("pdf")
    _PLUMB["pdf"] = None
    _PLUMB["key"] = None
    _TCACHE.clear()
    if pdf is not None:
        try:
            pdf.close()
        except Exception:
            pass


def _tables(pdf_path, page_index: int):
    """[(bbox, rows)] — pdfplumber 로 찾은 표. 없거나 실패하면 빈 목록."""
    pdf = _plumber(pdf_path)
    if pdf is None:
        return []
    ck = (_PLUMB.get("key"), int(page_index))
    hit = _TCACHE.get(ck)
    if hit is not None:
        return hit
    out = []
    try:
        if page_index < len(pdf.pages):
            pg = pdf.pages[page_index]
            for t in pg.find_tables():
                rows = t.extract() or []
                if rows:
                    out.append((tuple(t.bbox), rows))
            try:
                pg.flush_cache()            # 쪽마다 붙잡는 메모리를 놓는다
            except Exception:
                pass
    except Exception:
        out = []
    if len(_TCACHE) > _TCACHE_MAX:
        _TCACHE.clear()
    _TCACHE[ck] = out
    return out


def _inside(rect, box, frac: float = 0.6) -> bool:
    """`rect` 의 넓이 중 `frac` 이상이 `box` 안에 들면 True."""
    ax0, ay0, ax1, ay1 = rect
    bx0, by0, bx1, by1 = box
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    area = max(1e-6, (ax1 - ax0) * (ay1 - ay0))
    return ((ix1 - ix0) * (iy1 - iy0)) / area >= frac


def _row_line(row) -> str:
    """표 한 행 → 한 줄. 빈 칸도 자리를 지킨다(열이 밀리면 표가 아니게 된다)."""
    cells = [(c or "").replace("\n", " ").strip() for c in row]
    return " | ".join(cells)


def _classify(items):
    """대표 크기의 **중앙값**으로 제목/내용을 가른다(SOT §3.4)."""
    sizes = sorted(s for _r, _t, s in items if s > 0)
    if not sizes:
        return ["body"] * len(items)
    mid = sizes[len(sizes) // 2]
    thr = mid * TITLE_RATIO
    return ["title" if (s > 0 and s >= thr) else "body" for _r, _t, s in items]


def page_lines(doc, pdf_path, page_index: int, *, tables: str = "lines",
               ocr_text: str = "") -> list:
    """쪽 하나의 줄 목록(SOT §3). `tables` = "lines"(기본) / "omit" / "off".

    `ocr_text` 는 텍스트층이 쓸 만하지 않을 때 쓰는 OCR 결과(단어장 SOT 의 study.db).
    """
    try:
        page = doc.load_page(int(page_index))
    except Exception:
        return []
    items = _line_items(page)

    if not items:                       # 텍스트층 없음 → OCR 폴백(좌표 없음)
        out = []
        for ln in (ocr_text or "").splitlines():
            if ln.strip():
                out.append({"text": ln, "style": "body", "rect": None, "kind": "text"})
        return out

    tbl = _tables(pdf_path, page_index) if tables != "off" else []
    styles = _classify(items)
    rows_out = []
    for (rect, txt, _size), st in zip(items, styles):
        rows_out.append({"text": txt, "style": st, "rect": rect, "kind": "text"})

    if tbl:
        # 표와 겹치는 본문 줄을 빼고, 그 자리에 표 줄을 넣는다
        keep = []
        for r in rows_out:
            if any(_inside(r["rect"], bb) for bb, _rows in tbl):
                continue
            keep.append(r)
        for bb, rows in tbl:
            if tables == "omit":
                cols = max((len(r) for r in rows), default=0)
                keep.append({"text": TABLE_OMIT_FMT.format(cols=cols, rows=len(rows)),
                             "style": "body", "rect": bb, "kind": "table"})
            else:
                for row in rows:
                    line = _row_line(row)
                    if line.strip(" |"):
                        keep.append({"text": line, "style": "body",
                                     "rect": bb, "kind": "table"})
        keep.sort(key=lambda r: ((r["rect"][1] if r["rect"] else 0),
                                 (r["rect"][0] if r["rect"] else 0)))
        rows_out = keep
    return rows_out


def has_text_layer(doc, page_index: int) -> bool:
    """이 쪽에 쓸 만한 텍스트층이 있는가(스캔본이면 False → OCR 을 쓴다)."""
    try:
        page = doc.load_page(int(page_index))
    except Exception:
        return False
    try:
        from viewer.study import ocr as _ocr
        src, _ = _ocr.decide_source(page)
        return src != "ocr"
    except Exception:
        try:
            return len((page.get_text("text") or "").strip()) >= 20
        except Exception:
            return False
