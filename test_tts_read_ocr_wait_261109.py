# -*- coding: utf-8 -*-
"""261109-6: '전체' 를 골랐는데 처음엔 지금 쪽만 읽고 끝나던 결함 — [OCR 하고 읽기] 뒤 읽기는 OCR 이 아직 안 된 쪽을 기다린다
(영상·음성 SOT §1.11).

사용자 보고(beta.10, 다른 컴퓨터): "'전체'를 선택했으나, 현재 페이지만 읽고 말았어. 이후 다른 걸 선택했다가 '전체'를
선택하니 문제없었어."

원인(재현): OCR 결과가 없는 스캔 PDF 에서 ▶ 를 누르면 OCR 을 권하고(261108-30), [OCR 하고 읽기] 면 **시작 쪽** OCR 이
끝나자마자 읽기를 시작한다. 뒤쪽은 아직 OCR 중이라 읽을 글이 비어 있는데, 읽기는 빈 쪽을 곧바로 건너뛰어 —
OCR 보다 훨씬 빨리 — 마지막 쪽까지 가서 '읽기 완료' 로 멈췄다. 두 번째 ▶ 에서는 OCR 이 끝나 있어 정상이었다.

  A  시작 쪽 OCR 이 끝나면 읽기 시작, 다음 쪽 OCR 이 끝나기 전에는 **기다린다**(멈추지도 건너뛰지도 않는다)
  B  다음 쪽 OCR 이 끝나면 그 쪽을 읽는다
  C  OCR 이 다 끝나면(일꾼 끝) 남은 쪽을 읽고 '전체' 대로 끝까지
  D  OCR 을 중단(오류)하면 기다리지 않고 남은 쪽은 있는 글로 읽는다(매달리지 않는다)
  E  뒤쪽 결과가 오면 그 앞의 결과 없이 지나간 쪽(일꾼이 건너뛴 쪽)도 풀린다
창을 띄워 ▶ 단추를 누른다 — 소리는 내지 않는다(가짜 TTS, 말은 곧바로 끝), OCR 은 가짜 일꾼(결과는 보류 저장소에 넣고 신호).
수정 전 코드로 A·B·C 가 실패한다.
"""
import os, sys, tempfile, shutil

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "test")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QObject, pyqtSignal
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_read_ocr_wait_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


ANSWER = {"button": "OCR 하고 읽기"}


def _exec(box):
    for b in box.buttons():
        if b.text().replace("&", "") == ANSWER["button"]:
            b.click()
            break
    return 0
QMessageBox.exec = _exec


class FakeTts:
    """말은 곧바로 끝난다. 무엇을 읽었는지만 적는다."""
    def __init__(self):
        self.said = []
    def available(self): return True
    def speak_reading(self, text): self.said.append(text); return True
    def speak(self, text, lang="eng", queue=False): self.said.append(text); return True
    def is_speaking(self): return False
    def saw_speaking(self): return True
    def stop(self): pass
    def __getattr__(self, name): return lambda *a, **k: None


class FakeOcr(QObject):
    done = pyqtSignal(int, object, int, int)
    progress = pyqtSignal(int, int, str)
    error = pyqtSignal(str, int)
    finished = pyqtSignal()


PAGES = 4
WORDS = ["Alpha", "Bravo", "Charlie", "Delta"]


def line(p):
    return "%s page sentence is read aloud here now." % WORDS[p]


