# -*- coding: utf-8 -*-
"""Word(편집 가능) 쓰기 — python-docx (형식 변환 SOT §1, 261014-14).

HWPX 편집 가능과 같은 블록(`layout.page_blocks(join=True)`): 이은 문단, 제목은 'Heading 1', 표는 'Table Grid' 표,
그림은 원본 크기(글 너비를 넘으면 줄인다), 쪽 사이 쪽 나눔. 쪽 크기는 첫 쪽에 맞춘다.
"""
from __future__ import annotations

import io
from pathlib import Path

from viewer.convert import layout

TITLE_STYLE = "Heading 1"      # Word 기본 서식 이름(문서 안의 스타일 키 — 화면 문구가 아니다)
TABLE_STYLE = "Table Grid"
MARGIN_PT = 56.7               # 쪽 여백 2 cm


def write_docx_edit(ps, pages, dst: Path, tick) -> None:
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Pt
    out = Document()
    sec = out.sections[0]
    if pages:
        r = ps.doc.load_page(int(pages[0])).rect
        sec.page_width, sec.page_height = Pt(r.width), Pt(r.height)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Pt(MARGIN_PT)
    text_w = sec.page_width.pt - 2 * MARGIN_PT
    body = out.paragraphs[0] if out.paragraphs else None     # 빈 첫 문단 — 처음 쓰는 문단으로 쓴다

    def para(text="", style=None):
        nonlocal body
        if body is not None:
            p, body = body, None
            if text:
                p.add_run(text)
            if style:
                p.style = style
            return p
        return out.add_paragraph(text, style=style)

    for i, pg in enumerate(pages):
        tick(i, len(pages), f"p.{pg + 1}")
        if i:
            para().add_run().add_break(WD_BREAK.PAGE)
        for b in layout.page_blocks(ps, pg, join=True):
            if b["kind"] == "line":
                style = TITLE_STYLE if b.get("style") == "title" else None
                try:
                    para(b["text"], style)
                except KeyError:
                    para(b["text"])
            elif b["kind"] == "table":
                rows = b["rows"]
                t = out.add_table(rows=len(rows), cols=max(len(r) for r in rows))
                try:
                    t.style = TABLE_STYLE
                except Exception:
                    pass
                for ri, r in enumerate(rows):
                    for ci, c in enumerate(r):
                        if c:
                            t.cell(ri, ci).text = str(c)
                body = None
            else:
                x0, y0, x1, y1 = b["rect"]
                w, h = x1 - x0, y1 - y0
                if w > text_w:
                    w, h = text_w, h * text_w / w
                data = b["data"]
                try:
                    para().add_run().add_picture(io.BytesIO(data), width=Pt(w), height=Pt(h))
                except Exception:
                    continue                             # Word 가 못 받는 그림 형식 — 건너뛴다
    tick(len(pages), len(pages), "")
    out.save(str(dst))
