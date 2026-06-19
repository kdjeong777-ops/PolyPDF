# -*- coding: utf-8 -*-
"""260611-2: 오버레이가 실제로 '그려지는지'(paint) 픽셀로 검증."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent, QImage

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_paint_"))
d = fitz.open()
pg = d.new_page(width=400, height=600); pg.insert_text((40, 80), "hello world")
d.save(str(tmp / "P.pdf")); d.close()
(tmp / "bookmarks.json").write_text(
    json.dumps({"version": 1, "bookmarks": [{"title": "P", "file": "P.pdf", "children": []}]}),
    encoding="utf-8")

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(1100, 800); mw.show(); app.processEvents()
mw.open_folder(tmp); app.processEvents()
mw._on_bookmark_activated(mw.bookmark_tree.ordered_pdf_files()[0], 0); app.processEvents()
mv = mw._mv[0]
mv.set_draw_mode(True); app.processEvents()
mv.set_draw_line_mode(0); mv.set_draw_tool(("pen", 0))   # 빨강 직선
pr = mv._page_view_rect()
print("page rect:", pr and (pr.left(), pr.top(), pr.width(), pr.height()))

_vp = mv.view.viewport()
def send(t, x, y, btns=Qt.MouseButton.LeftButton):
    ev = QMouseEvent(t, QPointF(x, y), Qt.MouseButton.LeftButton, btns,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(_vp, ev); app.processEvents()

y = pr.top() + int(pr.height() * 0.5)
x0 = pr.left() + int(pr.width() * 0.15); x1 = pr.left() + int(pr.width() * 0.85)
send(QEvent.Type.MouseButtonPress, x0, y)
send(QEvent.Type.MouseMove, x1, y)
send(QEvent.Type.MouseButtonRelease, x1, y, Qt.MouseButton.NoButton)
app.processEvents()
chk(len(mv._page_strokes) == 1, "스트로크 생성", f"n={len(mv._page_strokes)}")

print("stroke[0]:", mv._page_strokes[0])
ov = mv._draw_overlay
chk(ov.parent() is mv.view, "오버레이가 self.view 자식(합성 안정)")
mv._position_draw_overlay()
# 페인트 호출/계산 추적
import types
orig_paint = ov.paintEvent
calls = {"n": 0, "pr": None, "vp": None}
def traced(e):
    calls["n"] += 1
    calls["pr"] = ov._pr()
    if mv._page_strokes:
        prr = ov._pr()
        if prr is not None:
            calls["vp"] = [ov._to_view(x, y, prr) for x, y in mv._page_strokes[0]["points"]]
    return orig_paint(e)
ov.paintEvent = traced
app.processEvents()
pm = ov.grab()
print("paint calls:", calls["n"], "pr:", calls["pr"] and (calls['pr'].left(),calls['pr'].top(),calls['pr'].width(),calls['pr'].height()),
      "viewpts:", calls["vp"] and [(p.x(),p.y()) for p in calls["vp"]])
img = pm.toImage()
# 그린 선 영역에서 빨강(불투명) 픽셀 탐색
found = 0; sample = None
vps = calls["vp"]
yy = int(vps[0].y()); xa = int(vps[0].x()); xb = int(vps[-1].x())
for xx in range(min(xa, xb) + 4, max(xa, xb) - 4, 3):
    for dy in (-1, 0, 1):
        c = img.pixelColor(xx, yy + dy)
        if c.alpha() > 40 and c.red() > 120 and c.green() < 120 and c.blue() < 120:
            found += 1
            if sample is None: sample = (xx, yy + dy, c.red(), c.green(), c.blue(), c.alpha())
            break
chk(found >= 3, "오버레이에 빨강 선이 실제로 그려짐(paint)",
    f"hits={found} sample={sample} ovsize=({ov.width()}x{ov.height()})")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
