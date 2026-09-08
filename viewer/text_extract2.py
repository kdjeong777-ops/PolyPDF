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
# 260908-6(SOT §3.5): OCR 잡음으로 보는 글자 상자 높이(pt). A4 에서 4pt = 약 1.4mm 라
#   사람이 읽으라고 넣은 글자일 수 없다. 실측 잡음 1.4~3.4 / 진짜 글 5.3~27.9.
NOISE_MIN_H_PT = 4.0
TABLE_OMIT_FMT = "[표 {cols}열 × {rows}행]"


def _is_ocr_layer(page) -> bool:
    """이 쪽의 글자가 **보이지 않는 OCR 층**인가(SOT §3.5).

    스캔본은 그림 위에 render mode 3(보이지 않음)으로 글자를 얹는다. 그 층에는 OCR 이
    종이의 티를 글자로 잘못 읽은 것이 섞여 있어, 잡음 거르기는 **이런 쪽에만** 한다 —
    사람이 넣은 작은 글씨를 지우면 안 된다."""
    try:
        tr = page.get_texttrace()
    except Exception:
        return False
    if not tr:
        return False
    inv = sum(1 for sp in tr if sp.get("type") == 3)
    return inv >= len(tr) * 0.9


def _line_items(page):
    """PyMuPDF 줄 → [(rect, 글, 대표크기)] — 빈 줄 제외, 블록 읽기 순서.

    260908-6(SOT §3.5): 보이지 않는 OCR 층인 쪽에서는 **글자라고 볼 수 없이 작은 줄**을
    뺀다. 반환값에 잡음 수를 곁들이지 않고, 부르는 쪽이 필요하면 `last_noise_count()` 로 본다.
    """
    try:
        d = page.get_text("dict")
    except Exception:
        return []
    ocr_layer = _is_ocr_layer(page)
    noise = 0
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
            if x1 <= x0 or y1 <= y0:            # 뒤집히거나 납작한 상자 — 글자가 아니다
                noise += 1
                continue
            if ocr_layer and (y1 - y0) < NOISE_MIN_H_PT:
                noise += 1
                continue
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
    _NOISE["n"] = noise
    out = []
    for _bb, lines in blocks:
        out.extend(lines)
    return out


_NOISE = {"n": 0}


def last_noise_count() -> int:
    """바로 앞 `_line_items` 가 뺀 잡음 줄 수(SOT §3.5 — 창 안내에 쓴다)."""
    return int(_NOISE.get("n", 0))


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


def _tables(pdf_path, page_index: int, *, cached_only: bool = False):
    """[(bbox, rows)] — pdfplumber 로 찾은 표. 없거나 실패하면 빈 목록.

    260908-5: 캐시를 **두 겹**으로 본다. ① 이번 실행의 메모리(`_TCACHE`), ② index.db 의
    `page_tables`. 둘 다 `pdfplumber` 를 열기 **전에** 본다 — 표 찾기가 실측 쪽당
    150ms~7초라, 캐시가 맞는데도 문서를 여는 것은 그 값을 헛되이 치르는 일이다.
    """
    size, mtime = _stat(pdf_path)
    ck = ((str(pdf_path), size, mtime), int(page_index))
    hit = _TCACHE.get(ck)
    if hit is not None:
        return hit
    db = _db_get(pdf_path, page_index)
    if db is not None:
        _TCACHE[ck] = db
        return db
    if cached_only:
        # 260908-5(응답성 SOT §4 ①): 인덱싱이 도는 동안에는 표를 **새로 파지 않는다** —
        #   둘 다 GIL 을 오래 쥐어 겹치면 창이 굼떠진다. 인덱싱이 끝나면 다시 부른다.
        #   결과를 캐시에 넣지 않는 것이 요점이다(다음 호출이 제대로 파도록).
        return []
    pdf = _plumber(pdf_path)
    if pdf is None:
        return []
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
    _db_put(pdf_path, page_index, out)
    return out


# 260908-5: 표 결과의 **영구 캐시**(index.db `page_tables`). 앱이 db 경로를 준다.
_DB_PATH = None


def set_table_cache_db(path) -> None:
    """앱 시작 때 한 번 — 없으면 캐시 없이 동작한다(기능 저하, 오류 아님)."""
    global _DB_PATH
    _DB_PATH = str(path) if path else None


def _stat(pdf_path):
    import os
    try:
        st = os.stat(pdf_path)
        return int(st.st_size), float(st.st_mtime)
    except Exception:
        return None, None


def _db_get(pdf_path, page):
    if not _DB_PATH:
        return None
    size, mtime = _stat(pdf_path)
    if size is None:
        return None
    try:
        from viewer.indexer import PdfIndex
        ix = PdfIndex(_DB_PATH)
        try:
            got = ix.tables_get(pdf_path, page, size, mtime)
        finally:
            ix.close()
        if got is None:
            return None
        return [(tuple(bb), rows) for bb, rows in got]
    except Exception:
        return None


def _db_put(pdf_path, page, data) -> None:
    if not _DB_PATH:
        return
    size, mtime = _stat(pdf_path)
    if size is None:
        return
    try:
        from viewer.indexer import PdfIndex
        ix = PdfIndex(_DB_PATH)
        try:
            ix.tables_set(pdf_path, page, size, mtime,
                          [[list(bb), rows] for bb, rows in data])
        finally:
            ix.close()
    except Exception:
        pass


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
               ocr_text: str = "", tables_cached_only: bool = False) -> list:
    """쪽 하나의 줄 목록(SOT §3). `tables` = "lines"(기본) / "omit" / "off".

    `ocr_text` 는 텍스트층이 쓸 만하지 않을 때 쓰는 OCR 결과(단어장 SOT 의 study.db).
    """
    try:
        page = doc.load_page(int(page_index))
    except Exception:
        return []
    items = _line_items(page)
    noise = last_noise_count()

    if not items:                       # 텍스트층 없음 → OCR 폴백(좌표 없음)
        out = []
        for ln in (ocr_text or "").splitlines():
            if ln.strip():
                out.append({"text": ln, "style": "body", "rect": None, "kind": "text"})
        return out

    tbl = (_tables(pdf_path, page_index, cached_only=tables_cached_only)
           if tables != "off" else [])
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
    _NOISE["n"] = noise          # 표 처리가 `_line_items` 를 다시 부르지 않음을 명시
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
