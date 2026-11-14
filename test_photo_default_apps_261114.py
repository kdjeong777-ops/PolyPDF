# -*- coding: utf-8 -*-
"""기본 앱 설정 한 단추 · 보기 종류 기본 혼용 (사진 보기 SOT §4.10·§4.45 '메뉴·단추'·'두 단계', 마스터 §14.10, 261114-7 사용자 지시·결정).

**실제 레지스트리·Windows 설정은 건드리지 않는다** — 가짜 레지스트리·가짜 화면 열기만. 실제 MainWindow(오프스크린, 실제 설정 폴더를
쓰지 않는다 — 마스터 §14.7.2 의 3), 실제 메뉴 항목·환경설정 단추를 누른다.
A. 보기 종류 — 값이 없으면 혼용(사진 단추 보임), 옛 설정 'PDF 전용' 도 한 번 혼용으로, 그 뒤 고른 PDF 전용은 지킨다
B. 환경설정 — '보기 종류' 콤보 **오른쪽 같은 줄**에 [기본 앱 설정], 콤보 아래 사진 전용 단추는 없다, 값 없으면 콤보도 혼용
C. 도구 탭 `설치·설정 ▾` — '기본 앱 설정' 한 항목(명령 id tools.pdf_handler), 사진 항목·tools.photo_handler 는 없다
D. 두 단계 — 혼용: PDF 화면 → [사진 계속] → 사진 화면(PDF·사진 키 둘 다) · [닫기]: PDF 만 · PDF 전용: PDF 만(묻지 않음)
E. 환경설정 단추는 [확인] 전 콤보에서 고른 값을 따른다
F. 개발 실행은 쓰지도 열지도 않는다(안내만)
"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_default_apps_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "기본 앱 설정", echo=False)   # 마스터 §14.7.2 의 6
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


class FakeReg:
    def __init__(self):
        self.keys, self.writes = {}, []

    def _k(self, root, path):
        return (root, path.lower())

    def get(self, root, path, name=""):
        return self.keys.get(self._k(root, path), {}).get(name)

    def has_key(self, root, path):
        return self._k(root, path) in self.keys

    def set(self, root, path, name, value, none_type=False):
        self.writes.append((root, path, name))
        parts = path.split("\\")
        for i in range(1, len(parts) + 1):
            self.keys.setdefault(self._k(root, "\\".join(parts[:i])), {})
        self.keys[self._k(root, path)][name] = b"" if none_type else value

    def delete_value(self, root, path, name):
        d = self.keys.get(self._k(root, path))
        if d is not None and name in d:
            del d[name]
            return True
        return False

    def delete_tree(self, root, path):
        p = path.lower()
        hit = [k for k in self.keys if k[0] == root and (k[1] == p or k[1].startswith(p + "\\"))]
        for k in hit:
            del self.keys[k]
        return bool(hit)


EXE = r"D:\Tools\PolyPDF\PolyPDF.exe"
_frozen, _exe = getattr(sys, "frozen", None), sys.executable


class Frozen:
    def __init__(self, frozen=True):
        self.frozen = frozen

    def __enter__(self):
        sys.frozen = self.frozen
        sys.executable = EXE

    def __exit__(self, *a):
        sys.executable = _exe
        if _frozen is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = _frozen


from viewer import pdf_default as pdd
from viewer import branding as _br                     # 261114-23: 안내의 실행 파일 이름은 이사 판부터 PolyPinax.exe
fake = {"reg": FakeReg()}
pdd.Reg = lambda: fake["reg"]                         # 실제 레지스트리를 만들지 못하게 — 먼저 바꿔 끼운다
from PyQt6.QtGui import QDesktopServices
opened = []
QDesktopServices.openUrl = staticmethod(lambda u: (opened.append(u.toString()), True)[1])
infos = []
QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else "") or 0)
try:
    from viewer import photo_default as phd
    PDF_URI, PHOTO_URI = pdd.URI_USER, phd.URI_USER

    def has_pdf(r):
        return r.get(pdd.HKCU if hasattr(pdd, "HKCU") else None, pdd.REG_APPS, pdd.APP) is not None or any(
            w[1].lower() == pdd.REG_APPS.lower() and w[2] == pdd.APP for w in r.writes)

    def has_photo(r):
        return any(w[1].lower() == pdd.REG_APPS.lower() and w[2] == phd.APP for w in r.writes)

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 850); mw.show(); pump()

    # A — 값이 없으면 혼용, 옛 'PDF 전용' 도 한 번 혼용으로
    pic = mw._prefs.get("picture") or {}
    chk(mw._photo_view_kind() == "mixed" and mw._photo_btn.isVisible(), "A 새 설정 — 보기 종류 혼용(사진 단추 보임)",
        "%s %s" % (mw._photo_view_kind(), pic))
    mw._prefs["picture"] = {"view_kind": "pdf"}            # 옛 설정(표식 없음)
    getattr(mw, "_photo_migrate_view_kind", lambda: None)()     # 시작 때 부르는 그것(_photo_init)
    pic = mw._prefs["picture"]
    chk(pic.get("view_kind") == "mixed" and pic.get("view_kind_261114"), "A 옛 'PDF 전용' 설정도 한 번 혼용으로(표식)", str(pic))
    pic["view_kind"] = "pdf"; mw._photo_apply_view_kind(); pump(0.1)
    getattr(mw, "_photo_migrate_view_kind", lambda: None)()     # 시작 때 부르는 그것(_photo_init)
    chk(mw._prefs["picture"].get("view_kind") == "pdf" and not mw._photo_btn.isVisible(),
        "A 표식 뒤 사용자가 고른 PDF 전용은 지킨다", str(mw._prefs["picture"]))

    # B — 환경설정 콤보 오른쪽
    from viewer.widgets.settings_dialog import SettingsDialog
    mw._prefs["picture"] = {"view_kind_261114": True}       # 값 없음 → 혼용
    dlg = SettingsDialog(mw._prefs, mw, host=mw)
    dlg.show(); pump(0.2)
    btn = getattr(dlg, "btn_default_apps", None)
    cmb = dlg.cmb_view_kind
    chk(cmb.currentData() == "mixed", "B 값이 없으면 콤보도 혼용", str(cmb.currentData()))
    ok_row = False
    if btn is not None:
        bc, cc = btn.mapTo(dlg, btn.rect().center()), cmb.mapTo(dlg, cmb.rect().center())
        ok_row = abs(bc.y() - cc.y()) <= 4 and btn.mapTo(dlg, btn.rect().topLeft()).x() > cmb.mapTo(dlg, cmb.rect().topRight()).x()
    chk(btn is not None and btn.text() == "기본 앱 설정" and btn.isEnabled() and ok_row, "B [기본 앱 설정] 이 보기 종류 콤보 오른쪽 같은 줄")
    chk(not any(b.text() == "기본 사진 앱으로 설정" for b in dlg.findChildren(QPushButton)), "B 콤보 아래 사진 전용 단추는 없다")   # 종전 이름

    # E — 콤보에서 고른 값대로(확인 전)
    if btn is not None:
        fake["reg"] = FakeReg(); opened.clear()
        asked = []
        mw._default_apps_ask = lambda parent: asked.append(1) or True
        cmb.setCurrentIndex(cmb.findData("pdf")); pump(0.05)
        with Frozen():
            btn.click()
        chk(opened[:1] == [PDF_URI] and PHOTO_URI not in opened and not asked and not has_photo(fake["reg"]),
            "E 콤보가 PDF 전용이면 PDF 만(묻지 않음)", str(opened))
        fake["reg"] = FakeReg(); opened.clear(); asked.clear()
        cmb.setCurrentIndex(cmb.findData("mixed")); pump(0.05)
        with Frozen():
            btn.click()
        chk(opened == [PDF_URI, PHOTO_URI] and asked and has_photo(fake["reg"]), "E 콤보가 혼용이면 PDF → [사진 계속] → 사진", str(opened))
    dlg.reject(); dlg.deleteLater(); pump(0.1)

    # C — 도구 탭 한 항목
    from viewer.widgets.ribbon import cmd_id
    inst = None
    for a in mw.menuBar().actions():
        m = a.menu()
        for b in (m.actions() if m is not None else []):
            if b.menu() is not None and b.text() == "설치·설정":
                inst = b.menu()
    items = [a for a in (inst.actions() if inst else []) if not a.isSeparator()]
    names = [a.text() for a in items]
    chk(names[:1] == ["기본 앱 설정"] and "기본 사진 앱으로 설정" not in names and "기본 PDF 앱으로 설정" not in names,   # 종전 이름 두 항목이 없다
        "C 설치·설정 ▾ — '기본 앱 설정' 한 항목", str(names))
    act = next((a for a in items if a.text() == "기본 앱 설정"), None)
    chk(act is not None and cmd_id(act) == "tools.pdf_handler" and "tools.photo_handler" not in mw._cmds,
        "C 명령 id tools.pdf_handler 그대로, tools.photo_handler 없음")

    # D — 두 단계(메뉴 항목으로)
    mw._prefs["picture"] = {"view_kind": "mixed", "view_kind_261114": True}
    if act is not None:
        fake["reg"] = FakeReg(); opened.clear()
        mw._default_apps_ask = lambda parent: True
        with Frozen():
            act.trigger()
        chk(opened == [PDF_URI, PHOTO_URI] and has_pdf(fake["reg"]) and has_photo(fake["reg"]),
            "D 혼용 — PDF 화면 → [사진 계속] → 사진 화면, 둘 다 후보", str(opened))
        fake["reg"] = FakeReg(); opened.clear()
        mw._default_apps_ask = lambda parent: False
        with Frozen():
            act.trigger()
        chk(opened == [PDF_URI], "D [닫기] 면 PDF 화면만 연다", str(opened))
        mw._prefs["picture"]["view_kind"] = "pdf"
        fake["reg"] = FakeReg(); opened.clear(); asked = []
        mw._default_apps_ask = lambda parent: asked.append(1) or True
        with Frozen():
            act.trigger()
        chk(opened == [PDF_URI] and not asked and not has_photo(fake["reg"]), "D PDF 전용 — PDF 만(묻지 않음·사진 키 없음)", str(opened))
        # 가운데 안내 창 — 실제 단추 이름
        del mw._default_apps_ask
        seen = {}
        orig_exec = QMessageBox.exec

        def _look(box):
            seen["btns"] = [b.text() for b in box.buttons()]
            return 0
        QMessageBox.exec = _look
        try:
            mw._default_apps_ask(mw)
        finally:
            QMessageBox.exec = orig_exec
        chk("사진 계속" in seen.get("btns", []) and "닫기" in seen.get("btns", []), "D 안내 창 [사진 계속]·[닫기]", str(seen))

    # F — 개발 실행
    fake["reg"] = FakeReg(); opened.clear(); infos.clear()
    with Frozen(frozen=False):
        mw._register_default_apps(view_kind="mixed")
    chk(not fake["reg"].writes and not opened and any(_br.EXE_NAME in t for t in infos), "F 개발 실행은 쓰지도 열지도 않고 안내만")
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
