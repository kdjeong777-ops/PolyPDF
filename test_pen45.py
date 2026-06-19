# -*- coding: utf-8 -*-
"""260611-5: 펜 버튼 4·5 가 도구 설정·그리기 되는지 버튼 클릭 경로로 검증."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_p45_"))
d = fitz.open(); d.new_page(width=400, height=600).insert_text((40, 80), "x"); d.save(str(tmp/"P.pdf")); d.close()
(tmp/"bookmarks.json").write_text(json.dumps({"version":1,"bookmarks":[{"title":"P","file":"P.pdf","children":[]}]}),encoding="utf-8")

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(1100,800); mw.show(); app.processEvents()
mw.open_folder(tmp); app.processEvents()
mw._on_bookmark_activated(mw.bookmark_tree.ordered_pdf_files()[0],0); app.processEvents()
mv = mw._mv[0]
mv.set_draw_mode(True); app.processEvents()
print("draw_pens count:", len(mv._draw_pens), "pen_btns:", len(mv._draw_pen_btns))

_vp = mv.view.viewport()
def send(t,x,y,btns=Qt.MouseButton.LeftButton):
    QApplication.sendEvent(_vp, QMouseEvent(t,QPointF(x,y),Qt.MouseButton.LeftButton,btns,Qt.KeyboardModifier.NoModifier)); app.processEvents()

pr = mv._page_view_rect()
for i in range(5):
    mv._page_strokes = []
    mv.set_draw_line_mode(2)   # 자유곡선(가장 단순)
    mv._draw_pen_btns[i].click(); app.processEvents()   # 실제 버튼 클릭 경로
    tool_ok = (mv._draw_tool == ("pen", i))
    x0=pr.left()+int(pr.width()*0.2); x1=pr.left()+int(pr.width()*0.8); y=pr.top()+int(pr.height()*(0.3+0.1*i))
    send(QEvent.Type.MouseButtonPress,x0,y)
    send(QEvent.Type.MouseMove,(x0+x1)//2,y)
    send(QEvent.Type.MouseMove,x1,y)
    send(QEvent.Type.MouseButtonRelease,x1,y,Qt.MouseButton.NoButton)
    drew = len(mv._page_strokes) == 1
    chk(tool_ok and drew, f"펜 버튼 {i+1} → 도구설정+그리기", f"tool={mv._draw_tool} strokes={len(mv._page_strokes)}")

# 6) 펜 데이터가 3개뿐이어도 버튼 4·5 가 동작(패딩) — 패닝 안 됨
mw._prefs["draw_pens"] = [dict(p) for p in mv._draw_pens[:3]]   # 3개만
mw._init_draw_config(mv); app.processEvents()
chk(len(mv._draw_pens) >= 5, "3개 설정도 5개로 보충(pad)", f"n={len(mv._draw_pens)}")
for i in (3, 4):
    mv._page_strokes = []
    mv.set_draw_line_mode(2)
    mv._draw_pen_btns[i].click(); app.processEvents()
    x0=pr.left()+int(pr.width()*0.2); x1=pr.left()+int(pr.width()*0.8); y=pr.top()+int(pr.height()*0.4)
    send(QEvent.Type.MouseButtonPress,x0,y); send(QEvent.Type.MouseMove,x1,y)
    send(QEvent.Type.MouseButtonRelease,x1,y,Qt.MouseButton.NoButton)
    chk(len(mv._page_strokes) == 1, f"3펜 환경에서도 버튼 {i+1} 그리기", f"strokes={len(mv._page_strokes)}")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
