# -*- coding: utf-8 -*-
"""쪽 블록 — 글 줄·표·그림을 쓰기 좋은 꼴로 (형식 변환 SOT §1·§3, 261014-14).

`page_blocks(ps, 쪽, join=)` 이 Word·HWPX 쓰기의 공통 입력이다.
- 글 줄은 `ps.lines`(텍스트 창 SOT §3 `page_lines` — 고침·스캔 쪽 OCR 반영) 그대로. `join=True` 면 문단으로 이은 줄(편집 가능),
  False 면 원본 줄(모양 그대로). 표 안 글은 빼고(`tables="omit"`) 표는 따로 블록이 된다.
- 줄의 굵기·세리프는 같은 쪽 글자 조각(`get_text("dict")`)에서 겹치는 것으로 읽는다.
- 그림은 쪽에 박힌 그림과 **선으로 그린 그림**(도표·그래프). 선 그림은 그 영역을 그려 그림 한 장으로 넣고, 영역 안에 든 글 줄은 뺀다.
  그림 제목처럼 영역 밖의 줄은 글이다(사용자 지시 261014-14 — "그림은 수정이 필요하지 않아. 그림제목은 텍스트").

블록은 dict — `kind`("line"/"table"/"image"), `rect`(x0, y0, x1, y1 pt, 위가 0). 차례는 읽는 차례(줄)이고, 표·그림은 그 자리 아래 첫 줄 앞에 끼운다.
"""
from __future__ import annotations

FIGURE_DPI = 200        # 선 그림·그대로 못 쓰는 그림을 그릴 때
FIG_MIN_PT = 36         # 선 그림으로 보는 가장 작은 가로·세로
FIG_MIN_PATHS = 4       # 선 조각이 이만큼은 있어야 그림(글 상자 테두리·밑줄은 그림이 아니다)
FIG_MAX_TEXT = 0.5      # 영역 안 글 면적이 이 비율 이상이면 글 상자다
BG_MIN_AREA = 0.8       # 쪽의 이만큼을 덮는 그림은 바탕(스캔 쪽 그림·장식) — 넣지 않는다
IMG_MIN_PT = 4          # 이보다 작은 그림은 장식

SERIF_FILE = "batang.ttc"     # Windows 에 늘 있는 글꼴 — 문서에 쓰는 이름과 짝
SANS_FILE = "malgun.ttf"
SERIF_FACE = "바탕"            # 문서 안 글꼴 이름(화면 문구가 아니다)
SANS_FACE = "맑은 고딕"


def _area(r) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _inter(a, b) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def _inside(inner, outer, pad=2.0) -> bool:
    return (inner[0] >= outer[0] - pad and inner[1] >= outer[1] - pad
            and inner[2] <= outer[2] + pad and inner[3] <= outer[3] + pad)


def _span_styles(page) -> list:
    """`[(자리, 굵음, 세리프, 글자 수, 글)]` — 줄의 굵기·글꼴 갈래와 나란한 조각의 자리를 읽는 데만 쓴다."""
    out = []
    try:
        d = page.get_text("dict")
    except Exception:
        return out
    for b in d.get("blocks", []):
        for ln in b.get("lines", []) or []:
            for sp in ln.get("spans", []) or []:
                t = (sp.get("text") or "").strip()
                if not t:
                    continue
                fl = int(sp.get("flags", 0) or 0)
                name = str(sp.get("font", "")).lower()
                bold = bool(fl & 16) or "bold" in name or name.endswith(",b") or "-b" in name[-3:]
                serif = bool(fl & 4) or any(k in name for k in ("batang", "myeongjo", "myungjo", "times", "serif", "명조", "바탕"))
                if any(k in name for k in ("gothic", "dotum", "gulim", "arial", "helvetica", "sans", "고딕", "돋움", "굴림")):
                    serif = False
                out.append((tuple(sp.get("bbox", (0, 0, 0, 0))), bold, serif, len(t), t))
    return out


