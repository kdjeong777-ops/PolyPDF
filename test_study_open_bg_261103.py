# -*- coding: utf-8 -*-
"""261103-12(지휘 세션 — beta.3 빌드 측정 회귀) PDF 를 열 때 메인이 사전 전체·NLTK 를 읽지 않는다 — 응답성 SOT §4.4.

beta.3 빌드 측정 T3(24 아스팔트, 단어장 있는 PDF): 처음 열 때 메인이 9.35초 섰다 —
`_load_main` → `_refresh_study_panel` → `_get_spot_terms` → `dict_store.all_terms`(사전 13,000여 항목) 와
`_compute_word_rects` → `lemma_en` → NLTK 첫 import. 단어장 창이 숨어 있어도 돌았다.

실제 창(MainWindow)에서 `_load_main` 으로 연다. 사전(dict.db)은 시험 프로필의 진짜 `DictStore` 에 항목을 많이 넣고,
단어장 자료(study.db)만 대역이다. 메인 스레드에서 `all_terms`·`_ensure_nltk` 가 불리면 실패.

A. 단어장 창이 숨어 있으면 열 때 단어장 갱신을 하지 않는다 — 메인에서 사전 전체·NLTK 를 읽지 않음, 앞 파일 밑줄·호버 없음
B. 단어장 창이 보이면 열 때 목록은 바로, 용어 인식 목록은 배경(`SpotTermsWorker`) — 다 되면 다단어 용어 행·밑줄이 붙는다
C. 읽는 사이 사전이 바뀌면(캐시 비움) 늦게 온 옛 목록을 버린다
D. 숨은 채 열었다가 단어장 창을 보이면 그 파일·쪽으로 다시 그린다
"""
import os, sys, time, tempfile, shutil, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
# 사용자 실제 설정 폴더(dict.db·settings.json)를 쓰지 않는다 — 마스터 §14.7.2 의 3
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_study_open_bg_%d" % os.getpid())
import modal_guard                    # 모달이 떠서 검사가 멈추지 않게(마스터 §14.7.2 의 6)
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


PAGES = [["pavement", "design", "asphalt"], ["asphalt", "layer", "pavement", "binder"]]
LEMMAS = {"pavement", "asphalt", "binder"}


class FakeStore:
    """study.db 대역 — `StudyStore` 의 읽기 길만(그 PDF 의 단어장 행·쪽 낱말·dpi)."""
    def __init__(self, pages):
        self.pages = pages
    def vocab_count(self, fkey):
        return 1
    def get_page_words(self, fkey, page):
        out, x = [], 72.0
        for w in self.pages[page]:
            out.append({"surface": w, "x0": x, "y0": 100.0, "x1": x + 8.0 * len(w), "y1": 112.0})
            x += 8.0 * len(w) + 10
        return out
    def get_page_dpi(self, fkey, page):
        return 0
    def get_page_study(self, fkey, page):
        return [{"lemma": w, "lang": "eng", "level": "중급", "count": 1, "pos": i,
                 "definitions": [], "examples": []}
                for i, w in enumerate(self.pages[page]) if w in LEMMAS]
    def __getattr__(self, name):
        return lambda *a, **k: None


# 메인 스레드에서 불렸는지 기록 — 진짜 함수를 감싼다
from viewer.study import dict_store as _ds, vocab as _vocab
on_main = []
_orig_all, _orig_nltk = _ds.DictStore.all_terms, _vocab._ensure_nltk


def _all_terms(self, *a, **k):
    if threading.current_thread() is threading.main_thread():
        on_main.append("all_terms")
    return _orig_all(self, *a, **k)


def _ensure_nltk():
    if threading.current_thread() is threading.main_thread() and _vocab._WN_READY is None:
        on_main.append("nltk")
    return _orig_nltk()


_ds.DictStore.all_terms = _all_terms
_vocab._ensure_nltk = _ensure_nltk


def wait_until(cond, sec=30.0):
    t = time.perf_counter()
    while time.perf_counter() - t < sec:
        if cond():
            return True
        QTest.qWait(50)
    return cond()


