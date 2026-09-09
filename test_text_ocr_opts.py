# -*- coding: utf-8 -*-
"""260909: OCR 언어·범위·워터마크 (텍스트 창 SOT §3.1.2, 단어학습 SOT §14.8·§14.9).

사용자 보고·지시 셋.
  ① "PDF OCR 시 한글이 안 되고 있어. 한글 인식 되게 수정해"
  ② "OCR 시 해당 페이지뿐 아니라 해당 문서 전체 OCR 도 선택적으로 가능하도록"
  ③ "뒷배경으로 있는 워터마크는 인식하지 않도록"

① 의 원인: 언어를 **텍스트층**에서 골랐다. OCR 을 돌리는 상황은 텍스트층이 없거나 못
믿을 때인데, 글자가 하나도 없으면 `한글 0 > 라틴 0` 이 거짓이라 `eng` 로 떨어져
한글 문서를 영문으로 읽었다.

검사 대상
  ① 기본 언어가 **한글+영문**이고, 설치된 것만 골라 쓴다
  ② 없는 언어를 요청해도 조용히 죽지 않고 있는 것으로 줄인다 + 무엇이 빠졌는지 알려 준다
  ③ '자동' 은 **글자가 적으면 판정을 믿지 않는다**(스캔본에서 eng 로 떨어지던 결함)
  ④ 범위 대화상자 — 현재 쪽 / 쪽 범위 / 문서 전체
  ⑤ 워커가 **쪽 목록**을 받고, 쪽마다 저장하며(취소해도 남는다) 점유율을 맞춘다
  ⑥ 워터마크 지우기 — 연한 픽셀이 사라지고 본문은 남는다
  ⑦ 실제 OCR 로 한글을 읽는다(Tesseract 가 있을 때만)
"""
import os, sys, inspect, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication

fails = []
NL = chr(10)


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv[:1])
app.setApplicationName("PolyPDF")
app.setOrganizationName("LocalTools")

import fitz
import test_fixtures as _fx
from viewer.study import ocr as so
from viewer.widgets.ocr_options_dialog import OcrOptionsDialog
from viewer.workers import TextOcrPageWorker

root = Path(tempfile.mkdtemp(prefix="polypdf_ocropt_"))
KRFONT = _fx.KRFONT
HAVE_TESS = bool(so.ensure_tesseract().get("ok"))

