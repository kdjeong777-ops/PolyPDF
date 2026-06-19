"""260611-57/60: 문서 암호화 설정 다이얼로그.

열기 암호(user)·권한 암호(owner)·인쇄/변경/복사 권한·암호화 수준(AES256 권장, 고급 128 폴백)을
받아 fitz.save() 인자를 산출. 이미 암호화된 문서를 다시 열면 기존 암호·수준·권한을 프리필하고,
권한이 제한된(읽기 전용 등) 문서는 그 제한을 변경하지 못하도록 잠근다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QComboBox,
    QPushButton, QGroupBox, QFormLayout,
)

import fitz


_PRINT_OPTS = [
    ("인쇄 제한(금지)", 0),
    ("인쇄 허용(저해상도)", fitz.PDF_PERM_PRINT),
    ("고해상도 인쇄 허용", fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ),
]
_CHANGE_OPTS = [
    ("변경할 수 없습니다", 0),
    ("페이지 삽입·삭제·회전", fitz.PDF_PERM_ASSEMBLE),
    ("양식 작성·서명", fitz.PDF_PERM_FORM),
    ("주석·양식·서명", fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM),
    ("모든 변경 허용", fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ASSEMBLE
     | fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM),
]


def _print_index(perm: int) -> int:
    if (perm & fitz.PDF_PERM_PRINT) and (perm & fitz.PDF_PERM_PRINT_HQ):
        return 2
    if perm & fitz.PDF_PERM_PRINT:
        return 1
    return 0


def _change_index(perm: int) -> int:
    if perm & fitz.PDF_PERM_MODIFY:
        return 4
    if (perm & fitz.PDF_PERM_ANNOTATE) and (perm & fitz.PDF_PERM_FORM):
        return 3
    if perm & fitz.PDF_PERM_FORM:
        return 2
    if perm & fitz.PDF_PERM_ASSEMBLE:
        return 1
    return 0


class EncryptDialog(QDialog):
    def __init__(self, parent=None, file_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("암호화")
        self.resize(560, 470)
        self._locked = False
        self._orig_perm = -1
        v = QVBoxLayout(self)
        v.setSpacing(6)
        if file_name:
            v.addWidget(QLabel(f"대상: {file_name}"))

        self._info = QLabel("")
        self._info.setStyleSheet("color:#d64; font-weight:bold;")
        self._info.setVisible(False)
        v.addWidget(self._info)

        # 열기 암호(user) — 260618-1: 문구 변경
        self.chk_open = QCheckBox("아래 암호를 입력하여 문서 열음")
        v.addWidget(self.chk_open)
        self.ed_open = QLineEdit(); self.ed_open.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_open.setPlaceholderText("암호를 입력")
        v.addLayout(self._pw_row(self.ed_open))

        # 권한 암호(owner) — 260618-1: 문구 변경(체크박스만; 암호칸은 권한 그룹 하단으로 이동)
        self.chk_owner = QCheckBox("문서를 설정에 따라 제한하여 이용")
        v.addWidget(self.chk_owner)
        self.ed_owner = QLineEdit(); self.ed_owner.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_owner.setPlaceholderText("비밀번호 입력(공개 비밀번호와 다름)")

        # 권한
        grp = QGroupBox(); f = QFormLayout(grp)
        self.cmb_print = QComboBox()
        for t, _ in _PRINT_OPTS:
            self.cmb_print.addItem(t)
        f.addRow("인쇄 권한:", self.cmb_print)
        self.cmb_change = QComboBox()
        for t, _ in _CHANGE_OPTS:
            self.cmb_change.addItem(t)
        f.addRow("변경 권한:", self.cmb_change)
        self.chk_copy = QCheckBox("텍스트, 이미지 및 기타 내용의 복사가 가능합니다.")
        f.addRow(self.chk_copy)
        # 260618-1: '제한 해제암호'(owner) 입력칸을 복사 체크박스 아래로 이동
        f.addRow("제한 해제암호:", self._pw_row(self.ed_owner))
        v.addWidget(grp)

        # 암호화 수준 — 256 고정, 고급에 128 폴백
        adv = QGroupBox("고급"); ar = QVBoxLayout(adv)
        ar.addWidget(QLabel("암호화 수준: 256-bit AES (권장)"))
        self.chk_compat = QCheckBox("호환 모드: 128-bit AES (Acrobat 7 등 구형 뷰어 호환)")
        ar.addWidget(self.chk_compat)
        v.addWidget(adv)

        v.addStretch(1)        # 남는 공간은 아래로 — 섹션 사이 빈틈 방지(창이 길어 보이던 문제)
        row = QHBoxLayout(); row.addStretch(1)
        self.btn_save = QPushButton("저장"); self.btn_cancel = QPushButton("취소")
        row.addWidget(self.btn_save); row.addWidget(self.btn_cancel)
        v.addLayout(row)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_cancel.clicked.connect(self.reject)

        self._owner_widgets = [self.ed_owner, self.cmb_print, self.cmb_change, self.chk_copy]
        self.chk_owner.toggled.connect(self._sync_owner)
        self.chk_open.toggled.connect(self.ed_open.setEnabled)
        self.ed_open.setEnabled(False)
        self._sync_owner(False)

    def _pw_row(self, edit: QLineEdit) -> QHBoxLayout:
        """암호 입력칸 + 문자보기(👁) 토글 버튼."""
        row = QHBoxLayout(); row.addWidget(edit, 1)
        btn = QPushButton("👁"); btn.setCheckable(True); btn.setFixedWidth(34)
        btn.setToolTip("입력한 암호 보기/숨기기")

        def _toggle(on, e=edit):
            e.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        btn.toggled.connect(_toggle)
        row.addWidget(btn)
        return row

    def _sync_owner(self, on):
        if self._locked:
            return
        for w in self._owner_widgets:
            w.setEnabled(bool(on))

    def prefill(self, open_pw: str = "", is_128: bool = False, perm: int = -1,
                locked: bool = False):
        """이미 암호화된 문서를 다시 열 때 기존 설정을 채워 넣음."""
        if open_pw:
            self.chk_open.setChecked(True); self.ed_open.setText(open_pw)
            self.ed_open.setEnabled(True)
        self.chk_compat.setChecked(bool(is_128))
        self._orig_perm = perm
        if perm is not None and perm != -1:
            self.chk_owner.setChecked(True)
            self.cmb_print.setCurrentIndex(_print_index(perm))
            self.cmb_change.setCurrentIndex(_change_index(perm))
            self.chk_copy.setChecked(bool(perm & fitz.PDF_PERM_COPY))
        if locked:
            self._lock()

    def _lock(self):
        """권한 제한(읽기 전용 등) 문서 — 제한을 변경하지 못하게 잠금."""
        self._locked = True
        self._info.setText("이 문서는 권한이 제한되어 있어 권한·암호화 수준을 변경할 수 없습니다.")
        self._info.setVisible(True)
        for w in (self.chk_owner, self.ed_owner, self.cmb_print, self.cmb_change,
                  self.chk_copy, self.chk_compat):
            w.setEnabled(False)

    def _on_save(self):
        from PyQt6.QtWidgets import QMessageBox
        if not self.chk_open.isChecked() and not self.chk_owner.isChecked():
            QMessageBox.information(self, "암호화", "열기 암호 또는 권한 암호 중 하나 이상을 설정하세요.")
            return
        if self.chk_open.isChecked() and not self.ed_open.text():
            QMessageBox.information(self, "암호화", "열기 암호를 입력하세요.")
            return
        if self.chk_owner.isChecked() and not self.ed_owner.text() and not self._locked:
            QMessageBox.information(self, "암호화", "권한 암호를 입력하세요.")
            return
        self.accept()

    def result_args(self) -> dict:
        open_pw = self.ed_open.text() if self.chk_open.isChecked() else ""
        owner_pw = self.ed_owner.text() if self.chk_owner.isChecked() else ""
        method = (fitz.PDF_ENCRYPT_AES_128 if self.chk_compat.isChecked()
                  else fitz.PDF_ENCRYPT_AES_256)
        if self._locked:
            perm = int(self._orig_perm)          # 제한 상태 유지(완화 불가)
        elif self.chk_owner.isChecked():
            perm = (fitz.PDF_PERM_ACCESSIBILITY
                    | _PRINT_OPTS[self.cmb_print.currentIndex()][1]
                    | _CHANGE_OPTS[self.cmb_change.currentIndex()][1]
                    | (fitz.PDF_PERM_COPY if self.chk_copy.isChecked() else 0))
        else:
            perm = -1
        return {
            "encryption": method,
            "owner_pw": owner_pw or open_pw,
            "user_pw": open_pw,
            "permissions": int(perm),
            "open_pw": open_pw,
        }
