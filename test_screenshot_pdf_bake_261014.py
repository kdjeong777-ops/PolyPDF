# -*- coding: utf-8 -*-
"""261014-7: 스크린샷 PDF 저장이 원본 쪽의 꾸밈을 굽는다 (스크린샷 SOT §7, 개선 로드맵 P1-4).

스크린샷 SOT §7 은 '원본 쪽의 주석·하이퍼링크를 구워 낸다' 고 했지만 코드는 원본 쪽을 `insert_pdf` 로 그대로 복사했다 —
저장하지 않은 꾸밈·사진이 결과에서 빠졌다. 실제 처리기(`action_save_screenshot_pdf`)로:
A. 저장 전 사진 꾸밈이 결과 PDF 에 들어간다(인쇄와 같은 굽기 `_baked_src`)
B. 글자는 그대로 남는다
C. '파일 이름 표시' 는 원래 파일 이름이다(구운 사본 이름 '…_baked' 가 아니라)
D. 꾸밈이 없는 문서는 원본 그대로 복사한다(그림 0)
"""
import os, sys, tempfile, shutil, base64
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=10, ms=20):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


root = Path(tempfile.mkdtemp(prefix="polypdf_shotbake_"))
try:
    deco = root / "deco.pdf"; plain = root / "plain.pdf"
    for p, tag in ((deco, "DECO"), (plain, "PLAIN")):
        d = fitz.open()
        for i in range(2):
            d.new_page(width=595, height=842).insert_text((72, 120), f"{tag} page {i + 1}", fontsize=14)
        d.save(str(p)); d.close()
    # 1×1 빨간 PNG
    pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False); pm.set_rect(pm.irect, (255, 0, 0))
    b64 = base64.b64encode(pm.tobytes("png")).decode()

    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1200, 800); mw.show(); app.processEvents()
    mw.open_folder(root); spin(15)
    st = mw._ensure_page_meta_store()
    st.set_images(str(deco), 0, [{"data": b64, "rect": [0.2, 0.1, 0.5, 0.2], "rot": 0.0, "alpha": 100, "shape": "rect"}])
    st.save()

    # 스트립 카드 두 장(원본 PDF 쪽을 가리키는 카드) — 저장 옵션: 파일 이름 표시 켬
    png = root / "c.png"; pm.save(str(png))
    mw.shot_strip.all_meta = lambda: [
        {"path": str(png), "kind": "pdf", "page": 0, "src_pdf": str(deco), "src_page": 0, "src_query": ""},
        {"path": str(png), "kind": "pdf", "page": 0, "src_pdf": str(plain), "src_page": 0, "src_query": ""}]
    from viewer.widgets import screenshot_pdf_dialog as spd

    class _Dlg:
        DialogCode = spd.ScreenshotPdfDialog.DialogCode

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def result_options(self):
            return {"show_query": False, "show_filename": True, "show_pageno": False}
    spd.ScreenshotPdfDialog = _Dlg
    out = root / "shots.pdf"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out), ""))
    ok = mw.action_save_screenshot_pdf(ask_open=False); spin(3)
    chk(ok and out.exists(), "준비 — 스크린샷 PDF 가 생겼다")
    d = fitz.open(str(out))
    try:
        n0 = len(d[0].get_images(full=True)); n1 = len(d[1].get_images(full=True))
        t0, t1 = d[0].get_text(), d[1].get_text()
    finally:
        d.close()
    chk(n0 >= 1, "A 저장 전 사진 꾸밈이 결과에 들어간다(인쇄와 같은 굽기)", f"images={n0}")
    chk("DECO page 1" in t0, "B 글자는 그대로 남는다", t0[:60])
    chk("deco" in t0 and "_baked" not in t0, "C 파일 이름 표시는 원래 이름", t0[:80])
    chk(n1 == 0 and "PLAIN page 1" in t1, "D 꾸밈 없는 문서는 그대로(그림 0)", f"images={n1}")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
