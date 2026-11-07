# -*- coding: utf-8 -*-
"""261107-30: [저장] 할 때 앱 OCR 을 PDF 글자층에 넣을지 묻는다 (텍스트 창 SOT §5.4.1).

사용자 지시: "이미지 PDF 자료를 OCR 했는데, 글자층으로 적용되지 않은 경우, '저장'을 누르면 OCR 결과를 PDF 파일에 포함할지 물어보고
적용해. 만일 pdf 의 ocr 과 db 에 ocr 한 것이 있고, 다를 경우 '저장'을 눌렀을 때도 해당 사항을 적용하는 걸 검토해서 수정해".

스캔 모사 PDF(쪽 전체 그림) 4쪽, 앱 OCR(study.db, 시험 모드) 4쪽:
  0·1쪽 글자층 없음 → '넣을 쪽'   2쪽 보이지 않는 층이 앱 OCR 과 다름 → '다른 쪽'   3쪽 층이 앱 OCR 과 같음 → 세지 않음
실제 책갈피창 [저장](`BookmarkTree._op_save`)과 편집 모드를 끌 때의 [저장] 으로 — 창만 가짜(고른 답을 돌려준다).
  A  창이 (넣을 2, 다른 1) 로 뜨고 [넣고 저장] → 0·1·2쪽에 앱 OCR 글자층, 3쪽 그대로, 원본 한 번 저장
  B  다시 [저장] → 묻지 않는다(넣은 쪽은 서명으로 같음)
  C  [취소] → 저장하지 않고 False
  D  '다시 묻지 않음' + [넣지 않고 저장] → 기억, 다음 [저장] 은 창 없이 넣지 않는다
  E  편집 모드를 끌 때 [저장](보류 OCR 만 있는 경우)도 같은 창
  F  닮음도: 다른 글 < LAYER_DIFF_SIM ≤ 같은 글
"""
import os, sys, tempfile, shutil, time
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
QCoreApplication.setApplicationName("polypdf_ocrlayersave_%d" % os.getpid())
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


TEXTS = ["Harbor captain engine winter frozen morning", "Ocean temperature current remarkable change measured",
         "Neighbor ladder hammer nails fence garden repair", "Mountain river valley forest village bridge road"]
