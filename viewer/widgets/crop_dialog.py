# -*- coding: utf-8 -*-
"""쪽 크롭 창 (261010-7, 마스터 §4.7.15).

왼쪽 = 쪽 썸네일(적용할 쪽 고르기, 이미 잘린 쪽은 ✂), 가운데 = 미리보기(쪽 전체 + 잘릴 곳 어둡게, 네 변 끌기,
겹쳐 보기), 오른쪽 = 적용 범위·스타일(가로긴/세로긴 자동 적용, 사용자 추가)·여백 %(지금 쪽 mm)·흰 여백 자동 감지·
홀짝 좌우 대칭. 계산은 `viewer.page_crop` — 이 창은 **값만 고르고** 저장은 호출부가 배경에서 한다.

미리보기용 문서는 **이 창만의 사본 핸들**이다 — 쪽 전체를 그리려고 CropBox 를 넓히지만 저장하지 않는다.
"""
from __future__ import annotations

import fitz
from PyQt6.QtCore import Qt, QTimer, QRectF, QSize, QItemSelectionModel, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QColor, QPen, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QFormLayout, QGridLayout, QGroupBox, QRadioButton, QButtonGroup,
    QLineEdit, QLabel, QCheckBox, QComboBox, QPushButton, QDoubleSpinBox, QSpinBox, QListWidget,
    QListWidgetItem, QListView, QAbstractItemView, QWidget, QDialogButtonBox, QInputDialog, QMessageBox,
    QScrollArea, QFrame,
)

from viewer import page_crop as pc
from viewer.i18n import tr

PT_PER_MM = 72.0 / 25.4
OVERLAY_MAX = 40
THUMB_W = 96


def style_label(st: dict) -> str:
    if st["id"] == pc.PORTRAIT:
        return tr("세로긴 쪽")
    if st["id"] == pc.LANDSCAPE:
        return tr("가로긴 쪽")
    return st.get("name") or st["id"]


def _qimage(pix) -> QImage:
    fmt = QImage.Format.Format_RGB888 if pix.n == 3 else QImage.Format.Format_Grayscale8
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


