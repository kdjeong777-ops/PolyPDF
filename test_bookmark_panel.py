# -*- coding: utf-8 -*-
"""260611-8: 책갈피 패널 — 저장 위치/단일·다중 토글 + 동일페이지 선택 유지."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication, QTreeWidgetItem, QAbstractItemView
from PyQt6.QtCore import Qt

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.bookmark_tree import BookmarkTree
bt = BookmarkTree()

# 1) 저장 버튼이 편집 행에 있고 편집모드에서만 보임
chk(hasattr(bt, "btn_edit_single") and not bt.btn_edit_single.icon().isNull(),
    "책갈피명 수정 버튼(새 아이콘) 존재")
chk(hasattr(bt, "btn_save"), "btn_save 존재")
chk(bt.btn_save.isHidden(), "비편집 시 저장 숨김")
chk(hasattr(bt, "btn_sel_mode") and not hasattr(bt, "rb_multi"),
    "단일/다중 라디오 → 토글 버튼 1개로 대체")

# 2) 단일/다중 토글 동작 + 트리 선택모드 반영(편집모드)
bt.set_edit_mode(True)
chk(not bt.btn_save.isHidden(), "편집모드 시 저장 보임")
chk(bt._multi_sel and bt.btn_sel_mode.text() == "다중", "초기 다중")
chk(bt.tree.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection,
    "다중 → ExtendedSelection(실제 다중 선택 가능)")
bt._toggle_sel_mode()
chk(not bt._multi_sel and bt.btn_sel_mode.text() == "단일", "토글 → 단일")
chk(bt.tree.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection,
    "단일 → SingleSelection")
bt._toggle_sel_mode()
chk(bt._multi_sel and bt.btn_sel_mode.text() == "다중", "다시 토글 → 다중")

# 3) 동일 페이지에 책갈피 2개 — 현재 선택이 그 페이지면 유지(마지막으로 안 옮김)
bt.set_edit_mode(False)
top = QTreeWidgetItem(["file"])
top.setData(0, bt.DATA_FILE, r"C:\x\A.pdf")
top.setData(0, bt.DATA_TOC_LOADED, True)
bt.tree.addTopLevelItem(top)
b1 = QTreeWidgetItem(["bm1 p3"]); b1.setData(0, bt.DATA_PAGE, 2)   # page0=2
b2 = QTreeWidgetItem(["bm2 p3"]); b2.setData(0, bt.DATA_PAGE, 2)   # 같은 페이지
b3 = QTreeWidgetItem(["bm3 p5"]); b3.setData(0, bt.DATA_PAGE, 4)
for b in (b1, b2, b3): top.addChild(b)
top.setExpanded(True)

# 현재 b1 선택(페이지 2) 상태에서 같은 페이지(2)로 동기 → b1 유지(b2로 안 감)
bt.tree.setCurrentItem(b1)
bt.select_for_page(r"C:\x\A.pdf", 2)
chk(bt.tree.currentItem() is b1, "현재 선택(b1)이 같은 페이지면 유지(마지막 b2로 안 감)",
    f"cur={bt.tree.currentItem().text(0) if bt.tree.currentItem() else None}")

# 현재 b2 선택 상태에서 같은 페이지로 동기 → b2 유지
bt.tree.setCurrentItem(b2)
bt.select_for_page(r"C:\x\A.pdf", 2)
chk(bt.tree.currentItem() is b2, "현재 선택(b2)이 같은 페이지면 유지")

# 다른 페이지(4)로 가면 정상적으로 b3 선택
bt.tree.setCurrentItem(b1)
bt.select_for_page(r"C:\x\A.pdf", 4)
chk(bt.tree.currentItem() is b3, "다른 페이지로는 정상 이동(b3)")

# 선택이 그 페이지가 아니면(예: 페이지5에서 페이지2 동기) → 해당 페이지 책갈피로 이동
bt.tree.setCurrentItem(b3)   # page4
bt.select_for_page(r"C:\x\A.pdf", 2)
chk(bt.tree.currentItem() in (b1, b2), "현재 선택이 그 페이지가 아니면 그 페이지 책갈피로 이동")

# 4) 취소 버튼: 편집↔저장 사이, 편집모드에서만, editCancelled 신호
chk(hasattr(bt, "btn_cancel"), "btn_cancel 존재")
chk(hasattr(bt, "editCancelled"), "editCancelled 신호 존재")
bt.set_edit_mode(False)
chk(bt.btn_cancel.isHidden(), "비편집 시 취소 숨김")
bt.set_edit_mode(True)
chk(not bt.btn_cancel.isHidden(), "편집모드 시 취소 보임")

# 5) 편집 아이콘 파랑↔빨강 스왑
chk(bt._ico_edit_blue.cacheKey() != bt._ico_edit_red.cacheKey(), "파랑/빨강 아이콘 서로 다름")
bt.set_edit_mode(True)
red_key = bt.btn_edit.icon().cacheKey()
bt.set_edit_mode(False)
blue_key = bt.btn_edit.icon().cacheKey()
chk(red_key == bt._ico_edit_red.cacheKey(), "편집 선택 시 빨강 아이콘")
chk(blue_key == bt._ico_edit_blue.cacheKey(), "편집 해제 시 파랑 아이콘")

# 6) 취소 동작: reload_fn 호출 + dirty 해제 + editCancelled emit (확인창=Yes)
from PyQt6.QtWidgets import QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
reloaded = {"n": 0}
bt._reload_fn = lambda: reloaded.__setitem__("n", reloaded["n"] + 1)
emitted = {"n": 0}
bt.editCancelled.connect(lambda: emitted.__setitem__("n", emitted["n"] + 1))
bt._dirty = True
bt._op_cancel()
chk(reloaded["n"] == 1 and not bt._dirty and emitted["n"] == 1,
    "취소 → 재로드+dirty해제+editCancelled", f"reload={reloaded['n']} dirty={bt._dirty} emit={emitted['n']}")

# 7) 다중 선택 보존: 2개 선택 후 select_for_page 가 선택을 깨지 않음
bt.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
b1.setSelected(True); b2.setSelected(True)
chk(len(bt.tree.selectedItems()) == 2, "2개 선택됨")
bt.select_for_page(r"C:\x\A.pdf", 4)   # 동기화 시도
chk(len(bt.tree.selectedItems()) == 2, "동기화가 다중 선택을 깨지 않음(보존)",
    f"sel={len(bt.tree.selectedItems())}")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
