"""260628(감사 F-5): 녹화·발표 컨트롤러 — MainWindow 에서 분리한 믹스인.

app.py 분할 후속(§11.11). 담당:
  - **화면+음성 녹화**: 출력 경로(`_recording_out_path`/`_present_record_path`),
    레코더 생성·시작/일시정지/정지(`_make_recorder`/`_on_record_*`), 버튼 상태
    (`_update_rec_buttons`), 설정·사전 점검(`_open_recording_settings`/`_test_recording`/
    `_ask_rec_test_gate`)
  - **발표 모드 보조**: 파일 경계 이동(`_presentation_sibling`), 상단 풀다운용 책갈피·
    하이퍼링크(`_presentation_bookmarks`/`_presentation_hyperlinks`), 종료 처리
    (`_on_presentation_closed`), 펜·포인터 설정(`_on_pen_settings`/`_on_pointer_settings`)

방식은 §11.11 표준: **본문 그대로 옮긴 믹스인**(`class MainWindow(PresentMixin, ...)`).
`self.*` 참조가 모두 그대로 동작하므로 **호출부(툴바·발표창 시그널)는 변경 없음**.
SOT: `영상 및 음성 작업 계획서.md`.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from viewer.workers import run_in_thread

__all__ = ["PresentMixin"]


class _RecStopWorker(QObject):
    """260628(발표 SOT B7): `ScreenRecorder.stop()` 을 **백그라운드에서** 수행.

    stop() 은 ffmpeg 에 'q' 를 보낸 뒤 **최대 8초** 종료를 기다린다. 발표 중 파일이 바뀌는
    순간 이 대기가 UI 스레드에서 일어나면 화면이 멈춘다 → 스레드로 옮기고, 완료 시그널을
    받아 **그때 새 녹화를 시작**한다(이전 파일 마감 → 새 파일 시작 순서는 그대로 보장)."""
    finished = pyqtSignal(dict)

    def __init__(self, rec):
        super().__init__()
        self._rec = rec

    def run(self):
        try:
            self._rec.stop()
        except Exception:
            pass
        self.finished.emit({})


class PresentMixin:
    """MainWindow 에 믹스인되는 녹화·발표 메서드 모음."""

    def _recording_out_path(self):
        import time as _t
        d = self._prefs.get("recording_dir") or (str(self._folder) if self._folder else "")
        if not d:
            d = str(Path.home())
        name = "polypdf_rec_" + _t.strftime("%Y%m%d_%H%M%S") + ".mp4"
        return str(Path(d) / name)

    def _present_record_path(self, path=None):
        """260611-23: 녹화 파일명 = <PDF 파일명>_YYYYMMDD_HHMM_SS.mp4 (발표 파일 기준)."""
        import time as _t
        d = self._prefs.get("recording_dir") or (str(self._folder) if self._folder else "")
        if not d:
            d = str(Path.home())
        if path is None and getattr(self, "_present", None) is not None:
            try:
                path = str(self._present._path)
            except Exception:
                path = None
        stem = Path(path).stem if path else "polypdf_rec"
        name = f"{stem}_{_t.strftime('%Y%m%d_%H%M_%S')}.mp4"
        # 260628: 같은 초에 다시 시작하면 기존 녹화를 덮어쓰던 문제 → 표준 유일경로 사용.
        from viewer.pathutil import unique_path
        return str(unique_path(Path(d) / name))

    def _on_present_file_changed(self, path):
        """260611-23: 발표 중 다른 파일 시작 → 현재 녹화 종료 후 새 파일로 녹화 재시작.

        260628(B7): 종전에는 `stop()`(최대 8초 대기)을 UI 스레드에서 수행해 **발표 도중
        파일이 바뀌는 순간 화면이 멈출 수 있었다**. 이제 종료는 백그라운드에서 하고
        **완료 시그널을 받은 뒤 새 녹화를 시작**한다(순서는 그대로 보장)."""
        r = getattr(self, "_rec", None)
        if r is None or not r.is_recording():
            return
        self._rec = None
        self._stop_rec_watch()             # 의도된 전환 → 중단 경고 대상 아님
        self._update_rec_buttons()
        self.status.showMessage("녹화 전환 중… (이전 파일 마무리)", 8000)
        w = _RecStopWorker(r)
        w.finished.connect(lambda _res=None, p=path: self._start_rec_after_switch(p))
        run_in_thread(w, self._thread_keep)

    def _start_rec_after_switch(self, path):
        """260628(B7): 이전 녹화 마감이 끝난 뒤 새 파일로 녹화 시작(UI 스레드)."""
        if getattr(self, "_present", None) is None:
            return                          # 그새 발표가 끝났으면 새로 시작하지 않는다
        out = self._present_record_path(path)
        self._rec, ff = self._make_recorder(out)
        if not ff:
            self._rec = None
            self._update_rec_buttons()
            return
        ok, _msg = self._rec.start()
        if not ok:
            self._rec = None
        else:
            self._start_rec_watch()        # 260628(B6)
            self.status.showMessage(f"녹화 전환: {Path(out).name}", 3000)
        self._update_rec_buttons()

    def _make_recorder(self, out_path):
        from viewer.recorder import find_ffmpeg, ScreenRecorder
        ff = find_ffmpeg(self._prefs.get("ffmpeg_path", ""))
        return ScreenRecorder(
            ff, out_path,
            audio_mode=self._prefs.get("recording_audio_mode", "mic"),
            mic=self._prefs.get("recording_mic", ""),
            system=self._prefs.get("recording_system", ""),
            fps=30, crf=23, abitrate="192k"), ff

    def _update_rec_buttons(self, dead: bool = False):
        """260628: `dead=True` 면 발표 표시등을 **경고색**으로 — 전체화면 발표 중에는
        메인창 상태바가 보이지 않아 B6 경고가 발표자에게 닿지 않기 때문이다(§9.0.1)."""
        if getattr(self, "_present", None) is not None:
            r = getattr(self, "_rec", None)
            self._present.set_recording_state(
                bool(r and r.is_recording()), bool(r and r.is_paused()), dead)

    def _on_record_toggle(self):
        r = getattr(self, "_rec", None)
        if r is not None and r.is_recording():
            if r.is_paused():
                r.resume()
            self._update_rec_buttons()
            return
        # 260611-25: '녹화 테스트' 합격 결과가 없으면 확인(녹화없이 진행/설정진행/취소)
        if not self._prefs.get("recording_test_ok"):
            choice = self._ask_rec_test_gate()
            if choice == "settings":
                self._open_recording_settings()
                return
            if choice != "proceed":          # cancel · 녹화없이 진행 → 녹화 안 함
                return
        # 260611-23: 발표 중이면 파일명 기반(<파일>_날짜_시각)으로 저장
        out = (self._present_record_path() if getattr(self, "_present", None)
               else self._recording_out_path())
        self._rec, ff = self._make_recorder(out)
        if not ff:
            QMessageBox.warning(self, "녹화 불가",
                                "ffmpeg 를 찾을 수 없습니다. 설정에서 ffmpeg 경로를 지정하세요.")
            self._rec = None
            return
        ok, msg = self._rec.start()
        if not ok:
            QMessageBox.warning(self, "녹화 실패", msg)
            self._rec = None
            return
        self.status.showMessage(f"녹화 시작: {Path(out).name}", 3000)
        self._start_rec_watch()            # 260628(B6)
        self._update_rec_buttons()

    def _ask_rec_test_gate(self):
        """260611-25: 녹화 테스트 합격 결과 없을 때 — 녹화없이 진행/설정진행/취소."""
        par = getattr(self, "_present", None) or self
        box = QMessageBox(par)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("녹화 확인")
        box.setText("'녹화 테스트' 합격 결과가 없습니다.\n어떻게 할까요?")
        b_no = box.addButton("녹화 없이 진행", QMessageBox.ButtonRole.AcceptRole)
        b_set = box.addButton("녹화 설정", QMessageBox.ButtonRole.ActionRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c is b_set:
            return "settings"
        if c is b_no:
            return "noproceed"      # 녹화 없이 시계만 사용
        return "cancel"

    def _open_recording_settings(self):
        """260611-25: '화면+음성 녹화' 설정 화면(녹화 테스트 포함)을 띄움."""
        from viewer.widgets.settings_dialog import SettingsDialog
        par = getattr(self, "_present", None) or self
        dlg = SettingsDialog(self._prefs, par, host=self)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, dlg.focus_recording)
        if dlg.exec() == dlg.DialogCode.Accepted:
            new_prefs = dlg.result_prefs()
            self._apply_prefs(new_prefs)
            self._save_settings_now()
            self.status.showMessage("설정 저장됨", 3000)

    def _on_record_pause(self):
        r = getattr(self, "_rec", None)
        if r is not None and r.is_recording() and not r.is_paused():
            r.pause()
            self._update_rec_buttons()

    # ===== 260628(발표 SOT B6): 녹화 중단 감시 =============================
    def _start_rec_watch(self):
        """녹화 중 주기적으로 살아 있는지 확인. ffmpeg 가 예기치 않게 죽으면(디스크 가득·
        오디오 장치 분리 등) 종전에는 **아무 표시가 없어 끊긴 줄 모르고 계속 발표**하게 됐다.
        알림은 사용자 선택에 따라 **상태바만** 사용한다(발표 흐름을 끊지 않음)."""
        t = getattr(self, "_rec_watch", None)
        if t is None:
            t = self._rec_watch = QTimer(self)
            t.setInterval(4000)
            t.timeout.connect(self._check_rec_alive)
        if not t.isActive():
            t.start()

    def _stop_rec_watch(self):
        t = getattr(self, "_rec_watch", None)
        if t is not None and t.isActive():
            t.stop()

    def _check_rec_alive(self):
        r = getattr(self, "_rec", None)
        if r is None:                      # 정상 종료됨 — 감시 해제
            self._stop_rec_watch()
            return
        if r.is_recording():               # 일시정지(프로세스 suspend)도 살아 있음으로 본다
            return
        # 여기 도달 = 사용자가 멈추지 않았는데 ffmpeg 가 사라짐
        out = ""
        try:
            out = Path(r.out_path).name
        except Exception:
            pass
        self._rec = None
        self._stop_rec_watch()
        self._update_rec_buttons(dead=True)     # 260628: 발표 표시등을 경고색으로
        self.status.showMessage(
            f"⚠ 녹화가 중단되었습니다{(' — ' + out) if out else ''}"
            " (디스크 공간·오디오 장치를 확인하세요)", 15000)

    def _on_record_stop(self):
        r = getattr(self, "_rec", None)
        if r is not None:
            out = r.out_path
            self._stop_rec_watch()         # 260628(B6): 의도된 정지 → 경고 대상 아님
            r.stop()
            self._rec = None
            self.status.showMessage(f"녹화 저장: {Path(out).name}", 4000)
        self._update_rec_buttons()

    def _test_recording(self, parent=None):
        """260609-17(F4)/260618-14: 3초 테스트 녹화 — 실패 시 ffmpeg 실제 오류·종료코드 표시.
        출력이 비면 백신(Defender)의 ffmpeg 실행 차단을 의심해 안내(조용한 실패 방지)."""
        import tempfile, subprocess
        from viewer.recorder import (find_ffmpeg, build_command, CREATE_NO_WINDOW)
        ff = find_ffmpeg(self._prefs.get("ffmpeg_path", ""))
        if not ff:
            return False, "ffmpeg 를 찾을 수 없습니다. (구성요소 설치 또는 설정에서 경로 지정)"
        out = Path(tempfile.gettempdir()) / "polypdf_rectest.mp4"
        try:
            if out.exists():
                out.unlink()
        except Exception:
            pass
        am = self._prefs.get("recording_audio_mode", "mic")
        cmd = build_command(ff, str(out), audio_mode=am,
                            mic=self._prefs.get("recording_mic", ""),
                            system=self._prefs.get("recording_system", ""), duration=3)
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=30,
                               creationflags=CREATE_NO_WINDOW)
            rc = p.returncode
            err = (p.stderr or b"").decode("utf-8", "replace").strip()
        except FileNotFoundError:
            return False, ("ffmpeg 실행 파일이 없습니다(백신이 삭제·격리했을 수 있음).\n"
                           "Windows 보안에서 ffmpeg.exe 를 허용/복원하거나 다시 설치하세요.")
        except subprocess.TimeoutExpired:
            return False, "테스트 시간 초과(녹화가 정상 종료되지 않음)."
        except OSError as e:
            return False, ("ffmpeg 을 실행할 수 없습니다(백신 차단 의심): %s\n"
                           "설치 폴더의 ffmpeg.exe 를 Windows 보안 예외에 추가하세요." % e)
        if not out.exists() or out.stat().st_size < 1024:
            tail = "\n".join(err.splitlines()[-6:]) if err else ""
            msg = "녹화 파일이 생성되지 않았습니다 (ffmpeg 종료코드 %s)." % rc
            if tail:
                msg += "\n\n[ffmpeg 오류]\n" + tail
            else:
                msg += ("\n\nffmpeg 출력이 전혀 없습니다 — 백신(Windows Defender)이 ffmpeg 실행을 "
                        "차단했을 수 있습니다. 설치 폴더의 ffmpeg.exe 를 보안 예외에 추가한 뒤 다시 시도하세요.")
            return False, msg
        # 오디오 스트림 유무 확인
        try:
            pr = subprocess.run([ff, "-hide_banner", "-i", str(out)],
                                capture_output=True, creationflags=CREATE_NO_WINDOW)
            has_audio = "Audio:" in (pr.stderr or b"").decode("utf-8", "replace")
        except Exception:
            has_audio = False
        if am != "none" and not has_audio:
            return True, ("화면 녹화는 정상입니다. 단, 선택한 오디오가 녹음되지 않았습니다.\n"
                          "장치 선택을 확인하세요(시스템 소리는 Stereo Mix/가상 오디오 필요).")
        return True, "테스트 성공 — 화면" + ("·소리 모두" if am != "none" else "") + " 정상 녹화됩니다."

    def _on_pen_settings(self):
        # 260611-2: 발표 펜 설정도 본문과 공유되는 동일 다이얼로그 사용 → 양쪽 동시 반영
        self._open_main_pen_settings()

    def _presentation_sibling(self, cur_path: str, direction: int):
        """260609-7: 발표 파일경계용 — 책갈피창 순서의 다음/이전 파일 경로."""
        try:
            files = self.bookmark_tree.all_file_paths() or []
            if not files:
                return None
            norm = [str(Path(f)) for f in files]
            cs = str(Path(cur_path))
            if cs not in norm:
                return None
            j = norm.index(cs) + (1 if direction > 0 else -1)
            if 0 <= j < len(files):
                return files[j]
        except Exception:
            pass
        return None

    def _presentation_bookmarks(self, path: str):
        """260609-12(D3): 발표 상단 페이지 풀다운용 — (page0, 책갈피명) 목록."""
        try:
            import fitz
            d = fitz.open(str(path))
            toc = d.get_toc(simple=True)
            d.close()
            return [(int(p) - 1, str(t)) for (lvl, t, p) in toc if int(p) >= 1]
        except Exception:
            return []

    def _presentation_hyperlinks(self, path: str, page0: int):
        """260609-8: 발표 상단 띠용 — 해당 파일·페이지의 하이퍼링크 목록."""
        try:
            st = self._ensure_hyperlink_store()
            if st and str(path).lower().endswith(".pdf"):
                return st.links_for(path, page0)
        except Exception:
            pass
        return []

    def _on_presentation_closed(self):
        """발표 창을 닫으면 마지막 파일·페이지를 메인 뷰에 동기화."""
        # 260609-17(F4): 녹화 중이면 안전 종료(파일 마감)
        r = getattr(self, "_rec", None)
        if r is not None and r.is_recording():
            self._stop_rec_watch()          # 260628(B6): 의도된 종료
            try:
                r.stop()
            except Exception:
                pass
            self._rec = None
        w = getattr(self, "_present", None)
        if not w or not self.main_view:
            return
        try:
            path = str(w._path)
            page = int(w._page)
            cur = self.main_view.current_file()
            if not cur or str(Path(cur)) != str(Path(path)):
                self._on_bookmark_activated(path, page)   # 파일이 바뀌었으면 로드
            else:
                self.main_view.go_to_page(page)
        except Exception:
            pass

    def _on_pointer_settings(self):
        from viewer.widgets.pointer_settings_dialog import PointerSettingsDialog
        from viewer.widgets.presentation import DEFAULT_POINTERS
        cur = self._prefs.get("presentation_pointers") or DEFAULT_POINTERS
        dlg = PointerSettingsDialog(cur, self._present or self)
        if dlg.exec():
            pts = dlg.result_pointers()
            self._prefs["presentation_pointers"] = pts
            self._save_settings_now()
            if self._present is not None:
                self._present.set_pointers(pts)
