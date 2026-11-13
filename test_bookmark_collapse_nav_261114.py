# -*- coding: utf-8 -*-
"""261114-3: '책갈피 모두 접기' 상태에서 ↑↓ 로 파일을 옮겨 다닐 때 책갈피를 펼치지 않는다 (책갈피창·저장 SOT §4.7.3).

사용자 지시: "책갈피창에서 '책갈피 모두 접기'를 선택한 상태에서 책갈피창에서 위아래로 커서를 움직여 파일이 선택되었을 때,
자동으로 책갈피를 펼치지 않도록 수정해. 다만. 해당 파일에서 엔터나 마우스 버튼을 누르거나, 우측키를 누를 때 펼쳐지게 해.
즉, 빠르게 위아래 파일을 이동하며 표지만 볼 수 있도록 하려는 거야."

종전: ↓ 로 파일 줄에 오면 본문이 그 파일을 연 뒤 `select_for_page` 가 책갈피를 읽어 파일 줄을 펼치고 첫 책갈피를 골라,
다음 ↓ 가 그 파일 안 책갈피로 들어갔다.

A. 모두 접기 → ↓ : 본문은 다음 파일 첫 쪽(표지), 파일 줄은 접힌 채 그 줄이 골라져 있다 · 다음 ↓ 는 다음 파일로
B. 빠르게 ↓↑ 연타 — 가장 긴 멈춤 < 1초(응답성 SOT), 끝나면 본문이 고른 줄의 파일(밀리지 않는다), 펼친 파일 없음
C. → 는 그 파일 줄을 펼친다 · D. 마우스 누름은 펼친다 · E. Enter 는 펼친다
F. 우클릭 메뉴 '책갈피 모두 접기' 가 상태를 체크로 · G. '모두 펼치기' 를 고르면 접기 상태가 꺼진다(종전 동작 그대로)
"""
import os, sys, time, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(240, exit=True)
from pathlib import Path

