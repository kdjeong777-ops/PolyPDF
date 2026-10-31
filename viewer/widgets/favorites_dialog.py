"""즐겨찾기 (v1.6.1 F1~F7 → 261025-1 즐겨찾기 탭, 디자인 SOT §2.9.5).

데이터 모델: settings.json 의 'favorites' 키 — 항목 리스트.
각 항목:
    {"name": "표시명", "kind": "folder"|"file"|"search",
     "folder": "...", "file": "...(파일용)", "query": "...(검색용)",
     "short": "...(선택 — 폴더·파일 개별 단추의 요약 이름, 261025-1)"}
법령·고시 / 특허 / 건설기준 즐겨찾기는 따로 저장된다(`law_favorites`·`kipo_favorites`·`kcsc_favorites`, 마스터 §8.2).

UI:
  - `항목 관리` 창(`FavoritesManagerDialog`) — 종류마다 탭(이름 변경 / 단추 이름 / 삭제 / 위·아래 이동)
  - `즐겨찾기` 탭의 드롭다운·개별 단추는 `MainWindow._refresh_favorites_menu`
"""
from __future__ import annotations

import copy

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QLabel, QMessageBox, QDialogButtonBox,
    QInputDialog, QTabWidget, QWidget,
)
from viewer.i18n import tr


# 261008-12: 즐겨찾기 메뉴와 같은 그룹 순서 — 폴더 → 파일 → 검색어(kind 가 없거나 모르면 폴더).
KIND_ORDER = ("folder", "file", "search")
KIND_PREFIX = {"folder": "📁 ", "file": "📄 ", "search": "🔍 "}
# 261025-1(디자인 SOT §2.9.5): `기타` 의 종류 — 차례는 보기 탭(법령·고시 → 특허 → 건설기준)
OTHER_KINDS = ("law", "kipo", "kcsc")
OTHER_PREFIX = {"law": "⚖ ", "kipo": "📄 ", "kcsc": "🏗 "}
SHORT_MAX = 12          # 개별 단추 요약 이름 — 이보다 길면 가운데를 줄인다
BUTTONS_MAX = 3         # 등록 폴더·등록 파일 개별 단추 수(목록 앞에서부터) — 261031-12 사용자 지시(종전 5)


def fav_kind(f: dict) -> str:
    k = f.get("kind")
    return k if k in KIND_ORDER else "folder"


def group_by_kind(favs: list) -> list:
    """종류 그룹 순서로 안정 정렬 — 그룹 안은 원래(등록·사용자가 정한) 순서 그대로."""
    return sorted(favs, key=lambda f: KIND_ORDER.index(fav_kind(f)))


def make_unique_name(base: str, existing: list) -> str:
    """기존 리스트에 같은 이름이 있으면 (1), (2)... 접미사."""
    names = {f.get("name", "") for f in existing}
    if base not in names:
        return base
    n = 1
    while f"{base}({n})" in names:
        n += 1
    return f"{base}({n})"


def middle_ellipsis(text: str, n: int = SHORT_MAX) -> str:
    """`n` 자보다 길면 가운데를 `…` 로 줄인다 — 앞쪽을 한 자 더 남긴다."""
    t = text or ""
    if len(t) <= n:
        return t
    keep = max(n - 1, 2)
    head = (keep + 1) // 2
    tail = keep - head
    return t[:head] + "…" + (t[-tail:] if tail else "")


def short_label(f: dict) -> str:
    """개별 단추 글 — 사용자가 정한 `short`, 없으면 등록 이름의 가운데 줄임(디자인 SOT §2.9.5)."""
    s = str(f.get("short") or "").strip()
    return s or middle_ellipsis(str(f.get("name", "?")))


def other_label(kind: str, f: dict) -> str:
    """법령·고시 / 특허 / 건설기준 즐겨찾기 한 줄 — 종전 메뉴 구역과 같은 꼴."""
    if kind == "kipo":
        return OTHER_PREFIX[kind] + (f.get("name") or f.get("appNo") or f.get("regNo") or tr("특허"))
    label = OTHER_PREFIX[kind] + f.get("name", "?")
    extra = (f.get("kind_label") or f.get("category")) if kind == "law" else f.get("category")
    if extra:
        label += f"  ({extra})"
    return label


def kind_title(kind: str) -> str:
    return {"folder": tr("폴더"), "file": tr("파일"), "search": tr("검색어"),
            "law": tr("법령·고시"), "kipo": tr("특허"), "kcsc": tr("건설기준")}[kind]


