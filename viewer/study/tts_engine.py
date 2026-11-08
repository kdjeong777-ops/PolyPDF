"""읽기 엔진 고르기 — SAPI(Windows 기본 음성) / 자연 음성(Supertonic) (영상·음성 SOT §1.10, 261108-28).

설정 `tts_voice` = {'engine': 'auto'|'sapi'|'neural', 'sid': 0~9, 'quality': 'fast'|'high'}.
- auto(기본): 자연 음성 구성요소(모델)가 있고 엔진(sherpa_onnx)이 있으면 자연 음성, 아니면 SAPI.
- neural: 자연 음성 — 없거나 실패하면 SAPI 로 물러선다(읽기가 멈추지 않게).
- sapi: 늘 SAPI.
모델이 있는지(파일 몇 개) 는 처음 한 번만 보고 기억한다 — 구성요소를 설치·지우면 `invalidate()`.
"""
from __future__ import annotations

from viewer.i18n import tr

ENGINES = ("auto", "sapi", "neural")
QUALITIES = ("fast", "high")
SPEAKERS = 10
# 261108-33: 미리 듣기 기본 글 — 한 줄씩(한국어·영어). 자연 음성은 둘 다, Windows 성우는 그 언어 줄만 읽는다
DEFAULT_SAMPLE = "안녕하세요. 이 목소리로 본문을 읽어 드립니다.\nHello. This voice will read the document for you."
DEFAULT = {"engine": "auto", "sid": 0, "quality": "fast", "normalize": True, "split_lang": True,
           "names": [""] * SPEAKERS, "hidden_sapi": [], "sample": ""}

_ready = None          # 자연 음성을 쓸 수 있나(엔진+모델) — 처음 한 번 본다


def normalize_cfg(v) -> dict:
    v = dict(v or {}) if isinstance(v, dict) else {}
    eng = v.get("engine") if v.get("engine") in ENGINES else DEFAULT["engine"]
    try:
        sid = max(0, min(9, int(v.get("sid", 0))))
    except (TypeError, ValueError):
        sid = 0
    q = v.get("quality") if v.get("quality") in QUALITIES else DEFAULT["quality"]
    # 261108-28: 자연 음성 앞단 — 사용자가 들어 보고 고른다(기본 둘 다 켬, 영상·음성 SOT §1.10 '앞단')
    nz = bool(v.get("normalize", DEFAULT["normalize"]))
    sl = bool(v.get("split_lang", DEFAULT["split_lang"]))
    # 261108-33: 자연 음성 목소리 이름(빈칸 = '목소리 N') · 쓰지 않는 Windows 성우 · 미리 듣기 글(빈칸 = 기본)
    names = [str(x or "").strip()[:40] for x in list(v.get("names") or [])[:SPEAKERS]]
    names += [""] * (SPEAKERS - len(names))
    hidden = sorted({str(x) for x in (v.get("hidden_sapi") or []) if str(x).strip()})
    sample = str(v.get("sample") or "")[:500]
    return {"engine": eng, "sid": sid, "quality": q, "normalize": nz, "split_lang": sl,
            "names": names, "hidden_sapi": hidden, "sample": sample}


def voice_label(cfg: dict, sid: int) -> str:
    """자연 음성 목소리 이름 — 사용자가 붙인 이름, 없으면 중립 '목소리 N'(▾ 메뉴·환경설정·mp3 메모 모두 이 값)."""
    c = normalize_cfg(cfg)
    try:
        nm = c["names"][int(sid)]
    except (IndexError, ValueError, TypeError):
        nm = ""
    return nm or tr("목소리 {n}").format(n=int(sid) + 1)


def sample_text(cfg: dict) -> str:
    return normalize_cfg(cfg)["sample"].strip() or DEFAULT_SAMPLE


def set_sid(mw, sid: int) -> None:
    """261108-33: ▾ 메뉴에서 자연 음성 목소리를 고르면 설정 `tts_voice.sid` 를 바꾼다 — 환경설정 '목소리' 와 같은 값 하나."""
    prefs = getattr(mw, "_prefs", None)
    if not isinstance(prefs, dict):
        return
    tv = dict(prefs.get("tts_voice") or {})
    tv["sid"] = max(0, min(SPEAKERS - 1, int(sid)))
    prefs["tts_voice"] = tv
    c = normalize_cfg(tv)
    r = getattr(mw, "_neural_reader", None)
    if r is not None:
        r.configure(c["sid"], c["quality"], c["normalize"], c["split_lang"])
    save = getattr(mw, "_save_settings_now", None)
    if callable(save):
        try:
            save()
        except Exception:
            pass


def apply_sapi_hidden(mw, tts) -> None:
    """SAPI 엔진에 '쓰지 않음' 성우를 알린다(목록·언어별 기본 음성에서 뺀다)."""
    try:
        tts.set_hidden(cfg_of(mw)["hidden_sapi"])
    except Exception:
        pass


def cfg_of(mw) -> dict:
    try:
        return normalize_cfg((getattr(mw, "_prefs", None) or {}).get("tts_voice"))
    except Exception:
        return dict(DEFAULT)


def neural_ready() -> bool:
    global _ready
    if _ready is None:
        from viewer.study import neural_tts
        _ready = bool(neural_tts.engine_importable() and neural_tts.model_ready())
    return _ready


def invalidate():
    global _ready
    _ready = None


def wants_neural(cfg: dict) -> bool:
    eng = normalize_cfg(cfg)["engine"]
    return eng != "sapi" and neural_ready()


def reader_for(mw):
    """본문 읽기가 쓸 엔진 — 자연 음성이면 `NeuralReader`(창마다 하나, 다시 씀), 아니면 SAPI(`mw._study_get_tts()`)."""
    c = cfg_of(mw)
    if wants_neural(c):
        r = getattr(mw, "_neural_reader", None)
        if r is None:
            from viewer.study.neural_tts import NeuralReader
            r = NeuralReader(mw, sid=c["sid"], quality=c["quality"])
            mw._neural_reader = r
        r.configure(c["sid"], c["quality"], c["normalize"], c["split_lang"])
        if r.available():
            return r
    return mw._study_get_tts()


def export_choice(mw) -> dict:
    """mp3 저장(배경 일꾼)에 넘길 값 — 그 자리에서 엔진을 고른다(일꾼은 창을 모른다)."""
    c = cfg_of(mw)
    return {"neural": wants_neural(c), "sid": c["sid"], "quality": c["quality"],
            "normalize": c["normalize"], "split_lang": c["split_lang"],
            "voice_label": voice_label(c, c["sid"]), "hidden_sapi": list(c["hidden_sapi"])}
