"""화면 언어와 언어팩 — 다국어(언어팩) SOT §3 (261008, Phase 0).

- 원문은 **한국어**이고 그대로 번역 키(gettext `msgid`)다. 한국어는 팩이 없다.
- 언어팩 = `resources/locale/<코드>/` — `LC_MESSAGES/polypdf.mo`(빌드 때 `.po` 에서) + `pack.json`(메타).
- 언어는 **시작할 때 한 번** 정한다(`install`). 실행 중에는 바뀌지 않는다 — 바꾸면 재시작(SOT §1).
- 함수 이름을 `_` 로 하지 않는다: 코드가 `_` 를 버리는 변수로 120곳 넘게 쓴다(SOT §3.1).

공개 함수: tr · trp · trn · tr_noop · language · available_languages · korea_only_visible ·
initial_language · install · pack_dir
"""
from __future__ import annotations

import gettext
import json
import logging
import os
import sys
from pathlib import Path

__all__ = ["tr", "trp", "trn", "tr_noop", "language", "available_languages",
           "korea_only_visible", "initial_language", "install", "pack_dir", "normalize"]

DOMAIN = "polypdf"
KO = "ko"
PSEUDO = "qps_ploc"             # 개발·검사 전용 가짜 언어(SOT §3.7) — 목록에 나오지 않는다
ENV = "POLYPDF_LANG"            # 설정보다 앞서는 언어(저장하지 않는다, SOT §3.6)
_KO_META = {"code": KO, "name": "한국어", "name_ko": "한국어", "fallback": [],
            "qt": "qtbase_ko", "status": "complete", "direction": "ltr"}

_log = logging.getLogger(__name__)
_lang = KO
_trans = gettext.NullTranslations()        # 한국어 = 원문 그대로
_qt_translator = None                      # 설치한 QTranslator(가비지 수거 방지)


# ── 위치 ──────────────────────────────────────────────────────────────────
def pack_dir() -> Path:
    """내장 언어팩 폴더 `resources/locale` (배포본은 `_MEIPASS/resources/locale`)."""
    try:
        from viewer.resources_path import resource_path
        p = resource_path("locale")
        if p:
            return Path(p)
    except Exception:
        pass
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / "resources" / "locale"


def normalize(code: str) -> str:
    """언어 코드를 gettext 꼴 `ll` / `ll_CC` 로(`ko-KR` → `ko_KR`, SOT §3.2)."""
    c = str(code or "").strip().replace("-", "_")
    if "_" in c:
        a, b = c.split("_", 1)
        return a.lower() + "_" + b.upper() if len(b) == 2 else a.lower() + "_" + b.lower()
    return c.lower()


def _read_meta(code: str):
    if code == KO:
        return dict(_KO_META)
    f = pack_dir() / code / "pack.json"
    try:
        meta = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(meta, dict) or normalize(meta.get("code", "")) != code or not meta.get("name"):
        _log.warning("언어팩 메타가 올바르지 않아 무시: %s", f)
        return None
    if str(meta.get("direction", "ltr")).lower() != "ltr":
        _log.warning("오른쪽→왼쪽 언어는 아직 지원하지 않는다(SOT §13): %s", code)
        return None
    meta.setdefault("fallback", [] if code == "en" else ["en"])   # 중간 언어(SOT §3.3)
    meta.setdefault("status", "partial")
    return meta


def available_languages() -> list:
    """고를 수 있는 언어 `[(코드, 자기 이름, 상태), …]` — 한국어 먼저, 나머지는 코드 순. 가짜 언어는 뺀다."""
    out = [(KO, _KO_META["name"], "complete")]
    try:
        dirs = sorted(d.name for d in pack_dir().iterdir() if d.is_dir())
    except Exception:
        dirs = []
    for code in dirs:
        if code in (KO, PSEUDO) or normalize(code) != code:
            continue
        meta = _read_meta(code)
        if meta:
            out.append((code, str(meta["name"]), str(meta.get("status", "partial"))))
    return out


# ── 번역 ──────────────────────────────────────────────────────────────────
def tr(text: str) -> str:
    """화면 문구. `text` = 한국어 원문(키). 번역이 없으면 원문."""
    return _trans.gettext(text)


def trp(context: str, text: str) -> str:
    """문맥이 다른 같은 원문(msgctxt)."""
    return _trans.pgettext(context, text)


def trn(text: str, n: int) -> str:
    """수에 따라 꼴이 바뀌는 문구 — 한국어 원문은 한 꼴이라 단·복수 키가 같다."""
    return _trans.ngettext(text, text, int(n))


def tr_noop(text: str) -> str:
    """추출만 표시 — 불러오는 시점에는 번역하지 않는다(쓰는 곳에서 `tr`)."""
    return text


def language() -> str:
    return _lang


def korea_only_visible() -> bool:
    """한국 전용 기능(법령·KCSC·KIPO·영어단어 학습)을 보일지 — SOT §7."""
    return _lang == KO


