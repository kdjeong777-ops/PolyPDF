"""특허 검색 — KIPRIS Plus 특허실용신안 항목별검색(getAdvancedSearch) (260618-44).

- 엔드포인트: http://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getAdvancedSearch
- 인증: ServiceKey (KIPRIS Plus 발급 키, 쿼리 파라미터)  ※ accessKey 아님(미등록 오류남)
- 응답: XML <response><header>successYN/resultMsg</header><body><items><item>…</item></items><count>…</count></response>
- 검색 항목(IN): word(자유)·inventionTitle(명칭)·astrtCont(초록/내용)·registerNumber(등록번호)·
  applicant(출원인)·applicationNumber(출원번호)·ipcNumber 등. patent/utility(true/false), pageNo·numOfRows(≤500).
- 결과(OUT item): inventionTitle·astrtCont·registerNumber·registerDate·applicationNumber·applicationDate·
  openNumber·publicationNumber·applicantName·ipcNumber·registerStatus·drawing(이미지) 등.
표준 라이브러리(urllib + xml.etree)만 사용.
"""
from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_UA = "Mozilla/5.0 (PolyPDF KIPRIS viewer)"
_BASE = "http://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice"

# 검색 기준(패널 드롭다운) → IN 파라미터명
SEARCH_FIELDS = [
    ("word", "자유검색"),
    ("inventionTitle", "발명의명칭"),
    ("astrtCont", "초록(내용)"),
    ("applicant", "출원인"),
    ("registerNumber", "등록번호"),
    ("applicationNumber", "출원번호"),
]
# 결과 상세 표시용 라벨(순서)
_OUT_LABELS = [
    ("inventionTitle", "발명의명칭"), ("registerStatus", "등록상태"),
    ("applicationNumber", "출원번호"), ("applicationDate", "출원일자"),
    ("openNumber", "공개번호"), ("openDate", "공개일자"),
    ("publicationNumber", "공고번호"), ("publicationDate", "공고일자"),
    ("registerNumber", "등록번호"), ("registerDate", "등록일자"),
    ("applicantName", "출원인"), ("ipcNumber", "IPC"),
    ("astrtCont", "초록"),
]


def _esc(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _wrap(body: str) -> str:
    return ("<div style=\"font-family:'Malgun Gothic','맑은 고딕',sans-serif;"
            "font-size:14px;line-height:1.7;color:#1a1a1a;background:#ffffff;\">"
            + body + "</div>")


def _fmt_date(s: str) -> str:
    s = (s or "").strip()
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s


def _local(tag: str) -> str:
    """네임스페이스 접두 제거({ns}tag → tag)."""
    return tag.split("}")[-1] if "}" in tag else tag


def _item_dict(el) -> dict:
    return {_local(ch.tag): (ch.text or "").strip() for ch in el}


def _findtext_local(root, name: str) -> str:
    for el in root.iter():
        if _local(el.tag) == name:
            return (el.text or "").strip()
    return ""


# 결과 레코드(행) 판별용 — 이 필드들이 2개 이상 직접 자식이면 한 건으로 본다(요소명 무관).
_FIELD_TAGS = {"inventionTitle", "applicationNumber", "registerNumber", "astrtCont",
               "applicantName", "applicant", "ipcNumber", "openNumber",
               "publicationNumber", "applicationDate", "registerDate", "indexNo"}


def _extract_records(root) -> list:
    recs = []
    for el in root.iter():
        kids = [_local(c.tag) for c in el]
        if sum(1 for k in kids if k in _FIELD_TAGS) >= 2:
            recs.append(_item_dict(el))
    return recs


def search_advanced_debug(key: str, field: str, query: str,
                          page: int = 1, rows: int = 30, timeout: float = 15.0):
    """(items[], total, [진단...]). field=IN 파라미터명(word/inventionTitle/…), query=검색어."""
    key = (key or "").strip()
    query = (query or "").strip()
    if not key:
        return [], 0, ["KIPRIS accessKey 없음"]
    if not query:
        return [], 0, ["검색어를 입력하세요."]
    field = field if field in dict(SEARCH_FIELDS) else "word"
    params = {
        "ServiceKey": key, field: query,    # 260618-46: 인증 파라미터는 ServiceKey (accessKey 아님)
        "patent": "true", "utility": "true",
        "pageNo": max(1, int(page)), "numOfRows": max(1, min(500, int(rows))),
        "sortSpec": "AD", "descSort": "true",
    }
    url = _BASE + "/getAdvancedSearch?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except Exception as e:
        return [], 0, [f"ERR {type(e).__name__}: {str(e)[:90]}"]
    try:
        root = ET.fromstring(raw)
    except Exception:
        return [], 0, [f"{status} XML 파싱 실패", raw[:200].decode('utf-8', 'replace')]
    succ = (_findtext_local(root, "successYN") or "").strip().upper()
    if succ == "N":
        msg = (_findtext_local(root, "resultMsg")
               or _findtext_local(root, "resultCode") or "조회 실패")
        return [], 0, [f"{status} 실패: {msg} (KIPRIS ServiceKey/검색어 확인)"]
    items = _extract_records(root)
    try:
        total = int(_findtext_local(root, "totalCount") or len(items))
    except Exception:
        total = len(items)
    if not items:
        # 진단: 응답 앞부분을 보여 줘 구조 파악(요소명/오류 확인)
        snippet = raw[:200].decode('utf-8', 'replace').replace("\n", " ")
        return [], total, [f"{status} 결과 없음", snippet]
    return items, total, [f"{status} {len(items)}건 (전체 {total})"]


def item_label(it: dict) -> str:
    title = (it.get("inventionTitle") or "(명칭 없음)").strip()
    num = (it.get("registerNumber") or it.get("applicationNumber") or "").strip()
    return f"{title} ({num})" if num else title


def format_item(it: dict) -> str:
    """검색결과 항목(dict) → 상세 표시 HTML."""
    title = (it.get("inventionTitle") or "").strip() or "특허"
    out = [f"<h2 style='color:#1456c4;margin:2px 0'>{_esc(title)}</h2>"]
    rows = []
    for key, label in _OUT_LABELS:
        if key in ("inventionTitle",):
            continue
        v = (it.get(key) or "").strip()
        if not v:
            continue
        if key.endswith("Date"):
            v = _fmt_date(v)
        rows.append(
            "<tr>"
            f"<th style='text-align:left;color:#555;font-weight:600;"
            f"padding:3px 12px 3px 0;white-space:nowrap;vertical-align:top'>{_esc(label)}</th>"
            f"<td style='padding:3px 0'>{_esc(v)}</td></tr>")
    if rows:
        out.append("<table style='border-collapse:collapse'>" + "".join(rows) + "</table>")
    img = (it.get("drawing") or it.get("bigDrawing") or "").strip()
    if img.startswith("http"):
        out.append(f"<p style='margin-top:10px'><img src='{_esc(img)}' "
                   f"style='max-width:100%;border:1px solid #ddd'/></p>")
    return _wrap("".join(out))
