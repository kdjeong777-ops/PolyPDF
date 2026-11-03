# -*- coding: utf-8 -*-
"""책갈피창 파일 종류 아이콘 (사진 보기 SOT §4.8, 사용자 결정 '가안 수정 — 첫 영문 크게').

A. 확장자 → 형식: 같은 형식의 다른 확장자(.jpeg·.tiff·.heif)는 한 아이콘, 대문자도, 모르는 확장자는 빈 아이콘
B. 띠 색이 형식 색(`FILE_KIND_COLOR`) — 밝은·어두운 테마 모두
C. 띠 글자색: 밝은 띠(어두운 테마 회색 TIF 등)는 어두운 글자, 그 밖에는 흰 글자
D. 첫 글자가 같은 PDF·PNG 는 색으로, 같은 회색 TIF·BMP 는 글자로 다르다
E. 형식·테마·크기마다 한 번만 그린다(같은 QIcon) — 수천 줄 목록에서 줄마다 그리지 않게
F. 배율(dpr 1·2)이 달라도 글자 폭이 같다 — 종전 점(pt) 크기 글꼴은 dpr 2 에서 띠 밖으로 넘쳤다
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor

app = QApplication.instance() or QApplication(sys.argv[:1])
from viewer.widgets import icons
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def img(kind, dark, size=48, dpr=1.0):
    return icons.file_kind_icon(kind, dark, size, dpr=dpr).pixmap(size, size).toImage()


def near(a: QColor, b: QColor, tol=24):
    return abs(a.red() - b.red()) <= tol and abs(a.green() - b.green()) <= tol and abs(a.blue() - b.blue()) <= tol


def band_pixels(im, size=48):
    """띠 안(글자 밖일 가능성이 큰 왼쪽 끝 기둥)의 색."""
    s = size / 16.0
    return QColor(im.pixel(int(1.4 * s), int(11.0 * s)))


def ink_pixels(im, ink: QColor, size=48):
    """띠 영역에서 글자색에 가까운 화소 수."""
    s = size / 16.0
    n = 0
    for y in range(int(7.4 * s), int(14.6 * s)):
        for x in range(int(1.0 * s), int(14.4 * s)):
            if near(QColor(im.pixel(x, y)), ink, 40):
                n += 1
    return n


# A
chk(icons.file_kind("a/b/사진.JPEG") == "JPG", "A1 .JPEG → JPG(대문자)")
chk(icons.file_kind("x.tiff") == "TIF" and icons.file_kind("x.heif") == "HEIC", "A2 .tiff → TIF, .heif → HEIC")
chk(icons.file_kind("x.pdf") == "PDF" and icons.file_kind("x.webp") == "WEBP", "A3 .pdf·.webp")
chk(icons.file_kind("x.txt") is None and icons.file_kind("noext") is None, "A4 모르는 확장자·확장자 없음 → None")
chk(icons.file_kind_icon("x.txt").isNull(), "A5 모르는 형식은 빈 아이콘")
chk(icons.file_kind_icon("x.jpeg", False, 16).cacheKey() == icons.file_kind_icon("JPG", False, 16).cacheKey(),
    "A6 .jpeg 와 JPG 는 같은 아이콘")

# B·C
for dark in (False, True):
    for kind, cols in icons.FILE_KIND_COLOR.items():
        im = img(kind, dark)
        want = QColor(cols[dark])
        got = band_pixels(im)
        chk(near(got, want), "B 띠 색 %s %s" % (kind, "어두운" if dark else "밝은"), "%s ≠ %s" % (got.name(), want.name()))
        ink = QColor(icons.band_ink(cols[dark]))
        chk(ink_pixels(im, ink) > 20, "C 띠 글자가 그 글자색으로 보인다 %s %s" % (kind, "어두운" if dark else "밝은"))
chk(icons.band_ink(icons.FILE_KIND_COLOR["TIF"][True]) == icons.INK_DARK, "C1 어두운 테마 회색 띠는 어두운 글자")
chk(icons.band_ink(icons.FILE_KIND_COLOR["JPG"][False]) == "#ffffff", "C2 밝은 테마 파랑 띠는 흰 글자")

# D
chk(not near(band_pixels(img("PDF", False)), band_pixels(img("PNG", False)), 40), "D1 PDF·PNG 는 띠 색이 다르다")
a, b = img("TIF", False), img("BMP", False)
chk(near(band_pixels(a), band_pixels(b), 2) and a != b, "D2 TIF·BMP 는 같은 띠 색, 글자로 다르다")

# E
chk(icons.file_kind_icon("PNG", True, 16).cacheKey() == icons.file_kind_icon("x.png", True, 16).cacheKey(),
    "E1 같은 형식·테마·크기는 한 번만 그린다")
chk(icons.file_kind_icon("PNG", True, 16).cacheKey() != icons.file_kind_icon("PNG", False, 16).cacheKey(),
    "E2 테마가 다르면 따로 그린다")


# F — 글자가 띠의 오른쪽 끝을 넘지 않는다(dpr 1·2 모두), 글자 폭이 배율과 무관
def ink_right(kind, dpr):
    size = 32
    pm = icons.file_kind_icon(kind, False, size, dpr=dpr).pixmap(int(size * dpr), int(size * dpr))
    im = pm.toImage()
    s = im.width() / 16.0
    ink = QColor("#ffffff")
    xs = [x for y in range(int(8.0 * s), int(14.4 * s)) for x in range(im.width())
          if near(QColor(im.pixel(x, y)), ink, 30)]
    return (max(xs) / s) if xs else 0.0


for kind in ("HEIC", "WEBP", "JPG"):
    r1, r2 = ink_right(kind, 1.0), ink_right(kind, 2.0)
    chk(0 < r1 < 14.4 and 0 < r2 < 14.4 and abs(r1 - r2) < 1.0, "F 글자가 띠 안·배율과 무관 %s" % kind,
        "dpr1 %.2f · dpr2 %.2f" % (r1, r2))

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
