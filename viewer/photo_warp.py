# -*- coding: utf-8 -*-
"""사진 모양 펴기 — 원근·휜 테두리를 직사각형으로 (사진 보기 SOT §4.43, 261106-6 사용자 지시).

새 라이브러리 없이(사용자 결정 'PIL 간단 인식' — OpenCV·numpy 를 넣지 않는다) 순수 파이썬 + Pillow 로:

- 점 8개 — 보이는 방향(보기 회전 뒤) 그림의 비율 좌표(0..1): 꼭짓점 `TL·TR·BR·BL` + 변 중간 `T·R·B·L`.
  변 중간점은 그 변이 지나는 곳(2차 곡선이 그 점을 지난다).
- 네 변이 곧으면(중간점이 꼭짓점 사이 가운데 — `STRAIGHT_TOL`) **원근 변환**(`Image.PERSPECTIVE`, 계수는 8×8 연립식을 풀어서).
- 휘었으면 원근을 먼저 풀고(꼭짓점 → 단위 정사각형) 그 판에서 네 변을 2차 곡선으로 잇는 **Coons 면**으로 펴서
  격자(`MESH_CELLS`)로 나눠 `Image.MESH` — 원근과 휨이 함께 있는 사진(책 가운데가 움푹)도 곧게 편다.
- 출력 크기 = 마주 보는 두 변 길이의 평균(원본 화소 기준), 넓이는 원본을 넘지 않게.
- 테두리 어림(`detect`): 줄인 회색 그림을 Otsu 로 둘로 나눠 가장자리에 많은 쪽을 바탕으로 보고, 나머지(종이·사진) 의
  맨 끝 점을 꼭짓점으로, 변 중간은 그 변의 바깥 경계를 찾는다. 틀리면 손으로 고친다(사용자 결정).
"""
from __future__ import annotations

import math

POINT_NAMES = ("TL", "TR", "BR", "BL", "T", "R", "B", "L")
STRAIGHT_TOL = 0.004        # 중간점이 꼭짓점 사이 가운데에서 이만큼(그림 비율) 안이면 곧은 변
MESH_CELLS = 24             # 휜 테두리 펴기 격자 — 한 변에 칸 수
DETECT_SIDE = 256           # 테두리 어림 — 줄인 그림 긴 변
DETECT_MIN_AREA = 0.06      # 어림한 영역이 그림의 이만큼보다 작거나
DETECT_MAX_AREA = 0.985     #   이만큼보다 크면 못 찾은 것으로 본다(기본 점)
DEFAULT_INSET = 0.04        # 못 찾았을 때 기본 점 — 가장자리에서 이만큼 안
OUT_MIN_SIDE = 16           # 펼친 그림 짧은 변 하한(화소)


# ── 점 ────────────────────────────────────────────────
def default_points(inset: float = DEFAULT_INSET) -> list:
    a, b = inset, 1.0 - inset
    c = [(a, a), (b, a), (b, b), (a, b)]
    return c + mids_of(c)


def mids_of(corners) -> list:
    """꼭짓점 넷 → 곧은 변의 가운데 넷(T·R·B·L)."""
    tl, trc, br, bl = corners
    return [_mid(tl, trc), _mid(trc, br), _mid(br, bl), _mid(bl, tl)]


def _mid(p, q):
    return ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)


def clamp_points(pts) -> list:
    return [(min(1.0, max(0.0, float(x))), min(1.0, max(0.0, float(y)))) for x, y in pts]


def is_straight(pts, tol: float = STRAIGHT_TOL) -> bool:
    c, m = pts[:4], pts[4:8]
    for got, want in zip(m, mids_of(c)):
        if math.hypot(got[0] - want[0], got[1] - want[1]) > tol:
            return False
    return True


