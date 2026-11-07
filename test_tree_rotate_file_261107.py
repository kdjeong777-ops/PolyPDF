# -*- coding: utf-8 -*-
"""261107-8: 책갈피창 PDF 파일 줄 '파일 회전 ▸' — 모든 쪽 왼쪽·오른쪽 90°·180° (마스터 §4.7.13, 기획 §5.3 ★).

실제 MainWindow(오프스크린, 시험 프로필 — 마스터 §14.7.2 의 3). 메뉴는 `QMenu.exec` 를 가로채 하위 항목을 고른다
(일은 `ctx_menu.CtxMenu.exec` 가 누른다 — 실제 처리기).
A. 파일 줄 메뉴의 '모양' 묶음에 '파일 회전 ▸'(왼쪽 90° 회전 · 오른쪽 90° 회전 · 180° 회전), 책갈피 줄·폴더 줄에는 없다
B. 본문에 없는 파일 줄에서 '오른쪽 90° 회전' → 그 파일이 본문에 열리고 **모든 쪽**이 저장 전 회전 90(쪽 회전과 같은 길),
   파일은 아직 그대로
C. 💾 저장(책갈피창 `_op_save` — 저장 한 길 `_finalize_save`) → 파일의 모든 쪽 /Rotate 90, 다른 파일은 그대로
D. 180° 를 한 번 더 → 270(누적), 저장하면 모든 쪽 270
수정 전 코드로 실패한다(메뉴에 '파일 회전' 이 없다).
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tree_rot_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "파일 회전", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


seen = {"menu": None, "pick": None}
_orig_exec = QMenu.exec


def _find(menu, path):
    """('파일 회전', '오른쪽 90° 회전') 처럼 하위 경로로 항목을 찾는다."""
    for x in menu.actions():
        if x.isSeparator():
            continue
        t = x.text().split("\t")[0]
        if t == path[0]:
            if len(path) == 1:
                return x
            return _find(x.menu(), path[1:]) if x.menu() is not None else None
    return None


def fake_exec(self, *a, **k):
    seen["menu"] = self
    p, seen["pick"] = seen["pick"], None
    return _find(self, p) if p else None


root = Path(tempfile.mkdtemp(prefix="tree_rot_"))
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", folder / "b.pdf"
    for p_ in (a, b):
        d = fitz.open()
        for i in range(3):
            d.new_page(width=595, height=842).insert_text((72, 400), "%s P%d" % (p_.stem.upper(), i + 1))
        d.set_toc([[1, "첫째", 1], [1, "둘째", 2]])
        d.save(str(p_)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    bt = mw.bookmark_tree
    QMenu.exec = fake_exec

    def node(name):
        return next(n for n in bt._iter_file_nodes() if Path(str(n.data(0, bt.DATA_FILE))).name == name)

    def menu_on(it, pick=None):
        seen["pick"] = pick
        bt.tree.scrollToItem(it)
        bt._on_tree_context_menu(bt.tree.visualItemRect(it).center())
        return seen["menu"]

    # A
    m = menu_on(node("b.pdf"))
    rot = next((x for x in m.actions() if x.text().split("\t")[0] == "파일 회전"), None) if m else None
    chk(rot is not None and rot.menu() is not None and rot.property("ctx_group") == "shape",
        "A 파일 줄 '모양' 묶음에 '파일 회전 ▸'")
    subs = [x.text().split("\t")[0] for x in rot.menu().actions()] if rot is not None and rot.menu() else []
    chk(subs == ["왼쪽 90° 회전", "오른쪽 90° 회전", "180° 회전"], "A 하위 — 왼쪽·오른쪽 90°·180°", str(subs))
    bnode = node("b.pdf")
    bnode.setExpanded(True); spin(0.5)
    if bnode.childCount():
        mb = menu_on(bnode.child(0))
        chk(mb is not None and not any(x.text().startswith("파일 회전") for x in mb.actions()), "A 책갈피 줄에는 '파일 회전' 이 없다")

    # B
    menu_on(node("b.pdf"), ("파일 회전", "오른쪽 90° 회전")); spin(1.5)
    cur = mw.main_view.current_file()
    chk(cur and Path(cur).name == "b.pdf", "B 누른 파일이 본문에 열린다", str(cur))
    st = mw._ensure_page_meta_store()
    chk(st.rotations(str(b)) == {0: 90, 1: 90, 2: 90}, "B 모든 쪽 저장 전 회전 90", str(st.rotations(str(b))))
    with fitz.open(str(b)) as f:
        chk([p.rotation for p in f] == [0, 0, 0], "B 저장 전에는 파일이 그대로")

    # C
    bt._op_save(str(b)); spin(2.0)
    with fitz.open(str(b)) as f:
        chk([p.rotation for p in f] == [90, 90, 90], "C 💾 저장 → 모든 쪽 /Rotate 90", str([p.rotation for p in f]))
    with fitz.open(str(a)) as f:
        chk([p.rotation for p in f] == [0, 0, 0], "C 다른 파일은 그대로")

    # D
    menu_on(node("b.pdf"), ("파일 회전", "180° 회전")); spin(1.0)
    bt._op_save(str(b)); spin(2.0)
    with fitz.open(str(b)) as f:
        chk([p.rotation for p in f] == [270, 270, 270], "D 180° 한 번 더 → 270(누적)", str([p.rotation for p in f]))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m_ in fails:
    print(" -", m_)
sys.stdout.flush()
os._exit(1 if fails else 0)
