# -*- coding: utf-8 -*-
"""261108-20 덧붙임 2: 겹침 감시가 잰 앱 자신의 자손을 '다른 무거운 프로세스' 로 세지 않는다 — 릴리스 SOT §4.3 의 8.

beta.6 설치·beta.8 빌드 1856·설치 2048 의 T5 가 모두 '겹침 — PolyPDF.exe←31416(15724) 0.76코어' 로 보류됐다. 사용자는 그때
다른 작업을 하지 않았다 — 31416 은 잰 앱, 15724 는 그 색인 자식. 점검은 대상을 닫은 **뒤** 하는데, 잰 앱이 목록에서 사라지면
`Watch.root`(release_test) 에서 내려가는 나무가 끊겨, 목록에 남은 색인 자식을 남으로 셌다.
  O  `Watch.check(exclude=[잰 앱, 자손])` 이면 잰 앱의 (끊긴) 자손과 그 아래 손자까지 빼고, 정말 남인 것은 그대로 센다
  R  `run_suite` 가 대상마다 측정 기록의 `app_pid`·`descendant_pids` 를 `check` 에 넘긴다
"""
import sys, tempfile, time
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
import overlap                           # noqa: E402
import release_test as R                 # noqa: E402
import probe_installed as probe          # noqa: E402

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


# O — release_test(20) 가 띄운 잰 앱 31416 은 닫혀 목록에 없고, 그 색인 자식 15724·손자 15800 과 남(사용자 창 900)이 남았다
ROOT = 20
PS1 = [(20, 10, "python.exe"), (15724, 31416, "PolyPDF.exe"), (15800, 15724, "PolyPDF.exe"), (900, 4, "PolyPDF.exe")]
CPU = {15724: 228.0, 15800: 30.0, 900: 0.0}
saved = (overlap.procs, overlap._cpu_s, overlap.system_busy_pct)
overlap.procs = lambda: list(PS1)
overlap._cpu_s = lambda pid: CPU.get(pid, 0.0)
overlap.system_busy_pct = lambda sec=1.0: 10.0
try:
    w = overlap.Watch(root=ROOT)
    w._last = (time.time() - 10.0, {})                    # 구간 시작 — 셋 다 그 뒤에 떴다(쓴 CPU 전부를 센다)
    try:
        w.check("T5_std", exclude=[31416, 15724])
        ok = not w.overlapped
    except TypeError as e:                 # 수정 전 — exclude 를 받지 않는다
        ok = False
        print("  (수정 전:", e, ")")
    chk(ok, "O 잰 앱의 끊긴 자손·손자는 겹침으로 세지 않는다", w.events)
    w2 = overlap.Watch(root=ROOT)
    w2._last = (time.time() - 10.0, {})
    CPU[900] = 200.0                       # 정말 남인 프로세스가 바쁘면
    try:
        w2.check("T5_std", exclude=[31416, 15724])
    except TypeError:
        w2.check("T5_std")
    chk(w2.overlapped and "(900)" in w2.events[0][1] and "(15724)" not in w2.events[0][1],
        "O 남인 프로세스는 그대로 센다(잰 앱 자손은 빠짐)", w2.events)
finally:
    overlap.procs, overlap._cpu_s, overlap.system_busy_pct = saved

# R — run_suite 가 측정 기록의 pid 들을 check 에 넘기는가
tmp = Path(tempfile.mkdtemp(prefix="ovtree261108_"))
target = tmp / "a.pdf"; target.write_bytes(b"%PDF-1.4\n")
seen = {}


class FakeWatch:
    def check(self, label, exclude=()):
        seen[label] = set(x for x in exclude if x)
        return False


names = ("seed", "backup", "restore", "clear_index", "drop", "run")
saved_p = {n: getattr(probe, n) for n in names}
saved_l = R.load_suite
try:
    probe.seed = lambda: None
    probe.backup = lambda dst: Path(dst).mkdir(parents=True, exist_ok=True)
    probe.restore = lambda src: None
    probe.clear_index = lambda: None
    probe.drop = lambda: None
    probe.run = lambda name, tgt, sec, out: {"name": name, "hangs": [], "max_hang_sec": 0, "exit": None, "close_sec": 0.5,
                                             "app_pid": 31416, "descendant_pids": [15724]}
    R.load_suite = lambda only: (tmp, [{"name": "T5_std", "target": "a.pdf", "seconds": 1}])
    out = tmp / "out"; out.mkdir()
    R.run_suite(Path("PolyPDF.exe"), out, None, {"fail": [], "runs": []}, FakeWatch())
finally:
    for n, f in saved_p.items():
        setattr(probe, n, f)
    R.load_suite = saved_l
chk(seen.get("T5_std") == {31416, 15724}, "R run_suite 가 잰 앱·자손 pid 를 겹침 점검에 넘긴다", seen)

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("=== FAILURE (%d) ===" % len(fails))
    sys.exit(1)
print("ALL PASS")
