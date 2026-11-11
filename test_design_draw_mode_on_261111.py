# -*- coding: utf-8 -*-
"""지우개·개체선택·손바닥이 켜지면 선긋기·도형 단추와 같은 주황 강조 (261111-9 보완, 사용자 결정 — 디자인 SOT §2.7).

종전에는 Qt 기본 체크 바탕이라 다크에서 켜짐(#333336)과 꺼짐(#3d3d40)이 거의 같아 켜졌는지 안 보였다.
A. 다크·라이트 실제 MainWindow 에서 각 단추를 켜면 주황 테(#ff7a00) 픽셀이 보인다, 끄면 없다
B. 켜진 손바닥 그림은 살구색 바탕에서 어두운 색(밝은 다크 그림이 묻히지 않게) — 꺼지면 테마 색
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 검사 작성 SOT §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_draw_mode_on_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "그리기 켜짐 강조", echo=False)   # 검사 작성 SOT §14.7.2 의 6
from viewer.app import MainWindow
import test_fixtures

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump():
    for _ in range(4):
        app.processEvents(); QTest.qWait(30)


def orange(img):
    return sum(1 for y in range(img.height()) for x in range(img.width())
               if (lambda c: c.red() > 230 and 100 < c.green() < 150 and c.blue() < 40)(img.pixelColor(x, y)))


mw = MainWindow(); mw.resize(1400, 800); mw.show()
mv = mw.main_view
mv.load_document(str(test_fixtures.text_pdf())); pump()
mv.set_draw_mode(True); pump()
for theme in ("dark", "light"):
    mw.apply_theme(theme); pump()
    for name, kind, btn in (("개체선택", "select", mv._draw_select_btn), ("손바닥", "pan", mv._draw_pan_btn),
                            ("지우개", "erase", mv._draw_erase_btns[0])):
        mv._erase_k = 0
        mv._draw_kind = kind; mv._apply_tool(); pump()
        on = orange(btn.grab().toImage())
        mv._draw_kind = None; mv._apply_tool(); pump()
        off = orange(btn.grab().toImage())
        chk(on >= 40 and off == 0, "A %s %s — 켜면 주황 테, 끄면 없다" % (theme, name), "켜짐 %d 꺼짐 %d" % (on, off))
    mv._draw_kind = "pan"; mv._apply_tool(); pump()
    hi = mv._draw_pan_btn.icon().pixmap(16, 16).toImage()
    ink = [hi.pixelColor(x, y) for y in range(16) for x in range(16) if hi.pixelColor(x, y).alpha() > 150]
    dark_ink = ink and sum(c.value() for c in ink) / len(ink) < 120
    chk(bool(dark_ink), "B %s 켜진 손바닥 그림은 어두운 색(살구색 바탕)" % theme)
    mv._draw_kind = None; mv._apply_tool(); pump()

mw.close()
print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
