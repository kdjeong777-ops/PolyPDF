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

무엇을 돌릴지는 먼저 `plan` 으로 정한다(릴리스 SOT, 261010-4) — 기준점(마지막으로 통과한 시험, `_review\\baseline.json`)
부터의 diff 로 등급(설치 시험 / 빌드 시험 / 생략 후보)과 이번 변경에 맞춘 확인 항목을 낸다. 시험 결과는 기준점 결과와
자동으로 견줘 20% 넘게 나빠진 값을 '회귀 의심' 으로 적는다(판정은 바꾸지 않는다).

사용:
  python scripts/release_test.py plan    [--base v0.45.0-beta.223] [--urgent]
  python scripts/release_test.py checks  [--ui]                 (묶음 릴리스: test_*.py 전부 + 화면 점검)
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


# ── 시험 계획 — 등급 판정(릴리스 SOT §3·§4, 261010-4) ─────────────
# 판정 경로의 **정확한 목록은 여기 한 곳**이 소유한다 — SOT 는 까닭과 영역만 적고 이 상수를 가리킨다.
INSTALL_PATHS = ("installer/", "build_ci.bat", "scripts/i18n.py", ".github/workflows/release.yml", "viewer/updater.py")
BUILD_PATHS = ("main.py", "requirements.txt", "viewer/workers.py", "viewer/index_proc.py", "viewer/kiwi_space.py",
               "viewer/child_job.py", "viewer/indexer.py", "viewer/settings_store.py", "viewer/open_gather.py",
               "viewer/widgets/thumbs_list.py")
# 바뀐 줄에 이것이 있으면 배경 작업·프로세스·DB 잠금을 건드린 것이다(응답성 SOT — 판정은 실측)
BUILD_TOKENS = re.compile(r"QThread|QTimer|threading|multiprocessing|subprocess|ThreadPool|sqlite3\.connect|processEvents")
# app.py 는 거의 모든 변경이 지나가므로 파일이 아니라 **시작·종료 함수**를 건드렸는지로 가른다
APP_FUNCS = re.compile(r"def (__init__|closeEvent|_startup_\w+|_start_index_worker)\b")
NO_BUILD = re.compile(r"(\.md$|^test_[^/]+\.py$|^resources/locale/|^\.gitignore$|^LICENSE)")
SMALL_LINES = 40                    # 코드 바뀐 줄이 이보다 적고 파일 3개 이하면 '미미' 후보
SAVE_TOKENS = re.compile(r"_finalize_save|_file_op_bg|os\.replace|_open_saved_file")
FOCUS = [   # (경로 앞부분, 볼 것, 측정 대상) — 상시 점검 목록(릴리스 SOT §5)에서 그 경로에 해당하는 것
    (("viewer/indexer.py", "viewer/index_proc.py", "viewer/workers.py"),
     "색인 — T5·T6 '색인한 파일' 수를 기준점과 견준다", "T5,T6"),
    (("viewer/kiwi_space.py", "viewer/text_extract2.py"), "한글 띄어쓰기 도우미 — 한글 대상의 정지·도우미 남음", "T1,T2,T3"),
    (("viewer/widgets/thumbs_list.py", "viewer/page_meta.py", "viewer/hyperlinks.py", "viewer/pdf_doc.py"),
     "큰 문서 첫 열기 — T3 정지", "T3"),
    (("viewer/settings_store.py", "viewer/open_gather.py", "main.py"),
     "데이터 위치 — 끝난 뒤 실제 설정 폴더를 탐색기로, 휴대용 경로를 바꿨으면 zip 을 풀어 실행(마스터 §14.9)", None),
    (("viewer/child_job.py",), "자식 프로세스 — 모든 대상 '도우미 남음' 0", None),
    (("installer/", "build_ci.bat", "scripts/i18n.py"),
     "설치 결과 — 종료 코드·버전·언어 유지(다국어 SOT §10.5), 작업 표시줄 아이콘은 사용자에게 확인", None),
    (("viewer/updater.py",), "앱 안 업데이트 — 이 시험으로는 못 본다(못 한 것으로 적는다)", None),
    ((".github/workflows/release.yml",), "릴리스 자산 — 태그 뒤 자산 목록·설치 프로그램·휴대용 zip", None),
]


