# -*- coding: utf-8 -*-
"""서명 자리(초안) — 본문 위 작은 위젯과 서명 자리 띠 (보안 SOT §3.10).

자리는 본문 뷰포트의 자식 위젯이다(하이퍼링크 단추와 같은 방식) — 지금 쪽의 자리만, 줌·스크롤·쪽 넘김 때
`MainView._position_hl_overlay` 가 `reposition()` 을 부른다. 자리 자료(쪽 좌표·미리보기)는 앱이 `provider` 로 준다:
`provider(경로, 쪽) -> [{"id", "rect"(그림 상자 pt), "strip"(아래 글자 줄 pt), "pix"(QPixmap|None), "fixed", "kind"}]`.

조작: 끌기 = 옮기기 · 오른쪽 아래 손잡이 = 크기(그림 비율 유지, Shift = 자유) · Delete = 지우기 · 우클릭 = 메뉴(앱이 띄운다).
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, QPoint, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from viewer.i18n import tr

HANDLE_PX = 9
MIN_PX = 14
ACCENT = "#1565c0"          # 디자인 SOT §2.16 — 서명 자리 테두리(테마 무관, 본문 위)


class _DraftBox(QWidget):
    def __init__(self, layer: "SignDraftLayer", d: dict):
        super().__init__(layer.viewport())
        self.layer = layer
        self.d = d
        self._drag = None              # (모드, 누른 자리, 처음 상자)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)
        self.setToolTip(tr("서명 자리 — 끌어 옮기기 · 오른쪽 아래 모서리로 크기 · Delete 로 지우기 · 우클릭 메뉴")
                        if not d.get("fixed") else tr("빈 서명 칸의 서명 자리 — Delete 로 지우기 · 우클릭 메뉴"))

    # ---- 그리기 ----
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self.rect()
        pix = self.d.get("pix")
        if pix is not None and not pix.isNull():
            p.drawPixmap(r, pix)
        else:
            p.fillRect(r, QColor(21, 101, 192, 28))
        pen = QPen(QColor(ACCENT))
        pen.setWidth(2 if self.hasFocus() else 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(r.adjusted(0, 0, -1, -1))
        if self.d.get("kind") == "image":
            p.setPen(QColor(ACCENT))
            f = p.font()
            f.setPointSizeF(7.5)
            p.setFont(f)
            p.drawText(r.adjusted(3, 1, -3, -1), int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft), tr("그림만"))
        if not self.d.get("fixed"):
            p.fillRect(QRect(r.right() - HANDLE_PX + 1, r.bottom() - HANDLE_PX + 1, HANDLE_PX, HANDLE_PX), QColor(ACCENT))
        p.end()

    def _in_handle(self, pos: QPoint) -> bool:
        return (not self.d.get("fixed") and pos.x() >= self.width() - HANDLE_PX - 2
                and pos.y() >= self.height() - HANDLE_PX - 2)

    # ---- 마우스·키 ----
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        self.setFocus()
        self.raise_()
        if self.d.get("fixed"):
            self.update()
            return
        mode = "size" if self._in_handle(e.position().toPoint()) else "move"
        self._drag = (mode, e.globalPosition().toPoint(), QRect(self.geometry()))
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._drag is None:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if self._in_handle(pos)
                           else (Qt.CursorShape.ArrowCursor if self.d.get("fixed") else Qt.CursorShape.SizeAllCursor))
            return
        mode, g0, r0 = self._drag
        dv = e.globalPosition().toPoint() - g0
        page = self.layer.page_rect_px()
        if page is None:
            return
        strip = int(round(self.d.get("strip", 0.0) * self.layer.scale()))
        if mode == "move":
            r = QRect(r0)
            r.moveTo(r0.topLeft() + dv)
            x = max(page.left(), min(page.right() - r.width() + 1, r.x()))
            y = max(page.top(), min(page.bottom() - r.height() + 1, r.y()))
            r.moveTo(x, y)
        else:
            img_w0, img_h0 = r0.width(), max(1, r0.height() - strip)
            w = max(MIN_PX, min(page.right() - r0.left() + 1, img_w0 + dv.x()))
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                ih = max(MIN_PX, img_h0 + dv.y())
            else:
                ih = max(MIN_PX, int(round(w * img_h0 / max(1, img_w0))))
            if r0.top() + ih + strip - 1 > page.bottom():          # 아래로 넘치면 쪽 안에 맞춘다
                ih = max(MIN_PX, page.bottom() - r0.top() - strip + 1)
                if not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    w = max(MIN_PX, int(round(ih * img_w0 / max(1, img_h0))))
            r = QRect(r0.left(), r0.top(), w, ih + strip)
        self.setGeometry(r)

    def mouseReleaseEvent(self, e):
        if self._drag is None or e.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(e)
        self._drag = None
        self.layer.box_moved(self)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.layer.removed.emit(str(self.d["id"]))
            return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        self.setFocus()
        self.layer.menuRequested.emit(str(self.d["id"]), e.globalPos())

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()


class SignDraftLayer(QObject):
    """한 `MainView` 의 서명 자리 위젯들. `mv.sign_draft_layer` 로 붙는다."""
    changed = pyqtSignal(str, object)          # id, 그림 상자(쪽 좌표 pt, (x0, y0, x1, y1))
    removed = pyqtSignal(str)
    menuRequested = pyqtSignal(str, object)    # id, 전역 QPoint

    def __init__(self, mv, provider):
        super().__init__(mv)
        self.mv = mv
        self.provider = provider
        self.boxes: list[_DraftBox] = []
        self._key = None
        mv.sign_draft_layer = self

    def viewport(self):
        return self.mv.view.viewport()

    def _page(self):
        mv = self.mv
        doc = getattr(getattr(mv, "_doc", None), "doc", None)
        cur = mv.current_file() if hasattr(mv, "current_file") else None
        if doc is None or not cur or getattr(mv, "_is_image", False):
            return None
        try:
            if mv.is_two_page_mode():
                return None
            pi = int(mv.current_page())
            if (getattr(mv, "_rotations", {}) or {}).get(pi, 0):
                return None                      # 저장 전 회전이 걸린 쪽 — 자리를 숨긴다(SOT §3.10)
            return str(cur), pi, doc[pi].rect
        except Exception:
            return None

    def page_rect_px(self):
        pr = self.mv._page_view_rect()
        return QRect(pr) if pr is not None and pr.width() > 0 else None

    def scale(self) -> float:
        pg = self._page()
        pr = self.page_rect_px()
        if pg is None or pr is None or pg[2].width <= 0:
            return 1.0
        return pr.width() / float(pg[2].width)

    def refresh(self) -> None:
        """자리를 다시 만든다(자료가 바뀌었을 때)."""
        self._key = None
        self.reposition()

    def reposition(self) -> None:
        pg = self._page()
        if pg is None:
            self._clear()
            self._key = None
            return
        path, pi, _rect = pg
        items = list(self.provider(path, pi) or [])
        key = (path, pi, tuple((d["id"], tuple(d["rect"]), round(float(d.get("strip", 0)), 2), id(d.get("pix")),
                                d.get("kind")) for d in items))
        if key != self._key:
            self._clear()
            self.boxes = [_DraftBox(self, d) for d in items]
            self._key = key
        pr = self.page_rect_px()
        s = self.scale()
        for b in self.boxes:
            if pr is None:
                b.hide()
                continue
            x0, y0, x1, y1 = b.d["rect"]
            strip = float(b.d.get("strip", 0.0))
            b.setGeometry(QRectF(pr.left() + x0 * s, pr.top() + y0 * s, (x1 - x0) * s, (y1 - y0 + strip) * s).toRect())
            b.show()
            b.raise_()

    def _clear(self) -> None:
        for b in self.boxes:
            b.hide()
            b.deleteLater()
        self.boxes = []

    def box_moved(self, box: _DraftBox) -> None:
        pr = self.page_rect_px()
        s = self.scale()
        if pr is None or s <= 0:
            return
        g = box.geometry()
        strip = float(box.d.get("strip", 0.0))
        x0 = (g.left() - pr.left()) / s
        y0 = (g.top() - pr.top()) / s
        x1 = x0 + g.width() / s
        y1 = y0 + g.height() / s - strip
        self.changed.emit(str(box.d["id"]), (x0, y0, x1, max(y0 + 1.0, y1)))

    def box_for(self, draft_id: str):
        return next((b for b in self.boxes if str(b.d.get("id")) == str(draft_id)), None)


class SignDraftBand(QFrame):
    """서명 자리 띠 — '✍ 서명 자리 N개 …' + [서명 확정…] · [모두 지우기] (SOT §3.10, 색은 디자인 SOT §2.16)."""
    confirmRequested = pyqtSignal()
    clearRequested = pyqtSignal()
    BG = "#e3f2fd"

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 4, 2)
        self.label = QLabel("")
        self.btn_confirm = QPushButton(tr("서명 확정…"))
        self.btn_clear = QPushButton(tr("모두 지우기"))
        self.btn_confirm.clicked.connect(self.confirmRequested.emit)
        self.btn_clear.clicked.connect(self.clearRequested.emit)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.btn_confirm)
        lay.addWidget(self.btn_clear)
        self.setStyleSheet(f"SignDraftBand{{background:{self.BG};border-bottom:1px solid #c8c8c8;}}"
                           f"QLabel{{color:#1a1a1a;background:transparent;}}")
        self.hide()

    def show_counts(self, n_sign: int, n_image: int, edit_of: str = "") -> None:
        n = n_sign + n_image
        if n <= 0:
            self.hide()
            return
        text = tr("✍  서명 자리 {n}개(전자서명 {a} · 그림만 {b}) — 끌어 옮기기 · 모서리로 크기 · Delete 로 지우기").format(
            n=n, a=n_sign, b=n_image)
        if edit_of:
            text += tr(" · 확정하면 '{name}' 을 바꿉니다").format(name=edit_of)
        self.label.setText(text)
        self.setToolTip(text)
        self.show()
