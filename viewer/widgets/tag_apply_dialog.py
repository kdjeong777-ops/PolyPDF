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

from viewer.i18n import tr, trp

THUMB = 128
MARK_ALL, MARK_SOME, MARK_NONE = "☑", "◐", "☐"
KIND_ROLE = Qt.ItemDataRole.UserRole + 1          # 두 목록 줄의 갈래 — fmt·tag·cand(붙일 수 있는) / all·some(붙은)


class _MoveList(QListWidget):
    """두 목록 이동식(261114-2 덧붙임) — 여러 줄 고르기, 다른 목록으로 끌어 놓으면 `dropped(받은 목록)`. 줄은 옮기지 않는다(다시 채운다)."""
    dropped = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, ev):
        if isinstance(ev.source(), _MoveList) and ev.source() is not self:
            ev.setDropAction(Qt.DropAction.CopyAction)
            ev.accept()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        self.dragEnterEvent(ev)

    def dropEvent(self, ev):
        if isinstance(ev.source(), _MoveList) and ev.source() is not self:
            ev.setDropAction(Qt.DropAction.CopyAction)
            ev.accept()
            self.dropped.emit(self)
        else:
            ev.ignore()


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
        self._mode = "avail"                    # 261111-20: 지금 쓰는 목록 — "avail"(붙일 수 있는 태그) | "tags"(붙은 태그)
        self._known = None                      # 저장소의 모든 태그(한 번 센다)
        self._cand_filter = False
        self._dates = None                      # 261111-19: 경로(정규화) → 'YYYY-MM-DD' — 배경에서 읽는다
        from viewer.tag_store import load_candidates
        self._cand = load_candidates()

        v = QVBoxLayout(self)
        # 261114-13(태그 SOT §8.2): 전체 태그 계산이 도는 동안 맨 위 한 줄
        try:
            busy = parent.autotag_busy_text() if parent is not None and hasattr(parent, "autotag_busy_text") else ""
        except Exception:
            busy = ""
        self.lbl_busy = QLabel(busy)
        self.lbl_busy.setObjectName("tag_busy")
        self.lbl_busy.setStyleSheet("color:#888;")
        self.lbl_busy.setVisible(bool(busy))
        v.addWidget(self.lbl_busy)
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
        # 261114-2(태그 SOT §5.3.2): 문서 종류 바꾸기 — 고른 PDF 의 종류를 한 번에(자동 종류는 거절, 고른 종류는 직접 태그)
        from PyQt6.QtWidgets import QMenu
        from viewer.auto_tag import FORMAT_VOCAB
        self.btn_format = QPushButton(tr("문서 종류"))
        self.btn_format.setToolTip(tr("고른 PDF 의 문서 종류를 바꿉니다 — 잘못 붙은 자동 종류는 다시 붙지 않습니다"))
        fm = QMenu(self.btn_format)
        for fv in FORMAT_VOCAB:                 # 종류 이름은 태그 데이터라 번역하지 않는다(다국어 SOT §5)
            fm.addAction(fv).triggered.connect(lambda _=False, v=fv: self.set_format(v))
        fm.addSeparator()
        fm.addAction(tr("종류 없음")).triggered.connect(lambda _=False: self.set_format(None))
        self.btn_format.setMenu(fm)
        top.addWidget(self.btn_format)
        top.addStretch(1)
        self.lbl_sel = QLabel()
        top.addWidget(self.lbl_sel)
        v.addLayout(top)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self.redo)

        # 261114-2 덧붙임(태그 SOT §8.7, 사용자 지시 '좌측은 등록가능한거, 우측은 등록된거'·결정 '가로 두 목록'):
        #   [붙일 수 있는 태그] [→ ←] [붙은 태그] | 썸네일 — 두 번 누르기·끌어 놓기도 옮긴다
        sp = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        fr = QHBoxLayout()                       # 261111-16: 찾기(두 목록 모두)·[추가]·정렬
        self.ed_find = QLineEdit()
        self.ed_find.setPlaceholderText(tr("태그 찾기 · 새 태그 이름"))
        self.ed_find.setClearButtonEnabled(True)
        self.btn_find_add = QPushButton(tr("추가"))
        self.btn_find_add.setToolTip(tr("찾는 글자를 새 태그로 고른 파일에 붙입니다(목록에 없을 때)"))
        self.btn_find_add.clicked.connect(self._find_add)
        self.cmb_sort = QComboBox()
        self.cmb_sort.addItem(tr("이름순"), self.SORT_NAME)
        self.cmb_sort.addItem(tr("등록순"), self.SORT_REG)
        self.cmb_sort.setCurrentIndex(0 if self._sort == self.SORT_NAME else 1)
        fr.addWidget(self.ed_find, 1)
        fr.addWidget(self.btn_find_add)
        fr.addWidget(self.cmb_sort)
        lv.addLayout(fr)
        lists = QHBoxLayout()
        ga = QGroupBox(tr("붙일 수 있는 태그"))
        gal = QVBoxLayout(ga)
        self.lst_avail = _MoveList(self)
        self.lst_avail.setToolTip(tr("두 번 누르거나 오른쪽으로 끌면 고른 파일에 붙입니다"))
        gal.addWidget(self.lst_avail)
        self.btn_dismiss = QPushButton(tr("고른 후보 무시"))
        self.btn_dismiss.setToolTip(tr("전역 기록 — 다시 적립되지 않습니다"))
        self.btn_dismiss.clicked.connect(self._dismiss)
        gal.addWidget(self.btn_dismiss)
        lists.addWidget(ga, 1)
        mid = QVBoxLayout()
        mid.addStretch(1)
        self.btn_to = QPushButton("→")
        self.btn_from = QPushButton("←")
        for b, tip in ((self.btn_to, tr("붙이기 — 고른 태그를 고른 파일 모두에")), (self.btn_from, tr("떼기 — 고른 태그를 고른 파일 모두에서(자동 태그는 거절)"))):
            b.setFixedWidth(32)
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            mid.addWidget(b)
        self.btn_to.clicked.connect(lambda: self.apply_tags(True))
        self.btn_from.clicked.connect(lambda: self.apply_tags(False))
        mid.addStretch(1)
        lists.addLayout(mid)
        self.g_attached = QGroupBox(tr("붙은 태그"))
        gtl = QVBoxLayout(self.g_attached)
        self.lst_tags = _MoveList(self)
        self.lst_tags.setToolTip(tr("두 번 누르거나 왼쪽으로 끌면 고른 파일에서 뗍니다 — ◐ 는 일부 파일에만"))
        gtl.addWidget(self.lst_tags)
        lists.addWidget(self.g_attached, 1)
        lv.addLayout(lists, 1)
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
        lv.addLayout(pr)
        self._pair_for = None                   # 짝 줄이 지금 가리키는 태그
        self._pair_req = 0
        self._show_cand_first = bool(show_candidates)
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
        # 261114-2 덧붙임(사용자 결정 '썸네일 위 콤보'): 종전 현재 태그 줄의 거르기 상자 — 태그 [고르기 ▾] [있음|없음]
        pb.addSpacing(16)
        pb.addWidget(QLabel(tr("태그")))
        self.cmb_tagf = QComboBox()
        self.cmb_tagf.setMinimumWidth(140)
        self.cmb_has = QComboBox()
        self.cmb_has.addItem(trp("태그 거르기", "있음"))     # 문맥 — '있음/없음' 의 다른 쓰임(Yes/None)과 번역이 다르다
        self.cmb_has.addItem(trp("태그 거르기", "없음"))
        pb.addWidget(self.cmb_tagf)
        pb.addWidget(self.cmb_has)
        pb.addStretch(1)
        rv.addLayout(pb)
        rv.addWidget(self.lst_files, 1)
        sp.addWidget(right)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        sp.setSizes([600, 620])
        v.addWidget(sp, 1)
        bot = QHBoxLayout()
        bot.addStretch(1)
        b_close = QPushButton(tr("닫기"))
        b_close.clicked.connect(self.accept)
        bot.addWidget(b_close)
        v.addLayout(bot)

        self.lst_files.itemSelectionChanged.connect(self._fill_lists)
        self.ed_find.textChanged.connect(self._on_find)
        self.ed_find.textChanged.connect(self._refresh_pair)
        self.ed_find.returnPressed.connect(self._find_add)
        self.cmb_sort.currentIndexChanged.connect(self._on_sort)
        # 261111-20: 두 목록은 한쪽만 활성 · 두 번 누르기·끌어 놓기로 옮긴다(261114-2 덧붙임)
        self.lst_tags.itemSelectionChanged.connect(lambda: self._on_list_pick("tags"))
        self.lst_avail.itemSelectionChanged.connect(lambda: self._on_list_pick("avail"))
        for lw in (self.lst_tags, self.lst_avail):
            lw.itemSelectionChanged.connect(self._refresh_pair)       # 261113-9(§8.9)
            lw.dropped.connect(self._on_dropped)
        self.lst_avail.itemDoubleClicked.connect(lambda _it: self.apply_tags(True))
        self.lst_tags.itemDoubleClicked.connect(lambda _it: self.apply_tags(False))
        self.cmb_pair.editTextChanged.connect(lambda _t: self.btn_link.setEnabled(bool(self._pair_target() and _t.strip())))
        self.cmb_period.currentIndexChanged.connect(self._on_period)
        self.d_from.dateChanged.connect(lambda *_: self._apply_filter())
        self.d_to.dateChanged.connect(lambda *_: self._apply_filter())
        self.cmb_tagf.currentIndexChanged.connect(lambda *_: self._apply_filter())
        self.cmb_has.currentIndexChanged.connect(lambda *_: self._apply_filter())
        self._fill_tag_filter()
        self._fill_lists()
        self._start_thumbs()
        self._start_dates()
        self._refresh_pair()

    # ── 목록 ──────────────────────────────────────────────
    def selected_paths(self) -> list:
        """고른 파일 — 거르기로 숨은 칸은 빼고(보이는 것만 적용·해제한다)."""
        lw = self.lst_files
        return [it.data(Qt.ItemDataRole.UserRole) for it in lw.selectedItems() if not lw.isRowHidden(lw.row(it))]

    def target_paths(self) -> list:
        """'붙은 태그' 가 세는 파일 — 고른 파일, 고른 것이 없으면 보이는 파일 모두(261114-2 덧붙임)."""
        sel = self.selected_paths()
        if sel:
            return sel
        lw = self.lst_files
        return [lw.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lw.count()) if not lw.isRowHidden(i)]

    # ── 거르기(261111-19·-20, 261114-2 덧붙임: 태그 거르기는 썸네일 위 콤보) ─────────
    def _on_list_pick(self, which: str):
        """한쪽 목록에서 고르면 그쪽이 활성 — 다른 쪽은 고름을 풀고 흐리게(261111-20). 후보만 고르면 그 근거 파일을 오른쪽에."""
        src = self.lst_tags if which == "tags" else self.lst_avail
        if not src.selectedItems():
            self._refresh_marks()
            return
        other = self.lst_avail if which == "tags" else self.lst_tags
        self._mode = which
        other.blockSignals(True)
        other.clearSelection()
        other.blockSignals(False)
        other.setStyleSheet("QListWidget{color: palette(placeholder-text);}")
        src.setStyleSheet("")
        cands = self._picked_cands()
        if which == "avail" and cands:
            self._apply_filter(select_cand=True)
        elif self.__dict__.get("_cand_filter"):
            self._cand_filter = False
            self._apply_filter()
        self._refresh_marks()

    def _picked_cands(self) -> list:
        """'붙일 수 있는 태그' 에서 고른 줄이 모두 새 태그 후보면 그 태그들."""
        sel = self.lst_avail.selectedItems()
        if sel and all(it.data(KIND_ROLE) == "cand" for it in sel):
            return [it.data(Qt.ItemDataRole.UserRole) for it in sel]
        return []

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

    def _fill_tag_filter(self):
        """썸네일 위 '태그' 콤보 — 이 창 파일에 붙은 태그(261114-2 덧붙임, 종전 현재 태그 줄의 거르기 상자)."""
        cur = self.cmb_tagf.currentData()
        tags = set()
        for p in self._paths:
            tags |= set(self.shown_tags(p))
        self.cmb_tagf.blockSignals(True)
        self.cmb_tagf.clear()
        self.cmb_tagf.addItem(tr("(모두)"), "")
        for t in sorted(tags, key=str.lower):
            self.cmb_tagf.addItem("#" + t, t)
        i = self.cmb_tagf.findData(cur) if cur else 0
        self.cmb_tagf.setCurrentIndex(max(0, i))
        self.cmb_tagf.blockSignals(False)
        self.cmb_has.setEnabled(bool(self.cmb_tagf.currentData()))

    def _apply_filter(self, select_cand: bool = False):
        """오른쪽 칸을 거른다 — 새 태그 후보를 골랐으면 그 근거 파일만(모두 고른 채로), 아니면 썸네일 위 '태그' 콤보
        (있음 = 그 태그가 있는 파일 · 없음 = 없는 파일)와 기간."""
        lw = self.lst_files
        cands = self._picked_cands() if self._mode == "avail" else []
        keys = self._cand_files(cands) if cands else None
        self._cand_filter = keys is not None
        tf = self.cmb_tagf.currentData() or ""
        want = self.cmb_has.currentIndex() == 0
        self.cmb_has.setEnabled(bool(tf))
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
                elif tf:
                    have = {t.lower() for t in self.shown_tags(p)}
                    show = (tf.lower() in have) == want
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
        self._fill_lists()
        w = self.__dict__.get("_vis_timer")
        if w is not None:
            w.start()

    # ── 한영 쌍(261113-9, 태그 SOT §8.9) ────────────────────
    def _pair_target(self) -> str:
        """짝 줄이 다루는 태그 — 두 목록 중 하나만 고른 줄, 아니면 찾기 칸에 쓴 글."""
        sel = [it for it in self.lst_tags.selectedItems() + self.lst_avail.selectedItems() if it.data(Qt.ItemDataRole.UserRole)]
        if len(sel) == 1:
            return sel[0].data(Qt.ItemDataRole.UserRole)
        return self.ed_find.text().strip().lstrip("#").strip()

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

    def _order(self, tags) -> list:
        if self._sort == self.SORT_REG:
            reg = self._reg_order()
            return sorted(tags, key=lambda t: (reg.get(t.lower(), len(reg)), t.lower()))
        return sorted(tags, key=lambda t: t.lower())

    def _all_known(self) -> list:
        """저장소의 모든 태그(한 번 센다) — 날짜 꼴(사진 촬영일·PDF 날짜 속성)과 사진 기본 정보로만 쓰인 태그(지역·장비 — §5.7
        `meta`, 이 창이 다루지 않는다)는 뺀다."""
        if self.__dict__.get("_known") is None:
            import re as _re
            seen, other = {}, set()
            meta_only = set()
            st = self._store
            for k in list(st._data.keys()):
                try:
                    meta = {t.lower() for t in st.get_auto_part(k, "meta")}
                    for t in st.get(k):
                        tl = t.lower()
                        if _re.match(r"^\d{4}-\d{2}-\d{2}$", t or ""):
                            continue
                        seen.setdefault(tl, t)
                        if tl in meta and tl not in {m.lower() for m in st.get_manual(k)}:
                            meta_only.add(tl)
                        else:
                            other.add(tl)
                except Exception:
                    continue
            self._known = [t for tl, t in seen.items() if tl in other or tl not in meta_only]
        return self._known

    def _fill_lists(self):
        """두 목록을 지금 고른 파일 기준으로(261114-2 덧붙임) — 붙은 태그: `#태그  n/m`(◐ = 일부, `·#` = 자동으로만),
        붙일 수 있는 태그: 문서 종류 · 기존 태그 · 새 태그 후보(고른 파일 중 하나라도 가진 태그는 오른쪽에만)."""
        from viewer.auto_tag import FORMAT_VOCAB, PDF_ATTR_ITEMS
        from viewer.tag_pairs import shared as _pairs
        pt = _pairs()
        files = self.target_paths()
        m = len(files)
        sel_files = bool(self.selected_paths())
        self.g_attached.setTitle(tr("붙은 태그 — 고른 파일 {n}개").format(n=m) if sel_files
                                 else tr("붙은 태그 — 보이는 파일 {n}개").format(n=m))
        counts, manual = {}, {}
        for p in files:
            for t in self.shown_tags(p):
                counts[t] = counts.get(t, 0) + 1
            for t in self._store.get_manual(p):
                manual[t.lower()] = manual.get(t.lower(), 0) + 1
        q = self._find_text()
        keep_t = {it.data(Qt.ItemDataRole.UserRole) for it in self.lst_tags.selectedItems()}
        keep_a = {it.data(Qt.ItemDataRole.UserRole) for it in self.lst_avail.selectedItems()}

        lw = self.lst_tags
        lw.blockSignals(True)
        lw.clear()
        for t in self._order([t for t in counts if not q or q in t.lower()]):
            n = counts[t]
            mate = pt.partner(t)                         # 261113-9(§8.9): 짝이 있으면 '태그 ⇄ 짝'
            hm = "#" if manual.get(t.lower()) else "·#"  # 261114-2(§5.3.2): 자동으로만 붙은 태그는 '·#'
            frac = ("%d/%d" % (n, m)) if n >= m else ("◐ %d/%d" % (n, m))
            it = QListWidgetItem("%s%s%s  %s" % (hm, t, (" ⇄ " + mate) if mate else "", frac))
            it.setData(Qt.ItemDataRole.UserRole, t)
            it.setData(KIND_ROLE, "some" if n < m else "all")
            it.setToolTip(tr("자동 {a} · 직접 {m}").format(a=max(0, n - manual.get(t.lower(), 0)), m=manual.get(t.lower(), 0)))
            lw.addItem(it)
            if t in keep_t:
                it.setSelected(True)
        lw.blockSignals(False)

        have = {t.lower() for t in counts}
        la = self.lst_avail
        la.blockSignals(True)
        la.clear()
        sections = []
        # 261114-2 덧붙임 2(사용자 결정 '늘 보이게'): 문서 종류 7 + 자동 해시태그 속성 6 = 13 항목은 늘 보인다(붙어 있으면 ✓·◐)
        sections.append((tr("문서 종류"), "fmt", [f for f in FORMAT_VOCAB if not q or q in f.lower()]))
        sections.append((tr("자동 해시태그 속성"), "attr", [a for a in PDF_ATTR_ITEMS if not q or q in a.lower()]))
        fl = {f.lower() for f in FORMAT_VOCAB} | {a.lower() for a in PDF_ATTR_ITEMS}
        known = [t for t in self._all_known() if t.lower() not in have and t.lower() not in fl and (not q or q in t.lower())]
        sections.append((tr("기존 태그"), "tag", self._order(known)))
        sections.append((tr("새 태그 후보"), "cand", [t for t, _h in self._cand_rows() if t.lower() not in have and (not q or q in t.lower())]))
        if self._show_cand_first:
            sections = [sections[3]] + sections[:3]
        import re as _re
        lowc = {t.lower(): n for t, n in counts.items()}
        n_date = sum(1 for p in files if any(_re.match(r"^\d{4}-\d{2}-\d{2}$", t) for t in self.shown_tags(p)))
        cand_n = {t: len(h) for t, h in self._cand_rows()}
        hf = la.font()
        hf.setBold(True)
        for title, kind, tags in sections:
            if not tags:
                continue
            h = QListWidgetItem(title)
            h.setFlags(Qt.ItemFlag.NoItemFlags)          # 묶음 머리 — 고를 수 없다
            h.setFont(hf)
            la.addItem(h)
            for t in tags:
                mate = pt.partner(t)
                txt = "  #%s%s" % (t, (" ⇄ " + mate) if mate else "")
                if kind in ("fmt", "attr"):
                    n_on = n_date if t == "날짜" else lowc.get(t.lower(), 0)
                    if m and n_on >= m:
                        txt += "  ✓"
                    elif n_on:
                        txt += "  ◐"
                if kind == "cand":
                    txt += tr("  ({n}건)").format(n=cand_n.get(t, 0))
                it = QListWidgetItem(txt)
                it.setData(Qt.ItemDataRole.UserRole, t)
                it.setData(KIND_ROLE, kind)
                if kind == "fmt":
                    it.setToolTip(tr("문서 종류 — 붙이면 고른 PDF 의 종류가 이것 하나로 바뀝니다"))
                elif kind == "attr":
                    it.setToolTip(tr("날짜는 고른 파일마다 그 파일 날짜로, 한글·영어와 스캔문서·텍스트문서는 짝 중 하나만 붙습니다")
                                  if t in ("날짜", "한글", "영어", "스캔문서", "텍스트문서") else tr("자동 해시태그 속성"))
                la.addItem(it)
                if t in keep_a:
                    it.setSelected(True)
        la.blockSignals(False)
        self._refresh_marks()

    # 종전 이름(검사·부른 쪽) — 두 목록을 함께 채운다
    def _fill_tags(self):
        self._fill_lists()

    def _cand_rows(self) -> list:
        """적립된 새 태그 후보 중 근거 파일이 지금 목록에 있는 것(261111-20 덧붙임) — [(태그, 근거 파일)]."""
        in_list = {_norm(p) for p in self._paths}
        rows = []
        for t, info in (self._cand.get("cand") or {}).items():
            here = [f for f in (info.get("files") or []) if _norm(f) in in_list]
            if here:
                rows.append((t, here))
        rows.sort(key=lambda kv: (-len(kv[1]), kv[0].lower()))
        return rows[:200]

    def _refresh_marks(self):
        n = len(self.selected_paths())
        vis = sum(1 for i in range(self.lst_files.count()) if not self.lst_files.isRowHidden(i))
        self.lbl_sel.setText(tr("고른 파일 {n}개 / 보이는 {v}개 / 모두 {m}개").format(n=n, v=vis, m=len(self._paths)))
        self.btn_undo.setEnabled(bool(self._undo))
        self.btn_redo.setEnabled(bool(self._redo))
        has_files = bool(self.target_paths())
        to = bool(self.lst_avail.selectedItems()) or any(it.data(KIND_ROLE) == "some" for it in self.lst_tags.selectedItems())
        self.btn_to.setEnabled(has_files and to)
        self.btn_from.setEnabled(has_files and bool(self.lst_tags.selectedItems()))
        self.btn_apply.setEnabled(self.btn_to.isEnabled())
        self.btn_clear.setEnabled(self.btn_from.isEnabled())
        self.btn_dismiss.setEnabled(bool(self._picked_cands()))
        q = self._find_text()
        known = {t.lower() for t in self._all_known()}
        for lw in (self.lst_tags, self.lst_avail):
            known |= {(lw.item(i).data(Qt.ItemDataRole.UserRole) or "").lower() for i in range(lw.count())}
        self.btn_find_add.setEnabled(bool(q) and q not in known and has_files)

    def _on_find(self, *_a):
        self._fill_lists()

    def _on_sort(self, *_a):
        self._sort = self.cmb_sort.currentData() or self.SORT_NAME
        self._fill_lists()

    def _find_add(self):
        """찾는 글자를 새 태그로 고른 파일에 곧바로 붙인다(목록에 없을 때 — 261114-2 덧붙임, 종전 '태그 추가' 묶음)."""
        if not self.btn_find_add.isEnabled():
            return
        from viewer.tag_store import normalize_tags
        ts = normalize_tags([self.ed_find.text()])
        if not ts:
            return
        self.ed_find.clear()
        self._known = None
        self.apply_tags(True, tags=[ts[0]])

    def _dismiss(self):
        from viewer.tag_store import save_candidates
        for t in self._picked_cands():
            self._cand["cand"].pop(t, None)
            if t not in self._cand["rejected"]:
                self._cand["rejected"].append(t)
        save_candidates(self._cand)
        self._cand_filter = False
        self._apply_filter()

    def _on_dropped(self, target):
        """끌어 놓기 — 붙은 태그로 놓으면 붙이고, 붙일 수 있는 태그로 놓으면 뗀다."""
        self.apply_tags(target is self.lst_tags)

    # ── 적용·해제·되돌리기 ─────────────────────────────────
    def chosen_tags(self, on: bool = True) -> list:
        """붙이기 = '붙일 수 있는 태그' 에서 고른 것(활성 목록이 그쪽일 때) 또는 붙은 쪽의 ◐(나머지에도) · 떼기 = 붙은 쪽에서 고른 것."""
        if on and self._mode == "avail":
            out = [it.data(Qt.ItemDataRole.UserRole) for it in self.lst_avail.selectedItems()]
        elif on:
            out = [it.data(Qt.ItemDataRole.UserRole) for it in self.lst_tags.selectedItems()]
        else:
            out = [it.data(Qt.ItemDataRole.UserRole) for it in self.lst_tags.selectedItems()]
        seen, res = set(), []
        for t in out:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                res.append(t)
        return res

    def set_format(self, fmt) -> int:
        """261114-2(태그 SOT §5.3.2): 고른 PDF 의 문서 종류를 fmt 로(None = 종류 없음) — 되돌리기 한 걸음. 바뀐 파일 수."""
        files = [p for p in self.target_paths() if str(p).lower().endswith(".pdf")]
        if not files:
            return 0
        st = self._store
        before = {p: st.record(p) for p in files}
        changed = st.set_format(files, fmt)
        if changed:
            self._undo.append(({p: before[p] for p in changed}, {p: st.record(p) for p in changed}))
            self._redo.clear()
            self._after_change()
        self._refresh_marks()
        return len(changed)

    def _after_change(self):
        self._known = None
        self._fill_tag_filter()
        self.changed.emit()
        self._apply_filter()                     # 태그가 바뀌면 거르기 결과·두 목록도

    def apply_tags(self, on: bool, tags=None) -> int:
        """→·[적용](on) = 고른 파일 모두에 붙임 · ←·[해제] = 모두에서 뗌(자동 태그는 거절). 바뀐 파일 수.
        문서 종류(§5.3.2)를 붙이면 PDF 의 종류가 그것 하나로 바뀐다(`set_format` — 같은 되돌리기 한 걸음)."""
        from viewer.auto_tag import FORMAT_VOCAB
        tags = list(tags) if tags else self.chosen_tags(on)
        files = self.target_paths()
        if not tags or not files:
            return 0
        st = self._store
        before = {p: st.record(p) for p in files}
        from viewer.auto_tag import PDF_ATTR_ITEMS
        fvl = {f.lower() for f in FORMAT_VOCAB}
        fmts = [t for t in tags if t.lower() in fvl] if on else []
        attrs = [t for t in tags if t in PDF_ATTR_ITEMS] if on else []
        if fmts or attrs:
            tags = [t for t in tags if t.lower() not in fvl and t not in PDF_ATTR_ITEMS]
        tl = {t.lower() for t in tags}
        with st.bulk():
            if fmts:
                st.set_format([p for p in files if str(p).lower().endswith(".pdf")], fmts[-1])
            for a in attrs:                              # 261114-2 덧붙임 2 — 속성 붙이기
                for p in files:
                    if a == "날짜":
                        d = self._file_date(p)
                        if d:
                            self._add_manual(p, d)
                        continue
                    other = {"한글": "영어", "영어": "한글", "스캔문서": "텍스트문서", "텍스트문서": "스캔문서"}.get(a)
                    if other:
                        man = st.get_manual(p)
                        if other in man:
                            st.set(p, [m for m in man if m != other])
                        if other in st.get_auto(p):
                            st.reject(p, [other])
                    self._add_manual(p, a)
            for p in files:
                if not tags:
                    break
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
        if changed:
            self._undo.append(({p: before[p] for p in changed}, {p: after[p] for p in changed}))
            self._redo.clear()
            self._after_change()
        self._refresh_marks()
        return len(changed)

    def _add_manual(self, p, t):
        """직접 태그로 붙인다(거절했던 것이면 거절을 푼다)."""
        st = self._store
        v = st._data.get(st._key(p))
        if isinstance(v, dict) and any(r.lower() == t.lower() for r in v.get("rejected") or ()):
            v["rejected"] = [r for r in v["rejected"] if r.lower() != t.lower()]
        man = st.get_manual(p)
        if t.lower() not in {m.lower() for m in man}:
            st.set(p, man + [t])
        else:
            st._save()

    def _file_date(self, p) -> str:
        """그 파일 날짜 — 썸네일 위 '기간' 과 같은 기준(사진은 촬영일, PDF 는 파일 날짜). 아직 못 읽었으면 파일 날짜."""
        d = (self._dates or {}).get(_norm(p))
        if d:
            return d
        import time as _t
        try:
            return _t.strftime("%Y-%m-%d", _t.localtime(os.stat(p).st_mtime))
        except (OSError, ValueError, OverflowError):
            return ""

    def _restore(self, snap: dict):
        with self._store.bulk():
            for p, rec in snap.items():
                self._store.put_record(p, rec)
        self._after_change()

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
