"""261020-2(긴급, 릴리스 SOT §5): 빌드본 자가 시험과 PyMuPDF 고정 판.

beta.293 은 CI 가 PyMuPDF 2.0 을 받아(요구 사항이 `>=` 였다) 설치본이 시작하자마자 꺼졌다 — 레이아웃 모델 파일이 빌드 묶음에 없었다.
A. `main.py --selftest <파일>` 이 시작 때 싣는 모듈을 싣고 'ok …' 를 적고 0 으로 끝난다(CI 가 빌드본에 같은 것을 돌린다).
B. requirements.txt 의 PyMuPDF 는 `==` 고정 판이다.
C. release.yml 에 빌드본 자가 시험 단계가 있다.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


out = Path(tempfile.mkdtemp(prefix="polypdf_selftest_")) / "selftest.txt"
env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
r = subprocess.run([sys.executable, str(ROOT / "main.py"), "--selftest", str(out)], cwd=str(ROOT), env=env,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
first = out.read_text(encoding="utf-8").splitlines()[0] if out.exists() else ""
chk(r.returncode == 0 and first.startswith("ok ") and first.endswith(" text"),
    "A --selftest 가 모듈을 싣고 PDF 를 만들어 'ok' 로 끝난다", f"rc={r.returncode} {first!r} {r.stderr[-300:]!r}")

req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
m = re.search(r"^PyMuPDF\s*([=<>!~]=?)\s*([\w.]+)", req, re.M | re.I)
chk(m is not None and m.group(1) == "==", "B PyMuPDF 는 고정 판(==)", m.group(0) if m else "없음")

wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
chk("--selftest" in wf and wf.find("--selftest") > wf.find("build_ci.bat"),
    "C release.yml 이 빌드 뒤 빌드본 자가 시험을 돌린다")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
