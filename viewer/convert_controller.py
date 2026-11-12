# -*- coding: utf-8 -*-
"""형식 변환 진입 (형식 변환 SOT §2, 261014-11) — 메뉴 넷이 모두 `action_convert` 하나로 들어온다.

- 파일·도구 탭 '변환...'(261025-5, 종전 '변환해서 내보내기') · 책갈피창 우클릭 '변환...'(하위 메뉴 없음, 여러 파일이면 일괄) · 썸네일 우클릭 '선택한 쪽 변환 ▸'.
- 실행은 `_run_merge_job`(배경 스레드 + 진행창 + 취소, 응답성 SOT §4). 문서·DB 는 그 스레드에서 `PageSource` 가 연다.

방식은 §11.11 표준: **본문 그대로 옮긴 믹스인**(`class MainWindow(ConvertMixin, ...)`).
"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtWidgets import QMenu, QMessageBox

from viewer.i18n import tr


class ConvertMixin:
    def convert_format_menu(self, parent, title: str, on_pick) -> QMenu:
        """형식 하위 메뉴 — 다 만든 형식만(SOT §1). `on_pick(형식 키)`."""
        from viewer import convert
        m = QMenu(title, parent)
        m.setToolTipsVisible(True)
        for f in convert.ready_formats():
            a = m.addAction(tr(f.label))
            if not convert.available(f.key):      # 261113-3(§5): Word 가 없으면 흐리게 + 까닭
                a.setEnabled(False)
                a.setToolTip(tr(convert.WORD_REQUIRED))
            a.triggered.connect(lambda _=False, k=f.key: on_pick(k))
        return m

    def action_convert(self, files=None, fmt: str | None = None, pages=None) -> bool:
        """변환 창을 띄우고 고른 대로 변환한다. 변환했으면 True."""
        from viewer import convert
        from viewer.widgets.convert_dialog import ConvertDialog
        mv = self.main_view
        if not files:
            cur = mv.current_file() if mv else None
            files = [cur] if cur else []
        if getattr(self, "_photo_mode", False):
            return self._photo_convert([str(f) for f in files if f], fmt)    # 사진 보기 SOT §4.35(261104-10 P4-b)
        files = [str(f) for f in files if f and str(f).lower().endswith(".pdf") and Path(f).exists()]
        if not files:
            QMessageBox.information(self, tr("변환"), tr("변환할 PDF 를 먼저 여세요."))
            return False
        self._lite_heavy_notice(tr("변환"))                 # 261021-1(응답성 SOT §4.7)
        if pages is not None:
            # 썸네일에서 — 저장 전 쪽 편집이 있으면 파일의 쪽 번호와 다르다(SOT §2.2)
            pt = self.page_thumbs
            doc = getattr(pt, "_doc", None)
            if doc is not None and str(doc.path) == files[0] and pt.is_page_dirty():
                QMessageBox.information(self, tr("변환"),
                                        tr("썸네일에서 바꾼 쪽 순서·삭제·끼운 쪽을 먼저 저장한 뒤 변환하세요."))
                return False
        n = 0
        try:
            import fitz
            from viewer import secure_store
            d = fitz.open(files[0])
            if d.needs_pass:
                d.authenticate(secure_store.recall_any(files[0]) or "")
            n = d.page_count
            d.close()
        except Exception:
            n = 0
        dlg = ConvertDialog(self, files=files, page_count=n, preset=fmt, picked_pages=pages)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return False
        key = dlg.format_key()
        sel = dlg.pages() if len(files) == 1 else None
        return self._run_convert(files, key, sel)

    def _photo_convert(self, files, fmt=None) -> bool:
        """사진 모드 '변환'(사진 보기 SOT §4.46, 261112-15 사용자 결정 '창 하나에 두 묶음') — 변환 창: 그림으로 저장(형식·바탕 지우기·
        흑백·색 바꾸기·가리기·보정) + 문서로(아래 `_photo_convert_doc`). 문서 형식이 정해져 오면 곧바로 문서로."""
        from viewer import convert
        from viewer.widgets.image_tune_dialog import ImageTuneDialog
        if fmt in convert.PHOTO_KEYS:
            return self._photo_convert_doc(files, fmt)
        files = [str(f) for f in files if f and self._is_photo_path(f) and Path(f).exists()]
        if not files:
            QMessageBox.information(self, tr("변환"), tr("변환할 사진을 먼저 여세요."))
            return False

        def saved(src, dst):
            for bt in (self.bookmark_tree, getattr(self, "bookmark_tree_right", None)):
                if bt is not None:
                    try:
                        bt.add_or_refresh_file(dst, after=src)
                    except Exception:
                        pass
        dlg = ImageTuneDialog(self, files, kind="photo",
                              rots={f: self._photo_rot_for(f) for f in files}, crops={f: self._photo_crop_for(f) for f in files},
                              on_saved=saved, doc_fn=lambda fs=list(files): self._photo_convert_doc(fs),
                              copy_fn=lambda img, png, done: self._copy_image_to_clipboard(img, done, png=png),
                              can_save=not self._photo_any_cached(files),
                              prefs=self._prefs.setdefault("image_tune", {}))
        self._image_tune_dlg = dlg
        try:
            dlg.exec()
        finally:
            self._image_tune_dlg = None
        if dlg.saved:
            self.status.showMessage(tr("새 파일 {n}장을 만들었습니다.").format(n=len(dlg.saved)), 5000)
        return bool(dlg.saved)

    def _photo_convert_doc(self, files, fmt=None) -> bool:
        """사진 → Word·HWPX·텍스트(사진 보기 SOT §4.35). 글은 사진 한 장 OCR(§4.34)의 결과 — 읽지 않은 사진은 먼저 읽으라고 알린다.
        zip·휴대 장치 사진(캐시)은 결과가 캐시에 생기므로 PC 로 복사한 뒤에."""
        from viewer import convert
        from viewer.widgets.convert_dialog import ConvertDialog
        files = [f for f in files if self._is_photo_path(f) and Path(f).exists()]
        if not files:
            QMessageBox.information(self, tr("변환"), tr("변환할 사진을 먼저 여세요."))
            return False
        if self._photo_any_cached(files):
            QMessageBox.information(self, tr("변환"), tr("zip·휴대 장치 사진은 'PC 로 복사' 한 뒤 변환하세요."))
            return False
        unread = [f for f in files if not self._photo_ocr_words(f)]
        if unread:
            QMessageBox.information(self, tr("변환"), tr("사진의 글자를 먼저 읽으세요 — 텍스트 창 [OCR 로 읽기]: {name}").format(
                name=", ".join(Path(f).name for f in unread[:3])))
            return False
        dlg = ConvertDialog(self, files=files, page_count=1, preset=fmt if fmt in convert.PHOTO_KEYS else None,
                            keys=convert.PHOTO_KEYS)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return False
        return self._run_convert(files, dlg.format_key(), None, rots={f: self._photo_rot_for(f) for f in files},
                                 crops={f: self._photo_crop_for(f) for f in files})     # 보기 크롭(사진 보기 SOT §4.40)

    def _run_convert(self, files, key, pages, rots=None, crops=None) -> bool:
        from viewer import convert
        from viewer.text_word import snapshot_fixes
        from viewer.twoup import MergeCancelled
        from viewer.progress_text import file_head
        fixes = snapshot_fixes()
        forced_all = getattr(self, "_text_force_ocr", None) or set()
        results = []                                    # (원본, 결과|None, 알림|None)

        def _job(progress):
            for i, src in enumerate(files):
                name = Path(src).name
                forced = {int(p) for (f, p) in forced_all if str(f) == str(src)}

                head = file_head(i, len(files), name)

                def prog(done, total, label, _i=i, _head=head):
                    # 여러 파일이면 파일 단위로 나눈 칸 안에서 나아간다 — 이 척도는 막대에만(형식 변환 SOT §5, 261026-2)
                    total = max(1, int(total))
                    return progress(_i * 1000 + int(1000 * done / total), len(files) * 1000,
                                    f"{_head}\n{label}" if label else _head)
                try:
                    out = convert.run(src, key, pages, fixes=fixes, forced_pages=forced, progress=prog,
                                      photo_rot=int((rots or {}).get(src, 0) or 0), photo_crop=(crops or {}).get(src))
                    results.append((src, out, None))
                except convert.Cancelled:
                    raise MergeCancelled()
                except convert.NothingToWrite:
                    results.append((src, None, tr("표가 없습니다")))
                except Exception as e:                 # noqa: BLE001 — 한 파일 실패가 일괄을 멈추지 않게
                    results.append((src, None, str(e)))
        res = self._run_merge_job(_job, tr("변환"), counts=False)
        if res.get("cancelled"):
            self.status.showMessage(tr("변환을 취소했습니다 — 만들던 파일은 지웠습니다."), 5000)
            return False
        ok = [r for r in results if r[1] is not None]
        bad = [r for r in results if r[1] is None]
        if not results and res.get("err"):
            QMessageBox.warning(self, tr("변환"), res.get("err"))
            return False
        if ok:
            self.status.showMessage(tr('변환: {path}').format(path=ok[0][1]), 8000)
        if len(files) == 1 and bad:
            QMessageBox.information(self, tr("변환"), tr('{name}: {why}').format(name=Path(bad[0][0]).name, why=bad[0][2]))
            return False
        msg = (tr('변환했습니다: {name}').format(name=Path(ok[0][1]).name) if len(files) == 1
               else tr('변환 {ok}개 · 실패 {bad}개').format(ok=len(ok), bad=len(bad))
               + ("".join("\n· %s — %s" % (Path(s).name, w) for s, _o, w in bad[:10])))
        if ok and QMessageBox.question(self, tr("변환"), msg + "\n\n" + tr("폴더를 열까요?")) == QMessageBox.StandardButton.Yes:
            self._reveal_converted(ok[0][1])
        elif not ok:
            QMessageBox.information(self, tr("변환"), msg)
        return bool(ok)

    def action_pages_to_pdf(self, path, pages) -> str | None:
        """고른 쪽(썸네일)·지금 쪽(본문)으로 새 PDF — 보이는 그대로 구워서(형식 변환 SOT §2.4, 261107-7 사용자 결정 A).

        `pages` 는 0부터 원본 쪽 번호, 받은 차례대로. 만든 파일 경로(취소·실패면 None)."""
        import os as _os
        import fitz
        from PyQt6.QtWidgets import QFileDialog
        from viewer import page_crop as _pc, page_rotate as _pr, pdf_mirror as _pm
        title = tr("PDF 저장")                       # 261111-24 — 메뉴 이름과 같게
        path = str(path or "")
        if not path.lower().endswith(".pdf") or not Path(path).exists():
            return None
        if not pages or any(isinstance(p, bool) or not isinstance(p, int) for p in pages):
            self._need_save_first()                    # 붙여넣은 쪽(저장 전)은 파일의 쪽 번호가 없다
            return None
        pages = list(dict.fromkeys(int(p) for p in pages))
        try:
            with fitz.open(path) as d:
                locked = bool(d.needs_pass or d.is_encrypted)
                n = d.page_count
        except Exception as e:                             # noqa: BLE001
            QMessageBox.warning(self, title, str(e))
            return None
        if locked:
            QMessageBox.information(self, title, tr("암호 PDF 입니다 — 새 파일이 암호 없이 저장되므로 만들지 않습니다."))
            return None
        if any(p < 0 or p >= n for p in pages):
            return None
        src = Path(path)
        lo, hi = min(pages) + 1, max(pages) + 1
        name = (tr('{stem}_{n}쪽.pdf').format(stem=src.stem, n=lo) if lo == hi
                else tr('{stem}_{a}-{b}쪽.pdf').format(stem=src.stem, a=lo, b=hi))
        out, _ = QFileDialog.getSaveFileName(self, title, str(src.with_name(name)), "PDF (*.pdf)")
        if not out:
            return None
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        if _os.path.normcase(_os.path.abspath(out)) == _os.path.normcase(_os.path.abspath(path)):
            QMessageBox.information(self, title, tr("원본과 다른 이름으로 저장하세요 — 원본은 그대로 둡니다."))
            return None
        # 굽기(Qt 그림)는 메인 — 평탄화해서 내보내기와 같은 길(마스터 §4.7.16), 고른 쪽의 꾸밈만
        try:
            doc = fitz.open(path)
            _pr.apply_pending(doc, path)
            _pc.apply_pending(doc, path)
            _pm.remove_layer(doc)                      # '저장' 사본은 지운다 — 구운 것과 두 번 보이지 않게
            _pm.remove_links(doc)
            keep = set(pages)
            norm = {p: v for p, v in (self._decorations_norm_for(path) or {}).items() if int(p) in keep}
            self._bake_decorations(doc, path, norm=norm, links=True)
        except Exception as e:                             # noqa: BLE001
            QMessageBox.warning(self, title, str(e))
            return None
        tmp = str(Path(out).with_name("~" + Path(out).stem + ".polypdf-tmp"))
        got = {}

        def _job(progress):
            from viewer.pdf_font import subset_fonts_safely
            from viewer.progress_text import step
            from viewer.twoup import MergeCancelled
            total = len(pages) + 1
            for k, p in enumerate(pages):
                if progress(k, total, step(tr("쪽 담기"), k + 1, len(pages), p + 1, n)) is False:
                    raise MergeCancelled()
                try:
                    _pc.cut_outside(doc[p])            # 크롭 바깥을 실제로 지운다(보이는 그대로)
                except Exception:
                    pass
            doc.select(pages)
            dropped = 0
            for page in doc:                           # 서명 값이 든 칸은 뺀다 — 고른 쪽만으로는 맞지 않는다
                for w in list(page.widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]) or []):
                    if w.is_signed:
                        page.delete_widget(w)
                        dropped += 1
            got["dropped"] = dropped
            if progress(len(pages), total, tr("저장 중")) is False:
                raise MergeCancelled()
            subset_fonts_safely(doc)
            doc.save(tmp, garbage=4, deflate=True)
        res = self._run_merge_job(_job, title, counts=False)
        doc.close()
        if not res.get("ok"):
            try:
                _os.remove(tmp)
            except OSError:
                pass
            if res.get("err"):
                QMessageBox.warning(self, title, res.get("err"))
            return None
        err = self._file_op_bg(lambda: _os.replace(tmp, out), tr("저장 중: {name}").format(name=Path(out).name))
        if err is not None:
            try:
                _os.remove(tmp)
            except OSError:
                pass
            QMessageBox.warning(self, title, str(err))
            return None
        try:
            self.bookmark_tree.add_or_refresh_file(str(out), after=path)
        except Exception:
            pass
        self.status.showMessage(tr('PDF 저장: {name} ({n}쪽)').format(name=Path(out).name, n=len(pages)), 6000)
        if got.get("dropped"):
            QMessageBox.information(self, title, tr("원본의 서명 {n}개는 고른 쪽만 담은 새 파일에서 맞지 않아 뺐습니다.").format(
                n=got["dropped"]))
        self._open_saved_file(str(out))                # 색인 먼저 걸고 연다(마스터 §4.7.10)
        return str(out)

    def _reveal_converted(self, path) -> None:
        """탐색기로 결과를 짚어 연다 — 책갈피창 '파일 탐색기 열기' 와 같은 함수."""
        try:
            self.bookmark_tree._reveal_in_explorer(str(path))
        except Exception:
            try:
                os.startfile(str(Path(path).parent))      # noqa: S606 — 사용자가 고른 결과 폴더
            except Exception:
                pass
