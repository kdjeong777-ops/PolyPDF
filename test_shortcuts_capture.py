# -*- coding: utf-8 -*-
"""260611-3: 단축키 그룹화/신설 + 전역 캡처 핫키 파싱 검증."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

# 1) 핫키 파서
from viewer.global_hotkey import (parse_sequence, MOD_CONTROL, MOD_SHIFT, MOD_ALT)
r = parse_sequence("Ctrl+Shift+S")
chk(r is not None and (r[0] & MOD_CONTROL) and (r[0] & MOD_SHIFT) and r[1] == ord("S"),
    "Ctrl+Shift+S 파싱", str(r))
r2 = parse_sequence("Alt+F4")
chk(r2 is not None and (r2[0] & MOD_ALT) and r2[1] == 0x73, "Alt+F4 파싱", str(r2))
chk(parse_sequence("") is None, "빈 시퀀스 None")
chk(parse_sequence("Ctrl+`") is not None, "Ctrl+` 파싱")

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(900, 700)

# 2) 단축키 레지스트리 — 3튜플(라벨,키,그룹) + 선긋기/발표 신설
defs = mw._sc_defs
chk(all(len(v) == 3 for v in defs.values()), "모든 단축키 (라벨,키,그룹) 3튜플")
groups = []
for _id, (_l, _k, g) in defs.items():
    if g not in groups: groups.append(g)
chk("선긋기(편집모드)" in groups and "캡처·저장" in groups and "파일" in groups,
    "그룹 존재(파일/캡처·저장/선긋기)", str(groups))
for need in ["draw_pen_1", "draw_pen_5", "draw_mode", "draw_erase_thin",
             "draw_erase_thick", "draw_clear", "present"]:
    chk(need in defs, f"단축키 항목 '{need}' 신설")
chk(defs["draw_pen_1"][1] == "Ctrl+1" and defs["draw_pen_5"][1] == "Ctrl+5",
    "펜 단축키 기본 Ctrl+1~5")
chk(defs["toggle_split"][1] == "Ctrl+Shift+2", "2단보기 키 충돌회피(Ctrl+Shift+2)")

# 3) 단축키 다이얼로그 그룹 렌더 + 캡처 전역 체크박스
from viewer.widgets.shortcuts_dialog import ShortcutsDialog
dlg = ShortcutsDialog(defs, {}, mw, capture_global=True)
chk(dlg.result_capture_global() is True, "다이얼로그 전역캡처 체크 반영")
chk(len(dlg._edits) == len(defs), "다이얼로그 항목 수 = 레지스트리 수")

# 4) 공유 펜 단축키 → 발표에 전달되는 5키
pk = mw._draw_pen_keys()
chk(len(pk) == 5 and pk[0] == "Ctrl+1", "발표 전달용 펜 단축키 5개", str(pk))

# 5) 전역 캡처 토글 등록/해제 (예외 없이)
mw._prefs["capture_global"] = True
mw._refresh_global_capture_hotkey()
chk(getattr(mw, "_global_hotkey", None) is not None, "전역 핫키 객체 생성")
mw._prefs["capture_global"] = False
mw._refresh_global_capture_hotkey()
chk(True, "전역 핫키 해제 무예외")

# 6) 선긋기 단축키 핸들러(편집모드 아닐 때 무동작·예외 없음)
mw._draw_sc_pen(0); mw._draw_sc_mode(); mw._draw_sc_erase(1); mw._draw_sc_clear()
chk(True, "선긋기 단축키 핸들러 무예외(비편집)")

# 7) 전역 캡처 디바운스 — 빠른 2연속은 1회만(스크린샷 2개 생기는 문제 방지)
calls = {"n": 0}
mw._do_capture = lambda v: calls.__setitem__("n", calls["n"] + 1)
mw._foreground_is_self = lambda: True
mw._cursor_in_viewer = lambda: True
mw._on_global_capture(); mw._on_global_capture()
chk(calls["n"] == 1, "전역 캡처 빠른 2연속 → 1회만(중복 방지)", f"n={calls['n']}")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
