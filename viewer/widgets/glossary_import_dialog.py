"""용어집 가져오기 한 창 — 이름·참고문헌·넣을 곳·종류·구분을 한꺼번에(단어장 SOT §11.1 '사전 파일').

261107-13(사용자 결정 '단추 하나 + 창으로 모음'): 종전에는 파일을 고른 뒤 입력 창이 다섯 번 이어 떠
중간에 되돌아갈 수 없었다. 한국 전용(다국어 SOT §7) — 화면 문구를 tr() 로 감싸지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QVBoxLayout, QLineEdit, QComboBox, QLabel, QDialogButtonBox,
)

KINDS = (("기본 사전(Base)", "base"), ("내 사전(User)", "user"))
TERMBASE = (("전문 용어집(전문용어로 분류)", True), ("일반 사전(난이도 분류 안 함)", False))
NO_CATEGORY = "(구분 없음)"


class GlossaryImportDialog(QDialog):
    def __init__(self, file_path, categories=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("용어집 가져오기")
        self.setMinimumWidth(460)
        stem = Path(file_path).stem
        v = QVBoxLayout(self)
        lbl = QLabel(f"파일: {Path(file_path).name}")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        form = QFormLayout()
        self.ed_name = QLineEdit(stem)
        self.ed_name.setToolTip("사전(출처) 표시명 — 사전 관리 목록·단어장 뜻의 출처에 보입니다")
        self.ed_ref = QLineEdit(stem)
        self.ed_ref.setPlaceholderText("참고문헌/출처 인용 (선택)")
        self.cmb_kind = QComboBox()
        for t, _k in KINDS:
            self.cmb_kind.addItem(t)
        self.cmb_tb = QComboBox()
        for t, _b in TERMBASE:
            self.cmb_tb.addItem(t)
        self.cmb_cat = QComboBox()
        self.cmb_cat.setEditable(True)
        self.cmb_cat.setToolTip("구분(분류) — 고르거나 새로 입력")
        for c in list(categories) + [NO_CATEGORY]:
            self.cmb_cat.addItem(c)
        form.addRow("이름", self.ed_name)
        form.addRow("참고문헌", self.ed_ref)
        form.addRow("넣을 곳", self.cmb_kind)
        form.addRow("종류", self.cmb_tb)
        form.addRow("구분", self.cmb_cat)
        v.addLayout(form)
        self.bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.bb.button(QDialogButtonBox.StandardButton.Ok).setText("가져오기")
        self.bb.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        v.addWidget(self.bb)
        self.ed_name.textChanged.connect(self._sync_ok)
        self._sync_ok()

    def _sync_ok(self):
        self.bb.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.ed_name.text().strip()))

    def values(self) -> dict:
        cat = self.cmb_cat.currentText().strip()
        return {"name": self.ed_name.text().strip(),
                "reference": self.ed_ref.text().strip(),
                "kind": KINDS[self.cmb_kind.currentIndex()][1],
                "kind_label": self.cmb_kind.currentText(),
                "is_termbase": TERMBASE[self.cmb_tb.currentIndex()][1],
                "category": "" if cat in ("", NO_CATEGORY) else cat}
