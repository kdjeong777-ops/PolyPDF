# -*- coding: utf-8 -*-
"""261105-25: 진행 메시지를 누르면 작업 창 — [계속]/[중단]/[취소] (응답성 SOT §4.6 · 디자인 SOT §2.18).

사용자 지시: "일괄 OCR 중에 여기첨부한 메시지를 클릭하면, 창이 뜨고 중간에 취소하거나, 중단할 수 있도록해.
유사한 시간이 오래 걸리는 작업도 검토하여 동일한 방법을 적용해" — 결정: [계속](기본)·[중단]·[취소], 취소는 그 파일의
저장 안 한 결과 전부를 다시 묻지 않고 버림, 폴더 색인도 작업 창에.

모두 실제 처리기(`_study_build_run`·`_start_index_worker`)와 실제 마우스·키 이벤트로 본다. 단어장 생성 워커만 OCR 대신
쪽마다 잠깐 쉬며 `request_cancel` 을 지키는 대역이다(Tesseract 없이 '쪽 경계에서 멈춤' 을 재려고).

A. 작업이 없을 때 상태 표시줄을 눌러도 작업 창이 뜨지 않는다(커서도 보통)
B. 단어장 생성 중 왼쪽 진행 메시지를 누르면 작업 창 — [계속] 이 기본 단추·초점, Enter 는 창만 닫고 작업은 계속
C. [중단] — 워커가 멈추고, 결과는 버리지 않고, '중단 — 이어서' 안내
D. [취소] — 워커가 멈추고, 끝난 뒤에 그 파일의 저장 안 한 결과를 버리고(한 번), '이어서' 안내 대신 '취소했습니다'
E. 폴더 색인 — 작업 창에 '인덱싱' 이 오르고 [중단] 이 실제 색인을 멈춘다 · '인덱싱 완료' 가 아니라 '인덱싱 중단'
"""
import os, sys, time, shutil, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, QCoreApplication, QObject, QPoint, Qt, pyqtSignal
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tool_cancel_jobs_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "작업 창")       # 마스터 §14.7.2 의 6 — 뜻밖의 모달이 검사를 세우지 않게
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait(cond, sec=10.0):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class FakeBuild(QObject):
    """StudyBuildWorker 대역 — 쪽마다 30ms, 쪽 경계에서 request_cancel 을 본다."""
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    made = []

    def __init__(self, path, **kw):
        super().__init__()
        self._cancel = False
        self.pages = 0
        self.ended = False
        FakeBuild.made.append(self)

    def request_cancel(self):
        self._cancel = True

    def run(self):
        n = 400
        for i in range(n):
            if self._cancel:
                break
            time.sleep(0.03)
            self.pages = i + 1
            self.progress.emit(i + 1, n, f"{i + 1}p [ocr]")
        self.ended = True
        self.finished.emit({"cancelled": self._cancel, "done": self.pages, "vocab": {}})


import test_fixtures as _fx
from viewer.i18n import tr
import viewer.study_controller as sc
sc.StudyBuildWorker = FakeBuild
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

