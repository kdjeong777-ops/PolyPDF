# -*- coding: utf-8 -*-
"""261111-1: mp3 저장 전 예상 시간 묻기 — 자연 음성이 오래 걸리면 'Windows 기본 음성으로 빠르게 / 자연 음성으로 계속' (영상·음성 SOT §1.1).

사용자 결정(2026-11-11): "예상 시간 묻기". 실측(261109-5): 자연 음성은 이 PC 에서 쪽당 약 1분 — 598쪽 책이면 몇 시간.

  A  예상이 문턱(`ASK_MIN_S`) 이상이면 글을 다 모은 뒤 **메인 스레드에서** 묻는다 — 예상 시간·글자 수·SAPI 예상이 보인다
  B  [Windows 기본 음성으로 빠르게] — 이 저장만 SAPI, 자연 음성 합성 0번, 설정의 읽기 엔진은 그대로
  C  [자연 음성으로 계속] — 자연 음성으로, 끝까지 저장하면 실측 속도를 설정 `mp3_speed` 에 기억
  D  짧으면 묻지 않고 곧바로
  E  [취소] — 파일 없음·경고창 없음
  F  묻는 창이 떠 있는 동안 메인은 돈다(하트비트) — 일꾼이 기다린다
합성 엔진은 가짜(자연 음성·SAPI 모두), mp3 인코딩·파일 쓰기는 진짜. 수정 전 코드로 A·B·C·E 가 실패한다.
"""
import os, sys, tempfile, shutil, threading, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "test")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_mp3_ask_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


# 묻는 창 — 단추 글자로 누른다(진짜 QMessageBox 를 만들고 그 단추를 누름). 창이 떠 있는 시간도 흉내 낸다.
ANSWER = {"button": "자연 음성으로 계속", "hold_ms": 0}
ASKED = []


def _exec(box):
    ASKED.append((box.windowTitle(), box.text(), box.informativeText(),
                  threading.current_thread() is threading.main_thread()))
    if ANSWER["hold_ms"]:
        QTest.qWait(ANSWER["hold_ms"])
    for b in box.buttons():
        if b.text().replace("&", "") == ANSWER["button"]:
            b.click()
            break
    return 0
QMessageBox.exec = _exec
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[1:3]) or QMessageBox.StandardButton.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)    # 이미 있는 폴더 → 새 폴더

