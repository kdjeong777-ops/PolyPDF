"""Case 2: 폰트 기반 자동 책갈피 추출기 (목차 페이지가 없을 때 사용)."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from .core import Bookmark, clean_title


# ─── 헤딩 정규식 ──────────────────────────────────────────────────
# 레벨 0: 장(章) 단위
_CHAPTER_PAT = re.compile(r"^\s*제\s*\d+\s*장\s+\S")
# 1./2./… 형태 — 레벨 0 (전체 문서에서 1~9 정도 출현)
_NUM1_PAT = re.compile(r"^\s*\d+\.\s+\S")
# 1.1, 1.1. 형태 — 레벨 1
_NUM2_PAT = re.compile(r"^\s*\d+\.\d+\.?\s+\S")
# 1.1.1, 1.1.1. 형태 — 레벨 2
_NUM3_PAT = re.compile(r"^\s*\d+\.\d+\.\d+\.?\s+\S")
# 제N절 — 레벨 1
_SECTION_PAT = re.compile(r"^\s*제\s*\d+\s*절\s+\S")

# 부정 패턴 — 본문 인용 "1. 그러나..." 등을 거르기 위한 최소 길이
_MIN_TITLE_LEN = 2
_MAX_TITLE_LEN = 80


@dataclass
class FontStats:
    body_size: float           # 본문 폰트 크기(최빈값)
    heading_sizes: list[float] # 본문 + 1.5pt 이상인 크기들(큰→작은 순)


@dataclass
class _Line:
    page_index: int  # 0-based
    text: str
    size: float      # 줄 내 최대 폰트 크기
    top: float
    x0: float


class FontBookmarkExtractor:
    """폰트 크기와 정규식으로 헤딩 후보를 추출한다."""

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(self.pdf_path)
        self._lines_cache: list[_Line] | None = None

    # ─── 폰트 통계 ────────────────────────────────────────────
    def analyze_fonts(self, min_heading_delta: float = 1.5) -> FontStats:
        lines = self._all_lines()
        if not lines:
            return FontStats(body_size=10.0, heading_sizes=[])
        sizes = [round(ln.size, 1) for ln in lines]
        body = Counter(sizes).most_common(1)[0][0]
        unique_sizes = sorted({s for s in sizes if s >= body + min_heading_delta},
                              reverse=True)
        return FontStats(body_size=float(body), heading_sizes=unique_sizes)

    # ─── 책갈피 추출 ──────────────────────────────────────────
    def extract(
        self,
        min_heading_delta: float = 1.5,
        use_regex: bool = True,
        use_font_size: bool = True,
    ) -> list[Bookmark]:
        if not (use_regex or use_font_size):
            return []

        stats = self.analyze_fonts(min_heading_delta=min_heading_delta)
        heading_size_to_level = self._size_to_level_map(stats.heading_sizes)

        bookmarks: list[Bookmark] = []
        for ln in self._all_lines():
            if len(ln.text) < _MIN_TITLE_LEN or len(ln.text) > _MAX_TITLE_LEN:
                continue

            regex_level = self._regex_level(ln.text) if use_regex else None
            font_level = (
                heading_size_to_level.get(round(ln.size, 1))
                if use_font_size else None
            )

            # 1순위: 정규식 + 폰트 둘 다 일치
            # 2순위: 정규식만 일치
            # 3순위: 폰트만 일치 (use_font_size 단독일 때)
            if regex_level is not None:
                level = regex_level
            elif font_level is not None and use_font_size and not use_regex:
                level = font_level
            else:
                continue

            page_1based = ln.page_index + 1
            title = clean_title(ln.text)
            if not title:
                continue
            # 같은 페이지의 동일 제목 중복 제거 (가장 위쪽만)
            if bookmarks and bookmarks[-1].title == title and bookmarks[-1].page == page_1based:
                continue
            bookmarks.append(Bookmark(title=title, page=page_1based, level=level))

        return self._dedup_keep_order(bookmarks)

    # ─── 내부 유틸 ────────────────────────────────────────────
    def _all_lines(self) -> list[_Line]:
        if self._lines_cache is not None:
            return self._lines_cache
        lines: list[_Line] = []
        with pdfplumber.open(self.pdf_path) as pdf:
            for pi, page in enumerate(pdf.pages):
                lines.extend(self._extract_lines(page, pi))
        self._lines_cache = lines
        return lines

    @staticmethod
    def _extract_lines(page, page_index: int) -> list[_Line]:
        chars = page.chars
        if not chars:
            return []
        chars_sorted = sorted(chars, key=lambda c: (round(c["top"], 1), c["x0"]))
        groups: list[list[dict]] = []
        for c in chars_sorted:
            if groups and abs(c["top"] - groups[-1][0]["top"]) <= 2.0:
                groups[-1].append(c)
            else:
                groups.append([c])

        result: list[_Line] = []
        for grp in groups:
            grp.sort(key=lambda c: c["x0"])
            text = "".join(c["text"] for c in grp).strip()
            if not text:
                continue
            size = max(float(c.get("size", 0.0)) for c in grp)
            result.append(_Line(
                page_index=page_index,
                text=text,
                size=size,
                top=grp[0]["top"],
                x0=grp[0]["x0"],
            ))
        return result

    @staticmethod
    def _regex_level(text: str) -> int | None:
        # 더 구체적인(긴 번호) 패턴부터 검사
        if _NUM3_PAT.match(text):
            return 2
        if _NUM2_PAT.match(text):
            return 1
        if _SECTION_PAT.match(text):
            return 1
        if _CHAPTER_PAT.match(text):
            return 0
        if _NUM1_PAT.match(text):
            return 0
        return None

    @staticmethod
    def _size_to_level_map(heading_sizes: list[float]) -> dict[float, int]:
        """[18, 14, 12] → {18:0, 14:1, 12:2}. 4번째부터는 모두 2."""
        mapping: dict[float, int] = {}
        for idx, sz in enumerate(heading_sizes):
            mapping[round(sz, 1)] = min(idx, 2)
        return mapping

    @staticmethod
    def _dedup_keep_order(bookmarks: list[Bookmark]) -> list[Bookmark]:
        seen: set[tuple[str, int, int]] = set()
        out: list[Bookmark] = []
        for bm in bookmarks:
            key = (bm.title, bm.page, bm.level)
            if key in seen:
                continue
            seen.add(key)
            out.append(bm)
        return out
