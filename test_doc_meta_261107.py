# -*- coding: utf-8 -*-
"""문서 정보 창에서 제목·작성자·주제·키워드 고치기 — 보류했다가 편집 모드 [저장] 때 PDF 정보에 (261107-31, 마스터 §4.12 '고치기').

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 파일은 모두 임시 폴더에 만든다.
W. `doc_meta.write_info` — 한글 값, 다른 Info 키(`/PolyPDFHash`) 그대로, 빈 값은 키를 지움, XMP(속성·요소 꼴) 같은 값, 암호 문서는 암호 그대로
R. `doc_info_rows` — 보류 값이 보이고 항목에 '(저장 안 됨)', 글자층 저장 일시 줄(D6)
A. 편집 모드가 아닐 때 창에서 제목을 고치면 §5.2.1 꼴로 묻고 [예] → 편집 모드·보류, PDF 는 아직 그대로
B. 책갈피창 [저장] (책갈피는 그대로) → PDF 의 제목·키워드가 바뀌고 다른 키 그대로, 보류가 비고, 창이 새 값을 보인다
C. 편집 모드를 끌 때 보류를 센다 — [버림] 이면 보류를 지우고 PDF 는 그대로, [저장] 이면 PDF 에
D. 종료 창(`_confirm_close_edit`)이 보류를 센다
E. 쪽 편집 저장(`_page_edit_save`) 길에도 들어간다
"""
import os, sys, tempfile, time, traceback
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_doc_meta_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "문서 정보 고치기", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=10.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


import fitz

XMP = ('<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
       '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
       'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:pdf="http://ns.adobe.com/pdf/1.3/" pdf:Keywords="old kw">'
       '<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Old Title</rdf:li></rdf:Alt></dc:title>'
       '<dc:creator><rdf:Seq><rdf:li>Old Author</rdf:li></rdf:Seq></dc:creator>'
       '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>')


def make_pdf(p, n=3, xmp=False, **enc):
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((72, 100), "Page %d meta test" % (i + 1))
    d.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 2]])
    d.set_metadata({"title": "Old Title", "author": "Old Author", "producer": "Maker"})
    x = int(d.xref_get_key(-1, "Info")[1].split()[0])
    d.xref_set_key(x, "PolyPDFTestKeep", fitz.get_pdf_str("keep-me"))
    if xmp:
        d.set_xml_metadata(XMP)
    d.save(str(p), **enc); d.close()
    return str(p)


def info_of(p, pw=None):
    d = fitz.open(str(p))
    if pw:
        d.authenticate(pw)
    m = dict(d.metadata)
    x = int(d.xref_get_key(-1, "Info")[1].split()[0])
    m["_hash"] = d.xref_get_key(x, "PolyPDFTestKeep")[1]
    m["_xmp"] = d.get_xml_metadata() or ""
    d.close()
    return m


