"""OCR 엔진 — 스캔 감지·300DPI 렌더·Tesseract OCR(단어좌표)·텍스트 전처리.

P0 검증 반영(단어학습 SOT §14):
  - 엔진: Tesseract(주). eng+kor. 단어좌표는 image_to_data TSV.
  - 스캔 감지: 텍스트 '길이'가 아닌 '품질(사전단어/한글 유효 비율)' 로 판정.
    깨끗한 디지털 레이어가 있으면 OCR 생략하고 레이어 사용(한글 기술문서 등).
  - 전처리: 줄바꿈 하이픈 복원 + 반복 머리말/꼬리말 제거.
Tesseract 미설치/로드 실패 시 OCR 함수는 RuntimeError — 호출자(워커)가 처리.
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import Optional

import fitz

from viewer import text_noise as _noise
from viewer.i18n import tr

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
        repo = Path(__file__).resolve().parents[3]   # .../PolyPDF
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
        _TESS_INFO = {"ok": False, "error": tr('pytesseract 미설치: {e}').format(e=e)}
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
        _TESS_INFO = {"ok": False, "error": tr('tesseract 실행 불가: {e}').format(e=e)}
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
    names = {"kor": tr("한국어"), "eng": tr("영어"), "jpn": tr("일본어"), "chi_sim": tr("중국어(간체)")}
    label = " · ".join(names.get(c, c) for c in gone)
    return (tr('{label} OCR 학습 데이터가 없습니다({join}).\n\n찾은 위치: {td}\n\n도구 → 구성요소 설치에서 OCR(Tesseract)을 다시 받으면 채워집니다. 설치본이 오래된 경우 프로그램을 최신 버전으로 올리면 함께 들어옵니다.').format(label=label, join=', '.join((c + '.traineddata' for c in gone)), td=td or tr('(미설정)')))


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
        from viewer.study.wordfreq_fast import zipf_frequency   # 261009-14: 설치본 import 1.9초 회피
        hit = sum(1 for t in sample if zipf_frequency(t, "en") >= 2.0)
        return hit / len(sample)
    except Exception:
        # 폴백: 모음 포함 + 길이 3~15 토큰 비율
        ok = sum(1 for t in sample if 3 <= len(t) <= 15 and re.search(r"[aeiou]", t))
        return ok / len(sample)


def _image_coverage(page: "fitz.Page") -> float:
    """페이지 면적 대비 이미지가 덮는 비율(0~1). 전면 스캔 감지용.

    261009-14(응답성 SOT §12): `get_image_rects()` 는 그림 위치를 찾느라 **쪽의 모든 그림 MD5** 를 계산한다 —
    텍스트 창이 쪽마다 메인 스레드에서 부르는 길이라 스캔·큰 그림 쪽에서 1.9~2.8초 섰다(설치본 실측).
    위치만 필요하므로 해시 없는 `get_image_info(hashes=False)` 의 bbox 를 쓴다(표본 4종 11쪽에서 값 동일, 100배 이상 빠름)."""
    try:
        pr = page.rect
        px0, py0, px1, py1 = float(pr.x0), float(pr.y0), float(pr.x1), float(pr.y1)
        total = float((px1 - px0) * (py1 - py0)) or 1.0
        area = 0.0
        # 261114-11(§14.18): `fitz.Rect` 를 만들지 않고 숫자로 — 질감 배경을 작은 그림 23,296개로 깐 쪽에서 `Rect` 만 2.4초(TRB9.pdf)
        for info in page.get_image_info(hashes=False, xrefs=False):
            a, b, c, d = info["bbox"]
            w = min(max(a, c), px1) - max(min(a, c), px0)
            h = min(max(b, d), py1) - max(min(b, d), py0)
            if w > 0 and h > 0:
                area += w * h
                if area >= total:
                    break
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
PHOTO_MAX_SIDE = 4000       # 사진 OCR 긴 변 상한(px) — 단어학습 SOT §14.B·§14.22
FALLBACK_LANG = "eng"


def user_tessdata_dir() -> Path:
    r"""쓰기 권한이 있는 tessdata 폴더 (§14.17).

    동봉 폴더는 보통 `C:\Program Files\PolyPDF\_internal\...` 이라 관리자 권한 없이는
    한 글자도 못 쓴다. 언어 자료를 그 자리에서 받아 고치려면 사용자 폴더가 필요하다.
    """
    # 시험·지원용 우회로. 실제 실행에서는 쓰지 않는다.
    over = os.environ.get("POLYPDF_TESSDATA_DIR")
    if over:
        return Path(over)
    from viewer.settings_store import local_data_dir   # 261009-22: 휴대용이면 데이터 폴더 안(마스터 §14.9)
    return local_data_dir() / "tessdata"


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
    # 261108-18(§14.24): `--list-langs` 는 `ensure_tesseract` 가 한 번 읽어 둔 것을 쓴다 — 종전에는 `resolve_lang` 마다
    #   tesseract 를 한 번 더 띄워(쪽마다 2~3번) 백신 검사·시간이 들었다. 언어 자료를 받으면 `reset_cache` 가 다시 읽게 한다
    have.update(info.get("langs") or [])
    if not have:
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
        return True, tr("받을 것이 없습니다.")
    dst = user_tessdata_dir()
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, tr("폴더를 만들 수 없습니다: %s") % e

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
        return False, (tr("받지 못한 언어: %s. 인터넷 연결을 확인하거나 설치 프로그램으로 "
                       "다시 설치하세요.") % ", ".join(failed))
    return True, (tr("언어 자료를 준비했습니다: %s%s위치: %s")
                  % (", ".join(got) if got else tr("(이미 있음)"), chr(10) * 2, dst))


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

def _overlaid_ocr_layer(page) -> bool:
    """이 쪽의 글자층이 **스캐너가 덧씌운 보이지 않는 OCR 층**인가 (§14.18).

    판정 본문은 텍스트 창 SOT §3.5 가 소유한다(`text_extract2._is_ocr_layer`) —
    여기서 다시 만들지 않는다. 못 부르면 **덧씌운 층이 아니라고** 본다:
    멀쩡한 글자층을 버리는 쪽이 더 나쁘다.
    """
    try:
        from viewer.text_extract2 import _is_ocr_layer
    except Exception:
        return False
    if _no_invisible_text(page):
        return False                       # 261114-11(§14.18): 내용 흐름에 `3 Tr` 가 없다 — 쪽을 돌려 볼 것도 없다
    try:
        return bool(_is_ocr_layer(page))
    except Exception:
        return False


_TR3_RE = re.compile(rb"(?<![0-9.])3\s+Tr\b")


def _no_invisible_text(page) -> bool:
    """render mode 3(안 보임) 글자가 **있을 수 없는** 쪽인가 — 내용 흐름에 `3 Tr` 가 없고 폼 XObject 도 없다(폼 안은 보지 않으므로 그때는 모른다).
    261114-11: 작은 그림 수만 개로 깐 쪽은 `get_texttrace` 한 번이 0.26~0.67초(TRB9.pdf) — 바이트 찾기는 0.1초 안. 모르면 False(종전대로 돌려 본다)."""
    try:
        if page.get_xobjects():
            return False
        return _TR3_RE.search(page.read_contents() or b"") is None
    except Exception:
        return False


def decide_source(page: "fitz.Page") -> tuple[str, dict]:
    """이 페이지를 'layer'(레이어 사용) 또는 'ocr'(재OCR) 중 무엇으로 처리할지 판정.

    핵심(§14.3-4): '텍스트 길이'가 아닌 품질로 판정하되, **전면 이미지(스캔)** 페이지는
    덧씌운 텍스트 레이어가 깨진 OCR 일 수 있으므로 재OCR 을 우선한다(HM.pdf 사례).
    261114-11(§14.18): (파일·수정 시각·쪽)마다 **프로세스에 하나** 기억한다 — 본문·텍스트 창·문서 정보 줄(배경)이 같은 쪽을
    저마다 연 문서로 묻는다. 다른 스레드가 그 쪽을 판정하는 중이면 다시 하지 않고 기다린다(둘이 GIL 을 다투면 두 배로 선다)."""
    key = _src_key(page)
    if key is None:
        return _decide_source(page)
    with _SRC_LOCK:
        got = _SRC_MEMO.get(key)
        ev = None if got is not None else _SRC_BUSY.get(key)
        mine = got is None and ev is None
        if mine:
            ev = _SRC_BUSY[key] = threading.Event()
    if got is not None:
        return got[0], dict(got[1])
    if not mine:
        ev.wait(SRC_WAIT_S)
        with _SRC_LOCK:
            got = _SRC_MEMO.get(key)
        if got is not None:
            return got[0], dict(got[1])
        return _decide_source(page)
    try:
        src, why = _decide_source(page)
        with _SRC_LOCK:
            if len(_SRC_MEMO) >= SRC_MEMO_MAX:
                _SRC_MEMO.clear()
            _SRC_MEMO[key] = (src, dict(why))
        return src, why
    finally:
        with _SRC_LOCK:
            _SRC_BUSY.pop(key, None)
        ev.set()


import threading
_SRC_LOCK = threading.Lock()
_SRC_MEMO: dict = {}        # (파일, 수정 시각 ns, 쪽) -> (판정, 근거)
_SRC_BUSY: dict = {}        # 판정 중인 열쇠 -> Event
SRC_MEMO_MAX = 4096         # 넘으면 비운다(쪽 하나에 몇십 바이트)
SRC_WAIT_S = 5.0            # 다른 스레드의 판정을 기다리는 상한 — 넘으면 스스로 한다


def _src_key(page):
    """(파일 경로, 수정 시각 ns, 쪽) — 메모리 문서·읽지 못하면 None(기억하지 않는다). 수정 시각은 문서 객체마다 한 번만 묻는다."""
    try:
        doc = page.parent
        name = str(doc.name or "")
        if not name:
            return None
        mt = doc.__dict__.get("_polypdf_mt")
        if mt is None:
            mt = doc.__dict__["_polypdf_mt"] = os.stat(name).st_mtime_ns
        return (os.path.normcase(os.path.abspath(name)), mt, int(page.number))
    except Exception:
        return None


def _decide_source(page: "fitz.Page") -> tuple[str, dict]:
    text = page.get_text("text")
    n = len(text.strip())
    has_img = bool(page.get_images(full=True))
    hangul = len(_HANGUL_RE.findall(text))
    latin = len(_WORD_RE.findall(text))

    # 전면 이미지(스캔본) → 레이어가 있어도 재OCR (덧씌운 OCR 레이어 신뢰 불가)
    # 260912-2(§14.18, 사용자 보고): 다만 **보이지 않는 글자층일 때만** 그렇다.
    #   스캐너가 얹은 OCR 층은 render mode 3(안 보임)이지만, 배경 그림 위에 진짜
    #   글을 **그려 넣은** 문서(구글 번역본·전면 배경을 깐 보고서)는 보이는 글자층이고
    #   그 글이 원본 그대로다. 종전에는 점유율만 보고 그 멀쩡한 층을 버리고 OCR 해
    #   `조 지 아 교 통 부` 처럼 글자마다 끊기고 본문이 제목으로 뒤집혔다(사용자 보고).
    #   실측(표본 4종 각 4쪽): 진짜 스캔 3종 = 안 보이는 층 100%, 구글 번역본 = 0%.
    # 261114-11(§14.18): 안 보이는 층인지 먼저(글자 한 번) — 점유율(그림 자리 읽기)은 그때만. 두 조건 모두라 판정은 같다.
    if has_img and _overlaid_ocr_layer(page):
        cov = _image_coverage(page)
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
        from viewer.text_extract2 import (CJK_GLUE_GAP, NUM_GLUE_GAP,
                                          CJK_GLUE_TOP, CJK_GLUE_MIN,
                                          CJK_GLUE_MAX, CJK_GLUE_MIN_N,
                                          _is_cjk_pair, _is_num_pair,
                                          fix_number_spaces, fix_number_ocr)
    except Exception:              # 모듈을 못 불러오면 종전대로 공백
        out = ''
        for q in parts:
            t = q if isinstance(q, str) else q.get('surface', '')
            out += t if t == NL else (
                ('' if (not out or out.endswith(NL)) else ' ') + t)
        return out
    # 260916-1(텍스트 창 SOT §3.6.12): 한글 문턱은 **이 쪽의 빈틈 분포**에서 뽑고,
    #   재는 자는 **그 줄 상자 높이의 중앙값**으로 한다. 텍스트 창과 같은 규칙이라야
    #   화면과 검색·단어장이 같은 글을 본다(§3.6.2 가 요구하는 것).
    lines = []                       # [[낱말…], …] — 개행으로 끊는다
    cur = []
    for q in parts:
        if isinstance(q, str):
            lines.append(cur)
            cur = []
        elif str(q.get('surface', '')):
            cur.append(q)
    lines.append(cur)
    refs = []
    for ws in lines:
        hs = sorted(max(1.0, float(w['y1']) - float(w['y0'])) for w in ws)
        refs.append(max(1.0, hs[len(hs) // 2]) if hs else 1.0)
    vals = []
    for ws, ref in zip(lines, refs):
        for a, b in zip(ws, ws[1:]):
            if not _is_cjk_pair(str(a['surface']), str(b['surface'])):
                continue
            r = (float(b['x0']) - float(a['x1'])) / ref
            if -0.5 <= r <= CJK_GLUE_TOP:
                vals.append(r)
    cjk_gap = CJK_GLUE_GAP
    if len(vals) >= CJK_GLUE_MIN_N:
        best, t = -1.0, CJK_GLUE_MIN - 0.10
        while t <= CJK_GLUE_MAX + 0.10 + 1e-9:
            lo = [v for v in vals if v < t]
            hi = [v for v in vals if v >= t]
            if len(lo) >= 5 and len(hi) >= 5:
                wl, wh = len(lo) / len(vals), len(hi) / len(vals)
                var = wl * wh * (sum(lo)/len(lo) - sum(hi)/len(hi)) ** 2
                if var > best:
                    best, cjk_gap = var, t
            t += 0.01
        cjk_gap = min(CJK_GLUE_MAX, max(CJK_GLUE_MIN, cjk_gap))

    chunks = []
    for ws, row_ref in zip(lines, refs):
        text = ''
        prev = None
        for q in ws:
            t = str(q['surface'])
            if prev is None:
                text += t
            else:
                ref = max(1.0, float(q['y1']) - float(q['y0']))
                gap = float(q['x0']) - float(prev['x1'])
                if _is_cjk_pair(text, t):
                    glue, ref = cjk_gap, row_ref
                elif _is_num_pair(text, t):
                    glue = NUM_GLUE_GAP
                else:
                    # 261101-1(텍스트 창 SOT §3.6.13): 라틴 낱말은 Tesseract 가 이미 갈랐다 — 언제나 빈칸
                    glue = None
                text += ('' if glue is not None and gap < glue * ref else ' ') + t
            prev = q
        chunks.append(text)
    # 261101-1(텍스트 창 SOT §3.6.15): 홀로 선 한글 한 음절은 줄 목록과 같은 규칙으로 — 검색·단어장 글도 같게
    try:
        from viewer.text_extract2 import fix_ko_spacing
        chunks = [re.sub(r"^([•■])(?=\S)", r"\1 ", fix_ko_spacing(c)) for c in chunks]   # 목록 기호 뒤 빈칸(§3.5.4)
    except Exception:
        pass
    text = NL.join(chunks)
    # 260909-3/4: 줄마다 수를 바로잡는다 — 닮은 글자(O→0) 되돌리기(§3.6.3) 뒤에
    #   빈칸 없애기(§3.6.2). 순서가 중요하다: `1 OO.O` 는 글자를 먼저 고쳐야 붙는다.
    return chr(10).join(fix_number_spaces(fix_number_ocr(x))
                        for x in text.split(chr(10)))

# 261101-1(§14.8.2): 한글 줄의 잡글 낱말을 잘라 다시 읽는다 — 쪽마다 이만큼까지(한 자리 약 0.12초, 표본 쪽당 10곳 남짓)
REREAD_MAX = 60
REREAD_RETRY = 12         # 쌓아 읽기에서 문턱을 못 넘은 자리를 따로 다시 읽는 최대 수(쪽마다)
REREAD_PAD = 6            # 자를 때 상자 둘레에 더하는 픽셀(300dpi)
REREAD_KOR_CONF = 80       # `kor` 로 다시 읽은 결과를 받는 평균 신뢰도
REREAD_ENG_CONF = 30       # 괄호 속 영문을 `eng` 로 다시 읽은 결과를 받는 평균 신뢰도(작은 세리프라 낮게 나온다)
REREAD_ONE_MAX = 10        # 번호·섞인 낱말·갈린 영문을 한 자리씩 다시 읽는 최대 수(쪽마다, §14.8.3)
_SECTION_NO = re.compile(r"\d{2,3}\.\d{1,2}|\d\.\d{2,3}|\d{2}")     # 점이 빠졌을 법한 줄 첫머리 번호(§14.8.3)
_JAMO_JUNK = re.compile(r"[ㄱ-ㅎㅏ-ㅠ\\]")                           # 낱자모(줄 같은 ㅡ·ㅣ 빼고)·`\` — 굵은 영문이 갈린 흔적
_LATIN_HEAD = re.compile(r"[A-Z]{2,}[A-Za-z\]}\[|0-9]+")            # `COES]`·`CBRAAYS` — 영문 머리 + 한글 토막이 잡글로
_LATIN_JUNK = re.compile(r"(?:[A-Z]{2,5}|[A-Za-z]{1,4}[\]}]|[A-Za-z]{1,2}[\]}][A-Za-z]{1,2}[\]}])[,.]?")


def _reread_kind(s: str, lang: str) -> str:
    """한글 줄의 이 낱말을 다시 읽을까 — `kor`(한글을 영문 잡글로) / `eng`(괄호 속 영문을 숫자 잡글로)
    / `mix`(영문 머리 + 한글 토막이 잡글로, §14.8.3) / ''."""
    if not s:
        return ""
    if _LATIN_HEAD.fullmatch(s) and (re.search(r"[\]}\[|0-9]", s) or len(s) >= 5):
        return "mix"
    if _LATIN_JUNK.fullmatch(s):
        core = re.sub(r"[^A-Za-z]", "", s)
        try:
            from viewer.study.wordfreq_fast import zipf_frequency
            if len(core) >= 4 and not core.isupper() and zipf_frequency(core.lower(), "en") >= 4.5:
                return ""               # 흔한 영어 낱말이다
        except Exception:
            pass
        return "kor"
    if "eng" in str(lang).split("+") and (("(" in s or ")" in s) and (sum(ch.isdigit() for ch in s) >= 3
                                                                       or not re.search(r"[A-Za-z]{3,}", s))
                                          or re.fullmatch(r"\d{5,}[)\],.]*", s)):
        return "eng"
    return ""


_STACK_GAP = 24             # 쌓아 읽기의 자리 사이 빈칸(px)
_TLS = threading.local()


def _stack_sheet(img, boxes):
    """잘라낸 자리들을 한 장에 세로로 쌓은 그림과 자리마다의 세로 구간."""
    from PIL import Image
    crops = [img.crop(b) for b in boxes]
    gap = _STACK_GAP
    W = max(c.size[0] for c in crops) + 2 * gap
    H = sum(c.size[1] + gap for c in crops) + gap
    sheet = Image.new(img.mode, (W, H), "white")
    spans, y = [], gap
    for c in crops:
        sheet.paste(c, (gap, y))
        spans.append((y, y + c.size[1]))
        y += c.size[1] + gap
    return sheet, spans


class _Reads:
    """한 쪽 그림의 자른 자리 판독을 모아 **tesseract 한 번에** 읽고 기억한다 (§14.24, 261108-18).

    요청 `(종류, 언어, 설정, 자리)` — 종류 `data`(낱말 TSV)·`boxes`(글자 상자), 자리는 `(x0, y0, x1, y1)` 또는
    `("sheet", 자리들)`(쌓아 읽기 한 장). 같은 (종류·언어·설정) 끼리 한 번에 읽는다 — 그림마다 따로 읽으므로 한 장씩 읽은 것과 같다."""

    def __init__(self, img):
        self.img = img
        self.memo = {}

    def _image(self, box):
        if box and box[0] == "sheet":
            return _stack_sheet(self.img, list(box[1]))[0]
        return self.img.crop(box)

    def prefetch(self, reqs) -> None:
        from viewer.study import tess_run
        groups = {}
        for kind, lang, cfg, box in reqs:
            if (kind, lang, cfg, box) in self.memo:
                continue
            bxs = groups.setdefault((kind, lang, cfg), [])
            if box not in bxs:
                bxs.append(box)
        for (kind, lang, cfg), bxs in groups.items():
            fn = tess_run.data if kind == "data" else tess_run.boxes
            for b, r in zip(bxs, fn([self._image(b) for b in bxs], lang, cfg)):
                self.memo[(kind, lang, cfg, b)] = r

    def get(self, kind, lang, cfg, box):
        key = (kind, lang, cfg, box)
        if key not in self.memo:
            self.prefetch([key])
        return self.memo[key]


def _reads_for(img, rd=None):
    """부르는 쪽이 넘긴 묶음 → 이 스레드에서 그 그림에 열어 둔 묶음(`batch_reads`) → 없으면 새 것(=종전처럼 한 장씩)."""
    if rd is not None and rd.img is img:
        return rd
    cur = getattr(_TLS, "reads", None)
    if cur is not None and cur.img is img:
        return cur
    return _Reads(img)


@contextlib.contextmanager
def batch_reads(img):
    """이 블록 안에서 그 그림의 `read_line_words` 등이 판독을 기억·묶어 쓴다(목차 쪽 다시 읽기, §14.24)."""
    prev = getattr(_TLS, "reads", None)
    _TLS.reads = _Reads(img)
    try:
        yield _TLS.reads
    finally:
        _TLS.reads = prev


def _key_box(b) -> tuple:
    return tuple(int(v) for v in b)


def _stack_reqs(boxes, lang) -> list:
    """`_read_stack` 이 읽을 것 — 미리 모아 두기(§14.24)."""
    if len(boxes) == 1:
        return [("data", lang, "--psm 7", _key_box(boxes[0]))]
    return [("data", lang, "--psm 6", ("sheet", tuple(_key_box(b) for b in boxes)))]


def _read_stack(img, boxes, lang, rd=None):
    """잘라낸 자리들을 **한 장에 세로로 쌓아** 한 번에 읽는다 → 자리마다 `(글, 평균 신뢰도)`.

    자리마다 Tesseract 를 따로 부르면 한 번에 0.1초 남짓 프로세스 값이 들어 쪽당 2~4초가 늘었다(실측 성격심리).
    261108-18: 판독은 `_Reads` 로 — 같은 쪽의 다른 다시 읽기와 함께 tesseract 한 번에(§14.24)."""
    rd = _reads_for(img, rd)
    if len(boxes) == 1:
        # 한 자리는 쌓지 않고 한 줄로 읽는다(psm 7) — 실험에서 가장 잘 읽힌 방식
        r = rd.get(*_stack_reqs(boxes, lang)[0])
        ws = []
        for t, c in zip(r["text"], r["conf"]):
            try:
                c = float(c)
            except (TypeError, ValueError):
                c = -1.0
            if str(t).strip() and c >= 0:
                ws.append((str(t).strip(), c))
        return [(" ".join(t for t, _ in ws), (sum(c for _, c in ws) / len(ws)) if ws else 0.0)]
    gap = _STACK_GAP
    spans, y = [], gap
    for b in boxes:
        h = int(b[3]) - int(b[1])
        spans.append((y, y + h))
        y += h + gap
    r = rd.get(*_stack_reqs(boxes, lang)[0])
    got = [[] for _ in boxes]
    for t, c, top, hh, left in zip(r["text"], r["conf"], r["top"], r["height"], r["left"]):
        try:
            c = float(c)
        except (TypeError, ValueError):
            c = -1.0
        if not str(t).strip() or c < 0:
            continue
        cy = top + hh / 2.0
        for k, (a, b) in enumerate(spans):
            if a - gap / 2 <= cy <= b + gap / 2:
                got[k].append((left, str(t).strip(), c))
                break
    out = []
    for ws in got:
        ws.sort()
        out.append((" ".join(t for _x, t, _c in ws), (sum(c for _x, _t, c in ws) / len(ws)) if ws else 0.0))
    return out


def _reread_words(img, items):
    """잡글 자리들을 다시 읽는다 — `items = [(번호, (x,y,w,h), 종류, 원래 글)]` → `{번호: (새 글, 신뢰도)}` (§14.8.2).

    `kor`: 한글 음절만 남고(빈칸은 지운다 — 한 낱말 자리다) 신뢰도가 `REREAD_KOR_CONF` 이상일 때만.
    실험 성격심리 5쪽 56곳 중 52곳이 바른 한글(`SAS`→`음식을`, `YES`→`행동을`, `ASA`→`실존적`).
    `eng`: 영문 조각(`(prepotence)`)을 `eng` 로 읽고, **원래 글이 괄호 앞뒤에 다른 글자를 달고 있었으면**
    (`psychology)o]e}` 의 `o]e}`) 그 자리의 한글 토막(`이라`)을 `kor` 로 읽어 잇는다 — 이미 따로 읽힌 토막은 다시 달지 않는다."""
    out = {}
    if not items:
        return out
    try:
        W, H = img.size
        boxes = [(max(0, int(x) - REREAD_PAD), max(0, int(y) - REREAD_PAD),
                  min(W, int(x + w) + REREAD_PAD), min(H, int(y + h) + REREAD_PAD)) for _i, (x, y, w, h), _k, _s in items]
        # 261108-18(§14.24): 아래 판독은 모두 `rd` 로 — 먼저 한꺼번에 모아 (종류·언어·설정)마다 tesseract 한 번에 읽고,
        #   차례·판정은 종전 그대로 기억해 둔 결과를 쓴다(결과가 같다). 다시 읽기(retry)는 앞 결과로 정해지므로 두 번째 묶음
        rd = _Reads(img)
        kor_idx = [n for n, it in enumerate(items) if it[2] == "kor" or (it[2] == "mix" and _LATIN_JUNK.fullmatch(it[3]))]
        eng_idx = [n for n, it in enumerate(items) if it[2] == "eng"]
        kor_need = kor_idx + [n for n in eng_idx if re.search(r"\)[^)\s]|[^(\s]\(", items[n][3])]
        reqs = []
        for n, (_i, _b, kind, _s) in enumerate(items):
            if kind in ("num", "mix", "grp"):
                reqs += _one_reqs(boxes[n], kind)
        if kor_need:
            reqs += _stack_reqs([boxes[n] for n in kor_need], "kor")
        if eng_idx:
            reqs += _stack_reqs([boxes[n] for n in eng_idx], "eng")
        rd.prefetch(reqs)
        # 261102-2(§14.8.3): 번호·섞인 낱말·갈린 영문은 한 자리씩 한 줄로(psm 7) 읽는다 — 드물고(쪽당 몇 곳) 쌓으면 점이 뭉개진다
        for n, (i, _b, kind, s) in enumerate(items):
            if kind in ("num", "mix", "grp"):
                got = _reread_one(img, boxes[n], kind, s, rd=rd)
                if got:
                    out[i] = got
        # 종전에 `kor` 로 읽던 꼴(`_LATIN_JUNK`)의 섞인 낱말은 쌓아 읽기에도 그대로 넣는다 — 쌓은 묶음이 바뀌면 이웃 자리의
        #   결과도 바뀐다(실측 성격심리 401쪽 `변화를`→`번화를`). 영문 머리를 못 가른 자리는 그 결과(종전 규칙)를 쓴다
        kres = dict(zip(kor_need, _read_stack(img, [boxes[n] for n in kor_need], "kor", rd=rd))) if kor_need else {}
        eres = dict(zip(eng_idx, _read_stack(img, [boxes[n] for n in eng_idx], "eng", rd=rd))) if eng_idx else {}
        # 쌓아 읽으면 몇 자리는 옆 자리에 휩쓸린다(실측 성격심리 300쪽 14곳 중 3곳) — 문턱을 못 넘은 자리만 따로 한 번 더
        #   (아래 두 고리와 같은 판정으로 먼저 고른 자리를 한 번에 읽어 둔다)
        retry, again = 0, []
        for n in kor_idx:
            if retry >= REREAD_RETRY:
                break
            if items[n][0] in out:
                continue
            if kres.get(n, ("", 0.0))[1] < REREAD_KOR_CONF:
                again += _stack_reqs([boxes[n]], "kor")
                retry += 1
        for n in eng_idx:
            if retry >= REREAD_RETRY:
                break
            if eres.get(n, ("", 0.0))[1] < REREAD_ENG_CONF or not re.search(r"[A-Za-z]{3,}", eres.get(n, ("", 0))[0]):
                again += _stack_reqs([boxes[n]], "eng")
                retry += 1
        rd.prefetch(again)
        retry = 0
        for n in kor_idx:
            if retry >= REREAD_RETRY:
                break
            if items[n][0] in out:
                continue
            if kres.get(n, ("", 0.0))[1] < REREAD_KOR_CONF:
                kres[n] = _read_stack(img, [boxes[n]], "kor", rd=rd)[0]
                retry += 1
        for n in eng_idx:
            if retry >= REREAD_RETRY:
                break
            if eres.get(n, ("", 0.0))[1] < REREAD_ENG_CONF or not re.search(r"[A-Za-z]{3,}", eres.get(n, ("", 0))[0]):
                eres[n] = _read_stack(img, [boxes[n]], "eng", rd=rd)[0]
                retry += 1
        from viewer.study.wordfreq_fast import zipf_frequency
        for n, (i, _b, kind, s) in enumerate(items):
            if kind not in ("kor", "eng", "mix") or i in out:
                continue
            if kind in ("kor", "mix"):
                t, c = kres.get(n, ("", 0.0))
                core = t.replace(" ", "")
                if c >= REREAD_KOR_CONF and _HANGUL_RE.search(core) and re.fullmatch(r"[가-힣.,?!·()\-]+", core):
                    out[i] = (core, c)
                continue
            e, ec = eres.get(n, ("", 0.0))
            pieces = re.findall(r"\(?[A-Za-z][A-Za-z\-]{2,}\)?[,.]?", e)
            if ec < REREAD_ENG_CONF or not pieces:
                continue
            lat = max(pieces, key=len)
            letters = re.sub(r"[^A-Za-z]", "", lat).lower()
            if zipf_frequency(letters, "en") < 2.0 and len(letters) < 7:
                continue
            k = kres.get(n, ("", 0.0))[0]
            pre = "".join(_HANGUL_RE.findall(k.split("(")[0])) if (lat.startswith("(") and "(" in k
                                                                    and re.search(r"[^(\s]\(", s)) else ""
            suf = "".join(_HANGUL_RE.findall(k.rsplit(")", 1)[1])) if (lat.rstrip(",.").endswith(")") and ")" in k
                                                                       and re.search(r"\)[^)\s]", s)) else ""
            out[i] = (pre + lat + suf, max(ec, float(MIN_CONF_PCT)))
    except Exception:
        return out
    return out


def _one_reqs(box, kind) -> list:
    """`_reread_one` 이 읽을 것 — 미리 모아 두기(§14.24)."""
    b = _key_box(box)
    if kind == "num":
        return _stack_reqs([b], "kor")
    return [("data", "kor", "--psm 7", b), ("boxes", "eng", "--psm 7", b)]


def _reread_one(img, box, kind, s, rd=None):
    """한 자리를 한 줄로 다시 읽어 받을 글을 고른다(§14.8.3) → `(글, 신뢰도)` 또는 None.

    `num`: `kor` 로 읽은 번호가 **숫자는 같고 점이 더 많을 때만**(`45.2`→`4.5.2`) — 숫자를 바꾸지 않는다.
    `mix`: 영문 머리는 `eng` 로(원래 글이 그 머리로 시작할 때), 뒤 한글은 `kor` 로(1~4 음절, 신뢰도 `REREAD_KOR_CONF` 이상)
    — `COES]`→`COE의`. 한글이 시작하는 자리(`kor` 낱말 상자)에서 가른다. 영문 머리를 못 가르면 None — 부르는 쪽이
    쌓아 읽은 `kor` 결과(종전 규칙)를 쓴다.
    `grp`: 갈린 토막을 묶은 상자를 `eng` 로 — 대문자 3자 이상(`WASHO`), 뒤 한글은 `mix` 와 같이."""
    crop = [box]
    if kind == "num":
        t, c = _read_stack(img, crop, "kor", rd=rd)[0]
        t = t.replace(" ", "")
        digits = lambda x: re.sub(r"\D", "", x)   # noqa: E731
        if (re.fullmatch(r"\d+(?:\.\d+)+\.?", t) and digits(t) == digits(s) and t.count(".") > s.count(".")):
            return (t, max(c, float(MIN_CONF_PCT)))
        return None
    # mix·grp: 한글이 시작하는 자리(`kor` 낱말 상자)에서 가른다 — 그 앞의 대문자는 `eng` 글자, 그 뒤는 `kor` 한글 낱말
    kws = _read_line_words(img, box, "kor", rd=rd)
    han = [(t, c, x) for t, c, x in kws if re.fullmatch(r"[가-힣]+[.,]?", t)]
    cut = han[0][2] if han else float("inf")
    tail = [(t, c) for t, c, x in han if x >= cut]
    # 영문에 맞닿은 첫 음절은 신뢰도가 바닥으로 나오곤 한다(`CBR설` 의 `설` 0) — 아래쪽 가운데 값으로 본다
    #   (둘이면 낮은 쪽 — 옆 낱말 음절이 걸려 든 `WAIS-IV는연` 의 `연` 을 받지 않게)
    tail_ok = bool(tail) and sorted(c for _t, c in tail)[(len(tail) - 1) // 2] >= REREAD_KOR_CONF
    head = ""
    for ch, cx in _read_line_chars(img, box, "eng", rd=rd):
        if cx >= cut or not ("A" <= ch <= "Z" or (ch == "-" and head)):
            break
        head += ch
    head = head.rstrip("-")
    need = 3 if kind == "grp" else 2
    if len(head) >= need and (kind == "grp" or s.startswith(head.replace("-", ""))) \
            and (tail_ok or (kind == "grp" and not tail)):
        got = head + ("".join(t for t, _c in tail) if tail_ok else "")
        if got != s:
            return (got, float(REREAD_KOR_CONF if tail_ok else MIN_CONF_PCT))
        return None
    return None                   # 영문 머리를 못 가르면 쌓아 읽은 `kor` 결과(종전 규칙)에 맡긴다


_CAPTION_CLOSE = re.compile(r"\d+(?:[-.]\d+)*>")      # 표·그림 번호의 닫는 꺾쇠 `2-1>`·`4-74>`
_CAPTION_WORDS = ("표", "그림")                      # 문서 글에서 찾는 표·그림 제목 낱말(화면 문구 아님 — 다국어 SOT §7 문서 처리)


def _caption_open(texts, idx, key, conf):
    """닫는 꺾쇠만 있는 표·그림 제목에 여는 `<` 를 되살린다 (텍스트 창 SOT §3.5.5, 261102-2).

    `<그림2-1>` 의 `<` 는 Tesseract 가 아예 내놓지 않거나(실측 _96 12쪽) 낮은 신뢰도로 내놓아 버려진다.
    `표`·`그림` 바로 뒤 번호가 `>` 로 끝나고 그 앞에 `<` 가 없으면 `표`/`그림` 첫 낱말 앞에 붙인다 — 따로 읽힌 `<` 가 있으면 그것을 남긴다."""
    by_line = {}
    for i in idx:
        by_line.setdefault(key(i), []).append(i)
    for ids in by_line.values():
        ids = [i for i in ids if str(texts[i]).strip()]
        for n, i in enumerate(ids):
            s = str(texts[i]).strip()
            m = re.match(r"(.*?)(" + "|".join(_CAPTION_WORDS) + ")" + _CAPTION_CLOSE.pattern + r"$", s)
            if m is not None:
                start, word = n, m.group(1) + m.group(2)
            elif _CAPTION_CLOSE.match(s):
                # `그` `림` `2-1>` 처럼 갈렸다 — 바로 앞 낱말 한두 개가 `표`/`그림` 으로 끝나면
                word, start = "", n
                for k in range(n - 1, max(-1, n - 3), -1):
                    word = str(texts[ids[k]]).strip() + word
                    start = k
                    if word.endswith(_CAPTION_WORDS):
                        break
                if not word.endswith(_CAPTION_WORDS):
                    continue
            else:
                continue
            if "<" in word or "〈" in word:
                continue
            if start > 0 and str(texts[ids[start - 1]]).strip() in ("<", "〈"):
                conf[ids[start - 1]] = max(float(conf.get(ids[start - 1], 0) or 0), float(MIN_CONF_PCT))
                continue
            # 문장 속 가리킴(`<표4-73>과같다`)은 이미 `<` 가 붙어 위에서 걸러진다 — 여기 오는 것은 `<` 가 빠진 것
            texts[ids[start]] = "<" + str(texts[ids[start]]).strip()


def _read_line_words(img, box, lang, rd=None):
    """한 자리를 한 줄로(psm 7) 읽어 낱말마다 `(글, 신뢰도, 왼쪽 x)` — 자른 그림 좌표."""
    r = _reads_for(img, rd).get("data", lang, "--psm 7", _key_box(box))
    out = []
    for t, c, x in zip(r["text"], r["conf"], r["left"]):
        try:
            c = float(c)
        except (TypeError, ValueError):
            c = -1.0
        if str(t).strip() and c >= 0:
            out.append((str(t).strip(), c, x))
    return out


def read_line_words(img, box, lang, psm=7):
    """한 자리를 한 줄로 읽어 낱말 상자 목록 — `{surface, x0, y0, x1, y1, conf(0~1)}`, **쪽 그림 좌표**(`box` 의 왼쪽 위를 더한다).
    목차 줄 다시 읽기(마스터 §4.4.2·단어학습 SOT §14.8.3)처럼 부르는 쪽이 낱말 자리로 맞춰 쓸 때.
    `batch_reads(img)` 안이면 미리 모은 판독을 쓴다(§14.24)."""
    r = _reads_for(img).get("data", lang, f"--psm {int(psm)}", _key_box(box))
    out = []
    for t, c, x, y, w, h in zip(r["text"], r["conf"], r["left"], r["top"], r["width"], r["height"]):
        try:
            c = float(c)
        except (TypeError, ValueError):
            c = -1.0
        if str(t).strip() and c >= 0:
            out.append({"surface": str(t).strip(), "x0": float(box[0] + x), "y0": float(box[1] + y),
                        "x1": float(box[0] + x + w), "y1": float(box[1] + y + h), "conf": c / 100.0})
    return out


def _read_line_chars(img, box, lang, rd=None):
    """한 자리를 한 줄로(psm 7) 읽어 글자마다 `(글자, 가운데 x)` — 자른 그림 좌표, 왼쪽부터."""
    out = []
    for ln in _reads_for(img, rd).get("boxes", lang, "--psm 7", _key_box(box)).splitlines():
        f = ln.split(" ")
        if len(f) >= 5:
            try:
                out.append((f[0], (int(f[1]) + int(f[3])) / 2.0))
            except ValueError:
                pass
    return sorted(out, key=lambda t: t[1])


def _small_glyph_keep(data, nb, s, x, w, h, c, line_h, dpi) -> bool:
    """납작한 진짜 글자인가(텍스트 창 SOT §3.5.3, 261101-1) — 이웃 낱말(`nb`) 높이로 맞춘 상자도 모양 거르기를 지나야 한다."""
    if nb is None or _noise.is_symbol_only(s) or not _noise.small_glyph_ok(s, h, c / 100.0, line_h):
        return False
    return _noise.keep_ocr_word(s, x, data["top"][nb], x + w, data["top"][nb] + data["height"][nb],
                                c / 100.0, scale=72.0 / max(1, int(dpi)))


MIN_CONF_PCT = 31           # 다시 읽어 받은 낱말이 신뢰도 거르기(§3.5 ④)에 다시 걸리지 않게 주는 최소값


def ocr_image(img, lang: str = "eng", psm: int = 0, dpi: int = 300) -> dict:
    """이미지 OCR → {text, conf, words:[{surface,x0,y0,x1,y1,conf}]} (픽셀 좌표).

    260908-8(텍스트 창 SOT §3.5 · 단어학습 SOT §14.6): **글자로 볼 수 없는 낱말은 버린다.**
    OCR 은 종이의 티·괘선을 `픔`·`■` 같은 글자로 읽는다. 그것을 그대로 두면
    본문·단어장·검색 색인이 모두 오염된다. 판정은 `viewer.text_noise` 가 소유한다.
    """
    info = ensure_tesseract()
    if not info.get("ok"):
        raise RuntimeError(f"Tesseract 사용 불가: {info.get('error')}")
    from viewer.study import tess_run
    cfg = f"--psm {int(psm) or DEFAULT_PSM}"
    data = tess_run.data([img], lang, cfg)[0]          # 261108-18(§14.24): 임시 파일 없이(표준 입출력)
    words = []
    confs = []
    parts = []
    prev_line = None        # (block,par,line) — 줄이 바뀌면 개행 삽입(머리말/꼬리말·하이픈 처리용)
    has_lineinfo = all(k in data for k in ("block_num", "par_num", "line_num"))
    # 261101-1(텍스트 창 SOT §3.5.3): 영문 `I` 를 `|`·`[`·`1`·`[can`·`Wait—t` 로 읽은 것과 `fi`↔`fl` 합자를
    #   **버리기 전에** 고친다 — 같은 줄의 앞뒤 낱말과 그 줄 낱말 높이로 판단한다
    _key = ((lambda i: (data["block_num"][i], data["par_num"][i], data["line_num"][i]))
            if has_lineinfo else (lambda i: 0))
    _idx = [i for i, t in enumerate(data["text"]) if str(t).strip()]
    _hs = {}
    for i in _idx:
        _hs.setdefault(_key(i), []).append(data["height"][i])
    _med = {k: sorted(v)[len(v) // 2] for k, v in _hs.items()}
    _texts = list(data["text"])
    _is_i = {}                     # 고친 낱말 → 상자를 맞출 이웃 낱말(같은 줄)
    _conf = {}                     # 다시 읽어 바꾼 낱말의 새 신뢰도(0~100)
    # 261101-1(§14.8.2, 표본 조사): `kor` 를 섞어 읽은 한글 줄에서 한글 낱말이 영문 대문자 잡글(`음식을`→`SAS`)로,
    #   괄호 속 작은 영문이 숫자 잡글(`(prepotence)`→`(0100010009'`)로 나온다 — 그 자리만 잘라 다시 읽는다
    _han_lines = {_key(i) for i in _idx if _HANGUL_RE.search(str(data["text"][i]))}
    _items = []
    _groups = {}                   # 묶어 읽은 첫 낱말 → 함께 지울 나머지 낱말(§14.8.3 `\4 ㅅ 980` → `WASHO`)
    if img is not None and "kor" in str(lang).split("+"):
        n_idx = len(_idx)
        skip = set()
        for n, i in enumerate(_idx):
            if len(_items) >= REREAD_MAX:
                break
            if i in skip:
                continue
            s0 = str(_texts[i]).strip()
            first = n == 0 or _key(_idx[n - 1]) != _key(i)
            box = (data["left"][i], data["top"][i], data["width"][i], data["height"][i])
            if _key(i) not in _han_lines:
                continue
            one = sum(1 for it in _items if it[2] in ("num", "mix", "grp"))
            # 261102-2(§14.8.3): 한글 줄 첫머리 번호 `45.2`·`21.1` — `kor` 로 다시 읽으면 `4.5.2`·`2.1.1`
            if first and _SECTION_NO.fullmatch(s0):
                if one < REREAD_ONE_MAX:
                    _items.append((i, box, "num", s0))
                continue
            # 261102-2(§14.8.3): 낱자모·`\` 가 낀 토막이 잇달면 굵은 영문 낱말이 갈린 것(`\4` `ㅅ` `980` = WASHO) — 묶어 `eng` 로
            #   괄호가 든 토막은 괄호 속 영문(§14.8.2 `eng`)이 먼저다 — `(『6\` = `(Psy`
            if _JAMO_JUNK.search(s0) and not _HANGUL_RE.search(s0) and len(s0) <= 4 and not re.search(r"[()]", s0):
                if one >= REREAD_ONE_MAX:
                    continue
                run = [i]
                for m in range(n + 1, min(n_idx, n + 6)):
                    j = _idx[m]
                    sj = str(_texts[j]).strip()
                    if _key(j) != _key(i) or not re.fullmatch(r"[^\s가-힣]{1,4}", sj):
                        break
                    run.append(j)
                x0 = min(data["left"][j] for j in run)
                y0 = min(data["top"][j] for j in run)
                x1 = max(data["left"][j] + data["width"][j] for j in run)
                y1 = max(data["top"][j] + data["height"][j] for j in run)
                _items.append((i, (x0, y0, x1 - x0, y1 - y0), "grp", s0))
                after = _idx[n + len(run)] if n + len(run) < n_idx and _key(_idx[n + len(run)]) == _key(i) else None
                _groups[i] = (run[1:], after)
                skip.update(run[1:])
                continue
            kind = _reread_kind(s0, lang)
            if kind and (kind != "mix" or one < REREAD_ONE_MAX):
                _items.append((i, box, kind, s0))
    for i, (t_new, c_new) in _reread_words(img, _items).items():
        rest, after = _groups.get(i, ((), None))
        if after is not None:
            # 묶은 상자에 바로 뒤 한글 낱말이 걸려 읽혔으면(`WASHO의` + `의도로`) 겹친 꼬리를 뗀다
            m = re.match(r"([A-Z]+)([가-힣]+)$", t_new)
            if m and str(_texts[after]).strip().startswith(m.group(2)):
                t_new = m.group(1)
        _texts[i], _conf[i] = t_new, c_new
        for j in rest:
            _texts[j] = ""            # 묶어 읽은 나머지 토막은 지운다
    _caption_open(_texts, _idx, _key, _conf)
    _neighbor = {}                 # 같은 줄의 이웃 낱말(앞, 없으면 뒤) — 상자 높이를 맞출 때
    _adj = {}                      # 같은 줄의 (앞, 뒤) 낱말 — 괄호가 낱말에 붙었나 볼 때
    for n, i in enumerate(_idx):
        a = _idx[n - 1] if n > 0 and _key(_idx[n - 1]) == _key(i) else None
        b = _idx[n + 1] if n + 1 < len(_idx) and _key(_idx[n + 1]) == _key(i) else None
        _neighbor[i] = a if a is not None else b
        _adj[i] = (a, b)
        if i in _conf:
            continue
        s0 = str(_texts[i]).strip()
        bul = _noise.as_bullet(s0, data["width"][i], data["height"][i], a is None, b is not None,
                               _med.get(_key(i), 0))
        if bul:
            # 261101-1(텍스트 창 SOT §3.5.4): 줄 첫머리의 작은 점·네모는 목록 기호 — 잡음으로 버리지 않는다
            _texts[i] = bul
            _is_i[i] = b
            continue
        got = _noise.fix_i(_texts[a] if a is not None else None, s0, data["width"][i], data["height"][i],
                           _texts[b] if b is not None else None, _med.get(_key(i), 0))
        if got is None:
            got = _noise.fix_ligature(s0)
            if got is not None:
                _texts[i] = got
            continue
        _texts[i] = got
        _is_i[i] = a if a is not None else b
    def _small_ok(i, s, x, w, h, c):
        return _small_glyph_keep(data, _neighbor.get(i), s, x, w, h, c, _med.get(_key(i), 0), dpi)

    def _bracket_ok(i, s, x, w, h, c):
        # 261102-2(텍스트 창 SOT §3.5.5): 낱말에 붙은 `<`·`(`·따옴표는 기호만이어도 남긴다 — 이웃이 지워진 토막이면 보지 않는다
        a, b = _adj.get(i, (None, None))
        gaps = []
        if a is not None and str(_texts[a]).strip():
            gaps.append(x - (data["left"][a] + data["width"][a]))
        if b is not None and str(_texts[b]).strip():
            gaps.append(data["left"][b] - (x + w))
        return _noise.bracket_ok(s, c / 100.0, h, _med.get(_key(i), 0), min((max(0, g) for g in gaps), default=None))

    def _rescue(i, s, x, w, h, c):
        return _small_ok(i, s, x, w, h, c) or _bracket_ok(i, s, x, w, h, c)

    for i, txt in enumerate(_texts):
        s = str(txt).strip()
        if not s:
            continue
        c = _conf.get(i, data["conf"][i])
        try:
            c = float(c)
        except (TypeError, ValueError):
            c = -1.0
        if c < 0:
            continue
        x, y, w, h = (data["left"][i], data["top"][i],
                      data["width"][i], data["height"][i])
        if i in _conf:
            pass                        # 다시 읽어 얻은 낱말(§14.8.2) — 잡글이던 자리라 모양·신뢰도 거르기는 하지 않는다
        elif i in _is_i:
            # 고친 `I` — 획이 1px 로 잡혀도 버리지 않는다. 높이는 이웃 낱말에 맞추고(위아래 글줄과 엉긴 53px 상자가
            #   두 줄을 잇지 않게) 폭은 글자 폭쯤으로 넓혀 화면 단계의 같은 규칙(③ 홀쭉한 한 글자)에도 걸리지 않게 한다.
            j = _is_i[i]
            if j is not None:
                y, h = data["top"][j], data["height"][j]
            if w < h * 0.3:
                x, w = int(x + w / 2 - h * 0.15), max(1, int(round(h * 0.3)))
        elif not _noise.keep_ocr_word(s, x, y, x + w, y + h, c / 100.0,
                                      scale=72.0 / max(1, int(dpi))):
            if not _rescue(i, s, x, w, h, c):
                continue                    # 260908-8: 잡음은 본문에서도 뺀다(괄호 남기기는 §3.5.5)
            # 261101-1(텍스트 창 SOT §3.5.3): 납작한 진짜 글자(`을`·`는` 15px)는 ①(4pt)에 걸려도 남긴다 — 상자 높이를
            #   같은 줄 이웃 낱말에 맞춰 화면 단계의 같은 규칙에도 걸리지 않게 한다
            y, h = data["top"][_neighbor[i]], data["height"][_neighbor[i]]
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

    260908-8: 이 경로도 **스캔본을 탈 수 있다** — 보이지 않게 얹힌 OCR 글자층이라도 그림
    점유율이 1번 문턱 미만인 쪽은 `decide_source` 가 'layer' 로 판정한다(단어학습 SOT §14.18).
    그런 쪽에서는 텍스트 창과 **같은 규칙**으로 잡음 낱말을 뺀다(텍스트 창 SOT §3.5).
    사람이 넣은 글자층은 건드리지 않는다.
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


# 261101-1(§14.8.1): `kor+eng` 로 읽는데 한글이 없으면 읽은 결과로 `eng` 로 좁힌다 — 값은 §14.B
LANG_EN_PAGES = 1          # 잇달아 이만큼 한글 0자 쪽이면(261101-1 보완: 2 → 1 — 두 쪽만 읽으면 첫 쪽이 늘 kor+eng 로 남았다)
LANG_EN_MIN_WORDS = 40     # (그 쪽에 라틴 낱말이 이만큼 있어야 판단에 넣는다)
LANG_EN_BACK_Q = 0.6       # `eng` 로 읽은 쪽의 영문다움(`_english_quality`)이 이 아래면 되돌린다


def _english_quality(text: str) -> float:
    """영문다움 0~1 — 세 글자 이상 낱말 가운데 **자연스러운 대소문자**(소문자·첫 글자만 대문자)이고 사전에 흔한(zipf ≥ 3) 것의 비율.

    261101-1(§14.8.1): `_latin_quality` 는 `Al`·`Bk` 같은 두 글자 조각도 사전 낱말로 쳐서, 한글 쪽을 `eng` 로 읽은
    잡글도 0.91~0.95 가 나온다. 이 값은 실측 잡글 0.25~0.40(검사의이해·성격심리) / 영문 0.91~0.95(HM·NAPA)."""
    toks = re.findall(r"[A-Za-z]{3,}", text or "")
    if not toks:
        return 0.0
    try:
        from viewer.study.wordfreq_fast import zipf_frequency
    except Exception:
        return _latin_quality(text)
    ok = sum(1 for t in toks if (t.islower() or t.istitle()) and zipf_frequency(t.lower(), "en") >= 3.0)
    return ok / len(toks)


class LangPicker:
    """여러 쪽을 읽는 동안 언어를 고른다 (단어학습 SOT §14.8.1, 261101-1).

    `kor+eng` 로 읽은 쪽이 잇달아 한글 0자면 그 뒤는 `eng` 로 — 영문 스캔본을 `kor+eng` 로 읽으면
    `I` 를 `1` 로 읽는다(HM 31쪽 42곳 → `eng` 3곳). `eng` 로 읽은 쪽이 사전 낱말 비율이 낮으면(한글 쪽을
    영문으로 읽은 잡글) 그 쪽을 다시 읽고 되돌린다. `kor`·`eng` 하나만 고른 것은 건드리지 않는다.
    `read()` 결과에 실제로 읽은 언어를 `lang` 으로 붙인다 — `save_page(lang=)` 에 그대로 쓴다."""

    def __init__(self, lang: str):
        self.base = resolve_lang(lang)
        parts = self.base.split("+")
        self.adapt = ("kor" in parts and "eng" in parts and "eng" in set(available_langs() or ["eng"]))
        self.lang = self.base
        self._streak = 0
        self.changed = ""           # 바뀌었으면 사람이 읽을 알림(부르는 쪽이 진행 글에 보인다)

    def read(self, doc, page_index: int, **kw) -> dict:
        return self._read(lambda lang: build_page(doc, page_index, lang=lang, **kw))

    def read_photo(self, path, rot: int = 0) -> dict:
        """사진 한 장(단어학습 SOT §14.22) — 언어 고르기는 PDF 와 같다."""
        return self._read(lambda lang: build_photo(path, lang=lang, rot=rot))

    def _read(self, fn) -> dict:
        res = fn(self.lang)
        used = self.lang
        self.changed = ""
        if self.adapt and res.get("source") == "ocr":
            text = res.get("text") or ""
            if self.lang == self.base:
                if _HANGUL_RE.search(text):
                    self._streak = 0
                elif (len(_WORD_RE.findall(text)) >= LANG_EN_MIN_WORDS
                      and _english_quality(text) >= LANG_EN_BACK_Q):
                    self._streak += 1
                    if self._streak >= LANG_EN_PAGES:
                        # 정한 그 쪽부터 `eng` 로 — 한 쪽을 더 읽는 값은 한 번뿐이다
                        self.lang = "eng"
                        self.changed = tr("한글이 없어 영문으로 읽습니다")
                        res = fn(self.lang)
                        used = self.lang
            elif len(text.strip()) >= 50 and _english_quality(text) < LANG_EN_BACK_Q:
                self.lang, self._streak = self.base, 0
                res = fn(self.lang)
                used = self.lang
                self.changed = tr("한글이 보여 한글 + 영문으로 다시 읽습니다")
        res["lang"] = used
        return res


def photo_sig(path) -> str:
    """사진 OCR 의 낡음 판정 표(단어학습 SOT §14.22) — 크기·수정 시각. study.db 의 `engine` 칸 끝에 붙여 남긴다."""
    st = os.stat(str(path))
    return "photo:%d:%d" % (st.st_size, st.st_mtime_ns)


def _box_rot(x0, y0, x1, y1, rot, w0, h0):
    """상자(픽셀) — 폭 w0·높이 h0 판에서 시계 방향 rot 만큼 돈 판으로(사진 꾸밈 좌표와 같은 규칙, photo_deco)."""
    if rot == 90:
        return h0 - y1, x0, h0 - y0, x1
    if rot == 180:
        return w0 - x1, h0 - y1, w0 - x0, h0 - y0
    if rot == 270:
        return y0, w0 - x1, y1, w0 - x0
    return x0, y0, x1, y1


def photo_words_view(words, rot: int, w0: float, h0: float) -> list:
    """회전 0 판 낱말(픽셀 = pt) → 보기 회전 판 낱말. 텍스트 창 줄·본문 강조가 돈 쪽 좌표를 쓴다."""
    rot = int(rot or 0) % 360
    if not rot:
        return [dict(w) for w in words]
    out = []
    for w in words:
        d = dict(w)
        d["x0"], d["y0"], d["x1"], d["y1"] = _box_rot(w["x0"], w["y0"], w["x1"], w["y1"], rot, w0, h0)
        out.append(d)
    return out


def build_photo(path, *, lang: str = "eng", rot: int = 0) -> dict:
    """사진 한 장 OCR(단어학습 SOT §14.22) — 원래 픽셀(EXIF 방향 적용 = 회전 0 판), 보기 회전대로 돌려 읽고 긴 변은
    `PHOTO_MAX_SIDE` 까지. 낱말 상자는 **회전 0 판 픽셀(= pt)** 로 되돌려 `dpi=72`. `engine` 끝에 `photo_sig`."""
    from PIL import Image, ImageOps
    from viewer import photo_io
    sig = photo_sig(path)
    photo_io._prep(path)
    with Image.open(str(path)) as im:
        im = ImageOps.exif_transpose(im)
        im.load()
    w0, h0 = im.size
    rot = int(rot or 0) % 360
    if rot:
        im = im.rotate(-rot, expand=True)               # PIL 은 반시계 — 시계 방향으로
    vw, vh = im.size
    s = min(1.0, PHOTO_MAX_SIDE / float(max(vw, vh)))
    if s < 1.0:
        im = im.resize((max(1, round(vw * s)), max(1, round(vh * s))), Image.Resampling.LANCZOS)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    res = ocr_image(im, lang=resolve_lang(lang), dpi=72.0 * s)
    back = (360 - rot) % 360
    words = []
    for w in res.get("words") or []:
        x0, y0, x1, y1 = (float(w[k]) / s for k in ("x0", "y0", "x1", "y1"))
        x0, y0, x1, y1 = _box_rot(x0, y0, x1, y1, back, vw, vh)
        d = dict(w)
        d.update(x0=x0, y0=y0, x1=x1, y1=y1)
        words.append(d)
    res["words"] = words
    res.update(source="ocr", dpi=72, engine="tesseract|" + sig, why={"reason": "photo"}, size=(w0, h0))
    return res


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
    if "kor" in resolve_lang(lang).split("+"):
        # 261102-2(§14.8.4): 목차 쪽이면 제목의 잡글 낱말(`Ds Fi`=`1. 서 론`)을 `kor` 로 — 텍스트 창·글자층·책갈피가 같은 글을 쓴다
        try:
            import sys as _sys
            from viewer.study import ocr_pages as _op
            _op.fix_toc_page(_sys.modules[__name__], img, res, dpi, lang=resolve_lang(lang))
        except Exception:
            pass
    res.update(source="ocr", dpi=dpi, engine="tesseract", why=why)
    return res
