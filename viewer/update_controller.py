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

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

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
                self, "업데이트 저장소 설정",
                "GitHub 저장소를 'OWNER/REPO' 형식으로 입력하세요:", text=repo)
            if not ok or not updater.valid_repo((txt or "").strip()):
                return
            repo = txt.strip()
            self._prefs["update_repo"] = repo
            try:
                self._save_settings_now()
            except Exception:
                pass
        if manual:
            self.status.showMessage("업데이트 확인 중…", 3000)
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
            info = updater.check_latest(repo, channel=channel)
            try:
                sig.done.emit(info, bool(manual))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_update_result(self, info, manual):
        from viewer import updater
        cur = updater.current_version()
        if not info:
            if manual:
                QMessageBox.information(
                    self, "업데이트",
                    "업데이트 정보를 가져오지 못했습니다.\n인터넷 연결과 저장소 설정을 확인하세요.")
            return
        latest = info.get("version") or ""
        if not updater.is_newer(latest, cur):
            if manual:
                QMessageBox.information(self, "업데이트", f"현재 최신 버전입니다. (v{cur})")
            return
        if not updater.is_frozen():
            if manual:
                QMessageBox.information(
                    self, "업데이트",
                    f"새 버전 v{latest} 이 있습니다(현재 v{cur}).\n"
                    f"개발(소스) 실행 중에는 자동 교체가 적용되지 않습니다.\n{info.get('html_url','')}")
            return
        if not info.get("asset_url"):
            if manual:
                QMessageBox.information(
                    self, "업데이트",
                    f"새 버전 v{latest} 이 있으나 배포 zip 자산을 찾지 못했습니다.\n{info.get('html_url','')}")
            return
        # 260618-24: 새 버전 인지(종료 시 업그레이드 프롬프트용)
        self._pending_update = info
        # 260618-36: 베타(테스트) 릴리스면 프롬프트에 명시 — 사용자가 알고 동의하게.
        is_beta = updater.is_prerelease_tag(info.get("tag", ""))
        kind = "베타(테스트) 버전" if is_beta else "버전"
        if manual:
            # D: 확인 → 종료하고 설치(설치 도우미가 파일 없으면 다운로드)
            notes = (info.get("notes") or "").strip()
            if len(notes) > 800:
                notes = notes[:800] + " …"
            title = "베타 업데이트" if is_beta else "업데이트"
            ret = QMessageBox.question(
                self, title,
                f"새 {kind}이 있습니다.\n\n현재: v{cur}\n최신: v{latest}\n\n"
                + (notes + "\n\n" if notes else "")
                + ("이 버전은 테스트(베타)입니다. " if is_beta else "")
                + "프로그램을 종료하고 설치합니다. 계속할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if ret == QMessageBox.StandardButton.Yes:
                if self._begin_upgrade():
                    self.close()
                else:
                    QMessageBox.warning(self, "업데이트", "업데이트 적용을 시작하지 못했습니다.")
        else:
            # C: 시작 시 자동 확인 — 설정 켜져 있으면 백그라운드로 미리 받아둠
            if self._prefs.get("auto_download_update", True):
                self._start_bg_update_download(info)
            else:
                self.status.showMessage(f"새 {kind} v{latest} 사용 가능 — 도움말 → 업데이트 확인", 6000)

    def _start_bg_update_download(self, info):
        """260618-24: 한가할 때 백그라운드로 업데이트 zip 을 미리 받아 둠(설정 폴더 캐시)."""
        from viewer import updater
        url = info.get("asset_url")
        ver = info.get("version", "")
        if not url:
            return
        dest = updater.pending_zip_path()
        verf = dest.with_suffix(".ver")
        try:
            if dest.exists() and verf.exists() and verf.read_text(encoding="utf-8").strip() == ver:
                self._pending_zip = str(dest)       # 이미 받아둔 동일 버전
                return
        except Exception:
            pass
        if getattr(self, "_dl_in_progress", False):
            return
        # 인덱싱 중이면(바쁨) 잠시 후 재시도
        if getattr(self, "_index_workers", None):
            QTimer.singleShot(15000, lambda: self._start_bg_update_download(info))
            return
        self._dl_in_progress = True
        import threading
        sig = self._update_sig

        def work():
            import shutil
            out = ""
            try:
                # 260628(A): 릴리스에 '<자산>.sha256' 이 있으면 받은 zip 을 검증(불일치=폐기).
                exp = updater.fetch_expected_sha256(info)
                path = updater.download_asset(url, expect_sha256=exp)   # 임시폴더(진행 UI 없음)
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
            self.status.showMessage("업데이트 다운로드 완료 — 종료 시 설치할 수 있습니다.", 5000)

    def _begin_upgrade(self) -> bool:
        """260618-24: 업그레이드 시작 — 받아둔 zip 있으면 사용, 없으면 설치 도우미가 다운로드.
        성공 시 _updating 플래그(종료 시 재질문 방지) 설정. 호출 후 앱을 종료해야 함."""
        from viewer import updater
        info = getattr(self, "_pending_update", None)
        if not info:
            return False
        z = getattr(self, "_pending_zip", None)
        zp = z if (z and os.path.isfile(z)) else None
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

    def _open_components_installer(self):
        """260618-12: 녹화(ffmpeg)·OCR(Tesseract) 구성요소를 릴리스에서 설치 폴더로 받기."""
        from viewer import components
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                      QPushButton, QProgressBar)
        repo = (self._prefs.get("update_repo") or "").strip() or components.DEFAULT_REPO
        dlg = QDialog(self)
        dlg.setWindowTitle("구성요소 설치 (녹화·OCR)")
        dlg.resize(460, 200)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("필요한 기능의 구성요소를 설치 폴더에 내려받습니다.\n"
                           "(녹화=ffmpeg, OCR=Tesseract · 재시작 불필요)"))
        bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(0); bar.setVisible(False)

        rows = {}

        def make_row(key, title, installed_fn, install_fn):
            row = QHBoxLayout()
            lab = QLabel(title)
            st = QLabel()
            btn = QPushButton()
            row.addWidget(lab, 1)
            row.addWidget(st)
            row.addWidget(btn)
            v.addLayout(row)
            rows[key] = (st, btn)

            def refresh():
                ok = installed_fn()
                st.setText("설치됨 ✓" if ok else "미설치")
                st.setStyleSheet("color:#2a7;" if ok else "color:#c33;")
                btn.setText("재설치" if ok else "다운로드")

            def do():
                bar.setVisible(True); bar.setValue(0)
                for _s, b in rows.values():
                    b.setEnabled(False)

                def prog(done, total):
                    if total > 0:
                        bar.setValue(int(done * 100 / total))
                    QApplication.processEvents()
                    return True
                ok, info = install_fn(repo, prog)
                bar.setVisible(False)
                for _s, b in rows.values():
                    b.setEnabled(True)
                if ok:
                    QMessageBox.information(dlg, "구성요소 설치", f"{title} 설치 완료.")
                else:
                    QMessageBox.warning(dlg, "구성요소 설치", f"{title} 설치 실패:\n{info}")
                refresh()

            btn.clicked.connect(do)
            refresh()

        make_row("ffmpeg", "녹화 (ffmpeg)",
                 components.ffmpeg_installed, components.install_ffmpeg)
        make_row("tess", "OCR (Tesseract)",
                 components.tesseract_installed, components.install_tesseract)
        v.addWidget(bar)
        v.addStretch(1)
        close = QPushButton("닫기"); close.clicked.connect(dlg.accept)
        h = QHBoxLayout(); h.addStretch(1); h.addWidget(close)
        v.addLayout(h)
        dlg.exec()
