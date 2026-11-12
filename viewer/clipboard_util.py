# -*- coding: utf-8 -*-
"""클립보드에 그림 넣기 — 한 곳 (261024-2, 스크린샷 SOT §8.3).

Windows 클립보드는 한 번에 한 프로그램만 연다. 다른 프로그램(클립보드 기록 서비스·메신저·
캡처 도구 등)이 쥐고 있으면 Qt 의 `setImage` 는 `OpenClipboard` 실패(0x800401D0)를 경고로만
남기고 **다시 시도하지 않는다** — 예외도 없어 부르는 쪽은 성공한 줄 안다. 그래서 넣은 뒤
정말 들어갔는지 보고, 아니면 타이머로 몇 번 더 넣는다(메인에서 기다리지 않는다).
"""
import ctypes
import uuid
from ctypes import wintypes

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QImage, QPixmap
from PyQt6.QtWidgets import QApplication

RETRY_MS = 250        # 다시 넣기 간격
RETRY_TRIES = 8       # 첫 시도 포함. 실패한 넣기 한 번이 Qt 안에서 약 0.33초 서서, 모두 약 4.5초
HISTORY_CLEAR_TIMEOUT_S = 8   # 기록 지우기를 기다리는 상한(검사가 쓴다) — 지금은 같은 프로세스 안 호출이라 곧바로 끝난다

# 261108-19(스크린샷 SOT §8.1): Win+V 기록 지우기는 WinRT `Clipboard`(IClipboardStatics2)를 **이 프로세스 안에서** 부른다.
#   종전 PowerShell `-Command` 자식 프로세스는 백신이 의심하는 모양이고 한 번에 1.5~2.2초 걸렸다.
_CLIP_CLASS = "Windows.ApplicationModel.DataTransfer.Clipboard"
_IID_CLIP_STATICS2 = "{D2AC1B6A-D29F-554B-B303-F0452345FE02}"
_VT_CLEAR_HISTORY = 7          # IInspectable 6 + GetHistoryItemsAsync 다음
_VT_IS_HISTORY_ENABLED = 10    # … DeleteItemFromHistory · SetHistoryItemAsContent 다음(261108-19 실측: 레지스트리 값과 같음)


class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]


def _clip_statics_call(index: int):
    """IClipboardStatics2 의 `HRESULT f(this, boolean*)` 꼴 함수를 부르고 (hr, 값). 이 스레드를 STA 로 연다 —
    MTA 에서는 RO_E_UNSUPPORTED_FROM_MTA(0x8000001D, 실측). 실패하면 (None, None)."""
    try:
        combase = ctypes.WinDLL("combase")
    except OSError:
        return None, None
    combase.RoInitialize.argtypes = [ctypes.c_int]
    combase.RoInitialize.restype = ctypes.c_long
    combase.WindowsCreateString.argtypes = [wintypes.LPCWSTR, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    combase.WindowsCreateString.restype = ctypes.c_long
    combase.WindowsDeleteString.argtypes = [ctypes.c_void_p]
    combase.RoGetActivationFactory.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    combase.RoGetActivationFactory.restype = ctypes.c_long
    init = combase.RoInitialize(0)                          # RO_INIT_SINGLETHREADED
    hs, fac = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        if combase.WindowsCreateString(_CLIP_CLASS, len(_CLIP_CLASS), ctypes.byref(hs)) != 0:
            return None, None
        u = uuid.UUID(_IID_CLIP_STATICS2)
        iid = _GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        if combase.RoGetActivationFactory(hs, ctypes.byref(iid), ctypes.byref(fac)) != 0 or not fac.value:
            return None, None
        vt = ctypes.cast(ctypes.cast(fac, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte))(vt[index])
        out = ctypes.c_ubyte(0)
        hr = fn(fac, ctypes.byref(out))
        return hr, bool(out.value)
    except Exception:
        return None, None
    finally:
        if fac.value:
            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
                ctypes.cast(ctypes.cast(fac, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))[2])
            release(fac)
        if hs.value:
            combase.WindowsDeleteString(hs)
        if init in (0, 1):                                  # S_OK·S_FALSE 면 짝을 맞춘다
            combase.RoUninitialize()


def history_enabled():
    """Win+V 기록이 켜져 있나(WinRT `IsHistoryEnabled`) — 모르면 None."""
    hr, val = _clip_statics_call(_VT_IS_HISTORY_ENABLED)
    return val if hr == 0 else None


def clear_history() -> bool:
    """Win+V 기록 지우기(WinRT `ClearHistory`) — 기록이 꺼져 있으면 부르지 않는다. 지웠으면 True. 배경 스레드에서 부른다."""
    if history_enabled() is False:
        return False
    hr, val = _clip_statics_call(_VT_CLEAR_HISTORY)
    return hr == 0 and bool(val)


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


PNG_MIME = 'application/x-qt-windows-mime;value="PNG"'     # Windows 의 'PNG' 클립보드 형식(투명이 사는 형식)


def set_image(img, on_done=None, tries=RETRY_TRIES, interval_ms=RETRY_MS, png: bytes | None = None):
    """그림(QImage·QPixmap)을 클립보드에 넣는다. 끝나면 `on_done(ok)`.

    첫 시도는 곧바로 한다 — 대개 여기서 끝나고 `on_done` 도 곧바로 불린다.
    `png`(261112-16, 스크린샷 SOT §8.3·사진 보기 SOT §4.46): 투명 그림이면 PNG 바이트를 함께 — 그림 형식(DIB)만으로는
    Office·메신저 등에서 투명이 검은 바탕이 된다. 'PNG' 형식과 `image/png` 를 그림과 함께 올린다."""
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
            if png:
                from PyQt6.QtCore import QMimeData
                md = QMimeData()
                md.setImageData(img)
                md.setData(PNG_MIME, png)
                md.setData("image/png", png)
                QApplication.clipboard().setMimeData(md)
            else:
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
    """Win+V 기록 지우기(스크린샷 SOT §8.1, 응답성 SOT §4.4) — `clear_history`(WinRT, 같은 프로세스).
    STA 를 여는 호출이라 메인 스레드(Qt 가 연 OLE)와 섞지 않게 `workers.run_in_thread` 로 돌린다."""
    finished = pyqtSignal()

    def run(self):
        try:
            clear_history()
        except Exception:
            pass
        self.finished.emit()
