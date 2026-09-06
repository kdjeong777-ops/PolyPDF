# -*- coding: utf-8 -*-
"""260906-6: 배경 인덱싱이 UI 스레드를 세우지 않는다 — DB 잠금 규칙(마스터 SOT §5 ⑤).

사용자 보고(260906, 3번째): 실행 직후 창이 '(응답 없음)' 이 됐다가 한참 뒤에 돌아온다.
앞선 두 번(GIL 양보·보이는 행만 검사)으로도 재발했고, 이번 원인은 GIL 이 아니라
**SQLite 잠금**이었다.

  - `index.db` 가 SQLite 기본인 롤백 저널(delete) 모드였다 → **쓰는 쪽이 읽는 쪽을 막는다**.
  - 파이썬 `sqlite3` 의 기본 대기 상한은 **5.0초** = Windows 가 '응답 없음' 을 칠하는 시간.
  - 실측: 큰 PDF 12개를 인덱싱하는 동안 UI 스레드 조회 하나가 **2.49초** 멈췄다.

검사 대상:
  ① 연결은 WAL 로 열린다(저널 모드는 DB 파일에 새겨져 유지된다)
  ② 대기 상한은 부르는 쪽이 정한다 — UI 200ms / 워커 30s
  ③ 쓰기가 열려 있는 동안에도 UI 조회는 막히지 않는다
  ④ 인덱싱이 도는 내내 UI 조회 최장 대기가 짧다
  ⑤ 쓰기 트랜잭션은 쪽 묶음으로 끊는다 + 중간에 끊긴 행은 다시 읽는다
  ⑥ 급하지 않은 시작 점검은 인덱싱 중에 하지 않는다
"""
import os, sys, time, threading, tempfile, shutil, sqlite3
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from viewer.indexer import PdfIndex
import test_fixtures as _fx

root = Path(tempfile.mkdtemp(prefix="polypdf_lock_"))
db = root / "index.db"
src = Path(_fx.text_pdf())
files = []
for i in range(8):
    p = root / f"doc{i}.pdf"
    shutil.copy(src, p)
    files.append(p)

try:
    idx = PdfIndex(db)

    # ── ① WAL ────────────────────────────────────────────────────────────
    mode = idx.conn.execute("PRAGMA journal_mode").fetchone()[0]
    chk(str(mode).lower() == "wal", "① 연결이 WAL 로 열린다", str(mode))
    idx.close()
    mode2 = sqlite3.connect(db).execute("PRAGMA journal_mode").fetchone()[0]
    chk(str(mode2).lower() == "wal", "① 저널 모드는 DB 에 새겨져 유지된다", str(mode2))

    # ── ② 대기 상한 ──────────────────────────────────────────────────────
    chk(0 < PdfIndex.BUSY_MS_UI <= 1000 < PdfIndex.BUSY_MS_BG,
        "② UI 연결은 짧게, 워커는 길게 기다린다",
        f"UI {PdfIndex.BUSY_MS_UI}ms / BG {PdfIndex.BUSY_MS_BG}ms")
    ui = PdfIndex(db, busy_ms=PdfIndex.BUSY_MS_UI)
    got = ui.conn.execute("PRAGMA busy_timeout").fetchone()[0]
    chk(int(got) == PdfIndex.BUSY_MS_UI, "② 준 값이 연결에 실제로 걸린다", f"{got}ms")

    # ── ③ 쓰기가 열려 있어도 읽기는 막히지 않는다 ────────────────────────
    holding = threading.Event()
    release = threading.Event()

    def hold_writer():
        w = PdfIndex(db)
        w.conn.execute("BEGIN IMMEDIATE")
        w.conn.executemany(
            "INSERT INTO pages_fts(text, file_id, page_index) VALUES(?, ?, ?)",
            [("가나다라마바사 " * 400, 99999, i) for i in range(400)])
        holding.set()
        release.wait(10)
        w.conn.rollback()
        w.close()

    th = threading.Thread(target=hold_writer, daemon=True)
    th.start()
    holding.wait(10)
    t0 = time.time()
    ui.probe_get(files[0], 1, 1.0)
    read_ms = (time.time() - t0) * 1000
    release.set(); th.join(10)
    chk(read_ms < 300, "③ 쓰기 트랜잭션이 열려 있어도 UI 조회가 막히지 않는다",
        f"{read_ms:.0f}ms")

    # ── ④ 인덱싱이 도는 내내 ─────────────────────────────────────────────
    done = threading.Event()

    def indexer():
        w = PdfIndex(db)
        for p in files:
            w.index_file(p)
        w.close(); done.set()

    th = threading.Thread(target=indexer, daemon=True)
    th.start()
    worst, n, errs = 0.0, 0, 0
    while not done.is_set():
        t0 = time.time()
        try:
            ui.probe_get(files[0], 1, 1.0)
        except Exception:
            errs += 1
        worst = max(worst, time.time() - t0); n += 1
        time.sleep(0.005)
    th.join(10)
    chk(worst < 1.0 and errs == 0,
        "④ 인덱싱 중에도 UI 조회 최장 대기가 1초 미만",
        f"{n}회 중 최장 {worst*1000:.0f}ms, 예외 {errs}")

    # ── ⑤ 쓰기는 묶음으로 끊는다 + 미완 행은 다시 읽는다 ─────────────────
    chk(0 < PdfIndex.WRITE_CHUNK <= 512,
        "⑤ 쓰기 트랜잭션 묶음 크기가 정해져 있다", f"{PdfIndex.WRITE_CHUNK}쪽")
    ui2 = PdfIndex(db)
    chk(ui2.needs_reindex(files[0]) is False, "⑤ 다 적은 파일은 다시 읽지 않는다")
    ui2.conn.execute("UPDATE files SET page_count=? WHERE path=?",
                     (PdfIndex.PAGES_PENDING, str(files[0])))
    ui2.conn.commit()
    chk(ui2.needs_reindex(files[0]) is True,
        "⑤ 중간에 끊긴 행(page_count<0)은 다시 읽는다")
    ui2.close()

    # ── ⑥ 시작 점검은 인덱싱 중에 하지 않는다 ────────────────────────────
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    import viewer.indexer as _ix_mod
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    opened = {"n": 0}
    _Orig = _ix_mod.PdfIndex

    class _Counting(_Orig):
        def __init__(self, *a, **k):
            opened["n"] += 1
            super().__init__(*a, **k)

    _ix_mod.PdfIndex = _Counting
    try:
        mw._index_workers = [object()]          # 인덱싱이 도는 중인 척
        mw._startup_index_check()
        chk(opened["n"] == 0, "⑥ 인덱싱 중에는 시작 점검이 DB 를 열지 않는다",
            f"{opened['n']}회")
        mw._index_workers = []
        mw._startup_index_check()
        chk(opened["n"] >= 1, "⑥ 인덱싱이 없으면 평소대로 점검한다", f"{opened['n']}회")
    finally:
        _ix_mod.PdfIndex = _Orig
    ui.close()
finally:
    try:
        idx.close()
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
