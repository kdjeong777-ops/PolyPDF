# -*- coding: utf-8 -*-
"""261101-2(사용자 지시) 책갈피 자동 생성 — 정답 책갈피 대조로 고친 것 (마스터 §4.4.3 P1·P8·F1~F4·R1·H2).

A. 줄 형식 — `제목 _ 86`·`요약 80`(한 칸 + 쪽), `CHAPTER 12` 는 항목 아님, `저13장` 은 장, `제18장` 만 한 줄이면 다음 줄과 잇는다
B. 스캔 목차 쪽 글자층 — 뜻 있는 글인지 확인, 둘 다 읽어 항목이 많은 쪽
C. 인쇄 쪽 번호 — 구간별 차이(Viterbi)·책 쪽 → PDF 쪽·표본만 읽기·장 표지(빈 뒷면)·장 제목으로 맞추기(F4)
D. 검토 표 — 쪽 번호 맞춤 항목, 한 행을 고치면 그 구간만 옮긴다
E. 목차 없는 스캔본 — 장 머리 낱말·순번 이름, 쪽 윤곽 + 머리 띠 OCR(Tesseract 없으면 SKIP)
F. 실제 표본(_samples, 없으면 SKIP) — 정답 책갈피와 대조
"""
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QApplication, QMessageBox

QStandardPaths.setTestModeEnabled(True)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
app = QApplication.instance() or QApplication(sys.argv)
root = Path(tempfile.mkdtemp(prefix="polypdf_bm261101_"))

from viewer import toc_parse as tp

# ── A. 줄 형식 ─────────────────────────────────────────────────────────
def one(s):
    r = tp.parse_line(s)
    return (r[0]["title"], r[0]["toc_page"]) if r else None
chk(one("1. 성격 평가 _ 86") == ("1. 성격 평가", 86), "A1 밑줄 뒤 쪽 번호", str(one("1. 성격 평가 _ 86")))
chk(one("요약 80") == ("요약", 80) and one("Review Questions 82") == ("Review Questions", 82),
    "A2 한 칸 + 쪽 번호", f"{one('요약 80')} {one('Review Questions 82')}")
chk(not tp.parse_line("CHAPTER 12") or tp.parse_line("CHAPTER 12")[0].get("toc_page") is None,
    "A3 장 낱말만 있는 줄은 쪽 항목이 아니다", str(tp.parse_line("CHAPTER 12")))
chk(tp.infer_level("저13장 프롬의 성격 유형") == 0, "A4 OCR 이 '제' 를 '저' 로 읽은 장 = 장")
_orig_pl = tp._page_lines
tp._page_lines = lambda pdf, pages, ocr=None: [(15, 80.0, "제18장"), (15, 100.0, "매슬로의 자아실현 접근 407"),
                                               (15, 110.0, "1. 매슬로의 생애 408"), (16, 80.0, "제 3 장"),
                                               (16, 110.0, "1 개관 / 57"), (16, 110.0, "2. 실시 / 62")]
rows = tp.parse_toc_pages("x.pdf", [15, 16])
tp._page_lines = _orig_pl
titles = [(r["title"], r["toc_page"], r["level"]) for r in rows]
chk(("제18장 매슬로의 자아실현 접근", 407, 0) in titles, "A5 장 번호만 한 줄 → 다음 줄 제목과 이음(장)", str(titles))
chk(any(t.startswith("제 3 장") and lv == 0 for t, _p, lv in titles) and any("개관" in t and not t.startswith("제") for t, _p, _l in titles),
    "A6 다음 줄이 하위 번호면 잇지 않는다", str(titles))
r18 = [r for r in rows if r["title"].startswith("제18장")]
r3 = [r for r in rows if r["title"].startswith("제 3 장")]
chk(not r18[0].get("toc_inherited") and r3 and r3[0].get("toc_inherited"), "A7 장 쪽을 물려받은 행 표시(toc_inherited)")

