# -*- coding: utf-8 -*-
"""261108-24: 캡처·읽기 — 아이콘 + 이름 한 단추(분할 단추) (디자인 SOT §2.10).

사용자 지시: "아이콘과 이름을 하나의 버튼으로 표시가능한지 검토(즉, 화면캡쳐 아이콘 오른쪽에 '전체' 표시된 버튼,
플레이 아이콘 오른쪽에 '전체' 표시된 버튼)". 결정: 분할 단추 — 아이콘·글자를 누르면 실행, ▾ 칸은 메뉴, 툴팁 합침.

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2), 실제 마우스·키 이벤트로.
A. 두 창 모두 캡처·읽기가 단추 하나 — QToolButton·MenuButtonPopup·아이콘 + 글자('전체'), 종전 따로 있던 메뉴 단추는 없다
B. 본체(아이콘 쪽)를 누르면 실행(캡처 / 읽기 토글), 메뉴는 열리지 않는다 · Space 도 실행
C. ▾ 칸을 누르면 메뉴(캡처: 전체·영역 캡처 … / 읽기: 1회·연속·전체·전체연속), 실행은 없다 · Alt+↓·F4 도 메뉴
D. 툴팁 두 줄 — 실행 설명 + '▾ …'
E. 메뉴에서 고르면 글자가 바뀐다(캡처 모드·재생 구간), 읽는 중(■)이어도 글자는 구간
F. 다크 테마 — 아이콘 그대로·글자 그대로
"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, Qt, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QToolButton, QMenu, QAbstractButton
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_split_btn_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "분할 단추", echo=False)   # 검사 작성 SOT §14.7.2 의 6
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


def menu_opened_by(fn):
    """fn() 이 메뉴를 열면 그 메뉴의 항목 글을 돌려준다(열린 메뉴는 닫는다). 안 열리면 None."""
    seen = []

    def close_popup():
        w = QApplication.activePopupWidget()
        if isinstance(w, QMenu):
            seen.append([a.text() for a in w.actions() if a.text()])
            w.close()
    QTimer.singleShot(250, close_popup)
    fn()
    spin(0.5)
    return seen[0] if seen else None


try:
    from viewer.app import MainWindow
    from viewer.i18n import tr
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 800); mw.show(); spin(0.6)

    caps, reads = [], []
    mw._do_capture = lambda view: caps.append(view)                 # 단추의 연결은 self._do_capture 를 부를 때 찾는다
    mw._pane_read_toggle = lambda i: reads.append(i)
    body = lambda b: QPoint(8, b.height() // 2)                       # 아이콘 쪽
    arrow = lambda b: QPoint(b.width() - 4, b.height() // 2)          # ▾ 칸

    for i in (0, 1):
        cap, rd = mw._cap_btns[i], mw._read_btns[i]
        # A
        for name, b in (("캡처", cap), ("읽기", rd)):
            chk(isinstance(b, QToolButton) and b.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup
                and b.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon and not b.icon().isNull()
                and b.text() == tr("전체") and b.menu() is not None,
                f"[{i}] A {name} — 아이콘 + '전체' 분할 단추 하나",
                f"{type(b).__name__} {getattr(b, 'popupMode', lambda: None)()} {b.text()!r}")
        grp = rd.parentWidget()
        chk(len([w for w in grp.findChildren(QAbstractButton) if not w.isHidden()]) == 1, f"[{i}] A 읽기 묶음에 단추 하나(따로 메뉴 단추 없음)")
        chk(len([w for w in cap.parentWidget().findChildren(QAbstractButton) if not w.isHidden()]) == 1,
            f"[{i}] A 캡처 묶음에 단추 하나(종전 카메라 단추 + 모드 드롭다운 둘)")
        # B
        caps.clear(); reads.clear()
        got = menu_opened_by(lambda: QTest.mouseClick(cap, Qt.MouseButton.LeftButton, pos=body(cap)))
        chk(got is None and caps == [mw._mv[i]], f"[{i}] B 캡처 본체 누르면 그 창 캡처·메뉴 없음", f"menu={got} caps={len(caps)}")
        got = menu_opened_by(lambda: QTest.mouseClick(rd, Qt.MouseButton.LeftButton, pos=body(rd)))
        chk(got is None and reads == [i], f"[{i}] B 읽기 본체 누르면 그 창 읽기 토글·메뉴 없음", f"menu={got} reads={reads}")
        caps.clear(); reads.clear()
        cap.setFocus(); QTest.keyClick(cap, Qt.Key.Key_Space); spin(0.2)
        rd.setFocus(); QTest.keyClick(rd, Qt.Key.Key_Space); spin(0.2)
        chk(caps == [mw._mv[i]] and reads == [i], f"[{i}] B Space 도 실행", f"caps={len(caps)} reads={reads}")
        # C
        caps.clear(); reads.clear()
        got = menu_opened_by(lambda: QTest.mousePress(cap, Qt.MouseButton.LeftButton, pos=arrow(cap)))
        QTest.mouseRelease(cap, Qt.MouseButton.LeftButton, pos=arrow(cap)); spin(0.2)
        chk(got is not None and tr("전체") in got and tr("영역 캡처") in got and not caps,
            f"[{i}] C 캡처 ▾ 칸은 모드 메뉴·캡처 없음", f"menu={got} caps={len(caps)}")
        got = menu_opened_by(lambda: QTest.mousePress(rd, Qt.MouseButton.LeftButton, pos=arrow(rd)))
        QTest.mouseRelease(rd, Qt.MouseButton.LeftButton, pos=arrow(rd)); spin(0.2)
        chk(got is not None and all(tr(x) in got for x in ("1회", "연속", "전체", "전체연속")) and not reads,
            f"[{i}] C 읽기 ▾ 칸은 재생 구간 메뉴·읽기 없음", f"menu={got} reads={reads}")
        got = menu_opened_by(lambda: QTest.keyClick(cap, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier))
        chk(got is not None and tr("영역 캡처") in got, f"[{i}] C Alt+↓ 로 캡처 메뉴", str(got))
        got = menu_opened_by(lambda: QTest.keyClick(rd, Qt.Key.Key_F4))
        chk(got is not None and tr("연속") in got, f"[{i}] C F4 로 읽기 메뉴", str(got))
        chk(not caps and not reads, f"[{i}] C 메뉴 키는 실행하지 않는다", f"caps={len(caps)} reads={reads}")
        # D
        chk(cap.toolTip().startswith(tr("이 창 캡처 (활성 창은 Ctrl+Shift+S)")) and "\n▾ " in cap.toolTip(),
            f"[{i}] D 캡처 툴팁 두 줄", repr(cap.toolTip()))
        chk(rd.toolTip().startswith(tr("본문 읽기/정지 (머리말·표·수식·그림 제외)")) and rd.toolTip().endswith("▾ " + tr("재생 구간 / 빠르기 / 성우")),
            f"[{i}] D 읽기 툴팁 두 줄", repr(rd.toolTip()))

    # E — 메뉴에서 고르면 글자
    cap, rd = mw._cap_btns[0], mw._read_btns[0]
    a = [x for x in cap.menu().actions() if x.text() == tr("영역 캡처")][0]
    a.trigger(); spin(0.3)
    chk(mw._cap_btns[0].text() == tr("영역 캡처") and mw._cap_btns[1].text() == tr("영역 캡처"), "E 캡처 모드를 고르면 두 창 글자 '영역 캡처'",
        f"{mw._cap_btns[0].text()} {mw._cap_btns[1].text()}")
    [x for x in mw._cap_btns[0].menu().actions() if x.text() == tr("전체")][0].trigger(); spin(0.3)
    [x for x in rd.menu().actions() if x.text() == tr("연속")][0].trigger(); spin(0.1)
    chk(rd.text() == tr("연속"), "E 재생 구간을 고르면 글자 '연속'", rd.text())
    from viewer.widgets.read_aloud import set_play_state
    k0 = rd.icon().cacheKey()
    set_play_state(rd, True)
    chk(rd.text() == tr("연속") and rd.icon().cacheKey() != k0
        and rd.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon, "E 읽는 중 ■ 아이콘이어도 글자는 구간", rd.text())
    set_play_state(rd, False)
    # F
    mw.apply_theme("dark"); spin(0.4)
    chk(all(not b.icon().isNull() for b in mw._cap_btns + mw._read_btns)
        and mw._cap_btns[0].text() == tr("전체") and rd.text() == tr("연속"), "F 다크 — 아이콘·글자 그대로")
    mw.apply_theme("light"); spin(0.2)
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
