# -*- coding: utf-8 -*-
"""사진 모드 줄 표기 — 보기설정 스타일 (사진 보기 SOT 4.38, 261104-13 사용자 지시).

책갈피창 줄 한 줄·썸네일 칸 두 줄(윗줄·아랫줄)을 **구문**(`{date} {name}` 꼴)으로 만든다. 조각은 `FIELDS` — 값이 없는 조각은
옆 구분자와 함께 빠진다. 스타일은 이름을 붙여 `preferences.picture.label_styles` 에 남긴다(최상위 새 키 금지 — 사진 보기 SOT 4.15).
이 모듈은 **글자 잇기만** 한다(메인에서 줄마다 불러도 가볍다). 값 읽기(날짜·가로×세로)는 배경 워커가 한다(사진 보기 SOT 4.37).
"""
from __future__ import annotations

import re
from pathlib import Path

from viewer.i18n import tr, tr_noop

FIELDS = ("date", "name", "size", "bytes", "ext")
FIELD_LABEL = {"date": tr_noop("날짜"), "name": tr_noop("파일명"), "size": tr_noop("가로×세로"),
               "bytes": tr_noop("용량(MB)"), "ext": tr_noop("확장자")}
SEPARATORS = (" ", " · ", " | ", " - ", "_", " / ")
_SEP_CHARS = " ·|-_/"
_TOKEN = re.compile(r"(\{(?:%s)\})" % "|".join(FIELDS))

# 기본 스타일 — 이름은 화면에 tr() 로. 사용자가 같은 이름으로 고치면 그 값이 이긴다('기본값으로' 로 되돌린다)
# 261105-11(사진 보기 SOT 4.37, 사용자 결정): 책갈피창 '기본' 은 이름만 — 날짜는 촬영일 자동 태그(·#YYYY-MM-DD)로 꼬리에 보인다.
#   종전 '{date} {name}' 은 날짜를 아직 못 읽은 줄만 이름으로 보여 줄마다 꼴이 달랐다. 앞 날짜는 '날짜 + 이름' 으로 고른다
BUILTIN_TREE = {"기본": "{name}", "날짜 + 이름": "{date} {name}", "상세": "{date} {name} · {size} · {bytes}"}
BUILTIN_STRIP = {"기본": ["{name}", "{date}"], "크기": ["{name}", "{size}"], "상세": ["{name}", "{date} · {bytes}"]}
_NAMES = (tr_noop("기본"), tr_noop("날짜 + 이름"), tr_noop("상세"), tr_noop("크기"))   # 기본 스타일 이름 — 번역 목록에 들게
DEFAULT = "기본"


def values(path, date: str = "", w: int = 0, h: int = 0, nbytes: int = 0) -> dict:
    """구문에 넣을 값 — 없는 것은 ''(그 조각은 빠진다)."""
    p = Path(str(path))
    return {"name": p.stem, "ext": p.suffix.lstrip(".").upper(), "date": date or "",
            "size": ("%d×%d" % (w, h)) if w and h else "",
            "bytes": fmt_mb(nbytes) if nbytes else ""}


def fmt_mb(n: int) -> str:
    mb = float(n) / (1024 * 1024)
    return ("%.1fMB" % mb) if mb >= 0.1 else ("%.2fMB" % mb)


def render(tpl: str, vals: dict) -> str:
    """구문 → 글. 값이 없는 조각은 빼고, 이어진 구분자는 앞 하나만, 앞뒤 구분자는 지운다."""
    parts = []
    for piece in _TOKEN.split(tpl or ""):
        if not piece:
            continue
        m = _TOKEN.fullmatch(piece)
        if m:
            v = vals.get(piece[1:-1], "")
            if v:
                parts.append(("v", v))
        else:
            if parts and parts[-1][0] == "t":
                continue                          # 빠진 값 사이의 구분자 — 앞 하나만
            parts.append(("t", piece))
    while parts and parts[0][0] == "t" and not parts[0][1].strip(_SEP_CHARS):
        parts.pop(0)
    while parts and parts[-1][0] == "t" and not parts[-1][1].strip(_SEP_CHARS):
        parts.pop()
    return "".join(s for _k, s in parts)


def styles(prefs: dict, which: str) -> dict:
    """이름 → 구문(책갈피창 `tree` 는 글, 썸네일 `strip` 은 [윗줄, 아랫줄]) — 기본 + 사용자(같은 이름이면 사용자)."""
    base = dict(BUILTIN_TREE if which == "tree" else BUILTIN_STRIP)
    mine = ((prefs or {}).get("label_styles") or {}).get(which) or {}
    base.update(mine.get("custom") or {})
    return base


def current(prefs: dict, which: str):
    """지금 고른 스타일의 구문."""
    st = styles(prefs, which)
    name = (((prefs or {}).get("label_styles") or {}).get(which) or {}).get("current") or DEFAULT
    return st.get(name) or st[DEFAULT]


def current_name(prefs: dict, which: str) -> str:
    name = (((prefs or {}).get("label_styles") or {}).get(which) or {}).get("current") or DEFAULT
    return name if name in styles(prefs, which) else DEFAULT


def save(prefs: dict, which: str, name: str, tpl, make_current: bool = True) -> None:
    """스타일 저장 — `prefs` 는 picture 묶음(사진 보기 SOT 4.15: 최상위 새 키 금지)."""
    ls = prefs.setdefault("label_styles", {})
    w = ls.setdefault(which, {})
    w.setdefault("custom", {})[name] = tpl
    if make_current:
        w["current"] = name


def delete(prefs: dict, which: str, name: str) -> None:
    """사용자 스타일을 지운다(기본 스타일이면 기본값으로 되돌아간다). 지금 것이었으면 '기본' 으로."""
    w = (prefs.setdefault("label_styles", {})).setdefault(which, {})
    (w.setdefault("custom", {})).pop(name, None)
    if w.get("current") == name and name not in (BUILTIN_TREE if which == "tree" else BUILTIN_STRIP):
        w["current"] = DEFAULT


def select(prefs: dict, which: str, name: str) -> None:
    prefs.setdefault("label_styles", {}).setdefault(which, {})["current"] = name


def is_builtin(which: str, name: str) -> bool:
    return name in (BUILTIN_TREE if which == "tree" else BUILTIN_STRIP)


def display_name(name: str) -> str:
    return tr(name) if name in BUILTIN_TREE or name in BUILTIN_STRIP else name
