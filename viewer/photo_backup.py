# -*- coding: utf-8 -*-
"""펼친 사진으로 원본을 대체할 때 원본 백업 (사진 보기 SOT §4.43, 261106-15 사용자 지시·결정).

- 백업 자리: 기본은 **사진이 있는 폴더 안 `_원본`**(`BACKUP_DIRNAME`). 환경설정에서 한 곳의 고정 폴더로 바꾸면(`picture.warp_backup_dir`)
  그 아래에 원래 폴더 구조를 하위 폴더로 보존한다(`<고정 폴더>/<드라이브>/<경로…>/이름`) — 다른 폴더의 같은 이름이 겹치지 않게.
- 같은 이름이 이미 있으면 'name (2).jpg' …(`pathutil.unique_path(first=2)`).
- 옮기기: 같은 드라이브면 이름 바꾸기(`os.replace`), 아니면 복사 → 크기 확인 → 원본 지우기. 실패하면 원본은 그대로(예외).
- 되돌리기 `restore`: 대체가 실패하면 백업을 원래 자리로.
- 목록·색인에서 숨김: `is_backup_path` — 경로에 `_원본` 폴더가 있거나 고정 백업 폴더 안이면 True.
- 이 모듈은 배경 스레드에서 부른다(파일 작업 — 마스터 §4.7.5, 응답성 SOT §5).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

BACKUP_DIRNAME = "_원본"       # 폴더 이름은 번역하지 않는다 — 목록 거르기가 이 이름 하나로 알아본다
_CUSTOM = {"dir": ""}          # 환경설정의 고정 백업 폴더(빈 글 = 사진 폴더 안 `_원본`) — 앱이 `set_custom_dir` 로 알려 준다


def set_custom_dir(path) -> None:
    _CUSTOM["dir"] = str(path or "").strip()


def custom_dir() -> str:
    return _CUSTOM["dir"]


def backup_dir_for(src) -> Path:
    """`src` 사진의 백업 폴더(만들지는 않는다)."""
    src = Path(str(src))
    base = custom_dir()
    if not base:
        return src.parent / BACKUP_DIRNAME
    parent = Path(os.path.abspath(str(src.parent)))
    drive, rest = os.path.splitdrive(str(parent))
    drive = drive.replace(":", "").replace("\\", "_").replace("/", "_").strip("_") or "root"
    parts = [p for p in Path(rest).parts if p not in ("\\", "/")]
    return Path(base).joinpath(drive, *parts)


def is_backup_path(path) -> bool:
    """백업 자리의 파일인가 — 사진 목록·썸네일 줄·사진 정보 색인에서 뺀다."""
    p = os.path.normcase(os.path.abspath(str(path)))
    if (os.sep + os.path.normcase(BACKUP_DIRNAME) + os.sep) in p:
        return True
    base = custom_dir()
    if base:
        b = os.path.normcase(os.path.abspath(base)).rstrip("\\/") + os.sep
        return p.startswith(b)
    return False


def _same_drive(a, b) -> bool:
    return os.path.normcase(os.path.splitdrive(os.path.abspath(str(a)))[0]) == \
        os.path.normcase(os.path.splitdrive(os.path.abspath(str(b)))[0])


def _move(src: Path, dst: Path) -> None:
    if _same_drive(src, dst):
        os.replace(str(src), str(dst))
        return
    tmp = dst.with_name("~" + dst.name + ".part")
    try:
        shutil.copy2(str(src), str(tmp))
        if os.path.getsize(str(tmp)) != os.path.getsize(str(src)):
            raise OSError("copy size mismatch")
        os.replace(str(tmp), str(dst))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    os.remove(str(src))


def move_to_backup(src) -> str:
    """원본을 백업 자리로 옮긴다 — 옮긴 경로. 실패하면 예외(원본은 그대로)."""
    from viewer.pathutil import unique_path
    src = Path(str(src))
    d = backup_dir_for(src)
    d.mkdir(parents=True, exist_ok=True)
    dst = unique_path(d / src.name, first=2)
    _move(src, dst)
    return str(dst)


def restore(backup, src) -> None:
    """백업을 원래 자리로 되돌린다(대체가 실패했을 때). 원래 자리에 무엇이 있으면 지우지 않고 예외."""
    b, s = Path(str(backup)), Path(str(src))
    if s.exists():
        raise FileExistsError(str(s))
    _move(b, s)


# ── 원본으로 되돌리기(261106-18, 사용자 승인 '넣기') ─────────────────────
import re as _re
_NUM = _re.compile(r"^(.*) \((\d+)\)$")


def _base_n(stem: str):
    m = _NUM.match(stem)
    return (m.group(1), int(m.group(2))) if m else (stem, 1)


def original_name(backup) -> str:
    """백업 파일 이름 → 원래 이름('IMG (2).HEIC' → 'IMG.HEIC')."""
    b = Path(str(backup))
    return _base_n(b.stem)[0] + b.suffix


def find_backup(path) -> str | None:
    """지금 사진의 원본 백업 — 백업 자리에서 이름(확장자 빼고)이 같은 것. HEIC 가 .jpg 로 바뀐 경우도 짝을 찾는다.
    여럿('name', 'name (2)' …)이면 **가장 최근 것**(번호가 가장 큰 것 — 대체할 때마다 하나씩 늘었다). 같은 번호면 같은 확장자를 먼저."""
    p = Path(str(path))
    d = backup_dir_for(p)
    try:
        entries = [e for e in os.scandir(str(d)) if e.is_file()]
    except OSError:
        return None
    want = os.path.normcase(p.stem)
    best = None
    for e in entries:
        stem, n = _base_n(Path(e.name).stem)
        if os.path.normcase(stem) != want or e.name.startswith("~"):
            continue
        key = (n, os.path.normcase(Path(e.name).suffix) == os.path.normcase(p.suffix))
        if best is None or key > best[0]:
            best = (key, e.path)
    return best[1] if best else None


def restore_from_backup(cur, backup, trash) -> str:
    """지금 파일을 휴지통으로(`trash(경로)`), 백업을 원래 이름 자리로 — 돌려준 경로가 되돌린 원본.
    순서: 백업을 지금 폴더의 임시 이름으로 옮김 → 지금 파일을 **제 이름 그대로** 휴지통으로 → 임시를 원래 이름으로.
    휴지통이 실패하면 백업을 제자리로 되돌리고 예외(아무것도 바뀌지 않는다). 배경에서 부른다."""
    cur, backup = Path(str(cur)), Path(str(backup))
    target = cur.parent / original_name(backup)
    if os.path.normcase(str(target)) != os.path.normcase(str(cur)) and target.exists():
        raise FileExistsError(str(target))
    tmp = cur.parent / ("~" + target.name + ".polypix-restore")
    _move(backup, tmp)
    try:
        trash(str(cur))
    except Exception:
        _move(tmp, backup)                       # 휴지통 실패 — 백업을 제자리로
        raise
    try:
        os.replace(str(tmp), str(target))
    except Exception:
        _move(tmp, backup)                       # 드문 실패 — 원본은 백업 자리에 그대로 남긴다(지금 파일은 휴지통에)
        raise
    return str(target)
