"""번역 산출물 Word/PDF 조립 (P4) — 서지(APA) → 요약 → 전문 → 용어집 + 책갈피.

SOT: `PDF 번역·요약 작업 계획서.md` §9.
- docx: python-docx. 순서 = 서지(첫머리) → 2줄 → 요약 → (다음 장) 전문(섹션 제목=Heading) → 용어집.
- PDF: Word(win32com) ExportAsFixedFormat + 제목(Heading) 책갈피. Word 없으면 docx 만.
- 그림/표 병기·표/그림 목차 책갈피·서식 템플릿은 후속(P4c).
"""
from __future__ import annotations

import os
import re

_SEC_KW = ("서론", "서 론", "머리말", "개요", "배경", "재료", "방법", "실험", "분석",
           "결과", "고찰", "토의", "논의", "결론", "참고문헌", "감사의", "부록",
           "introduction", "method", "material", "result", "discussion",
           "conclusion", "reference")


def _is_heading(s: str) -> bool:
    s = (s or "").strip()
    if not s or len(s) > 40:
        return False
    if re.match(r"^\d+(?:\.\d+)*\.?\s+\S", s):       # "2. 재료 및 방법", "3.1 시험"
        return True
    if len(s) <= 24 and not s.endswith((".", "다.", "다", ":", ";", ",")):
        low = s.lower()
        if any(k in low for k in _SEC_KW):
            return True
    return False


def _set_korean_font(doc, name="맑은 고딕"):
    try:
        from docx.oxml.ns import qn
    except Exception:
        return
    for sname in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
        try:
            st = doc.styles[sname]
            st.font.name = name
            rpr = st.element.get_or_add_rPr()
            rf = rpr.get_or_add_rFonts()
            rf.set(qn("w:eastAsia"), name)
        except Exception:
            pass


def build_docx(out_path, *, title="", citation="", summary="", translation="",
               glossary=None):
    """구조화 docx 저장(서지 → 요약 → 전문 → 용어집)."""
    from docx import Document
    doc = Document()
    _set_korean_font(doc)

    # 1) 첫머리: 서지(APA) — 본 논문 자체
    if (citation or "").strip():
        p = doc.add_paragraph()
        run = p.add_run(citation.strip())
        run.bold = True
    elif title:
        doc.add_paragraph(str(title)).runs and None

    # 2) 2줄 띄고 → 요약(같은 페이지)
    doc.add_paragraph("")
    doc.add_paragraph("")
    if (summary or "").strip():
        doc.add_heading("요약", level=1)
        for ln in summary.splitlines():
            ln = ln.rstrip()
            if ln.strip():
                doc.add_paragraph(ln)

    # 3) 요약이 끝나면 다음 장부터 전문 번역(섹션 제목 = Heading)
    doc.add_page_break()
    doc.add_heading("전문 번역", level=1)
    for para in (translation or "").split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if _is_heading(para):
            doc.add_heading(para, level=2)
        else:
            doc.add_paragraph(para)

    # 4) 용어집 부록
    gl = [g for g in (glossary or []) if g.get("en") and g.get("ko")]
    if gl:
        doc.add_page_break()
        doc.add_heading("용어집", level=1)
        t = doc.add_table(rows=1, cols=3)
        try:
            t.style = "Table Grid"
        except Exception:
            pass
        hc = t.rows[0].cells
        hc[0].text, hc[1].text, hc[2].text = "원어(EN)", "번역(KO)", "출처"
        for g in gl[:200]:
            c = t.add_row().cells
            c[0].text = g.get("en", "")
            c[1].text = g.get("ko", "")
            c[2].text = g.get("source", "")

    doc.save(out_path)
    return out_path


def docx_to_pdf(docx_path, pdf_path):
    """(성공, 메시지). Word(win32com)로 PDF 변환 + 제목(Heading) 책갈피. 스레드 안전(CoInitialize)."""
    pythoncom = None
    word = None
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        d = word.Documents.Open(os.path.abspath(docx_path))
        # 17=wdExportFormatPDF, CreateBookmarks=1=wdExportCreateHeadingBookmarks
        d.ExportAsFixedFormat(OutputFileName=os.path.abspath(pdf_path),
                              ExportFormat=17, CreateBookmarks=1)
        d.Close(False)
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}"
    finally:
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
        try:
            if pythoncom is not None:
                pythoncom.CoUninitialize()
        except Exception:
            pass


def _safe_name(name: str) -> str:
    return (re.sub(r'[\\/:*?"<>|]+', "_", name or "").strip() or "번역")[:120]


def save_translation_doc(folder, name, *, citation="", summary="", translation="",
                         glossary=None):
    """(docx_path, pdf_path|'', [진단]). 논문 폴더에 _번역.docx/.pdf 저장."""
    safe = _safe_name(name)
    docx_path = os.path.join(folder, f"{safe}_번역.docx")
    pdf_path = os.path.join(folder, f"{safe}_번역.pdf")
    build_docx(docx_path, title=name, citation=citation, summary=summary,
               translation=translation, glossary=glossary)
    ok, msg = docx_to_pdf(docx_path, pdf_path)
    dbg = ["docx 저장" + (" + PDF(책갈피)" if ok else f" (PDF 변환 실패: {msg})")]
    return docx_path, (pdf_path if ok else ""), dbg
