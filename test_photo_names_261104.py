# -*- coding: utf-8 -*-
"""긴 사진 이름·상태 막대 파일 이름 (사진 보기 SOT 4.18, 261104-8 사용자 보고).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 앞머리가 같은 긴 이름 둘 — 썸네일 칸에 그려진 이름이 서로 다르다(뒷부분이 보인다)
B. 상태 막대 가운데 사진 정보에 파일 이름이 있다
C. zip 안 사진이면 'zip 이름 › 사진 이름'
"""
import os, sys, tempfile, shutil, time, zipfile, io
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QStyleOptionViewItem
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_names_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 이름", echo=False)   # 마스터 §14.7.2 의 6
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


def drawn_name(strip, path):
    """칸에 실제로 그려지는 첫 줄 — 목록의 줄임 방식(textElideMode)·칸 폭으로 줄인 글."""
    from PyQt6.QtCore import Qt
    it = strip._items[path]
    first = it.text().split("\n")[0]
    w = min(strip.visualItemRect(it).width(), strip.viewport().width()) - 6     # 칸 글은 보이는 폭 안에서 줄인다
    return strip.fontMetrics().elidedText(first, strip.textElideMode(), w)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_names_"))
try:
    from PIL import Image
    a = tmp / "device_001_20260723_141501_front_meter.jpg"
    b = tmp / "device_001_20260723_141522_back_meter.jpg"
    Image.new("RGB", (320, 240), (90, 90, 160)).save(a, "JPEG")
    Image.new("RGB", (320, 240), (160, 90, 90)).save(b, "JPEG")
    buf = io.BytesIO(); Image.new("RGB", (200, 150), (40, 140, 40)).save(buf, "JPEG")
    zp = tmp / "현장 사진.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("계량기 앞.jpg", buf.getvalue())

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3)
    mw._on_bookmark_activated(str(a), 0); pump(timeout=0.8)
    strip = mw._photo_strip
    pump(lambda: len(strip.paths()) == 2, timeout=5)

    # A
    na, nb = drawn_name(strip, str(a)), drawn_name(strip, str(b))
    chk(na != nb and na.endswith(a.stem[-5:]), "A 긴 이름 — 뒷부분이 보여 서로 다르다", f"{na!r} {nb!r}")

    if os.environ.get("ZT_SHOT"):                  # 눈으로 볼 때만
        strip.grab().save(os.environ["ZT_SHOT"])

    # B
    btn = mw._photo_info_btn
    chk(pump(lambda: a.name in btn.text() and "320 × 240" in btn.text(), timeout=5), "B 상태 막대에 파일 이름·크기", repr(btn.text()))

    # C
    mw._on_bookmark_activated(str(zp), 0)
    chk(pump(lambda: "현장 사진.zip › 계량기 앞.jpg" in btn.text() and "200 × 150" in btn.text(), timeout=10),
        "C zip 안 사진 — 'zip 이름 › 사진 이름'", repr(btn.text()))
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
