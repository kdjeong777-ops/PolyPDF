# -*- coding: utf-8 -*-
"""260908-5: 배경 작업의 **점유율 조절** (응답성 SOT §4 ⑦).

의무 ② 의 '파일마다 5ms 양보' 는 *간격* 만 정한다. 그 사이에 한 일이 2초면 배경 작업이
벽시계의 99.7% 를 차지하고, 메인 스레드는 GIL 을 얻는 순서를 기다리며 굶는다 —
창이 '응답 없음' 이 되지는 않아도(한 번의 정지는 1초 미만) **내내 굼뜨다**.
실측: 1.2GB 폴더 첫 인덱싱 100초 동안 20ms 하트비트가 **기대의 47% 만** 울렸다.

그래서 간격이 아니라 **비율**을 정한다. 방금 일한 시간에 비례해 쉰다 —
`duty=0.7` 이면 배경이 벽시계의 7할을 넘게 쓰지 않는다. 총 소요는 그만큼 늘지만,
사용자가 만지는 창이 계속 부드럽다(느린 것은 배경이지 창이 아니다).

C 호출 **한 번**이 오래 걸리는 것은 여기서 못 고친다 — 그것은 의무 ③ 의 몫이다.
"""
from __future__ import annotations

import time

BG_DUTY = 0.6            # 배경 작업이 차지해도 좋은 벽시계 비율 상한
MIN_SLEEP_S = 0.005      # 의무 ② 의 종전 값 — 이보다 덜 쉬지는 않는다
MAX_SLEEP_S = 0.25       # 한 번에 이보다 오래 쉬면 진행이 눈에 띄게 끊긴다


class Pacer:
    """`tick()` 을 일감 사이에 부른다. 지난 `tick()` 이후 일한 만큼 비례해 잠든다."""

    def __init__(self, duty: float = BG_DUTY,
                 min_s: float = MIN_SLEEP_S, max_s: float = MAX_SLEEP_S):
        self.duty = max(0.05, min(0.95, float(duty)))
        self.min_s = float(min_s)
        self.max_s = float(max_s)
        self._t = time.monotonic()

    def tick(self) -> float:
        """쉬고, 실제로 쉰 시간을 돌려준다(계측용)."""
        worked = max(0.0, time.monotonic() - self._t)
        rest = worked * (1.0 - self.duty) / self.duty
        rest = max(self.min_s, min(self.max_s, rest))
        time.sleep(rest)
        self._t = time.monotonic()
        return rest

    def reset(self) -> None:
        """오래 쉬었다 돌아왔을 때 — 그 공백을 '일한 시간' 으로 세지 않게."""
        self._t = time.monotonic()


def pace(obj) -> float:
    """워커 인스턴스 하나에 박자 하나 — `time.sleep(self.YIELD_S)` 를 대신한다.

    `YIELD_S = 0` 이면 쉬지 않는다(검사에서 배경 작업을 몰아 돌릴 때 쓰던 관례 유지).
    `BG_DUTY` 를 붙여 두면 그 작업만 다른 점유율을 쓸 수 있다.
    """
    y = getattr(obj, "YIELD_S", MIN_SLEEP_S)
    if not y:
        return 0.0
    p = getattr(obj, "_pacer", None)
    if p is None:
        p = obj._pacer = Pacer(getattr(obj, "BG_DUTY", BG_DUTY), min_s=y)
    return p.tick()
