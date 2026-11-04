# -*- coding: utf-8 -*-
"""리본 탭 묶음은 늘 창 가운데 (261104-15, 사용자 결정 — 디자인 SOT §2.9.3, 사진 보기 SOT §9 D7).

A. PDF 전용·혼용(PDF 모드)·사진 모드 × 창 폭 여럿에서 탭 묶음 가운데 = 창 가운데(±1px)
   — 종전에는 창이 좁아(약 1000px 이하) 오른쪽 칸이 검색창 폭(220)에 걸리면 탭이 왼쪽으로 밀렸다
B. 좁을 때는 검색창이 줄어든다 — 폭은 `SEARCH_MIN_W` ~ `SEARCH_W`, 오른쪽 끝에 붙어 있다
C. 첫 레이아웃(이벤트 루프 없이)도 가운데
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
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tab_center_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "탭 가운데", echo=False)   # 마스터 §14.7.2 의 6 — 뜨는 모달은 닫는다
from viewer.app import MainWindow
from viewer.widgets import ribbon

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def mid(w, mw):
    return w.mapTo(mw, w.rect().topLeft()).x() + w.width() / 2


def set_mode(mw, mode):
    mw._photo_prefs()["view_kind"] = "pdf" if mode == "PDF 전용" else "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(mode == "사진 모드")


# C — 첫 레이아웃
mw0 = MainWindow()
set_mode(mw0, "사진 모드")
mw0.resize(900, 800)
mw0.show()
rb0 = mw0._ribbon
d0 = mid(rb0.tabs_box, mw0) - mw0.width() / 2
chk(abs(d0) <= 1, "C 첫 레이아웃 900px 사진 모드 가운데", "차이 %.1f" % d0)
mw0.close()

mw = MainWindow()
mw.show()
rb = mw._ribbon
s = mw.toolbar_search
for mode in ("PDF 전용", "혼용", "사진 모드"):
    set_mode(mw, mode)
    for wd in (1920, 1300, 1000, 900, 820):
        mw.resize(wd, 800)
        app.processEvents()
        d = mid(rb.tabs_box, mw) - mw.width() / 2
        chk(abs(d) <= 1, "A %s %dpx 탭 묶음이 창 가운데" % (mode, mw.width()), "차이 %.1f" % d)
        if s.isVisible():
            r = s.mapTo(mw, s.rect().topRight()).x()
            chk(ribbon.SEARCH_MIN_W <= s.width() <= ribbon.SEARCH_W and r > mw.width() - 20,
                "B %s %dpx 검색창 폭·자리" % (mode, mw.width()), "폭 %d 오른쪽 %d" % (s.width(), r))
mw.close()

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
