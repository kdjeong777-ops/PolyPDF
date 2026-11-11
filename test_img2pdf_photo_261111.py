# -*- coding: utf-8 -*-
"""261111-2·-3·-4: 사진 모드 썸네일 여러 장 → 'PDF 저장' → 이미지 → PDF 창 (사진 보기 SOT §4.21, 이미지 PDF SOT §2).

사용자 보고(2026-11-11): "썸네일에서 여러 썸네일을 선택한 후 pdf 만들기가 안되. 중간에 뜬 창에 리스트가 없어."
원인: 창이 받는 확장자가 `IMAGE_EXTS`(png·jpg …)라 사진 모드가 넘긴 HEIC·HEIF 를 조용히 버렸다 — 아이폰 사진만 고르면 목록이 비어
[PDF로 저장] 에서 '변환할 이미지를 추가하세요'.

실제 MainWindow(오프스크린, 시험 설정 폴더)·실제 썸네일 줄 Ctrl+클릭·실제 우클릭 메뉴 줄로:
A. 고른 세 장(.jpg·.png·.heic)이 이미지 → PDF 창 목록에 모두 실린다(목록 차례 = 넘긴 차례의 자연 정렬)
B. HEIC 도 PDF 쪽이 된다 — 원본 그대로·줄여 넣기 두 길
C. 목록 보기 [이름 | 썸네일] — 기본 썸네일(칸 격자), 이름이면 한 줄씩, 두 보기 모두 끌기 = 줄 옮기기(InternalMove)
D. 고른 보기는 기억한다(취소해도) — 다음에 연 창이 그 보기
E. 이름 'PDF 만들기' → 'PDF 저장'(사진 줄·저장 ▸), 옛 이름 없음
F. 창이 받는 확장자 이름은 ACCEPT_EXTS — image_page.IMAGE_EXTS(HEIC 없음)와 겹치지 않는다(261111-29)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, Qt
QStandardPaths.setTestModeEnabled(True)             # 검사 작성 SOT §14.7.2
from PyQt6.QtWidgets import QApplication, QMenu, QListView, QAbstractItemView
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_img2pdf_photo_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 → PDF 저장", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=10.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


seen = {"pick": None, "all": []}


def _all(menu):
    out = []
    for x in menu.actions():
        if x.isSeparator():
            continue
        if x.menu() is not None:
            out.extend(_all(x.menu()))
        else:
            out.append(x)
    return out


def fake_exec(self, *a, **k):
    seen["all"] = [x.text().split("\t")[0] for x in _all(self)]
    pick, seen["pick"] = seen["pick"], None
    for x in _all(self):
        if pick and x.text().split("\t")[0] == pick:
            return x                                 # 메뉴(ctx_menu.CtxMenu.exec)가 눌러 준다
    return None


QMenu.exec = fake_exec

from viewer.widgets import image_to_pdf_dialog as itp
opened = []
script = {"do": None}


def fake_dlg_exec(dlg):
    pump(lambda: all(not dlg.lst.item(i).icon().isNull() for i in range(dlg.lst.count())), timeout=5)
    opened.append({"paths": dlg.result_paths(), "view": getattr(dlg, "view_mode", lambda: None)(), "dlg": dlg,
                   "icons": sum(1 for i in range(dlg.lst.count()) if not dlg.lst.item(i).icon().isNull())})
    if script["do"]:
        script["do"](dlg)
    return 0                                         # 취소 — 저장 길은 B 가 따로 본다


itp.ImageToPdfDialog.exec = fake_dlg_exec

tmp = Path(tempfile.mkdtemp(prefix="polypdf_img2pdf_photo_"))
try:
    from PIL import Image
    Image.new("RGB", (800, 400), (200, 60, 60)).save(tmp / "a1.jpg", "JPEG")
    Image.new("RGB", (600, 300), (60, 160, 60)).save(tmp / "b2.png")
    # 아이폰 HEIC 흉내 — 해독기(pi-heif)는 읽기 전용이라 HEIC 를 만들 수 없다. 창이 버리던 까닭은 **확장자**이므로
    #   JPEG 바이트에 .heic 이름을 준다(Pillow 는 머리로 열어 썸네일·PDF 쪽이 된다).
    Image.new("RGB", (500, 250), (60, 60, 200)).save(tmp / "c3.heic", "JPEG")
    a, b, c = (str(tmp / n) for n in ("a1.jpg", "b2.png", "c3.heic"))

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw.open_folder(tmp); pump(timeout=1.5)
    mw._set_photo_mode(True)
    strip = mw._photo_strip
    pump(lambda: all(p in strip._items for p in (a, b, c)), timeout=8)
    mw._on_bookmark_activated(a, 0); pump(timeout=0.8)

    def click(path):
        it = strip._items[path]
        strip.scrollToItem(it)
        QTest.mouseClick(strip.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                         strip.visualItemRect(it).center())
        pump(timeout=0.4)
    click(b); click(c)
    chk(sorted(strip.selected_paths()) == sorted([a, b, c]), "준비 — 썸네일 줄 Ctrl+클릭으로 세 장(.jpg·.png·.heic)", str(strip.selected_paths()))

    # ── F. 창이 받는 확장자 이름(261111-29) — image_page.IMAGE_EXTS(HEIC 없음)와 같은 이름·다른 내용이면 헷갈린다 ──
    from viewer.widgets import image_to_pdf_dialog as _dmod
    from viewer import image_page as _ip
    chk(not hasattr(_dmod, "IMAGE_EXTS") and ".heic" in getattr(_dmod, "ACCEPT_EXTS", ()) and ".heic" not in _ip.IMAGE_EXTS,
        "F 창의 받는 확장자는 ACCEPT_EXTS(HEIC 포함) — image_page.IMAGE_EXTS 와 이름이 겹치지 않는다",
        str(sorted(k for k in vars(_dmod) if k.endswith("_EXTS"))))

    # ── E. 이름 ──────────────────────────────────────────────────────
    strip.menuRequested.emit(c, QPoint(10, 10)); pump()
    allm = list(seen["all"])
    chk("고른 사진 3장으로 PDF 저장" in allm and "PDF 저장 (3장)" in allm and "줄의 사진 3장 모두로 PDF 저장" in allm,
        "E 썸네일 줄 메뉴 — 'PDF 저장'(고른 사진 줄·저장 ▸·줄 전체)", str(allm))
    chk(not any("PDF 만들기" in t for t in allm), "E 사진 메뉴에 옛 이름 'PDF 만들기' 없음", str(allm))

    # ── A. 고른 세 장이 창 목록에 ────────────────────────────────────
    # 이름(E)과 따로 보려고 옛 이름 줄도 받는다 — 수정 전 코드로 돌리면 A 는 HEIC 가 빠져 실패한다
    seen["pick"] = next((t for t in allm if t in ("고른 사진 3장으로 PDF 저장", "고른 사진 3장으로 PDF 만들기")), None)
    strip.menuRequested.emit(c, QPoint(10, 10)); pump(lambda: bool(opened), timeout=5)
    got = opened[-1]["paths"] if opened else []
    chk(sorted(got) == sorted([a, b, c]), "A 고른 세 장이 이미지 → PDF 창 목록에 모두(HEIC 포함)", str(got))
    chk(opened and opened[-1]["icons"] == 3, "A 목록 그림(배경 줄여 읽기)이 세 장 모두 붙는다", str(opened[-1]["icons"] if opened else None))

    # ── C. 목록 보기 ─────────────────────────────────────────────────
    dlg = opened[-1]["dlg"] if opened else None
    if dlg is not None:
        lst = dlg.lst
        chk(opened[-1]["view"] == "thumb" and lst.viewMode() == QListView.ViewMode.IconMode
            and dlg.btn_view["thumb"].isChecked(), "C 기본은 썸네일 보기(칸 격자)", f"{opened[-1]['view']} {lst.viewMode()}")
        chk(lst.movement() == QListView.Movement.Snap and lst.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove,
            "C 썸네일 보기도 끌기 = 줄 옮기기(Snap·InternalMove — 쪽 썸네일 편집과 같은 조합)", f"{lst.movement()} {lst.dragDropMode()}")
        QTest.mouseClick(dlg.btn_view["name"], Qt.MouseButton.LeftButton); pump(timeout=0.2)
        chk(dlg.view_mode() == "name" and lst.viewMode() == QListView.ViewMode.ListMode
            and lst.movement() == QListView.Movement.Static and lst.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove,
            "C [이름] — 한 줄씩, 끌기 그대로", f"{dlg.view_mode()} {lst.viewMode()}")
        chk(dlg.result_paths() == got, "C 보기를 바꿔도 목록 차례 그대로", str(dlg.result_paths()))

    # ── D. 고른 보기 기억 ────────────────────────────────────────────
    script["do"] = lambda d: QTest.mouseClick(d.btn_view["name"], Qt.MouseButton.LeftButton)
    mw.action_image_to_pdf(initial_paths=[a]); pump(timeout=0.2)
    script["do"] = None
    chk((mw._prefs.get("img2pdf") or {}).get("list_view") == "name", "D 취소해도 고른 보기를 기억", str(mw._prefs.get("img2pdf")))
    mw.action_image_to_pdf(initial_paths=[a]); pump(timeout=0.2)
    chk(opened[-1]["view"] == "name" and opened[-1]["dlg"].lst.viewMode() == QListView.ViewMode.ListMode,
        "D 다음에 연 창은 그 보기(이름)", opened[-1]["view"])
    chk("img2pdf" in mw._prefs and isinstance(mw._prefs["img2pdf"], dict), "D 설정 허용 목록에 img2pdf 묶음")
    mw._apply_prefs(dict(mw._prefs))
    chk((mw._prefs.get("img2pdf") or {}).get("list_view") == "name", "D 설정을 다시 읽어도 남는다(허용 목록)", str(mw._prefs.get("img2pdf")))

    # ── B. HEIC 도 PDF 쪽 ────────────────────────────────────────────
    import fitz
    for ds in (False, True):
        out = str(tmp / ("out_%d.pdf" % ds))
        ok = mw._images_to_pdf([a, b, c], out, downscale=ds)
        n = fitz.open(out).page_count if ok and os.path.isfile(out) else 0
        chk(n == 3, "B HEIC 도 PDF 쪽 — %s" % ("줄여 넣기" if ds else "원본 그대로"), str(n))
    # PDF 모드 저장 ▸ 의 같은 이름은 test_ctx_menu_order·test_thumb_menu_261016·test_file_rename_menu 가 본다
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
