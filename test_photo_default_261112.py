# -*- coding: utf-8 -*-
"""기본 앱 설정의 사진 단계 · 사진 인자 → 사진 모드 · 다른 창 넘김 (사진 보기 SOT §4.45, 261112-10 사용자 지시·결정 · 261114-7 PDF 와 한 단추).

**실제 레지스트리·Windows 설정은 건드리지 않는다** — 가짜 레지스트리(`pdf_default.Reg` 를 가짜로 바꿔 끼움)·가짜 화면 열기만.
실제 MainWindow(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3), 실제 메뉴 항목·환경설정 단추를 눌러 본다.
A. HKCU 꼴 — ProgID `PolyPDF.photo`(명령 `"exe" "%1"`)·사진 확장자 전부의 OpenWithProgids·PhotoCapabilities·RegisteredApplications `PolyPDFPhoto`,
   PDF 이름(`PolyPDF.pdf`·`Capabilities`·값 `PolyPDF`)은 쓰지 않는다, 설치판에서도 HKCU(HKLM 에 PDF 등록이 있어도)
B. 설치판의 PDF 단계(옛 HKCU PDF 키 지우기)가 사진 키를 지우지 않는다
C. 개발 실행은 쓰지도 열지도 않는다(안내만)
D. 도구 탭 `설치·설정 ▾` 의 실제 항목 '기본 앱 설정'(혼용 — [사진 계속])을 누르면 사진 등록 + `registeredAppUser=PolyPDFPhoto` 화면, 다시 누르면 새 exe 로
E. 환경설정 '보기 종류' 콤보 오른쪽 [기본 앱 설정] 을 눌러도 같은 등록
F. 명령줄 가르기(`main._startup_args`) — 사진만이면 사진, PDF 가 섞이면 PDF 만, 없는 파일·스위치는 뺀다
G. PDF 전용 · PDF 모드 창에 사진 인자(`_photo_open_arg`) → 혼용으로 바꾸고 사진 모드, 그 폴더가 책갈피창에, 그 사진이 본문에
H. 다른 실행이 넘긴 사진(`instance_link.send_photo`) — 사진 모드인 창은 받아 그 사진을 열고, PDF 모드 창은 받지 않는다
"""
import os, sys, tempfile, shutil, threading, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMessageBox
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_default_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "기본 사진 앱", echo=False)   # 마스터 §14.7.2 의 6
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


class FakeReg:
    """(뿌리, 경로 소문자) → {이름: 값}. 키만 있는 것도 기억한다(test_pdf_default_261107 와 같은 꼴)."""

    def __init__(self):
        self.keys = {}
        self.writes = []

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


EXE = r"C:\Program Files\PolyPDF\PolyPDF.exe"
EXE2 = r"D:\Tools\PolyPDF\PolyPDF.exe"
_frozen, _exe = getattr(sys, "frozen", None), sys.executable


