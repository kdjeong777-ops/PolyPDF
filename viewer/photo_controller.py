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
MODE_ICON_PX = 20                # 탭 줄 높이 안 — 탭 글자보다 크게(261104-2 사용자 지시). TV 그림은 가로로 길어 실제 높이는 약 15px
# 사진 모드에서 끄는 명령(사진 보기 SOT 4.13 표) — 사진에 뜻이 없거나 사진용 동작이 아직 없는 것(평탄화·인쇄는 P2 에서 사진용으로 켠다)
PHOTO_OFF_CMDS = ("file.save_as", "file.export", "file.flatten", "file.print",
                  "fav.recent_searches", "fav.searches", "fav.add_search",
                  "view.text", "view.study", "view.search", "view.present",
                  "tools.ocr", "tools.build_study", "tools.bookmarker", "tools.study_and_bookmarks", "tools.autotag",
                  "tools.reindex", "tools.merge", "tools.nup", "tools.encrypt", "tools.sign", "tools.translate")
PHOTO_OFF_ATTRS = ("act_present",)       # 창에 따로 붙은 액션(F5)
PHOTO_LIST_ATTRS = ("_favorites", "_recent_folders", "_recent_files")   # 모드마다 따로(4.7) — 사진 묶음 키는 앞 _ 를 뺀 이름


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
        self.bookmark_tree.filesListed.connect(self._photo_on_listed)
        from viewer import photo_doc
        photo_doc.set_decode_requester(self._photo_request_decode)
        photo_doc.set_rotation_provider(self._photo_rot_for)     # 261104-3: 보기 회전(사이드카 `photo_rot`)
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
        self._photo_swap_lists(on)
        self._photo_refresh_button()
        self._photo_on_mode_changed(on)

    def _photo_on_mode_changed(self, on: bool):
        """모드가 바뀐 뒤 — 원천을 바꾼다(4.2). 메인이 하는 일은 보이는 것 바꾸기뿐, 훑기·디코드는 배경(§6, 응답성 SOT §5)."""
        for bt in (getattr(self, "bookmark_tree", None), getattr(self, "bookmark_tree_right", None)):
            if bt is not None and hasattr(bt, "set_photo_mode"):
                bt.set_photo_mode(on)
        strip = self._photo_strip_widget(create=on)
        if strip is not None:
            self.page_thumbs.set_alt_view(strip, on)     # 쪽 썸네일 자리에 사진 썸네일 줄(4.3)
            if not on:
                strip.stop()
        self._photo_gate_actions()
        if not on:
            self._photo_deco_gate(True)
            self._photo_info_hide()
        hook = getattr(self, "_photo_after_mode", None)
        if hook is not None:
            hook(on)

    def _photo_strip_widget(self, create: bool = True):
        s = getattr(self, "_photo_strip", None)
        if s is None and create:
            from viewer.widgets.photo_strip import PhotoStrip
            s = PhotoStrip(getattr(self.page_thumbs, "_icon_w", 130), self.page_thumbs)
            s.photoActivated.connect(lambda p: self._on_bookmark_activated(p, 0))
            s.menuRequested.connect(self._photo_strip_menu)          # 261104-3(4.20)
            s.rotation_provider = self._photo_rot_for
            self._photo_strip = s
        return s

    # ── 즐겨찾기·최근 — 모드마다 따로 (4.7, R8) ───────────────────
    def _photo_swap_lists(self, on: bool):
        """즐겨찾기·최근 폴더·최근 파일을 모드에 맞는 목록으로 바꿔 끼운다 — 즐겨찾기 탭·항목 관리 창 코드는 그대로.
        사진 것은 `picture` 묶음에(옛 판이 저장해도 지워지지 않는 자리, 4.15), PDF 것은 원래 자리에."""
        pic = self._photo_prefs()
        if on:
            self._photo_pdf_lists = {a: getattr(self, a) for a in PHOTO_LIST_ATTRS}
            for a in PHOTO_LIST_ATTRS:
                setattr(self, a, list(pic.get(a.lstrip("_"), []) or []))
        else:
            saved = getattr(self, "_photo_pdf_lists", None)
            if saved is None:
                return
            for a in PHOTO_LIST_ATTRS:
                pic[a.lstrip("_")] = list(getattr(self, a))
                setattr(self, a, saved[a])
            self._photo_pdf_lists = None
        for fn in ("_refresh_favorites_menu", "_refresh_recent_menu", "_refresh_recent_files_menu"):
            try:
                getattr(self, fn)()
            except Exception:
                pass

    def _photo_saved_list(self, attr: str) -> list:
        """settings.json 에 쓸 **PDF** 목록 — 사진 모드면 지금 목록을 사진 묶음에 담고 따로 든 PDF 목록을 준다."""
        if getattr(self, "_photo_mode", False) and getattr(self, "_photo_pdf_lists", None):
            self._photo_prefs()[attr.lstrip("_")] = list(getattr(self, attr))
            return self._photo_pdf_lists[attr]
        return getattr(self, attr)

    def _photo_open_file(self, path: str):
        """사진 하나를 연다(즐겨찾기·최근) — 그 폴더를 책갈피창에 열고 그 사진을 본문에."""
        p = Path(path)
        if self._root_folder_differs(p.parent):
            self.open_folder(p.parent)
        self._on_bookmark_activated(str(p), 0)

    def _root_folder_differs(self, folder) -> bool:
        cur = getattr(self.bookmark_tree, "_root_dir", None)
        try:
            return cur is None or Path(cur).resolve() != Path(folder).resolve()
        except OSError:
            return True

    def _photo_on_listed(self):
        """책갈피창 목록이 다 찼을 때 — 썸네일 줄이 폴더 전체를 보이는 중이면 새 목록으로(D3)."""
        if not getattr(self, "_photo_mode", False):
            return
        cur = self.main_view.current_file() if self.main_view else None
        if cur and self._is_photo_path(cur):
            strip = self._photo_strip_widget()
            strip.set_paths(self._photo_strip_source(), current=str(cur))

    def _photo_gate_actions(self):
        """사진 모드면 `PHOTO_OFF_CMDS` 를 끈다 — 끈 것만 기억했다가 PDF 모드에서 되살리고, 키·언어 판정
        (`_gate_api_dependent_ui`)을 다시 덧입힌다(그 함수 끝에서 이 함수를 부른다 — 한 길)."""
        acts = [(c, self._cmds.get(c)) for c in PHOTO_OFF_CMDS] + [(n, getattr(self, n, None)) for n in PHOTO_OFF_ATTRS]
        off = self.__dict__.setdefault("_photo_disabled", set())
        if self._photo_mode:
            for k, a in acts:
                if a is not None and a.isEnabled():
                    a.setEnabled(False)
                    off.add(k)
            return
        if not off:
            return
        for k, a in acts:
            if a is not None and k in off:
                a.setEnabled(True)
        off.clear()
        self._gate_api_dependent_ui(self._prefs)

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
        """넘김 원천 하나(4.12) — 사진 썸네일 줄의 차례(없으면 책갈피창 차례)."""
        s = self._photo_strip_widget(create=False)
        if s is not None and s.paths():
            return s.paths()
        return self._photo_tree_list()

    def _photo_tree_list(self) -> list:
        """책갈피창에 보이는 차례 그대로의 사진 경로."""
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
        strip = self._photo_strip_widget()
        self.page_thumbs.set_alt_view(strip, True)
        strip.set_paths(self._photo_strip_source(), current=str(path))
        lst = [str(Path(p)) for p in self._photo_list()]
        if str(Path(path)) in lst:                    # 쪽 칸 = 넘김 원천 안의 순번(4.12) — 사진은 늘 1쪽이라 '1 / 1' 은 뜻이 없다
            self.main_view.set_photo_position(lst.index(str(Path(path))), len(lst))
        self._photo_preload_neighbors(str(path))
        self._photo_deco_gate(not self._photo_is_broken())
        self._photo_info_request(path)
        try:
            self._touch_recent_files([path])          # 사진 모드면 사진의 최근 파일(4.7)
        except Exception:
            pass

    def _photo_strip_source(self) -> list:
        """썸네일 줄에 넣을 사진(D3) — 책갈피창에서 여럿 골랐으면 고른 것(트리 차례), 하나면 폴더 전체."""
        bt = self.bookmark_tree
        sel = []
        for it in bt._iter_file_nodes():
            if it.isSelected():
                p = it.data(0, bt.DATA_FILE)
                if p and self._is_photo_path(p):
                    sel.append(str(p))
        return sel if len(sel) > 1 else self._photo_tree_list()

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

    # ── 보기 회전 (4.11 '보기 회전'·4.16, 261104-3) ─────────────────
    def _photo_rot_for(self, path) -> int:
        """사진의 보기 회전(시계 방향 도) — 폴더 사이드카의 `photo_rot`(PDF 쪽 회전 대기값과 다른 자리)."""
        if not self._is_photo_path(path):
            return 0
        st = self._ensure_page_meta_store()
        return st.photo_rotation(path) if st else 0

    def _photo_deco_frame(self, path):
        """돌린 사진이면 (회전, 회전 0 판 폭, 높이) — 꾸밈 좌표를 읽을 때 돌리고 쓸 때 되돌린다(4.19). 아니면 None."""
        if not path or not self._is_photo_path(path):
            return None
        rot = self._photo_rot_for(path)
        if not rot:
            return None
        from viewer.photo_io import oriented_size
        w0, h0 = oriented_size(path)
        return (rot, float(w0), float(h0)) if w0 and h0 else None

    def _photo_rotate(self, delta: int = 90, absolute: int | None = None, path=None):
        """사진을 돌린다 — 보기만(원본 사진은 그대로, 방향 저장 D17 은 따로). 폴더를 연 사진만 기억한다(사이드카가 폴더에 있다).
        `path` 를 주면 그 사진(썸네일 줄 메뉴 — 지금 본문이 아니어도), 없으면 지금 사진."""
        now = self.main_view.current_file() if self.main_view else None
        cur = str(path) if path else now
        is_now = bool(now) and cur is not None and str(Path(cur)) == str(Path(now))
        if not cur or not self._is_photo_path(cur) or (is_now and self._photo_is_broken()):
            return
        if not is_now:
            from viewer.photo_io import oriented_size
            if not oriented_size(cur)[0]:
                return                                   # 열 수 없는 파일은 돌리지 않는다(4.18)
            st = self._ensure_page_meta_store()
            old = st.photo_rotation(cur) if st else 0
            new = (int(absolute) if absolute is not None else old + int(delta)) % 360
            if st and new != old and st.set_photo_rotation(cur, new) is not False:
                st.save_photo_rotation()
                strip = self._photo_strip_widget(create=False)
                if strip is not None:
                    strip.refresh(cur)
            return
        st = self._ensure_page_meta_store()
        old = st.photo_rotation(cur) if st else 0
        new = (int(absolute) if absolute is not None else old + int(delta)) % 360
        if new == old:
            return
        if not st or st.set_photo_rotation(cur, new) is False and new != 0:
            self.status.showMessage(tr("폴더를 열어 고른 사진만 돌릴 수 있습니다."), 4000)
            return
        st.save_photo_rotation()                 # 보기 상태 — 편집 저장 대기와 섞지 않고 이 묶음만 바로(4.16)
        strip = self._photo_strip_widget(create=False)
        if strip is not None:
            strip.refresh(cur)                   # 썸네일도 돌려 보인다(4.20)
        mv = self.main_view
        fit = mv._fit_mode
        if mv.load_document(cur, 0):
            mv._fit_mode = fit
            self._photo_after_open(Path(cur))
            mv._render_current()

    def _photo_is_broken(self) -> bool:
        return bool(getattr(getattr(self.main_view, "_doc", None), "is_broken", False))

    # ── 사진 정보 — 상태 막대 가운데·세부 정보 창 (4.18, 261104-3 사용자 지시) ─────────
    def _photo_info_button(self, create: bool = True):
        b = getattr(self, "_photo_info_btn", None)
        if b is None and create:
            from PyQt6.QtCore import QEvent, QObject as _QO
            b = QToolButton(self.status)
            b.setObjectName("photoInfo")
            b.setAutoRaise(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip(tr("누르면 사진의 세부 정보를 봅니다."))
            b.clicked.connect(self._photo_info_dialog)
            b.hide()
            owner = self

            class _Center(_QO):                          # 상태 막대 가운데에 둔다 — 상태 글(왼쪽)·단추(오른쪽) 자리와 따로
                def eventFilter(self, obj, ev):
                    if ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                        owner._photo_info_place()
                    return False
            self._photo_info_filter = _Center(self)
            self.status.installEventFilter(self._photo_info_filter)
            self._photo_info_btn = b
        return b

    def _photo_info_place(self):
        b = getattr(self, "_photo_info_btn", None)
        if b is None:
            return
        b.adjustSize()
        sb = self.status
        b.move(max(0, (sb.width() - b.width()) // 2), max(0, (sb.height() - b.height()) // 2))
        b.raise_()

    def _photo_info_hide(self):
        b = self._photo_info_button(create=False)
        if b is not None:
            b.hide()
        self._photo_info = None

    def _photo_info_request(self, path):
        """지금 사진의 정보를 배경에서 읽는다(머리만) — 끝나면 상태 막대 가운데에 한 줄."""
        from viewer.workers import run_in_thread
        self._photo_info_gen = getattr(self, "_photo_info_gen", 0) + 1
        self._photo_info = None
        b = self._photo_info_button()
        if self._photo_is_broken():
            from viewer.photo_doc import broken_reason_text
            b.setText(tr("열 수 없는 파일") + " · " + broken_reason_text(self.main_view._doc.reason))
            b.show(); self._photo_info_place()
            return
        b.setText(Path(str(path)).name)
        b.show(); self._photo_info_place()
        w = PhotoInfoWorker(self._photo_info_gen, str(path))
        w.done.connect(self._photo_info_done)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_info_done(self, gen: int, path: str, info: dict):
        if gen != getattr(self, "_photo_info_gen", 0) or not info:
            return
        self._photo_info = dict(info, path=path)
        b = self._photo_info_button()
        b.setText(photo_info_line(info))
        self._photo_info_place()

    def _photo_info_dialog(self):
        """세부 정보 창 — 파일·크기·촬영·카메라·노출·색 프로필·위치(있으면)."""
        info = getattr(self, "_photo_info", None)
        if not info:
            return
        from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QTableWidget,
                                     QTableWidgetItem, QVBoxLayout)
        rows = photo_info_rows(info)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("사진 정보") + " — " + Path(info["path"]).name)
        lay = QVBoxLayout(dlg)
        t = QTableWidget(len(rows), 2, dlg)
        t.setHorizontalHeaderLabels([tr("항목"), tr("값")])
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i, (k, v) in enumerate(rows):
            t.setItem(i, 0, QTableWidgetItem(k))
            t.setItem(i, 1, QTableWidgetItem(v))
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dlg)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.resize(560, 420)
        self._photo_info_dlg = dlg
        dlg.exec()

    def _photo_deco_gate(self, ok: bool):
        """꾸미기 도구 줄을 켜고 끈다 — 돌린 사진에서는 끈다(4.16, 그려도 남지 않으면 고장으로 보인다)."""
        bar = getattr(self.main_view, "_draw_bar", None)
        if bar is not None:
            bar.setEnabled(bool(ok))
            bar.setToolTip("" if ok else tr("열 수 없는 파일에는 꾸밀 수 없습니다."))

    def _photo_context_menu(self, global_pos):
        """사진 본문 우클릭 — 돌리기·맞춤(4.16). PDF 의 쪽 메뉴(쪽 번호·숨김·책갈피 …)는 사진에 뜻이 없다."""
        from PyQt6.QtWidgets import QMenu
        mv = self.main_view
        menu = QMenu(self)
        a_l = menu.addAction(self._kt(tr("왼쪽으로 90° 돌리기"), "rotate_left"))
        a_r = menu.addAction(self._kt(tr("오른쪽으로 90° 돌리기"), "rotate_right"))
        a_180 = menu.addAction(tr("180° 돌리기"))
        a_0 = menu.addAction(tr("원래 방향"))
        a_0.setEnabled(self._photo_rot_for(mv.current_file()) != 0)
        if self._photo_is_broken():                      # 4.18 — 열 수 없는 파일은 돌리지 않는다
            for a in (a_l, a_r, a_180, a_0):
                a.setEnabled(False)
        a_save = menu.addAction(tr("방향 저장 (원본 JPEG)"))       # 4.17 — 돌린 JPEG 일 때만
        a_save.setEnabled(self._photo_rot_for(mv.current_file()) != 0
                          and photo_io_is_jpeg(mv.current_file()) and not self.__dict__.get("_photo_orient_busy"))
        menu.addSeparator()
        a_fp = menu.addAction(tr("쪽 맞춤"))
        a_fw = menu.addAction(tr("폭 맞춤"))
        a_100 = menu.addAction(tr("원래 크기 (100%)"))
        menu.addSeparator()
        cur = mv.current_file()
        broken = self._photo_is_broken()
        extra = {}
        for key, label in (("copy_image", tr("사진 복사")), ("copy_path", tr("경로 복사")),
                           ("reveal", tr("파일 탐색기 열기")), ("info", tr("사진 정보...")),
                           ("to_pdf", tr("PDF 로 만들기..."))):
            a = menu.addAction(label)
            a.setEnabled(not broken or key in ("copy_path", "reveal"))
            extra[a] = key
        chosen = menu.exec(global_pos)
        if chosen in extra:
            self._photo_action(extra[chosen], [str(cur)])
            return
        if chosen is None:
            return
        if chosen is a_l:
            self._photo_rotate(-90)
        elif chosen is a_r:
            self._photo_rotate(+90)
        elif chosen is a_180:
            self._photo_rotate(180)
        elif chosen is a_0:
            self._photo_rotate(absolute=0)
        elif chosen is a_save:
            self._photo_save_orientation()
        elif chosen in (a_fp, a_fw):
            mv._show_fit(mv.FIT_PAGE if chosen is a_fp else mv.FIT_WIDTH)
            mv._fit_mode = mv.FIT_PAGE if chosen is a_fp else mv.FIT_WIDTH
            mv._render_current()
        elif chosen is a_100:
            self._photo_zoom_actual()

    def _photo_save_orientation(self):
        """보기 회전을 원본 JPEG 의 방향 태그에(D17, 4.17) — 배경 한 길, 끝나면 `_photo_orient_saved`."""
        cur = self.main_view.current_file() if self.main_view else None
        rot = self._photo_rot_for(cur) if cur else 0
        if not cur or not rot or self.__dict__.get("_photo_orient_busy"):
            return
        if not photo_io_is_jpeg(cur):
            self.status.showMessage(tr("방향 저장은 JPEG 사진만 됩니다 — 이 사진은 보기에서만 돌려 둡니다."), 5000)
            return
        if self._in_edit() and getattr(self, "_edit_dirty", False):
            # 꾸밈 좌표를 함께 옮겨 바로 써야 한다(4.19) — 저장 대기 중인 편집을 같이 내보내지 않게 먼저 저장하게 한다
            self.status.showMessage(tr("저장하지 않은 편집이 있습니다 — 먼저 [저장] 한 뒤 방향을 저장하세요."), 6000)
            return
        from viewer.workers import run_in_thread
        self._photo_orient_busy = True
        w = PhotoOrientSaveWorker(cur, rot)
        w.done.connect(self._photo_orient_saved)
        self.status.showMessage(tr("방향 저장 중…"), 2000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_orient_saved(self, path: str, ok: bool, why: str):
        """방향 저장이 끝났다(메인) — 성공이면 보기 회전을 지우고 다시 그린다. 실패면 원본 그대로·보기 회전 그대로."""
        self._photo_orient_busy = False
        if not ok:
            msg = {"locked": tr("다른 프로그램이 사진을 쓰고 있어 방향을 저장하지 못했습니다 — 원본은 그대로입니다."),
                   "jpeg": tr("방향 저장은 JPEG 사진만 됩니다 — 이 사진은 보기에서만 돌려 둡니다.")}.get(
                why, tr("방향을 저장하지 못했습니다 — 원본은 그대로입니다."))
            self.status.showMessage(msg, 8000)
            return
        st = self._ensure_page_meta_store()
        if st is not None:
            rot = st.photo_rotation(path)
            self._photo_move_decorations(st, path, rot)          # 회전 0 판이 바뀌었다 — 꾸밈도 같은 만큼(4.19)
            st.set_photo_rotation(path, 0)
            st.save_photo_rotation()
        strip = self._photo_strip_widget(create=False)
        if strip is not None:
            strip.refresh(path)                      # 썸네일 다시(캐시 키에 수정 시각 — 새 그림)
        cur = self.main_view.current_file() if self.main_view else None
        if cur and str(Path(cur)) == str(Path(path)):
            mv = self.main_view
            fit = mv._fit_mode
            if mv.load_document(cur, 0):
                mv._fit_mode = fit
                self._photo_after_open(Path(cur))
                mv._render_current()
        self.status.showMessage(tr("방향을 원본 사진에 저장했습니다: {name}").format(name=Path(path).name), 5000)

    def _photo_move_decorations(self, st, path, rot: int):
        """방향을 파일에 저장한 뒤 — 사이드카의 꾸밈(쪽 0)을 새 회전 0 판으로 옮겨 바로 쓴다.
        `oriented_size` 는 이미 새 방향이라 돌리기 전 크기는 맞바꿔 구한다."""
        if not rot:
            return
        from viewer import photo_deco
        from viewer.photo_io import oriented_size
        w1, h1 = oriented_size(path)
        w0, h0 = (h1, w1) if rot in (90, 270) else (w1, h1)
        moved = False
        for p0 in sorted(set(st.pages_with_drawings(path)) | set(st.pages_with_images(path))):
            d = st.get_drawings(path, p0)
            if d:
                st.set_drawings(path, p0, photo_deco.rotate_strokes(d, rot, w0, h0)); moved = True
            im = st.get_images(path, p0)
            if im:
                st.set_images(path, p0, photo_deco.rotate_images(im, rot, w0, h0)); moved = True
        if moved:
            st.save()

    def _photo_action(self, kind: str, paths: list):
        """사진 모드 메뉴의 일(4.20) — 책갈피창·썸네일 줄·본문이 같은 함수를 부른다."""
        paths = [str(p) for p in (paths or []) if p]
        if not paths:
            return
        from PyQt6.QtWidgets import QApplication
        if kind == "copy_path":
            QApplication.clipboard().setText("\n".join(paths))
            self.status.showMessage(tr("경로를 복사했습니다."), 2500)
        elif kind == "copy_image":
            from viewer.workers import run_in_thread
            w = PhotoCopyWorker(paths[0], self._photo_rot_for(paths[0]))
            w.done.connect(self._photo_copied)
            self.status.showMessage(tr("사진 복사 중…"), 2000)
            run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))
        elif kind == "to_pdf":
            self.action_image_to_pdf(initial_paths=paths)      # 이미지 → PDF 창(이미지 PDF SOT) — 고른 사진을 미리 넣는다
        elif kind == "reveal":
            try:
                self.bookmark_tree._reveal_in_explorer(paths[0])
            except Exception:
                pass
        elif kind == "info":
            self._photo_info_dialog()
        elif kind == "open":
            self._on_bookmark_activated(paths[0], 0)
        elif kind in ("rot_l", "rot_r"):
            self._photo_rotate(-90 if kind == "rot_l" else +90, path=paths[0])

    def _photo_copied(self, path: str, img):
        from PyQt6.QtWidgets import QApplication
        if img is None or img.isNull():
            self.status.showMessage(tr("사진을 복사하지 못했습니다."), 4000)
            return
        QApplication.clipboard().setImage(img)
        self.status.showMessage(tr("사진을 복사했습니다: {name}").format(name=Path(path).name), 3000)

    def _photo_strip_menu(self, path: str, global_pos):
        """썸네일 줄 우클릭(4.20) — 누른 사진에. 줄 전체로 PDF 만들기도."""
        from PyQt6.QtWidgets import QMenu
        from viewer.photo_io import oriented_size
        ok = bool(oriented_size(path)[0])
        strip = self._photo_strip_widget(create=False)
        allp = strip.paths() if strip is not None else [path]
        menu = QMenu(self)
        items = [("open", tr("열기")), (None, None),
                 ("rot_l", tr("왼쪽으로 90° 돌리기")), ("rot_r", tr("오른쪽으로 90° 돌리기")), (None, None),
                 ("copy_image", tr("사진 복사")), ("copy_path", tr("경로 복사")), ("reveal", tr("파일 탐색기 열기")), (None, None),
                 ("to_pdf", tr("PDF 로 만들기..."))]
        acts = {}
        for key, label in items:
            if key is None:
                menu.addSeparator()
                continue
            a = menu.addAction(label)
            a.setEnabled(ok or key in ("open", "copy_path", "reveal"))
            acts[a] = key
        a_all = None
        if len(allp) > 1:
            a_all = menu.addAction(tr('줄의 사진 {n}장으로 PDF 만들기...').format(n=len(allp)))
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is a_all:
            self._photo_action("to_pdf", allp)
        elif chosen in acts:
            self._photo_action(acts[chosen], [path])

    def _photo_zoom_actual(self):
        """원래 크기 — 사진 픽셀 하나 = 화면 논리 픽셀 하나(D14 좌표 = pt)."""
        mv = self.main_view
        mv._show_fit(mv.FIT_NONE)
        mv._fit_mode = mv.FIT_NONE
        mv._zoom = 1.0
        mv._render_current()

    def _rotate_current(self, delta: int):
        """돌리기 키(Ctrl+[ · Ctrl+]) — 사진이면 사진 보기 회전, PDF 면 지금 쪽 회전(쪽 메뉴의 회전과 같은 길)."""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur:
            return
        if self._is_photo_path(cur) and isinstance(getattr(self.main_view, "_doc", None), _photo_doc_cls()):
            self._photo_rotate(delta)
        elif str(cur).lower().endswith(".pdf"):
            self._rotate_pages([self.main_view.current_page()], delta)

    def _photo_goto(self, idx0: int):
        """쪽 칸에 적은 순번의 사진으로(4.12)."""
        lst = self._photo_list()
        if 0 <= idx0 < len(lst):
            self._on_bookmark_activated(lst[idx0], 0)

    def _photo_request_decode(self, path, box: int):
        """사진 문서가 메인에서 풀리지 않은 사진을 그리려 할 때 — 배경에서 풀고, 끝나면 그 사진이 아직 본문이면 다시 그린다."""
        from viewer.workers import run_in_thread
        key = (str(path), int(box))
        pend = self.__dict__.setdefault("_photo_decoding", set())
        if key in pend:
            return
        pend.add(key)
        w = PhotoPreloadWorker([str(path)], box=int(box))
        # 다 풀린 것만 알린다(못 풀면 알리지 않는다 — 다시 그리기 ↔ 다시 요청이 돌지 않게). 받는 쪽은 창의 메서드 = 메인 스레드
        w.decodedOne.connect(self._photo_on_decoded)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_on_decoded(self, path: str, box: int):
        """배경 해독이 끝났다(메인 스레드) — 그 사진이 아직 본문이면 다시 그린다."""
        self.__dict__.setdefault("_photo_decoding", set()).discard((str(path), int(box)))
        try:
            cur = self.main_view.current_file() if self.main_view else None
            if cur and str(cur) == str(path):
                self.main_view._render_current()
        except Exception:
            pass

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


