# -*- coding: utf-8 -*-
"""261105-8(마스터 §4.7.14, 사용자 지시 'OCR 결과 등이 이동·복사에 따라 이동/복사되게'): 책갈피창에서 PDF 를
옮기거나 복사하면 **경로를 키로 쓰는 기록**이 새 경로를 따라간다.

종전에는 OCR 쪽·낱말(study.db — 저장본·보류), 고른 낱말(user_study.db), 텍스트 창 고침·하이라이트(text_fix.json),
'OCR 다시 읽은 쪽' 표시가 옛 경로 키에 남아 옮긴 파일에서 **사라진 것처럼** 보였고, 연 폴더 밖으로 옮기거나 복사한 PDF 는
꾸밈·하이퍼링크(폴더 사이드카)도 잃었다. 복사본에는 아무것도 따라가지 않았다. 태그는 이 검사 밖(태그 SOT §6.1).

A. 연 폴더 안 하위 폴더로 **이동** — 저장본·보류 OCR, 고른 낱말, 고침, 다시 읽은 쪽, 꾸밈·링크가 새 경로로, 옛 키에는 없다
B. 연 폴더 밖으로 **복사** — 사본에도 모두(꾸밈·링크는 그 폴더 사이드카에), 원본 것은 그대로
C. 연 폴더 밖으로 **이동** — 그 폴더 사이드카로 옮기고 연 폴더 사이드카의 옛 키는 지운다
D. 이름 변경과 같은 길 — `_on_files_relocated` 가 `_carry_records` 를 부른다(사진 복사도 `filesCopied`)
"""
import os, sys, time, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

from PyQt6.QtCore import QCoreApplication
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_carry_%d" % os.getpid())   # 마스터 §14.7.2-3
import modal_guard                                                        # §14.7.2-6
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


