# -*- coding: utf-8 -*-
"""261108-28: 자연 음성(Supertonic 3 + sherpa-onnx) — 엔진 고르기·대체·배경 합성·구성요소·mp3·설정 (영상·음성 SOT §1.10).

사용자 지시: "tts가 아직 기계음이야. 이를 부드러운 인간음성으로 읽을 수 있는 방안을 검색하여 계획해" → 실측 → "앱에 넣기 진행".

  (A) 엔진 고르기 — 설정 값 정리, 모델 없으면 SAPI, 'sapi' 면 늘 SAPI, 있으면 자연 음성
  (B) 메인 스레드에서 모델 싣기·합성 0 — Synth 는 메인에서 부르면 거절, NeuralReader 는 배경 일꾼에서만 부른다
  (C) 대체 — 자연 음성 합성이 실패하면 본문 읽기가 SAPI 로 이어 읽는다
  (D) 구성요소 — 해시가 틀리면 아무것도 쓰지 않는다, 맞으면 풀어 제자리, 위로 올라가는 이름은 막는다
  (E) mp3 — 자연 음성이면 44.1kHz·ID3 '생성 음성' 표기·가사는 표시 글
  (F) 설정 — '읽기 음성' 쪽 값이 result_prefs 로 나오고 허용목록(_apply_prefs)에 남는다
  (G) 실제 합성 — 모델이 있으면(설치 폴더 voices\\ 또는 실측 폴더) 배경 스레드에서 한 문장. 없으면 SKIP
모델이 없는 CI 에서도 (A)~(F) 는 가짜 엔진으로 돈다. 소리는 내지 않는다(가짜 재생기).
"""
import os, sys, tempfile, shutil, threading, time, io, tarfile, hashlib

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QThread, QObject
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_tts_neural_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


def wait_until(fn, ms=3000):
    t0 = time.time()
    while time.time() - t0 < ms / 1000.0:
        if fn():
            return True
        QTest.qWait(20)
    return fn()


try:
    from viewer.study import tts_engine, neural_tts
except Exception as e:
    tts_engine = neural_tts = None
    chk(False, "(A) viewer.study.tts_engine·neural_tts 가 있다", repr(e))


class FakeSapi:
    def __init__(self):
        self.said = []
        self.rate = None

    def available(self):
        return True

    def speak_reading(self, text):
        self.said.append(text)
        return True

    def speak(self, text, lang="eng", queue=False):
        self.said.append(text)
        return True

    def is_speaking(self):
        return False

    def saw_speaking(self):
        return True

    def stop(self):
        pass

    def set_rate(self, r):
        self.rate = r

    def set_voice_name(self, n):
        pass


class FakePlayer:
    def __init__(self):
        self.fed = []

    def feed(self, pcm):
        self.fed.append(pcm)

    def busy(self):
        return False

    def stop(self):
        pass

    def played_s(self):
        return 0.0

    def written_s(self):
        return 0.0


class FakeSynth:
    """스레드를 적는 가짜 모델 — 0.2초짜리 소리를 준다."""
    threads = []
    fail = False

    def __init__(self):
        self.sample_rate = 44100

    def _note(self, what):
        FakeSynth.threads.append((what, QThread.currentThread() is app.thread()))

    def load(self):
        self._note("load")

    def unload(self):
        pass

    def generate(self, text, lang="ko", sid=0, steps=4, speed=1.0):
        self._note("generate")
        if FakeSynth.fail:
            raise RuntimeError("fake synth failure")
        return b"\x01\x00" * int(44100 * 0.2)


