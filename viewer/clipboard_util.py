# -*- coding: utf-8 -*-
"""클립보드에 그림 넣기 — 한 곳 (261024-2, 스크린샷 SOT §8.3).

Windows 클립보드는 한 번에 한 프로그램만 연다. 다른 프로그램(클립보드 기록 서비스·메신저·
캡처 도구 등)이 쥐고 있으면 Qt 의 `setImage` 는 `OpenClipboard` 실패(0x800401D0)를 경고로만
남기고 **다시 시도하지 않는다** — 예외도 없어 부르는 쪽은 성공한 줄 안다. 그래서 넣은 뒤
정말 들어갔는지 보고, 아니면 타이머로 몇 번 더 넣는다(메인에서 기다리지 않는다).
"""
import subprocess

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QImage, QPixmap
from PyQt6.QtWidgets import QApplication

RETRY_MS = 250        # 다시 넣기 간격
RETRY_TRIES = 8       # 첫 시도 포함. 실패한 넣기 한 번이 Qt 안에서 약 0.33초 서서, 모두 약 4.5초
HISTORY_CLEAR_TIMEOUT_S = 8

_PS_CLEAR_HISTORY = (
    "try{[Windows.ApplicationModel.DataTransfer.Clipboard,Windows.ApplicationModel.DataTransfer,"
    "ContentType=WindowsRuntime]::ClearHistory()}catch{}")


def _took():
    """방금 넣은 것이 들어갔나. Windows 는 `ownsClipboard()`(곧바로 답한다) — `mimeData()` 는
    다른 프로그램이 쥔 동안 **놓을 때까지 메인을 세운다**(실측 2.7초). 다른 플랫폼은 프로그램 안 클립보드."""
    try:
        c = QApplication.clipboard()
        if QGuiApplication.platformName() == "windows":
            return bool(c.ownsClipboard())
        md = c.mimeData()
        return bool(md is not None and md.hasImage())
    except Exception:
        return False


def holder_name():
    """지금 클립보드를 연 채 쥐고 있는 프로그램의 실행 파일 이름(예 'EXCEL.EXE') — 모르면 None (261107-1).

    `GetOpenClipboardWindow` → 창의 프로세스 → 실행 파일. 모두 곧바로 답하는 조회라 메인에서 불러도 된다
    (클립보드를 열지 않는다). 창 없이 연 프로그램(`OpenClipboard(NULL)`)·권한이 높은 프로세스는 알 수 없다."""
    if QGuiApplication.platformName() != "windows":
        return None
    try:
        import ctypes
        import ctypes.wintypes as wt
        import os
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        u.GetOpenClipboardWindow.restype = wt.HWND
        u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        k.OpenProcess.restype = wt.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        k.CloseHandle.argtypes = [wt.HANDLE]
        hwnd = u.GetOpenClipboardWindow()
        if not hwnd:
            return None
        pid = wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value == os.getpid():
            return None
        h = k.OpenProcess(0x1000, False, pid.value)       # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(520)
            n = wt.DWORD(520)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return os.path.basename(buf.value) or None
        finally:
            k.CloseHandle(h)
    except Exception:
        pass
    return None


def set_image(img, on_done=None, tries=RETRY_TRIES, interval_ms=RETRY_MS):
    """그림(QImage·QPixmap)을 클립보드에 넣는다. 끝나면 `on_done(ok)`.

    첫 시도는 곧바로 한다 — 대개 여기서 끝나고 `on_done` 도 곧바로 불린다."""
    if isinstance(img, QPixmap):
        img = img.toImage()
    if img is None or not isinstance(img, QImage) or img.isNull():
        if on_done:
            on_done(False)
        return
    state = {"left": max(1, int(tries))}

    def attempt():
        state["left"] -= 1
        try:
            QApplication.clipboard().setImage(img)
        except Exception:
            pass
        if _took():
            if on_done:
                on_done(True)
        elif state["left"] > 0:
            QTimer.singleShot(interval_ms, attempt)
        elif on_done:
            on_done(False)

    attempt()


class ClipHistoryClearWorker(QObject):
    """Win+V 기록 지우기(스크린샷 SOT §8.1, 응답성 SOT §4.4) — PowerShell 자식 프로세스라
    메인에서 돌리면 창이 1.5~2.2초 선다. `workers.run_in_thread` 로 돌린다."""
    finished = pyqtSignal()

    def run(self):
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", _PS_CLEAR_HISTORY],
                           creationflags=0x08000000, timeout=HISTORY_CLEAR_TIMEOUT_S)
        except Exception:
            pass
        self.finished.emit()
