# -*- coding: utf-8 -*-
"""이미지→PDF 창이 큰 사진을 메인에서 통째로 풀지 않는다 (사진 보기 SOT 4.14 G4, 이미지 PDF 변환 SOT, 261103-21).

종전에는 목록 아이콘(56px)·미리보기를 `QPixmap(경로)` 로 **메인에서 원본 전체** 디코드했다 — 24 MP 사진 50장이면 수십 초 '응답 없음'.
A. 큰 JPEG 여러 장을 넣는 `_add_files` 가 메인에서 짧게 끝난다(디코드는 배경)
B. 아이콘이 결국 붙는다(배경 줄여 읽기) · 미리보기·크기 글이 원래 픽셀로 나온다
C. EXIF 방향(6 = 시계 90°): 이 창은 **종전처럼 적용하지 않는다**(만드는 PDF 와 같게 — 셋을 함께 세우는 것은 사진 보기 SOT P1).
   `read_scaled(auto_transform=True)` 는 세운다(사진 모드가 쓸 길)
D. `image_page.image_size` 는 머리만 읽고, `images_to_pdf` 쪽 크기 = 사진 크기
"""
import os, sys, time, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump_until(cond, timeout=20.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_img2pdf_bg_"))
try:
    from PIL import Image
    W, H = 6000, 4000                                  # 24 MP
    big = tmp / "큰 사진 00.jpg"
    Image.new("RGB", (W, H), (60, 120, 200)).save(big, quality=90)
    paths = [big]
    for k in range(1, 8):
        p = tmp / ("큰 사진 %02d.jpg" % k)
        shutil.copy(big, p)
        paths.append(p)
    rot = tmp / "눕힌 사진.jpg"                         # EXIF 방향 6 — 저장은 가로, 보이기는 세로
    ex = Image.Exif()
    ex[0x0112] = 6
    Image.new("RGB", (800, 400), (200, 80, 40)).save(rot, exif=ex.tobytes())

    from viewer.widgets.image_to_pdf_dialog import ImageToPdfDialog
    dlg = ImageToPdfDialog()
    dlg.resize(860, 580)
    dlg.show()
    app.processEvents()
    t0 = time.perf_counter()
    dlg._add_files([str(p) for p in paths])
    dt = time.perf_counter() - t0
    chk(dt < 0.3, "A 24 MP 8장 넣기가 메인에서 짧다", "%.2f초" % dt)

    def icons_ready():
        return all(not dlg.lst.item(i).icon().isNull() for i in range(dlg.lst.count()))
    chk(pump_until(icons_ready), "B 아이콘이 배경에서 붙는다")
    chk(pump_until(lambda: dlg.preview.pixmap() is not None and not dlg.preview.pixmap().isNull()),
        "B 미리보기가 그려진다")
    chk(("%d×%d" % (W, H)) in dlg.info.text(), "B 크기 글이 원래 픽셀", dlg.info.text())

    dlg._add_files([str(rot)])
    dlg.lst.setCurrentRow(dlg.lst.count() - 1)
    chk(pump_until(lambda: "800×400" in dlg.info.text()), "C 이 창은 종전처럼 방향을 적용하지 않는다(만드는 PDF 와 같게)", dlg.info.text())
    from viewer.widgets.image_to_pdf_dialog import read_scaled
    img, w, h = read_scaled(str(rot), 200, auto_transform=True)
    chk((w, h) == (400, 800) and img.height() > img.width(), "C auto_transform 이면 크기·그림이 세로", "%s %dx%d" % ((w, h), img.width(), img.height()))
    dlg.reject()
    app.processEvents()

    from viewer import image_page
    chk(image_page.image_size(big) == (float(W), float(H)), "D image_size 가 픽셀 크기")
    out = tmp / "묶음.pdf"
    n = image_page.images_to_pdf([big, tmp / "없는.jpg"], out)
    import fitz
    d = fitz.open(str(out))
    r = d[0].rect
    chk(n == 1 and d.page_count == 1 and (round(r.width), round(r.height)) == (W, H), "D images_to_pdf 쪽 = 사진 크기, 없는 그림은 건너뜀")
    d.close()
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
