# -*- coding: utf-8 -*-
"""2단 빽빽한 가로 설명서는 발표자료가 아니다 · 보증서 낱말 (태그 SOT §5.3 ②·③, 261114-10 사용자 지시).

사용자 보고: 'Office.키보드.Leopold.FC980M.pdf'(2쪽 A4 가로 842×595 = 종횡비 1.42, 글자층 없는 스캔)가 #발표자료.
  "이거 발표자료 아니고 설명서야. 2단으로 편집되어 있고, 글씨도 작고, 보증서도 있어"
  1.9 상한(261114-2)에 안 걸린 까닭 = 종횡비 1.42 · 글자층 없음(쪽당 0자) · 색인 OCR 글자도 없음 → 글자로는 판정 불가.
실제 PDF 로(쪽 그림을 만든 스캔 — 글자층 없음), 실제 설정 폴더를 쓰지 않는다(검사 작성 SOT §14.7.2).
A. 글자층 없는 가로 스캔: 2단·작은 글씨 빽빽 → 설명서, 큰 글씨 슬라이드(2단 글머리라도) → 발표자료 그대로
B. 글자층 있는 가로 2단 빽빽 → 설명서, 글자 적은 16:9 슬라이드 → 발표자료
C. 본문 '보증서' → 설명서, 이름 '보증서' → 설명서, 약한 낱말(A/S·고객 지원·보증기간·warranty)·이름 'warranty' 로는 아니다
   (_samples 실측: 포장 성능보증 보고서·논문·뉴스·장비 개요 6개가 그 낱말로 잘못 걸렸다)
D. 그 전 재료(2단 값 없음) — 색인 DB 재료를 읽을 때 2단만 더 재서 채운다(재료를 통째로 다시 만들지 않는다)
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from pathlib import Path

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_twocol_"))
W, H = 842, 595                       # A4 가로(종횡비 1.42 — 1.9 상한 안)
LINE = "레오폴드 FC 시리즈 기계식 키보드는 제품 구입 시점부터 일년간 보증합니다 keyboard"


def text_doc(two_col_dense: bool, color=(0.45, 0.45, 0.45), nlines=40, nchar=44):
    d = fitz.open()
    pg = d.new_page(width=W, height=H)
    if two_col_dense:                 # 2단 · 7pt · 단마다 40줄 — 접지 설명서
        for col in (40, W / 2 + 25):
            for i in range(nlines):
                pg.insert_text((col, 50 + i * 12), LINE[:nchar], fontsize=7, fontname="korea", color=color)
    else:                             # 슬라이드 — 큰 제목 + 두 단 글머리 6줄(큰 글씨)
        pg.insert_text((60, 90), "Pavement Recycling", fontsize=36, color=color)
        for col in (60, W / 2 + 30):
            for i in range(6):
                pg.insert_text((col, 180 + i * 55), "- bullet item %d" % i, fontsize=22, color=color)
    return d


def save_scan(rel, two_col_dense, pages=2):
    """쪽 그림 하나뿐(글자층 없음) — 스캔본과 같은 꼴."""
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    src = text_doc(two_col_dense)
    pm = src[0].get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY)
    src.close()
    d = fitz.open()
    for _ in range(pages):
        d.new_page(width=W, height=H).insert_image(fitz.Rect(0, 0, W, H), pixmap=pm)
    d.save(str(p)); d.close()
    return str(p)


def save_text(rel, two_col_dense, pages=2):
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    d = fitz.open()
    for _ in range(pages):
        d.insert_pdf(text_doc(two_col_dense, color=(0, 0, 0), nlines=20, nchar=12))   # 쪽당 약 500자 — 발표자료 꼴(< 600)
    d.save(str(p)); d.close()
    return str(p)


try:
    from viewer import auto_tag as AT

    def feats(path):
        return AT.extract_features(path)          # 색인 글자 없이 — fitz 로 읽는다(스캔은 0자)

    def fmt(path, f=None):
        return AT.classify_format(f or feats(path), {})

    # A — 글자층 없는 스캔(폴더 이름 단서 없음)
    leo = save_scan("x/Office.키보드.FC980M.pdf", True)
    f = feats(leo)
    chk(f.scanned and 1.3 <= f.aspect <= 1.9, "A 준비 — 글자층 없는 A4 가로 스캔", "scan=%s ar=%.2f" % (f.scanned, f.aspect))
    chk(fmt(leo, f) == "설명서", "A 2단·작은 글씨 빽빽한 가로 스캔 → 설명서(발표자료 아님)", "%s twocol=%s" % (fmt(leo, f), getattr(f, "twocol", "-")))
    sl = save_scan("x/HIR 발표.pdf", False)
    chk(fmt(sl) == "발표자료", "A 큰 글씨 슬라이드 스캔(두 단 글머리라도) → 발표자료 그대로", str(fmt(sl)))

    # B — 글자층 있는 가로
    tx = save_text("x/접지 안내.pdf", True)
    ft = feats(tx)
    chk(fmt(tx, ft) == "설명서", "B 글자층 있는 가로 2단 빽빽(쪽당 글자 < 600) → 설명서", "%s tpp=%d twocol=%s" % (fmt(tx, ft), ft.text_per_page, getattr(ft, "twocol", "-")))
    chk(fmt(save_text("x/발표.pdf", False)) == "발표자료", "B 글자 적은 가로 슬라이드 → 발표자료")

    # C — 낱말(본문은 앞 3쪽·뒤 2쪽 원문)
    def body(txt):
        g = AT.Features(path=str(tmp / "y" / "a.pdf"), stem="a", page_count=2, struct_text=txt, aspect=0.71, text_per_page=900)
        return AT.classify_format(g, {})
    chk(body("보 증 서 아님 — 보증서 본 보증서는 제품에 문제가 발생했을 경우") == "설명서", "C 본문 '보증서' → 설명서", str(body("본 보증서는")))
    chk(body("고장 시 A/S 를 요청한다") != "설명서", "C 약한 낱말 하나('A/S')만으로는 설명서 아님", str(body("A/S")))
    chk(body("성능보증 보증기간 5년 warranty 고객지원 고객센터") != "설명서", "C 약한 낱말이 여럿이어도 설명서 아님(성능보증 보고서)")
    chk(body("This limited warranty is valid only in Korea.") == "설명서", "C 본문 'limited warranty' → 설명서")
    g = AT.Features(path=str(tmp / "y" / "키보드 보증서.pdf"), stem="키보드 보증서", page_count=1)
    chk(AT.classify_format(g, {}) == "설명서", "C 이름 '보증서' → 설명서")
    g = AT.Features(path=str(tmp / "y" / "Minnesota Warranty Use Summary.pdf"), stem="Minnesota Warranty Use Summary", page_count=1)
    chk(AT.classify_format(g, {}) != "설명서", "C 이름 'warranty'(포장 성능보증)만으로는 설명서 아님")

    # D — 그 전(2단 값 없는) 재료: 읽을 때 2단만 채운다
    from viewer.indexer import PdfIndex
    ix = PdfIndex(str(tmp / "index.db"))
    try:
        d0 = AT.features_to_dict(feats(leo))
        d0.pop("twocol", None)
        ix.save_tagfeat(leo, d0, None)
        got = ix.tagfeat(leo)
        chk(got is not None and "twocol" in got[0], "D 그 전 재료를 읽으면 2단 값이 채워진다", str(got and sorted(got[0])))
        f2 = AT.features_from_dict(leo, got[0]) if got else None
        chk(f2 is not None and AT.classify_format(f2, {}) == "설명서", "D 채운 재료로 → 설명서")
        got2 = ix.tagfeat(leo)
        chk(got2 is not None and got2[0].get("twocol") == got[0].get("twocol"), "D 채운 값은 색인 DB 에 남는다(다음엔 다시 재지 않음)")
        port2 = dict(d0, aspect=0.71)
        port2.pop("twocol", None)
        chk(not AT.needs_twocol(port2), "D 세로 쪽 재료는 2단을 재지 않는다")
    finally:
        ix.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("=" * 60)
print("ALL PASS" if not fails else "FAIL %d: %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
