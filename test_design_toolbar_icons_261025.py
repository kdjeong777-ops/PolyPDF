# -*- coding: utf-8 -*-
"""261025-10: 본문 도구 줄 아이콘 (화면 디자인 SOT §2.7·§2.10·§4.5, 사용자 지시·결정).

실제 MainWindow 의 단추를 그려 픽셀로 잰다(오프스크린, 실제 글꼴).
A. 드롭다운 단추(캡쳐 모드·재생구간, 단어장 출처·재생구간·재생내용) 글자에 ▾ 가 없다 — 삼각형은 Qt 메뉴 화살표 하나
B. 캡쳐 카메라가 옆 단추와 어울리는 크기(색 픽셀 높이 ≥ 13px — 종전 PNG 는 테두리 안의 작은 카메라)
C. 읽기 ▶ 가 단추 세로 가운데(색 픽셀 위·아래 빈자리 차 ≤ 1px — 종전 글리프 ▶ 는 아래로 처졌다)
D. 다크로 바꾸면 ▶·카메라가 밝은 파랑, 읽는 중 ■ 는 밝은 빨강 / 라이트로 돌리면 원래 색 (단어장 ▶ 도)
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QColor

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_toolbar_icons_261025_%d" % os.getpid())
app.setFont(QFont("Malgun Gothic", 9))
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump():
    for _ in range(5):
        app.processEvents()


def colored(c: QColor) -> bool:
    """회색이 아닌(채도 있는) 픽셀 — 단추 바탕·테두리·글자는 회색이다."""
    return c.hsvSaturation() > 90 and c.value() > 60


def color_box(btn):
    """색 픽셀의 (위, 아래, 높이, 가장 진한 색) — 단추를 그려서."""
    btn.show(); pump()
    img = btn.grab().toImage()
    pts = [(x, y) for y in range(img.height()) for x in range(img.width()) if colored(img.pixelColor(x, y))]
    if not pts:
        return None
    ys = [y for _x, y in pts]
    best = max((img.pixelColor(x, y) for x, y in pts), key=lambda c: c.hsvSaturation() * 1000 + c.alpha())
    return min(ys), max(ys), img.height(), best


def near(c: QColor, hexv: str, tol=40) -> bool:
    t = QColor(hexv)
    return abs(c.red() - t.red()) + abs(c.green() - t.green()) + abs(c.blue() - t.blue()) <= tol


from viewer.app import MainWindow
from viewer.widgets import icons
mw = MainWindow()
mw.resize(1300, 800)
mw.apply_theme("light")
mw.show(); pump()
sp = mw.study_panel

# A. 드롭다운 글자에 ▾ 없음 — 메뉴는 달려 있다(Qt 화살표가 그 하나)
drops = [("캡쳐 모드", d) for d in mw._cap_menus] + [("재생구간", m) for _b, m in mw._read_btns] + [
    ("단어장 출처", sp.btn_src), ("단어장 재생구간", sp.btn_readmode), ("단어장 재생내용", sp.btn_content)]
for name, b in drops:
    chk("▾" not in b.text() and "▼" not in b.text() and b.menu() is not None,
        "A '%s' 글자에 ▾ 없음·메뉴 있음" % name, repr(b.text()))
    chk("padding-right" in b.styleSheet(), "A '%s' 화살표 자리 오른쪽 여백(drop_button)" % name, repr(b.styleSheet()))
# 바꾼 뒤에도(모드 고르기·캡쳐 메뉴 다시 만들기) ▾ 가 다시 붙지 않는다
mw._refresh_capture_labels()
sp._set_read_mode(sp._read_mode)
chk(all("▾" not in b.text() for _n, b in drops), "A 다시 만든 뒤에도 ▾ 없음", str([b.text() for _n, b in drops]))

# A2. 맞춤 콤보의 ▾ 는 드롭다운 단추와 같은 오른쪽 아래 작은 화살표 — 진한 픽셀이 그 자리에만 있고, 큰 화살표 자리(세로 가운데)에는 없다
cmb = mw.cmb_fit                    # 261031-11: 맞춤 콤보는 창 아래(+ 0 − 왼쪽)
cmb.show(); pump()
img = cmb.grab().toImage()
ar = icons.corner_arrow_rect(cmb)
txt_end = 6 + cmb.fontMetrics().horizontalAdvance(cmb.currentText()) + 4
dark_px = [(x, y) for y in range(3, img.height() - 3) for x in range(txt_end, img.width() - 3)
           if img.pixelColor(x, y).lightness() < 110]
in_corner = [pt for pt in dark_px if ar.adjusted(-1, -1, 1, 1).contains(*pt)]
chk(bool(in_corner) and len(in_corner) == len(dark_px), "A2 맞춤 콤보 화살표는 오른쪽 아래 작은 것 하나",
    "구석 %d / 글자 뒤 진한 픽셀 %d, 자리 %s" % (len(in_corner), len(dark_px), ar))

# B. 카메라 크기
cam = mw.btn_capture
box = color_box(cam)
chk(box is not None and box[1] - box[0] + 1 >= 13, "B 카메라 색 픽셀 높이 ≥ 13px",
    "box=%s" % (box[:3] if box else None,))
chk(cam.iconSize().height() >= 18, "B 카메라 아이콘 크기 ≥ 18", str(cam.iconSize()))

# C. ▶ 세로 가운데
play = mw._read_btns[0][0]
box = color_box(play)
if box is None:
    chk(False, "C ▶ 색 픽셀이 보인다")
else:
    top, bot, h, _c = box
    chk(abs(top - (h - 1 - bot)) <= 1, "C ▶ 세로 가운데(위·아래 빈자리 차 ≤ 1px)", "위 %d 아래 %d" % (top, h - 1 - bot))
    chk(bot - top + 1 >= 10, "C ▶ 크기 ≥ 10px", str(bot - top + 1))

# D. 다크·라이트 색
for theme, dark in (("dark", True), ("light", False)):
    mw.apply_theme(theme); pump()
    tag = "다크" if dark else "라이트"
    for name, b, key in (("본문 ▶", play, "play"), ("카메라", cam, "camera"), ("단어장 ▶", sp.btn_play, "play")):
        box = color_box(b)
        want = icons.ACCENT[key][dark]
        chk(box is not None and near(box[3], want), "D [%s] %s 색 %s" % (tag, name, want),
            box[3].name() if box else "없음")
    # 읽는 중 ■
    mw.read_aloud._active = True
    mw.read_aloud._view = mw._mv[0]
    mw._update_read_buttons()
    box = color_box(play)
    want = icons.ACCENT["stop"][dark]
    chk(play.text() == "■" and box is not None and near(box[3], want), "D [%s] 읽는 중 ■ 색 %s" % (tag, want),
        box[3].name() if box else "없음")
    mw.read_aloud._active = False
    mw._update_read_buttons()

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
