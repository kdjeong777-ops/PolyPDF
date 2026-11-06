# -*- coding: utf-8 -*-
"""사진 방향 저장 한 길 (사진 보기 SOT 4.17, D17, 261104-3).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 사진은 모두 이 검사가 만든 임시 폴더의 것.
A. 돌린 JPEG 을 저장하면 EXIF 방향 태그만 바뀐다 — 그림 자료(SOS 뒤)·크기·다른 EXIF(기기 이름·GPS)는 그대로, 임시 파일이 남지 않는다,
   보기 회전(`photo_rot`)은 지워지고 본문은 그 방향 그대로 보인다
B. 이미 방향이 있는 사진(6)을 왼쪽으로 돌려 저장하면 1 — 방향 합성
C. JPEG 이 아니면(`.jpg` 이름의 PNG 포함) 저장하지 않는다 — 파일 그대로
D. 꾸밈이 있는 사진도 저장한다 — 꾸밈(사이드카)도 새 회전 0 판으로 함께 옮겨진다(4.19)
E. 바꿔치기가 끝내 거부되면 원본 그대로·임시 파일 지움·보기 회전 그대로
F. 파일 작업(`os.replace`)은 메인 스레드에서 하지 않는다(마스터 §4.7.5·응답성 SOT)
"""
import os, sys, tempfile, shutil, time, threading
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
QCoreApplication.setApplicationName("polypdf_photo_orient_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "방향 저장", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_orient_"))
try:
    from PIL import Image
    from viewer import photo_io

    def jpeg(name, orient=None, gps=False):
        im = Image.new("RGB", (800, 400), (40, 60, 200))
        im.paste(Image.new("RGB", (800, 200), (220, 40, 40)), (0, 0))
        ex = Image.Exif()
        ex[0x010F] = "PolyCam"
        if orient:
            ex[0x0112] = orient
        if gps:
            ex[0x8825] = {1: "N", 2: (37.0, 30.0, 0.0)}
        im.save(tmp / name, "JPEG", quality=92, exif=ex.tobytes())
        return str(tmp / name)

    a = jpeg("a 가로.jpg", orient=1, gps=True)
    b = jpeg("b 방향6.jpg", orient=6)
    c = str(tmp / "c 그림.jpg")
    Image.new("RGB", (300, 200), (30, 160, 60)).save(c, "PNG")         # 이름만 .jpg
    d = jpeg("d 꾸밈.jpg", orient=1)
    e = jpeg("e 잠김.jpg", orient=1)
    raw = {p: Path(p).read_bytes() for p in (a, b, c, d, e)}

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 5), "사진 5장 목록")
    mv = mw.main_view
    st = mw._ensure_page_meta_store()

    replace_threads = []
    real_replace = os.replace

    def spy_replace(s, t):
        if not str(t).lower().endswith(".jpg"):          # 사이드카(json) 저장은 따로 — 사진 파일 바꿔치기만 본다
            return real_replace(s, t)
        replace_threads.append(threading.current_thread() is threading.main_thread())
        return real_replace(s, t)
    os.replace = spy_replace

    def save_and_wait():
        mw._photo_save_orientation()
        pump(lambda: not mw.__dict__.get("_photo_orig_busy"), timeout=10)
        pump(timeout=0.3)

    # A
    mw._on_bookmark_activated(a, 0); pump(timeout=0.5)
    mw._photo_rotate(+90); pump(timeout=0.5)
    save_and_wait()
    new = Path(a).read_bytes()
    with Image.open(a) as im:
        ex = im.getexif()
        chk(ex.get(0x0112) == 6 and im.size == (800, 400), "A 방향 태그 1 → 6, 그림 크기 그대로", str((ex.get(0x0112), im.size)))
        chk(ex.get(0x010F) == "PolyCam" and bool(ex.get_ifd(0x8825)), "A 다른 EXIF(기기·GPS)는 그대로")
    chk(photo_io.jpeg_scan_data(new) == photo_io.jpeg_scan_data(raw[a]) and len(new) == len(raw[a]),
        "A 그림 자료·파일 길이 그대로(다시 압축하지 않음)")
    chk(not any(n.endswith(".polypix-tmp") for n in os.listdir(tmp)), "A 임시 파일이 남지 않는다")
    chk(st.photo_rotation(a) == 0, "A 보기 회전은 지워진다(이제 파일이 그 방향)")
    chk(tuple(map(round, mv._doc.doc[0].rect[2:])) == (400, 800), "A 본문은 그 방향 그대로(400×800)", str(mv._doc.doc[0].rect))

    # B
    mw._on_bookmark_activated(b, 0); pump(timeout=0.5)
    mw._photo_rotate(-90); pump(timeout=0.5)
    save_and_wait()
    with Image.open(b) as im:
        chk(im.getexif().get(0x0112) == 1, "B 방향 6 + 왼쪽 90° = 1", str(im.getexif().get(0x0112)))

    # C
    mw._on_bookmark_activated(c, 0); pump(timeout=0.5)
    mw._photo_rotate(+90); pump(timeout=0.5)
    save_and_wait()
    chk(Path(c).read_bytes() == raw[c] and st.photo_rotation(c) == 90, "C JPEG 아니면 파일 그대로·보기 회전만")

    # D
    st.set_drawings(d, 0, [{"points": [[0.1, 0.1], [0.9, 0.1]], "pen": 0, "width": 3}])
    st.set_images(d, 0, [{"data": "", "rect": [0.0, 0.0, 0.25, 0.5], "shape": "rect", "alpha": 100, "rot": 0}]); st.save()
    mw._on_bookmark_activated(d, 0); pump(timeout=0.5)
    mw._photo_rotate(+90); pump(timeout=0.5)
    save_and_wait()
    with Image.open(d) as im:
        chk(im.getexif().get(0x0112) == 6, "D 꾸밈이 있어도 방향 태그 저장")
    pts = [[round(x, 4), round(y, 4)] for x, y in st.get_drawings(d, 0)[0]["points"]]
    chk(pts == [[0.9, 0.1], [0.9, 0.9]], "D 선도 새 판으로 옮겨진다", str(pts))
    img = (st.get_images(d, 0) or [{}])[0]
    chk([round(v, 4) for v in img.get("rect", [])] == [0.5, 0.0, 0.5, 0.25] and round(img.get("rot", 0)) == 90,
        "D 삽입 그림은 중심을 옮기고 픽셀 크기 그대로·rot 90", str(img.get("rect")) + " rot=" + str(img.get("rot")))
    chk(st.photo_rotation(d) == 0, "D 보기 회전 지움")

    # E
    mw._on_bookmark_activated(e, 0); pump(timeout=0.5)
    mw._photo_rotate(+90); pump(timeout=0.5)

    def deny(s, t):
        replace_threads.append(threading.current_thread() is threading.main_thread())
        raise PermissionError(13, "locked")
    os.replace = deny
    save_and_wait()
    os.replace = spy_replace
    chk(Path(e).read_bytes() == raw[e], "E 바꿔치기 거부 — 원본 그대로")
    chk(not any(n.endswith(".polypix-tmp") for n in os.listdir(tmp)), "E 임시 파일을 지운다")
    chk(st.photo_rotation(e) == 90, "E 보기 회전은 그대로")

    # F
    os.replace = real_replace
    chk(replace_threads and not any(replace_threads), "F 바꿔치기는 메인 스레드에서 하지 않는다", str(replace_threads))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    try:
        os.replace = real_replace
    except NameError:
        pass
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
