# -*- coding: utf-8 -*-
"""변환 창 — 형식·범위를 고른다 (형식 변환 SOT §2·§5, 261014-11).

형식은 다 만든 것만(`convert.ready_formats`). 범위는 문서 전체 / 쪽 범위(`3-12`·`1,4,7-9`) / 고른 쪽(썸네일에서 왔을 때).
여러 파일(책갈피창 일괄)이면 범위는 문서 전체만.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton, QLineEdit,
                             QLabel, QDialogButtonBox, QButtonGroup)

from viewer.i18n import tr
from viewer import convert


class ConvertDialog(QDialog):
    def __init__(self, parent=None, *, files=(), page_count: int = 0, preset: str | None = None,
                 picked_pages=None):
        super().__init__(parent)
        self.setWindowTitle(tr("변환"))
        self.setMinimumWidth(420)
        self._n = int(page_count or 0)
        self._picked = list(picked_pages or [])
        files = list(files)
        lay = QVBoxLayout(self)
        from pathlib import Path
        who = (tr('대상: {name}').format(name=Path(files[0]).name) if len(files) == 1
               else tr('대상: {n}개 파일').format(n=len(files)))
        self.lbl_target = QLabel(who)
        self.lbl_target.setWordWrap(True)
        lay.addWidget(self.lbl_target)

        g_fmt = QGroupBox(tr("형식"))
        fl = QVBoxLayout(g_fmt)
        self.fmt_group = QButtonGroup(self)
        self._fmt_btn = {}
        for f in convert.ready_formats():
            b = QRadioButton(tr(f.label))
            b.setObjectName("fmt_" + f.key)
            self.fmt_group.addButton(b)
            fl.addWidget(b)
            self._fmt_btn[f.key] = b
        first = preset if preset in self._fmt_btn else next(iter(self._fmt_btn), None)
        if first:
            self._fmt_btn[first].setChecked(True)
        lay.addWidget(g_fmt)

        g_rng = QGroupBox(tr("범위"))
        rl = QVBoxLayout(g_rng)
        self.rb_all = QRadioButton(tr("문서 전체"))
        row = QHBoxLayout()
        self.rb_range = QRadioButton(tr("쪽 범위"))
        self.ed_range = QLineEdit()
        self.ed_range.setPlaceholderText(tr("예: 3-12 또는 1,4,7-9"))
        self.ed_range.textEdited.connect(lambda _t: self.rb_range.setChecked(True))
        row.addWidget(self.rb_range); row.addWidget(self.ed_range, 1)
        self.rb_picked = QRadioButton(tr('고른 쪽 ({n}쪽)').format(n=len(self._picked)))
        rl.addWidget(self.rb_all); rl.addLayout(row); rl.addWidget(self.rb_picked)
        self.rb_picked.setVisible(bool(self._picked))
        (self.rb_picked if self._picked else self.rb_all).setChecked(True)
        if len(files) != 1:                       # 일괄은 문서 전체만(SOT §2.2)
            self.rb_range.setEnabled(False); self.ed_range.setEnabled(False)
        lay.addWidget(g_rng)

        self.lbl_err = QLabel("")
        self.lbl_err.setStyleSheet("color:#b3261e;")
        lay.addWidget(self.lbl_err)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("변환"))
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def format_key(self) -> str | None:
        for k, b in self._fmt_btn.items():
            if b.isChecked():
                return k
        return None

    def pages(self):
        """None = 문서 전체, 그 밖에는 0부터 쪽 목록."""
        if self.rb_picked.isChecked() and self._picked:
            return list(self._picked)
        if self.rb_range.isChecked():
            return convert.parse_range(self.ed_range.text(), self._n)
        return None

    def _accept(self):
        if not self.format_key():
            self.lbl_err.setText(tr("형식을 고르세요."))
            return
        try:
            self.pages()
        except ValueError:
            self.lbl_err.setText(tr('쪽 범위는 1~{n} 안에서 3-12 처럼 적어 주세요.').format(n=self._n))
            return
        self.accept()
