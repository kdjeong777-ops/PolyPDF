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
# 260628-2: `<=180` 은 v1.19.1(260606-6, CARD_H 210→150 · 리스트 +22) 시점 값이다.
#   그 뒤 260606-17 이 **썸네일 아래 '번호' 줄**을 넣으며 +16 이 더해져 현행은 CARD_H+22+16 이다.
lh = mw.shot_strip.list.maximumHeight()
_expect = mw.shot_strip.CARD_H + 22 + 16
check(f"스크린샷 리스트 높이 = CARD_H+22+16 ({_expect})", lh == _expect, f"list fixedH={lh}")

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
# 260628-2: '둘이 같은 이미지'는 v1.19.1(260606-6) 사양이고, 그 뒤 **260611-9** 가 책갈피 편집
#   아이콘을 **상태별**로 바꿨다 — 비선택=파란 연필(icon_edit_blue), 편집 중=붉은 연필(icon_edit_red).
#   따라서 현행 사양은 '단어장 편집 = icon_edit.png' + '책갈피 편집 = 파랑↔빨강 전환' 이다.
check("단어장 편집 = icon_edit.png", key(sp_icon) == key(ref))
_blue = QIcon(resource_path("icon_edit_blue.png") or "")
_red = QIcon(resource_path("icon_edit_red.png") or "")
# ※ MainWindow 는 세션 복원 중 `_apply_doc_permissions` 에서 편집모드를 켤 수 있으므로
#   (그러면 아이콘이 이미 붉은 연필이다) 캡처해 둔 참조 대신 **상태를 정해 놓고 그때의 아이콘**을 읽는다.
mw.bookmark_tree.btn_edit.setChecked(False)
check("책갈피 편집(비선택) = 파란 연필",
      key(mw.bookmark_tree.btn_edit.icon()) == key(_blue))
mw.bookmark_tree.btn_edit.setChecked(True)
check("책갈피 편집(편집 중) = 붉은 연필",
      key(mw.bookmark_tree.btn_edit.icon()) == key(_red))
mw.bookmark_tree.btn_edit.setChecked(False)

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
# 260628-2 (§14.7): sys.exit 는 Qt teardown 에서 0xC0000409 로 죽어 종료코드가 무의미해진다 → os._exit.
sys.stdout.flush()
os._exit(0 if ok else 1)