def is_identity(pts, tol: float = 1e-3) -> bool:
    """꼭짓점이 그림 네 귀퉁이 그대로이고 변이 곧다 — 펼 것이 없다."""
    want = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    return is_straight(pts) and all(math.hypot(a[0] - b[0], a[1] - b[1]) <= tol for a, b in zip(pts[:4], want))


def is_valid(pts) -> bool:
    """꼭짓점 넷이 볼록한 사각형(같은 방향으로 돈다) — 꼬이면 펴지 않는다."""
    c = pts[:4]
    sign = 0
    for i in range(4):
        a, b, d = c[i], c[(i + 1) % 4], c[(i + 2) % 4]
        cross = (b[0] - a[0]) * (d[1] - b[1]) - (b[1] - a[1]) * (d[0] - b[0])
        if abs(cross) < 1e-9:
            return False
        s = 1 if cross > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


# ── 원근(호모그래피) ───────────────────────────────────
def _solve(a, b):
    """가우스 소거(부분 피벗) — a x = b."""
    n = len(b)
    m = [list(map(float, row)) + [float(v)] for row, v in zip(a, b)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ValueError("singular")
        m[col], m[piv] = m[piv], m[col]
        p = m[col][col]
        for r in range(n):
            if r != col and m[r][col]:
                f = m[r][col] / p
                for k in range(col, n + 1):
                    m[r][k] -= f * m[col][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def homography(dst, src):
    """dst 점 넷 → src 점 넷으로 보내는 계수 8개(PIL PERSPECTIVE 꼴): src = ((a x+b y+c)/(g x+h y+1), (d x+e y+f)/(g x+h y+1))."""
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return _solve(a, b)


def apply_h(c, x, y):
    w = c[6] * x + c[7] * y + 1.0
    return ((c[0] * x + c[1] * y + c[2]) / w, (c[3] * x + c[4] * y + c[5]) / w)


def invert_h(c):
    m = [[c[0], c[1], c[2]], [c[3], c[4], c[5]], [c[6], c[7], 1.0]]
    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    if abs(det) < 1e-15:
        raise ValueError("singular")
    inv = [[(m[(j + 1) % 3][(i + 1) % 3] * m[(j + 2) % 3][(i + 2) % 3]
             - m[(j + 1) % 3][(i + 2) % 3] * m[(j + 2) % 3][(i + 1) % 3]) / det for j in range(3)] for i in range(3)]
    s = inv[2][2]
    return [inv[0][0] / s, inv[0][1] / s, inv[0][2] / s, inv[1][0] / s, inv[1][1] / s, inv[1][2] / s,
            inv[2][0] / s, inv[2][1] / s]


# ── 휜 테두리(Coons 면) ────────────────────────────────
def _quad_curve(p0, mid, p2, t):
    """p0 → p2, t=0.5 에서 mid 를 지나는 2차 곡선."""
    cx, cy = 2 * mid[0] - (p0[0] + p2[0]) / 2.0, 2 * mid[1] - (p0[1] + p2[1]) / 2.0
    s = 1.0 - t
    return (s * s * p0[0] + 2 * s * t * cx + t * t * p2[0], s * s * p0[1] + 2 * s * t * cy + t * t * p2[1])


def surface(pts):
    """(u, v) ∈ [0,1]² → 그림 좌표(점과 같은 단위). 곧으면 원근, 휘었으면 원근을 푼 판의 Coons 면을 다시 원근으로."""
    c = pts[:4]
    sq = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    h = homography(sq, c)                  # 단위 정사각형 → 그림
    if is_straight(pts):
        return lambda u, v: apply_h(h, u, v)
    q = invert_h(h)                        # 그림 → 단위 정사각형
    tm, rm, bm, lm = (apply_h(q, x, y) for x, y in pts[4:8])
    tl, trc, br, bl = sq

    def f(u, v):
        top = _quad_curve(tl, tm, trc, u)
        bot = _quad_curve(bl, bm, br, u)
        lef = _quad_curve(tl, lm, bl, v)
        rig = _quad_curve(trc, rm, br, v)
        x = ((1 - v) * top[0] + v * bot[0] + (1 - u) * lef[0] + u * rig[0]
             - ((1 - u) * (1 - v) * tl[0] + u * (1 - v) * trc[0] + (1 - u) * v * bl[0] + u * v * br[0]))
        y = ((1 - v) * top[1] + v * bot[1] + (1 - u) * lef[1] + u * rig[1]
             - ((1 - u) * (1 - v) * tl[1] + u * (1 - v) * trc[1] + (1 - u) * v * bl[1] + u * v * br[1]))
        return apply_h(h, x, y)
    return f


def _curve_len(f, n=24):
    pts = [f(i / n) for i in range(n + 1)]
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def out_size(pts, w: int, h: int) -> tuple:
    """펼친 그림 크기(화소) — 마주 보는 두 변 길이의 평균, 넓이는 원본(w×h)을 넘지 않게."""
    px = [(x * w, y * h) for x, y in pts]
    tl, trc, br, bl, tm, rm, bm, lm = px
    top = _curve_len(lambda t: _quad_curve(tl, tm, trc, t))
    bot = _curve_len(lambda t: _quad_curve(bl, bm, br, t))
    lef = _curve_len(lambda t: _quad_curve(tl, lm, bl, t))
    rig = _curve_len(lambda t: _quad_curve(trc, rm, br, t))
    ow, oh = (top + bot) / 2.0, (lef + rig) / 2.0
    k = math.sqrt(min(1.0, (w * h) / max(1.0, ow * oh)))
    return max(OUT_MIN_SIDE, int(round(ow * k))), max(OUT_MIN_SIDE, int(round(oh * k)))


def unwarp(im, pts, size=None, cells: int = MESH_CELLS):
    """PIL 그림 `im` 의 점 8개(비율) 테두리를 직사각형으로 편다. `size` 가 없으면 `out_size`."""
    from PIL import Image
    pts = clamp_points(pts)
    if not is_valid(pts):
        raise ValueError("points")
    w, h = im.size
    ow, oh = size or out_size(pts, w, h)
    px = [(x * w, y * h) for x, y in pts]
    rs = getattr(Image, "Resampling", Image)
    if is_straight(pts):
        coef = homography([(0, 0), (ow, 0), (ow, oh), (0, oh)], px[:4])
        return im.transform((ow, oh), Image.Transform.PERSPECTIVE if hasattr(Image, "Transform") else Image.PERSPECTIVE,
                            coef, rs.BICUBIC)
    f = surface(px)
    n = max(2, int(cells))
    grid = [[f(i / n, j / n) for i in range(n + 1)] for j in range(n + 1)]       # grid[j][i]
    xs = [round(ow * i / n) for i in range(n + 1)]
    ys = [round(oh * j / n) for j in range(n + 1)]
    mesh = []
    for j in range(n):
        for i in range(n):
            if xs[i + 1] <= xs[i] or ys[j + 1] <= ys[j]:
                continue
            ul, ll, lr, ur = grid[j][i], grid[j + 1][i], grid[j + 1][i + 1], grid[j][i + 1]
            mesh.append(((xs[i], ys[j], xs[i + 1], ys[j + 1]), (ul[0], ul[1], ll[0], ll[1], lr[0], lr[1], ur[0], ur[1])))
    return im.transform((ow, oh), Image.Transform.MESH if hasattr(Image, "Transform") else Image.MESH, mesh, rs.BICUBIC)


# ── 테두리 어림 ────────────────────────────────────────
def _otsu(hist) -> int:
    total = sum(hist)
    if not total:
        return 128
    sum_all = sum(i * v for i, v in enumerate(hist))
    wb = sb = 0.0
    best, th = -1.0, 128
    for t in range(256):
        wb += hist[t]
        if wb == 0:
            continue
        wf = total - wb
        if wf == 0:
            break
        sb += t * hist[t]
        mb, mf = sb / wb, (sum_all - sb) / wf
        var = wb * wf * (mb - mf) ** 2
        if var > best:
            best, th = var, t
    return th


def detect(im) -> list | None:
    """PIL 그림에서 테두리(점 8개, 비율)를 어림한다 — 못 찾으면 None(쓰는 쪽이 기본 점)."""
    from PIL import Image, ImageFilter
    g = im.convert("L")
    w, h = g.size
    if w < 8 or h < 8:
        return None
    s = DETECT_SIDE / float(max(w, h))
    sw, sh = max(8, int(w * s)), max(8, int(h * s))
    g = g.resize((sw, sh), getattr(Image, "Resampling", Image).BILINEAR).filter(ImageFilter.MedianFilter(5))
    th = _otsu(g.histogram())
    data = list(g.getdata())
    bright = [v > th for v in data]
    border = [bright[x] for x in range(sw)] + [bright[(sh - 1) * sw + x] for x in range(sw)]
    border += [bright[y * sw] for y in range(sh)] + [bright[y * sw + sw - 1] for y in range(sh)]
    fg_bright = sum(border) < len(border) / 2.0      # 가장자리에 많은 쪽이 바탕
    mask = [b == fg_bright for b in bright]
    n = sum(mask)
    if not (DETECT_MIN_AREA * sw * sh <= n <= DETECT_MAX_AREA * sw * sh):
        return None
    best = {"TL": (None, 1e18), "TR": (None, -1e18), "BR": (None, -1e18), "BL": (None, 1e18)}
    for y in range(sh):
        row = y * sw
        for x in range(sw):
            if not mask[row + x]:
                continue
            a, d = x + y, x - y
            if a < best["TL"][1]:
                best["TL"] = ((x, y), a)
            if a > best["BR"][1]:
                best["BR"] = ((x, y), a)
            if d > best["TR"][1]:
                best["TR"] = ((x, y), d)
            if d < best["BL"][1]:
                best["BL"] = ((x, y), d)
    corners = [best[k][0] for k in ("TL", "TR", "BR", "BL")]
    if any(c is None for c in corners):
        return None

    def at(x, y):
        xi, yi = int(round(x)), int(round(y))
        return 0 <= xi < sw and 0 <= yi < sh and mask[yi * sw + xi]

    cx = sum(c[0] for c in corners) / 4.0
    cy = sum(c[1] for c in corners) / 4.0
    mids = []
    for p, q in ((corners[0], corners[1]), (corners[1], corners[2]), (corners[2], corners[3]), (corners[3], corners[0])):
        mx, my = (p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0
        nx, ny = mx - cx, my - cy                     # 바깥쪽
        ln = math.hypot(nx, ny) or 1.0
        nx, ny = nx / ln, ny / ln
        reach = int(max(sw, sh) * 0.25)
        got = None
        if at(mx, my):                                # 안에 있다 — 바깥으로 경계까지
            k = 0
            while k < reach and at(mx + nx * (k + 1), my + ny * (k + 1)):
                k += 1
            got = (mx + nx * k, my + ny * k)
        else:                                         # 밖 — 안으로 들어가 처음 닿는 곳(움푹 들어간 변)
            for k in range(1, reach):
                if at(mx - nx * k, my - ny * k):
                    got = (mx - nx * k, my - ny * k)
                    break
        mids.append(got or (mx, my))
    pts = [(x / (sw - 1), y / (sh - 1)) for x, y in corners + mids]
    straight = mids_of(pts[:4])                        # 거의 곧으면 곧게(작은 흔들림을 휨으로 보지 않는다)
    for i in range(4):
        if math.hypot(pts[4 + i][0] - straight[i][0], pts[4 + i][1] - straight[i][1]) < 2.5 / DETECT_SIDE:
            pts[4 + i] = straight[i]
    pts = clamp_points(pts)
    return pts if is_valid(pts) else None
