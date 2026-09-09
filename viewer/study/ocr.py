"""OCR 엔진 — 스캔 감지·300DPI 렌더·Tesseract OCR(단어좌표)·텍스트 전처리.

P0 검증 반영(계획서 §14·§15):
  - 엔진: Tesseract(주). eng+kor. 단어좌표는 image_to_data TSV.
  - 스캔 감지: 텍스트 '길이'가 아닌 '품질(사전단어/한글 유효 비율)' 로 판정.
    깨끗한 디지털 레이어가 있으면 OCR 생략하고 레이어 사용(한글 기술문서 등).
  - 전처리: 줄바꿈 하이픈 복원 + 반복 머리말/꼬리말 제거.
Tesseract 미설치/로드 실패 시 OCR 함수는 RuntimeError — 호출자(워커)가 처리.
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

import fitz

from viewer import text_noise as _noise

# --- Tesseract 위치 해석 --------------------------------------------------
_TESS_READY: Optional[bool] = None
_TESS_INFO: dict = {}


def reset_cache() -> None:
    """260618-12: 구성요소 설치(Tesseract 다운로드) 후 재탐색하도록 캐시 초기화."""
    global _TESS_READY, _TESS_INFO
    _TESS_READY = None
    _TESS_INFO = {}


def _candidate_dirs() -> list[Path]:
    cands: list[Path] = []
    # 0) 260618-12: 배포 exe 설치 폴더 옆 tesseract\ (앱 '구성요소 설치'로 받은 경우)
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
            cands.append(base / "tesseract" / "Library" / "bin")
            cands.append(base / "tesseract")
    except Exception:
        pass
    # 1) PyInstaller 동봉 (sys._MEIPASS/tesseract/Library/bin)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(Path(meipass) / "tesseract" / "Library" / "bin")
        cands.append(Path(meipass) / "tesseract")
    # 2) 환경변수 지정
    env = os.environ.get("STUDY_TESSERACT_DIR")
    if env:
        cands.append(Path(env))
    # 3) 개발용 micromamba 환경 (repo/study_spike/mamba/envs/ocr/Library/bin)
    try:
        repo = Path(__file__).resolve().parents[3]   # .../MPDF
        cands.append(repo / "study_spike" / "mamba" / "envs" / "ocr" / "Library" / "bin")
    except Exception:
        pass
    return cands


class _HiddenSubprocess:
    """pytesseract 가 tesseract 를 호출할 때 콘솔(도스창)을 띄우지 않도록 래핑.
    Windows --windowed/frozen 앱에서: CREATE_NO_WINDOW + SW_HIDE + stdin=DEVNULL 주입.
    (도스창 깜빡임 제거 + 잘못된 표준핸들 상속으로 인한 불안정/크래시 방지.)
    전역 subprocess 는 건드리지 않고 pytesseract 모듈의 참조만 교체."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def _inject(self, kwargs):
        if os.name == "nt":
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000  # CREATE_NO_WINDOW
            si = kwargs.get("startupinfo") or self._real.STARTUPINFO()
            si.dwFlags |= self._real.STARTF_USESHOWWINDOW
            si.wShowWindow = self._real.SW_HIDE
            kwargs["startupinfo"] = si
            kwargs.setdefault("stdin", self._real.DEVNULL)
        return kwargs

    def Popen(self, *a, **k):
        return self._real.Popen(*a, **self._inject(k))

    def run(self, *a, **k):
        return self._real.run(*a, **self._inject(k))

    def check_output(self, *a, **k):
        return self._real.check_output(*a, **self._inject(k))


def _harden_pytesseract_subprocess(pytesseract) -> None:
    """pytesseract.pytesseract.subprocess 를 콘솔 숨김 래퍼로 1회 교체."""
    try:
        mod = pytesseract.pytesseract
        if not isinstance(getattr(mod, "subprocess", None), _HiddenSubprocess):
            import subprocess as _sp
            mod.subprocess = _HiddenSubprocess(_sp)
    except Exception:
        pass


