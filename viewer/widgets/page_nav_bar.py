# -*- coding: utf-8 -*-
"""쪽 이동(❮ 칸 / 전체 ❯)을 창 아래 상태 막대에 — 본문 창마다 그 창 가운데 아래 (디자인 SOT §2.9.2·§2.20).

사용자 지시 원문: "페이지 이동을 본문뷰어 하단의 중앙으로 이동시켜"(261105-26),
"1단보기에서 쪽이동 내용이 파일에 따라 왼쪽 오른쪽 이동해. 뷰어창의 중간에 맞춰서 위치를 처음부터 잡도록 …
2단보기에서도 쪽이동 내용은 창 내용의 중간에 배치해. 다만, 오른쪽 메시지에 따라 왼쪽으로 이동될 수도 있다는거야"(261105-29).

- 묶음마다 가운데 = 그 본문 창 가운데. 2단 오른쪽 창 묶음은 오른쪽 고정 칸(진행 막대·가벼운 넘김·맞춤 콤보 …)과
  겹치면 겹치지 않을 만큼만 왼쪽으로 밀린다.
- 상태 막대 맨 앞 **고정 칸**(permanent) 하나가 묶음을 담는다 — 고정 칸이라 임시 메시지가 떠도 숨지 않고,
  임시 메시지는 이 칸 왼쪽 끝에서 잘린다(QStatusBar 가 첫 고정 칸 앞까지만 글을 그린다 — 겹치지 않는다).
- 이 칸의 폭(`sizeHint`)은 '왼쪽 묶음 왼쪽 끝 ~ 오른쪽 고정 칸 앞'. 최소 폭은 묶음 폭뿐이라 창 좁히기를 막지 않는다
  (좁으면 가운데를 못 지킨 만큼 밀리고, 왼쪽 메시지 자리 `MSG_MIN_W` 는 남긴다).
- ★ 261105-29: 묶음은 레이아웃이 아니라 **이 칸의 실제 자리에서 바로** 놓는다(`_place` — 칸이 옮겨지거나 커질 때마다,
  타이머를 기다리지 않는다). 종전에는 칸 안 레이아웃이 묶음을 칸 왼쪽 끝에 붙이고 칸 폭은 `RELAYOUT_MS` 뒤에야 맞춰,
  ① 창을 처음 띄우면 그 사이 묶음이 엉뚱한 자리(실측 378px)에 그려졌고 ② 전체 쪽 수 자릿수('/ 6' ↔ '/ 487')로 묶음 폭이
  ±7px 바뀌면 왼쪽 끝 기준이라 가운데가 흔들렸다. 지금은 묶음 폭이 자릿수와 무관하고(`page_nav.TOTAL_W`) 자리는 가운데 기준이다.
- ★ 261107-3(디자인 SOT §2.8.6.1): 본문 창마다 **정보 한 줄**(`InfoLine` — 사진 정보·PDF 정보)을 그 창 **왼쪽 끝**에.
  상태 막대 위에 떠 있는 단추(배치 칸이 아니다)라 메시지 자리를 줄이지 않고, 쪽 이동 앞에서 끝나며(뒤에서 줄임, '…' 없이),
  왼쪽 임시 메시지 글이 닿는 동안만 숨는다.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QSize, QTimer, QPoint, Qt
from PyQt6.QtGui import QIcon, QPalette
from PyQt6.QtWidgets import (QSizePolicy, QStyle, QStyleOptionToolButton, QStylePainter, QToolButton,
                             QWidget)

MSG_MIN_W = 120          # 왼쪽 메시지 자리(‘N개 PDF’·진행 글)는 이만큼은 남긴다(px)
NAV_GAP = 12             # 2단에서 두 묶음 사이 최소 간격(px)
RELAYOUT_MS = 10         # 칸 폭(sizeHint) 다시 맞추기를 모으는 시간(ms) — 묶음 자리는 기다리지 않는다
EDGE_GAP = 6             # 오른쪽 묶음 ↔ 오른쪽 고정 칸 사이 최소(px)
INFO_GAP = 12            # 정보 한 줄 ↔ 쪽 이동·개수 글·임시 메시지 사이(px)
INFO_MIN_W = 40          # 정보 한 줄이 이보다 좁아지면 숨긴다(px)
INFO_PAD = 4             # 정보 한 줄 글 앞뒤 여백(px)
MSG_X = 6                # QStatusBar 가 임시 메시지 글을 그리기 시작하는 x(Qt messageRect 의 왼쪽)


class InfoLine(QToolButton):
    """정보 한 줄 — 글(`text()`)은 늘 전체, 그리기만 폭에 맞춰 **뒤에서** 줄인다('…' 없음). 툴팁 = 전체 글 + 안내."""

    def __init__(self, host, pane: int, parent):
        super().__init__(parent)
        self._host, self.pane = host, pane
        self._hint = ""
        self._on = False                    # 보일 내용이 있나 — 실제 보임은 host 가 자리를 보고 정한다
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("infoLine%d" % pane)
        self.hide()

    def set_info(self, text, hint: str = "") -> None:
        """text None = 내용 없음(숨김)."""
        self._on = text is not None
        self._hint = hint or ""
        super().setText(text or "")
        full = text or ""
        self.setToolTip(full + ("\n" + self._hint if (full and self._hint) else ""))
        self._host._place_info()

    def setText(self, text):                # 사진 정보처럼 글만 바꿔도 자리·툴팁이 따른다
        self.set_info(text, self._hint)

    def has_info(self) -> bool:
        return self._on

    def sizeHint(self) -> QSize:
        sh = super().sizeHint()
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 2 * INFO_PAD + 2, sh.height())

    def shown_text(self) -> str:
        """지금 폭에 그려지는 글 — 전체 글의 앞부분(뒤에서 덜어 냄)."""
        t = self.text()
        fm = self.fontMetrics()
        avail = self.width() - 2 * INFO_PAD
        if fm.horizontalAdvance(t) <= avail:
            return t
        lo, hi = 0, len(t)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fm.horizontalAdvance(t[:mid]) <= avail:
                lo = mid
            else:
                hi = mid - 1
        return t[:lo].rstrip(" ·")

    def paintEvent(self, ev):
        p = QStylePainter(self)
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text = ""
        opt.icon = QIcon()
        p.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, opt)
        p.setPen(self.palette().color(QPalette.ColorRole.ButtonText))
        p.drawText(self.rect().adjusted(INFO_PAD, 0, -INFO_PAD, 0),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self.shown_text())


class PageNavHost(QWidget):
    """상태 막대 맨 앞 고정 칸 — 본문 창마다의 `MainView.page_nav` 를 담는다(자리는 `_place` 가 직접)."""

    def __init__(self, status, views, panes, parent=None):
        super().__init__(parent or status)
        self.setObjectName("pageNavHost")
        self._status = status
        self._views = list(views)
        self._panes = list(panes)
        self._navs = [v.page_nav for v in self._views]
        for n in self._navs:
            n.setParent(self)
        self._info = [None] * len(self._views)          # 창마다 정보 한 줄(디자인 SOT §2.8.6.1) — 처음 쓸 때 만든다
        self._info_click = None                          # 누르면 부를 함수(창 번호)
        self._left_widget = None                         # 상태 막대 왼쪽 일반 칸 글(개수 칸) — 정보 줄이 그 글을 덮지 않게
        status.messageChanged.connect(lambda _m: self._place_info())
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._want_w = self._nav_need()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RELAYOUT_MS)              # 한 번만(singleShot) — 잇단 크기 바뀜을 모아 칸 폭을 한 번 맞춘다
        self._timer.timeout.connect(self.relayout)
        # 본문 창이 옮겨 가는 모든 길 — 창 크기, 책갈피·썸네일 칸 폭(가르개 안 자리), 2단 켜고 끄기, 묶음 글 폭
        watch = [status] + self._views + self._panes + self._navs
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

    # ── 정보 한 줄 (디자인 SOT §2.8.6.1) ────────────────────────────────
    def info_line(self, i: int) -> InfoLine:
        """i 번 본문 창의 정보 한 줄 — 상태 막대 위에 떠 있는 단추(배치 칸 아님)."""
        b = self._info[i]
        if b is None:
            b = self._info[i] = InfoLine(self, i, self._status)
            b.clicked.connect(lambda _=False, k=i: self._info_click(k) if self._info_click else None)
        return b

    def set_info_handler(self, fn) -> None:
        self._info_click = fn

    def set_left_widget(self, w) -> None:
        self._left_widget = w
        w.installEventFilter(self)           # 글 폭·보임이 바뀌면 정보 줄 자리를 다시 본다

    def _status_x(self, w) -> int:
        win = self.window()
        return self._status.mapFrom(win, w.mapTo(win, QPoint(0, 0))).x()

    def _left_text_end(self) -> int:
        """상태 막대 왼쪽 글이 끝나는 x — 임시 메시지(있으면, 첫 고정 칸 앞까지) 아니면 개수 칸 글."""
        msg = self._status.currentMessage()
        if msg:
            end = MSG_X + self._status.fontMetrics().horizontalAdvance(msg)
            return min(end, self.x())
        w = self._left_widget
        if w is not None and w.isVisible() and w.text():
            m = w.contentsMargins()
            return w.x() + m.left() + w.fontMetrics().horizontalAdvance(w.text())
        return 0

    def _place_info(self) -> None:
        msg_on = bool(self._status.currentMessage())
        end = self._left_text_end()
        for i, b in enumerate(self._info):
            if b is None:
                continue
            if not (b.has_info() and self._shown(i) and self._navs[i].isVisible()):
                b.hide()
                continue
            left = self._status_x(self._views[i])
            right = self.x() + self._navs[i].geometry().x() - INFO_GAP     # 쪽 이동이 먼저
            if end and end + INFO_GAP > left:
                if msg_on:
                    b.hide()                     # 긴 메시지 — 떠 있는 동안만 숨는다
                    continue
                left = end + INFO_GAP            # 개수 칸 글 뒤에서
            w = min(b.sizeHint().width(), right - left)
            if w < INFO_MIN_W:
                b.hide()
                continue
            h = b.sizeHint().height()
            b.setGeometry(left, max(0, (self._status.height() - h) // 2), w, h)
            b.show()
            b.raise_()
            b.update()

    def _nav_need(self) -> int:
        ws = [n.sizeHint().width() for i, n in enumerate(self._navs) if self._shown(i)]
        return sum(ws) + NAV_GAP * max(0, len(ws) - 1)

    def _height(self) -> int:
        return max(n.sizeHint().height() for n in self._navs)

    def sizeHint(self) -> QSize:
        return QSize(max(self._want_w, self._nav_need()), self._height())

    def minimumSizeHint(self) -> QSize:
        return QSize(self._nav_need(), self._height())

    # ── 자리 ───────────────────────────────────────────────────────────
    def _sync_visible(self) -> None:
        for i, n in enumerate(self._navs):
            n.setVisible(self._shown(i))

    def _center_x(self, i: int) -> float:
        """i 번 본문 창 가운데 x — 상태 막대 좌표."""
        v = self._views[i]
        win = self.window()
        return self._status.mapFrom(win, v.mapTo(win, QPoint(0, 0))).x() + v.width() / 2.0

    def _targets(self, right: int):
        """(왼쪽 묶음 x, 오른쪽 묶음 x 또는 None) — 상태 막대 좌표. right = 이 칸 오른쪽 끝(오른쪽 고정 칸 앞)."""
        n0 = self._navs[0].sizeHint().width()
        dual = self._shown(1)
        n1 = self._navs[1].sizeHint().width() if dual else 0
        tail = (NAV_GAP + n1) if dual else 0
        x0 = self._center_x(0) - n0 / 2.0
        x0 = max(MSG_MIN_W, min(right - n0 - tail, x0))
        x1 = None
        if dual:
            x1 = self._center_x(1) - n1 / 2.0
            x1 = min(x1, right - EDGE_GAP - n1)                  # 오른쪽 고정 칸과 겹치면 그만큼만 왼쪽으로
            x1 = max(x1, x0 + n0 + NAV_GAP)                      # 왼쪽 묶음과는 겹치지 않게
        return int(round(x0)), (int(round(x1)) if x1 is not None else None)

    def _place(self) -> None:
        """묶음을 이 칸의 **지금** 자리에서 놓는다 — 칸 폭이 아직 덜 맞았어도 가운데 기준으로(칸 밖으로는 나가지 않게)."""
        self._sync_visible()
        right = self.x() + self.width()
        x0, x1 = self._targets(right)
        h = self.height()

        def put(w, sx):
            sh = w.sizeHint()
            lx = max(0, min(self.width() - sh.width(), sx - self.x()))
            w.setGeometry(lx, max(0, (h - sh.height()) // 2), sh.width(), sh.height())

        put(self._navs[0], x0)
        if x1 is not None:
            put(self._navs[1], x1)
        self._place_info()                    # 정보 한 줄은 쪽 이동 자리를 본다

    def relayout(self) -> None:
        """칸 폭을 '왼쪽 묶음 왼쪽 끝 ~ 오른쪽 끝' 으로 맞추고, 묶음을 바로 놓는다."""
        self._sync_visible()
        right = self.x() + self.width()
        x0, _x1 = self._targets(right)
        want = max(self._nav_need(), right - x0)
        if want != self._want_w:
            self._want_w = want
            self.updateGeometry()
            lay = self._status.layout()
            if lay is not None:
                lay.activate()                 # 바로 다시 배치 — 다음 그리기 전에 칸이 제자리(261105-29 '처음부터')
        self._place()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place()

    def moveEvent(self, ev):
        super().moveEvent(ev)
        self._place()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.relayout()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show, QEvent.Type.Hide,
                 QEvent.Type.LayoutRequest):
            if obj is self._status:
                self._timer.start()            # 상태 막대 자체의 크기 바뀜은 그 레이아웃이 칸을 옮긴 뒤(resize/moveEvent)에 놓인다
            else:
                self.relayout()                # 본문 창·가르개·묶음 — 그 자리에서 바로
                self._timer.start()            # 잇단 바뀜 끝에 한 번 더(칸 폭)
        return False