tmp = Path(tempfile.mkdtemp(prefix="polypdf_doc_meta_"))
try:
    try:
        from viewer import doc_meta
    except ImportError:
        doc_meta = None
    chk(doc_meta is not None, "W doc_meta 모듈")

    # W
    if doc_meta is not None:
        w = make_pdf(tmp / "w.pdf", xmp=True)
        r = doc_meta.write_info(w, {"title": "새 제목", "author": "", "keywords": "가, 나"})
        m = info_of(w)
        chk(m["title"] == "새 제목" and m["keywords"] == "가, 나", "W 한글 제목·키워드", str(m))
        chk(m["author"] == "" and m["producer"] == "Maker", "W 빈 값은 지우고 고치지 않은 키는 그대로", str(m))
        chk(m["_hash"] == "keep-me", "W 다른 Info 키 그대로 — set_metadata 를 쓰지 않는다", m["_hash"])
        chk(r.get("xmp") == "updated" and "새 제목" in m["_xmp"] and 'pdf:Keywords="가, 나"' in m["_xmp"]
            and "Old Author" not in m["_xmp"] and "Old Title" not in m["_xmp"] and m["_xmp"].startswith("<?xpacket"),
            "W XMP 같은 값(요소·속성 꼴), xpacket 그대로", m["_xmp"][:300])
        e = make_pdf(tmp / "e.pdf", encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
        doc_meta.write_info(e, {"subject": "암호 주제"}, password="u")
        d = fitz.open(e)
        chk(d.needs_pass and d.authenticate("u") and d.metadata.get("subject") == "암호 주제", "W 암호 문서 — 암호 그대로, 값 들어감")
        d.close()

    # R
    from viewer import doc_info
    facts = {"path": "x.pdf", "pages": 3}
    info = {"meta": {"title": "Old Title"}, "pages_checked": 3, "pages_no_text": 1, "layer_saved": "2026-11-07 15:30"}
    rows = dict(doc_info.doc_info_rows(facts, info, {"title": "고친 제목"})) if "pending" in doc_info.doc_info_rows.__code__.co_varnames else {}
    chk(rows.get("제목 (저장 안 됨)") == "고친 제목", "R 보류 값과 '(저장 안 됨)'", str(rows))
    chk(rows.get("글자층", "").endswith("2026-11-07 15:30 저장"), "R 글자층 저장 일시(D6)", rows.get("글자층"))
    from viewer import text_apply
    key = getattr(text_apply, "TEXT_LAYER_KEY", "/PolyPDFTextLayer").lstrip("/")
    sp = make_pdf(tmp / "stamp.pdf")
    d = fitz.open(sp)
    x = int(d.xref_get_key(-1, "Info")[1].split()[0])
    d.xref_set_key(x, key, fitz.get_pdf_str("D:20261107153000+09'00' ocr 2"))
    d.saveIncr(); d.close()
    got = doc_info.read_info(sp).get("layer_saved")
    chk(got == "2026-11-07 15:30", "R 글자층 저장 일시 — 파일의 정보 키를 텍스트 창 쪽 함수로 읽는다", repr(got))

    if doc_meta is not None:
        from viewer.app import MainWindow
        folder = tmp / "docs"; folder.mkdir()
        pdf = make_pdf(folder / "가 문서.pdf", xmp=True)
        mw = MainWindow(); mw._skip_save_on_close = True
        mw.resize(1400, 900); mw.show(); pump()
        bt = mw.bookmark_tree
        mw.open_folder(folder)
        pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 1)
        mw.open_pdf(Path(pdf)); pump()
        mw.show_doc_info()
        dlg = mw._doc_info_dlg
        t = dlg._table
        st = mw._doc_info_state[mw._active_pane]
        pump(lambda: (st.get("info") or {}).get("meta") is not None and t.rowCount() > 0)

        def row_of(prefix):
            for r in range(t.rowCount()):
                if t.item(r, 0).text().startswith(prefix):
                    return r
            return -1

        def set_cell(prefix, val):
            mw._doc_info_dialog_refresh(mw._active_pane)
            r = row_of(prefix)
            it = t.item(r, 1)
            chk(bool(it.flags() & Qt.ItemFlag.ItemIsEditable), "  %s 칸은 고칠 수 있다" % prefix)
            it.setText(val)
            pump()

        chk(not bool(t.item(row_of("파일 크기"), 1).flags() & Qt.ItemFlag.ItemIsEditable), "A 다른 칸은 고칠 수 없다")

        # A
        asked = []
        _q = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), QMessageBox.StandardButton.Yes)[1])
        if bt.is_edit_mode():
            bt.set_edit_mode(False); pump()
        chk(not bt.is_edit_mode(), "A 시작은 편집 모드 아님")
        set_cell("제목", "고친 제목")
        QMessageBox.question = _q
        chk(asked and "편집모드로 바꾼 뒤" in asked[0], "A 편집 모드로 바꾼 뒤 고친다고 묻는다", str(asked))
        chk(bt.is_edit_mode() and doc_meta.pending(pdf) == {"title": "고친 제목"}, "A [예] → 편집 모드·보류", str(doc_meta.pending(pdf)))
        chk(info_of(pdf)["title"] == "Old Title", "A PDF 는 아직 그대로")
        chk(row_of("제목 (저장 안 됨)") >= 0, "A 창에 '(저장 안 됨)'")
        set_cell("키워드", "열쇠, 낱말")
        chk(doc_meta.pending(pdf).get("keywords") == "열쇠, 낱말", "A 편집 모드에서는 묻지 않고 보류")

        # B
        r = bt._op_save(pdf, quiet=True)
        pump(lambda: not doc_meta.has_pending(pdf), timeout=15)
        m = info_of(pdf)
        chk(m["title"] == "고친 제목" and m["keywords"] == "열쇠, 낱말", "B [저장] (책갈피 그대로) → PDF 정보에", str(m))
        chk(m["_hash"] == "keep-me" and m["producer"] == "Maker" and m["author"] == "Old Author", "B 다른 키 그대로", str(m))
        chk("고친 제목" in m["_xmp"], "B XMP 도", m["_xmp"][:200])
        chk(not doc_meta.has_pending(pdf), "B 보류가 비었다")
        d = fitz.open(pdf); chk(len(d.get_toc()) == 2, "B 책갈피 그대로"); d.close()
        pump(lambda: (mw._doc_info_state[mw._active_pane].get("info") or {}).get("meta", {}).get("title") == "고친 제목", timeout=10)
        mw._doc_info_dialog_refresh(mw._active_pane)
        chk(t.item(row_of("제목"), 1).text() == "고친 제목" and row_of("제목 (저장 안 됨)") < 0, "B 창이 새 값")

        # C
        pump(lambda: (mw._doc_info_state[mw._active_pane].get("info") or {}).get("meta") is not None)
        if not bt.is_edit_mode():
            bt.btn_edit.setChecked(True); pump()
        set_cell("주제", "버릴 주제")
        chk(doc_meta.has_pending(pdf), "C 보류 있음")
        seen = []
        QMessageBox.question = staticmethod(lambda *a, **k: (seen.append(a[2] if len(a) > 2 else ""), QMessageBox.StandardButton.Discard)[1])
        bt.btn_edit.setChecked(False); pump()
        QMessageBox.question = _q
        chk(bool(seen), "C 편집 모드를 끌 때 보류를 세어 묻는다", str(seen))
        chk(not bt.is_edit_mode() and not doc_meta.has_pending() and info_of(pdf)["subject"] == "", "C [버림] → 보류 지움·PDF 그대로")
        bt.btn_edit.setChecked(True); pump()
        set_cell("주제", "남길 주제")
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Save)
        bt.btn_edit.setChecked(False); pump()
        QMessageBox.question = _q
        pump(lambda: info_of(pdf)["subject"] == "남길 주제", timeout=15)
        chk(info_of(pdf)["subject"] == "남길 주제" and not doc_meta.has_pending(), "C [저장] → PDF 에", str(info_of(pdf)["subject"]))

        # D
        bt.btn_edit.setChecked(True); pump()
        pump(lambda: (mw._doc_info_state[mw._active_pane].get("info") or {}).get("meta", {}).get("subject") == "남길 주제", timeout=10)
        set_cell("작성자", "종료 작성자")
        texts = []
        _exec = QMessageBox.exec

        def _fake_exec(box):
            texts.append(box.text())
            for b in box.buttons():
                if box.buttonRole(b) == QMessageBox.ButtonRole.RejectRole:
                    box._clicked = b
            return 0
        QMessageBox.exec = _fake_exec
        _cb = QMessageBox.clickedButton
        QMessageBox.clickedButton = lambda box: getattr(box, "_clicked", None)
        ok = mw._confirm_close_edit()
        QMessageBox.exec = _exec
        QMessageBox.clickedButton = _cb
        chk(bool(texts) and ok is False and doc_meta.has_pending(pdf), "D 종료 창이 보류를 센다([취소] → 남음)", str(texts))

        # E
        doc_meta.clear_pending()
        doc_meta.set_pending(pdf, "title", "쪽 편집 제목", "고친 제목")
        mw._page_edit_save(pdf, [("Chapter 1", 1, 0), ("Chapter 2", 2, 0)])
        pump(lambda: info_of(pdf)["title"] == "쪽 편집 제목", timeout=15)
        chk(info_of(pdf)["title"] == "쪽 편집 제목" and not doc_meta.has_pending(pdf), "E 쪽 편집 저장 길에도", info_of(pdf)["title"])
        print("INFO - 쪽 편집 저장 뒤 사용자 키:", repr(info_of(pdf)["_hash"]), "producer:", repr(info_of(pdf)["producer"]))
        doc_meta.clear_pending()
        try:
            bt.set_edit_mode(False)
        except Exception:
            pass
        mw.close()
except Exception:
    traceback.print_exc()
    fails.append("예외")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
