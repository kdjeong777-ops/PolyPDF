# -*- coding: utf-8 -*-
"""책갈피 검토 표 (260904-1, 마스터 SOT §4.4 · 디자인 §2.7).

목차 쪽에서 읽은(또는 폰트/OCR 로 추출한) 항목을 **표로 보여 주고, 실제 쪽과 대조해
수정·삭제·추가한 뒤** 저장한다. 비모달이 아니라 모달(저장/취소로 끝) — 결과가 곧 파일에
써지므로 확정 단계가 분명해야 한다.

열: 레벨 | 제목 | 목차 쪽 | 실제 쪽 | 확인
  - 실제 쪽 = 목차 쪽 + 오프셋. 셀을 직접 고치면 그 행은 '수동'(오프셋 재적용에도 유지).
  - 확인 = [제목 대조] 결과(그 쪽 텍스트에 제목 앞부분이 있으면 ✓). 저장에는 영향 없음.
오른쪽 미리보기: 현재 행의 실제 쪽을 렌더해 보여 준다(스캔본은 텍스트가 깨져 있어 눈으로
대조하는 것이 가장 확실하다).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QImage, QPixmap
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QTableWidget, QTableWidgetItem, QSpinBox, QComboBox,
                             QAbstractItemView, QHeaderView, QSplitter, QWidget,
                             QDialogButtonBox, QMessageBox, QFormLayout)

from viewer import toc_parse

COL_LEVEL, COL_TITLE, COL_TOC, COL_PAGE, COL_OK = range(5)
_OK_BG = QColor("#e8f5e9")
_NG_BG = QColor("#fdecea")
_MANUAL_BG = QColor("#fff8e1")


class TocReviewDialog(QDialog):
    previewPageRequested = pyqtSignal(int)     # 0-based — 앱이 본문 뷰어를 그 쪽으로(선택)

    def __init__(self, pdf_path, rows: list[dict], *, offset: int = 0,
                 candidates: list[tuple[int, float]] | None = None,
                 method: str = "toc", toc_pages: list[int] | None = None, parent=None):
        super().__init__(parent)
        self.pdf_path = Path(pdf_path)
        self.method = method
        self.toc_pages = list(toc_pages or [])
        self._rows = [dict(r) for r in rows]
        self._page_count = self._count_pages()
        self._offset = int(offset)
        self.setWindowTitle(f"책갈피 검토 — {self.pdf_path.name}")
        self.resize(1080, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10); root.setSpacing(6)
        head = QLabel(
            f"<b>{'목차 쪽 ' + ', '.join(map(str, self.toc_pages)) + ' 에서 읽은' if self.toc_pages else '추출한'} "
            f"항목 {len(self._rows)}개</b> — 실제 쪽과 대조해 고친 뒤 [저장]하면 PDF 책갈피로 씁니다. "
            "행을 고르면 오른쪽에 그 쪽이 보입니다. 실제 쪽 셀을 직접 고치면 그 행은 오프셋을 다시 적용해도 유지됩니다.")
        head.setWordWrap(True)
        root.addWidget(head)

        # ── 오프셋 (목차 방식일 때만) ─────────────────────────────────
        self.grp_offset = QWidget()
        fo = QHBoxLayout(self.grp_offset); fo.setContentsMargins(0, 0, 0, 0)
        fo.addWidget(QLabel("오프셋(실제 쪽 − 목차 쪽):"))
        self.spin_offset = QSpinBox(); self.spin_offset.setRange(-200, 2000); self.spin_offset.setValue(self._offset)
        fo.addWidget(self.spin_offset)
        self.cmb_cand = QComboBox()
        for off, conf in (candidates or []):
            self.cmb_cand.addItem(f"{off:+d}  (신뢰도 {conf:.0%})", off)
        if self.cmb_cand.count() == 0:
            self.cmb_cand.addItem("(추천 없음)", None); self.cmb_cand.setEnabled(False)
        self.cmb_cand.currentIndexChanged.connect(self._pick_candidate)
        fo.addWidget(QLabel("추천:")); fo.addWidget(self.cmb_cand)
        self.btn_apply_off = QPushButton("오프셋 적용")
        self.btn_apply_off.clicked.connect(self._apply_offset)
        fo.addWidget(self.btn_apply_off)
        self.btn_verify = QPushButton("제목 대조")
        self.btn_verify.setToolTip("각 행의 실제 쪽 텍스트에 제목 앞부분이 있는지 검사(✓/✗). 저장에는 영향 없음")
        self.btn_verify.clicked.connect(self._verify)
        fo.addWidget(self.btn_verify)
        fo.addStretch(1)
        root.addWidget(self.grp_offset)
        self.grp_offset.setVisible(method == "toc")

        # ── 표 + 미리보기 ───────────────────────────────────────────
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["레벨", "제목", "목차 쪽", "실제 쪽", "확인"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        for c in (COL_LEVEL, COL_TOC, COL_PAGE, COL_OK):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(lambda r, _c, _pr, _pc: self._show_preview(r))
        ll.addWidget(self.table, 1)
        ops = QHBoxLayout()
        for label, tip, slot in (
                ("행 추가", "현재 행 아래에 새 항목", self._add_row),
                ("삭제", "선택 행 삭제", self._del_rows),
                ("▲", "위로", lambda: self._move(-1)),
                ("▼", "아래로", lambda: self._move(+1)),
                ("◀", "레벨 올리기(상위)", lambda: self._level(-1)),
                ("▶", "레벨 내리기(하위)", lambda: self._level(+1))):
            b = QPushButton(label); b.setToolTip(tip); b.clicked.connect(slot)
            b.setAutoDefault(False); b.setDefault(False)          # 디자인 §2.7
            ops.addWidget(b)
        ops.addStretch(1)
        ll.addLayout(ops)
        split.addWidget(left)

        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(6, 0, 0, 0)
        self.lbl_pv_title = QLabel("미리보기"); self.lbl_pv_title.setStyleSheet("font-weight:bold;")
        rl.addWidget(self.lbl_pv_title)
        self.lbl_pv = QLabel(); self.lbl_pv.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.lbl_pv.setMinimumWidth(300)
        self.lbl_pv.setStyleSheet("background:#f3f3f3; border:1px solid #c8c8c8;")
        rl.addWidget(self.lbl_pv, 1)
        nav = QHBoxLayout()
        self.btn_pv_prev = QPushButton("◀ 쪽"); self.btn_pv_next = QPushButton("쪽 ▶")
        self.btn_pv_set = QPushButton("이 쪽으로 확정")
        self.btn_pv_set.setToolTip("미리보기 중인 쪽을 현재 행의 실제 쪽으로 기록(수동)")
        for b in (self.btn_pv_prev, self.btn_pv_next, self.btn_pv_set):
            b.setAutoDefault(False); b.setDefault(False)
        self.btn_pv_prev.clicked.connect(lambda: self._pv_step(-1))
        self.btn_pv_next.clicked.connect(lambda: self._pv_step(+1))
        self.btn_pv_set.clicked.connect(self._pv_confirm)
        nav.addWidget(self.btn_pv_prev); nav.addWidget(self.btn_pv_next); nav.addStretch(1); nav.addWidget(self.btn_pv_set)
        rl.addLayout(nav)
        split.addWidget(right)
        split.setStretchFactor(0, 3); split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        # ── 버튼 ────────────────────────────────────────────────────
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("저장(책갈피 쓰기)")
        for b in bb.buttons():
            b.setAutoDefault(False); b.setDefault(False)
        bb.accepted.connect(self._accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)

        self._pv_page = None
        self._fill()
        if method == "toc":
            self._apply_offset(initial=True)
        if self.table.rowCount():
            self.table.setCurrentCell(0, COL_TITLE)

    # ── 데이터 ↔ 표 ─────────────────────────────────────────────────
    def _count_pages(self) -> int:
        try:
            import fitz
            d = fitz.open(str(self.pdf_path)); n = d.page_count; d.close(); return n
        except Exception:
            return 10 ** 6

    def _fill(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for r in self._rows:
            self._append_row(r)
        self.table.blockSignals(False)

    def _append_row(self, r: dict, at: int | None = None):
        row = self.table.rowCount() if at is None else at
        self.table.insertRow(row)
        vals = [str(int(r.get("level", 0))), r.get("title", ""),
                "" if r.get("toc_page") is None else str(r["toc_page"]),
                "" if r.get("page") is None else str(r["page"]), ""]
        for c, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if c in (COL_LEVEL, COL_TOC, COL_PAGE):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if c == COL_OK:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, c, it)
        if r.get("manual"):
            self.table.item(row, COL_PAGE).setBackground(QBrush(_MANUAL_BG))

    def _row_dict(self, row: int) -> dict:
        def txt(c):
            it = self.table.item(row, c); return (it.text() if it else "").strip()
        lv = toc_parse.fix_ocr_number(txt(COL_LEVEL)); lv = 0 if lv is None else min(5, int(lv))
        tp = toc_parse.fix_ocr_number(txt(COL_TOC))
        pg = toc_parse.fix_ocr_number(txt(COL_PAGE))
        manual = bool(self.table.item(row, COL_PAGE) and
                      self.table.item(row, COL_PAGE).background().color() == _MANUAL_BG)
        return {"title": txt(COL_TITLE), "toc_page": tp, "page": pg, "level": lv, "manual": manual}

    def rows(self) -> list[dict]:
        return [self._row_dict(i) for i in range(self.table.rowCount())]

    def result_bookmarks(self) -> list[tuple[str, int, int]]:
        return toc_parse.to_bookmarks(self.rows())

    # ── 편집 ────────────────────────────────────────────────────────
    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() == COL_PAGE and item.text().strip():
            item.setBackground(QBrush(_MANUAL_BG))          # 직접 고친 실제 쪽 = 수동
        if item.column() in (COL_PAGE, COL_TITLE):
            ok = self.table.item(item.row(), COL_OK)
            if ok: ok.setText(""); ok.setBackground(QBrush())
        if item.column() == COL_PAGE:
            self._show_preview(item.row())

    def _add_row(self):
        cur = self.table.currentRow()
        at = (cur + 1) if cur >= 0 else self.table.rowCount()
        base = self._row_dict(cur) if cur >= 0 else {"level": 0}
        self.table.blockSignals(True)
        self._append_row({"level": base.get("level", 0), "title": "", "toc_page": None,
                          "page": base.get("page")}, at)
        self.table.blockSignals(False)
        self.table.setCurrentCell(at, COL_TITLE)
        self.table.editItem(self.table.item(at, COL_TITLE))

    def _sel_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _del_rows(self):
        for r in reversed(self._sel_rows()):
            self.table.removeRow(r)

    def _move(self, d: int):
        rows = self._sel_rows()
        if not rows:
            return
        if d > 0:
            rows = rows[::-1]
        self.table.blockSignals(True)
        moved = []
        for r in rows:
            j = r + d
            if j < 0 or j >= self.table.rowCount():
                moved.append(r); continue
            a = [self.table.takeItem(r, c) for c in range(5)]
            b = [self.table.takeItem(j, c) for c in range(5)]
            for c in range(5):
                self.table.setItem(r, c, b[c]); self.table.setItem(j, c, a[c])
            moved.append(j)
        self.table.blockSignals(False)
        self.table.clearSelection()
        for j in moved:
            self.table.selectRow(j)
        self.table.setCurrentCell(moved[0], COL_TITLE)

    def _level(self, d: int):
        self.table.blockSignals(True)
        for r in self._sel_rows():
            it = self.table.item(r, COL_LEVEL)
            v = toc_parse.fix_ocr_number(it.text()) or 0
            it.setText(str(max(0, min(5, v + d))))
        self.table.blockSignals(False)

    # ── 오프셋 / 대조 ───────────────────────────────────────────────
    def _pick_candidate(self, _i):
        off = self.cmb_cand.currentData()
        if off is not None:
            self.spin_offset.setValue(int(off))

    def _apply_offset(self, initial: bool = False):
        off = int(self.spin_offset.value())
        rows = self.rows()
        toc_parse.apply_offset(rows, off, self._page_count, keep_manual=not initial)
        self.table.blockSignals(True)
        for i, r in enumerate(rows):
            it = self.table.item(i, COL_PAGE)
            it.setText("" if r.get("page") is None else str(r["page"]))
            if not r.get("manual") or initial:
                it.setBackground(QBrush())
            ok = self.table.item(i, COL_OK)
            if ok: ok.setText(""); ok.setBackground(QBrush())
        self.table.blockSignals(False)
        self._show_preview(self.table.currentRow())

    def _verify(self):
        res = toc_parse.verify_rows(self.pdf_path, self.rows())
        self.table.blockSignals(True)
        n_ok = 0
        for i in range(self.table.rowCount()):
            ok = bool(res.get(i)); n_ok += ok
            it = self.table.item(i, COL_OK)
            it.setText("✓" if ok else "✗")
            it.setBackground(QBrush(_OK_BG if ok else _NG_BG))
        self.table.blockSignals(False)
        QMessageBox.information(self, "제목 대조",
                                f"{n_ok} / {self.table.rowCount()} 행에서 실제 쪽에 제목이 확인됐습니다.\n"
                                "✗ 행은 실제 쪽을 직접 고치거나(미리보기 ◀▶ 후 '이 쪽으로 확정') 삭제하세요.")

    # ── 미리보기 ────────────────────────────────────────────────────
    def _show_preview(self, row: int, page: int | None = None):
        if row < 0 or row >= self.table.rowCount():
            return
        r = self._row_dict(row)
        pg = page if page is not None else r.get("page")
        self._pv_page = pg
        if not pg:
            self.lbl_pv.setText("실제 쪽이 비어 있습니다"); self.lbl_pv_title.setText("미리보기"); return
        self.lbl_pv_title.setText(f"미리보기 — 실제 {pg}쪽  (행: {r['title'][:24]})")
        try:
            import fitz
            d = fitz.open(str(self.pdf_path))
            try:
                pix = d.load_page(pg - 1).get_pixmap(matrix=fitz.Matrix(0.45, 0.45))
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                self.lbl_pv.setPixmap(QPixmap.fromImage(img.copy()))
            finally:
                d.close()
        except Exception as e:
            self.lbl_pv.setText(f"렌더 실패: {e}")
        self.previewPageRequested.emit(int(pg) - 1)

    def _pv_step(self, d: int):
        if self._pv_page is None:
            return
        pg = max(1, min(self._page_count, int(self._pv_page) + d))
        self._show_preview(self.table.currentRow(), pg)

    def _pv_confirm(self):
        row = self.table.currentRow()
        if row < 0 or self._pv_page is None:
            return
        it = self.table.item(row, COL_PAGE)
        it.setText(str(self._pv_page))                       # itemChanged → 수동 표시

    # ── 확정 ────────────────────────────────────────────────────────
    def _accept(self):
        bms = self.result_bookmarks()
        bad = [i + 1 for i, r in enumerate(self.rows()) if not r.get("page")]
        if not bms:
            QMessageBox.warning(self, "저장", "저장할 항목이 없습니다(실제 쪽이 비어 있음)."); return
        if bad and QMessageBox.question(
                self, "저장", f"실제 쪽이 비어 있는 행 {len(bad)}개(예: {bad[:5]})는 제외됩니다. 계속할까요?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.accept()
