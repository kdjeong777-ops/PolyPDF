# -*- coding: utf-8 -*-
"""배경 쓰기 줄 하나 — 설정·사이드카·태그·고친 글 JSON 을 메인 스레드에서 쓰지 않는다 (261108-15, 응답성 SOT §6).

왜: 백신 실시간 검사는 새로 만든 파일·바꿔 끼운 파일을 붙든다. 메인의 `os.replace` 가 21.4초 선 적이 있고
(원본 저장은 그래서 `_file_op_bg`), 설정(`settings_store.save`)·꾸밈(`page_meta`)·링크(`hyperlinks`)·태그(`tag_store`)·
고친 글(`text_fix_store`)은 메인에서 tmp 쓰기 + `os.replace`(설정은 fsync 까지) 를 했다.

규칙
- **직렬화는 부르는 쪽(메인)에서** 끝낸 글(str)을 넘긴다 — 메인이 바꾸는 dict 를 배경에서 읽지 않는다.
- 경로마다 **마지막 글만** 남는다. `DELAY_S` 뒤에 한 번 쓴다(잇단 저장은 한 번으로 모인다).
- 쓰기는 tmp(이 프로세스 이름) → `os.replace`(잠겼으면 `REPLACE_TRIES` 번 다시) → 끝내 안 되면 바로 쓰기 → 그래도 실패면
  `error.log` 와 `on_error(경로, 까닭)`(배경 스레드에서 부른다 — 받는 쪽이 메인으로 넘긴다).
- **읽기는 `read_text`·`exists`** 로 — 아직 쓰지 않은 글이 있으면 그 글을 돌려준다(같은 프로세스 안에서 순서가 어긋나지 않는다).
- 다른 프로세스·파일 복사가 디스크를 읽기 전, 앱이 끝나기 전에는 `flush()` — `main.py` 는 `os._exit` 로 끝나 atexit 가 돌지
  않으므로 그 앞에서 직접 부른다(atexit 는 검사·자식 프로세스용 덧붙임).
"""
from __future__ import annotations

import atexit
import os
import threading
import time
from pathlib import Path

DELAY_S = 0.3              # 잇단 저장을 모으는 시간 — 이보다 짧게 끝나는 크래시면 마지막 저장을 잃는다
REPLACE_TRIES = 3          # 다른 창·백신이 잠깐 쥐었을 때 os.replace 다시(50ms 간격) — 종전 settings_store 와 같다
FLUSH_TIMEOUT_S = 15.0

_cv = threading.Condition()
_pending: dict = {}        # 키 → [경로, 글, 쓸 시각, fsync]
_inflight: dict = {}       # 키 → 쓰고 있는 글
_thread: threading.Thread | None = None
on_error = None            # (경로, 까닭) — 배경 스레드에서 불린다
stats = {"writes": 0, "fails": 0}


def _key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def submit(path, text: str, *, fsync: bool = False, delay: float | None = None) -> None:
    """`path` 에 `text` 를 쓰도록 맡긴다 — 바로 돌아온다."""
    global _thread
    k = _key(path)
    due = time.monotonic() + (DELAY_S if delay is None else delay)
    with _cv:
        _pending[k] = [str(path), text, due, fsync]
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_run, name="polypdf-bg-write", daemon=True)
            _thread.start()
        _cv.notify_all()


def pending_text(path):
    """아직 디스크에 다 쓰지 않은 마지막 글 — 없으면 None."""
    k = _key(path)
    with _cv:
        e = _pending.get(k)
        if e is not None:
            return e[1]
        return _inflight.get(k)


def read_text(path, encoding: str = "utf-8") -> str:
    """`Path.read_text` 와 같되 맡겨 둔 글이 있으면 그것(파일이 없으면 FileNotFoundError 그대로)."""
    t = pending_text(path)
    if t is not None:
        return t
    return Path(path).read_text(encoding=encoding)


def exists(path) -> bool:
    return pending_text(path) is not None or Path(path).exists()


def busy(path=None) -> bool:
    with _cv:
        if path is None:
            return bool(_pending or _inflight)
        k = _key(path)
        return k in _pending or k in _inflight


def flush(path=None, timeout: float = FLUSH_TIMEOUT_S) -> bool:
    """맡긴 쓰기(`path` 만 또는 전부)를 지금 쓰고 끝날 때까지 기다린다. 끝나면 True."""
    keys = None if path is None else {_key(path)}
    end = time.monotonic() + timeout
    with _cv:
        for k, e in _pending.items():
            if keys is None or k in keys:
                e[2] = 0.0
        _cv.notify_all()
        while True:
            left = [k for k in list(_pending) + list(_inflight) if keys is None or k in keys]
            if not left:
                return True
            if _thread is None or not _thread.is_alive():
                break
            rem = end - time.monotonic()
            if rem <= 0:
                return False
            _cv.wait(min(rem, 0.05))
    # 쓰는 스레드가 없다(인터프리터 종료 중 등) — 이 스레드에서 바로 쓴다
    with _cv:
        items = [(k, _pending.pop(k)) for k in list(_pending) if keys is None or k in keys]
    for _k, e in items:
        _write(e[0], e[1], e[3])
    return True


def _run():
    while True:
        with _cv:
            while True:
                if not _pending:
                    _cv.wait(5.0)
                    if not _pending:
                        continue
                now = time.monotonic()
                k, e = min(_pending.items(), key=lambda kv: kv[1][2])
                if e[2] <= now:
                    del _pending[k]
                    _inflight[k] = e[1]
                    break
                _cv.wait(e[2] - now)
        try:
            _write(e[0], e[1], e[3])
        finally:
            with _cv:
                if _inflight.get(k) is e[1]:
                    del _inflight[k]
                _cv.notify_all()


def _write(path: str, text: str, fsync: bool) -> bool:
    p = Path(path)
    tmp = p.with_name("%s.%d.bgw.tmp" % (p.name, os.getpid()))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
    except Exception as e:      # noqa: BLE001
        _failed(p, "tmp %s: %s" % (type(e).__name__, e))
        try:
            tmp.unlink()
        except Exception:
            pass
        return False
    for i in range(REPLACE_TRIES):
        try:
            os.replace(tmp, p)
            stats["writes"] += 1
            return True
        except PermissionError:
            if i + 1 < REPLACE_TRIES:
                time.sleep(0.05)
        except Exception:
            break
    ok = True
    try:
        with open(p, "w", encoding="utf-8", newline="\n") as f:     # 바꿔 끼우기가 끝내 안 되면 바로 쓴다(종전 settings_store 와 같다)
            f.write(text)
        stats["writes"] += 1
    except Exception as e:      # noqa: BLE001
        ok = False
        _failed(p, "%s: %s" % (type(e).__name__, e))
    try:
        tmp.unlink()
    except Exception:
        pass
    return ok


def _failed(p: Path, why: str) -> None:
    stats["fails"] += 1
    try:
        from viewer import settings_store
        settings_store._log_error("[배경 쓰기 실패] %s %s" % (p, why))
    except Exception:
        pass
    cb = on_error
    if cb is not None:
        try:
            cb(str(p), why)
        except Exception:
            pass


atexit.register(flush)
