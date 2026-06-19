"""스크린샷 PDF 저장 옵션 대화상자 (v1.6.4 C1).

저장 시마다 띄워 검색어 형광펜 / 상단 파일명 / 하단 페이지번호 표시 여부를
선택. 초기값은 prefs.pdf_save_show_* (없으면 False), 결과는 호출부가
다시 prefs 에 저장해 다음 저장의 기본값으로 기억.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QGroupBox,
    QCheckBox,
    QLabel,
    QDialogButtonBox,
)


class ScreenshotPdfDialog(QDialog):
    def __init__(self, prefs: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("스크린샷 PDF 저장 옵션")
        self.setMinimumWidth(440)
        p = dict(prefs or {})

        layout = QVBoxLayout(self)

        grp = QGroupBox("저장 옵션")
        gl = QVBoxLayout(grp)

        self.chk_query = QCheckBox("검색어 형광펜 표시 (원본을 고해상도로 재렌더 — 화질 다소 저하)")
        self.chk_query.setChecked(bool(p.get("pdf_save_show_query", False)))
        gl.addWidget(self.chk_query)

        hint = QLabel(
            "<small>해제 시 원본 PDF 페이지를 그대로 복사 — 원본 화질, 형광펜 없음.</small>"
        )
        hint.setStyleSheet("color:#666; padding-left:18px;")
        gl.addWidget(hint)

        self.chk_filename = QCheckBox("상단에 파일명 표시 (.pdf 제외)")
        self.chk_filename.setChecked(bool(p.get("pdf_save_show_filename", False)))
        gl.addWidget(self.chk_filename)

        self.chk_pageno = QCheckBox("하단에 페이지 번호 표시 (스크린샷 리스트 순번)")
        self.chk_pageno.setChecked(bool(p.get("pdf_save_show_pageno", False)))
        gl.addWidget(self.chk_pageno)

        layout.addWidget(grp)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def result_options(self) -> dict:
        return {
            "show_query": self.chk_query.isChecked(),
            "show_filename": self.chk_filename.isChecked(),
            "show_pageno": self.chk_pageno.isChecked(),
        }
