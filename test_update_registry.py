# -*- coding: utf-8 -*-
"""261010-15: 앱 안 업데이트 뒤 설치 정보(제어판 '프로그램 추가/제거')의 버전도 새 판으로 (마스터 §14.5).

설치 시험에서: 앱 안 업데이트로 beta.228 까지 올린 PC 의 설치 정보가 beta.223 에 머물러 있었다 — 도우미가 파일만 바꿨다.
설치 도우미 스크립트(`_PS_INSTALLER`)의 그 부분을 **실제 PowerShell 로** 돌린다. 진짜 Uninstall 키 대신 시험용 키
(`HKCU:\\Software\\PolyPDF-test-uninstall`)로 바꿔 넣고, 끝나면 지운다.

A. 설치 위치가 같은 항목: DisplayVersion·DisplayName 이 방금 깐 파일의 판으로(끝 '\\' 차이는 무시)
B. 설치 위치가 다른 항목(다른 설치·휴대용)은 그대로
C. 업데이트가 성공했을 때만, 다시 띄우기 전에
"""
import os, sys, subprocess, tempfile, shutil
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from viewer import updater

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


BS = chr(92)
ps = updater._PS_INSTALLER
a = ps.find("    # 261010-15(")
ok_at = ps.find("if ($fail -eq 0) {")
chk(0 <= ok_at < a < ps.find("# 3) 재실행"), "C 성공 블록 안, 다시 띄우기 전에")
b = ps.index("    } catch {}", a) + len("    } catch {}")
frag = ps[a:b]
root = "HKCU:" + BS + "Software" + BS + "PolyPDF-test-uninstall"
for real in ("HKLM:", "HKCU:"):
    frag = frag.replace("'" + real + BS + "SOFTWARE" + BS + "Microsoft" + BS + "Windows" + BS + "CurrentVersion" + BS + "Uninstall'",
                        "'" + root + "'")
chk(frag.count(root) == 2, "준비 — 두 Uninstall 위치를 시험 키로 바꿨다")

inst = tempfile.mkdtemp(prefix="polypdf_reg_")
other = tempfile.mkdtemp(prefix="polypdf_reg_other_")
os.makedirs(os.path.join(inst, "_internal", "viewer"))
with open(os.path.join(inst, "_internal", "viewer", "__init__.py"), "w", encoding="utf-8") as f:
    f.write('__version__ = "9.9.9-beta.1"\n')


def mk(key, loc):
    k = root + BS + key
    return ("New-Item -Path '%s' -Force | Out-Null\n"
            "New-ItemProperty -Path '%s' -Name DisplayName -Value 'PolyPDF v0.1' -Force | Out-Null\n"
            "New-ItemProperty -Path '%s' -Name DisplayVersion -Value '0.1' -Force | Out-Null\n"
            "New-ItemProperty -Path '%s' -Name InstallLocation -Value '%s' -Force | Out-Null\n" % (k, k, k, k, loc))


script = ("$ErrorActionPreference='Stop'\n" + mk("a", inst + BS) + mk("b", other)
          + "$install = '%s'\n$ErrorActionPreference='Continue'\n" % inst + frag
          + "\n$a = Get-ItemProperty '%s'; $b = Get-ItemProperty '%s'\n" % (root + BS + "a", root + BS + "b")
          + "'A=' + $a.DisplayVersion + '|' + $a.DisplayName\n'B=' + $b.DisplayVersion + '|' + $b.DisplayName\n"
          + "Remove-Item -Path '%s' -Recurse -Force\n'cleaned=' + (-not (Test-Path '%s'))\n" % (root, root))
p = os.path.join(tempfile.gettempdir(), "polypdf_regtest_%d.ps1" % os.getpid())
try:
    with open(p, "w", encoding="utf-8-sig") as f:
        f.write(script)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", p],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    out = dict(l.split("=", 1) for l in r.stdout.strip().splitlines() if "=" in l)
    chk(out.get("A") == "9.9.9-beta.1|PolyPDF v9.9.9-beta.1", "A 같은 설치 위치 → 새 판", r.stdout + r.stderr[:300])
    chk(out.get("B") == "0.1|PolyPDF v0.1", "B 다른 설치 위치는 그대로", str(out.get("B")))
    chk(out.get("cleaned") == "True", "시험 키를 지웠다")
finally:
    for t in (p,):
        try:
            os.remove(t)
        except Exception:
            pass
    shutil.rmtree(inst, ignore_errors=True)
    shutil.rmtree(other, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.exit(1 if fails else 0)
