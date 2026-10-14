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

__all__ = ["norm_key", "unique_path", "safe_name", "iter_pdfs"]

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


def iter_pdfs(folder, should_cancel=None, stats=None):
    """260906-1: `folder` 하위의 PDF 를 하나씩 내놓는 제너레이터 (`rglob("*.pdf")` 대체).

    `Path.rglob` 은 **끝까지 돌아야** 첫 결과를 쓸 수 있고 중간에 멈출 수도 없어,
    파일이 수만 개인 트리(외장 드라이브 루트 등)를 열면 호출한 스레드가 통째로 멈춘다.
    이 함수는 `os.scandir` 재귀라 항목마다 양보·취소가 가능하다(응답성 SOT §4).

    - `should_cancel()` 이 True 를 내면 즉시 중단한다(폴더당 한 번 이상 확인).
    - 권한이 없는 하위 폴더는 **건너뛴다**(전체 스캔은 계속).
    - 심볼릭 링크·정션 폴더로는 **내려가지 않는다** — `rglob` 과 같은 규칙이고
      순환 링크에서 무한 루프에 빠지지 않는다.
    - 확장자 판정은 대소문자를 무시한다(`.PDF` 포함) — `rglob` 과 동일.
    - `stats` 에 dict 를 주면 `{경로문자열: (크기, 수정시각)}` 를 함께 채운다. Windows 의
      `os.scandir` 는 이 값을 디렉터리 열거에서 **이미 받아 오므로 추가 비용이 없다** —
      나중에 정렬하려고 `Path.stat()` 을 다시 부르면 파일 수만큼 디스크를 또 때린다
      (실측: 외장 SSD 의 PDF 28,954개를 수정일로 정렬하는 데 **12.5초**, 그동안 창이 멈춘다).
    """
    stack = [str(folder)]
    while stack:
        if should_cancel is not None and should_cancel():
            return
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.name.lower().endswith(".pdf"):
                            if stats is not None:
                                try:
                                    st = entry.stat(follow_symlinks=False)
                                    stats[entry.path] = (st.st_size, st.st_mtime)
                                except OSError:
                                    pass
                            yield Path(entry.path)
                    except OSError:
                        continue          # 개별 항목 접근 실패는 건너뛴다
        except (PermissionError, OSError):
            continue                      # 못 여는 폴더는 건너뛰고 나머지를 계속


RENAME_WAIT_S = 4.0     # 이만큼은 '잠깐 잡힌 것' 으로 보고 다시 시도한다 — 색인이 한 파일을 읽는 시간보다 넉넉히
RENAME_STEP_S = 0.15


def _is_sharing_violation(e: OSError) -> bool:
    """Windows 공유 위반(32 = 다른 프로세스가 사용 중, 5 = 접근 거부 — 백신·색인이 막 연 때 함께 나온다)."""
    return getattr(e, "winerror", None) in (32, 5)


def rename_when_free(src, dst, move: bool = False, wait_s: float = RENAME_WAIT_S) -> None:
    """261014-4(마스터 §4.7.14): 파일·폴더 이름 바꾸기/옮기기 — 잠깐 잡혀 있으면 **기다렸다가 다시** 한다.

    Windows 는 누가 파일을 열고 있으면(같은 프로세스의 MuPDF 도) 이름을 못 바꾼다(`WinError 32`). 폴더를 열면 배경 색인
    (자식 프로세스)이 파일을 하나씩 짧게 열기 때문에, 그 순간 이름 바꾸기가 실패했다 — 부하가 클수록 자주. 공유 위반만
    `wait_s` 동안 다시 시도하고, 그 밖의 오류와 끝내 안 풀린 경우는 그대로 올린다. **메인 스레드에서 부르지 않는다**(기다린다).

    `move` 면 다른 드라이브로의 이동만 `shutil.move`(복사 후 지우기)로 — 같은 드라이브는 늘 이름 바꾸기다. `shutil.move` 를
    먼저 부르면 원본이 잠겨 있을 때 **복사는 되고 지우기는 실패해 두 벌**이 남는다.
    """
    import shutil
    import time
    src, dst = str(src), str(dst)
    deadline = time.monotonic() + max(0.0, wait_s)
    while True:
        try:
            os.rename(src, dst)
            return
        except OSError as e:
            if move and getattr(e, "winerror", None) == 17:      # 다른 드라이브 — 복사 후 지우기
                shutil.move(src, dst)
                return
            if not _is_sharing_violation(e) or time.monotonic() >= deadline:
                raise
        time.sleep(RENAME_STEP_S)
