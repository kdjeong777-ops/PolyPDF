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
            # 260910-6(§14.17): 동봉 두 배치 + **사용자 폴더**를 함께 놓고 고른다.
            #   차례가 곧 우선순위 — 가진 언어 수가 같으면 앞엣것(동봉본)이 이긴다.
            best = _pick_tessdata([d.parent.parent / "share" / "tessdata",
                                   d / "tessdata",
                                   user_tessdata_dir()])
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
# 260909-2(§14.11): 쪽 나누기 방식(psm). P0 스파이크는 소설 본문 한 쪽으로 재어
#   `--psm 6`(균일한 한 덩어리)을 골랐는데, 그 값은 **여러 구역이 섞인 쪽**에서
#   그림 속 글을 통째로 놓친다(실측: 붙여 넣은 표 그림을 psm 6 은 못 읽고 4 는 읽는다).
#   `--psm 4`(크기가 제각각인 한 단)가 실제 문서 3종에서 고루 가장 많이 읽었다.
DEFAULT_PSM = 4

DEFAULT_LANG = "kor+eng"
FALLBACK_LANG = "eng"


def user_tessdata_dir() -> Path:
    """쓰기 권한이 있는 tessdata 폴더 (§14.17).

    동봉 폴더는 보통 `C:@Program Files@PolyPDF@_internal@...` 이라 관리자 권한 없이는
    한 글자도 못 쓴다. 언어 자료를 그 자리에서 받아 고치려면 사용자 폴더가 필요하다.
    """.replace("@", chr(92))
    # 시험·지원용 우회로. 실제 실행에서는 쓰지 않는다.
    over = os.environ.get("POLYPDF_TESSDATA_DIR")
    if over:
        return Path(over)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "PolyPDF" / "tessdata"


def _langs_in(d) -> set:
    try:
        return {q.stem for q in Path(d).glob("*.traineddata")}
    except Exception:
        return set()


def _pick_tessdata(cands) -> "Optional[Path]":
    """후보 중 **필요한 언어를 더 많이 가진** 폴더 (§14.17).

    260908-1 은 '`kor` 이 든 쪽' 이라는 단발 규칙이었다. 사용자 폴더가 후보로 늘면서
    일반화한다 — 같으면 동봉본(변하지 않는 쪽)을 쓴다. 그래서 후보 차례가 곧 우선순위다.
    """
    need = {x for x in DEFAULT_LANG.split("+") if x}
    best, best_score = None, -1
    for d in cands:
        if not d or not Path(d).exists():
            continue
        score = len(need & _langs_in(d))
        if score > best_score:
            best, best_score = Path(d), score
    return best


def available_langs() -> list:
    """이 기계에서 쓸 수 있는 Tesseract 언어 목록(번들 tessdata 기준).

    260910-3(§14.16): 근거를 **둘 다** 본다 — `--list-langs` 와 tessdata 폴더의
    실제 `*.traineddata` 파일. 종전에는 `missing_langs()` 가 앞엣것만,
    `missing_language()` 가 뒤엣것만 봐서 **같은 물음에 다른 답**이 나올 수 있었다.
    둘을 합치면 한쪽이 빠뜨려도 한국어가 사라지지 않는다. 보는 폴더는
    `ensure_tesseract()` 가 고른 그 폴더라 tesseract 가 실제로 읽을 곳과 같다.
    """
    try:
        info = ensure_tesseract()
        if not info.get("ok"):
            return []
    except Exception:
        return []
    have = set()
    try:
        import pytesseract
        have.update(pytesseract.get_languages(config=""))
    except Exception:
        pass
    try:
        td = info.get("tessdata") or ""
        if td:
            have.update(q.stem for q in Path(td).glob("*.traineddata"))
    except Exception:
        pass
    return sorted(have)


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


TESSDATA_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/%s.traineddata"


