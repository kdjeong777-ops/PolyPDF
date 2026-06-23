"""요약 + 서지(APA) 생성 (P3) — Claude 활용.

SOT: `PDF 번역·요약 작업 계획서.md` §8(요약)·§9.0(서지 APA).
- 요약: 정제 본문에서 Abstract·Results·Conclusion 발췌 → Claude 가 근거 한정 한국어 요약.
- 서지: 1면 텍스트 → Claude 가 이 논문 자체를 APA 7판 참고문헌 형식으로 작성.
- assemble(): 산출물 순서(서지 → 2줄 → 요약 → 전문)로 텍스트 조립(P4 에서 Word/PDF 로 포맷).
"""
from __future__ import annotations

import re

_SEP = "\n\n" + "─" * 24 + " 전문 번역 " + "─" * 24 + "\n\n"


def extract_sections(text: str) -> dict:
    """초록/결과/결론 발췌(휴리스틱). 정제 본문 기준."""
    t = text or ""
    out = {"abstract": "", "results": "", "conclusion": ""}
    m = re.search(r"\bAbstract\b(.*?)(?:\bKeywords\b|\bIntroduction\b|\n\s*1[\.\s]|\Z)",
                  t, re.I | re.S)
    if m:
        out["abstract"] = m.group(1).strip()[:4000]
    m = re.search(r"\bResults(?:\s+and\s+Discussion)?\b(.*?)(?:\bConclusion|\bReferences\b|\Z)",
                  t, re.I | re.S)
    if m:
        out["results"] = m.group(1).strip()[:3000]
    m = re.search(r"\bConclusions?\b(.*?)(?:\bReferences\b|\bAcknowledg|\Z)", t, re.I | re.S)
    if m:
        out["conclusion"] = m.group(1).strip()[:4000]
    return out


def summarize_debug(key, text, model=None, auth="api"):
    """(요약 텍스트, [진단]). 초록·결과·결론에 근거한 한국어 요약."""
    from viewer.study import translate_api as tapi
    model = model or tapi.DEFAULT_MODEL
    if not tapi.available():
        return "", ["anthropic SDK 미설치"]
    if tapi._need_key_missing(key, auth):
        return "", ["API 키/로그인 없음"]
    secs = extract_sections(text)
    basis = "\n\n".join(f"[{k.upper()}]\n{v}" for k, v in secs.items() if v)
    if not basis.strip():
        basis = (text or "")[:6000]
    system = (
        "당신은 논문 전문 번역가입니다. 아래 발췌(초록·결과·결론)에 근거해 한국어로 핵심 요약을 "
        "작성하세요. 발췌에 없는 내용은 추측하지 마세요. 다음 구조로 작성합니다:\n"
        "■ 배경·목적\n■ 방법\n■ 주요 결과(핵심 수치 포함)\n■ 결론·시사점")
    try:
        c = tapi._client(key, auth)
        r = c.messages.create(model=model, max_tokens=2000, system=system,
                              messages=[{"role": "user", "content": basis}])
        txt = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
        if getattr(r, "stop_reason", "") == "refusal":
            return "", ["요약 요청이 거부되었습니다."]
        return txt.strip(), ["요약 ok"]
    except Exception as e:
        return "", [f"ERR {tapi._err_detail(e)}{tapi._auth_hint(e, auth)}"]


def citation_apa_debug(key, head_text, model=None, auth="api"):
    """(APA 참고문헌 한 줄, [진단]). 논문 1면 텍스트로 이 논문 자체를 APA 형식 작성."""
    from viewer.study import translate_api as tapi
    model = model or tapi.DEFAULT_MODEL
    if not tapi.available():
        return "", ["anthropic SDK 미설치"]
    if tapi._need_key_missing(key, auth):
        return "", ["API 키/로그인 없음"]
    if not (head_text or "").strip():
        return "", ["1면 텍스트 없음"]
    system = (
        "다음은 학술 논문의 첫 부분(제목·저자·서지정보)입니다. 이 논문 자체를 "
        "APA 7판 참고문헌 형식 한 항목으로 작성하세요. 형식: "
        "저자(성, 이니셜.; 여러 명은 APA 규칙), (년도). 논문 제목. 저널명, 권(호), 시작–끝쪽. "
        "https://doi.org/.... 확인되지 않는 항목은 생략. 설명 없이 참고문헌 한 줄만 출력하세요.")
    try:
        c = tapi._client(key, auth)
        r = c.messages.create(model=model, max_tokens=600, system=system,
                              messages=[{"role": "user", "content": head_text[:3000]}])
        txt = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
        return txt.strip(), ["서지 ok"]
    except Exception as e:
        return "", [f"ERR {tapi._err_detail(e)}{tapi._auth_hint(e, auth)}"]


def translate_captions(key, captions, model=None, auth="api"):
    """그림/표 캡션 리스트 → 한국어 리스트(입력 순서·개수 유지, 1회 호출). 실패 시 빈 문자열."""
    from viewer.study import translate_api as tapi
    import json
    model = model or tapi.DEFAULT_MODEL
    caps = list(captions or [])
    if not caps:
        return []
    if not tapi.available() or tapi._need_key_missing(key, auth) \
            or not any((c or "").strip() for c in caps):
        return [""] * len(caps)
    system = ("다음 그림/표 캡션들을 한국어로 번역하세요. 'Figure/Table N' 같은 번호·라벨은 "
              "그대로 유지하고 제목만 번역. 입력 순서대로 동일 개수의 항목을 반환하세요.")
    schema = {"type": "object", "properties": {
        "items": {"type": "array", "items": {"type": "string"}}},
        "required": ["items"], "additionalProperties": False}
    payload = "\n".join(f"{i+1}. {c}" for i, c in enumerate(caps))
    try:
        c = tapi._client(key, auth)
        r = c.messages.create(model=model, max_tokens=3000, system=system,
                              output_config={"format": {"type": "json_schema", "schema": schema}},
                              messages=[{"role": "user", "content": payload}])
        txt = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
        items = (json.loads(txt) if txt else {}).get("items") or []
        return [(items[i] if i < len(items) else "") for i in range(len(caps))]
    except Exception:
        return [""] * len(caps)


def assemble(citation: str, summary: str, translation: str) -> str:
    """산출물 순서: 서지 → (2줄) 요약 → (구분) 전문 번역."""
    parts = []
    if (citation or "").strip():
        parts.append(citation.strip())
    if (summary or "").strip():
        parts.append("\n■ 요약\n" + summary.strip())
    body = "\n\n".join(parts)
    return (body + _SEP + (translation or "").strip()) if body else (translation or "").strip()
