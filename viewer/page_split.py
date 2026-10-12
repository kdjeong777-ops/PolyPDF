# -*- coding: utf-8 -*-
"""쪽 나누기 — 1쪽을 2쪽(좌우·위아래) 또는 4쪽으로 (261012-2, 마스터 §4.7.15 '쪽 나누기').

크롭한 뒤 남은 영역(크롭 여백을 뺀 곳)을 나눔선으로 가르고, 조각마다 **쪽 내용은 그대로 복사하고 CropBox 만**
다르게 준다 — 글자 검색·복사·링크가 그대로 남는다. 위·아래·왼·오른쪽과 나눔선 위치는 크롭과 같이 **보이는 방향**
(`/Rotate`·저장 전 회전 적용 뒤) 기준 %. Qt 를 쓰지 않는다(배경 작업·검사에서 그대로 부른다).

결과는 조각들만 담은 임시 PDF — 앱이 썸네일 '스테이징 쪽'(§4.7.12)으로 원래 쪽 자리에 끼워 보이고 [저장] 때 넣는다.
"""
from __future__ import annotations

import fitz

from viewer import page_crop as pc
from viewer.i18n import tr

NONE, VERTICAL, HORIZONTAL, QUAD = "none", "v", "h", "4"
MODES = (NONE, VERTICAL, HORIZONTAL, QUAD)
POS_MIN, POS_MAX = 5.0, 95.0          # 나눔선 위치 % — 조각이 너무 얇지 않게


def norm_spec(spec) -> dict:
    spec = dict(spec or {})
    mode = spec.get("mode") if spec.get("mode") in MODES else NONE

    def _pos(v):
        try:
            return max(POS_MIN, min(POS_MAX, float(v)))
        except Exception:
            return 50.0
    return {"mode": mode, "x": _pos(spec.get("x", 50.0)), "y": _pos(spec.get("y", 50.0)),
            "rtl": bool(spec.get("rtl"))}


def part_count(spec) -> int:
    m = norm_spec(spec)["mode"]
    return {NONE: 1, VERTICAL: 2, HORIZONTAL: 2, QUAD: 4}[m]


def parts(spec) -> list:
    """크롭 영역 안의 조각 — [(x0, y0, x1, y1) 비율 0~1, 보이는 방향] 을 쪽 차례대로.
    좌우는 왼→오(rtl 이면 오→왼), 위아래는 위→아래, 4쪽은 위 줄 먼저(rtl 이면 줄마다 오→왼)."""
    s = norm_spec(spec)
    x, y = s["x"] / 100.0, s["y"] / 100.0
    if s["mode"] == VERTICAL:
        row = [(0.0, 0.0, x, 1.0), (x, 0.0, 1.0, 1.0)]
        return row[::-1] if s["rtl"] else row
    if s["mode"] == HORIZONTAL:
        return [(0.0, 0.0, 1.0, y), (0.0, y, 1.0, 1.0)]
    if s["mode"] == QUAD:
        top = [(0.0, 0.0, x, y), (x, 0.0, 1.0, y)]
        bot = [(0.0, y, x, 1.0), (x, y, 1.0, 1.0)]
        if s["rtl"]:
            top, bot = top[::-1], bot[::-1]
        return top + bot
    return [(0.0, 0.0, 1.0, 1.0)]


def part_margins(margins, frac) -> list:
    """크롭 여백 [위,아래,왼,오른] % 와 조각 비율 → 그 조각의 여백 %(쪽 전체 기준, 보이는 방향)."""
    t, b, l, r = (list(margins) if margins is not None else [0.0, 0.0, 0.0, 0.0])[:4]
    w = 100.0 - l - r
    h = 100.0 - t - b
    fx0, fy0, fx1, fy1 = frac
    return [t + h * fy0, b + h * (1.0 - fy1), l + w * fx0, r + w * (1.0 - fx1)]


def build_parts(src, pages, margins_by_page: dict, spec, out, with_pending_rotation: bool = True, progress=None) -> dict:
    """`pages`(0부터) 마다 조각들을 만들어 `out` 에 차례로 쓴다. 반환 {원래 쪽: [out 안의 조각 쪽, …]}.

    `margins_by_page` = 크롭 여백(보이는 방향 %, None = 자르지 않음). 저장 전 회전(§4.7.16)은 먼저 덧입힌다 —
    여백·나눔선은 회전 뒤 보이는 방향 기준이다(크롭과 같다). `progress(done, total, label) -> bool` 이 False 면 pc.Cancelled."""
    spec = norm_spec(spec)
    fr = parts(spec)
    sdoc = fitz.open(str(src))
    odoc = fitz.open()
    got = {}
    try:
        if with_pending_rotation:
            from viewer import page_rotate as _pr
            _pr.apply_pending(sdoc, src)
        total = max(1, len(pages))
        for k, pg in enumerate(pages):
            if progress is not None and progress(k, total, tr("쪽 나누기")) is False:
                raise pc.Cancelled()
            pg = int(pg)
            if not (0 <= pg < sdoc.page_count):
                continue
            m = margins_by_page.get(pg) if margins_by_page else None
            first = odoc.page_count
            odoc.insert_pdf(sdoc, from_page=pg, to_page=pg)
            for _ in fr[1:]:
                odoc.fullcopy_page(first)       # 쪽 내용을 그대로 — CropBox 만 조각마다 다르게
            idx = []
            for j, f in enumerate(fr):
                page = odoc[first + j]
                pc.set_crop(page, pc.crop_box(page, part_margins(m, f), clamp=False))
                idx.append(first + j)
            got[pg] = idx
        if odoc.page_count == 0:
            raise RuntimeError("no pages")
        odoc.save(str(out), garbage=3, deflate=True)
    finally:
        odoc.close()
        sdoc.close()
    return got
