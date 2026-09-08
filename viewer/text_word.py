# -*- coding: utf-8 -*-
"""260908-2: 텍스트 창 내용을 **Word 로 저장** (텍스트 창 SOT §7).

- 범위는 부르는 쪽이 정한다 — 현재 쪽 / 쪽 범위 / 문서 전체(사용자 결정 260908).
- 문단 스타일은 창에서 정한 값(글꼴·크기·굵기·자간·줄간격)을 그대로 얹는다.
  제목은 `Heading 1`, 내용은 `Normal` 위에 올린다 — Word 의 목차·탐색창이 그대로 먹는다.
- 표는 **글줄**로 나간다(SOT §3.3·§7). 표 개체로 만들면 원본 구조를 반쯤 맞게 복원해
  오히려 고치기 번거롭다.
"""
from __future__ import annotations


def _apply_run(run, st):
    from docx.shared import Pt
    run.font.name = st.get("family", "맑은 고딕")
    run.font.size = Pt(float(st.get("size_pt", 11)))
    run.bold = bool(st.get("bold", False))
    try:                                    # 자간(pt) — 한글 글꼴 포함 동작
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        sp = float(st.get("spacing_pt", 0.0) or 0.0)
        if sp:
            el = OxmlElement("w:spacing")
            el.set(qn("w:val"), str(int(round(sp * 20))))   # twip(1/20 pt)
            run._element.get_or_add_rPr().append(el)
        # 한글 글꼴이 서양 글꼴로 밀리지 않게 eastAsia 도 지정
        rf = run._element.get_or_add_rPr().get_or_add_rFonts()
        rf.set(qn("w:eastAsia"), st.get("family", "맑은 고딕"))
    except Exception:
        pass


def export_pages_to_docx(pdf_path, doc_fitz, pages, dst, styles, *,
                         omit_tables: bool = False,
                         fix_lookup=None, ocr_lookup=None) -> tuple:
    """쪽 목록을 docx 로. 반환 (성공여부, 메시지)."""
    try:
        from docx import Document
        from docx.shared import Pt
    except Exception as e:                       # noqa: BLE001
        return False, f"python-docx 없음: {e}"
    from viewer import text_extract2 as tx

    out = Document()
    try:
        for pg in pages:
            ocr = ""
            if not tx.has_text_layer(doc_fitz, pg):
                ocr = (ocr_lookup(pg) if ocr_lookup else "") or ""
            rows = tx.page_lines(doc_fitz, pdf_path, pg,
                                 tables=("omit" if omit_tables else "lines"),
                                 ocr_text=ocr)
            fixes = (fix_lookup(pg) if fix_lookup else {}) or {}
            for i, t in fixes.items():
                if 0 <= i < len(rows):
                    rows[i]["text"] = t
            if not rows:
                continue
            for r in rows:
                key = r.get("style", "body")
                st = (styles or {}).get(key, {})
                p = out.add_paragraph()
                if key == "title":
                    try:
                        p.style = out.styles["Heading 1"]
                    except Exception:
                        pass
                run = p.add_run(r.get("text", ""))
                _apply_run(run, st)
                try:
                    p.paragraph_format.line_spacing = float(
                        st.get("line_spacing", 1.2))
                except Exception:
                    pass
            if pg != pages[-1]:
                out.add_page_break()
        out.save(str(dst))
        return True, ""
    except Exception as e:                       # noqa: BLE001
        return False, str(e)
