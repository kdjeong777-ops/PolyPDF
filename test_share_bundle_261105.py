# -*- coding: utf-8 -*-
"""261105-9(마스터 §4.7.23, 사용자 지시 '전달'·결정 '묶음 파일(.zip)'): PDF + PolyPDF 자료 묶음 만들기·받기.

A. 책갈피창 '전달...' 길(`action_share_files`) — 묶음 `.polypdf.zip` 이 생기고 PDF 는 **바이트 그대로**, 클립보드에 그 파일
B. 목록에 고른 자료만 — OCR(저장본·보류 보이는 그대로)·고른 낱말·고친 글·꾸밈·링크, 태그는 기본 끔
C. 받기(`open_share_bundle`) — 다른 폴더에 풀고 그 경로 키로 OCR(저장본)·고른 낱말·고친 글·꾸밈·링크가 들어가고 목록에 더해진다
D. 내용이 목록 해시와 다르면(바뀐 PDF) 풀기만 하고 자료는 넣지 않는다
E. 안전 — 묶음 안 이름의 폴더·`..` 는 버리고 PDF 만, 더 새 판 묶음은 거절
F. 끌어 놓은 묶음은 받기로 간다(책갈피창·본문·창 — 같은 처리기)
"""
import os, sys, time, tempfile, shutil, json, zipfile, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_share_%d" % os.getpid())   # 마스터 §14.7.2-3
import modal_guard                                                       # §14.7.2-6
modal_guard.install(echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


root = Path(tempfile.mkdtemp(prefix="polypdf_share_"))
try:
    from viewer.study import study_store as ss
    ss.enable_pending(True, path=root / "pending" / "study_pending_test.db")
    folder = root / "f"; folder.mkdir()
    recv = root / "recv"; recv.mkdir()
    a = folder / "a.pdf"
    d = fitz.open(); d.new_page().insert_text((40, 80), "alpha"); d.new_page(); d.save(str(a)); d.close()

    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    QMessageBox.warning = staticmethod(lambda *a_, **k: None)
    from viewer.app import MainWindow
    from viewer import share_bundle, share_controller
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)

    from viewer.study.study_store import StudyStore, UserStore, file_key_for
    from viewer.text_fix_store import store as fix_store
    from viewer.page_meta import PageMetaStore
    from viewer.hyperlinks import HyperlinkStore
    W = [{"surface": "alpha", "lemma": "alpha", "x0": 1, "y0": 1, "x1": 9, "y1": 9}]
    k = file_key_for(a)
    ss.enable_pending(False)
    st = StudyStore(); st.save_page(k, 0, "saved text", dpi=300, engine="t", source="ocr", conf=90, words=W, lang="en")
    st.set_meta(k, str(a), 2, "en"); st.close()
    ss.enable_pending(True)
    st = StudyStore(); st.save_page(k, 1, "pending text", dpi=300, engine="t", source="ocr", conf=90, words=W, lang="en"); st.close()
    us = UserStore(); us.add_event(k, "alpha", "select"); us.close()
    fix_store().set_fix(str(a), 0, 0, "fixed line")
    pm = mw._ensure_page_meta_store()
    pm.import_entry(str(a), {"file": {"crop_global": [0, 0, 0, 0], "crop_pages": {}, "hidden": [1], "rotation": {}, "drawings": {}}})
    pm.save()
    hl = mw._ensure_hyperlink_store()
    hl._data["links"][hl._rel_key(str(a))] = {"0": [{"rect": [1, 2, 3, 4], "kind": "url", "target": "https://example.com"}]}
    hl.save()
    try:
        mw._tags.set(str(a), ["비밀분류"])
    except Exception:
        pass

    # ── A. 만들기 ──
    out = root / "send" / "a.polypdf.zip"; out.parent.mkdir()
    share_controller.ShareDialog.exec = lambda self_: QDialog.DialogCode.Accepted
    QFileDialog.getSaveFileName = staticmethod(lambda *a_, **k_: (str(out), ""))
    got = mw.action_share_files([str(a)]); spin(0.3)
    chk(Path(got) == out and out.exists(), "A1 '전달' 이 묶음 파일을 만든다", str(got))
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        same = hashlib.sha256(z.read("a.pdf")).hexdigest() == sha(a)
        man = json.loads(z.read(share_bundle.MANIFEST).decode("utf-8"))
    chk(same and share_bundle.MANIFEST in names, "A2 PDF 는 바이트 그대로 + 자료 목록", str(names))
    urls = QApplication.clipboard().mimeData().urls()
    chk(urls and Path(urls[0].toLocalFile()) == out, "A3 만든 묶음 파일이 클립보드에", str([u.toLocalFile() for u in urls]))
    chk(not list(out.parent.glob("*.tmp")), "A4 임시 파일이 남지 않는다")

    # ── B. 목록 ──
    rec = man["files"][0]
    pages = {r[0]: r[1] for r in (rec.get("ocr") or {}).get("pages", [])}
    chk(pages.get(0) == "saved text" and pages.get(1) == "pending text", "B1 OCR — 저장본·보류 보이는 그대로", str(pages))
    chk(rec.get("sel") and rec.get("fix") and rec.get("page_meta") and rec.get("hyperlinks"),
        "B2 고른 낱말·고친 글·꾸밈·링크", str(sorted(rec)))
    chk("tags" not in rec, "B3 태그는 기본으로 넣지 않는다(내 분류)", str(rec.get("tags")))

    # ── C. 받기 ──
    mw._share_ask_dest = lambda zp, n: recv
    paths = mw.open_share_bundle(out); spin(0.5)
    na = recv / "a.pdf"
    chk(na.exists() and sha(na) == sha(a), "C1 다른 폴더에 PDF 를 그대로 푼다", str(paths))
    kn = file_key_for(na)
    st = StudyStore()
    try:
        sv0, sv1 = st.saved_page(kn, 0), st.saved_page(kn, 1)
    finally:
        st.close()
    chk(sv0 and sv0[0] == "saved text" and sv1 and sv1[0] == "pending text", "C2 받은 OCR 은 그 경로 키의 저장본으로", f"{sv0} {sv1}")
    us = UserStore()
    try:
        chk("alpha" in us.selected_set(kn), "C3 고른 낱말")
    finally:
        us.close()
    chk(bool(fix_store().get_fixes(str(na), 0)), "C4 고친 글")
    pm2 = PageMetaStore(recv).export_entry(str(na))
    hs = HyperlinkStore(recv)
    chk(bool(pm2) and bool(hs._data["links"].get(hs._rel_key(str(na)))), "C5 꾸밈·링크는 그 폴더 사이드카에")
    spin(0.5)
    chk(mw.bookmark_tree.has_file(str(na)), "C6 목록(책갈피창)에 더한다", str(paths))

    # ── D. 바뀐 PDF ──
    bad = root / "bad.polypdf.zip"
    with zipfile.ZipFile(out) as zi, zipfile.ZipFile(bad, "w") as zo:
        for n_ in zi.namelist():
            data = zi.read(n_)
            zo.writestr(n_, data + b"\n%tamper\n" if n_ == "a.pdf" else data)
    recv2 = root / "recv2"; recv2.mkdir()
    mw._share_ask_dest = lambda zp, n: recv2
    mw.open_share_bundle(bad); spin(0.3)
    nb = recv2 / "a.pdf"
    st = StudyStore()
    try:
        chk(nb.exists() and st.saved_page(file_key_for(nb), 0) is None, "D1 해시가 다르면 풀기만 — 자료는 넣지 않는다")
    finally:
        st.close()

    # ── E. 안전 ──
    evil = root / "evil.polypdf.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../../evil.pdf", b"%PDF-1.4\n")
        z.writestr("run.exe", b"MZ")
        z.writestr(share_bundle.MANIFEST, json.dumps({"format": share_bundle.FORMAT, "version": 1, "files": [
            {"name": "../../evil.pdf", "sha256": ""}, {"name": "run.exe", "sha256": ""}]}))
    recv3 = root / "recv3"; recv3.mkdir()
    res = share_bundle.extract(evil, recv3)
    chk([p.name for p, _r, _ok in res] == ["evil.pdf"] and (recv3 / "evil.pdf").exists() and not (root.parent / "evil.pdf").exists(),
        "E1 이름의 폴더·'..' 는 버리고 PDF 만", str(res))
    newer = root / "newer.polypdf.zip"
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr(share_bundle.MANIFEST, json.dumps({"format": share_bundle.FORMAT, "version": 99, "files": []}))
    try:
        share_bundle.read_manifest(newer); ok = False
    except share_bundle.BundleError:
        ok = True
    chk(ok, "E2 더 새 판 묶음은 거절")

    # ── F. 끌어 놓기 ──
    seen = []
    mw.open_share_bundle = lambda p: seen.append(str(p)) or []
    mw._on_paths_dropped(0, [str(out)])
    chk(seen == [str(out)], "F1 끌어 놓은 묶음은 받기로", str(seen))
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
