"""PDF 번역·요약 — Claude(Anthropic) 호출 (P0: 최소 번역·토큰카운트).

SOT: `PDF 번역·요약 작업 계획서.md`.
- 접근: 사용자 API 키 + 공식 `anthropic` SDK (설정 → '번역(Claude)').
- 모델: claude-opus-4-8 기본 / claude-sonnet-4-6 / claude-haiku-4-5.
- 사고: adaptive, effort 조절. 긴 출력은 스트리밍.
- 용어집은 시스템 프롬프트 프리픽스로 주입(프롬프트 캐시) — P2 에서 본격 사용.
- 표준 라이브러리 외 의존성은 `anthropic`(빌드에 동봉). 미설치 환경에서도 import 는 되도록
  실제 호출 함수 안에서 지연 import 하고, 없으면 안내 메시지를 돌려준다.
"""
from __future__ import annotations

import re

DEFAULT_MODEL = "claude-opus-4-8"

# (id, 표시이름, 입력$/1M, 출력$/1M) — 비용 추정용(개략, 변동 가능)
MODELS = [
    ("claude-opus-4-8", "Claude Opus 4.8 (최고 품질·1M)", 5.0, 25.0),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (균형·절감)", 3.0, 15.0),
    ("claude-haiku-4-5", "Claude Haiku 4.5 (저가·간단)", 1.0, 5.0),
]

_PRICE = {m[0]: (m[2], m[3]) for m in MODELS}

_SYSTEM_BASE = (
    "당신은 도로·아스팔트 등 공학 분야의 전문 학술 번역가입니다. "
    "영문(또는 외국어) 학술 논문을 한국어로 정확하고 자연스럽게 번역합니다.\n"
    "규칙:\n"
    "① 제공된 용어집의 대역어가 있으면 반드시 그대로 사용한다.\n"
    "② 학술적 문체와 원문 의미를 보존한다(과도한 의역 금지).\n"
    "③ 수식·단위·인용 표기[N]·그림/표 번호·고유명사는 원형을 유지한다.\n"
    "④ 머리말·꼬리말·페이지번호 같은 반복 잡음은 무시하고 본문이 자연스럽게 이어지도록 번역한다.\n"
    "⑤ 한국어 번역문만 출력한다. 머리말·설명·메모를 덧붙이지 않는다.\n"
    "⑥ 【수식N】 형태의 토큰(예: 【수식1】)은 수식 자리표시자이다. 절대 번역·변형·삭제하지 말고 "
    "원래 위치에 그대로 한 줄로 둔다."
)


def available() -> bool:
    """anthropic SDK 사용 가능 여부."""
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def extract_pdf_text(path, max_pages: int = 0, max_chars: int = 0) -> str:
    """PDF 본문 텍스트 추출(P0 간이 — 머리말/꼬리말 제거·연결은 P1 `pdf_extract`).
    max_pages>0 면 앞쪽 그 페이지수만, max_chars>0 면 글자수 상한."""
    try:
        import fitz
        doc = fitz.open(str(path))
        n = doc.page_count if max_pages <= 0 else min(max_pages, doc.page_count)
        parts = [doc[i].get_text("text") for i in range(n)]
        doc.close()
        out = "\n".join(parts).strip()
        return out[:max_chars] if max_chars and max_chars > 0 else out
    except Exception:
        return ""


_OAUTH_BETA = "oauth-2025-04-20"


def _login_token(key: str = "") -> str:
    """로그인 모드 토큰: 사용자가 직접 넣은 값 우선, 없으면 ant(구독 로그인)에서 가져옴(자동 갱신)."""
    k = (key or "").strip()
    if k:
        return k
    try:
        from . import ant_cli
        return ant_cli.access_token()
    except Exception:
        return ""


def _client(key: str = "", auth: str = "api"):
    """auth='api' → API 키 / auth='login' → Claude 구독 로그인(OAuth).
    로그인 모드는 ant(`auth print-credentials`)에서 받은 액세스 토큰을 Bearer 로 사용하고
    /v1/messages 에 oauth 베타 헤더를 붙인다."""
    import anthropic
    if (auth or "api") == "login":
        kwargs = {"default_headers": {"anthropic-beta": _OAUTH_BETA}, "max_retries": 4}
        tok = _login_token(key)
        if tok:
            kwargs["auth_token"] = tok
        return anthropic.Anthropic(**kwargs)
    return anthropic.Anthropic(api_key=(key or "").strip(), max_retries=4)