def ensure_tesseract() -> dict:
    """pytesseract 가 동봉/개발/PATH 의 tesseract 를 쓰도록 설정. 1회 캐시.
    반환: {ok, exe, tessdata, version, langs} 또는 {ok:False, error}."""
    global _TESS_READY, _TESS_INFO
    if _TESS_READY is not None:
        return _TESS_INFO
    try:
        import pytesseract
    except Exception as e:
        _TESS_READY = False
        _TESS_INFO = {"ok": False, "error": f"pytesseract 미설치: {e}"}
        return _TESS_INFO

    _harden_pytesseract_subprocess(pytesseract)   # 도스창 숨김 + 핸들 안정화

    exe: Optional[Path] = None
    for d in _candidate_dirs():
        cand = d / "tesseract.exe"
        if cand.exists():
            try:
                os.add_dll_directory(str(d))
            except (OSError, AttributeError):
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            exe = cand
            # tessdata: env/share/tessdata(conda 구조) 또는 형제 tessdata.
            # 260908-1: **먼저 있는 것을 고르지 않는다** — 후보가 둘 다 있으면
            #   `kor.traineddata` 가 실제로 든 쪽을 고른다. 옛 설치본에는 `tessdata/` 에
            #   eng·osd 만 있어, 그 폴더를 잡은 뒤 한국어 OCR 이 Tesseract 의 영어 원문
            #   오류로 실패했다(사용자 보고 260908: "Error opening data file … kor.traineddata").
            cands_td = [d.parent.parent / "share" / "tessdata", d / "tessdata"]
            best = None
            for td in cands_td:
                if not td.exists():
                    continue
                if best is None:
                    best = td
                if (td / "kor.traineddata").exists():
                    best = td
                    break
            if best is not None:
                os.environ["TESSDATA_PREFIX"] = str(best)
            break
    if exe is not None:
        pytesseract.pytesseract.tesseract_cmd = str(exe)

    try:
        ver = str(pytesseract.get_tesseract_version())
        try:
            langs = pytesseract.get_languages()
        except Exception:
            langs = []          # 정보용 — 실패해도 OCR 가능
        _TESS_READY = True
        _TESS_INFO = {"ok": True, "exe": str(exe) if exe else "PATH",
                      "tessdata": os.environ.get("TESSDATA_PREFIX", ""),
                      "version": ver, "langs": langs}
    except Exception as e:
        _TESS_READY = False
        _TESS_INFO = {"ok": False, "error": f"tesseract 실행 불가: {e}"}
    return _TESS_INFO


def missing_language(lang: str) -> str:
    """260908-1: 이 언어의 학습 데이터가 없으면 **사람이 읽을 수 있는 안내**를 돌려준다.

    없으면 빈 문자열. Tesseract 가 내는 영어 원문 오류
    ("Error opening data file …/kor.traineddata")는 사용자가 무엇을 해야 하는지
    알려 주지 않는다(사용자 보고 260908 — PDF 병합 뒤 OCR 에서 그대로 노출됐다)."""
    info = ensure_tesseract()
    if not info.get("ok"):
        return ""
    td = info.get("tessdata") or ""
    need = [x for x in str(lang or "eng").split("+") if x]
    gone = []
    for code in need:
        if td and not (Path(td) / f"{code}.traineddata").exists():
            gone.append(code)
    if not gone:
        return ""
    names = {"kor": "한국어", "eng": "영어", "jpn": "일본어", "chi_sim": "중국어(간체)"}
    label = " · ".join(names.get(c, c) for c in gone)
    return (f"{label} OCR 학습 데이터가 없습니다({', '.join(c + '.traineddata' for c in gone)}).\n\n"
            f"찾은 위치: {td or '(미설정)'}\n\n"
            "도구 → 구성요소 설치에서 OCR(Tesseract)을 다시 받으면 채워집니다. "
            "설치본이 오래된 경우 프로그램을 최신 버전으로 올리면 함께 들어옵니다.")


# --- 스캔 감지(텍스트 레이어 품질) ----------------------------------------
_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_HANGUL_RE = re.compile(r"[가-힣]")


def _latin_quality(text: str) -> float:
    """라틴 토큰 중 사전(빈도)에 존재하는 비율 0~1. wordfreq 없으면 휴리스틱."""
    toks = _WORD_RE.findall(text.lower())
    if not toks:
        return 0.0
    sample = toks[:400]
    try:
        from wordfreq import zipf_frequency
        hit = sum(1 for t in sample if zipf_frequency(t, "en") >= 2.0)
        return hit / len(sample)
    except Exception:
        # 폴백: 모음 포함 + 길이 3~15 토큰 비율
        ok = sum(1 for t in sample if 3 <= len(t) <= 15 and re.search(r"[aeiou]", t))
        return ok / len(sample)


