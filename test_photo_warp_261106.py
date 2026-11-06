# -*- coding: utf-8 -*-
"""사진 모양 펴기 — 원근·휜 테두리를 직사각형으로 (사진 보기 SOT §4.43, 261106-6 사용자 지시).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 펴기 계산 — 원근 사각형은 원근 변환, 가운데가 움푹 들어간 종이는 변 가운데 점으로 곧게(곧은 점만이면 바깥이 남는다)
B. 자동 테두리 어림은 없다(261106-11 사용자 지시 '쓸만하지 않아') — 모듈·워커·[테두리 찾기] 모두
C. 점 끌기 화면 — 꼭짓점을 옮기면 곧은 변의 가운데 점이 따라가고, 옮긴 가운데 점은 그대로, 꼬이는 끌기는 받지 않는다
D. 크롭 창 — 옵션 '모양 펴기' 를 켜면 점 화면(처음 점 = 크롭 박스 — 크롭이 없으면 사진 네 귀), 여백 칸은 꺼짐.
   ❯ 로 넘긴 사진은 **꺼진 채**(261106-11), 켜고 점을 놓으면 그 사진도 펼친다,
   [확인] = 켠 사진마다 '<이름>_펼침' 새 사진(배경), 원본·크롭 그대로, 책갈피창에 새 줄
E. [취소] 면 아무것도 만들지 않는다 · 펴는 동안 메인 하트비트 공백 < 0.5초(응답성 SOT §5)
"""
import os, sys, tempfile, shutil, time, hashlib
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
QCoreApplication.setApplicationName("polypdf_photo_warp_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 모양 펴기", echo=False)   # 마스터 §14.7.2 의 6
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


