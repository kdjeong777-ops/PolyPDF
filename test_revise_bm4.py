# -*- coding: utf-8 -*-
"""260606-수정4 오프스크린 통합 테스트.
편집모드: 선택→이동 시그널, 더블클릭 편집, 컨텍스트 메뉴, 휴지통 아이콘,
         단일/다중·화살표 레이아웃, 변경 추적(dirty)·종료 확인.
썸네일: 우클릭 책갈피 추가 시그널.
책갈피 만들기: 출력 새/현재 라디오·폴더 비활성, _pdf_is_scanned, auto→ocr.
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_fixtures as _fx        # 260628-10: 샘플 PDF를 직접 생성

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  OK  " if cond else " FAIL ") + name + (f"  {extra}" if extra else ""))
    ok = ok and bool(cond)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
app = QApplication.instance() or QApplication(sys.argv)

# ---------- 책갈피 트리 편집모드 ----------
from viewer.widgets.bookmark_tree import BookmarkTree, _EditableTree
from PyQt6.QtWidgets import QTreeWidgetItem
bt = BookmarkTree()
# 레이아웃: 단일/다중 컨테이너 + 트리 서브클래스
check("트리=_EditableTree(드롭 추적)", isinstance(bt.tree, _EditableTree))
# 260628-2: 260611-8 에서 단일/다중이 **라디오 2개 → 토글 버튼 1개**(`btn_sel_mode`)로 바뀌고
#   컨테이너도 `sel_mode_widget` → 편집 조작 묶음 `edit_ops` 로 통합됐다(비편집시 숨김).
# 260901-2: 그 토글은 폐지되고(선택은 항상 다중) 같은 자리에 보기 전환 버튼이 들어갔다.
check("보기 전환(단일/트리) 버튼 존재", hasattr(bt, "btn_view_mode"))
check("편집 조작 컨테이너 존재", hasattr(bt, "edit_ops"))
check("비편집시 편집 조작(보기 전환 포함) 숨김", bt.edit_ops.isHidden())
# 휴지통 아이콘 색상(이모지 변형선택자 포함)
trash = [b for b in bt.findChildren(type(bt.btn_edit)) if "🗑" in b.text()]
check("휴지통 아이콘 컬러 이모지(🗑️)", any("️" in b.text() for b in trash),
      f"texts={[b.text() for b in trash]}")

# 가짜 단일 PDF 트리 구성
import fitz
PDF = _fx.text_pdf()
bt.load_single_pdf(PDF)
root = bt.tree.topLevelItem(0)
# 자식 책갈피 2개 추가(편집 대상)
bt.add_bookmark(PDF, 5, "테스트장")
bt.add_bookmark(PDF, 9, "테스트절")
check("add_bookmark 후 dirty=True", bt._dirty is True)

# 편집 모드 진입 → dirty 리셋, 단일/다중 표시
bt.set_edit_mode(True)
check("편집 진입시 dirty 리셋", bt._dirty is False)
check("편집시 단일/다중 표시", not bt.edit_ops.isHidden())
check("편집시 edit_ops 표시", not bt.edit_ops.isHidden())

# 선택→이동 시그널(편집 모드에서도 emit)
moved = {}
bt.bookmarkActivated.connect(lambda p, pg: moved.update(path=p, page=pg))
ch = root.child(root.childCount() - 1)   # '테스트절' p.9
bt._on_activated(ch)
# 260628-2: 260611-61 부터 이동 발행이 `QTimer.singleShot(0, _flush_nav)` 로 **지연**된다
#   (선택 하이라이트를 먼저 그린 뒤 이동·암호창이 뜨도록) → 이벤트 루프를 한 번 돌려야 emit 된다.
app.processEvents()
check("편집모드 선택→bookmarkActivated emit(지연 발행)", moved.get("page") == 8,
      f"moved={moved}")

# 변경 작업 → dirty
ch.setSelected(True)
bt._op_move_up()
check("이동 작업 후 dirty=True", bt._dirty is True)

# 종료 확인: dirty면 저장여부 질문(자동응답 위해 monkeypatch)
from PyQt6.QtWidgets import QMessageBox
calls = {"q": 0}
_orig_q = QMessageBox.question
QMessageBox.question = staticmethod(
    lambda *a, **k: (calls.__setitem__("q", calls["q"] + 1)
                     or QMessageBox.StandardButton.Discard))
bt.set_edit_mode(False)
QMessageBox.question = _orig_q
check("편집 종료시 변경분 저장확인 질문", calls["q"] == 1)
check("Discard 시 편집모드 해제", bt._edit_mode is False)

# ---------- 썸네일 우클릭 책갈피 추가 ----------
from viewer.widgets.thumbs_list import PageThumbs
pt = PageThumbs()
check("addBookmarkAtPage 시그널 존재", hasattr(pt, "addBookmarkAtPage"))
check("리스트 컨텍스트메뉴 정책", pt.list.contextMenuPolicy()
      == Qt.ContextMenuPolicy.CustomContextMenu)

# ---------- 책갈피 만들기 다이얼로그 ----------
from viewer.widgets.bookmarker_dialog import BookmarkerDialog
from pathlib import Path
dlg = BookmarkerDialog(default_pdf=Path(PDF))
check("새/현재 저장 라디오 존재", hasattr(dlg, "rb_save_new") and hasattr(dlg, "rb_save_over"))
check("기본=새 PDF로 저장", dlg.rb_save_new.isChecked())
dlg.rb_save_over.setChecked(True)
check("현재 저장 선택시 출력폴더 비활성", not dlg.edit_outdir.isEnabled()
      and not dlg.btn_browse_out.isEnabled())
opts = dlg.result_options()
check("result_options overwrite=True", opts.get("overwrite") is True)
check("result_options save_pdf=True", opts.get("save_pdf") is True)

# ---------- _pdf_is_scanned / auto→ocr ----------
from viewer.workers import _pdf_is_scanned
HM = _fx.scanned_pdf()
if os.path.exists(HM):
    check("HM(스캔본) is_scanned=True", _pdf_is_scanned(HM) is True)
check("아스팔트(디지털 레이어) is_scanned=False", _pdf_is_scanned(PDF) is False)

# ---------- 추가 A: 같은 페이지 다중 책갈피 → 헤딩/숫자만 ----------
from viewer.study.ocr_headings import (prefer_heading_per_page, is_heading_title)
from viewer._vendor.pdf_bookmarker.core import Bookmark as BM
check("is_heading 'CHAPTER 1'", is_heading_title("CHAPTER 1"))
check("is_heading '제1장'", is_heading_title("제1장"))
check("is_heading '1.1'", is_heading_title("1.1"))
check("is_heading '1. 일반사항'", is_heading_title("1. 일반사항"))
check("is_heading '제2편'", is_heading_title("제2편"))
check("not heading 'MARY'", not is_heading_title("MARY"))
# 같은 페이지(10)에 헤딩 1 + 잡음 2 → 헤딩만 남김
bms = [BM("MARY", 10, 0), BM("CHAPTER 1", 10, 0), BM("What's two", 10, 0),
       BM("PROJECT", 3, 0), BM("HAIL", 3, 0)]   # 3p는 전부 비헤딩 → 유지
out = prefer_heading_per_page(bms)
titles10 = [b.title for b in out if b.page == 10]
titles3 = [b.title for b in out if b.page == 3]
check("10p 헤딩만 남음(CHAPTER 1)", titles10 == ["CHAPTER 1"], f"{titles10}")
check("3p 전부 비헤딩 → 유지", set(titles3) == {"PROJECT", "HAIL"}, f"{titles3}")
# 전부 헤딩이면 모두 유지
bms2 = [BM("1.1", 5, 1), BM("1.2", 5, 1)]
check("같은 페이지 전부 헤딩 → 유지", len(prefer_heading_per_page(bms2)) == 2)

# ---------- 추가 B: 뷰어 우클릭 컨텍스트 메뉴(편집모드) ----------
from viewer.app import MainWindow
mw = MainWindow()
check("main_view contextMenuRequested 시그널", hasattr(mw.main_view, "contextMenuRequested"))
check("_on_viewer_context_menu 핸들러", callable(getattr(mw, "_on_viewer_context_menu", None)))
check("_prompt_add_bookmark 헬퍼", callable(getattr(mw, "_prompt_add_bookmark", None)))
# 260628-2: '편집모드가 아니면 메뉴가 안 뜬다'는 전제는 낡았다 — 260617-2 가 **편집모드와 무관한**
#   텍스트 복사·블럭설정·현재 페이지 인쇄를 넣었으므로 비편집에서도 메뉴는 뜬다.
#   현행 사양은 '책갈피 추가·하이퍼링크 등록은 편집모드에서만'. exec() 는 모달이라
#   가로채서 항목 구성만 확인한다(인자도 None 이 아니라 실제 QPoint 여야 한다).
from PyQt6.QtWidgets import QMenu
from PyQt6.QtCore import QPoint
seen = {}
_orig_exec = QMenu.exec
QMenu.exec = lambda self, *a, **k: seen.update(
    texts=[x.text() for x in self.actions()]) or None
try:
    for _mode, _label in ((False, "비편집"), (True, "편집")):
        seen.clear()
        mw.bookmark_tree.set_edit_mode(_mode)
        mw._on_viewer_context_menu(QPoint(10, 10))
        _texts = seen.get("texts", [])
        _has_add = any("책갈피 추가" in t for t in _texts)
        check(f"{_label}모드 우클릭 메뉴 예외 없음", bool(_texts), f"n={len(_texts)}")
        check(f"{_label}모드: 책갈피 추가 " + ("있음" if _mode else "없음"),
              _has_add is _mode, f"texts={_texts}")
finally:
    QMenu.exec = _orig_exec
    mw.bookmark_tree.set_edit_mode(False)

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
# 260628-2 (§14.7): sys.exit 는 Qt teardown 에서 0xC0000409 로 죽어 종료코드가 무의미해진다.
sys.stdout.flush()
os._exit(0 if ok else 1)
