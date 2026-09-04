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
_CHAPTER = re.compile(r"^(제\s*\d+\s*[장부편]|chapter\s+\d+|part\s+\d+|부록\s*\S*|참고\s*문헌|찾아보기|색인|서문|머리말"
                      r"|(?:appendix|references|bibliography|index|preface|foreword|acknowledg\w*)\b)", re.I)   # 260904-5: 영문 장 급
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
    # 260904-4: **번호가 빠진 형제** — OCR 이 '2.' 를 통째로 빠뜨리면 그 줄은 번호 폭만큼
    #   오른쪽에서 시작해(표본: x0 100.8 → 111.6) x 클러스터가 한 단계 아래로 내린다.
    #   바로 위쪽의 번호 있는 항목보다 2~18pt 만 더 들어갔으면 **같은 레벨**로 본다.
    still = []
    for i in unresolved:
        ref = None
        for k in range(i - 1, -1, -1):
            if k in unresolved:
                continue
            if rows[k]["level"] == 0 and _CHAPTER.match(rows[k]["title"]):
                break                                   # 장 경계 — 그 위로는 보지 않는다
            ref = rows[k]; break
        if ref is not None and 2.0 <= (rows[i]["x0"] - ref["x0"]) <= 18.0:
            rows[i]["level"] = ref["level"]
            rows[i]["num_dropped"] = True
            continue
        # 260904-5: **같은 x 에서 시작하는 앞선 번호 항목**(같은 장 안) 이 있으면 그 레벨.
        #   표본: '5. 해석' 을 OCR 이 '戶 해석' 으로 읽어 번호 패턴을 잃었지만 x0 99.6 은
        #   '4 각 지수점수…'(레벨 1) 와 같다 → 레벨 1 (x 클러스터는 2 로 내렸다).
        same = None
        for k in range(i - 1, -1, -1):
            if k in unresolved:
                continue
            if rows[k]["level"] == 0 and _CHAPTER.match(rows[k]["title"]):
                break
            if abs(rows[i]["x0"] - rows[k]["x0"]) <= 2.5:
                same = rows[k]; break
        if same is not None:
            rows[i]["level"] = same["level"]
            rows[i]["num_dropped"] = True
        else:
            still.append(i)
    unresolved = still
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
    # 260904-5: OCR 이 떨어뜨린 앞 번호는 **표를 만들 때 바로 복원**한다(사용자는 표를 열자마자
    #   '2. 심리검사는…' 을 기대 — 버튼을 눌러야만 채워지면 '여전히 없다' 로 보인다).
    #   근거 있는 묶음만: 같은 부모 아래 형제 중 번호 있는 항목이 하나라도 있을 때(evidence_only).
    #   번호가 아예 없는 차례는 손대지 않는다 — [번호 채우기] 버튼은 형식 변경·전체 채움용으로 남는다.
    # 260904-8: 목차 쪽이 중간에 줄어드는 행(두 단 배치를 OCR 이 섞어 읽음·숫자 누락)을 바로잡는다 — 번호 복원보다 먼저
    sort_by_toc_page(rows)
    renumber_rows(rows, evidence_only=True)
    return rows


# ── 260904-8: 목차 쪽 순서 ──────────────────────────────────────────────
_LIST_START = re.compile(r"^[\[<(【]?\s*(?P<kind>표|그림|사진|도표|table|figure|fig)\.?\s*[A-Z]?[\.\-]?\s*\d", re.I)
_LIST_HEAD = re.compile(r"^(?P<kind>표|그림|사진|도표)\s*(차례|목차|목록)")


def _page_segments(rows: list[dict]) -> list[list[int]]:
    """쪽 번호가 처음부터 다시 시작하는 구간 — 일반 목차 / 표 목록 / 그림 목록 … (제목 패턴으로 나눈다)."""
    segs, cur, kind = [], [], None
    for i, r in enumerate(rows):
        t = str(r.get("title") or "").strip()
        m = _LIST_HEAD.match(t) or _LIST_START.match(t)
        k = m.group("kind").lower() if m else None
        if k is not None and k != kind:
            if cur:
                segs.append(cur)
            cur, kind = [], k
        cur.append(i)
    if cur:
        segs.append(cur)
    return segs


