# -*- coding: utf-8 -*-
"""261010-8: 글쓰기 단추('T'/'T↘') — 폭 38, 글자는 ▾ 칸(구분선·삼각형)을 뺀 칸의 가운데 (화면 디자인 SOT §2.10).

사용자 지시: 'T↘' 기준으로 왼쪽 빈자리를 줄이고, 그 폭에서 'T' 를 ▾ 칸을 뺀 칸의 가운데로.
실제 MainView 의 단추를 그려 픽셀로 잰다 — 구분선 x 와 글자 경계(실제 글꼴, 오프스크린).
A. 'T↘' 글자가 다 보이고 왼쪽 빈자리 ≤ 3px (종전 폭 46 에서 10px)
B. 'T' 의 좌우 빈자리 차이 ≤ 1px (종전 9px — 단추 전체 가운데라 오른쪽으로 치우쳤다)
C. 지시선 모드·활성(주황 테두리)에서도 같은 값
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

app = QApplication.instance() or QApplication(sys.argv[:1])
app.setFont(QFont("Malgun Gothic", 9))
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def measure(btn):
    """(구분선 x, 글자 왼끝, 글자 오른끝) — 구분선은 높이 대부분이 테두리색인 오른쪽 열, 글자는 그 왼쪽의 진한 픽셀."""
    btn.show(); app.processEvents()
    img = btn.grab().toImage()
    W, H = img.width(), img.height()
    sep = next(x for x in range(W - 4, 4, -1)
               if sum(img.pixelColor(x, y).lightness() < 200 for y in range(H)) > H * 0.8)
    xs = [x for x in range(4, sep - 1) for y in range(6, H - 6) if img.pixelColor(x, y).lightness() < 90]
    return sep, min(xs), max(xs)


from viewer.widgets.main_view import MainView
mv = MainView()
b = mv._text_btn
chk(b.width() == MainView.TEXT_BTN_W == 38, "폭 38", str(b.width()))
for active in (False, True):
    tag = "활성" if active else "보통"
    mv._draw_kind = "text" if active else None
    for kind, glyph in (("leader", "T↘"), ("text", "T")):
        mv._text_kind = kind
        mv._update_text_button()
        sep, l, r = measure(b)
        border = 3 if active else 1
        lg, rg = l - border, sep - 1 - r
        if kind == "leader":
            full = b.fontMetrics().horizontalAdvance(glyph)
            chk(lg <= 3 and rg >= 1, "A [%s] 'T↘' 왼쪽 빈자리 ≤ 3px, 오른쪽에 붙지 않음" % tag, "왼 %d 오른 %d" % (lg, rg))
            chk(r - l + 1 >= full - 4, "A [%s] 'T↘' 글자가 다 보인다" % tag, "%d px < %d" % (r - l + 1, full))
        else:
            chk(abs(lg - rg) <= 1, "B [%s] 'T' 가 ▾ 칸을 뺀 칸의 가운데(좌우 차 ≤ 1px)" % tag, "왼 %d 오른 %d" % (lg, rg))

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
