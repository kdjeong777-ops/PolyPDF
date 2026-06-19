"""법제처 국가법령정보 공동활용 OPEN API — 법령·고시(행정규칙) 검색·본문 (260616-1).

- 목록: https://www.law.go.kr/DRF/lawSearch.do (DRF, JSON)
- 본문: https://www.law.go.kr/DRF/lawService.do (DRF, HTML) — 우측 창 표시용
- 인증: OC(이메일 ID 기반 무료 키)
- target: 'law'(법령) | 'admrul'(행정규칙=고시·훈령·예규) | 'expc'(법령해석)
표준 라이브러리(urllib)만 사용. 실패 시 예외 전파(호출자 처리).
260616-6: 결과에 category/target/본문 식별자(mst/ids) 추가, fetch_content() 신설.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

_UA = "Mozilla/5.0 (PolyPDF legal viewer)"
_BASE = "https://www.law.go.kr/DRF/lawSearch.do"
_SERVICE = "https://www.law.go.kr/DRF/lawService.do"
_SITE = "https://www.law.go.kr"

TARGETS = [("law", "법령"), ("admrul", "행정규칙(고시·훈령)"), ("expc", "법령해석")]
# 책갈피 1차 트리(그룹) 제목 — 짧은 표기
CATEGORY = {"law": "법령", "admrul": "행정규칙", "expc": "법령해석"}


def _items(data) -> list:
    """JSON 최상위(LawSearch/AdmRulSearch 등) 아래의 항목 리스트를 방어적으로 추출."""
    if not isinstance(data, dict):
        return []
    for top in data.values():
        if isinstance(top, dict):
            for k in ("law", "admrul", "expc", "Law", "AdmRul"):
                v = top.get(k)
                if v:
                    return v if isinstance(v, list) else [v]
            for v in top.values():        # 폴백: dict 리스트
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v
    return []


def search(oc: str, query: str, target: str = "law",
           display: int = 20, timeout: float = 10.0,
           search_kind: int = 1) -> list[dict]:
    """법령/행정규칙/법령해석 검색.

    search_kind: 1=이름(법령명), 2=내용(본문) — 법제처 lawSearch 의 search 파라미터.
    반환 항목: {name, kind, agency, date, link, target, category, ids:{...}}
    ids 는 본문 조회용 식별자(법령일련번호/행정규칙일련번호/법령해석일련번호 등).
    """
    if not oc or not query.strip():
        return []
    url = (_BASE + "?" + urllib.parse.urlencode(
        {"OC": oc, "target": target, "type": "JSON",
         "query": query, "display": max(1, min(100, display)),
         "search": 2 if search_kind == 2 else 1}))
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    out = []
    for it in _items(data):
        if not isinstance(it, dict):
            continue
        name = (it.get("법령명한글") or it.get("행정규칙명") or it.get("법령명")
                or it.get("안건명") or "").strip()
        if not name:
            continue
        kind = (it.get("법령구분명") or it.get("행정규칙종류")
                or dict(TARGETS).get(target, target))
        agency = (it.get("소관부처명") or it.get("담당부처명")
                  or it.get("질의기관명") or it.get("회신기관명") or "").strip()
        date = (it.get("공포일자") or it.get("발령일자")
                or it.get("회신일자") or it.get("시행일자") or "")
        link = (it.get("법령상세링크") or it.get("행정규칙상세링크")
                or it.get("법령해석상세링크") or it.get("상세링크") or "")
        if link and link.startswith("/"):
            link = _SITE + link
        ids = {
            "mst": str(it.get("법령일련번호") or "").strip(),
            "law_id": str(it.get("법령ID") or "").strip(),
            "admrul_seq": str(it.get("행정규칙일련번호") or "").strip(),
            "expc_seq": str(it.get("법령해석일련번호") or "").strip(),
        }
        out.append({"name": name, "kind": str(kind), "agency": agency,
                    "date": str(date), "link": link,
                    "target": target, "category": CATEGORY.get(target, target),
                    "ids": ids})
    return out


def _set_type(url: str, typ: str) -> str:
    """URL 의 type 파라미터를 typ 로 교체(없으면 추가)."""
    if "type=" in url:
        return re.sub(r"type=[^&]*", "type=" + typ, url)
    return url + ("&" if "?" in url else "?") + "type=" + typ


def _content_urls(oc: str, row: dict, typ: str = "HTML") -> list[str]:
    """본문 조회 후보 URL 목록(앞에서부터 시도).

    260616-8/9: 검색 API 가 준 상세링크(lawService.do)를 1순위로 사용하고,
    식별자(MST/ID/LID)로 구성한 URL 을 폴백으로. type 은 typ(HTML/XML)로 통일.
    """
    target = row.get("target") or "law"
    ids = row.get("ids") or {}
    urls: list[str] = []
    link = (row.get("link") or "").strip()
    if "lawService.do" in link:
        urls.append(_set_type(link, typ))
    cands: list[dict] = []
    if target == "law":
        if ids.get("mst"):
            cands.append({"target": "law", "MST": ids["mst"]})
        if ids.get("law_id"):
            cands.append({"target": "law", "ID": ids["law_id"]})
    elif target == "admrul":
        if ids.get("admrul_seq"):
            cands.append({"target": "admrul", "ID": ids["admrul_seq"]})
            cands.append({"target": "admrul", "LID": ids["admrul_seq"]})
    elif target == "expc":
        if ids.get("expc_seq"):
            cands.append({"target": "expc", "ID": ids["expc_seq"]})
    for c in cands:
        p = {"OC": oc, "type": typ}
        p.update(c)
        urls.append(_SERVICE + "?" + urllib.parse.urlencode(p))
    return urls


def _decode(raw: bytes, charset: str | None) -> str:
    """응답 바이트를 charset(헤더) → meta → utf-8/cp949 순으로 디코드."""
    enc = (charset or "").lower() or None
    if not enc:
        head = raw[:2048].lower()
        if b"euc-kr" in head or b"ks_c_5601" in head or b"cp949" in head:
            enc = "cp949"
        else:
            enc = "utf-8"
    try:
        return raw.decode(enc, "replace")
    except Exception:
        return raw.decode("utf-8", "replace")


def _get(url: str, timeout: float):
    """(text|None, 진단문자열). 본문/상태/길이 또는 예외를 진단으로 남긴다."""
    tail = url.split("lawService.do", 1)[-1][:60]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            charset = r.headers.get_content_charset()
            status = r.status
        text = _decode(raw, charset)
        return text, f"{status} len={len(raw)} …{tail}"
    except Exception as e:
        return None, f"ERR {type(e).__name__}: {str(e)[:80]} …{tail}"


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _wrap(body: str) -> str:
    return ("<div style=\"font-family:'Malgun Gothic','맑은 고딕',sans-serif;"
            "font-size:14px;line-height:1.7;color:#1a1a1a;background:#ffffff;\">"
            + body + "</div>")


# 동그라미 숫자(①~⑳). ① 은 조 헤더 줄에 이어붙이고, ②~ 는 새 줄.
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
# 목 기호(가.·나.·…)
_MOK = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허고노도로모보소오조초코토포호"
# 조 헤더: 제12조 / 제12조의2 / (제목)
_ART_RE = re.compile(r"(제\s*\d+\s*조(?:의\s*\d+)?\s*(?:\([^)]*\))?)\s*(.*)", re.S)


def _xml_plain_text(xml_text: str) -> str:
    """XML 에서 본문 텍스트만(조문/항/호/목 '…내용' 요소) 문서 순서로 추출.

    메타(조문번호·시행일자 등) 노이즈를 피하려 '내용' 으로 끝나는 태그를 우선 사용.
    없으면 모든 텍스트로 폴백.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return ""
    contents: list[str] = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag.endswith("내용"):
            t = (el.text or "").strip()
            if t:
                contents.append(t)
    if contents:
        return "\n".join(contents)
    return "\n".join(t.strip() for t in root.itertext() if t.strip())


