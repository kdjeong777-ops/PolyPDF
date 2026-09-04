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
                             QDialogButtonBox, QMessageBox, QRadioButton, QApplication,
                             QCheckBox, QScrollArea, QStyledItemDelegate)

from viewer import toc_parse

INDENT_PX = 14          # 260904-7: 제목 열 레벨당 들여쓰기(표시만 — 제목 텍스트는 그대로)


class _IndentDelegate(QStyledItemDelegate):
    """제목 셀을 레벨(같은 행 '레벨' 열)만큼 들여 그린다. 텍스트에 공백을 넣지 않으므로 책갈피 제목은 오염되지 않는다."""

    @staticmethod
    def indent_px(level) -> int:
        try:
            return max(0, int(level)) * INDENT_PX
        except (TypeError, ValueError):
            return 0

    def _indent(self, index) -> int:
        return self.indent_px(index.sibling(index.row(), COL_LEVEL).data())

    def paint(self, painter, option, index):
        opt = option
        d = self._indent(index)
        if d:
            from PyQt6.QtWidgets import QStyleOptionViewItem
            opt = QStyleOptionViewItem(option)
            opt.rect = option.rect.adjusted(d, 0, 0, 0)
            painter.save(); painter.setClipRect(option.rect)
            # 배경(선택·대조 색)은 셀 전체에, 글자만 들여쓰기
            if option.state & QStyle_Selected:
                painter.fillRect(option.rect, option.palette.highlight())
            else:
                bg = index.data(Qt.ItemDataRole.BackgroundRole)
                if bg is not None:
                    painter.fillRect(option.rect, bg)
        super().paint(painter, opt, index)
        if d:
            painter.restore()

    def updateEditorGeometry(self, editor, option, index):
        r = option.rect.adjusted(self._indent(index), 0, 0, 0)
        editor.setGeometry(r)


from PyQt6.QtWidgets import QStyle as _QStyle
QStyle_Selected = _QStyle.StateFlag.State_Selected

