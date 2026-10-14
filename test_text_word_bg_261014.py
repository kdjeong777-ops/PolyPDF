# -*- coding: utf-8 -*-
"""261014-5: 텍스트 창 Word 저장을 배경 스레드에서 (텍스트 창 SOT §7, 응답성 SOT §4).

종전에는 `_on_text_export_word` 가 메인 스레드에서 바쁨 커서만 띄우고 돌았다 — '문서 전체' 는 쪽마다 표 인식까지 해
수 초~수 분 창이 멈췄다. 실제 처리기로:
A. 내보내기(쪽 추출)가 **메인이 아닌 스레드**에서 돈다
B. 결과 docx 에 쪽 글과 **고침**이 들어간다(배경에서도 같은 고침 함수)
C. 취소하면 파일을 쓰지 않는다
D. 내보내는 동안 메인 이벤트 루프가 돈다(정지 없음)
"""
import os, sys, tempfile, shutil, threading, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=10, ms=20):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


root = Path(tempfile.mkdtemp(prefix="polypdf_wordbg_"))
try:
    src = root / "W.pdf"
    d = fitz.open()
    for i in range(6):
        pg = d.new_page()
        pg.insert_text((72, 90), f"Chapter {i + 1} heading", fontsize=18)
        for k in range(12):
            pg.insert_text((72, 130 + k * 18), f"body line {k} of page {i + 1} alpha", fontsize=11)
    d.save(str(src)); d.close()
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    mw.open_folder(root); spin(15)
    mw._load_main(HistoryItem(str(src), 0, "", "bookmark")); spin(10)

    # 고침 하나 — 2쪽(0-based 1) 의 'body line 3' 줄을 바꾼다(실제 줄 목록의 자리로)
    from viewer import text_extract2 as tx
    from viewer.text_fix_store import store
    doc = fitz.open(str(src))
    rows = tx.page_lines(doc, str(src), 1, tables="lines")
    doc.close()
    tgt = next((i, r) for i, r in enumerate(rows) if "body line 3 of page 2" in r.get("text", ""))
    store().set_fix(str(src), 1, tgt[0], "FIXED LINE THREE", orig=tgt[1]["text"], rect=tgt[1].get("rect"))

    threads, beats = [], []
    import viewer.text_word as tw
    real = tw.export_pages_to_docx

    import inspect as _insp
    _has_prog = "progress" in _insp.signature(real).parameters   # 수정 전 코드에도 같은 조건으로 돌게

    def spy(*a, **k):
        threads.append(threading.current_thread() is threading.main_thread())
        if not _has_prog:
            time.sleep(0.15 * len(a[2]))                 # 쪽마다 쉬는 것과 같은 시간을 한 번에
            return real(*a, **k)
        prog = k.get("progress")

        def slow(i, n, lbl):                         # 쪽마다 조금 쉬어 메인 루프가 도는지 볼 시간을 만든다
            time.sleep(0.15)
            return prog(i, n, lbl) if prog else True
        k["progress"] = slow
        return real(*a, **k)
    tw.export_pages_to_docx = spy
    hb = QTimer(); hb.timeout.connect(lambda: beats.append(time.monotonic())); hb.start(20)
    spin(5)                                           # 저장 **전** 박동을 쌓는다 — 없으면 메인이 선 구간이 틈으로 안 잡힌다

    dst = root / "out.docx"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(dst), ""))
    mw.text_panel  # 존재 확인
    mw._on_text_export_word("all"); spin(5)
    hb.stop()
    chk(threads and threads[0] is False, "A 쪽 추출이 메인이 아닌 스레드에서 돈다", str(threads))
    chk(dst.exists(), "B docx 가 생겼다")
    if dst.exists():
        from docx import Document
        txt = "\n".join(p.text for p in Document(str(dst)).paragraphs)
        chk("body line 5 of page 6" in txt and "Chapter 1 heading" in txt, "B 모든 쪽 글이 들어갔다")
        chk("FIXED LINE THREE" in txt and "body line 3 of page 2" not in txt, "B 고침이 반영됐다(배경에서도 같은 고침 함수)")
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    chk(len(beats) > 5 and max(gaps or [9]) < 0.5, "D 내보내는 동안 메인 이벤트 루프가 돈다(최장 틈 < 0.5초)",
        f"beats={len(beats)} maxgap={max(gaps or [0]):.2f}")

    # ── C. 취소 ──────────────────────────────────────────────────
    dst2 = root / "cancel.docx"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(dst2), ""))

    def spy_cancel(*a, **k):
        k["progress"] = lambda i, n, lbl: False       # 진행창 [취소] 와 같은 결과
        return real(*a, **k)
    tw.export_pages_to_docx = spy_cancel
    mw._on_text_export_word("all"); spin(5)
    chk(not dst2.exists(), "C 취소하면 파일을 쓰지 않는다")
    chk("취소" in mw.status.currentMessage(), "C 취소를 상태줄에 알린다", mw.status.currentMessage())
    tw.export_pages_to_docx = real
finally:
    try:
        from viewer.text_fix_store import store as _s
        _s()._data = {}; _s().save()          # 시험 전용 설정 폴더(테스트 모드)의 파일을 비운다
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
