# -*- coding: utf-8 -*-
"""260915-1: 썸네일에서 쪽을 옮기면 **저장 전에도** 그 순서가 적용된다 (마스터 §4.7.7).

사용자 보고
  "현재 pdf의 일부 페이지를 위/아래로 이동시, 해당 이동이 제대로 적용되지 않고, 변경된 순서가
   아니라, 이상하게 보여. … 수정 후 저장 전에 해당 수정 사항이 적용되지 않는 거 같아."

원인 셋 — ① 옮긴 뒤 커서가 옛 행에 남았다 ② 본문→썸네일 동기가 **쪽 번호를 행으로** 써서
옮긴 뒤엔 다른 썸네일을 골랐다(다음 Alt+↑ 가 엉뚱한 쪽을 옮김) ③ 본문 넘김이 원래 순서였다.
실제 앱에서 키 입력·본문 넘김으로 확인한다.
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, Qt, QModelIndex
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=8):
    for _ in range(n):
        app.processEvents(); QTest.qWait(30)


root = Path(tempfile.mkdtemp(prefix="polypdf_thumb_move_"))
try:
    src = root / "M.pdf"
    d = fitz.open()
    for i in range(6):
        d.new_page().insert_text((72, 72), f"PAGE {i + 1}")
    d.save(str(src)); d.close()
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1300, 900); mw.show(); app.processEvents()
    mw.open_folder(root); spin(15)
    mw._load_main(HistoryItem(str(src), 0, "", "bookmark")); spin(10)
    if not mw._in_edit():
        mw.bookmark_tree.btn_edit.setChecked(True); spin(4)
    pt, L, mv = mw.page_thumbs, mw.page_thumbs.list, mw.main_view
    sel = lambda: [L.row(i) for i in L.selectedItems()]

    it = L.item(4); L.setCurrentItem(it); L.itemClicked.emit(it); spin()
    chk(mv.current_page() == 4, "준비 — 5쪽 썸네일을 누르면 본문 5쪽")
    L.setFocus()
    QTest.keyClick(L, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier); spin()
    QTest.keyClick(L, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier); spin()
    chk(pt.current_page_sequence() == [0, 1, 4, 2, 3, 5], "Alt+↑ 두 번 — 5쪽이 셋째로", str(pt.current_page_sequence()))
    chk(sel() == [2] and L.currentRow() == 2, "① 옮긴 뒤 선택과 **커서가 함께** 옮긴 쪽에 있다",
        "sel=%s cur=%d" % (sel(), L.currentRow()))

    it = L.item(2); L.setCurrentItem(it); L.itemClicked.emit(it); spin()
    chk(mv.current_page() == 4 and L.currentRow() == 2 and sel() == [2],
        "② 옮긴 썸네일을 누르면 본문은 5쪽, 썸네일 선택은 **그 자리에 남는다**",
        "page=%d cur=%d sel=%s" % (mv.current_page(), L.currentRow(), sel()))
    QTest.keyClick(L, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier); spin()
    chk(pt.current_page_sequence() == [0, 4, 1, 2, 3, 5], "② 이어서 Alt+↑ 는 **같은 쪽**을 옮긴다",
        str(pt.current_page_sequence()))

    mv._on_page_step(+1); spin()
    chk(mv.current_page() == 1 and L.currentRow() == 2, "③ 본문 다음 쪽 = **옮긴 순서**의 다음(2쪽)",
        "page=%d row=%d" % (mv.current_page(), L.currentRow()))
    mv._on_page_step(-1); mv._on_page_step(-1); spin()
    chk(mv.current_page() == 0, "③ 본문 이전 쪽도 옮긴 순서로(5쪽 → 1쪽)", str(mv.current_page()))

    # 끌어 놓기 — Qt 6 은 사이에 놓으면 model().moveRow 로 옮긴다(QListView::dropEvent)
    L.model().moveRow(QModelIndex(), 0, QModelIndex(), 4); spin()
    chk(pt.current_page_sequence() == [4, 1, 2, 0, 3, 5], "끌어 놓기(행 이동) 순서", str(pt.current_page_sequence()))
    mv.go_to_page(0); spin()
    mv._on_page_step(+1); spin()
    chk(mv.current_page() == 3 and L.currentRow() == 4, "끌어 놓은 뒤에도 본문 넘김·썸네일 강조가 따라온다",
        "page=%d row=%d" % (mv.current_page(), L.currentRow()))

    L.clearSelection(); L.item(4).setSelected(True); pt._delete_selected(); spin()
    chk(3 not in pt.current_page_sequence(), "삭제 준비")
    mv._on_page_step(-1); mv._on_page_step(+1); spin()
    chk(mv.current_page() != 3, "지운 쪽은 본문 넘김에서 건너뛴다", str(mv.current_page()))
    chk(pt.selected_pages() == [] or all(isinstance(p, int) for p in pt.selected_pages()),
        "selected_pages 는 쪽 번호")
    L.clearSelection(); L.item(0).setSelected(True); L.item(1).setSelected(True)
    chk(pt.selected_pages() == [4, 1], "인쇄·캡처가 쓰는 선택은 **행이 아니라 쪽 번호**", str(pt.selected_pages()))

    # 저장하면 그 순서 그대로 파일에
    L.clearSelection()
    node = next(n for n in mw.bookmark_tree._iter_file_nodes()
                if str(n.data(0, mw.bookmark_tree.DATA_FILE)) == str(src))
    mw.bookmark_tree.tree.setCurrentItem(node); spin(2)
    want = pt.current_page_sequence()
    mw.bookmark_tree._op_save(); spin(10)
    dd = fitz.open(str(src))
    got = [int(dd[i].get_text().split()[1]) - 1 for i in range(dd.page_count)]
    dd.close()
    chk(got == want, "저장한 파일의 쪽 순서 = 썸네일 순서", "%s vs %s" % (got, want))
    chk(mv._nav_pages is None, "저장 뒤에는 본문 넘김이 다시 파일 순서(제한 없음)", str(mv._nav_pages))
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
