"""260915-2(마스터 §4.7.8): 다른 PolyPDF 창(프로그램)과 '이 PDF 를 놓아 달라' 를 주고받는다.

같은 PDF 를 다른 PolyPDF 가 열고 있으면, 이 창이 저장해도 그 창은 바뀐 파일을 **낡은 상태로**
계속 읽는다(화면이 깨지거나 오류). 그래서 원본을 덮어쓰기 전에 그 창에 물어 파일을 놓게 하고,
저장이 끝나면 같은 쪽으로 다시 열게 한다.

- 창마다 `QLocalServer` 하나(이름 `polypdf-<사용자>-<pid>-<n>`)를 열고, 설정 폴더의
  `instances/<이름>.json` 에 적어 서로 찾는다. 연결되지 않는 항목(죽은 프로세스)은 지운다.
- 요청·응답은 JSON 한 줄. `query`(열고 있나·저장 안 한 편집이 있나) / `release`(놓기) /
  `reload`(다시 열기) / `show`(그 폴더를 보고 있으면 목록에 더하고 열기 — 가상 프린터, 261031-4) /
  `photo`(사진 모드인 창이면 그 사진의 폴더·사진을 열기 — 기본 사진 앱으로 두 번 누름, 261112-10, 사진 보기 SOT §4.45) /
  `update_quit`(다른 창이 업데이트하려고 곧 이 창을 닫는다 — 업데이트 창을 다시 띄우지 않기, 261113-2, 릴리스 SOT §14.5 U25).
  창 쪽 동작은 `handler(op, path, page)` 가 한다(앱이 넣는다).
- 기다림은 짧다(연결 0.3초·응답 3초) — 응답하지 않는 창 하나 때문에 저장이 멈추지 않게.
"""
from __future__ import annotations

import getpass
import itertools
import json
import os
from pathlib import Path

from PyQt6.QtCore import QObject
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

CONNECT_MS = 300
REPLY_MS = 3000
_seq = itertools.count(1)


def _registry_dir() -> Path:
    from viewer.settings_store import settings_dir
    d = settings_dir() / "instances"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _user() -> str:
    try:
        u = getpass.getuser()
    except Exception:
        u = "user"
    return "".join(c for c in u if c.isalnum()) or "user"


def _pid_alive(pid) -> bool:
    """260915-9: 등록된 프로세스가 살아 있나 — 죽은 등록에 연결을 시도하면 항목마다 `CONNECT_MS` 를 기다린다
    (실측 0.65초). Windows 는 `OpenProcess`+`GetExitCodeProcess`. 판단이 안 서면 True(연결로 확인)."""
    try:
        pid = int(pid)
    except Exception:
        return True
    if os.name != "nt":
        return True
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5          # 접근 거부 = 있기는 하다
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code)):
                return True
            return code.value == 259                     # STILL_ACTIVE
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        return True


def same_file(a, b) -> bool:
    try:
        from viewer.pathutil import norm_key
        return norm_key(str(a)) == norm_key(str(b))
    except Exception:
        return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def _peer_entries(skip=None):
    """등록된 다른 창 → [(서버 이름, 등록 파일)]. 끝난 프로세스의 등록은 연결해 보지 않고 치운다."""
    try:
        entries = sorted(_registry_dir().glob("polypdf-*.json"))
    except Exception:
        return []
    out = []
    for f in entries:
        try:
            info = json.loads(f.read_text(encoding="utf-8"))
            name = info.get("server")
        except Exception:
            info, name = {}, None
        if not name or name == skip:
            continue
        if not _pid_alive(info.get("pid")):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
            continue
        out.append((name, f))
    return out


def _request(name, msg, timeout=REPLY_MS):
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(CONNECT_MS):
        return None
    try:
        sock.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        sock.flush()
        buf = b""
        while b"\n" not in buf:
            if not sock.waitForReadyRead(timeout):
                return {"error": "응답 없음"}
            buf += bytes(sock.readAll())
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except Exception as e:                      # noqa: BLE001
        return {"error": str(e)}
    finally:
        sock.disconnectFromServer()


