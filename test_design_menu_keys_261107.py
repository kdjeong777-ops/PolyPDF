# -*- coding: utf-8 -*-
"""261107-20(디자인 SOT §2.9.2 '포커스 기준 키', 사용자 결정 '보이게'): 키가 같은 일을 하는 우클릭 줄에 키 칸.

A. 본문 우클릭(편집 모드) — 새 페이지 넣기·크롭 (p.K)·책갈피 추가·하이퍼링크 등록·문서 정보·저장 ▸ 다른 이름으로 저장 에 키,
   OCR 로 읽기 에는 없다(메뉴는 그 쪽 범위를 미리 고른다 — 키와 하는 일이 다르다)
B. 썸네일 우클릭 — 크롭 (N쪽) 에 키, 새 페이지 넣기·책갈피 추가·하이퍼링크 등록 에는 없다(누른 썸네일 ↔ 키는 지금 쪽)
C. 책갈피창 우클릭 — 저장 ▸ 다른 이름으로 저장 에 키, 문서 정보 에는 없다(누른 줄 ↔ 키는 지금 본문)
D. F12 의 대상 = 메뉴와 같다 — 책갈피창 포커스면 그 창의 지금 줄 PDF, 본문 포커스면 지금 본문 PDF
종전 코드로 실패한다(키 칸이 없고, F12 는 대상 없이 불렀다).
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_menukeys261107_%d" % os.getpid())     # 마스터 §14.7.2 의 3
import modal_guard
modal_guard.install(label=lambda: "메뉴 키 261107", watch_ms=0, echo=False)        # 마스터 §14.7.2 의 6

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


seen = []


def _all(menu, out):
    for x in menu.actions():
        if x.isSeparator():
            continue
        base, _, key = x.text().partition("\t")
        out[base] = key
        if x.menu() is not None:
            _all(x.menu(), out)
    return out


def fake_exec(self, *a, **k):
    seen.append(_all(self, {}))
    return None


def has(rows, prefix):
    """prefix 로 시작하는 줄의 키(없는 줄이면 None)."""
    for t, k in rows.items():
        if t.startswith(prefix):
            return k
    return None


root = Path(tempfile.mkdtemp(prefix="menukeys261107_"))
_orig_exec = QMenu.exec
try:
    folder = root / "f"; folder.mkdir()
    a = folder / "a.pdf"
    d = fitz.open()
    for i in range(4):
        d.new_page(width=595, height=842).insert_text((72, 400), "A P%d" % (i + 1))
    d.set_toc([[1, "one", 1], [1, "two", 3]])
    d.save(str(a)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1400, 900); mw.show(); mw.activateWindow(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    bt, mv, pt = mw.bookmark_tree, mw.main_view, mw.page_thumbs
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)
    QMenu.exec = fake_exec

    # A — 본문
    mw._on_viewer_context_menu(mv.mapToGlobal(mv.rect().center())); spin(0.2)
    R = seen[-1] if seen else {}
    for name, sid in (("새 페이지 넣기", "new_page"), ("크롭 (p.", "crop"), ("책갈피 추가 (p.", "add_bookmark"),
                      ("하이퍼링크 등록 (p.", "hyperlink"), ("문서 정보", "info"), ("다른 이름으로 저장", "save_as")):
        k = has(R, name)
        chk(k == mw._sc_key(sid) and k, "A 본문 '%s' 에 키 %s" % (name, mw._sc_key(sid)), repr(k))
    chk(has(R, "OCR 로 읽기") == "", "A 본문 'OCR 로 읽기' 에는 키가 없다(하는 일이 다르다)", repr(has(R, "OCR 로 읽기")))

    # B — 썸네일
    pt.list.clearSelection(); pt.list.item(1).setSelected(True); pt.list.setCurrentRow(1)
    pt._on_list_menu(pt.list.visualItemRect(pt.list.item(1)).center()); spin(0.2)
    R = seen[-1] if seen else {}
    chk(has(R, "크롭 (") == mw._sc_key("crop") and has(R, "크롭 ("), "B 썸네일 '크롭 (N쪽)' 에 키", repr(has(R, "크롭 (")))
    for name in ("새 페이지 넣기", "책갈피 추가", "하이퍼링크 등록"):
        chk(has(R, name) in ("", None), "B 썸네일 '%s' 에는 키가 없다(누른 썸네일 ↔ 키는 지금 쪽)" % name, repr(has(R, name)))

    # C — 책갈피창
    anode = bt._file_node_for_path(str(a))
    bt.tree.setCurrentItem(anode)
    bt._on_tree_context_menu(bt.tree.visualItemRect(anode).center()); spin(0.2)
    R = seen[-1] if seen else {}
    chk(has(R, "다른 이름으로 저장") == mw._sc_key("save_as"), "C 책갈피창 저장 ▸ '다른 이름으로 저장' 에 키", repr(has(R, "다른 이름으로 저장")))
    chk(has(R, "문서 정보") in ("", None), "C 책갈피창 '문서 정보' 에는 키가 없다(누른 줄 ↔ 지금 본문)", repr(has(R, "문서 정보")))
    QMenu.exec = _orig_exec

    # D — F12 의 대상
    calls = []
    mw._action_save_as = lambda *a_, **k: calls.append(k)
    mw.activateWindow(); spin(0.1)
    bt.tree.setFocus(); bt.tree.setCurrentItem(anode); spin(0.1)
    QTest.keyClick(bt.tree, Qt.Key.Key_F12); spin(0.2)
    chk(calls and calls[-1].get("bt") is bt and calls[-1].get("file_path") == str(a),
        "D1 책갈피창 포커스 F12 → 그 창의 지금 줄 PDF(메뉴와 같은 대상)", str(calls))
    tgt = mv.view if hasattr(mv, "view") else mv
    tgt.setFocus(); spin(0.1)
    QTest.keyClick(tgt, Qt.Key.Key_F12); spin(0.2)
    chk(len(calls) >= 2 and calls[-1].get("file_path") == str(a), "D2 본문 포커스 F12 → 지금 본문 PDF", str(calls))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m_ in fails:
    print(" -", m_)
sys.stdout.flush()
os._exit(1 if fails else 0)
