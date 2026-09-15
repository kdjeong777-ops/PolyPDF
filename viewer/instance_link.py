"""260915-2(마스터 §4.7.8): 다른 PolyPDF 창(프로그램)과 '이 PDF 를 놓아 달라' 를 주고받는다.

같은 PDF 를 다른 PolyPDF 가 열고 있으면, 이 창이 저장해도 그 창은 바뀐 파일을 **낡은 상태로**
계속 읽는다(화면이 깨지거나 오류). 그래서 원본을 덮어쓰기 전에 그 창에 물어 파일을 놓게 하고,
저장이 끝나면 같은 쪽으로 다시 열게 한다.

- 창마다 `QLocalServer` 하나(이름 `polypdf-<사용자>-<pid>-<n>`)를 열고, 설정 폴더의
  `instances/<이름>.json` 에 적어 서로 찾는다. 연결되지 않는 항목(죽은 프로세스)은 지운다.
- 요청·응답은 JSON 한 줄. `query`(열고 있나·저장 안 한 편집이 있나) / `release`(놓기) /
  `reload`(다시 열기). 창 쪽 동작은 `handler(op, path, page)` 가 한다(앱이 넣는다).
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


def same_file(a, b) -> bool:
    try:
        from viewer.pathutil import norm_key
        return norm_key(str(a)) == norm_key(str(b))
    except Exception:
        return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


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
        try:
            entries = sorted(_registry_dir().glob("polypdf-*.json"))
        except Exception:
            return []
        out = []
        for f in entries:
            try:
                name = json.loads(f.read_text(encoding="utf-8")).get("server")
            except Exception:
                name = None
            if name and name != self.name:
                out.append((name, f))
        return out

    @staticmethod
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
                found.append({"server": name, "title": res.get("title") or "PolyPDF",
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
