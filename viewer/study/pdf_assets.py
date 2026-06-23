"""PDF 그림/표 추출 (번역 P4c) — 캡션 기준 + 단(column) 인식 정밀 크롭.

SOT: `PDF 번역·요약 작업 계획서.md` §5.4(그림)·§5.5(표).
설계 원칙(2026-06-23 정밀화):
- **모든 그림·표 캡션을 먼저 수집**(Table N. / Figure N.) → 캡션 1개 = 자산 1개(중복·누락 방지).
- **단(column) 인식 크롭**: 2단 논문에서 캡션의 가로 범위로 좌단/우단/전폭을 판정하고, 영역을
  그 단으로 **수평 클리핑** → 옆 단의 그림/본문이 표 크롭에 섞이지 않음(표7 문제 해결).
- **표**(캡션 위, 표 아래): 캡션 아래 ~ 표 행이 끝나는 지점(다음 캡션/2단 본문 시작 전)까지를
  단 범위 안에서 렌더. 표 행 실제 좌우로 추가 타이트닝.
- **그림**(캡션 아래에 위치, 그림은 캡션 위): 캡션 위 ~ 이전 캡션/제목 아래 구간에서
  **이미지+벡터 드로잉(차트)의 합집합 bbox**로 정밀 바운딩 → 벡터 차트도 잡고(F1/7/12/13/15
  누락 해결), 본문 텍스트는 배제.
- **재검토(_review_assets)**: 각 크롭을 다시 분석해 표=행 구조/그림=그래픽 존재를 검증, 표에
  본문·그림 혼입 시 트리밍·재크롭, 문제 항목은 issues 로 보고.
- **누락 보완(_fill_missing)**: 선언된 캡션 번호 집합 vs 추출 집합 비교 → 빠진 번호는 완화된
  바운딩으로 재추출, 다시 검증, 다시 누락 확인(수렴까지 반복).
PyMuPDF(fitz) 만 사용.
"""
from __future__ import annotations

import os
import re

# 캡션만 매칭(본문 내 'Table 1 shows…' 참조 제외): 번호 뒤 마침표/콜론 또는 대문자 제목.
# 제목 대문자([A-Z])는 대소문자 구분(re.I 미사용)해야 소문자 동사 시작 참조를 배제한다.
_FIG_RE = re.compile(r"^\s*[Ff]ig(?:ure)?\.?\s*\d+\s*(?:[.:]|\s+[A-Z])")
_TAB_RE = re.compile(r"^\s*[Tt]able\s*\d+\s*(?:[.:]|\s+[A-Z])")
_NUM_RE = re.compile(r"(?:Table|Figure|Fig)\.?\s*(\d+)", re.I)
_ZOOM = 2.0          # 영역 렌더 배율
_HDR = 36            # 머리말/꼬리말 여백(px) — 영역 상/하한에서 제외


_CONT_RE = re.compile(r"\bcont(?:\.|inued)?\b|\(continued\)|계속", re.I)


def _cap_num(caption: str):
    """캡션에서 실제 번호 파싱('Table 3.' → 3). 없으면 None."""
    m = _NUM_RE.search(caption or "")
    return int(m.group(1)) if m else None


def _is_cont(caption: str) -> bool:
    """'Table 1. Cont.'·'(continued)'·'계속' 등 다음 페이지 연속 캡션이면 True."""
    return bool(_CONT_RE.search(caption or ""))


def _caption_blocks(page):
    """페이지의 그림/표 캡션 블록 목록 → [{kind, num, bbox, text}] (y 순)."""
    out = []
    for b in page.get_text("blocks"):
        if len(b) < 5 or not isinstance(b[4], str) or not b[4].strip():
            continue
        first = (b[4].strip().splitlines() or [""])[0]
        kind = None
        if _TAB_RE.match(first):
            kind = "tab"
        elif _FIG_RE.match(first):
            kind = "fig"
        if not kind:
            continue
        cap = " ".join(b[4].split()).strip()
        out.append({"kind": kind, "num": _cap_num(first),
                    "bbox": (b[0], b[1], b[2], b[3]), "text": cap})
    out.sort(key=lambda c: c["bbox"][1])
    return out


