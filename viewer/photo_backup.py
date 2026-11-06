# -*- coding: utf-8 -*-
"""펼친 사진으로 원본을 대체할 때 원본 백업 (사진 보기 SOT §4.43, 261106-15 사용자 지시·결정).

- 백업 자리: 기본은 **사진이 있는 폴더 안 `_원본`**(`BACKUP_DIRNAME`). 환경설정에서 한 곳의 고정 폴더로 바꾸면(`picture.warp_backup_dir`)
  그 아래에 원래 폴더 구조를 하위 폴더로 보존한다(`<고정 폴더>/<드라이브>/<경로…>/이름`) — 다른 폴더의 같은 이름이 겹치지 않게.
- 같은 이름이 이미 있으면 'name (2).jpg' …(`pathutil.unique_path(first=2)`).
- 옮기기: 같은 드라이브면 이름 바꾸기(`os.replace`), 아니면 복사 → 크기 확인 → 원본 지우기. 실패하면 원본은 그대로(예외).
- 되돌리기 `restore`: 대체가 실패하면 백업을 원래 자리로.
- 짝 기록 `INDEX_NAME`(261106-20): 백업마다 원래 이름·대체한 파일 이름을 백업 폴더에 적고, '원본으로 되돌리기' 는 그 기록으로만 짝을 찾는다.
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


def move_to_backup(src, cur_name=None) -> str:
    """원본을 백업 자리로 옮기고 짝을 적는다(`record` — `cur_name` = 그 자리를 대신할 파일 이름, 없으면 원본 이름) — 옮긴 경로.
    실패하면 예외(원본은 그대로 — 짝을 못 적어도 원본을 제자리로 되돌린다)."""
    from viewer.pathutil import unique_path
    src = Path(str(src))
    d = backup_dir_for(src)
    d.mkdir(parents=True, exist_ok=True)
    dst = unique_path(d / src.name, first=2)
    _move(src, dst)
    try:
        record(dst, src.name, cur_name or src.name)
    except Exception:
        _move(dst, src)
        raise
    return str(dst)


def restore(backup, src) -> None:
    """백업을 원래 자리로 되돌린다(대체가 실패했을 때) — 짝 기록도 지운다. 원래 자리에 무엇이 있으면 지우지 않고 예외."""
    b, s = Path(str(backup)), Path(str(src))
    if s.exists():
        raise FileExistsError(str(s))
    _move(b, s)
    forget(b)


# ── 원본으로 되돌리기(261106-18, 사용자 승인 '넣기') · 짝 기록(261106-20) ─────────
# 백업할 때 '백업 파일 ↔ 원래 이름 ↔ 대체한 파일 이름' 짝을 백업 폴더의 작은 기록(`INDEX_NAME`)에 남기고,
# 되돌리기는 **그 기록으로만** 짝을 찾는다 — 'IMG (2).jpg' 처럼 원래 이름에 번호가 있는 사진이 'IMG.jpg' 의 두 번째 백업과
# 엉키지 않게(261106-20, 지휘 점검). 기록이 없는 옛 백업(261106-15~-19 사이에 만든 것)은 **정확히 같은 이름**(확장자 빼고)만 짝으로 본다.
import json as _json

INDEX_NAME = ".polypix-backup.json"    # 백업 폴더 안 짝 기록 — {백업 파일 이름: {"orig": 원래 이름, "cur": 대체한 파일 이름, "seq": 차례}}


def _read_index(d) -> dict:
    try:
        with open(os.path.join(str(d), INDEX_NAME), encoding="utf-8") as f:
            data = _json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_index(d, data: dict) -> None:
    """기록을 통째로 — 임시 파일에 쓰고 바꿔 넣는다(반쯤 쓴 기록이 남지 않게). 실패하면 예외."""
    p = os.path.join(str(d), INDEX_NAME)
    if not data:
        if os.path.exists(p):
            os.remove(p)
        return
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=0)
    os.replace(tmp, p)


def record(backup, orig_name: str, cur_name: str) -> None:
    """백업 짝을 적는다(배경). `orig_name` = 백업하기 전 이름, `cur_name` = 그 자리를 대신한 파일 이름(HEIC → .jpg 면 다르다)."""
    b = Path(str(backup))
    data = _read_index(b.parent)
    seq = max([int(v.get("seq") or 0) for v in data.values() if isinstance(v, dict)] + [0]) + 1
    data[b.name] = {"orig": str(orig_name), "cur": str(cur_name), "seq": seq}
    _write_index(b.parent, data)


def forget(backup) -> None:
    """되돌린 백업(또는 대체를 되돌린 백업)의 짝 기록을 지운다 — 실패해도 조용히(기록에 없는 파일은 짝으로 쓰지 않는다)."""
    b = Path(str(backup))
    try:
        data = _read_index(b.parent)
        if data.pop(b.name, None) is not None:
            _write_index(b.parent, data)
    except OSError:
        pass


def original_name(backup) -> str:
    """백업 파일 → 되돌릴 이름. 기록이 있으면 기록의 원래 이름, 없으면(옛 백업) 백업 파일 이름 그대로."""
    b = Path(str(backup))
    rec = _read_index(b.parent).get(b.name)
    if isinstance(rec, dict) and rec.get("orig"):
        return str(rec["orig"])
    return b.name


def scan(paths) -> dict:
    """사진들 → {사진 경로: 그 사진의 원본 백업 경로} (백업이 있는 것만). 백업 폴더마다 **한 번만** 읽는다
    (폴더 목록 한 번 + 기록 한 번 — 메뉴를 만들 때 사진마다 폴더를 읽지 않게, 261106-21·응답성 SOT §6).
    기록이 있으면 '대체한 파일 이름 = 지금 사진 이름' 인 것 중 가장 최근(seq 큰 것). 기록에 없는 옛 백업은 확장자를 뺀 이름이 정확히 같은 것
    (같은 확장자 먼저 — HEIC 를 .jpg 로 바꾼 사진도 짝)."""
    groups = {}
    for p in paths or []:
        p = Path(str(p))
        groups.setdefault(str(backup_dir_for(p)), []).append(p)
    out = {}
    for d, items in groups.items():
        try:
            names = {e.name for e in os.scandir(d) if e.is_file() and not e.name.startswith(("~", "."))}
        except OSError:
            continue
        if not names:
            continue
        idx = _read_index(d)
        recorded = {k for k in idx if k in names}
        for p in items:
            best = None
            for k in recorded:
                v = idx[k]
                if isinstance(v, dict) and os.path.normcase(str(v.get("cur") or "")) == os.path.normcase(p.name):
                    s = int(v.get("seq") or 0)
                    if best is None or s > best[0]:
                        best = (s, k)
            if best is None:                              # 기록 없는 옛 백업 — 정확히 같은 이름만
                want = os.path.normcase(p.stem)
                for k in sorted(names - set(idx)):
                    if os.path.normcase(Path(k).stem) != want:
                        continue
                    key = (1 if os.path.normcase(Path(k).suffix) == os.path.normcase(p.suffix) else 0, k)
                    if best is None or key > best:
                        best = key
            if best is not None:
                out[str(p)] = os.path.join(d, best[1])
    return out


def find_backup(path) -> str | None:
    """지금 사진 한 장의 원본 백업(`scan` 한 장짜리)."""
    return scan([path]).get(str(Path(str(path))))


def restore_from_backup(cur, backup, trash) -> str:
    """지금 파일을 휴지통으로(`trash(경로)`), 백업을 원래 이름 자리로 — 돌려준 경로가 되돌린 원본. 배경에서 부른다.
    **휴지통은 마지막** — 그 전 어느 단계에서 실패해도 모두 되돌려 아무것도 바뀌지 않는다(마스터 §4.7.5 '실패 되돌림', 261106-20):
    ① 백업을 지금 폴더의 임시 이름으로 ② 되돌릴 이름이 지금 파일과 같으면 지금 파일을 곁 폴더(`~polypix-restore`)로 비켜 둔다(이름 그대로)
    ③ 임시를 원래 이름으로 ④ 지금 파일(비켜 둔 것)을 휴지통으로 — 실패하면 ③·②·① 을 거꾸로."""
    cur, backup = Path(str(cur)), Path(str(backup))
    target = cur.parent / original_name(backup)
    same = os.path.normcase(str(target)) == os.path.normcase(str(cur))
    if not same and target.exists():
        raise FileExistsError(str(target))
    tmp = cur.parent / ("~" + target.name + ".polypix-restore")
    _move(backup, tmp)                                    # ①
    aside_dir = cur.parent / "~polypix-restore"
    aside = aside_dir / cur.name
    moved_aside = False
    placed = False
    try:
        if same:                                          # ②
            aside_dir.mkdir(exist_ok=True)
            os.replace(str(cur), str(aside))
            moved_aside = True
        os.replace(str(tmp), str(target))                 # ③
        placed = True
        trash(str(aside if moved_aside else cur))         # ④
    except Exception:
        if placed:
            os.replace(str(target), str(tmp))
        if moved_aside:
            os.replace(str(aside), str(cur))
        _move(tmp, backup)
        raise
    finally:
        if aside_dir.exists():
            try:
                aside_dir.rmdir()
            except OSError:
                pass
    forget(backup)
    return str(target)
