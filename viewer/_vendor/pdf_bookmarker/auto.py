"""자동 모드: 목차가 있으면 Case 1, 없으면 Case 2."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .core import Bookmark
from .font_extractor import FontBookmarkExtractor
from .toc_extractor import TocBookmarkExtractor


Method = Literal["toc", "font"]


@dataclass
class AutoResult:
    method: Method
    bookmarks: list[Bookmark]
    toc_pages: list[int]
    offset: int | None  # method=='toc' 일 때만 의미 있음


def detect_method(pdf_path: str | Path, scan_first_n: int = 30) -> tuple[Method, list[int]]:
    """목차 페이지 탐지 결과로 method 결정. 발견된 목차 페이지 리스트도 반환."""
    extractor = TocBookmarkExtractor(pdf_path)
    toc_pages = extractor.find_toc_pages(scan_first_n=scan_first_n)
    return ("toc" if toc_pages else "font"), toc_pages


def extract_bookmarks_auto(
    pdf_path: str | Path,
    force_method: Method | None = None,
    offset: int | None = None,
) -> AutoResult:
    """자동 모드 편의 함수.

    - force_method=None : 자동 탐지
    - force_method='toc': Case 1 강제
    - force_method='font': Case 2 강제
    - offset=None       : Case1일 때 추천 오프셋 중 신뢰도 최상위 사용
    """
    method, toc_pages = detect_method(pdf_path) if force_method is None else (force_method, [])

    if method == "toc":
        ex = TocBookmarkExtractor(pdf_path)
        if not toc_pages:
            toc_pages = ex.find_toc_pages()
        items = ex.parse_toc(toc_pages)
        if not items:
            # 목차 페이지는 있었지만 항목 파싱 실패 → 폰트로 폴백
            font_bms = FontBookmarkExtractor(pdf_path).extract()
            return AutoResult(method="font", bookmarks=font_bms,
                              toc_pages=toc_pages, offset=None)
        if offset is None:
            cands = ex.suggest_offsets(items)
            offset = cands[0].offset if cands else 0
        bookmarks = ex.build_bookmarks(items, offset=offset)
        return AutoResult(method="toc", bookmarks=bookmarks,
                          toc_pages=toc_pages, offset=offset)

    bookmarks = FontBookmarkExtractor(pdf_path).extract()
    return AutoResult(method="font", bookmarks=bookmarks,
                      toc_pages=toc_pages, offset=None)
