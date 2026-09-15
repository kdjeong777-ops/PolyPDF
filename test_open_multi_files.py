# -*- coding: utf-8 -*-
"""260915-3: PDF 여러 개를 열면 파일 모드 한 목록으로 (마스터 §4.9).

사용자 지시: "pdf를 2개 이상 선택하여 polypdf를 열 경우 '파일 모드'에서 해당 파일들을 모두 책갈피 창에
표시해서 열 수 있도록해" — 결정: 탐색기 다중 열기(파일마다 따로 실행)는 짧은 시간 안의 실행을 한 창으로,
창에 여러 개 끌어 놓기도 같게.

A. 앱 — open_pdfs·끌어 놓기·add_pdfs·폴더 모드 전환·하나면 종전과 같음
B. 모으기 — **실제 별도 프로세스**: 준비가 느린 대표 + 뒤따라 뜬 실행 2개 → 대표가 셋 다 받고 둘은 끝난다.
   대표가 서버를 닫은 뒤 뜬 실행은 스스로 대표가 된다(종전처럼 새 창).
"""
import os, sys, json, time, subprocess, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

# ── B 의 보조 프로세스 ────────────────────────────────────────────────
if len(sys.argv) >= 3 and sys.argv[1] in ("--primary", "--launch"):
    from PyQt6.QtCore import QCoreApplication, QTimer
    capp = QCoreApplication(sys.argv[:1])
    from viewer.open_gather import OpenGather, hand_off
    out = Path(sys.argv[2]); files = sys.argv[3:]
    g = OpenGather()
    if not g.claim():
        ok = hand_off(files)
        out.write_text(json.dumps({"role": "handed" if ok else "failed"}), encoding="utf-8")
        os._exit(0)
    if sys.argv[1] == "--primary":
        time.sleep(3.0)                      # 무거운 준비(fitz·앱) 동안 이벤트 루프가 돌지 않는다
    got = list(files)

    def opened():
        got.extend(g.pending)
        g.pending.clear()
        g.filesReceived.connect(lambda fs: got.extend(fs))
        g.close_after(1500)
        QTimer.singleShot(2500, lambda: (out.write_text(json.dumps({"role": "primary", "files": got}),
                                                        encoding="utf-8"), os._exit(0)))
    QTimer.singleShot(0, opened)
    capp.exec()
    os._exit(0)

import fitz
from PyQt6.QtCore import QStandardPaths, QMimeData, QUrl, QPointF, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QDropEvent
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=10, ms=30):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


