# -*- coding: utf-8 -*-
"""해시태그 넣기 — 썸네일 여러 장에 태그 붙이고 떼기 (태그 SOT §8.7, 261111-6).

왼쪽: 현재 태그(고른 파일 기준 ☑ 모두 / ◐ 일부 / ☐ 없음) · 태그 추가 · 새 태그 후보 · [적용]·[해제]
오른쪽: 지금 책갈피창 목록의 썸네일(여러 장 고르기). 위: [되돌리기]·[다시 실행].
썸네일 그림은 배경(`ThumbWorker`), 태그 저장소에는 메인이 쓴다.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListView,
                             QListWidget, QListWidgetItem, QPushButton, QSplitter, QVBoxLayout, QWidget)

from viewer.i18n import tr

THUMB = 128
MARK_ALL, MARK_SOME, MARK_NONE = "☑", "◐", "☐"


def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


class ThumbWorker(QObject):
    """파일 → 썸네일 QImage(배경). 사진은 클라우드 전용이면 그리지 않는다(사진 보기 SOT §4.37)."""
    image = pyqtSignal(int, QImage)
    finished = pyqtSignal()

    def __init__(self, paths, box: int = THUMB):
        super().__init__()
        self.paths, self.box = list(paths), int(box)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        from viewer import pacing
        try:
            for i, p in enumerate(self.paths):
                if self._cancel:
                    break
                img = None
                try:
                    img = self._one(p)
                except Exception:
                    img = None
                if img is not None and not img.isNull():
                    self.image.emit(i, img)
                pacing.pace(self)
        finally:
            self.finished.emit()

    def _one(self, p):
        if str(p).lower().endswith(".pdf"):
            import fitz
            with fitz.open(str(p)) as d:
                if d.needs_pass or d.page_count < 1:
                    return None
                pg = d[0]
                z = self.box / max(1.0, max(pg.rect.width, pg.rect.height))
                pm = pg.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
                return QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format.Format_RGB888).copy()
        from viewer import photo_io
        if photo_io.cloud_only(os.stat(str(p))):
            return None
        from viewer.widgets.photo_strip import load_thumb
        return load_thumb(str(p), self.box)


class TagApplyDialog(QDialog):
    changed = pyqtSignal()                      # 태그를 바꿨다 — 검사·부른 쪽

    def __init__(self, store, paths, selected=(), parent=None, show_candidates: bool = False, keep=None):
        super().__init__(parent)
        self.setWindowTitle(tr("해시태그 넣기"))
        self.resize(1100, 700)
        self._store = store
        self._paths = [str(p) for p in paths]
        self._undo, self._redo = [], []
        self._keep = keep if keep is not None else []
        self._added = []                        # 태그 추가로 넣고 아직 붙이지 않은 태그
        from viewer.tag_store import load_candidates
        self._cand = load_candidates()

        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.btn_undo = QPushButton(tr("되돌리기"))
        self.btn_redo = QPushButton(tr("다시 실행"))
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo.clicked.connect(self.redo)
        top.addWidget(self.btn_undo)
        top.addWidget(self.btn_redo)
        top.addStretch(1)
        self.lbl_sel = QLabel()
        top.addWidget(self.lbl_sel)
        v.addLayout(top)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self.redo)

        sp = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        g1 = QGroupBox(tr("현재 태그"))
        g1l = QVBoxLayout(g1)
        self.lst_tags = QListWidget()
        self.lst_tags.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        g1l.addWidget(self.lst_tags)
        lv.addWidget(g1, 3)
        g2 = QGroupBox(tr("태그 추가"))
        g2l = QHBoxLayout(g2)
        self.ed_new = QLineEdit()
        self.ed_new.setPlaceholderText(tr("새 태그 이름"))
        self.btn_add = QPushButton(tr("추가"))
        self.btn_add.clicked.connect(self._add_tag)
        self.ed_new.returnPressed.connect(self._add_tag)
        g2l.addWidget(self.ed_new, 1)
        g2l.addWidget(self.btn_add)
        lv.addWidget(g2)
        self.g3 = QGroupBox(tr("새 태그 후보"))
        self.g3.setCheckable(True)                # 접고 펴기
        g3l = QVBoxLayout(self.g3)
        self.lst_cand = QListWidget()
        self.lst_cand.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        g3l.addWidget(self.lst_cand)
        self.btn_dismiss = QPushButton(tr("고른 후보 무시"))
        self.btn_dismiss.setToolTip(tr("전역 기록 — 다시 적립되지 않습니다"))
        self.btn_dismiss.clicked.connect(self._dismiss)
        g3l.addWidget(self.btn_dismiss)
        self.g3.toggled.connect(lambda on: (self.lst_cand.setVisible(on), self.btn_dismiss.setVisible(on)))
        self.g3.setChecked(bool(show_candidates))
        self.lst_cand.setVisible(bool(show_candidates))
        self.btn_dismiss.setVisible(bool(show_candidates))
        lv.addWidget(self.g3, 2)
        hb = QHBoxLayout()
        self.btn_apply = QPushButton(tr("적용"))
        self.btn_apply.setToolTip(tr("고른 태그를 고른 파일 모두에 붙입니다"))
        self.btn_clear = QPushButton(tr("해제"))
        self.btn_clear.setToolTip(tr("고른 태그를 고른 파일 모두에서 뗍니다 — 자동 태그는 다시 붙지 않게 거절로 기록"))
        self.btn_apply.clicked.connect(lambda: self.apply_tags(True))
        self.btn_clear.clicked.connect(lambda: self.apply_tags(False))
        hb.addWidget(self.btn_apply)
        hb.addWidget(self.btn_clear)
        lv.addLayout(hb)
        sp.addWidget(left)

        self.lst_files = QListWidget()
        self.lst_files.setViewMode(QListView.ViewMode.IconMode)
        self.lst_files.setIconSize(QSize(THUMB, THUMB))
        self.lst_files.setGridSize(QSize(THUMB + 28, THUMB + 40))
        self.lst_files.setResizeMode(QListView.ResizeMode.Adjust)
        self.lst_files.setMovement(QListView.Movement.Static)
        self.lst_files.setWordWrap(True)
        self.lst_files.setUniformItemSizes(True)
        self.lst_files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        want = {_norm(p) for p in selected or ()}
        for p in self._paths:
            it = QListWidgetItem(os.path.basename(p))
            it.setToolTip(p)
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.lst_files.addItem(it)
            if _norm(p) in want:
                it.setSelected(True)
        sp.addWidget(self.lst_files)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        sp.setSizes([320, 780])
        v.addWidget(sp, 1)
        bot = QHBoxLayout()
        bot.addStretch(1)
        b_close = QPushButton(tr("닫기"))
        b_close.clicked.connect(self.accept)
        bot.addWidget(b_close)
        v.addLayout(bot)

        self.lst_files.itemSelectionChanged.connect(self._refresh_marks)
        self._fill_tags()
        self._fill_cand()
        self._refresh_marks()
        self._start_thumbs()

    # ── 목록 ──────────────────────────────────────────────
    def selected_paths(self) -> list:
        return [it.data(Qt.ItemDataRole.UserRole) for it in self.lst_files.selectedItems()]

    def _fill_tags(self):
        keep = {it.data(Qt.ItemDataRole.UserRole) for it in self.lst_tags.selectedItems()}
        counts = {}
        for p in self._paths:
            for t in self._store.get(p):
                counts[t] = counts.get(t, 0) + 1
        for t in self._added:
            counts.setdefault(t, 0)
        self.lst_tags.blockSignals(True)
        self.lst_tags.clear()
        for t in sorted(counts, key=lambda t: (-counts[t], t.lower())):
            it = QListWidgetItem("#" + t)
            it.setData(Qt.ItemDataRole.UserRole, t)
            self.lst_tags.addItem(it)
            if t in keep:
                it.setSelected(True)
        self.lst_tags.blockSignals(False)

    def _fill_cand(self):
        self.lst_cand.clear()
        cand = sorted((self._cand.get("cand") or {}).items(), key=lambda kv: -int(kv[1].get("n", 0)))
        for t, info in cand[:200]:
            it = QListWidgetItem(tr("#{tag}  ({n}건)").format(tag=t, n=int(info.get("n", 0))))
            it.setData(Qt.ItemDataRole.UserRole, t)
            it.setToolTip("\n".join(info.get("files", [])))
            self.lst_cand.addItem(it)

    def _refresh_marks(self):
        sel = self.selected_paths()
        n = len(sel)
        self.lbl_sel.setText(tr("고른 파일 {n}개 / 모두 {m}개").format(n=n, m=len(self._paths)))
        have = {}
        for p in sel:
            for t in {x.lower() for x in self._store.get(p)}:
                have[t] = have.get(t, 0) + 1
        for i in range(self.lst_tags.count()):
            it = self.lst_tags.item(i)
            t = it.data(Qt.ItemDataRole.UserRole)
            k = have.get(t.lower(), 0)
            mark = MARK_NONE if not n or not k else (MARK_ALL if k == n else MARK_SOME)
            it.setText("%s #%s%s" % (mark, t, ("  (%d/%d)" % (k, n)) if mark == MARK_SOME else ""))
        self.btn_undo.setEnabled(bool(self._undo))
        self.btn_redo.setEnabled(bool(self._redo))

    def _add_tag(self):
        from viewer.tag_store import normalize_tags
        ts = normalize_tags([self.ed_new.text()])
        if not ts:
            return
        t = ts[0]
        if t.lower() not in {x.lower() for x in self._added}:
            self._added.append(t)
        self.ed_new.clear()
        self._fill_tags()
        for i in range(self.lst_tags.count()):
            it = self.lst_tags.item(i)
            if it.data(Qt.ItemDataRole.UserRole).lower() == t.lower():
                it.setSelected(True)
        self._refresh_marks()

    def _dismiss(self):
        from viewer.tag_store import save_candidates
        for it in self.lst_cand.selectedItems():
            t = it.data(Qt.ItemDataRole.UserRole)
            self._cand["cand"].pop(t, None)
            if t not in self._cand["rejected"]:
                self._cand["rejected"].append(t)
        save_candidates(self._cand)
        self._fill_cand()

    # ── 적용·해제·되돌리기 ─────────────────────────────────
    def chosen_tags(self) -> list:
        out = [it.data(Qt.ItemDataRole.UserRole) for it in self.lst_tags.selectedItems()]
        if self.g3.isChecked():
            out += [it.data(Qt.ItemDataRole.UserRole) for it in self.lst_cand.selectedItems()]
        seen, res = set(), []
        for t in out:
            if t.lower() not in seen:
                seen.add(t.lower())
                res.append(t)
        return res

    def apply_tags(self, on: bool) -> int:
        """[적용](on) = 고른 파일 모두에 붙임 · [해제] = 모두에서 뗌(자동 태그는 거절). 바뀐 파일 수."""
        tags, files = self.chosen_tags(), self.selected_paths()
        if not tags or not files:
            return 0
        st = self._store
        before = {p: st.record(p) for p in files}
        tl = {t.lower() for t in tags}
        with st.bulk():
            for p in files:
                man = st.get_manual(p)
                if on:
                    low = {m.lower() for m in man}
                    add = [t for t in tags if t.lower() not in low]
                    rej = [r for r in st.get_rejected(p) if r.lower() in tl]
                    if rej:
                        v = st._dictify(st._key(p))
                        v["rejected"] = [r for r in (v.get("rejected") or []) if r.lower() not in tl]
                    if add:
                        st.set(p, man + add)
                    elif rej:
                        st._save()
                else:
                    keep = [m for m in man if m.lower() not in tl]
                    if keep != man:
                        st.set(p, keep)
                    auto = [a for a in st.get_auto(p) if a.lower() in tl]
                    if auto:
                        st.reject(p, auto)
        after = {p: st.record(p) for p in files}
        changed = [p for p in files if before[p] != after[p]]
        if on:                                   # 새 태그 후보였으면 기존 어휘로(후보 목록에서 뺀다)
            from viewer.tag_store import save_candidates
            hit = [t for t in tags if t in (self._cand.get("cand") or {})]
            if hit:
                for t in hit:
                    self._cand["cand"].pop(t, None)
                save_candidates(self._cand)
                self._fill_cand()
        if changed:
            self._undo.append(({p: before[p] for p in changed}, {p: after[p] for p in changed}))
            self._redo.clear()
            self._added = [t for t in self._added if t.lower() not in tl] if on else self._added
            self._fill_tags()
            self.changed.emit()
        self._refresh_marks()
        return len(changed)

    def _restore(self, snap: dict):
        with self._store.bulk():
            for p, rec in snap.items():
                self._store.put_record(p, rec)
        self._fill_tags()
        self.changed.emit()
        self._refresh_marks()

    def undo(self):
        if self._undo:
            b, a = self._undo.pop()
            self._redo.append((b, a))
            self._restore(b)

    def redo(self):
        if self._redo:
            b, a = self._redo.pop()
            self._undo.append((b, a))
            self._restore(a)

    # ── 썸네일 ───────────────────────────────────────────
    def _start_thumbs(self):
        from viewer.workers import run_in_thread
        self._thumber = ThumbWorker(self._paths)
        self._thumber.image.connect(self._on_thumb)
        run_in_thread(self._thumber, self._keep)

    def _on_thumb(self, i: int, img: QImage):
        it = self.lst_files.item(i)
        if it is not None:
            it.setIcon(QIcon(QPixmap.fromImage(img)))

    def done(self, r):
        w = self.__dict__.get("_thumber")
        if w is not None:
            w.request_cancel()
        super().done(r)
