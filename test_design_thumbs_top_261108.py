# -*- coding: utf-8 -*-
"""261108-23: 썸네일 창 위 끝 — 이름 줄 없음, 단추 줄이 맨 위 (디자인 SOT §2.8.7).

사용자 지시: "썸네일 창 위의 파일이름 표시를 삭제하고, 해당위치에 '전체'등의 버튼을 배치하고,
썸네일 창의 종방향 시작을 전체화면의 시작과 맞춰 (본화면 아래 등에 제목이 표시되므로 삭제)"

실제 MainWindow 배치로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 썸네일 칸에 이름 줄(제목 글·종류 아이콘)이 없다 — PDF 를 열어도
B. 단추 줄 [전체][보임][꾸밈][숨김] 위 끝 = 본문 창 위 끝, 단추 높이 = 본문 도구 줄 높이(TOOLBAR_H)
C. 썸네일 목록 위 끝 = 본문 쪽 보기 위 끝
D. 2단 보기에서도 B·C
"""
import os, sys, time, shutil, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QLabel

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_thumbs_top_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "썸네일 위 끝", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def wait(cond=None, sec=8.0):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        if cond is not None and cond():
            return True
        time.sleep(0.01)
    return cond() if cond is not None else True


import test_fixtures as _fx

tmp = Path(tempfile.mkdtemp(prefix="thumbs_top_"))
try:
    pdf = tmp / "긴 이름의 보고서 문서.pdf"
    shutil.copy(Path(_fx.text_pdf()), pdf)
    from viewer.app import MainWindow
    from viewer.widgets.main_view import MainView
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 820); mw.show(); wait(sec=0.5)
    bt = mw.bookmark_tree
    pt = mw.page_thumbs
    mw.open_folder(tmp)
    wait(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 1)
    mw._on_bookmark_activated(str(pdf), 0)
    wait(lambda: pt.list.count() >= 1)
    wait(sec=0.4)
    y = lambda w: w.mapTo(mw, QPoint(0, 0)).y()

    # A
    labels = [w for w in pt.findChildren(QLabel) if w.isVisible() and w.text().strip()]
    chk(not hasattr(pt, "title") and not hasattr(pt, "_title_icon") and pt.findChild(QLabel, "thumbsTitleIcon") is None,
        "A 썸네일 칸에 제목 글·종류 아이콘 위젯이 없다")
    chk(not any("보고서" in w.text() for w in labels), "A 파일 이름이 썸네일 칸에 보이지 않는다", str([w.text() for w in labels]))

    def check_pane(tag, mv):
        # 2단의 활성 창은 파란 테두리 틀(QFrame#paneN, 2px) 안이라 내용이 테두리만큼 내려간다 — 창 위 끝은 틀 위 끝
        frame = mv.parentWidget()
        border = y(mv) - y(frame)
        b = pt._filter_btns["all"]
        chk(y(b) == y(pt) == y(frame), f"{tag} B 단추 줄 위 끝 = 본문 창(틀) 위 끝", f"btn={y(b)} panel={y(pt)} frame={y(frame)}")
        chk(all(x.height() == MainView.TOOLBAR_H for x in pt._filter_btns.values()),
            f"{tag} B 단추 높이 = TOOLBAR_H", str([x.height() for x in pt._filter_btns.values()]))
        chk(y(pt.list) == y(mv.view) - border, f"{tag} C 썸네일 목록 위 끝 = 본문 쪽 보기 위 끝(테두리 {border}px 뺌)",
            f"list={y(pt.list)} view={y(mv.view)}")

    check_pane("1단", mw._mv[0])
    # D
    mw.resize(2400, 820)                    # 두 창 도구 줄이 한 줄에 들도록(좁으면 흘러 두 줄 — §2.8.7 표 마지막 줄)
    mw._toggle_split(True); wait(sec=0.5)
    print("  2단 도구 줄 높이", [m._toolbar_widget.height() for m in mw._mv], "mv y", [y(m) for m in mw._mv])
    check_pane("2단", mw._mv[0])
    chk(y(mw._mv[1].view) == y(pt.list), "2단 D 오른쪽 창 쪽 보기 위 끝도 같다", f"{y(mw._mv[1].view)} {y(pt.list)}")
    mw._toggle_split(False); wait(sec=0.3)
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
