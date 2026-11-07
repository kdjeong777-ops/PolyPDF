# -*- coding: utf-8 -*-
"""261107-29: PDF 처음 원본은 `_원본` 에 · 원본으로 되돌리기 (마스터 §4.7.5, 사진 보기 SOT §4.43 '원본 백업 — 사진·PDF 공용').

사용자 지시 'pdf가 원본 파일에 저장될 때, 기존 파일은 사진모드와 같이 _원본 폴더에 저장되도록', 결정 D1 '처음 원본 하나만'·D2 '사진과 같은 규칙 + 되돌리기'.
실제 MainWindow(오프스크린, 시험 프로필 — 마스터 §14.7.2 의 3), 파일은 모두 임시 폴더에 만든 사본. 저장은 실제 길(책갈피창 [저장] → `_finalize_save`).
A. 첫 저장 — 손대지 않은 원본이 `_원본/a.pdf` 에(바이트 그대로), a.pdf 는 바뀜
B. 두 번째 저장 — `_원본` 에 더하지 않는다(처음 원본 한 벌)
C. 숨김 — 책갈피창 목록·`iter_pdfs`(색인이 쓰는 함수)에 `_원본` 이 없다
D. 메뉴 — 책갈피창 a.pdf 줄·본문 '파일 ▸' 에 '원본으로 되돌리기', 백업 없는 b.pdf 줄에는 없다
E. 저장 안 한 편집이 있으면 되돌리지 않는다(알림, 아무것도 안 바뀜)
F. 되돌리기 — a.pdf = 처음 원본, 바꾼 파일은 휴지통(가짜), 백업·짝 기록 지움, 본문은 처음 원본(쪽 수), 꾸밈 기록 지움, 메뉴에서 사라짐
G. 실패 되돌림 — 휴지통이 실패하면 아무것도 바뀌지 않는다(지금 파일·백업 그대로)
H. 잠금 — 원본을 바꾸는 다른 작업이 돌면 저장하지 않는다(원본 그대로, 임시 산출물 지움)
I. 백업을 못 만들면 저장하지 않는다(원본 그대로, 임시 산출물 지움)
J. 환경설정 고정 폴더 — `<고정 폴더>/<드라이브>/<원래 경로>/c.pdf`, 목록에서도 숨김
(원본 옆 `.textfix.bak.pdf` 가 없어진 것은 test_text_apply_multi C·test_ocr_batch_261014 D 가 본다)
수정 전 코드로 실패한다(`_원본` 이 생기지 않고 메뉴 항목이 없다).
"""
import os, sys, tempfile, shutil, time, hashlib, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_pdf_backup_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "PDF 원본 백업", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def digest(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


def pages(p):
    d = fitz.open(str(p)); n = d.page_count; d.close(); return n


seen = {"labels": []}
pick = {"p": None}
_orig_exec = QMenu.exec


def fake_exec(self, *a, **k):
    from viewer.widgets.ctx_menu import walk, find_action
    seen["labels"] = [x.text().split("\t")[0] for _d, x in walk(self)]
    p, pick["p"] = pick["p"], None
    return find_action(self, p, exact=True) if p else None


root = Path(tempfile.mkdtemp(prefix="pdf_backup_"))
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", folder / "b.pdf"
    for p_, n in ((a, 3), (b, 2)):
        d = fitz.open()
        for i in range(n):
            d.new_page(width=595, height=842).insert_text((72, 400), "%s P%d" % (p_.stem.upper(), i + 1))
        d.set_toc([[1, "first", 1]])
        d.save(str(p_)); d.close()
    a0 = digest(a)
    from viewer.app import MainWindow
    from viewer import photo_backup
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    told = []
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: told.append(("info", a_[2] if len(a_) > 2 else "")))
    QMessageBox.warning = staticmethod(lambda *a_, **k: told.append(("warn", a_[2] if len(a_) > 2 else "")))
    bt, mv = mw.bookmark_tree, mw.main_view
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)
    bk_dir = folder / "_원본"

    # A — 첫 저장: 쪽 하나 지우고 [저장]
    pt = mw.page_thumbs
    pt.list.clearSelection(); pt.list.item(2).setSelected(True); pt._delete_selected(); spin(0.4)
    bt._op_save(str(a)); spin(2.0)
    chk((bk_dir / "a.pdf").exists() and digest(bk_dir / "a.pdf") == a0, "A 첫 저장 — 손대지 않은 원본이 `_원본/a.pdf` 에(바이트 그대로)",
        str(sorted(x.name for x in folder.rglob("*"))))
    chk(a.exists() and digest(a) != a0 and pages(a) == 2, "A a.pdf 는 저장한 내용(2쪽)", str(pages(a) if a.exists() else None))
    idx = json.loads((bk_dir / photo_backup.INDEX_NAME).read_text(encoding="utf-8")) if (bk_dir / photo_backup.INDEX_NAME).exists() else {}
    chk(idx.get("a.pdf", {}).get("cur") == "a.pdf", "A 짝 기록(원래 이름 = 지금 이름)", str(idx))
    a1 = digest(a)

    # B — 두 번째 저장: 더하지 않는다
    mw._rotate_pages([0], 90); spin(0.4)
    bt._op_save(str(a)); spin(2.0)
    files_bk = sorted(x.name for x in bk_dir.iterdir() if not x.name.startswith("."))
    chk(files_bk == ["a.pdf"] and digest(bk_dir / "a.pdf") == a0 and digest(a) != a1,
        "B 두 번째 저장은 `_원본` 에 더하지 않는다(처음 원본 한 벌)", str(files_bk))
    a2 = digest(a)

    # C — 숨김
    from viewer.pathutil import iter_pdfs
    listed = {Path(str(n.data(0, bt.DATA_FILE))).resolve() for n in bt._iter_file_nodes()}
    chk((bk_dir / "a.pdf").resolve() not in listed and a.resolve() in listed, "C 책갈피창 목록에 `_원본` 이 없다", str(listed))
    chk(all("_원본" not in str(x) for x in iter_pdfs(folder)), "C `iter_pdfs`(목록·색인 공용)가 `_원본` 으로 내려가지 않는다")

    # D — 메뉴
    QMenu.exec = fake_exec

    def node_of(name):
        return next(n for n in bt._iter_file_nodes() if Path(str(n.data(0, bt.DATA_FILE))).name == name)

    def tree_menu(name, path=None):
        pick["p"] = path
        bt._on_tree_context_menu(bt.tree.visualItemRect(node_of(name)).center()); spin(0.3)
        return list(seen["labels"])
    chk("원본으로 되돌리기" in tree_menu("a.pdf"), "D 책갈피창 a.pdf 줄에 '원본으로 되돌리기'", str(seen["labels"]))
    chk("원본으로 되돌리기" not in tree_menu("b.pdf"), "D 백업 없는 b.pdf 줄에는 없다")
    seen["labels"] = []
    mw._on_viewer_context_menu(mv.mapToGlobal(mv.rect().center())); spin(0.3)
    chk("원본으로 되돌리기" in seen["labels"], "D 본문 '파일 ▸' 에도", str(seen["labels"]))

    # 되돌리기 확인 창은 [되돌리기] 를 누른 것으로
    _mb_exec = QMessageBox.exec
    QMessageBox.exec = lambda self, *x: 0
    QMessageBox.clickedButton = lambda self: next((bb for bb in self.buttons() if bb.text() == "되돌리기"), None)
    import send2trash as _s2t
    trash = root / "trash"; trash.mkdir()
    trash_fail = {"on": False}

    def fake_trash(p):
        if trash_fail["on"]:
            raise OSError("trash failed (test)")
        shutil.move(str(p), str(trash / (Path(p).name + ".%d" % len(list(trash.iterdir())))))
    _s2t.send2trash = fake_trash

    # E — 저장 안 한 편집이 있으면 하지 않는다
    mw._rotate_pages([0], 90); spin(0.4)
    told.clear()
    tree_menu("a.pdf", "원본으로 되돌리기"); spin(0.5)
    chk(digest(a) == a2 and (bk_dir / "a.pdf").exists() and told and "저장하지 않은" in told[-1][1],
        "E 저장 안 한 편집이 있으면 되돌리지 않고 알린다", str(told))
    pt.revert_page_edits() if hasattr(pt, "revert_page_edits") else None
    bt._op_save(str(a)); spin(2.0)                    # 편집을 저장해 깨끗하게(백업은 그대로 처음 원본)
    chk(not mw._page_edits_dirty() and digest(bk_dir / "a.pdf") == a0, "준비 — 편집 없음, 백업은 처음 원본")

    # G — 실패 되돌림(휴지통 실패): 아무것도 바뀌지 않는다
    a3 = digest(a)
    trash_fail["on"] = True
    told.clear()
    tree_menu("a.pdf", "원본으로 되돌리기"); spin(1.5)
    chk(digest(a) == a3 and (bk_dir / "a.pdf").exists() and digest(bk_dir / "a.pdf") == a0
        and not list(folder.glob("~*")) and any(k == "warn" for k, _m in told),
        "G 휴지통이 실패하면 지금 파일·백업 그대로, 임시 이름도 남지 않는다", str((told, sorted(x.name for x in folder.iterdir()))))
    trash_fail["on"] = False

    # F — 되돌리기
    st = mw._ensure_page_meta_store()
    st.set_images(str(a), 0, [{"data": "", "rect": [0.1, 0.1, 0.2, 0.2], "rot": 0.0, "alpha": 100, "shape": "rect"}]); st.save()
    tree_menu("a.pdf", "원본으로 되돌리기"); spin(2.0)
    idx = json.loads((bk_dir / photo_backup.INDEX_NAME).read_text(encoding="utf-8")) if (bk_dir / photo_backup.INDEX_NAME).exists() else {}
    chk(a.exists() and digest(a) == a0, "F a.pdf 가 처음 원본으로", str(digest(a) == a0))
    chk(not (bk_dir / "a.pdf").exists() and "a.pdf" not in idx, "F 백업·짝 기록을 지운다", str(idx))
    chk(len(list(trash.iterdir())) == 1, "F 바꾼 파일은 휴지통으로(영구 삭제 아님)", str(list(trash.iterdir())))
    chk(mv.current_file() and Path(mv.current_file()).name == "a.pdf" and mv._doc is not None and mv._doc.page_count == 3,
        "F 본문은 처음 원본(3쪽)으로 다시 연다", str(getattr(mv._doc, "page_count", None)))
    chk(not mw._ensure_page_meta_store().get_images(str(a), 0), "F 쪽 구조 기록(꾸밈)을 지운다")
    chk("원본으로 되돌리기" not in tree_menu("a.pdf"), "F 되돌린 뒤 메뉴에서 사라진다")
    QMenu.exec = _orig_exec

    # H — 잠금: 다른 원본 작업이 돌면 저장하지 않는다
    b0 = digest(b)
    prod = folder / "b_prod_tmp.pdf"; shutil.copy2(str(a), str(prod))
    mw._photo_orig_busy = True
    try:
        mw._finalize_save(str(b), str(prod), shift=False); ok_h = False
    except OSError:
        ok_h = True
    mw._photo_orig_busy = False
    chk(ok_h and digest(b) == b0 and not prod.exists() and not (bk_dir / "b.pdf").exists(),
        "H 원본을 바꾸는 작업이 돌면 저장하지 않는다(원본 그대로, 임시 산출물 지움)")

    # I — 백업을 못 만들면 저장하지 않는다(백업 자리를 파일로 막는다)
    blocker = root / "blocker"; blocker.write_bytes(b"x")
    mw._prefs.setdefault("picture", {})["warp_backup_dir"] = str(blocker)
    prod = folder / "b_prod_tmp.pdf"; shutil.copy2(str(a), str(prod))
    try:
        mw._finalize_save(str(b), str(prod), shift=False); ok_i = False
    except OSError as e:
        ok_i = "백업" in str(e)
    chk(ok_i and digest(b) == b0 and not prod.exists(), "I 백업을 못 만들면 저장하지 않는다(원본 그대로, 임시 산출물 지움)")

    # J — 환경설정 고정 폴더
    custom = root / "custom_bk"
    mw._prefs["picture"]["warp_backup_dir"] = str(custom)
    c = folder / "c.pdf"; shutil.copy2(str(b), str(c)); c0 = digest(c)
    prod = folder / "c_prod_tmp.pdf"; shutil.copy2(str(a), str(prod))
    out = mw._finalize_save(str(c), str(prod), shift=False); spin(0.5)
    photo_backup.set_custom_dir(str(custom))
    want = photo_backup.backup_dir_for(c) / "c.pdf"
    chk(str(out) == str(c) and want.exists() and digest(want) == c0 and str(want).startswith(str(custom)),
        "J 고정 폴더 아래 원래 구조로(`<고정>/<드라이브>/<경로>/c.pdf`)", str(want))
    chk(photo_backup.is_backup_path(want), "J 고정 폴더 안은 백업 자리로 숨김(`is_backup_path`)")
    mw._prefs["picture"]["warp_backup_dir"] = ""
    photo_backup.set_custom_dir("")
    QMessageBox.exec = _mb_exec
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    try:
        from viewer import photo_backup as _pb
        _pb.set_custom_dir("")
    except Exception:
        pass
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m_ in fails:
    print(" -", m_)
sys.stdout.flush()
os._exit(1 if fails else 0)
