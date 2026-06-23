"""파일 해시태그 편집 다이얼로그 — 현재 태그 + 기존 태그 클릭 추가.

SOT: 화면 디자인/검색창 계획서 연계(책갈피창 파일 분류). `viewer.tag_store` 사용.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QDialogButtonBox, QWidget,
)


class TagEditDialog(QDialog):
    def __init__(self, file_name: str, current_tags, existing_tags, parent=None):
        super().__init__(parent)
        self.setWindowTitle("해시태그 편집")
        self.resize(460, 300)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{file_name}</b> 의 해시태그"))
        v.addWidget(QLabel("태그를 공백/쉼표로 구분해 입력하세요(앞의 # 는 생략 가능). "
                           "파일의 <b>종류</b>를 분류하는 데 쓰세요(예: 지침, 논문, 도로, 보고서)."))

        self.ed = QLineEdit(" ".join(current_tags or []))
        self.ed.setPlaceholderText("예: 지침 도로 2024")
        v.addWidget(self.ed)

        v.addWidget(QLabel("기존 태그(클릭하면 추가):"))
        wrap = QWidget()
        self._flow = QHBoxLayout(wrap)
        self._flow.setContentsMargins(0, 0, 0, 0)
        self._flow.setSpacing(4)
        shown = [t for t in (existing_tags or [])][:40]
        for t in shown:
            b = QPushButton("#" + t)
            b.setFlat(True)
            b.setStyleSheet("QPushButton{color:#1456c4;border:1px solid #cfe0ff;"
                            "border-radius:9px;padding:1px 8px;background:#f3f8ff;}"
                            "QPushButton:hover{background:#e3efff;}")
            b.clicked.connect(lambda _=False, tag=t: self._add_tag(tag))
            self._flow.addWidget(b)
        self._flow.addStretch(1)
        v.addWidget(wrap)
        if not shown:
            v.addWidget(QLabel("(아직 등록된 태그가 없습니다 — 위에 입력해 만드세요.)"))
        v.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _add_tag(self, tag: str):
        cur = self.ed.text().split()
        if tag.lower() not in [c.lstrip("#").lower() for c in cur]:
            self.ed.setText((self.ed.text() + " " + tag).strip())

    def tags(self) -> str:
        return self.ed.text()
