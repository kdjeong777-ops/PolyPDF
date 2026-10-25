# -*- coding: utf-8 -*-
"""오래 켜 두기 시험 — 같은 조작을 오래 되풀이하며 누수·예외·정지를 잰다 (릴리스 SOT §4.5, 261025-8).

측정 묶음(release_test.py)은 대상마다 1~5분, 부하 시험(load_test.py)은 조작 한 바퀴만 본다 — 사용자가 하루 종일 켜 두고
여러 문서를 오가며 쓸 때 쌓이는 것(메모리·핸들·GDI·스레드·자식 프로세스)과 드물게 나는 예외는 어느 쪽도 보지 못했다.

    .venv\\Scripts\\python.exe scripts/soak_test.py                    # 60분(SOAK_MINUTES) — 결과: <작업 폴더>\\_review\\soak_<버전>_<시각>\\summary.md
    .venv\\Scripts\\python.exe scripts/soak_test.py --minutes 5        # 도구 확인용 짧은 실행(판정에 쓰지 않는다)

- 개발 코드로 오프스크린 실행(load_test.py 와 같은 방식). 시험 모드 — 사용자 실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3).
- 한 바퀴: PDF 열기(측정 묶음 T1·T2·T3 차례로) → 쪽 넘기기 → 텍스트 창 보며 넘기기 → 검색 → 테마 왕복 → 트리·정렬 → (5바퀴마다) 폴더 다시 열기.
- 판정(값은 아래 상수 한 곳): 처음 `WARMUP_MINUTES` 뒤 표본부터 끝까지 전용 메모리 증가 < `LEAK_MB`, 핸들·GDI·USER·스레드 증가가
  한도 안(자식 프로세스 수 포함), 처리 안 된 예외 0, 조작 오류 0, 조작마다 최장 정지 < `STALL_LIMIT`. 정지 순간 메인 스레드 스택과
  자동 조작이 부른 모달 창을 summary 에 남긴다(모달은 받아 적고 '아니오·취소' 로 닫는다).
종료 코드: 0 통과, 1 실패.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import gc
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
PUBLIC = Path(__file__).resolve().parents[1]
WORK = PUBLIC.parent
sys.path.insert(0, str(PUBLIC))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SOAK_MINUTES = 60           # 사용자 결정(261025-8)
WARMUP_MINUTES = 10         # 이 뒤의 첫 표본을 기준으로 증가를 잰다(캐시·글꼴·첫 색인이 차는 동안은 늘어도 정상)
LEAK_MB = 50.0              # 사용자 결정(261025-8)
GROWTH_LIMITS = {"handles": 200, "gdi": 50, "user": 50, "threads": 10, "children": 1}   # 기준 표본에서 끝까지 늘어도 되는 개수
#   자식 프로세스(띄어쓰기 도우미·색인 자식)는 창 프로세스와 함께 끝난다 — 닫은 뒤 남지 않는지는 측정 묶음의 '도우미 남음'(release_test.py)이 본다.
#   이 시험은 한 프로세스 안이라 창을 닫아도 프로세스가 살아 있으므로, 도는 동안 자식이 쌓이지 않는지만 본다.
STALL_LIMIT = 1.0           # 응답성 SOT §5 통과 조건
STALL_DUMP_S = 0.8          # 박동이 이만큼 끊기면 메인 스레드 스택을 뜬다(정지 원인)
SAMPLE_S = 30.0
SEARCH_WORDS = ("도로", "asphalt", "기준", "pavement")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32")
k32.GetCurrentProcess.restype = wt.HANDLE
k32.GetProcessHandleCount.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.c_void_p]
k32.CloseHandle.argtypes = [wt.HANDLE]
u32.GetGuiResources.argtypes = [wt.HANDLE, wt.DWORD]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def _procs():
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    out = []
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.th32ParentProcessID, e.cntThreads, e.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def _descendants(procs, pid):
    kids, todo = [], [pid]
    while todo:
        p = todo.pop()
        for c in procs:
            if c[1] == p and c[0] != pid and c not in kids:
                kids.append(c)
                todo.append(c[0])
    return kids


def sample() -> dict:
    from load_test import private_mb
    h = k32.GetCurrentProcess()
    hc = wt.DWORD()
    k32.GetProcessHandleCount(h, ctypes.byref(hc))
    procs = _procs()
    me = os.getpid()
    mine = next((p for p in procs if p[0] == me), None)
    kids = _descendants(procs, me)
    return {"t": round(time.time(), 1), "private_mb": private_mb(), "handles": int(hc.value),
            "gdi": int(u32.GetGuiResources(h, 0)), "user": int(u32.GetGuiResources(h, 1)),
            "threads": int(mine[2]) if mine else -1, "py_threads": threading.active_count(),
            "children": len(kids), "children_names": sorted({k[3] for k in kids})}


def main():
    from load_test import suite_targets
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=float, default=SOAK_MINUTES)
    ap.add_argument("--warmup-minutes", type=float, default=None)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    warm = a.warmup_minutes if a.warmup_minutes is not None else min(WARMUP_MINUTES, a.minutes / 6)

    d = json.loads((WORK / "release_test_suite.json").read_text(encoding="utf-8"))
    base = Path(d.get("samples") or (WORK / "_samples"))
    cases = {c["name"][:2]: base / c["target"] for c in d.get("cases") or []}
    pdfs = [cases[k] for k in ("T1", "T2", "T3") if k in cases and cases[k].exists()]
    folder = cases.get("T4") if cases.get("T4") and cases["T4"].exists() else suite_targets()[0]

    from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
    QStandardPaths.setTestModeEnabled(True)
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QFont
    app = QApplication(sys.argv[:1])
    QCoreApplication.setApplicationName("polypdf_soak_%d" % os.getpid())
    app.setFont(QFont("Malgun Gothic", 9))
    from viewer import __version__ as ver
    out = Path(a.out) if a.out else WORK / "_review" / ("soak_%s_%s" % (ver, time.strftime("%y%m%d-%H%M")))
    out.mkdir(parents=True, exist_ok=True)

    excs = []

    def hook(et, ev, tb):
        excs.append("".join(traceback.format_exception(et, ev, tb)))
        print("!! 처리 안 된 예외:", et.__name__, ev, flush=True)
    sys.excepthook = hook

    # 모달 창은 오프스크린에서 영원히 멈춘다(마스터 §14.7.2 의 6) — 받아 적고 안전한 답(아니오·취소)으로 닫는다.
    #   첫 실행이 책갈피창이 파일 모드일 때 '트리 ↔ 단일' 의 안내 창에서 멈췄다(261025, 앱 결함 아님 — 사용자에게는 안내가 뜬다).
    from PyQt6.QtWidgets import QMessageBox
    modals = []

    def _modal(kind):
        def f(*args, **kw):
            txt = " / ".join(str(x) for x in args[1:3] if isinstance(x, str))
            modals.append((cur_op["name"], kind, txt[:160]))
            print("!! 모달 %s — %s: %s" % (kind, cur_op["name"], txt[:80]), flush=True)
            return QMessageBox.StandardButton.No if kind == "question" else QMessageBox.StandardButton.Ok
        return f
    for _k in ("information", "warning", "critical", "question"):
        setattr(QMessageBox, _k, staticmethod(_modal(_k)))
    QMessageBox.exec = lambda self: (modals.append((cur_op["name"], "exec", self.text()[:160])),
                                     QMessageBox.StandardButton.Cancel)[1]

    beat = {"last": time.perf_counter(), "max": 0.0}
    cur_op = {"name": "준비"}
    stall_stacks = []           # (조작, 정지 초, 메인 스레드 스택) — 정지 원인을 코드 줄로

    def tick():
        now = time.perf_counter()
        beat["max"] = max(beat["max"], now - beat["last"])
        beat["last"] = now
    hb = QTimer()
    hb.setInterval(20)
    hb.timeout.connect(tick)
    hb.start()

    main_id = threading.get_ident()

    def watchdog():             # 박동이 STALL_DUMP_S 넘게 끊기면 그 순간 메인 스레드 스택을 뜬다(정지마다 한 번)
        dumped = None
        while True:
            time.sleep(0.05)
            age = time.perf_counter() - beat["last"]
            if age > STALL_DUMP_S and dumped != beat["last"]:
                dumped = beat["last"]
                fr = sys._current_frames().get(main_id)
                st = "".join(traceback.format_stack(fr)[-14:]) if fr else "(스택 없음)"
                stall_stacks.append([cur_op["name"], round(age, 2), st])
    threading.Thread(target=watchdog, daemon=True).start()

    def spin(sec):
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < sec:
            app.processEvents()
            time.sleep(0.005)

    ops = {}            # 조작 이름 → {n, max_stall, errors, last_err}

    def op(name, fn, settle=0.5):
        spin(0.05)
        cur_op["name"] = name
        beat["last"] = time.perf_counter()
        beat["max"] = 0.0
        err = ""
        try:
            fn()
        except Exception as e:                   # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, e)
        spin(settle)
        tick()
        r = ops.setdefault(name, {"n": 0, "max_stall": 0.0, "stalls": 0, "errors": 0, "last_err": ""})
        r["n"] += 1
        r["max_stall"] = round(max(r["max_stall"], beat["max"]), 3)
        if beat["max"] >= STALL_LIMIT:
            r["stalls"] += 1
            print("!! 정지 %.2fs — %s" % (beat["max"], name), flush=True)
        if err:
            r["errors"] += 1
            r["last_err"] = err
            print("!! 조작 오류 — %s: %s" % (name, err), flush=True)

    from viewer.app import MainWindow
    mw = MainWindow()
    mw._skip_save_on_close = True
    mw.resize(1400, 900)
    mw.show()
    spin(1.0)
    bt = mw.bookmark_tree
    op("폴더 열기", lambda: mw.open_folder(str(folder)), settle=5.0)

    samples = [sample()]
    t_start = time.time()
    t_end = t_start + a.minutes * 60
    next_sample = t_start + SAMPLE_S
    cyc = 0
    print("오래 켜 두기 %.0f분 — 폴더 %s · PDF %d개" % (a.minutes, folder.name, len(pdfs)), flush=True)
    while time.time() < t_end:
        cyc += 1
        if pdfs:
            pdf = pdfs[cyc % len(pdfs)]
            op("PDF 열기", lambda: mw.open_pdf(Path(pdf)), settle=1.5)
            mv = mw.main_view

            def flip(n):
                if mv._doc is None:
                    return
                pc = mv._doc.page_count
                for k in range(n):
                    mv.go_to_page((mv.current_page() + 1) % pc)
                    app.processEvents()
            op("쪽 넘기기 ×20", lambda: flip(20))
            op("맨 끝·맨 앞", lambda: (mv.go_to_page(10 ** 6), app.processEvents(), mv.go_to_page(0)))
            prev_tab = mw.search_tabs.currentWidget()
            op("텍스트 창 보기", lambda: (mw.search_tabs.setCurrentWidget(mw.text_panel), mw._reload_text_panel()), settle=1.0)
            op("텍스트 창 보며 넘기기 ×5", lambda: [(flip(1), mw._reload_text_panel()) for _ in range(5)], settle=1.0)
            op("텍스트 창 닫기", lambda: mw.search_tabs.setCurrentWidget(prev_tab))
        word = SEARCH_WORDS[cyc % len(SEARCH_WORDS)]
        op("검색", lambda: mw.action_search(word), settle=2.0)
        op("테마 → 다크", lambda: mw.apply_theme("dark"))
        op("테마 → 밝게", lambda: mw.apply_theme("light"))
        if bt._sort_combo.count():
            op("정렬 바꾸기", lambda: bt._sort_combo.setCurrentIndex(cyc % bt._sort_combo.count()))
        if cyc % 5 == 0:
            op("폴더 다시 열기", lambda: mw.open_folder(str(folder)), settle=3.0)
            if bt._mode == "flat":    # 폴더 목록일 때만 — PDF 를 연 뒤(파일 모드)에는 앱이 안내 창만 띄운다
                op("트리 ↔ 단일", lambda: (bt._toggle_tree_view(), app.processEvents(), bt._toggle_tree_view()))
        if time.time() >= next_sample:
            gc.collect()
            s = sample()
            s["cycle"] = cyc
            samples.append(s)
            next_sample = time.time() + SAMPLE_S
            print("[%5.1f분] 바퀴 %d · 전용 %.1fMB · 핸들 %d · GDI %d · USER %d · 스레드 %d · 자식 %d · 예외 %d" % (
                (time.time() - t_start) / 60, cyc, s["private_mb"], s["handles"], s["gdi"], s["user"],
                s["threads"], s["children"], len(excs)), flush=True)

    gc.collect()
    spin(1.0)
    last = sample()
    last["cycle"] = cyc
    samples.append(last)
    # 기준 표본: 예열 시간이 지난 첫 표본
    t_warm = t_start + warm * 60
    basis = next((s for s in samples if s["t"] >= t_warm), samples[0])
    growth = {k: last[k] - basis[k] for k in ("private_mb", "handles", "gdi", "user", "threads", "children")}
    left = [(0, 0, 0, n) for n in last["children_names"]]

    stall_bad = {k: v for k, v in ops.items() if v["stalls"]}
    err_bad = {k: v for k, v in ops.items() if v["errors"]}
    verdict = {
        "메모리 증가 < %.0fMB" % LEAK_MB: growth["private_mb"] < LEAK_MB,
        **{"%s 증가 ≤ %d" % (k, lim): growth[k] <= lim for k, lim in GROWTH_LIMITS.items()},
        "처리 안 된 예외 0": not excs,
        "조작 오류 0": not err_bad,
        "정지 < %.0f초" % STALL_LIMIT: not stall_bad,
    }
    ok = all(verdict.values()) and a.minutes >= SOAK_MINUTES
    L = ["# 오래 켜 두기 시험 — %s" % ver, "",
         "- 시간 %.1f분(예열 %.1f분) · %d바퀴 · 폴더 `%s` · PDF %s" % (
             (last["t"] - t_start) / 60, warm, cyc, folder.name, ", ".join("`%s`" % p.name for p in pdfs)),
         "- 기준 표본(예열 뒤 첫 표본) → 끝: 전용 %.1f → %.1fMB · 핸들 %d → %d · GDI %d → %d · USER %d → %d · 스레드 %d → %d" % (
             basis["private_mb"], last["private_mb"], basis["handles"], last["handles"], basis["gdi"], last["gdi"],
             basis["user"], last["user"], basis["threads"], last["threads"]),
         "- 시작 전용 메모리 %.1fMB · 최대 %.1fMB" % (samples[0]["private_mb"], max(s["private_mb"] for s in samples)),
         "- 자식 프로세스: 기준 %d → 끝 %d (%s) · 도는 동안 최대 %d — 닫은 뒤 남는지는 측정 묶음이 본다" % (
             basis["children"], last["children"], ", ".join(x[3] for x in left) or "없음",
             max(s["children"] for s in samples)),
         ""]
    if a.minutes < SOAK_MINUTES:
        L.append("> 짧은 실행(%.0f분 < SOAK_MINUTES %d분) — 도구 확인용, 판정에 쓰지 않는다." % (a.minutes, SOAK_MINUTES))
        L.append("")
    L += ["| 기준 | 결과 |", "| --- | --- |"]
    L += ["| %s | %s |" % (k, "통과" if v else "**실패**") for k, v in verdict.items()]
    L += ["", "| 조작 | 횟수 | 최장 정지 | 1초+ | 오류 |", "| --- | --- | --- | --- | --- |"]
    L += ["| %s | %d | %.3fs | %d | %d%s |" % (k, v["n"], v["max_stall"], v["stalls"], v["errors"],
                                               (" — " + v["last_err"][:80]) if v["last_err"] else "")
          for k, v in ops.items()]
    if excs:
        L += ["", "## 처리 안 된 예외(%d)" % len(excs), "", "```", excs[0][-2000:], "```"]
    if modals:
        L += ["", "## 뜬 모달 창(%d) — 자동 조작이 부른 안내·확인. 결함인지 사람이 본다" % len(modals), ""]
        L += ["- %s · %s · %s" % m for m in modals[:20]]
    if stall_stacks:
        L += ["", "## 정지 순간 메인 스레드 스택(%d, %.1f초+)" % (len(stall_stacks), STALL_DUMP_S)]
        for o, sec, st in stall_stacks[:8]:
            L += ["", "### %s — %.2f초+" % (o, sec), "", "```", st.rstrip(), "```"]
    L += ["", "**판정: %s**" % ("통과" if ok else "실패")]
    (out / "summary.md").write_text("\n".join(L), encoding="utf-8")
    (out / "samples.json").write_text(json.dumps({"version": ver, "samples": samples, "ops": ops, "growth": growth,
                                                  "verdict": verdict, "exceptions": excs, "modals": modals,
                                                  "stall_stacks": stall_stacks, "ok": ok},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(L[-1:]))
    print("결과:", out / "summary.md", flush=True)
    sys.stdout.flush()
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
