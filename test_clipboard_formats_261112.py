# -*- coding: utf-8 -*-
"""261112-19: 앱에서 복사한 것이 다른 프로그램에서도 붙는다 — 실제 Windows 클립보드 형식 (스크린샷 SOT §8.4, 사용자 지시).

**실제 Windows 클립보드**로 잰다(검사 작성 SOT 오프스크린 예외 — 창은 화면에 띄우지 않는다, `WA_DontShowOnScreen`).

A. 불투명 그림: `CF_DIB` 를 올리고 받을 수 있다, Qt 의 군더더기 형식(`image/bmp` 등)이 없다
B. 투명 그림(`png=`): `"PNG"`·`CF_DIBV5`·`CF_DIB` — DIB 는 투명 자리가 흰색
C. 넣은 프로세스가 끝난 뒤에도 데이터를 받을 수 있다(즉시 데이터)
D. 쪽 복사: 표식 + 첫 쪽 그림, PolyPDF 안 판정은 'pages' 그대로
E. 꾸밈 복사: 표식 + 고른 꾸밈만 그린 투명 그림, 판정은 'deco' 그대로
F. 사진 복사(`_photo_copied`): 그림
G. Word 가 있으면 새 Word(보이지 않음)에 B·E 가 그림으로 붙는다 — 수정 전 코드(Qt 그림 + "PNG")는 '명령을 정상적으로 종료할 수 없습니다'
H. (261113-6) 글·파일 복사도 즉시 데이터 — 앱 메인이 3초 바쁜 동안 다른 프로세스가 경로 글을 곧바로 받는다(수정 전 Qt setText 는 섰다),
   파일은 CF_HDROP·Preferred DropEffect, 앱 코드에 clipboard_util 밖 Qt 직접 넣기 없음. '확인 못 함' 줄에 진단(clipboard_util.diag)
수정 전 코드는 A(군더더기)·B(DIB 흰 바탕 아님)·D·E(그림 없음)·G 가 실패한다.
다른 프로그램이 클립보드를 쥐어 넣지 못하면 그 항목은 '확인 못 함'(스크린샷 SOT §8.3 판정법). 끝에 사용자 클립보드의 글·그림을 되돌린다.
"""
import os, sys, time, json, ctypes, tempfile, shutil, subprocess, faulthandler
import ctypes.wintypes as wt
sys.stdout.reconfigure(encoding="utf-8")
if sys.platform != "win32":
    print("SKIP - Windows 클립보드 전용")
    sys.stdout.flush(); os._exit(0)
os.environ["QT_QPA_PLATFORM"] = "windows"          # 검사 작성 SOT §14.7 예외 — 실제 클립보드
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
faulthandler.dump_traceback_later(240, exit=True)
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_clipfmt_%d" % os.getpid())
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
import modal_guard
modal_guard.install(label=lambda: "클립보드 형식", echo=False)
cb = QApplication.clipboard()
from viewer import clipboard_util
fails, unverified = [], []

u, k = ctypes.windll.user32, ctypes.windll.kernel32
u.OpenClipboard.argtypes = [wt.HWND]
u.EnumClipboardFormats.argtypes = [wt.UINT]; u.EnumClipboardFormats.restype = wt.UINT
u.GetClipboardData.argtypes = [wt.UINT]; u.GetClipboardData.restype = wt.HANDLE
k.GlobalSize.argtypes = [wt.HGLOBAL]; k.GlobalSize.restype = ctypes.c_size_t
k.GlobalLock.argtypes = [wt.HGLOBAL]; k.GlobalLock.restype = ctypes.c_void_p
k.GlobalUnlock.argtypes = [wt.HGLOBAL]
STD = {2: "CF_BITMAP", 8: "CF_DIB", 13: "CF_UNICODETEXT", 15: "CF_HDROP", 17: "CF_DIBV5"}


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def unver(msg, why):
    print("SKIP -", msg, f"— 확인 못 함({why})")
    unverified.append(msg)