# ── B. 글자층 확인·선택 ────────────────────────────────────────────────
good = ["제1장 성격심리학의 이해", "1. 성격의 이해 24", "2. 성격에 대한 관점 37", "요약 49", "Review Questions 51"]
bad = ["㉧U=UJ직PT트日 세", "回U=UL직PT트R 딛", "回HZ직PT트日됩", "㉢HZ직PT트R 다", "●■ ⊂⊃ ▲"]
chk(tp.layer_meaningful(good), "B1 뜻 있는 글자층(번호·한글·영어)")
chk(not tp.layer_meaningful(bad), "B2 장식체를 읽은 잡글 글자층은 쓰지 않는다")
toc_pdf = root / "toc_layer.pdf"
d = fitz.open(); pg = d.new_page()
y = 72
for i, (t, p) in enumerate([("Introduction", 3), ("Methods", 12), ("Results", 25), ("Discussion", 40),
                            ("Summary", 52), ("References", 60)]):
    pg.insert_text((72, y), f"{i + 1}. {t} ........ {p}", fontsize=11); y += 22
d.save(toc_pdf); d.close()
class FakeOcr:
    def is_scan(self, p): return True
    def toc_lines(self, p): return [(72.0, "1. lntroductlon .... 3"), (72.0, "Rcsults")]
lines = tp._page_lines(toc_pdf, [1], ocr=FakeOcr())
chk(sum(len(tp.parse_line(t)) for _p, _x, t in lines) >= 6, "B3 스캔 쪽: 글자층이 항목이 더 많으면 글자층",
    f"{[t for _p, _x, t in lines]}")
class FakeOcr2(FakeOcr):
    def toc_lines(self, p): return [(72.0, f"{i}. Chapter title {i} .... {i * 10}") for i in range(1, 9)]
lines = tp._page_lines(toc_pdf, [1], ocr=FakeOcr2())
chk(len(lines) == 8 and "Chapter title" in lines[0][2], "B4 OCR 가 더 많으면 OCR")
class FakeOcr3(FakeOcr):      # 261103-1: 항목 수가 같으면 OCR 판독 — 예전에 덧씌운 글자층의 잡글이 이기지 않게
    def toc_lines(self, p): return [(72.0, f"{i}. Fresh title {i} .... {i * 10}") for i in range(1, 7)]
lines = tp._page_lines(toc_pdf, [1], ocr=FakeOcr3())
chk(len(lines) == 6 and "Fresh title" in lines[0][2], "B5 항목 수가 같으면 OCR 판독(글자층이 아니라)", f"{lines[:1]}")

# ── C. 인쇄 쪽 번호 ────────────────────────────────────────────────────
from viewer import page_numbers as pn
# 책 1..: PDF 13~ 시작(차이 +12), 책 41·42 를 스캐너가 지움(차이 +10), 책 70 뒤에 번호 없는 쪽 하나 끼움(+11)
book_of = {}
pdfp, b = 13, 1
while pdfp <= 120:
    if b in (41, 42):
        b += 1; continue
    book_of[pdfp] = b
    pdfp += 1
    if b == 70:
        book_of[pdfp] = None; pdfp += 1        # 번호 없는 쪽
    b += 1
fol = {p: ([n] if n else []) for p, n in book_of.items()}
fol[30] = [7]                                   # 잘못 읽은 숫자(그림 번호 등)
fol[31] = []                                    # 못 읽은 쪽
est = pn.fit_offsets(fol, 13, 120)
segs = [(a, b_, o) for a, b_, o, _e in est.segs] if est else []
chk(est is not None and [s[2] for s in segs] == [12, 10, 11], "C1 구간별 차이 +12 → +10 → +11", str(segs))
chk(est and est.book_to_pdf(5) == 17 and est.book_to_pdf(43) == 53 and est.book_to_pdf(80) == 91,
    "C2 책 쪽 → PDF 쪽", f"{est and [est.book_to_pdf(x) for x in (5, 43, 80)]}")
chk(est and est.book_to_pdf(41) == 53, "C3 지워진 책 쪽은 그다음 인쇄 쪽", f"{est and est.book_to_pdf(41)}")
# 디지털 PDF — 머리말 띠의 쪽 번호를 글자층에서 읽고, 표본만 읽는다
dig = root / "folio.pdf"
d = fitz.open()
for p in range(1, 121):
    pg = d.new_page(width=420, height=600)
    n = book_of.get(p)
    if n:
        pg.insert_text((370 if p % 2 else 30, 40), str(n), fontsize=10)
    pg.insert_text((50, 200), f"Body text of page {p} with words", fontsize=11)
