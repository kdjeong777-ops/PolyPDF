# -*- coding: utf-8 -*-
"""사진 크롭 창 (사진 보기 SOT §4.40, 261105-4) — PDF 크롭 창과 같은 미리보기 화면(`CropCanvas`).

사진 한 장을 보이는 방향(보기 회전 뒤) 그대로 그리고 잘릴 곳을 어둡게 — 네 변을 끌거나 위·아래·왼쪽·오른쪽 % 칸으로.
한계는 PDF 크롭과 같다(`page_crop.clamp_margins`). [크롭 해제] 는 자른 모양을 푼다. 원본 사진은 건드리지 않는다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                             QVBoxLayout)

from viewer import page_crop as pc
from viewer.i18n import tr
from viewer.widgets.crop_dialog import CropCanvas


class PhotoCropDialog(QDialog):
    def __init__(self, img, margins, has_crop: bool = False, title: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("사진 크롭") + (" — " + title if title else ""))
        self.resize(820, 680)
        self._reset = False
        root = QVBoxLayout(self)
        self.canvas = CropCanvas(self)
        self.canvas.set_image(img)
        m = [round(v, 1) for v in pc.clamp_margins(list(margins or [0.0, 0.0, 0.0, 0.0]))]
        self.canvas.set_margins(m)
        root.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        grid = QGridLayout()
        self.spins = []
        for i, name in enumerate((tr("위"), tr("아래"), tr("왼쪽"), tr("오른쪽"))):
            sp = QDoubleSpinBox(self)
            sp.setRange(0.0, pc.CROP_MAX)
            sp.setDecimals(1)
            sp.setSingleStep(0.5)
            sp.setSuffix(" %")
            sp.setValue(m[i])
            sp.valueChanged.connect(lambda _v, k=i: self._spin_changed(k))
            grid.addWidget(QLabel(name, self), 0, i * 2)
            grid.addWidget(sp, 0, i * 2 + 1)
            self.spins.append(sp)
        row.addLayout(grid)
        row.addStretch(1)
        root.addLayout(row)
        note = QLabel(tr("원본 사진은 그대로 두고 자른 모양만 기억합니다 — 사진 → PDF·인쇄·평탄화·공유용 사본·사진 복사도 자른 모양으로 나옵니다."), self)
        note.setWordWrap(True)
        root.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.btn_reset = bb.addButton(tr("크롭 해제"), QDialogButtonBox.ButtonRole.ResetRole)
        self.btn_reset.setEnabled(bool(has_crop))
        self.btn_reset.clicked.connect(self._on_reset)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self.canvas.marginsDragged.connect(self._dragged)

    def _dragged(self, m):
        for sp, v in zip(self.spins, m):
            sp.blockSignals(True)
            sp.setValue(float(v))
            sp.blockSignals(False)

    def _spin_changed(self, k: int):
        m = [round(v, 1) for v in pc.clamp_margins([sp.value() for sp in self.spins], keep=k)]
        self._dragged(m)
        self.canvas.set_margins(m)

    def _on_reset(self):
        self._reset = True
        self.accept()

    def margins(self):
        """[위, 아래, 왼, 오른] % — [크롭 해제] 를 눌렀거나 모두 0 이면 None(자르지 않음)."""
        if self._reset:
            return None
        m = [sp.value() for sp in self.spins]
        return None if not any(v > 0 for v in m) else m
