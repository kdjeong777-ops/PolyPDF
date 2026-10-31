# -*- coding: utf-8 -*-
"""전자서명 대화상자 — 서명 그림·디지털 ID·서명 (보안 SOT §3·§6).

무거운 일(키 만들기·`.pfx` 열기·Hello 확인)은 `runner(fn, title)` 로 배경에서 한다 — 앱이 넘겨 주는
`SignMixin._sign_bg`(진행창 + 배경 스레드, 응답성 SOT §4). 여기서는 화면만 다룬다.
비밀번호는 칸에서 읽어 바로 넘기고 들고 있지 않는다(SOT §6.4).
"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QImage, QPainter, QPixmap, QColor
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSlider,
    QSpinBox, QVBoxLayout,
)

from viewer.i18n import tr, tr_noop

GOOGLE_PM_URL = "https://passwords.google.com"      # SOT §6.3 — 주소만 연다, 아무 값도 넘기지 않는다


def open_google_password_manager() -> None:
    QDesktopServices.openUrl(QUrl(GOOGLE_PM_URL))


def google_hint_label() -> QLabel:
    """2순위 안내(SOT §6.3) — Hello 를 못 쓸 때 비밀번호 칸 옆에."""
    lab = QLabel(tr("이 PC 에서는 Windows Hello 를 쓸 수 없습니다. 비밀번호를 Google 비밀번호 관리자에 "
                    "저장해 두고 복사해 붙여넣을 수 있습니다(Ctrl+V). 붙여넣은 비밀번호는 Windows "
                    "클립보드 기록(Win+V)에 남을 수 있습니다."))
    lab.setWordWrap(True)
    return lab


def google_button(parent=None) -> QPushButton:
    b = QPushButton(tr("Google 비밀번호 관리자 열기"), parent)
    b.setToolTip(tr("기본 브라우저로 passwords.google.com 을 엽니다 — PolyPDF 는 아무 값도 넘기지 않습니다."))
    b.clicked.connect(open_google_password_manager)
    return b


def _checker(w: int, h: int, cell: int = 8) -> QPixmap:
    pm = QPixmap(max(1, w), max(1, h))
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            if (x // cell + y // cell) % 2:
                p.fillRect(x, y, cell, cell, QColor("#e6e6e6"))
    p.end()
    return pm


def _pil_to_qimage(img) -> QImage:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    q = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return q.copy()


def _qimage_to_pil(q: QImage):
    from PIL import Image
    q = q.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = q.constBits()
    ptr.setsize(q.sizeInBytes())
    return Image.frombuffer("RGBA", (q.width(), q.height()), bytes(ptr), "raw", "RGBA", q.bytesPerLine(), 1).copy()


# ---------------------------------------------------------------------------
# 서명 그림 — SOT §3.1
# ---------------------------------------------------------------------------

class _DrawPad(QLabel):
    """손으로 그리기 칸(보안 SOT §3.6) — 투명 바탕 위에 마우스·펜으로 그린다(굵기 4)."""
    W, H, PEN = 600, 220, 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.W, self.H)
        self.setStyleSheet("QLabel{background:#ffffff;border:1px solid #c8c8c8;}")
        self.clear()
        self._last = None

    def clear(self):
        self.img = QImage(self.W, self.H, QImage.Format.Format_ARGB32_Premultiplied)
        self.img.fill(0)
        self.strokes = 0
        self.update()

    def _line(self, a, b):
        from PyQt6.QtGui import QPen
        p = QPainter(self.img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(10, 10, 40), self.PEN, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawLine(a, b)
        p.end()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._last = e.position()
            self._line(self._last, self._last)
            self.strokes += 1

    def mouseMoveEvent(self, e):
        if self._last is not None:
            pos = e.position()
            self._line(self._last, pos)
            self._last = pos

    def mouseReleaseEvent(self, e):
        self._last = None

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.drawImage(0, 0, self.img)
        p.end()


class _DrawDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("손으로 그리기"))
        v = QVBoxLayout(self)
        v.addWidget(QLabel(tr("마우스나 펜으로 서명을 그리세요.")))
        self.pad = _DrawPad(self)
        v.addWidget(self.pad)
        row = QHBoxLayout()
        b_clear = QPushButton(tr("지우기"))
        b_clear.clicked.connect(self.pad.clear)
        row.addWidget(b_clear)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        v.addLayout(row)

    def pil_image(self):
        return _qimage_to_pil(self.pad.img)


class SignImageDialog(QDialog):
    """불러오기 → 배경 지우기(자동 임계값) → 잉크 색 → 자르기 → 디지털 ID 의 서명 그림으로(261031-1 — ID 하나에 그림 하나).
    `fp` 를 주면 그 ID 에 바로 저장하고, 없으면(새 ID 만들기 창) 정리한 그림을 `result_image` 로만 돌려준다."""

    def __init__(self, parent=None, fp: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("서명 그림 넣기"))
        self._fp = str(fp or "")
        self._src = None            # PIL 원본
        self._out = None            # 정리한 RGBA
        self.result_image = None
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        b_open = QPushButton(tr("그림 불러오기…"))
        b_clip = QPushButton(tr("클립보드에서"))
        b_draw = QPushButton(tr("손으로 그리기…"))
        b_open.clicked.connect(self._open_file)
        b_clip.clicked.connect(self._from_clipboard)
        b_draw.clicked.connect(self._draw)
        row.addWidget(b_open)
        row.addWidget(b_clip)
        row.addWidget(b_draw)
        row.addStretch(1)
        v.addLayout(row)
        self.preview = QLabel(tr("종이에 한 서명을 찍은 사진이나 투명 PNG 를 불러오거나, 손으로 그리세요."))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 180)
        self.preview.setStyleSheet("QLabel{border:1px solid #c8c8c8;}")
        v.addWidget(self.preview, 1)
        form = QFormLayout()
        thr_row = QHBoxLayout()
        self.chk_auto = QCheckBox(tr("자동"))
        self.chk_auto.setChecked(True)
        self.sld = QSlider(Qt.Orientation.Horizontal)
        self.sld.setRange(30, 240)
        self.sld.setValue(160)
        self.sld.setEnabled(False)
        thr_row.addWidget(self.chk_auto)
        thr_row.addWidget(self.sld, 1)
        form.addRow(tr("배경 지우기"), thr_row)
        self.cmb_ink = QComboBox()
        for key, label in (("original", tr("원래 색")), ("black", tr("검정")), ("blue", tr("파랑"))):
            self.cmb_ink.addItem(label, key)
        form.addRow(tr("잉크 색"), self.cmb_ink)
        v.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        self._btn_save = bb.button(QDialogButtonBox.StandardButton.Save)
        self._btn_save.setEnabled(False)
        v.addWidget(bb)
        self.chk_auto.toggled.connect(lambda on: (self.sld.setEnabled(not on), self._update()))
        self.sld.valueChanged.connect(lambda _v: self._update())
        self.cmb_ink.currentIndexChanged.connect(lambda _i: self._update())
        self.resize(520, 420)

    def set_source(self, pil_img) -> None:
        self._src = pil_img
        try:
            from viewer import sign_core
            if not sign_core.has_transparency(pil_img.convert("RGBA")):
                self.sld.blockSignals(True)
                self.sld.setValue(sign_core.auto_threshold(pil_img))
                self.sld.blockSignals(False)
        except Exception:
            pass
        self._update()

    def _open_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, tr("서명 그림 불러오기"), "",
                                            tr("그림 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)"))
        if not fn:
            return
        try:
            from PIL import Image
            img = Image.open(fn)
            img.load()
        except Exception as e:
            QMessageBox.warning(self, tr("서명 그림"), tr("그림을 열지 못했습니다: {e}").format(e=type(e).__name__))
            return
        self.set_source(img)

    def _draw(self):
        dlg = _DrawDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.pad.strokes:
            return
        self.set_source(dlg.pil_image())

    def _from_clipboard(self):
        q = QApplication.clipboard().image()
        if q.isNull():
            QMessageBox.information(self, tr("서명 그림"), tr("클립보드에 그림이 없습니다."))
            return
        self.set_source(_qimage_to_pil(q))

    def _update(self):
        if self._src is None:
            return
        from viewer import sign_core
        thr = None if self.chk_auto.isChecked() else self.sld.value()
        self._out = sign_core.clean_signature(self._src.copy(), threshold=thr, ink=self.cmb_ink.currentData())
        ok = sign_core.ink_bbox(self._out) is not None
        self._btn_save.setEnabled(ok)
        q = _pil_to_qimage(self._out)
        w = max(1, self.preview.width() - 8)
        h = max(1, self.preview.height() - 8)
        pm = QPixmap.fromImage(q).scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
        bg = _checker(pm.width(), pm.height())
        p = QPainter(bg)
        p.drawPixmap(0, 0, pm)
        p.end()
        self.preview.setPixmap(bg)
        if not ok:
            self.preview.setToolTip(tr("잉크가 보이지 않습니다 — '자동' 을 끄고 배경 지우기 값을 조정하세요."))

    def _save(self):
        if self._out is None:
            return
        self.result_image = self._out
        if self._fp:
            from viewer import sign_store
            sign_store.set_id_image(self._fp, self._out)
        self.accept()


# ---------------------------------------------------------------------------
# 디지털 ID — SOT §3.2·§6.1
# ---------------------------------------------------------------------------

def _mm_spin(value: float) -> QDoubleSpinBox:
    from viewer import sign_store
    sp = QDoubleSpinBox()
    sp.setRange(sign_store.IMAGE_MM_MIN, sign_store.IMAGE_MM_MAX)
    sp.setDecimals(1)
    sp.setSingleStep(1.0)
    sp.setSuffix(" mm")
    sp.setValue(float(value))
    return sp


def _height_mm_text(width_mm: float, img) -> str:
    """폭 mm → 그림 비율의 높이 mm 글(보안 SOT §3.1 실제 크기, 261031-6)."""
    if img is None:
        return tr("(그림 없음)")
    w, h = img.size                              # PIL
    if not w or not h:
        return ""
    return tr("× 높이 {h:.1f} mm").format(h=float(width_mm) * h / w)


def _checker_preview(pil_img, height: int) -> QPixmap:
    pm = QPixmap.fromImage(_pil_to_qimage(pil_img)).scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    bg = _checker(pm.width(), pm.height())
    p = QPainter(bg)
    p.drawPixmap(0, 0, pm)
    p.end()
    return bg


class _CreateIdDialog(QDialog):
    """새 디지털 ID — `edit`(ID 항목)을 주면 **내용 고치기**(지금 값으로 채움 — 확인하면 새 인증서로 발급, 보안 SOT §3.2, 261031-6)."""

    def __init__(self, parent=None, hello_ok: bool = False, edit: dict | None = None):
        super().__init__(parent)
        self._edit = edit
        self.setWindowTitle(tr("디지털 ID 내용 고치기") if edit else tr("새 디지털 ID"))
        v = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_name = QLineEdit()
        self.ed_email = QLineEdit()
        self.ed_org = QLineEdit()
        self.sp_years = QSpinBox()
        self.sp_years.setRange(1, 20)
        from viewer.sign_core import ID_YEARS_DEFAULT
        self.sp_years.setValue(ID_YEARS_DEFAULT)
        self.sp_years.setSuffix(tr("년"))
        self.ed_pw = QLineEdit()
        self.ed_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_pw2 = QLineEdit()
        self.ed_pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self.lab_strength = QLabel("")
        form.addRow(tr("이름(필수)"), self.ed_name)
        form.addRow(tr("이메일"), self.ed_email)
        form.addRow(tr("조직"), self.ed_org)
        form.addRow(tr("유효기간"), self.sp_years)
        form.addRow(tr("비밀번호"), self.ed_pw)
        form.addRow(tr("비밀번호 확인"), self.ed_pw2)
        form.addRow("", self.lab_strength)
        v.addLayout(form)
        self.chk_hello = QCheckBox(tr("Windows Hello 로 비밀번호 보관(서명할 때 지문·PIN 으로 확인)"))
        self.chk_hello.setChecked(hello_ok)
        self.chk_hello.setVisible(hello_ok)
        v.addWidget(self.chk_hello)
        if not hello_ok:
            v.addWidget(google_hint_label())
            row = QHBoxLayout()
            row.addWidget(google_button(self))
            row.addStretch(1)
            v.addLayout(row)
        if edit:
            note = QLabel(tr("인증서에 서명된 내용은 바꿀 수 없어, 확인하면 새 인증서로 발급하고 기존 디지털 ID 는 지웁니다. "
                             "이미 서명한 문서는 그대로 유효합니다. 받는 사람에게 준 공개 인증서(.cer)는 다시 보내야 합니다. "
                             "비밀번호는 새로 넣으세요(전과 같아도 됩니다)."))
        else:
            note = QLabel(tr("직접 만든 디지털 ID 는 받는 사람의 PDF 뷰어에서 '신원 알 수 없음' 으로 보입니다. "
                             "받는 사람이 공개 인증서(.cer)를 신뢰 등록하면 '유효' 로 보입니다. "
                             "문서가 바뀌었는지는 신뢰 등록 없이도 드러납니다."))
        note.setWordWrap(True)
        v.addWidget(note)
        # 261031-1(사용자 지시): 디지털 ID 가 서명 그림도 갖는다 — 만들 때 아래 단추로 넣는다(나중에 관리 창에서 바꿀 수 있다)
        self.image = None
        img_row = QHBoxLayout()
        self.b_image = QPushButton(tr("서명 그림 넣기"))
        self.b_image.clicked.connect(self._pick_image)
        self.b_image_rm = QPushButton(tr("빼기"))
        self.b_image_rm.clicked.connect(self._drop_image)
        self.b_image_rm.setVisible(False)
        self.lab_image = QLabel(tr("(서명 그림 없음 — 글자만 찍힙니다)"))
        img_row.addWidget(self.b_image)
        img_row.addWidget(self.b_image_rm)
        img_row.addWidget(self.lab_image, 1)
        v.addLayout(img_row)
        # 261031-6(사용자 지시): 서명 그림의 실제 크기 — 폭 mm, 높이는 그림 비율(보안 SOT §3.1)
        from viewer import sign_store
        mm_row = QHBoxLayout()
        mm_row.addWidget(QLabel(tr("그림 실제 폭")))
        self.sp_mm = _mm_spin((edit or {}).get("image_mm", sign_store.IMAGE_MM_DEFAULT) if edit else sign_store.IMAGE_MM_DEFAULT)
        self.lab_h = QLabel("")
        mm_row.addWidget(self.sp_mm)
        mm_row.addWidget(self.lab_h, 1)
        v.addLayout(mm_row)
        self.sp_mm.valueChanged.connect(lambda _v: self._sync_h())
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.ed_pw.textChanged.connect(self._strength)
        if edit:
            self.ed_name.setText(str(edit.get("name", "")))
            self.ed_email.setText(str(edit.get("email", "")))
            self.ed_org.setText(str(edit.get("org", "")))
            self.chk_hello.setChecked(bool(edit.get("hello")) and hello_ok)
            ip = sign_store.id_image_path(str(edit.get("fp", "")))
            if ip:
                try:
                    from PIL import Image
                    with Image.open(ip) as im:
                        self._set_image(im.convert("RGBA"))
                except Exception:
                    pass
        self._sync_h()
        self.resize(460, 0)

    def _sync_h(self):
        self.lab_h.setText(_height_mm_text(self.sp_mm.value(), self.image))

    def _set_image(self, img):
        self.image = img
        if img is None:
            self.lab_image.setPixmap(QPixmap())
            self.lab_image.setText(tr("(서명 그림 없음 — 글자만 찍힙니다)"))
            self.b_image.setText(tr("서명 그림 넣기"))
        else:
            self.lab_image.setPixmap(_checker_preview(img, 40))
            self.b_image.setText(tr("서명 그림 바꾸기"))
        self.b_image_rm.setVisible(img is not None)
        self._sync_h()

    def _drop_image(self):
        self._set_image(None)

    def _pick_image(self):
        dlg = SignImageDialog(self)
        try:
            if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_image is None:
                return
            img = dlg.result_image
        finally:
            dlg.deleteLater()
        self._set_image(img)

    def _strength(self, t):
        from viewer.sign_core import password_weak, PASSWORD_MIN
        if not t:
            self.lab_strength.setText("")
        elif password_weak(t):
            self.lab_strength.setText(tr("약함 — {n}자 이상, 글자·숫자·기호를 섞으세요").format(n=PASSWORD_MIN))
        else:
            self.lab_strength.setText(tr("괜찮음"))

    def _ok(self):
        from viewer.sign_core import password_weak
        if not self.ed_name.text().strip():
            QMessageBox.information(self, self.windowTitle(), tr("이름을 넣으세요."))
            return
        if not self.ed_pw.text():
            QMessageBox.information(self, self.windowTitle(), tr("비밀번호를 넣으세요."))
            return
        if self.ed_pw.text() != self.ed_pw2.text():
            QMessageBox.information(self, self.windowTitle(), tr("두 비밀번호가 다릅니다."))
            return
        if password_weak(self.ed_pw.text()) and QMessageBox.question(
                self, self.windowTitle(),
                tr("비밀번호가 약합니다. .pfx 파일이 새어 나가면 쉽게 풀릴 수 있습니다. 그대로 만들까요?")
        ) != QMessageBox.StandardButton.Yes:
            return
        self.accept()


def _ask_password(parent, title: str, text: str) -> str | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    v = QVBoxLayout(dlg)
    lab = QLabel(text)
    lab.setWordWrap(True)
    v.addWidget(lab)
    ed = QLineEdit()
    ed.setEchoMode(QLineEdit.EchoMode.Password)
    v.addWidget(ed)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    v.addWidget(bb)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return ed.text()


class DigitalIdDialog(QDialog):
    """디지털 ID 관리 — 만들기·가져오기·백업·공개 인증서·기본·Hello 보관·서명 그림·지우기."""

    def __init__(self, parent=None, runner=None, hello_ok: bool = False, select_fp: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("디지털 ID 관리"))
        self.replaced = {}           # '내용 고치기' 로 바뀐 지문 {옛: 새} — 지금 서명에 잇는다(261031-7)
        self._run = runner or (lambda fn, _t: fn())
        self._hello_ok = bool(hello_ok)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.lst = QListWidget()
        top.addWidget(self.lst, 3)
        # 261031-6(사용자 지시): 고른 ID 의 내용을 그림까지 보이고, 그림 폭(mm)은 여기서 바로 고친다(보안 SOT §3.2 '관리 창 — 보기')
        det = QVBoxLayout()
        self.lab_pic = QLabel()
        self.lab_pic.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lab_pic.setMinimumHeight(76)
        det.addWidget(self.lab_pic)
        mm_row = QHBoxLayout()
        mm_row.addWidget(QLabel(tr("그림 실제 폭")))
        from viewer import sign_store as _ss
        self.sp_mm = _mm_spin(_ss.IMAGE_MM_DEFAULT)
        self.lab_h = QLabel("")
        mm_row.addWidget(self.sp_mm)
        mm_row.addWidget(self.lab_h, 1)
        det.addLayout(mm_row)
        info = QFormLayout()
        self.lab_info = {}
        for k, label in (("name", tr("이름")), ("email", tr("이메일")), ("org", tr("조직")), ("until", tr("유효기간")),
                         ("kind", tr("종류")), ("hello", tr("Windows Hello")), ("fp", tr("지문"))):
            lab = QLabel("")
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lab.setWordWrap(True)
            self.lab_info[k] = lab
            info.addRow(label, lab)
        det.addLayout(info)
        det.addStretch(1)
        top.addLayout(det, 4)
        v.addLayout(top, 1)
        self._img_pil = None
        self.sp_mm.valueChanged.connect(self._mm_changed)
        grid = QHBoxLayout()
        self.b_new = QPushButton(tr("새로 만들기…"))
        self.b_imp = QPushButton(tr("가져오기…"))
        self.b_bak = QPushButton(tr("백업 내보내기…"))
        self.b_cer = QPushButton(tr("공개 인증서 내보내기…"))
        for b in (self.b_new, self.b_imp, self.b_bak, self.b_cer):
            grid.addWidget(b)
        v.addLayout(grid)
        grid2 = QHBoxLayout()
        self.b_def = QPushButton(tr("기본으로"))
        self.b_hello = QPushButton(tr("Windows Hello 보관"))
        self.b_img = QPushButton(tr("서명 그림…"))          # 261031-1: 고른 ID 의 서명 그림 넣기·바꾸기·빼기
        self.b_edit = QPushButton(tr("내용 고치기…"))       # 261031-6: 만들 때 넣은 것을 모두 고침 = 새 인증서로 발급
        self.b_del = QPushButton(tr("지우기…"))
        for b in (self.b_def, self.b_hello, self.b_img, self.b_edit, self.b_del):
            grid2.addWidget(b)
        grid2.addStretch(1)
        v.addLayout(grid2)
        # 3단계(보안 SOT §3.8·§3.9): 공동인증서 · Windows 인증서 저장소
        grid3 = QHBoxLayout()
        self.b_npki = QPushButton(tr("공동인증서 가져오기…"))
        self.b_store = QPushButton(tr("Windows 인증서 저장소에서…"))
        from viewer import sign_winstore
        self.b_store.setVisible(sign_winstore.available())
        grid3.addWidget(self.b_npki)
        grid3.addWidget(self.b_store)
        grid3.addStretch(1)
        v.addLayout(grid3)
        self.b_npki.clicked.connect(self._import_npki)
        self.b_store.clicked.connect(self._import_store)
        self.b_hello.setVisible(self._hello_ok)
        if not self._hello_ok:
            v.addWidget(google_hint_label())
            r = QHBoxLayout()
            r.addWidget(google_button(self))
            r.addStretch(1)
            v.addLayout(r)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        bb.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        v.addWidget(bb)
        self.b_new.clicked.connect(self._create)
        self.b_imp.clicked.connect(self._import)
        self.b_bak.clicked.connect(self._backup)
        self.b_cer.clicked.connect(self._export_cer)
        self.b_def.clicked.connect(self._set_default)
        self.b_hello.clicked.connect(self._toggle_hello)
        self.b_img.clicked.connect(self._image)
        self.b_edit.clicked.connect(self._reissue)
        self.b_del.clicked.connect(self._delete)
        self.lst.currentRowChanged.connect(lambda _r: self._sync_buttons())
        self.resize(820, 420)
        self.refresh(select_fp)

    # ---- 목록 ----
    def refresh(self, select_fp: str = "") -> None:
        from viewer import sign_store
        d = sign_store.load()
        self.lst.clear()
        for e in d["ids"]:
            mark = "★ " if e.get("fp") == d.get("default_id") else "   "
            hello = "  · Windows Hello" if e.get("hello") else ""
            if e.get("kind") == "win":
                hello += tr("  · Windows 저장소")
            elif e.get("source") == "npki":
                hello += tr("  · 공동인증서")
            if sign_store.id_image_path(e.get("fp", "")):
                hello += tr("  · 서명 그림")
            mail = f" <{e['email']}>" if e.get("email") else ""
            it = QListWidgetItem(tr("{mark}{name}{mail} — ~{until}{hello}").format(
                mark=mark, name=e.get("name", ""), mail=mail, until=e.get("not_after", ""), hello=hello))
            it.setData(Qt.ItemDataRole.UserRole, e.get("fp"))
            it.setToolTip(tr("지문(SHA-256): {fp}").format(fp=e.get("fp", "")))
            self.lst.addItem(it)
            if select_fp and e.get("fp") == select_fp:
                self.lst.setCurrentItem(it)
        if self.lst.currentRow() < 0 and self.lst.count():
            self.lst.setCurrentRow(0)
        self._sync_buttons()

    def _fp(self) -> str:
        it = self.lst.currentItem()
        return str(it.data(Qt.ItemDataRole.UserRole)) if it else ""

    @staticmethod
    def _kind_text(e: dict) -> str:
        if e.get("kind") == "win":
            return tr("Windows 인증서 저장소")
        if e.get("source") == "npki":
            return tr("공동인증서")
        if e.get("self_made"):
            return tr("직접 만든 디지털 ID")
        return tr("가져온 디지털 ID(.pfx)")

    @staticmethod
    def _can_reissue(e: dict) -> bool:
        """고치기(새로 발급) 후보 — 기관 인증서(공동인증서·Windows 저장소)는 아니다. 가져온 .pfx 는 열어 본 뒤 자체 서명만."""
        return bool(e) and e.get("kind") != "win" and e.get("source") != "npki"

    def _show_detail(self):
        from viewer import sign_store
        fp = self._fp()
        e = sign_store.get_id(fp) or {}
        self._img_pil = None
        ip = sign_store.id_image_path(fp) if fp else ""
        if ip:
            try:
                from PIL import Image
                with Image.open(ip) as im:
                    self._img_pil = im.convert("RGBA")
            except Exception:
                self._img_pil = None
        if self._img_pil is not None:
            self.lab_pic.setPixmap(_checker_preview(self._img_pil, 70))
        else:
            self.lab_pic.setPixmap(QPixmap())
            self.lab_pic.setText(tr("(서명 그림 없음 — [서명 그림…] 으로 넣으세요)") if fp else "")
        self.sp_mm.blockSignals(True)
        self.sp_mm.setValue(sign_store.id_image_mm(fp) if fp else sign_store.IMAGE_MM_DEFAULT)
        self.sp_mm.blockSignals(False)
        self.sp_mm.setEnabled(bool(fp))
        self.lab_h.setText(_height_mm_text(self.sp_mm.value(), self._img_pil) if fp else "")
        vals = {"name": e.get("name", ""), "email": e.get("email", ""), "org": e.get("org", ""),
                "until": ("~ " + e["not_after"]) if e.get("not_after") else "",
                "kind": self._kind_text(e) if e else "",
                "hello": (tr("보관함") if e.get("hello") else tr("보관 안 함")) if e else "",
                "fp": fp}
        for k, lab in self.lab_info.items():
            lab.setText(str(vals.get(k, "")))

    def _mm_changed(self, val):
        fp = self._fp()
        if not fp:
            return
        from viewer import sign_store
        sign_store.set_id_image_mm(fp, val)
        self.lab_h.setText(_height_mm_text(val, self._img_pil))

    def _sync_buttons(self):
        has = bool(self._fp())
        for b in (self.b_bak, self.b_cer, self.b_def, self.b_hello, self.b_img, self.b_edit, self.b_del):
            b.setEnabled(has)
        self._show_detail()
        if has:
            from viewer import sign_store
            e = sign_store.get_id(self._fp()) or {}
            win = e.get("kind") == "win"
            self.b_bak.setEnabled(not win)           # 키가 Windows 안에 있다(SOT §3.9)
            self.b_hello.setEnabled(not win)
            self.b_edit.setEnabled(self._can_reissue(e))
            self.b_edit.setToolTip("" if self._can_reissue(e) else
                                   tr("기관이 발급한 인증서는 고칠 수 없습니다 — 서명 그림·그림 폭만 바꿀 수 있습니다."))
        if has and self._hello_ok:
            from viewer import sign_store
            e = sign_store.get_id(self._fp()) or {}
            self.b_hello.setText(tr("Windows Hello 보관 해제") if e.get("hello") else tr("Windows Hello 보관"))

    # ---- 동작 ----
    def _store_hello(self, fp: str, password: str) -> bool:
        from viewer import sign_hello, sign_store
        try:
            self._run(lambda: sign_hello.store(fp, password), tr("Windows Hello 확인"))
        except sign_hello.HelloCancelled:
            return False
        except Exception as e:
            QMessageBox.warning(self, tr("Windows Hello"),
                                tr("Windows Hello 로 보관하지 못했습니다({e}). 서명할 때 비밀번호를 입력합니다.").format(e=e))
            return False
        sign_store.set_id_flag(fp, hello=True)
        return True

    def _create(self):
        dlg = _CreateIdDialog(self, hello_ok=self._hello_ok)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        from viewer import sign_core, sign_store
        pw = dlg.ed_pw.text()
        try:
            pfx, info = self._run(lambda: sign_core.create_id(
                dlg.ed_name.text(), pw, email=dlg.ed_email.text(), org=dlg.ed_org.text(),
                years=dlg.sp_years.value()), tr("디지털 ID 만드는 중"))
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), tr("디지털 ID 를 만들지 못했습니다: {e}").format(e=type(e).__name__))
            return
        sign_store.add_id(pfx, info, self_made=True)
        if dlg.image is not None:
            sign_store.set_id_image(info.fp, dlg.image)
        sign_store.set_id_image_mm(info.fp, dlg.sp_mm.value())
        if self._hello_ok and dlg.chk_hello.isChecked():
            self._store_hello(info.fp, pw)
        self.refresh(info.fp)
        QMessageBox.information(self, self.windowTitle(),
                                tr("디지털 ID 를 만들었습니다. '백업 내보내기' 로 .pfx 를 안전한 곳에 백업해 두세요 — "
                                   "이 PC 가 고장 나면 같은 ID 로 다시 서명할 수 없습니다."))

    def _import(self):
        fn, _ = QFileDialog.getOpenFileName(self, tr("디지털 ID 가져오기"), "", tr("디지털 ID (*.pfx *.p12)"))
        if not fn:
            return
        pw = _ask_password(self, tr("디지털 ID 가져오기"), tr("{name} 의 비밀번호").format(name=os.path.basename(fn)))
        if pw is None:
            return
        from viewer import sign_core, sign_store
        try:
            data = open(fn, "rb").read()
            pfx, info = self._run(lambda: sign_core.normalize_pfx(data, pw), tr("디지털 ID 확인 중"))
        except sign_core.WrongPassword:
            QMessageBox.warning(self, self.windowTitle(), tr("비밀번호가 맞지 않거나 디지털 ID 파일이 아닙니다."))
            return
        except sign_core.SignError as e:
            msg = {"no_key": tr("개인 키가 없는 인증서입니다 — 서명에 쓸 수 없습니다."),
                   "bad_usage": tr("문서 서명 용도가 아닌 인증서입니다.")}.get(e.reason, str(e))
            QMessageBox.warning(self, self.windowTitle(), msg)
            return
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), tr("가져오지 못했습니다: {e}").format(e=type(e).__name__))
            return
        sign_store.add_id(pfx, info)
        if self._hello_ok and QMessageBox.question(
                self, self.windowTitle(), tr("이 디지털 ID 의 비밀번호를 Windows Hello 로 보관할까요?")
        ) == QMessageBox.StandardButton.Yes:
            self._store_hello(info.fp, pw)
        self.refresh(info.fp)

    def _backup(self):
        from viewer import sign_store
        fp = self._fp()
        e = sign_store.get_id(fp) or {}
        fn, _ = QFileDialog.getSaveFileName(self, tr("디지털 ID 백업"), f"{e.get('name', 'id')}.pfx", tr("디지털 ID (*.pfx)"))
        if not fn:
            return
        try:
            with open(fn, "wb") as f:
                f.write(sign_store.read_pfx(fp))
        except Exception as ex:
            QMessageBox.warning(self, self.windowTitle(), tr("저장하지 못했습니다: {e}").format(e=type(ex).__name__))
            return
        QMessageBox.information(self, self.windowTitle(), tr("백업했습니다(비밀번호는 같습니다)."))

    def _export_cer(self):
        from viewer import sign_core, sign_store
        fp = self._fp()
        e = sign_store.get_id(fp) or {}
        if e.get("kind") == "win":
            try:
                der = sign_store.abspath(e["cert"]).read_bytes()
            except Exception as ex:
                QMessageBox.warning(self, self.windowTitle(), tr("인증서를 읽지 못했습니다: {e}").format(e=type(ex).__name__))
                return
        else:
            pw = self._password_for(fp)
            if pw is None:
                return
            try:
                der = self._run(lambda: sign_core.cert_der(sign_store.read_pfx(fp), pw), tr("인증서 읽는 중"))
            except sign_core.WrongPassword:
                QMessageBox.warning(self, self.windowTitle(), tr("비밀번호가 맞지 않습니다."))
                return
        fn, _ = QFileDialog.getSaveFileName(self, tr("공개 인증서 내보내기"), f"{e.get('name', 'id')}.cer", tr("인증서 (*.cer)"))
        if not fn:
            return
        with open(fn, "wb") as f:
            f.write(der)
        QMessageBox.information(self, self.windowTitle(),
                                tr("받는 사람이 이 .cer 를 PDF 뷰어(Acrobat: 서명 패널 → 인증서 → 신뢰할 수 있는 인증서에 추가)에 "
                                   "등록하면 서명이 '유효' 로 보입니다."))

    def _password_for(self, fp: str):
        """Hello 보관이면 Hello 로, 아니면 묻는다."""
        from viewer import sign_hello, sign_store
        e = sign_store.get_id(fp) or {}
        if e.get("hello") and self._hello_ok:
            try:
                return self._run(lambda: sign_hello.recall(fp), tr("Windows Hello 확인"))
            except sign_hello.HelloCancelled:
                pass
            except Exception:
                pass
        return _ask_password(self, self.windowTitle(), tr("{name} 의 비밀번호").format(name=e.get("name", "")))

    def _import_npki(self):
        """공동인증서 — 찾은 목록에서 고르고 비밀번호로 풀어 우리 형식으로 복사(SOT §3.8)."""
        from viewer import sign_core, sign_npki, sign_store
        try:
            found = self._run(sign_npki.find, tr("공동인증서 찾는 중"))
        except Exception:
            found = []
        dlg = NpkiDialog(self, found, runner=self._run)
        try:
            if dlg.exec() != QDialog.DialogCode.Accepted or dlg.chosen is None:
                return
            c, pw = dlg.chosen, dlg.password()
        finally:
            dlg.deleteLater()        # 비밀번호 칸을 남겨 두지 않는다(SOT §6.4, 261011-1)
        try:
            pfx, info = self._run(lambda: sign_npki.to_pfx(c.cert_path, c.key_path, pw), tr("공동인증서 확인 중"))
        except sign_core.WrongPassword:
            QMessageBox.warning(self, self.windowTitle(), tr("인증서 비밀번호가 맞지 않습니다."))
            return
        except sign_core.SignError as e:
            QMessageBox.warning(self, self.windowTitle(), npki_error_text(e))
            return
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), tr("가져오지 못했습니다: {e}").format(e=type(e).__name__))
            return
        sign_store.add_id(pfx, info, source="npki")
        if self._hello_ok and QMessageBox.question(
                self, self.windowTitle(), tr("이 디지털 ID 의 비밀번호를 Windows Hello 로 보관할까요?")
        ) == QMessageBox.StandardButton.Yes:
            self._store_hello(info.fp, pw)
        self.refresh(info.fp)
        QMessageBox.information(self, self.windowTitle(),
                                tr("공동인증서를 가져왔습니다(원래 인증서 폴더는 그대로입니다). 받는 쪽 PDF 뷰어에 발급기관 인증서가 "
                                   "신뢰 등록돼 있지 않으면 서명이 '신원 미확인' 으로 보일 수 있습니다."))

    def _import_store(self):
        """Windows 인증서 저장소 — 키는 복사하지 않고 참조만(SOT §3.9)."""
        from viewer import sign_store, sign_winstore
        try:
            certs = self._run(sign_winstore.list_certs, tr("인증서 저장소 읽는 중"))
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), tr("Windows 인증서 저장소를 읽지 못했습니다: {e}").format(
                e=getattr(e, "detail", "") or type(e).__name__))
            return
        dlg = StoreCertDialog(self, certs)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.chosen is None:
            return
        sign_store.add_win_id(dlg.chosen)
        self.refresh(dlg.chosen.fp)

    def _image(self):
        """고른 ID 의 서명 그림 — 넣기·바꾸기, 있으면 빼기도(261031-1, ID 하나에 그림 하나)."""
        from viewer import sign_store
        fp = self._fp()
        if not fp:
            return
        if sign_store.id_image_path(fp):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(tr("서명 그림"))
            box.setText(tr("이 디지털 ID 에는 서명 그림이 있습니다."))
            b_new = box.addButton(tr("바꾸기…"), QMessageBox.ButtonRole.AcceptRole)
            b_rm = box.addButton(tr("빼기"), QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            c = box.clickedButton()
            if c is b_rm:
                sign_store.clear_id_image(fp)
                self.refresh(fp)
                return
            if c is not b_new:
                return
        dlg = SignImageDialog(self, fp=fp)
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()
        self.refresh(fp)

    def _reissue(self):
        """내용 고치기 = 새 인증서로 발급하고 기존 ID 를 지운다(사용자 결정 261031-6, 보안 SOT §3.2).
        기존 비밀번호(또는 Hello)로 자체 서명 인증서인지 확인 → 지금 값으로 채운 만들기 창 → 확인 → `replace_id`."""
        from viewer import sign_core, sign_store
        fp = self._fp()
        e = sign_store.get_id(fp) or {}
        title = tr("디지털 ID 내용 고치기")
        if not self._can_reissue(e):
            QMessageBox.information(self, title, tr("기관이 발급한 인증서는 고칠 수 없습니다 — 서명 그림·그림 폭만 바꿀 수 있습니다."))
            return
        pw = self._password_for(fp)
        if pw is None:
            return
        try:
            own = self._run(lambda: sign_core.pfx_self_signed(sign_store.read_pfx(fp), pw), tr("비밀번호 확인 중"))
        except sign_core.WrongPassword:
            QMessageBox.warning(self, title, tr("비밀번호가 맞지 않습니다."))
            return
        except Exception as ex:
            QMessageBox.warning(self, title, tr("디지털 ID 를 열지 못했습니다: {e}").format(e=type(ex).__name__))
            return
        finally:
            pw = None
        if not own:
            QMessageBox.information(self, title, tr("기관이 발급한 인증서는 고칠 수 없습니다 — 서명 그림·그림 폭만 바꿀 수 있습니다."))
            return
        dlg = _CreateIdDialog(self, hello_ok=self._hello_ok, edit=dict(e, image_mm=sign_store.id_image_mm(fp)))
        try:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(title)
            box.setText(tr("새 인증서로 발급하고 기존 디지털 ID '{name}' 은 지웁니다. 이미 서명한 문서는 그대로 유효합니다"
                           "(옛 인증서는 신뢰 목록에 남습니다). 받는 사람에게 준 공개 인증서(.cer)는 다시 보내야 합니다.").format(name=e.get("name", "")))
            b_bak = box.addButton(tr("백업 후 고치기…"), QMessageBox.ButtonRole.AcceptRole)
            b_go = box.addButton(tr("고치기"), QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            c = box.clickedButton()
            if c is b_bak:
                self._backup()
            elif c is not b_go:
                return
            new_pw = dlg.ed_pw.text()
            try:
                pfx, info = self._run(lambda: sign_core.create_id(
                    dlg.ed_name.text(), new_pw, email=dlg.ed_email.text(), org=dlg.ed_org.text(),
                    years=dlg.sp_years.value()), tr("디지털 ID 만드는 중"))
            except Exception as ex:
                QMessageBox.warning(self, title, tr("디지털 ID 를 만들지 못했습니다: {e}").format(e=type(ex).__name__))
                return
            # 창의 그림 = 옛 그림으로 채워 두었다 — 그대로·바꿈·뺌(None) 모두 창 값대로
            sign_store.replace_id(fp, pfx, info, image=dlg.image, keep_image=False, image_mm=dlg.sp_mm.value())
            self.replaced[fp] = info.fp
            if self._hello_ok and dlg.chk_hello.isChecked():
                self._store_hello(info.fp, new_pw)
            new_pw = None
        finally:
            dlg.deleteLater()        # 비밀번호 칸을 남겨 두지 않는다(SOT §6.4)
        self.refresh(info.fp)
        QMessageBox.information(self, title, tr("새 디지털 ID 로 바꿨습니다. '백업 내보내기' 로 새 .pfx 를 백업해 두세요."))

    def _set_default(self):
        from viewer import sign_store
        d = sign_store.load()
        d["default_id"] = self._fp()
        sign_store.save(d)
        self.refresh(self._fp())

    def _toggle_hello(self):
        from viewer import sign_core, sign_hello, sign_store
        fp = self._fp()
        e = sign_store.get_id(fp) or {}
        if e.get("hello"):
            sign_hello.forget(fp)
            sign_store.set_id_flag(fp, hello=False)
            self.refresh(fp)
            return
        pw = _ask_password(self, tr("Windows Hello 보관"), tr("{name} 의 비밀번호 — 맞는지 확인한 뒤 Windows Hello 로 잠가 둡니다.").format(name=e.get("name", "")))
        if pw is None:
            return
        try:
            self._run(lambda: sign_core.load_pfx(sign_store.read_pfx(fp), pw), tr("비밀번호 확인 중"))
        except sign_core.WrongPassword:
            QMessageBox.warning(self, self.windowTitle(), tr("비밀번호가 맞지 않습니다."))
            return
        self._store_hello(fp, pw)
        self.refresh(fp)

    def _delete(self):
        from viewer import sign_store
        fp = self._fp()
        e = sign_store.get_id(fp) or {}
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("디지털 ID 지우기"))
        box.setText(tr("'{name}' 을 지우면 이 ID 로 다시 서명할 수 없습니다. 이미 서명한 문서는 그대로 유효합니다.").format(name=e.get("name", "")))
        b_bak = box.addButton(tr("백업 후 지우기…"), QMessageBox.ButtonRole.AcceptRole)
        b_del = box.addButton(tr("지우기"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("취소"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c is b_bak:
            self._backup()
        elif c is not b_del:
            return
        sign_store.remove_id(fp)
        self.refresh()


def npki_error_text(e) -> str:
    return {"expired": tr("만료된 인증서입니다 — 서명해도 검증에서 무효가 됩니다."),
            "not_yet": tr("아직 유효기간이 시작되지 않은 인증서입니다."),
            "bad_usage": tr("문서 서명 용도가 아닌 인증서입니다."),
            "key_mismatch": tr("개인 키와 인증서가 짝이 맞지 않습니다(signCert.der·signPri.key 가 같은 폴더의 것인지 확인하세요)."),
            "unsupported_cipher": tr("이 인증서의 개인 키 암호 방식은 지원하지 않습니다({oid}).").format(oid=getattr(e, "detail", "")),
            "unreadable": tr("인증서 파일을 읽지 못했습니다.")}.get(getattr(e, "reason", ""), str(e))


_WHY = {"expired": tr_noop("만료"), "not_yet": tr_noop("유효 전"), "bad_usage": tr_noop("서명 용도 아님"),
        "unreadable": tr_noop("읽을 수 없음")}


class NpkiDialog(QDialog):
    """공동인증서 고르기 — 찾은 목록 + [폴더 고르기…] + 인증서 비밀번호(보안 SOT §3.8)."""

    def __init__(self, parent=None, found=(), runner=None):
        super().__init__(parent)
        self._run = runner or (lambda fn, _t: fn())
        self.setWindowTitle(tr("공동인증서 가져오기"))
        self.chosen = None
        v = QVBoxLayout(self)
        lab = QLabel(tr("가져올 인증서를 고르세요. 원래 인증서 폴더는 건드리지 않고 PolyPDF 디지털 ID 로 복사합니다."))
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.lst = QListWidget()
        v.addWidget(self.lst, 1)
        self._items = []
        for c in found:
            self._add(c)
        if not self._items:
            self.lst.addItem(QListWidgetItem(tr("(찾은 공동인증서가 없습니다 — [폴더 고르기…] 로 signCert.der 가 있는 폴더를 고르세요)")))
            self.lst.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        r = QHBoxLayout()
        b_dir = QPushButton(tr("폴더 고르기…"))
        b_dir.clicked.connect(self._pick_dir)
        r.addWidget(b_dir)
        r.addStretch(1)
        v.addLayout(r)
        form = QFormLayout()
        self.ed_pw = QLineEdit()
        self.ed_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_pw.setPlaceholderText(tr("인증서 비밀번호"))
        form.addRow(tr("비밀번호"), self.ed_pw)
        v.addLayout(form)
        note = QLabel(tr("가져온 디지털 ID 의 비밀번호는 인증서 비밀번호와 같습니다."))
        note.setWordWrap(True)
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(560, 380)
        for i in range(self.lst.count()):
            if self.lst.item(i).flags() & Qt.ItemFlag.ItemIsEnabled:
                self.lst.setCurrentRow(i)
                break

    def _add(self, c):
        why = tr(_WHY.get(c.why, c.why)) if c.why else ""
        text = tr("{name} — {issuer} · ~{until}").format(name=c.name, issuer=c.issuer or "?", until=c.not_after or "?")
        if why:
            text += f"  ({why})"
        it = QListWidgetItem(text)
        it.setToolTip(c.folder)
        if not c.usable:
            it.setFlags(Qt.ItemFlag.NoItemFlags)       # 흐리게, 고를 수 없게
        self.lst.addItem(it)
        self._items.append((it, c))
        return it

    def _pick_dir(self):
        from viewer import sign_npki
        d = QFileDialog.getExistingDirectory(self, tr("signCert.der 가 있는 폴더"))
        if not d:
            return
        try:
            got = self._run(lambda: sign_npki.find([d]), tr("공동인증서 찾는 중"))   # 폴더 훑기는 배경(SOT §10)
        except Exception:
            got = []
        if not got:
            QMessageBox.information(self, self.windowTitle(), tr("이 폴더(와 그 아래 기관·USER 폴더)에서 signCert.der·signPri.key 짝을 찾지 못했습니다."))
            return
        if self._items == [] and self.lst.count() == 1:
            self.lst.clear()
        first = None
        for c in got:
            it = self._add(c)
            first = first or (it if c.usable else None)
        if first is not None:
            self.lst.setCurrentItem(first)

    def password(self) -> str:
        return self.ed_pw.text()

    def _ok(self):
        it = self.lst.currentItem()
        c = next((c for i, c in self._items if i is it), None)
        if c is None or not c.usable:
            QMessageBox.information(self, self.windowTitle(), tr("가져올 인증서를 고르세요."))
            return
        if not self.ed_pw.text():
            QMessageBox.information(self, self.windowTitle(), tr("비밀번호를 넣으세요."))
            return
        self.chosen = c
        self.accept()


class SigFieldDialog(QDialog):
    """빈 서명 칸 설정 — 이름 · 서명할 사람(누구나 / 인증서로 지정) · 서명하면 모든 칸 잠금(보안 SOT §3.7)."""

    def __init__(self, parent=None, default_name: str = "Signature1", used=()):
        super().__init__(parent)
        self.setWindowTitle(tr("빈 서명 칸"))
        self._used = set(used)
        self.cert_der = b""
        v = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_name = QLineEdit(default_name)
        self.ed_name.setPlaceholderText(tr("예: 검토자, 승인자"))
        form.addRow(tr("칸 이름"), self.ed_name)
        from PyQt6.QtWidgets import QWidget
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.cmb_who = QComboBox()
        self.cmb_who.addItem(tr("누구나"), "any")
        self.cmb_who.addItem(tr("인증서로 지정…"), "cert")
        self.lab_who = QLabel("")
        rl.addWidget(self.cmb_who)
        rl.addWidget(self.lab_who, 1)
        form.addRow(tr("서명할 사람"), row)
        self.chk_lock = QCheckBox(tr("이 칸에 서명하면 문서의 모든 칸을 잠금"))
        self.chk_lock.setToolTip(tr("잠긴 뒤에는 양식 채우기와 다른 서명 칸 서명도 '변경' 이 됩니다 — 마지막 서명 칸에 쓰세요."))
        form.addRow(tr("잠금"), self.chk_lock)
        v.addLayout(form)
        note = QLabel(tr("잠금은 마지막 서명 칸에 쓰세요 — 잠긴 뒤에는 다른 칸에 서명할 수 없습니다. "
                         "서명할 사람은 그 사람이 보낸 공개 인증서(.cer)로 정합니다."))
        note.setWordWrap(True)
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.cmb_who.activated.connect(self._who)
        self.resize(460, 0)

    def _who(self, _i=0):
        if self.cmb_who.currentData() != "cert":
            self.cert_der = b""
            self.lab_who.setText("")
            return
        fn, _ = QFileDialog.getOpenFileName(self, tr("서명할 사람의 공개 인증서"), "", tr("인증서 (*.cer *.crt *.der *.pem)"))
        if not self.load_cert(fn):
            self.cmb_who.setCurrentIndex(0)
            self.lab_who.setText("")

    def load_cert(self, fn: str) -> bool:
        """인증서 파일을 읽어 지정한다(DER·PEM). 못 읽으면 False."""
        if not fn:
            return False
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import serialization
            raw = open(fn, "rb").read()
            try:
                c = x509.load_der_x509_certificate(raw)
            except ValueError:
                c = x509.load_pem_x509_certificate(raw)
            from viewer import sign_core
            self.cert_der = c.public_bytes(serialization.Encoding.DER)
            self.lab_who.setText(sign_core._cert_info(c).name)
            self.cmb_who.setCurrentIndex(1)
            return True
        except Exception:
            QMessageBox.warning(self, self.windowTitle(), tr("인증서 파일을 읽지 못했습니다."))
            return False

    def name(self) -> str:
        return self.ed_name.text().strip()

    def _ok(self):
        if not self.name():
            QMessageBox.information(self, self.windowTitle(), tr("칸 이름을 넣으세요."))
            return
        if self.name() in self._used:
            QMessageBox.information(self, self.windowTitle(), tr("같은 이름의 서명 칸이 이미 있습니다: {name}").format(name=self.name()))
            return
        if self.cmb_who.currentData() == "cert" and not self.cert_der:
            QMessageBox.information(self, self.windowTitle(), tr("서명할 사람의 인증서를 고르세요."))
            return
        self.accept()


class StoreCertDialog(QDialog):
    """Windows 인증서 저장소('개인')에서 개인 키가 딸린 인증서 고르기(보안 SOT §3.9)."""

    def __init__(self, parent=None, certs=()):
        super().__init__(parent)
        self.setWindowTitle(tr("Windows 인증서 저장소"))
        self.chosen = None
        v = QVBoxLayout(self)
        lab = QLabel(tr("서명에 쓸 인증서를 고르세요. 키는 복사하지 않습니다 — 서명할 때 Windows 가 PIN·확인을 물을 수 있습니다."))
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.lst = QListWidget()
        v.addWidget(self.lst, 1)
        self._items = []
        for c in certs:
            text = tr("{name} — {issuer} · ~{until}").format(name=c.name, issuer=c.issuer or "?", until=c.not_after or "?")
            if c.hardware:
                text += tr("  · 스마트카드")
            if c.why:
                text += f"  ({tr(_WHY.get(c.why, c.why))})"
            it = QListWidgetItem(text)
            it.setToolTip(tr("지문(SHA-1): {fp}").format(fp=c.thumb))
            if not c.usable:
                it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.lst.addItem(it)
            self._items.append((it, c))
        if not self._items:
            it = QListWidgetItem(tr("(개인 키가 딸린 인증서가 없습니다)"))
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.lst.addItem(it)
        else:
            for it, c in self._items:
                if c.usable:
                    self.lst.setCurrentItem(it)
                    break
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(560, 340)

    def _ok(self):
        it = self.lst.currentItem()
        c = next((c for i, c in self._items if i is it), None)
        if c is None or not c.usable:
            QMessageBox.information(self, self.windowTitle(), tr("인증서를 고르세요."))
            return
        self.chosen = c
        self.accept()


# ---------------------------------------------------------------------------
# 서명 시작 확인 — SOT §3.3·§6 (261031-1)
# ---------------------------------------------------------------------------

class SignUnlockDialog(QDialog):
    """서명을 시작할 때 한 번 — 비밀번호(붙여넣기 가능) 또는 Windows Hello 로 디지털 ID 를 연다.
    비밀번호는 맞는 ID 를 모두 연다(쓸 수 있는 ID), Hello 는 기본 ID(없으면 Hello 로 보관한 첫 ID) 하나를 연다.
    연 열쇠는 서명 확정·취소까지만 앱이 들고 있다(SOT §6.4). 결과: `mode` = "hello" | "password"."""

    def __init__(self, parent=None, hello_ok: bool = False, hello_name: str = "", n_ids: int = 0):
        super().__init__(parent)
        self.setWindowTitle(tr("서명 — 본인 확인"))
        self.mode = ""
        v = QVBoxLayout(self)
        lab = QLabel(tr("서명에 쓸 디지털 ID 를 엽니다(이 PC 의 디지털 ID {n}개). 비밀번호가 맞는 ID 로 서명하고, "
                        "여럿이면 기본 ID(없으면 첫 ID)로 시작합니다 — 서명 자리 우클릭에서 바꿀 수 있습니다.").format(n=n_ids))
        lab.setWordWrap(True)
        v.addWidget(lab)
        self.btn_hello = QPushButton(tr("Windows Hello 로 확인 — {name}").format(name=hello_name) if hello_name
                                     else tr("Windows Hello 로 확인"))
        self.btn_hello.setVisible(bool(hello_ok and hello_name))
        self.btn_hello.clicked.connect(self._hello)
        v.addWidget(self.btn_hello)
        form = QFormLayout()
        self.ed_pw = QLineEdit()
        self.ed_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_pw.setPlaceholderText(tr("디지털 ID 비밀번호(붙여넣기 가능)"))
        form.addRow(tr("비밀번호"), self.ed_pw)
        v.addLayout(form)
        if not hello_ok:
            v.addWidget(google_hint_label())
            r = QHBoxLayout()
            r.addWidget(google_button(self))
            r.addStretch(1)
            v.addLayout(r)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        if self.btn_hello.isVisible():
            self.btn_hello.setDefault(True)
            self.btn_hello.setFocus()
        else:
            self.ed_pw.setFocus()
        self.resize(440, 0)

    def password(self) -> str:
        return self.ed_pw.text()

    def _hello(self):
        self.mode = "hello"
        self.accept()

    def _ok(self):
        if not self.ed_pw.text():
            if self.btn_hello.isVisible():
                self._hello()
                return
            QMessageBox.information(self, self.windowTitle(), tr("비밀번호를 넣으세요."))
            return
        self.mode = "password"
        self.accept()


# ---------------------------------------------------------------------------
# 서명 창 — SOT §3.3
# ---------------------------------------------------------------------------

class SignDialog(QDialog):
    """서명 확정 창 — 디지털 ID(서명을 시작할 때 연 것만)·서명 그림(그 ID 의 것, 켜고 끔)·겉모양 글자·사유 → [서명 확정] / [다른 이름으로…].
    비밀번호는 묻지 않는다 — 서명을 시작할 때 한 번 확인했다(261031-1, SOT §3.3·§6). 그림·글자를 모두 끄면 확정하지 않는다.
    첫 서명 자리 크기(그림 상자 + 아래 글자 줄)로 실제 겉모양을 미리 보인다(보안 SOT §3.3·§3.10)."""

    PREVIEW_DELAY_MS = 250
    PREVIEW_MAX = (360, 150)
    PREVIEW_DPI = 110

    def __init__(self, parent=None, file_name: str = "", box_size=(142.0, 57.0),
                 page_count: int = 1, current_page: int = 0, can_certify: bool = True, field_name: str = "",
                 field_signers=(), field_lock: bool = False, summary: str = "", out_name: str = "",
                 box_is_field: bool = False, ids=None, cur_fp: str = ""):
        super().__init__(parent)
        from viewer import sign_store
        self.setWindowTitle(tr("전자서명 — {name}").format(name=file_name) if file_name else tr("전자서명"))
        self.save_as = False
        self.field_name = str(field_name or "")      # 3단계(보안 SOT §3.7): 빈 서명 칸 채우기
        self.summary = str(summary or "")
        self._box_is_field = bool(box_is_field or self.field_name)   # 칸 크기 그대로(글자 줄을 덧붙이지 않는다)
        d = sign_store.load()
        v = QVBoxLayout(self)
        if summary:
            lab = QLabel(summary)                  # 261012-1(보안 SOT §3.10): 확정할 자리 요약
            lab.setWordWrap(True)
            v.addWidget(lab)
        form = QFormLayout()
        if self.field_name:
            form.addRow(tr("서명 칸"), QLabel(tr("{name} (p.{page})").format(name=self.field_name, page=int(current_page) + 1)))
            if field_signers:
                form.addRow(tr("서명할 사람"), QLabel(", ".join(field_signers)))
            if field_lock:
                form.addRow(tr("잠금"), QLabel(tr("서명하면 문서의 모든 칸이 잠깁니다")))
        self.cmb_id = QComboBox()
        allow = None if ids is None else {str(x) for x in ids}
        for e in d["ids"]:
            if allow is not None and e.get("fp") not in allow:
                continue                          # 서명을 시작할 때 열지 못한 ID 는 고를 수 없다(261031-1)
            self.cmb_id.addItem(f"{e.get('name', '')}" + (f" <{e['email']}>" if e.get("email") else ""), e.get("fp"))
        i = self.cmb_id.findData(cur_fp or d.get("default_id"))
        if i >= 0:
            self.cmb_id.setCurrentIndex(i)
        form.addRow(tr("디지털 ID"), self.cmb_id)
        ap = d.get("appearance") or {}
        # 줄 하나짜리 묶음 — QGroupBox 는 줄바꿈 라벨이 있는 창에서 높이를 못 받아 빈 막대로 눌렸다(화면 확인)
        from PyQt6.QtWidgets import QWidget
        g = QWidget()
        gl = QHBoxLayout(g)
        gl.setContentsMargins(0, 0, 0, 0)
        # 261031-1(사용자 지시): 서명 그림은 그 ID 의 그림 하나 — 고르기 목록 대신 켜고 끄는 체크
        self.chk_img = QCheckBox(tr("서명 그림"))
        self.chk_img.setChecked(bool(ap.get("show_image", True)))
        gl.addWidget(self.chk_img)
        self.chk_name = QCheckBox(tr("이름"))
        self.chk_date = QCheckBox(tr("날짜"))
        self.chk_reason = QCheckBox(tr("사유"))
        self.chk_name.setChecked(bool(ap.get("show_name", True)))
        self.chk_date.setChecked(bool(ap.get("show_date", True)))
        self.chk_reason.setChecked(bool(ap.get("show_reason", False)))
        for c in (self.chk_name, self.chk_date, self.chk_reason):
            gl.addWidget(c)
        gl.addStretch(1)
        form.addRow(tr("겉모양"), g)
        # 2단계(보안 SOT §3.6): 글자 배치
        self.cmb_layout = QComboBox()
        for key, label in (("image_top", tr("그림 위·글자 아래")), ("overlay", tr("그림 위에 겹쳐")),
                           ("image_left", tr("그림 왼쪽·글자 오른쪽"))):
            self.cmb_layout.addItem(label, key)
        from viewer import sign_core as _sc
        k_l = self.cmb_layout.findData(ap.get("layout") or _sc.LAYOUT_DEFAULT)
        self.cmb_layout.setCurrentIndex(max(0, k_l))
        form.addRow(tr("글자 배치"), self.cmb_layout)
        self.ed_reason = QLineEdit(d.get("last_reason", ""))
        self.ed_reason.setPlaceholderText(tr("예: 승인, 검토 완료"))
        self.ed_loc = QLineEdit(d.get("last_location", ""))
        form.addRow(tr("사유(선택)"), self.ed_reason)
        form.addRow(tr("장소(선택)"), self.ed_loc)
        # 2단계(보안 SOT §3.6): 서명 종류 — 인증은 문서의 첫 서명일 때만
        self.cmb_kind = QComboBox()
        self.cmb_kind.addItem(tr("승인 서명"), 0)
        if can_certify:
            self.cmb_kind.addItem(tr("인증 — 변경 금지"), 1)
            self.cmb_kind.addItem(tr("인증 — 양식 채우기·서명 허용"), 2)
            self.cmb_kind.addItem(tr("인증 — 주석·양식·서명 허용"), 3)
        else:
            self.cmb_kind.setToolTip(tr("이미 서명이 있는 문서에는 인증 서명을 할 수 없습니다(인증은 첫 서명만)."))
        form.addRow(tr("서명 종류"), self.cmb_kind)
        # 여러 쪽 — 이 쪽만 / 모든 쪽 / 쪽 범위
        self._page_count = max(1, int(page_count))
        self._current_page = int(current_page)
        pr = QWidget()
        pl = QHBoxLayout(pr)
        pl.setContentsMargins(0, 0, 0, 0)
        self.cmb_pages = QComboBox()
        self.cmb_pages.addItem(tr("이 쪽만 (p.{n})").format(n=self._current_page + 1), "this")
        self.cmb_pages.addItem(tr("모든 쪽 ({n}쪽)").format(n=self._page_count), "all")
        self.cmb_pages.addItem(tr("쪽 범위"), "range")
        self.ed_pages = QLineEdit()
        self.ed_pages.setPlaceholderText(tr("예: 1-3, 5"))
        self.ed_pages.setEnabled(False)
        pl.addWidget(self.cmb_pages)
        pl.addWidget(self.ed_pages, 1)
        self.cmb_pages.currentIndexChanged.connect(lambda _i: self.ed_pages.setEnabled(self.cmb_pages.currentData() == "range"))
        if self.field_name:
            self.cmb_pages.setEnabled(False)          # 빈 칸 채우기는 그 칸 하나
            self.cmb_pages.setToolTip(tr("빈 서명 칸 하나에 서명합니다."))
        if summary:
            pr.setParent(self)                   # 261012-1: 여러 쪽은 서명 자리 '다른 쪽에도 놓기…'(보안 SOT §3.6)
            pr.hide()
        else:
            form.addRow(tr("쪽"), pr)
        # 타임스탬프 기관 — 끄는 것이 기본, 주소는 사용자가
        tr_ = QWidget()
        tl = QHBoxLayout(tr_)
        tl.setContentsMargins(0, 0, 0, 0)
        self.chk_tsa = QCheckBox(tr("타임스탬프 기관(TSA) 시각 넣기"))
        self.ed_tsa = QLineEdit(d.get("tsa_url", ""))
        self.ed_tsa.setPlaceholderText("http://…")
        self.ed_tsa.setToolTip(tr("타임스탬프 기관 주소 — 서명할 때 인터넷이 필요합니다."))
        self.chk_tsa.setChecked(bool(d.get("tsa_on", False)))
        self.ed_tsa.setEnabled(self.chk_tsa.isChecked())
        self.chk_tsa.toggled.connect(self.ed_tsa.setEnabled)
        tl.addWidget(self.chk_tsa)
        tl.addWidget(self.ed_tsa, 1)
        form.addRow(tr("타임스탬프"), tr_)
        # 겉모양 미리보기 — 끈 상자 비율, 실제 서명과 같은 그리기(배경)
        self._box = (float(box_size[0]), float(box_size[1]))
        self.preview = QLabel(tr("미리보기 만드는 중…"))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("QLabel{border:1px solid #c8c8c8;background:#f3f3f3;}")
        # 높이는 처음부터 그림 크기로 — 그림이 온 뒤 늘리면 창이 따라 크지 않아 아래가 잘렸다(화면 확인)
        px_w = self._box[0] * self.PREVIEW_DPI / 72.0
        px_h = (self._box[1] + (0 if self._box_is_field else 40.0)) * self.PREVIEW_DPI / 72.0   # 아래 글자 줄 몫
        k = min(1.0, self.PREVIEW_MAX[0] / px_w, self.PREVIEW_MAX[1] / px_h)
        self.preview.setFixedHeight(int(px_h * k) + 6)
        form.addRow(tr("겉모양 미리보기"), self.preview)
        self._pv_gen = 0
        self._pv_threads = []
        self._pv_timer = QTimer(self)
        self._pv_timer.setSingleShot(True)
        self._pv_timer.setInterval(self.PREVIEW_DELAY_MS)
        self._pv_timer.timeout.connect(self._render_preview)
        v.addLayout(form)
        self._win_note = QLabel(tr("Windows 인증서 저장소의 키로 서명합니다 — 비밀번호 대신 Windows 가 PIN·확인을 물을 수 있습니다."))
        self._win_note.setWordWrap(True)
        v.addWidget(self._win_note)
        note = QLabel(tr("서명한 결과는 새 파일 '{name}' 로 저장되고 원본은 그대로입니다. 서명한 파일을 PolyPDF 에서 다시 저장하면 서명이 깨지므로 그때는 새 파일로 저장하라고 묻습니다.").format(
            name=out_name or tr("{stem}_서명.pdf").format(stem=Path(file_name).stem if file_name else "")))
        note.setWordWrap(True)
        v.addWidget(note)
        bb = QDialogButtonBox()
        self.b_sign = bb.addButton(tr("서명 확정"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.b_saveas = bb.addButton(tr("다른 이름으로…"), QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.b_sign.clicked.connect(self._sign)
        self.b_saveas.clicked.connect(self._sign_as)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.cmb_id.currentIndexChanged.connect(lambda _i: self._sync())
        self.cmb_id.currentIndexChanged.connect(lambda _i: self._pv_timer.start())
        for c in (self.chk_img, self.chk_name, self.chk_date, self.chk_reason):
            c.toggled.connect(lambda _on: self._pv_timer.start())
        self.ed_reason.textChanged.connect(lambda _t: self._pv_timer.start())
        self.cmb_layout.currentIndexChanged.connect(lambda _i: self._pv_timer.start())
        self._sync()
        self.resize(480, 0)
        self._pv_timer.start()

    # ---- 겉모양 미리보기 ----
    def _render_preview(self):
        from viewer import sign_core, sign_store
        e = sign_store.get_id(self.fp()) or {}
        app = self.appearance()
        self._pv_gen += 1
        label = sign_core.signer_label(e.get("name", ""), e.get("email", ""))
        w, h = self._box
        if not self._box_is_field:
            w, h = sign_core.stamp_size(app, label, self.ed_reason.text(), w, h)    # 그림 상자 + 아래 글자 줄(§3.6)
        # 261012-16(응답성 SOT §4.3): 워커 + `run_in_thread` — `_pv_threads` 는 keep 목록(끝나면 저절로 빠진다)
        from viewer.workers import SignPreviewWorker, run_in_thread
        wk = SignPreviewWorker(self._pv_gen, (app, label, self.ed_reason.text(), w, h, self.PREVIEW_DPI))
        wk.done.connect(self._on_preview)
        run_in_thread(wk, self._pv_threads)

    def _on_preview(self, gen, res):
        if gen != self._pv_gen:
            return                                   # 그 사이 다시 바꿨다 — 옛 결과는 버린다
        if isinstance(res, (bytes, bytearray)):
            pm = QPixmap()
            pm.loadFromData(bytes(res), "PNG")
            mw, mh = self.PREVIEW_MAX
            if pm.width() > mw or pm.height() > mh:
                pm = pm.scaled(mw, mh, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(pm)
            self.preview.setToolTip(tr("실제 서명과 같은 그리기 — 날짜는 서명하는 때의 시각으로 바뀝니다."))
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(empty_appearance_text() if res == "empty_appearance"
                                 else tr("겉모양에 쓸 한글 글꼴이 없습니다 — 서명 그림을 고르거나 겉모양 글자를 끄세요.")
                                 if res == "no_font" else tr("미리보기를 만들지 못했습니다({e}).").format(e=res))

    def _fit_height(self):
        """디자인 SOT §2.15 — 줄바꿈 라벨이 있는 최상위 창은 지금 폭에서 필요한 높이를 스스로 받지 못한다."""
        lay = self.layout()
        if lay is not None and lay.hasHeightForWidth():
            need = lay.totalHeightForWidth(self.width())
            if need > self.height():
                self.setMinimumHeight(need)
                self.resize(self.width(), need)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._fit_height)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._fit_height)

    def stop_preview(self):
        """그리는 중인 스레드를 기다린다 — 창이 먼저 지워지면 QThread 가 살아 있는 채 파괴된다."""
        self._pv_timer.stop()
        from PyQt6.QtCore import QThread
        for t in list(self._pv_threads):
            if isinstance(t, QThread):
                try:
                    t.wait(3000)
                except RuntimeError:              # 끝나 이미 지워진 스레드
                    pass

    def done(self, r):
        self.stop_preview()
        super().done(r)

    def appearance(self):
        """지금 고른 겉모양(서명·미리보기 공용) — 그림은 고른 ID 의 서명 그림(켰을 때)."""
        from viewer import sign_core, sign_store
        return sign_core.Appearance(image_path=sign_store.id_image_path(self.fp()) if self.chk_img.isChecked() else "",
                                    show_name=self.chk_name.isChecked(), show_date=self.chk_date.isChecked(),
                                    show_reason=self.chk_reason.isChecked(), font_path=sign_core.default_font(),
                                    layout=str(self.cmb_layout.currentData() or sign_core.LAYOUT_DEFAULT))

    def certify(self) -> int:
        return int(self.cmb_kind.currentData() or 0)

    def tsa_url(self) -> str:
        return self.ed_tsa.text().strip() if self.chk_tsa.isChecked() else ""

    def pages(self):
        """서명할 쪽(0부터) 목록. 쪽 범위를 못 읽으면 None."""
        mode = self.cmb_pages.currentData()
        if mode == "all":
            return list(range(self._page_count))
        if mode == "range":
            from viewer.page_crop import parse_range
            try:
                got = parse_range(self.ed_pages.text(), self._page_count)
            except Exception:
                got = []
            return sorted(set(got)) or None
        return [self._current_page]

    def fp(self) -> str:
        return str(self.cmb_id.currentData() or "")

    def _id_win(self) -> bool:
        from viewer import sign_store
        return (sign_store.get_id(self.fp()) or {}).get("kind") == "win"

    def _sync(self):
        from viewer import sign_store
        has_img = bool(sign_store.id_image_path(self.fp()))
        self.chk_img.setEnabled(has_img)
        self.chk_img.setToolTip("" if has_img else tr("이 디지털 ID 에는 서명 그림이 없습니다 — 디지털 ID 관리에서 넣을 수 있습니다."))
        self._win_note.setVisible(self._id_win())
        self.b_sign.setDefault(True)

    def _remember_choices(self):
        """고른 것은 다음 서명에도 그대로(261031-1, 사용자 지시) — 그림 켬·글자·배치·사유·타임스탬프·ID."""
        remember_appearance(show_image=self.chk_img.isChecked(), show_name=self.chk_name.isChecked(),
                            show_date=self.chk_date.isChecked(), show_reason=self.chk_reason.isChecked(),
                            layout=str(self.cmb_layout.currentData() or "image_top"),
                            tsa_on=self.chk_tsa.isChecked(), tsa_url=self.ed_tsa.text().strip(),
                            last_reason=self.ed_reason.text(), last_location=self.ed_loc.text(), fp=self.fp())

    def _sign(self):
        if not self.fp():
            return
        from viewer import sign_core, sign_store
        e = sign_store.get_id(self.fp()) or {}
        if not sign_core.has_content(self.appearance(), sign_core.signer_label(e.get("name", ""), e.get("email", "")),
                                     self.ed_reason.text()):
            QMessageBox.information(self, self.windowTitle(), empty_appearance_text())     # 261031-1 — 빈 서명은 하지 않는다
            return
        self._remember_choices()
        self.accept()

    def _sign_as(self):
        self.save_as = True
        self._sign()
        if self.result() != QDialog.DialogCode.Accepted:
            self.save_as = False


def empty_appearance_text() -> str:
    return tr("서명 내용이 없습니다 — 서명 그림이나 겉모양 글자(이름·날짜·사유)를 하나 이상 켜세요.")


def remember_appearance(fp: str = "", **kw) -> None:
    """서명 겉모양 고른 것을 `signing.json` 에 — 서명 확정 창·서명 자리 옵션 공용(261031-1).
    kw: show_image·show_name·show_date·show_reason·layout(appearance 안) · tsa_on·tsa_url·last_reason·last_location(맨 위)."""
    from viewer import sign_store
    d = sign_store.load()
    ap = dict(d.get("appearance") or {})
    for k in ("show_image", "show_name", "show_date", "show_reason", "layout"):
        if k in kw:
            ap[k] = kw.pop(k)
    d["appearance"] = ap
    for k, val in kw.items():
        d[k] = val
    if fp:
        d["default_id"] = fp
    sign_store.save(d)


class SignPanelDialog(QDialog):
    """서명 패널 — 서명 목록과 상세, [이 인증서 신뢰] (SOT §5)."""

    STATE_TEXT = {}

    def __init__(self, parent=None, report=None, path: str = "", open_cb=None):
        super().__init__(parent)
        from viewer import sign_core as sc
        self.setWindowTitle(tr("서명 패널"))
        self._rep = report
        self._path = str(path or "")
        self._open_cb = open_cb
        self.trust_changed = False
        st_text = {sc.OK_TRUSTED: tr("✅ 유효 · 신뢰함"), sc.OK_UNKNOWN: tr("⚠ 유효 · 신원 미확인"),
                   sc.MODIFIED: tr("⚠ 서명 뒤 변경됨"), sc.INVALID: tr("❌ 무효")}
        v = QVBoxLayout(self)
        self.lst = QListWidget()
        for s in (report.sigs if report else []):
            it = QListWidgetItem(f"{st_text.get(s.state, s.state)} — {s.signer or '?'}  ({s.field})")
            it.setData(Qt.ItemDataRole.UserRole, s)
            self.lst.addItem(it)
        v.addWidget(self.lst)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.detail, 1)
        row = QHBoxLayout()
        self.b_trust = QPushButton(tr("이 인증서 신뢰"))
        self.b_trust.clicked.connect(self._trust)
        row.addWidget(self.b_trust)
        # 2단계(보안 SOT §3.6): 서명할 때의 파일 그대로
        self.b_rev = QPushButton(tr("서명 시점 판 저장…"))
        self.b_rev.setToolTip(tr("이 서명이 덮는 판 — 서명할 때의 파일 그대로를 새 PDF 로 저장합니다."))
        self.b_rev.clicked.connect(self._save_revision)
        self.b_rev.setEnabled(bool(self._path))
        row.addWidget(self.b_rev)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        v.addLayout(row)
        self.lst.currentRowChanged.connect(lambda _r: self._show())
        if self.lst.count():
            self.lst.setCurrentRow(0)
        else:
            self.detail.setText(tr("서명을 확인하지 못했습니다({e}).").format(e=(report.error if report else "")))
            self.b_trust.setEnabled(False)
        self.resize(560, 420)

    def _cur(self):
        it = self.lst.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _show(self):
        s = self._cur()
        if s is None:
            return
        mod = {"none": tr("없음"), "form": tr("양식 채우기·서명 추가"), "annot": tr("주석"),
               "other": tr("내용 변경")}.get(s.modification, s.modification)
        kind = {0: tr("승인 서명"), 1: tr("인증 — 변경 금지"), 2: tr("인증 — 양식 채우기·서명 허용"),
                3: tr("인증 — 주석·양식·서명 허용")}.get(int(getattr(s, "certify", 0) or 0), tr("승인 서명"))
        lines = [
            tr("서명 종류: {v}").format(v=kind),
            tr("서명자: {v}").format(v=s.signer),
            tr("이메일: {v}").format(v=s.email or "—"),
            tr("조직: {v}").format(v=s.org or "—"),
            tr("서명 시각: {v} (서명한 PC 의 시계 기준)").format(v=s.time or "—"),
            (tr("타임스탬프: {v} (기관: {n})").format(v=s.ts_time, n=s.ts_name or "—") if getattr(s, "ts_time", "")
             else tr("타임스탬프: 없음")),
            tr("사유: {v}").format(v=s.reason or "—"),
            tr("장소: {v}").format(v=s.location or "—"),
            tr("인증서 지문(SHA-256): {v}").format(v=s.fp),
            tr("인증서 유효기간: ~{v}").format(v=s.not_after or "—"),
            tr("서명 뒤 덧붙은 변경: {v}").format(v=mod if not s.covers_whole else tr("없음")),
        ]
        if s.detail:
            lines.append(tr("오류: {v}").format(v=s.detail))
        self.detail.setText("\n".join(lines))
        from viewer import sign_store
        trusted = s.fp.lower() in {x.lower() for x in sign_store.trusted()}
        self.b_trust.setText(tr("신뢰 해제") if trusted else tr("이 인증서 신뢰"))
        self.b_trust.setEnabled(bool(s.fp))

    def _save_revision(self):
        """그 서명의 `/ByteRange` 끝까지 — 서명할 때의 파일 그대로를 새 PDF 로(SOT §3.6)."""
        s = self._cur()
        if s is None or not self._path:
            return
        from viewer import sign_core
        stem = os.path.splitext(os.path.basename(self._path))[0]
        default = os.path.join(os.path.dirname(self._path),
                               tr("{stem}_서명시점_{field}.pdf").format(stem=stem, field=s.field))
        fn, _ = QFileDialog.getSaveFileName(self, tr("서명 시점 판 저장"), default, tr("PDF 파일 (*.pdf)"))
        if not fn:
            return
        if not fn.lower().endswith(".pdf"):
            fn += ".pdf"
        if os.path.normcase(os.path.abspath(fn)) == os.path.normcase(os.path.abspath(self._path)):
            QMessageBox.warning(self, self.windowTitle(), tr("원본과 다른 이름으로 저장하세요."))
            return
        try:
            data = sign_core.signed_revision_bytes(self._path, s.field)
            with open(fn, "wb") as f:
                f.write(data)
        except Exception as e:                    # noqa: BLE001
            QMessageBox.warning(self, self.windowTitle(), tr("저장하지 못했습니다: {e}").format(e=type(e).__name__))
            return
        self.saved_revision = fn
        if self._open_cb is not None and QMessageBox.question(
                self, self.windowTitle(), tr("서명 시점 판을 저장했습니다. 지금 열까요?\n{name}").format(name=os.path.basename(fn))
        ) == QMessageBox.StandardButton.Yes:
            self.accept()
            self._open_cb(fn)

    def _trust(self):
        s = self._cur()
        if s is None or not s.fp:
            return
        from viewer import sign_store
        trusted = s.fp.lower() in {x.lower() for x in sign_store.trusted()}
        if not trusted and QMessageBox.question(
                self, self.windowTitle(),
                tr("'{name}' 의 인증서(지문 {fp}…)를 신뢰할까요? 그 사람에게서 받은 인증서인지 지문을 확인한 뒤에만 신뢰하세요.").format(
                    name=s.signer, fp=s.fp[:16])) != QMessageBox.StandardButton.Yes:
            return
        sign_store.trust(s.fp, not trusted)
        self.trust_changed = True
        self._show()