def _repair_candidates(page: int) -> list[int]:
    """OCR 이 자릿수를 떨어뜨린 쪽 번호의 후보: 앞자리 누락(20→120), 뒷자리 누락(31→31x, 3→3xx)."""
    c = [page + 100 * k for k in (1, 2, 3)]
    c += [page * 10 + d for d in range(10)]
    c += [page * 100 + d for d in range(100)]
    return sorted(set(c))


def _lnds(keys: list[int]) -> set:
    """가장 긴 비감소 부분수열의 인덱스(O(n²) — 목차는 수백 행)."""
    n = len(keys)
    if not n:
        return set()
    best = [1] * n; prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if keys[j] <= keys[i] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i = max(range(n), key=lambda k: best[k])
    out = set()
    while i >= 0:
        out.add(i); i = prev[i]
    return out


def existing_rows(pdf_path) -> list[dict]:
    """PDF 에 이미 들어 있는 책갈피 → 검토 표 행(260904-10).

    fitz 의 레벨은 1부터라 표(0=장)에 맞춰 1 을 뺀다. 목차 쪽은 없고(원문 차례를 모른다)
    실제 쪽만 채운다 — 표에서 제목·레벨·쪽을 고쳐 다시 저장하는 '기존 책갈피 수정' 경로의 입력."""
    try:
        import fitz
    except Exception:
        return []
    rows = []
    try:
        d = fitz.open(str(pdf_path))
        try:
            for item in d.get_toc(simple=True) or []:
                lv, title, page = item[0], item[1], item[2]
                if not str(title).strip():
                    continue
                rows.append({"title": str(title).strip(), "toc_page": None,
                             "page": (int(page) if int(page) > 0 else None),
                             "level": max(0, int(lv) - 1), "src": "existing"})
        finally:
            d.close()
    except Exception:
        return []
    return rows


def sort_by_toc_page(rows: list[dict]) -> int:
    """목차 쪽이 중간에 줄어들지 않도록 (260904-8). 바뀐 행 수를 돌려준다.

    구간(`_page_segments`)마다: ① 줄어든 쪽이 자릿수 누락으로 보이면 **번호를 고친다**(앞뒤 순서 안에 드는 후보 —
    20→120, 31→311, 3→312; `repaired`), ② 그래도 순서 밖인 행은 **가장 긴 비감소 열에 속하지 않는 행**으로 보고
    쪽 순서에 맞는 자리(그 쪽 이하의 마지막 행 뒤)로 옮긴다(`moved`). 표·그림 목록은 쪽이 처음부터 시작하므로 구간을 나눈다.
    옮긴/고친 행은 검토 표에서 목차 쪽 셀을 파란 배경으로 표시한다.
    기준 열은 목차 쪽 — 목차 쪽이 하나도 없으면(기존 책갈피 수정 경로) 실제 쪽으로 본다(260904-10)."""
    changed = 0
    out = []
    field = "toc_page" if any(r.get("toc_page") for r in rows) else "page"
    for seg in _page_segments(rows):
        sub = [rows[i] for i in seg]
        keys = []
        for r in sub:
            p = r.get(field)
            keys.append(int(p) if p else (keys[-1] if keys else 0))
        # ① 자릿수 복원
        prevmax = 0
        for j, r in enumerate(sub):
            if keys[j] >= prevmax:
                prevmax = keys[j]; continue
            if not r.get(field):
                continue
            nxt = next((keys[k] for k in range(j + 1, len(sub)) if keys[k] >= prevmax), None)
            hi = nxt if nxt is not None else prevmax + 30
            cand = next((c for c in _repair_candidates(keys[j]) if prevmax <= c <= hi), None)
            if cand is not None:
                r[field] = cand; r["repaired"] = True; keys[j] = cand; changed += 1
                prevmax = cand
        # ② 순서 밖 행 이동
        keep = _lnds(keys)
        result = [(keys[j], sub[j]) for j in range(len(sub)) if j in keep]
        for j in range(len(sub)):
            if j in keep:
                continue
            k = keys[j]
            pos = len(result)
            while pos > 0 and result[pos - 1][0] > k:
                pos -= 1
            sub[j]["moved"] = True; changed += 1
            result.insert(pos, (k, sub[j]))
        out.extend(r for _, r in result)
    rows[:] = out
    return changed


