# -*- coding: utf-8 -*-
"""사진 '원본으로 되돌리기' (사진 보기 SOT §4.43, 261106-18 사용자 승인 '넣기').

실제 MainWindow·실제 워커(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 휴지통은 검사용 폴더로 바꿔 친다
(실제 휴지통에 검사 파일을 넣지 않는다).
A. 백업 찾기 — 없으면 없음, 여럿('name'·'name (2)')이면 가장 최근(번호 큰 것), HEIC → .jpg 로 바뀐 사진도 짝(이름만으로)
B. 되돌리기 — 지금 파일은 **제 이름 그대로** 휴지통, 원본이 원래 이름 자리로(바이트 그대로), 백업 자리에서 빠짐
C. 휴지통이 실패하면 아무것도 바뀌지 않는다(지금 파일·백업 그대로)
D. 실제 창 — 펴기 [저장] 으로 바꾼 사진에만 우클릭 '원본으로 되돌리기' 가 보이고, 고른 여러 장 한꺼번에, 확인 창 [되돌리기] →
   원본 바이트·사이드카 기록 지움·책갈피창 목록 그대로, 고정 백업 폴더(환경설정)에서도
"""
import os, sys, tempfile, shutil, time, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_restore_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "원본으로 되돌리기", echo=False)
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_restore_"))
trash = Path(str(tmp) + "_trash"); trash.mkdir()
custom = Path(str(tmp) + "_bk")
try:
    import send2trash as _s2t
    _real = _s2t.send2trash
    trashed = []

    def fake_trash(p):
        trashed.append(Path(p).name)
        shutil.move(str(p), str(trash / Path(p).name))
    _s2t.send2trash = fake_trash
    from PIL import Image, ImageDraw
    from viewer import photo_backup as pb, photo_warp as pw
    import viewer.photo_controller as pc
    pb.set_custom_dir("")

    def photo(name, col=(40, 50, 60)):
        im = Image.new("RGB", (900, 700), col)
        ImageDraw.Draw(im).polygon([(160, 90), (760, 140), (800, 620), (110, 590)], fill=(245, 245, 240))
        im.save(tmp / name, "JPEG", quality=92)
        return str(tmp / name)

    # A
    a = photo("a.jpg")
    chk(pb.find_backup(a) is None, "A 백업이 없으면 없음")
    bdir = tmp / "_원본"; bdir.mkdir()
    (bdir / "a.jpg").write_bytes(b"v1"); (bdir / "a (2).jpg").write_bytes(b"v2"); (bdir / "ab.jpg").write_bytes(b"x")
    chk(Path(pb.find_backup(a) or "").name == "a (2).jpg", "A 여럿이면 가장 최근(번호 큰 것)", str(pb.find_backup(a)))
    (bdir / "h.HEIC").write_bytes(b"heic")
    chk(Path(pb.find_backup(tmp / "h.jpg") or "").name == "h.HEIC", "A HEIC → .jpg 로 바뀐 사진도 이름으로 짝")
    chk(pb.original_name(bdir / "a (2).jpg") == "a.jpg", "A 원래 이름 = '(n)' 뺀 이름")
    shutil.rmtree(bdir); os.remove(a)

    # B·C — 실제 워커로 대체한 뒤 되돌리기
    PTS = [(160 / 900, 90 / 700), (760 / 900, 140 / 700), (800 / 900, 620 / 700), (110 / 900, 590 / 700)]
    PTS = PTS + pw.mids_of(PTS)

    def replace(p):
        w = pc.PhotoWarpWorker([(p, 0, PTS)], dest=("replace", None))
        got = {}
        w.done.connect(lambda ok, bad, g=got: g.update(ok=ok))
        w.run()
        return got.get("ok")
    b = photo("b.jpg"); hb = md5(b)
    replace(b)
    hw = md5(b)
    rw = pc.PhotoRestoreWorker([(b, pb.find_backup(b))])
    got = {}
    rw.done.connect(lambda ok, bad: got.update(ok=ok, bad=bad))
    rw.run()
    chk(got.get("ok") == [(b, b)] and md5(b) == hb, "B 원본이 원래 이름 자리로(바이트 그대로)", str(got))
    chk(trashed == ["b.jpg"] and md5(trash / "b.jpg") == hw, "B 바꾼 파일은 제 이름 그대로 휴지통으로", str(trashed))
    chk(not list((tmp / "_원본").iterdir()) and not [x for x in tmp.iterdir() if x.name.startswith("~")],
        "B 백업 자리에서 빠지고 임시 파일도 없다")
    hj = photo("h.jpg")                                # HEIC 를 .jpg 로 바꿔 둔 꼴 — 백업은 h.HEIC
    (tmp / "_원본" / "h.HEIC").write_bytes(b"heic-bytes")
    trashed.clear()
    got.clear()
    rw = pc.PhotoRestoreWorker([(hj, pb.find_backup(hj))])
    rw.done.connect(lambda ok, bad: got.update(ok=ok, bad=bad))
    rw.run()
    chk(got.get("ok") == [(hj, str(tmp / "h.HEIC"))] and (tmp / "h.HEIC").read_bytes() == b"heic-bytes"
        and not Path(hj).exists() and trashed == ["h.jpg"], "B HEIC 짝 — h.jpg 는 휴지통, h.HEIC 가 제자리로", str(got))
    os.remove(tmp / "h.HEIC")
    c = photo("c.jpg"); hc = md5(c)
    replace(c); hcw = md5(c)

    def bad_trash(p):
        raise OSError("no recycle bin")
    _s2t.send2trash = bad_trash
    got.clear()
    rw = pc.PhotoRestoreWorker([(c, pb.find_backup(c))])
    rw.done.connect(lambda ok, bad: got.update(ok=ok, bad=bad))
    rw.run()
    _s2t.send2trash = fake_trash
    chk(got.get("bad") == [c] and md5(c) == hcw and md5(tmp / "_원본" / "c.jpg") == hc
        and not [x for x in tmp.iterdir() if x.name.startswith("~")], "C 휴지통 실패 — 지금 파일·백업 그대로", str(got))

    # D — 실제 창
    d1, d2 = photo("d1.jpg", (60, 40, 40)), photo("d2.jpg", (40, 60, 40))
    hd1, hd2 = md5(d1), md5(d2)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump()
    mw.open_folder(tmp)
    bt = mw.bookmark_tree
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 4)
    mw._photo_warp({d1: PTS, d2: PTS}, ("replace", None))
    pump(lambda: not mw.__dict__.get("_photo_warp_busy"), 30); pump(timeout=0.5)
    st = mw._ensure_page_meta_store()
    st.set_photo_crop(d1, (0.0, 0.1, 1.0, 1.0)); st.save()
    m = QMenu()
    chk(mw._photo_restore_action(m, [b]) is None, "D 백업이 없는 사진에는 '원본으로 되돌리기' 가 없다")
    act = mw._photo_restore_action(m, [d1, d2, b])
    chk(act is not None and "2장" in act.text(), "D 고른 여러 장 — 백업이 있는 2장만 '원본으로 되돌리기 (2장)...'", act.text() if act else "")
    _mb = QMessageBox.exec
    asked = {}

    def fake_box(self):
        asked["text"] = self.text()
        for bb in self.buttons():
            if bb.text() == "되돌리기":
                bb.click()
                break
        return 0
    QMessageBox.exec = fake_box
    trashed.clear()
    mw._photo_restore([d1, d2, b])
    pump(lambda: not mw.__dict__.get("_photo_restore_busy"), 30); pump(timeout=0.5)
    QMessageBox.exec = _mb
    chk("휴지통" in asked.get("text", ""), "D 확인 창 — 지금 파일은 휴지통으로 간다고 알린다")
    chk(md5(d1) == hd1 and md5(d2) == hd2 and sorted(trashed) == ["d1.jpg", "d2.jpg"], "D 2장 모두 원본으로(바이트 그대로), 바꾼 파일은 휴지통", str(trashed))
    chk(st.photo_crop(d1) is None, "D 되돌린 사진의 사이드카 기록(크롭)은 지운다")
    names = sorted(Path(it.data(0, bt.DATA_FILE)).name for it in bt._iter_file_nodes())
    chk("d1.jpg" in names and "d2.jpg" in names and not any("_원본" in n for n in names), "D 책갈피창 목록 그대로", str(names))
    # 고정 백업 폴더
    mw._prefs["picture"]["warp_backup_dir"] = str(custom)
    mw._photo_apply_view_kind()
    mw._photo_warp({d1: PTS}, ("replace", None))
    pump(lambda: not mw.__dict__.get("_photo_warp_busy"), 30); pump(timeout=0.5)
    chk(pb.find_backup(d1) and str(pb.find_backup(d1)).startswith(str(custom)), "D 고정 백업 폴더에서도 찾는다", str(pb.find_backup(d1)))
    QMessageBox.exec = fake_box
    mw._photo_restore([d1])
    pump(lambda: not mw.__dict__.get("_photo_restore_busy"), 30); pump(timeout=0.5)
    QMessageBox.exec = _mb
    chk(md5(d1) == hd1, "D 고정 백업 폴더에서 되돌린다")
    pb.set_custom_dir("")
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    try:
        import send2trash as _s2t2
        _s2t2.send2trash = _real
        from viewer import photo_backup as _pb
        _pb.set_custom_dir("")
    except Exception:
        pass
    for d in (tmp, trash, custom):
        shutil.rmtree(d, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
