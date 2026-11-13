# -*- coding: utf-8 -*-
"""해시태그 수정 창(261113-9 — 종전 이름 '넣기')·복사 때 태그 따라가기·해시태그 폴더로 사본 저장 (태그 SOT §8.7·§6.1-⑥·§8.8, 261111-6·-7·-8).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2 의 3).
A. '#' 메뉴 — 끝에 '해시태그 수정'(261113-9 — 종전 '해시태그 넣기')·'해시태그 폴더로 사본 저장', '새 태그 후보 검토' 는 없다(태그가 없어도 두 항목)
B. 복사(책갈피창 '폴더로 복사' 실제 길) — 사본에 직접·자동 태그가 따라간다(지문은 빼고), 이동은 전처럼 따라간다
C. 해시태그 수정 창 — 썸네일 범위(보이는 줄만), 고른 파일 기준 ☑/◐/☐, [적용]=모두에 붙임, [해제]=모두에서 뗌(자동은 거절),
   태그 추가, 새 태그 후보 적용 → 후보에서 빠짐, 되돌리기·다시 실행, 썸네일 그림(배경)
D. 해시태그 폴더로 사본 저장 — 태그마다 폴더·여러 태그면 폴더마다·'이름 (2)'·사본에 태그
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_apply_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "해시태그 수정", echo=False)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond, timeout=15.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def pdf(p, color=(1, 0, 0)):
    d = fitz.open(); pg = d.new_page(); pg.draw_rect(pg.rect, color=color, fill=color); d.save(p); d.close()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tagapply_"))
try:
    docs = tmp / "docs"; docs.mkdir()
    A, B, C, D = (str(docs / n) for n in ("a.pdf", "b.pdf", "c.pdf", "d.pdf"))
    for p in (A, B, C, D):
        pdf(p)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1100, 700); mw.show(); pump(lambda: False, 0.3)
    bt = mw.bookmark_tree
    st = bt._tags
    mw.open_folder(str(docs)); pump(lambda: len(list(bt._iter_file_nodes())) == 4, 10)

    # A 메뉴
    from PyQt6.QtWidgets import QWidgetAction
    bt._rebuild_tag_menu()
    texts = [a.text() for a in bt._tag_menu.actions() if not isinstance(a, QWidgetAction)]
    chk(texts[-2:] == ["해시태그 수정", "해시태그 폴더로 사본 저장"], "A '#' 메뉴 끝 — 해시태그 수정·사본 저장 (태그 없어도)", str(texts))
    st.set(A, ["가족"]); st.set_auto(A, ["보고서"]); st.set(B, ["가족", "여행"])
    bt._rebuild_tag_menu()
    texts = [a.text() for a in bt._tag_menu.actions() if not isinstance(a, QWidgetAction)]
    chk(texts[-2:] == ["해시태그 수정", "해시태그 폴더로 사본 저장"] and not any("새 태그 후보 검토" in t for t in texts),
        "A 태그가 있어도 끝 두 항목, '새 태그 후보 검토' 없음", str(texts))

    # B 복사·이동
    out = tmp / "out"; out.mkdir()
    v = st._dictify(st._key(A)); v["fp"] = "h64:x"; v["size"] = 1; st._save()
    bt._transfer_files([A], str(out), move=False)
    pump(lambda: st.get(str(out / "a.pdf")) != [], 10)
    cp = str(out / "a.pdf")
    chk(st.get_manual(cp) == ["가족"] and st.get_auto(cp) == ["보고서"], "B 앱 안 복사 — 사본에 직접·자동 태그가 따라간다", str(st.get(cp)))
    rec = st.record(cp) or {}
    chk("fp" not in rec and "size" not in rec, "B 사본에는 지문을 옮기지 않는다", str(rec))
    chk(st.get_manual(A) == ["가족"], "B 원본은 그대로")
    mv_dst = tmp / "mv"; mv_dst.mkdir()
    bt._transfer_files([D], str(mv_dst), move=False)        # D 는 태그 없음 — 사본에 빈 기록이 생기지 않는다
    pump(lambda: (mv_dst / "d.pdf").exists(), 10)
    chk(st.record(str(mv_dst / "d.pdf")) is None, "B 태그 없는 파일의 사본에는 기록을 만들지 않는다")

    # C 해시태그 수정 창
    bt.search_edit.setText("가족"); pump(lambda: False, 0.3)       # 글자 거르기 — 이름에 '가족' 없음 → 결과 없음이면 범위 0
    bt.search_edit.setText(""); pump(lambda: False, 0.3)
    bt.search_edit.setText("#가족"); pump(lambda: False, 0.3)      # A·B 만 보인다
    from viewer.tag_store import save_candidates, load_candidates
    save_candidates({"cand": {"배수성": {"n": 3, "files": [A]}}, "rejected": []})
    shown = []
    from viewer.widgets import tag_apply_dialog as TAD
    real_exec = TAD.TagApplyDialog.exec
    TAD.TagApplyDialog.exec = lambda self_: (shown.append(self_), 0)[1]
    mw.open_tag_apply()
    TAD.TagApplyDialog.exec = real_exec
    dlg = shown[0] if shown else None
    chk(dlg is not None and sorted(os.path.basename(p) for p in dlg._paths) == ["a.pdf", "b.pdf"], "C 썸네일 범위 — 지금 목록에서 보이는 줄만",
        str(dlg and dlg._paths))
    bt.search_edit.setText(""); pump(lambda: False, 0.2)
    if dlg is not None:
        chk(not dlg.g3.isChecked(), "C '#' 메뉴로 열면 새 태그 후보는 접힌 채")
        dlg.show()                                       # 보이는 칸만 그린다(261111-15) — 보여야 그린다
        bk = dlg._blank.cacheKey()
        chk(pump(lambda: all(dlg.lst_files.item(i).icon().cacheKey() != bk for i in range(dlg.lst_files.count())), 15), "C 썸네일 그림(배경)")
        marks = {dlg.lst_tags.item(i).data(Qt.ItemDataRole.UserRole): dlg.lst_tags.item(i).text() for i in range(dlg.lst_tags.count())}
        chk(marks.get("가족") == "#가족  (2)" and marks.get("여행") == "#여행  (1)", "C 태그 줄 — 파일 수(261111-18: ☑◐☐ 대신 거르기 상자)", str(marks))
        def pick(tag, has=True):
            dlg.lst_tags.clearSelection()
            for i in range(dlg.lst_tags.count()):
                it = dlg.lst_tags.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == tag:
                    it.setCheckState(Qt.CheckState.Checked if has else Qt.CheckState.Unchecked)
                    it.setSelected(True)
            dlg.lst_files.selectAll(); pump(lambda: False, 0.05)
        pick("여행", has=False)                          # 여행이 없는 파일(A)만 보인다 → 모두 골라 [적용]
        dlg.btn_apply.click()
        chk("여행" in st.get_manual(A) and "여행" in st.get_manual(B), "C [적용] — 보이는(고른) 파일 모두에 붙인다", f"{st.get(A)} {st.get(B)}")
        pick("보고서"); dlg.btn_clear.click()
        chk("보고서" not in st.get(A) and "보고서" in st.get_rejected(A), "C [해제] — 자동 태그는 거절로 기록", f"{st.get(A)} {st.get_rejected(A)}")
        pick("가족"); dlg.btn_clear.click()
        chk("가족" not in st.get(A) and "가족" not in st.get(B), "C [해제] — 직접 태그는 모두에서 뗀다")
        dlg.undo()
        chk(st.get_manual(A) == ["가족", "여행"] and "가족" in st.get(B), "C 되돌리기 — 직접 태그 해제가 돌아온다", f"{st.get(A)} {st.get(B)}")
        dlg.undo()
        chk("보고서" in st.get_auto(A) and "보고서" not in st.get_rejected(A), "C 되돌리기 두 번 — 자동 태그·거절도 그대로", f"{st.get(A)} {st.get_rejected(A)}")
        dlg.redo()
        chk("보고서" not in st.get(A), "C 다시 실행")
        dlg.ed_new.setText("새태그"); dlg.btn_add.click()
        dlg.lst_files.clearSelection(); dlg.lst_files.item(0).setSelected(True)
        dlg.btn_apply.click()
        p0 = dlg.lst_files.item(0).data(Qt.ItemDataRole.UserRole)
        chk("새태그" in st.get_manual(p0), "C 태그 추가 → 고른 파일에 [적용]", str(st.get(p0)))
        dlg.g3.setChecked(True)
        dlg.lst_cand.item(0).setSelected(True)           # 후보를 고르면 근거 파일(A)만 고른 채로(261111-20)
        dlg.btn_apply.click()
        chk("배수성" in st.get_manual(A) and "배수성" not in (load_candidates().get("cand") or {}), "C 새 태그 후보 [적용] — 근거 파일에 붙고 후보에서 빠진다",
            str(st.get(A)))
        dlg.reject()
    chk(callable(getattr(mw, "_autotag_review_candidates", None)), "C 도구 메뉴 진입점은 남아 있다")
    shown.clear()
    TAD.TagApplyDialog.exec = lambda self_: (shown.append(self_), 0)[1]
    mw._autotag_review_candidates()
    TAD.TagApplyDialog.exec = real_exec
    chk(bool(shown) and shown[0].g3.isChecked(), "C 도구 메뉴 '새 태그 후보 검토' 는 이 창을 후보를 펼친 채로")
    if shown:
        shown[0].reject()

    # D 사본 저장
    st.set(A, ["가족", "여행"]); st.set(B, ["여행"]); st.set(C, [])
    exp = tmp / "exp"; exp.mkdir()
    (exp / "여행").mkdir(); pdf(str(exp / "여행" / "b.pdf"))         # 이미 있는 이름 → 'b (2).pdf'
    done = mw._tag_export_run(st, [A, B, C], ["가족", "여행"], str(exp))
    names = sorted(str(Path(n).relative_to(exp)) for _o, n in done)
    chk(names == sorted([os.path.join("가족", "a.pdf"), os.path.join("여행", "a.pdf"), os.path.join("여행", "b (2).pdf")]),
        "D 태그마다 폴더·여러 태그면 폴더마다·겹치면 '이름 (2)'", str(names))
    pump(lambda: st.get(str(exp / "가족" / "a.pdf")) != [], 5)
    chk(st.get_manual(str(exp / "여행" / "b (2).pdf")) == ["여행"] and st.get_manual(str(exp / "가족" / "a.pdf")) == ["가족", "여행"],
        "D 사본에 태그가 따라간다", str(st.get(str(exp / "가족" / "a.pdf"))))
    from viewer.widgets.tag_export_dialog import folder_name
    chk(folder_name('a/b:c*?') == "a_b_c__" and folder_name("끝.") == "끝", "D 폴더 이름 — 쓸 수 없는 글자는 _")
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