class CropCanvas(QWidget):
    """쪽 전체 그림 위에 잘릴 곳을 어둡게. 편집 가능하면 네 변을 끌어 여백(%)을 바꾼다."""
    marginsDragged = pyqtSignal(object)        # [위,아래,왼,오른] %

    GRAB = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 420)
        self.setMouseTracking(True)
        self._img = None
        self._m = [0.0, 0.0, 0.0, 0.0]
        self._editable = True
        self._drag = None
        self._note = ""

    def set_image(self, img, note=""):
        self._img = img
        self._note = note
        self.update()

    def set_margins(self, m, editable=True):
        self._m = list(m) if m is not None else [0.0, 0.0, 0.0, 0.0]
        self._editable = bool(editable) and m is not None
        self.update()

    def _img_rect(self) -> QRectF:
        if self._img is None or self._img.isNull():
            return QRectF()
        W, H = self.width() - 16, self.height() - 16
        s = min(W / self._img.width(), H / self._img.height())
        w, h = self._img.width() * s, self._img.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _crop_rect(self, r: QRectF) -> QRectF:
        t, b, l, rr = (v / 100.0 for v in self._m)
        return QRectF(r.left() + l * r.width(), r.top() + t * r.height(),
                      r.width() * (1 - l - rr), r.height() * (1 - t - b))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().window())
        r = self._img_rect()
        if r.isNull():
            p.end(); return
        p.drawImage(r, self._img)
        c = self._crop_rect(r)
        shade = QColor(0, 0, 0, 110)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), c.top() - r.top()), shade)
        p.fillRect(QRectF(r.left(), c.bottom(), r.width(), r.bottom() - c.bottom()), shade)
        p.fillRect(QRectF(r.left(), c.top(), c.left() - r.left(), c.height()), shade)
        p.fillRect(QRectF(c.right(), c.top(), r.right() - c.right(), c.height()), shade)
        pen = QPen(QColor("#e53935"), 2 if self._editable else 1)
        if not self._editable:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(c)
        if self._note:
            p.setPen(QColor("#e53935"))
            p.drawText(QRectF(r.left(), r.bottom() - 22, r.width(), 20), Qt.AlignmentFlag.AlignCenter, self._note)
        p.end()

    def _hit(self, pos):
        r = self._img_rect()
        if r.isNull() or not self._editable:
            return None
        c = self._crop_rect(r)
        x, y, g = pos.x(), pos.y(), self.GRAB
        inside_v = c.top() - g <= y <= c.bottom() + g
        inside_h = c.left() - g <= x <= c.right() + g
        if inside_h and abs(y - c.top()) <= g:
            return 0
        if inside_h and abs(y - c.bottom()) <= g:
            return 1
        if inside_v and abs(x - c.left()) <= g:
            return 2
        if inside_v and abs(x - c.right()) <= g:
            return 3
        return None

    def mousePressEvent(self, ev):
        self._drag = self._hit(ev.position())

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is None:
            h = self._hit(pos)
            self.setCursor(Qt.CursorShape.SizeVerCursor if h in (0, 1) else
                           Qt.CursorShape.SizeHorCursor if h in (2, 3) else Qt.CursorShape.ArrowCursor)
            return
        r = self._img_rect()
        if r.isNull():
            return
        m = list(self._m)
        if self._drag == 0:
            m[0] = (pos.y() - r.top()) / r.height() * 100
        elif self._drag == 1:
            m[1] = (r.bottom() - pos.y()) / r.height() * 100
        elif self._drag == 2:
            m[2] = (pos.x() - r.left()) / r.width() * 100
        else:
            m[3] = (r.right() - pos.x()) / r.width() * 100
        m = [round(max(0.0, min(pc.CROP_MAX, v)), 1) for v in m]
        self._m = m
        self.update()
        self.marginsDragged.emit(m)

    def mouseReleaseEvent(self, ev):
        self._drag = None


