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
    mw.open_pdfs([A, B, C, A, root / "없음.pdf"]); spin(10)
    chk(bt._is_file_mode() and tops() == ["A", "B", "C"],
        "A 여러 파일을 **파일 모드** 한 목록에(받은 순서·중복·없는 파일 제외)", str(tops()))
    chk(Path(mw.main_view.current_file()).name == "A.pdf", "A 첫 파일을 본문에 연다")
    chk(len(mw._search_scope or ()) == 3, "A 검색 범위는 그 파일들", str(mw._search_scope))
    chk("3개 파일" in bt.info.text(), "A 책갈피창에 파일 수", bt.info.text())
    it = bt.tree.topLevelItem(1); bt.tree.setCurrentItem(it); bt.tree.itemClicked.emit(it, 0); spin(15)
    chk(Path(mw.main_view.current_file()).name == "B.pdf", "A 목록의 다른 파일을 누르면 그 파일이 열린다",
        str(mw.main_view.current_file()))

    mw.add_pdfs([C, D]); spin(8)
    chk(tops() == ["A", "B", "C", "D"] and Path(mw.main_view.current_file()).name == "B.pdf",
        "A 모아 받은 파일은 목록 **뒤에** 붙고 보던 파일은 그대로", str(tops()))
    chk(len(mw._search_scope or ()) == 4, "A 더한 파일도 검색 범위에")

    bt.tree.setCurrentItem(bt.tree.topLevelItem(1)); spin(2)
    bt._toggle_view_mode(); spin(15)
    chk(not bt._is_file_mode() and Path(bt._root_dir).name == "y", "A '폴더 모드로' 는 **고른 파일**의 폴더",
        str(bt._root_dir))

    mw.open_pdf(A); spin(8)
    chk(bt._is_file_mode() and tops() == ["A"] and "단일 파일" in bt.info.text(), "A 하나만 열면 종전과 같다")

    md = QMimeData(); md.setUrls([QUrl.fromLocalFile(str(C)), QUrl.fromLocalFile(str(B))])
    ev = QDropEvent(QPointF(50, 50), Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    mw.dropEvent(ev); spin(10)
    chk(tops() == ["C", "B"] and Path(mw.main_view.current_file()).name == "C.pdf",
        "A 창에 PDF 여러 개를 끌어 놓으면 모두 파일 모드로", str(tops()))
    md1 = QMimeData(); md1.setUrls([QUrl.fromLocalFile(str(D))])
    mw.dropEvent(QDropEvent(QPointF(50, 50), Qt.DropAction.CopyAction, md1, Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)); spin(8)
    chk(tops() == ["D"], "A 하나를 끌어 놓으면 종전과 같다", str(tops()))

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
