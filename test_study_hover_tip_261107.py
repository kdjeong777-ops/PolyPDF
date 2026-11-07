# -*- coding: utf-8 -*-
"""261107-32(사용자 지시 '단어장에 있는 단어를 본뷰어에서 마우스로 가리키면 관련 뜻이 호버링') — 단어장 SOT §11.3.

실제 창(MainWindow)·실제 본문 뷰포트에 마우스 이동과 Qt 툴팁 이벤트(QHelpEvent)를 보낸다. 단어장 자료(study.db)만 대역.
A. 단어 위 → 풍선: 굵은 표제어 + 첫 한글 뜻 + 첫 영어 뜻 + 출처, 긴 뜻은 HOVER_TIP_CHARS 에서 '…'
B. `한글뜻` 끄면 한글 뜻이 빠진다 · `참고문헌` 끄면 출처가 빠진다
C. `뜻 풍선` 끄면 띄우지 않는다 · 설정에 hover_tip 으로 저장
D. 수준 체크로 숨긴 행은 띄우지 않는다
E. 마우스 단추를 누른 채·그리기 도구가 켜진 동안은 띄우지 않는다
F. 단어 밖·단어장 창이 안 보이면 띄우지 않는다
G. 마우스 이동만으로는 사전·study.db 를 읽지 않는다(응답성)
수정 전 코드: 풍선이 없다 → A 부터 실패.
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from PyQt6.QtWidgets import QApplication, QToolTip
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QEvent, QPoint, QPointF
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_hover_tip_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


WORDS = ["pavement", "design", "asphalt", "binder"]
LONG = "a" * 30 + " very long English definition that keeps going well beyond the limit of the hover popup text"
DEFS = {
    "pavement": [{"definition": "포장, 포장도로", "source": "도로 용어집", "is_dict": True},
                 {"definition": "포장면", "source": "도로 용어집", "is_dict": True},
                 {"definition": "a paved surface", "source": "WordNet", "is_dict": True}],
    "asphalt": [{"definition": "아스팔트", "source": "", "is_dict": False}],
    "binder": [{"definition": LONG, "source": "", "is_dict": False}],
}
reads = {"n": 0}


class FakeStore:
    def vocab_count(self, fkey):
        return 1
    def get_page_words(self, fkey, page):
        reads["n"] += 1
        out, x = [], 72.0
        for w in WORDS:
            out.append({"surface": w, "x0": x, "y0": 100.0, "x1": x + 8.0 * len(w), "y1": 112.0})
            x += 8.0 * len(w) + 10
        return out
    def get_page_dpi(self, fkey, page):
        return 0
    def get_page_study(self, fkey, page):
        reads["n"] += 1
        return [{"lemma": w, "lang": "eng", "level": "고급" if w == "binder" else "중급",
                 "count": 1, "pos": i, "definitions": [dict(d) for d in DEFS[w]], "examples": []}
                for i, w in enumerate(WORDS) if w in DEFS]
    def __getattr__(self, name):
        return lambda *a, **k: None


root = tempfile.mkdtemp(prefix="polypdf_hovertip_")
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
    mw._study_get_store = lambda: fake
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

    shown = []
    _show = QToolTip.showText
    def _rec(*a, **k):                     # 띄운 글을 적는다(숨기기는 Qt 가 늦게 해 isVisible 로는 못 본다)
        shown.append(a[1] if len(a) > 1 else k.get("text", ""))
        return _show(*a, **k)
    QToolTip.showText = staticmethod(_rec)

    def tip_at(pos, buttons=None):
        """실제 마우스 이동 + 툴팁 이벤트(Qt 가 늦춤 뒤에 보내는 것과 같은 QHelpEvent). 이 이벤트로 띄운 글(없으면 빈 글)."""
        QTest.mouseMove(vp, pos); app.processEvents()
        shown.clear()
        ev = QHelpEvent(QEvent.Type.ToolTip, pos, vp.mapToGlobal(pos))
        QApplication.sendEvent(vp, ev); app.processEvents()
        return shown[-1] if shown else ""

    chk(sp.isVisible() and bool(getattr(m.view, "_hover_words", None)), "A0 단어장 창이 보이고 호버 영역이 있다")
    # ---- A ----
    t = tip_at(word_pos("pavement"))
    chk("<b>pavement</b>" in t and "포장, 포장도로" in t and "포장면" not in t and "a paved surface" in t,
        "A1 굵은 표제어 + 첫 한글 뜻 + 첫 영어 뜻", repr(t))
    chk("— 도로 용어집" in t and "— WordNet" in t, "A2 뜻 끝에 출처(참고문헌 켬)", repr(t))
    from viewer.widgets.study_panel import HOVER_TIP_CHARS
    sp._chk["고급"].setChecked(True); QTest.qWait(100)
    t = tip_at(word_pos("binder"))
    chk("…" in t and LONG[:HOVER_TIP_CHARS - 1] in t and LONG[:HOVER_TIP_CHARS + 5] not in t, "A3 긴 뜻은 HOVER_TIP_CHARS 에서 '…'", repr(t)[:120])
    # ---- B ----
    sp.chk_ko.setChecked(False)
    t = tip_at(word_pos("pavement"))
    chk(t and "포장" not in t and "a paved surface" in t, "B1 한글뜻 끄면 한글 뜻이 빠진다", repr(t))
    sp.chk_ko.setChecked(True); sp.chk_ref.setChecked(False)
    t = tip_at(word_pos("pavement"))
    chk(t and "도로 용어집" not in t and "포장, 포장도로" in t, "B2 참고문헌 끄면 출처가 빠진다", repr(t))
    sp.chk_ref.setChecked(True)
    # ---- C ----
    chk_tip = getattr(sp, "chk_tip", None)
    if chk_tip is not None:
        chk_tip.setChecked(False)
    chk(chk_tip is not None and tip_at(word_pos("pavement")) == "" and sp.get_settings().get("hover_tip") is False,
        "C1 '뜻 풍선' 끄면 띄우지 않고 설정에 hover_tip 으로 저장")
    if chk_tip is not None:
        chk_tip.setChecked(True)
        chk(chk_tip.text() == "뜻 풍선" and sp.get_settings().get("hover_tip") is True, "C2 기본 켬·이름")
    # ---- D ----
    sp._chk["고급"].setChecked(False); QTest.qWait(100)
    chk(tip_at(word_pos("binder")) == "" and bool(tip_at(word_pos("asphalt"))), "D1 수준 체크로 숨긴 행(고급 binder)은 띄우지 않는다")
    sp._chk["고급"].setChecked(True)
    # ---- E ----
    pos = word_pos("asphalt")
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, pos=pos); app.processEvents()
    shown.clear()
    QApplication.sendEvent(vp, QHelpEvent(QEvent.Type.ToolTip, pos, vp.mapToGlobal(pos))); app.processEvents()
    pressed_tip = bool(shown and shown[-1])
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=pos); app.processEvents()
    chk(not pressed_tip, "E1 단추를 누른 채로는 띄우지 않는다")
    old_tool = m._draw_tool
    m._draw_tool = ("pen", 0)
    t = tip_at(pos)
    m._draw_tool = old_tool
    chk(t == "", "E2 그리기 도구가 켜진 동안은 띄우지 않는다")
    # ---- G ----
    n0 = reads["n"]
    for w in WORDS:
        tip_at(word_pos(w))
    chk(reads["n"] == n0, "G1 마우스 이동·풍선만으로는 study.db 를 읽지 않는다", f"{n0} → {reads['n']}")
    # ---- F ----
    chk(tip_at(m.view.mapFromScene(QPointF(500 * m._zoom, 700 * m._zoom))) == "", "F1 단어 밖이면 띄우지 않는다")
    other = next(tabs.widget(i) for i in range(tabs.count()) if tabs.widget(i) is not sp)
    tabs.setCurrentWidget(other); QTest.qWait(300)
    chk(not sp.isVisible() and tip_at(word_pos("pavement")) == "", "F2 단어장 창이 안 보이면 띄우지 않는다")
    QToolTip.showText = _show
    mw._skip_save_on_close = True
    mw.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\nALL PASS" if not fails else f"\nFAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 순서 크래시(판정 무관)를 피한다 — 다른 창 검사와 같다
