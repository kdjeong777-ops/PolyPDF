"""무료 이미지(Openverse) 검색·선택 다이얼로그 — 단어 그림 등록 (P10).

검색·썸네일 다운로드는 백그라운드 스레드(UI 멈춤 방지). 선택 후 원본은 호출자가 저장.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QDialogButtonBox,
)


class _SearchWorker(QThread):
    done = pyqtSignal(list)        # [{result, thumb(bytes|None)}]
    failed = pyqtSignal(str)

    def __init__(self, query: str, limit: int = 12):
        super().__init__()
        self._q = query
        self._limit = limit

    def run(self):
        try:
            from viewer.study.image_fetch import search_openverse, download_bytes
            results = search_openverse(self._q, limit=self._limit)
            out = []
            for r in results:
                tb = None
                try:
                    tb = download_bytes(r.get("thumbnail") or r.get("url"), timeout=8.0)
                except Exception:
                    tb = None
                out.append({"result": r, "thumb": tb})
            self.done.emit(out)
        except Exception as e:
            self.failed.emit(str(e))


class ImageSearchDialog(QDialog):
    def __init__(self, query: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("무료 이미지 검색 (Openverse · CC)")
        self.resize(620, 480)
        self._chosen: Optional[dict] = None
        self._worker = None

        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.ed = QLineEdit(query)
        self.ed.returnPressed.connect(self._search)
        self.btn = QPushButton("검색")
        self.btn.clicked.connect(self._search)
        top.addWidget(self.ed, 1); top.addWidget(self.btn)
        v.addLayout(top)

        self.info = QLabel("검색어를 입력하고 [검색]. 이미지는 CC 라이선스이며 출처가 함께 저장됩니다.")
        self.info.setWordWrap(True); self.info.setStyleSheet("color:#888;")
        v.addWidget(self.info)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(140, 140))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSpacing(8)
        self.list.itemDoubleClicked.connect(lambda _=None: self._accept_sel())
        self.list.currentItemChanged.connect(self._on_sel)
        v.addWidget(self.list, 1)

        self.bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.bb.accepted.connect(self._accept_sel)
        self.bb.rejected.connect(self.reject)
        self.bb.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        v.addWidget(self.bb)
        if query.strip():
            self._search()

    def _search(self):
        q = self.ed.text().strip()
        if not q or (self._worker and self._worker.isRunning()):
            return
        self.list.clear()
        self.info.setText("검색 중…")
        self.btn.setEnabled(False)
        self._worker = _SearchWorker(q)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, items: list):
        self.btn.setEnabled(True)
        if not items:
            self.info.setText("결과가 없습니다. 다른 검색어를 시도하세요.")
            return
        self.info.setText(f"{len(items)}개 — 이미지를 골라 [확인]. (출처: Openverse·CC)")
        for d in items:
            r = d["result"]
            it = QListWidgetItem(r.get("license", "") or "CC")
            it.setData(Qt.ItemDataRole.UserRole, r)
            it.setToolTip(r.get("attribution", ""))
            if d.get("thumb"):
                pm = QPixmap()
                if pm.loadFromData(d["thumb"]):
                    it.setIcon(QIcon(pm))
            self.list.addItem(it)

    def _on_failed(self, msg: str):
        self.btn.setEnabled(True)
        self.info.setText(f"검색 실패(네트워크 확인): {msg}")

    def _on_sel(self, cur, _prev):
        self.bb.button(QDialogButtonBox.StandardButton.Ok).setEnabled(cur is not None)

    def _accept_sel(self):
        it = self.list.currentItem()
        if it is None:
            return
        self._chosen = it.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def chosen(self) -> Optional[dict]:
        return self._chosen