try:
    # ── ①② 언어 ────────────────────────────────────────────────
    chk(so.DEFAULT_LANG == "kor+eng", "① 기본 언어가 한글+영문", so.DEFAULT_LANG)
    langs = so.available_langs()
    if langs:
        chk("kor" in langs, "① 설치본에 한글 자료가 있다", str([x for x in langs if x in ("kor", "eng")]))
        chk(so.resolve_lang("kor+eng") == "kor+eng", "① 둘 다 있으면 그대로 쓴다")
        chk(so.resolve_lang("kor+zzz") == "kor", "② 없는 언어는 뺀다",
            so.resolve_lang("kor+zzz"))
        chk(so.missing_langs("kor+zzz") == ["zzz"], "② 무엇이 빠졌는지 알려 준다",
            str(so.missing_langs("kor+zzz")))
        chk(so.resolve_lang("zzz") in langs, "② 하나도 없으면 있는 것으로 내려간다",
            so.resolve_lang("zzz"))
    else:
        print("SKIP - Tesseract 언어 목록을 얻을 수 없다")
    chk(so.resolve_lang("") != "", "② 빈 값이면 기본값으로", so.resolve_lang(""))

    # ── ③ '자동' 은 글자가 적으면 기본값 ─────────────────────────
    blank = fitz.open()
    blank.new_page(width=595, height=842)          # 글자가 하나도 없다
    got = so.detect_lang(blank)
    blank.close()
    chk(got == so.default_lang(),
        "③ 글자가 없는 쪽에서는 판정을 믿지 않는다(종전엔 eng 로 떨어졌다)", got)

    kor = fitz.open()
    kp = kor.new_page(width=595, height=842)
    for i in range(6):
        kp.insert_text((60, 100 + i * 20), "한글 본문이 충분히 들어 있는 문서입니다",
                       fontsize=11, fontfile=KRFONT, fontname="kr")
    kpath = root / "kor.pdf"
    kor.save(str(kpath))
    kor.close()
    kd = fitz.open(str(kpath))
    chk("kor" in so.detect_lang(kd), "③ 한글만 있는 문서는 kor", so.detect_lang(kd))
    kd.close()

    eng = fitz.open()
    ep = eng.new_page(width=595, height=842)
    for i in range(6):
        ep.insert_text((60, 100 + i * 20), "This document has plenty of latin text",
                       fontsize=11)
    epath = root / "eng.pdf"
    eng.save(str(epath))
    eng.close()
    ed = fitz.open(str(epath))
    chk(so.detect_lang(ed) == so.resolve_lang("eng"), "③ 영문만 있는 문서는 eng",
        so.detect_lang(ed))
    ed.close()

    # ── ④ 범위 대화상자 ─────────────────────────────────────────
    dlg = OcrOptionsDialog(page=4, page_count=30)
    v = dlg.values()
    chk(v["pages"] == [4], "④ 기본은 현재 쪽만", str(v["pages"]))
    chk(v["lang"] == "kor+eng", "④ 기본 언어가 한글+영문", str(v["lang"]))
    chk(v["watermark"] is True, "④ 워터마크 지우기가 기본 켬")
    dlg.rb_all.setChecked(True)
    chk(len(dlg.values()["pages"]) == 30, "④ 문서 전체를 고를 수 있다",
        str(len(dlg.values()["pages"])) + "쪽")
    dlg.rb_range.setChecked(True)
    dlg.sp_from.setValue(3)
    dlg.sp_to.setValue(6)
    chk(dlg.values()["pages"] == [2, 3, 4, 5], "④ 쪽 범위를 고를 수 있다",
        str(dlg.values()["pages"]))
    dlg.sp_from.setValue(9)
    dlg.sp_to.setValue(7)
    chk(dlg.values()["pages"] == [6, 7, 8], "④ 앞뒤가 뒤집혀도 바로잡는다",
        str(dlg.values()["pages"]))
    chk("멈출 수 있" in dlg.lbl_note.text(), "④ 오래 걸리면 멈출 수 있다고 알린다",
        dlg.lbl_note.text())

    # ── ⑤ 워커 규약 ────────────────────────────────────────────
    w = TextOcrPageWorker("x.pdf", [1, 2, 3])
    chk(w.pages == [1, 2, 3], "⑤ 쪽 목록을 받는다", str(w.pages))
    chk(TextOcrPageWorker("x.pdf", 5).pages == [5], "⑤ 한 쪽만 줘도 된다")
    chk(w.drop_watermark is True, "⑤ 워터마크 지우기가 기본 켬")
    src = inspect.getsource(TextOcrPageWorker.run)
    chk("force_ocr=True" in src, "⑤ 텍스트층을 무시하고 OCR 한다")
    chk("fitz.open(self.doc_path)" in src, "⑤ 워커가 자기 문서를 따로 연다(응답성 §4)")
    chk(src.index("save_page") < src.index("self.done.emit"),
        "⑤ 쪽마다 **저장을 먼저** — 도중에 멈춰도 읽은 데까지 남는다")
    chk("_pacing.pace(self)" in src, "⑤ 쪽마다 점유율을 맞춘다(응답성 §4 ⑦)")
    chk(hasattr(w, "progress"), "⑤ 진행을 알린다(진행창·취소, 응답성 §4 ④)")
    from viewer.app import MainWindow
    asrc = inspect.getsource(MainWindow._start_text_ocr)
    chk("QProgressDialog" in asrc and "request_cancel" in asrc,
        "⑤ 여러 쪽이면 진행창 + 취소")
    chk("missing_langs" in asrc, "② 빠진 언어를 사용자에게 알린다")
    dsrc = inspect.getsource(MainWindow._on_text_ocr_done)
    chk("current_page()" in dsrc,
        "⑤ 다른 쪽 결과는 저장만 하고 화면을 건드리지 않는다")

    # ── ⑥ 워터마크 지우기 ───────────────────────────────────────
    wm = fitz.open()
    wp = wm.new_page(width=595, height=842)
    wp.insert_text((60, 300), "본문 글자입니다", fontsize=20,
                   fontfile=KRFONT, fontname="kr")
    wp.insert_text((60, 500), "대외비", fontsize=60, fontfile=KRFONT, fontname="kr",
                   color=(0.60, 0.60, 0.60))          # 회색값 153 — 실측 구간
    wpath = root / "wm.pdf"
    wm.save(str(wpath))
    wm.close()
    wd = fitz.open(str(wpath))
    img0, _, _ = so.render_page(wd, 0, dpi=150)
    img1, _, _ = so.render_page(wd, 0, dpi=150, drop_watermark_bg=True)

    def dark(im, thr=200):
        g = im.convert("L")
        return sum(1 for v in g.tobytes() if v < thr)

    d0, d1 = dark(img0), dark(img1)
    chk(d1 < d0 * 0.8, "⑥ 연한 워터마크 픽셀이 사라진다", "%d → %d" % (d0, d1))
    chk(d1 > 0, "⑥ 본문 글자는 남는다", str(d1))
    chk(so.WM_KEEP_LUMA == 140, "⑥ 기준값이 상수로 있다", str(so.WM_KEEP_LUMA))

    # ── ⑦ 실제 OCR ─────────────────────────────────────────────
    if HAVE_TESS:
        a = so.ocr_image(so.render_page(wd, 0, dpi=200)[0],
                         lang=so.resolve_lang("kor+eng"), dpi=200)["text"]
        b = so.ocr_image(so.render_page(wd, 0, dpi=200, drop_watermark_bg=True)[0],
                         lang=so.resolve_lang("kor+eng"), dpi=200)["text"]
        chk("본문" in a.replace(" ", ""), "⑦ 한글을 읽는다(사용자 보고 ①)",
            repr(a.replace(NL, " / ")[:44]))
        chk("외비" in a.replace(" ", ""), "⑥ 끄면 워터마크까지 읽는다",
            repr(a.replace(NL, " / ")[:44]))
        chk("외비" not in b.replace(" ", ""), "⑥ 켜면 워터마크를 읽지 않는다",
            repr(b.replace(NL, " / ")[:44]))
        chk("본문" in b.replace(" ", ""), "⑥ 켜도 본문은 읽는다",
            repr(b.replace(NL, " / ")[:44]))
    else:
        print("SKIP - Tesseract 없음(⑦ 실제 OCR 검사 생략)")
    wd.close()

finally:
    shutil.rmtree(root, ignore_errors=True)

print(NL + "=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
