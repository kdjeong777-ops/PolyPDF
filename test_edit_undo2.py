# -*- coding: utf-8 -*-
"""261012-10: 편집 모드 되돌리기 2단계 — 책갈피·쪽 편집·숨김·회전·하이퍼링크·크롭을 같은 기록에 (마스터 §4.6.8).

A. 썸네일 쪽 이동 → Ctrl+Z 원래 차례 · Ctrl+Y 다시
B. 쪽 숨김 → Ctrl+Z 해제
C. 쪽을 옮긴 뒤 회전 — 옮긴 차례가 남는다(종전: 말없이 사라짐) · Ctrl+Z 는 회전만 되돌린다
D. 하이퍼링크 추가 → Ctrl+Z 사라짐
E. 저장 전 크롭 → Ctrl+Z 크롭 없음(문서 크기 원래대로)
F. 책갈피 삭제 → Ctrl+Z 다시 있음 · ↷ 로 다시 삭제
G. 차례 — 숨김 → 선 그리기 → Ctrl+Z 는 선부터, 다시 Ctrl+Z 면 숨김
H. 편집 모드 끄기에서 책갈피창 확인 창 '취소' → 확인 창은 하나뿐, 모두 편집 모드에 남는다(종전: 둘·어긋남)
I. [취소] 는 연 파일만 되돌린다 — 같은 폴더 다른 파일의 바뀐 것은 그대로(종전: 폴더 전체)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_undo2_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


root = Path(tempfile.mkdtemp(prefix="undo2_"))
try:
    folder = root / "f"; folder.mkdir()
    pdf, other = folder / "a.pdf", folder / "b.pdf"
    for p_ in (pdf, other):
        d = fitz.open()
        for i in range(4):
            d.new_page(width=595, height=842).insert_text((72, 400), "%s P%d" % (p_.stem, i + 1))
        d.set_toc([[1, "첫째", 1], [1, "둘째", 2], [1, "셋째", 3]])
        d.save(str(p_)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 900); mw.show(); mw.activateWindow(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw.open_pdfs([str(pdf)]); spin(1.0)
    mv = mw.main_view
    asked = []
    QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[1] if len(a) > 1 else ""), QMessageBox.StandardButton.Yes)[1])
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    mw.bookmark_tree.btn_edit.setChecked(True); spin(0.3)
    pt = mw.page_thumbs
    st = mw._ensure_page_meta_store()

    def undo():
        mv.view.setFocus(); QTest.keyClick(mv.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier); spin(0.4)

    def redo():
        mv.view.setFocus(); QTest.keyClick(mv.view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier); spin(0.4)

    def plan():
        return [e[1] for e in pt.current_page_plan()]

    # A — 쪽 이동
    pt.list.clearSelection(); pt.list.setCurrentRow(0); pt.list.item(0).setSelected(True)
    pt._move_selected(+1); spin(0.3)
    chk(plan()[:2] == [1, 0], "A0 쪽 이동(저장 안 함)", str(plan()))
    undo()
    chk(plan()[:2] == [0, 1] and not pt.is_page_dirty(), "A1 Ctrl+Z → 원래 차례", str(plan()))
    redo()
    chk(plan()[:2] == [1, 0], "A2 Ctrl+Y → 다시 옮긴 차례", str(plan()))
    undo()

    # B — 쪽 숨김
    mw._set_pages_hidden([2], True); spin(0.1)
    chk(st.is_hidden(str(pdf), 2), "B0 쪽 숨김")
    undo()
    chk(not st.is_hidden(str(pdf), 2), "B1 Ctrl+Z → 숨김 해제")

    # C — 쪽을 옮긴 뒤 회전: 옮긴 차례가 남는다
    pt.list.clearSelection(); pt.list.setCurrentRow(0); pt.list.item(0).setSelected(True)
    pt._move_selected(+1); spin(0.3)
    mw._rotate_pages([3], 90); spin(1.0)
    pt = mw.page_thumbs
    chk(plan()[:2] == [1, 0] and st.get_rotation(str(pdf), 3) == 90,
        "C1 쪽을 옮긴 뒤 회전해도 옮긴 차례가 남는다(종전: 말없이 사라짐)", str(plan()))
    undo()
    chk(st.get_rotation(str(pdf), 3) == 0 and plan()[:2] == [1, 0], "C2 Ctrl+Z 는 회전만 되돌린다", str((plan(), st.get_rotation(str(pdf), 3))))
    undo()
    chk(plan()[:2] == [0, 1], "C3 다시 Ctrl+Z → 쪽 이동도 되돌린다", str(plan()))

    # D — 하이퍼링크
    import viewer.widgets.hyperlink_dialog as hd
    hl = mw._ensure_hyperlink_store()
    _orig = hd.HyperlinkDialog.exec
    hd.HyperlinkDialog.exec = lambda self: (hl.add_url_link(str(pdf), 0, "영상", "https://www.youtube.com/watch?v=x"), 0)[1]
    mw._open_hyperlink_dialog(str(pdf), 0); spin(0.1)
    hd.HyperlinkDialog.exec = _orig
    chk(len(hl.links_for(str(pdf), 0)) == 1, "D0 하이퍼링크 추가")
    undo()
    chk(not hl.links_for(str(pdf), 0), "D1 Ctrl+Z → 하이퍼링크 사라짐")

    # E — 저장 전 크롭
    from viewer import page_crop as pc
    from viewer.widgets import crop_dialog as cd

    def fake_exec(dlg):
        dlg.rb_cur.setChecked(True)
        dlg.cmb_style.setCurrentIndex(dlg.cmb_style.findData("portrait"))
        dlg.chk_auto.setChecked(False)
        dlg.spins[0].setValue(20.0)
        dlg._accept_crop()
        return QDialog.DialogCode.Accepted
    cd.CropDialog.exec = fake_exec
    mv.go_to_page(0); spin(0.2)
    mv.btn_crop.click(); spin(1.5)
    mv = mw.main_view
    chk(pc.has_pending(pdf) and round(mv._doc.doc[0].rect.height) == round(842 * 0.8), "E0 저장 전 크롭")
    undo(); spin(0.8)
    mv = mw.main_view
    chk(not pc.has_pending(pdf) and round(mv._doc.doc[0].rect.height) == 842, "E1 Ctrl+Z → 크롭 없음(문서 크기 원래대로)",
        str(mv._doc.doc[0].rect))

    # F — 책갈피 삭제
    bt = mw.bookmark_tree
    fnode = next(n for n in bt._iter_file_nodes() if Path(str(n.data(0, bt.DATA_FILE))).name == "a.pdf")
    fnode.setExpanded(True); spin(0.4)
    kids = [fnode.child(i).text(0) for i in range(fnode.childCount())]
    target = next((fnode.child(i) for i in range(fnode.childCount()) if fnode.child(i).text(0) == "둘째"), None)
    chk(target is not None, "F0 책갈피가 읽혔다", str(kids))
    bt.tree.clearSelection(); bt.tree.setCurrentItem(target); spin(0.1)
    bt.tree.clearSelection(); target.setSelected(True); spin(0.1)
    chk([i.text(0) for i in bt.tree.selectedItems()] == ["둘째"], "F0b 책갈피 하나만 골랐다(파일 행은 아님)", str([i.text(0) for i in bt.tree.selectedItems()]))
    bt._op_delete(); spin(0.2)
    now = [fnode.child(i).text(0) for i in range(fnode.childCount())]
    chk("둘째" not in now and bt._dirty, "F1 책갈피 삭제", str(now))
    undo()
    fnode = next(n for n in bt._iter_file_nodes() if Path(str(n.data(0, bt.DATA_FILE))).name == "a.pdf")
    now = [fnode.child(i).text(0) for i in range(fnode.childCount())]
    chk(now == kids, "F2 Ctrl+Z → 책갈피가 다시 있다", str(now))
    mv._redo_btn.click(); spin(0.3)
    now = [fnode.child(i).text(0) for i in range(fnode.childCount())]
    chk("둘째" not in now, "F3 ↷ 로 다시 삭제", str(now))
    undo()

    # G — 차례(시간순)
    mw._set_pages_hidden([1], True); spin(0.05)
    mv = mw.main_view
    mv.go_to_page(0); spin(0.2)
    mv._page_strokes.append({"color": "#f00", "width": 3, "alpha": 100, "points": [[0.1, 0.1], [0.3, 0.2]]})
    mv._save_page_strokes(); spin(0.05)
    undo()
    chk(not st.get_drawings(str(pdf), 0) and st.is_hidden(str(pdf), 1), "G1 Ctrl+Z 는 나중에 한 선부터")
    undo()
    chk(not st.is_hidden(str(pdf), 1), "G2 다시 Ctrl+Z → 그 전의 숨김")

    # H — 편집 모드 끄기: 책갈피창 확인 창 '취소'
    QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[1] if len(a) > 1 else ""), QMessageBox.StandardButton.Cancel)[1])
    boxes = []
    _qexec = QMessageBox.exec
    QMessageBox.exec = lambda self: (boxes.append(self.windowTitle()), 0)[1]
    asked.clear()
    bt._dirty = True
    mw._set_pages_hidden([3], True); spin(0.05)
    bt.btn_edit.setChecked(False); spin(0.3)
    chk(len(asked) + len(boxes) == 1 and bt.is_edit_mode() and mw.page_thumbs._edit_mode and mw.main_view._img_edit,
        "H 책갈피창에서 '취소' → 확인 창은 하나뿐, 책갈피·썸네일·그리기 모두 편집 모드에 남는다",
        str((asked, boxes, bt.is_edit_mode(), mw.page_thumbs._edit_mode, mw.main_view._img_edit)))
    QMessageBox.exec = _qexec
    bt._dirty = False

    # I — [취소] 는 연 파일만
    st.set_hidden(str(other), [2], True)          # 같은 폴더 다른 파일(이 편집과 무관하게 바뀜)
    mw._set_pages_hidden([0], True); spin(0.05)
    mw._on_edit_cancelled(); spin(0.6)
    chk(not st.is_hidden(str(pdf), 0) and st.is_hidden(str(other), 2),
        "I [취소] → 연 파일(a)만 되돌리고 다른 파일(b)의 바뀐 것은 그대로(종전: 폴더 전체)",
        str((sorted(st.hidden_pages(str(pdf))), sorted(st.hidden_pages(str(other))))))
    chk(not mw.edit_can_undo(), "I2 [취소] 뒤에는 되돌릴 것이 없다")
    mw._confirm_edit_save = lambda *a, **k: "discard"
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
    bt.btn_edit.setChecked(False); spin(0.3)
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
