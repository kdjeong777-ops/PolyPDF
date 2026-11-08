# -*- coding: utf-8 -*-
"""261108-25: TTS 를 실제 말소리에 가깝게 — 단기(엔진은 SAPI 그대로) (영상·음성 SOT §1.8).

사용자 지시: "tts의 음성을 좀더 실제 음성과 유사하게 향상시키는 방안을 검토해 … 개선 방안을 마련해",
"tts는 영어와 한글이 대상이야", 검토 뒤 "단기부터 진행".

  (A) 정규화 표 — 숫자·단위·셈 단위(고유어)·범위·날짜·문헌 번호·약어 (한국어·영어)
  (B) 한영 구간 — 한국어 문장 속 짧은 영어는 한국어 음성, 긴 구절만 영어 음성
  (C) 위치 맵 — 읽는 글의 낱말 위치가 표시 글의 그 낱말로 되돌아온다(칠하기가 어긋나지 않게)
  (D) TTS.speak_reading — 조각마다 그 언어 음성, word_span 은 표시 글 위치, 성우 고정이면 한 조각
  (E) mp3 — 화면 읽기와 같은 음성 목록(OneCore 포함)에서 고른 성우를 찾는다, 문장 사이 쉼, 가사는 표시 글
  (F) 본문 읽기 — 문장 사이 쉼(문단 끝은 더 길게), 읽는 글은 speak_reading 한 길

수정 전 코드: tts_text 모듈·speak_reading·_find_voice·쉼이 없어 (A)~(F) 가 실패한다.
실제 소리(자연스러움)는 사람이 듣고 판단한다 — 이 검사는 넘기는 글과 자리만 본다. 소리는 내지 않는다.
"""
import os, sys, tempfile, shutil

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


def spoken(text):
    from viewer.study import tts_text
    return [(sp.text, lg) for sp, lg in tts_text.reading_pieces(text)]


try:
    from viewer.study import tts_text
except Exception as e:                       # 수정 전 코드
    tts_text = None
    chk(False, "(A) viewer.study.tts_text 가 있다", repr(e))

