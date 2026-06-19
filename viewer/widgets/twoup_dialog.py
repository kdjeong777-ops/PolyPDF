# -*- coding: utf-8 -*-
"""260611-29/40: PDF 병합 'N-up 배치 설정' — 프리셋(최상단)·용지/배치·임베드 미리보기(여백/간격/크롭)."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QSpinBox, QComboBox,
    QLineEdit, QPushButton, QDialogButtonBox, QLabel, QCheckBox, QFileDialog,
    QInputDialog, QMessageBox, QScrollArea, QWidget, QFontComboBox,
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

from viewer.twoup import merge_twoup_settings, PAGE_SIZES
from viewer.widgets.merge_preview import MergePreviewWidget


class TwoUpSettingsDialog(QDialog):
    def __init__(self, settings=None, parent=None, preset_api=None, sample=None):
        super().__init__(parent)
        self.setWindowTitle("다단 생성 설정")
        self.resize(1020, 740)
        self._preset_api = preset_api or {}
        self._sample = sample
        s = merge_twoup_settings(settings)
        root = QVBoxLayout(self)

        # ── 본문: 좌=미리보기(여백/간격/크롭) | 우=용지/배치·쪽번호·표지·목차 ──
        body = QHBoxLayout()
        self.preview = MergePreviewWidget(s, sample)
        body.addWidget(self.preview, 2)

        cfg = QWidget(); cv = QVBoxLayout(cfg)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(cfg)
        scroll.setFixedWidth(400)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # ── 스타일(최상단) ──
        srow = QHBoxLayout()
        srow.addWidget(QLabel("스타일:"))
        self.cmb_preset = QComboBox()
        self._reload_presets()
        b_save = QPushButton("저장…"); b_save.clicked.connect(self._save_preset)
        b_del = QPushButton("삭제"); b_del.clicked.connect(self._delete_preset)
        if not self._preset_api:
            self.cmb_preset.setEnabled(False)
            for b in (b_save, b_del):
                b.setEnabled(False)
        self.cmb_preset.activated.connect(self._load_preset)   # 선택 즉시 적용
        srow.addWidget(self.cmb_preset, 1)
        srow.addWidget(b_save); srow.addWidget(b_del)
        cv.addLayout(srow)

        # 용지 / 배치
        grp_pg = QGroupBox("용지 / 배치")
        gf = QFormLayout(grp_pg)
        self.cmb_size = QComboBox()
        for k in PAGE_SIZES:
            self.cmb_size.addItem(k, k)
        self._set_combo(self.cmb_size, s.get("page_size", "A4"))
        gf.addRow("용지 크기:", self.cmb_size)
        self.cmb_nup = QComboBox()
        self.cmb_nup.addItem("2장 (2-up)", 2)
        self.cmb_nup.addItem("4장 (4-up, 2열×2행)", 4)   # 260617-6
        self.cmb_nup.addItem("6장 (6-up, 2열×3행)", 6)
        self.cmb_nup.addItem("8장 (8-up, 2열×4행)", 8)
        self._set_combo(self.cmb_nup, int(s.get("nup", 2)))
        gf.addRow("한 장에 배치:", self.cmb_nup)
        self.cmb_fit = QComboBox()
        self.cmb_fit.addItem("맞춤 (비율 유지·여백 생김)", "contain")
        self.cmb_fit.addItem("꽉 채움 (비율 유지·가장자리 잘림)", "cover")
        self.cmb_fit.addItem("늘이기 (비율 무시·꽉 채움)", "stretch")
        self._set_combo(self.cmb_fit, s.get("fit_mode", "contain"))
        gf.addRow("채움 방식:", self.cmb_fit)
        self.chk_center = QCheckBox("가운데 정렬"); self.chk_center.setChecked(bool(s.get("center", True)))
        gf.addRow(self.chk_center)
        self.cmb_duplex = QComboBox()
        self.cmb_duplex.addItem("단면", False); self.cmb_duplex.addItem("양면", True)
        self._set_combo(self.cmb_duplex, bool(s.get("duplex", False)))
        gf.addRow("인쇄 면:", self.cmb_duplex)
        self.sp_gutter = self._sp(s.get("gutter", 0))
        gf.addRow("제본 여백:", self.sp_gutter)
        # 260617-6: 맞쪽 인쇄 — 맨 앞에 여백 페이지 1장 추가(여백색 적용)
        self.chk_facing = QCheckBox("맞쪽 인쇄 (맨 앞 여백 페이지 1장 추가)")
        self.chk_facing.setChecked(bool(s.get("facing_first", False)))
        gf.addRow(self.chk_facing)
        self.chk_docbreak = QCheckBox("문서마다 새 페이지에서 시작")
        self.chk_docbreak.setChecked(bool(s.get("doc_break", False)))
        gf.addRow(self.chk_docbreak)
        self.chk_doc_odd = QCheckBox("새 문서는 홀수 페이지로 시작")
        self.chk_doc_odd.setChecked(bool(s.get("doc_start_odd", False)))
        gf.addRow(self.chk_doc_odd)
        self.chk_mbg = QCheckBox("여백 색 사용")
        self.chk_mbg.setChecked(bool(s.get("margin_bg_on", False)))
        self.bt_mbg = self._color_btn(s.get("margin_bg", "#ffffff"))
        gf.addRow(self.chk_mbg); gf.addRow("여백 색:", self.bt_mbg)
        cv.addWidget(grp_pg)

        # 쪽번호
        grp_f = QGroupBox("쪽번호 (출력 장 번호)")
        ff = QFormLayout(grp_f)
        self.cmb_fpos = QComboBox()
        for t, k in [("표시 안함", "none"), ("좌하단", "left"), ("중앙 하단", "center"),
                     ("우하단", "right"), ("우상단", "topright")]:   # 260617-6
            self.cmb_fpos.addItem(t, k)
        self._set_combo(self.cmb_fpos, s.get("footer_pos", "center"))
        self.sp_fsize = self._sp(s["footer_size"], 6, 48)
        ff.addRow("위치:", self.cmb_fpos); ff.addRow("글자 크기:", self.sp_fsize)
        # 글꼴 / 굵기
        self.cmb_ffont = QFontComboBox()
        if s.get("footer_font"):
            self.cmb_ffont.setCurrentFont(QFont(s.get("footer_font")))
        self.chk_fbold = QCheckBox("굵게"); self.chk_fbold.setChecked(bool(s.get("footer_bold", False)))
        ff.addRow("글꼴:", self.cmb_ffont); ff.addRow(self.chk_fbold)
        # 블록(배경)
        self.chk_fblock = QCheckBox("블록(배경) 사용")
        self.chk_fblock.setChecked(bool(s.get("footer_block", False)))
        ff.addRow(self.chk_fblock)
        self.cmb_fshape = QComboBox()
        self.cmb_fshape.addItem("직사각형", "rect")
        self.cmb_fshape.addItem("둥근 직사각형", "round")
        self._set_combo(self.cmb_fshape, s.get("footer_block_shape", "rect"))
        ff.addRow("블록 종류:", self.cmb_fshape)
        self.sp_fpad = self._sp(s.get("footer_block_pad", 10), 0, 20, suffix=" %")
        ff.addRow("블록 크기(여유):", self.sp_fpad)
        self.bt_fbcolor = self._color_btn(s.get("footer_block_color", "#ffffff"))
        ff.addRow("블록 색:", self.bt_fbcolor)
        self.sp_falpha = self._sp(s.get("footer_block_alpha", 100), 0, 100, suffix=" %")
        ff.addRow("블록 투명도:", self.sp_falpha)
        cv.addWidget(grp_f)

        # 선(테두리)
        grp_l = QGroupBox("선")
        lf = QFormLayout(grp_l)
        self.chk_bout = QCheckBox("외곽선"); self.chk_bout.setChecked(bool(s.get("border_outer", False)))
        self.chk_bh = QCheckBox("내부 가로선"); self.chk_bh.setChecked(bool(s.get("border_h", False)))
        self.chk_bv = QCheckBox("내부 세로선"); self.chk_bv.setChecked(bool(s.get("border_v", False)))
        lf.addRow(self.chk_bout); lf.addRow(self.chk_bh); lf.addRow(self.chk_bv)
        self.bt_lcolor = self._color_btn(s.get("line_color", "#888888"))
        lf.addRow("선 색:", self.bt_lcolor)
        self.sp_lwidth = self._sp(s.get("line_width", 1), 0, 12)
        lf.addRow("선 굵기:", self.sp_lwidth)
        cv.addWidget(grp_l)

        # 표지
        grp_c = QGroupBox("표지")
        cf = QFormLayout(grp_c)
        self.chk_cover = QCheckBox("표지 만들기"); self.chk_cover.setChecked(bool(s.get("make_cover", True)))
        cf.addRow(self.chk_cover)
        cov = s.get("cover", {})
        self.ed_title = QLineEdit(cov.get("title", "")); self.ed_sub = QLineEdit(cov.get("subtitle", ""))
        self.ed_comp = QLineEdit(cov.get("company", "")); self.ed_name = QLineEdit(cov.get("name", ""))
        cf.addRow("제목:", self.ed_title); cf.addRow("부제:", self.ed_sub)
        cf.addRow("회사명:", self.ed_comp); cf.addRow("성명:", self.ed_name)
        self.ed_cov_tpl = QLineEdit(s.get("cover_template", ""))
        self.ed_cov_tpl.setPlaceholderText("비우면 기본 양식")
        bc = QPushButton("양식…"); bc.clicked.connect(lambda: self._pick(self.ed_cov_tpl))
        rc = QHBoxLayout(); rc.addWidget(self.ed_cov_tpl, 1); rc.addWidget(bc)
        cf.addRow("표지 Word 양식:", self._wrap(rc))
        cv.addWidget(grp_c)

        # 목차
        grp_t = QGroupBox("목차")
        tf = QFormLayout(grp_t)
        self.chk_toc = QCheckBox("목차 만들기"); self.chk_toc.setChecked(bool(s.get("make_toc", True)))
        tf.addRow(self.chk_toc)
        self.ed_toc_tpl = QLineEdit(s.get("toc_template", ""))
        self.ed_toc_tpl.setPlaceholderText("비우면 기본 양식")
        bt = QPushButton("양식…"); bt.clicked.connect(lambda: self._pick(self.ed_toc_tpl))
        rt = QHBoxLayout(); rt.addWidget(self.ed_toc_tpl, 1); rt.addWidget(bt)
        tf.addRow("목차 Word 양식:", self._wrap(rt))
        cv.addWidget(grp_t)

        # 간지(파일별)
        grp_d = QGroupBox("간지 (파일별 구분지)")
        df = QFormLayout(grp_d)
        self.chk_div = QCheckBox("각 파일 앞에 간지 만들기 (파일명 기반)")
        self.chk_div.setChecked(bool(s.get("make_divider", False)))
        df.addRow(self.chk_div)
        self.ed_div_tpl = QLineEdit(s.get("divider_template", ""))
        self.ed_div_tpl.setPlaceholderText("비우면 기본 양식")
        bd = QPushButton("양식…"); bd.clicked.connect(lambda: self._pick(self.ed_div_tpl))
        rd = QHBoxLayout(); rd.addWidget(self.ed_div_tpl, 1); rd.addWidget(bd)
        df.addRow("간지 Word 양식:", self._wrap(rd))
        self.bt_div_bg = self._color_btn(s.get("divider_bg", "#eef2f7"))
        df.addRow("간지 배경색:", self.bt_div_bg)
        cv.addWidget(grp_d)

        # Word 양식 샘플 다운로드
        b_sample = QPushButton("표지·목차·간지 Word 양식 샘플 저장…")
        b_sample.clicked.connect(self._save_samples)
        cv.addWidget(b_sample)

        cv.addStretch(1)
        body.addWidget(scroll)
        root.addLayout(body, 1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)

        # 콤보가 가장 긴 항목 폭을 강제하지 않도록 — 라벨이 가려지는 문제 방지
        for cmb in (self.cmb_size, self.cmb_nup, self.cmb_fit, self.cmb_duplex,
                    self.cmb_fpos, self.cmb_fshape, self.cmb_ffont):
            cmb.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cmb.setMinimumContentsLength(6)

        # 용지/배치/쪽번호 변경 → 미리보기 재렌더
        for w in (self.cmb_size, self.cmb_nup, self.cmb_fit, self.cmb_duplex, self.cmb_fpos):
            w.currentIndexChanged.connect(self._sync_preview)
        self.cmb_fshape.currentIndexChanged.connect(self._sync_preview)
        for sp in (self.sp_gutter, self.sp_fsize, self.sp_lwidth,
                   self.sp_fpad, self.sp_falpha):
            sp.valueChanged.connect(self._sync_preview)
        for c in (self.chk_center, self.chk_docbreak,
                  self.chk_bout, self.chk_bh, self.chk_bv,
                  self.chk_mbg, self.chk_fblock, self.chk_fbold,
                  self.chk_cover, self.chk_toc, self.chk_div):
            c.toggled.connect(self._sync_preview)
        self.cmb_ffont.currentFontChanged.connect(self._sync_preview)
        for ed in (self.ed_title, self.ed_sub, self.ed_comp, self.ed_name):
            ed.textChanged.connect(self._sync_preview)   # 입력 즉시 미리보기 반영(디바운스)
        # '새 문서는 홀수 페이지로 시작'은 doc_break + 양면일 때만 노출
        self.chk_docbreak.toggled.connect(self._update_doc_odd)
        self.cmb_duplex.currentIndexChanged.connect(self._update_doc_odd)
        self._update_doc_odd()

    # ── 헬퍼 ──
    def _sp(self, val, lo=0, hi=300, suffix=" pt"):
        s = QSpinBox(); s.setRange(lo, hi); s.setSuffix(suffix); s.setValue(int(val)); return s

    def _color_btn(self, cur):
        from PyQt6.QtGui import QColor
        b = QPushButton(cur); b._color = cur
        b.setStyleSheet(f"background:{cur};")

        def pick():
            from PyQt6.QtWidgets import QColorDialog
            col = QColorDialog.getColor(QColor(b._color), self)
            if col.isValid():
                b._color = col.name(); b.setText(b._color)
                b.setStyleSheet(f"background:{b._color};")
                self._sync_preview()
        b.clicked.connect(pick)
        return b

    @staticmethod
    def _set_color(btn, color):
        btn._color = color; btn.setText(color); btn.setStyleSheet(f"background:{color};")

    def _wrap(self, layout):
        w = QWidget(); w.setLayout(layout); return w

    def _pick(self, edit):
        fn, _ = QFileDialog.getOpenFileName(self, "Word 양식 선택", "", "Word 문서 (*.docx)")
        if fn:
            edit.setText(fn)

    @staticmethod
    def _set_combo(cmb, data):
        for i in range(cmb.count()):
            if cmb.itemData(i) == data:
                cmb.setCurrentIndex(i); return

    def _update_doc_odd(self, *_):
        on = self.chk_docbreak.isChecked() and bool(self.cmb_duplex.currentData())
        self.chk_doc_odd.setVisible(on)

    def _save_samples(self, *_):
        from pathlib import Path as _P
        folder = QFileDialog.getExistingDirectory(self, "Word 양식 샘플을 저장할 폴더 선택")
        if not folder:
            return
        from viewer.twoup import write_sample_templates
        made = write_sample_templates(folder)
        if made:
            QMessageBox.information(self, "샘플 저장",
                                    f"{len(made)}개 양식을 저장했습니다:\n"
                                    + "\n".join(_P(m).name for m in made))
        else:
            QMessageBox.warning(self, "샘플 저장",
                                "python-docx가 설치되지 않아 샘플을 만들 수 없습니다.")

    def done(self, r):
        try:
            from viewer.twoup import clear_preview_cache
            clear_preview_cache()         # 미리보기 문서 캐시 정리(파일 핸들 해제)
        except Exception:
            pass
        super().done(r)

    def _base_settings(self) -> dict:
        return {
            "nup": self.cmb_nup.currentData(),
            "page_size": self.cmb_size.currentData(),
            "fit_mode": self.cmb_fit.currentData(),
            "center": self.chk_center.isChecked(),
            "duplex": self.cmb_duplex.currentData(),
            "gutter": self.sp_gutter.value(),
            "facing_first": self.chk_facing.isChecked(),
            "doc_break": self.chk_docbreak.isChecked(),
            "doc_start_odd": self.chk_doc_odd.isChecked(),
            "footer_pos": self.cmb_fpos.currentData(),
            "footer_size": self.sp_fsize.value(),
            "make_cover": self.chk_cover.isChecked(),
            "make_toc": self.chk_toc.isChecked(),
            "make_divider": self.chk_div.isChecked(),
            "divider_template": self.ed_div_tpl.text().strip(),
            "divider_bg": self.bt_div_bg._color,
            "border_outer": self.chk_bout.isChecked(),
            "border_h": self.chk_bh.isChecked(),
            "border_v": self.chk_bv.isChecked(),
            "line_color": self.bt_lcolor._color,
            "line_width": self.sp_lwidth.value(),
            "margin_bg_on": self.chk_mbg.isChecked(),
            "margin_bg": self.bt_mbg._color,
            "footer_font": self.cmb_ffont.currentFont().family(),
            "footer_bold": self.chk_fbold.isChecked(),
            "footer_block": self.chk_fblock.isChecked(),
            "footer_block_shape": self.cmb_fshape.currentData(),
            "footer_block_pad": self.sp_fpad.value(),
            "footer_block_color": self.bt_fbcolor._color,
            "footer_block_alpha": self.sp_falpha.value(),
            # 표지 내용(미리보기 즉시 반영용) — get_settings 가 동일 값으로 덮어씀
            "cover": {"title": self.ed_title.text(), "subtitle": self.ed_sub.text(),
                      "company": self.ed_comp.text(), "name": self.ed_name.text()},
            "cover_template": self.ed_cov_tpl.text().strip(),
            "toc_template": self.ed_toc_tpl.text().strip(),
        }

    def _sync_preview(self, *_):
        self.preview.set_base(self._base_settings())

    # ── 프리셋 ──
    def _reload_presets(self):
        self.cmb_preset.clear()
        try:
            for p in (self._preset_api.get("get_presets", lambda: [])() or []):
                self.cmb_preset.addItem(p.get("name", "(이름없음)"), p)
        except Exception:
            pass

    def _check_templates(self):
        """워드 양식 경로 중 실제로 없는 파일은 비우고, 비운 항목 라벨 목록을 반환."""
        import os
        missing = []
        for ed, label in ((self.ed_cov_tpl, "표지"), (self.ed_toc_tpl, "목차"),
                          (self.ed_div_tpl, "간지")):
            p = ed.text().strip()
            if p and not os.path.exists(p):
                ed.setText(""); missing.append(label)
        return missing

    def _warn_missing_templates(self, missing):
        if missing:
            QMessageBox.warning(
                self, "양식 파일 없음",
                "다음 Word 양식 파일을 찾을 수 없어 선택에서 제외했습니다:\n· "
                + "\n· ".join(f"{m} Word 양식" for m in missing))

    def current_preset_name(self) -> str:
        """260617-6: 마지막으로 저장/선택한 스타일 이름(인쇄창 풀다운 즉시 반영용)."""
        return getattr(self, "_cur_preset_name", "")

    def _load_preset(self, *_):
        p = self.cmb_preset.currentData()
        if isinstance(p, dict):
            self.apply_settings(p)
            self._cur_preset_name = self.cmb_preset.currentText()
            self._warn_missing_templates(self._check_templates())

    def _save_preset(self):
        cur = self.cmb_preset.currentText()
        name, ok = QInputDialog.getText(self, "스타일 저장", "스타일 이름:", text=cur)
        if not ok or not name.strip():
            return
        name = name.strip()
        existing = [p.get("name") for p in
                    (self._preset_api.get("get_presets", lambda: [])() or [])]
        if name in existing:        # 260611-41: 같은 이름이면 업데이트 확인
            if QMessageBox.question(
                self, "스타일 저장",
                f"'{name}' 스타일이 이미 있습니다. 기존 내용을 업데이트할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
                return
        # 첨부한 Word 양식 파일이 실제로 없으면 선택 해제 후 저장
        missing = self._check_templates()
        cfg = self.get_settings(); cfg["name"] = name      # _check_templates 후라 빠진 경로 반영
        try:
            self._preset_api.get("save_preset", lambda *_: None)(name, cfg)
        except Exception:
            pass
        self._reload_presets()
        i = self.cmb_preset.findText(name)
        if i >= 0:
            self.cmb_preset.setCurrentIndex(i)
        self._cur_preset_name = name        # 260617-6
        self._warn_missing_templates(missing)

    def _delete_preset(self):
        name = self.cmb_preset.currentText()
        if not name:
            return
        if QMessageBox.question(self, "스타일 삭제", f"'{name}' 스타일을 삭제할까요?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self._preset_api.get("delete_preset", lambda *_: None)(name)
        except Exception:
            pass
        self._reload_presets()

    # ── 설정 적용/수집 ──
    def apply_settings(self, p):
        s = merge_twoup_settings(p)
        self._set_combo(self.cmb_size, s.get("page_size", "A4"))
        self._set_combo(self.cmb_nup, int(s.get("nup", 2)))
        self._set_combo(self.cmb_fit, s.get("fit_mode", "contain"))
        self.chk_center.setChecked(bool(s.get("center", True)))
        self._set_combo(self.cmb_duplex, bool(s.get("duplex", False)))
        self.sp_gutter.setValue(int(s.get("gutter", 0)))
        self.chk_facing.setChecked(bool(s.get("facing_first", False)))
        self.chk_docbreak.setChecked(bool(s.get("doc_break", False)))
        self.chk_doc_odd.setChecked(bool(s.get("doc_start_odd", False)))
        self._update_doc_odd()
        self._set_combo(self.cmb_fpos, s.get("footer_pos", "center"))
        self.sp_fsize.setValue(int(s["footer_size"]))
        self.chk_cover.setChecked(bool(s.get("make_cover", True)))
        self.chk_toc.setChecked(bool(s.get("make_toc", True)))
        cov = s.get("cover", {})
        self.ed_title.setText(cov.get("title", "")); self.ed_sub.setText(cov.get("subtitle", ""))
        self.ed_comp.setText(cov.get("company", "")); self.ed_name.setText(cov.get("name", ""))
        self.ed_cov_tpl.setText(s.get("cover_template", "")); self.ed_toc_tpl.setText(s.get("toc_template", ""))
        self.chk_div.setChecked(bool(s.get("make_divider", False)))
        self.ed_div_tpl.setText(s.get("divider_template", ""))
        self._set_color(self.bt_div_bg, s.get("divider_bg", "#eef2f7"))
        self.chk_bout.setChecked(bool(s.get("border_outer", False)))
        self.chk_bh.setChecked(bool(s.get("border_h", False)))
        self.chk_bv.setChecked(bool(s.get("border_v", False)))
        self._set_color(self.bt_lcolor, s.get("line_color", "#888888"))
        self.sp_lwidth.setValue(int(s.get("line_width", 1)))
        self.chk_mbg.setChecked(bool(s.get("margin_bg_on", False)))
        self._set_color(self.bt_mbg, s.get("margin_bg", "#ffffff"))
        if s.get("footer_font"):
            self.cmb_ffont.setCurrentFont(QFont(s.get("footer_font")))
        self.chk_fbold.setChecked(bool(s.get("footer_bold", False)))
        self.chk_fblock.setChecked(bool(s.get("footer_block", False)))
        self._set_combo(self.cmb_fshape, s.get("footer_block_shape", "rect"))
        self.sp_fpad.setValue(int(s.get("footer_block_pad", 10)))
        self._set_color(self.bt_fbcolor, s.get("footer_block_color", "#ffffff"))
        self.sp_falpha.setValue(int(s.get("footer_block_alpha", 100)))
        self.preview.set_values(s)        # 여백/간격/크롭
        self._sync_preview()

    def get_settings(self) -> dict:
        c = {"enabled": True}
        c.update(self._base_settings())
        c.update(self.preview.values())   # 여백/간격/크롭
        c["cover"] = {"title": self.ed_title.text(), "subtitle": self.ed_sub.text(),
                      "company": self.ed_comp.text(), "name": self.ed_name.text()}
        c["cover_template"] = self.ed_cov_tpl.text().strip()
        c["toc_template"] = self.ed_toc_tpl.text().strip()
        return c
