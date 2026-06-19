"""PDF 병합 다이얼로그 — 좌(전체 파일)/우(병합 대상) 2리스트 (260606-15).

- 좌: 책갈피 트리의 전체 파일(확장자 제외). 다중 선택 → [→]로 우측 등록.
- 우: 병합 대상(드래그로 순서 변경). 삭제 버튼, 정렬(등록순/파일명순),
      외부 PDF 드래그앤드롭 추가, '스크린샷 추가'(스크린샷들을 '사용자 스크린샷' 1개로).
- 체크 '병합 후 책갈피와 단어장 자동 생성'(기본 체크).
- result_items(): [{type:'pdf'|'shots', path/paths, name}] (현재 순서). auto_build(): bool.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QDialogButtonBox, QAbstractItemView, QCheckBox,
    QComboBox,
)

SHOTS_NAME = "사용자 스크린샷"


def _has_pdf_urls(mime) -> bool:
    return mime.hasUrls() and any(
        u.toLocalFile().lower().endswith(".pdf") for u in mime.urls())


class _DropList(QListWidget):
    """외부 파일(URL) 드래그는 받지 않고 부모(다이얼로그)로 넘김 → 어디에 놓아도 우측 등록.
    내부 이동(InternalMove) 드래그는 기존대로 처리."""

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.ignore()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.ignore()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            e.ignore()
        else:
            super().dropEvent(e)


class MergeFilesDialog(QDialog):
    _DATA = Qt.ItemDataRole.UserRole

    def __init__(self, all_files: list, preselected: list = None,
                 screenshot_paths: list = None, parent=None, preset_api=None):
        super().__init__(parent)
        self.setWindowTitle("PDF 병합")
        self.setMinimumSize(720, 460)
        self.setAcceptDrops(True)
        self._screenshot_paths = list(screenshot_paths or [])
        self._order = 0
        self._preset_api = preset_api      # 260611-36: 사용자 스타일 저장/불러오기

        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "왼쪽에서 파일을 골라 <b>→</b> 로 오른쪽에 등록하세요. 오른쪽 목록의 "
            "<b>위에서부터</b> 순서대로 병합됩니다. 외부 PDF는 창에 <b>끌어다 놓기</b>로 추가."))

        body = QHBoxLayout()
        # 좌측: 전체 파일
        lcol = QVBoxLayout()
        lcol.addWidget(QLabel("책갈피창 전체 파일"))
        self.left = _DropList()
        self.left.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for p in (all_files or []):
            it = QListWidgetItem(Path(p).stem)
            it.setData(self._DATA, str(p))
            it.setToolTip(str(p))
            self.left.addItem(it)
        lcol.addWidget(self.left, 1)
        body.addLayout(lcol, 1)

        # 가운데: → 버튼
        mid = QVBoxLayout()
        mid.addStretch(1)
        btn_add = QPushButton("→")
        btn_add.setToolTip("선택 파일을 오른쪽(병합 대상)으로")
        btn_add.setFixedWidth(44)
        btn_add.clicked.connect(self._move_selected)
        mid.addWidget(btn_add)
        mid.addStretch(1)
        body.addLayout(mid)

        # 우측: 병합 대상
        rcol = QVBoxLayout()
        top_r = QHBoxLayout()
        top_r.addWidget(QLabel("병합 대상 (위→아래 순서)"))
        top_r.addStretch(1)
        top_r.addWidget(QLabel("정렬:"))
        self.cmb_sort = QComboBox()
        self.cmb_sort.addItem("등록순", "order")
        self.cmb_sort.addItem("파일명순", "name")
        self.cmb_sort.currentIndexChanged.connect(self._apply_sort)
        top_r.addWidget(self.cmb_sort)
        rcol.addLayout(top_r)

        # 우측 리스트 + 그 오른쪽에 ▲▼(이동)·삭제 버튼 세로열
        rlist_row = QHBoxLayout()
        self.right = _DropList()
        self.right.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.right.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.right.setDefaultDropAction(Qt.DropAction.MoveAction)
        rlist_row.addWidget(self.right, 1)
        rbtncol = QVBoxLayout()
        rbtncol.addStretch(1)
        btn_up = QPushButton("▲"); btn_up.setFixedWidth(40)
        btn_dn = QPushButton("▼"); btn_dn.setFixedWidth(40)
        btn_up.setToolTip("선택 항목 위로 이동")
        btn_dn.setToolTip("선택 항목 아래로 이동")
        btn_up.clicked.connect(lambda: self._move_right(-1))
        btn_dn.clicked.connect(lambda: self._move_right(+1))
        rbtncol.addWidget(btn_up)
        rbtncol.addWidget(btn_dn)
        rbtncol.addSpacing(18)
        btn_del = QPushButton("삭제"); btn_del.setFixedWidth(40)
        btn_del.setToolTip("선택 항목을 병합 대상에서 제거")
        btn_del.clicked.connect(self._delete_right)
        rbtncol.addWidget(btn_del)
        rbtncol.addStretch(1)
        rlist_row.addLayout(rbtncol)
        rcol.addLayout(rlist_row, 1)

        rbtns = QHBoxLayout()
        btn_shots = QPushButton("스크린샷 리스트 추가")
        btn_shots.setToolTip("스크린샷 창의 내용을 '사용자 스크린샷' 1개로 추가")
        btn_shots.setEnabled(bool(self._screenshot_paths))
        btn_shots.clicked.connect(self._add_screenshots)
        rbtns.addWidget(btn_shots)
        rbtns.addStretch(1)
        rcol.addLayout(rbtns)
        body.addLayout(rcol, 1)

        v.addLayout(body, 1)

        # 미리 선택된 파일
        for p in (preselected or []):
            self._add_right_pdf(p)

        self.chk_auto = QCheckBox("병합 후 책갈피와 단어장 자동 생성")
        self.chk_auto.setChecked(True)
        v.addWidget(self.chk_auto)

        # 260611-29: 2단 축소 배치(쪽번호·목차·표지)
        self._twoup_settings = None
        trow = QHBoxLayout()
        self.chk_twoup = QCheckBox("다단 생성 (쪽번호·목차·표지)")
        self.chk_twoup.toggled.connect(self._on_twoup_toggled)
        self.btn_twoup = QPushButton("배치 설정…")
        self.btn_twoup.setEnabled(False)
        self.btn_twoup.clicked.connect(self._open_twoup_settings)
        trow.addWidget(self.chk_twoup); trow.addWidget(self.btn_twoup); trow.addStretch(1)
        v.addLayout(trow)

        bb = QDialogButtonBox(self)
        self.btn_ok = bb.addButton("병합", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton("취소", QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        # 260606-21: 드롭 안내 오버레이(드래그 중 표시) — 창 어디에 놓아도 우측 등록
        self._drop_overlay = QLabel(
            "📄  여기에 PDF 파일을 끌어다 놓으세요\n(오른쪽 병합 목록에 추가됩니다)", self)
        self._drop_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_overlay.setStyleSheet(
            "QLabel{background:rgba(42,125,225,0.16);"
            "border:3px dashed #2a7de1;border-radius:12px;"
            "color:#1565c0;font-size:18px;font-weight:bold;}")
        self._drop_overlay.hide()

    # ── 드롭 안내 오버레이 ─────────────────────────────────────
    def _show_drop_overlay(self, on: bool):
        if on:
            self._drop_overlay.setGeometry(self.rect().adjusted(8, 8, -8, -8))
            self._drop_overlay.raise_()
            self._drop_overlay.show()
        else:
            self._drop_overlay.hide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._drop_overlay.isVisible():
            self._drop_overlay.setGeometry(self.rect().adjusted(8, 8, -8, -8))

    # ── 항목 추가 ──────────────────────────────────────────────
    def _next_order(self) -> int:
        self._order += 1
        return self._order

    def _right_has_pdf(self, path: str) -> bool:
        rp = str(Path(path).resolve()).lower()
        for i in range(self.right.count()):
            d = self.right.item(i).data(self._DATA) or {}
            if d.get("type") == "pdf":
                try:
                    if str(Path(d["path"]).resolve()).lower() == rp:
                        return True
                except Exception:
                    pass
        return False

    def _add_right_pdf(self, path: str):
        if not path or not str(path).lower().endswith(".pdf"):
            return
        if self._right_has_pdf(path):
            return
        name = Path(path).stem
        it = QListWidgetItem(name)
        it.setData(self._DATA, {"type": "pdf", "path": str(path), "name": name,
                                "order": self._next_order()})
        it.setToolTip(str(path))
        self.right.addItem(it)

    def _move_selected(self):
        for it in self.left.selectedItems():
            self._add_right_pdf(it.data(self._DATA))

    def _add_screenshots(self):
        if not self._screenshot_paths:
            return
        it = QListWidgetItem(f"🖼 {SHOTS_NAME} ({len(self._screenshot_paths)}장)")
        it.setData(self._DATA, {"type": "shots", "paths": list(self._screenshot_paths),
                                "name": SHOTS_NAME, "order": self._next_order()})
        self.right.addItem(it)

    def _move_right(self, direction: int):
        """우측 다중 선택 항목을 한 칸 위/아래로 이동(블록 이동, 선택 유지)."""
        rows = sorted(self.right.row(it) for it in self.right.selectedItems())
        if not rows:
            return
        if direction < 0:
            if rows[0] <= 0:
                return
            for r in rows:
                it = self.right.takeItem(r)
                self.right.insertItem(r - 1, it)
                it.setSelected(True)
        else:
            if rows[-1] >= self.right.count() - 1:
                return
            for r in reversed(rows):
                it = self.right.takeItem(r)
                self.right.insertItem(r + 1, it)
                it.setSelected(True)

    def _delete_right(self):
        for it in self.right.selectedItems():
            self.right.takeItem(self.right.row(it))

    def _apply_sort(self):
        by = self.cmb_sort.currentData()
        rows = [self.right.item(i).data(self._DATA) for i in range(self.right.count())]
        if by == "name":
            rows.sort(key=lambda d: (d.get("name") or "").lower())
        else:
            rows.sort(key=lambda d: d.get("order", 0))
        self.right.clear()
        for d in rows:
            label = (f"🖼 {d['name']} ({len(d['paths'])}장)"
                     if d.get("type") == "shots" else d["name"])
            it = QListWidgetItem(label)
            it.setData(self._DATA, d)
            if d.get("type") == "pdf":
                it.setToolTip(d.get("path", ""))
            self.right.addItem(it)

    # ── 드래그앤드롭(외부 PDF) — 창 어디에 놓아도 우측 등록 ────────
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._show_drop_overlay(_has_pdf_urls(e.mimeData()))

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._show_drop_overlay(False)

    def dropEvent(self, e):
        self._show_drop_overlay(False)
        n = 0
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p and p.lower().endswith(".pdf"):
                self._add_right_pdf(p)
                n += 1
        e.acceptProposedAction()

    # ── 결과 ───────────────────────────────────────────────────
    def _on_accept(self):
        from PyQt6.QtWidgets import QMessageBox
        if self.right.count() < 1:
            QMessageBox.information(self, "병합", "병합할 항목을 오른쪽에 추가하세요.")
            return
        self.accept()

    def result_items(self) -> list:
        return [self.right.item(i).data(self._DATA) for i in range(self.right.count())]

    def auto_build(self) -> bool:
        return self.chk_auto.isChecked()

    # 260611-29: 2단 축소 배치
    def _on_twoup_toggled(self, on):
        self.btn_twoup.setEnabled(on)
        if on and self._twoup_settings is None:
            self._open_twoup_settings()

    def _open_twoup_settings(self):
        from viewer.widgets.twoup_dialog import TwoUpSettingsDialog
        dlg = TwoUpSettingsDialog(self._twoup_settings, self,
                                  preset_api=self._preset_api, sample=self.result_items())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._twoup_settings = dlg.get_settings()

    def twoup_enabled(self) -> bool:
        return self.chk_twoup.isChecked()

    def twoup_settings(self) -> dict:
        from viewer.twoup import merge_twoup_settings
        s = merge_twoup_settings(self._twoup_settings)
        s["enabled"] = True
        return s
