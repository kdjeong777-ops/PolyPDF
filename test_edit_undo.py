# -*- coding: utf-8 -*-
"""261012-7: 편집 모드 되돌리기/다시실행 1단계 — 꾸밈 전체, 파일 단위 기록 (마스터 §4.6.8).

A. 1쪽에 선, 2쪽에 사진 → (1쪽에서) Ctrl+Z → 2쪽 사진이 사라지고 2쪽으로 간다(쪽을 넘겨도 기록이 남는다·사진도 된다)
B. 다시 Ctrl+Z → 1쪽 선이 사라지고 1쪽으로 · Ctrl+Y → 선이 돌아온다
C. 범위 선택으로 선+사진을 함께 지우기 → Ctrl+Z 한 번에 둘 다 돌아온다
D. Ctrl+Z 는 책갈피창에 포커스가 있어도 된다(창 어디서나) · ↶ 단추도 같은 기록 · 단추가 켜고 꺼짐
E. 편집 모드를 끄면 기록이 비워진다 · 편집 모드가 아니면 Ctrl+Z 는 아무것도 안 한다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QPixmap, QColor
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_undo_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


root = Path(tempfile.mkdtemp(prefix="undo_"))
try:
    folder = root / "f"; folder.mkdir()
    pdf = folder / "u.pdf"
    d = fitz.open()
    for i in range(3):
        d.new_page(width=595, height=842).insert_text((72, 400), "P%d" % (i + 1))
    d.save(str(pdf)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 900); mw.show(); mw.activateWindow(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw.open_pdfs([str(pdf)]); spin(1.0)
    mv = mw.main_view
    mw.bookmark_tree.btn_edit.setChecked(True); spin(0.3)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard)
    mw._confirm_edit_save = lambda *a, **k: "discard"      # 편집 모드 끄기 확인 창(이 검사의 대상 아님)

    def activate():
        mw.raise_(); mw.activateWindow()
        for _ in range(20):
            if QApplication.activeWindow() is mw:
                return True
            spin(0.05)
        return QApplication.activeWindow() is mw
    LINE = {"color": "#f00", "width": 3, "alpha": 100, "points": [[0.1, 0.1], [0.3, 0.2]]}

    def ctrl(key, w=None):
        QTest.keyClick(w or mv.view, key, Qt.KeyboardModifier.ControlModifier); spin(0.15)

    mv.go_to_page(0); spin(0.2)
    mv._page_strokes.append(dict(LINE)); mv._save_page_strokes(); spin(0.05)
    mv.go_to_page(1); spin(0.2)
    pix = QPixmap(40, 20); pix.fill(QColor("blue"))
    mv.add_image_from_pixmap(pix); spin(0.05)
    st = mw._ensure_page_meta_store()
    chk(len(st.get_drawings(str(pdf), 0)) == 1 and len(st.get_images(str(pdf), 1)) == 1, "준비 — 1쪽 선 · 2쪽 사진")
    mv.go_to_page(0); spin(0.2)
    mv.view.setFocus()
    ctrl(Qt.Key.Key_Z)
    chk(len(st.get_images(str(pdf), 1)) == 0 and mv.current_page() == 1 and not mv._img_objects,
        "A Ctrl+Z → 2쪽 사진이 사라지고 2쪽으로 간다(쪽을 넘겨도 기록·사진도)", str((mv.current_page(), len(st.get_images(str(pdf), 1)))))
    ctrl(Qt.Key.Key_Z)
    chk(len(st.get_drawings(str(pdf), 0)) == 0 and mv.current_page() == 0 and not mv._page_strokes,
        "B1 다시 Ctrl+Z → 1쪽 선이 사라지고 1쪽으로", str(mv.current_page()))
    ctrl(Qt.Key.Key_Y)
    chk(len(st.get_drawings(str(pdf), 0)) == 1 and len(mv._page_strokes) == 1, "B2 Ctrl+Y → 선이 돌아온다")

    # C — 선 + 사진을 범위로 함께 지우기 → 한 번에
    mv.add_image_from_pixmap(pix); spin(0.05)
    mv._multi_strokes = [0]; mv._multi_images = [0]
    mv._multi_delete(); spin(0.05)
    chk(not st.get_drawings(str(pdf), 0) and not st.get_images(str(pdf), 0), "C0 범위 지우기 — 둘 다 지워졌다")
    ctrl(Qt.Key.Key_Z)
    chk(len(st.get_drawings(str(pdf), 0)) == 1 and len(st.get_images(str(pdf), 0)) == 1,
        "C Ctrl+Z 한 번에 선·사진 둘 다 돌아온다(한 동작 = 한 단계)",
        str((len(st.get_drawings(str(pdf), 0)), len(st.get_images(str(pdf), 0)))))

    # D — 창 어디서나 · ↶ 단추
    chk(activate(), "D0 (전제) 창이 활성 — 창 단축키가 전달된다")
    mw.bookmark_tree.tree.setFocus(); spin(0.05)
    ctrl(Qt.Key.Key_Z, mw.bookmark_tree.tree)
    chk(len(st.get_drawings(str(pdf), 0)) == 1 and not st.get_images(str(pdf), 0),
        "D1 책갈피창에 포커스가 있어도 Ctrl+Z 가 된다(앞 단계 '사진 넣기' 를 되돌림)")
    chk(mv._redo_btn.isEnabled() and mv._undo_btn.isEnabled(), "D2 ↶·↷ 단추가 기록대로 켜진다")
    mv._redo_btn.click(); spin(0.1)
    chk(len(st.get_drawings(str(pdf), 0)) == 1 and len(st.get_images(str(pdf), 0)) == 1,
        "D3 ↷ 단추도 같은 기록 — 사진이 돌아온다")
    mv._redo_btn.click(); spin(0.1)
    chk(not st.get_drawings(str(pdf), 0) and not st.get_images(str(pdf), 0) and not mv._redo_btn.isEnabled(),
        "D4 마지막(범위 지우기)까지 다시 하면 ↷ 가 꺼진다")

    # E — 편집 모드를 끄면 비워진다
    mw.bookmark_tree.btn_edit.setChecked(False); spin(0.3)
    n0 = len(st.get_drawings(str(pdf), 0))
    mv.view.setFocus(); ctrl(Qt.Key.Key_Z)
    chk(len(st.get_drawings(str(pdf), 0)) == n0, "E1 편집 모드가 아니면 Ctrl+Z 는 아무것도 안 한다")
    mw.bookmark_tree.btn_edit.setChecked(True); spin(0.3)
    chk(not mw.edit_can_undo() and not mv._undo_btn.isEnabled(), "E2 편집 모드를 다시 켜면 기록은 비어 있다")
    mw.bookmark_tree.btn_edit.setChecked(False); spin(0.2)
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
