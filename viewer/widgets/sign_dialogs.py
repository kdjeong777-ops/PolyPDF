# -*- coding: utf-8 -*-
"""전자서명 대화상자 — 서명 그림·디지털 ID·서명 (보안 SOT §3·§6).

무거운 일(키 만들기·`.pfx` 열기·Hello 확인)은 `runner(fn, title)` 로 배경에서 한다 — 앱이 넘겨 주는
`SignMixin._sign_bg`(진행창 + 배경 스레드, 응답성 SOT §4). 여기서는 화면만 다룬다.
비밀번호는 칸에서 읽어 바로 넘기고 들고 있지 않는다(SOT §6.4).
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QImage, QPainter, QPixmap, QColor
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
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
    """불러오기 → 배경 지우기(자동 임계값) → 잉크 색 → 자르기 → 이름 붙여 저장."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("서명 그림 만들기"))
        self._src = None            # PIL 원본
        self._out = None            # 정리한 RGBA
        self.saved_name = ""
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
        self.ed_name = QLineEdit(tr("기본"))
        form.addRow(tr("이름"), self.ed_name)
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
        from viewer import sign_store
        e = sign_store.add_image(self._out, self.ed_name.text())
        self.saved_name = e["name"]
        self.accept()


# ---------------------------------------------------------------------------
# 디지털 ID — SOT §3.2·§6.1
# ---------------------------------------------------------------------------

class _CreateIdDialog(QDialog):
    def __init__(self, parent=None, hello_ok: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("새 디지털 ID"))
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
        note = QLabel(tr("직접 만든 디지털 ID 는 받는 사람의 PDF 뷰어에서 '신원 알 수 없음' 으로 보입니다. "
                         "받는 사람이 공개 인증서(.cer)를 신뢰 등록하면 '유효' 로 보입니다. "
                         "문서가 바뀌었는지는 신뢰 등록 없이도 드러납니다."))
        note.setWordWrap(True)
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.ed_pw.textChanged.connect(self._strength)
        self.resize(460, 0)

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
    """디지털 ID 관리 — 만들기·가져오기·백업·공개 인증서·기본·Hello 보관·지우기."""

    def __init__(self, parent=None, runner=None, hello_ok: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("디지털 ID"))
        self._run = runner or (lambda fn, _t: fn())
        self._hello_ok = bool(hello_ok)
        v = QVBoxLayout(self)
        self.lst = QListWidget()
        v.addWidget(self.lst, 1)
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
        self.b_del = QPushButton(tr("지우기…"))
        for b in (self.b_def, self.b_hello, self.b_del):
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
        self.b_del.clicked.connect(self._delete)
        self.lst.currentRowChanged.connect(lambda _r: self._sync_buttons())
        self.resize(620, 360)
        self.refresh()

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

    def _sync_buttons(self):
        has = bool(self._fp())
        for b in (self.b_bak, self.b_cer, self.b_def, self.b_hello, self.b_del):
            b.setEnabled(has)
        if has:
            from viewer import sign_store
            win = (sign_store.get_id(self._fp()) or {}).get("kind") == "win"
            self.b_bak.setEnabled(not win)           # 키가 Windows 안에 있다(SOT §3.9)
            self.b_hello.setEnabled(not win)
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
        sign_store.add_id(pfx, info)
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
        dlg = NpkiDialog(self, found)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.chosen is None:
            return
        c, pw = dlg.chosen, dlg.password()
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

    def __init__(self, parent=None, found=()):
        super().__init__(parent)
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
        got = sign_npki.find([d])
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
# 서명 창 — SOT §3.3
# ---------------------------------------------------------------------------

class _PreviewThread(QThread):
    """겉모양 미리보기 — 배경(0.2~0.4초, 보안 SOT §10). (세대, PNG 바이트 | 오류 글)."""
    done = pyqtSignal(int, object)

    def __init__(self, gen, args, parent=None):
        super().__init__(parent)
        self._gen, self._args = gen, args

    def run(self):
        try:
            from viewer import sign_core
            self.done.emit(self._gen, sign_core.preview_png(*self._args))
        except Exception as e:                    # noqa: BLE001
            self.done.emit(self._gen, getattr(e, "reason", "") or type(e).__name__)


