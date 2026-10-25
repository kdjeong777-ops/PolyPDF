# -*- coding: utf-8 -*-
"""진행 창 글 — 흔들리지 않게, 내부 값 없이 (디자인 SOT §2.7 '진행 창 글', 261026-2).

진행 창 글은 가운데 정렬이다 — 줄 폭이 바뀌면 줄 전체가 좌우로 움직인다. 그래서 바뀌는 부분의 폭을 고정한다.
- `HEARTBEAT` — 같은 글자 묶음을 자리만 바꾼 프레임(폭이 같다). 종전 `|`→`||`→`|||` 는 0.25초마다 폭이 바뀌었다.
- `pad_count` — 진행 숫자의 앞을 숫자 폭 빈칸(U+2007)으로 채워 전체 수의 자릿수에 맞춘다.
- `step` — 쪽을 말하는 일의 글 `단계 k/n · 원본 p쪽`. 파일마다 나눈 막대 척도(1000칸)·엔진 단계 이름·날 글(`p.12`)은 글에 넣지 않는다
  (그런 일은 `_run_merge_job(counts=False)` 로 부르고 글이 스스로 몇째인지 말한다).
- `file_head` — 일괄의 1줄 `파일 2/5 · 이름`(한 파일이면 이름만).

쓰는 쪽은 단계 이름을 `tr_noop` 상수로 두고 `step(tr(상수), …)` 로 부른다. `tr` 은 **모듈 머리에서** import 한다 —
함수 안에서 `from viewer.i18n import tr` 하면 그 함수의 `tr` 이 지역 이름이 되어 UnboundLocalError 가 날 수 있다(`test_i18n_keys` F, 261026-2 에 실제로 걸렸다).
"""
from __future__ import annotations

from viewer.i18n import tr

HEARTBEAT = ("|··", "·|·", "··|", "·|·")
FIGURE_SPACE = " "


def pad_count(k, n) -> str:
    """`k/n` — k 를 n 의 자릿수에 맞춰 앞을 숫자 폭 빈칸으로 채운다(9/50 과 10/50 이 같은 폭)."""
    k, n = str(int(k)), str(int(n))
    return FIGURE_SPACE * max(0, len(n) - len(k)) + k + "/" + n


def step(label: str, k=None, n=None, page=None, doc_pages=None) -> str:
    """`단계 k/n · 원본 p쪽`(label 은 이미 tr() 한 단계 이름, k·p 는 1부터). 없는 칸은 뺀다.
    `doc_pages`(문서 쪽 수)를 주면 p 도 그 자릿수에 맞춰 채운다."""
    out = str(label)
    if k is not None and n:
        out += " " + pad_count(k, n)
    if page is not None:
        p = str(int(page))
        if doc_pages:
            p = FIGURE_SPACE * max(0, len(str(int(doc_pages))) - len(p)) + p
        out += "  ·  " + tr("원본 {page}쪽").format(page=p)
    return out


def file_head(i: int, n: int, name: str) -> str:
    """일괄 진행 글의 1줄 — 여러 파일이면 `파일 2/5 · 이름`(i 는 0부터), 하나면 이름만."""
    if n <= 1:
        return str(name)
    return tr('파일 {count} · {name}').format(count=pad_count(i + 1, n), name=name)
