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

    # ── ⑧ 한글 띄어쓰기 (SOT §3.6.2 · 단어학습 §14.10) ───────────
    from viewer import text_extract2 as tx
    chk(tx.CJK_GLUE_GAP > tx.GLUE_GAP,
        '⑧ 한글은 라틴보다 붙임 기준이 넉넉하다',
        '%.2f > %.2f' % (tx.CJK_GLUE_GAP, tx.GLUE_GAP))
    chk(tx._is_cjk_pair('제', '8') and tx._is_cjk_pair('8', '조'),
        '⑧ 숫자가 섞여도 한쪽이 한글이면 한글 규칙')
    chk(not tx._is_cjk_pair('the', 'layer'), '⑧ 라틴끼리는 라틴 규칙')
    # 글자 높이 20pt 기준: 낱말 안 0.30(=6pt) 은 붙고, 낱말 사이 0.55(=11pt) 는 띈다
    def line(gaps, texts, h=20.0):
        fr, x = [], 0.0
        for g, t in zip([0.0] + gaps, texts):
            x += g
            fr.append(((x, 0.0, x + h * len(t), h), t, h))
            x += h * len(t)
        return tx._merge_rows(fr)[0][1]
    got = line([6.0, 11.0], ['재생', '첨가제', '사용'])
    chk(got == '재생첨가제 사용', '⑧ 한글 — 낱말 안은 붙이고 사이는 띈다', repr(got))
    got2 = line([6.0, 11.0], ['the', 'layer', 'to'], h=12.0)
    chk(got2 == 'the layer to', '⑧ 라틴은 낱말마다 띈다', repr(got2))

    if HAVE_TESS:
        sp = fitz.open()
        spp = sp.new_page(width=595, height=842)
        spp.insert_text((60, 200), '1. 재생첨가제 사용 규제 사항', fontsize=20,
                        fontfile=KRFONT, fontname='kr')
        sppath = root / 'sp.pdf'
        sp.save(str(sppath))
        sp.close()
        sd = fitz.open(str(sppath))
        r = so.build_page(sd, 0, lang=so.resolve_lang('kor+eng'), dpi=300,
                          force_ocr=True)
        rows = tx.lines_from_words(r['words'], dpi=r['dpi'])
        sd.close()
        txt = rows[0]['text'] if rows else ''
        chk('사용 규제 사항' in txt, '⑧ 실제 OCR 에서 낱말 사이가 띄어진다', repr(txt))
        chk('가 제' not in txt and '재 생' not in txt,
            '⑧ 낱말 안이 흩어지지 않는다(사용자 보고)', repr(txt))
        chk('사용 규제 사항' in r['text'],
            '⑧ **본문(검색·단어장)도** 같은 규칙으로 이어진다', repr(r['text'][:40]))

    # ── ⑪ 숫자 띄어쓰기 (SOT §3.6.2, 260909-3 사용자 보고) ────────
    chk(tx._is_num_pair('9', '5') and tx._is_num_pair('.', '6%'),
        '⑪ 한쪽이 한 글자면 수를 잇는다')
    chk(not tx._is_num_pair('95.', '6%'),
        '⑪ 둘 다 두 글자 이상이면 잇지 않는다(이어 붙인 것이 아니라 **원래 토막**으로 잰다)')
    chk(not tx._is_num_pair('3.9261', '4.0065'),
        '⑪ 둘 다 온전한 수면 붙이지 않는다 — 다른 값이다')
    chk(not tx._is_num_pair('1', 'BIN'), '⑪ 숫자가 아닌 것과는 잇지 않는다')
    for src_t, want in (('9 5 . 6%', '95.6%'), ('4 . 4', '4.4'),
                        ('1 000.0', '1000.0'), ('3 1 .0', '31.0'),
                        ('2 . 3 9 2', '2.392'), ('1 8.2', '18.2')):
        got = tx.fix_number_spaces(src_t)
        chk(got == want, '⑪ 쪼개진 수를 붙인다 — %r' % src_t, repr(got))
    for keep in ('3.9261 4.0065', '15.3 16.0 22.0', '제8조 2026년02월',
                 '1 BIN', 'PG 64-22', '20 mm'):
        chk(tx.fix_number_spaces(keep) == keep,
            '⑪ 멀쩡한 것은 건드리지 않는다 — %r' % keep,
            repr(tx.fix_number_spaces(keep)))
    chk(tx.fix_number_spaces('계 | 1 000.0 | 1 OO.0') == '계 | 1000.0 | 1 OO.0',
        '⑪ 칸 구분(|) 을 넘어 붙지 않는다')

    # ── ⑫ 0 을 O 로 읽은 것 (SOT §3.6.3, 260909-4 사용자 지시) ────
    #   "숫자가 명확할 때만 수정하도록 하는 규칙" — 네 조건을 모두 만족할 때만.
    FIX = (('44 . O', '44.0'), ('O .5', '0.5'), ('1 OO.O', '100.0'),
           ('1 OOO.0', '1000.0'), ('2026년O2월', '2026년02월'),
           ('5 . O', '5.0'), ('42 . O', '42.0'), ('3.O', '3.0'),
           ('1O형', '10형'))
    for src_t, want in FIX:
        got = tx.fix_number_spaces(tx.fix_number_ocr(src_t))
        chk(got == want, '⑫ 수가 분명하면 되돌린다 — %r' % src_t, repr(got))
    KEEP = ('No. 1',        # ④ 앞이 영문 글자
            'IoT',          # ② 숫자가 없다
            '1L', '100ml',  # ③ 수의 모양이 아니다
            'O', 'OO', 'O형', 'l',   # ② 진짜 숫자가 없다
            '3.9261 4.0065',         # ③ 소수점이 둘
            '2 B I N', 'PG 64-22', 'Cotton wool', 'TABLE 10', '처l 크기')
    for keep in KEEP:
        got = tx.fix_number_ocr(keep)
        chk(got == keep, '⑫ 분명하지 않으면 건드리지 않는다 — %r' % keep, repr(got))
    chk(tx.fix_number_ocr('O') == 'O' and tx.fix_number_ocr('1O') == '10',
        '⑫ 곁에 진짜 숫자가 있을 때만 바꾼다(② 조건)')
    chk(tx.fix_number_ocr('44 . O') == '44 . 0',
        '⑫ 글자만 바꾸고 빈칸은 그대로 둔다(붙이기는 §3.6.2 가 한다)',
        repr(tx.fix_number_ocr('44 . O')))

    # ── ⑨ 글자층+그림 섞인 쪽은 합친다 (SOT §3.1.3) ──────────────
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new('RGB', (1000, 260), 'white')
    dr = ImageDraw.Draw(im)
    # 합치는 **구조**를 보는 검사다 — 한글 OCR 품질은 ⑧ 에서 따로 본다.
    dr.text((40, 60), 'TABLE ANALYSIS RESULT',
            font=ImageFont.truetype(KRFONT, 90), fill=(0, 0, 0))
    cap = root / 'cap.png'
    im.save(str(cap))
    mx = fitz.open()
    mp = mx.new_page(width=595, height=842)
    mp.insert_text((50, 80), '표지 제목입니다', fontsize=18,
                   fontfile=KRFONT, fontname='kr')
    # 글자층이 '쓸 만하다' 고 판정될 만큼은 있어야 한다(단어학습 SOT §14.3)
    for i in range(8):
        mp.insert_text((50, 120 + i * 22), '본문 문장이 이어지는 줄 ' + str(i),
                       fontsize=12, fontfile=KRFONT, fontname='kr')
    mp.insert_image(fitz.Rect(50, 400, 545, 545), filename=str(cap))
    mpath = root / 'mixed.pdf'
    mx.save(str(mpath))
    mx.close()
    md = fitz.open(str(mpath))
    chk(tx.has_text_layer(md, 0) is True, '⑨ 글자층이 있는 쪽이다')
    from viewer.workers import TextOcrPageWorker as _W
    chk(_W._skippable(md, 0) is False,
        '⑨ 그림이 섞이면 건너뛰지 않는다(그림 속 글을 채워야 한다)')
    base = [r['text'] for r in tx.page_lines(md, str(mpath), 0, tables='off')]
    chk(any('표지 제목' in t for t in base), '⑨ 글자층 줄은 원래 나온다',
        str(base[:2]))
    if HAVE_TESS:
        r = so.build_page(md, 0, lang=so.resolve_lang('kor+eng'), dpi=300,
                          force_ocr=True, drop_watermark_bg=True)
        merged = tx.page_lines(md, str(mpath), 0, tables='off',
                               ocr_words=r['words'], ocr_dpi=r['dpi'])
        mt = [x['text'] for x in merged]
        chk(any('표지 제목입니다' == t for t in mt),
            '⑨ 글자층 줄이 **그대로** 남는다(짐작한 글자로 바뀌지 않는다)', str(mt[:2]))
        chk(any('ANALYSIS' in t.upper() for t in mt),
            '⑨ 그림 속 글이 더해진다', str([t for t in mt if '본문 문장' not in t]))
        chk(any(x['kind'] == 'ocr' for x in merged),
            '⑨ 더해진 줄은 어디서 왔는지 표시된다')
    md.close()

    # 순수 텍스트 쪽은 건너뛴다
    pu = fitz.open()
    pp = pu.new_page(width=595, height=842)
    for i in range(10):
        pp.insert_text((50, 100 + i * 20), '순수 텍스트 줄입니다 ' + str(i),
                       fontsize=11, fontfile=KRFONT, fontname='kr')
    ppath = root / 'pure.pdf'
    pu.save(str(ppath))
    pu.close()
    pd = fitz.open(str(ppath))
    chk(_W._skippable(pd, 0) is True, '⑨ 그림 없는 글자 쪽은 건너뛴다')
    pd.close()

    # ── ⑩ 세대 표 · 되돌리기 ────────────────────────────────────
    asrc2 = inspect.getsource(MainWindow._start_text_ocr)
    chk('_ocr_token' in asrc2 and '_text_token' not in asrc2.split('#')[0],
        '⑩ OCR 은 화면 갱신과 **다른 세대 표**를 쓴다(전체 읽기가 첫 쪽에서 멈추던 결함)')
    dsrc2 = inspect.getsource(MainWindow._on_text_ocr_done)
    chk('_ocr_token' in dsrc2, '⑩ 결과도 그 표로 확인한다')
    nsrc = inspect.getsource(MainWindow._on_text_need_ocr)
    chk('revert' in nsrc, '⑩ [원래 글자층 보기] 로 되돌릴 수 있다')
    dlg2 = OcrOptionsDialog(page=0, page_count=5)
    chk(dlg2.values()['skip_text'] is True, '⑨ 글자 있는 쪽 건너뛰기가 기본 켬')
    chk(dlg2.values()['revert'] is False, '⑩ 되돌리기는 눌렀을 때만')

    # ── ⑬ 단어장은 OCR 이 끝난 뒤 (SOT §3.1.4 · 단어학습 §14.12) ──
    from viewer.workers import StudyVocabWorker
    vsrc = inspect.getsource(StudyVocabWorker.run)
    chk('build_vocab' in vsrc, '⑬ 어휘만 다시 만든다')
    chk('force_ocr' not in vsrc and 'render_page' not in vsrc,
        '⑬ OCR 을 다시 하지 않는다 — 이미 저장된 글만 훑는다')
    chk('vocab_count' in vsrc,
        '⑬ 단어장이 이미 있는 문서만 — 만든 적 없는 문서에 몰래 만들지 않는다')
    ssrc = inspect.getsource(MainWindow._start_text_ocr)
    chk('_rebuild_study_vocab' in ssrc and 'w.finished.connect' in ssrc,
        '⑬ OCR 워커가 **끝난 뒤** 잇는다(쪽마다가 아니라 한 번)')
    rsrc = inspect.getsource(MainWindow._rebuild_study_vocab)
    chk('run_in_thread' in rsrc, '⑬ 워커에서 돈다(응답성 §4 ②)')

    # ── ⑮ 단어장은 정제된 글로 (SOT §3.1.5 · 단어학습 §14.12) ────
    #   날것 `ocr_page.text` 로 만들면 기호 줄·흩어진 표 칸·끊긴 낱말이 낱말이 된다.
    _scan = Path(_fx.scanned_form_pdf())
    cl = tx.clean_page_texts(str(_scan))
    chk(bool(cl) and cl[0][0] == 0, '⑮ 쪽마다 정제된 글을 돌려준다', str(len(cl)) + '쪽')
    ct = cl[0][1] if cl else ''
    chk('■' not in ct and '☜' not in ct,
        '⑮ 기호만 남은 줄이 낱말이 되지 않는다', repr(ct[:40]))
    chk('제품종류 | 일반아스팔트혼합물' in ct,
        '⑮ 표 한 행이 한 줄로 — 칸이 흩어지지 않는다', repr(ct.splitlines()[:1]))
    chk(tx.clean_page_texts(str(root / 'no_such.pdf')) == [],
        '⑮ 못 열면 빈 목록 — 부르는 쪽이 날것으로 돌아간다')
    from viewer.study import vocab as _vocab
    vsig = inspect.signature(_vocab.build_vocab)
    chk('pages_text' in vsig.parameters, '⑮ build_vocab 이 정제된 글을 받는다')
    chk(vsig.parameters['pages_text'].default is None,
        '⑮ 안 주면 종전대로 — 뒤로 호환')
    vs = inspect.getsource(StudyVocabWorker._clean_texts)
    chk('clean_page_texts' in vs, '⑮ 갱신 워커가 정제된 글을 쓴다')
    from viewer.workers import StudyBuildWorker
    bs = inspect.getsource(StudyBuildWorker.run)
    chk('clean_page_texts' in bs, '⑮ 단어장 생성도 정제된 글을 쓴다')

    # ── ⑭ 도구의 OCR · 보기의 텍스트 (SOT §2.1) ──────────────────
    asrc3 = inspect.getsource(MainWindow._action_ocr_read)
    chk('_vm_text' in asrc3 and '_on_text_need_ocr' in asrc3,
        '⑭ 도구의 [OCR] 은 텍스트 창을 켜고 대화상자를 연다')
    chk(hasattr(MainWindow, '_vm_text'), '⑭ 보기의 [텍스트] 가 있다')
    vt = inspect.getsource(MainWindow._vm_text)
    chk('text_panel' in vt and 'setCurrentWidget' in vt,
        '⑭ 우측 창을 켜고 텍스트 탭으로 간다')

finally:
    shutil.rmtree(root, ignore_errors=True)

print(NL + "=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
