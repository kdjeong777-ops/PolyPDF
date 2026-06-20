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

import os
import re
import shutil
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


# 상세 응답의 주요 태그 → 한글 라벨(없으면 원 태그)
_DETAIL_LABELS = {
    "inventionTitle": "발명의명칭", "inventionTitleEng": "발명의명칭(영문)",
    "astrtCont": "초록", "abstractInfo": "초록",
    "claim": "청구항", "claimScope": "청구범위", "claimInfo": "청구항",
    "applicantName": "출원인", "inventorName": "발명자", "agentName": "대리인",
    "ipcNumber": "IPC", "applicationNumber": "출원번호", "applicationDate": "출원일자",
    "registerNumber": "등록번호", "registerDate": "등록일자",
    "openNumber": "공개번호", "openDate": "공개일자",
    "publicationNumber": "공고번호", "publicationDate": "공고일자",
    "registerStatus": "등록상태", "legalStatusInfo": "법적상태",
    "applicantCode": "출원인코드", "bigDrawing": "도면", "drawing": "도면",
}
_DETAIL_SKIP = {"successYN", "resultCode", "resultMsg", "requestMsgID",
                "responseTime", "responseMsgID", "pageNo", "numOfRows",
                "totalCount", "docName", "indexNo"}


def read_detail_debug(key: str, appno: str, timeout: float = 15.0):
    """(상세 HTML, [진단...]). getBibliographyDetailInfoSearch — 청구범위·초록·서지 상세."""
    key = (key or "").strip()
    appno = "".join(ch for ch in str(appno or "") if ch.isdigit())
    if not key:
        return "", ["KIPRIS ServiceKey 없음"]
    if not appno:
        return "", ["출원번호가 없습니다."]
    url = (_BASE + "/getBibliographyDetailInfoSearch?"
           + urllib.parse.urlencode({"applicationNumber": appno, "ServiceKey": key}))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(); status = r.status
        root = ET.fromstring(raw)
    except Exception as e:
        return "", [f"ERR {type(e).__name__}: {str(e)[:90]}"]
    succ = (_findtext_local(root, "successYN") or "").strip().upper()
    if succ == "N":
        msg = (_findtext_local(root, "resultMsg") or _findtext_local(root, "resultCode") or "조회 실패")
        return "", [f"{status} 실패: {msg} (상세서지 서비스 활용신청 필요할 수 있음)"]
    # 모든 leaf 필드를 순서대로 라벨:값 으로(원본 내용 전체 표시)
    rows = []
    for el in root.iter():
        if list(el):                       # 컨테이너는 건너뜀
            continue
        tag = _local(el.tag)
        if tag in _DETAIL_SKIP:
            continue
        txt = (el.text or "").strip()
        if not txt:
            continue
        label = _DETAIL_LABELS.get(tag, tag)
        if tag.endswith("Date"):
            txt = _fmt_date(txt)
        rows.append(
            f"<p style='margin:6px 0 2px'><b style='color:#1456c4'>{_esc(label)}</b></p>"
            f"<div style='margin:0 0 4px 1em;white-space:pre-wrap'>{_esc(txt)}</div>")
    if not rows:
        return "", [f"{status} 상세 내용 없음", raw[:200].decode('utf-8', 'replace')]
    return _wrap("<h3 style='color:#1456c4'>원문(상세)</h3>" + "".join(rows)), [f"{status} ok"]


# 전문(全文) PDF 서비스 — 공개공보(공개전문)·공고/등록공보(공고전문) 순으로 시도.
#   특허는 공개공보가 없고 공고(등록)공보만 있는 경우가 많아, 공개전문만 보면 다수가 누락됨.
_FULLTEXT_OPS = [
    ("getPubFullTextInfoSearch", "공개전문"),
    ("getAnnFullTextInfoSearch", "공고전문"),
]
# PDF 경로일 가능성이 높은 필드명(소문자)
_PDF_PATH_TAGS = ("path", "docpath", "filepath", "url", "downloadurl", "fileurl", "pdfurl")


def _extract_pdf_url(root) -> str:
    """응답 루트에서 PDF URL 추출 — http…pdf leaf 우선, 없으면 path/url 류 필드."""
    for el in root.iter():
        if list(el):
            continue
        t = (el.text or "").strip()
        if t.lower().startswith("http") and ".pdf" in t.lower():
            return t
    for el in root.iter():
        if list(el):
            continue
        if _local(el.tag).lower() in _PDF_PATH_TAGS and (el.text or "").strip():
            return el.text.strip()
    return ""


def fetch_fulltext_pdf_url_debug(key: str, appno: str, timeout: float = 20.0):
    """(pdf_url, [진단...]). 공개전문→공고전문 순으로 전문 PDF 경로를 찾는다."""
    key = (key or "").strip()
    appno = "".join(ch for ch in str(appno or "") if ch.isdigit())
    if not key or not appno:
        return "", ["키/출원번호 없음"]
    dbg = []
    last_raw = b""
    for op, label in _FULLTEXT_OPS:
        url = (_BASE + "/" + op + "?"
               + urllib.parse.urlencode({"applicationNumber": appno, "ServiceKey": key}))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(); status = r.status
            last_raw = raw
            root = ET.fromstring(raw)
        except Exception as e:
            dbg.append(f"{label} ERR {type(e).__name__}: {str(e)[:80]}")
            continue
        succ = (_findtext_local(root, "successYN") or "").strip().upper()
        if succ == "N":
            msg = (_findtext_local(root, "resultMsg")
                   or _findtext_local(root, "resultCode") or "조회 실패")
            dbg.append(f"{label} {status} 실패: {msg}")
            continue
        pdf = _extract_pdf_url(root)
        if pdf:
            return pdf, dbg + [f"{label} {status} ok"]
        dbg.append(f"{label} {status} PDF 없음")  # 본문 비어있음(해당 공보 없음) → 다음 서비스
    # 모두 실패 — 진단에 마지막 응답 일부 첨부
    tail = last_raw[:300].decode("utf-8", "replace") if last_raw else ""
    return "", dbg + (["응답: " + tail] if tail else []) + \
        ["전문(공개/공고) PDF 를 찾지 못했습니다. 미공개·미등록이거나 전문 서비스 활용신청이 필요할 수 있습니다."]


def download_fulltext_pdf_debug(key: str, appno: str, dest_dir: str,
                                name: str = "", timeout: float = 90.0):
    """(저장경로, [진단...]). 공개전문 PDF 를 dest_dir 에 내려받아 경로 반환."""
    pdf_url, dbg = fetch_fulltext_pdf_url_debug(key, appno, timeout=20.0)
    if not pdf_url:
        return "", dbg
    safe = re.sub(r'[\\/:*?"<>|]+', "_", (name or appno)).strip()[:80] or appno
    appdigits = "".join(ch for ch in str(appno) if ch.isdigit())
    fname = f"{safe} ({appdigits}).pdf" if appdigits and appdigits not in safe else f"{safe}.pdf"
    dest = os.path.join(dest_dir, fname)
    try:
        os.makedirs(dest_dir, exist_ok=True)
        req = urllib.request.Request(pdf_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        size = os.path.getsize(dest)
        if size < 1000:                     # 너무 작으면 PDF 아님(오류 페이지)
            return "", dbg + [f"내려받은 파일이 비정상(크기 {size})"]
        return dest, dbg + [f"저장 {size} bytes"]
    except Exception as e:
        return "", dbg + [f"download ERR {type(e).__name__}: {str(e)[:80]}"]


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
