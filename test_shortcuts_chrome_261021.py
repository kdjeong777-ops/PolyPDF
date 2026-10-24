# -*- coding: utf-8 -*-
"""261021-5: 크롬식 창 단축키 (입력 SOT §3·§3.2 · 디자인 SOT §2.9.2 · 마스터 §8.2 v12·§11.3).

A. 기본 키 — 새 창 Ctrl+N · 저장 Ctrl+S · 새로고침 Ctrl+R · 스크린샷 PDF Ctrl+Alt+S · 확대/축소/기본 Ctrl++/Ctrl+-/Ctrl+0, 기본 키끼리 겹치지 않는다
B. 파일 메뉴 — 새 창·저장·새로고침 항목이 그 키를 오른쪽 칸에(항목에 건 키), 종료 항목은 `종료(&X)`·Ctrl+Q(파일 탭 단추 글에서는 니모닉을 뺀다 — 261024-5)
C. 실제 키: Ctrl+S 는 파일 저장(스크린샷 PDF 아님), Ctrl+Alt+S 는 스크린샷 PDF
D. 설정 v11→v12 — 옛 기본값 Ctrl+S 로 남은 save_shots_pdf 를 Ctrl+Alt+S 로, 사용자가 바꾼 값은 그대로
E. Ctrl+R — 포커스가 있는 책갈피창의 새로고침(아래 창이면 아래 창)
F. 확대·축소·기본 크기는 포커스 창별 — 본문 배율·쪽 맞춤 / 썸네일 크기와 칸 폭 / 책갈피창 글자 / 텍스트 창 보이는 글자(스타일 크기는 그대로)
G. 기억 — prefs `view_scales`, 허용목록 통과, 다시 넣으면 그대로
H. 창 아래 오른쪽 + 0 − 단추 — 포커스를 받지 않고 포커스 창에 적용
I. Home/End — 쪽 썸네일에서 본문이 따라간다, 그림 보기는 첫/마지막 그림으로(한 장이 아니라)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QToolButton
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_chromekeys261021_%d" % os.getpid())

fails = []
CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier
NOMOD = Qt.KeyboardModifier.NoModifier


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def focus(w):
    w.setFocus(Qt.FocusReason.OtherFocusReason); spin(0.05)


root = Path(tempfile.mkdtemp(prefix="chromekeys261021_"))
try:
    folder = root / "f"; folder.mkdir()
    a = folder / "a.pdf"
    d = fitz.open()
    for i in range(6):
        d.new_page(width=595, height=842).insert_text((72, 400), "A P%d" % (i + 1))
    d.set_toc([[1, "one", 1], [1, "two", 3], [1, "three", 5]])
    d.save(str(a)); d.close()

    from viewer.app import MainWindow
    from viewer import settings_store
    shots = []
    MainWindow.action_save_screenshot_pdf = lambda self, *a_, **k: shots.append(1)   # 단축키가 묶이기 전에
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1400, 900); mw.show(); mw.activateWindow(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    mv, pt, bt = mw.main_view, mw.page_thumbs, mw.bookmark_tree

    # A — 기본 키
    D = {sid: v[1] for sid, v in mw._sc_defs.items()}
    want = {"new_window": "Ctrl+N", "save": "Ctrl+S", "refresh": "Ctrl+R", "save_shots_pdf": "Ctrl+Alt+S",
            "zoom_in": "Ctrl++", "zoom_out": "Ctrl+-", "zoom_reset": "Ctrl+0", "quit": "Ctrl+Q"}
    chk(all(D.get(k) == v for k, v in want.items()), "A1 기본 키(크롬식)", str({k: D.get(k) for k in want}))
    norm = [QKeySequence(v).toString() for v in D.values()]
    dup = sorted({k for k in norm if norm.count(k) > 1})
    chk(not dup, "A2 기본 키끼리 겹치지 않는다(겹치면 Qt 가 둘 다 듣지 않는다)", str(dup))

    # B — 파일 메뉴
    m_file = next(x.menu() for x in mw.menuBar().actions() if x.text().startswith("파일"))
    acts = {x.text().split("\t")[0]: x for x in m_file.actions() if not x.isSeparator()}
    for name, key in (("새 창", "Ctrl+N"), ("저장", "Ctrl+S"), ("새로고침", "Ctrl+R")):
        x = acts.get(name)
        chk(x is not None and x.shortcut().toString() == key, "B1 파일 메뉴 '%s' 에 %s(오른쪽 칸)" % (name, key),
            str(x.shortcut().toString() if x else list(acts)))
    chk("종료(&X)" in acts and acts["종료(&X)"].shortcut().toString() == "Ctrl+Q",
        "B2 종료 항목 종료(&X)·Ctrl+Q(탭 단추 글은 니모닉 없음)", str(list(acts)))
    chk(m_file.title() == "파일(&F)", "B3 파일 메뉴 니모닉 F")

    # C — Ctrl+S / Ctrl+Alt+S 실제 키
    saves = []
    bt._op_save = lambda *a_, **k: saves.append(1)
    focus(mv.view)
    QTest.keyClick(mv.view, Qt.Key.Key_S, CTRL); spin(0.2)
    chk(saves == [1] and not shots, "C1 Ctrl+S → 파일 저장(스크린샷 PDF 아님)", str((saves, shots)))
    QTest.keyClick(mv.view, Qt.Key.Key_S, CTRL | ALT); spin(0.2)
    chk(shots == [1] and saves == [1], "C2 Ctrl+Alt+S → 스크린샷 PDF 저장", str((saves, shots)))

    # D — 설정 마이그레이션
    old = {"schema_version": 11, "preferences": {"shortcuts": {"save_shots_pdf": "Ctrl+S", "print": "Ctrl+P"}}}
    new = settings_store._migrate(old)
    chk(settings_store.CURRENT_SCHEMA >= 12 and new["preferences"]["shortcuts"]["save_shots_pdf"] == "Ctrl+Alt+S"
        and new["preferences"]["shortcuts"]["print"] == "Ctrl+P",
        "D1 v12 — 옛 기본값 Ctrl+S 는 Ctrl+Alt+S 로 옮긴다", str(new.get("preferences")))
    mine = settings_store._migrate({"schema_version": 11, "preferences": {"shortcuts": {"save_shots_pdf": "Ctrl+K"}}})
    chk(mine["preferences"]["shortcuts"]["save_shots_pdf"] == "Ctrl+K", "D2 사용자가 바꾼 키는 그대로")

    # E — Ctrl+R
    refs = []
    bt.refresh = lambda *a_, **k: refs.append("top")
    br = mw.bookmark_tree_right
    br.refresh = lambda *a_, **k: refs.append("bottom")
    focus(bt.tree)
    QTest.keyClick(bt.tree, Qt.Key.Key_R, CTRL); spin(0.2)
    br.show(); spin(0.2); focus(br.tree)
    QTest.keyClick(br.tree, Qt.Key.Key_R, CTRL); spin(0.2)
    br.hide(); spin(0.1)
    focus(mv.view)
    QTest.keyClick(mv.view, Qt.Key.Key_R, CTRL); spin(0.2)
    chk(refs == ["top", "bottom", "top"], "E Ctrl+R — 포커스 책갈피창(없으면 위 창)의 새로고침", str(refs))

    # F — 확대·축소 대상
    focus(mv.view); spin(0.2)
    z0 = mv._zoom
    QTest.keyClick(mv.view, Qt.Key.Key_Equal, CTRL); spin(0.3)
    chk(mv._fit_mode == mv.FIT_NONE and mv._zoom > z0 * 1.1, "F1 본문 — Ctrl+= 확대(Ctrl++ 와 같이)", str((mv._fit_mode, z0, mv._zoom)))
    z1 = mv._zoom
    QTest.keyClick(mv.view, Qt.Key.Key_Minus, CTRL); spin(0.3)
    chk(mv._zoom < z1 * 0.95, "F2 본문 — Ctrl+- 축소", str((z1, mv._zoom)))
    QTest.keyClick(mv.view, Qt.Key.Key_0, CTRL); spin(0.3)
    chk(mv._fit_mode == mv.FIT_PAGE, "F3 본문 — Ctrl+0 쪽 맞춤", str(mv._fit_mode))

    w0, tw0 = pt.width(), pt._thumb_size.width()
    focus(pt.list)
    QTest.keyClick(pt.list, Qt.Key.Key_Plus, CTRL); spin(0.3)
    chk(pt._thumb_size.width() > tw0 and pt.width() > w0, "F4 썸네일 — 크기와 칸 폭이 함께 커진다", str((w0, pt.width(), pt._thumb_size)))
    chk(mv._fit_mode == mv.FIT_PAGE, "F5 썸네일 확대는 본문 배율을 건드리지 않는다")
    QTest.keyClick(pt.list, Qt.Key.Key_0, CTRL); spin(0.3)
    chk(pt.width() == w0 and pt._thumb_size.width() == tw0, "F6 썸네일 — Ctrl+0 기본 크기", str((w0, pt.width())))

    f0 = bt.tree.font().pointSizeF()
    focus(bt.tree)
    QTest.keyClick(bt.tree, Qt.Key.Key_Plus, CTRL); spin(0.2)
    f1 = bt.tree.font().pointSizeF()
    chk(f1 > f0, "F7 책갈피창 — 글자가 커진다", str((f0, f1)))
    QTest.keyClick(bt.tree, Qt.Key.Key_0, CTRL); spin(0.2)
    chk(abs(bt.tree.font().pointSizeF() - f0) < 0.01, "F8 책갈피창 — Ctrl+0 원래 크기")

    mw._vm_text(); spin(0.5)
    tp = mw.text_panel
    s0 = float(tp.styles()["body"]["size_pt"]); q0 = tp._qfont("body").pointSizeF()
    focus(tp.edit)
    QTest.keyClick(tp.edit, Qt.Key.Key_Plus, CTRL); spin(0.2)
    chk(tp._qfont("body").pointSizeF() > q0 and float(tp.styles()["body"]["size_pt"]) == s0,
        "F9 텍스트 창 — 보이는 글자만 커지고 스타일 크기(Word 저장)는 그대로",
        str((q0, tp._qfont("body").pointSizeF(), s0, tp.styles()["body"]["size_pt"])))

    # G — 기억
    vs = mw._prefs.get("view_scales") or {}
    chk(vs.get("text", 1.0) > 1.0 and abs(vs.get("thumb", 0) - 1.0) < 1e-6, "G1 prefs view_scales 에 기억", str(vs))
    mw._apply_prefs({})
    chk((mw._prefs.get("view_scales") or {}).get("text", 1.0) > 1.0, "G2 허용목록 — 환경설정 [확인] 뒤에도 남는다")
    mw._prefs["view_scales"] = {"thumb": 1.5, "bookmark": 1.0, "text": 1.0}
    mw._apply_view_scales(); spin(0.3)
    chk(pt._thumb_size.width() == round(120 * 1.5), "G3 다시 넣으면(시작) 그 크기로", str(pt._thumb_size))
    mw._prefs["view_scales"] = {}
    mw._apply_view_scales(); spin(0.2)

    # H — 아래 오른쪽 단추
    btns = getattr(mw, "_zoom_btns", [])
    chk([b.text() for b in btns] == ["+", "0", "−"], "H1 창 아래 오른쪽 + 0 − 단추", str([b.text() for b in btns]))
    chk(btns and all(b.focusPolicy() == Qt.FocusPolicy.NoFocus and isinstance(b, QToolButton) for b in btns)
        and all(b.parent() is not None and mw.status.isAncestorOf(b) for b in btns), "H2 상태 막대에, 포커스를 받지 않는다")
    if btns:
        focus(pt.list); tw = pt._thumb_size.width()
        btns[0].click(); spin(0.3)
        chk(pt._thumb_size.width() > tw and QApplication.focusWidget() is pt.list, "H3 + 단추 — 포커스 창(썸네일)에 적용, 포커스 그대로")
        btns[1].click(); spin(0.3)
        chk(pt._thumb_size.width() == tw, "H4 0 단추 — 기본 크기")
        chk("Ctrl++" in btns[0].toolTip(), "H5 툴팁에 지금 키", btns[0].toolTip())

    # I — Home/End
    mw._on_bookmark_activated(str(a), 0); spin(0.8)
    mv = mw.main_view
    focus(pt.list); pt.list.setCurrentRow(0)
    QTest.keyClick(pt.list, Qt.Key.Key_End, NOMOD); spin(0.4)
    chk(mv.current_page() == 5, "I1 썸네일 End — 본문이 마지막 쪽으로", str(mv.current_page()))
    QTest.keyClick(pt.list, Qt.Key.Key_Home, NOMOD); spin(0.4)
    chk(mv.current_page() == 0, "I2 썸네일 Home — 본문이 첫 쪽으로", str(mv.current_page()))
    got = []
    mv.imageStepRequested.connect(lambda s: got.append(s))
    mv._is_image = True
    try:
        mv._on_page_step(+10 ** 6); mv._on_page_step(-10 ** 6)
    finally:
        mv._is_image = False
    chk(got == [10 ** 6, -10 ** 6], "I3 그림 보기 End/Home — 끝까지(종전엔 한 장)", str(got))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
