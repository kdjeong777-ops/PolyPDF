# -*- coding: utf-8 -*-
"""모양 펴기 여러 장 일괄 [저장] — 사진마다 제 점으로 (사진 보기 SOT §4.43, 261106-17 사용자 보고 '앞의 4개는 제대로, 뒤의 4개가 이상하게').

실제 MainWindow·실제 워커(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
사진 8장 — EXIF 방향 1·6 이 섞이고 크기가 다르다(앞 4장 방향 1, 뒤 4장 방향 6 — 사용자 상황), 네 귀퉁이 색이 달라 어긋나면 드러난다.
A. ❮ ❯ 로 넘기며 사진마다 다른 점 → [확인] → [저장] 한꺼번에 — 각 결과 = 그 사진(세운 그림)을 그 점으로 편 것, 방향 1
B. 원본은 모두 '_원본' 에(바이트 그대로), 다른 사진에 섞이지 않는다
C. 넘긴 뒤 그림이 들어오기 전에는 고치지 못한다 — 그때 누른 A 키·켜고 끔이 앞 사진 몫으로 섞이지 않는다
"""
import os, sys, tempfile, shutil, time, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_warp_batch_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "펴기 일괄", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=20.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


def diff(a, b, n=24):
    a = a.convert("RGB").resize((n, n))
    b = b.convert("RGB").resize((n, n))
    pa, pb_ = list(a.getdata()), list(b.getdata())
    return sum(abs(x[k] - y[k]) for x, y in zip(pa, pb_) for k in range(3)) / (3.0 * len(pa))


tmp = Path(tempfile.mkdtemp(prefix="polypdf_warp_batch_"))
try:
    from PIL import Image, ImageOps, ImageDraw
    from viewer import photo_warp as pw, photo_backup
    photo_backup.set_custom_dir("")
    COLORS = [(220, 30, 30), (30, 200, 30), (30, 30, 220), (230, 220, 30)]
    srcs = []
    for i in range(8):
        o = 1 if i < 4 else 6
        w, h = (900 + 40 * i, 600 + 20 * i)
        im = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(im)
        c = COLORS[i % 4:] + COLORS[:i % 4]                   # 사진마다 색 배치가 다르다
        d.rectangle((0, 0, w // 2, h // 2), fill=c[0]); d.rectangle((w // 2, 0, w, h // 2), fill=c[1])
        d.rectangle((0, h // 2, w // 2, h), fill=c[2]); d.rectangle((w // 2, h // 2, w, h), fill=c[3])
        d.rectangle((40 + 10 * i, 40, 160 + 10 * i, 100), fill=(255, 255, 255))
        ex = Image.Exif(); ex[0x0112] = o
        p = tmp / ("IMG_%02d.jpg" % i)
        im.save(p, "JPEG", quality=95, exif=ex.tobytes())
        os.utime(p, (1700000000 + i * 60, 1700000000 + i * 60))
        srcs.append(str(p))
    ups = {}
    for p in srcs:
        with Image.open(p) as im0:
            ups[p] = ImageOps.exif_transpose(im0).convert("RGB")
    sums = {p: hashlib.md5(Path(p).read_bytes()).hexdigest() for p in srcs}

    def pts_for(k):                                        # 사진마다 다른 비뚤어진 사각형
        a = 0.05 + 0.03 * (k % 4)
        c = [(a, a + 0.02), (0.6 + 0.04 * (k % 3), a), (0.62, 0.55 + 0.03 * (k % 2)), (a + 0.02, 0.5)]
        return c + pw.mids_of(c)

    from viewer.app import MainWindow
    from viewer.widgets.photo_crop_dialog import PhotoCropDialog
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump()
    mw.open_folder(tmp)
    bt = mw.bookmark_tree
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 8)
    mw._on_bookmark_activated(srcs[0], 0); pump(timeout=1.0)
    _exec = PhotoCropDialog.exec
    _mb = QMessageBox.exec
    seen = {}

    def fake_box(self):
        for b in self.buttons():
            if b.text() == "저장":
                b.click()
                break
        return 0
    QMessageBox.exec = fake_box

    def fake_exec(self):
        P = list(mw._photo_crop_paths)
        seen["P"] = P
        pump(lambda: not self._loading, 15)
        start = P.index(srcs[0])
        order = [start] + [k for k in range(len(P)) if k != start]
        used = {}
        for n, k in enumerate(order):
            if n:
                self._go(k)
                # C — 그림이 들어오기 전: A 키·켜고 끔은 받지 않는다(앞 사진 몫으로 섞이지 않게)
                if n == 1:
                    prev = order[0]
                    before = (self._warp_on.get(prev), list(self._warp_pts.get(prev) or []))
                    QTest.keyClick(self, Qt.Key.Key_A)
                    self.chk_warp.click()
                    seen["locked"] = (self._loading, not self.chk_warp.isEnabled(), not self.stack.isEnabled())
                    seen["prev_same"] = (self._warp_on.get(prev), list(self._warp_pts.get(prev) or [])) == before
                pump(lambda: not self._loading and self.index() == k, 15)
            self.chk_warp.setChecked(True)
            q = pts_for(k)
            self.warp.set_points(q)
            used[P[k]] = q
        seen["used"] = used
        self.accept()
        return getattr(self, "done_code", 0)
    PhotoCropDialog.exec = fake_exec
    mw._photo_crop_dialog(srcs[0])
    pump(lambda: "used" in seen, 60)
    pump(lambda: not mw.__dict__.get("_photo_warp_busy"), 120)
    pump(timeout=1.0)
    PhotoCropDialog.exec = _exec
    QMessageBox.exec = _mb

    # A·B
    used = seen.get("used") or {}
    bk = tmp / "_원본"
    bad = []
    for p in srcs:
        q = used.get(p)
        if q is None:
            bad.append((Path(p).name, "점 없음"))
            continue
        want = pw.unwarp(ups[p], q)
        got = Image.open(p)
        dd = diff(got, want)
        o = int(got.getexif().get(0x0112, 1) or 1)
        if dd >= 12 or o != 1:
            bad.append((Path(p).name, round(dd, 1), o))
    chk(len(used) == 8 and not bad, "A 8장 모두 그 사진을 제 점으로 편 결과(방향 1·6 섞임, 앞뒤 구분 없이), 방향 1", str(bad))
    names = sorted(x.name for x in bk.iterdir()) if bk.is_dir() else []
    chk(names == sorted(Path(p).name for p in srcs)
        and all(hashlib.md5((bk / Path(p).name).read_bytes()).hexdigest() == sums[p] for p in srcs),
        "B 원본 8장은 모두 '_원본' 에 바이트 그대로(다른 사진에 섞이지 않음)", str(names))
    # C
    chk(seen.get("locked") == (True, True, True), "C 넘긴 뒤 그림이 들어오기 전에는 고치는 칸·모양 펴기가 잠긴다", str(seen.get("locked")))
    chk(seen.get("prev_same") is True, "C 그 사이 누른 A·켜고 끔이 앞 사진 몫으로 섞이지 않는다")
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
