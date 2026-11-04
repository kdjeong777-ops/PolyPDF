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
import os
import struct
from pathlib import Path

ORIENT_TAG = 0x0112
GPS_TAG = 0x8825
# EXIF 방향 → PyMuPDF `insert_image(rotate=)`(반시계, 261104-1 실측). 거울 방향은 None — 다시 그린다
ROTATE_FOR = {1: 0, 3: 180, 6: 270, 8: 90}
MIRRORED = {2, 4, 5, 7}
REENCODE_QUALITY = 95                         # 거울 방향·HEIC — 다시 그릴 때 JPEG 화질
HEIF_EXTS = (".heic", ".heif")
_HEIF_STATE = {"tried": False, "ok": False}


# 아이폰은 HEIC 를 **.JPG 이름으로** 내보내기도 한다(사용자 표본 `_samples\pix` 51장 중 25장, 261104-2) — 확장자가 아니라 머리를 본다
_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1")


def is_heif(path) -> bool:
    """HEIC/HEIF 인가 — 확장자 또는 **파일 머리**(ISO BMFF `ftyp` 의 HEIF 상표). 머리는 16바이트만 읽는다."""
    if Path(str(path)).suffix.lower() in HEIF_EXTS:
        return True
    try:
        with open(str(path), "rb") as fh:
            head = fh.read(16)
    except OSError:
        return False
    return len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS


def heif_ready() -> bool:
    """HEIC 해독기(pi-heif, 읽기 전용 — 사진 보기 SOT 4.9·D5)를 **처음 만날 때 한 번** Pillow 에 등록한다.
    시작·PDF 모드에는 불러오지 않는다(§6.1). 없으면(휴대용 판에서 빠졌을 때 등) False — 목록에는 보이고 열 때 알린다."""
    if not _HEIF_STATE["tried"]:
        _HEIF_STATE["tried"] = True
        try:
            import pi_heif
            pi_heif.register_heif_opener()
            _HEIF_STATE["ok"] = True
        except Exception:
            _HEIF_STATE["ok"] = False
    return _HEIF_STATE["ok"]


def _prep(path) -> None:
    if is_heif(path):
        heif_ready()


def orientation(path) -> int:
    """EXIF 방향(1~8). 없거나 못 읽으면 1."""
    _prep(path)
    try:
        from PIL import Image
        with Image.open(str(path)) as im:
            o = int(im.getexif().get(ORIENT_TAG, 1) or 1)
        return o if 1 <= o <= 8 else 1
    except Exception:
        return 1


def oriented_size(path) -> tuple:
    """보이는 대로의 (폭, 높이) 픽셀 — **머리만** 읽는다. 못 읽으면 (0, 0)."""
    _prep(path)
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


# ── 방향 저장(D17, 사진 보기 SOT 4.17 — 다시 압축하지 않음) ─────────────────────
# 방향 = (거울?, 시계 방향 회전) — 거울 방향은 '좌우 뒤집은 뒤 돌리기' 로 본다(EXIF 2·7·4·5 = 뒤집기 + 0·90·180·270)
_ORIENT_PARTS = {1: (False, 0), 6: (False, 90), 3: (False, 180), 8: (False, 270),
                 2: (True, 0), 7: (True, 90), 4: (True, 180), 5: (True, 270)}
_PARTS_ORIENT = {v: k for k, v in _ORIENT_PARTS.items()}


def compose_orientation(orient: int, rot_cw: int) -> int:
    """지금 EXIF 방향 다음에 시계 방향 `rot_cw` 도를 더 돌린 EXIF 방향."""
    mirror, r = _ORIENT_PARTS.get(int(orient) if orient else 1, (False, 0))
    return _PARTS_ORIENT[(mirror, (r + int(rot_cw)) % 360)]


def _jpeg_segments(buf):
    """(표지, 시작, 끝) — 머리 묶음들(SOS 전까지). SOS 는 (0xDA, 시작, None)."""
    i = 2
    while i + 4 <= len(buf) and buf[i] == 0xFF:
        marker = buf[i + 1]
        if marker == 0xFF:                                  # 채움 바이트
            i += 1
            continue
        if marker == 0xDA:
            yield marker, i, None
            return
        if marker == 0xD9:
            return
        seg = struct.unpack_from(">H", buf, i + 2)[0]
        yield marker, i, i + 2 + seg
        i += 2 + seg


