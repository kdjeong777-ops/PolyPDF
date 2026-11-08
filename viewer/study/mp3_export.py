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


def _voice_tokens(voice):
    """언어별 기본 음성 — 화면 읽기와 같은 목록(클래식 + OneCore, `tts.enumerate_voices`)."""
    import win32com.client
    from viewer.study.tts import enumerate_voices
    return enumerate_voices(voice, win32com.client)[1]


def _find_voice(voice, name):
    """고른 성우 이름 → 토큰(없거나 이름이 비면 None). 화면 읽기 성우 목록과 같은 이름들이다."""
    if not name:
        return None
    import win32com.client
    from viewer.study.tts import enumerate_voices
    return enumerate_voices(voice, win32com.client)[0].get(name)


def _silence(ms: int) -> bytes:
    """쉼 — 0 으로 채운 PCM(22kHz 16bit mono)."""
    n = int(_SR * max(0, int(ms)) / 1000) * _CH * _SW
    return bytes(n)


def _fmt_ts(sec: float) -> str:
    m = int(sec // 60)
    return f"[{m:02d}:{sec - m * 60:05.2f}]"


def _segments_pcm(voice, tok, forced, segments):
    """세그먼트들을 인메모리 합성 → (PCM bytes, lrc 라인 목록)."""
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
    return bytes(pcm), lrc


def _make_voice(rate: int):
    import win32com.client
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    try:
        voice.Rate = max(-10, min(10, int(rate)))
    except Exception:
        pass
    return voice, _voice_tokens(voice)


def synth_to_mp3(segments, mp3_path, *, rate: int = 0, voice_name: str = None,
                 lrc_path=None, bitrate: int = 96,
                 voice=None, tok=None, forced=None) -> Path:
    """segments → mp3(+lrc). voice/tok/forced 를 넘기면 재사용(반복 호출 빠름)."""
    import lameenc
    mp3_path = Path(mp3_path)
    segments = [(t, l) for (t, l) in segments if t and str(t).strip()]
    if not segments:
        raise RuntimeError("저장할 내용이 없습니다.")
    if voice is None:
        voice, tok = _make_voice(rate)
        forced = _find_voice(voice, voice_name)

    pcm, lrc = _segments_pcm(voice, tok, forced, segments)
    enc = lameenc.Encoder()
    enc.set_channels(_CH); enc.set_in_sample_rate(_SR)
    enc.set_bit_rate(bitrate); enc.set_quality(2)
    mp3_path.write_bytes(enc.encode(pcm) + enc.flush())
    if lrc_path:
        Path(lrc_path).write_text("\n".join(lrc), encoding="utf-8")
    return mp3_path
