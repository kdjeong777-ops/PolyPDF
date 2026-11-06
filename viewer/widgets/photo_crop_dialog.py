# -*- coding: utf-8 -*-
"""사진 크롭 창 (사진 보기 SOT §4.40, 261105-4·261106-3) — PDF 크롭 창과 같은 미리보기 화면(`CropCanvas`).

사진 한 장을 보이는 방향(보기 회전 뒤) 그대로 그리고 잘릴 곳을 어둡게 — 네 변을 끌거나 위·아래·왼쪽·오른쪽 % 칸으로.
한계는 PDF 크롭과 같다(`page_crop.clamp_margins`). [크롭 해제] 는 자른 모양을 푼다. 원본 사진은 건드리지 않는다.

261106-3(사용자 지시 '이전·이후 추가, 넘어가면 임시 저장, 확인 시 전체 적용'): 넘길 사진이 둘 이상이면 미리보기 아래 가운데에
공통 `PageNav`(`❮ n / 전체 ❯`, 디자인 SOT §2.20). 창은 사진을 스스로 읽지 않는다 — `photoRequested(번호)` 를 내면 쓰는 쪽이
배경에서 그림을 풀어 `show_photo` 로 넣는다(그 사이 넘김은 꺼진다). 사진마다 고친 여백은 `pending()` 에 남고, [확인] 때
쓰는 쪽이 한꺼번에 적용한다. [취소] 면 아무것도 남지 않는다.

261106-6(사용자 지시 '원근·움푹 들어간 사진은 꼭짓점을 움직여 테두리를 고르고 직사각형으로 펼쳐 저장'): 옵션 **'모양 펴기'** 를
켜면 미리보기가 점 끌기 화면(`WarpCanvas`)으로 바뀐다 — 꼭짓점 넷 + 변 가운데 넷. 처음 점은 쓰는 쪽이 어림한 테두리
(`show_photo(..., auto_pts)`, 못 찾으면 기본 점). 켜고 끔·점은 사진마다 기억하고, 처음 보는 사진은 지금 켜고 끔을 이어받는다.
[확인] 때 `pending_warps()` 의 사진은 펼친 새 사진으로 만들고(쓰는 쪽), 그 사진의 크롭은 그대로 둔다(`pending()` 에서 뺀다).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                             QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout)

from viewer import page_crop as pc
from viewer import photo_warp as pw
from viewer.i18n import tr
from viewer.widgets.crop_dialog import CropCanvas
from viewer.widgets.page_nav import PageNav, centered_row
from viewer.widgets.photo_warp_canvas import WarpCanvas


RESULT_SIDE = 420          # 결과 미리보기 — 줄인 그림 긴 변(펴기를 메인에서 짧게: 이 크기에서 수십 ms)
RESULT_MIN_W = 240         # 결과 미리보기 칸 최소 폭
RESULT_DELAY_MS = 60       # 끄는 동안 미리보기를 모아 한 번에(잇단 움직임은 마지막 것만)


def _pil_of(img):
    """QImage → 줄인 PIL RGB(긴 변 `RESULT_SIDE`)."""
    from PIL import Image
    s = img.scaled(RESULT_SIDE, RESULT_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                   Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB888)
    w, h = s.width(), s.height()
    buf = bytes(s.constBits().asstring(s.bytesPerLine() * h))
    return Image.frombuffer("RGB", (w, h), buf, "raw", "RGB", s.bytesPerLine(), 1).copy()


def _qimage_of(pil) -> QImage:
    pil = pil.convert("RGB")
    data = pil.tobytes("raw", "RGB")
    return QImage(data, pil.size[0], pil.size[1], pil.size[0] * 3, QImage.Format.Format_RGB888).copy()


class PhotoCropDialog(QDialog):
    photoRequested = pyqtSignal(int)          # 넘길 사진 번호(0부터) — 쓰는 쪽이 그림을 풀어 show_photo

    def __init__(self, img, margins, has_crop: bool = False, title: str = "", parent=None,
                 count: int = 1, index: int = 0, auto_pts=None):
        super().__init__(parent)
        self.resize(1120, 720)
        self._reset = False
        self._count, self._index = max(1, int(count)), int(index)
        self._pending = {}                     # 번호 → [위, 아래, 왼, 오른] % (넘길 때 기억한 것)
        self._warp_on = {}                     # 번호 → 모양 펴기 켬(261106-6)
        self._warp_pts = {}                    # 번호 → 점 8개(비율)
        self._auto = None                      # 지금 사진의 어림한 테두리(없으면 None)
        self._has_crop = False
        self._loading = False
        root = QVBoxLayout(self)
        self.stack = QStackedWidget(self)
        self.canvas = CropCanvas(self)
        self.warp = WarpCanvas(self)
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.warp)
        top = QHBoxLayout()                    # 왼쪽 = 고치는 화면, 오른쪽 = 결과 미리보기(261106-6 사용자 지시)
        top.addWidget(self.stack, 3)
        side = QVBoxLayout()
        side.addWidget(QLabel(tr("결과 미리보기"), self))
        self.result = QLabel(self)
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result.setMinimumWidth(RESULT_MIN_W)
        self.result.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.result.setStyleSheet("QLabel{border:1px solid palette(mid);}")
        side.addWidget(self.result, 1)
        top.addLayout(side, 2)
        root.addLayout(top, 1)
        self._small = None                     # 미리보기용 줄인 PIL 그림(지금 사진)
        self._prev_timer = QTimer(self)
        self._prev_timer.setSingleShot(True)
        self._prev_timer.setInterval(RESULT_DELAY_MS)
        self._prev_timer.timeout.connect(self._update_result)
        self.warp.pointsDragged.connect(lambda _p: self._prev_timer.start())
        self.nav = PageNav(self)
        self.nav.stepRequested.connect(lambda d: self._go(self._index + d))
        self.nav.pageRequested.connect(lambda n: self._go(n - 1))
        self.nav.setVisible(self._count > 1)
        root.addLayout(centered_row(self.nav))
        row = QHBoxLayout()
        grid = QGridLayout()
        self.spins = []
        for i, name in enumerate((tr("위"), tr("아래"), tr("왼쪽"), tr("오른쪽"))):
            sp = QDoubleSpinBox(self)
            sp.setRange(0.0, pc.CROP_MAX)
            sp.setDecimals(1)
            sp.setSingleStep(0.5)
            sp.setSuffix(" %")
            sp.valueChanged.connect(lambda _v, k=i: self._spin_changed(k))
            grid.addWidget(QLabel(name, self), 0, i * 2)
            grid.addWidget(sp, 0, i * 2 + 1)
            self.spins.append(sp)
        row.addLayout(grid)
        row.addStretch(1)
        root.addLayout(row)
        wrow = QHBoxLayout()                   # 옵션 — 모양 펴기(261106-6)
        self.chk_warp = QCheckBox(tr("모양 펴기 (원근·휜 테두리)"), self)
        self.chk_warp.setToolTip(tr("비스듬히 찍었거나 가운데가 휜 사진을 테두리에 맞춰 직사각형으로 펼칩니다."))
        self.chk_warp.toggled.connect(self._warp_toggled)
        self.btn_detect = QPushButton(tr("테두리 찾기"), self)
        self.btn_detect.clicked.connect(self._on_detect)
        self.btn_corners = QPushButton(tr("점 처음대로"), self)
        self.btn_corners.setToolTip(tr("점을 사진 네 귀퉁이 가까이로 되돌립니다."))
        self.btn_corners.clicked.connect(lambda: self.warp.set_points(pw.default_points()))
        wrow.addWidget(self.chk_warp)
        wrow.addWidget(self.btn_detect)
        wrow.addWidget(self.btn_corners)
        wrow.addStretch(1)
        root.addLayout(wrow)
        self.note_warp = QLabel(tr("꼭짓점(네모)을 끌어 테두리에 맞추고, 휜 변은 가운데 점(동그라미)을 끕니다 — [확인] 이면 펼친 그림을 새 사진으로 저장합니다(원본은 그대로)."), self)
        self.note_warp.setWordWrap(True)
        root.addWidget(self.note_warp)
        note = QLabel(tr("원본 사진은 그대로 두고 자른 모양만 기억합니다 — 사진 → PDF·인쇄·평탄화·공유용 사본·사진 복사도 자른 모양으로 나옵니다."), self)
        note.setWordWrap(True)
        root.addWidget(note)
        self.note_many = QLabel(tr("❮ ❯ 로 넘기면 고친 크롭을 기억해 두었다가 [확인] 때 한꺼번에 적용합니다 — 크롭이 없는 사진은 최근에 정한 크롭을 미리 겁니다."), self)
        self.note_many.setWordWrap(True)
        self.note_many.setVisible(self._count > 1)
        root.addWidget(self.note_many)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.btn_reset = bb.addButton(tr("크롭 해제"), QDialogButtonBox.ButtonRole.ResetRole)
        self.btn_reset.clicked.connect(self._on_reset)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        self.canvas.marginsDragged.connect(self._dragged)
        self.show_photo(self._index, img, margins, has_crop, title, auto_pts)

    # ── 사진 하나 보이기 ──────────────────────────────
    def show_photo(self, index: int, img, margins, has_crop: bool = False, title: str = "", auto_pts=None) -> None:
        """`index` 사진을 보인다 — 그 사진에 이 창에서 고친 여백이 있으면 그것, 없으면 `margins`.
        모양 펴기 — 그 사진에 기억한 켜고 끔·점이 있으면 그것, 처음이면 지금 켜고 끔 그대로·점은 `auto_pts`(어림, 없으면 기본)."""
        self._index = int(index)
        self._loading = False
        self._has_crop = bool(has_crop)
        self._auto = pw.clamp_points(auto_pts) if auto_pts else None
        self.setWindowTitle(tr("사진 크롭") + (" — " + title if title else ""))
        self.canvas.set_image(img)
        self.warp.set_image(img)
        try:
            self._small = _pil_of(img) if img is not None and not img.isNull() else None
        except Exception:
            self._small = None
        m = self._pending.get(self._index, margins)
        m = [round(v, 1) for v in pc.clamp_margins(list(m or [0.0, 0.0, 0.0, 0.0]))]
        self._dragged(m)
        self.canvas.set_margins(m)
        self.warp.set_points(self._warp_pts.get(self._index) or self._auto or pw.default_points())
        on = self._warp_on.get(self._index, self.chk_warp.isChecked())
        self.chk_warp.blockSignals(True)
        self.chk_warp.setChecked(on)
        self.chk_warp.blockSignals(False)
        self._apply_warp_ui()
        self.nav.set_state(self._index + 1, self._count)

    def _go(self, index: int) -> None:
        if self._loading or not (0 <= index < self._count) or index == self._index:
            return
        self._pending[self._index] = self.current_margins()     # 지금 사진 것을 임시로 기억(261106-3)
        self._remember_warp()
        self._loading = True
        self.nav.btn_prev.setEnabled(False)
        self.nav.btn_next.setEnabled(False)
        self.photoRequested.emit(index)

    # ── 모양 펴기(261106-6) ──────────────────────────
    def _remember_warp(self) -> None:
        self._warp_on[self._index] = self.chk_warp.isChecked()
        self._warp_pts[self._index] = self.warp.points()

    def _warp_toggled(self, on: bool) -> None:
        self._warp_on[self._index] = bool(on)
        self._apply_warp_ui()

    def _apply_warp_ui(self) -> None:
        on = self.chk_warp.isChecked()
        self.stack.setCurrentWidget(self.warp if on else self.canvas)
        for sp in self.spins:
            sp.setEnabled(not on)
        self.btn_detect.setVisible(on)
        self.btn_detect.setEnabled(self._auto is not None)
        self.btn_detect.setToolTip(tr("어림한 테두리로 점을 놓습니다.") if self._auto is not None
                                   else tr("이 사진에서는 테두리를 찾지 못했습니다 — 점을 끌어 맞추세요."))
        self.btn_corners.setVisible(on)
        self.note_warp.setVisible(on)
        self.btn_reset.setEnabled(not on and (self._has_crop or any(v > 0 for v in self.current_margins())))
        self._prev_timer.start()

    # ── 결과 미리보기(261106-6 사용자 지시 '일반 크롭이나 펼칠 경우의 모습을 우측 창에') ──
    def result_image(self):
        """지금 설정의 결과(줄인 그림) — 펴기면 펼친 모양, 아니면 자른 모양. 못 만들면 None."""
        im = self._small
        if im is None:
            return None
        if self.chk_warp.isChecked():
            pts = self.warp.points()
            if not pw.is_valid(pts):
                return None
            try:
                return pw.unwarp(im, pts, cells=12)
            except Exception:
                return None
        t, b, l, r = (v / 100.0 for v in self.current_margins())
        w, h = im.size
        box = (int(round(l * w)), int(round(t * h)), int(round(w - r * w)), int(round(h - b * h)))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return None
        return im.crop(box)

    def _update_result(self):
        out = self.result_image()
        self._result_px = QPixmap.fromImage(_qimage_of(out)) if out is not None else None
        self._fit_result()

    def _fit_result(self):
        px = self.__dict__.get("_result_px")
        if px is None or px.isNull():
            self.result.clear()
            return
        self.result.setPixmap(px.scaled(self.result.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_result()

    def _on_detect(self) -> None:
        if self._auto is not None:
            self.warp.set_points(self._auto)

    def pending_warps(self) -> dict:
        """[확인] 때 펼칠 사진 — {번호: 점 8개}. 모양 펴기를 켠 사진만, 펼 것이 없거나 꼬인 점은 뺀다."""
        self._remember_warp()
        out = {}
        for i, on in self._warp_on.items():
            pts = self._warp_pts.get(i)
            if on and pts and pw.is_valid(pts) and not pw.is_identity(pts):
                out[i] = list(pts)
        return out

    def loading_failed(self) -> None:
        """쓰는 쪽이 그림을 풀지 못했다 — 지금 사진에 그대로."""
        self._loading = False
        self.nav.set_state(self._index + 1, self._count)

    # ── 여백 ──────────────────────────────────────────
    def _dragged(self, m):
        for sp, v in zip(self.spins, m):
            sp.blockSignals(True)
            sp.setValue(float(v))
            sp.blockSignals(False)
        t = self.__dict__.get("_prev_timer")
        if t is not None:
            t.start()

    def _spin_changed(self, k: int):
        m = [round(v, 1) for v in pc.clamp_margins([sp.value() for sp in self.spins], keep=k)]
        self._dragged(m)
        self.canvas.set_margins(m)

    def _on_reset(self):
        """[크롭 해제] — 사진 한 장이면 풀고 닫는다. 여럿이면 지금 사진만 풀고(0 %) 창은 그대로 — [확인] 때 함께."""
        if self._count > 1:
            self._dragged([0.0, 0.0, 0.0, 0.0])
            self.canvas.set_margins([0.0, 0.0, 0.0, 0.0])
            return
        self._reset = True
        self.accept()

    def current_margins(self) -> list:
        return [sp.value() for sp in self.spins]

    def index(self) -> int:
        return self._index

    def margins(self):
        """지금 사진의 [위, 아래, 왼, 오른] % — [크롭 해제] 를 눌렀거나 모두 0 이면 None(자르지 않음)."""
        if self._reset:
            return None
        m = self.current_margins()
        return None if not any(v > 0 for v in m) else m

    def pending(self) -> dict:
        """[확인] 때 적용할 것 — {번호: 여백 % 또는 None(자르지 않음)}: 넘기며 기억한 사진들 + 지금 사진."""
        out = {i: (m if any(v > 0 for v in m) else None) for i, m in self._pending.items()}
        out[self._index] = self.margins()
        self._remember_warp()
        for i, on in self._warp_on.items():              # 모양 펴기를 켠 사진은 크롭을 그대로 둔다(펼친 새 사진을 만든다, 261106-6)
            if on:
                out.pop(i, None)
        return out