if tts_text is not None:
    print("=== (A) 정규화 표 ===")
    KO = [
        ("시편 3개를 만든다.", "시편 세 개를 만든다."),
        ("학생 20명과 25명이 왔다.", "학생 스무 명과 스물다섯 명이 왔다."),
        ("두께는 25 mm 이다.", "두께는 25 밀리미터 이다."),
        ("두께는 25mm 이다.", "두께는 25 밀리미터 이다."),
        ("60℃ 에서 양생", "60 도 에서 양생"),
        ("면적 1,250㎡ 이다.", "면적 1250 제곱미터 이다."),
        ("하중 40 kN 과 5 MPa", "하중 40 킬로뉴턴 과 5 메가파스칼"),
        ("공극률 4.5% 이다.", "공극률 4.5 퍼센트 이다."),
        ("3~5 mm 로 한다.", "3에서 5 밀리미터 로 한다."),
        ("2~3시간 둔다.", "2에서 세 시간 둔다."),
        ("기준일 2026-11-08 이다.", "기준일 2026년 11월 8일 이다."),
        ("기준일 2026.11.08. 이다.", "기준일 2026년 11월 8일 이다."),
        ("결과는 다르다[12].", "결과는 다르다."),
        ("결과는 다르다 [3, 5].", "결과는 다르다."),
        ("3개월 동안", "3개월 동안"),               # 개월은 한자어 — 건드리지 않는다
        ("표 2-1 을 본다.", "표 2-1 을 본다."),       # 붙임표는 범위가 아니다(표·식 번호)
        ("100개", "100개"),                           # 고유어는 99 까지
    ]
    for src, want in KO:
        got = "".join(t for t, _ in spoken(src))
        chk(got == want, "(A) 한국어 " + src, "→ " + got)
    EN = [
        ("The layer is 25 mm thick.", "The layer is 25 millimeters thick."),
        ("A load of 1 kN was applied.", "A load of 1 kilonewton was applied."),
        ("Cured at 60 °C for 2–3 hours.", "Cured at 60 degrees Celsius for 2 to 3 hours."),
        ("Air voids were 4% e.g. in Fig. 4 [3].", "Air voids were 4 percent for example in Figure 4."),
        ("Tested on 2026-11-08 in the lab.", "Tested on November 8, 2026 in the lab."),
        ("See Table 2-1 and Eq. 3.", "See Table 2-1 and Equation 3."),
        ("The 3 more samples failed.", "The 3 more samples failed."),   # 'm' 뒤에 글자 — 단위 아님
    ]
    for src, want in EN:
        got = "".join(t for t, _ in spoken(src))
        chk(got == want, "(A) 영어 " + src, "→ " + got)
    chk(tts_text.native_number(1) == "한" and tts_text.native_number(20) == "스무"
        and tts_text.native_number(99) == "아흔아홉" and tts_text.native_number(100) is None,
        "(A) 고유어 셈 1→한·20→스무·99→아흔아홉·100 은 없음")

    print()
    print("=== (B) 한영 구간 ===")
    p = spoken("PolyPDF는 PDF 파일을 연다.")
    chk([lg for _, lg in p] == ["ko"], "(B) 이름·약어(1~2 낱말)는 한국어 음성", str(p))
    p = spoken("이 값은 ASTM D6373 기준이다.")
    chk([lg for _, lg in p] == ["ko"], "(B) 규격 번호도 한국어 음성", str(p))
    p = spoken("이 방법은 Superpave mix design method 에 따라 정한다.")
    chk([lg for _, lg in p] == ["ko", "en", "ko"], "(B) 긴 영어 구절만 영어 음성", str(p))
    chk(p[1][0] == "Superpave mix design method", "(B) 영어 조각은 그 구절", str(p))
    p = spoken("The binder grade is PG 64-22.")
    chk([lg for _, lg in p] == ["en"], "(B) 한글 없는 문장은 통째로 영어", str(p))
    p = spoken("(Superpave mix design method) 를 쓴다.")
    chk(p and p[0][1] == "en" and p[0][0].startswith("("),
        "(B) 부호만 남은 조각은 이웃에 붙는다 — 그것만으로 음성을 바꾸지 않는다", str(p))
    chk(tts_text.EN_RUN_MIN_WORDS == 3, "(B) 기준은 상수(낱말 3개)")

    print()
    print("=== (C) 위치 맵 ===")
    disp = "시편 3개를 25 mm 두께로 만든다."
    (sp, _), = tts_text.reading_pieces(disp)
    t = sp.text

    def back(word):
        i = t.index(word)
        a, n = sp.to_display(i, len(word))
        return disp[a:a + n]
    chk(back("시편") == "시편", "(C) 바뀌지 않은 낱말은 그 자리", back("시편"))
    chk(back("세") == "3개", "(C) '세' → 표시 '3개'(바꾼 조각 전체)", back("세"))
    chk(back("밀리미터") == "25 mm", "(C) '밀리미터' → 표시 '25 mm'", back("밀리미터"))
    chk(back("두께로") == "두께로", "(C) 바꾼 조각 뒤 낱말도 제자리", back("두께로"))
    chk(back("만든다") == "만든다", "(C) 문장 끝 낱말", back("만든다"))
    mixed = "이 방법은 Superpave mix design method 에 따라 25 mm 로 정한다."
    pcs = tts_text.reading_pieces(mixed)
    ok = True
    for sp2, _ in pcs:
        for w in ("방법은", "design", "따라", "정한다"):
            if w in sp2.text:
                a, n = sp2.to_display(sp2.text.index(w), len(w))
                ok = ok and mixed[a:a + n] == w
    chk(ok and len(pcs) == 3, "(C) 한영 조각마다 위치가 문장 전체 기준으로 맞는다")
    # 모든 바꾸지 않은 글자가 제 자리로 — 무작위 아닌 전수
    full = "공극률 4.5% 와 하중 40 kN, 기준일 2026-11-08, 결과[12] 는 3~5 mm 다."
    (sp3, _), = tts_text.reading_pieces(full)
    bad = 0
    s0 = 0
    for c in sp3.chunks:
        if not c.fixed:
            for k in range(len(c.text)):
                a, n = sp3.to_display(s0 + k, 1)
                if full[a:a + n] != c.text[k]:
                    bad += 1
        s0 += len(c.text)
    chk(bad == 0, "(C) 바꾸지 않은 글자는 하나하나 표시 글 같은 글자로", "어긋남 %d" % bad)

print()
print("=== (D) TTS.speak_reading ===")
from viewer.study import tts as tts_mod


class _Tok:
    def __init__(self, name, lang):
        self.name, self.lang = name, lang

    def GetAttribute(self, k):
        return self.name if k == "Name" else self.lang


class _Status:
    InputWordPosition = 0
    InputWordLength = 0
    CurrentStreamNumber = 0
    RunningState = 1


