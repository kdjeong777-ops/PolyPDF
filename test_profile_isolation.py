# -*- coding: utf-8 -*-
"""261009-19: 시험 프로필(`POLYPDF_PROFILE`)은 사용자 실제 설정과 갈린다 — 마스터 §14.2.1·§14.5 U19.

시험 도구가 실제 설정 폴더를 백업·복원·`--clear-index` 하다 사용자 색인(index.db)을 지웠다(Claude 앱 셸은 그 폴더의
복사본을 보는데 삭제는 실제 폴더에 닿았다). 이제 시험 실행은 `POLYPDF_PROFILE=test` 로 띄워 `LocalTools\\PolyPDF-test` 를 쓴다.

A. 실제 `main.py` 를 프로필을 주고 띄우면 창 기록·설정이 `PolyPDF-<프로필>` 폴더에 생기고, 창 제목은 그대로
B. 같은 실행 동안 실제 폴더(`PolyPDF`)의 창 기록(instances)에 이 실행이 적히지 않는다
C. 다른 창에 PDF 를 넘기는 통로(open_gather) 이름도 프로필마다 다르다 — 시험 실행이 사용자 창에 파일을 넘기지 않게
D. 프로필 이름은 영문·숫자·`-_` 만(경로 조작 방지)
"""
import os, sys, time, subprocess, shutil
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from pathlib import Path
prof = "ptest%d" % os.getpid()
base = Path(os.environ["APPDATA"]) / "LocalTools"
pdir, real = base / ("PolyPDF-" + prof), base / "PolyPDF"
before = set(os.listdir(real / "instances")) if (real / "instances").exists() else set()
env = dict(os.environ, POLYPDF_PROFILE=prof, QT_QPA_PLATFORM="offscreen")
env.pop("POLYPDF_OPEN_GATHER_NAME", None)
p = subprocess.Popen([sys.executable, os.path.join(HERE, "main.py")], env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    t0 = time.time()
    while time.time() - t0 < 40 and not (pdir / "instances").exists():
        time.sleep(0.5)
    time.sleep(2.0)
    chk(pdir.exists() and (pdir / "instances").exists(), "A 프로필을 주면 창 기록이 PolyPDF-<프로필> 폴더에 생긴다", str(pdir))
    after = set(os.listdir(real / "instances")) if (real / "instances").exists() else set()
    new = [n for n in after - before if str(p.pid) in n]
    chk(not new, "B 실제 폴더의 창 기록에는 이 실행이 적히지 않는다", str(new))
finally:
    p.kill(); p.wait(10)
    shutil.rmtree(pdir, ignore_errors=True)

os.environ["POLYPDF_PROFILE"] = ""
os.environ.pop("POLYPDF_OPEN_GATHER_NAME", None)
from viewer import open_gather
n0 = open_gather.server_name()
os.environ["POLYPDF_PROFILE"] = "test"
n1 = open_gather.server_name()
chk(n0 != n1 and n1.endswith("-test"), "C 넘기기 통로 이름이 프로필마다 다르다", "%s / %s" % (n0, n1))

import importlib.util
spec = importlib.util.spec_from_file_location("polypdf_main", os.path.join(HERE, "main.py"))
os.environ["POLYPDF_PROFILE"] = "..\\..\\evil/x"
src = Path(os.path.join(HERE, "main.py")).read_text(encoding="utf-8")
ns = {"os": os}
exec(src[src.index("def _profile()"):src.index("def _migrate_appdata()")], ns)
chk(ns["_profile"]() == "evilx", "D 프로필 이름은 영문·숫자·-_ 만", repr(ns["_profile"]()))

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