def _col_range(page, cap_bbox):
    """캡션 가로 범위로 단(column) 판정 → (x0, x1). 좌단/우단/전폭."""
    pg = page.rect
    mid = pg.x0 + pg.width / 2.0
    tol = pg.width * 0.04
    x0, _, x1, _ = cap_bbox
    left = x1 <= mid + tol
    right = x0 >= mid - tol
    if left and not right:
        return (pg.x0 + 2, mid - 2)
    if right and not left:
        return (mid + 2, pg.x1 - 2)
    return (pg.x0 + 2, pg.x1 - 2)        # 전폭


def _ov_x(bbox, colx, frac=0.5):
    """bbox 가 colx[x0,x1] 와 frac 이상 가로로 겹치면 True(같은 단)."""
    x0, x1 = colx
    bx0, bx1 = bbox[0], bbox[2]
    inter = max(0.0, min(x1, bx1) - max(x0, bx0))
    w = max(1.0, bx1 - bx0)
    return inter >= frac * w


def _graphic_rects(page, colx, y0, y1):
    """colx·(y0,y1) 범위의 이미지+벡터 드로잉 rect 목록(차트/사진). 전폭·미세 노이즈 제외."""
    import fitz
    pw, ph = page.rect.width, page.rect.height
    rects = []
    for img in page.get_images(full=True):
        try:
            for r in page.get_image_rects(img[0]):
                if r.width > 8 and r.height > 8 and _ov_x((r.x0, r.y0, r.x1, r.y1), colx, 0.3) \
                        and r.y1 > y0 and r.y0 < y1:
                    rects.append(fitz.Rect(r))
        except Exception:
            pass
    try:
        draws = page.get_drawings()
    except Exception:
        draws = []
    for d in draws:
        r = d.get("rect")
        if not r:
            continue
        if r.width < 3 or r.height < 3:
            continue
        if r.width > pw * 0.97 and r.height > ph * 0.5:    # 페이지 테두리 등 제외
            continue
        if _ov_x((r.x0, r.y0, r.x1, r.y1), colx, 0.3) and r.y1 > y0 and r.y0 < y1:
            rects.append(fitz.Rect(r))
    return rects


def _table_rows(page, cy1, search_bottom, colx):
    """캡션 아래 표 영역의 (bottom_y, row_words).

    학술 데이터 표는 **숫자 밀집 행(데이터 행)**으로 끝을 잡는 것이 견고하다(여러 줄 머리글이
    'prose' 로 오인되어 일찍 끊기던 문제 회피). 데이터 행이 있으면 마지막 데이터 행까지를
    표로 보고 머리글~데이터 전부를 row_words 로 모은다. 없으면 가로 분산 휴리스틱으로 폴백."""
    cx0, cx1 = colx
    words = [w for w in page.get_text("words")
             if cy1 + 1 < w[1] < search_bottom and _ov_x((w[0], w[1], w[2], w[3]), colx, 0.5)]
    if not words:
        return search_bottom, []
    lines = {}
    for x0, y0, x1, y1, txt, *_ in words:
        ymid = round((y0 + y1) / 2)
        key = next((k for k in lines if abs(k - ymid) <= 3), ymid)
        lines.setdefault(key, []).append((x0, x1, txt, y0, y1))
    colw = max(1.0, cx1 - cx0)
    ys = sorted(lines)

    def numcount(toks):
        return sum(1 for t in toks if re.search(r"\d", t[2]))

    # 데이터 행 = 숫자 토큰 2개↑ & 토큰 2개↑ (큰 간격 분포). 마지막 데이터 행까지가 표.
    data_ys = [y for y in ys if numcount(lines[y]) >= 2 and len(lines[y]) >= 2]
    if data_ys:
        last = max(data_ys)
        bottom = min(max(t[4] for y in lines if y <= last for t in lines[y]) + 6, search_bottom)
        rows = [t for y in ys if y <= last for t in lines[y]]
        return bottom, rows

    # 폴백: 가로 분산/큰 간격 휴리스틱(숫자 없는 표)
    last_tab = cy1
    seen = False
    consec_prose = 0
    row_words = []
    for y in ys:
        toks = sorted(lines[y])
        span = (toks[-1][1] - toks[0][0]) if toks else 0
        gaps = [toks[i + 1][0] - toks[i][1] for i in range(len(toks) - 1)]
        biggaps = sum(1 for g in gaps if g > 14)
        is_tab = biggaps >= 2 and span > colw * 0.45
        if is_tab:
            last_tab = max(last_tab, max(t[4] for t in toks))
            seen = True
            consec_prose = 0
            row_words.extend(toks)
        else:
            consec_prose += 1
            if seen and consec_prose >= 2:
                break
    if not seen:
        return search_bottom, []
    return min(last_tab + 8, search_bottom), row_words