def jpeg_scan_data(data: bytes) -> bytes:
    """그림 자료(SOS 부터 끝까지) — 방향 저장 뒤 픽셀이 그대로인지 견줄 때."""
    for marker, start, _end in _jpeg_segments(data):
        if marker == 0xDA:
            return bytes(data[start:])
    return b""


def _patch_orient_in_tiff(t: bytearray, value: int) -> bool:
    """TIFF(EXIF 본체) IFD0 의 방향 항목 값을 그 자리에서 바꾼다. 항목이 있으면 True."""
    if len(t) < 8 or t[:2] not in (b"II", b"MM"):
        return False
    e = "<" if t[:2] == b"II" else ">"
    try:
        ifd0 = struct.unpack_from(e + "I", t, 4)[0]
        n = struct.unpack_from(e + "H", t, ifd0)[0]
        for k in range(n):
            at = ifd0 + 2 + 12 * k
            tag, typ, num = struct.unpack_from(e + "HHI", t, at)
            if tag == ORIENT_TAG:
                if typ != 3 or num != 1:                    # SHORT 하나가 아니면 손대지 않는다(다시 짓는다)
                    return False
                struct.pack_into(e + "HH", t, at + 8, int(value), 0)
                return True
    except struct.error:
        return False
    return False


def jpeg_set_orientation(data: bytes, value: int) -> bytes | None:
    """JPEG 바이트의 EXIF 방향만 `value` 로(D17). 그림 자료·다른 묶음은 그대로. JPEG 이 아니면 None.
    태그가 있으면 그 자리에서 값만(길이 그대로), EXIF 는 있는데 태그가 없으면 그 EXIF 묶음만 다시 짓고, EXIF 가 없으면 새로 넣는다."""
    if data[:2] != b"\xff\xd8" or not 1 <= int(value) <= 8:
        return None
    buf = bytearray(data)
    app1 = None
    after_app0 = 2
    for marker, start, end in _jpeg_segments(buf):
        if end is None:
            break
        if marker == 0xE0 and start == after_app0:
            after_app0 = end                                 # JFIF 뒤에 넣는다(JFIF 는 맨 앞이어야 한다)
        if marker == 0xE1 and buf[start + 4:start + 10] == b"Exif\x00\x00":
            app1 = (start, end)
            break
    if app1 is not None:
        start, end = app1
        tiff = bytearray(buf[start + 10:end])
        if _patch_orient_in_tiff(tiff, value):
            buf[start + 10:end] = tiff
            return bytes(buf)
    from PIL import Image
    ex = Image.Exif()
    if app1 is not None:
        try:
            ex.load(bytes(buf[app1[0] + 4:app1[1]]))
        except Exception:
            return None                                      # 읽을 수 없는 EXIF — 망가뜨리지 않는다
    ex[ORIENT_TAG] = int(value)
    payload = ex.tobytes()
    if not payload.startswith(b"Exif\x00\x00"):
        payload = b"Exif\x00\x00" + payload
    if len(payload) + 2 > 0xFFFF:
        return None
    seg = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    if app1 is not None:
        return bytes(buf[:app1[0]]) + seg + bytes(buf[app1[1]:])
    return bytes(buf[:after_app0]) + seg + bytes(buf[after_app0:])


def is_jpeg_file(path) -> bool:
    """진짜 JPEG 인가(머리 FF D8 FF) — `.JPG` 이름의 HEIC·동영상을 거른다."""
    try:
        with open(str(path), "rb") as f:
            return f.read(3) == b"\xff\xd8\xff"
    except OSError:
        return False


