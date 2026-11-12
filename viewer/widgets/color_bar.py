# -*- coding: utf-8 -*-
"""가로 색 막대 — 견본 단추 줄에서 하나를 누르고, 끌어서 차례를 바꾸고, [＋] 로 색을 더한다
(사진 보기 SOT §4.46 '창 배치·기억', 디자인 SOT §2.23, 261113-4).

키: '#rrggbb'(색) 또는 무늬 키(예: 'mosaic' — `patterns` 로 이름·그림을 준다).
`fixed` 키는 늘 막대에 있고, 그 밖의 색은 '사용자 색' — 최근 `user_max` 개만 남는다.
신호: `picked(key)` 누른 단추 · `orderChanged(list)` 차례·사용자 색이 바뀜(기억은 부르는 쪽).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QMimeData, pyqtSignal, QPoint
from PyQt6.QtGui import QColor, QDrag, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QColorDialog, QHBoxLayout, QToolButton, QWidget

from viewer.i18n import tr

MIME = "application/x-polypdf-colorbar"
SW = 22                                   # 견본 단추 한 변(디자인 SOT §2.23)


def _norm(key: str) -> str:
    k = str(key or "").strip()
    return k.lower() if k.startswith("#") else k


class ColorBar(QWidget):
    picked = pyqtSignal(str)
    orderChanged = pyqtSignal(list)

    def __init__(self, fixed, *, order=None, current=None, user_max: int = 6, names=None, patterns=None,
                 pick_title: str = "", parent=None):
        super().__init__(parent)
        self._fixed = [_norm(k) for k in fixed]
        self._names = {_norm(k): v for k, v in (names or {}).items()}
        self._patterns = dict(patterns or {})          # 키 → QIcon 을 만드는 함수
        self._user_max = max(0, int(user_max))
        self._pick_title = pick_title or tr("색 지정")
        self._order = self._clean(order)
        self._cur = _norm(current) if current and _norm(current) in self._order else (self._order[0] if self._order else "")
        self._btns = {}
        self._press = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.btn_add = QToolButton()
        self.btn_add.setText("＋")
        self.btn_add.setFixedSize(SW, SW)
        self.btn_add.setToolTip(tr("색 지정…"))
        self.btn_add.clicked.connect(self._ask_color)
        self.setAcceptDrops(True)
        self._rebuild()

    # ── 차례 ──
    def _clean(self, order) -> list:
        out = []
        for k in list(order or []) + self._fixed:
            k = _norm(k)
            if not k or k in out:
                continue
            if k not in self._fixed and not (k.startswith("#") and QColor(k).isValid()):
                continue
            out.append(k)
        users = [k for k in out if k not in self._fixed]
        drop = set(users[self._user_max:])
        return [k for k in out if k not in drop]

    def order(self) -> list:
        return list(self._order)

    def user_colors(self) -> list:
        return [k for k in self._order if k not in self._fixed]

    def current(self) -> str:
        return self._cur

    def set_current(self, key: str) -> None:
        key = _norm(key)
        if key in self._order and key != self._cur:
            self._cur = key
            self._mark()
            self.picked.emit(key)

    def add_color(self, hexstr: str) -> None:
        """사용자 색 맨 앞(첫 사용자 색 자리)에 더하고 고른다 — 넘치면 가장 오래된(뒤) 사용자 색이 빠진다."""
        k = _norm(QColor(hexstr).name())
        if k in self._fixed:
            self.set_current(k)
            return
        rest = [x for x in self._order if x != k]
        users = [x for x in rest if x not in self._fixed]
        at = rest.index(users[0]) if users else len(rest)
        rest.insert(at, k)
        self._order = self._clean(rest)
        self._cur = k
        self._rebuild()
        self.orderChanged.emit(self.order())
        self.picked.emit(k)

    def move_key(self, key: str, index: int) -> None:
        key = _norm(key)
        if key not in self._order:
            return
        rest = [x for x in self._order if x != key]
        index = max(0, min(int(index), len(rest)))
        rest.insert(index, key)
        if rest == self._order:
            return
        self._order = rest
        self._rebuild()
        self.orderChanged.emit(self.order())

    # ── 화면 ──
    def _icon(self, key: str) -> QIcon:
        mk = self._patterns.get(key)
        if mk is not None:
            return mk()
        pm = QPixmap(SW - 6, SW - 6)
        pm.fill(QColor(key))
        return QIcon(pm)

    def _rebuild(self) -> None:
        lay = self.layout()
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None and w is not self.btn_add:
                w.hide(); w.setParent(None)      # 곧바로 막대에서 뗀다(deleteLater 는 다음 차례라 그 사이 옛 단추가 남는다)
                w.deleteLater()
        self._btns = {}
        for k in self._order:
            b = QToolButton()
            b.setFixedSize(SW, SW)
            b.setIcon(self._icon(k))
            b.setCheckable(True)
            b.setToolTip(tr("{name} — 끌어서 차례를 바꿉니다").format(name=self._names.get(k) or k))
            b.setProperty("colorKey", k)
            b.clicked.connect(lambda _=False, kk=k: self._on_click(kk))
            b.installEventFilter(self)
            lay.addWidget(b)
            self._btns[k] = b
        lay.addWidget(self.btn_add)
        lay.addStretch(1)
        self._mark()

    def _mark(self) -> None:
        for k, b in self._btns.items():
            on = k == self._cur
            b.setChecked(on)
            b.setStyleSheet("QToolButton{border:%s;border-radius:4px;padding:0;}"
                            % ("2px solid palette(highlight)" if on else "1px solid #888"))

    def _on_click(self, key: str) -> None:
        self._cur = key
        self._mark()
        self.picked.emit(key)

    def _ask_color(self) -> None:
        start = QColor(self._cur) if self._cur.startswith("#") else QColor("#808080")
        c = QColorDialog.getColor(start, self, self._pick_title)
        if c.isValid():
            self.add_color(c.name())

    # ── 끌어서 차례 바꾸기 ──
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == ev.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            self._press = (obj, ev.position().toPoint())
        elif t == ev.Type.MouseMove and self._press is not None and self._press[0] is obj:
            if (ev.position().toPoint() - self._press[1]).manhattanLength() >= QApplication.startDragDistance():
                self._press = None
                self._start_drag(obj)
                return True
        elif t == ev.Type.MouseButtonRelease:
            self._press = None
        return super().eventFilter(obj, ev)

    def _start_drag(self, btn) -> None:
        md = QMimeData()
        md.setData(MIME, str(btn.property("colorKey")).encode("utf-8"))
        dr = QDrag(btn)
        dr.setMimeData(md)
        dr.setPixmap(btn.icon().pixmap(SW - 6, SW - 6))
        dr.exec(Qt.DropAction.MoveAction)

    def drop_index(self, pos: QPoint) -> int:
        """놓은 자리(막대 좌표 x) → 끌어온 단추를 뺀 차례에서 넣을 자리."""
        x = pos.x()
        idx = 0
        for k in self._order:
            b = self._btns.get(k)
            if b is None:
                continue
            if x > b.geometry().center().x():
                idx += 1
        return idx

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(MIME):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(MIME):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        if not ev.mimeData().hasFormat(MIME):
            return
        key = bytes(ev.mimeData().data(MIME)).decode("utf-8")
        pos = ev.position().toPoint()
        idx = self.drop_index(pos)
        if key in self._order and self._order.index(key) < idx:
            idx -= 1                                     # 자기 자리를 뺀 차례로
        self.move_key(key, idx)
        ev.acceptProposedAction()
