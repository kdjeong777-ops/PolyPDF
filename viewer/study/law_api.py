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

# ── 260825: 이미지 임베드 · 문장중간 마커 오탐 방지 ──────────────────────
_LAW_IMG_BASE = "https://www.law.go.kr/LSW/flDownload.do?flSeq="
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
_IMG_TOKEN_RE = re.compile("\x01IMG(\\d+)\x01")


def _img_flseq(tag: str):
    """<img ...> 태그에서 flSeq(첨부 일련번호) 추출 — flSeq= / id= / src 내 숫자 순."""
    m = (re.search(r"flSeq=(\d+)", tag, re.I)
         or re.search(r"\bid\s*=\s*[\"']?(\d+)", tag, re.I)
         or re.search(r"\bsrc\s*=\s*[\"'][^\"']*?(\d{4,})", tag, re.I))
    return m.group(1) if m else None


def _img_tokenize(text: str) -> str:
    """본문 속 <img> 를 안전한 토큰(\\x01IMG{flSeq}\\x01)으로 치환하고 닫는 </img> 제거.

    태그 제거 전에 호출해 이미지 정보를 보존한다. (260825-7: `</img>` 텍스트 노출 방지)
    """
    def _repl(m):
        n = _img_flseq(m.group(0))
        return f"\x01IMG{n}\x01" if n else " "
    t = _IMG_TAG_RE.sub(_repl, text or "")
    return re.sub(r"</\s*img\s*>", "", t, flags=re.I)


# 260825-7: 표(<table>) 보존 — QTextBrowser 로 실제 표 렌더
_TBL_TOKEN_RE = re.compile("\x02TBL(\\d+)\x02")
_TABLE_RE = re.compile(r"<table\b.*?</table\s*>", re.I | re.S)


def _sanitize_table(html: str) -> str:
    """표 HTML 을 안전한 형태로 정리 — 구조 태그·colspan/rowspan·이미지만 유지."""
    def _open(m):
        tag = m.group(1).lower(); attrs = m.group(2) or ""
        if tag == "img":
            n = _img_flseq(m.group(0))
            return (f'<img src="{_LAW_IMG_BASE}{n}" style="max-width:100%">'
                    if n else " ")
        if tag in ("td", "th"):
            keep = ""
            for a in ("colspan", "rowspan"):
                mm = re.search(a + r"\s*=\s*[\"']?(\d+)", attrs, re.I)
                if mm:
                    keep += f' {a}="{mm.group(1)}"'
            return f"<{tag}{keep}>"
        if tag in ("table", "thead", "tbody", "tfoot", "tr", "caption"):
            return f"<{tag}>"
        return " "                       # 비허용 여는 태그 제거(내부 텍스트는 유지)

    def _close(m):
        tag = m.group(1).lower()
        if tag in ("table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption"):
            return f"</{tag}>"
        return " "
    h = re.sub(r"<([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>", _open, html or "")
    h = re.sub(r"</([a-zA-Z][a-zA-Z0-9]*)\s*>", _close, h)
    h = h.replace("<table>",
                  '<table border="1" cellspacing="0" cellpadding="4" '
                  'style="border-collapse:collapse;margin:8px 0;font-size:13px">')
    return h


def _extract_media(text: str):
    """본문에서 <table>·<img> 를 토큰으로 분리(표는 map 에 정리본 저장). (text_with_tokens, tables)."""
    tables: dict = {}

    def _tbl(m):
        tok = f"\x02TBL{len(tables)}\x02"
        tables[tok] = _sanitize_table(m.group(0))
        return "\n" + tok + "\n"           # 표는 독립 단락으로
    t = _TABLE_RE.sub(_tbl, text or "")
    t = _img_tokenize(t)                    # <img>→토큰, </img> 제거
    return t, tables


