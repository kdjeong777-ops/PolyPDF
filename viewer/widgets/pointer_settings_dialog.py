"""260609-5 (D Phase 2): 발표 포인터 1~3 설정 — 이름·채움색·테두리색."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QColorDialog, QGroupBox,
)


class _ColorBtn(QPushButton):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 24)
        self._color = QColor(color)
        self._apply()
        self.clicked.connect(self._pick)

    def _apply(self):
        self.setStyleSheet(
            f"background:{self._color.name()};border:1px solid #888;border-radius:4px;")

    def _pick(self):
        c = QColorDialog.getColor(self._color, self, "색 선택")
        if c.isValid():
            self._color = c
            self._apply()

    def color_name(self) -> str:
        return self._color.name()


class PointerSettingsDialog(QDialog):
    def __init__(self, pointers, parent=None):
        super().__init__(parent)
        self.setWindowTitle("발표 포인터 설정")
        self.resize(420, 280)
        self._rows = []
        v = QVBoxLayout(self)
        v.addWidget(QLabel("발표 전체화면에서 사용할 포인터(2초 무동작 시 자동 숨김):"))
        for i, pr in enumerate(pointers):
            grp = QGroupBox(f"포인터 {i + 1}")
            h = QHBoxLayout(grp)
            h.addWidget(QLabel("이름:"))
            ed = QLineEdit(pr.get("name", f"사용자 포인터 {i + 1}"))
            h.addWidget(ed, 1)
            h.addWidget(QLabel("채움:"))
            cf = _ColorBtn(pr.get("fill", "#ff3030"))
            h.addWidget(cf)
            h.addWidget(QLabel("테두리:"))
            cb = _ColorBtn(pr.get("border", "#ffffff"))
            h.addWidget(cb)
            v.addWidget(grp)
            self._rows.append((ed, cf, cb))

        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("확인"); ok.clicked.connect(self.accept)
        cancel = QPushButton("취소"); cancel.clicked.connect(self.reject)
        row.addWidget(ok); row.addWidget(cancel)
        v.addLayout(row)

    def result_pointers(self) -> list:
        out = []
        for i, (ed, cf, cb) in enumerate(self._rows):
            out.append({
                "name": ed.text().strip() or f"사용자 포인터 {i + 1}",
                "fill": cf.color_name(),
                "border": cb.color_name(),
            })
        return out
