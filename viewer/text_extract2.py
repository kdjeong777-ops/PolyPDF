# -*- coding: utf-8 -*-
"""260908-2: 텍스트 창이 보여 줄 **쪽 → 줄 목록** (텍스트 창 SOT §3).

한 줄은 dict 다.
    {"text": 글, "style": "title"|"body", "rect": (x0,y0,x1,y1)|None, "kind": "text"|"table"}

- `rect` 는 PDF 좌표(pt). 본문 뷰어에 되비추는 데 쓴다(SOT §4 '텍스트 창에서 고른 줄을
  본문에서 강조'). OCR 폴백에는 좌표가 없으므로 None.
- 표는 **한 행을 한 줄**로 잇는다(SOT §3.3). 표와 겹치는 본문 줄은 뺀다 — 같은 글이 두 번
  나오면 읽기도 고치기도 헷갈린다.
- 제목/내용은 **그 쪽 글자 크기의 중앙값**으로 가른다(SOT §3.4). 평균은 큰 제목 하나에
  끌려가므로 쓰지 않는다.

유료 API 를 쓰지 않는다 — PyMuPDF 와 pdfplumber(좌표 기반)만으로 판단한다(SOT §1).
"""
from __future__ import annotations

import re

# 260908-8(SOT §3.4, 사용자 지시): 제목은 **크기가 많이 차이 날 때만**.
#   1.15 배는 너무 낮아 본문과 같은 크기의 굵은 줄까지 제목이 됐다(실측 지침 문서에서
#   `제4장 …` 같은 본문 크기 줄이 제목으로 잡혔다). 굵기(bold)는 **판정에 쓰지 않는다**.
TITLE_RATIO = 1.40          # 중앙값 대비 이 배 이상이어야 제목
TITLE_MIN_GAP_PT = 2.0      # 그리고 중앙값보다 이만큼(pt)은 커야 한다
# 260908-6(SOT §3.5): OCR 잡음으로 보는 글자 상자 높이(pt). A4 에서 4pt = 약 1.4mm 라
#   사람이 읽으라고 넣은 글자일 수 없다. 실측 잡음 1.4~3.4 / 진짜 글 5.3~27.9.
# 260908-8: 판정 본문은 `viewer/text_noise.py` 가 소유한다(텍스트 창·OCR·단어장 공용).
from viewer import text_noise as _noise          # noqa: E402
NOISE_MIN_H_PT = _noise.MIN_H_PT
# 260908-7(SOT §3.6): 같은 줄에 있는 조각을 하나로 잇는 기준.
ROW_OVERLAP = 0.55      # 세로로 이만큼 겹치면 '같은 줄'
GLUE_GAP = 0.25         # 글자크기 대비 이보다 좁으면 붙여 쓴다(라틴)
# 260909-2(SOT §3.6.2, 사용자 보고 "재생첨가제 → 재생점 가제"): 한글은 다르다.
#   Tesseract 가 한글을 **글자 하나하나 낱말로** 내놓는데, 그 글자 사이 간격이
#   0.25 언저리라 붙일지 띄울지가 글자마다 뒤집혔다. 실측(300dpi, 간격÷높이):
#   한 낱말 안 0.14~0.40 / 낱말 사이 0.50~0.94 → 경계를 0.45 로 둔다.
CJK_GLUE_GAP = 0.45
# 260916-1(SOT §3.6.12, 사용자 지시 '기준을 재검토해'): **한 값으로는 안 된다.**
#   `image_to_string` 의 띄어쓰기를 정답 삼아 표본 4종 9,980곳을 재 보니 문서마다
#   최적이 갈렸다 — 성격심리·심리검사 0.33 / 아스팔트지침 0.50 이상. 0.45 로 고정하면
#   앞의 두 문서에서 열 곳에 한 곳꼴로 틀린다(9.6%·11.9%).
#   그래서 **쪽마다 스스로 뽑는다**(`cjk_gap_threshold`) — 빈틈 분포는 '낱말 안' 과
#   '낱말 사이' 두 봉우리라, 그 골짜기를 오츠로 찾으면 문서가 달라져도 따라간다.
CJK_GLUE_MIN, CJK_GLUE_MAX = 0.25, 0.55   # 뽑은 값을 이 사이로 가둔다
CJK_GLUE_TOP = 1.0      # 이보다 넓은 빈틈은 칸 사이 — 문턱을 뽑을 때 뺀다
CJK_GLUE_MIN_N = 40     # 표본이 이보다 적으면 뽑지 않는다(기본값을 쓴다)
# 260909-3(사용자 보고 '숫자가 한 자씩 띄어 써진다'): 숫자도 마찬가지다 —
#   흐린 스캔에서는 Tesseract 가 숫자를 한 자씩 낱말로 내놓는다. 다만 **완전한 두 수**
#   (`3.9261` | `4.0065`)를 붙이면 안 되므로, **한쪽이 한 글자일 때만** 넓은 기준을 쓴다.
NUM_GLUE_GAP = 0.45
_NUM_CHARS = set('0123456789.,%')
# 260909-4(사용자 지시): OCR 이 숫자를 닮은 글자로 잘못 읽은 것도 되돌린다.
#   실측(배합설계 2쪽 글자층): `44 . O`·`O .5`·`1 OO.O`·`2026년O2월`.
#   **글자를 바꾸는 일**이라 조건을 좁게 건다 — §3.6.3.
_LOOKALIKE = {'O': '0', 'o': '0', 'l': '1', 'I': '1'}
_NUMRUN_CHARS = _NUM_CHARS | set(_LOOKALIKE) | {' '}
COL_GAP = 2.5           # 이보다 넓게 벌어지면 '다른 칸' — " | " 로 잇는다
CELL_SEP = " | "
# 261101-1(SOT §3.6.14): OCR 본문 쪽에서 ` | ` 가 든 줄이 이 비율 이하이면 빈자리로 본다(표본 조사: 본문 쪽 0.05~0.37,
#   표·서식 쪽은 대부분 행). 줄이 `PROSE_MIN_ROWS` 보다 적은 쪽은 판단하지 않는다.
PROSE_BAR_MAX = 0.40
PROSE_MIN_ROWS = 8
COL_ALIGN = 0.40        # 단으로 보려면 왼쪽 끝이 이 비율 이상 맞아야 한다
# 260910-8(SOT §3.6.4): 단 사이 빈 띠의 최소 폭(쪽 너비 대비).
#   실측 0.012~0.038 — 종전 0.04 는 **실제 2단 쪽을 하나도 통과시키지 못했다**.
COL_GUTTER_MIN = 0.015
# 본문 폭의 이 비율을 넘게 걸치는 **조각**은 전폭 줄(제목·머리띠·넓은 캡션)이다.
COL_FULL = 0.60
# 한쪽 단이 다른 쪽보다 이 비율보다 좁으면 **단이 아니라 값 칸**이다(목차의 쪽번호 등).
#   실측: 목차 0.06~0.09 / 진짜 2단 0.45~1.87.
COL_WIDTH_MIN = 0.25
COL_WIDE_SHARE = 0.5     # 261108-31(§3.6.4): 단 정렬·폭은 그 쪽 가장 넓은 조각의 이 비율 이상인 조각으로 잰다
# 260910-9(SOT §3.6.5): 표의 **가로 줄**로 행을 가른다. 그 행 안의 어느 칸이든
#   두 줄 이상이면 **칸 단위로** 읽는다 — 줄 단위로 이으면 칸끼리 뒤섞인다.
CELL_GAP = 6.0          # 칸 사이 가로 빈틈(pt). 이보다 벌어지면 다른 칸
CELL_GAP_H = 0.60       # 글자 높이의 이 비율도 넘어야 다른 칸(큰 제목 대비)
HRULE_SPAN = 0.50       # 본문 폭의 이 비율을 넘는 가로 줄만 '행 구분선'
TABLE_OMIT_FMT = "[표 {cols}열 × {rows}행]"
# 260913-2(SOT §3.5.2, 사용자 지시): 쪽 가장자의 **세로 띠**·머리말·꼬리말은
#   본문이 아니다. 실측(AASHTO 기준문 3쪽): 세로 띠는 바깥 여백 10% 안에
#   폭 1.4% · 3글자 이하 조각이 높이의 60~75% 에 걸쳐 88~113개 쌓여 있었다.
#   깨끗한 표본 4종에는 그런 조각이 **하나도 없다**.
SIDE_MARGIN = 0.10       # 쪽 폭의 이 비율 안(왼·오른 바깥)에 있어야 한다
SIDE_WIDTH = 0.03        # 그리고 이보다 좁아야 한다(쪽 폭 대비)
SIDE_CHARS = 4           # 글자 수도 이하
SIDE_MIN_N = 8           # 이만큼 모여 있고
SIDE_SPAN = 0.40         # 높이의 이만큼에 걸쳐 있어야 '띠' 다
HEAD_BAND = 0.08         # 위쪽 이 비율 안 → 머리말 후보
HEAD_EXT, FOOT_EXT = 0.12, 0.85   # 쪽의 맨 위·맨 아래 줄은 이 비율까지 머리말·꼬리말 후보로 본다(쪽 번호 모양일 때만, 261101-1)
EDGE_GAP_TOP = 0.4       # 그 줄이 바로 옆 줄과 줄 높이의 이 배 이상 떨어져 있어야 한다
HEAD_SLACK = 0.03       # 머리말 상자 아래끝은 띠보다 이만큼까지 내려와도 된다(큰 쪽 번호, 261101-1)
FOOT_BAND = 0.88         # 아랫쪽 이 비율 밖 → 꼬리말 후보
EDGE_GAP = 1.5           # 본문과 이만큼(줄 높이 배) 떨어져 있어야 한다
# 260913-2 보강(실측으로 본문을 잃어 좁혔다):
#   ① '세로 띠' 는 조각이 좁은 것만으로 부족하다 — **한 줄기에 모여** 있어야 한다.
#     그렇게 안 하면 쪽 왼쪽의 좁은 표 칸(`구분`·`13mm`·`10mm`)까지 버렸다.
#   ② 머리말·꼬리말은 자리만으로 가를 수 없다 — **옆 쪽에도 같은 것이 있어야** 한다.
#     자리로만 가르니 단 마지막 줄(`demanding conditions.`)까지 꼬리말로 봤다.
SIDE_SPREAD = 0.02       # 띠 조각들이 차지하는 가로 폭이 이 이내여야 '한 줄기'
SIDE_VLINE_CHARS = 10    # 261108-31(§3.5.2 (가-2)): 세로로 쓴 한 줄 — 이만큼 글자가 있어야(가로 줄이 이렇게 좁고 길 수 없다)
#   실측: 진짜 세로 띠 **0.014~0.015** / 쪽 가장자의 표 칸 **0.024~0.059**.
#   사이가 넉넉해 0.02 로 둔다 — 표 칸을 버리면 본문을 잃는다.
EDGE_PEERS = 2           # 옆 쪽 이만큼을 둘러본다
EDGE_SIM = 0.70          # 빈칸을 뺀 **순서 유사도**가 이만큼이면 '되풀이되는 것'
# 261101-1(SOT §3.5.2): 쪽 번호를 단 줄이 이만큼 이하의 낱말이면 옆 쪽을 못 봐도 머리말·꼬리말로 본다
#   (`PROJECT HAIL MARY 5` 4개 · `Page 3 of 12` 는 끝이 쪽 번호라 4개 · 성격심리 `300 제12장 머레이의 욕구및 동기 이론` 6개 —
#   띄어쓰기 하나로 7개가 되므로 8). 본문 첫 줄은 띠 밖이거나 본문과 붙어 있어 묻지 않는다.
EDGE_NUM_WORDS = 8
EDGE_NUM_OFFSET = 50     # 인쇄된 쪽 번호와 PDF 쪽 순서의 차이 상한(앞붙이) — 넘으면 쪽 번호가 아니라 본문의 수(차례 항목)
EDGE_GAP_NUM = 1.0      # 쪽 번호를 단 줄은 본문과 줄 높이 이만큼만 떨어져도 머리말·꼬리말 후보(표본 조사: 성격심리 1.1~1.3배)
# 260913-4(SOT §3.5.2, 사용자 보고 "AASHTO 하단이 반복되는데 꼬리말로 인식 못한다"):
#   종전에는 **같은 자리의 글자끼리** 견줬다(0.60). OCR 이 쪽마다 한 글자만 더 읽어도
#   그 뒤가 전부 밀려 같은 꼬리말이 0.10~0.36 이 됐다. 순서 유사도로는 0.73~0.95.
#   실측(표본 10종 각 30쪽): 새로 버린 것은 모두 꼬리말, 종전에 버리던 것은 그대로.
# 260911-1(SOT §3.6.10): 글자층에 **빈칸이 아예 없는** PDF — 글자 자리로 띄어쓰기를 되살린다.
#   아래아한글에서 내보낸 보고서가 빈칸 글자를 아예 넣지 않았다(사용자 보고).
#   실측(빈틈÷글자크기): 한 낱말 안 0.05 / 낱말 사이 0.49~0.55 — 열 배 차이다.
SPACE_GAP = 0.25
# 그 줄의 빈틈 중 후보가 이 비율을 넘으면 **자간 벌리기**(균등분할)다 — 손대지 않는다.
SPACE_DENSE = 0.80
_SPACE_NO_BEFORE = set("%)]}>,.·…~’”」』、。!?;:")
_SPACE_NO_AFTER = set("([{<‘“「『")
# 260912-2(SOT §3.6.10 ②): **뒤 글자에 덮인 빈칸**은 지운다. 구글 번역본 PDF 가
#   낱말 사이에 NBSP 를 **두 개** 찍는데, 실측하면 둘째 것의 자리(105.09~106.96)를
#   다음 글자가 그대로 덮는다(105.09~112.78) — 종이에는 빈칸이 **하나만** 보인다.
#   그대로 두면 텍스트 창·단어장·읽기가 모두 `조지아  교통부의` 로 두 칸이 된다.
SPACE_COVERED = 0.5     # 뒤 글자가 이만큼(pt) 안으로 파고들면 그 빈칸은 없는 것
# 260912-2(SOT §3.6.10 ③): `\xa0`(줄바꿈 없는 빈칸) 같은 것도 **빈칸이다**.
#   구글 번역본 PDF 가 낱말 사이를 전부 NBSP 로 찍는데, 아래 규칙들은 하나같이
#   보통 빈칸(`' '`)을 찾는다 — §3.7 의 '원문이 빈칸으로 끝났는가'(`endswith(' ')`)가
#   언제나 거짓이 되어 `성공에` + `힘입어` 가 `성공에힘입어` 로 붙었다.
_SPACE_LIKE = {"\u00a0", "\u2007", "\u202f", "\u2009", "\u200a", "\ufeff"}


def _drop_covered_spaces(chars):
    """뒤 글자가 덮어 버린 빈칸을 뺀다 (SOT §3.6.10 ②).

    빈칸 글자의 자리를 **다음 글자가 파고들면** 그 빈칸은 종이에 나타나지 않는다.
    자리를 재서 아는 것이라 글자를 보고 짐작하지 않는다 — 일부러 넣은 두 칸
    (`제1장 총  칙`)은 서로 겹치지 않으므로 그대로 남는다.
    """
    if len(chars) < 2:
        return chars
    out = []
    for i, cur in enumerate(chars):
        c, bb, _sz = cur
        if c.isspace() and i + 1 < len(chars):
            nb = chars[i + 1][1]
            try:
                if float(nb[0]) <= float(bb[0]) + SPACE_COVERED:
                    continue                 # 다음 글자가 이 빈칸을 덮는다
            except Exception:
                pass
        out.append(cur)
    return out


def _restore_spaces(chars) -> str:
    """글자 사이 빈틈으로 **지워진 띄어쓰기**를 되살린다(SOT §3.6.10).

    `chars` 는 `[(글자, bbox, 글자크기)]`. 반환값은 빈칸을 돌려놓은 줄 글이다.
    둘 다 손대지 않는 경우가 있다 — 후보가 하나도 없거나, 거꾸로 많아서
    (`SPACE_DENSE`) **자간을 벌린 줄**로 보일 때다.
    """
    raw = "".join(c[0] for c in chars)
    if len(chars) < 2:
        return raw
    cand = []
    holes = 0
    for i in range(1, len(chars)):
        c, bb, size = chars[i]
        pc, pbb, psize = chars[i - 1]
        if not c.strip() or not pc.strip():      # 이미 빈칸이 있는 자리
            continue
        holes += 1
        ref = max(float(size or 0), float(psize or 0))
        if ref <= 0:
            continue
        if float(bb[0]) - float(pbb[2]) < SPACE_GAP * ref:
            continue
        if c in _SPACE_NO_BEFORE or pc in _SPACE_NO_AFTER:
            continue
        cand.append(i)
    if not cand:
        return raw
    if holes and len(cand) / holes >= SPACE_DENSE:
        return raw                               # 자간 벌리기 — 낱말 경계가 아니다
    at = set(cand)
    out = []
    for i, (c, _bb, _sz) in enumerate(chars):
        if i in at:
            out.append(" ")
        out.append(c)
    return "".join(out)


def _line_text(ln, restore: bool) -> str:
    """줄 하나의 글. `restore` 면 글자 자리로 빈칸을 되살린다(§3.6.10).

    `rawdict` 의 span 에는 `text` 가 **없다** — 글자를 이어 만든다. 되살리기를
    건너뛰더라도 글 자체는 돌려줘야 한다(안 그랬다가 OCR 층 쪽이 통째로 빈
    줄이 됐다 — 검사 2개가 잡았다).

    가로쓰기 줄만 되살린다 — 세로쓰기·돌린 줄은 가로 빈틈이 뜻을 잃는다."""
    spans = ln.get("spans", []) or []
    chars = []
    plain = []
    for sp in spans:
        t = sp.get("text")
        if t:
            for _sl in _SPACE_LIKE:               # §3.6.10 ③
                if _sl in t:
                    t = t.replace(_sl, " ")
            plain.append(t)
        size = float(sp.get("size", 0) or 0)
        for ch in sp.get("chars", []) or []:
            c = ch.get("c", "")
            if c in _SPACE_LIKE:                  # §3.6.10 ③
                c = " "
            if not t:
                plain.append(c)
            chars.append((c, ch.get("bbox") or (0, 0, 0, 0), size))
    chars = _drop_covered_spaces(chars)
    flat = "".join(c for c, _b, _s in chars) if chars else "".join(plain)
    if not restore or not chars:
        return flat
    if int(ln.get("wmode", 0) or 0) != 0:
        return flat
    d = ln.get("dir") or (1, 0)
    try:
        if abs(float(d[0]) - 1.0) > 1e-6 or abs(float(d[1])) > 1e-6:
            return flat
    except Exception:
        return flat
    return _restore_spaces(chars)


def _is_ocr_layer(page) -> bool:
    """이 쪽의 글자가 **보이지 않는 OCR 층**인가(SOT §3.5).

    스캔본은 그림 위에 render mode 3(보이지 않음)으로 글자를 얹는다. 그 층에는 OCR 이
    종이의 티를 글자로 잘못 읽은 것이 섞여 있어, 잡음 거르기는 **이런 쪽에만** 한다 —
    사람이 넣은 작은 글씨를 지우면 안 된다.
    261114-11(SOT §3.5): 내용 흐름에 `3 Tr` 가 없으면(`no_invisible_text`) 쪽을 돌려 보지 않고 '아니다'."""
    if no_invisible_text(page):
        return False
    try:
        traces = page.get_texttrace()
    except Exception:
        return False
    if not traces:
        return False
    inv = sum(1 for sp in traces if sp.get("type") == 3)
    return inv >= len(traces) * 0.9


import re as _re
_TR3_RE = _re.compile(rb"(?<![0-9.])3\s+Tr\b")


def no_invisible_text(page) -> bool:
    """render mode 3(안 보임) 글자가 **있을 수 없는** 쪽인가 — 내용 흐름에 `3 Tr` 가 없고 폼 XObject 도 없다(폼 안은 보지 않으므로 그때는 모른다).
    261114-11(SOT §3.5): 작은 그림 수만 개로 깐 쪽은 `get_texttrace` 한 번이 0.2~0.67초(TRB9.pdf) — 바이트 찾기는 0.1초 안. 모르면 False."""
    try:
        if page.get_xobjects():
            return False
        return _TR3_RE.search(page.read_contents() or b"") is None
    except Exception:
        return False


def text_dict(page, raw: bool = True, **kw) -> dict:
    """글·글자 자리만 쓰는 `get_text("rawdict"|"dict")` — **그림을 풀지 않는다** (261107-19, 응답성 SOT §6).

    기본 플래그(`TEXT_PRESERVE_IMAGES`)는 쪽의 그림을 모두 풀어 블록에 담는다 — 그림 전용 PDF(가상 프린터·사진→PDF)에서
    쪽당 0.8~1.4초였고, 그림을 빼면 0~1ms. 나머지 기본 플래그는 그대로라 글 블록은 같다. 그림 블록이 필요하면 `get_image_info`."""
    import fitz
    base = fitz.TEXTFLAGS_RAWDICT if raw else fitz.TEXTFLAGS_DICT
    return page.get_text("rawdict" if raw else "dict", flags=base & ~fitz.TEXT_PRESERVE_IMAGES, **kw)


