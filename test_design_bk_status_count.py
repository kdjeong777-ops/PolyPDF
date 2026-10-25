# -*- coding: utf-8 -*-
"""261025-4: 책갈피창 개수 글은 상태 표시줄로, 아래 끝은 본문과 같게 (디자인 SOT §2.8.6).

사용자 지시: "파일 개수 글을 진행 메시지가 나오는 자리로 — 진행 메시지가 나오는 동안에는 숨기고, 끝나면 다시.
책갈피창 하단 길이를 본화면 하단 길이와 같게." 결정: 다른 알림도 진행 메시지처럼(임시 메시지),
아래 책갈피창이 보이면 '위 … · 아래 …'.

A. 아래 끝 — 책갈피 목록·썸네일·본문의 아래 끝이 같다(트리 밑에 글 줄이 없다)
B. 개수 — 폴더를 열면 상태 표시줄 개수 칸에 'N개 PDF'. 임시 메시지 동안 숨고 지우면 다시 보인다
C. 진행 — 목록을 워커로 훑는 동안 'PDF 찾는 중' 이 상태 표시줄에 있고 개수는 숨는다. 끝나면 지워지고 개수
D. 진행 끝은 **제 글일 때만** 지운다 — 그사이 다른 진행 메시지가 덮었으면 남긴다
E. 알림 — [📁 폴더] 단추를 눌러 생긴 알림이 상태 표시줄에 떴다가 시간이 지나면 사라지고 개수가 돌아온다
F. 2단 — 아래 책갈피창이 보이면 '위 … · 아래 …', 1단으로 돌아가면 위 창 것만
"""
import os, sys, time, shutil, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, QPoint, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
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


def wait(cond, sec=8.0):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


import test_fixtures as _fx
from viewer.i18n import tr