ORIENT_TMP_SUFFIX = ".polypix-tmp"       # 방향 저장 임시 파일 — 그림 확장자가 아니라 목록에 안 뜬다(4.17)
ORIENT_REPLACE_TRIES = 4                 # 바꿔치기 재시도(마스터 §4.7.5 `SAVE_REPLACE_TRIES` 와 같은 횟수)
ORIENT_REPLACE_WAIT_S = 0.15


class PhotoOrientSaveWorker(QObject):
    """사진 방향 저장 한 길(사진 보기 SOT 4.17, D17) — 배경에서: 읽기 → 임시 파일 → 확인 → 바꿔치기. 실패하면 원본 그대로.
    응답성 SOT §4.4 감사표의 한 행(파일 작업은 메인에서 하지 않는다 — 마스터 §4.7.5)."""
    done = pyqtSignal(str, bool, str)        # 경로, 성공, 실패 까닭
    finished = pyqtSignal()

    def __init__(self, path: str, rot_cw: int):
        super().__init__()
        self.path, self.rot = str(path), int(rot_cw) % 360

    def request_cancel(self):
        pass                                 # 짧은 일 — 중간에 멈추지 않는다(반쯤 쓴 원본을 남기지 않게)

    def run(self):
        import os
        import time
        from viewer import photo_io
        tmp = None
        try:
            ok, why = False, ""
            src = Path(self.path)
            data = src.read_bytes()
            from PIL import Image
            with Image.open(src) as im:
                old = int(im.getexif().get(photo_io.ORIENT_TAG, 1) or 1)
                size = im.size
            new_o = photo_io.compose_orientation(old, self.rot)
            new = photo_io.jpeg_set_orientation(data, new_o)
            if new is None:
                why = "jpeg"
            else:
                tmp = src.with_name("~" + src.name + ORIENT_TMP_SUFFIX)
                tmp.write_bytes(new)
                with Image.open(tmp) as im:                 # 확인 — 태그·크기·그림 자료
                    good = (int(im.getexif().get(photo_io.ORIENT_TAG, 1) or 1) == new_o and im.size == size
                            and photo_io.jpeg_scan_data(tmp.read_bytes()) == photo_io.jpeg_scan_data(data))
                if not good:
                    why = "verify"
                else:
                    for k in range(ORIENT_REPLACE_TRIES):
                        try:
                            os.replace(str(tmp), str(src))
                            ok, tmp = True, None
                            break
                        except OSError:
                            time.sleep(ORIENT_REPLACE_WAIT_S)
                    if not ok:
                        why = "locked"
            self.done.emit(self.path, ok, why)
        except Exception as e:                               # noqa: BLE001 — 원본은 손대지 않았다
            self.done.emit(self.path, False, type(e).__name__)
        finally:
            if tmp is not None:
                try:
                    Path(tmp).unlink()
                except OSError:
                    pass
            self.finished.emit()


