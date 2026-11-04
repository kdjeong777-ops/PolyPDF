# -*- coding: utf-8 -*-
"""사진 모드 — 다른 기능과 맞물림 (사진 보기 SOT 4.11, 261104-6).

실제 MainWindow 둘로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A1. 사진 썸네일 줄에서 끌어내는 자료는 고른 사진의 파일 URL — PDF 모드 창의 쪽 썸네일(편집 모드)에 놓으면 새 쪽(HEIC 도)
A2. 가상 프린터로 받은 PDF — 받는 창이 사진 모드면 그 창을 PDF 모드로 바꾸지 않고 새 창(PDF 모드)으로, 다른 창이 넘겨도 사진 모드 창은 거절
A3. 스크린샷 카드를 본문에 보이는 중이면 ◀▶ 는 카드 목록, 사진을 보이는 중이면 사진 목록 — '지금 본문이 카드냐 사진이냐' 하나로 가린다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPointF, QEvent
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QDropEvent
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_dnd_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 맞물림", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_dnd_"))
try:
    from PIL import Image
    import fitz
    pdir = tmp / "사진"; pdir.mkdir()
    Image.new("RGB", (800, 400), (200, 60, 60)).save(pdir / "a.jpg", "JPEG")
    Image.new("RGB", (400, 300), (60, 160, 60)).save(pdir / "b.jpg", "JPEG")
    try:
        import pillow_heif  # noqa — 있으면 HEIC 도
    except Exception:
        pass
    from viewer import photo_io
    heic = None
    if photo_io.heif_ready():
        try:
            from pi_heif import register_heif_opener  # noqa
            Image.new("RGB", (300, 200), (30, 30, 200)).save(pdir / "c.heic", "HEIF")
            heic = str(pdir / "c.heic")
        except Exception:
            heic = None
    ddir = tmp / "문서"; ddir.mkdir()
    d = fitz.open(); d.new_page(); d.new_page(); d.save(str(ddir / "보고서.pdf")); d.close()
    shots = tmp / "shots"; shots.mkdir()
    for n in ("s1.png", "s2.png"):
        Image.new("RGB", (120, 90), (90, 90, 90)).save(shots / n, "PNG")

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(pdir)
    bt = mw.bookmark_tree
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 2)
    bt.set_sort_mode(bt.SORT_NAME); pump()
    mw._on_bookmark_activated(str(pdir / "a.jpg"), 0); pump(timeout=0.6)
    strip = mw._photo_strip

    # A1
    items = [strip._items[str(pdir / "a.jpg")], strip._items[str(pdir / "b.jpg")]]
    md = strip.mimeData(items)
    urls = [u.toLocalFile() for u in md.urls()]
    chk([Path(u).name for u in urls] == ["a.jpg", "b.jpg"], "A1 끌어내는 자료 = 고른 사진의 파일 URL", str(urls))
    chk(strip.dragEnabled(), "A1 썸네일 줄에서 끌어낼 수 있다")
    if heic:
        md.setUrls(md.urls() + [__import__("PyQt6.QtCore", fromlist=["QUrl"]).QUrl.fromLocalFile(heic)])
    mw2 = MainWindow(); mw2._skip_save_on_close = True
    mw2.resize(1200, 800); mw2.show(); pump()
    mw2.open_folder(ddir)
    bt2 = mw2.bookmark_tree
    pump(lambda: sum(1 for _ in bt2._iter_file_nodes()) == 1)
    mw2._on_bookmark_activated(str(ddir / "보고서.pdf"), 0); pump(timeout=0.8)
    bt2.set_edit_mode(True); pump()
    pt = mw2.page_thumbs
    n0 = pt.list.count()
    vp = pt.list.viewport()
    ev = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                    QEvent.Type.Drop)
    pt.eventFilter(vp, ev)
    want = 2 + (1 if heic else 0)
    chk(pump(lambda: pt.list.count() == n0 + want, timeout=10), "A1 PDF 창 쪽 썸네일에 놓으면 새 쪽 %d개" % want,
        "%d → %d" % (n0, pt.list.count()))
    from PyQt6.QtCore import QMimeData, QUrl
    hm = QMimeData(); hm.setUrls([QUrl.fromLocalFile(str(pdir / "x.heic")), QUrl.fromLocalFile(str(pdir / "y.txt"))])
    chk([Path(p).name for p in pt._image_paths_from_mime(hm)] == ["x.heic"], "A1 쪽 썸네일 받기 거름이 HEIC 도 받는다(글 파일은 아님)")
    mw2.close()

    # A2
    opened = []
    mw._vprinter_new_window = lambda p: opened.append(p)
    mw._vprinter_to_peer = lambda p: False
    mw._vprinter_open(str(ddir / "보고서.pdf")); pump()
    chk(opened == [str(ddir / "보고서.pdf")] and mw._photo_mode, "A2 사진 모드 창은 새 창으로 넘기고 사진 모드 그대로", str(opened))
    chk(mw._vprinter_peer_show(str(pdir / "x.pdf")).get("ok") is False, "A2 다른 창이 넘겨도 사진 모드 창은 거절")

    # A3
    for n in ("s1.png", "s2.png"):
        mw.shot_strip.add_item(str(shots / n), kind="image", prepend=False)
    mw._on_screenshot_activated(str(shots / "s1.png"), 0); pump(timeout=0.5)
    mw._on_image_step(+1); pump(timeout=0.5)
    chk(getattr(mw, "_current_shot_path", "") == str(shots / "s2.png"), "A3 카드를 보이는 중이면 ◀▶ 는 카드 목록",
        str(getattr(mw, "_current_shot_path", None)))
    mw._on_bookmark_activated(str(pdir / "a.jpg"), 0); pump(timeout=0.5)
    mw._on_file_boundary(+1, mw._active_pane); pump(timeout=0.5)
    chk(Path(mw.main_view.current_file()).name == "b.jpg", "A3 사진을 보이는 중이면 ◀▶ 는 사진 목록", str(mw.main_view.current_file()))
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
