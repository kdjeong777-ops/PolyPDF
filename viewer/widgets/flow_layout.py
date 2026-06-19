"""FlowLayout — 위젯을 가용 폭에 맞춰 자동 줄바꿈 배치 (Qt 공식 예제 기반).
책갈피 편집 툴바 버튼이 패널 폭을 넘지 않도록 사용(260603)."""
from __future__ import annotations

from PyQt6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QLayoutItem, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=4, center=True):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(QMargins(margin, margin, margin, margin))
        self.setSpacing(spacing)
        self._items: list[QLayoutItem] = []
        self._center = center        # 260618-2: False=각 줄 좌측 정렬(컨트롤 패널용)

    def __del__(self):
        while self._items:
            self._items.pop()

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    # 260606-9: 인덱스 기반 위젯 삽입/조회(툴바 외부 버튼 삽입용)
    def indexOf(self, widget) -> int:
        for i, it in enumerate(self._items):
            if it.widget() is widget:
                return i
        return -1

    def insertWidget(self, index: int, widget) -> None:
        self.addWidget(widget)            # 위젯 reparent + 끝에 추가
        item = self._items.pop()          # 방금 추가분을 떼어
        if index < 0:
            index = 0
        index = min(index, len(self._items))
        self._items.insert(index, item)   # 원하는 위치로
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        # 260606-18: 각 줄을 '가로 중앙' + '세로 중앙' 정렬(2-pass).
        m = self.contentsMargins()
        left = rect.x() + m.left()
        right = rect.right() - m.right()
        avail = max(0, right - left)
        sp = self.spacing()

        # 1) 항목을 줄(line)로 그룹화 — (items, line_width, line_height)
        lines: list = []
        cur: list = []
        cw = 0
        ch = 0
        for item in self._items:
            s = item.sizeHint()
            w, h = s.width(), s.height()
            nextw = w if not cur else cw + sp + w
            if cur and nextw > avail:
                lines.append((cur, cw, ch))
                cur, cw, ch = [], 0, 0
                nextw = w
            cur.append(item)
            cw = nextw
            ch = max(ch, h)
        if cur:
            lines.append((cur, cw, ch))

        # 2) 각 줄 배치 (center=True 면 가로 중앙, False 면 좌측 정렬)
        y = rect.y() + m.top()
        for idx, (items, lw, lh) in enumerate(lines):
            if not test_only:
                ox = left + (max(0, (avail - lw) // 2) if self._center else 0)
                for it in items:
                    s = it.sizeHint()
                    oy = y + max(0, (lh - s.height()) // 2)
                    it.setGeometry(QRect(QPoint(ox, oy), s))
                    ox += s.width() + sp
            y += lh + (sp if idx < len(lines) - 1 else 0)

        return y - rect.y() + m.bottom()
