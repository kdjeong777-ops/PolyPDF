# -*- coding: utf-8 -*-
"""261112-12: 원본을 덮어쓰는 저장이 잠긴 원본 대신 새 이름(_edited)으로 빠지면 꾸밈 옆 파일도 새 이름에 — `_finalize_save` 한 곳
(책갈피창·저장 SOT §4.7.5 의 3).

길마다 실제 처리기를 부른다. 원본은 PDF 보기 프로그램처럼 **읽기 공유만 허용한 Windows 핸들**로 잠가 덮어쓰기·제자리 쓰기가 막히게 한다.
T. 텍스트 창 'PDF 에 반영' — 워커가 만든 임시 파일을 받는 `_on_text_layer_done`
S. 빈 서명 칸 만들기 — `_sigfield_place`
O. OCR 묶음 — 끝난 파일을 놓는 `_ocr_batch_place`
M. 꾸밈만 바꾼 [저장]의 다른 뷰어용 사본 — `_mirror_to_pdf`(261112-9 가 고친 길, 한 곳으로 모은 뒤에도 그대로)
B. 책갈피창 [저장](책갈피를 고친 저장) — `_op_save`(종전 `_carry_meta` 를 없애고 한 곳으로)
각 길: 새 이름 파일이 생기고, 그 키에 꾸밈이 있다. 원본 키의 꾸밈도 남는다(원본 파일은 그대로라서).
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
QCoreApplication.setApplicationName("polypdf_newnamecarry_%d" % os.getpid())

fails = []
DECO = {"text_box": True, "rect": [0.1, 0.1, 0.4, 0.16], "text": "CARRY", "size_pt": 12}


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def make_pdf(p: Path, label: str):
    d = fitz.open()
    for i in range(2):
        d.new_page(width=595, height=842).insert_text((72, 100), "%s P%d" % (label, i + 1))
    d.set_toc([[1, label + " one", 1], [1, label + " two", 2]])
    d.save(str(p)); d.close()


class Lock:
    """읽기 공유만 허용한 핸들 — PolyPDF 는 읽지만 덮어쓰기·제자리 쓰기·지우기는 막힌다."""
    def __init__(self, path):
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k, self.h = k, k.CreateFileW(str(path), 0x80000000, 0x1, None, 3, 0x80, None)
        self.ok = self.h not in (None, 0, -1, 0xFFFFFFFF, 2 ** 64 - 1)

    def close(self):
        if self.ok:
            self.k.CloseHandle(self.h); self.ok = False


root = Path(tempfile.mkdtemp(prefix="newnamecarry_"))
try:
    folder = root / "f"; folder.mkdir()
    names = {"T": "텍스트반영", "S": "서명칸", "O": "OCR묶음", "M": "사본", "B": "책갈피"}
    files = {k: folder / (v + ".pdf") for k, v in names.items()}
    for k, p in files.items():
        make_pdf(p, k)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    mw.open_folder(str(folder)); spin(0.8)
    bt = mw.bookmark_tree
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)
    st = mw._ensure_page_meta_store()

    def prepare(key):
        p = files[key]
        mw._on_bookmark_activated(str(p), 0); spin(1.0)
        mv = mw.main_view
        mv.go_to_page(0); spin(0.2)
        mv._page_strokes = [dict(DECO)]
        mv._save_page_strokes(); st.save(); spin(0.1)
        from viewer import ocr_batch
        tmp = Path(tempfile.mkdtemp(prefix=ocr_batch.TEMP_PREFIX)) / p.name   # 앱처럼 전용 임시 폴더(OCR 묶음은 그 폴더째 지운다)
        shutil.copyfile(str(p), str(tmp))
        return p, str(tmp)

    def result(key, p):
        news = sorted(x for x in folder.glob(p.stem + "_edited*.pdf"))
        chk(len(news) == 1, "%s1 잠긴 원본 대신 새 이름으로 저장됐다" % key, str([x.name for x in folder.iterdir()]))
        if news:
            got = [s.get("text") for s in st.get_drawings(str(news[0]), 0)]
            chk(got == ["CARRY"], "%s2 새 이름 키에 꾸밈이 따라갔다(새 파일을 열어도 꾸밈이 보인다)" % key, str(got))
        chk([s.get("text") for s in st.get_drawings(str(p), 0)] == ["CARRY"], "%s3 원본 키의 꾸밈도 남는다" % key)

    def locked(p, fn):
        lk = Lock(p)
        chk(lk.ok, "준비 — %s 를 다른 프로그램처럼 잠갔다" % p.name)
        try:
            fn()
            spin(1.0)
        finally:
            lk.close()
        spin(0.3)

    # T — 텍스트 창 'PDF 에 반영'
    p, tmp = prepare("T")
    mw._text_layer_token = 4242
    locked(p, lambda: mw._on_text_layer_done(str(p), 0, tmp, {"rewritten": [0]}, 4242))
    result("T", p)
    # S — 빈 서명 칸
    p, tmp = prepare("S")
    locked(p, lambda: mw._sigfield_place(str(p), tmp))
    result("S", p)
    # O — OCR 묶음
    p, tmp = prepare("O")
    locked(p, lambda: mw._ocr_batch_place([(str(p), {"status": "ok", "tmp": tmp, "stats": {}, "ocr": 0})], False, 1))
    result("O", p)
    # M — 다른 뷰어용 사본
    p, _ = prepare("M")
    mw._edit_dirty = True
    locked(p, lambda: (bt._op_save(), spin(3.0)))
    result("M", p)
    # B — 책갈피를 고친 [저장]
    p, _ = prepare("B")
    bt._dirty = True                                      # 책갈피를 고친 저장(책갈피 쓰기 → _finalize_save)
    locked(p, lambda: (bt._op_save(), spin(3.0)))
    result("B", p)
    print("모달:", [(s[1], s[2][:50]) for s in guard.seen])
    mw._confirm_close_edit = lambda: True
    mw.close(); spin(0.2)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
