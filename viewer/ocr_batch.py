# -*- coding: utf-8 -*-
"""여러 파일 OCR 글자층 일괄 — 파일 하나의 일 (텍스트 창 SOT §5.5, 261014-16).

[OCR 다시 읽기](§3.1.2)와 [PDF 에 반영](§5.4)을 파일 하나에 잇는다. **배경 스레드에서** 부른다 — 문서·study.db 연결은
여기서 따로 연다(응답성 SOT §4 ⑤). 원본 덮어쓰기는 하지 않는다: 임시 PDF 까지만 만들고, 메인이 `_finalize_save` 로 놓는다.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from viewer.i18n import tr_noop

TEMP_PREFIX = "polypdf_ocrb_"      # temp_sweep.APP_TEMP_PREFIXES 에도 있다
OCR_DPI = 300                      # [OCR 다시 읽기] 와 같다(TextOcrPageWorker 기본)

# 건너뛴 까닭 — 화면에서 tr() 로 옮긴다(다국어 SOT §6)
SKIP_SIGNED = tr_noop("서명된 PDF — 덮어쓰면 서명이 깨집니다")
SKIP_ENCRYPTED = tr_noop("암호가 걸린 PDF")
SKIP_HAS_TEXT = tr_noop("모든 쪽에 글자층이 이미 있습니다")
SKIP_NO_TEXT = tr_noop("OCR 로 읽은 글이 없습니다")
SKIP_OPEN = tr_noop("열 수 없는 PDF")


def run_file(path, *, lang: str, drop_watermark: bool, tick, cancelled, db_path=None) -> dict:
    """파일 하나: 글자층 없는 쪽을 OCR(이미 읽은 쪽은 건너뜀) → 글자층 다시 쓰기 → 임시 PDF.

    `tick(했음, 전체, 글)` — 진행(중지면 예외를 던져도 된다). `cancelled() -> bool`.
    반환 `{"status": "ok"|"skip", "why": 까닭, "tmp": 임시 PDF, "ocr": 새로 읽은 쪽 수, "stats": 글자층 통계}`.
    중지 예외는 그대로 올린다 — 하던 파일의 임시 폴더는 지운다(읽은 쪽은 study.db 에 남는다)."""
    import fitz
    from viewer import sign_core
    from viewer import text_apply as ta
    from viewer import text_extract2 as tx
    from viewer.study import ocr as study_ocr
    from viewer.study.study_store import StudyStore, file_key_for
    from viewer.text_fix_store import store as fix_store
    path = str(path)
    res = {"status": "skip", "why": "", "tmp": "", "ocr": 0, "stats": {}}
    try:
        if sign_core.is_signed_file(path):
            res["why"] = SKIP_SIGNED
            return res
        doc = fitz.open(path)
    except Exception:
        res["why"] = SKIP_OPEN
        return res
    store = None
    tmpdir = None
    try:
        if doc.needs_pass:                       # 글자층 쓰기가 암호 문서를 열지 못한다 — 건너뛰고 알린다
            res["why"] = SKIP_ENCRYPTED
            return res
        scan = [p for p in range(doc.page_count) if not tx.has_text_layer(doc, p)]
        if not scan:
            res["why"] = SKIP_HAS_TEXT
            return res
        store = StudyStore(db_path)
        fkey = file_key_for(path)
        want = study_ocr.resolve_lang(lang or study_ocr.default_lang())
        todo = [p for p in scan if not store.is_page_done(fkey, p)]
        n = len(todo) + len(scan)                # OCR 몇 쪽 + 글자층 몇 쪽
        name = Path(path).name
        for i, pg in enumerate(todo):
            if cancelled():
                raise _Stop()
            tick(i, n, f"{name} · OCR p.{pg + 1}")
            r = study_ocr.build_page(doc, pg, lang=want, dpi=OCR_DPI, force_ocr=True,
                                     drop_watermark_bg=bool(drop_watermark))
            store.save_page(fkey, pg, r["text"], dpi=r["dpi"], engine=r["engine"], source=r["source"],
                            conf=r["conf"], words=r.get("words") or [], lang=want)   # 쪽마다 바로 — 중지해도 남는다
            res["ocr"] += 1
        doc.close()
        doc = None

        def look(p):
            try:
                return (store.get_page_words(fkey, int(p)) or [], int(store.get_page_dpi(fkey, int(p)) or 0))
            except Exception:
                return ([], 0)
        fs = fix_store()
        tmpdir = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
        out = tmpdir / Path(path).name

        def layer_tick(k, total, p):
            if p >= 0:
                tick(len(todo) + k, n, f"{name} · p.{p + 1}")
        tmp, stats = ta.build_layer_pdf(
            path, scan, rows_for=ta.layer_rows_for(path, look),
            fixes_for=lambda p, rows: fs.apply_to_rows(path, p, rows),
            items_for=lambda p: fs.get_items(path, p),
            progress=layer_tick, cancelled=cancelled, out=str(out), backup=True)
        if cancelled():
            raise _Stop()
        res["stats"] = stats
        if not tmp:
            res["why"] = SKIP_NO_TEXT
            shutil.rmtree(tmpdir, ignore_errors=True)
            return res
        res.update(status="ok", tmp=str(tmp))
        tmpdir = None                            # 메인이 원본에 놓은 뒤 지운다(`cleanup`)
        return res
    except BaseException:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    finally:
        if doc is not None:
            doc.close()
        if store is not None:
            try:
                store.close()
            except Exception:
                pass


class _Stop(Exception):
    """중지 — 부르는 쪽 진행(`progress`)이 따로 예외를 던지지 않을 때 쓴다."""


Stopped = _Stop


def cleanup(tmp) -> None:
    """원본에 놓은 뒤(또는 놓지 못했을 때) 임시 폴더를 지운다."""
    if tmp:
        shutil.rmtree(Path(tmp).parent, ignore_errors=True)