class Frozen:
    def __init__(self, exe=EXE, frozen=True):
        self.exe, self.frozen = exe, frozen

    def __enter__(self):
        sys.frozen = self.frozen
        sys.executable = self.exe

    def __exit__(self, *a):
        sys.executable = _exe
        if _frozen is None:
            if hasattr(sys, "frozen"):
                del sys.frozen
        else:
            sys.frozen = _frozen


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_default_"))
from viewer import pdf_default as pdd
_real_reg = pdd.Reg
fake = {"reg": FakeReg()}
pdd.Reg = lambda: fake["reg"]                         # 처리기가 실제 레지스트리를 만들지 못하게 — 먼저 바꿔 끼운다
from PyQt6.QtGui import QDesktopServices
_real_open = QDesktopServices.openUrl
opened = []
QDesktopServices.openUrl = staticmethod(lambda u: (opened.append(u.toString()), True)[1])
infos = []
_orig_info = QMessageBox.information
QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else ""))
try:
    try:
        from viewer import photo_default as phd
    except Exception:
        phd = None
    chk(phd is not None, "photo_default 모듈")
    from viewer.image_page import PHOTO_EXTS

    def photo_ok(r, exe):
        return (phd is not None
                and r.get("HKCU", phd.PROG_KEY + r"\shell\open\command", "") == '"%s" "%%1"' % exe
                and all(r.get("HKCU", phd.open_with_key(e), phd.PROG_ID) == b"" for e in PHOTO_EXTS)
                and all(r.get("HKCU", phd.CAPS + r"\FileAssociations", e) == phd.PROG_ID for e in PHOTO_EXTS)
                and r.get("HKCU", pdd.REG_APPS, phd.APP) == phd.CAPS)

    # A
    if phd is not None:
        r = FakeReg()
        r.set("HKLM", pdd.REG_APPS, pdd.APP, pdd.CAPS)                                      # 설치판 PDF 등록
        r.set("HKLM", pdd.PROG_KEY + r"\shell\open\command", "", '"%s" "%%1"' % EXE)
        r.writes.clear()
        plan = phd.prepare(EXE, True, r)
        chk(plan["uris"][:1] == [phd.URI_USER] and phd.URI_USER.endswith("registeredAppUser=" + phd.APP),
            "A registeredAppUser=PolyPDFPhoto 화면", str(plan))
        chk(photo_ok(r, EXE), "A HKCU 에 ProgID·확장자 전부·PhotoCapabilities·RegisteredApplications(설치판에서도)")
        chk(set(PHOTO_EXTS) >= {".jpg", ".jpeg", ".png", ".heic", ".heif"} and set(phd.EXTS) == set(PHOTO_EXTS),
            "A 후보 확장자 = PHOTO_EXTS 전부(HEIC 포함)", str(phd.EXTS))
        bad = [w for w in r.writes if w[0] != "HKCU" or "polypdf.pdf" in w[1].lower()
               or w[1].lower() == pdd.CAPS.lower() or (w[1].lower() == pdd.REG_APPS.lower() and w[2] == pdd.APP)]
        chk(not bad, "A PDF 이름·HKLM 에는 쓰지 않는다", str(bad))

        # B
        pdd.prepare(EXE, True, r)                                                          # 설치판 '기본 앱 설정' 의 PDF 단계
        chk(photo_ok(r, EXE), "B 설치판 PDF 정리가 사진 키를 지우지 않는다")

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 850); mw.show(); pump()

    # C
    fake["reg"] = FakeReg(); opened.clear(); infos.clear()
    fn = getattr(mw, "_register_default_apps", None)
    chk(fn is not None, "C 창에 기본 앱 처리기")
    if fn is not None:
        with Frozen(frozen=False):
            fn()
        chk(not fake["reg"].writes and not opened and any(__import__("viewer.branding", fromlist=["x"]).EXE_NAME in t for t in infos),
            "C 개발 실행은 쓰지도 열지도 않고 안내만", "%s %s %s" % (fake["reg"].writes, opened, infos))

    # D
    from viewer.widgets.ribbon import cmd_id
    inst = None
    for a in mw.menuBar().actions():
        m = a.menu()
        for b in (m.actions() if m is not None else []):
            if b.menu() is not None and b.text() == "설치·설정":
                inst = b.menu()
    items = [a for a in (inst.actions() if inst else [])]
    names = [a.text() for a in items]
    chk(names[:1] == ["기본 앱 설정"] and names.count("기본 앱 설정") == 1, "D 설치·설정 ▾ — '기본 앱 설정' 한 항목(261114-7)", str(names))
    act = next((a for a in items if cmd_id(a) == "tools.pdf_handler"), None)
    chk(act is not None, "D 명령 id tools.pdf_handler(모음 단추가 남게 그대로)")
    mw._default_apps_ask = lambda parent: True                 # 두 단계 가운데 [사진 계속]
    if act is not None and phd is not None:
        fake["reg"] = FakeReg(); opened.clear()
        with Frozen(EXE2):
            act.trigger()
        chk(photo_ok(fake["reg"], EXE2) and phd.URI_USER in opened, "D 메뉴 항목을 누르면 HKCU 등록 + 기본 앱 화면", str(opened))
        with Frozen(r"E:\Moved\PolyPDF.exe"):
            act.trigger()
        chk(photo_ok(fake["reg"], r"E:\Moved\PolyPDF.exe"), "D 옮긴 뒤 다시 누르면 새 exe 로")

    # E
    from viewer.widgets.settings_dialog import SettingsDialog
    dlg = SettingsDialog(mw._prefs, mw, host=mw)
    btn = getattr(dlg, "btn_default_apps", None)
    chk(btn is not None and btn.isEnabled() and btn.text() == "기본 앱 설정", "E 환경설정 보기 종류 옆 단추")
    if btn is not None and phd is not None:
        fake["reg"] = FakeReg(); opened.clear()
        with Frozen(EXE2):
            btn.click()
        chk(photo_ok(fake["reg"], EXE2) and phd.URI_USER in opened, "E 단추를 눌러도 같은 등록", str(opened))
    dlg.deleteLater()

    # F
    from PIL import Image
    a_jpg, b_png = tmp / "가 사진.jpg", tmp / "나 그림.png"
    Image.new("RGB", (320, 200), (30, 160, 60)).save(a_jpg, "JPEG")
    Image.new("RGB", (200, 320), (200, 60, 60)).save(b_png, "PNG")
    pdf = tmp / "문서.pdf"
    import fitz
    d = fitz.open(); d.new_page(); d.save(str(pdf)); d.close()
    try:
        import main as mainmod
        sa = mainmod._startup_args
    except Exception as e:
        sa = None
        print("main import:", e)
    chk(sa is not None, "F main._startup_args")
    if sa is not None:
        chk(sa([str(a_jpg), str(b_png)]) == ([], [str(a_jpg), str(b_png)]), "F 사진만 → 사진 목록", str(sa([str(a_jpg)])))
        chk(sa([str(a_jpg), str(pdf)]) == ([str(pdf)], []), "F PDF 가 섞이면 PDF 만", str(sa([str(a_jpg), str(pdf)])))
        chk(sa(["--printed", str(tmp / "없음.jpg"), str(a_jpg).upper().replace(".JPG", ".JPG")])[1] == [str(a_jpg).upper()],
            "F 스위치·없는 파일은 빼고 대문자 확장자도 사진")

    # G
    mw._prefs.setdefault("picture", {})["view_kind"] = "pdf"
    mw._prefs["photo_kind_ocr"] = False
    mw._photo_apply_view_kind()
    chk(not mw._photo_mode and not mw._photo_enabled(), "G 준비 — PDF 전용·PDF 모드")
    ok = getattr(mw, "_photo_open_arg", lambda p: False)(str(b_png))
    pump(lambda: mw.main_view.current_file() is not None and os.path.normcase(str(mw.main_view.current_file())) == os.path.normcase(str(b_png)))
    chk(ok and mw._photo_mode and mw._prefs["picture"].get("view_kind") == "mixed", "G 혼용으로 바꾸고 사진 모드",
        "%s %s %s" % (ok, mw._photo_mode, mw._prefs["picture"].get("view_kind")))
    root = getattr(mw.bookmark_tree, "_root_dir", None)
    chk(root is not None and Path(root).resolve() == tmp.resolve(), "G 그 사진의 폴더가 책갈피창에", str(root))
    cur = mw.main_view.current_file()
    chk(cur is not None and os.path.normcase(str(cur)) == os.path.normcase(str(b_png)), "G 그 사진이 본문에", str(cur))

    # H
    try:
        from viewer.instance_link import send_photo
    except Exception:
        send_photo = None
    chk(send_photo is not None, "H instance_link.send_photo")
    if send_photo is not None:
        def ask(p):
            res = {}
            th = threading.Thread(target=lambda: res.setdefault("ok", send_photo(str(p))), daemon=True)
            th.start()
            pump(lambda: "ok" in res, timeout=8)
            return res.get("ok")
        got = ask(a_jpg)
        pump(lambda: os.path.normcase(str(mw.main_view.current_file() or "")) == os.path.normcase(str(a_jpg)), timeout=5)
        chk(got is True and os.path.normcase(str(mw.main_view.current_file() or "")) == os.path.normcase(str(a_jpg)),
            "H 사진 모드인 창이 받아 그 사진을 연다", "%s %s" % (got, mw.main_view.current_file()))
        mw._set_photo_mode(False)
        pump(timeout=0.5)
        cur_pdf = mw.main_view.current_file()
        got = ask(b_png)
        pump(timeout=0.5)
        chk(got is False and not mw._photo_mode and mw.main_view.current_file() == cur_pdf,
            "H PDF 모드 창은 받지 않는다(보던 것 그대로)", "%s %s" % (got, mw._photo_mode))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    pdd.Reg = _real_reg
    QDesktopServices.openUrl = _real_open
    QMessageBox.information = _orig_info
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
