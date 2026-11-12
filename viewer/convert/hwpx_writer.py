# -*- coding: utf-8 -*-
"""한글 HWPX 쓰기 (형식 변환 SOT §1, 261014-14) — python-hwpx(Apache-2.0, 고정 판 의존성 §4.2).

- 편집 가능(261113-3): 모양 그대로 배치 쓰기 + 텍스트 창이 이은 문장 줄만 한 문단으로(줄을 꺾는다, 쪽 맞춤 §1.2).
- 모양 그대로(배치 쓰기): 쪽마다 구역 하나(쪽 크기 = PDF 쪽, 여백 0). 원본 줄마다 문단 — 왼쪽 여백·위 간격·글자 크기·굵기·
  자간을 원본에 맞춘다. 그림·표는 쪽에 띄워 원본 자리에(글의 흐름을 밀지 않는다).
단위는 HWPUNIT(1 pt = 100).
"""
from __future__ import annotations

from pathlib import Path

from viewer.convert import layout
from viewer.convert import page_step, step_text  # 진행 창 글(형식 변환 SOT §5, 261026-2)

HWPUNIT_PER_PT = 100
LINE_PCT = 100             # 모양 그대로의 줄 간격(%) — 줄 높이 = 글자 크기 × LINE_PCT / 100
SPACING_MIN, SPACING_MAX = -50, 50      # 한글 자간 범위(%)
HWP_WIDTH_K = 1.055        # 한글이 그리는 너비 ÷ 같은 글꼴 파일로 잰 너비(실측 261014-15: 바탕 영문 1.060·한글 1.047, 맑은 고딕 1.057·1.042)
ANCHOR_PT = 1.0            # 띄운 그림·표를 붙든 문단(쪽의 첫 문단)의 글자 크기 — 줄 높이를 거의 차지하지 않게


def _u(pt: float) -> int:
    return max(1, int(round(pt * HWPUNIT_PER_PT)))


def _u0(pt: float) -> int:
    return max(0, int(round(pt * HWPUNIT_PER_PT)))


def _pic(doc, val, sec=None, **kw):
    """그림 블록 → python-hwpx 그림. jpg·png 가 아니면 PNG 로."""
    data, fmt = val["data"], val["fmt"]
    if fmt not in ("png", "jpg"):
        data, fmt = _to_png(data), "png"
        if data is None:
            return None
    x0, y0, x1, y1 = val["rect"]
    return data, fmt, (x1 - x0), (y1 - y0)


def _to_png(data: bytes):
    """jpg·png 가 아닌 그림(jpx·jbig2 …)은 PNG 로 — 한글이 받는 형식으로."""
    try:
        import fitz
        return fitz.Pixmap(data).tobytes("png")
    except Exception:
        return None


def _sync_manifest(doc) -> int:
    """저장 직전 — 패키지 manifest 의 그림 항목(`BinData/`)을 문서 개체의 manifest 에 채운다(형식 변환 SOT §4.2, 261112-17).

    python-hwpx 6.6.0 은 구역을 더한 문서를 저장할 때 문서 개체가 처음 잡은 manifest 로 `content.hpf` 를 덮어쓴다 —
    그 사이 패키지가 새로 읽은 manifest 에만 적힌 그림(첫 그림 뒤 모두)이 빠지고, 한글은 등록 안 된 그림을 빼고 연다.
    더한 항목 수."""
    try:
        root = doc._root
        mine = root._manifest
        ns = "http://www.idpf.org/2007/opf/"
        man_el = mine.find(f"{{{ns}}}manifest")
        if man_el is None:
            return 0
        have = {e.get("id") for e in man_el.findall(f"{{{ns}}}item")}
        added = 0
        for it in doc._package._manifest_items():
            iid, href = str(it.get("id", "")).strip(), str(it.get("href", "")).strip()
            if not iid or iid in have or not href.startswith("BinData/"):
                continue
            man_el.append(man_el.makeelement(f"{{{ns}}}item", {k: str(v) for k, v in it.items()}))
            have.add(iid)
            added += 1
        if added:
            root._manifest_dirty = True
        return added
    except Exception:                                  # 라이브러리 내부가 바뀌면 — 아래 저장은 그대로(검사가 잡는다)
        return 0


