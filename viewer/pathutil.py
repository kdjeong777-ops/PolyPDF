"""260628: 공통 경로 유틸 — 경로 비교 키·중복 회피·파일명 정제의 **단일 표준**.

배경(감사 260628): 경로 정규화가 네 갈래로 갈라져 있었다.
  app._norm_path / search_panel._norm_key  = normcase(normpath(p))   (동일 코드 복붙)
  bookmark_tree                            = str(Path(p).resolve()).lower()
  indexer                                  = Python 측 normcase(normpath) ↔ SQL 측 lower(replace(...))
서로 다른 키로 비교하면 **조용히 매칭 실패**한다(검색 범위 누락·책갈피 선택 안 됨).
`resolve()` 는 파일시스템을 타서 느리고 없는 파일에서 예외가 난다.

규칙 (마스터 SOT §7.0):
  - 경로를 비교·매칭·dict 키로 쓰면 반드시 `norm_key()`.
  - 인덱스 검색 범위의 SQL 변환 `lower(replace(f.path,'/','\\'))` 은 `norm_key()` 와
    **같은 문자열**을 만들어야 한다. 한쪽을 바꾸면 반드시 함께 바꾼다.
  - `study/export_translation._safe_name`(120자·'번역' 폴백),
    `study/image_fetch._safe_name`(영숫자/한글+타임스탬프),
    `study/export_translation._unique_pair`(docx·pdf 동일 접미)는 도메인 요구가 달라
    **의도적으로 별도 유지**한다(여기로 통합하지 말 것).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = ["norm_key", "unique_path", "safe_name"]

# 파일명 금지문자(Windows) — 치환 대상
_BAD_CHARS = re.compile(r'[\\/:*?"<>|]+')
_WS = re.compile(r"\s+")


def norm_key(p) -> str:
    """경로 '비교 키' 표준 — 대소문자·구분자·`.`/`..` 정리.

    `os.path.normcase(os.path.normpath(str(p)))`. 파일시스템을 타지 않으므로
    존재하지 않는 경로에도 안전하고 빠르다. 실패 시 원본 문자열로 폴백."""
    try:
        return os.path.normcase(os.path.normpath(str(p)))
    except Exception:
        return str(p)


def unique_path(target) -> Path:
    """`target` 이 이미 있으면 'name (1).ext', 'name (2).ext' … 로 회피(Windows 방식).

    반환은 항상 `Path`. 문자열이 필요하면 호출측에서 `str()`."""
    t = Path(target)
    if not t.exists():
        return t
    parent, stem, suffix = t.parent, t.stem, t.suffix
    i = 1
    while True:
        cand = parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def safe_name(s: str, fallback: str = "", maxlen: int = 80) -> str:
    """파일명으로 안전한 문자열 — 금지문자 `_` 치환, 공백 압축, 양끝 ' .' 제거, 길이 제한.

    결과가 비면 `fallback`."""
    out = _BAD_CHARS.sub("_", (s or "").strip())
    out = _WS.sub(" ", out).strip(" .")
    return out[:maxlen] if out else fallback