d.save(dig); d.close()
with pn.PrintedPages(dig) as pp:
    est2 = pp.estimate(13, 120)
    nread = len(pp._fol)
chk(est2 is not None and [s[2] for s in est2.segs] == [12, 10, 11], "C4 글자층 띠에서 구간 추정",
    f"{est2 and est2.segs}")
chk(nread < 60, "C5 모든 쪽을 읽지 않는다(표본 + 경계 좁히기)", f"읽은 쪽 {nread}/108")
chk(est2 and est2.book_to_pdf(43) == 53 and est2.book_to_pdf(71) == 82,
    "C6 경계 쪽까지 맞음", f"{est2 and [est2.book_to_pdf(43), est2.book_to_pdf(71)]}")
# 장 표지: 표지(번호 없음) → 빈 뒷면 → 번호 쪽 (성격심리)
texts = {20: "앞 장 마지막 쪽 본문 글자가 여기에 많이 있다", 21: "제4장 올포트의 특질 이론 큰 제목 깨짐", 22: "",
         23: "4장 올포트의특질이론 106 본문이 이어진다 글자 글자", 30: "제6장 아무개 표지 글자 글자", 31: "", 32: "1. 주요 개념 본문 글자 글자 글자 글자 글자"}
tf = lambda q: texts.get(q, "본문 글자가 여기에 충분히 많이 있다")
rows = [{"title": "제4장 올포트의특질이론", "level": 0, "page": 22, "toc_page": 105},
        {"title": "제5장 커텔의특질이론", "level": 0, "page": 23, "toc_page": 129},
        {"title": "제6장 아무개", "level": 0, "page": 32, "toc_page": 140, "toc_inherited": True},
        {"title": "1. 주요 개념", "level": 1, "page": 22, "toc_page": 106}]
pn.refine_chapter_pages(rows, tf)
chk(rows[0]["page"] == 21, "C7 맞춘 쪽이 빈 뒷면이면 장 표지로", str(rows[0]["page"]))
chk(rows[1]["page"] == 23, "C8 앞이 빈 쪽이어도 장 제목이 없으면 당기지 않는다", str(rows[1]["page"]))
chk(rows[2]["page"] == 30, "C9 장 쪽을 물려받았고 앞이 빈 쪽이면 표지로", str(rows[2]["page"]))
chk(rows[3]["page"] == 22, "C10 하위 행은 당기지 않는다")
# F4: 머리말·꼬리말에 쪽 번호 없이 장 제목만(짝수 쪽만) — 장 쪽으로 세부 행을 정한다(사용자 지시)
ch_text = {}
for q in range(1, 80):
    ch_text[q] = "본문 글자 글자 글자 글자 글자 글자"
for q in (12, 14, 16, 18):  ch_text[q] += " 심리검사에 대한 개관"
for q in (21, 24, 26, 28):  ch_text[q] += " 지능 평가 Wechsler"
ch_text[21] = "제2장 지능 평가 Wechsler 지능검사"         # 2장 표지
ch_text[22] = ""                                   # 표지 뒤 번호 없는 빈 뒷면(책 쪽을 먹지 않는다)
rows = [{"title": "제 1 장 심리검사에 대한 개관", "level": 0, "toc_page": 1},
        {"title": "2. 발전", "level": 1, "toc_page": 4},
        {"title": "제 2 장 지능 평가: Wechsler 지능검사", "level": 0, "toc_page": 11},
        {"title": "1) 지능", "level": 2, "toc_page": 14}]
found = pn.map_rows_by_chapters(rows, lambda q: ch_text.get(q, ""), 80, start_offset=10)
chk(found == 2 and [r["page"] for r in rows] == [12, 15, 21, 25], "C11 장 제목 쪽 + (세부 − 장 목차 쪽)",
    str([r["page"] for r in rows]))

