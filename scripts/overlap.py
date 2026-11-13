# -*- coding: utf-8 -*-
"""측정이 다른 무거운 작업과 겹쳤는지 — 릴리스 SOT §4.3 의 8 (261025-12).

261025: 빌드 시험(build_1.0.0_261025-1607)이 다른 세션의 검사·점검과 함께 돌아 '회귀 의심' 6건(창 +32~48%·색인 파일 -29~41%)이
나왔고, 통과였으므로 그 결과가 **기준점(baseline.json)이 되었다** — 다음 시험이 흔들린 값과 견주게 된다.
그래서 측정 도구(release_test.py build/install · load_test.py · soak_test.py)는 시작부터 끝까지 이 감시를 두고,
겹쳤으면 판정을 '보류' 로 적고 기준점을 옮기지 않는다.

- **판정은 다른 무거운 프로세스로만**: 이름이 `HEAVY` 인 것 중 이 측정의 프로세스 나무(자신·조상·자손 — 잰 앱과 그 도우미) 밖의 것.
  지난 점검 뒤 쓴 CPU 시간이 경과 시간의 `OVERLAP_CORES` 배를 넘으면 겹침. 측정을 실제로 흔드는 것은 다른 검사·빌드·측정이다.
- **시스템 CPU 는 적기만 한다**(261025-12 보완): 측정 시작 전 1초의 사용률. 종전에는 `CPU_BUSY_PCT`(40%)를 넘으면 겹침으로 봤는데,
  이 PC 의 **평소 부하가 37% 안팎**(Claude 앱 여러 세션·메신저 등)이라 다른 시험이 없는데도 설치 시험 2120·2201 이 '보류' 됐다
  (시작 전 46%·47%, 대상마다 본 다른 무거운 프로세스는 0). 평소 부하는 PC 마다 다르고 측정 내내 비슷해 견줄 때 상쇄된다.
  백신(MsMpEng)이 설치 직후 새 파일을 읽는 것도 환경이다(릴리스 SOT §4.3 의 6) — `HEAVY` 에 넣지 않는다.
"""
import ctypes
import ctypes.wintypes as wt
import os
import time

HEAVY = {"python.exe", "pythonw.exe", "polypdf.exe", "pyinstaller.exe", "iscc.exe", "tesseract.exe", "py-spy.exe"}
OVERLAP_CORES = 0.3        # 다른 무거운 프로세스들이 점검 사이에 평균 이만큼(코어 수) 넘게 쓰면 겹침 — 판정 기준은 이것 하나

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


# 261113-5(릴리스 SOT §4.3 의 4): 전원 상태 — beta.12 부하 시험 회전 1.1~1.3초 실패가 배터리 동작 탓이었다(261113-1, beta.11 코드도 같은 값).
#   전원 모드는 Windows 의 오버레이 GUID(설정 > 전원 > 전원 모드).
POWER_MODES = {"961cc777-2547-4f9d-8174-7d86181b8a7a": "best_eff", "3af9b8d9-7c97-431d-ad78-34a8bfea439f": "better_batt",
               "00000000-0000-0000-0000-000000000000": "balanced", "ded574b5-45a0-4f42-8737-46345c09c238": "best_perf"}
POWER_NAMES = {"best_eff": "최고의 전력 효율", "better_batt": "배터리 절약", "balanced": "균형", "best_perf": "최고 성능", "?": "모름"}


class _SPS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", wt.DWORD), ("BatteryFullLifeTime", wt.DWORD)]


def power_raw() -> tuple:
    """(충전기 연결 여부 — 모르면 True, 배터리 % — 없으면 -1, 전원 모드 키)."""
    ac, pct, mode = True, -1, "?"
    try:
        s = _SPS()
        if k32.GetSystemPowerStatus(ctypes.byref(s)):
            ac = s.ACLineStatus != 0                 # 0 배터리, 1 충전기, 255 모름
            pct = -1 if s.BatteryLifePercent == 255 or s.BatteryFlag & 128 else s.BatteryLifePercent
    except Exception:                                # noqa: BLE001 — 적기만 한다
        pass
    try:
        import uuid
        g = (ctypes.c_byte * 16)()
        if ctypes.WinDLL("powrprof").PowerGetEffectiveOverlayScheme(ctypes.byref(g)) == 0:
            mode = POWER_MODES.get(str(uuid.UUID(bytes_le=bytes(g))), "?")
    except Exception:                                # noqa: BLE001 — 옛 Windows·함수 없음
        pass
    return ac, pct, mode


