# -*- coding: utf-8 -*-
"""가림 — 개인정보를 실제로 지운다 (보안 SOT §14, 261014-22).

- `find_marks` — 패턴·검색어로 가릴 자리(글자층은 글자 상자, 스캔 쪽은 우리 OCR 낱말 상자). 배경 스레드에서.
- `apply` — 자리마다 가림 주석 → `apply_redactions`(글 빼기·그림 화소 지우기·선 지우기) → 숨은 데이터 지우기 →
  새 파일(`garbage=4`). 저장 뒤 가린 자리에 글이 남지 않았는지 다시 뽑아 본다.
"""
from __future__ import annotations

from pathlib import Path

from viewer.i18n import tr, tr_noop

# (키, 화면 이름, 정규식) — 정규식은 OCR 이 빼먹거나 더 띄운 빈칸도 견딘다
REDACT_PATTERNS = (
    ("rrn", tr_noop("주민등록번호"), r"(?<!\d)\d{6}\s*-\s*[1-4]\d{6}(?!\d)"),
    ("phone", tr_noop("전화번호"), r"(?<!\d)0\d{1,2}\s*[-.)]\s*\d{3,4}\s*[-.]\s*\d{4}(?!\d)"),
    ("email", tr_noop("이메일"), r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    ("card", tr_noop("카드번호"), r"(?<!\d)\d{4}\s*[- ]\s*\d{4}\s*[- ]\s*\d{4}\s*[- ]\s*\d{4}(?!\d)"),
    ("bizno", tr_noop("사업자등록번호"), r"(?<!\d)\d{3}\s*-\s*\d{2}\s*-\s*\d{5}(?!\d)"),
)
KIND_AREA = tr_noop("영역")
KIND_SEARCH = tr_noop("검색어")
FILL = (0, 0, 0)


class Refused(Exception):
    """가릴 수 없는 파일 — 까닭(`tr_noop` 문구)."""


REFUSE_ENCRYPTED = tr_noop("암호 PDF 입니다 — 사본이 암호 없이 저장되므로 암호를 풀고 다시 하세요")


def out_path(src) -> Path:
    from viewer.pathutil import unique_path
    s = Path(src)
    return unique_path(s.with_name(tr("{stem}_가림").format(stem=s.stem) + ".pdf"), first=2)


def _ocr_lines(words, dpi):
    """OCR 낱말(픽셀) → 줄마다 `(글, [(시작, 끝, 사각형 pt)])` — 같은 높이 낱말을 왼쪽부터 빈칸 하나로 잇는다."""
    k = 72.0 / float(dpi or 72)
    items = []
    for w in words or []:
        try:
            r = (float(w["x0"]) * k, float(w["y0"]) * k, float(w["x1"]) * k, float(w["y1"]) * k)
            t = str(w.get("surface") or "")
        except Exception:
            continue
        if t.strip():
            items.append((r, t))
    items.sort(key=lambda it: ((it[0][1] + it[0][3]) / 2, it[0][0]))
    lines = []
    for r, t in items:
        cy, h = (r[1] + r[3]) / 2, r[3] - r[1]
        if lines and abs(lines[-1]["cy"] - cy) <= max(2.0, 0.5 * h):
            lines[-1]["w"].append((r, t))
        else:
            lines.append({"cy": cy, "w": [(r, t)]})
    out = []
    for ln in lines:
        ws = sorted(ln["w"], key=lambda q: q[0][0])
        text, spans = "", []
        for r, t in ws:
            if text:
                text += " "
            spans.append((len(text), len(text) + len(t), r))
            text += t
        out.append((text, spans))
    return out


def _ocr_hits(lines, matcher):
    import fitz
    hits = []
    for text, spans in lines:
        for s, e in matcher.spans(text):
            rr = None
            for a, b, r in spans:
                if a < e and b > s:
                    rr = fitz.Rect(r) if rr is None else rr | fitz.Rect(r)
            if rr is not None:
                hits.append((rr, text[s:e]))
    return hits


def find_marks(path, keys=(), custom: str = "", custom_regex: bool = False, tick=None) -> list:
    """가릴 자리 `[{page, rect, kind, text}]`. `tick(했음, 전체, 글)` 이 예외를 던지면 멈춘다."""
    import fitz
    from viewer import text_extract2 as tx
    from viewer.search_match import Matcher, match_rects
    matchers = [(lab, Matcher(rx, case=True, regex=True)) for k, lab, rx in REDACT_PATTERNS if k in set(keys)]
    if custom.strip():
        matchers.append((KIND_SEARCH, Matcher(custom.strip(), case=False, regex=bool(custom_regex))))
    if not matchers:
        return []
    st, fkey = None, None
    try:
        from viewer.study.study_store import StudyStore, file_key_for
        st, fkey = StudyStore(), file_key_for(str(path))
    except Exception:
        st = None
    doc = fitz.open(str(path))
    out = []
    try:
        if doc.needs_pass:
            raise Refused(REFUSE_ENCRYPTED)
        n = doc.page_count
        for pg in range(n):
            if tick:
                tick(pg, n, f"p.{pg + 1}")
            page = doc.load_page(pg)
            if tx.has_text_layer(doc, pg):
                for lab, m in matchers:
                    for r in match_rects(page, m):
                        out.append({"page": pg, "rect": tuple(r), "kind": lab,
                                    "text": page.get_textbox(r).strip()})
            elif st is not None:
                try:
                    words = st.get_page_words(fkey, pg) or []
                    dpi = int(st.get_page_dpi(fkey, pg) or 0)
                except Exception:
                    words, dpi = [], 0
                if words:
                    lines = _ocr_lines(words, dpi)
                    for lab, m in matchers:
                        for r, t in _ocr_hits(lines, m):
                            out.append({"page": pg, "rect": tuple(r), "kind": lab, "text": t})
    finally:
        doc.close()
        if st is not None:
            try:
                st.close()
            except Exception:
                pass
    return out


def apply(path, marks, *, scrub: bool = True, tick=None) -> tuple:
    """새 파일에 가려 저장 → `(결과 경로, 남은 글 목록)`. 남은 글이 있으면 부르는 쪽이 경고한다."""
    import fitz
    src = str(path)
    dst = out_path(src)
    doc = fitz.open(src)
    try:
        if doc.needs_pass:
            raise Refused(REFUSE_ENCRYPTED)
        by_page = {}
        for m in marks:
            by_page.setdefault(int(m["page"]), []).append(fitz.Rect(m["rect"]))
        pages = sorted(by_page)
        for i, pg in enumerate(pages):
            if tick:
                tick(i, len(pages) + 1, f"p.{pg + 1}")
            page = doc.load_page(pg)
            for r in by_page[pg]:
                page.add_redact_annot(r, fill=FILL)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS,
                                  graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                                  text=fitz.PDF_REDACT_TEXT_REMOVE)
        if scrub:
            # 숨은 글(hidden_text)은 지우지 않는다 — 스캔 문서의 OCR 글자층 전체가 사라진다. 링크·양식 값도 그대로
            doc.scrub(attached_files=True, clean_pages=True, embedded_files=True, hidden_text=False, javascript=True,
                      metadata=True, redactions=False, remove_links=False, reset_fields=False, reset_responses=True,
                      thumbnails=True, xml_metadata=True)
            doc.set_metadata({})
        if tick:
            tick(len(pages), len(pages) + 1, dst.name)
        doc.save(str(dst), garbage=4, deflate=True, clean=True)
    finally:
        doc.close()
    left = []
    chk = fitz.open(str(dst))
    try:
        for m in marks:
            r = fitz.Rect(m["rect"])
            got = chk.load_page(int(m["page"])).get_textbox(r + (1, 1, -1, -1)).strip()
            if got:
                left.append((int(m["page"]), got))
    finally:
        chk.close()
    return dst, left
