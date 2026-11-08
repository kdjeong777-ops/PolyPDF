# -*- coding: utf-8 -*-
"""261108-30: 읽기 ▶ 를 누를 때 — 우리 글자층이 아니면 OCR 을 먼저 권한다 (영상·음성 SOT §1.11).

사용자 지시: "플레이 버튼을 눌렀는데, 글자층이 없거나, 우리 프로그램에서 한게 아니면, OCR을 우선하도록 안내하고,
OCR 실행 여부를 물어보도록 해."
창을 띄워 **▶ 단추를 눌러** 네 꼴을 본다 — 소리는 내지 않는다(가짜 TTS), OCR 은 가짜 일꾼(결과 신호만).
  A  스캔(글자층 없음) — 묻는다, [그대로 읽기] 면 곧바로 읽는다
  B  남의 글자층(그림 위 보이지 않는 층, 다른 글꼴) — 묻는다(종전: 글이 있어 묻지 않고 그 층을 읽었다)
  C  우리 글자층(`krfix` 글꼴) — 묻지 않고 읽는다
  D  텍스트 PDF — 묻지 않고 읽는다
  E  앱 OCR 결과가 있는 스캔 쪽 — 묻지 않는다
  F  [취소] — 읽지 않는다
  G  [OCR 하고 읽기] — 전체 구간이면 OCR 할 쪽 = 구간의 스캔 쪽, 시작 쪽 OCR 이 끝나야 읽기 시작
  H  '이 파일은 다시 묻지 않음' — 다음 ▶ 는 묻지 않고 그 답, 설정 저장에 남는다
  I  쪽 판정은 메인 스레드에서 돌지 않는다
"""
import os, sys, tempfile, shutil, threading, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "test")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QObject, pyqtSignal, QTimer
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_read_ocr_offer_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


# 창 답 — 단추 글자로 누른다(실제 QMessageBox 를 만들고 그 단추를 누름)
ANSWER = {"button": "그대로 읽기", "remember": False}
ASKED = []


def _exec(box):
    ASKED.append((box.windowTitle(), box.text(), box.informativeText()))
    cb = box.checkBox()
    if cb is not None:
        cb.setChecked(bool(ANSWER["remember"]))
    for b in box.buttons():
        if b.text().replace("&", "") == ANSWER["button"]:
            b.click()
            break
    return 0
QMessageBox.exec = _exec


class FakeTts:
    def __init__(self):
        self.said = []
    def available(self): return True
    def speak_reading(self, text): self.said.append(text); return True
    def speak(self, text, lang="eng", queue=False): self.said.append(text); return True
    def is_speaking(self): return True          # 말이 끝나지 않는다 — 읽는 중으로 남는다
    def saw_speaking(self): return True
    def stop(self): pass
    def __getattr__(self, name): return lambda *a, **k: None


class FakeOcr(QObject):
    done = pyqtSignal(int, object, int, int)
    progress = pyqtSignal(int, int, str)
    error = pyqtSignal(str, int)
    finished = pyqtSignal()


