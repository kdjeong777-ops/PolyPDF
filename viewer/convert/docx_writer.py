# -*- coding: utf-8 -*-
"""Word 머리글·바닥글 (형식 변환 SOT §1.1) — pdf2docx 가 만든 docx 에 넣는다(`proc._put_header_footer`).

종전의 python-docx 흐르는 '편집 가능' 쓰기는 261113-3 에 pdf2docx 길(§4.1 고침 8)로 바뀌어 지웠다.
"""
from __future__ import annotations

from viewer.convert import layout


def set_hf_distance(sec, per_page) -> None:
    """머리글·바닥글 자리 = 원본 머리말 위쪽·꼬리말 아래쪽(쪽 높이 비율로 옮긴다)."""
    from docx.shared import Pt
    ph = sec.page_height.pt
    edges = [e for es in per_page.values() for e in es]
    heads = [e["rect"][1] / float(e.get("ph") or ph) for e in edges if e["where"] == "head"]
    foots = [e["rect"][3] / float(e.get("ph") or ph) for e in edges if e["where"] == "foot"]
    if heads:
        sec.header_distance = Pt(max(0.0, min(heads) * ph))
    if foots:
        sec.footer_distance = Pt(max(0.0, (1.0 - max(foots)) * ph))


def _page_field(run) -> None:
    """런 안에 Word 쪽 번호 필드(PAGE)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    for kind, text in (("begin", None), (None, " PAGE "), ("separate", None), (None, "1"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        elif text == " PAGE ":
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        else:
            el = OxmlElement("w:t")
            el.text = text
        run._r.append(el)


def _header_footer(out, sec, plan) -> None:
    """머리말·꼬리말(형식 변환 SOT §1.1) — Word 머리글·바닥글 기능으로, 쪽 번호는 PAGE 필드, 홀·짝이 다르면 따로."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt
    al = {"LEFT": WD_ALIGN_PARAGRAPH.LEFT, "CENTER": WD_ALIGN_PARAGRAPH.CENTER, "RIGHT": WD_ALIGN_PARAGRAPH.RIGHT}
    if any(k in plan[w] for w in ("head", "foot") for k in ("ODD", "EVEN")):
        out.settings.odd_and_even_pages_header_footer = True
    for where in ("head", "foot"):
        for kind, lines in plan[where].items():
            if kind == "EVEN":
                part = sec.even_page_header if where == "head" else sec.even_page_footer
            else:
                part = sec.header if where == "head" else sec.footer
            part.is_linked_to_previous = False
            first = True
            for ln in lines:
                pw = sec.page_width.pt
                text, align, indent = layout.compose(ln, pw, sec.left_margin.pt, pw - sec.right_margin.pt)
                para = part.paragraphs[0] if first and part.paragraphs else part.add_paragraph()
                first = False
                para.alignment = al.get(align)
                pf = para.paragraph_format
                pf.left_indent = Pt(indent) if indent else None
                pf.space_before = pf.space_after = Pt(0)       # 기본 서식의 문단 뒤 간격이 바닥글을 위로 민다
                pf.line_spacing = 1.0
                bits = text.split(layout.NUM_TOKEN)
                for k, bit in enumerate(bits):
                    run = para.add_run(bit)
                    run.font.size = Pt(ln["size"])
                    run.font.bold = bool(ln["bold"])
                    run.font.name = layout.SERIF_FACE if ln["serif"] else layout.SANS_FACE
                    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), run.font.name)
                    if k < len(bits) - 1:
                        _page_field(para.add_run())
    start = plan.get("start")
    if start and int(start) > 1:
        pg = OxmlElement("w:pgNumType")
        pg.set(qn("w:start"), str(int(start)))
        sec._sectPr.append(pg)
