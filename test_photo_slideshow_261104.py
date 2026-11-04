# -*- coding: utf-8 -*-
"""사진 슬라이드쇼 — 발표 창 재사용 (사진 보기 SOT 4.12, 발표 SOT 연동, 261104-7 B1).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진 모드 F5(발표보기) — 사진으로 발표 창이 열린다(종전: '먼저 PDF를 표시하세요'), 리본 발표 단추가 켜져 있다
B. 세로 사진에서 상하 2분할이 저절로 켜지지 않는다
C. 화면 크기로 그린다(DPI 하한 72 없음) — 24 MP 사진을 원본 크기로 그리지 않는다
D. 다음 사진으로 '무장 → 한 번 더' 없이 바로 넘긴다, 목록 끝이면 멈춘다
E. 꾸밈이 있는 사진은 구운 1쪽 PDF 로 그린다
F. 자동 넘김 간격(사진 묶음 slide_interval_s) — 그 간격마다 다음, 마지막에서 멈춘다
G. 녹화 중 사진이 바뀌어도 녹화를 끊지 않는다(슬라이드쇼 한 번 = 녹화 하나)
H. 24 MP 사진 슬라이드쇼를 열고 넘기는 동안 하트비트 최장 공백 < 1초(응답성 SOT §7.1)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_slide_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "슬라이드쇼", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_slide_"))
try:
    from PIL import Image
    ex = Image.Exif(); ex[0x0112] = 6
    nz = Image.merge("RGB", [Image.effect_noise((6000, 4000), 60) for _ in range(3)])
    nz.save(tmp / "1 세로 큰.jpg", "JPEG", quality=88, exif=ex.tobytes())          # 24 MP, 세로로 보임
    nz.save(tmp / "2 큰.jpg", "JPEG", quality=88)
    Image.new("RGB", (800, 600), (30, 160, 60)).save(tmp / "3 꾸밈.jpg", "JPEG")
    P = lambda n: str(tmp / n)

    from viewer.app import MainWindow
    from viewer.photo_doc import PhotoDocument
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3), "사진 3장 목록")
    bt.set_sort_mode(bt.SORT_NAME); pump()
    st = mw._ensure_page_meta_store()
    st.set_drawings(P("3 꾸밈.jpg"), 0, [{"points": [[0.1, 0.5], [0.9, 0.5]], "pen": 0, "width": 6}]); st.save()
    mw._on_bookmark_activated(P("1 세로 큰.jpg"), 0); pump(timeout=2.0)

    beats = {"last": time.perf_counter(), "worst": 0.0}

    def beat():
        now = time.perf_counter()
        beats["worst"] = max(beats["worst"], now - beats["last"]); beats["last"] = now
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(beat); hb.start()
    pump(); beats["worst"] = 0.0; beats["last"] = time.perf_counter()

    # A
    chk(mw.act_present.isEnabled(), "A 사진 모드에서 발표 단추가 켜져 있다")
    mw._open_presentation(); pump(timeout=1.5)
    pres = getattr(mw, "_present", None)
    chk(pres is not None and getattr(pres, "_photo", False), "A 사진으로 발표 창이 열린다")
    # B
    chk(pres is not None and not pres._split_mode, "B 세로 사진에서 상하 2분할이 켜지지 않는다")
    # C
    chk(pres is not None and isinstance(pres._doc, PhotoDocument) and pres._dpi_min == 1, "C 사진 문서·DPI 하한 없음")
    pm = pres._render_pixmap(18) if pres is not None else None
    chk(pm is not None and pm.height() <= 1600, "C 화면 크기로 그린다(24 MP 를 원본 크기로 그리지 않음)",
        str((pm.width(), pm.height()) if pm is not None else None))
    # D
    pres._next(); pump(timeout=1.5)
    chk(Path(str(pres._path)).name == "2 큰.jpg" and not pres._armed, "D 다음 사진으로 바로(무장 없이)", str(pres._path))
    # G
    class FakeRec:
        def is_recording(self):
            return True
    fr = FakeRec(); mw._rec = fr
    pres._next(); pump(timeout=1.0)
    chk(mw._rec is fr, "G 사진이 바뀌어도 녹화를 끊지 않는다")
    mw._rec = None
    # E
    chk(Path(str(pres._path)).name == "3 꾸밈.jpg" and str(pres._render_path(pres._path)).lower().endswith(".pdf"),
        "E 꾸밈이 있는 사진은 구운 1쪽 PDF 로 그린다", str(pres._render_path(pres._path)))
    pres._next(); pump(timeout=0.5)
    chk(Path(str(pres._path)).name == "3 꾸밈.jpg", "D 목록 끝이면 멈춘다(처음으로 돌지 않는다)")
    hb.stop()
    print("     슬라이드쇼 열기·넘김(24 MP) 하트비트 최장 공백 %.3f초" % beats["worst"])
    chk(beats["worst"] < 1.0, "H 하트비트 최장 공백 < 1초", "%.3f초" % beats["worst"])
    pres.close(); pump(timeout=0.5)

    # F
    mw._photo_prefs()["slide_interval_s"] = 1
    mw._on_bookmark_activated(P("2 큰.jpg"), 0); pump(timeout=1.0)
    mw._open_presentation(); pump(timeout=0.5)
    pres = mw._present
    chk(pump(lambda: Path(str(pres._path)).name == "3 꾸밈.jpg", timeout=4), "F 자동 넘김 — 간격마다 다음", str(pres._path))
    pump(timeout=1.6)
    t = mw.__dict__.get("_photo_slide_timer")
    chk(Path(str(pres._path)).name == "3 꾸밈.jpg" and (t is None or not t.isActive()), "F 마지막 사진에서 자동 넘김이 멈춘다")
    pres.close(); pump(timeout=0.3)
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