FONT = next((p for p in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\malgun.ttf") if os.path.exists(p)), None)
LINE = "This sentence is the page text for reading aloud."


def scan_image():
    d = fitz.open()
    pg = d.new_page(width=595, height=842)
    pg.insert_text((72, 120), LINE, fontsize=14)
    png = pg.get_pixmap(dpi=100).tobytes("png")
    d.close()
    return png


def make(path, kind, pages=1):
    """kind: scan · foreign · ours · digital"""
    png = scan_image()
    d = fitz.open()
    for _ in range(pages):
        pg = d.new_page(width=595, height=842)
        if kind == "digital":
            pg.insert_text((72, 120), LINE, fontsize=14)
            continue
        pg.insert_image(pg.rect, stream=png)
        if kind == "foreign":
            pg.insert_text((72, 120), LINE, fontsize=14, render_mode=3)               # 글꼴 helv — 다른 프로그램의 층
        elif kind == "ours":
            if FONT:
                pg.insert_text((72, 120), LINE, fontsize=14, render_mode=3, fontname="krfix", fontfile=FONT)
            else:
                pg.insert_text((72, 120), LINE, fontsize=14, render_mode=3, fontname="krfix")
    d.save(path)
    d.close()


root = tempfile.mkdtemp(prefix="polypdf_readocr_")
try:
    files = {}
    for k in ("scan", "foreign", "ours", "digital", "appocr", "cancel", "multi", "memo"):
        p = os.path.join(root, k + ".pdf")
        make(p, {"appocr": "scan", "cancel": "foreign", "multi": "foreign", "memo": "scan"}.get(k, k),
             pages=4 if k == "multi" else 1)
        files[k] = p
    # 'multi' 의 3쪽은 텍스트 쪽으로 — OCR 할 쪽에서 빠져야 한다
    d = fitz.open(files["multi"])
    pg = d.load_page(2)
    pg.clean_contents()
    d2 = fitz.open()
    for i in range(4):
        if i == 2:
            np_ = d2.new_page(width=595, height=842)
            np_.insert_text((72, 120), LINE, fontsize=14)
        else:
            d2.insert_pdf(d, from_page=i, to_page=i)
    d.close()
    d2.save(files["multi"] + ".tmp.pdf"); d2.close()
    os.replace(files["multi"] + ".tmp.pdf", files["multi"])

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    from viewer import read_ocr_offer as roo
    mw = MainWindow(); mw.resize(1600, 1000); mw.show(); app.processEvents()
    tts = FakeTts()
    mw._study_get_tts = lambda: tts
    from viewer.study import tts_engine as _te
    _te._ready = False          # 개발 폴더에 자연 음성 모델이 있어도 가짜 SAPI 를 쓰게(beta.9 전체 검사)
    ra = mw.read_aloud
    btn = mw.btn_read

    # 앱 OCR 결과가 있는 스캔 쪽(E) — 보류 저장소에 한 쪽
    from viewer.study.study_store import file_key_for
    st = mw._study_get_store()
    st.save_page(file_key_for(files["appocr"]), 0, LINE, dpi=300, engine="tesseract", source="ocr", conf=90.0,
                 words=[{"surface": w, "lemma": w, "lang": "eng", "x0": 100 + 60 * i, "y0": 400, "x1": 150 + 60 * i,
                         "y1": 440, "conf": 90} for i, w in enumerate(LINE.split())], lang="eng")

    # I — 쪽 판정이 어느 스레드에서 도는지
    main_th = threading.current_thread()
    judged_on_main = []
    _pk = roo.page_kind

    def _spy(*a, **k):
        judged_on_main.append(threading.current_thread() is main_th)
        return _pk(*a, **k)
    roo.page_kind = _spy

    # 가짜 OCR 일꾼 — 무엇을 OCR 하라 했는지 적는다
    OCR_CALLS = []

    def fake_start(path, pages, lang, watermark, skip_text=True):
        w = FakeOcr()
        OCR_CALLS.append((path, list(pages), w))
        mw._text_ocr_worker = w
    mw._start_text_ocr = fake_start

    def press(key, mode="1회", button="그대로 읽기", remember=False):
        if ra.is_active():
            ra.stop()
        ra.mode = mode
        app.processEvents()
        ASKED.clear(); tts.said.clear()
        ANSWER.update(button=button, remember=remember)
        mw._load_main(HistoryItem(files[key], 0, "", "bookmark")); QTest.qWait(500)
        btn.click()
        QTest.qWait(400)
        return list(ASKED), ra.is_active()

    asked, active = press("scan")
    chk(len(asked) == 1 and "글자층이 없습니다" in asked[0][1], "A 스캔 — ▶ 에서 OCR 을 권한다", asked)
    chk(active, "A [그대로 읽기] — 곧바로 읽는다", active)

    asked, active = press("foreign")
    chk(len(asked) == 1 and "다른 프로그램" in asked[0][1], "B 남의 글자층 — 묻는다", asked)
    chk(active and any("page text" in s for s in tts.said), "B [그대로 읽기] — 그 층의 글로 읽는다", tts.said)

    asked, active = press("ours")
    chk(not asked and active, "C 우리 글자층(krfix) — 묻지 않고 읽는다", (asked, active))

    asked, active = press("digital")
    chk(not asked and active, "D 텍스트 PDF — 묻지 않고 읽는다", (asked, active))

    asked, active = press("appocr")
    chk(not asked and active, "E 앱 OCR 이 있는 스캔 쪽 — 묻지 않는다", (asked, active))

    asked, active = press("cancel", button="취소")
    chk(len(asked) == 1 and not active and not OCR_CALLS, "F [취소] — 읽지도 OCR 하지도 않는다", (asked, active))

    asked, active = press("multi", mode="전체", button="OCR 하고 읽기")
    chk(len(asked) == 1 and "3쪽" in asked[0][2], "G 전체 구간 — OCR 할 쪽 수(텍스트 쪽 빼고 3쪽)", asked)
    chk(len(OCR_CALLS) == 1 and OCR_CALLS[0][1] == [0, 1, 3], "G OCR 할 쪽 = 구간의 스캔 쪽", [c[1] for c in OCR_CALLS])
    chk(not active, "G 시작 쪽 OCR 이 끝나기 전에는 읽지 않는다", active)
    if OCR_CALLS:
        w = OCR_CALLS[0][2]
        w.done.emit(1, [], 300, 0)                     # 다른 쪽이 먼저 끝나도
        QTest.qWait(100)
        chk(not ra.is_active(), "G 시작 쪽이 아닌 쪽 결과로는 시작하지 않는다", ra.is_active())
        w.done.emit(0, [], 300, 0)
        QTest.qWait(300)
        chk(ra.is_active() and ra._reading_page == 0, "G 시작 쪽 OCR 이 끝나면 그 자리부터 읽는다",
            (ra.is_active(), ra._reading_page))

    OCR_CALLS.clear()
    asked, active = press("memo", button="그대로 읽기", remember=True)
    chk(len(asked) == 1 and active, "H 처음엔 묻는다", asked)
    asked, active = press("memo", button="취소")
    chk(not asked and active, "H '다시 묻지 않음' 뒤에는 묻지 않고 그 답(그대로 읽기)", (asked, active))
    from viewer.pathutil import norm_key
    if ra.is_active():
        ra.stop()
    QTest.qWait(200)
    saved = (mw._build_settings_payload().get("preferences") or {}).get("read_ocr_offer") or {}
    # 설정 창 [확인]·다시 띄움과 같은 허용목록(`_apply_prefs` 첫 줄의 사전) — 뒤따르는 테마 다시 입히기는 오프스크린에서
    #   떨어지므로(이 기능과 무관) 대역 객체로 사전만 만든다
    import types
    stub = types.SimpleNamespace(_prefs={})
    try:
        MainWindow._apply_prefs(stub, dict(mw._prefs))
    except Exception:
        pass
    kept = (stub._prefs.get("read_ocr_offer") or {})
    chk(saved.get(norm_key(files["memo"])) == "read" and kept == saved,
        "H 답이 설정 저장에 남고 허용목록을 지난다", (saved, kept))

    chk(judged_on_main and not any(judged_on_main), "I 쪽 판정은 배경 스레드에서(%d번)" % len(judged_on_main),
        judged_on_main)
    if ra.is_active():
        ra.stop()
    mw._prefs.pop("read_ocr_offer", None)
    mw.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
