"""261017(가상 프린터 SOT §4.6): 도구 메뉴 '가상 프린터(PolyPDF) 설치·제거…' 창.

- 상태(`--vprinter check`)는 배경에서 읽는다(스풀러 조회). 설치·수리·제거는 **같은 설치 도구**를 UAC 로 승격해
  숨긴 창으로 돌리고, 끝날 때까지 배경에서 기다린다(응답성 SOT §4 — 창이 멈추지 않는다).
- 받은 문서 저장 설정 셋: 저장 폴더 기본(원래 파일 폴더/기본 저장 폴더), 기본 저장 폴더, 흑백으로 저장(§4.3·§4.8 — 저장 창은 없다).
"""
from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QRadioButton, QVBoxLayout)

from viewer.i18n import tr

ERROR_CANCELLED = 1223                      # UAC 에서 '아니요'
STILL_RUNNING = -2                          # 기다리는 시간이 넘음 — 설치 도구는 아직 돌고 있다


def vprinter_command(action: str) -> tuple:
    """(실행 파일, 인자) — 설치본은 PolyPDF.exe, 개발 실행은 python main.py."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--vprinter " + action
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "main.py")
    return sys.executable, '"%s" --vprinter %s' % (main, action)


def run_elevated(action: str, timeout_ms: int = 180000) -> int:
    """설치 도구를 관리자로(UAC) 숨긴 창에서 — 종료 코드. 배경 스레드에서 부른다."""
    import win32con
    import win32event
    import win32process
    from win32com.shell import shell, shellcon
    exe, args = vprinter_command(action)
    try:
        info = shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS, lpVerb="runas", lpFile=exe,
                                    lpParameters=args, nShow=win32con.SW_HIDE)
    except Exception as e:                               # noqa: BLE001 — UAC 취소는 pywintypes.error(1223)
        return getattr(e, "winerror", None) or (e.args[0] if e.args else 1)
    h = info["hProcess"]
    try:
        # 261017-18 점검: 기다리는 시간이 넘으면 종료 코드는 259(STILL_ACTIVE) — '실패' 가 아니라 '아직 진행 중'
        if win32event.WaitForSingleObject(h, timeout_ms) == win32event.WAIT_TIMEOUT:
            return STILL_RUNNING
        return win32process.GetExitCodeProcess(h)
    finally:
        h.Close()


def read_state() -> dict:
    """상태(일반 권한) — 설치 도구와 같은 판정."""
    from viewer import vprinter
    return vprinter.state()


class _Job(QObject):
    finished = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            out = self._fn()
        except Exception as e:                           # noqa: BLE001
            out = e
        self.finished.emit(out)


class VPrinterDialog(QDialog):
    def __init__(self, parent=None, prefs: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("가상 프린터 (PolyPDF)"))
        self.resize(560, 360)
        self._keep = []
        self._prefs = dict(prefs or {})
        v = QVBoxLayout(self)
        v.addWidget(QLabel(tr("다른 프로그램에서 'PolyPDF' 프린터로 인쇄하면 PDF 로 저장하고 PolyPDF 에서 엽니다.")))
        self.lbl_state = QLabel(tr("상태 확인 중…"))
        self.lbl_state.setWordWrap(True)
        v.addWidget(self.lbl_state)
        row = QHBoxLayout()
        self.btn_install = QPushButton(tr("설치"))
        self.btn_remove = QPushButton(tr("제거"))
        self.btn_install.clicked.connect(lambda: self._run("install"))
        self.btn_remove.clicked.connect(lambda: self._run("remove"))
        for b in (self.btn_install, self.btn_remove):
            b.setEnabled(False)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)

        gb = QGroupBox(tr("받은 문서 저장"))
        g = QVBoxLayout(gb)
        self._kind = QButtonGroup(self)
        self.rb_orig = QRadioButton(tr("원래 파일이 있는 폴더(찾지 못하면 기본 저장 폴더)"))
        self.rb_default = QRadioButton(tr("기본 저장 폴더"))
        for rb in (self.rb_orig, self.rb_default):
            self._kind.addButton(rb)
            g.addWidget(rb)
        (self.rb_default if self._prefs.get("kind") == "default" else self.rb_orig).setChecked(True)
        drow = QHBoxLayout()
        drow.addWidget(QLabel(tr("기본 저장 폴더")))
        from viewer.vprinter_recv import default_save_dir
        self.ed_dir = QLineEdit(self._prefs.get("default_dir") or default_save_dir())
        drow.addWidget(self.ed_dir, 1)
        b = QPushButton(tr("찾아보기…"))
        b.clicked.connect(self._browse)
        drow.addWidget(b)
        g.addLayout(drow)
        self.chk_gray = QCheckBox(tr("흑백으로 저장"))
        self.chk_gray.setChecked(self._prefs.get("color") == "gray")
        g.addWidget(self.chk_gray)
        g.addWidget(QLabel(tr("저장 창 없이 바로 저장하고 엽니다. 쪽 범위·여러 쪽 모아 찍기는 인쇄하는 프로그램의 인쇄 창에서 고르세요.")))
        v.addWidget(gb)
        v.addStretch(1)
        close = QPushButton(tr("닫기"))
        close.clicked.connect(self.accept)
        crow = QHBoxLayout()
        crow.addStretch(1)
        crow.addWidget(close)
        v.addLayout(crow)
        self._refresh()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("기본 저장 폴더"), self.ed_dir.text())
        if d:
            self.ed_dir.setText(d)

    def result_prefs(self) -> dict:
        p = dict(self._prefs)
        p.update({"kind": "default" if self.rb_default.isChecked() else "original",
                  "default_dir": self.ed_dir.text().strip(), "color": "gray" if self.chk_gray.isChecked() else "color"})
        p.pop("skip", None)
        return p

    # ── 배경 일 ─────────────────────────────────────────────────────────
    def _bg(self, fn, done):
        from viewer.workers import run_in_thread
        j = _Job(fn)
        j.finished.connect(done)
        run_in_thread(j, self._keep)

    def _refresh(self):
        self._bg(read_state, self._show_state)

    def _show_state(self, st):
        if isinstance(st, Exception):
            self.lbl_state.setText(tr("상태를 읽지 못했습니다: {err}").format(err=st))
            return
        why = {"arm64": tr("ARM64 Windows 에서는 쓸 수 없습니다."),
               "x86": tr("32비트 Windows 에서는 쓸 수 없습니다."),
               "wpp": tr("'보호된 인쇄 모드' 가 켜져 있어 쓸 수 없습니다."),
               "no-pscript": tr("Windows 의 PostScript 드라이버가 없어 쓸 수 없습니다.")}.get(st.get("support"))
        if why:
            self.lbl_state.setText(why)
            self.btn_install.setEnabled(False)
            self.btn_remove.setEnabled(bool(st.get("printer") or st.get("monitor")))
            return
        ok = all(st.get(k) for k in ("monitor", "dll", "port", "driver", "printer"))
        if ok:
            self.lbl_state.setText(tr("설치됨 ✓ — 프린터 'PolyPDF'"))
            self.btn_install.setText(tr("수리"))
        elif any(st.get(k) for k in ("monitor", "dll", "port", "driver", "printer")):
            self.lbl_state.setText(tr("일부만 설치됨 — '수리' 를 누르세요."))
            self.btn_install.setText(tr("수리"))
        else:
            self.lbl_state.setText(tr("설치되지 않음"))
            self.btn_install.setText(tr("설치"))
        self.btn_install.setEnabled(True)
        self.btn_remove.setEnabled(ok or any(st.get(k) for k in ("monitor", "dll", "port", "driver", "printer")))

    def _run(self, action: str):
        if not getattr(sys, "frozen", False) and action == "install":
            from viewer.vprinter import default_source_dir, MONITOR_DLL
            if not os.path.exists(os.path.join(default_source_dir(), "bin", MONITOR_DLL)):
                self.lbl_state.setText(tr("개발 실행에는 포트 모니터(printer\\bin)가 없습니다 — 빌드된 PolyPDF 에서 설치하세요."))
                return
        for b in (self.btn_install, self.btn_remove):
            b.setEnabled(False)
        self.lbl_state.setText(tr("관리자 권한으로 진행하는 중… (Windows 확인 창이 뜨면 '예')"))
        self._bg(lambda: run_elevated(action), lambda rc: self._done(action, rc))

    def _done(self, action, rc):
        msg = {0: tr("완료했습니다."), ERROR_CANCELLED: tr("취소했습니다."),
               STILL_RUNNING: tr("아직 진행 중입니다 — 잠시 뒤 이 창을 다시 열어 상태를 보세요."),
               2: tr("이 PC 에서는 쓸 수 없습니다."), 3: tr("이 배포본에는 가상 프린터 구성요소가 없습니다.")}
        self._last_msg = msg.get(rc if isinstance(rc, int) else -1,
                                 tr("실패했습니다(코드 {rc}) — 기록: {log}").format(
                                     rc=rc, log=os.path.join(os.environ.get("ProgramData", ""), "PolyPDF", "printer.log")))
        self.lbl_state.setText(self._last_msg)
        self._bg(read_state, self._show_state_after)

    def _show_state_after(self, st):
        self._show_state(st)
        self.lbl_state.setText(self._last_msg + "  " + self.lbl_state.text())
