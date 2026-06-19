# -*- coding: utf-8 -*-
"""260611-25: 발표 보기 설정을 전체화면 옵션으로 이동·본화면 설정에서 제거 / 녹화 테스트 게이트."""
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

app = QApplication.instance() or QApplication(sys.argv)

# 1) 본화면 설정 다이얼로그에서 발표 보기 위젯 제거 + result_prefs 에 키 없음
from viewer.widgets.settings_dialog import SettingsDialog
sd = SettingsDialog({"presentation_split": True, "presentation_overlap_pct": 12,
                     "presentation_topbar_h": 70})
chk(not hasattr(sd, "chk_present_split"), "본화면 설정에서 '상하 2분할' 위젯 제거")
chk(not hasattr(sd, "spin_overlap"), "본화면 설정에서 '겹침%' 위젯 제거")
rp = sd.result_prefs()
chk("presentation_split" not in rp and "presentation_overlap_pct" not in rp
    and "presentation_topbar_h" not in rp, "result_prefs 에 발표 보기 키 없음")
chk(hasattr(sd, "focus_recording"), "녹화 설정 포커스 메서드 존재")

# 2) _apply_prefs 가 발표 보기 키를 기존값에서 보존
from viewer.app import MainWindow
mw = MainWindow()
mw._prefs["presentation_overlap_pct"] = 25
mw._prefs["presentation_topbar_h"] = 88
mw._prefs["presentation_split"] = True
mw._apply_prefs(sd.result_prefs())     # 발표 키 미포함 → 보존되어야
chk(mw._prefs["presentation_overlap_pct"] == 25
    and mw._prefs["presentation_topbar_h"] == 88
    and mw._prefs["presentation_split"] is True, "발표 보기 설정값 보존",
    str([mw._prefs[k] for k in ("presentation_overlap_pct","presentation_topbar_h","presentation_split")]))

# 3) recording_test_ok 영속(_apply_prefs 보존)
mw._prefs["recording_test_ok"] = True
mw._apply_prefs(sd.result_prefs())
chk(mw._prefs.get("recording_test_ok") is True, "recording_test_ok 보존")

# 4) 발표창 라이브 setter
tmp = Path(tempfile.mkdtemp(prefix="polypdf_opt_"))
d = fitz.open(); d.new_page(width=400, height=600).insert_text((40, 80), "p")
d.save(str(tmp / "A.pdf")); d.close()
from viewer.widgets.presentation import PresentationWindow
pres = PresentationWindow(str(tmp / "A.pdf"), 0)
pres.resize(800, 600)
chk(hasattr(pres, "viewSettingsRequested"), "발표창 viewSettingsRequested 시그널 존재")
pres.set_overlap_pct(30)
chk(abs(pres._overlap_frac - 0.30) < 1e-6, "겹침% 라이브 반영", str(pres._overlap_frac))
pres.set_topbar_height(120)
chk(pres._topbar_h == 120, "상단 띠 높이 라이브 반영", str(pres._topbar_h))

# 5) 녹화 게이트: 합격 결과 없으면 '녹화없이 진행' 선택 시 녹화 안 함
mw._prefs["recording_test_ok"] = False
mw._rec = None
mw._present = None
mw._ask_rec_test_gate = lambda: "noproceed"
mw._on_record_toggle()
chk(getattr(mw, "_rec", None) is None, "테스트 미합격 + 녹화없이 진행 → 녹화 안 함")

# 설정진행 선택 시 녹화 설정 호출
opened = {"n": 0}
mw._ask_rec_test_gate = lambda: "settings"
mw._open_recording_settings = lambda: opened.__setitem__("n", opened["n"] + 1)
mw._on_record_toggle()
chk(opened["n"] == 1 and getattr(mw, "_rec", None) is None,
    "테스트 미합격 + 설정진행 → 녹화 설정 열기(녹화 안 함)")

# 합격 결과 있으면 게이트 없이 진행(make_recorder 모킹)
mw._prefs["recording_test_ok"] = True
gate_called = {"n": 0}
mw._ask_rec_test_gate = lambda: gate_called.__setitem__("n", gate_called["n"] + 1) or "cancel"
class FakeRec:
    def __init__(s): s._on = False
    def is_recording(s): return s._on
    def is_paused(s): return False
    def start(s): s._on = True; return True, "ok"
mw._make_recorder = lambda out: (FakeRec(), "ffmpeg")
mw._on_record_toggle()
chk(gate_called["n"] == 0 and getattr(mw, "_rec", None) is not None,
    "테스트 합격 → 게이트 없이 녹화 시작")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
