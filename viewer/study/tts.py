"""음성 읽어주기 (Windows SAPI). 한국어=Heami, 영어=Zira/David 자동 + 성우/빠르기 선택.
추가 의존성 없음(pywin32 의 win32com). SAPI 없으면 조용히 비활성.
"""
from __future__ import annotations

from typing import Optional

# SAPI 플래그
_ASYNC = 1          # SVSFlagsAsync — 즉시 반환(비동기)
_PURGE = 2          # SVSFPurgeBeforeSpeak — 이전 발화 중단
_IS_SPEAKING = 2    # SpeechRunState.SRSEIsSpeaking


class TTS:
    def __init__(self):
        self._voice = None
        self._tok = {"kor": None, "eng": None}
        self._by_name = {}        # 성우 이름 -> token
        self._ok = None
        self._forced = None       # 사용자가 고른 성우 토큰(있으면 우선)
        self._forced_name = None  # 260618-25: 고른 성우 '이름'(재초기화 후 토큰 재해석용)
        # 260618-7: 비동기 발화 시작 레이스 보정용 — 발화 직후 RunningState 가 잠시
        #   Done(1) 로 보여 자동읽기 폴링이 첫 단어를 건너뛰던(무음) 문제 방지.
        self._spk_t0 = 0.0        # 마지막 speak 시각
        self._spk_issued = False  # speak 후 아직 완료 확인 전
        self._spk_seen = False    # 이번 발화에서 RunningState==speaking 을 본 적 있는지

    def available(self) -> bool:
        self._ensure()
        return bool(self._ok)

    def _ensure(self) -> None:
        if self._ok is not None:
            return
        try:
            import win32com.client
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
            for tok in self._voice.GetVoices():
                lang = (tok.GetAttribute("Language") or "").lower()
                name = (tok.GetAttribute("Name") or "")
                self._by_name[name] = tok
                if "412" in lang and self._tok["kor"] is None:   # 412 = Korean
                    self._tok["kor"] = tok
                elif "409" in lang and self._tok["eng"] is None:  # 409 = English(US)
                    self._tok["eng"] = tok
            self._ok = True
        except Exception:
            self._ok = False
            self._voice = None

    def voice_names(self) -> list[str]:
        self._ensure()
        return list(self._by_name.keys())

    def set_voice_name(self, name: Optional[str]) -> None:
        """성우 고정(None 이면 언어 자동)."""
        self._ensure()
        self._forced_name = name or None
        self._forced = self._by_name.get(name) if name else None

    def _reinit(self) -> bool:
        """260618-25: 캐시된 SpVoice 가 일부 환경에서 깨져 무음이 될 때 1회 재초기화.
        성우 토큰은 새로 열거되므로, 고른 성우는 '이름' 으로 다시 해석한다."""
        self._ok = None
        self._voice = None
        self._tok = {"kor": None, "eng": None}
        self._by_name = {}
        self._forced = None
        self._ensure()
        if self._ok and self._forced_name:
            self._forced = self._by_name.get(self._forced_name)
        return bool(self._ok and self._voice is not None)

    def set_rate(self, rate: int) -> None:
        """빠르기 -10(느림)~10(빠름)."""
        self._ensure()
        if self._voice is not None:
            try:
                self._voice.Rate = max(-10, min(10, int(rate)))
            except Exception:
                pass

    def is_speaking(self) -> bool:
        if not self._ok or self._voice is None:
            return False
        try:
            running = (self._voice.Status.RunningState == _IS_SPEAKING)
        except Exception:
            running = False
        if running:
            self._spk_seen = True
            return True
        # 260618-7: 발화 직후 SAPI 가 아직 RunningState==speaking 으로 전환되기 전
        #   (비동기 시작 레이스)에는 '말하는 중'으로 간주해 폴링 루프가 첫 발화를
        #   퍼지·건너뛰지 않게 한다. 한 번이라도 speaking 을 본 뒤 Done 이면 진짜 종료.
        if self._spk_issued and not self._spk_seen:
            import time as _t
            if (_t.time() - self._spk_t0) < 0.6:
                return True
            self._spk_issued = False     # 유예 경과 — 시작 실패로 보고 진행
        return False

    def word_span(self):
        """현재 읽는 단어의 (입력텍스트내 문자위치, 길이). 없으면 None. (카라오케 표시용)"""
        if not self._ok or self._voice is None:
            return None
        try:
            st = self._voice.Status
            return (int(st.InputWordPosition), int(st.InputWordLength))
        except Exception:
            return None

    def _select(self, lang: str):
        if self._forced is not None:
            return self._forced
        key = "kor" if (lang or "").startswith("ko") else "eng"
        return self._tok.get(key) or self._tok.get("eng") or self._tok.get("kor")

    def speak(self, text: str, lang: str = "eng", *, queue: bool = False) -> bool:
        """text 를 읽음. queue=False 면 이전 발화 중단 후 즉시, True 면 이어서 대기열."""
        if not text or not text.strip():
            return False
        self._ensure()
        if not self._ok or self._voice is None:
            return False
        flags = _ASYNC if queue else (_ASYNC | _PURGE)

        def _do() -> bool:
            tok = self._select(lang)
            if tok is not None:
                # 260618-25: 성우 설정은 별도 try — 일부 환경에서 COM 토큰 비교/설정이
                #   예외를 던져도 '발화 자체'는 막지 않도록(무음 방지).
                try:
                    if self._voice.Voice != tok:
                        self._voice.Voice = tok
                except Exception:
                    try:
                        self._voice.Voice = tok
                    except Exception:
                        pass
            self._voice.Speak(text, flags)
            import time as _t
            self._spk_t0 = _t.time()
            self._spk_issued = True
            if not queue:
                self._spk_seen = False
            return True

        try:
            return _do()
        except Exception:
            # 260618-25: 캐시된 음성 객체가 깨진 경우 1회 재초기화 후 재시도(무음 복구)
            try:
                if self._reinit():
                    return _do()
            except Exception:
                pass
            return False

    def stop(self) -> None:
        self._spk_issued = False
        self._spk_seen = False
        if self._voice is not None:
            try:
                self._voice.Speak("", _ASYNC | _PURGE)
            except Exception:
                pass


_GLOBAL: Optional[TTS] = None


def get_tts() -> TTS:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = TTS()
    return _GLOBAL
