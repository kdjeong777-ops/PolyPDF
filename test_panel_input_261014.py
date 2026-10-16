# -*- coding: utf-8 -*-
"""261014-1: 창마다의 입력과 책갈피창 우클릭·정렬 (입력 SOT §2.11·§3.1, 마스터 §4.7.13, 디자인 SOT §2.8).

사용자 요청
  - 텍스트 창에서 굴리던 남은 휠이 마우스를 본문으로 옮기면 본문을 움직였다 → 휠은 그 창에서만.
  - 책갈피창 우클릭 메뉴 순서·이름('파일 탐색기 열기', '새 폴더 만들기').
  - 트리 + 수정일 순이면 폴더를 위로 모으지 않고 폴더·파일을 함께 수정일 순으로.
  - 선택 포인트(포커스) 이동과 Tab 차례 검토 — 본문 페이지 바의 Tab 이 보이는 차례와 달랐고,
    텍스트 창 편집기는 Tab 을 탭 문자로 먹어 빠져나갈 수 없었다.
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, Qt, QPoint, QPointF
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu, QWidget
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=8):
    for _ in range(n):
        app.processEvents(); QTest.qWait(30)


def make_pdf(path, n=3, label="P"):
    path.parent.mkdir(parents=True, exist_ok=True)
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((72, 72), f"{label} {i + 1} " + "text " * 40)
    d.save(str(path)); d.close()


def wheel(w, dy=-120, phase=Qt.ScrollPhase.NoScrollPhase):
    c = QPointF(w.rect().center())
    ev = QWheelEvent(c, QPointF(w.mapToGlobal(c.toPoint())), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, phase, False)
    QApplication.sendEvent(w, ev)


root = Path(tempfile.mkdtemp(prefix="polypdf_input261014_"))
try:
    # 수정일: F2/c(300) > b(200) > F1/a(100) > F1/sub/d(50) — 루트 층은 F2 · b · F1 이어야 한다
    t0 = time.time() - 10000
    for rel, dt in (("F1/a.pdf", 100), ("b.pdf", 200), ("F2/c.pdf", 300), ("F1/sub/d.pdf", 50)):
        p = root / rel
        make_pdf(p, 3, p.stem)
        os.utime(p, (t0 + dt, t0 + dt))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1500, 950); mw.show(); app.processEvents()
    bt = mw.bookmark_tree
    bt.set_sort_mode(bt.SORT_MTIME)
    if not bt.is_tree_view():
        bt.set_tree_view(True)
    mw.open_folder(root); spin(20)

    # ── 트리 + 수정일 순: 폴더와 파일을 함께 ───────────────────────────────
    T = bt.tree
    top = [T.topLevelItem(i).text(0) for i in range(T.topLevelItemCount())]
    chk(top == ["F2", "b", "F1"], "트리+수정일 순 — 폴더·파일을 함께 최신순(F2 · b · F1)", str(top))
    f1 = next(T.topLevelItem(i) for i in range(T.topLevelItemCount()) if T.topLevelItem(i).text(0) == "F1")
    kids = [f1.child(i).text(0) for i in range(f1.childCount())]
    chk(kids == ["a", "sub"], "트리+수정일 순 — 하위 층도 같은 규칙(a(100) · sub(50))", str(kids))
    bt.set_sort_mode(bt.SORT_NAME); spin(10)
    top = [T.topLevelItem(i).text(0) for i in range(T.topLevelItemCount())]
    chk(top == ["F1", "F2", "b"], "이름 순은 종전대로 폴더 먼저", str(top))
    bt.set_sort_mode(bt.SORT_MTIME); spin(10)

    # ── 우클릭 메뉴 차례 ─────────────────────────────────────────────
    menus = []

    def fake_exec(self, *a, **k):
        menus.append(["-" if x.isSeparator() else x.text() for x in self.actions()])
        return None
    _orig_exec = QMenu.exec
    QMenu.exec = fake_exec
    try:
        bfile = next(n for n in bt._iter_file_nodes() if Path(n.data(0, bt.DATA_FILE)).name == "b.pdf")
        bt.btn_edit.setChecked(True); spin(4)
        bt._on_tree_context_menu(T.visualItemRect(bfile).center()); spin(2)
    finally:
        QMenu.exec = _orig_exec
    m = menus[-1] if menus else []
    want = ["파일 탐색기 열기", "새 폴더 만들기...", "파일 복사 (1개)", "파일 이동 (1개)",
            "파일·책갈피 이름 변경", "파일·책갈피 삭제", "-",
            "저장", "다른 이름으로 저장...", "평탄화해서 내보내기...", "변환해서 내보내기...",   # 261016-1 하위 메뉴 없이
            "용량 줄여 내보내기...", "개인정보 지우고 별도 저장...", "-",   # 261016-1(마스터 §4.7.13) — OCR 은 '책갈피 생성' 아래
            "2단 보기", "책갈피 모두 펼치기", "책갈피 모두 접기"]
    chk(m[:len(want)] == want, "우클릭 메뉴 차례(파일 그룹 · 저장 그룹 · 보기 그룹)", str(m[:len(want) + 2]))
    chk("파일 폴더 열기" not in m and "이 폴더 안에 새 폴더..." not in m, "옛 이름·겹친 항목 없음")

    # ── 새 폴더 만들기: 누른 파일이 든 폴더 아래 ─────────────────────────
    from PyQt6.QtWidgets import QInputDialog
    QInputDialog.getText = staticmethod(lambda *a, **k: ("새폴더X", True))
    picked = {}

    def pick_new(self, *a, **k):
        for x in self.actions():
            if x.text() == "새 폴더 만들기...":
                return x
        return None
    QMenu.exec = pick_new
    try:
        cfile = next(n for n in bt._iter_file_nodes() if Path(n.data(0, bt.DATA_FILE)).name == "c.pdf")
        bt._on_tree_context_menu(T.visualItemRect(cfile).center()); spin(2)
    finally:
        QMenu.exec = _orig_exec
    chk((root / "F2" / "새폴더X").is_dir(), "새 폴더 만들기 — 누른 파일(c)이 든 F2 아래에")

    # ── 휠은 시작한 창에서만 ─────────────────────────────────────────
    mw._load_main(HistoryItem(str(root / "b.pdf"), 0, "", "bookmark")); spin(10)
    mw._vm_text(); spin(10)
    mv = mw.main_view
    mv._zoom_by(3.0); spin(10)
    sb = mv.view.verticalScrollBar()
    sb.setValue(sb.minimum()); spin(2)
    te = mw.text_panel.edit if hasattr(mw, "text_panel") and hasattr(mw.text_panel, "edit") else None
    if te is None:
        from viewer.widgets.text_panel import _LockedLinesEdit
        te = next(w for w in mw.findChildren(_LockedLinesEdit))
    chk(sb.maximum() > sb.minimum(), "준비 — 본문을 확대해 스크롤할 자리가 있다")
    wheel(te.viewport()); wheel(te.viewport())
    v0 = sb.value()
    wheel(mv.view.viewport())                         # 곧바로(묶음 안) 본문으로 넘어온 휠
    chk(sb.value() == v0, "텍스트 창에서 굴리던 휠이 본문에 들어가지 않는다", "%d→%d" % (v0, sb.value()))
    QTest.qWait(400)                                  # 휠이 멈췄다
    wheel(mv.view.viewport())
    chk(sb.value() > v0, "휠이 멈춘 뒤에는 본문이 받는다", "%d→%d" % (v0, sb.value()))
    v1 = sb.value()
    wheel(te.viewport())
    wheel(mv.view.viewport(), phase=Qt.ScrollPhase.ScrollBegin)
    chk(sb.value() > v1, "트랙패드에서 손가락을 새로 얹으면(ScrollBegin) 바로 받는다", "%d→%d" % (v1, sb.value()))
    # 새 창에서 일부러 계속 굴리면 MAX_HOLD_MS 뒤에는 받는다(멈출 때까지 막지 않는다)
    from viewer.wheel_latch import MAX_HOLD_MS
    QTest.qWait(400)
    wheel(te.viewport())
    v3 = sb.value()
    t_end = time.monotonic() + (MAX_HOLD_MS + 400) / 1000.0
    moved_at = None
    while time.monotonic() < t_end:
        wheel(mv.view.viewport()); app.processEvents()
        if sb.value() > v3 and moved_at is None:
            moved_at = time.monotonic()
        QTest.qWait(60)                               # 60ms 마다 한 칸 — 묶음(300ms)보다 촘촘하다
    chk(moved_at is not None, "새 창에서 계속 굴리면 오래 막지 않는다(MAX_HOLD_MS 뒤 받는다)")
    # 대조: 묶음을 빼면 같은 입력이 본문을 움직인다(이 검사가 무엇을 막는지)
    QTest.qWait(400)
    app.removeEventFilter(mw._wheel_latch)
    wheel(te.viewport())
    v2 = sb.value()
    wheel(mv.view.viewport())
    chk(sb.value() > v2, "대조 — 묶음이 없으면 넘어온 휠이 본문을 움직인다", "%d→%d" % (v2, sb.value()))
    app.installEventFilter(mw._wheel_latch)

    # ── Tab 차례 ───────────────────────────────────────────────────
    mv.view.setFocus(); spin(1)
    order, w = [], mv.btn_prev_page
    for _ in range(60):
        order.append(w)
        if w is mv.view:
            break
        w = w.nextInFocusChain()
        while not (w.focusPolicy() & Qt.FocusPolicy.TabFocus) or w.focusProxy() is not None:
            w = w.nextInFocusChain()
    bar = [x for x in order if x is not mv.view and x.isVisible()]
    xs = [(x.mapTo(mv, QPoint(0, 0)).y() // 10, x.mapTo(mv, QPoint(0, 0)).x()) for x in bar]
    chk(order[-1] is mv.view and xs == sorted(xs),
        "본문 페이지 바의 Tab 차례 = 보이는 차례(줄마다 왼쪽→오른쪽) → 본문", str(xs))
    te.setFocus(); spin(1)
    before = te.toPlainText()
    QTest.keyClick(te, Qt.Key.Key_Tab); spin(1)
    chk(app.focusWidget() is not te and te.toPlainText() == before,
        "텍스트 창 편집기에서 Tab 은 다음 칸으로(탭 문자를 넣지 않는다)")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
