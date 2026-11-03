# -*- coding: utf-8 -*-
"""사진 모드(PolyPix) — 앱 쪽 (사진 보기 SOT, 261104-2).

- **보기 종류**(사진 보기 SOT 4.10, D12): 환경설정의 'PDF 전용'(기본 — 사진 모드 없음)·'혼용'(PDF 모드 ↔ 사진 모드 토글).
  값은 `preferences` 안의 사진 묶음 `picture` 하나에 둔다(4.7·4.15 — 최상위 새 키는 옛 판이 저장하며 지운다).
- **모드 토글**(4.1, D1·D7): 리본 탭 줄 왼쪽 빈 칸 맨 앞의 브라운관 TV 단추. 창마다 모드 하나, 시작은 마지막 모드.
  파일을 지정해 뜬 창(새 창으로 PDF 열기·가상 프린터·탐색기 열기)은 늘 PDF 모드(D1).
- 모드가 바꾸는 것은 '원천' 뿐(4.2·위험 표 첫 줄) — 책갈피창이 보이는 확장자, 썸네일 원천, 즐겨찾기 목록. 화면 코드는 그대로.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QToolButton

from pathlib import Path

from viewer.i18n import tr

VIEW_PDF = "pdf"                 # 'PDF 전용' — 사진 모드 없음(기본)
VIEW_MIXED = "mixed"             # '혼용' — PDF 모드 ↔ 사진 모드
MODE_ICON_PX = 18                # 탭 줄 높이 안 — 탭 글자보다 조금 크게


class PhotoMixin:
    def _photo_init(self):
        self._photo_mode = False
        self._photo_forced_pdf = False           # 파일 인자로 뜬 창 — 늘 PDF 모드(D1)
        lf = self._ribbon.left_fill
        lay = QHBoxLayout(lf)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        b = QToolButton(lf)
        b.setObjectName("modeToggle")
        b.setAutoRaise(True)
        b.setIconSize(QSize(MODE_ICON_PX, MODE_ICON_PX))
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.clicked.connect(self._photo_toggle)
        lay.addWidget(b)
        lay.addStretch(1)                         # 빈 칸은 단추 뒤에서 늘어난다 — 탭 줄 가운데는 그대로(디자인 SOT §2.9.3)
        self._photo_btn = b
        self._photo_refresh_button()
        self._photo_apply_view_kind(restore=True)

    # ── 설정 묶음 ─────────────────────────────────────
    def _photo_prefs(self) -> dict:
        pic = self._prefs.get("picture")
        if not isinstance(pic, dict):
            pic = self._prefs["picture"] = {}
        return pic

    def _photo_view_kind(self) -> str:
        return VIEW_MIXED if self._photo_prefs().get("view_kind") == VIEW_MIXED else VIEW_PDF

    def _photo_enabled(self) -> bool:
        return self._photo_view_kind() == VIEW_MIXED

    def _photo_apply_view_kind(self, restore: bool = False):
        """보기 종류에 맞춘다 — PDF 전용이면 단추를 숨기고 사진 모드였으면 곧바로 PDF 모드로(4.10)."""
        on = self._photo_enabled()
        self._photo_btn.setVisible(on)
        if not on:
            if self._photo_mode:
                self._set_photo_mode(False)
            return
        if restore and not self._photo_forced_pdf and self._photo_prefs().get("mode") == "photo":
            self._set_photo_mode(True)

    def _photo_force_pdf(self):
        """파일 인자로 뜬 창 — 이 창은 PDF 모드로 시작한다(D1). 시작 복원보다 먼저 부른다."""
        self._photo_forced_pdf = True
        if self._photo_mode:
            self._set_photo_mode(False, remember=False)

    # ── 모드 ─────────────────────────────────────────
    def _photo_toggle(self, _checked=False):
        self._set_photo_mode(not self._photo_mode)

    def _set_photo_mode(self, on: bool, remember: bool = True):
        on = bool(on) and self._photo_enabled()
        if on == self._photo_mode:
            return
        self._photo_mode = on
        if remember:
            self._photo_prefs()["mode"] = "photo" if on else "pdf"
        self._photo_refresh_button()
        self._photo_on_mode_changed(on)

    def _photo_on_mode_changed(self, on: bool):
        """모드가 바뀐 뒤 — 원천을 바꾼다(4.2). 메인이 하는 일은 보이는 것 바꾸기뿐, 훑기·디코드는 배경(§6, 응답성 SOT §5)."""
        for bt in (getattr(self, "bookmark_tree", None), getattr(self, "bookmark_tree_right", None)):
            if bt is not None and hasattr(bt, "set_photo_mode"):
                bt.set_photo_mode(on)
        hook = getattr(self, "_photo_after_mode", None)
        if hook is not None:
            hook(on)

    def _photo_refresh_button(self, dark=None):
        from viewer.widgets.icons import mode_tv_icon
        b = getattr(self, "_photo_btn", None)
        if b is None:
            return
        b.setIcon(mode_tv_icon(self._photo_mode, dark, MODE_ICON_PX))
        tip = tr("PDF 모드로 바꾸기") if self._photo_mode else tr("사진 모드(PolyPix)로 바꾸기")
        b.setToolTip(tip)
        b.setAccessibleName(tip)

    # ── 본문 사진 (4.4·4.12) ─────────────────────────────
    def _is_photo_path(self, path) -> bool:
        from pathlib import Path as _P
        from viewer.image_page import PHOTO_EXTS
        return _P(str(path)).suffix.lower() in PHOTO_EXTS

    def _photo_list(self) -> list:
        """넘김 원천 하나(4.12) — 책갈피창에 보이는 차례 그대로의 사진 경로."""
        bt = self.bookmark_tree
        out = []
        for it in bt._iter_file_nodes():
            p = it.data(0, bt.DATA_FILE)
            if p and self._is_photo_path(p) and not it.isHidden():
                out.append(str(p))
        return out

    def _photo_after_open(self, path):
        """사진을 본문에 연 뒤 — 쪽 썸네일은 비우고(PDF 쪽 편집이 섞이지 않게, 4.3), 앞뒤 사진을 배경에서 미리 푼다(§6.4)."""
        try:
            self.page_thumbs.clear_document()
            self.page_thumbs.title.setText(self.page_thumbs._format_title(path.name))
        except Exception:
            pass
        self._photo_preload_neighbors(str(path))

    def _photo_step(self, direction: int):
        """다음·이전 사진(4.12) — 묻는 창 없이, 원천은 책갈피창 차례 하나. 목록 끝이면 상태 표시줄 알림만(처음으로 돌지 않는다)."""
        cur = self.main_view.current_file() if self.main_view else None
        lst = self._photo_list()
        if not cur or not lst:
            return
        norm = [str(Path(p)) for p in lst]
        try:
            i = norm.index(str(Path(cur)))
        except ValueError:
            return
        j = i + (1 if direction > 0 else -1)
        if j < 0 or j >= len(lst):
            self.status.showMessage(tr("마지막 사진입니다.") if direction > 0 else tr("첫 사진입니다."), 2000)
            return
        self._on_bookmark_activated(lst[j], 0)

    def _photo_preload_neighbors(self, cur: str):
        from viewer.workers import run_in_thread
        lst = self._photo_list()
        try:
            i = lst.index(cur)
        except ValueError:
            return
        near = [lst[j] for j in (i + 1, i - 1) if 0 <= j < len(lst)]
        if not near:
            return
        old = getattr(self, "_photo_preloader", None)
        if old is not None:
            old.request_cancel()                     # 앞 일은 멈춘다 — 빨리 넘기면 마지막 것만(4.12)
        w = PhotoPreloadWorker(near)
        self._photo_preloader = w
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))


class PhotoPreloadWorker(QObject):
    """다음·이전 사진을 배경에서 미리 푼다(사진 보기 SOT §6.4) — 응답성 SOT §4.4 감사표의 한 행."""
    finished = pyqtSignal()

    def __init__(self, paths):
        super().__init__()
        self.paths = list(paths)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        from viewer import pacing, photo_doc
        try:
            for p in self.paths:
                if self._cancel:
                    break
                photo_doc.preload(p)
                pacing.pace(self)
        finally:
            self.finished.emit()
