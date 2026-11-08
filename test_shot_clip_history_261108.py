# -*- coding: utf-8 -*-
"""261108-19(스크린샷 SOT §8.1): Win+V 기록 지우기는 PowerShell 자식 프로세스 없이 WinRT `Clipboard` 를 이 프로세스에서.

A. 기록 지우기 일꾼이 프로세스를 띄우지 않고 `clear_history` 를 부른다(종전 `powershell -Command` — 백신이 의심하는 모양·1.5~2.2초)
B. vtable 자리 확인 — `history_enabled()`(IsHistoryEnabled)가 레지스트리 `EnableClipboardHistory` 와 같다(읽기만, 실제 기록은 지우지 않는다)
C. 기록이 꺼져 있으면 ClearHistory 를 부르지 않는다
"""
import os, sys, subprocess, winreg
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from viewer import clipboard_util as CU

print("=== A. 프로세스 없이 ===")
spawned, cleared = [], []
_run, _popen = subprocess.run, subprocess.Popen
subprocess.run = lambda *a, **k: (spawned.append(a), None)[1]
subprocess.Popen = lambda *a, **k: (spawned.append(a), None)[1]
_clear = getattr(CU, "clear_history", None)
CU.clear_history = lambda: (cleared.append(1), True)[1]
try:
    w = CU.ClipHistoryClearWorker()
    done = []
    w.finished.connect(lambda: done.append(1))
    w.run()
finally:
    subprocess.run, subprocess.Popen = _run, _popen
    if _clear is not None:
        CU.clear_history = _clear
chk(not spawned and cleared == [1] and done == [1], "A 기록 지우기는 자식 프로세스(PowerShell) 없이 clear_history 를 부른다", str(spawned)[:200])

print("\n=== B. vtable 자리(읽기만) ===")


def _reg():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Clipboard") as k:
            return bool(winreg.QueryValueEx(k, "EnableClipboardHistory")[0])
    except OSError:
        return None


want = _reg()
got = CU.history_enabled() if hasattr(CU, "history_enabled") else "없음"
if want is None:
    chk(got in (None, False), "B 레지스트리 값이 없으면(기록 꺼짐) 켜짐이라 하지 않는다", str(got))
else:
    chk(got == want, "B IsHistoryEnabled(vtable %s) 가 레지스트리 EnableClipboardHistory 와 같다" % getattr(CU, "_VT_IS_HISTORY_ENABLED", "?"),
        "WinRT %s · 레지스트리 %s" % (got, want))

print("\n=== C. 꺼져 있으면 지우지 않는다 ===")
calls = []
if hasattr(CU, "clear_history"):
    _he, _call = CU.history_enabled, CU._clip_statics_call
    CU.history_enabled = lambda: False
    CU._clip_statics_call = lambda idx: (calls.append(idx), (0, True))[1]
    try:
        r = CU.clear_history()
    finally:
        CU.history_enabled, CU._clip_statics_call = _he, _call
    chk(r is False and not calls, "C 기록이 꺼져 있으면 ClearHistory 를 부르지 않는다", str(calls))
else:
    chk(False, "C clear_history 가 있다")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for f in fails:
    print(" -", f)
sys.stdout.flush()
os._exit(1 if fails else 0)
