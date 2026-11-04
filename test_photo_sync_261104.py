# -*- coding: utf-8 -*-
"""본문 사진 ↔ 책갈피창 고름 맞추기 (사진 보기 SOT 4.26, 261104-4 사용자 지시
'썸네일이나 본화면의 보이는 사진이 바뀌는데 책갈피창의 파일리스트에서 선택된 파일이 안 바뀌어').

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 썸네일 줄을 눌러 사진이 바뀌면 책갈피창의 그 줄이 골라진다(다시 열지 않는다 — 본문은 그 사진 그대로)
B. 넘김(PageDown 경계)·검색 결과로 바뀌어도 같다
C. 책갈피창에서 여러 장을 골라 둔 채 그중 다른 사진으로 가면 고름은 그대로, '지금 줄' 만 옮긴다
D. zip 에서 꺼낸 사진을 보면 책갈피창은 그 zip 줄
"""
import os, sys, tempfile, shutil, time, zipfile, io
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_sync_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 고름 맞추기", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_sync_"))
try:
    from PIL import Image
    for i, n in enumerate(("가 산.jpg", "나 바다.jpg", "다 숲.jpg", "라 강.jpg"), 1):
        Image.new("RGB", (200 + i, 150), (40 * i, 90, 160)).save(tmp / n, "JPEG")
    b = io.BytesIO(); Image.new("RGB", (100, 80), (9, 9, 9)).save(b, "JPEG")
    with zipfile.ZipFile(tmp / "마 묶음.zip", "w") as z:
        z.writestr("안.jpg", b.getvalue())
    P = lambda n: str(tmp / n)

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 5), "사진 4장·zip 1 목록")
    bt.set_sort_mode(bt.SORT_NAME); pump()
    mw._on_bookmark_activated(P("가 산.jpg"), 0); pump(timeout=0.5)
    cur_row = lambda: Path(str(bt.tree.currentItem().data(0, bt.DATA_FILE))).name if bt.tree.currentItem() else None
    sel_rows = lambda: sorted(Path(str(it.data(0, bt.DATA_FILE))).name for it in bt.tree.selectedItems())
    strip = mw._photo_strip
    pump(lambda: len(strip.paths()) == 4, timeout=5)

    # A
    it = strip._items[P("다 숲.jpg")]
    strip.scrollToItem(it)
    QTest.mouseClick(strip.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, strip.visualItemRect(it).center())
    pump(timeout=0.6)
    chk(Path(mw.main_view.current_file()).name == "다 숲.jpg", "A 썸네일 줄을 누르면 본문이 그 사진")
    chk(cur_row() == "다 숲.jpg" and sel_rows() == ["다 숲.jpg"], "A 책갈피창도 그 줄", "%s %s" % (cur_row(), sel_rows()))
    pump(timeout=0.5)
    chk(Path(mw.main_view.current_file()).name == "다 숲.jpg", "A 책갈피창 고름이 다시 열지 않는다")

    # B
    mw._on_file_boundary(+1, mw._active_pane); pump(timeout=0.5)
    chk(cur_row() == "라 강.jpg", "B 넘김 — 책갈피창도 다음 줄", str(cur_row()))
    mw.action_search("나"); pump(timeout=1.0)
    mw._photo_index_start(); pump(timeout=2.0)
    mw.action_search("바다"); pump(timeout=1.0)
    if Path(mw.main_view.current_file()).name == "나 바다.jpg":
        chk(cur_row() == "나 바다.jpg", "B 검색 결과 — 책갈피창도 그 줄", str(cur_row()))
    mw.action_search(""); pump(timeout=0.5)

    # C
    bt.tree.blockSignals(True)
    bt.tree.clearSelection()
    for x in bt._iter_file_nodes():
        if Path(str(x.data(0, bt.DATA_FILE))).name in ("가 산.jpg", "다 숲.jpg"):
            x.setSelected(True)
    bt.tree.blockSignals(False)
    mw._on_bookmark_activated(P("가 산.jpg"), 0); pump(timeout=0.5)
    mw._on_file_boundary(+1, mw._active_pane); pump(timeout=0.5)
    chk(Path(mw.main_view.current_file()).name == "다 숲.jpg", "C 고른 두 장 안에서 넘김", str(mw.main_view.current_file()))
    chk(sel_rows() == ["가 산.jpg", "다 숲.jpg"] and cur_row() == "다 숲.jpg", "C 여러 장 고름은 그대로, 지금 줄만 옮김", "%s %s" % (cur_row(), sel_rows()))

    # D
    bt.tree.clearSelection()
    mw._on_bookmark_activated(P("마 묶음.zip"), 0)
    pump(lambda: strip.paths() and Path(strip.paths()[0]).name == "안.jpg", timeout=10); pump(timeout=0.5)
    chk(cur_row() == "마 묶음.zip", "D zip 에서 꺼낸 사진을 보면 책갈피창은 그 zip 줄", str(cur_row()))
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
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
