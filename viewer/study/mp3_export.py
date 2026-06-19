"""재생내용을 mp3 로 저장 — Windows SAPI(SpMemoryStream, 인메모리) → lameenc.
디스크 임시파일 없이 합성(40x 빠름)·세그먼트별 정확한 길이로 가사(.lrc). segments=[(text,lang)]."""
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
    tok = {"kor": None, "eng": None}
    for t in voice.GetVoices():
        lang = (t.GetAttribute("Language") or "").lower()
        if "412" in lang and tok["kor"] is None:
            tok["kor"] = t
        elif "409" in lang and tok["eng"] is None:
            tok["eng"] = t
    return tok


def _fmt_ts(sec: float) -> str:
    m = int(sec // 60)
    return f"[{m:02d}:{sec - m * 60:05.2f}]"


def _segments_pcm(voice, tok, forced, segments):
    """세그먼트들을 인메모리 합성 → (PCM bytes, lrc 라인 목록)."""
    import win32com.client
    pcm = bytearray()
    lrc = []
    t_acc = 0.0
    for text, lang in segments:
        ms = win32com.client.Dispatch("SAPI.SpMemoryStream")
        ms.Format.Type = _SAFT_22k16bitMono
        voice.AudioOutputStream = ms
        tk = forced or (tok["kor"] if (lang or "").startswith("ko") else tok["eng"]) \
            or tok["eng"] or tok["kor"]
        if tk is not None:
            voice.Voice = tk
        voice.Speak(text, 0)
        voice.AudioOutputStream = None
        seg = bytes(bytearray(ms.GetData()))
        pcm += seg
        lrc.append(_fmt_ts(t_acc) + text)
        t_acc += len(seg) / float(_SR * _CH * _SW)
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
        import win32com.client
        by = {t.GetAttribute("Name"): t for t in voice.GetVoices()}
        forced = by.get(voice_name) if voice_name else None

    pcm, lrc = _segments_pcm(voice, tok, forced, segments)
    enc = lameenc.Encoder()
    enc.set_channels(_CH); enc.set_in_sample_rate(_SR)
    enc.set_bit_rate(bitrate); enc.set_quality(2)
    mp3_path.write_bytes(enc.encode(pcm) + enc.flush())
    if lrc_path:
        Path(lrc_path).write_text("\n".join(lrc), encoding="utf-8")
    return mp3_path
