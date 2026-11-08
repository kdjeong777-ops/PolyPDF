# -*- coding: utf-8 -*-
"""261108-29: 본문 읽기 중 본문을 찍으면 **찍은 곳의 문장부터** 읽는다 — 한글 스캔본에서도 (영상·음성 SOT §1.9).

사용자 보고: "샘플의 bm은 영어인데, 내가 찍은 곳부터 영어로 읽는것이 잘 되는데, 똑같은 스캔한 이미지인
성격심리책은 한글인데, 내가 찍은 곳을 제대로 찾지 못하고, 엉뚱한 곳부터 읽어."
원인: 찍은 점 → OCR 낱말 → 읽는 문장을 **낱말이 글자까지 똑같을 때만**(앞으로 10 낱말 안) 맞췄다.
한글 OCR 낱말은 글자 조각('성'·'격'·'론')이 많고 읽는 글은 띄어쓰기를 고친 텍스트 창 글이라
첫 문장 뒤로 맞는 낱말이 없어, 찍은 곳 대부분이 마지막 문장으로 갔다.
  A  한글 스캔 모사(글자 조각 OCR 낱말) — 낱말마다 찍으면 처음 읽는 문장에 그 낱말이 든다
  B  영문 스캔 모사(낱말 그대로) — 종전처럼 맞는다
  C  찍은 점이 상자 안인 낱말을 고른다(작은 조각 상자가 촘촘해도 옆 줄로 가지 않는다)
  D  맞춤 비용 — 낱말 500개 쪽에서 0.2초 안
"""
import os, sys, re, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "test")
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tempfile
import fitz
from PyQt6.QtCore import QObject, QStandardPaths
from PyQt6.QtWidgets import QApplication
QStandardPaths.setTestModeEnabled(True)
app = QApplication.instance() or QApplication([])
from viewer.widgets import read_aloud as RA

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


DPI = 300
TMP = tempfile.mkdtemp(prefix="ra_jump_")


def blank_pdf(name):
    p = os.path.join(TMP, name)
    d = fitz.open()
    d.new_page(width=595, height=842)
    d.save(p)
    d.close()
    return p


def layout(sentences, split_chars):
    """문장들을 한 문단으로 흘려 OCR 낱말 상자(300dpi 픽셀)를 만든다. split_chars 면 낱말을 글자 조각으로."""
    words, owner = [], []
    x, y = 200, 400
    CW, CH, GAP = 40, 50, 28
    for si, s in enumerate(sentences):
        for tok in s.split():
            wpx = CW * len(tok)
            if x + wpx > 2250:
                x, y = 200, y + 95
            parts = list(tok) if split_chars else [tok]
            cx = x
            for part in parts:
                pw = CW * len(part)
                words.append({"surface": part, "lemma": part, "lang": "kor", "conf": 90,
                              "x0": cx, "y0": y, "x1": cx + pw - 3, "y1": y + CH})
                owner.append((si, tok))
                cx += pw
            x += wpx + GAP
    return words, owner


class View:
    def __init__(self, p):
        self.p = p
        class _D:
            pass
        self._doc = _D()
        self._doc.doc = fitz.open(p)
        self._doc.page_count = 1
    def current_file(self): return self.p
    def current_page(self): return 0
    def go_to_page(self, n): pass
    def clear_word_highlights(self): pass
    def highlight_word_groups(self, *a, **k): pass


class TTS:
    def __init__(self): self.said = []
    def available(self): return True
    def set_rate(self, r): pass
    def stop(self): pass
    def speak_reading(self, t): self.said.append(t); return True
    def is_speaking(self): return True
    def saw_speaking(self): return True


class Store:
    def __init__(self, words): self.words = words
    def get_page_words(self, k, p): return [dict(w) for w in self.words] if p == 0 else []
    def get_page_dpi(self, k, p): return DPI if p == 0 else 0
    def get_page_text(self, k, p): return ""


class MW(QObject):
    def __init__(self, path, words):
        super().__init__()
        self.tts, self.store, self.main_view = TTS(), Store(words), View(path)
        # 261108-28 뒤로 읽기 엔진은 설정(`tts_voice`)이 고른다 — 자연 음성 모델이 깔린 기계에서도 가짜 SAPI 로 듣게
        self._prefs = {"tts_voice": {"engine": "sapi"}}
        class _S:
            def showMessage(self, *a): pass
        self.status = _S()
    def _study_get_tts(self): return self.tts
    def _study_get_store(self): return self.store
    def _clear_vocab_marks(self): pass
    def _vocab_marks_on(self): return False


def norm(t):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", (t or "").lower())


