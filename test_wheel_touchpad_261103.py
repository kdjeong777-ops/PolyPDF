# -*- coding: utf-8 -*-
"""261103-7: 터치패드 두 손가락 쓸기 한 번 = 한 쪽 — 입력 장치 SOT §2.2 규칙 8·§2.3 규칙 6.

사용자 보고: 쪽 맞춤에서 노트북 터치패드로 위아래(두 손가락 쓸기)를 하면 1쪽 또는 2쪽 등 그때그때 달라진다.
Windows 정밀 터치패드는 Qt 에 **단계(phase) 없이**(`NoScrollPhase`) 작은 휠 값(120 의 배수가 아님)을 8~16ms 마다 보내고,
손을 뗀 뒤의 관성도 같은 모양으로 보낸다. 종전 코드는 단계가 있는 장치만 '한 손짓에 한 쪽'(규칙 8)으로 묶어서,
한 번 쓸기를 120 단위마다 한 쪽씩(넘긴 직후 `FLIP_LOCK_MS` 만 쉬고) 셌다 — 쓸기 길이·세기에 따라 1~3쪽.
집기(pinch)는 Windows 가 Ctrl+작은 휠 값으로 보내는데, 종전에는 이벤트마다 1.15 배라 한 번 집기에 수십 배가 됐다.

실제 휠 이벤트를 뷰포트에 보내서:
  A  약한·보통·긴 쓸기(관성 꼬리 포함) 각각 정확히 한 쪽
  B  쓸기 두 번(사이에 손 뗌) = 두 쪽, 위로 뒤집어 쓸기 = 한 쪽 뒤로
  C  보통 마우스 휠(한 칸 120)을 빠르게 연달아 굴리면 종전처럼 칸마다 한 쪽
  D  집기: Ctrl+작은 값 30건(합 360 = 휠 세 칸어치)은 1.15³ 언저리, 휠 한 칸은 1.15 그대로, 가로만 온 Ctrl 휠은 확대·축소하지 않음
수정 전 코드는 A(긴 쓸기 2~3쪽)·D(수십 배·가로에 축소)로 실패한다.
"""
import os, sys, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QWheelEvent
app = QApplication.instance() or QApplication([])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(ms=0):
    end = time.perf_counter() + ms / 1000.0
    app.processEvents()
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)
    app.processEvents()


from viewer.widgets.main_view import MainView
from test_fixtures import text_pdf

m = MainView()
m.resize(900, 800)
m.show(); pump()
m.set_page_flip_anim(False)
m.load_document(text_pdf(), 10)
if m.shown_fit() != MainView.FIT_PAGE:
    m.choose_fit(MainView.FIT_PAGE)
pump(100)
vp = m.view.viewport()


def send(dy, dx=0, mods=Qt.KeyboardModifier.NoModifier):
    ev = QWheelEvent(QPointF(200, 200), QPointF(vp.mapToGlobal(QPoint(200, 200))), QPoint(0, 0), QPoint(dx, dy),
                     Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)


def swipe(sign, contact, inertia_start, decay=0.88, gap=10):
    """Windows 정밀 터치패드의 쓸기 한 번 — 손가락이 닿은 동안 + 손 뗀 뒤 관성, 모두 단계 없음."""
    for d in contact:
        send(sign * d); pump(gap)
    v = float(inertia_start)
    while v >= 1:
        send(sign * int(round(v))); pump(gap)
        v *= decay
    pump(350)                                     # 손 뗌·관성 끝 — 다음 쓸기 전 쉼


def moved(fn):
    p0 = m.current_page()
    fn()
    return m.current_page() - p0


CONTACT_SHORT = [6, 12, 20, 26, 22, 18]                                   # 합 104 — 약한 쓸기
CONTACT_MID = [8, 16, 28, 36, 40, 34, 26, 18]                             # 합 206
CONTACT_LONG = [10, 20, 34, 46, 54, 58, 56, 50, 44, 36, 28]               # 합 436 — 길고 센 쓸기

