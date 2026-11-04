# -*- coding: utf-8 -*-
"""사진 모드 HEIC — pi-heif 읽기 전용판 (사진 보기 SOT 4.9·D5, 261104-2).

표본은 합성 HEIC(64×48, 위 절반 빨강, EXIF 방향 6·GPS) — 시험용 pillow-heif 로 한 번 만들어 아래에 넣었다(업무 사진 아님).
A. 없으면(구성 요소가 빠진 판): 사진 문서가 `PhotoFormatMissing` 을 낸다 — 앱은 '이 형식을 읽는 구성 요소가 없습니다' 로 알린다
B. 있으면: 처음 만날 때 한 번 등록, 크기는 보이는 대로(48×64 — 해독기가 회전을 적용), 방향이 두 번 돌지 않는다
C. 사진 문서로 열고 그리면 원래 위(빨강)가 오른쪽
D. 사진 → PDF: PyMuPDF 가 HEIC 를 못 열어도 바로 세운 JPEG 으로 들어가고, EXIF(GPS)는 싣지 않는다
E. 사진 썸네일 줄의 줄여 읽기도 된다
"""
import base64, io, os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


HEIC_B64 = "AAAAHGZ0eXBoZWljAAAAAG1pZjFoZWljbWlhZgAAAchtZXRhAAAAAAAAACFoZGxyAAAAAAAAAABwaWN0AAAAAAAAAAAAAAAAAAAAADRpbG9jAAAAAERAAAIAAQAAAAAB7AABAAAAAAAAAFQAAgAAAAACQAABAAAAAAAAAJYAAAA4aWluZgAAAAAAAgAAABVpbmZlAgAAAAABAABodmMxAAAAABVpbmZlAgAAAQACAABFeGlmAAAAAA5waXRtAAAAAAABAAABB2lwcnAAAADmaXBjbwAAAHZodmNDAQNwAAAAkAAAAAAAHvAA/P34+AAADwNgAAEAGEABDAH//wNwAAADAJAAAAMAAAMAHroCQGEAAQAqQgEBA3AAAAMAkAAAAwAAAwAeoCCBBZbq5Ka5uAhoMCAAAAMDIAAAAwAhYgABAAZEAcFzwIkAAAATY29scm5jbHgAAQANAAaAAAAAFGlzcGUAAAAAAAAAQAAAAEAAAAAoY2xhcAAAAEAAAAABAAAAMAAAAAEAAAAAAAAAAv////AAAAACAAAAEHBpeGkAAAAAAwgICAAAAAlpcm90AwAAABlpcG1hAAAAAAAAAAEAAQaBAgMFhIYAAAAaaXJlZgAAAAAAAAAOY2RzYwACAAEAAQAAAPJtZGF0AAAAUCgBrwY44+e97bfsXv//9ZR+h/T1+idFb8aVjaq9zOl9+QJ3/+LRExPzo1sKlBfylHq4bifRul9t6h6m2VU7D9254x/prjzmO4hgacXawoxDAAAABkV4aWYAAE1NACoAAAAIAAIBEgADAAAAAQAGAACIJQAEAAAAAQAAACYAAAAAAAQAAQACAAAAAk4AAAAAAgAFAAAAAwAAAFwAAwACAAAAAkUAAAAABAAFAAAAAwAAAHQAAAAAAAAAJQAAAAEAAAAhAAAAAQAAADsAAAABAAAAfgAAAAEAAAA6AAAAAQAAACkAAAAB"

tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_heic_"))
try:
    p = tmp / "아이폰 사진.heic"
    p.write_bytes(base64.b64decode(HEIC_B64))
    from viewer import photo_io
    from viewer.photo_doc import PhotoDocument, PhotoFormatMissing

    # A — 구성 요소가 없는 판을 흉내
    sys.modules["pi_heif"] = None
    raised = False
    try:
        PhotoDocument(p)
    except PhotoFormatMissing:
        raised = True
    except Exception as e:
        print("     다른 예외", type(e).__name__)
    chk(raised, "A 구성 요소가 없으면 PhotoFormatMissing")
    del sys.modules["pi_heif"]
    photo_io._HEIF_STATE.update(tried=False, ok=False)

    # B
    chk(photo_io.heif_ready(), "B pi-heif 가 있으면 등록된다")
    chk(photo_io.oriented_size(p) == (48, 64), "B 크기는 보이는 대로(48×64)", str(photo_io.oriented_size(p)))
    chk(photo_io.orientation(p) == 1, "B 방향은 해독기가 이미 적용(두 번 돌지 않게 1)")

    # C
    doc = PhotoDocument(p)
    r = doc.render_scaled(0, 1.0)
    from PyQt6.QtGui import QImage
    img = QImage(r.samples, r.width, r.height, r.width * 3, QImage.Format.Format_RGB888).copy()
    def red(x, y):
        c = img.pixelColor(x, y)
        return c.red() > 150 and c.blue() < 120
    chk((r.width, r.height) == (48, 64) and red(44, 32) and not red(3, 32), "C 사진 문서 — 원래 위(빨강)가 오른쪽")
    doc.close()

    # D
    from viewer import image_page
    import fitz
    out = tmp / "묶음.pdf"
    n = image_page.images_to_pdf([p], out)
    d = fitz.open(str(out))
    pg = d[0]
    info = d.extract_image(pg.get_images()[0][0])
    from PIL import Image
    ex = Image.open(io.BytesIO(info["image"])).getexif()
    chk(n == 1 and (round(pg.rect.width), round(pg.rect.height)) == (48, 64), "D HEIC → PDF 쪽(48×64)")
    chk(info["ext"] in ("jpeg", "jpg") and not ex.get_ifd(0x8825), "D JPEG 으로 들어가고 GPS 없음", str(info["ext"]))
    d.close()

    # E
    from viewer.widgets.photo_strip import load_thumb
    t = load_thumb(str(p), 64)
    chk(not t.isNull() and t.height() > t.width(), "E 썸네일 줄여 읽기(세로)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
