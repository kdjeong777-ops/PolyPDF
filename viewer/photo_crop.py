# -*- coding: utf-8 -*-
"""사진 보기 크롭 — 자른 모양만 기억하고 원본은 그대로 (사진 보기 SOT §4.40, 261105-4).

- 저장값 `box0` = **회전 0 판 쪽 비율** (x0, y0, x1, y1) — D14(EXIF 방향 적용 뒤 픽셀). 보기 회전을 바꿔도 같은 곳이 남는다.
- 화면·크롭 창은 **보이는 방향**(보기 회전 뒤) 상자 `boxv` 와 여백 [위, 아래, 왼, 오른] % 로 다룬다.
- 꾸밈(`photo_deco` 로 돌린 뒤의 쪽 비율)·OCR 낱말(돌린 뒤 pt)은 자른 쪽 좌표로 옮겨 보이고, 쓸 때 되돌린다.
  쪽 비율을 선형으로 옮기므로 개체의 실제 크기(pt)는 그대로다 — 쪽이 작아진 만큼 비율이 커진다.
"""
from __future__ import annotations

import copy

from viewer.photo_deco import _pt, inverse

FULL = (0.0, 0.0, 1.0, 1.0)
EPS = 1e-4


def norm(box) -> tuple | None:
    """저장값 → (x0, y0, x1, y1) 0..1, 넓이가 있는 것만. 쪽 전체(자르지 않음)·이상한 값은 None."""
    try:
        x0, y0, x1, y1 = (float(v) for v in list(box)[:4])
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
    y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
    if x1 - x0 < 0.01 or y1 - y0 < 0.01:
        return None
    if x0 < EPS and y0 < EPS and x1 > 1 - EPS and y1 > 1 - EPS:
        return None
    return (round(x0, 5), round(y0, 5), round(x1, 5), round(y1, 5))


def _turn(box, rot: int) -> tuple:
    a = _pt(box[0], box[1], rot)
    b = _pt(box[2], box[3], rot)
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def to_view(box0, rot: int) -> tuple:
    """회전 0 판 상자 → 보이는 방향(시계 `rot`) 상자."""
    return _turn(box0, int(rot or 0) % 360)


def to_rot0(boxv, rot: int) -> tuple:
    """보이는 방향 상자 → 회전 0 판 상자."""
    return _turn(boxv, inverse(int(rot or 0) % 360))


def margins_of(boxv) -> list:
    """보이는 방향 상자 → [위, 아래, 왼, 오른] %."""
    x0, y0, x1, y1 = boxv or FULL
    return [round(y0 * 100, 1), round((1 - y1) * 100, 1), round(x0 * 100, 1), round((1 - x1) * 100, 1)]


def box_of(margins) -> tuple:
    """[위, 아래, 왼, 오른] % → 보이는 방향 상자."""
    t, b, l, r = (float(v) / 100.0 for v in margins)
    return (l, t, 1.0 - r, 1.0 - b)


def size_after(w: float, h: float, boxv) -> tuple:
    """보이는 방향 쪽 크기(pt) → 자른 뒤 크기."""
    if not boxv:
        return (w, h)
    return (max(1.0, w * (boxv[2] - boxv[0])), max(1.0, h * (boxv[3] - boxv[1])))


def px_box(box, w: int, h: int) -> tuple:
    """쪽 비율 상자 → 그림 픽셀 상자(PIL `crop` 꼴, 적어도 1px)."""
    x0, y0 = int(round(box[0] * w)), int(round(box[1] * h))
    x1, y1 = max(x0 + 1, int(round(box[2] * w))), max(y0 + 1, int(round(box[3] * h)))
    return (x0, y0, min(w, x1), min(h, y1))


def crop_pil(im, box0):
    """회전 0 판 그림(방향을 세운 뒤, 크기는 아무래도 됨) → 자른 그림. 상자가 없으면 그대로."""
    if not box0:
        return im
    return im.crop(px_box(box0, im.width, im.height))


def crop_qimage(img, box0):
    """회전 0 판 QImage → 자른 QImage."""
    if not box0 or img is None or img.isNull():
        return img
    x0, y0, x1, y1 = px_box(box0, img.width(), img.height())
    return img.copy(x0, y0, x1 - x0, y1 - y0)


def decode_box(box0, need: int) -> int:
    """자른 영역이 `need` px 이 되도록 풀 긴 변 — 자른 곳이 작을수록 크게(원본보다 크게는 풀지 않는다 — 부르는 쪽이 원본으로 막는다)."""
    if not box0:
        return int(need)
    k = min(box0[2] - box0[0], box0[3] - box0[1])
    return int(need / max(0.05, k)) + 1


