# -*- coding: utf-8 -*-
"""261008-1: 책갈피창 '이름 변경' 이 꺼지던 것 · 이름 변경 뒤 앱 상태 · 우클릭 메뉴 순서 (마스터 §4.7.13·§4.7.14·§14.7.3).

사용자 보고: "새로 추가한 PDF 여러개를 연속으로 '이름 변경'시 프로그램이 꺼질 때가 있음."
사용자 요청: 책갈피창 우클릭 — 파일 이동 아래 '다른 이름으로 저장'·'저장(PolyPDF용)'·'저장(일반뷰어용)',
그 아래 '파일·책갈피 이름 변경'·'파일·책갈피 삭제', 그 아래 '책갈피 모두 펼치기/접기/정렬'.

A. 대화상자가 떠 있는 동안 목록이 다시 그려져도(행이 지워져도) 예외 없이 새 이름이 반영된다
   — 수정 전에는 지워진 행에 setText → RuntimeError(실제 앱에서는 슬롯 예외 = 강제 종료)
B. 연속 이름 변경 뒤 ↻(다시 읽기)·정렬 변경에도 새 이름이 남고 옛 이름이 돌아오지 않는다(파일·폴더 모드)
C. 색인은 경로만 고친다(다시 색인하지 않는다) · 꾸밈(page_meta)·하이퍼링크가 새 이름을 따라간다
D. 우클릭 메뉴 순서 · 저장 셋이 **누른 파일**에 · 본문이 아닌 파일 저장은 본문 쪽 편집을 가져가지 않는다
E. 전역 예외 안전망 — 슬롯 예외가 앱을 끄지 않고 error.log 에 남는다
"""
import os, sys, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(240, exit=True)
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog, QLineEdit, QMenu
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=10, ms=20):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


def make_pdf(p, tag, pages=4):
    d = fitz.open()
    for i in range(pages):
        d.new_page().insert_text((72, 72), f"{tag} body {i} uniqueword{tag}")
    d.set_toc([[1, f"{tag}-ch1", 1], [1, f"{tag}-ch2", 3]])
    d.save(str(p)); d.close()


