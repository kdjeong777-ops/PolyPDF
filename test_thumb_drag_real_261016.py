# -*- coding: utf-8 -*-
"""261016-1: 썸네일 여러 장을 끌어 다른 파일 썸네일에 놓으면 끈 쪽이 **모두** 남는다 (마스터 §4.7.18).

사용자 보고: 썸네일 여러 장을 끌어 책갈피창의 다른 파일에 머물렀다가 그 파일 썸네일에 놓으면 **일부만** 붙었다.
원인: 썸네일 목록이 끌기의 출발지이자 도착지다. 편집 모드 끌기는 `InternalMove` 라 Qt 가 **옮기기만** 내놓는다
(`QAbstractItemView.startDrag` 가 복사를 뺀다) — 그래서 받는 쪽의 '복사로 받기' 가 먹지 않았고, 끌기가 옮기기로
끝나면 Qt 는 놓인 곳이 제 뷰포트일 때 **그 순간 골라져 있는 행을 지운다**(`clearOrRemove`). 놓은 뒤 첫 끼운 쪽을
골라 두므로 그 쪽이 지워졌다. `test_thumb_drag_copy.py` 는 복사·옮기기를 **둘 다** 내놓는 끌기로 시험해 못 잡았다.

offscreen 에서는 `QDrag.exec` 가 곧바로 끝나 진짜 마우스 끌기를 돌릴 수 없다 — 그래서 Qt 가 내놓는 그대로
(**옮기기만**) 끌기 이벤트를 실제 처리기에 보내고, 놓은 결과가 옮기기면 Qt 가 하는 일(고른 행 지우기)을 그대로 흉내 낸다.

A. a.pdf 썸네일 3쪽 → 책갈피창 b.pdf 위 머묾(b.pdf 가 열린다) → b.pdf 2쪽 썸네일에 놓기
   A1 b.pdf 가 썸네일에 · A2 놓은 결과가 옮기기가 아니다(Qt 가 행을 지우지 않는다)
   A3 Qt 의 뒤처리 뒤에도 끈 세 쪽이 모두, 2쪽 아래 차례대로 · A4 b.pdf 자기 쪽 넷 그대로
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPoint, QPointF
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_dragreal_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


MOVE_ONLY = Qt.DropAction.MoveAction            # InternalMove 끌기가 내놓는 것(Qt 가 복사를 뺀다)
LB, NOMOD = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier

root = Path(tempfile.mkdtemp(prefix="dragreal_"))
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", folder / "b.pdf"
    for p_ in (a, b):
        d = fitz.open()
        for i in range(4):
            d.new_page(width=595, height=842).insert_text((72, 400), "%s P%d" % (p_.stem.upper(), i + 1))
        d.set_toc([[1, "첫째", 1], [1, "둘째", 2]])
        d.save(str(p_)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); mw.activateWindow(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    bt = mw.bookmark_tree
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)
    pt = mw.page_thumbs
    chk(pt._edit_mode and pt.list.dragDropMode() == pt.list.DragDropMode.InternalMove,
        "0 편집 모드 — 썸네일 끌기는 InternalMove")

    pt.list.clearSelection()
    for r in (0, 1, 2):
        pt.list.item(r).setSelected(True)
    md = pt.list.mimeData(pt.list.selectedItems())       # 끌기 시작 때 Qt 가 부르는 그것

    # 책갈피창 b.pdf 위에 머묾
    bnode = next(n for n in bt._iter_file_nodes() if Path(str(n.data(0, bt.DATA_FILE))).name == "b.pdf")
    bt.tree.scrollToItem(bnode); spin(0.1)
    p = bt.tree.visualItemRect(bnode).center()
    tv = bt.tree.viewport()
    QApplication.sendEvent(tv, QDragEnterEvent(p, MOVE_ONLY, md, LB, NOMOD))
    QApplication.sendEvent(tv, QDragMoveEvent(p, MOVE_ONLY, md, LB, NOMOD))
    spin(bt.DRAG_HOVER_MS / 1000.0 + 0.8)
    pt = mw.page_thumbs
    chk(pt._doc is not None and Path(str(pt._doc.path)).name == "b.pdf", "A1 머물면 b.pdf 가 썸네일에",
        str(pt._doc and pt._doc.path))

    # b.pdf 2쪽 썸네일에 놓기
    lv = pt.list.viewport()
    r1 = pt.list.visualItemRect(pt.list.item(1)).center()
    QApplication.sendEvent(lv, QDragEnterEvent(r1, MOVE_ONLY, md, LB, NOMOD))
    QApplication.sendEvent(lv, QDragMoveEvent(r1, MOVE_ONLY, md, LB, NOMOD))
    ed = QDropEvent(QPointF(r1), MOVE_ONLY, md, LB, NOMOD)
    QApplication.sendEvent(lv, ed); spin(0.3)
    result = ed.dropAction() if ed.isAccepted() else Qt.DropAction.IgnoreAction
    chk(ed.isAccepted() and result != Qt.DropAction.MoveAction,
        "A2 놓은 결과가 옮기기가 아니다(Qt 가 고른 행을 지우지 않는다)", str(result))
    # Qt 의 뒤처리 흉내 — QAbstractItemView.startDrag: 결과가 옮기기이고 놓인 곳이 제 뷰포트면 고른 행을 지운다
    if result == Qt.DropAction.MoveAction:
        for it in sorted(pt.list.selectedItems(), key=pt.list.row, reverse=True):
            pt.list.takeItem(pt.list.row(it))
    plan = pt.current_page_plan()
    ext = [x for x in plan if x[0] == "ext"]
    chk(len(ext) == 3 and [x[2] for x in ext] == [0, 1, 2] and all(x[1] == str(a) for x in ext)
        and plan[:2] == [("own", 0), ("own", 1)] and plan[2:5] == ext,
        "A3 끈 세 쪽이 **모두** 2쪽 아래 차례대로", str(plan))
    chk(len([x for x in plan if x[0] == "own"]) == 4, "A4 b.pdf 자기 쪽 넷 그대로", str(plan))
    mw._confirm_close_edit = lambda: True
    mw.close(); spin(0.2)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
