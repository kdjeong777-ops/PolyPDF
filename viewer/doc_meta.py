# -*- coding: utf-8 -*-
"""문서 정보 고치기 — 제목·작성자·주제·키워드의 보류와 PDF 정보 쓰기 (마스터 SOT §4.12 '고치기', 261107-31).

- 문서 정보 창에서 고친 값은 **보류**(`set_pending`)로 두었다가 그 파일의 다음 편집 모드 💾 [저장] 이
  PDF 를 만들 때 그 임시 파일에 `write_info` 로 쓴다(사용자 결정 D5). 보류는 이번 실행 동안만(메모리).
- Info 사전은 **키마다** 쓴다 — `fitz.Document.set_metadata` 는 사전을 통째로 바꿔 다른 키(`/PolyPDFHash` …)를 지운다.
- XMP 가 있으면 같은 네 값도 고친다(Acrobat 등은 XMP 를 먼저 보여 준다). XMP 를 읽지 못하면 그대로 둔다.
- Qt 를 쓰지 않는다 — `write_info` 는 배경 작업·검사에서 그대로 부른다.
"""
from __future__ import annotations

import re
import threading

FIELDS = ("title", "author", "subject", "keywords")
INFO_KEY = {"title": "Title", "author": "Author", "subject": "Subject", "keywords": "Keywords"}

_PENDING: dict = {}               # norm_key(경로) → {"path": 경로, "fields": {필드: 값}}
_LOCK = threading.Lock()


def _key(path) -> str:
    from viewer.pathutil import norm_key
    return norm_key(str(path))


# ── 보류 ────────────────────────────────────────────────────────────────
def set_pending(path, field: str, value: str, original: str | None = None) -> None:
    """한 값을 보류에 넣는다. `original`(PDF 의 지금 값)과 같으면 그 필드 보류를 지운다."""
    if field not in FIELDS:
        raise ValueError(field)
    value = (value or "").strip()
    k = _key(path)
    with _LOCK:
        ent = _PENDING.setdefault(k, {"path": str(path), "fields": {}})
        if original is not None and value == (original or "").strip():
            ent["fields"].pop(field, None)
        else:
            ent["fields"][field] = value
        if not ent["fields"]:
            _PENDING.pop(k, None)


def pending(path) -> dict:
    """그 파일의 보류 {필드: 값} (없으면 {})."""
    with _LOCK:
        ent = _PENDING.get(_key(path))
        return dict(ent["fields"]) if ent else {}


def has_pending(path=None) -> bool:
    with _LOCK:
        return bool(_PENDING.get(_key(path))) if path is not None else bool(_PENDING)


def pending_paths() -> list:
    with _LOCK:
        return [ent["path"] for ent in _PENDING.values()]


def clear_pending(path=None) -> None:
    """그 파일(없으면 모두)의 보류를 지운다 — 저장 성공·버림."""
    with _LOCK:
        if path is None:
            _PENDING.clear()
        else:
            _PENDING.pop(_key(path), None)


def relocate(old, new) -> None:
    """이름 변경·이동 뒤 보류를 새 경로로(마스터 §4.7.14)."""
    with _LOCK:
        ent = _PENDING.pop(_key(old), None)
        if ent:
            ent["path"] = str(new)
            _PENDING[_key(new)] = ent


# ── 쓰기 ────────────────────────────────────────────────────────────────
def _info_xref(doc) -> int:
    """Info 사전의 xref — 없으면 만든다."""
    kind, val = doc.xref_get_key(-1, "Info")
    if kind == "xref":
        try:
            return int(val.split()[0])
        except (ValueError, IndexError):
            pass
    x = doc.get_new_xref()
    doc.update_object(x, "<<>>")
    doc.xref_set_key(-1, "Info", "%d 0 R" % x)
    return x


_NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "pdf": "http://ns.adobe.com/pdf/1.3/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
_XMP_PROP = {"title": ("dc", "title", "alt"), "author": ("dc", "creator", "seq"),
             "subject": ("dc", "description", "alt"), "keywords": ("pdf", "Keywords", "text")}


def _q(ns: str, name: str) -> str:
    return "{%s}%s" % (_NS[ns], name)


