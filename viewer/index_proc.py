# -*- coding: utf-8 -*-
"""261009-19: 색인을 **별도 프로세스**에서 (응답성 SOT §4 ③·§4.4, 검색창 SOT §3).

같은 프로세스의 배경 스레드에서 색인하면 PyMuPDF 의 C 호출이 GIL 을 쥐어 창이 선다 — 그래서 점유율 상한
(`BG_DUTY=0.6`, 벽시계의 6할만 일한다)과 미리 읽기(`_prefetch`)로 버텼고, 그만큼 **첫 색인이 느렸다**(약 1.7배).
자식 프로세스는 GIL 을 나누지 않으므로 **쉬지 않고** 색인하고, 대신 **낮은 우선순위**로 돌아 창이 CPU 를 먼저 쓴다.

- 부모(`IndexWorker` 의 배경 스레드): `run_job` 이 `Listener(AF_PIPE, authkey)` 를 열고
  `PolyPDF.exe --index-server <주소>`(개발: `python main.py …`)를 띄워 일감 하나를 넘기고 진행을 받는다.
- 자식(`serve`): `main.py` 가 PyQt 위젯을 싣기 전에 부른다. `PdfIndex` 로 일감을 하고 진행·오류를 보낸다.
  부모가 보낸 아무 말이나 '취소' 다(파일 사이에서 본다). 부모 쪽 파이프가 닫혀도 끝난다.
- 취소: 부모가 취소를 보내고 `CANCEL_WAIT_S` 안에 안 끝나면 자식을 끝낸다 — 쓰다 만 파일은 `PAGES_PENDING`
  표식이 남아 다음에 다시 읽는다(검색창 SOT §3).
- 자식을 못 띄우면 `run_job` 이 None — 부르는 쪽이 종전대로 이 프로세스의 배경 스레드에서 한다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from viewer.i18n import tr

SERVER_ARG = "--index-server"
KEY_ENV = "POLYPDF_INDEX_KEY"
CONNECT_WAIT_S = 30.0        # 자식이 붙기를 기다리는 한도(설치 직후 첫 실행의 백신 검사 여유)
CANCEL_WAIT_S = 1.5          # 취소를 보낸 뒤 스스로 끝나기를 기다리는 한도
BELOW_NORMAL = 0x00004000    # BELOW_NORMAL_PRIORITY_CLASS — 창(보통 우선순위)이 CPU 를 먼저
ENABLED = True               # 검사가 이 프로세스 경로를 볼 때 끈다


def _command(address: str) -> list:
    if getattr(sys, "frozen", False):
        return [sys.executable, SERVER_ARG, address]
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return [sys.executable, main_py, SERVER_ARG, address]


def run_job(job: dict, on_progress, should_cancel):
    """일감 하나를 자식에서. 끝나면 True, 자식을 못 띄우면 None, 자식이 오류를 보내면 RuntimeError.

    job = {"db": str, "folder": str|None, "files": [str]|None, "verify": bool, "settings_dir": str}"""
    if not ENABLED:
        return None
    try:
        from multiprocessing.connection import Listener
        key = os.urandom(16)
        listener = Listener(family="AF_PIPE", authkey=key)
        env = dict(os.environ)
        env[KEY_ENV] = key.hex()
        proc = subprocess.Popen(
            _command(listener.address), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | BELOW_NORMAL)
    except Exception:
        return None
    from viewer.child_job import attach
    attach(proc)                               # 부모가 어떻게 끝나든 자식도 끝난다(큰 파일 색인 중이어도)
    box = {}

    def _accept():
        try:
            box["conn"] = listener.accept()
        except Exception as e:
            box["err"] = e
    th = threading.Thread(target=_accept, name="index-proc-accept", daemon=True)
    th.start()
    t0 = time.monotonic()
    while th.is_alive():                       # accept 에는 시간 한도가 없다 — 자식이 먼저 죽었는지 함께 본다
        th.join(0.1)
        if proc.poll() is not None or time.monotonic() - t0 > CONNECT_WAIT_S or should_cancel():
            break
    try:
        listener.close()
    except Exception:
        pass
    conn = box.get("conn")
    if conn is None:
        _kill(proc)
        return None if not should_cancel() else True
    try:
        conn.send(job)
        cancel_sent = None
        while True:
            if should_cancel() and cancel_sent is None:
                try:
                    conn.send("cancel")
                except Exception:
                    pass
                cancel_sent = time.monotonic()
            if cancel_sent is not None and time.monotonic() - cancel_sent > CANCEL_WAIT_S:
                _kill(proc)
                return True
            if conn.poll(0.1):
                msg = conn.recv()
                kind = msg[0]
                if kind == "progress":
                    on_progress(msg[1], msg[2], msg[3])
                elif kind == "done":
                    return True
                elif kind == "error":
                    raise RuntimeError(msg[1])
            elif proc.poll() is not None:
                raise RuntimeError(tr("색인 프로세스가 예기치 않게 끝났습니다(코드 {code}).").format(code=proc.returncode))
    except (EOFError, OSError):
        if should_cancel():
            return True
        raise RuntimeError(tr("색인 프로세스와의 연결이 끊겼습니다."))
    finally:
        try:
            conn.close()
        except Exception:
            pass
        try:
            proc.wait(CANCEL_WAIT_S)
        except Exception:
            _kill(proc)


def _kill(proc):
    try:
        proc.kill()
        proc.wait(5)
    except Exception:
        pass


def serve(address: str) -> None:
    """자식 쪽 — 일감 하나를 하고 끝난다."""
    from multiprocessing.connection import Client
    from pathlib import Path
    key = bytes.fromhex(os.environ.get(KEY_ENV, ""))
    conn = Client(address, family="AF_PIPE", authkey=key)
    try:
        job = conn.recv()
    except (EOFError, OSError):
        return
    try:
        from viewer import settings_store
        settings_store._DIR_OVERRIDE = job.get("settings_dir")       # 텍스트 창 교정(text_fix.json)을 같은 곳에서
        from viewer.indexer import PdfIndex
        cancel = lambda: conn.poll(0)                                  # 부모가 보낸 아무 말 = 취소
        idx = PdfIndex(Path(job["db"]), verify=bool(job.get("verify")))
        # GIL 을 나누지 않으므로 쉬지도(점유율 상한), 미리 읽지도 않는다 — 대신 낮은 우선순위(run_job)
        idx.YIELD_S = 0
        idx._prefetch = lambda p: None
        try:
            files = job.get("files")
            if files:
                n = len(files)
                for k, f in enumerate(files):
                    if cancel():
                        break
                    conn.send(("progress", k, n, f))
                    if idx.needs_reindex(Path(f)):
                        idx.index_file(Path(f))
                    conn.send(("progress", k + 1, n, f))
            else:
                idx.index_folder(Path(job["folder"]),
                                 progress=lambda d, t, nm: conn.send(("progress", d, t, nm)),
                                 should_cancel=cancel)
        finally:
            idx.close()
        conn.send(("done",))
    except (EOFError, OSError):
        return
    except Exception as e:
        try:
            conn.send(("error", str(e)))
        except Exception:
            pass
