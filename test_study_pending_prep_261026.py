# -*- coding: utf-8 -*-
"""261026-6: 보류 DB 는 배경이 먼저 만든다 — 메인 스레드가 새 파일을 만들지 않는다(응답성 SOT §6, 단어학습 SOT §14.21).

1.0.1 빌드 시험 T1 1.37초 정지: 본문 첫 쪽을 그리는 메인의 첫 `StudyStore()` 가 이 프로세스의 보류 DB(`study_pending_<pid>.db`)를
**처음 만들었고**, 새 exe 가 만든 새 파일을 백신이 붙들었다(정지 스택 `_attach_pending`). 백신 붙듦은 파일 만들기를 느리게 해 모사한다.

  A  앱 진입점처럼 `start_pending_prep()` 를 부르면 보류 파일은 **배경 스레드**가 만든다(메인은 만들지 않는다)
  B  배경이 아직 만드는 중(느린 디스크·백신 모사 0.8초)에 메인이 `StudyStore()` 를 열면 기다렸다가 **보류 모드 그대로** 붙는다
     — 함께 만들다 잠금 경합으로 '보류 없이 바로 저장' 으로 떨어지지 않는다. 메인은 0.8초 전부를 쓰지 않는다(이미 지난 만큼은 덜 기다림)
  C  준비를 띄우지 않는 실행(검사·도구)은 종전대로 — 첫 `StudyStore()` 가 만든다
  D  쓰기·읽기가 보류 쪽으로 간다(종전과 같은 결과)
"""
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)            # 마스터 §14.7.2 의 3 — 사용자 실제 폴더를 쓰지 않는다
app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_pending_prep_%d" % os.getpid())

from viewer.study import study_store as ss

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def reset(tmp: Path):
    ss._PEND_PREP.update(started=False, ready=None)
    ss.enable_pending(True, tmp / "pending" / ("study_pending_%d.db" % os.getpid()))


root = Path(tempfile.mkdtemp(prefix="polypdf_pend_"))
db = root / "study.db"

# ── A·B: 배경 준비 + 느린 만들기 모사 ─────────────────────────────────
reset(root / "a")
pp = ss.pending_db_path()
creator = {}
_real_connect = sqlite3.connect


def slow_connect(path, *a, **k):
    if str(path) == str(pp) and not Path(path).exists():
        creator.setdefault("thread", threading.current_thread().name)
        time.sleep(0.8)                              # 백신이 새 파일을 붙든 것처럼
    return _real_connect(path, *a, **k)


sqlite3.connect = slow_connect
ss.sqlite3.connect = slow_connect
try:
    ss.start_pending_prep()
    time.sleep(0.2)                                  # 창을 만드는 동안 — 배경은 아직 만드는 중
    t0 = time.perf_counter()
    st = ss.StudyStore(db, busy_ms=200)             # 메인의 첫 열기(본문 첫 쪽)
    waited = time.perf_counter() - t0
finally:
    sqlite3.connect = _real_connect
    ss.sqlite3.connect = _real_connect
chk(creator.get("thread") == "study-pending-prep", "A 보류 파일은 배경 스레드가 만든다(메인이 아님)", creator)
chk(st._pend, "B 배경이 만드는 중이어도 메인은 기다렸다가 보류 모드로 붙는다('바로 저장' 으로 떨어지지 않음)")
chk(waited < 0.75, "B 메인은 이미 지난 만큼은 덜 기다린다(0.8초 전부가 아님)", "%.2fs" % waited)

# ── D: 쓰기·읽기가 보류 쪽으로 ─────────────────────────────────────
k = ss.file_key_for(str(root / "x.pdf"))
st.conn.execute("INSERT INTO p.ocr_page(file_key, page, text) VALUES (?, 0, '보류 글')", (k,))
st.conn.commit()
chk(st.get_page_text(k, 0) == "보류 글", "D 보류 쪽 글을 읽는다")
chk(st.conn.execute("SELECT COUNT(*) FROM main.ocr_page").fetchone()[0] == 0, "D 저장본(study.db)에는 아직 없다")
chk(st.pending_keys() == [k], "D 보류 목록에 그 파일", st.pending_keys())
st.close()

# ── C: 준비를 띄우지 않는 실행은 종전대로 ────────────────────────────
reset(root / "c")
t0 = time.perf_counter()
st2 = ss.StudyStore(root / "c_study.db", busy_ms=200)
chk(st2._pend and ss.pending_db_path().exists() and time.perf_counter() - t0 < 2.0,
    "C 준비 없이도 첫 StudyStore() 가 보류 파일을 만든다(검사·도구)")
st2.close()

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
