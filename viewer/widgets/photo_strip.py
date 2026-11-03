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
RESCAN_MS = 150                 # 스크롤이 멈추면 그 자리부터 다시 고른다
_PATH_ROLE = Qt.ItemDataRole.UserRole


def cache_dir() -> Path:
    from viewer.settings_store import settings_dir
    return settings_dir() / CACHE_DIRNAME


def cache_key(path: str, box: int = THUMB_BOX) -> str | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    raw = "%s|%d|%d|%d" % (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns, box)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def load_thumb(path: str, box: int = THUMB_BOX) -> QImage:
    """캐시에 있으면 읽고, 없으면 줄여 읽어 캐시에 남긴다 — 배경 스레드에서 부른다(QImage 만 쓴다)."""
    key = cache_key(path, box)
    f = (cache_dir() / (key + ".jpg")) if key else None
    if f is not None and f.is_file():
        img = QImage(str(f))                              # 작은 JPEG — 짧다
        if not img.isNull():
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


class PhotoThumbWorker(QObject):
    """썸네일 그림을 배경에서 만든다(응답성 SOT §4.4 감사표 한 행)."""
    done = pyqtSignal(int, str, QImage)
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
                self.done.emit(self.gen, p, img)
                pacing.pace(self)
        finally:
            self.finished.emit()


class PhotoStrip(QListWidget):
    """사진 썸네일 줄 — 한 칸 = 사진 하나, 아래 줄에 이름(확장자 없이)."""
    photoActivated = pyqtSignal(str)

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
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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
        try:
            self.clear()
            for p in paths:
                it = QListWidgetItem(self._placeholder, Path(p).stem)
                it.setData(_PATH_ROLE, p)
                it.setToolTip(Path(p).name)
                it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
                self.addItem(it)
                self._items[p] = it
        finally:
            self.setUpdatesEnabled(True)
        self.set_current(current)
        self._restart_from_visible()

    def set_current(self, path: str | None) -> None:
        it = self._items.get(str(path)) if path else None
        if it is None:
            return
        self.blockSignals(True)
        self.setCurrentItem(it)
        self.blockSignals(False)
        self.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)

    def stop(self) -> None:
        self._stop()

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

    def _on_done(self, gen: int, path: str, img: QImage):
        if gen != self._gen:
            return
        self._done.add(path)
        it = self._items.get(path)
        if it is None or img.isNull():
            return
        pm = QPixmap.fromImage(img).scaled(self.iconSize(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        it.setIcon(QIcon(pm))

    def _on_clicked(self, it):
        p = it.data(_PATH_ROLE)
        if p:
            self.photoActivated.emit(str(p))
