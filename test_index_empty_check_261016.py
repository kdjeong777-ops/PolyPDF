# -*- coding: utf-8 -*-
"""261016-8: 시작 때 '색인이 비었나' 점검이 색인 전체를 읽어 창이 섰다 (응답성 SOT §4, 설치 시험 T1 6.86초 정지).

`_startup_index_check` 가 메인 스레드에서 `SELECT count(*) FROM pages_fts` 를 불렀다 — FTS 의 count(*) 는 색인 전체를 읽는다.
파일 2천여 개 색인을 설치 직후(캐시가 차가울 때) 세다 6.9초 섰다. 비었는지는 한 행으로 안다(`PdfIndex.is_empty`).

A. 빈 색인 → True, 글이 들어가면 False
B. 큰 색인에서 is_empty 가 count(*) 보다 훨씬 빠르다(한 행만 읽는다)
C. 시작 점검·색인 이전 코드가 count(*) 대신 is_empty 를 쓴다
"""
import os, sys, tempfile, shutil, time, inspect
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = tempfile.mkdtemp(prefix="idxempty_")
try:
    from viewer.indexer import PdfIndex
    ix = PdfIndex(os.path.join(root, "index.db"))
    chk(callable(getattr(ix, "is_empty", None)), "0 PdfIndex.is_empty 가 있다")
    chk(ix.is_empty() is True, "A1 빈 색인 → 비었다")
    words = " ".join("낱말%d word%d" % (i, i) for i in range(400))
    with ix.conn:
        ix.conn.executemany("INSERT INTO pages_fts(text, file_id, page_index) VALUES (?, ?, ?)",
                            [(words, f, p) for f in range(60) for p in range(40)])
    chk(ix.is_empty() is False, "A2 글이 있으면 → 비지 않았다")
    t0 = time.perf_counter(); ix.conn.execute("SELECT count(*) FROM pages_fts").fetchone(); t_count = time.perf_counter() - t0
    t0 = time.perf_counter(); ix.is_empty(); t_one = time.perf_counter() - t0
    chk(t_one < 0.05 and t_one * 5 < t_count, "B 큰 색인에서 한 행만 읽는다(count(*) 보다 훨씬 빠름)",
        "is_empty %.4fs · count %.4fs" % (t_one, t_count))
    ix.close()
    from viewer.app import MainWindow
    src = inspect.getsource(MainWindow._startup_index_check)
    chk("is_empty()" in src and "SELECT count(*)" not in src, "C1 시작 점검은 is_empty 를 쓴다")
    import viewer.indexer as _ixm
    chk("SELECT count(*) FROM pages_fts" not in inspect.getsource(_ixm), "C2 색인 코드에 FTS count(*) 가 남지 않았다")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
