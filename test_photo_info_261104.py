# -*- coding: utf-8 -*-
"""사진 정보·크기 표시·열 수 없는 파일 (사진 보기 SOT 4.18, 261104-3 사용자 지시).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진 썸네일 줄 칸 아래 이름 다음 줄에 원본 픽셀 크기(EXIF 방향 뒤) — 썸네일만 보고 원본 크기를 안다
B. 상태 막대 **가운데**에 촬영일 · 크기 · 파일 크기 · 카메라 한 줄, 누르면 세부 정보(항목 표)
C. 열 수 없는 파일(그림 이름의 QuickTime 동영상)을 고르면 본문은 알림 쪽(까닭 = 동영상), 앞 사진에 머물지 않는다 — 쪽 칸 순번도 그 파일,
   돌리기는 하지 않는다, 썸네일 칸은 '열 수 없음'
D. 그 자리에서 다음·이전 넘김이 묻지 않고 그대로 이어진다
E. PDF 모드로 가면 가운데 사진 정보가 사라진다
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
QCoreApplication.setApplicationName("polypdf_photo_info_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 정보", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_info_"))
try:
    from PIL import Image
    ex = Image.Exif()
    ex[0x0112] = 6
    ex[0x010F] = "PolyCam"; ex[0x0110] = "Z1"
    ex.get_ifd(0x8769)[0x9003] = "2026:10:30 14:22:05"
    Image.new("RGB", (800, 400), (200, 60, 60)).save(tmp / "1 세로.jpg", "JPEG", exif=ex.tobytes())
    (tmp / "2 동영상.jpg").write_bytes(b"\x00\x00\x00\x08wide\x00\x1e\xb6Zmdat" + bytes(4000))
    Image.new("RGB", (640, 480), (60, 160, 60)).save(tmp / "3 초록.jpg", "JPEG")

    from viewer.app import MainWindow
    from viewer.photo_doc import BrokenPhotoDocument
    from viewer import photo_controller as pc
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3), "사진 3장 목록")
    bt.set_sort_mode(bt.SORT_NAME); pump()
    lst = mw._photo_tree_list()
    mv = mw.main_view
    mw._on_bookmark_activated(lst[0], 0); pump(timeout=0.5)

    # A
    s = mw._photo_strip
    chk(pump(lambda: len(s._done) >= 3, timeout=10), "A 썸네일 3장 다 만듦")
    t0, t1 = s._items[lst[0]].text(), s._items[lst[1]].text()
    chk(t0.split("\n")[-1] == "400 × 800", "A 이름 아래 원본 크기(방향 뒤 400 × 800)", repr(t0))
    chk(t0.split("\n")[0] == "1 세로", "A 첫 줄은 이름(확장자 없이)", repr(t0))

    # B
    b = getattr(mw, "_photo_info_btn", None)
    chk(pump(lambda: b is not None and "2026-10-30 14:22" in b.text(), timeout=5), "B 가운데 정보 — 촬영일",
        repr(b.text() if b else None))
    txt = b.text() if b else ""
    chk("400 × 800" in txt and "PolyCam Z1" in txt and "KB" in txt, "B 크기 · 파일 크기 · 카메라", repr(txt))
    cx = b.geometry().center().x() if b else -1
    chk(b is not None and b.isVisible() and abs(cx - mw.status.width() // 2) <= 4, "B 상태 막대 가운데에", "%d vs %d" % (cx, mw.status.width() // 2))
    rows = dict(pc.photo_info_rows(mw._photo_info))
    chk(rows.get("촬영일") == "2026-10-30 14:22" and rows.get("카메라") == "PolyCam Z1" and rows.get("방향(EXIF)") == "6",
        "B 누르면 보이는 세부 정보 표", str(rows))

    # C
    t = time.perf_counter()
    mw._on_bookmark_activated(lst[1], 0); app.processEvents()
    took = time.perf_counter() - t
    doc = mv._doc
    chk(isinstance(doc, BrokenPhotoDocument) and Path(mv.current_file()).name == "2 동영상.jpg",
        "C 본문은 그 파일의 알림 쪽(앞 사진에 머물지 않는다)", str(mv.current_file()))
    chk(doc is not None and getattr(doc, "reason", "") == "video", "C 까닭 = 동영상", str(getattr(doc, "reason", None)))
    chk(mv.spin_page.value() == 2 and mv.lbl_page_total.text() == "/ 3", "C 쪽 칸 순번 2 / 3")
    chk(took < 0.5, "C 열기가 멈추지 않는다", "%.3f초" % took)
    chk("열 수 없는" in mw._photo_info_btn.text(), "C 가운데에 열 수 없다는 알림", repr(mw._photo_info_btn.text()))
    mw._photo_rotate(+90); pump()
    chk(mw._ensure_page_meta_store().photo_rotation(lst[1]) == 0, "C 열 수 없는 파일은 돌리지 않는다")
    chk(pump(lambda: s._items[lst[1]].text().endswith("열 수 없음"), timeout=5), "C 썸네일 칸 '열 수 없음'", repr(s._items[lst[1]].text()))

    # D
    mw._on_file_boundary(+1, mw._active_pane); pump(timeout=0.5)
    chk(Path(mv.current_file()).name == "3 초록.jpg", "D 다음 → 그다음 사진(묻지 않음)", str(mv.current_file()))
    mw._on_file_boundary(-1, mw._active_pane); pump(timeout=0.5)
    chk(Path(mv.current_file()).name == "2 동영상.jpg", "D 이전 → 다시 그 파일")
    mw._on_file_boundary(-1, mw._active_pane); pump(timeout=0.5)
    chk(Path(mv.current_file()).name == "1 세로.jpg", "D 이전 → 첫 사진")

    # E
    mw._set_photo_mode(False); pump()
    chk(not mw._photo_info_btn.isVisible(), "E PDF 모드에서는 가운데 사진 정보가 없다")
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
