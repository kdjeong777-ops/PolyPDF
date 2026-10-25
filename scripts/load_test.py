# -*- coding: utf-8 -*-
"""부하 시험 — 큰 폴더를 색인하는 **동안** 화면 조작마다 메인 스레드 최장 정지를 잰다 (응답성 SOT §7, 릴리스 SOT §4.1).

측정 묶음(release_test.py build/install)은 '열고 기다리기' 만 잰다 — 사용자가 색인 중에 테마를 바꾸거나 정렬·보기를 바꿀 때의
정지는 잡지 못했다(261011-7: 색인 중 다크 전환 47초 '응답 없음' 이 측정 묶음을 통과한 뒤 사용자에게서 나왔다). 이 시험이 그 빈칸이다.

    .venv\\Scripts\\python.exe scripts/load_test.py            # 결과: <작업 폴더>\\_review\\load_<버전>_<시각>\\summary.md
    .venv\\Scripts\\python.exe scripts/load_test.py --theme-rounds 80

- 개발 코드로 오프스크린 실행한다(빌드본이 아니다) — 조작 경로의 알고리즘 문제(행 수의 제곱 등)를 잡는 것이 목적.
- 대상은 `release_test_suite.json` 의 가장 큰 폴더(`clear_index` 대상 중 마지막)와 가장 큰 PDF(`T3` 또는 첫 PDF 대상).
- 색인을 비우고 연다 → 색인 자식 프로세스가 도는 동안 조작한다(시작·끝 색인 파일 수를 적는다 — 부하가 실제로 있었는지).
- 박동: 20ms QTimer 의 간격 최댓값 = 조작 중 메인 정지. 판정 **모든 조작 < 1초**, 테마 왕복 뒤 전용 메모리 증가 < 20MB.
- 시험 프로필(`QStandardPaths` 테스트 모드) — 사용자 실제 설정 폴더를 건드리지 않는다.
- 261025-12: 다른 무거운 작업(다른 검사·빌드·측정)과 겹쳤으면 판정 '보류'(`scripts/overlap.py`, 릴리스 SOT §4.3 의 8).
종료 코드: 0 통과, 1 실패, 3 보류(겹침 — 다시 잰다).
"""
import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
PUBLIC = Path(__file__).resolve().parents[1]
WORK = PUBLIC.parent
sys.path.insert(0, str(PUBLIC))
STALL_LIMIT = 1.0           # 응답성 SOT §5 통과 조건
LEAK_LIMIT_MB = 20.0


def suite_targets():
    d = json.loads((WORK / "release_test_suite.json").read_text(encoding="utf-8"))
    base = Path(d.get("samples") or (WORK / "_samples"))
    cases = d.get("cases") or []
    folders = [c for c in cases if c.get("clear_index")]
    folder = base / (folders[-1]["target"] if folders else cases[-1]["target"])
    pdfs = [c for c in cases if str(c.get("target", "")).lower().endswith(".pdf")]
    big = next((c for c in pdfs if c["name"].startswith("T3")), pdfs[0] if pdfs else None)
    return folder, (base / big["target"]) if big else None


def private_mb():
    import ctypes
    import ctypes.wintypes as wt

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wt.HANDLE
    fn = k32.K32GetProcessMemoryInfo
    fn.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
    fn.restype = wt.BOOL
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    return round(pmc.PrivateUsage / 1048576, 1) if fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb) else -1.0