def _need_key_missing(key: str, auth: str) -> bool:
    """api 모드에서만 키가 필수(login 모드는 프로필/토큰을 SDK 가 해석)."""
    return (auth or "api") != "login" and not (key or "").strip()


def _err_detail(e: Exception) -> str:
    """예외 + 하위 원인(__cause__/__context__) 체인을 드러내 진단을 돕는다."""
    parts = [f"{type(e).__name__}: {str(e)[:120]}"]
    c = getattr(e, "__cause__", None) or getattr(e, "__context__", None)
    seen = 0
    while c is not None and seen < 3:
        parts.append(f"← {type(c).__name__}: {str(c)[:120]}")
        nxt = getattr(c, "__cause__", None) or getattr(c, "__context__", None)
        c = nxt if nxt is not c else None
        seen += 1
    return "  ".join(parts)


def _auth_hint(e: Exception, auth: str) -> str:
    """오류 메시지에 인증 모드별 안내 덧붙임."""
    name = type(e).__name__
    s = str(e).lower()
    if "APIConnection" in name or "connection error" in s or "connecterror" in s:
        return ("네트워크 연결 오류 — api.anthropic.com 에 접속하지 못했습니다. "
                "인터넷·VPN·프록시·방화벽/백신(PolyPDF.exe 의 인터넷 접속 차단)을 확인하고 "
                "다시 시도하세요.")
    if "credit balance" in s or "credit" in s and "low" in s:
        return (" → API 크레딧 부족입니다. console.anthropic.com → Billing 에서 크레딧을 "
                "충전하세요. (Claude 구독(Pro/Max)은 API 사용에 적용되지 않습니다.)")
    if (auth or "api") == "login" and (
            "resolve" in s or "credential" in s or "auth" in s or "api_key" in s
            or "Authentication" in name):
        return " (Claude 로그인 필요 — 설정 → '번역(Claude)' 의 [Claude 로그인] 버튼)"
    if "Authentication" in name:
        return " (API 키를 확인하세요)"
    if "RateLimit" in name:
        return " (속도 제한 — 잠시 후 다시 시도)"
    if "PermissionDenied" in name:
        return " (이 모델 사용 권한이 없습니다)"
    return ""


def _glossary_block(glossary) -> str:
    if not glossary:
        return ""
    lines = []
    for g in glossary:
        en = (g.get("en") or "").strip()
        ko = (g.get("ko") or "").strip()
        if en and ko:
            note = (g.get("note") or "").strip()
            lines.append(f"- {en} → {ko}" + (f"  ({note})" if note else ""))
    if not lines:
        return ""
    return "다음 용어는 반드시 이 대역어로 번역하세요(용어집):\n" + "\n".join(lines)


def _system(glossary):
    """system 프롬프트 블록. 용어집을 캐시 가능한 프리픽스로 둔다."""
    gb = _glossary_block(glossary)
    blocks = [{"type": "text", "text": _SYSTEM_BASE}]
    if gb:
        blocks.append({"type": "text", "text": gb, "cache_control": {"type": "ephemeral"}})
    else:
        blocks[0]["cache_control"] = {"type": "ephemeral"}
    return blocks


def estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    pin, pout = _PRICE.get(model, _PRICE[DEFAULT_MODEL])
    return (in_tokens / 1_000_000.0) * pin + (out_tokens / 1_000_000.0) * pout


def count_tokens_debug(key: str, text: str, model: str = DEFAULT_MODEL,
                       glossary=None, auth: str = "api"):
    """(입력토큰수, [진단]). 키/로그인 검증 겸용(인증 실패면 ERR)."""
    if not available():
        return -1, ["anthropic SDK 미설치 — 'pip install anthropic'"]
    if _need_key_missing(key, auth):
        return -1, ["API 키 없음 — 설정 → 번역(Claude)"]
    try:
        c = _client(key, auth)
        r = c.messages.count_tokens(
            model=model, system=_system(glossary),
            messages=[{"role": "user", "content": text or "x"}])
        n = int(r.input_tokens)
        return n, [f"입력 토큰 {n}"]
    except Exception as e:
        return -1, [f"ERR {_err_detail(e)}{_auth_hint(e, auth)}"]


def verify_auth_debug(key: str, model: str = DEFAULT_MODEL, auth: str = "api"):
    """(성공여부, [진단]). count_tokens 로 키/로그인·모델 접근 가능성 확인."""
    n, dbg = count_tokens_debug(key, "ping", model=model, auth=auth)
    return (n >= 0), dbg


