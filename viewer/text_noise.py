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
  - `study/ocr.py` — OCR 결과의 단어·본문(단어학습 SOT §14.6) → 단어장·검색까지 함께 깨끗해진다

**적용 범위**: 보이지 않는 OCR 글자층·OCR 결과에만 쓴다. **사람이 넣은 글자(일반 PDF)에는
쓰지 않는다** — 작은 글씨도 기호도 뜻이 있다.
"""
from __future__ import annotations

MIN_H_PT = 4.0       # 글자 상자 높이가 이보다 낮으면 글자가 아니다(A4 에서 약 1.4mm)
THIN = 0.12          # 한 글자인데 폭이 높이의 이 비율 미만(또는 그 반대)이면 글자가 아니다
MIN_CONF = 0.30      # OCR 이 스스로 이만큼도 확신하지 못한 낱말은 버린다
# 261101-1(SOT §3.5.3): 신뢰도가 낮아도 **영어 사전에 이만큼(zipf) 흔한 낱말**이면 남긴다.
#   실측 HM 4쪽 — 버려진 사전 낱말 `What's`(3.8 이상)·`they're`·`shouldn't`·`raise` 는 모두 3 이상, 잡음 조각은 사전에 없다.
KEEP_ZIPF = 3.0
# 문장 속 `|` 를 `I` 로 볼 상자 높이(그 줄 낱말 높이 중앙값의 배). 실측 `I`·`|` 29px / 줄 중앙 29~33px.
BAR_I_LO, BAR_I_HI = 0.6, 1.6


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


def known_word(surface) -> bool:
    """라틴 글자 낱말이 영어 빈도 사전에 있는가 (텍스트 창 SOT §3.5.3, 261101-1).

    문장부호·따옴표를 떼고 `’` 는 `'` 로 본다. `—`·`–` 로 이어진 것(`Wait—I`)은 조각마다 본다.
    한글·숫자가 섞이면 False — 한글 잡음이 사전 낱말로 살아나면 안 된다. 사전을 못 쓰면 False(종전대로)."""
    import re
    t = str(surface or "").strip().replace("’", "'").replace("‘", "'")
    parts = [p.strip("\"'“”‘’.,;:!?()[]…*") for p in re.split(r"[—–]", t)]
    parts = [p for p in parts if p]
    if not parts:
        return False
    try:
        from viewer.study.wordfreq_fast import zipf_frequency
    except Exception:
        return False
    for p in parts:
        if not re.fullmatch(r"[A-Za-z]+(?:'[A-Za-z]+)?", p):
            return False
        if (len(p) < 2 and p not in ("I", "a", "A")) or zipf_frequency(p.lower(), "en") < KEEP_ZIPF:
            return False
    return True


def bar_as_i(prev, cur, nxt, line_h: float) -> bool:
    """문장 속 `|` 를 `I` 로 볼까 (텍스트 창 SOT §3.5.3, 261101-1).

    Tesseract 는 세리프 `I` 를 `|` 로 읽는다(HM 4쪽: `I` 63개 중 5개). `prev`·`nxt` 는 **같은 줄**의 바로 앞뒤
    낱말 글자, `cur` 는 `(글자, 상자 높이)`, `line_h` 는 그 줄 낱말 높이의 중앙값이다.
    `I` 로 읽힌 것도 같은 조건이면 참 — 부르는 쪽이 ③(홀쭉한 한 글자)으로 버리지 않게 한다(획이 1px 인 `I` 3개)."""
    s, h = cur
    if str(s or "").strip() not in ("|", "I") or line_h <= 0:
        return False
    if not (BAR_I_LO <= float(h) / float(line_h) <= BAR_I_HI):
        return False
    lat = lambda t: any("A" <= c <= "z" and c.isalpha() for c in str(t or ""))    # noqa: E731
    return lat(prev) and lat(nxt)


def keep_ocr_word(surface, x0, y0, x1, y1, conf, *, scale: float = 1.0,
                  min_conf: float = MIN_CONF) -> bool:
    """OCR 낱말 하나를 남길지. 좌표는 픽셀이어도 되고 `scale` 로 pt 로 환산한다.

    `scale = 72 / dpi` (300dpi 면 0.24). 신뢰도가 낮은 낱말도 함께 버린다 —
    티를 글자로 읽을 때 Tesseract 의 conf 는 대체로 바닥이다.
    261101-1(SOT §3.5.3): 단 **영어 사전 낱말**은 신뢰도가 낮아도 남긴다 — 곧은 따옴표(`What's`)는
    conf 가 0 언저리로 나와 진짜 낱말이 사라지고 그 빈자리가 표 칸 구분(` | `)이 됐다. 모양(①③)은 그대로 본다.
    """
    if conf is not None and float(conf) < min_conf and not known_word(surface):
        return False
    if is_symbol_only(surface):
        return False
    return not is_noise_box(surface, float(x0) * scale, float(y0) * scale,
                            float(x1) * scale, float(y1) * scale)
