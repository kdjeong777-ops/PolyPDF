# -*- coding: utf-8 -*-
"""PDF → 다른 형식 (형식 변환 SOT, 261014-11).

- `FORMATS` — 형식 목록. **다 만든 형식만** `ready` 다(메뉴에는 그것만 보인다 — 형식 변환 SOT §1·§2.1).
- `out_path` — 같은 폴더·같은 이름, 겹치면 ` (2)` 부터(§2.3).
- `parse_range` — `3-12`·`1,4,7-9` 꼴(1부터) → 0부터 쪽 목록.
- `run` — 한 파일을 변환한다. **배경 스레드에서** 부른다(문서는 `PageSource` 가 그 스레드에서 연다).
  `progress(했음, 전체, 글) -> bool` 이 False 면 멈추고 `Cancelled` — 만들던 파일은 지운다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from viewer.i18n import tr_noop

IMAGE_DPI = 150


class Cancelled(Exception):
    pass


class NothingToWrite(Exception):
    """만들 것이 없다(예: 표가 없는 문서의 Excel) — 실패가 아니라 알림."""


@dataclass(frozen=True)
class Format:
    key: str
    label: str          # tr_noop — 화면에서 tr() 로 옮긴다(다국어 SOT §6)
    ext: str            # 확장자 — 이미지는 폴더
    ready: bool


FORMATS = (
    Format("docx_edit", tr_noop("Word (편집 가능)"), ".docx", True),
    Format("docx_shape", tr_noop("Word (모양 그대로)"), ".docx", False),
    Format("hwpx_edit", tr_noop("한글 HWPX (편집 가능)"), ".hwpx", False),
    Format("hwpx_shape", tr_noop("한글 HWPX (모양 그대로)"), ".hwpx", False),
    Format("xlsx", tr_noop("Excel (표)"), ".xlsx", True),
    Format("txt", tr_noop("텍스트"), ".txt", True),
    Format("png", tr_noop("이미지 (PNG)"), "", True),
)


def ready_formats() -> list:
    return [f for f in FORMATS if f.ready]


def fmt(key: str) -> Format:
    for f in FORMATS:
        if f.key == key:
            return f
    raise KeyError(key)


def out_path(src, key: str) -> Path:
    """같은 폴더·같은 이름 — 이미 있으면 ` (2)`, ` (3)` …(형식 변환 SOT §2.3). 이미지는 폴더."""
    from viewer.pathutil import unique_path
    s = Path(src)
    f = fmt(key)
    return unique_path(s.with_name(s.stem + f.ext) if f.ext else s.with_name(s.stem), first=2)


def parse_range(text: str, n: int) -> list:
    """`3-12`·`1,4,7-9`(1부터) → 0부터 쪽 목록(차례대로, 겹침 없음). 틀리면 ValueError."""
    out = []
    for part in str(text or "").replace(" ", "").split(","):
        if not part:
            continue
        a, sep, b = part.partition("-")
        lo = int(a); hi = int(b) if sep else lo
        if lo > hi:
            lo, hi = hi, lo
        if lo < 1 or hi > n:
            raise ValueError(part)
        out.extend(range(lo - 1, hi))
    seen, res = set(), []
    for p in out:
        if p not in seen:
            seen.add(p); res.append(p)
    if not res:
        raise ValueError(text)
    return res


def run(src, key: str, pages=None, *, fixes=None, forced_pages=(), progress=None) -> Path:
    """한 파일을 변환해 결과 경로를 돌려준다. 배경 스레드에서 부른다."""
    from viewer.convert import writers
    from viewer.convert.source import PageSource
    dst = out_path(src, key)

    def tick(i, n, label=""):
        if progress is not None and progress(i, n, label) is False:
            raise Cancelled()

    with PageSource(src, fixes=fixes, forced_pages=forced_pages) as ps:
        pg = list(pages) if pages else list(range(ps.page_count))
        try:
            writers.WRITERS[key](ps, pg, dst, tick)
        except BaseException:
            _remove(dst)
            raise
    return dst


def _remove(p: Path) -> None:
    """만들다 만 결과를 지운다(취소·실패). 이미지 폴더는 통째로."""
    import shutil
    try:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            os.remove(p)
    except Exception:
        pass
