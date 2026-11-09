"""재생내용을 mp3 로 저장 — Windows SAPI(SpMemoryStream, 인메모리) → lameenc.
디스크 임시파일 없이 합성(40x 빠름)·세그먼트별 정확한 길이로 가사(.lrc). segments=[(text,lang)].

261108-25(영상·음성 SOT §1.8): 화면 읽기와 **같은 규칙** — 음성 목록은 `tts.enumerate_voices`(OneCore 포함),
읽는 글은 `tts_text.reading_pieces`(숫자·단위 풀기·한영 조각), 문장 사이 쉼 `SENT_PAUSE_MS`.
가사(.lrc)는 표시 글 그대로 남긴다."""
from __future__ import annotations

from pathlib import Path

_SAFT_22k16bitMono = 22
_SR, _CH, _SW = 22050, 1, 2     # 22kHz 16bit mono


def unique_dir(base: Path) -> Path:
    base = Path(base)
    if not base.exists():
        return base
    i = 1
    while True:
        cand = base.with_name(f"{base.name}({i})")
        if not cand.exists():
            return cand
        i += 1


def _voice_tokens(voice, hidden=()):
    """언어별 기본 음성 — 화면 읽기와 같은 목록(클래식 + OneCore, `tts.enumerate_voices`)."""
    import win32com.client
    from viewer.study.tts import enumerate_voices
    return enumerate_voices(voice, win32com.client, hidden)[1]     # 261108-33: '쓰지 않음' 성우는 건너뛴다


def _find_voice(voice, name):
    """고른 성우 이름 → 토큰(없거나 이름이 비면 None). 화면 읽기 성우 목록과 같은 이름들이다."""
    if not name:
        return None
    import win32com.client
    from viewer.study.tts import enumerate_voices
    return enumerate_voices(voice, win32com.client)[0].get(name)


def _silence(ms: int, sr: int = 0) -> bytes:
    """쉼 — 0 으로 채운 PCM(16bit mono, 기본 22kHz)."""
    n = int((sr or _SR) * max(0, int(ms)) / 1000) * _CH * _SW
    return bytes(n)


def _fmt_ts(sec: float) -> str:
    m = int(sec // 60)
    return f"[{m:02d}:{sec - m * 60:05.2f}]"


class Mp3Cancelled(Exception):
    """261109-5: 문장 사이에서 [중단] — 만들던 구간은 버린다(파일을 남기지 않는다)."""


def _segments_pcm(voice, tok, forced, segments, on_seg=None):
    """세그먼트들을 인메모리 합성 → (PCM bytes, lrc 라인 목록). `on_seg(끝낸 문장 수)` — 중단이면 `Mp3Cancelled`."""
    import win32com.client
    pcm = bytearray()
    lrc = []
    t_acc = 0.0
    from viewer.study import tts_text
    bps = float(_SR * _CH * _SW)
    for i, (text, lang) in enumerate(segments):
        if forced is not None:              # 성우 고정 — 조각을 나누지 않는다(화면 읽기와 같다)
            lg = tts_text.base_lang(text)
            pieces = [(tts_text.normalize(text, lg), lg)]
        else:
            pieces = tts_text.reading_pieces(text)
        seg = bytearray()
        lead = _silence(tts_text.SENT_PAUSE_MS) if i > 0 else b""
        seg += lead
        for sp, lg in pieces:
            if not sp.text.strip():
                continue
            ms = win32com.client.Dispatch("SAPI.SpMemoryStream")
            ms.Format.Type = _SAFT_22k16bitMono
            voice.AudioOutputStream = ms
            tk = forced or (tok["kor"] if lg == "ko" else tok["eng"]) \
                or tok["eng"] or tok["kor"]
            if tk is not None:
                voice.Voice = tk
            voice.Speak(sp.text, 0)
            voice.AudioOutputStream = None
            seg += bytes(bytearray(ms.GetData()))
        pcm += seg
        # 가사는 표시 글 그대로, 시각은 쉼 뒤(그 문장 소리가 시작하는 때)
        lrc.append(_fmt_ts(t_acc + len(lead) / bps) + text)
        t_acc += len(seg) / bps
        if on_seg is not None:
            on_seg(i + 1)
    return bytes(pcm), lrc


def _neural_segments_pcm(neural, segments, *, sid=0, steps=4, speed=1.0, normalize=None, split_lang=None,
                         on_seg=None):
    """261108-28(SOT §1.10): 자연 음성 — 배경 스레드의 `neural_tts.Synth` 로 44.1kHz int16 PCM + 가사."""
    from viewer.study import tts_text, neural_tts
    sr = int(getattr(neural, "sample_rate", neural_tts.SAMPLE_RATE) or neural_tts.SAMPLE_RATE)
    bps = float(sr * _CH * _SW)
    pcm, lrc, t_acc = bytearray(), [], 0.0
    for i, (text, _lang) in enumerate(segments):
        lead = _silence(tts_text.SENT_PAUSE_MS, sr) if i > 0 else b""
        seg = bytearray(lead)
        for t, lg in neural_tts.pieces_for(text, normalize, split_lang):
            seg += neural.generate(t, lg, sid, steps, speed)
        pcm += seg
        lrc.append(_fmt_ts(t_acc + len(lead) / bps) + text)
        t_acc += len(seg) / bps
        if on_seg is not None:
            on_seg(i + 1)
    return bytes(pcm), lrc, sr


def id3_comment(text: str) -> bytes:
    """ID3v2.3 꼬리표 하나(COMM, UTF-16) — mp3 앞에 붙인다. '생성 음성' 표기(SOT §1.10, 모델 라이선스 고지)."""
    import struct
    body = b"\x01" + b"kor" + b"\xff\xfe\x00\x00" + b"\xff\xfe" + text.encode("utf-16-le")
    frame = b"COMM" + struct.pack(">I", len(body)) + b"\x00\x00" + body
    size = len(frame)
    syn = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])
    return b"ID3\x03\x00\x00" + syn + frame