COPY_MAX_SIDE = 8192            # 사진 복사 — 긴 변 상한(클립보드에 24 MP 그대로는 무겁다, 4.20)


class PhotoCopyWorker(QObject):
    """사진 복사 — 배경에서 풀고(보기 회전까지) 메인은 클립보드에 넣기만(응답성 SOT §4.4 감사표의 한 행)."""
    done = pyqtSignal(str, object)
    finished = pyqtSignal()

    def __init__(self, path: str, rot: int = 0):
        super().__init__()
        self.path, self.rot = path, int(rot or 0) % 360

    def request_cancel(self):
        pass

    def run(self):
        img = None
        try:
            from viewer.photo_io import read_scaled
            img, _w, _h = read_scaled(self.path, COPY_MAX_SIDE, auto_transform=True)
            if self.rot and img is not None and not img.isNull():
                from PyQt6.QtGui import QTransform
                img = img.transformed(QTransform().rotate(self.rot))
        except Exception:
            img = None
        finally:
            self.done.emit(self.path, img)
            self.finished.emit()


def _fmt_bytes(n: int) -> str:
    return "%.1f MB" % (n / 1048576.0) if n >= 1048576 else "%d KB" % max(1, round(n / 1024.0))


def _fmt_taken(s: str) -> str:
    """EXIF 날짜 '2026:10:30 14:22:05' → '2026-10-30 14:22'."""
    s = (s or "").strip()
    if len(s) >= 16 and s[4] == ":" and s[7] == ":":
        return s[:4] + "-" + s[5:7] + "-" + s[8:10] + " " + s[11:16]
    return s


