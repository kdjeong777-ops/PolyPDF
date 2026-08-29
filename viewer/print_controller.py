"""260628(감사 F-2): 인쇄·PDF 내보내기 컨트롤러 — MainWindow 에서 분리한 믹스인.

app.py 분할 2단계(§11.11). 담당: 인쇄 대화상자·범위 처리(`action_print`),
프린터 구성(`_make_printer`)·렌더(`_print_render`/`_draw_image_fit`),
다단(N-up) 구성(`_build_nup_pdf`/`_build_nup_pdf_items`)·다중 파일 합본
(`_combine_pdfs_temp`)·PDF 내보내기(`_export_*`/`_images_to_pdf`),
이미지→PDF 변환(`action_image_to_pdf`), 생성 후 처리(`_after_pdf_created`).

방식은 §11.11 표준: **본문 그대로 옮긴 믹스인**(`class MainWindow(PrintMixin, ...)`).
`self.*` 참조가 모두 그대로 동작하므로 **호출부(툴바·메뉴·썸네일 시그널)는 변경 없음**.
무거운 문서 생성은 `_run_merge_job`(스레드+취소 가능) 경유 — §11.9.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QMessageBox

__all__ = ["PrintMixin"]


class PrintMixin:
    """MainWindow 에 믹스인되는 인쇄·PDF 내보내기 메서드 모음."""

    def action_print(self):
        cur = self.main_view.current_file()
        is_pdf = bool(cur and str(cur).lower().endswith(".pdf"))
        pc = (self.main_view._doc.page_count
              if (is_pdf and self.main_view._doc is not None) else 0)
        cur_page = self.main_view.current_page()
        n_thumb = len(self.page_thumbs.list.selectedItems())
        n_shot = len(self.shot_strip.list.selectedItems())
        try:
            sel_files = self.bookmark_tree.selected_file_paths()
        except Exception:
            sel_files = []
        n_files = len(sel_files)
        if not is_pdf and self.shot_strip.list.count() == 0 and n_files == 0:
            QMessageBox.information(self, "인쇄", "인쇄할 문서가 없습니다.")
            return
        from viewer.widgets.print_dialog import PrintScopeDialog
        dlg = PrintScopeDialog(max(pc, 1), cur_page, n_thumb, n_shot, self,
                               preset_api=self._merge_preset_api(),
                               sample=(str(cur) if is_pdf else None),
                               n_files_sel=n_files)
        if not dlg.exec():
            return
        spec = dlg.result_spec()
        to_pdf = dlg.to_pdf()
        # 260827: 실제 인쇄면 다이얼로그에서 고른 프린터/색상/양면/방향자동/포함 옵션 적용
        self._print_opts = None
        if not to_pdf:
            _sm, _pct = dlg.size_mode()
            self._print_opts = {
                "printer": self._make_printer(dlg),
                "auto_orient": dlg.auto_orient(),
                "include_decorations": dlg.include_decorations(),
                "alignment": dlg.alignment(),
                "size_mode": _sm,
                "scale_pct": _pct,
            }
        if spec["mode"] == "shot":
            shots = self._shot_paths_to_print()
            if to_pdf:
                dst = self._save_pdf_dialog("스크린샷.pdf")
                if dst and self._export_images_pdf(shots, dst):
                    self.status.showMessage(f"PDF 저장: {dst}", 4000)
                    self._after_pdf_created(dst)
            else:
                self._print_images(shots)
            return
        if spec["mode"] == "files":
            if not sel_files:
                QMessageBox.information(self, "인쇄", "책갈피창에서 인쇄할 PDF 파일을 선택하세요.")
                return
            self._print_selected_files(sel_files, dlg, to_pdf)
            return
        if not is_pdf:
            QMessageBox.information(self, "인쇄", "현재 메인 문서가 PDF 가 아닙니다.")
            return
        if spec["mode"] == "all":
            pages = list(range(pc))
        elif spec["mode"] == "current":
            pages = [cur_page]
        elif spec["mode"] == "range":
            pages = list(range(spec["from"], spec["to"] + 1))
        else:  # thumb
            pages = sorted({self.page_thumbs.list.row(it)
                            for it in self.page_thumbs.list.selectedItems()})
        pages = [p for p in pages if 0 <= p < pc]
        if not pages:
            QMessageBox.information(self, "인쇄", "인쇄할 페이지가 없습니다.")
            return
        if dlg.nup_enabled():               # 260611-37/54: 다단 인쇄(표지만, 목차 제외)
            out_nup = self._build_nup_pdf(cur, pages, dlg.nup_settings())
            if not out_nup:
                return
            if to_pdf:
                dst = self._save_pdf_dialog(Path(cur).stem + "_다단.pdf")
                if dst and self._copy_pdf(out_nup, dst):
                    self.status.showMessage(f"PDF 저장: {dst}", 4000)
                    self._after_pdf_created(dst)
                return
            import fitz
            nd = fitz.open(out_nup); npages = list(range(nd.page_count)); nd.close()
            self._print_pdf_pages(out_nup, npages)
            return
        if to_pdf:
            dst = self._save_pdf_dialog(Path(cur).stem + "_인쇄.pdf")
            if dst and self._export_pages_pdf(cur, pages, dst):
                self.status.showMessage(f"PDF 저장: {dst}", 4000)
                self._after_pdf_created(dst)
            return
        self._print_pdf_pages(cur, pages)

    def _save_pdf_dialog(self, default_name):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "PDF로 저장", default_name, "PDF 파일 (*.pdf)")
        if path and not path.lower().endswith(".pdf"):
            path += ".pdf"
        return path

    def _copy_pdf(self, src, dst):
        import shutil
        try:
            shutil.copyfile(src, dst); return True
        except Exception as e:
            QMessageBox.warning(self, "PDF로 인쇄", f"저장 실패: {e}")
            return False

    def _export_pages_pdf(self, src, pages, out_path):
        import fitz
        self.status.showMessage("PDF 생성 중…")           # 260617-6
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        QApplication.processEvents()
        try:
            sd = fitz.open(src); td = fitz.open()
            for p in pages:
                td.insert_pdf(sd, from_page=p, to_page=p)
            sd.close(); td.save(out_path); td.close()
            return True
        except Exception as e:
            QMessageBox.warning(self, "PDF로 인쇄", f"저장 실패: {e}")
            return False
        finally:
            QApplication.restoreOverrideCursor()

    def _export_images_pdf(self, paths, out_path):
        import fitz
        d = fitz.open()
        for p in (paths or []):
            try:
                pix = fitz.Pixmap(p)
                pg = d.new_page(width=pix.width, height=pix.height)
                pg.insert_image(fitz.Rect(0, 0, pix.width, pix.height), filename=p)
            except Exception:
                continue
        ok = d.page_count > 0
        if ok:
            try:
                d.save(out_path)
            except Exception as e:
                ok = False; QMessageBox.warning(self, "PDF로 인쇄", f"저장 실패: {e}")
        d.close()
        if not ok:
            QMessageBox.information(self, "PDF로 인쇄", "내보낼 이미지가 없습니다.")
        return ok

    def _images_to_pdf(self, paths, out_path, progress=None, downscale=False,
                       max_px=2600) -> bool:
        """이미지들을 PDF 로 저장(각 1페이지).

        downscale=True: QImage 로 재인코딩·축소(150dpi 페이지) — 다단 배치·저장 속도/
        안정성↑, 이형(CMYK 등)·손상 포맷 정규화. False: 원본 그대로 삽입(무손실).
        progress(done,total,label)->bool: False 면 MergeCancelled 로 취소.
        """
        import fitz
        from viewer.twoup import MergeCancelled
        d = fitz.open()
        total = max(1, len(paths))
        for i, p in enumerate(paths):
            placed = False
            if downscale:
                try:
                    from PyQt6.QtGui import QImage
                    from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
                    img = QImage(str(p))
                    if not img.isNull():
                        if max(img.width(), img.height()) > max_px:
                            img = img.scaled(
                                max_px, max_px,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
                        ba = QByteArray(); buf = QBuffer(ba)
                        buf.open(QIODevice.OpenModeFlag.WriteOnly)
                        img.save(buf, "PNG" if img.hasAlphaChannel() else "JPEG", 88)
                        buf.close()
                        w_pt = img.width() / 150.0 * 72.0
                        h_pt = img.height() / 150.0 * 72.0
                        pg = d.new_page(width=w_pt, height=h_pt)
                        pg.insert_image(fitz.Rect(0, 0, w_pt, h_pt), stream=bytes(ba))
                        placed = True
                except Exception:
                    placed = False
            if not placed:
                try:
                    pix = fitz.Pixmap(str(p))
                    pg = d.new_page(width=pix.width, height=pix.height)
                    pg.insert_image(fitz.Rect(0, 0, pix.width, pix.height),
                                    filename=str(p))
                except Exception:
                    pass
            if progress is not None and progress(i + 1, total, "이미지 변환 중") is False:
                d.close()
                raise MergeCancelled()
        ok = d.page_count > 0
        if ok:
            d.save(out_path)
        d.close()
        return ok

    def action_image_to_pdf(self, initial_paths=None):
        """260825-13: 이미지 파일 → PDF 변환(목록·미리보기·순서변경·다단).

        260825-14: 무거운 작업(이미지 변환·다단 배치)을 백그라운드 스레드로 실행
        (`_run_merge_job`) → 대량/대형 이미지에서도 '응답 없음' 없이 진행·취소.
        """
        from viewer.widgets.image_to_pdf_dialog import ImageToPdfDialog
        dlg = ImageToPdfDialog(self, initial_paths=initial_paths,
                               preset_api=self._merge_preset_api())
        if not dlg.exec():
            return
        paths = dlg.result_paths()
        if not paths:
            QMessageBox.information(self, "이미지 → PDF", "변환할 이미지를 추가하세요.")
            return
        default_name = Path(paths[0]).stem + "_이미지.pdf"
        tmp = self._mk_print_tmpdir("polypdf_img2pdf_")
        base = str(tmp / "images.pdf")
        nup = dlg.nup_enabled()
        settings = dlg.nup_settings() if nup else None
        out_final = str(tmp / "nup.pdf") if nup else base
        name = Path(paths[0]).stem
        gen = self._gen_source_bookmarks

        def _job(progress, _paths=paths, _base=base, _out=out_final,
                 _nup=nup, _s=settings, _name=name, _gen=gen):
            # 다단은 QImage 로 정규화·축소(이형/손상 포맷·초대용량으로 build_twoup 가
            # 멈추던 문제 방지). 1단은 원본 그대로 삽입(무손실).
            if not self._images_to_pdf(_paths, _base, progress, downscale=_nup):
                return
            if _nup:
                from viewer.twoup import build_twoup
                build_twoup([{"type": "pdf", "path": _base, "name": _name}], _s, _out,
                            gen_bookmarks_fn=_gen, progress=progress)

        res = self._run_merge_job(_job, "이미지 → PDF" + (" (다단)" if nup else ""))
        if res.get("cancelled"):
            self.status.showMessage("취소했습니다.", 4000)
            return
        if res.get("err"):
            QMessageBox.warning(self, "이미지 → PDF", res["err"])
            return
        import fitz as _f
        try:
            nd = _f.open(out_final); npg = nd.page_count; nd.close()
        except Exception:
            npg = 0
        if not npg:
            QMessageBox.information(self, "이미지 → PDF", "생성된 페이지가 없습니다.")
            return
        dst = self._save_pdf_dialog(default_name)
        if dst and self._copy_pdf(out_final, dst):
            self.status.showMessage(f"PDF 저장: {dst}", 4000)
            self._after_pdf_created(dst)

    def _build_nup_pdf(self, cur, pages, settings):
        """260611-37/54: 선택 페이지를 다단(N-up)으로 구성(목차 제외). 출력 PDF 경로 반환(실패 None)."""
        import fitz
        from viewer.twoup import build_twoup
        tmpdir = self._mk_print_tmpdir("polypdf_nupprint_")
        src_sub = str(tmpdir / "sub.pdf"); out_nup = str(tmpdir / "nup.pdf")

        # 260628: BusyCursor + processEvents() 동기 루프 → **_run_merge_job(스레드+취소 가능
        #   진행창)** 으로 전환(마스터 SOT §11.9). 대용량 다중 파일 인쇄에서 '응답 없음'·취소
        #   불가하던 문제 해소. build_twoup 의 progress(done,total,label)->bool 시그니처가
        #   _MergeThread._progress 와 동일해 그대로 전달한다.
        def job(progress):
            progress(0, 1, "페이지 추출 중…")
            sd = fitz.open(cur); td = fitz.open()
            try:
                for p in pages:
                    td.insert_pdf(sd, from_page=p, to_page=p)
                td.save(src_sub)
            finally:
                sd.close(); td.close()
            build_twoup([{"type": "pdf", "path": src_sub, "name": Path(cur).stem}],
                        settings, out_nup,
                        log=lambda *a, **k: True, progress=progress)

        res = self._run_merge_job(job, "다단 PDF 생성")
        if res.get("cancelled"):
            return None
        if res.get("err"):
            QMessageBox.warning(self, "인쇄", f"다단 구성 실패: {res['err']}")
            return None
        nd = fitz.open(out_nup); n = nd.page_count; nd.close()
        if not n:
            QMessageBox.information(self, "인쇄", "구성된 페이지가 없습니다.")
            return None
        return out_nup

    def _mk_print_tmpdir(self, prefix):
        """260825-6: 인쇄용 임시 폴더 생성 + 앱 종료 시 자동 정리(atexit) 등록."""
        import tempfile, atexit, shutil
        d = tempfile.mkdtemp(prefix=prefix)
        atexit.register(shutil.rmtree, d, ignore_errors=True)
        # 260628-15: 앱은 종료 시 `os._exit` 로 끝내므로(§14.x 종료 크래시 회피) atexit 가
        #   돌지 않는다. 목록을 들고 있다가 closeEvent 에서 **직접** 지운다.
        try:
            self._print_tmpdirs.append(d)
        except AttributeError:
            self._print_tmpdirs = [d]
        return Path(d)

    def cleanup_print_tmpdirs(self):
        """260628-15: 인쇄용 임시폴더 정리(종료 시 closeEvent 에서 호출)."""
        import shutil
        for d in list(getattr(self, "_print_tmpdirs", [])):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
        self._print_tmpdirs = []

    def _build_nup_pdf_items(self, items, settings):
        """260825: 여러 항목(파일)을 다단(N-up)으로 구성. 출력 PDF 경로 반환(실패 None)."""
        import fitz
        from viewer.twoup import build_twoup
        tmpdir = self._mk_print_tmpdir("polypdf_nupfiles_")
        out_nup = str(tmpdir / "nup.pdf")

        # 260628: 동기 processEvents 루프 → _run_merge_job(스레드+취소 가능). SOT §11.9.
        def job(progress):
            build_twoup(items, settings, out_nup,
                        gen_bookmarks_fn=self._gen_source_bookmarks,
                        log=lambda *a, **k: True, progress=progress)

        res = self._run_merge_job(job, "다단 PDF 생성")
        if res.get("cancelled"):
            return None
        if res.get("err"):
            QMessageBox.warning(self, "인쇄", f"다단 구성 실패: {res['err']}")
            return None
        nd = fitz.open(out_nup); n = nd.page_count; nd.close()
        if not n:
            QMessageBox.information(self, "인쇄", "구성된 페이지가 없습니다.")
            return None
        return out_nup

    def _combine_pdfs_temp(self, files) -> str | None:
        """260825: 여러 PDF 의 전체 페이지를 하나의 임시 PDF 로 이어붙임. 경로 반환(실패 None)."""
        import fitz
        from viewer.twoup import MergeCancelled
        out = str(self._mk_print_tmpdir("polypdf_multi_") / "combined.pdf")
        flist = list(files or [])
        state = {"pages": 0}

        # 260628: 동기 processEvents → _run_merge_job(스레드+취소 가능). SOT §11.9.
        #   파일별로 progress 를 보고하므로 여러 파일 인쇄 준비 중에도 취소할 수 있다.
        def job(progress):
            td = fitz.open()
            try:
                total = max(1, len(flist))
                for i, f in enumerate(flist):
                    if progress(i, total, f"파일 읽는 중… {Path(f).name}") is False:
                        raise MergeCancelled()
                    try:
                        sd = fitz.open(f); td.insert_pdf(sd); sd.close()
                    except Exception:
                        continue
                state["pages"] = td.page_count
                if not td.page_count:
                    return
                progress(total, total, "저장 중…")
                td.save(out)
            finally:
                td.close()

        res = self._run_merge_job(job, "여러 파일 인쇄 준비")
        if res.get("cancelled"):
            return None
        if res.get("err"):
            QMessageBox.warning(self, "인쇄", f"여러 파일 준비 실패: {res['err']}")
            return None
        if not state["pages"]:
            return None
        return out

    def _print_selected_files(self, files, dlg, to_pdf):
        """260825-1: 책갈피창에서 선택한 여러 PDF 파일 전체를 하나로 이어 인쇄/PDF."""
        files = [f for f in (files or []) if f and str(f).lower().endswith(".pdf")]
        if not files:
            QMessageBox.information(self, "인쇄", "선택한 PDF 파일이 없습니다.")
            return
        default_stem = (Path(files[0]).stem + f"_외{len(files) - 1}건"
                        if len(files) > 1 else Path(files[0]).stem)
        if dlg.nup_enabled():
            items = [{"type": "pdf", "path": f, "name": Path(f).stem} for f in files]
            out_nup = self._build_nup_pdf_items(items, dlg.nup_settings())
            if not out_nup:
                return
            if to_pdf:
                dst = self._save_pdf_dialog(default_stem + "_다단.pdf")
                if dst and self._copy_pdf(out_nup, dst):
                    self.status.showMessage(f"PDF 저장: {dst}", 4000)
                    self._after_pdf_created(dst)
                return
            import fitz
            nd = fitz.open(out_nup); npages = list(range(nd.page_count)); nd.close()
            self._print_pdf_pages(out_nup, npages)
            return
        combined = self._combine_pdfs_temp(files)
        if not combined:
            QMessageBox.information(self, "인쇄", "인쇄할 페이지가 없습니다.")
            return
        if to_pdf:
            dst = self._save_pdf_dialog(default_stem + "_인쇄.pdf")
            if dst and self._copy_pdf(combined, dst):
                self.status.showMessage(f"PDF 저장: {dst}", 4000)
                self._after_pdf_created(dst)
            return
        import fitz
        nd = fitz.open(combined); npages = list(range(nd.page_count)); nd.close()
        self._print_pdf_pages(combined, npages)

    def _after_pdf_created(self, path):
        """260825-5: PDF 생성 종료 후 '파일 열기(기본)/폴더 열기/닫기' 선택."""
        try:
            path = str(path)
            box = QMessageBox(self)
            box.setWindowTitle("PDF 생성 완료")
            box.setText(f"PDF를 생성했습니다:\n{Path(path).name}\n\n어떻게 열까요?")
            b_file = box.addButton("파일 열기", QMessageBox.ButtonRole.AcceptRole)
            b_dir = box.addButton("폴더 열기", QMessageBox.ButtonRole.ActionRole)
            box.addButton("닫기", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_file)
            box.exec()
            clicked = box.clickedButton()
            if clicked is b_file:
                self._open_pdf_new_window(path)
            elif clicked is b_dir:
                self._open_containing_folder(path)
        except Exception:
            pass

    def _open_pdf_new_window(self, path):
        """260825-5: 생성된 PDF 를 별도 새 창(파일 모드)으로 띄운다."""
        import os, sys
        from PyQt6.QtCore import QProcess
        try:
            if getattr(sys, "frozen", False):
                ok = QProcess.startDetached(sys.executable, [str(path)])
            else:
                ok = QProcess.startDetached(
                    sys.executable, [os.path.abspath(sys.argv[0]), str(path)])
            if ok:
                return
        except Exception:
            pass
        # 폴백: 현재 창에서 파일 모드로 열기
        try:
            self.open_pdf(Path(path))
        except Exception:
            pass

    def _open_containing_folder(self, path):
        """260825-5: 생성된 PDF 가 있는 폴더를 열고(가능하면 해당 파일 선택)."""
        import os
        try:
            if os.name == "nt":
                import subprocess
                subprocess.Popen(["explorer", "/select,", os.path.normpath(str(path))])
                return
        except Exception:
            pass
        try:
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
        except Exception:
            pass

    def _shot_paths_to_print(self) -> list:
        metas = self.shot_strip.all_meta()
        sel = [self.shot_strip.list.row(it)
               for it in self.shot_strip.list.selectedItems()]
        rows = sel if sel else list(range(len(metas)))
        return [metas[r].get("path") for r in rows
                if 0 <= r < len(metas) and metas[r].get("path")]

    def _make_printer(self, dlg):
        """260827: 인쇄 다이얼로그에서 고른 프린터·색상·단면/양면으로 QPrinter 구성."""
        from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo
        printer = None
        try:
            name = dlg.printer_name()
            if name:
                info = QPrinterInfo.printerInfo(name)
                if not info.isNull():
                    printer = QPrinter(info, QPrinter.PrinterMode.HighResolution)
        except Exception:
            printer = None
        if printer is None:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        try:
            from PyQt6.QtPrintSupport import QPrinter, QPrinterInfo
            cm = dlg.color_mode()
            if cm is None:
                # 260827: '프린터 기본' → 프린터가 컬러 지원하면 컬러, 아니면 흑백
                try:
                    info = QPrinterInfo.printerInfo(dlg.printer_name())
                    supports_color = ((not info.isNull())
                                      and QPrinter.ColorMode.Color in info.supportedColorModes())
                    cm = (QPrinter.ColorMode.Color if supports_color
                          else QPrinter.ColorMode.GrayScale)
                except Exception:
                    cm = None
            if cm is not None:
                printer.setColorMode(cm)
            dm = dlg.duplex_mode()
            if dm is not None:
                printer.setDuplex(dm)
            sz = dlg.page_size()               # 260827: 용지 크기(프린터 지원 목록)
            if sz is not None:
                printer.setPageSize(sz)
            printer.setCopyCount(int(dlg.copies()))
        except Exception:
            pass
        return printer

    def _print_render(self, count: int, draw_fn, orient_fn=None) -> None:
        """QPrinter 설정 + 페이지별 draw_fn(painter, target_rect, index) 호출.

        260827: `_print_opts`(프린터/방향자동) 를 사용해 QPrintDialog 없이 인쇄하고,
        방향 자동 시 orient_fn(i)->QPageLayout.Orientation 으로 페이지별 용지 방향을 맞춤.
        """
        from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
        from PyQt6.QtGui import QPainter
        if count <= 0:
            return
        opts = getattr(self, "_print_opts", None) or {}
        printer = opts.get("printer")
        auto = bool(opts.get("auto_orient")) and orient_fn is not None
        if printer is None:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted:
                return
        if auto:
            try:
                printer.setPageOrientation(orient_fn(0))   # 첫 페이지 방향(균일 문서 커버)
            except Exception:
                pass
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "인쇄", "프린터를 열 수 없습니다.")
            return
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        try:
            for i in range(count):
                if i > 0:
                    if auto:
                        try:
                            printer.setPageOrientation(orient_fn(i))
                        except Exception:
                            pass
                    printer.newPage()
                draw_fn(painter, painter.viewport(), i)
                if i % 3 == 0:
                    self.status.showMessage(f"인쇄 중 {i+1}/{count}")
                    QApplication.processEvents()
            painter.end()
            self.status.showMessage(f"인쇄 완료: {count} 페이지", 4000)
        finally:
            QApplication.restoreOverrideCursor()

    def _draw_image_fit(self, painter, target, img, natural_dpi=None) -> None:
        """260827: 크기 모드(맞춤/실제/배율)+정렬(가운데/좌상)로 페이지 이미지를 인쇄면에 그린다.
        natural_dpi 는 img 가 렌더된 dpi(실제크기·배율 계산용, PDF=200). None 이면 항상 '맞춤'."""
        from PyQt6.QtCore import QRect
        if img.isNull():
            return
        opts = getattr(self, "_print_opts", None) or {}
        mode = opts.get("size_mode", "fit")
        pct = opts.get("scale_pct", 100)
        if mode in ("actual", "scale") and natural_dpi:
            try:
                dpi = float(painter.device().logicalDpiX()) or float(natural_dpi)
            except Exception:
                dpi = float(natural_dpi)
            f = dpi / float(natural_dpi)
            if mode == "scale":
                f *= max(1, int(pct)) / 100.0
            dw = max(1, int(img.width() * f)); dh = max(1, int(img.height() * f))
            scaled = img.scaled(dw, dh, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        else:
            scaled = img.scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        if opts.get("alignment", "center") == "topleft":
            x, y = target.x(), target.y()
        else:
            x = target.x() + (target.width() - scaled.width()) // 2
            y = target.y() + (target.height() - scaled.height()) // 2
        painter.drawImage(QRect(x, y, scaled.width(), scaled.height()), scaled)

    def _thumb_doc_path(self):
        """260616-21: 썸네일이 표시 중인 PDF 경로(없으면 활성 뷰 파일)."""
        p = getattr(self.page_thumbs, "_doc_path", None)
        if not p:
            cur = self.main_view.current_file() if self.main_view else None
            p = cur if (cur and str(cur).lower().endswith(".pdf")) else None
        return p

    def _on_thumb_print_pages(self, pages):
        """260616-21: 썸네일 다중선택 → 선택 페이지 인쇄."""
        cur = self._thumb_doc_path()
        pages = sorted({int(p) for p in (pages or []) if p is not None})
        if not cur or not pages:
            return
        self._print_opts = None      # 260827: 썸네일 직접 인쇄는 시스템 인쇄창(QPrintDialog) 사용
        self._print_pdf_pages(cur, pages)

    def _print_pdf_pages(self, pdf_path, pages: list) -> None:
        # 260618-1: 현재 문서 인쇄 권한 없으면 차단
        if not getattr(self, "_perm_can_print", True):
            self.status.showMessage("이 문서는 인쇄 권한이 없습니다.", 3000)
            return
        import fitz
        from PyQt6.QtGui import QImage
        from PyQt6.QtGui import QPageLayout
        doc = fitz.open(pdf_path)
        # 260615-3/260827: 인쇄에 꾸밈(선·도형·글)+하이퍼링크 포함 — '문서만' 이면 생략
        opts = getattr(self, "_print_opts", None) or {}
        if opts.get("include_decorations", True):
            try:
                self._bake_drawings_into_doc(doc, self._decorations_norm_for(pdf_path))
                self._bake_hyperlinks_into_doc(doc, pdf_path)
            except Exception:
                pass

        def draw(painter, target, i):
            page = doc.load_page(pages[i])
            zoom = 200 / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.width * 3,
                         QImage.Format.Format_RGB888).copy()
            self._draw_image_fit(painter, target, img, natural_dpi=200)

        def orient_fn(i):
            r = doc.load_page(pages[i]).rect
            return (QPageLayout.Orientation.Landscape if r.width >= r.height
                    else QPageLayout.Orientation.Portrait)
        try:
            self._print_render(len(pages), draw, orient_fn=orient_fn)
        finally:
            doc.close()

    def _print_images(self, paths: list) -> None:
        from PyQt6.QtGui import QImage, QPageLayout
        paths = [p for p in paths if p and Path(p).exists()]
        if not paths:
            QMessageBox.information(self, "인쇄", "인쇄할 스크린샷이 없습니다.")
            return
        imgs = [QImage(str(p)) for p in paths]

        def draw(painter, target, i):
            self._draw_image_fit(painter, target, imgs[i])

        def orient_fn(i):
            im = imgs[i]
            return (QPageLayout.Orientation.Landscape if im.width() >= im.height()
                    else QPageLayout.Orientation.Portrait)
        self._print_render(len(paths), draw, orient_fn=orient_fn)
