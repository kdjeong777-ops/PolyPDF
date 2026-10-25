# -*- coding: utf-8 -*-
"""261024-1(사용자 지시, 디자인 SOT §2.9·§2.9.3·§2.9.4): 메뉴를 **탭**으로 — 알PDF·Word 처럼.

- 탭 줄: `모음 · 파일 · 즐겨찾기 · 보기 · 도구 · 도움말`. 고른 탭 글자 아래에 굵은 바, 오른쪽 끝에 검색창.
- 세부 줄: 고른 탭의 항목을 **한 줄**로. 항목의 원본은 그 탭의 `QMenu` — 세부 줄은 메뉴의 `QAction` 을 **같은 객체로**
  단추로 보인다(숨김·꺼짐·체크가 메뉴와 따로 놀지 않는다). 하위 메뉴는 `▾` 단추.
- `모음` 탭: 사용자가 고른 명령(id) 차례. 기본값 `DEFAULT_COLLECTION` = 종전 패널 툴바.

가운데 정렬은 **레이아웃의 늘림 빈 칸**으로 한다 — 종전(261021-2)에는 창이 뜬 뒤 타이머로 빈 칸 폭을 쟀는데, 시작 직후
메인 스레드가 바쁘면 타이머가 돌지 못해 첫 화면이 왼쪽에 붙은 채 남았다(261024-1 사용자 보고). 레이아웃은 첫 그림 전에 끝난다.
"""
from __future__ import annotations

import re

from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QPainter
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QStackedWidget,
                             QToolBar, QToolButton, QToolTip, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from viewer.i18n import tr

TAB_BAR_PX = 3              # 고른 탭 아래 바 두께
TAB_BAR_COLOR = "#1456c4"   # 디자인 SOT §2.5 '강조'
GROUP_PAD_X = 4             # 그룹 바탕이 단추 바깥으로 나오는 폭
GROUP_RADIUS = 6
GROUP_BG = {False: "#ebebeb", True: "#3a3a3d"}   # 라이트(툴바 #f5f5f5 · 버튼 #e2e2e2 사이) / 다크(#2e2e31 · #484848 사이)
REBUILD_MS = 10             # 메뉴 항목이 바뀐 뒤 세부 줄을 다시 만들기까지(잇단 바뀜은 한 번으로 모인다)

SEP = "|"                   # 모음의 구분선
COLLECTION = "collection"   # 모음 탭 키
DEFAULT_COLLECTION = (
    "view.single", "view.split", "view.text", "view.study", "view.search", "view.shot",
    "view.law", "view.kipo", "view.kcsc", "view.present", SEP,      # 261025-1: 보기 탭 차례와 같게(디자인 SOT §2.9.5)
    "tools.ocr", "tools.build_study", "tools.bookmarker", "tools.merge", "tools.img2pdf",
    "tools.encrypt", "tools.translate", "file.export",
)

_MNEMONIC = re.compile(r"\(&.\)")


def short_text(text: str) -> str:
    """메뉴 글자 → 단추 글자: 단축키 칸(`\\t…`)·니모닉 `(&X)`·끝의 `...`/`…` 를 뺀다."""
    t = (text or "").split("\t")[0]
    t = _MNEMONIC.sub("", t).replace("&", "")
    t = t.rstrip()
    for tail in ("...", "…"):
        if t.endswith(tail):
            t = t[: -len(tail)].rstrip()
    return t


def cmd_id(action) -> str:
    v = action.property("cmd_id") if action is not None else None
    return str(v) if v else ""


