# -*- coding: utf-8 -*-
"""사진 썸네일 줄 — 사진 모드에서 쪽 썸네일 자리에 (사진 보기 SOT 4.3·§6.3, D3·D9, 261104-2).

- 원천: 책갈피창에서 사진을 여럿 고르면 그 사진들, 하나면 그 폴더 전체(D3) — 앱이 `set_paths` 로 넣는다.
- 썸네일 그림은 **배경 워커 하나**가 Pillow 로 줄여 읽는다(`photo_io.read_scaled` — 해독 중 GIL 을 놓는다, 응답성 SOT §6).
  보이는 칸부터, 스크롤하면 그 자리부터 다시(앞 일은 세대 토큰으로 버린다 — 응답성 SOT §4 ①·⑦).
- 캐시(D9): 사용자 데이터 폴더 `photo_thumbs\\` 에 작은 JPEG — 키 = 경로·크기·수정시각·썸네일 크기. 사진 폴더에는 아무것도 쓰지 않는다.
  두 번째부터는 디스크 캐시를 읽는다(같은 사진을 두 번 줄여 읽지 않는다 — 응답성 SOT §4.5).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PyQt6.QtCore import QObject, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem

THUMB_BOX = 256                 # 줄여 읽는 긴 변(고해상도 화면 2배) — 캐시 키에 들어간다
CACHE_DIRNAME = "photo_thumbs"
CACHE_QUALITY = 82
CACHE_VERSION = 2               # 캐시 그림을 만드는 규칙이 바뀌면 올린다(2 = 색 관리 sRGB, 261104-2)
CACHE_MAX_BYTES = 300 * 1024 * 1024     # D9 용량 상한 — 넘으면 오래 안 쓴 것부터 지운다(썸네일 약 2만 장)
_PRUNED = {"done": False}
RESCAN_MS = 150                 # 스크롤이 멈추면 그 자리부터 다시 고른다
KEY_ACTIVATE_MS = 120           # 키(↑↓·PageUp/Down·Home/End)로 고른 칸을 본문에 — 꾹 누르면 멈춘 칸만(261104-3 사용자 보고)
_PATH_ROLE = Qt.ItemDataRole.UserRole


def cache_dir() -> Path:
    from viewer.settings_store import settings_dir
    return settings_dir() / CACHE_DIRNAME


def cache_key(path: str, box: int = THUMB_BOX) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    raw = "%s|%d|%d|%d|v%d" % (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns, box, CACHE_VERSION)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def load_thumb(path: str, box: int = THUMB_BOX) -> QImage:
    """캐시에 있으면 읽고, 없으면 줄여 읽어 캐시에 남긴다 — 배경 스레드에서 부른다(QImage 만 쓴다)."""
    key = cache_key(path, box)
    f = (cache_dir() / (key + ".jpg")) if key else None
    if f is not None and f.is_file():
        img = QImage(str(f))                              # 작은 JPEG — 짧다
        if not img.isNull():
            try:
                os.utime(f)                               # 쓴 때를 새로 — 용량 상한은 오래 안 쓴 것부터 지운다
            except OSError:
                pass
            return img
    from viewer.photo_io import read_scaled
    img, _w, _h = read_scaled(path, box, auto_transform=True)
    if f is not None and not img.isNull():
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            if img.save(str(tmp), "JPG", CACHE_QUALITY):
                os.replace(tmp, f)
        except OSError:
            pass
    return img


def prune_cache(max_bytes: int = CACHE_MAX_BYTES) -> int:
    """캐시 폴더가 상한을 넘으면 오래 안 쓴 것(수정 시각 — 읽을 때 새로 찍는다)부터 지운다. 지운 개수. 배경에서 부른다."""
    d = cache_dir()
    try:
        files = [(e.stat().st_mtime, e.stat().st_size, e.path) for e in os.scandir(d) if e.is_file() and e.name.endswith(".jpg")]
    except OSError:
        return 0
    total = sum(sz for _m, sz, _p in files)
    if total <= max_bytes:
        return 0
    n = 0
    for _m, sz, p in sorted(files):
        if total <= max_bytes * 0.9:                      # 10% 여유를 두고 멈춘다 — 매번 지우지 않게
            break
        try:
            os.remove(p)
            total -= sz
            n += 1
        except OSError:
            pass
    return n


def _modifying() -> bool:
    """Ctrl·Shift 를 누른 채인가 — 여러 장 고르는 중이면 본문을 바꾸지 않는다."""
    from PyQt6.QtWidgets import QApplication
    m = QApplication.keyboardModifiers()
    return bool(m & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))


def label_text(path, w: int = 0, h: int = 0, unreadable: bool = False) -> str:
    """칸 아래 글 — 이름(확장자 없이) 다음 줄에 원본 픽셀 크기(EXIF 방향 뒤). 모르면 줄만 비워 둔다(칸 높이가 흔들리지 않게)."""
    from viewer.i18n import tr
    second = tr("열 수 없음") if unreadable else ("%d × %d" % (w, h) if w and h else " ")
    return Path(str(path)).stem + "\n" + second


class PhotoThumbWorker(QObject):
    """썸네일 그림을 배경에서 만든다(응답성 SOT §4.4 감사표 한 행)."""
    done = pyqtSignal(int, str, QImage, int, int)     # 세대, 경로, 썸네일, 보이는 폭·높이(EXIF 방향 뒤 원본 픽셀, 못 읽으면 0)
    finished = pyqtSignal()

    def __init__(self, gen: int, paths, box: int = THUMB_BOX):
        super().__init__()
        self.gen, self.paths, self.box = gen, list(paths), box
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        from viewer import pacing
        try:
            for p in self.paths:
                if self._cancel:
                    break
                try:
                    img = load_thumb(p, self.box)
                except Exception:
                    img = QImage()
                from viewer.photo_io import oriented_size
                w, h = oriented_size(p)                  # 머리만 — 썸네일만 보고 원본 크기를 알게(261104-3 사용자 지시)
                self.done.emit(self.gen, p, img, int(w), int(h))
                pacing.pace(self)
            if not self._cancel and not _PRUNED["done"]:
                _PRUNED["done"] = True                    # 실행마다 한 번 — 캐시 용량 상한(D9)
                prune_cache()
        finally:
            self.finished.emit()


class PhotoStrip(QListWidget):
    """사진 썸네일 줄 — 한 칸 = 사진 하나, 아래 줄에 이름(확장자 없이)."""
    photoActivated = pyqtSignal(str)
    menuRequested = pyqtSignal(str, object)       # 261104-3(사진 보기 SOT 4.20): 우클릭 — (사진 경로, 전역 위치)
    deleteRequested = pyqtSignal(list)            # 261104-4(사진 보기 SOT 4.25): Del — 고른 사진(없으면 지금 칸)

    def __init__(self, icon_w: int = 130, parent=None):
        super().__init__(parent)
        self.setObjectName("photoStrip")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.TopToBottom)
        self.setWrapping(False)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setWordWrap(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 261104-3(사용자 지시 '썸네일을 보면서 2개 이상 선택'): Ctrl·Shift+클릭으로 여러 장 — 고르기만 하고 본문은 그대로(4.20)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._icon_w = icon_w
        self.setIconSize(QSize(icon_w, int(icon_w * 0.75)))
        self._paths: list = []
        self._items: dict = {}
        self._done: set = set()
        self._gen = 0
        self._worker = None
        self._keep: list = []
        self._placeholder = self._make_placeholder()
        self._rescan = QTimer(self)
        self._rescan.setSingleShot(True)
        self._rescan.setInterval(RESCAN_MS)
        self._rescan.timeout.connect(self._restart_from_visible)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._rescan.start())
        self.itemClicked.connect(self._on_clicked)
        self.rotation_provider = None             # 경로 → 보기 회전(시계 방향 도) — 앱이 넣는다(4.16 의 photo_rot 를 썸네일에도)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)
        # 261104-3(사용자 보고 '썸네일을 위아래로 이동할 경우 본화면이 안 바뀜'): 클릭만 이었다 — 지금 칸이 바뀌면(키) 본문도.
        #   앱이 고르는 칸(set_current·set_paths)은 신호를 막아 되먹임이 없다.
        self._key_pick = QTimer(self)
        self._key_pick.setSingleShot(True)
        self._key_pick.setInterval(KEY_ACTIVATE_MS)
        self._key_pick.timeout.connect(self._activate_current)
        self.currentItemChanged.connect(lambda cur, _prev: cur is not None and not _modifying() and self._key_pick.start())

    def _make_placeholder(self) -> QIcon:
        pm = QPixmap(self.iconSize())
        pm.fill(QColor(128, 128, 128, 60))
        return QIcon(pm)

    # ── 바깥에서 ──────────────────────────────────────
    def paths(self) -> list:
        return list(self._paths)

    def set_paths(self, paths, current: str | None = None) -> None:
        """목록을 바꾼다 — 같은 목록이면 지금 사진만 고른다(다시 만들지 않는다)."""
        paths = [str(p) for p in paths]
        if paths == self._paths:
            self.set_current(current)
            return
        self._stop()
        self._paths = paths
        self._items = {}
        self._done = set()
        self.setUpdatesEnabled(False)
        self.blockSignals(True)                  # 다시 채우는 동안 '지금 칸 바뀜' 을 내지 않는다
        try:
            self.clear()
            for p in paths:
                it = QListWidgetItem(self._placeholder, label_text(p))
                it.setData(_PATH_ROLE, p)
                it.setToolTip(Path(p).name)
                it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
                self.addItem(it)
                self._items[p] = it
        finally:
            self.blockSignals(False)
            self.setUpdatesEnabled(True)
        self.set_current(current)
        self._restart_from_visible()

    def set_current(self, path: str | None) -> None:
        it = self._items.get(str(path)) if path else None
        if it is None:
            return
        self.blockSignals(True)
        if it.isSelected() and len(self.selectedItems()) > 1:
            # 여러 장 골라 둔 채 그중 하나를 열었다 — 고른 것을 지우지 않고 '지금 칸' 만 옮긴다
            from PyQt6.QtCore import QItemSelectionModel
            self.selectionModel().setCurrentIndex(self.indexFromItem(it), QItemSelectionModel.SelectionFlag.NoUpdate)
        else:
            self.setCurrentItem(it)
        self.blockSignals(False)
        self.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)

    def selected_paths(self) -> list:
        """고른 칸의 사진 경로 — 줄 차례대로."""
        sel = {id(x) for x in self.selectedItems()}
        return [p for p in self._paths if id(self._items.get(p)) in sel]

    def stop(self) -> None:
        self._stop()

    def refresh(self, path: str) -> None:
        """한 사진의 썸네일을 다시 만든다(방향 저장 뒤 — 수정 시각이 바뀌어 캐시 키도 새로, 사진 보기 SOT 4.17)."""
        p = str(path)
        it = self._items.get(p)
        if it is None:
            return
        self._done.discard(p)
        it.setIcon(self._placeholder)
        it.setText(label_text(p))
        self._restart_from_visible()

    # ── 속 ─────────────────────────────────────────────
    def _stop(self):
        self._gen += 1
        w, self._worker = self._worker, None
        if w is not None:
            w.request_cancel()

    def _first_visible_row(self) -> int:
        it = self.itemAt(5, 5)
        return self.row(it) if it is not None else max(0, self.currentRow())

    def _restart_from_visible(self):
        """보이는 칸부터 아직 없는 그림을 만든다 — 앞 일은 버린다."""
        if not self._paths:
            return
        start = self._first_visible_row()
        order = self._paths[start:] + self._paths[:start][::-1]
        todo = [p for p in order if p not in self._done]
        self._stop()
        if not todo:
            return
        from viewer.workers import run_in_thread
        w = PhotoThumbWorker(self._gen, todo)
        w.done.connect(self._on_done)
        self._worker = w
        run_in_thread(w, self._keep)

    def _on_done(self, gen: int, path: str, img: QImage, w: int = 0, h: int = 0):
        if gen != self._gen:
            return
        self._done.add(path)
        it = self._items.get(path)
        if it is None:
            return
        it.setText(label_text(path, w, h, unreadable=img.isNull() and not w))
        if img.isNull():
            return
        rot = 0
        if self.rotation_provider is not None:
            try:
                rot = int(self.rotation_provider(path) or 0) % 360
            except Exception:
                rot = 0
        if rot:
            from PyQt6.QtGui import QTransform
            img = img.transformed(QTransform().rotate(rot))      # 작은 썸네일만 — 가볍다
        pm = QPixmap.fromImage(img).scaled(self.iconSize(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        it.setIcon(QIcon(pm))

    def _on_clicked(self, it):
        self._key_pick.stop()                    # 클릭은 바로(타이머와 겹쳐 두 번 열지 않는다)
        if _modifying():
            return                               # Ctrl·Shift+클릭은 고르기만(본문은 그대로)
        p = it.data(_PATH_ROLE)
        if p:
            self.photoActivated.emit(str(p))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Delete:
            ps = self.selected_paths()
            if not ps and self.currentItem() is not None:
                ps = [str(self.currentItem().data(_PATH_ROLE))]
            if ps:
                self.deleteRequested.emit(ps)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _on_menu(self, pos):
        it = self.itemAt(pos)
        p = it.data(_PATH_ROLE) if it is not None else None
        if p:
            self.menuRequested.emit(str(p), self.viewport().mapToGlobal(pos))

    def _activate_current(self):
        it = self.currentItem()
        p = it.data(_PATH_ROLE) if it is not None else None
        if p:
            self.photoActivated.emit(str(p))
