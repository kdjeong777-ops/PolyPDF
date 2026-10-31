# -*- coding: utf-8 -*-
"""261031: 깨진 색인에 쓰면 SQLite 가 꾸밈 없는 'constraint failed' 만 낸다 — 손상 복구가 알아보게(응답성 SOT §4 ⑤, 사용자 결정).

사용자 실제 index.db 가 10-26~31 사이 다시 손상됐다(`btreeInitPage() returns error code 11`). 폴더를 열면 색인 자식이 첫 새 파일을 쓰다
`sqlite3.IntegrityError: constraint failed` 로 멈췄고, `dbutil.is_corrupt_error` 가 손상으로 보지 않아 복구(새로 만들기·error.log)가 돌지
않았다 — 새 파일이 말없이 검색에서 빠졌다(1.1.0-beta.1 빌드 시험 T4 색인 62).

  A  `is_corrupt_error`: 꾸밈 없는 'constraint failed'(예외 이름이 붙은 꼴 포함)는 손상, 종류·자리를 붙인 진짜 제약 위반과 잠금은 손상 아님
  B  실제 처리기 `MainWindow._on_index_db_error("constraint failed")` 가 손상 표식을 남기고(까닭은 error.log) 재구축을 건다 —
     수정 전 코드는 아무것도 하지 않아 실패
  C  진짜 제약 위반 문구로는 표식도 재구축도 없다(멀쩡한 색인을 지우지 않는다)
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_idx_constraint_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")

from viewer import dbutil

# ── A ──
for m in ("constraint failed", "IntegrityError: constraint failed", "Constraint failed."):
    chk(dbutil.is_corrupt_error(Exception(m)), "A 꾸밈 없는 '%s' 는 손상" % m)
for m in ("UNIQUE constraint failed: files.path", "NOT NULL constraint failed: pages.text",
          "CHECK constraint failed: x", "database is locked"):
    chk(not dbutil.is_corrupt_error(Exception(m)), "A '%s' 는 손상이 아니다" % m)

# ── B·C ── 실제 처리기
from viewer.app import MainWindow
from viewer.indexer import PdfIndex
mw = MainWindow()
mw._skip_save_on_close = True
calls = []
mw.action_reindex = lambda verify=True: calls.append(verify)
mark = PdfIndex._corrupt_mark(mw._db_path)
mark.unlink(missing_ok=True)

mw._on_index_db_error("UNIQUE constraint failed: files.path")
app.processEvents()
chk(not mark.exists() and not getattr(mw, "_index_recovering", False), "C 진짜 제약 위반으로는 손상 표식·복구가 없다")

mw._on_index_db_error("constraint failed")
from PyQt6.QtCore import QTimer, QEventLoop
loop = QEventLoop(); QTimer.singleShot(600, loop.quit); loop.exec()
chk(mark.exists(), "B 'constraint failed' → 손상 표식을 남긴다(다음 연결이 새로 만든다)", str(mark))
chk(calls == [False], "B 재구축을 건다", calls)
log = mw._db_path.parent / "error.log"
chk(log.exists() and "constraint failed" in log.read_text(encoding="utf-8"), "B error.log 에 까닭")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
