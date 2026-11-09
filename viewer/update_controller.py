"""260628(감사 F-1): 자동 업데이트 UI 컨트롤러 — MainWindow 에서 분리한 믹스인.

`app.py`(9,700줄 → 분할 진행 중)에서 **가장 독립적인 덩어리**부터 떼어낸다.
이 믹스인은 상태바·설정(prefs)·업데이트 시그널만 사용하므로 결합도가 낮다.

방식: **믹스인 클래스**(`class MainWindow(UpdateMixin, ..., QMainWindow)`).
`self.*` 참조가 전부 그대로 동작하므로 **호출부(메뉴·시작 타이머·closeEvent)는
변경이 없다**. 상태(`_pending_update`/`_pending_zip`/`_updating`/`_update_sig`)는
종전대로 MainWindow.__init__ 에서 초기화한다.

담당: 업데이트 확인(`_check_for_updates`/`_on_update_result`), 백그라운드 선다운로드
(`_start_bg_update_download`/`_on_bg_dl_done`), 업그레이드 시작(`_begin_upgrade`),
구성요소 설치 창(`_open_components_installer`).

무결성·다중 인스턴스 규칙은 마스터 SOT §14.5(U1~U7), 실제 적용은 `viewer/updater.py`.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox
from viewer.i18n import tr

__all__ = ["UpdateMixin"]


class UpdateMixin:
    """MainWindow 에 믹스인되는 업데이트 관련 메서드 모음."""

    def _check_for_updates(self, manual: bool = False):
        """최신 릴리스를 백그라운드로 확인(결과는 _on_update_result). manual=True 면
        저장소 미설정 시 입력받고, 최신/실패도 알림."""
        from viewer import updater
        # 260618-11: 설정값이 있으면 우선, 없으면 기본 저장소(고정) — 입력 불필요.
        repo = (self._prefs.get("update_repo") or "").strip() or updater.DEFAULT_REPO
        if not updater.valid_repo(repo):
            if not manual:
                return
            from PyQt6.QtWidgets import QInputDialog
            txt, ok = QInputDialog.getText(
                self, tr("업데이트 저장소 설정"),
                tr("GitHub 저장소를 'OWNER/REPO' 형식으로 입력하세요:"), text=repo)
            if not ok or not updater.valid_repo((txt or "").strip()):
                return
            repo = txt.strip()
            self._prefs["update_repo"] = repo
            try:
                self._save_settings_now()
            except Exception:
                pass
        dlg = None
        if manual:
            self.status.showMessage(tr("업데이트 확인 중…"), 3000)
            # 261026-5(사용자 지시): 창을 **먼저** 띄우고 확인 결과를 그 창에 보인다 — 아래에 두 체크(자동 다운로드·베타)
            from viewer.widgets.update_dialog import UpdateDialog
            from viewer import updater as _upd
            dlg = UpdateDialog(None, _upd.current_version(), "check", self, options=self._update_options())
            self._update_check_dlg = dlg
            self._update_check_closed = False
        import threading
        sig = self._update_sig

        channel = str(self._prefs.get("update_channel", "stable"))   # 260628-6(④)
        # 260618-36: 1.0 이전(major 0=pre-stable)에는 빌드가 베타로만 나오므로, 저장된 설정과
        #   무관하게 항상 베타를 포함해 새 베타 업그레이드를 찾는다. 1.0 이후엔 설정값을 따른다.
        try:
            if int((updater.current_version().lstrip("vV").split(".")[0]) or "0") == 0:
                channel = "beta"
        except Exception:
            pass

        def work():
            try:
                updater.cleanup_pending()        # 261108-13: 이미 깐 판의 받아 둔 파일(설치본 340MB) — 배경에서 지운다
            except Exception:
                pass
            info = updater.check_latest(repo, channel=channel)
            try:
                sig.done.emit(info, bool(manual))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()
        if dlg is not None:
            try:
                dlg.exec()
            finally:
                self._update_check_dlg = None
                self._update_check_closed = True     # 결과가 늦게 오면 창을 다시 띄우지 않는다
            if dlg.choice == "update":
                self._upgrade_now()

    def _manual_note(self, text: str) -> None:
        """261026-5 수동 확인의 결과 한 줄 — 업데이트 창이 열려 있으면 그 창에, 아니면 알림 창."""
        dlg = getattr(self, "_update_check_dlg", None)
        if dlg is not None:
            dlg.show_message(text.replace("\n", "<br>"))
        else:
            QMessageBox.information(self, tr("업데이트"), text)

    def _on_update_result(self, info, manual):
        from viewer import updater
        cur = updater.current_version()
        if manual and getattr(self, "_update_check_closed", False):
            manual = False                     # 261026-5 확인 창을 먼저 닫았다 — 시작 때 자동 확인처럼 조용히
        if not info:
            if manual:
                self._manual_note(tr("업데이트 정보를 가져오지 못했습니다.\n인터넷 연결과 저장소 설정을 확인하세요."))
            return
        latest = info.get("version") or ""
        if not updater.is_newer(latest, cur):
            if manual:
                self._manual_note(tr('현재 최신 버전입니다. (v{cur})').format(cur=cur))
            return
        if not updater.is_frozen():
            if manual:
                self._manual_note(
                    tr('새 버전 v{latest} 이 있습니다(현재 v{cur}).\n개발(소스) 실행 중에는 자동 교체가 적용되지 않습니다.\n{get}').format(latest=latest, cur=cur, get=info.get('html_url', '')))
            return
        if not info.get("asset_url"):
            if manual:
                self._manual_note(
                    tr('새 버전 v{latest} 이 있으나 배포 zip 자산을 찾지 못했습니다.\n{get}').format(latest=latest, get=info.get('html_url', '')))
            return
        # 260618-24: 새 버전 인지(종료 시 업그레이드 프롬프트용)
        self._pending_update = info
        # 260618-36: 베타(테스트) 릴리스면 프롬프트에 명시 — 사용자가 알고 동의하게.
        is_beta = updater.is_prerelease_tag(info.get("tag", ""))
        kind = tr("베타(테스트) 버전") if is_beta else tr("버전")
        if manual:
            # 261008-17·-18(마스터 §14.5 U13·U14): 업데이트 창에서 **바뀐 내용**을 보고 고른다 →
            #   ① 앱이 켜진 채 먼저 받는다 ② 닫는다(편집 저장 확인은 종료 길) ③ 설치 도우미가
            #   다른 창을 모두 닫고 확인 ④ 설치. 받기를 실패·취소하면 닫지 않는다.
            #   261026-5: 먼저 띄운 확인 창(`_check_for_updates`)에 결과를 넣는다 — [업데이트] 는 그 창이 닫힌 뒤 `_upgrade_now`
            dlg = getattr(self, "_update_check_dlg", None)
            if dlg is not None:
                dlg.show_result(info, cur)
            else:
                from viewer.widgets.update_dialog import UpdateDialog
                dlg = UpdateDialog(info, cur, "manual", self, options=self._update_options())
                dlg.exec()
                if dlg.choice == "update":
                    self._upgrade_now()
        else:
            # C: 시작 시 자동 확인 — 설정 켜져 있으면 백그라운드로 미리 받아둠
            if self._prefs.get("auto_download_update", True):
                self._start_bg_update_download(info)
            else:
                self.status.showMessage(tr('새 {kind} v{latest} 사용 가능 — 도움말 → 업데이트 확인').format(kind=kind, latest=latest), 6000)

    def _start_bg_update_download(self, info, force=False):
        """260618-24: 한가할 때 백그라운드로 업데이트 zip 을 미리 받아 둠(설정 폴더 캐시).
        261008-17: 업그레이드 직전 앞쪽 받기(`_ensure_update_zip`)도 이 함수를 쓴다(force=True)."""
        from viewer import updater
        # 261108-13(릴리스 SOT §14.5 U24): 설치 프로그램으로 깐 판은 설치본을 받는다(받은 뒤 조용히 실행), 아니면 종전 zip
        kind = self._update_kind(info)
        url = info.get("setup_url") if kind == "setup" else info.get("asset_url")
        ver = info.get("version", "")
        if not url:
            return
        dest = updater.pending_path(kind)
        verf = dest.with_suffix(".ver")
        try:
            if dest.exists() and verf.exists() and verf.read_text(encoding="utf-8").strip() == ver:
                self._pending_zip = str(dest)       # 이미 받아둔 동일 버전
                return
        except Exception:
            pass
        if getattr(self, "_dl_in_progress", False):
            return
        # 인덱싱 중이면(바쁨) 잠시 후 재시도 — 사용자가 기다리는 앞쪽 받기(force)는 미루지 않는다
        if getattr(self, "_index_workers", None) and not force:
            QTimer.singleShot(15000, lambda: self._start_bg_update_download(info))
            return
        import threading as _th
        self._dl_cancel = _th.Event()          # 261008-17: 앞쪽 받기의 '취소'
        cancel = self._dl_cancel
        self._dl_in_progress = True
        import threading
        sig = self._update_sig

        def work():
            import shutil
            out = ""
            try:
                # 260628(A): 릴리스에 '<자산>.sha256' 이 있으면 받은 zip 을 검증(불일치=폐기).
                # 261108-13(U24): 설치본은 해시가 **반드시** 있어야 받는다(관리자 권한으로 돌리는 파일)
                if kind == "setup":
                    exp = updater.fetch_sha256(info.get("setup_sha_url", ""))
                    if not exp:
                        raise RuntimeError("no setup sha256")
                else:
                    exp = updater.fetch_expected_sha256(info)
                def prog(done, total):
                    try:
                        sig.dl_progress.emit(int(done), int(total))
                    except Exception:
                        pass
                    return not cancel.is_set()             # False → download_asset 이 멈춘다
                path = updater.download_asset(url, progress=prog, expect_sha256=exp)
                if path:
                    try:
                        if exp:      # 종료 시 설치 단계에서 재검증할 수 있게 사이드카 저장
                            dest.with_suffix(".sha256").write_text(exp, encoding="utf-8")
                    except Exception:
                        pass
                    try:
                        if dest.exists():
                            dest.unlink()
                    except Exception:
                        pass
                    shutil.move(path, str(dest))
                    verf.write_text(ver, encoding="utf-8")
                    out = str(dest)
            except Exception:
                out = ""
            try:
                sig.dl_done.emit(out)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_bg_dl_done(self, path):
        self._dl_in_progress = False
        if path:
            self._pending_zip = path
            self.status.showMessage(tr("업데이트 다운로드 완료 — 종료 시 설치할 수 있습니다."), 5000)

    def _update_kind(self, info) -> str:
        """261108-13(U24): 'setup' 또는 'zip' — 한 업데이트 안에서는 한 번 정한 길을 그대로 쓴다(레지스트리는 한 번만 읽는다)."""
        from viewer import updater
        key = str((info or {}).get("version", ""))
        got = getattr(self, "_update_kind_cache", None)
        if got and got[0] == key:
            return got[1]
        try:
            kind = updater.update_kind(info)
        except Exception:
            kind = "zip"
        self._update_kind_cache = (key, kind)
        return kind

    def _update_zip_ready(self, info) -> bool:
        """받아 둔 zip(또는 설치본)이 **이 버전** 것인가(.ver 사이드카)."""
        from viewer import updater
        dest = updater.pending_path(self._update_kind(info))
        try:
            return (dest.is_file() and dest.with_suffix(".ver").is_file()
                    and dest.with_suffix(".ver").read_text(encoding="utf-8").strip()
                    == str(info.get("version", "")))
        except Exception:
            return False

    def _ensure_update_zip(self, info) -> bool:
        """261008-17(마스터 §14.5 U13): 업그레이드 **전에** 앱 안에서 받고 검증까지 끝낸다.
        진행 창(취소 가능)을 띄우고, 백그라운드 받기가 이미 돌고 있으면 그것을 기다린다.
        받아 둔 같은 버전이 있으면 바로 True. 실패·취소면 False(호출자는 닫지 않는다)."""
        from viewer import updater
        from PyQt6.QtCore import QEventLoop, Qt as _Qt
        from PyQt6.QtWidgets import QProgressDialog, QPushButton
        if self._update_zip_ready(info):
            self._pending_zip = str(updater.pending_path(self._update_kind(info)))
            return True
        sig = self._update_sig
        loop = QEventLoop()
        result = {"path": ""}
        dlg = QProgressDialog(tr("업데이트 파일을 받는 중…"), tr("취소"), 0, 0, self)
        dlg.setWindowTitle(tr("업데이트"))
        dlg.setWindowModality(_Qt.WindowModality.ApplicationModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        # 화면 디자인 SOT §2.7: 취소 단추가 기본 단추면 Enter 한 번에 받기가 취소된다.
        cancel_btn = QPushButton(tr("취소"))
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        dlg.setCancelButton(cancel_btn)

        def on_prog(done, total):
            if total > 0:
                dlg.setMaximum(100)
                dlg.setValue(min(100, int(done * 100 / total)))
                dlg.setLabelText(tr("업데이트 파일을 받는 중… %.1f / %.1f MB")
                                 % (done / 1048576.0, total / 1048576.0))

        def on_done(path):
            result["path"] = path or ""
            loop.quit()

        def on_cancel():
            ev = getattr(self, "_dl_cancel", None)
            if ev is not None:
                ev.set()
            dlg.setLabelText(tr("취소하는 중…"))

        sig.dl_progress.connect(on_prog)
        sig.dl_done.connect(on_done)
        dlg.canceled.connect(on_cancel)
        try:
            dlg.show()
            if not getattr(self, "_dl_in_progress", False):
                self._start_bg_update_download(info, force=True)
            if getattr(self, "_dl_in_progress", False):
                loop.exec()
        finally:
            # ★ QProgressDialog 는 close() 할 때도 canceled 를 낸다 — 먼저 끊지 않으면
            #   '사용자가 취소함' 으로 기록돼 받기 실패 안내가 사라진다(실측).
            for s_, f_ in ((dlg.canceled, on_cancel), (sig.dl_progress, on_prog),
                           (sig.dl_done, on_done)):
                try:
                    s_.disconnect(f_)
                except Exception:
                    pass
            dlg.close()
        ok = bool(result["path"]) and self._update_zip_ready(info)
        if ok:
            self._pending_zip = result["path"]
        else:
            ev = getattr(self, "_dl_cancel", None)
            if not (ev is not None and ev.is_set()):
                QMessageBox.warning(self, tr("업데이트"),
                                    tr("업데이트 파일을 받지 못했습니다(연결·무결성 검증 실패).\n"
                                    "프로그램은 닫지 않았습니다. 잠시 뒤 다시 시도해 주세요."))
        return ok

    def _upgrade_now(self):
        """261008-17(U13): 받기 → 닫기 요청. 설치 도우미는 **닫는 길(closeEvent)에서** 시작한다 —
        편집 저장 확인에서 사용자가 닫기를 취소하면 업그레이드도 시작하지 않게."""
        info = getattr(self, "_pending_update", None)
        if not info or not self._ensure_update_zip(info):
            return
        self._upgrade_requested = True
        if not self.close():                   # 닫기를 취소했다 → 업그레이드도 취소
            self._upgrade_requested = False

    def _begin_upgrade(self) -> bool:
        """260618-24: 업그레이드 시작 — 받아둔 zip 있으면 사용, 없으면 설치 도우미가 다운로드.
        성공 시 _updating 플래그(종료 시 재질문 방지) 설정. 호출 후 앱을 종료해야 함."""
        from viewer import updater
        info = getattr(self, "_pending_update", None)
        if not info:
            return False
        z = getattr(self, "_pending_zip", None)
        zp = z if (z and os.path.isfile(z)) else None
        if self._update_kind(info) == "setup":
            return self._begin_setup_upgrade(info, zp)
        # 260628(A): 무결성 해시를 설치 도우미에 전달 — 승격(UAC) 인스턴스가 **압축 해제
        #   직전 다시 검증**해, 승인 대기 중 zip 바꿔치기(TOCTOU/권한상승)를 차단한다.
        sha = ""
        try:
            if zp:                                   # 미리 받아둔 zip → 사이드카 우선
                side = updater.pending_zip_path().with_suffix(".sha256")
                if side.exists():
                    sha = side.read_text(encoding="utf-8").strip()
            if not sha:
                sha = updater.fetch_expected_sha256(info)
        except Exception:
            sha = ""
        # 260628-12(U8): 릴리스가 제공하면 **정식 파일목록**을 함께 넘겨, 새 버전에서
        #   없어진 파일을 설치 도우미가 지운다. 없으면 빈 값 → 정리 생략(안전 실패).
        man = ""
        try:
            man = updater.fetch_manifest(info)
        except Exception:
            man = ""
        ok = updater.apply_update(zip_path=zp, url=info.get("asset_url", ""), sha256=sha,
                                  manifest_path=man)
        if ok:
            self._updating = True
        return ok

    def _begin_setup_upgrade(self, info, setup_path) -> bool:
        """261108-13(릴리스 SOT §14.5 U24): 받아 둔 설치본을 조용히 실행. 그 전에 **다른 PolyPDF 창을 닫는다**(U1·U2 —
        종전 PowerShell 도우미가 하던 일: 정상 종료 요청 → 최대 60초 기다림 → 남으면 강제로 닫을지 묻기).
        설치본은 이 앱이 끝나기를 기다린 뒤(/WAITPID) 남은 PolyPDF(도우미)를 닫고 옛 판을 지우고 깐다."""
        from viewer import updater
        from viewer.i18n import language
        self._upgrade_declined = False
        if not setup_path:
            return False
        if not self._close_other_windows():
            self._upgrade_declined = True
            QMessageBox.information(self, tr("업데이트"), tr("업데이트를 취소했습니다. 다음에 다시 시도할 수 있습니다."))
            return False
        sha = ""
        try:
            side = updater.pending_path("setup").with_suffix(".sha256")
            if side.exists():
                sha = side.read_text(encoding="utf-8").strip()
        except Exception:
            sha = ""
        try:
            lang = language()
        except Exception:
            lang = ""
        # 실행 직전 해시(340MB, 약 0.5초+디스크)는 배경에서 — 메인은 이벤트를 돌리며 기다린다(응답성 SOT)
        import threading
        from PyQt6.QtCore import QEventLoop
        res = {"ok": False}
        loop = QEventLoop()

        def work():
            try:
                res["ok"] = bool(updater.apply_setup(setup_path, sha, lang))
            except Exception:
                res["ok"] = False
        th = threading.Thread(target=work, daemon=True)
        th.start()
        while th.is_alive():
            QTimer.singleShot(50, loop.quit)
            loop.exec()
        ok = res["ok"]
        if ok:
            self._updating = True
        return ok

    _OTHER_WIN_WAIT_S = 60.0                  # 저장 여부 응답 시간 포함(종전 도우미와 같다)

    def _close_other_windows(self) -> bool:
        """다른 PolyPDF 창에 닫기를 요청하고 기다린다. 다 닫혔거나 사용자가 '강제로 닫고 계속' 이면 True, 취소면 False."""
        from viewer import updater
        import time
        from PyQt6.QtCore import QEventLoop
        wait_s = float(self._OTHER_WIN_WAIT_S)
        wins = updater.other_windows()
        if not wins:
            return True
        updater.request_close(wins)
        from PyQt6.QtWidgets import QProgressDialog
        dlg = QProgressDialog(tr("다른 PolyPDF 창을 닫는 중... ({n}개)").format(n=len(wins)), "", 0, 0, self)
        dlg.setWindowTitle(tr("PolyPDF 업데이트"))
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.show()
        loop = QEventLoop()
        t_end = time.monotonic() + wait_s
        left = wins
        try:
            while time.monotonic() < t_end:
                left = updater.other_windows()
                if not left:
                    break
                dlg.setLabelText(tr("다른 PolyPDF 창이 닫히기를 기다리는 중... ({n}개 남음)").format(n=len(left)))
                QTimer.singleShot(400, loop.quit)
                loop.exec()
        finally:
            dlg.close()
        if not left:
            return True
        ans = QMessageBox.warning(
            self, tr("PolyPDF 업데이트"),
            tr("다른 PolyPDF 창 {n}개가 아직 열려 있습니다.\n"
               "열린 창이 파일을 잠그고 있어, 이대로 진행하면 일부 파일이 교체되지 않아 "
               "업데이트가 실패합니다.\n\n"
               "[예] 남은 창을 강제로 닫고 계속\n"
               "[아니오] 업데이트 취소 (저장하지 않은 작업이 있으면 이쪽을 선택하세요)").format(n=len(left)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return ans == QMessageBox.StandardButton.Yes       # 예 → 설치본이 남은 PolyPDF 를 닫는다(PrepareToInstall)

    # ── 구성요소 설치 (마스터 §14.5 U16, 261107-11 — 확인·내려받기는 배경, 응답성 SOT §4.4) ──────────
    def _comp_specs(self):
        from viewer import components
        return {"ffmpeg": (tr("녹화 (ffmpeg)"), components.ffmpeg_installed, components.install_ffmpeg),
                "tess": ("OCR (Tesseract)", components.tesseract_installed, components.install_tesseract),
                # 261108-28(영상·음성 SOT §1.10): 자연 음성 모델 123MB — 고정 URL·SHA-256, 풀기까지 배경
                "voice": (tr("자연 음성 (한국어·영어)"), components.voice_installed, components.install_voice)}

    def _open_components_installer(self, *_a, parent=None):
        """260618-12: 녹화(ffmpeg)·OCR(Tesseract) 구성요소를 릴리스에서 설치 폴더로 받기.
        261107-11: 모달 아님·하나만. 확인·내려받기는 배경 워커 — 받는 중 창을 닫아도 계속(작업 창에 남는다).
        261108-32(디자인 SOT §2.14 '모달 위 창'): 환경설정(모달)에서 열면 `parent`=그 창 — 메인을 부모로 띄우면 모달인
        환경설정이 다시 앞으로 와 이 창이 뒤에 숨었다(사용자 보고). 메뉴에서 열면 종전처럼 메인 창(인자 없음)."""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                      QPushButton, QProgressBar)
        owner = parent if parent is not None else self
        dlg = getattr(self, "_comp_dlg", None)
        if dlg is not None:
            try:
                if dlg.parent() is not owner:              # 이미 열린 창 — 지금 부르는 창 위로 옮겨 단다
                    dlg.setParent(owner, dlg.windowFlags())
                dlg.show(); dlg.raise_(); dlg.activateWindow()
                return
            except RuntimeError:
                self._comp_dlg = None
        dlg = QDialog(owner)
        dlg.setObjectName("componentsDialog")
        dlg.setWindowTitle(tr("구성요소 설치 (녹화·OCR)"))
        dlg.resize(460, 200)
        v = QVBoxLayout(dlg)
        # 261109-3(릴리스 SOT §14.5 U16): 설치본·휴대용에는 셋 다 들어 있다 — 이 창은 빠졌거나 손상됐을 때 다시 받는 길
        v.addWidget(QLabel(tr("설치본에는 세 구성요소가 모두 들어 있습니다. 빠졌거나 손상됐을 때 설치 폴더에 다시 내려받습니다.\n"
                           "(녹화=ffmpeg, OCR=Tesseract, 자연 음성=Supertonic 3 약 123MB · 재시작 불필요)")))
        dlg._rows = {}
        for key, (title, _inst, _fn) in self._comp_specs().items():
            row = QHBoxLayout()
            st, btn = QLabel(tr("확인 중…")), QPushButton(tr("다운로드"))
            btn.setEnabled(False)
            row.addWidget(QLabel(title), 1)
            row.addWidget(st)
            row.addWidget(btn)
            v.addLayout(row)
            dlg._rows[key] = (st, btn)
            btn.clicked.connect(lambda _=False, k=key: self._comp_button(k))
        dlg._bar = QProgressBar(); dlg._bar.setRange(0, 100); dlg._bar.setVisible(False)
        v.addWidget(dlg._bar)
        v.addStretch(1)
        close = QPushButton(tr("닫기")); close.clicked.connect(dlg.close)
        h = QHBoxLayout(); h.addStretch(1); h.addWidget(close)
        v.addLayout(h)
        self._comp_dlg = dlg
        self._comp_check()
        dlg.show()

    def _comp_check(self):
        """설치 여부를 배경에서(tesseract --version 실행 — 메인에서 부르면 선다)."""
        from viewer.workers import run_in_thread
        w = ComponentStatusWorker({k: s[1] for k, s in self._comp_specs().items()})
        w.done.connect(self._comp_status)
        run_in_thread(w, self.__dict__.setdefault("_comp_keep", []))

    def _comp_dialog(self):
        dlg = getattr(self, "_comp_dlg", None)
        try:
            return dlg if (dlg is not None and dlg.isVisible()) else None
        except RuntimeError:
            self._comp_dlg = None
            return None

    def _comp_status(self, res: dict):
        from viewer import theme
        from viewer.widgets import icons
        dlg = self._comp_dialog()
        if dlg is None:
            return
        dark = theme.is_dark()
        busy = getattr(self, "_comp_worker", None)
        for key, (st, btn) in dlg._rows.items():
            ok = bool(res.get(key))
            st.setText(tr("설치됨 ✓") if ok else tr("미설치"))
            st.setStyleSheet("color:%s;" % (icons.OK_GREEN[dark] if ok else icons.ACCENT["stop"][dark]))
            if busy is not None and busy.key == key:
                btn.setText(tr("중단")); btn.setEnabled(True)
            else:
                btn.setText(tr("재설치") if ok else tr("다운로드")); btn.setEnabled(busy is None)
        self._comp_show_bar(dlg)                           # 261108-32 덧붙임: 다시 열어도 지금 단계를 보인다

    def _comp_button(self, key: str):
        w = getattr(self, "_comp_worker", None)
        if w is not None:
            if w.key == key:
                w.request_cancel()                     # [중단]
            return
        self._comp_start(key)

    def _comp_start(self, key: str):
        from viewer import components
        from viewer.workers import run_in_thread
        title, _inst, fn = self._comp_specs()[key]
        repo = (self._prefs.get("update_repo") or "").strip() or components.DEFAULT_REPO
        w = ComponentInstallWorker(key, title, fn, repo)
        self._comp_worker = w
        self._comp_last = (0, "")
        jid = "components:" + key
        w.jid = jid
        self.job_add(jid, tr("구성요소 설치: {title}").format(title=title), cancel=w.request_cancel)
        w.progress.connect(self._comp_progress)
        w.done.connect(self._comp_done)
        dlg = self._comp_dialog()
        if dlg is not None:
            dlg._bar.setValue(0); dlg._bar.setVisible(True)
            for k, (_st, b) in dlg._rows.items():
                b.setEnabled(k == key)
                if k == key:
                    b.setText(tr("중단"))
        run_in_thread(w, self.__dict__.setdefault("_comp_keep", []))

    def _comp_progress(self, pct: int, msg: str):
        w = getattr(self, "_comp_worker", None)
        if w is not None:
            self.job_progress(w.jid, msg)
        self._comp_last = (pct, msg)                   # 261108-32 덧붙임: 창을 다시 열 때 지금 단계를 그대로 보인다
        dlg = self._comp_dialog()
        if dlg is not None:
            self._comp_show_bar(dlg)

    def _comp_show_bar(self, dlg):
        """진행 막대 — 받는 중이면 보이고 퍼센트·단계 글(예 '압축 푸는 중… 40%')을, 아니면 숨긴다."""
        busy = getattr(self, "_comp_worker", None) is not None
        dlg._bar.setVisible(busy)
        if not busy:
            return
        pct, msg = getattr(self, "_comp_last", (0, ""))
        if pct >= 0:
            dlg._bar.setValue(pct)
        dlg._bar.setFormat(msg or "%p%")

    def _comp_done(self, key: str, ok: bool, info: str, cancelled: bool):
        w = getattr(self, "_comp_worker", None)
        self._comp_worker = None
        if w is not None:
            self.job_done(w.jid)
        title = self._comp_specs()[key][0]
        if cancelled:
            text = tr("{title} 내려받기를 중단했습니다 — 아무것도 바꾸지 않았습니다.").format(title=title)
        elif ok:
            text = tr('{title} 설치 완료.').format(title=title)
        else:
            text = tr('{title} 설치 실패:\n{info}').format(title=title, info=info)
        dlg = self._comp_dialog()
        if dlg is None:                                # 창을 닫은 뒤 끝남 — 상태 표시줄로 알린다
            self.status.showMessage(text.replace("\n", " "), 8000)
            self._comp_notify(key, ok)
            return
        dlg._bar.setVisible(False)
        self.status.showMessage(text.replace("\n", " "), 8000)
        if not ok and not cancelled:
            QMessageBox.warning(dlg, tr("구성요소 설치"), text)
        self._comp_check()
        self._comp_notify(key, ok)

    def _comp_notify(self, key: str, ok: bool):
        """261108-32: 설치가 끝나면 듣는 쪽(환경설정 '읽기 음성' 의 설치 상태 글 등)에 알린다. 지워진 위젯은 빼낸다."""
        keep = []
        for fn in list(getattr(self, "_comp_listeners", []) or []):
            try:
                fn(key, ok)
                keep.append(fn)
            except RuntimeError:
                pass
        self._comp_listeners = keep


class ComponentStatusWorker(QObject):
    """구성요소 설치 여부(배경) — `tesseract_installed` 는 `tesseract --version` 을 실행한다(응답성 SOT §4.4)."""
    done = pyqtSignal(dict)
    finished = pyqtSignal()

    def __init__(self, checks: dict):
        super().__init__()
        self.checks = dict(checks)

    def request_cancel(self):
        pass

    def run(self):
        out = {}
        try:
            for k, fn in self.checks.items():
                try:
                    out[k] = bool(fn())
                except Exception:
                    out[k] = False
            self.done.emit(out)
        finally:
            self.finished.emit()


class ComponentInstallWorker(QObject):
    """구성요소 내려받기·설치(배경) — progress(퍼센트, 글), done(키, 성공, 정보, 중단됨). [중단] 은 다음 조각에서 멈춘다."""
    progress = pyqtSignal(int, str)
    done = pyqtSignal(str, bool, str, bool)
    finished = pyqtSignal()

    def __init__(self, key: str, title: str, install_fn, repo: str):
        super().__init__()
        self.key, self.title, self.install_fn, self.repo = key, title, install_fn, repo
        self._cancel = False
        self._last = -1

    def request_cancel(self):
        self._cancel = True

    def _prog(self, done, total):
        if self._cancel:
            return False                               # components._download 가 None 을 돌려준다 — 아무것도 쓰지 않는다
        if done < 0:
            return True                                # 중단 물음만(풀기 단계, components.install_voice)
        pct = int(done * 100 / total) if total > 0 else -1
        if pct != self._last:
            self._last = pct
            mb = done / 1048576.0
            self.progress.emit(pct, ("%d%% · %.0f MB" % (pct, mb)) if pct >= 0 else ("%.0f MB" % mb))
        return True

    def _phase(self, text: str, pct: int = -1):
        """261108-32 덧붙임: 내려받기 뒤 단계(무결성 확인·풀기·파일 확인)를 알린다 — 100% 에서 멈춘 듯 보이지 않게."""
        self.progress.emit(int(pct), str(text))

    def run(self):
        try:
            def prog(done, total):
                return self._prog(done, total)
            prog.phase = self._phase
            try:
                ok, info = self.install_fn(self.repo, prog)
            except Exception as e:
                ok, info = False, str(e)
            stopped = self._cancel and not ok              # 다 받은 뒤 누른 중단은 늦었다 — 이미 설치됐다
            self.done.emit(self.key, bool(ok), str(info or ""), bool(stopped))
        finally:
            self.finished.emit()