DPI = 300
root = Path(tempfile.mkdtemp(prefix="ocrlayersave_"))
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
        if i == 2:                                   # 다른 보이지 않는 층(스캐너 OCR 같은 잡글)
            for kk in range(6):
                op.insert_text((60, 120 + kk * 40), "Hcrb0r cap1ain eng1ne w1nter", fontsize=16, render_mode=3)
        if i == 3:                                   # 앱 OCR 과 같은 층
            for kk in range(6):
                op.insert_text((60, 120 + kk * 40), t, fontsize=16, render_mode=3)
    out.save(str(pdf)); out.close(); src.close()

    from viewer.study.study_store import StudyStore, file_key_for
    st = StudyStore()
    for i, t in enumerate(TEXTS):
        st.save_page(file_key_for(pdf), i, "\n".join([t] * 6), dpi=DPI, engine="tesseract", source="ocr", conf=95,
                     words=words_by_page[i], lang="eng")
    st.close()

    from viewer import ocr_layer_save as ols
    seen = []
    answer = {"choice": "put", "replace": True, "remember": False}

    class FakeDlg:
        def __init__(self, parent, name, n_missing, n_differs, replace=True):
            seen.append((n_missing, n_differs))
            self.choice = answer["choice"]

            class _C:
                def __init__(s, v): s.v = v
                def isChecked(s): return s.v
            self.cb_replace, self.cb_remember = _C(answer["replace"]), _C(answer["remember"])

        def exec(self):
            return 0
    ols._real_dialog_cls = ols._dialog_cls
    ols._dialog_cls = lambda: FakeDlg

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Save)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(pdf), 0); spin(1.0)
    bt = mw.bookmark_tree
    bt.btn_edit.setChecked(True); spin(0.3)

    def layer_text(p):
        d = fitz.open(str(pdf))
        try:
            return d[p].get_text().strip()
        finally:
            d.close()
    before3 = layer_text(3)

    # A
    r = bt._op_save(str(pdf)); spin(3.0)
    chk(seen == [(2, 1)], "A1 창이 넣을 2쪽·다른 1쪽으로 뜬다", seen)
    chk("Harbor" in layer_text(0) and "Ocean" in layer_text(1), "A2 글자층이 없던 쪽에 앱 OCR 글자층", (layer_text(0)[:40], layer_text(1)[:40]))
    chk("Neighbor" in layer_text(2) and "Hcrb0r" not in layer_text(2), "A3 다른 층은 앱 OCR 로 바뀐다", layer_text(2)[:60])
    chk(layer_text(3) == before3, "A4 같은 층은 그대로")
    d = fitz.open(str(pdf)); vis = [s for s in d[0].get_texttrace() if s.get("type") != 3]; d.close()
    chk(not vis, "A5 넣은 글자는 보이지 않는다(render mode 3)")
    chk(not list(folder.glob("*_ocrlayer_tmp.pdf")), "A6 임시 파일이 남지 않는다", [x.name for x in folder.iterdir()])
    from viewer import text_apply as ta
    d = fitz.open(str(pdf)); stamp = ta.read_text_layer_stamp(d); d.close()
    chk(stamp is not None and stamp["kind"] == "ocr" and stamp["pages"] == 3,
        "A7 PDF 정보에 글자층 저장 일시·내용(ocr 3쪽) — 책갈피 쓰기·원본 저장을 지나도 남는다(D6)", stamp)

    # B
    seen.clear()
    r = bt._op_save(str(pdf)); spin(1.5)
    chk(seen == [], "B 다시 [저장] 하면 묻지 않는다(넣은 쪽은 서명으로 같음)", seen)

    # C — 새 OCR 이 생긴 쪽(층을 지운 사본으로 흉내) → 취소
    st = StudyStore()
    st.save_page(file_key_for(pdf), 3, "Completely different words here now", dpi=DPI, engine="tesseract", source="ocr",
                 conf=95, words=words_by_page[3], lang="eng")
    st.close()
    seen.clear(); answer.update(choice="cancel")
    h = pdf.read_bytes()
    r = bt._op_save(str(pdf)); spin(1.0)
    chk(seen == [(0, 1)] and r is False and pdf.read_bytes() == h, "C [취소] 면 저장하지 않고 False", (seen, r))

    # D — 다시 묻지 않음 + 넣지 않고 저장
    seen.clear(); answer.update(choice="skip", remember=True)
    bt._op_save(str(pdf)); spin(1.5)
    from viewer.pathutil import norm_key
    memo = (mw._prefs.get(ols.PREF_KEY) or {}).get(norm_key(str(pdf)))
    chk(seen == [(0, 1)] and memo == {"put": False, "replace": True}, "D1 '다시 묻지 않음' 을 파일별로 기억", (seen, memo))
    seen.clear()
    bt._op_save(str(pdf)); spin(1.0)
    chk(seen == [] and layer_text(3) == before3, "D2 다음 [저장] 은 창 없이 넣지 않는다", seen)

    # E — 편집 모드를 끌 때 [저장](보류만 있는 경우)도 같은 길
    mw._prefs.get(ols.PREF_KEY, {}).pop(norm_key(str(pdf)), None)
    answer.update(choice="cancel", remember=False)
    seen.clear()
    bt._dirty = False
    bt._study_pending_fn = lambda p: True
    bt.btn_edit.setChecked(False); spin(1.0)
    chk(seen == [(0, 1)] and bt.is_edit_mode(), "E 편집 모드를 끌 때 [저장] 도 묻고, 취소하면 편집 모드에 남는다", (seen, bt.is_edit_mode()))
    mw.close()

    # G — 실제 창: Esc·닫기는 [취소](저장도 버림도 하지 않는다) — 가짜 창을 쓰는 다른 검사(modal_guard)도 같은 기본값을 본다
    real = ols.__dict__.get("_real_dialog_cls")
    dlg = real()(None, "x.pdf", 2, 1) if real else None
    if dlg is not None:
        dlg.reject()
        chk(dlg.choice == "cancel" and dlg.cb_replace.isChecked() and not dlg.cb_remember.isChecked(),
            "G Esc·닫기 = [취소], 바꾸기 기본 켬·다시 묻지 않음 기본 끔", (dlg.choice,))

    # F
    chk(ols.layer_similarity("the harbor captain", "Hcrb0r cap1ain the") < ols.LAYER_DIFF_SIM
        <= ols.layer_similarity("The harbor captain.", "the  harbor\ncaptain"), "F 닮음도: 다른 글 < 문턱 ≤ 같은 글")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