def _style_of(rects, spans, default_serif: bool):
    nb = ns = n = 0
    for r in rects:
        for bb, bold, serif, k, _t in spans:
            if bb[1] >= r[3] or bb[3] <= r[1] or bb[0] >= r[2] or bb[2] <= r[0]:
                continue
            n += k
            nb += k if bold else 0
            ns += k if serif else 0
    if not n:
        return False, default_serif
    return nb * 2 >= n, ns * 2 >= n


def _figures(page, tables, lines) -> list:
    """선으로 그린 그림 영역(§1 조건)."""
    try:
        clusters = page.cluster_drawings()
        paths = [p.get("rect") for p in page.get_drawings()]
    except Exception:
        return []
    prect = page.rect
    parea = _area(tuple(prect))
    out = []
    for c in clusters:
        r = (c.x0, c.y0, c.x1, c.y1)
        if (r[2] - r[0]) < FIG_MIN_PT or (r[3] - r[1]) < FIG_MIN_PT:
            continue
        a = _area(r)
        if a >= BG_MIN_AREA * parea:                     # 쪽 테두리
            continue
        if any(_inter(r, tuple(t)) > 0.3 * a for t, _rows in tables):
            continue
        n = sum(1 for pr in paths if pr is not None and _inside((pr.x0, pr.y0, pr.x1, pr.y1), r))
        if n < FIG_MIN_PATHS:
            continue
        txt = sum(_area(ln["rect"]) for ln in lines if ln.get("rect") and _inside(ln["rect"], r))
        if txt >= FIG_MAX_TEXT * a:
            continue
        out.append(r)
    return out


def _render(page, r) -> bytes:
    import fitz
    pix = page.get_pixmap(clip=fitz.Rect(r), dpi=FIGURE_DPI, alpha=False)
    return pix.tobytes("png")


def _images(ps, page, figs) -> list:
    """쪽에 박힌 그림 → 블록. 바탕·장식·선 그림 안의 것은 뺀다(§1)."""
    import fitz
    out = []
    prect = page.rect
    parea = _area(tuple(prect))
    seen = set()
    try:
        # 자리·변환을 한 번에. xrefs=True 는 그림마다 풀어 해시를 내 느리다(실측 30쪽 3.9초) — xref 는 크기·색으로 짝짓는다
        infos = page.get_image_info()
        by_shape = {}
        for it in page.get_images(full=True):
            by_shape.setdefault((it[2], it[3], it[4]), []).append(it[0])     # (가로, 세로, bpc) → xref
    except Exception:
        return out
    for info in infos:
        cand = by_shape.get((info.get("width"), info.get("height"), info.get("bpc")), [])
        xref = cand[0] if len(set(cand)) == 1 else 0            # 짝이 하나로 정해질 때만 원본 바이트 — 아니면 그 자리를 그린다
        rect = fitz.Rect(info.get("bbox") or (0, 0, 0, 0))
        m = fitz.Matrix(info.get("transform") or (1, 0, 0, 1, 0, 0))
        rr = rect & prect
        if rr.is_empty:
            continue
        r = (rr.x0, rr.y0, rr.x1, rr.y1)
        key = tuple(round(v, 1) for v in r)
        if key in seen:
            continue
        seen.add(key)
        if (r[2] - r[0]) < IMG_MIN_PT or (r[3] - r[1]) < IMG_MIN_PT or _area(r) >= BG_MIN_AREA * parea:
            continue
        if any(_inside(r, f) for f in figs):
            continue
        upright = abs(m.b) < 1e-3 and abs(m.c) < 1e-3 and m.a > 0 and m.d > 0 and rr == rect
        data, fmt = None, "png"
        if upright and xref > 0:
            try:
                img = ps.doc.extract_image(xref)
            except Exception:
                img = None
            ext = str((img or {}).get("ext", "")).lower()
            if img and img.get("image") and ext in ("png", "jpeg", "jpg") \
                    and not img.get("smask") and int(img.get("colorspace", 3) or 3) in (1, 3):
                data, fmt = img["image"], ("jpg" if ext != "png" else "png")
        if data is None:
            try:
                data = _render(page, r)
            except Exception:
                continue
        out.append({"kind": "image", "rect": r, "data": data, "fmt": fmt})
    return out


