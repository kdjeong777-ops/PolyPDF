# -*- coding: utf-8 -*-
"""261103-4(사용자 지시) 단어장 창이 보이면 본문에 단어장 단어 밑줄 — 단어장 SOT §11.2, 디자인 SOT §2.6.

실제 창(MainWindow)에서 탭 누르기·쪽 넘김·체크·오른쪽 창 닫기로 본문 장면(scene)의 밑줄을 센다.
단어장 자료(study.db)만 대역 — 그 PDF 의 단어장 행과 쪽 낱말을 앱 공급자와 같은 꼴로 준다.

A. 단어장 탭을 누르면 그 쪽의 단어장 단어에 밑줄(수준별 색 — 261107-33, 낱말 상자 바로 아래)
B. 쪽을 넘기면 새 쪽 단어에 밑줄 — 종전에는 쪽 넘김 처리기의 clear_word_highlights 가 곧바로 지웠다
C. 단어 클릭 강조·텍스트 창 강조를 걸거나 지워도 밑줄은 그대로 · 다시 렌더(확대)해도 그대로
D. 다른 탭을 누르면 지우고, 돌아오면 다시 · 오른쪽 창을 닫으면 지운다
E. '본문강조' 끄면 지우고 켜면 다시 · 읽기(TTS) 중에는 긋지 않는다
F. 설정 — 기본 켬, 옛 auto_highlight(꺼짐)는 읽지 않는다, body_highlight 로 저장
G. 그은 쪽 것만 — 다른 파일·다른 쪽에서는 다시 렌더해도 긋지 않는다
H. 응답성 — 단어 많은 쪽의 패널 갱신(대조·밑줄) 실측 < 1초(응답성 SOT §7)
"""
import os, sys, time, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from PyQt6.QtWidgets import QApplication, QGraphicsLineItem
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
# 사용자 실제 설정 폴더(색인·settings.json)를 쓰지 않는다 — 마스터 §14.7.2 의 3
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_vocab_marks_%d" % os.getpid())
import modal_guard                    # 모달이 떠서 검사가 멈추지 않게(마스터 §14.7.2 의 6)
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from viewer.vocab_marks import VOCAB_MARK_COLOR, VOCAB_MARK_COLORS
MARK_RGB = {QColor(c).rgb() for c in [VOCAB_MARK_COLOR, *VOCAB_MARK_COLORS.values()]}
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
        return [{"lemma": w, "lang": "eng", "level": "고급" if w == "binder" else "중급",
                 "count": 1, "pos": i,
                 "definitions": [], "examples": []}
                for i, w in enumerate(self.pages[page]) if w in LEMMAS]
    def __getattr__(self, name):          # 그 밖의 쓰기·조회는 빈 값
        return lambda *a, **k: None


def marks(m):
    """장면에서 단어장 밑줄 [(x0, y, x1)] (논리 px) — 수준별 색 어느 것이든(261107-33)."""
    out = []
    for it in m.scene.items():
        if isinstance(it, QGraphicsLineItem) and it.pen().color().rgb() in MARK_RGB:
            ln = it.line()
            out.append((round(ln.x1(), 1), round(ln.y1(), 1), round(ln.x2(), 1)))
    return sorted(out)


def wait(ms=700):          # 가벼운 넘김(_lite_follow)이 뒤에 패널을 고치는 시간까지
    QTest.qWait(ms)


