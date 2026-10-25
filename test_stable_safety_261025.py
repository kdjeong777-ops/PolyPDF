# -*- coding: utf-8 -*-
"""261025-8: 첫 정식판(1.0.0) 안정성 보강 회귀 검사 — 릴리스 SOT §4.5.

  A  설정 안전 저장(마스터 §8.2.0): 쓰는 도중 실패해도 원래 settings.json 이 그대로 · 임시 파일이 남지 않음 ·
     읽지 못한 파일은 `.broken-*` 으로 남고 error.log 에 까닭
  B  네이티브 크래시 기록(마스터 §14.7.3): 자식 프로세스가 진짜로 접근 위반으로 죽으면 crash.log 에 Python 스택
  C  색인 정기 무결성 점검(응답성 SOT §4 ⑤): 표식 없음·오래됨 → 점검 대상, 점검 뒤 표식, 손상이면 새로 만들고 error.log,
     배경 색인 일꾼이 그 판정을 쓴다
"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok = True


def check(name, cond, extra=""):
    global ok
    print(("  OK  " if cond else " FAIL ") + name + (f"  {extra}" if extra else ""), flush=True)
    ok = ok and bool(cond)


from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)        # 마스터 §14.7.2 의 3 — 사용자 실제 폴더를 쓰지 않는다
app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_stable_safety_%d" % os.getpid())
from viewer import settings_store
from viewer.indexer import PdfIndex

SD = settings_store.settings_dir()
SD.mkdir(parents=True, exist_ok=True)
LOG = SD / "error.log"


def log_text():
    try:
        return LOG.read_text(encoding="utf-8")
    except OSError:
        return ""


try:
    # ---------- A 설정 안전 저장 ----------
    name = "safety_test.json"
    p = settings_store.settings_path(name)
    settings_store.save({"favorites": ["가", "나"], "preferences": {"theme": "dark"}}, name)
    check("A1 저장 → 읽기", settings_store.load(name).get("favorites") == ["가", "나"])
    check("A1 임시 파일이 남지 않음", not list(SD.glob(name + ".*.tmp")))

    # 쓰는 도중 실패(디스크 가득·강제 종료 모사): 파일에 반쯤 쓰고 예외 — 원래 파일이 그대로여야 한다
    import builtins
    real_open = builtins.open

    class _Half:
        def __init__(self, f):
            self.f = f

        def write(self, s):
            self.f.write(s[: len(s) // 2])
            self.f.flush()
            raise OSError(28, "No space left on device (모사)")

        def __getattr__(self, k):
            return getattr(self.f, k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()

    def _open(file, mode="r", *a, **k):
        f = real_open(file, mode, *a, **k)
        return _Half(f) if ("w" in mode and str(file).startswith(str(p))) else f

    builtins.open, io.open = _open, _open
    try:
        try:
            settings_store.save({"favorites": ["새 값"] * 50}, name)
        except Exception:
            pass
    finally:
        builtins.open, io.open = real_open, real_open
    raw = p.read_text(encoding="utf-8")
    try:
        kept = json.loads(raw).get("favorites")
    except Exception as e:      # noqa: BLE001
        kept = "깨짐: %s" % e
    check("A2 쓰다 실패해도 원래 설정 그대로", kept == ["가", "나"], repr(kept)[:80])
    check("A2 실패한 임시 파일이 남지 않음", not list(SD.glob(name + ".*.tmp")))

    # 읽지 못하는 파일 — 기본값으로 시작하되 깨진 파일은 남기고 까닭을 적는다
    p.write_text('{"favorites": ["가"', encoding="utf-8")
    before = log_text()
    d = settings_store.load(name)
    broken = list(SD.glob(name + ".broken-*"))
    check("A3 깨진 설정 → 기본값", d.get("favorites") in (None, []) and "schema_version" in d)
    check("A3 깨진 파일을 .broken-* 로 남김", len(broken) == 1 and broken[0].read_text(encoding="utf-8").startswith('{"fav'))
    check("A3 다음 저장이 덮어쓸 원래 이름은 비움", not p.exists())
    check("A3 error.log 에 '설정 읽기 실패'", "[설정 읽기 실패] " + name in log_text()[len(before):])

    # ---------- B 네이티브 크래시 기록 ----------
    child = (
        "import os, sys\n"
        "sys.path.insert(0, %r)\n"
        "os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
        "from PyQt6.QtCore import QStandardPaths, QCoreApplication\n"
        "QStandardPaths.setTestModeEnabled(True)\n"
        "app = QCoreApplication(sys.argv[:1])\n"
        "QCoreApplication.setApplicationName(%r)\n"
        "import main\n"
        "main._install_crash_log()\n"
        "import faulthandler\n"
        "def deep_native_crash():\n"
        "    faulthandler._sigsegv()\n"
        "deep_native_crash()\n"
    ) % (HERE, "polypdf_stable_safety_%d" % os.getpid())
    r = subprocess.run([sys.executable, "-c", child], capture_output=True, timeout=120)
    crash = SD / "crash.log"
    txt = crash.read_text(encoding="utf-8", errors="replace") if crash.exists() else ""
    check("B1 자식이 크래시로 끝남", r.returncode != 0, "code=%s" % r.returncode)
    check("B1 crash.log 에 시작 줄", "=== 시작" in txt)
    check("B1 crash.log 에 치명 오류와 그 함수", ("Fatal Python error" in txt or "fatal exception" in txt)
          and "deep_native_crash" in txt, txt[-300:].replace("\n", " | "))

    # ---------- C 색인 정기 무결성 점검 ----------
    db = SD / "index_safety.db"
    for suf in ("", "-wal", "-shm", ".checked", ".corrupt"):
        try:
            os.remove(str(db) + suf)
        except OSError:
            pass
    check("C1 색인이 없으면 점검 대상 아님", not PdfIndex.integrity_due(db))
    ix = PdfIndex(db)
    ix.conn.execute("create table if not exists pad(x)")
    ix.conn.executemany("insert into pad values (?)", [("가" * 400,)] * 400)
    ix.conn.commit()
    ix.conn.execute("pragma wal_checkpoint(truncate)")
    ix.conn.close()
    check("C2 표식 없는 기존 색인 → 점검 대상(처음 한 번)", PdfIndex.integrity_due(db))
    PdfIndex(db, verify=True).conn.close()
    check("C3 점검 통과 → 표식 → 대상 아님", PdfIndex._checked_stamp(db).exists() and not PdfIndex.integrity_due(db))
    old = time.time() - (PdfIndex.INTEGRITY_DAYS + 1) * 86400
    os.utime(PdfIndex._checked_stamp(db), (old, old))
    check("C4 표식이 INTEGRITY_DAYS 넘게 오래됨 → 대상", PdfIndex.integrity_due(db))

    from viewer.workers import IndexWorker
    w = IndexWorker(db, None)
    check("C5 배경 색인 일꾼이 정기 점검을 켬(재구축을 고르지 않아도)", w._verify() is True)

    # 손상: pad 표의 b-tree 페이지 가운데를 망가뜨린다
    size = db.stat().st_size
    with real_open(db, "r+b") as f:
        f.seek(size // 2)
        f.write(b"\xff" * 4096)
    before = log_text()
    ix = PdfIndex(db, verify=True)
    good = ix.conn.execute("pragma quick_check(1)").fetchone()[0]
    ix.conn.close()
    check("C6 손상 색인 → 새로 만들어 정상", good == "ok")
    check("C6 error.log 에 '색인 초기화' 까닭(quick_check)", "quick_check" in log_text()[len(before):])
finally:
    pass

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.stdout.flush()
os._exit(0 if ok else 1)