def run(name, sentences, split_chars):
    path = blank_pdf(name)
    words, owner = layout(sentences, split_chars)
    mw = MW(path, words)
    ra = RA.ReadAloud(mw)
    ra.set_target(mw.main_view)
    ra.mode = "1회"
    ra.start()
    sc = 72.0 / DPI
    tried = bad = 0
    misses = []
    for w, (si, tok) in zip(words, owner):
        cx = (w["x0"] + w["x1"]) / 2 * sc
        cy = (w["y0"] + w["y1"]) / 2 * sc
        mw.tts.said.clear()
        ok = ra.jump_to_point(cx, cy)
        tried += 1
        said = mw.tts.said[0] if (ok and mw.tts.said) else ""
        if norm(tok) not in norm(said):
            bad += 1
            if len(misses) < 4:
                misses.append((w["surface"], tok, said[:40]))
    ra.stop()
    return ra, words, tried, bad, misses


KO = ["반두라에 따르면 부적응적 행동은 기능장애적 학습의 결과다.",
      "모든 종류의 학습처럼 부적응적 반응은 직접적 경험의 결과로써 학습된다.",
      "자기효능감은 개인 자기효능감뿐 아니라 집단 자기효능감도 있다.",
      "개인이 느끼는 불안의 정도는 과제의 지각된 정도에 대한 중요한 정보를 제공한다.",
      "매우 높은 불안수준은 개인이 잘한다고 느끼지 못하는 것을 알려 준다.",
      "언어적 설득의 효과가 약하지만 자기효능감의 결정요인으로서 작용한다."]
EN = ["My eyelids creep up and blinding light sears my retinas.",
      "I keep my eyes open with sheer force of will.",
      "The room is small and the walls are painted white.",
      "Someone has left a note on the table beside the bed.",
      "I try to sit up but my arms refuse to cooperate."]

# A
ra, words, n, bad, misses = run("ko.pdf", KO, True)
chk(len(ra._sents) >= 4, "A 준비: 읽을 문장", len(ra._sents))
chk(n > 100 and bad == 0, "A 한글 조각 낱말 %d개를 하나씩 찍으면 그 낱말이 든 문장부터 읽는다(틀림 %d)" % (n, bad), misses)

# B
ra_en, _, n, bad, misses = run("en.pdf", EN, False)
chk(n > 40 and bad == 0, "B 영문 낱말 %d개 — 찍은 낱말이 든 문장부터(틀림 %d)" % (n, bad), misses)

# C — 둘째 줄 맨 앞 조각 상자 안을 찍으면, 가운데가 더 가까운 첫 줄의 긴 낱말이 아니라 그 조각
path = blank_pdf("c.pdf")
cw = [{"surface": "가나다라마바사아자차", "lemma": "", "lang": "kor", "conf": 90, "x0": 200, "y0": 400, "x1": 1400, "y1": 450},
      {"surface": "다.", "lemma": "", "lang": "kor", "conf": 90, "x0": 1440, "y0": 400, "x1": 1520, "y1": 450},
      {"surface": "하", "lemma": "", "lang": "kor", "conf": 90, "x0": 760, "y0": 470, "x1": 790, "y1": 500},
      {"surface": "늘", "lemma": "", "lang": "kor", "conf": 90, "x0": 793, "y0": 470, "x1": 823, "y1": 500},
      {"surface": "파랗다.", "lemma": "", "lang": "kor", "conf": 90, "x0": 850, "y0": 470, "x1": 1100, "y1": 500}]
mw = MW(path, cw)
ra = RA.ReadAloud(mw)
ra.set_target(mw.main_view)
ra.mode = "1회"
ra.start()
sc = 72.0 / DPI
mw.tts.said.clear()
ra.jump_to_point(762 * sc, 498 * sc)        # '하' 상자 안 왼쪽 아래 — 첫 줄 긴 낱말 가운데(800,425)가 '하' 가운데보다 가깝다
said = mw.tts.said[0] if mw.tts.said else ""
chk("하늘" in norm(said) and "가나다" not in norm(said), "C 상자 안을 찍으면 그 낱말의 문장", (ra._sents, said))
ra.stop()

# D
long_ko = KO * 6
path = blank_pdf("d.pdf")
dw, _ = layout(long_ko, True)
mw = MW(path, dw)
ra = RA.ReadAloud(mw)
ra.set_target(mw.main_view)
ra.mode = "1회"
ra.start()
t0 = time.perf_counter()
ra._build_spans()
dt = time.perf_counter() - t0
ra.stop()
chk(len(dw) >= 500 and dt < 0.2, "D 낱말 %d개·문장 %d개 맞춤 %.3f초" % (len(dw), len(ra._sents), dt), dt)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
