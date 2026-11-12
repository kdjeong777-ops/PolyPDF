# -*- coding: utf-8 -*-
"""261112-9: 엑셀로 만든 PDF → 병합 → 그 병합본을 다시 병합 → 꾸밈 → [저장] 뒤 꾸밈이 남는가 (사용자 보고, 재현 조사).

엑셀 비슷한 PDF(Producer 'Microsoft Excel', 쪽 내용이 form XObject, /MarkInfo·/StructTreeRoot 태그 구조)를 만들어
앱의 병합 핵심(`MainWindow._do_normal_merge`)으로 두 번 합친 뒤, 실제 창에서 꾸밈을 넣고 책갈피창 [저장](`_op_save`)을 누른다.
R1. 보통 저장 — 저장 뒤 본문에 꾸밈이 보이고, 옆 파일(page_meta)에 있고, PDF 에 다른 뷰어용 사본(PolyPDF 레이어)이 들어간다
R2. 원본이 다른 프로그램에 잠겨 있을 때(실제 Windows 잠금 — 공유 없이 연 핸들) — 저장은 새 이름으로 빠지고 그 파일이 열린다.
    **그 새 파일에서도 꾸밈이 보여야 한다**(종전: 옆 파일이 옛 이름에 남고 새 파일의 PDF 사본 레이어는 PolyPDF 가 꺼서 '저장했는데 사라짐')
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
import modal_guard
guard = modal_guard.install(label=lambda: "검사")   # 검사 작성 SOT §14.7.2 의 6
QCoreApplication.setApplicationName("polypdf_mergedsave_%d" % os.getpid())
from PyQt6.QtWidgets import QFileDialog as _QFD
_QFD.getSaveFileName = staticmethod(lambda *a, **k: (a[2] if len(a) > 2 else "", "PDF (*.pdf)"))

fails = []
WARN = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def excel_like(dst: Path, label: str, pages=2):
    """엑셀 '다른 이름으로 저장 → PDF' 꼴 — 쪽 내용을 form XObject 로(show_pdf_page), 태그 구조·Producer."""
    src = fitz.open()
    for i in range(pages):
        pg = src.new_page(width=842, height=595)
        pg.draw_rect(fitz.Rect(40, 40, 800, 120), color=(0, 0, 0), width=0.5)
        pg.insert_text((50, 80), "%s SHEET%d A1 B1 C1" % (label, i + 1), fontsize=12)
    d = fitz.open()
    for i in range(pages):
        pg = d.new_page(width=842, height=595)
        pg.show_pdf_page(pg.rect, src, i)
    src.close()
    d.set_metadata({"producer": "Microsoft® Excel® for Microsoft 365", "creator": "Microsoft® Excel® for Microsoft 365"})
    cat = d.pdf_catalog()
    st = d.get_new_xref()
    d.update_object(st, "<< /Type /StructTreeRoot /K [] >>")
    d.xref_set_key(cat, "StructTreeRoot", "%d 0 R" % st)
    d.xref_set_key(cat, "MarkInfo", "<< /Marked true >>")
    d.xref_set_key(cat, "Lang", "(ko-KR)")
    d.save(str(dst)); d.close()


DECO = {"text_box": True, "rect": [0.1, 0.1, 0.4, 0.16], "text": "MERGED-DECO", "size_pt": 12}


def lock_exclusive(path):
    """PDF 보기 프로그램(Acrobat 등)이 연 것처럼 — 읽기 공유만 허용: PolyPDF 는 읽지만 덮어쓰기·제자리 쓰기·지우기는 막힌다."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.CreateFileW(str(path), 0x80000000, 0x1, None, 3, 0x80, None)   # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING
    return k, h


