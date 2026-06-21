"""인터넷 사전 조회(선택) — 계획서 §9.3 P11.

옵션 '인터넷 사전 포함'이 켜졌을 때만 호출. 표준 라이브러리(urllib)만 사용.
- Free Dictionary API(dictionaryapi.dev): 영어 뜻·예문·발음. 키 불필요. (Wiktionary CC BY-SA)
- 표준국어대사전 OpenAPI: 한국어 뜻. 사용자 무료 키 필요.
- 우리말샘 OpenAPI: 한국어 뜻. 사용자 무료 키 필요.
- Tatoeba: 한·영 예문. 키 불필요.
각 함수는 실패 시 빈 결과를 돌려준다(예외 전파 안 함). 반환:
  {"def_ko": [..], "def_en": [..], "examples": [{"text","ref"}], "source": "표시명"}
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

_UA = "PolyPDF/1.0 (educational dictionary)"


def _get_json(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _strip_tags(s: str) -> str:
    """260615-16: HTML 엔티티(&#44; &lt; 등) 복원 → 태그 제거 → 공백 정리.
    (우리말샘/온용어/표준국어대사전 정의에 섞인 꾸밈 마크업 제거)"""
    import html as _html
    t = _html.unescape(str(s or ""))      # &#44;→',', &lt;strong&gt;→<strong>
    t = re.sub(r"<[^>]+>", "", t)          # 태그 제거
    return re.sub(r"\s+", " ", t).strip()


def free_dictionary(word: str, timeout: float = 8.0) -> dict:
    """영어 단어 → 뜻(영어)·예문. dictionaryapi.dev (키 불필요)."""
    out = {"def_ko": [], "def_en": [], "examples": [], "source": "Free Dictionary"}
    try:
        url = ("https://api.dictionaryapi.dev/api/v2/entries/en/"
               + urllib.parse.quote(word))
        data = _get_json(url, timeout)
        for entry in (data or [])[:2]:
            for m in entry.get("meanings", []):
                for d in m.get("definitions", [])[:3]:
                    de = (d.get("definition") or "").strip()
                    if de and de not in out["def_en"]:
                        out["def_en"].append(de)
                    ex = (d.get("example") or "").strip()
                    if ex:
                        out["examples"].append({"text": ex, "ref": "Free Dictionary"})
    except Exception:
        pass
    return out


def stdict(word: str, key: str, timeout: float = 8.0) -> dict:
    """한국어 단어 → 뜻. 표준국어대사전 OpenAPI(사용자 키)."""
    out = {"def_ko": [], "def_en": [], "examples": [], "source": "표준국어대사전"}
    if not key:
        return out
    try:
        url = ("https://stdict.korean.go.kr/api/search.do?"
               + urllib.parse.urlencode({"key": key, "q": word,
                                         "req_type": "json", "num": 5}))
        data = _get_json(url, timeout)
        items = (data.get("channel", {}) or {}).get("item", []) or []
        if isinstance(items, dict):
            items = [items]
        for it in items[:5]:
            sense = it.get("sense", {})
            if isinstance(sense, list):
                sense = sense[0] if sense else {}
            de = _strip_tags(sense.get("definition", ""))
            if de and de not in out["def_ko"]:
                out["def_ko"].append(de)
    except Exception:
        pass
    return out


def urimalsaem(word: str, key: str, timeout: float = 8.0) -> dict:
    """한국어 단어 → 뜻·예문. 우리말샘 OpenAPI(사용자 키)."""
    out = {"def_ko": [], "def_en": [], "examples": [], "source": "우리말샘"}
    if not key:
        return out
    try:
        url = ("https://opendict.korean.go.kr/api/search?"
               + urllib.parse.urlencode({"key": key, "q": word,
                                         "req_type": "json", "num": 5}))
        data = _get_json(url, timeout)
        items = (data.get("channel", {}) or {}).get("item", []) or []
        if isinstance(items, dict):
            items = [items]
        for it in items[:5]:
            senses = it.get("sense", [])
            if isinstance(senses, dict):
                senses = [senses]
            for s in senses[:2]:
                de = _strip_tags(s.get("definition", ""))
                if de and de not in out["def_ko"]:
                    out["def_ko"].append(de)
    except Exception:
        pass
    return out


def onterm(word: str, key: str, timeout: float = 8.0) -> dict:
    """한국어 전문용어 → 뜻·분야. 국립국어원 '온용어' OpenAPI(사용자 키).
    엔드포인트: kli.korean.go.kr/term/api/search.do (key/apiSearchWord/num/sort)."""
    # by_glossary: {용어집이름: {"def_ko":[...],"def_en":[...],"examples":[...],"hanja":""}} — 260615-19
    out = {"def_ko": [], "def_en": [], "examples": [], "hanja": "",
           "source": "온용어", "by_glossary": {}}
    if not key:
        return out
    url = ("https://kli.korean.go.kr/term/api/search.do?"
           + urllib.parse.urlencode({"key": key, "apiSearchWord": word,
                                     "start": 1, "num": 30, "sort": "wt"}))
    try:
        data = _get_json(url, timeout)
    except Exception:
        return out
    # 구조: channel.return_object[].resultlist[].{word,definition,use_ex,glossary,...}
    ch = data.get("channel", data) if isinstance(data, dict) else {}
    ro = ch.get("return_object", [])
    if isinstance(ro, dict):
        ro = [ro]
    items = []
    for blk in (ro or []):
        rl = (blk or {}).get("resultlist", [])
        if isinstance(rl, dict):
            rl = [rl]
        items.extend(rl or [])
    if not items:      # 폴백: 다른 형태(item/resultlist 직접)
        rl = ch.get("resultlist") or ch.get("item") or []
        items = rl if isinstance(rl, list) else [rl] if rl else []
    for it in items[:30]:
        if not isinstance(it, dict):
            continue
        de = _strip_tags(it.get("definition", "") or "")
        ex = _strip_tags(it.get("use_ex", "") or "")        # 사용예시 → 예시
        origin = _strip_tags(it.get("origin", "") or "")     # 원어
        # 260615-21/22: origin 이 영어(라틴)면 영어뜻, 한자(CJK)면 '한자' 필드로
        origin_en = origin if re.search(r"[A-Za-z]", origin) else ""
        origin_hanja = (origin if (re.search(r"[㐀-鿿豈-﫿]", origin)
                                   and not origin_en) else "")
        gloss = _strip_tags(it.get("glossary", "") or "") or "기타"
        g = out["by_glossary"].setdefault(
            gloss, {"def_ko": [], "def_en": [], "examples": [], "hanja": ""})
        if de and de not in g["def_ko"]:
            g["def_ko"].append(de)
        if origin_en and origin_en not in g["def_en"]:
            g["def_en"].append(origin_en)
        if origin_hanja and not g["hanja"]:
            g["hanja"] = origin_hanja
        if ex:
            g["examples"].append({"text": ex, "ref": f"온용어-{gloss}"})
        if de and de not in out["def_ko"]:      # 병합본(back-compat)
            out["def_ko"].append(de)
        if origin_en and origin_en not in out["def_en"]:
            out["def_en"].append(origin_en)
        if origin_hanja and not out["hanja"]:
            out["hanja"] = origin_hanja
        if ex:
            out["examples"].append({"text": ex, "ref": "온용어"})
    return out


def tatoeba(word: str, lang: str = "eng", timeout: float = 8.0) -> dict:
    """예문 — Tatoeba(키 불필요). lang: 'eng'|'kor'."""
    out = {"def_ko": [], "def_en": [], "examples": [], "source": "Tatoeba"}
    try:
        url = ("https://api.tatoeba.org/unstable/sentences?"
               + urllib.parse.urlencode({"lang": lang, "q": word, "limit": 3}))
        data = _get_json(url, timeout)
        for s in (data.get("data", []) or [])[:3]:
            t = (s.get("text") or "").strip()
            if t:
                out["examples"].append({"text": t, "ref": "Tatoeba (CC BY)"})
    except Exception:
        pass
    return out


# 260615-18: 인터넷 사전 출처(제공처)별 분류 — source_id: (출처명, 전문용어집 여부)
ONLINE_PROVIDERS = {
    "online_onterm":      ("온용어", True),
    "online_stdict":      ("표준국어대사전", False),
    "online_urimalsaem":  ("우리말샘", False),
    "online_freedict":    ("Free Dictionary", False),
    "online_tatoeba":     ("Tatoeba", False),
}
# 기존 캐시(reference) 의 표시명 → source_id (재분류용)
ONLINE_NAME2ID = {name: sid for sid, (name, _tb) in ONLINE_PROVIDERS.items()}


def _gloss_sid(gloss: str) -> str:
    """260615-19: 온용어 용어집 이름 → 안정적 source_id."""
    import hashlib
    return "online_onterm__" + hashlib.md5(str(gloss).encode("utf-8")).hexdigest()[:8]


def lookup_sources(term_ko: str, term_en: str, *, prefs: dict) -> list:
    """260615-18/19: 제공처별 결과 — [{source_id,name,is_termbase,def_ko,def_en,examples}].
    온용어는 'glossary'(용어집 이름)별로 '온용어-<용어집>' 출처로 세분(개별 선택 가능)."""
    if not prefs.get("online_dict_enabled"):
        return []
    found: dict = {}

    def add(sid, name, tb, def_ko=None, def_en=None, examples=None, hanja=""):
        d = found.setdefault(
            sid, {"name": name, "is_termbase": tb,
                  "def_ko": [], "def_en": [], "examples": [], "hanja": ""})
        for v in (def_ko or []):
            if v not in d["def_ko"]:
                d["def_ko"].append(v)
        for v in (def_en or []):
            if v not in d["def_en"]:
                d["def_en"].append(v)
        for ex in (examples or []):
            if ex not in d["examples"]:
                d["examples"].append(ex)
        if hanja and not d["hanja"]:
            d["hanja"] = hanja

    en = (term_en or "").strip()
    ko = (term_ko or "").strip()
    if en:
        r = free_dictionary(en)
        add("online_freedict", "Free Dictionary", False,
            r["def_ko"], r["def_en"], r["examples"])
        add("online_tatoeba", "Tatoeba", False, examples=tatoeba(en, "eng")["examples"])
    if ko:
        r = stdict(ko, prefs.get("stdict_key", ""))
        add("online_stdict", "표준국어대사전", False, r["def_ko"], examples=r["examples"])
        r = urimalsaem(ko, prefs.get("urimalsaem_key", ""))
        add("online_urimalsaem", "우리말샘", False, r["def_ko"], examples=r["examples"])
        ot = onterm(ko, prefs.get("onterm_key", ""))
        bg = ot.get("by_glossary") or {}
        if bg:                       # 용어집별로 세분
            for gloss, gd in bg.items():
                add(_gloss_sid(gloss), f"온용어-{gloss}", True,
                    gd.get("def_ko"), gd.get("def_en"), gd.get("examples"),
                    hanja=gd.get("hanja", ""))
        elif ot.get("def_ko") or ot.get("def_en") or ot.get("examples"):
            add("online_onterm", "온용어", True, ot["def_ko"], ot.get("def_en"),
                ot["examples"], hanja=ot.get("hanja", ""))
        add("online_tatoeba", "Tatoeba", False, examples=tatoeba(ko, "kor")["examples"])
    out = []
    for sid, d in found.items():
        if d["def_ko"] or d["def_en"] or d["examples"]:
            out.append({"source_id": sid, **d})
    return out


def lookup_all(term_ko: str, term_en: str, *, prefs: dict) -> dict:
    """옵션/키에 따라 사용 가능한 인터넷 사전을 모아 조회·병합.
    prefs: {online_dict_enabled, urimalsaem_key, stdict_key}."""
    merged = {"def_ko": [], "def_en": [], "examples": [], "sources": []}
    if not prefs.get("online_dict_enabled"):
        return merged
    parts = []
    if (term_en or "").strip():
        parts.append(free_dictionary(term_en.strip()))
        parts.append(tatoeba(term_en.strip(), "eng"))
    if (term_ko or "").strip():
        parts.append(stdict(term_ko.strip(), prefs.get("stdict_key", "")))
        parts.append(urimalsaem(term_ko.strip(), prefs.get("urimalsaem_key", "")))
        parts.append(onterm(term_ko.strip(), prefs.get("onterm_key", "")))
        parts.append(tatoeba(term_ko.strip(), "kor"))
    for p in parts:
        for k in ("def_ko", "def_en"):
            for v in p.get(k, []):
                if v not in merged[k]:
                    merged[k].append(v)
        for ex in p.get("examples", []):
            if ex not in merged["examples"]:
                merged["examples"].append(ex)
        if (p.get("def_ko") or p.get("def_en") or p.get("examples")) \
                and p.get("source") and p["source"] not in merged["sources"]:
            merged["sources"].append(p["source"])
    return merged


def verify_provider_debug(provider: str, key: str, timeout: float = 8.0):
    """(성공여부, 메시지). 한국어 사전 키 확인 — 공통어 조회."""
    key = (key or "").strip()
    if not key:
        return False, "키 없음"
    word = "도로" if provider == "onterm" else "물"
    try:
        if provider == "stdict":
            r = stdict(word, key, timeout)
        elif provider == "urimal":
            r = urimalsaem(word, key, timeout)
        elif provider == "onterm":
            r = onterm(word, key, timeout)
        else:
            return False, "알 수 없는 제공자"
    except Exception as e:
        return False, f"오류: {str(e)[:80]}"
    if r.get("def_ko"):
        return True, "정상"
    return False, "결과 없음 — 키 확인 필요"
