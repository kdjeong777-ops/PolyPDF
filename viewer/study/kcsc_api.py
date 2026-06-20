"""국가건설기준센터(KCSC) OPEN API — 건설기준(KDS 설계기준·KCS 표준시방서) 본문 조회 (260618-37).

- 본문: GET https://kcsc.re.kr/OpenApi/CodeViewer/{Type}/{Code}?key={KEY}  (JSON)
        예) /CodeViewer/KCS/114010?key=...
        응답(배열) [{no, codeType, code, fullCode, name, version, updateDate,
                     list:[{no, sort, title, level, label, contents}]}]
- 목록: GET https://kcsc.re.kr/OpenApi/CodeList  (요청 파라미터 미확정 — 추후 지원)
- 인증: key(무료 발급, https://www.kcsc.re.kr/support/api), ?key= 로 전달
표준 라이브러리(urllib)만 사용. 법령·고시(law_api) 와 동일한 패턴.
"""
from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
import urllib.request

_UA = "Mozilla/5.0 (PolyPDF KCSC viewer)"
_BASE = "https://kcsc.re.kr/OpenApi"

# 코드 체계(타입). 표시명. (KDS=설계기준, KCS=표준시방서)
TYPES = [("KDS", "설계기준"), ("KCS", "표준시방서")]
TYPE_NAMES = dict(TYPES)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _wrap(body: str) -> str:
    return ("<div style=\"font-family:'Malgun Gothic','맑은 고딕',sans-serif;"
            "font-size:14px;line-height:1.7;color:#1a1a1a;background:#ffffff;\">"
            + body + "</div>")


def _contents_to_html(contents) -> str:
    """절 본문(contents) → 표시 HTML. 태그가 있으면 위험 요소만 제거하고 유지,
    평문이면 escape + 줄바꿈(<br>)."""
    s = str(contents or "")
    if not s.strip():
        return ""
    if "<" in s and ">" in s:           # HTML 로 판단
        for tag in ("script", "style", "iframe", "noscript", "head", "link", "meta"):
            s = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", s, flags=re.I | re.S)
            s = re.sub(rf"<{tag}\b[^>]*/?>", " ", s, flags=re.I)
        s = re.sub(r"\son\w+\s*=\s*\"[^\"]*\"", "", s, flags=re.I)   # on* 핸들러 제거
        s = re.sub(r"\son\w+\s*=\s*'[^']*'", "", s, flags=re.I)
        return s
    return _esc(s).replace("\n", "<br>")


def _format(it: dict):
    """CodeViewer 항목(dict) → (표시 HTML, [(절라벨, 앵커)...], meta)."""
    name = (it.get("name") or "").strip()
    ctype = str(it.get("codeType") or "").strip()
    code = str(it.get("code") or "").strip()
    version = str(it.get("version") or "").strip()
    udate = str(it.get("updateDate") or "").strip()
    meta = {"name": name, "ctype": ctype, "code": code,
            "version": version, "updateDate": udate}

    out: list[str] = []
    arts: list = []
    title = name or (f"{ctype} {code}".strip()) or "건설기준"
    out.append(f'<h2 style="color:#1456c4;margin:2px 0">{_esc(title)}</h2>')
    sub = " · ".join(x for x in [
        (TYPE_NAMES.get(ctype, ctype) if ctype else ""),
        (f"v{version}" if version else ""),
        (udate if udate else "")] if x)
    if sub:
        out.append(f'<p style="color:#666;margin:0 0 8px">{_esc(sub)}</p>')

    for s in (it.get("list") or []):
        if not isinstance(s, dict):
            continue
        try:
            level = int(s.get("level") or 0)
        except Exception:
            level = 0
        label = (str(s.get("label") or "")).strip()
        stitle = (str(s.get("title") or "")).strip()
        head = " ".join(x for x in (label, stitle) if x).strip()
        indent = min(max(level, 0), 6) * 1.2
        if head:
            anchor = f"sec_{len(arts) + 1}"
            arts.append((head, anchor))
            out.append(
                f'<a name="{anchor}"></a>'
                f'<p style="margin:11px 0 2px {indent}em">'
                f'<b><span style="color:#1456c4">{_esc(head)}</span></b></p>')
        body = _contents_to_html(s.get("contents"))
        if body:
            out.append(f'<div style="margin:2px 0 4px {indent + 0.6}em">{body}</div>')
    return _wrap("".join(out)), arts, meta


