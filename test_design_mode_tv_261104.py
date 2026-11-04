# -*- coding: utf-8 -*-
"""261104-2: PDF ↔ 사진 모드 토글 TV 그림 (사진 보기 SOT 4.1, 디자인 SOT §4.5·§4.6, 사용자 지시 '한 화면에 PDF 또는 사진만, 크게').

mode_tv_icon 을 실제 단추 크기(MODE_ICON_PX, 배율 2)로 그려 픽셀로 잰다 — 라이트·다크 모두.
A. PDF 모드 화면에는 붉은 PDF 만(사진의 파랑·초록 없음), 사진 모드 화면에는 사진만(붉은 PDF 없음)
B. 지금 모드 그림이 크다 — 색 픽셀이 그림 전체의 SHARE_MIN 이상(종전 겹친 두 장은 앞 장이 작아 구분이 안 됐다)
C. 그려진 TV 높이 ≤ 단추 높이 − 2×ICON_MARGIN (탭 줄 안, 디자인 SOT §4.6)
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QSize
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QToolButton
from PyQt6.QtGui import QColor

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_mode_tv_261104_%d" % os.getpid())
from viewer.widgets import icons
from viewer.photo_controller import MODE_ICON_PX

SHARE_MIN = 0.22
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def near(c, hexv, tol=60):
    t = QColor(hexv)
    return abs(c.red() - t.red()) + abs(c.green() - t.green()) + abs(c.blue() - t.blue()) <= tol


for dark in (False, True):
    tag = "다크" if dark else "라이트"
    red = icons.FILE_KIND_COLOR["PDF"][dark]
    blue, green = icons.ACCENT["play"][dark], icons.OK_GREEN[dark]
    for photo in (False, True):
        img = icons.mode_tv_icon(photo, dark, MODE_ICON_PX).pixmap(QSize(MODE_ICON_PX, MODE_ICON_PX), 2.0).toImage()
        grey = icons.FILE_KIND_LINE[dark]          # 종전 뒤 장(꺼진 모드)의 회색
        k = img.width() / 16.0                     # 16 캔버스 → 픽셀
        scr = icons.TV_SCREEN.adjusted(0.5, 0.5, -0.5, -0.5)
        n_red = n_photo = n_all = n_grey = 0
        ys = []
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.alpha() < 200:
                    continue
                n_all += 1
                ys.append(y)
                if near(c, red):
                    n_red += 1
                elif near(c, blue) or near(c, green):
                    n_photo += 1
                elif near(c, grey, 12) and scr.contains(x / k, y / k):    # 화면 안만 — 몸체 가장자리 흐림은 빼고
                    n_grey += 1
        mode = "사진" if photo else "PDF"
        chk(n_grey <= 4, "A [%s] %s 화면에 꺼진 모드의 회색 장 없음" % (tag, mode), str(n_grey))
        if photo:
            chk(n_red == 0, "A [%s] 사진 모드 화면에 붉은 PDF 없음" % tag, str(n_red))
            share = n_photo / max(1, n_all)
        else:
            chk(n_photo == 0, "A [%s] PDF 모드 화면에 사진 없음" % tag, str(n_photo))
            share = n_red / max(1, n_all)
        chk(share >= SHARE_MIN, "B [%s] %s 그림 면적 ≥ %.0f%%" % (tag, mode, SHARE_MIN * 100), "%.1f%%" % (share * 100))
        drawn_h = (max(ys) - min(ys) + 1) / 2.0 if ys else 0
        b = QToolButton(); b.setAutoRaise(True); b.setIconSize(QSize(MODE_ICON_PX, MODE_ICON_PX)); b.setIcon(icons.mode_tv_icon(photo, dark, MODE_ICON_PX))
        bh = b.sizeHint().height()
        chk(drawn_h <= bh - 2 * icons.ICON_MARGIN, "C [%s] %s TV 높이 %.1f ≤ 단추 %d − %d" % (tag, mode, drawn_h, bh, 2 * icons.ICON_MARGIN))

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
