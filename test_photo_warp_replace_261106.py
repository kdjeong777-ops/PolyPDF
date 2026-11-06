# -*- coding: utf-8 -*-
"""모양 펴기 [저장] = 원본 대체 + 원본 백업 (사진 보기 SOT §4.43, 261106-15 사용자 지시·결정).

실제 MainWindow·실제 워커(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 사진은 검사가 만든다(업무 사진 아님).
A. 백업 자리 — 기본 '사진 폴더 안 _원본', 고정 폴더면 원래 폴더 구조를 하위 폴더로, 같은 이름은 'name (2)', 되돌리기
B. 대체 — 원본 바이트는 백업으로, 원래 이름 자리에 펼친 사진. 촬영일·카메라(EXIF) 남고 방향 태그 1
C. 중간 실패 — 바꿔 넣기가 실패하면 원본이 제자리로 돌아온다(임시 파일 안 남음), 펴기 전에 실패하면 원본·백업 폴더 모두 그대로
D. 목록 — 사진 모드 목록에 '_원본'·고정 백업 폴더가 안 보인다
E. 환경설정 — 원본 백업 폴더 칸(기본 비움 = 사진 폴더 안 _원본), 고르면 그 폴더로 — 바꾼 값으로 대체 저장
F. 응답성 — 12 MP 대체 중 메인 하트비트 공백 < 1초(응답성 SOT §5)
"""
import os, sys, tempfile, shutil, time, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_warp_replace_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "펴기 원본 대체", echo=False)
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


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_warp_replace_"))
custom = Path(str(tmp) + "_backup")
try:
    from PIL import Image, ImageDraw
    from viewer import photo_backup as pb, photo_warp as pw
    import viewer.photo_controller as pc

    def photo(name, size=(1200, 900), orient=None):
        im = Image.new("RGB", size, (40, 50, 60))
        w, h = size
        ImageDraw.Draw(im).polygon([(w * .18, h * .13), (w * .84, h * .2), (w * .9, h * .9), (w * .12, h * .84)], fill=(245, 245, 240))
        ex = Image.Exif()
        ex[0x0110] = "TestCam X1"                       # Model
        ex[0x0132] = "2025:03:04 05:06:07"              # DateTime
        if orient:
            ex[0x0112] = orient
        im.save(tmp / name, "JPEG", quality=92, exif=ex.tobytes())
        return str(tmp / name)
    PTS = [(.18, .13), (.84, .2), (.9, .9), (.12, .84)]
    PTS = PTS + pw.mids_of(PTS)

    # A
    pb.set_custom_dir("")
    p1 = Path(tmp / "x.jpg")
    chk(pb.backup_dir_for(p1) == tmp / pb.BACKUP_DIRNAME, "A 기본 백업 자리 = 사진 폴더 안 _원본")
    pb.set_custom_dir(str(custom))
    bd = pb.backup_dir_for(p1)
    chk(str(bd).startswith(str(custom)) and bd.name == tmp.name and pb.is_backup_path(bd / "x.jpg"),
        "A 고정 폴더면 원래 폴더 구조를 하위 폴더로", str(bd))
    pb.set_custom_dir("")
    chk(pb.is_backup_path(tmp / "_원본" / "a.jpg") and not pb.is_backup_path(tmp / "a.jpg"), "A '_원본' 안 파일은 백업으로 본다")
    (tmp / "dup.jpg").write_bytes(b"one")
    (tmp / "_원본").mkdir()
    (tmp / "_원본" / "dup.jpg").write_bytes(b"old")
    moved = pb.move_to_backup(tmp / "dup.jpg")
    chk(Path(moved).name == "dup (2).jpg" and Path(moved).read_bytes() == b"one" and not (tmp / "dup.jpg").exists(),
        "A 같은 이름이 있으면 'name (2)'", moved)
    pb.restore(moved, tmp / "dup.jpg")
    chk((tmp / "dup.jpg").read_bytes() == b"one" and not Path(moved).exists(), "A 되돌리기 — 원래 자리로")
    (tmp / "dup.jpg").unlink(); shutil.rmtree(tmp / "_원본")

    # B — 실제 워커로 대체
    src = photo("doc.jpg", orient=6)
    h0 = md5(src)
    w = pc.PhotoWarpWorker([(src, 0, PTS)], dest=("replace", None))
    got = {}
    w.done.connect(lambda ok, bad: got.update(ok=ok, bad=bad))
    w.run()
    ok = got.get("ok") or []
    bkp = ok[0][2] if ok else ""
    chk(ok and ok[0][1] == src and bkp and Path(bkp).parent == tmp / "_원본" and md5(bkp) == h0,
        "B 원본 바이트는 _원본 으로, 펼친 사진은 원래 이름 자리에", str(ok))
    chk(md5(src) != h0 and not [p for p in tmp.iterdir() if p.name.endswith(".polypix-tmp")], "B 원래 자리는 펼친 사진, 임시 파일 안 남음")
    ex = Image.open(src).getexif()
    chk(ex.get(0x0110) == "TestCam X1" and ex.get(0x0132) == "2025:03:04 05:06:07" and int(ex.get(0x0112, 1) or 1) == 1,
        "B 카메라·촬영일 EXIF 는 남고 방향 태그는 1", str(dict(ex)))

    # C — 바꿔 넣기 실패 → 되돌림
    src2 = photo("doc2.jpg")
    h2 = md5(src2)
    _rep = os.replace

    def bad_replace(a, b):
        if str(a).endswith(".polypix-tmp"):
            raise PermissionError("locked")
        return _rep(a, b)
    os.replace = bad_replace
    got.clear()
    w = pc.PhotoWarpWorker([(src2, 0, PTS)], dest=("replace", None))
    w.done.connect(lambda ok, bad: got.update(ok=ok, bad=bad))
    w.run()
    os.replace = _rep
    chk(got.get("bad") == [src2] and Path(src2).exists() and md5(src2) == h2, "C 바꿔 넣기 실패 — 원본이 제자리로 돌아온다", str(got))
    chk(not (tmp / "_원본" / "doc2.jpg").exists() and not [p for p in tmp.iterdir() if p.name.endswith(".polypix-tmp")],
        "C 백업에 남지 않고 임시 파일도 없다")
    shutil.rmtree(tmp / "_원본", ignore_errors=True)
    got.clear()
    w = pc.PhotoWarpWorker([(src2, 0, [PTS[0], PTS[2], PTS[1], PTS[3]] + PTS[4:])], dest=("replace", None))   # 꼬인 점 — 펴기 실패
    w.done.connect(lambda ok, bad: got.update(ok=ok, bad=bad))
    w.run()
    chk(got.get("bad") == [src2] and md5(src2) == h2 and not (tmp / "_원본").exists(), "C 펴기 전에 실패하면 원본·백업 폴더 모두 그대로")

    # D·E·F — 실제 창
    for i in range(3):
        photo("p%d.jpg" % i)
    big = tmp / "big.jpg"
    im = Image.effect_noise((4000, 3000), 60).convert("RGB")
    im.save(big, "JPEG", quality=90)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump()
    mw.open_folder(tmp)
    bt = mw.bookmark_tree

    def names():
        return sorted(Path(it.data(0, bt.DATA_FILE)).name for it in bt._iter_file_nodes())
    pump(lambda: "big.jpg" in names(), 30)
    chk("doc.jpg" in names() and not any("_원본" in str(it.data(0, bt.DATA_FILE)) for it in bt._iter_file_nodes()),
        "D 사진 모드 목록에 '_원본' 이 안 보인다", str(names()))

    # E — 환경설정
    from viewer.widgets.settings_dialog import SettingsDialog
    try:
        sd = SettingsDialog(mw._prefs, mw)
    except TypeError:
        sd = SettingsDialog(mw._prefs)
    chk(hasattr(sd, "ed_warp_backup") and sd.ed_warp_backup.text() == "", "E 환경설정 — 원본 백업 폴더 칸(기본 비움 = 사진 폴더 안 _원본)")
    from PyQt6.QtWidgets import QFileDialog
    _gd = QFileDialog.getExistingDirectory
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(custom))
    sd._pick_warp_backup()
    QFileDialog.getExistingDirectory = _gd
    rp = sd.result_prefs()
    chk(rp.get("picture", {}).get("warp_backup_dir") == str(custom), "E 고르면 picture.warp_backup_dir 에", str(rp.get("picture")))
    sd.close()
    mw._prefs["picture"]["warp_backup_dir"] = str(custom)
    mw._photo_apply_view_kind()
    gaps = []
    last = [time.monotonic()]

    def beat():
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now
    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat)
    hbig = md5(big)
    BPTS = [(.1, .1), (.9, .12), (.88, .9), (.12, .88)]
    BPTS = BPTS + pw.mids_of(BPTS)
    hb.start(); last[0] = time.monotonic()
    mw._photo_warp({str(big): BPTS, str(tmp / "p1.jpg"): PTS}, ("replace", None))
    pump(lambda: not mw.__dict__.get("_photo_orig_busy"), 60)
    pump(timeout=0.5)
    hb.stop()
    cb = pb.backup_dir_for(big)
    chk(str(cb).startswith(str(custom)) and (cb / "big.jpg").exists() and md5(cb / "big.jpg") == hbig and (cb / "p1.jpg").exists(),
        "E 바꾼 백업 폴더(원래 폴더 구조 아래)로 원본이 간다", str(cb))
    chk(not (tmp / "_원본").exists() or not (tmp / "_원본" / "big.jpg").exists(), "E 그때는 사진 폴더 안 _원본 에 두지 않는다")
    chk(gaps and max(gaps) < 1.0, "F 12 MP 대체 중 메인 하트비트 공백 < 1초", "%.2f" % (max(gaps) if gaps else -1))
    pump(timeout=1.0)
    chk(sorted(names()) == sorted(["big.jpg", "doc.jpg", "doc2.jpg", "p0.jpg", "p1.jpg", "p2.jpg"]),
        "D·E 목록은 그대로(백업은 안 보인다)", str(names()))
    pb.set_custom_dir("")
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    try:
        from viewer import photo_backup as _pb
        _pb.set_custom_dir("")
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(custom, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