def classify(changes: list, diff_text: str) -> dict:
    """changes = [(상태, 경로, 바뀐 줄 수)], diff_text = `git diff -U0`(파이썬 함수 머리 포함).
    돌려줌: level(install|build|skip), reasons, focus, code_lines. **skip 은 후보** — 사용자에게 묻는다(릴리스 SOT §3.1)."""
    paths = [p for _, p, _ in changes]
    reasons, focus = [], []
    inst = [p for p in paths if p.startswith(INSTALL_PATHS)]
    if inst:
        reasons.append("설치 관련 파일: " + ", ".join(inst))
    code = [(s, p, n) for s, p, n in changes if not NO_BUILD.search(p)]
    code_lines = sum(n for _, _, n in code)
    must = [p for p in paths if p.startswith(BUILD_PATHS)]
    if must:
        reasons.append("빌드 시험 필수 경로: " + ", ".join(must))
    new = [p for s, p, _ in code if s.startswith("A") and p.endswith(".py")]
    if new:
        reasons.append("새 모듈: " + ", ".join(new))
    if any(p in ("requirements.txt",) for p in paths):
        reasons.append("의존 패키지 변경")
    cur, tok_files, app_hit = None, set(), False
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and cur == "viewer/app.py" and APP_FUNCS.search(line):
            app_hit = True
        elif cur and line[:1] in "+-" and not line.startswith(("+++", "---")) and not NO_BUILD.search(cur):
            if BUILD_TOKENS.search(line):
                tok_files.add(cur)
            if SAVE_TOKENS.search(line):
                focus.append(("원본 덮어쓰기 저장 — 실제 PDF 로 저장·다시 열기(마스터 §4.7.5)", None))
    if app_hit:
        reasons.append("app.py 시작·종료 함수")
    if tok_files:
        reasons.append("배경 작업·프로세스·DB 잠금 줄: " + ", ".join(sorted(tok_files)))
    for prefixes, what, cases in FOCUS:
        if any(p.startswith(prefixes) for p in paths):
            focus.append((what, cases))
    if inst:
        level = "install"
    elif reasons or code_lines >= SMALL_LINES or len(code) > 3:
        level = "build"
        if not reasons:
            reasons.append("코드 %d줄·%d개 파일 — 미미한 변경이 아니다" % (code_lines, len(code)))
    elif code:
        level, reasons = "skip", ["코드 %d줄·%d개 파일, 필수 경로·새 모듈·배경 작업 줄 없음" % (code_lines, len(code))]
    else:
        level, reasons = "skip", ["코드 변경 없음(문서·검사·번역문만)"]
    seen, uniq = set(), []
    for f in focus:
        if f[0] not in seen:
            seen.add(f[0])
            uniq.append(f)
    return {"level": level, "reasons": reasons, "focus": uniq, "code_lines": code_lines, "code_files": len(code)}


BASELINE = REVIEW / "baseline.json"


def load_baseline():
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except Exception:
        return None


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout


PENDING_DAYS, PENDING_COUNT = 14, 5     # 묶음 릴리스 제안 기준(릴리스 SOT §2.2)
CHECK_TIMEOUT = 600                     # 검사 하나의 상한(초)


