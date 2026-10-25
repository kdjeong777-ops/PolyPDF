# -*- coding: utf-8 -*-
"""261021-3: 발표 띠 맨 오른쪽 화면 단추 (발표 SOT §6.1). 261024-3: 글은 **누르면 갈 곳** — 화면2로 / 본화면으로.

A. 단추는 띠 첫 줄 **맨 오른쪽**(✕ 오른쪽), 모니터가 하나면 숨긴다(261025-3)
B. 모니터 둘(가짜) — 누르면 다른 모니터로 옮기고 '🖥 본화면으로', 설정 `presentation_other_screen` 참
C. 다시 누르면 본화면으로, 설정 거짓
D. 기억한 값(참)으로 다음 발표는 다른 화면에서 연다
E. 우클릭 '화면 ▸ 모니터 1'(본화면)을 고르면 단추·설정도 거짓으로 같이
F. 261025-3: 발표 중 화면2를 빼면 본화면에서 다시 열고 단추를 숨기며 기억은 그대로, 다시 꽂으면 화면2로
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QRect, QPoint
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox
from PyQt6.QtGui import QContextMenuEvent

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_presscreen261021_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


class FakeScreen:
    """두 번째 모니터 흉내 — 오프스크린에는 화면이 하나뿐이다."""
    def name(self):
        return r"\\.\DISPLAY2"

    def geometry(self):
        return QRect(1920, 0, 1920, 1080)


root = Path(tempfile.mkdtemp(prefix="presscreen261021_"))
_orig_screens = QApplication.screens
_orig_exec = QMenu.exec
try:
    folder = root / "f"; folder.mkdir()
    a = folder / "a.pdf"
    d = fitz.open()
    for i in range(2):
        d.new_page(width=842, height=595).insert_text((72, 300), "P%d" % (i + 1))
    d.save(str(a)); d.close()
    from viewer.app import MainWindow
    from viewer.widgets.presentation import PresentationWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.No)
    mw._prefs["presentation_other_screen"] = False

    # A — 모니터 하나
    mw._open_presentation(); spin(0.5)
    w = mw._present
    row1 = w._topbar.layout().itemAt(0).layout()
    last = row1.itemAt(row1.count() - 1).widget()
    chk(last is w._tb_screen and row1.indexOf(w._tb_close) == row1.count() - 2,
        "A1 단추는 띠 첫 줄 맨 오른쪽(✕ 오른쪽)", str(last))
    chk(w._tb_screen.isHidden(), "A2 모니터가 하나면 단추를 숨긴다(261025-3)",
        str((w._tb_screen.text(), w._tb_screen.isHidden())))

    # B·C — 가짜 모니터 둘
    home = w._home_screen()
    fake = FakeScreen()
    QApplication.screens = staticmethod(lambda: [home, fake])
    moved = []
    _orig_stt = PresentationWindow.set_target_screen
    PresentationWindow.set_target_screen = lambda self, scr: (moved.append(scr), setattr(self, "_target_screen", scr))
    w._update_screen_button()
    chk(not w._tb_screen.isHidden() and w._tb_screen.text() == "🖥 화면2로", "B0 모니터가 둘이면 '🖥 화면2로' 가 보인다")
    chk("DISPLAY2" in w._tb_screen.toolTip() and "1920×1080" in w._tb_screen.toolTip(),
        "B0 풍선 도움말에 갈 모니터 이름·해상도(261024-3)", w._tb_screen.toolTip())
    w._tb_screen.click(); spin(0.2)
    chk(moved and moved[-1] is fake, "B1 누르면 다른 모니터(본화면이 아닌 첫 모니터)로 옮긴다", str(moved))
    chk(w._tb_screen.text() == "🖥 본화면으로", "B2 글이 '🖥 본화면으로'", w._tb_screen.text())
    chk(mw._prefs.get("presentation_other_screen") is True, "B3 설정에 기억(참)")
    chk("뷰어가 있는 모니터" in w._tb_screen.toolTip(), "B4 화면2에서는 되돌리기 풍선 도움말(261024-3)", w._tb_screen.toolTip())
    w._tb_screen.click(); spin(0.2)
    chk(moved[-1] is home and w._tb_screen.text() == "🖥 화면2로"
        and mw._prefs.get("presentation_other_screen") is False, "C 다시 누르면 본화면으로·설정 거짓")

    # F — 261025-3: 발표 중 모니터 빼기·꽂기(앱의 screenRemoved·screenAdded 신호로)
    w._tb_screen.click(); spin(0.2)                      # 화면2로
    QApplication.screens = staticmethod(lambda: [home])  # 화면2를 뺐다
    app.screenRemoved.emit(home); spin(0.2)
    chk(moved[-1] is home, "F1 화면2가 빠지면 본화면에서 다시 연다", str(moved[-1]))
    chk(w._tb_screen.isHidden(), "F2 모니터가 하나가 되면 단추가 바로 숨는다")
    chk(mw._prefs.get("presentation_other_screen") is True and w._other_screen,
        "F3 빼도 기억(화면2)은 그대로", str(mw._prefs.get("presentation_other_screen")))
    QApplication.screens = staticmethod(lambda: [home, fake])  # 다시 꽂았다
    app.screenAdded.emit(home); spin(0.2)
    chk(moved[-1] is fake and not w._tb_screen.isHidden() and w._tb_screen.text() == "🖥 본화면으로",
        "F4 다시 꽂으면 기억대로 화면2로·단추 보임", str((moved[-1], w._tb_screen.text())))
    w._tb_screen.click(); spin(0.2)                      # 본화면으로 되돌려 둔다

    # E — 우클릭 '화면 ▸ 모니터 2' 를 고르면 참, '모니터 1' 이면 거짓
    def pick_monitor(n):
        def fake_exec(menu, *a_, **k):
            for x in menu.actions():
                sm = x.menu()
                if sm is not None and x.text() == "화면":
                    return next((y for y in sm.actions() if y.text().startswith("모니터 %d" % n)), None)
            return None
        QMenu.exec = fake_exec
        w.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20)))
        QMenu.exec = _orig_exec
        spin(0.1)
    pick_monitor(2)
    chk(moved[-1] is fake and w._tb_screen.text() == "🖥 본화면으로" and mw._prefs.get("presentation_other_screen") is True,
        "E1 우클릭에서 다른 모니터를 고르면 단추·설정도 '다른 화면'", str((w._tb_screen.text(), mw._prefs.get("presentation_other_screen"))))
    pick_monitor(1)
    chk(moved[-1] is home and w._tb_screen.text() == "🖥 화면2로" and mw._prefs.get("presentation_other_screen") is False,
        "E2 본화면 모니터를 고르면 '본화면'·거짓")

    # D — 기억한 값으로 다음 발표
    mw._prefs["presentation_other_screen"] = True
    w.close(); spin(0.5)
    mw._open_presentation(); spin(0.5)
    w2 = mw._present
    chk(w2 is not w and w2._target_screen is fake and w2._tb_screen.text() == "🖥 본화면으로",
        "D 기억한 '다른 화면' 으로 다음 발표를 연다", str(w2._target_screen))
    PresentationWindow.set_target_screen = _orig_stt
    QApplication.screens = _orig_screens
    w2._target_screen = None
    w2.close(); spin(0.3)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QApplication.screens = _orig_screens
    QMenu.exec = _orig_exec
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