class _TipFilter(QObject):
    """세부 줄 단추 툴팁 = 액션 툴팁 + 지금 단축키(디자인 SOT §2.9.2)."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.ToolTip and isinstance(obj, QToolButton):
            a = obj.defaultAction()
            if a is not None:
                tip = a.toolTip() or a.iconText()
                key = a.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
                if not key and "\t" in a.text():
                    key = a.text().split("\t", 1)[1].strip()
                if key and key not in tip:
                    tip = f"{tip} ({key})"
                QToolTip.showText(ev.globalPos(), tip, obj)
                return True
        return False


class RibbonRow(QToolBar):
    """세부 줄 하나 — 앞·뒤 늘림 빈 칸으로 가운데, 구분선 사이 단추마다 둥근 그룹 바탕."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setMovable(False)
        self.setFloatable(False)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.dark = False
        self._tips = _TipFilter(self)

    def _spacer(self) -> QWidget:
        w = QWidget(self)
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        w.setProperty("ribbonSpacer", True)
        return w

    def set_items(self, items) -> None:
        """items: QAction 또는 None(구분선). 앞·뒤·겹친 구분선은 하나로 줄인다."""
        for a in getattr(self, "_watched", ()):
            try:
                a.changed.disconnect(self._sync_seps)
            except (TypeError, RuntimeError):
                pass
        self._watched = []
        self.clear()
        self.lead = self.addWidget(self._spacer())
        pending_sep = False
        added = False
        for a in items:
            if a is None or a.isSeparator():
                pending_sep = added
                continue
            if pending_sep:
                self.addSeparator()
                pending_sep = False
            self.addAction(a)
            w = self.widgetForAction(a)
            if isinstance(w, QToolButton):
                if a.menu() is not None:
                    w.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                w.installEventFilter(self._tips)
            a.changed.connect(self._sync_seps)
            self._watched.append(a)
            added = True
        self.trail = self.addWidget(self._spacer())
        self._sync_seps()

    def _sync_seps(self) -> None:
        """261025-1: 구분선은 **양쪽에 보이는 단추가 있을 때만** — 묶음 전체가 숨으면(한국 전용·키 게이팅) 구분선이 겹쳐 보이지 않게."""
        show = {}
        seen = False            # 앞에 보이는 단추가 있었나
        pend = None             # 아직 뒤쪽 단추를 기다리는 구분선
        for a in self.actions():
            if a.isSeparator():
                if pend is None and seen:
                    pend = a
                else:
                    show[a] = False          # 앞에 단추가 없거나, 이미 기다리는 구분선이 있다
                continue
            w = self.widgetForAction(a)
            if w is None or w.property("ribbonSpacer") or not a.isVisible():
                continue
            if pend is not None:
                show[pend] = True
                pend = None
            seen = True
        if pend is not None:
            show[pend] = False
        for s, on in show.items():
            if s.isVisible() != on:
                s.setVisible(on)

    def buttons(self) -> list:
        """보이는 단추(빈 칸 제외) — 차례대로."""
        out = []
        for a in self.actions():
            if a.isSeparator():
                continue
            w = self.widgetForAction(a)
            if w is not None and not w.property("ribbonSpacer") and w.isVisible():
                out.append(w)
        return out

    def groups(self) -> list:
        """구분선으로 나뉜 보이는 단추 묶음."""
        gs, cur = [], []
        for a in self.actions():
            if a.isSeparator():
                if not a.isVisible():            # 숨긴 구분선(빈 묶음 사이)은 경계가 아니다
                    continue
                if cur:
                    gs.append(cur)
                cur = []
                continue
            w = self.widgetForAction(a)
            if w is not None and not w.property("ribbonSpacer") and w.isVisible():
                cur.append(w)
        if cur:
            gs.append(cur)
        return gs

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(GROUP_BG[bool(self.dark)]))
        for g in self.groups():
            x0 = min(w.geometry().left() for w in g) - GROUP_PAD_X
            x1 = max(w.geometry().right() for w in g) + GROUP_PAD_X
            y0 = min(w.geometry().top() for w in g) - 1
            y1 = max(w.geometry().bottom() for w in g) + 1
            p.drawRoundedRect(QRectF(x0, y0, x1 - x0 + 1, y1 - y0 + 1), GROUP_RADIUS, GROUP_RADIUS)
        p.end()