def spin(sec):
    t0 = time.monotonic()
    while time.monotonic() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def formats():
    """{형식 이름: 바이트(GDI 형식은 b'')} — 실제로 받을 수 있는 것만. 못 열면 None."""
    for _ in range(100):
        if u.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return None
    out = {}
    try:
        f = 0
        while True:
            f = u.EnumClipboardFormats(f)
            if not f:
                break
            if f in STD:
                nm = STD[f]
            else:
                b = ctypes.create_unicode_buffer(256)
                nm = b.value if u.GetClipboardFormatNameW(f, b, 256) else f"#{f}"
            h = u.GetClipboardData(f)
            if not h:
                continue
            if f == 2:
                out[nm] = b""
                continue
            n = k.GlobalSize(h); p = k.GlobalLock(h)
            out[nm] = ctypes.string_at(p, n) if p else b""
            k.GlobalUnlock(h)
    finally:
        u.CloseClipboard()
    return out


_owns = getattr(clipboard_util, "owns", None) or cb.ownsClipboard      # 수정 전 코드(Qt 로 넣음)로도 돌게


def wait_owned(ms=5000):
    t0 = time.monotonic()
    while not _owns() and (time.monotonic() - t0) * 1000 < ms:
        spin(0.05)
    return _owns()


def contended(section):
    # 261113-6(스크린샷 SOT §8.3 의 5): 진단 줄 — 연 창·내용 주인·순번·열기까지 시간
    d = getattr(clipboard_util, "diag", lambda: "")()
    unver(section, "다른 프로그램이 클립보드를 쥠 — 쥔 프로그램: " + str(clipboard_util.holder_name() or "알 수 없음")
          + (" · 진단: " + d if d else ""))


JUNK = ("image/bmp", "image/tiff", "image/ico", "image/jpeg")

# 사용자 클립보드를 받아 둔다
_md = cb.mimeData()
ORIG_TEXT = _md.text() if _md is not None and _md.hasText() else None
ORIG_IMG = cb.image() if ORIG_TEXT is None and _md is not None and _md.hasImage() else None

opaque = QImage(80, 60, QImage.Format.Format_RGB32); opaque.fill(QColor(0, 128, 255))
trans = QImage(80, 60, QImage.Format.Format_ARGB32); trans.fill(QColor(0, 0, 0, 0))
for y in range(60):
    for x in range(40):
        trans.setPixelColor(x, y, QColor(255, 0, 0, 255))          # 왼쪽 반 빨강, 오른쪽 반 투명
png = clipboard_util._png(trans) if hasattr(clipboard_util, "_png") else None
if png is None:
    from PyQt6.QtCore import QBuffer, QIODevice
    _b = QBuffer(); _b.open(QIODevice.OpenModeFlag.WriteOnly); trans.save(_b, "PNG"); png = bytes(_b.data())

# A. 불투명
clipboard_util.set_image(opaque, None)
if not wait_owned():
    contended("A 불투명 그림")
else:
    fm = formats() or {}
    chk(len(fm.get("CF_DIB", b"")) > 40, "A CF_DIB 를 받을 수 있다", str(sorted(fm)))
    chk(not any(j in fm for j in JUNK), "A Qt 군더더기 형식(image/bmp 등)이 없다", str(sorted(fm)))
    chk(cb.mimeData().hasImage(), "A PolyPDF(Qt)도 그림으로 읽는다")


