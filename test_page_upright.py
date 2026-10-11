# -*- coding: utf-8 -*-
"""261011-2: 회전은 `/Rotate` 그대로 — 바로 세우기 없음, 회전한 쪽 서명, '저장' 의 다른 뷰어용 사본, 평탄화 내보내기
(마스터 §4.7.13·§4.7.16 · 보안 SOT §3.3). 이름은 옛 '쪽 바로 세우기' 검사 그대로(검사 색인 §14.7.1).

A. 꾸밈 굽기(`_bake_decorations`) — `/Rotate` 0·90·180·270 쪽에서 보이는 자리 그대로(종전 결함: 회전 전 좌표로 그려 어긋남)
B. 평탄화해서 내보내기 — 새 파일로만, 저장 전 회전은 `/Rotate` 에 더함(0 으로 세우지 않음), 다른 쪽의 빈 서명 칸·양식은 그대로, 원본 그대로
C. 회전한 쪽 서명 — 막지 않고 유효, 겉모양 그림에 반대로 돌리는 `/Matrix`
D. '저장' 의 사본 — 'PolyPDF' 레이어(다른 뷰어=pdfium 에 보임 · PolyPDF 화면에서는 끔), 링크 사본(`/NM`), 태그 `/Keywords`,
   바뀐 것이 없으면 다시 쓰지 않음, 고치면 옛 사본을 지우고 새로, 서명된 문서에는 넣지 않음
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

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_upright_%d" % os.getpid())

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
    """빨강 화소의 테두리 상자(보이는 좌표 비율) — 없으면 None."""
    xs, ys = [], []
    for y in range(0, pix.height, 2):
        for x in range(0, pix.width, 2):
            r, g, b = pix.pixel(x, y)[:3]
            if r > 200 and g < 90 and b < 90:
                xs.append(x); ys.append(y)
    if not xs:
        return None
    return (min(xs) / pix.width, min(ys) / pix.height, max(xs) / pix.width, max(ys) / pix.height)


def pdfium_red(path, pno=0):
    import pypdfium2
    pg = pypdfium2.PdfDocument(str(path))[pno]
    im = pg.render(scale=0.5).to_pil().convert("RGB")
    w, h = im.size
    xs, ys = [], []
    px = im.load()
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b = px[x, y]
            if r > 200 and g < 90 and b < 90:
                xs.append(x); ys.append(y)
    return (min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h) if xs else None


RED = {"shape": "rect", "rect": [0.05, 0.05, 0.30, 0.12], "color": "#ff0000", "fill": "full", "width": 2, "alpha": 100}


def near(box, want, tol=0.03):
    return box is not None and all(abs(a - b) < tol for a, b in zip(box, want))


tmp = Path(tempfile.mkdtemp(prefix="polypdf_upright_"))
try:
    from viewer.app import MainWindow
    from viewer import sign_core as sc, sign_store as st, pdf_mirror as pm
    import viewer.widgets.sign_dialogs as sdlg
    root = tmp / "folder"; root.mkdir()

    # ── A ── 꾸밈 굽기는 보이는 자리 그대로(회전 4가지)
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 820); mw.show(); spin(0.3)
    mw.open_folder(str(root)); spin(0.5)
    bad = []
    for rot in (0, 90, 180, 270):
        d = fitz.open(); p = d.new_page(width=595, height=842); p.insert_text((72, 100), "TEXT", fontsize=20); p.set_rotation(rot)
        f = root / f"a{rot}.pdf"; d.save(str(f)); d.close()
        mw._ensure_page_meta_store().set_drawings(str(f), 0, [dict(RED)])
        d = fitz.open(str(f))
        mw._bake_decorations(d, str(f))
        got = red_box(d[0].get_pixmap(dpi=40))
        if not near(got, (0.05, 0.05, 0.30, 0.12)):
            bad.append((rot, got))
        d.close()
    chk(not bad, "A1 꾸밈 굽기 — /Rotate 0·90·180·270 모두 보이는 자리 그대로", str(bad))

    # ── B ── 평탄화해서 내보내기
    src = root / "도면.pdf"
    d = fitz.open()
    for i in range(3):
        p = d.new_page(width=595, height=842); p.insert_text((72, 100), f"PAGE{i} TOP LEFT", fontsize=20)
    d[0].set_rotation(90)                                   # PDF 안에서 회전된 쪽
    w = fitz.Widget(); w.field_type = fitz.PDF_WIDGET_TYPE_TEXT; w.field_name = "memo"; w.rect = fitz.Rect(72, 300, 300, 330)
    d[2].add_widget(w)
    d.save(str(src)); d.close()
    tmp_ef = root / "~ef.tmp"
    sc.add_empty_field(str(src), str(tmp_ef), page_index=1, box_pdf=(72, 600, 272, 660), name="승인자")
    shutil.move(str(tmp_ef), str(src))
    mw.open_pdfs([str(src)]); spin(1.0)
    mw._rotate_pages([0], +90); spin(0.8)                  # 저장 전 회전 → 보이는 합 180
    ms = mw._ensure_page_meta_store()
    ms.set_drawings(str(src), 0, [dict(RED)]); ms.save()
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.warning = staticmethod(lambda *a, **k: print("   [warning]", a[1:3]))
    out = root / "도면_평탄화.pdf"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out), "PDF (*.pdf)"))
    mw._action_save_decorated_pdf(file_path=str(src)); spin(1.0)
    with fitz.open(str(out)) as o:
        chk(o[0].rotation == 180, "B1 저장 전 회전은 /Rotate 에 더한다(90+90=180, 0 으로 세우지 않음)", str(o[0].rotation))
        chk(near(red_box(o[0].get_pixmap(dpi=40)), (0.05, 0.05, 0.30, 0.12)), "B2 꾸밈이 보이는 자리 그대로 구워졌다",
            str(red_box(o[0].get_pixmap(dpi=40))))
        names = sorted(w.field_name for p in o for w in (p.widgets() or []))
        chk(names == ["memo", "승인자"], "B3 다른 쪽의 빈 서명 칸·양식은 굽지 않고 그대로", str(names))
        chk(bool(o[0].search_for("PAGE0")), "B4 글자 검색은 그대로")
    with fitz.open(str(src)) as f0:
        chk(f0[0].rotation == 90, "B5 원본은 그대로(새 파일로만)")

    # ── C ── 회전한 쪽 서명
    mw.bookmark_tree._op_save(str(src)); spin(1.5)        # 저장 전 회전·꾸밈을 PDF 에(서명 전 저장)
    with fitz.open(str(src)) as f0:
        chk(f0[0].rotation == 180, "C0 '저장' 이 회전을 /Rotate 로 넣었다", str(f0[0].rotation))
    pfx, info = sc.create_id("홍길동", "Upright-2026!")
    st.add_id(pfx, info)

    class _Fake(sdlg.SignDialog):
        def exec(self):
            self.cmb_id.setCurrentIndex(self.cmb_id.findData(info.fp))
            self.ed_pw.setText("Upright-2026!")
            self._sign()
            return QDialog.DialogCode.Accepted
    _Real = sdlg.SignDialog
    sdlg.SignDialog = _Fake
    picks = ("새 자리 끌기", "그림 없이")          # 빈 서명 칸이 있는 문서 — 새 자리에, 서명 그림 없이
    orig_exec = QMessageBox.exec
    QMessageBox.exec = lambda self: (setattr(self, "_pick", next((b for b in self.buttons() if any(t in b.text() for t in picks)), None)), 0)[1]
    QMessageBox.clickedButton = lambda self: getattr(self, "_pick", None)
    told = []
    QMessageBox.information = staticmethod(lambda *a, **k: told.append(a[2] if len(a) > 2 else ""))
    mv = mw.main_view
    mw.action_sign_pdf(); spin(0.3)
    mv = mw.main_view
    z = mv._zoom or 1.0
    mv.signRegionSelected.emit(QRectF(300 * z, 400 * z, 520 * z, 480 * z)); spin(2.0)
    sdlg.SignDialog = _Real
    QMessageBox.exec = orig_exec
    rep = sc.verify_pdf(str(src), st.trusted())
    chk(not any("회전" in m for m in told) and rep.sigs and rep.worst == sc.OK_TRUSTED,
        "C1 회전한 쪽에도 막지 않고 서명 — 유효·신뢰함", str((told[-1:], rep.worst)))
    with fitz.open(str(src)) as f0:
        sw = [w for w in (f0[0].widgets(types=[fitz.PDF_WIDGET_TYPE_SIGNATURE]) or []) if w.is_signed]
        ap_ok = False
        if sw:
            t, ap = f0.xref_get_key(sw[0].xref, "AP/N")
            if t == "xref":
                mt, mv_ = f0.xref_get_key(int(ap.split()[0]), "Matrix")
                ap_ok = mt == "array" and [round(float(v)) for v in mv_.strip("[]").split()][:4] == [-1, 0, 0, -1]
        chk(ap_ok, "C2 겉모양 그림에 쪽 회전(180)만큼 반대로 돌리는 /Matrix")

    # ── D ── '저장' 의 다른 뷰어용 사본
    dsrc = root / "사본.pdf"
    d = fitz.open()
    for i in range(2):
        p = d.new_page(width=595, height=842); p.insert_text((72, 100), f"COPY{i}", fontsize=20)
    d[1].set_rotation(90)
    d.save(str(dsrc)); d.close()
    mw.open_pdfs([str(dsrc)]); spin(1.0)
    ms.set_drawings(str(dsrc), 0, [dict(RED)]); ms.set_drawings(str(dsrc), 1, [dict(RED)]); ms.save()
    hs = mw._ensure_hyperlink_store()
    hs.add_url_link(str(dsrc), 0, "영상", "https://www.youtube.com/watch?v=x"); hs.save()
    if mw.bookmark_tree._tags:
        mw.bookmark_tree._tags.set(str(dsrc), ["도로", "포장"])
    chk(mw._mirror_needed(str(dsrc)), "D0 사본이 없으니 넣어야 한다")
    mw.bookmark_tree._op_save(str(dsrc)); spin(1.5)
    with fitz.open(str(dsrc)) as f1:
        chk(bool(pm.find_layer(f1) and pm.stored_hash(f1)), "D1 'PolyPDF' 레이어·지문이 들어갔다")
        f2 = fitz.open("pdf", f1.tobytes())
        links = [l for l in f2[0].get_links() if str(l.get("uri", "")).startswith("https://www.youtube.com")]
        chk(bool(links) and f2.xref_get_key(links[0]["xref"], "NM")[1] == pm.LINK_NM,
            "D2 하이퍼링크 사본(링크 주석, /NM 표시)", str(links[:1]))
        chk("도로" in (f1.metadata or {}).get("keywords", "") or not mw.bookmark_tree._tags,
            "D3 태그가 /Keywords 에", str((f1.metadata or {}).get("keywords")))
    chk(near(pdfium_red(dsrc, 0), (0.05, 0.05, 0.30, 0.12), 0.04) and near(pdfium_red(dsrc, 1), (0.05, 0.05, 0.30, 0.12), 0.04),
        "D4 다른 뷰어(pdfium)에 꾸밈이 보이는 자리 그대로(회전 쪽 포함)", str((pdfium_red(dsrc, 0), pdfium_red(dsrc, 1))))
    from viewer.pdf_doc import PdfDocument
    pdv = PdfDocument(str(dsrc))
    chk(red_box(pdv.doc[0].get_pixmap(dpi=40)) is None, "D5 PolyPDF 화면 문서는 레이어를 끈다(두 번 그리지 않음)")
    pdv.close()
    m0 = dsrc.stat().st_mtime_ns
    chk(not mw._mirror_needed(str(dsrc)), "D6 바뀐 것이 없으면 다시 쓰지 않는다")
    mw.bookmark_tree._op_save(str(dsrc)); spin(0.8)
    chk(dsrc.stat().st_mtime_ns == m0, "D6 다시 저장해도 파일이 그대로")
    ms.set_drawings(str(dsrc), 0, [dict(RED, rect=[0.5, 0.5, 0.7, 0.6])]); ms.save()
    mw.bookmark_tree._op_save(str(dsrc)); spin(1.5)
    chk(near(pdfium_red(dsrc, 0), (0.5, 0.5, 0.7, 0.6), 0.04), "D7 꾸밈을 고치면 옛 사본을 지우고 새로(한 번만 보인다)",
        str(pdfium_red(dsrc, 0)))
    # 서명된 문서에는 넣지 않는다
    ms.set_drawings(str(src), 2, [dict(RED)]); ms.save()
    m1 = src.stat().st_mtime_ns
    chk(not mw._mirror_to_pdf(str(src)) and src.stat().st_mtime_ns == m1 and sc.verify_pdf(str(src), st.trusted()).worst == sc.OK_TRUSTED,
        "D8 서명된 문서에는 사본을 넣지 않는다(서명 그대로)")
    mw.close(); spin(0.2)
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
