# -*- coding: utf-8 -*-
"""261114-12: '책갈피 모두 접기' 체크 중 앱이 파일 줄을 다시 읽어도 펼치지 않는다 (책갈피창·저장 SOT §4.7.3).

사용자 보고: "책갈피창이 접은 상태로 체크되어 있는데, 접은 상태가 아님" — 편집 모드에서 연 파일의 책갈피가 펼쳐진 채,
우클릭 메뉴는 '☑ 책갈피 모두 접기'. 재현: 저장·변환·복사·되돌리기 뒤 그 파일 줄을 다시 읽는 길(`add_or_refresh_file` →
`_refresh_file_toc`, `restore_bookmarks`)이 늘 펼쳤다.

A. 다시 읽기(add_or_refresh_file) — 접힌 줄은 접힌 채
B. 실제 편집 모드 [저장](문서 정보 고침 보류 → 💾) 뒤 그 파일 줄이 접힌 채
C. 사용자가 → 로 펼친 줄은 다시 읽어도 펼친 채(책갈피도 다시 읽혀 있다)
D. 새로 넣은 파일 줄은 접힌 채
E. 되돌리기(restore_bookmarks) — 접힌 줄은 접힌 채
F. 상태가 꺼져 있으면 종전대로 다시 읽을 때 펼친다
"""
import os, sys, time, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(300, exit=True)
from pathlib import Path

import fitz
from PyQt6.QtCore import Qt, QStandardPaths, QCoreApplication
from PyQt6.QtWidgets import QApplication, QMenu
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QStandardPaths.setTestModeEnabled(True)               # 검사 작성 SOT §14.7.2 의 3
QCoreApplication.setApplicationName("polypdf_collapse_keep_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "모두 접기 유지", echo=False)   # §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(ms=300):
    t = time.perf_counter()
    while (time.perf_counter() - t) * 1000 < ms:
        app.processEvents(); QTest.qWait(5)


root = Path(tempfile.mkdtemp(prefix="polypdf_collapse_keep_"))
try:
    for i in range(4):
        d = fitz.open()
        for k in range(5):
            d.new_page().insert_text((50, 80), f"f{i} p{k}")
        d.set_toc([[1, f"f{i} 장1", 1], [2, f"f{i} 절", 2], [1, f"f{i} 장2", 3]])
        d.set_metadata({"title": "Old"})
        d.save(str(root / f"f{i}.pdf")); d.close()

    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    bt = mw.bookmark_tree; mv = mw.main_view
    bt.load_folder(root); spin(900)
    try:
        bt.set_tree_view(False); bt.set_sort_mode(bt.SORT_NAME)
    except Exception:
        pass
    if bt.is_edit_mode():
        bt.btn_edit.setChecked(False)
    spin(200)

    def row(stem):
        for n in bt._iter_file_nodes():
            if Path(n.data(0, bt.DATA_FILE)).stem == stem:
                return n
        return None

    def menu_action(text):
        got = {}
        orig = QMenu.exec

        def fake_exec(menu, *a, **k):
            for x in menu.actions():
                if x.text() == text:
                    got["a"] = x
        QMenu.exec = fake_exec
        try:
            bt._on_tree_context_menu(bt.tree.visualItemRect(row("f0")).center())
        finally:
            QMenu.exec = orig
        return got.get("a")

    bt.tree.setFocus(); bt.tree.setCurrentItem(row("f0")); spin(900)
    menu_action("책갈피 모두 접기").trigger(); spin(200)
    chk(not any(n.isExpanded() for n in bt._iter_file_nodes()), "준비 — 모두 접힘")

    # ── A ──
    bt.add_or_refresh_file(str(root / "f2.pdf")); spin(400)
    chk(not row("f2").isExpanded(), "A ★ 다시 읽기(add_or_refresh_file) 뒤에도 접힌 채(종전: 펼침)")

    # ── B 실제 편집 모드 [저장] ──
    bt.tree.setCurrentItem(row("f0")); spin(500)
    bt.btn_edit.setChecked(True); spin(400)
    from viewer import doc_meta
    pdf0 = str(root / "f0.pdf")
    doc_meta.set_pending(pdf0, "title", "고친 제목", original="Old")
    bt._op_save(pdf0, quiet=True)
    t = time.perf_counter()
    while doc_meta.has_pending(pdf0) and time.perf_counter() - t < 15:
        app.processEvents(); QTest.qWait(20)
    spin(1500)
    with fitz.open(pdf0) as d:
        saved = d.metadata.get("title")
    chk(saved == "고친 제목", "B 준비 — 실제로 저장됐다", str(saved))
    n0 = row("f0")
    chk(n0 is not None and not n0.isExpanded() and bt.is_collapse_all_mode(),
        "B ★ 편집 모드 [저장] 뒤 그 파일 줄이 접힌 채(사용자 보고)", f"exp={n0.isExpanded() if n0 else None}")
    bt.btn_edit.setChecked(False); spin(400)

    # ── C 사용자가 펼친 줄 ──
    n1 = row("f1")
    bt.tree.setCurrentItem(n1); spin(600)
    bt.tree.setFocus()
    QTest.keyClick(bt.tree, Qt.Key.Key_Right); spin(600)
    chk(row("f1").isExpanded(), "C 준비 — → 로 펼침")
    bt.add_or_refresh_file(str(root / "f1.pdf")); spin(800)
    n1 = row("f1")
    kids = [n1.child(k).text(0) for k in range(n1.childCount())]
    chk(n1.isExpanded() and any("장1" in k for k in kids), "C 사용자가 펼친 줄은 다시 읽어도 펼친 채·책갈피도 읽혀 있다", str(kids))

    # ── D 새 파일 ──
    shutil.copy(str(root / "f3.pdf"), str(root / "f3_copy.pdf"))
    bt.add_or_refresh_file(str(root / "f3_copy.pdf"), after=str(root / "f3.pdf")); spin(600)
    n3c = row("f3_copy")
    chk(n3c is not None and not n3c.isExpanded() and not row("f3").isExpanded(),
        "D 새로 넣은 파일 줄·원본 줄 모두 접힌 채", f"{n3c.isExpanded() if n3c else None}")

    # ── E 되돌리기 ──
    n2 = row("f2")
    snap = bt._bm_snapshot(n2) if hasattr(bt, "_bm_snapshot") else None
    if snap is not None:
        bt.restore_bookmarks(str(root / "f2.pdf"), snap); spin(300)
        chk(not row("f2").isExpanded(), "E 되돌리기(restore_bookmarks) 뒤에도 접힌 채")
    else:
        chk(False, "E 준비 — _bm_snapshot 없음")

    # ── F 상태 꺼짐 — 종전대로 ──
    menu_action("책갈피 모두 펼치기").trigger(); spin(600)
    menu_action("책갈피 모두 접기").trigger(); spin(200)
    bt._collapse_all_mode = False                           # 두 메뉴 모두 안 고른 처음 상태
    bt.add_or_refresh_file(str(root / "f2.pdf")); spin(500)
    chk(row("f2").isExpanded(), "F 상태가 꺼져 있으면 종전대로 다시 읽을 때 펼친다")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
