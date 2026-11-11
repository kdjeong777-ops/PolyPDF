# -*- coding: utf-8 -*-
"""파일 탭 '폴더 열기·파일 열기' 그림은 등록 폴더·등록 파일(▾)과 다르다 (261111-13, 사용자 지시 — 디자인 SOT §4.5).

종전에는 폴더 열기 = 등록 폴더(`fav_folder`), 파일 열기 = 등록 파일(`fav_file`) 같은 그림이라 네 단추가 둘씩 같았다.
A. 네 그림(open_folder·open_file·fav_folder·fav_file)이 라이트·다크 모두 서로 다르다
B. 실제 창 파일 탭의 '폴더 열기'·'파일 열기' 동작 그림 = 열린 폴더 그림, 등록 폴더·등록 파일 ▾ 메뉴 그림과 다르다
C. 열린 폴더 그림은 앞판이 비스듬히 열린 꼴 — 위쪽이 아래쪽보다 오른쪽으로 더 나가 있다(앞판 기울기), 파일 열기는 파란 서류가 폴더 위로 나온다
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
QCoreApplication.setApplicationName("polypdf_open_icons_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "열기 그림", echo=False)   # 검사 작성 SOT §14.7.2 의 6
from viewer.widgets import icons

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def img_of(icon, px=32):
    return icon.pixmap(px, px).toImage()


def differ(a, b) -> int:
    return sum(1 for y in range(a.height()) for x in range(a.width()) if a.pixelColor(x, y) != b.pixelColor(x, y))


NAMES = ("open_folder", "open_file", "fav_folder", "fav_file")
for dark in (False, True):
    ims = {n: img_of(icons.color_icon(n, dark=dark, size=32)) for n in NAMES}
    pairs = [(a, b, differ(ims[a], ims[b])) for i, a in enumerate(NAMES) for b in NAMES[i + 1:]]
    empty = [n for n in NAMES if sum(1 for y in range(32) for x in range(32) if ims[n].pixelColor(x, y).alpha() > 0) < 100]
    chk(not empty and all(d > 60 for _a, _b, d in pairs), "A %s 네 그림이 서로 다르다" % ("다크" if dark else "라이트"),
        "빈 그림 %s / %s" % (empty, [(a, b, d) for a, b, d in pairs if d <= 60]))

# C — 모양
of = img_of(icons.color_icon("open_folder", dark=False, size=64), 64)
def right_edge(img, y):
    xs = [x for x in range(64) if img.pixelColor(x, y).alpha() > 120]
    return max(xs) if xs else -1
chk(right_edge(of, int(8.6 / 16 * 64)) > right_edge(of, int(14.0 / 16 * 64)) + 3,
    "C 폴더 열기 — 앞판 위쪽이 아래쪽보다 오른쪽으로(비스듬히 열림)",
    "%d / %d" % (right_edge(of, int(8.6 / 16 * 64)), right_edge(of, int(14.0 / 16 * 64))))
ff = img_of(icons.color_icon("open_file", dark=False, size=64), 64)
blue_top = sum(1 for y in range(0, int(4.0 / 16 * 64)) for x in range(64)
               if (lambda c: c.alpha() > 120 and c.blue() > 150 and c.red() < 80)(ff.pixelColor(x, y)))
chk(blue_top > 40, "C 파일 열기 — 파란 서류가 폴더 위로 나온다", "위쪽 파란 픽셀 %d" % blue_top)

# B — 실제 창
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(1300, 700); mw.show()
for _ in range(4):
    app.processEvents(); QTest.qWait(30)
acts = dict((name, a) for a, name in getattr(mw, "_file_icon_acts", ()))
inv = {a: n for n, a in acts.items()}
a_open = next((a for n, a in acts.items() if n in ("open_folder", "fav_folder") and a.text().replace("&", "").startswith("폴더")), None)
a_file = next((a for n, a in acts.items() if n in ("open_file", "fav_file") and a.text().replace("&", "").startswith("파일")), None)
px = icons.FAV_ICON_PX
ok = a_open is not None and a_file is not None
if ok:
    io, ifl = img_of(a_open.icon(), px), img_of(a_file.icon(), px)
    rf, rfl = img_of(mw.menu_fav_folders.menuAction().icon(), px), img_of(mw.menu_fav_files.menuAction().icon(), px)
    chk(inv.get(a_open) == "open_folder" and inv.get(a_file) == "open_file" and differ(io, rf) > 10 and differ(ifl, rfl) > 10,
        "B 파일 탭 폴더 열기·파일 열기 = 열린 폴더 그림, 등록 폴더·등록 파일 ▾ 와 다르다",
        "%s %s 차이 %d %d" % (inv.get(a_open), inv.get(a_file), differ(io, rf), differ(ifl, rfl)))
else:
    chk(False, "B 파일 탭 폴더 열기·파일 열기 동작을 찾는다", str([(a.text(), n) for n, a in acts.items()]))
mw.close()

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