def repair_langs(codes, progress=None) -> tuple:
    """모자란 언어 자료를 **받아서** 쓸 수 있게 만든다 (§14.17). 반환 (ok, 사람이 읽을 말).

    왜 사용자 폴더인가 — 동봉 폴더는 `Program Files` 안이라 관리자 권한 없이 못 쓴다.
    왜 복사부터 하나 — Tesseract 는 tessdata 폴더를 **하나만** 본다. 받은 언어만 두면
    이번에는 동봉돼 있던 `eng` 를 잃는다. 그래서 있는 것을 먼저 옮겨 놓고 모자란 것만 받는다.

    `progress(done, total)` 이 False 를 돌려주면 그만둔다(취소).
    """
    import shutil
    from viewer.components import _download

    want = [x for x in (codes or []) if x]
    if not want:
        return True, "받을 것이 없습니다."
    dst = user_tessdata_dir()
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, "폴더를 만들 수 없습니다: %s" % e

    # ① 지금 쓰고 있는 폴더의 자료를 먼저 옮겨 둔다(없는 것만).
    cur = os.environ.get("TESSDATA_PREFIX") or ""
    if cur and Path(cur) != dst:
        for q in _langs_in(cur):
            t = dst / ("%s.traineddata" % q)
            if not t.exists():
                try:
                    shutil.copy2(Path(cur) / ("%s.traineddata" % q), t)
                except Exception:
                    pass

    # ② 모자란 것만 받는다. 받다 만 파일이 남지 않게 `.part` 로 받고 바꿔 끼운다.
    got, failed = [], []
    for code in want:
        if (dst / ("%s.traineddata" % code)).exists():
            continue
        data = _download(TESSDATA_URL % code, progress)
        if not data:
            failed.append(code)
            continue
        tmp = dst / ("%s.traineddata.part" % code)
        try:
            tmp.write_bytes(data)
            os.replace(tmp, dst / ("%s.traineddata" % code))
            got.append(code)
        except Exception:
            failed.append(code)
            try:
                tmp.unlink()
            except Exception:
                pass

    reset_cache()               # 다음 부름부터 새 폴더를 다시 고른다
    ensure_tesseract()
    if failed:
        return False, ("받지 못한 언어: %s. 인터넷 연결을 확인하거나 설치 프로그램으로 "
                       "다시 설치하세요." % ", ".join(failed))
    return True, ("언어 자료를 준비했습니다: %s%s위치: %s"
                  % (", ".join(got) if got else "(이미 있음)", chr(10) * 2, dst))


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


def _join_words_by_gap(parts) -> str:
    """낱말 상자를 **간격으로** 이어 한 줄 글로 (텍스트 창 SOT §3.6.2).

    `parts` 는 낱말 dict 와 개행 표시가 섞인 목록이다. 잇는 규칙은 텍스트 창의
    §3.6 과 **같은 것**을 쓴다 — 규칙이 갈라지면 화면과 검색이 서로 달라진다.
    """
    NL = chr(10)
    try:
        from viewer.text_extract2 import (GLUE_GAP, CJK_GLUE_GAP, NUM_GLUE_GAP,
                                          _is_cjk_pair, _is_num_pair,
                                          fix_number_spaces, fix_number_ocr)
    except Exception:              # 모듈을 못 불러오면 종전대로 공백
        out = ''
        for q in parts:
            t = q if isinstance(q, str) else q.get('surface', '')
            out += t if t == NL else (
                ('' if (not out or out.endswith(NL)) else ' ') + t)
        return out
    text = ''
    prev = None
    for q in parts:
        if isinstance(q, str):     # 개행
            text += q
            prev = None
            continue
        t = str(q.get('surface', ''))
        if not t:
            continue
        if prev is None or not text or text.endswith(NL):
            text += t
        else:
            ref = max(1.0, float(q['y1']) - float(q['y0']))
            gap = float(q['x0']) - float(prev['x1'])
            if _is_cjk_pair(text, t):
                glue = CJK_GLUE_GAP
            elif _is_num_pair(text, t):
                glue = NUM_GLUE_GAP
            else:
                glue = GLUE_GAP
            text += ('' if gap < glue * ref else ' ') + t
        prev = q
    # 260909-3/4: 줄마다 수를 바로잡는다 — 닮은 글자(O→0) 되돌리기(§3.6.3) 뒤에
    #   빈칸 없애기(§3.6.2). 순서가 중요하다: `1 OO.O` 는 글자를 먼저 고쳐야 붙는다.
    return chr(10).join(fix_number_spaces(fix_number_ocr(x))
                        for x in text.split(chr(10)))

def ocr_image(img, lang: str = "eng", psm: int = 0, dpi: int = 300) -> dict:
    """이미지 OCR → {text, conf, words:[{surface,x0,y0,x1,y1,conf}]} (픽셀 좌표).

    260908-8(텍스트 창 SOT §3.5 · 이 문서 §14.3): **글자로 볼 수 없는 낱말은 버린다.**
    OCR 은 종이의 티·괘선을 `픔`·`■` 같은 글자로 읽는다. 그것을 그대로 두면
    본문·단어장·검색 색인이 모두 오염된다. 판정은 `viewer.text_noise` 가 소유한다.
    """
    info = ensure_tesseract()
    if not info.get("ok"):
        raise RuntimeError(f"Tesseract 사용 불가: {info.get('error')}")
    import pytesseract
    cfg = f"--psm {int(psm) or DEFAULT_PSM}"
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
        parts.append(words[-1])
    # 260909-2(텍스트 창 SOT §3.6.2): 본문도 **글자 사이 간격**으로 잇는다.
    #   종전에는 낱말을 공백으로만 이어, 한글이 `재 생 점 가 제` 로 흩어졌다 —
    #   Tesseract 가 한글을 글자 하나하나 낱말로 내놓기 때문이다. 화면만 고치면
    #   검색·단어장에는 흩어진 채로 남는다.
    text = _join_words_by_gap(parts)
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
