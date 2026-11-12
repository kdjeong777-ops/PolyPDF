# -*- coding: utf-8 -*-
"""등록 이미지 — 등록 창(`StampEditDialog`)·관리 창(`StampManagerDialog`) (261101-3, 마스터 §4.6.11).

등록 창: 미리보기(체크무늬 바탕) · 종류(PDF 그대로 / 그림 바탕 투명) · 바탕 문턱 · 잉크 색 · 폭 mm · 날짜 글자(자리는 미리보기에서 끌어).
관리 창: 목록(끌어 차례) · 미리보기 · [추가 ▾] · [고치기…] · [지우기].
"""
from __future__ import annotations

import io

from PyQt6.QtCore import Qt, QRectF, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPen, QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QRadioButton,
                             QButtonGroup, QCheckBox, QSlider, QComboBox, QDoubleSpinBox, QPushButton, QWidget,
                             QDialogButtonBox, QListWidget, QListWidgetItem, QMenu, QMessageBox, QFileDialog,
                             QInputDialog, QColorDialog, QAbstractItemView)

from viewer.i18n import tr, tr_noop
from viewer import stamp_store, stamp_core

INPUT_MAX = 2400          # 정리 전에 긴 변을 이만큼으로 — 사진·600dpi 영역이 커도 창이 서지 않게(응답성 SOT §5)
INKS = (("original", tr_noop("원래 색")), ("black", tr_noop("검정")), ("blue", tr_noop("파랑")), ("red", tr_noop("빨강")))   # 표시는 tr()
RED = (192, 32, 32)


def _pix_from_png(data: bytes) -> QPixmap:
    pm = QPixmap()
    pm.loadFromData(data, "PNG")
    return pm


def _checker(p: QPainter, r: QRectF, cell: int = 8) -> None:
    p.save()
    p.setClipRect(r)
    p.fillRect(r, QColor("#ffffff"))
    y, row = r.top(), 0
    while y < r.bottom():
        x = r.left() + (cell if row % 2 else 0)
        while x < r.right():
            p.fillRect(QRectF(x, y, cell, cell), QColor("#d8d8d8"))
            x += 2 * cell
        y += cell
        row += 1
    p.restore()


class _Preview(QWidget):
    """체크무늬 바탕 위 그림. 날짜를 켜면 날짜 상자(점선)를 끌어 정한다."""
    boxChanged = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 220)
        self._pm = QPixmap()
        self._box = None
        self._drag = None

    def set_image(self, pm: QPixmap, box=None):
        self._pm = pm
        self._box = list(box) if box else None
        self.update()

    def _img_rect(self) -> QRectF:
        if self._pm.isNull():
            return QRectF()
        W, H = self.width() - 16, self.height() - 16
        s = min(W / max(1, self._pm.width()), H / max(1, self._pm.height()))
        w, h = self._pm.width() * s, self._pm.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        _checker(p, QRectF(self.rect()))
        r = self._img_rect()
        if not r.isEmpty():
            p.drawPixmap(r, self._pm, QRectF(self._pm.rect()))
            p.setPen(QPen(QColor("#888888"), 1, Qt.PenStyle.DotLine))
            p.drawRect(r)
            if self._box:
                x, y, w, h = self._box
                p.setPen(QPen(QColor("#ff7a00"), 1.5, Qt.PenStyle.DashLine))
                p.drawRect(QRectF(r.left() + x * r.width(), r.top() + y * r.height(), w * r.width(), h * r.height()))
        p.end()

    def _norm(self, pos):
        r = self._img_rect()
        return (min(1.0, max(0.0, (pos.x() - r.left()) / max(1.0, r.width()))),
                min(1.0, max(0.0, (pos.y() - r.top()) / max(1.0, r.height()))))

    def mousePressEvent(self, e):
        if self._box is not None and e.button() == Qt.MouseButton.LeftButton:
            self._drag = self._norm(e.position())

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            a, b = self._drag, self._norm(e.position())
            self._box = [min(a[0], b[0]), min(a[1], b[1]), abs(a[0] - b[0]), abs(a[1] - b[1])]
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            if self._box and self._box[2] > 0.02 and self._box[3] > 0.02:
                self.boxChanged.emit(list(self._box))


