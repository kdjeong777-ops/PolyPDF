# -*- coding: utf-8 -*-
"""261112-8: 쓰는 중인 글상자 — 파란 점선 상자 하나 (마스터 §4.6.13).

실제 창: 글쓰기 도구로 빈 곳을 눌러(실제 QMouseEvent) 글상자를 만들고 글자를 친 뒤, 본문 창(입력칸 포함)을 그려
A. 글상자 둘레에 주황 점선(입력칸 테두리 #ff7a00)이 없다
B. 상자 네 변에 진한 파란 점선(#1565c0)이 보인다 — 입력칸 바탕에 가려 옅어지지 않는다
C. 회전 손잡이(파란 원)가 보인다
D. 쓰는 중에도 바탕은 흰색(배경색 없는 글상자) — 밑 쪽 글이 비쳐 글이 섞이지 않게
E. 입력칸이 여전히 글을 받는다(친 글이 상자에 들어간다)
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
from PyQt6.QtGui import QMouseEvent, QColor
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
import modal_guard
guard = modal_guard.install(label=lambda: "검사")   # 검사 작성 SOT §14.7.2 의 6
QCoreApplication.setApplicationName("polypdf_onebox_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def dist(c, ref):
    return abs(c.red() - ref.red()) + abs(c.green() - ref.green()) + abs(c.blue() - ref.blue())


BLUE = QColor("#1565c0")
root = Path(tempfile.mkdtemp(prefix="onebox_"))
try:
    folder = root / "f"; folder.mkdir()
    pdf = folder / "글상자.pdf"
    d = fitz.open()
    d.new_page(width=595, height=842).insert_text((72, 100), "PAGE1")
    d.save(str(pdf)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw.open_pdfs([str(pdf)]); spin(1.0)
    mv = mw.main_view
    mv.go_to_page(0); spin(0.2)
    mw.bookmark_tree.btn_edit.setChecked(True); spin(0.3)
    mv._draw_kind = "text"; mv._apply_tool(); spin(0.1)
    vp = mv.view.viewport()
    pr = mv._page_view_rect()
    p = mv._norm_to_view(0.30, 0.40, pr)
    for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                          (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        mv.eventFilter(vp, QMouseEvent(kind, QPointF(p), Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
        spin(0.1)
    ed = mv._text_editor
    chk(ed is not None and mv._stroke_selected == mv._text_edit_idx, "준비 — 빈 곳을 누르면 글상자를 쓰기 시작한다")
    QTest.keyClicks(ed, "TEST BOX"); spin(0.3)
    mv._draw_overlay.update(); spin(0.2)
    st = mv._page_strokes[mv._text_edit_idx]
    pts = mv._shape_handle_points(st, pr)
    img = mv.view.grab().toImage()
    off = mv._draw_overlay.mapTo(mv.view, mv._draw_overlay.rect().topLeft())   # 오버레이 좌표 → view 좌표
    X = lambda q: int(q.x()) + off.x()
    Y = lambda q: int(q.y()) + off.y()
    x0, x1 = min(X(pts["tl"]), X(pts["br"])), max(X(pts["tl"]), X(pts["br"]))
    y0, y1 = min(Y(pts["tl"]), Y(pts["br"])), max(Y(pts["tl"]), Y(pts["br"]))
    orange = blue = 0
    for y in range(y0 - 6, y1 + 7):
        for x in range(x0 - 6, x1 + 7):
            if x0 + 6 < x < x1 - 6 and y0 + 6 < y < y1 - 6:
                continue                                  # 둘레 띠만 본다
            c = img.pixelColor(x, y)
            orange += c.red() > 200 and c.red() - c.blue() > 80   # 주황 계열(점선은 흐리게 섞여 #f6b67d 꼴로 찍힌다)
            blue += dist(c, BLUE) < 60
    chk(orange == 0, "A 쓰는 중인 글상자 둘레에 주황 점선이 없다", "주황 %d점" % orange)
    chk(blue >= (x1 - x0) // 2, "B 상자 둘레에 진한 파란 점선이 보인다(입력칸에 가려 옅어지지 않음)", "파랑 %d점, 변 %d" % (blue, x1 - x0))
    rx, ry = X(pts["rot"]), Y(pts["rot"])
    chk(dist(img.pixelColor(rx, ry), BLUE) < 60, "C 회전 손잡이(파란 원)가 보인다", img.pixelColor(rx, ry).name())
    inner = img.pixelColor(x1 - 10, y1 - 4)
    chk(inner.red() > 230 and inner.green() > 230 and inner.blue() > 230, "D 쓰는 중에도 상자 바탕은 흰색", inner.name())
    chk(ed.toPlainText() == "TEST BOX", "E 입력칸이 친 글을 받는다", ed.toPlainText())
    mv._commit_text_editor(); spin(0.1)
    chk(mv._page_strokes and mv._page_strokes[-1].get("text") == "TEST BOX", "E2 쓰기를 마치면 글이 상자에 들어간다")
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
