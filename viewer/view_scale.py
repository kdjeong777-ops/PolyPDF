"""261021-5(입력 SOT §3.2): 확대·축소 배율 — 쪽 썸네일 크기·책갈피창 글자·텍스트 창 글자.

값의 원본은 여기다. 배율은 설정 `view_scales`({종류: 배율}, 마스터 §8.2)에 기억한다.
본문 배율은 뷰어가 따로 갖는다(`MainView._zoom_by` — 한 번에 같은 `VIEW_SCALE_STEP`).
"""
from __future__ import annotations

VIEW_SCALE_MIN = 0.6
VIEW_SCALE_MAX = 3.0
VIEW_SCALE_STEP = 1.15
KINDS = ("thumb", "bookmark", "text")


def clamp(s) -> float:
    try:
        s = float(s)
    except (TypeError, ValueError):
        return 1.0
    if s != s:                                   # NaN
        return 1.0
    return round(max(VIEW_SCALE_MIN, min(VIEW_SCALE_MAX, s)), 3)


def step(s, direction: int) -> float:
    """`direction` +1 확대 / -1 축소 / 0 기본(1.0). 1.0 근처는 1.0 으로 붙인다(×1.15 ÷1.15 의 찌꺼기)."""
    if not direction:
        return 1.0
    v = clamp(clamp(s) * (VIEW_SCALE_STEP ** (1 if direction > 0 else -1)))
    return 1.0 if abs(v - 1.0) < 0.01 else v