def fetch_content_debug(key: str, ctype: str, code: str, timeout: float = 12.0):
    """(표시 HTML, [진단...], [(절라벨, 앵커)...], meta). 실패/빈응답이면 html=''."""
    key = (key or "").strip()
    ctype = (ctype or "").strip().upper()
    code = str(code or "").strip()
    if not key:
        return "", ["KCSC 키 없음"], [], {}
    if not ctype or not code:
        return "", ["코드체계(KDS/KCS)와 코드번호를 입력하세요."], [], {}
    url = (f"{_BASE}/CodeViewer/{urllib.parse.quote(ctype)}/"
           f"{urllib.parse.quote(code)}?key={urllib.parse.quote(key)}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:
        return "", [f"ERR {type(e).__name__}: {str(e)[:90]}"], [], {}
    items = data if isinstance(data, list) else [data]
    if not items or not isinstance(items[0], dict):
        return "", [f"{status} 빈 응답"], [], {}
    it = items[0]
    secs = it.get("list") or []
    has_body = any(isinstance(s, dict) and str(s.get("contents") or "").strip()
                   for s in secs)
    if not (it.get("name") or has_body):
        # 키 만료/오류 시 값이 모두 null 로 옴
        msg = str(it.get("message") or it.get("Message") or "").strip()
        return "", [f"{status} 데이터 없음 — KCSC 키/코드 확인"
                    + (f" ({msg})" if msg else "")], [], {}
    html, arts, meta = _format(it)
    return html, [f"{status} ok name={meta.get('name')!r} sections={len(secs)}"], arts, meta


def fetch_content(key: str, ctype: str, code: str, timeout: float = 12.0) -> str:
    return fetch_content_debug(key, ctype, code, timeout)[0]


def list_codes_debug(key: str, ctype: str = "", query: str = "", timeout: float = 12.0):
    """260618-38: 건설기준 목록(CodeList). (rows, [진단...]).
    GET /OpenApi/CodeList?type={KDS|KCS}&key={KEY}  (소문자 파라미터) → JSON 배열.
    query 가 있으면 이름·코드·fullCode 부분일치로 클라이언트 필터.
    rows: {code, fullCode, name, ctype, version, updateDate, parents:[..]}."""
    key = (key or "").strip()
    ctype = (ctype or "").strip().upper()
    if not key:
        return [], ["KCSC 키 없음"]
    params = {"key": key}
    if ctype:
        params["type"] = ctype
    url = _BASE + "/CodeList?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:
        return [], [f"ERR {type(e).__name__}: {str(e)[:90]}"]
    items = data if isinstance(data, list) else [data]
    rows = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = (str(it.get("name") or "")).strip()
        code = str(it.get("code") or "").strip()
        if not (name or code):
            continue
        parents = [(p.get("name") or "").strip()
                   for p in (it.get("listParentCodes") or [])
                   if isinstance(p, dict) and (p.get("name") or "").strip()]
        rows.append({
            "code": code,
            "fullCode": str(it.get("fullCode") or "").strip(),
            "name": name,
            "ctype": str(it.get("codeType") or ctype).strip(),
            "version": str(it.get("version") or "").strip(),
            "updateDate": str(it.get("updateDate") or "").strip(),
            "parents": parents,
        })
    q = (query or "").strip().lower()
    if q:
        rows = [r for r in rows if q in r["name"].lower()
                or q in r["code"].lower() or q in r["fullCode"].lower()]
    if not rows:
        msg = ""
        if items and isinstance(items[0], dict):
            msg = str(items[0].get("message") or "").strip()
        return [], [f"{status} 결과 없음 — 키/타입 확인" + (f" ({msg})" if msg else "")]
    return rows, [f"{status} {len(rows)}건"]


def list_codes(key: str, ctype: str = "", query: str = "", timeout: float = 12.0):
    return list_codes_debug(key, ctype, query, timeout)[0]
