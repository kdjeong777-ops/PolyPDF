# -*- coding: utf-8 -*-
"""261107-40: 글자층이 이미 앱 OCR 과 같으면 — 쓰지 않고 확인 기록, 문서 정보는 OCR 층을 '있는 쪽' 으로 센다.

사용자 지시: "기존에 글자층(0)으로 없다고 했는데, 있었던것이니, 글자층이 있다는 사항을 적어야 해. 그리고, 날짜는 이를 확인한 날짜로 적어."
HM_bm 꼴 합성 PDF(쪽 전체 그림 + 보이지 않는 다른 프로그램의 OCR 층) 3쪽, 앱 OCR(study.db, 시험 모드)이 그 층과 같다.
  A  문서 정보 '글자층' 행 — '있는 쪽 3(OCR 층 3) · 없는 쪽 0'(텍스트 창 SOT §5.4.2 · 마스터 §4.12 '글자층 세기')
  B  실제 책갈피창 [저장] — 창 없이, 층은 그대로(다시 쓰지 않음), PDF 정보에 확인 기록(same 3), 상태 표시줄 알림, 문서 정보 줄 '… 확인'
  C  다시 [저장] — 같은 쪽 수로 확인했으면 파일을 바꾸지 않는다
  D  실제 'OCR 로 글자층 생성'(책갈피창 신호) — 같은 판정(SOT §5.5 '쓰는 쪽'): 층 그대로, 확인 기록, 알림에 '앱 OCR 과 같은 글자층'
"""
import os, sys, tempfile, shutil, time, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "test")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_ocrlayercheck_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def digest(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


TEXTS = ["Harbor captain engine winter frozen morning", "Ocean temperature current remarkable change measured",
         "Neighbor ladder hammer nails fence garden repair"]
DPI = 300
root = Path(tempfile.mkdtemp(prefix="ocrlayercheck_"))
try:
    folder = root / "f"; folder.mkdir()
    pdf = folder / "scan.pdf"
    src = fitz.open(); out = fitz.open()
    words_by_page = {}
    for i, t in enumerate(TEXTS):
        pg = src.new_page(width=595, height=842)
        for k in range(6):
            pg.insert_text((60, 120 + k * 40), t, fontsize=16)
        k = DPI / 72.0
        words_by_page[i] = [{"surface": w[4], "x0": w[0] * k, "y0": w[1] * k, "x1": w[2] * k, "y1": w[3] * k, "conf": 95}
                            for w in pg.get_text("words")]
        pix = pg.get_pixmap(dpi=100)
        op = out.new_page(width=595, height=842)
        op.insert_image(op.rect, pixmap=pix)
        for kk in range(6):                          # 다른 프로그램(스캐너)이 넣은 보이지 않는 층 — 앱 OCR 과 같은 글
            op.insert_text((60, 120 + kk * 40), t, fontsize=16, render_mode=3)
    out.save(str(pdf)); out.close(); src.close()
    pdf2 = folder / "scan2.pdf"
    shutil.copy(pdf, pdf2)

    from viewer.study.study_store import StudyStore, file_key_for
    st = StudyStore()
    for f in (pdf, pdf2):
        for i, t in enumerate(TEXTS):
            st.save_page(file_key_for(f), i, "\n".join([t] * 6), dpi=DPI, engine="tesseract", source="ocr", conf=95,
                         words=words_by_page[i], lang="eng")
    st.close()

    def fonts(p):
        d = fitz.open(str(p))
        try:
            return sorted({f[4] for i in range(d.page_count) for f in d[i].get_fonts()})
        finally:
            d.close()
    fonts_before = fonts(pdf)

    from viewer import doc_info, text_apply as ta
    from viewer import ocr_layer_save as ols

    # A
    rows = dict(doc_info.doc_info_rows({"path": str(pdf), "pages": 3}, doc_info.read_info(str(pdf))))
    chk(rows.get("글자층", "").startswith("있는 쪽 3(OCR 층 3) · 없는 쪽 0"), "A 문서 정보 — OCR 층도 '있는 쪽' 으로 센다", rows.get("글자층"))

    seen = []
    _Real = ols._dialog_cls()

    class SpyDlg(_Real):
        def exec(self):
            seen.append(True)
            self._pick("skip")
            return 1
    ols._dialog_cls = lambda: SpyDlg

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    infos = []
    QMessageBox.information = staticmethod(lambda *a_, **k: infos.append(a_[2] if len(a_) > 2 else ""))
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Save)
    msgs = []
    _show = mw.status.showMessage
    mw.status.showMessage = lambda m, *a_: (msgs.append(m), _show(m, *a_))
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(pdf), 0); spin(1.0)
    bt = mw.bookmark_tree
    bt.btn_edit.setChecked(True); spin(0.3)

    # B
    bt._op_save(str(pdf)); spin(3.0)
    d = fitz.open(str(pdf)); c = ta.read_text_layer_check(d); w = ta.read_text_layer_stamp(d); d.close()
    chk(not seen, "B1 창 없이(넣을·다른 쪽 없음)", seen)
    chk(c is not None and c["pages"] == 3 and w is None, "B2 PDF 정보에 확인 기록(same 3) — 쓴 기록은 없다", (c, w))
    chk(fonts(pdf) == fonts_before and "krfix" not in fonts(pdf), "B3 층은 다시 쓰지 않는다(다른 프로그램의 층 그대로)", fonts(pdf))
    chk(any("이미 앱 OCR 과 같습니다" in m and "3쪽" in m for m in msgs), "B4 상태 표시줄 알림", msgs[-3:])
    rows = dict(doc_info.doc_info_rows({"path": str(pdf), "pages": 3}, doc_info.read_info(str(pdf))))
    g = rows.get("글자층", "")
    chk("OCR 층 3" in g and "앱 OCR 과 같음 3쪽" in g and g.endswith("확인"), "B5 문서 정보 줄 — 있음·같음 3쪽·확인 일시", g)

    # C
    h = digest(pdf)
    bt._op_save(str(pdf)); spin(1.5)
    chk(digest(pdf) == h and not seen, "C 같은 쪽 수로 확인했으면 다시 [저장] 해도 파일을 바꾸지 않는다")

    # D — 'OCR 로 글자층 생성'
    from viewer.widgets import ocr_batch_dialog as obd
    obd.OcrBatchDialog.exec = lambda dlg: (dlg.cmb_lang.setCurrentIndex(dlg.cmb_lang.findData("eng")),
                                           obd.OcrBatchDialog.DialogCode.Accepted)[1]
    infos.clear()
    bt.ocrLayerFilesRequested.emit([str(pdf2)]); spin(3.0)
    d = fitz.open(str(pdf2)); c2 = ta.read_text_layer_check(d); w2 = ta.read_text_layer_stamp(d); d.close()
    msg = "\n".join(str(x) for x in infos)
    chk(c2 is not None and c2["pages"] == 3 and w2 is None and "krfix" not in fonts(pdf2),
        "D1 일괄도 같은 판정 — 층 그대로, 확인 기록(same 3)", (c2, w2, fonts(pdf2)))
    chk("앱 OCR 과 같은 글자층" in msg and "scan2.pdf" in msg, "D2 끝 알림에 '앱 OCR 과 같은 글자층'", msg[-200:])
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
