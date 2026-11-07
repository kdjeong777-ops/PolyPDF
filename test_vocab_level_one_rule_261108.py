# -*- coding: utf-8 -*-
"""261108-4(SOT 전체 점검, 사용자 지시 '서로 상충되는 일이 발생하거나 이후 업그레이드에 문제 없게') — 단어학습 SOT §15.2.

단어장 창의 수준은 하나 — `종류` 거르기·목록 머리 글자·본문 밑줄·발표 밑줄이 같은 값(`study_panel.mark_level`).
종전(261107-33~): 머리 글자·밑줄은 '사전에 뜻이 있으면 전문용어', 거르기는 행 level — 일반 사전 뜻이 있는 중급 단어가
파란(전문용어) 밑줄인데 '중급' 을 끄면 사라지고 '전문용어' 를 끄면 남았다.
실제 '종류 ▾' 메뉴를 열고 메뉴 창으로 체크 칸을 눌러, 거른 목록·머리 글자·밑줄(본문 층·발표 길)의 수준을 맞춰 본다.
A. 체크마다: 밑줄에 보이는 단어 = 목록에 보이는 단어, 밑줄 수준은 모두 켜진 종류, 머리 글자 = 밑줄 수준
B. 일반 사전 뜻만 있는 중급 단어는 중급(녹색), 전문 용어집 단어는 전문용어
수정 전 코드: '전문용어' 를 끄면 일반 사전 중급 단어의 밑줄이 꺼진 수준(전문용어)으로 남아 A 에서 실패.
"""
import os, sys
from pathlib import Path
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, Qt, QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

QStandardPaths.setTestModeEnabled(True)
app = QApplication.instance() or QApplication(sys.argv)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

from viewer.widgets.study_panel import StudyPanel, _BADGE, _badge
from viewer.study_controller import StudyMixin

WORDS = ["easyword", "midword", "dictmid", "hardword", "termword", "plainword"]
ROWS = [
    {"lemma": "easyword", "level": "초급"},
    {"lemma": "midword", "level": "중급"},
    {"lemma": "dictmid", "level": "중급", "has_dict": True},            # 일반 사전(Wiktionary 등) 뜻만
    {"lemma": "hardword", "level": "고급"},
    {"lemma": "termword", "level": "전문용어", "has_dict": True},       # 전문 용어집 → 승격(_enrich_rows_with_dict)
    {"lemma": "plainword", "level": "미정"},
]
for i, r in enumerate(ROWS):
    r.update({"lang": "eng", "count": 1, "pos": i,
              "definitions": [{"definition": "뜻 " + r["lemma"], "source": "s", "is_dict": bool(r.get("has_dict"))}],
              "examples": []})
PDF = Path(os.path.abspath("doc_level_one_rule.pdf"))

sp = StudyPanel()
sp.resize(420, 600); sp.show(); app.processEvents()
sp.set_page_words(0, [dict(r) for r in ROWS])


class FakeStore:
    def vocab_count(self, fkey):
        return 1
    def get_page_words(self, fkey, page):
        out, x = [], 72.0
        for w in WORDS:
            out.append({"surface": w, "x0": x, "y0": 100.0, "x1": x + 60, "y1": 112.0})
            x += 70
        return out
    def get_page_dpi(self, fkey, page):
        return 0
    def get_page_study(self, fkey, page):
        return [dict(r) for r in ROWS]


class MV:
    def __init__(self):
        self.last = None
    def current_page(self):
        return 0
    def current_file(self):
        return str(PDF)
    def set_vocab_marks(self, page, rects):
        self.last = list(rects)
    def clear_vocab_marks(self):
        self.last = []


class Host(StudyMixin):
    def __init__(self):
        self._prefs = {}
        self._study_pdf = PDF
        self.main_view = MV()
        self.study_panel = sp
        self._spot_terms_cache = None
    def _study_get_store(self):
        return FakeStore()
    def _apply_word_filter(self, fkey, rs):
        return rs
    def _enrich_rows_with_dict(self, rs):
        return rs
    def _accumulate_and_merge_examples(self, rs):
        return rs
    def _spot_page_terms(self, page):
        return [], {}
    def _vocab_marks_on(self):
        return True


