# -*- coding: utf-8 -*-
"""OCR 글자층 일괄 진입 (텍스트 창 SOT §5.5, 261014-16) — 책갈피창 우클릭 'OCR 글자층 넣기...' 가 `action_ocr_batch` 로.

- 읽기·쓰기: 배경 일감 하나(`_run_merge_job(counts=False)` — 진행·중지, 막대는 파일마다 1000 칸, 글은 `progress_text.step`). 파일 하나의 일은 `ocr_batch.run_file`.
- 원본 덮어쓰기: 끝난 뒤 **메인에서** 파일마다 `_finalize_save`(마스터 §4.7.5 — 저장의 단일 길). 백업은 `build_layer_pdf` 가 한 번.
방식은 §11.11 표준: 본문 그대로 옮긴 믹스인(`class MainWindow(…, OcrBatchMixin, …)`).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from viewer.i18n import tr


class OcrBatchMixin:
    def action_ocr_batch(self, files) -> bool:
        """창을 띄우고 고른 파일들에 OCR 글자층을 넣는다. 한 파일이라도 넣었으면 True."""
        from viewer import ocr_batch
        from viewer.twoup import MergeCancelled
        from viewer.widgets.ocr_batch_dialog import OcrBatchDialog
        files = [str(f) for f in (files or []) if f and str(f).lower().endswith(".pdf") and Path(f).exists()]
        if not files:
            QMessageBox.information(self, tr("OCR 글자층 넣기"), tr("넣을 PDF 가 없습니다."))
            return False
        dlg = OcrBatchDialog(self, files=files, last=getattr(self, "_ocr_opts", None))
        if dlg.exec() != dlg.DialogCode.Accepted:
            return False
        opts = dlg.values()
        self._ocr_opts = dict(getattr(self, "_ocr_opts", None) or {}, lang=opts["lang"], watermark=opts["watermark"])
        if not self._ensure_ocr_langs(opts["lang"], True):
            return False
        results = []                                     # (원본, run_file 결과 | 예외 문자열)

        from viewer.progress_text import file_head

        def _job(progress):
            stop = {"v": False}
            for i, src in enumerate(files):
                head = file_head(i, len(files), Path(src).name)   # 261026-2(디자인 SOT §2.7): 1000칸 척도는 막대에만

                def tick(done, total, label, _i=i, _head=head):
                    total = max(1, int(total))
                    try:
                        progress(_i * 1000 + int(1000 * done / total), len(files) * 1000,
                                 f"{_head}\n{label}" if label else _head)
                    except MergeCancelled:
                        stop["v"] = True
                        raise
                try:
                    results.append((src, ocr_batch.run_file(src, lang=opts["lang"], drop_watermark=opts["watermark"],
                                                            tick=tick, cancelled=lambda: stop["v"])))
                except (MergeCancelled, ocr_batch.Stopped):
                    raise MergeCancelled()
                except Exception as e:                   # noqa: BLE001 — 한 파일 실패가 일괄을 멈추지 않게
                    results.append((src, str(e)))
            progress(len(files) * 1000, len(files) * 1000, tr("원본에 넣는 중…"))
        res = self._run_merge_job(_job, tr("OCR 글자층 넣기"), counts=False)
        cancelled = bool(res.get("cancelled"))
        if not results and res.get("err") and not cancelled:
            QMessageBox.warning(self, tr("OCR 글자층 넣기"), res.get("err"))
            return False
        return self._ocr_batch_place(results, cancelled, len(files))

    def _ocr_batch_place(self, results, cancelled: bool, n_files: int) -> bool:
        """끝난 파일들을 원본에 놓고(메인, 파일마다 `_finalize_save`) 결과를 알린다."""
        from viewer import ocr_batch
        from viewer.file_overwrite import SaveCancelled
        mv = self.main_view
        cur = mv.current_file() if mv is not None else None
        try:
            cur_page = int(mv.current_page()) if cur else 0
        except Exception:
            cur_page = 0
        done, skipped, failed, pages, ocred = [], [], [], 0, 0
        for src, r in results:
            if isinstance(r, str):
                failed.append((src, r))
                continue
            ocred += int(r.get("ocr") or 0)
            if r.get("status") != "ok":
                skipped.append((src, tr(r.get("why") or "")))
                continue
            try:
                out = str(self._finalize_save(src, r["tmp"]))
                rewritten, fallback = self._mark_layer_written(src, r.get("stats") or {})
                pages += len(rewritten) + len(fallback)
                done.append((src, out))
                self.study_commit_for(src)            # 261019-1: 원본에 넣었으면(=저장) 읽은 OCR 도 확정
            except SaveCancelled as e:
                skipped.append((src, str(e)))
            except Exception as e:                       # noqa: BLE001
                failed.append((src, str(e)))
            finally:
                ocr_batch.cleanup(r.get("tmp"))
        if done and cur:
            # 덮어쓰기가 본문을 닫는다(§4.7.5) — 보던 파일·쪽으로 다시 연다
            back = next((o for s, o in done if s == cur), cur)
            try:
                self._reload_after_text_apply(back, cur_page, src=cur)
            except Exception:
                pass
        lines = [tr('글자층을 넣은 파일: {n}개 · {p}쪽 (새로 읽은 쪽 {o}쪽)').format(n=len(done), p=pages, o=ocred)]
        if cancelled:
            lines.append(tr('중지했습니다 — {k}개 파일은 손대지 않았습니다(읽은 쪽은 이 실행 동안 남아 다시 읽지 않습니다 — 남기려면 상태 표시줄 \'저장 안 한 OCR\' 에서 저장).').format(
                k=max(0, n_files - len(results))))
        if skipped:
            lines.append(tr("건너뛴 파일:") + "".join("\n· %s — %s" % (Path(s).name, w) for s, w in skipped[:10]))
        if failed:
            lines.append(tr("실패:") + "".join("\n· %s — %s" % (Path(s).name, w) for s, w in failed[:10]))
        renamed = [(s, o) for s, o in done if Path(o).name != Path(s).name]
        if renamed:
            lines.append(tr("다른 이름으로 저장된 파일:") + "".join("\n· %s" % Path(o).name for _s, o in renamed[:10]))
        QMessageBox.information(self, tr("OCR 글자층 넣기"), "\n\n".join(lines))
        self.status.showMessage(tr('OCR 글자층: {n}개 파일 · {p}쪽').format(n=len(done), p=pages), 8000)
        self._pending_refresh()
        return bool(done)
