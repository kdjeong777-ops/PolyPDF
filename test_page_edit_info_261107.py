# -*- coding: utf-8 -*-
"""261107-35: 쪽 편집 저장은 원본 PDF 정보(Info)·XMP 를 그대로 옮긴다 (마스터 §4.7.9).

-31(작업 창)이 찾은 것: `page_edit_build.build` 는 새 문서에 쪽을 복사해 정보 사전이 비었다 — 제목·작성자·Producer 와
`PolyPDFTextLayer`(글자층 저장 기록, 텍스트 창 SOT §5.4.2)·`PolyPDFHash` 가 쪽 하나만 지워 저장해도 사라졌다.
  A  쪽 하나를 지우고 실제 앱 [저장](`_page_edit_save` → `_finalize_save`) → 표준 항목·사용자 키·XMP·ModDate 그대로
  B  다른 PDF 쪽을 끼워도 이 파일의 정보만(끼운 파일의 제목·키는 들어오지 않는다) — `build` 를 바로
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "test")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_pageeditinfo_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


XMP = ('<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
       '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
       'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>XMP 제목</dc:title></rdf:Description></rdf:RDF>'
       '</x:xmpmeta><?xpacket end="w"?>')


def make(path, tag, n, *, info=True):
    d = fitz.open()
    for i in range(n):
        d.new_page(width=595, height=842).insert_text((72, 300), "%s P%d" % (tag, i))
    if info:
        d.set_metadata({"title": "%s 제목" % tag, "author": "%s 작성자" % tag, "producer": "%s Producer" % tag,
                        "modDate": "D:20250101120000+09'00'"})
        ix = int(d.xref_get_key(-1, "Info")[1].split()[0])
        d.xref_set_key(ix, "PolyPDFHash", fitz.get_pdf_str("%s-hash" % tag))
        d.xref_set_key(ix, "PolyPDFTextLayer", fitz.get_pdf_str("D:20251107120000+09'00' ocr 3"))
        d.set_xml_metadata(XMP)
    d.save(str(path)); d.close()


def info_of(path):
    d = fitz.open(str(path))
    try:
        ix = d.xref_get_key(-1, "Info")
        keys = {}
        if ix[0] == "xref":
            x = int(ix[1].split()[0])
            keys = {k: d.xref_get_key(x, k)[1] for k in d.xref_get_keys(x)}
        return dict(d.metadata or {}), keys, d.get_xml_metadata() or "", d.page_count
    finally:
        d.close()


root = Path(tempfile.mkdtemp(prefix="pageeditinfo_"))
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", root / "b.pdf"
    make(a, "A", 4); make(b, "B", 2)

    # A — 실제 앱 저장
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    bt = mw.bookmark_tree
    bt.btn_edit.setChecked(True); spin(0.3)
    pt = mw.page_thumbs
    pt.list.clearSelection(); pt.list.item(1).setSelected(True); pt._delete_selected(); spin(0.3)
    mw._edit_dirty = True
    mw._save_current_file(); spin(4.0)
    md, keys, xmp, n = info_of(a)
    chk(n == 3, "A 준비: 쪽 하나를 지우고 저장했다", n)
    chk(md.get("title") == "A 제목" and md.get("author") == "A 작성자" and md.get("producer") == "A Producer",
        "A1 제목·작성자·Producer 가 남는다", md)
    # PolyPDFHash 는 저장 길이 새 내용으로 다시 적는다(값은 그쪽 몫) — 여기서는 글자층 기록이 그대로인지 본다
    chk("ocr 3" in keys.get("PolyPDFTextLayer", "") and "PolyPDFHash" in keys,
        "A2 PolyPDF 키(PolyPDFTextLayer 그대로·PolyPDFHash 있음)", keys)
    from viewer import text_apply as ta
    d = fitz.open(str(a)); st = ta.read_text_layer_stamp(d); d.close()
    chk(st is not None and st["pages"] == 3, "A3 글자층 저장 기록을 그대로 읽는다(D6 '파일을 넘겨도 따라간다')", st)
    chk("XMP 제목" in xmp, "A4 XMP 도 옮긴다", xmp[:80])
    chk(md.get("modDate") == "D:20250101120000+09'00'", "A5 ModDate 는 원본 그대로(다른 저장 길과 같다)", md.get("modDate"))
    mw.close()

    # B — 다른 PDF 쪽을 끼워도 이 파일의 정보만
    from viewer import page_edit_build as peb
    a2 = root / "a2.pdf"; make(a2, "A", 3)
    out = peb.build(a2, [("own", 0), ("ext", str(b), 1), ("own", 2)], [], root / "r.pdf", root / "bk.pdf")
    md, keys, xmp, n = info_of(out["path"])
    chk(n == 3 and md.get("title") == "A 제목" and "A-hash" in keys.get("PolyPDFHash", "") and "B" not in md.get("title", ""),
        "B 끼운 파일의 정보는 들어오지 않고 이 파일 정보만", (md.get("title"), keys.get("PolyPDFHash")))
    # 원본에 정보 사전이 없으면 아무것도 만들지 않아도 된다(실패하지 않는다)
    a3 = root / "a3.pdf"; make(a3, "C", 2, info=False)
    out = peb.build(a3, [("own", 1)], [], root / "r3.pdf", root / "bk3.pdf")
    chk(info_of(out["path"])[3] == 1, "B2 정보 사전이 없는 원본도 저장된다")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