def _strip_residual_html(s: str) -> str:
    """표·이미지 토큰을 제외한 나머지 HTML 태그 제거(블록 끝은 개행) + 엔티티 해제."""
    s = s or ""
    for tag in ("script", "style", "iframe", "noscript", "head"):
        s = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", s, flags=re.I | re.S)
    s = re.sub(r"</(p|div|tr|li|h\d|br)>", "\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    import html as _h
    return _h.unescape(s)


# 구조 마커(조/편/장/절/관/부칙) 앞 줄바꿈 후보. 조는 '(제목)' 형태만.
_HEAD_SPLIT_RE = re.compile(
    r"(?:제\s*\d+\s*조(?:의\s*\d+)?\s*\(|제\s*\d+\s*(?:편|장|절|관)(?=\s|$)|부칙\s*[<(])")
# 새 단락으로 인정할 '앞 문맥' — 줄 시작 또는 문장 종결부호 뒤에서만.
_SENT_END = ".。!?"
# '제5조에/의/를…' 처럼 조사로 시작하면 조문 헤더가 아니라 인용.
_JOSA_START = tuple("에의를은는이가과와로도만")
_CIRCLED_ALL = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _head_split_repl(m):
    s, st = m.string, m.start()
    j = st - 1
    while j >= 0 and s[j] in " \t":
        j -= 1
    if j < 0 or s[j] == "\n" or s[j] in _SENT_END:
        return "\n" + m.group(0)
    return m.group(0)                      # 문장 중간(인용) → 분리하지 않음


def _is_article_body(rest: str) -> bool:
    """'제N조' 뒤(제목 괄호 없음)가 실제 조문 본문인지(→헤더) 인용인지(→아님) 판정."""
    r = (rest or "").lstrip()
    if not r:
        return True
    if r[0] in _CIRCLED_ALL or r.startswith("삭제"):
        return True
    if r[0] in _JOSA_START:                # 제5조에/의/를… → 인용
        return False
    return False                           # 제목 없는 애매한 경우는 보수적으로 헤더 제외


def _img_mime(raw: bytes, ct: str = "") -> str | None:
    """바이트 매직 + Content-Type 으로 이미지 MIME 판정(아니면 None).

    ★ 법제처 flDownload 는 실제 BMP 를 image/gif 로 잘못 보내므로 **매직 우선**.
    """
    if raw[:8].startswith(b"\x89PNG"):
        return "image/png"
    if raw[:2] == b"\xff\xd8":
        return "image/jpeg"
    if raw[:4] == b"GIF8":
        return "image/gif"
    if raw[:2] == b"BM":
        return "image/bmp"                 # ← 법령 표 이미지가 실제로 BMP
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if ct.startswith("image/"):
        return ct                          # 매직은 몰라도 헤더가 이미지면 신뢰
    return None


def _download_data_uri(url: str, timeout: float = 8.0):
    """이미지 URL → data:URI (이미지가 아니거나 실패하면 None).

    BMP/TIFF 등은 가능하면 QImage 로 PNG 재인코딩(QTextBrowser 호환·용량↓),
    Qt 미가용 시 원본 바이트로 임베드.
    """
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://www.law.go.kr/"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except Exception:
        return None
    if not raw:
        return None
    mime = _img_mime(raw, ct)
    if not mime:
        return None                        # 이미지가 아니면 임베드하지 않음
    import base64
    # PNG/JPEG/GIF 가 아니면(BMP 등) QImage 로 PNG 재인코딩 시도
    if mime not in ("image/png", "image/jpeg", "image/gif"):
        try:
            from PyQt6.QtGui import QImage
            from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
            img = QImage()
            if img.loadFromData(raw):
                ba = QByteArray(); buf = QBuffer(ba)
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                img.save(buf, "PNG"); buf.close()
                return "data:image/png;base64," + base64.b64encode(
                    bytes(ba)).decode("ascii")
        except Exception:
            pass
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def _embed_images(html: str, timeout: float = 8.0, limit: int = 20) -> str:
    """본문 HTML 의 flDownload 이미지 URL 을 다운로드해 data:URI 로 치환."""
    seen: dict[str, str] = {}
    n = 0

    def _repl(m):
        nonlocal n
        url = m.group(0)
        if url in seen:
            return seen[url]
        if n >= limit:
            return url
        n += 1
        data = _download_data_uri(url, timeout)
        seen[url] = data or url
        return seen[url]
    return re.sub(r"https://www\.law\.go\.kr/LSW/flDownload\.do\?flSeq=\d+",
                  _repl, html or "")


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
            # 260825-7: el.text 만이 아니라 하위까지 포함(자식 요소로 잘리지 않게)
            t = "".join(el.itertext()).strip()
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
    raw, tables = _extract_media(text or "")  # 표(<table>)·이미지(<img>) 토큰화
    t = _strip_residual_html(raw)             # 남은 HTML 태그 제거 + 엔티티 해제
    t = re.sub(r"[ \t]+", " ", t)
    # 구조 마커 앞에서 줄바꿈 — 단, 줄 시작/문장종결부호 뒤에서만(문장 중간 인용 제외)
    t = _HEAD_SPLIT_RE.sub(_head_split_repl, t)
    t = re.sub(r"([②-⑳])", r"\n\1", t)
    t = re.sub(r"(?:(?<=\s)|(?<=\n))(\d{1,2}\.)\s", r"\n\1 ", t)
    t = re.sub(r"(?:(?<=\s)|(?<=\n))([" + _MOK + r"]\.)\s", r"\n\1 ", t)
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]

    out: list[str] = []
    arts: list = []
    seen: set = set()
    total = 0
    last_hdr = None     # 직전 조 헤더 단락 인덱스(① 병합용)
    after_buchik = False  # 260825: '부칙' 이후엔 제목/앵커 억제

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
        # 표 토큰 — 독립 단락으로 그대로 두고 끝에서 <table> 로 치환
        if _TBL_TOKEN_RE.fullmatch(ln):
            out.append(ln)
            last_hdr = None
            continue
        # 조: 제N조(제목) — ① 병합 대상. '(제목)' 이 있거나 본문선행일 때만 헤더로 인정.
        m = re.match(r"(제\s*\d+\s*조(?:의\s*\d+)?)(\s*\([^)]*\))?(.*)", ln)
        if (not after_buchik) and m and (m.group(2) or _is_article_body(m.group(3))):
            header = (m.group(1) + (m.group(2) or "")).strip()
            rest = m.group(3).strip()
            opener, _a = _blue(header)
            out.append(opener + (f' {_esc(rest)}' if rest else "") + "</p>")
            last_hdr = len(out) - 1
            continue
        # 편/장/절/관, 부칙 — 굵은 파란색(앵커), ① 병합 없음
        if (not after_buchik) and (
                re.match(r"제\s*\d+\s*(?:편|장|절|관)(?=\s|$)", ln)
                or ln.startswith("부칙")):
            opener, _a = _blue(ln)
            out.append(opener + "</p>")
            last_hdr = None
            if ln.startswith("부칙"):
                after_buchik = True       # 이후 조/장은 헤더/앵커 없이 본문 처리
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
    if total < 30 and not tables:
        return "", []
    body = "".join(out)
    # 이미지 토큰 → <img> (URL 은 fetch 단계에서 data:URI 로 임베드)
    body = _IMG_TOKEN_RE.sub(
        lambda m: (f'<img src="{_LAW_IMG_BASE}{m.group(1)}" '
                   f'style="max-width:98%;height:auto;margin:6px 0">'), body)
    # 표 토큰 → 정리된 <table>
    body = _TBL_TOKEN_RE.sub(lambda m: tables.get(m.group(0), ""), body)
    return _wrap(body), arts