def send_photo(path) -> bool:
    """261112-10(사진 보기 SOT §4.45): 기본 사진 앱으로 두 번 누른 사진을 **사진 모드인** 다른 창에 넘긴다 — 받은 창이 있으면 True.
    창이 없는 시작 단계(main.py)에서 부른다 — 서버를 열지 않는다. 받은 창이 앞으로 나올 수 있게 전경 허락을 먼저 준다."""
    peers = _peer_entries()
    if not peers:
        return False
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)      # ASFW_ANY
        except Exception:
            pass
    for name, f in peers:
        res = _request(name, {"op": "photo", "path": str(path)})
        if res is None:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
            continue
        if res.get("ok"):
            return True
    return False


class InstanceLink(QObject):
    def __init__(self, handler, parent=None):
        super().__init__(parent)
        self._handler = handler
        self.name = f"polypdf-{_user()}-{os.getpid()}-{next(_seq)}"
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(self.name)
        self._reg = None
        if self._server.listen(self.name):
            self._server.newConnection.connect(self._on_connection)
            try:
                self._reg = _registry_dir() / f"{self.name}.json"
                self._reg.write_text(json.dumps({"server": self.name, "pid": os.getpid()}),
                                     encoding="utf-8")
            except Exception:
                self._reg = None

    # ── 받는 쪽 ───────────────────────────────────────────
    def _on_connection(self):
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._on_ready(s))
            sock.disconnected.connect(sock.deleteLater)

    def _on_ready(self, sock):
        if not sock.canReadLine():
            return
        try:
            req = json.loads(bytes(sock.readLine()).decode("utf-8"))
            res = self._handler(req.get("op"), req.get("path"), req.get("page"))
        except Exception as e:                      # noqa: BLE001
            res = {"error": str(e)}
        try:
            sock.write((json.dumps(res or {}, ensure_ascii=False) + "\n").encode("utf-8"))
            sock.flush()
        except Exception:
            pass

    def close(self):
        try:
            self._server.close()
        except Exception:
            pass
        if self._reg is not None:
            try:
                self._reg.unlink(missing_ok=True)
            except Exception:
                pass
            self._reg = None

    # ── 묻는 쪽 ───────────────────────────────────────────
    def _peers(self):
        return _peer_entries(self.name)

    @staticmethod
    def _request(name, msg, timeout=REPLY_MS):
        return _request(name, msg, timeout)
    def holders(self, path) -> list:
        """이 PDF 를 열고 있는 다른 창 → [{server, title, dirty}]. 죽은 등록은 지운다."""
        found = []
        for name, f in self._peers():
            res = self._request(name, {"op": "query", "path": str(path)})
            if res is None:
                try:
                    f.unlink(missing_ok=True)       # 연결 안 됨 = 끝난 프로세스
                except Exception:
                    pass
                continue
            if res.get("open"):
                found.append({"server": name, "title": res.get("title") or "PolyPinax",   # 261114-6: 보이는 이름
                              "dirty": bool(res.get("dirty"))})
        return found

    def release(self, holders, path) -> list:
        """그 창들에 놓게 한다 → 놓은 창 [{server, page}] (못 놓은 창은 뺀다)."""
        done = []
        for h in holders:
            res = self._request(h["server"], {"op": "release", "path": str(path)})
            if res and res.get("ok"):
                done.append({"server": h["server"], "page": int(res.get("page") or 0)})
        return done

    def reload(self, released, path):
        for r in released:
            self._request(r["server"], {"op": "reload", "path": str(path), "page": r["page"]})

    def broadcast(self, msg, timeout=REPLY_MS) -> int:
        """모든 다른 창에 같은 요청을 보낸다 → `ok` 로 답한 창 수. 연결 안 되는 등록은 지운다
        (261113-2, 릴리스 SOT §14.5 U25 — 업데이트로 닫기 전에 `update_quit` 알림)."""
        n = 0
        for name, f in self._peers():
            res = self._request(name, msg, timeout)
            if res is None:
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
                continue
            if res.get("ok"):
                n += 1
        return n

    def show_file(self, path) -> bool:
        """261031-4(가상 프린터 SOT §4.4): 그 PDF 의 폴더를 책갈피창에 보고 있는 다른 창에 넘긴다(`show`) —
        처음 받은 창 하나가 목록에 더하고 연다. 받은 창이 있으면 True. 죽은 등록은 지운다."""
        for name, f in self._peers():
            res = self._request(name, {"op": "show", "path": str(path)})
            if res is None:
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
                continue
            if res.get("ok"):
                return True
        return False