# ── D. 검토 표 ─────────────────────────────────────────────────────────
from viewer.widgets.toc_review_dialog import TocReviewDialog, COL_PAGE
rv_rows = [{"title": "Ch A", "toc_page": 1, "page": 13, "level": 0, "seg": 0, "src": "p1"},
           {"title": "a1", "toc_page": 5, "page": 17, "level": 1, "seg": 0, "src": "p1"},
           {"title": "Ch B", "toc_page": 43, "page": 53, "level": 0, "seg": 1, "src": "p1"},
           {"title": "b1", "toc_page": 50, "page": 60, "level": 1, "seg": 1, "src": "p1"}]
dlg = TocReviewDialog(dig, rv_rows, offset=12, candidates=[(12, 0.5)], method="toc", toc_pages=[1],
                      page_map={"method": "folio", "segments": [[13, 52, 12, 5], [53, 120, 10, 5]]})
pages = lambda: [dlg.table.item(i, COL_PAGE).text() for i in range(dlg.table.rowCount())]
chk(pages() == ["13", "17", "53", "60"], "D1 맞춘 쪽을 그대로 연다(오프셋을 덮어쓰지 않는다)", str(pages()))
chk(dlg.cmb_cand.itemData(0) == "map", "D2 추천 첫 항목 = 쪽 번호 맞춤")
dlg.table.item(0, COL_PAGE).setText("12")
chk(pages() == ["12", "16", "53", "60"], "D3 한 행을 고치면 그 구간만 옮긴다(R1)", str(pages()))
dlg.cmb_cand.setCurrentIndex(1)
dlg._apply_offset()
dlg.cmb_cand.setCurrentIndex(0)
chk(pages()[2:] == ["53", "60"] and pages()[0] == "12", "D4 '쪽 번호 맞춤' 을 고르면 수동 아닌 행은 맞춘 쪽으로", str(pages()))
dlg.close()

# ── E. 목차 없는 스캔본 ────────────────────────────────────────────────
from viewer.study import ocr_headings as oh
chk(oh._chapter_word("GCGHAPTER 3") == ("CHAPTER", "3") and oh._chapter_word("CHAPTER G")
    and oh._chapter_word("제3장 아무개")[0] == "ko" and oh._chapter_word("What's two plus") is None,
    "E1 장 머리 낱말(장식체 오인식 포함)")
names = oh.sequence_names([("CHAPTER", "1"), ("CHAPTER", "2"), ("CHAPTER", "G"), ("", ""), ("CHAPTER", "41"),
                           ("CHAPTER", "6"), ("CHAPTER", "2O")])
chk(names == [f"CHAPTER {i}" for i in range(1, 8)], "E2 이름은 순번(OCR 번호는 믿지 않는다)", str(names))
from viewer.study import ocr as _ocr
if "eng" in (_ocr.available_langs() or []):
    scan = root / "novel.pdf"
    src = fitz.open()
    chap_pages = {3, 7, 11, 14}
    for p in range(1, 18):
        pg = src.new_page(width=420, height=600)
        if p in chap_pages:
            pg.insert_text((90, 130), f"CHAPTER {sorted(chap_pages).index(p) + 1}", fontsize=28)
            y = 220
        else:
            y = 40
        while y < 560:
            pg.insert_text((40, y), "the quick brown fox jumps over the lazy dog again", fontsize=10); y += 16
    img_pdf = fitz.open()
    for pg in src:
        pix = pg.get_pixmap(dpi=100)
        np_ = img_pdf.new_page(width=pg.rect.width, height=pg.rect.height)
        np_.insert_image(np_.rect, pixmap=pix)
    img_pdf.save(scan); img_pdf.close(); src.close()
    res = oh.chapter_pages_fast(scan, lang="eng")
    chk([p for _n, p in res] == sorted(chap_pages) and [n for n, _p in res] == [f"CHAPTER {i}" for i in range(1, 5)],
        "E3 쪽 윤곽 + 머리 띠 OCR 로 장 찾기", str(res))
else:
    print("SKIP - E3 Tesseract eng 없음")

# ── F. 실제 표본(정답 책갈피 대조) ─────────────────────────────────────
SAMPLES = os.path.join(os.path.dirname(HERE), "_samples")
def truth_of(path):
    d = fitz.open(path); t = d.get_toc(); d.close()
    return [x for x in t if x[1] not in ("차례", "표", "그림") and not x[1].startswith("[")]
