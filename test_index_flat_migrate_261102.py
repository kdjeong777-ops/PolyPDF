# -*- coding: utf-8 -*-
"""261102-1: 색인 스키마 5→6(`flat` 에서 하이픈도 뺌)은 PDF 를 다시 읽지 않는다 — 검색창 SOT §3.1.

종전에는 5→6 에서 모든 파일에 `size=-1` 을 적어, 1.1.0-beta.2 로 올린 뒤 첫 실행에 이미 색인된 파일 전부
(사용자 4,622개·15.8GB, 약 1시간 50분)를 PDF 부터 다시 읽었다. `flat` 은 저장한 원문 `text` 에서 나오므로 그것으로 고친다.

실제 `IndexWorker.run`(앱이 쓰는 길)으로:
  A  v5 색인을 자식 프로세스 일감으로 열면 — 파일을 다시 읽지 않고(행 id·손으로 넣은 쪽 그대로) `flat` 이 원문에서 고쳐져
     'laboratory' 가 찾히고, 이전 표식이 지워진다. 수정 전 코드는 파일을 전부 다시 읽어 실패
  B  자식을 못 띄울 때(이 프로세스의 배경 스레드)도 같다
  C  취소되면 끝낸 자리를 남기고, 다음 일감이 그 자리부터 잇는다
  D  스키마 4 이하(옛 표 `pages_fts`)는 종전대로 파일마다 다시 읽는다(`size=-1`) · 새 DB 에는 이전 표식이 없다
"""
import os, sys, shutil, sqlite3, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_flat_migrate_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from test_fixtures import text_pdf
from viewer import index_proc
from viewer.indexer import PdfIndex
from viewer.workers import IndexWorker

tmp = Path(tempfile.mkdtemp(prefix="polypdf_flat6_"))
docs = tmp / "docs"
docs.mkdir()
files = []
for i in range(3):
    f = docs / ("doc%d.pdf" % i)
    shutil.copy(text_pdf(), f)
    files.append(f)


def make_v5(db: Path):
    """지금 코드로 색인한 뒤 v5 꼴로 되돌린다 — 하이픈이 남은 옛 `flat` 쪽 하나를 손으로 넣는다(다시 읽으면 사라진다)."""
    idx = PdfIndex(db)
    for f in files:
        idx.index_file(f)
    fid = idx.conn.execute("SELECT id FROM files ORDER BY id LIMIT 1").fetchone()[0]
    with idx.conn:
        idx.conn.execute("INSERT INTO pages2(flat, text, file_id, page_index) VALUES(?, ?, ?, 99)",
                         ("labora-tory", "labora-\ntory work", fid))
        idx.conn.execute("PRAGMA user_version = 5")
    idx.close()
    c = sqlite3.connect(db)
    ids = [r[0] for r in c.execute("SELECT id FROM files ORDER BY id")]
    c.close()
    return ids


def state(db: Path):
    c = sqlite3.connect(db)
    try:
        ids = [r[0] for r in c.execute("SELECT id FROM files ORDER BY id")]
        neg = c.execute("SELECT count(*) FROM files WHERE size=-1").fetchone()[0]
        hit = c.execute("SELECT count(*) FROM pages2 WHERE flat LIKE '%laboratory%'").fetchone()[0]
        try:
            mig = c.execute("SELECT count(*) FROM migrate_state").fetchone()[0]
        except sqlite3.OperationalError:
            mig = 0
        uv = c.execute("PRAGMA user_version").fetchone()[0]
        return ids, neg, hit, mig, uv
    finally:
        c.close()


try:
    # ── A: 자식 프로세스 ──
    db = tmp / "a.db"
    ids0 = make_v5(db)
    seen = {}
    real = index_proc.run_job

    def spy(job, p, c):
        seen["r"] = real(job, p, c)
        return seen["r"]
    index_proc.run_job = spy
    errs = []
    w = IndexWorker(db, docs)
    w.error.connect(errs.append)
    w.run()
    index_proc.run_job = real
    ids, neg, hit, mig, uv = state(db)
    chk(seen.get("r") is True and not errs, "A 자식 프로세스 일감으로 돌았다", "%r %r" % (seen, errs))
    chk(ids == ids0 and neg == 0, "A 파일을 다시 읽지 않는다(행 id 그대로·size=-1 없음)", "%r→%r neg=%d" % (ids0, ids, neg))
    chk(hit == 1, "A 원문에서 고친 flat 으로 'laboratory' 가 찾힌다", hit)
    chk(mig == 0 and uv == PdfIndex.SCHEMA_VERSION, "A 이전 표식이 지워지고 스키마는 %d" % PdfIndex.SCHEMA_VERSION, (mig, uv))
    idx = PdfIndex(db)
    found = [r for r in idx.search("laboratory")]
    idx.close()
    chk(len(found) >= 1, "A 앱 검색(`search`)도 찾는다", len(found))

    # ── B: 배경 스레드(자식을 못 띄울 때) ──
    db = tmp / "b.db"
    ids0 = make_v5(db)
    index_proc.ENABLED = False
    IndexWorker(db, docs).run()
    index_proc.ENABLED = True
    ids, neg, hit, mig, uv = state(db)
    chk(ids == ids0 and neg == 0 and hit == 1 and mig == 0, "B 배경 스레드 길도 같다", (ids0, ids, neg, hit, mig))

    # ── C: 취소 뒤 이어 하기 ──
    db = tmp / "c.db"
    make_v5(db)
    idx = PdfIndex(db)
    fm = getattr(idx, "finish_migration", None)
    chk(fm is not None, "C finish_migration 이 있다")
    if fm is not None:
        idx.FLAT_CHUNK = 1
        n = {"k": 0}

        def cancel_after_two():
            n["k"] += 1
            return n["k"] > 2
        done = fm(cancel_after_two)
        pos = idx.conn.execute("SELECT pos FROM migrate_state WHERE name=?", (idx.FLAT_REDO,)).fetchone()
        chk(done is False and pos is not None and pos[0] > 0, "C 취소되면 끝낸 자리를 남긴다", (done, pos and pos[0]))
        idx.close()
        idx = PdfIndex(db)
        chk(idx.finish_migration() is True, "C 다음 일감이 이어서 끝낸다")
        idx.close()
        _, neg, hit, mig, _ = state(db)
        chk(hit == 1 and mig == 0 and neg == 0, "C 끝나면 고쳐지고 표식이 없다", (hit, mig, neg))
    else:
        idx.close()

    # ── D: 스키마 4 이하는 종전대로 · 새 DB ──
    db = tmp / "d.db"
    make_v5(db)
    c = sqlite3.connect(db); c.execute("PRAGMA user_version = 4"); c.commit(); c.close()
    PdfIndex(db).close()
    _, neg, _, mig, _ = state(db)
    chk(neg == len(files) and mig == 0, "D 스키마 4 이하는 파일마다 다시 읽게 한다(size=-1)", (neg, mig))
    db = tmp / "e.db"
    PdfIndex(db).close()
    _, _, _, mig, uv = state(db)
    chk(mig == 0 and uv == PdfIndex.SCHEMA_VERSION, "D 새 DB 에는 이전 표식이 없다", (mig, uv))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
