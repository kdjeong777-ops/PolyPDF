# -*- coding: utf-8 -*-
"""261107-21: 우클릭 저장 ▸ 사본 넷은 저장 전 쪽 편집이 있으면 먼저 저장하라고 알린다 (마스터 §4.7.13·§4.7.7·§4.7.23).

실제 MainWindow(오프스크린, 시험 프로필 — 마스터 §14.7.2 의 3). 메뉴는 `QMenu.exec` 를 가로채 '저장 ▸' 하위 항목을 고르고
(일은 `ctx_menu.CtxMenu.exec` 가 누른다 — 실제 처리기), 사본을 만드는 함수는 부름만 기록한다.
A. 본문 — 지금 쪽을 돌려(저장 전 회전) '평탄화 사본' → 만들지 않고 알림
B. 💾 저장 뒤 같은 '평탄화 사본' → 만든다
C. 썸네일 — 쪽을 지워(저장 전 쪽 편집) '용량 줄인 사본' → 만들지 않고 알림
D. 책갈피창 — 본문 파일(편집 있음) 줄 '개인정보 지운 사본' → 알림 · 다른 파일(편집 없음) 줄 '전달 묶음' → 만든다
수정 전 코드로 실패한다(편집이 있어도 알림 없이 만든다).
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
QCoreApplication.setApplicationName("polypdf_copy_save_first_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사본 먼저 저장", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


pick = {"p": None}
_orig_exec = QMenu.exec


def _find(menu, path):
    for x in menu.actions():
        if x.isSeparator():
            continue
        t = x.text().split("\t")[0]
        if t == path[0] or (len(path) == 1 and t.startswith(path[0])):
            if len(path) == 1:
                return x
            return _find(x.menu(), path[1:]) if x.menu() is not None else None
    return None


def fake_exec(self, *a, **k):
    p, pick["p"] = pick["p"], None
    return _find(self, p) if p else None


root = Path(tempfile.mkdtemp(prefix="copy_first_"))
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", folder / "b.pdf"
    for p_ in (a, b):
        d = fitz.open()
        for i in range(3):
            d.new_page(width=595, height=842).insert_text((72, 400), "%s P%d" % (p_.stem.upper(), i + 1))
        d.save(str(p_)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    told = []
    QMessageBox.information = staticmethod(lambda *a_, **k: told.append(a_[2] if len(a_) > 2 else ""))
    calls = []
    mw._action_save_decorated_pdf = lambda *a_, file_path=None, **k: calls.append(("flat", file_path))
    mw.action_compress = lambda fs: calls.append(("comp", list(fs)))
    mw.action_redact = lambda f: calls.append(("redact", f))
    mw.action_share_files = lambda fs: calls.append(("share", list(fs)))
    bt, mv, pt = mw.bookmark_tree, mw.main_view, mw.page_thumbs
    # 책갈피창은 신호로 앱에 보낸다(연결은 시작 때 묶인 원래 함수) — 신호를 직접 받아 기록한다
    for sig, tag in ((bt.redactFileRequested, "redact"), (bt.shareFilesRequested, "share")):
        sig.disconnect()
        sig.connect(lambda x, t=tag: calls.append((t, list(x) if isinstance(x, list) else x)))
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)
    QMenu.exec = fake_exec

    def body(path):
        pick["p"] = path
        mw._on_viewer_context_menu(mv.mapToGlobal(mv.rect().center())); spin(0.3)

    # A
    mw._rotate_pages([0], 90); spin(0.5)
    chk(mw._page_edits_dirty(), "준비 — 저장 전 회전이 있다")
    body(("저장", "평탄화 사본"))
    chk(not calls and told and "저장" in told[-1], "A 본문 — 저장 전 회전이 있으면 평탄화 사본을 만들지 않고 알린다", str((calls, told)))
    # B
    bt._op_save(str(a)); spin(2.0)
    chk(not mw._page_edits_dirty(), "준비 — 저장해서 편집이 없다")
    told.clear()
    body(("저장", "평탄화 사본"))
    chk(calls == [("flat", str(a))] and not told, "B 저장 뒤에는 평탄화 사본을 만든다", str((calls, told)))
    calls.clear()
    # C
    pt.list.clearSelection(); pt.list.item(2).setSelected(True); pt._delete_selected(); spin(0.5)
    chk(mw._page_edits_dirty(), "준비 — 썸네일 쪽 삭제(저장 전)")
    pt.list.clearSelection(); pt.list.item(0).setSelected(True)
    pick["p"] = ("저장", "용량 줄인 사본")
    pt._on_list_menu(pt.list.visualItemRect(pt.list.item(0)).center()); spin(0.3)
    chk(not calls and told, "C 썸네일 — 쪽 편집이 있으면 용량 줄인 사본을 만들지 않고 알린다", str((calls, told)))
    # D
    told.clear()

    def tree(name, path):
        node = next(n for n in bt._iter_file_nodes() if Path(str(n.data(0, bt.DATA_FILE))).name == name)
        pick["p"] = path
        bt._on_tree_context_menu(bt.tree.visualItemRect(node).center()); spin(0.3)
    tree("a.pdf", ("저장", "개인정보 지운 사본"))
    chk(not calls and told, "D 책갈피창 본문 파일 줄(편집 있음) — 개인정보 지운 사본을 만들지 않고 알린다", str((calls, told)))
    told.clear()
    tree("b.pdf", ("저장", "전달 묶음"))
    chk(calls == [("share", [str(b)])] and not told, "D 책갈피창 다른 파일 줄(편집 없음) — 전달 묶음을 만든다", str((calls, told)))
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