h = Host()
menu = sp.btn_kind.menu()
win = None


def click_kind(lv):
    """'종류 ▾' 메뉴를 열고 메뉴 창으로 그 체크 칸을 실제로 누른다."""
    global win
    if not menu.isVisible():
        menu.popup(sp.btn_kind.mapToGlobal(QPoint(0, sp.btn_kind.height()))); QTest.qWait(120)
    win = menu.windowHandle()
    cb = sp._chk[lv]
    p = cb.mapTo(menu, QPoint(20, cb.height() // 2))
    QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p); QTest.qWait(80)


def state():
    shown = [sp.tree.topLevelItem(i).data(0, sp.DATA_LEMMA) for i in range(sp.tree.topLevelItemCount())]
    heads = {sp.tree.topLevelItem(i).data(0, sp.DATA_LEMMA): sp.tree.topLevelItem(i).text(0).split(" ")[0]
             for i in range(sp.tree.topLevelItemCount())}
    ov = h.vocab_overlay_for(str(PDF), 0) or {"marks": []}
    marks = {m[4]: m[5] for m in ov["marks"]}
    rects = [(x0, y0, x1, y1, lm) for (x0, y0, x1, y1, lm) in h._study_page_rects(0, sp.filter_rows(sp._rows), {})]
    h._apply_vocab_marks(0, rects)
    body_lv = {lm: sp.level_of(lm) for lm in shown}
    return shown, heads, marks, body_lv


def checked():
    return {lv for lv in ("초급", "중급", "고급", "전문용어") if sp._chk[lv].isChecked()}


for lv in ("초급", "중급", "고급", "전문용어"):          # 처음에는 넷 다 켠다(메뉴로)
    if not sp._chk[lv].isChecked():
        click_kind(lv)
chk(checked() == {"초급", "중급", "고급", "전문용어"} and menu.isVisible(), "A0 메뉴로 넷 다 켬(메뉴 열린 채)")

shown, heads, marks, body_lv = state()
chk(marks.get("dictmid") == "중급" and heads.get("dictmid") == _badge("중급"),
    "B1 일반 사전 뜻만 있는 중급 단어 — 밑줄·머리 글자 모두 중급(녹색)", f"{marks.get('dictmid')} {heads.get('dictmid')}")
chk(marks.get("termword") == "전문용어" and heads.get("termword") == _BADGE["전문용어"],
    "B2 전문 용어집 단어 — 전문용어(📘·청색)", f"{marks.get('termword')} {heads.get('termword')}")

for step, lv in enumerate(("전문용어", "중급", "전문용어", "고급"), 1):
    click_kind(lv)
    on = checked()
    shown, heads, marks, body_lv = state()
    tag = f"[{step}: {lv} {'켬' if sp._chk[lv].isChecked() else '끔'} → {sorted(on)}]"
    chk(set(marks) == set(shown), f"A1{tag} 밑줄(발표 길) 단어 = 목록에 보이는 단어", f"{sorted(marks)} / {sorted(shown)}")
    bad = {lm: l for lm, l in marks.items() if not (l in on or (l == "미정" and "고급" in on))}
    chk(not bad, f"A2{tag} 밑줄 수준은 모두 켜진 종류", str(bad))
    chk(all(heads.get(lm) == _badge(l) for lm, l in marks.items()), f"A3{tag} 머리 글자 = 밑줄 수준",
        str({lm: (heads.get(lm), l) for lm, l in marks.items()}))
    chk(body_lv == {lm: marks.get(lm) for lm in shown}, f"A4{tag} 본문 밑줄 층의 수준(level_of) = 발표 길 수준", str(body_lv))
chk(menu.isVisible(), "A5 그동안 메뉴는 열린 채")
menu.hide()

print("\nALL PASS" if not fails else f"\nFAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)
