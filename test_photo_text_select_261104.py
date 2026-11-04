# -*- coding: utf-8 -*-
"""사진 위에서 글자 바로 고르기·복사 (사진 보기 SOT 4.39, §5.1 F9, 261104-14).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). OCR 낱말은 사진 한 장 OCR 과 같은 꼴로
보류 저장소에 직접 넣는다(Tesseract 없이 — 읽는 길은 test_photo_ocr_261104).
A. OCR 한 사진 — 본문을 마우스로 끌면 낱말이 골라지고 Ctrl+C 로 복사된다(PDF 의 OCR 글자 고르기와 같은 길)
B. 옆으로 찍은 사진(글이 세로) — 보기 회전 90° 로 세워 보면 가로로 끌어 고른다
C. 읽지 않은 사진·덮어써 낡은 OCR — 고를 글이 없다(OCR 은 누를 때만)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt, QPoint, QPointF
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_tsel_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 글자 고르기", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_tsel_"))
try:
    from PIL import Image
    from viewer.study import study_store, ocr as O
    from viewer.study.study_store import StudyStore, file_key_for
    study_store.enable_pending(True)
    a = tmp / "a 영수증.jpg"
    Image.new("RGB", (1200, 800), (250, 250, 250)).save(a, "JPEG")
    b = tmp / "b 안읽음.jpg"
    Image.new("RGB", (1200, 800), (240, 240, 240)).save(b, "JPEG")
    # 회전 0 판 낱말 — 한 줄 'TOTAL AMOUNT 15000'(y 300~360), 다른 줄 'THANK YOU'(y 500~560)
    words = [{"surface": "TOTAL", "x0": 200, "y0": 300, "x1": 400, "y1": 360, "conf": 95},
             {"surface": "AMOUNT", "x0": 430, "y0": 300, "x1": 700, "y1": 360, "conf": 95},
             {"surface": "15000", "x0": 730, "y0": 300, "x1": 940, "y1": 360, "conf": 95},
             {"surface": "THANK", "x0": 200, "y0": 500, "x1": 420, "y1": 560, "conf": 95},
             {"surface": "YOU", "x0": 450, "y0": 500, "x1": 580, "y1": 560, "conf": 95}]
    c = tmp / "c 옆으로.jpg"
    Image.new("RGB", (1200, 800), (245, 245, 245)).save(c, "JPEG")
    # c: 돌려 본 판(800×1200)에서 가로 줄 'LEFT SIDE TEXT' → 회전 0 판(1200×800)으로 되돌려 남긴다(사진 한 장 OCR 과 같은 꼴)
    view_words = [{"surface": "LEFT", "x0": 100, "y0": 400, "x1": 260, "y1": 460, "conf": 95},
                  {"surface": "SIDE", "x0": 290, "y0": 400, "x1": 450, "y1": 460, "conf": 95},
                  {"surface": "TEXT", "x0": 480, "y0": 400, "x1": 640, "y1": 460, "conf": 95}]
    st = StudyStore()
    st.save_page(file_key_for(str(c)), 0, "LEFT SIDE TEXT", dpi=72, engine="tesseract|" + O.photo_sig(c),
                 source="ocr", conf=95, words=O.photo_words_view(view_words, 270, 800, 1200), lang="eng")
    st.save_page(file_key_for(str(a)), 0, "TOTAL AMOUNT 15000\nTHANK YOU", dpi=72, engine="tesseract|" + O.photo_sig(a),
                 source="ocr", conf=95, words=words, lang="eng")
    st.close()

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3)
    mw._on_bookmark_activated(str(a), 0); pump(timeout=0.8)
    mv = mw.main_view
    view = mv.view
    cb = QApplication.clipboard()

    def drag_copy(p0, p1):
        """페이지 좌표(pt) p0→p1 을 화면에서 끌고 Ctrl+C — 복사된 글."""
        z = mv._zoom or 1.0
        v0 = view.mapFromScene(QPointF(p0[0] * z, p0[1] * z))
        v1 = view.mapFromScene(QPointF(p1[0] * z, p1[1] * z))
        cb.setText("")
        vp = view.viewport()
        QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, v0)
        for k in range(1, 6):
            QTest.mouseMove(vp, QPoint(v0.x() + (v1.x() - v0.x()) * k // 5, v0.y() + (v1.y() - v0.y()) * k // 5))
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, v1)
        pump(timeout=0.2)
        mv.copy_selection()
        pump(timeout=0.1)
        return cb.text()

    # A
    got = drag_copy((210, 330), (930, 330))
    chk(got.split() == ["TOTAL", "AMOUNT", "15000"], "A 끌어 고르기·복사 — 그 줄", repr(got))
    got = drag_copy((440, 330), (920, 330))
    chk(got.split() == ["AMOUNT", "15000"], "A 낱말 단위로 고른다", repr(got))

    # B — 옆으로 찍은 사진을 90° 세워 본다
    mw._on_bookmark_activated(str(c), 0); pump(timeout=0.8)
    got = drag_copy((110, 430), (630, 430))
    chk("LEFT" not in got.split()[:1] or got.split() != ["LEFT", "SIDE", "TEXT"], "B 돌리기 전에는 그 자리에 가로 줄이 없다", repr(got))
    mw._photo_rotate(+90); pump(timeout=0.8)
    got = drag_copy((110, 430), (630, 430))
    chk(got.split() == ["LEFT", "SIDE", "TEXT"], "B 90° 세워 보면 가로로 끌어 고른다", repr(got))
    mw._photo_rotate(-90); pump(timeout=0.8)
    mw._on_bookmark_activated(str(a), 0); pump(timeout=0.8)

    # C
    mw._on_bookmark_activated(str(b), 0); pump(timeout=0.8)
    got = drag_copy((210, 330), (930, 330))
    chk(not got.strip() or "TOTAL" not in got, "C 읽지 않은 사진 — 고를 글 없음", repr(got))
    mw._on_bookmark_activated(str(a), 0); pump(timeout=0.8)
    time.sleep(0.05)
    Image.new("RGB", (1200, 800), (230, 230, 230)).save(a, "JPEG")      # 덮어쓰기 — OCR 이 낡았다
    mw._photo_words_changed()
    mw._on_bookmark_activated(str(b), 0); pump(timeout=0.5)
    mw._on_bookmark_activated(str(a), 0); pump(timeout=0.8)
    got = drag_copy((210, 330), (930, 330))
    chk("TOTAL" not in got, "C 덮어써 낡은 OCR — 옛 글을 고르지 않는다", repr(got))
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
