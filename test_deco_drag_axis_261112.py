# -*- coding: utf-8 -*-
"""261112-7: 꾸밈 끌기 세 가지 — PPT 식 (마스터 §4.6.7).

A. Ctrl + 끌기 = 복사본을 옮긴다(원본 그대로) — 도형(개체선택)·사진·범위 선택·글상자(글쓰기 '이동' 손잡이)·도형 도구의 고른 도형
B. Ctrl+Shift + 끌기 = 복사본을 가로·세로로만(누른 자리에서 더 움직인 축 하나)
C. Shift + 끌기 = 옮기기만, 가로·세로로만(복사 없음)
D. Ctrl 로 누르고 끌지 않으면 복사하지 않는다
E. 되돌리기(편집 모드 Ctrl+Z) 한 번 = 복사 한 건 — 복사본이 통째로 사라지고 원본은 그대로
실제 QMouseEvent 를 MainView.eventFilter(본문 viewport)에 넣고, 이벤트 사이에 이벤트 고리를 돌린다(되돌리기 단계는 다음 이벤트에서 닫힌다).
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPointF, QEvent, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QMouseEvent, QColor, QPixmap

app = QApplication.instance() or QApplication(sys.argv[:1])
import modal_guard
guard = modal_guard.install(label=lambda: "검사")   # 검사 작성 SOT §14.7.2 의 6
QCoreApplication.setApplicationName("polypdf_dragaxis_%d" % os.getpid())

fails = []
K = Qt.KeyboardModifier


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.05):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)


def near(a, b, tol=0.006):
    return all(abs(x - y) < tol for x, y in zip(a, b))


root = Path(tempfile.mkdtemp(prefix="dragaxis_"))
try:
    folder = root / "f"; folder.mkdir()
    pdf = folder / "끌기.pdf"
    d = fitz.open()
    d.new_page(width=595, height=842).insert_text((72, 400), "PAGE1")
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
    vp = mv.view.viewport()
    pr = mv._page_view_rect()
    BOX = {"shape": "rect", "rect": [0.10, 0.10, 0.30, 0.20], "color": "#ff0000", "fill": "full", "width": 2, "alpha": 100}
    TB = {"text_box": True, "rect": [0.10, 0.50, 0.40, 0.56], "text": "AXIS", "size_pt": 14}

    def ev(kind, nx, ny, mods=K.NoModifier):
        p = mv._norm_to_view(nx, ny, pr)
        btn = Qt.MouseButton.LeftButton
        buttons = btn if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
        r = mv.eventFilter(vp, QMouseEvent(kind, QPointF(p), btn, buttons, mods))
        spin()
        return r

    def drag(a, b, mods=K.NoModifier, steps=4):
        ev(QEvent.Type.MouseButtonPress, a[0], a[1], mods)
        for i in range(1, steps + 1):
            ev(QEvent.Type.MouseMove, a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps, mods)
        ev(QEvent.Type.MouseButtonRelease, b[0], b[1], mods)

    def reset(strokes=(), images=(), kind="select"):
        mv._draw_kind = kind
        if kind == "shape":
            mv._ensure_pen()                     # 도형 도구는 펜이 골라져 있어야 켜진다(드롭다운과 같은 길)
        mv._apply_tool()
        mv._page_strokes = [dict(s) for s in strokes]; mv._img_objects = list(images)
        mv._multi_clear(); mv._stroke_selected = -1; mv._img_selected = -1
        mv._save_page_strokes(); mv._save_page_images(); spin(0.1)

    def blue(rect):
        pix = QPixmap(40, 20); pix.fill(QColor("blue"))
        return {"pix": pix, "data": None, "rect": list(rect), "shape": "rect", "alpha": 100, "rot": 0.0}

    rects = lambda: [list(s["rect"]) for s in mv._page_strokes]
    irects = lambda: [list(o["rect"]) for o in mv._img_objects]

    # A — Ctrl + 끌기 = 복사
    reset([BOX])
    drag((0.20, 0.15), (0.40, 0.35), K.ControlModifier)
    rs = rects()
    chk(len(rs) == 2 and rs[0] == BOX["rect"] and near(rs[1], [0.30, 0.30, 0.50, 0.40]),
        "A1 Ctrl + 끌기 — 도형: 원본 그대로, 복사본이 옮겨진다", str(rs))
    reset([], [blue([0.60, 0.60, 0.10, 0.05])])
    drag((0.65, 0.625), (0.75, 0.725), K.ControlModifier)
    ri = irects()
    chk(len(ri) == 2 and ri[0] == [0.60, 0.60, 0.10, 0.05] and near(ri[1], [0.70, 0.70, 0.10, 0.05]),
        "A2 Ctrl + 끌기 — 사진: 복사본", str(ri))
    reset([BOX, dict(BOX, rect=[0.10, 0.25, 0.30, 0.35])])
    drag((0.05, 0.05), (0.35, 0.40))                                    # 고무줄로 둘
    chk(sorted(mv._multi_strokes) == [0, 1], "A3a 고무줄로 둘을 고른다", str(mv._multi_strokes))
    drag((0.20, 0.15), (0.50, 0.15), K.ControlModifier)
    rs = rects()
    chk(len(rs) == 4 and rs[0][0] == 0.10 and rs[1][0] == 0.10 and near(rs[2][:1], [0.40]) and near(rs[3][:1], [0.40]),
        "A3 Ctrl + 끌기 — 범위 선택: 고른 것 모두의 복사본", str(rs))
    reset([TB], kind="text")
    mv._stroke_selected = 0; mv.view.viewport().update(); spin(0.1)
    hx, hy = None, None
    for fy in [i / 1000 for i in range(480, 600)]:                      # '이동' 손잡이(테두리)를 찾는다
        for fx in [i / 1000 for i in range(80, 420, 4)]:
            if mv._shape_handle_at(mv._norm_to_view(fx, fy, pr), pr) == "move":
                hx, hy = fx, fy; break
        if hx is not None:
            break
    chk(hx is not None, "A4a 글쓰기 도구 — 고른 글상자의 '이동' 손잡이를 찾았다")
    if hx is not None:
        drag((hx, hy), (hx, hy + 0.20), K.ControlModifier)
        rs = rects()
        chk(len(rs) == 2 and rs[0] == TB["rect"] and near(rs[1], [0.10, 0.70, 0.40, 0.76], 0.01),
            "A4 Ctrl + 끌기 — 글상자 '이동' 손잡이: 복사본", str(rs))
    reset([BOX], kind="shape")
    mv._stroke_selected = 0; spin(0.1)
    drag((0.20, 0.15), (0.20, 0.45), K.ControlModifier)
    rs = rects()
    chk(len(rs) == 2 and rs[0] == BOX["rect"] and near(rs[1], [0.10, 0.40, 0.30, 0.50], 0.01),
        "A5 Ctrl + 끌기 — 도형 도구의 고른 도형: 복사본", str(rs))

    # B — Ctrl+Shift = 가로·세로로만 복사
    reset([BOX])
    drag((0.20, 0.15), (0.45, 0.20), K.ControlModifier | K.ShiftModifier)     # 가로가 더 많다 → 세로는 그대로
    rs = rects()
    chk(len(rs) == 2 and rs[0] == BOX["rect"] and near(rs[1], [0.35, 0.10, 0.55, 0.20]),
        "B1 Ctrl+Shift + 끌기 — 복사본이 가로로만(세로 움직임은 버림)", str(rs))
    reset([], [blue([0.60, 0.60, 0.10, 0.05])])
    drag((0.65, 0.625), (0.67, 0.825), K.ControlModifier | K.ShiftModifier)  # 세로가 더 많다
    ri = irects()
    chk(len(ri) == 2 and ri[0] == [0.60, 0.60, 0.10, 0.05] and near(ri[1], [0.60, 0.80, 0.10, 0.05]),
        "B2 Ctrl+Shift + 끌기 — 사진 복사본이 세로로만", str(ri))

    # C — Shift = 가로·세로로만 옮기기
    reset([BOX])
    drag((0.20, 0.15), (0.24, 0.40), K.ShiftModifier)
    rs = rects()
    chk(len(rs) == 1 and near(rs[0], [0.10, 0.35, 0.30, 0.45]),
        "C1 Shift + 끌기 — 복사 없이 세로로만 옮긴다", str(rs))
    reset([BOX, dict(BOX, rect=[0.10, 0.25, 0.30, 0.35])])
    drag((0.05, 0.05), (0.35, 0.40))
    drag((0.20, 0.15), (0.45, 0.19), K.ShiftModifier)
    rs = rects()
    chk(len(rs) == 2 and near(rs[0], [0.35, 0.10, 0.55, 0.20]) and near(rs[1], [0.35, 0.25, 0.55, 0.35]),
        "C2 Shift + 끌기 — 범위 선택도 가로로만", str(rs))
    reset([], [blue([0.60, 0.60, 0.10, 0.05])])
    drag((0.65, 0.625), (0.80, 0.64), K.ShiftModifier)
    ri = irects()
    chk(len(ri) == 1 and near(ri[0], [0.75, 0.60, 0.10, 0.05]), "C3 Shift + 끌기 — 사진도 가로로만", str(ri))
    reset([BOX])
    drag((0.20, 0.15), (0.32, 0.27))
    chk(near(rects()[0], [0.22, 0.22, 0.42, 0.32]), "C4 키 없이 끌면 종전대로 자유롭게 옮긴다", str(rects()))

    # D — Ctrl 로 누르기만 하면 복사 없음
    reset([BOX])
    ev(QEvent.Type.MouseButtonPress, 0.20, 0.15, K.ControlModifier)
    ev(QEvent.Type.MouseButtonRelease, 0.20, 0.15, K.ControlModifier)
    chk(len(mv._page_strokes) == 1, "D1 Ctrl 로 누르고 끌지 않으면 복사하지 않는다", str(rects()))

    # E — 되돌리기 한 번 = 복사 한 건
    reset([BOX]); spin(0.2)
    mw._hist_reset(); spin(0.1)
    drag((0.20, 0.15), (0.40, 0.35), K.ControlModifier)
    chk(len(mv._page_strokes) == 2, "E0 Ctrl 끌기로 복사본이 생겼다", str(rects()))
    mw.action_edit_undo(); spin(0.3)
    rs = rects()
    chk(len(rs) == 1 and rs[0] == BOX["rect"], "E1 되돌리기 한 번에 복사본이 통째로 사라진다(겹친 복사본이 남지 않음)", str(rs))
    reset([], [blue([0.60, 0.60, 0.10, 0.05])]); spin(0.2)
    mw._hist_reset(); spin(0.1)
    drag((0.65, 0.625), (0.75, 0.725), K.ControlModifier)
    mw.action_edit_undo(); spin(0.3)
    ri = irects()
    chk(len(ri) == 1 and ri[0] == [0.60, 0.60, 0.10, 0.05], "E2 사진도 되돌리기 한 번에 복사본이 사라진다", str(ri))

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
