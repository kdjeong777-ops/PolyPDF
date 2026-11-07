# -*- coding: utf-8 -*-
"""261107-39(사용자 지시 '본문 읽기가 버튼으로 선택되지 않았는데, 가끔 단어 읽는 소리가 들려') — 단어장 SOT §11.5.

원인: 본문 단어장 단어 위 호버(hoverWord)가 '선택시읽기'(기본 켬)로 그 단어를 읽었다.
실제 창(MainWindow)·실제 본문 뷰포트에 마우스 이동·누름을 보낸다. 단어장 자료(study.db)와 음성(tts)만 대역.
A. 마우스를 단어 위로 옮기기만 하면 읽지 않는다 — 단어장 행은 고른 것으로 보인다
B. 단어를 누르면 읽는다 · '선택시읽기' 끄면 · 본문 읽기 중 · 끌기면 읽지 않는다
C. 목록이 다시 그려져도(쪽 다시 받기·종류 체크) 읽지 않는다
D. 목록에서 사용자가 행을 고르면 읽는다(종전 그대로)
수정 전 코드: A 에서 실패(호버로 읽음).
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPointF
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_speak_click_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


WORDS = ["pavement", "design", "asphalt", "binder"]


class FakeStore:
    def vocab_count(self, fkey):
        return 1
    def get_page_words(self, fkey, page):
        out, x = [], 72.0
        for w in WORDS:
            out.append({"surface": w, "x0": x, "y0": 100.0, "x1": x + 8.0 * len(w), "y1": 112.0})
            x += 8.0 * len(w) + 10
        return out
    def get_page_dpi(self, fkey, page):
        return 0
    def get_page_study(self, fkey, page):
        return [{"lemma": w, "lang": "eng", "level": "중급", "count": 1, "pos": i,
                 "definitions": [{"definition": "뜻 " + w, "source": "", "is_dict": False}], "examples": []}
                for i, w in enumerate(WORDS) if w != "design"]
    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeTts:
    def __init__(self):
        self.said = []
    def available(self):
        return True
    def speak(self, text, lang="eng", queue=False):
        self.said.append(text)
        return True
    def is_speaking(self):
        return False
    def stop(self):
        pass
    def __getattr__(self, name):
        return lambda *a, **k: None


root = tempfile.mkdtemp(prefix="polypdf_speakclick_")
try:
    src = os.path.join(root, "doc.pdf")
    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_text((72, 110), " ".join(WORDS), fontsize=11)
    d.save(src); d.close()

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(2200, 1000); mw.show(); app.processEvents()
    fake = FakeStore()
    tts = FakeTts()
    mw._study_get_store = lambda: fake
    mw._study_get_tts = lambda: tts
    mw._maybe_online_enrich = lambda *a, **k: None
    mw._enrich_rows_with_dict = lambda rows: rows
    mw._load_main(HistoryItem(src, 0, "", "bookmark")); QTest.qWait(700)
    m = mw.main_view
    tabs = mw.search_tabs
    mw.right_panel.setVisible(True); tabs.setVisible(True); QTest.qWait(300)
    if getattr(mw, "_panel_in_drawer", False) and not mw._drawer_open:
        mw._toggle_drawer(); QTest.qWait(300)
    tabs.setCurrentWidget(mw.study_panel); QTest.qWait(700)
    sp = mw.study_panel
    vp = m.view.viewport()

    def word_pos(word):
        x = 72.0
        for w in WORDS:
            if w == word:
                break
            x += 8.0 * len(w) + 10
        z = m._zoom
        return m.view.mapFromScene(QPointF((x + 4.0) * z, 106.0 * z))

    def cur_lemma():
        it = sp.tree.currentItem()
        top = sp._top_of(it) if it is not None else None
        return top.data(0, sp.DATA_LEMMA) if top is not None else None

    def click(pos):
        QTest.mouseMove(vp, pos); app.processEvents()
        QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=pos); app.processEvents()
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=pos); QTest.qWait(50)

    chk(sp.isVisible() and bool(getattr(m.view, "_hover_words", None)) and sp.is_speak_on_select(),
        "A0 단어장 창이 보이고 호버 영역이 있다 · '선택시읽기' 기본 켬")
    # ---- A ----
    tts.said.clear()
    off = m.view.mapFromScene(QPointF(500 * m._zoom, 700 * m._zoom))
    for w in ("pavement", "asphalt", "binder"):
        QTest.mouseMove(vp, off); app.processEvents()
        QTest.mouseMove(vp, word_pos(w)); QTest.qWait(30)
    chk(tts.said == [], "A1 단어 위로 마우스를 옮기기만 하면 읽지 않는다", str(tts.said))
    chk(cur_lemma() == "binder", "A2 호버한 단어는 단어장에서 고른 것으로 보인다", str(cur_lemma()))
    # ---- B ----
    tts.said.clear()
    click(word_pos("pavement"))
    chk(tts.said == ["pavement"] and cur_lemma() == "pavement", "B1 단어를 누르면 그 단어를 읽는다", str(tts.said))
    tts.said.clear()
    click(m.view.mapFromScene(QPointF(500 * m._zoom, 700 * m._zoom)))
    chk(tts.said == [], "B2 단어 밖을 누르면 읽지 않는다", str(tts.said))
    sp.chk_speak_sel.setChecked(False)
    click(word_pos("asphalt"))
    chk(tts.said == [], "B3 '선택시읽기' 끄면 눌러도 읽지 않는다", str(tts.said))
    sp.chk_speak_sel.setChecked(True)
    ra_active = mw.read_aloud.is_active
    mw.read_aloud.is_active = lambda: True
    mw.read_aloud.jump_to_point = lambda x, y: True
    click(word_pos("asphalt"))
    mw.read_aloud.is_active = ra_active
    chk(tts.said == [], "B4 본문 읽기 중의 누름은 읽기 자리 옮기기 — 따로 읽지 않는다", str(tts.said))
    p0 = word_pos("asphalt")
    QTest.mouseMove(vp, p0); QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=p0); app.processEvents()
    p1 = word_pos("binder")
    QTest.mouseMove(vp, p1); app.processEvents()
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=p1); QTest.qWait(50)
    chk(tts.said == [], "B5 끌어 고르면 읽지 않는다", str(tts.said))
    # ---- C ----
    tts.said.clear()
    sp._render(); QTest.qWait(50)
    sp._chk["고급"].setChecked(not sp._chk["고급"].isChecked()); QTest.qWait(50)
    mw._refresh_study_panel(m.current_page()); QTest.qWait(200)
    chk(tts.said == [], "C1 목록이 다시 그려져도 읽지 않는다", str(tts.said))
    # ---- D ----
    tts.said.clear()
    sp.tree.setFocus()
    sp.tree.setCurrentItem(sp.tree.topLevelItem(0)); QTest.qWait(50)
    first = sp.tree.topLevelItem(0).data(0, sp.DATA_LEMMA)
    chk(tts.said == [first], "D1 목록에서 고르면 읽는다(종전 그대로)", f"{tts.said} {first}")
    mw._skip_save_on_close = True
    mw.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\nALL PASS" if not fails else f"\nFAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 순서 크래시(판정 무관)를 피한다 — 다른 창 검사와 같다
