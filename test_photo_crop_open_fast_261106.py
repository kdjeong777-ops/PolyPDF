# -*- coding: utf-8 -*-
"""크롭 창이 바로 열린다 — 큰 사진 폴더에서도 (사진 보기 SOT §4.40, 응답성 SOT §5, 261106-14 사용자 지시 '크롭을 누른 후 꽤 많이 있다 열린다').

실제 MainWindow(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 사진 3,000장 폴더 + 12 MP 사진.
종전에는 넘김 목록을 사진마다 디스크를 타며 걸렀고(7천 장에서 메인 16초) 그림을 다 푼 뒤에야 창을 열었다.
A. '크롭...' → 창이 보일 때까지 < OPEN_LIMIT_S, 그동안·그 뒤 그림이 들어올 때까지 메인 하트비트 공백 < 1초
B. 창이 먼저 보이고(그림 없이, ❮ ❯ 꺼짐) 그림이 뒤따라 들어온다
C. 넘김 목록 거르기는 글자열만으로 — 폴더 밖·zip 꺼낸 사진·휴대 장치 사진·사진 아닌 파일은 빠지고, 순서는 그대로
"""
import os, sys, time, tempfile, shutil, io
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QDialog
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_crop_open_fast_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "크롭 빨리 열기", echo=False)
fails = []
N = 3000
OPEN_LIMIT_S = 1.0          # 창이 보일 때까지(실측 7천 장 0.12초 — 바쁜 기계 여유)


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
        time.sleep(0.005)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_crop_open_fast_"))
try:
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (64, 48), (90, 120, 160)).save(b, "JPEG"); small = b.getvalue()
    for i in range(N):
        (tmp / ("IMG_%05d.jpg" % i)).write_bytes(small)
    Image.effect_noise((4000, 3000), 60).convert("RGB").save(tmp / "big.jpg", "JPEG", quality=90)
    big = str(tmp / "big.jpg")

    from viewer.app import MainWindow
    from viewer.widgets.photo_crop_dialog import PhotoCropDialog
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump()
    mw.open_folder(tmp)
    bt = mw.bookmark_tree
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= N + 1, 120), "준비 — 사진 %d장 목록" % (N + 1))
    mw._on_bookmark_activated(big, 0); pump(timeout=1.5)

    gaps = []
    last = [time.monotonic()]

    def beat():
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now
    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat)
    seen = {}
    _exec = PhotoCropDialog.exec

    def fake_exec(self):
        self.show(); app.processEvents()
        seen["shown"] = time.perf_counter()
        seen["empty_at_show"] = self.canvas._img is None and self._loading and not self.nav.btn_next.isEnabled()
        pump(lambda: not self._loading and self.canvas._img is not None, 30)
        seen["image"] = time.perf_counter()
        seen["n"] = self._count
        return QDialog.DialogCode.Rejected
    PhotoCropDialog.exec = fake_exec
    hb.start(); last[0] = time.monotonic()
    t0 = time.perf_counter()
    mw._photo_crop_dialog(big)
    pump(lambda: "image" in seen, 30)
    hb.stop()
    PhotoCropDialog.exec = _exec

    # A
    open_s = seen.get("shown", t0 + 99) - t0
    img_s = seen.get("image", t0 + 99) - t0
    chk(open_s < OPEN_LIMIT_S, "A '크롭...' → 창이 보일 때까지 < %.1f초" % OPEN_LIMIT_S, "%.2f초" % open_s)
    chk(gaps and max(gaps) < 1.0, "A 메인 하트비트 공백 < 1초(응답성 SOT §5)", "%.2f초" % (max(gaps) if gaps else -1))
    chk(img_s < 5.0, "A 그림(12 MP)이 곧 따라온다(< 5초)", "%.2f초" % img_s)
    chk(seen.get("n") == N + 1, "A 넘김 차례는 폴더 전체", str(seen.get("n")))
    # B
    chk(seen.get("empty_at_show") is True, "B 창이 먼저 보인다(그림 없이·❮ ❯ 꺼짐) — 그림은 뒤따른다")

    # C
    from viewer import photo_zip, photo_device
    z = str(photo_zip.cache_root() / "abc" / "p.jpg")
    d = str(photo_device.cache_root() / "dev" / "f" / "q.jpg")
    other = str(Path(tempfile.gettempdir()) / "elsewhere" / "x.jpg")
    keep = [str(tmp / "IMG_00001.jpg"), big, str(tmp / "IMG_00002.jpg")]
    fake = [keep[0], z, big, d, other, str(tmp / "note.txt"), keep[2]]
    _pl = mw._photo_list
    mw._photo_list = lambda: fake
    got = mw._photo_crop_range(big)
    mw._photo_list = _pl
    chk(got == keep, "C 폴더 밖·zip·휴대 장치·사진 아닌 파일은 빠지고 순서 그대로", str([Path(p).name for p in got]))
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
os._exit(1 if fails else 0)
