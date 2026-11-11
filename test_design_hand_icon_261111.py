# -*- coding: utf-8 -*-
"""손바닥 단추 아이콘 = 손 윤곽만, 손가락 사이 선 없음 (261111-9, 사용자 결정 'A 윤곽만' — 디자인 SOT §4.2).

A. 손가락 높이(16칸의 5.5)를 가로로 지나면 잉크는 바깥 테 두 번뿐 — 종전 손가락 사이 선 셋이 더 있었다(다섯 번)
B. 선 굵기는 다른 라인 아이콘과 같다 — 바깥 테 한 줄 두께가 1.4px(64px 그림에서 5~7px)
C. 손 모양은 남는다 — 손가락 끝 높이가 다르다(가운데 둘이 바깥 둘보다 높다 — 윗변 굴곡)
D. 실제 단추(본문 그리기 줄 `_draw_pan_btn`)에 그 그림이 들어간다
E. 엄지가 손바닥에서 벌어져 있다 — 엄지 테와 손바닥 테 사이 빈 틈(261111-12, 사용자 지시)
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
chk(len(row) == 2, "A 손가락 높이 가로줄에 잉크는 바깥 테 두 번뿐(손가락 사이 선 없음)", str(row))
chk(all(4 <= w <= 8 for _x, w in row), "B 바깥 테 두께 ≈ 1.4px(64px 에서 4~8)", str(row))


def top_of(xu):
    x = int(xu / 16 * S)
    for y in range(S):
        if ink(x, y):
            return y
    return S
x0, fw = getattr(icons, "HAND_X0", 4.0), getattr(icons, "HAND_FW", 2.3)   # 손가락 자리(261111-12 부터 상수)
cx = [x0 + fw * (k + 0.5) for k in range(4)]
outer = (top_of(cx[0]), top_of(cx[3]))
inner = (top_of(cx[1]), top_of(cx[2]))
chk(max(inner) + 3 < min(outer), "C 가운데 손가락 둘이 바깥 둘보다 높다(손 윤곽)", "안 %s 바깥 %s" % (inner, outer))

# E — 엄지는 손바닥에서 벌어져 있다(261111-12, 사용자 지시 '엄지손가락을 … 손바닥에서 좀더 멀리 떨어뜨려야 손바닥처럼 보여'):
#   엄지 끝 아래 높이(16칸의 9.2)를 가로로 지나면 엄지 테와 손바닥 테 사이에 빈 틈이 16칸의 1 이상
gap_row = runs_row(int(9.2 / 16 * S))
gap = (gap_row[1][0] - (gap_row[0][0] + gap_row[0][1])) if len(gap_row) >= 2 else 0
chk(len(gap_row) >= 3 and gap >= S // 16, "E 엄지와 손바닥 사이 틈 ≥ 1/16(엄지가 벌어져 있다)", "%s 틈 %dpx" % (gap_row, gap))

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
