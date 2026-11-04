# -*- coding: utf-8 -*-
"""사진 꾸밈 좌표 돌리기 (사진 보기 SOT 4.19, 261104-3).

꾸밈(사이드카 `page_meta.json` 의 drawings·images)은 **회전 0 판**(D14 — EXIF 방향 적용 뒤 픽셀) 쪽 비율(0..1)로 남는다.
보기 회전(4.16)으로 쪽이 돌아 있으면 읽을 때 돌려 보이고 쓸 때 되돌려 남긴다. 방향 저장(4.17)은 회전 0 판 자체가 바뀌므로
저장값을 이 함수로 한 번 옮긴다.

규칙(시계 방향 `rot` — 90·180·270):
- 점 (x, y) → 90: (1−y, x) · 180: (1−x, 1−y) · 270: (y, 1−x)
- 상자를 가진 개체(도형 rect·round, 글상자, 지시선 상자, 삽입 그림): **중심만 옮기고 화면 크기(픽셀)는 그대로**, 개체 `rot` 에 회전을 더한다 —
  개체가 사진과 함께 돈다(글상자 글자도 함께 선다).
- 원: 중심을 옮기고 반지름(쪽 폭 비율)을 새 쪽 폭에 맞춘다.
- 하이라이트 띠(가로 띠만 나타낼 수 있다): 90·270 이면 띠마다 가운데 선의 두 끝점으로 바꾼다(`bands` 를 지우고 `points`, 두께 `h` 는 새 쪽 높이 비율).
- 선 굵기(화면 픽셀)·글자 크기(pt)는 그대로.
`w0`·`h0` 은 **돌리기 전** 쪽의 폭·높이(pt = 픽셀).
"""
from __future__ import annotations

import copy


def _pt(x, y, rot):
    if rot == 90:
        return 1.0 - y, x
    if rot == 180:
        return 1.0 - x, 1.0 - y
    if rot == 270:
        return y, 1.0 - x
    return x, y


def _dims(rot, w0, h0):
    return (h0, w0) if rot in (90, 270) else (w0, h0)


def _box(x0, y0, x1, y1, rot, w0, h0):
    """상자(두 모서리, 쪽 비율) → 중심을 옮기고 픽셀 크기는 그대로인 새 두 모서리."""
    w1, h1 = _dims(rot, w0, h0)
    cx, cy = _pt((x0 + x1) / 2.0, (y0 + y1) / 2.0, rot)
    hw = abs(x1 - x0) * w0 / w1 / 2.0
    hh = abs(y1 - y0) * h0 / h1 / 2.0
    return [cx - hw, cy - hh, cx + hw, cy + hh]


def _add_rot(d, rot):
    d["rot"] = round((float(d.get("rot", 0) or 0) + rot) % 360.0, 2)


def rotate_stroke(s: dict, rot: int, w0: float, h0: float) -> dict:
    rot = int(rot) % 360
    if not rot:
        return copy.deepcopy(s)
    d = copy.deepcopy(s)
    w1, h1 = _dims(rot, w0, h0)
    if d.get("hl"):
        bands = d.pop("bands", None)
        if rot in (90, 270) and bands:
            b = bands[0]
            x0, x1, yc, h = (float(v) for v in b[:4])
            d["points"] = [list(_pt(x0, yc, rot)), list(_pt(x1, yc, rot))]
            d["h"] = h * h0 / h1
        elif bands:
            d["bands"] = [[1.0 - float(b[1]), 1.0 - float(b[0]), 1.0 - float(b[2]), float(b[3])] for b in bands]
        if "points" in d and not (rot in (90, 270) and bands):
            d["points"] = [list(_pt(float(x), float(y), rot)) for x, y in d["points"]]
            if rot in (90, 270) and d.get("h") is not None:
                d["h"] = float(d["h"]) * h0 / h1
        return d
    if d.get("shape") == "circle":
        cx, cy = _pt(float(d.get("cx", 0.5)), float(d.get("cy", 0.5)), rot)
        r = float(d.get("r", 0.0)) * w0 / w1
        d["cx"], d["cy"], d["r"] = cx, cy, r
        d["rect"] = [cx - r, cy - r * w1 / h1, cx + r, cy + r * w1 / h1]
        return d
    if d.get("shape") or d.get("text_box") or d.get("leader"):
        if d.get("rect"):
            d["rect"] = _box(*(float(v) for v in d["rect"][:4]), rot, w0, h0)
            _add_rot(d, rot)
        for k in ("anchor", "box_anchor"):
            if d.get(k):
                d[k] = list(_pt(float(d[k][0]), float(d[k][1]), rot))
        if d.get("hl_rects"):
            out = []
            for r4 in d["hl_rects"]:
                a = _pt(float(r4[0]), float(r4[1]), rot)
                b = _pt(float(r4[2]), float(r4[3]), rot)
                out.append([min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])])
            d["hl_rects"] = out
        if d.get("points"):
            d["points"] = [list(_pt(float(x), float(y), rot)) for x, y in d["points"]]
        return d
    if d.get("points"):
        d["points"] = [list(_pt(float(x), float(y), rot)) for x, y in d["points"]]
    return d


def rotate_image(im: dict, rot: int, w0: float, h0: float) -> dict:
    """삽입 그림 — `rect` = [x, y, w, h](쪽 비율), 중심만 옮기고 픽셀 크기 그대로, `rot` 에 더한다."""
    rot = int(rot) % 360
    d = copy.deepcopy(im)
    if not rot or not d.get("rect"):
        return d
    x, y, w, h = (float(v) for v in d["rect"][:4])
    x0, y0, x1, y1 = _box(x, y, x + w, y + h, rot, w0, h0)
    d["rect"] = [round(x0, 5), round(y0, 5), round(x1 - x0, 5), round(y1 - y0, 5)]
    _add_rot(d, rot)
    return d


def rotate_strokes(strokes, rot: int, w0: float, h0: float) -> list:
    return [rotate_stroke(s, rot, w0, h0) for s in (strokes or []) if isinstance(s, dict)]


def rotate_images(images, rot: int, w0: float, h0: float) -> list:
    return [rotate_image(i, rot, w0, h0) for i in (images or []) if isinstance(i, dict)]


def inverse(rot: int) -> int:
    return (360 - int(rot)) % 360
