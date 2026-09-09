# -*- coding: utf-8 -*-
"""260908-8: 잡음 규칙의 단일 표준 · 제목 판정 · [OCR 다시 읽기]
(텍스트 창 SOT §3.1.1·§3.4·§3.5·§3.5.1, 단어학습 SOT §14.6·§14.7).

사용자 지시(260908) 셋.
  ① "이상한 글자가 많이 없어졌어. 그런데 ■ 등은 아직 있어."
  ② "제목 스타일은 글자 크기가 많이 차이가 날 때만 적용해. 크기는 거의 같은데
     진하기가 되어있다고 적용하지마."
  ③ "OCR 버튼을 넣어서 OCR 다시할 수 있게 해. 현재와 같이 빈공간에 이상한 글자 등에
     대한 규칙에 따라."
  ④ (작업 중 추가) "SOT 를 검토하여 OCR, 단어장 등의 규칙으로도 적용해."

검사 대상
  ① 기호만 남은 줄(`■`·`☜`)은 뺀다 — 크기로는 못 거른다(`■` 는 16pt)
  ② 그런데 `[ 제목 ]` 의 `]` 는 **살아서 이어진다**(조각이 아니라 줄에서 판단)
  ③ 한 글자인데 홀쭉·납작하면 뺀다(`l` 이 1pt × 54pt)
  ④ 일반 PDF 는 기호도 작은 글씨도 **하나도 빼지 않는다**
  ⑤ 제목은 배수와 절대 차이를 **둘 다** 넘을 때만 — 굵기는 보지 않는다
  ⑥ OCR 낱말 상자 → 줄 (좌표가 살아 있다) + 같은 잡음 규칙 + 신뢰도
  ⑦ `study/ocr` 이 같은 규칙을 쓴다 — 낱말과 **본문 양쪽에서** 뺀다
  ⑧ [OCR 다시 읽기] 단추는 늘 보이고, 한 쪽만 워커에서 읽는다
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
from viewer import text_noise as tn
from viewer import text_extract2 as tx

root = Path(tempfile.mkdtemp(prefix="polypdf_noise_"))
KRFONT = r"C:\Windows\Fonts\malgun.ttf"


def scan_page(dst):
    """그림 위에 보이지 않는 글자를 얹은 쪽 — 진짜 글 + 여러 종류의 잡음."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 595, 842))
    pix.clear_with(255)
    page.insert_image(page.rect, pixmap=pix)
    kr = dict(render_mode=3, fontfile=KRFONT, fontname="kr")
    page.insert_text((60, 120), "본문 첫째 줄입니다", fontsize=14, **kr)
    page.insert_text((60, 160), "[ 제목 같은 줄", fontsize=14, **kr)
    page.insert_text((230, 160), "]", fontsize=14, **kr)      # 같은 줄의 닫는 괄호
    page.insert_text((60, 200), "아주 큰 제목", fontsize=30, **kr)
    page.insert_text((400, 60), "픔", fontsize=2.0, **kr)      # ① 너무 작다
    page.insert_text((430, 300), "■", fontsize=16, **kr)       # ② 기호만
    page.insert_text((470, 300), "☜", fontsize=14, **kr)
    doc.save(str(dst))
    doc.close()
    return dst


