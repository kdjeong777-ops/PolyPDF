# -*- coding: utf-8 -*-
"""쪽 원천 — 배경 스레드에서 한 문서의 쪽 줄·표를 읽는다 (형식 변환 SOT §3, 텍스트 창 SOT §7).

쪽의 줄(글·제목/내용 스타일·자리·스캔 쪽 우리 OCR·사용자 고침)을 만드는 규칙은 **텍스트 창 SOT §3**(`text_extract2.page_lines`)이
소유한다 — 여기는 그것을 **배경 스레드에서** 부르는 자리다. PyMuPDF 문서와 sqlite 연결은 만든 스레드에서만 쓰므로
(응답성 SOT §4 ⑤) 문서·study.db 연결을 이 객체가 따로 연다. 고침은 메인이 뜬 **사본**을 받는다(`snapshot_fixes`).

텍스트 창 Word 저장(`text_word.export_docx_job`)과 형식 변환(Excel·텍스트·HWPX …)이 같은 길을 쓴다.
"""
from __future__ import annotations


class PageSource:
    """`with PageSource(경로, fixes=…, forced_pages=…) as src:` — 끝나면 문서·연결을 닫는다."""

    def __init__(self, pdf_path, *, fixes=None, forced_pages=(), tables: str = "lines"):
        self.path = str(pdf_path)
        self.fixes = fixes
        self.forced = {int(p) for p in (forced_pages or ())}
        self.tables_mode = tables
        self.doc = None
        self._st = None
        self._key = None
        self._plumb = None          # 자기 pdfplumber 문서(텍스트 창 SOT §3 규칙 6) — 처음 표를 볼 때 연다

    # ---- 열고 닫기 ------------------------------------------------------
    def __enter__(self):
        import fitz
        self.doc = fitz.open(self.path)
        if self.doc.needs_pass:
            from viewer import secure_store
            if not self.doc.authenticate(secure_store.recall_any(self.path) or ""):
                self.doc.close()
                raise PermissionError("암호를 모르는 문서입니다")
        try:
            from viewer.study.study_store import StudyStore, file_key_for
            from viewer import dbutil
            self._st = StudyStore(busy_ms=dbutil.BUSY_MS_UI)
            self._key = file_key_for(self.path)
        except Exception:
            self._st = None
        return self

    def __exit__(self, *exc):
        if self._plumb is not None:
            try:
                self._plumb.close()
            except Exception:
                pass
        if self._st is not None:
            try:
                self._st.close()
            except Exception:
                pass
        if self.doc is not None:
            self.doc.close()
        return False

    @property
    def page_count(self) -> int:
        return int(self.doc.page_count) if self.doc is not None else 0

    # ---- 텍스트 창과 같은 원천 ------------------------------------------
    def ocr_text(self, pg) -> str:
        try:
            return (self._st.get_page_text(self._key, int(pg)) or "") if self._st else ""
        except Exception:
            return ""

    def ocr_words(self, pg):
        """`(낱말상자, dpi)` — 판단은 `pick_ocr_words` 한 곳(텍스트 창 SOT §3.1)."""
        if self._st is None:
            return ([], 0)
        from viewer import text_extract2 as tx
        st, key = self._st, self._key
        return tx.pick_ocr_words(
            self.doc, int(pg),
            lambda k: (st.get_page_words(key, int(k)), int(st.get_page_dpi(key, int(k)) or 0)),
            forced=int(pg) in self.forced)

    def fix_rows(self, pg, rows):
        if self.fixes is None:
            return rows
        try:
            return self.fixes.apply_to_rows(self.path, int(pg), rows)
        except Exception:
            return rows

    def lines(self, pg, *, tables: str | None = None, join: bool = True, edges=None) -> list:
        """쪽 줄 목록(고침 반영) — 텍스트 창이 보이는 것과 같다. `join=False` 는 원본 줄(형식 변환 '모양 그대로').
        `edges` 에 list 를 주면 텍스트 창이 버리는 머리말·꼬리말 줄을 채운다(텍스트 창 SOT §3.5.2, 형식 변환 SOT §1.1)."""
        from viewer import text_extract2 as tx
        ocr = "" if tx.has_text_layer(self.doc, int(pg)) else self.ocr_text(pg)
        ws, dpi = self.ocr_words(pg)
        # 옆 쪽 OCR 낱말 — 스캔 쪽의 꼬리말 되풀이 판정(텍스트 창과 같게, 261014-15)
        peers = tx._peer_words(self.ocr_words, int(pg), self.page_count) if ws else None
        rows = tx.page_lines(self.doc, self.path, int(pg), tables=(tables or self.tables_mode),
                             ocr_text=ocr, ocr_words=ws or None, ocr_dpi=int(dpi or 0),
                             join_lines=join, ocr_peer_words=peers or None, edges_out=edges)
        return self.fix_rows(pg, rows)

    def tables(self, pg) -> list:
        """`[(영역, 행 목록)]` — index.db `page_tables` 캐시를 먼저 본다(검색 SOT). 스캔 쪽은 보통 없다."""
        from viewer import text_extract2 as tx
        if self._plumb is None:
            try:
                import pdfplumber
                pw = None
                if self.doc is not None and self.doc.needs_pass:
                    from viewer import secure_store
                    pw = secure_store.recall_any(self.path) or None
                self._plumb = pdfplumber.open(self.path, password=pw)
            except Exception:
                return []
        return tx._tables(self.path, int(pg), plumber=self._plumb)
