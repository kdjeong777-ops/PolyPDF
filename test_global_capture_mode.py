# -*- coding: utf-8 -*-
"""260611-14: 전역 캡처가 캡처 모드(전체/지정/사용자크기) 설정을 반영하는지 검증."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
import viewer.widgets.region_capture as rc

captured = {}
class FakeOverlay:
    def __init__(self, mode="region", fixed_size=None, copy_mode="visible", parent=None):
        captured["mode"] = mode; captured["fixed"] = fixed_size; captured["copy"] = copy_mode
    def grab(self):
        pm = QPixmap(60, 40); pm.fill(); return pm
rc.RegionCaptureOverlay = FakeOverlay

mw = MainWindow()
mw._foreground_is_self = lambda: False     # 전역 경로 강제
mw._cursor_in_viewer = lambda: False
mw._cap_copy = "visible"                   # 화질 선택(테스트 고정)

def fire(mode):
    captured.clear()
    mw._cap_mode = mode
    mw._last_gcap_ms = 0                    # 디바운스 초기화
    before = mw.shot_strip.list.count()
    mw._on_global_capture()
    app.processEvents()
    return before, mw.shot_strip.list.count()

# 1) 지정(region) 모드 → RegionCaptureOverlay(mode='region', visible) 사용 + 저장
b, a = fire("region")
chk(captured.get("mode") == "region" and captured.get("copy") == "visible",
    "전역 '지정' 모드 → region 오버레이(보이는 크기)", str(captured))
chk(a == b + 1, "지정 캡처 1장 저장")

# 2) 사용자 크기(user0) 모드 → fixed + 지정 크기
mw._cap_sizes = [{"name": "사용자1", "w": 321, "h": 222}]
b, a = fire("user0")
chk(captured.get("mode") == "fixed" and captured.get("fixed") == (321, 222),
    "전역 '사용자크기' 모드 → fixed 오버레이(지정 크기)", str(captured))
chk(a == b + 1, "사용자크기 캡처 1장 저장")

# 3) 전체(full) 모드 → 오버레이 미사용(화면 전체 grab 경로)
captured.clear()
mw._cap_mode = "full"; mw._last_gcap_ms = 0
mw._on_global_capture(); app.processEvents()
chk(captured == {}, "전역 '전체' 모드 → region 오버레이 미사용(화면 전체)", str(captured))

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
