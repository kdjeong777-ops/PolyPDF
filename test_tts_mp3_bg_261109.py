# -*- coding: utf-8 -*-
"""261109-5: 본문 mp3 저장 중 '응답 없음' — 읽을 글 모으기도 배경에서 (영상·음성 SOT §1.8 의 4·응답성 SOT §4.8).

사용자 보고(beta.10): "mp3 저장했는데, 응답없음이 떴어. 한참후에 돌아왔어."

원인(실측): 합성(자연 음성·SAPI)·mp3 인코딩·파일 쓰기는 종전에도 배경 일꾼이었고 GIL 도 놓는다(다른 스레드 최장 정지
0.11초). 막힌 곳은 그 **앞** — `_on_main_mp3` 가 문서 **모든 쪽**의 읽을 글을 메인 스레드에서 모았다
(`ReadAloud._page_text` → `text_extract2.clean_page_texts` 를 쪽마다, 부를 때마다 PDF 를 새로 열어 단 가르기까지).
286MB 책이면 수십 초 메인이 멈췄고, 그 뒤에야 일꾼이 돌았다.

  A  [mp3] 단추를 누르면 곧바로 돌아온다 — 메인에서 쪽 글을 뽑지 않는다
  B  저장하는 동안 메인 최장 정지 < 1초(하트비트)
  C  글은 종전과 같다(텍스트 창과 같은 글 — 모든 쪽의 문장이 mp3 에)
  D  진행·[중단] 은 작업 창 길(job_add) 그대로
합성은 가짜(파일만 쓴다), 쪽 글 뽑기는 무겁게(쪽마다 0.05초) 흉내 낸다. 수정 전 코드로 A·B 가 실패한다.
"""
import os, sys, tempfile, shutil, threading, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "test")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from PyQt6.QtWidgets import QApplication, QFileDialog
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_mp3_bg_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사", echo=False)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


