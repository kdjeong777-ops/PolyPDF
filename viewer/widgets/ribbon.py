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
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QStackedWidget,
                             QToolBar, QToolButton, QToolTip, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from viewer.i18n import tr

TAB_BAR_PX = 3              # 고른 탭 아래 바 두께
TAB_BAR_COLOR = "#1456c4"   # 디자인 SOT §2.5 '강조'
GROUP_PAD_X = 4             # 그룹 바탕이 단추 바깥으로 나오는 폭
GROUP_RADIUS = 6
# 261025-5(디자인 SOT §2.9.3, 사용자 결정): 탭 줄은 밝게·리본(세부 줄)은 한 단계 진한 회색 — 드롭다운(▾)은 진하게, 일반 단추는 옅게.
#   다크는 같은 단계를 반대로(리본 줄이 탭 줄보다 조금 밝다). 값은 이 표 하나 — 원본(§2.1 '리본 색').
TAB_ROW_BG = {False: "#f5f5f5", True: "#2e2e31"}
ROW_BG = {False: "#e4e4e4", True: "#38383c"}
ROW_BORDER = {False: "#c8c8c8", True: "#4a4a50"}       # 탭 줄과 리본 줄 사이 1px
GROUP_BG = {False: "#d8d8d8", True: "#424247"}
BTN = {False: ("#fafafa", "#b4b4b4", "#222"), True: ("#3e3e42", "#55555a", "#e8e8e8")}        # 바탕·테두리·글
BTN_DROP = {False: ("#efefef", "#a0a0a0", "#222"), True: ("#5a5a60", "#707078", "#f0f0f0")}
REBUILD_MS = 10             # 메뉴 항목이 바뀐 뒤 세부 줄을 다시 만들기까지(잇단 바뀜은 한 번으로 모인다)

