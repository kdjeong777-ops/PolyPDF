# -*- coding: utf-8 -*-
"""261025-3: 발표 왼쪽 '뒤로 가기 영역' 폭 설정과 '❮ 뒤로' 표시 (발표 SOT §3.1).

실제 마우스 클릭(QTest)을 발표 창에 넣어 본다.
A. 기본 폭 20% — 창 폭 15% 지점 클릭은 이전(종전 고정 10% 에서는 다음이었다)
B. 마우스로 뒤로 가면 왼쪽 가운데에 '❮ 뒤로' 가 보였다가 BACK_HINT_MS 뒤 사라진다
C. 앞으로(영역 밖 클릭)·키보드(←)로는 표시하지 않는다
D. 우클릭 메뉴 '뒤로 가기 영역' 입력칸 → 폭이 바뀌고 설정 `presentation_back_zone_pct` 에 저장, 다음 발표도 그 폭
E. 지우개 도구에서도 같은 영역 규칙, 범위 밖 값은 BACK_ZONE_MIN~MAX 로
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSpinBox, QWidgetAction, QLabel
from PyQt6.QtGui import QContextMenuEvent
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_presbackzone261025_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def click(w, frac):
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(int(w.width() * frac), w.height() // 2))
    spin(0.1)


root = Path(tempfile.mkdtemp(prefix="presbackzone261025_"))
_orig_exec = QMenu.exec
try:
    folder = root / "f"; folder.mkdir()
    a = folder / "a.pdf"
    d = fitz.open()
    for i in range(5):
        d.new_page(width=842, height=595).insert_text((72, 300), "P%d" % (i + 1))
    d.save(str(a)); d.close()
    from viewer.app import MainWindow
    from viewer.widgets import presentation as P
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 2); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.No)
    mw._prefs.pop("presentation_back_zone_pct", None)

    mw._open_presentation(); spin(0.5)
    w = mw._present
    w._page = 2; w._render(); spin(0.2)
    chk(w.width() > 100, "준비 발표 창 크기", str(w.width()))

    # A·B
    click(w, 0.15)
    chk(w._page == 1, "A1 창 폭 15% 지점 클릭 = 이전(기본 20%)", str(w._page))
    chk(abs(getattr(w, "_back_zone_frac", 0) - 0.20) < 1e-9, "A2 기본 폭 20%", str(getattr(w, "_back_zone_frac", None)))
    hint = w._back_hint
    chk(hint.isVisible() and hint.text() == "❮ 뒤로", "B1 '❮ 뒤로' 가 보인다", str((hint.isVisible(), hint.text())))
    chk(hint.x() < w.width() * 0.2 and abs(hint.geometry().center().y() - w.height() // 2) <= 2,
        "B2 왼쪽 끝·세로 가운데", str(hint.geometry()))
    spin(P.BACK_HINT_MS / 1000.0 + 0.3)
    chk(not hint.isVisible(), "B3 잠시 뒤 사라진다")

    # C
    click(w, 0.5)
    chk(w._page == 2 and not hint.isVisible(), "C1 영역 밖 클릭 = 다음, 표시 없음", str(w._page))
    QTest.keyClick(w, Qt.Key.Key_Left); spin(0.1)
    chk(w._page == 1 and not hint.isVisible(), "C2 키보드 ← 는 표시 없음", str(w._page))

    # D — 우클릭 메뉴 입력칸
    def set_spin(val):
        def fake_exec(menu, *a_, **k):
            for x in menu.actions():
                if isinstance(x, QWidgetAction):
                    wd = x.defaultWidget()
                    labs = [l.text() for l in wd.findChildren(QLabel)]
                    if "뒤로 가기 영역" in labs:
                        wd.findChild(QSpinBox).setValue(val)
            return None
        QMenu.exec = fake_exec
        w.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20)))
        QMenu.exec = _orig_exec
        spin(0.1)
    set_spin(35)
    chk(abs(w._back_zone_frac - 0.35) < 1e-9 and mw._prefs.get("presentation_back_zone_pct") == 35,
        "D1 메뉴 입력칸 → 폭·설정 저장", str((w._back_zone_frac, mw._prefs.get("presentation_back_zone_pct"))))
    w._page = 3; w._render(); spin(0.1)
    click(w, 0.30)
    chk(w._page == 2, "D2 바뀐 폭(35%) 안의 30% 지점 = 이전", str(w._page))
    w.close(); spin(0.4)
    mw._open_presentation(); spin(0.5)
    w = mw._present
    chk(abs(w._back_zone_frac - 0.35) < 1e-9, "D3 다음 발표도 기억한 폭", str(w._back_zone_frac))

    # E
    w._tool = "erase"
    w._page = 3; w._render(); spin(0.1)
    click(w, 0.30)
    chk(w._page == 2 and w._back_hint.isVisible(), "E1 지우개 도구도 같은 영역 규칙·표시", str(w._page))
    w._tool = "pen"
    w.set_back_zone_pct(99, emit=False)
    chk(abs(w._back_zone_frac - P.BACK_ZONE_MAX / 100.0) < 1e-9, "E2 범위 밖 값은 최대로", str(w._back_zone_frac))
    w.set_back_zone_pct(1, emit=False)
    chk(abs(w._back_zone_frac - P.BACK_ZONE_MIN / 100.0) < 1e-9, "E3 범위 밖 값은 최소로", str(w._back_zone_frac))
    w.close(); spin(0.3)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
