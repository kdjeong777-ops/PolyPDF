# -*- coding: utf-8 -*-
"""260606-18: FlowLayout 가로 중앙 정렬, 그룹 여백, 캡쳐 화질 용어."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication, QWidget, QPushButton
app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.flow_layout import FlowLayout

# 한 줄에 들어가는 좁은 항목들 → 넓은 폭에서 가로 중앙(왼쪽 여백>0)
w = QWidget(); w.resize(600, 40)
fl = FlowLayout(w, spacing=4)
b1 = QPushButton("A"); b1.setFixedSize(50, 26)
b2 = QPushButton("B"); b2.setFixedSize(50, 26)
fl.addWidget(b1); fl.addWidget(b2)
fl.setGeometry(w.rect())
x1 = b1.geometry().x()
total = 50 + 4 + 50
expected_ox = (600 - total) // 2
check("가로 중앙 정렬(좌측 여백)", abs(x1 - expected_ox) <= 3, f"x1={x1} exp={expected_ox}")
# 두 버튼이 인접(중앙 묶음)
check("두 버튼 간격=spacing", b2.geometry().x() - (b1.geometry().x() + 50) == 4)

# 캡쳐 화질 용어 + 그룹 여백
from viewer.app import MainWindow
mw = MainWindow()
mw._cap_menus[0].menu()  # 메뉴 빌드됨
# 메뉴 텍스트 수집
def menu_texts(menu):
    out = []
    for a in menu.actions():
        out.append(a.text())
        if a.menu():
            out += menu_texts(a.menu())
    return out
mt = menu_texts(mw._cap_menus[0].menu())
check("'캡쳐 화질 설정' 메뉴", "캡쳐 화질 설정" in mt, f"{mt}")
check("'보이는 화질'", "보이는 화질" in mt)
check("'원본 화질'", "원본 화질" in mt)
check("구 용어 제거", "복사 크기" not in mt and "보이는 크기로 복사" not in mt)

# 그룹 여백(읽기 그룹·캡쳐 그룹 왼쪽 마진 10)
grp = mw.btn_read.parent()
m = grp.layout().contentsMargins()
check("읽기 그룹 좌측 여백", m.left() >= 8, f"left={m.left()}")
cap_grp = mw.btn_capture.parent()
cm = cap_grp.layout().contentsMargins()
check("캡쳐 그룹 좌측 여백", cm.left() >= 8, f"left={cm.left()}")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
