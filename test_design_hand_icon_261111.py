# -*- coding: utf-8 -*-
"""손바닥 단추 아이콘 = 손 윤곽(굵기 1.4) + 손가락 사이 **얇은 선** (261111-14, 사용자 지시 '원래 아이콘에서 손가락 사이를 얇은 선으로' — 디자인 SOT §4.2).

A. 손가락 높이(16칸의 5.5)를 가로로 지나면 바깥 테 둘 사이에 손가락 사이 선이 셋 — 사이 선은 바깥 테보다 얇다(종전 261107-36 은
   손가락 막대를 띄워 사이마다 테 두 줄 + 사이 선이 겹쳐 바깥 테보다 굵었다, 261111-9 는 사이 선이 아예 없었다)
B. 바깥 테 두께는 다른 라인 아이콘과 같다 — 1.4px(64px 그림에서 4~8px)
C. 손 모양 — 가운데 손가락 둘이 바깥 둘보다 높다
D. 실제 단추(본문 그리기 줄 `_draw_pan_btn`)에 그 그림이 들어간다
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 검사 작성 SOT §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_hand_icon_%d" % os.getpid())
from viewer.widgets import icons

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


S = 64
img = icons.themed_icon("hand", dark=False, size=S).pixmap(S, S).toImage()


def ink(x, y):
    return img.pixelColor(x, y).alpha() > 110


def runs_row(y):
    out, on, start = [], False, 0
    for x in range(S):
        if ink(x, y) and not on:
            on, start = True, x
        elif not ink(x, y) and on:
            on = False; out.append((start, x - start))
    if on:
        out.append((start, S - start))
    return out


row = [r for r in runs_row(int(5.5 / 16 * S)) if r[0] >= int(3.0 / 16 * S)]     # 엄지(왼쪽 끝)는 빼고 손가락 폭만
edges, seps = ([row[0], row[-1]], row[1:-1]) if len(row) >= 2 else (row, [])
chk(len(seps) == 3 and max(w for _x, w in seps) * 1.5 <= min(w for _x, w in edges),
    "A 손가락 사이 선 셋, 바깥 테보다 얇다", str(row))
chk(all(4 <= w <= 8 for _x, w in edges), "B 바깥 테 두께 ≈ 1.4px(64px 에서 4~8)", str(row))


def top_of(xu):
    x = int(xu / 16 * S)
    for y in range(S):
        if ink(x, y):
            return y
    return S
fw = getattr(icons, "HAND_FW", 2.0)
cx = [x + fw / 2 for x, _t in getattr(icons, "HAND_FINGERS", ((4.0, 3.6), (6.4, 1.6), (8.8, 1.6), (11.2, 3.2)))]
outer = (top_of(cx[0]), top_of(cx[3]))
inner = (top_of(cx[1]), top_of(cx[2]))
chk(max(inner) + 3 < min(outer), "C 가운데 손가락 둘이 바깥 둘보다 높다(손 윤곽)", "안 %s 바깥 %s" % (inner, outer))

from viewer.widgets.main_view import MainView
mv = MainView(); mv.resize(900, 500); mv.show(); app.processEvents()
mv.refresh_theme_icons(False)
bi = mv._draw_pan_btn.icon().pixmap(16, 16).toImage()
ref = icons.themed_icon("hand", dark=False, size=16).pixmap(16, 16).toImage()
same = sum(1 for y in range(16) for x in range(16) if (bi.pixelColor(x, y).alpha() > 110) == (ref.pixelColor(x, y).alpha() > 110))
chk(same >= 250, "D 실제 손바닥 단추에 그 그림", "%d / 256" % same)
mv.close()

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