def _fill_table(t, rows) -> None:
    for ri, r in enumerate(rows):
        for ci, c in enumerate(r):
            if c:
                t.set_cell_text(ri, ci, str(c))


# ---- 편집 가능 = 모양 그대로 + 이은 문단(형식 변환 SOT §1, 261113-3) --------------------------------
def write_hwpx_edit(ps, pages, dst: Path, tick) -> None:
    """모양 그대로 배치 쓰기에서 텍스트 창이 이은 문장 줄만 한 문단으로(줄을 꺾는다). 쪽·그림·표·머리말은 모양 그대로와 같다."""
    write_hwpx_shape(ps, pages, dst, tick, join=True)


def _hf_content_at(lines, left: float, right: float) -> list:
    """모양 그대로 — 그 쪽의 머리말·꼬리말 글 그대로(쪽 번호도 원본 글), 맞춤은 그 쪽 글 영역 기준."""
    out = []
    for ln in lines:
        text, align, _ind = layout.compose(ln, float(ln.get("pw") or right), left, right, spaces=True)
        face = layout.SERIF_FACE if ln["serif"] else layout.SANS_FACE
        if text.strip():
            out.append({"align": align, "children": [{"type": "run", "text": text, "size": round(ln["size"] * 2) / 2,
                                                       "bold": bool(ln["bold"]), "font": face}]})
    return out


_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _page_num_ctrl(paragraph, pos: str, side: str, char_pr="0") -> None:
    """한글 '쪽 번호 매기기'(`hp:pageNum`)를 문단에 넣는다 — 그 쪽부터 뒤 쪽까지 `pos` 자리에 번호를 그린다(§1.1)."""
    p = paragraph.element if hasattr(paragraph, "element") else paragraph
    run = p.makeelement(_HP + "run", {"charPrIDRef": str(char_pr)})   # 번호 글자 모양 = 원본 번호 줄
    ctrl = run.makeelement(_HP + "ctrl", {})
    ctrl.append(ctrl.makeelement(_HP + "pageNum", {"pos": pos, "formatType": "DIGIT", "sideChar": side}))
    run.append(ctrl)
    p.append(run)


