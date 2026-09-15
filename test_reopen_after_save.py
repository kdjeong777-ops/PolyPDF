# -*- coding: utf-8 -*-
"""260915-10: 저장 뒤 다시 열기 멈춤 (응답성 SOT §4.4, 마스터 §4.7.10).

사용자 지시: "저장 뒤 다시 열기 멈춤 관련 문제가 있는지 검토해" → 실측(1000쪽·파일 300개) 저장 직후 0.57~1.17초 정지.
원인 둘 → "진행해".

A. 책갈피창 파일 노드 찾기(`add_or_refresh_file`·`add_bookmark`·`_same_file`)가 **디스크를 타지 않는다**
   (`Path.resolve` 0회) — 그러면서 슬래시·대소문자가 달라도 같은 노드를 찾는다(중복 노드 없음).
B. 저장 뒤 다시 열기는 **색인을 먼저 걸고** 연다 — 여는 순간 색인이 돌고 있어 텍스트 창 표 인식이 미뤄진다
   (쪽 편집 저장·책갈피 편집 저장·텍스트 반영 뒤 다시 읽기). 수정 전 코드로 실패 확인.
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import pathlib

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
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


def make_pdf(p, n, tag):
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((72, 72), f"{tag}{i + 1}")
    d.set_toc([[1, "처음", 1], [1, "끝", n]])
    d.save(str(p)); d.close()


root = Path(tempfile.mkdtemp(prefix="polypdf_reopen_"))
try:
    msgs = []
    QMessageBox.warning = staticmethod(lambda *a, **k: msgs.append(("w", a[2])))
    QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(("i", a[2])))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    bt, pt = mw.bookmark_tree, mw.page_thumbs
    work = root / "W"; work.mkdir()
    doc_p = work / "D.pdf"; make_pdf(doc_p, 8, "D")
    for k in range(40):
        make_pdf(work / f"f{k:02d}.pdf", 1, "f")
    mw.open_folder(work); spin(20)

    def file_nodes(p):
        return [nd for nd in bt._iter_file_nodes()
                if os.path.normcase(str(nd.data(0, bt.DATA_FILE))) == os.path.normcase(str(p))]

    # ── A. 노드 찾기가 디스크를 타지 않는다 ─────────────────────────────
    calls = [0]
    real_resolve = pathlib.Path.resolve

    def counting_resolve(self, *a, **k):
        calls[0] += 1
        return real_resolve(self, *a, **k)
    n_before = len(list(bt._iter_file_nodes()))
    variant = str(doc_p).replace("\\", "/").upper()
    pathlib.Path.resolve = counting_resolve
    try:
        bt.add_or_refresh_file(variant)
        c_refresh = calls[0]; calls[0] = 0
        new_p = work / "D_edited.pdf"; make_pdf(new_p, 3, "N")
        bt.add_or_refresh_file(str(new_p), after=variant)
        c_after = calls[0]; calls[0] = 0
        same = bt._same_file(file_nodes(doc_p)[0], variant)
        c_same = calls[0]; calls[0] = 0
    finally:
        pathlib.Path.resolve = real_resolve
    spin(4)
    chk(c_refresh == 0 and c_after == 0 and c_same == 0,
        "A 파일 노드 찾기에서 Path.resolve(디스크 조회)를 부르지 않는다", f"{c_refresh}/{c_after}/{c_same}")
    chk(len(file_nodes(doc_p)) == 1 and same, "A 슬래시·대소문자가 달라도 같은 노드(중복 노드 없음)")
    tops = list(bt._iter_file_nodes())
    names = [Path(str(nd.data(0, bt.DATA_FILE))).name for nd in tops]
    chk(len(tops) == n_before + 1 and "D_edited.pdf" in names
        and names.index("D_edited.pdf") == names.index("D.pdf") + 1,
        "A 새 파일은 원본(다른 표기로 준 경로) 바로 아래에 들어간다", str(names[:4]))

    # ── B. 색인을 먼저 걸고 연다 ──────────────────────────────────────
    seen = []
    real_load = mw._load_main

    def spy_load(item):
        seen.append((Path(item.file_path).name, bool(mw._index_workers)))
        return real_load(item)
    mw._load_main = spy_load

    def edit():
        real_load(HistoryItem(str(doc_p), 0, "", "bookmark")); spin(10)
        if not mw._in_edit():
            bt.btn_edit.setChecked(True); spin(4)
        pt.list.clearSelection(); pt.list.item(1).setSelected(True); pt._delete_selected()
        bt.tree.setCurrentItem(file_nodes(doc_p)[0]); spin(2)

    def settle():
        for _ in range(100):
            spin(1, 30)
            if not mw._index_workers:
                break
        spin(5)

    settle()
    edit(); seen.clear()
    bt._op_save()
    first = [s for s in seen if s[0] == "D.pdf"][:1]
    settle()
    chk(first and first[0][1] and not [m for t, m in msgs if t == "w"],
        "B 쪽 편집 저장 뒤 — 파일을 여는 순간 색인이 이미 돌고 있다", str(seen) + str(msgs))
    chk(len(fitz.open(str(doc_p))) == 7, "B 쪽 편집은 원본에 저장됐다")

    seen.clear()
    mw._on_bookmarks_edited(str(doc_p), str(new_p))
    ok = seen[:1] == [("D_edited.pdf", True)]
    settle()
    chk(ok, "B 책갈피 편집 저장 뒤 — 색인 먼저", str(seen))
    # 새 노드를 고르면 트리가 파일 열기를 예약한다 — 직접 여니 한 번만(종전 두 번)
    chk(len(seen) == 1, "B 책갈피 편집 저장 뒤 새 파일을 한 번만 연다", str(seen))

    seen.clear()
    mw._reload_after_text_apply(str(doc_p), 2)
    ok = seen[:1] == [("D.pdf", True)]
    settle()
    chk(ok and mw.main_view.current_page() == 2, "B 텍스트 반영 뒤 다시 읽기 — 색인 먼저·보던 쪽", str(seen))
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