def propose_glossary_debug(key: str, text: str, known_en=None,
                           model: str = DEFAULT_MODEL, auth: str = "api",
                           max_terms: int = 40):
    """(list[{en,ko}], [진단]). 본문에서 핵심 전문용어를 추출·한국어 대역 제안(구조화 출력).
    known_en 에 든 용어는 제외(이미 사전에 있는 것). 미등록 용어 자동 용어집(P2b §6.2)."""
    import json
    if not available():
        return [], ["anthropic SDK 미설치"]
    if _need_key_missing(key, auth):
        return [], ["API 키/로그인 없음"]
    sample = (text or "")[:8000]
    if not sample.strip():
        return [], ["본문 없음"]
    known = ", ".join(sorted({(k or "").strip().lower() for k in (known_en or []) if k}))[:1500]
    system = (
        "당신은 도로·아스팔트 등 공학 분야 전문 학술 번역가입니다. 주어진 영문 본문에서 "
        "그 분야의 핵심 전문용어(영문)를 추출하고 표준 한국어 대역을 제시하세요. "
        "약어는 한국어로 풀어쓰되 필요하면 약어를 병기합니다. 일반 단어·고유명사·저자명·"
        "기관명은 제외합니다. en 은 본문에 나온 형태, ko 는 한국어 대역. "
        f"최대 {max_terms}개." + (f" 이미 등록된 용어는 제외: {known}" if known else ""))
    schema = {
        "type": "object",
        "properties": {"terms": {"type": "array", "items": {
            "type": "object",
            "properties": {"en": {"type": "string"}, "ko": {"type": "string"}},
            "required": ["en", "ko"], "additionalProperties": False}}},
        "required": ["terms"], "additionalProperties": False}
    try:
        c = _client(key, auth)
        r = c.messages.create(
            model=model, max_tokens=4000,
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": "본문:\n\n" + sample}])
        txt = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
        data = json.loads(txt) if txt else {}
        out = []
        for t in (data.get("terms") or []):
            en = (t.get("en") or "").strip()
            ko = (t.get("ko") or "").strip()
            if en and ko:
                out.append({"en": en, "ko": ko})
        return out[:max_terms], [f"제안 {len(out)}개"]
    except Exception as e:
        return [], [f"ERR {_err_detail(e)}{_auth_hint(e, auth)}"]


def translate_table_image_debug(key: str, image_path: str,
                                model: str = DEFAULT_MODEL, auth: str = "api"):
    """(rows_ko, [진단]). 표 이미지를 비전으로 인식해 행/열 구조 그대로 한국어로 재구성.

    rows_ko = list[list[str]] (첫 행 = 머리글). 표가 없거나 실패 시 빈 리스트.
    번역 표를 '이상한 텍스트'가 아닌 실제 표 형식으로 만들기 위함(P4c 보완)."""
    import base64
    import json
    import os as _os
    if not available():
        return [], ["anthropic SDK 미설치"]
    if _need_key_missing(key, auth):
        return [], ["API 키/로그인 없음"]
    if not (image_path and _os.path.exists(image_path)):
        return [], ["이미지 없음"]
    ext = _os.path.splitext(image_path)[1].lower()
    media = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    try:
        with open(image_path, "rb") as f:
            data_b64 = base64.standard_b64encode(f.read()).decode("ascii")
    except Exception:
        return [], ["이미지 읽기 실패"]
    system = (
        "당신은 도로·아스팔트 등 공학 분야 전문 학술 번역가입니다. 이미지에는 논문의 표 "
        "1개와 주변 본문이 함께 있을 수 있습니다. **표만** 인식하고 주변 본문 문단은 무시하세요. "
        "표 위/아래의 **표 제목(캡션, 예: 'Table 1. …')은 포함하지 말고**, 표의 머리글 행부터 "
        "시작하세요. 행/열 구조를 그대로 유지하되 셀 내용을 한국어로 번역합니다. 숫자·단위·기호·"
        "시료 ID 는 그대로 둡니다. 머리글(헤더) 행을 첫 행으로 포함하고, 각 행의 셀 개수를 "
        "열 수에 맞춰 채웁니다(빈 칸은 빈 문자열). 이미지에 표가 없으면 rows 를 빈 배열로 반환.")
    schema = {
        "type": "object",
        "properties": {"rows": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "string"}}}},
        "required": ["rows"], "additionalProperties": False}
    try:
        c = _client(key, auth)
        r = c.messages.create(
            model=model, max_tokens=8000, system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": media, "data": data_b64}},
                {"type": "text", "text": "이 표를 한국어로 번역해 행/열 그대로 반환하세요."},
            ]}])
        if getattr(r, "stop_reason", "") == "refusal":
            return [], ["표 인식 거부됨"]
        txt = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
        data = json.loads(txt) if txt else {}
        rows = [[str(c) for c in row] for row in (data.get("rows") or [])
                if isinstance(row, list)]
        rows = [r for r in rows if any((c or "").strip() for c in r)]
        return rows, [f"표 {len(rows)}행"]
    except Exception as e:
        return [], [f"ERR {_err_detail(e)}{_auth_hint(e, auth)}"]


