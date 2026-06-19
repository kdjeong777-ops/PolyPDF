# -*- coding: utf-8 -*-
"""260606-19: 용어/폭, 패널 드로어(둘다 숨김), 스크린샷만 확장."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def ck(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow()
mv = mw._mv[0]

ck("2장 맞춤", mv.FIT_PAGE_TWO == "2장 맞춤", mv.FIT_PAGE_TWO)
ck("수동", mv.FIT_NONE == "수동", mv.FIT_NONE)
ck("캡쳐 버튼 글자 삭제·폭<=36", mw.btn_capture.text() == "" and mw.btn_capture.maximumWidth() <= 36)
ck("읽기메뉴 폭 78", mw.btn_read_menu.maximumWidth() == 78)
from viewer.widgets.capture_settings import CaptureSizesDialog
_dn = CaptureSizesDialog([]).result_sizes()[0]["name"]
ck("사용자 명칭 단축(기본)", _dn == "사용자1", _dn)
# 콤보 항목 텍스트
items = [mv.cmb_fit.itemText(i) for i in range(mv.cmb_fit.count())]
ck("콤보에 2장 맞춤·수동", "2장 맞춤" in items and "수동" in items, f"{items}")

# 패널 드로어/확장
mw.act_toggle_search.setChecked(True); mw.act_toggle_shot.setChecked(True)
mw._sync_right_layout()
ck("둘 다 켜짐→컬럼", not mw._panel_in_drawer)
mw.act_toggle_search.setChecked(False); mw.act_toggle_shot.setChecked(False)
ck("둘 다 끔→드로어(슬라이드)", mw._panel_in_drawer and mw.right_panel.parent() is mw._drawer)
mw.act_toggle_shot.setChecked(True)   # 스크린샷만
ck("스크린샷만→컬럼+확장", (not mw._panel_in_drawer) and mw.shot_strip.list.isWrapping())
mw.act_toggle_search.setChecked(True)  # 둘 다
ck("둘 다→비확장", not mw.shot_strip.list.isWrapping())
mw.act_split.setChecked(True)
ck("2분할→드로어", mw._panel_in_drawer)
mw.act_split.setChecked(False)
ck("2분할 해제+둘다→컬럼", not mw._panel_in_drawer)

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
