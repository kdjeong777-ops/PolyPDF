"""PDF Bookmarker — PDF 책갈피 텍스트 생성 라이브러리.

두 가지 추출 방법을 제공한다.
  - Case 1: 목차 페이지 기반 (TocBookmarkExtractor) — 1순위 권장
  - Case 2: 폰트 기반 자동 (FontBookmarkExtractor) — 목차가 없을 때 폴백

자세한 명세는 ../개발지시서.md 참조.
"""
from .core import (
    Bookmark,
    TocItem,
    OffsetCandidate,
    format_bookmarks,
    organize_appendix_bookmarks,
    write_bookmark_file,
    BOOKMARK_SUFFIX,
)
from .toc_extractor import TocBookmarkExtractor
from .font_extractor import FontBookmarkExtractor
from .auto import extract_bookmarks_auto, detect_method
from .pdf_writer import apply_bookmarks_to_pdf

__version__ = "0.2.0"

__all__ = [
    "Bookmark",
    "TocItem",
    "OffsetCandidate",
    "format_bookmarks",
    "organize_appendix_bookmarks",
    "write_bookmark_file",
    "BOOKMARK_SUFFIX",
    "TocBookmarkExtractor",
    "FontBookmarkExtractor",
    "extract_bookmarks_auto",
    "detect_method",
    "apply_bookmarks_to_pdf",
]
