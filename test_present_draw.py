# -*- coding: utf-8 -*-
"""260611-4: 발표 그리기 3단계(직선/하이라이트/자유) + 공유 동기 검증."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF, QPoint, QEvent
from PyQt6.QtGui import QMouseEvent

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_pdraw_"))
d = fitz.open()
pg = d.new_page(width=400, height=600)
for ln in range(10):
    pg.insert_text((40, 80 + ln * 40), f"line {ln} sample text here")
d.save(str(tmp / "P.pdf")); d.close()

app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.presentation import PresentationWindow
from viewer.widgets.main_view import MV_DEFAULT_PENS
pw = PresentationWindow(str(tmp / "P.pdf"), 0, None, pens=[dict(p) for p in MV_DEFAULT_PENS],
                        line_mode=0, highlight_alpha=40)
pw.resize(800, 600); pw.show(); app.processEvents()

# 1) 초기 직선 모드 + 순환
chk(pw._line_mode == 0 and pw._tb_mode.text() == "─", "발표 초기 직선(─)")
pw._cycle_line_mode(); app.processEvents()
chk(pw._line_mode == 1 and pw._tb_mode.text() == "▬", "발표 순환1 하이라이트(▬)")
pw._cycle_line_mode(); app.processEvents()
chk(pw._line_mode == 2 and pw._tb_mode.text() == "〜", "발표 순환2 자유(〜)")
pw._cycle_line_mode(); app.processEvents()
chk(pw._line_mode == 0, "발표 순환3 직선 복귀")

# 2) 펜 선택 후 하이라이트 그리기 → hl 스트로크 + 줄높이
pw._set_pen(2); pw.set_line_mode(1)
rect = pw._page_norm_rect(0)   # (x0,y0,w,h)
x0, y0, w, h = rect
yy = int(y0 + h * (80.0 / 600.0))
xa = int(x0 + w * 0.2); xb = int(x0 + w * 0.8)
def mev(t, x, y, btn=Qt.MouseButton.LeftButton, btns=Qt.MouseButton.LeftButton):
    return QMouseEvent(t, QPointF(x, y), btn, btns, Qt.KeyboardModifier.NoModifier)
pw.mousePressEvent(mev(QEvent.Type.MouseButtonPress, xa, yy))
pw.mouseMoveEvent(mev(QEvent.Type.MouseMove, xb, yy))
pw.mouseReleaseEvent(mev(QEvent.Type.MouseButtonRelease, xb, yy, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
app.processEvents()
strokes = pw._strokes.get(0, [])
hl = [s for s in strokes if s.get("hl")]
chk(len(hl) == 1, "발표 하이라이트 스트로크 생성", f"n={len(strokes)}")
if hl:
    chk(hl[0].get("h", 0) > 0, "발표 하이라이트 줄높이(h)", str(hl[0].get("h")))
    chk(hl[0]["color"] == pw._pens[2]["color"], "발표 하이라이트 펜색 사용")

# 3) 직선 그리기(수평)
pw._strokes.clear()
pw._set_pen(0); pw.set_line_mode(0)
yy2 = int(y0 + h * 0.5)
pw.mousePressEvent(mev(QEvent.Type.MouseButtonPress, xa, yy2))
pw.mouseMoveEvent(mev(QEvent.Type.MouseMove, xb, yy2 + 25))
pw.mouseReleaseEvent(mev(QEvent.Type.MouseButtonRelease, xb, yy2 + 25, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
app.processEvents()
ln = [s for s in pw._strokes.get(0, []) if not s.get("hl")]
chk(len(ln) == 1, "발표 직선 스트로크 1개", f"n={len(ln)}")
if ln:
    pts = ln[0]["points"]
    chk(pts[0].y() == pts[-1].y(), "발표 직선=수평")

# 4) 정규화에 hl/h 보존
pw._strokes.clear()
pw._set_pen(1); pw.set_line_mode(1)
pw.mousePressEvent(mev(QEvent.Type.MouseButtonPress, xa, yy))
pw.mouseMoveEvent(mev(QEvent.Type.MouseMove, xb, yy))
pw.mouseReleaseEvent(mev(QEvent.Type.MouseButtonRelease, xb, yy, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
norm = pw._normalized_strokes()
flat = [s for v in norm.values() for s in v]
chk(any(s.get("hl") and 0 < s.get("h", 0) <= 1 for s in flat),
    "정규화 스트로크에 hl/h(0..1) 보존", str(flat[:1]))

pw.close()
print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
