# -*- coding: utf-8 -*-
"""가벼운 넘김 — 느린 컴퓨터(절전 모드) 대응 (응답성 SOT §4.7, 261021-1 사용자 지시).

사용자 보고: 다른 노트북이 Windows 전원 모드 '최고의 전력 효율' 일 때 2장 맞춤 보기에서 쪽이
잘 안 넘어가고 중간에 멈췄다. 실측(이 기계, 같은 모드): 넘김 한 번에 메인 70~210ms, 그 위에
텍스트 창 추출(표 인식)이 **GIL 을 쥔 채** 같은 때 돌아 넘김 애니메이션이 끊겼다. 쪽 그리기
자체는 쪽당 4~14ms 로 싸다 — 무거운 것은 넘길 때마다 **곁따라 도는 일**이다.

그래서 '가벼운 넘김' 이 켜지면 뷰어·앱이 이렇게 한다(규칙은 응답성 SOT §4.7 이 소유).
  ① 넘김 애니메이션을 하지 않는다  ② 빠르게 잇달아 넘기면 가운데 쪽은 그리지 않는다
  ③ 텍스트 창·단어장은 넘김이 멈춘 뒤에 따라간다  ④ 멈춰 있을 때 다음 쪽을 미리 그려 둔다

켜는 조건 — 설정 `lite_flip`(`auto` 기본 / `on` / `off`):
  - `auto`: Windows 가 절전(전원 모드 '최고의 전력 효율' 또는 배터리 절약)이거나,
    **실제 넘김**이 느리면(최근 `SLOW_WINDOW` 번의 가운데 값 ≥ `SLOW_FLIP_MS`) 켠다.
  - 시험 프로필(`QStandardPaths` 테스트 모드)에서는 자동 판정을 하지 않는다 — 기계의 전원
    상태로 검사 결과가 바뀌면 안 된다. 가짜로 켜려면 `POLYPDF_FAKE_POWER_SAVING=1`.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

# Windows 전원 모드 오버레이 — '최고의 전력 효율'(Win11) / '배터리 수명 향상'(Win10)
OVERLAY_BEST_EFFICIENCY = uuid.UUID("961cc777-2547-4f9d-8174-7d86181b8a7a")
SLOW_FLIP_MS = 150          # 넘김 한 번(메인)의 가운데 값이 이 이상이면 느린 기계로 본다
SLOW_WINDOW = 5             # 가운데 값을 낼 최근 넘김 수
POWER_RECHECK_S = 30.0      # 전원 상태는 이 간격으로만 다시 묻는다(값싼 호출이지만 넘길 때마다 묻지 않는다)

_pref = ""                  # 앱이 `set_pref` 로 넣기 전에는 꺼짐 — 홀로 쓰는 MainView(검사·다른 창)는 늘 종전대로
_flips: list = []
_slow_latched = False       # 실측으로 한 번 느리면 이 실행 동안 켜 둔다(measured_slow)
_power = {"t": -1e9, "state": ""}
_engaged_cb = None
_announced = False


def set_pref(value) -> None:
    global _pref
    v = str(value or "auto")
    _pref = v if v in ("auto", "on", "off") else "auto"


def pref() -> str:
    """`''` 이면 앱이 아직 맡지 않았다(꺼짐)."""
    return _pref


def on_engaged(cb) -> None:
    """처음 켜질 때 한 번 부를 함수(앱이 상태 표시줄에 알린다). 인자는 `reason()`."""
    global _engaged_cb
    _engaged_cb = cb


def _test_mode() -> bool:
    """시험 프로필인가 — PyQt6 에는 `isTestModeEnabled` 가 없어, 테스트 모드의 설정 폴더(`…/qttest`)로 안다."""
    try:
        from PyQt6.QtCore import QStandardPaths
        loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)
        return os.path.basename(os.path.normpath(loc)).lower() == "qttest"
    except Exception:
        return False


def _query_power() -> str:
    """`'efficiency'`(전원 모드 최고의 전력 효율) / `'saver'`(배터리 절약) / `''`."""
    fake = os.environ.get("POLYPDF_FAKE_POWER_SAVING")
    if fake is not None:
        return "efficiency" if fake == "1" else ""
    if sys.platform != "win32" or _test_mode():
        return ""
    import ctypes
    try:
        class _SPS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                        ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
        s = _SPS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)) and (s.SystemStatusFlag & 1):
            return "saver"
    except Exception:
        pass
    try:
        g = (ctypes.c_ubyte * 16)()
        fn = ctypes.WinDLL("powrprof").PowerGetEffectiveOverlayScheme   # Win10 1709+
        if fn(ctypes.byref(g)) == 0 and uuid.UUID(bytes_le=bytes(g)) == OVERLAY_BEST_EFFICIENCY:
            return "efficiency"
    except Exception:
        pass
    return ""


def power_state() -> str:
    now = time.monotonic()
    if now - _power["t"] >= POWER_RECHECK_S:
        _power["t"] = now
        _power["state"] = _query_power()
    return _power["state"]


def note_flip(ms: float) -> None:
    """뷰어가 한 쪽 넘김(메인 스레드)에 걸린 시간을 알린다."""
    if _test_mode() and os.environ.get("POLYPDF_FAKE_POWER_SAVING") is None:
        return
    _flips.append(float(ms))
    del _flips[:-SLOW_WINDOW]
    is_lite()                                  # 막 느려졌으면 여기서 알린다


def measured_slow() -> bool:
    """한 번 느리다고 재면 **이 실행 동안 유지**한다(261024-5, 응답성 SOT §4.7) — 켜지면 텍스트 창이 미뤄져 넘김이 빨라지고,
    최근 값만 보면 다시 꺼졌다가 또 켜지는 왕복(상태 표시줄 깜빡임)이 생긴다."""
    global _slow_latched
    if _slow_latched:
        return True
    if len(_flips) < SLOW_WINDOW:
        return False
    _slow_latched = sorted(_flips)[len(_flips) // 2] >= SLOW_FLIP_MS
    return _slow_latched


def reason() -> str:
    """켜진 까닭 — `'on'`(설정) / `'efficiency'` / `'saver'` / `'slow'` / `''`(꺼짐)."""
    if _pref in ("", "off"):
        return ""
    if _pref == "on":
        return "on"
    p = power_state()
    if p:
        return p
    return "slow" if measured_slow() else ""


def is_lite() -> bool:
    global _announced
    r = reason()
    if r and not _announced:
        _announced = True
        cb = _engaged_cb
        if cb is not None:
            try:
                cb(r)
            except Exception:
                pass
    return bool(r)


def _reset_for_test() -> None:
    global _pref, _announced, _engaged_cb, _slow_latched
    _pref, _announced, _engaged_cb, _slow_latched = "", False, None, False
    _flips.clear()
    _power.update(t=-1e9, state="")
