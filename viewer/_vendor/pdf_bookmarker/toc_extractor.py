"""Case 1: 목차 페이지 기반 책갈피 추출기."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Iterable

import pdfplumber

from .core import (
    Bookmark,
    OffsetCandidate,
    TocItem,
    clean_title,
    organize_appendix_bookmarks,
)


# ─── 목차 페이지 탐지 신호 ─────────────────────────────────────────
_TOC_HEADER_PAT = re.compile(
    r"^\s*(목\s*차|차\s*례|CONTENTS|Contents|TABLE\s+OF\s+CONTENTS)\s*$"
)
# 줄 단위 점선 리더(타이틀과 페이지 사이 채움). 본문에 단발성으로 등장하는
# 단일 점 문자가 페이지 전체 차단을 유발하지 않도록 "연속" 패턴만 잡는다.
_DOT_LEADER_PAT = re.compile(r"[·•．․‥…⋯]{2,}|\.{3,}")
# 줄 끝이 페이지 번호인지: "제1장 총칙 ……… 15" 형태
_TOC_LINE_PAT = re.compile(
    r"^(?P<title>.+?)[\s·…．\.]{2,}(?P<page>\d{1,4})\s*$"
)
# 점선 리더 없이 "제목 (여러 공백) 페이지" 형태도 허용
_TOC_LINE_LOOSE_PAT = re.compile(
    r"^(?P<title>.+?\S)\s{2,}(?P<page>\d{1,4})\s*$"
)
# 구분자 없이 "제목뒤글자+숫자" 가 바로 붙은 형태 — 예: 'Materials85', 'Equipment87'.
# false positive 방지: 제목 마지막은 글자/한글/괄호여야 한다 (숫자나 공백 금지).
_TOC_LINE_TIGHT_PAT = re.compile(
    r"^(?P<title>.+?[A-Za-z가-힣\)\]])(?P<page>\d{1,4})\s*$"
)


class TocBookmarkExtractor:
    """PDF 앞쪽의 목차 페이지에서 책갈피를 추출한다."""

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(self.pdf_path)

    # ─── 목차 페이지 탐지 ─────────────────────────────────────
    def find_toc_pages(self, scan_first_n: int = 30) -> list[int]:
        """목차로 보이는 페이지 번호(1-based) 리스트를 반환."""
        toc_pages: list[int] = []
        with pdfplumber.open(self.pdf_path) as pdf:
            n = min(scan_first_n, len(pdf.pages))
            in_toc = False
            for i in range(n):
                page = pdf.pages[i]
                text = page.extract_text() or ""
                lines = [ln for ln in text.splitlines() if ln.strip()]
                if not lines:
                    continue

                # 상단 5줄 안에 목차 헤더가 있는지
                has_header = any(_TOC_HEADER_PAT.match(ln) for ln in lines[:5])
                # 점선 리더가 풍부한지
                leader_lines = sum(1 for ln in lines if _DOT_LEADER_PAT.search(ln))
                # 줄 끝이 페이지번호인 줄 수
                page_ending_lines = sum(
                    1 for ln in lines
                    if _TOC_LINE_PAT.match(ln) or _TOC_LINE_LOOSE_PAT.match(ln)
                )

                is_toc_page = (
                    has_header
                    or leader_lines >= 3
                    or page_ending_lines >= 5
                )
                if is_toc_page:
                    toc_pages.append(i + 1)
                    in_toc = True
                elif in_toc:
                    # 목차가 끝났다고 보고 중단 (연속 영역 가정)
                    break
        return toc_pages

    # ─── 목차 항목 파싱 ────────────────────────────────────────
    def parse_toc(self, toc_pages: Iterable[int]) -> list[TocItem]:
        """주어진 목차 페이지들에서 (제목, 페이지, 레벨) 추출.

        레벨 결정 우선순위:
          1) 제목 앞 번호 패턴 (``1.0`` / ``1.1`` / ``1.1.1`` / ``제N장`` / ``제N절``)
          2) (번호 없는 항목만) x 좌표 클러스터링

        한 항목이 두 줄에 걸쳐 표시되는 경우(긴 제목) ``_merge_multiline`` 으로
        자동 병합한 뒤 파싱한다.
        """
        raw: list[tuple[str, int, float]] = []
        with pdfplumber.open(self.pdf_path) as pdf:
            for pno in toc_pages:
                if pno < 1 or pno > len(pdf.pages):
                    continue
                page = pdf.pages[pno - 1]
                lines = self._group_lines_by_y(page)
                lines = self._merge_multiline(lines)
                for x0, text in lines:
                    parsed = self._parse_toc_line(text)
                    if parsed is None:
                        continue
                    title, toc_page = parsed
                    raw.append((title, toc_page, x0))

        if not raw:
            return []

        items: list[TocItem] = []
        unresolved_idx: list[int] = []
        unresolved_x: list[float] = []
        for i, (title, toc_page, x0) in enumerate(raw):
            nl = self._infer_level_from_number(title)
            if nl is not None:
                items.append(TocItem(title=title, toc_page=toc_page, level=nl))
            else:
                items.append(TocItem(title=title, toc_page=toc_page, level=0))
                unresolved_idx.append(i)
                unresolved_x.append(x0)

        if unresolved_x:
            x_levels = self._assign_levels_from_x(unresolved_x)
            for ui, lv in zip(unresolved_idx, x_levels):
                items[ui].level = lv
        return items

    # 제목 번호 → 레벨 추론
    _NUM_LEVEL_PAT = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[\s.:]|$)")
    # 부록 식 번호: "D.1", "D.2.", "F.1.3.", "F.2.3" 등
    _APPENDIX_NUM_PAT = re.compile(r"^[A-Z]\.(\d+)(?:\.(\d+))?(?:[\s.:]|$)")
    _KO_CHAPTER_PAT = re.compile(r"^제\s*\d+\s*장\b")
    _KO_SECTION_PAT = re.compile(r"^제\s*\d+\s*절\b")
    # 영문 표제 — 챕터 레벨
    _EN_CHAPTER_PAT = re.compile(
        r"^(Chapter|CHAPTER|Part|PART|Appendix|APPENDIX)\s+\S",
        re.IGNORECASE,
    )
    # 부록·참고문헌 등 단어 단독으로 챕터 동급
    _EN_STANDALONE_PAT = re.compile(
        r"^(References|REFERENCES|Bibliography|Glossary|Index|Preface|Foreword|"
        r"Abstract|Acknowledgements|Acknowledgments|Contents|"
        r"List of (Tables|Figures|Abbreviations))\b"
    )
    # 영문 섹션 레벨
    _EN_SECTION_PAT = re.compile(r"^Section\s+\d+\b", re.IGNORECASE)

    @classmethod
    def _infer_level_from_number(cls, title: str) -> int | None:
        """제목 앞 번호/표제 패턴으로 레벨을 추론. 매치 실패 시 None."""
        s = title.lstrip()
        if not s:
            return None
        # 한글
        if cls._KO_CHAPTER_PAT.match(s):
            return 0
        if cls._KO_SECTION_PAT.match(s):
            return 1
        # 영문 표제
        if cls._EN_CHAPTER_PAT.match(s):
            return 0
        if cls._EN_STANDALONE_PAT.match(s):
            return 0
        if cls._EN_SECTION_PAT.match(s):
            return 1
        # 부록 식 번호 — "D.1" → L1, "D.1.1" → L2 (부록 자체는 L0)
        ma = cls._APPENDIX_NUM_PAT.match(s)
        if ma is not None:
            return 2 if ma.group(2) is not None else 1
        # 숫자 트리 — "1.", "1.0", "1.1", "1.1.1" …
        m = cls._NUM_LEVEL_PAT.match(s)
        if not m:
            return None
        _, n2, n3 = m.group(1), m.group(2), m.group(3)
        if n3 is not None:
            return 2
        if n2 is not None:
            return 0 if n2 == "0" else 1  # "N.0" = 챕터, "N.M" (M≠0) = 섹션
        return 0  # 단순 "N." 또는 "N "

    @staticmethod
    def _group_lines_by_y(page) -> list[tuple[float, str]]:
        """페이지의 줄을 (x_start, text) 로 반환.

        pdfplumber 의 ``extract_text_lines()`` 를 사용하면 글리프 사이의
        간격을 보고 공백을 자동 추론한다. 직접 ``chars`` 를 join 하면 PDF 가
        공백을 글리프 대신 좌표 갭으로 표현했을 때 공백이 사라진다.
        """
        try:
            rows = page.extract_text_lines()
        except Exception:
            rows = None
        if rows:
            return [
                (float(r.get("x0", 0.0)), str(r.get("text", "")).strip())
                for r in rows
                if str(r.get("text", "")).strip()
            ]
        # 폴백: extract_text 줄별 split (x0 정보 없음)
        text = page.extract_text() or ""
        return [(0.0, ln) for ln in text.splitlines() if ln.strip()]

    @classmethod
    def _merge_multiline(
        cls,
        lines: list[tuple[float, str]],
        indent_threshold: float = 20.0,
    ) -> list[tuple[float, str]]:
        """한 항목이 두 줄에 걸쳐 표시된 경우 병합한다.

        병합 조건:
          - 줄 N 이 TOC 라인 형식(``제목 … 페이지번호``) 으로 매칭되지 **않고**
          - 줄 N+1 이 매칭되며
          - 줄 N+1 의 x0 이 줄 N 의 x0 보다 ``indent_threshold`` 이상 깊다
        → 줄 N 의 텍스트 + " " + 줄 N+1 의 텍스트 를 한 항목으로.

        ``indent_threshold`` 는 일반 들여쓰기 단계(보통 12pt)보다 큰 값으로 잡아
        본문 트리의 자식 항목과 줄바꿈 잔재를 구분한다.
        """
        if not lines:
            return []

        def _has_page(text: str) -> bool:
            return bool(
                _TOC_LINE_PAT.match(text)
                or _TOC_LINE_LOOSE_PAT.match(text)
                or _TOC_LINE_TIGHT_PAT.match(text)
            )

        merged: list[tuple[float, str]] = []
        i = 0
        while i < len(lines):
            x_i, t_i = lines[i]
            if not _has_page(t_i) and i + 1 < len(lines):
                x_j, t_j = lines[i + 1]
                if _has_page(t_j) and (x_j - x_i) >= indent_threshold:
                    merged.append((x_i, t_i.rstrip() + " " + t_j.lstrip()))
                    i += 2
                    continue
            merged.append((x_i, t_i))
            i += 1
        return merged

    @staticmethod
    def _parse_toc_line(text: str) -> tuple[str, int] | None:
        """한 줄 → (제목, 페이지번호). 매칭 실패 시 None.

        세 단계 패턴 시도:
          1) PAT — 점선 리더 + 페이지번호
          2) LOOSE — 2+ 공백 + 페이지번호
          3) TIGHT — 구분자 없이 '제목+페이지' 가 바로 붙은 경우
        """
        m = _TOC_LINE_PAT.match(text)
        if m is None:
            m = _TOC_LINE_LOOSE_PAT.match(text)
        if m is None:
            m = _TOC_LINE_TIGHT_PAT.match(text)
        if m is None:
            return None
        title = clean_title(m.group("title"))
        try:
            page = int(m.group("page"))
        except ValueError:
            return None
        if not title or page <= 0:
            return None
        return title, page

    @staticmethod
    def _has_many_toc_lines(text: str, threshold: int = 5) -> bool:
        """페이지 텍스트에 '제목 ……… 페이지번호' 형태 줄이 threshold 이상이면 목차성 페이지."""
        if not text:
            return False
        lines = text.splitlines()
        cnt = 0
        for ln in lines:
            if _TOC_LINE_PAT.match(ln) or _TOC_LINE_LOOSE_PAT.match(ln):
                cnt += 1
                if cnt >= threshold:
                    return True
        return False

    @staticmethod
    def _assign_levels_from_x(x_origins: list[float], max_levels: int = 3) -> list[int]:
        """들여쓰기 x 좌표를 클러스터링해 0/1/2 레벨로 매핑."""
        if not x_origins:
            return []
        # 가장 흔한 x 좌표를 본문 레벨(0)로 두고, +N pt 단위로 단계 나눔
        rounded = [round(x, 0) for x in x_origins]
        base = min(rounded)
        levels: list[int] = []
        for x in rounded:
            delta = x - base
            if delta < 8:
                lv = 0
            elif delta < 20:
                lv = 1
            else:
                lv = min(2, max_levels - 1)
            levels.append(lv)
        return levels

    # ─── 오프셋 추천 ───────────────────────────────────────────
    def suggest_offsets(
        self,
        items: list[TocItem],
        top_k: int = 3,
        probe_count: int = 20,
        search_range_pages: int = 400,
        min_needle_len: int = 6,
    ) -> list[OffsetCandidate]:
        """본문에서 여러 제목의 등장 페이지를 모두 수집해
        (실페이지 − 표기페이지) 의 **최빈 오프셋**을 추천.

        개선 사항:
          - TOC 마지막 페이지 다음부터 검색하여 표지/목차 페이지의 우연 매칭 제거
          - 한 probe 의 첫 매칭만 쓰지 않고 모든 매칭의 offset 을 집계
          - 줄 시작(`line.lstrip().startswith(needle)`) 매칭으로 본문 중간의
            인용·언급에서의 잘못된 매칭 감소
          - 너무 짧은 제목(<= min_needle_len-1)은 다수 매칭을 유발하므로 후순위
        """
        if not items:
            return []

        # 긴 제목일수록 유일성이 높음 → 길이 내림차순으로 probe 선택
        candidates = [it for it in items if it.level == 0]
        if not candidates:
            candidates = list(items)
        # 짧은 needle 은 마지막으로
        candidates.sort(key=lambda it: -len(it.title.strip()))
        probes = candidates[:probe_count]

        # TOC 페이지 자체와 그 이전의 표지/속표지는 검색 범위에서 제외
        toc_pages = self.find_toc_pages()
        toc_pages_set = set(toc_pages)
        start_idx = max(toc_pages) if toc_pages else 0  # 0-based: i=start_idx -> PDF page (start_idx+1)

        all_offsets: list[int] = []
        matched_by_offset: dict[int, list[str]] = {}

        ws_re = re.compile(r"\s+")
        with pdfplumber.open(self.pdf_path) as pdf:
            search_end = min(len(pdf.pages), search_range_pages)
            for probe in probes:
                needle = probe.title.strip()
                if len(needle) < min_needle_len:
                    continue
                needle_norm = ws_re.sub("", needle)
                for i in range(start_idx, search_end):
                    page_1based = i + 1
                    if page_1based in toc_pages_set:
                        continue  # TOC 페이지 자체 제외
                    text = pdf.pages[i].extract_text() or ""
                    # 안전망: 점선 리더가 풍부한 페이지(목차성)는 건너뜀
                    if self._has_many_toc_lines(text):
                        continue
                    # 공백을 무시하여 줄바꿈/공백 흔들림에도 매칭되도록
                    text_norm = ws_re.sub("", text)
                    if needle_norm not in text_norm:
                        continue
                    offset = page_1based - probe.toc_page
                    if offset < -50 or offset > 500:
                        continue  # 비현실적 오프셋
                    all_offsets.append(offset)
                    matched_by_offset.setdefault(offset, []).append(probe.title)

        if not all_offsets:
            # 폴백: TOC 페이지 개수를 오프셋으로 추정
            return [OffsetCandidate(offset=len(toc_pages), confidence=0.2)]

        counter = Counter(all_offsets)
        total = sum(counter.values())
        return [
            OffsetCandidate(
                offset=off,
                confidence=cnt / total,
                matched_titles=matched_by_offset.get(off, []),
            )
            for off, cnt in counter.most_common(top_k)
        ]

    # ─── 책갈피 빌드 ───────────────────────────────────────────
    @staticmethod
    def build_bookmarks(
        items: list[TocItem],
        offset: int,
        *,
        organize_appendix: bool = True,
    ) -> list[Bookmark]:
        """TocItem + 오프셋 → Bookmark.

        ``organize_appendix=True`` (기본) 이면 본문 트리 뒤에
        Table/Figure/표/그림 항목을 가상 부모 아래로 모아 재배치한다.
        """
        base = [
            Bookmark(title=it.title, page=it.toc_page + offset, level=it.level)
            for it in items
        ]
        if organize_appendix:
            base = organize_appendix_bookmarks(base)
        return base
