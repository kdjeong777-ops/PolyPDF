# -*- coding: utf-8 -*-
"""자동 태그 첫 실행 요약은 비모달 알림 창 (태그 SOT §8.2, 261114-15).

결함: 폴더를 열면 저절로 도는 태그 계산(기본 켬) 끝에 '태그 자동 부여' 요약이 모달 `exec()` 로 떠
사용자 작업을 막았고, 검사에서는 닫을 사람이 없어 test_reopen_after_save 등 다섯 검사가 시간 초과로 멈췄다.
사용자 결정: 비모달 알림 창 — 내용·단추 그대로, 막지 않는다.
실제 MainWindow·`_autotag_first_summary` 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 띄워도 곧바로 돌아온다(수정 전: 창을 닫을 때까지 돌아오지 않는다) · 창은 보이고 모달이 아니다
B. [되돌리기] 를 누르면 `_autotag_undo`, [새 태그 후보 검토] 는 `_autotag_review_candidates`
C. 두 번째 계산 끝에는 띄우지 않는다(1회)
A 덧붙임(261114-19): 띄워도 활성 창·포커스는 주 창의 치던 칸 그대로(수정 전 show() 가 빼앗아 검사 아홉 개가 흔들렸다)
"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_summary_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "첫 실행 요약", echo=False)   # 수정 전 exec() 는 여기 걸려 기록된다
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def pump(sec):
    t = time.monotonic()
    while time.monotonic() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def boxes():
    return [w for w in app.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()]


def closer():
    """수정 전 코드는 exec() 에서 돌아오지 않는다 — 2초 뒤 닫아 검사가 멈추지 않게(그 시간이 실패 증거)."""
    for b in boxes():
        b.reject()


try:
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True; mw.show(); pump(0.3)
    calls = []
    mw._autotag_undo = lambda: calls.append("undo")
    mw._autotag_review_candidates = lambda: calls.append("review")
    mw._prefs["autotag_summary_shown"] = False
    stats = {"total": 10, "known_tags": 3, "new_candidates": 2}

    # A
    mw.activateWindow(); se = mw.bookmark_tree.search_edit; se.setFocus(); pump(0.2)
    QTimer.singleShot(2000, closer)
    t0 = time.monotonic()
    mw._autotag_first_summary(stats, 4)
    dt = time.monotonic() - t0
    chk(dt < 1.0, "A 요약을 띄워도 곧바로 돌아온다(막지 않음)", "%.2fs" % dt)
    chk(not guard.seen, "A 모달 exec 로 띄우지 않는다", guard.report())
    pump(0.3)
    chk(app.activeWindow() is mw and app.focusWidget() is se, "A 활성 창·포커스를 빼앗지 않는다(치던 칸 그대로, 261114-19)",
        "%s / %s" % (type(app.activeWindow()).__name__, type(app.focusWidget()).__name__))
    bs = boxes()
    chk(len(bs) == 1, "A 요약 창이 하나 보인다", str(len(bs)))
    if bs:
        b = bs[0]
        chk(b.windowModality() == Qt.WindowModality.NonModal and not b.isModal(), "A 모달이 아니다", str(b.windowModality()))
        chk("10" in b.text() and "4" in b.text(), "A 내용은 그대로(살펴본 수·붙인 수)", b.text()[:60])
        # B
        undo = [x for x in b.buttons() if x.text() == "되돌리기"]
        chk(len(undo) == 1, "B [되돌리기] 단추")
        if undo:
            undo[0].click(); pump(0.3)
        chk(calls == ["undo"], "B [되돌리기] → 직전 자동 부여 되돌리기", str(calls))
        chk(not boxes(), "B 단추를 누르면 창이 닫힌다")
    # B 후보 검토(두 번째 창을 띄우려고 표시 기록을 지운다)
    mw._prefs["autotag_summary_shown"] = False
    mw._autotag_first_summary(stats, 4); app.processEvents()
    bs = boxes()
    rv = [x for x in (bs[0].buttons() if bs else []) if x.text() == "새 태그 후보 검토"]
    if rv:
        rv[0].click(); pump(0.3)
    chk(calls == ["undo", "review"], "B [새 태그 후보 검토] → 후보 검토", str(calls))
    # C
    mw._autotag_first_summary(stats, 4); app.processEvents()
    chk(not boxes(), "C 두 번째는 띄우지 않는다(1회)")
    chk(mw._prefs.get("autotag_summary_shown") is True, "C 띄운 기록을 남긴다")
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
