# -*- coding: utf-8 -*-
"""쪽 이동 묶음 하나 — `❮ [칸] / 전체 ❯` (261105-27, 사용자 지시 '모두 화면 아래 중앙에 페이지 이동이 있도록 … 전체 통일').

규칙 원본은 화면 디자인 SOT §2.20 '쪽 이동은 화면 아래 가운데'. 본문(창 아래 상태 막대, `page_nav_bar.PageNavHost`)과
모든 미리보기 창(인쇄·병합·다단·크롭·가림·발표 보기 설정·목차 검토)이 이 위젯 하나를 쓴다 — 모양·치수·동작이 같다.

- `❮` `❯` 는 폭 `BTN_W`, 칸은 폭 `SPIN_W`(올림·내림 단추 없음, 가운데 글), 모두 높이 `NAV_H`.
- 칸에 쓰고 Enter(또는 칸을 떠나면) → `pageRequested(1부터)`. 단추 → `stepRequested(±1)`. 위젯은 쪽을 스스로 바꾸지 않는다 — 쓰는 쪽이 `set_state` 로 알려 준다.
- `prefix`(예: 인쇄 다단 '시트 ')는 칸 앞에 작은 글로. `editable=False` 면 칸 대신 글(`set_text`) — 이동 단위가 쪽 하나가 아닌 곳(발표 보기 설정의 펼침).
- `centered_row(nav, right=…)` 는 양쪽에 **같은 폭 칸**을 두어 옆에 다른 단추가 있어도 묶음이 정확히 가운데에 서게 한다.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox, QWidget

NAV_H = 26          # = MainView.TOOLBAR_H (디자인 SOT §2.10)
BTN_W = 24
SPIN_W = 46
TOTAL_W = "/ 8888"   # '/ 전체' 칸 최소 폭을 재는 글 — 9,999쪽까지 묶음 폭이 같다(261105-29)


class PageNav(QWidget):
    stepRequested = pyqtSignal(int)      # -1 / +1
    pageRequested = pyqtSignal(int)      # 1부터

    def __init__(self, parent=None, *, editable: bool = True, prefix: str = ""):
        super().__init__(parent)
        self.setObjectName("pageNav")
        self._editable = editable
        self._prefix = prefix
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.btn_prev = QPushButton("❮")
        self.btn_next = QPushButton("❯")
        for b in (self.btn_prev, self.btn_next):
            b.setFixedSize(BTN_W, NAV_H)
            b.setAutoDefault(False)                 # 디자인 SOT §2.7 — 대화상자 Enter 로 눌리지 않게
            b.setDefault(False)
            b.setStyleSheet("QPushButton{font-size:13px;font-weight:bold;padding:0;text-align:center;}")
        self.lbl_prefix = QLabel(prefix)
        self.lbl_prefix.setFixedHeight(NAV_H)
        self.lbl_prefix.setVisible(bool(prefix))
        self.spin = QSpinBox()
        self.spin.setMinimum(1)
        self.spin.setFixedSize(SPIN_W, NAV_H)
        self.spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin.setKeyboardTracking(False)
        self.spin.setVisible(editable)
        self.lbl_total = QLabel("/ 0")
        self.lbl_total.setFixedHeight(NAV_H)
        # 261105-29: '/ 전체' 칸 폭은 자릿수와 무관(`TOTAL_W` 글 폭 이상) — 파일마다 '/ 6' ↔ '/ 487' 로 묶음 폭이 바뀌어
        #   가운데에 둔 묶음이 흔들렸다. 글은 칸 왼쪽에 붙인다(칸 숫자 바로 뒤에 읽히게).
        self.lbl_total.setMinimumWidth(self.lbl_total.fontMetrics().horizontalAdvance(TOTAL_W) + 2)
        self.lbl_total.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for w in (self.btn_prev, self.lbl_prefix, self.spin, self.lbl_total, self.btn_next):
            lay.addWidget(w)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_prev.clicked.connect(lambda: self.stepRequested.emit(-1))
        self.btn_next.clicked.connect(lambda: self.stepRequested.emit(+1))
        self.spin.editingFinished.connect(self._on_edited)
        self._cur, self._total = 0, 0

    def _on_edited(self):
        v = int(self.spin.value())
        if self._total and v != self._cur:
            self.pageRequested.emit(v)

    def set_prefix(self, prefix: str) -> None:
        self._prefix = prefix
        self.lbl_prefix.setText(prefix)
        self.lbl_prefix.setVisible(bool(prefix))

    def set_state(self, cur: int, total: int, can_prev=None, can_next=None) -> None:
        """지금 쪽(1부터)·전체 — 단추는 끝에서 꺼진다(넘어가는 길이 따로 있으면 can_prev/can_next 로)."""
        total = max(0, int(total))
        cur = max(1, min(max(1, total), int(cur))) if total else 0
        self._cur, self._total = cur, total
        self.spin.blockSignals(True)
        self.spin.setMaximum(max(1, total))
        self.spin.setValue(max(1, cur))
        self.spin.blockSignals(False)
        self.spin.setEnabled(total > 0)
        self.lbl_total.setText(f"/ {total}")
        self.btn_prev.setEnabled(bool(total) and (cur > 1 if can_prev is None else bool(can_prev)))
        self.btn_next.setEnabled(bool(total) and (cur < total if can_next is None else bool(can_next)))

    def set_text(self, text: str, can_prev: bool, can_next: bool) -> None:
        """editable=False — 칸 대신 글(예: '3·4쪽')."""
        self.lbl_total.setText(text)
        self.btn_prev.setEnabled(bool(can_prev))
        self.btn_next.setEnabled(bool(can_next))

    def text(self) -> str:
        """보이는 글 한 줄(검사·접근성용) — '시트 2 / 8', '3 / 6', '' (빈 대상)."""
        if not self._editable:
            return self.lbl_total.text()
        if not self._total:
            return ""
        return f"{self._prefix}{self._cur} / {self._total}"


def centered_row(nav: QWidget, left: QWidget | None = None, right: QWidget | None = None) -> QHBoxLayout:
    """[왼쪽 칸][nav][오른쪽 칸] — 두 칸은 늘림 비율·최소 폭이 같아 nav 가 줄 가운데에 선다(옆 단추가 있어도)."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    boxes = []
    for w, align in ((left, Qt.AlignmentFlag.AlignLeft), (right, Qt.AlignmentFlag.AlignRight)):
        box = QWidget()
        bl = QHBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        if w is not None:
            bl.addWidget(w, 0, align | Qt.AlignmentFlag.AlignVCenter)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        boxes.append((box, w))
    side = max([w.sizeHint().width() for _b, w in boxes if w is not None] or [0])
    for box, _w in boxes:
        box.setMinimumWidth(side)
    row.addWidget(boxes[0][0], 1)
    row.addWidget(nav, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(boxes[1][0], 1)
    return row
