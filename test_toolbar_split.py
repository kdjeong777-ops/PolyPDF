# -*- coding: utf-8 -*-
"""260606-9: 툴바 폭 축소(FlowLayout 2단 가능)·캡쳐 명칭·2분할 시 패널 숨김."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
from viewer.widgets.flow_layout import FlowLayout
app = QApplication.instance() or QApplication(sys.argv)

# FlowLayout indexOf/insertWidget
from PyQt6.QtWidgets import QPushButton, QWidget
w = QWidget(); fl = FlowLayout(w)
b1, b2, b3 = QPushButton("1"), QPushButton("2"), QPushButton("3")
fl.addWidget(b1); fl.addWidget(b2)
fl.insertWidget(fl.indexOf(b1) + 1, b3)   # 1,3,2
check("FlowLayout insertWidget 순서", [fl.itemAt(i).widget().text() for i in range(fl.count())] == ["1", "3", "2"])

from viewer.app import MainWindow
mw = MainWindow()
mv = mw.main_view
# 툴바가 FlowLayout
check("툴바가 FlowLayout", isinstance(mv._toolbar, FlowLayout))
# 줄바꿈 가능 → 좁은 폭에서 높이 증가(2단)
wide = mv._toolbar.heightForWidth(2000)
narrow = mv._toolbar.heightForWidth(180)
check("좁아지면 툴바 2단(높이 증가)", narrow > wide, f"wide={wide} narrow={narrow}")
# 위젯 폭 축소
check("페이지칸 폭 ≤ 48", mv.spin_page.maximumWidth() <= 48 or mv.spin_page.width() <= 48)
check("보기콤보 폭 ≤ 90", mv.cmb_fit.maximumWidth() <= 90)
# 캡쳐 버튼 명칭 '캡쳐'
check("캡쳐 버튼 '캡쳐'", "캡쳐" in mw.btn_capture.text() and "화면" not in mw.btn_capture.text())
# 툴바 순서: › 다음 캡쳐
tb = mv._toolbar
i_next = tb.indexOf(mv.btn_next_page)
i_cap = tb.indexOf(mw.btn_capture.parent())   # 260606-17: 캡쳐는 캡쳐그룹(버튼+드롭다운) 안
check("› 다음에 캡쳐그룹", i_cap == i_next + 1, f"next={i_next} cap={i_cap}")

# 2분할 시 검색·스크린샷 → 슬라이딩 드로어(오버레이)로 이동(평소 숨김)
mw.act_split.setChecked(True)
check("2분할 켜면 right_panel→드로어", mw.right_panel.parent() is mw._drawer)
check("드로어 기본 닫힘", mw._drawer_open is False)
# 좌우 동일 폭(설정값)
sizes = mw.main_split.sizes()
check("좌우 분할 동일 폭", abs(sizes[0] - sizes[1]) <= 2, f"{sizes}")
# 끄면 복원
mw.act_split.setChecked(False)
check("2분할 끄면 right_panel 복귀(4단)", mw.splitter.indexOf(mw.right_panel) == 3)

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
