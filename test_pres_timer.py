# -*- coding: utf-8 -*-
"""260611-19: 발표시간 — 컨트롤러 상태/알람, 톤 엔진, 발표창 전이·표시, 설정 라운드트립."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QPainter

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.pres_timer import (PresTimerController, ToneEngine,
                                       merge_timer_cfg, DEFAULT_PRES_TIMER,
                                       PresTimerDialog)

# ===== A. 컨트롤러 =====
ctl = PresTimerController(None)
ctl.arm_standby()
chk(ctl.state == "STANDBY" and ctl.display() is None, "준비 상태 → 표시 없음")
ctl.start_running(now=0)
chk(ctl.state == "RUNNING" and ctl.display(now=0) == "05:00", "시작 → 05:00(기본 5분 다운)")
chk(ctl.display(now=65) == "03:55", "65초 경과 → 03:55", ctl.display(now=65))

# count up
cu = PresTimerController({"count_dir": "up", "duration_sec": 300})
cu.start_running(now=0)
chk(cu.display(now=65) == "01:05", "업카운트 65초 → 01:05", cu.display(now=65))

# resume(연속, 리셋 없음)
ctl.resume_running(now=65)
chk(ctl.display(now=70) == "03:50", "재개 후 연속(리셋 없음)", ctl.display(now=70))

# 종료 → OVERTIME + 종료 알람(기본 종소리 bell_end)
r = ctl.tick(now=305)
chk(r["state"] == "OVERTIME" and ("bell_end", 80) in r["fired"], "종료 → OVERTIME+종료알람(종소리)", str(r))
chk(ctl.display(now=305) == "00:05", "초과 → 00:05 증가", ctl.display(now=305))

# 사전 알람 시작~종료 반복 발화 시점 집합
cfg2 = {"duration_sec": 300, "count_dir": "down",
        "alarm": {"end": {"sound": "beep_mid", "vol": 80},
                  "pre": [{"start_sec": 60, "interval_sec": 20, "sound": "beep_low", "vol": 60}]}}
c2 = PresTimerController(cfg2)
c2.start_running(now=0)
pre_fires = 0; end_fires = 0
for t in range(0, 306):                      # 1초 간격 스윕
    for snd, vol in c2.tick(now=t)["fired"]:
        if snd == "beep_low": pre_fires += 1
        if snd == "beep_mid": end_fires += 1
chk(pre_fires == 3, "사전 알람 60/40/20초에 3회 발화", f"pre={pre_fires}")
chk(end_fires == 1, "종료 알람 1회", f"end={end_fires}")

# 이후 알람 시작 시 이전 알람 반복 중지(260611-21)
cfg3 = {"duration_sec": 300, "count_dir": "down",
        "alarm": {"end": {"sound": "bell_end", "vol": 80},
                  "pre": [
                      {"start_sec": 120, "interval_sec": 30, "sound": "bell_high", "vol": 70},
                      {"start_sec": 60, "interval_sec": 20, "sound": "bell", "vol": 70}]}}
c3 = PresTimerController(cfg3)
c3.start_running(now=0)
cnt = {"bell_high": 0, "bell": 0, "bell_end": 0}
for t in range(0, 306):
    for snd, vol in c3.tick(now=t)["fired"]:
        if snd in cnt:
            cnt[snd] += 1
# rowA(start120,간격30 → 120/90/60/30) 중 60초(rowB 시작) 이후는 중지 → 120/90 = 2회
chk(cnt["bell_high"] == 2, "이전 알람: 이후 알람 시작 후 반복 중지(120/90만)", str(cnt))
chk(cnt["bell"] == 3, "이후 알람: 60/40/20 정상 발화", str(cnt))
chk(cnt["bell_end"] == 1, "종료 알람 1회", str(cnt))

# 반복 횟수 제한(260611-22)
cfg4 = {"duration_sec": 300, "alarm": {"end": {"sound": "none", "vol": 0},
        "pre": [{"start_sec": 100, "interval_sec": 10, "sound": "bell", "vol": 70, "count": 3}]}}
c4 = PresTimerController(cfg4)
c4.start_running(now=0)
n4 = sum(len(c4.tick(now=t)["fired"]) for t in range(0, 306))
chk(n4 == 3, "반복 횟수 3 → 100/90/80초만 3회", f"n={n4}")

# 중지(pause)/재개(260611-22)
cp = PresTimerController({"duration_sec": 300})
cp.start_running(now=0)
chk(round(cp.elapsed(now=10)) == 10, "경과 10초")
cp.pause(now=10)
chk(cp.is_paused() and round(cp.elapsed(now=30)) == 10, "중지 → 시간 멈춤(10초 고정)", str(cp.elapsed(now=30)))
chk(cp.tick(now=30)["fired"] == [], "중지 중 알람 없음")
cp.resume(now=30)
chk(round(cp.elapsed(now=35)) == 15, "재개 → 연속(15초)", str(cp.elapsed(now=35)))

# ===== B. 톤 엔진 =====
te = ToneEngine()
ok_all = all(te._gen_wav(k) for k in ("beep_high", "beep_mid", "beep_low", "blip"))
chk(ok_all, "프리셋 WAV 생성")
chk(te.play("none", 50) is False, "'없음' 재생은 무음(False)")
# 첨부 종소리 리소스 해석
from viewer.resources_path import resource_path
chk(bool(resource_path("snd_bell_end.wav")) and bool(resource_path("snd_bell.wav")),
    "번들 종소리 WAV 리소스 존재")
chk("bell_end" in [k for _, k in ToneEngine.NAMES], "종소리 알람 옵션 등록")

# ===== C. 병합 =====
m = merge_timer_cfg({"duration_sec": 600})
chk(m["duration_sec"] == 600 and m["standby"]["lines"][0]["text"] == "준비",
    "부분 cfg 병합(누락 기본 보충)")

# ===== D. 발표창 전이·표시 =====
tmp = Path(tempfile.mkdtemp(prefix="polypdf_ptmr_"))
for nm in ("A.pdf", "B.pdf"):
    d = fitz.open(); d.new_page(width=400, height=600).insert_text((40, 80), nm)
    d.save(str(tmp / nm)); d.close()
from viewer.widgets.presentation import PresentationWindow
pres = PresentationWindow(str(tmp / "A.pdf"), 0, timer_cfg={"duration_sec": 300})
pres.resize(800, 600)
chk(hasattr(pres, "_tb_timer"), "발표 상단띠 시계 버튼 존재")

pres._tb_timer.setChecked(True)
chk(pres._timer_ctl.state == "STANDBY", "시계 ON → 준비(STANDBY)")
pres._next()
chk(pres._timer_ctl.state == "RUNNING", "준비에서 다음 → RUNNING(시작·리셋)")
chk(pres._page == 0, "준비에서 다음은 페이지 이동 안 함")

# forward 파일 전환 → 준비
pres._switch_file(str(tmp / "B.pdf"), to_end=False)
chk(pres._timer_ctl.state == "STANDBY", "앞으로 파일 전환 → 준비 표시")
# backward 파일 전환 → 연속(RUNNING/OVERTIME)
pres._switch_file(str(tmp / "A.pdf"), to_end=True)
chk(pres._timer_ctl.state in ("RUNNING", "OVERTIME"), "뒤로 파일 전환 → 연속 시계")

# 페인트 무오류(준비/시각 HUD)
canvas = QPixmap(800, 600); canvas.fill()
pnt = QPainter(canvas)
pres._timer_ctl.arm_standby(); pres._paint_timer(pnt)         # 준비 박스
pres._timer_ctl.start_running(now=0); pres._paint_timer(pnt)  # 시각 HUD
pnt.end()
chk(True, "타이머 페인트 무오류(준비/HUD)")

# 260611-28: 카운트 중 끄기 → 확인창. '계속'이면 유지, '끄기'면 OFF + 녹화중지 emit
from PyQt6.QtWidgets import QMessageBox
pres._timer_ctl.start_running(now=0)
_orig_exec = QMessageBox.exec
_orig_clicked = QMessageBox.clickedButton
QMessageBox.exec = lambda self: setattr(self, "_ck",
    next(b for b in self.buttons() if b.text() == "계속")) or 0
QMessageBox.clickedButton = lambda self: self._ck
pres._tb_timer.setChecked(False)
chk(pres._timer_ctl.state in ("RUNNING", "OVERTIME") and pres._tb_timer.isChecked(),
    "카운트 중 끄기 + '계속' → 시계 유지")
rec_stop = []
pres.recordStopRequested.connect(lambda: rec_stop.append(1))
QMessageBox.exec = lambda self: setattr(self, "_ck",
    next(b for b in self.buttons() if b.text() == "끄기")) or 0
pres._tb_timer.setChecked(False)
chk(pres._timer_ctl.state == "OFF", "카운트 중 끄기 + '끄기' → OFF")
chk(rec_stop == [1], "시계 종료 시 녹화 저장(recordStopRequested)")
QMessageBox.exec = _orig_exec
QMessageBox.clickedButton = _orig_clicked

# 타이머 시작시 녹화시작 기본값 = True
chk(DEFAULT_PRES_TIMER.get("rec_on_start") is True, "타이머 시작시 녹화시작 기본 체크")

# 발표시 녹화시작 — 준비내용이 아니라 그 이후(시간 시작)부터 (260611-24)
pres2 = PresentationWindow(str(tmp / "A.pdf"), 0, timer_cfg={"duration_sec": 300, "rec_on_start": True})
rec_emits = []
pres2.recordToggleRequested.connect(lambda: rec_emits.append(1))
pres2._tb_timer.setChecked(True)               # 준비(STANDBY)
chk(len(rec_emits) == 0, "준비내용 표시 시점엔 녹화 시작 안 함")
pres2._next()                                   # 준비 → RUNNING
chk(len(rec_emits) == 1, "준비 이후(시간 시작) 시 녹화 시작")

# ===== E. 설정 다이얼로그 라운드트립 =====
dlg = PresTimerDialog(None, {"duration_sec": 1800, "count_dir": "up",
                             "pos": "top-left", "margin": 40,
                             "rec_on_start": True})
got = dlg.get_config()
chk(got["duration_sec"] == 1800 and got["count_dir"] == "up"
    and got["pos"] == "top-left" and got["margin"] == 40 and got["rec_on_start"] is True,
    "설정 다이얼로그 get_config 라운드트립", str({k: got[k] for k in ("duration_sec","count_dir","pos","margin")}))

# 준비내용 그림 base64 라운드트립 + 설정 저장
from viewer.widgets.pres_timer import _pix_to_b64, b64_to_pix
qp = QPixmap(40, 20); qp.fill()
b64 = _pix_to_b64(qp)
chk(bool(b64) and not b64_to_pix(b64).isNull(), "준비 그림 base64 ↔ QPixmap 라운드트립")
dlg2 = PresTimerDialog(None, {"duration_sec": 300})
dlg2._standby_img = b64
chk(dlg2.get_config()["standby"]["image"] == b64, "준비 그림 설정 저장")

# 클립보드 붙여넣기 → 준비 배경 그림 (260611-28)
from PyQt6.QtGui import QImage
clip_img = QImage(30, 20, QImage.Format.Format_RGB32); clip_img.fill(0x3366cc)
app.clipboard().setImage(clip_img)
dlg3 = PresTimerDialog(None, {"duration_sec": 300})
dlg3._standby_img = ""
dlg3._paste_standby_image()
chk(bool(dlg3._standby_img) and not b64_to_pix(dlg3._standby_img).isNull(),
    "클립보드 이미지 → 준비 배경 그림 붙여넣기")

# 발표창: 시계 중지 버튼 + 숨김/음소거 상태
chk(hasattr(pres, "_tb_timer_stop"), "시계 중지 버튼 존재")
pres._tb_timer.setChecked(True); pres._next()          # RUNNING
pres._tb_timer_stop.setChecked(True)
chk(pres._timer_ctl.is_paused(), "중지 버튼 → 시계 멈춤")
pres._tb_timer_stop.setChecked(False)
chk(not pres._timer_ctl.is_paused(), "중지 해제 → 재개")
pres._timer_hidden = True
cv = QPixmap(800, 600); cv.fill(); pn2 = QPainter(cv); pres._paint_timer(pn2); pn2.end()
chk(True, "시계 숨김 시 페인트 무오류")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