GENERATED_NOTE = "생성 음성(AI 합성): Supertonic 3 — OpenRAIL-M"


def _make_voice(rate: int, hidden=()):
    import win32com.client
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    try:
        voice.Rate = max(-10, min(10, int(rate)))
    except Exception:
        pass
    return voice, _voice_tokens(voice, hidden)


def synth_to_mp3(segments, mp3_path, *, rate: int = 0, voice_name: str = None,
                 lrc_path=None, bitrate: int = 96,
                 voice=None, tok=None, forced=None, neural=None, neural_opts=None, on_seg=None) -> Path:
    """segments → mp3(+lrc). voice/tok/forced 를 넘기면 재사용(반복 호출 빠름).
    261109-5: `on_seg(끝낸 문장 수)` — 문장마다 진행·중단(`Mp3Cancelled` 를 던지면 이 파일은 만들지 않는다).
    261108-28: neural(배경 스레드의 `neural_tts.Synth`)을 넘기면 자연 음성 — 44.1kHz, ID3 에 '생성 음성' 표기."""
    import lameenc
    mp3_path = Path(mp3_path)
    segments = [(t, l) for (t, l) in segments if t and str(t).strip()]
    if not segments:
        raise RuntimeError("저장할 내용이 없습니다.")
    tag = b""
    if neural is not None:
        o = dict(neural_opts or {})
        pcm, lrc, sr = _neural_segments_pcm(neural, segments, sid=o.get("sid", 0),
                                            steps=o.get("steps", 4), speed=o.get("speed", 1.0),
                                            normalize=o.get("normalize"), split_lang=o.get("split_lang"),
                                            on_seg=on_seg)
        tag = id3_comment(GENERATED_NOTE + ((" — " + o["voice_label"]) if o.get("voice_label") else ""))   # 261108-33: 목소리 이름
    else:
        if voice is None:
            voice, tok = _make_voice(rate)
            forced = _find_voice(voice, voice_name)
        pcm, lrc = _segments_pcm(voice, tok, forced, segments, on_seg=on_seg)
        sr = _SR
    enc = lameenc.Encoder()
    enc.set_channels(_CH); enc.set_in_sample_rate(sr)
    enc.set_bit_rate(bitrate); enc.set_quality(2)
    # 261109-5: 임시 이름으로 다 쓴 뒤 바꿔 끼운다 — 끊긴 파일이 '이어서 저장' 에서 다 된 것으로 보이지 않게(배경 스레드)
    import os
    part = mp3_path.with_name(mp3_path.name + ".part")
    part.write_bytes(tag + enc.encode(pcm) + enc.flush())
    os.replace(part, mp3_path)
    if lrc_path:
        Path(lrc_path).write_text("\n".join(lrc), encoding="utf-8")
    if not (mp3_path.exists() and mp3_path.stat().st_size > 0):
        raise RuntimeError("mp3 파일이 만들어지지 않았습니다: %s" % mp3_path)
    return mp3_path
