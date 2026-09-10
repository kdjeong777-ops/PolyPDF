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
# 260910-8(SOT §3.6.4): 단 사이 빈 띠의 최소 폭(쪽 너비 대비).
#   실측 0.012~0.038 — 종전 0.04 는 **실제 2단 쪽을 하나도 통과시키지 못했다**.
COL_GUTTER_MIN = 0.015
# 본문 폭의 이 비율을 넘게 걸치는 **조각**은 전폭 줄(제목·머리띠·넓은 캡션)이다.
COL_FULL = 0.60
# 한쪽 단이 다른 쪽보다 이 비율보다 좁으면 **단이 아니라 값 칸**이다(목차의 쪽번호 등).
#   실측: 목차 0.06~0.09 / 진짜 2단 0.45~1.87.
COL_WIDTH_MIN = 0.25
# 260910-9(SOT §3.6.5): 표의 **가로 줄**로 행을 가른다. 그 행 안의 어느 칸이든
#   두 줄 이상이면 **칸 단위로** 읽는다 — 줄 단위로 이으면 칸끼리 뒤섞인다.
CELL_GAP = 6.0          # 칸 사이 가로 빈틈(pt). 이보다 벌어지면 다른 칸
CELL_GAP_H = 0.60       # 글자 높이의 이 비율도 넘어야 다른 칸(큰 제목 대비)
HRULE_SPAN = 0.50       # 본문 폭의 이 비율을 넘는 가로 줄만 '행 구분선'
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
    if above:
        groups.append(above)
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
        groups.append(below)
    return groups if multi else None


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
    gx = _gutter_x(bands, page)
    if gx is None:
        return [frags]
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
    if owners is not None:      # 조각을 원래 낱말로 되돌린다
        groups = [[w for pc in g for w in owners.get(id(pc), [pc])] for g in groups]
    return groups


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
# 줄 **간격**이 아니라 **줄 사이 거리(pitch)** 를 글자 크기로 잰다 — 간격으로 재면
#   글자가 큰데 줄이 성긴 쪽(발표자료·서식)에서 남남인 줄이 붙는다(260910 실측).
#   실측 pitch÷크기: 이어지는 본문 1.6~1.8 / 따로 놓인 줄 2.9.
JOIN_PITCH = 2.2
JOIN_SIZE_TOL = 0.20     # 글자 크기가 이만큼 안에서 같아야 한다
_CAPTION_HEAD = None
_LIST_HEAD = None


def _starts_list(text) -> bool:
    """목록 표시로 시작하는가 — `1.` `가.` `①` `•` `-` `(1)` 등 (SOT §3.7 ⑦)."""
    global _LIST_HEAD
    if _LIST_HEAD is None:
        import re
        _LIST_HEAD = re.compile(
            r'^\s*(?:\(?\d+[.)]|\(?[' + KO_LIST_ORDER + r'][.)]|[①-⑳]|[•·▶◊▊☞*\-–—]\s|○|※)')
    return bool(_LIST_HEAD.match(text or ''))


