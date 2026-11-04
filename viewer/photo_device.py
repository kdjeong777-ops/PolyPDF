# -*- coding: utf-8 -*-
"""아이폰 등 휴대 장치의 사진 — 둘러보기 + 복사 (사진 보기 SOT 4.33, 261104-9 사용자 결정).

- 탐색기 '내 PC › Apple iPhone' 같은 휴대 장치(MTP/WPD)는 드라이브 문자가 없어 경로로 열 수 없다.
  Windows 셸(`Shell.Application` COM, pywin32)로 장치·사진 폴더·사진 이름을 읽고, 보는 폴더의 사진만
  사용자 데이터 폴더 캐시(`photo_device_cache\\<장치>\\<폴더>\\`)로 **복사**한다. 장치에는 쓰지 않는다.
- 캐시 사진은 **읽기 전용**(`is_cached`). 캐시 상한 `CACHE_MAX_BYTES`(오래 안 쓴 폴더부터 지움 — zip 캐시와 같은 규칙).
- 장치를 읽는 함수는 모두 `BACKEND` 를 거친다 — 검사는 가짜 장치를 끼운다. 셸 함수는 **배경 스레드**에서만 부른다
  (그 스레드에서 COM 초기화·해제 — `com_thread`).
"""
from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

CACHE_DIRNAME = "photo_device_cache"
CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024    # 2 GB — 휴대폰 사진(장당 2~5 MB) 몇 달 치. 넘으면 오래 안 쓴 폴더부터 지운다
COPY_TIMEOUT_S = 120                        # 사진 한 장 복사를 기다리는 상한(연결이 끊기면 여기서 멈춘다)
COPY_STABLE_S = 0.3                         # 크기가 이만큼 그대로면 복사가 끝난 것으로(장치가 크기를 0 으로 알려 미리 알 수 없다)
_COPY_FLAGS = 4 | 16 | 512 | 1024           # 진행 창 없음·모두 예·폴더 만들기 묻지 않음·오류 창 없음
_PC_NAMESPACE = 17                          # 셸 이름 공간 '내 PC'


