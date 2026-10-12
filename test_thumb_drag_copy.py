# -*- coding: utf-8 -*-
"""261012-11·12: 크롭·서명 단추는 편집 모드에서만 · 고른 꾸밈의 우클릭은 그 옵션만 · 썸네일 끌어 다른 파일로 복사 (마스터 §4.6.9·§4.7.18).

A. 크롭·서명 단추 — 편집 모드가 아니면 숨김, 편집 모드면 보임
B. 글상자를 고르고 우클릭 → 그 옵션만(텍스트 복사·인쇄·발표 등 없음) · '선과 텍스트 입력 설정…' 은 글쓰기 탭으로 · 사진이면 사진 옵션
C. a.pdf 썸네일 2쪽을 끌어(실제 끌기 자료) 책갈피창 b.pdf 의 '둘째' 책갈피 위에 머묾 → b.pdf 2쪽이 본문·썸네일에
D. b.pdf 썸네일 위로 움직이면 놓일 자리 표시 → 놓으면 그 아래에 끼운 쪽 2개(a.pdf 의 쪽), 원본 파일은 그대로 · [저장] 뒤 b.pdf 가 6쪽
E. 같은 파일 안 끌기는 가로채지 않는다(종전 순서 바꾸기) · 편집 모드가 아니면 받지 않는다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QEvent, QPoint, QPointF
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu, QDialog
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QPixmap, QColor

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_dragcopy_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


root = Path(tempfile.mkdtemp(prefix="dragcopy_"))
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
    mw._on_bookmark_activated(str(a), 0); spin(1.0)      # 폴더 목록을 둔 채 a.pdf 를 연다(책갈피창에 b.pdf 도 있게)
    mv = mw.main_view
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)

    # A — 단추(설정 '시작 모드' 기본이 편집이라 열면 편집 모드 — 먼저 끈다)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    mw.bookmark_tree.btn_edit.setChecked(False); spin(0.3)
    chk(not mw.bookmark_tree.is_edit_mode() and mv.btn_crop.isHidden() and mv.btn_sign.isHidden(),
        "A1 편집 모드가 아니면 크롭·서명 단추를 숨긴다")
    mw.bookmark_tree.btn_edit.setChecked(True); spin(0.3)
    chk(mv.btn_crop.isVisible() and mv.btn_sign.isVisible(), "A2 편집 모드면 보인다")

    # B — 고른 개체의 우클릭
    TB = {"text_box": True, "rect": [0.10, 0.10, 0.40, 0.16], "text": "MENU", "size_pt": 14}
    mv._page_strokes = [dict(TB)]; mv._save_page_strokes()
    pr = mv._page_view_rect()
    seen = []
    pick = {"t": None}

    def _mexec(self, *a_, **k):
        seen.append([x.text() for x in self.actions()])
        return next((x for x in self.actions() if pick["t"] and x.text() == pick["t"]), None)
    _orig_mexec = QMenu.exec
    QMenu.exec = _mexec
    g = mv.view.viewport().mapToGlobal(mv._norm_to_view(0.25, 0.13, pr))
    tabs = {}
    import viewer.widgets.line_text_settings_dialog as ltd
    _orig_lexec = ltd.LineTextSettingsDialog.exec
    ltd.LineTextSettingsDialog.exec = lambda self: (tabs.setdefault("i", self._tabs.currentIndex()), 0)[1]
    pick["t"] = "선과 텍스트 입력 설정…"
    mw._on_viewer_context_menu(g); spin(0.1)
    labels = seen[-1] if seen else []
    chk(mv._stroke_selected == 0 and "복사 (Ctrl+C)" in labels and "선택 글상자 삭제 (Del)" in labels
        and "텍스트 복사" not in labels and "발표보기" not in labels and "여기에 서명…" not in labels,
        "B1 글상자 우클릭 → 그 옵션만(텍스트 복사·발표·서명 등 없음)", str(labels))
    chk(tabs.get("i") == 1, "B2 '선과 텍스트 입력 설정…' 은 글쓰기 탭으로 연다", str(tabs))
    pick["t"] = None
    pix = QPixmap(40, 20); pix.fill(QColor("blue"))
    mv._page_strokes = []; mv._save_page_strokes()
    mv.add_image_from_pixmap(pix); spin(0.05)
    mv._img_selected = -1
    rc = mv._img_objects[0]["rect"]
    g = mv.view.viewport().mapToGlobal(mv._norm_to_view(rc[0] + rc[2] / 2, rc[1] + rc[3] / 2, pr))
    mw._on_viewer_context_menu(g); spin(0.1)
    labels = seen[-1] if seen else []
    chk("선택 사진 모양 변경" in labels and "선택 이미지 삭제 (Del)" in labels and "선과 텍스트 입력 설정…" not in labels,
        "B3 사진 우클릭 → 사진 옵션", str(labels))
    mv._img_objects = []; mv._save_page_images(); mv._img_selected = -1
    mv._multi_clear(); mv._stroke_selected = -1
    g = mv.view.viewport().mapToGlobal(mv._norm_to_view(0.7, 0.8, pr))
    mw._on_viewer_context_menu(g); spin(0.1)
    chk("텍스트 복사" in (seen[-1] if seen else []), "B4 빈 곳(고른 것 없음)은 종전 메뉴", str((seen[-1] if seen else [])[:3]))
    QMenu.exec = _orig_mexec
    ltd.LineTextSettingsDialog.exec = _orig_lexec

    # C — 끌기 자료(실제 mimeData) → 책갈피창 b.pdf '둘째' 위에 머묾
    pt = mw.page_thumbs
    pt.list.clearSelection()
    pt.list.item(0).setSelected(True); pt.list.item(1).setSelected(True)
    md = pt.list.mimeData(pt.list.selectedItems())
    from viewer.widgets.thumbs_list import pages_from_mime
    got = pages_from_mime(md)
    chk(got and got[0] == str(a) and got[1] == [(str(a), 0), (str(a), 1)], "C0 끌기 자료에 '어느 파일의 몇 쪽'", str(got))
    bt = mw.bookmark_tree
    bnode = next(n for n in bt._iter_file_nodes() if Path(str(n.data(0, bt.DATA_FILE))).name == "b.pdf")
    bnode.setExpanded(True); spin(0.4)
    print("  (info) b.pdf 자식:", [bnode.child(i).text(0) for i in range(bnode.childCount())])
    tgt = next(bnode.child(i) for i in range(bnode.childCount()) if bnode.child(i).text(0) == "둘째")
    bt.tree.scrollToItem(tgt); spin(0.1)
    p = bt.tree.visualItemRect(tgt).center()
    acts = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    tv = bt.tree.viewport()
    e1 = QDragEnterEvent(p, acts, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(tv, e1)
    e2 = QDragMoveEvent(p, acts, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(tv, e2)
    chk(e2.isAccepted(), "C1 책갈피창이 끄는 썸네일을 받아 들인다(머묾을 알려면)")
    spin(1.2)
    chk(Path(str(mw.main_view.current_file())).name == "a.pdf",
        "C1b 저장 안 한 편집(B 의 꾸밈)이 있으면 다른 파일을 열지 않는다(끌기 중 확인 창을 띄울 수 없다)")
    mw._save_meta_from_button(); spin(0.2)                    # 꾸밈 저장 → 이제 열 수 있다
    QApplication.sendEvent(tv, QDragMoveEvent(p + QPoint(0, 1), acts, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    bt._drag_hover_item = None
    QApplication.sendEvent(tv, QDragMoveEvent(p, acts, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    spin(1.2)
    mv = mw.main_view
    pt = mw.page_thumbs
    chk(Path(str(mv.current_file())).name == "b.pdf" and mv.current_page() == 1,
        "C2 머물면 b.pdf 의 '둘째'(2쪽)가 본문에", str((mv.current_file(), mv.current_page())))
    chk(pt._doc is not None and Path(str(pt._doc.path)).name == "b.pdf" and pt.list.currentRow() == 1,
        "C3 썸네일도 b.pdf · 2쪽이 골라져 있다", str(pt.list.currentRow()))

    # D — 썸네일 위로 → 놓기
    lv = pt.list.viewport()
    r1 = pt.list.visualItemRect(pt.list.item(1)).center()
    em = QDragMoveEvent(r1, acts, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(lv, QDragEnterEvent(r1, acts, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QApplication.sendEvent(lv, em)
    chk(em.isAccepted() and em.dropAction() == Qt.DropAction.CopyAction and pt.list.currentRow() == 1,
        "D1 썸네일 위 — 복사로 받고 놓일 자리(2쪽 아래)를 표시")
    ed = QDropEvent(QPointF(r1), acts, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(lv, ed); spin(0.4)
    plan = pt.current_page_plan()
    chk(plan[:4] == [("own", 0), ("own", 1), ("ext", str(a), 0), ("ext", str(a), 1)] and ed.dropAction() == Qt.DropAction.CopyAction,
        "D2 놓으면 2쪽 아래에 a.pdf 의 두 쪽이 끼운 쪽으로(복사)", str(plan[:5]))
    chk(fitz.open(str(b)).page_count == 4 and fitz.open(str(a)).page_count == 4, "D3 저장 전 — 두 원본 파일은 그대로")
    sel = [n for n in bt._iter_file_nodes() if Path(str(n.data(0, bt.DATA_FILE))).name == "b.pdf"]
    bt.tree.setCurrentItem(sel[0]); spin(0.6)
    bt.btn_save.click(); spin(2.0)
    with fitz.open(str(b)) as o:
        txt = [o[i].get_text().strip() for i in range(o.page_count)]
    chk(len(txt) == 6 and txt[2].startswith("A P1") and txt[3].startswith("A P2"), "D4 [저장] → b.pdf 6쪽, 3·4쪽이 a.pdf 1·2쪽", str(txt))

    # E — 같은 파일 끌기는 가로채지 않는다 · 편집 모드 아니면 받지 않는다
    mw._on_bookmark_activated(str(b), 0); spin(0.8)
    pt = mw.page_thumbs
    md2 = pt.list.mimeData([pt.list.item(0)])
    r0 = pt.list.visualItemRect(pt.list.item(0)).center()
    calls = []
    pt.pagesDropped.connect(lambda r, it: calls.append((r, it)))
    ev = QDropEvent(QPointF(r0), acts, md2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    handled = pt.eventFilter(pt.list.viewport(), ev)
    chk(not handled and not calls, "E1 같은 파일 안 끌기는 가로채지 않는다(종전 순서 바꾸기)")
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    mw.bookmark_tree.btn_edit.setChecked(False); spin(0.3)
    ev2 = QDropEvent(QPointF(r0), acts, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    handled = pt.eventFilter(pt.list.viewport(), ev2)
    chk(handled and not ev2.isAccepted() and not calls, "E2 편집 모드가 아니면 받지 않는다(알림)")
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
