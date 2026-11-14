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
  image_strips_pdf() 그림 전용 — 가상 프린터·사진→PDF 꼴, 쪽마다 2048px Flate 그림 띠(261107-19, 응답성 SOT §7.5)
  tiled_bg_pdf()   발표 슬라이드 꼴 — 첫 쪽 질감 배경을 4×4pt 내장 그림(BI) 6만 9천 번으로 깔아 쪽 훑기가 비싸다(261114-11, 응답성 SOT §6)
  paragraph_pdf()  양쪽 맞춤 한글 문단으로 꽉 찬 3쪽 + 제목·목록 줄, 설치 안 된 CJK 글꼴(261113-3, 형식 변환 쪽 맞춤·줄 잇기)
  ruled_table_pdf()  괘선이 **선으로 그려진** 3열 표 — pdfplumber 가 표로 인식한다
                 (텍스트 창 SOT §3.3 — 칸을 놓쳐도 글을 잃지 않는지)
  scanned_form_pdf() 스캔 서식 모사 — 그림 위에 **보이지 않는 글자**(render mode 3)로
                 4칸짜리 행을 얹고 잡음(작은 글자·기호·홀쭉한 한 글자)을 섞었다
                 (SOT §3.5·§3.6 — 잡음 거르기·한 행 한 줄·2단 오해 방지)

생성 비용을 매번 치르지 않도록 `%TEMP%` 아래 **버전 붙은 폴더에 캐시**한다.
픽스처 내용을 바꾸면 `_VER` 을 올려 캐시를 무효화할 것.

※ `test_ocr_bookmarks.py` 는 **일부러 이 픽스처를 쓰지 않는다** — 실제 스캔본의
  장식체를 OCR 이 읽어내는지를 보는 검사라, 깨끗한 합성 이미지로 바꾸면 더 약한
  검사가 된다(그 파일 주석 참조).
