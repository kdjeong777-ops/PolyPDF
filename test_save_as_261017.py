# -*- coding: utf-8 -*-
"""261017-15: '다른 이름으로 저장' 이 원본을 덮어쓰지 않는다 · 새 이름에도 꾸밈이 따라간다 · 다시 열기 한 번 · 아래 책갈피창 저장 훅
(마스터 §4.7.9·§4.7.13, SOT 전체 점검에서 나온 결함).

A. 쪽 편집(저장 전 쪽 지우기)이 있는 채 '다른 이름으로 저장' → 원본 쪽 수 그대로, `_edited` 새 파일에 편집 반영
   (종전: 쪽 편집 저장이 키보드 Shift 만 봐 메뉴 깃발을 무시하고 **원본을 덮어썼다**)
B. 꾸밈만 바꾼 채 '다른 이름으로 저장' → 원본 바이트 그대로, 새 파일이 생기고 그 키에 꾸밈이 있다, 다시 열기는 한 번
   (종전: 이 가지는 사본을 원본에 넣고 끝나 원본을 덮어썼고, 새 이름 길은 꾸밈을 옮기지 않았고, 사본이 한 번 더 열었다)
C. 아래(2창) 책갈피창에도 저장·파일 작업 훅과 bookmarksEdited 연결이 있다
"""
import os, sys, tempfile, shutil, time, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_saveas261017_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def edited(folder, stem):
    return sorted(p for p in folder.glob(stem + "_edited*.pdf"))


root = Path(tempfile.mkdtemp(prefix="saveas261017_"))
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", folder / "b.pdf"
    for p_ in (a, b):
        d = fitz.open()
        for i in range(3):
            d.new_page(width=595, height=842).insert_text((72, 400), "%s P%d" % (p_.stem.upper(), i + 1))
        d.set_toc([[1, "one", 1], [1, "two", 2]])
        d.save(str(p_)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    QMessageBox.warning = staticmethod(lambda *a_, **k: None)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    bt = mw.bookmark_tree
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)

    # A — 쪽 편집 + 다른 이름으로 저장
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    pt = mw.page_thumbs
    pt.list.clearSelection(); pt.list.item(1).setSelected(True); pt._delete_selected(); spin(0.3)
    h_a = sha(a)
    mw._action_save_as(); spin(4.0)
    ea = edited(folder, "a")
    chk(sha(a) == h_a and fitz.open(str(a)).page_count == 3, "A1 원본 a.pdf 는 그대로(3쪽) — 덮어쓰지 않는다")
    chk(len(ea) == 1 and fitz.open(str(ea[0])).page_count == 2, "A2 새 파일 a_edited 에 쪽 편집(2쪽)", str(ea))

    # B — 꾸밈만 + 다른 이름으로 저장
    mw._on_bookmark_activated(str(b), 0); spin(1.0)
    mv = mw.main_view
    mv.go_to_page(0); spin(0.3)
    mv._page_strokes = [{"text_box": True, "rect": [0.1, 0.1, 0.4, 0.16], "text": "DECO", "size_pt": 12}]
    mv._save_page_strokes(); mw._edit_dirty = True
    h_b = sha(b)
    opens = []
    _orig_open = mw._open_saved_file
    mw._open_saved_file = lambda *a_, **k: (opens.append(a_), _orig_open(*a_, **k))[1]
    mw._action_save_as(); spin(4.0)
    mw._open_saved_file = _orig_open
    eb = edited(folder, "b")
    chk(sha(b) == h_b, "B1 꾸밈만 바꿔 '다른 이름으로 저장' — 원본 b.pdf 바이트 그대로")
    chk(len(eb) == 1, "B2 새 파일 b_edited 가 생긴다", str(eb))
    if eb:
        st = mw._ensure_page_meta_store()
        chk([s.get("text") for s in st.get_drawings(str(eb[0]), 0)] == ["DECO"], "B3 새 파일 키에도 꾸밈이 있다(새 이름으로 옮김)")
        chk(fitz.open(str(eb[0])).get_toc(simple=True)[:2] == [[1, "one", 1], [1, "two", 2]], "B4 새 파일 책갈피 그대로")
    chk(len(opens) == 1, "B5 저장 한 번에 다시 열기 한 번", str(len(opens)))

    # C — 아래 책갈피창 훅
    br = mw.bookmark_tree_right
    chk(br._finalize_save is not None and br._after_save is not None and br._file_op is not None,
        "C1 아래 책갈피창에도 저장·사본·파일 작업 훅")
    mw._force_save_as = True
    _seen = br._is_save_as()
    mw._force_save_as = False
    chk(_seen and not br._is_save_as(), "C2 아래 책갈피창도 '다른 이름으로 저장' 깃발을 본다")
    chk(br.receivers(br.bookmarksEdited) > 0, "C3 아래 책갈피창 bookmarksEdited 가 연결돼 있다")

    # D — 이름 변경 뒤 기억 암호·저장 전 크롭도 새 이름(마스터 §4.7.14)
    from viewer import secure_store, page_crop
    old_p, new_p = folder / "r_old.pdf", folder / "r_new.pdf"
    shutil.copyfile(str(a), str(old_p))
    secure_store.set_session(old_p, "pw-test")
    page_crop.set_pending(old_p, {0: [1, 2, 3, 4]})
    os.replace(str(old_p), str(new_p))
    mw._on_files_relocated([[str(old_p), str(new_p)]]); spin(0.5)
    chk(secure_store.get_session(new_p) == "pw-test", "D1 이름 변경 뒤 세션 암호가 새 이름에")
    chk(page_crop.pending(new_p) == {0: [1.0, 2.0, 3.0, 4.0]} and not page_crop.has_pending(old_p), "D2 저장 전 크롭이 새 이름에")

    # E — 2단 다른 창이 같은 파일을 보던 쪽을 새 번호로(쪽 편집 제자리 저장)
    mw._closed_panes = {1: (str(a), 2), 0: (str(b), 1)}
    mw._remap_closed_pane_pages(str(a), str(a), [0, 2])          # 새 쪽 0←옛 0, 새 쪽 1←옛 2(옛 1 지움)
    chk(mw._closed_panes[1] == (str(a), 1) and mw._closed_panes[0] == (str(b), 1), "E 다른 창의 쪽 번호가 새 번호로", str(mw._closed_panes))
    mw._closed_panes = {}

    # F — 261025-1(입력 SOT §3.2.1·디자인 SOT §2.9.2, 사용자 결정): 1단·2단 키는 항목마다 하나 — 상태와 무관하게 각자 항목에
    va = mw._view_acts
    mw._refresh_menu_key_hints()
    off = va["single"].text().endswith("\tCtrl+Shift+1") and va["split"].text().endswith("\tCtrl+Shift+2")
    mw.act_split.setChecked(True); spin(0.5); mw._refresh_menu_key_hints()
    on = va["single"].text().endswith("\tCtrl+Shift+1") and va["split"].text().endswith("\tCtrl+Shift+2")
    mw.act_split.setChecked(False); spin(0.5)
    chk(off and on, "F 1단·2단 키는 늘 각자 항목에(Ctrl+Shift+1·2)", "%r / %r" % (va["single"].text(), va["split"].text()))
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