class _Voice:
    def __init__(self):
        self.calls = []
        self.Voice = None
        self.Rate = 0
        self.Status = _Status()
        self._n = 0

    def Speak(self, text, flags):
        self._n += 1
        self.calls.append((text, self.Voice.name if self.Voice else None, flags))
        return self._n

    def WaitUntilDone(self, ms):
        return True

    def GetVoices(self):
        return [_Tok("Microsoft Heami Desktop", "412"), _Tok("Microsoft Zira Desktop", "409")]


K, E = _Tok("Heami", "412"), _Tok("Zira", "409")
t = tts_mod.TTS()
t._ok = True
t._voice = _Voice()
t._tok = {"kor": K, "eng": E}
t._by_name = {"Heami": K, "Zira": E}
sr = getattr(t, "speak_reading", None)
chk(callable(sr), "(D) TTS.speak_reading 이 있다")
if callable(sr):
    disp = "이 방법은 Superpave mix design method 에 따라 3개를 만든다."
    ok = sr(disp)
    calls = t._voice.calls
    chk(ok and [c[1] for c in calls] == ["Heami", "Zira", "Heami"],
        "(D) 조각마다 그 언어 음성", str(calls))
    chk(calls and calls[0][2] & 2 and not (calls[1][2] & 2) and not (calls[2][2] & 2),
        "(D) 첫 조각만 앞 발화를 끊고(PURGE) 나머지는 이어서(대기열)", str([c[2] for c in calls]))
    chk(len(calls) == 3 and "세 개를" in calls[2][0], "(D) 엔진에는 읽는 글", str(calls[-1:]))
    # 셋째 흐름에서 '세' 를 읽는 중 → 표시 글 '3개'
    st = t._voice.Status
    st.CurrentStreamNumber = 3
    st.InputWordPosition = calls[2][0].index("세")
    st.InputWordLength = 1
    ws = t.word_span()
    chk(ws is not None and disp[ws[0]:ws[0] + ws[1]] == "3개",
        "(D) word_span 은 표시 글 위치(문장 전체 기준)", str(ws))
    st.CurrentStreamNumber = 2
    st.InputWordPosition = calls[1][0].index("design")
    st.InputWordLength = 6
    ws = t.word_span()
    chk(ws is not None and disp[ws[0]:ws[0] + ws[1]] == "design",
        "(D) 영어 조각의 낱말도 표시 글 자리로", str(ws))
    # 성우 고정 — 한 조각
    t._voice.calls = []
    t._forced = K
    sr(disp)
    chk(len(t._voice.calls) == 1 and "세 개를" in t._voice.calls[0][0],
        "(D) 성우를 고정하면 조각을 나누지 않는다(정규화는 한다)", str(t._voice.calls))
    t._forced = None

print()
print("=== (E) mp3 — 같은 음성 목록·쉼·가사 ===")
from viewer.study import mp3_export as mp3
fv = getattr(mp3, "_find_voice", None)
chk(callable(fv), "(E) mp3_export._find_voice 가 있다")
if callable(fv):
    orig = tts_mod.TTS._add_onecore_voices
    tts_mod.TTS._add_onecore_voices = staticmethod(
        lambda wc, add: [add(_Tok("Microsoft Mark", "409")), add(_Tok("Microsoft Heami", "412"))])
    try:
        v = _Voice()
        chk(fv(v, "Microsoft Mark") is not None,
            "(E) 화면 읽기에서 고른 OneCore 음성(Mark)을 mp3 도 찾는다")
        chk(fv(v, "Microsoft Heami") is None,
            "(E) 'Desktop' 만 다른 같은 음성은 하나만(클래식 우선 — 화면 읽기 목록과 같다)")
        chk(fv(v, None) is None, "(E) 성우를 안 골랐으면 언어 자동")
    finally:
        tts_mod.TTS._add_onecore_voices = orig
chk(getattr(mp3, "_silence", None) is not None and len(mp3._silence(200)) == int(22050 * 0.2) * 2,
    "(E) 쉼 200ms = 0 으로 채운 PCM")

# 실제 SAPI 가 있으면 소리 없이(메모리 합성) mp3 를 만들어 본다
real = False
try:
    import win32com.client  # noqa
    import lameenc  # noqa
    real = tts_mod.TTS().available()
except Exception:
    real = False
