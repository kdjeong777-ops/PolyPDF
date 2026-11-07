# -*- coding: utf-8 -*-
"""오른쪽 패널 열고 닫기 띠는 스크롤바 밖 (261107-15, 사용자 결정 '스크롤바 밖 옅은 띠' — 디자인 SOT §2.4.1).

A. 드로어(검색·스크린샷 모두 숨김 / 2단)일 때 띠가 보이고, 두 본문 창 세로 스크롤바 사각형과 겹치지 않는다 — 1단·2단·사진 모드
B. 띠는 창(가운데 칸) 높이 전부, 오른쪽 끝 — 본문은 띠 폭만큼 좁아진다(본문 오른쪽 끝 ≤ 띠 왼쪽)
C. 띠를 누르면 펼친다 → 띠는 패널 왼쪽 가장자리에 '›', 다시 누르면 접힌다. Enter 로도
D. 색은 디자인 SOT §2.5 토큰 — 다크 '패널 배경' #484848, 라이트 #e2e2e2, 드로어 바탕도 같은 토큰
E. 4단 컬럼(검색 보임)이면 띠도 자리도 없다
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, QRect, Qt
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_drawer_band_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "열고 닫기 띠", echo=False)   # 마스터 §14.7.2 의 6 — 뜨는 모달은 닫는다
from viewer.app import MainWindow
import test_fixtures

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(ms=60):
    for _ in range(4):
        app.processEvents()
        QTest.qWait(ms // 4)


def rect_in(w, mw):
    return QRect(w.mapTo(mw, QPoint(0, 0)), w.size())


mw = MainWindow()
mw.resize(1400, 820)
mw.show(); pump()
pdf = str(test_fixtures.text_pdf())
for mv in mw._mv:
    mv.load_document(pdf)
mw.act_toggle_search.setChecked(True); mw.act_toggle_shot.setChecked(True); pump()
band = mw._drawer_btn
chk(not band.isVisible() and not getattr(mw, "_drawer_gap", band).isVisible(), "E 4단 컬럼이면 띠·자리가 없다")
mw.act_toggle_search.setChecked(False); mw.act_toggle_shot.setChecked(False); pump(200)


def check_layout(tag):
    br = rect_in(band, mw)
    cen = rect_in(mw._central, mw)
    hits = []
    for mv in mw._mv:
        if mv.isVisible() and mv.doc_scroll.isVisible():
            sr = rect_in(mv.doc_scroll, mw)
            if br.intersects(sr):
                hits.append((sr.x(), sr.width()))
    chk(band.isVisible() and not hits, "A %s 띠가 보이고 본문 세로 스크롤바와 겹치지 않는다" % tag, "띠 %s 겹침 %s" % (br, hits))
    right_mv = max((rect_in(m, mw).right() for m in mw._mv if m.isVisible()), default=0)
    chk(br.height() == cen.height() and br.right() == cen.right() and right_mv < br.left(),
        "B %s 띠는 창 높이 전부·오른쪽 끝, 본문은 띠 왼쪽까지" % tag,
        "띠 %s 가운데 칸 %s 본문 오른쪽 %d" % (br, cen, right_mv))


check_layout("1단")
mw.act_split.setChecked(True); pump(200)
check_layout("2단")
mw.act_split.setChecked(False); pump(200)
mw._set_photo_mode(True); pump(200)
mw.act_toggle_search.setChecked(False); mw.act_toggle_shot.setChecked(False); pump(200)
if mw._panel_in_drawer:
    check_layout("사진 모드")
mw._set_photo_mode(False); pump(200)
mw.act_toggle_search.setChecked(False); mw.act_toggle_shot.setChecked(False); pump(200)

# C — 누르기·Enter
QTest.mouseClick(band, Qt.MouseButton.LeftButton, pos=QPoint(band.width() // 2, band.height() // 3)); pump(400)
dr = rect_in(mw._drawer, mw); br = rect_in(band, mw)
glyph = band.glyph() if hasattr(band, "glyph") else band.text()
chk(mw._drawer_open and br.right() + 1 == dr.left() and glyph == "›",
    "C 띠를 누르면 펼치고, 띠는 패널 왼쪽 가장자리에 ›", "띠 %s 패널 %s %r" % (br, dr, glyph))
band.setFocus(); QTest.keyClick(band, Qt.Key.Key_Return); pump(400)
glyph = band.glyph() if hasattr(band, "glyph") else band.text()
chk(not mw._drawer_open and glyph == "‹", "C Enter 로 접는다(‹)")

# D — 색 토큰
mw.apply_theme("dark"); pump()
bg = band.colors()[0] if hasattr(band, "colors") else None
chk(bg == "#484848" and "#484848" in mw._drawer.styleSheet(), "D 다크 — 띠·드로어 바탕 '패널 배경' #484848",
    "%s / %s" % (bg, mw._drawer.styleSheet()))
mw.apply_theme("light"); pump()
bg = band.colors()[0] if hasattr(band, "colors") else None
chk(bg == "#e2e2e2" and "#e2e2e2" in mw._drawer.styleSheet(), "D 라이트 — '패널 배경' #e2e2e2",
    "%s / %s" % (bg, mw._drawer.styleSheet()))

mw.close()
print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
