"""FlowLayout — 위젯을 가용 폭에 맞춰 자동 줄바꿈 배치 (Qt 공식 예제 기반).
책갈피 편집 툴바 버튼이 패널 폭을 넘지 않도록 사용(260603)."""
from __future__ import annotations

from PyQt6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QLayoutItem, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=4, center=True, justify=False):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(QMargins(margin, margin, margin, margin))
        self.setSpacing(spacing)
        self._items: list[QLayoutItem] = []
        self._center = center        # 260618-2: False=각 줄 좌측 정렬(컨트롤 패널용)
        # 261011-4(디자인 SOT §2.8.5): True 면 줄마다 남는 폭을 늘어날 수 있는 항목에 나눠 **오른쪽 끝을 맞춘다**
        #   (무게 = 위젯 속성 `flow_weight`, 기본 1). 늘지 않는 것: QLabel, 폭을 고정한 위젯(최대 폭 = 지금 폭)
        self._justify = justify

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

    @staticmethod
    def _weight(item) -> int:
        w = item.widget()
        try:
            v = int(w.property("flow_weight") or 1) if w is not None else 1
        except Exception:
            v = 1
        return max(1, v)

    @staticmethod
    def _can_grow(item) -> bool:
        from PyQt6.QtWidgets import QLabel
        w = item.widget()
        if w is None or isinstance(w, QLabel) or w.isHidden():
            return False
        return w.maximumWidth() > item.sizeHint().width()

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
            if item.isEmpty():
                continue                 # 261011-4: 숨긴 단추는 자리(간격)도 차지하지 않는다 — 오른쪽 끝이 어긋났다
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

        # 2) 각 줄 배치 (center=True 면 가로 중앙, False 면 좌측 정렬, justify 면 오른쪽 끝까지 늘린다)
        y = rect.y() + m.top()
        for idx, (items, lw, lh) in enumerate(lines):
            if not test_only:
                extra = {}
                if self._justify and avail > lw:
                    grow = [(it, self._weight(it)) for it in items if self._can_grow(it)]
                    tot = sum(w for _, w in grow)
                    left_over = avail - lw
                    for k, (it, w) in enumerate(grow):
                        add = left_over if k == len(grow) - 1 else (avail - lw) * w // tot
                        extra[id(it)] = add
                        left_over -= add
                ox = left + (max(0, (avail - lw) // 2) if (self._center and not extra) else 0)
                for it in items:
                    s = it.sizeHint()
                    sw = s.width() + extra.get(id(it), 0)
                    oy = y + max(0, (lh - s.height()) // 2)
                    it.setGeometry(QRect(QPoint(ox, oy), QSize(sw, s.height())))
                    ox += sw + sp
            y += lh + (sp if idx < len(lines) - 1 else 0)

        return y - rect.y() + m.bottom()
