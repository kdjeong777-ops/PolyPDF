# -*- coding: utf-8 -*-
"""사진 평탄화 사본이 원본 EXIF 를 싣는다 (사진 보기 SOT 4.21, 태그 SOT §6.1-⑥, 261111-32 사용자 결정 '평탄화가 원본 EXIF 를 싣게').

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 실제 평탄화 명령(`_photo_flatten`)·실제 사진 정보 색인.
A. 세로 휴대폰 JPEG(방향 6)에 꾸밈 → 평탄화 사본 EXIF 에 촬영일·장비·GPS 가 그대로, 방향은 1(화소가 이미 섰다 — 다른 프로그램에서 다시 돌지 않는다),
   크기 태그(PixelX·YDimension)는 새 그림, EXIF 썸네일(IFD1) 없음
B. 형식이 바뀌는 사본(PNG 원본 → PNG 사본)에도 EXIF
C. 사진 정보 색인을 다시 돌려도 사본의 기본 정보 태그(촬영일·지역·장비)가 남는다(종전엔 빈 값으로 맞춰져 빠졌다)
D. 공유용 사본(위치만 지움)은 그대로 GPS 가 없다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_flatexif_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "평탄화 EXIF", echo=False)   # 마스터 §14.7.2 의 6
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


def exif_of(path):
    from PIL import Image
    with Image.open(path) as im:
        ex = im.getexif()
        return (dict(ex), dict(ex.get_ifd(0x8769) or {}), dict(ex.get_ifd(0x8825) or {}),
                dict(ex.get_ifd(1) or {}) if hasattr(ex, "get_ifd") else {}, im.size)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_flatexif_"))
try:
    from PIL import Image
    ex = Image.Exif()
    ex[0x010F] = "Apple"; ex[0x0110] = "iPhone 15 Pro"; ex[0x0112] = 6
    ex[0x8769] = {0x9003: "2026:11:05 10:20:30", 0xA002: 800, 0xA003: 400}
    ex[0x8825] = {1: "N", 2: (37.0, 40.0, 35.76), 3: "E", 4: (126.0, 44.0, 49.2)}     # 고양시 일산(대화동 근처)
    Image.new("RGB", (800, 400), (30, 170, 60)).save(tmp / "a 세로.jpg", "JPEG", quality=92, exif=ex.tobytes())
    exb = Image.Exif(); exb[0x010F] = "Apple"; exb[0x0110] = "iPhone 15 Pro"
    exb[0x8769] = {0x9003: "2026:11:04 09:00:00"}
    Image.new("RGB", (300, 200), (200, 60, 60)).save(tmp / "b 그림.png", "PNG", exif=exb.tobytes())
    a, b = str(tmp / "a 세로.jpg"), str(tmp / "b 그림.png")

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 850); mw.show(); pump()
    mw._prefs["photo_kind_ocr"] = False                  # 종류 판정(OCR)은 이 검사와 무관 — 느리다
    bt = mw.bookmark_tree
    idx_done = []
    real_done = mw._photo_index_done
    mw._photo_index_done = lambda f, x, y, n: (idx_done.append(n), real_done(f, x, y, n))
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 2), "사진 2장 목록")
    chk(pump(lambda: bool(idx_done), timeout=30), "준비 — 사진 색인 끝")
    tags = bt._tags
    want_meta = tags.get_auto_part(a, "meta")
    chk("2026-11-05" in want_meta and "iPhone15Pro" in want_meta and "고양시" in want_meta,
        "준비 — 원본 기본 정보 태그(촬영일·지역·장비)", str(want_meta))

    st = mw._ensure_page_meta_store()
    for p in (a, b):
        st.set_drawings(p, 0, [{"points": [[0.1, 0.9], [0.9, 0.9]], "pen": 0, "width": 12, "color": "#ff0000", "alpha": 100}])
    st.save()

    # A
    mw._on_bookmark_activated(a, 0); pump(timeout=0.5)
    mw._photo_flatten(a)
    pump(lambda: not mw.__dict__.get("_photo_flat_busy") and any("평탄화" in n and n.endswith(".jpg") for n in os.listdir(tmp)), timeout=15)
    pump(timeout=0.3)
    fa = next((str(tmp / n) for n in os.listdir(tmp) if "평탄화" in n and n.endswith(".jpg")), None)
    chk(fa is not None, "A 평탄화 사본", str(os.listdir(tmp)))
    if fa:
        ifd0, sub, gps, ifd1, size = exif_of(fa)
        chk(ifd0.get(0x010F) == "Apple" and ifd0.get(0x0110) == "iPhone 15 Pro", "A 장비(Make·Model) 그대로", str(ifd0))
        chk(sub.get(0x9003) == "2026:11:05 10:20:30", "A 촬영일 그대로", str(sub))
        chk(gps.get(1) == "N" and gps.get(2) and abs(float(gps[2][0]) - 37.0) < 1e-6, "A GPS 그대로", str(gps))
        chk(ifd0.get(0x0112) == 1, "A 방향 1 — 화소가 이미 섰다(이중 회전 없음)", str(ifd0.get(0x0112)))
        chk(size == (400, 800) and sub.get(0xA002) == 400 and sub.get(0xA003) == 800, "A 크기 태그는 새 그림(400×800)",
            "%s %s" % (size, (sub.get(0xA002), sub.get(0xA003))))
        chk(not ifd1, "A EXIF 썸네일(IFD1) 없음", str(ifd1))

    # B
    mw._on_bookmark_activated(b, 0); pump(timeout=0.5)
    mw._photo_flatten(b)
    pump(lambda: not mw.__dict__.get("_photo_flat_busy") and any("평탄화" in n and n.endswith(".png") for n in os.listdir(tmp)), timeout=15)
    pump(timeout=0.3)
    fb = next((str(tmp / n) for n in os.listdir(tmp) if "평탄화" in n and n.endswith(".png")), None)
    if fb:
        ifd0, sub, gps, ifd1, size = exif_of(fb)
        chk(ifd0.get(0x0110) == "iPhone 15 Pro" and sub.get(0x9003) == "2026:11:04 09:00:00", "B PNG 사본에도 EXIF(장비·촬영일)",
            "%s %s" % (ifd0, sub))
    else:
        chk(False, "B PNG 평탄화 사본", str(os.listdir(tmp)))

    # C — 다시 훑어도 사본의 기본 정보 태그가 남는다
    if fa:
        pump(lambda: bool(bt._tags.get_auto_part(fa, "meta")), timeout=5)
        idx_done.clear()
        mw._photo_index_start()
        chk(pump(lambda: bool(idx_done), timeout=30), "C 다시 훑기 끝")
        pump(timeout=0.8)
        got = tags.get_auto_part(fa, "meta")
        chk(set(want_meta) <= set(got), "C 다시 훑은 뒤에도 사본의 기본 정보 태그(촬영일·지역·장비)", "%s vs %s" % (got, want_meta))

    # D — 공유용 사본(위치만 지움)은 그대로
    from viewer.photo_controller import PhotoShareWorker
    res = {}
    w = PhotoShareWorker([a], "gps", {})
    w.done.connect(lambda ok, bad: res.setdefault("ok", ok))
    w.run()
    pump(lambda: "ok" in res, timeout=5)
    outs = [o for _s, o in res.get("ok", [])]
    chk(outs and not exif_of(outs[0])[2], "D 공유용 사본(위치만 지움)은 GPS 없음 — 규칙 그대로", str(res))
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