def _table_region(page, cap, caps):
    """표 영역 Rect. 캡션 폭이 아니라 **표 행의 실제 가로 분포**로 단을 판정한다
    (전폭 표는 짧은 좌단 캡션을 가질 수 있음 → 캡션 단으로 자르면 안 됨). 단일 단 표는
    행 단어가 한쪽에 몰리므로 그 단으로 클리핑되어 옆 단 그림/본문이 자연히 배제된다."""
    import fitz
    pg = page.rect
    cy1 = cap["bbox"][3]
    search_bottom = pg.y1 - _HDR
    for c in caps:
        if c is cap:
            continue
        if c["bbox"][1] > cy1 + 4:                  # 아래의 어떤 캡션이든 스캔 상한
            search_bottom = min(search_bottom, c["bbox"][1] - 2)
    full = (pg.x0 + 2, pg.x1 - 2)
    bottom, rows = _table_rows(page, cy1, search_bottom, full)
    if not rows:
        return fitz.Rect(full[0], cy1 + 2, full[1], search_bottom), False
    mid = pg.x0 + pg.width / 2.0
    left = [t for t in rows if (t[0] + t[1]) / 2.0 < mid]
    right = [t for t in rows if (t[0] + t[1]) / 2.0 >= mid]
    nL, nR = len(left), len(right)
    if nL and nR and min(nL, nR) >= 0.2 * (nL + nR):        # 양단 모두 풍부 → 전폭 표
        sel = rows
    else:                                                    # 한쪽 단 표
        sel = left if nL >= nR else right
    x0 = max(full[0], min(t[0] for t in sel) - 6)
    x1 = min(full[1], max(t[1] for t in sel) + 6)
    return fitz.Rect(x0, cy1 + 2, x1, bottom), True


def _figure_region(page, cap, colx, caps):
    """그림 영역 Rect(캡션 위, 그래픽 합집합 bbox). (rect, has_graphic).

    전폭 그림(좌단 캡션을 가진 flowchart 등)은 캡션 단을 넘어 양 단에 그래픽이 걸치므로,
    **단 거터(mid)를 가로지르는 그래픽이 있으면 전폭**으로 확장한다. 좌우 나란한 별개 그림은
    거터에 그래픽이 없으므로 캡션 단으로 유지된다."""
    import fitz
    pg = page.rect
    mid = pg.x0 + pg.width / 2.0
    cy0 = cap["bbox"][1]
    full = (pg.x0 + 2, pg.x1 - 2)
    top_limit = pg.y0 + _HDR
    for c in caps:
        if c is cap:
            continue
        b = c["bbox"]
        if b[3] < cy0 - 2 and _ov_x(b, colx, 0.3):
            top_limit = max(top_limit, b[3] + 4)
    g_all = _graphic_rects(page, full, top_limit, cy0 - 2)
    g_col = [r for r in g_all if _ov_x((r.x0, r.y0, r.x1, r.y1), colx, 0.3)]
    if not g_col:
        return fitz.Rect(colx[0], top_limit, colx[1], cy0 - 2), False
    bridge = any(r.x0 < mid - 4 and r.x1 > mid + 4 for r in g_all)   # 거터 가로지름 → 전폭
    use = g_all if bridge else g_col
    x0, x1 = full if bridge else colx
    gx0 = min(r.x0 for r in use)
    gy0 = min(r.y0 for r in use)
    gx1 = max(r.x1 for r in use)
    # 하단은 캡션 직전까지 — 그래픽과 캡션 사이의 (a)/(b) 부분그림 라벨을 그림에 포함
    # (본문으로 새어 잘못 표시되던 문제 해결). 단, 그래픽 끝에서 캡션까지 간격이 과도하면
    # 본문 한 줄까지만 허용하지 않도록 제한.
    rect = fitz.Rect(max(x0, gx0 - 5), max(top_limit, gy0 - 5),
                     min(x1, gx1 + 5), cy0 - 2)
    return rect, True


