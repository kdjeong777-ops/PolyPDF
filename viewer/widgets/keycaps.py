# -*- coding: utf-8 -*-
"""261107-4(디자인 SOT §2.9.2 '키캡 그림', 사용자 지시·결정): 단축키를 키캡 그림으로 — 그리기는 이 모듈 한 곳.

- 바꾸개 키(Ctrl·Alt·Shift): **채운** 둥근 칸 — Ctrl = 큰 C + 작은 trl, Alt = 큰 A + 작은 lt, Shift = 속이 빈 굵은 ⇧.
- 보통 키(S·F2·Del·Enter·[·]): **테두리만**. 방향키는 가는 화살표.
- 작은 글자는 큰 글자의 `KEYCAP_SMALL_RATIO`, 최소 `KEYCAP_MIN_PX` — 그보다 작아지면 이름 전체를 같은 크기로.
- 키캡 사이 '+' 없이 `KEYCAP_GAP`. 색은 글자색에서(채움·테두리는 그 색의 옅은 꼴) — 다크·강조 반전·꺼짐 흐림이 저절로 따라온다.

쓰는 곳: 메뉴(`KeycapMenuStyle` — `\\t` 오른쪽 칸), 리본 단추 툴팁(`keycap_html`), 단축키 창(`KeycapLabel`).
글자(`Ctrl+Shift+S`)는 메뉴 항목 글에 그대로 남는다 — 화면 낭독기·글 복사는 글자를 받는다(그림은 그리기만).
"""
from __future__ import annotations

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QLabel, QProxyStyle, QStyle, QStyleOptionMenuItem

KEYCAP_RADIUS = 3            # 둥근 칸 모서리(px)
KEYCAP_SMALL_RATIO = 0.6     # 바꾸개 키 작은 글자 = 큰 글자 × 이 값
KEYCAP_MIN_PX = 7            # 작은 글자 최소 높이(px)
KEYCAP_GAP = 2               # 키캡 사이(px) — '+' 를 쓰지 않는다
KEYCAP_PAD_X = 3             # 키캡 안 좌우 여백(px)
FILL_ALPHA = 46              # 바꾸개 키 채움 = 글자색의 이 투명도
BORDER_ALPHA = 150           # 테두리 = 글자색의 이 투명도

MODS = {"ctrl": ("C", "trl"), "alt": ("A", "lt"), "meta": ("W", "in"), "win": ("W", "in")}
SHIFT = "shift"
ARROWS = {"up": 0, "right": 90, "down": 180, "left": 270, "↑": 0, "→": 90, "↓": 180, "←": 270}


def split_keys(text: str) -> list:
    """'Ctrl+Shift+S' → ['Ctrl', 'Shift', 'S'] · 'Ctrl++' → ['Ctrl', '+']. 여러 마디(', ')면 첫 마디만."""
    t = (text or "").split(", ")[0].strip()
    if not t:
        return []
    parts = t.split("+")
    out, i = [], 0
    while i < len(parts):
        p = parts[i]
        if p == "":                       # '+' 키 자체 — 빈 조각 둘이 '+' 하나
            out.append("+")
            i += 2
            continue
        out.append("Enter" if p == "Return" else p)      # 본 Enter 키(Qt 이름 Return)도 'Enter' 로
        i += 1
    return out


def _kind(tok: str) -> str:
    k = tok.lower()
    if k == SHIFT:
        return "shift"
    if k in MODS:
        return "mod"
    if k in ARROWS:
        return "arrow"
    return "key"


def _fonts(font: QFont):
    big = QFont(font)
    px = QFontMetricsF(big).height()
    small_px = px * KEYCAP_SMALL_RATIO
    small = QFont(font)
    uniform = small_px < KEYCAP_MIN_PX           # 너무 작으면 이름 전체를 같은 크기로
    if not uniform:
        small.setPixelSize(max(KEYCAP_MIN_PX, int(round(small_px * 0.8))))   # 높이 → 픽셀 크기(어림)
    return big, small, uniform


def _cap_w(tok: str, font: QFont, h: float) -> float:
    big, small, uniform = _fonts(font)
    kind = _kind(tok)
    if kind == "shift" or kind == "arrow":
        return h * 0.95 + 2 * KEYCAP_PAD_X - 2
    if kind == "mod":
        head, rest = MODS[tok.lower()]
        if uniform:
            return QFontMetricsF(big).horizontalAdvance(head + rest) + 2 * KEYCAP_PAD_X
        return QFontMetricsF(big).horizontalAdvance(head) + QFontMetricsF(small).horizontalAdvance(rest) + 2 * KEYCAP_PAD_X
    return max(QFontMetricsF(big).horizontalAdvance(tok) + 2 * KEYCAP_PAD_X, h * 0.95)