if tts_engine is not None:
    print("=== (A) 엔진 고르기 ===")
    nc = tts_engine.normalize_cfg
    chk(nc(None) == {"engine": "auto", "sid": 0, "quality": "fast", "normalize": True, "split_lang": True},
        "(A) 기본값 자동·목소리 1·빠름·숫자 풀기 켬·영어 구절 나눔 켬", str(nc(None)))
    chk(nc({"engine": "x", "sid": 42, "quality": "?"}) == {"engine": "auto", "sid": 9, "quality": "fast",
                                                           "normalize": True, "split_lang": True},
        "(A) 틀린 값은 기본·범위로", str(nc({"engine": "x", "sid": 42, "quality": "?"})))

    class _MW(QObject):
        def __init__(self, prefs):
            super().__init__()
            self._prefs = prefs
            self.sapi = FakeSapi()

        def _study_get_tts(self):
            return self.sapi

    tts_engine._ready = False                        # 모델 없음
    mw = _MW({"tts_voice": {"engine": "neural"}})
    chk(tts_engine.reader_for(mw) is mw.sapi, "(A) 모델이 없으면 '자연 음성' 을 골라도 SAPI 로")
    tts_engine._ready = True                         # 모델 있음(가짜)
    orig_avail = neural_tts.NeuralReader.available
    neural_tts.NeuralReader.available = lambda self: not self._failed
    try:
        mw = _MW({"tts_voice": {"engine": "sapi"}})
        chk(tts_engine.reader_for(mw) is mw.sapi, "(A) 'Windows 기본 음성' 이면 모델이 있어도 SAPI")
        mw = _MW({"tts_voice": {"engine": "auto", "sid": 3, "quality": "high"}})
        r = tts_engine.reader_for(mw)
        chk(isinstance(r, neural_tts.NeuralReader) and r.sid == 3 and r.steps == neural_tts.STEPS["high"],
            "(A) 자동이면 모델이 있을 때 자연 음성(목소리·음질 반영)", repr(r))
        chk(tts_engine.reader_for(mw) is r, "(A) 같은 창은 같은 자연 음성 읽개를 다시 쓴다")
        ex = tts_engine.export_choice(mw)
        chk(ex == {"neural": True, "sid": 3, "quality": "high", "normalize": True, "split_lang": True},
            "(A) mp3 에 넘길 값", str(ex))
        mw._prefs["tts_voice"].update(normalize=False, split_lang=False)
        r2 = tts_engine.reader_for(mw)
        chk(r2 is r and not r.normalize and not r.split_lang, "(A) 앞단 설정이 읽개에 들어간다")
        chk(tts_engine.export_choice(mw)["normalize"] is False, "(A) 앞단 설정이 mp3 에도")
    finally:
        neural_tts.NeuralReader.available = orig_avail
    s_mix = "이 방법은 Superpave mix design method 에 따라 25 mm 로 정한다."
    p1 = neural_tts.pieces_for(s_mix, True, True)
    p2 = neural_tts.pieces_for(s_mix, False, True)
    p3 = neural_tts.pieces_for(s_mix, True, False)
    chk([lg for _t, lg in p1] == ["ko", "en", "ko"] and "밀리미터" in p1[2][0], "(A) 기본 앞단 — 정규화·영어 구절 나눔", str(p1))
    chk("25 mm" in p2[2][0] and "밀리미터" not in "".join(t for t, _ in p2), "(A) '숫자·단위 풀어 읽기' 끄면 원문", str(p2))
    chk(len(p3) == 1 and p3[0][1] == "ko" and "밀리미터" in p3[0][0], "(A) '영어로 읽기' 끄면 한 문장 통째 ko", str(p3))

    print()
    print("=== (B) 메인 스레드에서 싣기·합성 0 ===")
    s = neural_tts.Synth(mdir=tempfile.gettempdir())
    try:
        s.load()
        ok_guard = False
    except RuntimeError as e:
        ok_guard = "main thread" in str(e)
    chk(ok_guard, "(B) Synth.load 를 메인에서 부르면 거절한다")
    try:
        s.generate("가")
        ok_guard = False
    except RuntimeError as e:
        ok_guard = "main thread" in str(e)
    chk(ok_guard, "(B) Synth.generate 를 메인에서 부르면 거절한다")

    FakeSynth.threads = []
    nr = neural_tts.NeuralReader(None, synth_factory=FakeSynth, player_factory=FakePlayer)
    nr.available = lambda: True
    nr.warm_up()
    ok = nr.speak_reading("시편 3개를 만든다, 그리고 25 mm 두께로 다진 뒤 양생한다.")
    chk(ok and nr.is_speaking(), "(B) 말하기를 맡기면 합성이 끝날 때까지 '말하는 중'")
    chk(len(nr._queue) == 2, "(B) 첫 문장이 길면 쉼표에서 둘로 — 앞 조각이 먼저", str(len(nr._queue)))
    wait_until(lambda: not nr.is_speaking())
    chk(not nr.is_speaking() and len(nr._player.fed) == 2, "(B) 조각 차례대로 재생기에", str(len(nr._player.fed)))
    nr.prefetch(["둘째 문장이다.", "셋째 문장이다.", "넷째."])
    wait_until(lambda: not nr._pending)
    keys = [k[0] for k in nr._cache]
    chk("둘째 문장이다." in keys and "셋째 문장이다." in keys and "넷째." not in keys,
        "(B) 다음 %d 문장만 미리 합성" % neural_tts.PREFETCH, str(keys))
    chk(FakeSynth.threads and not any(main for _w, main in FakeSynth.threads),
        "(B) 모델 싣기·합성이 모두 배경 스레드에서", str(FakeSynth.threads[:4]))
    chk(any(w == "load" for w, _m in FakeSynth.threads), "(B) 읽기 시작 때 미리 싣기(warm_up)")
    nr.speak_reading("둘째 문장이다.")
    chk(len(nr._player.fed) == 3 and not nr.is_speaking(), "(B) 미리 만든 문장은 곧바로 재생")
    nr.stop()
    chk(not nr._queue and nr._first, "(B) 멈추면 대기열을 버린다(다음 읽기의 첫 조각은 다시 짧게)")
    nr.shutdown()

    print()
    print("=== (C) 실패하면 SAPI 로 이어 읽는다 ===")
    from viewer.widgets.read_aloud import ReadAloud

    class _SB:
        msgs = []

        def showMessage(self, m, *a):
            _SB.msgs.append(m)

    class _View:
        def clear_word_highlights(self):
            pass

        def highlight_word_groups(self, *a, **k):
            pass

    class _MW2(QObject):
        status = _SB()
        main_view = _View()

        def __init__(self):
            super().__init__()
            self._prefs = {"tts_voice": {"engine": "neural"}}
            self.sapi = FakeSapi()

        def _study_get_tts(self):
            return self.sapi

    FakeSynth.fail = True
    mw2 = _MW2()
    nr2 = neural_tts.NeuralReader(mw2, synth_factory=FakeSynth, player_factory=FakePlayer)
    nr2.available = lambda: not nr2._failed
    mw2._neural_reader = nr2
    ra = ReadAloud(mw2)
    ra._active = True
    ra._eng = nr2
    ra._sents = ["첫 문장이다.", "둘째 문장이다."]
    ra._srects, ra._spans, ra._para_end = [], [], [False, False]
    ra._pages, ra._pi = [0], 0
    ra._speak_cur()
    wait_until(lambda: nr2._failed)
    chk(nr2._failed, "(C) 가짜 모델 실패가 읽개에 남는다", nr2.failed_msg)
    ra._pause_until = time.time() - 1
    ra._tick(); ra._pause_until = time.time() - 1; ra._tick()
    chk(mw2.sapi.said[:2] == ["첫 문장이다.", "둘째 문장이다."] and ra._eng is mw2.sapi,
        "(C) 실패한 그 문장부터 SAPI 가 이어 읽는다(건너뛰지 않는다)", str(mw2.sapi.said))
    chk(any("자연 음성을 쓸 수 없어" in m for m in _SB.msgs), "(C) 상태 표시줄에 알린다", str(_SB.msgs[-1:]))
    ra._timer.stop()
    nr2.shutdown()
    FakeSynth.fail = False

    print()
    print("=== (D) 구성요소 — 고정 SHA-256 ===")
    from viewer import components
    root = tempfile.mkdtemp(prefix="polypdf_voice_")
    orig_vd = neural_tts.voices_dir
    neural_tts.voices_dir = lambda: __import__("pathlib").Path(root) / "voices"
    try:
        def make_tar(evil=False):
            bio = io.BytesIO()
            with tarfile.open(fileobj=bio, mode="w:bz2") as t:
                for n in neural_tts.MODEL_FILES:
                    data = ("fake " + n).encode()
                    ti = tarfile.TarInfo(neural_tts.MODEL_INNER + "/" + n); ti.size = len(data)
                    t.addfile(ti, io.BytesIO(data))
                if evil:
                    data = b"evil"
                    ti = tarfile.TarInfo("../../evil.txt"); ti.size = len(data)
                    t.addfile(ti, io.BytesIO(data))
            p = os.path.join(root, "m%d.tar.bz2" % int(evil))
            open(p, "wb").write(bio.getvalue())
            return p, hashlib.sha256(bio.getvalue()).hexdigest()
        good, good_sha = make_tar()
        url = "file:///" + good.replace("\\", "/")
        licp = os.path.join(root, "LICENSE.txt")
        open(licp, "wb").write(b"fake Open RAIL-M license text")
        lic_sha = hashlib.sha256(b"fake Open RAIL-M license text").hexdigest()
        LIC = dict(license_url="file:///" + licp.replace("\\", "/"), license_sha256=lic_sha)
        ok, info = components.install_voice(url=url, sha256=good_sha, license_url=LIC["license_url"],
                                            license_sha256="0" * 64)
        chk(not ok and not neural_tts.model_dir().exists(), "(D) 라이선스 원문 해시가 틀려도 설치하지 않는다", info)
        ok, info = components.install_voice(url=url, sha256="0" * 64, **LIC)
        chk(not ok and not neural_tts.model_dir().exists(), "(D) 해시가 틀리면 설치하지 않는다(아무것도 안 씀)", info)
        left = os.listdir(neural_tts.voices_dir()) if neural_tts.voices_dir().exists() else []
        chk(left == [], "(D) 받던 파일·푼 폴더도 남기지 않는다", str(left))
        ok, info = components.install_voice(url=url, sha256=good_sha, **LIC)
        chk(ok and neural_tts.model_ready(), "(D) 해시가 맞으면 풀어 제자리(파일 7개)", info)
        chk((neural_tts.model_dir() / neural_tts.LICENSE_LOCAL).read_bytes() == b"fake Open RAIL-M license text",
            "(D) 모델 라이선스 원문을 모델 곁에 둔다(사본 동봉)")
        # 261108-32 덧붙임: 100% 뒤 단계 알림 · 풀기 중 중단 · 남은 조각 치우기
        phases = []

        def prog(done, total):
            return True
        prog.phase = lambda text, pct=-1: phases.append(text)
        vd = neural_tts.voices_dir()
        (vd / (neural_tts.MODEL_ARCHIVE + ".part")).write_bytes(b"half")
        (vd / (".unpack_" + neural_tts.MODEL_DIRNAME)).mkdir(exist_ok=True)
        ok, info = components.install_voice(url=url, sha256=good_sha, progress=prog, **LIC)
        chk(ok and any("무결성" in p for p in phases) and any("압축 푸는 중" in p for p in phases)
            and any("파일 확인" in p for p in phases), "(D) 내려받기 뒤 단계(확인·풀기·파일 확인)를 알린다", str(phases[:4]))
        chk(sorted(os.listdir(vd)) == [neural_tts.MODEL_DIRNAME], "(D) 받다 만 .part·풀다 만 폴더를 치우고 깨끗이",
            str(os.listdir(vd)))
        chk(components.voice_installed() == neural_tts.engine_importable(), "(D) 설치 판정은 디스크(모델+라이선스 사본)")
        shutil.rmtree(neural_tts.model_dir())

        def cancel_in_unpack(done, total):
            return done >= 0                         # 내려받기는 두고, 풀기 단계의 중단 물음에 '중단'
        ok, info = components.install_voice(url=url, sha256=good_sha, progress=cancel_in_unpack, **LIC)
        chk(not ok and os.listdir(vd) == [], "(D) 풀기 중에 누른 [중단] 도 듣는다 — 아무것도 남기지 않는다", str(os.listdir(vd)))
        ok, info = components.install_voice(url=url, sha256=good_sha, **LIC)
        from viewer.update_controller import ComponentInstallWorker
        w = ComponentInstallWorker("voice", "t", None, "")
        got = []
        w.progress.connect(lambda p, m: got.append((p, m)))
        chk(w._prog(-1, 0) is True and not got, "(D) 일꾼 — 중단 물음(-1)은 진행 글을 내지 않는다")
        w.request_cancel()
        chk(w._prog(-1, 0) is False, "(D) 일꾼 — [중단] 뒤 물음에는 '멈춤'")
        evil, evil_sha = make_tar(evil=True)
        ok, info = components.install_voice(url="file:///" + evil.replace("\\", "/"), sha256=evil_sha, **LIC)
        chk(not ok and not os.path.exists(os.path.join(root, "evil.txt")) and neural_tts.model_ready(),
            "(D) 위로 올라가는 이름은 막고 기존 모델은 그대로", info)
        chk(components.sha256_ok("x", b"") is False and neural_tts.MODEL_SHA256 ==
            "82fa96f91c4ef8abaae3a14a3f4153facf88bed821d1f7331cec2700f432c427",
            "(D) 앱에 박은 모델 해시 = 실측 묶음 해시")
        base = "https://github.com/kdjeong777-ops/PolyPDF/releases/download/components/"
        chk(neural_tts.MODEL_URL == base + neural_tts.MODEL_ARCHIVE and neural_tts.LICENSE_URL == base + neural_tts.LICENSE_ASSET,
            "(D) 받는 곳은 우리 components 릴리스 사본(모델·라이선스)", neural_tts.MODEL_URL)
        chk(neural_tts.LICENSE_SHA256 == "0d944a9110fed9a9602d60e0423a272903e7bd21ab060490774efc77c2275e9f",
            "(D) 라이선스 원문 해시도 앱에 박는다")
    finally:
        neural_tts.voices_dir = orig_vd
        shutil.rmtree(root, ignore_errors=True)

    print()
    print("=== (E) mp3 — 자연 음성 길 ===")
    from viewer.study import mp3_export
    d = tempfile.mkdtemp(prefix="polypdf_nmp3_")
    try:
        holder = {}

        def job():
            try:
                fs = FakeSynth()
                mp3_export.synth_to_mp3([("시편 3개를 만든다.", "ko"), ("The layer is 25 mm thick.", "en")],
                                        os.path.join(d, "a.mp3"), lrc_path=os.path.join(d, "a.lrc"),
                                        neural=fs, neural_opts={"sid": 2, "steps": 4})
                holder["ok"] = True
            except Exception as e:
                holder["err"] = repr(e)
        th = threading.Thread(target=job); th.start(); th.join(30)
        chk(holder.get("ok"), "(E) 자연 음성으로 mp3 를 만든다(배경 스레드)", holder.get("err", ""))
        if holder.get("ok"):
            b = open(os.path.join(d, "a.mp3"), "rb").read()
            chk(b[:3] == b"ID3" and "생성 음성".encode("utf-16-le") in b[:400],
                "(E) ID3 에 '생성 음성' 표기")
            lines = open(os.path.join(d, "a.lrc"), encoding="utf-8").read().splitlines()
            chk([ln[10:] for ln in lines] == ["시편 3개를 만든다.", "The layer is 25 mm thick."],
                "(E) 가사는 표시 글", str(lines))
            # 44.1kHz: 문장 둘 = 조각마다 0.2초 소리 + 쉼 0.2초 → 둘째 가사 시각이 0.2초 남짓
            chk(lines[1].startswith("[00:00.4") or lines[1].startswith("[00:00.6"),
                "(E) 가사 시각은 44.1kHz 기준", lines[1])
    finally:
        shutil.rmtree(d, ignore_errors=True)
    import viewer.workers as _wk
    chk("tts_cfg" in _wk.StudyMp3Worker.__init__.__code__.co_varnames, "(E) mp3 일꾼이 엔진 선택을 받는다")

    print()
    print("=== (F) 설정 '읽기 음성' ===")
    from viewer.widgets.settings_dialog import SettingsDialog, PAGES
    chk(any(p[0] == "voice" for p in PAGES), "(F) 환경설정에 '읽기 음성' 쪽")
    dlg = SettingsDialog({"tts_voice": {"engine": "sapi", "sid": 4, "quality": "high"}})
    chk(dlg.cmb_tts_engine.currentData() == "sapi" and dlg.cmb_tts_voice.currentData() == 4
        and dlg.cmb_tts_quality.currentData() == "high", "(F) 저장된 값으로 열린다")
    chk(dlg.cmb_tts_voice.itemText(0) == "목소리 1" and dlg.cmb_tts_voice.count() == 10,
        "(F) 목소리 이름은 중립 '목소리 1~10'", dlg.cmb_tts_voice.itemText(0))
    dlg.cmb_tts_engine.setCurrentIndex(dlg.cmb_tts_engine.findData("neural"))
    dlg.cmb_tts_voice.setCurrentIndex(7)
    rp = dlg.result_prefs()
    chk(rp.get("tts_voice") == {"engine": "neural", "sid": 7, "quality": "high", "normalize": True, "split_lang": True},
        "(F) 고친 값이 결과로", str(rp.get("tts_voice")))
    dlg.chk_tts_normalize.setChecked(False)
    chk(dlg.result_prefs()["tts_voice"]["normalize"] is False, "(F) '숫자·단위 풀어 읽기' 끄기가 결과로")
    dlg.cmb_tts_engine.setCurrentIndex(dlg.cmb_tts_engine.findData("sapi"))
    chk(not dlg.chk_tts_split.isEnabled(), "(F) Windows 기본 음성이면 자연 음성 칸은 끈다")
    dlg.close()
    from viewer import app as _app
    src = __import__("inspect").getsource(_app.MainWindow._apply_prefs)
    chk('"tts_voice"' in src, "(F) 허용목록(_apply_prefs)에 tts_voice — 없으면 조용히 사라진다")

    print()
    print("=== (G) 실제 합성 (모델이 있으면) ===")
    cand = [neural_tts.model_dir(),
            __import__("pathlib").Path(HERE).parent / "_review" / "tts_spike" / "models" / neural_tts.MODEL_INNER]
    md = next((c for c in cand if neural_tts.model_ready(c)), None)
    if md is None or not neural_tts.engine_importable():
        print("SKIP - (G) 자연 음성 모델·엔진 없음")
    else:
        res = {}

        def real():
            try:
                syn = neural_tts.Synth(md)
                t0 = time.perf_counter()
                pcm = syn.generate("시편 세 개를 만든다.", "ko", 0, 4, 1.0)
                res["s"] = len(pcm) / 2 / syn.sample_rate
                res["t"] = time.perf_counter() - t0
                res["sr"] = syn.sample_rate
            except Exception as e:
                res["err"] = repr(e)
        th = threading.Thread(target=real); th.start(); th.join(120)
        chk("s" in res and res["s"] > 0.5 and res.get("sr") == 44100,
            "(G) 배경 스레드에서 실제 한 문장(44.1kHz)", "%s" % res)
finally_ok = True
print()
print("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
