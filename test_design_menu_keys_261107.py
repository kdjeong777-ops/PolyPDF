# -*- coding: utf-8 -*-
"""261107-20 → 261107-26(디자인 SOT §2.9.2 '포커스 기준 키', 입력 SOT §3.2.3 '창 키도 포커스 따라'): 키가 같은 일을 하는 우클릭 줄에 키 칸.

A. 본문 우클릭(편집 모드) — 인쇄·새 페이지 넣기·크롭 (p.K)·책갈피 추가·하이퍼링크 등록·발표보기·저장 ▸ 다른 이름으로 저장 에 키,
   OCR 로 읽기 에는 없다(메뉴는 지금 쪽을 미리 고른다 — 키는 범위를 고르는 창). '문서 정보' 줄은 없다(261107-26, 정보 한 줄·Alt+Enter)
B. 썸네일 우클릭(편집 모드) — 인쇄·새 페이지 넣기·회전·크롭·OCR 로 읽기·책갈피 추가·하이퍼링크 등록 에 키, '문서 정보' 없음
C. 책갈피창 우클릭 — 파일 줄: 인쇄·파일 탐색기 열기·새 폴더 만들기·이름 변경·삭제·2단 보기·발표보기·OCR 로 읽기·즐겨찾기(파일)·
   저장 ▸ 다른 이름으로 저장 에 키, '문서 정보' 없음 · 책갈피 줄: 인쇄·책갈피 수정(F2)·OCR 로 읽기 에 키 · 파일 ▸(본문): 탐색기·즐겨찾기 에 키
D. F12 의 대상 = 메뉴와 같다 — 책갈피창 포커스면 그 창의 지금 줄 PDF, 본문 포커스면 지금 본문 PDF
E. 키의 대상 = 그 창 우클릭 줄 — 책갈피창 포커스: Ctrl+P(그 줄 파일·책갈피 쪽 범위), F5·Ctrl+Alt+O(그 줄 파일·범위), Ctrl+D(그 줄 파일),
   쪽 썸네일 포커스: Ctrl+B·Ctrl+K·Ctrl+Enter·Ctrl+]·Ctrl+Alt+O(고른 썸네일)
F. 사진 메뉴(썸네일 줄) — 인쇄·회전·크롭·탐색기·이름 변경·발표보기·OCR·사진 정보·즐겨찾기 에 키, 본문 사진 OCR 에는 없다 ·
   사진 줄 포커스 키(Ctrl+P·F5·Alt+Enter·Ctrl+Alt+O·Ctrl+[)가 고른 사진에
종전 코드로 실패한다(책갈피창 인쇄·발표보기 등에 키 칸이 없고, 키는 지금 본문에 일했다).
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
        out.setdefault(base, key)          # 같은 이름이면 먼저 나온 줄(바깥) — '폴더로 복사 ▸' 안에도 '새 폴더 만들기' 가 있다
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


def keys_on(R, where, pairs):
    for name, sid in pairs:
        k = has(R, name)
        chk(bool(k) and k == mw._sc_key(sid), "%s '%s' 에 키 %s" % (where, name, mw._sc_key(sid)), repr(k))


def no_line(R, where, name):
    chk(has(R, name) is None, "%s 에 '%s' 줄이 없다(261107-26 — 정보 한 줄·Alt+Enter)" % (where, name), repr(has(R, name)))


def recorder(sig):
    """앱 처리기를 떼고 받은 값을 적는다 — 키가 그 신호를 냈는지만 본다(창을 띄우지 않게)."""
    got = []
    try:
        sig.disconnect()
    except TypeError:
        pass
    sig.connect(lambda *a: got.append(a))
    return got


root = Path(tempfile.mkdtemp(prefix="menukeys261107_"))
_orig_exec = QMenu.exec
try:
    folder = root / "f"; folder.mkdir()
    a = folder / "a.pdf"
    b = folder / "b.pdf"
    for p in (a, b):
        d = fitz.open()
        for i in range(4):
            d.new_page(width=595, height=842).insert_text((72, 400), "A P%d" % (i + 1))
        d.set_toc([[1, "one", 1], [1, "two", 3]])
        d.save(str(p)); d.close()
    png = folder / "c.png"
    pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), False); pm.clear_with(200); pm.save(str(png)); pm = None
    from viewer.app import MainWindow
    from viewer import key_actions as ka
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
    keys_on(R, "A 본문", (("인쇄", "print"), ("새 페이지 넣기", "new_page"), ("크롭 (p.", "crop"), ("책갈피 추가 (p.", "add_bookmark"),
                         ("하이퍼링크 등록 (p.", "hyperlink"), ("발표보기", "present"), ("다른 이름으로 저장", "save_as")))
    chk(has(R, "OCR 로 읽기") == "", "A 본문 'OCR 로 읽기' 에는 키가 없다(하는 일이 다르다)", repr(has(R, "OCR 로 읽기")))
    no_line(R, "A 본문", "문서 정보")
    keys_on(R, "A 본문 파일 ▸", (("파일 탐색기 열기", "reveal"), ("현재 파일을 즐겨찾기에 추가", "fav_add_file")))

    # B — 썸네일
    pt.list.clearSelection(); pt.list.item(1).setSelected(True); pt.list.setCurrentRow(1)
    pt._on_list_menu(pt.list.visualItemRect(pt.list.item(1)).center()); spin(0.2)
    R = seen[-1] if seen else {}
    keys_on(R, "B 썸네일", (("인쇄 (", "print"), ("크롭 (", "crop"), ("새 페이지 넣기", "new_page"), ("왼쪽 90° 회전", "rotate_left"),
                           ("오른쪽 90° 회전", "rotate_right"), ("OCR 로 읽기", "ocr_read"), ("책갈피 추가", "add_bookmark"),
                           ("하이퍼링크 등록", "hyperlink")))
    no_line(R, "B 썸네일", "문서 정보")

    # C — 책갈피창
    anode = bt._file_node_for_path(str(a))
    bnode = bt._file_node_for_path(str(b))
    bt.tree.setCurrentItem(bnode)
    bt._on_tree_context_menu(bt.tree.visualItemRect(bnode).center()); spin(0.2)
    R = seen[-1] if seen else {}
    pairs = [("인쇄", "print"), ("파일 탐색기 열기", "reveal"), ("파일·책갈피 이름 변경", "rename_item"), ("파일·책갈피 삭제", "Del"),
             ("2단 보기", "toggle_split"), ("발표보기", "present"), ("OCR 로 읽기", "ocr_read"),
             ("현재 파일을 즐겨찾기에 추가", "fav_add_file"), ("다른 이름으로 저장", "save_as")]
    if has(R, "새 폴더 만들기") is not None:
        pairs.append(("새 폴더 만들기", "new_folder"))
    chk(has(R, "새 폴더 만들기") is not None, "C 책갈피창(폴더 목록) 파일 줄에 '새 폴더 만들기'", str(sorted(R)))
    keys_on(R, "C 책갈피창 파일 줄", [(n, s) for n, s in pairs if s != "Del"])
    chk(has(R, "파일·책갈피 삭제") == "Del", "C 책갈피창 '파일·책갈피 삭제' 에 Del", repr(has(R, "파일·책갈피 삭제")))
    no_line(R, "C 책갈피창", "문서 정보")
    bnode.setExpanded(True); spin(0.5)
    bm = next((bnode.child(i) for i in range(bnode.childCount()) if bnode.child(i).text(0).strip() == "two"), None)
    chk(bm is not None, "C 책갈피 줄 'two' 가 보인다", str([bnode.child(i).text(0) for i in range(bnode.childCount())]))
    if bm is not None:
        bt.tree.clearSelection(); bt.tree.setCurrentItem(bm); bm.setSelected(True)
        bt._on_tree_context_menu(bt.tree.visualItemRect(bm).center()); spin(0.2)
        R = seen[-1] if seen else {}
        keys_on(R, "C 책갈피 줄", (("인쇄", "print"), ("책갈피 수정", "rename_item"), ("OCR 로 읽기", "ocr_read")))
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

    # E — 키의 대상 = 그 창 우클릭 줄(본문은 a.pdf, 책갈피창은 b.pdf 줄)
    got_print = recorder(bt.printFilesRequested)
    got_act = recorder(bt.fileActionRequested)
    got_fav = recorder(bt.addFileFavoriteRequested)
    CTRL, ALT = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier
    bt.tree.setFocus(); bt.tree.clearSelection(); bt.tree.setCurrentItem(bnode); bnode.setSelected(True); spin(0.1)
    QTest.keyClick(bt.tree, Qt.Key.Key_P, CTRL); spin(0.2)
    chk(got_print and list(got_print[-1][0]) == [str(b)] and got_print[-1][1] is None,
        "E1 책갈피창 Ctrl+P → 그 줄 파일 인쇄(우클릭 '인쇄' 와 같은 신호)", str(got_print))
    QTest.keyClick(bt.tree, Qt.Key.Key_F5); spin(0.2)
    chk(any(x[0] == "present" and list(x[1]) == [str(b)] for x in got_act), "E2 책갈피창 F5 → 그 줄 파일 발표", str(got_act))
    QTest.keyClick(bt.tree, Qt.Key.Key_O, CTRL | ALT); spin(0.2)
    chk(any(x[0] == "ocr_read" and list(x[1]) == [str(b)] and x[2] is None for x in got_act),
        "E3 책갈피창 Ctrl+Alt+O → 그 줄 파일 전체 OCR", str(got_act))
    QTest.keyClick(bt.tree, Qt.Key.Key_D, CTRL); spin(0.2)
    chk(got_fav and got_fav[-1][0] == str(b), "E4 책갈피창 Ctrl+D → 그 줄 파일 즐겨찾기", str(got_fav))
    if bm is not None:
        bt.tree.clearSelection(); bt.tree.setCurrentItem(bm); bm.setSelected(True); spin(0.1)
        QTest.keyClick(bt.tree, Qt.Key.Key_P, CTRL); spin(0.2)
        chk(got_print and list(got_print[-1][0]) == [str(b)] and got_print[-1][1] == bt._bookmark_page_range(bm),
            "E5 책갈피 줄 Ctrl+P → 그 책갈피 쪽 범위", str(got_print[-1:]))
        n0 = len(got_act)
        QTest.keyClick(bt.tree, Qt.Key.Key_O, CTRL | ALT); spin(0.2)
        chk(len(got_act) > n0 and got_act[-1][0] == "ocr_read" and got_act[-1][2] == bt._bookmark_page_range(bm),
            "E6 책갈피 줄 Ctrl+Alt+O → 그 책갈피 쪽 범위", str(got_act[-1:]))
    got_bm = recorder(pt.addBookmarkAtPage)
    got_hl = recorder(pt.registerHyperlinkAtPage)
    got_blank = recorder(pt.addBlankPageRequested)
    got_rot = recorder(pt.rotatePages)
    got_ocr = recorder(pt.ocrPagesRequested)
    pt.list.setFocus(); pt.list.clearSelection(); pt.list.setCurrentRow(2); pt.list.item(2).setSelected(True); spin(0.1)
    for key, mod in ((Qt.Key.Key_B, CTRL), (Qt.Key.Key_K, CTRL), (Qt.Key.Key_Return, CTRL),
                     (Qt.Key.Key_BracketRight, CTRL), (Qt.Key.Key_O, CTRL | ALT)):
        QTest.keyClick(pt.list, key, mod); spin(0.2)
    chk(got_bm == [(2,)], "E7 썸네일 Ctrl+B → 고른 썸네일 쪽(p.3)", str(got_bm))
    chk(got_hl == [(2,)], "E8 썸네일 Ctrl+K → 고른 썸네일 쪽", str(got_hl))
    chk(got_blank == [(2,)], "E9 썸네일 Ctrl+Enter → 고른 썸네일 뒤", str(got_blank))
    chk(got_rot and list(got_rot[-1][0]) == [2] and got_rot[-1][1] == 90, "E10 썸네일 Ctrl+] → 고른 쪽 회전", str(got_rot))
    chk(got_ocr and list(got_ocr[-1][0]) == [2], "E11 썸네일 Ctrl+Alt+O → 고른 쪽 OCR", str(got_ocr))

    # F — 사진 메뉴(썸네일 줄·본문) — 줄 글자만 본다
    from viewer.widgets.ctx_menu import CtxMenu
    m = CtxMenu(mw)
    mw._photo_menu_fill(m, [str(png)], "strip", {})
    R = _all(m, {})
    keys_on(R, "F 사진 썸네일 줄", (("인쇄", "print"), ("왼쪽 90° 회전", "rotate_left"), ("오른쪽 90° 회전", "rotate_right"),
                                ("크롭", "crop"), ("파일 탐색기 열기", "reveal"), ("이름 변경", "rename_item"),
                                ("발표보기", "present"), ("OCR 로 읽기", "ocr_read"), ("사진 정보", "info"),
                                ("현재 파일을 즐겨찾기에 추가", "fav_add_file")))
    m = CtxMenu(mw)
    mw._photo_menu_fill(m, [str(png)], "body", {})
    R = _all(m, {})
    chk(has(R, "OCR 로 읽기") == "", "F 본문 사진 'OCR 로 읽기' 에는 키가 없다", repr(has(R, "OCR 로 읽기")))
    # 사진 줄 포커스 키 → 고른 사진(포커스 판정만 바꿔 끼운다 — 키 함수는 실제 것)
    got = []
    mw._photo_mode = True
    _fk = ka.focus_kind

    class _Strip:
        def selected_paths(self):
            return [str(png)]
    ka.focus_kind = lambda _mw: ("strip", _Strip())
    mw._photo_print = lambda *a_, **k: got.append(("print", k.get("paths")))
    mw._photo_open_then = lambda p_, fn: got.append(("open_then", p_, getattr(fn, "__name__", "")))
    mw._photo_info_for = lambda p_: got.append(("info", p_))
    mw._photo_rotate = lambda d_, path=None: got.append(("rot", d_, path))
    ka.print_(mw); ka.present(mw); ka.info(mw); ka.ocr_read(mw); ka.rotate(mw, -90)
    ka.focus_kind = _fk
    mw._photo_mode = False
    want = [("print", [str(png)]), ("open_then", str(png), "_open_presentation"), ("info", str(png)),
            ("open_then", str(png), "_photo_ocr_start"), ("rot", -90, str(png))]
    chk(got == want, "F 사진 줄 포커스 Ctrl+P·F5·Alt+Enter·Ctrl+Alt+O·Ctrl+[ → 고른 사진", str(got))
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
