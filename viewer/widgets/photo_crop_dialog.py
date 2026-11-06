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
PANE_MIN_W = 360           # 왼쪽(고치는)·오른쪽(결과) 칸 최소 폭 — 둘이 같다(261106-8, 디자인 SOT §2.21)
PANE_MIN_H = 360           # 두 칸 최소 높이
PANE_GAP = 6               # 칸과 ⇒ 사이
ARROW_PX = 32              # 가운데 ⇒ 그림 크기(`themed_icon("arrow_right")`)
FULL_KEY = "F11"           # 크롭 창 전체 화면 켜고 끄기(앱 단축키와 겹치지 않는다 — 발표 보기는 F5)
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


class PhotoCropCanvas(CropCanvas):
    """사진 크롭 화면 — PDF 크롭 화면(`CropCanvas`)에 **박스 통째로 옮기기**를 더한 것(261106-7 사용자 지시 '중간을 잡고
    박스를 이동'). 귀·변 끌기는 그대로, 박스 안쪽을 끌면 크기 그대로 옮기고 사진 밖으로는 나가지 않는다. PDF 크롭 창은 그대로."""

    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)
        if self._drag is None and self._editable and self._inside_box(ev.position()):
            self._drag = "move"
            self._move_from = (ev.position().x(), ev.position().y(), list(self._m))
            self.setCursor(Qt.CursorShape.SizeAllCursor)

    def _inside_box(self, pos) -> bool:
        r = self._img_rect()
        if r.isNull():
            return False
        return self._crop_rect(r).contains(pos)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is None and self._editable and self._hit(pos) is None and self._inside_box(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)   # 이동 모양 — 귀·변 위는 아래(부모)가 정한다
            return
        if self._drag != "move":
            return super().mouseMoveEvent(ev)
        r = self._img_rect()
        if r.isNull():
            return
        x0, y0, m0 = self._move_from
        self._m = move_margins(m0, (pos.x() - x0) / r.width() * 100.0, (pos.y() - y0) / r.height() * 100.0)
        self.update()
        self.marginsDragged.emit(list(self._m))


def r1_list(m) -> list:
    return [round(float(v), 1) for v in m]


