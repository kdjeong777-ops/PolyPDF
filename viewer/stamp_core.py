# -*- coding: utf-8 -*-
"""등록 이미지 만들기·그리기·자리 계산 (261101-3, 마스터 §4.6.11). Qt 를 쓰지 않는다(PyMuPDF·Pillow).

- PDF 영역 → 벡터 조각(1쪽 PDF) 또는 바탕 투명 그림
- 넣을 때의 그림(`compose`) — 날짜 글자를 벡터 조각에는 글자로, 그림에는 그림 해상도로
- 자리 계산 — 실제 mm 크기, 쪽 밖이면 줄이고 안으로, 여러 쪽은 가까운 모서리 기준
"""
from __future__ import annotations

import io

PT_PER_MM = 72.0 / 25.4
REGION_DPI = 600          # 글자층 없는 영역을 그림으로 뜰 때
PREVIEW_LONG = 1200       # 화면용 그림 긴 변(px) — `MainView.add_image_from_pixmap` 상한과 같다
DATE_FILL = 0.78          # 날짜 글자 높이 = 날짜 상자 높이 × 이 값(넘치면 폭에 맞춰 더 줄인다)


# ── PDF 영역 ────────────────────────────────────────────────────────────────

def region_has_text(page, clip) -> bool:
    """보이는 좌표(`page.rect` 기준) 영역에 글자층이 있나."""
    import fitz
    try:
        raw = fitz.Rect(clip) * page.derotation_matrix      # get_text 의 clip 은 회전 전 좌표(실측 — get_pixmap 은 보이는 좌표)
        raw.normalize()
        return bool(page.get_text("words", clip=raw))
    except Exception:
        return False


def region_piece(doc, pno: int, clip) -> bytes:
    """보이는 좌표 영역만 담은 1쪽 PDF(벡터). 쪽 크기 = 영역 크기(pt) — 회전한 쪽이면 보이는 방향으로 선다."""
    import fitz
    from viewer import pdf_font
    src = doc[pno]
    clip = fitz.Rect(clip) & src.rect
    if clip.is_empty:
        raise ValueError("empty clip")
    raw = clip * src.derotation_matrix            # show_pdf_page 의 clip 은 회전 전 좌표(실측)
    raw.normalize()
    out = fitz.open()
    pg = out.new_page(width=clip.width, height=clip.height)
    pg.show_pdf_page(pg.rect, doc, pno, clip=raw, rotate=-int(src.rotation) % 360)
    pdf_font.subset_fonts_safely(out)
    data = out.tobytes(garbage=4, deflate=True, clean=True)
    out.close()
    return data


