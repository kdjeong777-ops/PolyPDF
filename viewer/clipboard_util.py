# -*- coding: utf-8 -*-
"""클립보드에 넣기 — 한 곳: 그림 `set_image`·글 `set_text`·파일 `set_files`·표식 `set_data` (261024-2·261113-6, 스크린샷 SOT §8.3·§8.4).

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


PNG_MIME = 'application/x-qt-windows-mime;value="PNG"'     # Windows 의 'PNG' 클립보드 형식(투명이 사는 형식) — Qt 를 쓰는 다른 플랫폼용
CF_DIB, CF_DIBV5 = 8, 17
_owner = {"hwnd": None}


def _owner_hwnd():
    """클립보드 주인으로 쓸 메시지 전용 창(부르는 스레드 = 메인). `OpenClipboard(NULL)` 이면 `SetClipboardData` 가 실패한다."""
    if _owner["hwnd"]:
        return _owner["hwnd"]
    u = ctypes.windll.user32
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                  wintypes.HINSTANCE, wintypes.LPVOID]
    _owner["hwnd"] = u.CreateWindowExW(0, "STATIC", "PolyPDF clipboard", 0, 0, 0, 0, 0,
                                       wintypes.HWND(-3), None, None, None)      # HWND_MESSAGE
    return _owner["hwnd"]


def owns() -> bool:
    """마지막으로 올린 것이 아직 클립보드에 있나 — 주인이 앱의 창인지(곧바로 답한다, 클립보드를 열지 않는다)."""
    if QGuiApplication.platformName() != "windows":
        return _took()
    try:
        u = ctypes.windll.user32
        u.GetClipboardOwner.restype = wintypes.HWND
        h = _owner["hwnd"]
        return bool(h) and u.GetClipboardOwner() == h
    except Exception:
        return False


def _bits(img: QImage) -> bytes:
    """QImage 의 픽셀 바이트(줄 끝 4바이트 맞춤 그대로)."""
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return bytes(ptr)


def _dib(img: QImage) -> bytes:
    """CF_DIB — 24비트 BGR, 아래에서 위로. 투명은 흰 바탕에 합성(그림판·한글이 검게 보지 않게)."""
    import struct
    if img.hasAlphaChannel():
        from PyQt6.QtGui import QColor, QPainter
        base = QImage(img.size(), QImage.Format.Format_RGB32)
        base.fill(QColor("white"))
        p = QPainter(base)
        p.drawImage(0, 0, img)
        p.end()
        img = base
    im = img.convertToFormat(QImage.Format.Format_BGR888).mirrored(False, True)
    w, h, bpl = im.width(), im.height(), im.bytesPerLine()
    head = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, bpl * h, 3780, 3780, 0, 0)
    return head + _bits(im)


def _dibv5(img: QImage) -> bytes:
    """CF_DIBV5 — 32비트 BGRA(곱하지 않은 알파), BI_BITFIELDS, 아래에서 위로, sRGB."""
    import struct
    im = img.convertToFormat(QImage.Format.Format_ARGB32).mirrored(False, True)
    w, h = im.width(), im.height()
    head = struct.pack("<IiiHHIIiiIIIIIII36sIIIIIII", 124, w, h, 1, 32, 3, w * 4 * h, 3780, 3780, 0, 0,
                       0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000, 0x73524742, b"\0" * 36,
                       0, 0, 0, 4, 0, 0, 0)
    return head + _bits(im)


def _png(img: QImage) -> bytes:
    from PyQt6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def image_formats(img: QImage, png: bytes | None = None) -> list:
    """그림 하나를 올릴 Windows 형식 [(형식 번호, 바이트)…] — 스크린샷 SOT §8.4 표."""
    u = ctypes.windll.user32
    u.RegisterClipboardFormatW.restype = wintypes.UINT
    if img.hasAlphaChannel() or png:
        return [(u.RegisterClipboardFormatW("PNG"), png or _png(img)), (CF_DIBV5, _dibv5(img)), (CF_DIB, _dib(img))]
    return [(CF_DIB, _dib(img))]


def _write_win(formats) -> bool:
    """Win32 로 즉시 데이터 올리기 — 앱을 닫아도 남는다. 못 열면(다른 프로그램이 쥠) False."""
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u.SetClipboardData.restype = wintypes.HANDLE
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k.GlobalFree.argtypes = [wintypes.HGLOBAL]
    if not u.OpenClipboard(_owner_hwnd()):
        return False
    ok = True
    try:
        u.EmptyClipboard()
        for cf, data in formats:
            h = k.GlobalAlloc(0x0002, max(1, len(data)))           # GMEM_MOVEABLE
            if not h:
                ok = False
                continue
            p = k.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k.GlobalUnlock(h)
            if not u.SetClipboardData(cf, h):
                k.GlobalFree(h)
                ok = False
    finally:
        u.CloseClipboard()
    return ok


CF_UNICODETEXT, CF_HDROP = 13, 15


def _reg(name: str) -> int:
    u = ctypes.windll.user32
    u.RegisterClipboardFormatW.restype = wintypes.UINT
    u.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    return u.RegisterClipboardFormatW(name)


def _put(fmts_fn, qt_fill, on_done=None, tries=RETRY_TRIES, interval_ms=RETRY_MS):
    """261113-6(스크린샷 SOT §8.4): 넣기 한 길 — Windows 는 `fmts_fn()` 이 낸 [(형식, 바이트)] 를 Win32 **즉시 데이터**로,
    다른 플랫폼은 `qt_fill(QMimeData)` 로 Qt 에. 못 열면 타이머로 다시(§8.3). Qt 의 지연 렌더링은 앱이 바쁜 동안
    Win+V 기록 서비스가 클립보드를 쥔 채 기다려 다른 모든 프로그램을 막았다(실측 5.5초) — Windows 에서는 쓰지 않는다."""
    state = {"left": max(1, int(tries))}
    win = QGuiApplication.platformName() == "windows"
    fmts = []
    if win:
        try:
            fmts = fmts_fn()
        except Exception:
            win = False

    def attempt():
        state["left"] -= 1
        done = False
        try:
            if win:
                done = _write_win(fmts)
            else:
                from PyQt6.QtCore import QMimeData
                md = QMimeData()
                qt_fill(md)
                QApplication.clipboard().setMimeData(md)
                done = True                               # 다른 플랫폼은 프로그램 안 클립보드 — 곧바로 들어간다
        except Exception:
            pass
        if done:
            if on_done:
                on_done(True)
        elif state["left"] > 0:
            QTimer.singleShot(interval_ms, attempt)
        elif on_done:
            on_done(False)

    attempt()


def _extra_fmts(extra) -> list:
    return [(_reg(m), bytes(v)) for m, v in (extra or {}).items()]


def set_text(text: str, on_done=None, extra: dict | None = None):
    """글을 클립보드에 — Windows 는 `CF_UNICODETEXT` 즉시 데이터(`CF_TEXT` 는 Windows 가 만들어 준다). 261113-6."""
    text = str(text or "")

    def qt_fill(md):
        md.setText(text)
        for m, v in (extra or {}).items():
            md.setData(m, bytes(v))
    _put(lambda: [(CF_UNICODETEXT, text.encode("utf-16-le") + b"\0\0")] + _extra_fmts(extra), qt_fill, on_done)


def set_files(paths, on_done=None):
    """파일들을 클립보드에(탐색기·메일·메신저에 붙이면 첨부) — `CF_HDROP` + `Preferred DropEffect`=복사. 261113-6."""
    import os
    import struct
    paths = [os.path.abspath(str(p)) for p in paths]

    def fmts():
        body = "".join(p + "\0" for p in paths) + "\0"
        drop = struct.pack("<IiiII", 20, 0, 0, 0, 1) + body.encode("utf-16-le")       # DROPFILES(pFiles=20, fWide)
        return [(CF_HDROP, drop), (_reg("Preferred DropEffect"), struct.pack("<I", 1))]

    def qt_fill(md):
        from PyQt6.QtCore import QUrl
        md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    _put(fmts, qt_fill, on_done)


def set_data(extra: dict, on_done=None):
    """앱 안 전용 표식만(그림을 만들지 못했을 때) — 형식 이름 = MIME. 261113-6."""
    def qt_fill(md):
        for m, v in (extra or {}).items():
            md.setData(m, bytes(v))
    _put(lambda: _extra_fmts(extra), qt_fill, on_done)


def diag() -> str:
    """261113-6(스크린샷 SOT §8.3 의 5): '확인 못 함' 진단 한 줄 — 연 창의 프로세스·내용 주인·순번·지금 열기까지 걸린 시간.
    클립보드 내용은 바꾸지 않는다(열었다 닫기만). 검사 로그에만 찍는 개발용 진단이라 **영어로** 쓴다 — 화면 문구가 아니다(다국어 SOT §5 '감싸지 않는 것')."""
    if QGuiApplication.platformName() != "windows":
        return "not Windows"
    try:
        import os
        import time
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        u.GetOpenClipboardWindow.restype = wintypes.HWND
        u.GetClipboardOwner.restype = wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.OpenClipboard.argtypes = [wintypes.HWND]
        k.OpenProcess.restype = wintypes.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]

        def who(hwnd):
            if not hwnd:
                return None
            if hwnd == _owner["hwnd"]:
                return "this app"
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == os.getpid():
                return "this app (Qt window)"
            h = k.OpenProcess(0x1000, False, pid.value)
            if not h:
                return "pid %d (no access)" % pid.value
            try:
                buf = ctypes.create_unicode_buffer(520)
                n = wintypes.DWORD(520)
                ok = k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
                return "%s(pid %d)" % (os.path.basename(buf.value), pid.value) if ok else "pid %d" % pid.value
            finally:
                k.CloseHandle(h)
        opener = u.GetOpenClipboardWindow()
        seq0 = u.GetClipboardSequenceNumber()
        t0 = time.perf_counter()
        opened = False
        while time.perf_counter() - t0 < 1.0:
            if u.OpenClipboard(None):
                u.CloseClipboard()
                opened = True
                break
            time.sleep(0.01)
        wait = time.perf_counter() - t0
        return "opener %s · owner %s · seq %d->%d · open now %s" % (
            who(opener) or ("none" if opened and wait < 0.02 else "unknown (opened without a window)"),
            who(u.GetClipboardOwner()) or "none", seq0, u.GetClipboardSequenceNumber(),
            ("%.0fms" % (wait * 1000)) if opened else "blocked > 1s")
    except Exception as e:
        return "diag failed %r" % e


def set_image(img, on_done=None, tries=RETRY_TRIES, interval_ms=RETRY_MS, png: bytes | None = None,
              extra: dict | None = None):
    """그림(QImage·QPixmap)을 클립보드에 넣는다. 끝나면 `on_done(ok)`.

    첫 시도는 곧바로 한다 — 대개 여기서 끝나고 `on_done` 도 곧바로 불린다.
    261112-19(스크린샷 SOT §8.4): Windows 는 Win32 로 다른 프로그램이 받는 형식을 직접 — 불투명 `CF_DIB`, 투명이면 `"PNG"`
    (`png` 로 이미 만든 바이트를 넘길 수 있다)·`CF_DIBV5`·흰 바탕 `CF_DIB`. `extra` = {MIME: 바이트} 앱 안 표식(꾸밈·쪽)을 함께.
    ★ Qt 로 그림과 "PNG" 를 함께 올리면 Word·PowerPoint 붙여넣기가 실패한다(Qt 변환기가 PNG 요청을 가로챔)."""
    if isinstance(img, QPixmap):
        img = img.toImage()
    if img is None or not isinstance(img, QImage) or img.isNull():
        if on_done:
            on_done(False)
        return
    state = {"left": max(1, int(tries))}
    win = QGuiApplication.platformName() == "windows"
    fmts = []
    if win:
        try:
            u = ctypes.windll.user32
            u.RegisterClipboardFormatW.restype = wintypes.UINT
            fmts = image_formats(img, png)
            fmts += [(u.RegisterClipboardFormatW(m), bytes(v)) for m, v in (extra or {}).items()]
        except Exception:
            win = False

    def attempt():
        state["left"] -= 1
        done = False
        try:
            if win:
                done = _write_win(fmts)
            else:
                from PyQt6.QtCore import QMimeData
                md = QMimeData()
                md.setImageData(img)
                if png:                                   # 종전대로(Windows 가 아닌 길 — Office 결함은 Windows Qt 변환기에서만)
                    md.setData(PNG_MIME, png)
                    md.setData("image/png", png)
                for m, v in (extra or {}).items():
                    md.setData(m, bytes(v))
                QApplication.clipboard().setMimeData(md)
        except Exception:
            pass
        if done or (not win and _took()):
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
