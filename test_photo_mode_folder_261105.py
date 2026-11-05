# -*- coding: utf-8 -*-
"""모드를 바꿀 때의 폴더·본문 (사진 보기 SOT §6.1, 261105-23·-24 사용자 지시·결정).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. (-23 사용자 보고) PDF 모드의 기억이 없어 사진 폴더 그대로 PDF 모드로 오면('0개 PDF'), 목록에 없는 PDF(이 실행에서 보던 것)를
   본문·썸네일·창 제목에 띄우지 않는다
B. (-24) 모드마다 마지막 폴더 — PDF 모드로 오면 PDF 모드의 마지막 폴더와 그 PDF·쪽, 사진 모드로 가면 사진 폴더와 그 사진
C. (-24 사용자 결정) 기억한 폴더가 없어졌으면 그 모드 최근 폴더 중 있는 것 맨 앞
D. 바꿀 때 본문에 보이는 파일은 늘 책갈피창 목록에 있다(B·C 의 각 단계)
E. 사진 모드로 닫을 때 저장 — PDF 자리(last_open)는 PDF 폴더, 사진 자리는 picture 묶음
F. 큰 폴더(사진 3,000장)로 바꾸기 — 바꾸는 호출과 목록 채우기 동안 이벤트 루프 최장 공백 < 1초(응답성 SOT §5)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_mode_folder_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "모드 폴더", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_mode_folder_"))
try:
    from PIL import Image
    import fitz
    for d in ("pdfs", "other", "pix", "big"):
        (tmp / d).mkdir()

    def mkpdf(p, n=3):
        doc = fitz.open()
        for _ in range(n):
            doc.new_page()
        doc.save(str(p)); doc.close()

    mkpdf(tmp / "pdfs" / "a.pdf"); mkpdf(tmp / "pdfs" / "b.pdf")
    mkpdf(tmp / "other" / "x.pdf")
    Image.new("RGB", (300, 200), (200, 40, 40)).save(tmp / "pix" / "p1.jpg", "JPEG")
    Image.new("RGB", (300, 200), (40, 160, 60)).save(tmp / "pix" / "p2.jpg", "JPEG")
    small = (tmp / "pix" / "p1.jpg").read_bytes()
    for i in range(3000):
        (tmp / "big" / ("b%04d.jpg" % i)).write_bytes(small)

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mv = mw.main_view
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()

    def root():
        return os.path.normcase(str(bt._root_dir)) if bt._root_dir else ""

    def cur():
        c = mv.current_file()
        return Path(c).name if c else ""

    def listed():
        return {os.path.normcase(str(it.data(0, bt.DATA_FILE))) for it in bt._iter_file_nodes()}

    def settle():
        pump(lambda: getattr(bt, "_scan_worker", None) is None and not bt._fill_timer.isActive(), timeout=20)
        pump(timeout=0.4)

    def in_list(tag):
        c = mv.current_file()
        chk(not c or os.path.normcase(c) in listed(), "D %s 본문 파일은 책갈피창 목록에 있다" % tag, str((c, len(listed()))))

    # A — 사진 모드에서 PDF 모드의 기억 없이 PDF 모드로(사용자 화면 재현)
    mw.open_folder(tmp / "other"); settle()
    mw._on_bookmark_activated(str(tmp / "other" / "x.pdf"), 1); pump(timeout=0.5)
    mw._set_photo_mode(True); settle()
    mw.open_folder(tmp / "pix"); settle()
    mw._on_bookmark_activated(str(tmp / "pix" / "p1.jpg"), 0); pump(timeout=0.5)
    mw._photo_mode_last["pdf"] = {}                     # PDF 모드의 마지막 자리를 모른다(첫 사용·옛 설정)
    mw._set_photo_mode(False); settle()
    chk(root() == os.path.normcase(str(tmp / "pix")), "A 기억이 없으면 지금 폴더 그대로(사용자 결정)", root())
    chk(cur() == "" and mw.page_thumbs.list.count() == 0,
        "A 목록('0개 PDF')에 없는 PDF 는 본문·썸네일에 띄우지 않는다", "%s 썸네일 %d" % (cur(), mw.page_thumbs.list.count()))
    chk("x.pdf" not in mw.windowTitle(), "A 창 제목에도 그 PDF 가 없다", mw.windowTitle())
    in_list("A")

    # B — 모드마다 마지막 폴더
    mw.open_folder(tmp / "other"); settle()             # PDF 최근 폴더: other
    mw.open_folder(tmp / "pdfs"); settle()              # PDF 최근 폴더: pdfs, other
    mw._on_bookmark_activated(str(tmp / "pdfs" / "b.pdf"), 2); pump(timeout=0.5)
    mw._set_photo_mode(True); settle()
    chk(root() == os.path.normcase(str(tmp / "pix")), "B 사진 모드로 — 사진 모드의 마지막 폴더(pix)", root())
    chk(cur() == "p1.jpg", "B 사진 모드로 — 마지막에 본 사진", cur())
    in_list("B 사진")
    mw._on_bookmark_activated(str(tmp / "pix" / "p2.jpg"), 0); pump(timeout=0.5)
    mw._set_photo_mode(False); settle()
    chk(root() == os.path.normcase(str(tmp / "pdfs")), "B PDF 모드로 — PDF 모드의 마지막 폴더(pdfs, 사진 폴더를 끌고 오지 않는다)", root())
    chk(cur() == "b.pdf" and mv.current_page() == 2, "B PDF 모드로 — 보던 PDF·쪽", "%s %s" % (cur(), mv.current_page()))
    in_list("B PDF")
    mw._set_photo_mode(True); settle()
    chk(root() == os.path.normcase(str(tmp / "pix")) and cur() == "p2.jpg", "B 다시 사진 모드로 — pix·p2", "%s %s" % (root(), cur()))
    in_list("B 사진 2")

    # E — 사진 모드로 닫을 때 저장
    pay = mw._build_settings_payload()
    lo = pay.get("last_open") or {}
    pic_lo = (mw._prefs.get("picture") or {}).get("last_open") or {}
    chk(os.path.normcase(str(lo.get("path"))) == os.path.normcase(str(tmp / "pdfs"))
        and os.path.normcase(str(pic_lo.get("path"))) == os.path.normcase(str(tmp / "pix")),
        "E 저장 — PDF 자리는 pdfs, 사진 자리(picture.last_open)는 pix", str((lo, pic_lo)))

    # C — 기억한 PDF 폴더가 없어졌으면 그 모드 최근 폴더
    shutil.move(str(tmp / "pdfs"), str(tmp / "pdfs_moved"))
    mw._set_photo_mode(False); settle()
    chk(root() == os.path.normcase(str(tmp / "other")), "C 없어진 폴더 대신 PDF 최근 폴더 중 있는 것(other)", root())
    chk(cur() in ("", "x.pdf"), "C 본문은 그 폴더 안 것만", cur())
    in_list("C")

    # F — 큰 사진 폴더로 바꾸기
    mw._set_photo_mode(True); settle()
    mw.open_folder(tmp / "big"); settle()
    mw._set_photo_mode(False); settle()
    gaps = []
    last = [time.monotonic()]
    from PyQt6.QtCore import QTimer
    hb = QTimer(); hb.setInterval(20)

    def beat():
        now = time.monotonic(); gaps.append(now - last[0]); last[0] = now
    hb.timeout.connect(beat); hb.start()
    t0 = time.monotonic()
    mw._set_photo_mode(True)
    call = time.monotonic() - t0
    last[0] = time.monotonic()
    settle()
    pump(lambda: len(listed()) == 3000, timeout=30)      # 채우기는 틱마다 나눠 — 다 찰 때까지(부하 때 2,000장에서 잰 적이 있다)
    hb.stop()
    chk(root() == os.path.normcase(str(tmp / "big")) and len(listed()) == 3000, "F 사진 모드로 — 큰 폴더(3,000장) 목록", "%s %d" % (root(), len(listed())))
    chk(call < 1.0 and max(gaps or [0]) < 1.0, "F 바꾸는 호출·목록 채우기 동안 최장 공백 < 1초", "호출 %.2f초 공백 %.2f초" % (call, max(gaps or [0])))
    print("   (F 호출 %.3f초 · 최장 공백 %.3f초)" % (call, max(gaps or [0])))

    mw._set_photo_mode(False); pump()
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