class StampEditDialog(QDialog):
    """새 등록·고치기 공용. `pdf`(벡터 조각 바이트)·`img`(Pillow 그림) 중 있는 것으로 연다."""

    def __init__(self, parent=None, *, name: str = "", pdf: bytes | None = None, img=None,
                 width_mm: float | None = None, date: dict | None = None, kind: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("등록 이미지"))
        self._pdf = pdf
        self._src = None
        if img is not None:
            img = img.copy()
            if max(img.size) > INPUT_MAX:
                img.thumbnail((INPUT_MAX, INPUT_MAX))
            self._src = img
        elif pdf is not None:
            from PIL import Image
            self._src = Image.open(io.BytesIO(stamp_core.render_piece(pdf, INPUT_MAX))).convert("RGBA")
        self._date = stamp_store.norm_date(date)
        self._result = None
        self._cleaned = None
        self._crop = None                     # 원본 그림 안 정규화 [x, y, w, h] — 사진에 도장이 여럿·양식 선이 있을 때

        lay = QVBoxLayout(self)
        self.preview = _Preview(self)
        self.preview.boxChanged.connect(self._on_box)
        lay.addWidget(self.preview, 1)
        form = QFormLayout()
        self.ed_name = QLineEdit(name or tr("도장"))
        form.addRow(tr("이름"), self.ed_name)

        self.rb_pdf = QRadioButton(tr("선명하게 (PDF 그대로 — 글자가 글자로 남는다)"))
        self.rb_png = QRadioButton(tr("그림 (바탕 투명)"))
        grp = QButtonGroup(self)
        grp.addButton(self.rb_pdf)
        grp.addButton(self.rb_png)
        use_pdf = pdf is not None and (kind or "pdf") == "pdf"
        (self.rb_pdf if use_pdf else self.rb_png).setChecked(True)
        self.rb_pdf.setEnabled(pdf is not None)
        kind_row = QWidget()
        kl = QHBoxLayout(kind_row)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.addWidget(self.rb_pdf)
        kl.addWidget(self.rb_png)
        form.addRow(tr("종류"), kind_row)

        self.cb_auto = QCheckBox(tr("자동"))
        self.cb_auto.setChecked(True)
        self.sl_thr = QSlider(Qt.Orientation.Horizontal)
        self.sl_thr.setRange(30, 250)
        self.sl_thr.setValue(stamp_core_threshold(self._src))
        self.sl_thr.setEnabled(False)
        self.btn_crop = QPushButton(tr("자르기"))
        self.btn_crop.setCheckable(True)
        self.btn_crop.setToolTip(tr("누른 뒤 미리보기에서 남길 부분을 끌어 고릅니다 — 다시 누르면 적용"))
        self.btn_crop.toggled.connect(self._crop_mode)
        thr_row = QWidget()
        tl = QHBoxLayout(thr_row)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.cb_auto)
        tl.addWidget(self.sl_thr, 1)
        tl.addWidget(self.btn_crop)
        form.addRow(tr("바탕 지우기"), thr_row)
        self.cmb_ink = QComboBox()
        for key, label in INKS:
            self.cmb_ink.addItem(tr(label), key)
        form.addRow(tr("잉크 색"), self.cmb_ink)

        self.sp_mm = QDoubleSpinBox()
        self.sp_mm.setRange(stamp_store.MM_MIN, stamp_store.MM_MAX)
        self.sp_mm.setDecimals(1)
        self.sp_mm.setSuffix(" mm")
        self.sp_mm.setValue(stamp_store.clamp_mm(width_mm if width_mm else stamp_store.MM_DEFAULT))
        self.lb_h = QLabel()
        mm_row = QWidget()
        ml = QHBoxLayout(mm_row)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(self.sp_mm)
        ml.addWidget(self.lb_h, 1)
        form.addRow(tr("실제 폭"), mm_row)

        self.cb_date = QCheckBox(tr("날짜 넣기 (넣는 날의 날짜 — 미리보기에서 끌어 자리를 정합니다)"))
        self.cb_date.setChecked(self._date["on"])
        self.cmb_fmt = QComboBox()
        for f in stamp_store.DATE_FORMATS:
            self.cmb_fmt.addItem(stamp_store.date_text(f), f)
        self.cmb_fmt.setCurrentIndex(max(0, self.cmb_fmt.findData(self._date["fmt"])))
        self.btn_col = QPushButton()
        self.btn_col.clicked.connect(self._pick_color)
        date_row = QWidget()
        dl = QHBoxLayout(date_row)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(self.cb_date)
        dl.addWidget(self.cmb_fmt)
        dl.addWidget(self.btn_col)
        form.addRow(tr("날짜"), date_row)
        lay.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._refresh)
        for sig in (self.rb_pdf.toggled, self.cb_auto.toggled, self.sl_thr.valueChanged, self.cmb_ink.currentIndexChanged,
                    self.sp_mm.valueChanged, self.cb_date.toggled, self.cmb_fmt.currentIndexChanged):
            sig.connect(lambda *_: self._timer.start())
        self.cb_auto.toggled.connect(lambda on: self.sl_thr.setEnabled(not on))
        self._sync_color_btn()
        self.resize(560, 560)
        self._refresh()

    # ── 상태 ──
    def is_pdf(self) -> bool:
        return self._pdf is not None and self.rb_pdf.isChecked()

    def _payload(self):
        """(kind, 바이트, 그림(Pillow, 화면용)) — 지금 설정으로."""
        if self.is_pdf():
            from PIL import Image
            return "pdf", self._pdf, Image.open(io.BytesIO(stamp_core.render_piece(self._pdf))).convert("RGBA")
        thr = None if self.cb_auto.isChecked() else self.sl_thr.value()
        ink = self.cmb_ink.currentData()
        src = self._src
        if self._crop:
            x, y, w, h = self._crop
            W, H = src.size
            src = src.crop((int(x * W), int(y * H), max(int(x * W) + 1, int((x + w) * W)), max(int(y * H) + 1, int((y + h) * H))))
        img = stamp_core.clean(src, threshold=thr, ink="original" if ink == "red" else ink)
        if ink == "red":
            img = stamp_core.recolor(img, RED)
        return "png", stamp_core.png_bytes(img), img

    def _crop_mode(self, on: bool):
        if on:                                # 원본 전체를 보이고 지금 자르기 상자를 그린다
            self.preview.set_image(_pix_from_png(stamp_core.png_bytes(self._src.convert("RGBA"))),
                                   self._crop or [0.0, 0.0, 1.0, 1.0])
        else:
            self._timer.start()

    def _refresh(self):
        if self.btn_crop.isChecked():
            return
        for w in (self.cb_auto, self.sl_thr, self.cmb_ink, self.btn_crop):
            w.setEnabled(not self.is_pdf() and (w is not self.sl_thr or not self.cb_auto.isChecked()))
        try:
            kind, data, img = self._payload()
        except Exception:
            return
        self._cleaned = (kind, data, img)
        aspect = img.height / max(1, img.width)
        if kind == "pdf":
            w_pt, h_pt = stamp_core.piece_size_pt(data)
            aspect = h_pt / max(1.0, w_pt)
        self._aspect = aspect
        self.lb_h.setText(tr("높이 {h} mm").format(h=f"{self.sp_mm.value() * aspect:.1f}"))
        self._date.update(on=self.cb_date.isChecked(), fmt=self.cmb_fmt.currentData())
        self.cmb_fmt.setEnabled(self._date["on"])
        self.btn_col.setEnabled(self._date["on"])
        entry = {"kind": kind, "date": self._date}
        try:
            c = stamp_core.compose(entry, data)
            pm = _pix_from_png(c["png"])
        except Exception:
            pm = _pix_from_png(stamp_core.png_bytes(img))
        self.preview.set_image(pm, self._date["box"] if self._date["on"] else None)

    def _on_box(self, box):
        if self.btn_crop.isChecked():
            self._crop = None if box[2] > 0.98 and box[3] > 0.98 else [round(v, 4) for v in box]
            return                            # 다시 누르면 적용(_crop_mode)
        self._date["box"] = [round(v, 4) for v in box]
        self._timer.start()

    def _sync_color_btn(self):
        col = self._date.get("color") or ""
        self.btn_col.setText(tr("색: 잉크") if not col else tr("색: {c}").format(c=col))

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._date.get("color") or "#1030a0"), self, tr("날짜 글자 색"))
        if c.isValid():
            self._date["color"] = c.name()
            self._sync_color_btn()
            self._timer.start()

    def _ok(self):
        self._timer.stop()
        if self.btn_crop.isChecked():
            self.btn_crop.setChecked(False)
        self._refresh()
        if self._cleaned is None:
            return
        kind, data, img = self._cleaned
        if kind == "png" and stamp_core_ink_empty(img):
            QMessageBox.information(self, tr("등록 이미지"), tr("남은 그림이 없습니다 — 바탕 지우기 문턱을 낮추세요."))
            return
        self._result = {"kind": kind, "payload": data, "name": self.ed_name.text().strip() or tr("도장"),
                        "width_mm": self.sp_mm.value(), "date": dict(self._date)}
        self.accept()

    def result_value(self):
        return self._result