class _FavList(QWidget):
    """관리 창의 탭 하나 — 목록 + 위·아래·이름 변경·(단추 이름)·삭제."""

    def __init__(self, kind: str, favs: list, parent=None):
        super().__init__(parent)
        self.kind = kind
        h = QHBoxLayout(self)
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.itemDoubleClicked.connect(self._on_rename)
        for f in favs:
            self._append(copy.deepcopy(f))
        h.addWidget(self.list, 1)
        btns = QVBoxLayout()
        b_up = QPushButton(tr("↑ 위로"))
        b_up.clicked.connect(lambda: self._move(-1))
        b_dn = QPushButton(tr("↓ 아래로"))
        b_dn.clicked.connect(lambda: self._move(+1))
        b_rn = QPushButton(tr("이름 변경"))
        b_rn.clicked.connect(lambda: self._on_rename(self.list.currentItem()))
        for b in (b_up, b_dn, b_rn):
            btns.addWidget(b)
        self.btn_short = None
        if kind in ("folder", "file"):
            self.btn_short = QPushButton(tr("단추 이름"))
            self.btn_short.setToolTip(tr("즐겨찾기 탭 개별 단추에 보일 짧은 이름 — 비우면 가운데를 줄인 이름"))
            self.btn_short.clicked.connect(lambda: self._on_short(self.list.currentItem()))
            btns.addWidget(self.btn_short)
        b_rm = QPushButton(tr("삭제"))
        b_rm.clicked.connect(self._remove)
        btns.addWidget(b_rm)
        btns.addStretch(1)
        h.addLayout(btns)

    def _text(self, f: dict) -> str:
        if self.kind in KIND_ORDER:
            t = KIND_PREFIX[self.kind] + f.get("name", "?")
            if self.kind in ("folder", "file"):
                t += "   [" + short_label(f) + "]"
            return t
        return other_label(self.kind, f)

    def _tip(self, f: dict) -> str:
        if self.kind == "search":
            return tr("검색: '{get}' (폴더 {get2})").format(get=f.get('query', ''), get2=f.get('folder', ''))
        if self.kind == "file":
            return f.get("file", "") or f.get("folder", "")
        if self.kind == "folder":
            return f.get("folder", "")
        return f.get("name", "")

    def _append(self, f: dict):
        it = QListWidgetItem(self._text(f))
        it.setData(Qt.ItemDataRole.UserRole, f)
        it.setToolTip(self._tip(f))
        self.list.addItem(it)

    def _update(self, item, f):
        item.setData(Qt.ItemDataRole.UserRole, f)
        item.setText(self._text(f))
        item.setToolTip(self._tip(f))

    def _move(self, delta: int):
        row = self.list.currentRow()
        new_row = row + delta
        if row < 0 or not (0 <= new_row < self.list.count()):
            return
        item = self.list.takeItem(row)
        self.list.insertItem(new_row, item)
        self.list.setCurrentRow(new_row)

    def _remove(self):
        row = self.list.currentRow()
        if row < 0:
            return
        ret = QMessageBox.question(
            self, tr("삭제"),
            tr("'{text}' 을(를) 삭제할까요?").format(text=self.list.item(row).text()),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.list.takeItem(row)

    def _on_rename(self, item):
        if item is None:
            return
        f = item.data(Qt.ItemDataRole.UserRole) or {}
        new_name, ok = QInputDialog.getText(self, tr("이름 변경"), tr("새 이름:"), text=f.get("name", ""))
        if ok and new_name.strip():
            f["name"] = new_name.strip()
            self._update(item, f)

    def _on_short(self, item):
        if item is None:
            return
        f = item.data(Qt.ItemDataRole.UserRole) or {}
        new, ok = QInputDialog.getText(self, tr("단추 이름"),
                                       tr("즐겨찾기 탭 단추에 보일 이름 (비우면 자동):"),
                                       text=str(f.get("short") or ""))
        if ok:
            if new.strip():
                f["short"] = new.strip()
            else:
                f.pop("short", None)
            self._update(item, f)

    def result(self) -> list:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) or {} for i in range(self.list.count())]


class FavoritesManagerDialog(QDialog):
    """`항목 관리` — 종류마다 탭(디자인 SOT §2.9.5). 기능이 꺼진 종류는 탭을 만들지 않는다(넘기지 않으면 없다).

    lists: kind → 항목 리스트(보일 종류만, 차례 = 탭 차례). [확인] 하면 `result(kind)` 로 읽는다.
    """

    def __init__(self, lists: dict, start_kind: str = "folder", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("항목 관리"))
        self.resize(600, 460)
        v = QVBoxLayout(self)
        info = QLabel(tr("드래그하거나 ↑/↓ 버튼으로 순서 변경. 더블클릭으로 이름 수정. "
                         "폴더·파일은 앞 3개가 즐겨찾기 탭에 단추로 보입니다."))
        info.setStyleSheet("color:#666;")
        info.setWordWrap(True)
        v.addWidget(info)
        self.tabs = QTabWidget()
        self._pages = {}
        for kind, favs in lists.items():
            page = _FavList(kind, list(favs or []), self)
            self._pages[kind] = page
            self.tabs.addTab(page, kind_title(kind))
        if start_kind in self._pages:
            self.tabs.setCurrentWidget(self._pages[start_kind])
        v.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def kinds(self) -> list:
        return list(self._pages)

    def page(self, kind: str):
        return self._pages.get(kind)

    def result(self, kind: str) -> list:
        return self._pages[kind].result()


class AddFavoriteDialog(QDialog):
    """즐겨찾기 추가 — 이름 미리 채워줌, 사용자가 수정 가능."""

    def __init__(self, suggested_name: str, kind: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("즐겨찾기 등록"))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        label = {"folder": tr("📁 폴더"), "file": tr("📄 파일"), "search": tr("🔍 검색")}.get(kind, "📁 폴더")
        layout.addWidget(QLabel(tr('종류: {label}').format(label=label)))
        layout.addWidget(QLabel(tr("이름 (수정 가능):")))
        self.edit = QLineEdit(suggested_name)
        self.edit.selectAll()
        layout.addWidget(self.edit)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def name(self) -> str:
        return self.edit.text().strip()