def _split_text(text: str, max_chars: int = 7000) -> list:
    """긴 본문을 단락 경계로 청크 분할(전체 번역용). 단락이 너무 길면 강제 분할."""
    text = text or ""
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    paras = re.split(r"\n\s*\n", text)
    chunks: list = []
    cur = ""
    for p in paras:
        if len(p) > max_chars:
            if cur:
                chunks.append(cur); cur = ""
            for i in range(0, len(p), max_chars):
                chunks.append(p[i:i + max_chars])
            continue
        if cur and len(cur) + len(p) + 2 > max_chars:
            chunks.append(cur); cur = p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c.strip()]


def _stream_translate(client, text, model, glossary, effort, max_tokens, on_text):
    """한 청크 스트리밍 번역 → (번역문, stop_reason). 예외는 호출측에서 처리."""
    parts = []
    with client.messages.stream(
        model=model, max_tokens=max_tokens,
        system=_system(glossary),
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        messages=[{"role": "user", "content":
                   "다음 외국어 본문을 한국어로 번역하세요. 번역문만 출력하세요.\n\n" + text}],
    ) as stream:
        for t in stream.text_stream:
            parts.append(t)
            if on_text:
                try:
                    on_text(t)
                except Exception:
                    pass
        msg = stream.get_final_message()
    out = "".join(parts).strip()
    if not out:
        for b in getattr(msg, "content", []) or []:
            if getattr(b, "type", "") == "text":
                out += b.text
        out = out.strip()
    return out, getattr(msg, "stop_reason", "")


def translate_text_debug(key: str, text: str, model: str = DEFAULT_MODEL,
                         glossary=None, effort: str = "medium",
                         max_tokens: int = 64000, on_text=None, auth: str = "api"):
    """(번역문, [진단]). 긴 본문은 단락 경계로 청크 분할해 **전체** 번역 후 이어붙인다.

    auth='api'|'login'. on_text(delta:str): 진행 콜백(선택). 오류 시에도 그때까지의 번역을 반환.
    """
    if not available():
        return "", ["anthropic SDK 미설치 — 'pip install anthropic'"]
    if _need_key_missing(key, auth):
        return "", ["API 키 없음 — 설정 → 번역(Claude)"]
    if not (text or "").strip():
        return "", ["번역할 내용이 없습니다."]
    chunks = _split_text(text, max_chars=7000)
    if not chunks:
        return "", ["번역할 내용이 없습니다."]
    try:
        c = _client(key, auth)
    except Exception as e:
        return "", [f"ERR {_err_detail(e)}{_auth_hint(e, auth)}"]
    outs: list = []
    n = len(chunks)
    for i, ch in enumerate(chunks, 1):
        if n > 1 and on_text:
            try:
                on_text(f"\n\n[{i}/{n} 번역 중…]\n")
            except Exception:
                pass
        try:
            o, stop = _stream_translate(c, ch, model, glossary, effort, max_tokens, on_text)
        except Exception as e:
            partial = "\n\n".join(outs).strip()
            return partial, [f"{i}/{n} 청크 오류: {_err_detail(e)}{_auth_hint(e, auth)}"]
        if stop == "refusal":
            return "\n\n".join(outs).strip(), [f"{i}/{n} 청크에서 거부됨(refusal)."]
        if not o:
            return "\n\n".join(outs).strip(), [f"{i}/{n} 청크 결과 비어 있음."]
        outs.append(o)
    return "\n\n".join(outs).strip(), [f"완료 ({n}개 청크)" if n > 1 else "완료"]