def photo_info_line(info: dict) -> str:
    """상태 막대 가운데 한 줄 — 촬영일 · 크기 · 파일 크기 · 카메라(있는 것만)."""
    parts = []
    if info.get("taken"):
        parts.append(_fmt_taken(info["taken"]))
    if info.get("width"):
        parts.append("%d × %d" % (info["width"], info["height"]))
    if info.get("bytes"):
        parts.append(_fmt_bytes(info["bytes"]))
    if info.get("camera"):
        parts.append(info["camera"])
    return "  ·  ".join(parts) or tr("사진 정보")


def photo_info_rows(info: dict) -> list:
    """세부 정보 창의 (항목, 값) — 화면 글은 tr(), 값은 그대로."""
    ex = info.get("exif") or {}
    rows = [(tr("파일"), str(info.get("path", ""))),
            (tr("형식"), info.get("format", "")),
            (tr("크기(픽셀)"), "%d × %d" % (info.get("width", 0), info.get("height", 0)) if info.get("width") else ""),
            (tr("파일 크기"), _fmt_bytes(info["bytes"]) if info.get("bytes") else ""),
            (tr("촬영일"), _fmt_taken(info.get("taken", ""))),
            (tr("카메라"), info.get("camera", "")),
            (tr("렌즈"), ex.get("LensModel", "")),
            (tr("노출 시간"), ex.get("ExposureTime", "")),
            (tr("조리개"), ex.get("FNumber", "")),
            (tr("ISO"), ex.get("ISOSpeedRatings", "")),
            (tr("초점 거리"), ex.get("FocalLength", "")),
            (tr("방향(EXIF)"), ex.get("Orientation", "")),
            (tr("색 프로필"), info.get("icc", "")),
            (tr("위치(GPS)"), "%.6f, %.6f" % info["gps"] if info.get("gps") else ""),
            (tr("소프트웨어"), ex.get("Software", ""))]
    return [(k, v) for k, v in rows if v]


