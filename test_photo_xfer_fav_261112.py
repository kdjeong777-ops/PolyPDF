# -*- coding: utf-8 -*-
"""폴더로 복사·이동 맨 위 — 즐겨찾기 폴더 + 최근 폴더, 두 모드 한 함수 (261112-18 사용자 지시·결정,
책갈피창·저장 SOT '폴더로 복사·이동 의 맨 위' · 사진 보기 SOT §4.41).

실제 MainWindow(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 메뉴는 `QMenu.exec` 를 가로채 항목을 본다(일은 실제 처리기).
A. PDF 모드 책갈피창(편집 모드) 파일 줄 우클릭 '폴더로 복사 ▸' — 맨 위 ⭐ PDF 즐겨찾기 폴더 → 최근 폴더(즐겨찾기와 같은 것은 한 번) → 구분선 → 종전 '새 폴더 만들기'
B. ⭐ 즐겨찾기 폴더로 복사 → 그 폴더에 사본·태그가 사본에 따라감, 최근 폴더(PDF 모드 `transfer_dirs`) 맨 앞에 — 사진 모드 목록은 그대로(모드마다 따로)
C. 최근 폴더로 이동 → 옮겨지고 태그가 새 경로로(한 길 `_after_move` → `filesRelocated`)
D. 없어진 즐겨찾기 폴더 → 알림만, 옮기지 않음
E. 사진 모드 '폴더로 복사 ▸' — 맨 위 ⭐ 사진 즐겨찾기 폴더, PDF 최근 폴더는 보이지 않는다(모드마다 따로)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_xfer_fav_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "폴더로 복사 즐겨찾기", echo=False)   # 마스터 §14.7.2 의 6
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


_orig_exec = QMenu.exec
seen = {"menu": None}


def fake_exec(self, *a, **k):
    seen["menu"] = self
    return None


def sub_of(menu, title):
    for x in (menu.actions() if menu else []):
        if x.menu() is not None and x.text().split("\t")[0].startswith(title):
            return x.menu()
    return None


def labels(m):
    return [("─" if x.isSeparator() else x.text()) for x in (m.actions() if m else [])]


tmp = Path(tempfile.mkdtemp(prefix="polypdf_xfer_fav_"))
_oi, _oq, _ow = QMessageBox.information, QMessageBox.question, QMessageBox.warning
warns = []
try:
    root, fav, rec, pix, pfav = tmp / "문서", tmp / "즐겨 폴더", tmp / "최근 폴더", tmp / "사진", tmp / "사진 즐겨"
    for d in (root, fav, rec, pix, pfav):
        d.mkdir()
    import fitz
    for name in ("가.pdf", "나.pdf"):
        doc = fitz.open(); doc.new_page(); doc.save(str(root / name)); doc.close()
    from PIL import Image
    Image.new("RGB", (200, 120), (30, 120, 200)).save(pix / "하늘.jpg", "JPEG")

    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.warning = staticmethod(lambda *a, **k: (warns.append(a[2] if len(a) > 2 else ""), QMessageBox.StandardButton.Ok)[1])

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._favorites = [{"name": "즐겨 폴더", "kind": "folder", "folder": str(fav)},
                     {"name": "없는 폴더", "kind": "folder", "folder": str(tmp / "없음")}]
    mw._prefs["transfer_dirs"] = [str(rec), str(fav)]
    mw.open_folder(root)
    bt = mw.bookmark_tree
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 2)
    bt.set_edit_mode(True); pump(timeout=0.3)
    a_pdf = str(root / "가.pdf")
    tags = bt._tags
    tags.set(a_pdf, ["#보고서"])

    def node(p):
        return bt._file_node_for_path(str(p))

    QMenu.exec = fake_exec

    # A
    bt.tree.setCurrentItem(node(a_pdf))
    bt._on_tree_context_menu(bt.tree.visualItemRect(node(a_pdf)).center())
    sub = sub_of(seen["menu"], "폴더로 복사")
    lab = labels(sub)
    chk(lab[:4] == ["⭐ 즐겨 폴더", "⭐ 없는 폴더", "최근 폴더", "─"] and "새 폴더 만들기" in lab[4:6],
        "A PDF 폴더로 복사 ▸ — ⭐ 즐겨찾기 → 최근(중복 한 번) → ─ → 새 폴더 만들기", str(lab[:8]))

    # B
    act = next((x for x in (sub.actions() if sub else []) if x.text() == "⭐ 즐겨 폴더"), None)
    if act is not None:
        act.trigger()
        pump(lambda: (fav / "가.pdf").exists(), timeout=10)
    chk((fav / "가.pdf").exists() and (root / "가.pdf").exists(), "B ⭐ 즐겨찾기 폴더로 복사 — 사본, 원본 그대로")
    pump(timeout=0.5)
    chk("보고서" in tags.get(str(fav / "가.pdf")), "B 태그가 사본에 따라감", str(tags.get(str(fav / "가.pdf"))))
    chk(mw._prefs.get("transfer_dirs", [])[:1] == [str(fav)] and not mw._prefs["picture"].get("transfer_dirs"),
        "B 최근 폴더 맨 앞(PDF 모드 목록) — 사진 목록은 그대로", "%s %s" % (mw._prefs.get("transfer_dirs"), mw._prefs["picture"].get("transfer_dirs")))

    # C
    bt.tree.setCurrentItem(node(a_pdf))
    bt._on_tree_context_menu(bt.tree.visualItemRect(node(a_pdf)).center())
    sub = sub_of(seen["menu"], "폴더로 이동")
    act = next((x for x in (sub.actions() if sub else []) if x.text() == "최근 폴더"), None)
    if act is not None:
        act.trigger()
        pump(lambda: (rec / "가.pdf").exists(), timeout=10)
    chk((rec / "가.pdf").exists() and not (root / "가.pdf").exists(), "C 최근 폴더로 이동")
    pump(timeout=0.5)
    chk("보고서" in tags.get(str(rec / "가.pdf")) and not tags.get(a_pdf), "C 태그가 새 경로로(한 길)",
        "%s %s" % (tags.get(str(rec / "가.pdf")), tags.get(a_pdf)))

    # D
    b_pdf = str(root / "나.pdf")
    pump(lambda: node(b_pdf) is not None, timeout=5)
    bt.tree.setCurrentItem(node(b_pdf))
    bt._on_tree_context_menu(bt.tree.visualItemRect(node(b_pdf)).center())
    sub = sub_of(seen["menu"], "폴더로 복사")
    act = next((x for x in (sub.actions() if sub else []) if x.text() == "⭐ 없는 폴더"), None)
    warns.clear()
    if act is not None:
        act.trigger()
        pump(lambda: bool(warns), timeout=3)
    chk(bool(warns) and not (tmp / "없음").exists(), "D 없어진 즐겨찾기 폴더 — 알림만", str(warns))
    bt.set_edit_mode(False)

    # E
    mw._set_photo_mode(True)
    mw._favorites = [{"name": "사진 즐겨", "kind": "folder", "folder": str(pfav)}]
    mw.open_folder(pix)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 1)
    from viewer.widgets.ctx_menu import CtxMenu
    m = CtxMenu(mw)
    mw._photo_xfer_menu(m, [str(pix / "하늘.jpg")])
    lab = labels(sub_of(m, "폴더로 복사"))
    chk(lab[:2] == ["⭐ 사진 즐겨", "─"] and "최근 폴더" not in lab and "즐겨 폴더" not in " ".join(lab),
        "E 사진 모드 — ⭐ 사진 즐겨찾기만, PDF 최근 폴더는 안 보임(모드마다 따로)", str(lab))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    QMessageBox.information, QMessageBox.question, QMessageBox.warning = _oi, _oq, _ow
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