ICON_DROP_PAD = 14          # 261031-12 보완: 그림만 있는 ▾ 단추의 오른쪽 여백(▾ 자리)
SEP = "|"                   # 모음의 구분선
COLLECTION = "collection"   # 모음 탭 키
# 261031-17(디자인 SOT §2.9·§2.9.4, 사용자 결정 '표시를 항목으로'): 그룹 표시(바깥 왼쪽 그림·글자)도 모음 항목이다 —
#   `mark.*` id 로 넣고 뺀다. 원 탭(파일 `열기`·`저장`, 도구 `생성`·`PDF`)과 같은 표시(같은 RibbonIconMark 액션).
MARK_PREFIX = "mark."
DEFAULT_COLLECTION = (
    "mark.open", "file.open_folder", "file.open_file", "file.print", SEP,   # 261025-5: 앞 그룹 — 폴더 열기·파일 열기·인쇄(사용자 지시)
    "view.single", "view.split", SEP,                                # 261031-17: 보기 탭 그룹 그대로(디자인 SOT §2.9.5)
    "view.text", "view.study", "view.search", "view.shot", SEP,
    "view.law", "view.kipo", "view.kcsc", SEP, "view.present", SEP,
    "mark.create", "tools.ocr", "tools.build_study", "tools.bookmarker", SEP,   # 261031-16: 도구 탭 차례·묶음과 같게(§2.9.1)
    "mark.pdf", "tools.img2pdf", "tools.merge", "tools.encrypt", SEP,
    "file.export", "tools.translate",
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


def _make_icon_mark():
    from PyQt6.QtWidgets import QWidgetAction

    class RibbonIconMark(QWidgetAction):
        """261031-12 보완(디자인 SOT §2.9.5, 사용자 지시): 단추 무리 **바깥 왼쪽**의 눌리지 않는 그림 표시 —
        세부 줄에 놓이면 작은 그림 하나(`QLabel`), 메뉴로 펼칠 때는 보이지 않는다. 테마가 바뀌면 `refresh()`."""

        def __init__(self, parent, icon_fn=None, tip: str = "", text: str = ""):
            super().__init__(parent)
            self._icon_fn = icon_fn          # () -> QIcon — 없으면 글자 표시(`text`, 예: '최근'·'등록')
            self._text = text
            self.setToolTip(tip)
            self.setProperty("ribbonMark", True)

        def createWidget(self, parent):
            lab = QLabel(parent)
            lab.setProperty("ribbonMark", True)
            lab.setToolTip(self.toolTip())
            lab.setContentsMargins(2, 0, 0, 0)
            self._paint(lab)
            return lab

        def _paint(self, lab) -> None:
            if self._icon_fn is None:
                lab.setText(self._text)
                lab.setContentsMargins(4, 0, 2, 0)
                return
            ic = self._icon_fn()
            px = lab.parentWidget().iconSize() if hasattr(lab.parentWidget(), "iconSize") else None
            n = px.width() if px is not None and px.width() > 0 else 13
            lab.setPixmap(ic.pixmap(n, n))

        def refresh(self) -> None:
            for w in self.createdWidgets():
                self._paint(w)

    return RibbonIconMark


RibbonIconMark = _make_icon_mark()


class RibbonRow(QToolBar):
    """세부 줄 하나 — 앞·뒤 늘림 빈 칸으로 가운데, 구분선 사이 단추마다 둥근 그룹 바탕."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setMovable(False)
        self.setFloatable(False)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.dark = False
        self.use_short = False           # 261031-13(§2.9.7): 이 줄에서는 액션의 `ribbonShort` 를 단추 글로(파일·도구 탭)
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
                if a.property("ribbonIconOnly") and self.toolButtonStyle() != Qt.ToolButtonStyle.ToolButtonTextOnly:
                    # 261031-12 보완: 그림만(글자는 무리 바깥 표시·툴팁) — 글자만 줄(보기·도구 탭)에서는 글자 단추
                    w.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                    if a.menu() is not None:             # ▾ 가 그림에 겹치지 않게 오른쪽 여백(ICON_DROP_PAD)
                        w.setStyleSheet("QToolButton{padding-right:%dpx;}" % ICON_DROP_PAD)
                w.setProperty("ribbonDrop", a.menu() is not None)
                w.style().unpolish(w)
                w.style().polish(w)
                w.installEventFilter(self._tips)
            a.changed.connect(self._sync_seps)
            self._watched.append(a)
            added = True
        self.trail = self.addWidget(self._spacer())
        self._sync_seps()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit_spacers()

    def _fit_spacers(self) -> None:
        """261025-5(§2.9.3): 단추가 줄 폭에 다 들어가지 않으면(넘침 ») 앞·뒤 빈 칸을 0 으로 — 넘칠 때 Qt 는 뒤 빈 칸을
        넘침 안으로 보내 **앞 빈 칸만** 남은 폭을 가져가 단추를 오른쪽으로 민다(모음이 길어진 뒤 드러남). 레이아웃 안에서만 바꾼다."""
        lead, trail = getattr(self, "lead", None), getattr(self, "trail", None)
        if lead is None or trail is None:
            return
        lay = self.layout()
        sp = lay.spacing() if lay is not None else 0
        need = 0
        for a in self.actions():
            if a in (lead, trail) or not a.isVisible():
                continue
            w = self.widgetForAction(a)
            need += (w.sizeHint().width() if w is not None else 12) + sp
        m = self.contentsMargins()
        fits = need + m.left() + m.right() + 24 <= self.width()
        pol = QSizePolicy.Policy.Expanding if fits else QSizePolicy.Policy.Ignored
        changed = False
        for a in (lead, trail):
            w = self.widgetForAction(a)
            if w is not None and w.sizePolicy().horizontalPolicy() != pol:
                w.setSizePolicy(pol, QSizePolicy.Policy.Preferred)
                changed = True
        if changed and lay is not None:
            lay.activate()                  # 이벤트 루프를 기다리지 않고 그 자리에서 다시 놓는다(첫 그림부터 맞게, §2.9.3)

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
        self._apply_short()
        self._fit_spacers()                 # 단추가 숨거나 보이면 폭도 다시 잰다

    def _apply_short(self) -> None:
        """261031-13(디자인 SOT §2.9.7): 탭에서만 쓰는 짧은 이름 — 액션이 바뀌면 단추가 글을 되돌리므로 그때마다 다시 넣는다."""
        if not self.use_short:
            return
        for a in self.actions():
            short = a.property("ribbonShort")
            if short:
                w = self.widgetForAction(a)
                if isinstance(w, QToolButton) and w.text() != short:
                    w.setText(short)

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
        self.tab_row.setObjectName("ribbonTabRow")
        self.tab_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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
        self._peek = False               # 리본을 숨겨 둔 채 탭을 눌러 잠깐 보이는 중(§2.9.6)
        self.context_menu_provider = None   # 우클릭 메뉴를 만드는 함수(MainWindow 가 넣는다)
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
        row.actionTriggered.connect(lambda _a: self.end_peek())
        self.stack.addWidget(row)
        self._tabs[key] = b
        self._rows[key] = row
        self._order.append(key)
        if menu is not None:
            self._menus[key] = menu
            menu.installEventFilter(self)
            menu.triggered.connect(lambda _a: self.end_peek())     # ▾ 펼침 안의 명령도(하위 메뉴는 위로 전해진다)
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
        if not self._rows_visible:          # 261025-5(§2.9.6): 리본을 숨겨 두었으면 탭을 누를 때 **잠깐** 보인다
            self._start_peek()

    # ── 잠깐 보이기(§2.9.6, 사용자 지시) — 명령을 고르거나 리본 밖을 누르면 다시 숨는다 ──
    def _start_peek(self) -> None:
        if not self._peek:
            self._peek = True
            QApplication.instance().installEventFilter(self)
        self.stack.setVisible(True)

    def end_peek(self) -> None:
        if not self._peek:
            return
        self._peek = False
        QApplication.instance().removeEventFilter(self)
        if not self._rows_visible:
            self.stack.setVisible(False)

    def peeking(self) -> bool:
        return self._peek

    def contextMenuEvent(self, ev):
        """261025-5(§2.9.6): 탭 줄·리본 바탕 우클릭 — '리본 메뉴 보이기'·'모음 메뉴 관리...'."""
        fn = self.context_menu_provider
        if fn is None:
            return super().contextMenuEvent(ev)
        m = fn()
        if m is not None:
            m.exec(ev.globalPos())
        ev.accept()

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
        if self._peek and ev.type() == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget) and obj.isWindow() is False:
            # 잠깐 보이는 중 리본 밖을 누르면 숨긴다 — 펼친 ▾ 메뉴(팝업) 안은 리본의 일로 본다
            if not (obj is self or self.isAncestorOf(obj) or QApplication.activePopupWidget() is not None):
                self.end_peek()
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
        if self._rows_visible:
            self.end_peek()
        self.stack.setVisible(self._rows_visible or self._peek)

    def rows_visible(self) -> bool:
        return self._rows_visible

    @staticmethod
    def button_css(dark: bool) -> str:
        """리본 단추 — 일반은 옅게, 드롭다운(▾)은 진하게(§2.9.3 표, 원본 `BTN`·`BTN_DROP`)."""
        d = bool(dark)
        css = ""
        for sel, (bg, bd, fg) in (("QToolButton", BTN[d]), ('QToolButton[ribbonDrop="true"]', BTN_DROP[d])):
            css += (f"{sel}{{background:{bg};border:1px solid {bd};border-radius:3px;padding:2px 8px;margin:1px;color:{fg};}}"
                    f"{sel}:hover{{border-color:{'#909090' if not d else '#8a8a92'};}}")
        css += ("QToolButton:pressed{background:%s;}" % ("#bdbdbd" if not d else "#2f2f33"))
        return css

    def apply_style(self, dark: bool, button_css: str = "") -> None:
        self.dark = bool(dark)
        d = self.dark
        fg = "#e8e8e8" if dark else "#222"
        hover = "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.06)"
        self.tab_row.setStyleSheet(
            f"QWidget#ribbonTabRow{{background:{TAB_ROW_BG[d]};}}"
            "QToolButton#ribbonTab{background:transparent;border:none;"
            f"border-bottom:{TAB_BAR_PX}px solid transparent;padding:3px 12px 2px 12px;color:{fg};}}"
            f"QToolButton#ribbonTab:hover{{background:{hover};}}"
            f"QToolButton#ribbonTab:checked{{border-bottom-color:{TAB_BAR_COLOR};}}")
        css = button_css or self.button_css(d)
        for r in self._rows.values():
            r.dark = d
            r.setStyleSheet(f"QToolBar{{background:{ROW_BG[d]};border:none;border-top:1px solid {ROW_BORDER[d]};}}"
                            + css + "QToolBar::separator{width:12px;background:transparent;}")
            r.update()


class RibbonCustomizeDialog(QDialog):
    """`모음` 사용자 지정(디자인 SOT §2.9.4) — 왼쪽 탭별 명령, 오른쪽 모음 차례."""

    SEP_LABEL = "──── " + "{sep}" + " ────"

    def __init__(self, catalog, current, labels, parent=None):
        """catalog: [(탭 이름, [명령 id, ...]), ...] · current: 지금 모음(id·SEP) · labels: id → 단추 이름."""
        super().__init__(parent)
        self.setWindowTitle(tr("모음 메뉴 관리"))          # 261025-5 보완: 단추·우클릭 이름 '모음 메뉴 관리...' 와 같게
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
