# -*- coding: utf-8 -*-
"""261021-2(사용자 지시, 디자인 SOT §2.9.3): 메뉴 막대·패널 툴바를 **창 가운데**에.

- 메뉴 막대: 왼쪽 모서리 위젯(빈 칸)의 폭으로 메뉴 묶음을 창 가운데로 민다.
- 패널 툴바: 맨 앞 빈 칸(`pad`)의 폭으로 `보기`~`도구` 묶음을 창 가운데로 민다. 오른쪽 끝 검색창과는
  `GAP_TO_SEARCH` 이상 띄운다 — 창이 좁으면 묶음이 왼쪽으로 밀리고, 더 좁으면 왼쪽 정렬과 같아진다.
- 그룹 바탕: `보기`·`도구` 묶음마다 버튼보다 옅은 둥근 바탕(`GROUP_BG`) — 가운데에 떠 있는 버튼들이 한
  덩어리로 읽히게 한다(사용자 지시 '색상이 없을 경우 조금 이상하게 보이므로').

폭은 창 크기·보이는 단추가 바뀔 때마다 다시 잰다(`schedule`). 레이아웃이 끝난 뒤 재야 하므로 `RECENTER_MS` 타이머로 미룬다
(간격 0 타이머는 쓰지 않는다 — 응답성 SOT §4 ⑥).
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QResizeEvent
from PyQt6.QtWidgets import QApplication, QToolBar, QWidget

RECENTER_MS = 10            # 크기·단추가 바뀐 뒤 다시 재기까지(잇단 바뀜은 한 번으로 모인다)
GAP_TO_SEARCH = 16          # 도구 묶음 오른쪽 끝 ↔ 검색창 최소 간격(px)
OVERFLOW_RESERVE = 24       # 툴바가 넘침(») 단추용으로 남기는 폭 — 빈 칸이 이 몫까지 먹으면 끝 위젯이 넘침으로 밀린다
GROUP_PAD_X = 4             # 그룹 바탕이 라벨·버튼 바깥으로 나오는 폭
GROUP_RADIUS = 6
GROUP_BG = {False: "#ebebeb", True: "#3a3a3d"}   # 라이트(툴바 #f5f5f5 · 버튼 #e2e2e2 사이) / 다크(#2e2e31 · #484848 사이)


class PanelToolBar(QToolBar):
    """그룹 바탕을 그리고, 묶음이 창 가운데에 오도록 맨 앞 빈 칸의 폭을 맞추는 패널 툴바."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.pad = QWidget(self)
        self.pad.setFixedWidth(0)
        self.groups: list = []             # [[라벨, 버튼, ...], ...]
        self.search = None                 # 오른쪽 끝 검색창(보일 때만 간격을 지킨다)
        self.dark = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RECENTER_MS)
        self._timer.timeout.connect(self.recenter)

    def schedule(self) -> None:
        self._timer.start()

    def _span(self):
        """보이는 그룹 위젯 전체의 (왼쪽, 오른쪽) — 없으면 None."""
        ws = [w for g in self.groups for w in g if w.isVisible()]
        if not ws:
            return None
        return min(w.geometry().left() for w in ws), max(w.geometry().right() for w in ws)

    def recenter(self) -> None:
        span = self._span()
        if span is None:
            return
        cur = self.pad.width()
        base = span[0] - cur                       # 빈 칸 폭이 0 일 때 묶음이 시작하는 자리
        width = span[1] - span[0] + 1
        want = (self.width() - width) // 2         # 창 가운데(툴바는 창 폭 전체다)
        # 남는 폭 — 빈 칸이 이보다 넓으면 단추가 넘침(») 메뉴로 밀려난다. 검색창이 보이면 간격만큼 덜 쓴다.
        #   툴바는 넘침 단추 자리를 따로 남기므로(`sizeHint` 에 없다) 그만큼(`OVERFLOW_RESERVE`) 더 덜 쓴다.
        s = self.search
        slack = self.width() - (self.sizeHint().width() - cur) - OVERFLOW_RESERVE
        if s is not None and s.isVisible():
            slack -= GAP_TO_SEARCH
        new = max(0, min(want - base, slack))
        if new != cur:
            self.pad.setFixedWidth(new)
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.schedule()

    def event(self, ev):
        # 단추를 숨기고 보이는 것(키 게이팅·한국 전용·검색창 숨김)은 액션 가시성으로 한다 — 그때도 다시 잰다
        if ev.type() in (QEvent.Type.LayoutRequest, QEvent.Type.ActionChanged, QEvent.Type.Show):
            self.schedule()
        return super().event(ev)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(GROUP_BG[bool(self.dark)]))
        for g in self.groups:
            ws = [w for w in g if w.isVisible()]
            if not ws:
                continue
            x0 = min(w.geometry().left() for w in ws) - GROUP_PAD_X
            x1 = max(w.geometry().right() for w in ws) + GROUP_PAD_X
            y0 = min(w.geometry().top() for w in ws) - 1
            y1 = max(w.geometry().bottom() for w in ws) + 1
            p.drawRoundedRect(QRectF(x0, y0, x1 - x0 + 1, y1 - y0 + 1), GROUP_RADIUS, GROUP_RADIUS)
        p.end()


class _Spacer(QWidget):
    """폭만 있는 빈 칸 — 메뉴 막대는 모서리 위젯의 `sizeHint` 로 자리를 잡는다(맨 QWidget 은 힌트가 없어 무시된다)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._w = 0

    def set_width(self, w: int) -> None:
        self._w = max(0, int(w))
        self.setFixedSize(self._w, 1)
        self.updateGeometry()

    def width_hint(self) -> int:
        return self._w

    def sizeHint(self):
        return QSize(self._w, 1)

    def minimumSizeHint(self):
        return QSize(self._w, 1)


class _MenuBarCenter(QObject):
    """메뉴 막대 크기·항목이 바뀌면 왼쪽 빈 칸 폭을 다시 잰다."""

    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar
        self.pad = _Spacer(bar)
        self._left0 = None                 # 빈 칸이 없을 때 첫 메뉴가 시작하는 자리(막대 안쪽 여백)
        bar.setCornerWidget(self.pad, Qt.Corner.TopLeftCorner)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RECENTER_MS)
        self._timer.timeout.connect(self.recenter)
        bar.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.ActionAdded, QEvent.Type.ActionRemoved,
                         QEvent.Type.ActionChanged, QEvent.Type.Show):
            self._timer.start()
        return False

    def recenter(self) -> None:
        acts = [a for a in self.bar.actions() if a.isVisible()]
        rects = [self.bar.actionGeometry(a) for a in acts]
        rects = [r for r in rects if r.width() > 0]
        if not rects:
            return
        cur = self.pad.width_hint()
        left = min(r.left() for r in rects)
        if cur == 0 or self._left0 is None:
            self._left0 = left if cur == 0 else max(0, left - cur)
        width = max(r.right() for r in rects) - left + 1
        new = max(0, min(self.bar.width() - width, (self.bar.width() - width) // 2 - self._left0))
        if new != cur:
            self.pad.set_width(new)
            # 모서리 위젯 폭이 바뀐 것만으로는 메뉴 막대가 항목 자리를 다시 잡지 않는다 — 크기 바뀜을 한 번 보낸다
            #   (다시 들어와도 폭이 같아 여기서 멈춘다)
            QApplication.sendEvent(self.bar, QResizeEvent(self.bar.size(), self.bar.size()))


def center_menubar(bar) -> _MenuBarCenter:
    return _MenuBarCenter(bar)
