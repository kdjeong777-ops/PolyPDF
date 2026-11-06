# -*- coding: utf-8 -*-
"""동그란 ? 도움말 단추 — 대화상자 공통 (디자인 SOT §2.21, 261106-12 사용자 지시 '설명 내용을 동그란 ? 로, 누르면 호버링되거나 창으로').

안내 글을 창에 늘 띄우면 글 줄이 생기고 사라질 때 창 배치가 흔들린다(사진 크롭 창에서 실제로 칸이 줄었다). 그런 안내는 이 단추로 —
올리면 풍선 도움말(툴팁), 누르면 같은 글을 작은 창으로. 글은 HTML 이고, 바뀔 수 있으면 `set_html` 로 다시 넣는다.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QToolButton

from viewer.i18n import tr

HELP_PX = 22               # 지름


class HelpButton(QToolButton):
    def __init__(self, html: str = "", title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("helpButton")
        self.setText("?")
        self.setAccessibleName(tr("도움말"))
        self.setFixedSize(HELP_PX, HELP_PX)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setStyleSheet("QToolButton#helpButton{border:1px solid palette(mid);border-radius:%dpx;font-weight:bold;}"
                           "QToolButton#helpButton:hover{background:palette(midlight);}" % (HELP_PX // 2))
        self._title = title or tr("도움말")
        self.set_html(html)
        self.clicked.connect(self.show_window)

    def set_html(self, html: str) -> None:
        self._html = html or ""
        self.setToolTip(self._html)

    def html(self) -> str:
        return self._html

    def show_window(self) -> None:
        box = QMessageBox(QMessageBox.Icon.NoIcon, self._title, self._html, QMessageBox.StandardButton.Ok, self.window())
        box.setTextFormat(Qt.TextFormat.RichText)
        box.exec()
