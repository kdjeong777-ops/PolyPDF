# -*- coding: utf-8 -*-
"""사진 모드에서는 PDF 를 색인하지 않는다 (사진 보기 SOT 4.23, 261104-3 사용자 보고 '사진 모드에서 pdf 를 인덱싱하고 있어').

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진 모드에서 PDF·사진이 섞인 폴더를 열면 색인 작업이 시작되지 않는다(진행 막대도 없다)
B. 돌던 PDF 색인은 사진 모드로 바꾸면 멈춘다
C. PDF 모드로 돌아오면 그 폴더 색인을 다시 건다 — PDF 가 색인에 들어간다
"""
import os, sys, tempfile, shutil, time, sqlite3
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
QCoreApplication.setApplicationName("polypdf_photo_index_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 색인", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_index_"))
try:
    from PIL import Image
    import fitz
    Image.new("RGB", (300, 200), (30, 160, 60)).save(tmp / "사진.jpg", "JPEG")
    d = fitz.open(); pg = d.new_page(); pg.insert_text((72, 72), "polypix index probe"); d.save(str(tmp / "문서.pdf")); d.close()

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()

    started = []
    real_start = mw._start_index_worker.__func__

    # A
    mw._set_photo_mode(True); pump()
    n0 = len(getattr(mw, "_index_workers", []))
    mw.open_folder(tmp); pump(timeout=1.5)
    chk(not mw._index_workers, "A 사진 모드 폴더 열기 — 색인 작업 없음", str(mw._index_workers))
    chk(not mw.progress.isVisible(), "A 진행 막대도 없다")

    def indexed():
        try:
            con = sqlite3.connect(str(mw._db_path))
            try:
                rows = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            finally:
                con.close()
            return rows
        except Exception:
            return 0
    chk(indexed() == 0, "A 색인에 PDF 가 들어가지 않았다", str(indexed()))

    # C
    mw._set_photo_mode(False)
    chk(pump(lambda: indexed() >= 1, timeout=15), "C PDF 모드로 돌아오면 그 폴더를 색인한다", str(indexed()))

    # B
    mw._set_photo_mode(True); pump()
    chk(not mw._index_workers, "B 사진 모드로 바꾸면 돌던 색인을 멈춘다", str(mw._index_workers))
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
