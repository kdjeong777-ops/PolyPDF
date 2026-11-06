# -*- coding: utf-8 -*-
"""zip 압축 풀기 — 책갈피창·썸네일 줄·본문에서 (사진 보기 SOT §4.24.1, 261106-5 사용자 지시).

- **여기에 풀기**: zip 이 있는 폴더에 zip 이름 폴더(`target_dir` — 있으면 'name (2)')를 만들어 모두 푼다.
- **골라서 풀기**: 고른 항목만 사용자가 고른 폴더에(안의 폴더 구조는 그대로).
- 안전: 경로 탈출(`..`·절대 경로·드라이브·UNC)은 빼고(`photo_zip._safe_rel`·`_inside` 재사용), 목차를 속인 압축 폭탄은
  읽은 바이트로 막는다(`MEMBER_MAX_BYTES`·`MAX_RATIO`·`UNPACK_MAX_TOTAL`). 있는 파일은 **덮어쓰지 않는다** — 'name (1).ext'.
- 한글 이름: UTF-8 표시(0x800)가 없는 zip(윈도우 탐색기가 만든 것 등)은 cp437 로 읽힌 이름을 cp949 로 다시 푼다.
- 배경에서 부른다(응답성 SOT §5) — `ZipUnpackWorker`. 파일 하나가 끝날 때마다 멈출 수 있고, 일감 사이에 양보한다(`pacing`).
- 261106-23(응답성 SOT §4.1 '목록의 파일마다 열지 않는다'): zip 목차는 **배경에서 한 번** 읽어 (경로·크기·수정 시각) 키로 기억한다
  (`members`·`has_kind`). 메인(책갈피창 목록·zip 줄 펼치기)은 **기억만 본다**(`peek_kind`·`peek_members`) — 모르면 배경으로 넘긴다.
"""
from __future__ import annotations

import os
import threading
import zipfile
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from viewer.share_bundle import is_bundle    # 전달 묶음(마스터 §4.7.23) 접미사는 share_bundle.SUFFIX 한 곳 — 이 기능의 zip 이 아니다

MEMBER_MAX_BYTES = 8 * 1024 * 1024 * 1024      # 항목 하나의 풀린 크기 상한(8 GB)
UNPACK_MAX_TOTAL = 32 * 1024 * 1024 * 1024     # 한 번에 풀 크기 합 상한(32 GB)
MAX_RATIO = 500                                # 풀린 크기 ÷ 압축 크기 상한(글·표는 수십~백여 배, 폭탄은 천 배 이상)
CHUNK = 1 << 20
PACE_CHUNKS = 16                               # 큰 항목은 이만큼(16 MB) 쓸 때마다 한 번 더 양보한다
_SKIP_PREFIX = ("__MACOSX/",)
TOC_CACHE_MAX = 512                            # 기억하는 zip 수 — 넘으면 비우고 다시(목차는 작다)

# zip 목차 기억 — {(normcase 경로, 종류): (크기, 수정 시각 ns, 값)}. 종류 'all'·'.pdf' = members 목록, 'photo' = 사진 있음.
_TOC: dict = {}
_TOC_LOCK = threading.Lock()


def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _toc_get(zip_path, kind, st=None):
    """기억한 값 — `st`(os.stat 결과)를 주면 크기·시각이 같을 때만. 없으면 None."""
    with _TOC_LOCK:
        hit = _TOC.get((_norm(zip_path), kind))
    if hit is None:
        return None
    if st is not None and (hit[0], hit[1]) != (st.st_size, st.st_mtime_ns):
        return None
    return hit[2]


def _toc_put(zip_path, kind, st, value) -> None:
    with _TOC_LOCK:
        if len(_TOC) >= TOC_CACHE_MAX:
            _TOC.clear()
        _TOC[(_norm(zip_path), kind)] = (st.st_size, st.st_mtime_ns, value)


def toc_forget(zip_path=None) -> None:
    """기억을 지운다(검사·zip 을 바꾼 뒤). 경로를 주면 그 zip 만."""
    with _TOC_LOCK:
        if zip_path is None:
            _TOC.clear()
            return
        n = _norm(zip_path)
        for k in [k for k in _TOC if k[0] == n]:
            del _TOC[k]


