# -*- coding: utf-8 -*-
"""261102-3: 책갈피 자동 생성의 한 길 (마스터 §4.4.2 ②'' · §4.4.3 T1·T2).

책갈피 자동 생성(검토 없이)·일괄 OCR(종전 단어장·책갈피 동시 생성)·병합의 책갈피 만들기가 모두 `generate` 를 탄다.
  1) 목차 쪽 탐지 → 목차 항목이 있으면 **목차 항목만**(T2) — 실제 쪽은 인쇄 쪽 번호·장 제목(F1~F4), 못 하면 오프셋
  2) 목차 쪽은 그 줄을 책갈피로 넣지 않고 목차 첫 쪽에 '목차' 하나(T1)
  3) 목차가 없으면(또는 항목을 못 읽으면) 장 찾기(H2) ▶ 헤딩(H1, 스캔) · 글꼴(디지털) — 목차 쪽 위 헤딩은 버린다
Qt 비의존 — 워커 스레드에서 쓴다(응답성 SOT §4 ①).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from viewer.i18n import tr


def toc_entry_row(toc_pages: list[int]) -> dict:
    """T1: 목차 첫 쪽의 '목차' 행 — 수동(오프셋을 다시 적용해도 그대로)."""
    first = int(min(toc_pages))
    return {"title": tr("목차"), "toc_page": None, "page": first, "level": 0, "manual": True,
            "src": f"p{first}", "toc_entry": True}


def drop_toc_pages(items: list, toc_pages) -> list:
    """T1: 목차 쪽을 가리키는 헤딩 책갈피(Bookmark 또는 (제목, 쪽, 레벨))는 버린다."""
    skip = set(int(p) for p in (toc_pages or []))
    if not skip:
        return list(items)
    page_of = lambda b: int(b.page) if hasattr(b, "page") else int(b[1])
    return [b for b in items if page_of(b) not in skip]


def map_pages(pdf_path, rows: list[dict], toc_pages: list[int], off: int, *, ocr=None,
              should_cancel: Optional[Callable[[], bool]] = None,
              progress: Optional[Callable[[str], None]] = None,
              pace: Optional[Callable[[], object]] = None) -> Optional[dict]:
    """261101-2(F1~F4): 행마다 PDF 쪽·구간(`page`·`seg`). 성공하면 {"method": "folio"|"chapters", …}, 못 하면 None(오프셋으로)."""
    should_cancel = should_cancel or (lambda: False)
    progress = progress or (lambda _m: None)
    try:
        from viewer import page_numbers as _pn
        first = max(toc_pages) + 1
        with _pn.PrintedPages(pdf_path, ocr=ocr, should_cancel=should_cancel, progress=progress, pace=pace) as pp:
            n = pp.page_count
            est = pp.estimate(first, n)
            if should_cancel():
                return None
            if est is not None:
                _pn.map_rows(rows, est, n)
                _pn.refine_chapter_pages(rows, pp.text_of, skip=set(toc_pages))
                return {"method": "folio", "segments": est.as_list()}
            progress(tr("장 제목으로 쪽 맞추는 중..."))
            found = _pn.map_rows_by_chapters(rows, pp.text_of, n, start_offset=off, skip=set(toc_pages),
                                             should_cancel=should_cancel)
            if found:
                return {"method": "chapters", "chapters": found}
            for r in rows:                      # 못 찾았으면 표는 종전대로(오프셋)
                r["page"] = None
                r.pop("seg", None)
    except Exception:
        pass
    return None


def toc_rows(pdf_path, toc_pages: list[int], *, ocr=None, offset: Optional[int] = None,
             should_cancel=None, progress=None, pace=None) -> dict:
    """목차 쪽 → 표 행(쪽 맞춘 것) + T1 '목차' 행. {"rows", "candidates", "offset", "page_map"} — 항목이 없으면 rows=[]."""
    from viewer import toc_parse
    rows = toc_parse.parse_toc_pages(pdf_path, toc_pages, ocr=ocr)
    out = {"rows": rows, "candidates": [], "offset": 0, "page_map": None}
    if not rows or (should_cancel and should_cancel()):
        return out
    (progress or (lambda _m: None))(tr("오프셋(목차 쪽 → 실제 쪽) 추정 중..."))
    page_text = None
    if ocr is not None:
        page_text = (lambda pg: ocr.text(pg, run=False) if ocr.is_scan(pg) else None)
    cands = toc_parse.suggest_offsets(pdf_path, rows, toc_pages, page_text=page_text)
    off = offset if offset is not None else (cands[0][0] if cands else 0)
    page_map = None
    if offset is None:
        page_map = map_pages(pdf_path, rows, toc_pages, int(off), ocr=ocr, should_cancel=should_cancel,
                             progress=progress, pace=pace)
    rows.insert(0, toc_entry_row(toc_pages))          # T1
    out.update(rows=rows, candidates=cands, offset=int(off), page_map=page_map)
    return out


def finish_rows(rows: list[dict], off: int, page_count: int, page_map) -> list[tuple[str, int, int]]:
    """검토 없이 끝낼 때 — 맞춘 쪽은 두고 못 맞춘 행만 오프셋, (제목, 쪽, 레벨)."""
    from viewer import toc_parse
    for r in rows:
        if page_map or r.get("toc_entry"):
            r["manual"] = r.get("page") is not None
    toc_parse.apply_offset(rows, int(off), page_count, keep_manual=True)
    return toc_parse.to_bookmarks(rows)


def generate(pdf_path, *, ocr=None, should_cancel: Optional[Callable[[], bool]] = None,
             progress: Optional[Callable[[str], None]] = None,
             pace: Optional[Callable[[], object]] = None, ocr_font_auto: bool = False) -> list[tuple[str, int, int]]:
    """검토 없는 자동 생성 — [(제목, 쪽 1-based, 레벨 0-based)] (T1·T2·H2·H1·글꼴 순)."""
    import fitz
    from viewer import toc_parse
    should_cancel = should_cancel or (lambda: False)
    progress = progress or (lambda _m: None)
    own = None
    if ocr is None:
        try:
            from viewer.study.ocr_pages import OcrPages
            ocr = own = OcrPages(pdf_path, should_cancel=should_cancel, progress=progress, pace=pace)
        except Exception:
            ocr = None
    try:
        d = fitz.open(str(pdf_path))
        n = d.page_count
        d.close()
        progress(tr("목차 쪽 찾는 중..."))
        try:
            toc_pages = toc_parse.find_toc_pages(pdf_path, ocr=ocr)
        except Exception:
            toc_pages = []
        if should_cancel():
            return []
        if toc_pages:
            res = toc_rows(pdf_path, toc_pages, ocr=ocr, should_cancel=should_cancel, progress=progress, pace=pace)
            if len(res["rows"]) > 1:                       # '목차' 행 말고 항목이 있으면 — 목차 항목만(T2)
                return finish_rows(res["rows"], res["offset"], n, res["page_map"])
        out = _headings(pdf_path, ocr, n, should_cancel=should_cancel, progress=progress, pace=pace,
                        ocr_font_auto=ocr_font_auto)
        out = drop_toc_pages(out, toc_pages)
        if toc_pages:
            e = toc_entry_row(toc_pages)
            out = [(e["title"], e["page"], 0)] + out
        return out
    finally:
        if own is not None:
            own.close()


def _headings(pdf_path, ocr, n, *, should_cancel, progress, pace, ocr_font_auto) -> list[tuple[str, int, int]]:
    """목차가 없을 때: 스캔본은 장 찾기(H2) ▶ OCR 헤딩(H1), 디지털은 글꼴(pdf_bookmarker)."""
    scanned = False
    try:
        if ocr is not None:
            probe = sorted({1, max(1, n // 2), n})
            scanned = sum(1 for p in probe if ocr.is_scan(p)) * 2 > len(probe)
    except Exception:
        scanned = False
    if not scanned:
        try:
            from viewer import bookmarker_bridge as bridge
            if bridge.is_available():
                res = bridge.extract_auto(pdf_path, mode="auto")
                bms = res.get("bookmarks") or []
                if bms:
                    return [(b.title, int(b.page), int(b.level)) for b in bms]
        except Exception:
            pass
    from viewer.study.ocr_headings import chapter_pages_fast, extract_ocr_bookmarks, prefer_heading_per_page
    lang = getattr(getattr(ocr, "_picker", None), "lang", "") or ""
    fast = chapter_pages_fast(pdf_path, lang=lang, progress=progress, should_cancel=should_cancel, pace=pace)
    if fast:
        return [(t, int(p), 0) for t, p in fast]
    if should_cancel():
        return []
    progress(tr("OCR 헤딩 인식 중..."))
    bms = extract_ocr_bookmarks(pdf_path, use_font_auto=ocr_font_auto,
                                progress=lambda _d, _t, m: progress(m), should_cancel=should_cancel, pages=ocr)
    bms = prefer_heading_per_page(bms)
    return [(b.title, int(b.page), int(b.level)) for b in bms]