# ── 읽을 수 없는 파일의 까닭·사진 정보 (사진 보기 SOT 4.18, 261104-3 사용자 지시) ─────────────
UNREADABLE_VIDEO = "video"         # 동영상(QuickTime·MP4)이 그림 이름으로 — 아이폰 라이브 포토의 영상 등
UNREADABLE_EMPTY = "empty"         # 빈 파일
UNREADABLE_TRUNCATED = "truncated"  # 그림 머리는 맞는데 자료가 잘림·깨짐
UNREADABLE_OTHER = "other"         # 그림 형식이 아니거나 알 수 없는 까닭
_QT_ATOMS = (b"wide", b"mdat", b"moov", b"free", b"skip", b"pnot")
_VIDEO_BRANDS = (b"qt  ", b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"3gp4", b"3gp5")


def unreadable_reason(path) -> str:
    """그림으로 열리지 않는 파일의 까닭(위 상수 중 하나) — 머리 몇 바이트만 본다."""
    try:
        with open(str(path), "rb") as f:
            head = f.read(32)
    except OSError:
        return UNREADABLE_OTHER
    if not head:
        return UNREADABLE_EMPTY
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in _VIDEO_BRANDS:
        return UNREADABLE_VIDEO
    if len(head) >= 8 and head[4:8] in _QT_ATOMS:            # ftyp 없이 시작하는 QuickTime(사용자 표본 IMG_9298 — 'wide' 다음 'mdat')
        return UNREADABLE_VIDEO
    if head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n":
        return UNREADABLE_TRUNCATED
    return UNREADABLE_OTHER


_EXIF_IFD = 0x8769
_TAG_NAMES = {0x010F: "Make", 0x0110: "Model", 0x0131: "Software", 0x0132: "DateTime", 0x9003: "DateTimeOriginal",
              0x829A: "ExposureTime", 0x829D: "FNumber", 0x8827: "ISOSpeedRatings", 0x920A: "FocalLength",
              0xA405: "FocalLengthIn35mmFilm", 0xA434: "LensModel", 0x9209: "Flash", 0xA402: "ExposureMode",
              0xA403: "WhiteBalance", 0x0112: "Orientation", 0xA001: "ColorSpace"}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return float(v[0]) / float(v[1])
        except Exception:
            return None


def photo_info(path) -> dict:
    """사진 정보 — 배경에서 부른다(머리만 읽는다). 키: taken·width·height·bytes·camera·format·exif(태그 이름 → 값 글)·gps((위도, 경도) 또는 None)·icc(프로필 이름)."""
    info = {"taken": "", "width": 0, "height": 0, "bytes": 0, "camera": "", "format": "", "exif": {}, "gps": None, "icc": ""}
    try:
        info["bytes"] = os.path.getsize(str(path))
    except OSError:
        pass
    _prep(path)
    from PIL import Image
    with Image.open(str(path)) as im:
        info["format"] = "HEIC" if is_heif(path) else (im.format or "")
        ex = im.getexif()
        o = int(ex.get(ORIENT_TAG, 1) or 1)
        w, h = im.size
        info["width"], info["height"] = ((h, w) if o in (5, 6, 7, 8) else (w, h))
        sub = {}
        try:
            sub = ex.get_ifd(_EXIF_IFD) or {}
        except Exception:
            pass
        for src in (ex, sub):
            for tag, name in _TAG_NAMES.items():
                v = src.get(tag)
                if v not in (None, "", b""):
                    info["exif"][name] = str(v).strip("\x00 ")
        info["taken"] = (info["exif"].get("DateTimeOriginal") or info["exif"].get("DateTime") or "")
        info["camera"] = " ".join(x for x in (info["exif"].get("Make", ""), info["exif"].get("Model", "")) if x).strip()
        try:
            g = ex.get_ifd(GPS_TAG) or {}
            if g.get(2) and g.get(4):
                def dms(t):
                    d, m, s = (_num(x) or 0.0 for x in t)
                    return d + m / 60.0 + s / 3600.0
                lat = dms(g[2]) * (-1 if g.get(1) == "S" else 1)
                lon = dms(g[4]) * (-1 if g.get(3) == "W" else 1)
                info["gps"] = (round(lat, 6), round(lon, 6))
        except Exception:
            pass
        icc = im.info.get("icc_profile")
        if icc:
            try:
                from PIL import ImageCms
                info["icc"] = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
            except Exception:
                info["icc"] = "ICC"
    return info


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
    if is_heif(p):
        # PyMuPDF 는 HEIC 를 못 연다(사진 보기 SOT §8.1 ④) — 바로 세워 JPEG 으로 다시 그린다(EXIF·GPS 는 싣지 않는다)
        from PIL import Image, ImageOps
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            out = io.BytesIO()
            im.save(out, "JPEG", quality=REENCODE_QUALITY)
        return out.getvalue(), 0, w, h
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