# ---- 모양 그대로(배치 쓰기) ---------------------------------------------------
class _Styles:
    """문단·글자 속성 id 를 만들고 되쓴다(같은 값이면 같은 id)."""

    def __init__(self, doc):
        self.doc = doc
        self.hdr = doc.parts.headers[0]
        # 바탕 문단 속성: 왼쪽 맞춤, 줄 간격 LINE_PCT, 격자 맞춤 끔, 줄 나눔 없음(넘치면 자간을 줄여 한 줄 — SQUEEZE).
        # next=1 은 기본 서식과 똑같아져 그것을 고쳐 버리지 않게 하는 표시(0.01 pt)
        self.base = self.hdr.ensure_paragraph_format(
            alignment="LEFT", line_spacing_percent=LINE_PCT,
            margins={"intent": 0, "left": 0, "right": 0, "prev": 0, "next": 1})
        el = self._para_el(self.base)
        if el is not None:
            el.set("snapToGrid", "0")
            for e in el.iter():
                if e.tag.endswith("}breakSetting"):
                    e.set("lineWrap", "SQUEEZE")
                    e.set("widowOrphan", "0")
        self._base_el = el
        self._parent = self.hdr._para_properties_element(create=True)
        self._next = 1 + max((int(e.get("id")) for e in self._parent if str(e.get("id", "")).isdigit()), default=0)
        self._seen = len(self._parent)
        self._para = {}
        self._run = {}

    def _para_el(self, pid):
        for e in self.hdr.element.iter():
            if e.tag.endswith("}paraPr") and e.get("id") == str(pid):
                return e
        return None

    def cell_para(self) -> str:
        """표 칸 문단 — 줄 간격은 본문과 같고(`LINE_PCT`), 칸 너비에서 **줄을 꺾는다**(본문의 SQUEEZE 와 다르다, 261014-30)."""
        return self.para(0, 0, wrap=True)

    def para(self, left_pt: float, prev_pt: float, wrap: bool = False, *, right_pt: float = 0.0, intent_pt: float = 0.0,
             line_pct: int = LINE_PCT) -> str:
        """문단 서식 id. 이은 문단(편집 가능, 261113-3)은 `wrap`·오른쪽 여백·첫 줄 들여쓰기(음수 = 내어쓰기)·줄 간격(%)도."""
        key = (_u0(left_pt) // 50 * 50, _u0(prev_pt) // 10 * 10, bool(wrap),
               _u0(right_pt) // 50 * 50, int(round(intent_pt * HWPUNIT_PER_PT)) // 50 * 50, int(line_pct))
        if key not in self._para:
            # 바탕을 복제해 직접 붙인다 — python-hwpx 의 `ensure_paragraph_format` 은 만들 때마다 있는 것 전부와
            # 구조를 비교해(같은 것 되쓰기) 줄이 많은 문서에서 O(n²)이다(실측 10쪽 4.3초). 같은 값은 위 사전이 되쓴다.
            from copy import deepcopy
            el = deepcopy(self._base_el)
            self.hdr._apply_paragraph_margins(el, {"left": key[0], "prev": key[1], "right": key[3], "intent": key[4]})
            if key[5] != LINE_PCT:
                for e in el.iter():
                    if e.tag.endswith("}lineSpacing"):
                        e.set("value", str(key[5]))
            if wrap:
                for e in el.iter():
                    if e.tag.endswith("}breakSetting"):
                        e.set("lineWrap", "BREAK")
            # 번호는 그때마다 '지금 가장 큰 번호 + 1' — 사이에 python-hwpx 가 머리말·꼬리말 문단 서식을 더하면
            # 미리 잡아 둔 번호와 겹친다(261014-15 한글 대조: 본문 줄이 머리말 서식(오른쪽·160%)을 받았다)
            if len(self._parent) != self._seen:
                self._next = max(self._next, 1 + max((int(e.get("id")) for e in self._parent
                                                      if str(e.get("id", "")).isdigit()), default=0))
            pid = str(self._next)
            self._next += 1
            self._seen = len(self._parent) + 1
            el.set("id", pid)
            self._parent.append(el)
            self._para[key] = pid
        return self._para[key]

    def finish(self) -> None:
        self.hdr._update_item_count(self._parent, self._base_el.tag)
        self.hdr.mark_dirty()

    def run(self, size: float, spacing: int, bold: bool, serif: bool) -> str:
        key = (round(size * 2) / 2, int(spacing), bool(bold), bool(serif))
        if key not in self._run:
            self._run[key] = self.doc.styles.ensure_run(
                size=key[0], letter_spacing=key[1], bold=key[2],
                font=layout.SERIF_FACE if key[3] else layout.SANS_FACE)
        return self._run[key]


def _edge_zone_lines(blocks, heads, foots, pw, ph) -> list:
    """머리말·꼬리말 자리 안에 남은 본문 줄을 그 머리말·꼬리말로 옮긴다(같은 높이면 같은 줄의 조각으로).
    261014-30 표본 시험: 꼬리말의 쪽 번호(`i`)만 꼬리말로 잡히고 같은 줄의 문서 이름은 본문으로 남아, 본문 영역 아래라 한글이
    새 쪽으로 넘겼다(10쪽 → 11쪽). 머리말·꼬리말을 찾는 규칙은 텍스트 창 SOT §3.5.2 그대로 두고, 쪽 배치에서만 받는다."""
    zones = []
    if heads:
        zones.append((heads, "head", -1e9, max(e["rect"][3] for e in heads) + 1))
    if foots:
        zones.append((foots, "foot", min(e["rect"][1] for e in foots) - 1, 1e9))
    if not zones:
        return blocks
    keep = []
    for b in blocks:
        r = b.get("rect")
        moved = False
        if b["kind"] == "line" and r:
            for group, where, lo, hi in zones:
                if (where == "foot" and r[1] >= lo) or (where == "head" and r[3] <= hi):
                    piece = (r[0], r[2], b["text"])
                    mate = next((e for e in group if min(e["rect"][3], r[3]) - max(e["rect"][1], r[1]) > 0), None)
                    if mate is not None:
                        mate["pieces"] = sorted(list(mate["pieces"]) + [piece], key=lambda q: q[0])
                        er = mate["rect"]
                        mate["rect"] = (min(er[0], r[0]), min(er[1], r[1]), max(er[2], r[2]), max(er[3], r[3]))
                    else:
                        group.append({"where": where, "rect": tuple(r), "pieces": [piece], "text": b["text"],
                                      "size": b["size"], "bold": b["bold"], "serif": b["serif"], "pw": pw, "ph": ph})
                    moved = True
                    break
        if not moved:
            keep.append(b)
    return keep


BODY_SAFETY_PT = 2.0       # 본문 영역 아래 끝에서 남기는 여유(pt)
CELL_PAD_PT = 1.0         # 모양 그대로 표 칸 안 여백(좌우) — 기본(1.8 mm)이면 칸이 넓어지고 줄이 더 꺾여 표가 길어졌다


def _shape_cells(t, char_pr, para_pr=None) -> None:
    """모양 그대로 표 — 칸 글을 원본 크기로, 줄 간격을 본문과 같게(`LINE_PCT`, 기본 문단 서식은 160%), 칸 여백을 작게
    (261014-30 표본 시험: 큰 표가 원본보다 길어져 쪽을 넘었다)."""
    pad = _u0(CELL_PAD_PT)
    seen = set()
    for ri in range(t.row_count):
        for ci in range(t.column_count):
            try:
                cell = t.cell(ri, ci)
            except Exception:
                continue
            if cell.element in seen:                       # 합친 칸은 한 번만(요소 자체로 — lxml 프록시의 id 는 다시 쓰일 수 있다)
                continue
            seen.add(cell.element)
            try:
                cell.set_margins(left=pad, right=pad, top=0, bottom=0)
            except Exception:
                pass
            for p in cell.paragraphs:
                if para_pr is not None:
                    p.element.set("paraPrIDRef", str(para_pr))
                for r in p.element:
                    if r.tag.endswith("}run"):
                        r.set("charPrIDRef", str(char_pr))


def _float(el, x_pt: float, y_pt: float) -> None:
    """그림·표를 쪽(종이) 기준 자리에 띄운다 — 글 앞으로, 글의 흐름을 밀지 않는다."""
    el.set("textWrap", "IN_FRONT_OF_TEXT")
    for e in el:
        if e.tag.endswith("}pos"):
            e.set("treatAsChar", "0")
            e.set("affectLSpacing", "0")
            e.set("flowWithText", "0")
            e.set("allowOverlap", "1")
            e.set("vertRelTo", "PAPER")
            e.set("horzRelTo", "PAPER")
            e.set("vertAlign", "TOP")
            e.set("horzAlign", "LEFT")
            e.set("vertOffset", str(_u0(y_pt)))
            e.set("horzOffset", str(_u0(x_pt)))
            break


def _spacing(text: str, width: float, size: float, serif: bool) -> int:
    """원본 줄 너비에 맞춘 자간(%). 한글의 자간은 **그 줄 제 너비의 %** 로 든다(자간 −10 → 너비 0.90배, 영문·한글 같음)
    — (원본 너비 ÷ 한글이 그릴 너비 − 1) × 100. 한글이 그릴 너비 = 그 글꼴로 잰 너비 × `HWP_WIDTH_K`. 못 재면 0."""
    m = layout.measure(text, size, serif)
    if m is None or len(text) < 2 or width <= 0 or m <= 0:
        return 0
    sp = (width / (m * HWP_WIDTH_K) - 1.0) * 100.0
    return int(max(SPACING_MIN, min(SPACING_MAX, round(sp))))


def _joined_para(text, grp, size_pt, serif):
    """이은 문단 하나의 자리·크기 계획(형식 변환 SOT §1 'HWPX 편집 가능'·§1.2 쪽 맞춤, 261113-3).
    반환 (왼쪽 x, 첫 줄 들여쓰기, 오른쪽 끝 x, 첫 줄 가운데 y, 계획)."""
    first, rest = grp[0]["rect"], [b["rect"] for b in grp[1:]]
    rest_x = min(r[0] for r in rest)
    x0 = min(first[0], rest_x)
    intent = first[0] - rest_x                    # 양수 = 들여쓰기, 음수 = 내어쓰기(첫 줄이 왼쪽)
    x1 = max(b["rect"][2] for b in grp)
    cys = [(b["rect"][1] + b["rect"][3]) / 2 for b in grp]
    gaps = sorted(b - a for a, b in zip(cys, cys[1:]) if b > a)
    pitch = gaps[len(gaps) // 2] if gaps else size_pt * 1.2
    m = layout.measure_fit(text, size_pt, serif)
    width = (m * HWP_WIDTH_K) if m else 0.0
    plan = layout.fit_plan(width, len(grp), max(1.0, x1 - x0), size_pt, pitch, indent=intent)
    return x0, intent, x1, cys[0], plan


def write_hwpx_shape(ps, pages, dst: Path, tick, join: bool = False) -> None:
    from hwpx import HwpxDocument
    doc = HwpxDocument.new()
    st = _Styles(doc)
    anchor_para = st.para(0, 0)
    anchor_run = st.run(ANCHOR_PT, 0, False, True)
    for i, pg in enumerate(pages):
        tick(i, len(pages), page_step(ps, pages, i))
        page = ps.doc.load_page(int(pg))
        w, h = page.rect.width, page.rect.height
        sec = doc.sections[0] if i == 0 else doc.add_section()
        doc.page.set_size(width=_u(w), height=_u(h), section=sec)
        edges = []
        blocks = layout.page_blocks(ps, pg, join=False, edges=edges)
        # 쪽 여백 = 원본 글 영역(§1.1). 머리말·꼬리말이 있으면 그 자리가 머리말·꼬리말 영역이다
        xs = [b["rect"] for b in blocks if b["kind"] == "line" and b.get("rect")] + [e["rect"] for e in edges]
        left = max(0.0, min((r[0] for r in xs), default=0.0) - 1)
        right = max(0.0, w - max((r[2] for r in xs), default=w) - 1)
        heads = [e for e in edges if e["where"] == "head"]
        foots = [e for e in edges if e["where"] == "foot"]
        blocks = _edge_zone_lines(blocks, heads, foots, w, h)
        top = max(0.0, min((e["rect"][1] for e in heads), default=0.0) - 1)
        hlen = (max(e["rect"][3] for e in heads) - top + 1) if heads else 0.0
        bottom = max(0.0, h - max((e["rect"][3] for e in foots), default=h) - 1)
        flen = (max(e["rect"][3] for e in foots) - min(e["rect"][1] for e in foots) + 2) if foots else 0.0
        doc.page.set_margins(left=_u0(left), right=_u0(right), top=_u0(top), bottom=_u0(bottom),
                             header=_u0(hlen), footer=_u0(flen), gutter=0, section=sec)
        body_bottom = h - bottom - flen - BODY_SAFETY_PT      # 본문 영역 아래 끝 — 넘는 줄은 한글이 새 쪽으로 보낸다
        for kind, lines in (("head", heads), ("foot", foots)):
            # 쪽 번호뿐인 줄 → 한글 '쪽 번호 매기기' + 그 쪽 번호로 새 번호(§1.1). 나머지는 그 쪽 글 그대로
            nums = [ln for ln in lines if len(ln["pieces"]) == 1 and layout.number_only(ln["pieces"][0][2]) is not None]
            if nums:
                ln = nums[0]
                _t, align, _i = layout.compose(ln, w, left, w - right)
                side = layout.number_only(ln["pieces"][0][2])
                import re as _re
                n = int(_re.search(r"\d+", ln["pieces"][0][2]).group(0))
                head_p = sec.paragraphs[0]
                try:
                    doc.page.restart_page_number(head_p, number=n)
                except Exception:
                    pass
                # 런 글자 모양은 아래에서 붙든 문단과 같이 아주 작게 — 번호는 한글이 '쪽 번호 매기기' 모양으로 그린다
                #   (번호 크기로 두면 그 문단 줄 높이가 커져 본문이 10 pt 밀렸다 — 261014-15 한글 대조)
                _page_num_ctrl(head_p, ("TOP_" if kind == "head" else "BOTTOM_") + align, side)
                lines = [x for x in lines if x not in nums]
            content = _hf_content_at(lines, left, w - right)
            if content:
                (doc.page.set_header if kind == "head" else doc.page.set_footer)(content=content, section=sec)
        # 구역의 첫 문단(구역 설정을 든 것)이 그림·표를 붙든다 — 글자를 아주 작게 해 줄 높이를 거의 차지하지 않게
        head = sec.paragraphs[0]
        head.element.set("paraPrIDRef", str(anchor_para))
        for r in head.element:
            if r.tag.endswith("}run"):
                r.set("charPrIDRef", str(anchor_run))
        cur = top + hlen + ANCHOR_PT * LINE_PCT / 100.0       # 본문은 위 여백 + 머리말 아래에서 시작한다
        for b in blocks:
            if b["kind"] == "image":
                got = _pic(doc, b)
                if got is None:
                    continue
                data, fmt, bw, bh = got
                from hwpx._document.media import add_image      # 그림 바이트를 문서에 넣는 python-hwpx 6.6 의 기본 함수
                bid = str(add_image(doc, data, fmt))
                obj = head.add_picture(bid, width=_u(bw), height=_u(bh), treat_as_char=False,
                                       text_wrap="IN_FRONT_OF_TEXT", char_pr_id_ref=anchor_run)
                _float(obj.element, b["rect"][0], b["rect"][1])
            elif b["kind"] == "table":
                rows = b["rows"]
                x0, y0, x1, y1 = b["rect"]
                t = head.add_table(len(rows), max(len(r) for r in rows), width=_u(x1 - x0), height=_u(y1 - y0),
                                   char_pr_id_ref=anchor_run)
                _fill_table(t, rows)
                if b.get("cols") and len(b["cols"]) == t.column_count:
                    try:
                        t.set_column_widths([_u(c) for c in b["cols"]])      # 원본 열 너비(261014-30)
                    except Exception:
                        pass
                if b.get("heights") and len(b["heights"]) == t.row_count:   # 원본 행 높이(261014-30) — 한글이 내용만큼 늘린다
                    for ri, rh in enumerate(b["heights"]):
                        for ci in range(t.column_count):
                            try:
                                t.cell(ri, ci).set_size(height=_u(rh))
                            except Exception:
                                pass
                for ri, c0, c1 in layout.h_spans(rows):             # 합친 칸(261014-30)
                    try:
                        t.merge_cells(ri, c0, ri, c1)
                    except Exception:
                        pass
                _shape_cells(t, st.run(float(b.get("size") or layout.TABLE_PT_DEFAULT), 0, False, True), st.cell_para())
                _float(t.element, x0, y0)
        line_blocks = [b for b in blocks if b["kind"] == "line"]
        all_bands = layout.bands(line_blocks)
        first_of, skip = {}, set()
        if join:                     # 편집 가능 — 텍스트 창이 이은 줄 묶음 중 줄마다 홀로 선 것(옆 단과 나란하지 않은 것)만
            band_of = {id(q): k for k, bd in enumerate(all_bands) for q in bd}
            for jtext, grp in layout.join_groups(ps, pg, line_blocks):
                ks = sorted(band_of.get(id(q), -1) for q in grp)
                if ks[0] < 0 or any(len(all_bands[k]) != 1 for k in ks) or ks != list(range(ks[0], ks[0] + len(ks))):
                    continue
                first_of[ks[0]] = (jtext, grp)
                skip.update(ks[1:])
        for k_band, band in enumerate(all_bands):
            if k_band in skip:
                continue
            if k_band in first_of:
                jtext, grp = first_of[k_band]
                _t, _x, _w, size, bold, serif = layout.band_text(grp)
                jx0, intent, jx1, cy0, plan = _joined_para(jtext, grp, size, serif)
                fsize = size * plan["scale"]
                pitch = plan["pitch"] * 1.0
                rows = max(1, int(plan["rows"]))
                top = min(cy0 - pitch / 2, body_bottom - pitch * rows)
                prev = max(0.0, top - cur)
                cur = max(cur, top) + pitch * rows
                lpct = max(50, int(round(pitch / max(1.0, fsize) * 100)))
                spacing = int(max(SPACING_MIN, min(0, round(plan["shrink"] * 100))))
                # 왼쪽 여백 = 줄들의 가장 왼쪽. 들여쓰기(양수)면 첫 줄이 더 들어가고, 내어쓰기(음수)면 둘째 줄부터 |intent| 들어간다
                doc.add_paragraph(jtext, section=sec, para_pr_id_ref=st.para(
                    jx0 - left, prev, wrap=True, right_pt=max(0.0, (w - right) - jx1 - 0.5), intent_pt=intent, line_pct=lpct),
                    char_pr_id_ref=st.run(fsize, spacing, bold, serif))
                continue
            text, x0, width, size, bold, serif = layout.band_text(band)
            lh = size * LINE_PCT / 100.0
            cy = sum((q["rect"][1] + q["rect"][3]) / 2 for q in band) / len(band)
            top = cy - lh / 2
            # 본문 영역 아래 끝을 넘지 않게 — 꼬리말 바로 위 줄이 반올림·첫 문단 높이로 1~2 pt 넘쳐 쪽이 늘었다(261014-30 표본 시험)
            top = min(top, body_bottom - lh)
            prev = max(0.0, top - cur)
            cur = max(cur, top) + lh
            doc.add_paragraph(text, section=sec, para_pr_id_ref=st.para(x0 - left, prev),
                              char_pr_id_ref=st.run(size, _spacing(text, width, size, serif), bold, serif))
        for b in blocks:                           # 자리 없는 줄(좌표 없는 OCR) — 뒤에 이어서
            if b["kind"] == "line" and not b.get("rect"):
                doc.add_paragraph(b["text"], section=sec, para_pr_id_ref=st.para(0, 0),
                                  char_pr_id_ref=st.run(b["size"], 0, b["bold"], b["serif"]))
    st.finish()
    tick(len(pages), len(pages), step_text("save"))
    _sync_manifest(doc)                         # 쪽마다 구역 — 저장이 낡은 manifest 로 덮어써 그림이 빠졌다(§4.2, 261112-17)
    doc.save_to_path(str(dst))
