# -*- coding: utf-8 -*-
"""설치본 안정성·속도 측정 — 응답성 SOT §7.3·§7.4·§7.5 의 방법을 설치본에 그대로 (261009-13).

설치된 PolyPDF.exe 를 **밖에서** 띄우고 재기만 한다(앱 코드를 바꾸지 않는다):
  - 창이 뜨기까지·대상이 열리기까지(창 제목에 대상 이름이 나올 때)의 시간
  - **응답 지연**: 창에 `WM_NULL` 을 보내 돌아오기까지의 시간(`SendMessageTimeout`, 250ms 마다) — 메인 스레드가
    붙잡힌 시간 그대로다. 1초 넘으면 지연으로 세고(SOT §5 판정 < 1초) 그때 `py-spy dump` 스택을 남긴다.
    Windows '응답 없음'(`IsHungAppWindow`)은 5초가 지나야 참이라 1~4초 정지를 놓친다 — 함께 기록만 한다.
  - 메모리(작업 집합·최대 작업 집합·전용 바이트)와 CPU 사용률(1초 간격)
  - 정해진 시간이 지나면 창에 WM_CLOSE 로 정상 종료(안 닫히면 강제)

대상을 여는 길은 사용자가 쓰는 길 그대로다:
  - PDF 파일: 명령줄 인자(탐색기에서 '연결 프로그램' 으로 여는 것과 같다)
  - 폴더: 환경설정 '시작 시 동작 — 지정한 폴더·파일 열기'(settings.json `startup_mode=path`)

★ 설치본은 **사용자 실제 설정 폴더**(%APPDATA%\\LocalTools\\PolyPDF)를 쓴다(마스터 §14.2.1).
  이 스크립트는 `--backup` 으로 설정·색인을 통째로 백업하고 `--restore` 로 되돌린다 — 측정 전후에 꼭 쓴다.

사용:
  python scripts/probe_installed.py --backup  DIR
  python scripts/probe_installed.py --clear-index                       (빈 색인 — 최악 조건 §7.5)
  python scripts/probe_installed.py --run NAME --target PATH --seconds 90 --out DIR
  python scripts/probe_installed.py --restore DIR
"""
import argparse, ctypes, ctypes.wintypes as wt, json, os, shutil, subprocess, sys, time
from pathlib import Path

EXE = Path(os.environ.get("POLYPDF_EXE", r"C:\Program Files\PolyPDF\PolyPDF.exe"))
CFG = Path(os.environ["APPDATA"]) / "LocalTools" / "PolyPDF"
# 백업에서 빼는 것: 받아 둔 업데이트 zip(300MB)·실행 중 인스턴스 표식
SKIP = {"PolyPDF-update.zip", "instances"}
INDEX = ("index.db", "index.db-wal", "index.db-shm")

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]


def _mem(h):
    m = PMC(); m.cb = ctypes.sizeof(PMC)
    if psapi.GetProcessMemoryInfo(h, ctypes.byref(m), m.cb):
        return {"ws_mb": m.WorkingSetSize / 2**20, "peak_ws_mb": m.PeakWorkingSetSize / 2**20,
                "private_mb": m.PrivateUsage / 2**20}
    return {}


def _cpu_time(h):
    c, e, k, u = (wt.FILETIME() for _ in range(4))
    if k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
        f = lambda t: (t.dwHighDateTime << 32 | t.dwLowDateTime) / 1e7
        return f(k) + f(u)
    return 0.0


def _windows_of(pid):
    out = []
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            n = u32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            out.append((hwnd, buf.value))
        return True
    u32.EnumWindows(cb, 0)
    return out


def _main_window(pid):
    """메인 창 = 제목에 버전이 있는 창('PolyPDF  v0.45…'). 인덱싱 진행 창('PolyPDF — 폴더 준비')도
    'PolyPDF' 로 시작하므로 그것을 잡으면 열림 판정·WM_CLOSE 가 엉뚱한 창으로 간다(261009-13 T6 에서 겪음)."""
    wins = _windows_of(pid)
    for hwnd, title in wins:
        if title.startswith("PolyPDF") and " v" in title:
            return hwnd, title
    return None, ""


