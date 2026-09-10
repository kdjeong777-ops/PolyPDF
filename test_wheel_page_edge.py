# -*- coding: utf-8 -*-
"""260910-5: 휠로 쪽을 넘길 때의 규칙 (마스터 SOT §19.1).

사용자 보고: **"휠로 이동하다 보면 멈칫하거나 휙 이동해 미세하게 조절하기 어렵다.
특히 페이지 끝에서 순식간에 넘어가 이어진 내용인지 건너뛴 내용인지 인지하기 어렵다."**

결함은 셋이었다.
  (1) 뒤로 넘기면 이전 쪽의 **맨 위** 로 가 그 쪽 아래 전체를 건너뛰었다
  (2) 끝에 닿은 **바로 다음 칸**이 곧 쪽 넘김이라 관성 휠이 그냥 지나갔다
  (3) 한 번 튕기면 여러 쪽이 넘어갈 수 있었다
"""
import os, sys, inspect

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from PyQt6.QtWidgets import QApplication, QGraphicsScene
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QWheelEvent
app = QApplication.instance() or QApplication([])

from viewer.widgets.main_view import _PdfGraphicsView, MainView
import viewer.widgets.main_view as mv


def wheel(view, dy):
    """휠 한 건을 그대로 만들어 넣는다(모킹 아님 - 진짜 이벤트)."""
    ev = QWheelEvent(QPointF(10.0, 10.0), QPointF(10.0, 10.0),
                     QPoint(0, 0), QPoint(0, int(dy)),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    view.wheelEvent(ev)


def make_view():
    v = _PdfGraphicsView()
    v.setScene(QGraphicsScene(0, 0, 400, 3000))
    v.resize(400, 400)
    v.show()
    app.processEvents()
    got = []
    v.pageStep.connect(got.append)
    return v, got


print("=== (1) 경계 상수가 있다 (§19.1.2) ===")
chk(_PdfGraphicsView.EDGE_HOLD_MS == 350, "(1) 머무는 시간 기준이 상수다",
    str(_PdfGraphicsView.EDGE_HOLD_MS))
chk(_PdfGraphicsView.EDGE_PUSH == 120, "(1) 굴린 양 기준이 상수다",
    str(_PdfGraphicsView.EDGE_PUSH))

print()
print("=== (2) 쪽 안에서는 그냥 스크롤한다 ===")
v, got = make_view()
sb = v.verticalScrollBar()
sb.setValue(0)
before = sb.value()
wheel(v, -120)
chk(sb.value() > before, "(2) 아래로 굴리면 쪽 안에서 내려간다",
    "%d -> %d" % (before, sb.value()))
chk(got == [], "(2) 쪽 안에서는 쪽을 넘기지 않는다", str(got))

print()
print("=== (3) 끝에 처음 닿은 칸은 넘기지 않는다 (§19.1.2 규칙 2) ===")
sb.setValue(sb.maximum())
wheel(v, -120)
chk(got == [], "(3) 처음 닿은 칸은 '끝에 닿았음' 만 알린다", str(got))
wheel(v, -120)
chk(got == [], "(3) 350ms 안에서는 더 굴려도 넘어가지 않는다", str(got))

print()
print("=== (4) 시간과 양을 둘 다 넘겨야 넘어간다 (§19.1.2 규칙 3) ===")
# 시간만 채우고 양이 모자라면 넘어가지 않는다
v2, got2 = make_view()
sb2 = v2.verticalScrollBar()
sb2.setValue(sb2.maximum())
wheel(v2, -120)                       # 첫 접촉
v2._edge_ms -= 1000.0                 # 시간은 충분히 지난 것으로
wheel(v2, -40)                        # 양이 모자란다(40 < 120)
chk(got2 == [], "(4) 시간만 지나고 양이 모자라면 넘기지 않는다", str(got2))
wheel(v2, -100)                       # 누적 140 >= 120
chk(got2 == [1], "(4) 양까지 채우면 그때 넘어간다", str(got2))

print()
print("=== (5) 한 손짓에 한 쪽만 (§19.1.2 규칙 4) ===")
wheel(v2, -120)
chk(got2 == [1], "(5) 넘긴 직후 이어지는 칸은 또 넘기지 않는다", str(got2))
v2._edge_ms -= 1000.0
wheel(v2, -120)
chk(got2 == [1, 1], "(5) 다시 한 박자 쉬면 그다음 쪽으로 넘어간다", str(got2))

print()
print("=== (6) 쪽 안으로 돌아오면 처음부터 다시 센다 (§19.1.2 규칙 5) ===")
v3, got3 = make_view()
sb3 = v3.verticalScrollBar()
sb3.setValue(sb3.maximum())
wheel(v3, -120)
v3._edge_ms -= 1000.0
wheel(v3, 120)                        # 위로 - 쪽 안으로 돌아온다
chk(v3._edge_dir == 0, "(6) 경계 상태가 비워진다", str(v3._edge_dir))
sb3.setValue(sb3.maximum())
wheel(v3, -120)
chk(got3 == [], "(6) 다시 끝에 닿아도 첫 칸은 넘기지 않는다", str(got3))

print()
print("=== (7) 위끝에서도 같은 규칙 ===")
v4, got4 = make_view()
sb4 = v4.verticalScrollBar()
sb4.setValue(0)
wheel(v4, 120)
chk(got4 == [], "(7) 위끝 첫 칸은 넘기지 않는다", str(got4))
v4._edge_ms -= 1000.0
wheel(v4, 120)
chk(got4 == [-1], "(7) 한 박자 뒤에 이전 쪽으로", str(got4))

print()
print("=== (8) 뒤로 넘기면 이전 쪽의 아래끝으로 (§19.1.2 규칙 1) ===")
src = inspect.getsource(MainView.go_to_page)
chk("at_bottom" in src, "(8) go_to_page 가 착지 위치를 받는다")
chk("maximum()" in src, "(8) 아래끝으로 갈 길이 있다")
step = inspect.getsource(MainView._on_page_step)
chk("at_bottom=(delta < 0)" in step,
    "(8) 뒤로 갈 때만 아래끝으로 — 앞으로는 그대로 맨 위")
import re
sig = inspect.signature(MainView.go_to_page)
chk(sig.parameters["at_bottom"].default is False,
    "(8) 기본은 맨 위 — 책갈피·검색 등 다른 이동은 그대로다")

print()
print("=== (9) Ctrl+휠 확대는 그대로 ===")
v5, got5 = make_view()
zoom = []
v5.zoomRequested.connect(zoom.append)
ev = QWheelEvent(QPointF(10.0, 10.0), QPointF(10.0, 10.0), QPoint(0, 0),
                 QPoint(0, 120), Qt.MouseButton.NoButton,
                 Qt.KeyboardModifier.ControlModifier,
                 Qt.ScrollPhase.NoScrollPhase, False)
v5.wheelEvent(ev)
chk(len(zoom) == 1 and zoom[0] > 1.0, "(9) Ctrl+휠은 확대로 간다", str(zoom))
chk(got5 == [], "(9) 확대는 쪽을 넘기지 않는다", str(got5))

print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
