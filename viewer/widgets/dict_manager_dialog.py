"""단어장 관리 다이얼로그 — 출처 on/off · 우선순위(▲▼) · 폴더 관리.

SOT: `단어장 작업 계획서.md`. dict.db 출처(여러 단어장)를 표로 관리.
- 사용 체크(enabled), 우선순위 이동(▲▼ → priority 재배정), 종류/구분/항목수 표시.
- 폴더 열기 / 새로고침(폴더→dict.db 동기화) / 양식 CSV / 가져오기.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QMessageBox,
)

_KIND_LABEL = {"user": "사용자", "base": "사전/용어집", "auto": "자동(번역)",
               "online": "인터넷"}


class DictManagerDialog(QDialog):
    changed = pyqtSignal()

    def __init__(self, store, prefs: dict = None, host=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("단어장 관리")
        self.setMinimumSize(720, 460)
        self._store = store
        self._prefs = prefs or {}
        self._host = host

        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "여러 단어장(출처)을 <b>사용 여부</b>와 <b>우선순위(▲▼)</b>로 관리합니다. "
            "조회 우선순위: 사용자 ▶ 사전/용어집 ▶ 자동/인터넷, 같은 종류 안에서는 위(우선)부터.<br>"
            "<small>단어장 폴더에 표준 CSV(+ meta)를 넣고 [새로고침]하면 출처로 등록됩니다.</small>"))

        body = QHBoxLayout()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["사용", "종류", "구분", "출처명", "항목"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        body.addWidget(self.table, 1)

        col = QVBoxLayout()
        col.addStretch(1)
        b_up = QPushButton("▲"); b_up.setFixedWidth(40); b_up.setToolTip("우선순위 올림")
        b_dn = QPushButton("▼"); b_dn.setFixedWidth(40); b_dn.setToolTip("우선순위 내림")
        b_up.clicked.connect(lambda: self._move(-1))
        b_dn.clicked.connect(lambda: self._move(+1))
        b_del = QPushButton("삭제"); b_del.setFixedWidth(40)
        b_del.setToolTip("선택 단어장(출처) 삭제 — 사용자 단어장은 보호")
        b_del.clicked.connect(self._delete)
        col.addWidget(b_up); col.addWidget(b_dn); col.addSpacing(14); col.addWidget(b_del)
        col.addStretch(1)
        body.addLayout(col)
        v.addLayout(body, 1)

        row2 = QHBoxLayout()
        for txt, fn in (("폴더 열기", self._open_folder), ("새로고침", self._refresh_folder),
                        ("양식 CSV", self._write_sample), ("가져오기…", self._import)):
            b = QPushButton(txt); b.clicked.connect(fn); row2.addWidget(b)
        row2.addStretch(1)
        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self._on_close)
        row2.addWidget(self.btn_close)
        v.addLayout(row2)

        self.info = QLabel("")
        self.info.setStyleSheet("color:#666;")
        v.addWidget(self.info)

        self._reload()

    # ----- 표 -----
    def _reload(self):
        srcs = []
        try:
            srcs = self._store.list_sources()
        except Exception:
            srcs = []
        self.table.setRowCount(0)
        for s in srcs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                         | Qt.ItemFlag.ItemIsSelectable)
            chk.setCheckState(Qt.CheckState.Checked if s.get("enabled")
                              else Qt.CheckState.Unchecked)
            chk.setData(Qt.ItemDataRole.UserRole, s.get("source_id"))
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QTableWidgetItem(_KIND_LABEL.get(s.get("kind"), s.get("kind") or "")))
            self.table.setItem(r, 2, QTableWidgetItem(s.get("category") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(s.get("name") or s.get("source_id") or ""))
            self.table.setItem(r, 4, QTableWidgetItem(str(s.get("n_entries", 0))))
        self.info.setText(f"단어장(출처) {self.table.rowCount()}개")

    def _row_sid(self, r):
        it = self.table.item(r, 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _move(self, direction: int):
        r = self.table.currentRow()
        if r < 0:
            return
        nr = r + direction
        if nr < 0 or nr >= self.table.rowCount():
            return
        self._apply_enabled()        # 체크 상태 저장
        # 표 순서대로 우선순위를 10단위 재배정(낮을수록 우선) 후 두 행 교환
        order = [self._row_sid(i) for i in range(self.table.rowCount())]
        order[r], order[nr] = order[nr], order[r]
        try:
            for i, sid in enumerate(order):
                if sid:
                    self._store.set_source_priority(sid, (i + 1) * 10)
        except Exception:
            pass
        self._reload()
        self.table.setCurrentCell(nr, 0)
        self.changed.emit()

    def _apply_enabled(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if not it:
                continue
            sid = it.data(Qt.ItemDataRole.UserRole)
            on = it.checkState() == Qt.CheckState.Checked
            try:
                self._store.set_source_enabled(sid, on)
            except Exception:
                pass

    def _delete(self):
        r = self.table.currentRow()
        sid = self._row_sid(r)
        if not sid:
            return
        name = self.table.item(r, 3).text() if self.table.item(r, 3) else sid
        if QMessageBox.question(self, "단어장 삭제",
                                f"'{name}' 출처와 항목을 삭제할까요?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.delete_source(sid)
        except Exception:
            pass
        self._reload()
        self.changed.emit()

    # ----- 폴더 -----
    def _open_folder(self):
        from viewer.study import glossary_folder as gf
        d = gf.glossaries_dir(self._prefs)
        try:
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(str(d))
        except Exception as e:
            self.info.setText(f"폴더 열기 실패: {e}")

    def _refresh_folder(self):
        from viewer.study import glossary_folder as gf
        try:
            s = gf.sync_folder(self._store, self._prefs)
            self.info.setText(f"폴더 동기화: 파일 {s['files']}개 · 갱신 {s['updated']} · "
                              f"삭제 {s['removed']}  ({s['dir']})")
        except Exception as e:
            self.info.setText(f"동기화 실패: {e}")
        self._reload()
        self.changed.emit()

    def _write_sample(self):
        from viewer.study import glossary_folder as gf
        try:
            p = gf.write_sample(prefs=self._prefs)
            self.info.setText(f"양식 저장: {p}")
            os.startfile(str(p.parent))
        except Exception as e:
            self.info.setText(f"양식 저장 실패: {e}")

    def _import(self):
        if self._host is not None and hasattr(self._host, "_action_import_glossary"):
            self._host._action_import_glossary()
            self._reload()
            self.changed.emit()

    def _on_close(self):
        self._apply_enabled()
        self.changed.emit()
        self.accept()
