"""전역 테마 상태(다크/라이트) — 위젯·픽스맵 렌더가 색을 맞추도록 공유 (260606-14)."""
from __future__ import annotations

_DARK = False


def set_dark(on: bool) -> None:
    global _DARK
    _DARK = bool(on)


def is_dark() -> bool:
    return _DARK
