# -*- coding: utf-8 -*-
"""261107-7: 고른 쪽으로 새 PDF 만들기 (형식 변환 SOT §2.4, 사용자 결정 A '보이는 그대로 다').

실제 처리기(`MainWindow.action_pages_to_pdf(path, pages)`)로:
A. 고른 쪽만, 받은 차례(썸네일 차례)대로 — 중복은 한 번
B. 원본은 그대로(쪽 수·바이트)
C. 보이는 그대로 — 저장 전 회전은 `/Rotate` 에 더하고, 꾸밈은 보이는 자리에 구워진다(고른 쪽의 것만)
D. 저장 창 기본 이름 `<원본>_<첫쪽>-<끝쪽>쪽.pdf` · 한 쪽이면 `<원본>_<n>쪽.pdf`, 원본과 같은 이름은 받지 않는다
E. 붙여넣은 쪽(정수 아닌 쪽)·암호 PDF 는 만들지 않고 알린다
F. 쪽 고르기·저장은 배경 스레드, 끝나면 그 파일을 연다
G. 저장 창 제목은 메뉴와 같은 'PDF 저장'(261111-24 사용자 결정 '둘 다 PDF 저장으로', 옛 'PDF 만들기')
수정 전 코드(함수 없음)로 실패 확인.
"""
import os, sys, tempfile, shutil, time, hashlib, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_pages2pdf_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "PDF 만들기", watch_ms=0, echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def red_box(pix):
    xs, ys = [], []
    for y in range(0, pix.height, 2):
        for x in range(0, pix.width, 2):
            r, g, b = pix.pixel(x, y)[:3]
            if r > 200 and g < 90 and b < 90:
                xs.append(x); ys.append(y)
    if not xs:
        return None
    return (min(xs) / pix.width, min(ys) / pix.height, max(xs) / pix.width, max(ys) / pix.height)


def near(box, want, tol=0.03):
    return box is not None and all(abs(a - b) < tol for a, b in zip(box, want))


