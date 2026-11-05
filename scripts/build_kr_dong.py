# -*- coding: utf-8 -*-
"""행정동 경계 동봉 자료 만들기 (태그 SOT §5.7, 261105-6).

입력: vuski/admdongkor 의 `HangJeongDong_verYYYYMMDD.geojson`(WGS84, CC BY 4.0 — 원자료 통계청 SGIS 공공누리 1유형).
출력: `resources/geo/kr_dong.bin` — 앱이 오프라인으로 사진 위치 → 행정동 이름을 찾는 데 쓴다(`viewer/kr_dong.py`).

경계는 Douglas–Peucker 로 단순화(기본 허용 0.0002° ≈ 20m)하고 좌표는 1e-5° 정수로 양자화, 고리마다 차분 → int32 → zlib.
형식(모두 little-endian):
    b"KRDONG1\\n" + u32 머리 길이 + 머리(JSON: ver·source·count·scale·tol) + zlib(본문)
    본문 = u32 이름 바이트 길이 + 이름(UTF-8, '\\n' 으로 이음 — 'adm_nm' 전체)
         + 동마다: u16 고리 수, 고리마다 u32 점 수
         + 모든 고리의 점 (x, y) 차분 int32 (고리 첫 점은 절대값)
쓰는 법:  python scripts/build_kr_dong.py <geojson> [--tol 0.0002]
"""
from __future__ import annotations

import argparse
import array
import json
import re
import struct
import sys
import zlib
from pathlib import Path

SCALE = 100000
sys.stdout.reconfigure(encoding="utf-8")            # 마스터 §14.7.2-21 — 한글을 찍는다


def _dp(pts, tol):
    """Douglas–Peucker(반복형) — 첫·끝 점은 남긴다."""
    n = len(pts)
    if n < 5:
        return pts
    keep = bytearray(n)
    keep[0] = keep[-1] = 1
    stack = [(0, n - 1)]
    tol2 = tol * tol
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if L == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / L
                t = 0.0 if t < 0 else 1.0 if t > 1 else t
                d = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d > best:
                best, bi = d, i
        if best > tol2 and bi > 0:
            keep[bi] = 1
            stack.append((a, bi))
            stack.append((bi, b))
    return [p for p, k in zip(pts, keep) if k]


def build(src: Path, out: Path, tol: float) -> dict:
    gj = json.loads(src.read_text(encoding="utf-8"))
    ver = re.search(r"ver(\d{8})", src.name)
    names, ring_counts, ring_lens = [], [], []
    xs = array.array("i")
    n_in = n_out = 0
    for f in gj["features"]:
        nm = (f["properties"].get("adm_nm") or "").strip()
        g = f.get("geometry") or {}
        polys = g.get("coordinates") or []
        if g.get("type") == "Polygon":
            polys = [polys]
        rings = []
        for poly in polys:
            for ring in poly:
                n_in += len(ring)
                r = _dp([(float(x), float(y)) for x, y in ring], tol)
                q = []
                for x, y in r:
                    p = (round(x * SCALE), round(y * SCALE))
                    if not q or q[-1] != p:
                        q.append(p)
                if len(q) >= 4:
                    rings.append(q)
        if not rings:
            continue
        names.append(nm)
        ring_counts.append(len(rings))
        for q in rings:
            ring_lens.append(len(q))
            n_out += len(q)
            px = py = 0
            for i, (x, y) in enumerate(q):
                if i == 0:
                    xs.append(x)
                    xs.append(y)
                else:
                    xs.append(x - px)
                    xs.append(y - py)
                px, py = x, y
    nb = "\n".join(names).encode("utf-8")
    body = bytearray(struct.pack("<I", len(nb)) + nb)
    li = 0
    for rc in ring_counts:
        body += struct.pack("<H", rc)
        for _ in range(rc):
            body += struct.pack("<I", ring_lens[li])
            li += 1
    if sys.byteorder != "little":
        xs.byteswap()
    body += xs.tobytes()
    head = json.dumps({"ver": ver.group(1) if ver else "", "source": "vuski/admdongkor (통계청 SGIS, CC BY 4.0)",
                       "count": len(names), "scale": SCALE, "tol": tol}, ensure_ascii=False).encode("utf-8")
    data = b"KRDONG1\n" + struct.pack("<I", len(head)) + head + zlib.compress(bytes(body), 9)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return {"count": len(names), "points_in": n_in, "points_out": n_out, "bytes": len(data)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("geojson")
    ap.add_argument("--tol", type=float, default=0.0002)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "resources" / "geo" / "kr_dong.bin"))
    a = ap.parse_args()
    print(build(Path(a.geojson), Path(a.out), a.tol))


if __name__ == "__main__":
    main()