def display_name(info: zipfile.ZipInfo) -> str:
    """zip 안 이름 — UTF-8 표시가 없으면 cp949 로 다시(한글 윈도우 zip)."""
    name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            name = name.encode("cp437").decode("cp949")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def _safe_rel(name: str) -> str:
    from viewer.photo_zip import _safe_rel as f
    return f(name)


def _inside(root: Path, target: Path) -> bool:
    from viewer.photo_zip import _inside as f
    return f(root, target)


def members(zip_path, exts=None) -> list:
    """풀 수 있는 항목 [(zip 안 이름, 보일 이름)] — 폴더·맥 부속·숨김·탈출 이름·폭탄으로 보이는 것은 뺀다. `exts` 면 그 확장자만.
    못 읽으면 빈 목록. 보일 이름 차례. 한 번 읽은 zip 은 (경로·크기·시각) 이 같으면 다시 열지 않는다(261106-23). **배경에서**."""
    kind = "all" if not exts else "|".join(sorted(exts))
    try:
        st = os.stat(str(zip_path))
    except OSError:
        return []
    got = _toc_get(zip_path, kind, st)
    if got is not None:
        return list(got)
    out = _read_members(zip_path, exts)
    _toc_put(zip_path, kind, st, tuple(out))
    return out


def peek_members(zip_path, exts=None):
    """기억한 목차만 — 열지 않는다(메인에서). 모르면 None."""
    got = _toc_get(zip_path, "all" if not exts else "|".join(sorted(exts)))
    return None if got is None else list(got)


def has_kind(zip_path, kind: str) -> bool:
    """zip 이 목록에 보일지 — 'pdf'(PDF 모드: PDF 가 든 것, 전달 묶음은 빼고) / 'photo'(사진 모드: 사진이 든 것). **배경에서**."""
    if kind == "pdf":
        return has_pdfs(zip_path)
    try:
        st = os.stat(str(zip_path))
    except OSError:
        return False
    got = _toc_get(zip_path, "photo", st)
    if got is None:
        from viewer.photo_zip import has_photos
        got = bool(has_photos(zip_path))
        _toc_put(zip_path, "photo", st, got)
    return bool(got)


def scan_keep(kind: str, pre=None):
    """배경 폴더 훑기(`FolderScanWorker`)의 걸러내기 — zip 은 `has_kind`(목차를 읽고 기억), 그 밖은 `pre` 만. **배경에서만** 부른다."""
    def keep(p):
        if pre is not None and not pre(p):
            return False
        if not str(p).lower().endswith(".zip"):
            return True
        return has_kind(p, kind)
    return keep


def peek_kind(zip_path, kind: str):
    """`has_kind` 의 기억만 — 열지도 stat 하지도 않는다(메인 목록 거르기). 모르면 None(→ 배경 훑기로 넘긴다)."""
    if kind == "pdf":
        if is_bundle(zip_path):
            return False
        got = peek_members(zip_path, (".pdf",))
        return None if got is None else bool(got)
    got = _toc_get(zip_path, "photo")
    return None if got is None else bool(got)


def _read_members(zip_path, exts=None) -> list:
    out = []
    try:
        with zipfile.ZipFile(str(zip_path)) as z:
            for i in z.infolist():
                if i.is_dir() or i.filename.startswith(_SKIP_PREFIX):
                    continue
                shown = display_name(i)
                if os.path.basename(shown).startswith(".") or not _safe_rel(shown):
                    continue
                if exts and os.path.splitext(shown)[1].lower() not in exts:
                    continue
                if i.file_size > MEMBER_MAX_BYTES or i.file_size > max(1, i.compress_size) * MAX_RATIO:
                    continue
                out.append((i.filename, shown))
    except (OSError, zipfile.BadZipFile, ValueError, RuntimeError, NotImplementedError):
        return []
    return sorted(out, key=lambda t: t[1].lower())


