# -*- coding: utf-8 -*-
"""그림 다듬기 — 바탕 지우기·흑백·색 바꾸기·가리기·밝기 대비·문서 스캔처럼·여백 자르기 (사진 보기 SOT §4.46, 261112-15·-16).

사진 모드 '변환' 창과 스크린샷 '다듬기' 가 함께 쓰는 **계산 한 곳**이다 — Qt 를 쓰지 않는다(Pillow·numpy).
적용 차례는 SOT §4.46 표 그대로: 가리기 → 밝기·대비 → 스캔처럼 → 색 바꾸기 → 바탕 지우기 → 흑백 → 글씨·선 색 → 여백 자르기.
밝은 바탕 문턱은 이미지 넣기·서명 그림과 같은 `sign_core.auto_threshold`(오츠)·같은 부드러운 경계를 쓴다.
"""
from __future__ import annotations

import io

import numpy as np

PREVIEW_SIDE = 900          # 미리보기는 긴 변을 이만큼 줄인 판에서(저장·복사는 전체 해상도)
PREVIEW_DELAY_MS = 150      # 설정을 바꾼 뒤 미리보기를 다시 셈하기까지(창 쪽)
SOFT = 20                   # 문턱 경계를 부드럽게 — sign_core.clean_signature 와 같은 값
COLOR_SOFT = 24             # 누른 색 지우기·색 바꾸기의 허용 범위 바깥 부드러운 띠(RGB 거리)
TOL_DEFAULT = 40            # 허용 범위 기본(RGB 거리, 0~200)
TRIM_MARGIN = 0.02          # 여백 자르기 — 남은 그림 둘레에 긴 변의 이만큼
TRIM_ALPHA = 24             # 이 알파보다 크면 '남은 그림'(sign_core.ink_bbox 와 같음)
AUTO_CUTOFF = 1             # 자동 보정 — 양 끝 % 를 잘라 늘림
SCAN_WHITE = 0.90          # 스캔처럼 — 바탕 밝기의 이 비율 이상은 종이(흰색)
MOSAIC_CELLS = 48          # 모자이크 칸 — 그림 긴 변을 이만큼으로 나눈 크기
INKS = {"black": (0, 0, 0), "blue": (16, 48, 160), "red": (200, 24, 24)}
FORMATS = (("png", "PNG", ".png", True), ("webp", "WebP", ".webp", True), ("jpg", "JPEG", ".jpg", False))   # (키, 이름, 확장자, 투명)

# 단계 번호 — 미리보기에서 색을 누를 때 그 단계 '앞' 그림에서 집는다
ST_MASK, ST_LEVEL, ST_SCAN, ST_SWAP, ST_BG, ST_GRAY, ST_INK, ST_TRIM = range(1, 9)


def default_params() -> dict:
    return {"bg": "none", "threshold": None, "bg_colors": [], "bg_tol": TOL_DEFAULT,
            "gray": "none", "ink": None,
            "swap_from": None, "swap_to": None, "swap_tol": TOL_DEFAULT,
            "trim": False, "scan": False, "auto_level": False, "brightness": 0, "contrast": 0,
            "masks": [], "mask_mode": "mosaic"}


def makes_alpha(p: dict) -> bool:
    """투명이 남는 설정인가 — 그러면 PNG·WebP 로만 저장한다(JPEG 은 투명을 담지 못한다)."""
    return p.get("bg") in ("threshold", "color") and (p.get("bg") != "color" or bool(p.get("bg_colors")))


def is_identity(p: dict) -> bool:
    d = default_params()
    return all(p.get(k, d[k]) == d[k] for k in d if k not in ("bg_tol", "swap_tol", "mask_mode", "threshold"))


def _hex(c):
    if c is None:
        return None
    if isinstance(c, (tuple, list)):
        return tuple(int(v) for v in c[:3])
    s = str(c).lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def ink_rgb(ink):
    """'black'·'blue'·'red'·'#rrggbb'·(r,g,b) → (r,g,b), 없으면 None."""
    if not ink:
        return None
    return INKS.get(ink) or _hex(ink)


def auto_threshold(img) -> int:
    from viewer import sign_core
    return int(sign_core.auto_threshold(img.convert("RGB")))


def _thr_alpha(gray: np.ndarray, thr: int) -> np.ndarray:
    """밝기 → 글씨(앞) 무게 0~1. 문턱보다 SOFT 이상 어두우면 1, 문턱 이상 밝으면 0(서명 그림과 같은 경계)."""
    return np.clip((thr - gray.astype(np.float32)) / SOFT, 0.0, 1.0)


def _dist(rgb: np.ndarray, col) -> np.ndarray:
    d = rgb.astype(np.float32) - np.array(col, dtype=np.float32)
    return np.sqrt((d * d).sum(axis=2))


