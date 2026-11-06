# -*- coding: utf-8 -*-
"""사진 EXIF 방향 — 원본 화소를 다루는 길은 방향을 먼저 세운 좌표계로 (사진 보기 SOT §4.43·§4.22, 261106-17 결함).

사용자 보고: 휴대폰 세로 사진(방향 6)을 모양 펴기 [저장] 했더니 90° 돌고 엉뚱한 곳이 펴졌다. 원인은 Pillow 의 `getexif()` 가
그림이 쥔 객체라, 방향을 먼저 1 로 바꾸면 `exif_transpose` 가 세우지 않는 것. 공유용 사본(자른 JPEG '위치 지움')도 같은 꼴이었다.
방향 1·3·6·8 사진(화소는 저장 방향, 네 귀퉁이 색이 다르다)으로:
A. 모양 펴기 [저장](원본 대체)·새 파일 — 결과 = '세운 그림을 같은 점으로 편 것', 방향 태그 1
B. 크롭 창 미리보기(줄인 그림)로 편 것과 원본 해상도 결과가 같은 내용
C. 공유용 사본(위치 지움)의 자른 JPEG — 결과 = 세운 그림의 그 크롭
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_warp_orient_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def diff(a, b, n=24):
    a = a.convert("RGB").resize((n, n))
    b = b.convert("RGB").resize((n, n))
    pa, pb_ = list(a.getdata()), list(b.getdata())
    return sum(abs(x[k] - y[k]) for x, y in zip(pa, pb_) for k in range(3)) / (3.0 * len(pa))


tmp = Path(tempfile.mkdtemp(prefix="polypdf_warp_orient_"))
try:
    from PIL import Image, ImageOps, ImageDraw
    from viewer import photo_warp as pw, photo_backup
    import viewer.photo_controller as pc
    from viewer.widgets.photo_crop_dialog import _pil_of
    photo_backup.set_custom_dir("")
    PTS = [(0.08, 0.06), (0.62, 0.1), (0.58, 0.55), (0.1, 0.5)]      # 보이는 방향 왼쪽 위 쪽의 비뚤어진 사각형
    PTS = PTS + pw.mids_of(PTS)

    def make(name, o):
        im = Image.new("RGB", (800, 600))               # 저장 화소: 가로, 네 귀퉁이 색
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 399, 299), fill=(220, 30, 30)); d.rectangle((400, 0, 799, 299), fill=(30, 200, 30))
        d.rectangle((0, 300, 399, 599), fill=(30, 30, 220)); d.rectangle((400, 300, 799, 599), fill=(230, 220, 30))
        d.rectangle((60, 60, 200, 120), fill=(255, 255, 255))
        ex = Image.Exif(); ex[0x0112] = o; ex[0x0110] = "Cam"
        p = tmp / name
        im.save(p, "JPEG", quality=95, exif=ex.tobytes())
        return str(p)

    for o in (1, 3, 6, 8):
        src = make("o%d.jpg" % o, o)
        with Image.open(src) as im0:
            up = ImageOps.exif_transpose(im0).convert("RGB")
        want = pw.unwarp(up, PTS)
        # A — 새 파일
        w = pc.PhotoWarpWorker([(src, 0, PTS)], dest=None)
        got = {}
        w.done.connect(lambda ok, bad, g=got: g.update(ok=ok, bad=bad))
        w.run()
        out = got["ok"][0][1] if got.get("ok") else None
        o_new = Image.open(out) if out else None
        chk(o_new is not None and diff(o_new, want) < 12 and int(o_new.getexif().get(0x0112, 1) or 1) == 1,
            "A 방향 %d — 새 파일 = 세운 그림을 편 것, 방향 1" % o, "%.1f" % (diff(o_new, want) if o_new else -1))
        # B — 크롭 창 미리보기(배경 워커가 푼 줄인 그림)로 편 것
        cw = pc.PhotoCopyWorker(src, 0, max_side=400)
        gq = {}
        cw.done.connect(lambda p, img, g=gq: g.update(img=img))
        cw.run()
        prev = pw.unwarp(_pil_of(gq["img"]), PTS, cells=12)
        chk(diff(prev, want) < 14, "B 방향 %d — 미리보기로 편 것과 원본 해상도 결과가 같은 내용" % o, "%.1f" % diff(prev, want))
        # A — 원본 대체
        w = pc.PhotoWarpWorker([(src, 0, PTS)], dest=("replace", None))
        got = {}
        w.done.connect(lambda ok, bad, g=got: g.update(ok=ok, bad=bad))
        w.run()
        rep = Image.open(src)
        chk(got.get("ok") and diff(rep, want) < 12 and int(rep.getexif().get(0x0112, 1) or 1) == 1 and rep.getexif().get(0x0110) == "Cam",
            "A 방향 %d — 원본 대체 = 세운 그림을 편 것, 방향 1, 카메라 정보 남음" % o, "%.1f" % diff(rep, want))
        # C — 공유용 사본(위치 지움, 자른 JPEG)
        src2 = make("s%d.jpg" % o, o)
        box0 = (0.0, 0.0, 0.5, 0.5)                    # 회전 0 판(= 방향을 세운 그림) 왼쪽 위 사분면
        sw = pc.PhotoShareWorker([src2], "gps", {src2: 0}, dest=None, crops={src2: box0})
        gs = {}
        sw.done.connect(lambda ok, bad, g=gs: g.update(ok=ok, bad=bad))
        sw.run()
        sh = Image.open(gs["ok"][0][1]) if gs.get("ok") else None
        with Image.open(src2) as im0:
            up2 = ImageOps.exif_transpose(im0).convert("RGB")
        w2, h2 = up2.size
        want2 = up2.crop((0, 0, w2 // 2, h2 // 2))
        chk(sh is not None and diff(sh, want2) < 12 and int(sh.getexif().get(0x0112, 1) or 1) == 1,
            "C 방향 %d — 공유용 사본(자른 JPEG) = 세운 그림의 그 크롭, 방향 1" % o, "%.1f" % (diff(sh, want2) if sh else -1))
    # D — 재발 방지: 방향 태그를 고쳐 쓰는 곳은 `photo_io.upright_with_exif` 하나(세우기 먼저)
    import re
    root = Path(__file__).resolve().parent / "viewer"
    bad = []
    pat = re.compile(r"\[\s*(0x0112|ORIENT_TAG)\s*\]\s*=(?!=)")
    for f in root.rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line) and f.name != "photo_io.py":
                bad.append("%s:%d" % (f.relative_to(root), n))
    chk(not bad, "D 방향 태그를 직접 고쳐 쓰는 곳이 photo_io 밖에 없다(upright_with_exif 하나로)", str(bad))
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
