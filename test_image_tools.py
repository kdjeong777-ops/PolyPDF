# -*- coding: utf-8 -*-
"""260611-16: 개체선택 버튼·펜 토글·이미지 우선·빈곳 비활성화·호버 커서."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QColor, QMouseEvent
from PyQt6.QtCore import Qt, QPointF, QPoint, QEvent

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_itool_"))
d = fitz.open(); d.new_page(width=400, height=600).insert_text((40, 80), "p")
d.save(str(tmp / "T.pdf")); d.close()
(tmp / "bookmarks.json").write_text(
    json.dumps({"version": 1, "bookmarks": [{"title": "T", "file": "T.pdf", "children": []}]}),
    encoding="utf-8")

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(1100, 800); mw.show(); app.processEvents()
mw.open_folder(tmp); app.processEvents()
mw._on_bookmark_activated(mw.bookmark_tree.ordered_pdf_files()[0], 0); app.processEvents()
mv = mw._mv[0]
mv.set_draw_mode(True); app.processEvents()
pr = mv._page_view_rect()
_vp = mv.view.viewport()

# 1) 개체선택 버튼 토글
chk(hasattr(mv, "_draw_select_btn"), "개체선택 버튼 존재")
mv._on_draw_select()
chk(mv._draw_tool == ("select", None) and mv._draw_select_btn.isChecked(), "개체선택 ON")
mv._on_draw_select()
chk(mv._draw_tool is None and not mv._draw_select_btn.isChecked(), "개체선택 재클릭 → OFF(토글)")

# 2) 펜 버튼 토글(요청5)
mv._on_draw_pen(0)
chk(mv._draw_tool == ("pen", 0), "펜0 ON")
mv._on_draw_pen(0)
chk(mv._draw_tool is None, "같은 펜 재클릭 → OFF(토글)")

# 이미지 1개 삽입(중앙)
mv.add_image_from_pixmap((lambda: (lambda p: (p.fill(QColor('#00aa00')), p)[1])(QPixmap(80, 40)))())
app.processEvents()
ix = mv._img_objects[0]["rect"]
cx = pr.left() + int((ix[0] + ix[2] / 2) * pr.width())
cy = pr.top() + int((ix[1] + ix[3] / 2) * pr.height())

def press(x, y):
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(_vp, ev); app.processEvents()

# 3) 펜이 눌린 상태에서도 이미지 위를 누르면 이미지 우선(선 작업 비활성)(요청1)
mv.set_draw_tool(("pen", 0)); mv._img_selected = -1
mv._page_strokes = []
press(cx, cy)
chk(mv._img_selected == 0, "펜 활성이어도 이미지 클릭 → 이미지 선택(우선)")
chk(len(mv._page_strokes) == 0, "이미지 클릭은 선이 안 그려짐")
mv._img_mouse_release()

# 4) 활성 개체 있을 때 빈 곳 클릭 → 개체 비활성화(요청3), 그 클릭으로 그리기 안 함(요청1)
mv._img_selected = 0
ex = pr.left() + int(pr.width() * 0.02); ey = pr.top() + int(pr.height() * 0.02)  # 모서리 빈 곳
press(ex, ey)
chk(mv._img_selected == -1, "빈 곳 클릭 → 활성 개체 비활성화")

# 5) 호버 커서 — 핸들/개체 위 커서 변경(요청2)
mv._img_selected = 0
mv._img_update_hover_cursor(QPoint(cx, cy), pr)
chk(_vp.cursor().shape() == Qt.CursorShape.SizeAllCursor, "개체 위 호버 → 이동 커서")
rect = mv._draw_overlay._img_rect_view(mv._img_objects[0], pr)
tl = rect.topLeft()
mv._img_update_hover_cursor(QPoint(int(tl.x()), int(tl.y())), pr)
chk(_vp.cursor().shape() == Qt.CursorShape.SizeFDiagCursor, "좌상단 핸들 호버 → 대각 리사이즈 커서")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
