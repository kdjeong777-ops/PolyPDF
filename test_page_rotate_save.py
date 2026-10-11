# -*- coding: utf-8 -*-
"""261011-2: 회전은 쪽 `/Rotate` (마스터 §4.7.16 '회전').

A. 실제 MainWindow — 썸네일 90° 회전 → page_meta 에 저장 전 회전, 열린 문서의 `/Rotate` 에 덧입힘(파일은 그대로),
   화면 픽스맵 돌리기(보기 회전)는 쓰지 않음, 미저장 판정, 회전한 쪽에서 글자 찾기 좌표가 보이는 쪽 안
B. 💾 저장 → 파일 `/Rotate`, page_meta 회전 비움, 다시 열어도 두 번 돌지 않음
C. 쪽 편집과 함께 — 순서를 바꿔 저장해도 회전이 그 쪽을 따라간다(`page_edit_build.build(rotations=)`)
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
QCoreApplication.setApplicationName("polypdf_rot_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def mk(path, n=3):
    d = fitz.open()
    for i in range(n):
        p = d.new_page(width=595, height=842)
        p.insert_text((72, 100), f"PAGE{i} TOP LEFT", fontsize=20)
    d.save(str(path)); d.close()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_rot_"))
try:
    from viewer.app import MainWindow
    root = tmp / "folder"; root.mkdir()
    doc_path = root / "스캔.pdf"
    mk(doc_path)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: print("   [warning]", a[1:3]))
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 820); mw.show(); spin(0.3)
    mw.open_folder(str(root)); spin(0.8)
    mw.open_pdfs([str(doc_path)]); spin(1.0)
    mv = mw.main_view

    # ── A ──
    mw._rotate_pages([1], +90); spin(0.8)
    mv = mw.main_view
    chk(mw._rotations_for(str(doc_path)) == {1: 90}, "A1 회전은 page_meta 에 저장 전 회전으로", str(mw._rotations_for(str(doc_path))))
    chk(mv._doc.doc[1].rotation == 90 and mv._doc.doc[0].rotation == 0, "A2 열린 문서의 /Rotate 에 덧입혔다", str(mv._doc.doc[1].rotation))
    with fitz.open(str(doc_path)) as f:
        chk(f[1].rotation == 0, "A3 저장 전에는 파일이 그대로")
    chk(not mv._rotations and not mw.page_thumbs._rotations, "A4 화면 픽스맵 돌리기(보기 회전)는 쓰지 않는다", str((mv._rotations, mw.page_thumbs._rotations)))
    chk(mw._page_edits_dirty(), "A5 미저장 변경으로 본다")
    pd = mw.page_thumbs._doc.doc
    chk(pd[1].rotation == 90, "A6 썸네일 문서도 /Rotate 로", str(pd[1].rotation))
    q = mv._doc.doc[1]
    hits = q.search_for("PAGE1")
    chk(hits and all(q.rect.contains(h * q.rotation_matrix) for h in hits),
        "A7 회전한 쪽에서도 글자 찾기(보이는 쪽 안 좌표로 옮겨진다)", str(hits))

    # ── B ──
    mw.bookmark_tree._op_save(str(doc_path)); spin(1.5)
    with fitz.open(str(doc_path)) as f:
        chk(f[1].rotation == 90 and f[0].rotation == 0, "B1 💾 저장 → 파일 /Rotate", str([p.rotation for p in f]))
    chk(mw._rotations_for(str(doc_path)) == {}, "B2 page_meta 회전을 비웠다(두 번 돌지 않게)", str(mw._rotations_for(str(doc_path))))
    mv = mw.main_view
    chk(mv._doc.doc[1].rotation == 90 and not mw._page_edits_dirty(), "B3 다시 열어도 90(두 번 돌지 않음)·미저장 없음",
        str(mv._doc.doc[1].rotation))

    # ── C ──
    from viewer import page_edit_build as peb
    src2 = root / "순서.pdf"; mk(src2)
    recon, book = root / "~r.tmp", root / "~b.tmp"
    got = peb.build(src2, [("own", 2), ("own", 0), ("own", 1)], [], recon, book, rotations={0: 270})
    with fitz.open(got["path"]) as f:
        rots = [p.rotation for p in f]
        first = [p.get_text().split()[0] for p in f]
    chk(rots == [0, 270, 0] and first[1] == "PAGE0", "C1 순서를 바꿔도 회전이 그 쪽(원본 1쪽)을 따라간다", str((rots, first)))
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("=== ALL PASS ===" if not fails else "=== FAIL %d ===\n  " % len(fails) + "\n  ".join(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
