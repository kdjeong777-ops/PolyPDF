"""260611-85/86: 전체화면 하이퍼링크 미디어 오버레이.

- 사진/동영상 하이퍼링크를 앱 안의 '전체화면' 오버레이로 앞에 띄워 보여준다.
- 좌클릭(미디어 영역) / 우상단 ✕ / ESC → 닫힘(시퀀스 모드면 다음 항목으로).
- → 다음 하이퍼링크 / ← 이전 하이퍼링크(마지막에서 → 는 닫힘).
- 동영상: 하단 컨트롤바(마우스가 하단에 오면 슬라이드로 표시, 없으면 숨김) —
  재생/일시정지·처음부터·음소거·소리±·탐색바(클릭/드래그로 실시간 위치 이동).
  컨트롤바 위에서는 좌클릭해도 닫히거나 다음 링크로 넘어가지 않는다.
- 유튜브 하이퍼링크는 앱 내 임베드가 아니라 기본 웹브라우저의 일반 watch 페이지로
  연다(260611-96) — `open_youtube_external`. 임베드(embed)는 일부 환경에서 오류
  152/153 을 내므로 watch 페이지로 띄운다(전체화면은 플레이어에서 사용자가 직접).

지원 코덱(Qt 6.11 FFmpeg 백엔드, Windows): 컨테이너 MP4/MOV/MKV/WebM/AVI,
영상 H.264/H.265(HEVC)/VP8/VP9/AV1/MPEG-4, 음성 AAC/MP3/Opus/Vorbis/FLAC/AC-3.
권장 포맷은 MP4(H.264 + AAC).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, QTimer, QRect, QPropertyAnimation, QEvent
from PyQt6.QtGui import QPixmap, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QWidget, QLabel, QPushButton, QSlider, QHBoxLayout, QStyle)

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".mpg", ".mpeg"}

SUPPORTED_TEXT = (
    "지원: MP4/MOV/MKV/WebM/AVI · H.264·H.265·VP9·AV1 · AAC·MP3·Opus (권장 MP4=H.264+AAC)")


def media_kind(path) -> str | None:
    ext = Path(str(path)).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    return None


def is_youtube_url(u) -> bool:
    """260611-92: 유튜브 영상 주소면 True(외부 브라우저 전체화면 재생 대상)."""
    import re
    return bool(re.search(
        r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/|live/|v/))[A-Za-z0-9_-]{6,}",
        str(u or "")))


def _youtube_id_start(url):
    """유튜브 URL → (video_id, start_sec|"") 또는 None."""
    import re
    m = re.search(
        r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/|live/|v/))([A-Za-z0-9_-]{6,})",
        str(url))
    if not m:
        return None
    ts = re.search(r"[?&](?:t|start)=(\d+)", str(url))
    return m.group(1), (ts.group(1) if ts else "")


def youtube_watch_url(url: str) -> str:
    """유튜브 URL → 표준 watch 주소(시작초 t 보존)."""
    info = _youtube_id_start(url)
    if info:
        vid, start = info
        t = f"&t={start}" if start else ""
        return f"https://www.youtube.com/watch?v={vid}{t}"
    return str(url)


def open_youtube_external(url) -> bool:
    """260611-96: 유튜브를 기본 웹브라우저에서 일반 watch 페이지로 연다.

    임베드(embed) 주소는 일부 환경에서 '오류 152/153(플레이어 구성 오류)' 을 내므로,
    항상 정상 재생되는 watch 페이지를 기본 브라우저 탭으로 띄운다(전체화면은 사용자가
    플레이어에서 직접).
    """
    try:
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(youtube_watch_url(url)))
        return True
    except Exception:
        return False


class _SeekSlider(QSlider):
    """260611-86: 트랙의 아무 위치나 클릭하면 그 지점으로, 누른 채 움직이면 실시간 탐색."""

    def _val_at(self, x):
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                              int(x), self.width())

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._val_at(e.position().x()))
            self.sliderPressed.emit()
            self.sliderMoved.emit(self.value())
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.setValue(self._val_at(e.position().x()))
            self.sliderMoved.emit(self.value())
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.sliderReleased.emit(); e.accept()
        else:
            super().mouseReleaseEvent(e)


class MediaOverlay(QWidget):
    """이미지/동영상 항목 리스트를 전체화면으로 차례로 보여주는 오버레이."""

    BAR_H = 60

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet("background:#000;")
        self.setMouseTracking(True)
        self._items = []
        self._idx = 0
        self._player = None
        self._audio = None
        self._seeking = False
        self._bar_shown = False

        self._img = QLabel(self)
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setStyleSheet("background:#000;")
        self._img.setMouseTracking(True)
        self._img.installEventFilter(self)

        # 260611-88: QVideoWidget 은 네이티브 서피스라 위에 올린 컨트롤바가 가려짐 →
        #   QGraphicsView + QGraphicsVideoItem 으로 렌더해 일반 위젯(컨트롤바)이 위에 합성되게.
        from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene
        from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
        self._scene = QGraphicsScene(self)
        self._vitem = QGraphicsVideoItem()
        self._scene.addItem(self._vitem)
        self._vitem.nativeSizeChanged.connect(lambda _s: self._fit_video())
        self._gview = QGraphicsView(self._scene, self)
        self._gview.setStyleSheet("background:#000;border:none;")
        self._gview.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._gview.setInteractive(False)
        self._gview.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._gview.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._gview.setMouseTracking(True)
        self._gview.viewport().setMouseTracking(True)
        self._gview.viewport().installEventFilter(self)
        self._gview.hide()

        # 상단 안내(항상 표시) — 파일명 + 조작 안내
        self._hint = QLabel("", self)
        self._hint.setStyleSheet("color:#ddd;font-size:13px;background:rgba(0,0,0,0.35);"
                                 "padding:4px 10px;border-radius:6px;")

        # 하단 컨트롤바(자동 숨김·슬라이드) — 동영상 전용
        self._bar = QWidget(self)
        self._bar.setStyleSheet("background:rgba(18,18,22,0.92);")
        bl = QHBoxLayout(self._bar); bl.setContentsMargins(14, 6, 14, 6); bl.setSpacing(8)
        cbtn = ("QPushButton{background:#333;color:#fff;border:none;border-radius:5px;"
                "min-width:38px;min-height:30px;font-size:15px;}"
                "QPushButton:hover{background:#454545;}")
        self._btn_restart = QPushButton("⏮"); self._btn_restart.setStyleSheet(cbtn)
        self._btn_restart.clicked.connect(self._restart)
        self._btn_play = QPushButton("⏸"); self._btn_play.setStyleSheet(cbtn)
        self._btn_play.clicked.connect(self._toggle_play)
        self._btn_mute = QPushButton("🔊"); self._btn_mute.setStyleSheet(cbtn)
        self._btn_mute.clicked.connect(self._toggle_mute)
        self._btn_voldn = QPushButton("🔉−"); self._btn_voldn.setStyleSheet(cbtn)
        self._btn_voldn.clicked.connect(lambda: self._add_volume(-0.1))
        self._btn_volup = QPushButton("🔊＋"); self._btn_volup.setStyleSheet(cbtn)
        self._btn_volup.clicked.connect(lambda: self._add_volume(0.1))
        self._slider = _SeekSlider(Qt.Orientation.Horizontal)
        self._slider.setStyleSheet(
            "QSlider::groove:horizontal{height:6px;background:#555;border-radius:3px;}"
            "QSlider::sub-page:horizontal{background:#1e88e5;border-radius:3px;}"
            "QSlider::handle:horizontal{background:#fff;width:14px;margin:-5px 0;border-radius:7px;}")
        self._slider.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self._slider.sliderReleased.connect(self._seek_release)
        self._slider.sliderMoved.connect(self._on_slider_moved)
        self._lbl_time = QLabel("0:00 / 0:00"); self._lbl_time.setStyleSheet("color:#eee;")
        for w in (self._btn_restart, self._btn_play, self._btn_mute, self._btn_voldn, self._btn_volup):
            bl.addWidget(w)
        bl.addWidget(self._slider, 1); bl.addWidget(self._lbl_time)
        self._bar.hide()

        # 닫기 ✕ (우상단, 항상 표시)
        self._x = QPushButton("✕", self)
        self._x.setFixedSize(44, 44)
        self._x.setStyleSheet(
            "QPushButton{background:rgba(0,0,0,0.45);color:#fff;border:1px solid #888;"
            "border-radius:22px;font-size:20px;font-weight:bold;}"
            "QPushButton:hover{background:rgba(220,40,40,0.95);}")
        self._x.clicked.connect(self.close)

        self._bar_anim = QPropertyAnimation(self._bar, b"geometry", self)
        self._bar_anim.setDuration(160)
        self._hide_timer = QTimer(self); self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._maybe_hide_bar)
        # 260611-87: QVideoWidget 는 내부 렌더 자식이 마우스 이벤트를 가로채 mouseMove 가
        #   잘 안 온다 → 커서 위치를 주기적으로 폴링해 하단 7% 진입 여부로 컨트롤바 토글.
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(110)
        self._cursor_timer.timeout.connect(self._poll_cursor)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ---- 항목 표시 ----
    def show_items(self, items, idx=0):
        self._items = list(items or [])
        self._idx = max(0, min(idx, len(self._items) - 1)) if self._items else 0
        if not self._items:
            return False
        self.showFullScreen()
        self.raise_(); self.activateWindow(); self.setFocus()
        self._relayout(); self._show_current()
        return True

    def _show_current(self):
        self._teardown_player()
        if not (0 <= self._idx < len(self._items)):
            self.close(); return
        it = self._items[self._idx]
        seq = len(self._items) > 1
        nav = ("  ·  →다음 / ←이전 / 좌클릭=다음 / ✕·ESC=닫기" if seq
               else "  ·  좌클릭·✕·ESC=닫기")
        pos = f"  [{self._idx + 1}/{len(self._items)}]" if seq else ""
        kind = it.get("type")
        if kind == "image":
            self._cursor_timer.stop()
            self._gview.hide(); self._set_bar(False, animate=False); self._bar.hide()
            self._img.show()
            self._cur_pixmap = QPixmap(it["path"])
            if self._cur_pixmap.isNull():
                self._img.setText("이미지를 열 수 없습니다.\n" + str(it.get("name", "")))
                self._img.setStyleSheet("color:#ddd;font-size:20px;background:#000;")
            self._hint.setText(f"{it.get('name','')}{pos}{nav}")
        else:
            self._img.hide(); self._cur_pixmap = None
            self._gview.show(); self._bar.show()
            self._start_video(it["path"])
            self._hint.setText(f"{it.get('name','')}{pos}{nav}   ·   {SUPPORTED_TEXT}")
            self._set_bar(True)             # 시작 시 잠깐 보였다가 자동 숨김
            self._hide_timer.start(2500)
            self._cursor_timer.start()      # 커서 폴링으로 하단 진입 감지
        self._relayout()
        self._x.raise_(); self._hint.raise_()

    def _advance(self):
        if self._idx + 1 < len(self._items):
            self._idx += 1; self._show_current()
        else:
            self.close()

    def _prev(self):
        if self._idx > 0:
            self._idx -= 1; self._show_current()

    # ---- 동영상 ----
    def _start_video(self, path):
        from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.9)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._vitem)
        self._player.positionChanged.connect(self._on_pos)
        self._player.durationChanged.connect(self._on_dur)
        self._player.errorOccurred.connect(self._on_err)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        self._btn_play.setText("⏸"); self._update_mute_icon()

    def _teardown_player(self):
        if self._player is not None:
            try:
                self._player.stop(); self._player.setVideoOutput(None)
                self._player.deleteLater()
            except Exception:
                pass
        self._player = None
        if self._audio is not None:
            try:
                self._audio.deleteLater()
            except Exception:
                pass
        self._audio = None

    def _toggle_play(self):
        if self._player is None:
            return
        from PyQt6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause(); self._btn_play.setText("▶")
        else:
            self._player.play(); self._btn_play.setText("⏸")

    def _restart(self):
        if self._player is not None:
            self._player.setPosition(0); self._player.play(); self._btn_play.setText("⏸")

    def _toggle_mute(self):
        if self._audio is not None:
            self._audio.setMuted(not self._audio.isMuted()); self._update_mute_icon()

    def _add_volume(self, d):
        if self._audio is not None:
            v = max(0.0, min(1.0, self._audio.volume() + d))
            self._audio.setVolume(v)
            if v > 0 and self._audio.isMuted():
                self._audio.setMuted(False)
            self._update_mute_icon()

    def _update_mute_icon(self):
        if self._audio is None:
            return
        muted = self._audio.isMuted() or self._audio.volume() <= 0.0
        self._btn_mute.setText("🔇" if muted else "🔊")

    def _on_slider_moved(self, v):
        if self._player is not None:
            self._player.setPosition(int(v))     # 드래그/클릭 실시간 탐색

    def _seek_release(self):
        if self._player is not None:
            self._player.setPosition(self._slider.value())
        self._seeking = False

    def _on_pos(self, ms):
        if not self._seeking:
            self._slider.setValue(int(ms))
        self._lbl_time.setText(f"{_fmt(ms)} / {_fmt(self._slider.maximum())}")

    def _on_dur(self, ms):
        self._slider.setRange(0, max(0, int(ms)))
        self._lbl_time.setText(f"{_fmt(self._slider.value())} / {_fmt(ms)}")

    def _on_err(self, *a):
        self._img.show(); self._gview.hide(); self._bar.hide()
        self._cur_pixmap = None
        self._img.setText("이 동영상을 재생할 수 없습니다(코덱 미지원).\n\n" + SUPPORTED_TEXT)
        self._img.setStyleSheet("color:#ddd;font-size:18px;background:#000;")

    # ---- 컨트롤바 자동 숨김(슬라이드) ----
    def _bar_rect(self, shown):
        w, h = self.width(), self.height()
        y = (h - self.BAR_H) if shown else h
        return QRect(0, y, w, self.BAR_H)

    def _set_bar(self, shown, animate=True):
        if self._player is None or not self._gview.isVisible():
            shown = False
        if shown == self._bar_shown and animate:
            return
        self._bar_shown = shown
        end = self._bar_rect(shown)
        if animate:
            self._bar_anim.stop()
            self._bar_anim.setStartValue(self._bar.geometry())
            self._bar_anim.setEndValue(end)
            self._bar_anim.start()
        else:
            self._bar.setGeometry(end)

    def _zone_top(self):
        """260611-87: 컨트롤바를 띄우는 하단 트리거 영역의 상단 y(하단 7%, 단 바 영역 포함)."""
        h = self.height()
        return h - max(int(h * 0.07), self.BAR_H + 12)

    def _poll_cursor(self):
        from PyQt6.QtGui import QCursor
        if self._player is None or not self._gview.isVisible() or not self.isVisible():
            return
        p = self.mapFromGlobal(QCursor.pos())
        inside = (0 <= p.x() <= self.width())
        self._set_bar(inside and p.y() >= self._zone_top())

    def _maybe_hide_bar(self):
        from PyQt6.QtGui import QCursor
        p = self.mapFromGlobal(QCursor.pos())
        if p.y() < self._zone_top():
            self._set_bar(False)

    def _on_mouse_y(self, y):
        if self._player is None or not self._gview.isVisible():
            return
        self._set_bar(y >= self._zone_top())

    # ---- 레이아웃/이벤트 ----
    def _relayout(self):
        w, h = self.width(), self.height()
        self._img.setGeometry(0, 0, w, h)
        self._gview.setGeometry(0, 0, w, h); self._fit_video()
        self._bar.setGeometry(self._bar_rect(self._bar_shown))
        self._x.move(w - self._x.width() - 16, 16)
        self._x.raise_()
        self._hint.adjustSize()
        self._hint.move(16, 14); self._hint.raise_()
        self._bar.raise_()
        pm = getattr(self, "_cur_pixmap", None)
        if self._img.isVisible() and pm is not None and not pm.isNull():
            self._img.setPixmap(pm.scaled(self._img.size(),
                                          Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        self._relayout(); super().resizeEvent(e)

    def _fit_video(self):
        """260611-88: 영상 아이템을 뷰에 꽉 차게(비율 유지) 맞춤."""
        try:
            ns = self._vitem.nativeSize()
            if ns.isValid() and ns.width() > 0 and ns.height() > 0:
                self._vitem.setSize(ns)
                self._scene.setSceneRect(self._vitem.boundingRect())
                self._gview.fitInView(self._vitem, Qt.AspectRatioMode.KeepAspectRatio)
        except Exception:
            pass

    def eventFilter(self, obj, ev):
        if obj is self._img or obj is self._gview.viewport():
            t = ev.type()
            if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                self._advance(); return True
            if t == QEvent.Type.MouseMove:
                self._on_mouse_y(int(ev.position().y())); return False
        return super().eventFilter(obj, ev)

    def mouseMoveEvent(self, e):
        self._on_mouse_y(int(e.position().y())); super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._advance()
        else:
            super().mousePressEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.close()
        elif k == Qt.Key.Key_Right:
            self._advance()           # 다음 링크(마지막에선 닫힘)
        elif k == Qt.Key.Key_Left:
            self._prev()              # 이전 링크
        elif k == Qt.Key.Key_Space and self._player is not None:
            self._toggle_play()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        try:
            self._cursor_timer.stop()
        except Exception:
            pass
        self._teardown_player()
        super().closeEvent(e)
        self.deleteLater()


def _fmt(ms):
    s = int((ms or 0) / 1000)
    return f"{s // 60}:{s % 60:02d}"
