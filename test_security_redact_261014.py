# -*- coding: utf-8 -*-
"""261014-22: 가림 — 개인정보 지우기 (보안 SOT §14, 개선 로드맵 P3-5).

실제 처리기(책갈피창 신호 `redactFileRequested` → `action_redact` → 가림 창)로:
A. 패턴(주민번호·전화·이메일)과 검색어를 찾아 가리면 결과 파일에서 그 글이 뽑히지 않는다(덮기가 아니라 지우기)
B. 쪽 그림 위를 실제 마우스로 끌어 고른 영역 — 그 자리 그림 화소가 검게 지워진다
C. 문서 정보·첨부 파일을 지운다(숨은 데이터), 스캔 쪽의 OCR 글자층은 남긴다(가린 자리 밖)
D. 스캔 쪽은 우리 OCR 낱말 상자로 찾아 가린다
E. 새 파일 `<이름>_가림.pdf`, 원본은 그대로
F. 암호 PDF 는 거부한다
"""
import os, sys, tempfile, shutil, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, Qt, QPoint
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


root = Path(tempfile.mkdtemp(prefix="polypdf_redact_test_"))
try:
    src = root / "R.pdf"
    d = fitz.open()
    p1 = d.new_page()
    p1.insert_text((72, 100), "Name Hong Gildong 900101-1234567", fontsize=11)
    p1.insert_text((72, 120), "tel 010-1234-5678 mail hong.gd@example.com", fontsize=11)
    p1.insert_text((72, 140), "Public sentence stays.", fontsize=11)
    p2 = d.new_page()
    pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False); pm.set_rect(pm.irect, (30, 160, 60))
    p2.insert_image(fitz.Rect(100, 100, 300, 300), stream=pm.tobytes("png"))
    p3 = d.new_page()                                   # 스캔 쪽 — 그림만
    sc = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 400), False); sc.set_rect(sc.irect, (245, 245, 245))
    p3.insert_image(p3.rect, stream=sc.tobytes("png"))
    d.set_metadata({"author": "Hong Gildong", "title": "Private file"})
    d.embfile_add("secret.txt", b"secret attachment")
    d.save(str(src)); d.close()
    h0 = digest(src)
    # 3쪽 OCR 결과(우리 OCR — study.db). 300 dpi 픽셀 좌표
    from viewer.study.study_store import StudyStore, file_key_for
    st = StudyStore()
    words = [("ID", 300, 900, 380, 960), ("900101-2345678", 420, 900, 900, 960), ("visible", 300, 1100, 520, 1160)]
    st.save_page(file_key_for(str(src)), 2, "ID 900101-2345678 visible", dpi=300, engine="tesseract", source="ocr",
                 conf=90.0, lang="eng", words=[{"surface": w, "x0": a, "y0": b, "x1": c, "y1": e} for w, a, b, c, e in words])
    st.close()

    infos = []
    QMessageBox.information = staticmethod(lambda *x, **k: infos.append(("info", x[2] if len(x) > 2 else "")))
    QMessageBox.warning = staticmethod(lambda *x, **k: infos.append(("warn", x[2] if len(x) > 2 else "")))
    from viewer.widgets import redact_dialog as rd
    seen = {}

    def fake_exec(dlg):
        dlg.show(); app.processEvents()
        dlg.ed_custom.setText("Gildong")
        dlg._find(); app.processEvents()
        seen["found"] = [(m["page"], m["kind"], m["text"]) for m in dlg.marks()]
        dlg._go(1); app.processEvents()
        v = dlg.view
        k = dlg._k
        a = v.mapFromScene(150 * k, 150 * k); b = v.mapFromScene(250 * k, 250 * k)
        QTest.mousePress(v.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(v.viewport(), QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
        QTest.mouseMove(v.viewport(), b)
        QTest.mouseRelease(v.viewport(), Qt.MouseButton.LeftButton, pos=b)
        seen["areas"] = [m for m in dlg.marks() if m["page"] == 1]
        return rd.RedactDialog.DialogCode.Accepted
    rd.RedactDialog.exec = fake_exec

    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1200, 800); mw.show(); app.processEvents()
    mw.open_folder(root); QTest.qWait(400)
    mw.bookmark_tree.redactFileRequested.emit(str(src)); QTest.qWait(300)

    out = root / "R_가림.pdf"
    kinds = {k for _p, k, _t in seen.get("found", [])}
    chk({"주민등록번호", "전화번호", "이메일", "검색어"} <= kinds, "준비 — 찾기가 패턴·검색어 자리를 목록에", str(seen.get("found")))
    chk(out.exists(), "E 새 파일 <이름>_가림.pdf", str(infos[-1:]))
    if out.exists():
        r = fitz.open(str(out))
        t1 = r.load_page(0).get_text()
        chk(all(x not in t1 for x in ("900101-1234567", "010-1234-5678", "hong.gd@example.com", "Gildong"))
            and "Public sentence stays." in t1, "A 가린 글은 결과에서 뽑히지 않는다(나머지 글은 그대로)", repr(t1))
        pg2 = r.load_page(1)
        pix = pg2.get_pixmap(dpi=72, clip=fitz.Rect(190, 190, 210, 210))
        c = pix.pixel(10, 10)
        pix_out = pg2.get_pixmap(dpi=72, clip=fitz.Rect(110, 110, 120, 120)).pixel(5, 5)
        chk(len(seen.get("areas", [])) == 1 and max(c) < 30 and pix_out[1] > 100,
            "B 실제 끌기로 고른 영역 — 그림 화소가 검게(영역 밖은 그대로)", f"{c} {pix_out} {seen.get('areas')}")
        chk(not r.metadata.get("author") and not r.metadata.get("title") and r.embfile_count() == 0,
            "C 문서 정보·첨부 파일을 지운다", f"{r.metadata} {r.embfile_count()}")
        k3 = 72.0 / 300
        p3r = fitz.Rect(420 * k3, 900 * k3, 900 * k3, 960 * k3)
        cc = r.load_page(2).get_pixmap(dpi=72, clip=p3r).pixel(3, 3)
        chk(any(pg == 2 and k == "주민등록번호" for pg, k, _t in seen.get("found", [])) and max(cc) < 30,
            "D 스캔 쪽은 우리 OCR 낱말 상자로 찾아 가린다", f"{cc}")
        r.close()
    chk(digest(src) == h0, "E 원본은 그대로")

    # ── F. 암호 PDF ───────────────────────────────────────────────
    enc = root / "Locked.pdf"
    d = fitz.open(str(src)); d.save(str(enc), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o"); d.close()
    infos.clear()
    res = mw.action_redact(str(enc))
    chk(res is None and infos and "암호" in infos[-1][1] and not (root / "Locked_가림.pdf").exists(), "F 암호 PDF 는 거부한다", str(infos))
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