def region_png(page, clip, dpi: int = REGION_DPI, long_px: int = 2400):
    """보이는 좌표 영역을 그림으로(Pillow RGB). 바탕 투명은 `clean` 이 한다.
    긴 변이 `long_px` 를 넘지 않게 해상도를 낮춘다 — 쪽 전체를 600dpi 로 뜨면 메인이 1초 넘게 섰다(응답성 SOT §5)."""
    import fitz
    from PIL import Image
    c = fitz.Rect(clip)
    dpi = max(72, min(int(dpi), int(long_px * 72 / max(1.0, c.width, c.height))))
    pix = page.get_pixmap(clip=c, dpi=dpi, alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def content_clip(page):
    """쪽에서 무엇이 그려진 경계(보이는 좌표) — PDF 파일의 쪽을 등록할 때 여백을 뺀다. 없으면 쪽 전체."""
    import fitz
    box = fitz.Rect()
    full = page.rect
    try:
        for _kind, r in page.get_bboxlog():
            r = fitz.Rect(r) * page.rotation_matrix if page.rotation else fitz.Rect(r)
            r.normalize()
            if r.is_empty or (r.width >= full.width * 0.98 and r.height >= full.height * 0.98):
                continue                          # 쪽 전체 바탕 칠은 내용이 아니다
            box = fitz.Rect(r) if box.is_empty else box | r
    except Exception:
        pass
    box &= full
    return full if box.is_empty else box + (-2, -2, 2, 2) & full


def piece_size_pt(pdf_bytes: bytes):
    import fitz
    with fitz.open(stream=pdf_bytes, filetype="pdf") as d:
        r = d[0].rect
        return float(r.width), float(r.height)


def render_piece(pdf_bytes: bytes, long_px: int = PREVIEW_LONG) -> bytes:
    """벡터 조각 → 투명 바탕 PNG 바이트(화면용)."""
    import fitz
    with fitz.open(stream=pdf_bytes, filetype="pdf") as d:
        r = d[0].rect
        z = long_px / max(1.0, max(r.width, r.height))
        return d[0].get_pixmap(matrix=fitz.Matrix(z, z), alpha=True).tobytes("png")


# ── 그림 ────────────────────────────────────────────────────────────────────

def clean(img, threshold=None, ink: str = "original"):
    """바탕 투명·잉크 색·자르기 — 서명 그림과 같은 정리(보안 SOT §3.1)."""
    from viewer import sign_core
    return sign_core.clean_signature(img, threshold=threshold, ink=ink)


def recolor(img, rgb):
    """잉크 색을 한 색으로(알파는 그대로)."""
    from PIL import Image
    img = img.convert("RGBA")
    solid = Image.new("RGBA", img.size, tuple(rgb) + (0,))
    solid.putalpha(img.getchannel("A"))
    return solid


def ink_color(img) -> str:
    """보이는(알파 128 넘는) 점들의 평균색 '#rrggbb' — 날짜 글자 기본색."""
    img = img.convert("RGBA")
    small = img.copy()
    small.thumbnail((200, 200))
    n = r = g = b = 0
    for (pr, pg, pb, pa) in small.getdata():
        if pa > 128:
            n += 1; r += pr; g += pg; b += pb
    if not n:
        return "#000000"
    return "#%02x%02x%02x" % (r // n, g // n, b // n)


def png_bytes(img) -> bytes:
    bio = io.BytesIO()
    img.save(bio, "PNG", optimize=True)
    return bio.getvalue()


# ── 넣을 때의 그림 ──────────────────────────────────────────────────────────

def _hex_rgb(h: str):
    h = (h or "#000000").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _date_color(entry, payload_img_or_none) -> str:
    c = (entry.get("date") or {}).get("color") or ""
    if c:
        return c
    return ink_color(payload_img_or_none) if payload_img_or_none is not None else "#000000"


def compose(entry: dict, payload: bytes, when=None) -> dict:
    """넣을 그림 → {"png": 화면용 PNG, "pdf": 벡터 조각(벡터일 때만) | None, "aspect": 높이/폭}.
    날짜를 켰으면 오늘(또는 `when`) 날짜를 지금 그려 넣는다 — 넣은 뒤에는 바뀌지 않는다."""
    from viewer import stamp_store
    from PIL import Image
    date = stamp_store.norm_date(entry.get("date"))
    text = stamp_store.date_text(date["fmt"], when) if date["on"] else ""
    if entry.get("kind") == "pdf":
        import fitz
        from viewer import pdf_font
        doc = fitz.open(stream=payload, filetype="pdf")
        pg = doc[0]
        W, H = pg.rect.width, pg.rect.height
        if text:
            col = date["color"]
            if not col:
                col = ink_color(Image.open(io.BytesIO(render_piece(payload, 400))))
            ff = pdf_font.text_font_file()
            bx, by, bw, bh = date["box"]
            box = fitz.Rect(bx * W, by * H, (bx + bw) * W, (by + bh) * H)
            fname = pdf_font.fresh_font_name(pg, "stampdt")
            font = fitz.Font(fontfile=ff) if ff else fitz.Font("helv")
            size = _fit_size(font, text, box.width, box.height)
            tw = font.text_length(text, fontsize=size)
            x = box.x0 + (box.width - tw) / 2
            y = box.y0 + (box.height + size * 0.72) / 2       # 대문자·한글 높이 ≈ 0.72em 를 상자 가운데로
            kw = {"fontfile": ff} if ff else {}
            pg.insert_text((x, y), text, fontsize=size, fontname=fname if ff else "helv",
                           color=tuple(v / 255 for v in _hex_rgb(col)), **kw)
            pdf_font.subset_fonts_safely(doc)
            pdf = doc.tobytes(garbage=3, deflate=True)
        else:
            pdf = payload
        doc.close()
        return {"png": render_piece(pdf), "pdf": pdf, "aspect": H / max(1.0, W)}
    img = Image.open(io.BytesIO(payload)).convert("RGBA")
    if max(img.size) > PREVIEW_LONG:
        r = PREVIEW_LONG / max(img.size)
        img = img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))), Image.LANCZOS)
    if text:
        img = _draw_date(img, text, date["box"], _date_color(entry, img))
    return {"png": png_bytes(img), "pdf": None, "aspect": img.height / max(1, img.width)}