errs = []
old_hook = sys.excepthook
sys.excepthook = lambda t, v, tb: errs.append(f"{t.__name__}: {v}")
root = Path(tempfile.mkdtemp(prefix="polypdf_rename_"))
try:
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    warns = []
    QMessageBox.warning = staticmethod(lambda *a, **k: warns.append(a[2] if len(a) > 2 else ""))
    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    bt = mw.bookmark_tree
    tops = lambda: [bt.tree.topLevelItem(i).text(0) for i in range(bt.tree.topLevelItemCount())]

    # ── A·B. 파일 모드: 새로 더한 PDF 여러 개를 연속으로 ──────────────────
    fm = root / "fm"; fm.mkdir()
    files = []
    for nm in ("A", "B", "C", "D"):
        p = fm / f"{nm}.pdf"; make_pdf(p, nm); files.append(p)
    mw.open_pdfs(files[:2]); spin(15)
    mw.add_pdfs([str(f) for f in files[2:]]); spin(5)
    chk(tops() == ["A", "B", "C", "D"], "준비 — 파일 모드 4개(2개 열고 2개 더함)", str(tops()))

    state = {"rebuild": False}

    def fake_exec(dlg):
        ed = dlg.findChild(QLineEdit)
        if ed is not None:
            ed.setText(ed.text() + "_새")
        if state["rebuild"]:
            # 대화상자가 떠 있는 동안 목록이 다시 그려진다(다른 파일 더하기 등) → 누른 행이 지워진다
            bt.load_pdf_files(bt.all_file_paths())
        return QDialog.DialogCode.Accepted
    QDialog.exec = fake_exec

    state["rebuild"] = True
    it = bt.tree.topLevelItem(2)                                   # C
    bt._edit_file_node(it); spin(5)
    chk(not errs, "A 이름 바꾸는 사이 목록이 다시 그려져도 예외가 없다(종전: 지워진 행 RuntimeError → 꺼짐)",
        str(errs[:2]))
    chk((fm / "C_새.pdf").exists() and "C_새" in tops() and "C" not in tops(),
        "A 그 경우에도 새 이름이 목록에 반영된다(경로로 다시 찾는다)", str(tops()))
    state["rebuild"] = False
    errs.clear()

    for _ in range(2):                                             # 연속 두 바퀴
        for i in range(bt.tree.topLevelItemCount()):
            bt._edit_file_node(bt.tree.topLevelItem(i))
    spin(10)
    disk = sorted(p.stem for p in fm.glob("*.pdf"))
    chk(not errs and sorted(tops()) == disk and len(disk) == 4,
        "B 연속 이름 변경 — 디스크와 목록이 같다", f"{tops()} vs {disk} {errs[:2]}")
    bt.refresh(); spin(10)
    chk(sorted(tops()) == disk, "B 파일 모드 ↻ 다시 읽기에도 새 이름 그대로(종전: 옛 경로로 다시 읽어 빠졌다)",
        str(tops()))
    mw.main_view.current_file() and chk(Path(mw.main_view.current_file()).exists(),
                                        "B 본문은 있는 파일을 연다", str(mw.main_view.current_file()))

    # ── B. 폴더 모드: 정렬을 바꿔 다시 그려도 ───────────────────────────
    fo = root / "fo"; fo.mkdir()
    for nm in ("P", "Q", "R"):
        make_pdf(fo / f"{nm}.pdf", nm)
    mw.open_folder(fo); spin(20)
    chk(sorted(tops()) == ["P", "Q", "R"], "준비 — 폴더 모드 3개", str(tops()))
    for i in range(bt.tree.topLevelItemCount()):
        bt._edit_file_node(bt.tree.topLevelItem(i))
    spin(5)
    bt._render_flat(); spin(10)
    chk(sorted(tops()) == ["P_새", "Q_새", "R_새"],
        "B 폴더 모드에서 다시 그려도 새 이름(종전: _pdfs_flat 옛 경로 → 없는 파일 행이 돌아왔다)", str(tops()))
    # 돌아온 옛 행을 또 바꾸는 것이 '파일 없음' 경고로 이어졌다 — 이제는 옛 행이 없다
    warns.clear()
    bt._edit_file_node(bt.tree.topLevelItem(0)); spin(5)
    chk(not warns and not errs, "B 다시 그린 뒤 이어서 이름 변경해도 실패가 없다", str(warns[:1] + errs[:1]))

    # ── C. 색인·꾸밈·하이퍼링크 ────────────────────────────────────────
    from viewer.indexer import PdfIndex
    target = sorted(fo.glob("*.pdf"))[0]
    # 색인이 끝나기를 기다린다
    for _ in range(100):
        if not mw._index_workers:
            break
        spin(1, 50)
    idx = PdfIndex(mw._db_path)
    try:
        had = idx._find_file_row(target, "id")
    finally:
        idx.close()
    chk(had is not None, "준비 — 색인에 있다", str(target))
    st = mw._ensure_page_meta_store()
    st.set_crop(str(target), 0, 10.0, 0.0) if hasattr(st, "set_crop") else None
    st._file(st._key(str(target)), create=True)["hidden"] = [1]
    st.save()
    hs = mw._ensure_hyperlink_store()
    hs._bucket(hs._rel_key(str(target)), 0, create=True).append(
        {"name": "x", "kind": "url", "target": "https://example.com"})
    hs.save()
    started = []
    orig_isf = mw._index_single_file
    mw._index_single_file = lambda p: started.append(str(p))
    node = bt._file_node_for_path(str(target))
    bt._edit_file_node(node); spin(5)
    newp = target.with_name(target.stem + "_새.pdf")
    mw._index_single_file = orig_isf
    idx = PdfIndex(mw._db_path)
    try:
        r_new = idx._find_file_row(newp, "id")
        r_old = idx._find_file_row(target, "id")
    finally:
        idx.close()
    chk(r_new is not None and r_old is None and r_new["id"] == had["id"],
        "C 색인은 **같은 행의 경로만** 고친다", f"{r_new} {r_old}")
    chk(not started, "C 이름 변경은 새 색인 작업을 걸지 않는다(진행 중 색인을 취소하지 않는다)", str(started))
    st2 = mw._ensure_page_meta_store()
    chk(st2.hidden_pages(str(newp)) == {1} and not st2.hidden_pages(str(target)),
        "C 숨김·꾸밈 메타가 새 이름을 따라간다(종전: 옛 이름에 남아 사라진 것처럼 보였다)",
        str(st2.hidden_pages(str(newp))))
    from viewer.page_meta import PageMetaStore
    chk(PageMetaStore(fo).hidden_pages(str(newp)) == {1}, "C 디스크(page_meta.json)에도 새 키로")
    chk(len(mw._ensure_hyperlink_store().links_for(str(newp), 0)) == 1,
        "C 하이퍼링크도 새 이름을 따라간다")

    # ── D. 우클릭 메뉴 ───────────────────────────────────────────────
    seen = {}

    def fake_menu_exec(menu, *a, **k):
        seen["texts"] = [x.text() for x in menu.actions()]
        want = seen.get("pick")
        for x in menu.actions():
            if want and x.text() == want:
                return x
        return None
    QMenu.exec = fake_menu_exec
    bt.btn_edit.setChecked(True); spin(3)
    f0 = bt.tree.topLevelItem(0)
    pos = bt.tree.visualItemRect(f0).center()
    bt._on_tree_context_menu(pos)
    t = [x for x in seen.get("texts", []) if x]
    want_order = ["파일 폴더 열기", "파일 복사 (1개)", "파일 이동 (1개)", "다른 이름으로 저장...",
                  "저장(PolyPDF용)", "저장(일반뷰어용)...", "파일·책갈피 이름 변경", "파일·책갈피 삭제",
                  "책갈피 모두 펼치기", "책갈피 모두 접기"]
    pos_of = [t.index(w) if w in t else -1 for w in want_order]
    chk(-1 not in pos_of and pos_of == sorted(pos_of), "D 메뉴 순서(사용자 지시)", str(t))
    raw = seen.get("texts", [])
    try:
        i_fl, i_rn, i_ex = raw.index("저장(일반뷰어용)..."), raw.index("파일·책갈피 이름 변경"), raw.index("책갈피 모두 펼치기")
        chk(raw[i_fl + 1] == "" and raw[i_rn + 2] == "" and i_ex == i_rn + 3,
            "D 저장 그룹 / 이름 변경·삭제 그룹 / 펼치기 그룹이 구분선으로 나뉜다", str(raw))
    except ValueError:
        chk(False, "D 그룹 구분", str(raw))
    chk("이름 변경" not in t and "삭제" not in t and "일반뷰어용으로 저장 (꾸밈·사진 굽기)..." not in t,
        "D 옛 이름·옛 자리 항목이 남지 않는다", str(t))

    # 저장 셋은 **누른 파일**에
    f1 = bt.tree.topLevelItem(1)
    f1_path = f1.data(0, bt.DATA_FILE)
    got = {}
    bt.saveAsFileRequested.connect(lambda p: got.setdefault("as", p))
    bt.flattenFileRequested.disconnect()
    bt.flattenFileRequested.connect(lambda p: got.setdefault("flat", p))
    called = []
    real_op_save = bt._op_save
    bt._op_save = lambda file_path=None: called.append(file_path)
    for pick in ("다른 이름으로 저장...", "저장(PolyPDF용)", "저장(일반뷰어용)..."):
        seen["pick"] = pick
        bt._on_tree_context_menu(bt.tree.visualItemRect(f1).center())
    bt._op_save = real_op_save
    seen["pick"] = None
    # '다른 이름으로' 도 같은 저장 함수에 깃발만 세워 들어간다(§4.7.13) — 그래서 두 번
    chk(got.get("as") == f1_path and got.get("flat") == f1_path and called == [f1_path, f1_path],
        "D 저장 셋이 모두 **누른 그 파일**에 작용한다", f"{got} {called}")

    # 본문이 아닌 파일을 '저장(PolyPDF용)' 하면 본문의 쪽 편집을 가져가지 않는다
    from viewer.history import HistoryItem
    mw._load_main(HistoryItem(str(bt.all_file_paths()[0]), 0, "", "bookmark")); spin(5)
    main_file = mw.main_view.current_file()
    chk(bool(main_file), "준비 — 본문에 파일이 열려 있다")
    other = next(x for x in bt.all_file_paths() if str(x) != str(main_file))
    pe = []
    bt._page_edit_dirty = lambda: True
    real_pes = bt._page_edit_save
    bt._page_edit_save = lambda src, raw: pe.append(src)
    asked = []
    QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""),
                                                         QMessageBox.StandardButton.No)[1])
    onode = bt._file_node_for_path(str(other))
    chk(not onode.data(0, bt.DATA_TOC_LOADED), "준비 — 저장할 다른 파일은 책갈피를 아직 펼치지 않았다")
    bt._op_save(file_path=other)
    chk(not pe, "D ★ 다른 파일 저장이 본문 파일의 쪽 편집을 그 파일에 넣지 않는다", str(pe))
    chk(not any("책갈피가 제거" in m for m in asked),
        "D ★ 펼치지 않은 파일 저장이 '모든 책갈피 제거' 를 묻지 않는다(종전: 예 → 책갈피가 지워졌다)", str(asked))
    with fitz.open(str(other)) as _d:
        chk(len(_d.get_toc()) == 2, "D 그 파일의 책갈피는 그대로", str(_d.get_toc()))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    bt._op_save(file_path=str(main_file))
    chk(pe == [str(main_file)], "D 본문 파일을 저장하면 쪽 편집 저장으로 간다(종전 그대로)", str(pe))
    bt._page_edit_save = real_pes
    bt._page_edit_dirty = mw._page_edits_dirty
    bt._dirty = False
    bt.btn_edit.setChecked(False); spin(3)

    # 파일 메뉴 이름도 같다(사용자 결정)
    labels = [a.text() for a in mw.menuBar().actions()[0].menu().actions()]
    chk(all(x in labels for x in ("다른 이름으로 저장...", "저장(PolyPDF용)", "저장(일반뷰어용)...")),
        "D 파일 메뉴도 같은 이름", str(labels))

    # ── E. 전역 예외 안전망 ─────────────────────────────────────────
    sys.excepthook = old_hook
    import main as appmain
    appmain._install_excepthook()
    QTimer.singleShot(0, lambda: (_ for _ in ()).throw(RuntimeError("안전망 확인")))
    spin(5)
    log = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "error.log"
    chk(log.exists() and "안전망 확인" in log.read_text(encoding="utf-8"),
        "E 슬롯 예외가 앱을 끄지 않고 error.log 에 남는다", str(log))
    chk("안전망 확인" in mw.status.currentMessage(), "E 상태줄에 한 줄 알린다", mw.status.currentMessage())
    try:
        log.unlink()
    except Exception:
        pass
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    sys.excepthook = old_hook
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
