# -*- coding: utf-8 -*-
"""260611-6: 발표 지우개가 선 중간도 지우는지 + 썸네일 패널 포인터/배경."""
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

tmp = Path(tempfile.mkdtemp(prefix="polypdf_perase_"))
d = fitz.open()
for i in range(3):
    pg = d.new_page(width=400, height=600)
    for ln in range(6): pg.insert_text((40, 90 + ln*60), f"line {ln} text")
d.save(str(tmp/"P.pdf")); d.close()

app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.presentation import PresentationWindow
from viewer.widgets.main_view import MV_DEFAULT_PENS
pw = PresentationWindow(str(tmp/"P.pdf"), 0, None, pens=[dict(p) for p in MV_DEFAULT_PENS],
                        eraser_widths=[12,30], line_mode=0)
pw.resize(800,600); pw.show(); app.processEvents()

def mev(t,x,y,btn=Qt.MouseButton.LeftButton,btns=Qt.MouseButton.LeftButton):
    return QMouseEvent(t,QPointF(x,y),btn,btns,Qt.KeyboardModifier.NoModifier)

# 직선 1개 그림(끝점 2개만 → 중간엔 점 없음)
pw._set_pen(0); pw.set_line_mode(0)
y = 300
pw.mousePressEvent(mev(QEvent.Type.MouseButtonPress, 150, y))
pw.mouseMoveEvent(mev(QEvent.Type.MouseMove, 650, y))
pw.mouseReleaseEvent(mev(QEvent.Type.MouseButtonRelease, 650, y, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
app.processEvents()
chk(len(pw._strokes.get(0,[]))==1, "직선 1개 생성", f"n={len(pw._strokes.get(0,[]))}")

# 지우개(얇게)로 선의 '중간'(x=400, 점 없음) 문지름 → 지워져야
pw._set_eraser(0)   # 얇게
pw._erasing = True
pw._erase_at(QPoint(400, y))
app.processEvents()
chk(len(pw._strokes.get(0,[]))==0, "얇은 지우개가 직선 중간(점 없음)도 지움",
    f"n={len(pw._strokes.get(0,[]))}")

# 다시 직선 + 굵은 지우개로 약간 빗나간 위치(중간, y±10)도 지워지는지
pw._set_pen(0); pw.set_line_mode(0)
pw.mousePressEvent(mev(QEvent.Type.MouseButtonPress, 150, y))
pw.mouseMoveEvent(mev(QEvent.Type.MouseMove, 650, y))
pw.mouseReleaseEvent(mev(QEvent.Type.MouseButtonRelease, 650, y, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
pw._set_eraser(1)   # 두껍게
pw._erase_at(QPoint(420, y+12))   # 선에서 12px 떨어진 중간
chk(len(pw._strokes.get(0,[]))==0, "굵은 지우개가 선 근처(중간) 지움",
    f"n={len(pw._strokes.get(0,[]))}")

# 멀리(80px) 떨어진 곳은 안 지워짐
pw._set_pen(0)
pw.mousePressEvent(mev(QEvent.Type.MouseButtonPress, 150, y))
pw.mouseMoveEvent(mev(QEvent.Type.MouseMove, 650, y))
pw.mouseReleaseEvent(mev(QEvent.Type.MouseButtonRelease, 650, y, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
pw._erase_at(QPoint(400, y+80))
chk(len(pw._strokes.get(0,[]))==1, "멀리(80px) 떨어지면 안 지워짐",
    f"n={len(pw._strokes.get(0,[]))}")

# 썸네일 패널: 배경 40% 불투명 검정 + 일반 화살표 커서
tp = pw._thumb_panel
chk("#3c3c3c" in tp.styleSheet(), "패널 배경 일반 회색", tp.styleSheet())
chk(tp.cursor().shape() == Qt.CursorShape.ArrowCursor, "패널 일반 화살표 커서")
chk(tp.list.cursor().shape() == Qt.CursorShape.ArrowCursor, "패널 리스트 화살표 커서")

pw.close()
print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