try:
    tx.set_table_cache_db(None)

    # ── 판정 함수 그 자체 ────────────────────────────────────────
    chk(tn.is_symbol_only("■") and tn.is_symbol_only("☜ ←"),
        "① 기호만 남은 것을 알아본다")
    chk(not tn.is_symbol_only("가"), "① 글자가 섞이면 잡음이 아니다")
    chk(not tn.is_symbol_only("[ 제목 ]"), "① 이어 붙인 줄은 잡음이 아니다")
    chk(tn.is_noise_box("가", 0, 0, 10, 3.0), "③ 높이 4pt 미만은 잡음")
    chk(tn.is_noise_box("l", 0, 0, 1.0, 54.0), "③ 한 글자인데 홀쭉하면 잡음")
    chk(not tn.is_noise_box("l", 0, 0, 4.0, 14.0), "③ 보통 비율의 한 글자는 남는다")
    chk(not tn.is_noise_box("■", 0, 0, 16, 16),
        "③ 기호는 **모양으로는** 안 뺀다(줄에서 뺀다 — `]` 를 살리려고)")
    chk(tn.keep_ocr_word("가나", 0, 0, 60, 40, 0.9, scale=72.0 / 300) is True,
        "⑥ 300dpi 60×40px = 14.4×9.6pt → 남긴다")
    chk(tn.keep_ocr_word("가나", 0, 0, 60, 10, 0.9, scale=72.0 / 300) is False,
        "⑥ 같은 낱말도 10px(2.4pt) 높이면 잡음")
    chk(tn.keep_ocr_word("가나", 0, 0, 60, 40, 0.1, scale=72.0 / 300) is False,
        "⑥ 신뢰도가 낮으면 버린다")
    chk(tn.keep_ocr_word("■", 0, 0, 60, 60, 0.9, scale=72.0 / 300) is False,
        "⑥ 낱말 단계에서는 기호만인 것도 버린다(이을 것이 없다)")

    # ── ①②③ 실제 쪽 ───────────────────────────────────────────
    scan = scan_page(root / "scan.pdf")
    tx.close_cache()
    d = fitz.open(str(scan))
    rows = tx.page_lines(d, str(scan), 0, tables="off", join_lines=False)
    texts = [r["text"] for r in rows]
    chk(not any("■" in t or "☜" in t or "픔" in t for t in texts),
        "①③ 기호·너무 작은 글자가 줄 목록에 없다", str(texts))
    chk(any(t.strip().startswith("[ 제목") and t.strip().endswith("]") for t in texts),
        "② `]` 는 살아서 같은 줄에 이어진다", str(texts))

    # ── ⑤ 제목 판정 ────────────────────────────────────────────
    st = {t: r["style"] for t, r in zip(texts, rows)}
    big = [t for t in texts if "아주 큰 제목" in t]
    chk(bool(big) and st[big[0]] == "title", "⑤ 크게 차이 나면 제목", str(st))
    body = [t for t in texts if "본문 첫째" in t]
    chk(bool(body) and st[body[0]] == "body", "⑤ 본문 크기는 내용", str(st))
    d.close()

    src_cls = inspect.getsource(tx._classify)
    chk("TITLE_MIN_GAP_PT" in src_cls, "⑤ 절대 차이 조건도 본다")
    chk(tx.TITLE_RATIO >= 1.35, "⑤ 배수 기준이 넉넉하다", str(tx.TITLE_RATIO))
    chk("bold" not in src_cls.lower() and "flags" not in src_cls,
        "⑤ 굵기는 판정에 쓰지 않는다(사용자 지시)")

    # ── ④ 일반 PDF 는 하나도 빼지 않는다 ─────────────────────────
    plain = Path(_fx.text_pdf())
    tx.close_cache()
    d2 = fitz.open(str(plain))
    page = d2.load_page(0)
    chk(tx._is_ocr_layer(page) is False, "④ 일반 PDF 는 OCR 층이 아니다")
    n_raw = len([1 for b in page.get_text("dict")["blocks"] if b.get("type") == 0
                 for ln in b.get("lines", [])
                 if "".join(s.get("text", "") for s in ln.get("spans", [])).strip()])
    chk(len(tx.page_lines(d2, str(plain), 0, tables="off", join_lines=False)) == n_raw,
        "④ 일반 PDF 는 한 줄도 빠지지 않는다", str(n_raw))
    d2.close()

    # ── ⑥ 낱말 → 줄 ───────────────────────────────────────────
    words = [{"surface": "항목", "x0": 100, "y0": 400, "x1": 160, "y1": 440, "conf": .95},
             {"surface": "시험방법", "x0": 900, "y0": 400, "x1": 1050, "y1": 440, "conf": .93},
             {"surface": "■", "x0": 1500, "y0": 100, "x1": 1560, "y1": 160, "conf": .9},
             {"surface": "픔", "x0": 1200, "y0": 300, "x1": 1206, "y1": 306, "conf": .4},
             {"surface": "모래당량", "x0": 100, "y0": 500, "x1": 190, "y1": 540, "conf": .9},
             {"surface": "50 이상", "x0": 900, "y0": 500, "x1": 1000, "y1": 540, "conf": .9}]
    wr = tx.lines_from_words(words, dpi=300)
    wt = [r["text"] for r in wr]
    chk(len(wr) == 2, "⑥ 낱말이 두 줄로 모인다", str(wt))
    chk(all(" | " in t for t in wt), "⑥ 넓게 벌어진 낱말은 다른 칸으로", str(wt))
    chk(not any("■" in t or "픔" in t for t in wt), "⑥ 잡음 낱말은 빠진다", str(wt))
    chk(all(r["rect"] and r["rect"][3] > r["rect"][1] for r in wr),
        "⑥ **좌표가 있다** — 본문 강조·PDF 반영이 된다", str(wr[0]["rect"]))
    chk(abs(wr[0]["rect"][0] - 100 * 72 / 300) < 0.1,
        "⑥ 픽셀 → pt 환산이 맞는다", str(wr[0]["rect"][0]))

    # ── ⑦ study/ocr 이 같은 규칙을 쓴다 ─────────────────────────
    from viewer.study import ocr as so
    src_oi = inspect.getsource(so.ocr_image)
    chk("keep_ocr_word" in src_oi, "⑦ ocr_image 가 같은 판정을 부른다")
    chk("continue" in src_oi.split("keep_ocr_word")[1][:200],
        "⑦ 버린 낱말은 **본문에서도** 빠진다(좌표와 본문이 어긋나지 않게)")
    src_wl = inspect.getsource(so.words_from_layer)
    chk("_is_ocr_layer" in src_wl,
        "⑦ 보이지 않는 글자층('layer' 로 판정되는 스캔본)에도 건다")
    chk("keep_ocr_word" in src_wl, "⑦ 같은 판정을 쓴다")

    # ── ⑧ OCR 단추·워커 ───────────────────────────────────────
    from viewer.widgets.text_panel import TextPanel
    tp = TextPanel()
    tp.show()
    app.processEvents()
    tp.set_page("a.pdf", 0, [{"text": "가", "style": "body",
                              "rect": (0, 0, 10, 10), "kind": "text"}])
    app.processEvents()
    chk(tp.btn_ocr.isVisible() is True, "⑧ 글이 있어도 단추가 보인다")
    chk(tp.btn_ocr.text() == "OCR 다시 읽기", "⑧ 문구", tp.btn_ocr.text())
    tp.set_page("a.pdf", 0, [], "스캔본입니다")
    app.processEvents()
    chk(tp.btn_ocr.text() == "OCR 로 읽기", "⑧ 글이 없으면 문구가 바뀐다",
        tp.btn_ocr.text())

    from viewer.workers import TextOcrPageWorker
    src_w = inspect.getsource(TextOcrPageWorker.run)
    chk("force_ocr=True" in src_w, "⑧ 다시 읽기는 텍스트층을 무시하고 OCR 한다")
    chk("fitz.open(self.doc_path)" in src_w,
        "⑧ 워커가 자기 문서를 따로 연다(응답성 SOT §4)")
    chk("save_page" in src_w, "⑧ 결과를 study.db 에 남긴다 — 단어장·검색이 같이 쓴다")
    from viewer.app import MainWindow
    # 260909: 범위를 고르게 되면서 워커 띄우기가 `_start_text_ocr` 로 갈라졌다.
    #   기본은 여전히 '보고 있는 쪽 하나' 다(대화상자 기본값, `test_text_ocr_opts.py` ④).
    src_a = inspect.getsource(MainWindow._on_text_need_ocr)
    chk("OcrOptionsDialog" in src_a and "current_page" in src_a,
        "⑧ 앱은 보고 있는 쪽을 기준으로 범위를 묻는다")
    chk("TextOcrPageWorker" in inspect.getsource(MainWindow._start_text_ocr),
        "⑧ 고른 범위를 워커로 넘긴다")

finally:
    try:
        tx.close_cache()
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print(NL + "=== " + ("ALL PASS" if not fails else "FAILURE (" + str(len(fails)) + ")") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
