# -*- coding: utf-8 -*-
"""260611-23: 녹화 파일명(<파일>_날짜_시각)·파일 전환 시 녹화 재시작·fileChanged 시그널."""
import os, sys, re, tempfile, json
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
from viewer.app import MainWindow
mw = MainWindow()

# 1) 파일명 규칙: <stem>_YYYYMMDD_HHMM_SS.mp4
p = mw._present_record_path("C:/x/강의자료_3장.pdf")
name = Path(p).name
chk(re.match(r"^강의자료_3장_\d{8}_\d{4}_\d{2}\.mp4$", name) is not None,
    "녹화 파일명 = <파일>_YYYYMMDD_HHMM_SS.mp4", name)

# 2) 녹화 중 아니면 전환 무동작(무오류)
mw._rec = None
mw._on_present_file_changed("C:/x/다음파일.pdf")
chk(True, "녹화 중 아님 → 전환 무동작")

# 3) 녹화 중이면 종료 후 새 파일로 재시작 (recorder 모킹)
events = []
class FakeRec:
    def __init__(self, name): self.name = name; self._on = True
    def is_recording(self): return self._on
    def is_paused(self): return False
    def stop(self): self._on = False; events.append(("stop", self.name))
    def start(self): events.append(("start", self.name)); return True, "ok"
old = FakeRec("old")
mw._rec = old
mw._make_recorder = lambda out: (FakeRec(Path(out).name), "ffmpeg")  # ff 존재 가장
mw._on_present_file_changed("C:/x/새강의.pdf")
chk(("stop", "old") in events, "전환 시 이전 녹화 종료")
started = [e for e in events if e[0] == "start"]
chk(len(started) == 1 and re.match(r"^새강의_\d{8}_\d{4}_\d{2}\.mp4$", started[0][1]) is not None,
    "전환 시 새 파일명으로 녹화 시작", str(started))

# 4) 발표창 fileChanged 시그널이 _switch_file 에서 발생
tmp = Path(tempfile.mkdtemp(prefix="polypdf_rec_"))
for nm in ("A.pdf", "B.pdf"):
    d = fitz.open(); d.new_page(width=400, height=600).insert_text((40, 80), nm)
    d.save(str(tmp / nm)); d.close()
from viewer.widgets.presentation import PresentationWindow
pres = PresentationWindow(str(tmp / "A.pdf"), 0)
got = []
pres.fileChanged.connect(lambda pth: got.append(pth))
pres._switch_file(str(tmp / "B.pdf"), to_end=False)
chk(got and Path(got[-1]).name == "B.pdf", "파일 전환 시 fileChanged 발생", str(got))

# 5) ffmpeg 동봉 자료 존재(개발 트리)
chk(Path("ffmpeg.exe").exists(), "프로젝트에 ffmpeg.exe 존재(빌드 동봉 대상)")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