def native_rect(box0, w: float, h: float) -> list:
    """PDF 쪽(회전 0, MediaBox 원점 0, 폭 w·높이 h pt) 위 상자 → PDF 본래 좌표(왼쪽 아래 원점) [x0, y0, x1, y1]."""
    return [box0[0] * w, h - box0[3] * h, box0[2] * w, h - box0[1] * h]


# ── 꾸밈 좌표 (보이는 방향 쪽 비율 ↔ 자른 쪽 비율) ─────────────────────
def _fwd(boxv) -> tuple:
    """자르지 않은 쪽 비율 → 자른 쪽 비율: x' = (x − a)·sx."""
    x0, y0, x1, y1 = boxv
    return (x0, y0, 1.0 / (x1 - x0), 1.0 / (y1 - y0))


def _back(boxv) -> tuple:
    """자른 쪽 비율 → 자르지 않은 쪽 비율(같은 꼴의 역)."""
    x0, y0, x1, y1 = boxv
    sx, sy = (x1 - x0), (y1 - y0)
    return (-x0 / sx, -y0 / sy, sx, sy)


def _map_stroke(s: dict, a: float, b: float, sx: float, sy: float) -> dict:
    d = copy.deepcopy(s)

    def P(x, y):
        return [(float(x) - a) * sx, (float(y) - b) * sy]

    def R(r4):
        p, q = P(r4[0], r4[1]), P(r4[2], r4[3])
        return [p[0], p[1], q[0], q[1]]
    if d.get("points"):
        d["points"] = [P(x, y) for x, y in d["points"]]
    if d.get("bands"):
        d["bands"] = [[(float(v[0]) - a) * sx, (float(v[1]) - a) * sx, (float(v[2]) - b) * sy, float(v[3]) * sy] + list(v[4:])
                      for v in d["bands"]]
    if d.get("hl") and d.get("h") is not None:
        d["h"] = float(d["h"]) * sy
    if d.get("shape") == "circle":
        c = P(d.get("cx", 0.5), d.get("cy", 0.5))
        d["cx"], d["cy"] = c
        d["r"] = float(d.get("r", 0.0)) * sx
    if d.get("rect"):
        d["rect"] = R([float(v) for v in d["rect"][:4]])
    for k in ("anchor", "box_anchor"):
        if d.get(k):
            d[k] = P(d[k][0], d[k][1])
    if d.get("hl_rects"):
        d["hl_rects"] = [R([float(v) for v in r4[:4]]) for r4 in d["hl_rects"]]
    return d


def _map_image(im: dict, a: float, b: float, sx: float, sy: float) -> dict:
    d = copy.deepcopy(im)
    if d.get("rect"):
        x, y, w, h = (float(v) for v in d["rect"][:4])
        d["rect"] = [round((x - a) * sx, 6), round((y - b) * sy, 6), round(w * sx, 6), round(h * sy, 6)]
    return d


def map_strokes(strokes, boxv, back: bool = False) -> list:
    """꾸밈 선·도형 — `back=False` 면 자르지 않은 쪽 비율 → 자른 쪽 비율(보이기), True 면 그 역(남기기)."""
    lst = [s for s in (strokes or []) if isinstance(s, dict)]
    if not boxv:
        return [copy.deepcopy(s) for s in lst]
    k = _back(boxv) if back else _fwd(boxv)
    return [_map_stroke(s, *k) for s in lst]


def map_images(images, boxv, back: bool = False) -> list:
    lst = [i for i in (images or []) if isinstance(i, dict)]
    if not boxv:
        return [copy.deepcopy(i) for i in lst]
    k = _back(boxv) if back else _fwd(boxv)
    return [_map_image(i, *k) for i in lst]


def words_view(words, boxv, w: float, h: float) -> list:
    """보이는 방향 OCR 낱말(pt, 쪽 폭 w·높이 h) → 자른 쪽 pt. 가운데가 자른 바깥인 낱말은 뺀다."""
    if not boxv:
        return list(words or [])
    ox, oy = boxv[0] * w, boxv[1] * h
    ex, ey = boxv[2] * w, boxv[3] * h
    out = []
    for wd in words or []:
        cx = (float(wd["x0"]) + float(wd["x1"])) / 2.0
        cy = (float(wd["y0"]) + float(wd["y1"])) / 2.0
        if not (ox <= cx <= ex and oy <= cy <= ey):
            continue
        d = dict(wd)
        d["x0"], d["x1"] = float(wd["x0"]) - ox, float(wd["x1"]) - ox
        d["y0"], d["y1"] = float(wd["y0"]) - oy, float(wd["y1"]) - oy
        out.append(d)
    return out


def after_orient_save(box0, rot: int) -> tuple | None:
    """방향을 원본에 저장한 뒤(§4.17) — 새 회전 0 판 = 옛 보기 방향이므로 상자도 같은 만큼 돌린다."""
    return norm(to_view(box0, rot)) if box0 else None
