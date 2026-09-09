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
COL_ALIGN = 0.40        # 단으로 보려면 왼쪽 끝이 이 비율 이상 맞아야 한다
TABLE_OMIT_FMT = "[표 {cols}열 × {rows}행]"


def _is_ocr_layer(page) -> bool:
    """이 쪽의 글자가 **보이지 않는 OCR 층**인가(SOT §3.5).

    스캔본은 그림 위에 render mode 3(보이지 않음)으로 글자를 얹는다. 그 층에는 OCR 이
    종이의 티를 글자로 잘못 읽은 것이 섞여 있어, 잡음 거르기는 **이런 쪽에만** 한다 —
    사람이 넣은 작은 글씨를 지우면 안 된다."""
    try:
        tr = page.get_texttrace()
    except Exception:
        return False
    if not tr:
        return False
    inv = sum(1 for sp in tr if sp.get("type") == 3)
    return inv >= len(tr) * 0.9


def _line_items(page):
    """PyMuPDF 줄 → [(rect, 글, 대표크기)] — 빈 줄 제외, 블록 읽기 순서.

    260908-6(SOT §3.5): 보이지 않는 OCR 층인 쪽에서는 **글자라고 볼 수 없이 작은 줄**을
    뺀다. 반환값에 잡음 수를 곁들이지 않고, 부르는 쪽이 필요하면 `last_noise_count()` 로 본다.
    """
    try:
        d = page.get_text("dict")
    except Exception:
        return []
    ocr_layer = _is_ocr_layer(page)
    noise = 0
    blocks = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:                  # 0=텍스트
            continue
        lines = []
        for ln in b.get("lines", []):
            spans = ln.get("spans", []) or []
            txt = "".join(sp.get("text", "") for sp in spans)
            if not txt.strip():
                continue
            size = max((float(sp.get("size", 0) or 0) for sp in spans), default=0.0)
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
    for col_frags in _by_column(blocks, page):
        out.extend(_merge_rows(col_frags))
    if ocr_layer:
        # 260908-8(SOT §3.5): **줄을 이은 뒤에** 기호만 남은 줄을 뺀다(`■`·`☜`).
        #   조각 단계에서 빼면 `[ 제목 ]` 의 `]` 처럼 이어져야 할 것까지 사라진다.
        kept = [it for it in out if not _noise.is_symbol_only(it[1])]
        noise += len(out) - len(kept)
        out = kept
    _NOISE["n"] = noise
    return out


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


def _gutter_x(bands, page):
    """2단 쪽의 **빈 세로 띠**(단 사이 여백)의 x. 2단이 아니면 None (SOT §3.6).

    2단 판정을 블록 위치로 어림하면 **표가 있는 1단 쪽을 2단으로 잘못 본다** —
    실제로 그렇게 판정해 표 한 행의 왼쪽 칸과 오른쪽 칸이 갈라졌다(260908-7).
    그래서 '가운데 근처에 글이 거의 가로지르지 않는 띠가 있는가' 를 직접 본다.
    **줄 단위로 센다** — 전폭 제목 한두 줄이 가로지른다고 2단이 아닌 것은 아니다.
    """
    try:
        rect = page.rect
        w = float(rect.width or 0.0)
        mid = (float(rect.x0) + float(rect.x1)) / 2.0
    except Exception:
        return None
    if w <= 0 or len(bands) < 6:
        return None
    allow = max(1, int(len(bands) * 0.15))       # 전폭 제목 등은 이만큼 봐준다
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
    if best_a is None or (best_b - best_a) < 0.04 * w:
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
    if _left_edge_share(left) < COL_ALIGN or _left_edge_share(right) < COL_ALIGN:
        return None
    return gx


def _left_edge_share(frags) -> float:
    """왼쪽 끝(2pt 로 반올림)이 가장 흔한 값과 같은 조각의 비율."""
    if not frags:
        return 0.0
    counts = {}
    for f in frags:
        k = round(f[0][0] / 2.0)
        counts[k] = counts.get(k, 0) + 1
    return max(counts.values()) / float(len(frags))


def _by_column(blocks, page):
    """[[조각…]] — 2단이면 좌·우 두 묶음, 아니면 한 묶음(읽기 순서 유지)."""
    frags = [f for _bb, lines in blocks for f in lines]
    gx = _gutter_x(_row_bands(frags), page)
    if gx is None:
        return [frags]
    left = [f for f in frags if (f[0][0] + f[0][2]) / 2.0 < gx]
    right = [f for f in frags if (f[0][0] + f[0][2]) / 2.0 >= gx]
    return [left, right]


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

