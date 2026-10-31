# -*- coding: utf-8 -*-
"""261031-14(사용자 지시·결정, 마스터 §4.7.13): '다른 이름으로 저장' 은 저장 창에서 폴더·이름을 고른다.

A. 메뉴 '다른 이름으로 저장' → 저장 창(기본 이름 <원본>_edited.pdf) → **다른 폴더·다른 이름**(확장자 없이)을 고르면
   그 자리에 `.pdf` 를 붙여 저장, 원본은 그대로
B. 저장 창에서 취소 → 새 파일 없음·원본 그대로·남은 임시 파일 없음·오류 알림 없음
Shift+저장·서명 가드·다른 창 '새 이름' 도 같은 `_edit_save_dst` 를 지난다(test_merge_preview_peer 가 다른 창 '새 이름' 길).
수정 전 코드로 A 가 실패한다(종전에는 묻지 않고 <원본>_edited.pdf 로 저장).
"""
import os, sys, tempfile, shutil, time, hashlib, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(240, exit=True)
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_saveas_pick_%d" % os.getpid())   # 마스터 §14.7.2 의 3
import modal_guard
guard = modal_guard.install(label=lambda: "다른 이름으로 저장", watch_ms=0, echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
asked, answer = [], {"path": ""}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), (answer["path"], "PDF (*.pdf)"))[1])
warned = []

root = Path(tempfile.mkdtemp(prefix="saveaspick_"))
try:
    folder = root / "f"; folder.mkdir()
    other = root / "다른 폴더"; other.mkdir()
    a = folder / "a.pdf"
    d = fitz.open()
    for i in range(3):
        d.new_page(width=595, height=842).insert_text((72, 400), "A P%d" % (i + 1))
    d.set_toc([[1, "one", 1], [1, "two", 2]])
    d.save(str(a)); d.close()
    h_a = sha(a)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    QMessageBox.warning = staticmethod(lambda *a_, **k: warned.append(a_[2] if len(a_) > 2 else ""))
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    bt = mw.bookmark_tree
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.3)
    mw._on_bookmark_activated(str(a), 0); spin(1.0)

    # A 다른 폴더·이름(확장자 없이)
    answer["path"] = str(other / "새 이름")
    mw._action_save_as(); spin(3.0)
    out = other / "새 이름.pdf"
    chk(asked and asked[-1].endswith("a_edited.pdf"), "A 저장 창을 띄우고 기본 이름은 a_edited.pdf", str(asked))
    chk(out.is_file() and fitz.open(str(out)).page_count == 3, "A 고른 폴더·이름에 .pdf 를 붙여 저장", str(list(other.iterdir())))
    chk(sha(a) == h_a and not list(folder.glob("a_edited*.pdf")), "A 원본 그대로·<원본>_edited 는 만들지 않는다")

    # B 취소
    n0 = len(asked)
    answer["path"] = ""
    before = set(p.name for p in folder.iterdir()) | set(p.name for p in other.iterdir())
    mw._on_bookmark_activated(str(a), 0); spin(0.8)
    mw._action_save_as(); spin(2.0)
    after = set(p.name for p in folder.iterdir()) | set(p.name for p in other.iterdir())
    chk(len(asked) == n0 + 1 and after == before and sha(a) == h_a and not warned,
        "B 취소 → 새 파일·임시 파일 없음, 원본 그대로, 오류 알림 없음", str((after - before, warned)))

except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
