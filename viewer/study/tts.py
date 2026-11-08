"""음성 읽어주기 (Windows SAPI). 한국어=Heami, 영어=Zira/David 자동 + 성우/빠르기 선택.
추가 의존성 없음(pywin32 의 win32com). SAPI 없으면 조용히 비활성.
"""
from __future__ import annotations

from typing import Optional

# SAPI 플래그
_ASYNC = 1          # SVSFlagsAsync — 즉시 반환(비동기)
_PURGE = 2          # SVSFPurgeBeforeSpeak — 이전 발화 중단
_IS_SPEAKING = 2    # SpeechRunState.SRSEIsSpeaking


def enumerate_voices(voice, wc):
    """음성 목록 한 길 (영상·음성 SOT §1.1·§1.8 의 4, 261108-25) — 화면 읽기·mp3 저장이 함께 쓴다.

    ① 클래식 SAPI5(`GetVoices`) ② OneCore(레지스트리 토큰). 표시명에서 ' Desktop' 을 뺀 기준명으로
    겹침을 없앤다(클래식 우선). 돌려줌: (이름→토큰, {'kor': 토큰, 'eng': 토큰}).
    종전 mp3 저장은 ① 만 보아, 화면 읽기에서 고른 OneCore 음성(예: Mark)이 mp3 에서는 무시됐다.
    """
    by_name, tok, seen = {}, {"kor": None, "eng": None}, set()

    def _add(t):
        try:
            name = (t.GetAttribute("Name") or "")
        except Exception:
            return
        if not name:
            return
        base = name.replace(" Desktop", "").strip().lower()
        if base in seen:
            return
        seen.add(base)
        by_name[name] = t
        try:
            lang = (t.GetAttribute("Language") or "").lower()
        except Exception:
            lang = ""
        if "412" in lang and tok["kor"] is None:   # 412 = Korean
            tok["kor"] = t
        elif "409" in lang and tok["eng"] is None:  # 409 = English(US)
            tok["eng"] = t

    for t in voice.GetVoices():
        _add(t)
    TTS._add_onecore_voices(wc, _add)
    return by_name, tok


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
        # 261108-25(SOT §1.8 의 5): 읽는 글 ↔ 표시 글 위치 맵 — SAPI 흐름 번호(Speak 가 돌려줌)마다
        self._maps = {}           # stream_no -> tts_text.SpokenText
        self._multi = False       # 이번 문장을 여러 조각으로 넘겼는지(조각 사이 상태 보강용)
        self._last_stream = 0     # 마지막 Speak 의 흐름 번호

    def available(self) -> bool:
        self._ensure()
        return bool(self._ok)

    def _ensure(self) -> None:
        if self._ok is not None:
            return
        try:
            import win32com.client
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
            # 1) 클래식 SAPI5 음성 2) 260618-31: OneCore(최신·추가 설치) 음성 — 클래식 GetVoices 에는
            #    안 나오는 음성(예: Mark, Windows '음성' 설정에서 추가한 언어 음성). 한 길: enumerate_voices.
            self._by_name, self._tok = enumerate_voices(self._voice, win32com.client)
            self._ok = True
        except Exception:
            self._ok = False
            self._voice = None

    @staticmethod
    def _add_onecore_voices(wc, add) -> None:
        """260618-31: HKLM\\...\\Speech_OneCore\\Voices\\Tokens 의 음성을 SpObjectToken 으로
        만들어 add(tok). SAPI 호환(MSTTS) 음성이면 voice.Voice 로 사용 가능."""
        try:
            import winreg
        except Exception:
            return
        base = r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                        i += 1
                    except OSError:
                        break
                    try:
                        tok = wc.Dispatch("SAPI.SpObjectToken")
                        tok.SetId(r"HKEY_LOCAL_MACHINE\%s\%s" % (base, sub))
                        add(tok)
                    except Exception:
                        continue
        except Exception:
            pass

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
        # 261108-25: 한 문장을 한·영 조각 여럿으로 넘기면 조각 사이에 잠깐 'Done' 으로 보일 수 있다 —
        #   대기열이 다 끝났는지(WaitUntilDone(0) = 기다리지 않고 묻기)로 한 번 더 본다.
        if self._multi and self._spk_seen:
            try:
                if not self._voice.WaitUntilDone(0):
                    return True
            except Exception:
                pass
        # 260618-7: 발화 직후 SAPI 가 아직 RunningState==speaking 으로 전환되기 전
        #   (비동기 시작 레이스)에는 '말하는 중'으로 간주해 폴링 루프가 첫 발화를
        #   퍼지·건너뛰지 않게 한다. 한 번이라도 speaking 을 본 뒤 Done 이면 진짜 종료.
        # 260618-26: 일부 환경(특정 SAPI/EXE)에서 RunningState 가 speaking 으로 전혀
        #   바뀌지 않아 0.6s 유예 후 곧바로 다음 문장을 PURGE → 들리기도 전에 끊겨
        #   '무음'처럼 되는 문제 → 유예를 1.5s 로 늘림. (정상 환경은 speaking 을 보는
        #   즉시 _spk_seen 으로 전환되므로 영향 없음.)
        if self._spk_issued and not self._spk_seen:
            import time as _t
            if (_t.time() - self._spk_t0) < 1.5:
                return True
            self._spk_issued = False     # 유예 경과 — 시작 실패로 보고 진행
        return False

    def saw_speaking(self) -> bool:
        """260618-26: 이번 발화에서 RunningState==speaking 을 실제로 관측했는지.
        False 면 엔진의 발화상태 보고를 신뢰할 수 없으므로(읽기 루프가) 추정 발화시간을
        대신 사용한다."""
        return bool(self._spk_seen)

    def word_span(self):
        """현재 읽는 단어의 (입력텍스트내 문자위치, 길이). 없으면 None. (카라오케 표시용)"""
        if not self._ok or self._voice is None:
            return None
        try:
            st = self._voice.Status
            pos, ln = int(st.InputWordPosition), int(st.InputWordLength)
            sno = int(st.CurrentStreamNumber)
        except Exception:
            return None
        # 261108-25(SOT §1.8 의 5): speak_reading 으로 넘긴 글은 읽는 글 기준 위치 → 표시 글 위치로
        sp = self._maps.get(sno)
        if sp is not None:
            return sp.to_display(pos, ln)
        return (pos, ln)

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
            self._last_stream = self._voice.Speak(text, flags)
            import time as _t
            self._spk_t0 = _t.time()
            self._spk_issued = True
            if not queue:
                self._spk_seen = False
                self._maps = {}
                self._multi = False
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

    def speak_reading(self, text: str) -> bool:
        """본문 읽기·mp3 와 같은 규칙으로 문장 하나를 읽는다 (영상·음성 SOT §1.8, 261108-25).

        표시 글은 그대로 두고 `tts_text.reading_pieces` 가 만든 **읽는 글**(숫자·단위 풀기)을
        한·영 조각마다 그 언어 음성으로 차례로 넘긴다. 성우를 고정했으면 조각을 나누지 않는다
        (한 음성이 다 읽으니 나눌 까닭이 없다). `word_span` 은 표시 글 위치를 돌려준다.
        """
        from viewer.study import tts_text
        if not text or not text.strip():
            return False
        self._ensure()
        if self._forced is not None:
            lg = tts_text.base_lang(text)
            pieces = [(tts_text.normalize(text, lg), lg)]
        else:
            pieces = tts_text.reading_pieces(text)
        pieces = [(sp, lg) for sp, lg in pieces if sp.text.strip()]
        if not pieces:
            return False
        ok_any = False
        for i, (sp, lg) in enumerate(pieces):
            ok = self.speak(sp.text, "kor" if lg == "ko" else "eng", queue=(i > 0))
            if not ok:
                return ok_any
            ok_any = True
            try:
                self._maps[int(self._last_stream)] = sp
            except Exception:
                pass
        self._multi = len(pieces) > 1
        return ok_any

    def stop(self) -> None:
        self._maps = {}
        self._multi = False
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
