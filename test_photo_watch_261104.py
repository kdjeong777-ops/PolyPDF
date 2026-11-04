# -*- coding: utf-8 -*-
"""사진 폴더 감시 (사진 보기 SOT 4.27, 261104-7 B2).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진 모드에서 보는 폴더에 바깥에서 사진을 넣으면 목록에 더해진다(알림 300ms 모아 배경 훑기)
B. 바깥에서 지우면 목록에서 빠진다
C. 앱이 그 폴더에 쓰는 사이드카(page_meta.json — 돌리기)로는 다시 읽지 않는다
D. PDF 모드에서는 감시하지 않는다(보는 폴더 하나만, 사진 모드에서만)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_watch_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 폴더 감시", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_watch_"))
try:
    from PIL import Image
    Image.new("RGB", (300, 200), (30, 160, 60)).save(tmp / "a.jpg", "JPEG")
    Image.new("RGB", (300, 200), (60, 60, 200)).save(tmp / "b.jpg", "JPEG")

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    names = lambda: sorted(Path(str(it.data(0, bt.DATA_FILE))).name for it in bt._iter_file_nodes())
    chk(pump(lambda: names() == ["a.jpg", "b.jpg"]), "사진 2장 목록")
    pump(lambda: mw.__dict__.get("_photo_watch_sig") is not None, timeout=5)
    mw._on_bookmark_activated(str(tmp / "a.jpg"), 0); pump(timeout=0.5)
    refreshed = []
    real_refresh = bt.refresh
    bt.refresh = lambda: (refreshed.append(1), real_refresh())[-1]

    # C
    mw._photo_rotate(+90); pump(timeout=1.5)
    chk((tmp / "page_meta.json").exists() and not refreshed, "C 사이드카(page_meta.json) 쓰기로는 다시 읽지 않는다", str(refreshed))

    # A
    Image.new("RGB", (300, 200), (200, 60, 60)).save(tmp / "c 새.jpg", "JPEG")
    chk(pump(lambda: "c 새.jpg" in names(), timeout=8), "A 바깥에서 넣은 사진이 목록에 더해진다", str(names()))
    chk(Path(mw.main_view.current_file()).name == "a.jpg", "A 보던 사진은 그대로")

    # B
    (tmp / "b.jpg").unlink()
    chk(pump(lambda: "b.jpg" not in names(), timeout=8), "B 바깥에서 지운 사진은 목록에서 빠진다", str(names()))

    # D
    mw._set_photo_mode(False); pump()
    w = mw.__dict__.get("_photo_watcher")
    chk(w is None or not w.directories(), "D PDF 모드에서는 감시하지 않는다", str(w.directories() if w else None))
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
