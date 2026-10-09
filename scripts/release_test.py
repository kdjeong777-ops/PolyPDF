# -*- coding: utf-8 -*-
"""릴리스 전 시험 — **빌드 시험**과 **설치 시험**을 나눠 돌린다 (261009-18, 마스터 §14.5 U19).

  빌드 시험(build)   : 빌드된 프로그램을 **설치하지 않고** 그대로 띄워 잰다. UAC 없음.
                       --source local  이 PC 의 `dist\\PolyPDF\\PolyPDF.exe`(--rebuild 면 build_ci.bat 부터)
                       --source ci     CI 산출물 `PolyPDF-<ref>-full` 의 zip 을 풀어서(사용자에게 가는 것과 같은 빌드)
  설치 시험(install) : 설치 프로그램을 **기존 설치 위에** 돌리고(UAC), 버전·설치 정보를 확인한 뒤 설치본을 잰다.
                       --source ci     CI 산출물 `PolyPDF-<ref>-setup`(설치 프로그램만 — 다른 zip 은 받지 않는다)
                       --source local  이 PC 의 Inno(ISCC)로 `dist` 를 묶어서

두 시험은 **같은 측정 묶음**을 쓴다 — `probe_installed.py`(응답성 SOT §7.4)로 대상마다 창·열림 시간, 1초+ 정지,
메모리(본 + 띄어쓰기 도우미), 닫기·도우미 남음을 잰다. 대상 목록은 업무 파일 이름이 들어 있어 **공개 저장소 밖**
(`<작업 폴더>\\release_test_suite.json`)에 둔다. 시험 실행은 **시험 프로필**(`POLYPDF_PROFILE=test`)로 띄워
사용자 실제 설정은 읽기만 하고(복사해서 씀), 끝나면 시험 프로필을 지운다(261009-19 — 종전에는 실제 폴더를 백업·복원하다
사용자 색인을 지웠다). 지우지 못한 채 끊긴 시험이 있으면 새 시험을 시작하지 않는다.

사용:
  python scripts/release_test.py build   --source local [--rebuild] [--cases T1,T4]
  python scripts/release_test.py build   --source ci    [--run-id N]
  python scripts/release_test.py install --source ci    [--run-id N] [--no-suite]
  python scripts/release_test.py install --source local
  python scripts/release_test.py restore <결과 폴더>       (끊긴 시험의 시험 프로필 지우기)
결과: `<작업 폴더>\\_review\\<build|install>_<버전>_<시각>\\` — summary.md·runs\\·setup.log. 판정에 따라 종료 코드 0/1.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # public/
WORK = ROOT.parent                                      # 비공개 작업 폴더(SOT·_review·_samples)
SUITE = WORK / "release_test_suite.json"
REVIEW = WORK / "_review"
PENDING = ".restore_pending"                            # 이 파일이 있으면 설정을 아직 되돌리지 않았다
REPO = "kdjeong777-ops/PolyPDF"
DEFAULT_EXE = Path(r"C:\Program Files\PolyPDF\PolyPDF.exe")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_installed as probe                          # noqa: E402


def say(*a):
    print(*a, flush=True)


def source_version() -> str:
    s = (ROOT / "viewer" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', s).group(1)


def exe_version(exe: Path) -> str:
    f = exe.parent / "_internal" / "viewer" / "__init__.py"
    try:
        return re.search(r'__version__\s*=\s*"([^"]+)"', f.read_text(encoding="utf-8")).group(1)
    except Exception:
        return ""


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def gh(*args) -> str:
    r = subprocess.run(["gh", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit("gh 실패: gh %s\n%s" % (" ".join(args), r.stderr.strip()))
    return r.stdout


# ── 끊긴 시험 지키기 ─────────────────────────────────────────────
def check_no_pending():
    left = sorted(REVIEW.glob("*/" + PENDING)) if REVIEW.exists() else []
    if left:
        raise SystemExit("설정을 아직 되돌리지 않은 시험이 있다 — 먼저 되돌린다:\n" +
                         "\n".join("  python scripts/release_test.py restore \"%s\"" % p.parent for p in left))


def restore_dir(out: Path):
    """시험 프로필(`PolyPDF-test`)을 지운다 — 사용자 실제 설정은 처음부터 건드리지 않는다(261009-19)."""
    probe.drop()
    (out / PENDING).unlink(missing_ok=True)


# ── 시험 대상 exe 얻기 ───────────────────────────────────────────
def ci_run_id(run_id):
    """Release 워크플로의 성공한 main 실행 — 기본은 **지금 HEAD 커밋**의 것(다른 커밋이면 멈춘다)."""
    if run_id:
        return str(run_id)
    head = git_head()
    rows = json.loads(gh("run", "list", "-R", REPO, "--workflow", "release.yml", "--branch", "main", "--limit", "10",
                         "--json", "databaseId,headSha,status,conclusion"))
    for r in rows:
        if r["headSha"] == head and r["status"] == "completed" and r["conclusion"] == "success":
            return str(r["databaseId"])
    raise SystemExit("HEAD(%s) 의 성공한 Release 실행이 없다 — `gh workflow run release.yml --ref main` 로 돌린 뒤 다시"
                     % head[:7])


def ci_download(run_id: str, kind: str, dest: Path) -> Path:
    """산출물 하나만(`PolyPDF-main-setup` 또는 `-full`) 받는다 — 셋을 한 묶음으로 받으면 1GB 다(261009-18)."""
    name = "PolyPDF-main-%s" % kind
    dest.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    gh("run", "download", run_id, "-R", REPO, "-n", name, "-D", str(dest))
    files = [p for p in dest.rglob("*") if p.is_file()]
    say("받음: %s (%d개, %.0fMB, %.0f초)" % (name, len(files), sum(p.stat().st_size for p in files) / 2**20,
                                          time.perf_counter() - t))
    return dest


def newer_sources(exe: Path) -> list:
    """빌드본보다 나중에 고친 소스 — 같은 버전 번호로 낡은 빌드를 재는 것을 막는다(버전 비교만으로는 못 잡는다)."""
    t = exe.stat().st_mtime
    files = [ROOT / "main.py", ROOT / "build_ci.bat", *(ROOT / "viewer").rglob("*.py"), *(ROOT / "resources").rglob("*.po")]
    return [str(f.relative_to(ROOT)) for f in files if f.exists() and f.stat().st_mtime > t + 1]


def local_build():
    """build_ci.bat — 절대 경로로, 작업 폴더는 cwd(마스터 §14.2·빌드 메모). 실행 중인 dist 본은 먼저 닫는다."""
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process PolyPDF -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '%s*' } | Stop-Process -Force"
                    % (ROOT / "dist")], capture_output=True)
    log = ROOT / "_build.log"
    bat = ROOT / "build_ci.bat"
    say("빌드 중(수 분) — 로그:", log)
    # 배치 파일을 절대 경로로 바로 띄우고 작업 폴더는 cwd 로(cmd 따옴표 규칙을 피한다 — 이 PC 는 현재 폴더에서 배치를 찾지 않는다)
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        r = subprocess.run([str(bat)], cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT)
    if r.returncode != 0 or "BUILD SUCCESS" not in log.read_text(encoding="utf-8", errors="replace"):
        raise SystemExit("빌드 실패 — %s" % log)


def exe_for_build(a, out: Path) -> Path:
    if a.source == "local":
        if a.rebuild:
            local_build()
        exe = ROOT / "dist" / "PolyPDF" / "PolyPDF.exe"
        if not exe.exists():
            raise SystemExit("빌드본이 없다: %s (--rebuild 로 빌드부터)" % exe)
        stale = newer_sources(exe)
        if stale:
            raise SystemExit("빌드 뒤에 바뀐 소스가 있다(버전이 같아도 낡은 빌드) — --rebuild 로: %s" % ", ".join(stale[:5]))
    else:
        d = ci_download(ci_run_id(a.run_id), "full", out / "artifact")
        z = next(d.rglob("*-win64.zip"))
        app = out / "app"
        with zipfile.ZipFile(z) as zf:
            zf.extractall(app)
        exe = next(app.rglob("PolyPDF.exe"))
    v, want = exe_version(exe), source_version()
    if v != want:
        raise SystemExit("빌드본 버전 %s ≠ 소스 %s — 낡은 빌드를 재는 것을 막는다" % (v or "?", want))
    return exe


def installed_info():
    ps = ("$k = Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
          "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' -ErrorAction SilentlyContinue |"
          " Where-Object { $_.DisplayName -like 'PolyPDF*' } | Select-Object -First 1;"
          " if ($k) { $k.DisplayVersion + '|' + $k.InstallLocation }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    dv, _, loc = r.stdout.strip().partition("|")
    exe = (Path(loc) / "PolyPDF.exe") if loc else DEFAULT_EXE
    return dv, exe


def exe_for_install(a, out: Path, rec: dict) -> Path:
    want = source_version()
    if a.source == "ci":
        d = ci_download(ci_run_id(a.run_id), "setup", out / "artifact")
        setup = next(d.rglob("PolyPDF-Setup-v*.exe"))
    else:
        exe = ROOT / "dist" / "PolyPDF" / "PolyPDF.exe"
        if exe_version(exe) != want:
            raise SystemExit("dist 빌드본이 소스 버전(%s)이 아니다 — build --source local --rebuild 먼저" % want)
        iscc = next((p for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
                                 Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe") if p.exists()), None)
        if iscc is None:
            raise SystemExit("ISCC.exe 가 없다(Inno Setup 6)")
        r = subprocess.run([str(iscc), "/DMyAppVersion=%s" % want, str(ROOT / "installer" / "PolyPDF.iss")],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        setup = ROOT / ("PolyPDF-Setup-v%s.exe" % want)
        if r.returncode != 0 or not setup.exists():
            (out / "iscc.log").write_text(r.stdout + r.stderr, encoding="utf-8")
            raise SystemExit("ISCC 실패 — %s" % (out / "iscc.log"))
    before_dv, before_exe = installed_info()
    rec["before"] = {"display_version": before_dv, "app_version": exe_version(before_exe)}
    say("설치 전: 설치 정보 %s · 앱 파일 %s" % (before_dv or "(없음)", rec["before"]["app_version"] or "(없음)"))
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process PolyPDF -ErrorAction SilentlyContinue | ForEach-Object { $null = $_.CloseMainWindow() }"],
                   capture_output=True)
    time.sleep(3)
    log = out / "setup.log"
    say("설치 프로그램 실행 — **UAC 를 승인**해 주세요:", setup.name)
    ps = ("$p = Start-Process -FilePath '%s' -ArgumentList '/SILENT','/NORESTART','/LOG=\"%s\"' -Verb RunAs -PassThru -Wait;"
          " $p.ExitCode" % (setup, log))
    t = time.perf_counter()
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    code = (r.stdout.strip().splitlines() or ["?"])[-1]
    dv, exe = installed_info()
    rec["install"] = {"exit": code, "sec": round(time.perf_counter() - t), "display_version": dv,
                      "app_version": exe_version(exe), "setup": setup.name}
    say("설치: 종료 코드 %s · %s초 · 설치 정보 %s · 앱 파일 %s" % (code, rec["install"]["sec"], dv, rec["install"]["app_version"]))
    if code != "0" or dv != want or rec["install"]["app_version"] != want:
        rec["fail"].append("설치 결과가 %s 가 아니다(종료 코드·설치 정보·앱 파일)" % want)
    return exe


# ── 측정 묶음 ────────────────────────────────────────────────────
def load_suite(only):
    if not SUITE.exists():
        raise SystemExit("측정 대상 목록이 없다: %s (예시는 이 파일의 맨 아래 주석)" % SUITE)
    d = json.loads(SUITE.read_text(encoding="utf-8"))
    base = Path(d.get("samples", str(WORK / "_samples")))
    cases = d["cases"]
    if only:
        keep = {c.strip() for c in only.split(",")}
        cases = [c for c in cases if c["name"] in keep or c["name"].split("_")[0] in keep]
    return base, cases


def run_suite(exe: Path, out: Path, only, rec: dict):
    base, cases = load_suite(only)
    probe.EXE = exe
    # 261009-19: 실제 설정은 **읽어서** 시험 프로필로 복사만 — 대상마다 그 복사본(cfg_seed)으로 되돌린다
    probe.seed()
    bk = out / "cfg_seed"
    probe.backup(bk)
    (out / PENDING).write_text("시험 프로필: %s\n" % probe.CFG, encoding="utf-8")
    try:
        for c in cases:
            probe.restore(bk)
            if c.get("clear_index"):
                probe.clear_index()
            target = base / c["target"]
            if not target.exists():
                rec["fail"].append("%s 대상이 없다: %s" % (c["name"], target))
                continue
            r = probe.run(c["name"], target, int(c.get("seconds", 60)), out / "runs")
            rec["runs"].append({k: r.get(k) for k in ("name", "t_window", "t_loaded", "max_hang_sec", "peak_ws_mb",
                                                      "max_private_mb", "helper_max_ws_mb", "helper_left",
                                                      "close_sec", "exit", "indexed_files")} | {"hangs": len(r["hangs"])})
            if r["max_hang_sec"] >= 1.0:
                rec["fail"].append("%s 1초+ 정지 %d회(최장 %ss)" % (c["name"], len(r["hangs"]), r["max_hang_sec"]))
            if r.get("helper_left"):
                rec["fail"].append("%s 닫은 뒤 도우미 %s개 남음" % (c["name"], r["helper_left"]))
            if r["exit"] or r.get("close_sec") is None:
                rec["fail"].append("%s 종료 이상: %s" % (c["name"], r["exit"] or "닫히지 않음"))
    finally:
        restore_dir(out)


def write_summary(out: Path, rec: dict):
    L = ["# %s 시험 — %s (%s)" % ("빌드" if rec["mode"] == "build" else "설치", rec["version"], rec["source"]), "",
         "- 커밋 `%s` · exe `%s`" % (rec["commit"][:7], rec["exe"])]
    if "install" in rec:
        i, b = rec["install"], rec["before"]
        L.append("- 설치: %s → 종료 코드 %s · %s초 · 설치 정보 %s → %s · 앱 파일 %s → %s"
                 % (i["setup"], i["exit"], i["sec"], b["display_version"] or "-", i["display_version"],
                    b["app_version"] or "-", i["app_version"]))
    if rec["runs"]:
        L += ["", "| 대상 | 창 | 열림 | 1초+ 정지 | 최장 | 최대 작업 집합 | 도우미 | 도우미 남음 | 색인한 파일 | 닫기 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in rec["runs"]:
            L.append("| %s | %ss | %ss | %d | %ss | %sMB | %sMB | %s | %s | %ss |" % (
                r["name"], r["t_window"], r["t_loaded"], r["hangs"], r["max_hang_sec"], round(r["peak_ws_mb"] or 0),
                round(r["helper_max_ws_mb"] or 0), r.get("helper_left", "-"), r.get("indexed_files"), r["close_sec"]))
    L += ["", "**판정: %s**" % ("통과" if not rec["fail"] else "실패")] + ["- " + f for f in rec["fail"]]
    (out / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (out / "result.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    say("\n".join(L))
    say("\n결과:", out)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")      # 도움말·결과의 한글·'—' 가 cp949 콘솔에서 깨지지 않게
        sys.stderr.reconfigure(encoding="utf-8")      # SystemExit 안내도
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="릴리스 전 시험 — 빌드 시험 / 설치 시험 (마스터 §14.5 U19)")
    sub = ap.add_subparsers(dest="mode", required=True)
    for m in ("build", "install"):
        p = sub.add_parser(m)
        p.add_argument("--source", choices=("local", "ci"), default="local" if m == "build" else "ci")
        p.add_argument("--run-id", help="CI Release 실행 번호(기본: HEAD 커밋의 성공한 실행)")
        p.add_argument("--cases", help="일부만: T1,T4 처럼 이름 앞부분")
        if m == "build":
            p.add_argument("--rebuild", action="store_true", help="build_ci.bat 부터(--source local)")
        else:
            p.add_argument("--no-suite", action="store_true", help="설치·버전 확인만")
    p = sub.add_parser("restore")
    p.add_argument("out")
    a = ap.parse_args()

    if a.mode == "restore":
        restore_dir(Path(a.out))
        return 0
    check_no_pending()
    ver = source_version()
    out = REVIEW / ("%s_%s_%s" % (a.mode, ver, time.strftime("%y%m%d-%H%M")))
    out.mkdir(parents=True, exist_ok=False)
    rec = {"mode": a.mode, "source": a.source, "version": ver, "commit": git_head(), "runs": [], "fail": []}
    try:
        if a.mode == "build":
            exe = exe_for_build(a, out)
        else:
            exe = exe_for_install(a, out, rec)
        rec["exe"] = str(exe)
        if not (a.mode == "install" and a.no_suite) and not rec["fail"]:
            run_suite(exe, out, a.cases, rec)
    except SystemExit as e:
        rec["fail"].append(str(e))
        rec.setdefault("exe", "-")
    write_summary(out, rec)
    return 0 if not rec["fail"] else 1


if __name__ == "__main__":
    sys.exit(main())

# release_test_suite.json 예시(공개 저장소 밖, <작업 폴더> 에):
# {"samples": "C:/My/PolyPDF/_samples",
#  "cases": [{"name": "T1_small", "target": "작은 문서.pdf", "seconds": 45},
#            {"name": "T5_std", "target": "PDF/기준 폴더", "seconds": 300, "clear_index": true}]}
