# -*- coding: utf-8 -*-
"""261014-31: 녹화의 ffmpeg 는 진짜여야 한다 (영상 및 음성 SOT, 마스터 §14.5 U16).

CI 가 choco **shim**(392 KB — 다른 경로를 가리키는 작은 실행 파일)을 배포본에 넣어, 녹화가 바로 끝났다(설치 시험 뒤 녹화 시험).
A. `find_ffmpeg` 는 shim 처럼 작은 파일을 건너뛰고 다음 후보(진짜)를 고른다 — 아무것도 없으면 '' (앱은 구성요소 설치를 권한다)
B. `components.ffmpeg_installed` 는 shim 만 있으면 False
C. release.yml 은 components 릴리스의 ffmpeg.exe 를 먼저 받고, 넣은 뒤 `-version` 과 크기로 확인한다(Get-Command 의 shim 을 복사하지 않는다)
"""
import os, sys, tempfile, shutil
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


from viewer import recorder as rc
from viewer import components

tmp = Path(tempfile.mkdtemp(prefix="polypdf_ffmpeg_test_"))
try:
    shim = tmp / "shim" / "ffmpeg.exe"
    shim.parent.mkdir()
    shim.write_bytes(b"MZ" + b"\0" * 392 * 1024)                # choco shim 크기
    real = tmp / "real" / "ffmpeg.exe"
    real.parent.mkdir()
    with open(real, "wb") as f:
        f.truncate(rc.FFMPEG_MIN_BYTES + 1)                       # 진짜 크기(내용은 검사에 필요 없다)
    chk(not rc.real_ffmpeg(str(shim)) and rc.real_ffmpeg(str(real)), "A 크기로 shim 과 진짜를 가린다")
    _which = shutil.which
    _exe = sys.executable
    try:
        shutil.which = lambda name: None                          # PATH 에는 없다고 두고
        sys.executable = str(shim.parent / "PolyPDF.exe")         # 실행 파일 옆에 shim 만 있는 배포본
        rc_file = rc.__file__
        rc.__file__ = str(tmp / "none" / "viewer" / "recorder.py")  # 패키지 옆 후보도 비운다
        got = rc.find_ffmpeg("")
        chk(got == "", "A shim 만 있으면 찾지 못한 것으로(빈 값)", got)
        chk(components.ffmpeg_installed() is False, "B shim 만 있으면 '설치 안 됨'(구성요소 설치를 권한다)")
        got2 = rc.find_ffmpeg(str(real))
        chk(got2 == str(real), "A 설정한 진짜 경로는 그대로", got2)
    finally:
        shutil.which = _which
        sys.executable = _exe
        rc.__file__ = rc_file
    yml = (Path(HERE) / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    seg = yml[yml.find("Stage ffmpeg"):yml.find("Stage Tesseract")]
    chk("gh release download components" in seg and "-version" in seg and "5MB" in seg
        and "Get-Command ffmpeg" not in seg, "C release.yml 은 components 의 진짜 ffmpeg 를 넣고 실행·크기를 확인한다")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
