"""260915-3(마스터 §4.9): 탐색기에서 PDF 여러 개를 골라 열 때 **한 창**으로 모은다.

Windows 는 연결 명령(`"%1"`)을 파일마다 따로 실행한다 — PDF 3개를 골라 열면 PolyPDF 가 3개 뜬다.
그래서 거의 동시에 뜬 실행들 가운데 **먼저 뜬 하나(대표)** 만 창을 만들고, 나머지는 자기 파일을
대표에게 넘기고 창 없이 끝난다.

- 대표 정하기: 사용자별 잠금 파일(`QLockFile`)을 먼저 잡은 실행. Windows 의 이름 있는 파이프는 같은
  이름으로 여럿이 들을 수 있어 서버 이름만으로는 대표가 하나로 정해지지 않는다.
- 대표는 로컬 서버(`polypdf-open-<사용자>`)로 파일을 받는다. 창이 뜬 뒤 `GATHER_MS`(3초)가 지나면
  서버를 닫고 잠금을 푼다 — 그 뒤에 따로 여는 PDF 는 **종전처럼 새 창**이다(사용자 결정: 짧은 시간만).
- 나머지 실행은 무거운 준비(fitz·앱) **전에** 넘기고 끝나야 창이 번쩍이지 않는다. 대표가 아직 준비 중이라
  응답이 늦을 수 있어 넉넉히 기다리고(`HANDOFF_WAIT_MS`), 끝내 응답이 없으면 스스로 창을 연다(파일이 사라지지 않게).
"""
from __future__ import annotations

import getpass
import json
import os
import tempfile
import time

from PyQt6.QtCore import QLockFile, QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

GATHER_MS = 3000            # 대표 창이 뜬 뒤 더 받는 시간
CLAIM_WAIT_MS = 2500        # 대표가 서버를 열 때까지 기다리는 시간
HANDOFF_WAIT_MS = 20000     # 넘긴 파일을 대표가 받았다고 답할 때까지


def _user() -> str:
    try:
        u = getpass.getuser()
    except Exception:
        u = "user"
    return "".join(c for c in u if c.isalnum()) or "user"


def _base() -> str:
    # 검사는 이름을 바꿔 실제로 쓰는 PolyPDF 와 부딪히지 않게 한다
    return os.environ.get("POLYPDF_OPEN_GATHER_NAME") or f"polypdf-open-{_user()}"


def server_name() -> str:
    return _base()


def lock_path() -> str:
    return os.path.join(tempfile.gettempdir(), f"{_base()}.lock")


def hand_off(files, name=None, claim_wait_ms=CLAIM_WAIT_MS, handoff_ms=HANDOFF_WAIT_MS) -> bool:
    """대표에게 파일을 넘긴다. 받았다는 답을 들으면 True(이 실행은 끝내면 된다)."""
    name = name or server_name()
    deadline = time.monotonic() + claim_wait_ms / 1000.0
    sock = QLocalSocket()
    while True:
        sock.connectToServer(name)
        if sock.waitForConnected(200):
            break
        sock.abort()
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    try:
        sock.write((json.dumps({"files": [str(f) for f in files]}, ensure_ascii=False) + "\n").encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(1000)
        buf = b""
        end = time.monotonic() + handoff_ms / 1000.0
        while b"\n" not in buf:
            left = int((end - time.monotonic()) * 1000)
            if left <= 0 or not sock.waitForReadyRead(min(left, 500)):
                if time.monotonic() >= end:
                    return False
                if sock.state() != QLocalSocket.LocalSocketState.ConnectedState:
                    return False
                continue
            buf += bytes(sock.readAll())
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8")).get("ok") is True
    except Exception:
        return False
    finally:
        sock.disconnectFromServer()


class OpenGather(QObject):
    """대표 쪽 — 다른 실행이 넘긴 파일을 받는다. `filesReceived(list)`."""
    filesReceived = pyqtSignal(list)

    def __init__(self, name=None, lock_file=None, parent=None):
        super().__init__(parent)
        self._name = name or server_name()
        self._lock = QLockFile(lock_file or lock_path())
        self._lock.setStaleLockTime(0)
        self._server = None
        self.pending = []           # 창이 생기기 전에 받은 파일

    def claim(self) -> bool:
        """대표가 되면 True(서버를 연다). 이미 대표가 있으면 False."""
        if not self._lock.tryLock(0):
            try:                    # 대표가 죽고 남은 잠금이면 치우고 다시
                if self._lock.removeStaleLockFile() and self._lock.tryLock(0):
                    pass
                else:
                    return False
            except Exception:
                return False
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(self._name)
        if not self._server.listen(self._name):
            self.release()
            return False
        self._server.newConnection.connect(self._on_connection)
        return True

    def close_after(self, ms=GATHER_MS):
        QTimer.singleShot(ms, self.release)

    def release(self):
        if self._server is not None:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None
        try:
            self._lock.unlock()
        except Exception:
            pass

    def _on_connection(self):
        while self._server is not None and self._server.hasPendingConnections():
            s = self._server.nextPendingConnection()
            s.readyRead.connect(lambda s=s: self._on_ready(s))
            s.disconnected.connect(s.deleteLater)
            self._on_ready(s)       # 연결 전에 이미 도착한 글이 있으면 곧바로

    def _on_ready(self, s):
        if not s.canReadLine():
            return
        try:
            files = json.loads(bytes(s.readLine()).decode("utf-8")).get("files") or []
            ok = True
        except Exception:
            files, ok = [], False
        try:
            s.write((json.dumps({"ok": ok}) + "\n").encode("utf-8"))
            s.flush()
        except Exception:
            pass
        if files:
            self.pending.extend(files)
            self.filesReceived.emit(list(files))
