# -*- coding: utf-8 -*-
"""PolyPDF 꾸밈을 PDF 표준으로 — 'PolyPDF' 레이어(OCG)·보이는 좌표 얹기·링크·태그 사본 (261011-2, 마스터 §4.7.16).

편집 원본은 옆 파일(`page_meta.json`·`hyperlinks.json`·`file_tags.json`)이다. 이 모듈은 그 **사본**을 PDF 에 넣고 지운다.

- 꾸밈·사진: 그 쪽의 **보이는 크기** 빈 쪽(임시 문서)에 그린 그림을 `show_pdf_page(..., rotate=쪽 회전, oc=레이어)` 로 얹는다.
  PyMuPDF 의 그리기·`insert_link` 는 `/Rotate` 쪽에서 **회전 전 좌표**를 받는다(실측) — 그래서 보이는 좌표로 그린 임시 쪽을
  회전에 맞춰 얹는다. 레이어 없이(`oc=0`) 얹으면 평탄화(굽기)다.
- PolyPDF 화면은 그 레이어를 끈다(`hide_for_view`) — 옆 파일 꾸밈과 두 번 그려지지 않게.
Qt 를 쓰지 않는다(배경 작업·검사에서 그대로 부른다). 임시 쪽에 그리는 일(Qt 굽기)은 호출측이 한다.
"""
from __future__ import annotations

import hashlib
import json
import re

LAYER = "PolyPDF"          # 다른 뷰어 레이어 창에 보이는 이름 — 언어 중립(다국어 SOT §6)
LINK_NM = "PolyPDF:link"
HASH_KEY = "PolyPDFHash"
_DO = re.compile(rb"^\s*q\s*/([^\s/]+)\s+Do\s+Q\s*$")


def find_layer(doc) -> int:
    """레이어 OCG xref(목록에 있는 것), 없으면 0."""
    try:
        for x, info in (doc.get_ocgs() or {}).items():
            if info.get("name") == LAYER:
                return int(x)
    except Exception:
        pass
    return 0


def ensure_layer(doc) -> int:
    return find_layer(doc) or int(doc.add_ocg(LAYER, on=True))


def _is_layer_ocg(doc, ref: str) -> bool:
    m = re.match(r"\s*(\d+)\s+0\s+R", ref or "")
    if not m:
        return False
    try:
        t, v = doc.xref_get_key(int(m.group(1)), "Name")
        return t == "string" and v == LAYER
    except Exception:
        return False


def remove_layer(doc) -> int:
    """이 레이어에 묶인 XObject 를 부르는 내용 스트림(` q /이름 Do Q `)을 모든 쪽에서 뺀다. 뺀 쪽 수.
    레이어 OCG 는 이름으로 알아본다(쪽 편집 저장이 레이어 목록을 잃었을 수 있다)."""
    n = 0
    for page in doc:
        try:
            conts = page.get_contents()
        except Exception:
            continue
        if len(conts) < 2:
            continue
        keep, dropped = [], False
        for cx in conts:
            m = None
            try:
                m = _DO.match(doc.xref_stream(cx) or b"")
            except Exception:
                pass
            if m:
                name = m.group(1).decode("latin-1")
                t, ref = page.parent.xref_get_key(page.xref, f"Resources/XObject/{name}")
                if t == "xref":
                    xo = int(ref.split()[0])
                    if _is_layer_ocg(doc, doc.xref_get_key(xo, "OC")[1]):
                        try:
                            doc.xref_set_key(page.xref, f"Resources/XObject/{name}", "null")
                        except Exception:
                            pass
                        dropped = True
                        continue
            keep.append(cx)
        if dropped:
            doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in keep) + "]")
            n += 1
    return n


def hide_for_view(doc) -> bool:
    """열린 문서(저장하지 않을 것)에서 이 레이어를 끈다. **`set_layer(-1, off=…)` 로는 꺼지지 않는다**(실측)."""
    try:
        for c in doc.layer_ui_configs() or []:
            if c.get("text") == LAYER:
                doc.set_layer_ui_config(int(c["number"]), 2)
                return True
    except Exception:
        pass
    return False


def overlay_doc(doc):
    """`doc` 의 쪽마다 **보이는 크기**(회전·크롭 뒤 `page.rect`) 빈 쪽을 가진 임시 문서. 호출측이 여기에 그린다."""
    import fitz
    t = fitz.open()
    for page in doc:
        r = page.rect
        t.new_page(width=r.width, height=r.height)
    return t


def place(doc, overlay, oc: int = 0) -> int:
    """`overlay` 에서 그린 것이 있는 쪽만 `doc` 의 같은 쪽에 보이는 자리로 얹는다. 얹은 쪽 수.
    `oc` 를 주면 그 레이어에 묶고(사본), 0 이면 그냥 쪽 내용(평탄화)."""
    n = 0
    for i in range(min(doc.page_count, overlay.page_count)):
        try:
            if not overlay[i].get_contents():
                continue
        except Exception:
            continue
        pg = doc[i]
        pg.show_pdf_page(pg.rect * pg.derotation_matrix, overlay, i, rotate=int(pg.rotation), oc=int(oc or 0))
        n += 1
    return n


def to_unrotated(page, rect):
    """보이는 좌표 사각형 → 회전 전 좌표(`insert_link` 가 받는 좌표, 실측)."""
    r = rect * page.derotation_matrix
    r.normalize()
    return r


