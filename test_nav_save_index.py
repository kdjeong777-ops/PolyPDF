# -*- coding: utf-8 -*-
"""260902-6: 파일 경계 이동 썸네일 동기 · 편집모드 ↑/↓ 탐색 · 이동 시 페이지 편집 저장 확인 ·
폴더 인덱싱 진행 창."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)

root = Path(tempfile.mkdtemp(prefix="polypdf_nav_"))
for n, pages in (("a", 5), ("b", 3)):
    d = fitz.open()
    for i in range(pages):
        d.new_page().insert_text((40, 80), f"{n}{i}")
    d.save(str(root / f"{n}.pdf")); d.close()

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
from viewer.history import HistoryItem
mw = MainWindow(); mw.show(); app.processEvents()
mw._prefs["cross_file_nav"] = True
bt = mw.bookmark_tree; bt.load_folder(root); app.processEvents()
try: bt._sort_combo.setCurrentText(bt.SORT_NAME)
except Exception: pass
bt.btn_edit.setChecked(False); app.processEvents()
pt = mw.page_thumbs; mv = mw.main_view

# ── ① 이전 파일로 넘어가면 본문=마지막 쪽 + 썸네일도 마지막 쪽 선택 ────────
mw._load_main(HistoryItem(str(root / "b.pdf"), 0, "", "bookmark")); app.processEvents(); QTest.qWait(150)
pt.list.setFocus(); pt.list.setCurrentRow(0); app.processEvents()
QTest.keyClick(pt.list, Qt.Key.Key_Up); app.processEvents(); QTest.qWait(300); app.processEvents()
chk(Path(mv.current_file()).name == "a.pdf" and mv.current_page() == 4,
    "① ↑(첫 썸네일) → 이전 파일 마지막 쪽", f"{Path(mv.current_file()).name} p{mv.current_page()}")
chk(pt.list.currentRow() == 4, "① 썸네일 선택도 마지막 쪽(row 4)", f"row={pt.list.currentRow()}")
QTest.keyClick(pt.list, Qt.Key.Key_Down); app.processEvents(); QTest.qWait(300); app.processEvents()
chk(Path(mv.current_file()).name == "b.pdf" and mv.current_page() == 0 and pt.list.currentRow() == 0,
    "① ↓(끝 썸네일) → 다음 파일 첫 쪽 + 썸네일 row 0")

# ── ② 편집모드: ↑/↓ 는 탐색, Alt+↑/↓ 만 페이지 순서 이동 ────────────────────
mw._load_main(HistoryItem(str(root / "a.pdf"), 0, "", "bookmark")); app.processEvents(); QTest.qWait(150)
bt.btn_edit.setChecked(True); app.processEvents()
pt.list.setFocus(); pt.list.setCurrentRow(1); app.processEvents()
seq0 = pt.current_page_sequence()
QTest.keyClick(pt.list, Qt.Key.Key_Down); app.processEvents()
chk(pt.current_page_sequence() == seq0 and pt.list.currentRow() == 2 and mv.current_page() == 2,
    "② 편집모드 ↓ = 탐색(순서 불변, 본문 동기)", f"seq={pt.current_page_sequence()} row={pt.list.currentRow()}")
QTest.keyClick(pt.list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier); app.processEvents()
chk(pt.current_page_sequence() == [0, 2, 1, 3, 4],
    "② Alt+↑ = 선택 페이지 한 칸 위로(재배열)", f"{pt.current_page_sequence()}")
chk(pt.is_page_dirty(), "② 재배열 후 페이지 편집 dirty")

# ── ③ 페이지 편집 미저장 상태로 다른 파일 이동 → 확인창 ─────────────────────
asked = []
mw._confirm_edit_save = lambda switching=False: (asked.append(switching), "cancel")[1]
mw._load_main(HistoryItem(str(root / "b.pdf"), 0, "", "bookmark")); app.processEvents()
chk(asked == [True] and Path(mv.current_file()).name == "a.pdf",
    "③ 페이지 편집 미저장 + 다른 파일 → 확인창, '계속 편집'이면 이동 취소", f"{asked}")
# 되돌리기 → 썸네일 원상복구 후 이동
asked.clear(); mw._confirm_edit_save = lambda switching=False: "discard"
mw._load_main(HistoryItem(str(root / "b.pdf"), 0, "", "bookmark")); app.processEvents(); QTest.qWait(150)
chk(Path(mv.current_file()).name == "b.pdf", "③ '되돌리기' → 편집 버리고 이동")
mw._load_main(HistoryItem(str(root / "a.pdf"), 0, "", "bookmark")); app.processEvents(); QTest.qWait(150)
chk(pt.current_page_sequence() == [0, 1, 2, 3, 4] and not pt.is_page_dirty(),
    "③ 되돌린 파일을 다시 열면 원래 순서(디스크 상태)", f"{pt.current_page_sequence()}")
# 저장 → 현재 파일 기준으로 저장되는지(트리 선택은 새 파일이어도)
pt.list.setCurrentRow(0); app.processEvents()
QTest.keyClick(pt.list, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier); app.processEvents()   # 0↔1
chk(pt.current_page_sequence() == [1, 0, 2, 3, 4], "③ 저장 시험용 재배열", f"{pt.current_page_sequence()}")
saved = []
mw._page_edit_save = lambda src, raw: saved.append(Path(src).name)
mw._confirm_edit_save = lambda switching=False: "save"
bt.tree.clearSelection()
for node in bt._iter_file_nodes():                 # 트리 선택을 '새 파일'로 옮겨 둔다(실사용 순서)
    if node.text(0) == "b": bt.tree.setCurrentItem(node)
mw._load_main(HistoryItem(str(root / "b.pdf"), 0, "", "bookmark")); app.processEvents()
chk(saved == ["a.pdf"], "③ '저장' → 트리 선택(b)이 아니라 **편집한 현재 파일(a)** 에 저장", f"{saved}")
bt.btn_edit.setChecked(False); app.processEvents()

# ── ④ 인덱싱 진행 창 ───────────────────────────────────────────────────────
from viewer.widgets.indexing_dialog import IndexingDialog
dlg = IndexingDialog(mw, "표본폴더"); dlg.start()
chk(not dlg.isVisible(), "④ 시작 직후엔 보이지 않음(짧은 인덱싱 깜빡임 방지)")
QTest.qWait(IndexingDialog.SHOW_DELAY_MS + 200); app.processEvents()
chk(dlg.isVisible(), "④ 지연 뒤 아직 진행 중이면 표시")
dlg.on_progress(3, 10, "x.pdf"); app.processEvents()
chk(dlg.bar.maximum() == 10 and dlg.bar.value() == 3 and "x.pdf" in dlg.lbl_file.text(), "④ 진행률·파일명 갱신")
chk("느려질 수 있으니" in dlg.lbl_hint.text() and "끝난 뒤에 작업" in dlg.lbl_hint.text(),
    "④ 안내 문구(느려질 수 있음·끝난 뒤 작업 권장)")
chk(not dlg.btn_hide.autoDefault() and not dlg.btn_hide.isDefault(), "④ 숨기기 버튼 Enter 비기본(디자인 §2.7)")
dlg.btn_hide.click(); app.processEvents()
chk(not dlg.isVisible() and dlg._hidden_by_user, "④ [아래로 숨기기] → 창만 닫힘")
dlg2 = IndexingDialog(mw); dlg2.start(); dlg2.on_finished()
shown = []
try:
    QTest.qWait(IndexingDialog.SHOW_DELAY_MS + 200); app.processEvents()
    shown.append(dlg2.isVisible())          # deleteLater 전이면 False 여야 한다
except RuntimeError:
    shown.append(False)                     # 이미 정리(deleteLater)됨 = 뜨지 않았음
chk(shown == [False], "④ 지연 안에 끝나면 아예 뜨지 않음(정리까지)")
# 앱 연동: 폴더 워커에는 붙고, 단일 파일 워커에는 안 붙음
from viewer.workers import IndexWorker
class _W(IndexWorker):
    pass
w_folder = IndexWorker(mw._db_path, root)
mw._attach_indexing_dialog(w_folder)
chk(getattr(mw, "_indexing_dialog", None) is not None, "④ 폴더 인덱싱 워커 → 진행 창 부착")
mw._close_indexing_dialog()
w_single = IndexWorker(mw._db_path, root, single_file=root / "a.pdf")
mw._attach_indexing_dialog(w_single)
chk(getattr(mw, "_indexing_dialog", None) is None, "④ 단일 파일 인덱싱엔 창 없음(상태바만)")
chk(mw.status.currentMessage() is not None, "④ 상태바 메시지 경로 유지")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
