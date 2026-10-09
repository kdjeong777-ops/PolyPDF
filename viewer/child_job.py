# -*- coding: utf-8 -*-
"""261009-19: 자식 프로세스(색인·띄어쓰기 도우미)를 **부모와 함께 끝나게** 묶는다 (응답성 SOT §4 ③).

자식은 부모 쪽 파이프가 닫히면 스스로 끝나지만, 큰 PDF 를 색인하는 동안처럼 C 호출 안에 있으면 그것을 알아챌 수 없다 —
설치본 시험에서 창을 닫은 뒤에도 색인 자식이 남아 `index.db` 를 쥐었다(release_test T5 '도우미 남음 1').
Windows Job Object 에 `KILL_ON_JOB_CLOSE` 를 걸고 자식을 넣으면, 부모가 어떻게 끝나든(`os._exit`·강제 종료 포함)
**OS 가 job 핸들을 닫으며 자식을 끝낸다.** 넣지 못하면(다른 OS·권한) False — 종전대로 파이프 끊김에 기댄다.
"""
from __future__ import annotations

import ctypes
import sys

_JOB = None


class _BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]


class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]


class _EXT(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BASIC), ("IoInfo", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


_KILL_ON_JOB_CLOSE = 0x2000
_EXTENDED_LIMIT_INFO = 9


def attach(proc) -> bool:
    """`subprocess.Popen` 자식을 이 프로세스의 job 에 넣는다 — 이 프로세스가 끝나면 자식도 끝난다."""
    global _JOB
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes as wt
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wt.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        if _JOB is None:
            h = k32.CreateJobObjectW(None, None)
            if not h:
                return False
            info = _EXT()
            info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(h, _EXTENDED_LIMIT_INFO, ctypes.byref(info), ctypes.sizeof(info)):
                return False
            _JOB = h                     # 프로세스가 끝날 때까지 쥔다 — 닫히는 순간 자식이 끝난다
        return bool(k32.AssignProcessToJobObject(_JOB, int(proc._handle)))
    except Exception:
        return False
