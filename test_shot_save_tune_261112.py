# -*- coding: utf-8 -*-
"""스크린샷 컷 — 사진으로 저장·클립보드로 복사·다듬기 (스크린샷 SOT §4.1, 261112-16 사용자 지시·결정 '컷 우클릭 + 머리 단추 하나').

실제 MainWindow(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3)의 실제 스크린샷 스트립. 우클릭 메뉴는 `QMenu.exec` 를 가로채 항목을 고른다.
A. 컷 우클릭 — '사진으로 저장'·'클립보드로 복사'·'다듬기' 가 '삭제' 앞에(차례)
B. '사진으로 저장'(한 장) → 다른 이름으로 저장 창의 경로에 PNG(다듬지 않은 그대로), 여러 장 → 고른 폴더에 장마다
C. '클립보드로 복사'(투명 PNG 한 컷) → 클립보드에 그림 + 'PNG' 형식
D. 머리 [🖌 다듬기] — 고른 컷으로 '다듬기' 창(문서로 묶음 없음), 창에서 바탕 지우기 → 다른 이름으로 저장 경로에 투명 PNG
E. 고른 것이 없으면 본문에 띄운 컷
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu, QFileDialog

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_shot_tune_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "스크린샷 다듬기", echo=False)   # 마스터 §14.7.2 의 6
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


_orig_exec = QMenu.exec
seen = {"menu": None, "pick": None}


def fake_exec(self, *a, **k):
    seen["menu"] = self
    want, seen["pick"] = seen["pick"], None
    if want:
        for x in self.actions():
            if x.text().split("\t")[0].startswith(want):
                x.trigger()
                return x
    return None


tmp = Path(tempfile.mkdtemp(prefix="polypdf_shot_tune_"))
out = tmp / "out"
out.mkdir()
_gs, _gd = QFileDialog.getSaveFileName, QFileDialog.getExistingDirectory
try:
    from PIL import Image, ImageDraw
    shots = []
    for i, name in enumerate(("컷1.png", "컷2.png")):
        im = Image.new("RGBA", (300, 200), (255, 255, 255, 255))
        ImageDraw.Draw(im).rectangle((100, 60, 200, 140), fill=(10, 10, 10, 255))
        if i == 0:
            im.putpixel((0, 0), (255, 255, 255, 0))                     # 투명 점 하나 — 투명 PNG 컷
        im.save(tmp / name, "PNG")
        shots.append(str(tmp / name))
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    strip = mw.shot_strip
    for s in shots:
        strip.add_item(s, kind="image", label=Path(s).stem)
    pump(lambda: strip.list.count() == 2)
    L = strip.list
    shots = [L.item(r).data(strip.DATA_PATH) for r in range(L.count())]     # 스트립 차례(새 컷이 앞)
    QMenu.exec = fake_exec

    # A
    L.clearSelection()
    item0 = L.item(0)
    strip._show_menu(L.visualItemRect(item0).center())
    names = [x.text() for x in seen["menu"].actions() if not x.isSeparator()] if seen["menu"] else []
    chk(names[:4] == ["사진으로 저장", "클립보드로 복사", "다듬기", "삭제"], "A 컷 우클릭 — 저장·복사·다듬기·삭제 차례", str(names))

    # B
    dst1 = out / "하나.png"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(dst1), "PNG (*.png)"))
    seen["pick"] = "사진으로 저장"
    strip._show_menu(L.visualItemRect(item0).center())
    chk(pump(lambda: dst1.exists(), timeout=5) and dst1.read_bytes() == Path(shots[0]).read_bytes(),
        "B 한 장 — 다른 이름으로 저장 경로에 그대로")
    L.clearSelection()
    L.item(0).setSelected(True); L.item(1).setSelected(True)
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(out))
    seen["pick"] = "사진으로 저장"
    strip._show_menu(L.visualItemRect(L.item(1)).center())
    chk(pump(lambda: (out / "컷1.png").exists() and (out / "컷2.png").exists(), timeout=5), "B 여러 장 — 고른 폴더에 장마다", str(os.listdir(out)))
    tpng = next(s for s in shots if s.endswith("컷1.png"))                        # 투명 점이 있는 컷
    item_t = L.item(shots.index(tpng))

    # C
    L.clearSelection()
    QApplication.clipboard().clear()
    seen["pick"] = "클립보드로 복사"
    strip._show_menu(L.visualItemRect(item_t).center())
    pump(timeout=0.5)
    from viewer import clipboard_util
    md = QApplication.clipboard().mimeData()
    chk(md is not None and md.hasImage() and md.hasFormat(clipboard_util.PNG_MIME), "C 한 컷 클립보드 — 그림 + 'PNG' 형식")

    # D
    from viewer.widgets.image_tune_dialog import ImageTuneDialog
    _orig_tune = ImageTuneDialog.exec
    box = {}
    dst2 = out / "다듬은.png"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(dst2), "PNG (*.png)"))

    def scenario(dlg):
        box["paths"], box["title"], box["doc"] = list(dlg._paths), dlg.windowTitle(), bool(dlg.doc_buttons)
        wait_idle(dlg)
        dlg.rb_thr.setChecked(True)
        wait_idle(dlg)
        dlg.btn_save.click()
        wait_idle(dlg, 20)
        return 0
    ImageTuneDialog.exec = scenario
    L.clearSelection()
    L.item(1).setSelected(True)
    try:
        mw.btn_shot_tune.click()
        pump(lambda: dst2.exists(), timeout=15)
    finally:
        ImageTuneDialog.exec = _orig_tune
    chk(box.get("paths") == [shots[1]] and box.get("title") == "다듬기" and box.get("doc") is False,
        "D 머리 [다듬기] — 고른 컷으로 '다듬기' 창(문서로 없음)", str(box))
    if dst2.exists():
        with Image.open(dst2) as o:
            o = o.convert("RGBA")
            chk(o.getpixel((5, 5))[3] == 0 and o.getpixel((150, 100))[3] == 255, "D 바탕 지운 투명 PNG 를 저장 경로에")
    else:
        chk(False, "D 다듬은 PNG 저장", str(os.listdir(out)))

    # E
    L.clearSelection()
    mw._on_screenshot_activated(shots[1], 0); pump(timeout=0.5)
    cur = mw.main_view.current_file()
    chk(mw._shot_targets() == [shots[1]] if cur and os.path.normcase(str(cur)) == os.path.normcase(shots[1]) else mw._shot_targets() == [shots[0]],
        "E 고른 것이 없으면 본문에 띄운 컷(없으면 맨 앞)", "%s %s" % (cur, mw._shot_targets()))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    QFileDialog.getSaveFileName, QFileDialog.getExistingDirectory = _gs, _gd
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
