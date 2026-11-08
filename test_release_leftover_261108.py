# -*- coding: utf-8 -*-
"""261108-20: 측정 도구가 닫은 뒤 남은 앱 프로세스를 놓치지 않고, 그것 때문에 측정 전체가 죽지 않는다 — 릴리스 SOT §4.3·검사 작성 SOT.

beta.8 설치 시험 T5: 앱을 닫은 뒤 무엇이 시험 프로필의 index.db 를 쥐어 `restore_dir → drop → rmtree` 가 WinError 32 로 죽었다
(요약 없이 끝남). 같은 때 `helper_left` 는 0 — `_children` 이 **직계 자식만**, 그것도 표본 때 본 것만 셌다.
  D  `_descendants` 가 손자까지, 가운데 프로세스가 끝난 뒤에도(부모 pid 기록으로) 찾는다
  W  `drop` 은 이 측정이 띄운 프로세스가 파일을 쥐고 있으면 기다렸다 지운다 — 종전은 바로 PermissionError
  K  끝내 안 끝나는 남은 프로세스는 끝내고 지운다(`DROP_WAIT_S`)
  S  `run_suite` 는 시험 프로필을 못 지워도 예외 대신 실패로 적고 요약까지 간다
실제 시험 프로필(`PolyPDF-test`)은 건드리지 않는다 — `probe.CFG` 를 임시 폴더로 바꾼다.
"""
import os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
import probe_installed as probe          # noqa: E402
import release_test                      # noqa: E402

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


PY = getattr(sys, "_base_executable", None) or sys.executable      # venv 의 python.exe 는 진짜 파이썬을 또 띄우는 껍데기다
NAMES = (Path(PY).name.lower(),)
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
tmp = Path(tempfile.mkdtemp(prefix="leftover261108_"))
probe.CFG = tmp / "PolyPDF-fake"                                     # 실제 시험 프로필 대신

# D — 가운데 프로세스가 손자를 띄우고 먼저 끝난다
pidfile = tmp / "grand.pid"
mid = subprocess.Popen([PY, "-c",
                        "import subprocess,sys;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],creationflags=%d);"
                        "open(r'%s','w').write(str(p.pid));import time;time.sleep(1.5)" % (NOWIN, pidfile)], creationflags=NOWIN)
t = time.time()
while not (pidfile.exists() and pidfile.read_text()) and time.time() - t < 20:
    time.sleep(0.1)
grand = int(pidfile.read_text())
desc = getattr(probe, "_descendants", None)
if desc is None:                                                     # 수정 전 도구 — 직계만 보는 `_children` 뿐
    chk(False, "D 모든 대의 자손을 찾는 `_descendants` 가 있다")
else:
    seen = desc(os.getpid(), names=NAMES)                            # 표본 때 — 가운데가 살아 있다
    chk(grand in seen and mid.pid in seen, "D 손자까지 찾는다(종전 `_children` 은 직계만)", (grand, mid.pid, sorted(seen)))
    mid.wait(20)
    found = desc(os.getpid(), names=NAMES, known=seen)               # 닫은 뒤 — 가운데는 끝났다
    chk(grand in found, "D 가운데 프로세스가 끝난 뒤에도 앞서 본 자손에서 찾는다", (grand, sorted(found)))
mid.wait(20)
subprocess.run(["taskkill", "/F", "/PID", str(grand)], capture_output=True)

# W — 남은 프로세스가 2초 동안 파일을 쥐었다 놓는다
probe.CFG.mkdir(parents=True, exist_ok=True)
(probe.CFG / "index.db").write_bytes(b"x" * 100)
holder = subprocess.Popen([PY, "-c", "import time;f=open(r'%s','rb');time.sleep(2)" % (probe.CFG / "index.db")],
                          creationflags=NOWIN)
time.sleep(0.8)
if hasattr(probe, "SPAWNED"):
    probe.SPAWNED.clear(); probe.SPAWNED.add(holder.pid)
err = None
try:
    probe.drop()
except Exception as e:
    err = e
chk(err is None and not probe.CFG.exists(), "W 남은 프로세스가 놓기를 기다렸다 지운다", repr(err))

# K — 끝내 안 끝나는 남은 프로세스
probe.CFG.mkdir(parents=True, exist_ok=True)
(probe.CFG / "index.db").write_bytes(b"x" * 100)
stuck = subprocess.Popen([PY, "-c", "import time;f=open(r'%s','rb');time.sleep(60)" % (probe.CFG / "index.db")],
                         creationflags=NOWIN)
time.sleep(0.8)
if hasattr(probe, "SPAWNED"):
    probe.SPAWNED.clear(); probe.SPAWNED.add(stuck.pid)
old_wait = getattr(probe, "DROP_WAIT_S", None)
probe.DROP_WAIT_S = 1
err = None
try:
    probe.drop()
except Exception as e:
    err = e
chk(err is None and not probe.CFG.exists() and stuck.poll() is not None, "K 안 끝나는 남은 프로세스는 끝내고 지운다", repr(err))
if stuck.poll() is None:
    stuck.kill(); stuck.wait(5)
shutil.rmtree(probe.CFG, ignore_errors=True)
if old_wait is not None:
    probe.DROP_WAIT_S = old_wait

# S — 시험 프로필을 못 지워도 run_suite 가 예외로 죽지 않는다
saved = {n: getattr(probe, n) for n in ("seed", "backup", "drop")}
saved_load = release_test.load_suite
out = tmp / "out"
out.mkdir()


def _boom():
    raise PermissionError(32, "다른 프로세스가 사용 중", str(probe.CFG / "index.db"))


probe.seed = lambda: None
probe.backup = lambda dst: Path(dst).mkdir(parents=True, exist_ok=True)
probe.drop = _boom
release_test.load_suite = lambda only: (tmp, [])
rec = {"fail": [], "runs": []}
err = None
try:
    release_test.run_suite(Path("PolyPDF.exe"), out, None, rec)
except Exception as e:
    err = e
finally:
    for n, f in saved.items():
        setattr(probe, n, f)
    release_test.load_suite = saved_load
chk(err is None and any("지우지 못함" in f for f in rec["fail"]), "S 시험 프로필을 못 지우면 실패로 적고 이어 간다",
    (repr(err), rec["fail"]))
chk((out / release_test.PENDING).exists(), "S 되돌리기 표식은 남는다(다음 시험이 되돌리기를 요구)")

shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("=== FAILURE (%d) ===" % len(fails))
    sys.exit(1)
print("ALL PASS")
