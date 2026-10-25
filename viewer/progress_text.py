# -*- coding: utf-8 -*-
"""진행 창 글이 흔들리지 않게 (디자인 SOT §2.7 '진행 창 글', 261026-2).

진행 창 글은 가운데 정렬이다 — 줄 폭이 바뀌면 줄 전체가 좌우로 움직인다. 그래서 바뀌는 부분의 폭을 고정한다.
- `HEARTBEAT` — 같은 글자 묶음을 자리만 바꾼 프레임(폭이 같다). 종전 `|`→`||`→`|||` 는 0.25초마다 폭이 바뀌었다.
- `pad_count` — 진행 숫자의 앞을 숫자 폭 빈칸(U+2007)으로 채워 전체 수의 자릿수에 맞춘다.
"""
from __future__ import annotations

HEARTBEAT = ("|··", "·|·", "··|", "·|·")
FIGURE_SPACE = " "


def pad_count(k, n) -> str:
    """`k/n` — k 를 n 의 자릿수에 맞춰 앞을 숫자 폭 빈칸으로 채운다(9/50 과 10/50 이 같은 폭)."""
    k, n = str(int(k)), str(int(n))
    return FIGURE_SPACE * max(0, len(n) - len(k)) + k + "/" + n
