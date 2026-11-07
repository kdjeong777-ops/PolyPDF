# -*- coding: utf-8 -*-
"""오른쪽 패널 열고 닫기 띠 — 본문 스크롤바 **밖** (261107-15, 사용자 결정 '스크롤바 밖 옅은 띠', 디자인 SOT §2.4.1).

종전 손잡이(QToolButton, 폭 = 스크롤바 − 4px)는 본문 세로 스크롤바 위에 겹쳐 그려졌다. 이 띠는 본문 오른쪽 끝 바깥의
자기 자리(레이아웃이 비워 둔 `BAND_W`)에 놓이고, 띠 어디를 눌러도 열고 닫는다. 색은 디자인 SOT §2.5 토큰(그릴 때 테마를 읽는다).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QColor, QPainter, QFont
from PyQt6.QtWidgets import QWidget

BAND_W = 10          # 띠 폭(px)

# 디자인 SOT §2.5 — (다크, 라이트)
PANEL_BG = ("#484848", "#e2e2e2")
HOVER_BG = ("#5a5a5a", "#a8a8a8")      # '테두리'
ICON_FG = ("#e8e8e8", "#444444")       # '아이콘 전경'


def _tok(pair) -> str:
    try:
        from viewer import theme
        dark = theme.is_dark()
    except Exception:
        dark = False
    return pair[0] if dark else pair[1]


class DrawerBand(QWidget):
    toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("drawerBand")
        self._open = False
        self._hover = False
        self.setFixedWidth(BAND_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self._sync_tip()

    def _sync_tip(self):
        from viewer.i18n import tr
        self.setToolTip(tr("오른쪽 패널 펼치기/접기"))
        self.setAccessibleName(tr("오른쪽 패널 펼치기/접기"))

    def set_open(self, on: bool) -> None:
        self._open = bool(on)
        self.update()

    def is_open(self) -> bool:
        return self._open

    def glyph(self) -> str:
        return "›" if self._open else "‹"

    def colors(self):
        """(바탕, 글자) — 지금 테마·hover 의 토큰 값(검사용으로도 쓴다)."""
        return (_tok(HOVER_BG) if self._hover else _tok(PANEL_BG)), _tok(ICON_FG)

    # ── 그리기 ──
    def paintEvent(self, _ev):
        bg, fg = self.colors()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(bg))
        if self.hasFocus():
            p.setPen(QColor(fg))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor(fg))
        p.drawText(QRectF(self.rect()), int(Qt.AlignmentFlag.AlignCenter), self.glyph())
        p.end()

    # ── 입력 ──
    def enterEvent(self, ev):
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.toggled.emit()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.toggled.emit()
            ev.accept()
            return
        super().keyPressEvent(ev)