"""
import os
from pathlib import Path

_VER = "v5"
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
# 한글이 든 픽스처용 글꼴 — 없으면 기본 글꼴(라틴만)로 만든다.
_KRFONT = next((f for f in (r'C:\Windows\Fonts\malgun.ttf',
                            r'C:\Windows\Fonts\gulim.ttc')
                if Path(f).exists()), '')


KRFONT = _KRFONT      # 검사에서도 같은 글꼴을 쓴다(한글 픽스처)


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


_STRIP_PAGES = 3


def _build_image_strips_pdf(dst: Path) -> None:
    """261107-19(응답성 SOT §7.5): **그림 전용 PDF** — 가상 프린터(Ghostscript)·사진→PDF 가 만드는 꼴.
    A4 3쪽, 쪽마다 폭 2048px 그림 띠 4개(FlateDecode, 글자층 없음). 그림에 무늬를 그려 넣어 실제 사진처럼 압축이 덜 되게 한다."""
    import fitz
    out = fitz.open()
    W, H = 595.0, 842.0
    band = H / 4
    for i in range(_STRIP_PAGES):
        src = fitz.open()
        sp = src.new_page(width=W, height=H)
        for k in range(60):                              # 색 무늬(띠마다 다르게)
            x = (k * 37 + i * 11) % int(W); y = (k * 53 + i * 7) % int(H)
            sp.draw_circle((x, y), 20 + (k * 13) % 70, color=None,
                           fill=(((k * 7) % 10) / 10.0, ((k * 3 + i) % 10) / 10.0, ((k * 5) % 10) / 10.0))
            sp.insert_text((20 + (k * 29) % 500, 20 + (k * 41) % 800), "photo %d-%d" % (i, k), fontsize=9 + k % 12)
        p = out.new_page(width=W, height=H)
        for s in range(4):
            r = fitz.Rect(0, s * band, W, (s + 1) * band)
            z = 2048.0 / W
            pix = sp.get_pixmap(matrix=fitz.Matrix(z, z), clip=r)
            # 사진 같은 잡음(아래 1비트, 띠 둘에 하나) — 큰 정수 XOR 로 한 번에. 압축이 덜 돼 실제 산출물(쪽당 ~2MB)과 비슷한 무게가 된다
            if s % 2:
                p.insert_image(r, pixmap=pix)
                continue
            raw = pix.samples
            noise = int.from_bytes(os.urandom(len(raw)), "little") & int.from_bytes(b"\x01" * len(raw), "little")
            mixed = (int.from_bytes(raw, "little") ^ noise).to_bytes(len(raw), "little")
            pix = fitz.Pixmap(fitz.csRGB, pix.width, pix.height, mixed, False)
            p.insert_image(r, pixmap=pix)
        src.close()
    out.save(str(dst), deflate=True)
    out.close()


def image_strips_pdf() -> str:
    """그림 전용 PDF(가상 프린터·사진→PDF 꼴, 3쪽 · 쪽마다 2048px Flate 띠 4개) 경로 — 측정 묶음 T7 도 이것을 쓴다."""
    d = _ensure_dir()
    p = d / "sample_image_strips.pdf"
    if not p.exists() or p.stat().st_size == 0:
        _build_image_strips_pdf(p)
    return str(p)


_TILE_N = 69000


def _build_tiled_bg_pdf(dst: Path) -> None:
    """261114-11(응답성 SOT §6 표·단어학습 SOT §14.18): 발표 슬라이드 꼴 — 첫 쪽 질감 배경을 **4×4pt 내장 그림(BI, 16×16 1비트)** 6만 9천 번 깔고
    그 위에 보이는 영문 글(가로 쪽). 실제 TRB9.pdf 는 CCITT 내장 그림 23,296개 — 쪽 내용을 한 번 훑는 데 0.2~0.67초라 메인·배경에서 여러 번 훑으면 선다.
    이 픽스처 한 번 훑기는 약 0.3초(무압축이라 개수를 늘렸다). 2~5쪽은 보통 글."""
    import fitz
    doc = fitz.open()
    W, H = 842.0, 595.0
    p = doc.new_page(width=W, height=H)
    p.insert_text((1, 1), " ", fontsize=1)                  # 내용 흐름 하나를 만든다(아래에서 갈아 끼운다)
    cols = int(W // 4)
    mask = bytes((k * 37) & 0xFF for k in range(32))        # 16×16 1비트 무늬
    # TRB9.pdf 와 같은 꼴 — 내장 그림(BI … ID … EI, 16×16 1비트 마스크)을 칸마다. 그림 객체를 부르는 Do 와 달리 쪽을 훑을 때마다 그림을 다시 읽는다
    ops = [b"q 4 0 0 4 %d %d cm BI /IM true /W 16 /H 16 /BPC 1 /D [1 0] ID " % ((k % cols) * 4, int(H) - 4 - (k // cols) * 4)
           + mask + b" EI Q" for k in range(_TILE_N)]
    cx = p.get_contents()[0]
    doc.update_stream(cx, b"0.35 0.35 0.35 rg\n" + b"\n".join(ops) + b"\n")
    p.insert_text((60, 300), "Accelerated Pavement Testing and Modelling in South Africa", fontsize=22)
    p.insert_text((60, 340), "Materials and pavement specialist workshop presentation", fontsize=16)
    for i in range(4):
        q = doc.new_page(width=W, height=H)
        q.insert_text((60, 120), f"Slide {i + 2} pavement testing results and analysis", fontsize=18)
    doc.save(str(dst), deflate=True)
    doc.close()


def tiled_bg_pdf() -> str:
    """첫 쪽 배경을 작은 내장 그림 6만 9천 개로 깐 발표 PDF(5쪽, 가로) 경로 — 쪽 훑기가 비싼 쪽(261114-11)."""
    d = _ensure_dir()
    p = d / "sample_tiled_bg.pdf"
    if not p.exists() or p.stat().st_size == 0:
        _build_tiled_bg_pdf(p)
    return str(p)


_PARA_PAGES = 3
_PARA_BODY = ("중대재해를 줄이기 위한 위험성평가는 노사가 함께 사업장의 유해 위험요인을 스스로 찾아 개선 대책을 세우고 이행하는 "
              "제도이며 현장에 맞게 자리 잡도록 기준과 지원을 함께 마련한다. ")


def _build_paragraph_pdf(dst: Path) -> None:
    """261113-3(형식 변환 SOT §1.2): 쪽을 채운 **한글 문단**(여러 줄, 오른쪽 끝 가까이까지) + 제목 + 목록 줄 + 꼬리말 — 3쪽.
    글꼴은 PDF 기본 CJK(`korea` — Windows 에 설치되지 않은 이름)라 Word 가 다른 글꼴로 바꿔 그리는 길을 탄다."""
    import fitz
    doc = fitz.open()
    for i in range(_PARA_PAGES):
        pg = doc.new_page(width=595, height=842)
        y = 70.0
        pg.insert_text((72, y + 16), f"제{i + 1}장 추진 배경", fontsize=18, fontname="korea")
        y += 40
        for k in range(3):                                   # 문단 셋 — 줄마다 오른쪽 끝까지(양쪽 맞춤), 문단 사이 빈 자리
            r = fitz.Rect(72, y, 523, y + 200)
            left = pg.insert_textbox(r, _PARA_BODY * 3, fontsize=12, fontname="korea", align=fitz.TEXT_ALIGN_JUSTIFY,
                                     lineheight=1.4)
            y += (200 - left) + 14
            if k == 1:
                for j, t in enumerate(("○ 첫째 목록 줄", "○ 둘째 목록 줄", "○ 셋째 목록 줄")):
                    pg.insert_text((90, y + 12), t, fontsize=12, fontname="korea")
                    y += 18
                y += 8
        pg.insert_text((290, 815), f"- {i + 1} -", fontsize=9, fontname="korea")
    doc.save(str(dst))
    doc.close()


def paragraph_pdf() -> str:
    """양쪽 맞춤 한글 문단으로 쪽을 채운 PDF(3쪽, 설치 안 된 글꼴) 경로 — 형식 변환 쪽 맞춤·줄 잇기 검사(261113-3)."""
    d = _ensure_dir()
    p = d / "sample_paragraphs.pdf"
    if not p.exists() or p.stat().st_size == 0:
        _build_paragraph_pdf(p)
    return str(p)


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


def _build_ruled_table_pdf(dst) -> None:
    """괘선을 **선으로** 그린 3열 표 — pdfplumber 가 표로 잡는다."""
    import fitz
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    x = [70.0, 240.0, 400.0, 520.0]
    y = [160.0, 185.0, 210.0, 235.0]
    for yy in y:
        pg.draw_line(fitz.Point(x[0], yy), fitz.Point(x[-1], yy))
    for xx in x:
        pg.draw_line(fitz.Point(xx, y[0]), fitz.Point(xx, y[-1]))
    rows = [('항 목', '시 험 방 법', '기 준'),
            ('모래당량(%)', 'KS F 2340', '50 이상'),
            ('잔골재 입형(%)', 'KS F 2384', '45 이상')]
    kw = dict(fontsize=10, fontfile=_KRFONT, fontname='kr') if _KRFONT else dict(fontsize=10)
    for r, cells in enumerate(rows):
        for c, t in enumerate(cells):
            pg.insert_text((x[c] + 6, y[r] + 17), t, **kw)
    pg.insert_text((70, 120), '<표 1> 잔골재의 품질', **kw)
    doc.save(str(dst))
    doc.close()


def _build_scanned_form_pdf(dst) -> None:
    """그림 위에 **보이지 않는 글자**로 얹은 서식 + 잡음(§3.5)."""
    import fitz
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 595, 842))
    pix.clear_with(255)
    pg.insert_image(pg.rect, pixmap=pix)
    base = dict(render_mode=3)
    if _KRFONT:
        base.update(fontfile=_KRFONT, fontname='kr')
    # 한 행에 네 칸 — 가운데가 비어 보이지만 2단이 아니다(왼쪽 끝이 제각각)
    cells = [(52, 100, '제품종류'), (155, 100, '일반아스팔트혼합물'),
             (330, 100, '구 분'), (440, 100, '요약표'),
             (52, 130, '제품규격'), (200, 130, 'WC-3'),
             (330, 130, '작성자'), (470, 130, '홍길동'),
             (52, 160, '작성일자'), (185, 160, '2026년 2월'),
             (330, 160, '확인자'), (469, 160, '김철수')]
    for cx, cy, t in cells:
        pg.insert_text((cx, cy), t, fontsize=10, **base)
    pg.insert_text((60, 220), '[ Hot Asphalt Paving Mixture', fontsize=10, **base)
    pg.insert_text((215, 220), ']', fontsize=10, **base)   # 같은 줄의 닫는 괄호
    pg.insert_text((60, 260), '아주 큰 제목', fontsize=30, **base)
    # 잡음 셋 — 너무 작다 / 기호만 / 한 글자인데 홀쭉하다
    pg.insert_text((400, 60), '픔', fontsize=2.0, **base)
    pg.insert_text((430, 300), '■', fontsize=16, **base)
    pg.insert_text((470, 300), '☜', fontsize=14, **base)
    doc.save(str(dst))
    doc.close()


def ruled_table_pdf() -> str:
    """괘선이 그려진 3열 표가 든 PDF 경로(텍스트 창 SOT §3.3)."""
    d = _ensure_dir()
    p = d / 'sample_table.pdf'
    if not p.exists() or p.stat().st_size == 0:
        _build_ruled_table_pdf(p)
    return str(p)


def scanned_form_pdf() -> str:
    """보이지 않는 글자층 + 잡음이 든 서식 PDF 경로(텍스트 창 SOT §3.5·§3.6)."""
    d = _ensure_dir()
    p = d / 'sample_scanform.pdf'
    if not p.exists() or p.stat().st_size == 0:
        _build_scanned_form_pdf(p)
    return str(p)

def toc_entries():
    """`text_pdf()` 에 심은 TOC(레벨, 제목, 1-based 페이지) 사본."""
    return list(_TOC)


def wait_main_open(mw, timeout: float = 10.0) -> bool:
    """261108-22(응답성 SOT §4.9): 처음 보는 PDF 의 본문 열기는 배경에서 데운 뒤 일어난다 — 끝날 때까지 이벤트를 돌린다.
    `open_pdf`·`_load_main` 바로 뒤에 본문을 보는 검사가 부른다(실제 길 그대로, 기다리기만). 다 열렸으면 True."""
    import time
    from PyQt6.QtWidgets import QApplication
    t0 = time.perf_counter()
    while mw._main_opening() and time.perf_counter() - t0 < timeout:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    return not mw._main_opening()


def autotag_off(mw=None) -> None:
    """261114-19(검사 작성 SOT §14.7.2): 자동 태그와 상관없는 검사에서 PDF 자동 태그를 끈다 — 기본 켬(261113-10)이라
    폴더를 열면 배경 계산이 목록 글(`·#태그` 꼬리)·첫 실행 요약 창을 바꿔 검사가 흔들린다.
    `mw` 를 주면 그 창의 설정을, 없으면 시험 모드 설정 폴더의 settings.json 을(MainWindow 를 만들기 **전에**) 고친다.
    `auto_tag_on_migrated` 도 True — 꺼 둔 설정을 한 번 켜는 옮기기(태그 SOT §3.5)가 다시 켜지 않게."""
    vals = {"auto_tag_enabled": False, "auto_tag_on_migrated": True, "autotag_summary_shown": True}
    if mw is not None:
        mw._prefs.update(vals)
        return
    import json
    from viewer.settings_store import settings_path
    p = Path(settings_path("settings.json"))
    assert "qttest" in str(p).lower(), "시험 모드(QStandardPaths.setTestModeEnabled)에서만 — 실제 설정 폴더를 쓰지 않는다: %s" % p
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        d = {}
    prefs = dict(d.get("preferences") or {})              # 앱은 settings.json 의 "preferences" 를 읽는다
    prefs.update(vals)
    d["preferences"] = prefs
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


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
