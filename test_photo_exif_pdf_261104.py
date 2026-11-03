# -*- coding: utf-8 -*-
"""사진 → PDF 의 EXIF — GPS 는 빼고 방향은 세운다 (사진 보기 SOT 4.14 G6·G7, D16·D14, 261104-1).

실제로 PDF 를 만드는 두 길(`image_page.images_to_pdf` — 썸네일 사진 끼우기, `PrintMixin._images_to_pdf` — 이미지→PDF 창,
원본 그대로·줄여 넣기 둘)을 부른다.
A. GPS: 만든 PDF 안 그림의 EXIF 에 GPS 가 없다 · 촬영 시각(0x0132)은 남는다 · JPEG 그림 바이트는 다시 압축하지 않았다(길이 같음)
B. 방향 6(시계 90°): 쪽이 세로(폭 < 높이)이고, 원래 위(빨강)가 오른쪽에 보인다 — 종전엔 가로로 누웠다
C. 거울 방향(2): 바로 세워 다시 그린다 — 원래 왼쪽이 오른쪽에
D. 방향 1·GPS 없는 사진은 받은 그대로(바이트 같음)
E. 이미지→PDF 창 줄여 읽기도 세운다(만드는 PDF 와 같게)
"""
import io, os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
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


from PIL import Image
import fitz


def red_top(w, h, left_green=False):
    im = Image.new("RGB", (w, h), (40, 60, 200))
    im.paste(Image.new("RGB", (w, h // 2), (220, 40, 40)), (0, 0))
    if left_green:                                   # 거울 판정용 — 왼쪽 위 1/4 를 초록
        im.paste(Image.new("RGB", (w // 4, h // 2), (40, 200, 60)), (0, 0))
    return im


def save_jpeg(path, im, orient=None, gps=True):
    ex = Image.Exif()
    ex[0x0132] = "2025:06:23 09:43:07"
    if orient:
        ex[0x0112] = orient
    if gps:
        ex[0x8825] = {1: "N", 2: (37.0, 33.0, 59.0), 3: "E", 4: (126.0, 58.0, 41.0)}
    im.save(path, "JPEG", quality=90, exif=ex.tobytes())


def first_image(pdf):
    d = fitz.open(str(pdf))
    pg = d[0]
    xref = pg.get_images()[0][0]
    raw = d.extract_image(xref)["image"]
    rect = (round(pg.rect.width), round(pg.rect.height))
    pix = pg.get_pixmap(matrix=fitz.Matrix(0.1, 0.1))
    d.close()
    return raw, rect, pix


def color(pix, fx, fy):
    r, g, b = pix.pixel(int(pix.width * fx), int(pix.height * fy))[:3]
    return "R" if r > 150 and g < 120 else "G" if g > 150 else "B"


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_exif_"))
try:
    rot6 = tmp / "세로 사진.jpg"                 # 저장은 가로 800x400, 보이기는 세로(방향 6)
    save_jpeg(rot6, red_top(800, 400), orient=6, gps=True)
    mir = tmp / "거울.jpg"
    save_jpeg(mir, red_top(800, 400, left_green=True), orient=2, gps=False)
    plain = tmp / "보통.jpg"
    red_top(800, 400).save(plain, "JPEG", quality=90)

    from viewer import image_page
    from viewer.print_controller import PrintMixin

    class Stub:
        pass

    def make(kind, src, out):
        if kind == "끼우기":
            return image_page.images_to_pdf([src], out) > 0
        return PrintMixin._images_to_pdf(Stub(), [str(src)], str(out), downscale=(kind == "창·줄여 넣기"))

    for kind in ("끼우기", "창·원본 그대로", "창·줄여 넣기"):
        out = tmp / ("%s.pdf" % kind)
        chk(make(kind, rot6, out), "PDF 만들기 — %s" % kind)
        raw, rect, pix = first_image(out)
        ex = Image.open(io.BytesIO(raw)).getexif()
        chk(not ex.get_ifd(0x8825), "A GPS 가 PDF 그림에 없다 — %s" % kind)
        if kind != "창·줄여 넣기":
            chk(ex.get(0x0132) == "2025:06:23 09:43:07", "A 촬영 시각은 남는다 — %s" % kind)
            chk(len(raw) == rot6.stat().st_size, "A 다시 압축하지 않았다(길이 같음) — %s" % kind, "%d vs %d" % (len(raw), rot6.stat().st_size))
        chk(rect[0] < rect[1], "B 방향 6 → 세로 쪽 — %s" % kind, str(rect))
        chk(color(pix, 0.9, 0.5) == "R" and color(pix, 0.1, 0.5) == "B", "B 원래 위(빨강)가 오른쪽 — %s" % kind,
            "%s %s" % (color(pix, 0.9, 0.5), color(pix, 0.1, 0.5)))

    out = tmp / "거울.pdf"
    image_page.images_to_pdf([mir], out)
    raw, rect, pix = first_image(out)
    chk(color(pix, 0.9, 0.2) == "G" and color(pix, 0.1, 0.2) == "R", "C 거울 방향 2 → 바로 세움(초록이 오른쪽 위)",
        "%s %s" % (color(pix, 0.9, 0.2), color(pix, 0.1, 0.2)))

    from viewer import photo_io
    data = plain.read_bytes()
    chk(photo_io.jpeg_strip_gps(data) == data, "D GPS 없는 JPEG 은 바이트 그대로")
    s, rot, w, h = photo_io.pdf_image(plain)
    chk(s == data and rot == 0 and (w, h) == (800, 400), "D 방향 1 은 돌리지 않는다")

    from viewer.widgets.image_to_pdf_dialog import read_scaled
    img, w, h = read_scaled(str(rot6), 200, auto_transform=True)
    chk((w, h) == (400, 800) and img.height() > img.width(), "E 창 줄여 읽기도 세운다")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