PAGES = 30
root = tempfile.mkdtemp(prefix="polypdf_mp3ask_")
try:
    src = os.path.join(root, "book.pdf")
    d = fitz.open()
    for i in range(PAGES):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((72, 110), "Page %d first sentence is here for reading aloud now." % (i + 1), fontsize=12)
        pg.insert_text((72, 140), "The second sentence of page %d ends right here." % (i + 1), fontsize=12)
    d.save(src); d.close()
    out_parent = os.path.join(root, "out")
    os.makedirs(out_parent)
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: out_parent)

    from viewer.study import mp3_export
    from viewer import workers as _wk
    CALLS = {"neural": 0, "sapi": 0}

    class FakeNeural:
        sample_rate = 44100

        def generate(self, t, lg, sid, steps, speed):
            CALLS["neural"] += 1
            time.sleep(0.03)                 # 끝까지 1초가 넘게 — 짧은 저장은 속도 기억에서 뺀다(speed_after)
            return b"\x10\x00" * 2205
    _wk.StudyMp3Worker._neural = lambda self: (FakeNeural(), {"sid": 0, "steps": 4, "speed": 1.0})
    mp3_export._make_voice = lambda rate, hidden=(): (None, {})
    mp3_export._find_voice = lambda voice, name: None

    def fake_sapi_pcm(voice, tok, forced, segments, on_seg=None):
        CALLS["sapi"] += 1
        lrc = []
        for i, (t, _l) in enumerate(segments):
            lrc.append("[00:%02d.00]%s" % (i % 60, t))
            if on_seg is not None:
                on_seg(i + 1)
        return b"\x10\x00" * 2205 * len(segments), lrc
    mp3_export._segments_pcm = fake_sapi_pcm

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    from viewer.study import tts_engine as _te
    mw = MainWindow(); mw.resize(1600, 1000); mw.show(); app.processEvents()
    mw._load_main(HistoryItem(src, 0, "", "bookmark")); QTest.qWait(600)
    _te.export_choice = lambda mw_: {"neural": True, "sid": 0, "quality": "fast", "hidden_sapi": []}
    mw._prefs["tts_voice"] = {"engine": "neural"}
    _st = mw.status.showMessage
    MSGS = []
    mw.status.showMessage = lambda m, *a: (MSGS.append(m), _st(m, *a))[1]

    def mp3s():
        out = []
        for dp, _dn, fns in os.walk(out_parent):
            out += [os.path.join(dp, f) for f in fns if f.endswith(".mp3")]
        return out

    def run_save(timeout=60):
        mw.btn_main_mp3.click()
        t0 = time.time()
        QTest.qWait(200)
        while time.time() - t0 < timeout and mw._study_threads:
            QTest.qWait(50)
        QTest.qWait(200)

    def reset():
        ASKED.clear(); WARN.clear(); MSGS.clear()
        CALLS.update(neural=0, sapi=0)
        for f in mp3s():
            os.remove(f)

    SLOW = {"neural_fast": 0.5, "sapi": 190.0}           # 글 약 3,000자 → 자연 음성 약 100분(문턱 넘음)

    print("=== A·B. 길면 묻고, [빠르게] 면 이 저장만 SAPI ===")
    reset()
    mw._prefs["mp3_speed"] = dict(SLOW)
    ANSWER.update(button="Windows 기본 음성으로 빠르게", hold_ms=0)
    run_save()
    chk(len(ASKED) == 1, "A 오래 걸리면 저장 전에 묻는다", str(len(ASKED)))
    if ASKED:
        title, text, info, on_main = ASKED[0]
        chk(on_main, "A 묻는 창은 메인 스레드에서")
        chk("시간" in text and "자" in info and "Windows 기본 음성이면" in info, "A 예상 시간·글자 수·SAPI 예상이 보인다",
            repr(text + " / " + info))
    chk(CALLS["neural"] == 0 and CALLS["sapi"] >= 1 and len(mp3s()) == 1, "B [빠르게] — SAPI 로 저장, 자연 음성 합성 0번",
        "%s 파일 %d" % (CALLS, len(mp3s())))
    chk(mw._prefs.get("tts_voice", {}).get("engine") == "neural", "B 설정의 읽기 엔진은 그대로(이 저장만)",
        str(mw._prefs.get("tts_voice")))

    print()
    print("=== C. [계속] — 자연 음성, 실측 속도를 기억 ===")
    reset()
    mw._prefs["mp3_speed"] = dict(SLOW)
    ANSWER.update(button="자연 음성으로 계속", hold_ms=0)
    run_save()
    chk(len(ASKED) == 1 and CALLS["neural"] > 0 and CALLS["sapi"] == 0 and len(mp3s()) == 1,
        "C [계속] — 자연 음성으로 저장", "%s 파일 %d" % (CALLS, len(mp3s())))
    sp = (mw._prefs.get("mp3_speed") or {}).get("neural_fast")
    chk(sp and sp > SLOW["neural_fast"], "C 끝까지 저장하면 실측 속도(글자/초)를 기억", str(mw._prefs.get("mp3_speed")))
    pay = (mw._build_settings_payload().get("preferences") or {}).get("mp3_speed")
    chk(pay == mw._prefs.get("mp3_speed"), "C 기억한 속도가 설정 저장에 남는다", str(pay))

    print()
    print("=== D. 짧으면 묻지 않는다 ===")
    reset()
    mw._prefs["mp3_speed"] = {"neural_fast": 5000.0, "sapi": 190.0}
    run_save()
    chk(not ASKED and CALLS["neural"] > 0 and len(mp3s()) == 1, "D 문턱 아래면 묻지 않고 곧바로 자연 음성", "%s 물음 %d" % (CALLS, len(ASKED)))

    print()
    print("=== E·F. [취소] — 아무것도 만들지 않는다, 창이 떠 있는 동안 메인은 돈다 ===")
    reset()
    mw._prefs["mp3_speed"] = dict(SLOW)
    ANSWER.update(button="취소", hold_ms=1500)
    beat = {"last": time.perf_counter(), "worst": 0.0}

    def _beat():
        now = time.perf_counter()
        beat["worst"] = max(beat["worst"], now - beat["last"]); beat["last"] = now
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(_beat); hb.start()
    QTest.qWait(100); beat["worst"] = 0.0; beat["last"] = time.perf_counter()
    run_save()
    hb.stop()
    chk(len(ASKED) == 1 and not mp3s() and CALLS == {"neural": 0, "sapi": 0}, "E [취소] — 파일·합성 없음",
        "%s 파일 %d" % (CALLS, len(mp3s())))
    chk(not WARN and any("취소" in m for m in MSGS), "E 경고창이 아니라 '취소했습니다' 한 줄", str((WARN, MSGS[-2:])))
    chk(beat["worst"] < 1.0, "F 묻는 동안·저장 동안 메인 최장 정지 < 1초", "%.2fs" % beat["worst"])

    mw.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