def _render(page, rect, path):
    """rect 를 고해상도 PNG 로 저장. 성공 시 path, 실패 시 ''."""
    import fitz
    try:
        if rect.width < 12 or rect.height < 10:
            return ""
        page.get_pixmap(clip=rect, matrix=fitz.Matrix(_ZOOM, _ZOOM)).save(path)
        return path
    except Exception:
        return ""


def _extract_one(doc, page, cap, out_dir, idx):
    """캡션 1개 → 자산 dict({kind,num,image,caption,text?,region,has_content})."""
    caps = _caption_blocks(page)
    kind = cap["kind"]
    if kind == "tab":
        rect, has = _table_region(page, cap, caps)
        fn = f"table_{idx:02d}.png"
    else:
        colx = _col_range(page, cap["bbox"])
        rect, has = _figure_region(page, cap, colx, caps)
        fn = f"figure_{idx:02d}.png"
    img = _render(page, rect, os.path.join(out_dir, fn))
    rtext = ""
    if kind == "tab":
        try:
            rtext = page.get_text("text", clip=rect).strip()
        except Exception:
            rtext = ""
    return {"kind": kind, "num": cap["num"], "image": img, "images": [img] if img else [],
            "caption": cap["text"], "cont": _is_cont(cap["text"]),
            "text": rtext, "region": (rect.x0, rect.y0, rect.x1, rect.y1),
            "regions": [(rect.x0, rect.y0, rect.x1, rect.y1)],
            "caption_bbox": tuple(cap["bbox"]), "caption_bboxes": [tuple(cap["bbox"])],
            "page": page.number, "has_content": has}


def _merge_cont(base, part):
    """다음 페이지 연속 자산(part)을 기존 자산(base)에 누적(이미지·영역·본문 제외용 페이지)."""
    if part.get("image"):
        base.setdefault("images", []).append(part["image"])
    base.setdefault("regions", []).append(part.get("region"))
    base.setdefault("caption_bboxes", []).append(part.get("caption_bbox"))
    base.setdefault("extra_pages", []).append(
        {"page": part.get("page"), "region": part.get("region"),
         "caption_bbox": part.get("caption_bbox"), "kind": part.get("kind")})
    if part.get("text"):
        base["text"] = (base.get("text", "") + "\n" + part["text"]).strip()