def _split_pieces(text, rect, spans) -> list:
    """같은 줄에 벌어져 놓인 조각(텍스트 창 SOT §3.6 의 ` | ` 이음)을 원본 자리대로 다시 가른다 — 모양 그대로만.
    조각마다 그 글로 시작하는 글자 조각을 줄 안에서 찾고, 하나라도 못 찾으면 가르지 않는다."""
    parts = text.split(" | ")
    if len(parts) < 2:
        return [(text, rect)]
    cy = (rect[1] + rect[3]) / 2
    row = sorted((sp for sp in spans if sp[0][1] <= cy <= sp[0][3] and sp[0][0] >= rect[0] - 1 and sp[0][2] <= rect[2] + 1),
                 key=lambda sp: sp[0][0])
    xs, k = [], 0
    for part in parts:
        head = part.strip()[:4]
        while k < len(row) and not row[k][4].startswith(head):
            k += 1
        if k >= len(row) or not head:
            return [(text, rect)]
        xs.append(k)
        k += 1
    out = []
    for n, (part, k) in enumerate(zip(parts, xs)):
        end = xs[n + 1] if n + 1 < len(xs) else len(row)
        x0 = row[k][0][0]
        x1 = max(sp[0][2] for sp in row[k:end])
        out.append((part, (x0, rect[1], x1, rect[3])))
    return out


def page_blocks(ps, pg, *, join: bool, edges=None) -> list:
    """쪽 하나의 블록 목록(읽는 차례). 형식 변환 SOT §1·§3.
    `edges` 에 list 를 주면 머리말·꼬리말 줄(§1.1 — 본문 블록에는 없다)을 굵기·세리프를 붙여 채운다."""
    page = ps.doc.load_page(int(pg))
    raw_edges = [] if edges is not None else None
    rows = ps.lines(pg, tables="omit", join=join, edges=raw_edges)
    tables = ps.tables(pg)
    spans = _span_styles(page)
    serif_n = sum(k for _b, _bo, se, k, _t in spans if se)
    all_n = sum(k for _b, _bo, _se, k, _t in spans)
    default_serif = (serif_n * 2 >= all_n) if all_n else True
    for e in raw_edges or ():
        e = dict(e)
        e["bold"], e["serif"] = _style_of([tuple(e["rect"])], spans, default_serif)
        e["pw"], e["ph"] = float(page.rect.width), float(page.rect.height)
        edges.append(e)
    lines = []
    for r in rows:
        text = r.get("text", "")
        if r.get("kind", "text") != "text" or not str(text).strip():     # 표 자리 표시 줄 — 표는 표 블록으로
            continue
        rect = tuple(r["rect"]) if r.get("rect") else None
        size = float(r.get("size") or 0) or (((rect[3] - rect[1]) / 1.25) if rect else 10.0)
        pieces = _split_pieces(text, rect, spans) if (not join and rect) else [(text, rect)]
        for ptext, prect in pieces:
            rects = [prect] if prect and len(pieces) > 1 else                 [tuple(x) for x in (r.get("rects") or ([rect] if rect else []))]
            bold, serif = _style_of(rects, spans, default_serif)
            lines.append({"kind": "line", "rect": prect, "rects": rects, "text": ptext, "style": r.get("style", "body"),
                          "size": max(4.0, size), "bold": bold, "serif": serif})
    figs = _figures(page, tables, lines)
    if figs:
        lines = [ln for ln in lines if not (ln["rect"] and any(_inside(ln["rect"], f) for f in figs))]
    objs = [{"kind": "table", "rect": tuple(b), "rows": [list(x) for x in rows_ if x]} for b, rows_ in tables]
    objs = [o for o in objs if o["rows"]]
    for f in figs:
        try:
            objs.append({"kind": "image", "rect": f, "data": _render(page, f), "fmt": "png"})
        except Exception:
            pass
    objs += _images(ps, page, figs)
    objs.sort(key=lambda o: (o["rect"][1], o["rect"][0]))
    # 표·그림은 그 자리 아래(가로가 겹치는) 첫 줄 앞에 — 2단 쪽에서도 그 단 안에 들어간다
    out = list(lines)
    for o in objs:
        x0, y0, x1, _y1 = o["rect"]
        at = len(out)
        for k, b in enumerate(out):
            br = b.get("rect")
            if b["kind"] == "line" and br and br[1] >= y0 - 1 and br[0] < x1 and br[2] > x0:
                at = k
                break
        out.insert(at, o)
    return out


