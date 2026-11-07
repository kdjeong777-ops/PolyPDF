# -*- coding: utf-8 -*-
"""사진 모드(PolyPix) — 앱 쪽 (사진 보기 SOT, 261104-2).

- **보기 종류**(사진 보기 SOT 4.10, D12): 환경설정의 'PDF 전용'(기본 — 사진 모드 없음)·'혼용'(PDF 모드 ↔ 사진 모드 토글).
  값은 `preferences` 안의 사진 묶음 `picture` 하나에 둔다(4.7·4.15 — 최상위 새 키는 옛 판이 저장하며 지운다).
- **모드 토글**(4.1, D1·D7): 리본 탭 줄 왼쪽 빈 칸 맨 앞의 브라운관 TV 단추. 창마다 모드 하나, 시작은 마지막 모드.
  파일을 지정해 뜬 창(새 창으로 PDF 열기·가상 프린터·탐색기 열기)은 늘 PDF 모드(D1).
- 모드가 바꾸는 것은 '원천' 뿐(4.2·위험 표 첫 줄) — 책갈피창이 보이는 확장자, 썸네일 원천, 즐겨찾기 목록. 화면 코드는 그대로.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QMessageBox, QToolButton

from pathlib import Path

from viewer.i18n import tr

VIEW_PDF = "pdf"                 # 'PDF 전용' — 사진 모드 없음(기본)
VIEW_MIXED = "mixed"             # '혼용' — PDF 모드 ↔ 사진 모드
MODE_ICON_PX = 20                # 탭 줄 높이 안 — 탭 글자보다 크게(261104-2 사용자 지시). TV 그림은 가로로 길어 실제 높이는 약 15px
# 사진 모드에서 끄는 명령(사진 보기 SOT 4.13 표) — 사진에 뜻이 없거나 사진용 동작이 아직 없는 것(평탄화·인쇄는 P2 에서 사진용으로 켠다)
PHOTO_OFF_CMDS = ("file.save_as",                                    # 인쇄·평탄화는 사진용으로 켠다(261104-3, 4.21) · 변환은 사진 → Word·HWPX·텍스트(261104-10 P4-b, 4.35)
                  "fav.recent_searches", "fav.searches", "fav.add_search",
                  "view.study", "view.search",       # 발표 = 사진 슬라이드쇼(261104-7, 4.12) · 텍스트 창·도구 OCR = 사진 한 장 OCR(261104-10, 4.34)
                  # online_enrich: 열린 PDF 단어장 작업(261107-13)
                  "tools.build_study", "tools.online_enrich", "tools.bookmarker", "tools.study_and_bookmarks", "tools.autotag",
                  "tools.reindex", "tools.merge", "tools.nup", "tools.encrypt", "tools.sign", "tools.translate")
PHOTO_OFF_ATTRS = ()                     # 창에 따로 붙은 액션 — F5 발표는 사진 슬라이드쇼로 켠다(261104-7)
# 사진 모드에서 아예 숨기는 명령(4.13) — 끄기(PHOTO_OFF_CMDS)에 더해 리본·모음·메뉴에서 뺀다. 261106-1 전자서명에 이어
#   261106-4(사용자 결정 '모두 숨김'): 끄는 명령은 **모두** 숨긴다 — 회색 단추를 남기지 않는다(목록은 PHOTO_OFF_CMDS 하나)
PHOTO_HIDE_CMDS = PHOTO_OFF_CMDS
PHOTO_LIST_ATTRS = ("_favorites", "_recent_folders", "_recent_files")   # 모드마다 따로(4.7) — 사진 묶음 키는 앞 _ 를 뺀 이름
FIT_ACTUAL = "actual"                    # 창 아래 맞춤 콤보의 '원래 크기' — 사진 모드에만(4.16, 261105-16 사용자 결정)


START_PDF = False                        # main.py 가 창을 만들기 **전에** 켠다 — 파일 인자·인쇄로 뜬 창(D1, 261104-20)


class PhotoMixin:
    def _photo_init(self):
        self._photo_mode = False
        self._photo_forced_pdf = bool(START_PDF)  # 파일 인자로 뜬 창 — 늘 PDF 모드(D1). 창 만들 때 알아야 사진 모드 복원을 건너뛴다
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
        self.bookmark_tree.photo_menu_fill = self._photo_menu_fill   # 4.20(261107-2) — 사진 세 메뉴 한 함수(아래 창은 app 이 잇는다)
        from viewer import photo_doc
        photo_doc.set_decode_requester(self._photo_request_decode)
        photo_doc.set_rotation_provider(self._photo_rot_for)     # 261104-3: 보기 회전(사이드카 `photo_rot`)
        photo_doc.set_crop_provider(self._photo_crop_for)        # 261105-4: 보기 크롭(사이드카 `photo_crop`, 4.40)
        self._photo_refresh_button()
        # 모드마다 마지막 자리(6.1, 261105-1 사용자 지시) — PDF 것은 원래 자리(last_open·last_main·last_folder), 사진 것은 picture 묶음
        data = getattr(self, "_session_data", None) or {}
        pic = self._photo_prefs()
        self._photo_mode_last = {
            "pdf": {k: data.get(k) for k in ("last_open", "last_main", "last_folder")},
            "photo": {"last_open": pic.get("last_open"), "last_main": pic.get("last_main")},
        }
        self._photo_apply_view_kind(restore=True)
        self._photo_started = True

    # ── 모드마다 마지막 자리 (6.1, 261105-1) ───────────────
    def _photo_capture_last(self):
        """지금 모드의 마지막 자리를 담아 둔다 — 모드를 바꾸기 직전과 설정 저장 때."""
        rec = self.__dict__.get("_photo_mode_last")
        if rec is None or not self.__dict__.get("_photo_started"):
            return                                       # 창을 만드는 중의 모드 복원 — 아직 연 것이 없다(지난 자리를 지우지 않는다)
        cur = self.__dict__.get("_current_main")
        rec["photo" if self._photo_mode else "pdf"] = {
            "last_open": self._current_open_target(),
            "last_main": cur.to_dict() if cur is not None else None,
            "last_folder": str(self._folder) if getattr(self, "_folder", None) else "",
        }

    def _photo_saved_last(self, key: str, current):
        """settings.json 에 쓸 **PDF 모드** 마지막 자리(`key`) — 사진 모드로 닫으면 사진 것은 picture 묶음에 담고
        PDF 모드에서 마지막으로 보던 것을 준다(다음에 PDF 모드로 켜면 그 자리, 6.1)."""
        rec = self.__dict__.get("_photo_mode_last")
        if rec is None:
            return current
        self._photo_capture_last()
        ph = rec.get("photo") or {}
        pic = self._photo_prefs()
        pic["last_open"] = ph.get("last_open") or {}
        pic["last_main"] = ph.get("last_main")
        if not self._photo_mode:
            return current
        v = (rec.get("pdf") or {}).get(key)
        return v if v is not None else ({} if key == "last_open" else ("" if key == "last_folder" else None))

    def _photo_restore_start(self) -> bool:
        """사진 모드로 켠 창의 시작(6.1, 261105-1 사용자 지시) — 사진 모드에서 마지막으로 보던 폴더와 사진을 연다.
        PDF 시작 설정(startup_mode 'path')은 PDF 모드 몫이고, '없음' 이면 아무것도 열지 않는다. 사진 모드가 아니면 False."""
        if not self._photo_mode:
            return False
        if str(self._prefs.get("startup_mode", "last")) == "none":
            return True
        ph = (self.__dict__.get("_photo_mode_last") or {}).get("photo") or {}
        lo = ph.get("last_open") or {}
        target = str(lo.get("path") or "")
        main = ph.get("last_main") if isinstance(ph.get("last_main"), dict) else None
        if not target:                                    # 옛 설정 — 사진 최근 폴더 맨 앞
            target = next((str(f) for f in (self._recent_folders or []) if os.path.isdir(str(f))), "")
        p = Path(target) if target else None
        if p is None or not p.exists():
            return True                                   # 사라졌으면 빈 화면 — 다른 것을 열어 주지 않는다
        folder = p if p.is_dir() else p.parent
        self.open_folder(folder)
        fp = str((main or {}).get("file_path") or "")
        if not fp and p.is_file():
            fp = str(p)
        if not fp:                                        # 마지막 본 사진 — 그 폴더 안의 사진 최근 파일 맨 앞
            fp = next((str(t) for t in (self._recent_files or [])
                       if self._is_photo_path(t) and Path(str(t)).parent == folder and os.path.isfile(str(t))), "")
        if fp and os.path.isfile(fp) and folder in Path(fp).parents:
            from viewer.history import HistoryItem
            self._load_main(HistoryItem(fp, 0, "", "bookmark"))
        return True

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

    def _photo_sync_backup_dir(self) -> None:
        from viewer import photo_backup
        try:
            photo_backup.set_custom_dir(str(self._photo_prefs().get("warp_backup_dir") or ""))
        except Exception:
            pass

    def _photo_apply_view_kind(self, restore: bool = False):
        """보기 종류에 맞춘다 — PDF 전용이면 단추를 숨기고 사진 모드였으면 곧바로 PDF 모드로(4.10)."""
        self._photo_sync_backup_dir()                    # 환경설정의 백업 폴더(261106-15) — 목록 거르기·대체 저장이 쓴다
        on = self._photo_enabled()
        self._photo_btn.setVisible(on)
        if not on:
            if self._photo_mode:
                self._set_photo_mode(False)
            return
        if restore and not self._photo_forced_pdf and self._photo_prefs().get("mode") == "photo":
            self._set_photo_mode(True, load_last=False)

    def _photo_force_pdf(self):
        """파일 인자로 뜬 창 — 이 창은 PDF 모드로 시작한다(D1). 시작 복원보다 먼저 부른다."""
        self._photo_forced_pdf = True
        if self._photo_mode:
            self._set_photo_mode(False, remember=False)

    # ── 모드 ─────────────────────────────────────────
    def _photo_toggle(self, _checked=False):
        self._set_photo_mode(not self._photo_mode)

    def _set_photo_mode(self, on: bool, remember: bool = True, load_last: bool = True):
        """모드를 바꾼다. `load_last=False` — 새 모드의 마지막 문서를 열지 않는다(4.2): ① 창을 만들 때의 모드 복원 — 무엇을 열지는
        시작 복원 `_restore_session_deferred` 가 정한다(여기서 사진을 열면 그 복원이 '이미 열었다' 로 보고 시작 폴더를 건너뛰었다,
        261104-20) ② 곧 열 파일이 정해진 전환(`open_pdf`·`open_pdfs`) — 마지막 PDF 를 한 번 더 열지 않는다."""
        on = bool(on) and self._photo_enabled()
        if on == self._photo_mode:
            return
        if not self._photo_leave_guard():                # 저장 안 한 편집 — 취소면 모드를 바꾸지 않는다(261104-17)
            self._photo_refresh_button()
            return
        mv = getattr(self, "main_view", None)
        prev = mv.current_file() if mv is not None else None
        prev_page = mv.current_page() if (mv is not None and prev) else 0
        if prev and not self._photo_mode and str(prev).lower().endswith(".pdf"):
            self._photo_pdf_last = (str(prev), int(prev_page or 0))   # PDF 는 보던 쪽까지(이 실행 안)
        self._photo_capture_last()                       # 떠나는 모드의 마지막 자리(6.1, 261105-1)
        self._photo_mode = on
        if remember:
            self._photo_prefs()["mode"] = "photo" if on else "pdf"
        self._photo_swap_lists(on)
        plan = self._photo_mode_folder(on) if load_last else ("keep", None)
        if plan[0] != "keep":                            # 다른 폴더를 연다 — 앞 모드 폴더를 새 모드로 한 번 더 훑지 않게 떼어 둔다
            self.bookmark_tree._root_dir = None          # (set_photo_mode 는 뿌리가 없으면 목록만 비운다)
        self._photo_refresh_button()
        self._photo_on_mode_changed(on)
        if load_last:
            if self._photo_swap_folder(plan):            # 그 모드의 마지막 폴더(6.1, 261105-24)
                self._photo_swap_document(on, prev)
            self._photo_check_listed_soon()              # 본문은 늘 책갈피창 목록에 있는 파일(6.1, 261105-23)

    def _photo_leave_guard(self) -> bool:
        """모드를 바꾸기 전 — 편집 모드의 저장 안 한 꾸밈·쪽 편집은 파일을 옮길 때와 같은 확인 창(`_confirm_edit_save`). 취소면 False."""
        try:
            meta_dirty = self._in_edit() and self._edit_snap is not None and self._edit_dirty
            page_dirty = self._in_edit() and self._page_edits_dirty()
        except Exception:
            return True
        if not (meta_dirty or page_dirty):
            return True
        cur = self.main_view.current_file() if self.main_view else None
        choice = self._confirm_edit_save(switching=True)
        if choice == "cancel":
            return False
        if choice == "save":
            if page_dirty and cur:
                self._save_page_edits_for(cur)
            if meta_dirty:
                self._commit_edit()
        else:
            if meta_dirty:
                self._restore_edit()
            if page_dirty and cur:
                self._discard_page_edits(cur)
        self._edit_snap = None
        return True

    def _photo_mode_folder(self, on: bool):
        """바꿀 모드에서 열 폴더(6.1, 261105-24 사용자 지시·결정) — 모드마다 마지막 자리(`_photo_mode_last`)의 대상.
        → ("keep", None): 그 모드의 기억이 없다 — 지금 폴더 그대로(사용자 결정 '지금 폴더 그대로') ·
          ("open", (Path, "folder"|"file")) · ("empty", None): 기억한 폴더도 그 모드 최근 폴더도 없다.
        기억한 폴더가 없어졌으면 그 모드 **최근 폴더** 중 있는 것 맨 앞(사용자 결정). `_photo_swap_lists` 뒤에 부른다(최근 폴더가 새 모드 것)."""
        rec = (self.__dict__.get("_photo_mode_last") or {}).get("photo" if on else "pdf") or {}
        lo = rec.get("last_open") if isinstance(rec.get("last_open"), dict) else {}
        target, kind = str(lo.get("path") or ""), lo.get("kind")
        if not target:
            target, kind = str(rec.get("last_folder") or ""), "folder"
        if not target:
            return "keep", None
        p = Path(target)
        if p.exists():
            if kind not in ("file", "folder"):
                kind = "file" if p.is_file() else "folder"
            if kind == "file" and (on or p.suffix.lower() != ".pdf"):
                p, kind = p.parent, "folder"             # 사진 모드는 늘 폴더로
            return "open", (p, kind)
        for f in list(getattr(self, "_recent_folders", []) or []):
            if os.path.isdir(str(f)):
                return "open", (Path(str(f)), "folder")
        return "empty", None

    def _photo_swap_folder(self, plan) -> bool:
        """`_photo_mode_folder` 의 결과대로 책갈피창을 연다. 본문을 고를 일이 남았으면 True(파일 하나를 연 PDF 는 이미 열었다)."""
        what, arg = plan
        if what == "keep":
            return True
        if what == "empty":
            self._clear_workspace()
            self._folder = None
            self._photo_clear_document()
            self.status.showMessage(tr("이 모드에서 마지막으로 연 폴더가 없어졌습니다."), 5000)
            return False
        p, kind = arg
        if kind == "file":                               # PDF 모드에서 파일 하나만 보던 것 — 그 파일만(마스터 260906-3)
            self.open_pdf(p)
            lm = ((self.__dict__.get("_photo_mode_last") or {}).get("pdf") or {}).get("last_main") or {}
            if isinstance(lm, dict) and os.path.normcase(str(lm.get("file_path") or "")) == os.path.normcase(str(p)):
                try:
                    self.main_view.go_to_page(int(lm.get("page_index") or 0))
                except Exception:
                    pass
            return False
        self.open_folder(p)
        return True

    def _photo_clear_document(self):
        """본문·썸네일 칸·텍스트 창·창 제목을 비운다."""
        try:
            self.main_view.close_document()
            self.page_thumbs.clear_document()
            self.page_thumbs.set_title("")
        except Exception:
            pass
        self._current_main = None
        try:
            self._reload_text_panel()
            self._update_title()
        except Exception:
            pass

    def _photo_swap_document(self, on: bool, prev):
        """모드가 바뀌면 본문(과 썸네일 칸·텍스트 창·쪽 칸)이 앞 모드 문서를 버리고 새 모드의 마지막 자리를 연다 —
        **지금 책갈피창 폴더 안의 파일만**(6.1, 261105-23): 그 모드에서 마지막으로 보던 것(PDF 는 이 실행에서 보던 쪽까지) →
        그 모드의 최근 파일 맨 앞(모드마다 따로, 4.7). 없으면 빈 화면(4.2, 261104-17 사용자 보고).
        종전에는 폴더와 상관없이 최근 PDF 를 열어, 사진 폴더 그대로 PDF 모드로 오면 목록('0개 PDF')에 없는 PDF 가 본문에 남았다."""
        from viewer.history import HistoryItem
        root = getattr(self, "_folder", None)
        if root is None:
            self._photo_clear_document()
            return

        def inside(t) -> bool:
            try:
                return Path(root) in Path(str(t)).parents
            except Exception:
                return False

        def kind_ok(t) -> bool:
            return self._is_photo_path(t) if on else str(t).lower().endswith(".pdf")

        target, page = None, 0
        cands = []
        last = self.__dict__.get("_photo_pdf_last") if not on else None
        if last:
            cands.append((last[0], last[1]))
        lm = ((self.__dict__.get("_photo_mode_last") or {}).get("photo" if on else "pdf") or {}).get("last_main")
        if isinstance(lm, dict) and lm.get("file_path"):
            cands.append((str(lm["file_path"]), int(lm.get("page_index") or 0) if not on else 0))
        cands += [(str(t), 0) for t in list(getattr(self, "_recent_files", []) or [])]
        for t, pg in cands:
            if kind_ok(t) and inside(t) and os.path.isfile(t) and not self._photo_any_cached([t]):
                target, page = t, pg
                break
        if prev and target and os.path.normcase(str(prev)) == os.path.normcase(target) \
                and self.main_view.current_file():
            return
        self._photo_clear_document()
        if target:
            self._load_main(HistoryItem(target, int(page or 0), "", "bookmark"))

    def _photo_check_listed_soon(self):
        """모드를 바꾼 뒤 본문 파일이 책갈피창 목록에 없으면 비운다(6.1, 261105-23 사용자 지시 '이 경우에는 안 보여야 해').
        목록을 채우는 중이면 다 찬 뒤(`filesListed`) 한 번, 다 찼으면 바로."""
        bt = self.bookmark_tree
        busy = getattr(bt, "_scan_worker", None) is not None or bt._fill_timer.isActive()
        if busy:
            self._photo_listed_check = True
        else:
            self._photo_drop_unlisted()

    def _photo_drop_unlisted(self):
        cur = self.main_view.current_file() if self.main_view else None
        if not cur:
            return
        bt = self.bookmark_tree
        have = {os.path.normcase(str(it.data(0, bt.DATA_FILE) or "")) for it in bt._iter_file_nodes()}
        if os.path.normcase(str(cur)) not in have:
            self._photo_clear_document()

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
        self._photo_fit_combo(on)                      # 창 아래 맞춤 콤보 '원래 크기'(4.16, 261105-16)
        self._photo_watch_update()                     # 폴더 감시(4.27, 261104-7 B2) — 사진 모드에서만
        if not on:
            self._photo_search_paths = None
            self._photo_zip_paths = None
            self._photo_device_stop()
            self._photo_kind_stop()                     # 종류 자동 태그(태그 SOT §5.7) — 사진 모드에서만
            self._photo_anim_stop(hide=True)
            self._photo_deco_gate(True)
            self._photo_info_hide()
            self._photo_resume_index()
        else:
            try:
                self._cancel_active_indexing()          # 돌던 PDF 색인은 멈춘다(4.23) — PDF 모드로 오면 다시
                self._photo_index_skipped = True
            except Exception:
                pass
            self._photo_index_start()                   # 사진 정보 색인(4.24, D19)
        hook = getattr(self, "_photo_after_mode", None)
        if hook is not None:
            hook(on)

    def _photo_index_start(self):
        """사진 정보 색인(4.24, D19) — 사진 모드에서 연 폴더(하위 포함)를 배경에서 훑어 바뀐 사진만 다시 읽는다. 앞 일은 멈춘다(세대 토큰)."""
        folder = getattr(self, "_folder", None)
        if not folder or not getattr(self, "_photo_mode", False):
            return
        from viewer.workers import run_in_thread
        old = self.__dict__.get("_photo_indexer")
        if old is not None:
            old.request_cancel()
        self._photo_kind_stop()
        prefs = getattr(self, "_prefs", {}) or {}
        w = PhotoIndexWorker(str(folder), autotag=bool(prefs.get("photo_auto_tag", True)))
        w.done.connect(self._photo_index_done)
        w.autoTags.connect(lambda d, _w=w: self._photo_autotag_apply(d, "meta", _w))
        self._photo_indexer = w
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))
        self._photo_dates_prime()                        # 색인에 있는 촬영일은 첫 그리기부터(4.37, 261105-10)

    def _photo_index_done(self, folder: str, n_new: int, n_gone: int, n_total: int):
        if self.__dict__.get("_photo_indexer") is not None and getattr(self._photo_indexer, "folder", None) == folder:
            self._photo_indexer = None
        if n_new or n_gone:
            self.status.showMessage(tr("사진 색인: {n}장 (새로 {a}·지움 {d})").format(n=n_total, a=n_new, d=n_gone), 4000)
        self._photo_kind_start(folder)

    # ── 사진 자동 태그(태그 SOT §5.7, 261105-6) — 값은 배경 워커가 만들고, 태그 저장소에는 메인이 쓴다 ─────
    def _photo_autotag_apply(self, found: dict, part: str, run=None):
        """워커가 만든 자동 태그를 태그 저장소의 그 부분(`set_auto_part`)에 — 사용자 태그·거절한 태그는 그대로.
        한 번의 훑기(run)에서 처음 바꿀 때 `file_tags.bak.json` 백업(태그 SOT §6·§8.5) — 실패하면 쓰지 않는다."""
        if not found:
            return
        store = getattr(getattr(self, "bookmark_tree", None), "_tags", None)
        if store is None:
            return
        runs = self.__dict__.setdefault("_photo_autotag_backed", set())
        rid = id(run) if run is not None else 0
        if rid not in runs:
            if all({t.lower() for t in store.get_auto_part(p, part)} == {t.lower() for t in ts} for p, ts in found.items()):
                return                                   # 바꿀 것이 없다 — 백업도 하지 않는다
            if not store.backup():                       # bulk() 밖에서 — 안에서는 빈 저장소의 파일이 아직 없어 복사가 실패한다
                self.status.showMessage(tr("태그 백업 실패 — 사진 자동 태그를 건너뜀"), 5000)
                return
            runs.add(rid)
        dirty = self.__dict__.setdefault("_photo_autotag_dirty", set())
        with store.bulk():
            for path, tags in found.items():
                if store.set_auto_part(path, part, tags):
                    dirty.add(os.path.normcase(str(path)))
        if dirty:
            self._photo_autotag_refresh_soon()

    def _photo_autotag_refresh_soon(self):
        """태그 꼬리 다시 그리기를 모은다(0.5초) — 50장마다 목록 전체를 다시 그리지 않게."""
        t = self.__dict__.get("_photo_autotag_timer")
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(500)
            t.timeout.connect(self._photo_autotag_refresh)
            self._photo_autotag_timer = t
        t.start()

    def _photo_autotag_refresh(self):
        """바뀐 사진 줄의 태그 꼬리만, `batch_rows()` 안에서 — 한 줄씩 `setText` 하면 트리가 매번 모든 행을 다시 재
        1,500장 폴더에서 메인이 2초 넘게 섰다(행 수의 제곱, 실측 — `refresh_tag_labels` 를 쓰지 않는 까닭)."""
        dirty = self.__dict__.pop("_photo_autotag_dirty", set())
        if not dirty:
            return
        main = getattr(self, "bookmark_tree", None)
        for bt in (main, getattr(self, "bookmark_tree_right", None)):
            if bt is None or getattr(bt, "_tags", None) is None:
                continue
            try:
                if bt is not main:
                    bt._tags._load()                     # 아래 창은 저장소를 따로 든다 — 디스크에서 다시
                with bt.batch_rows():
                    for it in bt._iter_file_nodes():
                        pth = it.data(0, bt.DATA_FILE)
                        if pth and os.path.normcase(str(pth)) in dirty:
                            bt._apply_tag_label(it, pth)
                if "#" in (bt.search_edit.text() or ""):
                    bt._on_filter(bt.search_edit.text())  # `#태그` 로 거르는 중이면 다시 거른다
            except Exception:
                pass

    def _photo_kind_start(self, folder: str):
        """종류 자동 태그(영수증·명함·서류) — 색인 훑기 뒤 배경에서(설정 `photo_kind_ocr`, 기본 켬)."""
        prefs = getattr(self, "_prefs", {}) or {}
        if not getattr(self, "_photo_mode", False) or not prefs.get("photo_auto_tag", True) or not prefs.get("photo_kind_ocr", True):
            return
        if str(folder) != str(getattr(self, "_folder", "") or ""):
            return
        from viewer.workers import run_in_thread
        self._photo_kind_stop()
        w = PhotoKindWorker(str(folder))
        w.found.connect(lambda d, _w=w: self._photo_autotag_apply(d, "kind", _w))
        w.finished.connect(lambda _w=w: self.__dict__.get("_photo_kinder") is _w and setattr(self, "_photo_kinder", None))
        self._photo_kinder = w
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_kind_stop(self):
        w = self.__dict__.get("_photo_kinder")
        if w is not None:
            try:
                w.request_cancel()
            except Exception:
                pass
            self._photo_kinder = None

    def _photo_search(self, query: str):
        """사진 모드 검색(4.24, R13) — 사진 정보 색인에서 이름·촬영일·카메라·태그로 찾아 **썸네일 줄**에 결과를 보이고 첫 사진을 연다.
        빈 검색어면 폴더 전체로 돌아간다. zip 안 사진은 조각 ③·④ 뒤에 결과에 든다."""
        from viewer import photo_index
        q = (query or "").strip()
        strip = self._photo_strip_widget()
        if not q:
            self._photo_search_paths = None
            self._photo_zip_paths = None                 # '폴더 전체' 로 — zip 보기도 내려놓는다
            cur = self.main_view.current_file() if self.main_view else None
            strip.set_paths(self._photo_strip_source(), current=str(cur) if cur else None)
            self.status.showMessage(tr("사진 검색을 지웠습니다 — 폴더 전체."), 3000)
            return
        rows = photo_index.search(q, folder=getattr(self, "_folder", None))
        paths = []
        zips = {}
        for r in rows:
            if r.get("zip"):
                zips.setdefault(r["zip"], []).append(r["member"])
                continue
            p = Path(r["path"])
            if p.exists():
                paths.append(str(p))
        if not paths and zips:
            # zip 안에서만 찾았다 — 그 zip 을 열어(꺼내) 맞은 사진부터 보인다(4.24 ④)
            zp, members = next(iter(zips.items()))
            self._photo_open_zip(zp)
            self.status.showMessage(tr("'{q}': {name} 안 사진 {n}장").format(q=q, name=Path(zp).name, n=len(members)), 6000)
            return
        if not paths:
            self.status.showMessage(tr("'{q}' 에 맞는 사진이 없습니다.").format(q=q), 5000)
            return
        self._photo_search_paths = paths
        self._on_bookmark_activated(paths[0], 0)
        strip.set_paths(paths, current=paths[0])
        self.status.showMessage(tr("사진 검색 '{q}': {n}장").format(q=q, n=len(paths)), 6000)

    # ── 폴더 감시 (4.27, 261104-7 B2 — 사진 SOT §5 '폴더 감시') ─────────────────
    def _photo_watch_update(self):
        """사진 모드에서 보는 폴더 **하나**만 감시한다(하위 폴더는 보지 않는다). 사진 모드가 아니면 감시를 놓는다."""
        from PyQt6.QtCore import QFileSystemWatcher, QTimer
        w = self.__dict__.get("_photo_watcher")
        folder = str(getattr(self, "_folder", "") or "")
        want = folder if (getattr(self, "_photo_mode", False) and folder and os.path.isdir(folder)) else ""
        if w is None:
            if not want:
                return
            w = QFileSystemWatcher(self)
            w.directoryChanged.connect(lambda _p: self._photo_watch_timer.start())
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(WATCH_DEBOUNCE_MS)
            t.timeout.connect(self._photo_watch_fire)
            self._photo_watcher, self._photo_watch_timer = w, t
        cur = w.directories()
        if cur and (not want or os.path.normcase(cur[0]) != os.path.normcase(want)):
            w.removePaths(cur)
            self._photo_watch_sig = None
        if want and not w.directories():
            w.addPath(want)
            self._photo_watch_sig = None
            self._photo_watch_fire(quiet=True)          # 지금 지문을 잡아 둔다(다음 바뀜과 견주게)

    def _photo_watch_fire(self, quiet: bool = False):
        """알림을 모은 뒤 — 배경에서 사진·zip 목록 지문을 재고 바뀌었을 때만 다시 읽는다(우리가 쓰는 사이드카 `page_meta.json` 등은 지문에 없다)."""
        folder = str(getattr(self, "_folder", "") or "")
        if not folder or not getattr(self, "_photo_mode", False):
            return
        from viewer.workers import run_in_thread
        w = PhotoWatchScanWorker(folder)
        w.done.connect(lambda f, sig, q=quiet: self._photo_watch_scanned(f, sig, q))
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_watch_scanned(self, folder: str, sig, quiet: bool):
        if not getattr(self, "_photo_mode", False) or os.path.normcase(folder) != os.path.normcase(str(getattr(self, "_folder", "") or "")):
            return
        old = self.__dict__.get("_photo_watch_sig")
        self._photo_watch_sig = sig
        if quiet or old is None or old == sig:
            return
        bt = self.bookmark_tree
        if bt.is_edit_mode() and getattr(bt, "_dirty", False):
            return                                       # 저장 안 한 고침이 있으면 다시 읽지 않는다(묻는 창을 띄우지 않게)
        self._photo_relist_keep = folder                  # 같은 폴더 다시 읽기 — 검색 결과·zip 보기는 지킨다(4.27)
        bt.refresh()                                     # 다시 읽기(폴더 열기 3단 — 배경 훑기)
        self._photo_index_start()                        # 사진 색인도 바뀐 것만
        self.status.showMessage(tr("폴더가 바뀌어 사진 목록을 새로 읽었습니다."), 3000)

    # ── 2분할 비교 — 함께 움직이기 (4.28, 261104-7 B3, §5.1 F3) ─────────────────
    def _photo_pair_set(self, on: bool):
        """두 창의 확대·스크롤·넘김을 함께. 켜면 지금 창의 맞춤·배율을 다른 창에 맞춘다."""
        self._photo_pair_on = bool(on)
        if on:
            self._photo_pair_wire()
            self._photo_pair_zoom(self._active_pane)
            self._photo_pair_scroll(self._active_pane)
        self.status.showMessage(tr("2분할 함께 움직이기: 켬") if on else tr("2분할 함께 움직이기: 끔"), 2500)

    def _photo_pair_ok(self) -> bool:
        if not (self.__dict__.get("_photo_pair_on") and getattr(self, "_split_on", False) and getattr(self, "_photo_mode", False)):
            return False
        mvs = getattr(self, "_mv", [])
        return len(mvs) >= 2 and all(getattr(getattr(m, "_doc", None), "is_photo", False) for m in mvs[:2])

    def _photo_pair_wire(self):
        if self.__dict__.get("_photo_pair_wired"):
            return
        self._photo_pair_wired = True
        for i, mv in enumerate(self._mv[:2]):
            for sb in (mv.view.horizontalScrollBar(), mv.view.verticalScrollBar()):
                sb.valueChanged.connect(lambda _v, k=i: self._photo_pair_scroll(k))
                sb.rangeChanged.connect(lambda _a, _b, k=i: self._photo_pair_zoom(k))

    def _photo_pair_zoom(self, src: int):
        """한 창의 맞춤·배율이 바뀌었다 — 다른 창도 같게(사진 크기가 달라도 같은 맞춤 규칙·같은 배율)."""
        if not self._photo_pair_ok() or self.__dict__.get("_photo_pair_busy"):
            return
        a, b = self._mv[src], self._mv[1 - src]
        if b._fit_mode == a._fit_mode and (a._fit_mode != a.FIT_NONE or abs(b._zoom - a._zoom) < 1e-6):
            return
        self._photo_pair_busy = True
        try:
            b._fit_mode = a._fit_mode
            b._zoom = a._zoom
            b._show_fit(a._fit_mode)
            b._render_current()
        finally:
            self._photo_pair_busy = False
        self._photo_pair_scroll(src)

    def _photo_pair_scroll(self, src: int):
        """한 창을 스크롤했다 — 다른 창도 같은 비율 자리로."""
        if not self._photo_pair_ok() or self.__dict__.get("_photo_pair_busy"):
            return
        a, b = self._mv[src].view, self._mv[1 - src].view
        self._photo_pair_busy = True
        try:
            for sa, sb in ((a.horizontalScrollBar(), b.horizontalScrollBar()), (a.verticalScrollBar(), b.verticalScrollBar())):
                ra = sa.maximum() - sa.minimum()
                rb = sb.maximum() - sb.minimum()
                frac = (sa.value() - sa.minimum()) / ra if ra > 0 else 0.0
                sb.setValue(int(round(sb.minimum() + frac * rb)))
        finally:
            self._photo_pair_busy = False

    def _photo_pair_step(self, direction: int):
        """함께 움직이기 — 다른 창도 제 목록(그 창의 책갈피창 차례)에서 한 장 넘긴다."""
        if not self._photo_pair_ok() or self.__dict__.get("_photo_pair_stepping"):
            return
        other = 1 - self._active_pane
        mv = self._mv[other]
        bt = self.bookmark_tree_right if other == 1 else self.bookmark_tree
        cur = mv.current_file()
        lst = [str(it.data(0, bt.DATA_FILE)) for it in bt._iter_file_nodes()
               if it.data(0, bt.DATA_FILE) and self._is_photo_path(it.data(0, bt.DATA_FILE)) and not it.isHidden()]
        norm = [str(Path(p)) for p in lst]
        if not cur or str(Path(cur)) not in norm:
            return
        j = norm.index(str(Path(cur))) + (1 if direction > 0 else -1)
        if not (0 <= j < len(lst)):
            return
        me = self._active_pane
        self._photo_pair_stepping = True
        try:
            from viewer.history import HistoryItem
            self._set_active_pane(other)
            self._load_main(HistoryItem(lst[j], 0, "", "bookmark"))   # 그 창에(옆 창에 열기와 같은 길 — 책갈피창 신호는 위 창 기준이다)
        finally:
            self._set_active_pane(me)
            self._photo_pair_stepping = False

    # ── 지도 (4.29, 261104-7 B4·261105-17, §5.1 F6·D18) ─────────────────
    def _photo_map_show(self, paths):
        """고른 사진들을 한 지도에 — 위치 읽기·페이지 만들기는 배경(`PhotoMapWorker`), 메인은 확인 창과 브라우저 열기만."""
        from viewer import photo_map
        from viewer.workers import run_in_thread
        paths = [str(p) for p in (paths or []) if p]
        if not paths:
            return
        if self.__dict__.get("_photo_map_bridge") is None:
            b = photo_map.MapBridge(self)                # 브라우저의 [PolyPDF 에서 열기·고르기] → 메인
            b.picked.connect(self._photo_map_picked)
            photo_map.set_bridge(b)
            self._photo_map_bridge = b
        old = self.__dict__.get("_photo_mapper")
        if old is not None:
            old.request_cancel()
        w = photo_map.PhotoMapWorker(paths)
        w.done.connect(lambda r, _w=w: self._photo_map_done(r, _w))
        self._photo_mapper = w
        try:
            self.statusBar().showMessage(tr("사진 위치를 읽는 중… ({n}장)").format(n=len(paths)), 3000)
        except Exception:
            pass
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_map_done(self, r: dict, w=None):
        if w is not None and self.__dict__.get("_photo_mapper") is not w:
            return                                       # 뒤에 다시 불렀다
        self._photo_mapper = None
        shown, no_gps, cloud = int(r.get("shown", 0)), int(r.get("no_gps", 0)), int(r.get("cloud", 0))
        skip = []
        if no_gps:
            skip.append(tr("위치가 없는 사진 {n}장").format(n=no_gps))
        if cloud:
            skip.append(tr("클라우드에만 있어 읽지 않은 사진 {n}장").format(n=cloud))
        if not shown or not r.get("url"):
            msg = tr("고른 사진에 촬영 위치가 없습니다.")
            if cloud:
                msg += "\n" + tr("클라우드에만 있어 읽지 않은 사진 {n}장 — 내려받은 뒤 다시 해 보세요.").format(n=cloud)
            QMessageBox.information(self, tr("지도에서 위치 보기"), msg)
            return
        msg = tr("사진 {n}장의 위치를 지도에 표시합니다.").format(n=shown)
        if skip:
            msg += "\n" + tr("빼는 것: {list}").format(list=", ".join(skip))
        msg += "\n\n" + tr("지도 그림은 OpenStreetMap 에서 받으며, 보이는 곳의 대략적인 위치가 그 서버로 보내집니다. 기본 브라우저로 열까요?")
        ans = QMessageBox.question(self, tr("지도에서 위치 보기"), msg)      # D18 — 매번 묻는다(기억하지 않는다)
        if ans != QMessageBox.StandardButton.Yes:
            return
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(r["url"]))

    def _photo_map_picked(self, paths: list):
        """지도 페이지의 [PolyPDF 에서 열기·고르기] — 책갈피창에서 그 사진들을 고르고(하나면 연다) 창을 앞으로."""
        try:
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass
        if not getattr(self, "_photo_mode", False):
            return
        from viewer.pathutil import norm_key
        want = {norm_key(p) for p in (paths or [])}
        bt = self.bookmark_tree
        found = []
        with bt.batch_rows():
            for it in bt._iter_file_nodes():
                d = it.data(0, bt.DATA_FILE)
                if d and norm_key(str(d)) in want:
                    found.append(it)
        if not found:
            return                                       # 다른 폴더로 옮겼다 — 아무것도 하지 않는다
        if len(found) == 1:
            self._on_bookmark_activated(str(found[0].data(0, bt.DATA_FILE)), 0)
        tree = bt.tree
        tree.blockSignals(True)                          # 고르기만 — 이동(파일 열기)은 하지 않는다
        try:
            tree.clearSelection()
            for it in found:
                par = it.parent()
                while par is not None:
                    par.setExpanded(True)
                    par = par.parent()
                it.setSelected(True)
            tree.setCurrentItem(found[0], 0, tree.selectionModel().SelectionFlag.NoUpdate)
            tree.scrollToItem(found[0])
        finally:
            tree.blockSignals(False)

    # ── 일괄 작업 (4.30, 261104-7 B5, §5.1 F7) ─────────────────
    def _photo_batch_dialog(self, paths):
        """고른 사진에 — 이름 바꾸기(이름_###)·크기 줄이기·형식 바꾸기. 하나를 골라 실행."""
        from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QRadioButton,
                                     QSpinBox, QVBoxLayout)
        paths = [p for p in (paths or []) if self._is_photo_path(p)]
        if not paths:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("일괄 작업 — 사진 {n}장").format(n=len(paths)))
        lay = QVBoxLayout(dlg)
        r_ren = QRadioButton(tr("이름 바꾸기 (이름_001 …)")); r_ren.setChecked(True)
        r_size = QRadioButton(tr("크기 줄이기 (새 파일)"))
        r_fmt = QRadioButton(tr("형식 바꾸기 (새 파일)"))
        form = QFormLayout()
        ed_name = QLineEdit(Path(paths[0]).parent.name or tr("사진"))
        sp_start = QSpinBox(); sp_start.setRange(0, 99999); sp_start.setValue(1)
        sp_side = QSpinBox(); sp_side.setRange(64, 20000); sp_side.setValue(BATCH_SIDE_DEFAULT); sp_side.setSuffix(" px")
        cb_fmt = QComboBox(); cb_fmt.addItem("JPEG", "jpg"); cb_fmt.addItem("PNG", "png"); cb_fmt.addItem("WebP", "webp")   # 261107-5
        form.addRow(tr("새 이름:"), ed_name)
        form.addRow(tr("시작 번호:"), sp_start)
        form.addRow(tr("긴 변:"), sp_side)
        form.addRow(tr("형식:"), cb_fmt)
        for w in (r_ren, r_size, r_fmt):
            lay.addWidget(w)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if not dlg.exec():
            return
        if r_ren.isChecked():
            self._photo_batch_rename(paths, ed_name.text().strip(), sp_start.value())
        elif r_size.isChecked():
            self._photo_batch_convert(paths, "size", side=sp_side.value())
        else:
            self._photo_batch_convert(paths, "format", fmt=str(cb_fmt.currentData()))

    def _photo_batch_rename(self, paths, base: str, start: int = 1) -> int:
        """이름 바꾸기 — `<base>_<번호>`(자릿수는 장 수에 맞춰 3자리 이상), 확장자 그대로. 마스터 §4.7.14 의 한 길(`_rename_bg` → `_after_rename`)을
        사진마다 — 태그·색인·꾸밈 사이드카·본문이 새 이름을 따른다. 바꿀 이름이 이미 있으면 **하나도 바꾸지 않고** 알린다. 바꾼 장 수."""
        from viewer.pathutil import safe_name
        base = safe_name(base or "", fallback=tr("사진"))
        paths = [str(p) for p in paths]
        width = max(3, len(str(int(start) + len(paths) - 1)))
        plan = [(Path(p), Path(p).with_name("%s_%0*d%s" % (base, width, int(start) + i, Path(p).suffix))) for i, p in enumerate(paths)]
        srcs = {os.path.normcase(str(a)) for a, _b in plan}
        clash = [b for a, b in plan if b.exists() and os.path.normcase(str(b)) not in srcs]
        if clash or len({os.path.normcase(str(b)) for _a, b in plan}) != len(plan):
            self.status.showMessage(tr("이미 있는 이름이 있어 바꾸지 않았습니다: {name}").format(name=clash[0].name if clash else base), 6000)
            return 0
        # 고른 것끼리 이름이 엇갈리면(가 → 나, 나 → 다) 임시 이름을 거친다
        bt = self.bookmark_tree
        stage = []
        for a, b in plan:
            if a == b:
                continue
            mid = a.with_name("~" + a.stem + ".polypix-ren" + a.suffix) if os.path.normcase(str(b)) in srcs else b
            stage.append((a, mid, b))
        n = 0
        for a, mid, _b in stage:
            bt.releaseFileRequested.emit(str(a))
            err = bt._rename_bg(a, mid, tr("이름 바꾸는 중…"))
            if err is not None:
                self.status.showMessage(tr("이름을 바꾸지 못했습니다: {name}").format(name=a.name), 6000)
                break
            bt._after_rename(bt._file_node_for_path(str(a)), a, mid)
            n += 1
        for a, mid, b in stage:
            if mid != b and mid.exists():
                if bt._rename_bg(mid, b, tr("이름 바꾸는 중…")) is None:
                    bt._after_rename(bt._file_node_for_path(str(mid)), mid, b)
        self.status.showMessage(tr("사진 {n}장의 이름을 바꿨습니다.").format(n=n), 5000)
        return n

    def _photo_batch_convert(self, paths, mode: str, side: int = 0, fmt: str = "jpg") -> list:
        """크기 줄이기·형식 바꾸기 — 배경 진행 창 하나에서 **새 파일**(원본 그대로). 보이는 그대로(EXIF 방향·보기 회전), EXIF·GPS 는 싣지 않는다.
        HEIC 로는 쓰지 않는다(쓰기 인코더 없음 — JPEG 으로). 만든 경로 목록."""
        from viewer import photo_doc, photo_io
        from viewer.pathutil import unique_path
        rots = {str(p): self._photo_rot_for(p) for p in paths}
        crops = {str(p): self._photo_crop_for(p) for p in paths}          # 보기 크롭(4.40)
        out = []

        def job(progress, _paths=[str(p) for p in paths]):
            from PIL import Image, ImageOps
            from viewer.twoup import MergeCancelled
            for i, p in enumerate(_paths):
                src = Path(p)
                try:
                    photo_io._prep(src)
                    with Image.open(str(src)) as im:
                        icc = im.info.get("icc_profile")
                        im = ImageOps.exif_transpose(im)
                        from viewer.photo_crop import crop_pil
                        im = photo_doc._rotate(crop_pil(photo_io.to_srgb(im, icc), crops.get(p)), rots.get(p, 0))
                        im.load()
                    heif = photo_io.is_heif(src)
                    if mode == "size":
                        if max(im.size) > int(side):
                            im.thumbnail((int(side), int(side)), Image.Resampling.LANCZOS)
                        ext = ".jpg" if heif or src.suffix.lower() in (".jpg", ".jpeg") else src.suffix.lower()
                        dst = unique_path(src.with_name("%s_%dpx%s" % (src.stem, int(side), ext)))
                    else:
                        ext = "." + fmt
                        dst = unique_path(src.with_name(src.stem + ext))
                    tmp = dst.with_name("~" + dst.name + ".polypix-tmp")
                    # 261107-5(4.30): 형식은 이름으로 넘긴다 — 임시 파일(…polypix-tmp)은 확장자가 없어 Pillow 가 짐작하지 못한다
                    if ext in (".jpg", ".jpeg"):
                        im.convert("RGB").save(str(tmp), "JPEG", quality=SHARE_JPEG_QUALITY)
                    elif ext == ".png":
                        im.save(str(tmp), "PNG")
                    elif ext == ".webp":
                        im.save(str(tmp), "WEBP", quality=SHARE_JPEG_QUALITY)
                    else:
                        from PIL import Image as _I
                        im.save(str(tmp), _I.registered_extensions().get(ext, "PNG"))
                    os.replace(str(tmp), str(dst))
                    out.append((p, str(dst)))
                except MergeCancelled:
                    raise
                except Exception:
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
                if progress is not None and progress(i + 1, len(_paths), tr("사진 바꾸는 중")) is False:
                    raise MergeCancelled()
        res = self._run_merge_job(job, tr("일괄 작업"))
        for src, dst in out:
            try:
                for bt in (self.bookmark_tree, getattr(self, "bookmark_tree_right", None)):
                    if bt is not None:
                        bt.add_or_refresh_file(dst, after=src)
            except Exception:
                pass
        if res.get("err"):
            self.status.showMessage(res["err"], 6000)
        else:
            self.status.showMessage(tr("새 파일 {n}장을 만들었습니다.").format(n=len(out)), 5000)
        return [d for _s, d in out]

    # ── 움직이는 GIF·WebP (4.31, 261104-7 B6, §5.1 F10) ─────────────────
    def _photo_anim_check(self, path):
        """첫 장만 보이고, 움직이는 그림이면 본문 왼쪽 아래에 ▶ — 재생은 누를 때만·보일 때만."""
        self._photo_anim_stop(hide=True)
        if not path or Path(str(path)).suffix.lower() not in ANIM_EXTS:
            return
        from PyQt6.QtGui import QImageReader
        r = QImageReader(str(path))
        if not (r.supportsAnimation() and r.imageCount() != 1):
            return
        b = self.__dict__.get("_photo_anim_btn")
        mv = self.main_view
        if b is None or b.parent() is not mv.view:
            b = QToolButton(mv.view)
            b.setObjectName("photoAnimPlay")
            b.setAutoRaise(False)
            b.setToolTip(tr("움직이는 그림 재생·멈춤"))
            b.clicked.connect(self._photo_anim_toggle)
            self._photo_anim_btn = b
            for sb in (mv.view.horizontalScrollBar(), mv.view.verticalScrollBar()):
                sb.rangeChanged.connect(lambda _a, _b: self._photo_anim_stop())    # 확대가 바뀌면 멈춘다(첫 장으로)
        b.setText("▶")
        b.adjustSize()
        b.move(12, max(0, mv.view.height() - b.height() - 12))
        b.show()
        b.raise_()
        self._photo_anim_path = str(path)

    def _photo_anim_toggle(self):
        lab = self.__dict__.get("_photo_anim_label")
        if lab is not None and lab.isVisible():
            self._photo_anim_stop()
            return
        path = self.__dict__.get("_photo_anim_path")
        mv = self.main_view
        item = getattr(mv, "_page_item", None)
        if not path or item is None:
            return
        from PyQt6.QtGui import QMovie
        from PyQt6.QtWidgets import QLabel
        rect = mv.view.mapFromScene(item.sceneBoundingRect()).boundingRect()
        if lab is None or lab.parent() is not mv.view.viewport():
            lab = QLabel(mv.view.viewport())
            lab.setObjectName("photoAnimLabel")
            self._photo_anim_label = lab
        movie = QMovie(path, parent=lab)
        movie.setScaledSize(rect.size())
        lab.setMovie(movie)
        lab.setGeometry(rect)
        lab.show()
        lab.raise_()
        movie.start()
        self._photo_anim_movie = movie
        b = self.__dict__.get("_photo_anim_btn")
        if b is not None:
            b.setText("■")
            b.raise_()

    def _photo_anim_stop(self, hide: bool = False):
        m = self.__dict__.pop("_photo_anim_movie", None)
        if m is not None:
            m.stop()
        lab = self.__dict__.get("_photo_anim_label")
        if lab is not None:
            lab.hide()
            lab.setMovie(None)
        b = self.__dict__.get("_photo_anim_btn")
        if b is not None:
            if hide:
                b.hide()
            else:
                b.setText("▶")

    def _photo_resume_index(self):
        """사진 모드에서 걸지 않은 PDF 색인을 PDF 모드로 돌아와 그 폴더에 다시 건다(4.23). 바뀐 것만 다시 읽는다(색인 SOT 규칙 그대로)."""
        if not self.__dict__.pop("_photo_index_skipped", False):
            return
        folder = getattr(self, "_folder", None)
        if not folder:
            return
        try:
            from viewer.workers import IndexWorker
            worker = IndexWorker(self._db_path, Path(folder))
            worker.progress.connect(self._on_index_progress)
            worker.finished.connect(self._on_index_finished)
            self._start_index_worker(worker)
        except Exception:
            pass

    def _photo_strip_widget(self, create: bool = True):
        s = getattr(self, "_photo_strip", None)
        if s is None and create:
            from viewer.widgets.photo_strip import PhotoStrip
            s = PhotoStrip(getattr(self.page_thumbs, "_icon_w", 130), self.page_thumbs)
            s.photoActivated.connect(lambda p: self._on_bookmark_activated(p, 0))
            s.menuRequested.connect(self._photo_strip_menu)          # 261104-3(4.20)
            s.deleteRequested.connect(self._photo_delete)            # 261104-4(4.25): Del
            s.nearEnd.connect(self._photo_device_next)                # 261104-9(4.33): 휴대 장치 — 끝에 닿으면 다음 폴더를 잇는다
            s.set_label_style(self._photo_strip_style())             # 261104-13(4.38): 보기설정 스타일
            s.verticalScrollBar().valueChanged.connect(
                lambda v, _s=s: v and v >= _s.verticalScrollBar().maximum() and self._photo_device_next())
            s.rotation_provider = self._photo_rot_for
            s.crop_provider = self._photo_crop_for                   # 261105-4(4.40)
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
        if self.__dict__.pop("_photo_listed_check", False):
            self._photo_drop_unlisted()                  # 모드를 바꾼 뒤 첫 목록(6.1, 261105-23)
        if not getattr(self, "_photo_mode", False):
            return
        keep = self.__dict__.pop("_photo_relist_keep", None)
        if keep and os.path.normcase(str(keep)) == os.path.normcase(str(getattr(self, "_folder", "") or "")):
            found = self.__dict__.get("_photo_search_paths")    # 폴더 감시의 다시 읽기 — 검색 결과에서 없어진 것만 뺀다(4.27)
            if found:
                self._photo_search_paths = [p for p in found if os.path.exists(p)] or None
        else:
            self._photo_search_paths = None          # 새 목록 — 앞 검색 결과는 내려놓는다
        self._photo_watch_update()                   # 폴더가 바뀌었으면 감시도 그 폴더로(4.27)
        cur = self.main_view.current_file() if self.main_view else None
        if cur and self._is_photo_path(cur):
            strip = self._photo_strip_widget()
            strip.set_paths(self._photo_strip_source(), current=str(cur))
            self._photo_sync_tree(cur)               # 다시 읽은 목록에서도 그 줄(4.26)
        self._photo_devices_refresh()                # 휴대 장치 줄(4.33) — 폴더 열기·🔄 때 배경에서 한 번
        self._photo_dates_start()                    # 책갈피창 이름 앞 날짜(4.37) — 배경에서 읽어 붙인다

    # ── 책갈피창 줄 표기 — 날짜(4.37, 261104-12)·보기설정 스타일(4.38, 261104-13) ─────────────────
    def _photo_dates_start(self):
        """목록의 사진·zip 줄 이름을 보기설정 스타일대로(기본 'YYYY-MM-DD 이름') — 날짜·가로×세로는 배경에서
        (사진 정보 색인이 캐시 → 없거나 바뀐 것만 머리 읽기). 이름·확장자·용량은 바로. 읽은 것은 기억한다."""
        from viewer.workers import run_in_thread
        if not getattr(self, "_photo_mode", False):
            return
        bt = self.bookmark_tree
        cache = self.__dict__.setdefault("_photo_date_cache", {})
        paths = []
        for it in bt._iter_file_nodes():
            p = str(it.data(0, bt.DATA_FILE) or "")
            if p and (self._is_photo_path(p) or p.lower().endswith(".zip")):
                paths.append(p)
        bt.photo_sort_time = self._photo_sort_time       # '수정일 순' 정렬도 같은 값(§4.37)
        self._photo_label_nodes = None
        self._photo_labels_apply(None)                   # 지금 아는 값으로 먼저(이름·용량·기억한 날짜)
        old = self.__dict__.get("_photo_dater")
        if old is not None:
            old.request_cancel()
        if not paths:
            return
        w = PhotoDateWorker(paths, dict(cache))
        w.batch.connect(lambda d, _w=w: self._photo_dates_got(d, _w))
        w.indexed.connect(lambda _w=w: self._photo_dates_resort(_w))     # ① 색인 단계가 끝나면 한 번(261105-10)
        w.finished.connect(lambda _w=w: self._photo_dates_done(_w))
        self._photo_dater = w
        self._photo_dates_new = False
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_dates_prime(self):
        """사진 모드에서 폴더를 열 때(색인 시작과 함께) — 그 폴더 색인 행의 날짜를 배경에서 먼저 기억한다(SQL 만, §4.37 261105-10).
        큰 폴더는 목록 훑기보다 대개 먼저 끝나 **첫 그리기부터** 촬영일 순. 늦으면 끝났을 때 다시 늘어놓는다."""
        from viewer.workers import run_in_thread
        folder = getattr(self, "_folder", None)
        if not folder or not getattr(self, "_photo_mode", False):
            return
        self.bookmark_tree.photo_sort_time = self._photo_sort_time
        old = self.__dict__.get("_photo_primer")
        if old is not None:
            old.request_cancel()
        w = PhotoDateWorker([], dict(self.__dict__.setdefault("_photo_date_cache", {})), folder=str(folder))
        w.batch.connect(lambda d, _w=w: self._photo_dates_got(d, _w))
        w.finished.connect(lambda _w=w: self._photo_dates_resort(_w))
        self._photo_primer = w
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_date_recheck(self, path):
        """본문에 연 사진이 클라우드에서 받아졌다(해독 끝) — 날짜가 임시 값이면 그 한 장만 머리를 읽어 줄 이름을 고친다(§4.37).
        순서는 다음 목록 그리기 때(보던 목록이 갑자기 움직이지 않게)."""
        from viewer.workers import run_in_thread
        key = os.path.normcase(str(path))
        cache = self.__dict__.get("_photo_date_cache", {})
        hit = cache.get(key)
        if not hit or len(hit) < 7 or not hit[6]:
            return
        cache[key] = tuple(hit[:6]) + (False,)          # 해독 알림이 여러 번 와도 한 번만
        w = PhotoDateWorker([str(path)], {}, force=True)
        w.batch.connect(lambda d, _w=w: self._photo_dates_got(d, _w))
        self.__dict__.setdefault("_photo_rechecks", set()).add(w)
        w.finished.connect(lambda _w=w: self.__dict__.get("_photo_rechecks", set()).discard(_w))
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    CLOSE_WAIT_MS = 500                              # 창을 닫을 때 사진 배경 작업을 기다리는 상한(합계)

    def _photo_close_workers(self):
        """창을 닫을 때 — 사진 배경 작업에 멈추라고 알리고 `CLOSE_WAIT_MS` 까지만 기다린다. 이어서 `main.py` 가 프로세스를 곧바로 끝내는데,
        그때 작업이 그림 라이브러리를 불러오는 중이면 종료가 막힐 수 있었다(묶음 검사에서 ALL PASS 뒤 10분 — 261104-13).
        휴대 장치(셸 COM) 작업은 응답 없는 장치에 붙들릴 수 있어 기다리지 않는다(4.33 '닫기')."""
        import time as _t
        from PyQt6.QtCore import QThread
        keep = list(self.__dict__.get("_photo_keep", []) or [])
        s = self.__dict__.get("_photo_strip")
        if s is not None:
            try:
                s.stop()
                keep += list(getattr(s, "_keep", []) or [])
            except Exception:
                pass
        skip = (PhotoDeviceListWorker, PhotoDeviceScanWorker, PhotoDeviceWorker)
        ths = []
        for i, obj in enumerate(keep):
            if isinstance(obj, QThread):
                w = keep[i + 1] if i + 1 < len(keep) else None
                if isinstance(w, skip):
                    continue
                if w is not None and hasattr(w, "request_cancel"):
                    try:
                        w.request_cancel()
                    except Exception:
                        pass
                ths.append(obj)
        end = _t.monotonic() + self.CLOSE_WAIT_MS / 1000.0
        for th in ths:
            left = int((end - _t.monotonic()) * 1000)
            if left <= 0:
                break
            try:
                if th.isRunning():
                    th.wait(left)
            except RuntimeError:
                pass

    def _photo_dates_got(self, found: dict, worker=None):
        live = (worker is self.__dict__.get("_photo_dater") or worker is self.__dict__.get("_photo_primer")
                or worker in self.__dict__.get("_photo_rechecks", ()))
        if not live or not getattr(self, "_photo_mode", False):
            return
        cache = self.__dict__.setdefault("_photo_date_cache", {})
        for p, rec in found.items():
            cache[os.path.normcase(p)] = tuple(rec)      # (수정 시각 ns, 날짜, 정렬 시각, 폭, 높이, 바이트)
        self._photo_dates_new = True
        self._photo_labels_apply(set(os.path.normcase(p) for p in found))

    def _photo_sort_time(self, path):
        hit = self.__dict__.get("_photo_date_cache", {}).get(os.path.normcase(str(path)))
        return hit[2] if hit else None

    def _photo_dates_done(self, worker=None):
        """새로 읽은 날짜가 있고 정렬이 '수정일 순' 이면 한 번 다시 늘어놓는다(같은 값으로 — §4.37). 기억한 값만 쓰니 다시 읽지 않는다."""
        if worker is not self.__dict__.get("_photo_dater"):
            return
        self._photo_dater = None
        self.__dict__.pop("_photo_dates_new", None)
        self._photo_dates_resort()

    def _photo_dates_resort(self, worker=None):
        """'수정일 순' 이고 지금 줄 순서가 기억한 값과 다르면 한 번 다시 늘어놓는다 — 미리 읽기·① 색인 단계·② 머리 읽기가 끝날 때(261105-10).
        목록을 채우는 중이면 하지 않는다(채우기가 끝나면 새 날짜 작업이 다시 본다)."""
        if worker is not None and worker is not self.__dict__.get("_photo_dater") and worker is not self.__dict__.get("_photo_primer"):
            return
        if worker is not None and worker is self.__dict__.get("_photo_primer"):
            self._photo_primer = None
        bt = self.bookmark_tree
        if not getattr(self, "_photo_mode", False):
            return
        if getattr(bt, "_mode", "") != "flat" or bt._sort_combo.currentData() != bt.SORT_MTIME:
            return
        if getattr(bt, "_fill_plan", None):
            return
        # '새로 읽은 것' 표시가 아니라 **지금 줄 순서**로 판단한다(261105-2) — 읽는 도중 목록을 다시 그리면 새 작업이 그 표시를 지워
        #   다시 늘어놓기를 건너뛰었고, 날짜가 섞인 목록이 남았다. 순서가 맞으면 다시 그리지 않는다(되먹임 없음).
        if not self._photo_tree_out_of_order(bt):
            return
        self._photo_relist_keep = str(getattr(self, "_folder", "") or "")   # 검색 결과·zip 보기는 지킨다(4.27)
        bt._render_flat(after=(lambda c=self.main_view.current_file() if self.main_view else None:
                               self._photo_sync_tree(c) if c else None))

    @staticmethod
    def _photo_tree_out_of_order(bt) -> bool:
        """같은 부모 아래 파일 줄이 정렬 값(`_sort_stat` — 사진은 촬영 시각) 내림차순이 아니면 True. 기억한 값만 쓴다(디스크를 읽지 않는다)."""
        from PyQt6.QtWidgets import QTreeWidgetItem

        def files_of(children):
            return [bt._sort_stat(str(c.data(0, bt.DATA_FILE)))[1] for c in children if c.data(0, bt.DATA_FILE)]

        tree = bt.tree
        parents = [[tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]]
        stack = list(parents[0])
        while stack:
            it: QTreeWidgetItem = stack.pop()
            if it.childCount():
                kids = [it.child(i) for i in range(it.childCount())]
                parents.append(kids)
                stack.extend(kids)
        for kids in parents:
            ks = files_of(kids)
            if any(a < b for a, b in zip(ks, ks[1:])):
                return True
        return False

    def _photo_label_values(self, path) -> dict:
        """구문에 넣을 값 — 기억한 날짜·크기·용량, 없으면 목록 훑기가 준 용량(`_scan_stats`)."""
        from viewer import photo_label as PL
        hit = self.__dict__.get("_photo_date_cache", {}).get(os.path.normcase(str(path)))
        if hit and len(hit) >= 6:
            return PL.values(path, hit[1], hit[3], hit[4], hit[5])
        nbytes = 0
        try:
            v = self.bookmark_tree._scan_stats.get(str(path))
            nbytes = int(v[0]) if v else 0
        except Exception:
            nbytes = 0
        return PL.values(path, hit[1] if hit else "", 0, 0, nbytes)

    def _photo_labels_apply(self, only=None):
        """책갈피창 사진·zip 줄 이름을 지금 스타일로(글 잇기만 — 메인). `only` 는 바꿀 줄(normcase 경로 모음), None 이면 모두."""
        from viewer import photo_label as PL
        bt = self.bookmark_tree
        tpl = PL.current(self._photo_prefs(), "tree")
        nodes = self.__dict__.get("_photo_label_nodes")
        if only is None or nodes is None:
            nodes = {}                                   # 경로 → 줄(목록을 다시 채우면 새로) — 알림마다 모든 줄을 훑지 않게
            for it in bt._iter_file_nodes():
                p = str(it.data(0, bt.DATA_FILE) or "")
                if p and (self._is_photo_path(p) or p.lower().endswith(".zip")):
                    nodes[os.path.normcase(p)] = it
            self._photo_label_nodes = nodes
        todo = nodes.items() if only is None else ((k, nodes[k]) for k in only if k in nodes)
        with bt.batch_rows():                            # 한 줄씩 바꾸면 트리가 매번 모든 행을 다시 잰다(행 수의 제곱)
            for _k, it in todo:
                try:
                    p = str(it.data(0, bt.DATA_FILE) or "")
                except RuntimeError:
                    continue                             # 지워진 줄
                base = PL.render(tpl, self._photo_label_values(p)) or Path(p).stem
                if it.data(0, bt.DATA_BASELABEL) == base:
                    continue
                it.setData(0, bt.DATA_BASELABEL, base)
                if getattr(bt, "_tags", None) is not None:
                    bt._apply_tag_label(it, p)           # 태그 꼬리는 그대로 다시 붙인다
                else:
                    it.setText(0, base)

    def _photo_label_dialog(self, which: str):
        """보기설정(4.38) — 책갈피창(`tree`)·썸네일창(`strip`) 줄 표기 스타일. 적용하면 다시 그린다."""
        from viewer.widgets.photo_label_dialog import PhotoLabelDialog
        cur = self.main_view.current_file() if self.main_view else None
        sample = self._photo_label_values(cur) if cur else {"name": tr("사진 이름"), "ext": "JPG", "date": "2025-06-10",
                                                               "size": "4032×3024", "bytes": "2.4MB"}

        def apply():
            self._photo_labels_apply(None)
            s = self._photo_strip_widget(create=False)
            if s is not None:
                s.set_label_style(self._photo_strip_style())
        dlg = PhotoLabelDialog(self, self._photo_prefs(), which, sample, on_apply=apply)
        dlg.exec()

    def _photo_strip_style(self):
        from viewer import photo_label as PL
        return PL.current(self._photo_prefs(), "strip")

    # ── 휴대 장치 — 둘러보기 + 복사 (4.33, 261104-9 사용자 결정) ─────────────────
    DEVICE_ROLE = Qt.ItemDataRole.UserRole + 40      # 책갈피창 장치 줄 표식 — (장치, 폴더 또는 '', 오류 종류 또는 '')

    def _photo_devices_refresh(self):
        from viewer.workers import run_in_thread
        from viewer import photo_device
        if photo_device.qt_test_mode() and isinstance(photo_device.BACKEND, photo_device.ShellBackend):
            return                                       # 검사는 실제 장치(셸)를 읽지 않는다 — 가짜 장치를 끼운 검사만(종료 때 셸 호출이 걸려 프로세스가 끝나지 않았다)
        old = self.__dict__.get("_photo_dev_lister")
        if old is not None:
            old.request_cancel()
        w = PhotoDeviceListWorker()
        w.done.connect(lambda found, _w=w: self._photo_devices_listed(found, _w))    # 보낸 일을 직접 넘긴다(배경 신호의 sender 는 비어 온다)
        self._photo_dev_lister = w
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_device_nodes(self):
        bt = self.bookmark_tree
        return [bt.tree.topLevelItem(i) for i in range(bt.tree.topLevelItemCount())
                if bt.tree.topLevelItem(i).data(0, self.DEVICE_ROLE)]

    def _photo_devices_listed(self, found: list, worker=None):
        """장치 줄을 다시 단다 — 파일 행이 아닌 가지 행(DATA_FILE 없음)이라 파일 작업·색인·태그가 닿지 않는다.
        트리(폴더) 보기: 장치·사진 폴더를 폴더 줄 모양으로, 연 폴더 아래 사진 줄. 단일 보기: 폴더 없이 장치의 모든 사진 줄
        (배경에서 새 폴더부터 이름만 읽어 붙인다 — 사용자 결정 261104-9)."""
        if worker is not None and worker is not self.__dict__.get("_photo_dev_lister"):
            return                                       # 앞 일의 늦은 결과
        self._photo_dev_lister = None
        if not getattr(self, "_photo_mode", False):
            return
        from PyQt6.QtWidgets import QStyle, QTreeWidgetItem
        bt = self.bookmark_tree
        tree = bt.tree
        for n in self._photo_device_nodes():
            tree.takeTopLevelItem(tree.indexOfTopLevelItem(n))
        if not self.__dict__.get("_photo_dev_wired"):
            self._photo_dev_wired = True
            tree.itemClicked.connect(self._photo_device_clicked)
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DriveCDIcon)
        as_folders = bt.is_tree_view()
        opened = self.__dict__.get("_photo_dev_open")
        names = self.__dict__.setdefault("_photo_dev_names", {})     # 장치 → [(폴더, [이름…])] — 다시 읽지 않게
        self._photo_dev_folders = {d: list(fs) for d, fs, e in found if not e}   # 이어 받기(다음 폴더)의 차례
        for gone in [d for d in names if d not in {f[0] for f in found}]:
            names.pop(gone, None)                        # 뽑힌 장치
        to_scan = []
        with bt.batch_rows():
            self._photo_devices_rows(bt, tree, found, icon, as_folders, opened, names, to_scan)
        if to_scan:
            self._photo_device_scan(to_scan)

    def _photo_devices_rows(self, bt, tree, found, icon, as_folders, opened, names, to_scan):
        from PyQt6.QtWidgets import QTreeWidgetItem
        for pos, (dev, folders, err) in enumerate(found):
            top = QTreeWidgetItem([dev])
            top.setIcon(0, icon)
            top.setData(0, self.DEVICE_ROLE, (dev, "", err or "", ""))
            if err:
                top.setToolTip(0, self._photo_device_error_text(dev, err))
            if as_folders:
                for f in folders:
                    ch = QTreeWidgetItem([f.rsplit("/", 1)[-1]])
                    ch.setData(0, self.DEVICE_ROLE, (dev, f, "", ""))
                    ch.setToolTip(0, dev + " › " + f.replace("/", " › "))
                    top.addChild(ch)
                    self._photo_device_folder_look(ch)
                    if opened and opened[0] == dev and f in self.__dict__.get("_photo_dev_loaded", []):
                        from viewer import photo_device as _pd
                        pd_dir = os.path.normcase(str(_pd.cache_dir_for(dev, f)))
                        self._photo_device_fill_rows(ch, dev, f, [Path(p).name for p in (self.__dict__.get("_photo_zip_paths") or [])
                                                                  if os.path.normcase(str(Path(p).parent)) == pd_dir])
                        ch.setExpanded(True)
                self._photo_device_folder_look(top)
            elif not err:
                if dev in names and [f for f, _n in names[dev]] == list(folders):
                    for f, nm in names[dev]:
                        self._photo_device_fill_rows(top, dev, f, nm)
                else:
                    names.pop(dev, None)
                    to_scan.append((dev, list(folders)))
            tree.insertTopLevelItem(pos, top)              # 맨 위에 — 꽂은 장치는 보려고 꽂은 것(사용자 지시)
            top.setExpanded(as_folders or not err)

    def _photo_device_scan(self, todo: list):
        """단일 보기 — 장치의 모든 사진 이름을 배경에서(새 폴더부터 한 폴더씩 알림). 받지는 않는다."""
        from viewer.workers import run_in_thread
        old = self.__dict__.get("_photo_dev_scanner")
        if old is not None:
            old.request_cancel()
        w = PhotoDeviceScanWorker(todo)
        w.folderScanned.connect(lambda d, f, nm, _w=w: self._photo_device_scanned(d, f, nm, _w))
        self._photo_dev_scanner = w
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_device_scanned(self, dev: str, folder: str, nm: list, worker=None):
        if worker is not self.__dict__.get("_photo_dev_scanner"):
            return
        self.__dict__.setdefault("_photo_dev_names", {}).setdefault(dev, []).append((folder, list(nm)))
        if self.bookmark_tree.is_tree_view():
            return
        top = next((t for t in self._photo_device_nodes() if t.data(0, self.DEVICE_ROLE)[0] == dev), None)
        if top is not None:
            with self.bookmark_tree.batch_rows():
                self._photo_device_fill_rows(top, dev, folder, nm)

    def _photo_device_fill_rows(self, parent, dev: str, folder: str, nm):
        """사진 줄 — 경로는 캐시에 받을 자리(받기 전에도 같은 경로라 본문 사진과 줄을 짝지을 수 있다)."""
        from PyQt6.QtWidgets import QTreeWidgetItem
        from viewer import photo_device
        from viewer.widgets.icons import file_kind_icon
        d = photo_device.cache_dir_for(dev, folder)
        rows = []
        for n in nm:
            it = QTreeWidgetItem([Path(n).stem])
            it.setIcon(0, file_kind_icon(n))
            it.setData(0, self.DEVICE_ROLE, (dev, folder, "", str(d / n)))
            it.setToolTip(0, dev + " › " + folder.rsplit("/", 1)[-1] + " › " + n)
            rows.append(it)
        parent.addChildren(rows)

    def _photo_device_folder_look(self, item):
        """폴더 줄 모양(책갈피창 트리 보기의 폴더 그룹 행과 같게 — 디자인 §2.5). 폴더 표식(DATA_IS_FOLDER)은 달지 않는다 —
        폴더 행 메뉴(탐색기에서 열기 등)가 장치 줄에 닿지 않게."""
        from PyQt6.QtGui import QBrush, QColor, QFont
        bt = self.bookmark_tree
        item.setBackground(0, QBrush(QColor(bt.FOLDER_ROW_BG)))
        item.setForeground(0, QBrush(QColor(bt.FOLDER_ROW_FG)))
        f = QFont(bt.tree.font()); f.setBold(True); item.setFont(0, f)
        if item.parent() is not None:
            try:
                from viewer.widgets.icons import themed_icon
                item.setIcon(0, themed_icon("folder", dark=False))
            except Exception:
                pass

    def _photo_device_folder_item(self, dev: str, folder: str):
        for top in self._photo_device_nodes():
            k = top.data(0, self.DEVICE_ROLE)
            if k and k[0] == dev:
                for i in range(top.childCount()):
                    ch = top.child(i)
                    kk = ch.data(0, self.DEVICE_ROLE)
                    if kk[1] == folder and not kk[3]:
                        return ch
        return None

    def _photo_device_error_text(self, dev: str, kind: str) -> str:
        if kind == "locked":
            return tr("{dev}: 장치를 열 수 없습니다 — 잠금을 풀고 '이 컴퓨터 신뢰' 를 누른 뒤 🔄 를 누르세요.").format(dev=dev)
        if kind == "timeout":
            return tr("{dev}: 사진을 받는 동안 응답이 없습니다 — 연결을 확인하세요. 복사한 사진만 보입니다.").format(dev=dev)
        return tr("{dev}: 연결이 끊겼습니다 — 복사한 사진만 보입니다.").format(dev=dev)

    def _photo_device_clicked(self, item, _col=0):
        key = item.data(0, self.DEVICE_ROLE) if item is not None else None
        if not key:
            return
        dev, folder, err, path = key
        if err:
            self.status.showMessage(self._photo_device_error_text(dev, err), 8000)
            return
        if path:                                         # 사진 줄 — 그 폴더를 보고 있고 받아 둔 사진이면 바로, 아니면 그 폴더를 받으며 이 사진부터
            op = self.__dict__.get("_photo_dev_open")
            if op and op[0] == dev and folder in self.__dict__.get("_photo_dev_loaded", []):
                if path in (self.__dict__.get("_photo_zip_paths") or []):
                    self._on_bookmark_activated(path, 0)
                    return
                if self.__dict__.get("_photo_dev_worker") is not None:
                    self._photo_dev_want = path          # 받는 중 — 그 사진이 들어오면 연다
                    return
            self._photo_open_device(dev, folder, want=path)
            return
        if folder:
            self._photo_open_device(dev, folder)

    def _photo_device_next(self, open_first: bool = False):
        """썸네일 줄 끝에 닿았다 — 휴대 장치를 보는 중이면 다음(더 오래된) 폴더를 **이어** 받는다(줄은 그대로, 아래에 더한다, 사용자 지시).
        받는 중이면 기다린다. 더 없으면 알림만. open_first: 넘김(다음 사진)으로 닿았으면 이어 받은 첫 장을 연다."""
        op = self.__dict__.get("_photo_dev_open")
        if not op or self.__dict__.get("_photo_dev_worker") is not None or not self.__dict__.get("_photo_zip_paths"):
            return False
        dev = op[0]
        folders = (self.__dict__.get("_photo_dev_folders") or {}).get(dev) or []
        loaded = self.__dict__.get("_photo_dev_loaded") or []
        rest = [f for f in folders if f not in loaded]
        if not rest or not loaded or loaded[-1] not in folders:
            return False
        nxt = next((f for f in folders[folders.index(loaded[-1]) + 1:] if f not in loaded), None)
        if nxt is None:
            if open_first:
                self.status.showMessage(tr("마지막 사진입니다."), 2000)
            return False
        self._photo_open_device(dev, nxt, append=True, open_first=open_first)
        return True

    def _photo_open_device(self, dev: str, folder: str, want: str | None = None, append: bool = False, open_first: bool = False):
        """사진 폴더 하나를 캐시로 복사하며 본다 — 복사된 차례로 썸네일 줄에, 첫 장(또는 누른 사진 — 그것부터 받는다)을 연다(4.33).
        append: 썸네일 줄 끝에 이어 받는다(지금 사진·줄은 그대로, 제목은 장치 이름)."""
        from viewer.workers import run_in_thread
        if append:
            self._photo_dev_loaded = list(self.__dict__.get("_photo_dev_loaded") or []) + [folder]
            self._photo_group = (dev, None)
            self._photo_dev_want = None
            self._photo_dev_first = bool(open_first)
            try:
                self.page_thumbs.set_title(dev, None)
            except Exception:
                pass
            fi = self._photo_device_folder_item(dev, folder) if self.bookmark_tree.is_tree_view() else None
            if fi is not None:
                fi.setExpanded(True)
            self._photo_device_start(dev, folder, None)
            return
        self._photo_device_stop()
        old = self.__dict__.get("_photo_zipper")
        if old is not None:
            old.request_cancel()
            self._photo_zipper = None
        self._photo_zip_src = None
        self._photo_group = (dev + " › " + folder.rsplit("/", 1)[-1], None)
        self._photo_zip_paths = []
        self._photo_search_paths = None
        self._photo_dev_want = want
        self._photo_dev_first = want is None
        self._photo_dev_open = (dev, folder)
        self._photo_dev_loaded = [folder]
        if self.bookmark_tree.is_tree_view():              # 트리 보기 — 앞에 연 폴더의 사진 줄은 걷고 이 폴더를 펼친다
            for top in self._photo_device_nodes():
                for i in range(top.childCount()):
                    top.child(i).takeChildren()
            fi = self._photo_device_folder_item(dev, folder)
            if fi is not None:
                fi.setExpanded(True)
        try:
            self._photo_strip_widget().set_paths([])
            self.page_thumbs.set_title(self._photo_group[0], None)
        except Exception:
            pass
        self._photo_device_start(dev, folder, Path(want).name if want else None)

    def _photo_device_start(self, dev: str, folder: str, first):
        from viewer.workers import run_in_thread
        w = PhotoDeviceWorker(dev, folder, first)
        w.listed.connect(lambda n, _w=w: self._photo_device_listed_names(n, _w))
        w.fileReady.connect(lambda p, _w=w: self._photo_device_file(p, _w))
        w.done.connect(lambda d, f, n, e, _w=w: self._photo_device_done(d, f, n, e, _w))
        self._photo_dev_worker = w
        self.status.showMessage(tr("{dev} 에서 사진을 받는 중… {folder}").format(dev=dev, folder=folder.rsplit("/", 1)[-1]), 4000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_device_stop(self):
        w = self.__dict__.pop("_photo_dev_worker", None)
        if w is not None:
            w.request_cancel()

    def _photo_device_mine(self, worker) -> bool:
        return worker is not None and worker is self.__dict__.get("_photo_dev_worker")

    def _photo_device_listed_names(self, n: int, worker=None):
        if self._photo_device_mine(worker) and n == 0:
            self.status.showMessage(tr("이 폴더에는 사진이 없습니다."), 4000)

    def _photo_device_file(self, path: str, worker=None):
        if not self._photo_device_mine(worker):
            return
        lst = self.__dict__.setdefault("_photo_zip_paths", [])
        if lst is None:
            return                                       # 그새 장치 밖 사진을 열었다 — 줄은 그쪽
        lst.append(path)
        self._photo_strip_widget().append_paths([path])
        if self.bookmark_tree.is_tree_view():
            fi = self._photo_device_folder_item(*worker.dev_folder)
            if fi is not None:
                self._photo_device_fill_rows(fi, worker.dev, worker.folder, [Path(path).name])
        want = self.__dict__.get("_photo_dev_want")
        if (want and os.path.normcase(want) == os.path.normcase(path)) or (not want and self.__dict__.pop("_photo_dev_first", False)):
            self._photo_dev_want = None
            self._on_bookmark_activated(path, 0)

    def _photo_device_done(self, dev: str, folder: str, n: int, err: str, worker=None):
        if not self._photo_device_mine(worker):
            return
        self._photo_dev_worker = None
        lst = self.__dict__.get("_photo_zip_paths")
        if lst:                                          # 누른 사진부터 받았으면 줄 차례를 이름 차례로 되돌린다(이어 받은 폴더는 그 뒤에)
            from viewer import photo_device as _pd
            order = {os.path.normcase(str(_pd.cache_dir_for(dev, f))): i
                     for i, f in enumerate(self.__dict__.get("_photo_dev_loaded") or [folder])}
            lst.sort(key=lambda p: (order.get(os.path.normcase(str(Path(p).parent)), 0), Path(p).name.lower()))
            cur = self.main_view.current_file() if self.main_view else None
            self._photo_strip_widget().set_paths(lst, current=str(cur) if cur else None)
            if self.bookmark_tree.is_tree_view():
                fi = self._photo_device_folder_item(dev, folder)
                if fi is not None:
                    fi.takeChildren()
                    mine = os.path.normcase(str(_pd.cache_dir_for(dev, folder)))
                    self._photo_device_fill_rows(fi, dev, folder, [Path(p).name for p in lst
                                                                   if os.path.normcase(str(Path(p).parent)) == mine])
                if cur:
                    self._photo_sync_device_row(str(cur))
        if err:
            self.status.showMessage(self._photo_device_error_text(dev, err), 8000)
        else:
            self.status.showMessage(tr("{dev}: 사진 {n}장(읽기 전용)").format(dev=dev, n=n), 5000)

    # ── 사진 한 장 OCR → 텍스트 창 (4.34, 261104-10 P4-a, D15) ─────────────────
    def _photo_ocr_start(self):
        """지금 사진을 배경에서 읽는다(누를 때만). 결과는 보류 저장소 — 확정은 '💾 저장 안 한 OCR'·종료 창."""
        from viewer.workers import run_in_thread
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or not self._is_photo_path(cur) or self._photo_is_broken():
            return
        if self.__dict__.get("_photo_ocr_worker") is not None:
            self.status.showMessage(tr("사진 글자를 읽는 중입니다 — 끝난 뒤 다시 눌러 주세요."), 4000)
            return
        try:
            self._vm_text()
        except Exception:
            pass
        w = PhotoOcrWorker(str(cur), self._photo_rot_for(cur), None)   # 언어는 워커에서(OCR 모듈을 메인에서 처음 불러오지 않게)
        w.done.connect(self._photo_ocr_done)
        w.error.connect(lambda p, e: self.status.showMessage(tr("사진 글자를 읽지 못했습니다: {e}").format(e=e), 8000))
        w.finished.connect(lambda: self.__dict__.pop("_photo_ocr_worker", None))
        self._photo_ocr_worker = w
        tp = getattr(self, "text_panel", None)
        if tp is not None:
            tp.set_busy(tr("사진 글자를 읽는 중…"))
        self.status.showMessage(tr("사진 글자를 읽는 중… {name}").format(name=Path(str(cur)).name), 4000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_ocr_many(self, paths):
        """사진 여러 장 OCR(4.44, 261107-6) — 배경 한 워커가 차례로, 작업 창 [중단], 결과는 사진마다 보류 저장소."""
        from viewer.workers import run_in_thread
        paths = [str(p) for p in (paths or []) if p and self._is_photo_path(str(p))]
        if not paths:
            return
        if self.__dict__.get("_photo_ocr_batch") is not None:
            self.status.showMessage(tr("여러 사진을 읽는 중입니다 — 끝난 뒤 다시 하세요."), 4000)
            return
        w = PhotoOcrBatchWorker(paths, {p: self._photo_rot_for(p) for p in paths})
        self._photo_ocr_batch = w
        self._photo_ocr_seq = self.__dict__.get("_photo_ocr_seq", 0) + 1
        jid = "photo-ocr-%d" % self._photo_ocr_seq
        try:
            self.job_add(jid, tr('사진 OCR ({n}장)').format(n=len(paths)), cancel=w.request_cancel)
        except Exception:
            jid = None
        if jid:
            w.progress.connect(lambda i, n, p, j=jid: self.job_progress(j, "%d / %d  %s" % (i, n, Path(p).name)))
        w.one.connect(self._photo_ocr_one)
        w.done.connect(lambda ok, bad, stopped, j=jid: self._photo_ocr_many_done(j, ok, bad, stopped))
        try:
            self._vm_text()
        except Exception:
            pass
        self.status.showMessage(tr("사진 {n}장을 읽는 중…").format(n=len(paths)), 4000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_ocr_one(self, path: str, n: int):
        """한 장 끝 — 지금 본문 사진이면 낱말·텍스트 창을 다시(메인은 이것뿐)."""
        cur = self.main_view.current_file() if self.main_view else None
        if n >= 0 and cur and os.path.normcase(str(cur)) == os.path.normcase(path):
            self._photo_words_changed()
            self._reload_text_panel()

    def _photo_ocr_many_done(self, jid, ok: int, bad: int, stopped: bool):
        self._photo_ocr_batch = None
        if jid:
            try:
                self.job_done(jid)
            except Exception:
                pass
        try:
            self._pending_refresh()                      # 상태 줄 '💾 저장 안 한 OCR'
        except Exception:
            pass
        if stopped:
            msg = tr("사진 OCR 을 멈췄습니다 — {n}장을 읽었습니다.").format(n=ok)
        elif bad:
            msg = tr("사진 {n}장을 읽고 {m}장은 읽지 못했습니다.").format(n=ok, m=bad)
        else:
            msg = tr("사진 {n}장을 읽었습니다 — 남기려면 '저장 안 한 OCR' 을 저장하세요.").format(n=ok)
        self.status.showMessage(msg, 8000)

    def _photo_ocr_done(self, path: str, n: int):
        cur = self.main_view.current_file() if self.main_view else None
        if cur and os.path.normcase(str(cur)) == os.path.normcase(path):
            self._photo_words_changed()                  # 본문 위 글자 고르기(4.39)도 새 낱말로
            self._reload_text_panel()
        try:
            self._pending_refresh()                      # 상태 줄 '💾 저장 안 한 OCR'
        except Exception:
            pass
        self.status.showMessage(tr("사진 글자 {n}개를 읽었습니다 — 남기려면 '저장 안 한 OCR' 을 저장하세요.").format(n=n), 6000)

    def _photo_ocr_words(self, path):
        """보류 ▶ 저장본에서 이 사진의 OCR 낱말 — 사진이 바뀌었으면(크기·수정 시각, 단어학습 SOT §14.22) 없는 것으로."""
        from viewer.study import ocr as _ocr
        from viewer.study.study_store import file_key_for
        key = file_key_for(str(path))

        def read(st):
            row = st.conn.execute("SELECT engine FROM ocr_page WHERE file_key=? AND page=0", (key,)).fetchone()
            if not row:
                return []
            try:
                if not str(row["engine"] or "").endswith(_ocr.photo_sig(path)):
                    return []
            except OSError:
                return []
            return st.get_page_words(key, 0)
        return self._study_read(read, [])

    def _photo_words_changed(self):
        """본문이 기억한 쪽 낱말을 버린다 — OCR 이 새로 들어왔거나 보기 회전이 바뀌었을 때(4.39)."""
        for mv in getattr(self, "_mv", None) or [self.main_view]:
            try:
                mv._view_src_cache = None
                mv._page_words = []
                mv.clear_text_selection()
            except Exception:
                pass

    def _photo_view_words(self, path):
        """본문 위 글자 고르기·복사(4.39, F9)와 검색 강조가 쓰는 사진 OCR 낱말 — 지금 보기 회전 판, `(낱말, 72)`.
        낡은 OCR(덮어쓴 사진)·읽지 않은 사진은 빈 목록(OCR 은 누를 때만 — D15)."""
        words = self._photo_ocr_words(path)
        if not words:
            return ([], 0)
        return (self._photo_words_shown(path, words)[0], 72)

    def _photo_words_shown(self, path, words) -> tuple:
        """회전 0 판 OCR 낱말 → 지금 보이는 쪽(보기 회전 뒤·자른 뒤, 4.39·4.40)의 낱말과 그 쪽 크기(pt)."""
        from viewer.study import ocr as _ocr
        from viewer.photo_io import oriented_size
        w0, h0 = oriented_size(path)
        rot = self._photo_rot_for(path)
        vw = _ocr.photo_words_view(words, rot, w0, h0)
        size = (h0, w0) if rot in (90, 270) else (w0, h0)
        boxv = self._photo_view_box(path)
        if boxv:
            from viewer import photo_crop
            vw = photo_crop.words_view(vw, boxv, *size)
            size = photo_crop.size_after(size[0], size[1], boxv)
        return vw, size

    def _photo_text_reload(self, cur):
        """텍스트 창 — 사진은 우리 OCR 낱말만으로 줄을 만든다(표 인식 없음). 낱말은 지금 보기 회전으로 돌려 쓴다."""
        tp = getattr(self, "text_panel", None)
        if tp is None:
            return
        try:
            tp.btn_apply.setEnabled(False)               # [PDF 에 반영] — 사진에는 없다(4.34·G1)
        except Exception:
            pass
        words = self._photo_ocr_words(cur)
        if not words:
            tp.set_page(str(cur), 0, [], tr("이 사진의 글자를 아직 읽지 않았습니다 — [OCR 로 읽기] 를 누르세요."))
            return
        from viewer.study import ocr as _ocr
        from viewer.photo_io import oriented_size
        from viewer.workers import TextPageWorker, run_in_thread
        vw, size = self._photo_words_shown(cur, words)
        prev = getattr(self, "_text_worker", None)
        if prev is not None:
            try:
                prev.request_cancel()
            except Exception:
                pass
        self._text_token = getattr(self, "_text_token", 0) + 1
        tok = self._text_token
        tp.set_busy(tr("사진 글자 줄을 만드는 중…"))
        w = TextPageWorker(cur, 0, tables="omit", token=tok, ocr_words=vw, ocr_dpi=72,
                           join_lines=tp.join_lines(), page_size=size)
        self._text_worker = w
        w.done.connect(lambda pg, rows, t, _w=w: self._on_text_rows(cur, pg, rows, t, "", getattr(_w, "noise", 0)))
        w.error.connect(lambda msg, t: tp.set_busy(tr('읽지 못했습니다: {msg}').format(msg=msg)) if t == self._text_token else None)
        w.finished.connect(lambda: setattr(self, "_text_worker", None))
        run_in_thread(w, self._thread_keep)

    def _photo_ocr_committed(self, found: list):
        """OCR 을 확정한 사진들(§4.36) — `found` = [(경로, 확정 글, 형식 또는 None, 키워드)](배경에서 읽어 옴).
        태그는 앱의 태그 저장소 하나로 메인에서(자동 칸만 — 사용자 태그·고친 키워드는 그대로), 그 다음 사진 정보 색인 그 행."""
        if not found:
            return
        bt = self.bookmark_tree
        tags = getattr(bt, "_tags", None)
        from viewer import dbutil, photo_index
        try:
            con = photo_index.connect(busy_ms=dbutil.BUSY_MS_UI)
        except Exception:
            con = None
        try:
            for path, text, fmt, kws in found:
                if tags is not None:
                    try:
                        tags.set_auto_part(path, "ocr", [fmt] if fmt else [], src="photo_ocr")   # 261105-6: 자기 부분만 — 머리·종류 태그는 그대로(태그 SOT §5.7)
                        if kws and not tags.kw_edited(path):
                            tags.set_keywords(path, kws, src="photo_ocr")
                    except Exception:
                        pass
                if con is not None:
                    try:
                        photo_index.set_ocr(con, path, text, tags.get(path) if tags is not None else None)
                    except Exception:
                        pass
            if con is not None:
                con.commit()
        finally:
            if con is not None:
                con.close()

    def _photo_text_blocked(self):
        self.status.showMessage(tr("사진에는 글자층이 없어 PDF 에 반영하지 않습니다 — 글은 텍스트 창에서 복사하거나 [OCR 로 읽기] 로 다시 읽으세요."), 6000)

    def _photo_copy_out(self, paths):
        """'PC 로 복사' — 캐시의 장치 사진을 고른 폴더로(배경 진행 창·취소, 같은 이름이면 번호)."""
        from PyQt6.QtWidgets import QFileDialog
        from viewer import photo_device
        paths = [p for p in paths if photo_device.is_cached(p)]
        if not paths:
            return []
        dest = QFileDialog.getExistingDirectory(self, tr("PC 로 복사할 폴더"), str(getattr(self, "_folder", "") or ""))
        if not dest:
            return []
        out = []
        from viewer.twoup import MergeCancelled

        def job(progress, _paths=list(paths)):
            def prog(i, n):
                if progress is not None and progress(i, n, tr("PC 로 복사하는 중")) is False:
                    raise MergeCancelled()
            out.extend(photo_device.copy_out(_paths, dest, progress=prog))
        res = self._run_merge_job(job, tr("PC 로 복사"))
        if res.get("err"):
            self.status.showMessage(res["err"], 6000)
        else:
            self.status.showMessage(tr("사진 {n}장을 복사했습니다: {dest}").format(n=len(out), dest=dest), 6000)
        return out

    def _photo_gate_actions(self):
        """사진 모드면 `PHOTO_OFF_CMDS` 를 끈다 — 끈 것만 기억했다가 PDF 모드에서 되살리고, 키·언어 판정
        (`_gate_api_dependent_ui`)을 다시 덧입힌다(그 함수 끝에서 이 함수를 부른다 — 한 길)."""
        acts = [(c, self._cmds.get(c)) for c in PHOTO_OFF_CMDS] + [(n, getattr(self, n, None)) for n in PHOTO_OFF_ATTRS]
        off = self.__dict__.setdefault("_photo_disabled", set())
        hidden = self.__dict__.setdefault("_photo_hidden", set())
        if self._photo_mode:
            # 끄기를 숨기기보다 **먼저**, 그리고 숨은 것도 늘 다시 끈다(261106-4) — Qt 는 숨은 액션을 isEnabled()=False 로
            #   보고하지만 그 사이 권한 적용 등이 setEnabled(True) 를 하면 그 값을 기억해, 다시 보일 때 켜진 채로 나온다
            for k, a in acts:
                if a is None:
                    continue
                if a.isEnabled():
                    off.add(k)
                if k in off:
                    a.setEnabled(False)
        for c in PHOTO_HIDE_CMDS:                        # 숨김(261106-1·-4) — 숨긴 것만 기억했다가 PDF 모드에서 되살린다
            a = self._cmds.get(c)
            if a is None:
                continue
            if self._photo_mode and a.isVisible():
                a.setVisible(False)
                hidden.add(c)
            elif not self._photo_mode and c in hidden:
                a.setVisible(True)
                hidden.discard(c)
        for mv in getattr(self, "_mv", []) or []:       # 편집 모드 툴바의 전자서명 단추(크롭 오른쪽)
            if hasattr(mv, "set_sign_allowed"):
                mv.set_sign_allowed(not self._photo_mode)
        if self._photo_mode:
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
        except Exception:
            pass
        zipped = self.__dict__.get("_photo_zip_paths")
        if zipped and str(path) not in zipped:
            self._photo_zip_paths = None                 # zip 밖으로 나갔다 — 썸네일 줄은 종전대로(4.32)
            self._photo_dev_open = None
            zipped = None
        found = self.__dict__.get("_photo_search_paths")
        if found and str(path) not in found:
            self._photo_search_paths = None             # 검색 결과·zip 밖 사진을 열었다 — 원천은 다시 책갈피창(4.24)
        try:
            grp = self.__dict__.get("_photo_group")
            if zipped and grp:
                self.page_thumbs.set_title(grp[0], grp[1])    # 261104-8(4.32): zip 안 사진이면 제목은 zip 이름(장치 사진이면 '장치 › 폴더', 4.33)
            else:
                self.page_thumbs.set_title(Path(str(path)).name)
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
        self._photo_sync_tree(path)                   # 261104-4(4.26, 사용자 지시): 책갈피창도 그 사진 줄을
        self._photo_anim_check(path)                  # 움직이는 GIF·WebP 면 ▶(4.31, 261104-7 B6)
        try:
            self._touch_recent_files([path])          # 사진 모드면 사진의 최근 파일(4.7)
        except Exception:
            pass

    def _photo_strip_source(self) -> list:
        """썸네일 줄에 넣을 사진(D3) — 책갈피창에서 여럿 골랐으면 고른 것(트리 차례), 하나면 폴더 전체.
        zip 을 보는 동안은 그 zip 안 사진만(4.32, 261104-8 사용자 지시) — 폴더의 다른 사진·고름을 섞지 않는다."""
        zipped = self.__dict__.get("_photo_zip_paths")
        if zipped:
            return list(zipped)
        bt = self.bookmark_tree
        sel = []
        for it in bt._iter_file_nodes():
            if it.isSelected():
                p = it.data(0, bt.DATA_FILE)
                if p and self._is_photo_path(p):
                    sel.append(str(p))
        if len(sel) > 1:
            return sel
        found = self.__dict__.get("_photo_search_paths")
        if found:
            return list(found)                       # 사진 검색 결과(4.24) — 넘김·썸네일 줄이 결과 안에서
        return self._photo_tree_list()

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
            if direction > 0 and self._photo_device_next(open_first=True):
                return                                   # 휴대 장치 — 다음 폴더를 이어 받아 그 첫 장(4.33)
            self.status.showMessage(tr("마지막 사진입니다.") if direction > 0 else tr("첫 사진입니다."), 2000)
            return
        self._on_bookmark_activated(lst[j], 0)
        self._photo_pair_step(direction)                # 2분할 함께 움직이기면 다른 창도 한 장(4.28)

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

    def _photo_deco_in(self, path, items, images: bool = False):
        """저장된 꾸밈(회전 0 판·자르지 않은 쪽 비율) → 지금 보이는 쪽 비율 — 돌리고(4.19) 자른다(4.40). 사진이 아니면 그대로."""
        fr = self._photo_deco_frame(path)
        boxv = self._photo_view_box(path) if path and self._is_photo_path(path) else None
        if fr:
            from viewer import photo_deco
            items = (photo_deco.rotate_images if images else photo_deco.rotate_strokes)(items, *fr)
        if boxv:
            from viewer import photo_crop
            items = (photo_crop.map_images if images else photo_crop.map_strokes)(items, boxv)
        return items

    def _photo_deco_out(self, path, items, images: bool = False):
        """보이는 쪽 비율의 꾸밈 → 저장할 회전 0 판·자르지 않은 쪽 비율(`_photo_deco_in` 의 역)."""
        fr = self._photo_deco_frame(path)
        boxv = self._photo_view_box(path) if path and self._is_photo_path(path) else None
        if boxv:
            from viewer import photo_crop
            items = (photo_crop.map_images if images else photo_crop.map_strokes)(items, boxv, back=True)
        if fr:
            from viewer import photo_deco
            rot, w0, h0 = fr
            items = (photo_deco.rotate_images if images else photo_deco.rotate_strokes)(
                items, photo_deco.inverse(rot), *((h0, w0) if rot in (90, 270) else (w0, h0)))
        return items

    # ── 보기 크롭 (4.40, 261105-4 — 원본 그대로, 자른 모양만 사이드카 `photo_crop`) ─────────────
    def _photo_crop_for(self, path):
        """사진의 보기 크롭 — 회전 0 판 쪽 비율 상자, 없으면 None."""
        if not path or not self._is_photo_path(path):
            return None
        st = self._ensure_page_meta_store()
        try:
            return st.photo_crop(path) if st else None
        except Exception:
            return None

    def _photo_view_box(self, path):
        """보이는 방향(보기 회전 뒤)의 크롭 상자, 없으면 None."""
        box0 = self._photo_crop_for(path)
        if not box0:
            return None
        from viewer.photo_crop import to_view
        return to_view(box0, self._photo_rot_for(path))

    def _photo_crop_dialog(self, path=None):
        """크롭 창(4.40) — **창을 먼저** 띄우고 미리보기 그림은 배경에서 풀어 들어오면 넣는다(261106-14 사용자 지시 '크롭을 누른 후
        꽤 많이 있다 열린다' — 종전에는 넘김 목록을 사진마다 디스크를 타며 거르고(7천 장 폴더에서 메인 16초) 그림까지 다 푼 뒤에 열었다)."""
        now = self.main_view.current_file() if self.main_view else None
        cur = str(path) if path else now
        if not cur or not self._is_photo_path(cur):
            return
        if self._photo_any_cached([cur]):
            self._photo_ro_notice()
            return
        is_now = bool(now) and str(Path(cur)) == str(Path(now))
        from viewer.photo_io import oriented_size
        if (is_now and self._photo_is_broken()) or not oriented_size(cur)[0]:
            return                                       # 열 수 없는 파일은 자르지 않는다(4.18)
        st = self._ensure_page_meta_store()
        if st is None or st._key(cur) is None:
            self.status.showMessage(tr("폴더를 열어 고른 사진만 자를 수 있습니다."), 4000)
            return
        if self.__dict__.get("_photo_crop_busy"):
            return
        self._photo_crop_paths = self._photo_crop_range(cur)
        self._photo_crop_busy = True
        try:
            self._photo_crop_load(cur)                   # 그림은 배경에서 — 창은 바로
            self._photo_crop_run(cur)
        finally:
            self._photo_crop_busy = False

    def _photo_crop_range(self, cur: str) -> list:
        """크롭 창에서 ❮ ❯ 로 넘길 사진(4.40, 261106-3) — 썸네일 줄에서 고른 사진이 여럿이고 그 안이면 고른 것만,
        아니면 넘김 차례(`_photo_list` — 썸네일 줄, 없으면 책갈피창). 자를 수 없는 사진(zip·휴대 장치·폴더 밖·열 수 없음)은 뺀다."""
        strip = self._photo_strip_widget(create=False)
        sel = strip.selected_paths() if strip is not None else []
        src = sel if (len(sel) > 1 and any(os.path.normcase(str(p)) == os.path.normcase(cur) for p in sel)) else self._photo_list()
        # 261106-14(응답성 SOT §5): 사진마다 디스크를 타는 판정(`_photo_any_cached` 의 설정 폴더 찾기·`st._key` 의 resolve)을
        #   하지 않는다 — 글자열만으로(캐시 뿌리·폴더 앞부분은 한 번만 구한다). 7천 장 폴더에서 종전 16초 → 수십 ms.
        from viewer import photo_device, photo_zip
        from viewer.image_page import PHOTO_EXTS
        st = self._ensure_page_meta_store()
        base = getattr(st, "base", None) if st is not None else None
        if base is None:
            return [cur]
        norm = os.path.normcase
        base_n = norm(os.path.abspath(str(base))).rstrip("\\/") + os.sep
        roots = tuple(norm(os.path.abspath(str(r))).rstrip("\\/") + os.sep for r in (photo_zip.cache_root(), photo_device.cache_root()))
        out = []
        for p in src or []:
            p = str(p)
            if os.path.splitext(p)[1].lower() not in PHOTO_EXTS:
                continue
            pn = norm(os.path.abspath(p))
            if not pn.startswith(base_n) or pn.startswith(roots):
                continue
            out.append(p)
        if not any(norm(p) == norm(cur) for p in out):
            out = [cur]
        return out

    def _photo_crop_load(self, path: str):
        """크롭 창 미리보기 그림은 배경에서(사진 복사와 같은 워커, 응답성 SOT §5) — 끝나면 창을 열거나 그 사진으로 넘긴다."""
        from viewer.workers import run_in_thread
        w = PhotoCopyWorker(path, self._photo_rot_for(path), max_side=CROP_PREVIEW_SIDE)
        w.done.connect(self._photo_crop_ready)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_crop_start_margins(self, path: str):
        """크롭 창에 처음 걸 여백 — 그 사진의 크롭(보이는 방향 %), 없으면 **최근에 정한 크롭**(261106-3 사용자 지시, 이 실행 동안)."""
        from viewer import photo_crop
        boxv = self._photo_view_box(path)
        if boxv:
            return photo_crop.margins_of(boxv), True
        recent = self.__dict__.get("_photo_crop_recent")
        return (list(recent) if recent else [0.0, 0.0, 0.0, 0.0]), False

    def _photo_crop_ready(self, path: str, img):
        """배경에서 푼 크롭 창 그림 — 처음 사진이든 ❮ ❯ 로 넘긴 사진이든 열려 있는 창에 넣는다(창을 닫았으면 버린다)."""
        dlg = self.__dict__.get("_photo_crop_dlg")
        if dlg is None:
            return
        if img is None or img.isNull():
            dlg.loading_failed()
            self.status.showMessage(tr("사진을 읽지 못했습니다."), 4000)
            return
        paths = self.__dict__.get("_photo_crop_paths") or [path]
        idx = next((i for i, p in enumerate(paths) if os.path.normcase(p) == os.path.normcase(str(path))), dlg.index())
        m, has = self._photo_crop_start_margins(path)
        dlg.show_photo(idx, img, m, has, Path(path).name)

    def _photo_crop_run(self, path: str):
        """크롭 창을 그림 없이 먼저 띄운다(261106-14) — 그림은 `_photo_crop_ready` 가 넣는다. [확인] 이면 크롭·펴기를 적용."""
        from PyQt6.QtWidgets import QDialog
        from viewer.widgets.photo_crop_dialog import PhotoCropDialog
        paths = self.__dict__.get("_photo_crop_paths") or [str(path)]
        if not any(os.path.normcase(p) == os.path.normcase(str(path)) for p in paths):
            paths = self._photo_crop_paths = [str(path)]
        idx = next(i for i, p in enumerate(paths) if os.path.normcase(p) == os.path.normcase(str(path)))
        m, has = self._photo_crop_start_margins(path)
        dlg = PhotoCropDialog(None, m, has_crop=has, title=Path(path).name, parent=self, count=len(paths), index=idx)
        dlg.set_loading()

        def want(i, _d=dlg, _p=paths):
            cm = _d.current_margins()                    # 떠나는 사진의 여백 — 최근 크롭으로 기억(크롭이 없는 사진에 미리 건다)
            if any(v > 0 for v in cm):
                self._photo_crop_recent = list(cm)
            self._photo_crop_load(_p[i])
        dlg.photoRequested.connect(want)
        dlg.accept_hook = lambda _d=dlg, _p=paths: self._photo_warp_accept(_d, _p)   # [확인] 때 저장 묻기(261106-16)
        self._photo_crop_dlg = dlg
        pic = self._photo_prefs()                        # 지난 크롭 창 자리·크기·최대화(261106-8 — 전체 화면은 기억하지 않는다)
        dlg.restore_state(str(pic.get("crop_geom") or ""), bool(pic.get("crop_max")))
        try:
            ok = dlg.exec() == QDialog.DialogCode.Accepted
        finally:
            self._photo_crop_dlg = None
            if dlg.geometry_state:
                pic["crop_geom"], pic["crop_max"] = dlg.geometry_state
        if not ok:
            return                                       # [취소] — 넘기며 고친 것도 남기지 않는다
        todo = {paths[i]: m for i, m in dlg.pending().items() if 0 <= i < len(paths)}
        warps = {paths[i]: pts for i, pts in dlg.pending_warps().items() if 0 <= i < len(paths)}
        dest = dlg.__dict__.get("warp_dest")              # [확인] 때 이미 물었다(`_photo_warp_accept`)
        if warps and dest is None:
            return
        cm = dlg.margins()
        if cm and not dlg.chk_warp.isChecked():
            self._photo_crop_recent = list(cm)
        self._photo_set_crops(todo)
        if warps:
            self._photo_warp(warps, dest)

    # ── 모양 펴기(4.43, 261106-6) ─────────────────────────
    def _photo_warp_backup_label(self) -> str:
        from viewer import photo_backup
        d = photo_backup.custom_dir()
        return d if d else tr("사진 폴더 안 '{name}' 폴더").format(name=photo_backup.BACKUP_DIRNAME)

    def _photo_warp_ask(self, paths: list):
        """펼친 사진을 어디에 — [저장](원본을 대체하고 원본은 백업 폴더로, 261106-15) · [다른 이름으로 저장](사진마다 저장 창) ·
        [다른 폴더에 저장](폴더 고르기, 이름은 '<이름>_펼침'). 여러 장이면 한 번 묻고 모두에. 돌려줌: `("replace", None)`·
        `("names", {원본: 새 경로})`·`("dir", 폴더)`, 어디서든 취소하면 None(쓰는 쪽이 안내 — 261106-16)."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        n = len(paths)
        where = self._photo_warp_backup_label()
        box = QMessageBox(self)
        box.setWindowTitle(tr("펼친 사진 저장"))
        box.setText((tr("펼친 사진을 어떻게 저장할까요?") if n == 1 else tr("펼친 사진 {n}장을 어떻게 저장할까요?").format(n=n))
                    + "\n\n" + tr("[저장] 은 원본 사진을 펼친 사진으로 바꾸고, 원본은 {where}(으)로 옮겨 둡니다. "
                                    "다른 이름·다른 폴더는 원본을 그대로 두고 새 사진을 만듭니다.").format(where=where))
        b_here = box.addButton(tr("저장"), QMessageBox.ButtonRole.AcceptRole)
        b_here.setToolTip(tr("원본을 펼친 사진으로 바꿉니다 — 원본은 {where}(으)로 옮겨집니다.").format(where=where))
        b_names = box.addButton(tr("다른 이름으로 저장"), QMessageBox.ButtonRole.ActionRole)
        b_dir = box.addButton(tr("다른 폴더에 저장"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(b_here)
        box.exec()
        got = box.clickedButton()
        if got is b_here:
            return ("replace", None)
        if got is b_dir:
            start = str(self._photo_prefs().get("warp_dir") or Path(paths[0]).parent)
            d = QFileDialog.getExistingDirectory(self, tr("펼친 사진을 넣을 폴더"), start)
            if not d:
                return None
            self._photo_prefs()["warp_dir"] = str(d)
            return ("dir", str(d))
        if got is b_names:
            out = {}
            for p in paths:
                dst = PhotoWarpWorker.out_name(Path(p))
                got_p, _f = QFileDialog.getSaveFileName(self, tr("펼친 사진 저장"), str(dst),
                                                        tr("그림 (*{ext})").format(ext=dst.suffix))
                if not got_p:
                    return None                          # 중간에 취소 — 아직 아무것도 쓰지 않았다(261106-16)
                got_p = str(Path(got_p).with_suffix(dst.suffix)) if not Path(got_p).suffix else got_p
                if os.path.normcase(os.path.abspath(got_p)) == os.path.normcase(os.path.abspath(p)):
                    self.status.showMessage(tr("원본 자리에는 저장하지 않습니다 — 다른 이름을 고르세요."), 6000)
                    return None
                out[p] = got_p
            return ("names", out) if out else None
        return None

    def _photo_warp_accept(self, dlg, paths: list) -> str:
        """크롭 창 [확인] 을 누른 그 자리에서(창을 닫기 전에) 펼칠 사진의 저장을 묻는다(261106-16 사용자 지시 '다른 이름의 저장을
        누르고 선택을 안 하고 취소 시 그냥 밖으로 빠져나가 — 설정한 내용이 취소된다고 안내'). 돌려줌 "ok"(dlg.warp_dest 에 답)·
        "back"(창으로 돌아가 설정 그대로)·"cancel"(설정을 버리고 닫기)."""
        warps = [paths[i] for i in dlg.pending_warps() if 0 <= i < len(paths)]
        dlg.warp_dest = None
        if not warps:
            return "ok"
        dest = self._photo_warp_ask(warps)
        if dest is not None:
            dlg.warp_dest = dest
            return "ok"
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox(dlg)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("펼친 사진 저장"))
        box.setText(tr("저장 방법·위치를 고르지 않았습니다. 이대로 닫으면 이 창에서 설정한 크롭·모양 펴기가 모두 취소됩니다"
                       " — 아직 아무 사진도 저장하지 않았습니다."))
        b_back = box.addButton(tr("돌아가기"), QMessageBox.ButtonRole.RejectRole)
        b_drop = box.addButton(tr("설정 취소하고 닫기"), QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(b_back)
        box.setEscapeButton(b_back)
        box.exec()
        return "cancel" if box.clickedButton() is b_drop else "back"

    def _photo_warp(self, warps: dict, dest=None):
        """크롭 창 [확인] 의 모양 펴기 — {경로: 점 8개}. 배경 워커 하나가 차례로 편다 — [저장] 이면 원본을 대체(원본은 백업),
        다른 이름·다른 폴더면 새 사진(원본 그대로). `dest` = `_photo_warp_ask` 의 답(없으면 원본 옆 새 사진).
        원본을 바꾸는 사진 작업 잠금 하나(`_photo_orig_lock`, 261106-20)를 함께 쓴다."""
        if not warps:
            return
        if dest and dest[0] == "names":
            warps = {p: v for p, v in warps.items() if p in dest[1]}
            if not warps:
                return
        if not self._photo_orig_lock():
            return
        from viewer.workers import run_in_thread
        self._photo_sync_backup_dir()
        w = PhotoWarpWorker([(p, self._photo_rot_for(p), pts) for p, pts in warps.items()], dest=dest)
        w.done.connect(self._photo_warped)
        self.status.showMessage(tr("펼친 사진 만드는 중…"), 3000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_warped(self, pairs: list, failed: list):
        """펴기 끝 — pairs = [(원본, 새 파일, 백업 경로 또는 "")]. 원본을 대체했으면(261106-15) 그 사진의 보기 상태(크롭·보기 회전·꾸밈 —
        사이드카 기록 통째)를 지운다: 픽셀이 이미 펴지고 세워졌다. OCR 기록·사진 정보 색인·썸네일은 파일 크기·수정 시각으로 저절로 새로 읽힌다."""
        self._photo_orig_busy = False
        replaced = [(s_, o, b_) for s_, o, b_ in pairs if b_]
        if replaced:
            st = self._ensure_page_meta_store()
            for s_, o, _b in replaced:
                if st is not None:
                    st.drop_entry(s_)
                    if os.path.normcase(o) != os.path.normcase(s_):
                        st.drop_entry(o)
            if st is not None:
                try:
                    st.save()
                except Exception:
                    pass
        renamed = [(s_, o) for s_, o, b_ in replaced if os.path.normcase(o) != os.path.normcase(s_)]
        here = [(s_, o) for s_, o, b_ in pairs if not b_
                and os.path.normcase(str(Path(o).parent)) == os.path.normcase(str(Path(s_).parent))]
        for src, out in here:                            # 다른 폴더에 만든 것은 보고 있는 목록에 끼우지 않는다
            try:
                for bt in (self.bookmark_tree, getattr(self, "bookmark_tree_right", None)):
                    if bt is not None and hasattr(bt, "add_or_refresh_file"):
                        bt.add_or_refresh_file(out, after=src)
            except Exception:
                pass
        if renamed:                                      # HEIC → 같은 이름 .jpg — 목록을 다시 훑는다(옛 줄이 남지 않게)
            for bt in (self.bookmark_tree, getattr(self, "bookmark_tree_right", None)):
                r = getattr(bt, "_root_dir", None) if bt is not None else None
                if r:
                    try:
                        bt.load_folder(r)
                    except Exception:
                        pass
        strip = self._photo_strip_widget(create=False)
        mv = self.main_view
        cur = mv.current_file() if mv else None
        for s_, o, _b in replaced:
            if strip is not None:
                try:
                    strip.refresh(str(o))
                except Exception:
                    pass
            if cur and os.path.normcase(str(cur)) == os.path.normcase(s_) and not renamed:
                fit = mv._fit_mode
                if mv.load_document(o, 0):               # 같은 이름 — 바뀐 픽셀로 다시 연다
                    mv._fit_mode = fit
                    self._photo_after_open(Path(o))
                    self._photo_words_changed()
                    mv._render_current()
        where = self._photo_warp_backup_label()
        if replaced and not failed:
            msg = (tr("원본을 펼친 사진으로 바꿨습니다: {name} — 원본은 {where}(으)로 옮겼습니다.").format(name=Path(replaced[0][1]).name, where=where)
                   if len(pairs) == 1 else tr("{n}장을 펼친 사진으로 바꿨습니다 — 원본은 {where}(으)로 옮겼습니다.").format(n=len(pairs), where=where))
            if renamed:
                msg += " " + tr("(HEIC 는 JPEG 로 저장했습니다)")
        elif pairs and not failed:
            msg = (tr("펼친 사진을 새 파일로 저장했습니다: {name} — 원본은 그대로입니다.").format(name=Path(pairs[0][1]).name) if len(pairs) == 1
                   else tr("펼친 사진 {n}장을 새 파일로 저장했습니다 — 원본은 그대로입니다.").format(n=len(pairs)))
        elif pairs:
            msg = tr("펼친 사진 {n}장을 저장하고 {m}장은 만들지 못했습니다.").format(n=len(pairs), m=len(failed))
        else:
            msg = tr("펼친 사진을 만들지 못했습니다 — 원본은 그대로입니다.")
        self.status.showMessage(msg, 8000)
        if len(pairs) == 1 and here and self._photo_mode:   # 새 파일 한 장이면(같은 폴더) 그 사진을 연다
            try:
                self._on_bookmark_activated(here[0][1], 0)
            except Exception:
                pass
        elif len(replaced) == 1 and renamed and self._photo_mode:
            try:
                self._on_bookmark_activated(renamed[0][1], 0)
            except Exception:
                pass

    def _photo_set_crops(self, todo: dict):
        """크롭 창 [확인](261106-3) — {경로: 보이는 방향 여백 % 또는 None} 을 한꺼번에. 사이드카는 한 번만 쓴다."""
        from viewer import photo_crop
        st = self._ensure_page_meta_store()
        if st is None or not todo:
            return
        if len(todo) == 1:
            (p, m), = todo.items()
            box0 = None if m is None else photo_crop.norm(photo_crop.to_rot0(photo_crop.box_of(m), self._photo_rot_for(p)))
            self._photo_set_crop(p, box0)
            return
        changed = []
        for p, m in todo.items():
            box0 = None if m is None else photo_crop.norm(photo_crop.to_rot0(photo_crop.box_of(m), self._photo_rot_for(p)))
            if st.photo_crop(p) == (tuple(box0) if box0 else None):
                continue
            if st.set_photo_crop(p, box0) is not False:
                changed.append(p)
        if not changed:
            return
        st.save_photo_rotation()
        strip = self._photo_strip_widget(create=False)
        if strip is not None:
            for p in changed:
                strip.refresh(str(p))
        mv = self.main_view
        cur = mv.current_file() if mv else None
        if cur and any(os.path.normcase(str(cur)) == os.path.normcase(p) for p in changed):
            fit = mv._fit_mode
            if mv.load_document(cur, 0):
                mv._fit_mode = fit
                self._photo_after_open(Path(cur))
                self._photo_words_changed()
                mv._render_current()
        self.status.showMessage(tr("사진 {n}장의 크롭을 바꿨습니다 — 원본 사진은 그대로입니다.").format(n=len(changed)), 4000)

    def _photo_set_crop(self, path, box0):
        """크롭을 정한다(None 이면 푼다) — 보기 상태라 사진 보기 묶음만 바로 쓰고(4.16 과 같은 길), 썸네일·본문을 다시 그린다."""
        st = self._ensure_page_meta_store()
        if st is None:
            return False
        old = st.photo_crop(path)
        if old == (tuple(box0) if box0 else None):
            return True
        if st.set_photo_crop(path, box0) is False:
            self.status.showMessage(tr("폴더를 열어 고른 사진만 자를 수 있습니다."), 4000)
            return False
        st.save_photo_rotation()
        strip = self._photo_strip_widget(create=False)
        if strip is not None:
            strip.refresh(str(path))
        mv = self.main_view
        cur = mv.current_file() if mv else None
        if cur and str(Path(cur)) == str(Path(path)):
            fit = mv._fit_mode
            if mv.load_document(cur, 0):
                mv._fit_mode = fit
                self._photo_after_open(Path(cur))
                self._photo_words_changed()
                mv._render_current()
        self.status.showMessage(tr("크롭을 풀었습니다 — 원본 사진은 그대로입니다.") if not box0 else
                                tr("자른 모양으로 봅니다 — 원본 사진은 그대로입니다."), 4000)
        return True

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
            self._photo_words_changed()          # 본문 위 글자 고르기 — 돈 판 낱말로(4.39)
            mv._render_current()

    def _photo_is_broken(self) -> bool:
        return bool(getattr(getattr(self.main_view, "_doc", None), "is_broken", False))

    # ── 사진 정보 — 본문 창 왼쪽 끝 정보 한 줄·세부 정보 창 (4.18, 261104-3 → 261107-3 사용자 지시) ─────────
    def _photo_info_button(self, create: bool = True):
        """사진을 보이는 본문 창의 정보 한 줄(`PageNavHost.info_line` — 디자인 SOT §2.8.6.1). PDF 정보와 같은 단추·같은 자리."""
        host = getattr(self, "page_nav_host", None)
        if host is None:
            return None
        if not create and getattr(self, "_photo_info_btn", None) is None:
            return None
        try:
            i = self._mv.index(self.main_view)
        except (AttributeError, ValueError):
            i = 0
        b = host.info_line(i)
        old = getattr(self, "_photo_info_btn", None)
        if old is not None and old is not b:
            old.set_info(None)                          # 사진을 보이던 창이 바뀌었다 — 앞 창 줄은 비운다
        self._photo_info_btn = b
        return b

    def _photo_info_set(self, text):
        b = self._photo_info_button()
        if b is not None:
            b.set_info(text, tr("누르면 사진의 세부 정보를 봅니다."))

    def _photo_info_hide(self):
        b = self._photo_info_button(create=False)
        if b is not None:
            b.set_info(None)
        self._photo_info = None

    def _photo_info_request(self, path):
        """지금 사진의 정보를 배경에서 읽는다(머리만) — 끝나면 본문 창 왼쪽 끝 정보 한 줄에."""
        from viewer.workers import run_in_thread
        self._photo_info_gen = getattr(self, "_photo_info_gen", 0) + 1
        self._photo_info = None
        if self._photo_is_broken():
            from viewer.photo_doc import broken_reason_text
            self._photo_info_set(tr("열 수 없는 파일") + " · " + broken_reason_text(self.main_view._doc.reason))
            return
        self._photo_info_set(self._photo_display_name(path))
        w = PhotoInfoWorker(self._photo_info_gen, str(path))
        w.done.connect(self._photo_info_done)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_info_done(self, gen: int, path: str, info: dict):
        if gen != getattr(self, "_photo_info_gen", 0) or not info:
            return
        self._photo_info = dict(info, path=path)
        self._photo_info_set(photo_info_line(info, self._photo_display_name(path)))

    def _photo_display_name(self, path) -> str:
        """상태 막대에 보일 파일 이름 — zip 안 사진이면 'zip 이름 › 안쪽 사진 이름'(4.18·4.32, 사용자 지시)."""
        name = Path(str(path)).name
        grp = self.__dict__.get("_photo_group")
        if grp and self._photo_any_cached([str(path)]):
            return grp[0] + " › " + name
        return name

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
        if info.get("gps"):                                # 4.29(261104-7 B4, F6·D18): 지도에서 위치 보기 — 매번 확인
            b_map = bb.addButton(tr("지도에서 위치 보기"), QDialogButtonBox.ButtonRole.ActionRole)
            b_map.clicked.connect(lambda _=False, pth=str(info["path"]): self._photo_map_show([pth]))
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

    # ── 사진 세 메뉴 한 함수 — 책갈피창·썸네일 줄·본문(사진 보기 SOT §4.20, 디자인 SOT §2.9.8, 261107-2) ──────
    def _photo_menu_fill(self, menu, paths, where: str, extra=None, *, ok: bool = True, all_paths=None) -> None:
        """사진 메뉴를 PDF 메뉴와 같은 묶음 차례로 채운다 — `where` 는 'tree'·'strip'·'body'.
        `extra` 는 책갈피창만의 줄(새 폴더·이름 변경·삭제·2단·즐겨찾기·해시태그·보기설정 — `BookmarkTree._photo_tree_extra`).
        `ok` = 열 수 있는 사진(본문 깨진 파일·썸네일 머리 못 읽음이면 False — 경로 복사·탐색기만)."""
        from viewer import photo_device
        from viewer.widgets.ctx_menu import add_save_menu
        extra = extra or {}
        mv = self.main_view
        now = mv.current_file() if mv else None
        photos = [str(p) for p in (paths or []) if p and self._is_photo_path(str(p))]
        n = len(photos)
        one = photos[0] if n == 1 else None
        many = n > 1
        cached = self._photo_any_cached(photos)
        ro = cached or not ok
        edit = self.bookmark_tree.is_edit_mode()
        body = where == "body"

        def act(text, cb, enabled=True, tip=None):
            a = menu.addAction(text)
            a.setEnabled(bool(enabled))
            if tip:
                a.setToolTip(tip)
            if cb is not None:
                a.triggered.connect(lambda _=False, f=cb: QTimer.singleShot(0, f))
            return a
        each = lambda f: (lambda ps=list(photos): [f(p) for p in ps])     # noqa: E731 — 여러 장이면 사진마다
        # 인쇄 — 맨 위(261105-12·-16) · 여러 장이면 PDF 만들기도 한 번에
        menu.group("print")
        if photos:
            act(self._kt(tr("인쇄"), "print") if body else (tr('인쇄 ({n}장)').format(n=n) if many else tr("인쇄")),
                lambda ps=list(photos): self._photo_print(paths=ps), many or ok, tr("인쇄 창을 엽니다."))
        if many:
            act(tr('고른 사진 {n}장으로 PDF 만들기').format(n=n), lambda ps=list(photos): self._photo_action("to_pdf", ps))
        # 복사
        menu.group("copy")
        if photos:
            act(tr("사진 복사"), lambda p=photos[0]: self._photo_action("copy_image", [p]), bool(one) and ok,
                None if one else tr("한 장을 고르면 복사합니다."))
        # 261107-16(사용자 지시): '경로 복사' 줄은 두지 않는다 — 키 Ctrl+Shift+C(key_actions)로만
        if body and one:
            act(tr("텍스트 복사"), self._photo_copy_text, ok, tr("OCR 로 읽은 글에서 고른 블럭(없으면 사진 전체)의 글을 복사합니다."))
            act(tr("블럭설정 후 텍스트 복사"), self._photo_arm_text, ok)
            if edit:
                self._ctx_paste_items(menu)                       # 꾸밈으로 붙이기(마스터 §4.7.20 과 같은 줄)
        # 모양 — 회전·크롭·원본으로 되돌리기
        if photos:
            menu.group("shape")
            rot_tip = None if not ro else tr("읽기 전용 사진은 돌릴 수 없습니다.")
            act(self._kt(tr("왼쪽 90° 회전"), "rotate_left") if body else tr("왼쪽 90° 회전"),
                each(lambda p: self._photo_rotate(-90, path=p)), not ro, rot_tip)
            act(self._kt(tr("오른쪽 90° 회전"), "rotate_right") if body else tr("오른쪽 90° 회전"),
                each(lambda p: self._photo_rotate(+90, path=p)), not ro, rot_tip)
            act(tr("180° 회전"), each(lambda p: self._photo_rotate(180, path=p)), not ro, rot_tip)
            act(tr("원래 방향"), each(lambda p: self._photo_rotate(absolute=0, path=p)),
                not ro and any(self._photo_rot_for(p) for p in photos))
            act(tr("크롭"), lambda p=photos[0]: self._photo_crop_dialog(p), bool(one) and not ro,
                None if one else tr("한 장을 고르면 자릅니다."))
            act(tr("크롭 해제"), each(lambda p: self._photo_set_crop(p, None)),
                not ro and any(self._photo_crop_for(p) for p in photos))
            a = self._photo_restore_action(menu, photos)          # §4.43(261106-18) — 백업이 있을 때만
            if a is not None:
                a.triggered.connect(lambda _=False, ps=list(photos): QTimer.singleShot(0, lambda: self._photo_restore(ps)))
        # 파일
        menu.group("file")
        first = (photos or [str(p) for p in (paths or []) if p] or [""])[0]
        if first:
            act(tr("파일 탐색기 열기"), lambda p=first: self._photo_action("reveal", [p]), not cached)
        if extra.get("new_folder"):
            act(tr("새 폴더 만들기"), extra["new_folder"])
        self._photo_xfer_menu(menu, photos)                       # 4.41 — 폴더로 복사·이동
        if photos:
            ren = extra.get("rename") or (lambda p=photos[0]: self._photo_rename(p))
            act(self._kt(tr("이름 변경"), "rename_item") if where == "tree" else tr("이름 변경"), ren,
                bool(one) and not cached, None if one else tr("한 장을 고르면 이름을 바꿉니다."))
        a = self._zip_pick_action(menu, photos)                   # §4.24.1(261106-5) — zip 안 사진 풀기
        if a is not None:
            a.triggered.connect(lambda _=False, ps=list(photos): QTimer.singleShot(0, lambda: self._zip_unpack_cached(ps)))
        if any(photo_device.is_cached(p) for p in photos):
            act(tr('PC 로 복사 ({n}장)').format(n=n) if many else tr("PC 로 복사"),
                lambda ps=list(photos): self._photo_copy_out(ps))  # 4.33 — 휴대 장치 사진
        if extra.get("delete"):
            a = act(self._kt(tr("삭제"), "Del"), extra["delete"])  # 책갈피창 Del 과 같다
        elif photos:
            a = act(self._kt(tr('삭제 ({n}장)').format(n=n) if many else tr("삭제"), "Del"),
                    lambda ps=list(photos): self._photo_delete(ps), edit and not cached)
            if not edit:
                a.setToolTip(tr("편집 모드에서 지울 수 있습니다."))
        # 저장 ▸ — 글자 = 방향 저장(돌린 JPEG, 지금 사진), 할 수 없으면 하위를 연다
        if photos:
            can_orient = (bool(one) and bool(now) and os.path.normcase(str(now)) == os.path.normcase(one)
                          and not ro and bool(self._photo_rot_for(one)) and photo_io_is_jpeg(one)
                          and not self.__dict__.get("_photo_orig_busy"))
            mk = [{"text": tr("PDF 만들기") + (" " + tr("({n}장)").format(n=n) if many else ""),
                   "cb": lambda ps=list(photos): self._photo_action("to_pdf", ps), "enabled": many or ok}]
            if all_paths and len(all_paths) > 1:
                mk.append({"text": tr('줄의 사진 {n}장 모두로 PDF 만들기').format(n=len(all_paths)),
                           "cb": lambda ps=list(all_paths): self._photo_action("to_pdf", ps)})
            mk.append({"text": tr("변환"), "menu": self._photo_convert_menu(menu, photos), "enabled": not ro,
                       "tip": tr("JPEG·PNG·WebP 로 바꾼 새 파일을 원본 옆에 만듭니다(원본은 그대로).")})   # 261107-5(4.30)
            add_save_menu(
                menu,
                save={"cb": self._photo_save_orientation, "enabled": can_orient,
                      "tip": tr("방향 저장 — 보기에서 돌린 방향을 원본 JPEG 에 씁니다(지금 사진, 돌린 JPEG 일 때).")},
                copies=[{"text": tr("평탄화 사본"), "cb": lambda p=photos[0]: self._photo_action("flatten", [p]),
                         "enabled": bool(one) and not ro,
                         "tip": tr("꾸밈·돌린 방향·자른 모양을 구운 새 그림 파일을 원본 옆에 만듭니다(원본은 그대로).")},
                        {"text": tr("개인정보 지운 사본"), "cb": lambda ps=list(photos): self._photo_action("share_all", ps),
                         "enabled": not ro,
                         "tip": tr("촬영 정보·위치를 모두 지운 사본을 만듭니다(원본은 그대로).")}],
                make=mk)
        # 보기
        menu.group("view")
        if extra.get("split"):
            act(extra["split"][0], extra["split"][1])
        elif getattr(self, "_split_on", False):
            act(tr("옆 창에 열기"), lambda: self._copy_pane_to(self._active_pane, 1 - self._active_pane))
        else:
            act(self._kt(tr("2단 보기"), "toggle_split"), self._view_as_split)
        if photos:
            act(self._kt(tr("발표보기"), "present") if body else tr("발표보기"),
                lambda p=photos[0]: self._photo_open_then(p, self._open_presentation), ok or many)
        if getattr(self, "_split_on", False):
            a = menu.addAction(tr("2분할 함께 움직이기"))         # 4.28(261104-7 B3, §5.1 F3)
            a.setCheckable(True)
            a.setChecked(bool(self.__dict__.get("_photo_pair_on")))
            a.triggered.connect(lambda chk=False: self._photo_pair_set(bool(chk)))
        # 도구 — OCR 로 읽기(맨 앞) · 사진 정보 · 지도 · 일괄 작업 · 해시태그
        if photos:
            menu.group("tool")
            act(tr('OCR 로 읽기 ({n}장)').format(n=n) if many else tr("OCR 로 읽기"),
                (lambda ps=list(photos): self._photo_ocr_many(ps)) if many
                else (lambda p=photos[0]: self._photo_open_then(p, self._photo_ocr_start)), many or ok,
                tr("파일은 바꾸지 않고, 읽은 글을 텍스트 창에 보입니다.") if one
                else tr("고른 사진을 배경에서 차례로 읽습니다 — 작업 창에서 멈출 수 있습니다."))
            act(tr("사진 정보"), lambda p=photos[0]: self._photo_info_for(p), bool(one) and ok)
            gps_ok = True
            if body:
                gps_ok = bool((self.__dict__.get("_photo_info") or {}).get("gps"))
            act(tr('지도에서 위치 보기 ({n}장)').format(n=n) if many else tr("지도에서 위치 보기"),
                lambda ps=list(photos): self._photo_action("map", ps), gps_ok and ok or many,
                None if gps_ok else tr("이 사진에는 위치 정보가 없습니다."))
            act(tr("일괄 작업"), lambda ps=list(photos): self._photo_batch_dialog(ps), not cached)
            tags = extra.get("tags") or ((lambda p=photos[0]: self.bookmark_tree._edit_file_tags(p)) if one and not cached else None)
            act(tr("해시태그 편집"), tags, tags is not None)
        # 끝 — 즐겨찾기 · 보기설정 · (본문 편집) 입력 설정
        menu.group("end")
        act(tr("현재 폴더를 즐겨찾기에 추가"), extra.get("fav_folder") or self._add_current_folder_favorite)
        fav_file = extra.get("fav_file") if where == "tree" else ((lambda p=one: self._add_file_favorite(p)) if one and not cached else None)
        if fav_file is not None:
            act(tr("현재 파일을 즐겨찾기에 추가"), fav_file)
        if where == "tree" and extra.get("label_style"):
            act(tr("보기설정"), extra["label_style"])          # 4.38(261104-13)
        elif where == "strip":
            act(tr("보기설정"), lambda: self._photo_label_dialog("strip"))
        if body and edit:
            act(tr("도형 입력 설정"), lambda: self._open_line_text_settings(tab="line"))
            act(tr("글쓰기 입력 설정"), lambda: self._open_line_text_settings(tab="text"))

    PHOTO_CONVERT_FORMATS = (("jpg", "JPEG", (".jpg", ".jpeg")), ("png", "PNG", (".png",)), ("webp", "WebP", (".webp",)))

    def _photo_convert_menu(self, parent, photos):
        """저장 ▸ '변환 ▸'(4.30, 261107-5) — 형식마다 새 파일(일괄 작업 '형식 바꾸기' 와 같은 함수). 모두 지금 그 형식이면 끈다."""
        from viewer.widgets.ctx_menu import CtxMenu
        from viewer import photo_io as _pio
        from PyQt6.QtCore import QTimer
        cm = CtxMenu(parent)
        for key, label, exts in self.PHOTO_CONVERT_FORMATS:
            # 머리 읽기(HEIC 를 .JPG 이름으로)는 한 장일 때만 — 여러 장을 메인에서 사진마다 읽지 않는다(응답성 SOT §6, 261106-21)
            same = (bool(photos) and all(Path(p).suffix.lower() in exts for p in photos)
                    and not (len(photos) == 1 and _pio.is_heif(photos[0])))
            a = cm.addAction(label)
            a.setEnabled(not same)
            a.setToolTip(tr("이미 이 형식입니다.") if same else tr("{fmt} 로 바꾼 새 파일 — 원본은 그대로").format(fmt=label))
            a.triggered.connect(lambda _=False, k=key, ps=list(photos): QTimer.singleShot(
                0, lambda: self._photo_batch_convert(ps, "format", fmt=k)))
        return cm

    def _photo_open_then(self, path, fn) -> None:
        """그 사진을 본문에 띄운 뒤 `fn`(썸네일·책갈피창 줄이 지금 사진이 아닐 때 — OCR 로 읽기·발표보기)."""
        now = self.main_view.current_file() if self.main_view else None
        if not now or os.path.normcase(str(now)) != os.path.normcase(str(path)):
            self._on_bookmark_activated(str(path), 0)
        QTimer.singleShot(0, fn)

    def _photo_info_for(self, path, _tries: int = 0) -> None:
        """'사진 정보' — 지금 사진이 아니면 먼저 띄우고, 정보(배경 `PhotoInfoWorker`)가 오면 창을 연다(3초까지 기다림)."""
        now = self.main_view.current_file() if self.main_view else None
        if _tries == 0 and (not now or os.path.normcase(str(now)) != os.path.normcase(str(path))):
            self._on_bookmark_activated(str(path), 0)
        info = self.__dict__.get("_photo_info") or {}
        if info and os.path.normcase(str(info.get("path", ""))) == os.path.normcase(str(path)):
            self._photo_info_dialog()
        elif _tries < 30:
            QTimer.singleShot(100, lambda: self._photo_info_for(path, _tries + 1))

    def _photo_rename(self, path) -> None:
        """썸네일·본문 '이름 변경' — 책갈피창의 그 줄 이름 칸을 연다(이름 변경 뒤 길은 마스터 §4.7.14 한 길)."""
        bt = self.bookmark_tree
        node = bt._file_node_for_path(str(path))
        if node is None:
            self.status.showMessage(tr("책갈피창 목록에 없는 사진은 이름을 바꿀 수 없습니다."), 4000)
            return
        bt.tree.setCurrentItem(node)
        bt.tree.scrollToItem(node)
        bt._edit_item(node)

    def _photo_copy_text(self) -> None:
        self._cancel_draw_tools()
        if not self.main_view.copy_selection():
            self.status.showMessage(tr("복사할 글이 없습니다 — 먼저 'OCR 로 읽기' 를 하세요."), 4000)

    def _photo_arm_text(self) -> None:
        self._cancel_draw_tools()
        self.main_view.arm_text_selection()
        self.status.showMessage(tr("블럭 좌상점을 누르고 우하점까지 드래그하면 그 영역 텍스트가 복사됩니다."), 5000)

    def _photo_context_menu(self, global_pos):
        """사진 본문 우클릭 — 사진 세 메뉴 한 함수(4.20). 맞춤(쪽·폭·원래 크기)은 창 아래 맞춤 콤보(4.16, 261105-16)."""
        from viewer.widgets.ctx_menu import CtxMenu
        cur = self.main_view.current_file() if self.main_view else None
        if not cur:
            return
        menu = CtxMenu(self)
        self._photo_menu_fill(menu, [str(cur)], "body", ok=not self._photo_is_broken())
        menu.exec(global_pos)

    def _photo_sync_tree(self, path):
        """본문 사진이 바뀌면(썸네일 줄·넘김·검색·지운 뒤) 책갈피창의 그 줄을 고른다 — 신호 없이(다시 열지 않게).
        책갈피창에서 여러 장을 골라 둔 채 그중 하나면 고름은 그대로 두고 '지금 줄' 만 옮긴다(썸네일 줄 원천 D3 를 지키게).
        zip 에서 꺼낸 사진이면 그 zip 줄을 고른다(4.24)."""
        from PyQt6.QtCore import QItemSelectionModel
        from viewer.pathutil import norm_key
        bt = getattr(self, "bookmark_tree", None)
        if bt is None or not path:
            return
        target = str(path)
        from viewer import photo_device
        if photo_device.is_cached(target):
            self._photo_sync_device_row(target)
            return
        if self._photo_any_cached([target]):
            target = self.__dict__.get("_photo_zip_src") or ""
            if not target:
                return
        key = norm_key(target)
        node = next((it for it in bt._iter_file_nodes() if norm_key(str(it.data(0, bt.DATA_FILE))) == key), None)
        if node is None:
            return
        tree = bt.tree
        tree.blockSignals(True)
        try:
            if node.isSelected() and len(tree.selectedItems()) > 1:
                tree.selectionModel().setCurrentIndex(tree.indexFromItem(node), QItemSelectionModel.SelectionFlag.NoUpdate)
            else:
                par = node.parent()
                while par is not None:
                    par.setExpanded(True)
                    par = par.parent()
                tree.setCurrentItem(node)
            tree.scrollToItem(node)
        finally:
            tree.blockSignals(False)
        bt._pending_nav = None

    def _photo_sync_device_row(self, path: str):
        """트리 보기에서 장치 사진 줄을 고른다(신호 없이 — 다시 열지 않게)."""
        tree = self.bookmark_tree.tree
        want = os.path.normcase(str(path))

        def rows(node):
            for i in range(node.childCount()):
                ch = node.child(i)
                yield ch
                yield from rows(ch)
        for top in self._photo_device_nodes():
            for row in rows(top):
                k = row.data(0, self.DEVICE_ROLE)
                if k and k[3] and os.path.normcase(k[3]) == want:
                    tree.blockSignals(True)
                    try:
                        tree.setCurrentItem(row)
                        tree.scrollToItem(row)
                    finally:
                        tree.blockSignals(False)
                    return

    def _photo_any_cached(self, paths) -> bool:
        """zip 에서 꺼낸 사진·휴대 장치에서 복사한 사진(읽기 전용 — 4.24·4.33)."""
        from viewer import photo_device, photo_zip
        return any(photo_zip.is_cached(p) or photo_device.is_cached(p) for p in paths or [])

    def _photo_ro_notice(self):
        cur = self.main_view.current_file() if self.main_view else None
        from viewer import photo_device
        if cur and photo_device.is_cached(cur):
            self.status.showMessage(tr("휴대 장치 사진은 읽기 전용입니다 — 보기·복사·PDF 만들기·인쇄·PC 로 복사만 됩니다."), 5000)
        else:
            self.status.showMessage(tr("zip 안 사진은 읽기 전용입니다 — 보기·복사·PDF 만들기·인쇄만 됩니다."), 5000)

    def _photo_open_zip(self, zip_path):
        """사진이 든 zip(4.24) — 배경에서 캐시로 꺼내 썸네일 줄에 보이고 첫 장을 연다. 넘김은 zip 안에서."""
        from viewer.workers import run_in_thread
        old = self.__dict__.get("_photo_zipper")
        if old is not None:
            old.request_cancel()
        w = PhotoZipWorker(str(zip_path))
        w.done.connect(self._photo_zip_opened)
        self._photo_zip_src = str(zip_path)            # 꺼낸 사진을 볼 때 책갈피창은 이 zip 줄(4.26)
        self._photo_group = (Path(str(zip_path)).name, "ZIP")    # 제목·상태 막대 이름(4.32)
        self._photo_dev_open = None
        self._photo_device_stop()
        self._photo_zipper = w
        try:                                             # 꺼내는 동안에도 줄은 그 zip 것만(4.32) — 앞 폴더 사진을 지운다
            self._photo_strip_widget().set_paths([])
            self.page_thumbs.set_title(Path(str(zip_path)).name, "ZIP")
        except Exception:
            pass
        self.status.showMessage(tr("zip 여는 중… {name}").format(name=Path(str(zip_path)).name), 3000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_zip_opened(self, zip_path: str, paths: list):
        if self.__dict__.get("_photo_zipper") is not None and self._photo_zipper.zip_path != zip_path:
            return                                       # 그새 다른 zip 을 열었다
        w = self.__dict__.get("_photo_zipper")
        self._photo_zip_names = dict(getattr(w, "names", None) or {})   # 꺼낸 사진 → zip 안 이름('이 사진 풀기', 261106-21)
        self._photo_zipper = None
        if not paths:
            self.status.showMessage(tr("zip 에서 사진을 꺼내지 못했습니다: {name}").format(name=Path(zip_path).name), 5000)
            return
        self._photo_zip_paths = list(paths)               # 썸네일 줄·넘김의 원천 = zip 안 사진(4.32 — 고름·검색보다 먼저)
        self._photo_search_paths = None
        self._on_bookmark_activated(paths[0], 0)
        self._photo_strip_widget().set_paths(paths, current=paths[0])
        self.status.showMessage(tr("{name}: 사진 {n}장(읽기 전용)").format(name=Path(zip_path).name, n=len(paths)), 5000)

    # ── zip 풀기(§4.24.1, 261106-5 사용자 지시) ─────────────────────────
    def _zip_unpack(self, zip_path: str, names=None, how: str = "here"):
        """책갈피창 zip 줄·안 줄 — `here` = zip 옆 zip 이름 새 폴더에 모두, `pick` = 폴더를 골라(names 가 있으면 그것만).
        배경 워커 + 작업 창([중단] 은 파일 하나가 끝난 뒤, 푼 것은 남긴다)."""
        from PyQt6.QtWidgets import QFileDialog
        from viewer import zip_unpack
        zp = str(zip_path)
        if not zp or not os.path.isfile(zp):
            return
        if how == "here":
            dest = str(zip_unpack.target_dir(zp))
            strip = False
        else:
            start = str(self._photo_prefs().get("unzip_dir") or Path(zp).parent)
            dest = QFileDialog.getExistingDirectory(self, tr("풀어 넣을 폴더"), start)
            if not dest:
                return
            self._photo_prefs()["unzip_dir"] = str(dest)
            strip = False
        self._zip_start(zp, dest, names, strip)

    def _zip_start(self, zp: str, dest: str, names=None, strip: bool = False):
        from viewer.workers import run_in_thread
        from viewer.zip_unpack import ZipUnpackWorker
        w = ZipUnpackWorker(zp, dest, names, strip_dirs=strip)
        self._zip_seq = self.__dict__.get("_zip_seq", 0) + 1
        jid = "unzip-%d" % self._zip_seq
        label = tr("zip 풀기: {name}").format(name=Path(zp).name)
        try:
            self.job_add(jid, label, cancel=w.request_cancel)
        except Exception:
            jid = None
        if jid:
            w.progress.connect(lambda i, n, s, j=jid: self.job_progress(j, "%d / %d  %s" % (i, n, Path(s).name)))
        w.done.connect(lambda z, d, wr, sk, st, j=jid: self._zip_unpacked(j, z, d, wr, sk, st))
        self.status.showMessage(tr("zip 푸는 중… {name}").format(name=Path(zp).name), 3000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _zip_unpacked(self, jid, zp: str, dest: str, written: list, skipped: list, stopped: bool):
        if jid:
            try:
                self.job_done(jid)
            except Exception:
                pass
        n, m = len(written), len([s for s in skipped if s != "*"])
        if stopped:
            msg = tr("zip 풀기를 멈췄습니다 — {n}개를 풀었습니다: {folder}").format(n=n, folder=Path(dest).name)
        elif n and not skipped:
            msg = tr("{n}개를 풀었습니다: {folder}").format(n=n, folder=Path(dest).name)
        elif n:
            msg = tr("{n}개를 풀고 {m}개는 풀지 못했습니다(이름·크기 거름): {folder}").format(n=n, m=m, folder=Path(dest).name)
        else:
            msg = tr("zip 을 풀지 못했습니다: {name}").format(name=Path(zp).name)
        self.status.showMessage(msg, 8000)
        root = getattr(self.bookmark_tree, "_root_dir", None)
        if n and root:                                   # 보고 있는 폴더 안에 풀었으면 목록을 다시 훑는다(새 폴더가 보이게)
            try:
                inside = os.path.commonpath([os.path.normcase(os.path.abspath(str(root))),
                                             os.path.normcase(os.path.abspath(dest))]) == os.path.normcase(os.path.abspath(str(root)))
            except ValueError:
                inside = False
            if inside:
                for bt in (self.bookmark_tree, getattr(self, "bookmark_tree_right", None)):
                    r = getattr(bt, "_root_dir", None) if bt is not None else None
                    if r:
                        try:
                            bt.load_folder(r)
                        except Exception:
                            pass

    def _zip_pick_action(self, menu, paths):
        """썸네일 줄·본문 우클릭 — zip 에서 꺼낸 사진이면 '골라서 풀기...'(없으면 None)."""
        from viewer import photo_zip
        cached = [p for p in paths or [] if photo_zip.is_cached(p)]
        zp = self.__dict__.get("_photo_zip_src")
        if not cached or not zp:
            return None
        a = menu.addAction(tr("고른 {n}장 풀기").format(n=len(cached)) if len(cached) > 1 else tr("이 사진 풀기"))
        a.setToolTip(tr("zip 안 사진을 고른 폴더에 풉니다(원본 zip 은 그대로)."))
        return a

    def _zip_unpack_cached(self, paths):
        """zip 에서 꺼낸 사진(썸네일 줄·본문에서 고른 것) → zip 안 이름 → 고른 폴더에 그것만.
        이름은 꺼낼 때 배경에서 만든 짝(`PhotoZipWorker.names`)으로 찾는다 — 메인에서 사진마다 zip 을 열지 않는다(261106-21, 응답성 SOT §6)."""
        from viewer import photo_zip
        zp = self.__dict__.get("_photo_zip_src")
        if not zp:
            return
        known = self.__dict__.get("_photo_zip_names") or {}
        names = []
        for p in paths or []:
            if photo_zip.is_cached(p):
                n = known.get(os.path.normcase(os.path.abspath(str(p))))
                if n:
                    names.append(n)
        if not names:
            self.status.showMessage(tr("풀 사진을 찾지 못했습니다."), 4000)
            return
        from PyQt6.QtWidgets import QFileDialog
        start = str(self._photo_prefs().get("unzip_dir") or Path(zp).parent)
        dest = QFileDialog.getExistingDirectory(self, tr("풀어 넣을 폴더"), start)
        if not dest:
            return
        self._photo_prefs()["unzip_dir"] = str(dest)
        self._zip_start(zp, dest, names, strip=True)

    def _zip_open_member(self, zip_path: str, raw: str):
        """PDF 모드 zip 안 PDF 줄(§4.24.1, 사용자 결정 '펼쳐서 보기') — 그 파일 하나만 배경에서 캐시로 꺼내 본문에(사본)."""
        from viewer.workers import run_in_thread
        from viewer.zip_unpack import ZipCacheWorker
        w = ZipCacheWorker(zip_path, raw)
        w.done.connect(self._zip_member_ready)
        self.status.showMessage(tr("zip 에서 꺼내는 중… {name}").format(name=Path(raw).name), 3000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _zip_member_ready(self, zip_path: str, raw: str, out: str):
        if not out:
            self.status.showMessage(tr("zip 에서 꺼내지 못했습니다: {name}").format(name=Path(raw).name), 5000)
            return
        if self._photo_mode:
            return                                       # 그새 사진 모드로 — 열지 않는다
        from viewer.history import HistoryItem
        self._zip_member_open = out
        self._load_main(HistoryItem(out, 0, "", "zip"))
        self.status.showMessage(tr("zip 안 PDF 를 사본으로 열었습니다 — 고친 것은 zip 에 들어가지 않습니다(풀어서 고치세요)."), 8000)

    # ── 원본을 바꾸는 사진 작업 잠금 하나(§4.43, 261106-20) ─────────────────
    def _photo_orig_free(self) -> bool:
        """원본 사진을 바꾸는 작업(방향 저장·모양 펴기 저장·원본으로 되돌리기)은 **한 번에 하나** — 같은 사진에 겹치면 짝·백업이 엉킨다.
        이미 하나가 돌고 있으면 상태 줄에 알리고 False."""
        if self.__dict__.get("_photo_orig_busy"):
            self.status.showMessage(tr("원본 사진을 바꾸는 작업이 아직 끝나지 않았습니다 — 끝난 뒤 다시 하세요."), 5000)
            return False
        return True

    def _photo_orig_lock(self) -> bool:
        if not self._photo_orig_free():
            return False
        self._photo_orig_busy = True
        return True

    # ── 원본으로 되돌리기(§4.43, 261106-18 사용자 승인 '넣기') ─────────────────
    def _photo_restore_pairs(self, paths) -> list:
        from viewer import photo_backup
        self._photo_sync_backup_dir()
        ps = [str(p) for p in paths or [] if self._is_photo_path(str(p)) and not self._photo_any_cached([str(p)])]
        found = photo_backup.scan(ps)                    # 백업 폴더마다 한 번만 읽는다(261106-21 — 사진마다 폴더를 읽지 않게)
        return [(p, found[p]) for p in ps if p in found]

    def _photo_restore_action(self, menu, paths):
        """사진 우클릭 '원본으로 되돌리기' — 백업 자리에 그 사진의 원본이 있을 때만 보인다(없으면 메뉴에 없음)."""
        pairs = self._photo_restore_pairs(paths)
        if not pairs:
            return None
        a = menu.addAction(tr("원본으로 되돌리기 ({n}장)").format(n=len(pairs)) if len(pairs) > 1 else tr("원본으로 되돌리기"))
        a.setToolTip(tr("모양 펴기로 바꾼 사진을 백업해 둔 원본으로 되돌립니다 — 지금 파일은 휴지통으로 갑니다."))
        return a

    def _photo_restore(self, paths):
        from PyQt6.QtWidgets import QMessageBox
        pairs = self._photo_restore_pairs(paths)
        if not pairs or not self._photo_orig_free():
            return
        n = len(pairs)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("원본으로 되돌리기"))
        box.setText((tr("이 사진을 원본으로 되돌릴까요?") if n == 1 else tr("사진 {n}장을 원본으로 되돌릴까요?").format(n=n))
                    + "\n\n" + tr("지금 파일은 휴지통으로 보내고, 백업해 둔 원본을 제자리로 옮깁니다."))
        b_ok = box.addButton(tr("되돌리기"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(b_ok)
        box.exec()
        if box.clickedButton() is not b_ok:
            return
        if not self._photo_orig_lock():
            return
        from viewer.workers import run_in_thread
        w = PhotoRestoreWorker(pairs)
        w.done.connect(self._photo_restored)
        self.status.showMessage(tr("원본으로 되돌리는 중…"), 3000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_restored(self, pairs: list, failed: list):
        """되돌린 뒤 — 사이드카 기록(크롭·보기 회전·꾸밈)을 지우고 썸네일·본문을 새로(대체 뒤 정리와 같은 길, 261106-15)."""
        self._photo_orig_busy = False
        st = self._ensure_page_meta_store()
        if st is not None and pairs:
            for c, o in pairs:
                st.drop_entry(c)
                if os.path.normcase(o) != os.path.normcase(c):
                    st.drop_entry(o)
            try:
                st.save()
            except Exception:
                pass
        renamed = [(c, o) for c, o in pairs if os.path.normcase(o) != os.path.normcase(c)]
        if renamed:
            for bt in (self.bookmark_tree, getattr(self, "bookmark_tree_right", None)):
                r = getattr(bt, "_root_dir", None) if bt is not None else None
                if r:
                    try:
                        bt.load_folder(r)
                    except Exception:
                        pass
        strip = self._photo_strip_widget(create=False)
        mv = self.main_view
        cur = mv.current_file() if mv else None
        for c, o in pairs:
            if strip is not None:
                try:
                    strip.refresh(str(o))
                except Exception:
                    pass
            if cur and os.path.normcase(str(cur)) == os.path.normcase(c):
                if renamed:
                    try:
                        self._on_bookmark_activated(o, 0)
                    except Exception:
                        pass
                else:
                    fit = mv._fit_mode
                    if mv.load_document(o, 0):
                        mv._fit_mode = fit
                        self._photo_after_open(Path(o))
                        self._photo_words_changed()
                        mv._render_current()
        if pairs and not failed:
            msg = (tr("원본으로 되돌렸습니다: {name} — 바꾼 파일은 휴지통에 있습니다.").format(name=Path(pairs[0][1]).name) if len(pairs) == 1
                   else tr("사진 {n}장을 원본으로 되돌렸습니다 — 바꾼 파일은 휴지통에 있습니다.").format(n=len(pairs)))
        elif pairs:
            msg = tr("사진 {n}장을 되돌리고 {m}장은 되돌리지 못했습니다.").format(n=len(pairs), m=len(failed))
        else:
            msg = tr("원본으로 되돌리지 못했습니다 — 파일은 그대로입니다.")
        self.status.showMessage(msg, 8000)

    def _photo_save_orientation(self):
        """보기 회전을 원본 JPEG 의 방향 태그에(D17, 4.17) — 배경 한 길, 끝나면 `_photo_orient_saved`."""
        cur = self.main_view.current_file() if self.main_view else None
        if cur and self._photo_any_cached([cur]):
            self._photo_ro_notice()
            return
        rot = self._photo_rot_for(cur) if cur else 0
        if not cur or not rot or not self._photo_orig_free():
            return
        if not photo_io_is_jpeg(cur):
            self.status.showMessage(tr("방향 저장은 JPEG 사진만 됩니다 — 이 사진은 보기에서만 돌려 둡니다."), 5000)
            return
        if self._in_edit() and getattr(self, "_edit_dirty", False):
            # 꾸밈 좌표를 함께 옮겨 바로 써야 한다(4.19) — 저장 대기 중인 편집을 같이 내보내지 않게 먼저 저장하게 한다
            self.status.showMessage(tr("저장하지 않은 편집이 있습니다 — 먼저 [저장] 한 뒤 방향을 저장하세요."), 6000)
            return
        if not self._photo_orig_lock():
            return
        from viewer.workers import run_in_thread
        w = PhotoOrientSaveWorker(cur, rot)
        w.done.connect(self._photo_orient_saved)
        self.status.showMessage(tr("방향 저장 중…"), 2000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_orient_saved(self, path: str, ok: bool, why: str):
        """방향 저장이 끝났다(메인) — 성공이면 보기 회전을 지우고 다시 그린다. 실패면 원본 그대로·보기 회전 그대로."""
        self._photo_orig_busy = False
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
            box = st.photo_crop(path)
            if box:                                              # 크롭도 같은 만큼(4.40)
                from viewer.photo_crop import after_orient_save
                st.set_photo_crop(path, after_orient_save(box, rot))
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
        if kind in ("label_style_tree", "label_style_strip"):
            self._photo_label_dialog("tree" if kind == "label_style_tree" else "strip")   # 보기설정(4.38)
            return
        paths = [str(p) for p in (paths or []) if p]
        if kind not in ("copy_path", "reveal"):
            paths = [p for p in paths if self._is_photo_path(p)]     # zip 줄 등 사진 아닌 것은 빼고(4.24)
        if not paths:
            return
        if kind in ("share_gps", "share_all", "flatten", "reveal", "rot_l", "rot_r", "batch", "crop") and self._photo_any_cached(paths):
            self._photo_ro_notice()
            return
        from PyQt6.QtWidgets import QApplication
        if kind == "copy_path":
            QApplication.clipboard().setText("\n".join(paths))
            self.status.showMessage(tr("경로를 복사했습니다."), 2500)
        elif kind == "copy_image":
            from viewer.workers import run_in_thread
            w = PhotoCopyWorker(paths[0], self._photo_rot_for(paths[0]), crop=self._photo_crop_for(paths[0]))
            w.done.connect(self._photo_copied)
            self.status.showMessage(tr("사진 복사 중…"), 2000)
            run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))
        elif kind == "to_pdf":
            self.action_image_to_pdf(initial_paths=paths)      # 이미지 → PDF 창(이미지 PDF SOT) — 고른 사진을 미리 넣는다(4.21: 굽기·새 창)
        elif kind == "batch":
            self._photo_batch_dialog(paths)
        elif kind in ("share_gps", "share_all"):
            self._photo_share(paths, "gps" if kind == "share_gps" else "all")
        elif kind == "print":
            self._photo_print()
        elif kind == "flatten":
            self._photo_flatten(paths[0])
        elif kind == "reveal":
            try:
                self.bookmark_tree._reveal_in_explorer(paths[0])
            except Exception:
                pass
        elif kind == "info":
            self._photo_info_dialog()
        elif kind == "map":
            self._photo_map_show(paths)                  # 4.29(261105-17) — 고른 사진 모두를 한 지도에
        elif kind == "open":
            self._on_bookmark_activated(paths[0], 0)
        elif kind == "copy_out":
            self._photo_copy_out(paths)
        elif kind == "unzip":
            self._zip_unpack_cached(paths)
        elif kind == "restore":
            self._photo_restore(paths)
        elif kind in ("rot_l", "rot_r"):
            self._photo_rotate(-90 if kind == "rot_l" else +90, path=paths[0])
        elif kind == "crop":
            self._photo_crop_dialog(paths[0])

    def _photo_copied(self, path: str, img):
        from PyQt6.QtWidgets import QApplication
        if img is None or img.isNull():
            self.status.showMessage(tr("사진을 복사하지 못했습니다."), 4000)
            return
        QApplication.clipboard().setImage(img)
        self.status.showMessage(tr("사진을 복사했습니다: {name}").format(name=Path(path).name), 3000)

    def _photo_strip_menu(self, path: str, global_pos):
        """썸네일 줄 우클릭(4.20) — 누른 사진(고른 칸 위면 고른 사진 모두)에. 사진 세 메뉴 한 함수, 저장 ▸ 에 '줄의 사진 모두로 PDF'."""
        from viewer.widgets.ctx_menu import CtxMenu
        from viewer.photo_io import oriented_size
        ok = bool(oriented_size(path)[0])
        strip = self._photo_strip_widget(create=False)
        allp = strip.paths() if strip is not None else [path]
        sel = strip.selected_paths() if strip is not None else []
        many = path in sel and len(sel) > 1          # 고른 칸 위를 눌렀으면 고른 사진 모두에(사용자 지시 261104-3)
        targets = sel if many else [path]
        menu = CtxMenu(self)
        self._photo_menu_fill(menu, list(targets), "strip", ok=ok or many, all_paths=list(allp))
        menu.exec(global_pos)

    # ── 사진 → PDF·인쇄·평탄화 (P2 ④, 4.21) ─────────────────────────────
    def _photo_needs_bake(self, path) -> tuple:
        """(보기 회전, 꾸밈이 있는가, 보기 크롭 상자|None) — 사진을 PDF·그림으로 내보낼 때 보이는 그대로가 되도록(4.21·4.40)."""
        rot = self._photo_rot_for(path)
        st = self._ensure_page_meta_store()
        deco = bool(st and (0 in set(st.pages_with_drawings(path)) or 0 in set(st.pages_with_images(path))))
        return rot, deco, self._photo_crop_for(path)

    @staticmethod
    def _photo_pdf_cut(page, box0) -> None:
        """사진 한 쪽(회전 0, 원점 0)을 보기 크롭대로 — CropBox 를 정하고 바깥을 실제로 지운다(4.40, 마스터 §4.7.15 `cut_outside`)."""
        from viewer import page_crop, photo_crop
        r = page.rect
        page_crop.set_crop(page, photo_crop.native_rect(box0, r.width, r.height))
        page_crop.cut_outside(page.parent[page.number])

    def _photo_bake_pdf(self, pdf_path: str, paths: list) -> str:
        """사진을 쪽마다 하나씩 넣은 PDF(`paths` 와 같은 차례)에 꾸밈을 굽고 보기 회전을 `/Rotate` 로 — 보이는 그대로.
        굽기 그림은 메인(마스터 §4.7.16 과 같은 길 — 사진 몇 장은 짧다). 고칠 것이 없으면 받은 경로 그대로."""
        need = [(i, p) + self._photo_needs_bake(p) for i, p in enumerate(paths)]
        need = [t for t in need if t[2] or t[3] or t[4]]
        if not need:
            return pdf_path
        import fitz
        doc = fitz.open(pdf_path)
        try:
            if doc.page_count != len(paths):
                return pdf_path                      # 차례가 어긋났다(읽지 못한 사진) — 굽지 않는다
            for i, p, rot, deco, crop in need:
                if deco:
                    sub = fitz.open()
                    sub.insert_pdf(doc, from_page=i, to_page=i)
                    try:
                        self._bake_decorations(sub, p)
                    except Exception:
                        pass
                    doc.delete_page(i)
                    doc.insert_pdf(sub, start_at=i)
                    sub.close()
                if crop:
                    self._photo_pdf_cut(doc[i], crop)
                if rot:
                    doc[i].set_rotation((doc[i].rotation + rot) % 360)
            out = str(Path(pdf_path).with_name(Path(pdf_path).stem + "_baked.pdf"))
            doc.save(out, garbage=3, deflate=True)
            return out
        finally:
            doc.close()

    def _photo_readable(self, paths) -> list:
        from viewer.photo_io import oriented_size
        return [str(p) for p in paths if oriented_size(p)[0]]

    def _photo_make_pdf(self, paths, name: str = "") -> str | None:
        """사진들 → 보이는 그대로의 임시 PDF(사진 한 장 = 한 쪽, 원본 그대로 넣기·GPS 빼기 G6). 배경 진행창 + 메인 굽기."""
        paths = self._photo_readable(paths)
        if not paths:
            return None
        tmp = self._mk_print_tmpdir("polypdf_photopdf_")
        stem = name or (Path(paths[0]).stem if len(paths) == 1 else tr('사진 {n}장').format(n=len(paths)))
        base = str(tmp / (stem + ".pdf"))

        def _job(progress, _p=list(paths), _b=base):
            self._images_to_pdf(_p, _b, progress, downscale=False)
        res = self._run_merge_job(_job, tr("사진 → PDF"))
        if res.get("cancelled") or res.get("err") or not Path(base).exists():
            return None
        return self._photo_bake_pdf(base, paths)

    def _photo_print(self, preset_scope=None, paths=None):
        """사진 인쇄(4.21) — 책갈피창에서 여러 장 골랐으면 그것, 아니면 지금 사진. 보이는 그대로의 임시 PDF 를 같은 인쇄 창에.
        `paths` 를 주면 그 사진들(261105-12 책갈피창 우클릭 맨 위 '인쇄…' — 위·아래 창 어디서든 누른 사진)."""
        cur = self.main_view.current_file() if self.main_view else None
        if paths:
            paths = [str(p) for p in paths if self._is_photo_path(str(p))]
        else:
            try:
                sel = [p for p in self.bookmark_tree.selected_file_paths() if self._is_photo_path(p)]
            except Exception:
                sel = []
            paths = sel if len(sel) > 1 else ([cur] if cur else [])
        pdf = self._photo_make_pdf(paths)
        if not pdf:
            QMessageBox.information(self, tr("인쇄"), tr("인쇄할 사진이 없습니다."))
            return
        here = 0
        if cur and cur in paths:
            here = self._photo_readable(paths).index(cur) if cur in self._photo_readable(paths) else 0
        self.action_print(preset_scope=preset_scope, photo_pdf=(pdf, here))

    def _photo_flatten(self, path):
        """사진 평탄화(D4, 4.21) — 꾸밈을 굽고 보기 회전까지 적용한 **새 그림 파일**을 원본 옆에. 원본은 그대로."""
        rot, deco, crop = self._photo_needs_bake(path)
        if not rot and not deco and not crop:
            QMessageBox.information(self, tr("평탄화"), tr("이 사진에 구울 꾸밈(선·도형·글·사진)이나 돌린 방향·자른 모양이 없습니다."))
            return
        if self.__dict__.get("_photo_flat_busy"):
            return
        overlay = None
        if deco:
            import fitz
            from viewer.photo_io import oriented_size
            w0, h0 = oriented_size(path)
            ov = fitz.open()
            ov.new_page(width=w0, height=h0)
            try:
                self._bake_decorations(ov, path)          # 빈 쪽에 꾸밈만(메인 — 굽기 그림은 Qt)
                overlay = ov.tobytes()
            finally:
                ov.close()
        from viewer.workers import run_in_thread
        self._photo_flat_busy = True
        w = PhotoFlattenWorker(str(path), rot, overlay, crop)
        w.done.connect(self._photo_flattened)
        self.status.showMessage(tr("평탄화 중…"), 3000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    def _photo_flattened(self, src: str, out: str, why: str):
        self._photo_flat_busy = False
        if not out:
            self.status.showMessage(tr("평탄화하지 못했습니다 — 원본은 그대로입니다."), 6000)
            return
        try:
            for bt in (self.bookmark_tree, getattr(self, "bookmark_tree_right", None)):
                if bt is not None and hasattr(bt, "add_or_refresh_file"):
                    bt.add_or_refresh_file(out, after=src)
        except Exception:
            pass
        self.status.showMessage(tr("평탄화한 새 사진: {name}").format(name=Path(out).name), 6000)

    def _photo_share(self, paths, mode: str = "gps"):
        """공유용 사본(4.22) — 원본은 그대로. 저장 자리를 고른다(261104-18 사용자 지시): **1장**이면 저장 창(위치·이름, 처음 이름은
        '<이름>_공유'), **2장 이상**이면 위치(폴더)를 고르고 그 안에 새 폴더('YYMMDD-사진사본', 고칠 수 있음, 겹치면 '(2)')를 만들어 모두 넣는다.
        창은 마지막으로 고른 위치에서 시작한다(처음이면 사진 폴더). 파일 쓰기는 배경 워커 하나가 차례로."""
        paths = self._photo_readable(paths)
        if not paths or self.__dict__.get("_photo_share_busy"):
            return
        dest = self._photo_share_dest(paths)
        if not dest:
            return                                       # 취소
        from viewer.workers import run_in_thread
        self._photo_share_busy = True
        w = PhotoShareWorker(paths, mode, {p: self._photo_rot_for(p) for p in paths}, dest=dest,
                             crops={p: self._photo_crop_for(p) for p in paths})
        w.done.connect(self._photo_shared)
        self.status.showMessage(tr("공유용 사본 만드는 중…"), 3000)
        run_in_thread(w, self.__dict__.setdefault("_photo_keep", []))

    SHARE_DIR_FMT = "%y%m%d"                         # 여러 장 사본 폴더 이름의 날짜 꼴('261105-사진사본')

    def _photo_share_dest(self, paths):
        """저장 자리를 묻는다 — 1장: `('file', 경로)`, 여러 장: `('dir', 새 폴더 경로)`(만들기는 워커가). 취소면 None."""
        import time as _t
        from PyQt6.QtWidgets import QFileDialog
        pic = self._photo_prefs()
        start = str(pic.get("share_dir") or "")
        if not start or not os.path.isdir(start):
            start = str(Path(paths[0]).parent)
        if len(paths) == 1:
            from viewer import photo_io as _pio
            src = Path(paths[0])
            if _pio.is_jpeg_file(src):                   # 워커가 쓰는 확장자와 같게(JPEG 은 .jpg/.jpeg 그대로, HEIC 는 .jpg)
                ext = src.suffix if src.suffix.lower() in (".jpg", ".jpeg") else ".jpg"
            else:
                ext = ".jpg" if _pio.is_heif(src) else src.suffix
            name = tr('{stem}_공유').format(stem=src.stem) + ext
            got, _f = QFileDialog.getSaveFileName(self, tr("공유용 사본 저장"), str(Path(start) / name),
                                                  tr("그림 (*{ext})").format(ext=ext))
            if not got:
                return None
            got = str(Path(got).with_suffix(ext)) if not Path(got).suffix else got
            if os.path.normcase(os.path.abspath(got)) == os.path.normcase(os.path.abspath(str(src))):
                self.status.showMessage(tr("원본 자리에는 저장하지 않습니다 — 다른 이름을 고르세요."), 6000)
                return None
            pic["share_dir"] = str(Path(got).parent)
            return ("file", got)
        base = QFileDialog.getExistingDirectory(self, tr("공유용 사본 {n}장을 넣을 위치").format(n=len(paths)), start)
        if not base:
            return None
        default = share_dir_name(base, _t.strftime(self.SHARE_DIR_FMT) + "-" + tr("사진사본"))
        pic["share_dir"] = str(base)
        from PyQt6.QtWidgets import QApplication
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        if pic.get("share_auto_name") and not shift:     # '폴더 이름 자동' — 묻지 않고 그 이름 그대로(261104-18 보완 사용자 지시)
            return ("dir", default)
        name, ok, auto = self._photo_share_ask_name(Path(default).name)
        name = (name or "").strip().strip(".")
        if not ok or not name or any(c in name for c in '<>:"/\\|?*'):
            return None
        pic["share_auto_name"] = bool(auto)
        return ("dir", share_dir_name(base, name))

    def _photo_share_ask_name(self, default: str):
        """새 폴더 이름 창 — (이름, 확인?, '폴더 이름 자동' 체크). 체크하면 다음부터 묻지 않는다(Shift 를 누른 채 고르면 다시 묻는다)."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QCheckBox, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("공유용 사본 폴더"))
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(tr("새 폴더 이름")))
        ed = QLineEdit(default)
        ed.selectAll()
        lay.addWidget(ed)
        cb = QCheckBox(tr("폴더 이름 자동 설정 — 다음부터 묻지 않고 저장"))
        cb.setToolTip(tr("다시 물으려면 Shift 를 누른 채 공유용 사본을 고르세요."))
        lay.addWidget(cb)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        ok = dlg.exec() == QDialog.DialogCode.Accepted
        return ed.text(), ok, cb.isChecked()

    def _photo_shared(self, pairs: list, failed: list):
        self._photo_share_busy = False
        for src, out in pairs:
            if os.path.normcase(str(Path(out).parent)) != os.path.normcase(str(Path(src).parent)):
                continue                                 # 다른 폴더에 만든 사본 — 보고 있는 목록에 끼우지 않는다
            try:
                for bt in (self.bookmark_tree, getattr(self, "bookmark_tree_right", None)):
                    if bt is not None and hasattr(bt, "add_or_refresh_file"):
                        bt.add_or_refresh_file(out, after=src)
            except Exception:
                pass
        if pairs and not failed:
            msg = (tr("공유용 사본: {name}").format(name=Path(pairs[0][1]).name) if len(pairs) == 1
                   else tr("공유용 사본 {n}장을 만들었습니다: {folder}").format(n=len(pairs), folder=Path(pairs[0][1]).parent.name))
            if len(pairs) > 1 and self._photo_prefs().get("share_auto_name"):
                msg += " " + tr("(폴더 이름을 물으려면 Shift 를 누른 채 고르세요)")
        elif pairs:
            msg = tr("공유용 사본 {n}장을 만들고 {m}장은 만들지 못했습니다.").format(n=len(pairs), m=len(failed))
        else:
            msg = tr("공유용 사본을 만들지 못했습니다 — 원본은 그대로입니다.")
        self.status.showMessage(msg, 6000)

    def _photo_delete(self, paths):
        """사진 지우기(4.25, 사용자 지시) — 편집 모드에서만. 사진은 쪽이 하나라 **파일을 휴지통으로**.
        책갈피창의 삭제 한 길(`_op_delete` — 확인 창·핸들 놓기·목록에서 빼기)을 그대로 쓰고, 지운 사진이 보던 것이면 다음 사진을 연다."""
        paths = [str(p) for p in (paths or []) if p and self._is_photo_path(p)]
        if not paths:
            return
        bt = self.bookmark_tree
        if not bt.is_edit_mode():
            self.status.showMessage(tr("편집 모드에서 지울 수 있습니다."), 4000)
            return
        if self._photo_any_cached(paths):
            self._photo_ro_notice()
            return
        from viewer.pathutil import norm_key
        want = {norm_key(p) for p in paths}
        nodes = [it for it in bt._iter_file_nodes() if norm_key(str(it.data(0, bt.DATA_FILE))) in want]
        if not nodes:
            return
        lst = self._photo_list()
        cur = self.main_view.current_file() if self.main_view else None
        keys = [norm_key(p) for p in lst]
        idxs = [i for i, k in enumerate(keys) if k in want]
        nxt = None
        if idxs:
            after = [lst[i] for i in range(max(idxs) + 1, len(lst)) if keys[i] not in want]
            before = [lst[i] for i in range(min(idxs) - 1, -1, -1) if keys[i] not in want]
            nxt = (after or before or [None])[0]
        bt.tree.blockSignals(True)
        try:
            bt.tree.clearSelection()
            bt.tree.setCurrentItem(nodes[0])
            for it in nodes:
                it.setSelected(True)
        finally:
            bt.tree.blockSignals(False)
        bt._pending_nav = None
        bt._op_delete(keep_mode=False)
        bt._pending_nav = None                             # 줄을 지우며 바뀐 '지금 줄' 이 예약한 이동은 버린다 — 다음 사진은 아래에서
        gone = [p for p in paths if not Path(p).exists()]
        if not gone:
            return                                         # 취소했거나 지우지 못했다
        gk = {norm_key(p) for p in gone}
        found = self.__dict__.get("_photo_search_paths")
        if found:
            self._photo_search_paths = [p for p in found if norm_key(p) not in gk] or None
        if cur and norm_key(str(cur)) in gk and nxt:
            self._on_bookmark_activated(nxt, 0)          # 보던 사진을 지웠다 — 다음(없으면 앞) 사진
            bt.tree.blockSignals(True)
            try:
                bt._select_top_file(nxt)                 # 책갈피창도 그 줄을(신호 없이 — 다시 열지 않게)
            finally:
                bt.tree.blockSignals(False)
            bt._pending_nav = None
        strip = self._photo_strip_widget(create=False)
        if strip is not None:
            now = self.main_view.current_file() if self.main_view else None
            strip.set_paths(self._photo_strip_source(), current=str(now) if now else None)
        self.status.showMessage(tr("사진 {n}장을 휴지통으로 보냈습니다.").format(n=len(gone)), 4000)

    # ── 폴더로 복사·이동 (4.41, 261105-5 — 파일 통째로, 최근 폴더 + 다른 폴더) ─────────────
    def _photo_xfer_dirs(self) -> list:
        """최근 쓴 대상 폴더(맨 앞이 최근) — 없어진 폴더는 뺀다."""
        lst = [str(d) for d in (self._photo_prefs().get("transfer_dirs") or []) if d]
        return [d for d in lst if os.path.isdir(d)][:PHOTO_XFER_RECENT]

    def _photo_xfer_remember(self, d) -> None:
        pic = self._photo_prefs()
        old = [str(x) for x in (pic.get("transfer_dirs") or []) if os.path.normcase(str(x)) != os.path.normcase(str(d))]
        pic["transfer_dirs"] = ([str(d)] + old)[:PHOTO_XFER_RECENT]

    def _photo_xfer_menu(self, menu, paths) -> None:
        """우클릭 메뉴에 '폴더로 복사 ▸'·'폴더로 이동 ▸' — 최근 폴더 `PHOTO_XFER_RECENT` 개 + '다른 폴더…'. zip·휴대 장치 사진은 복사만."""
        from PyQt6.QtCore import QTimer
        paths = [str(p) for p in (paths or []) if p and self._is_photo_path(p)]
        if not paths:
            return
        cached = self._photo_any_cached(paths)
        dirs = self._photo_xfer_dirs()
        k = len(paths)
        for move in (False, True):
            if k > 1:
                title = (tr('폴더로 이동 ({n}장)') if move else tr('폴더로 복사 ({n}장)')).format(n=k)
            else:
                title = tr("폴더로 이동") if move else tr("폴더로 복사")
            from viewer.widgets.ctx_menu import CtxMenu
            sub = CtxMenu(menu, title)
            menu.addMenu(sub)
            if move and cached:
                sub.setEnabled(False)
                continue
            for d in dirs:
                a = sub.addAction(Path(d).name or d)
                a.setToolTip(d)
                a.triggered.connect(lambda _=False, dd=d, mv=move, ps=list(paths):
                                    QTimer.singleShot(0, lambda: self._photo_transfer(ps, dd, mv)))
            if dirs:
                sub.addSeparator()
            a = sub.addAction(tr("다른 폴더"))
            a.triggered.connect(lambda _=False, mv=move, ps=list(paths):
                                QTimer.singleShot(0, lambda: self._photo_transfer(ps, self._photo_xfer_pick(mv, ps), mv)))

    def _photo_xfer_pick(self, move: bool, paths):
        from PyQt6.QtWidgets import QFileDialog
        dirs = self._photo_xfer_dirs()
        start = dirs[0] if dirs else (str(Path(paths[0]).parent) if paths else "")
        d = QFileDialog.getExistingDirectory(self, tr("옮길 폴더") if move else tr("복사할 폴더"), start)
        return d or None

    def _photo_transfer(self, paths, dst, move: bool) -> list:
        """사진을 폴더로 복사·이동(4.41) — 파일 작업은 배경 진행 창, 이동 뒤는 이름 변경·이동과 같은 한 길(마스터 §4.7.14). [(원본, 새 경로)]."""
        if not dst:
            return []
        from viewer.pathutil import norm_key
        dst = Path(str(dst))
        paths = [str(p) for p in (paths or []) if p and self._is_photo_path(p)]
        if not paths:
            return []
        if not dst.is_dir():
            QMessageBox.warning(self, tr("사진 복사·이동"), tr('대상 폴더가 없습니다: {dst}').format(dst=dst))
            return []
        if move and self._photo_any_cached(paths):
            self._photo_ro_notice()
            return []
        if move:
            dk = norm_key(str(dst))
            paths = [p for p in paths if norm_key(str(Path(p).parent)) != dk]
            if not paths:
                self.status.showMessage(tr("이미 그 폴더에 있는 사진입니다."), 4000)
                return []
            if QMessageBox.question(self, tr("사진 이동"), tr('사진 {n}장을 아래 폴더로 옮길까요?\n\n{dst}').format(n=len(paths), dst=dst)) \
                    != QMessageBox.StandardButton.Yes:
                return []
        mv = self.main_view
        cur = mv.current_file() if mv else None
        want = {norm_key(p) for p in paths}
        cur_in = bool(cur) and norm_key(str(cur)) in want
        if move and cur_in and not self._photo_leave_guard():
            return []
        st = self._ensure_page_meta_store()
        entries = {p: (st.export_entry(p) if st else None) for p in paths}
        root = str(self._folder) if getattr(self, "_folder", None) else ""
        lst = self._photo_list()
        keys = [norm_key(p) for p in lst]
        idxs = [i for i, kk in enumerate(keys) if kk in want]
        nxt = None
        if idxs:
            after = [lst[i] for i in range(max(idxs) + 1, len(lst)) if keys[i] not in want]
            before = [lst[i] for i in range(min(idxs) - 1, -1, -1) if keys[i] not in want]
            nxt = (after or before or [None])[0]
        if move and cur_in:
            self.bookmark_tree.releaseFileRequested.emit(str(cur))     # 본문 핸들을 놓는다(마스터 §4.7.14)
        done = []

        def inside(path_s: str) -> bool:
            if not root:
                return False
            try:
                return norm_key(os.path.commonpath([root, path_s])) == norm_key(root)
            except ValueError:
                return False

        def after_files(_move):
            """옮긴(복사한) 것까지 — 사진 정보 색인 행·연 폴더 밖 대상 사이드카(배경). 도중에 실패해도 된 것은 맞춘다."""
            try:
                from viewer import photo_index
                con = photo_index.connect()
                try:
                    with con:
                        for o, nw in done:
                            photo_index.relocate(con, o, nw, copy=not _move)
                finally:
                    con.close()
            except Exception:
                pass
            from viewer.page_meta import PageMetaStore
            stores = {}
            for o, nw in done:
                ent = entries.get(o)
                if ent and not inside(nw):
                    ds = stores.setdefault(str(Path(nw).parent), PageMetaStore(Path(nw).parent))
                    ds.import_entry(nw, ent)
            for ds in stores.values():
                ds.save()

        def job(progress, _paths=list(paths), _dst=str(dst), _move=move):
            import shutil
            from viewer.pathutil import rename_when_free, unique_path
            from viewer.twoup import MergeCancelled
            try:
                for i, p in enumerate(_paths):
                    if progress is not None and progress(i, len(_paths), Path(p).name) is False:
                        raise MergeCancelled()
                    src = Path(p)
                    tgt = unique_path(Path(_dst) / src.name, first=2)
                    if _move:
                        rename_when_free(src, tgt, move=True)
                    else:
                        tmp = tgt.with_name("~" + tgt.name + ".polypix-tmp")
                        try:
                            shutil.copy2(str(src), str(tmp))
                            os.replace(str(tmp), str(tgt))
                        finally:
                            if tmp.exists():
                                try:
                                    tmp.unlink()
                                except OSError:
                                    pass
                    done.append((p, str(tgt)))
            finally:
                after_files(_move)
            if progress is not None:
                progress(len(_paths), len(_paths), "")

        res = self._run_merge_job(job, tr("사진 이동") if move else tr("사진 복사"))
        if res.get("err"):
            self.status.showMessage(tr('사진을 옮기지 못했습니다: {e}').format(e=res["err"]) if move else
                                    tr('사진을 복사하지 못했습니다: {e}').format(e=res["err"]), 8000)
        if not done:
            if move and cur_in and cur and os.path.exists(str(cur)):
                self._on_bookmark_activated(str(cur), 0)                 # 놓았던 본문을 되살린다
            return []
        self._photo_xfer_remember(dst)
        bt = self.bookmark_tree
        dirty = bool(getattr(self, "_edit_dirty", False))
        if st is not None:                                           # 연 폴더 안 — 복사는 사본 키에, 밖으로 옮긴 것은 옛 키를 지운다
            changed = False
            for o, nw in done:
                ent = entries.get(o)
                if not move and ent and inside(nw):
                    changed = st.import_entry(nw, ent) or changed
                if move and ent and not inside(nw):
                    changed = st.drop_entry(o) or changed
            if changed and not dirty:
                try:
                    st.save()
                except Exception:
                    pass
        pairs = []
        for o, nw in done:
            if move:
                bt._after_move(Path(o), Path(nw))                    # 태그(태그 SOT §6.1)
                pairs.append([o, nw])
            else:
                pairs.append(["", nw])
        try:
            bt._sync_after_transfer(dst)
        except Exception:
            pass
        bt.filesRelocated.emit(pairs)                               # 색인·연 폴더 안 사이드카·본문(마스터 §4.7.14 한 길)
        if not move:
            bt.filesCopied.emit([[o, nw] for o, nw in done])          # 261105-8: 사본에도 OCR 결과(마스터 §4.7.14)
        new_cur = next((nw for o, nw in done if cur and norm_key(o) == norm_key(str(cur))), None)
        if move and new_cur and not inside(new_cur) and nxt:
            self._on_bookmark_activated(nxt, 0)                      # 보던 사진이 연 폴더 밖으로 — 다음(없으면 앞) 사진(§4.25 와 같다)
        k = len(done)
        self.status.showMessage((tr('사진 {n}장을 옮겼습니다: {dst}') if move else tr('사진 {n}장을 복사했습니다: {dst}')).format(n=k, dst=dst), 6000)
        return done

    # ── 슬라이드쇼 (4.12, 261104-7 — 발표 창 재사용) ─────────────────
    def _photo_sibling(self, cur_path: str, direction: int):
        """슬라이드쇼 다음/이전 사진 — 넘김 원천 하나(썸네일 줄 차례, 4.12)."""
        lst = [str(Path(p)) for p in self._photo_list()]
        cs = str(Path(cur_path))
        if cs not in lst:
            return None
        j = lst.index(cs) + (1 if direction > 0 else -1)
        return lst[j] if 0 <= j < len(lst) else None

    def _photo_slide_src(self, path):
        """슬라이드쇼가 그릴 원천 — 꾸밈이 있는 사진만 구운 1쪽 PDF(보기 회전은 `/Rotate`), 아니면 사진 그대로(사진 문서가 돌림까지)."""
        rot, deco, crop = self._photo_needs_bake(path)
        if not deco:
            return str(path)                             # 사진 문서가 돌림·자름까지(4.16·4.40)
        import fitz
        from viewer import photo_io
        try:
            st = os.stat(str(path))
            key = (str(path), st.st_mtime_ns, rot, crop, repr(self._ensure_page_meta_store().get_drawings(path, 0)),
                   len(self._ensure_page_meta_store().get_images(path, 0)))
        except Exception:
            key = (str(path), rot)
        cache = self.__dict__.setdefault("_photo_slide_cache", {})
        hit = cache.get(key)
        if hit and os.path.exists(hit):
            return hit
        w, h = photo_io.oriented_size(path)
        doc = fitz.open()
        try:
            pg = doc.new_page(width=w, height=h)
            photo_io.insert_photo(pg, (0, 0, w, h), str(path))
            self._bake_decorations(doc, str(path))
            if crop:
                self._photo_pdf_cut(doc[0], crop)
            if rot:
                doc[0].set_rotation(rot)
            out = str(self._mk_print_tmpdir("polypdf_slide_") / (Path(str(path)).stem + "_slide.pdf"))
            doc.save(out, deflate=True)
        except Exception:
            return str(path)
        finally:
            doc.close()
        cache[key] = out
        return out

    def _photo_slideshow_started(self):
        pres = getattr(self, "_present", None)
        if pres is None:
            return
        self._photo_preload_neighbors(str(pres._path))
        sec = 0
        try:
            sec = int(self._photo_prefs().get("slide_interval_s", 0) or 0)
        except (TypeError, ValueError):
            sec = 0
        if sec > 0:
            from PyQt6.QtCore import QTimer
            t = QTimer(self)
            t.setInterval(sec * 1000)
            t.timeout.connect(self._photo_slide_tick)
            pres.closed.connect(lambda _pg=None, tt=t: tt.stop())
            t.start()
            self._photo_slide_timer = t

    def _photo_slide_tick(self):
        """자동 넘김 — 마지막 사진이면 멈춘다(처음으로 돌지 않는다, 4.12 '목록 끝')."""
        pres = getattr(self, "_present", None)
        t = self.__dict__.get("_photo_slide_timer")
        if pres is None or not getattr(pres, "_photo", False):
            if t is not None:
                t.stop()
            return
        if self._photo_sibling(str(pres._path), +1) is None:
            if t is not None:
                t.stop()
            return
        pres._next()
        if t is not None and self._photo_sibling(str(pres._path), +1) is None:
            t.stop()                                     # 마지막 사진에 닿았다 — 바로 멈춘다

    def _photo_slide_next_file(self, path):
        """슬라이드쇼가 다른 사진으로 넘어갔다 — 그 앞뒤를 미리 푼다(§6.4)."""
        self._photo_preload_neighbors(str(path))

    def _photo_zoom_actual(self):
        """원래 크기 — 사진 픽셀 하나 = 화면 논리 픽셀 하나(D14 좌표 = pt)."""
        mv = self.main_view
        mv._show_fit(FIT_ACTUAL)                 # 콤보는 '원래 크기'(261105-16) — 배율을 바꾸면 '수동 맞춤'
        mv._fit_mode = mv.FIT_NONE
        mv._zoom = 1.0
        mv._render_current()

    def _photo_fit_combo(self, on: bool):
        """261105-16(4.16, 사용자 결정): 본문 메뉴에서 뺀 '원래 크기' 를 창 아래 맞춤 콤보 끝에 — 사진 모드에서만(PDF 모드면 뺀다)."""
        cmb = getattr(self, "cmb_fit", None)
        if cmb is None:
            return
        i = cmb.findData(FIT_ACTUAL)
        cmb.blockSignals(True)
        try:
            if on and i < 0:
                cmb.addItem(tr("원래 크기"), FIT_ACTUAL)
            elif not on and i >= 0:
                if cmb.currentIndex() == i:
                    cmb.setCurrentIndex(max(0, cmb.findData(self.main_view.shown_fit())))
                cmb.removeItem(i)
        finally:
            cmb.blockSignals(False)
        self._sync_fit_combo()

    def _fit_combo_pick(self, key):
        """창 아래 맞춤 콤보에서 고름 — '원래 크기'(사진 모드) 는 `_photo_zoom_actual`, 그 밖은 본문 `choose_fit`(261031-11)."""
        if key == FIT_ACTUAL:
            if getattr(self, "_photo_mode", False):
                self._photo_zoom_actual()
            return
        self.main_view.choose_fit(key)

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
        self._photo_date_recheck(path)                   # 클라우드에서 받아졌으면 날짜를 촬영일로(4.37, 261105-10)
        try:
            cur = self.main_view.current_file() if self.main_view else None
            if cur and str(cur) == str(path):
                self.main_view._render_current()
        except Exception:
            pass
        pres = getattr(self, "_present", None)
        if pres is not None and hasattr(pres, "refresh_photo"):
            try:
                pres.refresh_photo(path)                 # 슬라이드쇼도 임시 그림 대신(261104-7)
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


PHOTO_XFER_RECENT = 5           # '폴더로 복사·이동' 메뉴의 최근 폴더 수(4.41, 사용자 결정)
CROP_PREVIEW_SIDE = 1600        # 크롭 창 미리보기 그림의 긴 변(4.40)
COPY_MAX_SIDE = 8192            # 사진 복사 — 긴 변 상한(클립보드에 24 MP 그대로는 무겁다, 4.20)


class PhotoCopyWorker(QObject):
    """사진 복사 — 배경에서 풀고(보기 회전까지) 메인은 클립보드에 넣기만(응답성 SOT §4.4 감사표의 한 행)."""
    done = pyqtSignal(str, object)
    finished = pyqtSignal()

    def __init__(self, path: str, rot: int = 0, crop=None, max_side: int = 0):
        super().__init__()
        self.path, self.rot, self.crop = path, int(rot or 0) % 360, crop        # 보기 크롭(4.40) — 자른 뒤 돌린다
        self.max_side = int(max_side or COPY_MAX_SIDE)

    def request_cancel(self):
        pass

    def run(self):
        img = None
        try:
            from viewer.photo_io import read_scaled
            img, _w, _h = read_scaled(self.path, self.max_side, auto_transform=True)
            if self.crop and img is not None and not img.isNull():
                from viewer.photo_crop import crop_qimage
                img = crop_qimage(img, self.crop)
            if self.rot and img is not None and not img.isNull():
                from PyQt6.QtGui import QTransform
                img = img.transformed(QTransform().rotate(self.rot))
        except Exception:
            img = None
        finally:
            self.done.emit(self.path, img)
            self.finished.emit()


class PhotoRestoreWorker(QObject):
    """원본으로 되돌리기(사진 보기 SOT §4.43, 261106-18) — 배경: 사진마다 지금 파일을 휴지통으로 보내고 백업을 원래 이름 자리로
    (`photo_backup.restore_from_backup` — 실패하면 아무것도 바뀌지 않는다)."""
    done = pyqtSignal(list, list)          # [(지금 파일, 되돌린 원본)], [실패한 지금 파일]
    finished = pyqtSignal()

    def __init__(self, items):
        super().__init__()
        self.items = [(str(c), str(b)) for c, b in items]

    def request_cancel(self):
        pass

    def run(self):
        from viewer import pacing, photo_backup
        ok, bad = [], []
        try:
            from send2trash import send2trash
            for cur, bk in self.items:
                try:
                    ok.append((cur, photo_backup.restore_from_backup(cur, bk, send2trash)))
                except Exception:
                    bad.append(cur)
                pacing.pace(self)
        except Exception:
            bad = [c for c, _b in self.items if c not in {x for x, _y in ok}]
        finally:
            self.done.emit(ok, bad)
            self.finished.emit()


WARP_JPEG_QUALITY = 95          # 펼친 사진(모양 펴기 §4.43) JPEG 화질 — 픽셀을 새로 만든다


class PhotoWarpWorker(QObject):
    """모양 펴기(사진 보기 SOT §4.43, 261106-6·-15) — 배경: 사진마다 원본(방향 세움·보기 회전)을 점 8개 테두리로 편다.
    `dest` 가 ("replace", None) 이면(묻는 창 [저장], 261106-15) **원본을 대체**한다: 같은 폴더 임시 파일에 쓰고 열어 확인 →
    원본을 백업 자리로 옮김(`photo_backup`) → 임시 파일을 원본 이름으로. 옮긴 뒤 바꿔 넣기가 실패하면 백업을 되돌린다 — 어느 단계에서
    멈춰도 원본이 사라지지 않는다. 그 밖(다른 이름·다른 폴더)은 새 파일 '<이름>_펼침'(원본 그대로).
    촬영 정보(EXIF)는 남기고 방향 태그만 1 로(픽셀을 세웠다). HEIC 는 JPEG 로(같은 이름 .jpg), PNG·TIFF·BMP·WEBP 는 같은 형식으로."""
    done = pyqtSignal(list, list)          # [(원본, 새 파일, 백업 경로 또는 "")], [실패한 원본]
    finished = pyqtSignal()

    def __init__(self, items, dest=None):
        super().__init__()
        self.items = [(str(p), int(r or 0) % 360, list(pts)) for p, r, pts in items]
        self.dest = dest                     # None·("here", None) 원본 옆 · ("names", {원본: 새 경로}) · ("dir", 폴더)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    @staticmethod
    def out_name(src: Path, folder=None) -> Path:
        """'<이름>_펼침' + 형식 확장자 — `folder`(없으면 원본 폴더) 안에서 겹치지 않게."""
        from viewer import photo_io
        from viewer.pathutil import unique_path
        if photo_io.is_jpeg_file(src) or photo_io.is_heif(src):
            ext = src.suffix if src.suffix.lower() in (".jpg", ".jpeg") else ".jpg"
        else:
            ext = src.suffix if src.suffix.lower() in (".png", ".tif", ".tiff", ".bmp", ".webp") else ".png"
        base = Path(folder) if folder else src.parent
        return unique_path(base / (tr('{stem}_펼침').format(stem=src.stem) + ext))

    @staticmethod
    def replace_name(src: Path) -> Path:
        """원본 대체 때 쓸 이름 — 쓸 수 있는 형식은 그 이름 그대로, HEIC 등은 같은 이름의 .jpg(있으면 겹치지 않게)."""
        from viewer import photo_io
        from viewer.pathutil import unique_path
        if src.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp") and not photo_io.is_heif(src):
            return src
        return unique_path(src.with_suffix(".jpg"))

    def _dst(self, src: Path) -> Path:
        d = self.dest
        if d and d[0] == "replace":
            return self.replace_name(src)
        if d and d[0] == "names" and str(src) in d[1]:
            p = Path(d[1][str(src)])                 # 사용자가 저장 창에서 고른 이름(덮어쓰기는 창이 물었다)
            known = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp")
            return p if p.suffix.lower() in known else p.with_suffix(self.out_name(src).suffix)
        if d and d[0] == "dir":
            Path(d[1]).mkdir(parents=True, exist_ok=True)
            return self.out_name(src, d[1])
        return self.out_name(src)

    def _one(self, src: Path, rot: int, pts) -> str:
        import os
        from PIL import Image, ImageOps
        from viewer import photo_doc, photo_io, photo_warp
        photo_io._prep(src)
        with Image.open(str(src)) as im:
            icc = im.info.get("icc_profile")
            im, exif = photo_io.upright_with_exif(im)    # 세우기 먼저, EXIF(방향 1)는 그 뒤 — 261106-17
            pil = photo_doc._rotate(photo_io.to_srgb(im, icc), rot)
            pil.load()
        out = photo_warp.unwarp(pil, pts)
        dst = self._dst(src)
        replace = bool(self.dest and self.dest[0] == "replace")
        tmp = dst.with_name("~" + dst.name + ".polypix-tmp")
        try:
            ext = dst.suffix.lower()
            if ext in (".jpg", ".jpeg"):
                kw = {"quality": WARP_JPEG_QUALITY}
                if exif:
                    kw["exif"] = exif
                out.convert("RGB").save(str(tmp), "JPEG", **kw)
            else:
                fmt = {".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF", ".bmp": "BMP", ".webp": "WEBP"}[ext]
                out.save(str(tmp), fmt)
            if not replace:
                os.replace(str(tmp), str(dst))
                return str(dst), ""
            from viewer import photo_backup
            with Image.open(str(tmp)) as chk:            # 다 썼는지 열어 확인 — 그 전에는 원본을 건드리지 않는다
                chk.load()
                if chk.size != out.size:
                    raise OSError("verify")
            bk = photo_backup.move_to_backup(src, dst.name)   # 짝 기록까지(261106-20) — 실패하면 예외, 원본 그대로
            try:
                os.replace(str(tmp), str(dst))
            except Exception:
                photo_backup.restore(bk, src)            # 바꿔 넣기 실패 — 원본을 제자리로
                raise
            return str(dst), bk
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def run(self):
        from viewer import pacing
        ok, bad = [], []
        try:
            for p, rot, pts in self.items:
                if self._cancel:
                    break
                try:
                    out, bk = self._one(Path(p), rot, pts)
                    ok.append((p, out, bk))
                except Exception:
                    bad.append(p)
                pacing.pace(self)
        finally:
            self.done.emit(ok, bad)
            self.finished.emit()


FLAT_JPEG_QUALITY = 95          # 평탄화한 JPEG 화질(다시 압축 — 꾸밈을 그림에 굽는다)
SHARE_JPEG_QUALITY = 92         # 공유용 사본 — HEIC 를 JPEG 로 바꿀 때·보기 크롭으로 자른 JPEG 을 다시 압축할 때 화질(자르지 않은 JPEG 은 다시 압축하지 않는다, 사진 보기 SOT 4.22·4.40)


def share_dir_name(base, name: str) -> str:
    """여러 장 공유용 사본 폴더 — `base/name`, 이미 있으면 `name(2)`·`name(3)` …(261104-18 사용자 결정 — 빈칸 없이)."""
    p = Path(str(base)) / name
    k = 2
    while p.exists():
        p = Path(str(base)) / ("%s(%d)" % (name, k))
        k += 1
    return str(p)


class PhotoShareWorker(QObject):
    """공유용 사본(사진 보기 SOT 4.22, F5) — 배경: 사진마다 같은 폴더 임시 파일에 쓰고 새 이름 '<이름>_공유' 로 옮긴다(원본 그대로).
    자르지 않은 JPEG: `gps` 면 GPS 만 비움(D16 `jpeg_strip_gps`), `all` 이면 정보 묶음을 모두 빼고 방향 태그만(`jpeg_strip_meta`) — 둘 다 다시 압축 없음,
    보기 회전은 방향 태그로. 보기 크롭으로 자른 JPEG 은 픽셀을 잘라 다시 압축(`SHARE_JPEG_QUALITY`). 그 밖: HEIC 는 JPEG 로, 나머지는 같은 형식으로 정보 없이 다시 저장(방향·보기 회전은 픽셀로 세움)."""
    done = pyqtSignal(list, list)          # [(원본, 사본)], [실패한 원본]
    finished = pyqtSignal()

    def __init__(self, paths, mode: str, rots: dict, dest=None, crops=None):
        super().__init__()
        self.paths, self.mode, self.rots = list(paths), mode, dict(rots or {})
        self.crops = {k: v for k, v in (crops or {}).items() if v}       # 보기 크롭(4.40) — 자른 사진은 픽셀로 다시 쓴다
        self.dest = dest                                 # ('file', 경로) · ('dir', 새 폴더) · None(원본 옆 — 검사·옛 길)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def _one(self, src: Path) -> str:
        import os
        from viewer import photo_doc, photo_io
        from viewer.pathutil import unique_path
        rot = int(self.rots.get(str(src), 0) or 0) % 360
        crop = self.crops.get(str(src))
        jpeg = photo_io.is_jpeg_file(src)
        exif = None
        if jpeg and not crop:
            data = src.read_bytes()
            o = photo_io.orientation(src)
            new_o = photo_io.compose_orientation(o, rot) if rot else o
            if self.mode == "all":
                new = photo_io.jpeg_strip_meta(data, new_o)
            else:
                new = photo_io.jpeg_strip_gps(data)
                if new_o != o:
                    new = photo_io.jpeg_set_orientation(new, new_o)
            if not new:
                raise ValueError("jpeg")
            ext = src.suffix if src.suffix.lower() in (".jpg", ".jpeg") else ".jpg"
            payload, pil = new, None
        else:
            from PIL import Image, ImageOps
            photo_io._prep(src)
            from viewer.photo_crop import crop_pil
            with Image.open(str(src)) as im:
                icc = im.info.get("icc_profile")
                im, ex_b = photo_io.upright_with_exif(im, drop_gps=True)   # 세우기 먼저(261106-17 — 종전엔 방향을 먼저 1 로 바꿔 세우지 못했다)
                if jpeg and crop and self.mode != "all":    # 자른 JPEG '위치 지움' — 다른 정보는 남기고 GPS 만 뺀다(방향은 픽셀로 세운다)
                    exif = ex_b
                pil = photo_doc._rotate(crop_pil(photo_io.to_srgb(im, icc), crop), rot)
                pil.load()
            heif = photo_io.is_heif(src)
            ext = ".jpg" if heif else (src.suffix if not jpeg or src.suffix.lower() in (".jpg", ".jpeg") else ".jpg")
            payload = None
        name = tr('{stem}_공유').format(stem=src.stem) + ext
        if self.dest and self.dest[0] == "file":
            dst = Path(self.dest[1])                     # 사용자가 저장 창에서 고른 이름(덮어쓰기는 창이 물었다)
        elif self.dest and self.dest[0] == "dir":
            d = Path(self.dest[1])
            d.mkdir(parents=True, exist_ok=True)
            dst = unique_path(d / name)
        else:
            dst = unique_path(src.with_name(name))
        tmp = dst.with_name("~" + dst.name + ".polypix-tmp")
        try:
            if payload is not None:
                tmp.write_bytes(payload)
            elif ext.lower() in (".jpg", ".jpeg"):
                if exif:
                    pil.convert("RGB").save(str(tmp), "JPEG", quality=SHARE_JPEG_QUALITY, exif=exif)   # GPS 를 뺀 정보
                else:
                    pil.convert("RGB").save(str(tmp), "JPEG", quality=SHARE_JPEG_QUALITY)      # EXIF·GPS 를 싣지 않는다
            else:
                fmt = {".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF", ".bmp": "BMP", ".webp": "WEBP", ".gif": "GIF"}.get(ext.lower(), "PNG")
                if fmt == "PNG" and ext.lower() != ".png":
                    dst = unique_path(dst.with_suffix(".png")) if not (self.dest and self.dest[0] == "file") else dst.with_suffix(".png")
                pil.save(str(tmp), fmt)
            os.replace(str(tmp), str(dst))
            return str(dst)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def run(self):
        from viewer import pacing
        ok, bad = [], []
        try:
            for p in self.paths:
                if self._cancel:
                    break
                try:
                    ok.append((p, self._one(Path(p))))
                except Exception:
                    bad.append(p)
                pacing.pace(self)
        finally:
            self.done.emit(ok, bad)
            self.finished.emit()


class PhotoFlattenWorker(QObject):
    """사진 평탄화(4.21) — 배경: 원본(방향 세움) 위에 꾸밈 겹(PDF 한 쪽)을 같은 크기로 그려 얹고, 보기 회전까지 돌려
    같은 폴더 임시 파일에 쓴 뒤 **새 이름**으로 옮긴다(원본은 덮어쓰지 않는다 — os.replace 도 배경). 응답성 SOT §4.4 감사표의 한 행."""
    done = pyqtSignal(str, str, str)          # 원본, 새 파일(실패면 ""), 까닭
    finished = pyqtSignal()

    def __init__(self, path: str, rot: int, overlay: bytes | None, crop=None):
        super().__init__()
        self.path, self.rot, self.overlay = path, int(rot or 0) % 360, overlay
        self.crop = crop                                         # 보기 크롭(4.40) — 꾸밈을 얹은 뒤 자르고 돌린다

    def request_cancel(self):
        pass

    def run(self):
        import os
        out, why, tmp = "", "", None
        try:
            from PIL import Image, ImageOps
            from viewer import photo_doc, photo_io
            from viewer.pathutil import unique_path
            src = Path(self.path)
            photo_io._prep(src)
            with Image.open(str(src)) as im:
                icc = im.info.get("icc_profile")
                im = ImageOps.exif_transpose(im)
                im = photo_io.to_srgb(im, icc).convert("RGBA")
            if self.overlay:
                import fitz
                d = fitz.open("pdf", self.overlay)
                try:
                    pm = d[0].get_pixmap(alpha=True)            # 쪽 pt = 사진 픽셀(D14) — 1:1
                    ov = Image.frombytes("RGBA", (pm.width, pm.height), pm.samples)
                finally:
                    d.close()
                if ov.size != im.size:
                    ov = ov.resize(im.size)
                im = Image.alpha_composite(im, ov)
            from viewer.photo_crop import crop_pil
            im = photo_doc._rotate(crop_pil(im, self.crop), self.rot)
            jpeg = src.suffix.lower() in (".jpg", ".jpeg") or photo_io.is_heif(src)
            ext = ".jpg" if jpeg else ".png"
            dst = unique_path(src.with_name(tr('{stem}_평탄화').format(stem=src.stem) + ext))
            tmp = dst.with_name("~" + dst.name + ".polypix-tmp")
            if jpeg:
                im.convert("RGB").save(str(tmp), "JPEG", quality=FLAT_JPEG_QUALITY)   # EXIF·GPS 는 싣지 않는다
            else:
                im.save(str(tmp), "PNG")
            os.replace(str(tmp), str(dst))
            tmp, out = None, str(dst)
        except Exception as e:                                   # noqa: BLE001 — 원본은 손대지 않았다
            why = type(e).__name__
        finally:
            if tmp is not None:
                try:
                    Path(tmp).unlink()
                except OSError:
                    pass
            self.done.emit(self.path, out, why)
            self.finished.emit()


def _fmt_bytes(n: int) -> str:
    return "%.1f MB" % (n / 1048576.0) if n >= 1048576 else "%d KB" % max(1, round(n / 1024.0))


def _fmt_taken(s: str) -> str:
    """EXIF 날짜 '2026:10:30 14:22:05' → '2026-10-30 14:22'."""
    s = (s or "").strip()
    if len(s) >= 16 and s[4] == ":" and s[7] == ":":
        return s[:4] + "-" + s[5:7] + "-" + s[8:10] + " " + s[11:16]
    return s


def photo_info_line(info: dict, name: str = "") -> str:
    """상태 막대 가운데 한 줄 — 파일 이름 · 촬영일 · 크기 · 파일 크기 · 카메라(있는 것만)."""
    parts = [name] if name else []
    if info.get("taken"):
        parts.append(_fmt_taken(info["taken"]))
    elif info.get("file_time"):                  # 촬영 정보가 없으면 파일 날짜(사용자 지시 '사진의 일시') — 그렇다고 알린다
        parts.append(tr("{t} (파일 날짜)").format(t=_fmt_taken(info["file_time"])))
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
            (tr("파일 날짜"), _fmt_taken(info.get("file_time", ""))),
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


ANIM_EXTS = (".gif", ".webp")   # 움직이는 그림일 수 있는 형식(4.31) — 장 수가 1 보다 많을 때만 ▶
BATCH_SIDE_DEFAULT = 1920       # 일괄 작업 '크기 줄이기' 의 긴 변 기본값(4.30)
WATCH_DEBOUNCE_MS = 300        # 폴더 감시 알림을 모으는 시간(4.27) — 카메라·캡처가 여러 장을 잇달아 쓸 때 한 번만


class PhotoWatchScanWorker(QObject):
    """폴더 감시(4.27) — 보는 폴더(하위 빼고)의 사진·zip 지문(이름·크기·수정 시각)을 배경에서. 응답성 SOT §4.4 감사표의 한 행."""
    done = pyqtSignal(str, object)
    finished = pyqtSignal()

    def __init__(self, folder: str):
        super().__init__()
        self.folder = folder

    def request_cancel(self):
        pass

    def run(self):
        sig = None
        try:
            from viewer.image_page import PHOTO_EXTS
            exts = tuple(PHOTO_EXTS) + (".zip",)
            items = []
            with os.scandir(self.folder) as it:
                for e in it:
                    if e.is_file() and e.name.lower().endswith(exts) and not e.name.startswith("~"):
                        st = e.stat()
                        items.append((e.name.lower(), st.st_size, st.st_mtime_ns))
            sig = frozenset(items)
        except OSError:
            sig = None
        finally:
            self.done.emit(self.folder, sig)
            self.finished.emit()


class PhotoIndexWorker(QObject):
    """사진 정보 색인(사진 보기 SOT 4.24) — 폴더(하위 포함) 사진을 훑어 바뀐 것만 머리를 읽어 넣는다, 사라진 것은 지운다.
    응답성 SOT §4.4 감사표의 한 행(배경·pacing·취소)."""
    done = pyqtSignal(str, int, int, int)      # 폴더, 새로·고친 장 수, 지운 장 수, 모두
    autoTags = pyqtSignal(dict)                # 경로 → 머리 자동 태그(태그 SOT §5.7) — 50장마다, 메인이 태그 저장소에
    finished = pyqtSignal()
    AUTOTAG_BATCH = 50

    def __init__(self, folder: str, autotag: bool = False):
        super().__init__()
        self.folder = str(folder)
        self.autotag = bool(autotag)
        self._cancel = False
        self._tag_out = {}

    def _autotag_one(self, con, tags, rules, key, full, info, write_row: bool):
        """머리 자동 태그(태그 SOT §5.7) — 만든 값을 내보낼 묶음에 넣고, 색인 행의 태그 글은 미리 맞춘다."""
        from viewer import photo_index, photo_tags
        try:
            meta = photo_tags.meta_tags(full, info, rules)
        except Exception:
            meta = []
        self._tag_out[full] = meta
        row = photo_tags.row_tags(tags, full, "meta", meta)
        if write_row:
            photo_index.set_tags(con, key, row, at_ver=photo_tags.AUTOTAG_VER)
        if len(self._tag_out) >= self.AUTOTAG_BATCH:
            self._flush_tags()
        return row

    def _flush_tags(self):
        if self._tag_out:                        # 멈춰도 내보낸다 — 색인 행에는 이미 판 표시를 적었다
            self.autoTags.emit(self._tag_out)
        self._tag_out = {}

    def request_cancel(self):
        self._cancel = True

    def _index_zip(self, con, zpath: str, old: dict, seen: set, tags) -> int:
        """zip 안 사진(4.24 ④) — 열쇠 `<zip 소문자 경로>|<안 이름>`, 크기·시각은 zip 의 것(zip 이 그대로면 다시 읽지 않는다)."""
        import os
        from viewer import pacing, photo_index, photo_zip
        try:
            st = os.stat(zpath)
        except OSError:
            return 0
        members = photo_zip.photo_members(zpath)
        zkey = os.path.normcase(zpath)
        n = 0
        for m in members:
            if self._cancel:
                break
            key = zkey + "|" + m
            seen.add(key)
            if old.get(key) == (st.st_size, st.st_mtime_ns):
                continue
            try:
                from viewer.photo_io import photo_info
                info = photo_info(m, photo_zip.member_bytes(zpath, m))
            except Exception:
                info = {}
            name = m.replace("\\", "/").split("/")[-1]
            photo_index.upsert(con, key, zpath + "|" + m, os.path.normcase(os.path.dirname(zpath)), name,
                               os.path.splitext(name)[1].lower(), st.st_size, st.st_mtime_ns, info,
                               tags.get(zpath) if tags is not None else [], zip_path=zpath, member=m)
            n += 1
            pacing.pace(self)
        return n

    def run(self):
        import os
        from viewer import pacing, photo_index
        from viewer.image_page import PHOTO_EXTS
        from viewer.photo_backup import BACKUP_DIRNAME as _BACKUP_DIRNAME, is_backup_path as _is_backup
        n_new = n_gone = total = 0
        try:
            root = photo_index.norm_folder(self.folder)
            tags = None
            try:
                from viewer.tag_store import TagStore
                tags = TagStore()
            except Exception:
                tags = None
            con = photo_index.connect()
            st = None
            try:
                from viewer.study.study_store import StudyStore
                st = StudyStore()                # 확정 글(저장본)만 읽는다 — §4.36
            except Exception:
                st = None
            rules = None
            todo = set()
            if self.autotag:
                try:
                    from viewer import auto_tag, kr_dong, photo_tags
                    rules = auto_tag.load_rules()
                    kr_dong.ensure_loaded()              # 행정동 자료 — 처음 한 번(배경)
                    todo = photo_index.autotag_todo(con, root, photo_tags.AUTOTAG_VER)
                except Exception:
                    todo = set()
            try:
                old = photo_index.known(con, root)
                seen = set()
                batch = 0
                for dirpath, dirnames, filenames in os.walk(root):
                    if self._cancel:
                        break
                    dirnames[:] = [d for d in dirnames if not d.startswith((".", "~")) and d != _BACKUP_DIRNAME
                                   and not _is_backup(os.path.join(dirpath, d, "x"))]   # 펴기 원본 백업(261106-15)은 색인하지 않는다
                    for fn in filenames:
                        if self._cancel:
                            break
                        ext = os.path.splitext(fn)[1].lower()
                        if ext == ".zip" and not fn.startswith("~"):
                            n_new += self._index_zip(con, os.path.join(dirpath, fn), old, seen, tags)
                            continue
                        if ext not in PHOTO_EXTS or fn.startswith("~"):
                            continue
                        full = os.path.join(dirpath, fn)
                        key = os.path.normcase(full)
                        seen.add(key)
                        total += 1
                        try:
                            stt = os.stat(full)
                        except OSError:
                            continue
                        if old.get(key) == (stt.st_size, stt.st_mtime_ns):
                            if key in todo:                  # 바뀌지 않았지만 머리 자동 태그가 아직·옛 판(태그 SOT §5.7)
                                try:
                                    from viewer.photo_io import photo_info
                                    self._autotag_one(con, tags, rules, key, full, photo_info(full), True)
                                except Exception:
                                    pass
                                batch += 1
                                if batch >= 50:
                                    con.commit()
                                    batch = 0
                                pacing.pace(self)
                            continue
                        t = tags.get(full) if tags is not None else []
                        from viewer.photo_io import cloud_only
                        if cloud_only(stt):
                            # 클라우드에만 있는 사진 — 머리를 읽으면 통째로 내려받는다(4.24·4.37, 261105-10 사용자 결정).
                            #   이름 행만(수정 시각 0 — PC 로 받아지면 다음 훑기가 머리를 읽는다)
                            if key not in old:
                                photo_index.upsert(con, key, full, os.path.normcase(dirpath), fn, ext, stt.st_size, 0, {}, t,
                                                   ocr=photo_saved_ocr(st, full))
                                n_new += 1
                                batch += 1
                                if batch >= 50:
                                    con.commit()
                                    batch = 0
                            continue
                        try:
                            from viewer.photo_io import photo_info
                            info = photo_info(full)
                        except Exception:
                            info = {}
                        at_ver = None
                        if self.autotag and info:
                            from viewer import photo_tags
                            t = self._autotag_one(con, tags, rules, key, full, info, False)
                            at_ver = photo_tags.AUTOTAG_VER
                        photo_index.upsert(con, key, full, os.path.normcase(dirpath), fn, ext, stt.st_size, stt.st_mtime_ns, info, t,
                                           ocr=photo_saved_ocr(st, full), at_ver=at_ver)
                        n_new += 1
                        batch += 1
                        if batch >= 50:
                            con.commit()
                            batch = 0
                        pacing.pace(self)
                if not self._cancel:
                    gone = [k for k in old if k not in seen]
                    photo_index.remove(con, gone)
                    n_gone = len(gone)
                con.commit()
            finally:
                con.close()
                if st is not None:
                    st.close()
        except Exception:
            pass
        finally:
            self._flush_tags()
            self.done.emit(self.folder, n_new, n_gone, total)
            self.finished.emit()


class PhotoKindWorker(QObject):
    """사진 종류 자동 태그(태그 SOT §5.7) — 영수증·명함·서류. 글이 있어 보이는 사진만 작게 OCR, 글은 판정에만(저장 없음, 사진 SOT D15).
    색인 훑기가 끝난 뒤 한 장씩, 취소 가능. 응답성 SOT §4.4 감사표의 한 행(배경·pacing·취소)."""
    found = pyqtSignal(dict)                   # 경로 → [종류] 또는 [] — 판정할 때마다(OCR 이 느려 묶지 않는다)
    finished = pyqtSignal()

    def __init__(self, folder: str, lang: str = ""):
        super().__init__()
        self.folder, self.lang = str(folder), lang
        self._cancel = False
        self.judged = 0

    def request_cancel(self):
        self._cancel = True

    def run(self):
        import os
        from viewer import pacing, photo_index, photo_io, photo_tags
        try:
            from viewer.study import ocr
            if not ocr.ensure_tesseract().get("ok"):
                return                               # Tesseract 없음 — 판정하지 않고 다음에 다시
            tags = None
            try:
                from viewer.tag_store import TagStore
                tags = TagStore()
            except Exception:
                tags = None
            rules = None
            try:
                from viewer import auto_tag
                rules = auto_tag.load_rules()
            except Exception:
                pass
            con = photo_index.connect()
            try:
                todo = photo_index.kind_todo(con, photo_index.norm_folder(self.folder), photo_tags.KIND_VER)
                for key, path in todo:
                    if self._cancel:
                        break
                    try:
                        if photo_io.cloud_only(os.stat(path)):
                            continue                         # 색인 뒤 클라우드로 비워진 사진 — 열면 내려받는다(§4.37, 261105-20). 판정은 아직으로 남긴다
                    except OSError:
                        continue
                    try:
                        k = photo_tags.kind_tag(path, self.lang or None)
                    except Exception:
                        k = None
                    if self._cancel:
                        break
                    new = [photo_tags.alias(k, rules)] if k else []
                    photo_index.set_tags(con, key, photo_tags.row_tags(tags, path, "kind", new),
                                         kind="%d:%s" % (photo_tags.KIND_VER, new[0] if new else ""))
                    con.commit()
                    self.judged += 1
                    self.found.emit({path: new})
                    pacing.pace(self)
            finally:
                con.close()
        except Exception:
            pass
        finally:
            self.finished.emit()


def photo_saved_ocr(st, path) -> str:
    """확정된(저장본) 사진 OCR 글 — 사진이 바뀌었으면(낡음, 단어학습 SOT §14.22) ''. 배경에서."""
    if st is None:
        return ""
    try:
        from viewer.study import ocr as _ocr
        from viewer.study.study_store import file_key_for
        got = st.saved_page(file_key_for(str(path)), 0)
        if not got or not str(got[1]).endswith(_ocr.photo_sig(path)):
            return ""
        return got[0] or ""
    except Exception:
        return ""


def photo_auto_tags(path, text):
    """확정 글로 형식(사진은 '영수증' 만 — 태그 SOT §5.3)·키워드(태그 SOT §9). `(형식 또는 None, [키워드])`. 배경에서."""
    if not (text or "").strip():
        return None, []
    from collections import Counter
    from viewer import auto_tag as at
    f = at.Features(path=str(path), stem="", page_count=1, head_text=text, full_text=text, struct_text=text,
                    terms=Counter(at._tokenize(text)))
    fmt = at.classify_format(f, {})                   # 표준명으로 판정(별칭 전) — 사진은 영수증만 받는다
    if fmt != "영수증":
        fmt = None
    else:
        try:
            fmt = (at.load_rules().get("alias") or {}).get("영수증", "영수증")
        except Exception:
            pass
    try:
        kws = [k["word"] for k in at.suggest_keywords(f, {}, 1)][:10]
    except Exception:
        kws = []
    return fmt, kws


def _photo_date_of_ns(mtime_ns: int) -> str:
    import time as _t
    try:
        return _t.strftime("%Y-%m-%d", _t.localtime(int(mtime_ns) / 1e9))
    except (ValueError, OverflowError, OSError):
        return ""


def _photo_taken_ts(taken: str, mtime: float) -> float:
    """색인의 촬영일(날짜만)의 정렬 시각 — 그날 0시 + 파일 시각의 하루 안 자리(같은 날 사진끼리는 파일 시각 차례)."""
    import time as _t
    d = (taken or "")[:10]
    try:
        return _t.mktime((int(d[:4]), int(d[5:7]), int(d[8:10]), 0, 0, 0, 0, 0, -1)) + (float(mtime) % 86400)
    except (ValueError, OverflowError):
        return float(mtime)


class PhotoDateWorker(QObject):
    """책갈피창 사진 줄 날짜·'수정일 순' 정렬 값(사진 보기 SOT 4.37) — 촬영일(색인 → EXIF 머리만) → 파일 날짜. 응답성 SOT 감사표의 한 행.

    두 단계(261105-10): ① 기억한 값·사진 정보 색인 행·zip·**클라우드에만 있는 사진**(머리를 읽으면 통째로 내려받는다 — 파일 날짜를
    임시 값으로) — `stat` 만, 끝나면 `indexed` ② 나머지만 머리 읽기(pacing). `folder` 를 주면 **미리 읽기** — 그 폴더(하위 포함)
    색인 행만 SQL 로(디스크를 보지 않는다 — 바뀐 사진은 목록 뒤의 작업이 수정 시각으로 걸러 다시 읽는다). `force` 는 한 장 다시 읽기(본문에 열어 받아진 사진)."""
    batch = pyqtSignal(dict)                     # 경로 → (수정 시각 ns, 'YYYY-MM-DD', 정렬 시각 초, 폭, 높이, 바이트, 임시 값)
    indexed = pyqtSignal()
    finished = pyqtSignal()
    INDEX_BATCH = 500
    READ_BATCH = 50

    def __init__(self, paths, cache: dict, folder=None, force: bool = False):
        super().__init__()
        self.paths, self.cache = list(paths), cache
        self.folder = folder
        self.force = bool(force)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    @staticmethod
    def _known(root=None) -> dict:
        """사진 정보 색인 = 캐시(4.38 사용자 결정) — 열쇠 → (크기, 수정 시각 ns, 촬영일, 폭, 높이, 원래 경로). `root` 면 그 폴더(하위 포함)만."""
        import os as _os
        from viewer import photo_index
        known = {}
        try:
            con = photo_index.connect_read()             # 읽기만 — 색인 훑기의 쓰기 트랜잭션 뒤에 서지 않는다(261105-10)
            try:
                if root:
                    sql = ("SELECT key, size, mtime_ns, taken, width, height, path FROM photos WHERE zip IS NULL"
                           " AND (folder = ? OR substr(folder, 1, ?) = ?)")
                    pre = root.rstrip("\\/") + _os.sep
                    rows = con.execute(sql, (root, len(pre), pre))
                else:
                    rows = con.execute("SELECT key, size, mtime_ns, taken, width, height, path FROM photos WHERE zip IS NULL")
                for k, sz, mt, tk, w_, h_, pth in rows:
                    known[k] = (sz or 0, mt or 0, tk or "", w_ or 0, h_ or 0, pth or k)
            finally:
                con.close()
        except Exception:
            known = {}
        return known

    def _emit(self, out: dict, n: int) -> dict:
        if len(out) >= n and not self._cancel:
            self.batch.emit(out)
            return {}
        return out

    def run(self):
        import os as _os
        from viewer import pacing, photo_io, photo_index
        try:
            if self.folder is not None:
                self._prime(photo_index.norm_folder(self.folder))
                return
            known = self._known()
            out, rest = {}, []
            for p in self.paths:                         # ① 디스크는 stat 만
                if self._cancel:
                    return
                try:
                    st = _os.stat(p)
                except OSError:
                    continue
                key = _os.path.normcase(p)
                hit = self.cache.get(key)
                cloud = photo_io.cloud_only(st)
                if self.force:
                    rest.append((p, st))
                    continue
                if hit and hit[0] == st.st_mtime_ns and len(hit) >= 6 and not (len(hit) > 6 and hit[6] and not cloud):
                    continue                             # 앱이 이미 붙였다(임시 값이면 PC 로 받아진 뒤 다시)
                row = known.get(key)
                if p.lower().endswith(".zip"):
                    rec = (photo_io._file_date(p), float(st.st_mtime), 0, 0, False)
                elif row and row[0] == st.st_size and row[1] and row[1] == st.st_mtime_ns:
                    if row[2]:                           # 색인의 촬영일 — 머리를 다시 읽지 않는다(폭·높이가 없어도)
                        rec = (row[2][:10], _photo_taken_ts(row[2], st.st_mtime), row[3], row[4], False)
                    else:                                # 색인이 머리를 읽었는데 촬영일이 없었다 — 파일 날짜
                        rec = (photo_io._file_date(p), float(st.st_mtime), row[3], row[4], False)
                elif cloud:
                    if row and row[2]:                   # 받아 둔 적 있는 촬영일(지금은 클라우드에만)
                        rec = (row[2][:10], _photo_taken_ts(row[2], st.st_mtime), row[3], row[4], True)
                    else:
                        rec = (photo_io._file_date(p), float(st.st_mtime), 0, 0, True)
                else:
                    rest.append((p, st))
                    continue
                if rec[0]:
                    out[p] = (st.st_mtime_ns, rec[0], rec[1], int(rec[2]), int(rec[3]), int(st.st_size), rec[4])
                out = self._emit(out, self.INDEX_BATCH)
            out = self._emit(out, 1)
            if self._cancel:
                return
            self.indexed.emit()
            for p, st in rest:                           # ② 머리 읽기
                if self._cancel:
                    return
                d, ts, w, h = photo_io.photo_meta(p)     # 촬영 시각·크기(머리만) → 없으면 파일 시각
                pacing.pace(self)
                if d:
                    out[p] = (st.st_mtime_ns, d, ts, int(w), int(h), int(st.st_size), False)
                out = self._emit(out, self.READ_BATCH)
            self._emit(out, 1)
        except Exception:
            pass
        finally:
            self.finished.emit()

    def _prime(self, root: str):
        """미리 읽기 — 색인 행만(디스크를 보지 않는다). 기억한 값이 있는 줄은 건너뛴다."""
        out = {}
        for key, (sz, mt, tk, w, h, pth) in self._known(root).items():
            if self._cancel:
                return
            if not mt or key in self.cache:
                continue                                 # 이름 행만(클라우드 사진, 4.24)·이미 아는 것
            if tk:
                rec = (tk[:10], _photo_taken_ts(tk, mt / 1e9))
            else:
                rec = (_photo_date_of_ns(mt), mt / 1e9)
            if rec[0]:
                out[pth] = (int(mt), rec[0], rec[1], int(w), int(h), int(sz), False)
            out = self._emit(out, self.INDEX_BATCH)
        self._emit(out, 1)


def photo_ocr_save(path: str, rot: int = 0, lang: str = "", picker=None) -> int:
    """사진 한 장을 읽어 보류 저장소에(사진 보기 SOT 4.34·4.44, 단어학습 SOT §14.22) — 배경 스레드에서만 부른다. 낱말 수."""
    from viewer.study import ocr
    from viewer.study.study_store import StudyStore, file_key_for
    picker = picker or ocr.LangPicker(lang or ocr.default_lang())
    res = picker.read_photo(path, rot=int(rot or 0))
    words = res.get("words") or []
    st = StudyStore()                                # 보류가 켜져 있으면 보류 DB 로(단어학습 SOT §14.21)
    try:
        key = file_key_for(path)
        st.save_page(key, 0, res.get("text", "") or "", dpi=72, engine=res.get("engine", "tesseract"),
                     source="ocr", conf=float(res.get("conf", 0) or 0), words=words, lang=res.get("lang", ""))
        st.set_meta(key, path, 1, res.get("lang", ""))
    finally:
        st.close()
    return len(words)


class PhotoOcrBatchWorker(QObject):
    """사진 여러 장 OCR(사진 보기 SOT 4.44, 261107-6) — 배경 한 워커가 차례로, 사진 사이 `pacing.pace`·[중단].
    결과는 사진마다 보류 저장소(한 장과 같은 `photo_ocr_save`). 응답성 SOT 감사표의 한 행."""
    one = pyqtSignal(str, int)                   # 끝난 사진, 낱말 수(못 읽으면 -1)
    progress = pyqtSignal(int, int, str)         # 몇째, 모두, 경로
    done = pyqtSignal(int, int, bool)            # 읽음, 못 읽음, 멈춤
    finished = pyqtSignal()

    def __init__(self, paths, rots: dict, lang: str = ""):
        super().__init__()
        self.paths, self.rots, self.lang = [str(p) for p in paths], dict(rots or {}), lang
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        ok = bad = 0
        stopped = False
        try:
            from viewer import pacing
            picker = None
            n = len(self.paths)
            for i, p in enumerate(self.paths):
                if self._cancel:
                    stopped = True
                    break
                self.progress.emit(i + 1, n, p)
                try:
                    if picker is None:
                        from viewer.study import ocr
                        picker = ocr.LangPicker(self.lang or ocr.default_lang())
                    k = photo_ocr_save(p, self.rots.get(p, 0), self.lang, picker=picker)
                    ok += 1
                    self.one.emit(p, k)
                except Exception:                        # noqa: BLE001 — 동영상·깨진 파일·Tesseract 없음
                    bad += 1
                    self.one.emit(p, -1)
                pacing.pace(self)
        finally:
            self.done.emit(ok, bad, stopped)
            self.finished.emit()


class PhotoOcrWorker(QObject):
    """사진 한 장 OCR(사진 보기 SOT 4.34, 단어학습 SOT §14.22) — 배경, 결과는 보류 저장소. 응답성 SOT 감사표의 한 행."""
    done = pyqtSignal(str, int)                  # 사진 경로, 낱말 수
    error = pyqtSignal(str, str)
    finished = pyqtSignal()

    def __init__(self, path: str, rot: int, lang: str):
        super().__init__()
        self.path, self.rot, self.lang = path, int(rot or 0), lang

    def run(self):
        try:
            self.done.emit(self.path, photo_ocr_save(self.path, self.rot, self.lang))
        except Exception as e:                   # noqa: BLE001 — Tesseract 없음·못 여는 사진
            self.error.emit(self.path, str(e))
        finally:
            self.finished.emit()


class PhotoDeviceListWorker(QObject):
    """연결된 휴대 장치와 그 사진 폴더(사진 보기 SOT 4.33) — 배경, 셸 COM 은 이 스레드에서. 응답성 SOT 감사표의 한 행."""
    done = pyqtSignal(list)                      # [(장치, [폴더…], 오류 종류 또는 '')]
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        out = []
        try:
            from viewer import photo_device as pd
            with pd.com_thread():
                for dev in pd.BACKEND.devices():
                    if self._cancel:
                        break
                    try:
                        out.append((dev, pd.BACKEND.folders(dev), ""))
                    except pd.DeviceError as e:
                        out.append((dev, [], e.kind))
                    except Exception:
                        out.append((dev, [], "gone"))
        except Exception:
            out = []
        finally:
            if not self._cancel:
                self.done.emit(out)
            self.finished.emit()


class PhotoDeviceWorker(QObject):
    """휴대 장치의 사진 폴더 하나를 캐시로 복사(사진 보기 SOT 4.33) — 한 장씩 알림, 취소 가능. 응답성 SOT 감사표의 한 행."""
    listed = pyqtSignal(int)                     # 폴더 안 사진 수
    fileReady = pyqtSignal(str)                  # 캐시에 들어온 사진 경로
    done = pyqtSignal(str, str, int, str)        # 장치, 폴더, 장 수, 오류 종류 또는 ''
    finished = pyqtSignal()

    def __init__(self, dev: str, folder: str, first: str | None = None):
        super().__init__()
        self.dev, self.folder, self.first = dev, folder, first
        self.dev_folder = (dev, folder)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        n, err = 0, ""
        try:
            from viewer import photo_device as pd
            with pd.com_thread():
                got = pd.copy_folder(self.dev, self.folder, should_cancel=lambda: self._cancel, first=self.first,
                                     on_list=lambda names: self.listed.emit(len(names)),
                                     on_file=lambda p: self._cancel or self.fileReady.emit(p))
                n = len(got)
            try:
                pd.prune_cache(keep=pd.cache_dir_for(self.dev, self.folder))
            except Exception:
                pass
        except Exception as e:
            err = getattr(e, "kind", "gone")
        finally:
            if not self._cancel:
                self.done.emit(self.dev, self.folder, n, err)
            self.finished.emit()


class PhotoDeviceScanWorker(QObject):
    """단일 보기 — 장치의 모든 사진 이름(사진 보기 SOT 4.33). 새 폴더부터 한 폴더씩 알림, 받지는 않는다. 응답성 SOT 감사표의 한 행."""
    folderScanned = pyqtSignal(str, str, list)   # 장치, 폴더, 사진 이름
    finished = pyqtSignal()

    def __init__(self, todo: list):
        super().__init__()
        self.todo = todo                         # [(장치, [폴더…])]
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        try:
            from viewer import photo_device as pd
            with pd.com_thread():
                for dev, folders in self.todo:
                    for f in folders:
                        if self._cancel:
                            return
                        try:
                            nm = pd.BACKEND.photos(pd.BACKEND.open_folder(dev, f))
                        except Exception:
                            break                # 뽑혔거나 잠김 — 그 장치는 여기까지
                        if not self._cancel:
                            self.folderScanned.emit(dev, f, nm)
        except Exception:
            pass
        finally:
            self.finished.emit()


class PhotoZipWorker(QObject):
    """사진이 든 zip 을 캐시로 꺼낸다(사진 보기 SOT 4.24 ③) — 배경, 취소 가능. 응답성 SOT §4.4 감사표의 한 행."""
    done = pyqtSignal(str, list)
    finished = pyqtSignal()

    def __init__(self, zip_path: str):
        super().__init__()
        self.zip_path = zip_path
        self.names = {}                  # 꺼낸 경로(normcase) → zip 안 이름 — '이 사진 풀기' 가 메인에서 zip 을 다시 열지 않게(261106-21)
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def run(self):
        out = []
        try:
            from viewer import photo_zip
            out = photo_zip.extract(self.zip_path, should_cancel=lambda: self._cancel)
            try:
                d = photo_zip.cache_dir_for(self.zip_path)
                for n in photo_zip.photo_members(self.zip_path):
                    rel = photo_zip._safe_rel(n)
                    if rel:
                        self.names[os.path.normcase(os.path.abspath(str(d / rel)))] = n
            except Exception:
                pass
            try:
                photo_zip.prune_cache()
            except Exception:
                pass
        except Exception:
            out = []
        finally:
            if not self._cancel:
                self.done.emit(self.zip_path, out)
            self.finished.emit()


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