# ── 색 관리 — 사진에 든 ICC 프로필을 화면용 sRGB 로 (사진 보기 SOT §5.1 F2) ───────────
_CMS: dict = {}                 # 프로필 해시 → 변환(또는 None = sRGB 라 그대로) — 같은 프로필은 한 번만 짓는다
_CMS_LOCK = None


def to_srgb(im, icc: bytes | None = None):
    """Pillow 그림을 sRGB 로 — 프로필이 없거나 sRGB 면 받은 그대로. Adobe RGB·넓은 색역 사진이 물빠져 보이지 않게.
    줄인 뒤의 그림에 부른다(변환 비용은 픽셀 수만큼 — 줄인 그림이면 짧다). 새 의존성 없음(Pillow 동봉 littlecms)."""
    global _CMS_LOCK
    icc = icc if icc is not None else im.info.get("icc_profile")
    if not icc or im.mode not in ("RGB", "RGBA", "CMYK"):
        return im
    import hashlib
    import threading
    from PIL import ImageCms
    if _CMS_LOCK is None:
        _CMS_LOCK = threading.Lock()
    key = (hashlib.sha1(icc).hexdigest(), im.mode)
    with _CMS_LOCK:
        got = _CMS.get(key, False)
    if got is False:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            desc = (ImageCms.getProfileDescription(src) or "").lower()
            if "srgb" in desc and im.mode != "CMYK":
                got = None                                   # 이미 sRGB — 바꾸지 않는다
            else:
                out_mode = "RGBA" if im.mode == "RGBA" else "RGB"
                got = ImageCms.buildTransform(src, ImageCms.createProfile("sRGB"), im.mode, out_mode)
        except Exception:
            got = None                                       # 깨진 프로필 — 그대로 보인다
        with _CMS_LOCK:
            _CMS[key] = got
    if got is None:
        return im
    try:
        return ImageCms.applyTransform(im, got)
    except Exception:
        return im


# ── 화면용 줄여 읽기(배경 스레드) ───────────────────────────────────
def read_scaled(path: str, box: int, auto_transform: bool = False):
    """그림을 **긴 변 `box` 안으로 줄여 읽는다** → (QImage, 원래 폭, 원래 높이). `auto_transform` 이면 EXIF 방향을 적용하고
    폭·높이도 보이는 대로.

    **Pillow 로 읽는다** — Qt 의 `QImageReader.read` 는 디코드하는 동안 GIL 을 쥐어 배경에서도 메인이 섰다
    (24 MP 20장 최장 1.28초, 응답성 SOT §6). Pillow 해독기는 GIL 을 놓고 JPEG 은 draft 로 디코드 단계에서 줄인다.
    Pillow 가 모르는 형식만 Qt 로."""
    _prep(path)
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
        icc = im.info.get("icc_profile")
        if auto_transform and int(im.getexif().get(ORIENT_TAG, 1) or 1) in (5, 6, 7, 8):
            w, h = h, w
        im.draft("RGB", (box, box))                      # JPEG: 디코드 단계에서 줄인다
        im = ImageOps.exif_transpose(im) if auto_transform else im
        im.thumbnail((box, box))
        if auto_transform:
            im = to_srgb(im, icc)                        # 화면용(방향을 세우는 길)이면 색 관리(F2) — 썸네일·본문·이미지→PDF 창 미리보기
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        fmt = QImage.Format.Format_RGBA8888 if im.mode == "RGBA" else QImage.Format.Format_RGB888
        data = im.tobytes()
        qi = QImage(data, im.width, im.height, im.width * len(im.mode), fmt).copy()
    return qi, w, h
