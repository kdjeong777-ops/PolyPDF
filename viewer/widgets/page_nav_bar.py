# -*- coding: utf-8 -*-
"""261105-26(사용자 지시, 디자인 SOT §2.9.2): 쪽 이동(‹ 칸 / 전체 ›)을 창 아래 상태 줄로.

사용자 지시 원문: "페이지 이동을 본문뷰어 하단의 중앙으로 이동시켜 … 2단보기에서 우측 창 페이지 이동 내용은
중앙이 아니더라도 메시지 왼쪽에 위치하도록 해".

- 1단: 본문 창(왼쪽 창) 쪽 이동 묶음의 가운데 = 그 창 가운데(창 아래 상태 줄).
- 2단: 왼쪽 창 묶음은 그 창 가운데 아래, 오른쪽 창 묶음은 상태 줄 오른쪽 고정 칸(가벼운 넘김·맞춤 콤보 …) 바로 왼쪽.
- 상태 줄 맨 앞 **고정 칸**(permanent) 하나가 두 묶음을 담는다 — 고정 칸이라 진행·알림 임시 메시지가 떠도 숨지 않고,
  임시 메시지는 이 칸 왼쪽 끝에서 잘린다(QStatusBar 가 첫 고정 칸 앞까지만 글을 그린다 — 겹치지 않는다).
- 이 칸의 폭(`sizeHint`)을 '왼쪽 창 가운데 − 묶음 폭/2' 부터 오른쪽 고정 칸 앞까지로 맞춘다. 최소 폭은 묶음 폭뿐이라
  창을 좁히는 것을 막지 않고, 좁으면 가운데를 지키지 못한 만큼 오른쪽으로 밀린다(왼쪽 메시지 자리 `MSG_MIN_W` 는 남긴다).
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, QPoint
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

MSG_MIN_W = 120          # 왼쪽 메시지 자리(‘N개 PDF’·진행 글)는 이만큼은 남긴다(px)
NAV_GAP = 12             # 2단에서 두 묶음 사이 최소 간격(px)
RELAYOUT_MS = 10         # 크기·자리 바뀜을 모아 다시 맞추기까지(ms)
SIDE_GAP = 12           # 왼쪽 묶음 ↔ 그 오른쪽에 붙는 사진 정보 줄 사이(px)


class PageNavHost(QWidget):
    """상태 줄 맨 앞 고정 칸 — 본문 창마다의 `MainView.page_nav` 를 담는다."""

    def __init__(self, status, views, panes, parent=None):
        super().__init__(parent or status)
        self.setObjectName("pageNavHost")
        self._status = status
        self._views = list(views)
        self._panes = list(panes)
        self._navs = [v.page_nav for v in self._views]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._side = None                                # 왼쪽 묶음 바로 오른쪽에 붙는 것(사진 정보 줄 — 사진 보기 SOT §4.18)
        lay.addWidget(self._navs[0])
        lay.addStretch(1)
        for n in self._navs[1:]:
            lay.addWidget(n)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._want_w = self._nav_need()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RELAYOUT_MS)              # 한 번만(singleShot) — 잇단 크기 바뀜을 모아 한 번 맞춘다
        self._timer.timeout.connect(self.relayout)
        # 본문 창이 옮겨 가는 모든 길 — 창 크기, 책갈피·썸네일 칸 폭(가르개 안 자리), 2단 켜고 끄기, 묶음 글 폭('/ 487')
        watch = [status, self] + self._views + self._panes
        a = self._views[0].parentWidget()
        while a is not None:
            watch.append(a)
            a = a.parentWidget()
        for w in watch:
            w.installEventFilter(self)
        # 고정 칸 맨 앞 — Qt 는 일반 칸('N개 PDF') 수보다 작은 차례를 '범위 밖' 으로 보고 **맨 끝에 붙인다**(실제로 맞춤 콤보 오른쪽에 붙었다).
        #   첫 고정 칸 차례(= 일반 칸 수)를 찾을 때까지 넣어 본다.
        for i in range(12):
            if status.insertPermanentWidget(i, self) == i:
                break
            status.removeWidget(self)    # removeWidget 은 숨긴다 — 아래에서 다시 보인다
        self.show()
        self._sync_visible()
        for v in self._views:            # 같은 창에 들어온 뒤라야 Tab 차례(툴바 → 쪽 이동 → 본문)가 먹는다
            v._sync_toolbar_tab_order()

    # ── 크기 ───────────────────────────────────────────────────────────
    def _shown(self, i: int) -> bool:
        return not self._panes[i].isHidden()

    def set_side_widget(self, w) -> None:
        """왼쪽 묶음 바로 오른쪽(`SIDE_GAP` 띄워)에 위젯 하나 — 사진 모드 사진 정보 줄(사진 보기 SOT §4.18).
        종전에는 상태 막대 가운데에 떠 있었는데 쪽 이동이 본문 창 가운데 아래로 오며 겹쳤다(261105-26)."""
        if w is self._side:
            return
        self._side = w
        lay = self.layout()
        lay.insertSpacing(1, SIDE_GAP)
        lay.insertWidget(2, w)
        w.installEventFilter(self)          # 보이고 숨을 때·글 폭이 바뀔 때 다시 맞춘다
        self._timer.start()

    def _nav_need(self) -> int:
        ws = [n.sizeHint().width() for i, n in enumerate(self._navs) if self._shown(i)]
        need = sum(ws) + NAV_GAP * max(0, len(ws) - 1)
        if self._side is not None and not self._side.isHidden():
            need += SIDE_GAP + self._side.sizeHint().width()
        return need

    def sizeHint(self) -> QSize:
        return QSize(max(self._want_w, self._nav_need()), self._navs[0].sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(self._nav_need(), self._navs[0].sizeHint().height())

    # ── 자리 맞추기 ─────────────────────────────────────────────────────
    def _sync_visible(self) -> None:
        for i, n in enumerate(self._navs):
            n.setVisible(self._shown(i))

    def _center_x(self) -> float:
        """왼쪽(본문) 창 가운데 x — 상태 줄 좌표."""
        v = self._views[0]
        win = self.window()
        p = v.mapTo(win, QPoint(0, 0))
        return self._status.mapFrom(win, p).x() + v.width() / 2.0

    def relayout(self) -> None:
        self._sync_visible()
        st = self._status
        right = self.geometry().right() + 1               # 이 칸 오른쪽 끝 = 오른쪽 고정 칸 바로 앞(이 칸 폭과 무관)
        n0 = self._navs[0].sizeHint().width()
        need = self._nav_need()
        left = self._center_x() - n0 / 2.0                # 왼쪽 묶음이 시작할 x
        lo = MSG_MIN_W
        hi = right - need
        left = int(round(max(lo, min(hi, left)))) if hi >= lo else max(0, right - need)
        want = max(need, right - left)
        if want != self._want_w:
            self._want_w = want
            self.updateGeometry()
            st.layout().invalidate() if st.layout() is not None else None

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.Hide,
                 QEvent.Type.LayoutRequest):
            self._timer.start()
        return False