PAGES = 40
root = tempfile.mkdtemp(prefix="polypdf_mp3bg_")
try:
    src = os.path.join(root, "book.pdf")
    d = fitz.open()
    for i in range(PAGES):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((72, 110), "Page %d first sentence is here for reading." % (i + 1), fontsize=12)
        pg.insert_text((72, 140), "The second sentence of page %d ends now." % (i + 1), fontsize=12)
    d.save(src); d.close()
    out_parent = os.path.join(root, "out")
    os.makedirs(out_parent)

    from viewer import text_extract2 as tx
    main_th = threading.main_thread()
    on_main = []
    _cpt = tx.clean_page_texts

    def heavy(*a, **k):
        """쪽 글 뽑기 — 실제로는 큰 책에서 쪽마다 무겁다(PDF 열기·단 가르기). 쪽 수만큼 느리게."""
        on_main.append(threading.current_thread() is main_th)
        pages = a[1] if len(a) > 1 else k.get("pages")
        time.sleep(0.05 * max(1, len(pages or [1])))
        return _cpt(*a, **k)
    tx.clean_page_texts = heavy

    from viewer.study import mp3_export
    SAVED = []
    _real_synth = mp3_export.synth_to_mp3

    def fake_synth(segs, mp3, **k):
        SAVED.append((mp3, [s for s, _l in segs]))
        with open(mp3, "wb") as f:
            f.write(b"ID3")
        return mp3
    mp3_export.synth_to_mp3 = fake_synth
    mp3_export._make_voice = lambda rate, hidden=(): (None, {})
    mp3_export._find_voice = lambda voice, name: None
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: out_parent)

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    from viewer.study import tts_engine as _te
    _te._ready = False                                # 자연 음성 모델이 있어도 이 검사는 SAPI 길(합성은 가짜)
    mw = MainWindow(); mw.resize(1600, 1000); mw.show(); app.processEvents()
    mw._load_main(HistoryItem(src, 0, "", "bookmark")); QTest.qWait(600)
    jobs_added = []
    _ja = mw.job_add
    mw.job_add = lambda jid, *a, **k: (jobs_added.append(jid), _ja(jid, *a, **k))[1]

    # 하트비트 — 메인이 멈춘 가장 긴 틈
    beat = {"last": time.perf_counter(), "worst": 0.0}

    def _beat():
        now = time.perf_counter()
        beat["worst"] = max(beat["worst"], now - beat["last"])
        beat["last"] = now
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(_beat); hb.start()
    QTest.qWait(100)
    beat["worst"] = 0.0; beat["last"] = time.perf_counter()

    print("=== A·B. 누르면 곧바로, 메인은 멈추지 않는다 ===")
    on_main.clear()
    t0 = time.perf_counter()
    mw.btn_main_mp3.click()
    t_click = time.perf_counter() - t0
    chk(t_click < 0.5, "A [mp3] 를 누르면 곧바로 돌아온다", "%.2fs" % t_click)
    for _ in range(300):
        if SAVED and not mw._study_threads:
            break
        QTest.qWait(50)
    QTest.qWait(200)
    chk(on_main and not any(on_main), "A 쪽 글 뽑기는 배경 스레드에서", "메인에서 %d번 / 모두 %d번" % (sum(on_main), len(on_main)))
    chk(beat["worst"] < 1.0, "B 저장하는 동안 메인 최장 정지 < 1초", "%.2fs" % beat["worst"])

    print()
    print("=== C. 글은 종전과 같다 ===")
    allsent = [s for _m, ss in SAVED for s in ss]
    chk(len(SAVED) == 1 and SAVED[0][0].endswith(".mp3"), "C 책갈피 없는 책 = mp3 하나", str([m for m, _ in SAVED]))
    chk(all(any(("Page %d first" % (i + 1)) in s for s in allsent) for i in range(PAGES))
        and any("second sentence of page %d" % PAGES in s for s in allsent),
        "C 모든 쪽의 문장이 들어갔다", "%d 문장" % len(allsent))

    print()
    print("=== D. 작업 창 길 ===")
    chk("main_mp3" in jobs_added, "D 진행·[중단] 은 job_add('main_mp3')", str(jobs_added))

    # --- E·F·G: 진짜 synth_to_mp3·lameenc 로(합성 엔진만 가짜 — 소리 장치·모델 없이) ---
    from PyQt6.QtWidgets import QMessageBox
    from viewer import workers as _wk
    import importlib
    mp3_export.synth_to_mp3 = _real_synth
    WARN, PROG = [], []
    QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[1:3]) or QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)    # 이미 있는 폴더 → 새 폴더
    _st = mw.status.showMessage
    mw.status.showMessage = lambda m, *a: (PROG.append(m), _st(m, *a))[1]

    class FakeNeural:
        sample_rate = 44100
        fail = False
        gate = None

        def generate(self, t, lg, sid, steps, speed):
            if FakeNeural.fail:
                raise RuntimeError("합성 실패(시험)")
            if FakeNeural.gate is not None:
                FakeNeural.gate()
            time.sleep(0.02)
            return b"\x10\x00" * 2205
    _wk.StudyMp3Worker._neural = lambda self: (FakeNeural(), {"sid": 0, "steps": 4, "speed": 1.0})
    _te.export_choice = lambda mw_: {"neural": True, "sid": 0, "quality": "fast", "hidden_sapi": []}

    def run_save(timeout=60):
        n0 = len(mw._study_threads)
        mw.btn_main_mp3.click()
        t0 = time.time()
        QTest.qWait(200)
        while time.time() - t0 < timeout and mw._study_threads:
            QTest.qWait(50)
        QTest.qWait(200)

    def mp3s():
        out = []
        for dp, _dn, fns in os.walk(out_parent):
            out += [os.path.join(dp, f) for f in fns]
        return out

    print()
    print("=== E. 저장 뒤 파일이 실제로 있다·진행은 문장 단위 ===")
    for f in mp3s():
        os.remove(f)
    run_save()
    got = [f for f in mp3s() if f.endswith(".mp3")]
    chk(len(got) == 1 and os.path.getsize(got[0]) > 1000, "E mp3 파일이 생겼다(진짜 lameenc)", str([(os.path.basename(f), os.path.getsize(f)) for f in got]))
    chk(not [f for f in mp3s() if f.endswith(".part")], "E 임시 .part 가 남지 않는다")
    chk(any("문장" in m for m in PROG), "E 진행은 문장 단위(긴 구간도 움직인다)", str([m for m in PROG if m.startswith("mp3")][-3:]))
    chk(any("남은 시간" in m for m in PROG), "E 남은 시간을 보인다", "")
    chk(not WARN, "E 성공이면 경고창 없음", str(WARN))

    print()
    print("=== F. 실패는 창으로 알린다 ===")
    WARN.clear()
    FakeNeural.fail = True                             # 자연 음성 실패 → SAPI 로 물러섬 → SAPI 도 없음(가짜 voice None)
    run_save()
    FakeNeural.fail = False
    chk(WARN and "mp3" in str(WARN[0][0]) and "만들지 못했습니다" in str(WARN[0][1]),
        "F 하나도 못 만들면 경고창(까닭·폴더)", str(WARN)[:300])

    print()
    print("=== G. 구간 중간에도 [중단] 이 듣는다 ===")
    WARN.clear(); PROG.clear()
    for f in mp3s():
        os.remove(f)
    calls = {"n": 0}

    def _gate():
        calls["n"] += 1
        if calls["n"] == 10:
            for t in list(mw._study_threads):
                w = t if hasattr(t, "request_cancel") else None
                if w is not None:
                    w.request_cancel()
    FakeNeural.gate = _gate
    run_save()
    FakeNeural.gate = None
    chk(calls["n"] < 40, "G 문장 사이에서 멈춘다(80 문장 다 만들지 않는다)", "합성 %d번" % calls["n"])
    chk(not [f for f in mp3s() if f.endswith(".mp3") or f.endswith(".part")], "G 끊긴 구간은 파일을 남기지 않는다", str(mp3s()))
    chk(not WARN, "G 중단은 경고창이 아니다", str(WARN))

    hb.stop()
    mw.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
