"""인쇄 다이얼로그 (260603-3 / 260827 개편).

좌: 인쇄 범위 + 다단 + 프린터/옵션(용지·색상·양면·정렬·부수·방향/포함),
우: 실제 용지 비율 미리보기(페이지 탐색 ◀▶).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QRadioButton, QButtonGroup,
    QSpinBox, QLabel, QDialogButtonBox, QCheckBox, QPushButton, QComboBox,
    QWidget, QGroupBox, QFormLayout,
)

from viewer.widgets.nup_preset import NupPresetMixin   # 260628: 다단 프리셋 공통(SOT §11.10)


class PrintScopeDialog(NupPresetMixin, QDialog):
    def __init__(self, page_count: int, cur_page: int,
                 n_thumb_sel: int, n_shot_sel: int, parent=None,
                 preset_api=None, sample=None, n_files_sel: int = 0):
        super().__init__(parent)
        self.setWindowTitle("인쇄")
        self.resize(800, 600)
        self.page_count = max(1, page_count)
        self._cur_page = cur_page
        self._preset_api = preset_api
        self._sample = sample
        self._nup_settings = {"make_cover": False, "make_toc": False}
        self._to_pdf = False
        self._preview_page = cur_page          # 미리보기 현재 페이지

        root = QVBoxLayout(self)
        body = QHBoxLayout()
        root.addLayout(body, 1)

        # ── 좌 ──
        left = QVBoxLayout()
        self.grp = QButtonGroup(self)
        self.rb_all = QRadioButton(f"현재 문서 전체 ({page_count} 페이지)")
        self.rb_all.setChecked(True)
        self.rb_cur = QRadioButton(f"현재 페이지 (p.{cur_page + 1})")
        self.rb_thumb = QRadioButton(f"선택한 썸네일 페이지 ({n_thumb_sel}개)")
        self.rb_thumb.setEnabled(n_thumb_sel > 0)
        self.rb_files = QRadioButton(f"선택한 책갈피 파일 인쇄 ({n_files_sel}개)")
        self.rb_files.setEnabled(n_files_sel > 0)
        self.rb_range = QRadioButton("페이지 범위")
        self.rb_shot = QRadioButton(f"스크린샷(선택 {n_shot_sel}개, 없으면 전체)")
        for rb in self.grp_order():
            self.grp.addButton(rb)

        rrow = QHBoxLayout()
        rrow.addSpacing(20)
        rrow.addWidget(QLabel("시작"))
        self.sp_from = QSpinBox(); self.sp_from.setRange(1, page_count); self.sp_from.setValue(1)
        rrow.addWidget(self.sp_from)
        rrow.addWidget(QLabel("끝"))
        self.sp_to = QSpinBox(); self.sp_to.setRange(1, page_count); self.sp_to.setValue(page_count)
        rrow.addWidget(self.sp_to)
        rrow.addStretch(1)

        left.addWidget(QLabel("<b>인쇄 범위</b>"))
        for rb in (self.rb_all, self.rb_cur, self.rb_thumb, self.rb_files, self.rb_range):
            left.addWidget(rb)
        left.addLayout(rrow)
        left.addWidget(self.rb_shot)
        self.rb_range.toggled.connect(
            lambda on: (self.sp_from.setEnabled(on), self.sp_to.setEnabled(on)))
        self.sp_from.setEnabled(False); self.sp_to.setEnabled(False)
        if n_files_sel >= 2:
            self.rb_files.setChecked(True)
        elif n_thumb_sel >= 2:
            self.rb_thumb.setChecked(True)

        nrow = QHBoxLayout()
        self.chk_nup = QCheckBox("다단 인쇄")
        self.chk_nup.toggled.connect(self._on_nup_toggle)
        self.cmb_preset = QComboBox(); self.cmb_preset.setMinimumWidth(120)
        self._reload_presets()
        self.cmb_preset.activated.connect(self._on_preset_pick)
        self.btn_nup = QPushButton("설정"); self.btn_nup.setEnabled(False)
        self.btn_nup.clicked.connect(self._open_nup)
        nrow.addWidget(self.chk_nup)
        nrow.addWidget(QLabel("스타일:"))
        nrow.addWidget(self.cmb_preset, 1)
        nrow.addWidget(self.btn_nup)
        left.addLayout(nrow)
        left.addWidget(self._build_printer_group())
        left.addStretch(1)
        lw = QWidget(); lw.setLayout(left); body.addWidget(lw, 3)

        # ── 우: 미리보기 ──
        right = QVBoxLayout()
        prow = QHBoxLayout()
        prow.addWidget(QLabel("<b>미리보기</b>"))
        prow.addStretch(1)
        self.btn_prev = QPushButton("◀"); self.btn_prev.setFixedWidth(32)
        self.btn_next = QPushButton("▶"); self.btn_next.setFixedWidth(32)
        self.lbl_pageno = QLabel("")
        self.btn_prev.clicked.connect(lambda: self._step_preview(-1))
        self.btn_next.clicked.connect(lambda: self._step_preview(1))
        prow.addWidget(self.btn_prev); prow.addWidget(self.lbl_pageno); prow.addWidget(self.btn_next)
        right.addLayout(prow)
        self.preview = QLabel("미리보기")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumWidth(320)
        self.preview.setStyleSheet("background:#e9e9e9;border:1px solid #cccccc;")
        right.addWidget(self.preview, 1)
        self.preview_cap = QLabel("")
        self.preview_cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_cap.setStyleSheet("color:#555555;")
        right.addWidget(self.preview_cap)
        rw = QWidget(); rw.setLayout(right); body.addWidget(rw, 2)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("인쇄")
        self.btn_pdf = bb.addButton("PDF로 인쇄", QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_pdf.clicked.connect(self._accept_pdf)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        # 미리보기 갱신 트리거
        for rb in self.grp_order():
            rb.toggled.connect(self._sync_preview_to_scope)
        self.sp_from.valueChanged.connect(self._sync_preview_to_scope)
        self.chk_auto_orient.toggled.connect(self._update_preview)
        self.cmb_paper.currentIndexChanged.connect(self._update_preview)
        self.chk_center.toggled.connect(self._update_preview)
        self.cmb_size.currentIndexChanged.connect(self._update_preview)
        self.sp_scale.valueChanged.connect(self._update_preview)
        self.cmb_color.currentIndexChanged.connect(self._update_preview)
        self._sync_preview_to_scope()        # 260827: 미리보기를 '인쇄되는 첫 페이지'로

    # ----- 프린터/옵션 -----
    def _build_printer_group(self) -> QGroupBox:
        gb = QGroupBox("프린터 · 옵션")
        form = QFormLayout(gb)
        self.cmb_printer = QComboBox()
        try:
            from PyQt6.QtPrintSupport import QPrinterInfo
            for nm in QPrinterInfo.availablePrinterNames():
                self.cmb_printer.addItem(nm)
            dft = QPrinterInfo.defaultPrinterName()
            if dft:
                i = self.cmb_printer.findText(dft)
                if i >= 0:
                    self.cmb_printer.setCurrentIndex(i)
        except Exception:
            pass
        self.cmb_printer.currentIndexChanged.connect(self._reload_paper_sizes)
        form.addRow("프린터", self.cmb_printer)

        self.cmb_paper = QComboBox()
        self._reload_paper_sizes()
        form.addRow("용지 크기", self.cmb_paper)

        # 크기 모드: 맞춤 / 실제 크기 / 사용자 지정 배율(%)
        srow = QHBoxLayout()
        self.cmb_size = QComboBox()
        self.cmb_size.addItems(["맞춤(용지에 맞게)", "실제 크기", "사용자 지정 배율"])
        srow.setContentsMargins(0, 0, 0, 0)
        srow.addWidget(self.cmb_size, 1)
        self.sp_scale = QSpinBox(); self.sp_scale.setRange(10, 400)
        self.sp_scale.setValue(100); self.sp_scale.setSuffix("%")
        self.sp_scale.setFixedWidth(76); self.sp_scale.setEnabled(False)
        srow.addWidget(self.sp_scale)
        self.cmb_size.currentIndexChanged.connect(
            lambda i: self.sp_scale.setEnabled(i == 2))
        sw = QWidget(); sw.setLayout(srow)
        form.addRow("인쇄 크기", sw)

        self.cmb_color = QComboBox()
        self.cmb_color.addItems(["프린터 기본", "컬러", "흑백"])
        form.addRow("색상", self.cmb_color)

        self.cmb_duplex = QComboBox()
        self.cmb_duplex.addItems(["단면", "양면(긴 쪽)", "양면(짧은 쪽)"])
        self.cmb_duplex.setCurrentIndex(0)      # 기본 단면
        form.addRow("단면/양면", self.cmb_duplex)

        self.cmb_include = QComboBox()
        self.cmb_include.addItems(["문서 + 주석·꾸미기", "문서만"])
        form.addRow("포함", self.cmb_include)

        self.sp_copies = QSpinBox(); self.sp_copies.setRange(1, 99); self.sp_copies.setValue(1)
        self.sp_copies.setFixedWidth(70)
        form.addRow("부수", self.sp_copies)

        self.chk_center = QCheckBox("자동 가운데 정렬(작을 때) — 해제 시 좌상 맞춤")
        self.chk_center.setChecked(True)
        form.addRow("", self.chk_center)
        self.chk_auto_orient = QCheckBox("페이지 방향 자동(가로/세로)")
        self.chk_auto_orient.setChecked(True)
        form.addRow("", self.chk_auto_orient)
        return gb

    def _reload_paper_sizes(self, *_):
        cur = self.cmb_paper.currentData() if hasattr(self, "cmb_paper") else None
        self.cmb_paper.blockSignals(True)
        self.cmb_paper.clear()
        self.cmb_paper.addItem("자동(페이지 크기)", None)
        try:
            from PyQt6.QtPrintSupport import QPrinterInfo
            info = QPrinterInfo.printerInfo(self.cmb_printer.currentText())
            if not info.isNull():
                for sz in info.supportedPageSizes():
                    self.cmb_paper.addItem(sz.name(), sz)
        except Exception:
            pass
        # 이전 선택 유지, 없으면 기본 A4
        if cur is not None:
            i = self.cmb_paper.findText(cur.name())
            self.cmb_paper.setCurrentIndex(i if i >= 0 else 0)
        else:
            i = self.cmb_paper.findText("A4")
            self.cmb_paper.setCurrentIndex(i if i >= 0 else 0)
        self.cmb_paper.blockSignals(False)
        if hasattr(self, "preview"):
            self._update_preview()

    # ----- 미리보기 -----
    def _scope_first_page(self) -> int:
        if self.rb_cur.isChecked():
            return self._cur_page
        if self.rb_range.isChecked():
            return max(0, self.sp_from.value() - 1)
        return 0

    def _sync_preview_to_scope(self, *_):
        self._preview_page = self._scope_first_page()
        self._update_preview()

    def _step_preview(self, d: int):
        self._preview_page = max(0, min(self.page_count - 1, self._preview_page + d))
        self._update_preview()

    def _sheet_dims(self, page_landscape: bool):
        """선택 용지의 (w,h) — 방향 반영. '자동(페이지)'이면 None."""
        sz = self.cmb_paper.currentData()
        if sz is None:
            return None
        s = sz.sizePoints()
        w, h = float(s.width()), float(s.height())
        land = page_landscape if self.chk_auto_orient.isChecked() else False
        if land and w < h:
            w, h = h, w
        if (not land) and w > h:
            w, h = h, w
        return (w, h)

    def _align_pos(self, cw, ch, iw, ih):
        if self.chk_center.isChecked():
            return (cw - iw) // 2, (ch - ih) // 2
        return 0, 0                              # 좌상 맞춤

    def _update_preview(self, *_):
        self.btn_prev.setEnabled(self._preview_page > 0)
        self.btn_next.setEnabled(self._preview_page < self.page_count - 1)
        self.lbl_pageno.setText(f"{self._preview_page + 1} / {self.page_count}")
        if not self._sample or not str(self._sample).lower().endswith(".pdf"):
            self.preview.setText("미리보기 없음"); self.preview_cap.setText("")
            return
        ppix = self._render_preview_pixmap(self._preview_page)
        if ppix is None or ppix.isNull():
            self.preview.setText("미리보기를 만들 수 없습니다."); self.preview_cap.setText("")
            return
        from PyQt6.QtGui import QPixmap, QPainter, QColor, QImage
        PREVIEW_DPI = 110.0
        page_pt_w = ppix.width() * 72.0 / PREVIEW_DPI
        page_pt_h = ppix.height() * 72.0 / PREVIEW_DPI
        page_land = ppix.width() >= ppix.height()
        dims = self._sheet_dims(page_land)            # 용지(포인트) 또는 None(자동=페이지)
        sw, sh = dims if dims else (page_pt_w, page_pt_h)
        area = self.preview.size()
        maxw = max(200, area.width() - 12); maxh = max(200, area.height() - 12)
        scale = min(maxw / sw, maxh / sh)             # px per point
        cw, ch = max(1, int(sw * scale)), max(1, int(sh * scale))
        # 크기 모드로 콘텐츠 크기 결정
        mode, pct = self.size_mode()
        if mode == "fit":
            cont = ppix.scaled(cw, ch, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        else:
            f = 1.0 if mode == "actual" else pct / 100.0
            dw = max(1, int(page_pt_w * scale * f)); dh = max(1, int(page_pt_h * scale * f))
            cont = ppix.scaled(dw, dh, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        # 흑백 미리보기
        if self.cmb_color.currentText() == "흑백":
            cont = QPixmap.fromImage(
                cont.toImage().convertToFormat(QImage.Format.Format_Grayscale8))
        canvas = QPixmap(cw, ch); canvas.fill(QColor("#ffffff"))
        pnt = QPainter(canvas)
        pnt.drawPixmap(*self._align_pos(cw, ch, cont.width(), cont.height()), cont)
        pnt.setPen(QColor("#b0b0b0")); pnt.drawRect(0, 0, cw - 1, ch - 1)
        pnt.end()
        self.preview.setPixmap(canvas)
        orient = "가로" if (page_land if self.chk_auto_orient.isChecked() else False) else "세로"
        self.preview_cap.setText(
            f"용지: {self.cmb_paper.currentText()} · {orient} · {self.cmb_size.currentText()}"
            + (f" · {'흑백' if self.cmb_color.currentText()=='흑백' else '컬러'}"))

    def _render_preview_pixmap(self, page_index: int):
        try:
            import fitz
            from PyQt6.QtGui import QImage, QPixmap
            doc = fitz.open(self._sample)
            try:
                if page_index >= doc.page_count:
                    page_index = 0
                page = doc.load_page(page_index)
                zoom = 110 / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.width * 3,
                             QImage.Format.Format_RGB888).copy()
                return QPixmap.fromImage(img)
            finally:
                doc.close()
        except Exception:
            return None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_preview()

    def showEvent(self, e):
        super().showEvent(e)
        self._update_preview()               # 레이아웃 완료 후 정확한 크기로 렌더

    # ----- 접근자 -----
    def printer_name(self) -> str:
        return self.cmb_printer.currentText() if self.cmb_printer.count() else ""

    def page_size(self):
        return self.cmb_paper.currentData()      # QPageSize 또는 None(자동)

    def alignment(self) -> str:
        return "center" if self.chk_center.isChecked() else "topleft"

    def size_mode(self):
        """(mode, pct) — 'fit' | 'actual' | 'scale'(pct)."""
        i = self.cmb_size.currentIndex()
        if i == 1:
            return ("actual", 100)
        if i == 2:
            return ("scale", int(self.sp_scale.value()))
        return ("fit", 100)

    def copies(self) -> int:
        return int(self.sp_copies.value())

    def color_mode(self):
        from PyQt6.QtPrintSupport import QPrinter
        t = self.cmb_color.currentText()
        if t == "컬러":
            return QPrinter.ColorMode.Color
        if t == "흑백":
            return QPrinter.ColorMode.GrayScale
        return None

    def duplex_mode(self):
        from PyQt6.QtPrintSupport import QPrinter
        return {
            "단면": QPrinter.DuplexMode.DuplexNone,
            "양면(긴 쪽)": QPrinter.DuplexMode.DuplexLongSide,
            "양면(짧은 쪽)": QPrinter.DuplexMode.DuplexShortSide,
        }.get(self.cmb_duplex.currentText())

    def include_decorations(self) -> bool:
        return self.cmb_include.currentText() != "문서만"

    def auto_orient(self) -> bool:
        return self.chk_auto_orient.isChecked()

    # ----- 기존 로직 -----
    def grp_order(self):
        return (self.rb_all, self.rb_cur, self.rb_thumb,
                self.rb_files, self.rb_range, self.rb_shot)

    # 260628: _reload_presets/_on_preset_pick/_on_nup_toggle/_open_nup/nup_enabled 는
    #   NupPresetMixin 공통 구현 사용(SOT §11.10).

    def _accept_pdf(self, *_):
        self._to_pdf = True
        self.accept()

    def to_pdf(self) -> bool:
        return self._to_pdf


    def nup_settings(self) -> dict:
        from viewer.twoup import merge_twoup_settings
        s = merge_twoup_settings(self._nup_settings)
        s["enabled"] = True
        return s

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
        if self.rb_files.isChecked():
            return {"mode": "files"}
        return {"mode": "shot"}
