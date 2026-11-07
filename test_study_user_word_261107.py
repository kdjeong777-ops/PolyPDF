# -*- coding: utf-8 -*-
"""261107-34(사용자 지시 '단어를 찍은 단어는 사용자 단어장에 넣고, 해당 문장은 예시로 포함' ·
'사용자 단어장을 수정/보완할 수 있도록 단어장창에 버튼 추가') — 단어장 SOT §11.4.

실제 MainWindow(오프스크린, 시험 프로필 — 마스터 §14.7.2 의 3). 우클릭 메뉴는 `QMenu.exec` 를 가로채 항목을 고른다(처리기는 실제).
A. 본문 우클릭 `도구` 에 `사용자 단어장에 넣기` — 낱말 위에서 켜짐, 낱말 밖에서 꺼짐, 한국어가 아니면 없다
B. `word_context_at` — 누른 낱말·그 문장(블록 글을 `. ? !` 에서 끊음), 끌어 고른 글이 있으면 그 글
C. 항목을 누르면 편집 창이 채워져 열린다 — 표제어·예시 맨 위 `그 문장 — 문서이름 p.N`, [저장] 뒤 사용자 단어장에, 다시 해도 예시가 겹치지 않는다
D. 단어장 창 머리줄 [사용자] → 사용자 뜻 편집 창(`_action_user_terms`)
수정 전 코드: 항목·함수·단추가 없어 실패.
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPointF, QRectF
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_user_word_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사용자 단어장에 넣기", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(sec=0.4):
    t = time.monotonic()
    while time.monotonic() - t < sec:
        app.processEvents()
        time.sleep(0.01)


LABEL = "사용자 단어장에 넣기"
seen = {"menu": None, "pick": None}


def fake_exec(self, *a, **k):
    seen["menu"] = self
    if seen["pick"]:
        for act in self.actions():
            if act.text().split("\t")[0].strip() == seen["pick"] and act.isEnabled():
                return act
    return None


QMenu.exec = fake_exec


def item(menu):
    if menu is None:
        return None
    return next((a for a in menu.actions() if a.text().split("\t")[0].strip() == LABEL), None)


from viewer.widgets import study_edit_dialog as sed
opened = []


def fake_dlg_exec(self):
    opened.append({"ko": self.ed_ko.text(), "en": self.ed_en.text(), "ex": self.ed_ex.toPlainText()})
    return 1                                    # [저장]


sed.StudyEditDialog.exec = fake_dlg_exec

root = tempfile.mkdtemp(prefix="polypdf_userword_")
try:
    import fitz
    src = os.path.join(root, "roadbook.pdf")
    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_text((72, 110), "The asphalt zqbinder holds the stones. A second sentence here.", fontsize=11)
    d.save(src); d.close()

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1600, 1000); mw.show(); pump(0.3)
    mw._load_main(HistoryItem(src, 0, "", "bookmark")); pump(0.8)
    m = mw.main_view
    m._load_page_words()
    words = m._page_words or []
    box = next((w for w in words if w[4] == "zqbinder"), None)
    chk(box is not None, "A0 합성 쪽의 낱말 상자", str([w[4] for w in words]))

    def gpos(px, py):
        z = m._zoom or 1.0
        vp = m.view.mapFromScene(QPointF(px * z, py * z))
        return m.view.viewport().mapToGlobal(vp)

    g_on = gpos((box[0] + box[2]) / 2, (box[1] + box[3]) / 2) if box else None
    g_off = gpos(400.0, 700.0)

    # ---- A ----
    seen["pick"] = None
    mw._on_viewer_context_menu(g_on); pump(0.1)
    a = item(seen["menu"])
    chk(a is not None and a.isEnabled(), "A1 낱말 위 우클릭 — `사용자 단어장에 넣기` 켜짐")
    mw._on_viewer_context_menu(g_off); pump(0.1)
    a = item(seen["menu"])
    chk(a is not None and not a.isEnabled(), "A2 낱말 밖 — 항목은 있으나 꺼짐")
    import viewer.i18n as i18n
    old_lang = i18n._lang
    i18n._lang = "en"
    try:
        mw._on_viewer_context_menu(g_on); pump(0.1)
        chk(item(seen["menu"]) is None, "A3 한국어가 아니면 항목이 없다(한국 전용)")
        n0 = len(opened)
        mw._action_add_user_word("zqbinder", "x", 0); pump(0.1)
        chk(len(opened) == n0, "A4 처리기도 한국어가 아니면 아무것도 하지 않는다(@korea_only)")
    finally:
        i18n._lang = old_lang

    # ---- B ----
    wc = getattr(m, "word_context_at", None)
    ctx = wc(g_on) if wc else None
    chk(ctx is not None and ctx["word"] == "zqbinder" and ctx["sentence"] == "The asphalt zqbinder holds the stones.",
        "B1 누른 낱말·그 문장", str(ctx))
    chk(wc is not None and wc(g_off) is None, "B2 낱말 밖이면 None")
    m._sel_text = "asphalt zqbinder"
    ctx2 = wc(g_off) if wc else None
    chk(ctx2 is not None and ctx2["word"] == "asphalt zqbinder" and "holds the stones." in ctx2["sentence"],
        "B3 끌어 고른 글이 있으면 그 글(문장은 첫 낱말의 블록에서)", str(ctx2))
    m.clear_text_selection()

    # ---- C ----
    seen["pick"] = LABEL
    mw._on_viewer_context_menu(g_on); pump(0.4)
    chk(len(opened) == 1 and opened[0]["en"] == "zqbinder", "C1 항목을 누르면 표제어가 채워진 편집 창", str(opened))
    want_ex = "The asphalt zqbinder holds the stones. — roadbook p.1"
    chk(opened and opened[0]["ex"].split("\n")[0] == want_ex, "C2 예시 맨 위 = 그 문장 — 문서이름 p.N", str(opened[-1:]))
    dic = mw._study_get_dict()
    hits = [h for h in dic.lookup("zqbinder") if h.get("src_kind") == "user"]
    chk(len(hits) == 1 and want_ex in (hits[0].get("examples") or ""), "C3 [저장] 뒤 사용자 단어장에", str(hits)[:300])
    mw._on_viewer_context_menu(g_on); pump(0.4)
    chk(len(opened) == 2 and opened[1]["ex"].count(want_ex) == 1, "C4 다시 넣어도 같은 예시는 하나", str(opened[-1:]))

    # ---- D ----
    called = []
    mw._action_user_terms = lambda *a, **k: called.append(1)
    btn = getattr(mw.study_panel, "btn_user_terms", None)
    if btn is not None:
        btn.click(); pump(0.1)
    chk(called == [1], "D1 머리줄 [사용자] → 사용자 뜻 편집 창(_action_user_terms)")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\nALL PASS" if not fails else f"\nFAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)
