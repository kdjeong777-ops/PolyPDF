# -*- coding: utf-8 -*-
"""261107-33(사용자 지시 '단어 수준별 밑줄 색 다르게'·'밑줄을 투명도를 높여') — 단어장 SOT §11.2, 디자인 SOT §2.6.

A. `vocab_mark_line` — 수준별 색(초급 호박·중급 녹색·고급 분홍·전문용어 청색·미정 청록), 알파 153, 선은 상자 **바로 아래**, 굵기 1.5~3 px
B. 패널 머리 글자도 같은 뜻(🟡 초급 · 🟢 중급 · 🩷/🔴 고급 · 📘 전문용어·사전 매칭) — `mark_level` 이 둘의 규칙
C. 본문 밑줄 층에 수준이 간다(`_apply_vocab_marks` → `set_vocab_marks` 의 5번째 값)
D. 발표 길 `vocab_overlay_for` — marks(수준 포함, '종류' 체크로 거름)·tips(패널이 안 보여도, `뜻 풍선` 끄면 빈 dict)·다른 PDF 는 None
수정 전 코드: 한 색·불투명·상자 안쪽 아래, 머리 글자 초급 🟢, 함수가 없어 실패.
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

QStandardPaths.setTestModeEnabled(True)
app = QApplication.instance() or QApplication(sys.argv)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

WANT = {"초급": "#E6A100", "중급": "#2E7D32", "고급": "#D81B60", "전문용어": "#1565C0", None: "#00897B", "미정": "#00897B"}

# ---- A ----
try:
    from viewer.vocab_marks import vocab_mark_line
except Exception as e:                        # 수정 전 코드: 모듈이 없다
    vocab_mark_line = None
    print("   (vocab_marks 없음)", e)
chk(vocab_mark_line is not None, "A0 viewer/vocab_marks.vocab_mark_line 이 있다")
if vocab_mark_line is not None:
    for lv, hexc in WANT.items():
        col, (lx0, ly, lx1, ly2), w = vocab_mark_line(72.0, 100.0, 120.0, 112.0, 2.0, lv)
        chk(col.name().upper() == hexc and col.alpha() == 153, f"A1 {lv} 색 {hexc}·알파 153", f"{col.name()} {col.alpha()}")
    col, (lx0, ly, lx1, ly2), w = vocab_mark_line(72.0, 100.0, 120.0, 112.0, 2.0, "초급")
    chk(lx0 == 144.0 and lx1 == 240.0 and ly == ly2, "A2 왼·오른 끝 = 상자 × 배율, 가로선", f"{lx0} {lx1} {ly} {ly2}")
    chk(ly - w / 2 > 112.0 * 2.0 and ly < 112.0 * 2.0 + 4.0, "A3 선 전체가 상자 아래 끝 밖(바로 아래)", f"y={ly} w={w}")
    chk(1.5 <= w <= 3.0, "A4 굵기 1.5~3 px", str(w))
    _c, _l, w_small = vocab_mark_line(0, 0, 10, 2, 1.0)
    _c, _l, w_big = vocab_mark_line(0, 0, 10, 200, 1.0)
    chk(w_small == 1.5 and w_big == 3.0, "A5 굵기는 글자 높이 8 %, 1.5~3 px 로 묶음", f"{w_small} {w_big}")

# ---- B ----
from viewer.widgets import study_panel as spm
from viewer.widgets.study_panel import StudyPanel
mark_level = getattr(spm, "mark_level", None)
chk(mark_level is not None, "B0 study_panel.mark_level 이 있다")
sp = StudyPanel()
sp.resize(420, 600)
for _lv in ("초급", "중급", "고급", "전문용어"):      # 기본은 초급이 꺼져 있다 — 넷 다 보이게
    sp._chk[_lv].setChecked(True)
rows =[{"lemma": "easyword", "lang": "eng", "level": "초급", "count": 1, "pos": 0, "definitions": [{"definition": "쉬운 말", "source": "s"}], "examples": []},
        {"lemma": "midword", "lang": "eng", "level": "중급", "count": 1, "pos": 1, "definitions": [{"definition": "중간 말", "source": "s"}], "examples": []},
        {"lemma": "hardword", "lang": "eng", "level": "고급", "count": 1, "pos": 2, "definitions": [], "examples": []},
        {"lemma": "dictword", "lang": "eng", "level": "초급", "has_dict": True, "count": 1, "pos": 3, "definitions": [{"definition": "사전 뜻", "source": "d", "is_dict": True}], "examples": []}]
sp.set_page_words(0, rows)
heads = {}
for i in range(sp.tree.topLevelItemCount()):
    it = sp.tree.topLevelItem(i)
    heads[it.data(0, sp.DATA_LEMMA)] = it.text(0).split(" ")[0]
chk(heads.get("easyword") == "🟡" and heads.get("midword") == "🟢" and heads.get("hardword") in ("🩷", "🔴")
    and heads.get("dictword") == "📘", "B1 머리 글자 — 🟡 초급 · 🟢 중급 · 🩷 고급 · 📘 사전 매칭", str(heads))
if mark_level is not None:
    chk([mark_level(r) for r in rows] == ["초급", "중급", "고급", "전문용어"] and mark_level({"lemma": "x"}) == "미정",
        "B2 mark_level — 사전 매칭은 전문용어, 없으면 미정")

# ---- C·D (StudyMixin 대역 창) ----
from viewer.study_controller import StudyMixin
PDF = Path(os.path.abspath("doc_vocab_colors.pdf"))


class FakeStore:
    def vocab_count(self, fkey):
        return 1
    def get_page_words(self, fkey, page):
        out, x = [], 72.0
        for w in ("easyword", "midword", "hardword", "dictword"):
            out.append({"surface": w, "x0": x, "y0": 100.0, "x1": x + 60, "y1": 112.0})
            x += 70
        return out
    def get_page_dpi(self, fkey, page):
        return 0
    def get_page_study(self, fkey, page):
        return [dict(r) for r in rows]


class MV:
    def __init__(self):
        self.calls = []
    def current_page(self):
        return 0
    def current_file(self):
        return str(PDF)
    def set_vocab_marks(self, page, rects):
        self.calls.append(("set", page, list(rects)))
    def clear_vocab_marks(self):
        self.calls.append(("clear",))


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
rects = [(72.0, 100.0, 132.0, 112.0, "easyword"), (142.0, 100.0, 202.0, 112.0, "midword")]
h._apply_vocab_marks(0, rects)
got = next((c for c in h.main_view.calls if c[0] == "set"), None)
lv = [r[4] if len(r) > 4 else None for r in got[2]] if got else []
chk(lv == ["초급", "중급"], "C1 본문 밑줄 층에 수준이 간다(set_vocab_marks 의 5번째 값)", str(got))

ov = getattr(h, "vocab_overlay_for", None)
res = ov(str(PDF), 0) if ov else None
chk(isinstance(res, dict), "D0 vocab_overlay_for 가 dict 를 준다", str(res)[:200])
if isinstance(res, dict):
    mk = {m[4]: m for m in res["marks"]}
    chk(set(mk) == {"easyword", "midword", "hardword", "dictword"} and mk["dictword"][5] == "전문용어"
        and mk["easyword"][5] == "초급" and mk["easyword"][:4] == (72.0, 100.0, 132.0, 112.0),
        "D1 marks = (x0, y0, x1, y1, lemma, level) — 표시 쪽 pt, 사전 매칭은 전문용어", str(res["marks"]))
    chk(not sp.isVisible() and "easyword" in res["tips"] and "쉬운 말" in res["tips"]["easyword"]
        and "hardword" not in res["tips"], "D2 tips — 패널이 안 보여도 글을 준다, 뜻 없는 단어는 빼고", str(res["tips"]))
    sp._chk["고급"].setChecked(False)
    res2 = ov(str(PDF), 0)
    chk(res2 and "hardword" not in {m[4] for m in res2["marks"]}, "D3 '종류' 체크로 거른다(본문 밑줄과 같은 집합)")
    sp._chk["고급"].setChecked(True)
    sp.chk_tip.setChecked(False)
    res3 = ov(str(PDF), 0)
    chk(res3 and res3["tips"] == {} and res3["marks"], "D4 `뜻 풍선` 꺼짐 → tips 빈 dict(밑줄은 그대로)")
    sp.chk_tip.setChecked(True)
    chk(ov(str(PDF.with_name("other.pdf")), 0) is None, "D5 지금 단어장을 보는 PDF 가 아니면 None")

print("\nALL PASS" if not fails else f"\nFAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)
