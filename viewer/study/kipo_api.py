"""특허청(KIPO) 특허 등록정보 — patent.go.kr 웹서비스(REST/JSON) (260618-43).

- 베이스: https://www.patent.go.kr/smart/webservice/rgt/{method}.do  (JSON)
  · readRgstBasicInfo  — 등록번호(rgstNo)로 등록 기본정보
  · readRgstNoInfo     — 출원인코드(apAgtCd)의 등록번호 목록
  · readRgstHistInfo   — 등록 이력,  readRgstRightInfo — 권리자
- 인증: signKey(쿼리 파라미터). 응답 공통: {errorType, procResult, errorMsg, ...데이터...}
표준 라이브러리(urllib)만 사용. 응답 필드명은 기관 정의를 그대로 키:값 표로 표시(방어적).
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

_UA = "Mozilla/5.0 (PolyPDF KIPO viewer)"
_BASE = "https://www.patent.go.kr/smart/webservice/rgt"

# 데이터가 아닌 제어/페이지 필드(표에서 제외)
_CONTROL = {"errortype", "procresult", "errormsg", "resultmsg", "resultcode",
            "totalcount", "pageperrow", "pageno", "count", "result"}
# 등록번호로 추정되는 키(부분일치, 소문자)
_RGST_KEYS = ("rgstno", "regno", "registrationnumber", "rgst_no")
# 명칭으로 추정되는 키
_TITLE_KEYS = ("inventiontitle", "title", "etitl", "ettitl", "invtitle",
               "발명의명칭", "고안의명칭", "디자인의대상", "상표명칭", "name", "titl")


def _esc(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _wrap(body: str) -> str:
    return ("<div style=\"font-family:'Malgun Gothic','맑은 고딕',sans-serif;"
            "font-size:14px;line-height:1.7;color:#1a1a1a;background:#ffffff;\">"
            + body + "</div>")


def _get_json(method: str, params: dict, timeout: float):
    url = _BASE + "/" + method + ".do?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        status = r.status
    txt = raw.decode("utf-8", "replace")
    try:
        data = json.loads(txt)
    except Exception:
        data = None
    return status, data, txt


def _proc_failed(data):
    """procResult=false 면 (True, 메시지). 성공/판단불가면 (False, '')."""
    if isinstance(data, dict):
        pr = str(data.get("procResult") or data.get("procresult") or "").strip().lower()
        if pr == "false":
            msg = (data.get("errorMsg") or data.get("errorType")
                   or data.get("resultMsg") or "조회 실패")
            return True, str(msg)
    return False, ""


def _records(data):
    """JSON 응답에서 데이터 레코드(dict) 목록을 방어적으로 추출."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for v in data.values():                    # 중첩 리스트 우선
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        for k, v in data.items():                  # 중첩 단일 객체
            if isinstance(v, dict) and k.lower() not in _CONTROL:
                return [v]
        rest = {k: v for k, v in data.items()       # 최상위(제어필드 제외)
                if k.lower() not in _CONTROL and not isinstance(v, (dict, list))}
        return [rest] if rest else []
    return []


def _find(rec: dict, key_subs) -> str:
    for k, v in rec.items():
        kl = k.lower().replace("_", "")
        if any(s in kl for s in key_subs) and v not in (None, ""):
            return str(v)
    return ""


def _kv_table(rec: dict) -> str:
    rows = []
    for k, v in rec.items():
        if k.lower() in _CONTROL:
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        if v in (None, ""):
            continue
        rows.append(
            "<tr>"
            f"<th style='text-align:left;color:#555;font-weight:600;"
            f"padding:3px 12px 3px 0;white-space:nowrap;vertical-align:top'>{_esc(k)}</th>"
            f"<td style='padding:3px 0'>{_esc(v)}</td></tr>")
    return ("<table style='border-collapse:collapse'>" + "".join(rows) + "</table>"
            if rows else "")


def read_basic_info_debug(signkey: str, rgstno: str, timeout: float = 12.0):
    """(표시 HTML, [진단...], meta). 등록번호로 등록 기본정보."""
    signkey = (signkey or "").strip()
    rgstno = re.sub(r"\D", "", str(rgstno or ""))
    if not signkey:
        return "", ["KIPO signKey 없음"], {}
    if not rgstno:
        return "", ["등록번호(숫자)를 입력하세요."], {}
    try:
        st, data, txt = _get_json("readRgstBasicInfo",
                                  {"signKey": signkey, "rgstNo": rgstno}, timeout)
    except Exception as e:
        return "", [f"ERR {type(e).__name__}: {str(e)[:90]}"], {}
    failed, msg = _proc_failed(data)
    if failed:
        return "", [f"{st} 실패: {msg} (signKey/등록번호 확인)"], {}
    recs = _records(data)
    if not recs:
        return "", [f"{st} 데이터 없음", txt[:160]], {}
    rec = recs[0]
    title = _find(rec, _TITLE_KEYS)
    meta = {"name": title or f"등록 {rgstno}", "rgstNo": rgstno}
    head = _esc(title) if title else f"등록번호 {rgstno}"
    html = _wrap(
        f"<h2 style='color:#1456c4;margin:2px 0'>{head}</h2>"
        f"<p style='color:#666;margin:0 0 8px'>등록번호 {_esc(rgstno)}</p>"
        + _kv_table(rec))
    return html, [f"{st} ok"], meta


def list_reg_numbers_debug(signkey: str, apagtcd: str, page: int = 1,
                           per_row: int = 100, timeout: float = 12.0):
    """(rows, [진단...]). 출원인코드의 등록번호 목록. rows: {rgstNo, name, raw}."""
    signkey = (signkey or "").strip()
    apagtcd = (apagtcd or "").strip()
    if not signkey:
        return [], ["KIPO signKey 없음"]
    if not apagtcd:
        return [], ["출원인코드를 입력하세요."]
    try:
        st, data, txt = _get_json("readRgstNoInfo",
                                  {"signKey": signkey, "apAgtCd": apagtcd,
                                   "pageNo": max(1, page),
                                   "pagePerRow": max(1, min(100, per_row))}, timeout)
    except Exception as e:
        return [], [f"ERR {type(e).__name__}: {str(e)[:90]}"]
    failed, msg = _proc_failed(data)
    if failed:
        return [], [f"{st} 실패: {msg} (signKey/출원인코드 확인)"]
    rows = []
    for rec in _records(data):
        rgst = re.sub(r"\D", "", _find(rec, _RGST_KEYS))
        if not rgst:
            continue
        rows.append({"rgstNo": rgst, "name": _find(rec, _TITLE_KEYS), "raw": rec})
    if not rows:
        return [], [f"{st} 결과 없음", txt[:160]]
    return rows, [f"{st} {len(rows)}건"]


def read_basic_info(signkey: str, rgstno: str, timeout: float = 12.0) -> str:
    return read_basic_info_debug(signkey, rgstno, timeout)[0]
