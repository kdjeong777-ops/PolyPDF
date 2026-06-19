"""테마 대응 단색(라인) 아이콘 — 화면 디자인 통일용 (260616-14).

규칙(작업계획서 '화면 디자인 작업 계획서.md' 참조):
- 모든 아이콘은 단색 라인 스타일로 통일.
- **다크 모드 = 밝은 회색(흰색 계열)**, 라이트 모드 = 짙은 회색.
- 리소스 PNG 의존 없이 QPainter 로 그려, 어떤 테마/배율에서도 또렷하게.

사용: `from viewer.widgets.icons import themed_icon` → `btn.setIcon(themed_icon("globe"))`.
새 아이콘은 `_DRAW` 에 그리기 함수를 추가하면 곧바로 themed_icon 으로 쓸 수 있다.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPolygonF


def fg_color(dark: bool | None = None) -> str:
    """현재(또는 지정) 테마의 아이콘 전경색."""
    if dark is None:
        try:
            from viewer import theme
            dark = theme.is_dark()
        except Exception:
            dark = False
    return "#e8e8e8" if dark else "#444444"


# --- 개별 그리기(16x16 캔버스, p=QPainter, c=QColor) -----------------------

def _search(p, c):
    p.setPen(QPen(c, 1.7))
    p.drawEllipse(QPointF(6.3, 6.3), 4.0, 4.0)
    p.drawLine(QPointF(9.4, 9.4), QPointF(14.0, 14.0))


def _globe(p, c):
    p.setPen(QPen(c, 1.4))
    p.drawEllipse(QPointF(8, 8), 6.2, 6.2)
    p.drawEllipse(QPointF(8, 8), 2.6, 6.2)      # 세로 자오선
    p.drawLine(QPointF(1.9, 8), QPointF(14.1, 8))
    p.drawLine(QPointF(3.0, 4.4), QPointF(13.0, 4.4))
    p.drawLine(QPointF(3.0, 11.6), QPointF(13.0, 11.6))


def _close(p, c):
    p.setPen(QPen(c, 1.8))
    p.drawLine(QPointF(4, 4), QPointF(12, 12))
    p.drawLine(QPointF(12, 4), QPointF(4, 12))


def _chevron_up(p, c):
    p.setPen(QPen(c, 1.8))
    p.drawLine(QPointF(4, 10), QPointF(8, 5.5))
    p.drawLine(QPointF(8, 5.5), QPointF(12, 10))


def _chevron_down(p, c):
    p.setPen(QPen(c, 1.8))
    p.drawLine(QPointF(4, 6), QPointF(8, 10.5))
    p.drawLine(QPointF(8, 10.5), QPointF(12, 6))


def _chevron_left(p, c):
    p.setPen(QPen(c, 1.8))
    p.drawLine(QPointF(10, 4), QPointF(5.5, 8))
    p.drawLine(QPointF(5.5, 8), QPointF(10, 12))


def _chevron_right(p, c):
    p.setPen(QPen(c, 1.8))
    p.drawLine(QPointF(6, 4), QPointF(10.5, 8))
    p.drawLine(QPointF(10.5, 8), QPointF(6, 12))


def _star(p, c):
    p.setPen(QPen(c, 1.3))
    import math
    pts = []
    cx, cy = 8.0, 8.4
    for k in range(10):
        r = 6.2 if k % 2 == 0 else 2.6
        a = -math.pi / 2 + k * math.pi / 5
        pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
    p.drawPolygon(QPolygonF(pts))


def _bookmark(p, c):
    p.setPen(QPen(c, 1.5))
    poly = QPolygonF([QPointF(4.5, 2.5), QPointF(11.5, 2.5),
                      QPointF(11.5, 13.5), QPointF(8, 10.3),
                      QPointF(4.5, 13.5)])
    p.drawPolygon(poly)


def _refresh(p, c):
    p.setPen(QPen(c, 1.5))
    p.drawArc(QRectF(3, 3, 10, 10), 60 * 16, 250 * 16)
    p.drawLine(QPointF(12.5, 3.5), QPointF(12.8, 7.0))
    p.drawLine(QPointF(12.8, 7.0), QPointF(9.4, 6.4))


_DRAW = {
    "search": _search, "globe": _globe, "close": _close,
    "chevron_up": _chevron_up, "chevron_down": _chevron_down,
    "chevron_left": _chevron_left, "chevron_right": _chevron_right,
    "star": _star, "bookmark": _bookmark, "refresh": _refresh,
}


def themed_icon(name: str, dark: bool | None = None, size: int = 16) -> QIcon:
    """이름으로 테마색 단색 아이콘 생성. 없는 이름이면 빈 아이콘."""
    fn = _DRAW.get(name)
    if fn is None:
        return QIcon()
    c = QColor(fg_color(dark))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if size != 16:
            p.scale(size / 16.0, size / 16.0)
        fn(p, c)
    finally:
        p.end()
    return QIcon(pm)
