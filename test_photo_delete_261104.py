# -*- coding: utf-8 -*-
"""사진 지우기 — 썸네일 줄·본문의 '삭제'·Del (사진 보기 SOT 4.25, 261104-4 사용자 지시).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
휴지통 함수는 검사 폴더로 옮기는 가짜로 바꾼다 — 사용자 휴지통에 검사 파일을 보내지 않는다. 확인 창은 '예' 로 답한다.
A. 편집 모드가 아니면 Del 로 지우지 않는다(사진 파일 그대로)
B. 편집 모드에서 썸네일 줄 Del — 보던 사진을 휴지통으로, 책갈피창·썸네일 줄에서 빠지고 다음 사진을 연다
C. 썸네일 줄에서 여러 장 골라 Del — 고른 것 모두
D. 본문 Del(고른 꾸밈 없음) — 지금 사진을 지운다(PDF 처럼 쪽 편집이 아니라 파일)
E. 확인 창에서 '아니요' 면 아무것도 지우지 않는다
F. 썸네일 줄·본문 우클릭 메뉴에 '삭제'
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, Qt
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox, QMenu
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_delete_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 지우기", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=15.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


answer = {"v": QMessageBox.StandardButton.Yes}
_orig_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: answer["v"])
menu_texts = []
_orig_exec = QMenu.exec
QMenu.exec = lambda self, *a, **k: (menu_texts.clear(), menu_texts.extend(x.text().split("\t")[0] for x in self.actions()), None)[-1]

tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_delete_"))
trash = tmp.parent / (tmp.name + "_trash")
trash.mkdir()
try:
    from PIL import Image
    for i, n in enumerate(("1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg"), 1):
        Image.new("RGB", (200 + i, 150), (40 * i, 90, 160)).save(tmp / n, "JPEG")
    P = lambda n: str(tmp / n)

    import viewer.widgets.bookmark_tree as _btm
    _btm._trash_fn = lambda: (lambda p: os.replace(p, str(trash / Path(p).name)))

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 5), "사진 5장 목록")
    bt.set_sort_mode(bt.SORT_NAME); pump()
    mw._on_bookmark_activated(P("2.jpg"), 0); pump(timeout=0.5)
    strip = mw._photo_strip
    names = lambda: sorted(Path(str(it.data(0, bt.DATA_FILE))).name for it in bt._iter_file_nodes())

    # A
    bt.set_edit_mode(False); pump()
    strip.setFocus(); QTest.keyClick(strip, Qt.Key.Key_Delete); pump()
    chk(Path(P("2.jpg")).exists(), "A 편집 모드가 아니면 지우지 않는다")

    # F
    strip.menuRequested.emit(P("2.jpg"), QPoint(5, 5)); pump()
    chk("삭제" in menu_texts, "F 썸네일 줄 메뉴에 '삭제'", str(menu_texts))
    mw._photo_context_menu(QPoint(5, 5))
    chk("삭제" in menu_texts, "F 본문 사진 메뉴에 '삭제'", str(menu_texts))

    # B
    bt.set_edit_mode(True); pump()
    mw._on_bookmark_activated(P("2.jpg"), 0); pump(timeout=0.5)
    strip.setFocus(); QTest.keyClick(strip, Qt.Key.Key_Delete); pump(timeout=0.8)
    chk(not Path(P("2.jpg")).exists() and (trash / "2.jpg").exists(), "B 보던 사진을 휴지통으로")
    chk("2.jpg" not in names() and all(Path(p).name != "2.jpg" for p in strip.paths()), "B 책갈피창·썸네일 줄에서 빠진다", str(names()))
    chk(Path(mw.main_view.current_file()).name == "3.jpg", "B 다음 사진을 연다", str(mw.main_view.current_file()))

    # E
    answer["v"] = QMessageBox.StandardButton.No
    QTest.keyClick(strip, Qt.Key.Key_Delete); pump(timeout=0.5)
    chk(Path(P("3.jpg")).exists(), "E '아니요' 면 지우지 않는다")
    answer["v"] = QMessageBox.StandardButton.Yes

    # C
    mw._photo_delete([P("4.jpg"), P("5.jpg")]); pump(timeout=0.8)
    chk(not Path(P("4.jpg")).exists() and not Path(P("5.jpg")).exists() and names() == ["1.jpg", "3.jpg"], "C 여러 장 함께", str(names()))

    # D
    mw._on_bookmark_activated(P("3.jpg"), 0); pump(timeout=0.5)
    mw.main_view.view.setFocus()
    mw._delete_current_page(); pump(timeout=0.8)
    chk(not Path(P("3.jpg")).exists() and Path(mw.main_view.current_file()).name == "1.jpg", "D 본문 Del — 지금 사진을 지우고 남은 사진으로",
        str(mw.main_view.current_file()))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMessageBox.question = _orig_q
    QMenu.exec = _orig_exec
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(trash, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
