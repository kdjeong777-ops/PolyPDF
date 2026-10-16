# -*- coding: utf-8 -*-
"""261014-16: 여러 파일 OCR 글자층 일괄 (텍스트 창 SOT §5.5, 개선 로드맵 P2-2).

실제 처리기(책갈피창 신호 `ocrLayerFilesRequested` → `action_ocr_batch`)로:
A. 스캔 PDF 둘에 보이지 않는 글자층이 생겨 다른 프로그램(PyMuPDF)이 글을 뽑는다 — 하나는 실제 Tesseract 로 읽었다
B. 이미 읽은 쪽(study.db)은 다시 읽지 않는다
C. 글자층이 있는 PDF·서명된 PDF 는 건너뛰고(원본 그대로) 알린다
D. 원본 옆 백업(.textfix.bak.pdf)은 넣은 파일마다 한 번
E. OCR 은 배경 스레드에서(메인이 아니다), 임시 폴더를 남기지 않는다
F. 중지 — 하던 파일 원본은 그대로, 읽은 쪽은 study.db 에 남고 임시 폴더는 없다
G. 책갈피창 폴더 행 우클릭에 'OCR로 글자층 생성 (N개 파일)...' 이 있다
"""
import os, sys, tempfile, shutil, threading, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
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


def scan_pdf(path, words, pages=1):
    """글자를 그림으로만 가진 PDF(스캔본 흉내) — 큰 글씨라 Tesseract 가 읽는다."""
    d = fitz.open()
    for k in range(pages):
        src = fitz.open()
        p = src.new_page(width=595, height=842)
        p.insert_text((60, 200), f"{words} {k + 1}", fontsize=36)
        pix = p.get_pixmap(dpi=150)
        pg = d.new_page(width=595, height=842)
        pg.insert_image(pg.rect, stream=pix.tobytes("png"))
    d.save(str(path)); d.close()


