# -*- coding: utf-8 -*-
"""dict.db 만들기·동봉 용어집 넣기는 앱 시작 때 배경에서 — 메인의 첫 사전 열기가 새 DB 파일을 만들지 않는다 (261108-16, 단어장 SOT §5·응답성 SOT §4.8).

종전: 메인의 첫 `_study_get_dict` 가 새 `dict.db` 를 만들고 동봉 용어집 13,500 용어를 넣어 첫 실행 1.16초 섰다(실측 279 + 878ms).

P. `start_dict_prep()` 뒤 배경이 dict.db 를 만들고 동봉 용어집을 넣는다(메인은 아직 DictStore 를 만들지 않았다)
M. 그 뒤 메인의 첫 `StudyMixin._study_get_dict` — 메인 스레드에서 `seed_source_if_newer` 0번(수정 전 코드: 동봉 용어집 수만큼), 시간 < 0.5초,
   넣은 용어집 이름은 상태 표시줄로 알린다
F. 준비를 띄우지 않은 실행(검사·자식)은 종전대로 메인이 넣는다 — 사전에 동봉 용어가 있다
"""
import os, shutil, sys, tempfile, threading, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"          # 검사 작성 SOT §14.7
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)             # 검사 작성 SOT §14.7.2 의 3

from viewer import settings_store
from viewer.study import glossary_import as gi
from viewer.study.dict_store import DictStore
from viewer.study_controller import StudyMixin

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


main_seeds = []
_orig_seed = DictStore.seed_source_if_newer


def _spy_seed(self, *a, **k):
    if threading.current_thread() is threading.main_thread():
        main_seeds.append(a[0] if a else k.get("source_id"))
    return _orig_seed(self, *a, **k)


DictStore.seed_source_if_newer = _spy_seed


class _Status:
    def __init__(self):
        self.msgs = []

    def showMessage(self, m, *a):
        self.msgs.append(m)


class _Host:
    def __init__(self):
        self._dict_store = None
        self._prefs = {}
        self.status = _Status()

    def _sync_dict_file_sel(self):
        pass


_Host._study_get_dict = StudyMixin._study_get_dict


def fresh(name):
    d = tempfile.mkdtemp(prefix="polypdf_dictprep_%s_" % name)
    settings_store._DIR_OVERRIDE = d
    return d


# P
d1 = fresh("prep")
start = getattr(gi, "start_dict_prep", None)
chk(callable(start), "P start_dict_prep 이 있다")
if callable(start):
    start()
    ev = gi._PREP.get("ev")
    ev.wait(60)
    chk(ev.is_set() and os.path.exists(os.path.join(d1, "dict.db")), "P 배경이 dict.db 를 만들었다")
    chk(bool(gi._PREP.get("seeded")), "P 배경이 동봉 용어집을 넣었다", str(gi._PREP.get("seeded")))

# M
h = _Host()
main_seeds.clear()
t = time.perf_counter()
ds = h._study_get_dict()
dt = time.perf_counter() - t
chk(not main_seeds, "M 메인의 첫 사전 열기가 동봉 용어집을 넣지 않는다", "메인 seed %d번 %s" % (len(main_seeds), main_seeds))
chk(dt < 0.5, "M 메인의 첫 사전 열기 < 0.5초", "%.2f초" % dt)
chk(any("기본 용어집" in m for m in h.status.msgs), "M 넣은 용어집을 상태 표시줄로 알린다", str(h.status.msgs))
n = ds.conn.execute("SELECT count(*) FROM dict_entry").fetchone()[0] if ds else 0
chk(n > 1000, "M 사전에 동봉 용어가 있다", str(n))
ds.conn.close()

# F — 준비 없이
d2 = fresh("noprep")
gi._PREP.update(ev=None, seeded=None)
h2 = _Host()
ds2 = h2._study_get_dict()
n2 = ds2.conn.execute("SELECT count(*) FROM dict_entry").fetchone()[0]
chk(n2 > 1000, "F 준비 없이도 종전대로 동봉 용어가 들어간다", str(n2))
ds2.conn.close()

DictStore.seed_source_if_newer = _orig_seed
settings_store._DIR_OVERRIDE = None
for d in (d1, d2):
    shutil.rmtree(d, ignore_errors=True)
print()
print("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
