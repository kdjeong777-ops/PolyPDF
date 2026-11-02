# -*- coding: utf-8 -*-
"""261102-4: 책갈피창 [저장] 은 메인 스레드에서 PDF 를 열거나 쓰개를 불러오지 않는다 — 응답성 SOT §4.4.

사용자 보고(1.1.0-beta.2): 책갈피를 만든 뒤 [저장] 하면 창이 멈췄다가 돌아온다. `_96`(10MB) 사본 실측으로 메인 정지 두 곳:
  ① 처음 [저장] 때 책갈피 쓰개(`pdf_bookmarker`·pypdf) import 를 메인에서 — 1.12초
  ② 저장 뒤 '다른 뷰어용 사본' 확인(`_mirror_state`)이 방금 쓴 파일을 메인에서 `fitz.open` — 백신 검사에 붙들려 0.73~0.81초
실제 처리기(`BookmarkTree._op_save`, 앱의 `_finalize_save`·`_file_op_bg` 연결 그대로)로:
  A  쓰개 import 는 메인이 아닌 스레드에서 일어난다(수정 전 코드는 메인)
  B  저장 뒤 사본 확인이 그 파일을 메인에서 `fitz.open` 하지 않는다(수정 전 코드는 `_mirror_open` 이 메인에서) —
     다시 여는 본문·썸네일은 보는 일이라 메인이 연다(마스터 §4.7.10, 이 검사 밖)
  C  책갈피는 PDF 에 실제로 써진다
  D  (사용자 보고 '저장한 후 빈 화면이 표시되고 응답 없음이었다가 돌아왔다') 원본 자리에 놓은 뒤 메인이 그 파일을 처음 열기
     (책갈피창 새로 고침의 조사·본문 다시 열기) **전에** 배경에서 한 번 훑는다(`app._warm_read`) — 백신의 첫 열기 검사를 메인 밖에서.
     수정 전 코드는 `add_or_refresh_file` 의 조사가 메인에서 먼저 열어 실패
"""
import os, sys, shutil, tempfile, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_save_bg_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


import fitz
from test_fixtures import text_pdf
from viewer.app import MainWindow
from viewer.history import HistoryItem
from viewer import bookmarker_bridge

root = Path(tempfile.mkdtemp(prefix="polypdf_savebg_"))
pdf = root / "doc.pdf"
shutil.copy(text_pdf(), pdf)
MAIN = threading.get_ident()

# A — 쓰개를 아직 불러오지 않은 상태로(처음 [저장])
for m in [k for k in sys.modules if "pdf_bookmarker" in k]:
    del sys.modules[m]
bookmarker_bridge._loaded = None
import_threads = []


class _Spy:
    def find_spec(self, name, path=None, target=None):
        if name.endswith("_vendor.pdf_bookmarker"):
            import_threads.append(threading.get_ident())
        return None
sys.meta_path.insert(0, _Spy())

# B — 그 파일을 어느 스레드가 여나
opens = []
_real_open = fitz.open


events = []        # (순서 표, 스레드, 무엇) — 저장 뒤 메인이 그 파일을 처음 열기 전에 배경이 한 번 훑었나(D)
placed = []        # `_finalize_save` 가 새 파일을 원본 자리에 놓은 뒤부터 센다


def _open(*a, **k):
    # 다시 여는 본문·썸네일은 보는 일이라 메인이 연다(마스터 §4.7.10) — '다른 뷰어용 사본' 확인만 본다
    if a and Path(str(a[0])).name == pdf.name:
        import traceback
        st = traceback.extract_stack()
        if any(f.name in ("_mirror_open", "_mirror_state") for f in st):
            opens.append(threading.get_ident())
        if threading.get_ident() == MAIN and placed:
            events.append(("open", MAIN, " > ".join(f.name for f in st[-6:-1])))
    return _real_open(*a, **k)

mw = MainWindow(); mw.show(); app.processEvents()
try:
    mw.bookmark_tree.load_pdf_files([str(pdf)]); app.processEvents()
    mw._load_main(HistoryItem(str(pdf), 0, "", "bookmark")); app.processEvents(); QTest.qWait(200)
    bt = mw.bookmark_tree
    bt.btn_edit.setChecked(True); app.processEvents()
    bms = [("가 장", 1, 0), ("나 장", 3, 0), ("다 절", 4, 1)]
    chk(bt.replace_file_bookmarks(str(pdf), bms), "준비: 책갈피창에 '저장 안 됨' 으로 넣었다")
    import viewer.app as _appmod
    _real_warm = getattr(_appmod, "_warm_read", None)
    if _real_warm is not None:
        def _warm(p, *a, **k):
            if Path(str(p)).name == pdf.name:
                events.append(("warm", threading.get_ident(), ""))
            return _real_warm(p, *a, **k)
        _appmod._warm_read = _warm
    _real_fin = bt._finalize_save

    def _fin(*a, **k):
        r = _real_fin(*a, **k)
        placed.append(1)
        return r
    bt._finalize_save = _fin
    fitz.open = _open
    bt._op_save(str(pdf))
    for _ in range(40):
        app.processEvents(); QTest.qWait(50)
    fitz.open = _real_open
    chk(import_threads and MAIN not in import_threads, "A 책갈피 쓰개 import 는 메인이 아닌 스레드에서",
        "main=%s threads=%s" % (MAIN, import_threads))
    chk(opens and MAIN not in opens, "B 저장 뒤 사본 확인(`_mirror_state`)은 그 파일을 메인에서 열지 않는다",
        "확인 %d번 중 메인 %d번" % (len(opens), opens.count(MAIN)))
    first_open = next((i for i, e in enumerate(events) if e[0] == "open"), None)
    warm_before = [e for e in events[: first_open if first_open is not None else len(events)] if e[0] == "warm"]
    chk(warm_before and all(e[1] != MAIN for e in warm_before),
        "D 저장 뒤 메인이 그 파일을 처음 열기 전에 배경에서 한 번 훑는다(백신 검사를 메인 밖에서)",
        "처음 메인 열기: %s" % (events[first_open][2] if first_open is not None else "-"))
    d = fitz.open(str(pdf)); toc = d.get_toc(); d.close()
    chk([t[1] for t in toc] == ["가 장", "나 장", "다 절"], "C 책갈피가 PDF 에 써졌다", toc)
finally:
    mw._skip_save_on_close = True
    mw.close()
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
