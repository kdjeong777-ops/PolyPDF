# -*- coding: utf-8 -*-
"""260912-4: 트랙패드·키보드 (입력 장치 SOT §2.3·§3).

사용자 보고: **"노트북 패드에서 두 손가락으로 페이지를 아래로 넘기다가 위로 넘기면
잘 작동하지 않는다."**

트랙패드는 손가락을 뗀 뒤에도 **관성**으로 이벤트를 더 보낸다. 종전에는 그것을
사람이 민 것과 구별하지 않아, 방향을 뒤집으면 관성이 사람의 입력을 계속 지웠다.

**이 검사는 '함수가 있는가' 를 보지 않는다.** 관성과 사람 입력을 실제로 섞어 넣어
**몇 건 만에 넘어가는지**를 잰다 — 그 값이 곧 사용자가 느끼는 차이다.
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF
from PyQt6.QtGui import QWheelEvent, QKeyEvent
from PyQt6.QtWidgets import QApplication, QGraphicsScene
from viewer.widgets import main_view as mv

CLOCK = {"t": 0.0}
_real_perf = mv._perf_ms
mv._perf_ms = lambda: CLOCK["t"]        # 시계를 손에 쥔다 — 350ms 를 재려면 필요하다

app = QApplication.instance() or QApplication(sys.argv)

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


U = Qt.ScrollPhase.ScrollUpdate
M = Qt.ScrollPhase.ScrollMomentum
B = Qt.ScrollPhase.ScrollBegin
N = Qt.ScrollPhase.NoScrollPhase


def make(tall=True):
    v = mv._PdfGraphicsView()
    sc = QGraphicsScene()
    sc.addRect(QRectF(0, 0, 700, 3000 if tall else 400))
    v.setScene(sc)
    v.resize(800, 600)
    v.show()
    app.processEvents()
    v._steps = []
    v.pageStep.connect(lambda d: v._steps.append(d))
    return v


def wheel(v, dy, phase=N, dt=8.0):
    CLOCK["t"] += dt
    ev = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(0, dy),
                     QPoint(0, dy), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, phase, False)
    v.wheelEvent(ev)


def key(v, k, mod=Qt.KeyboardModifier.NoModifier):
    v.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, k, mod))


def edge(v, where):
    sb = v.verticalScrollBar()
    sb.setValue(sb.minimum() if where == "top" else sb.maximum())
    v._edge_dir = 0
    v._edge_sum = 0
    v._fling = False
    v._user_dir = 0
    v._steps.clear()


def count_to_step(v, gen, limit=200, dt=8.0):
    """몇 건 만에 쪽이 넘어가나. 안 넘어가면 None."""
    for i in range(limit):
        dy, ph = gen(i)
        wheel(v, dy, ph, dt)
        if v._steps:
            return i + 1
    return None


# ── ① 관성만으로는 절대 쪽이 넘어가지 않는다 (§2.3 규칙 3) ────────────
v = make()
edge(v, "bottom")
n = count_to_step(v, lambda i: (-30, M))
chk(n is None, "① 관성 200건으로는 쪽이 넘어가지 않는다", "%s건에 넘어감" % n)

# ── ② 사람이 밀면 넘어간다 (§2.2 는 그대로) ───────────────────────────
edge(v, "bottom")
n = count_to_step(v, lambda i: (-16, U))
chk(n is not None and 20 <= n <= 80,
    "② 트랙패드로 밀면 한 박자 뒤 넘어간다", "n=%s" % n)
clean = n

# ── ③ ★ 관성이 섞여도 깨끗한 뒤집기와 **같은 값**에 넘어간다 ──────────
#   이것이 사용자가 보고한 바로 그 자리다.
edge(v, "top")
n_clean = count_to_step(v, lambda i: (+16, U))
edge(v, "top")
n_mixed = count_to_step(v, lambda i: (-12, M) if i % 3 == 0 else (+16, U))
chk(n_mixed is not None,
    "③ 관성이 섞인 채 뒤집어도 이전 쪽으로 넘어간다", "안 넘어감")
chk(n_mixed is not None and n_clean is not None and n_mixed <= n_clean * 1.3,
    "③ 관성이 있든 없든 드는 품이 거의 같다",
    "깨끗 %s건 / 섞임 %s건" % (n_clean, n_mixed))

# ── ④ 뒤집으면 앞 손짓의 관성은 취소된다 (§2.3 규칙 4) ────────────────
v2 = make()
sb2 = v2.verticalScrollBar()
sb2.setValue(500)
v2._fling = False
v2._user_dir = 0
wheel(v2, +16, U)                      # 사람이 위로 민다
pos = sb2.value()
wheel(v2, -400, M)                     # 앞 손짓(아래)의 관성이 크게 들어온다
chk(sb2.value() == pos,
    "④ 사람이 민 방향과 반대인 관성은 화면을 밀지 못한다",
    "%d → %d" % (pos, sb2.value()))
wheel(v2, +400, M)                     # 같은 방향 관성은 그대로 흐른다
chk(sb2.value() < pos, "④ 같은 방향 관성은 평소대로 스크롤한다",
    "%d → %d" % (pos, sb2.value()))

# ── ⑤ 손을 새로 얹으면(ScrollBegin) 경계는 처음부터 (§2.3 규칙 1) ─────
v3 = make()
edge(v3, "bottom")
wheel(v3, -16, U)
wheel(v3, -16, U)
chk(v3._edge_dir == +1 and v3._edge_sum > 0, "⑤ 밀면 경계가 쌓인다",
    "dir=%s sum=%s" % (v3._edge_dir, v3._edge_sum))
#   ScrollBegin 은 그 자체가 '경계에 처음 닿은 칸' 이기도 하다 — 쌓아 둔 양이
#   0 으로 돌아가고 시계가 다시 시작하는 것이 규칙이다.
CLOCK["t"] += 1000                      # 시계를 넉넉히 돌려 놓고
wheel(v3, -16, B)
chk(v3._edge_sum == 0, "⑤ 손을 새로 얹으면 쌓아 둔 양을 비운다",
    "sum=%s" % v3._edge_sum)
chk(abs(v3._edge_ms - CLOCK["t"]) < 1.0, "⑤ 그리고 한 박자 시계도 다시 시작한다",
    "edge_ms=%s now=%s" % (v3._edge_ms, CLOCK["t"]))

# ── ⑥ 위상 없는 고전 휠은 종전 그대로 (§2.3 규칙 5) ───────────────────
v4 = make()
edge(v4, "bottom")
n = count_to_step(v4, lambda i: (-120, N), dt=120)
chk(n is not None and n <= 6, "⑥ 고전 휠은 종전대로 몇 칸이면 넘어간다", "n=%s" % n)

# ── ⑦ 쪽 한가운데서 흔들어도 쪽은 안 넘어간다 ─────────────────────────
v5 = make()
sb5 = v5.verticalScrollBar()
sb5.setValue((sb5.minimum() + sb5.maximum()) // 2)
v5._steps.clear()
for i in range(60):
    wheel(v5, +16 if i % 2 == 0 else -16, U)
chk(not v5._steps, "⑦ 쪽 한가운데서 위아래로 흔들어도 쪽이 안 넘어간다",
    str(v5._steps))

# ── ⑧ 키보드 — 확대한 쪽은 안을 먼저 훑는다 (§3) ──────────────────────
v6 = make(tall=True)
sb6 = v6.verticalScrollBar()
sb6.setValue(sb6.minimum()); v6._steps.clear()
key(v6, Qt.Key.Key_Down)
chk(sb6.value() > sb6.minimum() and not v6._steps,
    "⑧ ↓ 는 쪽 안에서 한 칸 내려간다", "%d %s" % (sb6.value(), v6._steps))

sb6.setValue(sb6.minimum()); v6._steps.clear()
key(v6, Qt.Key.Key_Space)
chk(sb6.value() > sb6.minimum() and not v6._steps,
    "⑧ 빈칸은 한 화면 내려간다", "%d %s" % (sb6.value(), v6._steps))
one_line = None
sb6.setValue(sb6.minimum()); key(v6, Qt.Key.Key_Down); one_line = sb6.value()
sb6.setValue(sb6.minimum()); key(v6, Qt.Key.Key_Space)
chk(sb6.value() > one_line, "⑧ 빈칸이 ↓ 보다 많이 내려간다",
    "빈칸 %d / ↓ %d" % (sb6.value(), one_line))

sb6.setValue(sb6.maximum()); v6._steps.clear()
key(v6, Qt.Key.Key_Down)
chk(v6._steps == [1], "⑧ 아래끝에서 ↓ 는 다음 쪽", str(v6._steps))

sb6.setValue(sb6.minimum()); v6._steps.clear()
key(v6, Qt.Key.Key_Up)
chk(v6._steps == [-1], "⑧ 맨 위에서 ↑ 는 이전 쪽", str(v6._steps))

sb6.setValue((sb6.minimum() + sb6.maximum()) // 2); v6._steps.clear()
key(v6, Qt.Key.Key_PageDown)
chk(v6._steps == [1], "⑧ PageDown 은 한가운데서도 늘 쪽 단위", str(v6._steps))
sb6.setValue((sb6.minimum() + sb6.maximum()) // 2); v6._steps.clear()
key(v6, Qt.Key.Key_PageUp)
chk(v6._steps == [-1], "⑧ PageUp 도 늘 쪽 단위", str(v6._steps))

# ── ⑨ 쪽 맞춤(스크롤 자리 없음)은 **예전과 똑같다** ───────────────────
v7 = make(tall=False)
sb7 = v7.verticalScrollBar()
chk(sb7.maximum() == sb7.minimum(), "⑨ 쪽 맞춤에는 스크롤 자리가 없다",
    "%d..%d" % (sb7.minimum(), sb7.maximum()))
for k, want in ((Qt.Key.Key_Down, 1), (Qt.Key.Key_Up, -1),
                (Qt.Key.Key_Space, 1), (Qt.Key.Key_PageDown, 1)):
    v7._steps.clear()
    key(v7, k)
    chk(v7._steps == [want], "⑨ 자리가 없으면 곧바로 쪽 이동 (%s)" % k.name,
        str(v7._steps))

# ── ⑩ Home/End 는 문서 끝으로 ─────────────────────────────────────────
v7._steps.clear(); key(v7, Qt.Key.Key_Home)
chk(v7._steps and v7._steps[0] < -10 ** 5, "⑩ Home 은 첫 쪽", str(v7._steps))
v7._steps.clear(); key(v7, Qt.Key.Key_End)
chk(v7._steps and v7._steps[0] > 10 ** 5, "⑩ End 는 마지막 쪽", str(v7._steps))

mv._perf_ms = _real_perf
print()
print("=== ALL PASS ===" if not fails else "=== FAILURE (%d) ===" % len(fails))
for f in fails:
    print(" -", f)
sys.stdout.flush()
os._exit(1 if fails else 0)
