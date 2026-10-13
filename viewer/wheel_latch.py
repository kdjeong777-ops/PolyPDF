# -*- coding: utf-8 -*-
"""휠은 시작한 창에서만 (입력 SOT §2.11, 261014-1 사용자 보고).

사용자 보고: 텍스트 창에서 휠로 끝까지 내린 뒤 마우스를 본문으로 옮기면, **남은 휠**
(관성 휠·고해상도 휠·트랙패드 여운)이 본문에 들어가 본문이 위아래로 움직였다.

Windows 는 휠 이벤트를 **지금 마우스 아래** 창에 보낸다. 한 번 굴린 휠이 이어 보내는
이벤트도 마우스를 옮기면 새 창으로 간다. 그래서 휠 이벤트를 **창(스크롤 영역) 단위로
묶는다** — 이어지는 휠은 처음 받은 창에서만 쓰고, 다른 창에 닿은 것은 버린다. 휠이
`LATCH_MS` 동안 멈추면 묶음이 풀려 다음 휠은 마우스 아래 창이 받는다. 트랙패드에서
손가락을 새로 얹으면(`ScrollBegin`) 기다리지 않고 바로 그 창이 받는다.
"""
import time

from PyQt6.QtCore import QObject, QEvent, Qt
from PyQt6.QtWidgets import QAbstractScrollArea, QWidget

LATCH_MS = 300      # 휠이 이만큼 멈추면 묶음을 푼다 — 관성 휠의 칸 사이(수십 ms)보다 넉넉히 길다


def pane_of(w):
    """휠을 묶는 단위 — 가장 가까운 스크롤 영역(뷰포트면 그 주인), 없으면 그 창(최상위)."""
    cur = w
    while cur is not None:
        if isinstance(cur, QAbstractScrollArea):
            return cur
        cur = cur.parentWidget()
    return w.window() if isinstance(w, QWidget) else None


class WheelLatch(QObject):
    """`QApplication` 에 거는 이벤트 필터. 휠 하나를 받은 창 밖으로 새지 않게 한다."""

    def __init__(self, parent=None, latch_ms: int = LATCH_MS):
        super().__init__(parent)
        self.latch_ms = float(latch_ms)
        self._pane = None
        self._last = 0.0
        self.dropped = 0            # 검사용 — 버린 이벤트 수

    def eventFilter(self, obj, event):
        try:
            if event.type() != QEvent.Type.Wheel or not isinstance(obj, QWidget):
                return False
            pane = pane_of(obj)
            now = time.monotonic() * 1000.0
            if (pane is not self._pane and self._pane is not None
                    and now - self._last < self.latch_ms
                    and event.phase() != Qt.ScrollPhase.ScrollBegin):
                # 앞 창에서 굴리던 휠이 마우스를 따라 넘어왔다 — 버린다. 시각은 늘린다:
                #   휠이 이어지는 동안은 계속 묶고, **멈춰야** 풀린다(긴 관성의 꼬리도 막는다).
                self.dropped += 1
                self._last = now
                return True
            self._pane = pane
            self._last = now
        except Exception:
            pass
        return False