root = tempfile.mkdtemp(prefix="polypdf_vocabmarks_")
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
    from viewer.widgets.study_panel import StudyPanel
    mw = MainWindow(); mw.resize(2200, 1000); mw.show(); app.processEvents()   # 넓게 — 좁으면 오른쪽 창이 서랍으로
    fake = FakeStore(PAGES)
    mw._study_get_store = lambda: fake
    mw._maybe_online_enrich = lambda *a, **k: None
    mw._enrich_rows_with_dict = lambda rows: rows     # 기본 사전이 '전문용어' 로 바꾸지 않게 — 종류는 대역이 정한다
    mw._load_main(HistoryItem(src, 0, "", "bookmark")); wait()
    m = mw.main_view
    tabs = mw.search_tabs
    mw.right_panel.setVisible(True); tabs.setVisible(True); wait()   # 오른쪽 창 열기(시험 프로필은 닫혀 시작)
    if getattr(mw, "_panel_in_drawer", False) and not mw._drawer_open:
        mw._toggle_drawer(); wait()          # 화면이 좁으면 오른쪽 창은 서랍 — 손잡이를 누른 것과 같다
    print("   서랍:", getattr(mw, "_panel_in_drawer", None), "탭 보임:", tabs.isVisible())
    tb = tabs.tabBar()

    def click_tab(widget):
        i = tabs.indexOf(widget)
        QTest.mouseClick(tb, Qt.MouseButton.LeftButton, pos=tb.tabRect(i).center())
        wait()

    other_tab = next(tabs.widget(i) for i in range(tabs.count()) if tabs.widget(i) is not mw.study_panel)
    if tabs.currentWidget() is mw.study_panel:
        click_tab(other_tab)
    chk(not marks(m), "A0 단어장 창이 안 보이면 밑줄 없음")

    # ---- A ----
    click_tab(mw.study_panel)
    chk(mw.study_panel.isVisible(), "A1 단어장 탭을 누르면 단어장 창이 보인다")
    mk = marks(m)
    chk(len(mk) == 2, "A2 그 쪽의 단어장 단어(pavement·asphalt)에 밑줄 2개", str(mk))
    z = m._zoom
    if mk:
        chk(abs(mk[0][0] - 72.0 * z) < 1.0 and 112.0 * z < mk[0][1] <= 112.0 * z + 4.0,
            "A3 밑줄은 낱말 상자 바로 아래(글자를 덮지 않는다 — 261107-33, 왼쪽 끝 = 상자 왼쪽)", str(mk[0]))
    cols = sorted({(it.pen().color().name(), it.pen().color().alpha()) for it in m.scene.items()
                   if isinstance(it, QGraphicsLineItem) and it.pen().color().rgb() in MARK_RGB})
    chk(cols == [(VOCAB_MARK_COLORS["중급"].lower(), 153)], "A4 중급 두 낱말 = 중급 색·반투명(261107-33)", str(cols))

    # ---- B ----
    m.go_to_page(1); wait()
    mk = marks(m)
    chk(m.current_page() == 1 and len(mk) == 3, "B1 쪽을 넘기면 새 쪽 단어(asphalt·pavement·binder)에 밑줄 3개", str(mk))
    n_hi = sum(1 for it in m.scene.items() if isinstance(it, QGraphicsLineItem)
               and it.pen().color().name() == VOCAB_MARK_COLORS["고급"].lower())
    chk(n_hi == 1, "B2 고급(binder) 은 고급 색 한 줄(261107-33)", str(n_hi))

    # ---- C ----
    mw._on_study_word_activated("asphalt", 1); app.processEvents()
    chk(len(marks(m)) == 3, "C1 단어 클릭 강조(초록)를 걸어도 밑줄 그대로")
    m.highlight_word_rects([(72, 100, 120, 112)], src="text_panel"); app.processEvents()
    m.clear_word_highlights(); app.processEvents()
    chk(len(marks(m)) == 3, "C2 텍스트 창 강조를 걸고 지워도 밑줄 그대로")
    m.zoom_reset(); wait(200)
    chk(len(marks(m)) == 3, "C3 다시 렌더(확대 바꿈)해도 밑줄 그대로")

    # ---- D ----
    click_tab(other_tab)
    chk(not mw.study_panel.isVisible() and not marks(m), "D1 다른 탭을 누르면 밑줄을 지운다")
    click_tab(mw.study_panel)
    chk(len(marks(m)) == 3, "D2 단어장 탭으로 돌아오면 다시 긋는다")
    tabs.setVisible(False); app.processEvents()
    chk(not marks(m), "D3 오른쪽 창(탭 묶음)을 닫으면 지운다")
    tabs.setVisible(True); wait()
    chk(len(marks(m)) == 3, "D4 다시 열면 다시 긋는다")

    # ---- E ----
    mw.study_panel.chk_hl.click(); app.processEvents()
    chk(not mw.study_panel.is_auto_highlight() and not marks(m), "E1 '본문강조' 를 끄면 지운다")
    mw.study_panel.chk_hl.click(); app.processEvents()
    chk(len(marks(m)) == 3, "E2 다시 켜면 다시 긋는다")
    ra = mw.read_aloud
    ra._active = True
    mw._refresh_study_panel(1); app.processEvents()
    chk(not marks(m), "E3 읽기(TTS) 중에는 긋지 않는다")
    ra._active = False
    mw._refresh_study_panel(1); app.processEvents()
    chk(len(marks(m)) == 3, "E4 읽기가 끝나면 다시 긋는다")
    lv_mid = mw.study_panel._chk["중급"]
    lv_mid.click(); app.processEvents()
    mk = marks(m)
    chk(not lv_mid.isChecked() and len(mk) == 1, "E5 '종류' 중급을 끄면 목록에 남은 단어(binder, 고급)만 밑줄", str(mk))
    lv_mid.click(); app.processEvents()
    chk(len(marks(m)) == 3, "E6 다시 켜면 바로 다시 긋는다")

    # ---- F ----
    p2 = StudyPanel()
    chk(p2.is_auto_highlight(), "F1 '본문강조' 기본 켬")
    p2.apply_settings({"auto_highlight": False})
    chk(p2.is_auto_highlight(), "F2 옛 auto_highlight(꺼짐)는 읽지 않는다")
    s = p2.get_settings()
    chk(s.get("body_highlight") is True and "auto_highlight" not in s, "F3 body_highlight 로 저장")
    p2.apply_settings({"body_highlight": False})
    chk(not p2.is_auto_highlight(), "F4 body_highlight 꺼짐은 복원")
    p2.deleteLater()

    # ---- G ----
    m.set_vocab_marks(0, [(72, 100, 140, 112)])          # 0쪽 것을 1쪽에서 걸면
    chk(not marks(m), "G1 다른 쪽의 밑줄은 지금 쪽에 긋지 않는다")
    mw._refresh_study_panel(1); app.processEvents()
    chk(len(marks(m)) == 3, "G2a 그 쪽으로 다시 고치면 다시 긋는다")
    mw._study_get_store = lambda: FakeStore([[], []])    # 다른 파일의 같은 쪽 — 단어장 단어 없음
    mw._load_main(HistoryItem(other, 1, "", "bookmark")); wait()
    m._render_current(); app.processEvents()
    chk(not marks(m), "G2 다른 파일로 바뀌면 앞 파일 밑줄을 다시 렌더해도 긋지 않는다")

    # ---- H ----
    big = [["pavement" if i % 7 == 0 else ("asphalt" if i % 11 == 0 else "w%d" % i) for i in range(900)]] * 2
    bigstore = FakeStore(big)
    mw._study_get_store = lambda: bigstore
    LEMMAS |= {"w%d" % i for i in range(0, 900, 3)}
    mw._load_main(HistoryItem(src, 0, "", "bookmark")); wait()
    t = time.perf_counter()
    mw._refresh_study_panel(0); app.processEvents()
    dt = time.perf_counter() - t
    print("   패널 갱신(낱말 900·단어장 행 %d) %.3f초, 밑줄 %d" % (len(bigstore.get_page_study(0, 0)), dt, len(marks(m))))
    chk(dt < 1.0 and len(marks(m)) > 100, "H1 단어 많은 쪽의 패널 갱신(대조·밑줄) < 1초", "%.3f" % dt)

    mw._skip_save_on_close = True
    mw.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("FAIL", len(fails), fails) if fails else print("ALL PASS")
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 순서 크래시(판정 무관)를 피한다 — 다른 창 검사와 같다
