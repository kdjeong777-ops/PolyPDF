# -*- coding: utf-8 -*-
"""변환·다듬기 창 — 그림으로 저장(바탕 지우기·흑백·색 바꾸기·가리기·밝기 대비·스캔처럼·여백) + (사진이면) 문서로.

사진 보기 SOT §4.46(261112-15) · 스크린샷 SOT §4.1(261112-16). 계산은 `viewer.image_tune` 한 곳, 미리보기·저장·복사는 모두 배경
(`ImageTuneWorker`, 응답성 SOT §4.4) — 설정을 바꾸면 `PREVIEW_DELAY_MS` 뒤 한 번, 늦게 온 옛 결과는 세대 토큰으로 버린다.
"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QRadioButton, QScrollArea,
                             QSlider, QToolButton, QVBoxLayout, QWidget)

from viewer import image_tune as it
from viewer.i18n import tr


PREVIEW_W = 560          # 처음 열 때 미리보기 폭(화면이 좁으면 줄인다)
PREVIEW_MIN = 240        # 미리보기 최소 폭


class ImageTuneWorker(QObject):
    """함수 하나를 배경에서 — done(토큰, 결과, 오류 글)."""
    done = pyqtSignal(int, object, str)
    finished = pyqtSignal()

    def __init__(self, token: int, fn):
        super().__init__()
        self._token, self._fn = token, fn

    def run(self):
        try:
            res, err = self._fn(), ""
        except Exception as e:                       # noqa: BLE001
            res, err = None, str(e) or e.__class__.__name__
        self.done.emit(self._token, res, err)
        self.finished.emit()


def pil_to_qimage(im) -> QImage:
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    return QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888).copy()


class _Preview(QWidget):
    """체크무늬 바탕 위에 그림(맞춤). mode: '' · 'pick'(누른 자리) · 'rect'(네모 끌기). 좌표는 그림 비율 0~1."""
    clicked = pyqtSignal(float, float)
    rectDrawn = pyqtSignal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self._img = QImage()
        self.mode = ""
        self._drag = None
        self._cur = None

    def set_image(self, img: QImage):
        self._img = img
        self.update()

    def _rect(self) -> QRectF:
        if self._img.isNull():
            return QRectF()
        W, H = self.width() - 8, self.height() - 8
        s = min(W / self._img.width(), H / self._img.height())
        w, h = self._img.width() * s, self._img.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _norm(self, pos):
        r = self._rect()
        if r.isEmpty():
            return None
        x, y = (pos.x() - r.x()) / r.width(), (pos.y() - r.y()) / r.height()
        return (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self._rect()
        if not r.isEmpty():
            c1, c2, n = QColor(255, 255, 255), QColor(214, 214, 214), 10
            p.save()
            p.setClipRect(r)
            y = r.top()
            row = 0
            while y < r.bottom():
                x = r.left() + (n if row % 2 else 0)
                p.fillRect(QRectF(r.left(), y, r.width(), n), c1)
                while x < r.right():
                    p.fillRect(QRectF(x, y, n, n), c2)
                    x += 2 * n
                y += n
                row += 1
            p.restore()
            p.drawImage(r, self._img)
        if self._drag is not None and self._cur is not None:
            p.setPen(QPen(QColor(230, 80, 0), 2, Qt.PenStyle.DashLine))
            p.drawRect(QRectF(QPointF(*self._drag), QPointF(*self._cur)).normalized())
        p.end()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self.mode:
            return
        if self.mode == "pick":
            n = self._norm(e.position())
            if n:
                self.clicked.emit(*n)
        elif self.mode == "rect":
            self._drag = (e.position().x(), e.position().y())
            self._cur = self._drag

    def mouseMoveEvent(self, e):
        self.setCursor(Qt.CursorShape.CrossCursor if self.mode else Qt.CursorShape.ArrowCursor)
        if self._drag is not None:
            self._cur = (e.position().x(), e.position().y())
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is None:
            return
        a = self._norm(QPointF(*self._drag))
        b = self._norm(e.position())
        self._drag = self._cur = None
        self.update()
        if a and b and abs(a[0] - b[0]) > 0.005 and abs(a[1] - b[1]) > 0.005:
            self.rectDrawn.emit(a[0], a[1], b[0], b[1])


class ImageTuneDialog(QDialog):
    """paths: 그림 파일들. kind 'photo'(사진 모드 '변환' — 문서로 묶음·원본 옆 저장) · 'shot'(스크린샷 '다듬기' — 다른 이름으로 저장).
    rots·crops: 사진의 보기 회전·보기 크롭. on_saved(src, dst): 새 파일 뒤(책갈피창 줄). doc_fn(fmt): '문서로' 단추.
    copy_fn(qimage, png_bytes): 클립보드(없으면 clipboard_util). can_save=False 면 저장 단추는 알림만(zip·휴대 장치)."""

    def __init__(self, parent, paths, *, kind: str = "photo", rots=None, crops=None, on_saved=None, doc_fn=None,
                 copy_fn=None, can_save: bool = True, start_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("변환") if kind == "photo" else tr("다듬기"))
        self._paths = [str(p) for p in paths]
        self._kind = kind
        self._rots, self._crops = dict(rots or {}), dict(crops or {})
        self._on_saved, self._doc_fn, self._copy_fn = on_saved, doc_fn, copy_fn
        self._can_save = can_save
        self._start_dir = start_dir
        self._p = it.default_params()
        self._masks = {}                         # 경로 → 가림 네모들(사진마다)
        self._small = {}                         # 경로 → 줄인 원본(PIL)
        self._idx = 0
        self._tok = 0
        self._keep = []
        self._busy = False
        self.saved = []                          # [(원본, 새 파일)]
        self._last_preview = None                # 마지막 미리보기 결과(PIL) — 검사
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(it.PREVIEW_DELAY_MS)
        self._timer.timeout.connect(self._run_preview)
        self._build()
        self._fit_size()
        self._show_path()

    # ── 화면 ────────────────────────────────────────
    def _build(self):
        outer = QVBoxLayout(self)
        root = QHBoxLayout()
        outer.addLayout(root, 1)
        left = QVBoxLayout()
        nav = QHBoxLayout()
        self.btn_prev, self.btn_next = QToolButton(), QToolButton()
        self.btn_prev.setText("❮"); self.btn_next.setText("❯")
        self.btn_prev.clicked.connect(lambda: self._step(-1)); self.btn_next.clicked.connect(lambda: self._step(1))
        self.lb_name = QLabel()
        nav.addWidget(self.btn_prev); nav.addWidget(self.lb_name, 1); nav.addWidget(self.btn_next)
        left.addLayout(nav)
        self.preview = _Preview()
        self.preview.clicked.connect(self._on_pick)
        self.preview.rectDrawn.connect(self._on_rect)
        left.addWidget(self.preview, 1)
        self.lb_hint = QLabel()
        self.lb_hint.setWordWrap(True)
        left.addWidget(self.lb_hint)
        root.addLayout(left, 1)                  # 남는 폭은 미리보기에(오른쪽 칸은 제 폭 — 디자인 SOT §2.22)

        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        g = QGroupBox(tr("그림으로 저장"))
        f = QFormLayout(g)
        self.cmb_fmt = QComboBox()
        for key, name, _e, _t in it.FORMATS:
            self.cmb_fmt.addItem(name, key)
        first = self._paths[0] if self._paths else ""
        self.cmb_fmt.setCurrentIndex(max(0, self.cmb_fmt.findData(it.fmt_of_path(first) if self._kind == "photo" else "png")))
        self.cmb_fmt.currentIndexChanged.connect(self._changed)
        f.addRow(tr("형식"), self.cmb_fmt)

        # 바탕 지우기
        bgw = QWidget(); bv = QVBoxLayout(bgw); bv.setContentsMargins(0, 0, 0, 0)
        self.rb_none, self.rb_thr, self.rb_col = QRadioButton(tr("없음")), QRadioButton(tr("밝은 바탕(문턱)")), QRadioButton(tr("누른 색"))
        self._bg_grp = QButtonGroup(self)
        for i, rb in enumerate((self.rb_none, self.rb_thr, self.rb_col)):
            self._bg_grp.addButton(rb, i)
        self.rb_none.setChecked(True)
        rr = QHBoxLayout(); rr.addWidget(self.rb_none); rr.addWidget(self.rb_thr); rr.addWidget(self.rb_col); rr.addStretch(1)
        bv.addLayout(rr)
        tr_row = QHBoxLayout()
        self.cb_auto = QCheckBox(tr("자동")); self.cb_auto.setChecked(True)
        self.sl_thr = QSlider(Qt.Orientation.Horizontal); self.sl_thr.setRange(0, 255); self.sl_thr.setValue(200); self.sl_thr.setEnabled(False)
        tr_row.addWidget(self.cb_auto); tr_row.addWidget(self.sl_thr, 1)
        bv.addLayout(tr_row)
        cr = QHBoxLayout()
        self.btn_bg_pick = QPushButton(tr("바탕 누르기")); self.btn_bg_pick.setCheckable(True)
        self.btn_bg_pick.setToolTip(tr("누른 뒤 미리보기에서 지울 바탕을 누르세요 — 여러 번 누르면 더해집니다"))
        self.lb_bg = QLabel(); self.btn_bg_clear = QPushButton(tr("지우기"))
        cr.addWidget(self.btn_bg_pick); cr.addWidget(self.lb_bg, 1); cr.addWidget(self.btn_bg_clear)
        bv.addLayout(cr)
        tol = QHBoxLayout(); tol.addWidget(QLabel(tr("허용 범위")))
        self.sl_bg_tol = QSlider(Qt.Orientation.Horizontal); self.sl_bg_tol.setRange(0, 200); self.sl_bg_tol.setValue(it.TOL_DEFAULT)
        tol.addWidget(self.sl_bg_tol, 1)
        bv.addLayout(tol)
        self.cb_trim = QCheckBox(tr("빈 여백 자르기"))
        bv.addWidget(self.cb_trim)
        f.addRow(tr("바탕 지우기"), bgw)

        self.cmb_gray = QComboBox()
        for k, t in (("none", tr("없음")), ("gray", tr("회색조")), ("bw", tr("흑백 (두 색)"))):
            self.cmb_gray.addItem(t, k)
        f.addRow(tr("흑백"), self.cmb_gray)

        self.cmb_ink = QComboBox()
        for k, t in (("", tr("그대로")), ("black", tr("검정")), ("blue", tr("파랑")), ("red", tr("빨강")), ("pick", tr("고른 색…"))):
            self.cmb_ink.addItem(t, k)
        self._ink_hex = None
        f.addRow(tr("글씨·선 색"), self.cmb_ink)

        sw = QWidget(); sl = QVBoxLayout(sw); sl.setContentsMargins(0, 0, 0, 0)
        s1 = QHBoxLayout()
        self.btn_sw_pick = QPushButton(tr("바꿀 색 누르기")); self.btn_sw_pick.setCheckable(True)
        self.lb_sw_from = QLabel(); self.lb_sw_from.setFixedSize(28, 18)
        self.btn_sw_to = QPushButton(tr("새 색"))
        self.lb_sw_to = QLabel(); self.lb_sw_to.setFixedSize(28, 18)
        self.btn_sw_clear = QPushButton(tr("없애기"))
        for w_ in (self.btn_sw_pick, self.lb_sw_from, QLabel("→"), self.btn_sw_to, self.lb_sw_to):
            s1.addWidget(w_)
        s1.addStretch(1); s1.addWidget(self.btn_sw_clear)
        sl.addLayout(s1)
        s2 = QHBoxLayout(); s2.addWidget(QLabel(tr("허용 범위")))
        self.sl_sw_tol = QSlider(Qt.Orientation.Horizontal); self.sl_sw_tol.setRange(0, 200); self.sl_sw_tol.setValue(it.TOL_DEFAULT)
        s2.addWidget(self.sl_sw_tol, 1)
        sl.addLayout(s2)
        f.addRow(tr("색 바꾸기"), sw)

        tw = QWidget(); tv = QVBoxLayout(tw); tv.setContentsMargins(0, 0, 0, 0)
        t1 = QHBoxLayout()
        self.cb_scan = QCheckBox(tr("문서 스캔처럼")); self.cb_level = QCheckBox(tr("밝기·대비 자동"))
        t1.addWidget(self.cb_scan); t1.addWidget(self.cb_level); t1.addStretch(1)
        tv.addLayout(t1)
        self.sl_bri, self.sl_con = QSlider(Qt.Orientation.Horizontal), QSlider(Qt.Orientation.Horizontal)
        for lab, s in ((tr("밝기"), self.sl_bri), (tr("대비"), self.sl_con)):
            s.setRange(-100, 100); s.setValue(0)
            row = QHBoxLayout(); row.addWidget(QLabel(lab)); row.addWidget(s, 1)
            tv.addLayout(row)
        f.addRow(tr("밝기·대비"), tw)

        mw_ = QWidget(); mh = QHBoxLayout(mw_); mh.setContentsMargins(0, 0, 0, 0)
        self.btn_mask = QPushButton(tr("가릴 곳 끌기")); self.btn_mask.setCheckable(True)
        self.cmb_mask = QComboBox(); self.cmb_mask.addItem(tr("모자이크"), "mosaic"); self.cmb_mask.addItem(tr("검정"), "black")
        self.btn_mask_clear = QPushButton(tr("가림 지우기"))
        mh.addWidget(self.btn_mask); mh.addWidget(self.cmb_mask); mh.addWidget(self.btn_mask_clear); mh.addStretch(1)
        f.addRow(tr("가리기"), mw_)
        sv.addWidget(g)

        self.btn_save = QPushButton(tr("새 파일로 저장"))
        self.btn_copy = QPushButton(tr("클립보드로 복사"))
        self.btn_save.clicked.connect(self._save)
        self.btn_copy.clicked.connect(self._copy)

        self.doc_buttons = {}
        if self._kind == "photo" and self._doc_fn is not None:
            gd = QGroupBox(tr("문서로 (OCR 글)"))
            dh = QHBoxLayout(gd)
            b = QPushButton(tr("Word·HWPX·텍스트로"))
            b.setToolTip(tr("사진의 OCR 글로 문서를 만듭니다 — 형식은 다음 창에서 고릅니다"))
            b.clicked.connect(lambda _=False: self._doc(None))
            dh.addWidget(b)
            self.doc_buttons["doc"] = b
            dh.addStretch(1)
            sv.addWidget(gd)
        sv.addStretch(1)
        self.lb_status = QLabel()
        self.lb_status.setWordWrap(True)
        sv.addWidget(self.lb_status)
        self.btn_close = QPushButton(tr("닫기"))
        self.btn_close.clicked.connect(self.reject)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(side); sc.setFrameShape(QScrollArea.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # 가로 스크롤 금지 — 칸 폭을 내용에 맞춘다(261112-15 덧붙임)
        root.addWidget(sc, 0)
        self._side, self._sc = side, sc
        # 아래 단추 줄은 스크롤 칸 **밖** — 창이 낮아 오른쪽 칸이 세로로 넘쳐도 [저장]·[복사]·[닫기] 는 늘 보인다(디자인 SOT §2.22)
        bar = QHBoxLayout()
        bar.addWidget(self.btn_save); bar.addWidget(self.btn_copy); bar.addStretch(1); bar.addWidget(self.btn_close)
        outer.addLayout(bar)
        self._bar = bar

        for w_ in (self.cb_auto, self.cb_trim, self.cb_scan, self.cb_level):
            w_.toggled.connect(self._changed)
        self._bg_grp.idToggled.connect(lambda *_: self._changed())
        for s in (self.sl_thr, self.sl_bg_tol, self.sl_sw_tol, self.sl_bri, self.sl_con):
            s.valueChanged.connect(self._changed)
        self.cmb_gray.currentIndexChanged.connect(self._changed)
        self.cmb_mask.currentIndexChanged.connect(self._changed)
        self.cmb_ink.activated.connect(self._ink_chosen)
        self.btn_bg_clear.clicked.connect(self._bg_clear)
        self.btn_sw_to.clicked.connect(self._swap_to)
        self.btn_sw_clear.clicked.connect(self._swap_clear)
        self.btn_mask_clear.clicked.connect(self._mask_clear)
        for b, m in ((self.btn_bg_pick, "bg"), (self.btn_sw_pick, "swap"), (self.btn_mask, "mask")):
            b.toggled.connect(lambda on, mm=m: self._arm(mm, on))

    def _fit_size(self):
        """오른쪽 칸은 **제 폭(sizeHint) 그대로** — 가로 스크롤 없이 [닫기]까지 보이게. 창은 미리보기 `PREVIEW_W` 를 더한 크기,
        화면(사용 가능 영역)보다 크면 **미리보기부터** 줄인다(최소 `PREVIEW_MIN`). 높이는 오른쪽 칸 높이(넘치면 세로 스크롤만).
        디자인 SOT §2.22(261112-15 덧붙임 — 100% 배율에서 오른쪽 칸이 잘려 가로 막대가 생기고 [닫기]가 반쯤 가려졌다)."""
        from PyQt6.QtWidgets import QApplication
        side, sc = self._side, self._sc
        side.adjustSize()
        hint = side.sizeHint()
        bar = sc.verticalScrollBar().sizeHint().width()
        side_w = hint.width() + bar + 2 * sc.frameWidth() + 2
        sc.setMinimumWidth(side_w)
        lay = self.layout()
        m = lay.contentsMargins()
        extra_w = m.left() + m.right() + self._root_spacing()
        scr = self.screen() or QApplication.primaryScreen()
        avail = scr.availableGeometry() if scr is not None else None
        max_w = int(avail.width() * 0.95) if avail is not None else 10 ** 6
        max_h = int(avail.height() * 0.9) if avail is not None else 10 ** 6
        pw = max(PREVIEW_MIN, min(PREVIEW_W, max_w - side_w - extra_w))
        self.preview.setMinimumSize(min(pw, 360), 240)
        w = min(max_w, side_w + extra_w + pw)
        bar_h = self._bar.sizeHint().height() + lay.spacing()
        h = min(max_h, max(hint.height() + bar_h + m.top() + m.bottom(), 560))
        self.resize(w, h)

    def _root_spacing(self) -> int:
        lay = self.layout().itemAt(0).layout()
        return max(0, lay.spacing()) if lay is not None else 6

    # ── 설정 ────────────────────────────────────────
    def params(self) -> dict:
        p = dict(self._p)
        p["masks"] = list(self._masks.get(self._cur_path(), []))
        return p

    def _cur_path(self) -> str:
        return self._paths[self._idx] if self._paths else ""

    def _changed(self, *_):
        p = self._p
        p["bg"] = ("none", "threshold", "color")[max(0, self._bg_grp.checkedId())]
        self.sl_thr.setEnabled(p["bg"] == "threshold" and not self.cb_auto.isChecked())
        p["threshold"] = None if self.cb_auto.isChecked() else int(self.sl_thr.value())
        p["bg_tol"] = int(self.sl_bg_tol.value())
        p["trim"] = self.cb_trim.isChecked()
        p["gray"] = self.cmb_gray.currentData()
        p["swap_tol"] = int(self.sl_sw_tol.value())
        p["scan"] = self.cb_scan.isChecked()
        p["auto_level"] = self.cb_level.isChecked()
        p["brightness"], p["contrast"] = int(self.sl_bri.value()), int(self.sl_con.value())
        p["mask_mode"] = self.cmb_mask.currentData()
        alpha = it.makes_alpha(p)
        self.cb_trim.setEnabled(p["bg"] != "none")
        # 투명이면 PNG·WebP 만(SOT §4.46 '형식')
        m = self.cmb_fmt.model()
        ji = self.cmb_fmt.findData("jpg")
        item = m.item(ji) if hasattr(m, "item") else None
        if item is not None:
            item.setEnabled(not alpha)
            item.setToolTip(tr("투명을 담지 못합니다") if alpha else "")
        if alpha and self.cmb_fmt.currentData() == "jpg":
            self.cmb_fmt.blockSignals(True)
            self.cmb_fmt.setCurrentIndex(self.cmb_fmt.findData("png"))
            self.cmb_fmt.blockSignals(False)
            self.lb_status.setText(tr("바탕을 지우면 투명이 남아 PNG 로 저장합니다(JPEG 은 투명을 담지 못합니다)."))
        self.lb_bg.setText(tr("{n}가지 색").format(n=len(p["bg_colors"])) if p["bg_colors"] else "")
        self._swatch(self.lb_sw_from, p["swap_from"]); self._swatch(self.lb_sw_to, p["swap_to"])
        self._timer.start()

    @staticmethod
    def _swatch(lab, hexcol):
        lab.setStyleSheet("background:%s;border:1px solid #888;" % hexcol if hexcol else "border:1px dashed #888;")

    def _ink_chosen(self, _i=0):
        k = self.cmb_ink.currentData()
        if k == "pick":
            c = QColorDialog.getColor(QColor(self._ink_hex or "#1030a0"), self, tr("글씨·선 색"))
            if c.isValid():
                self._ink_hex = c.name()
            if not self._ink_hex:
                self.cmb_ink.setCurrentIndex(0)
                k = ""
            self._p["ink"] = self._ink_hex if k == "pick" else None
        else:
            self._p["ink"] = k or None
        self._changed()

    def _arm(self, mode, on):
        for b, m in ((self.btn_bg_pick, "bg"), (self.btn_sw_pick, "swap"), (self.btn_mask, "mask")):
            if m != mode and on and b.isChecked():
                b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        self._arm_mode = mode if on else ""
        self.preview.mode = ("rect" if mode == "mask" else "pick") if on else ""
        hints = {"bg": tr("미리보기에서 지울 바탕을 누르세요."), "swap": tr("미리보기에서 바꿀 색을 누르세요."),
                 "mask": tr("미리보기에서 가릴 곳을 끌어 네모로 고르세요.")}
        self.lb_hint.setText(hints.get(mode, "") if on else "")

    def _on_pick(self, x, y):
        small = self._small.get(self._cur_path())
        mode = getattr(self, "_arm_mode", "")
        if small is None or mode not in ("bg", "swap"):
            return
        if mode == "bg":
            col = it.pick(small, self.params(), x, y, it.ST_BG)
            if col not in self._p["bg_colors"]:
                self._p["bg_colors"] = list(self._p["bg_colors"]) + [col]
            self.rb_col.setChecked(True)
        else:
            self._p["swap_from"] = it.pick(small, self.params(), x, y, it.ST_SWAP)
            if not self._p["swap_to"]:
                self._swap_to()
        self._changed()

    def _on_rect(self, x0, y0, x1, y1):
        self._masks.setdefault(self._cur_path(), []).append((x0, y0, x1, y1))
        self._changed()

    def _bg_clear(self):
        self._p["bg_colors"] = []
        self._changed()

    def _swap_to(self):
        c = QColorDialog.getColor(QColor(self._p["swap_to"] or "#ffffff"), self, tr("새 색"))
        if c.isValid():
            self._p["swap_to"] = c.name()
        self._changed()

    def _swap_clear(self):
        self._p["swap_from"] = self._p["swap_to"] = None
        self._changed()

    def _mask_clear(self):
        self._masks.pop(self._cur_path(), None)
        self._changed()

    def set_swap(self, src, dst):
        """검사·다른 길에서 색 바꾸기를 정한다."""
        self._p["swap_from"], self._p["swap_to"] = src, dst
        self._changed()

    # ── 미리보기 ────────────────────────────────────
    def _step(self, d):
        if not self._paths:
            return
        self._idx = (self._idx + d) % len(self._paths)
        self._show_path()

    def _show_path(self):
        n = len(self._paths)
        self.btn_prev.setVisible(n > 1); self.btn_next.setVisible(n > 1)
        path = self._cur_path()
        self.lb_name.setText(("%d/%d  " % (self._idx + 1, n) if n > 1 else "") + Path(path).name)
        if path and path not in self._small:
            rot, crop = self._rots.get(path, 0), self._crops.get(path)
            self._start(lambda p=path: it.preview_of(it.load_visible(p, rot, crop)), self._small_ready)
        else:
            self._run_preview()

    def _small_ready(self, res, err):
        if res is not None:
            self._small[self._cur_path()] = res
            self._run_preview()
        else:
            self.lb_status.setText(tr("그림을 열 수 없습니다.") + (" " + err if err else ""))

    def _run_preview(self):
        small = self._small.get(self._cur_path())
        if small is None:
            return
        p = self.params()
        self._start(lambda: it.apply(small, p), self._preview_ready)

    def _preview_ready(self, res, err):
        if res is None:
            self.lb_status.setText(err)
            return
        self._last_preview = res
        self.preview.set_image(pil_to_qimage(res))

    def _start(self, fn, cb):
        from viewer.workers import run_in_thread
        self._tok += 1
        tok = self._tok
        w = ImageTuneWorker(tok, fn)
        w.done.connect(lambda t, r, e, c=cb: c(r, e) if t == self._tok else None)
        run_in_thread(w, self._keep)

    def _start_job(self, fn, cb):
        """저장·복사 — 미리보기 토큰과 따로(미리보기가 새로 돌아도 버리지 않는다)."""
        from viewer.workers import run_in_thread
        w = ImageTuneWorker(-1, fn)
        w.done.connect(lambda _t, r, e: cb(r, e))
        run_in_thread(w, self._keep)

    def busy(self) -> bool:
        """배경 일(미리보기·저장·복사)이 남았나 — 검사가 기다릴 때 본다."""
        return bool(self._keep) or self._timer.isActive()

    # ── 저장·복사 ───────────────────────────────────
    def _full(self, path, p):
        im = it.apply(it.load_visible(path, self._rots.get(path, 0), self._crops.get(path)), p)
        if it.makes_alpha(p) and not it.has_content(im):
            raise ValueError(tr("남은 그림이 없습니다 — 바탕 지우기 문턱(허용 범위)을 낮추세요."))
        return im

    def _targets(self, fmt):
        """[(원본, 새 경로)] — 사진은 원본 옆 '<이름>_변환', 스크린샷은 다른 이름으로 저장 창(여럿이면 폴더)."""
        from viewer.pathutil import unique_path
        ext = it.ext_of(fmt)
        if self._kind == "photo":
            return [(p, str(unique_path(Path(p).with_name(Path(p).stem + "_" + tr("변환") + ext)))) for p in self._paths]
        if len(self._paths) == 1:
            p = self._paths[0]
            flt = {"png": "PNG (*.png)", "webp": "WebP (*.webp)", "jpg": "JPEG (*.jpg)"}[fmt]
            dst, _ = QFileDialog.getSaveFileName(self, tr("사진으로 저장"), os.path.join(self._start_dir or "", Path(p).stem + ext), flt)
            if not dst:
                return []
            if not dst.lower().endswith(ext) and not (fmt == "jpg" and dst.lower().endswith(".jpeg")):
                dst += ext
            return [(p, dst)]
        d = QFileDialog.getExistingDirectory(self, tr("사진으로 저장"), self._start_dir or "")
        if not d:
            return []
        return [(p, str(unique_path(Path(d) / (Path(p).stem + ext)))) for p in self._paths]

    def _save(self):
        if self._busy:
            return
        if not self._can_save:
            QMessageBox.information(self, self.windowTitle(), tr("zip·휴대 장치 사진은 'PC 로 복사' 한 뒤 저장하세요 — 클립보드로 복사는 됩니다."))
            return
        fmt = self.cmb_fmt.currentData()
        pairs = self._targets(fmt)
        if not pairs:
            return
        masks = dict(self._masks)
        base = dict(self._p)

        def job():
            out, bad = [], []
            for src, dst in pairs:
                p = dict(base, masks=list(masks.get(src, [])))
                try:
                    data = it.encode(self._full(src, p), fmt)
                    tmp = dst + ".polypix-tmp"
                    with open(tmp, "wb") as fh:
                        fh.write(data)
                    os.replace(tmp, dst)
                    out.append((src, dst))
                except Exception as e:               # noqa: BLE001
                    bad.append((src, str(e)))
            return out, bad
        self._set_busy(True, tr("저장하는 중…"))
        self._start_job(job, self._saved)

    def _saved(self, res, err):
        self._set_busy(False)
        out, bad = res if res else ([], [(self._cur_path(), err)])
        self.saved += out
        for s, d in out:
            if self._on_saved:
                try:
                    self._on_saved(s, d)
                except Exception:
                    pass
        msg = tr("새 파일 {n}장을 만들었습니다.").format(n=len(out)) if out else ""
        if bad:
            msg = (msg + " " if msg else "") + bad[0][1]
        self.lb_status.setText(msg)
        if self._start_dir is not None and out and self._kind == "shot":
            self._start_dir = str(Path(out[-1][1]).parent)

    def _copy(self):
        if self._busy or not self._paths:
            return
        path, p = self._cur_path(), self.params()
        self._set_busy(True, tr("복사하는 중…"))
        self._start_job(lambda: it.encode(self._full(path, p), "png"), self._copied)

    def _copied(self, png, err):
        self._set_busy(False)
        if not png:
            self.lb_status.setText(err)
            return
        img = QImage.fromData(png, "PNG")

        def done(ok):
            self.lb_status.setText(tr("클립보드에 복사했습니다(투명 PNG 포함).") if ok else tr("클립보드에 복사하지 못했습니다."))
        if self._copy_fn is not None:
            self._copy_fn(img, png, done)
        else:
            from viewer import clipboard_util
            clipboard_util.set_image(img, done, png=png)

    def _set_busy(self, on, text=""):
        self._busy = on
        self.btn_save.setEnabled(not on)
        self.btn_copy.setEnabled(not on)
        if text or not on:
            self.lb_status.setText(text)

    def _doc(self, key):
        fn = self._doc_fn
        self.accept()
        if fn is not None:
            QTimer.singleShot(0, fn)
