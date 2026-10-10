# -*- coding: utf-8 -*-
"""전자서명 대화상자 — 서명 그림·디지털 ID·서명 (보안 SOT §3·§6).

무거운 일(키 만들기·`.pfx` 열기·Hello 확인)은 `runner(fn, title)` 로 배경에서 한다 — 앱이 넘겨 주는
`SignMixin._sign_bg`(진행창 + 배경 스레드, 응답성 SOT §4). 여기서는 화면만 다룬다.
비밀번호는 칸에서 읽어 바로 넘기고 들고 있지 않는다(SOT §6.4).
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QImage, QPainter, QPixmap, QColor
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSlider,
    QSpinBox, QVBoxLayout,
)

from viewer.i18n import tr

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
        b_open.clicked.connect(self._open_file)
        b_clip.clicked.connect(self._from_clipboard)
        row.addWidget(b_open)
        row.addWidget(b_clip)
        row.addStretch(1)
        v.addLayout(row)
        self.preview = QLabel(tr("종이에 한 서명을 찍은 사진이나 투명 PNG 를 불러오세요."))
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


# ---------------------------------------------------------------------------
# 서명 창 — SOT §3.3
# ---------------------------------------------------------------------------

class SignDialog(QDialog):
    """디지털 ID·그림·겉모양 글자·사유·비밀번호(또는 Windows Hello) → [서명] / [다른 이름으로 서명…]."""

    def __init__(self, parent=None, hello_ok: bool = False, file_name: str = ""):
        super().__init__(parent)
        from viewer import sign_hello, sign_store
        self.setWindowTitle(tr("전자서명 — {name}").format(name=file_name) if file_name else tr("전자서명"))
        self._hello_ok = bool(hello_ok)
        self.save_as = False
        self.use_hello = False
        d = sign_store.load()
        v = QVBoxLayout(self)
        form = QFormLayout()
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
        g = QGroupBox(tr("겉모양 글자"))
        gl = QHBoxLayout(g)
        self.chk_name = QCheckBox(tr("이름"))
        self.chk_date = QCheckBox(tr("날짜"))
        self.chk_reason = QCheckBox(tr("사유"))
        self.chk_name.setChecked(bool(ap.get("show_name", True)))
        self.chk_date.setChecked(bool(ap.get("show_date", True)))
        self.chk_reason.setChecked(bool(ap.get("show_reason", False)))
        for c in (self.chk_name, self.chk_date, self.chk_reason):
            gl.addWidget(c)
        gl.addStretch(1)
        form.addRow(g)
        self.ed_reason = QLineEdit(d.get("last_reason", ""))
        self.ed_reason.setPlaceholderText(tr("예: 승인, 검토 완료"))
        self.ed_loc = QLineEdit(d.get("last_location", ""))
        form.addRow(tr("사유(선택)"), self.ed_reason)
        form.addRow(tr("장소(선택)"), self.ed_loc)
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
        self._has_hello = sign_hello.has
        self._sync()
        self.resize(480, 0)

    def fp(self) -> str:
        return str(self.cmb_id.currentData() or "")

    def image_name(self) -> str:
        return str(self.cmb_img.currentData() or "")

    def _id_hello(self) -> bool:
        from viewer import sign_store
        e = sign_store.get_id(self.fp()) or {}
        return bool(self._hello_ok and e.get("hello") and self._has_hello(self.fp()))

    def _sync(self):
        h = self._id_hello()
        self.btn_hello.setVisible(h)
        self._g_lab.setVisible(not self._hello_ok)
        self._g_btn.setVisible(not self._hello_ok)
        self.b_sign.setDefault(not h)

    def password(self) -> str:
        return self.ed_pw.text()

    def _remember_choices(self):
        from viewer import sign_store
        d = sign_store.load()
        d["appearance"] = {"show_name": self.chk_name.isChecked(), "show_date": self.chk_date.isChecked(),
                           "show_reason": self.chk_reason.isChecked()}
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
        if not self.ed_pw.text():
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

    def __init__(self, parent=None, report=None):
        super().__init__(parent)
        from viewer import sign_core as sc
        self.setWindowTitle(tr("서명 패널"))
        self._rep = report
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
        lines = [
            tr("서명자: {v}").format(v=s.signer),
            tr("이메일: {v}").format(v=s.email or "—"),
            tr("조직: {v}").format(v=s.org or "—"),
            tr("서명 시각: {v} (서명한 PC 의 시계 기준)").format(v=s.time or "—"),
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
