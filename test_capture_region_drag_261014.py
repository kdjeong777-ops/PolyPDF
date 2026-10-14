# -*- coding: utf-8 -*-
"""261014-18: 영역 캡처 — 끌어 고르기 (스크린샷 SOT §3.1, 개선 로드맵 P2-7).

A. 누른 채 끌어 놓으면 그 사각형이 영역이 되고 고치기 단계로(종전: 놓아도 다음 클릭을 기다렸다)
B. 클릭 두 번 방식도 그대로(덜 끌었으면 클릭)
C. 오른쪽 클릭 — 고르는 중이면 취소, 고치기 단계면 다시 고르기
D. 화살표 1 px · Shift 10 px 옮기기, Ctrl+화살표 크기
E. Enter 로 캡처하면 `region_out`, 다음 번 시작 단계에서 Enter = 지난 영역(같은 화면일 때)
F. 이름 — 캡처 모드 메뉴·단추가 '영역 캡처'
G. 안내 줄은 단계마다 지금 되는 조작
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QStandardPaths, Qt, QPoint, QRect
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from viewer.widgets.region_capture import RegionCaptureOverlay

L, R = Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton


def overlay(**k):
    ov = RegionCaptureOverlay(mode=k.pop("mode", "region"), **k)
    ov.resize(800, 600)
    ov.show(); app.processEvents()
    return ov


# ── A. 끌어 놓기 ─────────────────────────────────────────────────
ov = overlay()
h0 = ov.hint()
QTest.mousePress(ov, L, pos=QPoint(100, 100))
QTest.mouseMove(ov, QPoint(200, 180))
h1 = ov.hint()
QTest.mouseMove(ov, QPoint(300, 250))
QTest.mouseRelease(ov, L, pos=QPoint(300, 250))
chk(ov._phase == "edit" and ov._rect.normalized() == QRect(QPoint(100, 100), QPoint(300, 250)),
    "A 끌어 놓으면 영역이 정해지고 고치기 단계로", f"{ov._phase} {ov._rect}")
h2 = ov.hint()
chk(h0 != h1 != h2 and "끌어서" in h0 and "Enter" in h2, "G 안내 줄이 단계마다 바뀐다", f"{h0} | {h1} | {h2}")

# ── D. 화살표 ───────────────────────────────────────────────────
r0 = ov._rect.normalized()
QTest.keyClick(ov, Qt.Key.Key_Right)
QTest.keyClick(ov, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
r1 = ov._rect.normalized()
QTest.keyClick(ov, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
r2 = ov._rect.normalized()
chk(r1.topLeft() == r0.topLeft() + QPoint(1, 10) and r1.size() == r0.size() and r2.width() == r1.width() + 1,
    "D 화살표 1px·Shift 10px 옮기기, Ctrl 크기", f"{r0} {r1} {r2}")

# ── C. 오른쪽 클릭(고치기 → 다시 고르기) ───────────────────────────
QTest.mouseClick(ov, R, pos=QPoint(10, 10))
chk(ov._phase == "place" and not ov._rect.isValid() and ov.isVisible(), "C 고치기 단계 오른쪽 클릭 = 다시 고르기")

# ── E. 다시 끌어 Enter → region_out ───────────────────────────────
QTest.mousePress(ov, L, pos=QPoint(50, 60))
QTest.mouseMove(ov, QPoint(250, 210))
QTest.mouseRelease(ov, L, pos=QPoint(250, 210))
QTest.keyClick(ov, Qt.Key.Key_Return)
out = ov.region_out
chk(out is not None and out[:4] == [50, 60, 201, 151] and ov._result is not None,
    "E Enter 로 캡처 — 지난 영역을 돌려준다", str(out))

ov2 = overlay(last_region=out)
QTest.keyClick(ov2, Qt.Key.Key_Return)
chk(ov2._phase == "edit" and ov2._rect.normalized() == QRect(50, 60, 201, 151), "E 시작 단계 Enter = 지난 영역",
    f"{ov2._phase} {ov2._rect}")
ov2.close()
ov3 = overlay(last_region=[50, 60, 201, 151, "다른 화면"])
QTest.keyClick(ov3, Qt.Key.Key_Return)
chk(ov3._phase == "place", "E 다른 화면의 지난 영역은 쓰지 않는다")
# 고르는 중 오른쪽 클릭 = 취소
QTest.mouseClick(ov3, R, pos=QPoint(10, 10))
chk(not ov3.isVisible() and ov3._result is None, "C 고르는 중 오른쪽 클릭 = 취소")

# ── B. 클릭 두 번 ───────────────────────────────────────────────
ov4 = overlay()
QTest.mouseClick(ov4, L, pos=QPoint(40, 40))
chk(ov4._phase == "sizing", "B 덜 끈 클릭은 첫 모서리(다음 클릭을 기다린다)", ov4._phase)
QTest.mouseMove(ov4, QPoint(140, 120))
QTest.mouseClick(ov4, L, pos=QPoint(140, 120))
chk(ov4._phase == "edit" and ov4._rect.normalized() == QRect(QPoint(40, 40), QPoint(140, 120)), "B 두 번째 클릭이 맞은편 모서리")
ov4.close()

# ── F. 이름 ────────────────────────────────────────────────────
from viewer.app import MainWindow
mw = MainWindow(); mw.show(); app.processEvents()
mw._cap_mode = "region"
lab = mw._capture_mode_label()
from PyQt6.QtWidgets import QToolButton
dd = QToolButton()
mw._rebuild_capture_menu(dd)
names = [a.text() for a in dd.menu().actions()] if dd.menu() else []
chk(lab == "영역 캡처" and "영역 캡처" in names and "지정" not in names, "F 캡처 모드 이름 '영역 캡처'", f"{lab} {names}")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
