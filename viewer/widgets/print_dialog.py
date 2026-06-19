"""인쇄 범위 선택 다이얼로그 (260603-3).
모드: 전체 문서 / 현재 페이지 / 페이지 범위(시작-끝) / 선택한 썸네일 페이지 / 스크린샷(선택)."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QRadioButton, QButtonGroup,
    QSpinBox, QLabel, QDialogButtonBox, QWidget, QCheckBox, QPushButton, QComboBox,
)


class PrintScopeDialog(QDialog):
    def __init__(self, page_count: int, cur_page: int,
                 n_thumb_sel: int, n_shot_sel: int, parent=None,
                 preset_api=None, sample=None):
        super().__init__(parent)
        self.setWindowTitle("인쇄")
        self.page_count = page_count
        self._preset_api = preset_api
        self._sample = sample
        # 260617-6: 인쇄 다단 기본값 — 표지·목차 체크 해제(필요 시 설정에서 켬)
        self._nup_settings = {"make_cover": False, "make_toc": False}
        self._to_pdf = False
        v = QVBoxLayout(self)
        self.grp = QButtonGroup(self)

        self.rb_all = QRadioButton(f"현재 문서 전체 ({page_count} 페이지)")
        self.rb_all.setChecked(True)
        self.rb_cur = QRadioButton(f"현재 페이지 (p.{cur_page + 1})")
        self.rb_range = QRadioButton("페이지 범위")
        self.rb_thumb = QRadioButton(f"선택한 썸네일 페이지 ({n_thumb_sel}개)")
        self.rb_thumb.setEnabled(n_thumb_sel > 0)
        self.rb_shot = QRadioButton(f"스크린샷(선택 {n_shot_sel}개, 없으면 전체)")
        for rb in (self.rb_all, self.rb_cur, self.rb_range, self.rb_thumb, self.rb_shot):
            self.grp.addButton(rb)
            v.addWidget(rb)

        # 범위 스핀
        row = QHBoxLayout()
        row.addSpacing(20)
        row.addWidget(QLabel("시작"))
        self.sp_from = QSpinBox(); self.sp_from.setRange(1, page_count); self.sp_from.setValue(1)
        row.addWidget(self.sp_from)
        row.addWidget(QLabel("끝"))
        self.sp_to = QSpinBox(); self.sp_to.setRange(1, page_count); self.sp_to.setValue(page_count)
        row.addWidget(self.sp_to)
        row.addStretch(1)
        v.addLayout(row)
        self.rb_range.toggled.connect(
            lambda on: (self.sp_from.setEnabled(on), self.sp_to.setEnabled(on)))
        self.sp_from.setEnabled(False); self.sp_to.setEnabled(False)

        # 260611-37/54: 다단 인쇄(표지만, 목차 제외) + 등록 스타일 선택
        nrow = QHBoxLayout()
        self.chk_nup = QCheckBox("다단 인쇄")
        self.chk_nup.toggled.connect(self._on_nup_toggle)
        self.cmb_preset = QComboBox(); self.cmb_preset.setMinimumWidth(150)
        self._reload_presets()
        self.cmb_preset.activated.connect(self._on_preset_pick)
        self.btn_nup = QPushButton("설정"); self.btn_nup.setEnabled(False)
        self.btn_nup.clicked.connect(self._open_nup)
        nrow.addWidget(self.chk_nup)
        nrow.addWidget(QLabel("스타일:"))
        nrow.addWidget(self.cmb_preset, 1)
        nrow.addWidget(self.btn_nup)
        v.addLayout(nrow)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("인쇄...")
        self.btn_pdf = bb.addButton("PDF로 인쇄", QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_pdf.clicked.connect(self._accept_pdf)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _reload_presets(self):
        self.cmb_preset.clear()
        self.cmb_preset.addItem("(기본 설정)", None)
        try:
            for p in ((self._preset_api or {}).get("get_presets", lambda: [])() or []):
                self.cmb_preset.addItem(p.get("name", "(이름없음)"), p)
        except Exception:
            pass
        if not self._preset_api:
            self.cmb_preset.setEnabled(False)

    def _on_preset_pick(self, *_):
        p = self.cmb_preset.currentData()
        if isinstance(p, dict):
            self._nup_settings = dict(p)
            self.chk_nup.setChecked(True)        # 스타일 선택 시 다단 인쇄 자동 켜짐

    def _accept_pdf(self, *_):
        self._to_pdf = True
        self.accept()

    def to_pdf(self) -> bool:
        return self._to_pdf

    def _on_nup_toggle(self, on):
        self.btn_nup.setEnabled(on)        # 체크 시 설정 버튼만 활성화(자동으로 창 열지 않음)

    def _open_nup(self):
        from viewer.widgets.twoup_dialog import TwoUpSettingsDialog
        dlg = TwoUpSettingsDialog(self._nup_settings, self,
                                  preset_api=self._preset_api, sample=self._sample)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._nup_settings = dlg.get_settings()
        # 260617-6: 설정 창에서 저장한 스타일을 풀다운에 즉시 반영(나갔다 들어올 필요 없이)
        cur = dlg.current_preset_name() if hasattr(dlg, "current_preset_name") else ""
        self._reload_presets()
        if cur:
            i = self.cmb_preset.findText(cur)
            if i >= 0:
                self.cmb_preset.setCurrentIndex(i)
                self.chk_nup.setChecked(True)

    def nup_enabled(self) -> bool:
        return self.chk_nup.isChecked()

    def nup_settings(self) -> dict:
        from viewer.twoup import merge_twoup_settings
        s = merge_twoup_settings(self._nup_settings)
        s["enabled"] = True
        return s                            # 표지·목차는 설정 다이얼로그 값을 따름(기본 해제)

    def result_spec(self) -> dict:
        if self.rb_all.isChecked():
            return {"mode": "all"}
        if self.rb_cur.isChecked():
            return {"mode": "current"}
        if self.rb_range.isChecked():
            a, b = self.sp_from.value() - 1, self.sp_to.value() - 1
            return {"mode": "range", "from": min(a, b), "to": max(a, b)}
        if self.rb_thumb.isChecked():
            return {"mode": "thumb"}
        return {"mode": "shot"}
