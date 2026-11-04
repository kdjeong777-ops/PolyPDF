# -*- coding: utf-8 -*-
"""움직이는 GIF·WebP (사진 보기 SOT 4.31, §5.1 F10, 261104-7 B6).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 움직이는 GIF 를 열면 첫 장이 보이고 본문 왼쪽 아래에 ▶ — 저절로 재생하지 않는다
B. ▶ 를 누르면 사진 자리에 재생(■ 로 바뀜), 다시 누르면 멈춘다
C. 다른 사진으로 가면 멈추고 ▶ 도 사라진다(재생은 보일 때만)
D. 한 장짜리 GIF·JPEG 에는 ▶ 가 없다
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
from PyQt6.QtGui import QMovie
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_anim_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "움직이는 그림", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_anim_"))
try:
    from PIL import Image
    frames = [Image.new("RGB", (200, 150), c) for c in ((200, 0, 0), (0, 200, 0), (0, 0, 200))]
    frames[0].save(tmp / "a 움직임.gif", save_all=True, append_images=frames[1:], duration=100, loop=0)
    frames[0].save(tmp / "b 한장.gif")
    Image.new("RGB", (200, 150), (90, 90, 90)).save(tmp / "c 사진.jpg", "JPEG")

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3)

    # A
    mw._on_bookmark_activated(str(tmp / "a 움직임.gif"), 0); pump(timeout=0.8)
    b = mw.__dict__.get("_photo_anim_btn")
    chk(b is not None and b.isVisible() and b.text() == "▶", "A 움직이는 GIF — ▶ 가 보인다")
    chk(mw.__dict__.get("_photo_anim_movie") is None, "A 저절로 재생하지 않는다")

    # B
    b.click(); pump(timeout=0.5)
    m = mw.__dict__.get("_photo_anim_movie")
    lab = mw.__dict__.get("_photo_anim_label")
    chk(m is not None and m.state() == QMovie.MovieState.Running and lab.isVisible() and b.text() == "■", "B 누르면 재생")
    b.click(); pump()
    chk(mw.__dict__.get("_photo_anim_movie") is None and not lab.isVisible() and b.text() == "▶", "B 다시 누르면 멈춘다")

    # C
    b.click(); pump(timeout=0.3)
    mw._on_bookmark_activated(str(tmp / "c 사진.jpg"), 0); pump(timeout=0.8)
    chk(mw.__dict__.get("_photo_anim_movie") is None and not lab.isVisible() and not b.isVisible(), "C 다른 사진으로 가면 멈추고 ▶ 도 사라진다")

    # D
    mw._on_bookmark_activated(str(tmp / "b 한장.gif"), 0); pump(timeout=0.8)
    chk(not b.isVisible(), "D 한 장짜리 GIF 에는 ▶ 가 없다")
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