root = tempfile.mkdtemp(prefix="polypdf_studyopen_")
try:
    src = os.path.join(root, "doc.pdf")
    other = os.path.join(root, "other.pdf")
    for path in (src, other):
        d = fitz.open()
        for words in PAGES:
            pg = d.new_page(width=595, height=842)
            pg.insert_text((72, 110), " ".join(words), fontsize=11)
        d.save(path)
        d.close()

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(2200, 1000); mw.show(); app.processEvents()   # 넓게 — 좁으면 오른쪽 창이 서랍으로
    fake = FakeStore(PAGES)
    mw._study_get_store = lambda: fake
    mw._maybe_online_enrich = lambda *a, **k: None
    mw._enrich_rows_with_dict = lambda rows: rows
    # 큰 사전 — 실제 사전처럼 다단어 표제어가 많다. 그 가운데 하나가 1쪽 'asphalt layer'
    dic = mw._study_get_dict()
    dic.add_source("bigtest", "큰 시험 사전", kind="base")
    dic.add_entries("bigtest", [{"term_en": "term %d word" % i, "def_ko": "뜻 %d" % i} for i in range(20000)]
                    + [{"term_en": "asphalt layer", "def_ko": "아스팔트 층"}])
    mw._spot_terms_cache = None
    _vocab._WN_READY, _vocab._LEMMATIZER = None, None       # 이 프로세스에서 NLTK 를 아직 안 부른 상태로

    tabs = mw.search_tabs
    other_tab = next(tabs.widget(i) for i in range(tabs.count()) if tabs.widget(i) is not mw.study_panel)
    mw.right_panel.setVisible(True); tabs.setVisible(True); QTest.qWait(100)
    if getattr(mw, "_panel_in_drawer", False) and not mw._drawer_open:
        mw._toggle_drawer(); QTest.qWait(100)
    tb = tabs.tabBar()

    def click_tab(widget):
        QTest.mouseClick(tb, Qt.MouseButton.LeftButton, pos=tb.tabRect(tabs.indexOf(widget)).center())
        QTest.qWait(100)

    # ---- A 숨은 창 ----
    click_tab(other_tab)
    on_main.clear()
    t = time.perf_counter()
    mw._load_main(HistoryItem(src, 1, "", "bookmark")); app.processEvents()
    dt = time.perf_counter() - t
    chk(not mw.study_panel.isVisible(), "A0 단어장 창이 숨어 있다")
    chk(not on_main, "A1 숨은 창이면 열 때 메인에서 사전 전체(all_terms)·NLTK 를 읽지 않는다", str(on_main))
    chk(getattr(mw.main_view, "_vocab_marks", None) is None and not mw.main_view.view._hover_words,
        "A2 숨은 창이면 밑줄·호버 단어 없음")
    print("   숨은 창 열기 %.3f초" % dt)

    # ---- D 숨은 채 열고 → 단어장 창 보이기 ----
    on_main.clear()
    click_tab(mw.study_panel)
    chk(mw.study_panel.isVisible() and "asphalt" in {lm for lm, _l in mw.study_panel.shown_lemmas()},
        "D1 단어장 창을 보이면 그 파일·쪽 목록을 그린다")
    chk(not on_main, "D2 보이게 할 때도 메인에서 사전 전체·NLTK 를 읽지 않는다(배경)", str(on_main))
    ok = wait_until(lambda: "asphalt layer" in {lm for lm, _l in mw.study_panel.shown_lemmas()})
    chk(ok, "D3 배경 읽기가 끝나면 다단어 용어(asphalt layer) 행이 붙는다")
    chk(_vocab.nltk_ready(), "D4 NLTK 는 배경에서 불러 둔다")
    chk(not on_main, "D5 끝까지 메인에서 사전 전체·NLTK 를 읽지 않는다", str(on_main))

    # ---- B 보이는 창으로 다른 파일 열기 ----
    mw._spot_terms_cache = None
    on_main.clear()
    mw._load_main(HistoryItem(other, 1, "", "bookmark")); app.processEvents()
    chk(not on_main, "B1 보이는 창이어도 열 때 메인에서 사전 전체를 읽지 않는다", str(on_main))
    chk("asphalt" in {lm for lm, _l in mw.study_panel.shown_lemmas()}, "B2 단어장 목록은 바로 그린다")
    ok = wait_until(lambda: "asphalt layer" in {lm for lm, _l in mw.study_panel.shown_lemmas()})
    chk(ok, "B3 배경 읽기가 끝나면 용어 행이 붙는다")

    # ---- C 늦게 온 옛 목록 ----
    mw._spot_terms_cache = None
    old_gen = mw.__dict__.get("_spot_terms_gen")
    mw._spot_terms_cache = None                       # 읽는 사이 사전이 또 바뀜
    mw._on_spot_terms_built(old_gen, [("zzz", {"term_en": "zzz"})])
    chk(mw._spot_terms_cache is None or ("zzz", {"term_en": "zzz"}) not in (mw._spot_terms_cache or []),
        "C1 옛 세대 목록은 캐시에 넣지 않는다")
    ok = wait_until(lambda: mw._spot_terms_cache is not None)
    chk(ok and any(n == "asphaltlayer" or "asphalt" in n for n, _e in mw._spot_terms_cache or []),
        "C2 새로 읽은 목록이 들어온다")

    mw._skip_save_on_close = True
    mw.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("FAIL", len(fails), fails) if fails else print("ALL PASS")
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 순서 크래시(판정 무관)를 피한다 — 다른 창 검사와 같다