def update_xmp(xml: str, fields: dict) -> str | None:
    """XMP 글의 네 값을 고친 글. 못 읽으면 None(부른 쪽은 XMP 를 그대로 둔다)."""
    import xml.etree.ElementTree as ET
    m = re.search(r"<x:xmpmeta\b.*?</x:xmpmeta>", xml, re.S) or re.search(r"<rdf:RDF\b.*?</rdf:RDF>", xml, re.S)
    if not m:
        return None
    body = m.group(0)
    for p, uri in re.findall(r'xmlns:([A-Za-z_][\w.-]*)="([^"]+)"', xml):
        try:
            ET.register_namespace(p, uri)       # 원래 접두어 그대로(ns0 으로 바뀌지 않게)
        except ValueError:
            pass
    for p in ("x", "rdf", "dc", "pdf", "xmp"):
        ET.register_namespace(p, _NS[p])
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    rdf = root if root.tag == _q("rdf", "RDF") else root.find(_q("rdf", "RDF"))
    if rdf is None:
        return None
    descs = rdf.findall(_q("rdf", "Description"))
    if not descs:
        d = ET.SubElement(rdf, _q("rdf", "Description"))
        d.set(_q("rdf", "about"), "")
        descs = [d]
    for f, val in fields.items():
        ns, name, form = _XMP_PROP[f]
        tag = _q(ns, name)
        done = False
        for d in descs:
            if tag in d.attrib:                 # 속성 꼴(`pdf:Keywords="…"`)
                if val:
                    d.set(tag, val)
                else:
                    del d.attrib[tag]
                done = True
            for el in d.findall(tag):
                if not val:
                    d.remove(el)
                elif form == "text":
                    for ch in list(el):
                        el.remove(ch)
                    el.text = val
                else:
                    _set_list(el, form, val)
                done = True
        if not done and val:
            el = ET.SubElement(descs[0], tag)
            if form == "text":
                el.text = val
            else:
                _set_list(el, form, val)
    out = ET.tostring(root, encoding="unicode")
    return xml[:m.start()] + out + xml[m.end():]


def _set_list(el, form: str, val: str) -> None:
    import xml.etree.ElementTree as ET
    for ch in list(el):
        el.remove(ch)
    el.text = None
    box = ET.SubElement(el, _q("rdf", "Alt" if form == "alt" else "Seq"))
    li = ET.SubElement(box, _q("rdf", "li"))
    if form == "alt":
        li.set(_q("xml", "lang"), "x-default")
    li.text = val


def write_info(pdf_path, fields: dict, password: str | None = None, source=None) -> dict:
    """`pdf_path`(저장 길의 **임시 파일**)의 Info·XMP 에 네 값을 쓴다 — 덧붙여 저장(암호화 그대로).
    암호 문서면 `password`, 없으면 `source`(원본 경로)로 이번 실행에서 연 암호. 반환 {"xmp": "updated"|"none"|"kept"}.
    **배경 스레드에서만**(파일을 연다)."""
    import fitz
    fields = {f: (fields.get(f) or "").strip() for f in FIELDS if f in (fields or {})}
    if not fields:
        return {"xmp": "none"}
    doc = fitz.open(str(pdf_path))
    try:
        if doc.needs_pass:
            pw = password
            if pw is None:
                try:
                    from viewer import secure_store
                    pw = secure_store.get_session(str(source or pdf_path))
                except Exception:
                    pw = None
            if not (pw and doc.authenticate(pw)):
                raise RuntimeError("암호를 몰라 문서 정보를 쓰지 못했습니다")
        x = _info_xref(doc)
        for f, val in fields.items():
            doc.xref_set_key(x, INFO_KEY[f], fitz.get_pdf_str(val) if val else "null")
        xmp_state = "none"
        try:
            xml = doc.get_xml_metadata() or ""
        except Exception:
            xml = ""
        if xml.strip():
            new = update_xmp(xml, fields)
            if new is None:
                xmp_state = "kept"
            else:
                doc.set_xml_metadata(new)
                xmp_state = "updated"
        doc.save(str(pdf_path), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    finally:
        doc.close()
    return {"xmp": xmp_state}