def _xml_to_html(xml_text: str):
    """XML → (표시 HTML, 조문목록). 실패하면 ('', [])."""
    return _format_law_text(_xml_plain_text(xml_text))


def _html_to_display(html: str):
    """본문 HTML → (표시 HTML, 조문목록).

    260825-7: 표(<table>)·이미지(<img>)는 `_format_law_text` 안에서 토큰으로 보존·복원하고,
    나머지 HTML 태그만 제거해 텍스트 기준으로 정렬(표·이미지는 실제로 렌더)."""
    return _format_law_text(html or "")


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
                return _embed_images(out, timeout), dbg, arts
    for url in _content_urls(oc, row, "HTML"):
        text, info = _get(url, timeout)
        dbg.append("HTML " + info)
        if text:
            out, arts = _html_to_display(text)
            if out:
                return _embed_images(out, timeout), dbg, arts
    return "", dbg, []


def verify_oc_debug(oc: str, timeout: float = 10.0):
    """(성공여부, 메시지). 법제처 OC 키 확인 — 공통어로 1건 검색."""
    oc = (oc or "").strip()
    if not oc:
        return False, "OC 없음"
    try:
        rows = search(oc, "도로", "law", display=1, timeout=timeout)
    except Exception as e:
        return False, f"오류: {type(e).__name__}: {str(e)[:80]}"
    if rows:
        return True, f"정상 (예: {(rows[0].get('name') or '')[:18]})"
    return False, "결과 없음 — OC(법제처 키) 확인 필요"
