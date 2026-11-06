# -*- coding: utf-8 -*-
"""사진 크롭 창 (사진 보기 SOT §4.40, 261105-4·261106-3) — PDF 크롭 창과 같은 미리보기 화면(`CropCanvas`).

사진 한 장을 보이는 방향(보기 회전 뒤) 그대로 그리고 잘릴 곳을 어둡게 — 네 변을 끌거나 위·아래·왼쪽·오른쪽 % 칸으로.
한계는 PDF 크롭과 같다(`page_crop.clamp_margins`). [크롭 해제] 는 자른 모양을 푼다. 원본 사진은 건드리지 않는다.

261106-3(사용자 지시 '이전·이후 추가, 넘어가면 임시 저장, 확인 시 전체 적용'): 넘길 사진이 둘 이상이면 미리보기 아래 가운데에
공통 `PageNav`(`❮ n / 전체 ❯`, 디자인 SOT §2.20). 창은 사진을 스스로 읽지 않는다 — `photoRequested(번호)` 를 내면 쓰는 쪽이
배경에서 그림을 풀어 `show_photo` 로 넣는다(그 사이 넘김은 꺼진다). 사진마다 고친 여백은 `pending()` 에 남고, [확인] 때
쓰는 쪽이 한꺼번에 적용한다. [취소] 면 아무것도 남지 않는다.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                             QVBoxLayout)

from viewer import page_crop as pc
from viewer.i18n import tr
from viewer.widgets.crop_dialog import CropCanvas
from viewer.widgets.page_nav import PageNav, centered_row


class PhotoCropDialog(QDialog):
    photoRequested = pyqtSignal(int)          # 넘길 사진 번호(0부터) — 쓰는 쪽이 그림을 풀어 show_photo

    def __init__(self, img, margins, has_crop: bool = False, title: str = "", parent=None,
                 count: int = 1, index: int = 0):
        super().__init__(parent)
        self.resize(820, 700)
        self._reset = False
        self._count, self._index = max(1, int(count)), int(index)
        self._pending = {}                     # 번호 → [위, 아래, 왼, 오른] % (넘길 때 기억한 것)
        self._loading = False
        root = QVBoxLayout(self)
        self.canvas = CropCanvas(self)
        root.addWidget(self.canvas, 1)
        self.nav = PageNav(self)
        self.nav.stepRequested.connect(lambda d: self._go(self._index + d))
        self.nav.pageRequested.connect(lambda n: self._go(n - 1))
        self.nav.setVisible(self._count > 1)
        root.addLayout(centered_row(self.nav))
        row = QHBoxLayout()
        grid = QGridLayout()
        self.spins = []
        for i, name in enumerate((tr("위"), tr("아래"), tr("왼쪽"), tr("오른쪽"))):
            sp = QDoubleSpinBox(self)
            sp.setRange(0.0, pc.CROP_MAX)
            sp.setDecimals(1)
            sp.setSingleStep(0.5)
            sp.setSuffix(" %")
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
        self.note_many = QLabel(tr("❮ ❯ 로 넘기면 고친 크롭을 기억해 두었다가 [확인] 때 한꺼번에 적용합니다 — 크롭이 없는 사진은 최근에 정한 크롭을 미리 겁니다."), self)
        self.note_many.setWordWrap(True)
        self.note_many.setVisible(self._count > 1)
        root.addWidget(self.note_many)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.btn_reset = bb.addButton(tr("크롭 해제"), QDialogButtonBox.ButtonRole.ResetRole)
        self.btn_reset.clicked.connect(self._on_reset)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self.canvas.marginsDragged.connect(self._dragged)
        self.show_photo(self._index, img, margins, has_crop, title)

    # ── 사진 하나 보이기 ──────────────────────────────
    def show_photo(self, index: int, img, margins, has_crop: bool = False, title: str = "") -> None:
        """`index` 사진을 보인다 — 그 사진에 이 창에서 고친 여백이 있으면 그것, 없으면 `margins`."""
        self._index = int(index)
        self._loading = False
        self.setWindowTitle(tr("사진 크롭") + (" — " + title if title else ""))
        self.canvas.set_image(img)
        m = self._pending.get(self._index, margins)
        m = [round(v, 1) for v in pc.clamp_margins(list(m or [0.0, 0.0, 0.0, 0.0]))]
        self._dragged(m)
        self.canvas.set_margins(m)
        self.btn_reset.setEnabled(bool(has_crop) or any(v > 0 for v in m))
        self.nav.set_state(self._index + 1, self._count)

    def _go(self, index: int) -> None:
        if self._loading or not (0 <= index < self._count) or index == self._index:
            return
        self._pending[self._index] = self.current_margins()     # 지금 사진 것을 임시로 기억(261106-3)
        self._loading = True
        self.nav.btn_prev.setEnabled(False)
        self.nav.btn_next.setEnabled(False)
        self.photoRequested.emit(index)

    def loading_failed(self) -> None:
        """쓰는 쪽이 그림을 풀지 못했다 — 지금 사진에 그대로."""
        self._loading = False
        self.nav.set_state(self._index + 1, self._count)

    # ── 여백 ──────────────────────────────────────────
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
        """[크롭 해제] — 사진 한 장이면 풀고 닫는다. 여럿이면 지금 사진만 풀고(0 %) 창은 그대로 — [확인] 때 함께."""
        if self._count > 1:
            self._dragged([0.0, 0.0, 0.0, 0.0])
            self.canvas.set_margins([0.0, 0.0, 0.0, 0.0])
            return
        self._reset = True
        self.accept()

    def current_margins(self) -> list:
        return [sp.value() for sp in self.spins]

    def index(self) -> int:
        return self._index

    def margins(self):
        """지금 사진의 [위, 아래, 왼, 오른] % — [크롭 해제] 를 눌렀거나 모두 0 이면 None(자르지 않음)."""
        if self._reset:
            return None
        m = self.current_margins()
        return None if not any(v > 0 for v in m) else m

    def pending(self) -> dict:
        """[확인] 때 적용할 것 — {번호: 여백 % 또는 None(자르지 않음)}: 넘기며 기억한 사진들 + 지금 사진."""
        out = {i: (m if any(v > 0 for v in m) else None) for i, m in self._pending.items()}
        out[self._index] = self.margins()
        return out