def keep_awake() -> bool:
    """261113-7(릴리스 SOT §4.3 의 4): 재는 동안 PC 가 절전에 들지 않게 — 이 프로세스가 사는 동안만(끝나면 Windows 가 푼다).
    beta.12 설치 확인 '닫기 5529.9초'(10:38 절전 → 12:10 깨어남)·전체 검사 test_auto_tag 944초(09:01 → 09:16)가 절전에 걸친 값이었다."""
    try:
        k32.SetThreadExecutionState.restype = wt.DWORD
        k32.SetThreadExecutionState.argtypes = [wt.DWORD]
        return bool(k32.SetThreadExecutionState(0x80000000 | 0x00000001))     # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception:                                # noqa: BLE001
        return False


def power_text(ac: bool, pct: int, mode: str) -> str:
    """summary 줄 — 배터리이거나 절전 쪽 전원 모드면 경고(판정은 그대로)."""
    src = "충전기" if ac else ("**배터리**%s" % (" %d%%" % pct if pct >= 0 else ""))
    line = "- 전원: %s · 전원 모드 %s" % (src, POWER_NAMES.get(mode, mode))
    if not ac or mode in ("best_eff", "better_batt"):
        line += " — **⚠ 배터리·절전 상태라 느리게 잴 수 있다(판정은 그대로) — 충전기를 꽂고 전원 모드를 올린 뒤 다시 잰다**(릴리스 SOT §4.3 의 4)"
    return line


class Watch:
    """측정 동안 다른 무거운 작업을 지켜본다 — `start()` 를 측정 전에, `check(이름)` 을 구간마다(대상 사이·표본마다), `lines()` 를 요약에."""

    def __init__(self, root: int = None):
        self.root = root or os.getpid()
        self.events = []          # (구간 이름, 설명)
        self.start_busy = None
        self.power = ""           # 시작 때 전원 줄(261113-5)
        self._last = None

    def _others(self, exclude=()) -> dict:
        ps = procs()
        mine = _tree(ps, self.root)
        # 261108-20 덧붙임 2: 잰 앱과 그 모든 대 자손은 '다른' 것이 아니다 — 잰 앱이 닫혀 목록에서 사라지면 root 에서 내려가는
        #   나무가 끊겨, 아직 목록에 남은 색인 자식(끝났지만 핸들이 남은 것 포함)을 남으로 셌다(beta.6·beta.8 T5 겹침 'PolyPDF.exe←앱 pid')
        ex = set(exclude)
        if ex:
            grew = True
            while grew:
                grew = False
                for pid, pp, _n in ps:
                    if pp in ex and pid not in ex:
                        ex.add(pid)
                        grew = True
            mine |= ex
        # 261108-20: 이름에 부모 pid 를 붙인다 — 잰 앱의 자식이 부모가 끝난 뒤 남은 것인지(부모 pid 가 잰 앱) 사용자의 다른 창인지 가린다
        return {pid: ("%s←%d" % (name, pp), _cpu_s(pid)) for pid, pp, name in ps if name.lower() in HEAVY and pid not in mine}

    def start(self) -> "Watch":
        self.start_busy = system_busy_pct()          # 적기만 한다 — 평소 부하는 PC 마다 다르다(위 설명)
        self.power = power_text(*power_raw())
        keep_awake()                                  # 261113-7: 재는 동안 절전 막기
        self._last = (time.time(), self._others())
        return self

    def check(self, label: str, exclude=()) -> bool:
        """지난 점검 뒤 다른 무거운 프로세스가 쓴 CPU — 넘으면 events 에 적고 True.
        `exclude`: 이 구간에 잰 앱 pid 와 그 자손 pid(측정 도구가 본 것) — 그 아래 자손까지 뺀다."""
        if self._last is None:
            self.start()
        t0, o0 = self._last
        now, o1 = time.time(), (self._others(exclude) if exclude else self._others())
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
        head = "- 겹침 감시(릴리스 SOT §4.3 의 8): 시작 전 시스템 CPU %s%%(참고 — 판정은 다른 무거운 프로세스로만)" % (
            self.start_busy if self.start_busy is not None else "?")
        pw = [self.power] if self.power else []
        if not self.events:
            return [head + " · 다른 무거운 작업 없음"] + pw
        return [head + " · **겹침 %d번 — 판정 보류, 기준점을 옮기지 않는다**" % len(self.events)] + \
               ["  - %s: %s" % e for e in self.events] + pw


if __name__ == "__main__":        # 지금 겹칠 것이 있는지 한 번 보기: python scripts/overlap.py
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    w = Watch().start()
    time.sleep(3)
    w.check("지금")
    print("\n".join(w.lines()))
