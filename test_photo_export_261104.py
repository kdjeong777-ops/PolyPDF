# -*- coding: utf-8 -*-
"""사진 → PDF·인쇄·평탄화 — 보이는 그대로 (사진 보기 SOT 4.6·4.21, D4·D6, 261104-3 P2 ④).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 창(인쇄·이미지→PDF·저장)은 가짜로 바꿔 받은 값만 본다.
A. 사진들 → PDF: 한 장 = 한 쪽, 돌린 사진은 `/Rotate`(보이는 방향), 꾸밈이 있는 사진은 쪽에 구워진다, 꾸밈 없는 사진은 그대로
B. 사진 모드 인쇄: 같은 인쇄 창을 사진으로 만든 PDF(쪽 수·지금 쪽)로 연다 — 종전엔 리본 인쇄가 꺼져 있었다
C. 평탄화: 꾸밈을 굽고 보기 회전까지 적용한 **새 그림**이 원본 옆에(원본 그대로·EXIF 없음), 임시 파일이 남지 않는다
D. 이미지 → PDF 창(사진 모드): 만든 PDF 에 꾸밈·회전이 들어가고 **새 창**(PDF 모드)으로 연다
E. 사진 모드에서 인쇄·평탄화 명령이 켜져 있고, 본문 사진 메뉴에 '인쇄…'·'평탄화...'
"""
import os, sys, tempfile, shutil, time
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
QCoreApplication.setApplicationName("polypdf_photo_export_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 내보내기", echo=False)   # 마스터 §14.7.2 의 6
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

tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_export_"))
try:
    from PIL import Image
    import fitz
    ex = Image.Exif(); ex[0x8825] = {1: "N", 2: (37.0, 30.0, 0.0)}
    Image.new("RGB", (800, 400), (30, 170, 60)).save(tmp / "a 가로.jpg", "JPEG", quality=92, exif=ex.tobytes())
    Image.new("RGB", (600, 300), (60, 60, 200)).save(tmp / "b 가로.jpg", "JPEG", quality=92)
    a, b = str(tmp / "a 가로.jpg"), str(tmp / "b 가로.jpg")
    a_raw = Path(a).read_bytes()

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 2), "사진 2장 목록")
    st = mw._ensure_page_meta_store()
    st.set_drawings(a, 0, [{"points": [[0.1, 0.9], [0.9, 0.9]], "pen": 0, "width": 12, "color": "#ff0000", "alpha": 100}])
    st.save()
    mw._on_bookmark_activated(a, 0); pump(timeout=0.5)
    mw._photo_rotate(+90); pump(timeout=0.5)

    # A
    pdf = mw._photo_make_pdf([a, b])
    doc = fitz.open(pdf) if pdf else None
    chk(doc is not None and doc.page_count == 2, "A 두 장 → 두 쪽")
    if doc is not None:
        p0, p1 = doc[0], doc[1]
        chk(p0.rotation == 90 and tuple(map(round, p0.rect[2:])) == (400, 800), "A 돌린 사진은 /Rotate 90 — 보이는 400×800",
            "%s %s" % (p0.rotation, p0.rect))
        chk(len(p0.get_drawings()) > 0 or len(p0.get_xobjects()) > 0, "A 꾸밈이 쪽에 구워진다")
        chk(p1.rotation == 0 and not p1.get_drawings() and len(p1.get_images()) == 1, "A 꾸밈 없는 사진 쪽은 그림 하나 그대로")
        doc.close()

    # B
    import viewer.widgets.print_dialog as _pdm
    seen = {}

    class FakeDlg:
        def __init__(self, n, cur_page, n_thumb, n_shot, parent, **kw):
            seen.update(n=n, cur_page=cur_page, sample=kw.get("sample"), files=kw.get("file_paths"))

        def exec(self):
            return False
    real_dlg = _pdm.PrintScopeDialog
    _pdm.PrintScopeDialog = FakeDlg
    try:
        mw._cmds["file.print"].trigger(); pump(timeout=2)
    finally:
        _pdm.PrintScopeDialog = real_dlg
    chk(seen.get("n") == 1 and str(seen.get("sample", "")).lower().endswith(".pdf") and not seen.get("files"),
        "B 사진 모드 인쇄 — 같은 창을 사진 PDF(1쪽)로", str(seen))

    # C
    mw._photo_flatten(a)
    pump(lambda: not mw.__dict__.get("_photo_flat_busy"), timeout=10); pump(timeout=0.3)
    outs = [n for n in os.listdir(tmp) if "평탄화" in n]
    chk(len(outs) == 1 and outs[0] == "a 가로_평탄화.jpg", "C 새 그림 'a 가로_평탄화.jpg'", str(outs))
    if outs:
        with Image.open(tmp / outs[0]) as im:
            chk(im.size == (400, 800), "C 보기 회전까지 적용(400×800)", str(im.size))
            chk(not im.getexif().get_ifd(0x8825), "C 평탄화한 그림에 GPS 없음")
            px = im.convert("RGB").getpixel((int(0.1 * 400), 400))
            bg = im.convert("RGB").getpixel((200, 400))
            chk(px != bg and abs(px[1] - bg[1]) > 40, "C 꾸밈(선)이 그림에 구워짐", "%s vs %s" % (px, bg))
    chk(Path(a).read_bytes() == a_raw, "C 원본 사진 그대로")
    chk(not any(n.endswith(".polypix-tmp") for n in os.listdir(tmp)), "C 임시 파일이 남지 않는다")

    # D
    import viewer.widgets.image_to_pdf_dialog as _idm
    real_img = _idm.ImageToPdfDialog

    class FakeImg:
        def __init__(self, parent, initial_paths=None, **kw):
            self._p = list(initial_paths or [])

        def exec(self):
            return True

        def result_paths(self):
            return self._p

        def nup_enabled(self):
            return False
    _idm.ImageToPdfDialog = FakeImg
    dst = str(tmp / "out" / "모음.pdf"); Path(dst).parent.mkdir()
    mw._save_pdf_dialog = lambda name: dst
    opened = []
    mw._open_pdf_new_window = lambda p: opened.append(str(p))
    try:
        mw._photo_action("to_pdf", [a, b]); pump(timeout=2)
    finally:
        _idm.ImageToPdfDialog = real_img
    chk(opened == [dst], "D 만든 PDF 를 새 창으로 연다", str(opened))
    if Path(dst).exists():
        with fitz.open(dst) as d2:
            chk(d2.page_count == 2 and d2[0].rotation == 90 and (len(d2[0].get_drawings()) > 0 or len(d2[0].get_xobjects()) > 0),
                "D 이미지 → PDF 창으로 만든 PDF 에도 회전·꾸밈", "%d %d" % (d2.page_count, d2[0].rotation))
    else:
        chk(False, "D PDF 가 만들어졌다")

    # E
    chk(mw._cmds["file.print"].isEnabled() and mw._cmds["file.flatten"].isEnabled(), "E 사진 모드에서 인쇄·평탄화 켜짐")
    mw._photo_context_menu(QPoint(5, 5))
    chk("인쇄" in menu_texts and "저장" in menu_texts, "E 본문 사진 메뉴에 인쇄·저장 ▸(평탄화 사본은 그 안 — 261107-2, test_ctx_menu_order)", str(menu_texts))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
