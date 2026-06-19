"""책갈피 자동 생성 대화상자 (v1.6.16 — 외부 pdf_bookmarker 호출).

OK 직후 호출부가 result_options() 로 입력을 받아 BookmarkerWorker 를 기동.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QSpinBox,
    QPushButton,
    QLabel,
    QLineEdit,
    QFileDialog,
    QDialogButtonBox,
)

from viewer import bookmarker_bridge as bridge


class BookmarkerDialog(QDialog):
    """입력 PDF/모드/오프셋/출력옵션 선택. 외부 모듈 미발견 시 OK 비활성."""

    def __init__(self, *, default_pdf: Optional[Path] = None,
                 prefs: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("책갈피 자동 생성")
        self.setMinimumWidth(560)
        p = dict(prefs or {})

        layout = QVBoxLayout(self)

        # 내장 라이브러리 안내
        info = QLabel(
            "내장 <b>pdf_bookmarker</b> 라이브러리를 사용합니다 "
            "(런타임 의존성: pypdf · pdfplumber · pypdfium2 — requirements.txt)."
        )
        info.setStyleSheet("color:#555;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # 가용성 안내 — 동적 재확인 (경로 변경 시 갱신)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        layout.addWidget(self.warn)

        # ── 입력 ───────────────────────────────────────────────────
        grp_in = QGroupBox("입력")
        fi = QFormLayout(grp_in)

        self.edit_input = QLineEdit(str(default_pdf) if default_pdf else "")
        self.edit_input.setPlaceholderText("PDF 파일 경로")
        btn_browse_in = QPushButton("...")
        btn_browse_in.setFixedWidth(32)
        btn_browse_in.clicked.connect(self._browse_input)
        row_in = QHBoxLayout()
        row_in.addWidget(self.edit_input, 1)
        row_in.addWidget(btn_browse_in)
        fi.addRow("PDF 파일:", row_in)

        # 모듈 경로(고급)
        self.edit_path = QLineEdit(p.get("bookmarker_path", ""))
        self.edit_path.setPlaceholderText(
            "(내장 라이브러리 사용 — 외부 버전을 쓰려면 여기에 경로 지정)"
        )
        btn_browse_path = QPushButton("...")
        btn_browse_path.setFixedWidth(32)
        btn_browse_path.clicked.connect(self._browse_pkg)
        row_path = QHBoxLayout()
        row_path.addWidget(self.edit_path, 1)
        row_path.addWidget(btn_browse_path)
        fi.addRow("모듈 경로(선택):", row_path)

        layout.addWidget(grp_in)

        # ── 모드 ───────────────────────────────────────────────────
        grp_mode = QGroupBox("추출 모드")
        mv = QVBoxLayout(grp_mode)
        ml = QHBoxLayout()
        self.rb_auto = QRadioButton("자동 (목차 있으면 TOC, 없으면 폰트)")
        self.rb_toc = QRadioButton("TOC 강제")
        self.rb_font = QRadioButton("폰트 강제")
        self.rb_ocr = QRadioButton("스캔/이미지 (OCR)")
        self.bg_mode = QButtonGroup(self)
        for rb in (self.rb_auto, self.rb_toc, self.rb_font, self.rb_ocr):
            self.bg_mode.addButton(rb)
            ml.addWidget(rb)
        mode = (p.get("bookmarker_mode") or "auto").lower()
        {"toc": self.rb_toc, "font": self.rb_font,
         "ocr": self.rb_ocr}.get(mode, self.rb_auto).setChecked(True)
        mv.addLayout(ml)
        # OCR 모드 보조 옵션
        self.chk_ocr_fontauto = QCheckBox(
            "큰 글자도 헤딩으로 포함 (정규식 'CHAPTER 1'·'제1장' 외에 본문보다 큰 줄)")
        self.chk_ocr_fontauto.setChecked(bool(p.get("bookmarker_ocr_font_auto", True)))
        mv.addWidget(self.chk_ocr_fontauto)
        self.lbl_ocr_hint = QLabel(
            "<small>스캔된 책의 'CHAPTER 1'·'제1장' 등을 Tesseract OCR로 인식해 책갈피를 만듭니다. "
            "스캔 페이지만 처리하며 페이지가 많으면 다소 시간이 걸립니다.</small>")
        self.lbl_ocr_hint.setStyleSheet("color:#888;")
        self.lbl_ocr_hint.setWordWrap(True)
        mv.addWidget(self.lbl_ocr_hint)
        layout.addWidget(grp_mode)
        self.rb_ocr.toggled.connect(self._sync_ocr_enabled)

        # ── 오프셋 (TOC 모드) ──────────────────────────────────────
        grp_off = QGroupBox("TOC 오프셋 (목차 표기 페이지 → 실제 페이지 보정)")
        fo = QFormLayout(grp_off)
        self.spin_offset = QSpinBox()
        self.spin_offset.setRange(-100, 200)
        self.spin_offset.setValue(0)
        self.spin_offset.setSpecialValueText("자동")     # 0 표시 시 '자동'
        self.spin_offset.setSuffix(" 페이지")
        fo.addRow("오프셋:", self.spin_offset)
        hint = QLabel("<small>0 = 추천 후보 1순위 사용. TOC 모드에서만 의미.</small>")
        hint.setStyleSheet("color:#888;")
        fo.addRow("", hint)
        layout.addWidget(grp_off)

        # ── 출력 ───────────────────────────────────────────────────
        grp_out = QGroupBox("출력")
        ol = QVBoxLayout(grp_out)

        # 260606-4: 새 PDF로 저장 / 현재 PDF에 저장 선택
        self.rb_save_new = QRadioButton("새 PDF로 저장")
        self.rb_save_over = QRadioButton("현재 PDF에 저장 (덮어쓰기)")
        self.bg_save = QButtonGroup(self)
        self.bg_save.addButton(self.rb_save_new)
        self.bg_save.addButton(self.rb_save_over)
        (self.rb_save_over if p.get("bookmarker_overwrite")
         else self.rb_save_new).setChecked(True)
        row_save = QHBoxLayout()
        row_save.addWidget(QLabel("PDF 저장:"))
        row_save.addWidget(self.rb_save_new)
        row_save.addWidget(self.rb_save_over)
        row_save.addStretch(1)
        ol.addLayout(row_save)
        self.rb_save_over.toggled.connect(self._sync_outdir_enabled)

        self.chk_txt = QCheckBox("알PDF용 책갈피 텍스트(.txt) 저장")
        self.chk_txt.setChecked(bool(p.get("bookmarker_save_txt", False)))
        ol.addWidget(self.chk_txt)

        # 출력 폴더
        self.edit_outdir = QLineEdit(
            str(default_pdf.parent) if default_pdf else ""
        )
        self.edit_outdir.setPlaceholderText("(비우면 PDF 파일과 같은 폴더)")
        self.btn_browse_out = QPushButton("...")
        self.btn_browse_out.setFixedWidth(32)
        self.btn_browse_out.clicked.connect(self._browse_outdir)
        row_out = QHBoxLayout()
        row_out.addWidget(QLabel("출력 폴더:"))
        row_out.addWidget(self.edit_outdir, 1)
        row_out.addWidget(self.btn_browse_out)
        ol.addLayout(row_out)

        # 260606-4: '자동 열기' 체크 제거 — 완료 시 항상 책갈피 새로고침(목록 유지)
        hint_out = QLabel("<small>완료 후 책갈피 목록이 자동 새로고침됩니다"
                          "(기존 파일 목록은 그대로 유지).</small>")
        hint_out.setStyleSheet("color:#888;")
        hint_out.setWordWrap(True)
        ol.addWidget(hint_out)

        layout.addWidget(grp_out)

        # ── 버튼 ───────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
        self.rb_toc.toggled.connect(self._sync_offset_enabled)
        self.rb_auto.toggled.connect(self._sync_offset_enabled)
        self.rb_ocr.toggled.connect(self._sync_offset_enabled)
        self._sync_offset_enabled()
        self._sync_ocr_enabled()
        self._sync_outdir_enabled()

        # v1.6.16: 모듈 경로 변경 시 동적 재확인 (300ms 디바운스)
        self._recheck_timer = QTimer(self)
        self._recheck_timer.setSingleShot(True)
        self._recheck_timer.setInterval(300)
        self._recheck_timer.timeout.connect(self._recheck_module)
        self.edit_path.textChanged.connect(lambda _t: self._recheck_timer.start())
        # 초기 1회 확인
        self._recheck_module()

    def _recheck_module(self):
        """모듈 가용성 재확인 후 OK/경고 UI 갱신."""
        path = self.edit_path.text().strip() or None
        ok = bridge.recheck(path)
        self._ok_btn.setEnabled(ok)
        if ok:
            self.warn.setText(
                f"<small style='color:#070'>모듈 로드 완료 — {bridge.get_status()}</small>"
            )
            self.warn.setStyleSheet("padding:4px; background:#f4fff4;")
        else:
            self.warn.setText(
                "<b>라이브러리 로드 실패.</b><br>"
                f"<small>{bridge.get_status()}</small><br>"
                "런타임 의존성을 설치하세요:<br>"
                "  • <code>pip install -r requirements.txt</code> "
                "(또는 <code>pip install pdfplumber pypdfium2 pypdf</code>)"
            )
            self.warn.setStyleSheet("color:#a33; padding:6px; background:#fff4f4;")

    # --- helpers ----------------------------------------------------
    def _browse_input(self):
        start = self.edit_input.text() or ""
        fn, _ = QFileDialog.getOpenFileName(self, "PDF 선택", start, "PDF (*.pdf)")
        if fn:
            self.edit_input.setText(fn)
            if not self.edit_outdir.text():
                self.edit_outdir.setText(str(Path(fn).parent))

    def _browse_pkg(self):
        start = self.edit_path.text() or ""
        d = QFileDialog.getExistingDirectory(self, "pdf_bookmarker 패키지의 부모 폴더", start)
        if d:
            self.edit_path.setText(d)
            self._recheck_module()           # 즉시 재확인

    def _browse_outdir(self):
        start = self.edit_outdir.text() or ""
        d = QFileDialog.getExistingDirectory(self, "출력 폴더", start)
        if d:
            self.edit_outdir.setText(d)

    def _sync_offset_enabled(self):
        # 폰트·OCR 모드면 오프셋 무의미
        on = not (self.rb_font.isChecked() or self.rb_ocr.isChecked())
        self.spin_offset.setEnabled(on)

    def _sync_ocr_enabled(self):
        on = self.rb_ocr.isChecked()
        self.chk_ocr_fontauto.setEnabled(on)
        self.lbl_ocr_hint.setEnabled(on)

    def _sync_outdir_enabled(self):
        # 260606-4: '현재 PDF에 저장'이면 출력 폴더는 의미 없음 → 비활성
        over = self.rb_save_over.isChecked()
        self.edit_outdir.setEnabled(not over)
        self.btn_browse_out.setEnabled(not over)

    def _mode(self) -> str:
        if self.rb_toc.isChecked():
            return "toc"
        if self.rb_font.isChecked():
            return "font"
        if self.rb_ocr.isChecked():
            return "ocr"
        return "auto"

    # --- 결과 -------------------------------------------------------
    def result_options(self) -> dict:
        return {
            "input_pdf": self.edit_input.text().strip(),
            "bookmarker_path": self.edit_path.text().strip(),
            "mode": self._mode(),
            "ocr_font_auto": self.chk_ocr_fontauto.isChecked(),
            "offset": (None if self.spin_offset.value() == 0
                       else int(self.spin_offset.value())),
            "save_pdf": True,
            "overwrite": self.rb_save_over.isChecked(),
            "save_txt": self.chk_txt.isChecked(),
            "out_dir": self.edit_outdir.text().strip(),
        }