def has_pdfs(zip_path) -> bool:
    """PDF 가 하나라도 든 zip(전달 묶음은 빼고) — PDF 모드 목록에 보일지."""
    if is_bundle(zip_path):
        return False
    return bool(members(zip_path, (".pdf",)))


def target_dir(zip_path) -> Path:
    """'여기에 풀기' 의 새 폴더 — zip 옆 zip 이름, 있으면 'name (2)'…(파일 이름 규칙 `unique_path` 와 같은 꼴)."""
    from viewer.pathutil import unique_path
    p = Path(str(zip_path))
    stem = p.name[: -len(".zip")] if p.name.lower().endswith(".zip") else p.stem
    return unique_path(p.parent / stem, first=2)


def unpack(zip_path, dest, names=None, should_cancel=None, progress=None, strip_dirs: bool = False,
           pace=None) -> tuple:
    """`dest` 에 푼다 — `names`(zip 안 이름 목록)이 없으면 모두. 돌려줌 (쓴 파일, 건너뛴 이름, 멈췄나).
    `strip_dirs` 면 안의 폴더를 빼고 이름만(골라서 풀기에서 사진·PDF 를 한 폴더에). 있는 파일은 'name (1)' 로.
    `pace()` 를 주면 항목마다·큰 항목은 `PACE_CHUNKS` 마다 부른다 — 다른 작업·창에 양보(응답성 SOT §4 ⑦, 261106-23)."""
    from viewer.pathutil import unique_path
    dest = Path(str(dest))
    want = None if names is None else set(names)
    written, skipped = [], []
    total = 0
    stopped = False
    with zipfile.ZipFile(str(zip_path)) as z:
        items = [(raw, shown) for raw, shown in members(zip_path) if want is None or raw in want]
        if want is not None:
            got = {raw for raw, _s in items}
            skipped.extend(n for n in names if n not in got)
        for k, (raw, shown) in enumerate(items):
            if pace is not None and k:
                pace()
            if should_cancel is not None and should_cancel():
                stopped = True
                break
            rel = os.path.basename(_safe_rel(shown)) if strip_dirs else _safe_rel(shown)
            dst = dest / rel
            if not rel or not _inside(dest, dst):
                skipped.append(raw)
                continue
            info = z.getinfo(raw)
            if total + info.file_size > UNPACK_MAX_TOTAL:
                skipped.append(raw)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst = unique_path(dst)
            tmp = dst.with_name("~" + dst.name + ".part")
            got = 0
            try:
                with z.open(raw) as src, open(tmp, "wb") as fh:
                    n_chunk = 0
                    while True:
                        buf = src.read(CHUNK)
                        if not buf:
                            break
                        got += len(buf)
                        if got > min(MEMBER_MAX_BYTES, info.file_size + CHUNK):
                            raise ValueError("zip member larger than declared")    # 목차를 속인 폭탄
                        fh.write(buf)
                        n_chunk += 1
                        if pace is not None and n_chunk % PACE_CHUNKS == 0:
                            pace()
                os.replace(str(tmp), str(dst))
                try:                                  # zip 안의 날짜를 남긴다
                    import time as _t
                    ts = _t.mktime(tuple(info.date_time) + (0, 0, -1))
                    os.utime(str(dst), (ts, ts))
                except (OverflowError, ValueError, OSError):
                    pass
                total += got
                written.append(str(dst))
            except (ValueError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
                skipped.append(raw)
                try:
                    tmp.unlink()
                except OSError:
                    pass
            if progress is not None:
                progress(k + 1, len(items), shown)
    return written, skipped, stopped


def cache_member(zip_path, raw: str) -> str:
    """zip 안 파일 하나를 사용자 데이터 폴더 캐시로(읽기 전용으로 본다 — `photo_zip.is_cached`). 이미 있으면 그대로. 배경에서."""
    from viewer import photo_zip
    d = photo_zip.cache_dir_for(zip_path)
    with zipfile.ZipFile(str(zip_path)) as z:
        info = z.getinfo(raw)
        rel = _safe_rel(display_name(info))
        dst = d / rel
        if not rel or not _inside(d, dst):
            raise ValueError("name")
        if dst.exists() and dst.stat().st_size == info.file_size:
            return str(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".part")
        got = 0
        try:
            with z.open(raw) as src, open(tmp, "wb") as fh:
                while True:
                    buf = src.read(CHUNK)
                    if not buf:
                        break
                    got += len(buf)
                    if got > min(MEMBER_MAX_BYTES, info.file_size + CHUNK):
                        raise ValueError("zip member larger than declared")
                    fh.write(buf)
            os.replace(str(tmp), str(dst))
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    try:
        os.utime(d)
    except OSError:
        pass
    return str(dst)


def cached_to_member(zip_path, cached) -> str | None:
    """캐시로 꺼낸 파일 경로 → zip 안 이름(골라서 풀기 — 썸네일 줄·본문에서 고른 사진). 없으면 None."""
    from viewer import photo_zip
    try:
        d = photo_zip.cache_dir_for(zip_path)
        rel = os.path.normcase(os.path.relpath(str(cached), str(d)))
    except (OSError, ValueError):
        return None
    for raw, shown in members(zip_path):
        if os.path.normcase(_safe_rel(shown)) == rel:
            return raw
        if os.path.normcase(_safe_rel(raw)) == rel:          # 사진 캐시는 zip 안 이름 그대로 꺼낸다(photo_zip.extract)
            return raw
    return None


class ZipUnpackWorker(QObject):
    """배경에서 풀기 — 작업 창(`job_add`)의 [중단] 은 파일 하나가 끝난 뒤 멈춘다(푼 것은 남긴다)."""
    progress = pyqtSignal(int, int, str)
    done = pyqtSignal(str, str, list, list, bool)     # zip, 넣은 폴더, 쓴 파일, 건너뛴 이름, 멈췄나
    finished = pyqtSignal()

    def __init__(self, zip_path, dest, names=None, strip_dirs: bool = False):
        super().__init__()
        self.zip_path, self.dest = str(zip_path), str(dest)
        self.names = None if names is None else list(names)
        self.strip_dirs = bool(strip_dirs)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        written, skipped, stopped = [], [], False
        try:
            Path(self.dest).mkdir(parents=True, exist_ok=True)
            from viewer import pacing
            written, skipped, stopped = unpack(self.zip_path, self.dest, self.names, should_cancel=lambda: self._cancel,
                                               progress=lambda i, n, s: self.progress.emit(i, n, s),
                                               strip_dirs=self.strip_dirs, pace=lambda: pacing.pace(self))
        except Exception:
            skipped = list(self.names or []) or ["*"]
        finally:
            self.done.emit(self.zip_path, self.dest, written, skipped, stopped)
            self.finished.emit()


class ZipMembersWorker(QObject):
    """261106-23: zip 목차를 배경에서 읽는다(책갈피창 zip 줄을 펼쳤는데 기억이 없을 때) — 읽은 것은 `members` 가 기억한다."""
    done = pyqtSignal(str, list)                      # zip, [(zip 안 이름, 보일 이름)]
    finished = pyqtSignal()

    def __init__(self, zip_path, exts=None):
        super().__init__()
        self.zip_path = str(zip_path)
        self.exts = None if exts is None else tuple(exts)

    def request_cancel(self):
        pass

    def run(self):
        got = []
        try:
            got = members(self.zip_path, self.exts)
        except Exception:
            got = []
        finally:
            self.done.emit(self.zip_path, list(got))
            self.finished.emit()


class ZipCacheWorker(QObject):
    """PDF 모드 zip 줄 아래 PDF 를 누르면 — 그 파일 하나만 캐시로 꺼낸다(배경)."""
    done = pyqtSignal(str, str, str)                  # zip, zip 안 이름, 꺼낸 경로(실패면 "")
    finished = pyqtSignal()

    def __init__(self, zip_path, raw):
        super().__init__()
        self.zip_path, self.raw = str(zip_path), str(raw)

    def request_cancel(self):
        pass

    def run(self):
        out = ""
        try:
            out = cache_member(self.zip_path, self.raw)
        except Exception:
            out = ""
        finally:
            self.done.emit(self.zip_path, self.raw, out)
            self.finished.emit()
