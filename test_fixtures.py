# -*- coding: utf-8 -*-
"""260628-10: 테스트용 샘플 PDF를 **직접 생성**한다.

종전에는 오프스크린 테스트 13개가 `C:/Claude/MPDF/_samples/…` 의 실제 업무 PDF를
**절대경로로 하드코딩**해 참조했다. 문제가 셋이었다.

  1. 그 파일이 없는 기계에서는 검사가 조용히 건너뛰어진다(가짜 통과).
  2. 샘플을 옮기면 13개 파일이 한꺼번에 깨진다.
  3. 업무 문서의 파일명이 **공개 저장소**에 그대로 들어간다.

여기서 만드는 PDF는 각 테스트가 실제로 의존하는 성질만 재현한다.

  text_pdf()     디지털 문서 — 텍스트 레이어 있음, **TOC 12개**, 30쪽
                 (`_pdf_is_scanned` → False, `_read_orig_toc`/`load_single_pdf` 용)
  scanned_pdf()  스캔 모사 — 페이지가 **이미지 뿐**이라 텍스트 레이어가 없음, 14쪽
                 (`_pdf_is_scanned` → True. 앞 12쪽 표본의 60% 이상이 'ocr' 로 판정되면 참)

생성 비용을 매번 치르지 않도록 `%TEMP%` 아래 **버전 붙은 폴더에 캐시**한다.
픽스처 내용을 바꾸면 `_VER` 을 올려 캐시를 무효화할 것.

※ `test_ocr_bookmarks.py` 는 **일부러 이 픽스처를 쓰지 않는다** — 실제 스캔본의
  장식체를 OCR 이 읽어내는지를 보는 검사라, 깨끗한 합성 이미지로 바꾸면 더 약한
  검사가 된다(그 파일 주석 참조).
"""
import os
from pathlib import Path

_VER = "v1"
_DIR = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / f"polypdf_fixtures_{_VER}"

# TOC — 계층(레벨 1/2)을 섞어 트리 구성까지 검사되게 한다.
_TOC = [
    (1, "표지", 1),
    (1, "목차", 2),
    (1, "제1장 총칙", 3),
    (2, "1.1 적용 범위", 4),
    (2, "1.2 용어 정의", 6),
    (1, "제2장 재료", 9),
    (2, "2.1 골재", 10),
    (2, "2.2 아스팔트", 13),
    (1, "제3장 시공", 17),
    (2, "3.1 준비", 18),
    (2, "3.2 포설", 22),
    (1, "부칙", 27),
]
_TEXT_PAGES = 30
_SCAN_PAGES = 14


def _ensure_dir() -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR


def _build_text_pdf(dst: Path) -> None:
    import fitz
    doc = fitz.open()
    for i in range(_TEXT_PAGES):
        pg = doc.new_page(width=420, height=595)          # A5 정도
        pg.insert_text((50, 70), f"Sample Document  page {i + 1}", fontsize=14)
        for ln in range(10):
            pg.insert_text((50, 110 + ln * 22),
                           f"line {ln} of page {i + 1} - sample body text", fontsize=10)
    doc.set_toc([[lvl, title, pno] for lvl, title, pno in _TOC])
    doc.save(str(dst))
    doc.close()


def _build_scanned_pdf(dst: Path) -> None:
    """텍스트를 **이미지로 굽고** 그 이미지만 담은 PDF — 텍스트 레이어가 없다."""
    import fitz
    src = fitz.open()
    for i in range(_SCAN_PAGES):
        pg = src.new_page(width=420, height=595)
        pg.insert_text((50, 80), f"SCANNED PAGE {i + 1}", fontsize=20)
        for ln in range(6):
            pg.insert_text((50, 130 + ln * 26), f"scanned body line {ln}", fontsize=12)
    out = fitz.open()
    for i in range(src.page_count):
        pix = src.load_page(i).get_pixmap(dpi=110)
        p = out.new_page(width=pix.width, height=pix.height)
        p.insert_image(p.rect, pixmap=pix)                 # 이미지만 → 텍스트 레이어 없음
    src.close()
    out.save(str(dst))
    out.close()


def text_pdf() -> str:
    """디지털 PDF(텍스트 레이어 + TOC 12개, 30쪽) 경로."""
    d = _ensure_dir()
    p = d / "sample_text.pdf"
    if not p.exists() or p.stat().st_size == 0:
        _build_text_pdf(p)
    return str(p)


def scanned_pdf() -> str:
    """스캔 모사 PDF(이미지 전용, 14쪽) 경로 — `_pdf_is_scanned` 가 True 로 본다."""
    d = _ensure_dir()
    p = d / "sample_scanned.pdf"
    if not p.exists() or p.stat().st_size == 0:
        _build_scanned_pdf(p)
    return str(p)


def toc_entries():
    """`text_pdf()` 에 심은 TOC(레벨, 제목, 1-based 페이지) 사본."""
    return list(_TOC)


if __name__ == "__main__":                                 # 수동 점검용
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    import fitz
    from viewer.workers import _pdf_is_scanned
    for fn in (text_pdf, scanned_pdf):
        path = fn()
        doc = fitz.open(path)
        print(f"{fn.__name__:14} {doc.page_count:3}쪽  TOC {len(doc.get_toc()):2}개  "
              f"1쪽텍스트 {len((doc[0].get_text() or '').strip()):4}자  "
              f"is_scanned={_pdf_is_scanned(path)}")
        doc.close()
    print("경로:", _DIR)