root = Path(tempfile.mkdtemp(prefix="mergedsave_"))
try:
    folder = root / "f"; folder.mkdir()
    xa, xb, xc = folder / "엑셀A.pdf", folder / "엑셀B.pdf", folder / "엑셀C.pdf"
    excel_like(xa, "A"); excel_like(xb, "B"); excel_like(xc, "C", 1)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    QMessageBox.warning = staticmethod(lambda *a_, **k: WARN.append(a_[2] if len(a_) > 2 else ""))
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    prog = lambda *a_: True
    m1, m2 = folder / "병합1.pdf", folder / "병합2.pdf"
    mw._do_normal_merge([{"path": str(xa), "name": "A"}, {"path": str(xb), "name": "B"}], str(m1), True, prog)
    mw._do_normal_merge([{"path": str(m1), "name": "M1"}, {"path": str(xc), "name": "C"}], str(m2), True, prog)
    m3 = folder / "병합3.pdf"                                       # R2 용 — 책갈피창에 보이게 폴더를 열기 전에 만든다
    mw._do_normal_merge([{"path": str(m2), "name": "M2"}, {"path": str(xc), "name": "C"}], str(m3), True, prog)
    chk(fitz.open(str(m2)).page_count == 5, "준비 — 엑셀 비슷한 PDF 를 두 번 병합(5쪽)")
    mw.open_folder(str(folder)); spin(0.8)
    bt = mw.bookmark_tree
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)

    def decorate_and_save(path):
        mw._on_bookmark_activated(str(path), 0); spin(1.0)
        mv = mw.main_view
        mv.go_to_page(0); spin(0.3)
        mv._page_strokes = [dict(DECO)]
        mv._save_page_strokes(); mw._edit_dirty = True
        bt._op_save(); spin(4.0)
        return mv

    def shown(mv):
        return [s.get("text") for s in mv._page_strokes]

    # R1 — 보통 저장
    mv = decorate_and_save(m2)
    cur = mv.current_file()
    chk(cur and Path(cur).name == m2.name, "R1a 저장 뒤 본문은 같은 파일", str(cur))
    mv.go_to_page(1); spin(0.2); mv.go_to_page(0); spin(0.3)
    chk(shown(mv) == ["MERGED-DECO"], "R1b 저장 뒤에도 본문에 꾸밈이 보인다", str(shown(mv)))
    st = mw._ensure_page_meta_store()
    chk([s.get("text") for s in st.get_drawings(str(m2), 0)] == ["MERGED-DECO"], "R1c 옆 파일(page_meta)에 꾸밈이 있다")
    d = fitz.open(str(m2))
    names = [v.get("name") for v in (d.get_ocgs() or {}).values()]
    chk("PolyPDF" in names, "R1d PDF 에 다른 뷰어용 사본(PolyPDF 레이어)이 들어갔다", str(names))
    d.close()

    # R2 — 원본이 다른 프로그램에 잠겨 있으면 새 이름으로 빠진다 → 그 파일에서도 꾸밈이 보여야 한다
    mw._on_bookmark_activated(str(m3), 0); spin(1.0)
    mv = mw.main_view
    mv.go_to_page(0); spin(0.3)
    mv._page_strokes = [dict(DECO)]
    mv._save_page_strokes(); mw._edit_dirty = True
    k, h = lock_exclusive(m3)
    ok_lock = h not in (None, 0, -1, 0xFFFFFFFF, 2 ** 64 - 1)
    chk(ok_lock, "R2a 원본을 다른 프로그램처럼 잠갔다", "err %d" % __import__("ctypes").get_last_error())
    try:
        bt._op_save(); spin(4.0)
    finally:
        if ok_lock:
            k.CloseHandle(h)
    spin(0.5)
    cur = mv.current_file()
    chk(cur and Path(cur).name != m3.name, "R2b 잠긴 원본은 새 이름으로 저장되고 그 파일이 열린다", str(cur))
    if cur:
        mv.go_to_page(1); spin(0.2); mv.go_to_page(0); spin(0.3)
        chk(shown(mv) == ["MERGED-DECO"], "R2c 새 이름으로 빠진 파일에서도 꾸밈이 보인다(저장했는데 사라지지 않는다)", str(shown(mv)))
        st = mw._ensure_page_meta_store()
        chk([s.get("text") for s in st.get_drawings(str(cur), 0)] == ["MERGED-DECO"], "R2d 옆 파일 꾸밈도 새 이름 키에 있다")
    mw._confirm_close_edit = lambda: True
    mw.close(); spin(0.2)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("경고 창:", [w[:60] for w in WARN])
print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
