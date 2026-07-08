"""우측 상단 - 검색바 + 결과 리스트.

v1.4.0:
 - P3: 책갈피 순 정렬을 bookmarks.json 트리 출현 순서로 (set_bookmark_order)
 - F8: 엑셀 내보내기 버튼 + exportRequested 시그널
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from viewer.resources_path import resource_path
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QComboBox,
)


class SearchBar(QWidget):
    searchRequested = pyqtSignal(str)
    prevMatch = pyqtSignal()
    nextMatch = pyqtSignal()
    screenshotRequested = pyqtSignal()
    screenshotPdfSaveRequested = pyqtSignal()
    queryCleared = pyqtSignal()
    favoriteRequested = pyqtSignal()      # v1.6.1 F4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText("검색...  (Enter: 검색, Ctrl+F: 포커스)")
        self.edit.returnPressed.connect(self._emit_search)
        layout.addWidget(self.edit, 1)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedWidth(28)
        self.btn_prev.setToolTip("이전 매치 (Shift+F3)")
        self.btn_prev.clicked.connect(self.prevMatch.emit)
        layout.addWidget(self.btn_prev)

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedWidth(28)
        self.btn_next.setToolTip("다음 매치 (F3)")
        self.btn_next.clicked.connect(self.nextMatch.emit)
        layout.addWidget(self.btn_next)

        self.match_label = QLabel("0 / 0")
        self.match_label.setStyleSheet("color: #666; min-width: 50px;")
        layout.addWidget(self.match_label)

        # v1.6.1 F4: 즐겨찾기 추가 (검색바 오른쪽 끝)
        self.btn_fav = QPushButton("⭐")
        self.btn_fav.setFixedWidth(28)
        self.btn_fav.setToolTip("현재 검색어를 즐겨찾기에 추가")
        self.btn_fav.clicked.connect(self.favoriteRequested.emit)
        layout.addWidget(self.btn_fav)

        # v1.5.0 M7: 검색바의 📷/💾 버튼은 스크린샷 패널로 이동.
        # 시그널 (screenshotRequested, screenshotPdfSaveRequested) 은 호환 보존.

    def _emit_search(self):
        text = self.edit.text().strip()
        if not text:
            self.queryCleared.emit()
        else:
            self.searchRequested.emit(text)

    def set_match_position(self, current: int, total: int):
        self.match_label.setText(f"{current} / {total}")

    def focus_search(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def set_context_label(self, label: str = ""):
        """검색 대상 표시 — 우측창(건설기준/법령/특허) 활성 시 '○○ 내용 검색', 없으면 PDF 기본."""
        if label:
            self.edit.setPlaceholderText(f"{label} 내용 검색...  (Ctrl+F)")
        else:
            self.edit.setPlaceholderText("검색...  (Enter: 검색, Ctrl+F: 포커스)")

    def current_query(self) -> str:
        return self.edit.text().strip()


class SearchResults(QWidget):
    """검색 결과 리스트."""
    resultActivated = pyqtSignal(str, int, str)
    exportRequested = pyqtSignal()         # v1.4.0 F8
    screenshotForResultRequested = pyqtSignal()   # v1.5.0 M6

    DATA_FILE = Qt.ItemDataRole.UserRole + 0
    DATA_PAGE = Qt.ItemDataRole.UserRole + 1
    DATA_QUERY = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: list = []
        self._query = ""
        self._order_map: dict = {}             # v1.4.0 P3
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 4, 0)
        head.addWidget(QLabel("검색 결과"))
        head.addStretch(1)
        head.addWidget(QLabel("정렬"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["이름 순", "횟수 순"])
        self.sort_combo.currentIndexChanged.connect(lambda _: self._render_results())
        head.addWidget(self.sort_combo)

        # v1.6.1 S3: excel.png + "저장"
        self.btn_excel = QPushButton(" 저장")
        _ico = resource_path("excel.png")
        if _ico:
            self.btn_excel.setIcon(QIcon(_ico))
        else:
            self.btn_excel.setText("📊 저장")
        self.btn_excel.setToolTip("현재 결과를 엑셀(.xlsx)로 저장")
        self.btn_excel.clicked.connect(self.exportRequested.emit)
        head.addWidget(self.btn_excel)

        # v1.6.1 S4: screenshot.png + "캡쳐"
        self.btn_shot_result = QPushButton(" 전체 캡쳐")
        _ico = resource_path("screenshot.png")
        if _ico:
            self.btn_shot_result.setIcon(QIcon(_ico))
        else:
            self.btn_shot_result.setText("📷 전체 캡쳐")
        self.btn_shot_result.setToolTip("검색결과의 모든 매치 페이지를 일괄 스크린샷 (v1.6.1 S5)")
        self.btn_shot_result.clicked.connect(self.screenshotForResultRequested.emit)
        head.addWidget(self.btn_shot_result)

        layout.addLayout(head)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["내용", "페이지", "횟수"])
        self.tree.setColumnWidth(0, 240)
        self.tree.setColumnWidth(1, 50)
        self.tree.setColumnWidth(2, 40)
        self.tree.itemActivated.connect(self._on_activated)
        self.tree.itemClicked.connect(self._on_activated)
        layout.addWidget(self.tree, 1)

    def set_bookmark_order(self, order_map: dict):
        """v1.4.0 P3: 파일 절대경로 -> 출현 순번."""
        self._order_map = dict(order_map or {})
        self._render_results()

    def set_results(self, query: str, results: list):
        self._query = query
        self._results = results
        self._render_results()

    def current_query(self) -> str:
        """v1.6.6: 현재 결과를 생성한 검색어 (일괄 캡쳐 시 형광펜 대상)."""
        return self._query or ""

    def get_displayed_results(self) -> list:
        """엑셀 저장 등 외부에서 사용할 현재 표시 순서의 결과."""
        if not self._results:
            return []
        from collections import defaultdict
        groups: dict = defaultdict(list)
        for r in self._results:
            groups[r.file_path].append(r)
        ordered = self._sorted_groups(groups)
        flat: list = []
        for _, page_results in ordered:
            for r in sorted(page_results, key=lambda x: x.page_index):
                flat.append(r)
        return flat

    def _sorted_groups(self, groups: dict):
        sort_key = self.sort_combo.currentText()
        if sort_key == "횟수 순":
            return sorted(groups.items(),
                          key=lambda kv: -sum(r.match_count for r in kv[1]))
        # 책갈피 순: order_map 사용. 없으면 가나다 순으로 폴백.
        if self._order_map:
            return sorted(
                groups.items(),
                key=lambda kv: (self._order_map.get(kv[0], 10**9), kv[0]),
            )
        return sorted(groups.items(), key=lambda kv: kv[0])

    def _render_results(self):
        self.tree.clear()
        if not self._results:
            return
        from collections import defaultdict
        groups = defaultdict(list)
        for r in self._results:
            groups[r.file_path].append(r)

        ordered = self._sorted_groups(groups)

        for file_path, page_results in ordered:
            total = sum(r.match_count for r in page_results)
            top = QTreeWidgetItem([Path(file_path).stem, "", f"{total}"])  # v1.6.0 S7: .pdf 제거
            top.setData(0, self.DATA_FILE, file_path)
            top.setData(0, self.DATA_PAGE, page_results[0].page_index)
            top.setData(0, self.DATA_QUERY, self._query)
            top.setToolTip(0, file_path)
            self.tree.addTopLevelItem(top)

            for r in sorted(page_results, key=lambda x: x.page_index):
                snip = r.snippet.replace("<", "[").replace(">", "]")
                child = QTreeWidgetItem([snip, str(r.page_index + 1), str(r.match_count)])
                child.setData(0, self.DATA_FILE, file_path)
                child.setData(0, self.DATA_PAGE, r.page_index)
                child.setData(0, self.DATA_QUERY, self._query)
                top.addChild(child)
            top.setExpanded(True)

    def _on_activated(self, item: QTreeWidgetItem, _column: int = 0):
        file_path = item.data(0, self.DATA_FILE)
        if not file_path:
            return
        page = item.data(0, self.DATA_PAGE) or 0
        query = item.data(0, self.DATA_QUERY) or ""
        self.resultActivated.emit(file_path, int(page), query)