def _pyspy(pid, path):
    exe = shutil.which("py-spy") or str(Path(sys.executable).parent / "py-spy.exe")
    try:
        r = subprocess.run([exe, "dump", "--pid", str(pid), "--nonblocking"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=20)
        path.write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
    except Exception as e:
        path.write_text("py-spy 실패: %r" % e, encoding="utf-8")


def _set_startup(target):
    """폴더는 '지정한 폴더·파일 열기' 로 연다 — settings.json 은 UTF-8(한글)이라 json 으로 읽고 쓴다."""
    f = CFG / "settings.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    pr = d.setdefault("preferences", {})
    pr["startup_mode"] = "path"
    pr["startup_path"] = str(target)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def run(name, target, seconds, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    target = Path(target)
    args = [str(EXE)]
    if target.is_file():
        args.append(str(target))
    else:
        _set_startup(target)
    t0 = time.perf_counter()
    proc = subprocess.Popen(args)
    PROCESS_QUERY = 0x1000 | 0x0010   # QUERY_LIMITED_INFORMATION | VM_READ
    h = k32.OpenProcess(PROCESS_QUERY, False, proc.pid)
    rec = {"name": name, "target": str(target), "kind": "file" if target.is_file() else "folder",
           "t_window": None, "t_loaded": None, "hangs": [], "samples": [], "exit": None}
    key = target.name
    last_cpu, last_t = _cpu_time(h), time.perf_counter()
    next_sample = last_t + 1.0
    hwnd = None
    try:
        while time.perf_counter() - t0 < seconds:
            if proc.poll() is not None:
                rec["exit"] = "프로세스가 먼저 끝남(코드 %s)" % proc.returncode
                break
            now = time.perf_counter()
            if hwnd is None or not u32.IsWindow(hwnd):
                hwnd, title = _main_window(proc.pid)
                if hwnd and rec["t_window"] is None:
                    rec["t_window"] = round(now - t0, 2)
            if hwnd:
                n = u32.GetWindowTextLengthW(hwnd); buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, buf, n + 1)
                if rec["t_loaded"] is None and key and key in buf.value:
                    rec["t_loaded"] = round(now - t0, 2)
                rec["title"] = buf.value
                if u32.IsHungAppWindow(hwnd):
                    rec["os_hung"] = rec.get("os_hung", 0) + 1
                # WM_NULL 왕복 — 1초 안에 안 오면 스택을 뜨고(정지 중) 끝까지 기다려 길이를 잰다(최대 30초)
                res = ctypes.c_size_t()
                t_s = time.perf_counter()
                ok = u32.SendMessageTimeoutW(hwnd, 0x0000, 0, 0, 0x0000, 1000, ctypes.byref(res))
                if not ok:
                    n_h = len(rec["hangs"]) + 1
                    _pyspy(proc.pid, out / ("%s_stall%d.txt" % (name, n_h)))
                    u32.SendMessageTimeoutW(hwnd, 0x0000, 0, 0, 0x0000, 30000, ctypes.byref(res))
                lat = time.perf_counter() - t_s
                rec["max_latency"] = max(rec.get("max_latency", 0.0), round(lat, 3))
                if lat >= 1.0:
                    rec["hangs"].append({"at": round(t_s - t0, 2), "sec": round(lat, 2)})
                now = time.perf_counter()
            if now >= next_sample:
                cpu = _cpu_time(h)
                pct = 100.0 * (cpu - last_cpu) / max(1e-6, now - last_t) / (os.cpu_count() or 1)
                last_cpu, last_t = cpu, now
                s = {"t": round(now - t0, 1), "cpu_pct": round(pct, 1)}
                s.update({k: round(v, 1) for k, v in _mem(h).items()})
                rec["samples"].append(s)
                next_sample = now + 1.0
            time.sleep(0.25)
        # 정상 종료: WM_CLOSE → 10초 기다림 → 안 닫히면 강제
        if proc.poll() is None:
            if hwnd:
                u32.PostMessageW(hwnd, 0x0010, 0, 0)
            t_close = time.perf_counter()
            try:
                proc.wait(timeout=15)
                rec["close_sec"] = round(time.perf_counter() - t_close, 2)
            except subprocess.TimeoutExpired:
                _pyspy(proc.pid, out / ("%s_close.txt" % name))
                proc.kill(); rec["close_sec"] = None; rec["exit"] = "닫히지 않아 강제 종료"
    finally:
        k32.CloseHandle(h)
    sm = rec["samples"]
    rec["peak_ws_mb"] = max((s.get("peak_ws_mb", 0) for s in sm), default=None)
    rec["max_private_mb"] = max((s.get("private_mb", 0) for s in sm), default=None)
    busy = [s["t"] for s in sm if s["cpu_pct"] > 5]
    rec["cpu_busy_until"] = busy[-1] if busy else None
    rec["max_hang_sec"] = max((x["sec"] for x in rec["hangs"]), default=0)
    (out / ("%s.json" % name)).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print("%-14s 창 %5ss · 열림 %5ss · 1초+ 지연 %d회(최장 %ss) · 최대 작업집합 %sMB · 전용 %sMB · CPU 바쁨~%ss · 닫기 %ss %s"
          % (name, rec["t_window"], rec["t_loaded"], len(rec["hangs"]), rec["max_hang_sec"], round(rec["peak_ws_mb"] or 0),
             round(rec["max_private_mb"] or 0), rec["cpu_busy_until"], rec.get("close_sec"), rec["exit"] or ""))
    return rec


def backup(dst):
    dst = Path(dst)
    if dst.exists():
        raise SystemExit("백업 폴더가 이미 있다(덮지 않는다): %s" % dst)
    shutil.copytree(CFG, dst, ignore=lambda d, names: [n for n in names if n in SKIP and Path(d) == CFG])
    print("백업 →", dst)


def restore(src):
    """백업에 있던 파일은 되돌리고, 시험 중 새로 생긴 파일(SKIP 제외)은 지운다."""
    src = Path(src)
    for p in CFG.iterdir():
        if p.name in SKIP:
            continue
        if not (src / p.name).exists():
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    for p in src.iterdir():
        d = CFG / p.name
        if p.is_dir():
            shutil.copytree(p, d, dirs_exist_ok=True)       # 덮어쓰기(폴더를 지우고 다시 만들면 잠긴 파일에서 멈춘다)
        else:
            shutil.copy2(p, d)
    print("복원 ←", src)


def clear_index():
    for n in INDEX:
        f = CFG / n
        if f.exists():
            f.unlink()
    print("색인 비움:", ", ".join(INDEX))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup"); ap.add_argument("--restore"); ap.add_argument("--clear-index", action="store_true")
    ap.add_argument("--run"); ap.add_argument("--target"); ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    if a.backup:
        backup(a.backup)
    elif a.restore:
        restore(a.restore)
    elif a.clear_index:
        clear_index()
    elif a.run:
        r = run(a.run, a.target, a.seconds, a.out)
        sys.exit(0 if (r["max_hang_sec"] or 0) < 1.0 and not r["exit"] else 1)
    else:
        ap.print_help()
