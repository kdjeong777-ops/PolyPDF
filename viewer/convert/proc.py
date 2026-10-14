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


def _layered_copy(ps, pages, tick) -> str | None:
    """범위 안의 스캔 쪽에 우리 OCR 글자층을 넣은 임시 사본. 넣을 쪽이 없으면 None(원본을 그대로 변환)."""
    from viewer import text_extract2 as tx
    scan = [p for p in pages if not tx.has_text_layer(ps.doc, int(p)) and ps.ocr_text(p)]
    if not scan:
        return None
    from viewer import text_apply
    out = Path(tempfile.mkdtemp(prefix="polypdf_conv_")) / "layered.pdf"
    tmp, _stats = text_apply.build_layer_pdf(
        ps.path, scan,
        rows_for=lambda _doc, pg: ps.lines(pg), fixes_for=lambda _pg, rows: rows,   # ps.lines 가 이미 고침을 얹었다
        out=str(out), progress=lambda k, n, pg: tick(0, 1, "OCR p.%d" % (int(pg) + 1)))
    return tmp or None


def convert_docx(ps, pages, dst: Path, tick) -> None:
    """부모 쪽 — 배경 스레드에서 부른다. `tick` 이 `Cancelled` 를 던지면 자식을 멈추고 결과를 지운다(부르는 쪽이)."""
    from viewer import index_proc
    from viewer.convert import Cancelled
    src = _layered_copy(ps, pages, tick) or ps.path
    # 머리말·꼬리말(§1.1): 사본에서 그 글을 지우고 변환한 뒤 Word 머리글·바닥글 기능으로 다시 넣는다
    from viewer.convert import layout
    per_page = {}
    for k, pg in enumerate(pages):
        tick(0, 1, "p.%d" % (int(pg) + 1))
        per_page[int(pg)] = layout.page_edges(ps, pg)
    if any(per_page.values()):
        src = _without_edges(src, ps.path, per_page)
    state = {"cancel": False, "err": None}

    def on_progress(done, total, label):
        try:
            tick(int(done), max(1, int(total)), str(label))
        except Cancelled:
            state["cancel"] = True
    job = {"src": str(src), "dst": str(dst), "pages": [int(p) for p in pages]}
    try:
        ok = index_proc.run_job(job, on_progress, lambda: state["cancel"],
                                server_arg=SERVER_ARG, key_env=KEY_ENV, what="Word")
    finally:
        if src != ps.path:
            import shutil
            shutil.rmtree(Path(src).parent, ignore_errors=True)
    if state["cancel"]:
        raise Cancelled()
    if ok is None:
        raise RuntimeError(tr("변환 프로세스를 띄우지 못했습니다"))
    if not Path(dst).exists():
        raise RuntimeError(tr("Word 파일을 만들지 못했습니다"))
    if any(per_page.values()):
        _put_header_footer(dst, layout.edge_plan(per_page), per_page)


def _without_edges(src: str, orig: str, per_page: dict) -> str:
    """머리말·꼬리말 글을 지운 임시 사본(그림·선은 그대로). `src` 가 이미 임시 사본이면 그것을 고친다."""
    import fitz
    if src == orig:
        out = Path(tempfile.mkdtemp(prefix="polypdf_conv_")) / "noedge.pdf"
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


def _put_header_footer(dst, plan, per_page) -> None:
    """pdf2docx 가 만든 docx 의 첫 구역에 머리글·바닥글(뒤 구역은 앞을 따른다). 머리글 자리는 원본 머리말 자리."""
    from docx import Document
    from viewer.convert.docx_writer import _header_footer, set_hf_distance
    out = Document(str(dst))
    secs = out.sections
    if not secs:
        return
    sec = secs[0]
    _header_footer(out, sec, plan)
    for k, s2 in enumerate(secs):
        if k:                                  # 뒤 구역은 첫 구역을 따른다(구역 개체는 꺼낼 때마다 새것 — 번호로 가른다)
            s2.header.is_linked_to_previous = True
            s2.footer.is_linked_to_previous = True
        set_hf_distance(s2, per_page)
    out.save(str(dst))


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
        import logging
        logging.disable(logging.CRITICAL)             # pdf2docx 의 쪽마다 로그 — 자식은 창도 콘솔도 없다
        from viewer._vendor.pdf2docx import Converter
        from viewer._vendor.pdf2docx.converter import ConversionCancelled

        def progress(done, total, label):
            if conn.poll(0):                           # 부모가 보낸 아무 말 = 취소
                return False
            conn.send(("progress", done, total, label))
            return True
        cv = Converter(job["src"])
        try:
            cv.convert(job["dst"], pages=job.get("pages") or None, progress=progress)
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
