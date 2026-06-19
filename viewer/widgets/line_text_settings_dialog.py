"""260611-78: '선과 텍스트 입력 설정' — 탭 2개(선긋기 / 글쓰기) 통합 대화상자.

- 선긋기 탭: 5펜 색·굵기·투명도 + 하이라이트 투명도 + 지우개 면적(기존 선긋기 설정 이동).
- 글쓰기 탭: 최대 7개 사용자 스타일 관리(이름·저장·삭제·위/아래) + 스타일 편집기
  (폰트·색상·크기·박스선 on/off·배경색+불투명도·정렬·지시선 끝모양).
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QColorDialog,
    QGroupBox, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QLineEdit,
    QListWidget, QTabWidget, QWidget, QFormLayout, QDialogButtonBox, QMessageBox,
)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt

from viewer.widgets.pen_settings_dialog import _ColorBtn

MAX_STYLES = 7
_FONTS = ["맑은 고딕", "굴림", "바탕", "돋움"]
_TIP_GLYPH = [("arrow", "→", "뾰족한 화살표"), ("circle", "●", "끝 원형"),
              ("plain", "—", "직선")]


def _wrap(layout):
    w = QWidget(); layout.setContentsMargins(0, 0, 0, 0); w.setLayout(layout)
    return w


class LineTextSettingsDialog(QDialog):
    def __init__(self, pens, eraser_widths, highlight_alpha, styles, parent=None):
        super().__init__(parent)
        self.setWindowTitle("선과 텍스트 입력 설정")
        self.resize(520, 560)
        self._styles = [dict(s) for s in (styles or [])]
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_line_tab(pens, eraser_widths, highlight_alpha), "선긋기")
        tabs.addTab(self._build_text_tab(), "글쓰기")
        v.addWidget(tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)

    # ---------------- 선긋기 탭 ----------------
    def _build_line_tab(self, pens, eraser_widths, highlight_alpha):
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel("편집모드 본문/발표에서 왼쪽 드래그로 선을 긋습니다(설정 공유).\n"
                           "선 1~5의 색·굵기·투명도. 투명도 100%=안 보임, 0%=불투명."))
        self._pen_rows = []
        for i, pr in enumerate(pens):
            grp = QGroupBox(f"선 {i + 1}"); h = QHBoxLayout(grp)
            h.addWidget(QLabel("색:")); cb = _ColorBtn(pr.get("color", "#ff3030")); h.addWidget(cb)
            h.addWidget(QLabel("굵기:"))
            sw = QSpinBox(); sw.setRange(1, 40); sw.setValue(int(pr.get("width", 3))); h.addWidget(sw)
            h.addWidget(QLabel("투명도:"))
            stp = QSpinBox(); stp.setRange(0, 100); stp.setSuffix(" %")
            stp.setValue(100 - int(pr.get("alpha", 100))); h.addWidget(stp)
            h.addStretch(1)
            v.addWidget(grp); self._pen_rows.append((cb, sw, stp))
        hg = QGroupBox("하이라이트"); hh = QHBoxLayout(hg)
        hh.addWidget(QLabel("투명도:"))
        self._sp_hl = QSpinBox(); self._sp_hl.setRange(0, 100); self._sp_hl.setSuffix(" %")
        self._sp_hl.setValue(100 - int(highlight_alpha or 35))
        hh.addWidget(self._sp_hl); hh.addStretch(1); v.addWidget(hg)
        ew = list(eraser_widths or [12, 30])
        eg = QGroupBox("지우개 면적(px)"); eh = QHBoxLayout(eg)
        eh.addWidget(QLabel("얇게:"))
        self._sp_e1 = QSpinBox(); self._sp_e1.setRange(4, 80)
        self._sp_e1.setValue(int(ew[0]) if ew else 12); eh.addWidget(self._sp_e1)
        eh.addWidget(QLabel("두껍게:"))
        self._sp_e2 = QSpinBox(); self._sp_e2.setRange(4, 160)
        self._sp_e2.setValue(int(ew[1]) if len(ew) > 1 else 30); eh.addWidget(self._sp_e2)
        eh.addStretch(1); v.addWidget(eg); v.addStretch(1)
        return w

    def result_pens(self):
        return [{"name": f"선 {i + 1}", "color": cb.color_name(),
                 "width": int(sw.value()), "alpha": 100 - int(stp.value())}
                for i, (cb, sw, stp) in enumerate(self._pen_rows)]

    def result_eraser_widths(self):
        return [int(self._sp_e1.value()), int(self._sp_e2.value())]

    def result_highlight_alpha(self):
        return 100 - int(self._sp_hl.value())

    # ---------------- 글쓰기 탭 ----------------
    def _build_text_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel(f"사용자 스타일(최대 {MAX_STYLES}개). 이름을 적고 아래 설정 후 [저장].\n"
                           "상단 버튼 풀다운에서 선택해 글쓰기/지시선에 적용합니다."))
        # 260611-80: 이름 입력을 리스트 위로
        row_save = QHBoxLayout()
        row_save.addWidget(QLabel("이름:"))
        self._ed_name = QLineEdit(); row_save.addWidget(self._ed_name, 1)
        b_save = QPushButton("저장"); b_save.clicked.connect(self._style_save)
        row_save.addWidget(b_save)
        v.addLayout(row_save)
        # 스타일 목록(약 5줄 표시, 초과 시 스크롤) + 관리 버튼
        top = QHBoxLayout()
        self._lst = QListWidget()
        rowh = self._lst.sizeHintForRow(0)
        if rowh <= 0:
            rowh = 22
        self._lst.setFixedHeight(rowh * 5 + 6)        # 약 5개 표시
        self._lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._lst.currentRowChanged.connect(self._on_pick_style)
        top.addWidget(self._lst, 1)
        col = QVBoxLayout()
        b_del = QPushButton("삭제"); b_del.clicked.connect(self._style_delete)
        b_up = QPushButton("▲"); b_up.clicked.connect(lambda: self._style_move(-1))
        b_dn = QPushButton("▼"); b_dn.clicked.connect(lambda: self._style_move(1))
        for b in (b_del, b_up, b_dn):
            col.addWidget(b)
        col.addStretch(1)
        top.addLayout(col)
        v.addLayout(top)

        # 하단: 스타일 편집기
        form = QFormLayout()
        self._cmb_font = QComboBox(); self._cmb_font.addItems(_FONTS)
        self._cb_bold = QCheckBox("굵게"); self._cb_italic = QCheckBox("기울임")
        rf = QHBoxLayout(); rf.addWidget(self._cmb_font, 1)
        rf.addWidget(self._cb_bold); rf.addWidget(self._cb_italic)
        form.addRow("문자 폰트", _wrap(rf))
        self._cb_color = _ColorBtn("#111111"); form.addRow("문자 색상", self._cb_color)
        self._sp_size = QDoubleSpinBox(); self._sp_size.setRange(0.5, 15.0)
        self._sp_size.setSingleStep(0.2); self._sp_size.setSuffix(" %")
        form.addRow("문자 크기(페이지 대비)", self._sp_size)
        self._cb_boxline = QCheckBox("적용 (색·굵기·투명도는 색상버튼 스타일)")
        form.addRow("텍스트 박스선", self._cb_boxline)
        self._cb_bg = QCheckBox("적용"); self._cb_bgcolor = _ColorBtn("#fff7c0")
        self._sp_bga = QSpinBox(); self._sp_bga.setRange(0, 100); self._sp_bga.setSuffix(" %")
        rbg = QHBoxLayout(); rbg.addWidget(self._cb_bg); rbg.addWidget(self._cb_bgcolor)
        rbg.addWidget(QLabel("불투명도:")); rbg.addWidget(self._sp_bga); rbg.addStretch(1)
        form.addRow("텍스트 박스 배경", _wrap(rbg))
        self._cmb_align = QComboBox(); self._cmb_align.addItems(["왼쪽", "가운데", "오른쪽"])
        form.addRow("정렬", self._cmb_align)
        # 지시선 끝모양(글쓰기 모드에는 미적용)
        self._tip = "arrow"; self._tip_btns = {}
        rtip = QHBoxLayout()
        for key, glyph, tip in _TIP_GLYPH:
            b = QPushButton(glyph); b.setCheckable(True); b.setFixedWidth(46); b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self._set_tip(k))
            self._tip_btns[key] = b; rtip.addWidget(b)
        rtip.addStretch(1)
        form.addRow("지시선 끝모양", _wrap(rtip))
        v.addLayout(form); v.addStretch(1)

        self._refresh_list()
        if self._styles:
            self._lst.setCurrentRow(0)
        return w

    def _set_tip(self, key):
        self._tip = key
        for k, b in self._tip_btns.items():
            b.setChecked(k == key)

    def _refresh_list(self):
        self._lst.blockSignals(True)
        self._lst.clear()
        for s in self._styles:
            self._lst.addItem(s.get("name", ""))
        self._lst.blockSignals(False)

    def _editor_to_style(self, name):
        return {"name": name, "family": self._cmb_font.currentText(),
                "color": self._cb_color.color_name(),
                "size": self._sp_size.value() / 100.0,
                "bold": self._cb_bold.isChecked(), "italic": self._cb_italic.isChecked(),
                "box_line": self._cb_boxline.isChecked(),
                "bg": self._cb_bgcolor.color_name() if self._cb_bg.isChecked() else None,
                "bg_alpha": int(self._sp_bga.value()),
                "align": self._cmb_align.currentIndex(), "tip": self._tip}

    def _load_style(self, s):
        self._ed_name.setText(s.get("name", ""))
        i = self._cmb_font.findText(s.get("family", "맑은 고딕"))
        self._cmb_font.setCurrentIndex(max(0, i))
        self._cb_color._color = QColor(s.get("color", "#111111")); self._cb_color._apply()
        self._sp_size.setValue(float(s.get("size", 0.022)) * 100.0)
        self._cb_bold.setChecked(bool(s.get("bold", False)))
        self._cb_italic.setChecked(bool(s.get("italic", False)))
        self._cb_boxline.setChecked(bool(s.get("box_line", False)))
        self._cb_bg.setChecked(s.get("bg") is not None)
        self._cb_bgcolor._color = QColor(s.get("bg") or "#fff7c0"); self._cb_bgcolor._apply()
        self._sp_bga.setValue(int(s.get("bg_alpha", 100)))
        self._cmb_align.setCurrentIndex(int(s.get("align", 0)))
        self._set_tip(s.get("tip", "arrow"))

    def _on_pick_style(self, row):
        if 0 <= row < len(self._styles):
            self._load_style(self._styles[row])

    def _style_save(self):
        name = self._ed_name.text().strip()
        if not name:
            QMessageBox.information(self, "스타일 저장", "스타일 이름을 입력하세요."); return
        existing = next((i for i, s in enumerate(self._styles) if s.get("name") == name), -1)
        if existing >= 0:
            if QMessageBox.question(
                    self, "스타일 덮어쓰기",
                    f"이미 '{name}' 스타일이 있습니다. 덮어쓸까요?") \
                    != QMessageBox.StandardButton.Yes:
                return
            self._styles[existing] = self._editor_to_style(name)
            self._refresh_list(); self._lst.setCurrentRow(existing)
            return
        if len(self._styles) >= MAX_STYLES:
            QMessageBox.warning(self, "스타일 저장",
                                f"스타일은 최대 {MAX_STYLES}개까지 저장할 수 있습니다."); return
        self._styles.append(self._editor_to_style(name))
        self._refresh_list(); self._lst.setCurrentRow(len(self._styles) - 1)

    def _style_delete(self):
        row = self._lst.currentRow()
        if 0 <= row < len(self._styles):
            del self._styles[row]
            self._refresh_list()
            self._lst.setCurrentRow(min(row, len(self._styles) - 1))

    def _style_move(self, delta):
        row = self._lst.currentRow(); new = row + delta
        if 0 <= row < len(self._styles) and 0 <= new < len(self._styles):
            self._styles[row], self._styles[new] = self._styles[new], self._styles[row]
            self._refresh_list(); self._lst.setCurrentRow(new)

    def result_styles(self):
        return [dict(s) for s in self._styles]