def checks(ui: bool, only=None) -> int:
    """묶음 릴리스의 전체 검사(릴리스 SOT §4.1) — CI 는 일부만 돌리므로 `test_*.py` **전부**를 개발 venv 로,
    판정은 **종료 코드**(출력 문자열 아님 — 'ALL PASS' 대신 '전부 통과' 로 끝나는 검사가 있다). `--ui` 면 화면 점검 ko·en 도."""
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    out = REVIEW / ("checks_%s_%s" % (source_version(), time.strftime("%y%m%d-%H%M%S")))
    (out / "logs").mkdir(parents=True)
    tests = sorted(p for p in ROOT.glob("test_*.py") if p.name != "test_fixtures.py")
    if only:                                      # 다시 볼 것만: --only nup_links,ocr_lang
        keys = [k.strip() for k in only.split(",") if k.strip()]
        tests = [t for t in tests if any(k in t.name for k in keys)]
    fails, flaky, t0 = [], [], time.perf_counter()
    env = dict(os.environ, PYTHONUNBUFFERED="1")    # 걸렸을 때 로그에 어디까지 갔는지 남게
    for i, t in enumerate(tests, 1):
        s = time.perf_counter()
        rcs = []
        for k in range(2):                            # 실패하면 한 번 더 — 다시 통과하면 '불안정' 으로 따로 적는다
            log = out / "logs" / (t.stem + ("" if k == 0 else ".retry") + ".log")
            with open(log, "w", encoding="utf-8", errors="replace") as f:
                try:
                    rc = subprocess.run([str(py), "-I", t.name], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                        timeout=CHECK_TIMEOUT, env=env).returncode
                except subprocess.TimeoutExpired:
                    rc = "시간 초과"
            rcs.append(rc)
            if rc == 0:
                break
        if rcs[-1] != 0:
            fails.append("%s (rc=%s)" % (t.name, "·".join(map(str, rcs))))
        elif len(rcs) > 1:
            flaky.append("%s (처음 rc=%s, 다시 통과)" % (t.name, rcs[0]))
        say("[%d/%d] %s %s %.0fs" % (i, len(tests), "통과" if rcs[-1] == 0 else "실패", t.name, time.perf_counter() - s))
    L = ["# 전체 검사 — %s" % source_version(), "",
         "- 검사 %d개 · 통과 %d · 실패 %d · 불안정 %d · %.0f분" % (
             len(tests), len(tests) - len(fails), len(fails), len(flaky), (time.perf_counter() - t0) / 60)]
    L += ["- 실패: " + f for f in fails] + ["- 불안정(원인을 찾는다): " + f for f in flaky]
    if ui:
        r = subprocess.run([str(py), "scripts/ui_check.py", "--out", str(out / "ui")], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        L.append("- 화면 점검(ko·en): 종료 코드 %s — `%s`" % (r.returncode, out / "ui" / "summary.md"))
        if r.returncode != 0:
            fails.append("ui_check")
    L += ["", "**판정: %s**" % ("통과" if not fails else "실패")]
    (out / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    say("\n".join(L) + "\n결과: %s" % out)
    return 0 if not fails else 1


def unreleased() -> dict:
    """마지막 릴리스 태그 뒤에 쌓인 코드 커밋(docs·test 제외) — 묶음 릴리스를 제안할 때가 됐나."""
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v*").strip()
    if not tag:
        return {"tag": "", "count": 0, "days": 0}
    rows = [l.split("\t", 1) for l in git("log", "--format=%ct\t%s", tag + "..HEAD").splitlines() if "\t" in l]
    code = [(int(t), s) for t, s in rows if not re.match(r"(docs|test|chore)(\(|:)", s)]
    days = (time.time() - min(t for t, _ in code)) / 86400 if code else 0
    return {"tag": tag, "count": len(code), "days": int(days)}


def plan(base_arg, urgent=False) -> int:
    bl = load_baseline()
    base = base_arg or (bl or {}).get("commit")
    if not base:
        raise SystemExit("기준점이 없다 — --base <커밋|태그> 로 주거나 시험을 한 번 통과시켜 %s 를 만든다" % BASELINE)
    ns = [l.split("\t") for l in git("diff", "--name-status", base + "..HEAD").splitlines() if l]
    nums = {}
    for l in git("diff", "--numstat", base + "..HEAD").splitlines():
        a, d, p = l.split("\t", 2)
        nums[p] = (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    changes = [(r[0], r[-1], nums.get(r[-1], 0)) for r in ns]
    attrs = REVIEW / ".plan_attrs"
    REVIEW.mkdir(exist_ok=True)
    attrs.write_text("*.py diff=python\n", encoding="utf-8")      # 함수 머리(@@ … def x)를 얻으려고
    diff = git("-c", "core.attributesFile=" + str(attrs), "diff", "-U0", base + "..HEAD")
    c = classify(changes, diff)
    if urgent and c["level"] == "skip":    # 긴급 릴리스는 생략하지 않는다(릴리스 SOT §2.1)
        c["level"] = "build"
        c["reasons"].append("긴급 릴리스 — 생략 후보라도 빌드 시험")
    u = unreleased()
    # 261010-10(릴리스 SOT §3.2): 릴리스에는 **마지막 릴리스 뒤 전부**가 나간다 — 그 사이 설치 관련 변경이 있었다면
    #   기준점(마지막 시험) 뒤에 없더라도 설치 시험. 빌드 시험 이상이 기준점 뒤에 통과했으면 빌드 쪽은 기준점으로 충분하다.
    if u["tag"] and c["level"] != "install":
        since = [l.split("	")[-1] for l in git("diff", "--name-status", u["tag"] + "..HEAD").splitlines() if l]
        inst = [p for p in since if p.startswith(INSTALL_PATHS)]
        if inst:
            c["level"] = "install"
            c["reasons"].append("마지막 릴리스 %s 뒤 설치 관련 변경: %s" % (u["tag"], ", ".join(inst)))
    dirty = [l for l in git("status", "--porcelain", "--untracked-files=no").splitlines() if l]
    name = {"install": "설치 시험", "build": "빌드 시험", "skip": "생략 후보 — 사용자에게 묻는다"}[c["level"]]
    cmd = {"install": "python scripts\\release_test.py install --source ci",
           "build": "python scripts\\release_test.py build --source local --rebuild", "skip": "(CI tests 성공만 확인)"}
    L = ["# 시험 계획 — %s" % source_version(), "",
         "- 기준점: `%s`%s" % (base[:9] if re.fullmatch(r"[0-9a-f]{10,}", base) else base, (" (%s, %s 통과)" % (bl.get("version"), bl.get("mode")) if bl and not base_arg else "")),
         "- 릴리스 종류: %s" % ("**긴급**" if urgent else "묶음"),
         "- **등급: %s** — `%s`" % (name, cmd[c["level"]])]
    L += ["  - " + r for r in c["reasons"]]
    if u["tag"]:
        due = u["count"] >= PENDING_COUNT or (u["count"] and u["days"] >= PENDING_DAYS)
        L.append("- 마지막 릴리스 `%s` 뒤 코드 커밋 %d건, 가장 오래된 것 %d일%s" % (
            u["tag"], u["count"], u["days"], " — **묶음 릴리스를 제안할 때**" if due else ""))
    if dirty:
        L.append("- ⚠ 커밋하지 않은 변경 %d개 — 판정은 커밋된 것만 본다" % len(dirty))
    L += ["", "## 기준점 이후 커밋", ""] + ["- " + l for l in git("log", "--oneline", base + "..HEAD").splitlines()]
    L += ["", "## 이번 변경과 관련된 항목", ""]
    L += ["- %s%s" % (w, " — `--cases %s`" % k if k else "") for w, k in c["focus"]] or ["- (경로로 고른 항목 없음 — 마스터 §0 행을 보고 손 확인 단계를 더한다)"]
    if not urgent:
        L += ["", "## 묶음 릴리스 — 최대 범위(릴리스 SOT §4.1)", "",
              "- 전체 검사: `python scripts\\release_test.py checks --ui` (CI 가 돌리지 않는 것까지 `test_*.py` 전부 + 화면 점검 ko·en)",
              "- 측정 묶음 전체(위 등급의 명령, `--cases` 없이)",
              "- 기능 점검표(릴리스 SOT §4.2) — 시험 프로필로 띄운 빌드본에서 주요 기능을 차례로"]
        if c["level"] == "skip":
            L.append("- 쌓인 변경이 미미하다 — 측정 묶음·기능 점검표를 건너뛸지 사용자에게 묻는다(전체 검사는 한다)")
    L += ["", "## 상시 항목", ""]
    if c["level"] == "skip":
        L.append("- 측정 묶음을 돌리지 않는다 — 정지·자식 남음·색인 속도는 이번 판에서 보지 않는다(못 한 것)")
    else:
        L += ["- 측정 묶음 전체: 대상마다 1초+ 정지 0 · 닫은 뒤 도우미 0 · 정상 종료",
              "- 기준점 결과와 자동 비교(창·열림 시간, 메모리, 색인한 파일 수 — 20% 넘게 나빠지면 '회귀 의심')",
              "- 끝난 뒤 실제 설정 폴더(`%APPDATA%\\LocalTools\\PolyPDF`)를 탐색기로 확인"]
    L += ["", "## 못 하는 것", "", "- 앱 안 업데이트(그 버전에서 다음 버전으로 올릴 때 처음 돈다)"]
    if c["level"] != "install":
        L.append("- 설치 프로그램(이번 판은 설치 관련 변경이 없다)")
    txt = "\n".join(L) + "\n"
    out = REVIEW / ("plan_%s_%s.md" % (source_version(), time.strftime("%y%m%d-%H%M")))
    out.write_text(txt, encoding="utf-8")
    say(txt + "\n계획: %s" % out)
    return 0


# ── 기준점 결과와 견주기(릴리스 SOT §4, 261010-4) — 판정은 바꾸지 않고 '회귀 의심' 만 적는다 ──
REGRESS = (   # (키, 이름, 나빠지는 쪽 +1=커짐, 절대 하한)
    ("t_window", "창", 1, 0.5), ("t_loaded", "열림", 1, 0.5), ("peak_ws_mb", "작업 집합", 1, 50),
    ("helper_max_ws_mb", "도우미", 1, 50), ("indexed_files", "색인한 파일", -1, 20),
)


def compare(rec: dict, base_rec: dict) -> list:
    old = {r["name"]: r for r in base_rec.get("runs", [])}
    rows = []
    for r in rec["runs"]:
        o = old.get(r["name"])
        if not o:
            continue
        for k, label, sign, floor in REGRESS:
            a, b = o.get(k), r.get(k)
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not a:
                continue
            worse = (b - a) * sign
            if worse > floor and worse / abs(a) > 0.20:
                rows.append("%s %s: %s → %s (%+.0f%%)" % (r["name"], label, a, b, (b - a) / abs(a) * 100))
    return rows


def save_baseline(rec: dict, out: Path):
    BASELINE.write_text(json.dumps({"commit": rec["commit"], "version": rec["version"], "mode": rec["mode"],
                                    "source": rec["source"], "result": out.name,
                                    "date": time.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False, indent=1),
                        encoding="utf-8")


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
    if rec.get("baseline"):
        L += ["", "기준점 `%s`(%s) 과 견줌: %s" % (rec["baseline"], rec.get("baseline_version", "?"),
                                              "회귀 의심 없음" if not rec.get("regress") else "**회귀 의심 %d건**" % len(rec["regress"]))]
        L += ["- " + x for x in rec.get("regress", [])]
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
    p = sub.add_parser("plan", help="기준점부터의 변경으로 시험 등급·확인 항목을 정한다(릴리스 SOT §3·§4)")
    p.add_argument("--base", help="기준점 커밋·태그(기본: 마지막으로 통과한 시험, _review/baseline.json)")
    p.add_argument("--urgent", action="store_true", help="긴급 릴리스(보안·데이터 손상·실행 불가·핵심 회귀) — 생략하지 않는다")
    p = sub.add_parser("checks", help="묶음 릴리스의 전체 검사 — test_*.py 전부(종료 코드로 판정)")
    p.add_argument("--ui", action="store_true", help="화면 점검(scripts/ui_check.py) ko·en 도")
    p.add_argument("--only", help="이름에 이 글자가 든 검사만(쉼표로 여럿) — 실패한 것 다시 보기")
    a = ap.parse_args()

    if a.mode == "checks":
        return checks(a.ui, a.only)
    if a.mode == "restore":
        restore_dir(Path(a.out))
        return 0
    if a.mode == "plan":
        return plan(a.base, a.urgent)
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
    bl = load_baseline()
    if bl and rec["runs"]:
        try:
            base_rec = json.loads((REVIEW / bl["result"] / "result.json").read_text(encoding="utf-8"))
            rec["baseline"], rec["baseline_version"] = bl["result"], bl.get("version")
            rec["regress"] = compare(rec, base_rec)
        except Exception as e:
            say("기준점 결과를 읽지 못했다:", e)
    write_summary(out, rec)
    # 묶음 전체를 돌려 통과했을 때만 기준점을 옮긴다(일부 대상·설치만 확인은 기준이 못 된다)
    full = not a.cases and not (a.mode == "install" and a.no_suite)
    if not rec["fail"] and full and rec["runs"]:
        save_baseline(rec, out)
        say("기준점 갱신:", BASELINE)
    return 0 if not rec["fail"] else 1


if __name__ == "__main__":
    sys.exit(main())

# release_test_suite.json 예시(공개 저장소 밖, <작업 폴더> 에):
# {"samples": "C:/My/PolyPDF/_samples",
#  "cases": [{"name": "T1_small", "target": "작은 문서.pdf", "seconds": 45},
#            {"name": "T5_std", "target": "PDF/기준 폴더", "seconds": 300, "clear_index": true}]}
