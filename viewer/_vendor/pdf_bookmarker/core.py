"""책갈피 자료형과 텍스트 출력 포맷터."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


BOOKMARK_SUFFIX = ",Black,Bold,notitalic,open,FitPage"

_DOT_LEADER_RE = re.compile(r"[·•．․‥…⋯]|\.{2,}")
_MULTI_SPACE_RE = re.compile(r"\s+")


@dataclass
class Bookmark:
    """최종 책갈피. PDF 페이지는 1-based 절대 페이지."""
    title: str
    page: int
    level: int = 0


@dataclass
class TocItem:
    """목차에서 추출된 원시 항목. 페이지는 목차에 표기된 값(보정 전)."""
    title: str
    toc_page: int
    level: int = 0


@dataclass
class OffsetCandidate:
    """오프셋 후보. final_page = toc_page + offset."""
    offset: int
    confidence: float
    matched_titles: list[str] = field(default_factory=list)


def clean_title(raw: str) -> str:
    """제목 정제: 점선 리더 제거, 공백 정리, '/' → '／' 치환."""
    if not raw:
        return ""
    s = _DOT_LEADER_RE.sub(" ", raw)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    # 구분자 충돌 방지
    s = s.replace("/", "／")
    return s


def format_bookmark_line(bm: Bookmark) -> str:
    """단일 책갈피 → 한 줄 문자열 (개행 미포함)."""
    indent = "\t" * max(bm.level, 0)
    title = clean_title(bm.title)
    return f"{indent}{title}/{bm.page}{BOOKMARK_SUFFIX}"


def format_bookmarks(bookmarks: list[Bookmark]) -> str:
    """책갈피 리스트 → 텍스트(끝에 개행 1개)."""
    if not bookmarks:
        return ""
    return "\n".join(format_bookmark_line(bm) for bm in bookmarks) + "\n"


def write_bookmark_file(bookmarks: list[Bookmark], out_path: str | Path,
                        encoding: str = "utf-8") -> Path:
    """책갈피를 텍스트 파일로 저장. UTF-8 기본, BOM 없음."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(format_bookmarks(bookmarks), encoding=encoding)
    return p


# ─── 부속 항목(Table/Figure/표/그림) 재배치 ─────────────────────────
# 부속 그룹 분류 — 제목의 시작이 다음 패턴 중 하나면 해당 그룹으로 모음.
_APPENDIX_GROUPS: list[tuple[str, "re.Pattern[str]"]] = [
    ("Table",  re.compile(r"^Table\s+",  re.IGNORECASE)),
    ("Figure", re.compile(r"^Figure\s+", re.IGNORECASE)),
    ("표",     re.compile(r"^표\s*\d")),
    ("그림",   re.compile(r"^그림\s*\d")),
]
# 기존 "List of Tables/Figures" 또는 "표 목차"/"그림 목차" 항목은 본문 트리에서
# 제거 — 우리가 가상 부모를 새로 만들기 때문에 중복을 방지한다.
_APPENDIX_HEADER_PAT = re.compile(
    r"^(List of (Tables|Figures|Abbreviations)|표\s*목차|그림\s*목차)\b"
)


def organize_appendix_bookmarks(bookmarks: list[Bookmark]) -> list[Bookmark]:
    """본문 트리 뒤로 Table/Figure/표/그림 항목을 모아 가상 부모 아래에 배치.

    - 분류된 항목은 본문 트리에서 빠지고, 가상 부모 책갈피(`Table` 등) 아래
      level 1 자식으로 다시 들어간다.
    - 가상 부모의 페이지는 해당 그룹 첫 자식의 페이지.
    - 입력 순서를 유지 — TOC 출현 순서대로.
    """
    if not bookmarks:
        return list(bookmarks)

    main: list[Bookmark] = []
    groups: dict[str, list[Bookmark]] = {label: [] for label, _ in _APPENDIX_GROUPS}

    for bm in bookmarks:
        t = bm.title.lstrip()
        if _APPENDIX_HEADER_PAT.match(t):
            # "List of Tables" 같은 기존 헤더 — 가상 부모로 대체할 것이므로 제거
            continue
        matched = False
        for label, pat in _APPENDIX_GROUPS:
            if pat.match(t):
                groups[label].append(bm)
                matched = True
                break
        if not matched:
            main.append(bm)

    if not any(groups.values()):
        return main

    result = list(main)
    for label, _ in _APPENDIX_GROUPS:
        items = groups[label]
        if not items:
            continue
        result.append(Bookmark(title=label, page=items[0].page, level=0))
        for it in items:
            result.append(Bookmark(title=it.title, page=it.page, level=1))
    return result