def indexed_count():
    try:
        import sqlite3
        from viewer import settings_store
        db = os.path.join(settings_store.settings_dir(), "index.db")
        con = sqlite3.connect("file:" + db + "?mode=ro", uri=True, timeout=1)
        try:
            return con.execute("select count(*) from files").fetchone()[0]
        finally:
            con.close()
    except Exception:
        return -1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theme-rounds", type=int, default=40, help="누수 확인용 테마 왕복 수")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    folder, bigpdf = suite_targets()

    from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
    QStandardPaths.setTestModeEnabled(True)
    from PyQt6.QtWidgets import QApplication, QDialog
    from PyQt6.QtGui import QFont
    app = QApplication(sys.argv[:1])
    QCoreApplication.setApplicationName("polypdf_load_%d" % os.getpid())
    app.setFont(QFont("Malgun Gothic", 9))
    from viewer import __version__ as ver
    out = Path(a.out) if a.out else WORK / "_review" / ("load_%s_%s" % (ver, time.strftime("%y%m%d-%H%M")))
    out.mkdir(parents=True, exist_ok=True)

    beat = {"last": time.perf_counter(), "max": 0.0}

    def tick():
        now = time.perf_counter()
        beat["max"] = max(beat["max"], now - beat["last"])
        beat["last"] = now
    hb = QTimer()
    hb.setInterval(20)
    hb.timeout.connect(tick)
    hb.start()

    def spin(sec):
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < sec:
            app.processEvents()
            time.sleep(0.005)

    rows = []

    def op(name, fn, settle=1.0):
        cur["op"] = name
        spin(0.3)
        beat["last"] = time.perf_counter()
        beat["max"] = 0.0
        t0 = time.perf_counter()
        err = ""
        try:
            fn()
        except Exception as e:                   # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, e)
        dur = time.perf_counter() - t0
        spin(settle)
        tick()
        rows.append({"op": name, "max_stall_s": round(beat["max"], 3), "op_s": round(dur, 3), "err": err})
        print("%-30s 최장 정지 %.3fs%s" % (name, beat["max"], ("  " + err) if err else ""), flush=True)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import overlap                                  # 261025-12(릴리스 SOT §4.3 의 8): 다른 무거운 작업과 겹쳤는지
    watch = overlap.Watch().start()
    import modal_guard                              # 261025-12: 모달은 공통 장치가 닫고 적는다(마스터 §14.7.2 의 6)
    cur = {"op": "준비"}
    guard = modal_guard.install(label=lambda: cur["op"])
    from viewer import settings_store
    for f in ("index.db", "index.db-wal", "index.db-shm"):
        p = os.path.join(settings_store.settings_dir(), f)
        if os.path.exists(p):
            os.remove(p)
    from viewer.app import MainWindow
    mw = MainWindow()
    mw._skip_save_on_close = True
    mw.resize(1400, 900)
    mw.show()
    spin(1.0)
    bt = mw.bookmark_tree
    op("폴더 열기(색인 시작)", lambda: mw.open_folder(str(folder)), settle=8.0)
    files = sum(1 for _ in bt._iter_file_nodes())
    idx0 = indexed_count()

    import viewer.widgets.settings_dialog as sdm
    orig_exec, orig_rp = sdm.SettingsDialog.exec, sdm.SettingsDialog.result_prefs

    def settings_ok(theme):                      # 환경설정 [확인] 실제 경로 — 창은 띄우지 않고 받아들인 것으로
        sdm.SettingsDialog.exec = lambda self: QDialog.DialogCode.Accepted
        sdm.SettingsDialog.result_prefs = lambda self: dict(orig_rp(self), theme=theme)
        try:
            mw.action_open_settings()
        finally:
            sdm.SettingsDialog.exec, sdm.SettingsDialog.result_prefs = orig_exec, orig_rp

    op("환경설정 [확인] → 다크", lambda: settings_ok("dark"))
    op("환경설정 [확인] → 밝게", lambda: settings_ok("light"))
    op("환경설정 [확인](테마 그대로)", lambda: settings_ok("light"))
    op("트리 → 단일", bt._toggle_tree_view)
    op("단일 → 트리", bt._toggle_tree_view)
    for i in range(bt._sort_combo.count()):
        op("정렬 %d" % i, lambda i=i: bt._sort_combo.setCurrentIndex(i))
    op("목록 검색어 입력", lambda: bt.search_edit.setText("도로"))
    op("목록 검색어 지우기", lambda: bt.search_edit.setText(""))
    op("편집 모드 켜기", lambda: bt.set_edit_mode(True))
    op("편집 모드 끄기", lambda: bt.set_edit_mode(False))
    sp = bt.parentWidget()
    while sp is not None and not hasattr(sp, "setSizes"):
        sp = sp.parentWidget()
    if sp is not None:
        n = sp.count()
        op("패널 넓히기", lambda: sp.setSizes([320] + [max(100, (1400 - 320) // max(1, n - 1))] * (n - 1)))
        op("패널 좁히기", lambda: sp.setSizes([185] + [max(100, (1400 - 185) // max(1, n - 1))] * (n - 1)))
    if bigpdf is not None and bigpdf.exists():
        op("큰 PDF 열기", lambda: mw.open_pdf(str(bigpdf)), settle=3.0)
        mv = mw.main_view
        op("쪽 넘기기 ×20", lambda: [mv.go_to_page(p) or app.processEvents() for p in range(0, 200, 10)])
        op("쪽 회전(저장 전)", lambda: mw._rotate_pages([5], +90), settle=2.0)
        op("회전 되돌리기", lambda: mw._rotate_pages([5], -90), settle=2.0)
    gc.collect()
    spin(1.0)
    m1 = private_mb()
    worst = 0.0
    for k in range(a.theme_rounds):
        beat["last"] = time.perf_counter()
        beat["max"] = 0.0
        mw.apply_theme("dark" if k % 2 == 0 else "light")
        spin(0.1)
        tick()
        worst = max(worst, beat["max"])
    gc.collect()
    spin(1.0)
    m2 = private_mb()
    rows.append({"op": "테마 %d번 왕복" % a.theme_rounds, "max_stall_s": round(worst, 3), "op_s": 0, "err": "",
                 "mem_before_mb": m1, "mem_after_mb": m2})
    idx1 = indexed_count()

    bad = [r for r in rows if r["max_stall_s"] >= STALL_LIMIT or r["err"]]
    leak = (m2 - m1) if (m1 > 0 and m2 > 0) else 0.0
    ok = not bad and leak < LEAK_LIMIT_MB
    watch.check("부하 시험 동안")
    L = ["# 부하 시험 — %s" % ver, "",
         "- 폴더: `%s` (파일 %d개) · 큰 PDF: `%s`" % (folder.name, files, bigpdf.name if bigpdf else "-"),
         "- 색인 파일 수: 시작 %s → 끝 %s (부하가 실제로 있었는지)" % (idx0, idx1),
         "- 테마 %d번 왕복 전용 메모리: %.1f → %.1f MB (증가 %.1f, 한도 %.0f)" % (a.theme_rounds, m1, m2, leak, LEAK_LIMIT_MB), "",
         "| 조작 | 최장 정지 | 판정 |", "| --- | --- | --- |"]
    for r in rows:
        L.append("| %s | %.3fs | %s |" % (r["op"], r["max_stall_s"], "실패" if (r["max_stall_s"] >= STALL_LIMIT or r["err"]) else "통과"))
    if guard.seen:
        L += ["", "- 뜬 모달 창 %d개(자동으로 닫음 — 결함인지 사람이 본다): %s" % (
            len(guard.seen), "; ".join("%s·%s·%s" % s for s in guard.seen[:10]))]
    L += [""] + watch.lines()
    L += ["", "**판정: %s**" % ("실패" if not ok else ("보류(겹침)" if watch.overlapped else "통과"))]
    (out / "summary.md").write_text("\n".join(L), encoding="utf-8")
    (out / "result.json").write_text(json.dumps({"version": ver, "files": files, "indexed": [idx0, idx1],
                                                 "mem": [m1, m2], "rows": rows, "ok": ok}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    print("\n".join(L[-3:]))
    print("결과:", out / "summary.md", flush=True)
    sys.stdout.flush()
    os._exit(1 if not ok else (3 if watch.overlapped else 0))


if __name__ == "__main__":
    main()
