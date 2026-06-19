"""즐겨찾기 메뉴 구현 (v1.6.1 F1~F7).

데이터 모델: settings.json 의 'favorites' 키 — 항목 리스트.
각 항목:
    {"name": "표시명", "kind": "folder"|"search",
     "folder": "...", "query": "...(검색용)"}

UI:
  - 즐겨찾기 관리 다이얼로그 (이름 변경 / 삭제 / 위/아래 이동 / 패널에 등록 안내)
  - 메뉴 '즐겨찾기' 동적 항목: 클릭 시 해당 폴더/검색 즉시 실행

저장은 settings_store v6 → v7 마이그레이션으로 키만 추가.
"""
from __future__ import annotations

from typing import List
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QLabel, QMessageBox, QDialogButtonBox,
    QInputDialog,
)


def make_unique_name(base: str, existing: list) -> str:
    """기존 리스트에 같은 이름이 있으면 (1), (2)... 접미사."""
    names = {f.get("name", "") for f in existing}
    if base not in names:
        return base
    n = 1
    while f"{base}({n})" in names:
        n += 1
    return f"{base}({n})"


class FavoritesDialog(QDialog):
    """즐겨찾기 관리 다이얼로그.

    parent.app_main_window 가 (favorites: list, callbacks) 주입.
    """

    def __init__(self, favorites: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("즐겨찾기 관리")
        self.resize(560, 460)
        # 260611-107: 항목 dict 를 깊은 복사 — 다이얼로그 편집(이름변경 등)이 원본을
        #   바로 건드리지 않게 하여, 확인(OK) 시에만 정확히 반영(취소 시 원복).
        import copy as _copy
        self._favs: List[dict] = [_copy.deepcopy(f) for f in favorites]

        layout = QVBoxLayout(self)

        info = QLabel("드래그하거나 ↑/↓ 버튼으로 순서 변경. 더블클릭으로 이름 수정.")
        info.setStyleSheet("color:#666;")
        layout.addWidget(info)

        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.itemDoubleClicked.connect(self._on_rename)
        for f in self._favs:
            self._append_to_list(f)
        body.addWidget(self.list, 1)

        # 우측 버튼 패널
        btns = QVBoxLayout()
        b_up = QPushButton("↑ 위로")
        b_up.clicked.connect(lambda: self._move(-1))
        b_dn = QPushButton("↓ 아래로")
        b_dn.clicked.connect(lambda: self._move(+1))
        b_rm = QPushButton("삭제")
        b_rm.clicked.connect(self._remove)
        b_rn = QPushButton("이름 변경")
        b_rn.clicked.connect(lambda: self._on_rename(self.list.currentItem()))
        btns.addWidget(b_up)
        btns.addWidget(b_dn)
        btns.addWidget(b_rn)
        btns.addWidget(b_rm)
        btns.addStretch(1)
        body.addLayout(btns)

        layout.addLayout(body, 1)

        # 닫기
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _append_to_list(self, f: dict):
        kind = f.get("kind", "folder")
        prefix = {"folder": "📁 ", "file": "📄 ", "search": "🔍 "}.get(kind, "📁 ")
        it = QListWidgetItem(f"{prefix}{f.get('name', '?')}")
        it.setData(Qt.ItemDataRole.UserRole, f)
        it.setToolTip(self._tip(f))
        self.list.addItem(it)

    @staticmethod
    def _tip(f: dict) -> str:
        if f.get("kind") == "search":
            return f"검색: '{f.get('query', '')}' (폴더 {f.get('folder', '')})"
        if f.get("kind") == "file":
            return f.get("file", "") or f.get("folder", "")
        return f.get("folder", "")

    def _move(self, delta: int):
        row = self.list.currentRow()
        if row < 0: return
        new_row = row + delta
        if new_row < 0 or new_row >= self.list.count(): return
        item = self.list.takeItem(row)
        self.list.insertItem(new_row, item)
        self.list.setCurrentRow(new_row)

    def _remove(self):
        row = self.list.currentRow()
        if row < 0: return
        ret = QMessageBox.question(
            self, "삭제",
            f"'{self.list.item(row).text()}' 을(를) 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.list.takeItem(row)

    def _on_rename(self, item: QListWidgetItem):
        if item is None: return
        f = item.data(Qt.ItemDataRole.UserRole) or {}
        old_name = f.get("name", "")
        new_name, ok = QInputDialog.getText(self, "이름 변경",
                                            "새 이름:", text=old_name)
        if ok and new_name.strip():
            f["name"] = new_name.strip()
            kind = f.get("kind", "folder")
            prefix = {"folder": "📁 ", "file": "📄 ", "search": "🔍 "}.get(kind, "📁 ")
            item.setText(f"{prefix}{f['name']}")
            item.setData(Qt.ItemDataRole.UserRole, f)
            item.setToolTip(self._tip(f))

    def result_favorites(self) -> list:
        out = []
        for i in range(self.list.count()):
            f = self.list.item(i).data(Qt.ItemDataRole.UserRole) or {}
            out.append(f)
        return out


class AddFavoriteDialog(QDialog):
    """즐겨찾기 추가 — 이름 미리 채워줌, 사용자가 수정 가능."""

    def __init__(self, suggested_name: str, kind: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("즐겨찾기 등록")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"종류: {'📁 폴더' if kind == 'folder' else '🔍 검색'}"))
        layout.addWidget(QLabel("이름 (수정 가능):"))
        self.edit = QLineEdit(suggested_name)
        self.edit.selectAll()
        layout.addWidget(self.edit)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def name(self) -> str:
        return self.edit.text().strip()
