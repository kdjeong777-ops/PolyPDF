# -*- coding: utf-8 -*-
"""사진 파일 공통 — 머리만 읽기·EXIF 방향·GPS 지우기·PDF 에 넣을 그림 (사진 보기 SOT 4.14 G6·G7, D14·D16).

사진을 다루는 길(이미지→PDF 창·썸네일 사진 끼우기·사진 모드)이 **같은 규칙**을 쓰게 한 곳에 모은다:

- **방향**: 보이는 대로가 맞다(G7). 쪽 크기는 EXIF 방향을 적용한 뒤의 픽셀(D14). JPEG 은 다시 압축하지 않고
  그대로 넣은 뒤 PDF 쪽에서 돌려 세운다(방향 3·6·8). 거울 방향(2·4·5·7)만 다시 그린다.
- **GPS**: 사진 → PDF 에는 촬영 위치를 넣지 않는다(D16). JPEG 의 EXIF 안 GPS 묶음만 그 자리에서 비운다 —
  길이가 바뀌지 않아 다른 EXIF(시각·기기)와 그림 바이트는 그대로다(다시 압축하지 않는다).

Qt 를 쓰지 않는다(배경 스레드·자식 프로세스에서 부른다). `read_scaled` 만 QImage 를 돌려주므로 그 안에서 Qt 를 불러온다.
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

ORIENT_TAG = 0x0112
GPS_TAG = 0x8825
# EXIF 방향 → PyMuPDF `insert_image(rotate=)`(반시계, 261104-1 실측). 거울 방향은 None — 다시 그린다
ROTATE_FOR = {1: 0, 3: 180, 6: 270, 8: 90}
MIRRORED = {2, 4, 5, 7}
REENCODE_QUALITY = 95                         # 거울 방향만 — 다시 그릴 때 JPEG 화질


def orientation(path) -> int:
    """EXIF 방향(1~8). 없거나 못 읽으면 1."""
    try:
        from PIL import Image
        with Image.open(str(path)) as im:
            o = int(im.getexif().get(ORIENT_TAG, 1) or 1)
        return o if 1 <= o <= 8 else 1
    except Exception:
        return 1


def oriented_size(path) -> tuple:
    """보이는 대로의 (폭, 높이) 픽셀 — **머리만** 읽는다. 못 읽으면 (0, 0)."""
    try:
        from PIL import Image
        with Image.open(str(path)) as im:
            w, h = im.size
            o = int(im.getexif().get(ORIENT_TAG, 1) or 1)
        return (h, w) if o in (5, 6, 7, 8) else (w, h)
    except Exception:
        return (0, 0)


# ── GPS 지우기(JPEG, 다시 압축하지 않음) ─────────────────────────────
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


def _blank_gps_in_tiff(t: bytearray) -> bool:
    """TIFF(EXIF 본체) 안 GPS IFD 를 그 자리에서 비운다 — 항목 수 0, 항목·값 바이트는 0 으로. 비웠으면 True."""
    if len(t) < 8 or t[:2] not in (b"II", b"MM"):
        return False
    e = "<" if t[:2] == b"II" else ">"
    try:
        ifd0 = struct.unpack_from(e + "I", t, 4)[0]
        n = struct.unpack_from(e + "H", t, ifd0)[0]
        gps_off = None
        for k in range(n):
            tag = struct.unpack_from(e + "H", t, ifd0 + 2 + 12 * k)[0]
            if tag == GPS_TAG:
                gps_off = struct.unpack_from(e + "I", t, ifd0 + 2 + 12 * k + 8)[0]
                break
        if not gps_off or gps_off + 2 > len(t):
            return False
        cnt = struct.unpack_from(e + "H", t, gps_off)[0]
        for k in range(cnt):
            at = gps_off + 2 + 12 * k
            typ, num = struct.unpack_from(e + "HI", t, at + 2)
            size = _TYPE_SIZE.get(typ, 1) * num
            if size > 4:                                  # 값이 다른 곳에 있다 — 그 바이트도 0 으로
                off = struct.unpack_from(e + "I", t, at + 8)[0]
                if 0 < off and off + size <= len(t):
                    t[off:off + size] = bytes(size)
            t[at:at + 12] = bytes(12)
        struct.pack_into(e + "H", t, gps_off, 0)
        return True
    except struct.error:
        return False


def jpeg_strip_gps(data: bytes) -> bytes:
    """JPEG 바이트에서 EXIF 의 GPS 만 비운다(D16). 길이·그림·다른 EXIF 는 그대로. GPS 가 없으면 받은 그대로."""
    if data[:2] != b"\xff\xd8":
        return data
    buf = bytearray(data)
    i = 2
    while i + 4 <= len(buf) and buf[i] == 0xFF:
        marker = buf[i + 1]
        if marker in (0xD9, 0xDA):                         # 그림 시작 — 머리 끝
            break
        seg = struct.unpack_from(">H", buf, i + 2)[0]
        if marker == 0xE1 and buf[i + 4:i + 10] == b"Exif\x00\x00":
            tiff = bytearray(buf[i + 10:i + 2 + seg])
            if _blank_gps_in_tiff(tiff):
                buf[i + 10:i + 2 + seg] = tiff
        i += 2 + seg
    return bytes(buf)


def has_gps(path) -> bool:
    try:
        from PIL import Image
        with Image.open(str(path)) as im:
            ex = im.getexif()
            return bool(ex.get_ifd(GPS_TAG))
    except Exception:
        return False


# ── PDF 에 넣을 그림 ────────────────────────────────────────────────
def pdf_image(path):
    """사진을 PDF 쪽에 넣을 재료 → (stream 바이트 또는 None, rotate, 보이는 폭, 보이는 높이).

    stream 이 None 이면 파일을 그대로 넣는다(`filename=`). JPEG 은 GPS 를 비운 바이트를 다시 압축 없이,
    방향 3·6·8 은 `rotate` 로 세운다. 거울 방향은 Pillow 로 바로 세워 다시 그린다. 못 읽으면 (None, 0, 0, 0)."""
    p = str(path)
    w, h = oriented_size(p)
    if w <= 0 or h <= 0:
        return None, 0, 0, 0
    o = orientation(p)
    is_jpeg = Path(p).suffix.lower() in (".jpg", ".jpeg")
    if o in MIRRORED:
        from PIL import Image, ImageOps
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im)
            out = io.BytesIO()
            if is_jpeg and im.mode in ("RGB", "L", "CMYK"):
                im.save(out, "JPEG", quality=REENCODE_QUALITY)    # EXIF 를 싣지 않는다 — GPS 도 없다
            else:
                im.save(out, "PNG")
        return out.getvalue(), 0, w, h
    rot = ROTATE_FOR.get(o, 0)
    if is_jpeg:
        try:
            data = Path(p).read_bytes()
        except OSError:
            return None, 0, 0, 0
        return jpeg_strip_gps(data), rot, w, h
    return None, rot, w, h


def insert_photo(page, rect, path) -> bool:
    """`pdf_image` 로 사진 한 장을 쪽의 `rect` 에 넣는다 — 사진 → PDF 의 두 길이 함께 쓴다. 넣었으면 True."""
    import fitz
    stream, rot, w, h = pdf_image(path)
    if w <= 0:
        return False
    if stream is not None:
        page.insert_image(fitz.Rect(*rect), stream=stream, rotate=rot)
    else:
        page.insert_image(fitz.Rect(*rect), filename=str(path), rotate=rot)
    return True


# ── 화면용 줄여 읽기(배경 스레드) ───────────────────────────────────
def read_scaled(path: str, box: int, auto_transform: bool = False):
    """그림을 **긴 변 `box` 안으로 줄여 읽는다** → (QImage, 원래 폭, 원래 높이). `auto_transform` 이면 EXIF 방향을 적용하고
    폭·높이도 보이는 대로.

    **Pillow 로 읽는다** — Qt 의 `QImageReader.read` 는 디코드하는 동안 GIL 을 쥐어 배경에서도 메인이 섰다
    (24 MP 20장 최장 1.28초, 응답성 SOT §6). Pillow 해독기는 GIL 을 놓고 JPEG 은 draft 로 디코드 단계에서 줄인다.
    Pillow 가 모르는 형식만 Qt 로."""
    try:
        return _read_scaled_pil(path, box, auto_transform)
    except Exception:
        pass
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QImageReader, QImageIOHandler
    r = QImageReader(str(path))
    r.setAutoTransform(bool(auto_transform))
    sz = r.size()
    w, h = sz.width(), sz.height()
    if w > 0 and h > 0:
        if auto_transform and r.transformation() & QImageIOHandler.Transformation.TransformationRotate90:
            w, h = h, w
        k = min(1.0, float(box) / max(sz.width(), sz.height()))
        if k < 1.0:
            r.setScaledSize(QSize(max(1, int(sz.width() * k)), max(1, int(sz.height() * k))))
    return r.read(), w, h


def _read_scaled_pil(path: str, box: int, auto_transform: bool):
    from PIL import Image, ImageOps
    from PyQt6.QtGui import QImage
    with Image.open(str(path)) as im:
        w, h = im.size
        if auto_transform and int(im.getexif().get(ORIENT_TAG, 1) or 1) in (5, 6, 7, 8):
            w, h = h, w
        im.draft("RGB", (box, box))                      # JPEG: 디코드 단계에서 줄인다
        im = ImageOps.exif_transpose(im) if auto_transform else im
        im.thumbnail((box, box))
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        fmt = QImage.Format.Format_RGBA8888 if im.mode == "RGBA" else QImage.Format.Format_RGB888
        data = im.tobytes()
        qi = QImage(data, im.width, im.height, im.width * len(im.mode), fmt).copy()
    return qi, w, h