tmp = Path(tempfile.mkdtemp(prefix="bkcount_"))
try:
    for i in range(3):
        shutil.copy(Path(_fx.text_pdf()), tmp / f"doc{i}.pdf")

    from viewer.app import MainWindow
    mw = MainWindow()
    mw._skip_save_on_close = True
    mw.resize(1200, 800)
    mw.show()
    spin(0.8)
    bt = mw.bookmark_tree
    lbl = getattr(mw, "_bk_count", None)
    chk(lbl is not None, "B 상태 표시줄에 개수 칸이 있다")
    if lbl is None:
        raise SystemExit(1)

    mw.open_folder(tmp)
    wait(lambda: bt.tree.topLevelItemCount() > 0)
    wait(lambda: not mw.progress.isVisible(), 30)     # 색인 진행 글이 뒤에서 덮지 않게
    spin(0.5)

    # A — 아래 끝
    def bottom(w):
        return w.mapTo(mw, QPoint(0, w.height())).y()
    b_tree, b_thumbs, b_main = bottom(bt.tree), bottom(mw.page_thumbs), bottom(mw._mv[0])
    chk(b_tree == b_main == b_thumbs, "A 책갈피 목록·썸네일·본문 아래 끝이 같다",
        f"tree={b_tree} thumbs={b_thumbs} main={b_main}")
    chk(not hasattr(bt, "info"), "A 트리 밑 글 줄(info)이 없다")

    # B — 개수와 임시 메시지
    #   (색인·목록 조사가 남긴 시간 제한 메시지가 스스로 사라질 때까지 기다린다 — 지우면 뒤따라 또 온다)
    want = tr('{n}개 PDF').format(n=3)
    wait(lambda: mw.status.currentMessage() == "", 15)
    chk(lbl.text() == want and lbl.isVisible(), "B 폴더를 열면 상태 표시줄에 'N개 PDF'",
        f"{lbl.text()!r} 보임={lbl.isVisible()} 메시지={mw.status.currentMessage()!r}")
    mw.status.showMessage("다른 진행…")             # 숨기기·다시 보이기는 그 자리에서 일어난다 — 사이에 이벤트를 돌리지 않는다
    chk(not lbl.isVisible(), "B 진행 메시지 동안 개수는 숨는다")
    mw.status.clearMessage()
    chk(lbl.isVisible(), "B 메시지가 지워지면 개수가 다시 보인다")

    # C — 워커로 훑는 동안의 진행
    bt.SCAN_BUDGET_MS = -1                      # 예산을 넘긴 것으로 — 워커로 훑게
    bt.load_folder(tmp)
    prog = mw.status.currentMessage()
    chk(prog in (tr("PDF 찾는 중..."), tr('{n}개 PDF 찾는 중...').format(n=0)), "C 훑는 동안 상태 표시줄에 진행 글", repr(prog))
    chk(not lbl.isVisible(), "C 진행 중에는 개수가 숨는다")
    ok = wait(lambda: bt._scan_worker is None and bt.tree.topLevelItemCount() == 3)
    spin(0.2)
    chk(ok and mw.status.currentMessage() == "", "C 훑기가 끝나면 진행 글을 지운다", repr(mw.status.currentMessage()))
    chk(lbl.isVisible() and lbl.text() == want, "C 끝나면 개수가 다시 보인다", repr(lbl.text()))

    # D — 다른 진행이 덮었으면 지우지 않는다
    #   (훑는 중의 'N개 PDF 찾는 중' 갱신은 다른 글을 다시 덮는다 — 끝 신호만 본다)
    bt._progress(tr("PDF 찾는 중..."))
    mw.status.showMessage("인덱싱 1/3 - 다른 작업")
    bt._progress_done()
    spin(0.1)
    chk(mw.status.currentMessage() == "인덱싱 1/3 - 다른 작업", "D 다른 진행 메시지는 지우지 않는다",
        repr(mw.status.currentMessage()))
    mw.status.clearMessage(); spin(0.1)
    del bt.SCAN_BUDGET_MS

    # E — 단추를 눌러 생긴 알림
    bt.NOTICE_MS = 400
    bt.tree.setCurrentItem(None)
    bt.tree.clearSelection()
    wait(lambda: mw.status.currentMessage() == "", 15)
    QTest.mouseClick(bt.btn_mode, Qt.MouseButton.LeftButton)   # 폴더 → 파일: 고른 파일이 없으면 알림
    spin(0.1)
    msg = mw.status.currentMessage()
    chk(msg == tr("파일 모드로 볼 파일을 먼저 선택하세요.") and not lbl.isVisible(),
        "E 알림은 상태 표시줄에 뜨고 그동안 개수가 숨는다", repr(msg))
    spin(0.7)
    chk(mw.status.currentMessage() == "" and lbl.isVisible() and lbl.text() == want,
        "E 알림은 시간이 지나면 사라지고 개수가 돌아온다", repr(mw.status.currentMessage()))
    del bt.NOTICE_MS

    # F — 2단
    mw.open_folder(tmp)
    wait(lambda: bt.tree.topLevelItemCount() == 3)
    mw._toggle_split(True)
    rt = mw.bookmark_tree_right
    wait(lambda: not rt.isHidden() and rt.count_text() != "")
    spin(0.3)
    both = tr('위 {top} · 아래 {bottom}').format(top=want, bottom=want)
    chk(lbl.text() == both, "F 아래 책갈피창이 보이면 '위 … · 아래 …'", repr(lbl.text()))
    chk(bottom(rt.tree) == bottom(mw._panes[0]) == bottom(mw.page_thumbs), "F 아래 책갈피창의 아래 끝도 본문 창 틀·썸네일과 같다",
        f"{bottom(rt.tree)} vs pane {bottom(mw._panes[0])} mv {bottom(mw._mv[0])} thumbs {bottom(mw.page_thumbs)}")
    mw._toggle_split(False)
    spin(0.3)
    chk(lbl.text() == want, "F 1단으로 돌아가면 위 창 것만", repr(lbl.text()))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL PASS" if not fails else f"FAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)
