# -*- coding: utf-8 -*-
"""260611-2: 본문·발표 선긋기 통일 + 편집모드→전체화면 실행 검증."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_uni_"))
d = fitz.open()
for i in range(2):
    pg = d.new_page(width=400, height=600); pg.insert_text((40, 80), f"page {i+1}")
d.save(str(tmp / "U.pdf")); d.close()
(tmp / "bookmarks.json").write_text(
    json.dumps({"version": 1, "bookmarks": [{"title": "U", "file": "U.pdf", "children": []}]}),
    encoding="utf-8")

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(1100, 800); mw.show(); app.processEvents()
mw.open_folder(tmp); app.processEvents()
mw._on_bookmark_activated(mw.bookmark_tree.ordered_pdf_files()[0], 0); app.processEvents()
mv = mw._mv[0]

# 1) 공유 설정 변경 → 두 메인뷰에 즉시 반영
mw._prefs["draw_pens"] = [dict(p) for p in mv._draw_pens]
mw._prefs["draw_pens"][0]["color"] = "#0a0b0c"
mw._prefs["draw_eraser_widths"] = [9, 41]
mw._prefs["draw_highlight_alpha"] = 22
mw._apply_draw_config_all()
chk(mw._mv[0]._draw_pens[0]["color"] == "#0a0b0c"
    and mw._mv[1]._draw_pens[0]["color"] == "#0a0b0c", "공유 펜색 → 두 메인뷰 반영")
chk(mv._draw_eraser_widths == [9, 41], "공유 지우개 면적 반영", str(mv._draw_eraser_widths))
chk(mv._highlight_alpha() == 22, "공유 하이라이트 투명도 반영")

# 2) 발표창이 공유 5펜·지우개·하이라이트 setter 보유 + 동작
from viewer.widgets.presentation import PresentationWindow
pw = PresentationWindow(str(tmp / "U.pdf"), 0, mw, pens=mw._draw_pens(),
                        eraser_widths=mw._draw_eraser_widths())
chk(len(pw._pens) == 5, "발표창 공유 5펜", f"n={len(pw._pens)}")
pw.set_eraser_widths([7, 19]); chk(pw._eraser_widths == [7, 19], "발표 set_eraser_widths")
pw.set_highlight_alpha(33); chk(pw._highlight_alpha == 33, "발표 set_highlight_alpha")
pw.set_pens([dict(p) for p in mw._draw_pens()]); chk(len(pw._pens) == 5, "발표 set_pens 5개")
pw.close()

# 3) 편집모드 → 전체화면: 저장처리 후 '실행'(기존: 종료만)
launched = {"n": 0}
def fake_show():
    launched["n"] += 1
PresentationWindow.show_presentation = lambda self: fake_show()
mw.bookmark_tree.btn_edit.setChecked(True); app.processEvents()
chk(mw.bookmark_tree.is_edit_mode(), "편집모드 진입")
mw._edit_dirty = False    # 변경 없음 → 저장 확인 없이 종료
mw._open_presentation(); app.processEvents()
chk(not mw.bookmark_tree.is_edit_mode(), "전체화면 실행 시 편집모드 해제됨")
chk(launched["n"] == 1, "편집모드여도 저장처리 후 전체화면 실행됨", f"launched={launched['n']}")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
