"""260611-3(6): Windows 전역 단축키(RegisterHotKey) — 화면 캡처용.

Qt 의 네이티브 이벤트 필터로 WM_HOTKEY 를 받아 콜백을 호출한다.
의존성 없이 ctypes(user32)만 사용. 등록 실패해도 앱은 정상 동작(전역만 비활성).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
# 260611-11: 64비트에서 HWND(포인터) 가 잘리지 않도록 시그니처 명시(등록 실패 방지)
if _user32 is not None:
    try:
        _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                           wintypes.UINT, wintypes.UINT]
        _user32.RegisterHotKey.restype = wintypes.BOOL
        _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        _user32.UnregisterHotKey.restype = wintypes.BOOL
    except Exception:
        pass

# 특수키 이름 → 가상키코드(VK)
_VK_NAMES = {
    "ESC": 0x1B, "ESCAPE": 0x1B, "SPACE": 0x20, "TAB": 0x09,
    "RETURN": 0x0D, "ENTER": 0x0D, "BACKSPACE": 0x08, "DELETE": 0x2E, "DEL": 0x2E,
    "INSERT": 0x2D, "INS": 0x2D, "HOME": 0x24, "END": 0x23,
    "PGUP": 0x21, "PAGEUP": 0x21, "PGDOWN": 0x22, "PAGEDOWN": 0x22,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "`": 0xC0, "~": 0xC0,
}


def parse_sequence(seq_str: str):
    """'Ctrl+Shift+S' → (mods, vk). 파싱 불가면 None."""
    if not seq_str:
        return None
    # 'Ctrl+Shift+S' 처럼 '+' 구분. 키 자체가 '+' 인 경우는 드물어 무시.
    raw = [p for p in seq_str.split("+")]
    parts = [p.strip() for p in raw if p.strip()]
    if not parts:
        return None
    mods = 0
    key = None
    for p in parts:
        up = p.upper()
        if up in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif up == "SHIFT":
            mods |= MOD_SHIFT
        elif up == "ALT":
            mods |= MOD_ALT
        elif up in ("META", "WIN"):
            mods |= MOD_WIN
        else:
            key = p
    if not key:
        return None
    up = key.upper()
    vk = None
    if len(up) == 1 and ("A" <= up <= "Z"):
        vk = ord(up)
    elif len(up) == 1 and ("0" <= up <= "9"):
        vk = ord(up)
    elif up.startswith("F") and up[1:].isdigit():
        n = int(up[1:])
        if 1 <= n <= 24:
            vk = 0x70 + (n - 1)
    elif up in _VK_NAMES:
        vk = _VK_NAMES[up]
    if vk is None:
        return None
    return (mods | MOD_NOREPEAT, vk)


class GlobalHotkey(QAbstractNativeEventFilter):
    """단일 전역 핫키를 등록·관리. install() 로 앱 이벤트 필터에 연결."""

    def __init__(self, hwnd: int, hotkey_id: int, callback):
        super().__init__()
        self._hwnd = int(hwnd)
        self._id = int(hotkey_id)
        self._cb = callback
        self._registered = False

    def register(self, seq_str: str) -> bool:
        self.unregister()
        if _user32 is None:
            return False
        parsed = parse_sequence(seq_str)
        if not parsed:
            return False
        mods, vk = parsed
        try:
            ok = bool(_user32.RegisterHotKey(self._hwnd, self._id, mods, vk))
        except Exception:
            ok = False
        self._registered = ok
        return ok

    def unregister(self):
        if self._registered and _user32 is not None:
            try:
                _user32.UnregisterHotKey(self._hwnd, self._id)
            except Exception:
                pass
        self._registered = False

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG" and self._registered:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and int(msg.wParam) == self._id:
                    self._cb()
                    # 260611-13: 처리한 WM_HOTKEY 는 소비(True) → 중복 디스패치로 2번 호출 방지
                    return True, 0
        except Exception:
            pass
        return False, 0