root = tempfile.mkdtemp(prefix="polypdf_readocrwait_")
try:
    src = os.path.join(root, "scan.pdf")
    d = fitz.open()
    for i in range(PAGES):
        t = fitz.open()
        tp = t.new_page(width=595, height=842)
        tp.insert_text((72, 120), line(i), fontsize=14)
        png = tp.get_pixmap(dpi=100).tobytes("png")
        t.close()
        pg = d.new_page(width=595, height=842)
        pg.insert_image(pg.rect, stream=png)          # 글자층 없는 스캔 쪽
    d.save(src); d.close()

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    from viewer.study import tts_engine as _te
    from viewer.study.study_store import file_key_for
    _te._ready = False                                # 개발 폴더에 자연 음성 모델이 있어도 가짜 SAPI 로
    mw = MainWindow(); mw.resize(1600, 1000); mw.show(); app.processEvents()
    tts = FakeTts()
    mw._study_get_tts = lambda: tts
    ra = mw.read_aloud
    st = mw._study_get_store()
    fk = file_key_for(src)

    OCR = []

    def fake_start(path, pages, lang, watermark, skip_text=True):
        w = FakeOcr()
        OCR.append((list(pages), w))
        mw._text_ocr_worker = w
    mw._start_text_ocr = fake_start

    def ocr_done(w, p):
        """진짜 OCR 처럼 — 결과를 보류 저장소에 넣고 done 신호."""
        txt = line(p)
        st.save_page(fk, p, txt, dpi=300, engine="tesseract", source="ocr", conf=90.0,
                     words=[{"surface": x, "lemma": x, "lang": "eng", "x0": 100 + 70 * i, "y0": 400,
                             "x1": 160 + 70 * i, "y1": 440, "conf": 90} for i, x in enumerate(txt.split())], lang="eng")
        w.done.emit(p, [], 300, 0)

    def read_pages():
        return [k for k in range(PAGES) if any(WORDS[k] in s for s in tts.said)]

    def press():
        if ra.is_active():
            ra.stop()
        OCR.clear(); tts.said.clear()
        mw._load_main(HistoryItem(src, 0, "", "bookmark")); QTest.qWait(500)
        ra.mode = "전체"
        app.processEvents()
        mw.btn_read.click()
        QTest.qWait(300)

    print("=== A. 다음 쪽 OCR 을 기다린다 ===")
    press()
    chk(len(OCR) == 1 and OCR[0][0] == list(range(PAGES)), "준비 — OCR 을 권해 모든 쪽 OCR", str([o[0] for o in OCR]))
    w = OCR[0][1] if OCR else FakeOcr()
    ocr_done(w, 0)
    QTest.qWait(1500)                                 # 수정 전: 빈 쪽을 건너뛰어 이미 끝났다
    chk(ra.is_active(), "A 시작 쪽을 읽은 뒤 멈추지 않는다(다음 쪽 OCR 기다림)", "active=%s" % ra.is_active())
    chk(read_pages() == [0] and ra._reading_page == 1, "A 지금은 1쪽만 읽고 2쪽에서 기다린다",
        "읽은 쪽=%s 읽는 쪽=%s" % (read_pages(), ra._reading_page))

    print()
    print("=== B. 다음 쪽 OCR 이 끝나면 그 쪽을 ===")
    ocr_done(w, 1)
    QTest.qWait(1500)
    chk(read_pages() == [0, 1] and ra.is_active() and ra._reading_page == 2, "B 2쪽을 읽고 3쪽을 기다린다",
        "읽은 쪽=%s 읽는 쪽=%s" % (read_pages(), ra._reading_page))

    print()
    print("=== C. OCR 이 다 끝나면 끝까지 ===")
    ocr_done(w, 2)
    ocr_done(w, 3)
    w.finished.emit()
    QTest.qWait(2000)
    chk(read_pages() == [0, 1, 2, 3], "C '전체' — 모든 쪽을 읽었다", str(read_pages()))
    chk(not ra.is_active(), "C 다 읽으면 멈춘다")

    print()
    print("=== E. 뒤쪽 결과가 오면 앞의 건너뛴 쪽도 풀린다 ===")
    src = os.path.join(root, "scan3.pdf")
    shutil.copy(os.path.join(root, "scan.pdf"), src)
    fk = file_key_for(src)
    press()
    w = OCR[0][1] if OCR else FakeOcr()
    ocr_done(w, 0)
    QTest.qWait(800)
    ocr_done(w, 2)                                    # 2쪽(0부터 1)은 일꾼이 결과 없이 건너뛰었다(글자층이 멀쩡한 쪽처럼)
    QTest.qWait(1500)
    chk(2 in read_pages() and ra.is_active() and ra._reading_page == 3, "E 1쪽(건너뜀)을 지나 2쪽을 읽고 3쪽을 기다린다",
        "읽은 쪽=%s 읽는 쪽=%s" % (read_pages(), ra._reading_page))
    if ra.is_active():
        ra.stop()

    print()
    print("=== D. OCR 중단이면 기다리지 않는다 ===")
    src2 = os.path.join(root, "scan2.pdf")
    shutil.copy(src, src2)
    src = src2
    fk = file_key_for(src)
    press()
    w = OCR[0][1] if OCR else FakeOcr()
    ocr_done(w, 0)
    QTest.qWait(500)
    w.error.emit("중단", 0)
    for _ in range(60):
        if not ra.is_active():
            break
        QTest.qWait(100)
    chk(not ra.is_active() and read_pages() == [0], "D OCR 이 멈추면 남은 쪽(글 없음)을 지나 끝낸다 — 기다려 매달리지 않는다",
        "active=%s 읽은 쪽=%s" % (ra.is_active(), read_pages()))

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