def number_after_sibling(rows: list[dict], row: int, *, style: Optional[str] = None) -> Optional[str]:
    """[번호 수정] (260904-8): row 의 번호 = 바로 위 같은 레벨 형제(더 얕은 레벨이 나오기 전까지 거슬러)의 번호 + 1.
    형제가 없으면 1. 형식은 지정값 ▶ 그 형제의 형식 ▶ 기본(레벨 1 '1.', 그 아래 '1)'). 장 행(레벨 0)은 None."""
    if row < 0 or row >= len(rows):
        return None
    lv = int(rows[row].get("level", 0))
    if lv <= 0:
        return None
    num, sib_style = 0, None
    for k in range(row - 1, -1, -1):
        l2 = int(rows[k].get("level", 0))
        if l2 < lv:
            break
        if l2 != lv:
            continue
        t = rows[k]["title"]
        m = _NUM_PREFIX.match(t)
        if m and not _CJK_GARBLE.match(t):
            try:
                num = int(re.sub(r"\D", "", m.group("num")))
            except ValueError:
                num = 0
            sib_style = _num_style(t)
            break
    gstyle = style or sib_style or ("dot" if lv == 1 else "paren")
    return _fmt_num(gstyle, num + 1, _strip_num(rows[row]["title"]))


def renumber_siblings_from(rows: list[dict], row: int, *, style: Optional[str] = None) -> int:
    """[번호 수정] (260904-8, 추가 지시 '다음 번호도 검토하여 적용'): row 를 위 형제 + 1 로 맞춘 뒤,
    그 아래 **같은 레벨 형제들**(더 얕은 레벨이 나오기 전까지)도 차례로 +1 씩 잇는다. 바뀐 행 수."""
    first = number_after_sibling(rows, row, style=style)
    if first is None:
        return 0
    changed = 0
    lv = int(rows[row].get("level", 0))
    if first != rows[row]["title"]:
        rows[row]["title"] = first; changed += 1
    for k in range(row + 1, len(rows)):
        l2 = int(rows[k].get("level", 0))
        if l2 < lv:
            break
        if l2 != lv:
            continue
        new = number_after_sibling(rows, k, style=style)
        if new is not None and new != rows[k]["title"]:
            rows[k]["title"] = new; changed += 1
    return changed


_TOC_HEADER = re.compile(r"(목\s*차|차\s*[례려레]|contents|table\s+of\s+contents)", re.I)


def find_toc_pages(pdf_path, scan_first_n: int = 40, min_entries: int = 4, gap: int = 1) -> list[int]:
    """목차로 보이는 쪽(1-based) 목록 — 관대한 파서(`parse_line`) 기준 (260904-2).

    내장 `find_toc_pages` 는 점선 리더·머리글 정규식만 보고 **연속이 끊기면 즉시 중단**해,
    표본(차례 6~11쪽)에서 7쪽 머리글이 '차려'로 깨지고 줄이 `제목 / 12` 형식이라 **6쪽만** 잡았다.
    여기서는 ① 상단 6줄에 머리글(차례/차려/목차/contents) 또는 ② 항목으로 읽히는 줄이
    `min_entries` 이상이면 목차 쪽으로 보고, 첫 목차 쪽 이후 `gap` 쪽까지 비어도 이어 본다."""
    found, last_hit = [], None
    try:
        import pdfplumber
        from viewer._vendor.pdf_bookmarker.toc_extractor import TocBookmarkExtractor as _T
        with pdfplumber.open(str(pdf_path)) as pdf:
            n = min(scan_first_n, len(pdf.pages))
            for i in range(n):
                pno = i + 1
                lines = [t_ for _x, t_ in _T._group_lines_by_y(pdf.pages[i])]
                if not lines:
                    lines = [t_ for _x, t_ in _ocr_lines(pdf_path, pno)] if found else []
                header = any(_TOC_HEADER.search(ln) for ln in lines[:6])
                entries = sum(len(parse_line(ln)) for ln in lines)
                is_toc = header or entries >= min_entries
                if is_toc:
                    found.append(pno); last_hit = pno
                elif found and last_hit is not None and pno - last_hit > gap:
                    break                                   # 목차 구간 종료
    except Exception:
        pass
    return found


def format_page_spec(pages: list[int]) -> str:
    """[6,7,8] → '6-8', [6] → '6', [6,7,9] → '6-7, 9'."""
    pages = sorted(set(int(p) for p in pages))
    if not pages:
        return ""
    out, start, prev = [], pages[0], pages[0]
    for p in pages[1:] + [None]:
        if p is not None and p == prev + 1:
            prev = p; continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        if p is not None:
            start = prev = p
    return ", ".join(out)


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


