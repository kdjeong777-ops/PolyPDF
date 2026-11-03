# -*- coding: utf-8 -*-
"""261103-16: 쪽 편집 저장 뒤 OCR·단어장·텍스트 창 고침이 **쪽을 따라간다** (마스터 §4.7.9).

사용자 보고: "새 페이지 넣기 후 저장하면, 텍스트 창과 단어장의 내용이 새 페이지에 다음 페이지의 내용이 나타남".
study.db(OCR 쪽·낱말·쪽별 어휘)와 text_fix.json(고침·칠)은 쪽 번호로 적혀 있는데, 쪽 편집 저장(`_page_edit_save`)은
꾸밈·링크만 새 번호로 옮겼다.

실제 썸네일 조작(새 쪽 넣기·다른 PDF 쪽 끼우기·삭제·아래로 옮기기) → 실제 [저장](`_save_current_file`) → 그 뒤 study.db 와
고침 저장소를 본다. 원본 쪽 A0~A3, 다른 파일 b.pdf 쪽 B1.
  편집:  A0 | 새 흰 쪽 | A1 | B1(끼움) | A3 | (A2 지움)  → 이어서 A1 을 아래로 한 칸: A0 | 흰 | B1 | A1 | A3
  기대:  0=A0  1=없음  2=B1  3=A1  4=A3  — 지운 A2 의 기록은 없다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_pagefollow_%d" % os.getpid())
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


root = Path(tempfile.mkdtemp(prefix="pagefollow_"))
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", root / "b.pdf"
    for path, tag, n in ((a, "A", 4), (b, "B", 3)):
        d = fitz.open()
        for i in range(n):
            d.new_page(width=595, height=842).insert_text((72, 300), "%s P%d" % (tag, i))
        d.save(str(path)); d.close()
    from viewer.study.study_store import StudyStore, file_key_for
    from viewer import text_fix_store
    st = StudyStore()
    for path, tag, n in ((a, "A", 4), (b, "B", 3)):
        k = file_key_for(path)
        for i in range(n):
            w = "%s%dword" % (tag, i)
            st.save_page(k, i, "%s%d text" % (tag, i), dpi=300, engine="t", source="ocr", conf=90,
                         words=[{"surface": w, "lemma": w, "x0": 1, "y0": 1, "x1": 9, "y1": 9}], lang="eng")
            st.conn.execute("INSERT OR REPLACE INTO vocab_page(file_key,page,lemma,lang,count,pos) VALUES(?,?,?,?,1,0)",
                            (k, i, w, "eng"))
            st.conn.execute("INSERT OR REPLACE INTO vocab(file_key,lemma,lang,level,zipf,freq_in_book) VALUES(?,?,?,?,3,1)",
                            (k, w, "eng", "B1"))
        st.conn.commit()
    st.close()
    fx = text_fix_store.store()
    for path, tag, n in ((a, "A", 4), (b, "B", 3)):
        for i in range(n):
            fx.set_fix(str(path), i, 0, "%s%d fixed" % (tag, i), orig="x", rect=(1, 1, 9, 9))
            fx.add_highlight(str(path), i, 0, 0, 2)

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    bt = mw.bookmark_tree
    bt.btn_edit.setChecked(True); spin(0.4)
    pt = mw.page_thumbs

    def sel(row):
        pt.list.clearSelection(); pt.list.item(row).setSelected(True)
        pt.list.setCurrentItem(pt.list.item(row))
    # 새 흰 쪽(A0 뒤) — 실제 메뉴 처리기 대신 같은 자리의 함수
    sel(0)
    if hasattr(pt, "_insert_blank_after"):
        pt._insert_blank_after(0)
    else:
        from PyQt6.QtWidgets import QMenu
        _orig = QMenu.exec
        QMenu.exec = lambda self, *a_, **k: next(x for x in self.actions() if x.text().startswith("새 페이지 넣기"))
        try:
            pt._on_list_menu(pt.list.visualItemRect(pt.list.item(0)).center()); spin(0.4)
        finally:
            QMenu.exec = _orig
    spin(0.3)
    chk(pt.list.count() == 5, "준비: 새 흰 쪽을 넣었다", pt.list.count())
    pt.insert_external_pages(2, str(b), [1]); spin(0.3)           # A1 뒤에 B1
    rows = [pt.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(pt.list.count())]
    i_a2 = rows.index(2)
    sel(i_a2); pt._delete_selected(); spin(0.3)                      # A2 지움
    rows = [pt.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(pt.list.count())]
    sel(rows.index(1)); pt._move_selected(+1); spin(0.3)             # A1 을 아래로(B1 뒤)
    plan = pt.current_page_plan()
    chk([p[0] for p in plan] == ["own", "ext", "ext", "own", "own"] and plan[3] == ("own", 1) and plan[2][2] == 1,
        "준비: A0 | 흰 | B1 | A1 | A3", plan)
    mw._edit_dirty = True
    mw._save_current_file(); spin(4.0)
    sd = fitz.open(str(a)); texts = [p.get_text().strip() for p in sd]; sd.close()
    chk(texts == ["A P0", "", "B P1", "A P1", "A P3"], "준비: 저장된 PDF 쪽 차례", texts)

    k = file_key_for(a)
    st = StudyStore()
    pages = {r[0]: r[1] for r in st.conn.execute("SELECT page, text FROM ocr_page WHERE file_key=?", (k,))}
    words = {r[0]: r[1] for r in st.conn.execute("SELECT page, surface FROM ocr_word WHERE file_key=?", (k,))}
    vp = {r[0]: r[1] for r in st.conn.execute("SELECT page, lemma FROM vocab_page WHERE file_key=?", (k,))}
    voc = {r[0] for r in st.conn.execute("SELECT lemma FROM vocab WHERE file_key=?", (k,))}
    st.close()
    want = {0: "A0", 2: "B1", 3: "A1", 4: "A3"}
    chk(pages == {p: t + " text" for p, t in want.items()}, "1 OCR 쪽 글이 쪽을 따라갔다(새 쪽은 비고, 지운 A2 는 없다)", pages)
    chk(words == {p: t + "word" for p, t in want.items()}, "2 OCR 낱말 상자도", words)
    chk(vp == {p: t + "word" for p, t in want.items()}, "3 쪽별 어휘(단어장)도", vp)
    chk("B1word" in voc, "4 끼운 쪽의 어휘가 이 파일 어휘에 더해졌다", sorted(voc))
    fx.load()
    fixes = {p: fx.get_fixes(str(a), p).get(0) for p in range(5)}
    chk(fixes == {0: "A0 fixed", 1: None, 2: "B1 fixed", 3: "A1 fixed", 4: "A3 fixed"}, "5 텍스트 창 고침이 쪽을 따라갔다", fixes)
    hls = {p: bool(fx.get_highlights(str(a), p)) for p in range(5)}
    chk(hls == {0: True, 1: False, 2: True, 3: True, 4: True}, "6 텍스트 창 칠도", hls)
    chk(fx.get_fixes(str(b), 1).get(0) == "B1 fixed", "7 끼워 온 파일(b.pdf)의 기록은 그대로")

    # 9 — 쪽은 그대로, 꾸밈만 바꿔 '다른 이름으로 저장'(책갈피창 `_carry_meta`) — 새 파일에도 OCR·고침이 같은 쪽에
    from PyQt6.QtWidgets import QFileDialog
    QFileDialog.getSaveFileName = staticmethod(lambda *a_, **k: ((a_[2] if len(a_) > 2 else ""), "PDF (*.pdf)"))
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    mv = mw.main_view
    mv.go_to_page(0); spin(0.3)
    mv._page_strokes = [{"text_box": True, "rect": [0.1, 0.1, 0.4, 0.16], "text": "DECO", "size_pt": 12}]
    mv._save_page_strokes(); mw._edit_dirty = True
    mw._action_save_as(); spin(4.0)
    ea = sorted(folder.glob("a_edited*.pdf"))
    chk(len(ea) == 1, "9 준비: 새 이름 파일", [x.name for x in folder.iterdir()])
    if ea:
        st = StudyStore()
        p9 = {r[0]: r[1] for r in st.conn.execute("SELECT page, text FROM ocr_page WHERE file_key=?", (file_key_for(ea[0]),))}
        p9a = {r[0] for r in st.conn.execute("SELECT page FROM ocr_page WHERE file_key=?", (k,))}
        st.close()
        chk(p9 == {p: t + " text" for p, t in want.items()}, "9 새 이름 파일에도 OCR 이 같은 쪽에", p9)
        chk(p9a == set(want), "9 원본 파일의 OCR 은 그대로", p9a)
        fx.load()
        chk(fx.get_fixes(str(ea[0]), 2).get(0) == "B1 fixed", "9 새 이름 파일에도 텍스트 창 고침")
    mw.close()

    # 8 — 보류 저장소([저장] 전 OCR, 단어학습 SOT §14.21)도 옮긴다: 새 이름 저장이면 원본 기록은 그대로
    from viewer.study import study_store as ss
    ss.enable_pending(True, path=root / "pend.db")
    try:
        ps = StudyStore(root / "s.db")
        ps.save_page("src", 0, "P0", dpi=300, engine="t", source="ocr", conf=90, words=[], lang="eng")
        ps.save_page("src", 1, "P1", dpi=300, engine="t", source="ocr", conf=90, words=[], lang="eng")
        ps.remap_pages("dst", [("src", 1), None, ("src", 0)])
        got = {r[0]: r[1] for r in ps.conn.execute("SELECT page, text FROM p.ocr_page WHERE file_key='dst'")}
        chk(got == {0: "P1", 2: "P0"}, "8 보류 중인 OCR 도 새 쪽 번호로(보류로 남는다)", got)
        src_left = {r[0] for r in ps.conn.execute("SELECT page FROM p.ocr_page WHERE file_key='src'")}
        chk(src_left == {0, 1}, "8 새 이름 저장이면 원본 키의 기록은 그대로", src_left)
        ps.close()
    finally:
        ss.enable_pending(False)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
