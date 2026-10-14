# -*- coding: utf-8 -*-
"""PDF 압축 진입 (마스터 §4.7.19, 261014-21) — 책갈피창 우클릭 'PDF 압축...' 이 `action_compress` 로.

방식은 §11.11 표준: 본문 그대로 옮긴 믹스인(`class MainWindow(…, CompressMixin, …)`). 실행은 `_run_merge_job` 한 일감
(파일마다 1000 칸, 중지), 파일 하나는 `pdf_compress.run`(보조 프로세스).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QLabel, QMessageBox, QRadioButton,
                             QVBoxLayout)

from viewer.i18n import tr


class CompressDialog(QDialog):
    def __init__(self, parent=None, *, files=(), level="mid"):
        super().__init__(parent)
        from viewer.pdf_compress import COMPRESS_LEVELS, LEVEL_LABELS
        self.setWindowTitle(tr("PDF 압축"))
        files = list(files)
        v = QVBoxLayout(self)
        head = (tr('{name} 을(를) 압축해 새 파일로 저장합니다.').format(name=Path(files[0]).name) if len(files) == 1
                else tr('PDF {n}개를 압축해 새 파일로 저장합니다.').format(n=len(files)))
        lb = QLabel(head + "\n" + tr("그림만 줄이고 글자는 그대로입니다. 원본은 그대로 둡니다."))
        lb.setWordWrap(True)
        v.addWidget(lb)
        self._grp = QButtonGroup(self)
        self._btn = {}
        for key in COMPRESS_LEVELS:
            b = QRadioButton(tr(LEVEL_LABELS[key]))
            self._grp.addButton(b)
            self._btn[key] = b
            v.addWidget(b)
        self._btn.get(level, self._btn["mid"]).setChecked(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        for b in bb.buttons():
            b.setAutoDefault(False)                 # 디자인 §2.7 — Enter 로 닫히지 않게
            b.setDefault(False)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def level(self) -> str:
        return next((k for k, b in self._btn.items() if b.isChecked()), "mid")


def _size(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, n // 1024)} KB"


class CompressMixin:
    def action_compress(self, files) -> bool:
        from viewer import pdf_compress
        from viewer.convert import Cancelled
        from viewer.twoup import MergeCancelled
        files = [str(f) for f in (files or []) if f and str(f).lower().endswith(".pdf") and Path(f).exists()]
        if not files:
            QMessageBox.information(self, tr("PDF 압축"), tr("압축할 PDF 가 없습니다."))
            return False
        dlg = CompressDialog(self, files=files, level=getattr(self, "_compress_level", "mid"))
        if dlg.exec() != dlg.DialogCode.Accepted:
            return False
        level = self._compress_level = dlg.level()
        results = []                                      # (원본, ("ok", 결과, 전, 후) | ("skip", 까닭) | ("fail", 까닭))

        def _job(progress):
            for i, src in enumerate(files):
                def tick(done, total, label, _i=i):
                    total = max(1, int(total))
                    if progress(_i * 1000 + int(1000 * done / total), len(files) * 1000, label) is False:
                        raise Cancelled()
                try:
                    out, a, b = pdf_compress.run(src, level, tick)
                    results.append((src, ("ok", out, a, b)))
                except (Cancelled, MergeCancelled):
                    raise MergeCancelled()
                except pdf_compress.Skipped as e:
                    results.append((src, ("skip", tr(str(e)))))
                except Exception as e:                     # noqa: BLE001 — 한 파일 실패가 일괄을 멈추지 않게
                    results.append((src, ("fail", str(e))))
        res = self._run_merge_job(_job, tr("PDF 압축"))
        cancelled = bool(res.get("cancelled"))
        ok = [(s, r) for s, r in results if r[0] == "ok"]
        lines = []
        for s, r in ok[:10]:
            _k, out, a, b = r
            lines.append(tr('· {name}: {a} → {b} ({p}% 줄임)').format(name=Path(out).name, a=_size(a), b=_size(b),
                                                                      p=int(round(100 * (a - b) / max(1, a)))))
        msg = [tr('압축한 파일: {n}개').format(n=len(ok)) + ("\n" + "\n".join(lines) if lines else "")]
        skipped = [(s, r[1]) for s, r in results if r[0] == "skip"]
        failed = [(s, r[1]) for s, r in results if r[0] == "fail"]
        if skipped:
            msg.append(tr("건너뛴 파일:") + "".join("\n· %s — %s" % (Path(s).name, w) for s, w in skipped[:10]))
        if failed:
            msg.append(tr("실패:") + "".join("\n· %s — %s" % (Path(s).name, w) for s, w in failed[:10]))
        if cancelled:
            msg.append(tr("중지했습니다 — 만들던 파일은 지웠습니다."))
        for s, r in ok:                                   # 새 파일을 책갈피창에(원본 바로 아래)
            try:
                self.bookmark_tree.add_or_refresh_file(str(r[1]), after=str(s))
            except Exception:
                pass
        QMessageBox.information(self, tr("PDF 압축"), "\n\n".join(msg))
        return bool(ok)