def _fit_size(font, text, w, h) -> float:
    size = max(1.0, h * DATE_FILL)
    tw = font.text_length(text, fontsize=size)
    if tw > w * 0.96 and tw > 0:
        size *= (w * 0.96) / tw
    return max(1.0, size)


def _draw_date(img, text, box, color):
    from PIL import ImageDraw, ImageFont
    from viewer import pdf_font
    W, H = img.size
    bx, by, bw, bh = box
    x0, y0, w, h = bx * W, by * H, bw * W, bh * H
    ff = pdf_font.text_font_file()
    d = ImageDraw.Draw(img)

    def _font(px):
        try:
            return ImageFont.truetype(ff, max(1, int(px))) if ff else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()
    px = max(4, h * DATE_FILL)
    f = _font(px)
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    if r - l > w * 0.96 and r > l:
        px *= (w * 0.96) / (r - l)
        f = _font(px)
        l, t, r, b = d.textbbox((0, 0), text, font=f)
    d.text((x0 + (w - (r - l)) / 2 - l, y0 + (h - (b - t)) / 2 - t), text, font=f, fill=_hex_rgb(color) + (255,))
    return img


# ── 자리 ────────────────────────────────────────────────────────────────────

def fit_rect(x_pt, y_pt, w_pt, h_pt, page_w, page_h):
    """(x, y)가 왼쪽 위인 w×h 상자 — 쪽보다 크면 비율대로 줄이고 쪽 안으로 민다. 쪽 비율 [fx, fy, fw, fh]."""
    s = min(1.0, page_w / max(w_pt, 1e-6), page_h / max(h_pt, 1e-6))
    w, h = w_pt * s, h_pt * s
    x = max(0.0, min(page_w - w, x_pt))
    y = max(0.0, min(page_h - h, y_pt))
    return [x / page_w, y / page_h, w / page_w, h / page_h]


def real_rect(fx, fy, width_mm, aspect, page_w, page_h):
    """누른 자리(쪽 비율 fx, fy)가 왼쪽 위인 실제 크기 상자."""
    w = float(width_mm) * PT_PER_MM
    return fit_rect(fx * page_w, fy * page_h, w, w * float(aspect), page_w, page_h)


def same_corner_rect(rect, src_w, src_h, dst_w, dst_h):
    """원래 쪽의 상자 [fx, fy, fw, fh] → 다른 쪽에서 같은 pt 크기, **가장 가까운 모서리**로부터 같은 거리."""
    fx, fy, fw, fh = rect
    w, h = fw * src_w, fh * src_h
    x0, y0 = fx * src_w, fy * src_h
    right = (fx + fw / 2) > 0.5
    bottom = (fy + fh / 2) > 0.5
    s = min(1.0, dst_w / max(w, 1e-6), dst_h / max(h, 1e-6))
    nw, nh = w * s, h * s
    x = dst_w - (src_w - (x0 + w)) - nw if right else x0
    y = dst_h - (src_h - (y0 + h)) - nh if bottom else y0
    return fit_rect(x, y, nw, nh, dst_w, dst_h)
