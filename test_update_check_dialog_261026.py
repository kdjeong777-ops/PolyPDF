# -*- coding: utf-8 -*-
"""261026-5(사용자 지시, 마스터 §14.5 U14): '업데이트 확인' 창 아래에 자동 다운로드·베타 체크.

종전 결함: 두 체크 항목이 도움말 메뉴의 체크 액션이라 리본(세부 줄) 단추로는 체크 상태를 다룰 수 없었다.
수정 전 코드로 A·B 가 실패한다.

A. 도움말 탭에 두 체크 항목이 없다(사용법·업데이트 확인·정보만)
B. `업데이트 확인…` 을 누르면 창이 **먼저** 뜨고('확인 중…'), 결과('현재 최신 버전입니다')가 그 창에 들어간다 — 알림 창 따로 없음
C. 창 아래 두 체크 — 자동 다운로드를 **눌러** 끄면 곧바로 설정에 저장, 1.0 이전이면 베타는 켜진 채 잠김
D. 새 버전이면 같은 창에 바뀐 내용과 [업데이트]·[나중에]
E. 결과가 오기 전에 창을 닫으면 늦게 온 결과로 창을 다시 띄우지 않는다
"""
import os, sys, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)

from PyQt6.QtCore import QStandardPaths, Qt, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
from PyQt6.QtCore import QCoreApplication as _QCA
_QCA.setApplicationName("polypdf_update_check_%d" % os.getpid())   # 마스터 §14.7.2 의 3 — 공유 시험 설정(qttest/python)에 남기지 않는다
import modal_guard
guard = modal_guard.install(label=lambda: "업데이트 확인", watch_ms=0, echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


try:
    from viewer.app import MainWindow
    from viewer import updater
    from viewer.widgets import update_dialog as UD
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1600, 900); mw.show(); QTest.qWait(100)
    saved = []
    mw._save_settings_now = lambda *a, **k: saved.append(dict(mw._prefs))
    cur = updater.current_version()

    # A
    help_items = [a.text() for a in mw._tab_menus["help"].actions() if not a.isSeparator()]
    chk(help_items == ["사용법", "업데이트 확인…", "정보"], "A 도움말 탭에 두 체크 항목이 없다", str(help_items))

    # B·C — 결과가 늦게 오는 확인(실제 스레드·시그널 길)
    boxes = []
    _orig_info = QMessageBox.information
    QMessageBox.information = lambda *a, **k: boxes.append(a[2] if len(a) > 2 else "")
    _orig_check = updater.check_latest
    updater.check_latest = lambda repo, channel="stable": (__import__("time").sleep(0.3), {"version": cur})[1]
    seen = {}
    _orig_exec = UD.UpdateDialog.exec

    def _exec(self):
        self.show()                                      # 실제 창처럼 보인 채(누름이 닿게)
        seen["first"] = self.head.text()
        for _ in range(60):
            QTest.qWait(50)
            if "최신" in self.head.text():
                break
        seen["after"] = self.head.text()
        seen["chk"] = (self.chk_auto_download is not None, self.chk_beta is not None)
        if self.chk_auto_download is not None:
            mw._prefs["auto_download_update"] = True
            self.chk_auto_download.setChecked(True)
            from PyQt6.QtCore import QPoint
            QTest.mouseClick(self.chk_auto_download, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             QPoint(8, self.chk_auto_download.height() // 2)); QTest.qWait(30)   # 체크 표시 위(글자 밖 빈 곳은 안 눌린다)
            seen["beta"] = (self.chk_beta.isChecked(), self.chk_beta.isEnabled())
        return QDialog.DialogCode.Rejected
    UD.UpdateDialog.exec = _exec
    try:
        mw._tab_menus["help"].actions()[1].trigger(); QTest.qWait(100)
    finally:
        UD.UpdateDialog.exec = _orig_exec
    chk("확인하는 중" in seen.get("first", ""), "B 창이 먼저 뜨고 '확인 중…'", seen.get("first"))
    chk("최신 버전" in seen.get("after", "") and not boxes, "B 결과가 그 창에 들어간다(알림 창 따로 없음)", str((seen.get("after"), boxes)))
    chk(seen.get("chk") == (True, True), "C 창 아래 두 체크", str(seen.get("chk")))
    chk(mw._prefs.get("auto_download_update") is False and saved, "C 자동 다운로드를 눌러 끄면 곧바로 저장")
    pre10 = int((cur.lstrip("vV").split(".")[0]) or "0") == 0
    if pre10:
        chk(seen.get("beta") == (True, False), "C 1.0 이전: 베타 켜진 채 잠김", str(seen.get("beta")))
    else:
        chk(seen.get("beta", (None, None))[1] is True, "C 1.0 이후: 베타 체크를 고를 수 있다", str(seen.get("beta")))

    # D 새 버전 — 같은 창에 바뀐 내용·단추
    dlg = UD.UpdateDialog(None, cur, "check", mw, options=mw._update_options())
    dlg.show_result({"version": "9.9.9", "tag": "v9.9.9", "changes": [{"version": "9.9.9", "notes": "- 새 기능"}]}, cur)
    btns = [w.text() for w in dlg.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton) if w.isVisibleTo(dlg)]
    chk("새 버전이 있습니다" in dlg.head.text() and dlg.notes.isVisibleTo(dlg) and "업데이트" in btns and "나중에" in btns,
        "D 새 버전이면 바뀐 내용과 [업데이트]·[나중에]", str(btns))
    dlg.done(0)

    # E 결과 전에 닫으면 늦은 결과로 다시 띄우지 않는다
    boxes.clear()
    UD.UpdateDialog.exec = lambda self: QDialog.DialogCode.Rejected          # 곧바로 닫음
    try:
        mw._check_for_updates(manual=True)
        QTest.qWait(800)                                                     # 늦은 결과(0.3초 뒤) 처리
    finally:
        UD.UpdateDialog.exec = _orig_exec
    chk(not boxes, "E 창을 먼저 닫으면 늦게 온 결과로 알림을 띄우지 않는다", str(boxes))
    updater.check_latest = _orig_check
    QMessageBox.information = _orig_info
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
