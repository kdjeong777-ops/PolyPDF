# -*- coding: utf-8 -*-
"""261009-14: 검색 색인(index.db) 손상 복구 — 검색창 SOT §9 · 응답성 SOT §4 ⑤.

설치본 시험에서 색인이 **열리기는 하지만 쿼리에서야** `database disk image is malformed` 를 내는 상태로
발견됐다. 그때 앱은 검색 목록을 조용히 비우고 상태줄에 영어 오류만 잠깐 보였고, '도구 → 인덱스 재구축' 도
같은 DB 에 다시 넣을 뿐이라 **고쳐지지 않았다.**

A. 손상 DB 를 만든다 — 여는 것은 되고 FTS 조회가 malformed (설치본에서 본 모양)
B. `PdfIndex(verify=True)`(재구축 경로)는 무결성을 보고 새로 만든다 → 조회가 된다
C. `PdfIndex.mark_corrupt` 표식이 있으면 다음에 여는 연결이 새로 만들고 표식을 지운다
D. 실제 `MainWindow.action_search` 가 손상 DB 에서 오류를 받으면 → 표식·한국어 안내·재구축(verify 없이)을 건다
E. 실제 `action_reindex`(메뉴 경로)는 verify 로 워커를 만들고, 그 전에 UI 의 조사용 연결을 닫는다
"""
import os, sys, sqlite3, tempfile, shutil, time, random
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_idx_corrupt_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from viewer.indexer import PdfIndex

tmp = Path(tempfile.mkdtemp(prefix="polypdf_idxc_"))


def make_corrupt_db(db: Path):
    """정상 색인을 채운 뒤 **가운데 쪽들만** 쓰레기로 덮는다(머리·스키마 쪽은 그대로 → 열기는 된다)."""
    ix = PdfIndex(db)
    cur = ix.conn.cursor()
    cur.execute("INSERT INTO files(path, mtime, page_count) VALUES (?,?,?)", ("x.pdf", 1.0, 400))
    fid = cur.lastrowid
    for i in range(400):
        cur.execute("INSERT INTO pages_fts(text, file_id, page_index) VALUES (?,?,?)",
                    ("asphalt superpave mixture page %d " % i * 40, fid, i))
    ix.conn.commit()
    ix.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    ix.close()
    size = db.stat().st_size
    rnd = random.Random(1)                               # 늘 같은 손상(재현 가능)
    with open(db, "r+b") as f:
        for off in range(size // 3, size * 2 // 3, 4096):
            f.seek(off + 100)
            f.write(bytes(rnd.randrange(256) for _ in range(600)))


def query_ok(db: Path) -> bool:
    try:
        c = sqlite3.connect(str(db))
        c.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH 'asphalt'").fetchone()
        c.execute("PRAGMA quick_check(1)").fetchone()
        ok = c.execute("PRAGMA quick_check(1)").fetchone()[0] == "ok"
        c.close()
        return ok
    except sqlite3.DatabaseError:
        return False


try:
    # ── A ──
    db = tmp / "a" / "index.db"; db.parent.mkdir()
    make_corrupt_db(db)
    opened = True
    try:
        PdfIndex(db).close()
    except Exception:
        opened = False
    chk(opened and not query_ok(db), "A 손상 DB — 열기는 되고 조회·무결성 검사는 실패(설치본에서 본 모양)")

    # ── B ──
    ix = PdfIndex(db, verify=True); ix.close()
    chk(query_ok(db), "B verify=True(재구축 경로)가 손상을 보고 새로 만든다")

    # ── C ──
    db2 = tmp / "c" / "index.db"; db2.parent.mkdir()
    make_corrupt_db(db2)
    PdfIndex.mark_corrupt(db2)
    chk(Path(str(db2) + ".corrupt").exists(), "C 표식이 생긴다")
    PdfIndex(db2).close()
    chk(query_ok(db2) and not Path(str(db2) + ".corrupt").exists(), "C 표식이 있으면 다음 연결이 새로 만들고 표식을 지운다")

    # ── D: 실제 검색 경로 ──
    from viewer.app import MainWindow
    import viewer.app as appmod
    mw = MainWindow(); mw._skip_save_on_close = True
    db3 = tmp / "d" / "index.db"; db3.parent.mkdir()
    make_corrupt_db(db3)
    folder = tmp / "pdfs"; folder.mkdir()
    mw._db_path = db3
    mw._folder = folder
    reindex_calls = []
    orig_reindex = mw.action_reindex
    mw.action_reindex = lambda verify=True: reindex_calls.append(verify)
    msgs = []
    mw.status.messageChanged.connect(lambda m: msgs.append(m))
    mw.action_search("asphalt")
    t0 = time.time()
    while time.time() - t0 < 5 and not reindex_calls:
        app.processEvents(); time.sleep(0.02)
    chk(Path(str(db3) + ".corrupt").exists(), "D 검색이 손상을 만나면 표식을 남긴다")
    chk(reindex_calls == [False], "D 그리고 재구축을 건다(표식이 새로 만들게 — verify 없이)", str(reindex_calls))
    chk(any("손상" in m for m in msgs), "D 한국어로 알린다(영어 오류만 남기지 않는다)", str(msgs[-3:]))

    # ── E: 메뉴 경로 ──
    mw.action_reindex = orig_reindex
    made = []
    orig_iw = appmod.IndexWorker

    class _IW(orig_iw):
        def __init__(self, *a, **k):
            made.append(k.get("verify"))
            super().__init__(*a, **k)
    appmod.IndexWorker = _IW
    closed = []

    class _Probe:
        def close(self):
            closed.append(1)
    mw._probe_idx = _Probe()
    try:
        mw.action_reindex()
    finally:
        appmod.IndexWorker = orig_iw
    chk(made == [True], "E '인덱스 재구축' 은 verify 로 워커를 만든다", str(made))
    chk(closed == [1] and mw._probe_idx is None, "E 그 전에 UI 의 조사용 색인 연결을 닫는다(열린 파일은 못 지운다)")
    t0 = time.time()
    while time.time() - t0 < 5 and mw._index_workers:
        app.processEvents(); time.sleep(0.02)
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(tmp), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