class CropDialog(QDialog):
    """적용할 쪽·스타일·여백을 고른다. `result_plan()` 이 호출부에 넘길 값."""

    def __init__(self, path: str, *, current_page: int = 0, selected_pages=None,
                 styles=None, auto=None, chosen_id: str = pc.PORTRAIT, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("쪽 크롭"))
        self.resize(1080, 700)
        self._doc = fitz.open(str(path))          # 미리보기 전용 사본 핸들 — 저장하지 않는다
        self._n = self._doc.page_count
        self._full = set()                         # CropBox 를 쪽 전체로 넓힌 쪽(미리보기용)
        self._cropped = {}
        self._styles = pc.load_styles(styles)
        self._auto = pc.load_auto(auto, self._styles)
        self._cur = max(0, min(self._n - 1, int(current_page or 0)))
        self._reset = False
        self._ov_img = None
        self._ov_queue = []
        self._ov_timer = QTimer(self); self._ov_timer.setInterval(15)     # 응답성 SOT ⑥ — 간격 0 반복 타이머 금지
        self._ov_timer.timeout.connect(self._overlay_step)
        self._thumb_queue = list(range(self._n))
        self._thumb_timer = QTimer(self); self._thumb_timer.setInterval(15)
        self._thumb_timer.timeout.connect(self._thumb_step)

        root = QHBoxLayout(self)
        # ── 왼쪽: 쪽 썸네일 ──
        left = QVBoxLayout()
        hdr = QLabel(tr("쪽 (Ctrl·Shift 로 여럿 고르기)"))
        hdr.setWordWrap(True); hdr.setFixedWidth(THUMB_W + 50)
        left.addWidget(hdr)
        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setFlow(QListView.Flow.TopToBottom)
        self.list.setWrapping(False)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setIconSize(QSize(THUMB_W, int(THUMB_W * 1.42)))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setFixedWidth(THUMB_W + 50)
        ph = QPixmap(THUMB_W, int(THUMB_W * 1.42)); ph.fill(QColor("#eeeeee"))
        for i in range(self._n):
            it = QListWidgetItem(QIcon(ph), str(i + 1))
            it.setData(Qt.ItemDataRole.UserRole, i)
            self.list.addItem(it)
        left.addWidget(self.list, 1)
        root.addLayout(left)

        # ── 가운데: 미리보기 ──
        mid = QVBoxLayout()
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀"); self.btn_prev.setFixedWidth(34)
        self.btn_next = QPushButton("▶"); self.btn_next.setFixedWidth(34)
        self.spin_page = QSpinBox(); self.spin_page.setRange(1, max(1, self._n))
        self.lbl_total = QLabel("/ %d" % self._n)
        self.lbl_kind = QLabel()
        self.chk_overlay = QCheckBox(tr("겹쳐 보기"))
        self.chk_overlay.setToolTip(tr("적용할 쪽 가운데 지금 쪽과 같은 방향의 쪽을 겹쳐 그립니다(최대 40쪽) — "
                                       "어느 쪽 내용도 잘리지 않게 고를 때"))
        for w in (self.btn_prev, self.spin_page, self.lbl_total, self.btn_next):
            nav.addWidget(w)
        nav.addSpacing(12); nav.addWidget(self.lbl_kind); nav.addStretch(1); nav.addWidget(self.chk_overlay)
        mid.addLayout(nav)
        self.canvas = CropCanvas()
        mid.addWidget(self.canvas, 1)
        root.addLayout(mid, 1)

        # ── 오른쪽: 설정 ──
        side = QWidget()
        sv = QVBoxLayout(side); sv.setContentsMargins(0, 0, 0, 0)

        g_scope = QGroupBox(tr("적용할 쪽"))
        gs = QGridLayout(g_scope)
        self.rb_all = QRadioButton(tr("전체"))
        self.rb_range = QRadioButton(tr("쪽 범위:"))
        self.edit_range = QLineEdit(); self.edit_range.setPlaceholderText(tr("예: 1-5, 8"))
        self.rb_sel = QRadioButton(tr("왼쪽에서 고른 쪽"))
        self.rb_cur = QRadioButton(tr("현재 쪽"))
        self.bg_scope = QButtonGroup(self)
        for b in (self.rb_all, self.rb_range, self.rb_sel, self.rb_cur):
            self.bg_scope.addButton(b)
        gs.addWidget(self.rb_all, 0, 0, 1, 2)
        gs.addWidget(self.rb_range, 1, 0); gs.addWidget(self.edit_range, 1, 1)
        gs.addWidget(self.rb_sel, 2, 0, 1, 2)
        gs.addWidget(self.rb_cur, 3, 0, 1, 2)
        self.lbl_count = QLabel(); self.lbl_count.setStyleSheet("color:#888;")
        gs.addWidget(self.lbl_count, 4, 0, 1, 2)
        sv.addWidget(g_scope)

        g_style = QGroupBox(tr("스타일"))
        fs = QFormLayout(g_style)
        self.chk_auto = QCheckBox(tr("쪽 방향에 맞는 스타일 자동 적용"))
        fs.addRow(self.chk_auto)
        self.cmb_auto_p = QComboBox(); self.cmb_auto_l = QComboBox()
        fs.addRow(tr("세로긴 쪽 →"), self.cmb_auto_p)
        fs.addRow(tr("가로긴 쪽 →"), self.cmb_auto_l)
        self.cmb_style = QComboBox()
        fs.addRow(tr("편집할 스타일:"), self.cmb_style)
        rs = QHBoxLayout(); rs.setContentsMargins(0, 0, 0, 0)
        self.btn_add = QPushButton(tr("스타일 추가")); self.btn_del = QPushButton(tr("스타일 삭제"))
        self.btn_add.setToolTip(tr("지금 스타일을 복사해 새 스타일을 만듭니다"))
        rs.addWidget(self.btn_add); rs.addWidget(self.btn_del); rs.addStretch(1)
        fs.addRow(rs)
        for cmb in (self.cmb_auto_p, self.cmb_auto_l, self.cmb_style):
            # 디자인 SOT §2.14: 콤보가 가장 긴 이름으로 폭을 벌려 가로 스크롤을 만들지 않게
            cmb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cmb.setMinimumContentsLength(8)
        sv.addWidget(g_style)

        g_m = QGroupBox(tr("여백 (%)"))
        self.g_margin = g_m
        gm = QGridLayout(g_m)
        self.spins, self.mm = [], []
        for i, name in enumerate((tr("위"), tr("아래"), tr("왼쪽"), tr("오른쪽"))):
            sp = QDoubleSpinBox(); sp.setRange(0.0, pc.CROP_MAX); sp.setDecimals(1); sp.setSingleStep(0.5)
            sp.setSuffix(" %")
            lab = QLabel(); lab.setStyleSheet("color:#888;")
            gm.addWidget(QLabel(name), i, 0); gm.addWidget(sp, i, 1); gm.addWidget(lab, i, 2)
            self.spins.append(sp); self.mm.append(lab)
        self.chk_detect = QCheckBox(tr("흰 여백 자동 감지"))
        self.chk_detect.setToolTip(tr("쪽마다 내용의 경계를 찾아 자릅니다 — 위 칸은 경계 바깥으로 남길 여백이 됩니다"))
        self.chk_mirror = QCheckBox(tr("홀짝 좌우 대칭"))
        self.chk_mirror.setToolTip(tr("짝수 쪽에서는 왼쪽·오른쪽 여백을 바꿔 적용합니다(제본 안쪽·바깥쪽)"))
        self.btn_zero = QPushButton(tr("0 으로"))
        gm.addWidget(self.chk_detect, 4, 0, 1, 3)
        gm.addWidget(self.chk_mirror, 5, 0, 1, 3)
        gm.addWidget(self.btn_zero, 6, 0, 1, 1)
        sv.addWidget(g_m)
        sv.addStretch(1)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # 디자인 SOT §2.14 — 세로 스크롤만
        sa.setWidget(side); sa.setFixedWidth(max(340, side.minimumSizeHint().width() + 20))
        right = QVBoxLayout()
        right.addWidget(sa, 1)
        bb = QDialogButtonBox()
        self.btn_reset = bb.addButton(tr("크롭 해제"), QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_reset.setToolTip(tr("적용할 쪽을 원래 쪽 크기로 되돌립니다"))
        self.btn_ok = bb.addButton(tr("적용"), QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(tr("취소"), QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self._accept_crop)
        bb.rejected.connect(self.reject)
        self.btn_reset.clicked.connect(self._accept_reset)
        right.addWidget(bb)
        root.addLayout(right)

        # ── 초기값 ──
        self._fill_style_combos()
        self.chk_auto.setChecked(bool(self._auto.get("on")))
        i = self.cmb_style.findData(chosen_id)
        self.cmb_style.setCurrentIndex(max(0, i))
        sel = sorted({int(p) for p in (selected_pages or []) if 0 <= int(p) < self._n})
        if sel:
            for p in sel:
                self.list.item(p).setSelected(True)
            self.rb_sel.setChecked(True)
        else:
            self.rb_all.setChecked(True)

        # ── 연결 ──
        self.btn_prev.clicked.connect(lambda: self._goto(self._cur - 1))
        self.btn_next.clicked.connect(lambda: self._goto(self._cur + 1))
        self.spin_page.valueChanged.connect(lambda v: self._goto(v - 1))
        self.list.currentRowChanged.connect(lambda r: self._goto(r) if r >= 0 else None)
        self.list.itemSelectionChanged.connect(self._on_selection)
        for b in (self.rb_all, self.rb_range, self.rb_sel, self.rb_cur):
            b.toggled.connect(lambda _on: self._scope_changed())
        self.edit_range.textChanged.connect(lambda _t: (self.rb_range.setChecked(True), self._scope_changed()))
        self.chk_auto.toggled.connect(self._auto_toggled)
        self.cmb_auto_p.currentIndexChanged.connect(lambda _i: self._auto_map_changed())
        self.cmb_auto_l.currentIndexChanged.connect(lambda _i: self._auto_map_changed())
        self.cmb_style.currentIndexChanged.connect(lambda _i: self._load_style_into_controls())
        self.btn_add.clicked.connect(self._add_style)
        self.btn_del.clicked.connect(self._del_style)
        for sp in self.spins:
            sp.valueChanged.connect(lambda _v: self._controls_changed())
        self.chk_detect.toggled.connect(lambda _on: self._controls_changed())
        self.chk_mirror.toggled.connect(lambda _on: self._controls_changed())
        self.btn_zero.clicked.connect(self._zero)
        self.canvas.marginsDragged.connect(self._on_drag)
        self.chk_overlay.toggled.connect(lambda _on: self._refresh_preview())

        self._auto_toggled(self.chk_auto.isChecked())
        self._goto(self._cur, force=True)
        self._scope_changed()
        self._thumb_timer.start()

    # ── 공용 ──────────────────────────────────────────────────────
    def _style(self, sid=None) -> dict:
        sid = sid or self.cmb_style.currentData()
        return next((s for s in self._styles if s["id"] == sid), self._styles[0])

    def _fill_style_combos(self):
        for cmb in (self.cmb_style, self.cmb_auto_p, self.cmb_auto_l):
            keep = cmb.currentData()
            cmb.blockSignals(True)
            cmb.clear()
            for st in self._styles:
                cmb.addItem(style_label(st), st["id"])
            i = cmb.findData(keep)
            cmb.setCurrentIndex(max(0, i))
            cmb.blockSignals(False)
        self.cmb_auto_p.blockSignals(True); self.cmb_auto_l.blockSignals(True)
        self.cmb_auto_p.setCurrentIndex(max(0, self.cmb_auto_p.findData(self._auto.get(pc.PORTRAIT))))
        self.cmb_auto_l.setCurrentIndex(max(0, self.cmb_auto_l.findData(self._auto.get(pc.LANDSCAPE))))
        self.cmb_auto_p.blockSignals(False); self.cmb_auto_l.blockSignals(False)

    def _page_full(self, i):
        """미리보기 사본에서 i 쪽의 CropBox 를 쪽 전체로(처음 한 번). 원래 잘렸는지 먼저 적어 둔다."""
        if i in self._full:
            return self._doc[i]
        page = self._doc[i]
        self._cropped[i] = pc.is_cropped(page)
        pc.reset_crop(page)
        self._full.add(i)
        return self._doc[i]

    def _render(self, i, width) -> QImage:
        page = self._page_full(i)
        s = width / max(1.0, page.rect.width)
        return _qimage(page.get_pixmap(matrix=fitz.Matrix(s, s), alpha=False))

    def target_pages(self) -> list:
        if self.rb_all.isChecked():
            return list(range(self._n))
        if self.rb_range.isChecked():
            return pc.parse_range(self.edit_range.text(), self._n)
        if self.rb_sel.isChecked():
            return sorted(it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems())
        return [self._cur]

    def _style_for_page(self, i) -> dict:
        if self.chk_auto.isChecked():
            o = pc.orientation(self._page_full(i))
            return self._style(self._auto.get(o) or o)
        return self._style()

    # ── 쪽 이동·미리보기 ──────────────────────────────────────────
    def _goto(self, i, force=False):
        i = max(0, min(self._n - 1, int(i)))
        if i == self._cur and not force:
            return
        self._cur = i
        for w, v in ((self.spin_page, i + 1),):
            w.blockSignals(True); w.setValue(v); w.blockSignals(False)
        self.list.blockSignals(True); self.list.setCurrentRow(i, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.list.blockSignals(False)
        page = self._page_full(i)
        o = pc.orientation(page)
        self.lbl_kind.setText(tr("가로긴 쪽") if o == pc.LANDSCAPE else tr("세로긴 쪽"))
        if self.chk_auto.isChecked():
            sid = self._auto.get(o) or o
            self.cmb_style.blockSignals(True)
            self.cmb_style.setCurrentIndex(max(0, self.cmb_style.findData(sid)))
            self.cmb_style.blockSignals(False)
            self._load_style_into_controls()
        else:
            self._refresh_preview()
        if self.rb_cur.isChecked():
            self._scope_changed()

    def _refresh_preview(self):
        page = self._page_full(self._cur)
        st = self._style_for_page(self._cur)
        m = pc.margins_for(page, self._cur, st)
        w, h = pc.full_size_pt(page)
        for k, lab in enumerate(self.mm):
            size = h if k < 2 else w
            v = (m[k] if m is not None else 0.0) if st["auto"] else self.spins[k].value()
            lab.setText("%.1f mm" % (size * v / 100.0 / PT_PER_MM))
        note = tr("내용이 없어 자르지 않습니다") if m is None else ""
        editable = not st["auto"]
        if self.chk_overlay.isChecked():
            self._start_overlay()
        else:
            self._ov_timer.stop()
            self.canvas.set_image(self._render(self._cur, 900), note)
        self.canvas.set_margins(m, editable=editable)

    def _start_overlay(self):
        o = pc.orientation(self._page_full(self._cur))
        same = [p for p in self.target_pages() if pc.orientation(self._doc[p]) == o] or [self._cur]
        if len(same) > OVERLAY_MAX:
            step = len(same) / float(OVERLAY_MAX)
            same = [same[int(k * step)] for k in range(OVERLAY_MAX)]
        base = self._render(self._cur, 700)
        self._ov_img = QImage(base.size(), QImage.Format.Format_RGB888)
        self._ov_img.fill(QColor("white"))
        self._ov_queue = list(same)
        self._ov_timer.start()

    def _overlay_step(self):
        """한 틱에 한 쪽씩 겹친다(응답성 SOT — 메인 스레드 반복문을 시간으로 나눈다)."""
        if not self._ov_queue or self._ov_img is None:
            self._ov_timer.stop(); return
        p = self._ov_queue.pop(0)
        img = self._render(p, self._ov_img.width())
        qp = QPainter(self._ov_img)
        qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Darken)
        qp.drawImage(QRectF(0, 0, self._ov_img.width(), self._ov_img.height()), img)
        qp.end()
        self.canvas.set_image(self._ov_img, tr("겹쳐 보기: 남은 {n}쪽").format(n=len(self._ov_queue)) if self._ov_queue else "")

    def _thumb_step(self):
        if not self._thumb_queue:
            self._thumb_timer.stop(); return
        i = self._thumb_queue.pop(0)
        try:
            img = self._render(i, THUMB_W)
            it = self.list.item(i)
            it.setIcon(QIcon(QPixmap.fromImage(img)))
            if self._cropped.get(i):
                it.setText("%d ✂" % (i + 1))
                it.setToolTip(tr("이미 크롭된 쪽"))
        except Exception:
            pass

    # ── 범위 ──────────────────────────────────────────────────────
    def _on_selection(self):
        if self.list.selectedItems() and not self.rb_sel.isChecked() and self.list.hasFocus():
            self.rb_sel.setChecked(True)
        self._scope_changed()

    def _scope_changed(self):
        n = len(self.target_pages())
        self.lbl_count.setText(tr("대상 {n}쪽").format(n=n))
        self.btn_ok.setEnabled(n > 0)
        self.btn_reset.setEnabled(n > 0)
        if self.chk_overlay.isChecked():
            self._refresh_preview()

    # ── 스타일 ────────────────────────────────────────────────────
    def _auto_toggled(self, on):
        self._auto["on"] = bool(on)
        self.cmb_auto_p.setEnabled(on); self.cmb_auto_l.setEnabled(on)
        self._goto(self._cur, force=True)

    def _auto_map_changed(self):
        self._auto[pc.PORTRAIT] = self.cmb_auto_p.currentData()
        self._auto[pc.LANDSCAPE] = self.cmb_auto_l.currentData()
        self._goto(self._cur, force=True)

    def _load_style_into_controls(self):
        st = self._style()
        for k, sp in enumerate(self.spins):
            sp.blockSignals(True); sp.setValue(st["margins"][k]); sp.blockSignals(False)
        for chk, v in ((self.chk_detect, st["auto"]), (self.chk_mirror, st["mirror"])):
            chk.blockSignals(True); chk.setChecked(v); chk.blockSignals(False)
        self.g_margin.setTitle(tr("남길 여백 (%)") if st["auto"] else tr("여백 (%)"))
        self.btn_del.setEnabled(st["id"] not in pc.BUILTIN_IDS)
        if self.chk_auto.isChecked():
            # 자동 적용 중 편집할 스타일을 바꾸면 그 스타일이 쓰이는 방향의 쪽으로 미리보기를 옮기지는 않는다
            pass
        self._refresh_preview()

    def _controls_changed(self):
        st = self._style()
        st["margins"] = [round(sp.value(), 1) for sp in self.spins]
        st["auto"] = self.chk_detect.isChecked()
        st["mirror"] = self.chk_mirror.isChecked()
        self.g_margin.setTitle(tr("남길 여백 (%)") if st["auto"] else tr("여백 (%)"))
        self._refresh_preview()

    def _on_drag(self, m):
        """미리보기에서 끈 값(보이는 쪽 기준) → 스타일 값. 홀짝 대칭인 짝수 쪽이면 좌우를 되돌린다."""
        st = self._style()
        m = list(m)
        if st["mirror"] and (self._cur + 1) % 2 == 0:
            m[2], m[3] = m[3], m[2]
        for k, sp in enumerate(self.spins):
            sp.blockSignals(True); sp.setValue(m[k]); sp.blockSignals(False)
        st["margins"] = [round(v, 1) for v in m]
        self._refresh_mm_only()

    def _refresh_mm_only(self):
        page = self._page_full(self._cur)
        w, h = pc.full_size_pt(page)
        for k, lab in enumerate(self.mm):
            size = h if k < 2 else w
            lab.setText("%.1f mm" % (size * self.spins[k].value() / 100.0 / PT_PER_MM))

    def _zero(self):
        for sp in self.spins:
            sp.blockSignals(True); sp.setValue(0.0); sp.blockSignals(False)
        self._controls_changed()

    def _add_style(self):
        name, ok = QInputDialog.getText(self, tr("스타일 추가"), tr("새 스타일 이름:"))
        name = (name or "").strip()
        if not ok or not name:
            return
        if any(style_label(s) == name for s in self._styles):
            QMessageBox.information(self, tr("스타일 추가"), tr("같은 이름의 스타일이 있습니다."))
            return
        src = self._style()
        st = pc.norm_style(dict(src, id=pc.new_style_id(self._styles), name=name))
        self._styles.append(st)
        self._fill_style_combos()
        self.cmb_style.setCurrentIndex(self.cmb_style.findData(st["id"]))

    def _del_style(self):
        st = self._style()
        if st["id"] in pc.BUILTIN_IDS:
            return
        self._styles = [s for s in self._styles if s["id"] != st["id"]]
        for k in (pc.PORTRAIT, pc.LANDSCAPE):
            if self._auto.get(k) == st["id"]:
                self._auto[k] = k
        self._fill_style_combos()
        self._load_style_into_controls()

    # ── 결과 ──────────────────────────────────────────────────────
    def _accept_crop(self):
        self._reset = False
        self.accept()

    def _accept_reset(self):
        n = len(self.target_pages())
        if QMessageBox.question(self, tr("크롭 해제"),
                                tr("대상 {n}쪽의 크롭을 해제해 원래 쪽 크기로 되돌릴까요?").format(n=n)) \
                != QMessageBox.StandardButton.Yes:
            return
        self._reset = True
        self.accept()

    def result_plan(self) -> dict:
        return {"reset": self._reset, "pages": self.target_pages(),
                "styles": [dict(s) for s in self._styles], "auto": dict(self._auto),
                "chosen_id": self.cmb_style.currentData()}

    def done(self, r):
        self._ov_timer.stop(); self._thumb_timer.stop()
        try:
            self._doc.close()
        except Exception:
            pass
        super().done(r)