# 번호 형태: '1)' / '(1)' / '1.' / '1 ' / '제1장'. 앞의 낱 한자(戶·丁 등)는 OCR 이 숫자를 잘못 읽은 것.
_NUM_PREFIX = re.compile(r"^(?P<num>\(?\d{1,2}\)|\d{1,2}\.|\d{1,2}(?=\s))\s*")
_CJK_GARBLE = re.compile(r"^[\u4e00-\u9fff\u3400-\u4dbf]\s+")


def _num_style(title: str) -> Optional[str]:
    """번호가 있으면 그 스타일: 'paren'(1)) / 'dot'(1.) / 'bare'(1 ). 없으면 None."""
    m = _NUM_PREFIX.match(title or "")
    if not m:
        return None
    s = m.group("num")
    return "paren" if s.endswith(")") else "dot" if s.endswith(".") else "bare"


def _strip_num(title: str) -> str:
    t = _NUM_PREFIX.sub("", title or "", count=1)
    t = _CJK_GARBLE.sub("", t, count=1)
    return t.strip()


def _fmt_num(style: str, seq: int, core: str) -> str:
    if style == "paren":
        return f"{seq}){core}"
    if style == "dot":
        return f"{seq}. {core}"
    return f"{seq} {core}"


def renumber_rows(rows: list[dict], *, levels: tuple = (1, 2), style: Optional[str] = None,
                  evidence_only: bool = False, start: int = 0, end: Optional[int] = None,
                  reseq: bool = False) -> int:
    """같은 부모 아래 형제 항목에 순번을 채운다(260904-3). 바뀐 행 수를 돌려준다.

    evidence_only(260904-5): 묶음 안에 번호 있는 항목이 하나도 없으면 건너뛴다(파서 자동 복원용).
    start(260904-6): 이 행부터만 고친다(앞 행은 손대지 않되, 같은 묶음이면 그 번호에서 이어 센다).
    end(260904-6): 이 행 앞까지만(대화상자는 커서 행의 묶음 끝 — 뒤 장·그림 목록으로 번지지 않게).
    reseq(260904-6): 있는 번호도 형제 순서대로 다시 매긴다 — 레벨을 바꾼 뒤 남은 '6) 7)' 을 '1) 2)' 로.
      (파서 자동 복원은 False — 있는 번호는 원문 증거이므로 유지하고 빠진 것만 채운다.)

    OCR 텍스트층은 긴 줄에서 앞 번호 '1)' 를 통째로 빠뜨리거나(표본: '심리검사는 어떻게…')
    숫자를 한자로 읽는다('5 해석' → '戶 해석'). 규칙:
      - 형제 묶음 = 같은 레벨이 연속되는 구간(더 얕은 레벨이 나오면 끊김). levels 에 든 레벨만.
      - 묶음 안에 번호 있는 항목이 하나라도 있으면 그 스타일('1)'/'1.'/'1 ')을 쓰고, 없으면
        레벨 2 는 '1)', 레벨 1 은 '1 ' 로.
      - 번호 없는 항목·낱 한자로 시작하는 항목에만 순번을 붙인다(있는 번호는 그대로 두되 그 값에서
        이어 센다). 장 제목(레벨 0)은 손대지 않는다."""
    changed = 0
    n = len(rows)
    for lv in sorted(levels):                      # 얕은 레벨부터, 레벨별로 따로 묶는다(중첩 처리)
        i = 0
        while i < n:
            if int(rows[i].get("level", 0)) != lv:
                i += 1; continue
            j = i
            while j < n and int(rows[j].get("level", 0)) >= lv:   # 더 얕은 레벨이 나오면 묶음 끝
                j += 1
            group = [k for k in range(i, j) if int(rows[k].get("level", 0)) == lv]
            styles = [s for s in (_num_style(rows[k]["title"]) for k in group) if s]
            if evidence_only and not styles:
                i = j; continue
            if group and (group[-1] < start or (end is not None and group[0] >= end)):
                i = j; continue                            # 260904-6: 범위 밖 묶음은 그대로
            gstyle = style or (styles[0] if styles else ("paren" if lv >= 2 else "dot"))
            # 260904-4: 레벨 1 의 'bare'('1 제목') 는 OCR 이 '1.' 의 점을 떨어뜨린 것이 대부분 → 'dot' 로
            if style is None and gstyle == "bare" and lv <= 1:
                gstyle = "dot"
            seq = 0
            last_num = None                                # reseq: 직전 원문 번호(재시작 감지)
            for k in group:
                title = rows[k]["title"]
                m = _NUM_PREFIX.match(title)
                if end is not None and k >= end:
                    break
                if k < start:                              # 260904-6: 커서 앞 행 — 번호만 이어받는다
                    if m and not _CJK_GARBLE.match(title):
                        try:
                            seq = int(re.sub(r"\D", "", m.group("num")))
                        except ValueError:
                            seq += 1
                    else:
                        seq += 1
                    continue
                if reseq:                                  # 260904-6: 순서대로 다시 매김(있는 번호 무시)
                    num = None
                    if m and not _CJK_GARBLE.match(title):
                        try:
                            num = int(re.sub(r"\D", "", m.group("num")))
                        except ValueError:
                            num = None
                    # 원문 번호가 **다시 작아지면**(… 36) 뒤에 2)) 상위 제목을 잃은 새 묶음 → 그 번호부터 이어 센다
                    #   (표본: '2) 척도별 점수…' 가 '38)' 로 밀리던 것)
                    if num is not None and last_num is not None and num < last_num:
                        seq = num
                    else:
                        seq += 1
                    if num is not None:
                        last_num = num
                    new = _fmt_num(gstyle, seq, _strip_num(title))
                    if new != title:
                        rows[k]["title"] = new; changed += 1
                    continue
                if m and not _CJK_GARBLE.match(title):
                    try:
                        seq = int(re.sub(r"\D", "", m.group("num")))   # 있는 번호에서 이어 센다
                    except ValueError:
                        seq += 1
                    if _num_style(title) != gstyle:                     # 형식 통일('1 ' → '1.')
                        core = _strip_num(title)
                        rows[k]["title"] = _fmt_num(gstyle, seq, core); changed += 1
                    continue
                seq += 1
                rows[k]["title"] = _fmt_num(gstyle, seq, _strip_num(title))
                changed += 1
            i = j
    return changed


