"""화면 영역 캡쳐 오버레이 (260606-17).

- mode='region'(지정): 좌클릭으로 좌상단 지정→마우스로 크기→좌클릭으로 우하단 확정.
- mode='fixed'(사용자 크기): 좌클릭 지점을 좌상단으로 지정 크기 박스 생성.
- 생성된 박스: 내부 드래그 이동, 꼭지점/변 드래그 리사이즈.
- 확정: Enter 또는 좌더블클릭 → 그 영역의 화면 픽스맵 반환. 취소: Esc.
- copy_mode='visible'(보이는 크기, 논리픽셀) / 'original'(원본=장치픽셀).

grab() 가 QPixmap(또는 None)을 반환(로컬 이벤트루프).
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QRect, QPoint, QEventLoop, QSize
from PyQt6.QtGui import QPainter, QColor, QPen, QGuiApplication, QPixmap, QCursor
from PyQt6.QtWidgets import QWidget

_HANDLE = 8        # 핸들 히트 반경(px)
_MIN = 12          # 최소 박스 크기


class RegionCaptureOverlay(QWidget):
    def __init__(self, mode: str = "region", fixed_size=None,
                 copy_mode: str = "visible", parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._mode = mode
        self._fixed = QSize(*fixed_size) if fixed_size else QSize(300, 200)
        self._copy_mode = copy_mode
        self._result: Optional[QPixmap] = None
        self._loop: Optional[QEventLoop] = None

        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self._screen = scr
        self._dpr = scr.devicePixelRatio()
        self._bg = scr.grabWindow(0)                 # 장치픽셀 픽스맵
        geo = scr.geometry()
        self.setGeometry(geo)

        self._rect = QRect()           # 현재 선택 박스(위젯 좌표)
        self._phase = "place"          # place→(region:sizing)→edit
        self._drag = None              # 'move' | 'tl','tr','bl','br','l','r','t','b'
        self._drag_off = QPoint()
        self._origin = QPoint()

    # ── 공개 ──────────────────────────────────────────────────
    def grab(self) -> Optional[QPixmap]:
        self.showFullScreen()
        self.activateWindow()
        self.raise_()
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
        else:
            self._result = None
        self.close()
        if self._loop:
            self._loop.quit()

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
            # 핸들
            p.setBrush(QColor("#2a7de1"))
            for hp in self._handle_points(r).values():
                p.drawRect(QRect(hp.x() - 3, hp.y() - 3, 6, 6))
            # 크기 표시 + 안내(같은 폰트, 크기 텍스트 오른쪽) — 260611-15
            p.setPen(QColor("white"))
            size_txt = f"{r.width()} × {r.height()}"
            if self._phase == "edit":
                size_txt += "    사이즈 설정 후 더블클릭하여 캡쳐하세요"
            p.drawText(r.x(), max(12, r.y() - 6), size_txt)
        # 안내
        p.setPen(QColor("white"))
        hint = ("좌클릭=좌상단 지정" if self._phase == "place"
                else "Enter/더블클릭=캡쳐, 드래그=이동/크기조절, Esc=취소")
        p.drawText(16, 24, hint)

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

    # ── 마우스 ────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        if self._phase == "place":
            if self._mode == "fixed":
                w = min(self._fixed.width(), self.width())
                h = min(self._fixed.height(), self.height())
                self._rect = QRect(pos, QSize(w, h))
                self._phase = "edit"
            else:
                self._origin = pos
                self._rect = QRect(pos, QSize(1, 1))
                self._phase = "sizing"
            self.update()
            return
        if self._phase == "sizing":
            # 두 번째 클릭 = 우하단 확정
            self._rect = QRect(self._origin, pos).normalized()
            self._phase = "edit"
            self.update()
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

    def mouseDoubleClickEvent(self, e):
        if self._phase == "edit" and e.button() == Qt.MouseButton.LeftButton:
            self._finish(True)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._phase == "edit":
                self._finish(True)
        elif e.key() == Qt.Key.Key_Escape:
            self._finish(False)

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
