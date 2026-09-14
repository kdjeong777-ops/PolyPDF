# -*- coding: utf-8 -*-
"""휠로 쪽을 넘길 때의 규칙 (입력 장치 SOT §2.2).

260910-5 사용자 보고: "페이지 끝에서 순식간에 넘어가 이어진 내용인지 모르겠다"
  → 뒤로 넘기면 아래끝, 경계에서 한 박자.
260914-1 사용자 지시: "약간의 움직임으로 넘어가게. 다만 휠 떨림으로는 넘어가지 않게,
  지체 후 갑자기 넘어가지 않게."
  → 쪽 맞춤은 한 칸에 한 쪽. 멈추면 쌓인 양 0, 넘긴 직후·되튐·늦게 처리된 이벤트 무시.

**함수가 있는가를 보지 않는다.** 진짜 휠 이벤트를 시계를 돌려 가며 넣고 몇 번 넘어가는지 센다.
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

CLOCK = {"t": 100000.0}
_real_perf = mv._perf_ms
mv._perf_ms = lambda: CLOCK["t"]          # 시계를 손에 쥔다


class _TsWheel(QWheelEvent):
    """OS 이벤트 시각을 정해 넣은 휠(PyQt6 에는 setTimestamp 가 없다)."""
    _ts = 0

    def timestamp(self):
        return self._ts


def wheel(view, dy, dt=0.0, phase=Qt.ScrollPhase.NoScrollPhase, ts=None,
          mods=Qt.KeyboardModifier.NoModifier):
    """휠 한 건을 그대로 만들어 넣는다(모킹 아님 - 진짜 이벤트). dt 만큼 시계를 먼저 돌린다."""
    CLOCK["t"] += dt
    ev = _TsWheel(QPointF(10.0, 10.0), QPointF(10.0, 10.0),
                  QPoint(0, 0), QPoint(0, int(dy)),
                  Qt.MouseButton.NoButton, mods, phase, False)
    ev._ts = int(ts) if ts is not None else 0
    view.wheelEvent(ev)


def make_view(tall=True):
    v = _PdfGraphicsView()
    v.setScene(QGraphicsScene(0, 0, 380, 3000 if tall else 300))
    v.resize(400, 400)
    v.show()
    app.processEvents()
    got = []
    v.pageStep.connect(got.append)
    CLOCK["t"] += 10000.0                  # 앞 검사의 여운이 남지 않게
    return v, got


P = _PdfGraphicsView
print("=== (1) 값은 한 곳(코드)에 있다 (§2.2) ===")
chk(P.EDGE_PUSH == 120, "(1) 휠 한 칸이 넘김 양이다", str(P.EDGE_PUSH))
chk(0 < P.EDGE_HOLD_MS < 350, "(1) 확대한 쪽의 한 박자가 종전(350)보다 짧다", str(P.EDGE_HOLD_MS))
chk(P.FLIP_LOCK_MS < P.FLIP_BOUNCE_MS, "(1) 되튐 무시가 잠금보다 길다",
    "%s/%s" % (P.FLIP_LOCK_MS, P.FLIP_BOUNCE_MS))
chk(P.EDGE_IDLE_MS > 0 and P.STALE_MS > 0, "(1) 멈춤·늦음 기준이 있다")

print()
print("=== (2) 쪽 안에서는 그냥 스크롤한다 ===")
v, got = make_view()
sb = v.verticalScrollBar()
sb.setValue(0)
before = sb.value()
wheel(v, -120)
chk(sb.value() > before, "(2) 아래로 굴리면 쪽 안에서 내려간다", "%d -> %d" % (before, sb.value()))
chk(got == [], "(2) 쪽 안에서는 쪽을 넘기지 않는다", str(got))

print()
print("=== (3) ★ 쪽 맞춤(스크롤 자리 없음)은 한 칸에 한 쪽 (규칙 2) ===")
f, gf = make_view(tall=False)
sbf = f.verticalScrollBar()
chk(sbf.maximum() == sbf.minimum(), "(3) 스크롤 자리가 없다", "%d..%d" % (sbf.minimum(), sbf.maximum()))
wheel(f, -120)
chk(gf == [1], "(3) 아래로 한 칸 → 곧바로 다음 쪽", str(gf))
gf.clear()
wheel(f, +120, dt=1000)
chk(gf == [-1], "(3) 위로 한 칸 → 곧바로 이전 쪽", str(gf))

print()
print("=== (4) 확대한 쪽은 끝에 닿은 뒤 한 박자 (규칙 3) ===")
v, got = make_view()
sb = v.verticalScrollBar()
sb.setValue(sb.maximum() - 30)             # 끝 가까이
wheel(v, -120)                             # 이 칸으로 끝에 닿는다
chk(sb.value() == sb.maximum() and got == [], "(4) 닿는 칸은 스크롤만 한다", str(got))
wheel(v, -120, dt=P.EDGE_HOLD_MS * 0.5)
chk(got == [], "(4) 한 박자 안의 다음 칸은 넘기지 않는다", str(got))
wheel(v, -120, dt=P.EDGE_HOLD_MS)
chk(got == [1], "(4) 한 박자 뒤 한 칸이면 넘어간다", str(got))
# 닿은 뒤 충분히 쉬었다면 **한 칸**이면 된다 — 닿는 칸을 버리지 않는다
v, got = make_view()
sb = v.verticalScrollBar()
sb.setValue(sb.maximum() - 30)
wheel(v, -120)
wheel(v, -120, dt=P.EDGE_HOLD_MS + 50)
chk(got == [1], "(4) 끝까지 읽고 쉬었다가 한 칸 → 넘어간다(두 칸 들지 않는다)", str(got))
# 스크롤이 아닌 길(키·막대)로 끝에 와 있었다면 첫 칸은 알림
v, got = make_view()
sb = v.verticalScrollBar()
sb.setValue(sb.maximum())
wheel(v, -120)
chk(got == [], "(4) 스크롤로 닿은 게 아니면 첫 칸은 '끝' 알림", str(got))
wheel(v, -120, dt=P.EDGE_HOLD_MS + 10)
chk(got == [1], "(4) 그다음 칸에 넘어간다", str(got))

print()
print("=== (5) ★ 떨림은 시간을 두고 쌓이지 않는다 (규칙 4, 원인 2) ===")
f, gf = make_view(tall=False)
for i in range(40):                        # 작은 떨림 30 을 0.3초마다 — 12초 동안
    wheel(f, -30, dt=300)
chk(gf == [], "(5) 띄엄띄엄 오는 작은 떨림 40번으로는 넘어가지 않는다", str(gf))
for i in range(4):                         # 같은 양을 한 번에 굴리면(한 칸) 넘어간다
    wheel(f, -30, dt=10)
chk(gf == [1], "(5) 같은 양이라도 이어서 굴리면 한 칸이다", str(gf))

print()
print("=== (6) 넘긴 직후는 잠근다 — 빨리 굴리면 여러 쪽 (규칙 5) ===")
f, gf = make_view(tall=False)
wheel(f, -120)
wheel(f, -120, dt=P.FLIP_LOCK_MS * 0.5)
chk(gf == [1], "(6) 넘긴 직후 들어온 칸은 버린다", str(gf))
wheel(f, -120, dt=P.FLIP_LOCK_MS)
chk(gf == [1, 1], "(6) 잠금이 풀린 뒤의 칸은 또 한 쪽", str(gf))

print()
print("=== (7) ★ 그리느라 막혔던 사이 쌓인 이벤트는 넘기지 않는다 (규칙 5, 원인 3) ===")
f, gf = make_view(tall=False)
f.pageStep.connect(lambda _d: CLOCK.__setitem__("t", CLOCK["t"] + 600))   # 쪽 그리기 0.6초
wheel(f, -120)
chk(gf == [1], "(7) 첫 칸은 넘어간다", str(gf))
wheel(f, -120, dt=2)                        # 막힘이 풀리자마자 처리되는 쌓인 칸
wheel(f, -120, dt=2)
chk(gf == [1], "(7) 막힘이 풀리자마자 처리된 칸들로 또 넘기지 않는다", str(gf))

print()
print("=== (8) 걸쇠 되튐(반대 방향)은 무시 (규칙 6) ===")
f, gf = make_view(tall=False)
wheel(f, -120)
wheel(f, +120, dt=P.FLIP_LOCK_MS + 10)
chk(gf == [1], "(8) 넘긴 직후 반대로 튄 칸은 도로 넘기지 않는다", str(gf))
wheel(f, +120, dt=P.FLIP_BOUNCE_MS)
chk(gf == [1, -1], "(8) 한참 뒤 반대로 굴리면 그건 의도다", str(gf))

print()
print("=== (9) ★ 늦게 처리된 이벤트로는 넘기지 않는다 (규칙 7) ===")
f, gf = make_view(tall=False)
T0 = 5000000
wheel(f, 0, ts=T0)                         # 기준 잡기(시각 차이) — 양 0 은 무시된다
f._ts_off = CLOCK["t"] - T0                # 늦지 않은 차이
lag_ts = int(CLOCK["t"] - f._ts_off) - int(P.STALE_MS + 400)
wheel(f, -120, dt=0, ts=lag_ts)            # 만들어진 지 0.65초 뒤 처리
chk(gf == [], "(9) 창이 멈춘 사이 굴린 칸은 풀린 뒤 넘기지 않는다", str(gf))
ok_ts = int(CLOCK["t"] + 1000 - f._ts_off) - 5
wheel(f, -120, dt=1000, ts=ok_ts)
chk(gf == [1], "(9) 제때 처리된 칸은 넘어간다", str(gf))
wheel(f, -120, dt=1000, ts=0)
chk(gf == [1, 1], "(9) 시각이 없는 이벤트는 검사하지 않는다", str(gf))

print()
print("=== (10) 트랙패드 — 한 번 쓸면 한 쪽 (규칙 8) ===")
f, gf = make_view(tall=False)
U, B = Qt.ScrollPhase.ScrollUpdate, Qt.ScrollPhase.ScrollBegin
wheel(f, -16, phase=B)
for i in range(80):
    wheel(f, -16, dt=8, phase=U)
chk(gf == [1], "(10) 길게 쓸어도 한 쪽", str(gf))
wheel(f, -16, dt=8, phase=B)
for i in range(20):
    wheel(f, -16, dt=8, phase=U)
chk(gf == [1, 1], "(10) 손을 새로 얹으면 다음 쪽", str(gf))

print()
print("=== (11) 뒤로 넘기면 이전 쪽의 아래끝으로 (규칙 1) ===")
src = inspect.getsource(MainView.go_to_page)
chk("at_bottom" in src, "(11) go_to_page 가 착지 위치를 받는다")
chk("_page_span()[1]" in src, "(11) 지금 쪽의 아래끝으로 갈 길이 있다(이어 보기에서도)")
step = inspect.getsource(MainView._on_page_step)
chk("at_bottom=(delta < 0)" in step, "(11) 뒤로 갈 때만 아래끝으로 — 앞으로는 그대로 맨 위")
sig = inspect.signature(MainView.go_to_page)
chk(sig.parameters["at_bottom"].default is False,
    "(11) 기본은 맨 위 — 책갈피·검색 등 다른 이동은 그대로다")

print()
print("=== (12) Ctrl+휠 확대는 그대로 ===")
v5, got5 = make_view(tall=False)
zoom = []
v5.zoomRequested.connect(zoom.append)
wheel(v5, 120, mods=Qt.KeyboardModifier.ControlModifier)
chk(len(zoom) == 1 and zoom[0] > 1.0, "(12) Ctrl+휠은 확대로 간다", str(zoom))
chk(got5 == [], "(12) 확대는 쪽을 넘기지 않는다", str(got5))

mv._perf_ms = _real_perf
print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
