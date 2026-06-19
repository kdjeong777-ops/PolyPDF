# -*- coding: utf-8 -*-
"""260606-17: 캡쳐 드롭다운 모드/복사크기/사용자크기, 클립보드 버튼, 썸네일 번호."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ok = True
def check(n, c, e=""):
    global ok; print(("  OK  " if c else " FAIL ") + n + (f"  {e}" if e else "")); ok = ok and bool(c)

from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow()

# 모드/라벨 (설정 영속성 때문에 명시적으로 full 설정 후 확인)
mw._set_cap_mode("full")
check("캡쳐모드 full", mw._cap_mode == "full")
check("드롭다운 라벨 전체", "전체" in mw._cap_menus[0].text())
mw._set_cap_mode("region")
check("지정 모드 라벨", "지정" in mw._cap_menus[0].text())
mw._cap_sizes[0]["name"] = "와이드"
mw._set_cap_mode("user0")
check("사용자크기 라벨=이름", "와이드" in mw._cap_menus[0].text(), mw._cap_menus[0].text())
mw._set_cap_copy("original")
check("복사크기 original 저장", mw._cap_copy == "original")
# 양쪽 창 드롭다운 동기화
check("드롭다운 2개(양쪽 창)", len(mw._cap_menus) == 2)
check("양쪽 라벨 동일", mw._cap_menus[0].text() == mw._cap_menus[1].text())

# 사용자 크기 다이얼로그
from viewer.widgets.capture_settings import CaptureSizesDialog
d = CaptureSizesDialog([{"name": "a", "w": 111, "h": 222}])
res = d.result_sizes()
check("사용자크기 5개", len(res) == 5)
check("사용자크기 값 보존", res[0]["name"] == "a" and res[0]["w"] == 111 and res[0]["h"] == 222)

# 클립보드 버튼
check("클립보드 저장 버튼 존재", hasattr(mw, "btn_clip"))
check("클립보드 버튼 툴팁", "Win+v" in mw.btn_clip.toolTip())
check("_on_clipboard_save 메서드", callable(getattr(mw, "_on_clipboard_save", None)))

# 캡쳐 디스패치/렌더 메서드
for m in ("_do_capture", "_capture_pages", "_capture_region", "_render_page_pixmap"):
    check(f"{m} 존재", callable(getattr(mw, m, None)))

# region overlay 임포트
from viewer.widgets.region_capture import RegionCaptureOverlay
check("RegionCaptureOverlay 임포트", RegionCaptureOverlay is not None)

# 썸네일 번호: 2개 추가 → 텍스트 1,2
from viewer.resources_path import resource_path
mw.shot_strip.add_item(resource_path("icon.png"), kind="image", label="a", prepend=False)
mw.shot_strip.add_item(resource_path("icon.png"), kind="image", label="b", page_index=1, prepend=False)
texts = [mw.shot_strip.list.item(i).text() for i in range(mw.shot_strip.list.count())]
check("썸네일 번호 1..N", texts == ["1", "2"], f"{texts}")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
