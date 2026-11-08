"""자연 음성(신경망 TTS) — Supertonic 3 int8 + sherpa-onnx (영상·음성 SOT §1.10, 261108-28).

- 모델은 선택 구성요소('자연 음성(한국어·영어)', `components.install_voice`)로 **설치 폴더\\voices\\** 에 받는다 — 설치본에는 없다.
- 엔진(sherpa_onnx·onnxruntime.dll)은 앱 묶음에 든다. 없거나 모델이 없거나 실패하면 부르는 쪽이 SAPI 로 물러선다(`tts_engine`).
- ★ 모델 싣기·합성은 **배경 스레드에서만**(응답성 SOT §4.8). `Synth` 는 메인 스레드에서 부르면 예외를 던진다.
  화면 읽기는 `NeuralReader`(메인) → `_SynthWorker`(전용 QThread) → 결과 PCM 을 메인의 `_PcmPlayer`(QAudioSink) 에 넣는다.
- 첫 소리: 읽기를 시작할 때 모델을 배경에서 싣고(`warm_up`), 첫 문장이 길면 쉼표에서 잘라 앞 조각을 먼저, 다음 문장들은
  미리 합성(`prefetch`). 칠하기는 문장 단위(엔진이 낱말 시각을 주지 않는다) — `word_span` 은 글자 비례 추정.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

# ── 모델 묶음(고정) — 바꾸면 SOT §1.10 표·릴리스 SOT §8 A5 도 함께 ──
MODEL_ARCHIVE = "sherpa-onnx-supertonic-3-tts-int8-2026-05-11.tar.bz2"
# 받는 곳: 우리 공개 저장소의 고정 태그 `components` 릴리스 사본(261108-28 덧붙임 2, 사용자 결정 '우리 릴리스에 사본').
#   원본 출처는 k2-fsa/sherpa-onnx 릴리스 tts-models(상류 보관 상태) — 같은 바이트(해시 같음). 앱은 먼저 components 태그에서
#   이름으로 찾고(`components._assets`, 다른 구성요소와 같은 길), 못 찾으면 아래 고정 주소로.
COMPONENTS_BASE = "https://github.com/kdjeong777-ops/PolyPDF/releases/download/components/"
MODEL_URL = COMPONENTS_BASE + MODEL_ARCHIVE
MODEL_SOURCE_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/" + MODEL_ARCHIVE)
# 모델 라이선스 원문(BigScience Open RAIL-M, HF Supertone/supertonic-3 의 LICENSE) — 모델 폴더에 함께 둔다(사본 동봉 의무)
LICENSE_ASSET = "Supertonic-3-LICENSE.txt"
LICENSE_URL = COMPONENTS_BASE + LICENSE_ASSET
LICENSE_SHA256 = "0d944a9110fed9a9602d60e0423a272903e7bd21ab060490774efc77c2275e9f"
LICENSE_LOCAL = "LICENSE-model-OpenRAIL-M.txt"
MODEL_SHA256 = "82fa96f91c4ef8abaae3a14a3f4153facf88bed821d1f7331cec2700f432c427"
MODEL_BYTES = 128774318
MODEL_INNER = "sherpa-onnx-supertonic-3-tts-int8-2026-05-11"     # 묶음 안 폴더 이름
MODEL_DIRNAME = "supertonic-3-int8"                              # 설치 폴더\voices\ 아래 이름
MODEL_FILES = ("duration_predictor.int8.onnx", "text_encoder.int8.onnx", "vector_estimator.int8.onnx",
               "vocoder.int8.onnx", "tts.json", "unicode_indexer.bin", "voice.bin")
ENGINE_NAME = "Supertonic 3 (int8, sherpa-onnx 2.0.1)"

# ── 합성 설정 — 실측(_review\tts_spike\결과.md §2): threads 4 는 이득 없음, steps 4 = RTF 0.15 ──
THREADS = 2
STEPS = {"fast": 4, "high": 8}       # 설정 '음질' — 빠름(기본) / 고음질
SPEAKERS = 10                        # sid 0~9 — 화면 이름은 '목소리 1~10'(중립)
SAMPLE_RATE = 44100
FIRST_PIECE_MAX_CHARS = 30           # 첫 문장이 이보다 길면 쉼표에서 잘라 앞 조각을 먼저(첫 소리 < 1.5초, 실측 §3)
PREFETCH = 2                         # 다음 문장 몇 개를 미리 합성하나
CACHE_MAX = 8                        # 만든 소리를 몇 문장까지 들고 있나
IDLE_UNLOAD_S = 300                  # 이만큼 안 쓰면 모델을 놓는다(상주 약 +190MB, 실측 §5-6)
# 앞단: Supertonic 에 정규화한 글을 줄지 — 단위 약어(kN·MPa·㎡)·셈 단위 고유어는 규칙이 확실하다(SOT §1.10 표 '앞단')
NEURAL_NORMALIZE = True
NEURAL_SPLIT_LANG = True             # 한국어 문장 속 긴 영어 구절은 lang='en' 조각으로(같은 화자라 목소리는 안 바뀐다)


def voices_dir() -> Path:
    from viewer.updater import install_dir
    return install_dir() / "voices"


def model_dir() -> Path:
    return voices_dir() / MODEL_DIRNAME


def model_ready(d: Path | None = None) -> bool:
    d = Path(d) if d is not None else model_dir()
    try:
        return all((d / n).is_file() for n in MODEL_FILES)
    except OSError:
        return False


def engine_importable() -> bool:
    """sherpa_onnx 가 있는가 — 싣지 않고 찾기만(빠르다)."""
    import importlib.util
    try:
        return importlib.util.find_spec("sherpa_onnx") is not None
    except Exception:
        return False


def rate_to_speed(rate: int) -> float:
    """SAPI 빠르기(-10~10) → Supertonic speed(0.6~1.6)."""
    try:
        r = max(-10, min(10, int(rate)))
    except (TypeError, ValueError):
        r = 0
    return round(max(0.6, min(1.6, 1.0 + r * 0.06)), 2)


def _on_main_thread() -> bool:
    try:
        from PyQt6.QtCore import QCoreApplication, QThread
        app = QCoreApplication.instance()
        return app is not None and QThread.currentThread() is app.thread()
    except Exception:
        return False


class Synth:
    """모델 하나 — **배경 스레드에서만** 싣고 합성한다. 결과는 int16 PCM 바이트(44.1kHz mono)."""

    calls = []          # 검사용: (무엇, 메인 스레드였나)

    def __init__(self, mdir: Path | None = None, threads: int = THREADS):
        self.mdir = Path(mdir) if mdir is not None else model_dir()
        self.threads = int(threads)
        self._tts = None
        self.sample_rate = SAMPLE_RATE
        self.last_used = 0.0

    def _guard(self, what: str):
        main = _on_main_thread()
        Synth.calls.append((what, main))
        if main:
            raise RuntimeError("neural TTS %s on the main thread (응답성 SOT §4.8)" % what)

    def loaded(self) -> bool:
        return self._tts is not None

    def load(self):
        self._guard("load")
        if self._tts is not None:
            return
        import sherpa_onnx as so
        j = lambda n: str(self.mdir / n)
        cfg = so.OfflineTtsConfig(model=so.OfflineTtsModelConfig(
            supertonic=so.OfflineTtsSupertonicModelConfig(
                duration_predictor=j("duration_predictor.int8.onnx"), text_encoder=j("text_encoder.int8.onnx"),
                vector_estimator=j("vector_estimator.int8.onnx"), vocoder=j("vocoder.int8.onnx"),
                tts_json=j("tts.json"), unicode_indexer=j("unicode_indexer.bin"), voice_style=j("voice.bin")),
            num_threads=self.threads, provider="cpu", debug=False))
        if not cfg.validate():
            raise RuntimeError("supertonic config invalid: %s" % self.mdir)
        self._tts = so.OfflineTts(cfg)
        self.sample_rate = int(getattr(self._tts, "sample_rate", SAMPLE_RATE) or SAMPLE_RATE)
        self.last_used = time.time()

    def unload(self):
        self._tts = None

    def generate(self, text: str, lang: str = "ko", sid: int = 0, steps: int = 4, speed: float = 1.0) -> bytes:
        self._guard("generate")
        self.load()
        import numpy as np
        import sherpa_onnx as so
        g = so.GenerationConfig()
        g.sid = max(0, min(SPEAKERS - 1, int(sid)))
        g.num_steps = int(steps)
        g.speed = float(speed)
        g.extra["lang"] = "ko" if str(lang).startswith("ko") else "en"
        a = self._tts.generate(text, g)
        x = np.asarray(a.samples, dtype=np.float32)
        self.last_used = time.time()
        return float_to_int16(x)


def float_to_int16(x) -> bytes:
    """float PCM(-1~1) → int16 little-endian 바이트(mp3·재생 공용)."""
    import numpy as np
    x = np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0)
    return (x * 32767.0).astype("<i2").tobytes()


# ── 앞단 ──────────────────────────────────────────────────────────

def pieces_for(text: str, normalize: bool | None = None, split_lang: bool | None = None) -> list:
    """자연 음성에 넘길 조각 [(글, 'ko'|'en')] — 앞단 규칙. 261108-28: 설정 '숫자·단위 풀어 읽기'·'긴 영어 구절은 영어로'
    (`tts_voice.normalize`·`split_lang`)로 고른다 — None 이면 기본(NEURAL_NORMALIZE·NEURAL_SPLIT_LANG)."""
    from viewer.study import tts_text
    if not (text or "").strip():
        return []
    norm = NEURAL_NORMALIZE if normalize is None else bool(normalize)
    split = NEURAL_SPLIT_LANG if split_lang is None else bool(split_lang)
    if split:
        ps = tts_text.reading_pieces(text)
        out = [(sp.text if norm else sp.display, lg) for sp, lg in ps]
    else:
        lg = tts_text.base_lang(text)
        out = [(tts_text.normalize(text, lg).text if norm else text, lg)]
    return [(t.strip(), lg) for t, lg in out if t.strip()]


_CLAUSE = re.compile(r"[,，;:、]\s+")


def split_first(text: str, limit: int = FIRST_PIECE_MAX_CHARS) -> list:
    """첫 문장이 길면 limit 안의 마지막 쉼표(절 끝)에서 둘로 — 앞 조각이 먼저 소리 난다. 쉼표가 없으면 그대로."""
    if len(text) <= limit:
        return [text]
    cut = None
    for m in _CLAUSE.finditer(text):
        if m.start() + 1 <= limit:
            cut = m
        else:
            if cut is None and m.start() + 1 <= limit * 2:
                cut = m
            break
    if cut is None:
        return [text]
    a, b = text[:cut.start() + 1].strip(), text[cut.end():].strip()
    return [x for x in (a, b) if x]


# ── 배경 합성 일꾼 ─────────────────────────────────────────────────

def _make_worker_classes():
    from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer

    class _SynthWorker(QObject):
        """전용 QThread 안에서만 산다. request → ready(key, pcm) / failed(key, 글)."""
        ready = pyqtSignal(object, bytes)
        failed = pyqtSignal(object, str)
        loaded = pyqtSignal(bool, str)

        def __init__(self, synth_factory):
            super().__init__()
            self._factory = synth_factory
            self._synth = None
            self._idle = None
            self._drop = set()

        def _get(self):
            if self._synth is None:
                self._synth = self._factory()
            return self._synth

        def _touch(self):
            if self._idle is None:
                self._idle = QTimer(self)
                self._idle.setSingleShot(True)
                self._idle.timeout.connect(self._unload)
            self._idle.start(int(IDLE_UNLOAD_S * 1000))

        @pyqtSlot()
        def warm(self):
            try:
                self._get().load()
                self.loaded.emit(True, "")
            except Exception as e:
                self.loaded.emit(False, str(e))
            self._touch()

        @pyqtSlot(object)
        def request(self, job):
            key, text, lang, sid, steps, speed = job
            try:
                pcm = self._get().generate(text, lang, sid, steps, speed)
                self.ready.emit(key, pcm)
            except Exception as e:
                self.failed.emit(key, str(e))
            self._touch()

        @pyqtSlot()
        def _unload(self):
            if self._synth is not None:
                self._synth.unload()

    return _SynthWorker


def _make_player_class():
    from PyQt6.QtCore import QObject, QTimer, pyqtSignal

    class _PcmPlayer(QObject):
        """QAudioSink(밀어 넣기) — 메인 스레드. 바이트만 넣고 30ms 마다 장치 빈자리만큼 써 준다."""
        error = pyqtSignal(str)

        def __init__(self, parent=None, rate=SAMPLE_RATE):
            super().__init__(parent)
            self._rate = rate
            self._buf = bytearray()
            self._written = 0
            self._sink = None
            self._dev = None
            self._t = QTimer(self)
            self._t.setInterval(30)
            self._t.timeout.connect(self._pump)

        def _open(self):
            from PyQt6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
            fmt = QAudioFormat()
            fmt.setSampleRate(self._rate)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            self._sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
            self._dev = self._sink.start()
            self._written = 0

        def feed(self, pcm: bytes):
            if not pcm:
                return
            if self._sink is None:
                try:
                    self._open()
                except Exception as e:
                    self.error.emit(str(e))
                    return
            self._buf += pcm
            if not self._t.isActive():
                self._t.start()
            self._pump()

        def _pump(self):
            if self._sink is None or self._dev is None:
                return
            if self._buf:
                n = min(len(self._buf), max(0, int(self._sink.bytesFree())))
                n -= n % 2
                if n > 0:
                    w = int(self._dev.write(bytes(self._buf[:n])))
                    if w > 0:
                        del self._buf[:w]
                        self._written += w

        def played_s(self) -> float:
            if self._sink is None:
                return 0.0
            return self._sink.processedUSecs() / 1e6

        def written_s(self) -> float:
            return (self._written + len(self._buf)) / float(self._rate * 2)

        def busy(self) -> bool:
            """아직 소리가 남았나 — 넣은 것이 다 재생됐는지(장치 지연 50ms 여유)."""
            if self._sink is None:
                return False
            if self._buf:
                return True
            return self.played_s() + 0.05 < self.written_s()

        def stop(self):
            self._t.stop()
            self._buf = bytearray()
            if self._sink is not None:
                try:
                    self._sink.stop()
                except Exception:
                    pass
            self._sink = None
            self._dev = None
            self._written = 0

    return _PcmPlayer


# ── 화면 읽기용 — SAPI `TTS` 와 같은 모양 ──────────────────────────────

from PyQt6.QtCore import QObject as _QObject


class NeuralReader(_QObject):
    """`ReadAloud` 가 쓰는 SAPI 모양(available·speak_reading·is_speaking·saw_speaking·stop·set_rate·word_span) +
    `prefetch(글들)`·`warm_up()`. 메인 스레드 객체 — 합성은 `_SynthWorker`(QThread) 에, 재생은 `_PcmPlayer`."""

    def __init__(self, parent=None, *, sid: int = 0, quality: str = "fast",
                 synth_factory=None, player_factory=None):
        super().__init__(parent)          # QObject — 배경 일꾼의 신호가 메인 스레드로(대기열 연결) 오게
        self.sid = int(sid)
        self.steps = STEPS.get(quality, STEPS["fast"])
        self.normalize = NEURAL_NORMALIZE      # 설정 '숫자·단위 풀어 읽기'
        self.split_lang = NEURAL_SPLIT_LANG    # 설정 '긴 영어 구절은 영어로'
        self.speed = 1.0
        self._synth_factory = synth_factory or (lambda: Synth())
        self._player_factory = player_factory
        self._thread = None
        self._worker = None
        self._player = None
        self._cache = {}              # key -> pcm
        self._order = []
        self._pending = set()         # 요청했고 아직 안 온 key
        self._queue = []              # 지금 문장의 조각 key 들(차례)
        self._fed = 0                 # _queue 에서 플레이어에 넣은 수
        self._gen = 0
        self._first = True            # 읽기 시작 뒤 첫 문장인가(첫 조각 짧게)
        self._cur_text = ""
        self._t0 = 0.0
        self.failed_msg = ""
        self._failed = False

    # --- 상태 ---
    def available(self) -> bool:
        return engine_importable() and model_ready() and not self._failed

    def configure(self, sid: int, quality: str, normalize: bool = NEURAL_NORMALIZE, split_lang: bool = NEURAL_SPLIT_LANG):
        new = (int(sid), STEPS.get(quality, STEPS["fast"]), bool(normalize), bool(split_lang))
        if new != (self.sid, self.steps, self.normalize, self.split_lang):
            self.sid, self.steps, self.normalize, self.split_lang = new
            self._cache.clear(); self._order.clear()

    def set_rate(self, rate: int):
        sp = rate_to_speed(rate)
        if sp != self.speed:
            self.speed = sp
            self._cache.clear(); self._order.clear()

    def set_voice_name(self, name):
        pass                            # 화자는 설정 '목소리 1~10'(sid) — SAPI 성우 이름은 쓰지 않는다

    # --- 배경 일꾼 ---
    def _ensure_thread(self):
        if self._worker is not None:
            return
        from PyQt6.QtCore import QThread
        W = _make_worker_classes()
        self._thread = QThread()
        self._thread.setObjectName("polypdf-neural-tts")
        self._worker = W(self._synth_factory)
        self._worker.moveToThread(self._thread)
        try:                                   # 앱이 끝날 때 일꾼 스레드를 멈춘다(돌던 QThread 소멸 충돌 방지)
            from PyQt6.QtCore import QCoreApplication
            QCoreApplication.instance().aboutToQuit.connect(self.shutdown)
        except Exception:
            pass
        self._worker.ready.connect(self._on_ready)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def warm_up(self):
        """모델을 배경에서 미리 싣는다(읽기를 누른 때 — 앱이 켜질 때가 아니다)."""
        self._ensure_thread()
        from PyQt6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self._worker, "warm", Qt.ConnectionType.QueuedConnection)

    def _key(self, text, lang, sid=None):
        return (text, lang, self.sid if sid is None else int(sid), self.steps, self.speed)

    def _request(self, text, lang, sid=None):
        k = self._key(text, lang, sid)
        if k in self._cache or k in self._pending:
            return k
        self._ensure_thread()
        self._pending.add(k)
        from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
        QMetaObject.invokeMethod(self._worker, "request", Qt.ConnectionType.QueuedConnection,
                                 Q_ARG(object, (k, text, lang, k[2], self.steps, self.speed)))
        return k

    def _on_ready(self, key, pcm):
        self._pending.discard(key)
        self._cache[key] = pcm
        self._order.append(key)
        while len(self._order) > CACHE_MAX:
            old = self._order.pop(0)
            if old not in self._queue:
                self._cache.pop(old, None)
        self._feed()

    def _on_failed(self, key, msg):
        self._pending.discard(key)
        self.failed_msg = msg
        self._failed = True             # 이번 실행에서는 자연 음성을 끈다 — 부르는 쪽이 SAPI 로(tts_engine)
        self._queue = []
        if self._player is not None:
            self._player.stop()

    def _get_player(self):
        if self._player is None:
            if self._player_factory is not None:
                self._player = self._player_factory()
            else:
                P = _make_player_class()
                self._player = P(None, SAMPLE_RATE)
        return self._player

    def _feed(self):
        """지금 문장 조각을 차례대로 — 앞 조각이 와야 뒤 조각을 넣는다."""
        while self._fed < len(self._queue):
            k = self._queue[self._fed]
            pcm = self._cache.get(k)
            if pcm is None:
                return
            if self._fed == 0:
                self._t0 = time.time()
            self._get_player().feed(pcm)
            self._fed += 1

    # --- SAPI 모양 ---
    def speak_reading(self, text: str, sid: int | None = None) -> bool:
        """sid 를 주면 그 목소리로(환경설정 미리 듣기 — 읽기 목소리는 그대로, 261108-33)."""
        if not (text or "").strip() or not self.available():
            return False
        if self._player is not None and self._player.busy():
            self._player.stop()           # 아직 소리 나는 앞 문장을 끊는다(SAPI 의 PURGE 와 같다 — 찍은 곳부터 읽기 등)
        self._cur_text = text
        ps = pieces_for(text, self.normalize, self.split_lang)
        if self._first and ps:
            t0, lg0 = ps[0]
            ps = [(x, lg0) for x in split_first(t0)] + ps[1:]
        self._first = False
        self._queue = [self._request(t, lg, sid) for t, lg in ps]
        self._fed = 0
        self._feed()
        return bool(self._queue)

    def speak(self, text: str, lang: str = "kor", *, queue: bool = False) -> bool:
        return self.speak_reading(text)

    def prefetch(self, texts):
        """다음 문장들을 미리 합성(최대 PREFETCH 개)."""
        if not self.available():
            return
        for t in list(texts or [])[:PREFETCH]:
            for x, lg in pieces_for(t, self.normalize, self.split_lang):
                self._request(x, lg)

    def is_speaking(self) -> bool:
        if self._fed < len(self._queue):
            return True                 # 아직 합성 중(또는 앞 조각 재생 중)
        return bool(self._player is not None and self._player.busy())

    def saw_speaking(self) -> bool:
        return True

    def word_span(self):
        """칠할 자리 추정 — 문장 안 글자 비례(엔진이 낱말 시각을 주지 않는다)."""
        if not self._cur_text or self._player is None:
            return None
        tot = max(0.01, self._player.written_s())
        f = max(0.0, min(1.0, self._player.played_s() / tot))
        return (int(f * max(0, len(self._cur_text) - 1)), 1)

    def stop(self):
        """멈춤·건너뛰기 — 대기열과 재생을 버린다(만들던 합성은 끝나면 캐시에만 들어간다)."""
        self._queue = []
        self._fed = 0
        self._first = True
        self._cur_text = ""
        if self._player is not None:
            self._player.stop()

    def shutdown(self):
        self.stop()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = self._worker = None


def synth_once_in_thread(texts_langs, sid=0, steps=4, speed=1.0, mdir=None):
    """검사·mp3 용 — 지금 스레드(배경이어야 한다)에서 차례로 합성해 PCM 들을 돌려준다."""
    s = Synth(mdir)
    return [s.generate(t, lg, sid, steps, speed) for t, lg in texts_langs]

