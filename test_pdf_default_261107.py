# -*- coding: utf-8 -*-
"""기본 PDF 앱으로 설정 — Windows 기본 앱 화면을 연다 (261107-14, 마스터 §14.10).

**실제 레지스트리·Windows 설정은 건드리지 않는다** — 가짜 레지스트리(`FakeReg`)·가짜 화면 열기만. 처리기가 가짜를 받지 못하면
(수정 전 코드) 부르지 않고 실패로 적는다(그 코드는 실제 HKCU 에 쓴다).
A. 설치판(HKLM 등록이 이 exe): HKCU 에 쓰지 않고 `registeredAppMachine` 을 연다, 옛 HKCU PolyPDF 키는 지운다, 다른 앱의 값은 그대로
B. HKLM 이 다른 exe 를 가리키면 휴대용처럼(HKCU)
C. 휴대용(설치 정보 없음): HKCU 에 ProgID·OpenWithProgids·Capabilities·RegisteredApplications → `registeredAppUser`
D. 폴더를 옮겨 다시 누르면 HKCU 명령이 새 exe 로
E. 화면을 못 열면 `ms-settings:defaultapps` 로 물러서고, 그것도 안 되면 손으로 고르는 법을 알린다
F. 개발 실행은 아무것도 쓰지 않는다 · 메뉴 이름 '기본 PDF 앱으로 설정'
"""
import inspect, os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_pdf_default_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "기본 PDF 앱", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


class FakeReg:
    """(뿌리, 경로 소문자) → {이름: 값}. 키만 있는 것도 기억한다."""

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


try:
    from viewer import pdf_default as pdd
except Exception:
    pdd = None
chk(pdd is not None, "pdf_default 모듈")

from viewer.app import MainWindow
import viewer.app as appmod
mw = MainWindow(); mw._skip_save_on_close = True
mw.show(); app.processEvents()
fn = mw._register_pdf_handler
safe = "reg" in inspect.signature(fn).parameters and "opener" in inspect.signature(fn).parameters
chk(safe, "처리기가 가짜 레지스트리·화면 열기를 받는다(아니면 실제 레지스트리에 쓰므로 부르지 않는다)")

infos = []
_orig_info = appmod.QMessageBox.information
appmod.QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else ""))
EXE = r"C:\Program Files\PolyPDF\PolyPDF.exe"
EXE2 = r"D:\Tools\PolyPDF\PolyPDF.exe"
_frozen, _exe = getattr(sys, "frozen", None), sys.executable


def run(reg, opener_ok=lambda u: True, exe=EXE, frozen=True):
    opened = []

    def opener(u):
        opened.append(u)
        return opener_ok(u)
    sys.frozen = frozen
    sys.executable = exe
    try:
        fn(reg=reg, opener=opener)
    finally:
        sys.executable = _exe
        if _frozen is None:
            del sys.frozen
        else:
            sys.frozen = _frozen
    return opened


if safe and pdd is not None:
    # A
    r = FakeReg()
    r.set("HKLM", pdd.REG_APPS, "PolyPDF", pdd.CAPS)
    r.set("HKLM", pdd.PROG_KEY + r"\shell\open\command", "", '"%s" "%%1"' % EXE)
    r.set("HKCU", pdd.PROG_KEY + r"\shell\open\command", "", '"C:\\old\\PolyPDF.exe" "%1"')   # 예전 앱이 쓴 키
    r.set("HKCU", pdd.OPEN_WITH, pdd.PROG_ID, None, none_type=True)
    r.set("HKCU", pdd.OPEN_WITH, "Acrobat.Document.DC", None, none_type=True)               # 다른 앱
    r.set("HKCU", r"Software\Classes\Applications\PolyPDF.exe", "FriendlyAppName", "PolyPDF")
    r.writes.clear()
    op = run(r)
    chk(op[:1] == [pdd.URI_MACHINE], "A 설치판은 registeredAppMachine 화면", str(op))
    chk(not [w for w in r.writes if w[0] == "HKCU"], "A 설치판은 HKCU 에 쓰지 않는다", str(r.writes))
    chk(not r.has_key("HKCU", pdd.PROG_KEY) and r.get("HKCU", pdd.OPEN_WITH, pdd.PROG_ID) is None
        and not r.has_key("HKCU", r"Software\Classes\Applications\PolyPDF.exe"), "A 옛 HKCU PolyPDF 키를 지운다")
    chk(r.get("HKCU", pdd.OPEN_WITH, "Acrobat.Document.DC") == b"" and r.has_key("HKCU", pdd.OPEN_WITH),
        "A 다른 앱의 값·.pdf 키는 그대로")
    chk(r.get("HKLM", pdd.REG_APPS, "PolyPDF") == pdd.CAPS, "A HKLM 은 그대로")

    # B
    r = FakeReg()
    r.set("HKLM", pdd.REG_APPS, "PolyPDF", pdd.CAPS)
    r.set("HKLM", pdd.PROG_KEY + r"\shell\open\command", "", '"%s" "%%1"' % EXE)
    op = run(r, exe=EXE2)
    chk(op[:1] == [pdd.URI_USER] and r.get("HKCU", pdd.PROG_KEY + r"\shell\open\command", "") == '"%s" "%%1"' % EXE2,
        "B HKLM 이 다른 exe 면 휴대용처럼 HKCU", str(op))

    # C
    r = FakeReg()
    op = run(r, exe=EXE2)
    chk(op[:1] == [pdd.URI_USER], "C 휴대용은 registeredAppUser 화면", str(op))
    chk(r.get("HKCU", pdd.PROG_KEY + r"\shell\open\command", "") == '"%s" "%%1"' % EXE2
        and r.get("HKCU", pdd.OPEN_WITH, pdd.PROG_ID) == b""
        and r.get("HKCU", pdd.CAPS + r"\FileAssociations", ".pdf") == pdd.PROG_ID
        and r.get("HKCU", pdd.REG_APPS, "PolyPDF") == pdd.CAPS, "C HKCU 에 설치 프로그램과 같은 꼴")
    chk(not [w for w in r.writes if w[0] == "HKLM"], "C HKLM 에는 쓰지 않는다")

    # D
    EXE3 = r"E:\Moved\PolyPDF.exe"
    run(r, exe=EXE3)
    chk(r.get("HKCU", pdd.PROG_KEY + r"\shell\open\command", "") == '"%s" "%%1"' % EXE3, "D 옮긴 뒤 다시 누르면 새 exe 로")

    # E
    r = FakeReg()
    op = run(r, opener_ok=lambda u: u == pdd.URI_PLAIN, exe=EXE2)
    chk(op == [pdd.URI_USER, pdd.URI_PLAIN], "E 못 열면 ms-settings:defaultapps 로 물러선다", str(op))
    infos.clear()
    op = run(FakeReg(), opener_ok=lambda u: False, exe=EXE2)
    chk(any("연결 프로그램" in t for t in infos), "E 그것도 안 되면 손으로 고르는 법을 알린다", str(infos))

    # F
    r = FakeReg()
    op = run(r, frozen=False)
    chk(not r.writes and not op, "F 개발 실행은 쓰지도 열지도 않는다")

names = []
for a in mw.menuBar().actions():
    m = a.menu()
    if m is None:
        continue
    for b in m.actions():
        if b.menu() is not None and b.text() == "설치·설정":
            names = [c.text() for c in b.menu().actions()]
chk(names[:1] == ["기본 PDF 앱으로 설정"], "F 메뉴 이름 '기본 PDF 앱으로 설정'", str(names))

appmod.QMessageBox.information = _orig_info
mw.close()
print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
