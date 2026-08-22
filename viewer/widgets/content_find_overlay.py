"""우측 패널(건설기준/법령·고시/특허) 본문 검색용 슬라이드 오버레이.

SOT: `검색창 작업 계획서.md`. 우측 패널이 열려 있을 때 Ctrl+F 로 상단에서 슬라이드로 나타나며,
- 검색 입력 + 'N/M' 개수 + ∧∨ 이동 + ✕ 닫기(브라우저 찾기바 스타일).
- 아래에 **검색된 항목(문맥 스니펫) 목록** 표시 → 클릭하면 그 매치로 이동.
- 본문은 `content_find` 로 전체 하이라이트(현재 매치 강조).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QPropertyAnimation, QRect
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QToolButton, QListWidget,
    QListWidgetItem,
)

from viewer.widgets import content_find as cf


class ContentFindOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._panel = None
        self._state: dict = {}
        self.setObjectName("cfoverlay")
        self.setStyleSheet(
            "QWidget#cfoverlay{background:#ffffff;border:1px solid #b8b8b8;border-radius:8px;}"
            "QLineEdit{border:1px solid #cfcfcf;border-radius:5px;padding:4px 6px;}"
            "QToolButton{border:none;padding:2px 8px;font-size:14px;}"
            "QToolButton:hover{background:#eaeaea;border-radius:5px;}")

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        bar = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("본문 내용 검색")
        self.count = QLabel("0/0")
        self.count.setStyleSheet("color:#666;min-width:44px;")
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_prev = QToolButton(); self.btn_prev.setText("∧"); self.btn_prev.setToolTip("이전 (Shift+Enter)")
        self.btn_next = QToolButton(); self.btn_next.setText("∨"); self.btn_next.setToolTip("다음 (Enter)")
        self.btn_close = QToolButton(); self.btn_close.setText("✕"); self.btn_close.setToolTip("닫기 (Esc)")
        for w in (self.edit, self.count, self.btn_prev, self.btn_next, self.btn_close):
            bar.addWidget(w, 1 if w is self.edit else 0)
        v.addLayout(bar)
        self.list = QListWidget()
        self.list.setMaximumHeight(220)
        self.list.setStyleSheet("QListWidget{border:1px solid #e2e2e2;border-radius:5px;}")
        v.addWidget(self.list)

        self.edit.textChanged.connect(self._on_text)
        self.edit.returnPressed.connect(self._on_enter)
        self.btn_prev.clicked.connect(lambda: self._nav(True))
        self.btn_next.clicked.connect(lambda: self._nav(False))
        self.btn_close.clicked.connect(self.close_overlay)
        self.list.itemClicked.connect(self._on_item)
        QShortcut(QKeySequence("Esc"), self.edit, activated=self.close_overlay)

        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(160)
        self.hide()

    # ----- 열기/닫기(슬라이드) -----
    def open_for(self, panel, seed_query: str = ""):
        self._panel = panel
        self._state = {}
        lbl = getattr(panel, "CONTENT_LABEL", "본문")
        self.edit.setPlaceholderText(f"{lbl} 내용 검색")
        par = self.parentWidget()
        w = min(480, (par.width() - 40) if par else 480)
        h = 300
        x = (par.width() - w - 20) if par else 20
        target = QRect(x, 12, w, h)
        self.setGeometry(QRect(x, -h, w, h))
        self.show(); self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(target)
        self._anim.start()
        if seed_query:
            self.edit.setText(seed_query)
        self.edit.setFocus(); self.edit.selectAll()
        if self.edit.text().strip():
            self._on_text()

    def close_overlay(self):
        v = self._viewer()
        if v is not None:
            try:
                cf.clear(v, self._state)
            except Exception:
                pass
        self.hide()

    def _viewer(self):
        return getattr(self._panel, "viewer", None) if self._panel is not None else None

    # ----- 검색/이동 -----
    def _on_text(self):
        v = self._viewer()
        if v is None:
            return
        self._state.pop("query", None)          # 입력 변경 → 항상 첫 매치부터(이동 아님)
        cur, tot = cf.search(v, self.edit.text().strip(), False, self._state)
        self.count.setText(f"{cur}/{tot}")
        self._fill_list()

    def _on_enter(self):
        from PyQt6.QtWidgets import QApplication
        back = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._nav(back)

    def _nav(self, backward: bool):
        v = self._viewer()
        if v is None:
            return
        cur, tot = cf.search(v, self.edit.text().strip(), backward, self._state)
        self.count.setText(f"{cur}/{tot}")
        idx = self._state.get("idx", -1)
        if 0 <= idx < self.list.count():
            self.list.setCurrentRow(idx)

    def _fill_list(self):
        self.list.clear()
        v = self._viewer()
        for i, snip in enumerate(cf.snippets(v, self._state)):
            self.list.addItem(QListWidgetItem(f"{i + 1}.  {snip}"))
        idx = self._state.get("idx", -1)
        if 0 <= idx < self.list.count():
            self.list.setCurrentRow(idx)

    def _on_item(self, item):
        v = self._viewer()
        if v is None:
            return
        cur, tot = cf.goto(v, self._state, self.list.row(item))
        self.count.setText(f"{cur}/{tot}")
