# -*- coding: utf-8 -*-
"""사진 보기 크롭 — 원본 그대로, 보이는 그대로 다 (사진 보기 SOT §4.40, 261105-4 사용자 결정).

시험 사진 400×300 — 왼위 빨강·오른위 초록·왼아래 파랑·오른아래 흰색. 크롭 = 오른위 1/4(회전 0 판 (0.5, 0, 1, 0.5)).
A. 계산 — 회전 판 오가기·꾸밈 비율 오가기·OCR 낱말·방향 저장 뒤
B. 본문 — 쪽 크기가 자른 영역, 그린 그림이 초록. 원본 사진 파일은 바이트 그대로. 사이드카 `photo_crop` 이 디스크에. 보기 회전 90° 와 함께
C. 꾸밈 — 자른 쪽에 그린 선은 자르지 않은 회전 0 판으로 남고, 읽으면 다시 자른 쪽 좌표
D. 내보내기 — 사진 → PDF(굽기 길: 쪽 크기·바깥을 실제로 지움)·평탄화·공유용 사본·사진 복사가 자른 모양
E. 크롭 창 — 칸 값·한계·[크롭 해제] / 편집 모드 크롭 단추 길이 사진이면 사진 크롭 창으로
F. 이름 변경 — 크롭이 새 이름을 따라온다(마스터 §4.7.14 `rename_file`)
실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3).
"""
import os
import sys
import time
import shutil
import tempfile
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def near(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


app = QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_crop_%d" % os.getpid())
import modal_guard
modal_guard.install(echo=False)
from PIL import Image

GREEN, RED = (0, 200, 0), (220, 0, 0)


def is_green(px):
    return px[1] > 150 and px[0] < 80 and px[2] < 80


# ── A. 계산 ─────────────────────────────────────────────
try:
    from viewer import photo_crop as PC
except Exception as e:                       # 수정 전 — 모듈이 없다
    PC = None
    chk(False, "A photo_crop 모듈", repr(e))
if PC is not None:
    b0 = (0.1, 0.2, 0.6, 0.9)
    chk(all(near(PC.to_rot0(PC.to_view(b0, r), r), b0) for r in (0, 90, 180, 270)), "A 회전 판 오가기(0·90·180·270)")
    chk(near(PC.to_view((0.5, 0.0, 1.0, 0.5), 90), (0.5, 0.5, 1.0, 1.0)), "A 오른위 1/4 → 90° 보기에서 오른아래")
    st0 = [{"points": [[0.2, 0.3], [0.9, 0.95]], "width": 2},
           {"shape": "rect", "rect": [0.1, 0.1, 0.3, 0.4], "rot": 0},
           {"shape": "circle", "cx": 0.5, "cy": 0.5, "r": 0.1, "rect": [0.4, 0.4, 0.6, 0.6]},
           {"hl": True, "bands": [[0.1, 0.5, 0.3, 0.02]]}]
    bv = (0.1, 0.2, 0.6, 0.9)
    back = PC.map_strokes(PC.map_strokes(st0, bv), bv, back=True)
    ok = near(back[0]["points"][1], st0[0]["points"][1]) and near(back[1]["rect"], st0[1]["rect"]) \
        and abs(back[2]["r"] - 0.1) < 1e-9 and near(back[3]["bands"][0], st0[3]["bands"][0])
    chk(ok, "A 꾸밈 비율 — 자른 쪽으로 갔다 되돌아오면 같다", str(back))
    im0 = [{"rect": [0.2, 0.3, 0.1, 0.1]}]
    chk(near(PC.map_images(PC.map_images(im0, bv), bv, back=True)[0]["rect"], im0[0]["rect"]), "A 넣은 그림 비율 오가기")
    words = [{"x0": 210, "y0": 10, "x1": 250, "y1": 30, "text": "in"}, {"x0": 10, "y0": 10, "x1": 50, "y1": 30, "text": "out"}]
    got = PC.words_view(words, (0.5, 0.0, 1.0, 0.5), 400, 300)
    chk(len(got) == 1 and got[0]["text"] == "in" and abs(got[0]["x0"] - 10) < 1e-9, "A OCR 낱말 — 보이는 것만, 자른 쪽 pt", str(got))
    chk(PC.norm((0, 0, 1, 1)) is None and PC.norm((0.2, 0.2, 0.2, 0.9)) is None, "A 쪽 전체·넓이 없는 상자는 자르지 않음")
    chk(near(PC.after_orient_save((0.5, 0.0, 1.0, 0.5), 90), (0.5, 0.5, 1.0, 1.0)), "A 방향 저장 뒤 — 새 회전 0 판 상자")

# ── B~F. 실제 앱 ────────────────────────────────────────
tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_crop_"))
try:
    pix = tmp / "pix"
    pix.mkdir()
    src = pix / "q.png"
    im = Image.new("RGB", (400, 300), (255, 255, 255))
    for (x0, y0, c) in ((0, 0, RED), (200, 0, GREEN), (0, 150, (0, 0, 220))):
        im.paste(Image.new("RGB", (200, 150), c), (x0, y0))
    im.save(src, "PNG")
    orig = src.read_bytes()
    from viewer import settings_store
    settings_store.save({"preferences": {"picture": {"mode": "photo", "view_kind": "mixed"}, "startup_mode": "none"}})
    from viewer.app import MainWindow
    win = MainWindow()
    win._skip_save_on_close = True
    win.show()

    def spin(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
    spin(1)
    win.open_folder(pix)
    spin(2)
    win._on_bookmark_activated(str(src), 0)
    spin(1)
    BOX = (0.5, 0.0, 1.0, 0.5)
    ok_set = bool(getattr(win, "_photo_set_crop", None)) and win._photo_set_crop(str(src), BOX)
    chk(bool(ok_set), "B 크롭을 정한다(_photo_set_crop)")
    if ok_set:
        from viewer import photo_doc
        spin(0.5)
        mv = win.main_view
        doc = mv._doc
        chk(tuple(doc.size) == (200, 150), "B 본문 쪽 크기 = 자른 영역", str(doc.size))
        photo_doc.decoded(str(src), 2000)
        rp = doc.render(0, dpi=72, cache=False)
        mid = rp.samples[((rp.height // 2) * rp.width + rp.width // 2) * 3:][:3]
        chk(is_green(tuple(mid)), "B 그린 그림 = 자른 곳(초록)", str(tuple(mid)))
        chk(src.read_bytes() == orig, "B 원본 사진은 바이트 그대로")
        side = (pix / "page_meta.json")
        chk(side.exists() and "photo_crop" in side.read_text(encoding="utf-8"), "B 사이드카에 photo_crop")
        win._photo_rotate(absolute=90)
        spin(0.3)
        chk(tuple(mv._doc.size) == (150, 200), "B 보기 회전 90° 와 함께 — 쪽 크기", str(mv._doc.size))
        rp = mv._doc.render(0, dpi=72, cache=False)
        mid = rp.samples[((rp.height // 2) * rp.width + rp.width // 2) * 3:][:3]
        chk(is_green(tuple(mid)), "B 돌려도 같은 곳(초록)", str(tuple(mid)))
        win._photo_rotate(absolute=0)
        spin(0.3)

        # C. 꾸밈
        st = win._ensure_page_meta_store()
        win._set_drawings(str(src), 0, [{"points": [[0.5, 0.5], [1.0, 1.0]], "width": 2, "color": "#ff0000"}])
        raw = st.get_drawings(str(src), 0)
        chk(bool(raw) and near(raw[0]["points"][0], (0.75, 0.25)) and near(raw[0]["points"][1], (1.0, 0.5)),
            "C 자른 쪽에 그린 선 → 자르지 않은 회전 0 판으로 남는다", str(raw))
        shown = win._drawings_for(str(src), 0)
        chk(bool(shown) and near(shown[0]["points"][0], (0.5, 0.5)), "C 읽으면 자른 쪽 좌표", str(shown))
        st.set_drawings(str(src), 0, [])

        # D. 내보내기
        import fitz
        out_pdf = str(tmp / "out.pdf")
        win._images_to_pdf([str(src)], out_pdf)
        baked = win._photo_bake_pdf(out_pdf, [str(src)])
        d = fitz.open(baked)
        pg = d[0]
        chk(abs(pg.rect.width - 200) < 1 and abs(pg.rect.height - 150) < 1, "D 사진 → PDF — 쪽 크기 = 자른 영역", str(pg.rect))
        mb = pg.mediabox
        chk(abs(mb.width - 200) < 1 and abs(mb.height - 150) < 1, "D 사진 → PDF — 바깥을 실제로 지움(MediaBox 도 자름)", str(mb))
        pm = pg.get_pixmap(dpi=72)
        c = pm.pixel(pm.width // 2, pm.height // 2)
        chk(is_green(c), "D 사진 → PDF — 가운데 초록", str(c))
        d.close()
        from viewer.photo_controller import PhotoFlattenWorker, PhotoShareWorker, PhotoCopyWorker
        got = {}
        w = PhotoFlattenWorker(str(src), 0, None, BOX)
        w.done.connect(lambda a, b, why: got.setdefault("flat", (b, why)))
        w.run()
        fo = got.get("flat", ("", ""))[0]
        if fo and os.path.exists(fo):
            with Image.open(fo) as fi:
                chk(fi.size == (200, 150) and is_green(fi.convert("RGB").getpixel((100, 75))), "D 평탄화 — 자른 모양", str(fi.size))
            os.remove(fo)
        else:
            chk(False, "D 평탄화 — 파일", str(got))
        sd = tmp / "share"
        w = PhotoShareWorker([str(src)], "gps", {str(src): 0}, dest=("dir", str(sd)), crops={str(src): BOX})
        w.done.connect(lambda ok, bad: got.setdefault("share", ok))
        w.run()
        so = (got.get("share") or [(None, "")])[0][1]
        if so and os.path.exists(so):
            with Image.open(so) as si:
                chk(si.size == (200, 150) and is_green(si.convert("RGB").getpixel((100, 75))), "D 공유용 사본 — 자른 모양", str(si.size))
        else:
            chk(False, "D 공유용 사본 — 파일", str(got))
        w = PhotoCopyWorker(str(src), 0, crop=BOX)
        w.done.connect(lambda p, img: got.setdefault("copy", img))
        w.run()
        ci = got.get("copy")
        chk(ci is not None and (ci.width(), ci.height()) == (200, 150), "D 사진 복사 — 자른 모양",
            str((ci.width(), ci.height()) if ci is not None else None))
        chk(win._photo_needs_bake(str(src))[2] is not None, "D 굽기 판정에 크롭이 든다(인쇄·이미지→PDF 창 같은 길)")

        # E. 크롭 창
        from PyQt6.QtGui import QImage
        from viewer.widgets.photo_crop_dialog import PhotoCropDialog
        dlg = PhotoCropDialog(QImage(100, 80, QImage.Format.Format_RGB888), [0, 0, 0, 0])
        dlg.spins[0].setValue(10)
        chk(dlg.margins() == [10.0, 0.0, 0.0, 0.0], "E 칸 값 → 여백", str(dlg.margins()))
        dlg.spins[0].setValue(60)
        dlg.spins[1].setValue(60)
        m = dlg.margins()
        chk(m[0] + m[1] <= 95.0 + 1e-6, "E 마주 보는 두 변 합 ≤ 95%(PDF 크롭과 같은 한계)", str(m))
        dlg._on_reset()
        chk(dlg.margins() is None, "E [크롭 해제] → 자르지 않음")
        from PyQt6.QtWidgets import QDialog
        _exec = PhotoCropDialog.exec

        def fake_exec(self):                    # 사용자가 아래 50%·오른쪽 50% 를 넣고 [확인]
            self.spins[1].setValue(50)
            self.spins[3].setValue(50)
            return QDialog.DialogCode.Accepted
        PhotoCropDialog.exec = fake_exec
        win._photo_set_crop(str(src), None)     # 창은 지금 크롭에서 시작한다 — 빈 데서 시작
        win._photo_rotate(absolute=90)         # 보기 회전 90° 에서 고른 여백 → 회전 0 판으로 남는다
        spin(0.3)
        win._photo_crop_ready(str(src), QImage(80, 100, QImage.Format.Format_RGB888))
        PhotoCropDialog.exec = _exec
        chk(st.photo_crop(str(src)) == (0.0, 0.5, 0.5, 1.0), "E 크롭 창 [확인] → 보이는 방향 여백이 회전 0 판 상자로", str(st.photo_crop(str(src))))
        win._photo_rotate(absolute=0)
        win._photo_set_crop(str(src), BOX)
        spin(0.3)
        rec = []
        win._photo_crop_dialog = lambda p=None: rec.append(p)
        win._open_crop_dialog()
        chk(rec == [str(src)], "E 편집 모드 크롭 단추 길 — 사진이면 사진 크롭 창", str(rec))
        del win._photo_crop_dialog

        # F. 이름 변경
        new = pix / "q2.png"
        st.rename_file(str(src), str(new))
        chk(st.photo_crop(str(new)) == BOX and st.photo_crop(str(src)) is None, "F 이름 변경 — 크롭이 새 이름으로")
        st.rename_file(str(new), str(src))
        win._photo_set_crop(str(src), None)
        chk(st.photo_crop(str(src)) is None and tuple(win.main_view._doc.size) == (400, 300), "F 크롭 해제 — 원래 크기")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
