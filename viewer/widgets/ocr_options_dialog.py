# -*- coding: utf-8 -*-
"""260909: [OCR 다시 읽기] 의 범위·언어·워터마크 (텍스트 창 SOT §3.1.2).

사용자 지시 셋을 한 창에 모은다.
  - "한글이 안 되고 있어" → 언어를 **고를 수 있게**(기본 한글+영문)
  - "문서 전체 OCR 도 선택적으로" → 범위(현재 쪽 / 쪽 범위 / 문서 전체)
  - "뒷배경 워터마크는 인식하지 않도록" → 체크상자(기본 켬)

값의 뜻과 한계는 SOT 가 갖는다. 이 창은 **고르게만** 한다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                             QRadioButton, QSpinBox, QCheckBox, QPushButton,
                             QDialogButtonBox, QButtonGroup)

# (표시 이름, Tesseract 언어 문자열) — "" 는 '자동'(텍스트층으로 짐작)
LANGS = [("한글 + 영문 (권장)", "kor+eng"),
         ("한글만", "kor"),
         ("영문만", "eng"),
         ("자동", "")]


class OcrOptionsDialog(QDialog):
    """반환값은 `values()` — {"pages": [0-based…], "lang": str, "watermark": bool}."""

    def __init__(self, parent=None, *, page: int = 0, page_count: int = 1,
                 last=None):
        super().__init__(parent)
        self.setWindowTitle("OCR 다시 읽기")
        self._page = int(page)
        self._count = max(1, int(page_count))
        last = last or {}

        v = QVBoxLayout(self)
        v.addWidget(QLabel("어디를 다시 읽을까요?"))

        self.rb_one = QRadioButton(f"현재 쪽 ({self._page + 1}쪽)")
        self.rb_range = QRadioButton("쪽 범위")
        self.rb_all = QRadioButton(f"문서 전체 ({self._count}쪽)")
        grp = QButtonGroup(self)
        for b in (self.rb_one, self.rb_range, self.rb_all):
            grp.addButton(b)
        self.rb_one.setChecked(True)
        v.addWidget(self.rb_one)

        row = QHBoxLayout()
        row.addWidget(self.rb_range)
        self.sp_from = QSpinBox()
        self.sp_to = QSpinBox()
        for sp in (self.sp_from, self.sp_to):
            sp.setRange(1, self._count)
            sp.setEnabled(False)
        self.sp_from.setValue(self._page + 1)
        self.sp_to.setValue(min(self._count, self._page + 10))
        row.addWidget(self.sp_from)
        row.addWidget(QLabel("~"))
        row.addWidget(self.sp_to)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(self.rb_all)
        self.rb_range.toggled.connect(self.sp_from.setEnabled)
        self.rb_range.toggled.connect(self.sp_to.setEnabled)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("언어"))
        self.cmb_lang = QComboBox()
        for name, code in LANGS:
            self.cmb_lang.addItem(name, code)
        want = last.get("lang", "kor+eng")
        i = self.cmb_lang.findData(want)
        self.cmb_lang.setCurrentIndex(i if i >= 0 else 0)
        row2.addWidget(self.cmb_lang, 1)
        v.addLayout(row2)

        self.cb_wm = QCheckBox("뒷배경 워터마크는 읽지 않기")
        self.cb_wm.setChecked(bool(last.get("watermark", True)))
        self.cb_wm.setToolTip(
            "본문 뒤에 연하게 깔린 글씨를 지우고 읽습니다. "
            "연한 진짜 글자(회색 캡션 등)도 함께 사라질 수 있습니다.")
        v.addWidget(self.cb_wm)

        self.cb_skip = QCheckBox("글자가 이미 있는 쪽은 건너뛰기 (권장)")
        self.cb_skip.setChecked(bool(last.get("skip_text", True)))
        self.cb_skip.setToolTip(
            "글자층이 멀쩡한 쪽은 OCR 이 원본보다 반드시 나쁩니다. "
            "그림이 섞인 쪽은 건너뛰지 않고, 그림 속 글만 더해 줍니다.")
        v.addWidget(self.cb_skip)

        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        v.addWidget(self.lbl_note)
        self._update_note()
        for w in (self.rb_one, self.rb_range, self.rb_all):
            w.toggled.connect(self._update_note)
        self.sp_from.valueChanged.connect(self._update_note)
        self.sp_to.valueChanged.connect(self._update_note)

        # 260909-2: 잘못 읽힌 문서를 **원래대로 되돌릴 길**이 있어야 한다(SOT §3.1.2).
        self._revert = False
        self.btn_revert = QPushButton("원래 글자층 보기")
        self.btn_revert.setToolTip("이 문서의 'OCR 로 보기' 표시를 지웁니다.")
        self.btn_revert.clicked.connect(self._do_revert)
        v.addWidget(self.btn_revert)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        for b in bb.buttons():
            b.setAutoDefault(False)     # 디자인 §2.7 — Enter 로 닫히지 않게
            b.setDefault(False)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _do_revert(self):
        self._revert = True
        self.accept()

    # ---------------- 값 ----------------
    def pages(self) -> list:
        if self.rb_all.isChecked():
            return list(range(self._count))
        if self.rb_range.isChecked():
            a, b = self.sp_from.value(), self.sp_to.value()
            if a > b:
                a, b = b, a
            return list(range(a - 1, b))
        return [self._page]

    def values(self) -> dict:
        return {"pages": self.pages(),
                "lang": self.cmb_lang.currentData() or "",
                "watermark": self.cb_wm.isChecked(),
                "skip_text": self.cb_skip.isChecked(),
                "revert": self._revert}

    def _update_note(self):
        n = len(self.pages())
        # 실측 300dpi 한 쪽 4.4초(단어학습 SOT §14.7) — 대략만 알린다
        secs = int(n * 4.5)
        if n <= 1:
            self.lbl_note.setText("한 쪽만 읽습니다. 몇 초 걸립니다.")
        elif secs < 90:
            self.lbl_note.setText(f"{n}쪽 — 대략 {secs}초 걸립니다. 도중에 멈출 수 있습니다.")
        else:
            self.lbl_note.setText(
                f"{n}쪽 — 대략 {secs // 60}분 걸립니다. 도중에 멈출 수 있고, "
                "읽은 쪽까지는 남습니다.")