class DeviceError(Exception):
    """장치를 읽지 못함 — kind: 'locked'(잠김·신뢰 안 함 — 저장소가 비었다) · 'gone'(뽑힘·찾지 못함) · 'timeout'."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail or kind)
        self.kind = kind


def _photo_exts():
    from viewer.image_page import PHOTO_EXTS
    return PHOTO_EXTS


def _is_photo(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in _photo_exts()


# ── 셸(COM) 백엔드 ─────────────────────────────────────
@contextmanager
def com_thread():
    """이 스레드에서 COM 을 쓴다 — 들어갈 때 초기화, 나올 때 해제(응답성 SOT 감사표 — 배경 스레드 전용)."""
    try:
        import pythoncom
    except ImportError:
        yield
        return
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


class ShellBackend:
    """Windows 셸 이름 공간으로 휴대 장치를 읽는다. 모든 함수는 `com_thread()` 안의 배경 스레드에서."""

    def _shell(self):
        import win32com.client
        return win32com.client.Dispatch("Shell.Application")

    def _device_items(self):
        pc = self._shell().NameSpace(_PC_NAMESPACE)
        out = []
        for it in pc.Items():
            try:
                if not it.IsFileSystem and it.IsFolder and "\\\\?\\" in str(it.Path):
                    out.append(it)
            except Exception:
                continue
        return out

    def devices(self) -> list:
        """연결된 휴대 장치 이름(탐색기 '내 PC' 에 보이는 이름)."""
        return [str(it.Name) for it in self._device_items()]

    def _device(self, dev: str):
        for it in self._device_items():
            if str(it.Name) == dev:
                return it.GetFolder
        raise DeviceError("gone", dev)

    def folders(self, dev: str) -> list:
        """사진 폴더(장치 안 상대 경로 'Internal Storage/202611_a' 꼴) — 새것부터. 저장소가 없으면 잠김."""
        root = self._device(dev)
        stores = [s for s in root.Items() if s.IsFolder]
        if not stores:
            raise DeviceError("locked", dev)
        out = []
        for s in stores:
            subs = [x for x in s.GetFolder.Items() if x.IsFolder]
            dcim = next((x for x in subs if str(x.Name).upper() == "DCIM"), None)
            if dcim is not None:
                base, subs = "%s/%s" % (s.Name, dcim.Name), [x for x in dcim.GetFolder.Items() if x.IsFolder]
            else:
                base = str(s.Name)
            out.extend("%s/%s" % (base, x.Name) for x in subs)
        return sorted(out, key=lambda k: k.rsplit("/", 1)[-1].lower(), reverse=True)

    def open_folder(self, dev: str, folder: str):
        cur = self._device(dev)
        for part in folder.split("/"):
            nxt = None
            for x in cur.Items():
                if str(x.Name) == part and x.IsFolder:
                    nxt = x.GetFolder
                    break
            if nxt is None:
                raise DeviceError("gone", folder)
            cur = nxt
        return cur

    def photos(self, handle) -> list:
        """폴더 안 사진 이름 — 이름 차례."""
        return sorted((str(x.Name) for x in handle.Items() if not x.IsFolder and _is_photo(str(x.Name))), key=str.lower)

    def copy(self, handle, name: str, dest_dir: Path) -> Path:
        """사진 한 장을 dest_dir 로(임시 폴더에 받아 끝나면 옮긴다) — 막힘. 끝난 경로."""
        item = handle.ParseName(name)
        if item is None:
            raise DeviceError("gone", name)
        part = dest_dir / ".part"
        part.mkdir(parents=True, exist_ok=True)
        got = part / name
        try:
            got.unlink()
        except OSError:
            pass
        self._shell().NameSpace(str(part)).CopyHere(item, _COPY_FLAGS)
        t0, last, since = time.monotonic(), -1, None
        while True:
            try:
                sz = got.stat().st_size
            except OSError:
                sz = -1
            now = time.monotonic()
            if sz > 0 and sz == last:
                if since is not None and now - since >= COPY_STABLE_S:
                    break
            else:
                since = now
            last = sz
            if now - t0 > COPY_TIMEOUT_S:
                raise DeviceError("timeout", name)
            time.sleep(0.05)
        final = dest_dir / name
        for _ in range(20):                       # 복사 엔진이 손을 놓을 때까지 잠깐(바꿔 이름이 막히면)
            try:
                os.replace(got, final)
                return final
            except PermissionError:
                time.sleep(0.1)
        os.replace(got, final)
        return final


BACKEND = ShellBackend()


# ── 캐시 ──────────────────────────────────────────────
def cache_root() -> Path:
    from viewer.settings_store import settings_dir
    return Path(settings_dir()) / CACHE_DIRNAME


def _safe(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(s)).strip(" .")
    return s or "_"


def cache_dir_for(dev: str, folder: str) -> Path:
    return cache_root() / _safe(dev) / _safe(folder.replace("/", " - "))


def is_cached(path) -> bool:
    """장치에서 복사한 사진인가(읽기 전용으로 다룬다)."""
    try:
        root = os.path.normcase(str(cache_root()))
        return os.path.normcase(os.path.abspath(str(path))).startswith(root + os.sep)
    except Exception:
        return False


def copy_folder(dev: str, folder: str, should_cancel=None, on_list=None, on_file=None) -> list:
    """사진 폴더 하나를 캐시로 — 이미 있는 것은 그대로 두고 없는 것만 장치에서 복사한다. 복사(또는 이미 있던) 경로 목록.
    on_list(이름 목록) · on_file(경로) 로 차례로 알린다. 배경 스레드에서 `com_thread()` 안에서 부른다."""
    d = cache_dir_for(dev, folder)
    d.mkdir(parents=True, exist_ok=True)
    os.utime(d, None)                            # 오래 안 쓴 것부터 지울 때의 기준
    h = BACKEND.open_folder(dev, folder)
    names = BACKEND.photos(h)
    if on_list is not None:
        on_list(names)
    out = []
    for n in names:
        if should_cancel is not None and should_cancel():
            break
        dst = d / n
        if not dst.exists():
            dst = BACKEND.copy(h, n, d)
        out.append(str(dst))
        if on_file is not None:
            on_file(str(dst))
    return out


def prune_cache(max_bytes: int = CACHE_MAX_BYTES, keep=None) -> int:
    """캐시가 상한을 넘으면 오래 안 쓴 폴더(장치\\폴더)부터 지운다 — keep(지금 보는 폴더)은 남긴다. 지운 폴더 수."""
    import shutil
    root = cache_root()
    dirs = []
    try:
        for e in os.scandir(root):
            if e.is_dir():
                dirs.extend(Path(x.path) for x in os.scandir(e.path) if x.is_dir())
    except OSError:
        return 0

    def size(p):
        n = 0
        for dirpath, _d, files in os.walk(p):
            for f in files:
                try:
                    n += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        return n
    sized = sorted((p.stat().st_mtime, size(p), p) for p in dirs)
    total = sum(s for _m, s, _p in sized)
    n = 0
    kk = os.path.normcase(str(keep)) if keep else None
    for _m, s, p in sized:
        if total <= max_bytes:
            break
        if kk and os.path.normcase(str(p)) == kk:
            continue
        shutil.rmtree(p, ignore_errors=True)
        total -= s
        n += 1
    return n


def copy_out(paths, dest_dir, should_cancel=None, progress=None) -> list:
    """캐시 사진을 사용자가 고른 폴더로('PC 로 복사') — 같은 이름이 있으면 '이름 (2).jpg'. 만든 경로 목록."""
    import shutil
    dest = Path(dest_dir)
    out = []
    for i, p in enumerate(paths):
        if should_cancel is not None and should_cancel():
            break
        src = Path(p)
        t = dest / src.name
        k = 2
        while t.exists():
            t = dest / ("%s (%d)%s" % (src.stem, k, src.suffix))
            k += 1
        shutil.copy2(src, t)
        out.append(str(t))
        if progress is not None:
            progress(i + 1, len(paths))
    return out