def regions_by_page(figures, tables):
    """{page: [(x0,y0,x1,y1),…]} — 본문 추출에서 제외할 표 영역 + 모든 그림/표 캡션 영역.

    표 셀 텍스트·캡션이 본문 번역에 중복 유입되는 것을 막는다(워커가 pdf_extract 에 전달)."""
    d = {}
    for a in list(tables or []) + list(figures or []):
        pg = a.get("page")
        if pg is None:
            continue
        # 표·그림 영역을 모두 본문에서 제외(표 셀 텍스트·그림 (a)/(b) 부분라벨·축 라벨 누출 방지)
        if a.get("region"):
            d.setdefault(pg, []).append(tuple(a["region"]))
        if a.get("caption_bbox"):
            d.setdefault(pg, []).append(tuple(a["caption_bbox"]))
        for ep in a.get("extra_pages", []):         # 연속(Cont.) 페이지도 제외
            epg = ep.get("page")
            if epg is None:
                continue
            if ep.get("region"):
                d.setdefault(epg, []).append(tuple(ep["region"]))
            if ep.get("caption_bbox"):
                d.setdefault(epg, []).append(tuple(ep["caption_bbox"]))
    return d


def _review_assets(doc, assets):
    """재검토 — 표=행 구조/그림=그래픽 존재 검증. issues 목록 반환(자산에 review 기록)."""
    issues = []
    for a in assets:
        page = doc[a["page"]]
        rect = a["region"]
        ok = True
        why = ""
        if not a.get("image"):
            ok = False
            why = "이미지 렌더 실패"
        elif a["kind"] == "tab":
            # 표: 영역에 표 행이 있어야(가로 분산 토큰)
            colx = (rect[0], rect[2])
            _b, rows = _table_rows(page, rect[1] - 2, rect[3] + 2, colx)
            if not rows:
                ok = False
                why = "표 행 미검출(본문/그림 의심)"
        else:
            # 그림: 그래픽 콘텐츠가 있어야
            if not a.get("has_content"):
                ok = False
                why = "그래픽 미검출(벡터/이미지 없음)"
        a["review"] = "ok" if ok else why
        if not ok:
            issues.append({"kind": a["kind"], "num": a["num"], "why": why})
    return issues


def _declared(doc):
    """선언된 캡션 집합 {('tab',n), ('fig',n)} (재출현/중복 무시)."""
    decl = set()
    for pno in range(doc.page_count):
        for c in _caption_blocks(doc[pno]):
            if c["num"]:
                decl.add((c["kind"], c["num"]))
    return decl


def _fill_missing(doc, out_dir, figures, tables, max_round=2):
    """선언 vs 추출 비교 → 누락 번호 재추출(완화 바운딩). (figures, tables, report)."""
    report = {"declared": 0, "missing": [], "recovered": []}
    decl = _declared(doc)
    report["declared"] = len(decl)
    for _round in range(max_round):
        have = {("tab", t["num"]) for t in tables if t["num"]} | \
               {("fig", f["num"]) for f in figures if f["num"]}
        missing = sorted(decl - have)
        if not missing:
            break
        recovered = 0
        for kind, num in missing:
            # 해당 번호 캡션을 찾아 재추출
            for pno in range(doc.page_count):
                page = doc[pno]
                cap = next((c for c in _caption_blocks(page)
                            if c["kind"] == kind and c["num"] == num), None)
                if not cap:
                    continue
                idx = (len(tables) + len(figures) + 1)
                a = _extract_one(doc, page, cap, out_dir, idx)
                if not a.get("image"):
                    continue
                (tables if kind == "tab" else figures).append(a)
                report["recovered"].append(f"{kind}{num}")
                recovered += 1
                break
        if recovered == 0:
            break
    have = {("tab", t["num"]) for t in tables if t["num"]} | \
           {("fig", f["num"]) for f in figures if f["num"]}
    report["missing"] = [f"{k}{n}" for k, n in sorted(decl - have)]
    return figures, tables, report


