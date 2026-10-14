# -*- coding: utf-8 -*-
"""261014-26: 시작 때 불러오는 모듈 줄이기 (마스터 §5 시작 import, 개선 로드맵 P3-8).

깨끗한 파이썬(자식 프로세스)에서 실제 `MainWindow` 를 만들고 띄운 뒤:
A. 시작에 쓰지 않는 무거운 모듈이 실리지 않았다 — `send2trash`(휴지통, 약 0.12초)·`urllib.request`(업데이트·구성요소, 약 0.05초)·
   `win32com`(성우 목록 — SAPI COM, 약 0.03초 + COM 생성)
B. 성우 목록은 메뉴를 처음 열 때 채운다 — 본문 '재생구간' 메뉴(두 창)·단어장 '성우' 메뉴
C. 휴지통 보내기는 쓸 때 싣는다(`_trash_fn`)
"""
import os, sys, subprocess, json
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


CHILD = r'''
import os, sys, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, HERE)
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from viewer.app import MainWindow
mw = MainWindow(); mw.show()
for _ in range(20):
    app.processEvents()
heavy = [m for m in ("send2trash", "urllib.request", "win32com", "win32com.client") if m in sys.modules]
calls = []

class FakeTts:
    def voice_names(self):
        calls.append(1)
        return ["Fake Voice A", "Fake Voice B"]
mw._study_get_tts = lambda: FakeTts()
names = []
for btn, menu_btn in mw._read_btns:
    m = menu_btn.menu()
    m.aboutToShow.emit()
    names.append(sorted(a.text() for sub in m.actions() if sub.menu() for a in sub.menu().actions()))
mw.study_panel._voice_menu.aboutToShow.emit()
mw.study_panel._voice_menu.aboutToShow.emit()          # 두 번 열어도 한 번만 채운다
study = [a.text() for a in mw.study_panel._voice_menu.actions()]
from viewer.widgets import bookmark_tree
fn = bookmark_tree._trash_fn()
print("RESULT " + json.dumps({"heavy": heavy, "names": names, "study": study, "calls": len(calls),
                               "trash": bool(fn), "trash_loaded": "send2trash" in sys.modules}, ensure_ascii=False))
sys.stdout.flush()
os._exit(0)
'''.replace("HERE", repr(HERE))

r = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=HERE,
                   timeout=300, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
chk(line is not None, "준비 — 자식에서 창을 띄웠다", (r.stdout + r.stderr)[-1500:])
if line:
    res = json.loads(line[7:])
    chk(res["heavy"] == [], "A 시작 때 send2trash·urllib.request·win32com 을 싣지 않는다", str(res["heavy"]))
    chk(len(res["names"]) == 2 and all("Fake Voice A" in n for n in res["names"]),
        "B 본문 재생구간 메뉴(두 창)는 처음 열 때 성우를 채운다", str(res["names"]))
    chk(res["study"].count("Fake Voice A") == 1, "B 단어장 성우 메뉴도 처음 열 때 한 번만 채운다", str(res["study"]))
    chk(res["trash"] and res["trash_loaded"], "C 휴지통 보내기는 쓸 때 싣는다", str(res))

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
