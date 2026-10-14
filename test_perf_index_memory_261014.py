# -*- coding: utf-8 -*-
"""261014-25: 색인 자식 프로세스의 메모리 상한 (응답성 SOT §4.4, 개선 로드맵 P3-7).

실제 `IndexWorker.run` → `index_proc.run_job` → 자식(`--index-server`)으로:
A. 자식이 파일 사이에서 상한(`MEM_SOFT_MB`)을 넘으면 '갈아타기' 를 보내고, 부모가 새 자식으로 이어서 끝낸다
   — 상한을 1MB 로 낮춰(검사용 환경 변수) 파일마다 갈아타게 하고, 결과는 갈아타지 않은 색인과 같다
B. 새 자식은 끝낸 파일을 건너뛰고 한 파일 이상 색인한 뒤에만 갈아탄다 — 자식 수 = 파일 수(되풀이 없음)
C. 상한 안이면 자식 하나로 끝난다
D. `private_mb()` 가 이 프로세스 메모리를 잰다(0 이 아님)
"""
import os, sys, tempfile, shutil, sqlite3
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_index_mem_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def counts(db):
    c = sqlite3.connect(db)
    try:
        return (c.execute("select count(*) from files where page_count>=0").fetchone()[0],
                c.execute("select count(*) from pages_fts").fetchone()[0])
    finally:
        c.close()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_imem_"))
try:
    from test_fixtures import text_pdf
    from viewer import index_proc
    from viewer.workers import IndexWorker
    src = Path(text_pdf())
    files = []
    for i in range(4):
        f = tmp / ("doc%d.pdf" % i); shutil.copy(src, f); files.append(f)

    chk(index_proc.private_mb() > 1, "D private_mb() 가 메모리를 잰다", str(index_proc.private_mb()))

    spawned = []
    real_once = index_proc._run_once

    def spy(*a, **k):
        r = real_once(*a, **k)
        spawned.append(r)
        return r
    index_proc._run_once = spy

    # ── A·B: 상한 1MB(자식 환경으로 넘어간다) ──
    os.environ["POLYPDF_INDEX_MEM_MB"] = "1"
    db1 = tmp / "recycle.db"
    errs = []
    w = IndexWorker(db1, tmp, files=files); w.error.connect(lambda e: errs.append(e)); w.run()
    del os.environ["POLYPDF_INDEX_MEM_MB"]
    n_recycle = spawned.count("recycle")
    chk(not errs and spawned and spawned[-1] is True and n_recycle >= 1, "A 상한을 넘으면 갈아타고 끝까지 한다",
        f"{spawned} {errs}")
    chk(len(spawned) == len(files), "B 자식 수 = 파일 수(끝낸 파일 건너뛰고 되풀이 없음)", f"{spawned}")

    # ── C: 상한 안 ──
    spawned.clear()
    db2 = tmp / "plain.db"
    IndexWorker(db2, tmp, files=files).run()
    chk(spawned == [True], "C 상한 안이면 자식 하나", f"{spawned}")
    chk(counts(db1) == counts(db2) and counts(db1)[0] == len(files), "A 결과는 갈아타지 않은 색인과 같다",
        f"{counts(db1)} vs {counts(db2)}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
