# -*- coding: utf-8 -*-
"""260611-1: 본문 선긋기 개편 — 5펜·색배경·직선/하이라이트·우클릭설정 검증."""
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

# 텍스트가 있는 PDF 1개 폴더
tmp = Path(tempfile.mkdtemp(prefix="polypdf_draw_"))
d = fitz.open()
for i in range(2):
    pg = d.new_page(width=400, height=600)
    for ln in range(8):
        pg.insert_text((40, 80 + ln * 40), f"Line {ln} on page {i+1} sample text")
d.save(str(tmp / "T.pdf")); d.close()
(tmp / "bookmarks.json").write_text(
    json.dumps({"version": 1, "bookmarks": [{"title": "T", "file": "T.pdf", "children": []}]}),
    encoding="utf-8")

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
from viewer.widgets.main_view import MV_DEFAULT_PENS
mw = MainWindow(); mw.resize(1200, 800); mw.show(); app.processEvents()
mw.open_folder(tmp); app.processEvents()
files = mw.bookmark_tree.ordered_pdf_files()
mw._on_bookmark_activated(files[0], 0); app.processEvents()
mv = mw._mv[0]

# 1) 펜 5개 + 색배경
chk(len(MV_DEFAULT_PENS) == 5, "기본 펜 5개")
chk(len(mv._draw_pen_btns) == 5, "선긋기 버튼 5개", f"n={len(mv._draw_pen_btns)}")
css0 = mv._draw_pen_btns[0].styleSheet()
chk("rgba(" in css0 and "background" in css0, "버튼 배경에 색·투명도(rgba)", css0[:60])

# 2) 선 종류 3단계 순환(직선→하이라이트→자유곡선)
mv.set_draw_mode(True); app.processEvents()
chk(mv._draw_line_mode == 0 and mv._draw_mode_btn.text() == "─", "초기 직선 모드(─)")
mv._cycle_draw_mode(); app.processEvents()
chk(mv._draw_line_mode == 1 and mv._draw_mode_btn.text() == "▬", "순환1 하이라이트(▬)")
mv._cycle_draw_mode(); app.processEvents()
chk(mv._draw_line_mode == 2 and mv._draw_mode_btn.text() == "〜", "순환2 자유곡선(〜)")
mv._cycle_draw_mode(); app.processEvents()
chk(mv._draw_line_mode == 0, "순환3 다시 직선")

# 3) 하이라이트 줄 높이 탐지(텍스트 줄 bbox)
band = mv._hl_band_at(0.3, 80.0 / 600.0)   # 첫 줄 근처
chk(band is not None and band[1] > band[0], "줄 높이 탐지(band)", str(band))

# 4) 오버레이로 실제 하이라이트 스트로크 생성
ov = mv._draw_overlay
pr = mv._page_view_rect()
chk(pr is not None and pr.width() > 0, "페이지 렌더 사각형 존재", str(pr and (pr.width(), pr.height())))

