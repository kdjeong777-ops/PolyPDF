"""손잡이 더블클릭으로 인접 패널을 접기/펴기하는 QSplitter (260616-12).

손잡이(handle[i])를 마우스로 더블클릭하면 그 **왼쪽(작은 인덱스) 패널**을
숨김/보이기 토글한다. 접을 때의 폭을 기억해 다시 펼 때 복원한다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QSplitter, QSplitterHandle
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtCore import Qt


class _ToggleHandle(QSplitterHandle):
    def paintEvent(self, ev):
        """260618-10: 손잡이 중앙에 잡기 좋은 그립 표식 — 더 진하고 길게.
        260618-25: 중간 그립 길이를 종전의 50% 로 축소(요청)."""
        super().paintEvent(ev)
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(110, 110, 110))     # 진한 회색(라이트/다크 모두 보임)
            r = self.rect()
            if self.orientation() == Qt.Orientation.Horizontal:
                # 가로 스플리터 → 세로 손잡이: 중앙에 세로 그립(종전의 절반 길이)
                gw = min(4, r.width())
                gh = int(min(80, max(40, r.height() * 0.175)))
                x = (r.width() - gw) / 2.0
                y = (r.height() - gh) / 2.0
                p.drawRoundedRect(int(x), int(y), gw, gh, 2, 2)
            else:
                gh = min(4, r.height())
                gw = int(min(80, max(40, r.width() * 0.175)))
                x = (r.width() - gw) / 2.0
                y = (r.height() - gh) / 2.0
                p.drawRoundedRect(int(x), int(y), gw, gh, 2, 2)
            p.end()
        except Exception:
            pass

    def mouseDoubleClickEvent(self, ev):
        sp = self.splitter()
        idx = None
        for k in range(sp.count()):
            if sp.handle(k) is self:
                idx = k
                break
        if idx is not None and idx > 0:
            sp.toggle_section(idx - 1)
        super().mouseDoubleClickEvent(ev)


class ToggleSplitter(QSplitter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setChildrenCollapsible(True)
        self._saved_sizes: dict = {}

    def createHandle(self):
        return _ToggleHandle(self.orientation(), self)

    def toggle_section(self, idx: int):
        sizes = self.sizes()
        n = len(sizes)
        if not (0 <= idx < n):
            return
        if sizes[idx] > 4:                       # 펼쳐져 있음 → 접기
            self._saved_sizes[idx] = sizes[idx]
            freed = sizes[idx]
            sizes[idx] = 0
            others = [k for k in range(n) if k != idx]
            if others:
                j = max(others, key=lambda k: sizes[k])
                sizes[j] += freed
        else:                                    # 접혀 있음 → 펴기
            w = self._saved_sizes.get(idx, 220)
            j = max(range(n), key=lambda k: sizes[k])
            take = min(w, max(0, sizes[j] - 80))
            if take <= 0:
                take = w
            sizes[idx] = take
            sizes[j] = max(0, sizes[j] - take)
        self.setSizes(sizes)
