# -*- coding: utf-8 -*-
"""260606-12: FlowLayout 세로 중앙 정렬(라벨), 창별 ▶/■ 상태(두 창 비동기화)."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QLabel
app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.flow_layout import FlowLayout

# 세로 중앙 정렬: 큰 버튼 + 작은 라벨 한 줄 → 라벨 y 가 버튼 y 보다 아래(중앙)
w = QWidget(); w.resize(400, 60)
fl = FlowLayout(w, spacing=4)
big = QPushButton("BIG"); big.setFixedSize(80, 40)
lab = QLabel("/ 598"); lab.setFixedSize(40, 16)
fl.addWidget(big); fl.addWidget(lab)
fl.setGeometry(w.rect())
gy_big = big.geometry().y(); gy_lab = lab.geometry().y()
# 라벨(16) 이 버튼(40) 줄에서 중앙 → 라벨 y > 버튼 y, 두 중심선이 비슷
center_big = gy_big + 40 / 2
center_lab = gy_lab + 16 / 2
check("FlowLayout 세로 중앙(라벨이 위로 안 뜸)", gy_lab > gy_big and abs(center_big - center_lab) <= 2,
      f"big_y={gy_big} lab_y={gy_lab}")

# 창별 ▶/■: 그 창이 읽는 중일 때만 ■
from viewer.app import MainWindow
mw = MainWindow()
b0 = mw._read_btns[0][0]; b1 = mw._read_btns[1][0]
# 비활성 → 둘 다 ▶
mw.read_aloud._active = False
mw._update_read_buttons()
check("비활성 → 둘 다 ▶", b0.text() == "▶" and b1.text() == "▶")
# 1번창 읽는 중 → b0 ■, b1 ▶
mw.read_aloud._active = True
mw.read_aloud._view = mw._mv[0]
mw._update_read_buttons()
check("1번창 재생 → b0=■, b1=▶", b0.text() == "■" and b1.text() == "▶",
      f"b0={b0.text()} b1={b1.text()}")
# 2번창으로 전환 → b1 ■, b0 ▶
mw.read_aloud._view = mw._mv[1]
mw._update_read_buttons()
check("2번창 재생 → b1=■, b0=▶", b1.text() == "■" and b0.text() == "▶",
      f"b0={b0.text()} b1={b1.text()}")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