def _line_items(page, edges_out=None):
    """PyMuPDF 줄 → [(rect, 글, 대표크기)] — 빈 줄 제외, 블록 읽기 순서.

    260908-6(SOT §3.5): 보이지 않는 OCR 층인 쪽에서는 **글자라고 볼 수 없이 작은 줄**을
    뺀다. 반환값에 잡음 수를 곁들이지 않고, 부르는 쪽이 필요하면 `last_noise_count()` 로 본다.
    """
    # 260911-1(SOT §3.6.10): 글자 자리는 `dict` 에 없다 — `rawdict` 라야 `span["chars"]`
    #   가 따라온다. 표본 6종 14,163줄로 두 방식의 글이 같음을 확인했고, 빨라졌으면
    #   빨라졌지 느려지지는 않는다(13.3 → 10.7 ms/쪽). 안 되면 `dict` 로 물러선다.
    raw = True
    try:
        d = text_dict(page)
    except Exception:
        raw = False
        try:
            d = text_dict(page, raw=False)
        except Exception:
            return []
    ocr_layer = _is_ocr_layer(page)
    # OCR 글자층은 자리가 고르지 않고 이미 §3.6.2 의 낱말 규칙이 돌고 있다 — 겹치면 망가진다.
    restore = raw and not ocr_layer
    noise = 0
    blocks = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:                  # 0=텍스트
            continue
        lines = []
        for ln in b.get("lines", []):
            spans = ln.get("spans", []) or []
            txt = _line_text(ln, restore)
            if not txt.strip():
                continue
            # 261108-31(SOT §3.7.16): 글머리표 한 글자뿐인 조각(`•` 12pt + 본문 8.8pt)은 크기에서 뺀다 — 그 줄만 커 보여
            #   ⑧(글자 크기)이 항목의 둘째 줄을 막았다(NAPA 6쪽 40곳). 다른 조각이 없으면 그대로.
            _sz = [sp for sp in spans if not _MARK_ONLY.match(
                sp.get("text") or "".join(str(c.get("c") or "") for c in (sp.get("chars") or [])))] or spans
            size = max((float(sp.get("size", 0) or 0) for sp in _sz), default=0.0)
            x0, y0, x1, y1 = ln.get("bbox", (0, 0, 0, 0))
            if x1 <= x0 or y1 <= y0:            # 뒤집히거나 납작한 상자 — 글자가 아니다
                noise += 1
                continue
            if ocr_layer and _noise.is_noise_box(txt, x0, y0, x1, y1):
                noise += 1
                continue
            lines.append(((x0, y0, x1, y1), txt, size))
        if lines:
            bb = b.get("bbox", (0, 0, 0, 0))
            blocks.append((bb, lines))
    if not blocks:
        return []
    # 읽기 순서: 번역·요약과 같은 규칙(2단이면 좌측 먼저)
    try:
        from viewer.study.pdf_extract import _order_reading
        packed = [(bb[0], bb[1], bb[2], bb[3], "") for bb, _l in blocks]
        order = _order_reading(packed, page.rect)
        index = {(round(p[0], 2), round(p[1], 2)): i for i, p in enumerate(order)}
        blocks.sort(key=lambda t: index.get((round(t[0][0], 2), round(t[0][1], 2)), 1 << 30))
    except Exception:
        blocks.sort(key=lambda t: (t[0][1], t[0][0]))
    # 260908-7(SOT §3.6): 조각을 **같은 줄끼리 이어 붙인다**.
    #   PyMuPDF 는 가로로 벌어진 글을 각각 다른 `line` 으로 준다. 그대로 두면
    #   `[ Hot Asphalt Paving Mixture` 와 `]` 가 두 줄이 되고, 표 한 행의 칸들이
    #   블록 순서대로 흩어져 **앞뒤가 바뀐 여러 줄**로 보인다(사용자 보고 260908).
    out = []
    # 260913-2(SOT §3.5.2, 사용자 지시): 세로 띠·머리말·꼬리말은 **잇기 전에** 버린다.
    #   잇고 나면 세로 띠 조각이 본문 줄에 `|` 로 붙어 떼어낼 수 없다
    #   (실측: `낡쥰~ | Fracture and Damage…`). 판정은 **쪽 전체**를 보고 한다 —
    #   띠는 블록을 가로질러 흩어져 있어 블록마다 따로 보면 못 찾는다.
    _all = [f for _bb, lns in blocks for f in lns]
    if edges_out is None:
        _keep, _dropped = drop_edge_frags(_all, page)
    else:
        # 261014-15(§3.5.2, 형식 변환 SOT §1.1): 버리는 머리말·꼬리말을 따로 돌려준다 — 판정은 같고 나눠 부를 뿐이다
        _k1, _d1 = drop_edge_frags(_all, page, edge=False)
        _keep, _d2 = drop_edge_frags(_k1, page, side=False)
        _dropped = _d1 + _d2
        if _d2:
            _ok2 = {id(f) for f in _keep}
            edges_out.extend(edge_rows([f for f in _k1 if id(f) not in _ok2], page))
    if _dropped:
        _ok = {id(f) for f in _keep}
        _nb = []
        for _bb, _lns in blocks:
            _l2 = [f for f in _lns if id(f) in _ok]
            if _l2:
                _nb.append((_bb, _l2))
        if _nb:
            blocks = _nb
            noise += _dropped
    # 260910-9(SOT §3.6.5): 가로 줄로 나뉜 표에 **여러 줄짜리 칸**이 있으면 칸 단위로.
    _flat = [f for _bb, lines in blocks for f in lines]
    _cells = _table_cells(_flat, page)
    for col_frags in (_cells if _cells is not None else _by_column(blocks, page)):
        out.extend(_merge_rows(col_frags))
    if ocr_layer:
        # 260908-8(SOT §3.5): **줄을 이은 뒤에** 기호만 남은 줄을 뺀다(`■`·`☜`).
        #   조각 단계에서 빼면 `[ 제목 ]` 의 `]` 처럼 이어져야 할 것까지 사라진다.
        kept = [it for it in out if not _noise.is_symbol_only(it[1])]
        noise += len(out) - len(kept)
        out = kept
    _NOISE["n"] = noise
    return out


