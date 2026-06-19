"""스캔/이미지 PDF에서 'CHAPTER 1' 등 헤딩을 OCR로 인식해 책갈피(Bookmark) 생성.

기존 책갈피 자동 생성(텍스트 레이어 기반 toc/font)이 스캔본에서 0개가 나오는 한계를
보완한다. viewer/study/ocr.py(Tesseract, 단어 bbox)를 재사용:
  - 글자 높이(y1-y0)를 폰트 크기 대용으로 사용 → 본문보다 큰 줄을 헤딩 후보로.
  - 영문(CHAPTER/PART/PROLOGUE…)·한글(제N장/제N절/프롤로그…) 정규식.
  - '큰 글자 자동'(use_font_auto)은 호출자(다이얼로그)가 켤 때만 적용.
  - 스캔 페이지만 처리(scanned_only): decide_source 로 이미지 페이지 선별(디지털은 스킵).
Tesseract 미가용 시 RuntimeError(호출 워커가 처리).
"""
from __future__ import annotations

import re
from pathlib import Path
from statistics import median
from typing import Callable, Optional

import fitz

from viewer._vendor.pdf_bookmarker.core import Bookmark, clean_title
from viewer.study import ocr as _ocr

# ─── 헤딩 정규식 ──────────────────────────────────────────────────
_EN_NUMWORD = (r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
               r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
               r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)")
# CHAPTER 1 / CHAPTER ONE / CHAPTER IV / PART 2 …
# OCR가 장식체(아웃라인) 'CHAPTER'를 'GCGHAPTER'처럼 깨뜨리는 경우가 잦아,
# 안정적 코어 'H A P T E R'(앞 0~4 잡글자 허용)로 관대하게 매칭한다.
_EN_NUM = rf"(\d{{1,3}}|[ivxlcdm]{{1,6}}|{_EN_NUMWORD})"
_EN_CHAP = re.compile(rf"^\s*[a-z]{{0,4}}h[a4]pter\s+{_EN_NUM}\b", re.I)
_EN_PART = re.compile(rf"^\s*(part|book|volume)\s+{_EN_NUM}\b", re.I)
_EN_SPECIAL = re.compile(
    r"^\s*(prologue|epilogue|foreword|preface|introduction|afterword|appendix)\b", re.I)
# 한글: 제1장 / 1장 / 제 1 장, 제1절, 프롤로그 등
_KO_CHAP = re.compile(r"^\s*제?\s*\d+\s*장\b")
_KO_SEC = re.compile(r"^\s*제?\s*\d+\s*절\b")
_KO_SPECIAL = re.compile(r"^\s*(프롤로그|에필로그|머리말|머릿말|서문|서론|들어가며|부록|후기)\b")

_MIN_LEN = 2
_MAX_LEN = 80
_LETTER = re.compile(r"[A-Za-z가-힣]")


# 같은 페이지 다중 책갈피 정리용 — 숫자(1·1.1·1.1.1)·한글 구조단위(편/부/관/조…)
_NUM_TITLE = re.compile(r"^\s*\d+(?:\.\d+){0,4}\.?(?:\s|$)")
_KO_STRUCT = re.compile(r"^\s*제?\s*\d+\s*(?:편|부|장|절|관|조|항|강|과|회|차)\b")


def is_heading_title(title: str) -> bool:
    """제목이 '장/절·CHAPTER·번호(1/1.1)·한글 구조단위' 등 헤딩형인지."""
    t = (title or "").strip()
    if not t:
        return False
    if regex_level(t) is not None:
        return True
    if _KO_STRUCT.match(t):
        return True
    if _NUM_TITLE.match(t):
        return True
    return False


def prefer_heading_per_page(bookmarks: list) -> list:
    """같은 페이지에 책갈피가 여럿이면 헤딩형(제목명/숫자)만 남기고 나머지 제거.
    헤딩형이 하나도 없거나 전부 헤딩형이면 그대로 둔다(임의 삭제 방지). 입력 순서 유지."""
    from collections import defaultdict
    groups = defaultdict(list)
    for b in bookmarks:
        groups[b.page].append(b)
    drop = set()
    for _page, group in groups.items():
        if len(group) <= 1:
            continue
        heads = [b for b in group if is_heading_title(b.title)]
        if heads and len(heads) < len(group):
            for b in group:
                if not is_heading_title(b.title):
                    drop.add(id(b))
    return [b for b in bookmarks if id(b) not in drop]


def regex_level(text: str) -> Optional[int]:
    """헤딩 정규식 일치 시 레벨(0=장·특수, 1=절). 미일치 None."""
    t = text.strip()
    if _KO_SEC.match(t):
        return 1
    if _KO_CHAP.match(t) or _KO_SPECIAL.match(t):
        return 0
    if _EN_CHAP.match(t) or _EN_PART.match(t) or _EN_SPECIAL.match(t):
        return 0
    return None


def _canonical_title(text: str) -> str:
    """정규식 헤딩의 표제를 표준화(OCR로 깨진 'GCGHAPTER 1' → 'CHAPTER 1')."""
    t = text.strip()
    m = _EN_CHAP.match(t)
    if m:
        return f"CHAPTER {m.group(1).upper()}"
    m = _EN_PART.match(t)
    if m:
        return f"{m.group(1).upper()} {m.group(2).upper()}"
    m = _EN_SPECIAL.match(t)
    if m:
        return m.group(1).upper()
    return clean_title(t)