def _image_coverage(page: "fitz.Page") -> float:
    """페이지 면적 대비 이미지가 덮는 비율(0~1). 전면 스캔 감지용."""
    try:
        total = float(page.rect.width * page.rect.height) or 1.0
        area = 0.0
        for img in page.get_images(full=True):
            try:
                for r in page.get_image_rects(img[0]):
                    area += abs(r.width * r.height)
            except Exception:
                continue
        return min(area / total, 1.0)
    except Exception:
        return 0.0


# 260909(§14.8, 사용자 보고 "PDF OCR 시 한글이 안 되고 있어"): 언어를 **텍스트층으로
#   고르지 않는다.** OCR 을 돌리는 상황은 텍스트층이 없거나 못 믿을 때인데, 글자가
#   하나도 없으면 `한글 0 > 라틴 0` 이 거짓이라 `eng` 로 떨어져 한글 문서를 영문으로
#   읽었다. 기본값을 한글+영문으로 두고, 설치된 것만 골라 쓴다.
DEFAULT_LANG = "kor+eng"
FALLBACK_LANG = "eng"


def available_langs() -> list:
    """이 기계에서 쓸 수 있는 Tesseract 언어 목록(번들 tessdata 기준)."""
    try:
        info = ensure_tesseract()
        if not info.get("ok"):
            return []
        import pytesseract
        return sorted(pytesseract.get_languages(config=""))
    except Exception:
        return []


def default_lang() -> str:
    """기본 OCR 언어 — 설치된 것만 남긴 `kor+eng`(§14.8)."""
    return resolve_lang(DEFAULT_LANG)


def resolve_lang(lang: str) -> str:
    """요청한 언어 중 **설치된 것만** 남긴다. 하나도 없으면 `eng`.

    조용히 틀린 언어로 읽느니 줄여서라도 맞는 언어로 읽는다. 무엇이 빠졌는지는
    `missing_langs()` 로 알 수 있다(부르는 쪽이 사용자에게 알린다).
    """
    want = [x for x in str(lang or "").split("+") if x]
    if not want:
        want = DEFAULT_LANG.split("+")
    have = set(available_langs())
    if not have:
        return "+".join(want)          # 목록을 못 얻으면 요청대로 시도한다
    keep = [x for x in want if x in have]
    if keep:
        return "+".join(keep)
    return FALLBACK_LANG if FALLBACK_LANG in have else (sorted(have)[0] if have else FALLBACK_LANG)


def missing_langs(lang: str) -> list:
    """요청했지만 설치돼 있지 않은 언어(사용자 안내용)."""
    have = set(available_langs())
    if not have:
        return []
    return [x for x in str(lang or "").split("+") if x and x not in have]


def detect_lang(doc, pages: int = 5) -> str:
    """'자동' — 텍스트층으로 짐작하되, **글자가 적으면 믿지 않는다**(§14.8).

    종전 판정의 결함이 여기 있었다: 스캔본은 텍스트층이 비어 있어 어느 쪽으로도
    셀 수 없는데, 그때 조용히 영문으로 떨어졌다. 이제 기본값(한글+영문)으로 돌아간다.
    """
    try:
        n = min(int(pages), doc.page_count)
        sample = "".join(doc.load_page(i).get_text("text") for i in range(n))
    except Exception:
        return default_lang()
    if len(sample.strip()) < 30:
        return default_lang()
    han = len(_HANGUL_RE.findall(sample))
    lat = len(_WORD_RE.findall(sample))
    if han == 0 and lat > 0:
        return resolve_lang("eng")
    if han > 0 and lat == 0:
        return resolve_lang("kor")
    return default_lang()

