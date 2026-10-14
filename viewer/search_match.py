# -*- coding: utf-8 -*-
"""검색 일치 규칙 한 곳 — 대소문자 구분·정규식 (검색창 SOT §4.1, 261014-18).

질의를 글에 맞춰 보는 곳(결과 목록·개수·조각 글·본문 강조·이전/다음·스크린샷 강조·오른쪽 창 내용 찾기)은 모두 `Matcher` 를 쓴다.
둘 다 꺼져 있으면(`plain`) 부르는 쪽이 종전 길(LIKE·`search_for`)을 그대로 탄다.
"""
from __future__ import annotations

import re


class Matcher:
    """`Matcher(질의, case=, regex=)` — 정규식이 틀리면 `re.error`."""

    def __init__(self, query: str, case: bool = False, regex: bool = False):
        self.query = str(query or "")
        self.case = bool(case)
        self.regex = bool(regex)
        flags = 0 if self.case else re.IGNORECASE
        self.rx = re.compile(self.query if self.regex else re.escape(self.query), flags)

    @property
    def plain(self) -> bool:
        return not (self.case or self.regex)

    @property
    def mode(self) -> tuple:
        return (self.case, self.regex)

    def spans(self, text: str):
        """맞은 자리 `(시작, 끝)` — 길이 0 인 일치는 세지 않는다."""
        for m in self.rx.finditer(text or ""):
            if m.end() > m.start():
                yield m.start(), m.end()

    def count(self, text: str) -> int:
        return sum(1 for _ in self.spans(text))

    def first(self, text: str):
        return next(self.spans(text), None)

    def like_hint(self):
        """색인 LIKE 로 후보를 추릴 글 조각(대소문자 무시 부분일치) — 없으면 None(전부 훑는다).
        정규식은 맨 위 차례에 이어진 글자들 중 가장 긴 3자 이상 조각(맨 위에 `|` 가 있으면 None)."""
        if not self.regex:
            return self.query
        try:
            from re import _parser as sre_parse          # 표준 라이브러리 안쪽 — 실패하면 힌트 없이
            from re import _constants as C
            seq = sre_parse.parse(self.query)
        except Exception:
            return None
        runs, cur = [], []
        for op, av in seq:
            if op is C.LITERAL:
                cur.append(chr(av))
                continue
            if op is C.BRANCH:
                return None
            if cur:
                runs.append("".join(cur))
            cur = []
        if cur:
            runs.append("".join(cur))
        best = max(runs, key=len, default="")
        return best if len(best) >= 3 else None


def mode_of(case=False, regex=False):
    """설정 두 값 → `(case, regex)` 또는 None(둘 다 꺼짐 = 종전 길)."""
    return (bool(case), bool(regex)) if (case or regex) else None


def match_rects(page, matcher: Matcher) -> list:
    """쪽에서 맞은 자리의 사각형(`fitz.Rect`) — 줄마다 글자 상자로 글을 만들어 찾고 맞은 글자 상자를 합친다.
    `search_for` 처럼 줄을 넘는 일치는 찾지 않는다(검색창 SOT §4.1)."""
    import fitz
    out = []
    try:
        d = page.get_text("rawdict")
    except Exception:
        return out
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []) or []:
            chars = [c for sp in ln.get("spans", []) or [] for c in sp.get("chars", []) or []]
            if not chars:
                continue
            text = "".join(c.get("c", "") for c in chars)
            for s, e in matcher.spans(text):
                r = None
                for c in chars[s:e]:
                    cb = fitz.Rect(c["bbox"])
                    r = cb if r is None else (r | cb)
                if r is not None and not r.is_empty:
                    out.append(r)
    return out
