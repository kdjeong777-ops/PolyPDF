# -*- coding: utf-8 -*-
"""261012-4: 꾸밈 개체 복사·붙여넣기·Shift 끌어 복사 (마스터 §4.6.7) · 261012-3 책갈피창 ↻ 편집 모드에서도.

A. 글상자를 고르고 Ctrl+C → Ctrl+V(실제 키): 같은 쪽은 조금 비켜, 거듭 붙이면 또 비켜, 다른 쪽은 같은 자리
B. 그 뒤 다른 프로그램에서 그림을 복사하면 Ctrl+V 는 종전대로 그림 붙여넣기(마지막에 복사한 것)
C. 우클릭 '복사'·'붙여넣기' — 붙여넣기는 누른 자리에
D. Shift + 끌기(실제 마우스) — 원본은 그대로, 복사본이 옮겨진다(선·글상자·사진·범위 선택)
E. 붙인 것은 꾸밈 옆 파일(page_meta)에 남는다
F. 책갈피창 ↻ — 편집 모드에서도 보이고, 저장 안 한 수정이 있으면 묻는다(취소면 그대로)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPointF, QEvent, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu
from PyQt6.QtGui import QMouseEvent, QImage, QColor, QPixmap
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_deco_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


root = Path(tempfile.mkdtemp(prefix="deco_"))
try:
    folder = root / "f"; folder.mkdir()
    pdf = folder / "꾸밈.pdf"
    d = fitz.open()
    for i in range(2):
        d.new_page(width=595, height=842).insert_text((72, 400), "PAGE%d" % (i + 1))
    d.save(str(pdf)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw.open_pdfs([str(pdf)]); spin(1.0)
    mv = mw.main_view
    mv.go_to_page(0); spin(0.2)
    mw.bookmark_tree.btn_edit.setChecked(True); spin(0.3)
    chk(mv._img_edit, "준비 — 편집 모드")
    TB = {"text_box": True, "rect": [0.10, 0.10, 0.40, 0.16], "text": "COPYME", "size_pt": 14}
    mv._page_strokes = [dict(TB)]
    mv._save_page_strokes()
    mv._draw_kind = "select"; mv._apply_tool()
    vp = mv.view.viewport()
    pr = mv._page_view_rect()

    def ev(kind, nx, ny, btn=Qt.MouseButton.LeftButton, shift=False):
        p = mv._norm_to_view(nx, ny, pr)
        buttons = btn if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
        mods = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
        return mv.eventFilter(vp, QMouseEvent(kind, QPointF(p), btn, buttons, mods))

    def click(nx, ny):
        ev(QEvent.Type.MouseButtonPress, nx, ny); ev(QEvent.Type.MouseButtonRelease, nx, ny)

    def drag(a, b, shift=False):
        ev(QEvent.Type.MouseButtonPress, a[0], a[1], shift=shift)
        ev(QEvent.Type.MouseMove, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, shift=shift)
        ev(QEvent.Type.MouseMove, b[0], b[1], shift=shift)
        ev(QEvent.Type.MouseButtonRelease, b[0], b[1], shift=shift)

    click(0.25, 0.13)
    chk(mv._stroke_selected == 0, "A0 개체선택으로 글상자를 고른다(실제 마우스)", str(mv._stroke_selected))
    mv.view.setFocus(); spin(0.05)
    QTest.keyClick(mv.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier); spin(0.1)
    md = QApplication.clipboard().mimeData()
    chk(mv._deco_clip and len(mv._deco_clip["strokes"]) == 1 and md.hasFormat(mv.DECO_MIME),
        "A1 Ctrl+C → 고른 글상자를 담는다(글 복사가 아니라)")
    QTest.keyClick(mv.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier); spin(0.1)
    rs = [s["rect"] for s in mv._page_strokes]
    chk(len(rs) == 2 and abs(rs[1][0] - 0.12) < 1e-6 and abs(rs[1][1] - 0.12) < 1e-6 and mv._stroke_selected == 1,
        "A2 Ctrl+V → 같은 쪽은 2% 비켜 붙이고 그것을 고른다", str(rs))
    QTest.keyClick(mv.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier); spin(0.1)
    rs = [s["rect"] for s in mv._page_strokes]
    chk(len(rs) == 3 and abs(rs[2][0] - 0.14) < 1e-6, "A3 거듭 붙이면 또 비켜(겹치지 않게)", str(rs[2]))
    mv.go_to_page(1); spin(0.3)
    pr = mv._page_view_rect()
    mv.view.setFocus()
    QTest.keyClick(mv.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier); spin(0.1)
    chk(len(mv._page_strokes) == 1 and abs(mv._page_strokes[0]["rect"][0] - 0.14) < 1e-6,
        "A4 다른 쪽에 붙이면 담은 자리 그대로", str([s["rect"] for s in mv._page_strokes]))

    # B — 그 뒤 그림을 복사하면 Ctrl+V 는 그림
    img = QImage(60, 30, QImage.Format.Format_RGB32); img.fill(QColor("red"))
    QApplication.clipboard().setImage(img); spin(0.1)
    n_s, n_i = len(mv._page_strokes), len(mv._img_objects)
    QTest.keyClick(mv.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier); spin(0.2)
    chk(len(mv._page_strokes) == n_s and len(mv._img_objects) == n_i + 1,
        "B1 다른 곳에서 그림을 복사한 뒤 Ctrl+V 는 그림 붙여넣기(마지막에 복사한 것)",
        str((len(mv._page_strokes), len(mv._img_objects))))

    # C — 우클릭 '복사'·'붙여넣기'(누른 자리에)
    mv.go_to_page(0); spin(0.3)
    pr = mv._page_view_rect()
    mv._multi_clear(); mv._stroke_selected = -1; mv._img_selected = -1
    picked = {"t": "복사 (Ctrl+C)"}
    labels = []
    _orig_exec = QMenu.exec

    def _menu_exec(self, *a, **k):
        labels.extend(x.text() for x in self.actions())
        return next((x for x in self.actions() if x.text() == picked["t"]), None)
    QMenu.exec = _menu_exec
    g = vp.mapToGlobal(mv._norm_to_view(0.25, 0.13, pr))
    mw._on_viewer_context_menu(g); spin(0.1)
    chk("복사 (Ctrl+C)" in labels and "붙여넣기 (Ctrl+V)" in labels and mv._deco_clip
        and mv._deco_clip["strokes"] and mv._deco_clip["strokes"][0]["text"] == "COPYME",
        "C1 우클릭 '복사' — 누른 자리의 글상자를 골라 담는다", str(labels[-4:]))
    picked["t"] = "붙여넣기 (Ctrl+V)"
    n0 = len(mv._page_strokes)
    g2 = vp.mapToGlobal(mv._norm_to_view(0.50, 0.60, pr))
    mw._on_viewer_context_menu(g2); spin(0.1)
    QMenu.exec = _orig_exec
    new = mv._page_strokes[-1]["rect"] if len(mv._page_strokes) > n0 else None
    bb = mv._stroke_bbox_view_any(mv._page_strokes[-1], pr) if new else None
    tl = ((bb.left() - pr.left()) / pr.width(), (bb.top() - pr.top()) / pr.height()) if bb else None
    chk(new is not None and tl and abs(tl[0] - 0.50) < 0.01 and abs(tl[1] - 0.60) < 0.01,
        "C2 우클릭 '붙여넣기' — 누른 자리에 붙인다", str(tl))

    # D — Shift + 끌기 = 복사본을 옮긴다
    mv._page_strokes = [dict(TB)]; mv._img_objects = []; mv._save_page_strokes()
    mv._multi_clear(); mv._stroke_selected = -1
    drag((0.25, 0.13), (0.25, 0.33), shift=True)
    rs = [s["rect"] for s in mv._page_strokes]
    chk(len(rs) == 2 and rs[0] == TB["rect"] and abs(rs[1][1] - 0.30) < 0.01,
        "D1 Shift + 끌기 — 원본은 그대로, 복사본이 옮겨진다(글상자)", str(rs))
    drag((0.25, 0.33), (0.25, 0.43))
    rs = [s["rect"] for s in mv._page_strokes]
    chk(len(rs) == 2 and abs(rs[1][1] - 0.40) < 0.01, "D2 Shift 없이 끌면 종전대로 옮기기만", str(rs))
    pix = QPixmap(40, 20); pix.fill(QColor("blue"))
    mv._img_objects = [{"pix": pix, "data": None, "rect": [0.6, 0.6, 0.1, 0.05], "shape": "rect", "alpha": 100, "rot": 0.0}]
    mv._img_selected = -1
    drag((0.65, 0.625), (0.65, 0.725), shift=True)
    ri = [o["rect"] for o in mv._img_objects]
    chk(len(ri) == 2 and abs(ri[0][1] - 0.6) < 1e-6 and abs(ri[1][1] - 0.7) < 0.01,
        "D3 사진도 Shift + 끌기 = 복사본", str(ri))
    # 범위 선택(둘) → Shift + 끌기
    mv._page_strokes = [dict(TB), dict(TB, rect=[0.10, 0.20, 0.40, 0.26])]
    mv._img_objects = []
    mv._multi_clear(); mv._stroke_selected = -1; mv._img_selected = -1
    drag((0.05, 0.05), (0.45, 0.30))                    # 고무줄
    chk(sorted(mv._multi_strokes) == [0, 1], "D4a 고무줄로 둘을 고른다", str(mv._multi_strokes))
    drag((0.25, 0.13), (0.55, 0.13), shift=True)
    rs = [s["rect"] for s in mv._page_strokes]
    chk(len(rs) == 4 and rs[0][0] == 0.10 and rs[1][0] == 0.10 and abs(rs[2][0] - 0.40) < 0.01 and abs(rs[3][0] - 0.40) < 0.01,
        "D4 범위 선택도 Shift + 끌기 = 고른 것 모두의 복사본", str(rs))

    # E — 옆 파일에 남는다
    st = mw._ensure_page_meta_store()
    saved = st.get_drawings(str(pdf), 0) if hasattr(st, "get_drawings") else None
    chk(saved is not None and len(saved) == 4, "E1 붙인 것은 꾸밈 옆 파일(page_meta)에 남는다", str(len(saved) if saved else saved))

    # F — 책갈피창 ↻ 편집 모드
    bt = mw.bookmark_tree
    chk(bt.btn_refresh.isVisible(), "F1 편집 모드에서도 ↻ 가 보인다(종전 숨김)")
    bt._dirty = True
    asked = []
    _qe = QMessageBox.exec
    QMessageBox.exec = lambda self: (asked.append(self.text()), setattr(self, "_c", None), 0)[2]
    _qc = QMessageBox.clickedButton
    QMessageBox.clickedButton = lambda self: None
    reloaded = []
    bt._reload_fn = lambda: reloaded.append(1)
    bt.btn_refresh.click(); spin(0.1)
    chk(asked and not reloaded and bt._dirty, "F2 저장 안 한 수정이 있으면 묻고, 취소면 다시 읽지 않는다", str(asked[:1]))
    QMessageBox.clickedButton = lambda self: next((b for b in self.buttons() if b.text() == "버리고 새로고침"), None)
    bt.btn_refresh.click(); spin(0.1)
    chk(reloaded and not bt._dirty and bt.is_edit_mode(), "F3 '버리고 새로고침' → 다시 읽고 편집 모드는 그대로")
    bt._dirty = False
    mw._confirm_close_edit = lambda: True               # 편집 중 종료 확인 창은 이 검사의 대상이 아니다
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
