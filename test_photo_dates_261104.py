# -*- coding: utf-8 -*-
"""책갈피창 이름 앞 날짜·썸네일 칸 날짜 (사진 보기 SOT 4.37·4.18, 261104-12 사용자 지시).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진 모드 책갈피창(스타일 '날짜 + 이름', 261105-11) — '2025-06-10 이름'(촬영일), 촬영일이 없으면 파일 날짜, zip 줄은 zip 의 파일 날짜
B. 태그 꼬리는 그대로(날짜 + 이름 + 태그)
C. 썸네일 칸 둘째 줄은 날짜, 원본 크기는 칸 도움말
D. PDF 모드 목록에는 날짜를 붙이지 않는다
E. '수정일 순' 정렬은 이름 앞 날짜와 같은 값(촬영 시각, 없으면 파일 시각) — 지휘 세션 지시
F. 사진 1500장 폴더 — 날짜를 읽는 동안 메인 최장 공백(하트비트) < 0.5초, 모두 날짜가 붙는다
"""
import os, sys, tempfile, shutil, time, zipfile, io
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
QCoreApplication.setApplicationName("polypdf_photo_dates_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 날짜", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_dates_"))
try:
    from PIL import Image
    a = tmp / "가 해변.jpg"
    im = Image.new("RGB", (640, 480), (40, 120, 200))
    ex = im.getexif()
    ex.get_ifd(0x8769)[0x9003] = "2025:06:10 09:30:00"
    im.save(a, "JPEG", exif=ex.tobytes())
    b = tmp / "나 캡처.png"
    Image.new("RGB", (300, 200), (200, 200, 200)).save(b, "PNG")
    ts = time.mktime((2024, 1, 2, 12, 0, 0, 0, 0, -1))
    os.utime(b, (ts, ts))
    z = tmp / "다 묶음.zip"
    buf = io.BytesIO(); Image.new("RGB", (100, 80), (0, 0, 0)).save(buf, "JPEG")
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("안.jpg", buf.getvalue())
    tz = time.mktime((2023, 3, 4, 12, 0, 0, 0, 0, -1))
    os.utime(z, (tz, tz))
    e = tmp / "마 옛사진.jpg"                      # 촬영 2020 — 파일 시각은 지금(수정 시각 순이면 맨 위, 날짜 순이면 맨 아래)
    im2 = Image.new("RGB", (320, 240), (90, 30, 30))
    ex2 = im2.getexif()
    ex2.get_ifd(0x8769)[0x9003] = "2020:01:01 08:00:00"
    im2.save(e, "JPEG", exif=ex2.tobytes())
    import fitz
    d = fitz.open(); d.new_page(); d.save(str(tmp / "라 보고서.pdf")); d.close()

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    from viewer import photo_label as PL
    PL.select(mw._photo_prefs(), "tree", "날짜 + 이름")   # 261105-11: 책갈피창 '기본' 은 이름만 — 이 검사는 앞 날짜 스타일로 날짜 읽기를 본다
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 1)
    labels = lambda: {Path(str(it.data(0, bt.DATA_FILE))).name: it.text(0) for it in bt._iter_file_nodes()}

    # D (PDF 모드 먼저)
    chk(labels().get("라 보고서.pdf") == "라 보고서", "D PDF 모드 — 날짜를 붙이지 않는다", str(labels()))

    # A
    mw._set_photo_mode(True)
    ok = pump(lambda: labels().get("가 해변.jpg", "").startswith("2025-06-10")
              and labels().get("나 캡처.png", "").startswith("2024-01-02")
              and labels().get("다 묶음.zip", "").startswith("2023-03-04"), timeout=10)
    L = labels()
    chk(ok and L["가 해변.jpg"] == "2025-06-10 가 해변", "A 촬영일 + 이름", str(L))
    chk(L.get("나 캡처.png") == "2024-01-02 나 캡처", "A 촬영일이 없으면 파일 날짜", str(L))
    chk(L.get("다 묶음.zip", "").startswith("2023-03-04 다 묶음"), "A zip 줄은 zip 의 파일 날짜", str(L))

    # B
    node = next(it for it in bt._iter_file_nodes() if Path(str(it.data(0, bt.DATA_FILE))).name == "가 해변.jpg")
    bt._tags.set(str(a), ["가족"])
    bt._apply_tag_label(node, str(a))
    chk(node.text(0).startswith("2025-06-10 가 해변") and "#가족" in node.text(0), "B 태그 꼬리는 그대로", node.text(0))

    # C
    mw._on_bookmark_activated(str(a), 0)
    strip = mw._photo_strip
    pump(lambda: str(a) in strip._done and str(b) in strip._done, timeout=10)
    ta, tb = strip._items[str(a)].text(), strip._items[str(b)].text()
    chk(ta.split("\n") == ["가 해변", "2025-06-10"] and tb.split("\n")[-1] == "2024-01-02", "C 썸네일 둘째 줄은 날짜", f"{ta!r} {tb!r}")
    chk("640 × 480" in strip._items[str(a)].toolTip(), "C 원본 크기는 칸 도움말", strip._items[str(a)].toolTip())

    # E — 정렬(기본 '수정일 순')
    order = lambda: [Path(str(it.data(0, bt.DATA_FILE))).name for it in bt._iter_file_nodes()]
    chk(bt._sort_combo.currentData() == bt.SORT_MTIME, "E 기본 정렬은 '수정일 순'")
    want = ["가 해변.jpg", "나 캡처.png", "다 묶음.zip", "마 옛사진.jpg"]
    chk(pump(lambda: [n for n in order() if n in want] == want, timeout=10), "E 정렬은 이름 앞 날짜와 같은 값(촬영 시각)", str(order()))

    # D — PDF 모드로 돌아오면 날짜 없음
    mw._set_photo_mode(False)
    pump(lambda: "라 보고서.pdf" in labels(), timeout=10)
    chk(all(not v[:4].isdigit() for v in labels().values()), "D PDF 모드로 오면 날짜 없음", str(labels()))
    # F — 1500장 하트비트
    big = tmp / "많이"
    big.mkdir()
    src = big / "p0000.jpg"
    im3 = Image.new("RGB", (160, 120), (30, 90, 30))
    ex3 = im3.getexif()
    ex3.get_ifd(0x8769)[0x9003] = "2022:02:02 02:02:02"
    im3.save(src, "JPEG", exif=ex3.tobytes())
    raw = src.read_bytes()
    for i in range(1, 1500):
        (big / ("p%04d.jpg" % i)).write_bytes(raw)
    mw._set_photo_mode(True)
    gap, last = [0.0], [time.perf_counter()]

    def beat():
        now = time.perf_counter(); gap[0] = max(gap[0], now - last[0]); last[0] = now
    from PyQt6.QtCore import QTimer
    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat); hb.start()
    t0 = time.perf_counter()
    mw.open_folder(big)
    done = pump(lambda: sum(1 for it in bt._iter_file_nodes() if it.text(0).startswith("2022-02-02")) == 1500, timeout=60)
    hb.stop()
    print("   F 1500장: %.1f초, 메인 최장 공백 %.3f초" % (time.perf_counter() - t0, gap[0]))
    chk(done, "F 1500장 모두 날짜가 붙는다")
    chk(gap[0] < 0.5, "F 메인 최장 공백 < 0.5초", "%.3f" % gap[0])
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
