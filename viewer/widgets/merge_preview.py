# -*- coding: utf-8 -*-
"""260611-37/40/41: 병합 미리보기 — 합성 시트를 넘겨보며 여백·간격·크롭 조정(스핀박스+드래그).
가이드=여백/크롭/숨김(옵션버튼), 전체화면 보기 지원."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QSpinBox,
    QDialogButtonBox, QWidget, QLabel, QPushButton, QComboBox,
    QRadioButton, QButtonGroup,
)

from viewer.twoup import compose_preview, merge_twoup_settings

_KEYS = ("margin_top", "margin_bottom", "margin_left", "margin_right",
         "gap", "gap_v", "crop_top", "crop_bottom", "crop_left", "crop_right")
_MARGIN = ("margin_left", "margin_right", "margin_top", "margin_bottom")
_GAP = ("gap", "gap_v")
_SPACING = _MARGIN + _GAP
_CROP = ("crop_top", "crop_bottom", "crop_left", "crop_right")


class _PreviewCanvas(QWidget):
    changed = pyqtSignal(str, int)

    def __init__(self):
        super().__init__()
        self._pm = None
        self._ow = 1.0; self._oh = 1.0
        self._cells = []
        self._vals = {}
        self._drag = None
        self._show = "margin"        # margin | crop | none
        self.setMouseTracking(True)
        self.setMinimumSize(340, 440)

    def set_show(self, mode):
        self._show = mode
        self.update()

    def set_image(self, png, ow, oh, cells, vals):
        pm = QPixmap()
        pm.loadFromData(png, "PNG")
        self._pm = pm
        self._ow, self._oh = float(ow), float(oh)
        self._cells = cells; self._vals = vals
        self.update()

    def _disp(self):
        if self._pm is None or self._ow <= 0:
            return 0.0, 0.0, 1.0
        sc = min(self.width() / self._ow, self.height() / self._oh) * 0.96
        dw = self._ow * sc; dh = self._oh * sc
        return (self.width() - dw) / 2.0, (self.height() - dh) / 2.0, sc

    def _cols_rows(self):
        if not self._cells:
            return 1, 1
        y0 = self._cells[0][1]
        cols = max(1, sum(1 for c in self._cells if abs(c[1] - y0) < 1.0))
        rows = max(1, len(self._cells) // cols)
        return cols, rows

    def _guides(self):
        if self._show == "none":
            return []
        x0, y0, sc = self._disp()
        v = self._vals
        g = []
        if self._show == "margin":
            g.append(("margin_left", "v", x0 + v["margin_left"] * sc))
            g.append(("margin_right", "v", x0 + (self._ow - v["margin_right"]) * sc))
            g.append(("margin_top", "h", y0 + v["margin_top"] * sc))
            g.append(("margin_bottom", "h", y0 + (self._oh - v["margin_bottom"]) * sc))
            if self._cells:
                cols, rows = self._cols_rows()
                if cols > 1:
                    g.append(("gap", "v", x0 + self._cells[0][2] * sc))
                if rows > 1:
                    g.append(("gap_v", "h", y0 + self._cells[0][3] * sc))
        elif self._show == "crop" and self._cells:
            cx0, cy0, cx1, cy1 = self._cells[0]
            cw = cx1 - cx0; ch = cy1 - cy0
            g.append(("crop_top", "h", y0 + (cy0 + v["crop_top"] / 100.0 * ch) * sc))
            g.append(("crop_bottom", "h", y0 + (cy1 - v["crop_bottom"] / 100.0 * ch) * sc))
            g.append(("crop_left", "v", x0 + (cx0 + v["crop_left"] / 100.0 * cw) * sc))
            g.append(("crop_right", "v", x0 + (cx1 - v["crop_right"] / 100.0 * cw) * sc))
        return g

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#3a3a3a"))
        if self._pm is None:
            return
        x0, y0, sc = self._disp()
        p.drawPixmap(QRectF(x0, y0, self._ow * sc, self._oh * sc).toRect(), self._pm)
        # 260617-6: 크롭 모드 — 잘려나가는 부분(가운데 유지영역 제외)을 흑색 70%로 표시
        if self._show == "crop" and self._cells:
            v = self._vals
            cl = v.get("crop_left", 0) / 100.0; cr = v.get("crop_right", 0) / 100.0
            ct = v.get("crop_top", 0) / 100.0; cb = v.get("crop_bottom", 0) / 100.0
            ov = QColor(0, 0, 0, 178)        # 70% 불투명
            for (ax0, ay0, ax1, ay1) in self._cells:
                cw = ax1 - ax0; ch = ay1 - ay0
                CX0 = x0 + ax0 * sc; CY0 = y0 + ay0 * sc
                CX1 = x0 + ax1 * sc; CY1 = y0 + ay1 * sc
                KX0 = x0 + (ax0 + cl * cw) * sc; KX1 = x0 + (ax1 - cr * cw) * sc
                KY0 = y0 + (ay0 + ct * ch) * sc; KY1 = y0 + (ay1 - cb * ch) * sc
                p.fillRect(QRectF(CX0, CY0, CX1 - CX0, KY0 - CY0).toRect(), ov)  # 상
                p.fillRect(QRectF(CX0, KY1, CX1 - CX0, CY1 - KY1).toRect(), ov)  # 하
                p.fillRect(QRectF(CX0, KY0, KX0 - CX0, KY1 - KY0).toRect(), ov)  # 좌
                p.fillRect(QRectF(KX1, KY0, CX1 - KX1, KY1 - KY0).toRect(), ov)  # 우
        for key, orient, pos in self._guides():
            col = "#ff8c00" if key in _CROP else ("#22aa55" if key in _GAP else "#1e88e5")
            p.setPen(QPen(QColor(col), 2, Qt.PenStyle.DashLine))
            if orient == "v":
                p.drawLine(int(pos), int(y0), int(pos), int(y0 + self._oh * sc))
            else:
                p.drawLine(int(x0), int(pos), int(x0 + self._ow * sc), int(pos))
        p.end()

    def _hit(self, pos):
        best = None; bestd = 8.0
        for key, orient, c in self._guides():
            d = abs((pos.x() if orient == "v" else pos.y()) - c)
            if d < bestd:
                bestd = d; best = (key, orient)
        return best

    def mousePressEvent(self, e):
        self._drag = self._hit(e.position())

    def mouseMoveEvent(self, e):
        if self._drag is None:
            hit = self._hit(e.position())
            self.setCursor(Qt.CursorShape.SizeHorCursor if hit and hit[1] == "v"
                           else Qt.CursorShape.SizeVerCursor if hit
                           else Qt.CursorShape.ArrowCursor)
            return
        key, orient = self._drag
        x0, y0, sc = self._disp()
        if sc <= 0:
            return
        pt = ((e.position().x() - x0) / sc) if orient == "v" else ((e.position().y() - y0) / sc)
        val = self._val_from_pt(key, pt)
        if val is not None:
            self.changed.emit(key, int(round(val)))

    def mouseReleaseEvent(self, e):
        self._drag = None

    def _val_from_pt(self, key, pt):
        ow, oh = self._ow, self._oh
        if key == "margin_left":
            return max(0, min(ow / 2, pt))
        if key == "margin_right":
            return max(0, min(ow / 2, ow - pt))
        if key == "margin_top":
            return max(0, min(oh / 2, pt))
        if key == "margin_bottom":
            return max(0, min(oh / 2, oh - pt))
        if not self._cells:
            return None
        cols, rows = self._cols_rows()
        if key == "gap":
            if cols < 2:
                return None
            content_w = self._cells[cols - 1][2] - self._cells[0][0]
            cw = pt - self._cells[0][0]
            return max(0, min(200, (content_w - cols * cw) / (cols - 1)))
        if key == "gap_v":
            if rows < 2:
                return None
            content_h = self._cells[(rows - 1) * cols][3] - self._cells[0][1]
            ch = pt - self._cells[0][1]
            return max(0, min(200, (content_h - rows * ch) / (rows - 1)))
        cx0, cy0, cx1, cy1 = self._cells[0]
        cw = cx1 - cx0; ch = cy1 - cy0
        if key == "crop_top":
            return max(0, min(45, (pt - cy0) / ch * 100))
        if key == "crop_bottom":
            return max(0, min(45, (cy1 - pt) / ch * 100))
        if key == "crop_left":
            return max(0, min(45, (pt - cx0) / cw * 100))
        if key == "crop_right":
            return max(0, min(45, (cx1 - pt) / cw * 100))
        return None


def _guide_radios(parent, current, on_change):
    """가이드 옵션버튼(여백/크롭/숨김) 행 + 버튼그룹 반환."""
    row = QHBoxLayout()
    row.addWidget(QLabel("가이드:"))
    rbm = QRadioButton("여백"); rbc = QRadioButton("크롭"); rbh = QRadioButton("숨김")
    bg = QButtonGroup(parent)
    for rb, mode in [(rbm, "margin"), (rbc, "crop"), (rbh, "none")]:
        bg.addButton(rb)
        rb.toggled.connect(lambda on, m=mode: on and on_change(m))
        row.addWidget(rb)
    {"margin": rbm, "crop": rbc, "none": rbh}.get(current, rbm).setChecked(True)
    row.addStretch(1)
    return row, bg


class MergePreviewWidget(QWidget):
    """미리보기 + 여백/간격/크롭 조정(스핀박스+드래그+시트 넘김+전체화면). 임베드용."""

    def __init__(self, settings, sample, parent=None):
        super().__init__(parent)
        self._sample = sample
        self._base = merge_twoup_settings(settings)
        self.vals = {k: int(self._base.get(k, 0)) for k in _KEYS}
        self._sheet = 0
        self._total = 1
        self._fs = None

        root = QHBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        nav = QHBoxLayout()
        self.b_prev = QPushButton("◀ 이전"); self.b_prev.clicked.connect(self._prev_sheet)
        self.b_next = QPushButton("다음 ▶"); self.b_next.clicked.connect(self._next_sheet)
        self.lbl_nav = QLabel("1 / 1"); self.lbl_nav.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self.b_prev); nav.addWidget(self.lbl_nav, 1); nav.addWidget(self.b_next)
        left.addLayout(nav)
        self.canvas = _PreviewCanvas()
        self.canvas.changed.connect(self._on_drag)
        left.addWidget(self.canvas, 1)
        b_full = QPushButton("전체 화면으로 보기")
        b_full.clicked.connect(self._open_fullscreen)
        left.addWidget(b_full)
        root.addLayout(left, 1)

        side = QVBoxLayout()
        grow, self._bg = _guide_radios(self, self.canvas._show, self.canvas.set_show)
        side.addLayout(grow)
        self.sp = {}
        gm = QGroupBox("여백 / 간격 (pt)"); fm = QFormLayout(gm)
        for key, lab in [("margin_top", "상단 여백"), ("margin_bottom", "하단 여백"),
                         ("margin_left", "좌측 여백"), ("margin_right", "우측 여백"),
                         ("gap", "가로 간격"), ("gap_v", "세로 간격")]:
            self.sp[key] = self._mk_spin(key, 0, 400, " pt")
            fm.addRow(lab + ":", self.sp[key])
        side.addWidget(gm)
        gc = QGroupBox("원본 크롭 (%)"); fc = QFormLayout(gc)
        for key, lab in [("crop_top", "상단"), ("crop_bottom", "하단"),
                         ("crop_left", "좌측"), ("crop_right", "우측")]:
            self.sp[key] = self._mk_spin(key, 0, 45, " %")
            fc.addRow(lab + ":", self.sp[key])
        side.addWidget(gc)
        hint = QLabel("파란선=여백, 초록선=간격, 주황선=크롭.\n"
                      "드래그/숫자로 조정하고 ◀▶로 페이지를 넘겨 확인하세요.")
        hint.setWordWrap(True); hint.setStyleSheet("color:#888;font-size:11px;")
        side.addWidget(hint)
        side.addStretch(1)
        root.addLayout(side)

        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.setInterval(120); self._timer.timeout.connect(self._recompose)
        self._recompose()

    def _mk_spin(self, key, lo, hi, suf):
        s = QSpinBox(); s.setRange(lo, hi); s.setSuffix(suf); s.setValue(int(self.vals[key]))
        s.setFixedWidth(76)
        s.valueChanged.connect(lambda v, k=key: self._on_spin(k, v))
        return s

    def set_base(self, base):
        self._base = merge_twoup_settings(base)
        for k in _KEYS:
            self._base[k] = self.vals[k]
        self._timer.start()        # 디바운스 — 연속 변경(스타일 적용 등) 시 1회만 렌더

    def set_sample(self, sample):
        self._sample = sample
        self._timer.start()

    def _cur_settings(self):
        s = dict(self._base); s.update(self.vals); return s

    def values(self) -> dict:
        return dict(self.vals)

    def set_values(self, d):
        for k in _KEYS:
            if k in d:
                self.vals[k] = int(d[k])
        self._sync_from_vals()

    def _sync_from_vals(self):
        for k in _KEYS:
            sp = self.sp.get(k)
            if sp is not None:
                sp.blockSignals(True); sp.setValue(int(self.vals[k])); sp.blockSignals(False)
        self.canvas._vals = self.vals
        self._timer.start()

    def _recompose(self):
        try:
            png, ow, oh, cells, total = compose_preview(
                self._sample, self._cur_settings(), self._sheet)
            self._total = max(1, int(total))
            self._sheet = max(0, min(self._total - 1, self._sheet))
            self.canvas.set_image(png, ow, oh, cells, self.vals)
            self.lbl_nav.setText(f"{self._sheet + 1} / {self._total}")
            self.b_prev.setEnabled(self._sheet > 0)
            self.b_next.setEnabled(self._sheet < self._total - 1)
        except Exception:
            pass

    def _prev_sheet(self):
        if self._sheet > 0:
            self._sheet -= 1
            self._recompose()

    def _next_sheet(self):
        if self._sheet < self._total - 1:
            self._sheet += 1
            self._recompose()

    def _on_spin(self, key, val):
        self.vals[key] = int(val)
        self.canvas._vals = self.vals; self.canvas.update()
        self._timer.start()

    def _on_drag(self, key, val):
        self.vals[key] = int(val)
        sp = self.sp.get(key)
        if sp is not None:
            sp.blockSignals(True); sp.setValue(int(val)); sp.blockSignals(False)
        self.canvas.update()
        self._timer.start()

    def _open_fullscreen(self):
        fs = FullscreenPreview(dict(self._base), self.vals, self._sample,
                               self._sheet, self.canvas._show, parent=self.window())
        # 모달 설정창 위에서 보이도록 모달+최상위로
        fs.setWindowModality(Qt.WindowModality.ApplicationModal)
        fs.closed.connect(self._on_fs_closed)
        self._fs = fs
        fs.showFullScreen()
        fs.raise_()
        fs.activateWindow()

    def _on_fs_closed(self, sheet):
        self._sheet = int(sheet)
        self._sync_from_vals()
        self._fs = None


class FullscreenPreview(QWidget):
    """전체화면 미리보기 — 좌/우 이전·다음, ←/→, 우상단 가이드 풀다운+닫기, ESC 닫기."""
    closed = pyqtSignal(int)

    def __init__(self, base, vals, sample, sheet, show, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle("병합 미리보기 — 전체화면")
        self._base = base; self.vals = vals; self._sample = sample
        self._sheet = sheet; self._total = 1
        self.setStyleSheet("background:#202020;")
        self.canvas = _PreviewCanvas()
        self.canvas.set_show(show)
        self.canvas.changed.connect(self._on_drag)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)

        # 좌우 이동 버튼 — 세로가 가로보다 긴(세로 막대) 형태, 글리프 다 보이게
        navcss = ("QPushButton{background:rgba(255,255,255,0.20);color:#fff;border:none;"
                  "border-radius:8px;font-size:26px;}"
                  "QPushButton:hover{background:rgba(255,255,255,0.36);}")
        self.b_prev = QPushButton("◀", self); self.b_prev.setStyleSheet(navcss)
        self.b_prev.setFixedSize(48, 104); self.b_prev.clicked.connect(self._prev)
        self.b_next = QPushButton("▶", self); self.b_next.setStyleSheet(navcss)
        self.b_next.setFixedSize(48, 104); self.b_next.clicked.connect(self._next)
        self.cmb_guide = QComboBox(self)
        self.cmb_guide.addItem("여백", "margin"); self.cmb_guide.addItem("크롭", "crop")
        self.cmb_guide.addItem("숨김", "none")
        self.cmb_guide.setCurrentIndex({"margin": 0, "crop": 1, "none": 2}.get(show, 0))
        self.cmb_guide.setStyleSheet(
            "QComboBox{background:#ffffff;color:#222;padding:4px 10px;border:1px solid #888;"
            "border-radius:4px;min-height:24px;}"
            "QComboBox QAbstractItemView{background:#ffffff;color:#222;"
            "selection-background-color:#1e88e5;selection-color:#fff;}")
        self.cmb_guide.currentIndexChanged.connect(
            lambda: self.canvas.set_show(self.cmb_guide.currentData()))
        self.lbl = QLabel("", self); self.lbl.setStyleSheet("color:#fff;font-size:15px;")
        self.b_close = QPushButton("✕", self)
        self.b_close.setStyleSheet(navcss + "QPushButton{font-size:20px;}")
        self.b_close.setFixedSize(40, 32)
        self.b_close.clicked.connect(self.close)

        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.setInterval(120); self._timer.timeout.connect(self._recompose)
        self._recompose()

    def resizeEvent(self, e):
        w, h = self.width(), self.height()
        self.b_prev.move(16, h // 2 - self.b_prev.height() // 2)
        self.b_next.move(w - self.b_next.width() - 16, h // 2 - self.b_next.height() // 2)
        self.cmb_guide.adjustSize()
        self.b_close.move(w - self.b_close.width() - 16, 16)
        self.cmb_guide.move(w - self.b_close.width() - self.cmb_guide.width() - 28, 18)
        self.lbl.adjustSize(); self.lbl.move(20, 18)
        super().resizeEvent(e)

    def _cur_settings(self):
        s = dict(self._base); s.update(self.vals); return s

    def _recompose(self):
        try:
            png, ow, oh, cells, total = compose_preview(
                self._sample, self._cur_settings(), self._sheet)
            self._total = max(1, int(total))
            self._sheet = max(0, min(self._total - 1, self._sheet))
            self.canvas.set_image(png, ow, oh, cells, self.vals)
            self.lbl.setText(f"{self._sheet + 1} / {self._total}")
            self.b_prev.setVisible(self._sheet > 0)
            self.b_next.setVisible(self._sheet < self._total - 1)
            self.lbl.adjustSize()
        except Exception:
            pass

    def _prev(self):
        if self._sheet > 0:
            self._sheet -= 1; self._recompose()

    def _next(self):
        if self._sheet < self._total - 1:
            self._sheet += 1; self._recompose()

    def _on_drag(self, key, val):
        self.vals[key] = int(val)
        self.canvas.update()
        self._timer.start()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close(); return
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self._prev(); return
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
            self._next(); return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        try:
            self.closed.emit(self._sheet)
        except Exception:
            pass
        super().closeEvent(e)


class MergePreviewDialog(QDialog):
    """단독 미리보기 다이얼로그(MergePreviewWidget 래퍼)."""

    def __init__(self, settings, sample, parent=None):
        super().__init__(parent)
        self.setWindowTitle("병합 미리보기 / 여백·간격·크롭 조정")
        self.resize(960, 660)
        v = QVBoxLayout(self)
        self.widget = MergePreviewWidget(settings, sample, self)
        v.addWidget(self.widget, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def get_values(self) -> dict:
        return self.widget.values()