# ---- 글자 너비 재기(모양 그대로의 자간) --------------------------------------
import threading
_TLS = threading.local()        # PyMuPDF 개체는 만든 스레드에서만(응답성 SOT §4 ⑤)


def _font(serif: bool):
    key = SERIF_FILE if serif else SANS_FILE
    _FONTS = _TLS.__dict__.setdefault("fonts", {})
    if key not in _FONTS:
        f = None
        try:
            import os
            import fitz
            p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", key)
            if os.path.exists(p):
                f = fitz.Font(fontfile=p)
        except Exception:
            f = None
        _FONTS[key] = f
    return _FONTS[key]


def measure(text: str, size: float, serif: bool):
    """그 글꼴로 잰 너비(pt). 글꼴 파일이 없으면 None — 자간을 맞추지 않는다."""
    f = _font(serif)
    if f is None:
        return None
    try:
        return float(f.text_length(text, fontsize=size))
    except Exception:
        return None


# ---- 머리말·꼬리말(§1.1) -----------------------------------------------------
def page_edges(ps, pg) -> list:
    """쪽 하나의 머리말·꼬리말 줄만(굵기·세리프·쪽 너비 붙임) — 블록이 필요 없는 Word 모양 그대로(§4.1)가 쓴다."""
    page = ps.doc.load_page(int(pg))
    raw = []
    ps.lines(pg, tables="off", join=False, edges=raw)
    if not raw:
        return []
    spans = _span_styles(page)
    all_n = sum(k for _b, _bo, _se, k, _t in spans)
    default_serif = (sum(k for _b, _bo, se, k, _t in spans if se) * 2 >= all_n) if all_n else True
    out = []
    for e in raw:
        e = dict(e)
        e["bold"], e["serif"] = _style_of([tuple(e["rect"])], spans, default_serif)
        e["pw"], e["ph"] = float(page.rect.width), float(page.rect.height)
        out.append(e)
    return out


NUM_TOKEN = "\x00#\x00"        # 틀 안의 쪽 번호 자리(쓰기에서 쪽 번호 필드로 바꾼다)


EDGE_SNAP = 0.06        # 글 영역 너비의 이 비율 안이면 가운데·오른쪽 끝에 맞춘 것으로 본다


def compose(ln, tpw: float, left: float, right: float, *, spaces: bool = False) -> tuple:
    """머리말·꼬리말 한 줄 → (글, 맞춤, 들여쓰기 pt) — 대상 문서의 쪽 너비 `tpw`, 글 영역 [left, right] 에 맞춘다(§1.1).

    원본 자리를 쪽 너비 비율로 옮겨, 가운데면 CENTER, 오른쪽 끝이면 RIGHT, 그 밖은 LEFT + 들여쓰기.
    조각이 둘 이상이면 LEFT 에 사이를 빈칸으로 벌린다. `spaces=True` 면 들여쓰기도 빈칸으로(문단 들여쓰기를 줄 수 없는 곳)."""
    pieces, size, serif = ln["pieces"], ln["size"], ln["serif"]
    k = tpw / max(1.0, float(ln.get("pw") or tpw))
    w = max(1.0, right - left)
    sp = measure(" ", size, serif) or size * 0.3
    x0, x1 = pieces[0][0] * k, pieces[-1][1] * k
    if len(pieces) == 1:
        text = pieces[0][2]
        if abs((x0 + x1) / 2 - (left + right) / 2) <= w * EDGE_SNAP:
            return text, "CENTER", 0.0
        if abs(x1 - right) <= w * EDGE_SNAP:
            return text, "RIGHT", 0.0
    else:
        text = pieces[0][2]
        for prev, cur in zip(pieces, pieces[1:]):
            gap = (cur[0] - prev[1]) * k
            text += " " * max(1, min(200, int(round(gap / max(0.5, sp))))) + cur[2]
    indent = max(0.0, x0 - left)
    if spaces and indent > 0:
        return " " * min(200, int(round(indent / max(0.5, sp)))) + text, "LEFT", 0.0
    return text, "LEFT", indent