tmp = Path(tempfile.mkdtemp(prefix="jobs261105_"))
try:
    pdf = tmp / "doc.pdf"
    shutil.copy(Path(_fx.text_pdf()), pdf)
    from viewer.app import MainWindow
    mw = MainWindow()
    mw._skip_save_on_close = True
    mw.resize(1200, 800)
    mw.show()
    spin(0.6)
    discarded = []
    ended_at_discard = []
    mw.study_discard_for = lambda p: (discarded.append(str(p)),
                                      ended_at_discard.append(bool(FakeBuild.made and FakeBuild.made[-1].ended)))
    seen = []
    mw.status.messageChanged.connect(lambda m: seen.append(m))
    mw._detect_study_lang = lambda p: "kor"

    def msg_point():
        return QPoint(30, mw.status.height() // 2)

    def jobs_dlg():
        d = getattr(mw, "_jobs_dlg", None)
        return d if (d is not None and d.isVisible()) else None

    # A — 작업이 없으면 무반응
    mw.status.showMessage("아무 메시지")
    QTest.mouseClick(mw.status, Qt.MouseButton.LeftButton, pos=msg_point())
    spin(0.2)
    chk(jobs_dlg() is None, "A 작업이 없으면 상태 표시줄을 눌러도 작업 창이 뜨지 않는다")
    chk(mw.status.cursor().shape() != Qt.CursorShape.PointingHandCursor, "A 작업이 없으면 손가락 커서가 아니다")
    mw.status.clearMessage()

    def start_build():
        FakeBuild.made.clear()
        mw._study_pdf = pdf
        mw._study_build_run(also_bookmarks=False, with_vocab=True)
        wait(lambda: FakeBuild.made and FakeBuild.made[-1].pages >= 3)
        return FakeBuild.made[-1]

    # B — 진행 메시지를 누르면 작업 창, Enter = [계속]
    w = start_build()
    chk(mw.status.currentMessage().startswith(tr("단어장 생성")), "B 진행 메시지가 상태 표시줄에", repr(mw.status.currentMessage()))
    chk(mw.status.cursor().shape() == Qt.CursorShape.PointingHandCursor, "B 작업이 돌면 상태 표시줄이 손가락 커서")
    QTest.mouseClick(mw.status, Qt.MouseButton.LeftButton, pos=msg_point())
    ok = wait(lambda: jobs_dlg() is not None, 3)
    chk(ok, "B 진행 메시지를 누르면 작업 창이 뜬다")
    if not ok:
        raise SystemExit(1)
    d = jobs_dlg()
    names = {b.objectName() for b in d.findChildren(type(d.btn_continue)) if b.isVisible()}
    chk({"job_continue", "job_stop_study_build", "job_cancel_study_build"} <= names,
        "B [계속]·[중단]·[취소] 가 있다", str(names))
    chk(d.btn_continue.isDefault() and d.focusWidget() is d.btn_continue, "B 기본 단추·처음 초점은 [계속]",
        f"default={d.btn_continue.isDefault()} focus={d.focusWidget()}")
    QTest.keyClick(d, Qt.Key.Key_Return)
    spin(0.3)
    chk(jobs_dlg() is None and not w._cancel and "study_build" in mw._jobs, "B Enter 는 창만 닫고 작업은 계속",
        f"dlg={jobs_dlg()} cancel={w._cancel}")

    # C — [중단]
    QTest.mouseClick(mw.status, Qt.MouseButton.LeftButton, pos=msg_point())
    wait(lambda: jobs_dlg() is not None, 3)
    d = jobs_dlg()
    b = next(x for x in d.findChildren(type(d.btn_continue)) if x.objectName() == "job_stop_study_build")
    p0 = w.pages
    QTest.mouseClick(b, Qt.MouseButton.LeftButton)
    stopped = wait(lambda: "study_build" not in mw._jobs, 5)
    chk(stopped and w._cancel and w.pages < 400, "C [중단] 이 워커를 쪽 경계에서 멈춘다", f"pages={w.pages} (누를 때 {p0})")
    chk(not discarded, "C [중단] 은 결과를 버리지 않는다", str(discarded))
    chk(mw.status.currentMessage().startswith(tr("{what} 중단 — 읽은 {n}쪽은 저장하지 않은 상태로 남아, 다시 시작하면 이어서 합니다.")
                                              .split("{what}")[0] + tr("단어장 생성")),
        "C 중단 안내 — 다시 하면 이어서", repr(mw.status.currentMessage()))
    d.close(); spin(0.2)

    # D — [취소]
    w = start_build()
    QTest.mouseClick(mw.status, Qt.MouseButton.LeftButton, pos=msg_point())
    wait(lambda: jobs_dlg() is not None, 3)
    d = jobs_dlg()
    b = next(x for x in d.findChildren(type(d.btn_continue)) if x.objectName() == "job_cancel_study_build")
    QTest.mouseClick(b, Qt.MouseButton.LeftButton)
    stopped = wait(lambda: "study_build" not in mw._jobs, 5)
    spin(0.2)
    chk(stopped and w._cancel and w.pages < 400, "D [취소] 도 워커를 멈춘다", f"pages={w.pages}")
    chk(discarded == [str(pdf)], "D 끝난 뒤 그 파일의 저장 안 한 결과를 한 번 버린다(다시 묻지 않음)", str(discarded))
    chk(ended_at_discard == [True], "D 버림은 워커가 끝난 뒤에(쓰는 중에 지우지 않음)", str(ended_at_discard))
    chk("취소" in mw.status.currentMessage() or "cancel" in mw.status.currentMessage().lower(),
        "D '취소했습니다' 안내(이어서 안내가 아니다)", repr(mw.status.currentMessage()))
    d.close(); spin(0.2)

    # E — 폴더 색인
    big = tmp / "many"
    big.mkdir()
    for i in range(160):
        shutil.copy(pdf, big / f"f{i:03d}.pdf")
    seen.clear()
    mw.open_folder(big)
    ok = wait(lambda: "index" in mw._jobs, 10)
    chk(ok, "E 폴더 색인이 작업 창에 오른다", str(list(mw._jobs)))
    iw = mw._index_workers[0] if mw._index_workers else None
    QTest.mouseClick(mw.status, Qt.MouseButton.LeftButton, pos=msg_point())
    wait(lambda: jobs_dlg() is not None, 3)
    d = jobs_dlg()
    b = next((x for x in d.findChildren(type(d.btn_continue)) if x.objectName() == "job_stop_index"), None) if d else None
    chk(b is not None and not any(x.objectName() == "job_cancel_index" for x in d.findChildren(type(d.btn_continue))),
        "E 색인은 [중단] 만(버릴 결과가 없다)")
    if b is not None:
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
    ended = wait(lambda: "index" not in mw._jobs and not mw.progress.isVisible(), 20)
    spin(0.3)
    chk(ended and iw is not None and iw._cancel, "E [중단] 이 실제 색인을 멈춘다")
    chk(tr("인덱싱 중단 — 다음에 폴더를 열면 남은 파일부터 이어서 색인합니다.") in seen and tr("인덱싱 완료") not in seen,
        "E '인덱싱 완료' 가 아니라 '인덱싱 중단'", str([m for m in seen if '인덱싱' in m][-3:]))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL PASS" if not fails else f"FAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)
