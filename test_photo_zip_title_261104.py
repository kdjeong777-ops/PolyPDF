# -*- coding: utf-8 -*-
"""썸네일 칸 제목·zip 보기 (사진 보기 SOT 4.32, 261104-8 사용자 지시).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진을 보면 썸네일 칸 제목 앞에 그 형식 아이콘(JPG), PDF 모드의 PDF 는 PDF 아이콘
B. zip 줄을 누르면 곧바로 제목 = zip 이름·ZIP 아이콘, 썸네일 줄은 비운다(꺼내는 동안 폴더 사진이 남지 않게)
C. 꺼낸 뒤 제목은 계속 zip 이름(안쪽 사진 이름이 아니다), 썸네일 줄은 그 zip 사진만 — 책갈피창에서 사진 여럿을 함께 골라 둔 채라도
D. zip 안에서 넘겨도 제목은 zip 이름·줄은 zip 사진만
E. zip 밖 사진을 누르면 종전대로(제목 = 그 사진, 줄 = 폴더 사진)
"""
import os, sys, tempfile, shutil, time, zipfile, io
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
QCoreApplication.setApplicationName("polypdf_photo_ztitle_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "zip 제목", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_ztitle_"))
try:
    from PIL import Image
    import fitz
    Image.new("RGB", (300, 200), (30, 160, 60)).save(tmp / "밖 하나.jpg", "JPEG")
    Image.new("RGB", (300, 200), (160, 30, 60)).save(tmp / "밖 둘.jpg", "JPEG")

    def jpg_bytes(color):
        b = io.BytesIO(); Image.new("RGB", (400, 300), color).save(b, "JPEG"); return b.getvalue()
    zp = str(tmp / "여행 사진.zip")
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("여행/가 해변.jpg", jpg_bytes((200, 60, 60)))
        z.writestr("여행/나 산.jpg", jpg_bytes((60, 60, 200)))
    d = fitz.open(); d.new_page(); d.save(str(tmp / "보고서.pdf")); d.close()

    from viewer.app import MainWindow
    from viewer.widgets.photo_strip import PhotoStrip  # noqa: F401  (사진 줄이 있는 판인지)
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    pt = mw.page_thumbs
    kind = lambda: getattr(pt, "_title_kind", None)
    icon_on = lambda: getattr(pt, "_title_icon", None) is not None and pt._title_icon.isVisible()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 1)

    # A — PDF 모드
    mw._on_bookmark_activated(str(tmp / "보고서.pdf"), 0); pump(timeout=0.8)
    chk(kind() == "PDF" and icon_on() and pt.title.text() == "보고서", "A PDF 모드 제목 앞 PDF 아이콘", f"{kind()} {pt.title.text()}")
    mw._set_photo_mode(True)
    names = lambda: sorted(Path(str(it.data(0, bt.DATA_FILE))).name for it in bt._iter_file_nodes())
    pump(lambda: names() == ["밖 둘.jpg", "밖 하나.jpg", "여행 사진.zip"])
    mw._on_bookmark_activated(str(tmp / "밖 하나.jpg"), 0); pump(timeout=0.8)
    chk(kind() == "JPG" and icon_on() and pt.title.text() == "밖 하나", "A 사진 제목 앞 JPG 아이콘", f"{kind()} {pt.title.text()}")
    strip = mw._photo_strip

    # B·C — 책갈피창에서 밖 사진 둘과 zip 을 함께 고른 채 zip 을 연다
    for it in bt._iter_file_nodes():
        it.setSelected(True)
    mw._on_bookmark_activated(zp, 0)
    chk(kind() == "ZIP" and pt.title.text() == "여행 사진", "B 누르자마자 제목 = zip 이름·ZIP 아이콘", f"{kind()} {pt.title.text()}")
    chk(not any(Path(p).name.startswith("밖") for p in strip.paths()), "B 꺼내는 동안 폴더 사진이 줄에 남지 않는다", str(strip.paths()))
    zipped = lambda: sorted(Path(p).name for p in strip.paths()) == ["가 해변.jpg", "나 산.jpg"]
    chk(pump(zipped, timeout=10), "C 썸네일 줄은 zip 사진만(여럿 고름이 있어도)", str([Path(p).name for p in strip.paths()]))
    pump(timeout=0.5)
    chk(zipped(), "C 열고 난 뒤에도 zip 사진만", str([Path(p).name for p in strip.paths()]))
    chk(kind() == "ZIP" and pt.title.text() == "여행 사진", "C 제목은 안쪽 사진이 아니라 zip 이름", f"{kind()} {pt.title.text()}")

    # D
    mw._on_file_boundary(+1, mw._active_pane); pump(timeout=0.6)
    chk(Path(mw.main_view.current_file()).name == "나 산.jpg" and zipped() and pt.title.text() == "여행 사진",
        "D zip 안에서 넘겨도 제목·줄 그대로", f"{mw.main_view.current_file()} {pt.title.text()}")

    # E
    for it in bt._iter_file_nodes():
        it.setSelected(False)
    mw._on_bookmark_activated(str(tmp / "밖 둘.jpg"), 0); pump(timeout=0.8)
    chk(kind() == "JPG" and pt.title.text() == "밖 둘", "E zip 밖 사진 — 제목은 그 사진", f"{kind()} {pt.title.text()}")
    chk(sorted(Path(p).name for p in strip.paths()) == ["밖 둘.jpg", "밖 하나.jpg"], "E 줄은 다시 폴더 사진",
        str([Path(p).name for p in strip.paths()]))
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