def _merge_rows(frags):
    """세로로 겹치는 조각을 **한 줄**로 잇는다 — 왼쪽부터 오른쪽으로.

    잇는 방법은 벌어진 폭에 따른다(SOT §3.6).
      - 글자크기의 0.25 배 미만 → 붙여 쓴다
      - 2.5 배 미만 → 공백 하나
      - 그 이상 → `" | "` — 표의 다른 칸으로 본다(§3.3 과 같은 표기)
    """
    out = []
    for bd in _row_bands(frags):
        items = sorted(bd["items"], key=lambda f: f[0][0])
        text = items[0][1].rstrip()
        x0, y0, x1, y1 = items[0][0]
        for rect, txt, size in items[1:]:
            piece = txt.strip()
            if not piece:
                continue
            ref = max(1.0, size or (rect[3] - rect[1]))
            gap = rect[0] - x1
            if _is_cjk_pair(text, piece):
                glue = CJK_GLUE_GAP
            elif _is_num_pair(text, piece):
                glue = NUM_GLUE_GAP
            else:
                glue = GLUE_GAP
            if gap < glue * ref:
                sep = ""
            elif gap < COL_GAP * ref:
                sep = "" if (not text or text.endswith(" ")) else " "
            else:
                sep = CELL_SEP
            text = text.rstrip() + sep + piece if sep == CELL_SEP else text + sep + piece
            x0, y0 = min(x0, rect[0]), min(y0, rect[1])
            x1, y1 = max(x1, rect[2]), max(y1, rect[3])
        # 대표 크기 = **글자가 가장 많은 조각**의 크기(제목/내용 판정용, SOT §3.4)
        size = max(items, key=lambda f: len(f[1].strip()))[2]
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
_TCACHE = {}          # (파일키, 쪽) -> [(bbox, rows)]
_TCACHE_MAX = 64


def _plumber(pdf_path):
    import os
    try:
        key = (str(pdf_path), os.path.getmtime(pdf_path))
    except Exception:
        return None
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
    """열어 둔 핸들·표 결과를 놓는다. 파일을 지우거나 덮어쓰기 전에 부른다."""
    pdf = _PLUMB.get("pdf")
    _PLUMB["pdf"] = None
    _PLUMB["key"] = None
    _TCACHE.clear()
    if pdf is not None:
        try:
            pdf.close()
        except Exception:
            pass


def _tables(pdf_path, page_index: int, *, cached_only: bool = False):
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
    pdf = _plumber(pdf_path)
    if pdf is None:
        return []
    out = []
    try:
        if page_index < len(pdf.pages):
            pg = pdf.pages[page_index]
            for t in pg.find_tables():
                rows = t.extract() or []
                if rows:
                    out.append((tuple(t.bbox), rows))
            try:
                pg.flush_cache()            # 쪽마다 붙잡는 메모리를 놓는다
            except Exception:
                pass
    except Exception:
        out = []
    if len(_TCACHE) > _TCACHE_MAX:
        _TCACHE.clear()
    _TCACHE[ck] = out
    _db_put(pdf_path, page_index, out)
    return out


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
# 줄 **간격**이 아니라 **줄 사이 거리(pitch)** 를 글자 크기로 잰다 — 간격으로 재면
#   글자가 큰데 줄이 성긴 쪽(발표자료·서식)에서 남남인 줄이 붙는다(260910 실측).
#   실측 pitch÷크기: 이어지는 본문 1.6~1.8 / 따로 놓인 줄 2.9.
JOIN_PITCH = 2.2
JOIN_SIZE_TOL = 0.20     # 글자 크기가 이만큼 안에서 같아야 한다
_LIST_HEAD = None


def _starts_list(text) -> bool:
    """목록 표시로 시작하는가 — `1.` `가.` `①` `•` `-` `(1)` 등 (SOT §3.7 ⑦)."""
    global _LIST_HEAD
    if _LIST_HEAD is None:
        import re
        _LIST_HEAD = re.compile(
            r'^\s*(?:\(?\d+[.)]|\(?[가-힣][.)]|[①-⑳]|[•·▶◊▊☞*\-–—]\s|○|※)')
    return bool(_LIST_HEAD.match(text or ''))


def _join_sep(a_text, b_text) -> str:
    """두 줄을 어떻게 이을지 — 빈칸 / 붙임 / 분철 떼기 (SOT §3.7)."""
    if a_text.endswith(' '):
        return ' '
    a = a_text.rstrip()
    b = (b_text or '').lstrip()
    if not a or not b:
        return ''
    if a.endswith('-') and ('a' <= b[0] <= 'z'):
        return '-drop'
    if _is_cjk(a[-1]) and _is_cjk(b[0]):
        return ''
    return ' '


