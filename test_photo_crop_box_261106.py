# -*- coding: utf-8 -*-
"""사진 크롭 창 — 박스 통째로 옮기기·모양 펴기 처음 점 = 조절한 박스 (사진 보기 SOT §4.40·§4.43, 261106-7 사용자 지시).

오프스크린, 실제 마우스 이벤트(QTest)로 화면을 끈다. 실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3).
A. 크롭 박스 안쪽을 끌면 크기 그대로 옮긴다 — 사진 밖으로는 나가지 않는다(가장자리에서 멈춤), 커서는 이동 모양
B. 변 끌기는 그대로(크기 바뀜) · PDF 크롭 창(`CropCanvas`)은 안쪽 끌기를 하지 않는다(종전대로)
C. 박스를 조절한 뒤 '모양 펴기' 를 켜면 처음 점 = 그 박스 네 귀(변 가운데는 곧은 변 가운데) — 안 건드렸으면 자동 어림,
   미리 건 최근 크롭만으로는 어림, 그 사진의 저장된 크롭이 있으면 그 박스
D. [점 처음대로] = 조절한 박스(없으면 기본 점) · [테두리 찾기] = 늘 어림
E. 펴기 화면도 테두리 안쪽을 끌면 점 전체를 옮긴다(사진 밖으로는 안 나감)
F. ❮ ❯ — 사진마다 같은 규칙(넘긴 사진은 제 박스·어림, 되돌아오면 놓아 둔 점)
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_crop_box_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def r1(v):
    return [round(x, 1) for x in v]


def near(a, b, tol=0.012):
    return all(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for p, q in zip(a, b))


def drag(w, a, b, steps=6):
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for k in range(1, steps + 1):
        QTest.mouseMove(w, QPoint(a.x() + (b.x() - a.x()) * k // steps, a.y() + (b.y() - a.y()) * k // steps))
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    app.processEvents()


try:
    from viewer import photo_warp as pw
    from viewer.widgets.photo_crop_dialog import PhotoCropDialog, move_margins
    from viewer.widgets.crop_dialog import CropCanvas

    img = QImage(800, 600, QImage.Format.Format_RGB32)
    img.fill(QColor(200, 200, 200))
    AUTO = [(0.2, 0.15), (0.8, 0.12), (0.85, 0.9), (0.15, 0.85)]
    AUTO = AUTO + pw.mids_of(AUTO)

    # A
    dlg = PhotoCropDialog(img, [20, 20, 20, 20], has_crop=False, auto_pts=AUTO)
    dlg.resize(1120, 720); dlg.show(); app.processEvents()
    cv = dlg.canvas
    r = cv._img_rect()
    c = cv._crop_rect(r)
    mid = QPoint(int(c.center().x()), int(c.center().y()))
    QTest.mouseMove(cv, mid); app.processEvents()
    chk(cv.cursor().shape() == Qt.CursorShape.SizeAllCursor, "A 박스 안쪽 위 커서 = 이동 모양")
    drag(cv, mid, QPoint(mid.x() + int(r.width() * 0.10), mid.y() + int(r.height() * 0.05)))
    m = r1(dlg.current_margins())
    chk(abs(m[0] - 25) <= 0.6 and abs(m[1] - 15) <= 0.6 and abs(m[2] - 30) <= 0.6 and abs(m[3] - 10) <= 0.6,
        "A 안쪽 끌기 = 크기 그대로 옮김(왼 +10%·위 +5%)", str(m))
    chk(abs((m[0] + m[1]) - 40) < 0.2 and abs((m[2] + m[3]) - 40) < 0.2, "A 박스 크기는 그대로", str(m))
    c = cv._crop_rect(r)
    mid = QPoint(int(c.center().x()), int(c.center().y()))
    drag(cv, mid, QPoint(mid.x() + int(r.width() * 0.6), mid.y() - int(r.height() * 0.6)))
    m = r1(dlg.current_margins())
    chk(m[3] == 0.0 and m[0] == 0.0 and abs(m[2] - 40) < 0.2 and abs(m[1] - 40) < 0.2, "A 사진 밖으로 나가지 않는다(오른쪽·위 가장자리에서 멈춤)", str(m))
    chk(move_margins([10, 10, 10, 10], -50, 50) == [20.0, 0.0, 0.0, 20.0], "A 옮기기 계산 — 넘치면 가장자리까지만")

    # B
    c = cv._crop_rect(r)
    left = QPoint(int(c.left()), int(c.center().y()))
    drag(cv, left, QPoint(int(c.left() + r.width() * 0.1), int(c.center().y())))
    m = r1(dlg.current_margins())
    chk(abs(m[2] - 50) <= 0.6 and m[3] == 0.0, "B 변 끌기는 그대로 — 왼 변만 옮겨 크기가 바뀐다", str(m))
    pdf = CropCanvas(); pdf.resize(500, 500); pdf.set_image(img); pdf.set_margins([20, 20, 20, 20]); pdf.show(); app.processEvents()
    pr = pdf._img_rect(); pc_ = pdf._crop_rect(pr)
    pm = QPoint(int(pc_.center().x()), int(pc_.center().y()))
    drag(pdf, pm, QPoint(pm.x() + 60, pm.y() + 40))
    chk(r1(pdf._m) == [20.0, 20.0, 20.0, 20.0], "B PDF 크롭 화면은 안쪽 끌기로 바뀌지 않는다(종전대로)", str(pdf._m))
    pdf.close()

    # C — 조절한 박스 → 펴기 처음 점
    dlg.chk_warp.setChecked(True); app.processEvents()
    t, b, l, rr = (v / 100.0 for v in dlg.current_margins())
    box = [(l, t), (1 - rr, t), (1 - rr, 1 - b), (l, 1 - b)]
    chk(near(dlg.warp.points(), box + pw.mids_of(box), 1e-6), "C 박스를 조절한 뒤 펴기를 켜면 처음 점 = 그 박스 네 귀·곧은 변 가운데",
        str(dlg.warp.points()[:4]))
    dlg.close()
    d2 = PhotoCropDialog(img, [10, 10, 10, 10], has_crop=False, auto_pts=AUTO)   # 미리 건 최근 크롭(손대지 않음)
    d2.chk_warp.setChecked(True)
    chk(near(d2.warp.points(), AUTO, 1e-6), "C 박스를 안 건드렸으면(미리 건 최근 크롭만) 자동 어림")
    d2.close()
    d3 = PhotoCropDialog(img, [5, 5, 30, 5], has_crop=True, auto_pts=AUTO)       # 그 사진의 저장된 크롭
    d3.chk_warp.setChecked(True)
    bx = [(0.30, 0.05), (0.95, 0.05), (0.95, 0.95), (0.30, 0.95)]
    chk(near(d3.warp.points(), bx + pw.mids_of(bx), 1e-6), "C 저장된 크롭이 있는 사진은 그 박스", str(d3.warp.points()[:4]))
    d3.close()
    d4 = PhotoCropDialog(img, [0, 0, 0, 0], has_crop=False, auto_pts=None)
    d4.chk_warp.setChecked(True)
    chk(near(d4.warp.points(), pw.default_points(), 1e-6), "C 어림도 박스도 없으면 기본 점")
    d4.close()

    # D — 단추
    d5 = PhotoCropDialog(img, [0, 0, 0, 0], has_crop=False, auto_pts=AUTO)
    d5.spins[0].setValue(20.0)                          # 손으로 고침
    d5.chk_warp.setChecked(True)
    want = [(0.0, 0.2), (1.0, 0.2), (1.0, 1.0), (0.0, 1.0)]
    chk(near(d5.warp.points(), want + pw.mids_of(want), 1e-6), "D 여백 칸으로 고친 박스도 '조절한 박스'")
    d5.warp.move_point(0, (0.1, 0.3))
    d5.btn_detect.click()
    chk(near(d5.warp.points(), AUTO, 1e-6), "D [테두리 찾기] = 늘 자동 어림")
    d5.btn_corners.click()
    chk(near(d5.warp.points(), want + pw.mids_of(want), 1e-6), "D [점 처음대로] = 조절한 박스")
    d5.close()
    d6 = PhotoCropDialog(img, [0, 0, 0, 0], has_crop=False, auto_pts=AUTO)
    d6.chk_warp.setChecked(True)
    d6.btn_corners.click()
    chk(near(d6.warp.points(), pw.default_points(), 1e-6), "D 박스가 없으면 [점 처음대로] = 기본 점(사진 귀퉁이 가까이)")

    # E — 펴기 화면 안쪽 끌기
    d6.resize(1120, 720); d6.show(); app.processEvents()
    wv = d6.warp
    before = wv.points()
    wr = wv._img_rect()
    cen = QPoint(int(wr.center().x()), int(wr.center().y()))
    QTest.mouseMove(wv, cen); app.processEvents()
    chk(wv.cursor().shape() == Qt.CursorShape.SizeAllCursor, "E 테두리 안쪽 위 커서 = 이동 모양")
    drag(wv, cen, QPoint(cen.x() + int(wr.width() * 0.02), cen.y() + int(wr.height() * 0.03)))
    after = wv.points()
    dx = [a[0] - b_[0] for a, b_ in zip(after, before)]
    dy = [a[1] - b_[1] for a, b_ in zip(after, before)]
    chk(max(dx) - min(dx) < 1e-6 and max(dy) - min(dy) < 1e-6 and 0.01 < dx[0] < 0.03 and 0.02 < dy[0] < 0.04,
        "E 안쪽 끌기 = 점 8개가 모양 그대로 옮김", str((round(dx[0], 3), round(dy[0], 3))))
    drag(wv, cen, QPoint(cen.x() + int(wr.width() * 0.5), cen.y() + int(wr.height() * 0.5)))
    xs = [p[0] for p in wv.points()]; ys = [p[1] for p in wv.points()]
    chk(max(xs) <= 1.0 + 1e-9 and max(ys) <= 1.0 + 1e-9 and abs(max(xs) - 1.0) < 1e-6, "E 사진 밖으로는 안 나간다(가장자리에서 멈춤)")
    d6.close()

    # G — 껐다 켜기: 박스 그대로면 놓아 둔 점, 박스를 다시 고쳤으면 새 박스
    d8 = PhotoCropDialog(img, [0, 0, 0, 0], has_crop=False, auto_pts=AUTO)
    d8.chk_warp.setChecked(True)
    d8.warp.move_point(0, (0.25, 0.2))
    moved = d8.warp.points()
    d8.chk_warp.setChecked(False); d8.chk_warp.setChecked(True)
    chk(near(d8.warp.points(), moved, 1e-6), "G 박스를 그대로 두고 껐다 켜면 놓아 둔 점")
    d8.chk_warp.setChecked(False)
    d8.spins[2].setValue(15.0)
    d8.chk_warp.setChecked(True)
    nb = [(0.15, 0.0), (1.0, 0.0), (1.0, 1.0), (0.15, 1.0)]
    chk(near(d8.warp.points(), nb + pw.mids_of(nb), 1e-6), "G 끈 동안 박스를 고치고 켜면 새 박스 네 귀", str(d8.warp.points()[:4]))
    d8.close()

    # F — ❮ ❯ 사진마다
    img2 = QImage(600, 600, QImage.Format.Format_RGB32); img2.fill(QColor(120, 120, 120))
    AUTO2 = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]
    AUTO2 = AUTO2 + pw.mids_of(AUTO2)
    d7 = PhotoCropDialog(img, [0, 0, 0, 0], has_crop=False, auto_pts=AUTO, count=2, index=0)
    d7.photoRequested.connect(lambda i: d7.show_photo(i, img2 if i == 1 else img, [10, 10, 10, 10] if i == 1 else [0, 0, 0, 0],
                                                      False, "p%d" % i, AUTO2 if i == 1 else AUTO))
    d7.spins[1].setValue(30.0)                          # 0번 사진 박스를 고친 뒤 켠다
    d7.chk_warp.setChecked(True)
    p0 = d7.warp.points()
    d7._go(1); app.processEvents()
    chk(d7.chk_warp.isChecked() and near(d7.warp.points(), AUTO2, 1e-6), "F 넘긴 사진(박스 안 건드림)은 켬을 이어받고 제 어림 점")
    d7._go(0); app.processEvents()
    chk(near(d7.warp.points(), p0, 1e-6), "F 되돌아오면 놓아 둔 점(조절한 박스로 시작한 점)")
    d7.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