def number_only(text: str, token: str | None = None):
    """줄이 쪽 번호뿐인가(`12`·`- 12 -`·`—12—`) → 양옆 글자(`"-"` 또는 `""`), 아니면 None (§1.1 — 한글 '쪽 번호 매기기' 로).
    `token` 을 주면 숫자 대신 그 자리 표시(`NUM_TOKEN`)를 찾는다."""
    import re
    num = re.escape(token) if token else r"\d{1,5}"
    m = re.match(r"^\s*([-–—]?)\s*" + num + r"\s*([-–—]?)\s*$", str(text or ""))
    if not m:
        return None
    return "-" if (m.group(1) or m.group(2)) else ""


def edge_plan(per_page: dict) -> dict:
    """쪽별 머리말·꼬리말 줄 `{쪽: [줄]}` → 문서 하나의 틀(편집 가능용, §1.1).

    - 쪽 번호: 줄 안 숫자 중 '쪽 번호 − 쪽 위치' 가 두 쪽 이상에서 같은 것 → `NUM_TOKEN`(쓰기에서 쪽 번호 필드).
    - 틀은 쪽 번호를 바꾼 글로 견주어 가장 흔한 것. 홀·짝 쪽(인쇄 번호 기준)의 틀이 다르면 따로 둔다.
    반환 `{"head"|"foot": {"BOTH"|"ODD"|"EVEN": [줄]}, "start": 첫 쪽의 인쇄 번호 또는 None}`.
    쪽 번호뿐인 줄은 `number_only(…, NUM_TOKEN)` 으로 가린다 — 한글은 그 줄을 '쪽 번호 매기기' 로 넣는다."""
    import re
    from collections import Counter
    votes = Counter()
    for pg, lines in per_page.items():
        for ln in lines:
            for n in set(re.findall(r"\d+", ln["text"])):
                if len(n) <= 5:
                    votes[int(n) - int(pg)] += 1
    off = None
    if votes:
        o, c = votes.most_common(1)[0]
        if c >= 2:
            off = o
    plan = {"head": {}, "foot": {}, "start": None}
    if off is not None and per_page:
        plan["start"] = min(per_page) + off

    def templ(pg, ln):
        pieces = []
        for x0, x1, t in ln["pieces"]:
            if off is not None:
                t = re.sub(r"(?<!\d)%d(?!\d)" % (int(pg) + off), NUM_TOKEN, t, count=1)
            pieces.append((x0, x1, t))
        return dict(ln, pieces=pieces)

    for where in ("head", "foot"):
        by_parity = {0: Counter(), 1: Counter()}
        sample = {}
        for pg, lines in sorted(per_page.items()):
            mine = [templ(pg, ln) for ln in lines if ln["where"] == where]
            if not mine:
                continue
            key = tuple(" ".join(p[2] for p in ln["pieces"]) for ln in mine)
            num = (int(pg) + (off or 0)) % 2
            by_parity[num][key] += 1
            sample.setdefault(key, mine)
        tops = {k: c.most_common(1)[0][0] for k, c in by_parity.items() if c}
        if not tops:
            continue
        if len(tops) == 2 and tops[0] != tops[1]:
            plan[where]["EVEN"] = sample[tops[0]]
            plan[where]["ODD"] = sample[tops[1]]
        else:
            allc = by_parity[0] + by_parity[1]
            plan[where]["BOTH"] = sample[allc.most_common(1)[0][0]]
    return plan