def cap_height(font: QFont) -> float:
    return QFontMetricsF(font).height() + 2


def keycap_size(text: str, font: QFont) -> QSize:
    """키캡 줄의 크기(px) — 키가 없으면 0×0."""
    toks = split_keys(text)
    if not toks:
        return QSize(0, 0)
    h = cap_height(font)
    w = sum(_cap_w(t, font, h) for t in toks) + KEYCAP_GAP * (len(toks) - 1)
    return QSize(int(round(w + 1)), int(round(h + 1)))


def _shift_path(r: QRectF) -> QPainterPath:
    """속이 빈 굵은 ⇧ — 키보드 Shift 각인 꼴."""
    cx, top, bot = r.center().x(), r.top() + r.height() * 0.18, r.bottom() - r.height() * 0.18
    hw = r.height() * 0.30                     # 머리 반폭
    sw = r.height() * 0.13                     # 기둥 반폭
    mid = top + (bot - top) * 0.50
    path = QPainterPath()
    path.moveTo(cx, top)
    path.lineTo(cx + hw, mid)
    path.lineTo(cx + sw, mid)
    path.lineTo(cx + sw, bot)
    path.lineTo(cx - sw, bot)
    path.lineTo(cx - sw, mid)
    path.lineTo(cx - hw, mid)
    path.closeSubpath()
    return path


