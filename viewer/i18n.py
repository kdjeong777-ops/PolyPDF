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
import re
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
_external = False                          # 외부 언어팩 사용(설정 `external_language_packs`, SOT §3.4 — 기본 꺼짐)
_fallback_from = ""                        # 고른 언어의 팩이 없어 물러났으면 그 코드(상태줄에 한 번 알린다)
_PH = re.compile(r"\{[^{}]*\}|%[sd]")      # 자리표시 — 번역과 원문의 집합이 같아야 한다(SOT §3.2)


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


def external_dir() -> Path:
    """외부 언어팩 폴더 `%APPDATA%\\LocalTools\\PolyPDF\\locale`(설정 폴더 아래, SOT §3.4). 앱 이름을 정한 뒤 부른다."""
    try:
        from viewer.settings_store import settings_dir
        return Path(settings_dir()) / "locale"
    except Exception:
        return Path()


def _pack_root(code: str) -> Path:
    """그 언어의 팩 폴더 — 외부 팩을 켰고 쓸 수 있으면 외부(내장을 덮는다), 아니면 내장."""
    if _external and code not in (KO, PSEUDO):
        ext = external_dir() / code
        if (ext / "pack.json").is_file():
            if _valid_meta(_load_meta_file(ext / "pack.json"), code) and \
                    _mo_ok(ext / "LC_MESSAGES" / (DOMAIN + ".mo")):
                return ext
            _log.warning("외부 언어팩이 올바르지 않아 무시(내장을 쓴다): %s", ext)
    return pack_dir() / code


def _mo_ok(mo: Path) -> bool:
    """외부 팩의 .mo 가 있고 gettext 로 읽힌다(깨진 파일이면 그 팩을 쓰지 않는다)."""
    key = str(mo)
    if key not in _mo_checked:
        try:
            with open(mo, "rb") as f:
                gettext.GNUTranslations(f)
            _mo_checked[key] = True
        except Exception:
            _mo_checked[key] = False
    return _mo_checked[key]


_mo_checked = {}


def _load_meta_file(f: Path):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def _valid_meta(meta, code: str) -> bool:
    """pack.json 형식(SOT §3.2) — 사전·코드=폴더·이름·방향(ltr)·대체 사슬은 코드 목록."""
    if not isinstance(meta, dict) or normalize(meta.get("code", "")) != code or not meta.get("name"):
        return False
    if str(meta.get("direction", "ltr")).lower() != "ltr":
        return False
    fb = meta.get("fallback", [])
    return isinstance(fb, list) and all(isinstance(x, str) for x in fb)


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
    f = _pack_root(code) / "pack.json"
    meta = _load_meta_file(f)
    if meta is None:
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
    names = set()
    for root in ([pack_dir()] + ([external_dir()] if _external else [])):
        try:
            names |= {d.name for d in root.iterdir() if d.is_dir()}
        except Exception:
            pass
    dirs = sorted(names)
    for code in dirs:
        if code in (KO, PSEUDO) or normalize(code) != code:
            continue
        meta = _read_meta(code)
        if meta:
            out.append((code, str(meta["name"]), str(meta.get("status", "partial"))))
    return out


# ── 번역 ──────────────────────────────────────────────────────────────────
def tr(text: str) -> str:
    """화면 문구. `text` = 한국어 원문(키). 번역이 없으면 원문.
    빈 글자는 그대로 — gettext 는 빈 키에 .mo 머리(메타데이터)를 돌려준다(`tr(변수)` 가 빈 값일 때)."""
    if not text:
        return text
    return _safe(text, _trans.gettext(text))


def trp(context: str, text: str) -> str:
    """문맥이 다른 같은 원문(msgctxt)."""
    return _safe(text, _trans.pgettext(context, text))


def trn(text: str, n: int) -> str:
    """수에 따라 꼴이 바뀌는 문구 — 한국어 원문은 한 꼴이라 단·복수 키가 같다."""
    return _safe(text, _trans.ngettext(text, text, int(n)))