# A — 쓸기 한 번 = 한 쪽
chk(moved(lambda: swipe(-1, CONTACT_SHORT, 16)) == 1, "A1 약한 쓸기(+관성) 한 번 = 한 쪽")
d = moved(lambda: swipe(-1, CONTACT_MID, 24))
chk(d == 1, "A2 보통 쓸기(+관성) 한 번 = 한 쪽", "넘어간 쪽 %d" % d)
d = moved(lambda: swipe(-1, CONTACT_LONG, 40, decay=0.93))
chk(d == 1, "A3 길고 센 쓸기(+긴 관성) 한 번 = 한 쪽", "넘어간 쪽 %d" % d)

# B — 두 번 쓸면 두 쪽, 뒤집으면 한 쪽 뒤로
d = moved(lambda: (swipe(-1, CONTACT_MID, 24), swipe(-1, CONTACT_MID, 24)))
chk(d == 2, "B1 쓸기 두 번 = 두 쪽", "넘어간 쪽 %d" % d)
d = moved(lambda: swipe(+1, CONTACT_MID, 24))
chk(d == -1, "B2 위로 쓸기 한 번 = 한 쪽 뒤로", "넘어간 쪽 %d" % d)


# C — 보통 마우스 휠은 종전대로(빠르게 굴리면 칸마다 한 쪽)
def notches():
    for _ in range(3):
        send(-120); pump(180)
    pump(300)


d = moved(notches)
chk(d == 3, "C 보통 마우스 휠 세 칸(180ms 간격) = 세 쪽", "넘어간 쪽 %d" % d)

# D — 집기 확대
m.choose_fit(MainView.FIT_PAGE); pump(100)
z0 = m._zoom
for _ in range(30):
    send(12, mods=Qt.KeyboardModifier.ControlModifier); pump(8)
pump(150)
r = m._zoom / z0
chk(1.3 < r < 1.75, "D1 집기(Ctrl+12 × 30, 합 360) ≈ 1.15³", "배율 %.2f" % r)
z1 = m._zoom
send(120, mods=Qt.KeyboardModifier.ControlModifier); pump(150)
r = m._zoom / z1
chk(abs(r - 1.15) < 0.01, "D2 Ctrl+휠 한 칸 = 1.15 배 그대로", "배율 %.3f" % r)
z2 = m._zoom
send(0, dx=40, mods=Qt.KeyboardModifier.ControlModifier); pump(150)
chk(abs(m._zoom - z2) < 1e-9, "D3 가로만 온 Ctrl 휠은 확대·축소하지 않는다", "%.3f → %.3f" % (z2, m._zoom))

# E — 쪽 썸네일 목록: 작은 값은 모아 120 마다 한 칸, 목록 끝의 파일 경계는 쓸기 한 번에 한 번
from viewer.widgets.thumbs_list import PageThumbs
pt = PageThumbs(); pt.resize(150, 300); pt.show(); pump()
pt.load_document(text_pdf()); pump(300)
tvp = pt.list.viewport()
tsb = pt.list.verticalScrollBar()
asked = []
pt.fileBoundaryRequested.connect(asked.append)


def tsend(dy):
    ev = QWheelEvent(QPointF(50, 50), QPointF(tvp.mapToGlobal(QPoint(50, 50))), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(tvp, ev)


chk(tsb.maximum() >= 6, "E0 썸네일 목록에 굴릴 자리가 있다", "max %d" % tsb.maximum())
tsb.setValue(0); v0 = tsb.value()
for _ in range(24):                     # 합 −240 = 휠 두 칸어치
    tsend(-10); pump(8)
chk(tsb.value() - v0 == 2, "E1 작은 값 24건(합 240) = 썸네일 두 칸", "%d칸" % (tsb.value() - v0))
pump(300)
tsb.setValue(tsb.maximum()); pump(50)
for _ in range(60):                     # 목록 끝에서 길게 쓸기
    tsend(-15); pump(8)
chk(asked == [+1], "E2 목록 끝에서 쓸기 한 번 = 파일 경계 한 번", str(asked))
pump(300)
v1 = tsb.value()
tsend(+120); pump(20)
chk(v1 - tsb.value() == 1, "E3 보통 휠 한 칸 = 썸네일 한 칸 그대로", "%d칸" % (v1 - tsb.value()))

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
