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
# 캡쳐 버튼: v1.25.0(260606-19)에서 **글자 삭제 → 아이콘만·폭 34**(그 전 260606-9 의 '캡쳐' 라벨은 폐기)
check("캡쳐 버튼 아이콘만(글자 없음)", mw.btn_capture.text() == "" and not mw.btn_capture.icon().isNull(),
      f"text={mw.btn_capture.text()!r}")
check("캡쳐 버튼 폭 34", mw.btn_capture.width() == 34, f"w={mw.btn_capture.width()}")
check("캡쳐 툴팁에 '캡처'", "캡처" in mw.btn_capture.toolTip(), mw.btn_capture.toolTip())
# 툴바 순서: › 다음 캡쳐
tb = mv._toolbar
i_next = tb.indexOf(mv.btn_next_page)
i_cap = tb.indexOf(mw.btn_capture.parent())   # 260606-17: 캡쳐는 캡쳐그룹(버튼+드롭다운) 안
check("› 다음에 캡쳐그룹", i_cap == i_next + 1, f"next={i_next} cap={i_cap}")

# 2분할 시 검색·스크린샷 → 슬라이딩 드로어(오버레이)로 이동(평소 숨김)
# 260628-2: 컬럼 4단은 저장된 `panels_visible` 의존이므로(계획서 §3.1) 두 패널을 명시적으로 켠 뒤 전환을 본다.
mw.act_toggle_search.setChecked(True)
mw.act_toggle_shot.setChecked(True)
mw.act_split.setChecked(True)
check("2분할 켜면 right_panel→드로어", mw.right_panel.parent() is mw._drawer)
check("드로어 기본 닫힘", mw._drawer_open is False)
# 좌우 동일 폭(설정값)
sizes = mw.main_split.sizes()
check("좌우 분할 동일 폭", abs(sizes[0] - sizes[1]) <= 2, f"{sizes}")
# 끄면 복원
mw.act_split.setChecked(False)
check("2분할 끄면 right_panel 복귀(4단)",
      mw.splitter.indexOf(mw.right_panel) == 3 and not mw._panel_in_drawer,
      f"idx={mw.splitter.indexOf(mw.right_panel)} drawer={mw._panel_in_drawer}")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
# 260628-2: `sys.exit` 는 Qt teardown 을 거치며 0xC0000409 로 죽어 종료코드가 무의미했다
# -> `test_side_panels.py` 관례대로 `os._exit`.
sys.stdout.flush()
os._exit(0 if ok else 1)
