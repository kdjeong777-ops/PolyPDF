# -*- coding: utf-8 -*-
"""261107-5: 사진 형식 변환 — 우클릭 저장 ▸ '변환' (사진 보기 SOT §4.30·§4.20·§4.46, 디자인 SOT §2.9.8).

261112-15(사진 보기 SOT §4.46, 사용자 결정 '창 하나에 두 묶음'): 종전 '변환 ▸' JPEG·PNG·WebP 하위 메뉴는 **변환 창**으로 — 형식은 창에서 고른다.
실제 MainWindow(오프스크린, 시험 프로필 — 마스터 §14.7.2 의 3). 메뉴는 `QMenu.exec` 를 가로채 항목을 고르고, 변환 창은 `exec` 를 가로채 실제 창을 다룬다.
A. 세 사진 메뉴(책갈피창·썸네일 줄·본문)의 저장 ▸ 에 '변환' — 켜져 있고 누르면 변환 창(그 사진)
B. 창에서 'WebP' → 원본 옆에 새 .webp(Pillow 로 열리고 WEBP), 원본은 바이트 그대로
C. 여러 장(썸네일 줄에서 둘 고름) → 창에 두 장, 'PNG' 저장 → 두 장 모두 새 .png
D. 일괄 작업 창 '형식 바꾸기' 에도 WebP
"""
import os, sys, tempfile, shutil, time, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_fmt_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 형식 변환", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def wait_idle(dlg, timeout_s=10.0):
    """변환 창의 배경 일(미리보기·저장·복사)이 끝날 때까지 이벤트를 돌린다 — 검사 쪽 기다림(앱 코드에는 두지 않는다, 응답성 SOT §6)."""
    t = time.monotonic()
    while time.monotonic() - t < timeout_s:
        QApplication.processEvents()
        if not dlg.busy():
            return True
        time.sleep(0.01)
    return False


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


seen = {"menu": None, "pick": None}
_orig_exec = QMenu.exec


def _find(menu, path):
    for x in menu.actions():
        if x.isSeparator():
            continue
        if x.text().split("\t")[0] == path[0]:
            if len(path) == 1:
                return x
            return _find(x.menu(), path[1:]) if x.menu() is not None else None
    return None


def fake_exec(self, *a, **k):
    seen["menu"] = self
    p, seen["pick"] = seen["pick"], None
    return _find(self, p) if p else None


def conv_sub(menu):
    sv = next((x for x in menu.actions() if x.property("ctx_save")), None) if menu else None
    cv = next((x for x in sv.menu().actions() if x.text().split("\t")[0] == "변환"), None) if sv else None
    return cv


from viewer.widgets.image_tune_dialog import ImageTuneDialog
_orig_tune_exec = ImageTuneDialog.exec
tune = {"plan": None, "seen": []}


def tune_exec(self):
    """변환 창 — 실제 창을 다룬다: plan = 고를 형식(없으면 그냥 닫기)."""
    tune["seen"].append(list(self._paths))
    fmt = tune["plan"]
    if fmt:
        wait_idle(self)
        self.cmb_fmt.setCurrentIndex(self.cmb_fmt.findData(fmt))
        self.btn_save.click()
        wait_idle(self, 20)
    return 0


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_fmt_"))
try:
    from PIL import Image
    Image.new("RGB", (640, 320), (200, 60, 60)).save(tmp / "a 사진.jpg", "JPEG")
    Image.new("RGB", (500, 300), (60, 160, 60)).save(tmp / "b 사진.jpg", "JPEG")
    a, b = str(tmp / "a 사진.jpg"), str(tmp / "b 사진.jpg")
    h_a = sha(a)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw.open_folder(tmp)
    mw._set_photo_mode(True)

    def node(name):
        return next((n for n in bt._iter_file_nodes() if Path(str(n.data(0, bt.DATA_FILE))).name == name), None)
    pump(lambda: node("a 사진.jpg") is not None and node("b 사진.jpg") is not None)
    mw._on_bookmark_activated(a, 0); pump(timeout=0.8)
    QMenu.exec = fake_exec
    ImageTuneDialog.exec = tune_exec

    # A
    it = node("a 사진.jpg")
    bt._on_tree_context_menu(bt.tree.visualItemRect(it).center())
    cv_tree = conv_sub(seen["menu"])
    strip = mw._photo_strip_widget()
    pump(lambda: len(strip.paths()) >= 2, timeout=8)
    mw._photo_strip_menu(a, QPoint(5, 5))
    cv_strip = conv_sub(seen["menu"])
    mw._photo_context_menu(QPoint(5, 5))
    cv_body = conv_sub(seen["menu"])
    for name, cv in (("책갈피창", cv_tree), ("썸네일 줄", cv_strip), ("본문", cv_body)):
        chk(cv is not None and cv.isEnabled() and cv.menu() is None, "A %s 저장 ▸ '변환' — 하위 메뉴 없이 창" % name,
            str(cv.menu() if cv is not None else None))
    tune["plan"] = None
    seen["pick"] = ("저장", "변환")
    mw._photo_context_menu(QPoint(5, 5))
    chk(pump(lambda: bool(tune["seen"]), timeout=5) and tune["seen"][-1] == [a], "A 누르면 그 사진의 변환 창", str(tune["seen"]))

    # B
    tune["plan"] = "webp"
    seen["pick"] = ("저장", "변환")
    mw._photo_context_menu(QPoint(5, 5))
    w = tmp / "a 사진_변환.webp"
    chk(pump(lambda: w.exists(), timeout=10), "B 원본 옆에 새 .webp", str(os.listdir(tmp)))
    if w.exists():
        with Image.open(str(w)) as im:
            chk(im.format == "WEBP" and im.size == (640, 320), "B WEBP 로 열리고 크기 그대로", "%s %s" % (im.format, im.size))
    chk(sha(a) == h_a, "B 원본은 그대로")

    # C
    strip.clearSelection()
    for p in (a, b):
        strip._items[p].setSelected(True)
    tune["plan"] = "png"
    seen["pick"] = ("저장", "변환")
    mw._photo_strip_menu(b, QPoint(5, 5))
    chk(pump(lambda: (tmp / "a 사진_변환.png").exists() and (tmp / "b 사진_변환.png").exists(), timeout=10)
        and sorted(tune["seen"][-1]) == sorted([a, b]), "C 여러 장 — 창에 두 장, 두 장 모두 새 .png", str(os.listdir(tmp)))

    # D
    QMenu.exec = _orig_exec
    from PyQt6.QtWidgets import QComboBox, QDialog
    seen_fmt = []
    _orig_dexec = QDialog.exec

    def dexec(self):
        for cb in self.findChildren(QComboBox):
            seen_fmt.append([cb.itemData(i) for i in range(cb.count())])
        return QDialog.DialogCode.Rejected
    QDialog.exec = dexec
    try:
        mw._photo_batch_dialog([a])
    finally:
        QDialog.exec = _orig_dexec
    chk(any("webp" in f for f in seen_fmt), "D 일괄 작업 '형식 바꾸기' 에도 WebP", str(seen_fmt))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    ImageTuneDialog.exec = _orig_tune_exec
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