def remove_links(doc) -> int:
    """이전 사본 링크(`/NM` = PolyPDF:link)를 지운다."""
    n = 0
    for page in doc:
        for ln in list(page.get_links() or []):
            x = ln.get("xref") or 0
            try:
                t, v = doc.xref_get_key(x, "NM")
            except Exception:
                continue
            if t == "string" and v == LINK_NM:
                page.delete_link(ln)
                n += 1
    return n


def link_xrefs(page) -> set:
    try:
        return {int(x[0]) for x in (page.annot_xrefs() or []) if int(x[1]) == 1}     # 1 = PDF_ANNOT_LINK
    except Exception:
        return set()


def tag_links(page, before: set) -> int:
    """`before` 뒤에 생긴 링크에 사본 표시(`/NM`)를 붙인다 — `insert_link` 는 `/NM` 을 받지 않는다."""
    doc = page.parent
    n = 0
    for x in link_xrefs(page) - set(before or ()):
        doc.xref_set_key(x, "NM", f"({LINK_NM})")
        n += 1
    return n


def set_keywords(doc, keywords: str) -> None:
    md = dict(doc.metadata or {})
    md["keywords"] = keywords or ""
    doc.set_metadata(md)


def fingerprint(payload) -> str:
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _info_xref(doc, create: bool = False) -> int:
    t, v = doc.xref_get_key(-1, "Info")
    if t == "xref":
        return int(v.split()[0])
    if create:
        doc.set_metadata(dict(doc.metadata or {}))
        t, v = doc.xref_get_key(-1, "Info")
        if t == "xref":
            return int(v.split()[0])
    return 0


def stored_hash(doc) -> str:
    """지난 사본의 지문 — 문서 정보(Info)의 `/PolyPDFHash`. 레이어에 두지 않는다(꾸밈 없이 태그만 있는 문서에 빈 레이어가 생긴다)."""
    try:
        x = _info_xref(doc)
        if not x:
            return ""
        t, v = doc.xref_get_key(x, HASH_KEY)
        return v if t == "string" else ""
    except Exception:
        return ""


def store_hash(doc, h: str) -> None:
    x = _info_xref(doc, create=True)
    if x:
        doc.xref_set_key(x, HASH_KEY, f"({h})")


def geometry(doc) -> list:
    """쪽마다 (보이는 폭, 높이, 회전) — 회전·크기가 바뀌면 사본을 다시 얹는다."""
    return [(round(p.rect.width, 1), round(p.rect.height, 1), int(p.rotation)) for p in doc]


# ── 평탄화 내보내기 재서명 표식(보안 SOT §4.1) ─────────────────────────────
RESIGN_URI = "polypdf-resign:"


def mark_signatures(doc, keep_fields) -> int:
    """값이 있는 서명 칸을 지운다. `keep_fields` 에 든 칸은 자리를 숨은 표식 링크(`polypdf-resign:<칸>`)로 남긴다.
    인증 서명이 가리키던 `/Perms` 도 지운다(지운 서명을 가리키게 두지 않는다). 지운 칸 수."""
    import fitz
    keep = set(keep_fields or ())
    n = 0
    for page in doc:
        for w in list(page.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]) or []):
            if not getattr(w, "is_signed", False):
                continue                          # 빈 서명 칸은 그대로
            name = str(w.field_name or "")
            if name in keep:
                page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(w.rect), "uri": RESIGN_URI + name})
            page.delete_widget(w)
            n += 1
    if n:
        cat = doc.pdf_catalog()
        try:
            doc.xref_set_key(cat, "Perms", "null")
        except Exception:
            pass
        # 마지막 칸을 지우면 PyMuPDF 가 AcroForm 객체를 지우는데 카탈로그는 그것을 계속 가리켜 저장 때
        #   'cannot find object' 를 낸다(실측) — 남은 칸이 없으면 끊는다
        try:
            if not any(True for pg in doc for _w in (pg.widgets() or [])):
                doc.xref_set_key(cat, "AcroForm", "null")
        except Exception:
            pass
    return n


def take_marks(doc) -> dict:
    """표식 링크를 읽어 지운다 → {칸 이름: (쪽, PDF 사용자 공간 상자)}. 같은 세션에서 넣은 링크는 `get_links` 에
    나오지 않아(실측) 주석 사전의 `/Rect`(PDF 좌표 — 크롭으로 쪽 상자가 바뀌어도 그대로)로 읽는다."""
    out = {}
    for page in doc:
        t, v = doc.xref_get_key(page.xref, "Annots")
        if t not in ("array", "xref"):
            continue
        if t == "xref":
            arr_x = int(v.split()[0])
            v = doc.xref_object(arr_x, compressed=True)
        refs = [int(m) for m in re.findall(r"(\d+)\s+0\s+R", v)]
        keep = []
        for x in refs:
            tu, uri = doc.xref_get_key(x, "A/URI")
            if tu == "string" and uri.startswith(RESIGN_URI):
                tr_, rect = doc.xref_get_key(x, "Rect")
                nums = [float(z) for z in re.findall(r"-?[\d.]+", rect)]
                if len(nums) == 4:
                    x0, y0, x1, y1 = nums
                    out[uri[len(RESIGN_URI):]] = (page.number, (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
                continue
            keep.append(x)
        if len(keep) != len(refs):
            doc.xref_set_key(page.xref, "Annots", "[" + " ".join(f"{x} 0 R" for x in keep) + "]")
    return out