# 260611-1: 실제 라우팅(뷰포트 eventFilter→오버레이) 검증 — sendEvent 사용
_vp = mv.view.viewport()
def send(t, x, y, btns=Qt.MouseButton.LeftButton):
    ev = QMouseEvent(t, QPointF(x, y), Qt.MouseButton.LeftButton, btns,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(_vp, ev); app.processEvents()

mv.set_draw_line_mode(1)                         # 하이라이트
mv.set_draw_tool(("pen", 2)); mv._update_draw_buttons()
y0 = pr.top() + int(pr.height() * (80.0 / 600.0))
x_s = pr.left() + int(pr.width() * 0.1)
x_e = pr.left() + int(pr.width() * 0.7)
send(QEvent.Type.MouseButtonPress, x_s, y0)
send(QEvent.Type.MouseMove, x_e, y0)
send(QEvent.Type.MouseButtonRelease, x_e, y0, Qt.MouseButton.NoButton)
hl = [s for s in mv._page_strokes if s.get("hl")]
chk(len(hl) == 1, "하이라이트 스트로크 1개 저장", f"strokes={len(mv._page_strokes)}")
if hl:
    s = hl[0]
    chk("h" in s and s["h"] > 0, "하이라이트 띠 높이 h 저장", str(s.get("h")))
    chk(s.get("color") == mv._draw_pens[2]["color"], "펜3 색 사용",
        f'{s.get("color")} vs {mv._draw_pens[2]["color"]}')

# 5) 직선 스트로크(수평) 생성
mv.set_draw_line_mode(0)                          # 직선
mv.set_draw_tool(("pen", 0))
y1 = pr.top() + int(pr.height() * 0.5)
send(QEvent.Type.MouseButtonPress, x_s, y1)
send(QEvent.Type.MouseMove, x_e, y1 + 20)
send(QEvent.Type.MouseButtonRelease, x_e, y1 + 20, Qt.MouseButton.NoButton)
ln = [s for s in mv._page_strokes if not s.get("hl")]
chk(len(ln) == 1, "직선 스트로크 1개", f"n={len(ln)}")
if ln:
    pts = ln[0]["points"]
    chk(abs(pts[0][1] - pts[1][1]) < 1e-6, "직선=수평(시작 y 고정)", str(pts))

# 6) 저장/로드 — page_meta 영속
mv._save_page_strokes(); app.processEvents()
loaded = mw._drawings_for(str(files[0]), 0)
chk(len([s for s in loaded if s.get("hl")]) == 1
    and len([s for s in loaded if not s.get("hl")]) == 1,
    "page_meta 저장·로드(하이라이트+직선)", f"loaded={len(loaded)}")

# 7) 우클릭 설정 다이얼로그 왕복(5펜 + 지우개면적 + 투명도 반전)
from viewer.widgets.pen_settings_dialog import MainDrawSettingsDialog
src = [dict(p) for p in (mw._prefs.get("draw_pens") or MV_DEFAULT_PENS)]
src[0]["alpha"] = 100   # 불투명 → 다이얼로그 투명도 0% 로 보여야
dlg = MainDrawSettingsDialog(src, mw, eraser_widths=[14, 33], highlight_alpha=40)
rp = dlg.result_pens()
chk(len(rp) == 5 and all("color" in p and "width" in p and "alpha" in p for p in rp),
    "설정 다이얼로그 5펜 결과", f"n={len(rp)}")
chk(dlg._rows[0][2].value() == 0, "투명도 표시 반전(불투명100→투명도0%)",
    f"shown={dlg._rows[0][2].value()}")
chk(rp[0]["alpha"] == 100, "저장 시 불투명도 복원(투명도0→alpha100)", f'{rp[0]["alpha"]}')
chk(dlg.result_eraser_widths() == [14, 33], "지우개 면적 왕복")
chk(dlg.result_highlight_alpha() == 40, "하이라이트 투명도 왕복")

# 7b) 지우개 — 직선 '중간'(점 없는 구간)도 지워지는지
mv.set_draw_line_mode(0); mv.set_draw_tool(("pen", 0))
mv._page_strokes = []
send(QEvent.Type.MouseButtonPress, pr.left()+int(pr.width()*0.1), pr.top()+int(pr.height()*0.3))
send(QEvent.Type.MouseMove, pr.left()+int(pr.width()*0.9), pr.top()+int(pr.height()*0.3))
send(QEvent.Type.MouseButtonRelease, pr.left()+int(pr.width()*0.9), pr.top()+int(pr.height()*0.3), Qt.MouseButton.NoButton)
before = len(mv._page_strokes)
mv.set_draw_tool(("erase", 20))
midx = pr.left()+int(pr.width()*0.5); midy = pr.top()+int(pr.height()*0.3)  # 선 중간
send(QEvent.Type.MouseButtonPress, midx, midy)
send(QEvent.Type.MouseButtonRelease, midx, midy, Qt.MouseButton.NoButton)
chk(before == 1 and len(mv._page_strokes) == 0,
    "지우개가 직선 중간에서도 지움", f"before={before} after={len(mv._page_strokes)}")

# 8) set_main_pens 가 버튼 색 갱신
mv.set_draw_tool(None)
newpens = [dict(p) for p in MV_DEFAULT_PENS]
newpens[0]["color"] = "#112233"
mv.set_main_pens(newpens)
chk("17,34,51" in mv._draw_pen_btns[0].styleSheet() or "112233" in mv._draw_pen_btns[0].styleSheet().lower()
    or "rgba(17,34,51" in mv._draw_pen_btns[0].styleSheet(),
    "set_main_pens → 버튼1 색 갱신", mv._draw_pen_btns[0].styleSheet()[:70])

# 9) 지우개·청소 버튼 아이콘 적용
eb = mv._draw_erase_btns
chk(len(eb) == 2 and all(not b.icon().isNull() for b in eb),
    "지우개 2버튼 아이콘 적용", f"icons={[not b.icon().isNull() for b in eb]}")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
