# -*- coding: utf-8 -*-
"""공유용 사본 — 정보 지운 사본 (사진 보기 SOT 4.22, F5·D16, 261104-3 P2 ⑤).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 사진은 이 검사가 만든 임시 폴더의 것.
A. '위치 지움': 같은 폴더 '<이름>_공유.jpg' — GPS 만 없고 다른 EXIF(기기)는 그대로, 그림 자료 같음(다시 압축 없음), 원본 그대로
B. '정보 모두 지움': EXIF(기기·GPS)·주석 없음, 방향 태그만 남음, 색 프로필 그대로, 그림 자료 같음
C. 돌린 사진(보기 회전 90)의 사본은 방향 태그로 돌아 있다
D. JPEG 아닌 사진(PNG)은 같은 형식으로 정보 없이 다시 저장
E. 여러 장 한 번에, 다시 만들면 '(1)' 이 붙는다 — 사본을 덮어쓰지 않는다, 임시 파일이 남지 않는다
F. 세 메뉴(책갈피창 사진 행·썸네일 줄·본문)에 두 항목
G. 바꿔치기(os.replace)는 메인 스레드에서 하지 않는다
"""
import os, sys, tempfile, shutil, time, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_share_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "공유용 사본", echo=False)   # 마스터 §14.7.2 의 6
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


menu_texts = []
_orig_exec = QMenu.exec
QMenu.exec = lambda self, *a, **k: (menu_texts.clear(), menu_texts.extend(x.text().split("\t")[0] for x in self.actions()), None)[-1]
real_replace = os.replace
on_main = []

tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_share_"))
try:
    from PIL import Image, ImageCms
    from viewer import photo_io
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()

    def jpeg(name, orient=1):
        ex = Image.Exif()
        ex[0x010F] = "PolyCam"
        ex[0x0112] = orient
        ex[0x8825] = {1: "N", 2: (37.0, 30.0, 0.0), 3: "E", 4: (127.0, 0.0, 0.0)}
        Image.new("RGB", (800, 400), (200, 60, 60)).save(tmp / name, "JPEG", quality=90, exif=ex.tobytes(),
                                                         icc_profile=icc, comment=b"secret note")
        return str(tmp / name)

    a = jpeg("a.jpg")
    b = jpeg("b 방향6.jpg", orient=6)
    c = jpeg("c 돌림.jpg")
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo(); info.add_text("Author", "someone")
    Image.new("RGB", (300, 200), (30, 160, 60)).save(tmp / "d.png", "PNG", pnginfo=info)
    d = str(tmp / "d.png")
    raw = {p: Path(p).read_bytes() for p in (a, b, c, d)}

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 4), "사진 4장 목록")

    def spy(s, t):
        if Path(str(t)).suffix.lower() in (".jpg", ".png"):
            on_main.append(threading.current_thread() is threading.main_thread())
        return real_replace(s, t)
    os.replace = spy

    def share(paths, mode):
        mw._photo_share(paths, mode)
        pump(lambda: not mw.__dict__.get("_photo_share_busy"), timeout=10); pump(timeout=0.3)

    # A
    share([a], "gps")
    sa = tmp / "a_공유.jpg"
    chk(sa.exists(), "A '<이름>_공유.jpg' 생김")
    if sa.exists():
        with Image.open(sa) as im:
            ex = im.getexif()
            chk(not ex.get_ifd(0x8825) and ex.get(0x010F) == "PolyCam", "A GPS 만 없고 기기 정보는 그대로")
        chk(photo_io.jpeg_scan_data(sa.read_bytes()) == photo_io.jpeg_scan_data(raw[a]), "A 그림 자료 같음(다시 압축 없음)")
    chk(Path(a).read_bytes() == raw[a], "A 원본 그대로")

    # B
    share([b], "all")
    sb = tmp / "b 방향6_공유.jpg"
    if sb.exists():
        data = sb.read_bytes()
        with Image.open(sb) as im:
            ex = im.getexif()
            chk(ex.get(0x0112) == 6 and ex.get(0x010F) is None and not ex.get_ifd(0x8825), "B 방향 태그만 남음", str(dict(ex)))
            chk(im.info.get("icc_profile") == icc, "B 색 프로필 그대로")
        chk(b"secret note" not in data, "B 주석 묶음 없음")
        chk(photo_io.jpeg_scan_data(data) == photo_io.jpeg_scan_data(raw[b]), "B 그림 자료 같음")
    else:
        chk(False, "B 사본 생김")

    # C
    mw._on_bookmark_activated(c, 0); pump(timeout=0.5)
    mw._photo_rotate(+90); pump(timeout=0.5)
    share([c], "all")
    sc = tmp / "c 돌림_공유.jpg"
    if sc.exists():
        with Image.open(sc) as im:
            chk(im.getexif().get(0x0112) == 6, "C 보기 회전 90 → 사본 방향 6", str(im.getexif().get(0x0112)))
    else:
        chk(False, "C 사본 생김")

    # D
    share([d], "all")
    sd = tmp / "d_공유.png"
    if sd.exists():
        with Image.open(sd) as im:
            chk(im.format == "PNG" and "Author" not in im.info, "D PNG 는 정보 없이 PNG 로", str(im.info))
    else:
        chk(False, "D 사본 생김")

    # E
    share([a, b], "gps")
    names = sorted(n for n in os.listdir(tmp) if "_공유" in n)
    chk("a_공유 (1).jpg" in names and "b 방향6_공유 (1).jpg" in names, "E 여러 장·다시 만들면 '(1)' — 덮어쓰지 않음", str(names))
    chk(not any(n.endswith(".polypix-tmp") for n in os.listdir(tmp)), "E 임시 파일이 남지 않는다")
    chk(all(Path(p).read_bytes() == raw[p] for p in (a, b, d)), "E 원본은 모두 그대로")

    # F
    os.replace = real_replace
    it = next(x for x in bt._iter_file_nodes() if Path(str(x.data(0, bt.DATA_FILE))).name == "a.jpg")
    bt.tree.scrollToItem(it)
    bt._on_tree_context_menu(bt.tree.visualItemRect(it).center())
    t1 = list(menu_texts)
    mw._photo_strip.menuRequested.emit(a, QPoint(5, 5)); pump()
    t2 = list(menu_texts)
    mw._photo_context_menu(QPoint(5, 5))
    t3 = list(menu_texts)
    for name, tx in (("책갈피창", t1), ("썸네일 줄", t2), ("본문", t3)):
        chk("공유용 사본 (위치 지움)" in tx and "공유용 사본 (정보 모두 지움)" in tx, "F %s 메뉴에 공유용 사본 두 항목" % name, str(tx))

    # G
    chk(on_main and not any(on_main), "G 바꿔치기는 메인에서 하지 않는다", str(on_main))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    os.replace = real_replace
    QMenu.exec = _orig_exec
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