def move_margins(m, dx: float, dy: float) -> list:
    """여백 [위, 아래, 왼, 오른] % 의 박스를 크기 그대로 (dx, dy) % 옮긴다 — 사진 밖으로 나가지 않게(각 여백 ≥ 0)."""
    t, b, l, r = (float(v) for v in m)
    dx = max(-l, min(r, dx))
    dy = max(-t, min(b, dy))
    return [round(t + dy, 1), round(b - dy, 1), round(l + dx, 1), round(r - dx, 1)]


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
        self._touched = set()                  # 이 창에서 크롭 박스를 손으로 고친 사진 번호(261106-7)
        self._warp_box = {}                    # 번호 → 점을 놓을 때의 박스(여백 %) — 그 뒤 박스를 고치면 다시 켤 때 새 박스로
        self._loading = False
        self.geometry_state = None             # 닫을 때의 창 자리·최대화(전체 화면은 풀고) — 쓰는 쪽이 기억(261106-8)
        # 261106-8(사용자 지시 '창 배치·⇒ 그림·전체 화면'): 제목 줄 최대화 단추 + 크기 조절 손잡이
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        root = QVBoxLayout(self)
        self.stack = QStackedWidget(self)
        self.canvas = PhotoCropCanvas(self)
        self.warp = WarpCanvas(self)
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.warp)
        # 배치(디자인 SOT §2.21): [왼쪽 = 고치는 칸] [⇒] [오른쪽 = 결과 칸] — 두 칸은 같은 폭, 창 가운데를 두고 대칭.
        #   그 아래 왼쪽 칸 폭에 ❮ ❯·여백 칸·모양 펴기 줄을 가운데로, 오른쪽 칸 폭에 안내 글. 단추 줄은 창 폭.
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(PANE_GAP)
        for w in (self.stack,):
            w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.grid.addWidget(self.stack, 0, 0)
        self.arrow = QLabel(self)
        self.arrow.setObjectName("cropArrow")
        self.arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arrow.setToolTip(tr("왼쪽에서 고친 대로 오른쪽처럼 됩니다"))
        self.arrow.setAccessibleName(tr("결과"))
        self.arrow.setFixedWidth(ARROW_PX + 8)
        self._paint_arrow()
        self.grid.addWidget(self.arrow, 0, 1)
        self.result = QLabel(self)
        self.result.setObjectName("cropResult")
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result.setToolTip(tr("결과 미리보기"))
        self.result.setAccessibleName(tr("결과 미리보기"))
        self.result.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)   # 테두리 없음 — 왼쪽 칸과 같게
        self.grid.addWidget(self.result, 0, 2)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(2, 1)
        self.grid.setRowStretch(0, 1)
        self.grid.setRowMinimumHeight(0, PANE_MIN_H)
        root.addLayout(self.grid, 1)
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
        left = QVBoxLayout()                   # 왼쪽 칸 아래 — 모두 그 칸 가운데(❮ ❯ 와 같은 기준선)
        left.addLayout(centered_row(self.nav))
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
        row.addStretch(1)
        row.addLayout(grid)
        row.addStretch(1)
        left.addLayout(row)
        wrow = QHBoxLayout()                   # 옵션 — 모양 펴기(261106-6)
        wrow.addStretch(1)
        self.chk_warp = QCheckBox(tr("모양 펴기 (원근·휜 테두리)"), self)
        self.chk_warp.setToolTip(tr("비스듬히 찍었거나 가운데가 휜 사진을 테두리에 맞춰 직사각형으로 펼칩니다."))
        self.chk_warp.toggled.connect(self._warp_toggled)
        self.btn_detect = QPushButton(tr("테두리 찾기"), self)
        self.btn_detect.clicked.connect(self._on_detect)
        self.btn_corners = QPushButton(tr("점 처음대로"), self)
        self.btn_corners.setToolTip(tr("점을 처음 자리로 — 크롭 박스를 고쳐 두었으면 그 박스 네 귀, 아니면 사진 네 귀퉁이 가까이."))
        self.btn_corners.clicked.connect(lambda: self._set_warp_points(self._start_points(box_first=True)))
        wrow.addWidget(self.chk_warp)
        wrow.addWidget(self.btn_detect)
        wrow.addWidget(self.btn_corners)
        wrow.addStretch(1)
        left.addLayout(wrow)
        left.addStretch(1)
        right = QVBoxLayout()                  # 오른쪽 칸 아래 — 안내 글
        self.note_warp = QLabel(tr("꼭짓점(네모)을 끌어 테두리에 맞추고, 휜 변은 가운데 점(동그라미)을 끕니다 — [확인] 이면 펼친 그림을 새 사진으로 저장합니다(원본은 그대로)."), self)
        self.note_warp.setWordWrap(True)
        right.addWidget(self.note_warp)
        self.note = QLabel(tr("원본 사진은 그대로 두고 자른 모양만 기억합니다 — 사진 → PDF·인쇄·평탄화·공유용 사본·사진 복사도 자른 모양으로 나옵니다."), self)
        self.note.setWordWrap(True)
        right.addWidget(self.note)
        self.note_many = QLabel(tr("❮ ❯ 로 넘기면 고친 크롭을 기억해 두었다가 [확인] 때 한꺼번에 적용합니다 — 크롭이 없는 사진은 최근에 정한 크롭을 미리 겁니다."), self)
        self.note_many.setWordWrap(True)
        self.note_many.setVisible(self._count > 1)
        right.addWidget(self.note_many)
        right.addStretch(1)
        self.grid.addLayout(left, 1, 0)
        self.grid.addLayout(right, 1, 2)
        lw = max(left.minimumSize().width(), PANE_MIN_W)
        self.grid.setColumnMinimumWidth(0, lw)             # 두 칸 최소 폭을 같게 — 그래야 늘어도 같은 폭(대칭)
        self.grid.setColumnMinimumWidth(2, lw)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.btn_full = bb.addButton(tr("전체 화면 (F11)"), QDialogButtonBox.ButtonRole.ResetRole)   # 왼쪽 — [확인]·[취소] 사이에 끼지 않게
        self.btn_full.setCheckable(True)
        self.btn_full.setToolTip(tr("크롭 창을 화면 가득 — 다시 누르거나 F11·Esc 로 돌아옵니다."))
        self.btn_full.toggled.connect(self._set_full)
        self.btn_reset = bb.addButton(tr("크롭 해제"), QDialogButtonBox.ButtonRole.ResetRole)
        self.btn_reset.clicked.connect(self._on_reset)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        from PyQt6.QtGui import QShortcut, QKeySequence
        self._sc_full = QShortcut(QKeySequence(FULL_KEY), self)
        self._sc_full.activated.connect(self.btn_full.toggle)
        self.canvas.marginsDragged.connect(self._box_dragged)
        self.show_photo(self._index, img, margins, has_crop, title, auto_pts)

    # ── 창 배치·전체 화면(261106-8) ─────────────────────
    def _paint_arrow(self) -> None:
        from viewer.widgets.icons import themed_icon
        dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        self.arrow.setPixmap(themed_icon("arrow_right", size=ARROW_PX, dpr=dpr).pixmap(ARROW_PX, ARROW_PX))

    def changeEvent(self, ev):
        super().changeEvent(ev)
        from PyQt6.QtCore import QEvent
        if ev.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange) and hasattr(self, "arrow"):
            self._paint_arrow()                          # 테마가 바뀌면 ⇒ 색도(디자인 SOT 아이콘 규칙)
        if ev.type() == QEvent.Type.WindowStateChange and hasattr(self, "btn_full"):
            full = self.isFullScreen()
            if self.btn_full.isChecked() != full:
                self.btn_full.blockSignals(True)
                self.btn_full.setChecked(full)
                self.btn_full.blockSignals(False)

    def _set_full(self, on: bool) -> None:
        if on:
            self._pre_full_max = self.isMaximized()
            self.showFullScreen()
        elif self.__dict__.get("_pre_full_max"):
            self.showMaximized()
        else:
            self.showNormal()
        self._fit_result()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.btn_full.setChecked(False)              # 전체 화면에서 Esc = 전체 화면만 푼다(창은 그대로)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def restore_state(self, geom_hex: str = "", maximized: bool = False) -> None:
        """지난번 크롭 창 자리·크기·최대화(쓰는 쪽이 기억한 것) — 전체 화면은 다시 열 때 늘 푼 채로."""
        if geom_hex:
            try:
                from PyQt6.QtCore import QByteArray
                self.restoreGeometry(QByteArray(bytes.fromhex(geom_hex)))
            except (ValueError, TypeError):
                pass
        if maximized:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def done(self, r):
        if self.isFullScreen():                          # 전체 화면은 기억하지 않는다 — 푼 뒤의 자리를 남긴다
            self.btn_full.setChecked(False)
        try:
            self.geometry_state = (bytes(self.saveGeometry()).hex(), bool(self.isMaximized()))
        except Exception:
            self.geometry_state = None
        super().done(r)

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
        self.warp.set_points(self._warp_pts.get(self._index) or self._start_points())
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
        if self.chk_warp.isChecked():                    # 켠 채 놓은 점만 그 사진의 점 — 끈 동안 박스를 고치면 다시 켤 때 박스로
            self._warp_pts[self._index] = self.warp.points()
            self._warp_box[self._index] = r1_list(self.current_margins())

    def _box_adjusted(self) -> bool:
        """지금 사진의 크롭 박스가 '조절해 둔' 것인가(261106-7) — 이 창에서 손으로 고쳤거나 그 사진의 크롭이 있고, 사진 전체가 아닐 때.
        미리 건 최근 크롭(261106-3)만으로는 아니다 — 그런 사진은 자동 어림."""
        return ((self._index in self._touched or self._has_crop)
                and any(v > 0 for v in self.current_margins()))

    def _box_points(self) -> list:
        t, b, l, r = (v / 100.0 for v in self.current_margins())
        c = [(l, t), (1.0 - r, t), (1.0 - r, 1.0 - b), (l, 1.0 - b)]
        return c + pw.mids_of(c)                         # 변 가운데 점은 각 변 가운데(곧은 변)

    def _start_points(self, box_first: bool = False) -> list:
        """모양 펴기의 처음 점(261106-7 사용자 지시 '박스를 조절 후 모양 펴기를 체크하면 조절된 박스의 점 위치를 초기 위치로') —
        조절해 둔 박스가 있으면 그 네 귀, 없으면 자동 어림(못 찾으면 기본 점). `box_first`([점 처음대로])는 어림 대신 기본 점."""
        if self._box_adjusted():
            return self._box_points()
        if box_first or self._auto is None:
            return pw.default_points()
        return list(self._auto)

    def _set_warp_points(self, pts) -> None:
        self.warp.set_points(pts)
        self._prev_timer.start()

    def _warp_toggled(self, on: bool) -> None:
        self._warp_on[self._index] = bool(on)
        box = r1_list(self.current_margins())
        if on:
            # 이 사진에서 처음 켜거나, 점을 놓은 뒤 박스를 다시 고쳤으면 — 지금 박스(조절했으면)·어림으로(261106-7)
            if self._index not in self._warp_pts or self._warp_box.get(self._index) != box:
                self._set_warp_points(self._start_points())
            self._warp_box[self._index] = box
        else:
            self._warp_pts[self._index] = self.warp.points()   # 끄기 전 점 — 박스를 그대로 두고 다시 켜면 그 점
            self._warp_box[self._index] = box
        self._apply_warp_ui()

    def _apply_warp_ui(self) -> None:
        on = self.chk_warp.isChecked()
        self.stack.setCurrentWidget(self.warp if on else self.canvas)
        for sp in self.spins:
            sp.setEnabled(not on)
        # 두 단추는 늘 보이고 켰을 때만 눌린다(261106-8) — 숨기면 켜고 끌 때마다 줄이 옆으로 움직였다
        self.btn_detect.setEnabled(on and self._auto is not None)
        self.btn_detect.setToolTip(tr("어림한 테두리로 점을 놓습니다.") if self._auto is not None
                                   else tr("이 사진에서는 테두리를 찾지 못했습니다 — 점을 끌어 맞추세요."))
        self.btn_corners.setEnabled(on)
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
            self._set_warp_points(self._auto)            # [테두리 찾기] = 늘 자동 어림(박스와 무관)

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

    def _box_dragged(self, m):
        self._touched.add(self._index)                   # 손으로 고친 박스(261106-7)
        self._dragged(m)

    def _spin_changed(self, k: int):
        self._touched.add(self._index)
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
