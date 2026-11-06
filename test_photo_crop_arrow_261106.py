# -*- coding: utf-8 -*-
"""사진 크롭 창 가운데 ⇒ — 옅은 회색으로 채운 블록 화살표 (디자인 SOT §2.21·§4.5, 261106-10 사용자 지시 '옅은 회색의 이런 이미지').

오프스크린, 실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3).
A. 채운 도형(외곽선만 그린 라인 아이콘이 아님) — 머리 가운데·몸통 가운데가 칠해져 있고 귀퉁이는 비었다
B. 색 = 한 가지 옅은 회색: 밝은 테마는 꺼진 단추 글(`BTN_OFF_FG`)보다 옅고, 다크는 다크 값 — 회색(R=G=B 언저리)
C. 모양 — 몸통 높이 ≈ 머리 높이의 45%, 몸통 길이 ≈ 전체 길이의 45%
D. 크롭 창에서 이 그림을 쓰고, 창을 키우면 함께 커진다(ARROW_MIN~ARROW_MAX) — 두 칸 대칭은 그대로
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QColor

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_crop_arrow_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def lum(c):
    return (c.red() + c.green() + c.blue()) / 3.0


try:
    from viewer.widgets import icons
    from viewer.widgets.ribbon import BTN_OFF_FG
    N = 96
    im = icons.color_icon("block_arrow", dark=False, size=N, dpr=1.0).pixmap(N, N).toImage()
    chk(not im.isNull() and im.width() == N, "준비 — 그림이 있다")

    def px(x, y):
        return im.pixelColor(int(x), int(y))

    def filled(x, y):
        return px(x, y).alpha() > 200

    # A
    chk(filled(N * 0.80, N * 0.5) and filled(N * 0.25, N * 0.5) and filled(N * 0.62, N * 0.25),
        "A 머리·몸통 가운데가 칠해진 채운 도형")
    chk(not filled(2, 2) and not filled(N - 3, 3) and not filled(N * 0.25, N * 0.2), "A 귀퉁이·몸통 위는 비었다")
    # B
    cols = {(c.red(), c.green(), c.blue()) for c in (px(x, y) for x in range(N) for y in range(N)) if c.alpha() > 250}
    want = QColor(icons.ACCENT["block_arrow"][False])
    chk(len(cols) == 1 and cols == {(want.red(), want.green(), want.blue())}, "B 한 가지 색(외곽선 없음)", str(list(cols)[:4]))
    chk(abs(want.red() - want.green()) <= 6 and abs(want.green() - want.blue()) <= 6, "B 회색")
    chk(lum(want) > lum(QColor(BTN_OFF_FG[False])), "B 밝은 테마 — 꺼진 단추 글보다 옅다",
        "%s vs %s" % (want.name(), BTN_OFF_FG[False]))
    dk = icons.color_icon("block_arrow", dark=True, size=N, dpr=1.0).pixmap(N, N).toImage().pixelColor(int(N * 0.8), N // 2)
    chk(dk.name() == QColor(icons.ACCENT["block_arrow"][True]).name() and lum(dk) < 128, "B 다크 테마는 다크 값(어두운 바탕에 은은하게)", dk.name())

    # C
    def col_span(x):
        ys = [y for y in range(N) if filled(x, y)]
        return (max(ys) - min(ys) + 1) if ys else 0

    def row_span(y):
        xs = [x for x in range(N) if filled(x, y)]
        return (min(xs), max(xs)) if xs else (0, 0)
    body_h = col_span(N * 0.22)
    head_h = max(col_span(x) for x in range(int(N * 0.47), int(N * 0.6)))
    x0, x1 = row_span(N // 2)
    xs_top = [x for x in range(N) if filled(x, int(N * 0.5 - head_h * 0.4))]
    head_x0 = min(xs_top) if xs_top else 0
    chk(0.38 <= body_h / float(head_h) <= 0.52, "C 몸통 높이 ≈ 머리의 45%", "%d / %d" % (body_h, head_h))
    chk(0.38 <= (head_x0 - x0) / float(x1 - x0) <= 0.52, "C 몸통 길이 ≈ 전체의 45%", "%d / %d" % (head_x0 - x0, x1 - x0))

    # D
    from viewer.widgets.photo_crop_dialog import PhotoCropDialog, ARROW_MIN, ARROW_MAX
    img = QImage(800, 600, QImage.Format.Format_RGB32); img.fill(QColor(200, 200, 200))
    dlg = PhotoCropDialog(img, [10, 10, 10, 10])
    dlg.resize(1120, 720); dlg.show()
    for _ in range(10):
        app.processEvents()
    p1 = dlg.arrow.pixmap()
    a1 = dlg.arrow.pixmap().width()
    c = p1.toImage().pixelColor(int(a1 * 0.8), a1 // 2)
    chk(c.name() == want.name(), "D 크롭 창 가운데가 이 옅은 회색 블록 화살표", c.name())
    dlg.resize(1800, 1000)
    for _ in range(10):
        app.processEvents()
    a2 = dlg.arrow.pixmap().width()
    chk(ARROW_MIN <= a1 < a2 <= ARROW_MAX, "D 창을 키우면 함께 커진다(범위 안)", "%d → %d" % (a1, a2))
    l0 = dlg.stack.mapTo(dlg, QPoint(0, 0)).x()
    r1 = dlg.result.mapTo(dlg, QPoint(0, 0)).x() + dlg.result.width()
    ac = dlg.arrow.mapTo(dlg, QPoint(0, 0)).x() + dlg.arrow.width() / 2.0
    chk(abs(dlg.stack.width() - dlg.result.width()) <= 2 and abs((l0 + r1) / 2.0 - dlg.width() / 2.0) <= 3
        and abs(ac - dlg.width() / 2.0) <= 3, "D 커져도 두 칸 대칭·⇒ 가운데")
    dlg.btn_full.setChecked(True)
    for _ in range(10):
        app.processEvents()
    chk(dlg.isFullScreen(), "D 그림이 커진 뒤에도 전체 화면이 풀리지 않는다(⇒ 칸 폭은 늘 같다)")
    dlg.btn_full.setChecked(False)
    dlg.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
