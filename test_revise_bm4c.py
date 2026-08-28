# -*- coding: utf-8 -*-
"""260606-5: mp3 아이콘 축소, 캡처→클립보드, 파일우클릭 단어장생성, 전체삭제→자동숨김."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  OK  " if cond else " FAIL ") + name + (f"  {extra}" if extra else ""))
    ok = ok and bool(cond)

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QSize
from viewer.resources_path import resource_path
app = QApplication.instance() or QApplication(sys.argv)

# mp3 아이콘: 비율이 이전(가로 길쭉)보다 작아짐(세로 여백 포함) → 글자 작게
ic = QIcon(resource_path("icon_mp3.png"))
check("새 mp3 아이콘 로드", not ic.isNull())
from PIL import Image
w, h = Image.open(resource_path("icon_mp3.png")).size
check("mp3 아이콘 비율 ≤ 2.2 (여백 포함·글자 축소)", (w / h) <= 2.2, f"{w}x{h} ratio={w/h:.2f}")

from viewer.app import MainWindow
mw = MainWindow()
# 260628-2: 40×20 은 260611-31 이전 사양이다. 그 항목이 mp3 아이콘을 **정사각**(분홍 음표+＋)으로
#   교체하면서 메인 툴바는 24×24 가 됐고, 단어장 패널 헤더는 버튼 4종을 26×26 칸에 22×22 아이콘으로
#   통일(메인 툴바 높이 26 과 맞춤)했다.
_sz = mw.study_panel.btn_mp3.iconSize()
check(f"단어장 mp3 iconSize 22x22 (실측 {_sz.width()}x{_sz.height()})", _sz == QSize(22, 22))
check("단어장 mp3 버튼 26x26 정사각", mw.study_panel.btn_mp3.size() == QSize(26, 26),
      str(mw.study_panel.btn_mp3.size()))
_sz2 = mw.btn_main_mp3.iconSize()
check(f"메인 mp3 iconSize 24x24 (실측 {_sz2.width()}x{_sz2.height()})", _sz2 == QSize(24, 24))

# 파일 우클릭 '단어장 생성'
bt = mw.bookmark_tree
check("createStudyRequested 시그널", hasattr(bt, "createStudyRequested"))
check("_on_create_study_requested 핸들러", callable(getattr(mw, "_on_create_study_requested", None)))

# 전체삭제(clear) → 자동 숨김
mw.act_toggle_shot.setChecked(True)
mw.shot_strip.add_item(resource_path("icon.png"), kind="image", label="t1", prepend=False)
check("스크린샷 추가됨", mw.shot_strip.list.count() == 1)
mw.shot_strip.clear()      # list.clear() → modelReset → _hide_shots_if_empty
check("전체삭제 후 토글 꺼짐(자동숨김)", not mw.act_toggle_shot.isChecked(),
      f"count={mw.shot_strip.list.count()} checked={mw.act_toggle_shot.isChecked()}")

# 개별 삭제 경로(takeItem→rowsRemoved)도 확인
mw.act_toggle_shot.setChecked(True)
mw.shot_strip.add_item(resource_path("icon.png"), kind="image", label="t2", prepend=False)
mw.shot_strip.list.takeItem(0)
check("개별 삭제로 비면 토글 꺼짐", not mw.act_toggle_shot.isChecked())

# 캡처 → 클립보드 복사(경고/저장 부작용 차단 후 호출)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.information = staticmethod(lambda *a, **k: None)
import viewer.app as appmod
appmod.ss.save_screenshot = lambda *a, **k: __import__("pathlib").Path(
    os.environ.get("TEMP", ".")) / "cap_test.png"
mw.shot_strip.add_item = lambda *a, **k: None
PDF = r"C:/Claude/MPDF/_samples/24 아스팔트콘크리트포장시공지침.pdf"
from viewer.app import HistoryItem
if os.path.exists(PDF):
    mw._load_main(HistoryItem(PDF, 0, "", "bookmark"))
    app.processEvents()
    QApplication.clipboard().clear()
    try:
        mw.action_screenshot()
        cp = QApplication.clipboard().pixmap()
        check("캡처 시 클립보드에 이미지 복사", cp is not None and not cp.isNull(),
              f"null={cp.isNull() if cp else 'None'}")
    except Exception as e:
        check(f"캡처 클립보드 ({e})", False)
else:
    print("  SKIP 캡처(테스트 PDF 없음)")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
# 260628-2 (§14.7): sys.exit 는 Qt teardown 에서 0xC0000409 로 죽어 종료코드가 무의미해진다 → os._exit.
sys.stdout.flush()
os._exit(0 if ok else 1)