hm = os.path.join(SAMPLES, "HM_bm.pdf")
if os.path.exists(hm) and "eng" in (_ocr.available_langs() or []):
    res = oh.chapter_pages_fast(hm, lang="eng")
    tr_pages = [p for _l, _t, p in truth_of(hm)]
    chk([p for _n, p in res] == tr_pages and [n for n, _p in res] == [f"CHAPTER {i}" for i in range(1, 31)],
        "F1 HM: 장 30개 쪽·이름", f"{len(res)}개")
else:
    print("SKIP - F1 HM_bm.pdf 또는 Tesseract 없음")

def sample_pages(path, toc_pages):
    from viewer.study import study_store as ss
    from viewer.study.ocr_pages import OcrPages
    ss.enable_pending(False)
    store = ss.StudyStore(root / ("study_" + Path(path).stem[:4] + ".db"))
    op = OcrPages(path, store=store)
    try:
        rows = tp.parse_toc_pages(path, toc_pages, ocr=op)
        with pn.PrintedPages(path, ocr=op) as pp:
            est = pp.estimate(max(toc_pages) + 1, pp.page_count)
            pn.map_rows(rows, est, pp.page_count)
            pn.refine_chapter_pages(rows, pp.text_of, skip=set(toc_pages))
        return rows
    finally:
        op.close(); store.close()

def score(rows, truth, fix=None):
    import difflib, re
    norm = lambda s: re.sub(r"[\s\W_]+", "", re.sub(r"^\s*(제\s*\d+\s*장|\d+\s*[\.\)]|\(\d+\))\s*", "", s)).lower()
    used, ok = set(), 0
    for _l, t, p in truth:
        p = (fix or {}).get(p, p)
        best, bi = 0, None
        for i, r in enumerate(rows):
            if i not in used:
                sc = difflib.SequenceMatcher(None, norm(t), norm(r["title"])).ratio()
                if sc > best: best, bi = sc, i
        if bi is not None and best >= 0.5:
            used.add(bi); ok += (rows[bi].get("page") == p)
    return ok

ps = os.path.join(SAMPLES, "심리검사의이해_최정윤_bm.pdf")
if os.path.exists(ps):
    rows = sample_pages(ps, list(range(6, 12)))
    truth = truth_of(ps)
    ok = score(rows, truth)
    chk(len(rows) >= 200 and ok >= 184, "F2 심리검사: 목차 표·쪽(정답 188)", f"행 {len(rows)} · 쪽 맞음 {ok}")
else:
    print("SKIP - F2 심리검사의이해_최정윤_bm.pdf 없음")
pa = os.path.join(SAMPLES, "성격심리.pdf")
_pa_truth = truth_of(pa) if os.path.exists(pa) else []
if os.path.exists(pa) and len(_pa_truth) != 29:
    # 261105: 샘플에 생성 책갈피(214개)가 [저장]돼 정답이 바뀌었다 — beta.3 코드로도 같은 값(행 195)이라 코드 회귀 아님.
    #         원래 29개 책갈피 판을 _samples 에 되돌려 놓으면 다시 잰다.
    print(f"SKIP - F3 성격심리.pdf 책갈피가 원래 정답(29개)이 아님 — {len(_pa_truth)}개")
elif os.path.exists(pa):
    rows = sample_pages(pa, list(range(9, 18)))
    truth = _pa_truth
    # 사용자 결정(261101-2): 목표는 내용이 있는 쪽 — 정답이 한 쪽 앞이던 곳(그림으로 확인)
    ok = score(rows, truth, fix={79: 80, 83: 84, 45: 46, 60: 61, 186: 187})
    chk(len(rows) >= 200 and ok >= 27, "F3 성격심리: 목차 표·쪽(정답 29)", f"행 {len(rows)} · 쪽 맞음 {ok}")
else:
    print("SKIP - F3 성격심리.pdf 없음")

print()
print("ALL PASS" if not fails else f"FAILED {len(fails)}: {fails}")
sys.exit(1 if fails else 0)
