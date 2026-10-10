# -*- coding: utf-8 -*-
"""일반뷰어용 저장 — 보기 회전을 넣고 쪽을 바로 세운다(`/Rotate` 0, 보이는 모양은 그대로) (마스터 §4.7.13, 261010-24).

PolyPDF 보기 회전(`page_meta.json` `rotation`)은 다른 뷰어에 없다 — 일반뷰어용은 '보던 그대로' 라 넣는다.
넣는 김에 `/Rotate` 를 0 으로 만든다(PyMuPDF `remove_rotation` — 내용을 돌려 다시 쓴다). 전자서명은 `/Rotate` 쪽에서
겉모양이 누워 막혀 있는데(보안 SOT §3.3), 바로 세운 쪽은 그대로 서명된다.

`remove_rotation` 의 두 함정(실측):
  - 링크를 지운다 → 미리 읽어 `rotation_matrix` 로 옮겨 다시 넣는다
  - PDF 주석 자리를 옮기지 못한다(90° 는 쪽 밖으로) → 회전할 쪽이 있으면 문서의 주석·양식을 먼저 내용으로 굽는다(사용자 결정)
"""
from __future__ import annotations


def targets(doc, view_rot: dict | None = None) -> list:
    """[(쪽 번호, 합친 회전)] — `(PDF /Rotate + 보기 회전) % 360` 이 0 이 아닌 쪽."""
    out = []
    vr = view_rot or {}
    for i in range(doc.page_count):
        r = (int(doc[i].rotation) + int(vr.get(i, 0) or 0)) % 360
        if r:
            out.append((i, r))
    return out


def _crop_to_media(doc, page) -> None:
    """`/CropBox` 가 `/MediaBox` 와 다르면 PDF 값 그대로 `/MediaBox` 에 옮긴다(보이는 범위는 같다).
    PyMuPDF `set_mediabox(page.cropbox)` 는 MediaBox 원점이 0 이 아닌 쪽에서 내용이 밀렸다(실측 — 마스터 §4.7.15 와 같은 함정)."""
    try:
        t, cb = doc.xref_get_key(page.xref, "CropBox")
        if t == "null":
            return
        _t, mb = doc.xref_get_key(page.xref, "MediaBox")
        if cb.split() == mb.split():
            return
        doc.xref_set_key(page.xref, "MediaBox", cb)
        doc.xref_set_key(page.xref, "CropBox", "null")
    except Exception:
        pass


def make_upright(doc, view_rot: dict | None = None):
    """돌릴 쪽을 바로 세운다. (문서, 바로 세운 쪽 수) — **돌려준 문서를 쓴다**(새로 열어 만든 사본일 수 있다).
    굽기·크롭이 끝난 뒤 **마지막에** 부른다."""
    todo = targets(doc, view_rot)
    if not todo:
        return doc, 0
    import fitz
    try:
        doc.bake(annots=True, widgets=True)
    except Exception:
        pass
    # 같은 세션에 넣은 링크(하이퍼링크 굽기)는 get_links 에 나오지 않는다(실측) — 바이트로 다시 연 사본에서 한다
    doc = fitz.open("pdf", doc.tobytes())
    n = 0
    for i, r in todo:
        page = doc[i]
        # CropBox 가 MediaBox 와 다르면 remove_rotation 이 내용을 잃는다(실측: 180° 에서 글자가 사라짐) — 보이는 범위로
        #   쪽을 맞춘다. 일반뷰어용은 이미 크롭 바깥을 지웠으므로(§4.7.15) 보통은 같다.
        _crop_to_media(doc, page)
        links = page.get_links()
        # remove_rotation 은 링크를 엉뚱한 자리로 옮긴다(실측) — 지우고, 맞게 옮겨 다시 넣는다
        for ln in links:
            try:
                page.delete_link(ln)
            except Exception:
                pass
        # get_links 의 자리는 **지금 /Rotate 로 보이는** 좌표다(실측) — 회전 전 좌표로 되돌린 뒤 새 회전으로 보낸다
        derot = page.derotation_matrix
        page.set_rotation(r)
        mat = derot * page.rotation_matrix             # 옛 보이는 좌표 → 회전 전 → 새로 보이는 좌표 = 바로 세운 뒤 좌표
        page.remove_rotation()
        for ln in links:
            nl = {k: v for k, v in ln.items() if k not in ("xref", "id", "zoom")}
            r2 = ln["from"] * mat
            r2.normalize()
            nl["from"] = r2
            try:
                page.insert_link(nl)
            except Exception:
                pass
        n += 1
    return doc, n
