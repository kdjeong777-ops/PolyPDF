"""다단어 전문용어 인식(term spotting) — 계획서 §4.4 (P4).

페이지의 단어 표면형 열(읽기순)에서 사전의 다단어 표제어를 찾는다.
- 각 단어를 normalize_key 로 정규화해 이어붙인 문자열에서 표제어(정규화)를 부분일치 검색.
- 매칭은 **단어 경계에서 시작**해야 인정(조사 등으로 끝이 단어 중간이어도 허용) → 한글
  '가열 아스팔트 혼합물' 이 OCR ['가열','아스팔트','혼합물을'] 처럼 조사가 붙어도 인식.
순수 함수(좌표 비의존) — 좌표 합성/회전 보정은 호출자(app)가 처리.
"""
from __future__ import annotations

from viewer.study.dict_store import normalize_key


def _concat(norms: list[str]):
    starts: set[int] = set()
    wordpos: list[int] = []
    pos = 0
    for i, w in enumerate(norms):
        starts.add(pos)
        wordpos.extend([i] * len(w))
        pos += len(w)
    return "".join(norms), starts, wordpos


def spot(word_surfaces, terms, *, min_len: int = 4):
    """word_surfaces: 페이지 단어 표면형(읽기순).
    terms: [(norm, payload)] — 다단어 표제어 정규화 + 임의 payload.
    반환: [(payload, w0, w1)] — 경계정렬 매칭의 시작/끝 단어 인덱스(등장순)."""
    norms = [normalize_key(s) for s in word_surfaces]
    concat, start_set, wordpos = _concat(norms)
    if not concat:
        return []
    out = []
    for norm, payload in terms:
        if not norm or len(norm) < min_len:
            continue
        i = concat.find(norm)
        while i != -1:
            if i in start_set:
                out.append((payload, wordpos[i], wordpos[i + len(norm) - 1]))
            i = concat.find(norm, i + 1)
    # 등장 순서(시작 단어 인덱스)
    out.sort(key=lambda m: m[1])
    return out