def paint_keys(p: QPainter, right: float, center_y: float, text: str, font: QFont, fg: QColor) -> float:
    """키캡 줄을 오른쪽 끝 `right`·세로 가운데 `center_y` 에 그린다. 그린 폭을 돌려준다."""
    toks = split_keys(text)
    if not toks:
        return 0.0
    h = cap_height(font)
    big, small, uniform = _fonts(font)
    widths = [_cap_w(t, font, h) for t in toks]
    total = sum(widths) + KEYCAP_GAP * (len(toks) - 1)
    x = right - total
    y = center_y - h / 2.0
    fill = QColor(fg); fill.setAlpha(FILL_ALPHA)
    border = QColor(fg); border.setAlpha(BORDER_ALPHA)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    for tok, w in zip(toks, widths):
        r = QRectF(x + 0.5, y + 0.5, w - 1, h - 1)
        kind = _kind(tok)
        if kind in ("mod", "shift"):           # 바꾸개 — 채운 칸
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
        else:                                  # 보통 키 — 테두리만
            p.setPen(QPen(border, 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, KEYCAP_RADIUS, KEYCAP_RADIUS)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "shift":
            p.setPen(QPen(fg, max(1.2, h / 11.0), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(_shift_path(r))
        elif kind == "arrow":
            p.save()
            p.translate(r.center())
            p.rotate(ARROWS[tok.lower()])
            p.setPen(QPen(fg, 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            a = h * 0.30
            p.drawLine(QPointF(0, a), QPointF(0, -a))
            p.drawLine(QPointF(0, -a), QPointF(-a * 0.6, -a * 0.35))
            p.drawLine(QPointF(0, -a), QPointF(a * 0.6, -a * 0.35))
            p.restore()
        elif kind == "mod":
            head, rest = MODS[tok.lower()]
            p.setPen(fg)
            if uniform:
                p.setFont(big)
                p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), head + rest)
            else:
                fmb, fms = QFontMetricsF(big), QFontMetricsF(small)
                bx = r.left() + KEYCAP_PAD_X - 0.5
                base = r.top() + (r.height() + fmb.ascent() - fmb.descent()) / 2.0
                p.setFont(big)
                p.drawText(QPointF(bx, base), head)
                p.setFont(small)
                p.drawText(QPointF(bx + fmb.horizontalAdvance(head), base), rest)
        else:
            p.setPen(fg)
            p.setFont(big)
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), tok)
        x += w + KEYCAP_GAP
    p.restore()
    return total


def keycap_pixmap(text: str, font: QFont, fg: QColor, dpr: float = 2.0) -> QPixmap:
    sz = keycap_size(text, font)
    pm = QPixmap(max(1, int(sz.width() * dpr)), max(1, int(sz.height() * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        paint_keys(p, sz.width() - 0.5, sz.height() / 2.0, text, font, fg)
    finally:
        p.end()
    return pm


def keycap_html(text: str, font: QFont, fg: QColor) -> str:
    """툴팁(서식 글)에 넣을 키캡 그림 — `<img>`(data URL). 키가 없으면 ''."""
    if not split_keys(text):
        return ""
    pm = keycap_pixmap(text, font, fg)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    sz = keycap_size(text, font)
    return '<img src="data:image/png;base64,%s" width="%d" height="%d" style="vertical-align:middle">' % (
        bytes(ba.toBase64()).decode("ascii"), sz.width(), sz.height())


class KeycapMenuStyle(QProxyStyle):
    """메뉴 항목의 `\\t` 오른쪽 칸(단축키)을 키캡 그림으로 — 앱 스타일(Fusion)을 감싼다(디자인 SOT §2.9.2)."""

    RIGHT_MARGIN = 10          # 메뉴 오른쪽 끝에서 키캡까지(px)
    SUBMENU_SPACE = 14         # 하위 메뉴 화살표 자리

    def _split(self, opt):
        t = getattr(opt, "text", "") or ""
        if "\t" not in t:
            return None, None
        label, key = t.split("\t", 1)
        return label, key.strip()

    def drawControl(self, element, opt, p, w=None):
        if element == QStyle.ControlElement.CE_MenuItem and isinstance(opt, QStyleOptionMenuItem):
            label, key = self._split(opt)
            if key:
                o = QStyleOptionMenuItem(opt)
                o.text = label
                super().drawControl(element, o, p, w)
                enabled = bool(opt.state & QStyle.StateFlag.State_Enabled)
                selected = bool(opt.state & QStyle.StateFlag.State_Selected) and enabled
                grp = QPalette.ColorGroup.Normal if enabled else QPalette.ColorGroup.Disabled
                role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
                fg = opt.palette.color(grp, role)
                r = opt.rect
                right = r.right() - self.RIGHT_MARGIN
                if opt.menuItemType == QStyleOptionMenuItem.MenuItemType.SubMenu:
                    right -= self.SUBMENU_SPACE
                    # 261107-4 덧붙임: 나눈 항목(저장 ▸·붙여넣기 ▼, ctx_menu)은 ▸ 쪽 나눔선 왼쪽에 — 선과 겹치지 않게
                    act = w.actionAt(r.center()) if w is not None and hasattr(w, "actionAt") else None
                    if act is not None and act.property("ctx_split"):
                        from viewer.widgets.ctx_menu import SPLIT_ARROW_W
                        right = r.right() - SPLIT_ARROW_W - 6
                paint_keys(p, right, r.center().y() + 0.5, key, opt.font, fg)
                return
        super().drawControl(element, opt, p, w)

    def sizeFromContents(self, ct, opt, size, w=None):
        s = super().sizeFromContents(ct, opt, size, w)
        if ct == QStyle.ContentsType.CT_MenuItem and isinstance(opt, QStyleOptionMenuItem):
            _label, key = self._split(opt)
            if key:
                need = keycap_size(key, opt.font).width() - int(QFontMetricsF(opt.font).horizontalAdvance(key))
                if need > 0:
                    s.setWidth(s.width() + need)
                s.setHeight(max(s.height(), keycap_size(key, opt.font).height() + 4))
        return s


def app_style(base_name: str = "Fusion"):
    """앱 스타일 — Fusion 을 키캡 메뉴 스타일로 감싼다(테마를 바꿀 때마다 새로)."""
    from PyQt6.QtWidgets import QStyleFactory
    return KeycapMenuStyle(QStyleFactory.create(base_name))


class KeycapLabel(QLabel):
    """단축키 창의 키캡 미리 보기 — 키가 바뀌면 `set_keys`."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._keys = ""
        self.set_keys(text)

    def set_keys(self, text: str) -> None:
        self._keys = text or ""
        self.setAccessibleName(self._keys)            # 낭독기에는 글자
        self.setToolTip(self._keys)
        sz = keycap_size(self._keys, self.font())
        self.setMinimumSize(QSize(max(sz.width(), 8), sz.height()))
        self.update()

    def keys(self) -> str:
        return self._keys

    def paintEvent(self, ev):
        if not self._keys:
            return
        p = QPainter(self)
        try:
            fg = self.palette().color(QPalette.ColorGroup.Normal if self.isEnabled() else QPalette.ColorGroup.Disabled,
                                      QPalette.ColorRole.WindowText)
            sz = keycap_size(self._keys, self.font())
            paint_keys(p, float(sz.width()), self.height() / 2.0, self._keys, self.font(), fg)
        finally:
            p.end()
