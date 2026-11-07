# -*- coding: utf-8 -*-
"""단어장 단어 밑줄 — 색·투명도·자리 한 곳(261107-33, 화면 디자인 SOT §2.6 · 단어장 SOT §11.2).

본문(`MainView._draw_vocab_marks`)과 발표 보기가 같은 함수(`vocab_mark_line`)로 긋는다.
Qt 위젯은 쓰지 않는다(QColor 만).
"""
from __future__ import annotations

from PyQt6.QtGui import QColor

VOCAB_MARK_COLOR = "#00897B"        # 미정(수준을 모르는 단어) — 261103-4 의 한 색
VOCAB_MARK_COLORS = {               # 수준별(테마 무관 — 본문 종이는 늘 흰색)
    "초급": "#E6A100",
    "중급": "#2E7D32",
    "고급": "#D81B60",
    "전문용어": "#1565C0",
}
VOCAB_MARK_ALPHA = 153              # 60 % — 밑줄이 글자·다른 강조를 가리지 않게
VOCAB_MARK_GAP_PX = 1.0             # 낱말 상자 아래 끝과 밑줄 사이 틈(화면 px)


def mark_color(level=None) -> QColor:
    col = QColor(VOCAB_MARK_COLORS.get(level or "", VOCAB_MARK_COLOR))
    col.setAlpha(VOCAB_MARK_ALPHA)
    return col


def vocab_mark_line(x0, y0, x1, y1, px_per_pt, level=None):
    """낱말 상자(pt) + 화면 px/pt 배율 → (색(알파 포함), (lx0, ly, lx1, ly) 화면 px, 굵기 px).

    선은 상자 **바로 아래** — 상자 안쪽에 그으면 잉크에 꼭 맞는 OCR 상자에서 글자 아랫부분을 덮는다."""
    z = float(px_per_pt or 1.0)
    w = max(1.5, min(3.0, (y1 - y0) * z * 0.08))
    y = y1 * z + VOCAB_MARK_GAP_PX + w / 2
    return mark_color(level), (x0 * z, y, x1 * z, y), w
