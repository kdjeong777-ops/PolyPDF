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
            # tessdata: env/share/tessdata (conda 구조) 또는 형제 tessdata
            for td in (d.parent.parent / "share" / "tessdata", d / "tessdata"):
                if td.exists():
                    os.environ["TESSDATA_PREFIX"] = str(td)
                    break
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
def render_page(doc: "fitz.Document", page_index: int, dpi: int = 300):
    """페이지를 dpi 로 렌더해 (PIL.Image, page_rect) 반환."""
    from PIL import Image
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return img, page.rect, (pix.width, pix.height)


def ocr_image(img, lang: str = "eng", psm: int = 6) -> dict:
    """이미지 OCR → {text, conf, words:[{surface,x0,y0,x1,y1,conf}]} (픽셀 좌표)."""
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
    """디지털 레이어에서 단어+좌표 추출 (point 좌표). OCR 대체."""
    raw = page.get_text("words")   # [x0,y0,x1,y1, word, block,line,wordno]
    words = [{"surface": w[4], "x0": float(w[0]), "y0": float(w[1]),
              "x1": float(w[2]), "y1": float(w[3]), "conf": 1.0}
             for w in raw if w[4].strip()]
    return {"text": page.get_text("text"), "conf": 1.0, "words": words}


def build_page(doc: "fitz.Document", page_index: int, *,
               lang: str = "eng", dpi: int = 300,
               force_ocr: bool = False) -> dict:
    """한 페이지를 처리해 {source, text, conf, words, dpi, engine} 반환.
    source='layer' 면 텍스트 레이어 사용, 'ocr' 면 Tesseract."""
    page = doc.load_page(page_index)
    src, why = ("ocr", {"reason": "forced"}) if force_ocr else decide_source(page)
    if src == "layer":
        res = words_from_layer(page)
        res.update(source="layer", dpi=0, engine="pymupdf", why=why)
        return res
    img, _, _ = render_page(doc, page_index, dpi=dpi)
    res = ocr_image(img, lang=lang)
    res.update(source="ocr", dpi=dpi, engine="tesseract", why=why)
    return res
