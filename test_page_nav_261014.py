# -*- coding: utf-8 -*-
"""261014-1: 쪽 지우기·저장 뒤 본문이 머무는 쪽, 썸네일 ↑/↓ 차례 (마스터 §4.7.5·§4.7.7).

사용자 요청
  - 썸네일에서 쪽을 지우면 **지우지 않은 바로 위 쪽**으로 간다.
  - '저장' 하면 지금 쪽에서 움직이지 않는다(종전: 1쪽으로 돌아감).
  - 썸네일에서 쪽을 지우고·옮긴 뒤 ↑/↓ 차례가 맞지 않았다 — 지운 뒤 본문이 지운 쪽 **번호 다음**으로
    건너뛰어(쪽 번호 기준 스냅) 옮긴 순서와 어긋났다. 끼운 쪽에서 ↓ 는 `int(튜플)` 예외로 멈췄다.
실제 앱에서 키 입력·저장으로 확인한다.
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


def page_label(path, i):
    d = fitz.open(str(path))
    try:
        return d[i].get_text().split()[1]
    finally:
        d.close()


root = Path(tempfile.mkdtemp(prefix="polypdf_nav261014_"))
try:
    src = root / "M.pdf"
    d = fitz.open()
    for i in range(8):
        d.new_page().insert_text((72, 72), f"PAGE {i + 1}")
    d.set_toc([[1, "one", 1], [1, "five", 5]])
    d.save(str(src)); d.close()
    other = root / "O.pdf"
    d = fitz.open()
    for i in range(3):
        d.new_page().insert_text((72, 72), f"OTHER {i + 1}")
    d.save(str(other)); d.close()
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    _boxes = []
    QMessageBox.information = staticmethod(lambda *a, **k: (_boxes.append(a[1:3]), QMessageBox.StandardButton.Ok)[1])
    QMessageBox.warning = staticmethod(lambda *a, **k: (_boxes.append(a[1:3]), QMessageBox.StandardButton.Ok)[1])
    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1300, 900); mw.show(); app.processEvents()
    mw.open_folder(root); spin(15)
    mw._load_main(HistoryItem(str(src), 0, "", "bookmark")); spin(10)
    if not mw._in_edit():
        mw.bookmark_tree.btn_edit.setChecked(True); spin(4)
    pt, L, mv = mw.page_thumbs, mw.page_thumbs.list, mw.main_view

    def click(row):
        it = L.item(row); L.setCurrentItem(it); L.itemClicked.emit(it); spin()

    # ① Delete 키 — 바로 위 쪽으로
    click(3); L.setFocus()
    QTest.keyClick(L, Qt.Key.Key_Delete); spin()
    chk(mv.current_page() == 2 and L.currentRow() == 2,
        "① 4쪽을 지우면 바로 위 3쪽으로", "page=%d row=%d" % (mv.current_page(), L.currentRow()))
    # 맨 위를 지우면 새 첫 쪽
    click(0); QTest.keyClick(L, Qt.Key.Key_Delete); spin()
    chk(mv.current_page() == 1 and L.currentRow() == 0,
        "① 맨 위를 지우면 남은 첫 쪽", "page=%d row=%d" % (mv.current_page(), L.currentRow()))

    # ② 옮긴 뒤 지우기 — 쪽 번호가 아니라 **목록의 바로 위**
    click(4)                                                  # 7쪽(0-based 6)
    for _ in range(3):
        QTest.keyClick(L, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier); spin()
    seq = pt.current_nav_ids()
    chk(seq == [1, 6, 2, 4, 5, 7], "② 준비 — 7쪽을 위로 옮김", str(seq))
    click(4)                                                  # 6쪽(0-based 5), 위는 5쪽(0-based 4)
    pt._delete_selected(); spin()                             # 우클릭 '삭제' 와 같은 함수
    chk(mv.current_page() == 4 and L.currentRow() == 3,
        "② 옮긴 뒤 지우면 목록의 바로 위(5쪽) — 번호 다음(7쪽, 둘째 줄)이 아니다",
        "page=%d row=%d" % (mv.current_page(), L.currentRow()))

    # ③ 지우고 옮긴 뒤 ↑/↓ 는 목록 차례대로, 본문과 썸네일이 함께 간다
    L.setFocus()
    got = []
    for k in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Up, Qt.Key.Key_Up):
        QTest.keyClick(L, k); spin()
        got.append((L.currentRow(), mv.current_page()))
    # 목록 [2·7·3·5·8쪽] — 5쪽(3행)에서 ↓ 8쪽, ↑ 5·3·7쪽
    chk(got == [(4, 7), (3, 4), (2, 2), (1, 6)], "③ ↑/↓ 는 목록 차례(본문·썸네일 함께)", str(got))

    # ④ 끼운 쪽(다른 파일)으로 ↓ — 예외 없이 본문이 그 쪽으로
    pt.insert_external_pages(3, str(other), [0]); spin()
    click(3); L.setFocus()
    QTest.keyClick(L, Qt.Key.Key_Down); spin()
    chk(L.currentRow() == 4 and pt.is_staged_page(mv.current_page()),
        "④ 끼운 쪽으로 ↓ 하면 본문도 그 쪽", "row=%d page=%d" % (L.currentRow(), mv.current_page()))

    # ⑤ 쪽 편집 저장 — 저장 뒤에도 보던 쪽(새 파일의 그 자리)
    click(2)                                                  # 3쪽(0-based 2) — 새 파일의 셋째 쪽
    want_label = "3"
    # 우클릭 '저장' 과 같은 길(트리 선택을 바꾸면 그 자체가 파일 이동이라 쓰지 않는다)
    mw.bookmark_tree._op_save(file_path=str(src)); spin(15)
    chk(mv.current_page() == 2 and page_label(src, mv.current_page()) == want_label,
        "⑤ 쪽 편집 저장 뒤에도 보던 쪽(3쪽)", "page=%d" % mv.current_page())

    # ⑥ 책갈피만 저장 — 1쪽으로 돌아가지 않는다
    mv.go_to_page(4); spin()
    bt = mw.bookmark_tree
    if not mw._in_edit():
        bt.btn_edit.setChecked(True); spin(4)
    node = next(n for n in bt._iter_file_nodes() if str(n.data(0, bt.DATA_FILE)) == str(src))
    node.setExpanded(True); spin(4)
    bm = next(node.child(i) for i in range(node.childCount())
              if node.child(i).data(0, bt.DATA_PAGE) is not None)
    bm.setText(0, "renamed"); bt._dirty = True
    bt._op_save(file_path=str(src)); spin(15)
    chk(mv.current_file() and Path(mv.current_file()) == src and mv.current_page() == 4,
        "⑥ 책갈피 저장 뒤에도 지금 쪽(5쪽째)", "page=%d" % mv.current_page())
    chk(not _boxes, "저장 중 경고 창 없음", str(_boxes))
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