class SignDialog(QDialog):
    """디지털 ID·그림·겉모양 글자·사유·비밀번호(또는 Windows Hello) → [서명] / [다른 이름으로 서명…].
    끈 상자 크기 그대로 실제 겉모양을 미리 보인다(보안 SOT §3.3)."""

    PREVIEW_DELAY_MS = 250
    PREVIEW_MAX = (360, 150)
    PREVIEW_DPI = 110

    def __init__(self, parent=None, hello_ok: bool = False, file_name: str = "", box_size=(142.0, 57.0),
                 page_count: int = 1, current_page: int = 0, can_certify: bool = True, field_name: str = "",
                 field_signers=(), field_lock: bool = False):
        super().__init__(parent)
        from viewer import sign_hello, sign_store
        self.setWindowTitle(tr("전자서명 — {name}").format(name=file_name) if file_name else tr("전자서명"))
        self._hello_ok = bool(hello_ok)
        self.save_as = False
        self.use_hello = False
        self.field_name = str(field_name or "")      # 3단계(보안 SOT §3.7): 빈 서명 칸 채우기
        d = sign_store.load()
        v = QVBoxLayout(self)
        form = QFormLayout()
        if self.field_name:
            form.addRow(tr("서명 칸"), QLabel(tr("{name} (p.{page})").format(name=self.field_name, page=int(current_page) + 1)))
            if field_signers:
                form.addRow(tr("서명할 사람"), QLabel(", ".join(field_signers)))
            if field_lock:
                form.addRow(tr("잠금"), QLabel(tr("서명하면 문서의 모든 칸이 잠깁니다")))
        self.cmb_id = QComboBox()
        for e in d["ids"]:
            self.cmb_id.addItem(f"{e.get('name', '')}" + (f" <{e['email']}>" if e.get("email") else ""), e.get("fp"))
        i = self.cmb_id.findData(d.get("default_id"))
        if i >= 0:
            self.cmb_id.setCurrentIndex(i)
        form.addRow(tr("디지털 ID"), self.cmb_id)
        self.cmb_img = QComboBox()
        self.cmb_img.addItem(tr("(그림 없음)"), "")
        for im in d["images"]:
            self.cmb_img.addItem(im.get("name", ""), im.get("name", ""))
        j = self.cmb_img.findData(d.get("default_image"))
        if j >= 0:
            self.cmb_img.setCurrentIndex(j)
        form.addRow(tr("서명 그림"), self.cmb_img)
        ap = d.get("appearance") or {}
        # 줄 하나짜리 묶음 — QGroupBox 는 줄바꿈 라벨이 있는 창에서 높이를 못 받아 빈 막대로 눌렸다(화면 확인)
        from PyQt6.QtWidgets import QWidget
        g = QWidget()
        gl = QHBoxLayout(g)
        gl.setContentsMargins(0, 0, 0, 0)
        self.chk_name = QCheckBox(tr("이름"))
        self.chk_date = QCheckBox(tr("날짜"))
        self.chk_reason = QCheckBox(tr("사유"))
        self.chk_name.setChecked(bool(ap.get("show_name", True)))
        self.chk_date.setChecked(bool(ap.get("show_date", True)))
        self.chk_reason.setChecked(bool(ap.get("show_reason", False)))
        for c in (self.chk_name, self.chk_date, self.chk_reason):
            gl.addWidget(c)
        gl.addStretch(1)
        form.addRow(tr("겉모양 글자"), g)
        # 2단계(보안 SOT §3.6): 글자 배치
        self.cmb_layout = QComboBox()
        for key, label in (("overlay", tr("그림 위에 겹쳐")), ("image_left", tr("그림 왼쪽·글자 오른쪽")),
                           ("image_top", tr("그림 위·글자 아래"))):
            self.cmb_layout.addItem(label, key)
        k_l = self.cmb_layout.findData(ap.get("layout", "overlay"))
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
        px_w, px_h = self._box[0] * self.PREVIEW_DPI / 72.0, self._box[1] * self.PREVIEW_DPI / 72.0
        k = min(1.0, self.PREVIEW_MAX[0] / px_w, self.PREVIEW_MAX[1] / px_h)
        self.preview.setFixedHeight(int(px_h * k) + 6)
        form.addRow(tr("겉모양 미리보기"), self.preview)
        self._pv_gen = 0
        self._pv_threads = []
        self._pv_timer = QTimer(self)
        self._pv_timer.setSingleShot(True)
        self._pv_timer.setInterval(self.PREVIEW_DELAY_MS)
        self._pv_timer.timeout.connect(self._render_preview)
        self.ed_pw = QLineEdit()
        self.ed_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_pw.setPlaceholderText(tr("디지털 ID 비밀번호(붙여넣기 가능)"))
        form.addRow(tr("비밀번호"), self.ed_pw)
        v.addLayout(form)
        self.btn_hello = QPushButton(tr("Windows Hello 로 서명"))
        self.btn_hello.setDefault(True)
        self.btn_hello.clicked.connect(self._hello)
        v.addWidget(self.btn_hello)
        self._google_row = QHBoxLayout()
        self._g_lab = google_hint_label()
        self._g_btn = google_button(self)
        v.addWidget(self._g_lab)
        self._google_row.addWidget(self._g_btn)
        self._google_row.addStretch(1)
        v.addLayout(self._google_row)
        self._win_note = QLabel(tr("Windows 인증서 저장소의 키로 서명합니다 — 비밀번호 대신 Windows 가 PIN·확인을 물을 수 있습니다."))
        self._win_note.setWordWrap(True)
        v.addWidget(self._win_note)
        note = QLabel(tr("서명은 현재 파일에 덧붙여 저장됩니다. 서명 뒤 PolyPDF 에서 이 파일을 다시 저장하면 서명이 깨지므로 그때는 새 파일로 저장하라고 묻습니다."))
        note.setWordWrap(True)
        v.addWidget(note)
        bb = QDialogButtonBox()
        self.b_sign = bb.addButton(tr("서명"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.b_saveas = bb.addButton(tr("다른 이름으로 서명…"), QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.b_sign.clicked.connect(self._sign)
        self.b_saveas.clicked.connect(self._sign_as)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.cmb_id.currentIndexChanged.connect(lambda _i: self._sync())
        for sig in (self.cmb_id.currentIndexChanged, self.cmb_img.currentIndexChanged):
            sig.connect(lambda _i: self._pv_timer.start())
        for c in (self.chk_name, self.chk_date, self.chk_reason):
            c.toggled.connect(lambda _on: self._pv_timer.start())
        self.ed_reason.textChanged.connect(lambda _t: self._pv_timer.start())
        self.cmb_layout.currentIndexChanged.connect(lambda _i: self._pv_timer.start())
        self._has_hello = sign_hello.has
        self._sync()
        self.resize(480, 0)
        self._pv_timer.start()

    # ---- 겉모양 미리보기 ----
    def _render_preview(self):
        from viewer import sign_core, sign_store
        e = sign_store.get_id(self.fp()) or {}
        app = self.appearance()
        self._pv_gen += 1
        th = _PreviewThread(self._pv_gen, (app, sign_core.signer_label(e.get("name", ""), e.get("email", "")),
                                           self.ed_reason.text(), self._box[0], self._box[1], self.PREVIEW_DPI), self)
        th.done.connect(self._on_preview)
        self._pv_threads.append(th)

        def _gone(t=th):
            try:
                self._pv_threads.remove(t)
            except ValueError:
                pass
            t.deleteLater()
        th.finished.connect(_gone)
        th.start()

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
            self.preview.setText(tr("겉모양에 쓸 한글 글꼴이 없습니다 — 서명 그림을 고르거나 겉모양 글자를 끄세요.")
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
        for t in list(self._pv_threads):
            t.wait(3000)

    def done(self, r):
        self.stop_preview()
        super().done(r)

    def appearance(self):
        """지금 고른 겉모양(서명·미리보기 공용)."""
        from viewer import sign_core, sign_store
        return sign_core.Appearance(image_path=sign_store.image_path(self.image_name()),
                                    show_name=self.chk_name.isChecked(), show_date=self.chk_date.isChecked(),
                                    show_reason=self.chk_reason.isChecked(), font_path=sign_core.default_font(),
                                    layout=str(self.cmb_layout.currentData() or "overlay"))

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

    def image_name(self) -> str:
        return str(self.cmb_img.currentData() or "")

    def _id_hello(self) -> bool:
        from viewer import sign_store
        e = sign_store.get_id(self.fp()) or {}
        return bool(self._hello_ok and e.get("hello") and self._has_hello(self.fp()))

    def _id_win(self) -> bool:
        from viewer import sign_store
        return (sign_store.get_id(self.fp()) or {}).get("kind") == "win"

    def _sync(self):
        win = self._id_win()
        h = self._id_hello() and not win
        self.btn_hello.setVisible(h)
        self._g_lab.setVisible(not self._hello_ok and not win)
        self._g_btn.setVisible(not self._hello_ok and not win)
        self.ed_pw.setEnabled(not win)
        self._win_note.setVisible(win)
        self.b_sign.setDefault(not h)

    def password(self) -> str:
        return self.ed_pw.text()

    def _remember_choices(self):
        from viewer import sign_store
        d = sign_store.load()
        d["appearance"] = {"show_name": self.chk_name.isChecked(), "show_date": self.chk_date.isChecked(),
                           "show_reason": self.chk_reason.isChecked(),
                           "layout": str(self.cmb_layout.currentData() or "overlay")}
        d["tsa_on"] = self.chk_tsa.isChecked()
        d["tsa_url"] = self.ed_tsa.text().strip()
        d["last_reason"] = self.ed_reason.text()
        d["last_location"] = self.ed_loc.text()
        if self.fp():
            d["default_id"] = self.fp()
        d["default_image"] = self.image_name() or d.get("default_image", "")
        sign_store.save(d)

    def _hello(self):
        self.use_hello = True
        self._remember_choices()
        self.accept()

    def _sign(self):
        if not self.fp():
            return
        if not self.ed_pw.text() and not self._id_win():
            QMessageBox.information(self, self.windowTitle(), tr("비밀번호를 넣으세요."))
            return
        self.use_hello = False
        self._remember_choices()
        self.accept()

    def _sign_as(self):
        self.save_as = True
        if self._id_hello() and not self.ed_pw.text():
            self._hello()
            return
        self._sign()
        if self.result() != QDialog.DialogCode.Accepted:
            self.save_as = False


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
