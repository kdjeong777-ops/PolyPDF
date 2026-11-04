# -*- coding: utf-8 -*-
"""사진 문서 — `PdfDocument` 와 같은 겉면의 사진 한 장 (사진 보기 SOT 4.4 (다), D2·D14, 261104-2).

- **경로는 원본 사진**이다(4.14 G3) — 앱 곳곳의 `.pdf` 가드가 PDF 전용 기능(저장·크롭·색인·텍스트 창 …)을 그대로 끈다.
- 쪽은 **사진 크기의 빈 1쪽**(메모리 PDF, 그림 없음) — 쪽 크기·꾸밈 좌표·영역 캡처·쪽 사각형이 PDF 와 같은 코드로 돈다.
  좌표는 EXIF 방향을 적용한 뒤의 픽셀 = pt(D14) — 한 번 정하면 바꾸지 않는다(`COORD_VERSION`).
- 그림은 **Pillow 로 필요한 크기만큼만** 풀어 준다(`photo_io` 와 같은 길 — 해독 중 GIL 을 놓는다, 응답성 SOT §6).
  PyMuPDF 로 그리지 않는다(배경에서도 GIL 을 쥐어 메인이 섰다 — 사진 보기 SOT §8.1 ②).
  한 번 푼 그림은 사진마다 하나 들고 있다가(`_DECODED`, 최대 `KEEP_DECODED` 장) 배율이 바뀌면 줄이기만 한다.
  다음·이전 사진은 `preload` 로 배경에서 미리 푼다(4.4·§6.4).
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

import fitz

from viewer import photo_io
from viewer.pdf_doc import GLOBAL_PAGE_CACHE, PageCache, RenderedPage, RenderKey

COORD_VERSION = 1           # 사진 쪽 좌표 판(D14: 방향 적용 뒤 픽셀 = pt) — 바꾸면 꾸밈·OCR 자리를 옮기는 길이 필요하다
KEEP_DECODED = 3            # 푼 그림을 들고 있는 장 수 — 지금·앞·뒤(§6.4 '세 장보다 많이 들고 있지 않는다')
PRELOAD_BOX = 2560          # 미리 풀 때 긴 변 — 보통 화면의 쪽 맞춤에 넉넉하다

_DECODED: "OrderedDict[str, tuple]" = OrderedDict()     # 태그 → (PIL 그림, 그 긴 변)
_LOCK = threading.Lock()


def _tag(path: Path) -> str:
    try:
        return "%s|%d" % (path, path.stat().st_mtime_ns)
    except OSError:
        return str(path)


def _decode(path: Path, box: int):
    """긴 변 `box` 이상으로(원본보다 크게는 안 함) 방향을 세워 푼다 — 배경·메인 어디서든(Pillow 는 해독 중 GIL 을 놓는다)."""
    from PIL import Image, ImageOps
    photo_io._prep(path)                                   # HEIC 면 해독기를 처음 한 번 등록
    with Image.open(str(path)) as im:
        icc = im.info.get("icc_profile")
        im.draft("RGB", (box, box))                        # JPEG: 디코드 단계에서 줄인다
        im = ImageOps.exif_transpose(im)
        if max(im.size) > box:
            im.thumbnail((box, box))
        return photo_io.to_srgb(im, icc).convert("RGB")      # 색 관리 — 사진 프로필을 화면 sRGB 로(§5.1 F2)


def decoded(path, box: int):
    """긴 변이 `box` 이상인 푼 그림(가진 것이 작으면 다시 푼다). 들고 있는 장 수는 `KEEP_DECODED`."""
    p = Path(path)
    tag = _tag(p)
    with _LOCK:
        got = _DECODED.get(tag)
        if got is not None:
            _DECODED.move_to_end(tag)
    if got is not None:
        im, have = got
        if have >= box or max(im.size) < have:             # 넉넉하거나, 이미 원본 크기다
            return im
    im = _decode(p, box)
    with _LOCK:
        _DECODED[tag] = (im, box)
        _DECODED.move_to_end(tag)
        while len(_DECODED) > KEEP_DECODED:
            _DECODED.popitem(last=False)
    return im


def decoded_ready(path, box: int):
    """이미 풀어 둔 그림이 `box` 에 넉넉하면 그것, 아니면 None — **기다리지 않는다**(메인 스레드용)."""
    tag = _tag(Path(path))
    with _LOCK:
        got = _DECODED.get(tag)
        if got is not None:
            _DECODED.move_to_end(tag)
    if got is None:
        return None
    im, have = got
    return im if (have >= box or max(im.size) < have) else None


_REQUESTER = {"fn": None}
_ROT_PROVIDER = {"fn": None}


def set_rotation_provider(fn) -> None:
    """사진의 보기 회전(경로 → 0·90·180·270, 시계 방향)을 알려 줄 함수 — 앱이 폴더 사이드카(`photo_rot`)로 넣는다(4.11 '보기 회전')."""
    _ROT_PROVIDER["fn"] = fn


def _view_rotation(path) -> int:
    fn = _ROT_PROVIDER["fn"]
    if fn is None:
        return 0
    try:
        v = int(fn(str(path)) or 0) % 360
    except Exception:
        return 0
    return v if v in (90, 180, 270) else 0


def _rotate(im, rot: int):
    """시계 방향 `rot` 도로 돌린다(PIL 의 ROTATE_n 은 반시계)."""
    if not rot:
        return im
    from PIL import Image
    return im.transpose({90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
                         270: Image.Transpose.ROTATE_90}[rot])


def set_decode_requester(fn) -> None:
    """메인 스레드가 풀리지 않은 사진을 그려야 할 때 부를 함수(경로, 긴 변) — 앱이 배경 해독을 띄우고 끝나면 다시 그린다."""
    _REQUESTER["fn"] = fn


def _provisional(path: Path, tw: int, th: int, rot: int = 0):
    """풀리기 전 임시 그림 — 썸네일 캐시가 있으면 그것을 키우고, 없으면 회색. 렌더 캐시에 넣지 않는다.
    `tw`·`th` 는 돌린 뒤 크기 — 캐시 그림(방향만 세운 것)을 돌려 맞춘다."""
    from PIL import Image
    try:
        from viewer.widgets.photo_strip import cache_dir, cache_key
        key = cache_key(str(path))
        f = cache_dir() / (key + ".jpg") if key else None
        if f is not None and f.is_file():
            with Image.open(str(f)) as im:
                return _rotate(im.convert("RGB"), rot).resize((tw, th))
    except Exception:
        pass
    return Image.new("RGB", (tw, th), (128, 128, 128))


def preload(path, box: int = PRELOAD_BOX) -> None:
    """배경 스레드에서 부른다 — 다음·이전 사진을 미리 풀어 둔다. 실패는 조용히(보일 때 다시 푼다)."""
    try:
        decoded(path, box)
    except Exception:
        pass


def forget_decoded() -> None:
    with _LOCK:
        _DECODED.clear()


class PhotoFormatMissing(ValueError):
    """이 형식(HEIC)을 읽는 구성 요소가 없다 — 목록에는 보이고 열 때 알린다(사진 보기 SOT 4.9)."""


class PhotoDocument:
    """`PdfDocument` 의 겉면(본문·썸네일·캡처가 부르는 것)만 가진 사진 한 장."""

    is_photo = True

    def __init__(self, file_path, cache: PageCache | None = None):
        self.path = Path(file_path)
        w, h = photo_io.oriented_size(self.path)
        if w <= 0 or h <= 0:
            if photo_io.is_heif(self.path) and not photo_io.heif_ready():
                raise PhotoFormatMissing(str(self.path))
            raise ValueError("그림을 읽을 수 없다: %s" % self.path)
        # 보기 회전(261104-3, 4.11): 쪽 자체를 돌린다 — 꾸밈 겹(선·하이퍼링크·서명 자리)이 쪽 사각형을 따라가도록
        #   본문 화면을 돌리지 않고 쪽 크기를 바꾼다. 좌표 판(D14, `COORD_VERSION`)은 **회전 0** 기준 그대로다.
        self.rotation = _view_rotation(self.path)
        if self.rotation in (90, 270):
            w, h = h, w
        self.size = (int(w), int(h))
        self.doc = fitz.open()
        self.doc.new_page(width=float(w), height=float(h))   # 그림 없는 빈 쪽 — 좌표·사각형만
        self.cache = cache or GLOBAL_PAGE_CACHE
        self._cache_tag = "photo|%s|r%d" % (_tag(self.path), self.rotation)

    # ── PdfDocument 겉면 ──────────────────────────────
    @property
    def needs_password(self) -> bool:
        return False

    def authenticate(self, password: str) -> bool:
        return True

    def __len__(self) -> int:
        return 1

    @property
    def page_count(self) -> int:
        return 1

    def extract_text(self, page_index: int) -> str:
        return ""

    def iter_pages_text(self):
        yield 0, ""

    def search(self, query: str, mode=None) -> list:
        return []

    def search_pages(self, query: str, mode=None, pages=()) -> list:
        return []

    def search_page(self, page_index: int, query: str, mode=None) -> list:
        return []

    def _flat_page(self, i: int, page=None) -> str:
        return ""

    def render(self, page_index: int, *, base_dpi: int = 192, scale: float = 1.0, rgba: bool = False,
               dpi: int | None = None, cache: bool = True) -> RenderedPage:
        eff = int(dpi) if dpi is not None else round(base_dpi * scale)
        return self._render(max(1, eff) / 72.0, cache=cache)

    def render_scaled(self, page_index: int, physical_scale: float) -> RenderedPage:
        return self._render(max(0.01, min(20.0, float(physical_scale))), cache=True)

    def render_thumbnail(self, page_index: int, dpi: int = 48) -> RenderedPage:
        return self._render(dpi / 72.0, cache=False)

    def points_to_pixels(self, rect, dpi: int) -> tuple:
        s = dpi / 72
        if isinstance(rect, fitz.Rect):
            return (rect.x0 * s, rect.y0 * s, rect.x1 * s, rect.y1 * s)
        x0, y0, x1, y1 = rect
        return (x0 * s, y0 * s, x1 * s, y1 * s)

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── 그리기 ─────────────────────────────────────────
    def _render(self, factor: float, cache: bool) -> RenderedPage:
        w, h = self.size
        tw, th = max(1, round(w * factor)), max(1, round(h * factor))
        key = RenderKey(self._cache_tag, 0, int(round(factor * 10000)), False)
        if cache:
            got = self.cache.get(key)
            if got is not None:
                return got
        need = max(tw, th)
        im = decoded_ready(self.path, need)
        if im is None:
            req = _REQUESTER["fn"]
            if req is not None and threading.current_thread() is threading.main_thread():
                # 메인에서 큰 사진(HEIC 24 MP 0.7~0.9초, 사용자 표본)을 풀지 않는다 — 임시 그림을 주고 배경에 맡긴다(응답성 SOT §6)
                req(self.path, need)
                tmp = _provisional(self.path, tw, th, self.rotation)
                return RenderedPage(width=tw, height=th, samples=tmp.tobytes(), page_rect=(0.0, 0.0, float(w), float(h)))
            im = decoded(self.path, need)
        im = _rotate(im, self.rotation)
        if im.size != (tw, th):
            from PIL import Image
            im = im.resize((tw, th), Image.Resampling.LANCZOS if max(tw, th) < max(im.size) else Image.Resampling.BICUBIC)
        out = RenderedPage(width=tw, height=th, samples=im.tobytes(), page_rect=(0.0, 0.0, float(w), float(h)))
        if cache:
            self.cache.put(key, out)
        return out


def open_document(file_path, cache: PageCache | None = None):
    """경로에 맞는 문서 — 그림(사진 모드의 확장자)이면 사진 문서, 아니면 PDF 문서."""
    from viewer.image_page import PHOTO_EXTS
    from viewer.pdf_doc import PdfDocument
    if Path(file_path).suffix.lower() in PHOTO_EXTS:
        return PhotoDocument(file_path, cache)
    return PdfDocument(file_path, cache)