class PhotoInfoWorker(QObject):
    """지금 사진의 정보(머리만)를 배경에서 읽는다 — 응답성 SOT §4.4 감사표의 한 행."""
    done = pyqtSignal(int, str, dict)
    finished = pyqtSignal()

    def __init__(self, gen: int, path: str):
        super().__init__()
        self.gen, self.path = gen, path

    def request_cancel(self):
        pass

    def run(self):
        try:
            from viewer.photo_io import photo_info
            try:
                info = photo_info(self.path)
            except Exception:
                info = {}
            self.done.emit(self.gen, self.path, info)
        finally:
            self.finished.emit()


def photo_io_is_jpeg(path) -> bool:
    if not path:
        return False
    from viewer.photo_io import is_jpeg_file
    return is_jpeg_file(path)


def _photo_doc_cls():
    from viewer.photo_doc import PhotoDocument
    return PhotoDocument


class PhotoPreloadWorker(QObject):
    """다음·이전 사진을 배경에서 미리 푼다(사진 보기 SOT §6.4) — 응답성 SOT §4.4 감사표의 한 행."""
    finished = pyqtSignal()
    decodedOne = pyqtSignal(str, int)        # 다 푼 사진(경로, 긴 변) — box 를 준 해독 요청만

    def __init__(self, paths, box: int | None = None):
        super().__init__()
        self.paths = list(paths)
        self.box = box
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        from viewer import pacing, photo_doc
        try:
            for p in self.paths:
                if self._cancel:
                    break
                if self.box is None:
                    photo_doc.preload(p)
                else:
                    photo_doc.preload(p, self.box)
                    if photo_doc.decoded_ready(p, self.box) is not None:   # 못 풀었으면 알리지 않는다 — 다시 그리기 ↔ 다시 요청이 돌지 않게
                        self.decodedOne.emit(p, int(self.box))
                pacing.pace(self)
        finally:
            self.finished.emit()
