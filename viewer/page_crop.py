# -*- coding: utf-8 -*-
"""쪽 크롭 — PDF 의 `/CropBox` 계산·쓰기 (261010-7, 마스터 §4.7.15).

여백은 **MediaBox(쪽 전체) 기준 %** 이고, 위·아래·왼·오른쪽은 PDF `/Rotate` 를 적용해 **보이는 방향** 기준이다.
PyMuPDF `set_cropbox` 는 MediaBox 원점이 0 이 아닌 쪽에서 좌표가 어긋나(실측) PDF 본래 좌표(왼쪽 아래 원점)로
셈해 `/CropBox` 를 직접 쓴다. Qt 를 쓰지 않는다(배경 작업·검사에서 그대로 부른다).
"""
from __future__ import annotations

import re
from pathlib import Path

import fitz

CROP_MAX = 45.0                 # 한 변 최대 %(양쪽 합이 100 을 넘지 않게)
PORTRAIT, LANDSCAPE = "portrait", "landscape"
BUILTIN_IDS = (PORTRAIT, LANDSCAPE)
WHITE = 245                     # 흰 여백 감지 — 이보다 어두우면 내용
DETECT_W = 220                  # 흰 여백 감지 렌더 폭(px)


class Cancelled(Exception):
    pass


# ── 스타일 ────────────────────────────────────────────────────────
def default_styles() -> list:
    """기본 스타일 2개 — 이름은 화면에서 번역해 보인다(`style_label`)."""
    return [{"id": PORTRAIT, "name": "", "margins": [0.0, 0.0, 0.0, 0.0], "auto": False, "mirror": False},
            {"id": LANDSCAPE, "name": "", "margins": [0.0, 0.0, 0.0, 0.0], "auto": False, "mirror": False}]


def norm_style(st: dict) -> dict:
    m = list(st.get("margins") or [0, 0, 0, 0])[:4] + [0.0] * 4
    return {"id": str(st.get("id") or ""), "name": str(st.get("name") or ""),
            "margins": [max(0.0, min(CROP_MAX, float(v or 0))) for v in m[:4]],
            "auto": bool(st.get("auto")), "mirror": bool(st.get("mirror"))}


def load_styles(saved) -> list:
    """설정의 `crop_styles` → 기본 2개가 늘 맨 앞에 있는 목록."""
    by = {}
    for st in (saved or []):
        if isinstance(st, dict) and st.get("id"):
            by[str(st["id"])] = norm_style(st)
    out = [by.pop(d["id"], d) for d in default_styles()]
    seen = set(BUILTIN_IDS)
    for st in (saved or []):
        sid = str(st.get("id") or "") if isinstance(st, dict) else ""
        if sid and sid not in seen and sid in by:
            out.append(by[sid]); seen.add(sid)
    return out


def new_style_id(styles) -> str:
    used = {s["id"] for s in styles}
    i = 1
    while "user%d" % i in used:
        i += 1
    return "user%d" % i


def default_auto() -> dict:
    return {"on": True, PORTRAIT: PORTRAIT, LANDSCAPE: LANDSCAPE}


def load_auto(saved, styles) -> dict:
    a = default_auto()
    if isinstance(saved, dict):
        a["on"] = bool(saved.get("on", True))
        ids = {s["id"] for s in styles}
        for k in (PORTRAIT, LANDSCAPE):
            if saved.get(k) in ids:
                a[k] = saved[k]
    return a


# ── 쪽 정보 ──────────────────────────────────────────────────────
def orientation(page) -> str:
    """보이는 방향(MediaBox 에 /Rotate 적용) — 가로가 더 길면 가로긴 쪽."""
    mb = page.mediabox
    w, h = mb.width, mb.height
    if page.rotation % 180:
        w, h = h, w
    return LANDSCAPE if w > h else PORTRAIT


def full_size_pt(page) -> tuple:
    """보이는 방향의 쪽 전체(MediaBox) 크기(pt)."""
    mb = page.mediabox
    w, h = mb.width, mb.height
    return (h, w) if page.rotation % 180 else (w, h)


def is_cropped(page) -> bool:
    try:
        mb, cb = _native_box(page, "MediaBox"), _native_box(page, "CropBox")
    except Exception:
        return False
    if cb is None:
        return False
    return any(abs(a - b) > 0.5 for a, b in zip(_clip(cb, mb), mb))


