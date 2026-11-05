# -*- coding: utf-8 -*-
"""쪽 원천 — 배경 스레드에서 한 문서의 쪽 줄·표를 읽는다 (형식 변환 SOT §3, 텍스트 창 SOT §7).

쪽의 줄(글·제목/내용 스타일·자리·스캔 쪽 우리 OCR·사용자 고침)을 만드는 규칙은 **텍스트 창 SOT §3**(`text_extract2.page_lines`)이
소유한다 — 여기는 그것을 **배경 스레드에서** 부르는 자리다. PyMuPDF 문서와 sqlite 연결은 만든 스레드에서만 쓰므로
(응답성 SOT §4 ⑤) 문서·study.db 연결을 이 객체가 따로 연다. 고침은 메인이 뜬 **사본**을 받는다(`snapshot_fixes`).

텍스트 창 Word 저장(`text_word.export_docx_job`)과 형식 변환(Excel·텍스트·HWPX …)이 같은 길을 쓴다.
"""
from __future__ import annotations

import re


_XML_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def xml_safe(text: str) -> str:
    """XML(docx·hwpx·pptx·xlsx)에 넣을 수 없는 제어 문자 → `�`(알 수 없는 글자 표시). 글꼴이 대시 등을 제어 문자로
    대응시킨 PDF 에서 Word 쓰기가 실패했다(261014-30 표본 시험 — 2단 논문의 `25\x0130 °C`). 무엇이었는지 알 수 없어 지우지 않고 표시한다."""
    return _XML_BAD.sub("\ufffd", text) if text else text


PHOTO_TMP_PREFIX = "polypdf_photosrc_"


def _sweep_photo_tmp() -> None:
    """앞 변환이 남긴 사진 임시 PDF 폴더를 지운다 — 실패한 쓰기 함수의 예외가 문서를 쥔 채로 끝나면 그때는 못 지운다(쓰는 중인 것은 안 지워진다)."""
    import glob, os, shutil, tempfile
    for d in glob.glob(os.path.join(tempfile.gettempdir(), PHOTO_TMP_PREFIX + "*")):
        shutil.rmtree(d, ignore_errors=True)


class PageSource:
    """`with PageSource(경로, fixes=…, forced_pages=…) as src:` — 끝나면 문서·연결을 닫는다."""

    def __init__(self, pdf_path, *, fixes=None, forced_pages=(), tables: str = "lines", photo_rot: int = 0, photo_crop=None):
        self.path = str(pdf_path)
        self.src_path = self.path                # 고침·OCR 의 키가 되는 원본(사진이면 사진 경로 — 사진 보기 SOT §4.35)
        self.photo_rot = int(photo_rot or 0) % 360
        self.photo_crop = photo_crop                 # 사진 보기 크롭 — 회전 0 판 쪽 비율(사진 보기 SOT §4.40)
        self._photo = None                       # 사진이면 (회전 0 판 폭, 높이) — 쓰기 함수는 임시 PDF(`self.path`)를 연다
        self._tmpdir = None
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
        from viewer.image_page import PHOTO_EXTS
        import os as _os
        if _os.path.splitext(self.path)[1].lower() in PHOTO_EXTS:
            self._open_photo()
            return self
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

    def _open_photo(self):
        """사진 한 장 → 보기 회전대로 구운 1쪽 임시 PDF(사진 보기 SOT §4.35). 쪽 크기 = 돈 판 픽셀(= pt, D14).
        OCR 낱말은 원본 사진 키의 보류 ▶ 저장본(단어학습 SOT §14.22 — 사진이 바뀌었으면 없는 것으로)."""
        import io
        import os
        import tempfile
        from pathlib import Path
        import fitz
        from PIL import Image, ImageOps
        from viewer import photo_io
        from viewer.study import ocr as _ocr
        photo_io._prep(self.path)
        with Image.open(self.path) as im:
            im = ImageOps.exif_transpose(im)
            im.load()
        w0, h0 = im.size
        if self.photo_crop:
            from viewer.photo_crop import crop_pil
            im = crop_pil(im, self.photo_crop)
        if self.photo_rot:
            im = im.rotate(-self.photo_rot, expand=True)
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=92)
        self._photo = (w0, h0)
        _sweep_photo_tmp()
        self._tmpdir = tempfile.mkdtemp(prefix=PHOTO_TMP_PREFIX)
        pdf = os.path.join(self._tmpdir, Path(self.path).stem + ".pdf")
        d = fitz.open()
        pg = d.new_page(width=float(im.width), height=float(im.height))
        pg.insert_image(pg.rect, stream=buf.getvalue())
        d.save(pdf)
        d.close()
        self.path = pdf
        self.doc = fitz.open(pdf)
        self._photo_words, self._photo_text = [], ""
        try:
            from viewer.study.study_store import StudyStore, file_key_for
            from viewer import dbutil
            self._st = StudyStore(busy_ms=dbutil.BUSY_MS_UI)
            self._key = file_key_for(self.src_path)
            row = self._st.conn.execute("SELECT engine FROM ocr_page WHERE file_key=? AND page=0", (self._key,)).fetchone()
            if row and str(row["engine"] or "").endswith(_ocr.photo_sig(self.src_path)):
                self._photo_words = _ocr.photo_words_view(self._st.get_page_words(self._key, 0), self.photo_rot, w0, h0)
                if self.photo_crop:
                    from viewer import photo_crop as _pc
                    vw, vh = (h0, w0) if self.photo_rot in (90, 270) else (w0, h0)
                    self._photo_words = _pc.words_view(self._photo_words, _pc.to_view(self.photo_crop, self.photo_rot), vw, vh)
                self._photo_text = self._st.get_page_text(self._key, 0) or ""
        except Exception:
            self._st = None

    def __exit__(self, *exc):
        if self._tmpdir:
            try:
                if self.doc is not None:
                    self.doc.close()
                    self.doc = None
            except Exception:
                pass
            import gc, os, shutil, time
            for _ in range(5):                   # 실패한 쓰기 함수가 연 문서가 아직 파일을 쥐고 있을 수 있다 — 거둔 뒤 다시
                shutil.rmtree(self._tmpdir, ignore_errors=True)
                if not os.path.exists(self._tmpdir):
                    break
                gc.collect()
                time.sleep(0.1)
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
        if self._photo is not None:
            return self._photo_text if int(pg) == 0 else ""
        try:
            return (self._st.get_page_text(self._key, int(pg)) or "") if self._st else ""
        except Exception:
            return ""

    def ocr_words(self, pg):
        """`(낱말상자, dpi)` — 판단은 `pick_ocr_words` 한 곳(텍스트 창 SOT §3.1)."""
        if self._photo is not None:                  # 사진 — 우리 OCR 낱말만(돈 판 px = pt)
            return (list(self._photo_words), 72) if int(pg) == 0 and self._photo_words else ([], 0)
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
            return self.fixes.apply_to_rows(self.src_path, int(pg), rows)
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
        for e in edges or ():
            if "text" in e:
                e["text"] = xml_safe(e["text"])
            if e.get("pieces"):
                e["pieces"] = [(a, b, xml_safe(t)) for a, b, t in e["pieces"]]
        rows = self.fix_rows(pg, rows)
        for r in rows:
            if isinstance(r.get("text"), str):
                r["text"] = xml_safe(r["text"])
        return rows

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
        return [(bb, [[xml_safe(c) if isinstance(c, str) else c for c in (row or [])] for row in rows])
                for bb, rows in tx._tables(self.path, int(pg), plumber=self._plumb)]
