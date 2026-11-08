# -*- coding: utf-8 -*-
"""261108-20 덧붙임(사용자 결정 '설치본 그대로 재기'): `release_test.py install --skip-install` — 릴리스 SOT §3.1·§4.

원격 접속이라 UAC(보안 화면)에 답할 수 없어, 이미 설치된 beta.8 을 다시 잴 때마다 설치 단계에서 126초 뒤 멈췄다.
  A  명령줄에 `--skip-install` 이 있다
  B  설치 정보·앱 파일이 요구 판이 아니면 멈춘다(SystemExit) — 둘 중 하나만 달라도
  C  같으면 설치하지 않고 그 exe 를 돌려주며, 같은 판을 설치한 가장 최근 설치 시험 폴더를 기록한다(현재 폴더·setup.log 없는 폴더 제외)
  D  요약에 '설치 건너뜀 — 설치는 <폴더>' 가 나온다
실제 설치·레지스트리·_review 는 건드리지 않는다 — `installed_info`·`exe_version`·`source_version`·`REVIEW` 를 바꿔 끼운다.
"""
import shutil, subprocess, sys, tempfile
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))
import release_test as R                 # noqa: E402

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


r = subprocess.run([sys.executable, str(HERE / "scripts" / "release_test.py"), "install", "--help"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
chk("--skip-install" in r.stdout, "A 설치 시험에 --skip-install 이 있다", r.stdout[-300:] + r.stderr[-300:])

fn = getattr(R, "exe_skip_install", None)
if fn is None:
    chk(False, "B·C·D 설치를 건너뛰는 길(`exe_skip_install`)이 있다")
else:
    tmp = Path(tempfile.mkdtemp(prefix="skipinst261108_"))
    saved = {n: getattr(R, n) for n in ("installed_info", "exe_version", "source_version", "REVIEW", "say")}
    try:
        R.REVIEW = tmp
        R.say = lambda *a: None
        R.source_version = lambda: "1.1.0-beta.8"
        old = tmp / "install_1.1.0-beta.8_261108-1918"; old.mkdir(); (old / "setup.log").write_text("ok")
        nolog = tmp / "install_1.1.0-beta.8_261108-2013"; nolog.mkdir()          # UAC 에서 멈춘 것 — setup.log 없음
        out = tmp / "install_1.1.0-beta.8_261108-2100"; out.mkdir()
        exe = Path(r"C:\Program Files\PolyPDF\PolyPDF.exe")
        for dv, av, why in (("1.1.0-beta.7", "1.1.0-beta.8", "설치 정보"), ("1.1.0-beta.8", "1.1.0-beta.7", "앱 파일"),
                            ("", "", "설치 안 됨")):
            R.installed_info = lambda dv=dv: (dv, exe)
            R.exe_version = lambda p, av=av: av
            rec = {"fail": [], "runs": []}
            try:
                fn(out, rec, None)
                stopped = False
            except SystemExit:
                stopped = True
            chk(stopped and "install" not in rec, "B 요구 판이 아니면 멈춘다 — %s" % why)
        R.installed_info = lambda: ("1.1.0-beta.8", exe)
        R.exe_version = lambda p: "1.1.0-beta.8"
        rec = {"fail": [], "runs": [], "mode": "install", "source": "ci", "version": "1.1.0-beta.8",
               "commit": "0123456789", "exe": str(exe)}
        got = fn(out, rec, None)
        i = rec.get("install", {})
        chk(got == exe and i.get("skipped") and i.get("installed_by") == str(old),
            "C 같으면 그 exe 를 재고 설치한 시험 폴더를 적는다", (got, i))
        rec2 = {"fail": [], "runs": []}
        fn(out, rec2, r"D:\elsewhere")
        chk(rec2["install"].get("installed_by") == r"D:\elsewhere", "C 폴더를 주면 그것을 적는다", rec2["install"])
        R.write_summary(out, rec)
        s = (out / "summary.md").read_text(encoding="utf-8")
        chk("설치 건너뜀" in s and str(old) in s, "D 요약에 '설치 건너뜀 — 설치는 <폴더>'", s[:400])
    finally:
        for n, f in saved.items():
            setattr(R, n, f)
        shutil.rmtree(tmp, ignore_errors=True)

print()
if fails:
    print("=== FAILURE (%d) ===" % len(fails))
    sys.exit(1)
print("ALL PASS")
