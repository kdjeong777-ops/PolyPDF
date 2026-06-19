# -*- coding: utf-8 -*-
"""260606-9 추가: 2분할 시 검색·스크린샷 슬라이딩 드로어 + 책갈피 활성창 동기화."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow, HistoryItem
mw = MainWindow()

# 드로어 구성요소
check("드로어 위젯 존재", hasattr(mw, "_drawer") and hasattr(mw, "_drawer_btn"))
check("기본 right_panel은 splitter 4단", mw.splitter.indexOf(mw.right_panel) == 3)

# 2분할 켜기 → right_panel 이 드로어로 이동(오버레이), 핸들 표시, 기본 닫힘
mw.act_split.setChecked(True)
check("2분할 시 right_panel→드로어로 reparent", mw.right_panel.parent() is mw._drawer)
check("드로어 기본 닫힘", mw._drawer_open is False)
check("핸들 버튼 표시(숨김 아님)", not mw._drawer_btn.isHidden())
check("splitter 3단으로 축소(뷰어 폭 확보)", mw.splitter.indexOf(mw.right_panel) == -1)

# 드로어 열기/닫기
mw._toggle_drawer()
check("드로어 열림", mw._drawer_open is True)
mw._toggle_drawer()
check("드로어 닫힘", mw._drawer_open is False)

# 2분할 끄기 → right_panel 복귀, 핸들 숨김
mw.act_split.setChecked(False)
check("2분할 끄면 right_panel 복귀(4단)", mw.splitter.indexOf(mw.right_panel) == 3)
check("핸들 숨김", mw._drawer_btn.isHidden())

# 책갈피 활성창 위치 동기화
PDF = r"C:/Claude/MPDF/24 아스팔트콘크리트포장시공지침.pdf"
if os.path.exists(PDF):
    mw.bookmark_tree.load_single_pdf(PDF)      # 트리에 파일 노드+TOC
    mw._load_main(HistoryItem(PDF, 0, "", "bookmark"))
    app.processEvents()
    mw._mv[0].go_to_page(20)                    # 21쪽으로
    app.processEvents()
    mw._sync_bookmark_to_active()
    cur = mw.bookmark_tree.tree.currentItem()
    pg = cur.data(0, mw.bookmark_tree.DATA_PAGE) if cur else None
    check("책갈피가 활성 페이지(≤20) 위치로 선택", cur is not None and pg is not None and int(pg) <= 20,
          f"sel_page={pg}")
else:
    print("  SKIP 책갈피 동기화(PDF 없음)")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