def dark_share(im, y):
    g = im.convert("L")
    row = [g.getpixel((x, y)) for x in range(g.size[0])]
    return sum(v < 128 for v in row) / len(row)


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_warp_"))
try:
    from PIL import Image, ImageDraw
    from viewer import photo_warp as pw

    W, H = 1200, 900
    QUAD = [(220, 120), (1010, 180), (1090, 820), (140, 760)]
    persp = Image.new("RGB", (W, H), (40, 50, 60))
    ImageDraw.Draw(persp).polygon(QUAD, fill=(245, 245, 240))
    curved = Image.new("RGB", (W, H), (30, 30, 30))
    top = [(200 + i * 8, 150 + 60 * (1 - ((i - 50) / 50.0) ** 2)) for i in range(101)]
    bot = [(200 + i * 8, 780 - 60 * (1 - ((i - 50) / 50.0) ** 2)) for i in range(101)]
    ImageDraw.Draw(curved).polygon(top + bot[::-1], fill=(250, 250, 250))

    QPTS = [(x / W, y / H) for x, y in QUAD]
    QPTS = QPTS + pw.mids_of(QPTS)
    CPTS = [(200 / W, 150 / H), (1000 / W, 150 / H), (1000 / W, 780 / H), (200 / W, 780 / H),
            (600 / W, 210 / H), (1000 / W, 465 / H), (600 / W, 720 / H), (200 / W, 465 / H)]

    # A
    pts = [(x / W, y / H) for x, y in QUAD]
    pts = pts + pw.mids_of(pts)
    out = pw.unwarp(persp, pts)
    chk(max(dark_share(out, 2), dark_share(out, out.size[1] - 3), dark_share(out, out.size[1] // 2)) < 0.02,
        "A 원근 사각형 → 펼친 그림에 바탕이 남지 않는다", str(out.size))
    cp = [(200 / W, 150 / H), (1000 / W, 150 / H), (1000 / W, 780 / H), (200 / W, 780 / H)]
    cpts = cp + [(600 / W, 210 / H), (1000 / W, 465 / H), (600 / W, 720 / H), (200 / W, 465 / H)]
    chk(not pw.is_straight(cpts) and dark_share(pw.unwarp(curved, cpts), 3) < 0.02,
        "A 움푹 들어간 종이 — 변 가운데 점으로 위 가장자리까지 곧게")
    chk(dark_share(pw.unwarp(curved, cp + pw.mids_of(cp)), 3) > 0.5, "A (대조) 곧은 점만이면 위 가운데에 바탕이 남는다")
    try:
        pw.unwarp(persp, [pts[0], pts[2], pts[1], pts[3]] + pts[4:])
        chk(False, "A 꼬인 꼭짓점은 펴지 않는다(ValueError)")
    except ValueError:
        chk(True, "A 꼬인 꼭짓점은 펴지 않는다(ValueError)")
    sz = pw.out_size(pts, W, H)
    chk(sz[0] * sz[1] <= W * H and 700 < sz[0] < 950 and 550 < sz[1] < 700, "A 출력 크기 = 변 길이 평균, 원본 넓이 이하", str(sz))

    # B
    import viewer.photo_controller as _pc
    import viewer.widgets.photo_crop_dialog as _pcd
    chk(not hasattr(pw, "detect") and not hasattr(_pc, "PhotoCropLoadWorker") and not hasattr(_pc, "warp_detect_qimage"),
        "B 자동 테두리 어림이 없다(모듈·워커)")
    chk(not hasattr(_pcd.PhotoCropDialog, "_on_detect"), "B [테두리 찾기] 가 없다")

    # C
    from viewer.widgets.photo_warp_canvas import WarpCanvas
    cv = WarpCanvas()
    cv.set_points(pw.default_points(0.1))
    cv.move_point(0, (0.2, 0.15))
    p = cv.points()
    chk(abs(p[4][0] - (0.2 + 0.9) / 2) < 1e-6 and abs(p[4][1] - (0.15 + 0.1) / 2) < 1e-6, "C 꼭짓점을 옮기면 곧은 변 가운데 점이 따라간다", str(p[4]))
    cv.move_point(4, (0.55, 0.3))
    cv.move_point(1, (0.85, 0.12))
    chk(cv.points()[4] == (0.55, 0.3), "C 옮긴 가운데 점은 꼭짓점을 옮겨도 그대로")
    before = cv.points()
    cv.move_point(0, (0.95, 0.95))                    # 꼬인다
    chk(cv.points() == before, "C 꼬이는 끌기는 받지 않는다")

    # D — 실제 창
    persp.save(tmp / "a_doc.jpg", "JPEG", quality=92)
    curved.save(tmp / "b_book.jpg", "JPEG", quality=92)
    big = Image.new("RGB", (4000, 3000), (40, 50, 60))
    ImageDraw.Draw(big).polygon([(x * 10 / 3, y * 10 / 3) for x, y in QUAD], fill=(245, 245, 240))
    big.save(tmp / "c_big.jpg", "JPEG", quality=90)
    srcs = [str(tmp / n) for n in ("a_doc.jpg", "b_book.jpg", "c_big.jpg")]
    sums = {p: md5(p) for p in srcs}

    from viewer.app import MainWindow
    from viewer.widgets.photo_crop_dialog import PhotoCropDialog
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump()
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3), "사진 3장 목록")
    a, b, c = srcs
    mw._on_bookmark_activated(a, 0); pump(timeout=0.8)
    st = mw._ensure_page_meta_store()
    crops_before = {p: st.photo_crop(p) for p in srcs}
    _exec = PhotoCropDialog.exec
    seen = {}

    def go(dlg, i):
        dlg._go(i)
        return pump(lambda: dlg.index() == i and not dlg._loading, timeout=10)

    def fake_exec(self):
        P = mw._photo_crop_paths
        seen["stack0"] = self.stack.currentWidget() is self.canvas
        self.chk_warp.setChecked(True)
        seen["on"] = (self.stack.currentWidget() is self.warp, all(not sp.isEnabled() for sp in self.spins))
        seen["a_pts"] = self.warp.points()
        self.warp.set_points(QPTS)                    # 사용자가 꼭짓점을 종이에 맞춘다
        seen["go_b"] = go(self, P.index(b))
        seen["b_on"] = self.chk_warp.isChecked()
        self.chk_warp.setChecked(True)
        self.warp.set_points(CPTS)
        seen["go_c"] = go(self, P.index(c))
        seen["c_on"] = self.chk_warp.isChecked()
        self.chk_warp.setChecked(False)               # c 는 펴지 않는다
        return QDialog.DialogCode.Accepted
    PhotoCropDialog.exec = fake_exec
    from PyQt6.QtWidgets import QMessageBox, QFileDialog
    _mb_exec = QMessageBox.exec
    asked = {}
    pick = {"text": "저장"}

    def fake_box(self):                                # 묻는 창 — 단추 글로 고른다(실제 단추를 누른다)
        asked["buttons"] = [b.text() for b in self.buttons()]
        asked["default"] = self.defaultButton().text() if self.defaultButton() else ""
        for b in self.buttons():
            if b.text() == pick["text"] or (pick["text"] == "cancel" and self.buttonRole(b) == QMessageBox.ButtonRole.RejectRole):
                b.click()
                break
        return 0
    QMessageBox.exec = fake_box
    gaps = []
    last = [time.monotonic()]

    def beat():
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(beat)
    mw._photo_crop_dialog(a)
    pump(lambda: "go_c" in seen, timeout=20)
    hb.start(); last[0] = time.monotonic()
    done = pump(lambda: not mw.__dict__.get("_photo_warp_busy") and "go_c" in seen, timeout=30)
    pump(timeout=0.6)
    hb.stop()
    PhotoCropDialog.exec = _exec
    chk({"저장", "다른 이름으로 저장...", "다른 폴더에 저장..."} <= set(asked.get("buttons", [])) and len(asked.get("buttons", [])) == 4
        and asked.get("default") == "저장",
        "D [확인] 이면 묻는다 — [저장]·[다른 이름으로 저장]·[다른 폴더에 저장](기본 [저장])", str(asked))
    chk(seen.get("stack0"), "D 처음엔 크롭 화면(옵션 꺼짐)")
    chk(seen.get("on") == (True, True), "D '모양 펴기' 를 켜면 점 화면 · 여백 칸 꺼짐", str(seen.get("on")))
    ap = seen.get("a_pts") or []
    chk(ap and all(abs(g[0] - q[0]) < 1e-6 and abs(g[1] - q[1]) < 1e-6 for g, q in zip(ap, pw.default_points())),
        "D 처음 점 = 크롭 박스(크롭이 없으면 사진 네 귀) — 어림 아님", str(ap[:4]))
    chk(seen.get("go_b") and seen.get("b_on") is False and seen.get("c_on") is False,
        "D ❯ 로 넘긴 사진은 모양 펴기가 꺼진 채 시작(261106-11)", str((seen.get("b_on"), seen.get("c_on"))))
    outs = sorted(p.name for p in tmp.iterdir() if "_펼침" in p.name)
    chk(done and outs == ["a_doc_펼침.jpg", "b_book_펼침.jpg"], "D [확인] — 켠 사진마다 '<이름>_펼침' 새 사진, 끈 사진은 없음", str(outs))
    if (tmp / "a_doc_펼침.jpg").exists():
        oa = Image.open(tmp / "a_doc_펼침.jpg")
        chk(max(dark_share(oa, 2), dark_share(oa, oa.size[1] - 3)) < 0.05, "D 펼친 사진에 바탕이 거의 남지 않는다", str(oa.size))
    if (tmp / "b_book_펼침.jpg").exists():
        ob = Image.open(tmp / "b_book_펼침.jpg")
        chk(dark_share(ob, 3) < 0.05, "D 움푹 들어간 종이도 곧게", str(dark_share(ob, 3)))
    chk(all(md5(p) == sums[p] for p in srcs), "D 원본 사진은 그대로")
    chk({p: st.photo_crop(p) for p in srcs} == crops_before, "D 크롭(사이드카)은 그대로")
    names = [Path(bt_p).name for bt_p in (it.data(0, bt.DATA_FILE) for it in bt._iter_file_nodes())]
    chk("a_doc_펼침.jpg" in names and "b_book_펼침.jpg" in names, "D 책갈피창에 새 줄", str(names))

    # F — 다른 폴더·다른 이름·묻는 창 취소
    other = tmp.parent / (tmp.name + "_out")
    other.mkdir(exist_ok=True)

    def fake_one(self):
        self.chk_warp.setChecked(True)
        self.warp.set_points(QPTS)
        return QDialog.DialogCode.Accepted
    PhotoCropDialog.exec = fake_one
    _gd = QFileDialog.getExistingDirectory
    _gs = QFileDialog.getSaveFileName
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(other))
    pick["text"] = "다른 폴더에 저장..."
    mw._photo_crop_dialog(a)
    pump(lambda: not mw.__dict__.get("_photo_crop_busy") and not mw.__dict__.get("_photo_warp_busy"), timeout=20)
    pump(lambda: (other / "a_doc_펼침.jpg").exists(), timeout=20)
    chk((other / "a_doc_펼침.jpg").exists(), "F [다른 폴더에 저장] — 고른 폴더에 '<이름>_펼침'", str(list(other.iterdir())))
    names = [Path(it.data(0, bt.DATA_FILE)).name for it in bt._iter_file_nodes()]
    chk(names.count("a_doc_펼침.jpg") == 1 and "a_doc_펼침(2).jpg" not in names, "F 다른 폴더의 것은 보고 있는 목록에 끼우지 않는다", str(names))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(tmp / "내가고른.jpg"), ""))
    pick["text"] = "다른 이름으로 저장..."
    mw._photo_crop_dialog(a)
    pump(lambda: not mw.__dict__.get("_photo_crop_busy") and not mw.__dict__.get("_photo_warp_busy"), timeout=20)
    pump(lambda: (tmp / "내가고른.jpg").exists(), timeout=20)
    chk((tmp / "내가고른.jpg").exists(), "F [다른 이름으로 저장] — 저장 창에서 고른 이름")
    n0 = len(list(tmp.iterdir()))
    st.set_photo_crop(b, None)
    pick["text"] = "cancel"

    def fake_both(self):                               # 크롭도 바꾸고 펴기도 켠 채 [확인] → 묻는 창 [취소]
        P = mw._photo_crop_paths
        self.spins[0].setValue(25)
        go(self, P.index(b))
        self.chk_warp.setChecked(True)
        self.warp.set_points(CPTS)
        return QDialog.DialogCode.Accepted
    PhotoCropDialog.exec = fake_both
    mw._photo_crop_dialog(c)
    pump(lambda: not mw.__dict__.get("_photo_crop_busy"), timeout=20)
    pump(timeout=0.8)
    chk(len(list(tmp.iterdir())) == n0 and st.photo_crop(c) == crops_before[c], "F 묻는 창 [취소] — 펴기도 크롭도 남기지 않는다")
    QFileDialog.getExistingDirectory, QFileDialog.getSaveFileName = _gd, _gs
    pick["text"] = "저장"

    # G — 오른쪽 결과 미리보기(261106-6 사용자 지시 '일반 크롭이나 펼칠 경우의 모습을 우측 창에')
    from PyQt6.QtGui import QImage
    qa = QImage(str(tmp / "a_doc.jpg"))
    dlg = PhotoCropDialog(qa, [0, 0, 0, 0], parent=mw)
    dlg.show(); pump(timeout=0.3)
    r0 = dlg.result_image()
    dlg.spins[0].setValue(50.0)
    pump(timeout=0.3)
    r1 = dlg.result_image()
    chk(r0 is not None and r1 is not None and abs(r1.size[1] / r0.size[1] - 0.5) < 0.03,
        "G 일반 크롭 — 오른쪽에 자른 모양(위 50% 를 자르면 높이 절반)", str((r0 and r0.size, r1 and r1.size)))
    chk(dlg.result.pixmap() is not None and not dlg.result.pixmap().isNull(), "G 미리보기 칸에 그림이 있다")
    dlg.spins[0].setValue(0.0)
    dlg.chk_warp.setChecked(True)
    dlg._set_warp_points(QPTS); pump(timeout=0.3)
    rw = dlg.result_image()
    chk(rw is not None and max(dark_share(rw, 1), dark_share(rw, rw.size[1] - 2)) < 0.1, "G 펴기 — 오른쪽에 펼친 모양(바탕 없음)",
        str(rw and rw.size))
    before_px = dlg.result.pixmap().cacheKey()
    dlg.warp.move_point(0, (0.05, 0.05)); pump(timeout=0.4)
    chk(dlg.result.pixmap().cacheKey() != before_px, "G 점을 끌면 미리보기가 따라 바뀐다")
    t0 = time.perf_counter()
    for _ in range(5):
        dlg._update_result()
    chk((time.perf_counter() - t0) / 5 < 0.15, "G 미리보기 한 번 < 0.15초(줄인 그림)", "%.3f" % ((time.perf_counter() - t0) / 5))
    dlg.reject()
    QMessageBox.exec = _mb_exec

    # E
    def fake_cancel(self):
        self.chk_warp.setChecked(True)
        return QDialog.DialogCode.Rejected
    PhotoCropDialog.exec = fake_cancel
    n0 = len(list(tmp.iterdir()))
    mw._photo_crop_dialog(c)
    pump(lambda: not mw.__dict__.get("_photo_crop_busy"), timeout=20)
    pump(timeout=0.8)
    PhotoCropDialog.exec = _exec
    chk(len(list(tmp.iterdir())) == n0, "E [취소] 면 새 사진을 만들지 않는다")

    # E — 큰 사진(12 MP) 펴는 동안 메인 하트비트
    gaps.clear()
    hb.start(); last[0] = time.monotonic()
    mw._photo_warp({c: [(x / W, y / H) for x, y in QUAD] + pw.mids_of([(x / W, y / H) for x, y in QUAD])})
    pump(lambda: not mw.__dict__.get("_photo_warp_busy"), timeout=60)
    hb.stop()
    chk((tmp / "c_big_펼침.jpg").exists(), "E 12 MP 사진도 펼친다")
    chk(gaps and max(gaps) < 0.5, "E 펴는 동안 메인 하트비트 공백 < 0.5초", "%.2f" % (max(gaps) if gaps else -1))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(str(tmp) + "_out", ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