class Ribbon(QWidget):
    """탭 줄 + 세부 줄. `QMainWindow.setMenuWidget` 자리에 놓는다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ribbon")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 탭 줄: [왼쪽 빈 칸][탭 묶음][오른쪽 칸(검색창)] — 양쪽 같은 늘림 → 탭 묶음이 창 가운데(§2.9.3)
        self.tab_row = QWidget(self)
        h = QHBoxLayout(self.tab_row)
        h.setContentsMargins(6, 2, 6, 0)
        h.setSpacing(0)
        self.left_fill = QWidget(self.tab_row)
        self.left_fill.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.tabs_box = QWidget(self.tab_row)
        self._tabs_lay = QHBoxLayout(self.tabs_box)
        self._tabs_lay.setContentsMargins(0, 0, 0, 0)
        self._tabs_lay.setSpacing(2)
        self.right_box = QWidget(self.tab_row)
        self.right_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._right_lay = QHBoxLayout(self.right_box)
        self._right_lay.setContentsMargins(0, 0, 0, 0)
        self._right_lay.addStretch(1)
        h.addWidget(self.left_fill, 1)
        h.addWidget(self.tabs_box, 0)
        h.addWidget(self.right_box, 1)
        v.addWidget(self.tab_row)

        self.stack = QStackedWidget(self)
        v.addWidget(self.stack)

        self._tabs = {}          # key → 탭 단추
        self._rows = {}          # key → RibbonRow
        self._menus = {}         # key → QMenu(메뉴에서 오는 줄)
        self._order = []
        self._dirty = set()
        self._rows_visible = True
        self.dark = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REBUILD_MS)
        self._timer.timeout.connect(self._rebuild_dirty)

    # ── 탭 ─────────────────────────────────────────────
    def add_tab(self, key: str, title: str, menu=None) -> RibbonRow:
        b = QToolButton(self.tabs_box)
        b.setObjectName("ribbonTab")
        b.setText(title)                 # '파일(&F)' — Alt+F 가 이 탭을 고른다
        b.setCheckable(True)
        b.setAutoExclusive(True)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.clicked.connect(lambda _=False, k=key: self.select(k))
        self._tabs_lay.addWidget(b)
        row = RibbonRow(short_text(title), self.stack)
        self.stack.addWidget(row)
        self._tabs[key] = b
        self._rows[key] = row
        self._order.append(key)
        if menu is not None:
            self._menus[key] = menu
            menu.installEventFilter(self)
            self._fill_from_menu(key)
        if len(self._order) == 1:
            self.select(key)
        return row

    def select(self, key: str) -> None:
        if key not in self._tabs:
            return
        self._tabs[key].setChecked(True)
        if key in self._dirty:
            self._fill_from_menu(key)
        self.stack.setCurrentWidget(self._rows[key])
        if not self._rows_visible:          # 세부 줄을 숨겨 둔 채 탭을 누르면 다시 보인다(§2.9)
            self._rows_visible = True
            self.stack.setVisible(True)

    def current_key(self) -> str:
        for k, b in self._tabs.items():
            if b.isChecked():
                return k
        return ""

    def tab_button(self, key: str):
        return self._tabs.get(key)

    def row(self, key: str):
        return self._rows.get(key)

    def keys(self) -> list:
        return list(self._order)

    # ── 메뉴에서 오는 줄 ─────────────────────────────────
    def _fill_from_menu(self, key: str) -> None:
        self._dirty.discard(key)
        menu = self._menus.get(key)
        if menu is None:
            return
        items = []
        for a in menu.actions():
            items.append(None if a.isSeparator() else a)    # 빈 묶음 사이 구분선은 RibbonRow 가 숨긴다
        self._rows[key].set_items(items)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.ActionAdded, QEvent.Type.ActionRemoved):
            for k, m in self._menus.items():
                if m is obj:
                    self._dirty.add(k)
                    self._timer.start()
        return False

    def _rebuild_dirty(self) -> None:
        for k in list(self._dirty):
            self._fill_from_menu(k)

    # ── 모음 ────────────────────────────────────────────
    def set_collection(self, actions) -> None:
        """actions: QAction 또는 None(구분선) — 사용자가 고른 차례(디자인 SOT §2.9·§2.9.4)."""
        row = self._rows.get(COLLECTION)
        if row is not None:
            row.set_items(actions)

    # ── 검색창·보이기·테마 ───────────────────────────────
    def set_search(self, w: QWidget) -> None:
        self._right_lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_rows_visible(self, on: bool) -> None:
        self._rows_visible = bool(on)
        self.stack.setVisible(self._rows_visible)

    def apply_style(self, dark: bool, button_css: str) -> None:
        self.dark = bool(dark)
        fg = "#e8e8e8" if dark else "#222"
        hover = "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.06)"
        self.tab_row.setStyleSheet(
            "QToolButton#ribbonTab{background:transparent;border:none;"
            f"border-bottom:{TAB_BAR_PX}px solid transparent;padding:3px 12px 2px 12px;color:{fg};}}"
            f"QToolButton#ribbonTab:hover{{background:{hover};}}"
            f"QToolButton#ribbonTab:checked{{border-bottom-color:{TAB_BAR_COLOR};}}")
        for r in self._rows.values():
            r.dark = self.dark
            r.setStyleSheet(button_css + "QToolBar::separator{width:12px;background:transparent;}")
            r.update()


class RibbonCustomizeDialog(QDialog):
    """`모음` 사용자 지정(디자인 SOT §2.9.4) — 왼쪽 탭별 명령, 오른쪽 모음 차례."""

    SEP_LABEL = "──── " + "{sep}" + " ────"

    def __init__(self, catalog, current, labels, parent=None):
        """catalog: [(탭 이름, [명령 id, ...]), ...] · current: 지금 모음(id·SEP) · labels: id → 단추 이름."""
        super().__init__(parent)
        self.setWindowTitle(tr("모음 메뉴 편집"))
        self.resize(640, 480)
        self._labels = dict(labels)
        self._sep_text = self.SEP_LABEL.format(sep=tr("구분선"))

        v = QVBoxLayout(self)
        info = QLabel(tr("왼쪽에서 명령을 골라 '모음' 탭에 넣습니다. 차례는 오른쪽 목록 차례입니다."))
        info.setWordWrap(True)
        v.addWidget(info)
        h = QHBoxLayout()
        v.addLayout(h, 1)

        lv = QVBoxLayout()
        lv.addWidget(QLabel(tr("명령 고르기")))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        for title, ids in catalog:
            top = QTreeWidgetItem([short_text(title)])
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for cid in ids:
                it = QTreeWidgetItem([self._labels.get(cid, cid)])
                it.setData(0, Qt.ItemDataRole.UserRole, cid)
                top.addChild(it)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()
        self.tree.itemDoubleClicked.connect(lambda *_: self._add())
        lv.addWidget(self.tree, 1)
        h.addLayout(lv, 1)

        mid = QVBoxLayout()
        mid.addStretch(1)
        self.btn_add = QPushButton(tr("추가 >"))
        self.btn_remove = QPushButton(tr("< 제거"))
        self.btn_sep = QPushButton(tr("구분선"))
        self.btn_up = QPushButton("▲")
        self.btn_down = QPushButton("▼")
        self.btn_up.setToolTip(tr("위로"))
        self.btn_down.setToolTip(tr("아래로"))
        for b, fn in ((self.btn_add, self._add), (self.btn_remove, self._remove), (self.btn_sep, self._add_sep),
                      (self.btn_up, lambda: self._move(-1)), (self.btn_down, lambda: self._move(1))):
            b.clicked.connect(fn)
            mid.addWidget(b)
        mid.addStretch(1)
        h.addLayout(mid)

        rv = QVBoxLayout()
        rv.addWidget(QLabel(tr("모음")))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        rv.addWidget(self.list, 1)
        h.addLayout(rv, 1)
        self._load(current)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.btn_default = bb.addButton(tr("기본값으로"), QDialogButtonBox.ButtonRole.ResetRole)
        self.btn_default.clicked.connect(lambda: self._load(DEFAULT_COLLECTION))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _item(self, cid: str) -> QListWidgetItem:
        it = QListWidgetItem(self._sep_text if cid == SEP else self._labels.get(cid, cid))
        it.setData(Qt.ItemDataRole.UserRole, cid)
        return it

    def _load(self, ids) -> None:
        self.list.clear()
        for cid in ids:
            if cid == SEP or cid in self._labels:
                self.list.addItem(self._item(cid))

    def _ids_in_list(self) -> list:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def _insert(self, cid: str) -> None:
        row = self.list.currentRow()
        row = self.list.count() if row < 0 else row + 1
        self.list.insertItem(row, self._item(cid))
        self.list.setCurrentRow(row)

    def _add(self) -> None:
        it = self.tree.currentItem()
        cid = it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None
        if not cid or cid in self._ids_in_list():       # 같은 명령은 한 번만
            return
        self._insert(cid)

    def _add_sep(self) -> None:
        self._insert(SEP)

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)

    def _move(self, d: int) -> None:
        row = self.list.currentRow()
        new = row + d
        if row < 0 or not (0 <= new < self.list.count()):
            return
        it = self.list.takeItem(row)
        self.list.insertItem(new, it)
        self.list.setCurrentRow(new)

    def result_ids(self) -> list:
        return self._ids_in_list()