def _group_lines(words: list[dict]) -> list[dict]:
    """OCR 단어(bbox, 픽셀)들을 줄 단위로 묶어 [{text,h,x0,x1,y0}] 반환."""
    ws = sorted(words, key=lambda w: (w["y0"], w["x0"]))
    lines: list[dict] = []
    for w in ws:
        h = w["y1"] - w["y0"]
        if lines and abs(w["y0"] - lines[-1]["y0"]) <= max(4.0, 0.6 * lines[-1]["h"]):
            ln = lines[-1]
            ln["words"].append(w)
            ln["h"] = max(ln["h"], h)
            ln["x1"] = max(ln["x1"], w["x1"])
        else:
            lines.append({"y0": w["y0"], "h": h, "x0": w["x0"],
                          "x1": w["x1"], "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
        ln["text"] = " ".join(w["surface"] for w in ln["words"]).strip()
    return lines


def _is_pagenum_or_noise(text: str) -> bool:
    s = text.strip()
    if len(s) < _MIN_LEN or len(s) > _MAX_LEN:
        return True
    non_space = re.sub(r"\s", "", s)
    if not non_space:
        return True
    # 글자 비율이 낮으면(숫자·기호 위주) 잡음
    if len(_LETTER.findall(non_space)) / len(non_space) < 0.4:
        return True
    return False


def extract_ocr_bookmarks(
    pdf_path: str | Path,
    *,
    dpi: int = 150,
    lang: str = "eng+kor",
    use_font_auto: bool = True,
    font_ratio: float = 1.5,
    scanned_only: bool = True,
    progress: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[Bookmark]:
    """스캔 PDF를 OCR해 헤딩 책갈피 리스트를 만든다.

    dpi: 헤딩은 크고 드물어 150이면 충분(속도↑). font_ratio: 본문 높이 대비 헤딩 배수.
    use_font_auto: 정규식 외에 '본문보다 큰 줄'도 헤딩으로. scanned_only: 이미지 페이지만.
    """
    _ocr.ensure_tesseract()      # 미가용 시 ocr_image 단계에서 RuntimeError
    doc = fitz.open(str(pdf_path))
    try:
        total = doc.page_count
        # 1) 대상 페이지 선별 + OCR → 페이지별 줄 목록
        page_lines: dict[int, list[dict]] = {}
        all_heights: list[float] = []
        for pi in range(total):
            if should_cancel and should_cancel():
                break
            if progress:
                progress(pi, total, f"OCR {pi + 1}/{total}p")
            page = doc.load_page(pi)
            if scanned_only:
                src, _ = _ocr.decide_source(page)
                if src != "ocr":
                    continue            # 디지털 페이지 — 폰트 방식이 처리할 영역
            img, _, _ = _ocr.render_page(doc, pi, dpi=dpi)
            try:
                res = _ocr.ocr_image(img, lang=lang)
            except Exception:
                continue
            lines = _group_lines(res.get("words", []))
            lines = [ln for ln in lines if not _is_pagenum_or_noise(ln["text"])]
            if not lines:
                continue
            page_lines[pi] = lines
            all_heights.extend(ln["h"] for ln in lines)

        bookmarks = _bookmarks_from_page_lines(
            page_lines, use_font_auto=use_font_auto, font_ratio=font_ratio)
        if progress:
            progress(total, total, f"헤딩 {len(bookmarks)}개")
        return bookmarks
    finally:
        doc.close()


def _bookmarks_from_page_lines(page_lines: dict, *, use_font_auto: bool = True,
                               font_ratio: float = 1.5) -> list:
    """페이지별 줄목록(text·h)에서 헤딩 책갈피 추출(렌더/OCR 무관 — 공용 코어)."""
    all_heights = [ln["h"] for lines in page_lines.values() for ln in lines]
    if not all_heights:
        return []
    body_h = median(all_heights)
    big_h = body_h * font_ratio
    from collections import Counter
    norm = lambda s: re.sub(r"\s+", " ", s.strip()).lower()
    cand_counter: Counter = Counter()
    for lines in page_lines.values():
        seen_pg = set()
        for ln in lines:
            k = norm(ln["text"])
            if k and k not in seen_pg:
                cand_counter[k] += 1
                seen_pg.add(k)
    npages = max(1, len(page_lines))
    repeated = {k for k, c in cand_counter.items() if c >= max(4, int(npages * 0.3))}
    bookmarks: list = []
    for pi in sorted(page_lines):
        page_done = set()
        page_max_h = max(ln["h"] for ln in page_lines[pi])
        for ln in page_lines[pi]:
            text = ln["text"]
            if norm(text) in repeated:
                continue
            lvl = regex_level(text)
            from_regex = lvl is not None
            if lvl is None and use_font_auto:
                if ln["h"] >= big_h and ln["h"] >= page_max_h * 0.92:
                    lvl = 0
            if lvl is None:
                continue
            title = _canonical_title(text) if from_regex else clean_title(text)
            if not title or title in page_done:
                continue
            page_done.add(title)
            bookmarks.append(Bookmark(title=title, page=pi + 1, level=lvl))
    return bookmarks


def extract_headings_from_store(store, file_key: str, page_count: int, *,
                                use_font_auto: bool = False,
                                font_ratio: float = 1.5) -> list:
    """260606-11(시간단축): 이미 만들어진 study.db 의 OCR 단어좌표(ocr_word)를
    재사용해 책갈피(헤딩)를 추출 — 재렌더/재OCR 없음. 같은 페이지 다중은 헤딩만."""
    page_lines: dict = {}
    for p in range(int(page_count)):
        try:
            words = store.get_page_words(file_key, p) or []
        except Exception:
            words = []
        if not words:
            continue
        lines = _group_lines(words)
        lines = [ln for ln in lines if not _is_pagenum_or_noise(ln["text"])]
        if lines:
            page_lines[p] = lines
    bms = _bookmarks_from_page_lines(page_lines, use_font_auto=use_font_auto,
                                     font_ratio=font_ratio)
    return prefer_heading_per_page(bms)
