"""번역 용어집 생성 (P2) — 전문 용어사전(dict.db) 1순위.

SOT: `PDF 번역·요약 작업 계획서.md` §6.
- 본문에 등장하는 dict.db 의 영문 표제어(term_en)를 찾아, 그 한국어 대역(term_ko)을
  용어집으로 수집 → 번역 시스템 프롬프트에 주입(프롬프트 캐시)하여 일관 번역.
- 우선순위는 DictStore 정렬(User ▶ Base ▶ Auto)을 그대로 따른다(중복은 1위만).
- 미등록 용어의 LLM 제안(Auto)·온라인 사전 보조는 후속(§6.2).
"""
from __future__ import annotations

import re


def _word_surfaces(text: str):
    """영문 단어 토큰(읽기순) — term_spotter 가 정규화·다단어 경계 매칭."""
    return re.findall(r"[A-Za-z]+", text or "")


def build_glossary(text: str, store, max_terms: int = 200) -> list:
    """(list[{en, ko, note, source}]). 본문에 등장하는 사전 용어만 수집."""
    if not text or store is None:
        return []
    try:
        rows = store.all_terms()
    except Exception:
        return []
    if not rows:
        return []
    try:
        from viewer.study.term_spotter import spot
    except Exception:
        return []
    terms = []
    for r in rows:
        ne = (r.get("norm_en") or "").strip()
        tk = (r.get("term_ko") or "").strip()
        if ne and tk:
            terms.append((ne, r))
    if not terms:
        return []
    words = _word_surfaces(text)
    if not words:
        return []
    seen = set()
    out = []
    for (r, _w0, _w1) in spot(words, terms, min_len=3):
        en = (r.get("term_en") or "").strip()
        ko = (r.get("term_ko") or "").strip()
        key = en.lower()
        if not en or not ko or key in seen:
            continue
        seen.add(key)
        out.append({"en": en, "ko": ko, "note": "",
                    "source": (r.get("src_kind") or "")})
        if len(out) >= max_terms:
            break
    # 다단어(긴) 용어 우선 — 프롬프트에서 먼저 적용되도록
    out.sort(key=lambda g: -len(g["en"]))
    return out


def build_glossary_for_pdf(path, store, max_terms: int = 200) -> list:
    """PDF 정제 본문 기준 용어집(배치 워커용 — 자체 추출)."""
    try:
        from viewer.study import pdf_extract
        text = pdf_extract.extract_clean_text(path, max_chars=200000)
    except Exception:
        text = ""
    if not text:
        try:
            from viewer.study import translate_api
            text = translate_api.extract_pdf_text(path, max_chars=200000)
        except Exception:
            text = ""
    return build_glossary(text, store, max_terms=max_terms)
