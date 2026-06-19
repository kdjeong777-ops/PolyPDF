"""캡쳐 '사용자 크기' 5개 설정 다이얼로그 (이름·가로·세로) — 260606-17."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QLineEdit, QSpinBox,
    QDialogButtonBox,
)


class CaptureSizesDialog(QDialog):
    def __init__(self, sizes: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("사용자 크기 설정")
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("캡쳐 박스의 사용자 크기 5개 (이름·가로·세로 픽셀)"))
        g = QGridLayout()
        g.addWidget(QLabel("이름"), 0, 1)
        g.addWidget(QLabel("가로(px)"), 0, 2)
        g.addWidget(QLabel("세로(px)"), 0, 3)
        self._rows = []
        for i in range(5):
            s = sizes[i] if i < len(sizes) else {}
            g.addWidget(QLabel(f"{i+1}"), i + 1, 0)
            name = QLineEdit(str(s.get("name", f"사용자{i+1}")))
            w = QSpinBox(); w.setRange(20, 10000); w.setValue(int(s.get("w", 300)))
            h = QSpinBox(); h.setRange(20, 10000); h.setValue(int(s.get("h", 200)))
            g.addWidget(name, i + 1, 1)
            g.addWidget(w, i + 1, 2)
            g.addWidget(h, i + 1, 3)
            self._rows.append((name, w, h))
        v.addLayout(g)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def result_sizes(self) -> list:
        out = []
        for i, (name, w, h) in enumerate(self._rows):
            nm = name.text().strip() or f"사용자{i+1}"
            out.append({"name": nm, "w": int(w.value()), "h": int(h.value())})
        return out
