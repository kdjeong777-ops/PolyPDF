# -*- coding: utf-8 -*-
"""261008-2: 스크린샷 창 머리줄 — 폭이 좁으면 단추가 잘리지 않고 아래 줄로 흐른다 (디자인 SOT §2.8.4, 스크린샷 SOT §4).

사용자 요청: "버튼이 잘리지 않게 창폭이 좁으면 아래로 흘러서 표시되도록 수정"
(종전: 한 줄 QHBoxLayout 이 단추를 최소 폭 아래로 눌러 '클립보드 가져' 처럼 글자가 잘렸다.)

A. 좁은 폭 — 모든 단추가 제 폭(sizeHint) 그대로, 칸 안에, 서로 겹치지 않고, 두 줄 이상
B. 접힌 모드 높이 한도(§2.8.2)가 늘어난 머리줄만큼 커져 목록이 잘리지 않는다
C. 넓은 폭 — 한 줄로 돌아오고 높이 한도도 줄어든다
"""
import os, sys, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(120, exit=True)

from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=6):
    for _ in range(n):
        app.processEvents(); QTest.qWait(15)


try:
    from viewer.widgets.strip import MiniStrip
    btns = [QPushButton("📥 클립보드 가져오기"), QPushButton("📋 클립보드로 복사"), QPushButton("💾 PDF 저장")]
    strip = MiniStrip("🖼 스크린샷", max_items=30, draggable=True, extra_widgets=btns)
    strip.resize(1000, 200); strip.show(); spin()
    strip._fit_height(False); spin()
    wide_head = strip.head_widget.height()
    wide_max = strip.maximumHeight()

    strip.resize(260, strip.height()); spin()
    W = strip.head_widget.width()
    rects = [b.geometry() for b in btns + [strip.clear_btn]]
    chk(all(b.width() >= b.sizeHint().width() for b in btns),
        "A 좁아도 단추가 제 폭 그대로(글자가 잘리지 않는다)", str([(b.width(), b.sizeHint().width()) for b in btns]))
    chk(all(r.right() <= W and r.left() >= 0 for r in rects), "A 모든 단추가 칸 안에 있다", f"W={W} {[(r.left(), r.right()) for r in rects]}")
    chk(all(not rects[i].intersects(rects[j]) for i in range(len(rects)) for j in range(i + 1, len(rects))),
        "A 단추끼리 겹치지 않는다")
    rows = len({r.top() for r in rects})
    chk(rows >= 2 and strip.head_widget.height() > wide_head, "A 아래 줄로 흐른다", f"rows={rows} h={strip.head_widget.height()}")
    chk(strip.maximumHeight() > wide_max, "B 접힌 모드 높이 한도가 머리줄 만큼 커진다", f"{strip.maximumHeight()} vs {wide_max}")
    strip.resize(260, strip.maximumHeight()); spin()          # 분할자가 한도만큼 높이를 준다
    chk(strip.list.geometry().bottom() <= strip.height(), "B 한도 안에서 목록이 칸 밖으로 잘리지 않는다",
        f"{strip.list.geometry().bottom()} vs {strip.height()}")

    strip.resize(1000, strip.height()); spin()
    rects = [b.geometry() for b in btns]
    chk(len({r.top() for r in rects}) == 1 and strip.maximumHeight() == wide_max,
        "C 넓히면 한 줄로 돌아오고 높이 한도도 줄어든다", f"{strip.maximumHeight()} vs {wide_max}")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
