# -*- coding: utf-8 -*-
"""사진 위치 → 행정동 이름 — 동봉 자료로 오프라인 찾기 (태그 SOT §5.7, 261105-6).

자료: `resources/geo/kr_dong.bin` — vuski/admdongkor(통계청 SGIS 행정동 경계 가공, CC BY 4.0)를 단순화해 넣은 것
(만드는 법 `scripts/build_kr_dong.py`). 위치는 앱 밖으로 나가지 않는다.

- 처음 부를 때 한 번 읽어 격자 색인(`CELL` 칸)을 만든다 — **배경에서만** 부른다(응답성 SOT §4, 읽기·색인 ~1초).
- 찾기: 점이 든 칸의 동 후보 → 상자 → 다각형(짝홀 규칙). 단순화로 생긴 경계 틈(해안·경계선 위)은
  `NEAR` 안의 가장 가까운 꼭짓점의 동으로. 국내 상자(`KR_BOX`) 밖·못 찾으면 None.
"""
from __future__ import annotations

import array
import json
import re
import struct
import sys
import threading
import zlib

KR_BOX = (124.0, 32.8, 132.2, 38.9)      # 경도·위도 — 이 밖은 찾지 않는다(해외)
CELL = 2000                              # 격자 칸(좌표 단위 1e-5° → 0.02°)
NEAR = 300                               # 경계 틈 허용(≈ 300m)

_LOCK = threading.Lock()
_DATA = None                             # (이름들, 동별 (고리 시작, 고리 끝), 고리 (점 시작, 점 수), 좌표 array, 상자들, 격자, 머리)


def data_path():
    from viewer.resources_path import resource_path
    return resource_path("geo/kr_dong.bin")


def _load(path=None):
    raw = open(path or data_path(), "rb").read()
    if not raw.startswith(b"KRDONG1\n"):
        raise ValueError("kr_dong.bin 형식이 아니다")
    hl = struct.unpack_from("<I", raw, 8)[0]
    head = json.loads(raw[12:12 + hl].decode("utf-8"))
    body = zlib.decompress(raw[12 + hl:])
    nl = struct.unpack_from("<I", body, 0)[0]
    names = body[4:4 + nl].decode("utf-8").split("\n")
    off = 4 + nl
    feats, rings = [], []
    for _ in names:
        rc = struct.unpack_from("<H", body, off)[0]
        off += 2
        r0 = len(rings)
        for _ in range(rc):
            rings.append(struct.unpack_from("<I", body, off)[0])
            off += 4
        feats.append((r0, len(rings)))
    d = array.array("i")
    d.frombytes(body[off:])
    if sys.byteorder != "little":
        d.byteswap()
    # 차분 → 절대 좌표(고리마다 첫 점이 절대값)
    xy = array.array("i", bytes(len(d) * 4))
    ring_at, p = [], 0
    for n in rings:
        ring_at.append((p, n))
        x = y = 0
        for i in range(n):
            j = 2 * (p + i)
            if i == 0:
                x, y = d[j], d[j + 1]
            else:
                x += d[j]
                y += d[j + 1]
            xy[j], xy[j + 1] = x, y
        p += n
    boxes, grid = [], {}
    for fi, (r0, r1) in enumerate(feats):
        x0 = y0 = 1 << 30
        x1 = y1 = -(1 << 30)
        for ri in range(r0, r1):
            s, n = ring_at[ri]
            xs = xy[2 * s:2 * (s + n):2]
            ys = xy[2 * s + 1:2 * (s + n):2]
            x0, x1 = min(x0, min(xs)), max(x1, max(xs))
            y0, y1 = min(y0, min(ys)), max(y1, max(ys))
        boxes.append((x0, y0, x1, y1))
        for cx in range(x0 // CELL, x1 // CELL + 1):
            for cy in range(y0 // CELL, y1 // CELL + 1):
                grid.setdefault((cx, cy), []).append(fi)
    return names, feats, ring_at, xy, boxes, grid, head


def ensure_loaded(path=None):
    """자료를 읽어 둔다(배경에서). 못 읽으면 False — 동 태그만 빠진다."""
    global _DATA
    with _LOCK:
        if _DATA is None:
            try:
                _DATA = _load(path)
            except Exception:
                _DATA = False
        return bool(_DATA)


def info() -> dict:
    """자료 머리(ver·source·count) — 정보 창·검사용."""
    return dict(_DATA[6]) if ensure_loaded() else {}


def _inside(xy, s, n, x, y) -> bool:
    c = False
    j = s + n - 1
    for i in range(s, s + n):
        xi, yi = xy[2 * i], xy[2 * i + 1]
        xj, yj = xy[2 * j], xy[2 * j + 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def lookup(lat, lon):
    """(위도, 경도) → 행정동 전체 이름('경기도 고양시일산서구 대화동') 또는 None."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (KR_BOX[0] <= lon <= KR_BOX[2] and KR_BOX[1] <= lat <= KR_BOX[3]):
        return None
    if not ensure_loaded():
        return None
    names, feats, ring_at, xy, boxes, grid, _h = _DATA
    x, y = round(lon * 100000), round(lat * 100000)
    cands = grid.get((x // CELL, y // CELL), ())
    for fi in cands:
        b = boxes[fi]
        if not (b[0] <= x <= b[2] and b[1] <= y <= b[3]):
            continue
        r0, r1 = feats[fi]
        inside = False
        for ri in range(r0, r1):
            s, n = ring_at[ri]
            if _inside(xy, s, n, x, y):
                inside = not inside              # 짝홀 — 구멍은 빠진다
        if inside:
            return names[fi]
    best, bd = None, NEAR * NEAR + 1             # 경계 틈 — 가까운 꼭짓점
    seen = set()
    for cx in (x // CELL - 1, x // CELL, x // CELL + 1):
        for cy in (y // CELL - 1, y // CELL, y // CELL + 1):
            for fi in grid.get((cx, cy), ()):
                if fi in seen:
                    continue
                seen.add(fi)
                b = boxes[fi]
                if x < b[0] - NEAR or x > b[2] + NEAR or y < b[1] - NEAR or y > b[3] + NEAR:
                    continue
                r0, r1 = feats[fi]
                for ri in range(r0, r1):
                    s, n = ring_at[ri]
                    for i in range(s, s + n):
                        dx, dy = xy[2 * i] - x, xy[2 * i + 1] - y
                        dd = dx * dx + dy * dy
                        if dd < bd:
                            bd, best = dd, fi
    return names[best] if best is not None else None


_CITY_GU = re.compile(r"^(.+?시).+구$")       # 구가 있는 시 — 자료에는 '고양시일산서구' 처럼 붙어 있다


def region_of(full: str):
    """행정동 전체 이름 → 시·군·구 태그 값(태그 SOT §5.7, 261105-13 사용자 결정).
    '경기도 고양시일산서구 대화동' → 고양시(구가 있는 시는 시만) · '서울특별시 강남구 역삼1동' → 강남구(자치구) ·
    '경기도 연천군 연천읍' → 연천군 · '세종특별자치시 세종시 조치원읍' → 세종시."""
    parts = (full or "").split()
    if len(parts) < 3:
        return None
    sgg = parts[1]
    m = _CITY_GU.match(sgg)
    return m.group(1) if m else sgg


def region_name(lat, lon):
    """시·군·구 이름 — 사진 지역 태그 값. 못 찾으면 None."""
    return region_of(lookup(lat, lon))


def dong_name(lat, lon):
    """동 이름만('대화동') — 태그 값. 못 찾으면 None."""
    full = lookup(lat, lon)
    if not full:
        return None
    return full.split()[-1]