import fitz
from PyQt6.QtCore import Qt, QStandardPaths, QCoreApplication, QTimer, QElapsedTimer
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
import modal_guard
modal_guard.install(label=lambda: "모두 접기 ↑↓", echo=False)   # 검사 작성 SOT §14.7.2 의 6 — 뜬 물음·모달은 닫는다
QStandardPaths.setTestModeEnabled(True)               # 검사 작성 SOT §14.7.2 의 3 — 실제 설정 폴더를 쓰지 않는다
QCoreApplication.setApplicationName("polypdf_collapse_nav_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(ms=300):
    t = time.perf_counter()
    while (time.perf_counter() - t) * 1000 < ms:
        app.processEvents(); QTest.qWait(10)


root = Path(tempfile.mkdtemp(prefix="polypdf_collapse_nav_"))
try:
    names = [f"f{i}" for i in range(6)]
    for n in names:
        d = fitz.open()
        for k in range(4):
            d.new_page().insert_text((50, 80), f"{n} p{k}")
        d.set_toc([[1, f"{n} 장1", 1], [2, f"{n} 절", 2], [1, f"{n} 장2", 3]])
        d.save(str(root / f"{n}.pdf")); d.close()

    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1200, 800); mw.show(); app.processEvents()
    bt = mw.bookmark_tree; mv = mw.main_view
    bt.load_folder(root); spin(800)
    try:
        bt.set_tree_view(False)
        bt.set_sort_mode(bt.SORT_NAME)
    except Exception:
        pass
    bt.btn_edit.setChecked(False); spin(200)
    files = list(bt._iter_file_nodes())
    chk(len(files) == 6, "준비 — 파일 6개", str(len(files)))
    row = {Path(n.data(0, bt.DATA_FILE)).stem: n for n in files}

    def menu_action(text, it):
        """우클릭 메뉴를 실제로 짓고 그 항목을 돌려준다(exec 는 띄우지 않는다)."""
        got = {}
        orig = QMenu.exec

        def fake_exec(menu, *a, **k):
            for x in menu.actions():
                if x.text() == text:
                    got["a"] = x
            return None
        QMenu.exec = fake_exec
        try:
            bt._on_tree_context_menu(bt.tree.visualItemRect(it).center())
        finally:
            QMenu.exec = orig
        return got.get("a")

    def cur_file():
        f = mv.current_file()
        return Path(f).stem if f else None

    def cur_row():
        it = bt.tree.currentItem()
        return it, (Path(it.data(0, bt.DATA_FILE)).stem if it is not None and it.data(0, bt.DATA_FILE) else None)

    def wait_file(stem, ms=3000):
        t = time.perf_counter()
        while cur_file() != stem and (time.perf_counter() - t) * 1000 < ms:
            spin(30)
        spin(150)
        return cur_file() == stem

    # 첫 파일을 열어 두고 모두 접기(메뉴 항목을 실제로 누른다)
    bt.tree.setFocus()
    bt.tree.setCurrentItem(row["f0"]); wait_file("f0"); spin(300)
    act = menu_action("책갈피 모두 접기", row["f0"])
    chk(act is not None, "준비 — 우클릭에 '책갈피 모두 접기'")
    act.trigger(); spin(200)
    chk(not any(n.isExpanded() for n in bt._iter_file_nodes()), "준비 — 모두 접혀 파일 줄만 남는다")
    bt.tree.setCurrentItem(row["f0"]); spin(300)

    # ── A ──
    bt.tree.setFocus()
    QTest.keyClick(bt.tree, Qt.Key.Key_Down)
    ok = wait_file("f1")
    it, stem = cur_row()
    chk(ok and mv.current_page() == 0, "A ↓ → 본문은 다음 파일의 첫 쪽(표지)", f"{cur_file()} p{mv.current_page()}")
    chk(not row["f1"].isExpanded(), "A ★ 그 파일 줄은 접힌 채(종전: 책갈피를 읽어 펼쳤다)")
    chk(it is row["f1"], "A 고른 줄은 파일 줄 그대로(종전: 안쪽 첫 책갈피로 옮겨 갔다)", f"{stem} {it.text(0) if it else None}")
    QTest.keyClick(bt.tree, Qt.Key.Key_Down)
    ok = wait_file("f2")
    chk(ok and bt.tree.currentItem() is row["f2"] and not row["f2"].isExpanded(),
        "A 다음 ↓ 는 다음 파일로(책갈피 안으로 들어가지 않는다)", f"{cur_file()} {cur_row()[1]}")

    # ── B 연타 + 하트비트 ──
    beat = QElapsedTimer(); beat.start(); worst = [0]

    def tick():
        worst[0] = max(worst[0], beat.restart())
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(tick); hb.start()
    spin(100); worst[0] = 0; beat.restart()
    seq = [Qt.Key.Key_Down] * 3 + [Qt.Key.Key_Up] * 5 + [Qt.Key.Key_Down] * 4   # f2 → f5 → f0 → f4
    for k in seq:
        QTest.keyClick(bt.tree, k); app.processEvents(); QTest.qWait(15)
    ok = wait_file("f4")
    hb.stop()
    chk(ok and bt.tree.currentItem() is row["f4"], "B 연타 뒤 본문이 고른 줄의 파일(밀리지 않는다)", f"{cur_file()} {cur_row()[1]}")
    chk(not any(n.isExpanded() for n in bt._iter_file_nodes()), "B 연타 뒤에도 펼친 파일 없음",
        str([Path(n.data(0, bt.DATA_FILE)).stem for n in bt._iter_file_nodes() if n.isExpanded()]))
    chk(worst[0] < 1000, "B 가장 긴 멈춤 < 1초(응답성 SOT)", f"{worst[0]}ms")
    print(f"  실측: 연타 {len(seq)}번 동안 가장 긴 멈춤 {worst[0]}ms")

    # ── C → ──
    QTest.keyClick(bt.tree, Qt.Key.Key_Right); spin(600)
    chk(row["f4"].isExpanded() and row["f4"].childCount() >= 2, "C → 는 그 파일 줄을 펼친다(책갈피가 보인다)",
        f"exp={row['f4'].isExpanded()} n={row['f4'].childCount()}")

    # ── D 마우스 누름 ──
    r = bt.tree.visualItemRect(row["f1"])
    QTest.mouseClick(bt.tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
    ok = wait_file("f1"); spin(400)
    chk(ok and row["f1"].isExpanded(), "D 마우스로 누른 파일은 펼친다", f"{cur_file()} exp={row['f1'].isExpanded()}")

    # ── E Enter ──
    menu_action("책갈피 모두 접기", row["f1"]).trigger(); spin(200)
    bt.tree.setFocus()
    QTest.keyClick(bt.tree, Qt.Key.Key_Home)            # 목록 첫 줄(f0) — 본문도 따라간다(입력 SOT §3)
    ok = wait_file("f0")
    chk(ok and bt.tree.currentItem() is row["f0"] and not row["f0"].isExpanded(), "E 준비 — Home 으로 f0, 접힌 채",
        f"{cur_file()} {cur_row()[1]} exp={row['f0'].isExpanded()}")
    QTest.keyClick(bt.tree, Qt.Key.Key_Return); spin(600)
    chk(row["f0"].isExpanded() and cur_file() == "f0", "E Enter 는 그 파일 줄을 펼친다",
        f"exp={row['f0'].isExpanded()} {cur_file()}")

    # ── F 메뉴 체크 ──
    a = menu_action("책갈피 모두 접기", row["f0"])
    chk(a is not None and a.isCheckable() and a.isChecked(), "F 우클릭 '책갈피 모두 접기' 가 상태를 체크로 보여 준다")

    # ── G 모두 펼치기 → 접기 상태 꺼짐 ──
    menu_action("책갈피 모두 펼치기", row["f0"]).trigger(); spin(800)
    a = menu_action("책갈피 모두 접기", row["f0"])
    chk(a is not None and not a.isChecked() and bt.is_expand_all_mode(), "G 모두 펼치기를 고르면 접기 상태가 꺼진다")
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
