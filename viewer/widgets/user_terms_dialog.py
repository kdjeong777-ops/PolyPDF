"""261019-5(단어장 SOT §4.1, 사용자 지시 '사용자 뜻만 불러서 수정할 수도 있어야'): **사용자 뜻** 목록·고치기·지우기.

사용자 뜻은 `user_dict.db`(DictStore 의 사용자 출처)에만 있다 — 기본 사전·자동 뜻은 이 창에 나오지 않는다.
고치기는 단어장의 편집 창(`StudyEditDialog`)을 그대로 쓴다(같은 칸·같은 저장).
이 기능은 한국 전용(단어장)이라 화면 문구를 `tr()` 로 감싸지 않는다(다국어 SOT §7).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QTableWidget,
                             QTableWidgetItem, QAbstractItemView, QHeaderView, QPushButton,
                             QLabel, QMessageBox)


class UserTermsDialog(QDialog):
    def __init__(self, store, edit_fn, parent=None):
        """store = DictStore, edit_fn(entry: dict) -> 'saved'|'deleted'|None (편집 창을 띄우고 저장까지)."""
        super().__init__(parent)
        self.setWindowTitle("사용자 뜻 편집")
        self.setMinimumSize(720, 480)
        self._store = store
        self._edit_fn = edit_fn
        self._rows = []
        v = QVBoxLayout(self)
        v.addWidget(QLabel("직접 고치거나 더한 뜻만 보입니다. 사용자 뜻은 따로 저장되고(<code>user_dict.db</code>) "
                           "사전·자동 뜻보다 <b>가장 먼저</b> 쓰입니다."))
        top = QHBoxLayout()
        self.ed_q = QLineEdit()
        self.ed_q.setPlaceholderText("표제어 찾기(한글·영문)")
        self.ed_q.setClearButtonEnabled(True)
        top.addWidget(self.ed_q, 1)
        v.addLayout(top)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["한글 표제어", "영문 표제어", "한글 뜻", "영어 뜻"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._edit())
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.btn_new = QPushButton("새 뜻…")
        self.btn_edit = QPushButton("수정…")
        self.btn_del = QPushButton("삭제")
        for b, fn in ((self.btn_new, self._new), (self.btn_edit, self._edit), (self.btn_del, self._delete)):
            b.setAutoDefault(False); b.setDefault(False)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self.info = QLabel("")
        self.info.setStyleSheet("color:#666;")
        row.addWidget(self.info)
        b_close = QPushButton("닫기")
        b_close.setAutoDefault(False)
        b_close.clicked.connect(self.accept)
        row.addWidget(b_close)
        v.addLayout(row)
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(250)
        self._t.timeout.connect(self.reload)
        self.ed_q.textChanged.connect(lambda _t: self._t.start())
        self.reload()

    def reload(self):
        try:
            self._rows = self._store.user_entries(self.ed_q.text())
        except Exception:
            self._rows = []
        self.table.setRowCount(0)
        for e in self._rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, k in enumerate(("term_ko", "term_en", "def_ko", "def_en")):
                t = str(e.get(k) or "").replace("\n", " ")
                self.table.setItem(r, c, QTableWidgetItem(t[:120]))
        self.info.setText(f"사용자 뜻 {len(self._rows)}개")
        self.btn_edit.setEnabled(bool(self._rows))
        self.btn_del.setEnabled(bool(self._rows))

    def _cur(self):
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def _new(self):
        if self._edit_fn({}):
            self.reload()

    def _edit(self):
        e = self._cur()
        if e is not None and self._edit_fn(dict(e)):
            self.reload()

    def _delete(self):
        e = self._cur()
        if e is None:
            return
        name = e.get("term_ko") or e.get("term_en") or ""
        if QMessageBox.question(self, "사용자 뜻 삭제", f"'{name}' 의 사용자 뜻을 지울까요?\n"
                                "(사전·자동 뜻은 그대로 — 지우면 그것이 다시 보입니다)") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.delete_entry(int(e["entry_id"]))
        except Exception as ex:
            QMessageBox.warning(self, "사용자 뜻 삭제", str(ex))
        self.reload()
