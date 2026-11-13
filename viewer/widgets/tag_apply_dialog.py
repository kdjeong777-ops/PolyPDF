# -*- coding: utf-8 -*-
"""해시태그 수정 — 썸네일 여러 장에 태그 붙이고 떼기, 한영 쌍 (태그 SOT §8.7·§8.9, 261111-6·261113-9).

위: '해시태그' · [↶]·[↷] · [적용]·[해제](261113-9). 왼쪽: 현재 태그(거르기 상자·짝 표시) · 태그 추가 + 짝 낱말 · 새 태그 후보.
오른쪽: 책갈피창에서 고른 파일(없으면 지금 목록)의 썸네일(여러 장 고르기).
썸네일 그림은 배경(`ThumbWorker`), 태그 저장소에는 메인이 쓴다.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QDate, QObject, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListView,
                             QListWidget, QListWidgetItem, QPushButton, QSplitter, QVBoxLayout, QWidget)

from viewer.i18n import tr

THUMB = 128
MARK_ALL, MARK_SOME, MARK_NONE = "☑", "◐", "☐"


def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


class ThumbWorker(QObject):
    """파일 → 썸네일 QImage(배경). **창이 달라는 칸만**(`want` — 보이는 칸, 261111-15: 8,694장을 다 만들지 않는다).
    창이 닫힐 때까지 기다리며 요청을 받는다. 사진은 클라우드 전용이면 그리지 않는다(사진 보기 SOT §4.37)."""
    image = pyqtSignal(int, QImage)
    finished = pyqtSignal()

    def __init__(self, paths, box: int = THUMB):
        super().__init__()
        import threading
        self.paths, self.box = list(paths), int(box)
        self._cancel = False
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._queue = []                        # 차례대로 만들 칸 번호 — 새 요청이 앞의 것을 바꾼다(스크롤)
        self.done = set()                       # 만든(또는 못 만든) 칸
        self.made = 0                           # 검사용 — 실제로 만든 수

    def request_cancel(self):
        self._cancel = True
        self._wake.set()

    def want(self, indices):
        """이 칸들을 먼저(메인에서). 이미 만든 칸은 뺀다."""
        with self._lock:
            self._queue = [i for i in indices if 0 <= i < len(self.paths) and i not in self.done]
        self._wake.set()

    def _next(self):
        with self._lock:
            while self._queue:
                i = self._queue.pop(0)
                if i not in self.done:
                    self.done.add(i)
                    return i
            self._wake.clear()
        return None

    def run(self):
        from viewer import pacing
        try:
            while not self._cancel:
                i = self._next()
                if i is None:
                    self._wake.wait(0.5)
                    continue
                img = None
                try:
                    img = self._one(self.paths[i])
                except Exception:
                    img = None
                if img is not None and not img.isNull():
                    self.made += 1
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


class DateWorker(QObject):
    """파일 → 'YYYY-MM-DD'(배경, 261111-19) — 사진은 사진 정보 색인의 촬영일(없으면 파일 날짜), PDF 는 파일 수정 날짜.
    책갈피창 날짜와 같은 기준(사진 보기 SOT §4.37). 사진 머리를 새로 읽지 않는다(8,694장 — 색인과 stat 만)."""
    ready = pyqtSignal(dict)
    finished = pyqtSignal()

    def __init__(self, paths):
        super().__init__()
        self.paths = list(paths)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        import time as _t
        from viewer import pacing
        out = {}
        try:
            taken = {}
            try:
                from viewer import photo_index
                con = photo_index.connect_read()
                try:
                    for k, d in con.execute("SELECT key, taken FROM photos WHERE zip IS NULL AND taken IS NOT NULL AND taken<>''"):
                        taken[k] = str(d)[:10]
                finally:
                    con.close()
            except Exception:
                pass
            for i, p in enumerate(self.paths):
                if self._cancel:
                    break
                k = _norm(p)
                d = taken.get(k)
                if not d:
                    try:
                        d = _t.strftime("%Y-%m-%d", _t.localtime(os.stat(p).st_mtime))
                    except (OSError, ValueError, OverflowError):
                        d = ""
                out[k] = d
                if i % 500 == 499:
                    pacing.pace(self)
        finally:
            self.ready.emit(out)
            self.finished.emit()


class TagApplyDialog(QDialog):
    changed = pyqtSignal()                      # 태그를 바꿨다 — 검사·부른 쪽

    SORT_NAME, SORT_REG = "name", "reg"

    def __init__(self, store, paths, selected=(), parent=None, show_candidates: bool = False, keep=None, state=None):
        super().__init__(parent)
        self.setWindowTitle(tr("해시태그 수정"))           # 261113-9(태그 SOT §8.7): 종전 '해시태그 넣기'
        # 261111-17: 최대화 단추 + 크기·최대화·정렬을 기억(`state` — 부른 쪽이 설정 'tag_apply_window' 에)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        st0 = dict(state or {})
        try:
            self.resize(max(700, int(st0.get("w", 1100))), max(480, int(st0.get("h", 700))))
        except (TypeError, ValueError):
            self.resize(1100, 700)
        self._start_max = bool(st0.get("max"))
        self._sort = st0.get("sort") if st0.get("sort") in (self.SORT_NAME, self.SORT_REG) else self.SORT_NAME
        self.state_out = dict(st0)
        self._reg = None                        # 태그 → 등록 차례(처음 붙은 차례) — 등록순 정렬 때 한 번 센다
        self._store = store
        self._paths = [str(p) for p in paths]
        self._undo, self._redo = [], []
        self._keep = keep if keep is not None else []
        self._added = []                        # 태그 추가로 넣고 아직 붙이지 않은 태그
        self._mode = "tags"                     # 261111-20: 지금 쓰는 목록 — "tags"(현재 태그) | "cand"(새 태그 후보)
        self._has = {}                          # 261111-18: 태그(소문자) → 체크(True = 있는 것, False = 없는 것) — 기본 체크
        self._dates = None                      # 261111-19: 경로(정규화) → 'YYYY-MM-DD' — 배경에서 읽는다
        from viewer.tag_store import load_candidates
        self._cand = load_candidates()

        v = QVBoxLayout(self)
        # 261113-9(태그 SOT §8.7, 사용자 지시): 위 줄 = '해시태그' · [↶][↷](꾸밈 도구 줄과 같은 그림 글자) · 조금 띄워 [적용][해제]
        top = QHBoxLayout()
        lbl_tag = QLabel(tr("해시태그"))
        f0 = lbl_tag.font()
        f0.setBold(True)
        lbl_tag.setFont(f0)
        top.addWidget(lbl_tag)
        self.btn_undo = QPushButton("↶")
        self.btn_redo = QPushButton("↷")
        for b, tip in ((self.btn_undo, tr("되돌리기 (Ctrl+Z)")), (self.btn_redo, tr("다시 실행 (Ctrl+Y)"))):
            b.setFixedWidth(28)
            b.setToolTip(tip)
            b.setAccessibleName(tip)
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo.clicked.connect(self.redo)
        top.addWidget(self.btn_undo)
        top.addWidget(self.btn_redo)
        top.addSpacing(16)
        self.btn_apply = QPushButton(tr("적용"))
        self.btn_apply.setToolTip(tr("고른 태그를 고른 파일 모두에 붙입니다"))
        self.btn_clear = QPushButton(tr("해제"))
        self.btn_clear.setToolTip(tr("고른 태그를 고른 파일 모두에서 뗍니다 — 자동 태그는 다시 붙지 않게 거절로 기록"))
        self.btn_apply.clicked.connect(lambda: self.apply_tags(True))
        self.btn_clear.clicked.connect(lambda: self.apply_tags(False))
        top.addWidget(self.btn_apply)
        top.addWidget(self.btn_clear)
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
        # 261111-16: 목록 위 검색창(글자를 담은 태그만 — 대소문자 무시, 새 태그 후보도 같이)·정렬 [이름순|등록순]
        fr = QHBoxLayout()
        self.ed_find = QLineEdit()
        self.ed_find.setPlaceholderText(tr("태그 찾기"))
        self.ed_find.setClearButtonEnabled(True)
        self.btn_find_add = QPushButton(tr("추가"))
        self.btn_find_add.setToolTip(tr("찾는 글자를 새 태그로 넣습니다(목록에 없을 때)"))
        self.btn_find_add.clicked.connect(self._find_add)
        self.cmb_sort = QComboBox()
        self.cmb_sort.addItem(tr("이름순"), self.SORT_NAME)
        self.cmb_sort.addItem(tr("등록순"), self.SORT_REG)
        self.cmb_sort.setCurrentIndex(0 if self._sort == self.SORT_NAME else 1)
        fr.addWidget(self.ed_find, 1)
        fr.addWidget(self.btn_find_add)
        fr.addWidget(self.cmb_sort)
        g1l.addLayout(fr)
        self.lst_tags = QListWidget()
        self.lst_tags.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        g1l.addWidget(self.lst_tags)
        lv.addWidget(g1, 3)
        g2 = QGroupBox(tr("태그 추가"))
        g2v = QVBoxLayout(g2)
        g2l = QHBoxLayout()
        self.ed_new = QLineEdit()
        self.ed_new.setPlaceholderText(tr("새 태그 이름"))
        self.btn_add = QPushButton(tr("추가"))
        self.btn_add.clicked.connect(self._add_tag)
        self.ed_new.returnPressed.connect(self._add_tag)
        g2l.addWidget(self.ed_new, 1)
        g2l.addWidget(self.btn_add)
        g2v.addLayout(g2l)
        # 261113-9(태그 SOT §8.9): 한영 쌍 — 짝 낱말(추천이 펼쳐지는 콤보, 고쳐 쓸 수 있다) + [잇기]·[끊기]
        pr = QHBoxLayout()
        pr.addWidget(QLabel(tr("짝 낱말")))
        self.cmb_pair = QComboBox()
        self.cmb_pair.setEditable(True)
        self.cmb_pair.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.cmb_pair.lineEdit().setPlaceholderText(tr("한글이면 영어, 영어면 한글"))
        self.cmb_pair.setToolTip(tr("고른 태그와 쌍으로 이을 낱말 — #태그 거르기가 짝도 함께 찾습니다"))
        self.btn_link = QPushButton(tr("잇기"))
        self.btn_unlink = QPushButton(tr("끊기"))
        self.btn_link.clicked.connect(self._link_pair)
        self.btn_unlink.clicked.connect(self._unlink_pair)
        pr.addWidget(self.cmb_pair, 1)
        pr.addWidget(self.btn_link)
        pr.addWidget(self.btn_unlink)
        g2v.addLayout(pr)
        lv.addWidget(g2)
        self._pair_for = None                   # 짝 줄이 지금 가리키는 태그
        self._pair_req = 0
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
        sp.addWidget(left)

        self.lst_files = QListWidget()
        self.lst_files.setViewMode(QListView.ViewMode.IconMode)
        self.lst_files.setIconSize(QSize(THUMB, THUMB))
        self.lst_files.setGridSize(QSize(THUMB + 28, THUMB + 40))
        self.lst_files.setResizeMode(QListView.ResizeMode.Adjust)
        self.lst_files.setMovement(QListView.Movement.Static)
        self.lst_files.setWordWrap(True)
        # 261111-15: 칸 크기는 칸마다 고정(그리드)하고 처음부터 빈 그림 자리를 둔다 — 종전 setUniformItemSizes 는
        #   첫 줄(아직 그림 없음)로 칸 높이를 재 글자 높이만큼만 잡혀 썸네일이 위 20px 띠로 잘렸다(사용자 보고)
        self.lst_files.setUniformItemSizes(True)
        self.lst_files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        blank = QPixmap(THUMB, THUMB)
        blank.fill(Qt.GlobalColor.transparent)
        self._blank = QIcon(blank)
        cell = QSize(THUMB + 28, THUMB + 40)
        want = {_norm(p) for p in selected or ()}
        self.lst_files.setUpdatesEnabled(False)
        for p in self._paths:
            it = QListWidgetItem(self._blank, os.path.basename(p))
            it.setToolTip(p)
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            it.setSizeHint(cell)
            self.lst_files.addItem(it)
            if _norm(p) in want:
                it.setSelected(True)
        self.lst_files.setUpdatesEnabled(True)
        # 261111-19: 오른쪽 위 '기간' — 사진은 촬영일(없으면 파일 날짜), PDF 는 파일 수정 날짜(책갈피창 날짜와 같은 기준)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        pb = QHBoxLayout()
        pb.addWidget(QLabel(tr("기간")))
        self.cmb_period = QComboBox()
        for key, label in (("all", tr("전체")), ("today", tr("오늘")), ("7", tr("최근 7일")), ("30", tr("최근 30일")),
                           ("year", tr("올해")), ("custom", tr("직접"))):
            self.cmb_period.addItem(label, key)
        self.d_from, self.d_to = QDateEdit(), QDateEdit()
        for de in (self.d_from, self.d_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy-MM-dd")
            de.setDate(QDate.currentDate())
            de.setVisible(False)
        self.d_from.setDate(QDate.currentDate().addMonths(-1))
        self.lbl_dash = QLabel("~")
        self.lbl_dash.setVisible(False)
        self.lbl_dates = QLabel(tr("날짜 읽는 중…"))
        self.cmb_period.setEnabled(False)
        pb.addWidget(self.cmb_period)
        pb.addWidget(self.d_from)
        pb.addWidget(self.lbl_dash)
        pb.addWidget(self.d_to)
        pb.addWidget(self.lbl_dates)
        pb.addStretch(1)
        rv.addLayout(pb)
        rv.addWidget(self.lst_files, 1)
        sp.addWidget(right)
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
        self.ed_find.textChanged.connect(self._on_find)
        self.ed_find.returnPressed.connect(self._find_add)
        self.cmb_sort.currentIndexChanged.connect(self._on_sort)
        # 261111-18: 태그를 고르면 오른쪽을 거른다(체크 = 있는 것, 해제 = 없는 것), 후보 ↔ 현재 태그는 한쪽만 활성
        self.lst_tags.itemSelectionChanged.connect(lambda: self._on_list_pick("tags"))
        self.lst_tags.itemSelectionChanged.connect(self._refresh_pair)       # 261113-9(§8.9)
        self.ed_new.textChanged.connect(self._refresh_pair)
        self.cmb_pair.editTextChanged.connect(lambda _t: self.btn_link.setEnabled(bool(self._pair_target() and _t.strip())))
        self.lst_tags.itemChanged.connect(self._on_tag_check)
        self.lst_cand.itemSelectionChanged.connect(lambda: self._on_list_pick("cand"))
        self.cmb_period.currentIndexChanged.connect(self._on_period)
        self.d_from.dateChanged.connect(lambda *_: self._apply_filter())
        self.d_to.dateChanged.connect(lambda *_: self._apply_filter())
        self._fill_tags()
        self._fill_cand()
        self._refresh_marks()
        self._start_thumbs()
        self._start_dates()
        self._refresh_pair()

    # ── 목록 ──────────────────────────────────────────────
    def selected_paths(self) -> list:
        """고른 파일 — 거르기로 숨은 칸은 빼고(보이는 것만 적용·해제한다)."""
        lw = self.lst_files
        return [it.data(Qt.ItemDataRole.UserRole) for it in lw.selectedItems() if not lw.isRowHidden(lw.row(it))]

    # ── 거르기(261111-18·-19·-20) ──────────────────────────
    def _on_list_pick(self, which: str):
        """한쪽 목록에서 고르면 그쪽이 활성 — 다른 쪽은 고름을 풀고 흐리게(사용자 지시 '새태그 후보 작업시 현재 태그 리스트의 활성화 해제. 그 반대도')."""
        src = self.lst_tags if which == "tags" else self.lst_cand
        if not src.selectedItems():
            if which == self._mode:
                self._apply_filter()
            return
        other = self.lst_cand if which == "tags" else self.lst_tags
        self._mode = which
        other.blockSignals(True)
        other.clearSelection()
        other.blockSignals(False)
        other.setStyleSheet("QListWidget{color: palette(placeholder-text);}")
        src.setStyleSheet("")
        self._apply_filter(select_cand=(which == "cand"))

    def _on_tag_check(self, it):
        t = it.data(Qt.ItemDataRole.UserRole)
        if t:
            self._has[t.lower()] = it.checkState() == Qt.CheckState.Checked
            if it.isSelected():
                self._apply_filter()

    def _cand_files(self, tags) -> set:
        out = set()
        for t in tags:
            for f in ((self._cand.get("cand") or {}).get(t) or {}).get("files", []):
                out.add(_norm(f))
        return out

    def _period(self):
        """(시작, 끝) 'YYYY-MM-DD' 또는 None(전체)."""
        import datetime as _dt
        key = self.cmb_period.currentData()
        today = _dt.date.today()
        if key == "today":
            return today.isoformat(), today.isoformat()
        if key in ("7", "30"):
            return (today - _dt.timedelta(days=int(key) - 1)).isoformat(), today.isoformat()
        if key == "year":
            return "%04d-01-01" % today.year, today.isoformat()
        if key == "custom":
            a, b = self.d_from.date().toString("yyyy-MM-dd"), self.d_to.date().toString("yyyy-MM-dd")
            return (a, b) if a <= b else (b, a)
        return None

    def _on_period(self, *_a):
        custom = self.cmb_period.currentData() == "custom"
        for w in (self.d_from, self.lbl_dash, self.d_to):
            w.setVisible(custom)
        self._apply_filter()

    def _apply_filter(self, select_cand: bool = False):
        """오른쪽 칸을 거른다 — 현재 태그 줄을 골랐으면 태그마다 (체크 = 있는 것 · 해제 = 없는 것) 모두 만족, 후보를 골랐으면
        그 후보의 근거 파일만(모두 고른 채로), 그리고 기간. 고른 것이 없으면 전체."""
        lw = self.lst_files
        if self._mode == "cand" and self.lst_cand.selectedItems():
            keys = self._cand_files([it.data(Qt.ItemDataRole.UserRole) for it in self.lst_cand.selectedItems()])
            conds = None
        else:
            keys = None
            conds = [(it.data(Qt.ItemDataRole.UserRole).lower(), it.checkState() == Qt.CheckState.Checked)
                     for it in self.lst_tags.selectedItems()]
        per = self._period()
        dates = self._dates or {}
        lw.setUpdatesEnabled(False)
        try:
            for i in range(lw.count()):
                it = lw.item(i)
                p = it.data(Qt.ItemDataRole.UserRole)
                show = True
                if keys is not None:
                    show = _norm(p) in keys
                elif conds:
                    have = {t.lower() for t in self.shown_tags(p)}
                    show = all((t in have) == want for t, want in conds)
                if show and per is not None:
                    d = dates.get(_norm(p), "")
                    show = bool(d) and per[0] <= d <= per[1]
                lw.setRowHidden(i, not show)
                if not show and it.isSelected():
                    it.setSelected(False)
                elif show and select_cand and keys is not None:
                    it.setSelected(True)
        finally:
            lw.setUpdatesEnabled(True)
        self._refresh_marks()
        w = self.__dict__.get("_vis_timer")
        if w is not None:
            w.start()

    # ── 한영 쌍(261113-9, 태그 SOT §8.9) ────────────────────
    def _pair_target(self) -> str:
        """짝 줄이 다루는 태그 — '태그 추가' 칸에 쓴 글, 아니면 현재 태그에서 하나만 고른 줄."""
        t = self.ed_new.text().strip().lstrip("#").strip()
        if t:
            return t
        sel = self.lst_tags.selectedItems()
        return sel[0].data(Qt.ItemDataRole.UserRole) if len(sel) == 1 else ""

    def _refresh_pair(self, *_a):
        from viewer.tag_pairs import shared
        t = self._pair_target()
        mate = shared().partner(t) if t else None
        self.btn_unlink.setEnabled(bool(mate))
        if t == self._pair_for:
            self.btn_link.setEnabled(bool(t and self.cmb_pair.currentText().strip()))
            return
        self._pair_for = t
        self.cmb_pair.blockSignals(True)
        self.cmb_pair.clear()
        self.cmb_pair.setEditText(mate or "")
        self.cmb_pair.blockSignals(False)
        self.cmb_pair.setEnabled(bool(t))
        self.btn_link.setEnabled(bool(t and mate))
        if t:
            from viewer.tag_pairs import PairSuggestWorker
            from viewer.workers import run_in_thread
            self._pair_req += 1
            rid = self._pair_req
            w = PairSuggestWorker(t)
            w.found.connect(lambda tag, words, _r=rid: self._on_pair_words(_r, tag, words))
            self._pair_worker = w
            run_in_thread(w, self._keep)

    def _on_pair_words(self, rid: int, tag: str, words: list):
        if rid != self._pair_req or tag != self._pair_for:
            return                                  # 앞 요청 — 버린다
        cur = self.cmb_pair.currentText()
        self.cmb_pair.blockSignals(True)
        self.cmb_pair.clear()
        self.cmb_pair.addItems(words)
        self.cmb_pair.setEditText(cur or (words[0] if words else ""))
        self.cmb_pair.blockSignals(False)
        self.btn_link.setEnabled(bool(self.cmb_pair.currentText().strip()))
        self.pair_words = list(words)               # 검사용

    def _link_pair(self):
        from viewer.tag_pairs import shared
        t, w = self._pair_target(), self.cmb_pair.currentText().strip().lstrip("#").strip()
        if not t or not w:
            return
        if shared().link(t, w):
            self._fill_tags()
            self._refresh_pair()

    def _unlink_pair(self):
        from viewer.tag_pairs import shared
        t = self._pair_target()
        if t and shared().unlink(t):
            self._pair_for = None
            self._fill_tags()
            self._refresh_pair()

    def _start_dates(self):
        from viewer.workers import run_in_thread
        self._dater = DateWorker(self._paths)
        self._dater.ready.connect(self._on_dates)
        run_in_thread(self._dater, self._keep)

    def _on_dates(self, d: dict):
        self._dates = d
        self.cmb_period.setEnabled(True)
        self.lbl_dates.setText("")
        if self.cmb_period.currentData() != "all":
            self._apply_filter()

    def shown_tags(self, p) -> list:
        """이 창에서 다루는 태그 — 사진 기본 정보(머리에서 만든 촬영일·지역·장비·스크린샷 — `meta` 부분)는 뺀다(261111-16,
        태그 SOT §8.7). 같은 이름을 직접 붙였으면 남긴다."""
        st = self._store
        meta = {t.lower() for t in st.get_auto_part(p, "meta")} - {t.lower() for t in st.get_manual(p)}
        return [t for t in st.get(p) if t.lower() not in meta]

    def _reg_order(self) -> dict:
        """태그 → 등록 차례 — 태그 저장소에 기록된 차례대로 처음 나온 자리(앞서 붙은 태그 먼저)."""
        if self._reg is None:
            reg = {}
            for k in list(self._store._data.keys()):
                for t in self._store.get(k):
                    reg.setdefault(t.lower(), len(reg))
            self._reg = reg
        return self._reg

    def _find_text(self) -> str:
        return self.ed_find.text().strip().lstrip("#").lower()

    def _fill_tags(self):
        keep = {it.data(Qt.ItemDataRole.UserRole) for it in self.lst_tags.selectedItems()}
        counts = {}
        for p in self._paths:
            for t in self.shown_tags(p):
                counts[t] = counts.get(t, 0) + 1
        for t in self._added:
            counts.setdefault(t, 0)
        q = self._find_text()
        if q:
            counts = {t: n for t, n in counts.items() if q in t.lower()}
        if self._sort == self.SORT_REG:
            reg = self._reg_order()
            order = sorted(counts, key=lambda t: (reg.get(t.lower(), len(reg)), t.lower()))
        else:
            order = sorted(counts, key=lambda t: t.lower())
        self.lst_tags.blockSignals(True)
        self.lst_tags.clear()
        from viewer.tag_pairs import shared as _pairs
        pt = _pairs()
        for t in order:
            mate = pt.partner(t)                        # 261113-9(§8.9): 짝이 있으면 '태그 ⇄ 짝'
            it = QListWidgetItem(("#%s ⇄ %s  (%d)" % (t, mate, counts[t])) if mate else ("#%s  (%d)" % (t, counts[t])))
            it.setData(Qt.ItemDataRole.UserRole, t)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if self._has.get(t.lower(), True) else Qt.CheckState.Unchecked)
            it.setToolTip(tr("체크하면 이 태그가 있는 파일, 체크를 풀면 없는 파일을 오른쪽에 보입니다(줄을 고를 때)"))
            self.lst_tags.addItem(it)
            if t in keep:
                it.setSelected(True)
        self.lst_tags.blockSignals(False)

    def _fill_cand(self):
        self.lst_cand.blockSignals(True)
        self.lst_cand.clear()
        self.lst_cand.blockSignals(False)
        # 261111-20 덧붙임(사용자 지시 '책갈피창 리스트에 있는 것을 기반으로 후보를 만들어야해. 만일 없으면 안만들어도 되'):
        #   후보마다 근거 파일 중 **지금 목록에 있는 것**만 세고, 하나도 없으면 늘어놓지 않는다 — 종전 개수는 모든 폴더에서
        #   적립한 횟수라 오른쪽에 보이는 근거 파일 수와 맞지 않았다
        in_list = {_norm(p) for p in self._paths}
        cand = []
        for t, info in (self._cand.get("cand") or {}).items():
            here = [f for f in (info.get("files") or []) if _norm(f) in in_list]
            if here:
                cand.append((t, here))
        cand.sort(key=lambda kv: (-len(kv[1]), kv[0].lower()))
        q = self._find_text()
        if q:
            cand = [(t, h) for t, h in cand if q in t.lower()]
        for t, here in cand[:200]:
            it = QListWidgetItem(tr("#{tag}  ({n}건)").format(tag=t, n=len(here)))
            it.setData(Qt.ItemDataRole.UserRole, t)
            it.setToolTip("\n".join(here))
            self.lst_cand.addItem(it)

    def _refresh_marks(self):
        n = len(self.selected_paths())
        vis = sum(1 for i in range(self.lst_files.count()) if not self.lst_files.isRowHidden(i))
        self.lbl_sel.setText(tr("고른 파일 {n}개 / 보이는 {v}개 / 모두 {m}개").format(n=n, v=vis, m=len(self._paths)))
        self.btn_undo.setEnabled(bool(self._undo))
        self.btn_redo.setEnabled(bool(self._redo))
        q = self._find_text()
        known = {self.lst_tags.item(i).data(Qt.ItemDataRole.UserRole).lower() for i in range(self.lst_tags.count())}
        self.btn_find_add.setEnabled(bool(q) and q not in known)

    def _on_find(self, *_a):
        self._fill_tags()
        self._fill_cand()
        self._refresh_marks()

    def _on_sort(self, *_a):
        self._sort = self.cmb_sort.currentData() or self.SORT_NAME
        self._fill_tags()
        self._refresh_marks()

    def _find_add(self):
        """찾는 글자를 새 태그로(목록에 없을 때) — 태그 추가와 같은 길."""
        if not self.btn_find_add.isEnabled():
            return
        self.ed_new.setText(self.ed_find.text().strip().lstrip("#"))
        self._add_tag()

    def _add_tag(self):
        from viewer.tag_store import normalize_tags
        ts = normalize_tags([self.ed_new.text()])
        if not ts:
            return
        t = ts[0]
        if t.lower() not in {x.lower() for x in self._added}:
            self._added.append(t)
        self._has.setdefault(t.lower(), False)         # 새 태그는 '없는 것' 으로 — 고르면 아직 안 붙은 파일이 보인다(261111-18)
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
        if self._mode == "cand" and self.g3.isChecked():         # 261111-20: 활성 목록 한쪽에서만
            out = [it.data(Qt.ItemDataRole.UserRole) for it in self.lst_cand.selectedItems()]
        else:
            out = [it.data(Qt.ItemDataRole.UserRole) for it in self.lst_tags.selectedItems()]
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
                    meta = {m.lower() for m in st.get_auto_part(p, "meta")}      # 사진 기본 정보는 이 창이 건드리지 않는다(261111-16)
                    auto = [a for a in st.get_auto(p) if a.lower() in tl and a.lower() not in meta]
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
            self._apply_filter()                 # 태그가 바뀌면 거르기 결과도(있는 것/없는 것)
        self._refresh_marks()
        return len(changed)

    def _restore(self, snap: dict):
        with self._store.bulk():
            for p, rec in snap.items():
                self._store.put_record(p, rec)
        self._fill_tags()
        self.changed.emit()
        self._apply_filter()

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
        from PyQt6.QtCore import QTimer
        self._thumber = ThumbWorker(self._paths)
        self._thumber.image.connect(self._on_thumb)
        run_in_thread(self._thumber, self._keep)
        self._vis_timer = QTimer(self)                 # 스크롤·크기 바꿈을 모아 보이는 칸을 달라고 한다(261111-15)
        self._vis_timer.setSingleShot(True)
        self._vis_timer.setInterval(60)
        self._vis_timer.timeout.connect(self._want_visible)
        self.lst_files.verticalScrollBar().valueChanged.connect(lambda *_: self._vis_timer.start())
        self.lst_files.viewport().installEventFilter(self)
        self._vis_timer.start()

    def visible_rows(self) -> list:
        """지금 보이는 칸 번호(+ 다음 한 화면) — 아이콘 보기는 칸이 차례대로 놓인다."""
        lw = self.lst_files
        n = lw.count()
        if not n:
            return []
        vp = lw.viewport().rect()
        first = lw.indexAt(vp.topLeft() + QPoint(4, 4)).row()
        last = -1
        for pt in (vp.bottomRight() - QPoint(4, 4), QPoint(4, vp.bottom() - 4)):
            last = max(last, lw.indexAt(pt).row())
        first = max(0, first if first >= 0 else 0)
        if last < 0:
            last = n - 1 if lw.verticalScrollBar().maximum() == 0 else min(n - 1, first + 200)
        span = max(1, last - first + 1)
        out, i = [], first
        while i < n and len(out) < 2 * span:                 # 거르기로 숨은 칸은 건너뛴다(261111-18)
            if not lw.isRowHidden(i):
                out.append(i)
            i += 1
        return out

    def _want_visible(self):
        w = self.__dict__.get("_thumber")
        if w is not None:
            w.want(self.visible_rows())

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if obj is self.lst_files.viewport() and ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._vis_timer.start()
        return super().eventFilter(obj, ev)

    def _on_thumb(self, i: int, img: QImage):
        it = self.lst_files.item(i)
        if it is not None:
            it.setIcon(QIcon(QPixmap.fromImage(img)))

    def showEvent(self, e):
        super().showEvent(e)
        if self._start_max:
            self._start_max = False
            self.showMaximized()

    def done(self, r):
        self.state_out = {"max": bool(self.isMaximized()), "sort": self._sort}
        g = self.normalGeometry() if self.isMaximized() else self.geometry()
        self.state_out.update({"w": int(g.width()), "h": int(g.height())})
        for name in ("_thumber", "_dater"):
            w = self.__dict__.get(name)
            if w is not None:
                w.request_cancel()
        super().done(r)
