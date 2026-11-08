"""읽는 글 다듬기 — TTS(SAPI)에 넘기기 전 정규화·한영 구간 나누기·위치 맵 (영상·음성 SOT §1.8, 261108-25).

화면에 보이는 글(**표시 글**)은 바꾸지 않는다. 소리 내기 좋게 바꾼 **읽는 글**만 엔진에 넘기고,
읽는 글의 위치를 표시 글의 위치로 되돌리는 맵(`SpokenText.to_display`)을 함께 둔다 —
SAPI 의 낱말 경계(`InputWordPosition`)는 읽는 글 기준이라, 맵 없이는 칠하는 자리가 어긋난다.

규칙(전부 상수·표 — 바꿀 때는 SOT §1.8 표와 함께):
- 한국어 구간: 숫자+단위(mm·kN·℃·㎡ …)는 단위를 한글로, 셈 단위(개·명·권 …) 앞 1~99 는 고유어(세 개),
  범위 `3~5` → '3에서 5', 날짜 `2026-11-08`·`2026.11.08` → '2026년 11월 8일', 천 단위 쉼표 빼기.
- 영어 구간: SAPI 가 잘 읽는 숫자는 그대로, 단위·약어(e.g.·Fig.)·범위·날짜만.
- 둘 다: 문헌 번호 `[12]`·`[3, 5]` 는 읽지 않는다. 그림·표·식 참조는 읽는다(줄임말만 풀어서).
- 한국어 문장 속 짧은 영어(낱말 `EN_RUN_MIN_WORDS` 개 미만)는 한국어 음성으로 둔다 — 음성이 잦게 바뀌면 더 어색하다.

이 모듈은 Qt·COM 을 쓰지 않는다(정규식뿐, 문장 하나에 1ms 미만 — 메인 스레드에서 불러도 된다, 응답성 SOT §4.8).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── 쉼 (ms) — 문장 사이·문단(줄 묶음) 사이. SAPI 가 문장 끝에 두는 쉼에 더해진다. ──
SENT_PAUSE_MS = 200
PARA_PAUSE_MS = 500

# ── 한영 섞인 글: 한국어 문장 안의 영어 구절이 이만큼 길어야 영어 음성으로 ──
EN_RUN_MIN_WORDS = 3        # 낱말 수(약어·이름 1~2 낱말은 한국어 음성이 읽는다)
EN_RUN_MIN_LETTERS = 10     # 영문자 수(짧은 낱말 셋 'a b c' 같은 것은 빼려고)

_HANGUL = re.compile(r"[가-힣]")

# 숫자 뒤에서만 바꾸는 단위 — (표시, 한국어, 영어 단수, 영어 복수). 긴 것부터 맞춘다(정규식 만들 때 정렬).
UNITS = [
    ("mm", "밀리미터", "millimeter", "millimeters"),
    ("cm", "센티미터", "centimeter", "centimeters"),
    ("km", "킬로미터", "kilometer", "kilometers"),
    ("m", "미터", "meter", "meters"),
    ("㎜", "밀리미터", "millimeter", "millimeters"),
    ("㎝", "센티미터", "centimeter", "centimeters"),
    ("㎞", "킬로미터", "kilometer", "kilometers"),
    ("㎡", "제곱미터", "square meter", "square meters"),
    ("m²", "제곱미터", "square meter", "square meters"),
    ("m2", "제곱미터", "square meter", "square meters"),
    ("㎥", "세제곱미터", "cubic meter", "cubic meters"),
    ("m³", "세제곱미터", "cubic meter", "cubic meters"),
    ("m3", "세제곱미터", "cubic meter", "cubic meters"),
    ("mg", "밀리그램", "milligram", "milligrams"),
    ("kg", "킬로그램", "kilogram", "kilograms"),
    ("g", "그램", "gram", "grams"),
    ("㎏", "킬로그램", "kilogram", "kilograms"),
    ("t", "톤", "ton", "tons"),
    ("kN", "킬로뉴턴", "kilonewton", "kilonewtons"),
    ("MN", "메가뉴턴", "meganewton", "meganewtons"),
    ("N", "뉴턴", "newton", "newtons"),
    ("MPa", "메가파스칼", "megapascal", "megapascals"),
    ("GPa", "기가파스칼", "gigapascal", "gigapascals"),
    ("kPa", "킬로파스칼", "kilopascal", "kilopascals"),
    ("Pa", "파스칼", "pascal", "pascals"),
    ("㎫", "메가파스칼", "megapascal", "megapascals"),
    ("㎪", "킬로파스칼", "kilopascal", "kilopascals"),
    ("℃", "도", "degree Celsius", "degrees Celsius"),
    ("°C", "도", "degree Celsius", "degrees Celsius"),
    ("°F", "화씨 도", "degree Fahrenheit", "degrees Fahrenheit"),
    ("°", "도", "degree", "degrees"),
    ("%", "퍼센트", "percent", "percent"),
    ("mL", "밀리리터", "milliliter", "milliliters"),
    ("ml", "밀리리터", "milliliter", "milliliters"),
    ("L", "리터", "liter", "liters"),
    ("㎖", "밀리리터", "milliliter", "milliliters"),
    ("ℓ", "리터", "liter", "liters"),
    ("kW", "킬로와트", "kilowatt", "kilowatts"),
    ("W", "와트", "watt", "watts"),
    ("Hz", "헤르츠", "hertz", "hertz"),
    ("kHz", "킬로헤르츠", "kilohertz", "kilohertz"),
    ("rpm", "알피엠", "RPM", "RPM"),
    ("km/h", "킬로미터 매 시", "kilometer per hour", "kilometers per hour"),
    ("m/s", "미터 매 초", "meter per second", "meters per second"),
]

# 한국어 셈 단위 — 앞의 1~99 를 고유어로(세 개, 스무 명). '번'(번호/횟수)·'시'·'장'(章)은 뜻이 갈려 넣지 않는다.
NATIVE_COUNTERS = ("시간", "개", "명", "권", "마리", "살", "그루", "켤레", "가지", "군데", "자루", "대", "채", "척", "벌")

# 영어 약어(구간 안 어디서나) — SAPI 가 글자로 끊어 읽거나 마침표에서 문장을 끊는 것들
EN_ABBREV = [
    ("e.g.", "for example"), ("i.e.", "that is"), ("etc.", "et cetera"), ("vs.", "versus"),
    ("approx.", "approximately"), ("Fig.", "Figure"), ("Figs.", "Figures"), ("Eq.", "Equation"),
    ("Eqs.", "Equations"), ("Tab.", "Table"), ("et al.", "and others"),
    ("cf.", "compare"), ("Ref.", "Reference"), ("Sec.", "Section"), ("Ch.", "Chapter"),
]

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")
_NATIVE_ONES = ("", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉")
_NATIVE_TENS = ("", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔")


def native_number(n: int):
    """1~99 의 고유어 셈 꼴(관형형): 1→한, 3→세, 20→스무, 25→스물다섯. 범위 밖은 None."""
    if not (1 <= n <= 99):
        return None
    t, o = divmod(n, 10)
    if t == 2 and o == 0:
        return "스무"
    return _NATIVE_TENS[t] + _NATIVE_ONES[o]


# ── 읽는 글 + 위치 맵 ────────────────────────────────────────────────

@dataclass
class _Chunk:
    text: str          # 읽는 글 조각
    d0: int            # 표시 글 시작
    d1: int            # 표시 글 끝
    fixed: bool        # 바꾼 조각(다시 바꾸지 않음, 위치는 조각 전체로 맞춘다)


@dataclass
class SpokenText:
    """읽는 글과 표시 글 위치 맵. `display` 는 이 조각의 표시 글(전체 글 속 `offset` 부터)."""
    display: str
    offset: int = 0
    chunks: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(c.text for c in self.chunks)

    def to_display(self, pos: int, length: int = 1):
        """읽는 글 (pos, length) → 표시 글 (pos, length) — 전체 글 기준(offset 포함).

        바꾼 조각에 걸리면 그 조각의 표시 범위 전체(예: '세 개' 의 '세' → '3개')."""
        if not self.chunks:
            return (self.offset, 0)
        end = pos + max(1, int(length))
        a = b = None
        s0 = 0
        for c in self.chunks:
            s1 = s0 + len(c.text)
            if s1 > pos and s0 < end:          # 겹친다
                if c.fixed:
                    ca, cb = c.d0, c.d1
                else:
                    ca = c.d0 + max(0, pos - s0)
                    cb = c.d0 + min(len(c.text), end - s0)
                a = ca if a is None else min(a, ca)
                b = cb if b is None else max(b, cb)
            s0 = s1
        if a is None:                           # 끝을 넘었다 — 마지막 자리
            last = self.chunks[-1]
            return (self.offset + last.d1, 0)
        return (self.offset + a, b - a)


def _apply(chunks: list, rx: re.Pattern, repl) -> list:
    """바꾸지 않은 조각에서만 rx 를 찾아 repl(m) 로 바꾼 조각(fixed)으로 나눈다."""
    out = []
    for c in chunks:
        if c.fixed:
            out.append(c)
            continue
        t, pos = c.text, 0
        for m in rx.finditer(t):
            new = repl(m)
            if new is None:
                continue
            if m.start() > pos:
                out.append(_Chunk(t[pos:m.start()], c.d0 + pos, c.d0 + m.start(), False))
            out.append(_Chunk(new, c.d0 + m.start(), c.d0 + m.end(), True))
            pos = m.end()
        if pos < len(t):
            out.append(_Chunk(t[pos:], c.d0 + pos, c.d1, False))
    return out


_NUM = r"\d+(?:[.,]\d+)*"
_UNIT_KEYS = sorted({u[0] for u in UNITS}, key=len, reverse=True)
_UNIT_BY = {u[0]: u for u in UNITS}
# 단위 뒤에 글자가 이어지면 단위가 아니다(3 meters, 5 mmHg, 2 m짜리 는 'm' 뒤가 한글이라 단위로 본다)
_UNIT_RX = re.compile(r"(?<![\w.])(" + _NUM + r")\s?(" + "|".join(re.escape(k) for k in _UNIT_KEYS)
                      + r")(?![A-Za-z0-9²³])")
_CITE_RX = re.compile(r"\s?\[\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]")
_RANGE_RX = re.compile(r"(?<=\d)\s*[~～∼–]\s*(?=\d)")
_DATE_RX = re.compile(r"(?<!\d)((?:19|20)\d{2})[-./](\d{1,2})[-./](\d{1,2})\.?(?!\d)")
_KO_THOUSANDS_RX = re.compile(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)")
_COUNTER_RX = re.compile(r"(?<![\d.,])(\d{1,2})\s?(" + "|".join(NATIVE_COUNTERS) + r")(?!월)")   # '3개월' 은 한자어(삼 개월)
_EN_ABBR_RX = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(a) for a, _ in
                         sorted(EN_ABBREV, key=lambda x: len(x[0]), reverse=True)) + r")")
_EN_ABBR = dict(EN_ABBREV)


def _num_value(s: str):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def normalize(text: str, lang: str, *, offset: int = 0) -> SpokenText:
    """표시 글 text → 읽는 글(+위치 맵). lang 은 'ko…'/'kor' 면 한국어, 아니면 영어 규칙."""
    ko = (lang or "").lower().startswith("ko")
    chunks = [_Chunk(text, 0, len(text), False)]
    chunks = _apply(chunks, _CITE_RX, lambda m: "")             # [12] — 읽지 않음

    def _date(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return None
        return f"{y}년 {mo}월 {d}일" if ko else f"{_MONTHS[mo - 1]} {d}, {y}"
    chunks = _apply(chunks, _DATE_RX, _date)
    # 범위는 물결·en 대시만 — 붙임표 '2-1' 은 표·식 번호일 때가 많아 건드리지 않는다
    chunks = _apply(chunks, _RANGE_RX, lambda m: "에서 " if ko else " to ")

    def _unit(m):
        num, key = m.group(1), m.group(2)
        u = _UNIT_BY[key]
        if ko:
            return f"{num.replace(',', '')} {u[1]}"
        v = _num_value(num)
        return f"{num} {u[2] if v == 1 else u[3]}"
    chunks = _apply(chunks, _UNIT_RX, _unit)
    if ko:
        def _counter(m):
            w = native_number(int(m.group(1)))
            return f"{w} {m.group(2)}" if w else None
        chunks = _apply(chunks, _COUNTER_RX, _counter)
        chunks = _apply(chunks, _KO_THOUSANDS_RX, lambda m: m.group(0).replace(",", ""))
    chunks = _apply(chunks, _EN_ABBR_RX, lambda m: _EN_ABBR.get(m.group(1)))
    return SpokenText(display=text, offset=offset, chunks=chunks)


# ── 한영 구간 나누기 ────────────────────────────────────────────────

_EN_RUN_RX = re.compile(r"[A-Za-z][A-Za-z'’\-]*(?:(?:[ \t,:;/]|\s-\s)+[A-Za-z0-9][A-Za-z0-9'’\-]*)*")


def base_lang(text: str) -> str:
    """문장의 바탕 언어 — 한글이 있으면 'ko'(종전 읽기 규칙과 같다)."""
    return "ko" if _HANGUL.search(text or "") else "en"


def split_lang(text: str) -> list:
    """표시 글 → [(시작, 끝, 'ko'|'en')] 구간. 한글 없는 글은 통째로 영어.

    한국어 문장 안의 영어 구절은 낱말 `EN_RUN_MIN_WORDS` 개 이상·영문자 `EN_RUN_MIN_LETTERS`
    자 이상일 때만 영어 구간으로 뗀다 — 약어·이름·단위(1~2 낱말)는 한국어 음성이 그대로 읽는다.
    """
    if not text:
        return []
    if base_lang(text) == "en":
        return [(0, len(text), "en")]
    runs = []
    for m in _EN_RUN_RX.finditer(text):
        seg = m.group(0).rstrip(" ,:;/-")
        words = re.findall(r"[A-Za-z][A-Za-z'’\-]*", seg)
        letters = sum(len(w) for w in words)
        if len(words) >= EN_RUN_MIN_WORDS and letters >= EN_RUN_MIN_LETTERS:
            runs.append((m.start(), m.start() + len(seg)))
    if not runs:
        return [(0, len(text), "ko")]
    out, pos = [], 0
    for a, b in runs:
        if a > pos:
            out.append((pos, a, "ko"))
        out.append((a, b, "en"))
        pos = b
    if pos < len(text):
        out.append((pos, len(text), "ko"))
    # 글자 없는(문장부호·빈칸뿐) 한국어 조각은 앞 구간에 붙인다 — 그것만으로 음성을 바꾸지 않게
    merged = []
    for a, b, lg in out:
        if merged and not re.search(r"[0-9A-Za-z가-힣]", text[a:b]):
            pa, _, plg = merged[-1]
            merged[-1] = (pa, b, plg)
        else:
            merged.append((a, b, lg))
    if len(merged) > 1 and not re.search(r"[0-9A-Za-z가-힣]", text[merged[0][0]:merged[0][1]]):
        a0 = merged.pop(0)[0]
        _, b1, lg1 = merged[0]
        merged[0] = (a0, b1, lg1)
    return merged


def reading_pieces(text: str) -> list:
    """문장 하나 → 엔진에 차례로 넘길 [SpokenText] 와 언어 — [(SpokenText, 'ko'|'en')].

    각 SpokenText 의 `to_display` 는 **문장 전체(표시 글)** 기준 위치를 돌려준다."""
    out = []
    for a, b, lg in split_lang(text or ""):
        sp = normalize(text[a:b], lg, offset=a)
        if sp.text.strip():
            out.append((sp, lg))
    return out
