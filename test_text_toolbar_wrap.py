# -*- coding: utf-8 -*-
"""261008-3: 텍스트 창 단추줄 — 폭이 좁으면 단추가 잘리지 않고 아래 줄로 흐른다 (디자인 SOT §2.8.4, 텍스트 창 SOT §2).

사용자 요청: "텍스트 창 단추도 같은 방식으로" (스크린샷 창 머리줄 261008-2 와 같은 방식)
(종전: '스타일 적용'·'OCR 다시 읽기'·'하이라이트'·'PDF 에 반영' 이 '타일 적'·'R 다시 읽' 처럼 잘렸다.)

A. 좁은 폭 — 둘째·셋째 줄의 모든 위젯이 제 폭 그대로, 칸 안에, 겹치지 않고, 줄이 늘어난다
B. '자간 [값]'·'줄간격 [값]' 은 한 덩어리 — 이름과 칸이 같은 줄
C. 넓은 폭 — 각 줄이 한 줄로 돌아온다
"""
import os, sys, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(120, exit=True)

from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QLabel
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


def items(bar):
    lay = bar.layout()
    return [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]


try:
    from viewer.widgets.text_panel import TextPanel
    tp = TextPanel()
    tp.resize(900, 600); tp.show(); spin()
    wide_rows = {k: len({w.geometry().center().y() for w in items(b)}) for k, b in
                 (("bar2", tp.bar2_widget), ("bar3", tp.bar3_widget))}
    chk(wide_rows == {"bar2": 1, "bar3": 1}, "준비 — 넓으면 각 한 줄", str(wide_rows))

    tp.resize(300, 600); spin()
    for name, bar in (("둘째 줄", tp.bar2_widget), ("셋째 줄", tp.bar3_widget)):
        ws = items(bar)
        W = bar.width()
        rects = [w.geometry() for w in ws]
        chk(all(w.width() >= w.sizeHint().width() for w in ws),
            f"A {name}: 위젯이 제 폭 그대로(글자가 잘리지 않는다)",
            str([(w.width(), w.sizeHint().width()) for w in ws if w.width() < w.sizeHint().width()]))
        chk(all(r.left() >= 0 and r.right() <= W for r in rects), f"A {name}: 모두 칸 안에", f"W={W}")
        chk(all(not rects[i].intersects(rects[j]) for i in range(len(rects)) for j in range(i + 1, len(rects))),
            f"A {name}: 겹치지 않는다")
        chk(len({r.center().y() for r in rects}) >= 2, f"A {name}: 아래 줄로 흐른다")
    chk(tp.bar3_widget.geometry().bottom() < tp.info.geometry().top() + 1
        and tp.bar2_widget.geometry().bottom() < tp.bar3_widget.geometry().top() + 1,
        "A 줄이 늘어나도 아래 칸과 겹치지 않는다")
    for spn, label in ((tp.sp_sp, "자간"), (tp.sp_ls, "줄간격")):
        box = spn.parentWidget()
        lab = [c for c in box.findChildren(QLabel) if c.text() == label]
        chk(box is not tp.bar2_widget and lab and box.layout().indexOf(spn) >= 0,
            f"B '{label}' 이름과 칸이 한 덩어리")
    tp.resize(900, 600); spin()
    rows = {k: len({w.geometry().center().y() for w in items(b)}) for k, b in
            (("bar2", tp.bar2_widget), ("bar3", tp.bar3_widget))}
    chk(rows == {"bar2": 1, "bar3": 1}, "C 넓히면 한 줄로 돌아온다", str(rows))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