def _format_law_text(text: str):
    """법령 본문 텍스트 → (표시 HTML, [(조 라벨, 앵커)...]).

    260616-10: 법령정보시스템 스타일 정렬.
    - 조 헤더 '제N조(제목)' = 굵은 파란색, 새 단락(+앵커).
    - ① 은 조 헤더 줄에 이어 붙임. ②~⑳ 은 새 줄(들여쓰기 1단).
    - 호 '1. 2.' 새 줄(2단), 목 '가. 나.' 새 줄(3단).
    """
    t = re.sub(r"[ \t]+", " ", text or "")
    # 구조 마커 앞에서 줄바꿈(① 은 제외 — 조 헤더에 붙임)
    t = re.sub(r"(제\s*\d+\s*조(?:의\s*\d+)?\s*\()", r"\n\1", t)
    t = re.sub(r"(제\s*\d+\s*(?:편|장|절|관))", r"\n\1", t)   # 편/장/절/관
    t = re.sub(r"(부칙\s*[<(])", r"\n\1", t)                  # 부칙 <...>
    t = re.sub(r"([②-⑳])", r"\n\1", t)
    t = re.sub(r"(?:(?<=\s)|(?<=\n))(\d{1,2}\.)\s", r"\n\1 ", t)
    t = re.sub(r"(?:(?<=\s)|(?<=\n))([" + _MOK + r"]\.)\s", r"\n\1 ", t)
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]

    out: list[str] = []
    arts: list = []
    seen: set = set()
    total = 0
    last_hdr = None     # 직전 조 헤더 단락 인덱스(① 병합용)

    def _blue(label: str, indent_em: float = 0.0):
        """굵은 파란 헤더 단락(+앵커) 출력하고 arts 에 등록."""
        anchor = f"art_{len(arts) + 1}"
        arts.append((label, anchor))
        mg = f"13px 0 2px {indent_em}em" if indent_em else "13px 0 2px 0"
        return (f'<a name="{anchor}"></a><p style="margin:{mg}">'
                f'<b><span style="color:#1456c4">{_esc(label)}</span></b>'), anchor

    for ln in lines:
        if ln in seen:
            continue
        seen.add(ln)
        total += len(ln)
        # 조: 제N조(제목) — ① 병합 대상
        m = re.match(r"(제\s*\d+\s*조(?:의\s*\d+)?\s*(?:\([^)]*\))?)(.*)", ln)
        if m and m.group(1).strip():
            header, rest = m.group(1).strip(), m.group(2).strip()
            opener, _a = _blue(header)
            out.append(opener + (f' {_esc(rest)}' if rest else "") + "</p>")
            last_hdr = len(out) - 1
            continue
        # 편/장/절/관, 부칙 — 굵은 파란색(앵커), ① 병합 없음
        if re.match(r"제\s*\d+\s*(?:편|장|절|관)", ln) or ln.startswith("부칙"):
            opener, _a = _blue(ln)
            out.append(opener + "</p>")
            last_hdr = None
            continue
        if ln[:1] == "①" and last_hdr is not None:
            out[last_hdr] = out[last_hdr][:-4] + f" {_esc(ln)}</p>"
            continue
        last_hdr = None
        if ln[:1] in _CIRCLED:
            out.append(f'<p style="margin:3px 0 1px 1.4em">{_esc(ln)}</p>')
        elif re.match(r"\d{1,2}\.", ln):
            out.append(f'<p style="margin:1px 0 1px 2.8em">{_esc(ln)}</p>')
        elif re.match(r"[" + _MOK + r"]\.", ln):
            out.append(f'<p style="margin:1px 0 1px 4.2em">{_esc(ln)}</p>')
        else:
            out.append(f'<p style="margin:2px 0 2px 1.4em">{_esc(ln)}</p>')
    if total < 30:
        return "", []
    return _wrap("".join(out)), arts