def decide_source(page: "fitz.Page") -> tuple[str, dict]:
    """이 페이지를 'layer'(레이어 사용) 또는 'ocr'(재OCR) 중 무엇으로 처리할지 판정.

    핵심(§14.3-4): '텍스트 길이'가 아닌 품질로 판정하되, **전면 이미지(스캔)** 페이지는
    덧씌운 텍스트 레이어가 깨진 OCR 일 수 있으므로 재OCR 을 우선한다(HM.pdf 사례)."""
    text = page.get_text("text")
    n = len(text.strip())
    has_img = bool(page.get_images(full=True))
    hangul = len(_HANGUL_RE.findall(text))
    latin = len(_WORD_RE.findall(text))

    # 전면 이미지(스캔본) → 레이어가 있어도 재OCR (덧씌운 OCR 레이어 신뢰 불가)
    cov = _image_coverage(page) if has_img else 0.0
    if cov >= 0.6:
        return "ocr", {"reason": "scanned-page", "img_cov": round(cov, 2)}

    # 텍스트가 거의 없고 이미지가 있으면 명백한 스캔
    if n < 30 and has_img:
        return "ocr", {"reason": "image-only", "len": n}
    if n < 30:
        return "ocr", {"reason": "empty-text", "len": n}

    # 한글 위주: 유효 한글 음절이 충분하면 레이어 신뢰(깨진 OCR 한글은 드묾)
    if hangul >= latin and hangul > 20:
        return "layer", {"reason": "hangul-layer", "hangul": hangul}

    # 라틴 위주: 사전 적중률로 품질 판정 (HM.pdf 깨진 레이어 0.1~0.3 대 정상 0.7+)
    q = _latin_quality(text)
    if q >= 0.55:
        return "layer", {"reason": "latin-layer", "quality": round(q, 3)}
    return "ocr", {"reason": "broken-layer", "quality": round(q, 3)}


# --- 전처리 ---------------------------------------------------------------
def dehyphenate(text: str) -> str:
    """줄바꿈 하이픈 복원: 'com-\\nputer' -> 'computer'."""
    return re.sub(r"([A-Za-z가-힣])-\s*\n\s*([A-Za-z가-힣])",
                  r"\1\2", text)


def strip_repeated_lines(pages_text: list[str], threshold: float = 0.4) -> list[str]:
    """여러 페이지에 반복 등장하는 짧은 라인(머리말/꼬리말)을 제거.
    threshold 비율 이상 페이지에 나타나는 동일 라인을 제거."""
    if len(pages_text) < 3:
        return pages_text
    counter: Counter[str] = Counter()
    per_page_lines = []
    for t in pages_text:
        lines = {ln.strip() for ln in t.splitlines() if 0 < len(ln.strip()) <= 60}
        per_page_lines.append(lines)
        counter.update(lines)
    cut = max(2, int(len(pages_text) * threshold))
    repeated = {ln for ln, c in counter.items() if c >= cut}
    if not repeated:
        return pages_text
    out = []
    for t in pages_text:
        out.append("\n".join(ln for ln in t.splitlines()
                             if ln.strip() not in repeated))
    return out


# --- 렌더 + OCR -----------------------------------------------------------
# 260909(§14.9, 사용자 지시): 워터마크는 본문 **뒤에 연하게** 깔린다. 크기·위치로는
#   본문과 못 가르므로(전면을 가로지르는 큰 글씨가 많다) **밝기로** 가른다.
#   실측 근거: 스캔본 본문 글자는 거의 검정(<100), 워터마크는 옅은 회색(>180).
WM_KEEP_LUMA = 140          # 0~255. 이보다 밝은 픽셀은 흰색으로 지운다


def drop_watermark(img):
    """연한 픽셀을 흰색으로 — 워터마크를 지우고 본문만 남긴다(§14.9).

    한계: **연한 진짜 글자**(회색 캡션·도장)도 함께 사라질 수 있다. 그래서 옵션이다.
    """
    try:
        g = img.convert("L")
        # point() 로 한 번에 — 픽셀 반복문은 300dpi A4 에서 몇 초씩 걸린다
        bw = g.point(lambda v: 0 if v < WM_KEEP_LUMA else 255, mode="L")
        return bw.convert("RGB")
    except Exception:
        return img          # 못 지워도 OCR 자체는 돌아야 한다


def render_page(doc: "fitz.Document", page_index: int, dpi: int = 300,
                drop_watermark_bg: bool = False):
    """페이지를 dpi 로 렌더해 (PIL.Image, page_rect, 픽셀크기) 반환.

    `drop_watermark_bg=True` 면 연한 배경(워터마크)을 지우고 넘긴다(§14.9).
    """
    from PIL import Image
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if drop_watermark_bg:
        img = drop_watermark(img)
    return img, page.rect, (pix.width, pix.height)


