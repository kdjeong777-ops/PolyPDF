# -*- coding: utf-8 -*-
"""261010-11: 메인 스레드의 study.db 읽기는 연결 하나를 다시 쓴다 (응답성 SOT §4 ⑤).

빌드 시험(beta.227) T2(스캔본 HM.pdf) 첫 쪽에서 1.21초 정지 — 메인 스레드가 `dbutil.tune` 에 있었다.
쪽을 그릴 때마다 `StudyStore()` 를 2~3번 새로 열었고, 열 때마다 스키마 스크립트(쓰기 트랜잭션)·PRAGMA 가 돌아
OCR 워커가 같은 DB 에 쓰는 동안 기다렸다.

A. 실제 MainWindow 로 PDF 를 열고 쪽을 여럿 넘겨도 메인 스레드의 `StudyStore()` 생성은 1번(종전 쪽마다 2~3번)
B. 다른 연결(워커 흉내)이 저장한 OCR 글·낱말을 다시 연결하지 않고도 읽는다(오래 쥔 연결이 낡은 값을 보지 않는다)
C. 메인 스레드가 아닌 곳에서 부르면 새로 열어 읽는다(sqlite 연결은 만든 스레드에서만)
"""
import os, sys, time, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_study_reads_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


import test_fixtures as fx
from viewer.study import study_store as ss
made = []
_orig_init = ss.StudyStore.__init__


def _count_init(self, *a, **k):
    made.append(threading.current_thread() is threading.main_thread())
    return _orig_init(self, *a, **k)


ss.StudyStore.__init__ = _count_init
try:
    from viewer.app import MainWindow
    pdf = str(fx.scanned_pdf())
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); spin(0.3)
    mw.open_pdfs([pdf]); spin(1.0)
    made.clear()
    mv = mw.main_view
    for p in range(1, 6):
        mv.go_to_page(p); spin(0.15)
    main_made = sum(1 for m in made if m)
    chk(main_made <= 1, "A 쪽 5개를 넘기는 동안 메인 스레드의 study.db 새 연결 ≤ 1", "새 연결 %d번" % main_made)

    key = ss.file_key_for(pdf)
    w = ss.StudyStore()                                   # 워커 흉내 — 다른 연결로 저장
    w.save_page(key, 3, "스캔 본문 글", dpi=300, engine="t", source="ocr", conf=90.0,
                words=[{"lemma": "본문", "surface": "본문", "lang": "ko", "x0": 1, "y0": 2, "x1": 3, "y1": 4, "conf": 90}],
                lang="ko")
    w.close()
    chk(mw._ocr_page_text(pdf, 3) == "스캔 본문 글", "B 다른 연결이 저장한 OCR 글을 그대로 읽는다", repr(mw._ocr_page_text(pdf, 3)))
    chk(mw._ocr_page_dpi(pdf, 3) == 300 and len(mw._ocr_page_words(pdf, 3)) == 1, "B DPI·낱말도")

    out = {}
    t = threading.Thread(target=lambda: out.update(v=mw._ocr_page_text(pdf, 3)))
    t.start(); t.join()
    chk(out.get("v") == "스캔 본문 글", "C 메인 스레드가 아니면 새로 열어 읽는다", repr(out))
    mw.close(); spin(0.2)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    ss.StudyStore.__init__ = _orig_init
    try:
        import shutil
        from viewer import settings_store
        shutil.rmtree(str(settings_store.settings_dir()), ignore_errors=True)
    except Exception:
        pass

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
