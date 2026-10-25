# -*- coding: utf-8 -*-
"""정식판 점검 — 크래시 근거·데이터 무결성·새 프로필 첫 실행·업데이트 채널을 한 곳에 모은다 (릴리스 SOT §4.5, 261025-8).

    python scripts/stable_check.py snapshot --out <폴더>            # 시작 전: 사용자 실제 폴더 상태(읽기만)와 시작 시각
    python scripts/stable_check.py fresh --exe <PolyPDF.exe> --out <폴더>   # 빈 시험 프로필로 첫 실행 → 닫기 → 프로필 확인·지우기
    python scripts/stable_check.py report --out <폴더> [--online]   # 끝난 뒤: 시작 시각 이후의 크래시·예외, 무결성, 실제 폴더 전후

- 사용자 실제 설정 폴더(`%APPDATA%\\LocalTools\\PolyPDF`)는 **읽기만** 한다 — 무결성은 index.db 를 작업 폴더로 **복사해서** 본다
  (WAL 색인은 읽기 전용으로 열어도 `-shm` 을 건드릴 수 있다). 시험 프로필(`PolyPDF-<이름>`)만 쓰고 지운다(마스터 §14.2.1).
- 크래시 근거: Windows 이벤트 로그(응용 프로그램 오류 1000·정지 1002 — `PolyPDF.exe`), 시험 프로필들의 `error.log`(처리 안 된 예외·
  설정 읽기 실패·색인 초기화)와 `crash.log`(네이티브 크래시, 마스터 §14.7.3) — 시작 시각 이후 것만 센다.
종료 코드: 0 통과, 1 실패(report·fresh), 2 사용법.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1]
WORK = PUBLIC.parent
LT = Path(os.environ["APPDATA"]) / "LocalTools"
REAL = LT / "PolyPDF"                          # 사용자 실제 설정 — 읽기만
WATCH = ("settings.json", "index.db", "index.db-wal", "error.log", "crash.log")
FRESH_SECONDS = 30                             # 새 프로필 첫 실행을 지켜보는 시간
ENTRY = re.compile(r"^--- (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
START = re.compile(r"^=== 시작 (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
FATAL = re.compile(r"Fatal Python error|Windows fatal exception")
# 261026-4: Windows 의 faulthandler 는 오류 등급 SEH 를 **모두** 적는다 — 처리되는 첫 기회 예외까지. Word COM 변환 중 RPC 런타임이
#   스스로 던지고 받는 0x800706be(호출 실패)·0x800706ba(서버 없음)가 1.0.0 설치본 crash.log 에 4건 '치명' 으로 적혔지만 앱은 계속 돌았다
#   (이벤트 로그 크래시 0). 그래서 프로세스를 실제로 끝내는 코드만 치명으로 센다 — 나머지(0x8xxxxxxx 등)는 '참고'.
FATAL_CODES = {"0xc0000005", "0xc0000409", "0xc00000fd", "0xc0000374", "0xc000001d", "0xc0000094", "0xc0000096",
               "0xc0000417", "0xc0000602"}
_CODE = re.compile(r"Windows fatal exception: (?:code )?(0x[0-9a-fA-F]+|access violation|stack overflow)", re.I)


def is_fatal_line(line: str) -> bool:
    """crash.log 한 줄이 진짜 크래시인지 — `Fatal Python error` 는 늘 치명, Windows 예외는 코드로 가린다."""
    if "Fatal Python error" in line:
        return True
    m = _CODE.search(line)
    if not m:
        return False
    c = m.group(1).lower()
    return c in FATAL_CODES or c in ("access violation", "stack overflow")


def stat_real() -> dict:
    out = {}
    for n in WATCH:
        p = REAL / n
        try:
            s = p.stat()
            out[n] = {"size": s.st_size, "mtime": datetime.fromtimestamp(s.st_mtime).strftime("%Y-%m-%d %H:%M:%S")}
        except OSError:
            out[n] = None
    return out


def check_db_copy(db: Path, full: bool = False) -> str:
    """색인을 임시 폴더로 복사해(-wal 포함) 무결성을 본다 — 원본은 읽기만."""
    if not db.exists():
        return "없음"
    tmp = Path(tempfile.mkdtemp(prefix="polypdf_dbcheck_"))
    try:
        for suf in ("", "-wal"):
            if Path(str(db) + suf).exists():
                shutil.copy2(str(db) + suf, tmp / ("index.db" + suf))
        con = sqlite3.connect(str(tmp / "index.db"))
        try:
            t = time.perf_counter()
            r = con.execute("PRAGMA %s(1)" % ("integrity_check" if full else "quick_check")).fetchone()[0]
            n = con.execute("select count(*) from files").fetchone()[0] if r == "ok" else -1
            return "%s (%.1f초, 파일 %d개, %.0fMB)" % (r.replace("\n", " "), time.perf_counter() - t, n, db.stat().st_size / 2**20)
        finally:
            con.close()
    except Exception as e:      # noqa: BLE001
        return "확인 실패: %s: %s" % (type(e).__name__, e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def log_entries(p: Path, since: str) -> list:
    """error.log 의 `--- 시각` 항목 중 since 이후 것 — (시각, 첫 줄 요약)."""
    if not p.exists():
        return []
    out, cur = [], None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = ENTRY.match(line)
        if m:
            cur = [m.group(1), ""]
            if cur[0] >= since:
                out.append(cur)
            continue
        if cur is not None and cur[0] >= since and line.strip() and not line.startswith(("Traceback", "  ")):
            cur[1] = cur[1] or line.strip()[:160]
    return [tuple(x) for x in out]


def crash_entries(p: Path, since: str, fatal: bool = True) -> list:
    """crash.log 에서 since 이후 시작한 실행의 예외 줄 — fatal=True 면 진짜 크래시만, False 면 비치명(첫 기회 SEH)만."""
    if not p.exists():
        return []
    out, run = [], ""
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = START.match(line)
        if m:
            run = m.group(1)
        elif FATAL.search(line) and run >= since and is_fatal_line(line) == fatal:
            out.append((run, line.strip()[:160]))
    return out


def event_crashes(since: str) -> list:
    ps = ("$s=[datetime]'%s'; Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000,1002; StartTime=$s} "
          "-ErrorAction SilentlyContinue | Where-Object { $_.Message -match 'PolyPDF\\.exe' } | ForEach-Object { "
          "$_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss') + ' | ' + $_.Id + ' | ' + (($_.Message -split \"`n\")[0..3] -join ' ; ') }") % since
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return [x.strip() for x in r.stdout.splitlines() if x.strip()]


def cmd_snapshot(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    rec = {"since": time.strftime("%Y-%m-%d %H:%M:%S"), "real_before": stat_real()}
    (out / "stable_snapshot.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print("시작 시각", rec["since"])
    for k, v in rec["real_before"].items():
        print("  실제 폴더 %-14s %s" % (k, v))
    return 0


def cmd_fresh(exe: Path, out: Path) -> int:
    """빈 시험 프로필로 첫 실행 — 설정 파일이 없는 사용자(첫 설치)의 길."""
    out.mkdir(parents=True, exist_ok=True)
    prof = "fresh%s" % time.strftime("%H%M%S")
    cfg = LT / ("PolyPDF-" + prof)
    if cfg.exists():
        shutil.rmtree(cfg)
    d = json.loads((WORK / "release_test_suite.json").read_text(encoding="utf-8"))
    base = Path(d.get("samples") or (WORK / "_samples"))
    t1 = next((base / c["target"] for c in d["cases"] if c["name"].startswith("T1")), None)
    env = dict(os.environ, POLYPDF_TEST_PROFILE=prof, POLYPDF_EXE=str(exe))
    since = time.strftime("%Y-%m-%d %H:%M:%S")
    r = subprocess.run([sys.executable, str(PUBLIC / "scripts" / "probe_installed.py"), "--run", "fresh_T1",
                        "--target", str(t1), "--seconds", str(FRESH_SECONDS), "--out", str(out)], env=env)
    rec = json.loads((out / "fresh_T1.json").read_text(encoding="utf-8")) if (out / "fresh_T1.json").exists() else {}
    files = sorted(p.name for p in cfg.iterdir()) if cfg.exists() else []
    try:
        s = json.loads((cfg / "settings.json").read_text(encoding="utf-8"))
        settings_ok = isinstance(s, dict) and "schema_version" in s
    except Exception as e:      # noqa: BLE001
        settings_ok, s = False, str(e)
    errs = log_entries(cfg / "error.log", since)
    fatal = crash_entries(cfg / "crash.log", since)
    ok = (r.returncode == 0 and rec.get("t_window") is not None and settings_ok and not errs and not fatal
          and not rec.get("helper_left"))
    L = ["## 새 프로필 첫 실행 — `%s`" % exe, "",
         "- 창 %ss · 대상 열림 %ss · 정지 %d번(최장 %ss) · 닫기 %ss · 도우미 남음 %s · 끝 %s" % (
             rec.get("t_window"), rec.get("t_loaded"), len(rec.get("hangs") or []), rec.get("max_hang_sec"),
             rec.get("close_sec"), rec.get("helper_left"), rec.get("exit") or "정상"),
         "- 만든 파일: %s" % (", ".join(files) or "없음"),
         "- settings.json: %s · error.log 새 항목 %d · crash.log 치명 %d" % ("정상" if settings_ok else "**읽기 실패**", len(errs), len(fatal))]
    L += ["  - error.log %s %s" % e for e in errs] + ["  - crash.log %s %s" % e for e in fatal]
    L += ["", "**판정: %s**" % ("통과" if ok else "실패"), ""]
    (out / "stable_fresh.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    shutil.rmtree(cfg, ignore_errors=True)
    return 0 if ok else 1


def cmd_report(out: Path, online: bool) -> int:
    snap = json.loads((out / "stable_snapshot.json").read_text(encoding="utf-8"))
    since = snap["since"]
    after = stat_real()
    ev = event_crashes(since)
    prof_rows, bad = [], []
    for cfg in sorted(LT.glob("PolyPDF-*")):
        if not cfg.is_dir():
            continue
        errs = log_entries(cfg / "error.log", since)
        fatal = crash_entries(cfg / "crash.log", since)
        db = check_db_copy(cfg / "index.db") if (cfg / "index.db").exists() else "없음"
        try:
            json.loads((cfg / "settings.json").read_text(encoding="utf-8")) if (cfg / "settings.json").exists() else None
            sj = "정상" if (cfg / "settings.json").exists() else "없음"
        except Exception:      # noqa: BLE001
            sj = "**읽기 실패**"
        prof_rows.append((cfg.name, len(errs), len(fatal), sj, db, errs, fatal))
        if errs or fatal or sj.startswith("**") or not (db == "없음" or db.startswith("ok")):
            bad.append(cfg.name)
    real_db = check_db_copy(REAL / "index.db")
    real_fatal = crash_entries(REAL / "crash.log", since)                    # 읽기만
    real_noise = crash_entries(REAL / "crash.log", since, fatal=False)
    L = ["## 크래시 근거·데이터 무결성 (%s 이후)" % since, "",
         "| 항목 | 결과 |", "| --- | --- |",
         "| 이벤트 로그 PolyPDF.exe 오류·정지 | %s |" % ("없음" if not ev else "**%d건**" % len(ev)),
         "| 사용자 실제 crash.log 치명(`FATAL_CODES`) | %s |" % ("없음" if not real_fatal else "**%d건**" % len(real_fatal)),
         "| 사용자 실제 crash.log 비치명(처리된 첫 기회 SEH — COM/RPC 0x8007xxxx 등, 참고) | %d건%s |" % (
             len(real_noise), (" — " + "; ".join("%s %s" % x for x in real_noise[:3])) if real_noise else ""),
         "| 사용자 실제 색인(복사본) quick_check | %s |" % real_db, ""]
    L += ["- crash.log 치명 %s %s" % x for x in real_fatal]
    L += ["- " + e for e in ev]
    L += ["", "| 시험 프로필 | error.log 새 항목 | crash.log 치명 | settings.json | index.db quick_check(복사본) |",
          "| --- | --- | --- | --- | --- |"]
    for name, ne, nf, sj, db, errs, fatal in prof_rows:
        L.append("| %s | %d | %d | %s | %s |" % (name, ne, nf, sj, db))
    for name, ne, nf, sj, db, errs, fatal in prof_rows:
        for e in errs:
            L.append("- `%s` error.log %s — %s" % (name, e[0], e[1]))
        for e in fatal:
            L.append("- `%s` crash.log %s — %s" % (name, e[0], e[1]))
    L += ["", "| 사용자 실제 폴더 | 시작 전 | 끝난 뒤 |", "| --- | --- | --- |"]
    for k in WATCH:
        b, a = snap["real_before"].get(k), after.get(k)
        fmt = lambda v: "-" if not v else "%s B · %s" % (format(v["size"], ","), v["mtime"])
        L.append("| %s | %s | %s%s |" % (k, fmt(b), fmt(a), "" if b == a else " ← 바뀜"))
    L.append("")
    L.append("> 실제 폴더가 바뀌었으면 시험 도구가 아니라 사용자가 그동안 PolyPDF 를 썼는지 먼저 본다(시험은 시험 프로필만 쓴다).")
    if online:
        sys.path.insert(0, str(PUBLIC))
        from viewer import updater
        for ch in ("beta", "stable"):
            info = updater.check_latest("kdjeong777-ops/PolyPDF", channel=ch) or {}
            L.append("- 업데이트 확인(지금 판 %s, %s 채널): 새 판 `%s` · 자산 %s" % (
                updater.current_version(), ch, info.get("tag"), "있음" if info.get("asset_url") else "없음"))
    ok = not ev and not bad and not real_fatal and real_db.startswith(("ok", "없음"))
    L += ["", "**판정: %s**" % ("통과" if ok else "실패")]
    (out / "stable_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    return 0 if ok else 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    for c in ("snapshot", "fresh", "report"):
        p = sub.add_parser(c)
        p.add_argument("--out", required=True)
        if c == "fresh":
            p.add_argument("--exe", required=True)
        if c == "report":
            p.add_argument("--online", action="store_true", help="GitHub 릴리스 목록으로 두 채널의 새 판을 본다(읽기만)")
    a = ap.parse_args()
    if a.cmd == "snapshot":
        return cmd_snapshot(Path(a.out))
    if a.cmd == "fresh":
        return cmd_fresh(Path(a.exe), Path(a.out))
    if a.cmd == "report":
        return cmd_report(Path(a.out), a.online)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
