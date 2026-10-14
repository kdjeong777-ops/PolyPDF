# -*- coding: utf-8 -*-
"""문서 비교 — 개정판 차이 (마스터 §4.11, 261014-23).

`compare(옛판, 새판, tick)` — 텍스트 창과 같은 원천(`PageSource.lines`, join=False)으로 두 문서의 줄을 이어
`difflib.SequenceMatcher` 로 비교한다. 배경 스레드에서 부른다(문서는 PageSource 가 그 스레드에서 연다).
결과 `[{kind, old: [(쪽, 사각형, 글)], new: [...], text}]` — kind 는 "replace" | "delete" | "insert".
"""
from __future__ import annotations

import difflib
import re

from viewer.i18n import tr_noop

KIND_LABELS = {"replace": tr_noop("바뀜"), "delete": tr_noop("지움"), "insert": tr_noop("넣음")}
_WS = re.compile(r"\s+")


def _norm(t: str) -> str:
    return _WS.sub(" ", str(t or "")).strip()


def _lines(path, tick, base: int, span: int) -> list:
    """`[(쪽, 사각형, 글)]` — 빈 줄·자리 없는 줄은 뺀다."""
    from viewer.convert.source import PageSource
    out = []
    with PageSource(path, tables="off") as ps:
        n = ps.page_count
        for pg in range(n):
            if tick:
                tick(base + int(span * pg / max(1, n)), f"p.{pg + 1}")
            for r in ps.lines(pg, tables="off", join=False):
                t = _norm(r.get("text", ""))
                if t and r.get("rect"):
                    out.append((pg, tuple(r["rect"]), t))
    return out


def word_diff(a: str, b: str) -> str:
    """낱말 단위 차이 — `[-지운-]{+넣은+}` 꼴(같은 낱말은 그대로)."""
    wa, wb = a.split(), b.split()
    sm = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out.append(" ".join(wa[i1:i2]))
        else:
            if i2 > i1:
                out.append("[-" + " ".join(wa[i1:i2]) + "-]")
            if j2 > j1:
                out.append("{+" + " ".join(wb[j1:j2]) + "+}")
    return " ".join(x for x in out if x)


PAIR_MIN = 0.5      # 바뀐 덩어리 안에서 '같은 줄을 고친 것' 으로 볼 비슷함(difflib ratio)
PAIR_MAX_CELLS = 40000   # 짝 맞추기를 할 덩어리 크기 상한(옛 줄 수 × 새 줄 수) — 넘으면 덩어리째 바뀜


def _split_block(old: list, new: list) -> list:
    """difflib 의 replace 덩어리를 줄 짝으로 다시 나눈다 — 비슷한 줄끼리는 바뀜, 짝 없는 줄은 지움·넣음.

    difflib 은 붙어 있는 '고친 줄 + 지운 줄' 을 한 replace 로 묶어, 지운 줄이 바뀜(노랑)으로 보인다.
    차례를 지키며(앞뒤 바뀜 없음) 가장 비슷한 짝을 앞에서부터 고른다."""
    if len(old) * len(new) > PAIR_MAX_CELLS:
        return [("replace", old, new)]
    out, j = [], 0
    for o in old:
        best, bk = 0.0, None
        for k in range(j, len(new)):
            r = difflib.SequenceMatcher(None, o[2], new[k][2], autojunk=False).ratio()
            if r > best:
                best, bk = r, k
        if bk is not None and best >= PAIR_MIN:
            if bk > j:
                out.append(("insert", [], new[j:bk]))
            out.append(("replace", [o], [new[bk]]))
            j = bk + 1
        else:
            out.append(("delete", [o], []))
    if j < len(new):
        out.append(("insert", [], new[j:]))
    # 이어진 같은 종류는 한 항목으로
    merged = []
    for kind, a, b in out:
        if merged and merged[-1][0] == kind and kind != "replace":
            merged[-1] = (kind, merged[-1][1] + a, merged[-1][2] + b)
        else:
            merged.append((kind, a, b))
    return merged


def compare(old_path, new_path, tick=None) -> list:
    """`tick(했음 0~1000, 글)`. 바뀐 곳 목록(차례대로)."""
    a = _lines(old_path, tick, 0, 450)
    b = _lines(new_path, tick, 450, 450)
    if tick:
        tick(900, "diff")
    sm = difflib.SequenceMatcher(None, [t for _p, _r, t in a], [t for _p, _r, t in b], autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        parts = _split_block(a[i1:i2], b[j1:j2]) if op == "replace" else [(op, a[i1:i2], b[j1:j2])]
        for kind, old, new in parts:
            if kind == "replace":
                text = word_diff(" ".join(t for *_x, t in old), " ".join(t for *_x, t in new))
            elif kind == "delete":
                text = " ".join(t for *_x, t in old)
            else:
                text = " ".join(t for *_x, t in new)
            out.append({"kind": kind, "old": old, "new": new, "text": text})
    if tick:
        tick(1000, "")
    return out
