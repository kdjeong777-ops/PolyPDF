# -*- coding: utf-8 -*-
"""261010-24: 일반뷰어용 저장 — 보기 회전을 넣고 쪽을 바로 세운다 (마스터 §4.7.13 '회전도 넣고 쪽을 바로 세운다', 보안 SOT §3.3).

A. make_upright — PDF /Rotate 90·180·270 × 보기 회전 × MediaBox 원점이 0 이 아닌 쪽 × CropBox:
   /Rotate 0 · 보이는 모양 같음 · 글자 검색 · 링크가 같은 글자 위 · PDF 주석은 내용으로 구워짐
   (수정 전 — 그냥 remove_rotation — 이면 링크가 사라지거나 엉뚱한 자리, 주석이 쪽 밖으로 간다)
B. 실제 MainWindow — 썸네일 회전 → '저장(일반뷰어용)' 현재 파일 → /Rotate 0·모양 그대로·page_meta 회전 비움
   → 그 쪽에 전자서명이 막히지 않고 겉모양이 바로 선다(서명 유효)
C. 할 일이 회전뿐이어도 저장한다 · 새 파일로 저장하면 원본·보기 회전은 그대로
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["POLYPDF_FAKE_HELLO"] = "1"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QRectF
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog, QFileDialog
from PIL import Image, ImageChops, ImageStat

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_upright_%d" % os.getpid())
from viewer.page_upright import make_upright

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def gray(page, dpi=30):
    pix = page.get_pixmap(dpi=dpi)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")


def diff(a, b):
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0] if a.size == b.size else 999.0


def mk(path, offset=False, crop=False, prot=0):
    d = fitz.open(); p = d.new_page(width=595, height=842)
    if offset:
        p.set_mediabox(fitz.Rect(10, 20, 605, 862))
    o = p.rect.tl
    p.insert_text(o + (72, 100), "TOP LEFT TEXT", fontsize=20)
    p.draw_rect(fitz.Rect(300, 500, 400, 700) + (o.x, o.y, o.x, o.y), color=(1, 0, 0), width=4)
    p.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 80, 250, 105) + (o.x, o.y, o.x, o.y), "uri": "https://x.y"})
    p.add_highlight_annot(fitz.Rect(72, 80, 250, 105) + (o.x, o.y, o.x, o.y))
    if crop:
        p.set_cropbox(fitz.Rect(30, 30, 500, 800))
    p.set_rotation(prot)
    d.save(str(path)); d.close()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_upright_"))
try:
    # ── A ──
    bad = []
    for offset in (False, True):
        for crop in (False, True):
            for prot, vrot in ((90, 0), (0, 90), (90, 90), (180, 0), (0, 270), (270, 180)):
                f = tmp / f"a_{int(offset)}{int(crop)}_{prot}_{vrot}.pdf"   # Windows: 앞 판의 d 가 열려 있어 같은 이름은 덮어쓰지 못한다
                mk(f, offset, crop, prot)
                d = fitz.open(str(f)); p = d[0]
                p.set_rotation((prot + vrot) % 360)
                exp = gray(p)
                p.set_rotation(prot)
                d2, n = make_upright(d, {0: vrot})
                d2 = fitz.open("pdf", d2.tobytes())
                q = d2[0]
                t = q.search_for("TOP")
                L = q.get_links()
                ok = (n == 1 and q.rotation == 0 and diff(exp, gray(q)) < 2 and t and L
                      and L[0]["from"].intersects(t[0]) and not list(q.annots()))
                if not ok:
                    bad.append((offset, crop, prot, vrot, q.rotation, round(diff(exp, gray(q)), 2), bool(t), len(L)))
    chk(not bad, "A1 24가지(원점·크롭·/Rotate·보기 회전) — /Rotate 0·모양 같음·글자 검색·링크 자리·주석은 내용으로", str(bad))
    d = fitz.open(); d.new_page()
    same, n0 = make_upright(d, {})
    chk(same is d and n0 == 0, "A2 돌릴 쪽이 없으면 문서를 그대로 둔다(사본도 만들지 않음)")

    # ── B ──
    from viewer.app import MainWindow
    from viewer import sign_core as sc
    import viewer.widgets.sign_dialogs as sdlg
    root = tmp / "folder"; root.mkdir()
    doc_path = root / "도면.pdf"
    mk(doc_path, prot=90)                         # PDF 안에서 90° 회전된 쪽
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 820); mw.show(); spin(0.3)
    mw.open_folder(str(root)); spin(0.8)
    mw.open_pdfs([str(doc_path)]); spin(1.0)
    mv = mw.main_view
    mw._rotate_pages([0], +90)                    # 보기 회전 90 더 → 보이는 합 180
    spin(0.3)
    chk(mw._rotations_for(str(doc_path)) == {0: 90}, "B0 썸네일 회전이 page_meta 에 들어갔다")
    ref = fitz.open(str(doc_path)); ref[0].set_rotation(180); want = gray(ref[0]); ref.close()

    picked = {"text": ""}
    orig_exec = QMessageBox.exec
    QMessageBox.exec = lambda self: (setattr(self, "_pick", next((b for b in self.buttons() if picked["text"] and picked["text"] in b.text()), None)), 0)[1]
    QMessageBox.clickedButton = lambda self: getattr(self, "_pick", None)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.warning = staticmethod(lambda *a, **k: print("   [warning]", a[1:3]))

    # 서명은 먼저 막힌다(회전된 쪽) — 안내가 일반뷰어용 저장을 가리킨다
    told = []
    QMessageBox.information = staticmethod(lambda *a, **k: told.append(a[2] if len(a) > 2 else ""))
    from viewer import sign_store as st
    pfx, info = sc.create_id("홍길동", "Upright-2026!")
    st.add_id(pfx, info)
    mw._sign_pending = str(doc_path)
    mv.signRegionSelected.emit(QRectF(100, 100, 200, 60)); spin(0.3)
    chk(any("일반뷰어용" in m for m in told), "B1 회전된 쪽에 서명하면 막고 '저장(일반뷰어용)' 으로 바로 세우라고 안내", str(told[-1:]))
    QMessageBox.information = staticmethod(lambda *a, **k: None)

    picked["text"] = "현재 파일에 저장"
    mw._action_save_decorated_pdf(file_path=str(doc_path))
    spin(1.0)
    dd = fitz.open(str(doc_path))
    chk(dd[0].rotation == 0, "B2 현재 파일 — /Rotate 0", str(dd[0].rotation))
    chk(diff(want, gray(dd[0])) < 2, "B3 보이는 모양은 회전(PDF 90 + 보기 90 = 180)했던 그대로", "%.2f" % diff(want, gray(dd[0])))
    t = dd[0].search_for("TOP"); L = dd[0].get_links()
    chk(t and L and L[0]["from"].intersects(t[0]), "B4 글자 검색·링크 자리 그대로")
    dd.close()
    chk(mw._rotations_for(str(doc_path)) == {}, "B5 page_meta 보기 회전을 비웠다(두 번 돌지 않게)", str(mw._rotations_for(str(doc_path))))

    class _Fake(sdlg.SignDialog):
        def exec(self):
            self.ed_pw.setText("Upright-2026!"); self._sign()
            return QDialog.DialogCode.Accepted
    sdlg.SignDialog = _Fake
    picked["text"] = "그림 없이"
    mw._open_saved_file(str(doc_path)); spin(0.6)
    mv = mw.main_view
    mw.action_sign_pdf()
    z = mv._zoom or 1.0
    mv.signRegionSelected.emit(QRectF(60 * z, 60 * z, 200 * z, 60 * z)); spin(1.5)
    rep = sc.verify_pdf(str(doc_path), st.trusted())
    dd = fitz.open(str(doc_path))
    w = [x.rect for x in dd[0].widgets()]
    chk(rep.worst == sc.OK_TRUSTED and w and w[0].width > w[0].height,
        "B6 바로 세운 쪽에 서명 — 막히지 않고 유효, 겉모양 상자가 가로로(누워 있지 않음)", "%s %s" % (rep.worst, w))
    dd.close()

    # ── C ──
    only = root / "회전만.pdf"
    mk(only)                                       # /Rotate 0, 링크·주석은 있지만 PolyPDF 꾸밈 없음
    mw.open_pdfs([str(only)]); spin(0.8)
    mw._rotate_pages([0], -90); spin(0.2)
    out_new = root / "회전만_일반뷰어용.pdf"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out_new), "PDF (*.pdf)"))
    picked["text"] = "새 파일로"
    mw._action_save_decorated_pdf(file_path=str(only)); spin(0.8)
    chk(out_new.exists() and fitz.open(str(out_new))[0].rotation == 0
        and fitz.open(str(out_new))[0].rect.width > fitz.open(str(out_new))[0].rect.height,
        "C1 할 일이 보기 회전뿐이어도 저장 — 새 파일은 바로 세운 가로 쪽")
    chk(fitz.open(str(only))[0].rotation == 0 and mw._rotations_for(str(only)) == {0: 270},
        "C2 새 파일로 저장하면 원본·보기 회전은 그대로", str(mw._rotations_for(str(only))))
    QMessageBox.exec = orig_exec
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