def _chain(code: str) -> list:
    """고른 언어 → fallback(순서대로) — 고리·중복 없이. 끝의 한국어 원문은 NullTranslations."""
    out, todo = [], [code]
    while todo:
        c = normalize(todo.pop(0))
        if not c or c == KO or c in out:
            continue
        meta = _read_meta(c) if c != PSEUDO else {"fallback": []}
        if meta is None:
            continue
        out.append(c)
        todo.extend(meta.get("fallback") or [])
    return out


def _translations_for(codes: list):
    """사슬의 `.mo` 들을 add_fallback 으로 잇는다. 하나도 없으면 NullTranslations."""
    head = None
    for c in codes:
        mo = pack_dir() / c / "LC_MESSAGES" / (DOMAIN + ".mo")
        if not mo.is_file():
            _log.warning("언어팩 .mo 가 없다(빌드 때 만든다 — scripts/i18n.py compile): %s", mo)
            continue
        try:
            with open(mo, "rb") as f:
                t = gettext.GNUTranslations(f)
        except Exception as e:
            _log.warning("언어팩 .mo 를 읽지 못함 %s: %s", mo, e)
            continue
        if head is None:
            head = t
        else:
            head.add_fallback(t)
    return head or gettext.NullTranslations()


# ── 처음 정하는 값 (SOT §4) ───────────────────────────────────────────────
def _registry_install_language() -> str:
    """설치 프로그램이 남긴 `HKLM\\Software\\PolyPDF\\InstallLanguage`(SOT §10). 없으면 ""."""
    if not sys.platform.startswith("win"):
        return ""
    try:
        import winreg
    except Exception:
        return ""
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\PolyPDF", 0,
                                winreg.KEY_READ | view) as k:
                v, _t = winreg.QueryValueEx(k, "InstallLanguage")
                if v:
                    return normalize(v)
        except OSError:
            continue
    return ""


def _os_languages() -> list:
    try:
        from PyQt6.QtCore import QLocale
        return [normalize(x) for x in QLocale.system().uiLanguages()]
    except Exception:
        return []


def initial_language(settings_existed: bool, os_languages=None, install_language=None) -> str:
    """설정에 언어가 없을 때 처음 정하는 값(SOT §4):
    ① 설정 파일이 이미 있으면 ko(이 기능 전 설치본은 모두 한국어 — 업데이트로 바뀌면 안 된다)
    ② 설치 프로그램이 남긴 언어(그 팩이 있을 때) ③ OS 화면 언어 목록을 팩과 맞춤(같은 코드 → 주 언어)
    ④ en(팩이 있으면) → ko."""
    if settings_existed:
        return KO
    have = {c for c, _n, _s in available_languages()}
    inst = normalize(install_language if install_language is not None else _registry_install_language())
    if inst and inst in have:
        return inst
    for c in (os_languages if os_languages is not None else _os_languages()):
        c = normalize(c)
        if c in have:
            return c
        if c.split("_")[0] in have:
            return c.split("_")[0]
    return "en" if "en" in have else KO


# ── 설치 (시작 때 한 번) ──────────────────────────────────────────────────
def _install_qt(app, code: str, meta) -> None:
    global _qt_translator
    qm = (meta or {}).get("qt") or ""
    if not qm or app is None:
        return
    try:
        from PyQt6.QtCore import QTranslator, QLibraryInfo
        dirs = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)]
        try:                       # 배포본에서 Qt 경로를 못 얻을 때 대비 — PyQt6 패키지 안의 번역 폴더
            import PyQt6
            dirs.append(str(Path(PyQt6.__file__).resolve().parent / "Qt6" / "translations"))
        except Exception:
            pass
        t = QTranslator(app)
        for tdir in dirs:
            if tdir and t.load(qm, tdir):
                app.installTranslator(t)
                _qt_translator = t
                return
        _log.info("Qt 기본 번역을 찾지 못함: %s (%s)", qm, dirs)
    except Exception as e:
        _log.info("Qt 기본 번역 설치 실패: %s", e)


def install(app=None, code: str = None) -> str:
    """언어를 정하고 번역을 설치한다. `POLYPDF_LANG` 이 있으면 그것이 먼저(SOT §3.6).
    고른 언어의 팩이 없으면 en → ko 로 물러난다(설정 값은 바꾸지 않는다, SOT §3.4). 정한 코드를 돌려준다."""
    global _lang, _trans
    want = normalize(os.environ.get(ENV) or code or KO)
    if want != KO and want != PSEUDO and _read_meta(want) is None:
        _log.warning("언어팩이 없어 물러남: %s", want)
        want = "en" if _read_meta("en") else KO
    _lang = want
    _trans = gettext.NullTranslations() if want == KO else _translations_for(_chain(want))
    _install_qt(app, want, _read_meta(want) if want != PSEUDO else None)
    return _lang
