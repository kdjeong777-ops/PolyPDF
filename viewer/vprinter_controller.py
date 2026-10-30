"""261017(가상 프린터 SOT §4.1·§4.3·§4.4·§4.8): 가상 프린터로 받은 문서를 PDF 로 저장하고 여는 창 쪽 흐름 — MainWindow 믹스인.

- 창이 뜨면(`_vprinter_start`) 인쇄 받기 통로(`open_gather` 를 다른 이름으로)를 열고, 배경에서 사용자별 예약 작업을 맞추고,
  쌓인 PS 가 있으면 처리한다. 인쇄 뒤 예약 작업이 `PolyPDF.exe --printed` 를 띄우면 그 실행은 이 통로에 알리고 끝난다.
- 한 건씩: 변환(배경, `_run_merge_job`) → 도구 메뉴 설정(폴더·흑백)대로 저장(배경, 같은 이름이면 (1)(2)) → 연다.
  저장 창은 띄우지 않는다(261017-14 사용자 지시 — 인쇄 창으로 열지 않고 그냥 연다).
- 여는 곳: 저장 폴더를 이 창의 위·아래 책갈피창이 보고 있으면 그 목록에 더하고(`add_or_refresh_file`) `_open_saved_file` 로 연다,
  다른 PolyPDF 창이 보고 있으면 그 창에 넘기고(`InstanceLink.show_file`, 261031-4), 아무것도 안 열려 있으면 여기서 연다, 아니면 새 PolyPDF 창.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from viewer.i18n import tr

__all__ = ["VPrinterMixin", "print_server_name", "print_lock_path"]

PREF_KEY = "vprinter"                        # {"kind": original|default, "default_dir", "color": color|gray}


def print_server_name() -> str:
    from viewer.open_gather import server_name
    return server_name() + "-print"


def print_lock_path() -> str:
    from viewer.open_gather import lock_path
    p = lock_path()
    return (p[:-5] if p.endswith(".lock") else p) + "-print.lock"


class _StartWorker(QObject):
    """창이 뜬 뒤 한 번 — 프린터가 설치됐고 **설치본 창이면** 예약 작업을 맞추고, 쌓인 PS 수를 센다(스풀러·schtasks 조회라 배경)."""
    finished = pyqtSignal(dict)

    def run(self):
        out = {"installed": False, "pending": 0, "task": None}
        try:
            from viewer import vprinter_recv
            out["installed"] = _printer_installed()
            if out["installed"] and vprinter_recv.task_owner():      # 개발·휴대용·시험 프로필 창은 바꾸지 않는다(SOT §4.4)
                out["task"] = vprinter_recv.ensure_task()
            out["pending"] = len(vprinter_recv.pending_jobs())
        except Exception as e:                       # noqa: BLE001
            out["err"] = repr(e)
        self.finished.emit(out)


PRINTERS_KEY = "SYSTEM\\CurrentControlSet\\Control\\Print\\Printers\\"


def _printer_installed() -> bool:
    """프린터가 있는가 — **레지스트리로**(261017-19, 응답성 SOT §4.4). 종전 `win32print.EnumPrinters` 는 스풀러에 묻는 동안
    GIL 을 놓지 않아, 설치 직후(스풀러가 막 다시 시작해 느릴 때) 배경 스레드에서 불러도 창이 섰다(beta.289 설치 시험 T1 5.3초).
    로컬 프린터는 스풀러가 이 키에 적는다 — 창이 뜰 때마다 도는 길이라 스풀러를 깨우지 않는다."""
    from viewer import vprinter
    return vprinter._reg_exists(PRINTERS_KEY + vprinter.PRINTER_NAME)


class VPrinterMixin:
    """MainWindow 에 믹스인 — 가상 프린터 받기."""

    def _vprinter_start(self):
        self._vp_busy = False
        self._vp_failed = set()                    # 이 창에서 변환에 실패한 PS — 다시 시도하지 않는다(경고 되풀이 방지, 261017-18)
        self._vp_keep = []
        try:
            from viewer.open_gather import OpenGather
            g = OpenGather(name=print_server_name(), lock_file=print_lock_path(), parent=self)
            if g.claim():
                g.filesReceived.connect(lambda _f: QTimer.singleShot(0, self._vprinter_receive))
                self._vp_gather = g
        except Exception:
            pass
        try:
            from viewer.workers import run_in_thread
            w = _StartWorker()
            w.finished.connect(self._vprinter_started)
            run_in_thread(w, self._vp_keep)
        except Exception:
            pass

    def _vprinter_started(self, out: dict):
        if out.get("pending"):
            QTimer.singleShot(0, self._vprinter_receive)

    # ── 도구 메뉴(SOT §4.6) ─────────────────────────────────────────────
    def _open_vprinter_dialog(self):
        from viewer.widgets.vprinter_dialog import VPrinterDialog
        if not hasattr(self, "_vp_keep"):
            self._vp_keep = []
        dlg = VPrinterDialog(self, self._vprinter_prefs(), keep=self._vp_keep)   # 배경 일은 창보다 오래 사는 목록에(261017-19)
        dlg.exec()
        try:
            self._prefs[PREF_KEY] = dlg.result_prefs()
            self._save_settings_now()
        except Exception:
            pass
        dlg.deleteLater()                          # 열 때마다 창이 쌓이지 않게(261017-18)
        try:                                       # 방금 설치했으면 예약 작업을 맞춘다(배경)
            from viewer.workers import run_in_thread
            w = _StartWorker()
            w.finished.connect(self._vprinter_started)
            run_in_thread(w, getattr(self, "_vp_keep", []))
        except Exception:
            pass

    # ── 받기 ───────────────────────────────────────────────────────────
    def _vprinter_receive(self):
        """스풀 폴더의 PS 를 하나씩 저장한다. 처리 중에 또 오면 끝난 뒤 다시 본다(한 건이 끝날 때마다 폴더를 다시 읽는다).
        이 창에서 변환에 실패한 PS 는 건너뛴다 — 지우지 않고 다음 실행 때 한 번 더(SOT §4.3, 261017-18)."""
        if getattr(self, "_vp_busy", False):
            return
        self._vp_busy = True
        failed = getattr(self, "_vp_failed", set())
        try:
            from viewer import vprinter_recv as R
            seen = set()
            while True:
                jobs = [p for p in R.pending_jobs() if p not in seen and p not in failed]
                if not jobs:
                    break
                for ps in jobs:
                    seen.add(ps)
                    self._vprinter_one(ps)
        finally:
            self._vp_busy = False

    def _vprinter_prefs(self) -> dict:
        p = dict((getattr(self, "_prefs", {}) or {}).get(PREF_KEY) or {})
        p.setdefault("kind", "original")
        p.setdefault("color", "color")
        p.pop("skip", None)                      # 저장 창이 없어져 쓰지 않는다(261017-14)
        return p

    def _vprinter_one(self, ps: str):
        from viewer import vprinter_recv as R
        pref = self._vprinter_prefs()
        box = {}

        # 261017-18 점검: 임시 폴더 만들기·지우기·PS 지우기도 배경 일 안에서 — 메인 스레드는 파일을 만지지 않는다(응답성 SOT §4)
        def job(progress):
            progress(0, 2, tr("받은 문서를 PDF 로 바꾸는 중…"))
            tmpdir = tempfile.mkdtemp(prefix="polypdf_vprint_")
            box["tmp"] = tmpdir
            try:
                plan = R.plan_save(ps, "original" if pref["kind"] != "default" else "default", pref.get("default_dir", ""))
                conv = os.path.join(tmpdir, "printed.pdf")
                R.convert(ps, conv, title=os.path.splitext(R.clean_title(plan["title"]))[0] or plan["name"])
                box["plan"], box["conv"] = plan, conv
            except Exception:
                shutil.rmtree(tmpdir, ignore_errors=True)
                raise
            progress(2, 2, tr("완료"))

        res = self._run_merge_job(job, tr("PolyPDF 프린터"), cancellable=False)
        if res.get("err") or "conv" not in box:
            self._vp_failed = getattr(self, "_vp_failed", set()) | {ps}
            QMessageBox.warning(self, tr("PolyPDF 프린터"),
                                tr("받은 문서를 PDF 로 바꾸지 못했습니다: {err}").format(err=res.get("err") or "?") + "\n\n"
                                + tr("받은 인쇄 파일은 지우지 않았습니다 — 다음에 PolyPDF 를 켤 때 다시 바꿔 봅니다."))
            return                                   # PS 는 남긴다(잃지 않게), 이 창에서는 다시 시도하지 않는다
        plan, conv = box["plan"], box["conv"]
        # 261017-14 사용자 지시: 저장 창(인쇄 창 저장 모드) 없이 — 도구 메뉴 설정(폴더 종류·기본 폴더·흑백)대로 바로 저장하고 연다.
        #   쪽 범위·다단은 인쇄한 프로그램의 인쇄 창에서 고른다(받은 PDF 를 그대로 둔다).
        folder = plan["folder"] or plan["default_dir"]
        color = pref["color"]
        box2 = {}

        def save_job(progress):
            progress(0, 1, tr("저장하는 중…"))
            try:
                os.makedirs(folder, exist_ok=True)
                final = R.unique_pdf_path(folder, plan["name"])
                if color == "gray":
                    R.to_gray(conv, final)
                else:
                    shutil.copyfile(conv, final)
                box2["final"] = final
                try:
                    os.remove(ps)
                except OSError:
                    pass
            finally:
                shutil.rmtree(box["tmp"], ignore_errors=True)
            progress(1, 1, tr("완료"))

        res = self._run_merge_job(save_job, tr("PolyPDF 프린터"), cancellable=False)
        if res.get("err") or "final" not in box2:
            self._vp_failed = getattr(self, "_vp_failed", set()) | {ps}
            QMessageBox.warning(self, tr("PolyPDF 프린터"), tr("저장하지 못했습니다: {err}").format(err=res.get("err") or "?"))
            return
        self.status.showMessage(tr("PolyPDF 프린터 — 저장: {path}").format(path=box2["final"]), 6000)
        self._vprinter_open(box2["final"])

    # ── 여는 곳(SOT §4.4) ─────────────────────────────────────────────
    def _vprinter_open(self, path: str):
        nothing_open = not getattr(self, "_folder", None) and not self.main_view.current_file()
        try:
            if self._vprinter_place(path):
                return
            # 261031-4: 받는 창이 아닌 다른 창이 그 폴더를 보고 있으면 그 창에 넘긴다('폴더 = 창', 사용자 결정 261017-6)
            if self._vprinter_to_peer(path):
                return
            if not nothing_open:
                self._vprinter_new_window(path)
                return
            self.open_pdf(Path(path))
        except Exception:
            self._vprinter_new_window(path)
            return
        self._vprinter_raise()

    def _vprinter_pane_for(self, path: str):
        """그 PDF 의 폴더를 보고 있는 이 창의 책갈피창 → (창 번호, 책갈피창) 또는 None.
        위 책갈피창(`_folder`) 먼저, 2단에서 아래 책갈피창이 보이면 그것(`_folder_right`, 261031-4 — 종전에는 위만 봤다)."""
        folder = os.path.normcase(os.path.dirname(os.path.abspath(path)))

        def same(f):
            return bool(f) and os.path.normcase(os.path.abspath(str(f))) == folder
        if same(getattr(self, "_folder", None)):
            return 0, self.bookmark_tree
        rt = getattr(self, "bookmark_tree_right", None)
        if getattr(self, "_split_on", False) and rt is not None and not rt.isHidden() \
                and same(getattr(self, "_folder_right", None)):
            return 1, rt
        return None

    def _vprinter_place(self, path: str) -> bool:
        """이 창의 책갈피창이 그 폴더를 보고 있으면 그 목록에 더하고 그 창(위=1창·아래=2창)에 연다 → 했으면 True."""
        hit = self._vprinter_pane_for(path)
        if hit is None:
            return False
        pane, tree = hit
        if getattr(self, "_split_on", False):
            self._set_active_pane(pane)
        # 261017-18 점검: 폴더 전체를 다시 읽지 않고(`refresh` 는 메인에서 전부·편집 중이면 질문 창) 그 파일만 더하고,
        #   색인부터 거는 '저장 뒤 여는 길' 하나로(CLAUDE.md `_open_saved_file`)
        tree.add_or_refresh_file(str(path))
        try:
            tree._pending_nav = None                 # 새 행이 예약한 열기 — 여기서 직접 연다(`_open_saved_file` 은 위 창 것만 지운다)
        except Exception:
            pass
        self._open_saved_file(str(path), 0)
        self._vprinter_raise()
        return True

    def _vprinter_to_peer(self, path: str) -> bool:
        """261031-4: 그 폴더를 보고 있는 **다른 PolyPDF 창**에 넘긴다 → 받았으면 True. 묻고 기다리는 일은 배경(`_peer_bg`, 응답성 SOT §4.4)."""
        link = getattr(self, "_instance_link", None)
        if link is None:
            return False
        return bool(self._peer_bg(lambda: link.show_file(path), tr("그 폴더를 보고 있는 PolyPDF 창을 찾는 중…")))

    def _vprinter_peer_show(self, path) -> dict:
        """261031-4: 다른 창(받는 창)이 넘긴 파일 — 이 창이 그 폴더를 보고 있으면 응답을 먼저 보내고 연다(`_on_instance_request` 'show')."""
        if not path or self._vprinter_pane_for(str(path)) is None:
            return {"ok": False}
        QTimer.singleShot(0, lambda p=str(path): self._vprinter_place(p))
        return {"ok": True}

    def _vprinter_raise(self):
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _vprinter_new_window(path: str):
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, path]
        else:
            cmd = [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"), path]
        try:
            subprocess.Popen(cmd, close_fds=True)
        except OSError:
            pass
