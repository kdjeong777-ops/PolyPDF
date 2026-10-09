# -*- coding: utf-8 -*-
"""261009-16: 한국어 띄어쓰기(kiwi)를 **별도 프로세스**에서 묻는다 (응답성 SOT §4 ③·§6, 텍스트 창 SOT §3.7.10).

kiwi 는 만들 때(0.74초)와 첫 `space()`(0.48초)에 **GIL 을 쥔다** — 배경 스레드에서 불러도 메인이 선다.
색인이 같이 돌면 메인이 둘 다를 기다려 2.28초(설치본 재실측, 응답성 SOT §9.1). 프로세스가 다르면 GIL 을 나누지 않는다.

- 부모: `Listener(AF_PIPE, authkey)` 를 열고 `PolyPDF.exe --kiwi-space-server <주소>`(개발: `python main.py …`)를
  띄운다. 키는 환경변수로 넘긴다. 자식은 kiwi 를 만들고 **첫 `space()` 까지 치른 뒤** 'ready' 를 보낸다.
  부모가 하는 일은 프로세스 띄우기·파이프 열기뿐이고, 기다리는 일은 배경 스레드(`kiwi-space-boot`)가 한다.
- `space(text)` → 띄어 쓴 글 또는 None(못 씀). 잠금 하나로 보내고-받기를 묶는다. 기다리는 동안 GIL 을 놓는다.
- **UI 스레드**(`set_ui_thread`)는 준비가 안 됐으면 기다리지 않고 None — 부르는 쪽이 기하 규칙으로 물러선다.
  워커는 준비를 `READY_WAIT_S` 까지 기다린다(결과가 시작 시점에 따라 갈리지 않게).
- 자식은 부모 쪽 파이프가 닫히면(부모 종료·`os._exit`) 스스로 끝난다.
- 자식을 못 띄운 기기면 `failed()` 가 참 — 부르는 쪽이 종전대로 이 프로세스에서 kiwi 를 쓴다(워커에서만).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

SERVER_ARG = "--kiwi-space-server"
KEY_ENV = "POLYPDF_KIWI_KEY"
READY_WAIT_S = 20.0      # 워커가 자식의 준비를 기다리는 한도(설치본 찬 시작 + 백신 검사 여유)
CALL_TIMEOUT_S = 5.0     # 한 번 묻는 데 이보다 오래면 자식이 멈춘 것으로 본다
UI_WAIT_S = 0.2          # UI 스레드가 잠금·답을 기다리는 한도 — 넘으면 이번만 물러선다(창이 서지 않게, 응답성 SOT §2)

_start_lock = threading.Lock()
_io_lock = threading.Lock()      # 보내고-받기 한 쌍을 묶는다(여러 스레드가 함께 부른다)
_ready = threading.Event()       # 준비됐거나 실패했으면 켜진다 — `_state["bad"]` 로 가른다
_state = {"started": False, "bad": False, "conn": None, "proc": None}
_ui_ident = None


def set_ui_thread() -> None:
    """이 스레드에서는 자식의 준비를 기다리지 않는다(창이 서지 않게). MainWindow 가 만들 때 부른다."""
    global _ui_ident
    _ui_ident = threading.get_ident()


def on_ui_thread() -> bool:
    return threading.get_ident() == _ui_ident


def failed() -> bool:
    """자식을 띄우지 못했거나 도중에 죽었다 — 다시 띄우지 않는다."""
    return bool(_state["bad"])


def ready() -> bool:
    return _ready.is_set() and not _state["bad"]


def make_kiwi():
    """띄어쓰기용 kiwi 를 짓는다 — 자식(`serve`)과 물러설 길(`text_extract2._local_kiwi`)이 **같은 설정**을 쓰게 한 곳에.

    261009-14: 기본·오타·복합 사전은 싣지 않는다 — 띄어쓰기(`space`)만 쓴다. 실제 한글 PDF 5종 1,506곳에서 판정 99.9% 같다
    (다른 2곳: 이름 사이·단위). kiwipiepy 를 올릴 때는 여기만 고치고 `test_text_ko_space`·`test_kiwi_space` 를 돌린다."""
    from kiwipiepy import Kiwi
    return Kiwi(load_default_dict=False, load_typo_dict=False, load_multi_dict=False)


def _command(address: str) -> list:
    if getattr(sys, "frozen", False):
        return [sys.executable, SERVER_ARG, address]
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return [sys.executable, main_py, SERVER_ARG, address]


def start() -> None:
    """한 번만 띄운다. 곧바로 돌아온다 — 자식을 기다리는 일은 배경 스레드가."""
    with _start_lock:
        if _state["started"]:
            return
        _state["started"] = True
    threading.Thread(target=_boot, name="kiwi-space-boot", daemon=True).start()


def _fail() -> None:
    _state["bad"] = True
    conn = _state.get("conn")
    _state["conn"] = None
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _ready.set()                  # 기다리는 워커를 깨운다(실패로)


def _watch(proc) -> None:
    """자식이 준비 전에 끝나면 실패로 — `Listener.accept()` 에는 시간 한도가 없다."""
    try:
        proc.wait()
    except Exception:
        pass
    if not _ready.is_set() or _state["conn"] is None:
        _fail()


def _boot() -> None:
    try:
        from multiprocessing.connection import Listener
        key = os.urandom(16)
        listener = Listener(family="AF_PIPE", authkey=key)
        env = dict(os.environ)
        env[KEY_ENV] = key.hex()
        proc = subprocess.Popen(
            _command(listener.address), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _state["proc"] = proc
        threading.Thread(target=_watch, args=(proc,), name="kiwi-space-watch", daemon=True).start()
        conn = listener.accept()
        msg = conn.recv()             # 자식이 kiwi 를 다 지을 때까지 — GIL 을 놓고 기다린다
        try:
            listener.close()
        except Exception:
            pass
        if msg != "ready":
            raise RuntimeError(str(msg))
        _state["conn"] = conn
        _ready.set()
    except Exception:
        _fail()


def space(text: str):
    """kiwi 가 띄어 쓴 글. 못 쓰면 None — 부르는 쪽이 다른 길로 간다."""
    if _state["bad"]:
        return None
    if not _ready.is_set():
        start()
        if on_ui_thread():
            return None
        if not _ready.wait(READY_WAIT_S):
            return None
    ui = on_ui_thread()
    if not _io_lock.acquire(timeout=UI_WAIT_S if ui else CALL_TIMEOUT_S):
        return None                      # 다른 스레드가 묻는 중 — UI 는 이번만 물러선다
    try:
        conn = _state["conn"]
        if conn is None:
            return None
        try:
            conn.send(text)
            if not conn.poll(CALL_TIMEOUT_S):
                raise TimeoutError("kiwi-space")
            out = conn.recv()
        except Exception:
            _fail()
            return None
    finally:
        _io_lock.release()
    return out if isinstance(out, str) else None


def serve(address: str) -> None:
    """자식 쪽 — `main.py` 가 PyQt 를 싣기 전에 부른다. kiwi 를 짓고 묻는 대로 답한다."""
    from multiprocessing.connection import Client
    key = bytes.fromhex(os.environ.get(KEY_ENV, ""))
    conn = Client(address, family="AF_PIPE", authkey=key)
    try:
        k = make_kiwi()
        k.space("준비된 문장")          # 첫 호출의 모델 짓기를 여기서 치른다
    except Exception as e:
        try:
            conn.send("error: %r" % (e,))
        except Exception:
            pass
        return
    conn.send("ready")
    while True:
        try:
            text = conn.recv()
        except (EOFError, OSError):
            return                       # 부모가 끝났다
        try:
            out = k.space(text)
        except Exception:
            out = None
        try:
            conn.send(out)
        except (EOFError, OSError):
            return