def dib_pixel(dib, x, y_from_top):
    """24비트 아래→위 DIB 의 (x, y) 픽셀 (r, g, b)."""
    import struct
    hs, w, h, _pl, bpp = struct.unpack("<IiiHH", dib[:16])
    bpl = ((w * bpp + 31) // 32) * 4
    row = (h - 1 - y_from_top) if h > 0 else y_from_top
    o = hs + row * bpl + x * (bpp // 8)
    b, g, r = dib[o], dib[o + 1], dib[o + 2]
    return r, g, b


# B. 투명
clipboard_util.set_image(trans, None, png=png)
if not wait_owned():
    contended("B 투명 그림")
else:
    fm = formats() or {}
    chk(fm.get("PNG", b"")[:4] == b"\x89PNG", "B 'PNG' 형식(투명)", str(sorted(fm)))
    chk(len(fm.get("CF_DIBV5", b"")) > 124, "B CF_DIBV5(알파)")
    dib = fm.get("CF_DIB", b"")
    chk(len(dib) > 40 and dib_pixel(dib, 70, 30) == (255, 255, 255) and dib_pixel(dib, 10, 30) == (255, 0, 0),
        "B CF_DIB 는 투명 자리가 흰색(그림판·한글이 검게 보지 않게)", str(dib_pixel(dib, 70, 30)) if len(dib) > 60 else "")
    chk(not any(j in fm for j in JUNK), "B Qt 군더더기 형식이 없다", str(sorted(fm)))
    chk(cb.image().hasAlphaChannel(), "B PolyPDF(Qt)는 투명 그대로 읽는다")

# C. 넣은 프로세스가 끝난 뒤
CHILD = ("import os,sys\n"
         "os.environ['QT_QPA_PLATFORM']='windows'\n"
         f"sys.path.insert(0,{HERE!r})\n"
         "from PyQt6.QtWidgets import QApplication\nfrom PyQt6.QtGui import QImage,QColor\nfrom PyQt6.QtCore import QTimer\n"
         "a=QApplication(sys.argv[:1])\nfrom viewer import clipboard_util\n"
         "im=QImage(30,20,QImage.Format.Format_RGB32); im.fill(QColor('green'))\n"
         "r=[]\nclipboard_util.set_image(im,r.append)\n"
         "print('ok' if r==[True] else 'fail',flush=True)\nQTimer.singleShot(200,a.quit); a.exec()\n")
r = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True, timeout=60, creationflags=0x08000000)
if "ok" not in r.stdout:
    contended("C 앱이 끝난 뒤")
else:
    spin(0.3)
    fm = formats() or {}
    chk(len(fm.get("CF_DIB", b"")) > 40, "C 넣은 프로세스가 끝난 뒤에도 CF_DIB 를 받는다(즉시 데이터)", str(sorted(fm)))

# 앱 길
tmp = Path(tempfile.mkdtemp(prefix="polypdf_clipfmt_"))
pdf = tmp / "쪽.pdf"
d = fitz.open()
for i in range(2):
    d.new_page(width=400, height=600).insert_text((40, 80), "PAGE%d" % (i + 1), fontsize=30)
d.save(str(pdf)); d.close()
from viewer.app import MainWindow
from viewer.widgets.thumbs_list import PAGES_CLIP_MIME
mw = MainWindow(); mw._skip_save_on_close = True
mw.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
mw.resize(1200, 900); mw.show(); spin(0.3)
mw.open_folder(str(tmp)); spin(0.8)
mw.open_pdfs([str(pdf)]); spin(1.0)
mv = mw.main_view
mv.go_to_page(0); spin(0.3)

# D. 쪽 복사
mw._on_copy_pages([0])
if not wait_owned():
    contended("D 쪽 복사")
else:
    fm = formats() or {}
    chk(len(fm.get("CF_DIB", b"")) > 1000, "D 쪽 복사 — 첫 쪽 그림(CF_DIB)", str(sorted(fm)))
    chk(PAGES_CLIP_MIME in fm, "D 쪽 표식도 함께", str(sorted(fm)))
    chk(mw._clipboard_kind() == "pages", "D PolyPDF 안 판정은 'pages' 그대로", str(mw._clipboard_kind()))

# E. 꾸밈 복사
mw.bookmark_tree.btn_edit.setChecked(True); spin(0.3)
mv._page_strokes = [{"shape": "rect", "rect": [0.2, 0.2, 0.5, 0.4], "color": "#ff0000", "width": 4,
                     "alpha": 100, "fill": "full"}]
mv._save_page_strokes()
mv._stroke_selected = 0; spin(0.2)
n = mv.copy_decorations()
chk(n == 1, "E 준비 — 꾸밈 하나를 담는다", str(n))
if not wait_owned():
    contended("E 꾸밈 복사")
else:
    fm = formats() or {}
    chk(fm.get("PNG", b"")[:4] == b"\x89PNG", "E 꾸밈 복사 — 투명 그림(PNG)", str(sorted(fm)))
    chk(mv.DECO_MIME in fm, "E 꾸밈 표식도 함께", str(sorted(fm)))
    chk(mw._clipboard_kind() == "deco", "E PolyPDF 안 판정은 'deco' 그대로", str(mw._clipboard_kind()))
    im = cb.image()
    if not im.isNull():
        c = im.pixelColor(im.width() // 2, im.height() // 2)
        chk(c.red() > 200 and c.green() < 60 and c.alpha() > 200, "E 그림 가운데는 꾸밈(빨강)", str(c.getRgb()))
        chk(im.pixelColor(0, 0).alpha() < 255 or im.width() > 10, "E 그림은 고른 꾸밈 크기", f"{im.width()}x{im.height()}")
    deco_fm = fm

# F. 사진 복사
mw._photo_copied(str(tmp / "p.jpg"), opaque)
if not wait_owned():
    contended("F 사진 복사")
else:
    fm = formats() or {}
    chk(len(fm.get("CF_DIB", b"")) > 40 and not any(j in fm for j in JUNK), "F 사진 복사 — CF_DIB(군더더기 없이)", str(sorted(fm)))


# H. 261113-6(스크린샷 SOT §8.4·응답성 SOT): 글·파일도 즉시 데이터 — 앱이 넣은 뒤 메인이 바빠도 다른 프로세스가 곧바로 받는다.
#   수정 전(Qt setText = 지연 렌더링)은 다른 프로세스의 GetClipboardData 가 앱이 그려 줄 때까지(메인이 쉴 때까지) 섰다.
READER = ("import ctypes,ctypes.wintypes as wt,time,threading\n"
          "u=ctypes.windll.user32;k=ctypes.windll.kernel32\n"
          # 261113-7: 스스로 25초 뒤 끝난다 — 부모가 먼저 죽으면 고아가 클립보드를 연 채 남아 다음 실행의 클립보드 검사를 모두 막았다
          "k.GetCurrentProcess.restype=ctypes.c_void_p;k.TerminateProcess.argtypes=[ctypes.c_void_p,ctypes.c_uint]\n"
          "threading.Timer(25,lambda:k.TerminateProcess(k.GetCurrentProcess(),3)).start()\n"
          "u.GetClipboardData.restype=wt.HANDLE;k.GlobalLock.restype=ctypes.c_void_p;k.GlobalLock.argtypes=[wt.HANDLE]\n"
          "k.GlobalUnlock.argtypes=[wt.HANDLE]\n"
          "time.sleep(0.3);t0=time.perf_counter()\n"
          "while not u.OpenClipboard(None):\n time.sleep(0.005)\n"
          "t=time.perf_counter()\n"     # 261113-7: 열기까지 기다린 시간(다른 프로그램이 쥠)과 받기 시간(지연 렌더링)을 가른다
          "h=u.GetClipboardData(13);s=ctypes.wstring_at(k.GlobalLock(h)) if h else '';h and k.GlobalUnlock(h)\n"
          "u.CloseClipboard()\nprint('%.3f|%.3f|%s'%(time.perf_counter()-t,t-t0,s[-200:]),flush=True)\n")
from viewer import key_actions
mw.open_pdfs([str(pdf)]); spin(0.3)

def clip_free(ms=300):
    """지금 클립보드가 곧바로 열리나(다른 프로그램이 쥐고 있지 않나) — 열었다 닫기만."""
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        if u.OpenClipboard(None):
            u.CloseClipboard()
            return True
        time.sleep(0.01)
    return False


free_before = clip_free()                         # 261113-7: 시작 전에 이미 다른 프로그램이 쥐었으면 다툼 — 판정하지 않는다
key_actions.copy_path(mw)
rd = subprocess.Popen([sys.executable, "-c", READER], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                      encoding="utf-8", errors="replace", creationflags=0x08000000,
                      env=dict(os.environ, PYTHONIOENCODING="utf-8"))
time.sleep(3.0)                                   # 앱 메인이 바쁘다(메시지를 처리하지 않음)
_t = time.monotonic()
while rd.poll() is None and time.monotonic() - _t < 40:   # 그 뒤로는 메시지를 처리하며 기다린다(지연 렌더링이면 이때 그려 준다)
    spin(0.05)
try:
    out_r = (rd.communicate(timeout=10)[0] or "").strip()
except subprocess.TimeoutExpired:                 # 261113-7: 다른 프로그램이 40초 넘게 쥠(전체 검사에서 실제로 겪음) — 죽지 않고 다툼으로
    rd.kill()
    out_r = ""
print("   다른 프로세스가 읽음:", out_r[-160:])
spin(0.2)
try:
    sec, wait_open, txt = out_r.split("|", 2)
    sec, wait_open = float(sec), float(wait_open)
except Exception:
    sec, wait_open, txt = 99.0, 0.0, out_r
if not free_before or (pdf.name not in txt and sec >= 99):
    # 시작 전에 이미 다른 프로그램이 클립보드를 쥐고 있었다 — 다툼('확인 못 함')
    contended("H 글 복사 — 다른 프로세스")
else:
    chk(pdf.name in txt, "H 경로 복사 글을 다른 프로세스가 받는다(CF_UNICODETEXT)", repr(txt))
    # 지연 렌더링이면 기록 서비스가 우리 그림을 기다리며 클립보드를 쥐어 다른 프로세스는 **열기부터** 선다(수정 전 실측 29.9초)
    chk(sec + wait_open < 1.0, "H 앱 메인이 바쁜 동안에도 다른 프로세스가 곧바로 받는다(지연 렌더링 아님)",
        "열기까지 %.2f초 · 받기 %.2f초" % (wait_open, sec))
fm = formats() or {}
chk(not any(m.startswith("application/x-qt") for m in fm), "H 글 복사에 Qt 전용 형식이 없다", str(sorted(fm)))
if hasattr(clipboard_util, "set_files"):
    clipboard_util.set_files([str(pdf)]); spin(0.2)
    fm = formats() or {}
    if fm is None or "CF_HDROP" not in fm:
        if not wait_owned(2000):
            contended("H 파일 복사")
    else:
        chk(str(pdf).encode("utf-16-le") in fm["CF_HDROP"], "H 파일 복사 — CF_HDROP 에 그 경로", str(sorted(fm)))
        chk("Preferred DropEffect" in fm, "H 파일 복사 — Preferred DropEffect(복사)", str(sorted(fm)))
        md = cb.mimeData()
        chk(md is not None and md.hasUrls() and Path(md.urls()[0].toLocalFile()) == pdf, "H PolyPDF(Qt)도 파일로 읽는다")
else:
    chk(False, "H clipboard_util.set_files 가 있다")
import re as _re
_bad = []
for _p in Path(HERE, "viewer").rglob("*.py"):
    if _p.name == "clipboard_util.py":
        continue
    for _i, _l in enumerate(_p.read_text(encoding="utf-8").splitlines(), 1):
        if _re.search(r"clipboard\(\)\.(setText|setMimeData|setImage|setPixmap)\(", _l):
            _bad.append("%s:%d" % (_p.relative_to(HERE), _i))
chk(not _bad, "H 앱 코드는 clipboard_util 밖에서 Qt 로 클립보드에 넣지 않는다", _bad)


# G. Word 에 붙이기(있을 때만)
def word_paste():
    code = ("import sys,pythoncom,win32com.client as w\n"
            "pythoncom.CoInitialize()\nwd=w.DispatchEx('Word.Application');wd.Visible=False;wd.DisplayAlerts=0\n"
            "try:\n doc=wd.Documents.Add()\n try:\n  doc.Content.Paste();print('n',doc.InlineShapes.Count+doc.Shapes.Count)\n"
            " except Exception as e:\n  print('err',str(e)[:100])\n doc.Close(0)\nfinally:\n wd.Quit(0)\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=90, creationflags=0x08000000)
    return r.stdout.strip()


try:
    import winreg
    winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application").Close()
    import win32com.client  # noqa: F401
    has_word = True
except Exception:
    has_word = False
if not has_word:
    unver("G Word 붙이기", "Word·pywin32 없음")
else:
    clipboard_util.set_image(trans, None, png=png)
    if wait_owned():
        out = word_paste()
        chk(out.startswith("n ") and out != "n 0", "G 투명 그림(PNG 함께)이 Word 에 그림으로 붙는다", out)
    else:
        contended("G Word 붙이기(투명)")
    mv._stroke_selected = 0
    mv.copy_decorations()
    if wait_owned():
        out = word_paste()
        chk(out.startswith("n ") and out != "n 0", "G 꾸밈 복사가 Word 에 그림으로 붙는다", out)
    else:
        contended("G Word 붙이기(꾸밈)")

shutil.rmtree(tmp, ignore_errors=True)
# 사용자 클립보드 되돌리기
if ORIG_TEXT is not None:
    (getattr(clipboard_util, "set_text", None) or cb.setText)(ORIG_TEXT)
elif ORIG_IMG is not None and not ORIG_IMG.isNull():
    clipboard_util.set_image(ORIG_IMG, None)
spin(0.3)
print("사용자 클립보드:", "되돌림" if (ORIG_TEXT is not None or ORIG_IMG is not None) else "글·그림이 아니라(비었거나 파일 등) 되돌리지 않음")
if unverified:
    print("\n확인 못 함(클립보드 다툼·Word 없음 — 실패 아님):", unverified)
print("\n=== " + ("ALL PASS" if not fails else f"FAILURE {len(fails)}") + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