def _join_sep(a_text, b_text, wrapped: bool = False) -> str:
    """두 줄을 어떻게 이을지 — 빈칸 / 붙임 / 분철 떼기 (SOT §3.7·§3.7.7).

    `wrapped` 는 **어절이 안 들어가서 넘어갔는가**(④ 의 둘째 갈래). 참이면 줄이 바뀐
    자리는 **어절 경계**이므로 한글끼리라도 빈칸을 넣는다. 거짓(줄이 여백까지 꽉 참)이면
    낱말 가운데서 잘렸을 수 있어 붙인다 — 실측 `의무사` + `용대상` = `의무사용대상`.
    """
    if a_text.endswith(' '):
        return ' '
    a = a_text.rstrip()
    b = (b_text or '').lstrip()
    if not a or not b:
        return ''
    if a.endswith('-') and ('a' <= b[0] <= 'z'):
        return '-drop'
    if _is_cjk(a[-1]) and _is_cjk(b[0]):
        return ' ' if wrapped else ''
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
    # 260910-12(사용자 보고 "부호로 잇는 규칙이 적용 안 된다", SOT §3.7.8):
    #   여백은 **단마다** 잰다. 쪽 하나로 재면 2단 쪽에서 왼쪽 단이 한 줄도 못 잇는다 —
    #   실측 1쪽: 쪽 전체 90분위 556.9 인데 왼쪽 단은 **가장 긴 줄도 300.2** 라
    #   ④(오른쪽까지 찼는가)가 언제나 거짓이었다.
    cols = _column_extents(body)
    idx = {id(q): i for i, q in enumerate(body)}
    out = []
    for r in rows:
        r = dict(r)
        r.setdefault('rects', [r['rect']] if r.get('rect') else [])
        prev = out[-1] if out else None
        # 260910-12: 이웃한 줄(같은 단, 앞뒤 4줄)로 **그 자리의** 여백을 본다.
        _k = idx.get(id(r))
        _near = None
        if _k is not None:
            _lo, _hi = max(0, _k - 4), min(len(body), _k + 5)
            _near = [q for q in body[_lo:_hi]
                     if abs(q['rect'][0] - r['rect'][0]) <= 24.0]
        margin, span = _extent_for(cols, r, _near)
        if prev is not None and _can_join(prev, r, margin, span):
            # ★ 조건 판정은 **마지막에 붙인 줄**로 한다(`_can_join` 안에서 `_last`).
            # 260910-4(SOT §3.7.7): 왜 넘어갔는지가 빈칸 여부를 가른다.
            #   어절이 안 들어가서 넘어갔으면 그 자리는 어절 경계다.
            _ra = prev.get('_last') or prev['rect']
            _sa = max(1.0, prev.get('size') or 0)
            _wrapped = (margin - _ra[2]) > _sa * JOIN_FILL
            sep = _join_sep(prev.get('_tail', prev['text']), r['text'], _wrapped)
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
    return bool(_CAPTION_HEAD.match(t or ''))


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


def _can_join(a, b, margin, span: float = 0.0) -> bool:
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
    # ④ 오른쪽이 찼는가. 260910-4(SOT §3.7.6 가): 고정 문턱만 보면 **11.4pt 모자란**
    #   줄이 탈락했는데, 뒷줄 첫 어절은 18pt 라 애초에 들어갈 수 없었다 — 문단이 끝난 게
    #   아니라 자리가 없어 넘어간 것이다. 그래서 거의 찼으면 통과, 덜 찼으면
    #   **그 빈칸에 뒷줄 첫 어절이 들어갔겠는가**를 묻는다.
    gap = margin - ra[2]
    if gap > sa * JOIN_FILL:
        if span > 0 and gap > span * JOIN_GAP_MAX:
            return False            # 너무 많이 남았다 — 어떤 어절이 와도 문단 끝
        w = _first_word_width(b)
        if w <= 0 or gap >= w * JOIN_WORD_SLACK:
            return False            # 넉넉히 들어갔을 텐데 넘어갔다 → 문단이 끝났다
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
    # ⑦ 260910-4(SOT §3.7.6 나): 앞줄에 닫히지 않은 `(` 가 있으면 뒷줄의 `)` 는
    #   목록 표시가 아니라 그 괄호를 닫는 이어지는 글이다.
    if _starts_list(tb) and not _unclosed_paren(ta):
        return False                                    # ⑦
    if abs(sa - sb) > max(sa, sb) * JOIN_SIZE_TOL:
        return False                                    # ⑧
    # ⑨ 260910-4(SOT §3.7.6 다): 표·그림 제목은 **첫머리로** 알아본다.
    #   캡션은 부호로 끝나지 않고 길이도 본문과 비슷할 수 있어 ④ 로는 안 갈린다.
    if _is_caption(ta):
        return False
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
    for col in ([frags] if page is None
                else _by_column([((0, 0, 0, 0), frags)], page, word_level=True)):
        items.extend(_merge_rows(col))
    items = [it for it in items if not _noise.is_symbol_only(it[1])]
    styles = _classify(items)
    return [{'text': t, 'style': st, 'rect': r, 'kind': 'text', 'size': sz}
            for (r, t, sz), st in zip(items, styles)]

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
        return src
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
        return src
    out = []
    for grp in groups:
        for bd in sorted(_row_bands(grp), key=lambda b: (b["y0"], b["y1"])):
            for f in sorted(bd["items"], key=lambda q: q[0][0]):
                i = pos.get(id(f))
                if i is not None:
                    out.append(keep[i])
    # 하나라도 빠지면 원래 차례를 쓴다 — 읽다 마는 것보다 낫다
    return out if len(out) == len(src) else src


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
                words, wdpi = (words_lookup(pno) if words_lookup else (None, 0))
                rows = page_lines(doc, str(pdf_path), pno, tables='lines',
                                  ocr_text=ocr, ocr_words=words or None,
                                  ocr_dpi=int(wdpi or 0))
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
