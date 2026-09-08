# -*- coding: utf-8 -*-
"""260908-8: **'이건 글자가 아니다' 판정의 단일 표준** (텍스트 창 SOT §3.5).

스캔 PDF 는 그림 위에 보이지 않는 OCR 글자층을 얹는다. OCR 은 종이의 티·접힌 자국·표
괘선을 글자로 잘못 읽어 그 자리에 남기고, 그것이 **텍스트 창·단어장·검색 색인·번역**까지
그대로 흘러간다. 사용자 보고(260908) 두 번이 모두 이 잡음이었다 —
`픔`·`똬` 같은 한 글자, 그리고 `■`·`☜` 같은 기호.

규칙을 여기 한곳에 둔다. 텍스트 창만 고치면 단어장·검색에는 같은 잡음이 남는다
(응답성 SOT §4.5 와 같은 이유 — 규칙이 흩어지면 한쪽만 낡는다).

**쓰는 곳**
  - `text_extract2` — 텍스트 창의 줄 목록(SOT §3.5)
  - `study/ocr.py` — OCR 결과의 단어·본문(단어학습 SOT §14.3) → 단어장·검색까지 함께 깨끗해진다

**적용 범위**: 보이지 않는 OCR 글자층·OCR 결과에만 쓴다. **사람이 넣은 글자(일반 PDF)에는
쓰지 않는다** — 작은 글씨도 기호도 뜻이 있다.
"""
from __future__ import annotations

MIN_H_PT = 4.0       # 글자 상자 높이가 이보다 낮으면 글자가 아니다(A4 에서 약 1.4mm)
THIN = 0.12          # 한 글자인데 폭이 높이의 이 비율 미만(또는 그 반대)이면 글자가 아니다
MIN_CONF = 0.30      # OCR 이 스스로 이만큼도 확신하지 못한 낱말은 버린다


def has_letter(text) -> bool:
    """글자(한글·한자·라틴)나 숫자가 하나라도 있는가."""
    for ch in (text or ""):
        if ch.isalnum():
            return True
    return False


def is_symbol_only(text) -> bool:
    """`■`·`☜`·`←` 처럼 **기호·문장부호만** 남은 것인가.

    사용자 보고(260908): "이상한 글자가 많이 없어졌는데 `■` 등은 아직 있어."
    크기로는 못 거른다 — `■` 는 16pt 로 본문만 하다. 내용으로 가른다.
    """
    t = (text or "").strip()
    return bool(t) and not has_letter(t)


def is_noise_box(text, x0, y0, x1, y1, *, min_h: float = MIN_H_PT,
                 thin: float = THIN) -> bool:
    """**모양으로** 거른다 — 낱말/조각 하나의 상자를 pt 단위로 받는다.

    ① 상자가 뒤집혔거나 납작하다 ② 높이가 `min_h` 미만 ③ 한 글자인데 홀쭉·납작하다
    (`l` 이 1pt × 54pt 로 잡히는 식).

    ※ 기호만 남은 것(`is_symbol_only`)은 여기서 보지 않는다 — 조각 단계에서 빼면
      `[ 제목 ]` 의 `]` 처럼 **옆 글자와 이어져야 할 것**까지 사라진다(260908-7 회귀).
      그 판정은 줄을 이은 **뒤에** 한다.
    """
    t = (text or "").strip()
    if not t:
        return True
    w, h = (x1 - x0), (y1 - y0)
    if w <= 0 or h <= 0:
        return True
    if h < min_h:
        return True
    if len(t) == 1 and (w < h * thin or h < w * thin):
        return True
    return False


def keep_ocr_word(surface, x0, y0, x1, y1, conf, *, scale: float = 1.0,
                  min_conf: float = MIN_CONF) -> bool:
    """OCR 낱말 하나를 남길지. 좌표는 픽셀이어도 되고 `scale` 로 pt 로 환산한다.

    `scale = 72 / dpi` (300dpi 면 0.24). 신뢰도가 낮은 낱말도 함께 버린다 —
    티를 글자로 읽을 때 Tesseract 의 conf 는 대체로 바닥이다.
    """
    if conf is not None and float(conf) < min_conf:
        return False
    if is_symbol_only(surface):
        return False
    return not is_noise_box(surface, float(x0) * scale, float(y0) * scale,
                            float(x1) * scale, float(y1) * scale)
