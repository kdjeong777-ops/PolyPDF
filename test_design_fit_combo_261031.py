# -*- coding: utf-8 -*-
"""261031-11(사용자 지시, 디자인 SOT §2.9.2·§2.10): 맞춤 콤보는 창 아래 오른쪽 `+ 0 −` 왼쪽, 본문 툴바의 − / + 는 없다.

A. 상태 막대 차례: [맞춤 ▾] + 0 − — 본문 툴바에는 맞춤 콤보·− / + 단추가 없다(두 창 모두)
B. 맞춤 콤보는 **본화면(활성 창)에만** — 2단에서 오른쪽 창을 활성으로 두고 '폭 맞춤' 을 고르면 그 창만 바뀐다
C. 활성 창을 바꾸면 콤보가 그 창의 맞춤을 보인다
D. 창 아래 `+` 는 종전대로 포커스 창 기준 — 본문이면 본문 확대(콤보는 '수동 맞춤'), 썸네일에 포커스면 본문은 그대로
수정 전 코드로 A 가 실패한다.
"""
import os, sys, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)

from PyQt6.QtCore import QStandardPaths, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
from PyQt6.QtCore import QCoreApplication as _QCA
_QCA.setApplicationName("polypdf_fit_combo_%d" % os.getpid())   # 마스터 §14.7.2 의 3
import modal_guard
guard = modal_guard.install(label=lambda: "맞춤 콤보", watch_ms=0, echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


try:
    from test_fixtures import text_pdf
    from viewer.app import MainWindow
    from viewer.widgets.main_view import MainView as MV
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1500, 900); mw.show(); mw.activateWindow(); QTest.qWait(200)

    # A
    x = lambda w: w.mapTo(mw, w.rect().topLeft()).x()
    btns = mw._zoom_btns
    chk(hasattr(mw, "cmb_fit") and mw.cmb_fit.isVisible() and x(mw.cmb_fit) < x(btns[0]) < x(btns[1]) < x(btns[2])
        and [b.text() for b in btns] == ["+", "0", "−"], "A 상태 막대 차례 [맞춤 ▾] + 0 −")
    chk(all(not hasattr(m, "cmb_fit") and not hasattr(m, "btn_zoom_in") and not hasattr(m, "btn_zoom_out") for m in mw._mv),
        "A 본문 툴바에 맞춤 콤보·− / + 가 없다(두 창)")
    chk(mw.cmb_fit.focusPolicy() == Qt.FocusPolicy.NoFocus, "A 맞춤 콤보는 포커스를 받지 않는다")

    # B 2단 — 오른쪽 창 활성에서 '폭 맞춤'
    mw.open_pdf(text_pdf()); QTest.qWait(500)
    mw.act_split.setChecked(True); QTest.qWait(400)
    mw._on_bookmark_activated_right(str(text_pdf()), 0); QTest.qWait(400)
    left, right = mw._mv
    mw._set_active_pane(1); QTest.qWait(50)
    chk(mw.main_view is right, "B 준비 — 오른쪽 창이 활성")
    mw.cmb_fit.setCurrentIndex(mw.cmb_fit.findData(MV.FIT_WIDTH)); QTest.qWait(200)
    chk(right._fit_mode == MV.FIT_WIDTH and left._fit_mode == MV.FIT_PAGE, "B 맞춤 콤보는 활성 창에만",
        str((left._fit_mode, right._fit_mode)))

    # C 활성 창을 바꾸면 콤보가 따라간다
    mw._set_active_pane(0); QTest.qWait(50)
    chk(mw.cmb_fit.currentData() == MV.FIT_PAGE, "C 왼쪽 창 활성 → 콤보 '쪽 맞춤'", mw.cmb_fit.currentData())
    mw._set_active_pane(1); QTest.qWait(50)
    chk(mw.cmb_fit.currentData() == MV.FIT_WIDTH, "C 오른쪽 창 활성 → 콤보 '폭 맞춤'", mw.cmb_fit.currentData())

    # D + 0 − 는 포커스 창 기준
    mw.act_split.setChecked(False); QTest.qWait(300)
    mv = mw.main_view
    mv.choose_fit(MV.FIT_PAGE); QTest.qWait(100)
    mv.view.setFocus(); QTest.qWait(50)
    z0 = mv._zoom
    QTest.mouseClick(btns[0], Qt.MouseButton.LeftButton); QTest.qWait(200)
    chk(mv._zoom > z0 and mw.cmb_fit.currentData() == MV.FIT_NONE, "D 본문 포커스 + → 본문 확대·콤보 '수동 맞춤'",
        str((z0, mv._zoom, mw.cmb_fit.currentData())))
    mv.choose_fit(MV.FIT_PAGE); QTest.qWait(100)
    z1 = mv._zoom
    mw.page_thumbs.list.setFocus(); QTest.qWait(50)
    QTest.mouseClick(btns[0], Qt.MouseButton.LeftButton); QTest.qWait(200)
    chk(abs(mv._zoom - z1) < 1e-9 and mw.cmb_fit.currentData() == MV.FIT_PAGE, "D 썸네일 포커스 + → 본문은 그대로",
        str((z1, mv._zoom)))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
