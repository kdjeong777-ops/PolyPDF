# -*- coding: utf-8 -*-
"""가림 진입 (보안 SOT §14, 261014-22) — 책갈피창 우클릭 '가림(개인정보 지우기)...' 이 `action_redact` 로.

방식은 §11.11 표준: 본문 그대로 옮긴 믹스인. 찾기·지우기·저장은 `_run_merge_job`(배경·진행·중지), 결과는 새 파일.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from viewer.i18n import tr


class RedactMixin:
    def action_redact(self, path) -> str | None:
        """가림 창 → 새 파일 `<이름>_가림.pdf`. 만든 파일 경로(없으면 None)."""
        from viewer import redact, sign_core
        from viewer.widgets.redact_dialog import RedactDialog
        path = str(path or "")
        if not path or not path.lower().endswith(".pdf") or not Path(path).exists():
            return None
        try:
            import fitz
            d = fitz.open(path)
            locked = d.needs_pass or d.is_encrypted
            d.close()
        except Exception:
            locked = False
        if locked:
            QMessageBox.information(self, tr("가림(개인정보 지우기)"), tr(redact.REFUSE_ENCRYPTED))
            return None
        dlg = RedactDialog(self, path=path, runner=lambda job, title: self._run_merge_job(job, title))
        if dlg.exec() != dlg.DialogCode.Accepted or not dlg.marks():
            return None
        marks, scrub = dlg.marks(), dlg.scrub()
        box = {}

        def job(progress):
            def tick(i, n, label):
                if progress(i, max(1, n), label) is False:
                    from viewer.twoup import MergeCancelled
                    raise MergeCancelled()
            box["out"] = redact.apply(path, marks, scrub=scrub, tick=tick)
        res = self._run_merge_job(job, tr("가림(개인정보 지우기)"))
        if "out" not in box:
            if res.get("err"):
                QMessageBox.warning(self, tr("가림(개인정보 지우기)"), str(res.get("err")))
            return None
        out, left = box["out"]
        try:
            self.bookmark_tree.add_or_refresh_file(str(out), after=path)
        except Exception:
            pass
        lines = [tr('가린 자리 {n}곳 — 새 파일: {name}').format(n=len(marks), name=Path(out).name),
                 tr("원본은 그대로입니다.")]
        if sign_core.is_signed_file(path):
            lines.append(tr("원본은 서명된 문서입니다 — 새 파일의 서명은 효력이 없습니다."))
        if left:
            QMessageBox.warning(self, tr("가림(개인정보 지우기)"), "\n".join(lines) + "\n\n"
                                + tr("주의: 아래 자리에 글이 남았습니다 — 새 파일을 확인하세요.")
                                + "".join("\n· p.%d %s" % (p + 1, t[:40]) for p, t in left[:10]))
        else:
            QMessageBox.information(self, tr("가림(개인정보 지우기)"), "\n".join(lines))
        return str(out)
