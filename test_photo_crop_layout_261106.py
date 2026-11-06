# -*- coding: utf-8 -*-
"""사진 크롭 창 배치 — 두 칸 대칭·가운데 ⇒·조절 칸 가운데·최대화·전체 화면 (디자인 SOT §2.21, 사진 보기 SOT §4.40, 261106-8 사용자 지시).

오프스크린, 실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3).
A. 왼쪽(고치는) 칸과 오른쪽(결과) 칸이 같은 폭, 창 가운데를 두고 대칭 — 사이에 ⇒ 그림(글자 '결과 미리보기' 없음)
B. ❮ ❯·여백 칸·모양 펴기 줄이 왼쪽 칸 가운데(같은 기준선), 안내 글은 오른쪽 칸 아래
C. 제목 줄 최대화 단추, F11 = 전체 화면 켜고 끄기, 전체 화면에서 Esc = 전체 화면만 풀기(창은 그대로)
D. 창을 키우면 두 칸이 함께 커지고(여전히 대칭) 박스 끌기 좌표가 맞다(끈 화소 ÷ 그림 폭 = 여백 %)
E. 닫을 때 자리·크기·최대화를 남기고(전체 화면은 남기지 않음) 다시 열면 그대로 — 실제 창에서
"""
import os, sys, time, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QLabel, QDialog
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_crop_layout_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 크롭 배치", echo=False)
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


def gx(w, dlg):
    """대화상자 좌표의 (왼, 오른, 가운데 x)."""
    tl = w.mapTo(dlg, QPoint(0, 0))
    return tl.x(), tl.x() + w.width(), tl.x() + w.width() / 2.0


def layout_center(lay, dlg):
    r = lay.geometry()
    return r.x() + r.width() / 2.0