root = Path(tempfile.mkdtemp(prefix="polypdf_carry_"))
try:
    from viewer.study import study_store as ss
    ss.enable_pending(True, path=root / "pending" / "study_pending_test.db")
    folder = root / "f"; folder.mkdir()
    sub = folder / "sub"; sub.mkdir()
    out = root / "out"; out.mkdir()
    out2 = root / "out2"; out2.mkdir()
    a, b = folder / "a.pdf", folder / "b.pdf"
    for p_ in (a, b):
        d = fitz.open(); d.new_page().insert_text((40, 80), p_.stem); d.save(str(p_)); d.close()

    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    QMessageBox.warning = staticmethod(lambda *a_, **k: None)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)

    from viewer.study.study_store import StudyStore, UserStore, file_key_for, default_db_path
    from viewer.text_fix_store import store as fix_store
    from viewer.page_meta import PageMetaStore
    from viewer.hyperlinks import HyperlinkStore

    W = [{"surface": "hello", "lemma": "hello", "x0": 1, "y0": 1, "x1": 9, "y1": 9}]

    def seed(p):
        """저장본(쪽 0) + 보류(쪽 1) OCR, 고른 낱말, 고침, 다시 읽은 쪽, 꾸밈·링크."""
        k = file_key_for(p)
        ss.enable_pending(False)
        st = StudyStore(); st.save_page(k, 0, "saved text", dpi=300, engine="t", source="ocr", conf=90, words=W, lang="en")
        st.set_meta(k, str(p), 2, "en"); st.close()
        ss.enable_pending(True)
        st = StudyStore(); st.save_page(k, 1, "pending text", dpi=300, engine="t", source="ocr", conf=90, words=W, lang="en"); st.close()
        us = UserStore(); us.add_event(k, "hello", "select"); us.close()
        fix_store().set_fix(str(p), 0, 0, "fixed line")
        mw._text_force_ocr = set(getattr(mw, "_text_force_ocr", None) or set()) | {(str(p), 1)}
        pm = mw._ensure_page_meta_store()
        pm.import_entry(str(p), {"file": {"crop_global": [0, 0, 0, 0], "crop_pages": {}, "hidden": [1],
                                          "rotation": {}, "drawings": {}}})
        pm.save()
        hl = mw._ensure_hyperlink_store()
        hl._data["links"][hl._rel_key(str(p))] = {"0": [{"rect": [1, 2, 3, 4], "kind": "url", "target": "https://example.com"}]}
        hl.save()

    def records(p):
        """(저장본 쪽0 글, 보류 쪽1 글, 고른 낱말, 고침, 다시 읽은 쪽)"""
        k = file_key_for(p)
        st = StudyStore()
        try:
            saved = st.saved_page(k, 0)
            pend = st.get_page_text(k, 1)
        finally:
            st.close()
        us = UserStore()
        try:
            sel = us.selected_set(k)
        finally:
            us.close()
        fx = fix_store().get_fixes(str(p), 0)
        forced = any(str(f) == str(p) for f, _pg in (getattr(mw, "_text_force_ocr", None) or set()))
        return (saved[0] if saved else None, pend, sel, fx, forced)

    def sidecar(folder_, p):
        hs = HyperlinkStore(Path(folder_))
        k = hs._rel_key(str(p))
        return (PageMetaStore(Path(folder_)).export_entry(str(p)), hs._data["links"].get(k) if k else None)

    bt = mw.bookmark_tree
    # ── A. 연 폴더 안으로 이동 ──
    seed(a)
    chk(records(a)[0] == "saved text" and records(a)[1] == "pending text", "A0 심은 기록이 읽힌다", str(records(a)))
    bt._transfer_files([a], sub, True); spin(0.5)
    na = sub / "a.pdf"
    r = records(na)
    chk(na.exists() and r[0] == "saved text", "A1 이동 — 저장본 OCR 이 새 경로로", str(r))
    chk(r[1] == "pending text", "A2 이동 — 보류 OCR 도 새 경로로(보류로 남는다)", str(r))
    chk("hello" in r[2], "A3 이동 — 고른 낱말", str(r))
    chk(bool(r[3]), "A4 이동 — 텍스트 창 고침", str(r))
    chk(r[4], "A5 이동 — 'OCR 다시 읽은 쪽'", str(r))
    o = records(a)
    chk(o[0] is None and o[1] is None and not o[2] and not o[3] and not o[4], "A6 옛 경로 키에는 남지 않는다", str(o))
    pm, hl = sidecar(folder, na)
    chk(bool(pm) and bool(hl), "A7 연 폴더 안 — 꾸밈·링크 새 키", f"pm={pm} hl={hl}")

    # ── B. 연 폴더 밖으로 복사 ──
    seed(b)
    bt._transfer_files([b], out, False); spin(0.5)
    cb = out / "b.pdf"
    r, o = records(cb), records(b)
    chk(cb.exists() and r[0] == "saved text" and r[1] == "pending text" and "hello" in r[2] and r[3] and r[4],
        "B1 복사 — 사본에도 OCR(저장본·보류)·고른 낱말·고침·다시 읽은 쪽", str(r))
    chk(o[0] == "saved text" and o[1] == "pending text" and "hello" in o[2] and o[3] and o[4], "B2 복사 — 원본 것은 그대로", str(o))
    pm, hl = sidecar(out, cb)
    chk(bool(pm) and bool(hl), "B3 연 폴더 밖 사본 — 그 폴더 사이드카에 꾸밈·링크", f"pm={pm} hl={hl}")
    pm0, hl0 = sidecar(folder, b)
    chk(bool(pm0) and bool(hl0), "B4 원본의 꾸밈·링크도 그대로")

    # ── C. 연 폴더 밖으로 이동 ──
    bt._transfer_files([b], out2, True); spin(0.5)
    mb = out2 / "b.pdf"
    r = records(mb)
    chk(mb.exists() and not b.exists() and r[0] == "saved text", "C1 밖으로 이동 — OCR 이 따라간다", str(r))
    pm, hl = sidecar(out2, mb)
    pm0, hl0 = sidecar(folder, b)
    chk(bool(pm) and bool(hl) and not pm0 and not hl0, "C2 밖으로 이동 — 꾸밈·링크가 그 폴더 사이드카로, 옛 키는 지움",
        f"new={pm},{hl} old={pm0},{hl0}")

    # ── D. 길 ──
    src = Path(__file__).with_name("viewer")
    app_src = (src / "app.py").read_text(encoding="utf-8")
    photo_src = (src / "photo_controller.py").read_text(encoding="utf-8")
    body = app_src[app_src.index("def _on_files_relocated"):app_src.index("def _rehome_sidecars")]
    chk("self._carry_records(" in body, "D1 이름 변경·이동 공통 처리기가 기록을 옮긴다")
    chk("filesCopied.emit(" in photo_src, "D2 사진 복사도 filesCopied 를 낸다")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