RED = {"shape": "rect", "rect": [0.05, 0.05, 0.30, 0.12], "color": "#ff0000", "fill": "full", "width": 2, "alpha": 100}
root = Path(tempfile.mkdtemp(prefix="polypdf_pages2pdf_"))
try:
    src = root / "지침.pdf"
    d = fitz.open()
    for i in range(8):
        p = d.new_page(width=595, height=842)
        for k in range(8):
            p.insert_text((72, 200 + 18 * k), f"PAGE{i + 1:02d} line {k} with words enough for a text layer", fontsize=11)
    d.save(str(src)); d.close()
    digest = hashlib.sha256(src.read_bytes()).hexdigest()

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 820); mw.show(); spin(0.3)
    mw.open_folder(str(root)); spin(0.5)
    mw.open_pdfs([str(src)]); spin(1.0)
    mw._rotate_pages([2], +90); spin(0.8)                     # 3쪽 저장 전 회전
    ms = mw._ensure_page_meta_store()
    ms.set_drawings(str(src), 4, [dict(RED)])                 # 5쪽 꾸밈(고른 쪽)
    ms.set_drawings(str(src), 0, [dict(RED, rect=[0.6, 0.6, 0.9, 0.7])])   # 1쪽 꾸밈(고르지 않은 쪽)
    ms.save()

    asked = {}
    out = root / "지침_고른쪽.pdf"

    def save_dlg(*a, **k):
        asked["default"] = a[2] if len(a) > 2 else k.get("directory", "")
        asked["caption"] = a[1] if len(a) > 1 else k.get("caption", "")
        return (asked.get("answer", str(out)), "PDF (*.pdf)")
    QFileDialog.getSaveFileName = staticmethod(save_dlg)
    seen_threads = []
    import viewer.pdf_font as _pf
    _real_subset = _pf.subset_fonts_safely
    _pf.subset_fonts_safely = lambda doc: (seen_threads.append(threading.current_thread() is threading.main_thread()),
                                           _real_subset(doc))[1]

    # 새 파일을 열면 원본의 저장 전 편집(회전)을 어떻게 할지 묻는다 — 사용자가 고를 일, 여기서는 '되돌리기(저장 안 함)'
    QMessageBox.exec = lambda self: (setattr(self, "_pick", next(
        (b for b in self.buttons() if "되돌리기" in b.text()), None)), 0)[1]
    QMessageBox.clickedButton = lambda self: getattr(self, "_pick", None)
    got = mw.action_pages_to_pdf(str(src), [4, 2, 6, 2]); spin(1.0)
    chk(got and Path(got) == out and out.exists(), "준비 — 새 PDF 를 만들었다", str(got))
    if out.exists():
        with fitz.open(str(out)) as o:
            marks = [next((w for w in o[i].get_text().split() if w.startswith("PAGE")), "") for i in range(o.page_count)]
            chk(o.page_count == 3 and marks == ["PAGE05", "PAGE03", "PAGE07"],
                "A 고른 쪽만, 받은 차례대로(중복은 한 번)", f"{o.page_count} {marks}")
            chk(o[1].rotation == 90, "C 저장 전 회전은 /Rotate 에 더한다(보이는 그대로)", str(o[1].rotation))
            chk(near(red_box(o[0].get_pixmap(dpi=40)), (0.05, 0.05, 0.30, 0.12)),
                "C 고른 쪽의 꾸밈이 보이는 자리에 구워졌다", str(red_box(o[0].get_pixmap(dpi=40))))
            chk(all(red_box(o[i].get_pixmap(dpi=40)) is None for i in (1, 2)),
                "C 고르지 않은 쪽(1쪽)의 꾸밈은 들어오지 않는다")
            chk(bool(o[0].search_for("PAGE05")), "C 글자층은 그대로(검색·복사)")
    with fitz.open(str(src)) as s:
        chk(s.page_count == 8 and hashlib.sha256(src.read_bytes()).hexdigest() == digest, "B 원본은 그대로")
    chk(asked.get("caption") == "PDF 저장", "G 저장 창 제목 'PDF 저장'(261111-24)", repr(asked.get("caption")))
    chk(Path(asked.get("default", "")).name == "지침_3-7쪽.pdf", "D 기본 이름 <원본>_<첫쪽>-<끝쪽>쪽.pdf", asked.get("default"))
    chk(seen_threads and not any(seen_threads), "F 쪽 고르기·저장은 배경 스레드에서", str(seen_threads))
    cur = mw.main_view.current_file() if mw.main_view else None
    chk(cur and Path(str(cur)) == out, "F 끝나면 그 파일을 연다", str(cur))

    # D 한 쪽 이름 · 원본과 같은 이름은 받지 않는다
    asked["answer"] = str(src)
    r2 = mw.action_pages_to_pdf(str(src), [0]); spin(0.3)
    chk(Path(asked.get("default", "")).name == "지침_1쪽.pdf", "D 한 쪽이면 <원본>_<n>쪽.pdf", asked.get("default"))
    chk(r2 is None and hashlib.sha256(src.read_bytes()).hexdigest() == digest, "D 원본과 같은 이름은 받지 않는다(원본 그대로)")

    # E 붙여넣은 쪽 · 암호 PDF
    n_before = len(guard.seen)
    r3 = mw.action_pages_to_pdf(str(src), [1, ("other.pdf", 0)])
    chk(r3 is None and any("붙여넣은 쪽" in t for _l, _k, t in guard.seen[n_before:]),
        "E 붙여넣은 쪽이 섞이면 '먼저 저장' 알림", str(guard.seen[n_before:]))
    enc = root / "잠금.pdf"
    d = fitz.open(); d.new_page().insert_text((72, 100), "secret"); d.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256,
                                                                        user_pw="u1", owner_pw="o1"); d.close()
    asked["answer"] = str(root / "잠금_1쪽.pdf")
    n_before = len(guard.seen)
    r4 = mw.action_pages_to_pdf(str(enc), [0]); spin(0.3)
    chk(r4 is None and not (root / "잠금_1쪽.pdf").exists() and any("암호" in t for _l, _k, t in guard.seen[n_before:]),
        "E 암호 PDF 는 만들지 않고 알린다(새 파일이 암호 없이 저장되므로)", str(guard.seen[n_before:]))
    chk(not list(root.glob("~*.polypdf-tmp")), "임시 파일을 남기지 않는다", str(list(root.glob("~*"))))
    _pf.subset_fonts_safely = _real_subset
    mw.close(); spin(0.2)
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