def parse_range(text: str, n: int) -> list:
    """'1-5, 8' → 0-based 쪽 목록(정렬·중복 제거). 범위를 벗어난 것은 버린다."""
    out = set()
    for part in re.split(r"[,\s]+", (text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*[-~]\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            out.update(range(max(1, a), min(n, b) + 1))
        elif part.isdigit():
            if 1 <= int(part) <= n:
                out.add(int(part))
    return sorted(p - 1 for p in out)


# ── 계산 ──────────────────────────────────────────────────────────
def _native_box(page, key):
    """페이지(또는 물려받은 부모)의 상자 — PDF 본래 좌표 [x0,y0,x1,y1](왼쪽 아래 원점)."""
    doc = page.parent
    xref = page.xref
    for _ in range(32):
        t, v = doc.xref_get_key(xref, key)
        if t == "array":
            nums = [float(x) for x in re.findall(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", v)][:4]
            if len(nums) == 4:
                x0, y0, x1, y1 = nums
                return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        pt, pv = doc.xref_get_key(xref, "Parent")
        if pt != "xref":
            break
        xref = int(pv.split()[0])
    return None


def _clip(box, mb):
    return [max(box[0], mb[0]), max(box[1], mb[1]), min(box[2], mb[2]), min(box[3], mb[3])]


def _to_unrotated(margins, rotation):
    """보이는 방향의 [위,아래,왼,오른] → 회전 전 쪽의 [위,아래,왼,오른]."""
    t, b, l, r = margins
    rot = rotation % 360
    if rot == 90:        # 보이는 위 = 회전 전 왼, 보이는 오른 = 회전 전 위
        return [r, l, t, b]
    if rot == 180:
        return [b, t, r, l]
    if rot == 270:       # 보이는 위 = 회전 전 오른, 보이는 왼 = 회전 전 위
        return [l, r, b, t]
    return [t, b, l, r]


def crop_box(page, margins_pct) -> list:
    """보이는 방향 여백(%) → PDF 본래 좌표 CropBox [x0,y0,x1,y1]."""
    mb = _native_box(page, "MediaBox") or [page.mediabox.x0, page.mediabox.y0,
                                           page.mediabox.x1, page.mediabox.y1]
    ut, ub, ul, ur = (max(0.0, min(CROP_MAX, float(v))) / 100.0 for v in _to_unrotated(margins_pct, page.rotation))
    w, h = mb[2] - mb[0], mb[3] - mb[1]
    return [mb[0] + ul * w, mb[1] + ub * h, mb[2] - ur * w, mb[3] - ut * h]


def detect_margins(page) -> list | None:
    """흰 여백 감지 — 보이는 방향 [위,아래,왼,오른] %(내용 경계까지). 내용이 없으면 None.
    쪽 전체(MediaBox)를 보도록 렌더 전에 CropBox 를 잠시 넓힌다 — 이 문서는 저장하지 않는 사본이어야 한다."""
    mb = _native_box(page, "MediaBox")
    old = page.parent.xref_get_key(page.xref, "CropBox")
    if mb:
        page.parent.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % tuple(mb))
    try:
        rw = page.rect.width or 1
        pix = page.get_pixmap(matrix=fitz.Matrix(DETECT_W / rw, DETECT_W / rw), colorspace=fitz.csGRAY, alpha=False)
    finally:
        if mb:
            page.parent.xref_set_key(page.xref, "CropBox", old[1] if old[0] != "null" else "null")
    W, H, stride, data = pix.width, pix.height, pix.stride, pix.samples
    if W < 2 or H < 2:
        return None
    table = bytes(1 if i < WHITE else 0 for i in range(256))
    top = bot = None
    left, right = W, -1
    for y in range(H):
        row = data[y * stride:y * stride + W].translate(table)
        i = row.find(b"\x01")
        if i < 0:
            continue
        j = row.rfind(b"\x01")
        if top is None:
            top = y
        bot = y
        left, right = min(left, i), max(right, j)
    if top is None:
        return None
    return [top / H * 100.0, (H - 1 - bot) / H * 100.0, left / W * 100.0, (W - 1 - right) / W * 100.0]


def margins_for(page, page_index: int, style: dict) -> list | None:
    """이 쪽에 쓸 보이는 방향 여백(%) — 자동 감지면 내용 경계 − 남길 여백, 홀짝 대칭이면 짝수 쪽 좌우를 바꾼다.
    None = 자르지 않는다(자동 감지에서 내용이 없는 쪽)."""
    st = norm_style(style)
    m = list(st["margins"])
    if st["auto"]:
        d = detect_margins(page)
        if d is None:
            return None
        m = [max(0.0, d[i] - m[i]) for i in range(4)]
    if st["mirror"] and (page_index + 1) % 2 == 0:
        m[2], m[3] = m[3], m[2]
    return [max(0.0, min(CROP_MAX, v)) for v in m]


def assign_styles(doc, pages, styles, auto: dict, chosen_id: str) -> dict:
    """{쪽: 스타일} — 자동 적용이면 쪽 방향으로, 아니면 고른 스타일 하나."""
    by = {s["id"]: s for s in styles}
    one = by.get(chosen_id) or styles[0]
    out = {}
    for p in pages:
        if auto.get("on"):
            out[p] = by.get(auto.get(orientation(doc[p])), by.get(orientation(doc[p]), one))
        else:
            out[p] = one
    return out


def set_crop(page, box):
    page.parent.xref_set_key(page.xref, "CropBox", "[%g %g %g %g]" % tuple(box))


def reset_crop(page):
    mb = _native_box(page, "MediaBox")
    if mb:
        set_crop(page, mb)


def build(src, out, pages, styles_by_page: dict | None, reset: bool = False, progress=None) -> dict:
    """원본을 열어 대상 쪽의 CropBox 를 고친 **임시 PDF** 를 `out` 에 쓴다(배경에서).
    `progress(done, total, phase) -> False` 면 취소(phase = "crop"|"save", 화면 글자는 호출부가). 돌려줌: {path, changed}."""
    src, out = Path(src), Path(out)
    doc = fitz.open(str(src))
    changed = 0
    try:
        total = len(pages)
        for k, p in enumerate(pages):
            if progress is not None and progress(k, total, "crop") is False:
                raise Cancelled()
            if not (0 <= p < doc.page_count):
                continue
            page = doc[p]
            if reset:
                reset_crop(page); changed += 1
                continue
            m = margins_for(page, p, styles_by_page[p])
            if m is None:
                continue
            set_crop(page, crop_box(page, m)); changed += 1
        if progress is not None:
            progress(total, total, "save")
        doc.save(str(out), garbage=1, deflate=True)
    except Cancelled:
        doc.close()
        try:
            out.unlink()
        except Exception:
            pass
        raise
    doc.close()
    return {"path": str(out), "changed": changed}