def stamp_core_threshold(img) -> int:
    from viewer import sign_core
    try:
        return int(sign_core.auto_threshold(img)) if img is not None else 200
    except Exception:
        return 200


def stamp_core_ink_empty(img) -> bool:
    from viewer import sign_core
    return sign_core.ink_bbox(img) is None


# ── 등록 원천 → 등록 창 ────────────────────────────────────────────────────

def edit_from_pdf_region(parent, doc, pno: int, clip, name: str = "") -> dict | None:
    """본문 영역 → 등록 창. 글자층이 있으면 벡터 조각이 기본, 없으면 그림."""
    page = doc[pno]
    has_text = stamp_core.region_has_text(page, clip)
    pdf = stamp_core.region_piece(doc, pno, clip)
    img = stamp_core.region_png(page, clip)
    import fitz
    w_mm = fitz.Rect(clip).width / stamp_core.PT_PER_MM          # 끈 영역의 실제 폭(쪽 pt 기준)
    dlg = StampEditDialog(parent, name=name, pdf=pdf, img=img, width_mm=w_mm, kind="pdf" if has_text else "png")
    return dlg.result_value() if dlg.exec() == QDialog.DialogCode.Accepted else None


def edit_from_image(parent, img, name: str = "", width_mm=None) -> dict | None:
    dlg = StampEditDialog(parent, name=name, img=img, width_mm=width_mm)
    return dlg.result_value() if dlg.exec() == QDialog.DialogCode.Accepted else None