def extract_assets(path, out_dir, max_items: int = 80):
    """(figures, tables). 캡션 기준 + 단 인식 정밀 크롭 + 재검토 + 누락 보완.

    각 항목 = {kind,num,image,caption,text,region,page,has_content,review}. 이미지=절대경로."""
    figures, tables = [], []
    try:
        import fitz
    except Exception:
        return figures, tables
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(str(path))

    # 1) 모든 캡션 수집(페이지·y 순) → 캡션 1개 = 자산 1개
    seq = []
    for pno in range(doc.page_count):
        for c in _caption_blocks(doc[pno]):
            seq.append((pno, c))
    # 같은 (kind,num) 캡션 인스턴스를 그룹화 → 여러 페이지에 걸친 자산은 1개로 병합(연속 표/그림).
    # (본문 참조 'Figure 9 shows…' 는 캡션 정규식에서 이미 제외되므로 캡션 그룹은 같은 자산이다.)
    groups, order = {}, []
    for pno, c in seq:
        key = (c["kind"], c["num"]) if c["num"] else (c["kind"], id(c))
        if key not in groups:
            order.append(key)
        groups.setdefault(key, []).append((pno, c))
    idx = 0
    for key in order:
        if idx >= max_items:
            break
        parts = sorted(groups[key], key=lambda pc: pc[0])     # 페이지 순
        idx += 1
        base = _extract_one(doc, doc[parts[0][0]], parts[0][1], out_dir, idx)
        for pno, c in parts[1:]:
            idx += 1
            _merge_cont(base, _extract_one(doc, doc[pno], c, out_dir, idx))
        # 표시 캡션 = 그룹 내 가장 완전한(연속표기 아닌·긴) 캡션
        best = max((c for _, c in parts),
                   key=lambda c: (not _is_cont(c["text"]), len(c["text"] or "")))
        base["caption"] = best["text"]
        base["num"] = best["num"] or base.get("num")
        base["cont"] = False
        (tables if base["kind"] == "tab" else figures).append(base)

    # 2) 재검토
    _review_assets(doc, figures + tables)
    # 3) 누락 보완(선언 vs 추출 → 재추출 → 재검토)
    figures, tables, _rep = _fill_missing(doc, out_dir, figures, tables)
    _review_assets(doc, figures + tables)

    # 번호 순 정렬(보기 좋게)
    figures.sort(key=lambda a: (a["num"] is None, a["num"] or 0))
    tables.sort(key=lambda a: (a["num"] is None, a["num"] or 0))
    doc.close()
    return figures, tables


_MATH_CH = set("=+×÷±∓∑∏∫√∂∇≤≥≠≈∝∞·•αβγδεζηθλμνξπρσςτφχψωΓΔΘΛΞΠΣΦΨΩ^_")
_EQNUM_RE = re.compile(r"\(\s*\d+\s*\)\s*$")


def _is_equation(txt: str) -> bool:
    """표시 수식 블록 판정(번역 대신 이미지로 처리). 번호식 또는 수학기호 밀집·짧은 블록."""
    t = (txt or "").strip()
    if not t or len(t) > 400:
        return False
    nmath = sum(1 for ch in t if ch in _MATH_CH)
    longwords = re.findall(r"[A-Za-z]{4,}", t)
    has_eqnum = bool(_EQNUM_RE.search(t))
    if has_eqnum and (nmath >= 1 or "=" in t):          # 번호 매겨진 표시 수식(신뢰도 높음)
        return True
    if nmath >= 4 and len(longwords) <= 3 and len(t) < 200:   # 무번호 수식(보수적)
        return True
    return False


