# -*- coding: utf-8 -*-
"""260611-7: 발표 상하2분할 — 반쪽별 선 분리 + 페이지 왕복 보존 + 방향키 포커스."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication, QPushButton, QListWidget
from PyQt6.QtCore import Qt, QPointF, QPoint, QEvent
from PyQt6.QtGui import QMouseEvent

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_split_"))
d = fitz.open()
for i in range(3):
    pg = d.new_page(width=400, height=700)   # 세로로 긴 페이지(분할 대상)
    pg.insert_text((40, 100), f"page {i}")
d.save(str(tmp/"P.pdf")); d.close()

app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.presentation import PresentationWindow
from viewer.widgets.main_view import MV_DEFAULT_PENS
pw = PresentationWindow(str(tmp/"P.pdf"), 0, None, pens=[dict(p) for p in MV_DEFAULT_PENS],
                        split_mode=True, eraser_widths=[12,30], line_mode=2)
pw.resize(800,600); pw.show(); app.processEvents()
# 260611-27: 분할 기본값은 방향(세로>가로)으로 결정 — 세로 페이지면 기본 ON
chk(pw._split_mode and pw._page_is_split(), "세로 페이지 → 상하2분할 기본 ON")

def draw(x0,y0,x1,y1):
    pw.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress,QPointF(x0,y0),Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
    pw.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove,QPointF(x1,y1),Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
    pw.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease,QPointF(x1,y1),Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier))
    app.processEvents()

# 상부(half=0)에서 그림
pw._split_half = 0; pw._set_pen(0); pw.set_line_mode(2)
draw(150,150,400,150)
s = pw._strokes.get(0, [])
chk(len(s)==1 and s[0].get("half")==0, "상부 선 half=0 기록", f"{[x.get('half') for x in s]}")

# 하부(half=1)로 이동 후 그림
pw._split_half = 1
draw(150,400,400,400)
s = pw._strokes.get(0, [])
chk(len(s)==2 and sorted(x.get("half") for x in s)==[0,1], "하부 선 half=1 기록")

# 하부에서 상부 선(half=0) 위치를 지워도 안 지워짐(다른 반쪽 보존)
pw._set_eraser(1)
pw._erase_at(QPoint(250,150))   # 상부 선 위치
chk(len([x for x in pw._strokes.get(0,[]) if x.get("half")==0])==1,
    "하부에서 상부 선은 안 지워짐(반쪽 분리)")
# 하부 선은 하부에서 지워짐
pw._erase_at(QPoint(250,400))
chk(len([x for x in pw._strokes.get(0,[]) if x.get("half")==1])==0, "하부에서 하부 선은 지워짐")

# 페이지 왕복 후에도 선 보존(없어지지 않음)
n_before = len(pw._strokes.get(0, []))
pw._go(1); app.processEvents(); pw._go(0); app.processEvents()
chk(len(pw._strokes.get(0, [])) == n_before and n_before >= 1,
    "다른 페이지 왕복 후 선 보존", f"before={n_before} after={len(pw._strokes.get(0,[]))}")

# 방향키 포커스 — 버튼/리스트 NoFocus, 창 StrongFocus
btns = pw.findChildren(QPushButton)
chk(btns and all(b.focusPolicy()==Qt.FocusPolicy.NoFocus for b in btns),
    f"툴바 버튼 {len(btns)}개 NoFocus")
lists = pw.findChildren(QListWidget)
chk(all(l.focusPolicy()==Qt.FocusPolicy.NoFocus for l in lists), "썸네일 리스트 NoFocus")
chk(pw.focusPolicy()==Qt.FocusPolicy.StrongFocus, "창 StrongFocus")

# 패널 배경 일반 회색(투명 없음)
chk("#3c3c3c" in pw._thumb_panel.styleSheet() and "rgba" not in pw._thumb_panel.styleSheet(),
    "패널 배경 일반 회색(투명 없음)", pw._thumb_panel.styleSheet())

pw.close()

# 260611-26: 가로 페이지 PDF → 상하2분할 기본 ON
tmpL = Path(tempfile.mkdtemp(prefix="polypdf_land_"))
dL = fitz.open(); dL.new_page(width=700, height=400).insert_text((40, 80), "L")  # 가로>세로
dL.save(str(tmpL/"L.pdf")); dL.close()
pwL = PresentationWindow(str(tmpL/"L.pdf"), 0, None, pens=[dict(p) for p in MV_DEFAULT_PENS],
                         eraser_widths=[12,30], line_mode=2)
chk(not pwL._split_mode and not pwL._page_is_split(), "가로 페이지 → 상하2분할 기본 OFF")
pwL.set_split(True)   # 토글을 켜도 가로 페이지는 그 페이지만 분할 해제(260611-28)
chk(not pwL._page_is_split(), "가로 페이지는 토글 ON이어도 분할 해제")
chk(hasattr(pwL, "overlapChanged") and hasattr(pwL, "_on_overlap_spin"),
    "중앙겹침 입력(overlapChanged/_on_overlap_spin) 존재")
ov_emit = []
pwL.overlapChanged.connect(lambda v: ov_emit.append(v))
pwL._on_overlap_spin(25)
chk(abs(pwL._overlap_frac - 0.25) < 1e-6 and ov_emit == [25], "중앙겹침 입력 → 반영+영속 시그널")
pwL.close()

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
