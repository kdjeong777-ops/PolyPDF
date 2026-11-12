# -*- coding: utf-8 -*-
"""변환·다듬기 창 배치·기억 (사진 보기 SOT §4.46 '창 배치·기억', 디자인 SOT §2.23, 스크린샷 SOT §4.1, 261113-4 사용자 지시·결정).

실제 MainWindow(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3)의 실제 부르는 길
(사진 '변환' `_photo_convert` · 스크린샷 '다듬기' `_shot_tune`)로 창을 연다 — 창의 exec 만 '보이고 검사' 로 바꾼다.
A. 배치 — '그림으로 저장'(형식) → '꾸미기' → 구역 '바탕 정리'(바탕 지우기·가리기) · '색 고치기'(흑백·글씨·선 색·색 바꾸기) · '밝기 보정'(스캔·밝기·대비) 차례
B. 바탕 지우기 — 처음 사진 '밝은 바탕'·스크린샷 '없음', 그 뒤 마지막 고른 값(사진·스크린샷 따로)
C. 가리기 색 막대 — 검정·흰색·회색·모자이크 단추, 흰색을 누르면 흰 가림, [＋] 색 지정은 사용자 색 맨 앞(최대 6), 끌어 놓기로 차례 바꿈, 차례·색 기억
D. 설정 `image_tune` 이 _apply_prefs 를 지나도 남는다
E. 미리보기가 도는 중 창을 닫아 지워도 앱이 꺼지지 않는다(배경 스레드는 모듈 목록에서 끝까지)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QMimeData, QPointF, QEvent
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QGroupBox, QToolButton, QLabel, QColorDialog
from PyQt6.QtGui import QColor, QDropEvent
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tune_layout_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "변환 창 배치", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(t=0.3):
    end = time.monotonic() + t
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_idle(dlg, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if not dlg.busy() and dlg._last_preview is not None:
            return True
        time.sleep(0.01)
    return False


def gy(w, dlg):
    return w.mapTo(dlg, w.rect().topLeft()).y()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tune_layout_"))
try:
    from PIL import Image
    src = tmp / "사진.jpg"
    Image.new("RGB", (400, 300), (200, 30, 30)).save(src, "JPEG")
    from viewer.app import MainWindow
    from viewer.widgets import image_tune_dialog as itd
    from viewer import image_tune as it
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()

    hook = {"fn": None}

    def _exec(self):
        self.show(); pump(0.3)
        try:
            hook["fn"](self)
        finally:
            self.close()
        return 0
    itd.ImageTuneDialog.exec = _exec

    def open_photo(fn):
        hook["fn"] = fn
        mw._photo_convert([str(src)])

    def open_shot(fn):
        hook["fn"] = fn
        mw._shot_tune([str(src)])

    def bar_keys(dlg):
        return [b.property("colorKey") for b in dlg.findChildren(QToolButton) if b.property("colorKey")]

    # A — 배치
    def a_layout(dlg):
        boxes = {g.title(): g for g in dlg.findChildren(QGroupBox)}
        names = ["그림으로 저장", "바탕 정리", "색 고치기", "밝기 보정"]
        chk(all(n in boxes for n in names), "A 구역 넷(그림으로 저장·바탕 정리·색 고치기·밝기 보정)", str(list(boxes)))
        if not all(n in boxes for n in names):
            return
        deco = next((l for l in dlg.findChildren(QLabel) if l.text() == "꾸미기"), None)
        ys = [gy(boxes["그림으로 저장"], dlg)] + ([gy(deco, dlg)] if deco else [-1]) + [gy(boxes[n], dlg) for n in names[1:]]
        chk(deco is not None and ys == sorted(ys) and deco.font().bold(), "A 차례 — 형식 → 꾸미기(굵게) → 바탕 정리 → 색 고치기 → 밝기 보정", str(ys))

        def inside(w, box):
            return box.isAncestorOf(w)
        chk(inside(dlg.cmb_fmt, boxes["그림으로 저장"]), "A 형식은 '그림으로 저장'")
        chk(inside(dlg.rb_thr, boxes["바탕 정리"]) and inside(dlg.btn_mask, boxes["바탕 정리"])
            and gy(dlg.rb_thr, dlg) < gy(dlg.btn_mask, dlg), "A 바탕 정리 = 바탕 지우기, 그 아래 가리기")
        chk(all(inside(w, boxes["색 고치기"]) for w in (dlg.cmb_gray, dlg.cmb_ink, dlg.btn_sw_pick)), "A 색 고치기 = 흑백·글씨·선 색·색 바꾸기")
        chk(all(inside(w, boxes["밝기 보정"]) for w in (dlg.cb_scan, dlg.cb_level, dlg.sl_bri)), "A 밝기 보정 = 스캔·자동·막대")
        hb = dlg.findChildren(type(dlg._sc))[0].horizontalScrollBar() if hasattr(dlg, "_sc") else None
        chk(hb is not None and not hb.isVisible(), "A 색 막대가 들어가도 오른쪽 칸 가로 스크롤 없음")

    open_photo(a_layout)

    # B — 바탕 지우기 처음 값·기억(따로)
    seen = {}

    def b_first_photo(dlg):
        wait_idle(dlg)
        seen["p0"] = (dlg.rb_thr.isChecked(), dlg.params()["bg"], dlg.cmb_fmt.currentData())
        QTest.mouseClick(dlg.rb_none, Qt.MouseButton.LeftButton); pump(0.1)

    def b_first_shot(dlg):
        seen["s0"] = (dlg.rb_none.isChecked(), dlg.params()["bg"])
        QTest.mouseClick(dlg.rb_col, Qt.MouseButton.LeftButton); pump(0.1)

    open_photo(b_first_photo)
    chk(seen.get("p0") == (True, "threshold", "png"), "B 사진 처음 = 밝은 바탕(형식은 PNG 로)", str(seen.get("p0")))
    open_shot(b_first_shot)
    chk(seen.get("s0") == (True, "none"), "B 스크린샷 처음 = 없음", str(seen.get("s0")))
    open_photo(lambda d: seen.__setitem__("p1", (d.rb_none.isChecked(), d.params()["bg"])))
    chk(seen.get("p1") == (True, "none"), "B 사진 다음 = 마지막 고른 '없음'", str(seen.get("p1")))
    open_shot(lambda d: seen.__setitem__("s1", (d.rb_col.isChecked(), d.params()["bg"])))
    chk(seen.get("s1") == (True, "color"), "B 스크린샷 다음 = 마지막 고른 '누른 색'(사진과 따로)", str(seen.get("s1")))

    # C — 가리기 색 막대
    def c_bar(dlg):
        keys = bar_keys(dlg)
        chk(keys[:4] == ["#000000", "#ffffff", "#808080", "mosaic"], "C 처음 차례 검정·흰색·회색·모자이크", str(keys))
        chk(dlg.params()["mask_mode"] == "mosaic", "C 기본 가림 = 모자이크", dlg.params()["mask_mode"])
        white = next(b for b in dlg.findChildren(QToolButton) if b.property("colorKey") == "#ffffff")
        QTest.mouseClick(white, Qt.MouseButton.LeftButton); pump(0.1)
        p = dlg.params(); p.update(masks=[(0.25, 0.25, 0.75, 0.75)], bg="none")
        out = it.apply(Image.new("RGB", (400, 300), (200, 30, 30)), p)
        chk(p["mask_mode"] == "#ffffff" and out.getpixel((200, 150))[:3] == (255, 255, 255)
            and out.getpixel((10, 10))[:3] != (255, 255, 255), "C 흰색 단추 → 흰 가림", str((p["mask_mode"], out.getpixel((200, 150)))))
        cols = ["#12ab34", "#2233cc", "#a0a000", "#00a0a0", "#a000a0", "#505050", "#c08040"]
        orig = QColorDialog.getColor
        try:
            for c in cols:
                QColorDialog.getColor = staticmethod(lambda *a, _c=c, **k: QColor(_c))
                QTest.mouseClick(dlg.bar_mask.btn_add, Qt.MouseButton.LeftButton); pump(0.05)
        finally:
            QColorDialog.getColor = orig
        keys = bar_keys(dlg)
        users = [k for k in keys if k not in itd.MASK_FIXED]
        chk(users == list(reversed(cols))[:itd.MASK_USER_MAX] and dlg.params()["mask_mode"] == "#c08040",
            "C [＋] 색 지정 — 사용자 색 맨 앞, 최대 %d개, 고른 색이 가림" % itd.MASK_USER_MAX, str(keys))
        # 끌어 놓기 — 회색을 맨 앞으로(막대에 실제 놓기 이벤트)
        bar = dlg.bar_mask
        first = next(b for b in dlg.findChildren(QToolButton) if b.property("colorKey") == keys[0])
        md = QMimeData(); md.setData("application/x-polypdf-colorbar", b"#808080")
        pos = QPointF(first.geometry().left() + 2, first.geometry().center().y())
        ev = QDropEvent(pos, Qt.DropAction.MoveAction, md, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        bar.event(ev); pump(0.1)            # QApplication.notify 는 진행 중인 끌기가 없으면 Drop 을 버린다 — 막대의 event() 로 같은 처리기에
        seen["c_order"] = bar_keys(dlg)

    open_photo(c_bar)
    order = seen.get("c_order") or []
    chk(order[:1] == ["#808080"], "C 끌어 놓기로 회색이 맨 앞", str(order))
    open_shot(lambda d: seen.__setitem__("c_shot", bar_keys(d)))
    chk(seen.get("c_shot") == order and order, "C 차례·사용자 색 기억(스크린샷 다듬기도 같은 막대)", str(seen.get("c_shot")))

    # D — 설정 허용목록
    before = dict(mw._prefs.get("image_tune") or {})
    mw._apply_prefs(dict(mw._prefs))
    chk(before and mw._prefs.get("image_tune") == before, "D image_tune 이 _apply_prefs 를 지나도 남는다", str(mw._prefs.get("image_tune")))
    # E — 미리보기가 도는 중 창을 닫아 지워도 앱이 꺼지지 않는다(종전: 창과 함께 QThread 가 지워져 0xC0000409)
    import gc
    big = tmp / "큰.jpg"
    Image.new("RGB", (4000, 3000), (240, 240, 240)).save(big, "JPEG")
    for i in range(4):
        d = itd.ImageTuneDialog(mw, [str(big)], kind="photo", prefs={})
        if i % 2 == 0:
            d.close()                    # 닫고 지움 / 닫지 않고 지움(부모와 함께 지워질 때) — 둘 다 늦게 온 결과를 버린다
        d.deleteLater(); del d
        gc.collect(); pump(0.05)
    end = time.monotonic() + 20
    while time.monotonic() < end and itd._THREADS:
        app.processEvents(); time.sleep(0.02)
    gc.collect(); pump(0.2)
    chk(not itd._THREADS, "E 미리보기 중 창을 닫아 지워도 배경 일이 끝까지 돌고 앱이 꺼지지 않는다")
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
