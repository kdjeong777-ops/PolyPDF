# -*- coding: utf-8 -*-
"""사진 우클릭 메뉴·'이 사진 풀기' 가 메인에서 사진마다 파일을 읽지 않는다 (사진 보기 SOT §4.43·§4.24.1, 응답성 SOT §6, 261106-21 지휘 점검).

실제 MainWindow(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. '원본으로 되돌리기' 메뉴 — 고른 사진 30장(한 폴더) → 백업 폴더 목록은 **한 번만** 읽는다(종전: 사진마다 `os.scandir`), 3장만 '(3장)'
B. zip 에서 꺼낸 사진 '고른 n장 풀기' — 메인에서 zip 을 **열지 않는다**(종전: 사진마다 `cached_to_member` 가 zip 목차를 읽음), 고른 것만 풀린다
"""
import os, sys, tempfile, shutil, time, threading, zipfile, io
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu, QFileDialog
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_main_fs_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 메뉴 파일 읽기", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=30.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_mainfs_"))
out = Path(str(tmp) + "_out"); out.mkdir()
MAIN = threading.main_thread().ident
_gd = QFileDialog.getExistingDirectory
try:
    from PIL import Image
    from viewer import photo_backup as pb
    pb.set_custom_dir("")

    def jpg_bytes(col):
        b = io.BytesIO(); Image.new("RGB", (120, 90), col).save(b, "JPEG"); return b.getvalue()
    paths = []
    for i in range(30):
        p = tmp / ("p%02d.jpg" % i)
        p.write_bytes(jpg_bytes((i * 8, 60, 90)))
        paths.append(str(p))
    for p in paths[:3]:                                  # 펴기 [저장] 처럼 — 백업으로 옮기고 같은 이름에 새 그림
        pb.move_to_backup(p)
        Path(p).write_bytes(jpg_bytes((200, 200, 200)))
    with zipfile.ZipFile(tmp / "pics.zip", "w") as z:
        for k in range(3):
            z.writestr("in/z%d.jpg" % k, jpg_bytes((40 * k, 100, 100)))

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump()
    mw.open_folder(tmp)
    bt = mw.bookmark_tree
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 30, timeout=20)

    # A
    calls = []
    _scandir = os.scandir

    def counting_scandir(*a, **k):
        if threading.get_ident() == MAIN:
            calls.append(a[0] if a else "")
        return _scandir(*a, **k)
    os.scandir = counting_scandir
    try:
        menu_a = QMenu()
        act = mw._photo_restore_action(menu_a, paths)
    finally:
        os.scandir = _scandir
    chk(act is not None and "3장" in act.text(), "A 백업이 있는 3장만 '원본으로 되돌리기 (3장)...'", act.text() if act else "")
    chk(len(calls) <= 1, "A 메뉴를 만들 때 백업 폴더는 한 번만 읽는다(사진 30장)", "scandir %d번" % len(calls))

    # B
    mw._on_bookmark_activated(str(tmp / "pics.zip"), 0)
    strip = mw._photo_strip_widget()
    pump(lambda: len(strip.paths()) == 3, timeout=20)
    sel = strip.paths()[:2]
    opens = []
    _zinit = zipfile.ZipFile.__init__

    def counting_init(self, *a, **k):
        if threading.get_ident() == MAIN:
            opens.append(str(a[0]) if a else "")
        return _zinit(self, *a, **k)
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(out))
    zipfile.ZipFile.__init__ = counting_init
    try:
        mw._zip_unpack_cached(sel)
    finally:
        zipfile.ZipFile.__init__ = _zinit
    chk(not opens, "B '고른 2장 풀기' — 메인에서 zip 을 열지 않는다", "%d번" % len(opens))
    chk(pump(lambda: len(os.listdir(out)) == 2 and not mw._jobs, timeout=30)
        and sorted(os.listdir(out)) == sorted(Path(p).name for p in sel), "B 고른 사진만 풀린다", str(os.listdir(out)))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QFileDialog.getExistingDirectory = _gd
    try:
        from viewer import photo_backup as _pb
        _pb.set_custom_dir("")
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
