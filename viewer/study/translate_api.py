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
    "⑤ 한국어 번역문만 출력한다. 머리말·설명·메모를 덧붙이지 않는다."
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


def translate_text_debug(key: str, text: str, model: str = DEFAULT_MODEL,
                         glossary=None, effort: str = "medium",
                         max_tokens: int = 64000, on_text=None, auth: str = "api"):
    """(번역문, [진단]). 스트리밍으로 한국어 번역(P0 단일 청크).

    auth='api'|'login'. on_text(delta:str): 진행 콜백(선택). 거부/오류 시 빈 문자열 + 진단.
    """
    if not available():
        return "", ["anthropic SDK 미설치 — 'pip install anthropic'"]
    if _need_key_missing(key, auth):
        return "", ["API 키 없음 — 설정 → 번역(Claude)"]
    if not (text or "").strip():
        return "", ["번역할 내용이 없습니다."]
    try:
        c = _client(key, auth)
        parts = []
        with c.messages.stream(
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
        stop = getattr(msg, "stop_reason", "")
        usage = getattr(msg, "usage", None)
        dbg = [f"ok stop={stop}"]
        if usage is not None:
            dbg.append(
                f"in={getattr(usage,'input_tokens',0)} out={getattr(usage,'output_tokens',0)} "
                f"cache_r={getattr(usage,'cache_read_input_tokens',0)}")
        if stop == "refusal":
            return "", dbg + ["요청이 거부되었습니다(refusal)."]
        if not out:
            return "", dbg + ["번역 결과가 비어 있습니다."]
        return out, dbg
    except Exception as e:
        return "", [f"ERR {_err_detail(e)}{_auth_hint(e, auth)}"]
