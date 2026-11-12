# -*- coding: utf-8 -*-
"""사진 모드 '변환' 창 — 그림으로 저장(바탕 지우기·흑백·색 바꾸기·다듬기) + 문서로 (사진 보기 SOT §4.46, 261112-15 사용자 지시·결정).

계산(`viewer.image_tune`)과 실제 창(오프스크린 MainWindow, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 계산 — 밝은 바탕 문턱(자동)·누른 색 지우기·여백 자르기·흑백 두 색·색 바꾸기(고른 색 → 다른 색)·글씨 색·가리기(모자이크·검정)·
   문서 스캔처럼(그림자 고르게)·자동 보정, 투명이면 makes_alpha, 남은 그림 없음 판정
B. 사진 모드 파일·도구 '변환'(act_export) → 변환 창(실제 창): 미리보기가 그려지고, [바탕 누르기] 뒤 미리보기 **마우스 클릭**으로 바탕 색을 집으면
   '누른 색' 이 켜지고 JPEG 은 고를 수 없다(투명), [새 파일로 저장] → 원본 옆 '<이름>_변환.png' 의 바탕은 투명·글씨는 그대로, 원본은 그대로
C. [클립보드로 복사] → 클립보드에 그림 + Windows 'PNG' 형식(투명이 사는 형식)
D. '문서로' 단추 → 창을 닫고 종전 문서 변환 길(`_photo_convert_doc`)
E. zip·휴대 장치 사진은 저장하지 않고 알림(클립보드는 된다)
"""
import os, sys, tempfile, shutil, time, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_image_tune_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "변환 창", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def wait_idle(dlg, timeout_s=10.0):
    """변환 창의 배경 일(미리보기·저장·복사)이 끝날 때까지 이벤트를 돌린다 — 검사 쪽 기다림(앱 코드에는 두지 않는다, 응답성 SOT §6)."""
    t = time.monotonic()
    while time.monotonic() - t < timeout_s:
        QApplication.processEvents()
        if not dlg.busy():
            return True
        time.sleep(0.01)
    return False


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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_image_tune_"))
try:
    from PIL import Image, ImageDraw
    try:
        from viewer import image_tune as it
    except Exception:
        it = None
    chk(it is not None, "image_tune 모듈")

    def paper():
        im = Image.new("RGB", (800, 500), (236, 230, 205))            # 누런 종이
        d = ImageDraw.Draw(im)
        d.rectangle((300, 200, 500, 300), fill=(20, 20, 30))            # 글씨(검은 덩어리)
        d.ellipse((60, 60, 160, 160), fill=(200, 30, 30))               # 빨간 도장
        return im

    # A
    if it is not None:
        im = paper()
        p = it.default_params(); p.update(bg="threshold")
        o = it.apply(im, p)
        chk(o.getpixel((5, 5))[3] == 0 and o.getpixel((400, 250))[3] == 255, "A 밝은 바탕(자동 문턱) 투명·글씨 남음")
        p["trim"] = True
        o2 = it.apply(im, p)
        chk(o2.size[0] < 800 and o2.size[1] < 500 and o2.getbbox() is not None, "A 빈 여백 자르기", str(o2.size))
        p = it.default_params(); p.update(bg="color", bg_colors=[it.pick(im, p, 0.01, 0.01, it.ST_BG)])
        o = it.apply(im, p)
        chk(o.getpixel((5, 5))[3] == 0 and o.getpixel((110, 110))[3] == 255 and o.getpixel((400, 250))[3] == 255,
            "A 누른 색(종이) 지우기 — 도장·글씨는 남음")
        chk(it.makes_alpha(p) and not it.makes_alpha(it.default_params()), "A 투명이 남는 설정 판정")
        p = it.default_params(); p.update(gray="bw")
        o = it.apply(im, p)
        chk(o.getpixel((5, 5))[:3] == (255, 255, 255) and o.getpixel((400, 250))[:3] == (0, 0, 0), "A 흑백 두 색")
        p = it.default_params(); p.update(swap_from=it.pick(im, p, 110 / 800, 110 / 500, it.ST_SWAP), swap_to="#1e1ec8")
        o = it.apply(im, p)
        chk(o.getpixel((110, 110))[:3] == (30, 30, 200) and o.getpixel((400, 250))[:3] == (20, 20, 30),
            "A 색 바꾸기 — 고른 색(빨강)만 파랑으로", str(o.getpixel((110, 110))))
        p = it.default_params(); p.update(ink="blue")
        o = it.apply(im, p)
        chk(o.getpixel((400, 250))[:3] == (16, 48, 160) and o.getpixel((5, 5))[:3] == (236, 230, 205), "A 글씨·선 색 — 글씨만 파랑")
        p = it.default_params(); p.update(masks=[(300 / 800, 200 / 500, 500 / 800, 300 / 500)], mask_mode="black")
        o = it.apply(im, p)
        chk(o.getpixel((400, 250))[:3] == (0, 0, 0) and o.getpixel((5, 5))[:3] == (236, 230, 205), "A 가리기(검정)")
        noisy = Image.effect_noise((800, 500), 80).convert("RGB")
        p = it.default_params(); p.update(masks=[(0, 0, 0.5, 1)])
        o = it.apply(noisy, p)
        blk = [o.getpixel((x, 7)) for x in range(0, 16)]
        chk(len(set(blk)) <= 2, "A 가리기(모자이크) — 칸 안은 한 색", str(len(set(blk))))
        sh = Image.new("RGB", (800, 500), (240, 240, 240))
        d = ImageDraw.Draw(sh)
        for x in range(800):
            d.line((x, 0, x, 499), fill=(240 - x // 6,) * 3)            # 오른쪽으로 갈수록 그림자
        d.rectangle((100, 200, 160, 260), fill=(30, 30, 30)); d.rectangle((650, 200, 710, 260), fill=(20, 20, 20))
        p = it.default_params(); p.update(scan=True)
        o = it.apply(sh, p)
        chk(abs(o.getpixel((20, 20))[0] - o.getpixel((780, 20))[0]) <= 12 and o.getpixel((130, 230))[0] < 60
            and o.getpixel((680, 230))[0] < 60, "A 문서 스캔처럼 — 그림자 고르게·글씨는 검게",
            "%s %s %s" % (o.getpixel((20, 20)), o.getpixel((780, 20)), o.getpixel((680, 230))))
        dim = Image.new("RGB", (100, 100), (90, 90, 90)); ImageDraw.Draw(dim).rectangle((0, 0, 49, 99), fill=(110, 110, 110))
        p = it.default_params(); p.update(auto_level=True)
        o = it.apply(dim, p)
        chk(o.getpixel((10, 10))[0] > 200 and o.getpixel((80, 10))[0] < 50, "A 밝기·대비 자동 — 흐린 사진을 늘린다")
        white = Image.new("RGB", (50, 50), (255, 255, 255))
        chk(not it.has_content(it.apply(white, {"bg": "threshold", "threshold": 128})), "A 남은 그림 없음 판정")

    # B
    src = tmp / "가 종이.jpg"
    paper().save(src, "JPEG", quality=95)
    h0 = hashlib.sha256(src.read_bytes()).hexdigest()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._prefs["photo_kind_ocr"] = False
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    bt = mw.bookmark_tree
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 1)
    mw._on_bookmark_activated(str(src), 0); pump(timeout=0.8)

    from viewer.widgets.image_tune_dialog import ImageTuneDialog
    _orig = ImageTuneDialog.exec
    box = {}

    def scenario(dlg):
        box["dlg"] = dlg
        box["title"] = dlg.windowTitle()
        dlg.show()
        wait_idle(dlg)
        box["preview"] = dlg._last_preview is not None
        from PyQt6.QtTest import QTest
        dlg.btn_bg_pick.click()
        r = dlg.preview._rect()
        QTest.mouseClick(dlg.preview, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(r.left() + 4), int(r.top() + 4)))
        wait_idle(dlg)
        box["col"] = dlg.rb_col.isChecked() and len(dlg._p["bg_colors"]) == 1
        ji = dlg.cmb_fmt.findData("jpg")
        box["jpg_off"] = not dlg.cmb_fmt.model().item(ji).isEnabled() and dlg.cmb_fmt.currentData() != "jpg"
        dlg.btn_save.click()
        wait_idle(dlg, 20)
        box["saved"] = list(dlg.saved)
        # C
        dlg.btn_copy.click()
        wait_idle(dlg, 20)
        pump(timeout=0.5)
        md = QApplication.clipboard().mimeData()
        from viewer import clipboard_util
        box["clip"] = (md is not None and md.hasImage(), md is not None and md.hasFormat(clipboard_util.PNG_MIME))
        dlg.hide()
        return 0

    ImageTuneDialog.exec = scenario
    try:
        mw.act_export.trigger()
        pump(lambda: "clip" in box, timeout=30)
    finally:
        ImageTuneDialog.exec = _orig
    chk(box.get("title") == "변환", "B 사진 모드 '변환' → 변환 창", str(box.get("title")))
    chk(box.get("preview"), "B 미리보기가 그려짐")
    chk(box.get("col"), "B [바탕 누르기] 뒤 미리보기 클릭 → '누른 색' 켜짐·색 하나")
    chk(box.get("jpg_off"), "B 투명이면 JPEG 은 고를 수 없음")
    out = tmp / "가 종이_변환.png"
    chk(out.exists() and box.get("saved") == [(str(src), str(out))], "B 원본 옆 '<이름>_변환.png'", str(os.listdir(tmp)))
    if out.exists():
        with Image.open(out) as o:
            o = o.convert("RGBA")
            chk(o.getpixel((5, 5))[3] == 0 and o.getpixel((400, 250))[3] == 255, "B 새 PNG 의 바탕은 투명·글씨는 그대로")
    chk(hashlib.sha256(src.read_bytes()).hexdigest() == h0, "B 원본은 그대로")
    pump(lambda: bt._file_node_for_path(str(out)) is not None, timeout=3)
    chk(bt._file_node_for_path(str(out)) is not None, "B 새 파일이 책갈피창에")
    chk(box.get("clip") == (True, True), "C 클립보드에 그림 + 'PNG' 형식", str(box.get("clip")))

    # D
    calls = []
    mw._photo_convert_doc = lambda fs, fmt=None: calls.append(list(fs)) or True

    def scen_doc(dlg):
        dlg.doc_buttons["doc"].click()
        return 0
    ImageTuneDialog.exec = scen_doc
    try:
        mw._photo_convert([str(src)])
        pump(lambda: bool(calls), timeout=3)
    finally:
        ImageTuneDialog.exec = _orig
    chk(calls == [[str(src)]], "D '문서로' 단추 → 종전 문서 변환 길", str(calls))

    # E
    infos = []
    _oi = QMessageBox.information
    QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else ""))
    mw._photo_any_cached = lambda ps: True

    def scen_ro(dlg):
        wait_idle(dlg)
        dlg.btn_save.click()
        wait_idle(dlg)
        box["ro_saved"] = list(dlg.saved)
        return 0
    ImageTuneDialog.exec = scen_ro
    try:
        mw._photo_convert([str(src)])
    finally:
        ImageTuneDialog.exec = _orig
        QMessageBox.information = _oi
    chk(not box.get("ro_saved") and any("PC 로 복사" in t for t in infos), "E zip·휴대 장치 사진은 저장하지 않고 알림", str(infos))
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