def digest(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


tmp_before = {p.name for p in Path(tempfile.gettempdir()).glob("polypdf_ocrb_*")}
root = Path(tempfile.mkdtemp(prefix="polypdf_ocrbatch_test_"))
try:
    sub = root / "scans"
    sub.mkdir()
    a, b, t, s = sub / "A.pdf", sub / "B.pdf", sub / "T.pdf", sub / "S.pdf"
    scan_pdf(a, "SEEDED PAGE")
    scan_pdf(b, "HELLO BATCH")
    d = fitz.open(); d.new_page().insert_text((72, 72), "Already has text", fontsize=12); d.save(str(t)); d.close()
    scan_pdf(s, "SIGNED DOC")
    t_hash, s_hash = digest(t), digest(s)

    # A 는 이미 읽어 둔 결과(study.db) — 다시 읽지 않아야 한다
    from viewer.study.study_store import StudyStore, file_key_for
    st = StudyStore()
    st.save_page(file_key_for(str(a)), 0, "SEEDED PAGE 1", dpi=300, engine="tesseract", source="ocr", conf=95.0,
                 lang="eng", words=[{"surface": w, "x0": 250 + i * 330, "y0": 760, "x1": 540 + i * 330, "y1": 840}
                                    for i, w in enumerate(["SEEDED", "PAGE", "1"])])
    st.close()

    from viewer import sign_core
    _real_signed = sign_core.is_signed_file
    sign_core.is_signed_file = lambda p: Path(p).name == "S.pdf" or _real_signed(p)   # 서명 판정만 바꾼다

    from viewer.study import ocr as study_ocr
    calls, threads = [], set()
    _real_build = study_ocr.build_page

    def spy_build(doc, pg, **k):
        calls.append(Path(doc.name).name)
        threads.add(threading.current_thread() is threading.main_thread())
        return _real_build(doc, pg, **k)
    study_ocr.build_page = spy_build

    infos = []
    QMessageBox.information = staticmethod(lambda *x, **k: infos.append(x[2] if len(x) > 2 else ""))
    QMessageBox.warning = staticmethod(lambda *x, **k: infos.append(x[2] if len(x) > 2 else ""))
    QMessageBox.question = staticmethod(lambda *x, **k: QMessageBox.StandardButton.No)
    from viewer.widgets import ocr_batch_dialog as obd
    obd.OcrBatchDialog.exec = lambda dlg: (dlg.cmb_lang.setCurrentIndex(dlg.cmb_lang.findData("eng")),
                                           obd.OcrBatchDialog.DialogCode.Accepted)[1]

    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    mw.open_folder(root); spin(20)

    # ── G. 폴더 행 우클릭 메뉴 ──────────────────────────────────────
    bt = mw.bookmark_tree
    folder = None
    for i in range(bt.tree.topLevelItemCount()):
        it = bt.tree.topLevelItem(i)
        stack = [it]
        while stack:
            x = stack.pop()
            if bt._is_folder_node(x) and x.toolTip(0) and Path(x.toolTip(0)) == sub:
                folder = x
            stack.extend(x.child(k) for k in range(x.childCount()))
    from PyQt6.QtWidgets import QMenu
    m = QMenu()
    ff = [str(f.data(0, bt.DATA_FILE)) for f in bt._iter_folder_files(folder)] if folder is not None else []
    bt._add_ocr_layer_action(m, ff)
    labels = [x.text() for x in m.actions()]
    chk(folder is not None and any("OCR로 글자층 생성 (4개 파일)" in x for x in labels),
        "G 폴더 행 — 'OCR로 글자층 생성 (4개 파일)...'(261016-1 개명)", str(labels))

    # ── 실행: 책갈피창 신호로(실제 연결) ─────────────────────────────
    bt.ocrLayerFilesRequested.emit([str(a), str(b), str(t), str(s)]); spin(5)
    msg = "\n".join(str(x) for x in infos)

    def text_of(p):
        dd = fitz.open(str(p)); out = dd.load_page(0).get_text(); dd.close(); return out
    chk("SEEDED" in text_of(a), "A 이미 읽은 결과로 A 에 글자층(다른 프로그램이 글을 뽑는다)", text_of(a)[:80])
    chk("HELLO" in text_of(b).upper(), "A Tesseract 로 읽은 B 에 글자층", text_of(b)[:80])
    chk(calls.count("B.pdf") == 1 and calls.count("A.pdf") == 0, "B 이미 읽은 쪽은 다시 읽지 않는다", str(calls))
    chk(digest(t) == t_hash and digest(s) == s_hash and "T.pdf" in msg and "S.pdf" in msg,
        "C 글자층 있는 PDF·서명된 PDF 는 건너뛰고 알린다(원본 그대로)", msg[-300:])
    chk((sub / "A.pdf.textfix.bak.pdf").exists() and (sub / "B.pdf.textfix.bak.pdf").exists()
        and not (sub / "T.pdf.textfix.bak.pdf").exists(), "D 넣은 파일마다 백업 한 번",
        str(sorted(p.name for p in sub.iterdir())))
    left = {p.name for p in Path(tempfile.gettempdir()).glob("polypdf_ocrb_*")} - tmp_before
    chk(threads == {False} and not left, "E OCR 은 배경 스레드에서, 임시 폴더를 남기지 않는다", f"{threads} {left}")
    chk("2개" in msg, "A 알림 — 넣은 파일 2개", msg[:120])

    # ── F. 중지 ─────────────────────────────────────────────────
    c = sub / "C.pdf"
    scan_pdf(c, "CANCEL ME", pages=2)
    c_hash = digest(c)
    from viewer import ocr_batch
    seen = []

    def tick(done, total, label):
        seen.append(label)
        if len(seen) >= 2:                       # 둘째 쪽을 읽기 전에 중지
            raise ocr_batch.Stopped()
    try:
        ocr_batch.run_file(str(c), lang="eng", drop_watermark=True, tick=tick, cancelled=lambda: False)
        stopped = False
    except ocr_batch.Stopped:
        stopped = True
    st = StudyStore()
    done_pages = st.done_pages(file_key_for(str(c)))
    st.close()
    left = {p.name for p in Path(tempfile.gettempdir()).glob("polypdf_ocrb_*")} - tmp_before
    chk(stopped and digest(c) == c_hash and done_pages == {0} and not left,
        "F 중지 — 원본 그대로, 읽은 쪽은 남고, 임시 폴더 없음", f"{stopped} {done_pages} {left}")
finally:
    try:
        study_ocr.build_page = _real_build
        sign_core.is_signed_file = _real_signed
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
