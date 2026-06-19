# -*- coding: utf-8 -*-
"""260606-20: 드로어 손잡이가 스크롤바와 겹칠 때 방향 따라 비킴, 아니면 중앙."""
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
mw.resize(1200, 800)
mw.show()
app.processEvents()

# 드로어 모드 진입(검색·스크린샷 모두 끔)
mw.act_toggle_search.setChecked(False)
mw.act_toggle_shot.setChecked(False)
app.processEvents()
ck("드로어 모드", mw._panel_in_drawer and not mw._drawer_open)

mv = mw.main_view
sb = mv.doc_scroll
if sb.maximum() <= 0:
    sb.setRange(0, 1000)
mx = sb.maximum()
mid = mx // 2
H = mw._central.height()
ck("central 높이>0", H > 0, f"H={H}")
ck("스크롤 범위>0", mx > 0, f"max={mx}")

# 결정적 검증: 신호 차단 + 값/직전값 직접 설정 후 _update 직접 호출
def probe(val, last):
    sb.blockSignals(True); sb.setValue(val); sb.blockSignals(False)
    mw._last_scroll_val = last
    mw._handle_offset = 0
    mw._update_handle_for_scroll(mv)
    return mw._handle_offset

ck("아래로 스크롤+겹침 → 손잡이 위로", probe(mid, mid - mx // 10) < 0, f"off={mw._handle_offset}")
ck("위로 스크롤+겹침 → 손잡이 아래로", probe(mid, mid + mx // 10) > 0, f"off={mw._handle_offset}")
ck("상단 겹침 없음 → 중앙", probe(int(mx * 0.02), 0) == 0, f"off={mw._handle_offset}")
ck("하단 겹침 없음 → 중앙", probe(int(mx * 0.98), mx) == 0, f"off={mw._handle_offset}")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