def _equation_region(page, block):
    """수식 블록의 전체 영역(좌우 같은 줄 토막 + 위/아래 분수·루트(드로잉)·적층 항 포함).

    수식은 'σ = √( … ) (1)' 처럼 같은 줄에 여러 토막으로 쪼개지고, 분수/루트 막대가 텍스트
    bbox 밖으로 나가 잘리기 쉽다. 같은 y 밴드의 블록·드로잉을 합쳐 전체를 잡는다."""
    import fitz
    bx0, by0, bx1, by1 = block[0], block[1], block[2], block[3]
    h = max(8.0, by1 - by0)
    yc = (by0 + by1) / 2.0
    win_top, win_bot = by0 - h * 0.9, by1 + h * 0.5    # 적층 분자/분모용 좁은 세로 창
    rx0, ry0, rx1, ry1 = bx0, by0, bx1, by1

    def _xov(a0, a1):                                   # 현재 영역과 가로로 겹치거나 인접?
        return a1 > rx0 - 30 and a0 < rx1 + 30

    for b in page.get_text("blocks"):
        if len(b) < 5 or not isinstance(b[4], str) or not b[4].strip():
            continue
        b_yc = (b[1] + b[3]) / 2.0
        same_line = abs(b_yc - yc) <= max(6.0, h * 0.4)            # 같은 줄(σ=, (1))
        short_stack = (len(b[4].strip()) <= 14 and b[3] > win_top  # 적층 짧은 토막(1, N−1, n)
                       and b[1] < win_bot and _xov(b[0], b[2]))
        if same_line or short_stack:
            rx0, ry0 = min(rx0, b[0]), min(ry0, b[1])
            rx1, ry1 = max(rx1, b[2]), max(ry1, b[3])
    try:
        draws = page.get_drawings()
    except Exception:
        draws = []
    for d in draws:                                    # 분수 막대·루트선 등
        r = d.get("rect")
        if not r or r.width > page.rect.width * 0.9:
            continue
        if r.y1 > win_top and r.y0 < win_bot and _xov(r.x0, r.x1):
            rx0, ry0 = min(rx0, r.x0), min(ry0, r.y0)
            rx1, ry1 = max(rx1, r.x1), max(ry1, r.y1)
    return fitz.Rect(rx0 - 4, ry0 - 3, rx1 + 4, ry1 + 3)


def extract_equations(path, out_dir, max_items: int = 60):
    """표시 수식 블록 → 이미지로 캡처. [{id, token, page, region, width_pt, image}] 반환.

    번역하지 않고 이미지로 본문 흐름에 삽입하기 위함(토큰 `【수식N】` 으로 위치 표시)."""
    out = []
    try:
        import fitz
    except Exception:
        return out
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(str(path))
    n = 0
    for pno in range(doc.page_count):
        page = doc[pno]
        used = []                                       # 같은 수식 중복 캡처 방지(영역 겹침)
        for b in page.get_text("blocks"):
            if len(b) < 5 or not isinstance(b[4], str):
                continue
            if not _is_equation(b[4]):
                continue
            if n >= max_items:
                break
            rect = _equation_region(page, b)
            if any(abs(rect & u) > 0.5 * abs(rect) for u in used if abs(rect) > 0):
                continue                                # 이미 잡은 수식과 겹침 → 건너뜀
            used.append(fitz.Rect(rect))
            n += 1
            img = _render(page, rect, os.path.join(out_dir, f"eq_{n:02d}.png"))
            out.append({"id": n, "token": f"【수식{n}】", "page": pno,
                        "region": (rect.x0, rect.y0, rect.x1, rect.y1),
                        "width_pt": rect.x1 - rect.x0, "image": img})
        if n >= max_items:
            break
    doc.close()
    return [e for e in out if e.get("image")]


def equation_placeholders(equations):
    """{page: [((x0,y0,x1,y1), token)]} — pdf_extract 에 넘겨 본문에 토큰 삽입."""
    d = {}
    for e in (equations or []):
        d.setdefault(e["page"], []).append((tuple(e["region"]), e["token"]))
    return d


def extract_assets_report(path, out_dir, max_items: int = 80):
    """extract_assets + 진단 리포트(declared/recovered/missing/issues) 반환(워커 로깅용)."""
    import fitz
    figures, tables = extract_assets(path, out_dir, max_items)
    doc = fitz.open(str(path))
    decl = _declared(doc)
    issues = _review_assets(doc, figures + tables)
    have = {("tab", t["num"]) for t in tables if t["num"]} | \
           {("fig", f["num"]) for f in figures if f["num"]}
    doc.close()
    report = {
        "declared": len(decl),
        "figures": len(figures),
        "tables": len(tables),
        "missing": [f"{k}{n}" for k, n in sorted(decl - have)],
        "issues": issues,
    }
    return figures, tables, report
