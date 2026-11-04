# -*- coding: utf-8 -*-
"""사진 한 장 OCR → 텍스트 창 (사진 보기 SOT 4.34, 단어학습 SOT §14.22, 261104-10 P4-a).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 보류 저장소를 켠다(단어학습 SOT §14.21).
A. 사진 모드에서 텍스트 창을 켤 수 있고, 읽기 전에는 '아직 읽지 않았습니다' — 넘기기만으로는 읽지 않는다(D15)
B. [OCR 로 읽기] → 묻는 창 없이 배경에서 읽어 텍스트 창에 줄(메인 최장 공백 < 0.5초)
C. 결과는 보류 저장소 — 버리면 다시 '아직 읽지 않았습니다'
D. 긴 변 상한 — Tesseract 에 넘기는 그림은 PHOTO_MAX_SIDE 이하, 상자는 원래 픽셀(= pt)
E. 보기 회전 — 돌려 읽고 상자는 회전 0 판으로, 텍스트 창은 다시 돈 판으로(왕복 같음)
F. 같은 이름으로 덮어쓴 사진 — 옛 글을 보이지 않는다
G. [PDF 에 반영]·줄 상자 늘리기 — 사진 원본 그대로, 알림만
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
QCoreApplication.setApplicationName("polypdf_photo_ocr_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 OCR", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_ocr_"))
try:
    from PIL import Image, ImageDraw, ImageFont
    from viewer.study import ocr as O
    if not O.ensure_tesseract().get("ok"):
        print("SKIP - Tesseract 없음")
        print("ALL PASS"); sys.stdout.flush(); os._exit(0)

    def text_photo(path, lines, size=(1600, 900)):
        im = Image.new("RGB", size, (250, 250, 248))
        d = ImageDraw.Draw(im)
        f = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 72)
        for i, t in enumerate(lines):
            d.text((80, 80 + i * 130), t, fill=(20, 20, 20), font=f)
        im.save(path, "JPEG", quality=95)
    a = tmp / "a 영수증.jpg"
    text_photo(a, ["RECEIPT NUMBER 4821", "TOTAL AMOUNT 15000", "THANK YOU"])
    b = tmp / "b 풍경.jpg"
    Image.new("RGB", (800, 600), (90, 140, 200)).save(b, "JPEG")

    from viewer.study import study_store
    study_store.enable_pending(True)
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 850); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 2)
    tp = mw.text_panel

    # A
    mw._on_bookmark_activated(str(a), 0); pump(timeout=0.6)
    act = mw._cmds.get("view.text")
    chk(act is not None and act.isEnabled(), "A 사진 모드에서 텍스트 창을 켤 수 있다")
    mw._vm_text(); pump(timeout=0.6)
    mw._reload_text_panel(); pump(timeout=0.6)
    msg = lambda: (tp.lbl_note.text() if hasattr(tp, "lbl_note") else "") + " " + str(getattr(tp, "_note", ""))
    rows = lambda: list(getattr(tp, "_rows", []) or [])
    chk(not rows() and mw.__dict__.get("_photo_ocr_worker") is None, "A 넘기기만으로는 읽지 않는다(줄 없음)", str(rows())[:120])

    # B
    gap, last = [0.0], [time.perf_counter()]

    def beat():
        now = time.perf_counter(); gap[0] = max(gap[0], now - last[0]); last[0] = now
    from PyQt6.QtCore import QTimer
    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat); hb.start()
    mw._on_text_need_ocr()
    ok = pump(lambda: mw.__dict__.get("_photo_ocr_worker") is None and rows(), timeout=60)
    hb.stop()
    text = " ".join(str(getattr(r, "text", r.get("text", "") if isinstance(r, dict) else r)) for r in rows())
    chk(ok and "RECEIPT" in text.upper() and "4821" in text, "B 읽어 텍스트 창에 줄", text[:200])
    chk(gap[0] < 0.5, "B 메인 최장 공백 < 0.5초", "%.3f" % gap[0])

    # C
    from viewer.study.study_store import file_key_for, StudyStore
    st = StudyStore()
    key = file_key_for(str(a))
    eng = st.conn.execute("SELECT engine, dpi FROM ocr_page WHERE file_key=? AND page=0", (key,)).fetchone()
    chk(eng is not None and str(eng["engine"]).startswith("tesseract|photo:") and int(eng["dpi"]) == 72, "C 원본 사진 경로 키·dpi 72·낡음 표", str(dict(eng) if eng else None))
    chk(key in st.pending_keys(), "C 보류 저장소에 있다(아직 확정 아님)")
    st.discard_pending(key)
    st.close()
    mw._reload_text_panel(); pump(timeout=0.6)
    chk(not rows(), "C 보류를 버리면 다시 읽지 않은 상태", str(rows())[:80])

    # D·E — 그림 크기·좌표(가짜 판독으로 상자 수학만)
    seen = {}
    real_ocr = O.ocr_image

    def fake_ocr(img, lang="eng", psm=0, dpi=300):
        seen["size"] = img.size; seen["dpi"] = dpi
        W, H = img.size
        return {"text": "X", "conf": 90, "words": [{"surface": "X", "x0": W * 0.1, "y0": H * 0.2, "x1": W * 0.3, "y1": H * 0.25, "conf": 90}]}
    O.ocr_image = fake_ocr
    big = tmp / "큰.jpg"
    Image.new("RGB", (6000, 3000), (255, 255, 255)).save(big, "JPEG")
    r = O.build_photo(big, lang="eng")
    w = r["words"][0]
    chk(max(seen["size"]) <= O.PHOTO_MAX_SIDE and abs(seen["dpi"] - 72.0 * O.PHOTO_MAX_SIDE / 6000) < 0.01,
        "D 긴 변 상한·배율만큼의 dpi", str(seen))
    chk(abs(w["x0"] - 600) < 2 and abs(w["y0"] - 600) < 2 and abs(w["x1"] - 1800) < 2, "D 상자는 원래 픽셀", str(w))
    r90 = O.build_photo(big, lang="eng", rot=90)
    w90 = r90["words"][0]                         # 돈 판(3000×6000)의 (300..900, 1200..1500) → 회전 0 판
    back = O.photo_words_view([w90], 90, 6000, 3000)[0]
    chk(abs(back["x0"] - 300) < 2 and abs(back["y0"] - 1200) < 2 and abs(back["x1"] - 900) < 2 and abs(back["y1"] - 1500) < 2,
        "E 보기 회전 — 회전 0 판으로 남기고 다시 돌리면 같은 자리", f"{w90} → {back}")
    chk(0 <= w90["x0"] <= 6000 and 0 <= w90["y0"] <= 3000, "E 남긴 상자는 회전 0 판 안", str(w90))
    O.ocr_image = real_ocr

    # F — 같은 이름으로 덮어쓰기
    mw._on_text_need_ocr()
    pump(lambda: mw.__dict__.get("_photo_ocr_worker") is None and rows(), timeout=60)
    time.sleep(0.05)
    text_photo(a, ["OTHER PICTURE"], size=(1500, 800))
    mw._reload_text_panel(); pump(timeout=0.8)
    chk(not rows(), "F 덮어쓴 사진 — 옛 글을 보이지 않는다", str(rows())[:80])

    # G
    raw = a.read_bytes()
    mw._on_text_apply_pdf()
    m1 = mw.status.currentMessage()                # 바로 읽는다 — 폴더 감시 알림이 덮기 전에
    pump(timeout=0.3)
    mw._on_text_rect_stretched(0, (10, 10, 50, 30), (5, 10, 80, 30)); pump(timeout=0.5)
    chk(a.read_bytes() == raw and "글자층" in m1 and not tp.btn_apply.isEnabled(), "G [PDF 에 반영]·줄 늘리기 막음 — 원본 그대로", m1)
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
