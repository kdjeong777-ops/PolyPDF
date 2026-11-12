# -*- coding: utf-8 -*-
"""띠로 펼친 오른쪽 드로어는 바깥을 누르면 접힌다 (261112-21, 사용자 지시 — 디자인 SOT §2.4.1 '바깥을 누르면 접힘').

A. 띠를 누르면 펼치고 바깥 누름 감시가 걸린다
B. 본문(1단)을 누르면 접히고, 그 누름은 본문이 그대로 받는다(먹지 않는다) · 감시는 떨어진다
C. 드로어 안을 누르면 그대로 펼쳐 있다
D. 다른 최상위 창(대화상자)을 누르면 그대로 펼쳐 있다
E. 띠로 접으면 감시가 떨어진다
F. 캡처 자동 펼침(_drawer_auto_show)은 바깥을 눌러도 접지 않는다(1.5초 타이머가 접는다)
G. 2단에서도 B 와 같다 · 썸네일(왼쪽) 누름도 접는다
H. 우클릭도 접는다
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, Qt, QObject, QEvent
QStandardPaths.setTestModeEnabled(True)             # 검사 작성 SOT §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton, QVBoxLayout
from PyQt6.QtTest import QTest
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_drawer_autoclose_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "드로어 자동 접기", echo=False)   # 뜨는 모달은 닫는다
from viewer.app import MainWindow
import test_fixtures

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(ms=60):
    for _ in range(4):
        app.processEvents()
        QTest.qWait(ms // 4)


class PressCount(QObject):
    def __init__(self, w):
        super().__init__(w)
        self.n = 0
        w.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonPress:
            self.n += 1
        return False


def closer_armed():
    c = getattr(mw, "_drawer_closer", None)
    return bool(c is not None and c.is_armed())


def open_by_band():
    if not mw._drawer_open:
        QTest.mouseClick(band, Qt.MouseButton.LeftButton, pos=QPoint(band.width() // 2, band.height() // 3))
        pump(300)


def press_target(mv):
    """본문 창 가운데 아래에 있는 실제 위젯(누름을 받는 것)."""
    p = mv.mapTo(mw, QPoint(mv.width() // 3, mv.height() // 2))
    w = mw.childAt(p)
    return w, w.mapFrom(mw, p)


mw = MainWindow()
mw.resize(1400, 820)
mw.show(); pump()
pdf = str(test_fixtures.text_pdf())
for mv in mw._mv:
    mv.load_document(pdf)
mw.act_toggle_search.setChecked(False); mw.act_toggle_shot.setChecked(False); pump(200)
band = mw._drawer_btn
chk(mw._panel_in_drawer and band.isVisible(), "준비 — 검색·스크린샷 숨김이면 드로어")

# A
open_by_band()
chk(mw._drawer_open and closer_armed(), "A 띠를 누르면 펼치고 바깥 누름 감시가 걸린다")

# B
tw, tp = press_target(mw._mv[0])
cnt = PressCount(tw)
QTest.mouseClick(tw, Qt.MouseButton.LeftButton, pos=tp); pump(300)
chk(not mw._drawer_open, "B 본문을 누르면 접힌다", "위젯 %s" % type(tw).__name__)
chk(cnt.n >= 1, "B 그 누름은 본문이 그대로 받는다(먹지 않는다)", "받은 누름 %d" % cnt.n)
chk(not closer_armed(), "B 접히면 감시가 떨어진다")

# C
open_by_band()
inner = mw.right_panel
ip = QPoint(inner.width() // 2, inner.height() // 2)
iw = inner.childAt(ip) or inner
QTest.mouseClick(iw, Qt.MouseButton.LeftButton, pos=iw.mapFrom(inner, ip)); pump(300)
chk(mw._drawer_open, "C 드로어 안을 누르면 그대로 펼쳐 있다", "위젯 %s" % type(iw).__name__)

# D
dlg = QDialog(mw); _l = QVBoxLayout(dlg); _b = QPushButton("x"); _l.addWidget(_b)
dlg.show(); pump()
QTest.mouseClick(_b, Qt.MouseButton.LeftButton); pump(200)
chk(mw._drawer_open, "D 다른 최상위 창을 누르면 그대로")
dlg.close(); dlg.deleteLater(); pump()

# E
QTest.mouseClick(band, Qt.MouseButton.LeftButton, pos=QPoint(band.width() // 2, band.height() // 3)); pump(300)
chk(not mw._drawer_open and not closer_armed(), "E 띠로 접으면 감시가 떨어진다")

# F
mw._drawer_auto_show(); pump(100)
tw, tp = press_target(mw._mv[0])
QTest.mouseClick(tw, Qt.MouseButton.LeftButton, pos=tp); pump(100)
chk(mw._drawer_open and not closer_armed(), "F 캡처 자동 펼침은 바깥 누름으로 접지 않는다")
mw._drawer_timer.stop()
mw._toggle_drawer(); pump(300)

# G
mw.act_split.setChecked(True); pump(300)
chk(mw._panel_in_drawer, "G 준비 — 2단이면 드로어")
open_by_band()
tw, tp = press_target(mw._mv[1])
QTest.mouseClick(tw, Qt.MouseButton.LeftButton, pos=tp); pump(300)
chk(not mw._drawer_open, "G 2단 오른쪽 본문을 누르면 접힌다")
open_by_band()
th = mw.page_thumbs
if th.isVisible() and th.width() > 4:
    tpt = QPoint(th.width() // 2, 10)
    tww = th.childAt(tpt) or th
    QTest.mouseClick(tww, Qt.MouseButton.LeftButton, pos=tww.mapFrom(th, tpt)); pump(300)
    chk(not mw._drawer_open, "G 썸네일창을 눌러도 접힌다")
else:
    mw._toggle_drawer(); pump(300)

# H
open_by_band()
tw, tp = press_target(mw._mv[0])
QTest.mousePress(tw, Qt.MouseButton.RightButton, pos=tp); pump(200)
QTest.mouseRelease(tw, Qt.MouseButton.RightButton, pos=tp); pump(200)
for w in QApplication.topLevelWidgets():          # 뜬 우클릭 메뉴는 닫는다
    if w.isVisible() and w.inherits("QMenu"):
        w.close()
pump()
chk(not mw._drawer_open, "H 우클릭도 접는다")

mw.close()
print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
