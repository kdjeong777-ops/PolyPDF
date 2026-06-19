# -*- coding: utf-8 -*-
"""260606-수정4 추가배치 검증: 아이콘, 툴바 순서, 책갈피 새로고침/우클릭메뉴, 다이얼로그."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  OK  " if cond else " FAIL ") + name + (f"  {extra}" if extra else ""))
    ok = ok and bool(cond)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from viewer.resources_path import resource_path
app = QApplication.instance() or QApplication(sys.argv)

# 아이콘 파일 로드 확인
for n in ("icon_edit.png", "icon_word.png", "icon_mp3.png"):
    p = resource_path(n)
    check(f"{n} 존재·로드", os.path.exists(p) and not QIcon(p).isNull(), p)

from viewer.app import MainWindow
mw = MainWindow()

# 편집 버튼 아이콘
check("책갈피 편집 버튼 아이콘", not mw.bookmark_tree.btn_edit.icon().isNull())
# 단어장 Word/mp3 아이콘(아이콘만)
sp = mw.study_panel
check("단어장 Word 아이콘", not sp.btn_word.icon().isNull() and sp.btn_word.text() == "")
check("단어장 mp3 아이콘", not sp.btn_mp3.icon().isNull() and sp.btn_mp3.text() == "")
# 메인 mp3 아이콘
check("메인 mp3 아이콘", not mw.btn_main_mp3.icon().isNull())

# 툴바 순서: 좌→우 [화면캡쳐][▶ 전체▾][mp3]
tb = mw.main_view._toolbar
grp = mw.btn_read.parent()
i_cap = tb.indexOf(mw.btn_capture)
i_grp = tb.indexOf(grp)
i_mp3 = tb.indexOf(mw.btn_main_mp3)
check("툴바 순서 캡쳐<읽기그룹<mp3", i_cap < i_grp < i_mp3,
      f"cap={i_cap} grp={i_grp} mp3={i_mp3}")

# 다이얼로그: 자동열기 체크 제거
from viewer.widgets.bookmarker_dialog import BookmarkerDialog
from pathlib import Path
PDF = r"C:/Claude/MPDF/24 아스팔트콘크리트포장시공지침.pdf"
dlg = BookmarkerDialog(default_pdf=Path(PDF))
check("자동열기 체크 제거", not hasattr(dlg, "chk_open"))
check("result_options open_after 없음", "open_after" not in dlg.result_options())

# 책갈피 트리: 새로고침/추가(목록 유지), 우클릭 신호
bt = mw.bookmark_tree
check("createBookmarksRequested 시그널", hasattr(bt, "createBookmarksRequested"))
check("add_or_refresh_file 메서드", callable(getattr(bt, "add_or_refresh_file", None)))
bt.load_single_pdf(PDF)
n0 = bt.tree.topLevelItemCount()
# 같은 파일 → 노드 수 불변(refresh)
bt.add_or_refresh_file(PDF)
check("같은 파일 add_or_refresh → 노드 수 유지", bt.tree.topLevelItemCount() == n0,
      f"{n0}->{bt.tree.topLevelItemCount()}")
# 다른 파일 → 노드 추가(기존 유지)
other = r"C:/Claude/MPDF/HM.pdf"
if os.path.exists(other):
    bt.add_or_refresh_file(other)
    check("다른 파일 추가 → 노드 +1(기존 유지)", bt.tree.topLevelItemCount() == n0 + 1,
          f"{n0}->{bt.tree.topLevelItemCount()}")

# action_open_bookmarker default_file 인자
import inspect
sig = inspect.signature(mw.action_open_bookmarker)
check("action_open_bookmarker(default_file=) 지원", "default_file" in sig.parameters)

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
