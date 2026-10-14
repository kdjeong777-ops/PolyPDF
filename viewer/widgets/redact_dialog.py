# -*- coding: utf-8 -*-
"""가림 창 (보안 SOT §14, 261014-22) — 쪽 그림 위를 끌어 영역을 고르고, 패턴·검색어로 찾아 목록에 더한다.

본문 뷰어는 건드리지 않는다. 찾기는 `runner(일, 제목)`(메인 창의 `_run_merge_job`)로 배경에서 한다.
`marks()` = `[{page, rect(pt), kind, text}]`, `scrub()` = 숨은 데이터도 지울지.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QBrush, QColor, QImage, QPen, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGraphicsRectItem, QGraphicsScene, QGraphicsView,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

from viewer.i18n import tr

PREVIEW_DPI = 96


class _PageView(QGraphicsView):
    """쪽 그림 — 끌어서 영역을 만든다(좌표는 pt 로 돌려준다)."""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner
        self.setScene(QGraphicsScene(self))
        self._start = None
        self._rubber = None
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._start = self.mapToScene(e.position().toPoint())
            self._rubber = self.scene().addRect(QRectF(self._start, self._start), QPen(QColor("#d33"), 1.5),
                                                QBrush(QColor(220, 50, 50, 50)))
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._start is not None and self._rubber is not None:
            self._rubber.setRect(QRectF(self._start, self.mapToScene(e.position().toPoint())).normalized())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._start is not None and e.button() == Qt.MouseButton.LeftButton:
            r = QRectF(self._start, self.mapToScene(e.position().toPoint())).normalized()
            self.scene().removeItem(self._rubber)
            self._start = self._rubber = None
            if r.width() >= 3 and r.height() >= 3:
                self._owner._add_area(r)
            return
        super().mouseReleaseEvent(e)


class RedactDialog(QDialog):
    def __init__(self, parent=None, *, path: str, runner=None):
        super().__init__(parent)
        import fitz
        self.setWindowTitle(tr("가림(개인정보 지우기)") + " — " + Path(path).name)
        self.resize(1100, 760)
        self._path = str(path)
        self._runner = runner
        self._doc = fitz.open(self._path)
        self._page = 0
        self._marks = []
        self._k = PREVIEW_DPI / 72.0

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.view = _PageView(self)
        left.addWidget(self.view, 1)
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀")
        self.btn_next = QPushButton("▶")
        self.lbl_page = QLabel("")
        for w in (self.btn_prev, self.lbl_page, self.btn_next):
            nav.addWidget(w)
        nav.addStretch(1)
        nav.addWidget(QLabel(tr("쪽 그림 위를 끌어 가릴 영역을 고르세요.")))
        left.addLayout(nav)
        root.addLayout(left, 3)
        self.btn_prev.clicked.connect(lambda: self._go(self._page - 1))
        self.btn_next.clicked.connect(lambda: self._go(self._page + 1))

        right = QVBoxLayout()
        right.addWidget(QLabel(tr("찾아 가리기")))
        from viewer.redact import REDACT_PATTERNS
        self._chk = {}
        for key, label, _rx in REDACT_PATTERNS:
            c = QCheckBox(tr(label))
            c.setChecked(key in ("rrn", "phone", "email"))
            self._chk[key] = c
            right.addWidget(c)
        row = QHBoxLayout()
        self.ed_custom = QLineEdit()
        self.ed_custom.setPlaceholderText(tr("검색어(이름 등)"))
        self.cb_regex = QCheckBox(tr("정규식"))
        row.addWidget(self.ed_custom, 1)
        row.addWidget(self.cb_regex)
        right.addLayout(row)
        self.btn_find = QPushButton(tr("찾기"))
        self.btn_find.clicked.connect(self._find)
        right.addWidget(self.btn_find)
        right.addWidget(QLabel(tr("가릴 자리")))
        self.lst = QListWidget()
        self.lst.itemActivated.connect(self._goto_item)
        self.lst.itemClicked.connect(self._goto_item)
        right.addWidget(self.lst, 1)
        row2 = QHBoxLayout()
        self.btn_del = QPushButton(tr("고른 것 빼기"))
        self.btn_clear = QPushButton(tr("모두 빼기"))
        self.btn_del.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self._clear)
        row2.addWidget(self.btn_del)
        row2.addWidget(self.btn_clear)
        right.addLayout(row2)
        self.cb_scrub = QCheckBox(tr("문서 정보·숨은 데이터도 지우기"))
        self.cb_scrub.setChecked(True)
        self.cb_scrub.setToolTip(tr("작성자·제목 등 문서 정보, XMP, 첨부 파일, 자바스크립트, 썸네일을 지웁니다."))
        right.addWidget(self.cb_scrub)
        note = QLabel(tr("가린 자리의 글·그림은 실제로 지워집니다. 결과는 새 파일 <이름>_가림.pdf 로 저장하고 원본은 그대로 둡니다."))
        note.setWordWrap(True)
        right.addWidget(note)
        bb = QDialogButtonBox()
        self.btn_ok = bb.addButton(tr("가려서 저장"), QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        for b in bb.buttons():
            b.setAutoDefault(False)                 # 디자인 §2.7 — Enter 로 닫히지 않게
            b.setDefault(False)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        root.addLayout(right, 2)
        self._go(0)
        self._sync()

    # ── 쪽 ───────────────────────────────────────────────────
    def _go(self, pg: int) -> None:
        import fitz
        n = self._doc.page_count
        pg = max(0, min(n - 1, int(pg)))
        self._page = pg
        pix = self._doc.load_page(pg).get_pixmap(matrix=fitz.Matrix(self._k, self._k), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        sc = self.view.scene()
        sc.clear()
        sc.addPixmap(QPixmap.fromImage(img))
        sc.setSceneRect(QRectF(0, 0, pix.width, pix.height))
        for m in self._marks:
            if m["page"] == pg:
                self._draw(m)
        self.view.fitInView(sc.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.lbl_page.setText(f"{pg + 1} / {n}")
        self.btn_prev.setEnabled(pg > 0)
        self.btn_next.setEnabled(pg < n - 1)

    def showEvent(self, e):
        super().showEvent(e)
        self.view.fitInView(self.view.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _draw(self, m) -> None:
        x0, y0, x1, y1 = m["rect"]
        k = self._k
        it = QGraphicsRectItem(QRectF(QPointF(x0 * k, y0 * k), QPointF(x1 * k, y1 * k)))
        it.setPen(QPen(QColor("#d33"), 2))
        it.setBrush(QBrush(QColor(220, 50, 50, 60)))
        self.view.scene().addItem(it)

    # ── 자리 ─────────────────────────────────────────────────
    def _add_area(self, r: QRectF) -> None:
        from viewer.redact import KIND_AREA
        k = self._k
        m = {"page": self._page, "rect": (r.left() / k, r.top() / k, r.right() / k, r.bottom() / k),
             "kind": KIND_AREA, "text": ""}
        self._marks.append(m)
        self._draw(m)
        self._sync()

    def add_marks(self, ms) -> None:
        have = {(m["page"], tuple(round(v, 1) for v in m["rect"])) for m in self._marks}
        for m in ms:
            key = (m["page"], tuple(round(v, 1) for v in m["rect"]))
            if key not in have:
                have.add(key)
                self._marks.append(m)
        self._go(self._page)
        self._sync()

    def _find(self) -> None:
        from viewer import redact
        keys = [k for k, c in self._chk.items() if c.isChecked()]
        custom, rx = self.ed_custom.text(), self.cb_regex.isChecked()
        if rx and custom.strip():
            import re
            try:
                re.compile(custom.strip())
            except re.error as e:
                self.ed_custom.setToolTip(str(e))
                self.ed_custom.setStyleSheet("QLineEdit { border: 1px solid #d33; }")
                return
        self.ed_custom.setStyleSheet("")
        box = {}

        def job(progress):
            def tick(i, n, label):
                if progress(i, max(1, n), label) is False:
                    from viewer.twoup import MergeCancelled
                    raise MergeCancelled()
            box["ms"] = redact.find_marks(self._path, keys, custom, rx, tick)
        if self._runner is not None:
            self._runner(job, tr("가릴 자리 찾기"))
        else:
            job(lambda *a: True)
        ms = box.get("ms") or []
        self.add_marks(ms)
        self.lbl_page.setToolTip(tr('찾은 자리 {n}곳').format(n=len(ms)))

    def _sync(self) -> None:
        self.lst.clear()
        for i, m in enumerate(sorted(self._marks, key=lambda q: (q["page"], q["rect"][1], q["rect"][0]))):
            it = QListWidgetItem(f"p.{m['page'] + 1}  {tr(m['kind'])}  {m.get('text') or ''}".strip())
            it.setData(Qt.ItemDataRole.UserRole, id(m))     # Qt 는 dict 를 복사해 돌려준다 — 번호로 찾는다
            self.lst.addItem(it)
        self.btn_ok.setEnabled(bool(self._marks))
        self.btn_del.setEnabled(bool(self._marks))
        self.btn_clear.setEnabled(bool(self._marks))

    def _by_id(self, i):
        return next((m for m in self._marks if id(m) == i), None)

    def _goto_item(self, it) -> None:
        m = self._by_id(it.data(Qt.ItemDataRole.UserRole))
        if m and m["page"] != self._page:
            self._go(m["page"])

    def _remove_selected(self) -> None:
        drop = {it.data(Qt.ItemDataRole.UserRole) for it in self.lst.selectedItems()}
        self._marks = [m for m in self._marks if id(m) not in drop]
        self._go(self._page)
        self._sync()

    def _clear(self) -> None:
        self._marks = []
        self._go(self._page)
        self._sync()

    # ── 결과 ─────────────────────────────────────────────────
    def marks(self) -> list:
        return list(self._marks)

    def scrub(self) -> bool:
        return self.cb_scrub.isChecked()

    def done(self, r):
        try:
            self._doc.close()
        except Exception:
            pass
        super().done(r)