def drop_edge_frags(frags, page, *, side: bool = True, edge: bool = True,
                    peers=None, ocr: bool = False):
    """세로 띠·머리말·꼬리말 조각을 버린다 → `(남은 조각, 버린 수)` (SOT §3.5.2).

    `ocr=True`(OCR 낱말로 만든 줄): 쪽 번호 모양 줄의 완화(본문과 `EDGE_GAP_NUM`, 쪽의 맨 위·맨 아래 줄)를 함께 건다 —
    글자층은 되풀이 판정이 잘 듣고, 합성 검사의 첫 줄 `line 0 of page 1` 이 쪽 번호 머리말로 지워졌다(261101-1).

    사용자 지시: *"세로 띠, 상단부 머리말, 하단부 꼬리말 등은 텍스트 창에서 제외"*.

    **잇는 순서가 중요하다** — 버리는 일이라 잇기 전에 해야 한다(§3.A 2단계).
    잇고 나면 세로 띠 조각이 본문 줄에 `|` 로 붙어 떼어낼 수 없다
    (실측: `낡쥰~ | Fracture and Damage…`).

    260913-4: OCR **낱말**로 만든 줄은 두 번에 나눠 부른다(§3.5.2) — 세로 띠는 낱말 단계에서
    (`edge=False`), 머리말·꼬리말은 줄을 이은 뒤 줄 단위로(`side=False`). `peers` 는 옆 쪽의
    글자층 말고도 **더 볼 글**(옆 쪽 OCR 줄)이다.
    """
    if not frags:
        return frags, 0
    try:
        pw, ph = float(page.rect.width), float(page.rect.height)
    except Exception:
        return frags, 0
    if pw <= 0 or ph <= 0:
        return frags, 0
    heights = sorted(max(1e-6, r[3] - r[1]) for r, _t, _s in frags)
    lh = heights[len(heights) // 2] if heights else 0.0

    # (가) 세로 띠 — 바깥 여백의 좁고 짧은 조각이 높이 대부분에 쌓인 것
    do_side, do_edge = bool(side), bool(edge)
    side = set()
    for lo, hi in (((0.0, SIDE_MARGIN), (1.0 - SIDE_MARGIN, 1.0)) if do_side else ()):
        cand = []
        for i, (r, t, _s) in enumerate(frags):
            if (r[0] / pw) >= lo and (r[2] / pw) <= hi \
                    and (r[2] - r[0]) <= pw * SIDE_WIDTH \
                    and len(t.strip()) <= SIDE_CHARS:
                cand.append(i)
        if len(cand) < SIDE_MIN_N:
            continue
        ys = [frags[i][0][1] / ph for i in cand] + [frags[i][0][3] / ph for i in cand]
        xs = [frags[i][0][0] / pw for i in cand] + [frags[i][0][2] / pw for i in cand]
        # **한 줄기**여야 한다 — 가로로 퍼져 있으면 표 칸이지 띠가 아니다(실측)
        if (max(ys) - min(ys)) >= SIDE_SPAN and (max(xs) - min(xs)) <= SIDE_SPREAD:
            side.update(cand)
    # (가-2) 261108-31(SOT §3.5.2·§3.7.16): **세로로 쓴 한 줄**(돌린 글 — 논문 왼쪽 가장자리의 `Downloaded from …`) — 조각 하나가
    #   바깥 여백에서 좁고 쪽 높이의 `SIDE_SPAN` 넘게 길다. (가) 는 짧은 조각이 여럿 쌓인 띠(스캔 OCR)만 보아 이 꼴을 못 잡았고,
    #   그 키 큰 상자가 같은 높이의 모든 본문 줄을 한 줄로 끌어 모았다(cao 1쪽 — 2단 본문 60줄이 한 줄 3,234자).
    if do_side:
        for i, (r, t, _s) in enumerate(frags):
            if i in side:
                continue
            w, h = r[2] - r[0], r[3] - r[1]
            outer = (r[2] / pw) <= SIDE_MARGIN or (r[0] / pw) >= 1.0 - SIDE_MARGIN
            if outer and w <= pw * SIDE_WIDTH and h >= ph * SIDE_SPAN and len(t.strip()) >= SIDE_VLINE_CHARS:
                side.add(i)

    rest = [i for i in range(len(frags)) if i not in side]
    if not rest:
        return frags, 0                      # 다 버릴 일은 없다 — 그대로 둔다

    # (나) 머리말·꼬리말 — 위·아래 띠에 있고 본문과 **떨어져** 있어야 한다
    ys0 = sorted(frags[i][0][1] for i in rest)
    ys1 = sorted(frags[i][0][3] for i in rest)
    edge = set()
    body = [i for i in rest
            if HEAD_BAND < (frags[i][0][1] / ph) and (frags[i][0][1] / ph) < FOOT_BAND]

    # 261101-1(SOT §3.5.2): 쪽 번호 판정은 **같은 높이의 조각을 모은 한 줄**로 한다 — 띠에 걸친 표의 칸 하나(`100`)가
    #   쪽 번호로 보이지 않게.
    def _row_text(i):
        r = frags[i][0]
        same = [j for j in rest
                if min(r[3], frags[j][0][3]) - max(r[1], frags[j][0][1]) > 0.5 * min(r[3] - r[1], frags[j][0][3] - frags[j][0][1])]
        return " ".join(frags[j][1] for j in sorted(same, key=lambda j: frags[j][0][0]))
    try:
        _pg_no = int(page.number) + 1
    except Exception:
        _pg_no = 0
    # 261102-2(SOT §3.5.2): 목차 쪽의 첫·끝 항목(`3. 시험포장공법의 재료적 특성 43`)은 쪽 번호를 단 머리말 모양이지만 지우지 않는다
    _toc = {}

    def _page_number_row(i):
        t = _row_text(i)
        if not _page_number_line(t, _pg_no):
            return False
        from viewer.study.ocr_pages import toc_text_lines, _toc_numbered
        if "page" not in _toc:
            _toc["page"] = toc_text_lines(list({_row_text(j) for j in rest}))
        return not (_toc["page"] and _toc_numbered(t))
    pno = set()
    if body and do_edge:
        body_top = min(frags[i][0][1] for i in body)
        body_bot = max(frags[i][0][3] for i in body)
        for i in rest:
            r = frags[i][0]
            # 261101-1(표본 조사): 위끝이 띠 안이고 아래끝이 `HEAD_SLACK` 만큼까지 — 성격심리는 큰 쪽 번호(`300`) 때문에
            #   머리말 상자 아래끝이 8.2% 라 상자 **전체**를 띠 안에 요구하던 종전 판정에 6/11쪽이 걸리지 않았다.
            #   쪽 번호를 단 줄은 본문과 `EDGE_GAP_NUM` 줄 높이만 떨어져도 된다(성격심리 1.1~1.3배).
            in_head = (r[1] / ph) <= HEAD_BAND and (r[3] / ph) <= HEAD_BAND + HEAD_SLACK
            in_foot = (r[1] / ph) >= FOOT_BAND
            if not (in_head or in_foot):
                continue
            gap = (body_top - r[3]) if in_head else (r[1] - body_bot)
            if gap >= lh * EDGE_GAP:
                edge.add(i)
            elif ocr and gap >= lh * EDGE_GAP_NUM and _page_number_row(i):
                edge.add(i)
    # 261101-1(표본 조사, 심리검사의이해 12쪽 모두): 머리말 위끝이 8.3~8.6% 라 띠 밖이었고, 그래서 본문으로 잡혀 '본문과
    #   떨어짐' 도 잴 수 없었다. **쪽의 맨 위·맨 아래 줄**은 `HEAD_EXT`·`FOOT_EXT` 까지 보고, 쪽 번호 모양이며 바로 옆 줄과
    #   줄 높이의 `EDGE_GAP_TOP` 배 이상 떨어져 있으면 후보로 한다(같은 높이의 조각도 함께).
    if ocr and do_edge and len(rest) >= 3:
        def _same_row(i, j):
            a, b = frags[i][0], frags[j][0]
            return min(a[3], b[3]) - max(a[1], b[1]) > 0.5 * min(a[3] - a[1], b[3] - b[1])
        order = sorted(rest, key=lambda i: frags[i][0][1])
        for i, top in ((order[0], True), (max(rest, key=lambda i: frags[i][0][3]), False)):
            r = frags[i][0]
            if (top and r[1] / ph > HEAD_EXT) or (not top and r[1] / ph < FOOT_EXT):
                continue
            row = [j for j in rest if j == i or _same_row(i, j)]
            others = [frags[j][0] for j in rest if j not in row]
            if not others:
                continue
            gap = (min(o[1] for o in others if o[1] >= r[1]) - max(frags[j][0][3] for j in row)) if top else \
                  (min(frags[j][0][1] for j in row) - max(o[3] for o in others if o[3] <= r[3]))
            if gap >= lh * EDGE_GAP_TOP and _page_number_row(i):
                edge.update(row)

    # **되풀이되는가** — 머리말·꼬리말은 옆 쪽에도 거의 같은 글이 같은 자리에 있다.
    #   자리만으로 가르면 단의 마지막 줄까지 꼬리말로 본다(실측: `demanding conditions.`).
    if edge:
        seen = _edge_peer_texts(page)
        more = [_norm_edge(t) for t in (peers or []) if str(t or "").strip()]
        # 261101-1(SOT §3.5.2): **쪽 번호를 단 짧은 줄**은 옆 쪽을 못 봐도(두 쪽만 OCR 한 상태) 머리말·꼬리말이다 —
        #   되풀이를 확인할 길이 없어 `4 ANDY WEIR`·`PROVECGCT HAIL MARY 5` 가 남아 본문 첫 줄에 붙었다.
        pno = {i for i in edge if _page_number_row(i)}
        if seen is None and not more:
            edge = pno                       # 옆 쪽을 못 보면 쪽 번호 모양만 버린다
        else:
            allp = list(seen or []) + more
            edge = {i for i in edge if i in pno or _looks_repeated(frags[i][1], allp)}

    drop = side | edge
    if len(drop) >= len(frags):
        return frags, 0
    return [f for i, f in enumerate(frags) if i not in drop], len(drop)


def edge_rows(frags, page) -> list:
    """버린 머리말·꼬리말 조각 → 줄 `{text, rect, size, where, pieces}` (261014-15, 형식 변환 SOT §1.1).

    같은 높이의 조각을 한 줄로 모으고, 줄 안에서 크게 떨어진 조각(왼쪽 제목·오른쪽 쪽 번호)은 `pieces` 에
    자리째 남긴다. `where` 는 쪽의 위 절반이면 "head", 아니면 "foot"."""
    try:
        ph = float(page.rect.height)
    except Exception:
        ph = 0.0
    items = []
    for r, t, sz in sorted(frags, key=lambda f: ((f[0][1] + f[0][3]) / 2, f[0][0])):
        cy = (r[1] + r[3]) / 2
        for it in items:
            if abs(it["cy"] - cy) <= max(2.0, 0.5 * (r[3] - r[1])):
                it["parts"].append((r, str(t).replace(" | ", "  "), sz))
                break
        else:
            items.append({"cy": cy, "parts": [(r, str(t).replace(" | ", "  "), sz)]})
    out = []
    for it in items:
        parts = sorted(it["parts"], key=lambda q: q[0][0])
        size = max(float(q[2] or 0) for q in parts) or (parts[0][0][3] - parts[0][0][1]) / 1.25
        pieces = []
        for r, t, _sz in parts:
            if pieces and r[0] - pieces[-1][1] <= size * 1.5:      # 이어진 조각 — 빈칸 하나로
                x0, _x1, tt = pieces[-1]
                pieces[-1] = (x0, r[2], tt + " " + t.strip())
            else:
                pieces.append((r[0], r[2], t.strip()))
        rect = (min(q[0][0] for q in parts), min(q[0][1] for q in parts),
                max(q[0][2] for q in parts), max(q[0][3] for q in parts))
        out.append({"text": "  ".join(p[2] for p in pieces), "rect": rect, "size": size,
                    "where": "head" if (not ph or it["cy"] < ph / 2) else "foot", "pieces": pieces})
    return out


# 아라비아(세 자리까지 — 네 자리는 `January 2025` 처럼 연도일 때가 많다)·소문자 로마 숫자
#   OCR 이 끝자리 `1` 을 `|`·`l`·`I` 로 읽은 것(`30|`)도 받는다(표본 조사)
#   괄호는 짝으로만 — `1)` 은 목록 번호다(NAPA 15쪽 `1) materials, 2) production, …` 이 꼬리말로 지워졌다)
_PN = r"(\d{1,2}[\d|lI]?|(?=[ivx])x{0,3}(?:ix|iv|v?i{0,3}))"
_PAGE_NO = re.compile(r"^(?:[-–—]?" + _PN + r"[-–—]?|\(" + _PN + r"\)|\[" + _PN + r"\])$")


def _page_number_line(t: str, page_no: int = 0) -> bool:
    """쪽 번호를 단 머리말·꼬리말 모양인가 — 낱말 `EDGE_NUM_WORDS` 개 이하이고 **맨 앞이나 맨 끝**이 쪽 번호
    (`4 ANDY WEIR` · `PROJECT HAIL MARY 5` · `- 12 -` · `iv`). 위·아래 띠에서 본문과 떨어진 줄에만 묻는다(§3.5.2).

    `page_no`(1부터) 를 주면 아라비아 숫자가 그 쪽 순서와 `EDGE_NUM_OFFSET` 안이어야 한다 — 차례 쪽 맨 아래 항목
    `1, 설리반의 생애 270`(12쪽)이 꼬리말로 지워졌다(표본 조사). 책은 앞붙이 때문에 인쇄 쪽 번호가 몇 쪽 어긋난다(HM 7)."""
    toks = [x for x in re.split(r"\s+", str(t or "").replace(CELL_SEP, " ").strip()) if x]
    if not toks or len(toks) > EDGE_NUM_WORDS:
        return False
    if len(toks) >= 3 and toks[0] in "-–—" and toks[-1] in "-–—":
        toks = toks[1:-1]                     # `- 12 -`
    for tk in (toks[0], toks[-1]):
        m = _PAGE_NO.match(tk)
        if not m:
            continue
        num = re.sub(r"[|lI]$", "1", next(g for g in m.groups() if g))
        if page_no and num.isdigit() and abs(int(num) - int(page_no)) > EDGE_NUM_OFFSET:
            continue
        return True
    return False


def _norm_edge(t: str) -> str:
    """쪽 번호처럼 쪽마다 바뀌는 것은 지운 뒤 견준다(`- 10 -` 과 `- 11 -` 은 같은 꼬리말)."""
    return re.sub(r"[0-9IVXivx]+", "#", str(t or "")).strip()


def _looks_repeated(t: str, peers) -> bool:
    """옆 쪽에 비슷한 글이 있나 — 빈칸을 빼고 **순서 유사도**로 견준다(260913-4).

    OCR 은 같은 꼬리말도 `A A S H T O`·`AASHTO` 로 달리 띄우고 한두 글자를 더 읽는다.
    같은 자리의 글자끼리 견주면 그 뒤가 전부 밀려 '다른 글' 이 된다."""
    import difflib
    a = re.sub(r"\s+", "", _norm_edge(t))
    if len(a) < 2:
        return True                          # `i`·`3` 같은 쪽 번호 — 자리로 이미 걸렀다
    for b in peers:
        b = re.sub(r"\s+", "", str(b or ""))
        if not b:
            continue
        if a == b:
            return True
        # 길이가 크게 다르면 닮을 수 없다 — 긴 옆 쪽 글마다 비교를 치르지 않는다
        if min(len(a), len(b)) * 2 < max(len(a), len(b)):
            continue
        if difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= EDGE_SIM:
            return True
    return False


def _edge_peer_texts(page):
    """옆 쪽들의 **위·아래 띠** 글. 못 보면 None(그때는 버리지 않는다)."""
    try:
        doc = page.parent
        n = int(doc.page_count)
        cur = int(page.number)
    except Exception:
        return None
    out = []
    seen = 0
    for d in (-2, -1, 1, 2):
        k = cur + d
        if k < 0 or k >= n or seen >= EDGE_PEERS:
            continue
        try:
            pg = doc.load_page(k)
            ph2 = float(pg.rect.height)
            if ph2 <= 0:
                continue
            for b in text_dict(pg, raw=False).get("blocks", []):
                if b.get("type") != 0:
                    continue
                for ln in b.get("lines", []):
                    x0, y0, x1, y1 = ln.get("bbox", (0, 0, 0, 0))
                    if (y1 / ph2) <= HEAD_BAND or (y0 / ph2) >= FOOT_BAND:
                        t = "".join(sp.get("text", "") for sp in ln.get("spans", []))
                        if t.strip():
                            out.append(_norm_edge(t.strip()))
            seen += 1
        except Exception:
            continue
    return out if seen else None


def _row_bands(frags):
    """세로로 겹치는 조각끼리 묶는다 — [[조각…]] (같은 줄 후보)."""
    bands = []
    for f in sorted(frags, key=lambda f: (f[0][1], f[0][0])):
        rect = f[0]
        h = rect[3] - rect[1]
        for bd in bands:
            ov = min(rect[3], bd["y1"]) - max(rect[1], bd["y0"])
            if ov > 0 and ov >= ROW_OVERLAP * min(h, bd["y1"] - bd["y0"]):
                bd["items"].append(f)
                bd["y0"], bd["y1"] = min(bd["y0"], rect[1]), max(bd["y1"], rect[3])
                break
        else:
            bands.append({"y0": rect[1], "y1": rect[3], "items": [f]})
    return bands


def _gutter_x(bands, page, x0=None, x1=None):
    """2단 쪽의 **빈 세로 띠**(단 사이 여백)의 x. 2단이 아니면 None (SOT §3.6).

    260910-10: `x0`·`x1` 을 주면 **그 안에서만** 찾는다 — 이미 가른 한쪽 단 안에 또
    단이 있는 경우(본문 옆의 안내 상자)를 한 겹 더 가르기 위해서다. 기준(띠 폭·
    가운데)은 모두 **그 구간 폭**에 대한 비율이라 쪽 전체든 한쪽 단이든 같게 쓴다.

    2단 판정을 블록 위치로 어림하면 **표가 있는 1단 쪽을 2단으로 잘못 본다** —
    실제로 그렇게 판정해 표 한 행의 왼쪽 칸과 오른쪽 칸이 갈라졌다(260908-7).
    그래서 '가운데 근처에 글이 거의 가로지르지 않는 띠가 있는가' 를 직접 본다.
    **줄 단위로 센다** — 전폭 제목 한두 줄이 가로지른다고 2단이 아닌 것은 아니다.
    """
    try:
        rect = page.rect
        lo_b = float(rect.x0) if x0 is None else float(x0)
        hi_b = float(rect.x1) if x1 is None else float(x1)
        w = hi_b - lo_b
        mid = (lo_b + hi_b) / 2.0
    except Exception:
        return None
    if w <= 0 or len(bands) < 6:
        return None
    # 260910-8(SOT §3.6.4): **전폭 조각은 세지 않는다.** 제목·머리띠·넓은 캡션이
    #   가운데를 가로지른다고 그 쪽이 2단이 아닌 것은 아니다 — 사용자 보고
    #   "위에 전체 내용이 있거나 중간에 사진이 있을 경우" 가 바로 이것이다.
    #   폭은 **띠가 아니라 조각 하나**로 잰다. 좌·우 단의 두 줄이 한 띠에 묶이면
    #   띠 폭은 늘 전폭이라, 띠로 재면 본문까지 전폭으로 오해한다(실측: 38줄 중 24줄).
    try:
        _f = [f for bd in bands for f in bd["items"]]
        _body = max(1.0, max(x[0][2] for x in _f) - min(x[0][0] for x in _f))
    except Exception:
        _body = w
    bands = [bd for bd in bands
             if max(f[0][2] - f[0][0] for f in bd["items"]) < COL_FULL * _body] or bands
    if len(bands) < 6:
        return None
    allow = max(1, int(len(bands) * 0.15))       # 남은 줄 중 이만큼은 봐준다
    lo, hi = mid - 0.15 * w, mid + 0.15 * w
    step = max(0.5, w / 400.0)
    best_a = best_b = None
    a = None
    x = lo
    while x <= hi:
        cross = 0
        for bd in bands:
            if any(f[0][0] < x < f[0][2] for f in bd["items"]):
                cross += 1
                if cross > allow:
                    break
        if cross > allow:
            a = None
        else:
            if a is None:
                a = x
            if best_a is None or (x - a) > (best_b - best_a):
                best_a, best_b = a, x
        x += step
    if best_a is None or (best_b - best_a) < COL_GUTTER_MIN * w:
        return None
    gx = (best_a + best_b) / 2.0
    frags = [f for bd in bands for f in bd["items"]]
    left = [f for f in frags if f[0][2] <= gx]
    right = [f for f in frags if f[0][0] >= gx]
    if len(left) < 5 or len(right) < 5:
        return None
    # ★ 표와 가르는 마지막 관문: **왼쪽 끝이 맞춰져 있는가.**
    #   글의 단은 왼쪽 여백이 일정하다(실측 100%). 표·서식은 칸마다 제각각이다(5~9%).
    #   가운데 빈 띠만 보고 판단하면 **칸이 두 무리로 놓인 서식을 2단으로 잘못 본다**
    #   — 실제로 배합설계 서식이 그렇게 갈라져 한 행이 두 줄이 됐다(260908-7).
    # 261108-31(SOT §3.6.4·§3.7.16): 정렬·폭은 그 쪽의 **넓은 조각**(그 쪽 가장 넓은 조각 폭의 절반 이상)으로 잰다 — 반 단짜리
    #   표가 본문 옆에 있으면(cao 3·5쪽 왼쪽 단의 표) 칸 조각이 왼쪽 끝 비율·중앙 폭을 끌어내려 2단 쪽을 1단으로 봤다. 넓은
    #   조각이 다섯이 안 되면 종전대로 모든 조각. 비율이라 목차(쪽번호 쪽은 모두 좁다)는 그대로 걸린다.
    def _wide(fs):
        if not fs:
            return fs
        mx = max(f[0][2] - f[0][0] for f in fs)
        w = [f for f in fs if (f[0][2] - f[0][0]) >= mx * COL_WIDE_SHARE]
        return w if len(w) >= 5 else fs
    left, right = _wide(left), _wide(right)
    if _left_edge_share(left) < COL_ALIGN or _left_edge_share(right) < COL_ALIGN:
        return None
    # 260910-8(SOT §3.6.4): **한쪽이 지나치게 좁으면 단이 아니다.** 목차는 왼쪽에 제목,
    #   오른쪽에 쪽번호가 놓여 위 관문을 모두 지나간다. 그런데 그것을 2단으로 갈라
    #   읽으면 제목이 전부 나온 뒤 쪽번호가 몰려 나와 짝이 끊긴다.
    #   실측(가운데 폭): 목차 0.06~0.09 / 진짜 2단 0.45~1.87.
    lw = _median_w(left)
    rw = _median_w(right)
    if max(lw, rw) <= 0 or min(lw, rw) / max(lw, rw) < COL_WIDTH_MIN:
        return None
    return gx


def _median_w(frags) -> float:
    """조각 폭의 중앙값 (SOT §3.6.4). 한두 줄이 길어도 흔들리지 않게 중앙값을 쓴다."""
    ws = sorted((f[0][2] - f[0][0]) for f in frags)
    if not ws:
        return 0.0
    return ws[len(ws) // 2]


def _left_edge_share(frags) -> float:
    """왼쪽 끝(2pt 로 반올림)이 가장 흔한 값과 같은 조각의 비율."""
    if not frags:
        return 0.0
    counts = {}
    for f in frags:
        k = round(f[0][0] / 2.0)
        counts[k] = counts.get(k, 0) + 1
    return max(counts.values()) / float(len(frags))


def _hrules(page) -> list:
    """쪽에 그려진 **전폭 가로 줄**의 y 목록 (SOT §3.6.5).

    표의 행 구분선이다. 세로 줄이 없는 표(이 문서의 Table 1~3)는 pdfplumber 가
    칸을 못 잡지만, 가로 줄은 그려져 있어 **행 경계는 정확히 알 수 있다**.
    """
    try:
        w = float(page.rect.width or 0.0)
        need = HRULE_SPAN * w
        ys = []
        for d in page.get_drawings():
            for it in d.get("items", []):
                if it[0] == "l":
                    a, b = it[1], it[2]
                    if abs(a.y - b.y) < 1.0 and abs(a.x - b.x) >= need:
                        ys.append(float(a.y))
                elif it[0] == "re":
                    r = it[1]
                    if r.height < 3.0 and r.width >= need:
                        ys.append(float(r.y0))
        out = []
        for y in sorted(ys):
            if not out or abs(y - out[-1]) > 2.0:
                out.append(y)
        return out
    except Exception:
        return []


def _split_cols(frags) -> list:
    """한 행 안의 조각을 **가로 빈틈**으로 칸마다 나눈다 (SOT §3.6.5).

    260911(SOT §3.6.9): 빈틈 기준은 **글자 크기에 따라** 커진다. 큰 제목은 낱말
    사이가 원래 넓어(실측 `MOVING`~`BEYOND` **14.8pt**, 글자 높이 37.5) 고정 6pt 로
    자르면 제목 한 줄이 낱말마다 쪼개지고, 그러면 좌·우 단으로 찢어진다.
    본문(높이 10 안팎)에서는 6pt 그대로다.
    """
    if not frags:
        return []
    order = sorted(frags, key=lambda f: (f[0][0], f[0][1]))
    cols, cur = [], [order[0]]
    edge = order[0][0][2]
    hi = order[0][0][3] - order[0][0][1]
    for f in order[1:]:
        h = max(hi, f[0][3] - f[0][1])
        if f[0][0] - edge > max(CELL_GAP, h * CELL_GAP_H):
            cols.append(cur)
            cur = [f]
            edge = f[0][2]
            hi = f[0][3] - f[0][1]
        else:
            cur.append(f)
            edge = max(edge, f[0][2])
            hi = max(hi, f[0][3] - f[0][1])
    cols.append(cur)
    return cols


def _table_cells(frags, page):
    """가로 줄로 나뉜 표를 **칸 단위**로 읽는 차례. 표가 아니면 None (SOT §3.6.5).

    260910-9(사용자 보고 "텍스트 창에서 제대로 인식 못 한다"): 칸 안에 여러 줄이 든 표를
    줄 단위로 이으면 **다른 칸의 첫 줄끼리** 붙는다 — 실측(NAPA Table 1):
    `Virgin asphalt binder source. | Variations in the high, intermediate,`.
    두 칸 다 문장이 이어지는 글이라 그렇게 붙이면 양쪽 다 못 읽는다.

    판정은 **행마다** 한다. 칸이 모두 한 줄인 행(점검표의 `항목 | YES NO`)은 종전대로
    한 줄로 잇는 편이 낫다 — 그 줄은 실제로 한 줄이기 때문이다.
    """
    if len(frags) < 6:
        return None                  # 261114-11(SOT §3.6.5): 표 안 조각은 쪽 조각의 일부 — 6 미만이면 선을 읽을 것도 없다(같은 답)
    rules = _hrules(page)
    if len(rules) < 2:
        return None
    inner = [f for f in frags if rules[0] < (f[0][1] + f[0][3]) / 2.0 < rules[-1]]
    if len(inner) < 6:
        return None
    outside = [f for f in frags if f not in inner]
    above = [f for f in outside if (f[0][1] + f[0][3]) / 2.0 <= rules[0]]
    below = [f for f in outside if (f[0][1] + f[0][3]) / 2.0 >= rules[-1]]
    groups, multi = [], False
    # 261108-31(SOT §3.6.5·§3.7.16): 표 **바깥**(위·아래)은 단 가르기(`_by_column`)를 거친다 — 종전에는 한 묶음으로 내보내
    #   2단 논문의 본문 좌·우 단 줄이 한 줄로 붙었다(cao 1쪽: 초록을 두른 가로 줄 아래의 2단 본문, 2~5쪽: 표 위의 2단 본문).
    def _cols(fs):
        return [g for g in _by_column([(None, fs)], page) if g]
    if above:
        groups.extend(_cols(above))
    for k in range(len(rules) - 1):
        y0, y1 = rules[k], rules[k + 1]
        band = [f for f in inner if y0 < (f[0][1] + f[0][3]) / 2.0 < y1]
        if not band:
            continue
        cols = _split_cols(band)
        if any(len(_row_bands(c)) > 1 for c in cols):
            multi = True
            groups.extend(cols)          # 칸마다 따로 — 왼쪽부터
        else:
            groups.append(band)          # 한 줄짜리 행은 종전대로
    if below:
        groups.extend(_cols(below))
    if not multi:
        # 표 칸 차례가 필요 없어도 바깥이 2단이면 그 차례를 쓴다(가운데 띠는 한 묶음 그대로)
        if len([g for g in groups if g]) > (1 if above else 0) + (1 if below else 0) + sum(
                1 for k in range(len(rules) - 1)
                if any(rules[k] < (f[0][1] + f[0][3]) / 2.0 < rules[k + 1] for f in inner)):
            return groups
        return None
    return groups


def _line_pieces(frags):
    """낱말 상자를 **줄 조각**으로 모은다 — 단 판정에만 쓴다 (SOT §3.6.7).

    260910-11: OCR 은 **낱말마다** 상자를 준다. 그 상태로 `_left_edge_share` 를 재면
    낱말이 제각기 다른 x 에서 시작하므로 정렬도가 바닥이라, **2단인 쪽도 2단이 아니라고**
    나온다(실측 1쪽: 글자층은 gutter 307.5 인데 같은 쪽 OCR 은 None).

    한 줄 안에서 낱말 사이는 좁고(빈칸 두어 점) 단 사이는 넓다. 그래서 `_split_cols`
    (6pt)로 모으면 **단마다 한 줄 조각**이 되고, 그 조각의 왼쪽 끝은 글자층의 줄과 같다.
    """
    out = []
    for bd in _row_bands(frags):
        for grp in _split_cols(bd["items"]):
            x0 = min(f[0][0] for f in grp)
            y0 = min(f[0][1] for f in grp)
            x1 = max(f[0][2] for f in grp)
            y1 = max(f[0][3] for f in grp)
            out.append(((x0, y0, x1, y1), " ".join(f[1] for f in grp),
                        max(f[2] for f in grp)))
    return out


def _by_column(blocks, page, word_level: bool = False):
    """[[조각…]] — 읽는 차례대로 나눈 묶음들 (SOT §3.6.4).

    260910-8(사용자 보고 "2단인데 위에 전체 내용이 있거나 중간에 사진이 있을 경우
    단 구분 없이 읽는다"): 종전에는 쪽 전체를 **좌 한 덩어리 · 우 한 덩어리**로만
    갈랐다. 그러면 전폭 제목이 어느 한쪽 단의 글 사이에 끼어 들어간다.

    이제 쪽을 세로로 **토막 낸다** — 전폭 줄은 제 자리에 그대로 두고, 그 사이의
    2단 구역만 좌·우로 가른다. 그래서 나오는 차례는

        전폭 제목 → (구역1 좌 → 구역1 우) → 전폭 사진 설명 → (구역2 좌 → 구역2 우)

    로, 사람이 읽는 차례와 같다.
    """
    frags = [f for _bb, lines in blocks for f in lines]
    # 260910-11(SOT §3.6.7)·260911(§3.6.9): 낱말 상자로 들어오면 **줄 조각으로 묶어**
    #   판정도 차례도 그 위에서 한다. 낱말 하나는 가운데를 가로지를 수 없어, 낱말로
    #   전폭을 따지면 전폭 제목이 좌·우로 찢어진다(실측: `MOVING` 은 왼쪽, `BEYOND`
    #   는 오른쪽). 조각으로 묶으면 제목 한 줄이 통째로 전폭이 된다.
    #   내보낼 때는 **원래 낱말로 되돌린다** — `_merge_rows` 의 간격 규칙이 살아야 한다.
    owners = None
    if word_level:
        pieces, owners = [], {}
        for bd in _row_bands(frags):
            for grp in _split_cols(bd["items"]):
                g = sorted(grp, key=lambda q: q[0][0])
                rect = (min(f[0][0] for f in g), min(f[0][1] for f in g),
                        max(f[0][2] for f in g), max(f[0][3] for f in g))
                pc = (rect, " ".join(f[1] for f in g), max(f[2] for f in g))
                pieces.append(pc)
                owners[id(pc)] = g
        frags = pieces
    bands = sorted(_row_bands(frags), key=lambda b: (b["y0"], b["y1"]))

    def _restore(groups):
        """묶음 안의 줄 조각을 **원래 낱말로** 되돌린다 (260916-1).

        260916-1(SOT §3.6.11, 사용자 보고): 되돌리기가 **2단으로 갈린 길에만** 있어서,
        단이 하나면(`gx is None` — 보통의 책 쪽) 공백으로 이어 붙인 줄 조각이 그대로
        나갔다. 그러면 `_merge_rows` 의 간격 규칙(§3.6.2)이 아예 돌지 못해 OCR 이
        글자마다 낸 낱말이 `성 격 은` 으로 흩어진다. 나가는 길이 둘이므로 되돌리기도
        **두 곳 모두**에서 한다.
        """
        if owners is None:
            return groups
        return [[w for pc in g for w in owners.get(id(pc), [pc])] for g in groups]

    gx = _gutter_x(bands, page)
    if gx is None:
        return _restore([frags])
    tail = _tail_band_start(bands)     # 260910-10: 꼬리말 띠는 단에 넣지 않는다
    groups, left, right = [], [], []

    def _flush():
        # 260910-10(SOT §3.6.6): 한쪽 단 안에 또 단이 있으면(본문 옆 안내 상자)
        #   한 겹 더 가른다. 그러지 않으면 그 상자 글이 본문과 줄줄이 붙는다.
        for side in (left, right):
            if side:
                groups.extend(_split_inner(list(side), page))
                side.clear()

    # 260910-12(SOT §3.6.8): '가로지른다' 는 **양쪽으로 넉넉히** 뻗은 것만.
    try:
        _bx0 = min(f[0][0] for f in frags)
        _bx1 = max(f[0][2] for f in frags)
        _need = max(1.0, (_bx1 - _bx0) * COL_CROSS)
    except ValueError:
        _need = 1.0

    def _crosses(f):
        return min(gx - f[0][0], f[0][2] - gx) >= _need

    for i, bd in enumerate(bands):
        if i == tail:
            _flush()                      # 꼬리말 앞에서 단을 닫는다
        if tail is not None and i >= tail:
            groups.append(list(bd["items"]))
            continue
        # 가운데를 실제로 가로지르는 조각이 있으면 그 줄은 전폭이다.
        if any(_crosses(f) for f in bd["items"]):
            _flush()                      # 앞 구역을 좌→우 차례로 닫고
            groups.append(list(bd["items"]))   # 전폭 줄을 제 자리에 둔다
            continue
        for f in bd["items"]:
            (left if (f[0][0] + f[0][2]) / 2.0 < gx else right).append(f)
    _flush()
    groups = [g for g in groups if g]
    return _restore(groups)     # 조각을 원래 낱말로 되돌린다


def _tail_band_start(bands):
    """꼬리말(쪽번호·출처)이 시작하는 띠의 자리. 없으면 None (SOT §3.6.6).

    260910-10(사용자 보고): 꼬리말은 두 단 아래에 걸쳐 있어 **마지막 두 단 줄**로
    잡혔다. 그래서 왼쪽 반쪽이 왼쪽 단 끝에 붙어 **본문 한가운데** 나왔다
    (실측 5쪽: `… verification of plant components including the` 다음에
    `BMD-002 © NAPA, March 2026`, 그 뒤에 오른쪽 단이 시작).

    판정은 **큰 빈틈 뒤에 남은 띠가 한두 줄뿐인가** 로 한다. 쪽 가운데의 문단 사이
    빈틈은 이 조건을 못 넘는다 — 뒤에 남은 줄이 많기 때문이다.
    실측(이 문서 4쪽): 문단 사이 0.9배 / 꼬리말 앞 2.3~31.8배.
    """
    if len(bands) < 4:
        return None
    pitches = sorted(bands[i + 1]["y0"] - bands[i]["y0"] for i in range(len(bands) - 1))
    med = pitches[len(pitches) // 2]
    if med <= 0:
        return None
    for i in range(len(bands) - 1, max(0, len(bands) - 3) - 1, -1):
        if i <= 0:
            break
        if (bands[i]["y0"] - bands[i - 1]["y1"]) >= 2.0 * med:
            return i
    return None


def _split_inner(frags, page):
    """한쪽 단 안을 한 겹 더 가른다 (SOT §3.6.6). 가를 수 없으면 [그대로].

    실측 14쪽: 오른쪽 단 옆에 안내 상자(QR)가 있어 `Volumetric properties |
    LEARN MORE ABOUT` 처럼 본문과 상자 글이 줄마다 붙었다.
    """
    if len(frags) < 8:
        return [frags]
    x0 = min(f[0][0] for f in frags)
    x1 = max(f[0][2] for f in frags)
    gx = _gutter_x(_row_bands(frags), page, x0, x1)
    if gx is None:
        return [frags]
    a = [f for f in frags if (f[0][0] + f[0][2]) / 2.0 < gx]
    b = [f for f in frags if (f[0][0] + f[0][2]) / 2.0 >= gx]
    return [g for g in (a, b) if g] or [frags]


def _is_cjk(ch) -> bool:
    """한글·한자·가나인가(띄어쓰기 규칙이 라틴과 다르다, SOT §3.6.2)."""
    o = ord(ch)
    return (0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF      # 한글
            or 0x3130 <= o <= 0x318F
            or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF   # 한자
            or 0x3040 <= o <= 0x30FF)                           # 가나


def _is_cjk_pair(left, right) -> bool:
    """맞닿는 두 글자 중 **하나라도** CJK 면 CJK 규칙을 쓴다.

    `제`+`8`, `8`+`조` 처럼 숫자가 섞인 자리도 한 낱말 안이다(실측 §3.6.2).
    """
    a = (left or '').rstrip()[-1:]
    b = (right or '').lstrip()[:1]
    return bool((a and _is_cjk(a)) or (b and _is_cjk(b)))

def _is_num_pair(left, right) -> bool:
    """숫자가 한 자씩 흩어진 자리인가 (SOT §3.6.2).

    양쪽 다 숫자·소수점·쉼표·%% 로만 되어 있고 **한쪽이 한 글자**일 때만 참이다.
    `3.9261` 과 `4.0065` 처럼 둘 다 온전한 수면 붙이지 않는다 — 다른 값이다.
    """
    a = (left or '').rstrip().split(' ')[-1]
    b = (right or '').lstrip().split(' ')[0]
    if not a or not b:
        return False
    if not (set(a) <= _NUM_CHARS and set(b) <= _NUM_CHARS):
        return False
    if not (any(c.isdigit() for c in a) or any(c.isdigit() for c in b)):
        return False
    return len(a) == 1 or len(b) == 1


def fix_number_spaces(text: str) -> str:
    """글 안에 이미 들어 있는 **수 사이의 빈칸**을 없앤다 (SOT §3.6.2).

    흐린 스캔의 글자층에는 `9 5 . 6%`·`4 . 4`·`1 000.0` 처럼 수가 쪼개져 들어 있다
    (그 PDF 를 만든 OCR 이 그렇게 적었다). 자리 정보가 없으니 글자만 보고 고친다.

    **한 글자짜리 토막이 낀 자리만** 붙인다 — `3.9261 4.0065` 처럼 둘 다 온전한 수는
    서로 다른 값이므로 건드리지 않는다.
    """
    if not text or ' ' not in text:
        return text
    toks = text.split(' ')
    out = [toks[0]]
    prev = toks[0]                  # **원래 토막**으로 판단한다 — 이어 붙인 것이 길어지면
    for t in toks[1:]:              #   '한쪽이 한 글자' 조건이 곧 거짓이 되어 뒤가 끊긴다
        if t and prev and _is_num_pair(prev, t):
            out[-1] = out[-1] + t
        else:
            out.append(t)
        prev = t
    return ' '.join(out)

def _is_ascii_letter(ch) -> bool:
    return ('a' <= ch <= 'z') or ('A' <= ch <= 'Z')


def fix_number_ocr(text: str) -> str:
    """수 안에서 `0`→`O`, `1`→`l`·`I` 로 잘못 읽은 것을 되돌린다 (SOT §3.6.3).

    **글자를 바꾸는 일**이라 세 가지를 모두 만족할 때만 바꾼다.
      ① 그 토막이 숫자·소수점·쉼표·%%·닮은 글자·빈칸 으로만 되어 있다
      ② 원래 토막에 **진짜 숫자가 하나 이상** 있다 — 홀로 있는 `O` 는 글자다
      ③ 바꾼 결과가 **수의 모양**이다(소수점 하나, 천 단위 쉼표만)
    그리고 토막의 앞뒤가 **영문 글자가 아니어야** 한다 — `No. 1` 이 `N0.1` 이 되면 안 된다
    (한글은 영문 글자가 아니므로 `2026년O2월` 은 고쳐진다).

    빈칸은 **그대로 둔다**. 붙이는 일은 `fix_number_spaces()` 가 따로 한다.
    """
    if not text:
        return text
    import re
    out = []
    i, n = 0, len(text)
    while i < n:
        if text[i] not in _NUMRUN_CHARS:
            out.append(text[i])
            i += 1
            continue
        j = i
        while j < n and text[j] in _NUMRUN_CHARS:
            j += 1
        run = text[i:j]
        core = run.strip()
        before = text[i - 1] if i > 0 else ''
        after = text[j] if j < n else ''
        ok = bool(core) and any(c.isdigit() for c in core)
        if ok and (_is_ascii_letter(before) or _is_ascii_letter(after)):
            ok = False
        if ok:
            cand = ''.join(_LOOKALIKE.get(c, c) for c in core if c != ' ')
            if re.match(r'^\d+(,\d{3})*(\.\d+)?%?$', cand):
                run = ''.join(_LOOKALIKE.get(c, c) for c in run)
        out.append(run)
        i = j
    return ''.join(out)

def cjk_gap_threshold(frags, bands=None):
    """이 쪽의 **낱말 사이 빈틈 문턱**을 빈틈 분포에서 뽑는다 (SOT §3.6.12, 260916-1).

    OCR 이 한글을 글자마다 낱말로 내놓으므로, 한 줄의 빈틈은 두 봉우리를 이룬다 —
    **글자 사이**(좁다)와 **낱말 사이**(넓다). 그 골짜기를 1차원 오츠로 찾는다.
    문서가 달라도 그 문서 자신의 분포를 보므로 따라간다(§3.7.6 의 교훈과 같다).

    잰 값은 `빈틈 ÷ 그 줄 상자 높이의 중앙값` 이다 — 상자 하나의 잉크 높이로 재면
    `으로`(받침 없음)처럼 낮은 상자에서 비율이 부풀어 흔들린다.

    표본이 `CJK_GLUE_MIN_N` 에 못 미치면 **None** 을 준다(부르는 쪽이 기본값을 쓴다).
    """
    vals = []
    for bd in (bands if bands is not None else _row_bands(frags)):
        items = sorted(bd["items"], key=lambda f: f[0][0])
        if len(items) < 2:
            continue
        hs = sorted(max(1.0, f[0][3] - f[0][1]) for f in items)
        ref = max(1.0, hs[len(hs) // 2])
        for a, b in zip(items, items[1:]):
            ta, tb = a[1].strip(), b[1].strip()
            if not ta or not tb:
                continue
            if not _is_cjk_pair(ta, tb):
                continue
            r = (b[0][0] - a[0][2]) / ref
            if -0.5 <= r <= CJK_GLUE_TOP:      # 칸 사이(아주 넓은 빈틈)는 뺀다
                vals.append(r)
    if len(vals) < CJK_GLUE_MIN_N:
        return None
    best, thr = -1.0, None
    step = 0.01
    t = CJK_GLUE_MIN - 0.10
    while t <= CJK_GLUE_MAX + 0.10 + 1e-9:
        lo = [v for v in vals if v < t]
        hi = [v for v in vals if v >= t]
        if len(lo) >= 5 and len(hi) >= 5:
            wl, wh = len(lo) / len(vals), len(hi) / len(vals)
            var = wl * wh * (sum(lo) / len(lo) - sum(hi) / len(hi)) ** 2
            if var > best:
                best, thr = var, t
        t += step
    if thr is None:
        return None
    return min(CJK_GLUE_MAX, max(CJK_GLUE_MIN, thr))


def _merge_rows(frags, cjk_gap=None):
    """세로로 겹치는 조각을 **한 줄**로 잇는다 — 왼쪽부터 오른쪽으로.

    잇는 방법은 벌어진 폭에 따른다(SOT §3.6).
      - 글자크기의 0.25 배 미만 → 붙여 쓴다(OCR 낱말 상자의 라틴은 붙이지 않는다 — §3.6.13)
      - 2.5 배 미만 → 공백 하나
      - 그 이상 → `" | "` — 표의 다른 칸으로 본다(§3.3 과 같은 표기)

    260916-1(SOT §3.6.12): `cjk_gap` 을 주면 **한글 문턱**을 그 값으로 하고, 재는
    자도 **그 줄 상자 높이의 중앙값**으로 바꾼다. OCR 낱말 상자로 들어올 때만 준다 —
    글자층의 `size` 는 이미 글꼴 크기라 흔들리지 않는다.
    """
    out = []
    for bd in _row_bands(frags):
        items = sorted(bd["items"], key=lambda f: f[0][0])
        row_ref = None
        if cjk_gap is not None:
            hs = sorted(max(1.0, f[0][3] - f[0][1]) for f in items)
            row_ref = max(1.0, hs[len(hs) // 2])
        text = items[0][1].rstrip()
        x0, y0, x1, y1 = items[0][0]
        for rect, txt, size in items[1:]:
            piece = txt.strip()
            if not piece:
                continue
            ref = max(1.0, size or (rect[3] - rect[1]))
            gap = rect[0] - x1
            if _is_cjk_pair(text, piece):
                if row_ref is not None:
                    glue, ref = cjk_gap, row_ref
                else:
                    glue = CJK_GLUE_GAP
            elif _is_num_pair(text, piece):
                glue = NUM_GLUE_GAP
            elif cjk_gap is not None:
                # 261101-1(SOT §3.6.13): OCR 낱말 상자의 라틴은 Tesseract 가 이미 갈랐다 — 붙이지 않는다.
                #   `GLUE_GAP` 은 글자층 조각을 위한 것이라 양쪽 정렬된 소설에서 486곳을 붙였다(`mywillpower`).
                glue = None
            else:
                glue = GLUE_GAP
            if glue is not None and gap < glue * ref:
                sep = ""
            elif gap < COL_GAP * ref:
                sep = "" if (not text or text.endswith(" ")) else " "
            else:
                sep = CELL_SEP
            text = text.rstrip() + sep + piece if sep == CELL_SEP else text + sep + piece
            x0, y0 = min(x0, rect[0]), min(y0, rect[1])
            x1, y1 = max(x1, rect[2]), max(y1, rect[3])
        # 대표 크기 = **글자가 가장 많은 조각**의 크기(제목/내용 판정용, SOT §3.4)
        #   260912-2: OCR 쪽에서는 이 값이 흔들린다(§3.4.1 백로그) — '글자 수로 무게를
        #   준 중앙값' 으로 바꿔 봤으나 표 많은 스캔 서식이 되레 나빠져(제목 38 → 69)
        #   되돌렸다. 고치려면 제목 판정 자체를 손봐야 한다.
        size = max(items, key=lambda f: len(f[1].strip()))[2]
        if row_ref is not None:
            # 261102-2(SOT §3.4): OCR 낱말 줄은 **낱말 높이의 중앙값** — 상자 몇 개가 위아래 글줄과 엉겨 68px 로 잡히면
            #   (_96 보고서 12쪽 `됐다.`·`로시`·`험의`, 나머지 46px) 줄이 제목이 되어 문단이 끊겼다
            size = row_ref
        # 260910(SOT §3.7): 끝의 빈칸을 **남긴다** — 문장을 이을 때 그 자리가
        #   낱말 경계였는지 알려 주는 유일한 단서다. 판단은 **마지막 조각의 원본**으로
        #   한다: `text` 는 이미 다듬여 있어 그것으로 재면 언제나 빈칸이 없다.
        tail = ' ' if items[-1][1].endswith((' ', chr(9))) else ''
        out.append(((x0, y0, x1, y1),
                    fix_number_spaces(fix_number_ocr(text.rstrip())) + tail,
                    size))
    return out


_NOISE = {"n": 0}


def last_noise_count() -> int:
    """바로 앞 `_line_items` 가 뺀 잡음 줄 수(SOT §3.5 — 창 안내에 쓴다)."""
    return int(_NOISE.get("n", 0))


# 260908-3(응답성 SOT §4 ⑥, 감사에서 발견): **pdfplumber 핸들을 재사용한다.**
#   쪽을 넘길 때마다 `pdfplumber.open()` 을 새로 하면 그 문서를 처음부터 다시 뜯는다 —
#   실측 348쪽 61MB 문서에서 **쪽당 8.5~17초**(응답 없음 문턱의 두세 배)였다.
#   같은 핸들을 쓰면 쪽당 29~192ms 다. 파일이 바뀌거나 수정되면 새로 연다.
_PLUMB = {"key": None, "pdf": None}
# 260913-4: 여는 것·닫는 것은 **한 번에 한 스레드**만 한다. 텍스트 창 작업과 앞뒤 쪽
#   미리 읽기가 동시에 `_plumber` 에 들어오면 둘 다 새로 열고 하나가 다른 하나를 덮어쓴다.
#   덮인 핸들은 아무도 닫지 않아 가비지 수집 전까지 **원본을 잠근다** — 'PDF에 반영' 이
#   `_edited.pdf` 로 빠지던 원인이었다(실측: gc 를 돌리면 풀렸다).
import threading as _threading
_PLUMB_LOCK = _threading.RLock()
# 261014-19(SOT §3 규칙 8): **읽기**는 한 번에 한 스레드 — 여닫기 잠금(`_PLUMB_LOCK`)과 따로 둔다. 메인이 부르는
#   `close_cache()` 가 배경의 긴 표 찾기(쪽당 최대 수 초)를 기다리며 서지 않게, 읽는 중이면 닫기를 읽는 쪽에 넘긴다.
_PLUMB_USE = _threading.Lock()
_PLUMB_PENDING = []        # 읽는 중이라 못 닫은 핸들 — 읽던 스레드가 끝나고 닫는다
_TCACHE = {}          # (파일키, 쪽) -> [(bbox, rows)]
_TCACHE_MAX = 64


def _plumber(pdf_path):
    import os
    try:
        key = (str(pdf_path), os.path.getmtime(pdf_path))
    except Exception:
        return None
    with _PLUMB_LOCK:
        if _PLUMB["key"] == key and _PLUMB["pdf"] is not None:
            return _PLUMB["pdf"]
        close_cache()
        try:
            import pdfplumber
            _PLUMB["pdf"] = pdfplumber.open(str(pdf_path))
            _PLUMB["key"] = key
        except Exception:
            _PLUMB["key"] = None
            _PLUMB["pdf"] = None
        return _PLUMB["pdf"]


def close_cache() -> None:
    """열어 둔 핸들·표 결과를 놓는다. 파일을 지우거나 덮어쓰기 전에 부른다.
    배경이 그 핸들로 읽는 중이면 기다리지 않고 읽는 쪽이 끝난 뒤 닫는다(SOT §3 규칙 8)."""
    with _PLUMB_LOCK:
        pdf = _PLUMB.get("pdf")
        _PLUMB["pdf"] = None
        _PLUMB["key"] = None
        _TCACHE.clear()
    if pdf is None:
        return
    if _PLUMB_USE.acquire(blocking=False):
        try:
            pdf.close()
        except Exception:
            pass
        finally:
            _PLUMB_USE.release()
    else:
        _PLUMB_PENDING.append(pdf)


def _close_pending() -> None:
    """`_PLUMB_USE` 를 쥔 스레드가 부른다 — 읽는 동안 미뤄 둔 닫기."""
    while _PLUMB_PENDING:
        try:
            _PLUMB_PENDING.pop().close()
        except Exception:
            pass


TABLE_MIN_COLS = 2      # 열이 이보다 적으면 표가 아니다(SOT §3 규칙 9, 261014-30)


def _real_tables(found) -> list:
    """열이 `TABLE_MIN_COLS` 보다 적은(표 구조가 1열인) '표' 를 뺀다 — 2단 논문의 단 하나·테두리 친 문단이 1열 표로 잡혀
    본문이 표 칸에 들어갔다(표본 시험). 캐시(`_TCACHE`·`page_tables`)에 든 옛 결과에도 같이 건다.
    **글이 든 열** 로 세지 않는다 — 왼쪽 칸이 그림(지도)이고 오른쪽 칸만 글인 2열 표가 빠져 그 글이 그림으로 들어갔다(같은 표본 시험)."""
    return [(bbox, rows) for bbox, rows in (found or []) if max((len(r or []) for r in rows), default=0) >= TABLE_MIN_COLS]


def _tables(pdf_path, page_index: int, *, cached_only: bool = False, plumber=None):
    return _real_tables(_tables_raw(pdf_path, page_index, cached_only=cached_only, plumber=plumber))


def _tables_raw(pdf_path, page_index: int, *, cached_only: bool = False, plumber=None):
    """[(bbox, rows)] — pdfplumber 로 찾은 표. 없거나 실패하면 빈 목록.

    260908-5: 캐시를 **두 겹**으로 본다. ① 이번 실행의 메모리(`_TCACHE`), ② index.db 의
    `page_tables`. 둘 다 `pdfplumber` 를 열기 **전에** 본다 — 표 찾기가 실측 쪽당
    150ms~7초라, 캐시가 맞는데도 문서를 여는 것은 그 값을 헛되이 치르는 일이다.
    """
    size, mtime = _stat(pdf_path)
    ck = ((str(pdf_path), size, mtime), int(page_index))
    hit = _TCACHE.get(ck)
    if hit is not None:
        return hit
    db = _db_get(pdf_path, page_index)
    if db is not None:
        _TCACHE[ck] = db
        return db
    if cached_only:
        # 260908-5(응답성 SOT §4 ①): 인덱싱이 도는 동안에는 표를 **새로 파지 않는다** —
        #   둘 다 GIL 을 오래 쥐어 겹치면 창이 굼떠진다. 인덱싱이 끝나면 다시 부른다.
        #   결과를 캐시에 넣지 않는 것이 요점이다(다음 호출이 제대로 파도록).
        return []
    # 261014-12(SOT §3 규칙 6): 여러 쪽을 이어 읽는 배경 작업은 자기 pdfplumber 문서를 준다 — 공유 핸들은
    #   다른 스레드의 `close_cache()` 로 언제든 닫힌다.
    pdf = plumber if plumber is not None else _plumber(pdf_path)
    if pdf is None:
        return []
    out = []
    failed = False
    # 261014-19(SOT §3 규칙 8): 공유 핸들은 **한 번에 한 스레드만** 읽는다 — 텍스트 창과 앞뒤 쪽 미리 읽기가 같은 pdfminer
    #   문서를 동시에 읽으면 표가 조용히 깨졌다(실측 60번 중 51~60번 틀림, 예외 없이). 자기 문서(`plumber=`)는 잠그지 않는다.
    import contextlib
    guard = _PLUMB_USE if plumber is None else contextlib.nullcontext()
    try:
        with guard:
            pg = _plumber_page(pdf, pdf_path, int(page_index))
            if pg is not None:
                for t in pg.find_tables():
                    rows = t.extract() or []
                    if rows:
                        out.append((tuple(t.bbox), rows))
                try:
                    pg.flush_cache()            # 쪽마다 붙잡는 메모리를 놓는다
                except Exception:
                    pass
            if plumber is None:
                _close_pending()
    except Exception:
        out = []
        failed = True
        if plumber is None and _PLUMB_USE.acquire(blocking=False):
            try:
                _close_pending()
            finally:
                _PLUMB_USE.release()
    if failed:
        # 261014-12(SOT §3 규칙 6): 예외(핸들이 닫힘 등)는 '표 없음' 이 아니다 — 캐시·page_tables 에 남기지 않는다.
        #   종전에는 [] 를 영구 저장해 파일이 바뀌기 전까지 그 쪽 표가 사라졌다.
        return []
    if len(_TCACHE) > _TCACHE_MAX:
        _TCACHE.clear()
    _TCACHE[ck] = out
    _db_put(pdf_path, page_index, out)
    return out


_INHERIT = ("Resources", "MediaBox", "CropBox", "Rotate")


def _plumber_page(pdf, pdf_path, k: int):
    """pdfplumber 쪽 하나(SOT §3 규칙 7, 261014-17). `pdf.pages` 는 쪽 하나를 봐도 문서 전체 쪽 목록을 순수 파이썬으로 만든다 —
    아직 만들지 않았으면 PyMuPDF 로 그 쪽 객체 번호를 찾아 그 쪽만 만든다. 안 되면 종전 길. 없는 쪽이면 None."""
    if "_pages" not in getattr(pdf, "__dict__", {}):
        try:
            import fitz
            from pdfminer.pdfpage import PDFPage
            from pdfminer.pdftypes import dict_value
            from pdfplumber.page import Page
            d = fitz.open(str(pdf_path))
            try:
                if d.needs_pass or not (0 <= k < d.page_count):
                    raise ValueError("fallback")
                xref = d.page_xref(k)
            finally:
                d.close()
            attrs = dict(dict_value(pdf.doc.getobj(xref)))
            parent, hops = attrs.get("Parent"), 0
            while parent is not None and hops < 64:          # 물려받는 값은 부모에서(PDF 32000 7.7.3.4)
                pd = dict_value(parent)
                for key in _INHERIT:
                    if key not in attrs and key in pd:
                        attrs[key] = pd[key]
                parent, hops = pd.get("Parent"), hops + 1
            return Page(pdf, PDFPage(pdf.doc, xref, attrs, None), page_number=k + 1, initial_doctop=0)
        except Exception:
            pass
    return pdf.pages[k] if 0 <= k < len(pdf.pages) else None


# 260908-5: 표 결과의 **영구 캐시**(index.db `page_tables`). 앱이 db 경로를 준다.
_DB_PATH = None


def set_table_cache_db(path) -> None:
    """앱 시작 때 한 번 — 없으면 캐시 없이 동작한다(기능 저하, 오류 아님)."""
    global _DB_PATH
    _DB_PATH = str(path) if path else None


def _stat(pdf_path):
    import os
    try:
        st = os.stat(pdf_path)
        return int(st.st_size), float(st.st_mtime)
    except Exception:
        return None, None


def _db_get(pdf_path, page):
    if not _DB_PATH:
        return None
    size, mtime = _stat(pdf_path)
    if size is None:
        return None
    try:
        from viewer.indexer import PdfIndex
        ix = PdfIndex(_DB_PATH)
        try:
            got = ix.tables_get(pdf_path, page, size, mtime)
        finally:
            ix.close()
        if got is None:
            return None
        return [(tuple(bb), rows) for bb, rows in got]
    except Exception:
        return None


def _db_put(pdf_path, page, data) -> None:
    if not _DB_PATH:
        return
    size, mtime = _stat(pdf_path)
    if size is None:
        return
    try:
        from viewer.indexer import PdfIndex
        ix = PdfIndex(_DB_PATH)
        try:
            ix.tables_set(pdf_path, page, size, mtime,
                          [[list(bb), rows] for bb, rows in data])
        finally:
            ix.close()
    except Exception:
        pass


def _inside(rect, box, frac: float = 0.6) -> bool:
    """`rect` 의 넓이 중 `frac` 이상이 `box` 안에 들면 True."""
    ax0, ay0, ax1, ay1 = rect
    bx0, by0, bx1, by1 = box
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    area = max(1e-6, (ax1 - ax0) * (ay1 - ay0))
    return ((ix1 - ix0) * (iy1 - iy0)) / area >= frac


def _row_line(row) -> str:
    """표 한 행 → 한 줄. 빈 칸도 자리를 지킨다(열이 밀리면 표가 아니게 된다)."""
    cells = [(c or "").replace("\n", " ").strip() for c in row]
    return " | ".join(cells)


SENT_END = set('.?!。？！:;')
JOIN_FILL = 1.0          # 오른쪽 여백까지 찼다고 보는 기준(여백 − 글자 하나)
# 260910-4(SOT §3.7.6): 빈칸이 본문 폭의 이 비율을 넘으면 어떤 어절이 와도 문단 끝.
#   목차·제목처럼 크게 남는 줄이 긴 낱말 하나 때문에 이어지는 것을 막는다.
JOIN_GAP_MAX = 0.40
# 260910-12(SOT §3.7.8): '다음 어절이 들어갔겠는가' 에 여유를 둔다.
#   그림 옆으로 글이 흐르면 줄마다 쓸 수 있는 폭이 달라, 우리가 잰 여백으로는
#   '들어갔겠다' 로 보이지만 실제로는 그림에 막혀 넘어간 자리가 있다.
#   넉넉히 남았을 때만 문단 끝으로 본다.
JOIN_WORD_SLACK = 1.5
# 260910-12(SOT §3.6.8): 전폭 줄로 보려면 **양쪽으로 이만큼씩** 뻗어야 한다.
#   조금 넘어선 것까지 전폭으로 보면, 그 줄에 딸린 다른 단의 글까지 한 줄로 붙는다
#   (실측 1쪽: 지도 범례가 가운데를 살짝 넘어 왼쪽 단 마지막 줄과 붙었다).
COL_CROSS = 0.15
# 260910-4(SOT §3.7.6 나): 한글 한 글자 목록 표시는 **가나다 차례**만 인정한다.
#   아무 글자나 받으면 `포함)` 의 `함)` 이 목록으로 보여 문장이 끊긴다.
KO_LIST_ORDER = "가나다라마바사아자차카타파하"
# 261101-1(SOT §3.6.15): 늘 띄어 쓰는 한 음절 — 낱자 붙이기(`fix_ko_spacing`)가 건드리지 않는다(`및 주지화` 가 붙었다)
KO_ALONE = set("및등또각총약첫더잘못안꼭곧즉단")
# 줄 **간격**이 아니라 **줄 사이 거리(pitch)** 를 글자 크기로 잰다 — 간격으로 재면
#   글자가 큰데 줄이 성긴 쪽(발표자료·서식)에서 남남인 줄이 붙는다(260910 실측).
#   실측 pitch÷크기: 이어지는 본문 1.6~1.8 / 따로 놓인 줄 2.9.
JOIN_PITCH = 2.2
# 260916-1(SOT §3.7.9, 사용자 지시 '줄 붙이는 방법이 적정한지 검토해'): **크기로 재면
#   문서마다 어긋난다.** `size` 가 글자층에서는 글꼴 크기(em)인데 OCR 낱말 상자에서는
#   **잉크 높이**라 1.3~1.4배 작다. 실측 pitch÷size 중앙값 — NAPA 1.12 / 보고서 2.00 /
#   지침 1.31~2.40 / 성격심리 **1.95~2.50** / 심리검사 1.83~2.29. 곧 성격심리는 본문
#   줄이 **하나도** 2.2 를 넘지 못해 ⑥ 이 문단을 통째로 막았고, 보고서는 2.00 이라
#   여유가 10% 뿐이었다.
#   **그 쪽의 보통 줄 거리로 잰다** — 이어지는 줄은 1.00, 문단·구역 사이라야 커진다
#   (실측 90분위: 멀쩡한 쪽 1.00~1.31, 구역이 갈린 쪽 2.4~5.2). §3.7.6 의 교훈과 같다.
#   다만 **줄이 성긴 쪽에서는 이 자를 쓸 수 없다** — 쪽 전체가 성기면 중앙값도 성겨
#   비율이 1.00 이 되어 남남인 줄까지 붙는다(§3.7.5 함정 3 이 적어 둔 발표자료·서식).
#   그래서 그런 쪽은 **종전 크기 기준으로 되돌린다**. 실측 중앙줄거리÷크기: 보통 쪽
#   1.12~2.50 / 성긴 서식 4.29 → 경계 3.0.
JOIN_PITCH_REL = 1.45    # 그 쪽의 중앙 줄거리의 이 배를 넘으면 남남으로 본다
JOIN_PITCH_SPARSE = 3.0  # 중앙 줄거리가 글자 크기의 이 배를 넘으면 '성긴 쪽'
JOIN_PITCH_MIN_N = 4     # 줄이 이보다 적으면 중앙값을 믿지 않는다(종전 크기 기준)
JOIN_SIZE_TOL = 0.20     # 글자 크기가 이만큼 안에서 같아야 한다(OCR 줄에는 보지 않는다 — SOT §3.7.11)
# 261101-1(SOT §3.7.11): 줄 끝 `-` 로 이은 말의 영어 빈도(zipf)가 이보다 낮고 앞뒤가 각각 사전 낱말이면
#   분철이 아니라 합성어다 — `-` 를 남긴다(`oval-shaped`). `satisfied`·`itself`·`otherwise` 는 모두 이 값보다 높다.
HYPHEN_PART_ZIPF = 2.0   # 그때 앞뒤 조각이 각각 이만큼 흔한 낱말이어야 한다(`volumetric` 2.6 — 3.0 이면 `volumetriconly` 로 붙었다)
HYPHEN_KEEP_ZIPF = 2.0  # 표본 조사: `twentysix` 1.19·`wellknown` 1.57 / 분철 `unconsciousness` 2.69 — 1.0 이면 앞의 둘이 붙었다
_CAPTION_REF = re.compile(r"^\s*[\[<(]?\s*(?:표|그림|사진|도표|부표)\s*[\]>)]?\s*[-.]?\s*[\d.\-]+\s*[\]>)]?"
                          r"(?:은|는|이|가|을|를|에|에서|에는|과|와|의|로|으로|처럼|및|부터|까지)(?:\s|,|$)")
# 끝까지 찬 한글 줄 뒤의 `다.` — 목록 셋째 표시가 아니라 문장 끝 `…있` + `다.` (`가.`·`나.` 는 목록 그대로, test_text_join)
_KO_LIST_HEAD = re.compile(r"^\s*다[.,]")
_CLOSERS ="”\"’')]」』"   # 문장 끝 부호 뒤에 올 수 있는 닫는 따옴표·괄호(SOT §3.7.2 ③)
# 앞 줄이 뒷줄보다 본문 폭의 이 비율 넘게 오른쪽에서 시작하면 잇지 않는다(SOT §3.7.11).
#   실측: 지우지 못한 머리말 `PROJECT HAIL MARY 5` 0.52 / 검사의이해 문단 첫 줄(앞이 그림 옆) 0.21 — 그 사이.
JOIN_LEFT_MAX = 0.40
# 261101-1(SOT §3.7.13): 들여쓰기 문단 — 첫 줄 들여쓰기는 본문 폭의 이 사이(실측 HM 3%·성격심리 4%),
#   그런 줄이 이만큼 이상이면 들여쓰기 문단 쪽. 들여쓰지 않은 줄은 왼쪽 끝에서 본문 폭의 `PARA_FLUSH` 안.
# 261102-2(SOT §3.7.14): 왼쪽 정렬 단 — 문장 끝이 아닌 줄 가운데 오른쪽이 글자 크기의 RAGGED_GAP 배 넘게 빈 비율·최소 줄 수
#   (실측 NAPA 왼쪽 정렬 단 0.6 넘게 / 양쪽 정렬 교재·보고서 0.1 아래)
RAGGED_GAP, RAGGED_SHARE, RAGGED_MIN_N = 1.0, 0.4, 4
PARA_INDENT_LO, PARA_INDENT_HI, PARA_INDENT_MIN, PARA_FLUSH =0.015, 0.08, 2, 0.01
_TOC_TAIL = re.compile(r"\s\d{1,4}$")     # 차례 항목의 끝(빈칸 + 쪽 번호) — SOT §3.7.11
_CAPTION_HEAD = None
_LIST_HEAD = None
_NUM_ONLY = re.compile(r"^(?=.*\d)[\d\s.,%+\-–−/=()×·~]*$")   # 261108-31(§3.7.2 ⑩): 수만 있는 줄(표 칸)
_MARK_ONLY = re.compile(r"^\s*[^\w\s]\s*$")     # 261108-31: 글자 하나뿐인 표시 조각(`•`·U+F0B7 …) — 줄 크기에서 뺀다
# 261108-31(SOT §3.7.16): 여러 단 항목 번호(`1.2.1 “감독자”라 함은 …`)로 시작하는 줄 — ⑤ 에서만 목록 첫 줄처럼 내어쓰기를 받는다.
#   ⑦(뒷줄 목록 표시)에는 넣지 않는다 — 점 하나짜리 `3.5 MPa` 같은 값으로 시작하는 이어지는 줄을 막게 된다(점 둘 이상만).
_HANG_HEAD = re.compile(r"^\s*\d{1,3}(?:\.\d{1,3}){2,4}\.?\s+\S")


def _starts_list(text) -> bool:
    """목록 표시로 시작하는가 — `1.` `가.` `①` `•` `-` `(1)` 등 (SOT §3.7 ⑦)."""
    global _LIST_HEAD
    if _LIST_HEAD is None:
        import re
        _LIST_HEAD = re.compile(
            r'^\s*(?:\(?\d+[.)](?!\d)|\(?[' + KO_LIST_ORDER + r'][.)]|[①-⑳]|[•·▶◊▊☞*\-–—■□-]\s|○|※|【|§)')   # `1.00 g` 는 목록이 아니다(261101-1)
    # 261108-31(SOT §3.7.16): 사용자 영역 글자(U+E000~F8FF)는 Symbol·Wingdings 글꼴의 글머리표 — 글자층이 그 글자 그대로 준다
    return bool(_LIST_HEAD.match(text or ''))


import threading as _th                                      # noqa: E402
_KIWI = {"obj": None, "bad": False}
# 260916-1: 만드는 데 1.5초 걸린다(한 번뿐). 텍스트 창 워커와 읽어 주기가 동시에
#   들어오면 둘 다 만들어 3초를 쓰므로 **만드는 동안만** 잠근다. `space()` 는 잠그지
#   않는다 — kiwi 는 여러 갈래로 부르는 것을 견디고, 여기서 잠그면 워커가 줄 선다.
# 261009-16: 이 프로세스의 kiwi 는 **자식 프로세스를 못 띄운 기기의 물러설 길**이다(`viewer.kiwi_space`).
_KIWI_LOCK = _th.Lock()


def _local_kiwi():
    """이 프로세스에서 kiwi 를 짓는다 — GIL 을 1.2초 쥐므로 자식을 못 띄웠을 때만, 워커에서만."""
    if _KIWI["bad"]:
        return None
    k = _KIWI["obj"]
    if k is None:
        with _KIWI_LOCK:
            k = _KIWI["obj"]
            if k is None and not _KIWI["bad"]:
                try:
                    from viewer.kiwi_space import make_kiwi      # 자식과 같은 설정(한 곳에서)
                    k = _KIWI["obj"] = make_kiwi()
                except Exception:
                    _KIWI["bad"] = True
    return k


def _kiwi_space(probe: str):
    """kiwi 띄어쓰기 — 자식 프로세스에 묻는다(261009-16, 응답성 SOT §4 ③). 못 물으면 None.

    자식이 아직 준비 중이면 UI 스레드는 기다리지 않고 None(기하 규칙으로), 워커는 기다린다.
    자식을 못 띄운 기기에서는 종전대로 이 프로세스에서 — 단 UI 스레드에서는 짓지 않는다."""
    from viewer import kiwi_space as _ks
    out = _ks.space(probe)
    if out is not None or not _ks.failed() or _ks.on_ui_thread():
        return out
    k = _local_kiwi()
    if k is None:
        return None
    try:
        return k.space(probe)
    except Exception:
        _KIWI["bad"] = True
        return None


def _ko_wants_space(a, b, ctx: int = 8) -> bool:
    """한글끼리 이을 때 그 자리에 빈칸이 있었나 — **말뭉치로 묻는다** (SOT §3.7.10).

    260916-1: §3.7.7 은 기하로만 갈랐고, 그래서 **양쪽 정렬된 한글 책**에서는 줄이 늘
    꽉 차 보여 언제나 '붙임' 으로 갔다(`성향적` + `관점을` → `성향적관점을`).
    §3.6.10·§3.7.7 이 두 번 재어 보고 '낱말 사전이 있어야 풀린다' 고 적어 둔 자리다 —
    **그 사전이 이미 이 프로그램에 있다**(단어장이 쓰는 `kiwipiepy`).

    앞줄 **마지막 어절**과 뒷줄 **첫 어절**만 붙여 `Kiwi.space` 에 물어, 그 자리에
    빈칸이 생기면 어절 경계로 본다. 문맥은 여덟 글자면 충분하다(스물까지 재 봐도 같다).

    실측(표본 1,011곳, `image_to_string` 의 맞는 띄어쓰기를 정답으로):
    종전 규칙 70.5% → **95.6%**. 문서별 성격심리 69.5→95.6 · 심리검사 70.7→96.5 ·
    아스팔트지침 74.4→93.2. 값이 0.23 ms/곳(자식 프로세스 왕복 0.34 ms, 261009-16)이라 쪽마다 수십 번 물어도 눈에 띄지 않는다.

    kiwi 를 못 불러오면 **False** 를 주어 부르는 쪽이 기하 규칙으로 돌아가게 한다.
    261009-16: kiwi 는 자식 프로세스에 있다(`_kiwi_space`) — 이 프로세스의 GIL 을 쥐지 않는다.
    `_KIWI["bad"]` 는 종전대로 'kiwi 를 못 쓴다' 다(물러설 길까지 실패했거나 검사가 그렇게 둔 것).
    """
    if _KIWI["bad"]:
        return False
    ta, tb = a[max(0, len(a) - ctx):], b[:ctx]
    i = ta.rfind(' ')
    head, tail = (ta[:i + 1], ta[i + 1:]) if i >= 0 else ('', ta)
    j = tb.find(' ')
    nxt, rest = (tb[:j], tb[j:]) if j >= 0 else (tb, '')
    probe = head + tail + nxt + rest
    at = len((head + tail).replace(' ', ''))      # 빈칸을 뺀 글자 수로 센다
    out = _kiwi_space(probe)
    if out is None:
        return False
    n = 0
    for x, ch in enumerate(out):
        if ch == ' ' and (x == 0 or out[x - 1] != ' ') and n == at:
            return True
        if ch != ' ':
            n += 1
            if n > at:
                break
    return False


_HAN1 = re.compile(r"[가-힣]")
_HAN_TAIL = re.compile(r"[가-힣]+$")
_HAN_HEAD = re.compile(r"^[가-힣]+")


def _kiwi_spaces(probe: str):
    """kiwi 가 띄운 자리 — 빈칸을 뺀 글자 수의 집합. 못 물으면 None."""
    if _KIWI["bad"]:
        return None
    out = _kiwi_space(probe)
    if out is None:
        return None
    pos, n = set(), 0
    for ch in out:
        if ch == " ":
            pos.add(n)
        else:
            n += 1
    return pos


def fix_ko_spacing(text: str) -> str:
    """OCR 한글 줄의 **홀로 선 한 음절**(`가 족이나`·`대 상에`)을 앞뒤 낱말에 붙일지 말뭉치에 묻는다 (SOT §3.6.15, 261101-1).

    표본 조사: 쪽마다 뽑는 붙임 문턱(§3.6.12)이 명조체 교재에서 흔들려 성격심리 48곳·심리검사의이해 75곳이 남았다.
    줄 전체를 kiwi 에 맡기면 이름(`전용신` → `전 용 신`)과 `실시 및 채점 요강과…` 를 망쳤다 — 그래서 **그 음절의 양옆 경계
    두 곳만** 묻고(앞뒤 한 토막씩 문맥을 넣어) 다른 빈칸은 건드리지 않는다. 늘 띄어 쓰는 음절(`KO_ALONE`)은 그대로.
    kiwi 를 못 쓰면(UI 스레드에서 준비 전 포함) 그대로 돌려준다."""
    if not text or not re.search(r"(?:^|\s)[가-힣](?=\s|$)", text):
        return text
    toks = text.split(" ")
    i = 0
    while i < len(toks):
        t = toks[i]
        if len(t) != 1 or not _HAN1.match(t) or t in KO_ALONE:
            i += 1
            continue
        L = toks[i - 1] if i > 0 else ""
        R = toks[i + 1] if i + 1 < len(toks) else ""
        lh = _HAN_TAIL.search(L) if (L and L not in KO_ALONE) else None
        rh = _HAN_HEAD.match(R) if (R and R not in KO_ALONE) else None
        if not lh and not rh:
            i += 1
            continue
        a = lh.group(0) if lh else ""
        b = rh.group(0) if rh else ""
        L2 = toks[i - 2] if (lh and a == L and i > 1 and re.fullmatch(r"[가-힣]+", toks[i - 2])) else ""
        r2 = _HAN_HEAD.match(toks[i + 2]) if (rh and b == R and i + 2 < len(toks)) else None
        R2 = r2.group(0) if r2 else ""
        pos = _kiwi_spaces((L2 + " " if L2 else "") + a + t + b + (" " + R2 if R2 else ""))
        if pos is None:
            return " ".join(toks)
        off = len(L2)
        join_r = bool(rh) and (off + len(a) + 1) not in pos
        join_l = bool(lh) and (off + len(a)) not in pos
        if join_r:
            toks[i] = t + R
            del toks[i + 1]
        if join_l:
            toks[i - 1] = L + toks[i]
            del toks[i]
            i -= 1
        i += 1
    return " ".join(toks)


def _hyphen_keep(a, b) -> bool:
    """줄 끝 `-` 가 분철이 아니라 **합성어의 붙임표**인가 (SOT §3.7.3·§3.7.11, 261101-1).

    `oval-` + `shaped` → `ovalshaped` 는 사전에 없고 `oval`·`shaped` 는 각각 낱말이다 → 남긴다.
    `satis-` + `fied` → `satisfied` 는 사전에 있다 → 뗀다. 사전을 못 쓰면 False(종전대로 뗀다)."""
    import re
    ma = re.search(r"([A-Za-z]+)-$", a)
    mb = re.match(r"([a-z]+)", b)
    if not ma or not mb:
        return False
    wa, wb = ma.group(1).lower(), mb.group(1)
    try:
        from viewer.study.wordfreq_fast import zipf_frequency
        return (zipf_frequency(wa + wb, "en") < HYPHEN_KEEP_ZIPF
                and zipf_frequency(wa, "en") >= HYPHEN_PART_ZIPF and zipf_frequency(wb, "en") >= HYPHEN_PART_ZIPF)
    except Exception:
        return False


def _dehyphen_ligature(a, b) -> str:
    """분철을 이은 낱말이 `fi`↔`fl` 합자를 바꿔 읽은 것이면 뒷줄 첫머리를 고친다 (SOT §3.5.3, 261101-1).

    `satis-` + `fled.` — `fled` 는 저 혼자 사전 낱말이라 OCR 단계에서는 고칠 수 없고, 이어야 `satisfled` 가 드러난다."""
    ma = re.search(r"([A-Za-z]+)$", a or "")
    mb = re.match(r"([a-z]+)(.*)$", b or "", re.S)
    if not ma or not mb:
        return b
    try:
        from viewer.text_noise import fix_ligature
        got = fix_ligature(ma.group(1) + mb.group(1))
    except Exception:
        got = None
    if got and got.lower().startswith(ma.group(1).lower()):
        return got[len(ma.group(1)):] + mb.group(2)
    return b


def _join_sep(a_text, b_text, wrapped: bool = False) -> str:
    """두 줄을 어떻게 이을지 — 빈칸 / 붙임 / 분철 떼기 (SOT §3.7·§3.7.7·§3.7.10).

    `wrapped` 는 **어절이 안 들어가서 넘어갔는가**(④ 의 둘째 갈래). 참이면 줄이 바뀐
    자리는 **어절 경계**이므로 한글끼리라도 빈칸을 넣는다. 거짓(줄이 여백까지 꽉 참)이면
    낱말 가운데서 잘렸을 수 있어 붙인다 — 실측 `의무사` + `용대상` = `의무사용대상`.

    260916-1(§3.7.10): 한글끼리는 기하보다 **말뭉치**가 낫다(70.5% → 95.6%). 기하는
    kiwi 가 없을 때의 폴백으로 남는다.
    """
    if a_text.endswith(' '):
        return ' '
    a = a_text.rstrip()
    b = (b_text or '').lstrip()
    if not a or not b:
        return ''
    if a.endswith('-') and ('a' <= b[0] <= 'z'):
        return '' if _hyphen_keep(a, b) else '-drop'
    # 261101-1: `Performance-` + `Based` — 대문자로 이어지면 분철일 수 없다(합성어) — 붙임표를 남기고 붙인다
    if re.search(r"[A-Za-z]{2,}-$", a) and b[0].isupper() and b[:1].isalpha():
        return ''
    # 261101-1: 줄 끝에서 끊긴 웹 주소는 빈칸 없이 잇는다(NAPA 10쪽 `https://doi.org/10.1080/` + `14680629.2022…`)
    if re.search(r"(?:https?://|www\.|doi\.org/)\S*$", a) and not b[0].isspace() and a[-1] in "/.-_=?&#":
        return ''
    if _is_cjk(a[-1]) and _is_cjk(b[0]):
        if _ko_wants_space(a, b):
            return ' '
        return ' ' if wrapped else ''
    return ' '


def join_text(a_text, b_text, wrapped: bool = False) -> str:
    """두 글을 §3.7.3 의 규칙 **그대로** 잇는다 — 빈칸 / 붙임 / 분철 떼기(`_join_sep`·`_dehyphen_ligature`).

    261108-31(영상·음성 SOT §1.8 의 1): 본문 읽기는 창이 잇지 않은 줄(문장부호로 끝나지 않음)을 한 문장으로 한 번 더 잇는데,
    종전에는 늘 빈칸으로 이어 한글 낱말이 줄 끝에서 갈린 곳(`취사` + `선택`)을 '취사 선택' 으로 읽었다. 잇는 규칙은 이 하나다."""
    a = (a_text or "").rstrip()
    b = (b_text or "").lstrip()
    if not a:
        return b
    if not b:
        return a
    sep = _join_sep(a_text or "", b, wrapped)
    if sep == '-drop':
        a = a[:-1]
        return a + _dehyphen_ligature(a, b)
    return a + sep + b


def _is_toc_rows(rows) -> bool:
    """목차 쪽인가(SOT §3.7.15) — 여러 단 번호 목차(`toc_text_lines`, 단어학습 SOT §14.8.4) 또는 한 단계 번호 목차(`toc_tail_lines`).
    261103-13(사용자 보고): 교재 목차(`1. 아이젱크의 … 151`)는 앞의 판정에 걸리지 않아 `…모델 158` 과 `요약 162` 가 한 줄로 이어졌다."""
    from viewer.study.ocr_pages import toc_text_lines, toc_tail_lines
    texts = [r.get('text') or '' for r in rows]
    return toc_text_lines(texts) or toc_tail_lines(texts)


_TOC_NO_OK = re.compile(r"(\d{1,2})\.\s")
_TOC_NO_BAD = re.compile(r"(\d{1,2}|[A-Za-z])[.,]?\s+(?=[가-힣A-Za-z])")


def fix_toc_numbers(rows) -> list:
    """목차 쪽의 **잘못 읽은 항목 번호**를 앞뒤 줄 번호로 바로잡는다 (SOT §3.6.17, 261103-14 사용자 지시).

    `3. 성격 발달 180` / `A 성격 평가기법 183` / `5. 성격이론의 적용 185` → `4. 성격 평가기법 183`.
    `1, 아이젱크의 …`·`2 주요 개념` 처럼 점을 못 읽거나 쉼표로 읽은 것도 `1.`·`2.` 로. 바로 위·아래 줄의 번호만 본다 —
    사이에 `요약`·`제7장` 이 끼면 그 줄은 이웃이 아니다. 글자로 읽은 번호(`A`)는 **위·아래가 둘 다** 맞을 때만,
    숫자로 읽은 번호는 그 숫자가 이웃 번호에서 나온 값과 같을 때만 고친다. 목차 쪽(`_is_toc_rows`)이 아니면 그대로 돌려준다."""
    body = [r for r in rows if r.get('kind') == 'text' and (r.get('text') or '').strip()]
    if len(body) < 3 or not _is_toc_rows(body):
        return rows

    def _ok(r):
        m = _TOC_NO_OK.match((r.get('text') or '').lstrip()) if r is not None else None
        return int(m.group(1)) if m else None
    for _ in range(3):                       # `1 융` / `2 주요` / `3. …` — 아래에서 고친 번호로 위를 다시 본다
        changed = False
        for i, r in enumerate(body):
            t = (r.get('text') or '').lstrip()
            if _TOC_NO_OK.match(t):
                continue
            m = _TOC_NO_BAD.match(t)
            if not m:
                continue
            p = _ok(body[i - 1]) if i > 0 else None
            n = _ok(body[i + 1]) if i + 1 < len(body) else None
            if p is not None and n is not None:
                k = p + 1 if p + 1 == n - 1 else None
            else:
                k = p + 1 if p is not None else (n - 1 if n is not None else None)
            head = m.group(1)
            if not k or k < 1:
                continue
            if head.isdigit():
                if int(head) != k:
                    continue
            elif p is None or n is None:
                continue
            r['text'] = "%d. %s" % (k, t[m.end():])
            changed = True
        if not changed:
            break
    return rows


def join_sentences(rows, why_out=None) -> list:
    """종이 때문에 끊긴 줄을 **한 문장으로** 잇는다 (SOT §3.7).

    `why_out`(261108-31, 측정 도구 `scripts/join_gaps.py`)에 list 를 주면 잇지 않은 이웃 줄마다 (앞 줄, 뒷줄, 막은 조건들)을 덧붙인다 — 잇는 결과는 같다.

    문장부호만으로 판단하지 않는다 — 제목·표 제목·그림 제목도 부호로 끝나지 않는다.
    가장 강한 신호는 **줄이 오른쪽 여백까지 찼는가** 다(실측: 이어지는 본문 1.00,
    제목·문단 마지막 줄 0.28~0.94).
    """
    body = [r for r in rows
            if r.get('rect') and r.get('style') == 'body'
            and r.get('kind') == 'text' and ' | ' not in r.get('text', '')]
    if len(body) < 2:
        return list(rows)
    # 261102-2(SOT §3.7.15): 목차 쪽은 잇지 않는다 — OCR 이 쪽 번호·점선을 못 읽으면 제목 줄이 오른쪽까지 찬
    #   문단처럼 보여 `3.1 …` 뒤에 `3.2 …`·`3.3 …` 이 붙었다(_96 5쪽). 판정은 OCR 목차 쪽과 같은 것(단어학습 SOT §14.8.4).
    if _is_toc_rows(body):
        return list(rows)
    # 260910-12(사용자 보고 "부호로 잇는 규칙이 적용 안 된다", SOT §3.7.8):
    #   여백은 **단마다** 잰다. 쪽 하나로 재면 2단 쪽에서 왼쪽 단이 한 줄도 못 잇는다 —
    #   실측 1쪽: 쪽 전체 90분위 556.9 인데 왼쪽 단은 **가장 긴 줄도 300.2** 라
    #   ④(오른쪽까지 찼는가)가 언제나 거짓이었다.
    cols = _column_extents(body)
    med_pitch = _median_pitch(body, cols)          # 261108-31(SOT §3.7.16): 단마다
    indents = _para_indents(cols, body)
    ragged = _ragged_cols(cols, body)
    idx = {id(q): i for i, q in enumerate(body)}
    out = []
    for r0 in rows:
        r = dict(r0)
        r.setdefault('rects', [r['rect']] if r.get('rect') else [])
        prev = out[-1] if out else None
        # 260910-12: 이웃한 줄(같은 단, 앞뒤 4줄)로 **그 자리의** 여백을 본다.
        # 261108-31(SOT §3.7.16): 찾기는 **원래 줄**로 — 종전에는 위에서 만든 사본(`dict(r)`)의 id 로 찾아 늘 못 찾았고,
        #   그래서 이 이웃 여백이 한 번도 쓰이지 않았다(단 전체 여백만). cao 1쪽은 전폭 초록이 왼쪽 단과 같은 무리라
        #   왼쪽 단 여백이 569 로 잡혀 왼쪽 단 줄이 하나도 이어지지 않았다(실제 끝 294).
        _k = idx.get(id(r0))
        _near = None
        if _k is not None:
            _lo, _hi = max(0, _k - 4), min(len(body), _k + 5)
            # 261108-31(SOT §3.7.16): 높이로도 가까운 줄만 — 차례로만 이웃이고 멀리 떨어진 줄(가로 줄 위의 전폭 초록·DOI 줄)이
            #   그 자리 여백을 넓히지 않게. 글자 크기의 `JOIN_NEAR_Y` 배(줄 넷 남짓) 안.
            _ny = max(1.0, r.get('size') or 10.0) * JOIN_NEAR_Y
            _near = [q for q in body[_lo:_hi]
                     if abs(q['rect'][0] - r['rect'][0]) <= 24.0 and abs(q['rect'][1] - r['rect'][1]) <= _ny]
            # 261108-31 보완(SOT §3.7.16): 그 끝에 한 줄만 닿으면(대개 잇기를 따지는 앞 줄 자신) **숫자가 낀 짝**에는 쓰지 않는다 —
            #   들쭉날쭉한 짧은 줄 무리(차례·표의 수)에서 ④ 가 늘 '찼다' 가 됐다(`…같다` + `12 34 56 78`). §3.7.14 의 숫자 예외와 같다.
            #   글은 살린다 — 좁은 글머리표 항목(`…asphalt mixture` ⏎ `production rate.`, NAPA 8·10쪽)은 이웃 여백으로 잇는다.
            if _near and prev is not None:
                _loc = max(q['rect'][2] for q in _near)
                _tol = max(1.0, r.get('size') or 10.0) * JOIN_FILL
                _pt = (prev.get('_tail') or prev.get('text') or '').rstrip()
                if (sum(1 for q in _near if _loc - q['rect'][2] <= _tol) < 2
                        and (re.search(r"\d$", _pt) or re.match(r"\s*\d", r.get('text') or ''))):
                    _near = None
        margin, span = _extent_for(cols, r, _near)
        rg = bool(r.get('rect')) and any(g0 - 0.5 <= r['rect'][0] <= g1 + 0.5 for g0, g1 in ragged)
        _why = [] if why_out is not None else None
        if prev is not None and (_can_join(prev, r, margin, span, med_pitch, ragged=rg, why=_why)
                                 or (r.get('ocr') and prev.get('ocr') and _continues_para(r, indents)
                                     and _can_join(prev, r, margin, span, med_pitch, para=True))):
            # ★ 조건 판정은 **마지막에 붙인 줄**로 한다(`_can_join` 안에서 `_last`).
            # 260910-4(SOT §3.7.7): 왜 넘어갔는지가 빈칸 여부를 가른다.
            #   어절이 안 들어가서 넘어갔으면 그 자리는 어절 경계다.
            _ra = prev.get('_last') or prev['rect']
            _sa = max(1.0, prev.get('size') or 0)
            _wrapped = (margin - _ra[2]) > _sa * JOIN_FILL
            sep = _join_sep(prev.get('_tail', prev['text']), r['text'], _wrapped)
            a = prev['text']
            b_txt = r['text'].lstrip()
            # 261103-15(SOT §5.1.5): 원래 줄마다의 글 — 본문에서 줄 상자 하나를 늘리면 텍스트 창이 그 줄 자리에 넣는다
            # 261104-11: 키는 'line_texts'(글 목록) — 'parts' 는 (자리, 글) 짝 목록(text_fix_store·text_apply)이라 같은 이름이면 [PDF 에 반영]·Word 가 깨졌다
            prev['line_texts'] = list(prev.get('line_texts') or [a]) + list(r.get('line_texts') or [b_txt])
            if sep == '-drop':
                a, sep = a.rstrip()[:-1], ''
                b_txt = _dehyphen_ligature(a, b_txt)
            prev['text'] = a.rstrip() + sep + b_txt
            prev['rects'] = list(prev.get('rects', [])) + list(r.get('rects', []))
            pr, rr = prev['rect'], r['rect']
            prev['rect'] = (min(pr[0], rr[0]), min(pr[1], rr[1]),
                            max(pr[2], rr[2]), max(pr[3], rr[3]))
            prev['_last'] = rr           # 다음 판정의 기준
            prev['_tail'] = r['text']    # 끝의 빈칸도 마지막 줄의 것
            continue
        if why_out is not None and prev is not None:
            why_out.append((dict(prev), dict(r), list(_why or [])))
        out.append(r)
    for r in out:
        r['text'] = r['text'].rstrip()
        r.pop('_last', None)
        r.pop('_tail', None)
    return out


# 261108-31(SOT §3.7.16): 단을 넘어 이을 앞 줄을 찾을 때의 글자 크기 허용 — ⑧ 의 20% 보다 좁다. 사이에 낀 각주(8.5pt)를
#   본문(9.5pt, 차 10.5%)으로 보지 않게(cao 1쪽).
JOIN_COL_SIZE_TOL = 0.05
JOIN_NEAR_Y = 5.0        # 261108-31(§3.7.16): 이웃 여백을 볼 줄 — 위아래로 글자 크기의 이 배 안


def join_columns(rows) -> list:
    """**왼쪽 단 끝 → 오른쪽 단 처음**으로 넘어간 문장을 잇는다 (SOT §3.7.16, 261108-31).

    `join_sentences` 는 바로 앞 줄과만 잇는다. 단을 넘어간 문장은 사이에 각주·꼬리 글이 끼어(그 단의 아래쪽)
    이웃이 아니다 — 실측 cao 1쪽 `…Ministry of Com-` ⏎(각주 넷)⏎ `munications 2004. With …`.
    뒷줄 B 가 **단의 첫 줄**(앞 줄보다 위로 올라가고 오른쪽으로 옮김)이면, 그 앞의 **본문 줄 A**(B 와 글자 크기가 비슷한 마지막 줄)와
    잇는다. 조건: A 가 문장 끝 부호로 끝나지 않고, A 의 마지막 줄이 그 단 오른쪽 끝까지 찼고, B 가 목록·표·그림 제목으로
    시작하지 않으며, ㄱ) A 가 `-` 로 끝나거나 ㄴ) B 가 라틴 소문자로 시작하거나 ㄷ) 앞뒤가 한글·한자. 잇는 법은 §3.7.3(`join_text`)."""
    out = [dict(r) for r in rows]
    i = 1
    while i < len(out):
        b, p = out[i], out[i - 1]
        rb = b.get('rect')
        rp = (p.get('rects') or [p.get('rect')])[-1] if p.get('rect') else None    # 이은 줄이면 그 마지막 줄 자리로
        if not (rb and rp and b.get('kind') == 'text' and b.get('style') == 'body'):
            i += 1
            continue
        if not (rb[1] < rp[1] - 2 * max(1.0, b.get('size') or 10) and rb[0] > rp[0] + 0.25 * max(1.0, rp[2] - rp[0])):
            i += 1
            continue
        sb = max(1.0, b.get('size') or (rb[3] - rb[1]))
        j = i - 1
        while j >= 0:
            q = out[j]
            if q.get('kind') == 'text' and q.get('style') == 'body' and q.get('rect') \
                    and abs(max(1.0, q.get('size') or 0) - sb) <= max(0.3, sb * JOIN_COL_SIZE_TOL) \
                    and ' | ' not in (q.get('text') or ''):
                break
            j -= 1
        if j < 0:
            i += 1
            continue
        a = out[j]
        ta = (a.get('line_texts') or [a.get('text') or ''])[-1].rstrip()
        tb = (b.get('text') or '').lstrip()
        la = (a.get('rects') or [a['rect']])[-1]
        # A 의 단 오른쪽 끝 — 같은 왼쪽 끝이면서 B 의 단보다 왼쪽에서 끝나는 줄만(전폭 초록·제목은 빼고)
        same_col = [q for q in out[:i] if q.get('rect') and abs(q['rect'][0] - a['rect'][0]) <= 2 * sb
                    and q['rect'][2] <= rb[0]]
        right = max(q['rect'][2] for q in same_col) if same_col else la[2]
        ok = (ta and tb and ta[-1] not in SENT_END and ta.rstrip(_CLOSERS)[-1:] not in SENT_END
              and right - la[2] <= sb * JOIN_FILL and not _starts_list(tb) and not _is_caption(tb)
              and ' | ' not in tb
              and (ta.endswith('-') or re.match(r"[a-z]", tb) or (_is_cjk(ta[-1]) and _is_cjk(tb[0]))))
        if not ok:
            i += 1
            continue
        a['text'] = join_text(a.get('text') or '', tb)
        a['line_texts'] = list(a.get('line_texts') or [a.get('text')]) + list(b.get('line_texts') or [tb])
        a['rects'] = list(a.get('rects') or [a['rect']]) + list(b.get('rects') or [rb])
        del out[i]                                  # B 는 A 에 들어갔다 — 그 자리는 비운다(자리는 A 의 rects 에)
    return out


def as_body(rows) -> list:
    """텍스트 창·텍스트 창 Word 저장용 — 모든 글 줄을 **본문**으로 (SOT §3.4, 261102-2 사용자 결정).

    '제목' 은 글자 크기로 가린 짐작이라 OCR 쪽에서 엉뚱한 줄(끊긴 어절)에 제목 글꼴이 붙었다. 제목 판정은 줄 잇기(§3.7 ①)와
    형식 변환(형식 변환 SOT)에서만 쓰고, 텍스트 창에는 보이지 않는다."""
    out = []
    for r in rows:
        if r.get("style") == "title":
            r = dict(r, style="body")
        out.append(r)
    return out


def join_hyphens(rows) -> list:
    """'문장 잇기' 를 꺼도 **줄 끝 하이픈으로 끊긴 영문 낱말만** 잇는다 (SOT §3.7.4, 261101-1 사용자 결정).

    앞 줄이 `글자-` 로 끝나고 뒷줄이 소문자로 시작하는 본문 줄 둘 — 뒷줄의 **첫 낱말만** 앞 줄로 옮기고
    (`labora-` + `tory is …` → `laboratory` / `is …`) 나머지 줄은 그대로 둔다. 줄 수와 자리가 원본 줄과 같다 —
    뒷줄이 그 낱말 하나뿐이면 그 줄은 없어지고 자리는 앞 줄에 합친다.
    붙임표를 남길지는 §3.7.3 그대로(`_join_sep`)."""
    out = [dict(r) for r in rows]
    for a, b in zip(out, out[1:]):
        ta, tb = (a.get('text') or '').rstrip(), (b.get('text') or '').lstrip()
        # 뒷줄이 소문자(분철·합성어) 또는 대문자 합성어(`Performance-` + `Based`)로 시작할 때만
        if not (ta and tb and re.search(r"[A-Za-z]-$", ta) and re.match(r"[A-Za-z]", tb)
                and (tb[0].islower() or re.search(r"[A-Za-z]{2,}-$", ta))):
            continue
        if any(r.get('style') != 'body' or r.get('kind') != 'text' or CELL_SEP in (r.get('text') or '') for r in (a, b)):
            continue
        head, _sp, rest = tb.partition(" ")
        m = re.match(r"([A-Za-z]+)(.*)$", head)
        word, punct = (m.group(1), m.group(2)) if m else (head, "")
        sep = _join_sep(ta, tb)
        if sep == '-drop':
            ta = ta[:-1]
            word = _dehyphen_ligature(ta, word)
        a['text'] = ta + word + punct
        b['text'] = rest
        if not rest.strip():                  # 뒷줄이 그 낱말 하나뿐이었다 — 자리를 앞 줄에 합친다(고침이 자리로 되맞춰지게)
            a['rects'] = list(a.get('rects') or [a.get('rect')]) + list(b.get('rects') or [b.get('rect')])
    return [r for r in out if (r.get('text') or '').strip() or r.get('kind') != 'text']


def page_carry(prev_rows, rows) -> bool:
    """쪽을 넘어간 문장을 잇는다 — 앞 쪽 마지막 줄 + 다음 쪽 첫 줄 (SOT §3.7.12, 261101-1).

    **여러 쪽을 한 글로 만드는 곳**(Word 저장·단어장 글)만 부른다 — 텍스트 창은 쪽마다 보여 주므로 잇지 않는다.
    이으면 `prev_rows[-1]['text']` 를 늘리고 `rows[0]` 을 지운 뒤 True. 두 목록은 고쳐 쓴다.
    조건: 두 줄이 §3.7.2 의 ①②③⑦ 을 만족하고, 앞 줄이 그 단 오른쪽 끝까지 찼다(④ 의 첫 갈래).
    자리·거리(⑤⑥)는 쪽이 달라 재지 않는다. 빈칸은 §3.7.3 그대로(`_join_sep`)."""
    if not prev_rows or not rows:
        return False
    a, b = prev_rows[-1], rows[0]
    for r in (a, b):
        if r.get('style') != 'body' or r.get('kind') != 'text' or ' | ' in (r.get('text') or ''):
            return False                                    # ①②
    ta, tb = (a.get('text') or '').rstrip(), (b.get('text') or '').lstrip()
    if not ta or not tb or ta[-1] in SENT_END or ta[-1] in '”"’)':
        return False                                        # ③ (닫는 따옴표로 끝난 대화문도 끝난 것)
    if _starts_list(tb) and not _unclosed_paren(ta):
        return False                                        # ⑦
    ra = (a.get('rects') or [a.get('rect')])[-1] if (a.get('rects') or a.get('rect')) else None
    if not ra:
        return False
    body = [r for r in prev_rows if r.get('rect') and r.get('style') == 'body' and r.get('kind') == 'text']
    margin, _span = _extent_for(_column_extents(body), {'rect': ra})
    sa = max(1.0, a.get('size') or (ra[3] - ra[1]))
    if margin <= 0 or (margin - ra[2]) > sa * JOIN_FILL:
        return False                                        # ④ 앞 줄이 차지 않았다 — 문단이 끝났다
    sep = _join_sep(a.get('text') or '', tb)
    if sep == '-drop':
        ta, sep = ta[:-1], ''
        tb = _dehyphen_ligature(ta, tb)
    a['text'] = ta + sep + tb
    del rows[0]
    return True


def _para_indents(cols, body) -> list:
    """단마다 **들여쓰기로 문단을 가르는가** → `[(g0, g1, 왼쪽 끝, 본문 폭)]` (SOT §3.7.13, 261101-1).

    표본 조사(HM_bm 12쪽 27곳·성격심리 7곳): 소설·교재는 문단 첫 줄을 들여 쓰고, 문단 안에서도 줄 끝에서 문장이
    끝난다. 그 쪽에 들여쓴 줄(왼쪽 끝 + 본문 폭의 `PARA_INDENT_LO`~`PARA_INDENT_HI`)이 `PARA_INDENT_MIN` 개 이상이면
    들여쓰기 문단으로 본다. 들여쓰기가 없는 문서(문단 사이를 띄우는 보고서)에는 걸리지 않는다."""
    out = []
    for g0, g1, _margin, span in cols:
        if span <= 0:
            continue
        mine = sorted(r['rect'][0] for r in body if g0 - 0.5 <= r['rect'][0] <= g1 + 0.5)
        if len(mine) < 4:
            continue
        left = mine[len(mine) // 5]
        ind = sum(1 for x in mine if left + span * PARA_INDENT_LO <= x <= left + span * PARA_INDENT_HI)
        if ind >= PARA_INDENT_MIN:
            out.append((g0, g1, left, span))
    return out


def _continues_para(b, indents) -> bool:
    """뒷줄이 들여쓰기 문단 단에서 **들여쓰지 않고** 시작하는가 — 그러면 앞 문단이 이어진다(§3.7.13)."""
    rb = b.get('rect')
    if not rb or not indents:
        return False
    for g0, g1, left, span in indents:
        if g0 - 0.5 <= rb[0] <= g1 + 0.5:
            return abs(rb[0] - left) <= span * PARA_FLUSH
    return False


def _median_pitch(body, cols=None) -> float:
    """그 쪽 본문의 **보통 줄 거리**(위끝~위끝의 중앙값) (SOT §3.7.9, 260916-1).

    줄이 `JOIN_PITCH_MIN_N` 에 못 미치면 0 을 준다 — 부르는 쪽이 종전 크기 기준을 쓴다.
    `cols`(`_column_extents`)를 주면 **단마다** 위아래 이웃 줄끼리만 잰다(261108-31, SOT §3.7.16) — 쪽 전체를 높이로만
    늘어놓으면 2단 쪽에서 왼쪽·오른쪽 단 줄이 번갈아 와(높이 차 0.1pt·12.9pt) 중앙값이 본문 줄 거리보다 작게 나왔다
    (NAPA 1쪽 8.5 대 13.0 — 본문 줄이 ⑥ 에 막혀 한 쪽에서 161곳이 끊겼다).
    """
    if len(body) < JOIN_PITCH_MIN_N:
        return 0.0
    groups = [body]
    if cols:
        groups = [[r for r in body if g0 - 0.5 <= r['rect'][0] <= g1 + 0.5] for g0, g1, _m, _s in cols]
    ps = []
    for g in groups:
        rows = sorted(g, key=lambda r: (r['rect'][1], r['rect'][0]))
        ps.extend(b['rect'][1] - a['rect'][1]
                  for a, b in zip(rows, rows[1:])
                  if b['rect'][1] - a['rect'][1] > 0)
    ps.sort()
    if len(ps) < JOIN_PITCH_MIN_N - 1:
        return 0.0
    return ps[len(ps) // 2]


def _first_word_width(b) -> float:
    """뒷줄 **첫 어절**의 대략 폭 (SOT §3.7.6 가).

    글꼴·크기를 따로 알 필요가 없게 **그 줄 자신에게서** 기준을 뽑는다 —
    줄 폭 ÷ 글자 수로 글자 하나의 평균 폭을 구하고 첫 어절 글자 수를 곱한다.
    한글/영문이 섞여도, 두 단 편집이라 쪽마다 폭이 달라도 스스로 맞는다.
    """
    t = (b.get('text') or '').strip()
    rb = b.get('rect')
    if not t or not rb:
        return 0.0
    avg = (rb[2] - rb[0]) / max(1, len(t))
    return avg * len(t.split(' ', 1)[0])


def _is_caption(t) -> bool:
    """표·그림 제목으로 시작하는가 (SOT §3.7.6 다).

    260910-4: 캡션은 부호로 끝나지 않고 길이도 본문과 비슷할 수 있어 ④ 만으로는
    본문과 갈리지 않는다. 그런데 **첫머리는 규칙적이다** — `표 1` `그림 2`
    `<표 3>` `Table 1` `Figure 2`. 그 표시를 직접 본다.
    """
    global _CAPTION_HEAD
    if _CAPTION_HEAD is None:
        import re
        _CAPTION_HEAD = re.compile(
            r'^\s*[\[<(]?\s*(?:표|그림|사진|도표|부표|Table|Figure|Fig|Photo)'
            r'\s*[\]>)]?\s*[-.]?\s*\d', re.IGNORECASE)
    if not _CAPTION_HEAD.match(t or ''):
        return False
    # 261101-1: 번호 바로 뒤에 조사가 붙으면(`<표 1.3>은`·`그림 2에서`) 표를 **가리키는 본문 문장**이다 —
    #   글자층 보고서에서 `<표 1.3>은 … 총 58개 지역이 도출` + `되었으며` 가 갈렸다(4곳)
    return not _CAPTION_REF.match(t)


def _unclosed_paren(t) -> bool:
    """앞줄에 닫히지 않은 `(` 가 있는가 (SOT §3.7.6 나).

    있으면 뒷줄 첫머리의 `)` 는 그 괄호를 닫는 **이어지는 글**이지 목록 표시가 아니다.
    실측: `…아스팔트 함량 시험 포` + `함)을 평가하는…` — `시험(` 이 열려 있었다.
    """
    t = t or ''
    return t.count('(') > t.count(')')


def _column_extents(body) -> list:
    """단마다 (왼쪽끝 범위, 오른쪽 여백, 본문 폭) (SOT §3.7.8).

    260910-12: §3.7 의 ④ 는 '이 줄이 오른쪽 여백까지 찼는가' 를 본다. 그 여백을
    **쪽 하나로** 재면 2단 쪽에서 왼쪽 단이 통째로 탈락한다 — 왼쪽 단의 가장 긴 줄도
    오른쪽 단의 여백보다 한참 짧기 때문이다(실측 1쪽: 300.2 대 556.9).

    단은 **왼쪽 끝이 일정하다**(§3.6.1). 그래서 왼쪽 끝을 무리 지어 단을 가른다.
    사이가 본문 폭의 10% 넘게 벌어지면 다른 단으로 본다. 1단 쪽이면 무리가 하나라
    종전과 똑같이 동작한다.
    """
    if not body:
        return []
    xs = sorted(r['rect'][0] for r in body)
    lo = xs[0]
    hi = max(r['rect'][2] for r in body)
    gap = max(1.0, (hi - lo) * 0.10)
    groups = [[xs[0]]]
    for x in xs[1:]:
        if x - groups[-1][-1] > gap:
            groups.append([x])
        else:
            groups[-1].append(x)
    out = []
    for g in groups:
        g0, g1 = g[0], g[-1]
        mine = [r for r in body if g0 - 0.5 <= r['rect'][0] <= g1 + 0.5]
        if not mine:
            continue
        rights = sorted(r['rect'][2] for r in mine)
        margin = rights[int(len(rights) * 0.9)]
        lefts = sorted(r['rect'][0] for r in mine)
        span = margin - lefts[int(len(lefts) * 0.1)]
        out.append((g0, g1, margin, span))
    return out


def _extent_for(cols, r, near=None):
    """그 줄이 속한 단의 (여백, 본문 폭). 못 찾으면 가장 가까운 단 (SOT §3.7.8).

    `near` 는 **바로 이웃한 줄들**이다. 주면 그 안의 가장 긴 오른쪽 끝을 여백으로 쓴다 —
    그림 옆으로 글이 좁게 흐르는 구간은 단 전체보다 여백이 앞에 있기 때문이다
    (실측 1쪽 'DEFINITION OF BMD' 문단: 단 여백 292.9, 그 문단은 260 에서 끝난다).
    단 여백보다 넓어지지는 않게 묶어 둔다.
    """
    rc = r.get('rect')
    if not cols or not rc:
        return (0.0, 0.0)
    x0 = rc[0]
    got = None
    for g0, g1, margin, span in cols:
        if g0 - 0.5 <= x0 <= g1 + 0.5:
            got = (margin, span)
            break
    if got is None:
        best = min(cols, key=lambda c: min(abs(x0 - c[0]), abs(x0 - c[1])))
        got = (best[2], best[3])
    if near:
        loc = max(q['rect'][2] for q in near if q.get('rect'))
        if loc < got[0]:
            return (loc, got[1])
    return got


def _ragged_cols(cols, body) -> list:
    """**왼쪽 정렬(오른쪽이 들쭉날쭉한)** 단 → `[(g0, g1)]` (SOT §3.7.14, 261102-2).

    ④ 의 둘째 갈래('뒷줄 첫 어절이 그 빈칸에 들어갔겠는가')는 양쪽 정렬 글을 전제로 한다. 왼쪽 정렬 글은 줄 끝이 15~33pt 씩
    들쭉날쭉해, 짧은 낱말(`BMD`·`the`·`to`)이 다음 줄에 오면 문단이 끝난 것으로 잘못 봤다(NAPA 2·3쪽 7곳 — '건너뛰기' 와 무관).
    문장 끝 부호로 끝나지 않는 낱말 셋 이상 줄 가운데 오른쪽이 글자 크기의 `RAGGED_GAP` 배 넘게 빈 것이 `RAGGED_SHARE`
    이상(그런 줄 `RAGGED_MIN_N` 개 이상)이면 왼쪽 정렬 단이다. 양쪽 정렬 글은 그런 줄이 거의 없다."""
    out = []
    for g0, g1, margin, _span in cols:
        mine = [r for r in body if g0 - 0.5 <= r['rect'][0] <= g1 + 0.5]
        mid = [r for r in mine
               if len((r.get('text') or '').split()) >= 3
               and (r.get('text') or '').rstrip().rstrip(_CLOSERS)[-1:] not in SENT_END]
        if len(mid) < RAGGED_MIN_N:
            continue
        loose = sum(1 for r in mid if margin - r['rect'][2] > max(1.0, r.get('size') or 1.0) * RAGGED_GAP)
        if loose >= len(mid) * RAGGED_SHARE:
            out.append((g0, g1))
    return out


def _no(why, tag: str) -> bool:
    """`_can_join` 이 잇지 않을 때 — `why` 가 list 면 막은 조건을 적는다(261108-31, 측정 도구 `scripts/join_gaps.py`)."""
    if why is not None:
        why.append(tag)
    return False


def _can_join(a, b, margin, span: float = 0.0, med_pitch: float = 0.0, para: bool = False,
              ragged: bool = False, why=None) -> bool:
    """SOT §3.7 의 여덟 조건을 모두 본다.

    `para=True`(§3.7.13): 들여쓰기 문단 단에서 뒷줄이 들여쓰지 않았다 — ③(문장 끝)을 보지 않는 대신 앞 줄이
    **오른쪽 끝까지 찼어야** 한다(④ 의 첫 갈래만). 나머지 조건은 그대로."""
    # ★ 260910: 이미 이어 붙인 줄이면 **마지막에 붙인 줄**로 잰다. 합친 사각형으로 재면
    #   오른쪽 끝이 늘 여백까지 차 있어 ④ 가 무력해진다(문단 마지막 줄까지 붙는다).
    ra = a.get('_last') or a.get('rect')
    rb = b.get('rect')
    if not ra or not rb:
        return _no(why, 'rect')
    ta = a.get('_tail', a.get('text', ''))
    tb = b.get('text', '')
    if a.get('style') != 'body' or b.get('style') != 'body':
        return _no(why, '①')                                    # ①
    if a.get('kind') != 'text' or b.get('kind') != 'text':
        return _no(why, '①')                                    # ①
    if ' | ' in ta or ' | ' in tb:
        return _no(why, '②')                                    # ②
    core = ta.rstrip()
    # 261101-1(SOT §3.7.11): 닫는 따옴표·괄호 **앞**의 부호로 본다 — `…two-i-pi.”` 다음 문단이 붙었다
    if not core:
        return _no(why, 'empty')
    if not para and (core[-1] in SENT_END or core.rstrip(_CLOSERS)[-1:] in SENT_END):
        return _no(why, '③')                                    # ③
    sa = max(1.0, a.get('size') or (ra[3] - ra[1]))
    sb = max(1.0, b.get('size') or (rb[3] - rb[1]))
    if para and margin - ra[2] > sa * JOIN_FILL:
        return _no(why, '③')                                    # ③ 대신: 앞 줄이 끝까지 찼어야 같은 문단
    # ④ 오른쪽이 찼는가. 260910-4(SOT §3.7.6 가): 고정 문턱만 보면 **11.4pt 모자란**
    #   줄이 탈락했는데, 뒷줄 첫 어절은 18pt 라 애초에 들어갈 수 없었다 — 문단이 끝난 게
    #   아니라 자리가 없어 넘어간 것이다. 그래서 거의 찼으면 통과, 덜 찼으면
    #   **그 빈칸에 뒷줄 첫 어절이 들어갔겠는가**를 묻는다.
    gap = margin - ra[2]
    if gap > sa * JOIN_FILL:
        if span > 0 and gap > span * JOIN_GAP_MAX:
            return _no(why, '④')            # 너무 많이 남았다 — 어떤 어절이 와도 문단 끝
        w = _first_word_width(b)
        # 261102-2(SOT §3.7.14): 왼쪽 정렬 단은 줄 끝이 원래 들쭉날쭉하다 — '어절이 들어갔겠는가' 를 묻지 않는다
        #   다만 숫자로 끝나거나(차례 `…주요 문제 39`) 숫자로 시작하는(표의 수 줄) 줄은 그 완화를 받지 않는다
        rag_ok = ragged and not re.search(r"\d$", core) and not re.match(r"\s*\d", tb)
        if not rag_ok and (w <= 0 or gap >= w * JOIN_WORD_SLACK):
            return _no(why, '④')            # 넉넉히 들어갔을 텐데 넘어갔다 → 문단이 끝났다
    # ⑤ 왼쪽 여백. 뒷줄이 들여써져 있으면 보통 **새 문단**이지만, 앞줄이 목록 항목의
    #   첫 줄이면(`(3) …`) 그 다음 줄들은 표시 아래로 들여쓰는 것이 정상이다
    #   (내어쓰기). 실측 지침 41쪽: 첫 줄 x=68.0, 이어지는 줄 x=86.8.
    # 261108-31(SOT §3.7.2 ⑤·§3.7.16): 뒷줄이 들여썼어도 **앞 줄이 `-` 로 끝나거나 뒷줄이 라틴 소문자로 시작하면** 이어지는 글이다 —
    #   새 문단은 소문자로 시작하지 않는다. 참고문헌의 내어쓰기(`… porous asphalt pave-` ⏎ `ment, Maruzen …`, cao 5·6쪽)
    _cont = core.endswith('-') or bool(re.match(r"[a-z]", tb.lstrip()))
    if rb[0] > ra[0] + sa and not (_starts_list(ta) or _HANG_HEAD.match(ta) or _cont):
        return _no(why, '⑤')
    if rb[0] > ra[0] + sa * 4:
        return _no(why, '⑤')                                    # 너무 많이 들여썼다 — 다른 글
    # 261101-1(SOT §3.7.11): **앞 줄이 한참 오른쪽에서 시작**하면(가운데·오른쪽 머리말 `PROJECT HAIL MARY 5`)
    #   다른 글이다 — 첫 줄 들여쓰기는 본문 폭의 몇 % 다. ⑧ 을 OCR 줄에서 빼자 지우지 못한 머리말이 본문에 붙었다.
    #   OCR 줄에만 — 글자층은 한 줄이 여러 조각으로 오고 조각이 줄 가운데서 시작할 수 있다(NAPA 2쪽 `of an asphalt`).
    if a.get('ocr') and span > 0 and ra[0] - rb[0] > span * JOIN_LEFT_MAX:
        return _no(why, '⑤')
    pitch = rb[1] - ra[1]                               # ⑥ 줄 사이 거리
    if pitch <= 0:
        return _no(why, '⑥')
    # 260916-1(SOT §3.7.9): 그 쪽의 **보통 줄 거리**로 잰다 — 없거나 쪽이 성기면 크기로.
    if med_pitch > 0 and med_pitch <= max(sa, sb) * JOIN_PITCH_SPARSE:
        if pitch > med_pitch * JOIN_PITCH_REL:
            return _no(why, '⑥')
    elif pitch > max(sa, sb) * JOIN_PITCH:
        return _no(why, '⑥')
    # ⑦ 260910-4(SOT §3.7.6 나): 앞줄에 닫히지 않은 `(` 가 있으면 뒷줄의 `)` 는
    #   목록 표시가 아니라 그 괄호를 닫는 이어지는 글이다.
    # 261101-1(SOT §3.7.2 ⑦): 앞 줄이 오른쪽 끝까지 찬 **한글**로 끝나면 뒷줄의 `다.`·`가.` 는 목록 번호가 아니라
    #   이어지는 낱말 끝이다 — 글자층 보고서에서 `…하고 있` + `다. 또한` 이 갈렸다(5곳). 목록 앞 줄은 끝까지 차지 않는다.
    if (_starts_list(tb) and not _unclosed_paren(ta)
            and not (_KO_LIST_HEAD.match(tb) and _is_cjk(core[-1]) and (margin - ra[2]) <= sa * JOIN_FILL)):
        return _no(why, '⑦')                                    # ⑦
    # ⑧ 261101-1(SOT §3.7.11): OCR 줄의 `size` 는 잉크 높이라 **줄에 든 글자**로 달라진다
    #   (`two?”` 7.0 / `plus` 가 든 줄 10.8) — 글꼴 크기를 잴 수 없어 OCR 줄에는 보지 않는다.
    if not (a.get('ocr') or b.get('ocr')) and abs(sa - sb) > max(sa, sb) * JOIN_SIZE_TOL:
        return _no(why, '⑧')                                    # ⑧
    #   ⑧ 을 빼자 차례 쪽의 두 항목(`…자극 추구 165` + `성격 연습 9 성실성 167`)이 이어졌다 — 종전에는 ⑧ 이
    #   우연히 막고 있었다. **두 줄 다 쪽 번호 같은 수로 끝나면** 차례로 보고 잇지 않는다(OCR 줄만).
    if (a.get('ocr') or b.get('ocr')) and _TOC_TAIL.search(ta.rstrip()) and _TOC_TAIL.search(tb.rstrip()):
        return _no(why, 'toc')
    # ⑨ 260910-4(SOT §3.7.6 다): 표·그림 제목은 **첫머리로** 알아본다.
    #   캡션은 부호로 끝나지 않고 길이도 본문과 비슷할 수 있어 ④ 로는 안 갈린다.
    if _is_caption(ta):
        return _no(why, '⑨')
    # ⑩ 261108-31(SOT §3.7.2 ⑩): **숫자만 있는 줄끼리**는 잇지 않는다 — 세로 줄 없는 표의 수 칸(가로 줄로만 나뉜 표, §3.6.5)이
    #   한 칸 안의 여러 줄로 묶여 `5.6 8.6 …`·`100 100 100 …` 으로 이어졌다(cao 2~4쪽).
    if _NUM_ONLY.match(core) and _NUM_ONLY.match(tb.strip()):
        return _no(why, '⑩')
    return True

def _classify(items):
    """대표 크기의 **중앙값**으로 제목/내용을 가른다(SOT §3.4).

    260908-8(사용자 지시): **크기가 많이 차이 날 때만** 제목이다 — 배수(`TITLE_RATIO`)와
    절대 차이(`TITLE_MIN_GAP_PT`)를 **둘 다** 넘어야 한다. 굵기는 보지 않는다:
    '크기는 거의 같은데 진하다' 는 이유로 제목이 되면 본문이 온통 제목이 된다.
    """
    sizes = sorted(s for _r, _t, s in items if s > 0)
    if not sizes:
        return ["body"] * len(items)
    mid = sizes[len(sizes) // 2]
    thr = max(mid * TITLE_RATIO, mid + TITLE_MIN_GAP_PT)
    return ["title" if (s > 0 and s >= thr) else "body" for _r, _t, s in items]


def page_lines(doc, pdf_path, page_index: int, *, tables: str = "lines",
               ocr_text: str = "", tables_cached_only: bool = False,
               ocr_words=None, ocr_dpi: int = 0, join_lines: bool = True,
               ocr_peer_words=None, edges_out=None) -> list:
    """쪽 하나의 줄 목록(SOT §3). `tables` = "lines"(기본) / "omit" / "off".

    `edges_out` 에 list 를 주면 §3.5.2 로 버린 머리말·꼬리말 줄(`edge_rows`)을 거기 채운다 — 형식 변환이 머리말·꼬리말
    기능으로 넣는 데 쓴다(형식 변환 SOT §1.1). 주지 않으면 지금과 똑같다.

    `ocr_text` 는 텍스트층이 쓸 만하지 않을 때 쓰는 OCR 결과(단어장 SOT 의 study.db).
    """
    try:
        page = doc.load_page(int(page_index))
    except Exception:
        return []
    if ocr_words:
        # 260908-8: [OCR 다시 읽기] 로 새로 읽은 쪽.
        # 260913-4(§3.5.2): 옆 쪽 OCR 낱말 — 꼬리말 되풀이를 알아보는 데 쓴다
        _ocr_edges = [] if edges_out is not None else None
        rows = lines_from_words(ocr_words, dpi=ocr_dpi, page=page,
                                peer_words=ocr_peer_words, edges_out=_ocr_edges)
        if rows:
            _NOISE["n"] = 0
            if join_lines:
                rows = join_hyphens(join_columns(join_sentences(rows)))   # 261101-1(SOT §3.7.4): 남은 분철도 · 261108-31(§3.7.16): 단 넘김
            if not has_text_layer(doc, page_index):
                if edges_out is not None:
                    edges_out.extend(_ocr_edges)
                return fix_toc_numbers(rows)    # 스캔 쪽 — OCR 이 전부다
            # 260909-2(SOT §3.1.3): 글자층이 있는 쪽은 **갈아 끼우지 않고 합친다**.
            #   글자층이 정확하고, 그림 속 글만 OCR 로 채운다.
            base = page_lines(doc, pdf_path, page_index, tables=tables,
                              tables_cached_only=tables_cached_only,
                              join_lines=join_lines, edges_out=edges_out)
            return fix_toc_numbers(merge_layer_and_ocr(base, rows))
    items = _line_items(page, edges_out)
    noise = last_noise_count()

    if not items:                       # 텍스트층 없음 → OCR 폴백(좌표 없음)
        out = []
        for ln in (ocr_text or "").splitlines():
            if ln.strip():
                out.append({"text": ln, "style": "body", "rect": None, "kind": "text"})
        return out

    tbl = (_tables(pdf_path, page_index, cached_only=tables_cached_only)
           if tables != "off" else [])
    styles = _classify(items)
    rows_out = []
    for (rect, txt, size), st in zip(items, styles):
        rows_out.append({"text": txt, "style": st, "rect": rect, "kind": "text",
                         "size": size})

    if tbl:
        # 260908-7(SOT §3.3 개정): **우리가 이은 줄을 그대로 쓰고 표시만 한다.**
        #   종전에는 표 안의 본문 줄을 빼고 pdfplumber 가 뽑은 칸으로 갈아 끼웠는데,
        #   실측(아스팔트 지침 41쪽)에서 pdfplumber 가 3열 표의 가운데 칸에만 두 줄을
        #   몰아 넣고 나머지를 None 으로 뽑아 **모래당량·50 이상 같은 칸이 사라졌다**.
        #   §3.6 의 줄 잇기가 이미 한 행을 왼쪽부터 한 줄로 만들어 주므로, 표 사각형은
        #   '여기가 표다' 를 표시하고 생략 옵션을 처리하는 데만 쓴다.
        if tables == "omit":
            keep = [r for r in rows_out
                    if not any(_inside(r["rect"], bb) for bb, _rows in tbl)]
            for bb, rows in tbl:
                cols = max((len(r) for r in rows), default=0)
                keep.append({"text": TABLE_OMIT_FMT.format(cols=cols, rows=len(rows)),
                             "style": "body", "rect": bb, "kind": "table"})
            keep.sort(key=lambda r: ((r["rect"][1] if r["rect"] else 0),
                                     (r["rect"][0] if r["rect"] else 0)))
            rows_out = keep
        else:
            for r in rows_out:
                if any(_inside(r["rect"], bb) for bb, _rows in tbl):
                    r["kind"] = "table"
    _NOISE["n"] = noise          # 표 처리가 `_line_items` 를 다시 부르지 않음을 명시
    if join_lines:               # 260910(SOT §3.7): 종이 때문에 끊긴 문장을 잇는다
        rows_out = join_hyphens(join_columns(join_sentences(rows_out)))   # 261101-1(SOT §3.7.4): 남은 분철도 · 261108-31(§3.7.16): 단 넘김
    # 261103-14(SOT §3.6.17): 목차 쪽 항목 번호 오독(`A 성격 평가기법` → `4.`)
    return fix_toc_numbers(rows_out)


def lines_from_words(words, *, dpi: int = 0, page=None, peer_words=None, edges_out=None) -> list:
    """OCR 낱말 상자 → **줄 목록**(SOT §3.1·§3.6, 260908-8).

    종전 OCR 폴백은 저장된 본문을 줄바꿈으로 쪼개기만 해서 **좌표가 없었다** —
    본문 강조도, [PDF 에 반영]도 못 했다. 낱말 상자를 쓰면 §3.6 의 줄 잇기를 그대로
    태울 수 있어 좌표가 살아 있고, 잡음 규칙도 같은 것이 적용된다.

    `dpi` 가 0 이면 좌표가 이미 pt 다(디지털 레이어). 아니면 픽셀 → pt 로 환산한다.
    """
    if not words:
        return []
    k = 1.0 if not dpi else 72.0 / float(dpi)
    frags = []
    for w in words:
        try:
            x0, y0 = float(w['x0']) * k, float(w['y0']) * k
            x1, y1 = float(w['x1']) * k, float(w['y1']) * k
            t = str(w.get('surface') or '')
        except Exception:
            continue
        if not t.strip():
            continue
        if _noise.is_noise_box(t, x0, y0, x1, y1):
            continue
        frags.append(((x0, y0, x1, y1), t, max(1.0, y1 - y0)))
    if not frags:
        return []
    # 260913-4(SOT §3.5.2): 세로 띠는 **낱말 단계**에서 버린다 — 잇고 나면 본문 줄에 붙는다.
    if page is not None:
        frags, _n = drop_edge_frags(frags, page, edge=False)
    # 260916-1(SOT §3.6.12): 한글 문턱은 **이 쪽의 빈틈 분포**에서 뽑는다.
    #   단을 가르기 전에 쪽 전체로 뽑는다 — 표본이 많을수록 골짜기가 뚜렷하다.
    cjk_gap = cjk_gap_threshold(frags)
    if cjk_gap is None:
        cjk_gap = CJK_GLUE_GAP
    items = []
    for col in ([frags] if page is None
                else _by_column([((0, 0, 0, 0), frags)], page, word_level=True)):
        items.extend(_merge_rows(col, cjk_gap=cjk_gap))
    items = [it for it in items if not _noise.is_symbol_only(it[1])]
    # 261101-1(SOT §3.6.15): 홀로 선 한글 한 음절(`가 족이나`)은 앞뒤 경계만 말뭉치에 물어 붙인다
    items = [(r, fix_ko_spacing(t), sz) for r, t, sz in items]
    # 261101-1(SOT §3.5.4): 줄 첫머리 목록 기호 뒤에는 빈칸 — 기호와 한글이 붙어(`•화를`) 목록으로 보이지 않았다
    items = [(r, re.sub(r"^([•■])(?=\S)", r"\1 ", t), sz) for r, t, sz in items]
    # 261101-1(SOT §3.6.14, 표본 조사): **본문 쪽**의 ` | ` 는 표 칸이 아니라 버려진 낱말의 빈자리다 — ` | ` 가 든 줄이
    #   그 쪽 줄의 `PROSE_BAR_MAX` 이하이고 그 줄에 하나뿐이면 빈칸으로. 표·서식 쪽은 거의 모든 행에 ` | ` 가 있다.
    if len(items) >= PROSE_MIN_ROWS:
        nb = sum(1 for it in items if CELL_SEP in it[1])
        if nb and nb <= len(items) * PROSE_BAR_MAX:
            items = [(r, t.replace(CELL_SEP, " ") if t.count(CELL_SEP) == 1 else t, sz) for r, t, sz in items]
    # 머리말·꼬리말은 **줄을 이은 뒤** 줄 단위로 — 낱말 하나는 옆 쪽 꼬리말 한 줄과 같을 수 없다.
    if page is not None and items:
        _before = items
        items, _n = drop_edge_frags(items, page, side=False, ocr=True,
                                    peers=peer_texts_from_words(peer_words))
        if edges_out is not None and _n:
            _ok = {id(f) for f in items}
            edges_out.extend(edge_rows([f for f in _before if id(f) not in _ok], page))
    styles = _classify(items)
    # 'ocr' — 낱말 상자로 만든 줄이다(`size` 가 잉크 높이, SOT §3.7.11 의 ⑧)
    return [{'text': t, 'style': st, 'rect': r, 'kind': 'text', 'size': sz, 'ocr': True}
            for (r, t, sz), st in zip(items, styles)]

def peer_texts_from_words(peer_words) -> list:
    """옆 쪽들의 OCR 낱말 `[(낱말상자, dpi), …]` → 줄 글 목록(§3.5.2 되풀이 판정용).

    되풀이 판정은 빈칸을 빼고 견주므로 줄 안의 띄어쓰기는 따지지 않는다 — 같은 높이의
    낱말을 왼쪽부터 이어 붙이기만 한다. 좌표 단위(dpi)는 줄을 가르는 데 쓰이지 않는다."""
    out = []
    for ent in peer_words or []:
        try:
            pair = isinstance(ent, (tuple, list)) and len(ent) == 2
            ws = ent[0] if pair and not isinstance(ent[0], dict) else ent
        except Exception:
            continue
        boxes = []
        for w in ws or []:
            try:
                t = str(w.get("surface") or "").strip()
                y0, y1 = float(w["y0"]), float(w["y1"])
                x0 = float(w["x0"])
            except Exception:
                continue
            if t:
                boxes.append(((y0 + y1) / 2.0, max(1e-6, y1 - y0), x0, t))
        boxes.sort()
        line, yc, hh = [], None, 0.0
        for c, h, x0, t in boxes:
            if yc is not None and abs(c - yc) > 0.5 * max(h, hh):
                out.append("".join(tt for _x, tt in sorted(line)))
                line = []
            if not line:
                yc, hh = c, h
            line.append((x0, t))
        if line:
            out.append("".join(tt for _x, tt in sorted(line)))
    return out


LINE_YC_TOL = 0.5           # 세로 가운데가 줄 높이의 이 배 안이면 같은 줄(§3.6.16)


def words_in_line_order(words) -> list:
    """낱말 상자를 **줄 차례**로 늘어놓는다 — 줄은 위→아래, 줄 안은 왼→오른 (SOT §3.6.16).

    261103-5: 저장된 OCR 낱말은 `ORDER BY y0, x0` 로 와서 줄 안이 뒤섞인다(한글 음절마다 위끝이 1~2px 다르다).
    이웃끼리 견주는 곳은 받은 차례를 믿지 않고 이것을 먼저 거친다. 좌표가 없는 낱말은 버리지 않고 끝에 둔다."""
    good, bad = [], []
    for w in words or []:
        try:
            y0, y1 = float(w['y0']), float(w['y1'])
            float(w['x0'])
            good.append(((y0 + y1) / 2.0, max(1e-6, y1 - y0), w))
        except Exception:
            bad.append(w)
    good.sort(key=lambda q: q[0])
    rows = []
    for yc, h, w in good:
        if rows:
            r = rows[-1]
            if abs(yc - r["yc"]) <= LINE_YC_TOL * max(h, r["h"]):
                n = len(r["ws"])
                r["yc"] = (r["yc"] * n + yc) / (n + 1)
                r["h"] = (r["h"] * n + h) / (n + 1)
                r["ws"].append(w)
                continue
        rows.append({"yc": yc, "h": h, "ws": [w]})
    return [w for r in rows for w in sorted(r["ws"], key=lambda q: float(q['x0']))] + bad


def merge_words_by_gap(words) -> list:
    """낱말 상자를 **낱말 단위로** 묶는다 (SOT §3.6.2 의 규칙 그대로).

    260913-1(입력 SOT §2.8): Tesseract 는 한글을 **글자 하나하나** 낱말로 내놓는다.
    그대로 본문 뷰어에 넘기면 끌어서 고를 때 `티` `검` `사` 가 따로 잡히고, 복사한
    글도 글자마다 띄어진다. 여기서 붙여 준다 — 붙임/띄움 기준은 §3.6.2 가 소유하고
    이 함수는 그것을 **부르기만** 한다(같은 규칙이 두 벌이 되면 반드시 어긋난다).

    받는 것도 주는 것도 `{"surface", "x0", "y0", "x1", "y1"}` 목록이다. 받은 차례는 믿지 않는다 — 줄 차례로 늘어놓고 묶는다(§3.6.16).
    """
    out = []
    for w in words_in_line_order(words):
        try:
            t = str(w.get("surface") or "")
            x0, y0 = float(w["x0"]), float(w["y0"])
            x1, y1 = float(w["x1"]), float(w["y1"])
        except Exception:
            continue
        if not t.strip():
            continue
        if out:
            p = out[-1]
            lo = min(p["y1"] - p["y0"], y1 - y0)
            ov = min(p["y1"], y1) - max(p["y0"], y0)
            same_row = lo > 0 and (ov / lo) >= ROW_OVERLAP
            ref = max(1.0, min(p["y1"] - p["y0"], y1 - y0))
            gap = x0 - p["x1"]
            if _is_cjk_pair(p["surface"], t):
                glue = CJK_GLUE_GAP
            elif _is_num_pair(p["surface"], t):
                glue = NUM_GLUE_GAP
            else:
                glue = None             # 261101-1(SOT §3.6.13): OCR 라틴 낱말은 붙이지 않는다
            if same_row and glue is not None and gap < glue * ref:
                p["surface"] += t
                p["x1"] = max(p["x1"], x1)
                p["y0"] = min(p["y0"], y0)
                p["y1"] = max(p["y1"], y1)
                continue
        out.append({"surface": t, "x0": x0, "y0": y0, "x1": x1, "y1": y1})
    return out


def words_in_reading_order(words, *, dpi: int = 0, page=None) -> list:
    """OCR 낱말을 **읽는 차례**로 다시 늘어놓는다 (SOT §3.6.9).

    260911(사용자 보고 "본문 읽기가 2단을 1단처럼 읽는다"): `study.db` 의 낱말은
    **OCR 이 준 차례** 그대로다 — 줄 단위로 쪽을 가로지르므로 2단 쪽에서는 왼쪽 단
    한 줄, 오른쪽 단 한 줄이 번갈아 나온다.

    텍스트 창은 §3.6 의 규칙으로 이미 단을 갈라 읽는다. 읽기(TTS)와 그 강조도
    **같은 차례**를 써야 한다 — 글은 단 차례인데 낱말은 OCR 차례면 강조가 엉뚱한
    자리로 튄다. 그래서 같은 `_by_column` 을 태워 낱말 자체를 다시 늘어놓는다.

    돌려주는 것은 **원래 낱말 dict 그대로**(좌표·surface 보존), 차례만 바뀐다.
    """
    src = list(words or [])
    if not src or page is None:
        return words_in_line_order(src)
    k = 1.0 if not dpi else 72.0 / float(dpi)
    frags, keep = [], []
    for w in src:
        try:
            x0, y0 = float(w['x0']) * k, float(w['y0']) * k
            x1, y1 = float(w['x1']) * k, float(w['y1']) * k
        except Exception:
            return src                      # 좌표를 못 읽으면 손대지 않는다
        frags.append(((x0, y0, x1, y1), str(w.get('surface') or ''),
                      max(1.0, y1 - y0)))
        keep.append(w)
    pos = {id(f): i for i, f in enumerate(frags)}
    try:
        groups = _by_column([((0, 0, 0, 0), frags)], page, word_level=True)
    except Exception:
        return words_in_line_order(src)
    out = []
    for grp in groups:
        for bd in sorted(_row_bands(grp), key=lambda b: (b["y0"], b["y1"])):
            for f in sorted(bd["items"], key=lambda q: q[0][0]):
                i = pos.get(id(f))
                if i is not None:
                    out.append(keep[i])
    # 하나라도 빠지면 줄 차례를 쓴다 — 읽다 마는 것보다 낫고, 받은 차례(`y0, x0`)는 줄 안이 뒤섞였을 수 있다(§3.6.16)
    return out if len(out) == len(src) else words_in_line_order(src)


def merge_layer_and_ocr(layer_rows, ocr_rows, *, frac: float = 0.5) -> list:
    """글자층 줄 + **그림 속에만 있던** OCR 줄 (SOT §3.1.3, 260909-2).

    사용자 보고: 표지 제목·붙여 넣은 표 그림의 글이 텍스트 창에 아예 안 나온다.
    그 쪽은 **글자층과 그림이 섞인 쪽**이었다 — 글자층만 읽으니 그림 속 글은 없고,
    OCR 로 갈아 끼우면 멀쩡한 글자층까지 짐작한 글자로 바뀐다. 그래서 **합친다**.

    260910-11(사용자 보고 "순서와 내용 구분에 문제가 있다", SOT §3.6.7): 두 가지를 고쳤다.

    ① **덮였는지는 여러 줄을 합쳐 본다.** 종전에는 OCR 줄이 *한* 글자층 줄 안에
       절반 넘게 드는지만 봤다. 2단 쪽에서 OCR 줄이 두 단에 걸치면 어느 한 줄에도
       절반이 안 들어 **같은 글이 한 번 더** 나왔다(실측 1쪽: `INTRODUCTION`,
       `CURRENT APPROACHES TO BMD`, 그리고 `INTRODUCTION | CURRENT APPROACHES TO BMD`).
       이제 겹친 넓이를 **모두 더해** 판단한다.

    ② **글자층의 차례를 흐트러뜨리지 않는다.** 종전에는 합친 뒤 (y, x) 로 다시
       정렬해, 애써 세운 단 차례(왼쪽 단 전부 → 오른쪽 단 전부)가 **줄마다 좌우로
       엇갈리는** 차례로 돌아갔다. 이제 글자층 차례를 그대로 두고, 더할 줄만 **제
       자리 뒤에** 끼운다.
    """
    keep = list(layer_rows or [])
    rects = [x.get('rect') for x in keep]

    def _covered(rc):
        area = max(1e-6, (rc[2] - rc[0]) * (rc[3] - rc[1]))
        hit = 0.0
        for q in rects:
            if not q:
                continue
            w = min(rc[2], q[2]) - max(rc[0], q[0])
            h = min(rc[3], q[3]) - max(rc[1], q[1])
            if w > 0 and h > 0:
                hit += w * h
        return (hit / area) >= frac

    extra = []
    for r in (ocr_rows or []):
        rc = r.get('rect')
        if not rc or _covered(rc):
            continue
        r = dict(r)
        r['kind'] = 'ocr'          # 어디서 왔는지 남긴다(창 안내·검증용)
        extra.append(r)
    if not extra:
        return keep

    # 더할 줄마다 '어느 글자층 줄 뒤인가' 를 정한다 — 같은 단(가로로 겹침)에서
    # 바로 위에 있는 줄. 없으면 맨 앞에 둔다.
    after = {}
    for r in extra:
        rc = r['rect']
        best, best_y = -1, None
        for k, q in enumerate(rects):
            if not q:
                continue
            if min(rc[2], q[2]) - max(rc[0], q[0]) <= 0:     # 가로로 안 겹치면 다른 단
                continue
            if q[1] <= rc[1] and (best_y is None or q[1] >= best_y):
                best, best_y = k, q[1]
        after.setdefault(best, []).append(r)
    for v in after.values():
        v.sort(key=lambda x: (x['rect'][1], x['rect'][0]))

    out = list(after.get(-1, []))
    for k, row in enumerate(keep):
        out.append(row)
        out.extend(after.get(k, []))
    return out


def _peer_words(words_lookup, pno: int, n: int) -> list:
    """옆 쪽(앞뒤 **둘씩**)의 OCR 낱말 — 머리말·꼬리말 되풀이 판정용(§3.5.2). 못 읽으면 건너뛴다.

    261101-1: 책은 짝수 쪽과 홀수 쪽의 머리말이 다르다(`4 ANDY WEIR` / `PROJECT HAIL MARY 5`) — ±1 만 보면
    언제나 다른 머리말이라 한 쪽도 지우지 못했다(HM 31쪽 중 0 → ±2 로 26)."""
    out = []
    for k in (pno - 2, pno - 1, pno + 1, pno + 2):
        if 0 <= k < n:
            try:
                ws, dpi = words_lookup(k)
            except Exception:
                continue
            if ws:
                out.append((ws, dpi))
    return out


def display_rows(pdf_path, page: int, *, ocr_lookup=None, words_lookup=None) -> list:
    """쪽 하나를 **텍스트 창이 보여 주는 그대로** 돌려준다 — 글과 **자리**를 함께.

    260911(SOT §3.1.6): `clean_page_texts` 는 글만 준다. 읽기(TTS)는 강조까지 해야 해서
    **줄마다의 사각형**이 필요하다. 두 곳이 각자 줄을 만들면 언젠가 어긋나므로,
    같은 `page_lines` 를 한 번 태워 그 결과를 함께 쓴다.

    돌려주는 각 줄: `{'text', 'rect', 'rects'}` — `rects` 는 이은 줄의 **원래 줄들**이다
    (§3.7). 고침(§5.1)이 있으면 글에 반영해 준다.
    """
    try:
        import fitz
    except Exception:
        return []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return []
    # 261011-5(마스터 §4.7.16): '저장' 이 넣은 'PolyPDF' 레이어(꾸밈 글상자 글)는 추출에서 뺀다 — 본문 화면처럼
    try:
        from viewer import pdf_mirror as _pm
        _pm.hide_for_view(doc)
    except Exception:
        pass
    try:
        pno = int(page)
        if pno < 0 or pno >= doc.page_count:
            return []
        try:
            ocr = (ocr_lookup(pno) if ocr_lookup else '') or ''
            words, wdpi = (words_lookup(pno) if words_lookup else (None, 0))
            rows = page_lines(doc, str(pdf_path), pno, tables='lines',
                              ocr_text=ocr, ocr_words=words or None,
                              ocr_dpi=int(wdpi or 0),
                              ocr_peer_words=(_peer_words(words_lookup, pno, doc.page_count)
                                              if words else None))
        except Exception:
            return []
        # 260913-4(SOT §5.1.3): 고침은 **자리로** 얹는다(합친 줄 포함) — 창과 같은 함수
        try:
            from viewer.text_fix_store import store as _fix_store
            rows = _fix_store().apply_to_rows(str(pdf_path), pno, rows)
        except Exception:
            pass
        out = []
        for r in rows:
            t = r.get('text', '')
            if not (t or '').strip():
                continue
            rcs = r.get('rects') or ([r['rect']] if r.get('rect') else [])
            out.append({'text': t, 'rect': r.get('rect'),
                        'rects': [tuple(x) for x in rcs if x]})
        return out
    finally:
        try:
            doc.close()
        except Exception:
            pass


def clean_page_texts(pdf_path, pages=None, *, ocr_lookup=None,
                     words_lookup=None) -> list:
    """쪽마다 **이 창이 보여 주는 글**을 모아 [(쪽, 글)] 로 (SOT §3.1.5, 260910).

    단어장은 종전에 `study.db` 의 **날것 `ocr_page.text`** 를 읽어 낱말을 뽑았다.
    그 글은 화면과 다르다 — 기호 줄이 살아 있고, 표 칸이 흩어져 있고, 끊긴 낱말
    (`취사` + `선택`)이 따로 놀고, 고쳐 둔 것이 반영돼 있지 않다. 그래서
    **의미 없는 낱말이 단어장에 많이 들어갔다**(사용자 보고).

    여기서는 §3.A 의 열 단계를 다 거친 줄을 쓰고, 고침(§5.1)까지 얹는다.
    실패하면 빈 목록을 돌려준다 — 부르는 쪽이 날것으로 돌아갈 수 있게.

    ★ `words_lookup(쪽) -> (낱말상자, dpi)` 를 주면 **그 낱말로** 줄을 만든다.
      단어장은 스캔 쪽을 OCR 로 읽어 `study.db` 에 담아 두는데, 그 쪽의 PDF **글자층**은
      대개 그보다 나쁘다(실측: 어떤 책은 글자층에 띄어쓰기가 아예 없어 표제어가
      엉망이 됐다). **단어장이 쓰는 글과 같은 것**에 규칙을 걸어야 뜻이 있다.
    """
    try:
        import fitz
    except Exception:
        return []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return []
    # 261011-5(마스터 §4.7.16): '저장' 이 넣은 'PolyPDF' 레이어(꾸밈 글상자 글)는 추출에서 뺀다 — 본문 화면처럼
    try:
        from viewer import pdf_mirror as _pm
        _pm.hide_for_view(doc)
    except Exception:
        pass
    try:
        from viewer.text_fix_store import store as _fix_store
        fixes = _fix_store()
    except Exception:
        fixes = None
    if words_lookup is not None:
        # 260913-4: 옆 쪽 낱말도 읽으므로(§3.5.2) 한 쪽을 두세 번 묻지 않게 기억한다
        _raw_lookup, _memo = words_lookup, {}

        def words_lookup(k, _f=_raw_lookup, _m=_memo):
            if k not in _m:
                _m[k] = _f(k)
            return _m[k]
    out = []
    held = None                     # (쪽, 줄목록) — 다음 쪽 첫 줄을 이어 붙일 수 있게 한 쪽 늦게 낸다(§3.7.12)

    def _emit(h):
        out.append((h[0], chr(10).join(x for x in (r.get('text', '') for r in h[1]) if x)))
    try:
        idx = range(doc.page_count) if pages is None else [int(p) for p in pages]
        for pno in idx:
            if pno < 0 or pno >= doc.page_count:
                continue
            try:
                ocr = (ocr_lookup(pno) if ocr_lookup else '') or ''
                words, wdpi = (words_lookup(pno) if words_lookup else (None, 0))
                rows = page_lines(doc, str(pdf_path), pno, tables='lines',
                                  ocr_text=ocr, ocr_words=words or None,
                                  ocr_dpi=int(wdpi or 0),
                                  ocr_peer_words=(_peer_words(words_lookup, pno,
                                                              doc.page_count)
                                                  if words else None))
            except Exception:
                continue
            if fixes is not None:           # 260913-4(SOT §5.1.3): 자리로 얹는다
                try:
                    rows = fixes.apply_to_rows(str(pdf_path), pno, rows)
                except Exception:
                    pass
            rows = [dict(r) for r in rows]
            # 261101-1(SOT §3.7.12): 쪽 끝에서 끊긴 문장을 다음 쪽 첫 줄과 잇는다 — 이어진 쪽끼리만
            if held is not None:
                if held[0] + 1 == pno:
                    page_carry(held[1], rows)
                _emit(held)
            held = (pno, rows)
        if held is not None:
            _emit(held)
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return out

def pick_ocr_words(doc, page_index: int, words_lookup, forced: bool = False):
    """이 쪽에 **우리 OCR 낱말**을 쓸지 정한다 → `(낱말상자, dpi)` 또는 `([], 0)` (SOT §3.1).

    260913-6(사용자 결정 "우리 OCR로 통일"): 판단은 **여기 한 곳**이다 — 본문 뷰어(입력 SOT §2.8)·
    텍스트 창·Word 저장·글자층 다시 쓰기(§5.4)가 모두 이것을 거친다.
      · 쓸 만한 글자층이 있고 사용자가 다시 읽히지 않았다 → 쓰지 않는다(층이 가장 정확하다)
      · 그 밖(스캔본, 스캐너 OCR 층만 있는 쪽 포함, 또는 [OCR 다시 읽기] 한 쪽) → 우리 OCR 이 있으면 쓴다
    `words_lookup(쪽) -> (낱말상자, dpi)` 는 study.db 를 읽는 쪽이 준다(소유 경계)."""
    try:
        if not forced and has_text_layer(doc, int(page_index)):
            return ([], 0)
    except Exception:
        return ([], 0)
    try:
        ws, dpi = words_lookup(int(page_index))
    except Exception:
        return ([], 0)
    return (ws, int(dpi or 0)) if ws else ([], 0)


def has_text_layer(doc, page_index: int) -> bool:
    """이 쪽에 쓸 만한 텍스트층이 있는가(스캔본이면 False → OCR 을 쓴다)."""
    try:
        page = doc.load_page(int(page_index))
    except Exception:
        return False
    try:
        from viewer.study import ocr as _ocr
        src, _ = _ocr.decide_source(page)
        return src != "ocr"
    except Exception:
        try:
            return len((page.get_text("text") or "").strip()) >= 20
        except Exception:
            return False
