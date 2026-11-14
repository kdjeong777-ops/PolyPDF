# -*- coding: utf-8 -*-
"""261114-11: 쪽 훑기가 비싼 PDF(작은 그림 수만 개로 깐 질감 배경)를 열 때 메인이 서지 않는다
(응답성 SOT §6 표·§4.7 ③·⑤, 단어학습 SOT §14.18).

사용자 보고: "이건 분류는 잘 맞는데, 이 파일을 볼때만 버벅거려서 다음 파일로 잘 넘어가지 않아"(TRB9.pdf — 발표 슬라이드,
첫 쪽 배경이 4×4pt 그림 23,296개). 실측: 쪽 내용을 한 번 훑는 데 0.25~1초인데 메인이 글자층 판정(`ocr.decide_source` 한 번 9.4초 —
그림 자리 읽기·`fitz.Rect` 2만 3천 개)을 본문·텍스트 창·쪽 낱말에서 여러 번, 쪽 낱말(`_view_src`)을 그릴 때마다, 썸네일이 표지를 또 그려
한 번 열기에 메인 8.6초·↑↓ 넘김 중 15~19초 정지.

픽스처 `test_fixtures.tiled_bg_pdf()` — 첫 쪽에 4×4pt 그림 1만 4천 번 + 보이는 영문 글(같은 성질).
A. 글자층 판정은 같은 답이고, 두 번째부터는 기억한 것(다른 문서 객체로 같은 파일을 물어도)
B. 안 보이는 층이 아니면 그림 점유율을 재지 않는다 — 안 보이는 OCR 층 스캔 쪽은 종전대로 'ocr'(scanned-page)
C. 실제 MainWindow 로 열 때: 쪽 낱말을 읽지 않는다(끌어 고르기를 시작하면 읽는다)
D. 텍스트 창은 여는 이벤트 안에서 돌지 않고 한 박자 뒤에 따라간다
E. 표지 썸네일은 본문이 그린 것을 쓴다(그 쪽을 다시 그리지 않는다)
F. 여는 동안 가장 긴 멈춤 < 1초
"""
import os, sys, time, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(300, exit=True)
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer, QElapsedTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QStandardPaths.setTestModeEnabled(True)               # 검사 작성 SOT §14.7.2 의 3
QCoreApplication.setApplicationName("polypdf_tiled_page_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "질감 배경", echo=False)   # §14.7.2 의 6
import test_fixtures
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(ms=300):
    t = time.perf_counter()
    while (time.perf_counter() - t) * 1000 < ms:
        app.processEvents(); QTest.qWait(5)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tiled_"))
try:
    src = test_fixtures.tiled_bg_pdf()
    pdf = str(tmp / "tiled_slides.pdf")
    shutil.copy(src, pdf)                                  # 검사마다 새 경로 — 프로세스 기억이 앞 검사 것을 쓰지 않게
    from viewer.study import ocr

    # ── A ──
    d1 = fitz.open(pdf)
    p1 = d1.load_page(0)
    plain = getattr(ocr, "_decide_source", ocr.decide_source)(p1)     # 기억 없이(수정 전 코드에는 이 이름이 없다 — 그때는 같은 함수)
    t = time.perf_counter(); r1 = ocr.decide_source(p1); a1 = (time.perf_counter() - t) * 1000
    t = time.perf_counter(); r2 = ocr.decide_source(p1); a2 = (time.perf_counter() - t) * 1000
    d2 = fitz.open(pdf)
    t = time.perf_counter(); r3 = ocr.decide_source(d2.load_page(0)); a3 = (time.perf_counter() - t) * 1000
    print(f"  실측: 판정 {a1:.0f}ms → 다시 {a2:.0f}ms · 다른 문서 객체 {a3:.0f}ms")
    chk(r1[0] == r2[0] == r3[0] == plain[0] == "layer", "A 판정은 같은 답(보이는 글 = layer)", str((plain, r1, r2, r3)))
    chk(a2 < 50, "A ★ 같은 쪽을 다시 물으면 기억한 것(종전: 매번 다시 — 쪽 하나 1.7~2.4초)", f"{a2:.0f}ms")
    chk(a3 < 50, "A 다른 문서 객체로 같은 파일을 물어도 기억한 것(본문·텍스트 창·배경 정보 줄)", f"{a3:.0f}ms")
    d2.close()

    # ── B ──
    called = []
    _orig_cov = ocr._image_coverage
    ocr._image_coverage = lambda pg: (called.append(1), _orig_cov(pg))[1]
    try:
        d3 = fitz.open(pdf)
        p3 = d3.load_page(0)
        getattr(ocr, "_decide_source", ocr.decide_source)(p3)
        chk(not called, "B 안 보이는 층이 아니면 그림 점유율(그림 자리 1만 4천 개)을 재지 않는다", f"{len(called)}번")
        d3.close()
        scan = str(tmp / "scan_layer.pdf")                 # 전면 그림 + 안 보이는 OCR 층(render mode 3) — 종전대로 ocr
        ds = fitz.open()
        sp = ds.new_page(width=595, height=842)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 560), False)
        pix.set_rect(pix.irect, (235, 235, 230))
        sp.insert_image(sp.rect, pixmap=pix)
        for k in range(12):
            sp.insert_text((60, 90 + k * 40), "invisible scanned ocr layer words line %d" % k, fontsize=14, render_mode=3)
        ds.save(scan); ds.close()
        dd = fitz.open(scan)
        rs = ocr.decide_source(dd.load_page(0))
        chk(rs[0] == "ocr" and rs[1].get("reason") == "scanned-page", "B 안 보이는 OCR 층 스캔 쪽은 종전대로 ocr(scanned-page)", str(rs))
        dd.close()
    finally:
        ocr._image_coverage = _orig_cov
    d1.close()

    # ── C·D·E·F 실제 창 ──
    from viewer.app import MainWindow
    from viewer.widgets.main_view import MainView
    from viewer.pdf_doc import PdfDocument
    from viewer.history import HistoryItem
    rendered = []
    _orig_rt = PdfDocument.render_thumbnail
    PdfDocument.render_thumbnail = lambda self, page, *a, **k: (rendered.append(int(page)), _orig_rt(self, page, *a, **k))[1]
    words_calls = []
    _orig_lw = MainView._load_page_words
    MainView._load_page_words = lambda self: (words_calls.append(1), _orig_lw(self))[1]
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    spin(800)
    inside = {"open": False, "text_inside": 0, "text_after": 0}
    _orig_now = mw._load_main_now

    def _spy_now(item):
        inside["open"] = True
        try:
            return _orig_now(item)
        finally:
            inside["open"] = False
    mw._load_main_now = _spy_now
    _orig_omp = mw._on_main_page_changed

    def _spy_omp(page):
        inside["text_inside" if inside["open"] else "text_after"] += 1
        return _orig_omp(page)
    mw._on_main_page_changed = _spy_omp
    beat = QElapsedTimer(); beat.start(); worst = [0]
    hb = QTimer(); hb.setInterval(10)
    hb.timeout.connect(lambda: worst.__setitem__(0, max(worst[0], beat.restart())))
    hb.start(); spin(50); worst[0] = 0; beat.restart()
    words_calls.clear(); rendered.clear()
    mw._load_main(HistoryItem(pdf, 0, "", "bookmark"))
    t = time.perf_counter()
    while (not mw.main_view.current_file() or Path(mw.main_view.current_file()).name != "tiled_slides.pdf") and time.perf_counter() - t < 15:
        app.processEvents(); QTest.qWait(5)
    spin(2500)
    hb.stop()
    mv = mw.main_view
    chk(Path(mv.current_file() or "").name == "tiled_slides.pdf", "준비 — 본문에 열렸다")
    chk(not words_calls and mv._page_words == [], "C ★ 열 때 쪽 낱말을 읽지 않는다(종전: 그릴 때마다 — 그 쪽 4.7초)", f"{len(words_calls)}번")
    mv._sel_begin(80, 300)
    chk(bool(mv._page_words), "C 끌어 고르기를 시작하면 그때 읽는다", str(len(mv._page_words)))
    mv.clear_text_selection()
    chk(inside["text_inside"] == 0 and inside["text_after"] >= 1,
        "D 텍스트 창은 여는 이벤트 안이 아니라 한 박자 뒤에", str(inside))
    chk(0 not in rendered, "E 표지 썸네일은 본문이 그린 것(쪽 0 을 다시 그리지 않음)", str(rendered[:6]))
    chk(worst[0] < 1000, "F 여는 동안 가장 긴 멈춤 < 1초", f"{worst[0]}ms")
    print(f"  실측: 여는 동안 가장 긴 멈춤 {worst[0]}ms")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
