# -*- coding: utf-8 -*-
"""크롭 창 ←/→ = ❮ ❯ — 사진 크롭·PDF 쪽 크롭 (사진 보기 SOT §4.40, 마스터 §4.7.15, 261106-13 사용자 지시).

오프스크린, 실제 키 이벤트(QTest). 실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3).
A. 사진 크롭 — 단추·체크 상자에 포커스가 있어도 → = 다음 사진, ← = 이전(❮ ❯ 와 같은 처리기 — 끝에서는 그대로)
B. 넘길 때 규칙 그대로 — 고친 여백을 기억하고, 모양 펴기를 켠 채 넘기면 처음 보는 사진은 꺼진 채
C. 숫자 칸(여백 %)을 고치는 중이면 ←/→ 는 칸 안 커서 이동 — 넘기지 않는다
D. PDF 쪽 크롭 창도 같은 규칙(→ = 다음 쪽, 숫자 칸에서는 칸 안)
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_crop_arrow_keys_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(n=10):
    for _ in range(n):
        app.processEvents()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_crop_arrow_keys_"))
try:
    from viewer.widgets.photo_crop_dialog import PhotoCropDialog
    img = QImage(800, 600, QImage.Format.Format_RGB32); img.fill(QColor(200, 200, 200))
    dlg = PhotoCropDialog(img, [0, 0, 0, 0], count=3, index=0)
    dlg.photoRequested.connect(lambda i: dlg.show_photo(i, img, [5, 5, 5, 5], False, "p%d" % i))
    dlg.resize(1120, 720); dlg.show(); dlg.activateWindow(); pump()

    # A
    dlg.btn_full.setFocus(); pump()
    QTest.keyClick(dlg.btn_full, Qt.Key.Key_Right); pump()
    chk(dlg.index() == 1, "A 단추에 포커스 — → = 다음 사진", str(dlg.index()))
    dlg.chk_warp.setFocus(); pump()
    QTest.keyClick(dlg.chk_warp, Qt.Key.Key_Left); pump()
    chk(dlg.index() == 0, "A 체크 상자에 포커스 — ← = 이전 사진", str(dlg.index()))
    QTest.keyClick(dlg.chk_warp, Qt.Key.Key_Left); pump()
    chk(dlg.index() == 0, "A 처음에서 ← 는 그대로")

    # B
    dlg.spins[0].setValue(20.0)
    dlg.chk_warp.setChecked(True); pump()
    dlg.btn_corners.setFocus(); pump()
    QTest.keyClick(dlg.btn_corners, Qt.Key.Key_Right); pump()
    chk(dlg.index() == 1 and not dlg.chk_warp.isChecked(), "B 모양 펴기를 켠 채 → — 처음 보는 사진은 꺼진 채")
    QTest.keyClick(dlg.btn_corners if dlg.btn_corners.hasFocus() else dlg, Qt.Key.Key_Left); pump()
    chk(dlg.index() == 0 and dlg.chk_warp.isChecked() and round(dlg.current_margins()[0], 1) == 20.0,
        "B ← 로 돌아오면 고친 여백·켬 그대로", str((dlg.index(), dlg.current_margins()[0])))

    # C
    dlg.chk_warp.setChecked(False); pump()
    sp = dlg.spins[1]
    sp.setFocus(); pump()
    le = sp.lineEdit()
    le.setCursorPosition(0)
    QTest.keyClick(sp, Qt.Key.Key_Right); pump()
    chk(dlg.index() == 0 and le.cursorPosition() == 1, "C 숫자 칸을 고치는 중 → 는 칸 안 커서 이동(넘기지 않음)",
        "index %d · 커서 %d" % (dlg.index(), le.cursorPosition()))
    dlg.close()

    # D — PDF 쪽 크롭 창
    import fitz
    d = fitz.open()
    for i in range(3):
        d.new_page(width=595, height=842).insert_text((72, 72), "p%d" % (i + 1))
    pdf = tmp / "doc.pdf"; d.save(str(pdf)); d.close()
    from viewer.widgets.crop_dialog import CropDialog
    cd = CropDialog(str(pdf), current_page=0)
    cd.show(); cd.activateWindow(); pump(30)
    cd.chk_overlay.setFocus(); pump()
    QTest.keyClick(cd.chk_overlay, Qt.Key.Key_Right); pump()
    chk(cd._cur == 1, "D PDF 크롭 — → = 다음 쪽", str(cd._cur))
    QTest.keyClick(cd.chk_overlay, Qt.Key.Key_Left); pump()
    chk(cd._cur == 0, "D PDF 크롭 — ← = 이전 쪽", str(cd._cur))
    sp2 = cd.spins[0]
    sp2.setFocus(); pump()
    sp2.lineEdit().setCursorPosition(0)
    QTest.keyClick(sp2, Qt.Key.Key_Right); pump()
    chk(cd._cur == 0 and sp2.lineEdit().cursorPosition() == 1, "D 숫자 칸에서는 칸 안 커서 이동")
    cd.reject()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
