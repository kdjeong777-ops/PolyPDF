# -*- coding: utf-8 -*-
"""스캔 PDF OCR 책갈피(헤딩 인식) 통합 테스트.
1) regex_level 패턴(영문 CHAPTER/PART/특수 + 한글 장/절/특수)
2) _group_lines 줄 묶기
3) 실제 스캔본(HM.pdf) 앞부분 OCR → 'CHAPTER N' 헤딩 인식
4) 추출 책갈피 → pypdf 임베드 → get_toc 재확인(소형 PDF)
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  OK  " if cond else " FAIL ") + name + (f"  {extra}" if extra else ""))
    ok = ok and bool(cond)

from viewer.study.ocr_headings import regex_level, _group_lines, extract_ocr_bookmarks

# --- 1) 정규식 레벨 ---
cases = [
    ("CHAPTER 1", 0), ("Chapter 12", 0), ("CHAPTER ONE", 0), ("PART II", 0),
    ("PROLOGUE", 0), ("Epilogue", 0), ("제1장", 0), ("제 3 장", 0),
    ("제2절", 1), ("프롤로그", 0), ("부록", 0),
    ("What's two plus two?", None), ("Something about the question", None),
    ("123", None),
]
for text, exp in cases:
    check(f"regex_level({text!r})={exp}", regex_level(text) == exp,
          f"got={regex_level(text)}")

# --- 2) 줄 묶기 ---
words = [
    {"surface": "CHAPTER", "x0": 50, "y0": 100, "x1": 180, "y1": 140},
    {"surface": "1",       "x0": 190, "y0": 102, "x1": 210, "y1": 138},
    {"surface": "What's",  "x0": 50, "y0": 300, "x1": 110, "y1": 318},
    {"surface": "two",     "x0": 115, "y0": 300, "x1": 150, "y1": 318},
]
lines = _group_lines(words)
check("줄 2개로 묶임", len(lines) == 2, f"n={len(lines)}")
check("첫 줄 'CHAPTER 1'", lines[0]["text"] == "CHAPTER 1", lines[0]["text"])
check("헤딩 줄이 본문보다 큼", lines[0]["h"] > lines[1]["h"])

# --- 4) 임베드 라운드트립(소형 PDF) ---
import fitz
from viewer._vendor.pdf_bookmarker.core import Bookmark
from viewer import bookmarker_bridge as bridge
small = r"C:/Claude/MPDF/smart_pdf_viewer/260518_1333_screenshots.pdf"
if os.path.exists(small) and bridge.is_available():
    d = fitz.open(small); npg = d.page_count; d.close()
    bms = [Bookmark("CHAPTER 1", 1, 0)]
    if npg >= 2:
        bms.append(Bookmark("CHAPTER 2", 2, 0))
    out = os.path.join(os.environ.get("TEMP", "."), "rt_bm.pdf")
    bridge.load()
    bridge.apply_to_pdf(small, out, bms)
    d2 = fitz.open(out); toc = d2.get_toc(); d2.close()
    check("임베드 후 get_toc 일치", len(toc) == len(bms) and toc[0][1] == "CHAPTER 1",
          f"toc={toc}")
else:
    print("  SKIP 임베드 라운드트립(소형 PDF/모듈 없음)")

# --- 3) 실제 스캔본 OCR (HM.pdf 앞부분) ---
HM = r"C:/Claude/MPDF/HM.pdf"
if os.path.exists(HM):
    # 정규식 경로(큰글자자동 OFF)로 'CHAPTER 1' 인식 검증 — CHAPTER 1은 10p
    def make_cancel(limit):
        st = {"n": 0}
        def c():
            st["n"] += 1
            return st["n"] > limit
        return c
    def prog(d, t, m):
        if d % 5 == 0:
            print(f"    {m}")
    bms = extract_ocr_bookmarks(HM, dpi=150, lang="eng",
                                use_font_auto=False, progress=prog,
                                should_cancel=make_cancel(12))
    titles = [(b.page, b.title) for b in bms]
    print("  정규식 헤딩:", titles)
    ch1 = [b for b in bms if b.title == "CHAPTER 1"]
    check("HM에서 'CHAPTER 1' 정규식 인식(장식체 OCR 보정)", len(ch1) >= 1,
          f"titles={titles}")
    check("CHAPTER 1이 10p", ch1 and ch1[0].page == 10,
          f"page={ch1[0].page if ch1 else '-'}")
    # 큰글자자동 ON 이면 후보가 더 많아짐(노이즈 포함, 사용자 선택 옵션)
    bms2 = extract_ocr_bookmarks(HM, dpi=150, lang="eng",
                                 use_font_auto=True,
                                 should_cancel=make_cancel(12))
    check("큰글자자동 ON 이 후보 ≥ 정규식만", len(bms2) >= len(bms),
          f"auto={len(bms2)} regex={len(bms)}")
else:
    print("  SKIP HM.pdf 없음")

print("\n=== " + ("ALL PASS" if ok else "FAILURE") + " ===")
sys.exit(0 if ok else 1)
