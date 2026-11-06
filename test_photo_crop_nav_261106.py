# -*- coding: utf-8 -*-
"""사진 모드 — 전자서명 숨김·크롭 창 여러 장 넘기기 (사진 보기 SOT §4.13·§4.40, 261106-1·-3 사용자 지시).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. (-1) 사진 모드면 전자서명 명령이 리본·메뉴에 보이지 않고, 편집 모드 툴바의 전자서명 단추도 숨는다 — PDF 모드로 오면 그대로
B. (-3) 크롭 창 ❮ ❯ — 넘길 사진이 여럿이면 공통 쪽 이동 묶음, 넘기면 지금 사진 여백을 기억하고 다음 사진으로
C. 크롭이 없는 사진은 최근에 정한 크롭(여백 %)을 미리 건다 — 크기가 달라도 같은 %, 크롭이 있는 사진은 제 것
D. [확인] 이면 넘기며 본 사진 모두 한꺼번에(되돌아온 사진은 기억한 값), [취소] 면 아무것도 남지 않는다
E. 범위 — 썸네일 줄에서 고른 사진이 여럿이면 고른 것만
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QDialog
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_crop_nav_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 크롭 넘김", echo=False)   # 마스터 §14.7.2 의 6
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


def r1(t):
    return tuple(round(v, 3) for v in t) if t else None


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_crop_nav_"))
try:
    from PIL import Image
    paths = []
    for name, size, col in (("p1.jpg", (800, 600), (200, 40, 40)), ("p2.jpg", (400, 600), (40, 160, 60)),
                            ("p3.jpg", (1000, 500), (40, 60, 200)), ("p4.jpg", (600, 600), (90, 90, 90))):
        Image.new("RGB", size, col).save(tmp / name, "JPEG")
        paths.append(str(tmp / name))
    p1, p2, p3, p4 = paths

    from viewer.app import MainWindow
    from viewer.widgets.photo_crop_dialog import PhotoCropDialog
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mv = mw.main_view
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()

    # A — 전자서명 숨김
    sign = mw._cmds.get("tools.sign")
    mv.set_draw_mode(True)
    chk(sign is not None and sign.isVisible() and mv.btn_sign.isVisibleTo(mv), "A PDF 모드 — 전자서명 명령·편집 툴바 단추가 보인다")
    mw._set_photo_mode(True); pump()
    chk(not sign.isVisible(), "A 사진 모드 — 전자서명 명령이 리본·메뉴에서 빠진다(회색이 아니라 숨김)")
    shown = [r for r in (mw._ribbon.row(k) for k in mw._ribbon.keys()) if r is not None
             and r.widgetForAction(sign) is not None and r.widgetForAction(sign).isVisibleTo(r)]
    chk(not shown, "A 사진 모드 — 리본 줄에 전자서명 단추가 보이지 않는다", str(len(shown)))
    chk(not mv.btn_sign.isVisibleTo(mv), "A 사진 모드 — 편집 툴바의 전자서명 단추(크롭 오른쪽)도 숨는다")
    mv.set_draw_mode(False); mv.set_draw_mode(True)
    chk(not mv.btn_sign.isVisibleTo(mv), "A 사진 모드에서 편집 모드를 다시 켜도 숨김")
    mw._set_photo_mode(False); pump()
    chk(sign.isVisible() and mv.btn_sign.isVisibleTo(mv), "A PDF 모드로 오면 그대로 보인다")
    mv.set_draw_mode(False)

    # B~D — 크롭 창 넘기기
    mw._set_photo_mode(True); pump()
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 4), "사진 4장 목록")
    mw._on_bookmark_activated(p1, 0); pump(timeout=0.8)
    st = mw._ensure_page_meta_store()
    mw._photo_set_crop(p3, (0.0, 0.1, 1.0, 1.0))      # p3 은 제 크롭(위 10%)이 있다
    pump(timeout=0.3)
    _exec = PhotoCropDialog.exec
    seen = {}

    def go(dlg, i):
        dlg._go(i)
        return pump(lambda: dlg.index() == i and not dlg._loading, timeout=10)

    def fake_exec(self):                               # p1 위 20% → ❯ p2(미리 건 20% 를 왼 10% 로 바꿈) → ❯ p3(제 것) → ❮❮ p1(기억한 값) → [확인]
        pump(lambda: not self._loading, timeout=15)   # 261106-14: 창이 먼저 뜨고 그림은 뒤따른다
        seen["nav"] = (self.nav.isVisible() or self.nav.isVisibleTo(self), self.nav.text())
        P = mw._photo_crop_paths                       # 넘김 차례(목록 정렬 그대로 — 기본 '수정일 순')
        ix = {q: P.index(q) for q in (p1, p2, p3)}
        seen["p1_no"] = ix[p1] + 1
        self.spins[0].setValue(20)
        seen["go2"] = go(self, ix[p2])
        seen["p2_start"] = [round(sp.value(), 1) for sp in self.spins]
        self.spins[0].setValue(0); self.spins[2].setValue(10)
        seen["go3"] = go(self, ix[p3])
        seen["p3_start"] = [round(sp.value(), 1) for sp in self.spins]
        go(self, ix[p2])
        seen["p2_back"] = [round(sp.value(), 1) for sp in self.spins]
        go(self, ix[p1])
        seen["p1_back"] = [round(sp.value(), 1) for sp in self.spins]
        seen["title"] = self.windowTitle()
        return QDialog.DialogCode.Accepted
    PhotoCropDialog.exec = fake_exec
    mw._photo_crop_dialog(p1)
    pump(lambda: "title" in seen or not mw.__dict__.get("_photo_crop_busy"), timeout=20)
    pump(timeout=0.5)
    PhotoCropDialog.exec = _exec
    chk(seen.get("nav", (False, ""))[0] and seen["nav"][1] == "%d / 4" % seen.get("p1_no", 0), "B 넘길 사진이 여럿 — 미리보기 아래 ❮ n / 4 ❯", str(seen.get("nav")))
    chk(seen.get("go2") and seen.get("go3"), "B ❯ 로 다음 사진(그림은 배경에서 풀고 넘어간다)")
    chk(seen.get("p2_start") == [20.0, 0.0, 0.0, 0.0], "C 크롭이 없는 사진(다른 크기)은 최근에 정한 크롭 % 를 미리 건다", str(seen.get("p2_start")))
    chk(seen.get("p3_start") == [10.0, 0.0, 0.0, 0.0], "C 크롭이 있는 사진은 제 크롭", str(seen.get("p3_start")))
    chk(seen.get("p2_back") == [0.0, 0.0, 10.0, 0.0] and seen.get("p1_back") == [20.0, 0.0, 0.0, 0.0],
        "B 되돌아오면 넘길 때 기억한 값", str((seen.get("p2_back"), seen.get("p1_back"))))
    chk("p1.jpg" in seen.get("title", ""), "B 창 제목은 지금 사진 이름", seen.get("title", ""))
    chk(r1(st.photo_crop(p1)) == (0.0, 0.2, 1.0, 1.0) and r1(st.photo_crop(p2)) == (0.1, 0.0, 1.0, 1.0)
        and r1(st.photo_crop(p3)) == (0.0, 0.1, 1.0, 1.0) and st.photo_crop(p4) is None,
        "D [확인] — 넘기며 본 사진 모두 한꺼번에, 안 본 사진은 그대로",
        str([r1(st.photo_crop(p)) for p in paths]))

    def fake_cancel(self):
        pump(lambda: not self._loading, timeout=15)   # 261106-14: 창이 먼저 뜨고 그림은 뒤따른다
        self.spins[1].setValue(30)
        go(self, mw._photo_crop_paths.index(p4))
        self.spins[3].setValue(15)
        return QDialog.DialogCode.Rejected
    PhotoCropDialog.exec = fake_cancel
    before = [st.photo_crop(p) for p in paths]
    mw._photo_crop_dialog(p1)
    pump(lambda: not mw.__dict__.get("_photo_crop_busy"), timeout=20)
    pump(timeout=0.5)
    PhotoCropDialog.exec = _exec
    chk([st.photo_crop(p) for p in paths] == before, "D [취소] — 넘기며 고친 것도 남기지 않는다")

    # E — 고른 사진만
    strip = mw._photo_strip_widget()
    pump(lambda: len(strip.paths()) == 4, timeout=5)
    strip.clearSelection()
    for p in (p2, p4):
        it = strip._items.get(p)
        if it is not None:
            it.setSelected(True)
    chk(mw._photo_crop_range(p2) == [q for q in strip.paths() if q in (p2, p4)], "E 썸네일 줄에서 고른 사진이 여럿이면 그것만", str(mw._photo_crop_range(p2)))
    chk(len(mw._photo_crop_range(p1)) == 4, "E 고른 것 밖의 사진에서 열면 넘김 차례 전체")

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
