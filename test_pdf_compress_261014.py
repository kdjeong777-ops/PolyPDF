# -*- coding: utf-8 -*-
"""261014-21: PDF 압축 (마스터 §4.7.19, 개선 로드맵 P3-4).

실제 처리기(책갈피창 신호 `compressFilesRequested` → `action_compress`)로:
A. 새 파일 `<이름>_압축.pdf` — 더 작고, 글자는 그대로, 그림은 목표 해상도로, 원본은 그대로
B. 서명된 PDF·암호 PDF 는 건너뛰고 알린다
C. 더 줄일 것이 없으면 파일을 만들지 않는다
D. 보조 프로세스(`--convert-server`, kind compress)에서 — 이 프로세스에서 그림을 다시 쓰지 않는다
E. 중지하면 만들던 파일을 지운다
"""
import os, sys, tempfile, shutil, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def digest(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


root = Path(tempfile.mkdtemp(prefix="polypdf_compress_test_"))
try:
    import random
    big = root / "Big.pdf"
    d = fitz.open()
    for k in range(2):
        p = d.new_page()
        p.insert_text((72, 72), f"Keep this text {k}", fontsize=14)
        pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1600, 1600), False)
        rnd = random.Random(k)
        pm.set_rect(pm.irect, (rnd.randint(0, 255), 120, 200))
        for _ in range(400):                         # 무늬 — 너무 잘 압축되지 않게
            x, y = rnd.randint(0, 1550), rnd.randint(0, 1550)
            pm.set_rect(fitz.IRect(x, y, x + 50, y + 50), (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255)))
        p.insert_image(fitz.Rect(72, 100, 372, 400), stream=pm.tobytes("png"))   # 300pt 에 1600px ≈ 384 dpi
    d.save(str(big)); d.close()
    small = root / "Tiny.pdf"
    d = fitz.open(); d.new_page().insert_text((72, 72), "only text", fontsize=12); d.save(str(small)); d.close()
    signed = root / "Signed.pdf"
    shutil.copy2(big, signed)
    enc = root / "Locked.pdf"
    d = fitz.open(str(big)); d.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u1", owner_pw="o1"); d.close()
    h_big = digest(big)

    from viewer import sign_core
    _real_signed = sign_core.is_signed_file
    sign_core.is_signed_file = lambda p: Path(p).name == "Signed.pdf" or _real_signed(p)
    from viewer import index_proc
    calls = []
    _real_run = index_proc.run_job

    def spy(job, *a, **k):
        calls.append((k.get("server_arg"), job.get("kind")))
        return _real_run(job, *a, **k)
    index_proc.run_job = spy
    rewrote_here = []
    _real_rw = fitz.Document.rewrite_images
    fitz.Document.rewrite_images = lambda self, *a, **k: (rewrote_here.append(1), _real_rw(self, *a, **k))[1]

    infos = []
    QMessageBox.information = staticmethod(lambda *x, **k: infos.append(x[2] if len(x) > 2 else ""))
    QMessageBox.warning = staticmethod(lambda *x, **k: infos.append(x[2] if len(x) > 2 else ""))
    from viewer import compress_controller as cc
    cc.CompressDialog.exec = lambda dlg: cc.CompressDialog.DialogCode.Accepted
    from viewer.app import MainWindow
    mw = MainWindow(); mw.show(); app.processEvents()
    mw.open_folder(root); QTest.qWait(400)
    mw.bookmark_tree.compressFilesRequested.emit([str(big), str(small), str(signed), str(enc)]); QTest.qWait(300)
    msg = "\n".join(str(x) for x in infos)

    out = root / "Big_압축.pdf"
    chk(out.exists() and out.stat().st_size < big.stat().st_size * 0.8, "A 더 작은 새 파일 <이름>_압축.pdf",
        f"{big.stat().st_size} → {out.stat().st_size if out.exists() else None}")
    if out.exists():
        dd = fitz.open(str(out))
        txt = dd.load_page(1).get_text()
        info = dd.load_page(0).get_image_info()
        w = info[0]["width"] if info else 0
        dd.close()
        chk("Keep this text 1" in txt, "A 글자는 그대로", txt[:60])
        chk(625 <= w <= 800, "A 그림은 목표 해상도(보통 150 dpi × 300pt ≈ 625px) 이상에서 정수 배로 줄인다(1600 → 800)", str(w))
    chk(digest(big) == h_big, "A 원본은 그대로")
    chk("Signed.pdf" in msg and "Locked.pdf" in msg and not (root / "Signed_압축.pdf").exists()
        and not (root / "Locked_압축.pdf").exists(), "B 서명된·암호 PDF 는 건너뛰고 알린다", msg[-300:])
    chk(not (root / "Tiny_압축.pdf").exists() and "Tiny.pdf" in msg, "C 더 줄일 것이 없으면 만들지 않는다")
    chk(("--convert-server", "compress") in calls and not rewrote_here, "D 보조 프로세스에서(이 프로세스는 그림을 다시 쓰지 않는다)",
        f"{calls} here={len(rewrote_here)}")

    # ── E. 중지 ────────────────────────────────────────────────
    from viewer import pdf_compress
    from viewer.convert import Cancelled
    n = {"k": 0}

    def tick(done, total, label):
        n["k"] += 1
        if n["k"] > 3:
            raise Cancelled()
    try:
        pdf_compress.run(str(big), "high", tick)
        stopped = False
    except Cancelled:
        stopped = True
    QTest.qWait(500)
    left = sorted(p.name for p in root.glob("Big_압축*.pdf"))
    chk(stopped and left == ["Big_압축.pdf"], "E 중지하면 만들던 파일을 지운다", f"{stopped} {left}")
finally:
    try:
        index_proc.run_job = _real_run
        sign_core.is_signed_file = _real_signed
        fitz.Document.rewrite_images = _real_rw
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