if real and tts_text is not None:
    d = tempfile.mkdtemp(prefix="polypdf_tts261108_")
    try:
        segs = [("시편 3개를 25 mm 두께로 만든다.", "ko"),
                ("The layer is 25 mm thick.", "en"),
                ("이 방법은 Superpave mix design method 에 따라 정한다.", "ko")]
        out = os.path.join(d, "a.mp3")
        lrc = os.path.join(d, "a.lrc")
        mp3.synth_to_mp3(segs, out, lrc_path=lrc)
        lines = open(lrc, encoding="utf-8").read().splitlines()
        chk(os.path.getsize(out) > 1000, "(E) 실제 SAPI 로 mp3 가 만들어진다(소리 없이)")
        chk([ln[10:] for ln in lines] == [s for s, _ in segs], "(E) 가사는 표시 글 그대로", str(lines))
        # 고른 OneCore 음성으로도 만들어진다
        tt = tts_mod.TTS(); tt._ensure()
        oc = [n for n in tt.voice_names() if "Desktop" not in n]
        if oc:
            mp3.synth_to_mp3(segs[:1], os.path.join(d, "b.mp3"), voice_name=oc[0])
            chk(os.path.getsize(os.path.join(d, "b.mp3")) > 1000,
                "(E) OneCore 음성(%s)으로 mp3" % oc[0])
    finally:
        shutil.rmtree(d, ignore_errors=True)
else:
    print("SKIP - (E) 실제 SAPI·lameenc 없음 — 메모리 합성 생략")

print()
print("=== (F) 본문 읽기 — 쉼·한 길 ===")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject
app = QApplication.instance() or QApplication([])
from viewer.widgets.read_aloud import ReadAloud


class _FakeTts:
    def __init__(self):
        self.said = []

    def speak_reading(self, text):
        self.said.append(text)
        return True

    def speak(self, text, lang="eng", queue=False):
        self.said.append(("raw", text))
        return True

    def is_speaking(self):
        return False

    def saw_speaking(self):
        return True

    def stop(self):
        pass


class _SB:
    def showMessage(self, *a, **k):
        pass


class _View:
    def clear_word_highlights(self):
        pass

    def highlight_word_groups(self, *a, **k):
        pass


fk = _FakeTts()


class _MW(QObject):
    status = _SB()
    main_view = _View()

    def _study_get_tts(self):
        return fk


r = ReadAloud(_MW())
r._active = True
r._sents = ["첫 문장은 3개다.", "둘째 문장.", "셋째."]
r._srects = []
r._spans = []
r._para_end = [False, True, False]
r._pages, r._pi = [0], 0
r._speak_cur()
chk(fk.said == ["첫 문장은 3개다."], "(F) 읽는 글은 speak_reading 한 길(표시 글을 넘긴다)", str(fk.said))
r._tick()
chk(r._si == 0, "(F) 문장이 끝나도 곧바로 넘어가지 않고 쉰다", "si=%d" % r._si)
import time as _time
pu = getattr(r, "_pause_until", 0.0)
chk(0.15 <= pu - _time.time() <= 0.25, "(F) 문장 사이 쉼 = SENT_PAUSE_MS", "%.3f" % (pu - _time.time()))
r._pause_until = _time.time() - 0.01
r._tick()
chk(r._si == 1 and fk.said[-1] == "둘째 문장.", "(F) 쉼이 지나면 다음 문장", str(fk.said))
r._tick()
pu = r._pause_until - _time.time()
chk(0.4 <= pu <= 0.55, "(F) 문단(줄 묶음) 끝은 더 길게 = PARA_PAUSE_MS", "%.3f" % pu)
r._timer.stop()

# _page_units 의 셋째 값 — 줄의 마지막 문장인가(이어지는 줄이면 아니다)
import viewer.text_extract2 as tx
rows = [{"text": "첫째 문장이다. 둘째 문장은 다음 줄로", "rects": [(0, 0, 1, 1)]},
        {"text": "이어진다. 셋째 문장이다.", "rects": [(0, 2, 1, 3)]},
        {"text": "넷째 문단이다.", "rects": [(0, 4, 1, 5)]}]
orig_dr = tx.display_rows
tx.display_rows = lambda *a, **k: rows


class _V2(_View):
    def current_file(self):
        return "x.pdf"


r._view = _V2()
try:
    units = r._page_units(0)
finally:
    tx.display_rows = orig_dr
flags = [(u[0], u[2] if len(u) > 2 else None) for u in units]
want = [("첫째 문장이다.", False), ("둘째 문장은 다음 줄로 이어진다.", False),
        ("셋째 문장이다.", True), ("넷째 문단이다.", True)]
chk(flags == want, "(F) 줄(문단) 끝 표시 — 다음 줄로 이어지는 줄의 앞 문장은 끝이 아니다", str(flags))

print()
print("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