def ocr_image(img, lang: str = "eng", psm: int = 6, dpi: int = 300) -> dict:
    """이미지 OCR → {text, conf, words:[{surface,x0,y0,x1,y1,conf}]} (픽셀 좌표).

    260908-8(텍스트 창 SOT §3.5 · 이 문서 §14.3): **글자로 볼 수 없는 낱말은 버린다.**
    OCR 은 종이의 티·괘선을 `픔`·`■` 같은 글자로 읽는다. 그것을 그대로 두면
    본문·단어장·검색 색인이 모두 오염된다. 판정은 `viewer.text_noise` 가 소유한다.
    """
    info = ensure_tesseract()
    if not info.get("ok"):
        raise RuntimeError(f"Tesseract 사용 불가: {info.get('error')}")
    import pytesseract
    cfg = f"--psm {psm}"
    data = pytesseract.image_to_data(img, lang=lang, config=cfg,
                                     output_type=pytesseract.Output.DICT)
    words = []
    confs = []
    parts = []
    prev_line = None        # (block,par,line) — 줄이 바뀌면 개행 삽입(머리말/꼬리말·하이픈 처리용)
    has_lineinfo = all(k in data for k in ("block_num", "par_num", "line_num"))
    for i, txt in enumerate(data["text"]):
        s = txt.strip()
        if not s:
            continue
        c = data["conf"][i]
        try:
            c = float(c)
        except (TypeError, ValueError):
            c = -1.0
        if c < 0:
            continue
        x, y, w, h = (data["left"][i], data["top"][i],
                      data["width"][i], data["height"][i])
        if not _noise.keep_ocr_word(s, x, y, x + w, y + h, c / 100.0,
                                    scale=72.0 / max(1, int(dpi))):
            continue                    # 260908-8: 잡음은 본문에서도 뺀다
        words.append({"surface": s, "x0": float(x), "y0": float(y),
                      "x1": float(x + w), "y1": float(y + h), "conf": c / 100.0})
        confs.append(c / 100.0)
        if has_lineinfo:
            line = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            if prev_line is not None and line != prev_line:
                parts.append("\n")
            prev_line = line
        parts.append(s)
    # parts 를 줄 구조로 합침('\n' 토큰은 개행, 나머지는 공백)
    text = ""
    for p in parts:
        if p == "\n":
            text += "\n"
        else:
            text += ("" if (not text or text.endswith("\n")) else " ") + p
    avg = sum(confs) / len(confs) if confs else 0.0
    return {"text": text, "conf": avg, "words": words}


def words_from_layer(page: "fitz.Page") -> dict:
    """디지털 레이어에서 단어+좌표 추출 (point 좌표). OCR 대체.

    260908-8: 이 경로도 **스캔본을 탄다** — 그림 위에 보이지 않게 얹힌 OCR 글자층은
    `decide_source` 가 'layer' 로 판정하기 때문이다. 그런 쪽에서는 텍스트 창과 **같은
    규칙**으로 잡음 낱말을 뺀다(텍스트 창 SOT §3.5). 사람이 넣은 글자층은 건드리지 않는다.
    """
    raw = page.get_text("words")   # [x0,y0,x1,y1, word, block,line,wordno]
    words = [{"surface": w[4], "x0": float(w[0]), "y0": float(w[1]),
              "x1": float(w[2]), "y1": float(w[3]), "conf": 1.0}
             for w in raw if w[4].strip()]
    text = page.get_text("text")
    try:
        from viewer.text_extract2 import _is_ocr_layer
        invisible = _is_ocr_layer(page)
    except Exception:
        invisible = False
    if invisible:
        words = [w for w in words
                 if _noise.keep_ocr_word(w["surface"], w["x0"], w["y0"],
                                         w["x1"], w["y1"], w["conf"])]
    return {"text": text, "conf": 1.0, "words": words}


def build_page(doc: "fitz.Document", page_index: int, *,
               lang: str = "eng", dpi: int = 300,
               force_ocr: bool = False,
               drop_watermark_bg: bool = False) -> dict:
    """한 페이지를 처리해 {source, text, conf, words, dpi, engine} 반환.
    source='layer' 면 텍스트 레이어 사용, 'ocr' 면 Tesseract."""
    page = doc.load_page(page_index)
    src, why = ("ocr", {"reason": "forced"}) if force_ocr else decide_source(page)
    if src == "layer":
        res = words_from_layer(page)
        res.update(source="layer", dpi=0, engine="pymupdf", why=why)
        return res
    img, _, _ = render_page(doc, page_index, dpi=dpi,
                            drop_watermark_bg=drop_watermark_bg)
    res = ocr_image(img, lang=resolve_lang(lang), dpi=dpi)
    res.update(source="ocr", dpi=dpi, engine="tesseract", why=why)
    return res