COL_LEVEL, COL_TITLE, COL_TOC, COL_PAGE = range(4)
N_COLS = 4          # 260904-3: '확인' 열 삭제 — [제목 대조] 결과는 제목 셀 배경색(✓ 초록/✗ 빨강)
_OK_BG = QColor("#e8f5e9")
_NG_BG = QColor("#fdecea")
_MANUAL_BG = QColor("#fff8e1")
_MOVED_BG = QColor("#e3f2fd")       # 260904-8: 쪽 순서 정렬로 옮기거나 번호를 고친 행의 목차 쪽 셀


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
        self.setWindowTitle(("기존 책갈피 수정 — " if method == "existing" else "책갈피 검토 — ")
                            + self.pdf_path.name)
        # 260904-2(사용자 요청): 전체 화면의 3/4 크기, 미리보기를 오른쪽에 충분히 크게
        try:
            scr = (parent.screen() if parent is not None else QApplication.primaryScreen()).availableGeometry()
            self.resize(int(scr.width() * 0.75), int(scr.height() * 0.75))
        except Exception:
            self.resize(1280, 800)

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
        self.btn_renumber = QPushButton("번호 수정")
        self.btn_renumber.setToolTip("현재 행의 번호를 **바로 위 같은 레벨 형제의 번호 + 1** 로 고치고(형제가 없으면 1), "
                                     "그 아래 같은 레벨 형제들도 이어서 +1 씩 다시 매깁니다(상위 레벨이 나오기 전까지). "
                                     "레벨을 고친 뒤 이 버튼으로 번호를 잇습니다. 형식은 옆 콤보(자동 = 위 형제의 형식)")
        self.btn_renumber.clicked.connect(self._renumber)
        fo.addWidget(self.btn_renumber)
        self.cmb_numstyle = QComboBox()
        for label, key in (("형식: 자동", None), ("1.", "dot"), ("1)", "paren"), ("1", "bare")):
            self.cmb_numstyle.addItem(label, key)
        self.cmb_numstyle.setToolTip("번호 수정 형식 — 자동: 바로 위 같은 레벨 형제의 형식을 따름(없으면 레벨 1 '1.', 그 아래 '1)')")
        fo.addWidget(self.cmb_numstyle)
        for b in (self.btn_apply_off, self.btn_verify, self.btn_renumber):
            b.setAutoDefault(False); b.setDefault(False)
        fo.addStretch(1)
        root.addWidget(self.grp_offset)
        self.grp_offset.setVisible(method == "toc")

        # ── 표 + 미리보기 ───────────────────────────────────────────
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, N_COLS)
        self.table.setItemDelegateForColumn(COL_TITLE, _IndentDelegate(self.table))   # 260904-7: 위계 들여쓰기
        self.table.setHorizontalHeaderLabels(["레벨", "제목", "목차 쪽", "실제 쪽"])
        hh = self.table.horizontalHeader()
        # 260904-2: 표는 내용이 보일 만큼만 — 제목 열은 내용 맞춤(상한 420px), 나머지는 내용 맞춤.
        hh.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(False)
        for c in (COL_LEVEL, COL_TOC, COL_PAGE):
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
                ("▶", "레벨 내리기(하위)", lambda: self._level(+1)),
                ("쪽순 정렬", "목차 쪽이 중간에 줄어들지 않도록 — 자릿수가 빠진 쪽은 고치고(20→120), 순서 밖 행은 제자리로 옮깁니다"
                             "(표·그림 목록은 따로). 바뀐 행은 목차 쪽 셀이 파란색", self._sort_pages)):
            b = QPushButton(label); b.setToolTip(tip); b.clicked.connect(slot)
            b.setAutoDefault(False); b.setDefault(False)          # 디자인 §2.7
            ops.addWidget(b)
        ops.addStretch(1)
        ll.addLayout(ops)
        split.addWidget(left)

        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(6, 0, 0, 0)
        top = QHBoxLayout()
        self.lbl_pv_title = QLabel("미리보기"); self.lbl_pv_title.setStyleSheet("font-weight:bold;")
        top.addWidget(self.lbl_pv_title, 1)
        # 260904-2: 미리보기 대상 — '목차' 쪽(항목을 읽어 온 차례 쪽) / '내용' 쪽(실제 쪽)
        self.rb_pv_toc = QRadioButton("목차 보기"); self.rb_pv_body = QRadioButton("내용 보기")
        # 260904-4(사용자 요청): 처음엔 '목차 보기' — 읽어 온 원문과 표를 먼저 대조하도록
        (self.rb_pv_toc if self.toc_pages else self.rb_pv_body).setChecked(True)
        self.rb_pv_toc.setToolTip("이 행을 읽어 온 차례 쪽을 보여 줍니다(제목·쪽번호 원문 확인)")
        self.rb_pv_body.setToolTip("실제 쪽을 보여 줍니다(◀▶ 로 이웃 쪽을 훑고 '이 쪽으로 확정')")
        self.rb_pv_toc.setEnabled(bool(self.toc_pages))
        for rb in (self.rb_pv_toc, self.rb_pv_body):
            rb.toggled.connect(lambda on: on and self._show_preview(self.table.currentRow(), force=True))
            top.addWidget(rb)
        # 260904-3: 가로 꽉 차게(세로는 스크롤) ↔ 쪽 전체 맞춤
        self.chk_fit_width = QCheckBox("가로 꽉 차게")
        self.chk_fit_width.setToolTip("미리보기 폭에 쪽 너비를 맞춥니다(세로는 스크롤). 끄면 쪽 전체가 보이게 맞춤")
        self.chk_fit_width.toggled.connect(lambda _on: self._show_preview(self.table.currentRow(), force=True))
        top.addWidget(self.chk_fit_width)
        rl.addLayout(top)
        self.lbl_pv = QLabel(); self.lbl_pv.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.lbl_pv.setStyleSheet("background:#f3f3f3;")
        self.pv_scroll = QScrollArea(); self.pv_scroll.setWidget(self.lbl_pv)
        self.pv_scroll.setWidgetResizable(True)
        self.pv_scroll.setMinimumSize(360, 300)
        self.pv_scroll.setStyleSheet("QScrollArea{background:#f3f3f3; border:1px solid #c8c8c8;}")
        rl.addWidget(self.pv_scroll, 1)
        nav = QHBoxLayout()
        self.btn_pv_prev = QPushButton("◀ 쪽"); self.btn_pv_next = QPushButton("쪽 ▶")
        self.btn_pv_set = QPushButton("이 쪽으로 확정")
        self.btn_pv_set.setToolTip("미리보기 중인 쪽을 현재 행의 실제 쪽으로 기록(수동)")
        for b in (self.btn_pv_prev, self.btn_pv_next, self.btn_pv_set):
            b.setAutoDefault(False); b.setDefault(False)
        self.btn_pv_prev.clicked.connect(lambda: self._pv_step(-1))
        self.btn_pv_next.clicked.connect(lambda: self._pv_step(+1))
        self.btn_pv_set.clicked.connect(self._pv_confirm)
        # 260904-3: ◀▶ 는 미리보기 폭의 중앙, 확정 버튼은 오른쪽
        nav.addStretch(1); nav.addWidget(self.btn_pv_prev); nav.addWidget(self.btn_pv_next); nav.addStretch(1)
        nav.addWidget(self.btn_pv_set)
        self._nav = nav
        rl.addLayout(nav)
        split.addWidget(right)
        # 260904-2: 오른쪽(미리보기)이 넓게 — 표는 내용 폭만
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1)
        self._split = split
        root.addWidget(split, 1)

        # ── 버튼 ────────────────────────────────────────────────────
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("저장(책갈피 쓰기)")
        for b in bb.buttons():
            b.setAutoDefault(False); b.setDefault(False)
        bb.accepted.connect(self._accept); bb.rejected.connect(self.reject)
        root.addWidget(bb)

        self._pv_page = None; self._pv_mode = None; self._pv_rendered = False
        self._fill()
        if method == "toc":
            self._apply_offset(initial=True)
        self._fit_table_width()
        if self.table.rowCount():
            self.table.setCurrentCell(0, COL_TITLE)

    def _fit_table_width(self):
        """표 폭 = 열 내용 폭 합(제목 열 상한 420) + 여백; 나머지는 전부 미리보기."""
        self.table.resizeColumnToContents(COL_TITLE)
        deepest = 0
        for i in range(self.table.rowCount()):
            it = self.table.item(i, COL_LEVEL)
            deepest = max(deepest, _IndentDelegate.indent_px(it.text() if it else 0))
        self.table.setColumnWidth(COL_TITLE, min(420 + deepest, max(160, self.table.columnWidth(COL_TITLE) + 8 + deepest)))
        w = sum(self.table.columnWidth(c) for c in range(N_COLS)) + self.table.verticalHeader().width() + 28
        total = max(self.width(), 900)
        w = min(w, int(total * 0.5))
        try:
            self._split.setSizes([w, max(300, total - w)])
        except Exception:
            pass

    def showEvent(self, ev):
        super().showEvent(ev)
        # 260904-4: 처음 뜰 때는 레이아웃이 아직 확정 전이라 첫 렌더가 작게 나왔다 →
        #   표시 뒤 한 틱 늦게 표 폭·미리보기를 실제 크기로 다시 맞춘다.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._after_show)

    def _after_show(self):
        try:
            self._fit_table_width()
            self._show_preview(self.table.currentRow(), force=True)
        except Exception:
            pass

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # 창 크기가 바뀌면 미리보기를 라벨 크기에 맞춰 다시 렌더
        r = self.table.currentRow()
        if r >= 0 and self._pv_page and self._pv_rendered:
            self._render_preview(self._pv_page, keep_scroll=True)

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
                "" if r.get("page") is None else str(r["page"])]
        for c, v in enumerate(vals):
            it = QTableWidgetItem(v)
            if c in (COL_LEVEL, COL_TOC, COL_PAGE):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if c == COL_TITLE:
                it.setData(Qt.ItemDataRole.UserRole, r.get("src") or "")   # 출처 쪽(pN) 보존
            if c == COL_PAGE:
                it.setData(Qt.ItemDataRole.UserRole, r.get("page"))        # 260904-6: 이전 값(이동량 계산)
            self.table.setItem(row, c, it)
        if r.get("manual"):
            self.table.item(row, COL_PAGE).setBackground(QBrush(_MANUAL_BG))
        if r.get("moved") or r.get("repaired"):
            it = self.table.item(row, COL_TOC)
            it.setBackground(QBrush(_MOVED_BG))
            it.setToolTip("쪽 순서 정렬로 " + ("번호를 고친 행" if r.get("repaired") else "옮긴 행") + " — 원문과 대조하세요")

    def _row_dict(self, row: int) -> dict:
        def txt(c):
            it = self.table.item(row, c); return (it.text() if it else "").strip()
        lv = toc_parse.fix_ocr_number(txt(COL_LEVEL)); lv = 0 if lv is None else min(5, int(lv))
        tp = toc_parse.fix_ocr_number(txt(COL_TOC))
        pg = toc_parse.fix_ocr_number(txt(COL_PAGE))
        manual = bool(self.table.item(row, COL_PAGE) and
                      self.table.item(row, COL_PAGE).background().color() == _MANUAL_BG)
        src = self.table.item(row, COL_TITLE).data(Qt.ItemDataRole.UserRole) if self.table.item(row, COL_TITLE) else ""
        return {"title": txt(COL_TITLE), "toc_page": tp, "page": pg, "level": lv, "manual": manual,
                "src": src or ""}

    def rows(self) -> list[dict]:
        return [self._row_dict(i) for i in range(self.table.rowCount())]

    def result_bookmarks(self) -> list[tuple[str, int, int]]:
        return toc_parse.to_bookmarks(self.rows())

    # ── 편집 ────────────────────────────────────────────────────────
    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() == COL_PAGE and item.text().strip():
            item.setBackground(QBrush(_MANUAL_BG))          # 직접 고친 실제 쪽 = 수동
        if item.column() in (COL_PAGE, COL_TITLE):
            tt = self.table.item(item.row(), COL_TITLE)
            if tt and item.column() == COL_PAGE: tt.setBackground(QBrush())   # 대조 결과 무효화
        if item.column() == COL_PAGE:
            self._shift_following(item)
            self._show_preview(item.row())

    def _shift_following(self, item: QTableWidgetItem):
        """260904-6: 실제 쪽을 고치면(직접 입력·[이 쪽으로 확정]) 그 차이만큼 **이후 행도 같이** 옮긴다
        — 스캔본의 오프셋은 그 지점부터 바뀐 것이므로(76→75 면 다음 80→79). 다음 수동 행(이미 확인한 쪽)
        전까지만; 수동 행은 건드리지 않는다. 옮긴 행은 수동이 아니므로 [오프셋 적용] 은 다시 계산한다."""
        old = item.data(Qt.ItemDataRole.UserRole)
        new = toc_parse.fix_ocr_number(item.text())
        item.setData(Qt.ItemDataRole.UserRole, new)
        if old is None or new is None or int(old) == int(new):
            return
        delta = int(new) - int(old)
        self.table.blockSignals(True)
        try:
            for j in range(item.row() + 1, self.table.rowCount()):
                pit = self.table.item(j, COL_PAGE)
                if pit is None:
                    continue
                if pit.background().color() == _MANUAL_BG:
                    break                                   # 다음 수동 행부터는 그 행이 기준
                p = toc_parse.fix_ocr_number(pit.text())
                if p is None:
                    continue
                q = max(1, min(self._page_count, int(p) + delta))
                pit.setText(str(q)); pit.setData(Qt.ItemDataRole.UserRole, q)
                tt = self.table.item(j, COL_TITLE)
                if tt: tt.setBackground(QBrush())           # 대조 결과 무효화
        finally:
            self.table.blockSignals(False)

    def _add_row(self):
        cur = self.table.currentRow()
        at = (cur + 1) if cur >= 0 else self.table.rowCount()
        base = self._row_dict(cur) if cur >= 0 else {"level": 0}
        self.table.blockSignals(True)
        # 260904-6: 출처 목차 쪽(src)을 물려받아 '목차 보기' 미리보기가 첫 목차 쪽으로 튀지 않게
        self._append_row({"level": base.get("level", 0), "title": "", "toc_page": None,
                          "page": base.get("page"), "src": base.get("src") or ""}, at)
        # 새 행의 물려받은 쪽은 관측값이 아니다 → 처음 고칠 때 이후 행을 옮기지 않는다(이전 값 없음)
        self.table.item(at, COL_PAGE).setData(Qt.ItemDataRole.UserRole, None)
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
            a = [self.table.takeItem(r, c) for c in range(N_COLS)]
            b = [self.table.takeItem(j, c) for c in range(N_COLS)]
            for c in range(N_COLS):
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
            it.setData(Qt.ItemDataRole.UserRole, r.get("page"))
            if not r.get("manual") or initial:
                it.setBackground(QBrush())
            tt = self.table.item(i, COL_TITLE)
            if tt: tt.setBackground(QBrush())
        self.table.blockSignals(False)
        self._show_preview(self.table.currentRow())

    def _verify(self):
        res = toc_parse.verify_rows(self.pdf_path, self.rows())
        self.table.blockSignals(True)
        n_ok = 0
        for i in range(self.table.rowCount()):
            ok = bool(res.get(i)); n_ok += ok
            self.table.item(i, COL_TITLE).setBackground(QBrush(_OK_BG if ok else _NG_BG))
        self.table.blockSignals(False)
        QMessageBox.information(self, "제목 대조",
                                f"{n_ok} / {self.table.rowCount()} 행에서 실제 쪽에 제목이 확인됐습니다"
                                "(제목 칸 초록=확인, 빨강=미확인).\n"
                                "빨간 행은 실제 쪽을 직접 고치거나(미리보기 ◀▶ 후 '이 쪽으로 확정') 삭제하세요.")

    def _renumber(self):
        """[번호 수정] (260904-8): 선택한 행마다 번호 = 바로 위 같은 레벨 형제 + 1 (위에서부터 차례로)."""
        rows = self.rows()
        sel = self._sel_rows() or ([self.table.currentRow()] if self.table.currentRow() >= 0 else [])
        n, skipped = 0, 0
        for i in sel:
            if int(rows[i].get("level", 0)) <= 0:
                skipped += 1; continue
            n += toc_parse.renumber_siblings_from(rows, i, style=self.cmb_numstyle.currentData())
        self.table.blockSignals(True)
        for i, r in enumerate(rows):
            it = self.table.item(i, COL_TITLE)
            if it and it.text() != r["title"]:
                it.setText(r["title"])
        self.table.blockSignals(False)
        if not sel:
            QMessageBox.information(self, "번호 수정", "번호를 고칠 행을 먼저 선택하세요."); return
        if skipped and not n:
            QMessageBox.information(self, "번호 수정", "장 제목(레벨 0)은 번호를 붙이지 않습니다."); return
        self.status_msg(f"{n}개 행의 번호를 고쳤습니다(위 형제 + 1, 아래 형제 이어서)." + (f" (장 행 {skipped}개 제외)" if skipped else ""))

    def status_msg(self, text: str):
        """창 제목줄 대신 미리보기 제목 옆에 잠깐 보이는 안내(모달 메시지 없이)."""
        try:
            self.lbl_pv_title.setText(text)
        except Exception:
            pass

    def _sort_pages(self):
        """[쪽순 정렬] (260904-8): 표의 현재 내용을 `toc_parse.sort_by_toc_page` 로 정리해 다시 채운다."""
        rows = self.rows()
        cur = self.table.currentRow()
        cur_row = rows[cur] if 0 <= cur < len(rows) else None
        n = toc_parse.sort_by_toc_page(rows)
        if n:
            self._rows = rows
            self._fill()
            if cur_row is not None:
                for i, r in enumerate(rows):
                    if r is cur_row:
                        self.table.setCurrentCell(i, COL_TITLE); break
        QMessageBox.information(self, "쪽순 정렬", f"{n}개 행을 옮기거나 쪽 번호를 고쳤습니다(목차 쪽 셀 파란색)." if n
                                else "쪽 순서가 이미 맞습니다.")

    def verify_marks(self) -> list:
        """(테스트용) 제목 셀 배경으로 본 대조 결과 — 'ok'/'ng'/''."""
        out = []
        for i in range(self.table.rowCount()):
            c = self.table.item(i, COL_TITLE).background().color()
            out.append("ok" if c == _OK_BG else "ng" if c == _NG_BG else "")
        return out

    # ── 미리보기 ────────────────────────────────────────────────────
    def _preview_mode(self) -> str:
        return "toc" if (self.rb_pv_toc.isChecked() and self.rb_pv_toc.isEnabled()) else "body"

    def _src_page(self, r: dict) -> int | None:
        """행의 출처 차례 쪽(pN → N). 없으면 첫 목차 쪽."""
        s = str(r.get("src") or "")
        if s.startswith("p") and s[1:].isdigit():
            return int(s[1:])
        return self.toc_pages[0] if self.toc_pages else None

    def _show_preview(self, row: int, page: int | None = None, force: bool = False):
        if row < 0 or row >= self.table.rowCount():
            return
        r = self._row_dict(row)
        mode = self._preview_mode()
        if page is not None:
            pg = page
        elif mode == "toc":
            pg = self._src_page(r)
        else:
            pg = r.get("page")
        same = (pg == self._pv_page and mode == self._pv_mode and self._pv_rendered)
        self._pv_page = pg; self._pv_mode = mode
        self.btn_pv_set.setEnabled(mode == "body")             # 확정은 내용 보기에서만
        if not pg:
            self._pv_rendered = False
            self.lbl_pv.setText("실제 쪽이 비어 있습니다" if mode == "body" else "출처 목차 쪽을 알 수 없습니다")
            self.lbl_pv_title.setText("미리보기"); return
        self.lbl_pv_title.setText(
            f"{'목차' if mode == 'toc' else '내용'} — {pg}쪽  (행: {r['title'][:28]})")
        # 260904-6: 같은 쪽·같은 모드면 다시 그리지 않는다 — 행 추가/편집/커서 이동에도 보던 위치(스크롤) 유지
        if same and not force:
            return
        self._render_preview(pg, keep_scroll=same)
        if mode == "body":
            self.previewPageRequested.emit(int(pg) - 1)

    def _render_preview(self, pg: int, keep_scroll: bool = False):
        """라벨 크기에 맞춰 쪽을 렌더(창을 키우면 더 크게). keep_scroll: 같은 쪽 재렌더 — 스크롤 비율 유지."""
        sb = self.pv_scroll.verticalScrollBar()
        ratio = (sb.value() / sb.maximum()) if (keep_scroll and sb.maximum() > 0) else None
        try:
            import fitz
            d = fitz.open(str(self.pdf_path))
            try:
                page = d.load_page(int(pg) - 1)
                rect = page.rect
                vp = self.pv_scroll.viewport()
                aw = max(200, vp.width() - 4); ah = max(200, vp.height() - 4)
                if self.chk_fit_width.isChecked():
                    zoom = max(0.2, (aw - 2) / rect.width)          # 가로 꽉 차게(세로 스크롤)
                else:
                    zoom = max(0.2, min(aw / rect.width, ah / rect.height))
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                self.lbl_pv.setPixmap(QPixmap.fromImage(img.copy()))
                self._pv_rendered = True
                if ratio is not None:
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: sb.setValue(int(ratio * sb.maximum())))
            finally:
                d.close()
        except Exception as e:
            self._pv_rendered = False
            self.lbl_pv.setText(f"렌더 실패: {e}")

    def _pv_step(self, d: int):
        if self._pv_page is None:
            return
        pg = max(1, min(self._page_count, int(self._pv_page) + d))
        if pg == self._pv_page:
            return
        self._show_preview(self.table.currentRow(), pg)
        # 260904-8: 다음 쪽은 상단부터, 이전 쪽은 하단부터(가로 꽉 차게 보기에서 읽던 흐름 그대로)
        sb = self.pv_scroll.verticalScrollBar()
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: sb.setValue(0 if d > 0 else sb.maximum()))

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