def check_sym(dlg, tag):
    l0, l1, lc = gx(dlg.stack, dlg)
    r0, r1, rc = gx(dlg.result, dlg)
    a0, a1, ac = gx(dlg.arrow, dlg)
    mid = dlg.width() / 2.0
    chk(abs(dlg.stack.width() - dlg.result.width()) <= 2, tag + " 두 칸 같은 폭", "%d vs %d" % (dlg.stack.width(), dlg.result.width()))
    chk(abs((l0 + r1) / 2.0 - mid) <= 3 and abs(ac - mid) <= 3, tag + " 창 가운데를 두고 대칭 · ⇒ 가 가운데",
        "칸 %.0f · ⇒ %.0f · 창 %.0f" % ((l0 + r1) / 2.0, ac, mid))
    chk(l1 <= a0 and a1 <= r0, tag + " ⇒ 는 두 칸 사이")


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_crop_layout_"))
try:
    from viewer.widgets.photo_crop_dialog import PhotoCropDialog
    img = QImage(800, 600, QImage.Format.Format_RGB32)
    img.fill(QColor(200, 200, 200))
    dlg = PhotoCropDialog(img, [20, 20, 20, 20], count=5, index=2)
    dlg.resize(1120, 720); dlg.show(); pump()

    # A
    check_sym(dlg, "A")
    texts = [lb.text() for lb in dlg.findChildren(QLabel) if lb.isVisible()]
    chk("결과 미리보기" not in texts, "A '결과 미리보기' 글자는 없다(툴팁·접근성 이름으로만)", str([t for t in texts if "미리" in t]))
    chk(dlg.result.accessibleName() == "결과 미리보기", "A 결과 칸 접근성 이름")
    px = dlg.arrow.pixmap()
    chk(px is not None and not px.isNull() and not dlg.arrow.text(), "A ⇒ 는 그림(글자 아님)")

    # B
    _l, _r, lc = gx(dlg.stack, dlg)
    _a, _b, nc = gx(dlg.nav, dlg)
    sp0 = dlg.spins[0].mapTo(dlg, QPoint(0, 0)).x()
    sp3 = dlg.spins[3].mapTo(dlg, QPoint(0, 0)).x() + dlg.spins[3].width()
    lab0 = [lb for lb in dlg.findChildren(QLabel) if lb.text() == "위"][0].mapTo(dlg, QPoint(0, 0)).x()
    spin_c = (lab0 + sp3) / 2.0
    w0_off = dlg.chk_warp.mapTo(dlg, QPoint(0, 0)).x()
    dlg.chk_warp.setChecked(True); pump(timeout=0.2)
    w0 = dlg.chk_warp.mapTo(dlg, QPoint(0, 0)).x()
    w1 = dlg.btn_corners.mapTo(dlg, QPoint(0, 0)).x() + dlg.btn_corners.width()
    warp_c = (w0 + w1) / 2.0
    chk(w0 == w0_off, "B 모양 펴기를 켜고 꺼도 체크 상자 자리가 그대로", "%d → %d" % (w0_off, w0))
    chk(abs(nc - lc) <= 4 and abs(spin_c - lc) <= 8 and abs(warp_c - lc) <= 8,
        "B ❮ ❯·여백 칸·모양 펴기 줄이 왼쪽 칸 가운데", "칸 %.0f · ❮❯ %.0f · 여백 %.0f · 펴기 %.0f" % (lc, nc, spin_c, warp_c))
    dlg.chk_warp.setChecked(False); pump(timeout=0.2)
    n0 = dlg.note.mapTo(dlg, QPoint(0, 0)).x()
    chk(n0 >= gx(dlg.result, dlg)[0] - 2, "B 안내 글은 오른쪽 칸 아래", "%d vs %d" % (n0, gx(dlg.result, dlg)[0]))

    # C
    chk(bool(dlg.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint), "C 제목 줄 최대화 단추")
    QTest.keyClick(dlg, Qt.Key.Key_F11); pump(timeout=0.3)
    chk(dlg.isFullScreen() and dlg.btn_full.isChecked(), "C F11 = 전체 화면")
    QTest.keyClick(dlg, Qt.Key.Key_Escape); pump(timeout=0.3)
    chk(not dlg.isFullScreen() and dlg.isVisible(), "C 전체 화면에서 Esc = 전체 화면만 풀고 창은 그대로")
    dlg.btn_full.setChecked(True); pump(timeout=0.3)
    chk(dlg.isFullScreen(), "C [전체 화면] 단추도 같은 일")
    dlg.btn_full.setChecked(False); pump(timeout=0.3)

    # D
    dlg.showNormal(); dlg.resize(1600, 1000); pump(timeout=0.4)
    check_sym(dlg, "D(1600)")
    chk(dlg.stack.width() > 600, "D 창을 키우면 칸도 커진다", str(dlg.stack.width()))
    cv = dlg.canvas
    r = cv._img_rect(); c = cv._crop_rect(r)
    a = QPoint(int(c.left()), int(c.center().y()))
    b = QPoint(int(c.left() + r.width() * 0.10), int(c.center().y()))
    QTest.mousePress(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(cv, b)
    QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    pump(timeout=0.2)
    m = dlg.current_margins()
    chk(abs(m[2] - 30.0) <= 0.6, "D 큰 창에서도 끈 화소 = 여백 %(왼 변 +10%)", str(m))
    dlg.showMaximized(); pump(timeout=0.4)
    check_sym(dlg, "D(최대화)")

    # E — 실제 창: 닫을 때 남기고 다시 열면 그대로
    from PIL import Image as PImage
    PImage.new("RGB", (400, 300), (90, 120, 160)).save(tmp / "a.jpg", "JPEG")
    dlg.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump()
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in mw.bookmark_tree._iter_file_nodes()) == 1)
    _exec = PhotoCropDialog.exec
    seen = {}

    def first(self):
        self.show(); self.showNormal(); self.resize(1240, 860); app.processEvents()
        seen["first"] = (self.width(), self.height(), self.minimumSizeHint().width(), self.minimumSizeHint().height())
        self.btn_full.setChecked(True); app.processEvents()      # 전체 화면인 채 닫아도 전체 화면은 남지 않는다
        self.done(QDialog.DialogCode.Rejected)
        return QDialog.DialogCode.Rejected

    def second(self):
        self.show(); app.processEvents()
        seen["size"] = (self.width(), self.height())
        seen["full"] = self.isFullScreen()
        self.done(QDialog.DialogCode.Rejected)
        return QDialog.DialogCode.Rejected
    PhotoCropDialog.exec = first
    mw._photo_crop_dialog(str(tmp / "a.jpg"))
    pump(lambda: not mw.__dict__.get("_photo_crop_busy"), timeout=10); pump(timeout=0.3)
    pic = mw._prefs.get("picture", {})
    chk(bool(pic.get("crop_geom")) and pic.get("crop_max") is False, "E 닫을 때 자리·크기를 남긴다(최대화 아님)", str(pic.get("crop_max")))
    saved1 = pic.get("crop_geom")
    PhotoCropDialog.exec = second
    _rs = PhotoCropDialog.restore_state
    got = {}

    def spy(self, geom_hex="", maximized=False):
        got["args"] = (geom_hex, maximized)
        return _rs(self, geom_hex, maximized)
    PhotoCropDialog.restore_state = spy
    mw._photo_crop_dialog(str(tmp / "a.jpg"))
    pump(lambda: "size" in seen, timeout=10); pump(timeout=0.3)
    PhotoCropDialog.exec = _exec
    PhotoCropDialog.restore_state = _rs
    # 오프스크린 화면은 800×800 이라 Qt 가 자리를 화면 안으로 줄인다 — 크기 값 대신 '남긴 것을 그대로 돌려준다' 를 본다
    chk(got.get("args") == (saved1, False) and seen.get("full") is False,
        "E 다시 열면 남긴 자리·크기로 연다(전체 화면은 아님)", str((bool(got.get("args")), seen)))
    from PyQt6.QtCore import QByteArray
    probe = PhotoCropDialog(img, [0, 0, 0, 0])
    chk(probe.restoreGeometry(QByteArray(bytes.fromhex(pic.get("crop_geom") or ""))), "E 남긴 값은 Qt 가 읽을 수 있는 자리 값")
    probe.restore_state("", True)
    chk(bool(probe.windowState() & Qt.WindowState.WindowMaximized), "E 최대화로 닫았으면 최대화로 연다")
    probe.close()
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
os._exit(1 if fails else 0)