def join_sentences(rows) -> list:
    """종이 때문에 끊긴 줄을 **한 문장으로** 잇는다 (SOT §3.7).

    문장부호만으로 판단하지 않는다 — 제목·표 제목·그림 제목도 부호로 끝나지 않는다.
    가장 강한 신호는 **줄이 오른쪽 여백까지 찼는가** 다(실측: 이어지는 본문 1.00,
    제목·문단 마지막 줄 0.28~0.94).
    """
    body = [r for r in rows
            if r.get('rect') and r.get('style') == 'body'
            and r.get('kind') == 'text' and ' | ' not in r.get('text', '')]
    if len(body) < 2:
        return list(rows)
    rights = sorted(r['rect'][2] for r in body)
    margin = rights[int(len(rights) * 0.9)]
    out = []
    for r in rows:
        r = dict(r)
        r.setdefault('rects', [r['rect']] if r.get('rect') else [])
        prev = out[-1] if out else None
        if prev is not None and _can_join(prev, r, margin):
            # ★ 조건 판정은 **마지막에 붙인 줄**로 한다(`_can_join` 안에서 `_last`).
            sep = _join_sep(prev.get('_tail', prev['text']), r['text'])
            a = prev['text']
            if sep == '-drop':
                a, sep = a.rstrip()[:-1], ''
            prev['text'] = a.rstrip() + sep + r['text'].lstrip()
            prev['rects'] = list(prev.get('rects', [])) + list(r.get('rects', []))
            pr, rr = prev['rect'], r['rect']
            prev['rect'] = (min(pr[0], rr[0]), min(pr[1], rr[1]),
                            max(pr[2], rr[2]), max(pr[3], rr[3]))
            prev['_last'] = rr           # 다음 판정의 기준
            prev['_tail'] = r['text']    # 끝의 빈칸도 마지막 줄의 것
            continue
        out.append(r)
    for r in out:
        r['text'] = r['text'].rstrip()
        r.pop('_last', None)
        r.pop('_tail', None)
    return out


def _can_join(a, b, margin) -> bool:
    """SOT §3.7 의 여덟 조건을 모두 본다."""
    # ★ 260910: 이미 이어 붙인 줄이면 **마지막에 붙인 줄**로 잰다. 합친 사각형으로 재면
    #   오른쪽 끝이 늘 여백까지 차 있어 ④ 가 무력해진다(문단 마지막 줄까지 붙는다).
    ra = a.get('_last') or a.get('rect')
    rb = b.get('rect')
    if not ra or not rb:
        return False
    ta = a.get('_tail', a.get('text', ''))
    tb = b.get('text', '')
    if a.get('style') != 'body' or b.get('style') != 'body':
        return False                                    # ①
    if a.get('kind') != 'text' or b.get('kind') != 'text':
        return False                                    # ①
    if ' | ' in ta or ' | ' in tb:
        return False                                    # ②
    core = ta.rstrip()
    if not core or core[-1] in SENT_END:
        return False                                    # ③
    sa = max(1.0, a.get('size') or (ra[3] - ra[1]))
    sb = max(1.0, b.get('size') or (rb[3] - rb[1]))
    if ra[2] < margin - sa * JOIN_FILL:
        return False                                    # ④ 오른쪽이 안 찼다
    # ⑤ 왼쪽 여백. 뒷줄이 들여써져 있으면 보통 **새 문단**이지만, 앞줄이 목록 항목의
    #   첫 줄이면(`(3) …`) 그 다음 줄들은 표시 아래로 들여쓰는 것이 정상이다
    #   (내어쓰기). 실측 지침 41쪽: 첫 줄 x=68.0, 이어지는 줄 x=86.8.
    if rb[0] > ra[0] + sa and not _starts_list(ta):
        return False
    if rb[0] > ra[0] + sa * 4:
        return False                                    # 너무 많이 들여썼다 — 다른 글
    pitch = rb[1] - ra[1]                               # ⑥ 줄 사이 거리
    if pitch <= 0 or pitch > max(sa, sb) * JOIN_PITCH:
        return False
    if _starts_list(tb):
        return False                                    # ⑦
    if abs(sa - sb) > max(sa, sb) * JOIN_SIZE_TOL:
        return False                                    # ⑧
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
               ocr_words=None, ocr_dpi: int = 0, join_lines: bool = True) -> list:
    """쪽 하나의 줄 목록(SOT §3). `tables` = "lines"(기본) / "omit" / "off".

    `ocr_text` 는 텍스트층이 쓸 만하지 않을 때 쓰는 OCR 결과(단어장 SOT 의 study.db).
    """
    try:
        page = doc.load_page(int(page_index))
    except Exception:
        return []
    if ocr_words:
        # 260908-8: [OCR 다시 읽기] 로 새로 읽은 쪽.
        rows = lines_from_words(ocr_words, dpi=ocr_dpi, page=page)
        if rows:
            _NOISE["n"] = 0
            if join_lines:
                rows = join_sentences(rows)
            if not has_text_layer(doc, page_index):
                return rows                     # 스캔 쪽 — OCR 이 전부다
            # 260909-2(SOT §3.1.3): 글자층이 있는 쪽은 **갈아 끼우지 않고 합친다**.
            #   글자층이 정확하고, 그림 속 글만 OCR 로 채운다.
            base = page_lines(doc, pdf_path, page_index, tables=tables,
                              tables_cached_only=tables_cached_only,
                              join_lines=join_lines)
            return merge_layer_and_ocr(base, rows)
    items = _line_items(page)
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
        rows_out = join_sentences(rows_out)
    return rows_out


