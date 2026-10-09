# -*- coding: utf-8 -*-
"""261009-14: 문서를 열거나 쪽을 넘길 때의 메인 스레드 정지 두 가지 — 응답성 SOT §12 · §9.1.

설치본 실측(py-spy 스택):
  ① 쪽마다 텍스트 창 갱신 → `has_text_layer` → `ocr.decide_source` → `_image_coverage` 가 `page.get_image_rects()`
     로 **쪽의 모든 그림 MD5** 를 계산 — 스캔·큰 그림 쪽에서 1.9~2.8초.
  ② 문서를 처음 열 때 `ocr._latin_quality` 가 `wordfreq` 를 불러오고, wordfreq 가 `locate.this_dir()` →
     `inspect.stack()` 으로 자기 폴더를 찾느라 설치본에서 1.9초.

A. 실제 경로 `text_extract2.has_text_layer`(스캔본 픽스처)가 `get_image_rects` 를 부르지 않는다 · 점유율 값은 종전과 같다
B. 새 프로세스에서 OCR 판정의 영어 사전을 처음 쓸 때 `inspect.stack` 을 부르지 않는다(값은 같다)
C. MainWindow 가 시작 뒤 wordfreq 를 배경 스레드에서 미리 불러 둔다
E. 색인이 PyMuPDF 로 열기 전에 파일을 파이썬 read() 로 훑는다(설치본 빈 색인 1.0~2.75초 9회)
D. 한국어 띄어쓰기(kiwi)의 첫 호출이 GIL 을 1초 넘게 쥐지 않는다 — 기본 사전을 싣지 않는다(설치본 1.7초)
"""
import os, sys, subprocess, threading, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_perf_open_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


try:
    import fitz
    import test_fixtures as fx
    from viewer.study import ocr
    from viewer import text_extract2

    # ── A ──
    pdf = fx.scanned_pdf()
    calls = []
    orig = fitz.Page.get_image_rects

    def spy(self, *a, **k):
        calls.append(1)
        return orig(self, *a, **k)
    fitz.Page.get_image_rects = spy
    try:
        doc = fitz.open(str(pdf))
        page = doc[0]
        text_extract2.has_text_layer(doc, 0)
        cov = ocr._image_coverage(page)
    finally:
        fitz.Page.get_image_rects = orig
    chk(not calls, "A 쪽 판정(has_text_layer)이 그림 MD5(get_image_rects)를 부르지 않는다", "호출 %d회" % len(calls))
    total = page.rect.width * page.rect.height
    old = min(sum(abs(r.width * r.height) for img in page.get_images(full=True)
                  for r in page.get_image_rects(img[0])) / total, 1.0)
    chk(abs(cov - old) < 1e-6, "A 점유율 값은 종전과 같다", "%.4f vs %.4f" % (cov, old))

    # ── B: 새 프로세스(첫 import 여야 의미가 있다) ──
    code = r'''
import sys, inspect
sys.path.insert(0, r"%s")
n = [0]
_orig = inspect.stack
def _spy(*a, **k):
    n[0] += 1
    return _orig(*a, **k)
inspect.stack = _spy
from viewer.study import ocr
q = ocr._latin_quality("the asphalt mixture design practice for superpave volumetric")
print("STACK", n[0], "Q", round(q, 3))
''' % HERE
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", timeout=120)
    out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
    parts = out.split()
    stack_n = int(parts[1]) if len(parts) >= 4 and parts[0] == "STACK" else -1
    q = float(parts[3]) if stack_n >= 0 else -1
    chk(stack_n == 0, "B 영어 사전을 처음 쓸 때 inspect.stack 을 부르지 않는다(설치본 1.9초의 원인)", out)
    chk(q > 0.55, "B 사전 판정 값은 그대로(정상 영문 = 레이어 신뢰 기준 0.55 이상)", out)

    # ── D: 한국어 띄어쓰기의 첫 호출(새 프로세스 — 모델을 처음 짓는 순간) ──
    code_d = r'''
import sys, time, threading
sys.path.insert(0, r"%s")
from viewer import text_extract2 as tx
g = {"worst": 0.0, "last": time.perf_counter(), "run": True}
def hb():
    while g["run"]:
        now = time.perf_counter(); g["worst"] = max(g["worst"], now - g["last"]); g["last"] = now
        time.sleep(0.01)
threading.Thread(target=hb, daemon=True).start(); time.sleep(0.3)
r1 = tx._ko_wants_space("이 문서는 띄어쓰기가", "없는 문장입니다")
r2 = tx._ko_wants_space("시세조사", "결과를 반영하여")
g["run"] = False
print("GAP", round(g["worst"], 3), r1, r2)
''' % HERE
    r = subprocess.run([sys.executable, "-c", code_d], capture_output=True, text=True, encoding="utf-8", timeout=180)
    out = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
    parts = out.split()
    gap = float(parts[1]) if parts and parts[0] == "GAP" else 99.0
    chk(gap < 0.3, "D 한국어 띄어쓰기 첫 호출이 다른 스레드를 막지 않는다(종전 1.7초 → 사전 없이 0.46 → 261009-16 자식 프로세스)", out)
    chk(len(parts) == 4 and parts[2] == "True", "D 판정은 그대로(어절 경계는 띄운다)", out)

    # ── E: 색인은 PyMuPDF 에 넘기기 전에 파일을 파이썬 read() 로 먼저 훑는다(디스크 대기 동안 GIL 을 놓게) ──
    import tempfile, shutil as _sh
    from viewer.indexer import PdfIndex
    _td = tempfile.mkdtemp(prefix="polypdf_pref_")
    order = []
    ix = PdfIndex(os.path.join(_td, "index.db"))
    _orig_pref = PdfIndex._prefetch if hasattr(PdfIndex, "_prefetch") else None
    _orig_open = fitz.open
    try:
        if _orig_pref is not None:
            def _pref(self, fp):
                order.append(("prefetch", str(fp)))
                return _orig_pref(self, fp)
            PdfIndex._prefetch = _pref
        def _open(*a, **k):
            order.append(("fitz.open", str(a[0]) if a else ""))
            return _orig_open(*a, **k)
        fitz.open = _open
        from pathlib import Path as _P
        src = _P(fx.text_pdf())
        ix.index_file(src)
    finally:
        fitz.open = _orig_open
        if _orig_pref is not None:
            PdfIndex._prefetch = _orig_pref
        ix.close()
        _sh.rmtree(_td, ignore_errors=True)
    kinds = [k for k, _p in order]
    chk(kinds[:2] == ["prefetch", "fitz.open"], "E 색인은 fitz.open 전에 파일을 먼저 훑는다(찬 파일·백신 대기를 GIL 밖에서)", str(kinds[:4]))

    # ── C ──
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    started = []
    orig_start = threading.Thread.start

    def _start(self):
        started.append(self.name)
        return orig_start(self)
    threading.Thread.start = _start
    try:
        mw._warm_up_wordfreq()
    finally:
        threading.Thread.start = orig_start
    chk("wordfreq-warmup" in started, "C 시작 뒤 wordfreq 를 배경 스레드에서 미리 불러 둔다", str(started))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
