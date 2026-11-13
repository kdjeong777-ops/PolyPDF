# -*- coding: utf-8 -*-
"""잘못 붙은 문서 종류 고치기 — 판정 개선·한 번에 바꾸기·사람이 고친 것 배우기 (태그 SOT §5.3·§5.3.2, 261114-2 사용자 지시·결정).

사용자 보고: '보조배터리(AC220)-MUZ.pdf'(제품 설명서, 4쪽 가로 스캔 — 종횡비 2.15·글자층 없음)가 #발표자료, 사람이 고치기 어려움.
사용자 결정: 다단으로 옆으로 긴 쪽은 발표자료 아님·폴더 이름도 본다·설명서 낱말 늘림, 고친 것은 비슷한 문서에 반영, 고치는 길은 추천안.
실제 PDF·MainWindow·BookmarkTree 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 검사 작성 SOT §14.7.2).
A. 판정 — 종횡비 2.15 가로 스캔은 발표자료 아님(1.78 은 발표자료), '메뉴얼'·본문 '사용설명서' → 설명서, 폴더 이름 → 그 종류
B. `TagStore.set_format` — 자동 종류는 거절·직접 태그로, 종류 없음, 거절했던 종류도 다시 고를 수 있다
C. '해시태그 수정' 창 [문서 종류 ▾] — 고른 PDF 를 한 번에, 되돌리기, 자동으로만 붙은 태그 줄은 '·#'
D. 책갈피창 PDF 우클릭 '문서 종류 ▸' — 고른 PDF 모두
E. 배우기 — 같은 폴더 2개 이상 직접 태그 → 그 폴더 다른 PDF 에 그 종류, 직접 종류가 있는 파일엔 자동 종류 없음, 비슷한 본문
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMenu
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_format_fix_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "문서 종류 고치기", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def pump(sec=0.2):
    t = time.monotonic()
    while time.monotonic() - t < sec:
        app.processEvents(); time.sleep(0.01)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_fmtfix_"))


def mk(rel, pages=1, size=(595, 842), img=False, text=""):
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    d = fitz.open()
    for _ in range(pages):
        pg = d.new_page(width=size[0], height=size[1])
        if img:
            pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 90)); pm.set_rect(pm.irect, (230, 230, 230))
            pg.insert_image(pg.rect, pixmap=pm)
        if text:
            pg.insert_text((30, 40), text, fontsize=8)
    d.save(str(p)); d.close()
    return str(p)


try:
    from viewer import auto_tag as AT

    def fmt(path, texts=None, learned=None):
        return AT.classify_format(AT.extract_features(path, page_texts=texts), {}, learned)

    # A
    scan_wide = mk("x/보조배터리(AC220)-MUZ.pdf", pages=4, size=(842, 392), img=True)
    chk(fmt(scan_wide, []) != "발표자료", "A 종횡비 2.15 가로 스캔(다단) — 발표자료 아님", str(fmt(scan_wide, [])))
    slides = mk("x/회의.pdf", pages=12, size=(960, 540), text="slide")
    chk(fmt(slides, ["slide"] * 12) == "발표자료", "A 16:9 글자 적은 슬라이드는 그대로 발표자료")
    chk(fmt(mk("x/CR1000 메뉴얼.pdf"), ["x"]) == "설명서", "A 이름 '메뉴얼'(맞춤법 변형) → 설명서")
    chk(fmt(mk("x/보조배터리.pdf"), ["이 사용설명서를 잘 읽고 안전하게 사용하십시오. 제품 사양 정격 입력"]) == "설명서", "A 본문 '사용설명서'·'제품 사양' → 설명서")
    chk(fmt(mk("11.1 설명서.회사/보조배터리.pdf", pages=4, size=(842, 392), img=True), []) == "설명서", "A 폴더 이름 '11.1 설명서.회사' → 설명서")
    chk(fmt(mk("06.1 국외보고서/a.pdf"), ["x"]) == "보고서", "A 폴더 이름 '국외보고서' → 보고서")
    chk(fmt(mk("x/a.pdf"), ["x"], {"dir": "견적서"}) == "견적서", "A 사람이 고친 폴더 종류(①-2)")
    chk(fmt(mk("x/b.pdf"), ["x"], {"sims": {"논문": 0.41, "설명서": 0.2}}) == "논문", "A 고친 문서와 비슷한 본문(②-2, 0.30 이상)")
    chk(fmt(mk("x/c.pdf"), ["x"], {"sims": {"논문": 0.2}}) is None, "A 유사도가 낮으면 쓰지 않는다")

    # B
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1100, 700); mw.show(); pump(0.3)
    st = mw.bookmark_tree._tags
    P = [mk("docs/%s.pdf" % n) for n in ("a", "b", "c")]
    st.set_auto(P[0], ["2023-06-22", "발표자료", "스캔문서"])
    st.set(P[0], ["가족"])
    ch = st.set_format([P[0]], "설명서")
    chk(ch == [P[0]] and st.get_manual(P[0]) == ["가족", "설명서"] and "발표자료" in st.get_rejected(P[0])
        and st.get_auto(P[0]) == ["2023-06-22", "스캔문서"], "B 바꾸기 — 자동 종류는 거절, 고른 종류는 직접 태그, 다른 태그는 그대로", str(st.record(P[0])))
    st.set_format([P[0]], "발표자료")
    chk(st.get_manual(P[0]) == ["가족", "발표자료"] and "발표자료" not in st.get_rejected(P[0]), "B 거절했던 종류도 다시 고를 수 있다", str(st.record(P[0])))
    st.set_format([P[0]], None)
    chk(st.get_manual(P[0]) == ["가족"], "B 종류 없음 — 직접 종류도 뺀다", str(st.record(P[0])))

    # C
    from viewer.widgets.tag_apply_dialog import TagApplyDialog
    st.set_auto(P[1], ["발표자료", "스캔문서"]); st.set(P[2], ["발표자료"])
    dlg = TagApplyDialog(st, [P[1], P[2]], [P[1]], keep=mw.__dict__.setdefault("_thread_keep", []))
    dlg.show(); pump()
    rows = {dlg.lst_tags.item(i).data(Qt.ItemDataRole.UserRole): dlg.lst_tags.item(i).text() for i in range(dlg.lst_tags.count())}
    chk(rows.get("스캔문서", "").startswith("·#") and rows.get("발표자료", "").startswith("#"), "C 자동으로만 붙은 태그 줄은 '·#', 직접 태그가 있으면 '#'", str(rows))
    m = dlg.btn_format.menu()
    acts = [a for a in m.actions() if a.text() == "설명서"] if m else []
    chk(bool(acts) and dlg.btn_format.parent() is dlg and dlg.btn_format.y() < dlg.lst_tags.mapTo(dlg, dlg.lst_tags.rect().topLeft()).y(),
        "C 위 줄 [문서 종류 ▾] 에 종류가 있다")
    if acts:
        acts[0].trigger(); pump()
    chk(st.get_manual(P[1]) == ["설명서"] and "발표자료" in st.get_rejected(P[1]) and st.get_manual(P[2]) == ["발표자료"],
        "C 고른 파일만 바뀐다", f"{st.record(P[1])} {st.record(P[2])}")
    dlg.undo(); pump()
    chk(st.get_auto(P[1]) == ["발표자료", "스캔문서"] and st.get_manual(P[1]) == [], "C 되돌리기 한 걸음", str(st.record(P[1])))
    dlg.reject()

    # D
    bt = mw.bookmark_tree
    menu_built = []
    from viewer.widgets.ctx_menu import CtxMenu
    cm = CtxMenu(bt)
    bt.selected_file_paths = lambda: [P[1], P[2]]
    bt._mi_pdf_tools(cm, P[1], [P[1], P[2]])
    subs = [a.menu() for a in cm.actions() if a.menu() is not None and a.text() == "문서 종류"]
    chk(bool(subs), "D 우클릭 '문서 종류 ▸'", str([a.text() for a in cm.actions()][-4:]))
    if subs:
        a2 = [a for a in subs[0].actions() if a.text() == "논문"]
        if a2:
            a2[0].trigger(); pump()
    chk(st.get_manual(P[1]) == ["논문"] and st.get_manual(P[2]) == ["논문"], "D 고른 PDF 모두 바뀐다", f"{st.get(P[1])} {st.get(P[2])}")

    # E 배우기 — 실제 워커
    from viewer.workers import AutoTagWorker
    F = [mk("수집/%d.pdf" % i, text="x") for i in range(4)]
    res = {}
    w = AutoTagWorker(os.path.join(str(tmp), "none.db"), F, {"설명서": [F[0], F[1]]}, known_tags=["설명서"], rules={},
                      today_year=2026, store_keys=set(), fp_missing_keys=set())
    w.finished.connect(lambda r, s: res.update(r={x["path"]: [t for t, _ in x["auto"]] for x in r}))
    w.run()
    rr = res.get("r", {})
    chk(os.path.normcase(os.path.dirname(F[0])) in w.learned_dirs, "E 같은 폴더 2개 직접 태그 → 폴더 규칙", str(w.learned_dirs))
    chk("설명서" in rr.get(F[2], []) and "설명서" in rr.get(F[3], []), "E 그 폴더의 다른 PDF 에 설명서", str(rr))
    chk(not any(t in AT.FORMAT_VOCAB for t in rr.get(F[0], [])), "E 직접 종류가 있는 파일에는 자동 종류를 더 붙이지 않는다", str(rr.get(F[0])))
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
