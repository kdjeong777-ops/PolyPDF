# -*- coding: utf-8 -*-
"""선긋기 단추의 하이라이트 그림 = 굵고 반투명한 형광펜 띠 (261111-5, 사용자 지시 — 디자인 SOT §4.5).

A. 하이라이트 모드면 단추에 글자 대신 그림(`color_icon("highlighter")`), 직선·자유곡선은 종전 글리프 ─ · 〜
B. 그림에 노란 띠가 있고 **반투명**(알파 HL_ALPHA 근처), 띠 두께 ≥ 16px 칸의 5px — 종전 '▬' 글리프는 얇은 검은 막대였다
C. 띠 밑으로 글자 줄이 비친다 — 띠 가운데 픽셀이 순수 노랑보다 어둡다(라이트) / 섞인 색(다크)
D. 실제 단추를 그리면(grab) 노란 띠가 보인다 — 본문 도구 줄(라이트·다크)·발표 띠
E. 켜진 단추(살구색 바탕)에서도 띠가 묻히지 않는다 — 띠 가장자리 진한 호박색 테 `HL_EDGE`(261111-5 보완, 사용자 보고)
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 검사 작성 SOT §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_hl_icon_%d" % os.getpid())
from viewer.widgets import icons
from viewer import theme

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def yellowish(c: QColor) -> bool:
    h = c.hsvHue()
    return 35 <= h <= 60 and c.hsvSaturation() > 90 and c.value() > 120


# B·C — 그림 자체(16칸을 64px 로)
for dark in (False, True):
    img = icons.color_icon("highlighter", dark=dark, size=64, dpr=1.0).pixmap(64, 64).toImage()
    band = [(x, y) for y in range(64) for x in range(64) if yellowish(img.pixelColor(x, y)) and img.pixelColor(x, y).alpha() > 40]
    alphas = [img.pixelColor(x, y).alpha() for (x, y) in band]
    semi = [a for a in alphas if 60 <= a <= 210]
    col = [y for (x, y) in band if x == 32]
    thick = (max(col) - min(col) + 1) if col else 0
    tag = "다크" if dark else "라이트"
    chk(len(band) > 200 and len(semi) > len(band) * 0.5, "B %s 노란 띠가 있고 반투명" % tag,
        "띠 %d 반투명 %d" % (len(band), len(semi)))
    chk(thick >= 20, "B %s 띠 두께 ≥ 5/16(64px 에서 20px)" % tag, "%dpx" % thick)
    mid = img.pixelColor(32, 34)          # 글자 줄(8.5/16)이 지나는 띠 가운데
    pure = QColor(icons.ACCENT["highlighter"][dark])
    chk(mid.alpha() > 200 and (mid.value() < pure.value() - 15 if not dark else abs(mid.value() - pure.value()) > 3 or mid.hsvSaturation() < pure.hsvSaturation()),
        "C %s 띠 밑 글자 줄이 비친다" % tag, "가운데 %s alpha %d / 순수 %s" % (mid.name(), mid.alpha(), pure.name()))

# A·D — 실제 단추
from viewer.widgets.main_view import MainView
for dark in (False, True):
    theme.set_dark(dark)
    mv = MainView(); mv.apply_theme(dark); mv.resize(900, 600); mv.show(); app.processEvents()
    mv.set_draw_line_mode(0); app.processEvents()
    t0 = "직선 그림" if (mv._draw_mode_btn.text() == "" and not mv._draw_mode_btn.icon().isNull()) else mv._draw_mode_btn.text()
    mv.set_draw_line_mode(2); app.processEvents()
    t2 = mv._draw_mode_btn.text()
    mv.set_draw_line_mode(1); mv._update_line_button(); app.processEvents()
    b = mv._draw_mode_btn
    b.show(); b.resize(30, 26); app.processEvents()
    g = b.grab().toImage()
    ys = sum(1 for y in range(g.height()) for x in range(g.width()) if yellowish(g.pixelColor(x, y)))
    tag = "다크" if dark else "라이트"
    chk(t0 == "직선 그림" and t2 == "〜" and b.text() == "" and not b.icon().isNull(),
        "A %s 본문 단추 — 직선 그림·자유곡선 〜 글리프, 하이라이트는 그림" % tag, "%r %r %r" % (t0, t2, b.text()))
    chk(ys >= 25, "D %s 본문 단추를 그리면 노란 띠가 보인다" % tag, "노란 픽셀 %d" % ys)
    mv.close()
theme.set_dark(False)

# E — 켜진 단추(살구색 바탕 #ffce99)에서도 띠가 선다: 띠 가장자리에 진한 호박색 테(사용자 보고 '선택되어 있을 때 오히려 잘 안보여')
def amber_edge(c: QColor) -> bool:
    return 30 <= c.hsvHue() <= 50 and c.hsvSaturation() > 150 and c.value() < 190
for dark in (False, True):
    theme.set_dark(dark)
    mv = MainView(); mv.apply_theme(dark); mv.resize(900, 600); mv.show(); app.processEvents()
    mv._draw_kind = "line"
    mv.set_draw_line_mode(1); mv._update_line_button(); app.processEvents()
    b = mv._draw_mode_btn
    b.show(); b.resize(30, 26); app.processEvents()
    g = b.grab().toImage()
    edge = sum(1 for y in range(4, g.height() - 4) for x in range(4, g.width() - 4) if amber_edge(g.pixelColor(x, y)))
    chk(edge >= 12, "E %s 켜진 단추(살구색 바탕)에서 띠 테가 보인다" % ("다크" if dark else "라이트"), "테 픽셀 %d" % edge)
    mv.close()
theme.set_dark(False)

# F — 직선 단추의 선 굵기 = 옆 직사각형(도형) 단추의 선 굵기(사용자 지시 '직선이 너무 얇아. 옆의 직사각형의 선굵기와 동일하게')
def ink_rows(img, x):
    """x 열에서 진한(글자색) 픽셀이 이어진 가장 긴 세로 길이."""
    best = run = 0
    for y in range(img.height()):
        c = img.pixelColor(x, y)
        if c.alpha() > 100 and c.value() < 110:
            run += 1; best = max(best, run)
        else:
            run = 0
    return best
mv = MainView(); mv.apply_theme(False); mv.resize(900, 600); mv.show(); app.processEvents()
mv._draw_kind = None
mv.set_draw_line_mode(0); mv._update_line_button(); mv._update_shape_button(); app.processEvents()
li = mv._draw_mode_btn.icon().pixmap(18, 18).toImage()
si = mv._shape_btn.icon().pixmap(28, 18).toImage()
lt = ink_rows(li, li.width() // 2)
st_top = ink_rows(si.copy(0, 0, si.width(), si.height() // 2), 9)     # 직사각형 윗변(왼쪽 18 안 가운데 열)
chk(lt >= 2 and abs(lt - st_top) <= 0, "F 직선 굵기 = 직사각형 선 굵기", "직선 %dpx · 직사각형 %dpx" % (lt, st_top))
mv.close()

from viewer.widgets.presentation import PresentationWindow
from viewer.widgets.main_view import MV_DEFAULT_PENS
import test_fixtures
pw = PresentationWindow(str(test_fixtures.text_pdf()), 0, None, pens=[dict(p) for p in MV_DEFAULT_PENS],
                        line_mode=0, highlight_alpha=40)
pw.resize(800, 600); pw.show(); app.processEvents()
pw.set_line_mode(1); app.processEvents()
b = pw._tb_mode
g = b.grab().toImage()
ys = sum(1 for y in range(g.height()) for x in range(g.width()) if yellowish(g.pixelColor(x, y)))
chk(b.text() == "" and not b.icon().isNull() and ys >= 25, "D 발표 띠 단추도 같은 형광펜 그림", "%r 노란 %d" % (b.text(), ys))
pw.close()

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
