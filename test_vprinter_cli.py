# -*- coding: utf-8 -*-
"""261017(가상 프린터 SOT §4.2·§4.5·§6.1): 가상 프린터 설치 도구 `viewer/vprinter.py`·`--vprinter` 의 검사.

실제 프린터·드라이버·모니터는 건드리지 않는다(관리자가 아니면 설치·제거는 실패로 끝나야 하고, 상태만 읽는다).
A. 상태(`--vprinter check`)는 일반 권한에서 JSON 으로 나온다
B. 관리자가 아니면 install·remove 는 실패(1)로 끝나고 아무것도 바꾸지 않는다
C. 포트 설정 — 사용자별 폴더(%u)·문서 이름(%t)·PostScript, 인쇄 후 명령은 사용자별 예약 작업(P0 ②)
D. 스풀러 API 를 즉석 컴파일로 부르지 않는다 — PowerShell Add-Type 의 임시 DLL 을 알약이 잡았다(261017)
E. 들여온 포트 모니터 원본이 우리 이름으로 고쳐져 있다(monitor_src/POLYPDF_PATCHES.md)
F. main.py 는 `--vprinter` 를 PyQt 를 싣기 전에 처리한다(창 없이 빨리 끝나게)
"""
import ctypes
import json
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")    # Qt 는 쓰지 않는다 — 마스터 §14.7 규약(본문에 PyQt6 글자가 있다)
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8", errors="replace") as f:
        return f.read()


from viewer import vprinter as vp

print("=== A. 상태 ===")
r = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), "--vprinter", "check"], capture_output=True, timeout=120)
chk(r.returncode == 0, "A1 `--vprinter check` 가 0 으로 끝난다", str(r.returncode))
try:
    st = json.loads(r.stdout.decode("utf-8").strip().splitlines()[-1])
except Exception as ex:
    st = {}
    print("   출력:", r.stdout[-300:], r.stderr[-300:], ex)
want = {"support", "monitor", "dll", "port", "driver", "printer", "ppd", "spool", "default"}
chk(set(st) == want, "A2 상태 JSON 의 키", str(sorted(st)))
chk(st.get("support") in ("ok", "arm64", "x86", "wpp", "no-pscript"), "A3 지원 판정이 정해진 값", str(st.get("support")))

print("\n=== B. 관리자가 아니면 바꾸지 않는다 ===")
if ctypes.windll.shell32.IsUserAnAdmin():
    print("SKIP - 관리자로 실행 중(실제 프린터를 바꿀 수 있어 시험하지 않는다)")
else:
    before = vp.state()
    for action in ("install", "remove"):
        rc = vp.run_cli([action])
        chk(rc == vp.EXIT_FAIL, "B1 일반 권한 %s → 실패(1)" % action, str(rc))
    chk(vp.state() == before, "B2 상태가 그대로다")

print("\n=== C. 포트 설정 ===")
s, d = vp.port_config()
chk(s["FilePattern"].startswith("%u\\"), "C1 파일은 사용자별 폴더(%u)에 — 남의 파일을 볼 수 없게(P0 ②)")
chk("%t" in s["FilePattern"] and "%j" in s["FilePattern"], "C2 이름에 작업 번호·문서 이름(겹치지 않고, 원래 이름을 찾게 — SOT §4.3)")
chk(s["FilePattern"].endswith(".ps"), "C3 PostScript 로 받는다(변환은 사용자 쪽 — SOT §4.1)")
chk("schtasks.exe" in s["UserCommand"] and ('"' + vp.TASK_PREFIX + '%u"') in s["UserCommand"],
    "C4 인쇄 후 명령은 사용자별 예약 작업을 깨운다(모니터가 띄우면 세션 0)")
chk(s["OutputPath"] == vp.spool_root() and d["Overwrite"] == 0 and d["PipeData"] == 0, "C5 덮어쓰지 않고 파이프를 쓰지 않는다")
chk(all(ord(c) < 128 for c in vp.PRINTER_NAME + vp.PORT_NAME + vp.MONITOR_NAME + vp.TASK_PREFIX),
    "C6 시스템 이름은 영문(언어에 따라 바뀌지 않게)")

print("\n=== D. 즉석 컴파일 없음 ===")
import re
src = read("viewer/vprinter.py")
code = re.sub(r'"""(?:.|\n)*?"""', '""', src)                     # 설명문(이력 설명)은 보지 않는다
code = "\n".join(l.split("#", 1)[0] for l in code.splitlines())
chk("Add-Type" not in code and "powershell" not in code.lower(), "D1 vprinter 가 PowerShell·Add-Type 을 부르지 않는다")
chk(not os.path.exists(os.path.join(ROOT, "printer", "printer.ps1")), "D2 즉석 컴파일하던 printer.ps1 이 없다")

print("\n=== E. 포트 모니터 원본 ===")
chk('L"PolyPDF Port Monitor"' in read("printer/monitor_src/common/defs.cpp"), "E1 모니터 이름이 PolyPDF")
chk("LIBRARY polypdfmon" in read("printer/monitor_src/monitor/mfilemon.def"), "E2 DLL 이름 polypdfmon")
pl = read("printer/monitor_src/monitor/portlist.cpp").replace("\r\n", "\n")
# POLYPDF_NO_RUNAS 로 전처리했을 때 남는 줄에 OpenSSL 이 없어야 한다 — 생성자의 RAND_poll 을 놓쳐 CI 빌드가 실패했다(261017)
kept, stack = [], []
for l in pl.split("\n"):
    s = l.strip()
    if s.startswith("#ifndef POLYPDF_NO_RUNAS"):
        stack.append("skip"); continue
    if s.startswith("#ifdef POLYPDF_NO_RUNAS"):
        stack.append("keep"); continue
    if s.startswith("#if"):
        stack.append("other"); continue
    if s.startswith("#else") and stack and stack[-1] in ("skip", "keep"):
        stack[-1] = "keep" if stack[-1] == "skip" else "skip"; continue
    if s.startswith("#endif") and stack:
        stack.pop(); continue
    if "skip" not in stack:
        kept.append(l)
import re as _re
left = [l.strip() for l in kept if _re.search(r"\b(RAND_\w+|EVP_\w+)|openssl", l)]
chk(not left, "E3 '다른 계정으로 실행'(비밀번호·OpenSSL)을 뺀다 — 전처리 뒤 OpenSSL 없음", str(left[:3]))
chk("/DPOLYPDF_NO_RUNAS" in read("printer/build_monitor.bat"), "E4 빌드가 POLYPDF_NO_RUNAS 로 한다")
chk(os.path.exists(os.path.join(ROOT, "printer", "monitor_src", "LICENSE.txt")) and
    os.path.exists(os.path.join(ROOT, "printer", "monitor_src", "POLYPDF_PATCHES.md")), "E5 라이선스 원문·고친 곳 기록이 있다")
ppd = open(os.path.join(ROOT, "printer", "POLYPDF.PPD"), "rb").read()
chk(all(b < 128 for b in ppd) and b"*ColorDevice: True" in ppd and b'*ImageableArea A4/A4: "0 0 595 842"' in ppd,
    "E6 PPD — ASCII, 컬러, 여백 0")

print("\n=== F. main.py ===")
m = read("main.py")
chk(0 <= m.find('"--vprinter"') < m.find("from PyQt6"), "F1 `--vprinter` 를 PyQt 전에 처리")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for f in fails:
    print(" -", f)
sys.stdout.flush()
os._exit(0 if not fails else 1)
