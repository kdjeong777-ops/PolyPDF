# -*- coding: utf-8 -*-
"""사진이 든 zip (사진 보기 SOT 4.24, 결정 D19, 261104-4 조각 ③·④).

- 사진 모드 목록에는 **사진이 하나라도 든 zip** 만 한 줄로 보인다(`has_photos`).
- 누르면 안의 사진을 사용자 데이터 폴더 캐시(`photo_zip_cache\\<zip 지문>\\`)로 **배경에서** 꺼내(`extract`)
  썸네일 줄에 보이고 첫 장을 연다. 꺼낸 사진은 **읽기 전용**으로 다룬다(`is_cached`) — 원본 zip 은 고치지 않는다.
- 지문 = zip 경로·크기·수정 시각 — zip 이 바뀌면 새로 꺼낸다. 캐시 크기 상한 `CACHE_MAX_BYTES`(오래 안 쓴 것부터 지움).
"""
from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path

CACHE_DIRNAME = "photo_zip_cache"
CACHE_MAX_BYTES = 1024 * 1024 * 1024       # 1 GB — 넘으면 오래 안 쓴 zip 꺼냄부터 지운다
_SKIP_PREFIX = ("__MACOSX/",)


def _photo_exts():
    from viewer.image_page import PHOTO_EXTS
    return PHOTO_EXTS


def photo_members(zip_path) -> list:
    """zip 안 사진 이름(안 경로) — 이름 차례. 못 읽으면 빈 목록."""
    exts = _photo_exts()
    try:
        with zipfile.ZipFile(str(zip_path)) as z:
            names = [i.filename for i in z.infolist()
                     if not i.is_dir() and not i.filename.startswith(_SKIP_PREFIX)
                     and os.path.splitext(i.filename)[1].lower() in exts
                     and not os.path.basename(i.filename).startswith(".")]
    except (OSError, zipfile.BadZipFile, ValueError):
        return []
    return sorted(names, key=lambda n: n.lower())


def has_photos(zip_path) -> bool:
    return bool(photo_members(zip_path))


def cache_root() -> Path:
    from viewer.settings_store import settings_dir
    return Path(settings_dir()) / CACHE_DIRNAME


def cache_dir_for(zip_path) -> Path:
    st = os.stat(str(zip_path))
    raw = "%s|%d|%d" % (os.path.normcase(os.path.abspath(str(zip_path))), st.st_size, st.st_mtime_ns)
    return cache_root() / hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def is_cached(path) -> bool:
    """zip 에서 꺼낸 사진인가(읽기 전용으로 다룬다)."""
    try:
        root = os.path.normcase(str(cache_root()))
        return os.path.normcase(os.path.abspath(str(path))).startswith(root + os.sep)
    except Exception:
        return False


def _safe_rel(name: str) -> str:
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return os.path.join(*parts) if parts else "photo"


def extract(zip_path, should_cancel=None) -> list:
    """zip 안 사진을 캐시로 꺼낸다(이미 있으면 그대로) — 꺼낸 경로 목록(이름 차례). 배경에서 부른다."""
    out = []
    d = cache_dir_for(zip_path)
    d.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(zip_path)) as z:
        for name in photo_members(zip_path):
            if should_cancel is not None and should_cancel():
                break
            dst = d / _safe_rel(name)
            info = z.getinfo(name)
            if not (dst.exists() and dst.stat().st_size == info.file_size):
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.name + ".part")
                with z.open(name) as src, open(tmp, "wb") as fh:
                    while True:
                        buf = src.read(1 << 20)
                        if not buf:
                            break
                        fh.write(buf)
                os.replace(str(tmp), str(dst))
            out.append(str(dst))
    try:
        os.utime(d)                                  # 쓴 때 — 상한을 넘으면 오래 안 쓴 것부터
    except OSError:
        pass
    return out


def member_bytes(zip_path, name: str) -> bytes:
    with zipfile.ZipFile(str(zip_path)) as z:
        return z.read(name)


def prune_cache(max_bytes: int = CACHE_MAX_BYTES) -> int:
    """캐시가 상한을 넘으면 오래 안 쓴 zip 꺼냄 폴더부터 지운다. 지운 폴더 수. 배경에서 부른다."""
    import shutil
    root = cache_root()
    try:
        dirs = [Path(e.path) for e in os.scandir(root) if e.is_dir()]
    except OSError:
        return 0

    def size(p):
        n = 0
        for dirpath, _dirs, files in os.walk(p):
            for f in files:
                try:
                    n += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        return n
    sized = sorted(((p.stat().st_mtime, size(p), p) for p in dirs))
    total = sum(s for _m, s, _p in sized)
    n = 0
    for _m, s, p in sized:
        if total <= max_bytes:
            break
        shutil.rmtree(p, ignore_errors=True)
        total -= s
        n += 1
    return n