def register(res: dict | None):
    if not res:
        return None
    return stamp_store.add(res["kind"], res["payload"], res["name"], res["width_mm"], res["date"])


def qimage_to_pil(qimg):
    from PIL import Image
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QIODevice.OpenModeFlag.WriteOnly)
    qimg.save(b, "PNG")
    b.close()
    return Image.open(io.BytesIO(bytes(ba))).convert("RGBA")


def load_from_file(parent, path: str):
    """파일 → 등록 창 결과. PDF 면 쪽을 골라 내용 경계만 벡터 조각으로."""
    from pathlib import Path
    if path.lower().endswith(".pdf"):
        import fitz
        doc = fitz.open(path)
        try:
            n = doc.page_count
            pno = 0
            if n > 1:
                v, ok = QInputDialog.getInt(parent, tr("등록 이미지"), tr("등록할 쪽 (1~{n})").format(n=n), 1, 1, n)
                if not ok:
                    return None
                pno = v - 1
            return edit_from_pdf_region(parent, doc, pno, stamp_core.content_clip(doc[pno]), name=Path(path).stem)
        finally:
            doc.close()
    from PIL import Image
    try:
        img = Image.open(path)
        img.load()
    except Exception:
        QMessageBox.warning(parent, tr("등록 이미지"), tr("그림을 열 수 없습니다."))
        return None
    return edit_from_image(parent, img, name=Path(path).stem)


