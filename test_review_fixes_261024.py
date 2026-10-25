# -*- coding: utf-8 -*-
"""261024-5: SOT 전체 점검에서 나온 코드 결함 (마스터 §0 261024-5).

A. 파일 탭 '저장'(Ctrl+S) — 포커스가 있는 책갈피창을 저장한다(종전: 늘 위 창). Ctrl+R 과 같은 판정 `_focused_bm_tree`
B. 새 창으로 열기 실패 — PyQt6 `startDetached` 는 (성공, pid) 튜플이라 늘 참이었다 → 실패면 이 창에서 연다
C. 1단↔2단 '바꾸는 키' 는 지금 상태의 반대 항목에만 — 메뉴가 화면에 펼쳐지지 않으니 상태가 바뀔 때 맞춘다(디자인 SOT §2.9.2)
D. 가벼운 넘김 'slow' 는 한 번 켜지면 이 실행 동안 유지(응답성 SOT §4.7) — 켜진 뒤 빨라져도 꺼졌다 켜지지 않는다
E. 본문 ＋/－ 단추의 한 걸음 = `VIEW_SCALE_STEP`(값은 한 곳)
"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_FAKE_POWER_SAVING", "0")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_reviewfix261024_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


from viewer.app import MainWindow
from test_fixtures import text_pdf
mw = MainWindow(); mw._skip_save_on_close = True
mw.resize(1300, 850); mw.show(); spin(0.3)

# A — 저장은 포커스 책갈피창
saved = []
mw.bookmark_tree._op_save = lambda *a, **k: saved.append("top")
mw.bookmark_tree_right._op_save = lambda *a, **k: saved.append("bottom")
mw.bookmark_tree_right.show(); spin(0.1)
mw.bookmark_tree_right.tree.setFocus(); spin(0.1)
mw._sc_act_save.trigger(); spin(0.1)
chk(saved == ["bottom"], "A1 아래 책갈피창에 포커스가 있으면 Ctrl+S(파일 탭 '저장') 는 아래 창을 저장", str(saved))
saved.clear()
mw.bookmark_tree.tree.setFocus(); spin(0.1)
mw._sc_act_save.trigger(); spin(0.1)
chk(saved == ["top"], "A2 위 창에 포커스면 위 창", str(saved))

# B — 새 창 실패면 이 창에서 연다
from PyQt6.QtCore import QProcess
_orig_sd = QProcess.startDetached
opened = []
QProcess.startDetached = staticmethod(lambda *a, **k: (False, 0))
_orig_open = mw.open_pdf
mw.open_pdf = lambda p, *a, **k: opened.append(str(p))
mw._open_pdf_new_window(str(text_pdf()))
QProcess.startDetached = _orig_sd
mw.open_pdf = _orig_open
chk(len(opened) == 1, "B 새 창을 못 띄우면(False, 0) 이 창에서 연다", str(opened))

# C — 261025-1(입력 SOT §3.2.1, 사용자 결정): 보기 탭 키는 항목마다 하는 일이 하나 — 상태와 무관하게 늘 그 항목에
va = mw._view_acts
mw.act_split.setChecked(True); spin(0.3)
chk(va["single"].text().endswith("\tCtrl+Shift+1") and va["split"].text().endswith("\tCtrl+Shift+2"),
    "C1 2단이어도 1단·2단 항목에 각자 키", "%r / %r" % (va["single"].text(), va["split"].text()))
mw.act_split.setChecked(False); spin(0.3)
chk(va["single"].text().endswith("\tCtrl+Shift+1") and va["split"].text().endswith("\tCtrl+Shift+2"),
    "C2 1단으로 돌아가도 같다", "%r / %r" % (va["single"].text(), va["split"].text()))

# D — slow 는 한 번 켜지면 유지
from viewer import perf_mode
perf_mode._reset_for_test()
perf_mode.set_pref("auto")
os.environ["POLYPDF_FAKE_POWER_SAVING"] = "0"
perf_mode._power.update(t=-1e9)
for _ in range(perf_mode.SLOW_WINDOW):
    perf_mode._flips.append(perf_mode.SLOW_FLIP_MS + 50)
chk(perf_mode.reason() == "slow", "D1 느리면 켜진다")
for _ in range(perf_mode.SLOW_WINDOW):
    perf_mode._flips.append(10)
del perf_mode._flips[:-perf_mode.SLOW_WINDOW]
chk(perf_mode.reason() == "slow", "D2 켜진 뒤 넘김이 빨라져도 이 실행 동안 유지(깜빡이지 않는다)", perf_mode.reason())
perf_mode.set_pref("off")
chk(perf_mode.reason() == "", "D3 설정 '끄기' 는 그래도 끈다")
perf_mode._reset_for_test()

# E — ＋/－ 한 걸음
from viewer.view_scale import VIEW_SCALE_STEP
mv = mw.main_view
mw.open_pdf(text_pdf()); spin(1.0)
z0 = mv._zoom
mv.btn_zoom_in.click(); spin(0.2)
chk(abs(mv._zoom / z0 - VIEW_SCALE_STEP) < 1e-6, "E 본문 ＋ 한 번 = VIEW_SCALE_STEP 배", "%.4f" % (mv._zoom / z0))

print("\n=== %s ===" % ("ALL PASS" if not fails else "FAIL %d" % len(fails)))
sys.stdout.flush()
os._exit(1 if fails else 0)
