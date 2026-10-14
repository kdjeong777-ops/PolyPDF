# -*- coding: utf-8 -*-
"""261014-27: 빌드에서 쓰지 않는 묶음 빼기 (마스터 §14.5 U23, 개선 로드맵 P3-9).

`scripts/prune_dist.py` 로:
A. 빼는 Qt 모듈을 앱 코드가 import 하지 않는다 — 새로 쓰게 되면 이 검사가 먼저 깨진다
B. wordfreq 는 코드가 묻는 언어(`zipf_frequency(…, "xx")`)만 남긴다
C. 실제 Qt DLL 로 만든 작은 묶음에서: 빼는 DLL(Qt6Pdf)을 지우면 그것을 부르는 플러그인(qpdf)도 함께 지우고, 남은 것은 모두 풀린다
D. 남은 파일이 지운 DLL 을 부르면(플러그인 밖) 실패로 알린다
E. build_ci.bat 가 PyInstaller 다음에 부르고 실패를 빌드 실패로 본다
F. tkinter 묶음은 빼지 않는다(빼면 exe 가 시작하자마자 끝난다 — 실측)
"""
import os, sys, re, shutil, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"          # PyQt6 는 DLL 경로를 찾는 데만 쓴다(§14.7 규약)
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "scripts"))
from pathlib import Path
import prune_dist as pd

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


root = Path(HERE)
code = [p for p in list((root / "viewer").rglob("*.py")) + [root / "main.py"] if "_vendor" not in p.parts]
src = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in code)

# A
removed_mods = [Path(p).stem for p in pd.REMOVE if p.startswith("PyQt6/") and p.endswith(".pyd")]
used = sorted({m for m in removed_mods if re.search(r"PyQt6\." + m + r"\b|from PyQt6 import [^\n]*\b" + m + r"\b", src)})
chk(removed_mods and not used, "A 빼는 Qt 모듈을 앱 코드가 import 하지 않는다", str(used))

# B
langs = set(re.findall(r"zipf_frequency\([^)]*?,\s*[\"']([a-z]{2,3})[\"']", src))
chk(langs and langs <= set(pd.KEEP_WORDFREQ_LANG), "B wordfreq 는 코드가 묻는 언어만 남긴다", f"{langs} vs {pd.KEEP_WORDFREQ_LANG}")

# C·D — 실제 Qt DLL 로 작은 묶음
import PyQt6
qt = Path(PyQt6.__file__).parent / "Qt6"
tmp = Path(tempfile.mkdtemp(prefix="polypdf_prune_test_"))
try:
    dist = tmp / "PolyPDF"
    b = dist / "_internal" / "PyQt6" / "Qt6" / "bin"
    pl = dist / "_internal" / "PyQt6" / "Qt6" / "plugins" / "imageformats"
    b.mkdir(parents=True); pl.mkdir(parents=True)
    names = {f.lower() for f in pd._imports(qt / "bin" / "Qt6Pdf.dll")} | {"qt6core.dll", "qt6gui.dll", "qt6pdf.dll"}
    for f in (qt / "bin").iterdir():
        if f.name.lower() in names:
            shutil.copy(f, b / f.name)
    # Qt6Gui·Qt6Pdf 가 부르는 Qt DLL 도(한 단계 더)
    for g in list(b.iterdir()):
        for n in pd._imports(g):
            s = qt / "bin" / n
            if s.exists() and not (b / s.name).exists():
                shutil.copy(s, b / s.name)
    shutil.copy(qt / "plugins" / "imageformats" / "qpdf.dll", pl / "qpdf.dll")
    shutil.copy(qt / "plugins" / "imageformats" / "qjpeg.dll", pl / "qjpeg.dll")
    r = pd.prune(dist)
    left = {p.name for p in dist.rglob("*") if p.is_file()}
    chk("Qt6Pdf.dll" not in left and "qpdf.dll" not in left and "qjpeg.dll" in left and "Qt6Core.dll" in left
        and not r["broken"], "C 뺀 DLL 을 부르는 플러그인도 함께 지우고 나머지는 풀린다", f"{sorted(left)} {r['broken']}")
    # D — 플러그인 밖 파일이 지울 DLL 을 부르면 실패
    shutil.copy(qt / "bin" / "Qt6Pdf.dll", b / "Qt6Pdf.dll")
    (dist / "_internal" / "PyQt6").joinpath("Holder").mkdir()
    shutil.copy(qt / "plugins" / "imageformats" / "qpdf.dll", dist / "_internal" / "PyQt6" / "Holder" / "qpdf.dll")
    r2 = pd.prune(dist)
    shutil.copy(qt / "bin" / "Qt6Pdf.dll", b / "Qt6Pdf.dll")          # 종료 코드도 — 같은 상태로 다시
    rc = pd.main([str(dist)])
    chk(any(p.name == "qpdf.dll" for p in r2["broken"]) and rc == 1,
        "D 플러그인 밖 파일이 지운 DLL 을 부르면 실패", str(r2["broken"]))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# E
bat = (root / "build_ci.bat").read_text(encoding="utf-8")
i_py, i_pr = bat.find("python -m PyInstaller"), bat.find("scripts\\prune_dist.py")
chk(0 < i_py < i_pr and "if errorlevel 1" in bat[i_pr:i_pr + 200], "E build_ci.bat 가 PyInstaller 뒤에 부르고 실패를 빌드 실패로")

# F
chk(not any("tcl" in p.lower() or "tk" in p.lower().split("/")[-1][:3] for p in pd.REMOVE), "F tkinter 묶음은 빼지 않는다",
    str([p for p in pd.REMOVE if "tcl" in p.lower() or "tk" in p.lower()]))

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