class _OrderList(QListWidget):
    """끌어 놓아 차례를 바꾸는 목록 — 놓은 뒤 `dropped`. QListWidget 의 InternalMove 는 `rowsMoved` 를 내지 않아
    (지우고 새로 넣는다) 종전 연결로는 바뀐 차례가 저장되지 않았다(261112-5)."""
    dropped = pyqtSignal()

    def dropEvent(self, e):
        super().dropEvent(e)
        self.dropped.emit()


class StampManagerDialog(QDialog):
    """'등록 이미지 관리' — 목록·미리보기·추가·고치기·지우기. `shots()` = 스크린샷 그림 경로 목록(새 것 먼저)."""

    def __init__(self, parent=None, shots=None):
        super().__init__(parent)
        self.setWindowTitle(tr("등록 이미지 관리"))
        self._shots = shots or (lambda: [])
        lay = QHBoxLayout(self)
        self.lst = _OrderList()
        self.lst.setIconSize(QSize(64, 40))
        self.lst.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lst.dropped.connect(lambda: stamp_store.reorder(self._ids()))
        self.lst.currentRowChanged.connect(self._show)
        # 261112-5(마스터 §4.6.11 '차례'): ↑ 위로 · ↓ 아래로 — 즐겨찾기 항목 관리와 같은 방식(디자인 SOT §2.9.5)
        left = QVBoxLayout()
        left.addWidget(self.lst, 1)
        mv_row = QHBoxLayout()
        self.btn_up = QPushButton(tr("↑ 위로"))
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down = QPushButton(tr("↓ 아래로"))
        self.btn_down.clicked.connect(lambda: self._move(+1))
        mv_row.addWidget(self.btn_up)
        mv_row.addWidget(self.btn_down)
        mv_row.addStretch(1)
        left.addLayout(mv_row)
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        self.preview = _Preview(self)
        right.addWidget(self.preview, 1)
        self.lb_info = QLabel()
        self.lb_info.setWordWrap(True)
        right.addWidget(self.lb_info)
        row = QHBoxLayout()
        self.btn_add = QPushButton(tr("추가"))
        m = QMenu(self.btn_add)
        m.addAction(tr("파일에서"), self._add_file)
        m.addAction(tr("클립보드에서"), self._add_clip)
        self._m_shot = m.addMenu(tr("스크린샷에서"))
        self._m_shot.aboutToShow.connect(self._fill_shots)
        self.btn_add.setMenu(m)
        self.btn_edit = QPushButton(tr("고치기"))
        self.btn_edit.clicked.connect(self._edit)
        self.btn_del = QPushButton(tr("지우기"))
        self.btn_del.clicked.connect(self._delete)
        for b in (self.btn_add, self.btn_edit, self.btn_del):
            row.addWidget(b)
        row.addStretch(1)
        bc = QPushButton(tr("닫기"))
        bc.clicked.connect(self.accept)
        row.addWidget(bc)
        right.addLayout(row)
        lay.addLayout(right, 2)
        self.resize(720, 420)
        self._reload()

    def _ids(self):
        return [self.lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lst.count())]

    def _move(self, delta: int):
        e = self._cur()
        if e is not None and stamp_store.move(e["id"], delta):
            self._reload(e["id"])

    def _reload(self, select: str = ""):
        self.lst.blockSignals(True)
        self.lst.clear()
        for e in stamp_store.items():
            it = QListWidgetItem(tr('{name} · 폭 {mm} mm').format(name=e.get("name", ""), mm=f'{float(e.get("width_mm", 0)):g}'))
            it.setData(Qt.ItemDataRole.UserRole, e["id"])
            try:
                it.setIcon(QIcon(_pix_from_png(stamp_core.compose(e, stamp_store.payload(e))["png"])))
            except Exception:
                pass
            self.lst.addItem(it)
        self.lst.blockSignals(False)
        ids = self._ids()
        self.lst.setCurrentRow(ids.index(select) if select in ids else (0 if ids else -1))
        self._show(self.lst.currentRow())

    def _cur(self):
        it = self.lst.currentItem()
        return stamp_store.get(it.data(Qt.ItemDataRole.UserRole)) if it else None

    def _show(self, _row=-1):
        e = self._cur()
        self.btn_edit.setEnabled(e is not None)
        self.btn_del.setEnabled(e is not None)
        row = self.lst.currentRow()
        self.btn_up.setEnabled(e is not None and row > 0)
        self.btn_down.setEnabled(e is not None and 0 <= row < self.lst.count() - 1)
        if e is None:
            self.preview.set_image(QPixmap())
            self.lb_info.setText(tr("등록 이미지가 없습니다 — [추가] 로 파일·클립보드·스크린샷을 등록하거나, 이미지 ▾ 'PDF 에서 영역 등록' 으로 본문의 영역을 등록합니다."))
            return
        try:
            c = stamp_core.compose(e, stamp_store.payload(e))
            self.preview.set_image(_pix_from_png(c["png"]))
            h = float(e.get("width_mm", 0)) * c["aspect"]
        except Exception:
            self.preview.set_image(QPixmap())
            h = 0.0
        kind = tr("PDF 그대로(선명)") if e.get("kind") == "pdf" else tr("그림(바탕 투명)")
        d = stamp_store.norm_date(e.get("date"))
        dt = stamp_store.date_text(d["fmt"]) if d["on"] else tr("없음")
        self.lb_info.setText(tr("{kind} · 폭 {w} mm × 높이 {h} mm · 날짜: {d}").format(
            kind=kind, w=f'{float(e.get("width_mm", 0)):g}', h=f"{h:.1f}", d=dt))

    def _added(self, res):
        e = register(res)
        if e:
            self._reload(e["id"])

    def _add_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, tr("등록할 그림·PDF"), "",
                                            tr("그림·PDF (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff *.pdf)"))
        if fn:
            self._added(load_from_file(self, fn))

    def _add_clip(self):
        from PyQt6.QtWidgets import QApplication
        img = QApplication.clipboard().image()
        if img is None or img.isNull():
            QMessageBox.information(self, tr("등록 이미지"), tr("클립보드에 그림이 없습니다."))
            return
        self._added(edit_from_image(self, qimage_to_pil(img)))

    def _fill_shots(self):
        from pathlib import Path
        self._m_shot.clear()
        paths = list(self._shots() or [])[:12]
        if not paths:
            self._m_shot.addAction(tr("스크린샷 없음")).setEnabled(False)
        for p in paths:
            self._m_shot.addAction(Path(p).name, lambda pp=p: self._add_shot(pp))

    def _add_shot(self, path):
        from PIL import Image
        from pathlib import Path
        try:
            img = Image.open(path)
            img.load()
        except Exception:
            return
        self._added(edit_from_image(self, img, name=Path(path).stem))

    def _edit(self):
        e = self._cur()
        if e is None:
            return
        from PIL import Image
        data = stamp_store.payload(e)
        if e.get("kind") == "pdf":
            dlg = StampEditDialog(self, name=e["name"], pdf=data, width_mm=e.get("width_mm"), date=e.get("date"), kind="pdf")
        else:
            dlg = StampEditDialog(self, name=e["name"], img=Image.open(io.BytesIO(data)), width_mm=e.get("width_mm"),
                                  date=e.get("date"))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        r = dlg.result_value()
        stamp_store.update(e["id"], name=r["name"], width_mm=r["width_mm"], date=r["date"],
                           payload=r["payload"], kind=r["kind"])
        self._reload(e["id"])

    def _delete(self):
        e = self._cur()
        if e is None:
            return
        if QMessageBox.question(self, tr("등록 이미지"), tr("'{name}' 을(를) 지울까요? 이미 넣은 곳은 그대로 남습니다.").format(
                name=e["name"])) != QMessageBox.StandardButton.Yes:
            return
        stamp_store.remove(e["id"])
        self._reload()
