# -*- coding: utf-8 -*-
"""260606-6: 스크린샷 패널 높이 축소, 단어장 편집 아이콘=책갈피 편집과 동일."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.strip import MiniStrip
check("CARD_H 축소(<=160)", MiniStrip.CARD_H <= 160, f"CARD_H={MiniStrip.CARD_H}")

from viewer.app import MainWindow
mw = MainWindow()
lh = mw.shot_strip.list.maximumHeight()
check("스크린샷 리스트 높이 축소(<=180)", lh <= 180, f"list fixedH={lh}")

# 단어장 편집 아이콘 = 책갈피 편집 아이콘과 동일 이미지(연필)
from viewer.resources_path import resource_path
sp_icon = mw.study_panel.btn_edit.icon()
bt_icon = mw.bookmark_tree.btn_edit.icon()
check("단어장 편집 아이콘 적용(아이콘만)",
      not sp_icon.isNull() and mw.study_panel.btn_edit.text() == "")
# 동일 이미지인지: 같은 파일(icon_edit.png) 픽스맵 비교
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QSize
ref = QIcon(resource_path("icon_edit.png"))
def key(ic):
    return ic.pixmap(QSize(18, 18)).toImage()
check("단어장 편집 = 책갈피 편집과 동일 이미지",
      key(sp_icon) == key(ref) and key(bt_icon) == key(ref))

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