root = Path(tempfile.mkdtemp(prefix="polypdf_open_multi_"))
try:
    (root / "x").mkdir(); (root / "y").mkdir()
    files = []
    for sub, nm in (("x", "A"), ("y", "B"), ("x", "C"), ("x", "D")):
        p = root / sub / f"{nm}.pdf"
        d = fitz.open()
        for i in range(3):
            d.new_page().insert_text((72, 72), f"{nm} {i}")
        d.save(str(p)); d.close(); files.append(p)
    A, B, C, D = files
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    bt = mw.bookmark_tree
    tops = lambda: [bt.tree.topLevelItem(i).text(0) for i in range(bt.tree.topLevelItemCount())]

    # ── A. 앱 ──────────────────────────────────────────────────────
    msgs = []
    QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(a[2]))
    mw.open_pdfs([C, A, B, C, root / "없음.pdf"]); spin(10)
    chk(bt._is_file_mode() and tops() == ["A", "B", "C"],
        "A 여러 파일을 **파일 모드** 한 목록에 — **파일명 순**·중복·없는 파일 제외", str(tops()))
    chk(Path(mw.main_view.current_file()).name == "A.pdf", "A 이름 순 첫 파일을 본문에 연다")
    chk(len(mw._search_scope or ()) == 3, "A 검색 범위는 그 파일들", str(mw._search_scope))
    chk("3개 파일" in bt.info.text(), "A 책갈피창에 파일 수", bt.info.text())
    it = bt.tree.topLevelItem(1); bt.tree.setCurrentItem(it); bt.tree.itemClicked.emit(it, 0); spin(15)
    chk(Path(mw.main_view.current_file()).name == "B.pdf", "A 목록의 다른 파일을 누르면 그 파일이 열린다",
        str(mw.main_view.current_file()))

    mw.add_pdfs([D, C]); spin(8)
    chk(tops() == ["A", "B", "C", "D"] and Path(mw.main_view.current_file()).name == "B.pdf",
        "A 모아 받은 파일도 이름 순으로 들어가고 보던 파일은 그대로", str(tops()))
    chk(len(mw._search_scope or ()) == 4, "A 더한 파일도 검색 범위에")

    bt.tree.setCurrentItem(bt.tree.topLevelItem(1)); spin(2)
    bt._toggle_view_mode(); spin(15)
    chk(not bt._is_file_mode() and Path(bt._root_dir).name == "y", "A '폴더 모드로' 는 **선택된 파일**의 폴더",
        str(bt._root_dir))
    mw.open_pdf(B); spin(8)
    bt._single_file = A                            # 파일 모드로 연 파일과 선택이 다를 때(하나뿐이어도)
    bt._toggle_view_mode(); spin(15)
    chk(Path(bt._root_dir).name == "y", "A 파일 하나여도 **선택된 파일** 기준(종전: 파일 모드로 연 파일)",
        str(bt._root_dir))

    mw.open_pdf(A); spin(8)
    chk(bt._is_file_mode() and tops() == ["A"] and "단일 파일" in bt.info.text(), "A 하나만 열면 종전과 같다")

    def mime(*paths):
        md = QMimeData(); md.setUrls([QUrl.fromLocalFile(str(x)) for x in paths]); return md

    def drop_on(widget, *paths):
        md = mime(*paths)                          # QDropEvent 는 QMimeData 를 소유하지 않는다 — 붙잡아 둔다
        widget.dropEvent(QDropEvent(QPointF(40, 40), Qt.DropAction.CopyAction, md,
                                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        spin(10)

    drop_on(bt.tree, C, B)                         # 실제 책갈피창 드롭 처리기
    chk(tops() == ["A", "B", "C"] and Path(mw.main_view.current_file()).name == "A.pdf",
        "B 책갈피창에 여러 개 놓으면 **지금 목록에 더한다**(이름 순, 본문 그대로)", str(tops()))
    drop_on(mw.main_view.view, D)                  # 실제 본문 드롭 처리기
    chk(tops() == ["A", "B", "C", "D"] and Path(mw.main_view.current_file()).name == "A.pdf",
        "B 본문에 놓아도 목록에 더한다(사용자 결정)", str(tops()))
    drop_on(bt.tree, B)
    chk(tops() == ["A", "B", "C", "D"], "B 이미 있는 파일은 다시 넣지 않는다")
    cur_node = bt.tree.currentItem()
    chk(cur_node is not None and bt._file_node_of(cur_node).text(0) == "A", "B 더한 뒤에도 보던 파일이 선택돼 있다",
        cur_node.text(0) if cur_node else "")

    bt.tree.setCurrentItem(bt.tree.topLevelItem(0)); spin(2)
    bt._toggle_view_mode(); spin(15)
    chk(not bt._is_file_mode(), "준비 — 폴더 모드(x)")
    drop_on(bt.tree, B)
    chk(bt._is_file_mode() and tops() == ["A", "B"] and Path(mw.main_view.current_file()).name == "A.pdf",
        "B 폴더 모드에서 놓으면 **보던 파일 + 놓은 파일** 파일 모드 목록", str(tops()))

    _md = mime(C)
    mw.dropEvent(QDropEvent(QPointF(40, 40), Qt.DropAction.CopyAction, _md,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)); spin(8)
    chk(tops() == ["A", "B", "C"], "B 창(그 밖의 자리)에 놓아도 같은 규칙", str(tops()))

    bt._dirty = True
    msgs.clear()
    drop_on(bt.tree, D)
    chk(tops() == ["A", "B", "C"] and msgs and "저장하지 않은 편집" in msgs[-1],
        "B 책갈피창에 저장 안 한 편집이 있으면 더하지 않고 알린다", str(msgs))
    bt._dirty = False

    drop_on(bt.tree, root / "y")
    chk(not bt._is_file_mode() and Path(bt._root_dir).name == "y", "B 폴더를 놓으면 종전대로 그 폴더를 연다",
        str(bt._root_dir))

    # ── A2. 폴더 목록을 채우는 중에 파일 모드로 열기 — 종전에는 앱이 죽었다 ──────────
    #   실측(빌드 exe): 시작 때 복원한 폴더를 채우는 중 PDF 인자로 열면 채우기 틱이 지운 행에 붙이다
    #   RuntimeError → 0xC0000409. load_single_pdf·load_pdf_files 가 채우기를 먼저 멈춘다.
    many = root / "many"; many.mkdir()
    for i in range(1500):                          # 하위 폴더 + 트리 보기 — 폴더 행 밑에 붙이는 길(_fill_folder_item)
        sub = many / f"s{i // 50:02d}"; sub.mkdir(exist_ok=True)
        shutil.copyfile(str(A), str(sub / f"m{i:04d}.pdf"))
    bt.set_tree_view(True)
    errs = []
    old_hook = sys.excepthook
    sys.excepthook = lambda t, v, tb: errs.append(f"{t.__name__}: {v}")
    try:
        for opener in (lambda: mw.open_pdf(B), lambda: mw.open_pdfs([B, C])):
            bt._fill_timer.stop()
            mw.open_folder(many); app.processEvents()
            filling = bt._fill_timer.isActive() or bool(getattr(bt, "_fill_plan", None)) or \
                bool(getattr(bt, "_scan_worker", None))
            chk(filling, "준비 — 폴더 목록이 아직 채워지는 중이다")
            opener(); spin(40, 20)
            chk(bt._is_file_mode() and not errs, "A2 채우는 중 파일 모드로 열어도 오류가 없다", str(errs[:2]))
            errs.clear()
    finally:
        sys.excepthook = old_hook
    shutil.rmtree(many, ignore_errors=True)

    # ── B. 모으기(별도 프로세스) ──────────────────────────────────────
    env = dict(os.environ, POLYPDF_OPEN_GATHER_NAME=f"polypdf-open-test-{os.getpid()}")
    me = os.path.abspath(__file__)
    cwd = os.path.dirname(me)
    outs = [root / f"o{i}.json" for i in range(4)]
    p0 = subprocess.Popen([sys.executable, me, "--primary", str(outs[0]), str(A)], cwd=cwd, env=env)
    time.sleep(0.8)                              # 대표가 잠금을 잡은 뒤 탐색기가 나머지를 띄운다
    p1 = subprocess.Popen([sys.executable, me, "--launch", str(outs[1]), str(B)], cwd=cwd, env=env)
    p2 = subprocess.Popen([sys.executable, me, "--launch", str(outs[2]), str(C)], cwd=cwd, env=env)
    for p in (p0, p1, p2):
        p.wait(60)
    res = [json.loads(o.read_text(encoding="utf-8")) if o.exists() else {} for o in outs[:3]]
    chk(res[0].get("role") == "primary" and sorted(Path(f).name for f in res[0].get("files", [])) ==
        ["A.pdf", "B.pdf", "C.pdf"], "B 대표가 **준비 중에도** 뒤따라 뜬 실행의 파일을 모두 받는다", str(res))
    chk(res[1].get("role") == "handed" and res[2].get("role") == "handed",
        "B 나머지 실행은 넘기고 창 없이 끝난다", str(res[1:]))
    p3 = subprocess.Popen([sys.executable, me, "--launch", str(outs[3]), str(D)], cwd=cwd, env=env)
    p3.wait(60)
    r3 = json.loads(outs[3].read_text(encoding="utf-8")) if outs[3].exists() else {}
    chk(r3.get("role") == "primary" and [Path(f).name for f in r3.get("files", [])] == ["D.pdf"],
        "B 모으는 시간이 끝난 뒤 연 PDF 는 **스스로 새 창**(종전과 같다)", str(r3))
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
