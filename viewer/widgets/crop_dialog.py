"""260609-14 (D4): 발표 크롭 설정 — 전역(전체 페이지) + 현재 페이지 상/하단(%)."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QSpinBox,
    QPushButton, QLabel, QCheckBox,
)


class CropDialog(QDialog):
    def __init__(self, page_no, global_tb, page_tb, has_page, parent=None):
        """global_tb=(top%,bot%) 전역, page_tb=(top%,bot%) 현재 페이지(없으면 전역값)."""
        super().__init__(parent)
        self.setWindowTitle(f"크롭 설정 — 현재 p.{page_no}")
        self.resize(380, 300)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("페이지 상·하단을 잘라 본문을 크게 봅니다(%). "
                           "현재 페이지 값이 전역보다 우선합니다."))

        grp_g = QGroupBox("전체 페이지(전역)")
        gf = QFormLayout(grp_g)
        self.sp_gt = self._spin(global_tb[0]); self.sp_gb = self._spin(global_tb[1])
        gf.addRow("상단 크롭:", self.sp_gt)
        gf.addRow("하단 크롭:", self.sp_gb)
        v.addWidget(grp_g)

        grp_p = QGroupBox("현재 페이지(개별)")
        pf = QFormLayout(grp_p)
        self.chk_page = QCheckBox("이 페이지에만 별도 적용")
        self.chk_page.setChecked(bool(has_page))
        pf.addRow(self.chk_page)
        self.sp_pt = self._spin(page_tb[0]); self.sp_pb = self._spin(page_tb[1])
        pf.addRow("상단 크롭:", self.sp_pt)
        pf.addRow("하단 크롭:", self.sp_pb)
        v.addWidget(grp_p)

        row = QHBoxLayout()
        btn_reset = QPushButton("초기화(이 파일 전체)")
        btn_reset.clicked.connect(self._on_reset)
        row.addWidget(btn_reset)
        row.addStretch(1)
        ok = QPushButton("적용"); ok.clicked.connect(self.accept)
        cancel = QPushButton("취소"); cancel.clicked.connect(self.reject)
        row.addWidget(ok); row.addWidget(cancel)
        v.addLayout(row)
        self._reset = False

    def _spin(self, val):
        s = QSpinBox(); s.setRange(0, 45); s.setSuffix(" %")
        s.setValue(int(round(float(val))))
        return s

    def _on_reset(self):
        self._reset = True
        self.accept()

    def result(self):
        """dict: reset / global(t,b) / page_enabled / page(t,b)."""
        return {
            "reset": self._reset,
            "global": (self.sp_gt.value(), self.sp_gb.value()),
            "page_enabled": self.chk_page.isChecked(),
            "page": (self.sp_pt.value(), self.sp_pb.value()),
        }
