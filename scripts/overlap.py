# -*- coding: utf-8 -*-
"""측정이 다른 무거운 작업과 겹쳤는지 — 릴리스 SOT §4.3 의 8 (261025-12).

261025: 빌드 시험(build_1.0.0_261025-1607)이 다른 세션의 검사·점검과 함께 돌아 '회귀 의심' 6건(창 +32~48%·색인 파일 -29~41%)이
나왔고, 통과였으므로 그 결과가 **기준점(baseline.json)이 되었다** — 다음 시험이 흔들린 값과 견주게 된다.
그래서 측정 도구(release_test.py build/install · load_test.py · soak_test.py)는 시작부터 끝까지 이 감시를 두고,
겹쳤으면 판정을 '보류' 로 적고 기준점을 옮기지 않는다.

- **다른 무거운 프로세스**: 이름이 `HEAVY` 인 것 중 이 측정의 프로세스 나무(자신·조상·자손 — 잰 앱과 그 도우미) 밖의 것.
  지난 점검 뒤 쓴 CPU 시간이 경과 시간의 `OVERLAP_CORES` 배를 넘으면 겹침.
- **시스템 CPU**: 측정 **시작 전** 1초 동안 `CPU_BUSY_PCT` 를 넘으면 겹침(시작 뒤에는 잰 앱이 쓰므로 견주지 않는다).
"""
import ctypes
import ctypes.wintypes as wt
import os
import time

HEAVY = {"python.exe", "pythonw.exe", "polypdf.exe", "pyinstaller.exe", "iscc.exe", "tesseract.exe", "py-spy.exe"}
OVERLAP_CORES = 0.3        # 다른 무거운 프로세스들이 점검 사이에 평균 이만큼(코어 수) 넘게 쓰면 겹침
CPU_BUSY_PCT = 40          # 시작 전 시스템 CPU 사용률(%) — 넘으면 겹침

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.c_void_p]
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
k32.GetSystemTimes.argtypes = [ctypes.POINTER(wt.FILETIME)] * 3


class _PE(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def _ft(f) -> float:
    return ((f.dwHighDateTime << 32) | f.dwLowDateTime) / 1e7


def procs() -> list:
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    out = []
    e = _PE()
    e.dwSize = ctypes.sizeof(e)
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def _cpu_s(pid: int) -> float:
    h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return 0.0
    try:
        c, x, kt, ut = wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME()
        if k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(x), ctypes.byref(kt), ctypes.byref(ut)):
            return _ft(kt) + _ft(ut)
        return 0.0
    finally:
        k32.CloseHandle(h)


def _tree(ps: list, root: int) -> set:
    """root 의 조상(이 측정을 띄운 셸·런처)과 자손(잰 앱·도우미)."""
    parent = {p[0]: p[1] for p in ps}
    kids = {root}                                     # 자손은 root 에서만 — 조상의 자손(같은 셸이 띄운 다른 작업)은 남이다
    grew = True
    while grew:
        grew = False
        for pid, ppid, _n in ps:
            if ppid in kids and pid not in kids and ppid != 0:
                kids.add(pid)
                grew = True
    mine = set(kids)
    p = root
    for _ in range(32):
        p = parent.get(p)
        if not p or p in mine:
            break
        mine.add(p)
    return mine


def system_busy_pct(sec: float = 1.0) -> float:
    a = [wt.FILETIME() for _ in range(3)]
    b = [wt.FILETIME() for _ in range(3)]
    k32.GetSystemTimes(*[ctypes.byref(x) for x in a])
    time.sleep(sec)
    k32.GetSystemTimes(*[ctypes.byref(x) for x in b])
    idle = _ft(b[0]) - _ft(a[0])
    total = (_ft(b[1]) - _ft(a[1])) + (_ft(b[2]) - _ft(a[2]))       # 커널(유휴 포함) + 사용자
    return round(100.0 * (1 - idle / total), 1) if total > 0 else 0.0


class Watch:
    """측정 동안 다른 무거운 작업을 지켜본다 — `start()` 를 측정 전에, `check(이름)` 을 구간마다(대상 사이·표본마다), `lines()` 를 요약에."""

    def __init__(self, root: int = None):
        self.root = root or os.getpid()
        self.events = []          # (구간 이름, 설명)
        self.start_busy = None
        self._last = None

    def _others(self) -> dict:
        ps = procs()
        mine = _tree(ps, self.root)
        return {pid: (name, _cpu_s(pid)) for pid, _pp, name in ps if name.lower() in HEAVY and pid not in mine}

    def start(self) -> "Watch":
        self.start_busy = system_busy_pct()
        o = self._others()
        if self.start_busy > CPU_BUSY_PCT:
            self.events.append(("시작 전", "시스템 CPU %.0f%% (한도 %d%%)" % (self.start_busy, CPU_BUSY_PCT)))
        self._last = (time.time(), o)
        return self

    def check(self, label: str) -> bool:
        """지난 점검 뒤 다른 무거운 프로세스가 쓴 CPU — 넘으면 events 에 적고 True."""
        if self._last is None:
            self.start()
        t0, o0 = self._last
        now, o1 = time.time(), self._others()
        dt = max(1e-3, now - t0)
        busy = []
        for pid, (name, cpu) in o1.items():
            used = cpu - (o0.get(pid, (name, cpu if pid in o0 else 0.0))[1])
            if pid not in o0:
                used = cpu                                # 구간 중에 새로 뜬 것 — 쓴 CPU 전부
            if used / dt >= 0.05:
                busy.append((name, pid, used / dt))
        load = sum(x[2] for x in busy)
        self._last = (now, o1)
        if load > OVERLAP_CORES:
            self.events.append((label, "다른 무거운 프로세스 %.2f코어 — %s" % (
                load, ", ".join("%s(%d) %.2f" % b for b in sorted(busy, key=lambda b: -b[2])[:5]))))
            return True
        return False

    @property
    def overlapped(self) -> bool:
        return bool(self.events)

    def lines(self) -> list:
        head = "- 겹침 감시(릴리스 SOT §4.3 의 8): 시작 전 시스템 CPU %s%%" % (self.start_busy if self.start_busy is not None else "?")
        if not self.events:
            return [head + " · 다른 무거운 작업 없음"]
        return [head + " · **겹침 %d번 — 판정 보류, 기준점을 옮기지 않는다**" % len(self.events)] + \
               ["  - %s: %s" % e for e in self.events]


if __name__ == "__main__":        # 지금 겹칠 것이 있는지 한 번 보기: python scripts/overlap.py
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    w = Watch().start()
    time.sleep(3)
    w.check("지금")
    print("\n".join(w.lines()))
