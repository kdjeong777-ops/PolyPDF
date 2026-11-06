# -*- coding: utf-8 -*-
"""사진 모양 펴기 — 점 끌기 화면 (사진 보기 SOT §4.43, 261106-6 사용자 지시).

사진 전체를 그리고 테두리 밖을 어둡게. 꼭짓점 넷(네모 손잡이)을 끌어 테두리를 맞추고, 변이 휘었으면 변 가운데 점(동그라미)을
끌어 그 변을 휜다(2차 곡선이 그 점을 지난다 — `photo_warp`). 변 가운데 점을 건드리지 않은 변은 곧은 채라 꼭짓점을 옮기면
가운데 점도 따라간다. 좌표는 그림 비율(0..1, 보이는 방향).
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from viewer import photo_warp as pw

HANDLE_PX = 7               # 손잡이 반지름(화면 화소)
GRAB_PX = 11                # 이만큼 안을 누르면 그 손잡이
LINE_COLOR = "#e53935"      # 크롭 창 선과 같은 빨강(디자인 SOT §2.20 크롭 창)
MID_COLOR = "#1565c0"       # 변 가운데 점 — 나눔선과 같은 파랑
SHADE = (0, 0, 0, 110)      # 테두리 밖 어둡게 — 크롭 창과 같은 값


class WarpCanvas(QWidget):
    pointsDragged = pyqtSignal(object)        # 점 8개(비율)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 420)
        self.setMouseTracking(True)
        self._img = None
        self._pts = pw.default_points()
        self._drag = None

    # ── 값 ───────────────────────────────────────────
    def set_image(self, img):
        self._img = img
        self.update()

    def set_points(self, pts):
        self._pts = pw.clamp_points(pts or pw.default_points())
        self.update()

    def points(self) -> list:
        return list(self._pts)

    # ── 자리 ─────────────────────────────────────────
    def _img_rect(self) -> QRectF:
        if self._img is None or self._img.isNull():
            return QRectF()
        W, H = self.width() - 2 * GRAB_PX, self.height() - 2 * GRAB_PX
        s = min(W / self._img.width(), H / self._img.height())
        w, h = self._img.width() * s, self._img.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_screen(self, p, r: QRectF) -> QPointF:
        return QPointF(r.left() + p[0] * r.width(), r.top() + p[1] * r.height())

    def _outline(self, r: QRectF) -> QPainterPath:
        tl, trc, br, bl, tm, rm, bm, lm = self._pts
        path = QPainterPath()
        path.moveTo(self._to_screen(tl, r))
        n = 24
        for p0, mid, p2 in ((tl, tm, trc), (trc, rm, br), (br, bm, bl), (bl, lm, tl)):
            for i in range(1, n + 1):
                path.lineTo(self._to_screen(pw._quad_curve(p0, mid, p2, i / n), r))
        path.closeSubpath()
        return path

    # ── 그리기 ───────────────────────────────────────
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), self.palette().window())
        r = self._img_rect()
        if r.isNull():
            p.end()
            return
        p.drawImage(r, self._img)
        out = QPainterPath()
        out.addRect(r)
        shape = self._outline(r)
        p.fillPath(out.subtracted(shape), QColor(*SHADE))
        p.setPen(QPen(QColor(LINE_COLOR), 2))
        p.drawPath(shape)
        for i, q in enumerate(self._pts):
            c = self._to_screen(q, r)
            if i < 4:
                p.setBrush(QColor("#ffffff"))
                p.setPen(QPen(QColor(LINE_COLOR), 2))
                p.drawRect(QRectF(c.x() - HANDLE_PX, c.y() - HANDLE_PX, 2 * HANDLE_PX, 2 * HANDLE_PX))
            else:
                p.setBrush(QColor("#ffffff"))
                p.setPen(QPen(QColor(MID_COLOR), 2))
                p.drawEllipse(c, HANDLE_PX - 1, HANDLE_PX - 1)
        p.end()

    # ── 끌기 ─────────────────────────────────────────
    def _hit(self, pos):
        r = self._img_rect()
        if r.isNull():
            return None
        best, bd = None, GRAB_PX + 1
        for i, q in enumerate(self._pts):          # 꼭짓점을 먼저(겹치면 꼭짓점)
            c = self._to_screen(q, r)
            d = math.hypot(c.x() - pos.x(), c.y() - pos.y())
            if d < bd - (0.5 if i < 4 else 0):
                best, bd = i, d
        return best

    def mousePressEvent(self, ev):
        self._drag = self._hit(ev.position())

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is None:
            self.setCursor(Qt.CursorShape.SizeAllCursor if self._hit(pos) is not None else Qt.CursorShape.ArrowCursor)
            return
        r = self._img_rect()
        if r.isNull():
            return
        x = min(1.0, max(0.0, (pos.x() - r.left()) / r.width()))
        y = min(1.0, max(0.0, (pos.y() - r.top()) / r.height()))
        self.move_point(self._drag, (x, y))

    def move_point(self, i: int, xy) -> None:
        """점 하나를 옮긴다 — 꼭짓점이면 곧은 채였던 이웃 변의 가운데 점도 따라간다. 꼬이면 옮기지 않는다."""
        pts = list(self._pts)
        if i < 4:
            straight_before = pw.mids_of(pts[:4])
            follow = [math.hypot(pts[4 + k][0] - straight_before[k][0], pts[4 + k][1] - straight_before[k][1])
                      <= pw.STRAIGHT_TOL for k in range(4)]
            pts[i] = tuple(xy)
            straight_after = pw.mids_of(pts[:4])
            for k in range(4):
                if follow[k]:
                    pts[4 + k] = straight_after[k]
        else:
            pts[i] = tuple(xy)
        if not pw.is_valid(pts):
            return
        self._pts = pts
        self.update()
        self.pointsDragged.emit(list(pts))

    def mouseReleaseEvent(self, ev):
        self._drag = None
