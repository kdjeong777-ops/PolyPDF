"""화면 영역 캡처 오버레이 (260606-17 → 261014-18 '영역 캡처', 스크린샷 SOT §3.1).

- mode='region'(영역 캡처): **누른 채 끌어 놓기** 로 영역(클릭 두 번 — 한 모서리·맞은편 모서리 — 도 된다).
  시작 단계에서 Enter/Space = 지난 영역(`last_region`, 같은 화면일 때).
- mode='fixed'(사용자 크기): 클릭한 곳을 좌상단으로 그 크기 상자를 놓는다.
- 고치기 단계: 안쪽 끌기 = 옮기기, 꼭짓점·변 끌기 = 크기, 화살표 = 1 px(Shift 10 px), Ctrl+화살표 = 크기.
- 확정: Enter 또는 더블클릭. 취소: Esc, 오른쪽 클릭(고치기 단계에서는 다시 고르기).
- copy_mode='visible'(보이는 크기, 논리 픽셀) / 'original'(원본 = 장치 픽셀).

grab() 가 QPixmap(또는 None)을 반환(로컬 이벤트 루프). 끝난 뒤 `region_out` = `[x, y, w, h, 화면 이름]`(영역 캡처일 때).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRect, QPoint, QEventLoop, QSize
from PyQt6.QtGui import QPainter, QColor, QPen, QGuiApplication, QPixmap, QCursor
from PyQt6.QtWidgets import QWidget
from viewer.i18n import tr

_HANDLE = 8        # 핸들 히트 반경(px)
_MIN = 12          # 최소 박스 크기
DRAG_MIN = 4       # 이보다 덜 끌었으면 클릭으로 본다(클릭 두 번 방식) — 스크린샷 SOT §3.1


class RegionCaptureOverlay(QWidget):
    def __init__(self, mode: str = "region", fixed_size=None,
                 copy_mode: str = "visible", parent=None, last_region=None):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._mode = mode
        self._fixed = QSize(*fixed_size) if fixed_size else QSize(300, 200)
        self._copy_mode = copy_mode
        self._result: Optional[QPixmap] = None
        self._loop: Optional[QEventLoop] = None
        self.region_out = None

        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self._screen = scr
        self._dpr = scr.devicePixelRatio()
        self._bg = scr.grabWindow(0)                 # 장치픽셀 픽스맵
        geo = scr.geometry()
        self.setGeometry(geo)

        self._rect = QRect()           # 현재 선택 박스(위젯 좌표)
        self._phase = "place"          # place → (region: sizing) → edit
        self._drag = None              # 'move' | 'tl','tr','bl','br','l','r','t','b'
        self._drag_off = QPoint()
        self._origin = QPoint()
        self._pressed = False          # sizing 중 누른 채인가(끌어 고르기)
        self._last = None              # 지난 영역(같은 화면일 때만)
        try:
            if mode == "region" and last_region and len(last_region) == 5 \
                    and str(last_region[4]) == scr.name():
                x, y, w, h = (int(v) for v in last_region[:4])
                r = QRect(x, y, w, h).intersected(QRect(QPoint(0, 0), geo.size()))
                if r.width() >= _MIN and r.height() >= _MIN:
                    self._last = r
        except Exception:
            self._last = None

    # ── 공개 ──────────────────────────────────────────────────
    def grab(self) -> Optional[QPixmap]:
        self.showFullScreen()
        self.activateWindow()
        self.raise_()
        self.setFocus()
        self._loop = QEventLoop()
        self._loop.exec()
        return self._result

    def _finish(self, ok: bool):
        if ok and self._rect.isValid() and self._rect.width() >= _MIN and self._rect.height() >= _MIN:
            r = self._rect.normalized()
            # 위젯 좌표 → 장치픽셀
            dp = QRect(int(r.x() * self._dpr), int(r.y() * self._dpr),
                       int(r.width() * self._dpr), int(r.height() * self._dpr))
            pm = self._bg.copy(dp)
            if self._copy_mode == "visible" and self._dpr != 1.0:
                pm = pm.scaled(r.width(), r.height(),
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            self._result = pm
            if self._mode == "region":
                self.region_out = [r.x(), r.y(), r.width(), r.height(), self._screen.name()]
        else:
            self._result = None
        self.close()
        if self._loop:
            self._loop.quit()

    # ── 안내 ──────────────────────────────────────────────────
    def hint(self) -> str:
        """지금 단계에서 되는 조작만(스크린샷 SOT §3.1 표와 같은 말)."""
        if self._phase == "place":
            if self._mode == "fixed":
                return tr('클릭 = {w}×{h} 상자 놓기 · Esc·오른쪽 클릭 = 취소').format(
                    w=self._fixed.width(), h=self._fixed.height())
            s = tr("끌어서 영역 고르기(클릭 두 번도 됩니다) · Esc·오른쪽 클릭 = 취소")
            if self._last is not None:
                s += tr(" · Enter = 지난 영역")
            return s
        if self._phase == "sizing":
            return tr("놓거나 한 번 더 클릭하면 영역이 정해집니다 · Esc·오른쪽 클릭 = 취소")
        return tr("Enter·더블클릭 = 캡처 · 끌기 = 옮기기·크기 · 화살표 = 1px(Shift 10px, Ctrl 크기) · "
                  "오른쪽 클릭 = 다시 고르기 · Esc = 취소")

    # ── 그리기 ────────────────────────────────────────────────
    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self._bg, self._bg.rect())   # 화면 배경
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))          # 어둡게
        if self._rect.isValid():
            r = self._rect.normalized()
            p.drawPixmap(r, self._bg, QRect(
                int(r.x() * self._dpr), int(r.y() * self._dpr),
                int(r.width() * self._dpr), int(r.height() * self._dpr)))  # 선택영역 밝게
            p.setPen(QPen(QColor("#2a7de1"), 2))
            p.drawRect(r)
            if self._phase == "edit":                              # 손잡이는 고칠 수 있을 때만
                p.setBrush(QColor("#2a7de1"))
                for hp in self._handle_points(r).values():
                    p.drawRect(QRect(hp.x() - 3, hp.y() - 3, 6, 6))
            # 크기 — 끄는 동안·고치는 동안
            p.setPen(QColor("white"))
            p.drawText(r.x(), max(12, r.y() - 6), f"{r.width()} × {r.height()}")
        # 안내 — 어두운 띠 위에
        txt = self.hint()
        fm = p.fontMetrics()
        p.fillRect(QRect(8, 6, fm.horizontalAdvance(txt) + 16, fm.height() + 10), QColor(0, 0, 0, 170))
        p.setPen(QColor("white"))
        p.drawText(16, 6 + 5 + fm.ascent(), txt)

    def _handle_points(self, r: QRect) -> dict:
        cx, cy = r.center().x(), r.center().y()
        return {
            "tl": r.topLeft(), "tr": r.topRight(),
            "bl": r.bottomLeft(), "br": r.bottomRight(),
            "t": QPoint(cx, r.top()), "b": QPoint(cx, r.bottom()),
            "l": QPoint(r.left(), cy), "r": QPoint(r.right(), cy),
        }

    def _hit_handle(self, pos: QPoint):
        if not self._rect.isValid():
            return None
        for name, hp in self._handle_points(self._rect.normalized()).items():
            if abs(pos.x() - hp.x()) <= _HANDLE and abs(pos.y() - hp.y()) <= _HANDLE:
                return name
        if self._rect.normalized().contains(pos):
            return "move"
        return None

    def _to_edit(self, r: QRect):
        self._rect = r.normalized()
        self._phase = "edit"
        self._pressed = False
        self.update()

    # ── 마우스 ────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            if self._phase == "edit" and self._mode == "region":   # 다시 고르기
                self._rect = QRect()
                self._phase = "place"
                self.setCursor(Qt.CursorShape.CrossCursor)
                self.update()
            else:
                self._finish(False)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        if self._phase == "place":
            if self._mode == "fixed":
                w = min(self._fixed.width(), self.width())
                h = min(self._fixed.height(), self.height())
                self._to_edit(QRect(pos, QSize(w, h)))
            else:
                self._origin = pos
                self._rect = QRect(pos, QSize(1, 1))
                self._phase = "sizing"
                self._pressed = True
                self.update()
            return
        if self._phase == "sizing":
            # 클릭 두 번 방식 — 두 번째 클릭이 맞은편 모서리
            self._to_edit(QRect(self._origin, pos))
            return
        # edit: 핸들/이동 시작
        h = self._hit_handle(pos)
        self._drag = h
        if h == "move":
            self._drag_off = pos - self._rect.normalized().topLeft()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._phase == "sizing":
            self._rect = QRect(self._origin, pos)
            self.update()
            return
        if self._phase == "edit" and self._drag:
            r = self._rect.normalized()
            if self._drag == "move":
                np = pos - self._drag_off
                np.setX(max(0, min(np.x(), self.width() - r.width())))
                np.setY(max(0, min(np.y(), self.height() - r.height())))
                self._rect = QRect(np, r.size())
            else:
                l, t, rr, b = r.left(), r.top(), r.right(), r.bottom()
                if "l" in self._drag:
                    l = min(pos.x(), rr - _MIN)
                if "r" in self._drag:
                    rr = max(pos.x(), l + _MIN)
                if "t" in self._drag:
                    t = min(pos.y(), b - _MIN)
                if "b" in self._drag:
                    b = max(pos.y(), t + _MIN)
                self._rect = QRect(QPoint(l, t), QPoint(rr, b))
            self.update()
            return
        # edit 중 커서 모양
        if self._phase == "edit":
            h = self._hit_handle(pos)
            self.setCursor(self._cursor_for(h))

    def mouseReleaseEvent(self, e):
        self._drag = None
        if self._phase == "sizing" and self._pressed and e.button() == Qt.MouseButton.LeftButton:
            pos = e.position().toPoint()
            self._pressed = False
            d = pos - self._origin
            if abs(d.x()) >= DRAG_MIN or abs(d.y()) >= DRAG_MIN:     # 끌어 놓기 — 영역이 정해진다
                self._to_edit(QRect(self._origin, pos))
            # 아니면 클릭 — 두 번째 클릭을 기다린다(클릭 두 번 방식)

    def mouseDoubleClickEvent(self, e):
        if self._phase == "edit" and e.button() == Qt.MouseButton.LeftButton:
            self._finish(True)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self._finish(False)
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._phase == "edit":
                if k != Qt.Key.Key_Space:
                    self._finish(True)
            elif self._phase == "place" and self._last is not None:
                self._to_edit(QRect(self._last))               # 지난 영역
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                  Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if self._phase == "edit" and k in arrows:
            dx, dy = arrows[k]
            step = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            r = self._rect.normalized()
            if e.modifiers() & Qt.KeyboardModifier.ControlModifier:      # 크기
                w = max(_MIN, min(self.width() - r.x(), r.width() + dx * step))
                h = max(_MIN, min(self.height() - r.y(), r.height() + dy * step))
                self._rect = QRect(r.topLeft(), QSize(w, h))
            else:                                                         # 옮기기
                x = max(0, min(self.width() - r.width(), r.x() + dx * step))
                y = max(0, min(self.height() - r.height(), r.y() + dy * step))
                self._rect = QRect(QPoint(x, y), r.size())
            self.update()

    @staticmethod
    def _cursor_for(h):
        if h in ("tl", "br"):
            return Qt.CursorShape.SizeFDiagCursor
        if h in ("tr", "bl"):
            return Qt.CursorShape.SizeBDiagCursor
        if h in ("l", "r"):
            return Qt.CursorShape.SizeHorCursor
        if h in ("t", "b"):
            return Qt.CursorShape.SizeVerCursor
        if h == "move":
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.CrossCursor