def _near(rgb: np.ndarray, col, tol: float) -> np.ndarray:
    """그 색에 가까운 정도 0~1 — 허용 범위 안은 1, 바깥 COLOR_SOFT 띠에서 줄어든다."""
    return np.clip((float(tol) + COLOR_SOFT - _dist(rgb, col)) / COLOR_SOFT, 0.0, 1.0)


def _mask_boxes(w, h, masks):
    for m in masks or ():
        try:
            x0, y0, x1, y1 = (float(v) for v in m[:4])
        except Exception:
            continue
        a, b = sorted((x0, x1)), sorted((y0, y1))
        box = (int(a[0] * w), int(b[0] * h), int(round(a[1] * w)), int(round(b[1] * h)))
        if box[2] - box[0] >= 1 and box[3] - box[1] >= 1:
            yield box


def apply(img, p: dict, upto: int = 99):
    """그림(Pillow) → 다듬은 RGBA 그림. `upto` 단계 **앞**까지만(미리보기에서 색을 집을 때)."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    d = default_params()
    d.update(p or {})
    p = d
    img = img.convert("RGBA")
    w, h = img.size
    # 1 가리기
    if upto > ST_MASK and p["masks"]:
        cell = max(4, int(max(w, h) / MOSAIC_CELLS))
        for box in _mask_boxes(w, h, p["masks"]):
            if p["mask_mode"] == "black":
                img.paste((0, 0, 0, 255), box)
            else:
                part = img.crop(box)
                sw, sh = max(1, part.width // cell), max(1, part.height // cell)
                part = part.resize((sw, sh), Image.Resampling.BILINEAR).resize(part.size, Image.Resampling.NEAREST)
                img.paste(part, box)
    alpha = img.getchannel("A")
    rgb = img.convert("RGB")
    # 2 밝기·대비
    if upto > ST_LEVEL:
        if p["auto_level"]:
            rgb = ImageOps.autocontrast(rgb, cutoff=AUTO_CUTOFF)
        if int(p["brightness"]):
            rgb = ImageEnhance.Brightness(rgb).enhance(max(0.0, 1.0 + int(p["brightness"]) / 100.0))
        if int(p["contrast"]):
            rgb = ImageEnhance.Contrast(rgb).enhance(max(0.0, 1.0 + int(p["contrast"]) / 100.0))
    # 3 문서 스캔처럼 — 큰 흐림으로 바탕 밝기를 구해 나눈다(그림자·누런 종이 고르게) → 대비
    if upto > ST_SCAN and p["scan"]:
        g = rgb.convert("L")
        small = g.resize((max(1, w // 8), max(1, h // 8)), Image.Resampling.BILINEAR)
        bgl = small.filter(ImageFilter.GaussianBlur(radius=max(2, max(small.size) / 30))).resize((w, h), Image.Resampling.BILINEAR)
        ga = np.asarray(g, dtype=np.float32)
        ba = np.maximum(np.asarray(bgl, dtype=np.float32), 1.0)
        norm = np.clip(ga / ba * 255.0, 0, 255)
        # 종이(바탕 밝기의 SCAN_WHITE 이상)는 흰색으로, 가장 어두운 1% 를 검정으로 늘린다 — 자동 대비(autocontrast)는 종이 띠(248~255)를
        #   통째로 늘려 그림자 쪽을 다시 회색으로 만들었다(검사 A)
        lo = min(float(np.percentile(norm, 1)), 128.0)
        out = np.clip((norm - lo) / max(1.0, SCAN_WHITE * 255.0 - lo) * 255.0, 0, 255).astype(np.uint8)
        rgb = Image.fromarray(out, "L").convert("RGB")
    if upto <= ST_SWAP:
        out = rgb.convert("RGBA"); out.putalpha(alpha)
        return out
    arr = np.asarray(rgb, dtype=np.float32).copy()
    a = np.asarray(alpha, dtype=np.float32) / 255.0
    # 4 색 바꾸기 — 고른 색 → 다른 색(밝기 차이는 남긴다)
    src, dst = _hex(p["swap_from"]), _hex(p["swap_to"])
    if src is not None and dst is not None:
        wgt = _near(arr, src, p["swap_tol"])[..., None]
        moved = np.clip(arr + (np.array(dst, np.float32) - np.array(src, np.float32)), 0, 255)
        arr = arr * (1 - wgt) + moved * wgt
    if upto <= ST_BG:
        return _to_img(arr, a)
    # 5 바탕 지우기
    gray_now = arr @ np.array([0.299, 0.587, 0.114], np.float32)
    fg = None                                           # 글씨·선 무게(문턱 기준) — 7 에서 다시 쓴다
    if p["bg"] == "threshold":
        thr = int(p["threshold"]) if p["threshold"] is not None else auto_threshold(_to_img(arr, a))
        fg = _thr_alpha(gray_now, thr)
        a = np.minimum(a, fg)
    elif p["bg"] == "color" and p["bg_colors"]:
        keep = np.ones_like(a)
        for c in p["bg_colors"]:
            keep = np.minimum(keep, 1.0 - _near(arr, _hex(c), p["bg_tol"]))
        a = np.minimum(a, keep)
    if upto <= ST_GRAY:
        return _to_img(arr, a)
    # 6 흑백
    if p["gray"] in ("gray", "bw"):
        g = arr @ np.array([0.299, 0.587, 0.114], np.float32)
        if p["gray"] == "bw":
            from viewer.sign_core import _otsu
            t = _otsu(np.bincount(np.clip(g, 0, 255).astype(np.uint8).ravel(), minlength=256).tolist())
            g = np.where(g < t, 0.0, 255.0)
        arr = np.repeat(g[..., None], 3, axis=2)
    if upto <= ST_INK:
        return _to_img(arr, a)
    # 7 글씨·선 색 — 바탕을 지웠으면 남은 점 전부, 아니면 문턱보다 어두운 점
    ink = ink_rgb(p["ink"])
    if ink is not None:
        col = np.array(ink, np.float32)
        if makes_alpha(p):
            arr = np.broadcast_to(col, arr.shape).copy()
        else:
            if fg is None:
                g = arr @ np.array([0.299, 0.587, 0.114], np.float32)
                thr = int(p["threshold"]) if p["threshold"] is not None else auto_threshold(_to_img(arr, a))
                fg = _thr_alpha(g, thr)
            wgt = fg[..., None]
            arr = arr * (1 - wgt) + col * wgt
    out = _to_img(arr, a)
    # 8 여백 자르기
    if upto > ST_TRIM and p["trim"] and makes_alpha(p):
        box = content_box(out)
        if box:
            m = int(max(out.size) * TRIM_MARGIN)
            x0, y0, x1, y1 = box
            out = out.crop((max(0, x0 - m), max(0, y0 - m), min(out.width, x1 + m), min(out.height, y1 + m)))
    return out


def _to_img(arr: np.ndarray, a: np.ndarray):
    from PIL import Image
    rgba = np.dstack([np.clip(arr, 0, 255), np.clip(a * 255.0, 0, 255)]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def content_box(img):
    """남은 그림(알파 > TRIM_ALPHA)의 경계, 없으면 None."""
    a = img.getchannel("A")
    return a.point(lambda v: 255 if v > TRIM_ALPHA else 0).getbbox()


def has_content(img) -> bool:
    return content_box(img.convert("RGBA")) is not None


def pick(img, p: dict, x: float, y: float, stage: int):
    """미리보기에서 누른 자리(그림 비율 0~1)의 색 — 그 단계 **앞** 그림에서(앞 단계가 바꾼 색과 맞게). '#rrggbb'."""
    im = apply(img, p, upto=stage).convert("RGB")
    px = im.getpixel((min(im.width - 1, max(0, int(x * im.width))), min(im.height - 1, max(0, int(y * im.height)))))
    return "#%02x%02x%02x" % tuple(px[:3])


def preview_of(img, side: int = PREVIEW_SIDE):
    from PIL import Image
    im = img.copy()
    if max(im.size) > side:
        im.thumbnail((side, side), Image.Resampling.LANCZOS)
    return im


def encode(img, fmt: str) -> bytes:
    """형식 키(png·webp·jpg) → 바이트. JPEG 은 투명을 흰 바탕에 얹는다(창이 투명이면 JPEG 을 막는다)."""
    from PIL import Image
    bio = io.BytesIO()
    if fmt == "jpg":
        im = img.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        bg.save(bio, "JPEG", quality=92)
    elif fmt == "webp":
        img.save(bio, "WEBP", quality=92, method=4)
    else:
        img.save(bio, "PNG", optimize=False)
    return bio.getvalue()


def ext_of(fmt: str) -> str:
    return next((e for k, _n, e, _t in FORMATS if k == fmt), ".png")


def fmt_of_path(path) -> str:
    s = str(path).lower()
    return "jpg" if s.endswith((".jpg", ".jpeg", ".heic", ".heif")) else ("webp" if s.endswith(".webp") else "png")


def load_visible(path, rot: int = 0, crop=None):
    """보이는 그대로(EXIF 방향·보기 크롭·보기 회전) — 일괄 작업(사진 보기 SOT §4.30)과 같은 읽기. 배경에서 부른다."""
    from PIL import Image, ImageOps
    from viewer import photo_io, photo_doc
    from viewer.photo_crop import crop_pil
    photo_io._prep(path)
    with Image.open(str(path)) as im:
        icc = im.info.get("icc_profile")
        keep_a = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
        im = ImageOps.exif_transpose(im)
        if keep_a:
            im = im.convert("RGBA")
        else:
            im = photo_io.to_srgb(im, icc)
        im = photo_doc._rotate(crop_pil(im, crop), int(rot or 0))
        im.load()
    return im
