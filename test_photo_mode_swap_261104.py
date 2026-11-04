# -*- coding: utf-8 -*-
"""모드를 바꾸면 본문이 앞 모드 문서를 버린다 (사진 보기 SOT 4.2, 261104-17 사용자 보고).

사용자 보고: "pdf를 사진 모드로 바꿨을 때 본화면에 바꾸기 전 pdf가 화면에 그대로 보이고, 반대의 경우에는 사진이 계속 보이는 문제".
실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. PDF 를 보다 사진 모드로 — 처음이면 빈 화면(PDF 가 남지 않는다), 썸네일 칸·쪽 칸도 비운다
B. 사진을 보고 PDF 모드로 — 보던 PDF 의 보던 쪽으로(사진이 남지 않는다)
C. 다시 사진 모드로 — 마지막에 본 사진
D. 저장 안 한 편집이 있으면 확인 — 취소면 모드를 바꾸지 않는다
E. 전환 동안 메인 최장 공백 < 0.5초
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
QCoreApplication.setApplicationName("polypdf_photo_mswap_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "모드 전환", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_mswap_"))
try:
    from PIL import Image
    import fitz
    pdf = tmp / "보고서.pdf"
    d = fitz.open()
    for i in range(3):
        d.new_page().insert_text((72, 72), "page %d" % (i + 1))
    d.save(str(pdf)); d.close()
    a = tmp / "가 사진.jpg"
    Image.new("RGB", (400, 300), (40, 120, 200)).save(a, "JPEG")

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mv = mw.main_view
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 1)
    mw._load_main(HistoryItem(str(pdf), 1, "", "bookmark")); pump(timeout=0.5)
    chk(mv.current_file() and mv.current_file().endswith("보고서.pdf") and mv.current_page() == 1, "준비 — PDF 2쪽")

    gap, last = [0.0], [time.perf_counter()]

    def beat():
        now = time.perf_counter(); gap[0] = max(gap[0], now - last[0]); last[0] = now
    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat); hb.start()

    # A
    mw._set_photo_mode(True); pump(timeout=0.8)
    chk(mv.current_file() is None, "A 사진 모드로 — PDF 가 본문에 남지 않는다(처음이면 빈 화면)", str(mv.current_file()))
    chk(mw.page_thumbs._doc is None and mv.lbl_page_total.text() == "/ 0", "A 쪽 썸네일·쪽 칸도 비운다", mv.lbl_page_total.text())

    # 사진 보기
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 1)
    mw._on_bookmark_activated(str(a), 0); pump(timeout=0.8)
    chk(mv.current_file() and mv.current_file().endswith("가 사진.jpg"), "사진을 연다")

    # B
    mw._set_photo_mode(False); pump(timeout=0.8)
    chk(mv.current_file() and mv.current_file().endswith("보고서.pdf") and mv.current_page() == 1,
        "B PDF 모드로 — 보던 PDF 의 보던 쪽(사진이 남지 않는다)", f"{mv.current_file()} p{mv.current_page()}")

    # C
    mw._set_photo_mode(True); pump(timeout=0.8)
    chk(mv.current_file() and mv.current_file().endswith("가 사진.jpg"), "C 다시 사진 모드로 — 마지막에 본 사진", str(mv.current_file()))
    hb.stop()

    # E
    chk(gap[0] < 0.5, "E 전환 동안 메인 최장 공백 < 0.5초", "%.3f" % gap[0])

    # D — 저장 안 한 편집 + 취소
    asked = []
    mw._in_edit = lambda: True
    mw._edit_snap = {"x": 1}
    mw._edit_dirty = True
    mw._confirm_edit_save = lambda switching=False: (asked.append(1), "cancel")[1]
    mw._set_photo_mode(False); pump(timeout=0.5)
    chk(asked and mw._photo_mode and mv.current_file().endswith("가 사진.jpg"), "D 취소면 모드를 바꾸지 않는다")
    chk(mw._photo_btn.isChecked() == mw._photo_mode if hasattr(mw._photo_btn, "isChecked") and mw._photo_btn.isCheckable() else True,
        "D 토글 단추도 사진 모드 그대로")
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
