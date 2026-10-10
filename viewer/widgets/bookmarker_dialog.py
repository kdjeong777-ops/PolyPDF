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
    QGridLayout,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QSpinBox,
    QPushButton,
    QLabel,
    QLineEdit,
    QFileDialog,
    QWidget,
    QDialogButtonBox,
)

from viewer import bookmarker_bridge as bridge
from viewer.i18n import tr


class BookmarkerDialog(QDialog):
    """입력 PDF/모드/오프셋/출력옵션 선택. 외부 모듈 미발견 시 OK 비활성."""

    def __init__(self, *, default_pdf: Optional[Path] = None,
                 prefs: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("책갈피 자동 생성"))
        self.setMinimumWidth(560)
        p = dict(prefs or {})

        layout = QVBoxLayout(self)

        # 260905(§4.4.6.1): 모듈 안내는 **로드에 실패했을 때만** 보인다.
        #   내장본이라 실사용에서 실패하지 않는데도 "로드 완료 — <내부 경로>" 상자가
        #   창을 열 때마다 첫 두 줄을 차지하고 설치 경로까지 드러냈다.
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setVisible(False)
        layout.addWidget(self.warn)

        # ── 입력 ───────────────────────────────────────────────────
        grp_in = QGroupBox(tr("입력"))
        fi = QFormLayout(grp_in)

        self.edit_input = QLineEdit(str(default_pdf) if default_pdf else "")
        self.edit_input.setPlaceholderText(tr("PDF 파일 경로"))
        btn_browse_in = QPushButton("...")
        btn_browse_in.setFixedWidth(32)
        btn_browse_in.clicked.connect(self._browse_input)
        row_in = QHBoxLayout()
        row_in.addWidget(self.edit_input, 1)
        row_in.addWidget(btn_browse_in)
        fi.addRow(tr("PDF 파일:"), row_in)

        # 260905(§4.4.6.1): '모듈 경로(선택)' 입력칸 삭제 — 내장본을 쓰므로 외부 버전을
        #   가리킬 이유가 없고, 잘못 지정하면 로드만 깨진다(설정 bookmarker_path 도 제거).

        layout.addWidget(grp_in)

        # ── 260904-10: 기존 책갈피가 있으면 새로 만들지 / 고칠지 ──────────
        self.grp_exist = QGroupBox(tr("기존 책갈피"))
        ev = QVBoxLayout(self.grp_exist)
        self.lbl_exist = QLabel()
        self.lbl_exist.setWordWrap(True)
        ev.addWidget(self.lbl_exist)
        self.rb_bm_new = QRadioButton(tr("새로 만들기 — 목차를 다시 읽어 기존 책갈피를 대체합니다"))
        self.rb_bm_edit = QRadioButton(tr("기존 책갈피 수정 — 지금 책갈피를 표로 불러와 제목·레벨·쪽을 고칩니다"))
        self.bg_exist = QButtonGroup(self)
        for rb in (self.rb_bm_edit, self.rb_bm_new):
            self.bg_exist.addButton(rb)
            ev.addWidget(rb)
        self.rb_bm_edit.setChecked(True)              # 있는 책갈피를 지우지 않는 쪽이 기본
        self.rb_bm_edit.toggled.connect(self._sync_exist_mode)
        layout.addWidget(self.grp_exist)
        self.grp_exist.setVisible(False)

        # ── 모드 ───────────────────────────────────────────────────
        grp_mode = QGroupBox(tr("추출 모드"))
        self.grp_mode = grp_mode
        mv = QVBoxLayout(grp_mode)
        # 261010-6(디자인 SOT §2.15): 종전 흐르는 줄은 둘째 줄로 넘어가도 창이 그 높이를 주지 않아 '스캔/이미지 (OCR)' 가
        #   아래 체크박스와 겹쳤다 — 2×2 격자로 줄 수를 정해 둔다(가장 긴 '자동 (…)' 도 한 칸에 들어간다).
        ml = QGridLayout()
        ml.setHorizontalSpacing(10)
        self.rb_auto = QRadioButton(tr("자동 (목차 있으면 TOC, 없으면 폰트)"))
        self.rb_toc = QRadioButton(tr("TOC 강제"))
        self.rb_font = QRadioButton(tr("폰트 강제"))
        self.rb_ocr = QRadioButton(tr("스캔/이미지 (OCR)"))
        self.bg_mode = QButtonGroup(self)
        for i, rb in enumerate((self.rb_auto, self.rb_toc, self.rb_font, self.rb_ocr)):
            self.bg_mode.addButton(rb)
            ml.addWidget(rb, i // 2, i % 2)
        ml.setColumnStretch(2, 1)
        mode = (p.get("bookmarker_mode") or "auto").lower()
        {"toc": self.rb_toc, "font": self.rb_font,
         "ocr": self.rb_ocr}.get(mode, self.rb_auto).setChecked(True)
        mv.addLayout(ml)
        # OCR 모드 보조 옵션 — 체크박스 글자는 줄바꿈이 안 되므로 이름만, 풀이는 아래 작은 글씨(디자인 SOT §2.14)
        self.chk_ocr_fontauto = QCheckBox(tr("큰 글자도 헤딩으로 포함"))
        self.chk_ocr_fontauto.setToolTip(tr("정규식 'CHAPTER 1'·'제1장' 외에 본문보다 큰 줄도 헤딩으로 봅니다"))
        self.chk_ocr_fontauto.setChecked(bool(p.get("bookmarker_ocr_font_auto", True)))
        mv.addWidget(self.chk_ocr_fontauto)
        self.lbl_ocr_hint = QLabel(
            tr("<small>스캔된 책의 'CHAPTER 1'·'제1장' 등을 Tesseract OCR로 인식해 책갈피를 만듭니다. "
            "스캔 페이지만 처리하며 페이지가 많으면 다소 시간이 걸립니다.</small>"))
        self.lbl_ocr_hint.setStyleSheet("color:#888;")
        self.lbl_ocr_hint.setWordWrap(True)
        mv.addWidget(self.lbl_ocr_hint)
        layout.addWidget(grp_mode)
        self.rb_ocr.toggled.connect(self._sync_ocr_enabled)

        # ── 260904-1(§4.4): 목차 쪽 지정 + 검토 표 ─────────────────────
        grp_toc = QGroupBox(tr("목차(차례) 쪽 지정 — 자동 탐지가 놓칠 때"))
        self.grp_toc = grp_toc
        ft = QFormLayout(grp_toc)
        self.edit_toc_pages = QLineEdit("")
        self.edit_toc_pages.setPlaceholderText(tr("예: 6-11  (비우면 자동 탐지 — PDF 쪽 번호, 1부터)"))
        self.btn_detect_toc = QPushButton(tr("자동 탐지"))
        self.btn_detect_toc.setToolTip(tr("PDF 앞부분에서 목차로 보이는 쪽을 찾아 채웁니다"))
        self.btn_detect_toc.setAutoDefault(False); self.btn_detect_toc.setDefault(False)
        self.btn_detect_toc.clicked.connect(self._detect_toc_pages)
        row_toc = QHBoxLayout()
        row_toc.addWidget(self.edit_toc_pages, 1)
        row_toc.addWidget(self.btn_detect_toc)
        ft.addRow(tr("목차 쪽:"), row_toc)
        self.chk_review = QCheckBox(tr("저장 전에 책갈피 표를 검토한다"))
        self.chk_review.setToolTip(tr("검토 표에서 실제 쪽과 대조해 고치거나 지우고 더할 수 있습니다"))
        self.chk_review.setChecked(bool(p.get("bookmarker_review", True)))
        ft.addRow(self.chk_review)                     # 이름 칸 없이 두 칸 폭(디자인 SOT §2.14)
        hint_toc = QLabel(tr("<small>스캔본처럼 목차를 못 알아보는 책은 목차 쪽을 직접 적어 주세요. "
                          "검토 표에서는 오프셋(목차 쪽→실제 쪽)을 추천받고, 행마다 실제 쪽을 미리보기로 확인해 고칠 수 있습니다.</small>"))
        hint_toc.setStyleSheet("color:#888;"); hint_toc.setWordWrap(True)
        ft.addRow(hint_toc)

        # ── 오프셋 (TOC 모드) ──────────────────────────────────────
        # 261010-6(디자인 SOT §2.15): 따로 있던 'TOC 오프셋' 묶음을 목차 묶음의 한 줄로 — 겹침을 풀며 늘어난 높이를 되찾아
        #   작은 화면(1366×768)에 들어가게. 묶음 제목은 칸의 툴팁, 풀이는 칸 옆 작은 글씨.
        self.spin_offset = QSpinBox()
        self.spin_offset.setToolTip(tr("TOC 오프셋 (목차 표기 페이지 → 실제 페이지 보정)"))
        self.spin_offset.setRange(-100, 200)
        self.spin_offset.setValue(0)
        self.spin_offset.setSpecialValueText(tr("자동"))     # 0 표시 시 '자동'
        self.spin_offset.setSuffix(tr(" 페이지"))
        hint = QLabel(tr("<small>0 = 추천 후보 1순위 사용. TOC 모드에서만 의미.</small>"))
        hint.setStyleSheet("color:#888;")
        self.grp_off = QWidget()                       # 기존 책갈피 수정이면 함께 꺼진다(_sync_exist_mode)
        ro = QHBoxLayout(self.grp_off)
        ro.setContentsMargins(0, 0, 0, 0)
        ro.addWidget(self.spin_offset)
        ro.addWidget(hint, 1)
        ft.addRow(tr("오프셋:"), self.grp_off)
        layout.addWidget(grp_toc)

        # ── 출력 ───────────────────────────────────────────────────
        grp_out = QGroupBox(tr("출력"))
        ol = QVBoxLayout(grp_out)

        # 260606-4: 새 PDF로 저장 / 현재 PDF에 저장 선택
        self.rb_save_new = QRadioButton(tr("새 PDF로 저장"))
        self.rb_save_over = QRadioButton(tr("현재 PDF에 저장 (덮어쓰기)"))
        self.bg_save = QButtonGroup(self)
        self.bg_save.addButton(self.rb_save_new)
        self.bg_save.addButton(self.rb_save_over)
        (self.rb_save_over if p.get("bookmarker_overwrite")
         else self.rb_save_new).setChecked(True)
        row_save = QHBoxLayout()
        row_save.addWidget(QLabel(tr("PDF 저장:")))
        row_save.addWidget(self.rb_save_new)
        row_save.addWidget(self.rb_save_over)
        row_save.addStretch(1)
        ol.addLayout(row_save)
        self.rb_save_over.toggled.connect(self._sync_outdir_enabled)

        self.chk_txt = QCheckBox(tr("알PDF용 책갈피 텍스트(.txt) 저장"))
        self.chk_txt.setChecked(bool(p.get("bookmarker_save_txt", False)))
        ol.addWidget(self.chk_txt)

        # 출력 폴더
        self.edit_outdir = QLineEdit(
            str(default_pdf.parent) if default_pdf else ""
        )
        self.edit_outdir.setPlaceholderText(tr("(비우면 PDF 파일과 같은 폴더)"))
        self.btn_browse_out = QPushButton("...")
        self.btn_browse_out.setFixedWidth(32)
        self.btn_browse_out.clicked.connect(self._browse_outdir)
        row_out = QHBoxLayout()
        row_out.addWidget(QLabel(tr("출력 폴더:")))
        row_out.addWidget(self.edit_outdir, 1)
        row_out.addWidget(self.btn_browse_out)
        ol.addLayout(row_out)

        # 260606-4: '자동 열기' 체크 제거 — 완료 시 항상 책갈피 새로고침(목록 유지)
        hint_out = QLabel(tr("<small>완료 후 책갈피 목록이 자동 새로고침됩니다"
                          "(기존 파일 목록은 그대로 유지).</small>"))
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

        # 261010-6(디자인 SOT §2.15): 최상위 창은 줄바꿈 높이(heightForWidth)를 스스로 맞추지 않는다 — 보일 때·폭이 바뀔 때 맞춘다
        self._fit_pending = False

        # v1.6.16: 모듈 경로 변경 시 동적 재확인 (300ms 디바운스)
        self._recheck_timer = QTimer(self)
        self._recheck_timer.setSingleShot(True)
        self._recheck_timer.setInterval(300)
        self._recheck_timer.timeout.connect(self._recheck_module)
        # 260904-10: 입력 PDF 가 바뀌면 기존 책갈피 개수를 다시 센다(300ms 디바운스)
        self._exist_timer = QTimer(self)
        self._exist_timer.setSingleShot(True)
        self._exist_timer.setInterval(300)
        self._exist_timer.timeout.connect(self._recheck_existing)
        self.edit_input.textChanged.connect(lambda _t: self._exist_timer.start())
        # 초기 1회 확인
        self._recheck_module()
        self._recheck_existing()

    # --- 261010-6: 줄바꿈 높이 맞추기(디자인 SOT §2.15) -----------------
    def _fit_height(self):
        """지금 폭에서 레이아웃이 필요한 높이를 최소 높이로 — 모자라면 창을 그만큼 키운다."""
        self._fit_pending = False
        lay = self.layout()
        if lay is None:
            return
        lay.activate()
        need = lay.totalHeightForWidth(self.width()) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        if need > 0 and need != self.minimumHeight():
            self.setMinimumHeight(need)
            if self.height() < need:
                self.resize(self.width(), need)

    def _schedule_fit(self):
        if not self._fit_pending:
            self._fit_pending = True
            QTimer.singleShot(0, self._fit_height)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._fit_height()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if ev.oldSize().width() != ev.size().width():
            self._schedule_fit()

    # --- 260904-10: 기존 책갈피 ---------------------------------------
    def _recheck_existing(self):
        """입력 PDF 의 기존 책갈피 개수를 세어 선택 그룹을 보이거나 감춘다."""
        fn = self.edit_input.text().strip()
        n = 0
        if fn and Path(fn).exists() and fn.lower().endswith(".pdf"):
            try:
                from viewer import toc_parse
                n = len(toc_parse.existing_rows(fn))
            except Exception:
                n = 0
        self._existing_count = n
        self.grp_exist.setVisible(n > 0)
        if n:
            self.lbl_exist.setText(
                tr('이 PDF에는 이미 책갈피 <b>{n}개</b>가 있습니다. 어떻게 할지 고르세요.').format(n=n))
        self._sync_exist_mode()
        if self.isVisible():
            self._schedule_fit()                       # 묶음이 나타나거나 사라지면 높이가 바뀐다

    def _sync_exist_mode(self):
        """'기존 책갈피 수정'이면 추출(모드·목차 쪽·오프셋)은 쓰지 않으므로 비활성."""
        edit = self.editing_existing()
        for w in (self.grp_mode, self.grp_toc, self.grp_off):
            w.setEnabled(not edit)

    def editing_existing(self) -> bool:
        """기존 책갈피를 고치는 경로인가(기존 책갈피가 있고 '수정'을 골랐을 때)."""
        return bool(getattr(self, "_existing_count", 0)) and self.rb_bm_edit.isChecked()

    def _recheck_module(self):
        """260905(§4.4.6.1): 모듈 가용성 확인 — **실패했을 때만** 안내를 띄운다."""
        ok = bridge.recheck(None)
        self._ok_btn.setEnabled(ok)
        if ok:
            self.warn.clear()
            self.warn.setVisible(False)
            return
        self.warn.setText(
            tr('<b>pdf_bookmarker 라이브러리를 불러오지 못했습니다.</b><br><small>{get_status}</small><br>런타임 의존성(pypdf · pdfplumber · pypdfium2)을 설치하세요:<br>  • <code>pip install -r requirements.txt</code> (또는 <code>pip install pdfplumber pypdfium2 pypdf</code>)').format(get_status=bridge.get_status())
        )
        self.warn.setStyleSheet("color:#a33; padding:6px; background:#fff4f4;")
        self.warn.setVisible(True)
        if self.isVisible():
            self._schedule_fit()

    # --- helpers ----------------------------------------------------
    def _browse_input(self):
        start = self.edit_input.text() or ""
        fn, _ = QFileDialog.getOpenFileName(self, tr("PDF 선택"), start, "PDF (*.pdf)")
        if fn:
            self.edit_input.setText(fn)
            if not self.edit_outdir.text():
                self.edit_outdir.setText(str(Path(fn).parent))

    def _browse_outdir(self):
        start = self.edit_outdir.text() or ""
        d = QFileDialog.getExistingDirectory(self, tr("출력 폴더"), start)
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

    def _detect_toc_pages(self):
        """260904-1: 내장 탐지기로 목차 쪽 후보를 채운다(없으면 안내)."""
        fn = self.edit_input.text().strip()
        if not fn or not Path(fn).exists():
            self.edit_toc_pages.setPlaceholderText(tr("먼저 PDF 파일을 지정하세요"))
            return
        from viewer import toc_parse
        try:
            pages = toc_parse.find_toc_pages(fn)         # 260904-2: 관대한 탐지(표본 6~11쪽)
        except Exception:
            pages = []
        if pages:
            self.edit_toc_pages.setText(toc_parse.format_page_spec(pages))
        else:
            self.edit_toc_pages.setText("")
            self.edit_toc_pages.setPlaceholderText(tr("자동 탐지 실패 — 목차 쪽을 직접 입력하세요(예: 6-11)"))

    def toc_pages(self) -> list:
        """입력한 목차 쪽 목록(1-based). 비면 []."""
        fn = self.edit_input.text().strip()
        n = 10 ** 6
        try:
            import fitz
            d = fitz.open(fn); n = d.page_count; d.close()
        except Exception:
            pass
        from viewer import toc_parse
        return toc_parse.parse_page_spec(self.edit_toc_pages.text(), n)

    # --- 결과 -------------------------------------------------------
    def result_options(self) -> dict:
        edit = self.editing_existing()                        # 260904-10
        return {
            "input_pdf": self.edit_input.text().strip(),
            "toc_pages": [] if edit else self.toc_pages(),     # 260904-1
            "review": True if edit else self.chk_review.isChecked(),
            "mode": "existing" if edit else self._mode(),
            "ocr_font_auto": self.chk_ocr_fontauto.isChecked(),
            "offset": (None if self.spin_offset.value() == 0
                       else int(self.spin_offset.value())),
            "save_pdf": True,
            "overwrite": self.rb_save_over.isChecked(),
            "save_txt": self.chk_txt.isChecked(),
            "out_dir": self.edit_outdir.text().strip(),
        }
