# -*- coding: utf-8 -*-
"""그림 단추 아이콘 여백 (화면 디자인 SOT §4.6, 사용자 지시 '아이콘이 단추에 꽉 차 답답').

실제 MainWindow 를 그려 잰다(오프스크린).
A. 단어장 머리줄(편집·Word·mp3·단어장 생성)·본문 도구 줄(카메라·mp3) 아이콘은 BTN_ICON_PX
B. 보이는 모든 아이콘 단추: 아이콘 높이 ≤ 단추 높이 − 2×ICON_MARGIN (종전 단어장 22·mp3 24 는 26 단추를 꽉 채웠다)
C. 검색결과 '전체 캡쳐' 는 도구 줄과 같은 그린 카메라 — 테마를 바꾸면 그 색으로(종전 screenshot.png)
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication, QAbstractButton, QToolButton
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_icon_margin_%d" % os.getpid())
app.setFont(QFont("Malgun Gothic", 9))
import modal_guard
modal_guard.install(label=lambda: "아이콘 여백", echo=False)   # 마스터 §14.7.2 의 6 — 뜨는 모달은 닫는다
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump():
    for _ in range(5):
        app.processEvents()


def main_color(btn):
    """단추에서 가장 진한 채도 있는 픽셀 색."""
    btn.show(); pump()
    img = btn.grab().toImage()
    best = None
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.hsvSaturation() > 90 and c.value() > 60 and (best is None or c.hsvSaturation() > best.hsvSaturation()):
                best = c
    return best


def near(c, hexv, tol=40):
    t = QColor(hexv)
    return c is not None and abs(c.red() - t.red()) + abs(c.green() - t.green()) + abs(c.blue() - t.blue()) <= tol


from viewer.app import MainWindow
from viewer.widgets import icons
mw = MainWindow()
mw.resize(1300, 800)
mw.apply_theme("light")
mw.show(); pump()
sp = mw.study_panel
sp.show()
sr = mw.search_results
sr.show(); pump()

# A
for name, b in (("단어장 편집", sp.btn_edit), ("단어장 Word", sp.btn_word), ("단어장 mp3", sp.btn_mp3),
                ("단어장 생성", sp.btn_build), ("도구 줄 카메라", mw.btn_capture), ("도구 줄 mp3", mw.btn_main_mp3)):
    chk(b.iconSize().height() == icons.BTN_ICON_PX, "A %s 아이콘 %d" % (name, icons.BTN_ICON_PX), str(b.iconSize()))

# B
seen = 0
for b in mw.findChildren(QAbstractButton):
    if not b.isVisibleTo(mw) or b.icon().isNull() or b.height() <= 0:
        continue
    if type(b.parentWidget()).__name__ == "QLineEdit":     # Qt 가 입력칸 안에 넣는 지우기(×) 단추 — 우리 단추가 아니다
        continue
    if isinstance(b, QToolButton) and b.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextOnly:
        continue
    seen += 1
    lim = b.height() - 2 * icons.ICON_MARGIN
    chk(b.iconSize().height() <= lim, "B 여백 %s '%s'" % (type(b).__name__, b.toolTip()[:30] or b.text()),
        "아이콘 %d > 단추 %d − %d (%s ← %s)" % (b.iconSize().height(), b.height(), 2 * icons.ICON_MARGIN,
                                           b.objectName(), type(b.parentWidget()).__name__))
chk(seen >= 8, "B 잰 단추 수 ≥ 8", str(seen))

# C
shot = sr.btn_shot_result
chk(shot.property("colorIcon") == "camera", "C 전체 캡쳐는 그린 카메라", repr(shot.property("colorIcon")))
for theme, dark in (("dark", True), ("light", False)):
    mw.apply_theme(theme); pump()
    c = main_color(shot)
    want = icons.ACCENT["camera"][dark]
    chk(near(c, want), "C [%s] 전체 캡쳐 카메라 색 %s" % (theme, want), c.name() if c else "없음")
    chk(shot.iconSize().height() == 16, "C [%s] 전체 캡쳐 아이콘 16 유지" % theme, str(shot.iconSize()))

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
