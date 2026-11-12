# -*- coding: utf-8 -*-
"""Word(모양 그대로) — pdf2docx 를 보조 프로세스에서 (형식 변환 SOT §4.1, 261014-13; 방식 이름은 261014-14).

pdf2docx 는 순수 파이썬이라 느리고(GIL 을 오래 쥔다) 메모리가 크다. 그래서 색인과 **같은 자식 프로세스 틀**
(`index_proc.run_job` — 파이프·진행·취소·작업 개체·낮은 우선순위)로 `PolyPDF.exe --convert-server` 를 띄운다.
자식은 일감 하나를 하고 끝난다 — 끝나면 메모리를 모두 돌려준다(응답성 SOT §9.2).

스캔 쪽(글자층 없음)이 범위에 있으면 우리 OCR 결과를 보이지 않는 글자층으로 넣은 **임시 사본**(임시 폴더)을 넘긴다
(`text_apply.build_layer_pdf(out=)` — 텍스트 창 [PDF 에 반영] 과 같은 길).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from viewer.i18n import tr

SERVER_ARG = "--convert-server"
KEY_ENV = "POLYPDF_CONVERT_KEY"
TEMP_PREFIX = "polypdf_conv_"      # 스캔 쪽·머리말 가린 사본의 전용 임시 폴더(temp_sweep.APP_TEMP_PREFIXES 에도 있다)


def _is_original(src, orig) -> bool:
    """변환할 것이 원본 그 자체인가 — 실제 경로로(형식 변환 SOT §4.1 '임시 폴더 지우기', 261112-14)."""
    from viewer.temp_sweep import same_path
    return same_path(src, orig)


def remove_copy(src, orig) -> None:
    """사본이면 그 전용 임시 폴더를 지운다 — 전용 폴더일 때만(마스터 §14.8.1). 원본이면 아무것도 하지 않는다."""
    if not src or _is_original(src, orig):
        return
    from viewer.temp_sweep import remove_own_temp_dir
    remove_own_temp_dir(Path(src).parent, TEMP_PREFIX, who="convert")


def _layered_copy(ps, pages, tick) -> str | None:
    """범위 안의 스캔 쪽에 우리 OCR 글자층을 넣은 임시 사본. 넣을 쪽이 없으면 None(원본을 그대로 변환)."""
    from viewer import text_extract2 as tx
    scan = [p for p in pages if not tx.has_text_layer(ps.doc, int(p)) and ps.ocr_text(p)]
    if not scan:
        return None
    from viewer import text_apply
    from viewer.convert import step_text
    out = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX)) / "layered.pdf"
    tmp, _stats = text_apply.build_layer_pdf(
        ps.path, scan,
        rows_for=lambda _doc, pg: ps.lines(pg), fixes_for=lambda _pg, rows: rows,   # ps.lines 가 이미 고침을 얹었다
        out=str(out), progress=lambda k, n, pg: tick(0, 1, step_text(
            "ocr", min(int(k) + 1, int(n)), n, int(pg) + 1 if int(pg) >= 0 else None, ps.page_count)))
    return tmp or None


def convert_docx(ps, pages, dst: Path, tick, mode: str = "shape") -> None:
    """부모 쪽 — 배경 스레드에서 부른다. `tick` 이 `Cancelled` 를 던지면 자식을 멈추고 결과를 지운다(부르는 쪽이).
    `mode` — "shape"(모양 그대로: 원본 줄마다 끊음) / "edit"(편집 가능: 텍스트 창이 이은 줄만 잇는다) — §1·§4.1 고침 8(261113-3)."""
    from viewer import index_proc
    from viewer.convert import Cancelled, step_text
    from viewer.convert import word_fit
    src = _layered_copy(ps, pages, tick) or ps.path
    # 머리말·꼬리말(§1.1): 사본에서 그 글을 지우고 변환한 뒤 Word 머리글·바닥글 기능으로 다시 넣는다
    from viewer.convert import layout
    per_page = {}
    plan = {"mode": mode, "pages": {}}
    for k, pg in enumerate(pages):
        tick(0, 1, step_text("edges", k + 1, len(pages), int(pg) + 1, ps.page_count))
        per_page[int(pg)] = layout.page_edges(ps, pg)
        if mode == "edit":
            plan["pages"][int(pg)] = word_fit.page_plan(ps, pg)
    if any(per_page.values()):
        src = _without_edges(src, ps.path, per_page)
    state = {"cancel": False, "err": None}

    def on_progress(done, total, label):
        try:
            tick(int(done), max(1, int(total)), _child_step(done, total, label, ps.page_count))
        except Cancelled:
            state["cancel"] = True
    job = {"src": str(src), "dst": str(dst), "pages": [int(p) for p in pages],
           "plan": plan, "settings": dict(word_fit.MARGIN_SETTINGS)}
    try:
        ok = index_proc.run_job(job, on_progress, lambda: state["cancel"],
                                server_arg=SERVER_ARG, key_env=KEY_ENV, what="Word")
    finally:
        remove_copy(src, ps.path)
    if state["cancel"]:
        raise Cancelled()
    if ok is None:
        raise RuntimeError(tr("변환 프로세스를 띄우지 못했습니다"))
    if not Path(dst).exists():
        raise RuntimeError(tr("Word 파일을 만들지 못했습니다"))
    if any(per_page.values()):
        _put_header_footer(dst, layout.edge_plan(per_page), per_page)


def _child_step(done, total, label, doc_pages) -> str:
    """자식(pdf2docx 고침 3)이 보낸 `parse 33`·`make 12`(전체 = 쪽 수 × 2) → `쪽 분석 k/n · 원본 p쪽`(형식 변환 SOT §5, 261026-2).
    엔진의 날 글은 화면에 내지 않는다 — 모르는 글이면 단계만 없이 쪽 수만."""
    from viewer.convert import step_text
    n = max(1, int(total) // 2)
    word, _sp, num = str(label).partition(" ")
    page = int(num) if num.strip().isdigit() else None
    if word == "parse":
        return step_text("parse", int(done) + 1, n, page, doc_pages)
    if word == "make":
        return step_text("make", int(done) - n + 1, n, page, doc_pages)
    return step_text("pages", None, None, page, doc_pages)


def _without_edges(src: str, orig: str, per_page: dict) -> str:
    """머리말·꼬리말 글을 지운 임시 사본(그림·선은 그대로). `src` 가 이미 임시 사본이면 그것을 고친다."""
    import fitz
    if _is_original(src, orig):
        out = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX)) / "noedge.pdf"
    else:
        out = Path(src).with_name("noedge.pdf")
    doc = fitz.open(src)
    try:
        if doc.needs_pass:
            from viewer import secure_store
            doc.authenticate(secure_store.recall_any(orig) or "")
        for pg, edges in per_page.items():
            if not edges:
                continue
            page = doc.load_page(int(pg))
            for e in edges:
                page.add_redact_annot(fitz.Rect(e["rect"]) + (-0.5, -0.5, 0.5, 0.5))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
        doc.save(str(out))
    finally:
        doc.close()
    return str(out)


def _blank_part(part) -> None:
    """빈 머리글·바닥글 — 빈 문단도 기본 글꼴 높이를 차지해 Word 가 본문을 민다. 1 pt 로."""
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Pt
    part.is_linked_to_previous = False
    for p in part.paragraphs:
        pf = p.paragraph_format
        pf.space_before = pf.space_after = Pt(0)
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(1)
        for r in p.runs:
            r.font.size = Pt(1)


def _put_header_footer(dst, plan, per_page) -> None:
    """pdf2docx 가 만든 docx 에 머리글·바닥글 — **원본에 머리말·꼬리말이 있던 쪽의 구역에만**, 자리는 그 쪽의 자리로(§1.1·§1.2).
    pdf2docx 는 쪽마다 새 쪽 구역 하나 + 단 나눔용 이어지는 구역을 만든다 — 새 쪽 구역의 차례 = 변환한 쪽의 차례.
    261113-3: 종전에는 첫 구역 틀을 모든 구역이 따라, 머리말 없던 표지·목차 쪽(위 여백 22 pt)에도 머리글(거리 63 pt)이 들어가
    Word 가 본문을 밀었고 쪽마다 한 쪽씩 넘쳤다(별첨4 37 → 71쪽)."""
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.shared import Pt
    from viewer.convert.docx_writer import _header_footer, set_hf_distance
    out = Document(str(dst))
    secs = list(out.sections)
    if not secs:
        return
    pages = sorted(int(p) for p in per_page)
    k = -1
    for i, s in enumerate(secs):
        if i == 0 or s.start_type != WD_SECTION.CONTINUOUS:
            k += 1
        pg = pages[min(k, len(pages) - 1)] if pages else None
        edges = per_page.get(pg) or []
        has = {w: any(e["where"] == w for e in edges) for w in ("head", "foot")}
        sub = {"head": plan["head"] if has["head"] else {}, "foot": plan["foot"] if has["foot"] else {},
               "start": plan.get("start") if i == 0 else None}
        _header_footer(out, s, sub)
        for where, parts in (("head", (s.header, s.even_page_header)), ("foot", (s.footer, s.even_page_footer))):
            if not has[where]:
                for part in parts:
                    _blank_part(part)
                if where == "head":
                    s.header_distance = Pt(0)
                else:
                    s.footer_distance = Pt(0)
        set_hf_distance(s, {pg: edges} if pg is not None else per_page)
        _bottom_slack(s, edges, has["foot"])
    for p in out.paragraphs:                    # 구역 끝 빈 문단(pdf2docx 가 쪽 끝에 둔다) — 넘치면 빈 쪽이 생긴다(§1.2)
        ppr = p._p.pPr
        if ppr is not None and ppr.sectPr is not None and not p.text.strip():
            _blank_para(p)
    if out.paragraphs and not out.paragraphs[-1].text.strip():
        _blank_para(out.paragraphs[-1])
    out.save(str(dst))


BOTTOM_FLOOR_PT = 20.0      # 꼬리말 없는 쪽의 아래 여백 하한(§1.2 — 본문 아래에 남기는 여유)


def _blank_para(p) -> None:
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Pt
    pf = p.paragraph_format
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(1)


def _bottom_slack(sec, edges, has_foot) -> None:
    """아래 여백을 꼬리말 위(없으면 `BOTTOM_FLOOR_PT`)까지 낮춘다 — 본문 자리는 위에서부터 정해져 아무것도 움직이지 않고,
    마지막 줄이 몇 pt 넘쳐 한 쪽이 더 생기던 것만 막는다(§1.2, 261113-3)."""
    from docx.shared import Pt
    try:
        ph = sec.page_height.pt
        cur = sec.bottom_margin.pt
        if has_foot:
            top = min(e["rect"][1] for e in edges if e["where"] == "foot")
            want = ph * (1.0 - top / float(edges[0].get("ph") or ph)) + 2.0
        else:
            want = BOTTOM_FLOOR_PT
        if want < cur:
            sec.bottom_margin = Pt(max(0.0, want))
    except Exception:
        pass


def serve(address: str) -> None:
    """자식 쪽 — `main.py` 가 PyQt 를 싣기 전에 부른다. 일감 하나를 하고 끝난다."""
    from multiprocessing.connection import Client
    key = bytes.fromhex(os.environ.get(KEY_ENV, ""))
    conn = Client(address, family="AF_PIPE", authkey=key)
    try:
        job = conn.recv()
    except (EOFError, OSError):
        return
    try:
        if job.get("kind") == "compress":            # 261014-21(마스터 §4.7.19): PDF 압축 — 같은 자식 틀
            from viewer.pdf_compress import compress_file
            conn.send(("progress", 0, 1, os.path.basename(job["src"])))
            try:
                compress_file(job["src"], job["dst"], job.get("level", "mid"))
            except Exception:
                try:
                    os.remove(job["dst"])
                except Exception:
                    pass
                raise
            conn.send(("done",))
            return
        import logging
        logging.disable(logging.CRITICAL)             # pdf2docx 의 쪽마다 로그 — 자식은 창도 콘솔도 없다
        from viewer._vendor.pdf2docx import Converter
        from viewer._vendor.pdf2docx.converter import ConversionCancelled

        def progress(done, total, label):
            if conn.poll(0):                           # 부모가 보낸 아무 말 = 취소
                return False
            conn.send(("progress", done, total, label))
            return True
        # 고침 8(261113-3): 줄 잇기·쪽 맞춤·글꼴 걸이 — 계획이 없는 옛 일감도 모양 그대로(줄마다 끊음)로
        from viewer._vendor.pdf2docx import polypdf_fit
        from viewer.convert.word_fit import Hook
        polypdf_fit.HOOK = Hook(job.get("plan"))
        cv = Converter(job["src"])
        try:
            cv.convert(job["dst"], pages=job.get("pages") or None, progress=progress, **(job.get("settings") or {}))
        except ConversionCancelled:
            try:
                os.remove(job["dst"])
            except Exception:
                pass
            return
        finally:
            cv.close()
        conn.send(("done",))
    except (EOFError, OSError):
        return
    except Exception as e:                             # noqa: BLE001
        try:
            conn.send(("error", str(e)))
        except Exception:
            pass
