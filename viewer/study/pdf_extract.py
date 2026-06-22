"""PDF 본문 추출·정제 (번역 전처리, P1) — 머리말/꼬리말 제거 + 본문 연결.

SOT: `PDF 번역·요약 작업 계획서.md` §5.
- 추출: PyMuPDF 블록(bbox 포함).
- 머리말/꼬리말 제거: 상/하단 밴드에서 **여러 페이지에 반복**되는 텍스트(숫자 제거 정규화)
  + 단독 페이지번호 블록 제외(밴드+반복+짧은길이 동시조건으로 본문 오삭제 방지).
- 본문 연결: 줄끝 하이픈 복원, 블록 내 줄→공백(=문단), 블록 간 빈 줄(문단 경계),
  2단(컬럼) 페이지는 좌측 컬럼 먼저 읽기.
표준 라이브러리 + PyMuPDF(fitz)만 사용.
"""
from __future__ import annotations

import re


def _norm(s: str) -> str:
    """반복 판정용 정규화 — 숫자(페이지·연도) 제거, 공백 정리, 소문자."""
    s = re.sub(r"\d+", "", s or "")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


_PAGENUM_RE = re.compile(r"^[\s\-–—]*(?:p\.?\s*)?\d{1,4}[\s\-–—]*$", re.I)


def _is_pagenum(s: str) -> bool:
    return bool(_PAGENUM_RE.match((s or "").strip()))


def _blocks(page):
    """텍스트 블록 [(x0,y0,x1,y1,text)] — 빈 블록 제외."""
    out = []
    for b in page.get_text("blocks"):
        if len(b) < 5:
            continue
        x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
        if isinstance(txt, str) and txt.strip():
            out.append((x0, y0, x1, y1, txt))
    return out


def _order_reading(blocks, rect):
    """읽기 순서 정렬 — 2단(컬럼) 페이지는 좌측 먼저, 아니면 위→아래."""
    if not blocks:
        return []
    w = rect.width or 1.0
    midx = (rect.x0 + rect.x1) / 2.0

    def col_of(b):
        x0, _, x1, _, _ = b
        if (x1 - x0) > 0.55 * w:      # 전폭(제목/초록 등) → 좌측 그룹(위에서 읽힘)
            return 0
        return 0 if ((x0 + x1) / 2.0) < midx else 1

    left = [b for b in blocks if col_of(b) == 0]
    right = [b for b in blocks if col_of(b) == 1]
    if right and len(right) >= 2 and left:    # 2단으로 판단
        return sorted(left, key=lambda b: b[1]) + sorted(right, key=lambda b: b[1])
    return sorted(blocks, key=lambda b: (b[1], b[0]))


def _block_paragraph(txt: str) -> str:
    """블록 텍스트 → 한 문단(줄끝 하이픈 복원, 줄바꿈→공백)."""
    s = txt or ""
    s = re.sub(r"(\w)[\-­]\s*\n\s*([a-z])", r"\1\2", s)   # 하이픈 분철 복원
    s = re.sub(r"\s*\n\s*", " ", s)                            # 줄바꿈 → 공백
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s


def extract_clean_debug(path, max_chars: int = 0):
    """(정제 본문, info). info={pages, removed_headers:[..], n_paras}."""
    info = {"pages": 0, "removed_headers": [], "n_paras": 0}
    try:
        import fitz
        doc = fitz.open(str(path))
    except Exception as e:
        return "", {"error": f"{type(e).__name__}: {e}", **info}
    n = doc.page_count
    info["pages"] = n

    # --- 1차: 페이지별 블록 + 상/하단 밴드 반복 텍스트 집계 ---
    pages_blocks = []
    band_count: dict = {}
    for i in range(n):
        pg = doc[i]
        rect = pg.rect
        h = rect.height or 1.0
        top_lim = rect.y0 + h * 0.12
        bot_lim = rect.y0 + h * 0.88
        bl = _blocks(pg)
        pages_blocks.append((rect, bl))
        seen_norm = set()
        for (x0, y0, x1, y1, txt) in bl:
            in_band = (y1 <= top_lim) or (y0 >= bot_lim)
            if not in_band:
                continue
            nm = _norm(txt)
            if not nm or len(nm) > 90:
                continue
            if nm in seen_norm:
                continue
            seen_norm.add(nm)
            band_count[nm] = band_count.get(nm, 0) + 1

    # 반복 머리말/꼬리말 = 밴드에서 페이지의 30%↑(최소 2회) 등장한 정규화 텍스트
    thr = max(2, int(round(n * 0.3)))
    headers = {nm for nm, c in band_count.items() if c >= thr}
    info["removed_headers"] = sorted(headers)

    # --- 2차: 머리말/꼬리말·페이지번호 제외 후 읽기순서로 본문 구성 ---
    paras = []
    for (rect, bl) in pages_blocks:
        h = rect.height or 1.0
        top_lim = rect.y0 + h * 0.12
        bot_lim = rect.y0 + h * 0.88
        kept = []
        for b in bl:
            x0, y0, x1, y1, txt = b
            in_band = (y1 <= top_lim) or (y0 >= bot_lim)
            if in_band:
                nm = _norm(txt)
                if nm in headers or _is_pagenum(txt):
                    continue                      # 반복 헤더/푸터·페이지번호 제거
            kept.append(b)
        for b in _order_reading(kept, rect):
            para = _block_paragraph(b[4])
            if para:
                paras.append(para)
    doc.close()

    text = "\n\n".join(paras)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    info["n_paras"] = len(paras)
    if max_chars and max_chars > 0:
        text = text[:max_chars]
    return text, info


def extract_clean_text(path, max_chars: int = 0) -> str:
    txt, _ = extract_clean_debug(path, max_chars=max_chars)
    return txt