def _safe(src: str, out: str) -> str:
    """번역의 자리표시가 원문과 다르면 원문을 돌려준다 — 쓰는 곳의 `.format()` 이 KeyError 로
    창을 깨지 않게(외부 언어팩·검사를 거치지 않은 팩, SOT §3.2·§3.4). 같으면 번역 그대로."""
    if out is src or out == src:
        return out
    try:
        ok = _ph_cache[(src, out)]
    except KeyError:
        ok = sorted(_PH.findall(src)) == sorted(_PH.findall(out))
        if not ok:
            _log.warning("번역의 자리표시가 원문과 달라 원문을 쓴다: %r", src[:60])
        if len(_ph_cache) > 20000:
            _ph_cache.clear()
        _ph_cache[(src, out)] = ok
    return out if ok else src


_ph_cache = {}


def fallback_from() -> str:
    """고른 언어의 팩을 찾지 못해 물러났으면 그 코드(없으면 ""). 창이 상태줄에 한 번 알린다(SOT §3.4)."""
    return _fallback_from


def external_enabled() -> bool:
    return _external


def tr_noop(text: str) -> str:
    """추출만 표시 — 불러오는 시점에는 번역하지 않는다(쓰는 곳에서 `tr`)."""
    return text


def language() -> str:
    return _lang


def korea_only_visible() -> bool:
    """한국 전용 기능(법령·KCSC·KIPO·영어단어 학습·영→한 번역과 사전 관리)을 보일지 — SOT §7."""
    return _lang == KO


def korea_only(fn):
    """한국 전용 기능의 처리기 — 한국어가 아니면 아무것도 하지 않는다(SOT §7).
    메뉴·단추를 숨겨도 단축키·우클릭·자동 후속 작업(병합 뒤 단어장 등)이 처리기를 부를 수 있어
    **처리기 자체**를 막는다."""
    import functools

    @functools.wraps(fn)
    def _guarded(*a, **k):
        if not korea_only_visible():
            return None
        return fn(*a, **k)
    _guarded.korea_only = True
    return _guarded


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


def resource_chain() -> list:
    """언어별 리소스(도움말 등)를 찾을 차례 — 지금 언어 → fallback → 한국어(원문). SOT §8.
    예: `for c in resource_chain(): resources/help/help_<c>.html` 이 있으면 그것."""
    out = _chain(_lang) if _lang != KO else []
    return out + [KO]


def _translations_for(codes: list):
    """사슬의 `.mo` 들을 add_fallback 으로 잇는다. 하나도 없으면 NullTranslations."""
    head = None
    for c in codes:
        mo = _pack_root(c) / "LC_MESSAGES" / (DOMAIN + ".mo")
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


def install(app=None, code: str = None, external: bool = None) -> str:
    """언어를 정하고 번역을 설치한다. `POLYPDF_LANG` 이 있으면 그것이 먼저(SOT §3.6).
    고른 언어의 팩이 없으면 en → ko 로 물러난다(설정 값은 바꾸지 않는다, SOT §3.4). 정한 코드를 돌려준다."""
    global _lang, _trans, _external, _fallback_from
    if external is None:                       # 설정 `external_language_packs`(SOT §3.4 — 기본 꺼짐)
        try:
            from viewer.settings_store import peek_pref
            external = bool(peek_pref("external_language_packs"))
        except Exception:
            external = False
    _external = bool(external)
    _ph_cache.clear()
    _mo_checked.clear()
    want = normalize(os.environ.get(ENV) or code or KO)
    _fallback_from = ""
    if want != KO and want != PSEUDO and _read_meta(want) is None:
        _log.warning("언어팩이 없어 물러남: %s", want)
        _fallback_from = want
        want = "en" if _read_meta("en") else KO
    _lang = want
    _trans = gettext.NullTranslations() if want == KO else _translations_for(_chain(want))
    _install_qt(app, want, _read_meta(want) if want != PSEUDO else None)
    return _lang
