"""우클릭 메뉴 한 틀 — 묶음 차례·나눈 항목·저장 ▸ (디자인 SOT §2.9.8, 261107-2).

여섯 메뉴(PDF·사진 × 책갈피창·썸네일창·본문)와 꾸밈 개체 메뉴가 이 클래스를 쓴다.

- `CtxMenu.group(이름)` — 묶음을 연다. 차례(`GROUPS`)를 거꾸로 가면 `AssertionError`(개발 중에 잡히게).
  항목마다 `ctx_group` 속성을 적는다 — 검사(`test_ctx_menu_order.py`)가 읽는다.
- `CtxMenu.add_split(글, 하위, 기본 항목)` — **나눈 항목**: 글자 = 기본 일, ▸ = 하위.
  글자를 누르거나 Enter = 기본 일(할 수 없으면 하위를 연다), → 와 마우스 올림 = 하위 열기(보통 하위 메뉴와 같다).
- `add_save_menu(메뉴, 줄들)` — `저장 ▸` 하나(두 모드·여섯 메뉴 공통).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtGui import QAction, QKeyEvent, QPainter, QPen, QColor
from PyQt6.QtWidgets import QMenu

from viewer.i18n import tr

GROUPS = ("zip", "print", "copy", "shape", "file", "save", "view", "tool", "end")
SPLIT_ARROW_W = 26          # 나눈 항목 줄 오른쪽에서 ▸ 쪽으로 보는 폭(px) — 그 안을 누르면 하위를 연다


class CtxMenu(QMenu):
    """묶음 차례를 지키는 우클릭 메뉴(하위 메뉴도 이 클래스)."""

    def __init__(self, parent=None, title: str = ""):
        super().__init__(title, parent) if title else super().__init__(parent)
        self.setToolTipsVisible(True)
        self._group = None
        self._split = {}            # 하위 메뉴 항목 → 기본 항목(QAction) 또는 None
        self._forced = None         # 글자를 눌러 고른 기본 항목 — exec 가 돌려준다
        self._fired = None          # 이 메뉴(하위까지)에서 실제로 눌린 항목 — Qt 는 하위 항목도 맨 위 메뉴의 triggered 로 알린다
        self.triggered.connect(self._note_fired)

    def _note_fired(self, a):
        self._fired = a

    # ── 묶음 ────────────────────────────────────────────────
    def group(self, name: str) -> "CtxMenu":
        assert name in GROUPS, name
        if self._group is not None and GROUPS.index(name) < GROUPS.index(self._group):
            # 개발용 단언(화면에 나오지 않는다) — 화면 문구가 아니라 영문 그대로(다국어 SOT §6, test_i18n_coverage)
            raise AssertionError("ctx menu group order reversed: %s -> %s" % (self._group, name))
        if self._group != name and not self.isEmpty():
            self.addSeparator()
        self._group = name
        return self

    def actionEvent(self, ev):
        if ev.type() == QEvent.Type.ActionAdded:
            a = ev.action()
            if a is not None and a.property("ctx_group") is None and not a.isSeparator():
                a.setProperty("ctx_group", self._group or "")
        super().actionEvent(ev)

    def sub(self, title: str) -> "CtxMenu":
        """이 메뉴 안의 하위 메뉴(같은 클래스 — 하위 안에서도 묶음·나눈 항목을 쓴다)."""
        m = CtxMenu(self, title)
        self.addMenu(m)
        return m

    # ── 나눈 항목 ───────────────────────────────────────────
    def add_split(self, text: str, sub: QMenu, default: QAction | None, key: str = "", icon=None) -> QAction:
        """`text` 줄 = `default` 를 하는 글자 + `sub` 를 여는 ▸. `key` 는 오른쪽 칸 단축키 글(`_kt` 와 같은 값)."""
        sub.setTitle(text + ("\t" + key if key else ""))
        a = self.addMenu(sub)
        if icon is not None:
            a.setIcon(icon)
        a.setProperty("ctx_split", True)
        self._split[a] = default
        return a

    def split_default(self, a: QAction):
        return self._split.get(a)

    def _in_label(self, a: QAction, x: int) -> bool:
        g = self.actionGeometry(a)
        return x < g.right() - SPLIT_ARROW_W

    def _press_label(self, a: QAction) -> None:
        d = self._split.get(a)
        if d is not None and d.isEnabled():
            self._forced = d
            top = self
            while isinstance(top.parent(), QMenu) and top.parent().isVisible():   # 하위 안의 나눈 항목이면 맨 위까지 닫는다
                top = top.parent()
            if isinstance(top, CtxMenu):
                top._forced = d
                top._fired = d
            for m in self._chain():
                m.hide()
            d.trigger()
            return
        # 기본 일을 할 수 없으면 하위를 연다(회색으로 막히지 않게 — 디자인 SOT §2.9.8 의 3)
        self.setActiveAction(a)
        QTimer.singleShot(0, lambda: self._open_sub(a))

    def _open_sub(self, a: QAction) -> None:
        if not self.isVisible():
            return
        self.setActiveAction(a)
        self.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))

    def _chain(self):
        out, m = [], self
        while isinstance(m, QMenu):
            out.append(m)
            m = m.parent()
        return out

    def mouseReleaseEvent(self, ev):
        a = self.actionAt(ev.position().toPoint())
        if a is not None and a in self._split and a.isEnabled() and self._in_label(a, int(ev.position().x())):
            self._press_label(a)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev):
        a = self.activeAction()
        if (a is not None and a in self._split and a.isEnabled()
                and ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self._press_label(a)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self._split:
            return
        p = QPainter(self)
        col = QColor(self.palette().color(self.foregroundRole()))
        col.setAlpha(70)
        p.setPen(QPen(col, 1))
        for a in self._split:
            if not a.isVisible():
                continue
            g = self.actionGeometry(a)
            x = g.right() - SPLIT_ARROW_W
            p.drawLine(x, g.top() + 4, x, g.bottom() - 4)
        p.end()

    def exec(self, *args, **kw):
        """`QMenu.exec` 그대로 + 나눈 항목 글자로 고른 것도 돌려준다.
        돌려받은 항목이 아직 눌리지 않았으면(검사가 `QMenu.exec` 를 가로채 항목만 돌려줄 때) 여기서 누른다 —
        항목마다 `triggered` 로 일을 거는 메뉴도 검사에서 같은 길을 탄다. 실제 Qt 는 이미 눌렀으므로 다시 누르지 않는다."""
        self._forced = None
        self._fired = None
        r = QMenu.exec(self, *args, **kw)
        if r is None:
            return self._forced
        if r is not self._fired and r is not self._forced and r.isEnabled():
            r.trigger()
        return r


def find_action(menu: QMenu, text: str, *, exact: bool = False):
    """메뉴(하위까지)에서 글(단축키 칸 앞)이 `text` 로 시작하는(exact 면 같은) 첫 항목 — 검사·코드가 같이 쓴다."""
    for a in menu.actions():
        t = a.text().split("\t")[0]
        if (t == text) if exact else t.startswith(text):
            return a
        if a.menu() is not None:
            r = find_action(a.menu(), text, exact=exact)
            if r is not None:
                return r
    return None


def walk(menu: QMenu, depth: int = 0):
    """(깊이, 항목) — 구분선은 빼고, 하위 메뉴 안까지 차례대로."""
    for a in menu.actions():
        if a.isSeparator():
            continue
        yield depth, a
        if a.menu() is not None:
            yield from walk(a.menu(), depth + 1)


def _add(menu: QMenu, spec: dict) -> QAction | None:
    if spec is None:
        return None
    if spec.get("menu") is not None:                 # 하위 메뉴째(썸네일창 '변환 ▸')
        m = spec["menu"]
        m.setTitle(spec["text"])
        a = menu.addMenu(m)
    else:
        a = menu.addAction(spec["text"])
        cb = spec.get("cb")
        if cb is not None:
            a.triggered.connect(lambda _=False, f=cb: QTimer.singleShot(0, f))   # 창은 메뉴가 닫힌 뒤(마스터 §4.7.11)
    a.setEnabled(bool(spec.get("enabled", True)))
    if spec.get("tip"):
        a.setToolTip(spec["tip"])
    if spec.get("key_id"):
        a.setProperty("ctx_key", spec["key_id"])
    return a


def add_save_menu(menu: CtxMenu, *, save=None, save_as=None, copies=(), make=(), key: str = "",
                  title: str | None = None) -> QAction:
    """`저장 ▸` 나눈 항목 하나(디자인 SOT §2.9.8 의 3).

    줄은 dict — `{"text", "cb", "enabled", "tip"}`(또는 `"menu"` 로 하위째). 차례: 저장 · 다른 이름으로 저장 ─ 사본 ─ 만들기.
    글자 = `save` 줄(할 수 없거나 없으면 하위를 연다)."""
    menu.group("save")
    sub = CtxMenu(menu)
    sub.setToolTipsVisible(True)
    a_save = None
    if save is not None:
        sp = dict(save)
        sp["text"] = sp.get("text") or tr("저장")
        if key:
            sp["text"] = sp["text"] + "\t" + key
        a_save = _add(sub, sp)
    _add(sub, save_as)
    rest = [c for c in copies if c is not None]
    if rest:
        sub.addSeparator()
        for c in rest:
            _add(sub, c)
    rest = [c for c in make if c is not None]
    if rest:
        sub.addSeparator()
        for c in rest:
            _add(sub, c)
    a = menu.add_split(title or tr("저장"), sub, a_save, key)
    a.setProperty("ctx_save", True)
    return a
