# -*- coding: utf-8 -*-
"""OCR 글자층 일괄 창 (텍스트 창 SOT §5.5, 261014-16) — 파일 수·언어·뒷배경 워터마크만 고른다.

언어 목록과 기억은 [OCR 다시 읽기](`OcrOptionsDialog`)와 같다(같은 `LANGS`, 같은 `_ocr_opts`).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                             QVBoxLayout)

from viewer.i18n import tr
from viewer.widgets.ocr_options_dialog import LANGS


class OcrBatchDialog(QDialog):
    def __init__(self, parent=None, *, files=(), last=None):
        super().__init__(parent)
        self.setWindowTitle(tr("OCR 글자층 넣기"))
        last = last or {}
        files = list(files)
        v = QVBoxLayout(self)
        if len(files) == 1:
            head = tr('{name} 의 글자층 없는 쪽을 OCR 로 읽어 보이지 않는 글자층을 넣습니다.').format(name=Path(files[0]).name)
        else:
            head = tr('PDF {n}개의 글자층 없는 쪽을 OCR 로 읽어 보이지 않는 글자층을 넣습니다.').format(n=len(files))
        lb = QLabel(head)
        lb.setWordWrap(True)
        v.addWidget(lb)
        note = QLabel(tr("원본 PDF 에 덮어쓰고, 처음 한 번 원본 옆에 백업(.textfix.bak.pdf)을 남깁니다. "
                         "이미 읽은 쪽은 다시 읽지 않습니다. 서명된 PDF·암호 PDF 는 건너뜁니다."))
        note.setWordWrap(True)
        v.addWidget(note)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("언어")))
        self.cmb_lang = QComboBox()
        for name, code in LANGS:
            self.cmb_lang.addItem(tr(name), code)
        i = self.cmb_lang.findData(last.get("lang", "kor+eng"))
        self.cmb_lang.setCurrentIndex(i if i >= 0 else 0)
        row.addWidget(self.cmb_lang, 1)
        v.addLayout(row)

        self.cb_wm = QCheckBox(tr("뒷배경 워터마크는 읽지 않기"))
        self.cb_wm.setChecked(bool(last.get("watermark", True)))
        v.addWidget(self.cb_wm)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        for b in bb.buttons():
            b.setAutoDefault(False)     # 디자인 §2.7 — Enter 로 닫히지 않게
            b.setDefault(False)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self) -> dict:
        return {"lang": self.cmb_lang.currentData() or "", "watermark": self.cb_wm.isChecked()}
