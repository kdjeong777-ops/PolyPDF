# -*- coding: utf-8 -*-
"""261014-19: 공유 pdfplumber 문서는 한 번에 한 스레드만 (텍스트 창 SOT §3 규칙 8).

A. 여러 스레드가 공유 핸들(`_tables(…)`, plumber 없이)로 동시에 표를 찾아도 결과가 모두 맞다
   — 종전에는 예외 없이 표가 깨졌다(실측 60번 중 51~60번), 그 결과가 `page_tables` 에 영구 저장됐다
B. 색인 DB 스키마 4 — 그 전에 저장된 표 캐시는 한 번 비운다(다시 판다)
C. 메인이 부르는 `close_cache()` 는 배경이 읽는 중이어도 기다리지 않는다(읽는 쪽이 끝난 뒤 닫는다)
"""
import os, sys, tempfile, shutil, threading, sqlite3
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = Path(tempfile.mkdtemp(prefix="polypdf_tblthr_test_"))
try:
    src = root / "T.pdf"
    d = fitz.open()
    for i in range(6):
        p = d.new_page()
        x0, y0, cw, rh = 72, 160, 140, 24
        for r in range(4):
            p.draw_line((x0, y0 + r * rh), (x0 + 3 * cw, y0 + r * rh))
        for c in range(4):
            p.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + 3 * rh))
        for r in range(3):
            for c in range(3):
                p.insert_text((x0 + c * cw + 6, y0 + r * rh + 16), f"P{i}R{r}C{c}", fontsize=10)
    d.save(str(src)); d.close()

    from viewer import text_extract2 as tx
    tx.set_table_cache_db(None)
    bad = [0]

    def run(k):
        want = [[f"P{k}R{r}C{c}" for c in range(3)] for r in range(3)]
        for _ in range(8):
            tx._TCACHE.clear()
            got = tx._tables(str(src), k)
            if [rows for _b, rows in got] != [want]:
                bad[0] += 1
    ths = [threading.Thread(target=run, args=(k % 6,)) for k in range(6)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    tx.close_cache()
    chk(bad[0] == 0, "A 공유 핸들을 여러 스레드가 동시에 써도 표가 깨지지 않는다", f"{bad[0]} / 48 틀림")

    # ── C. 읽는 중 닫기는 기다리지 않는다(메인이 서지 않게) ─────────────────
    import time
    pdf = tx._plumber(str(src))
    held = threading.Event(); done = threading.Event()

    def reader():
        with tx._PLUMB_USE:                    # 배경이 공유 핸들로 오래 읽는 중
            held.set()
            done.wait(2)
            tx._close_pending()
    th = threading.Thread(target=reader); th.start(); held.wait(2)
    t0 = time.perf_counter(); tx.close_cache(); took = time.perf_counter() - t0
    pending_while = len(tx._PLUMB_PENDING)
    done.set(); th.join()
    chk(took < 0.1 and pending_while == 1 and not tx._PLUMB_PENDING,
        "C 읽는 중 닫기는 기다리지 않고 읽는 쪽이 끝난 뒤 닫는다", f"{took:.3f}s pending={pending_while}")

    # ── B. 스키마 4 — 옛 표 캐시 비우기 ─────────────────────────────
    db = root / "index.db"
    from viewer.indexer import PdfIndex
    ix = PdfIndex(db)
    ix.tables_set(str(src), 0, 1, 1.0, [[[0, 0, 1, 1], [["x"]]]])
    ix.close()
    con = sqlite3.connect(str(db)); con.execute("PRAGMA user_version = 3"); con.commit(); con.close()
    ix = PdfIndex(db)
    n = ix.conn.execute("SELECT count(*) FROM page_tables").fetchone()[0]
    uv = ix.conn.execute("PRAGMA user_version").fetchone()[0]
    ix.close()
    chk(n == 0 and uv == PdfIndex.SCHEMA_VERSION, "B 스키마 3 → 4 에서 표 캐시를 한 번 비운다", f"rows={n} uv={uv}")
    ix = PdfIndex(db)
    ix.tables_set(str(src), 0, 1, 1.0, [[[0, 0, 1, 1], [["y"]]]])
    ix.close()
    ix = PdfIndex(db)
    n2 = ix.conn.execute("SELECT count(*) FROM page_tables").fetchone()[0]
    ix.close()
    chk(n2 == 1, "B 그 뒤에는 비우지 않는다", str(n2))
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