def _xml_to_html(xml_text: str):
    """XML → (표시 HTML, 조문목록). 실패하면 ('', [])."""
    return _format_law_text(_xml_plain_text(xml_text))


def _html_to_display(html: str):
    """본문 HTML → (표시 HTML, 조문목록). 태그 제거 후 텍스트 기준으로 정렬."""
    s = html or ""
    for tag in ("script", "style", "iframe", "noscript", "head"):
        s = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", s, flags=re.I | re.S)
    # 블록 끝을 줄바꿈으로 보존(조/항 구분 유지)
    s = re.sub(r"</(p|div|tr|li|h\d|br)>", "\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    import html as _h
    s = _h.unescape(s)
    return _format_law_text(s)


def fetch_content(oc: str, row: dict, timeout: float = 12.0) -> str:
    """표시용 본문 HTML 을 반환(없으면 '')."""
    return fetch_content_debug(oc, row, timeout)[0]


def fetch_content_debug(oc: str, row: dict, timeout: float = 12.0):
    """(표시용 HTML, [진단문자열...], [(조라벨,앵커)...]). XML 우선, 실패 시 HTML."""
    dbg: list[str] = []
    if not oc:
        return "", ["OC 없음"], []
    for url in _content_urls(oc, row, "XML"):
        text, info = _get(url, timeout)
        dbg.append("XML " + info)
        if text:
            out, arts = _xml_to_html(text)
            if out:
                return out, dbg, arts
    for url in _content_urls(oc, row, "HTML"):
        text, info = _get(url, timeout)
        dbg.append("HTML " + info)
        if text:
            out, arts = _html_to_display(text)
            if out:
                return out, dbg, arts
    return "", dbg, []