def group_end(rows: list[dict], start: int) -> int:
    """start 행이 속한 묶음의 끝 — 더 얕은 레벨(장 행이면 다음 장)이 나오는 행 인덱스(260904-6)."""
    if start >= len(rows):
        return len(rows)
    lv = int(rows[start].get("level", 0))
    for k in range(start + 1, len(rows)):
        l2 = int(rows[k].get("level", 0))
        if l2 < lv or (lv == 0 and l2 == 0):
            return k
    return len(rows)


def renumber_from(rows: list[dict], start: int, *, style: Optional[str] = None) -> tuple[int, int]:
    """[번호 채우기] (260904-6): 커서 행부터 그 묶음 끝까지.
      - 커서 행과 **같은 레벨**: 빠진 번호·형식만 채운다(있는 번호는 유지 — 사용자가 적은 '5.' 를 존중,
        위 형제 번호가 그대로면 뒤 '9. MMPI…' 가 '16.' 으로 밀리지 않는다).
      - 커서보다 **깊은 레벨**: 형제 순서대로 다시 매긴다(레벨을 고친 뒤 남은 '6) 7)' → '1) 2)').
      - 번호가 하나도 없는 묶음은 건너뛴다(첫 항목에 '1)' 을 적어 주면 나머지를 채운다).
    (바뀐 행 수, 범위 끝) 을 돌려준다."""
    if not rows or start >= len(rows):
        return 0, len(rows)
    start = max(0, start)
    end = group_end(rows, start)
    lv0 = int(rows[start].get("level", 0))
    n = 0
    if lv0 >= 1:
        n += renumber_rows(rows, levels=(lv0,), style=style, start=start, end=end, reseq=False, evidence_only=True)
    deeper = tuple(l for l in range(lv0 + 1, 6))
    n += renumber_rows(rows, levels=deeper, style=style, start=start, end=end, reseq=True, evidence_only=True)
    return n, end


def to_bookmarks(rows: list[dict]) -> list[tuple[str, int, int]]:
    """검토 표 → (title, page_1based, level) — 저장 경로 입력."""
    return [(r["title"], int(r["page"]), int(r.get("level", 0)))
            for r in rows if r.get("title") and r.get("page")]
