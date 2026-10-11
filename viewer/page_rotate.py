# -*- coding: utf-8 -*-
"""저장 전 회전 — 쪽 `/Rotate` 에 덧입힌다 (261011-2, 마스터 §4.7.16 '회전').

썸네일·본문 우클릭 90° 회전은 `page_meta.json` `rotation`(쪽 → 더할 각도)에 적는다 — 앱을 다시 켜도 남는 **저장 전 회전**이다.
`PdfDocument` 가 열 때 그 값을 열린 문서의 `/Rotate` 에 덧입혀(파일은 그대로) 본문·썸네일·발표가 PDF 회전으로 그리고,
💾 저장이 쪽 편집 저장 길(`page_edit_build.build(rotations=)`)로 원본에 넣는다. 저장 전 크롭(`page_crop` 의 `_PENDING`)과 같은 모양이다.

`page_meta` 는 열린 폴더에 있어 `PdfDocument` 가 찾지 못한다 — 앱이 `set_provider(경로 → {쪽: 각도})` 로 알려 준다.
Qt 를 쓰지 않는다(배경 작업·검사에서 그대로 부른다).
"""
from __future__ import annotations

import os

_PROVIDER = None
_VERSION: dict = {}


def _pkey(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def set_provider(fn) -> None:
    """fn(path) -> {쪽(원본 번호): 더할 각도} — 앱이 `page_meta` 로 알려 준다. None 이면 저장 전 회전 없음."""
    global _PROVIDER
    _PROVIDER = fn


def pending(path) -> dict:
    if not path or _PROVIDER is None:
        return {}
    try:
        got = _PROVIDER(str(path)) or {}
    except Exception:
        return {}
    return {int(p): int(d) % 360 for p, d in got.items() if int(d) % 360}


def has_pending(path) -> bool:
    return bool(pending(path))


def bump(path) -> None:
    """회전이 바뀌었다 — 캐시 태그가 옛 픽셀을 다시 쓰지 않게."""
    k = _pkey(path)
    _VERSION[k] = _VERSION.get(k, 0) + 1


def version(path) -> int:
    return _VERSION.get(_pkey(path), 0)


def rotate_page(page, delta: int) -> None:
    """쪽 하나의 `/Rotate` 에 더한다(90 의 배수)."""
    d = int(delta) % 360
    if d:
        page.set_rotation((int(page.rotation) + d) % 360)


def apply_pending(doc, path) -> int:
    """열린 문서(저장하지 않을 것)에 저장 전 회전을 덧입힌다. 덧입힌 쪽 수."""
    n = 0
    for p, d in pending(path).items():
        if 0 <= p < doc.page_count:
            rotate_page(doc[p], d)
            n += 1
    return n
