# -*- coding: utf-8 -*-
"""261105-12: 책갈피창 우클릭 메뉴 맨 위 '인쇄…' (마스터 §4.7.13 '맨 위 인쇄', 사진 보기 SOT 4.20·4.21).

사용자 지시: "책갈피창의 리스트 선택시 옵션창 가장 상단에 '인쇄'를 넣어".
사용자 결정: 책갈피 행 = 그 책갈피 쪽 범위, 폴더 행 = 그 아래 PDF 전부, 사진 줄 = 사진 인쇄.

실제 MainWindow·실제 메뉴 함수(`_on_tree_context_menu`)로 — `QMenu.exec` 를 가로채 항목을 보고 '인쇄' 를 누르며,
인쇄 창(`PrintScopeDialog.exec`)은 가짜로 바꿔 열린 창의 상태(문서·범위 단추·쪽 범위·파일 목록)만 본다.
A. 파일 행 — 맨 위가 '인쇄…' 이고 바로 아래 구분선. 누르면 인쇄 창의 문서가 **그 파일**(본문 파일이 아니어도), '전체' 가 골라짐
B. 책갈피 행 — 그 책갈피 쪽 ~ 다음 책갈피 앞 쪽이 '페이지 범위' 에(하위 책갈피는 위층의 다음까지, 끝 책갈피는 끝 쪽까지)
C. 여러 파일 — '인쇄 (2개 파일)…', 창은 '선택한 책갈피 파일 인쇄' 가 그 두 파일로
D. 폴더 행 — '인쇄 (N개 파일)…' 그 아래 PDF 전부
E. 아래(2창) 책갈피창의 신호도 앱에 이어져 있다
F. 사진 모드 사진 줄 — '인쇄…'/'인쇄 (2장)…' 이 사진 인쇄 길(그 사진들로 만든 임시 PDF)로, 사진 모드 폴더 행에는 없다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tree_print_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "책갈피창 인쇄", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=10.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


seen = {"texts": [], "pick": None}
_orig_exec = QMenu.exec


def fake_exec(self, *a, **k):
    acts = list(self.actions())
    seen["texts"] = ["-" if x.isSeparator() else x.text().split("\t")[0] for x in acts]
    pick, seen["pick"] = seen["pick"], None
    if pick:
        for x in acts:
            if not x.isSeparator() and x.text().startswith(pick):
                x.trigger()                       # 인쇄 항목은 triggered 로 잇는다
                return x
    return None


QMenu.exec = fake_exec

from viewer.widgets import print_dialog as PD
dlgs = []


def fake_dlg_exec(self, *a, **k):
    dlgs.append(dict(pc=self.page_count, sample=self._sample, all=self.rb_all.isChecked(),
                     rng=self.rb_range.isChecked(), files=self.rb_files.isChecked(),
                     frm=self.sp_from.value(), to=self.sp_to.value(), paths=list(self._file_paths)))
    return 0                                       # 취소 — 실제 인쇄는 하지 않는다


PD.PrintScopeDialog.exec = fake_dlg_exec
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)

tmp = Path(tempfile.mkdtemp(prefix="polypdf_tree_print_"))
try:
    import fitz
    from PIL import Image
    root = tmp / "docs"
    (root / "F").mkdir(parents=True)
    a, b, c = root / "a.pdf", root / "b.pdf", root / "F" / "c.pdf"
    for p_, n in ((a, 6), (b, 3), (c, 2)):
        d = fitz.open()
        for i in range(n):
            d.new_page(width=595, height=842).insert_text((72, 400), "%s P%d" % (p_.stem.upper(), i + 1))
        if p_ is a:   # 첫째 p1(하위 p2) · 둘째 p3 · 셋째 p5
            d.set_toc([[1, "첫째", 1], [2, "하위", 2], [1, "둘째", 3], [1, "셋째", 5]])
        d.save(str(p_)); d.close()

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    if not bt.is_tree_view():
        bt.set_tree_view(True)
    mw.open_folder(str(root)); pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 3)
    mw._on_bookmark_activated(str(b), 0); pump(timeout=1.0)        # 본문은 b — 인쇄는 누른 파일(a)이어야

    def fnode(path):
        return next((n for n in bt._iter_file_nodes() if str(n.data(0, bt.DATA_FILE)) == str(path)), None)

    def menu_on(it, pick=None):
        bt.tree.scrollToItem(it)
        seen["pick"] = pick
        n0 = len(dlgs)
        bt._on_tree_context_menu(bt.tree.visualItemRect(it).center())
        if pick:
            pump(lambda: len(dlgs) > n0, timeout=5)
        return list(seen["texts"])

    # A — 파일 행
    an = fnode(a)
    tx = menu_on(an)
    chk(tx[:2] == ["인쇄…", "-"], "A 맨 위가 '인쇄…' 이고 그 아래 구분선", str(tx[:4]))
    menu_on(an, "인쇄")
    g = dlgs[-1] if dlgs else {}
    chk(g.get("sample") == str(a) and g.get("pc") == 6 and g.get("all"),
        "A 누르면 인쇄 창의 문서가 누른 파일(본문 b 가 아니라 a)·'전체'", str(g))

    # B — 책갈피 행(쪽 범위)
    an.setExpanded(True); pump(lambda: an.childCount() >= 3, timeout=5)

    def bm(title, parent=None):
        par = parent or an
        return next((par.child(i) for i in range(par.childCount())
                     if par.child(i).text(0).startswith(title)), None)
    first = bm("첫째")
    if first is not None:
        first.setExpanded(True); pump(timeout=0.3)
    cases = (("둘째", None, (3, 4)), ("셋째", None, (5, 6)), ("첫째", None, (1, 2)), ("하위", first, (2, 2)))
    for title, par, want in cases:
        it = bm(title, par)
        if it is None:
            chk(False, "B 책갈피 '%s' 행이 있다" % title, str([an.child(i).text(0) for i in range(an.childCount())]))
            continue
        tx = menu_on(it)
        chk(tx[:1] == ["인쇄…"], "B 책갈피 행 '%s' 메뉴 맨 위 '인쇄…'" % title, str(tx[:3]))
        menu_on(it, "인쇄")
        g = dlgs[-1] if dlgs else {}
        chk(g.get("sample") == str(a) and g.get("rng") and (g.get("frm"), g.get("to")) == want,
            "B '%s' → 페이지 범위 p.%d~%d" % (title, want[0], want[1]), str(g))

    # C — 여러 파일(편집모드에서 둘 고르기)
    bt.btn_edit.setChecked(True); pump(timeout=0.3)
    an.setExpanded(False)
    bn = fnode(b)
    bt.tree.clearSelection(); an.setSelected(True); bn.setSelected(True)
    tx = menu_on(an)
    chk(tx[:2] == ["인쇄 (2개 파일)…", "-"], "C 여러 파일 — '인쇄 (2개 파일)…' 맨 위", str(tx[:3]))
    an.setSelected(True); bn.setSelected(True)
    menu_on(an, "인쇄")
    g = dlgs[-1] if dlgs else {}
    chk(g.get("files") and sorted(g.get("paths", [])) == sorted([str(a), str(b)]),
        "C 창은 '선택한 책갈피 파일 인쇄' 가 그 두 파일로", str(g))
    bt.tree.clearSelection()
    bt.btn_edit.setChecked(False); pump(timeout=0.3)

    # D — 폴더 행
    fo = next((bt.tree.topLevelItem(i) for i in range(bt.tree.topLevelItemCount())
               if bt._is_folder_node(bt.tree.topLevelItem(i))), None)
    if fo is None:
        chk(False, "D 폴더 행이 있다(트리 보기)")
    else:
        tx = menu_on(fo)
        chk(tx[:2] == ["인쇄…", "-"], "D 폴더 행(PDF 1개) 맨 위 '인쇄…'", str(tx[:3]))
        menu_on(fo, "인쇄")
        g = dlgs[-1] if dlgs else {}
        chk(g.get("sample") == str(c) and g.get("all"), "D 폴더 행 → 그 아래 PDF", str(g))

    # E — 아래(2창) 책갈피창도 이어져 있다
    n0 = len(dlgs)
    mw.bookmark_tree_right.printFilesRequested.emit([str(b)], None)
    pump(lambda: len(dlgs) > n0, timeout=5)
    chk(len(dlgs) > n0 and dlgs[-1].get("sample") == str(b), "E 아래 책갈피창 신호 → 같은 인쇄 창(그 파일)",
        str(dlgs[-1] if dlgs else None))

    # F — 사진 모드
    pix = tmp / "pix"; pix.mkdir()
    Image.new("RGB", (800, 400), (200, 60, 60)).save(pix / "p1.jpg", "JPEG")
    Image.new("RGB", (600, 300), (60, 160, 60)).save(pix / "p2.jpg", "JPEG")
    (pix / "sub").mkdir()
    Image.new("RGB", (300, 300), (60, 60, 200)).save(pix / "sub" / "p3.jpg", "JPEG")
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"     # test_photo_menus_261104 와 같은 차림
    mw._photo_apply_view_kind()
    mw.open_folder(pix); pump(timeout=1.0)
    mw._set_photo_mode(True)
    pump(lambda: fnode(pix / "p1.jpg") is not None and fnode(pix / "p2.jpg") is not None)
    p1n, p2n = fnode(pix / "p1.jpg"), fnode(pix / "p2.jpg")
    if p1n is None or p2n is None:
        chk(False, "F 사진 줄이 있다")
    else:
        tx = menu_on(p1n)
        chk(tx[:2] == ["인쇄…", "-"], "F 사진 줄 맨 위 '인쇄…'", str(tx[:3]))
        menu_on(p1n, "인쇄")
        g = dlgs[-1] if dlgs else {}
        chk(g.get("pc") == 1 and str(g.get("sample", "")).lower().endswith(".pdf") and g.get("sample") != str(pix / "p1.jpg"),
            "F 사진 한 장 → 사진 인쇄 길(그 사진의 임시 PDF 1쪽)", str(g))
        bt.btn_edit.setChecked(True); pump(timeout=0.3)
        bt.tree.clearSelection(); p1n.setSelected(True); p2n.setSelected(True)
        tx = menu_on(p1n)
        chk(tx[:1] == ["인쇄 (2장)…"], "F 사진 두 장 — '인쇄 (2장)…'", str(tx[:3]))
        p1n.setSelected(True); p2n.setSelected(True)
        menu_on(p1n, "인쇄")
        g = dlgs[-1] if dlgs else {}
        chk(g.get("pc") == 2, "F 두 장 → 임시 PDF 2쪽", str(g))
        bt.tree.clearSelection()
        bt.btn_edit.setChecked(False); pump(timeout=0.3)
        pf = next((bt.tree.topLevelItem(i) for i in range(bt.tree.topLevelItemCount())
                   if bt._is_folder_node(bt.tree.topLevelItem(i))), None)
        chk(pf is not None, "F 사진 모드 폴더 행(sub)이 있다(트리 보기)")
        if pf is not None:
            tx = menu_on(pf)
            chk(not any(t.startswith("인쇄") for t in tx), "F 사진 모드 폴더 행에는 '인쇄' 가 없다", str(tx[:3]))
    mw._set_photo_mode(False); pump(timeout=0.3)
finally:
    QMenu.exec = _orig_exec
    try:
        mw.close()
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)

print("\n%d FAIL" % len(fails) if fails else "\nALL PASS")
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
