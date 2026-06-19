# -*- coding: utf-8 -*-
"""260606-10: 우측 패널 비면 메인 전체폭, 2분할 두 창 쪽맞춤, 분할해제 전체폭."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow()

# 260606-19: '모두 숨김'은 우측 패널을 드로어로 이동(슬라이드)→메인 전체폭
mw.act_toggle_search.setChecked(False)
mw.act_toggle_shot.setChecked(False)
check("패널 모두 숨김 → 드로어(메인 전체폭)", mw._panel_in_drawer)
mw.act_toggle_search.setChecked(True)
check("검색 켜면 컬럼(드로어 아님)", not mw._panel_in_drawer)
mw.act_toggle_search.setChecked(False)
check("다시 모두 끄면 드로어", mw._panel_in_drawer)

# 2분할: 두 창 쪽맞춤 기본
mw.act_split.setChecked(True)
check("2분할 두 창 모두 쪽맞춤", all(m._fit_mode == m.FIT_PAGE for m in mw._mv),
      f"{[m._fit_mode for m in mw._mv]}")

# 분할 해제 → 패널이 꺼져 있던 상태였으므로 드로어 유지(메인 전체폭)
mw.act_split.setChecked(False)
check("분할 해제 + 패널 꺼짐 → 드로어(전체폭)", mw._panel_in_drawer)

# 패널 다시 켜면 분할 해제 상태에서 컬럼
mw.act_toggle_shot.setChecked(True)
check("스크린샷 켜면 컬럼", not mw._panel_in_drawer)

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
