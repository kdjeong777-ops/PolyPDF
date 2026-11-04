# -*- coding: utf-8 -*-
"""지도에서 위치 보기 (사진 보기 SOT 4.29, §5.1 F6·D18, 261104-7 B4).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 브라우저 열기는 가짜로 바꿔 주소만 본다.
A. GPS 가 있는 사진의 본문 우클릭에 '지도에서 위치 보기', 없는 사진에는 없다
B. 누를 때마다 '촬영 위치가 지도 서비스로 보내집니다' 를 묻는다(D18) — '아니요' 면 열지 않는다
C. '예' 면 그 좌표의 지도 주소(OpenStreetMap)를 기본 브라우저로
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox
from PyQt6.QtGui import QDesktopServices
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_map_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "지도", echo=False)   # 마스터 §14.7.2 의 6
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


menu_texts = []
_orig_exec = QMenu.exec
QMenu.exec = lambda self, *a, **k: (menu_texts.clear(), menu_texts.extend(x.text().split("\t")[0] for x in self.actions()), None)[-1]
asked = []
answer = {"v": QMessageBox.StandardButton.No}
_orig_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), answer["v"])[-1])
opened = []
_orig_open = QDesktopServices.openUrl
QDesktopServices.openUrl = staticmethod(lambda u: (opened.append(u.toString()), True)[-1])

tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_map_"))
try:
    from PIL import Image
    ex = Image.Exif()
    ex[0x8825] = {1: "N", 2: (37.0, 30.0, 0.0), 3: "E", 4: (127.0, 0.0, 36.0)}
    Image.new("RGB", (300, 200), (30, 160, 60)).save(tmp / "a 위치.jpg", "JPEG", exif=ex.tobytes())
    Image.new("RGB", (300, 200), (60, 60, 200)).save(tmp / "b 없음.jpg", "JPEG")

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 2)

    # A
    mw._on_bookmark_activated(str(tmp / "b 없음.jpg"), 0)
    pump(lambda: mw.__dict__.get("_photo_info") is not None, timeout=5)
    mw._photo_context_menu(QPoint(5, 5))
    chk("지도에서 위치 보기" not in menu_texts, "A GPS 없는 사진에는 지도 항목이 없다")
    mw._on_bookmark_activated(str(tmp / "a 위치.jpg"), 0)
    pump(lambda: (mw.__dict__.get("_photo_info") or {}).get("gps") is not None, timeout=5)
    mw._photo_context_menu(QPoint(5, 5))
    chk("지도에서 위치 보기" in menu_texts, "A GPS 있는 사진에는 지도 항목", str(menu_texts))

    # B
    mw._photo_action("map", [str(tmp / "a 위치.jpg")])
    chk(len(asked) == 1 and "지도 서비스" in asked[0] and not opened, "B 묻고, '아니요' 면 열지 않는다", str(asked))
    # C
    answer["v"] = QMessageBox.StandardButton.Yes
    mw._photo_action("map", [str(tmp / "a 위치.jpg")])
    chk(len(asked) == 2, "B 누를 때마다 묻는다")
    chk(opened and "openstreetmap.org" in opened[-1] and "mlat=37.500000" in opened[-1] and "mlon=127.010000" in opened[-1],
        "C '예' 면 그 좌표의 지도 주소로", str(opened))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    QMessageBox.question = _orig_q
    QDesktopServices.openUrl = _orig_open
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
