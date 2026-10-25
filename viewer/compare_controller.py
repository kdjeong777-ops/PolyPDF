# -*- coding: utf-8 -*-
"""문서 비교 진입 (마스터 §4.11, 261014-23) — 책갈피창 '두 파일 비교...' 가 `action_compare` 로.

비교는 배경(`_run_merge_job`), 보이기는 2단 보기(왼쪽 옛판·오른쪽 새판) + 본문 칠하기(`MainView.set_marks`) + 변경 목록 창(모달 아님).
방식은 §11.11 표준: 본문 그대로 옮긴 믹스인.
"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout

from viewer.i18n import tr

COLOR_DELETE = (230, 60, 60, 70)       # 지운 줄 — 옛판
COLOR_INSERT = (40, 170, 70, 70)       # 넣은 줄 — 새판
COLOR_REPLACE = (240, 200, 40, 80)     # 바뀐 줄 — 양쪽


class CompareDialog(QDialog):
    """변경 목록 — 누르면 두 창이 함께 그 쪽으로. 닫으면 칠한 것을 지운다."""

    def __init__(self, owner, old, new, changes):
        super().__init__(owner)
        from viewer.compare import KIND_LABELS
        self.setWindowTitle(tr("문서 비교") + f" — {Path(old).name} ↔ {Path(new).name}")
        self.setModal(False)
        self.resize(560, 520)
        self._owner, self._old, self._new = owner, str(old), str(new)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(tr('왼쪽(옛판): {a}\n오른쪽(새판): {b}\n바뀐 곳 {n}곳 — 누르면 두 창이 그 쪽으로 갑니다.').format(
            a=Path(old).name, b=Path(new).name, n=len(changes))))
        self.lst = QListWidget()
        for i, c in enumerate(changes):
            po = c["old"][0][0] + 1 if c["old"] else None
            pn = c["new"][0][0] + 1 if c["new"] else None
            where = f"p.{po if po else '-'} ↔ p.{pn if pn else '-'}"
            it = QListWidgetItem(f"{where}  {tr(KIND_LABELS[c['kind']])}: {c['text'][:120]}")
            it.setData(Qt.ItemDataRole.UserRole, i)
            self.lst.addItem(it)
        self.lst.itemClicked.connect(self._go)
        self.lst.itemActivated.connect(self._go)
        v.addWidget(self.lst, 1)
        b = QPushButton(tr("닫기"))
        b.setAutoDefault(False)
        b.clicked.connect(self.close)
        v.addWidget(b)
        self._changes = changes

    def _go(self, it) -> None:
        c = self._changes[int(it.data(Qt.ItemDataRole.UserRole))]
        self._owner._compare_show(self._old, self._new, c)

    def closeEvent(self, e):
        self._owner._compare_clear(self._old, self._new)
        super().closeEvent(e)


class CompareMixin:
    def action_compare(self, a, b) -> list | None:
        """두 파일 비교 — 옛판은 수정 시각이 이른 파일. 바뀐 곳 목록(없거나 취소면 None)."""
        from viewer import compare
        from viewer.twoup import MergeCancelled
        a, b = str(a), str(b)
        if not (Path(a).exists() and Path(b).exists()):
            return None
        old, new = (a, b) if os.path.getmtime(a) <= os.path.getmtime(b) else (b, a)
        box = {}

        def job(progress):
            def tick(done, label):
                if progress(int(done), 1000, label) is False:
                    raise MergeCancelled()
            box["ch"] = compare.compare(old, new, tick)
        res = self._run_merge_job(job, tr("문서 비교"), counts=False)   # 막대 척도 0~1000 은 글에 넣지 않는다(디자인 SOT §2.7)
        if "ch" not in box:
            if res.get("err"):
                QMessageBox.warning(self, tr("문서 비교"), str(res.get("err")))
            return None
        changes = box["ch"]
        if not changes:
            QMessageBox.information(self, tr("문서 비교"), tr("두 문서의 글이 같습니다."))
            return changes
        # 칠하기 — 옛판: 지움(빨강)·바뀜(노랑), 새판: 넣음(초록)·바뀜(노랑)
        mo, mn = {}, {}
        for c in changes:
            col_o = COLOR_DELETE if c["kind"] == "delete" else COLOR_REPLACE
            col_n = COLOR_INSERT if c["kind"] == "insert" else COLOR_REPLACE
            for pg, rect, _t in c["old"]:
                mo.setdefault(pg, []).append((rect, col_o))
            for pg, rect, _t in c["new"]:
                mn.setdefault(pg, []).append((rect, col_n))
        if not getattr(self, "_split_on", False):
            self._toggle_split(True)
            try:
                self.act_split.setChecked(True)
            except Exception:
                pass
        self._mv[0].set_marks(old, mo)
        self._mv[1].set_marks(new, mn)
        self._compare_show(old, new, changes[0])
        dlg = CompareDialog(self, old, new, changes)
        self._compare_dlg = dlg
        dlg.show()
        return changes

    def _compare_show(self, old, new, change) -> None:
        """두 창이 함께 그 바뀐 곳의 쪽으로(왼쪽 옛판·오른쪽 새판)."""
        from viewer.history import HistoryItem
        po = change["old"][0][0] if change["old"] else None
        pn = change["new"][0][0] if change["new"] else None
        for pane, path, pg in ((0, old, po), (1, new, pn)):
            mv = self._mv[pane]
            if pg is None:
                continue
            self._set_active_pane(pane)
            if mv.current_file() and os.path.normcase(str(mv.current_file())) == os.path.normcase(path):
                mv.go_to_page(pg) if hasattr(mv, "go_to_page") else self._load_main(HistoryItem(path, pg, "", "bookmark"))
            else:
                self._load_main(HistoryItem(path, pg, "", "bookmark"))

    def _compare_clear(self, old, new) -> None:
        for mv, path in ((self._mv[0], old), (self._mv[1], new)):
            try:
                mv.set_marks(path, None)
            except Exception:
                pass
