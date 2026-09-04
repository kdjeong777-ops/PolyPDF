# -*- coding: utf-8 -*-
"""목차(차례) 페이지 → 책갈피 표 (260904-1, 마스터 SOT §4.4).

내장 `pdf_bookmarker.toc_extractor` 의 파서는 점선 리더(`제목 ……… 12`) 형식만 알아
**OCR 텍스트층이 있는 스캔본**(예: `제목 / 12`, 한 줄에 두 항목, `ll`→11 같은 숫자
오인식, 쪽번호 없는 장 제목)을 0건으로 냈다(사용자 표본 `검사의이해`: 352쪽, 차례 6~11쪽).
이 모듈은 그 상위 호환 파서다 — Qt 비의존, 순수 함수. 검토 창(`toc_review_dialog`)과
`BookmarkerWorker` 가 쓴다.

행(dict) 스키마: {"title": str, "toc_page": int|None, "level": int, "page": int|None, "src": str}
  - toc_page : 목차에 인쇄된 쪽번호(없으면 None — 장 제목 줄 등)
  - page     : 실제 PDF 쪽(1-based). 오프셋 적용 결과 또는 사용자가 고친 값.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

# ── OCR 숫자 오인식 교정 ─────────────────────────────────────────────
_OCR_DIGIT = str.maketrans({"l": "1", "I": "1", "|": "1", "O": "0", "o": "0", "S": "5", "B": "8"})


def fix_ocr_number(s: str) -> Optional[int]:
    """'ll'→11, 'lOO'→100, '3l9'→319, '1 63'→163. 숫자로 못 만들면 None."""
    if s is None:
        return None
    t = re.sub(r"\s+", "", str(s)).translate(_OCR_DIGIT)
    if not t or not t.isdigit():
        return None
    v = int(t)
    return v if 0 < v < 10000 else None


_ROMAN = re.compile(r"^(?=[ivxlcdm]+$)m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.I)

# 줄 끝 쪽번호 표기들: `… 12` / `  12` / `/ 12` / `/12` / `Materials85`
_SEP_PAGE = re.compile(
    r"^(?P<title>.+?)\s*(?:[·•．․‥…⋯]{2,}|\.{3,}|/|\s{2,})\s*(?P<page>[0-9lIO|oSB][0-9lIO|oSB ]{0,4})\s*$")
_TIGHT_PAGE = re.compile(r"^(?P<title>.+?[A-Za-z가-힣\)\]])(?P<page>\d{1,4})\s*$")
_ROMAN_PAGE = re.compile(r"^(?P<title>.+?)\s*(?:/|\.{3,}|[·…]{2,}|\s{2,})\s*(?P<page>[ivxlcdmIVXLCDM]{1,6})\s*$")
# 한 줄에 여러 항목: `1)검사점수/10 2)반응의내용과주제/ll` — '/숫자' 뒤에 공백+새 항목이 이어짐
_MULTI_END = re.compile(r"/\s?[0-9lIO|oSB]{1,4}(?=\s+\S)")


def _split_multi(text: str) -> list[str]:
    """'/쪽번호' 가 끝난 자리마다 잘라 항목별 조각으로."""
    parts, last = [], 0
    for m in _MULTI_END.finditer(text):
        parts.append(text[last:m.end()]); last = m.end()
    parts.append(text[last:])
    return [s for s in parts if s.strip()]
# 하위 번호(2단계) `1)`, `(1)`, `가.`, `a.`  /  본문 번호(1단계) `1 `, `1.`, `2. SSCT`
_SUB_NUM = re.compile(r"^\(?\d{1,2}\)|^[가-힣]\.\s|^[a-zA-Z]\.\s")
_MAIN_NUM = re.compile(r"^\d{1,2}[\.\s]\s*\S")
_CHAPTER = re.compile(r"^(제\s*\d+\s*[장부편]|chapter\s+\d+|part\s+\d+|부록\s*\S*|참고\s*문헌|찾아보기|색인|서문|머리말)", re.I)
_NOISE = re.compile(r"^[\W_\d\s]{0,3}$|차\s*[례려]|CONTENTS", re.I)


def _clean_title(t: str) -> str:
    t = re.sub(r"[·•．․‥…⋯\.]{2,}\s*$", "", t)          # 뒤 점선 제거
    t = re.sub(r"\s+", " ", t).strip(" /-–—.:")
    return t


def parse_line(text: str) -> list[dict]:
    """한 줄 → 항목 0~N개. 쪽번호 없는 장 제목은 toc_page=None 으로 남긴다."""
    text = (text or "").strip()
    if not text or _NOISE.match(text):
        return []
    parts = _split_multi(text) if "/" in text else [text]
    out = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = _SEP_PAGE.match(part) or _TIGHT_PAGE.match(part)
        if m:
            title = _clean_title(m.group("title"))
            page = fix_ocr_number(m.group("page"))
            if title and page:
                out.append({"title": title, "toc_page": page})
                continue
        mr = _ROMAN_PAGE.match(part)
        if mr and _ROMAN.match(mr.group("page")):
            title = _clean_title(mr.group("title"))
            if title:
                out.append({"title": title, "toc_page": None, "front": True})
            continue
        # 쪽번호 없는 줄 — 장 제목이면 채택(쪽은 첫 하위 항목에서 상속)
        if _CHAPTER.match(part):
            out.append({"title": _clean_title(part), "toc_page": None})
    return out


def infer_level(title: str) -> int:
    s = title.strip()
    if _CHAPTER.match(s):
        return 0
    if _SUB_NUM.match(s):
        return 2
    if _MAIN_NUM.match(s):
        return 1
    return -1                                   # 미정 → x 좌표로


def _levels_from_x(xs: list[float]) -> list[int]:
    if not xs:
        return []
    base = min(xs)
    lv = []
    for x in xs:
        d = x - base
        lv.append(0 if d < 8 else 1 if d < 24 else 2)
    return lv


def _page_lines(pdf_path, pages: Iterable[int]) -> list[tuple[int, float, str]]:
    """(쪽, x0, 줄) 목록 — pdfplumber 줄 묶음. 텍스트층이 비면 OCR 폴백."""
    out = []
    try:
        import pdfplumber
        from viewer._vendor.pdf_bookmarker.toc_extractor import TocBookmarkExtractor as _T
        with pdfplumber.open(str(pdf_path)) as pdf:
            for pno in pages:
                if pno < 1 or pno > len(pdf.pages):
                    continue
                lines = _T._group_lines_by_y(pdf.pages[pno - 1])
                if not lines:
                    lines = _ocr_lines(pdf_path, pno)
                out.extend((pno, x0, t) for x0, t in lines)
    except Exception:
        for pno in pages:
            out.extend((pno, x0, t) for x0, t in _ocr_lines(pdf_path, pno))
    return out


def _ocr_lines(pdf_path, pno: int) -> list[tuple[float, str]]:
    """텍스트층이 없는 목차 쪽 — Tesseract 로 줄을 얻는다(없으면 빈 목록)."""
    try:
        import fitz
        from viewer.study import ocr as _ocr
        doc = fitz.open(str(pdf_path))
        try:
            res = _ocr.build_page(doc, pno - 1, lang="kor+eng", force_ocr=True)
        finally:
            doc.close()
        text = res.get("text") or ""
        return [(0.0, ln) for ln in text.splitlines() if ln.strip()]
    except Exception:
        return []


def parse_toc_pages(pdf_path, pages: Iterable[int]) -> list[dict]:
    """지정한 목차 쪽들 → 행 목록(순서 유지). 쪽번호 없는 장 제목은 첫 하위 쪽을 상속."""
    rows = []
    for pno, x0, text in _page_lines(pdf_path, list(pages)):
        for it in parse_line(text):
            it["src"] = f"p{pno}"
            it["x0"] = x0
            rows.append(it)
    # 레벨: 번호 패턴 우선, 나머지는 x 좌표 클러스터
    unresolved = []
    for i, r in enumerate(rows):
        lv = infer_level(r["title"])
        if lv >= 0:
            r["level"] = lv
        else:
            r["level"] = 0
            unresolved.append(i)
    has_chapter = any(rows[i]["level"] == 0 for i in range(len(rows)) if i not in unresolved)
    xs = [rows[i]["x0"] for i in unresolved]
    for i, lv in zip(unresolved, _levels_from_x(xs)):
        # 장 제목이 따로 있으면 미정 항목은 최소 1단계(장 아래)로
        rows[i]["level"] = max(1, lv) if has_chapter else lv
    # 장 제목(쪽 없음) ← 다음 항목의 쪽 상속
    for i, r in enumerate(rows):
        if r.get("toc_page") is None and not r.get("front"):
            for nxt in rows[i + 1:]:
                if nxt.get("toc_page"):
                    r["toc_page"] = nxt["toc_page"]
                    break
    # 앞 부속(로마 숫자 쪽) 은 표에서 뺀다 — 실제 쪽을 알 수 없음
    rows = [r for r in rows if r.get("toc_page")]
    for r in rows:
        r.pop("x0", None); r.pop("front", None)
        r["page"] = None
    return rows


def parse_page_spec(spec: str, page_count: int) -> list[int]:
    """'6-11, 14' → [6,7,8,9,10,11,14] (1-based, 범위 밖 제거, 중복 제거)."""
    out = []
    for tok in re.split(r"[,\s]+", (spec or "").strip()):
        if not tok:
            continue
        m = re.match(r"^(\d+)\s*[-~]\s*(\d+)$", tok)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out.extend(range(min(a, b), max(a, b) + 1))
        elif tok.isdigit():
            out.append(int(tok))
    seen, res = set(), []
    for p in out:
        if 1 <= p <= page_count and p not in seen:
            seen.add(p); res.append(p)
    return res


def _title_needle(title: str, head_chars: int = 10) -> str:
    """제목 → 대조용 앞부분(번호·'제N장' 제거, 공백·기호 제거, 소문자)."""
    # 번호·표제 접두 제거: '1)', '1.', '제3장', 'Chapter 2', 'Part II', 'Section 3' — 본문 쪽에는
    # 보통 제목만 인쇄돼 있어 접두를 남기면 대조가 실패한다.
    core = re.sub(r"^\(?\d{1,2}\)?[\.\s]*|^제\s*\d+\s*[장부편]\s*|^(chapter|part|section|unit)\s+[\divxlc]+[\.\s:]*",
                  "", title or "", flags=re.I)
    return _norm(core)[:head_chars]


def suggest_offsets(pdf_path, rows: list[dict], toc_pages: list[int],
                    *, window: int = 120, probes: int = 60) -> list[tuple[int, float]]:
    """(실제 쪽 − 목차 쪽) 오프셋 후보 [(offset, confidence)] — 신뢰도 내림차순.

    내장 추정기는 제목 **전체** 일치를 요구해 OCR 텍스트층(잡글자)에서 무너졌다(표본:
    후보 3개가 각 3.6%). 여기서는 [제목 대조] 와 같은 **앞부분 부분일치**(`_title_needle`)로,
    각 항목의 목차 쪽 이후 `window` 쪽 안에서 제목이 처음 나오는 쪽을 찾아 (실제−목차)를 모으고
    최빈값을 낸다. 상위 레벨·긴 제목을 우선 표본으로 쓴다."""
    toc_set = set(int(p) for p in (toc_pages or []))
    last_toc = max(toc_set) if toc_set else 0
    cand = [r for r in rows if r.get("toc_page") and len(_title_needle(r["title"])) >= 6]
    cand.sort(key=lambda r: (int(r.get("level", 0)), -len(_title_needle(r["title"]))))
    cand = cand[:probes]
    from collections import Counter
    votes = Counter()
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        try:
            n = doc.page_count
            cache = {}
            def page_norm(pg):
                if pg not in cache:
                    cache[pg] = _norm(doc.load_page(pg - 1).get_text() or "")
                return cache[pg]
            for r in cand:
                needle = _title_needle(r["title"])
                tp = int(r["toc_page"])
                lo = max(last_toc + 1, tp)                  # 실제 쪽은 목차 쪽 이상(오프셋 ≥ 0)
                hi = min(n, tp + window)
                for pg in range(lo, hi + 1):
                    if pg in toc_set:
                        continue
                    if needle in page_norm(pg):
                        votes[pg - tp] += 1
                        break                               # 첫 등장만(이후 인용 제외)
        finally:
            doc.close()
    except Exception:
        pass
    if not votes:
        return [(last_toc, 0.2)]
    total = sum(votes.values())
    return [(off, cnt / total) for off, cnt in votes.most_common(5)]


def apply_offset(rows: list[dict], offset: int, page_count: int, *, keep_manual: bool = True) -> None:
    """toc_page + offset → page (수동으로 고친 행은 keep_manual 이면 유지)."""
    for r in rows:
        if keep_manual and r.get("manual"):
            continue
        tp = r.get("toc_page")
        if tp:
            r["page"] = max(1, min(page_count, int(tp) + int(offset)))


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s or "").lower()


def verify_rows(pdf_path, rows: list[dict], *, head_chars: int = 10) -> dict:
    """행별로 '실제 쪽에 제목이 있는가' 검사 → {index: True/False}. 비교용(저장에 영향 없음).

    제목 앞부분(head_chars 자)만 공백·기호 제거 후 그 쪽 텍스트에서 찾는다 — OCR 텍스트층의
    잡글자에도 견디도록 부분 일치."""
    res = {}
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        try:
            cache = {}
            for i, r in enumerate(rows):
                pg = r.get("page")
                if not pg or not (1 <= pg <= doc.page_count):
                    res[i] = False; continue
                if pg not in cache:
                    cache[pg] = _norm(doc.load_page(pg - 1).get_text() or "")
                needle = _title_needle(r["title"], head_chars)     # 오프셋 추정과 같은 규칙
                res[i] = bool(needle) and needle in cache[pg]
        finally:
            doc.close()
    except Exception:
        pass
    return res


def to_bookmarks(rows: list[dict]) -> list[tuple[str, int, int]]:
    """검토 표 → (title, page_1based, level) — 저장 경로 입력."""
    return [(r["title"], int(r["page"]), int(r.get("level", 0)))
            for r in rows if r.get("title") and r.get("page")]
