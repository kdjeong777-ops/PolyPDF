# -*- coding: utf-8 -*-
"""PDF 정보 한 줄 · 문서 정보 창 — 앱 쪽 (`DocInfoMixin`, 마스터 SOT §4.12 · 디자인 SOT §2.8.6.1, 261107-3).

본문 창마다 정보 한 줄(`PageNavHost.info_line(i)`)을 그 창 문서로 채운다. 사진 모드에서는 같은 줄을 사진 정보가 쓴다
(`photo_controller._photo_info_*`) — 여기서는 건드리지 않는다. 문서 정보 창을 여는 함수는 `show_doc_info` 하나다.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QObject

from viewer import doc_info
from viewer.i18n import tr


def _hint() -> str:
    return tr("누르면 문서의 세부 정보를 봅니다.")


class _EmptyWatch(QObject):
    """본문 창의 빈 화면 안내가 보이면(문서를 닫음) 그 창 정보 줄을 비운다 — `close_document` 는 신호를 내지 않는다."""

    def __init__(self, owner, pane: int):
        super().__init__(owner)
        self._owner, self._pane = owner, pane

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Show:
            self._owner._doc_info_refresh(self._pane)
        return False


class DocInfoMixin:
    def _doc_info_init(self):
        host = self.page_nav_host
        host.set_info_handler(self._doc_info_clicked)
        host.set_left_widget(self._bk_count)
        self._doc_info_state = [{} for _ in self._mv]          # 창마다 {path, gen, facts, info}
        self._doc_info_gen = 0
        self._doc_info_keep = []
        self._doc_info_watch = []
        for i, mv in enumerate(self._mv):
            mv.pageChanged.connect(lambda _pg, k=i: self._doc_info_refresh(k))
            lab = getattr(mv, "_empty_label", None)
            if lab is not None:
                f = _EmptyWatch(self, i)
                lab.installEventFilter(f)
                self._doc_info_watch.append(f)

    def _photo_after_mode(self, on: bool):
        """사진 모드 훅(`photo_controller._photo_on_mode_changed` 끝) — 모드가 바뀌면 정보 줄 주인이 바뀐다.
        사진 모드로: PDF 정보를 지운다(사진 정보가 사진을 열 때 쓴다). PDF 모드로: 창마다 다시."""
        host = getattr(self, "page_nav_host", None)
        if host is None:
            return
        for i in range(len(self._mv)):
            if on:
                self._doc_info_state[i].clear()
                host.info_line(i).set_info(None)
            else:
                self._doc_info_refresh(i)

    def _doc_info_pdf(self, i: int):
        from viewer.pdf_doc import PdfDocument
        doc = getattr(self._mv[i], "_doc", None)
        return doc if isinstance(doc, PdfDocument) else None

    def _doc_info_refresh(self, i: int):
        """i 번 창의 정보 한 줄을 다시 — 메인은 열린 문서에서 아는 값만, 나머지는 배경(응답성 SOT §5)."""
        if getattr(self, "_photo_mode", False):
            return                                              # 사진 모드 — 사진 정보가 이 줄을 쓴다
        host = getattr(self, "page_nav_host", None)
        if host is None:
            return
        st = self._doc_info_state[i]
        doc = self._doc_info_pdf(i)
        if doc is None:
            st.clear()
            host.info_line(i).set_info(None)
            return
        path = str(doc.path)
        facts = doc_info.main_facts(doc, self._mv[i].current_page())
        if st.get("path") != path:
            old = st.get("worker")
            if old is not None:
                try:
                    old.request_cancel()
                except RuntimeError:
                    pass
            st.clear()
            st["path"] = path
            st["info"] = doc_info.cached(path)
            self._doc_info_gen += 1
            st["gen"] = self._doc_info_gen
            from viewer.workers import run_in_thread
            w = doc_info.DocInfoWorker(st["gen"], i, path)
            w.done.connect(self._doc_info_done)
            st["worker"] = w
            run_in_thread(w, self._doc_info_keep)
        st["facts"] = facts
        host.info_line(i).set_info(doc_info.doc_info_line(facts, st.get("info")), _hint())
        self._doc_info_dialog_refresh(i)

    def _doc_info_done(self, gen: int, i: int, path: str, info: dict):
        st = self._doc_info_state[i] if 0 <= i < len(self._doc_info_state) else {}
        if st.get("gen") != gen or st.get("path") != path:
            return
        st["info"] = info
        st.pop("worker", None)
        if getattr(self, "_photo_mode", False) or "facts" not in st:
            return
        self.page_nav_host.info_line(i).set_info(doc_info.doc_info_line(st["facts"], info), _hint())
        self._doc_info_dialog_refresh(i)

    def _doc_info_clicked(self, i: int):
        self.show_doc_info(i)

    def show_doc_info(self, pane=None):
        """문서 정보 창 — 우클릭 '문서 정보'·단축키·정보 한 줄이 부르는 하나의 함수(마스터 §4.12).
        사진 모드면 사진 정보 창. pane 없으면 활성 창."""
        if getattr(self, "_photo_mode", False):
            self._photo_info_dialog()
            return
        i = self._active_pane if pane is None else int(pane)
        if self._doc_info_pdf(i) is None:
            self.status.showMessage(tr("열린 PDF 가 없습니다."), 3000)
            return
        if not self._doc_info_state[i].get("facts"):
            self._doc_info_refresh(i)
        from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QTableWidget,
                                     QVBoxLayout)
        dlg = getattr(self, "_doc_info_dlg", None)
        if dlg is None:
            dlg = QDialog(self)
            dlg.setObjectName("docInfoDialog")
            lay = QVBoxLayout(dlg)
            t = QTableWidget(0, 2, dlg)
            t.setHorizontalHeaderLabels([tr("항목"), tr("값")])
            t.verticalHeader().setVisible(False)
            t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            t.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(t)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dlg)
            bb.rejected.connect(dlg.close)
            lay.addWidget(bb)
            dlg.resize(560, 560)
            dlg._table = t
            self._doc_info_dlg = dlg
        dlg._pane = i
        self._doc_info_dialog_refresh(i)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _doc_info_dialog_refresh(self, i: int):
        dlg = getattr(self, "_doc_info_dlg", None)
        if dlg is None or getattr(dlg, "_pane", None) != i:
            return
        from PyQt6.QtWidgets import QTableWidgetItem
        st = self._doc_info_state[i]
        facts = st.get("facts") or {}
        rows = doc_info.doc_info_rows(facts, st.get("info"))
        t = dlg._table
        t.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            t.setItem(r, 0, QTableWidgetItem(k))
            t.setItem(r, 1, QTableWidgetItem(v))
        dlg.setWindowTitle(tr("문서 정보") + " — " + Path(facts.get("path") or "").name)