def lines_from_words(words, *, dpi: int = 0, page=None) -> list:
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
    items = []
    for col in ([frags] if page is None else _by_column([((0, 0, 0, 0), frags)], page)):
        items.extend(_merge_rows(col))
    items = [it for it in items if not _noise.is_symbol_only(it[1])]
    styles = _classify(items)
    return [{'text': t, 'style': st, 'rect': r, 'kind': 'text', 'size': sz}
            for (r, t, sz), st in zip(items, styles)]

def merge_layer_and_ocr(layer_rows, ocr_rows, *, frac: float = 0.5) -> list:
    """글자층 줄 + **그림 속에만 있던** OCR 줄 (SOT §3.1.3, 260909-2).

    사용자 보고: 표지 제목·붙여 넣은 표 그림의 글이 텍스트 창에 아예 안 나온다.
    그 쪽은 **글자층과 그림이 섞인 쪽**이었다 — 글자층만 읽으니 그림 속 글은 없고,
    OCR 로 갈아 끼우면 멀쩡한 글자층까지 짐작한 글자로 바뀐다. 그래서 **합친다**.

    글자층 줄은 그대로 두고, OCR 줄 중 **어느 글자층 줄과도 겹치지 않는 것**만 더한다
    (겹치면 같은 글을 두 번 보여 주게 된다). 자리 순서로 다시 정렬한다.
    """
    keep = list(layer_rows or [])
    for r in (ocr_rows or []):
        rc = r.get('rect')
        if not rc:
            continue
        if any(_inside(rc, x['rect'], frac) for x in keep if x.get('rect')):
            continue
        r = dict(r)
        r['kind'] = 'ocr'          # 어디서 왔는지 남긴다(창 안내·검증용)
        keep.append(r)
    keep.sort(key=lambda x: ((x['rect'][1] if x.get('rect') else 0),
                             (x['rect'][0] if x.get('rect') else 0)))
    return keep

def clean_page_texts(pdf_path, pages=None, *, ocr_lookup=None) -> list:
    """쪽마다 **이 창이 보여 주는 글**을 모아 [(쪽, 글)] 로 (SOT §3.1.5, 260910).

    단어장은 종전에 `study.db` 의 **날것 `ocr_page.text`** 를 읽어 낱말을 뽑았다.
    그 글은 화면과 다르다 — 기호 줄이 살아 있고, 표 칸이 흩어져 있고, 끊긴 낱말
    (`취사` + `선택`)이 따로 놀고, 고쳐 둔 것이 반영돼 있지 않다. 그래서
    **의미 없는 낱말이 단어장에 많이 들어갔다**(사용자 보고).

    여기서는 §3.A 의 열 단계를 다 거친 줄을 쓰고, 고침(§5.1)까지 얹는다.
    실패하면 빈 목록을 돌려준다 — 부르는 쪽이 날것으로 돌아갈 수 있게.
    """
    try:
        import fitz
    except Exception:
        return []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return []
    try:
        from viewer.text_fix_store import store as _fix_store
        fixes = _fix_store()
    except Exception:
        fixes = None
    out = []
    try:
        idx = range(doc.page_count) if pages is None else [int(p) for p in pages]
        for pno in idx:
            if pno < 0 or pno >= doc.page_count:
                continue
            try:
                ocr = (ocr_lookup(pno) if ocr_lookup else '') or ''
                rows = page_lines(doc, str(pdf_path), pno, tables='lines',
                                  ocr_text=ocr)
            except Exception:
                continue
            lines = [r.get('text', '') for r in rows]
            if fixes is not None:
                try:
                    lines = fixes.apply_to_text(str(pdf_path), pno, lines)
                except Exception:
                    pass
            out.append((pno, chr(10).join(x for x in lines if x)))
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return out

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
