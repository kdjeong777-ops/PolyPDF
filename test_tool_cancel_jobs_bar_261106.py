# -*- coding: utf-8 -*-
"""261106-19: 상태 표시줄 진행 막대 = 작업 창에 오른 작업이 있을 때만 (응답성 SOT §4.6 '진행 막대').

사용자 보고: "하단에 파란 바가 있어 확인했더니, 진행없다고" — 진행 막대가 돌고 있는데 눌러 연 작업 창은 '진행 중인 작업이
없습니다'. 원인: `job_add` 는 막대를 켜지만 `job_done` 은 끄지 않아(부른 쪽이 따로 꺼야 했다) zip 풀기(사진 모드)·일괄 OCR 뒤
책갈피 만들기처럼 끄지 않는 작업이 끝나면 막대가 남았고, 파일 하나 색인·단어장 일부는 작업 등록 없이 막대를 켰다.

A. 소스 — `self.progress` 의 보임(setVisible/show/hide)을 jobs_controller 밖에서 바꾸지 않는다
B. 실제 흐름 — zip 풀기(사진 모드 길 `_zip_start`)·폴더 열기·파일 열기 동안 줄곧 '막대가 보임 = 작업이 있음', 끝나면 막대가 없다
"""
import os, sys, time, re, shutil, tempfile, zipfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tool_cancel_jobs_bar_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "진행 막대")       # 마스터 §14.7.2 의 6
fails = []
ROOT = Path(__file__).resolve().parent


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def wait(cond, sec=15.0):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# ── A. 소스 ───────────────────────────────────────────────────────────
pat = re.compile(r"\bself\.progress\.(setVisible|show|hide)\(")
bad = []
for p in sorted((ROOT / "viewer").rglob("*.py")):
    if p.name == "jobs_controller.py":
        continue
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if pat.search(ln.split("#", 1)[0]):
            bad.append(f"{p.relative_to(ROOT)}:{i}")
chk(not bad, "A 진행 막대의 보임은 jobs_controller 만 바꾼다", str(bad[:12]))

# ── B. 실제 흐름 ──────────────────────────────────────────────────────
import test_fixtures as _fx
tmp = Path(tempfile.mkdtemp(prefix="jobsbar261106_"))
try:
    folder = tmp / "f"
    folder.mkdir()
    for i in range(6):
        shutil.copy(Path(_fx.text_pdf()), folder / f"d{i}.pdf")
    zp = tmp / "pics.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for i in range(40):
            z.writestr(f"p{i:02d}.txt", "x" * 20000)

    from viewer.app import MainWindow
    mw = MainWindow()
    mw._skip_save_on_close = True
    mw.resize(1200, 800)
    mw.show()
    wait(lambda: False, 0.6)

    bad_samples = []

    def sample():
        vis = mw.progress.isVisible()
        if vis != bool(mw._jobs):
            bad_samples.append((vis, sorted(mw._jobs)))
    t = QTimer()
    t.timeout.connect(sample)
    t.start(15)

    # 폴더 열기(폴더 색인 — 작업 창 '인덱싱')
    mw.open_folder(folder)
    wait(lambda: not mw._index_workers and not mw._jobs, 30)
    # 파일 열기(파일 하나 색인 — 짧아 작업 창에 없음 → 막대도 없다)
    mw.open_pdf(folder / "d0.pdf")
    wait(lambda: not mw._index_workers and not mw._jobs, 30)
    wait(lambda: False, 0.5)
    n_before_zip = len(bad_samples)
    # zip 풀기(사진 모드 길)
    mw._zip_start(str(zp), str(tmp / "out"))
    ok = wait(lambda: not any(k.startswith("unzip") for k in mw._jobs), 30)
    wait(lambda: False, 0.4)
    t.stop()
    chk(ok and (tmp / "out").exists(), "B zip 풀기가 끝났다", str(list(mw._jobs)))
    chk(not mw.progress.isVisible(), "B zip 풀기가 끝나면 진행 막대가 없다(작업 창도 비었다)")
    chk(not bad_samples, "B 줄곧 '막대가 보임 = 작업이 있음'(폴더 열기·파일 열기·zip 풀기)",
        f"어긋난 표본 {len(bad_samples)}개(zip 전 {n_before_zip}) 예 {bad_samples[:3]}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL PASS" if not fails else f"FAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)
