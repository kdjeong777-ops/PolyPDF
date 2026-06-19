"""260609-3/11 (C): 페이지 하이퍼링크 등록/관리 다이얼로그.

레이아웃(위→아래):
- 입력: 명칭 / 작업 파일(드래그앤드롭·파일 선택, '대기' 표시) / URL
- ⬇ 등록 버튼(선택·입력 후 눌러야 리스트에 추가)
- 등록된 하이퍼링크 표(좌:명칭, 우:파일명·URL) — 선택해 위/아래 이동·이름변경·삭제
- 닫기
보안 검증은 store(HyperlinkStore)가 담당. 앱이 닫은 뒤 save()+오버레이 갱신.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox, QGroupBox,
    QHeaderView, QAbstractItemView,
)


class HyperlinkDialog(QDialog):
    def __init__(self, store, file_path, page0, base_folder, parent=None):
        super().__init__(parent)
        self._store = store
        self._file = file_path
        self._page0 = int(page0)
        self._base = Path(base_folder) if base_folder else None
        self._pending_file = None          # ⬇ 등록 대기 중인 파일 경로
        self.setWindowTitle(f"하이퍼링크 — {Path(str(file_path)).name} p.{self._page0 + 1}")
        self.setAcceptDrops(True)
        self.resize(500, 470)
        self._build()
        self._refresh_list()
        # 260609-15(C3): 드래그 시 전체 다이얼로그가 드롭 범위임을 표시하는 오버레이
        self._drop_overlay = QLabel("⬇  파일을 여기에 놓으세요  ⬇", self)
        self._drop_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_overlay.setStyleSheet(
            "background:rgba(21,101,192,0.18);color:#1565c0;font-size:20px;"
            "font-weight:bold;border:3px dashed #1565c0;border-radius:12px;")
        self._drop_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._drop_overlay.hide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        ov = getattr(self, "_drop_overlay", None)
        if ov is not None:
            ov.setGeometry(6, 6, self.width() - 12, self.height() - 12)

    def _show_drop_overlay(self, on):
        ov = getattr(self, "_drop_overlay", None)
        if ov is None:
            return
        if on:
            ov.setGeometry(6, 6, self.width() - 12, self.height() - 12)
            ov.show(); ov.raise_()
        else:
            ov.hide()

    def _build(self):
        v = QVBoxLayout(self)

        # 명칭
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("명칭"))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("버튼에 표시할 명칭(비우면 파일명/주소)")
        name_row.addWidget(self.ed_name, 1)
        v.addLayout(name_row)

        # 파일 등록(대기)
        grp_f = QGroupBox("파일 (책갈피 폴더 안의 문서·이미지·동영상 등)")
        fl = QVBoxLayout(grp_f)
        self.drop = QLabel("⬇  여기로 파일을 끌어다 놓으세요  ⬇")
        self.drop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop.setStyleSheet(
            "QLabel{border:2px dashed #888;border-radius:8px;padding:12px;color:#777;}")
        fl.addWidget(self.drop)
        fr = QHBoxLayout()
        self.lbl_pending = QLabel("선택된 파일: (없음)")
        self.lbl_pending.setStyleSheet("color:#444;")
        fr.addWidget(self.lbl_pending, 1)
        btn_pick = QPushButton("파일 선택…")
        btn_pick.clicked.connect(self._on_pick_file)
        fr.addWidget(btn_pick)
        fl.addLayout(fr)
        v.addWidget(grp_f)

        # URL
        grp_u = QGroupBox("외부 링크(URL) — https + 허용 도메인(youtube 등)")
        ul = QHBoxLayout(grp_u)
        self.ed_url = QLineEdit()
        self.ed_url.setPlaceholderText("https://youtu.be/…")
        ul.addWidget(self.ed_url, 1)
        v.addWidget(grp_u)

        # ⬇ 등록 버튼
        reg_row = QHBoxLayout()
        reg_row.addStretch(1)
        self.btn_register = QPushButton("⬇  등록")
        self.btn_register.setStyleSheet(
            "QPushButton{background:#1565c0;color:#fff;font-weight:bold;"
            "padding:6px 28px;border:none;border-radius:6px;}"
            "QPushButton:hover{background:#1976d2;}")
        self.btn_register.clicked.connect(self._on_register)
        reg_row.addWidget(self.btn_register)
        reg_row.addStretch(1)
        v.addLayout(reg_row)

        # 등록된 표(맨 아래, 닫기 바로 위)
        v.addWidget(QLabel("등록된 하이퍼링크 (명칭 더블클릭 = 이름변경):"))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["명칭", "파일명 · URL"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.table, 1)

        # 리스트 조작 — 260609-15(C2): 삭제를 이름변경 바로 오른쪽(닫기와 멀리)
        ops = QHBoxLayout()
        b_up = QPushButton("▲ 위"); b_up.clicked.connect(lambda: self._move(-1))
        b_dn = QPushButton("▼ 아래"); b_dn.clicked.connect(lambda: self._move(+1))
        b_rn = QPushButton("이름변경"); b_rn.clicked.connect(self._rename_selected)
        b_del = QPushButton("삭제"); b_del.clicked.connect(self._delete_selected)
        ops.addWidget(b_up); ops.addWidget(b_dn); ops.addWidget(b_rn)
        ops.addSpacing(16); ops.addWidget(b_del)
        ops.addStretch(1)
        v.addLayout(ops)

        # 닫기
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        v.addLayout(close_row)

    # --- 표 ---
    def _refresh_list(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for ln in self._store.links_for(self._file, self._page0):
            r = self.table.rowCount()
            self.table.insertRow(r)
            it_name = QTableWidgetItem(ln.get("name", ""))
            it_name.setFlags(it_name.flags() | Qt.ItemFlag.ItemIsEditable)
            tag = "📄 " if ln.get("kind") == "file" else "🔗 "
            it_tgt = QTableWidgetItem(tag + str(ln.get("target", "")))
            it_tgt.setFlags(it_tgt.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 0, it_name)
            self.table.setItem(r, 1, it_tgt)
        self.table.blockSignals(False)

    def _sel_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _on_item_changed(self, item):
        if item.column() != 0:
            return
        row = item.row()
        if self._store.rename_link(self._file, self._page0, row, item.text()):
            pass  # 저장은 앱이 닫을 때

    def _move(self, delta):
        row = self._sel_row()
        if row < 0:
            return
        nj = self._store.move_link(self._file, self._page0, row, delta)
        if nj >= 0:
            self._refresh_list()
            self.table.selectRow(nj)

    def _rename_selected(self):
        row = self._sel_row()
        if row < 0:
            return
        self.table.editItem(self.table.item(row, 0))

    def _delete_selected(self):
        row = self._sel_row()
        if row < 0:
            return
        if self._store.remove_link(self._file, self._page0, row):
            self._refresh_list()

    # --- 등록 ---
    def _set_pending(self, path):
        self._pending_file = path
        self.lbl_pending.setText(f"선택된 파일: {Path(path).name}" if path
                                 else "선택된 파일: (없음)")

    def _on_pick_file(self):
        start = str(self._base) if self._base else ""
        path, _ = QFileDialog.getOpenFileName(self, "작업 파일 선택", start)
        if path:
            self._set_pending(path)

    def _on_register(self):
        """⬇ 등록 — URL 우선, 없으면 대기 파일."""
        url = self.ed_url.text().strip()
        if url:
            ok, msg = self._store.add_url_link(
                self._file, self._page0, self.ed_name.text(), url)
            if not ok:
                QMessageBox.warning(self, "등록 불가", msg); return
            self.ed_url.clear()
        elif self._pending_file:
            ok, msg = self._store.add_file_link(
                self._file, self._page0, self.ed_name.text(), self._pending_file)
            if not ok:
                QMessageBox.warning(self, "등록 불가", msg); return
            self._set_pending(None)
        else:
            QMessageBox.information(
                self, "안내", "URL을 입력하거나 파일을 선택한 뒤 등록하세요.")
            return
        self.ed_name.clear()
        self._refresh_list()

    # --- 드래그앤드롭(파일 → 대기), 전체 다이얼로그가 드롭 범위 ---
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._show_drop_overlay(True)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._show_drop_overlay(False)

    def dropEvent(self, e):
        self._show_drop_overlay(False)
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self._set_pending(url.toLocalFile())
                e.acceptProposedAction()
                break
