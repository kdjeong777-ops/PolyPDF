# -*- coding: utf-8 -*-
"""261107-28: 단어장 언어는 **읽은 글**로 정한다 — OCR 언어가 아니다 (단어학습 SOT §15.0).

사용자 보고: "hm 의 단어장 생성을 클릭하여 만들었는데, 없는 이유를 찾아". 영문 스캔본이 '자동' 에서 `kor+eng` 로 시작했고,
단어장 생성(`StudyBuildWorker`)이 그 값을 `build_vocab` 에 그대로 줘 영문 글이 한국어 형태소 분석으로 가서 단어가 0개였다.

실제 워커 두 길로 본다 — `StudyBuildWorker.run`(단어장 생성)과 `StudyVocabWorker.run`(정제 뒤 다시 만들기), 둘 다 `kor+eng`.
  A  영문 글 → 영어 단어장(> 0, 표의 lang 은 eng, 뜻·예문도)
  B  한글 글 → 한국어 단어장, 받은 `kor+eng` 를 그대로 적는다(사용자 뜻 고침이 (표제어, lang) 으로 붙어 있다)
  C  `vocab_lang` 판정 — 몫 문턱, 글자가 없으면 받은 값
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "test")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_vocablang_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


import fitz
from test_fixtures import KRFONT
from viewer.study import ocr as study_ocr
from viewer.study import vocab as study_vocab
from viewer.study.study_store import StudyStore, file_key_for
from viewer.workers import StudyBuildWorker, StudyVocabWorker

# 설치된 언어와 무관하게 `kor+eng` 가 그대로 가게 — 사용자 PC 와 같은 조건
study_ocr.available_langs = lambda: ["eng", "kor"]

EN = ["The captain looked across the frozen harbor and wondered whether the engine would survive another winter.",
      "Scientists measured the temperature of the ocean and recorded a remarkable change in the current.",
      "Her neighbor borrowed a ladder, a hammer and several nails to repair the broken fence near the garden."]
KO = ["아스팔트 포장의 품질은 다짐 온도와 골재 입도에 따라 크게 달라진다.",
      "시험시공 구간에서 측정한 밀도는 설계 기준을 만족하였으며 균열은 관찰되지 않았다.",
      "배합설계는 공극률과 안정도를 함께 고려하여 최적 아스팔트 함량을 결정한다."]

root = Path(tempfile.mkdtemp(prefix="vocablang_"))
try:
    def make(name, lines, font=None):
        p = root / name
        d = fitz.open()
        for t in lines:
            pg = d.new_page(width=595, height=842)
            kw = dict(fontsize=11, fontfile=font, fontname="kr") if font else dict(fontsize=11)
            pg.insert_textbox(fitz.Rect(60, 80, 535, 700), (t + " ") * 6, **kw)
        d.save(str(p)); d.close()
        return p

    def build(pdf, db):
        got = {}
        w = StudyBuildWorker(pdf, lang="kor+eng", db_path=db, with_vocab=True)
        w.finished.connect(lambda r: got.update(r))
        w.error.connect(lambda e: got.update(err=e))
        w.run()
        return got

    def rows(db, pdf):
        st = StudyStore(db)
        try:
            k = file_key_for(pdf)
            v = [tuple(r) for r in st.conn.execute("SELECT lemma, lang FROM vocab WHERE file_key=?", (k,))]
            nd = st.conn.execute("SELECT COUNT(*) FROM vocab_def").fetchone()[0]
            return v, nd
        finally:
            st.close()

    # A — 영문 글, 단어장 생성
    en_pdf = make("en.pdf", EN)
    db = root / "s.db"
    res = build(en_pdf, db)
    chk(not res.get("err"), "A 준비: 단어장 생성이 끝난다", res.get("err"))
    v, nd = rows(db, en_pdf)
    chk(len(v) > 5, "A1 영문 글을 'kor+eng' 로 만들어도 단어가 생긴다", len(v))
    chk(v and {l for _w, l in v} == {"eng"}, "A2 단어 표의 언어는 eng", sorted({l for _w, l in v}))
    chk(any(w in {"harbor", "engine", "temperature", "ladder"} for w, _l in v), "A3 영어 표제어", v[:10])
    chk(nd > 0, "A4 뜻(영→한·WordNet)도 생긴다", nd)
    chk((res.get("vocab") or {}).get("lang") == "eng", "A5 요약에 정한 언어", res.get("vocab"))

    # A' — 정제 뒤 다시 만들기 길(StudyVocabWorker)도 `kor+eng` 로
    vw = StudyVocabWorker(en_pdf, lang="kor+eng", db_path=db)
    out = {}
    vw.done.connect(lambda s: out.update(s))
    vw.run()
    v2, _nd = rows(db, en_pdf)
    chk(len(v2) > 5 and out.get("lang") == "eng", "A6 다시 만들기 길도 영어 단어장", (len(v2), out))

    # B — 한글 글은 한국어, 받은 값 그대로
    if KRFONT:
        ko_pdf = make("ko.pdf", KO, KRFONT)
        db2 = root / "s2.db"
        res = build(ko_pdf, db2)
        v, _nd = rows(db2, ko_pdf)
        chk(len(v) > 3 and {l for _w, l in v} == {"kor+eng"}, "B 한글 글은 한국어 단어장 — 표의 lang 은 받은 그대로",
            (len(v), sorted({l for _w, l in v})))
    else:
        print("SKIP - B 한글 글꼴 없음")

    # C — 판정
    vl = study_vocab.vocab_lang
    chk(vl(EN, "kor+eng") == "eng", "C1 영문 글 + kor+eng → eng")
    chk(vl(KO, "kor+eng") == "kor+eng", "C2 한글 글 + kor+eng → 그대로")
    chk(vl(KO, "eng") == "kor", "C3 한글 글 + eng → kor")
    chk(vl(EN, "eng") == "eng", "C4 영문 글 + eng → 그대로")
    mixed = ["아스팔트 Marshall 시험 결과 공극률 4.5% VMA 15 VFA 70 기준 만족"] * 3
    chk(vl(mixed, "kor+eng") == "kor+eng", "C5 영문 기호가 섞인 한글 보고서는 한국어")
    chk(vl(["", "123 456"], "kor+eng") == "kor+eng", "C6 글자가 없으면 받은 값")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
