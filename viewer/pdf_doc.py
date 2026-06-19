"""PyMuPDF (fitz) 문서 래퍼와 페이지 렌더 캐시.

v1.3.0: render() 시그니처가 base_dpi/scale 로 변경됨. 호환을 위해 dpi= 키워드도 받음.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import fitz  # PyMuPDF


@dataclass(frozen=True)
class RenderKey:
    file_path: str
    page_index: int
    dpi: int
    rgba: bool

    def __hash__(self):
        return hash((self.file_path, self.page_index, self.dpi, self.rgba))


@dataclass
class RenderedPage:
    width: int
    height: int
    samples: bytes
    page_rect: tuple
    is_rgba: bool = False     # True 면 4채널, False 면 3채널


@dataclass
class SearchHit:
    page_index: int
    rects: list


class PageCache:
    """OrderedDict 기반 LRU. 메모리 한도(byte)로 자동 회수."""

    def __init__(self, max_bytes: int = 256 * 1024 * 1024):
        self._max = max_bytes
        self._cur = 0
        self._items: "OrderedDict[RenderKey, RenderedPage]" = OrderedDict()

    def get(self, key: RenderKey):
        page = self._items.get(key)
        if page is not None:
            self._items.move_to_end(key)
        return page

    def put(self, key: RenderKey, page: RenderedPage):
        existing = self._items.pop(key, None)
        if existing is not None:
            self._cur -= len(existing.samples)
        self._items[key] = page
        self._cur += len(page.samples)
        while self._cur > self._max and self._items:
            _k, victim = self._items.popitem(last=False)
            self._cur -= len(victim.samples)

    def clear(self):
        self._items.clear()
        self._cur = 0


class PdfDocument:
    """PyMuPDF 문서 래퍼."""

    def __init__(self, file_path: str | Path, cache: PageCache | None = None):
        self.path = Path(file_path)
        self.doc = fitz.open(self.path)
        # needs_pass 는 인증 후에도 True 로 남을 수 있어 별도 인증 상태를 추적
        try:
            self._authed = not bool(self.doc.needs_pass)
        except Exception:
            self._authed = True
        self.cache = cache or PageCache()

    @property
    def needs_password(self) -> bool:
        """암호가 걸려 아직 인증되지 않은 경우 True."""
        return not self._authed

    def authenticate(self, password: str) -> bool:
        """암호로 문서 잠금 해제. 성공 시 True."""
        try:
            if self.doc.authenticate(password or ""):
                self._authed = True
                return True
        except Exception:
            pass
        return False

    def __len__(self) -> int:
        return self.doc.page_count

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def extract_text(self, page_index: int) -> str:
        return self.doc.load_page(page_index).get_text("text")

    def iter_pages_text(self) -> Iterator[tuple]:
        for i in range(self.doc.page_count):
            yield i, self.doc.load_page(i).get_text("text")

    def search(self, query: str) -> list:
        if not query:
            return []
        hits: list = []
        for i in range(self.doc.page_count):
            page = self.doc.load_page(i)
            rects = page.search_for(query)
            if rects:
                hits.append(SearchHit(page_index=i, rects=list(rects)))
        return hits

    def search_page(self, page_index: int, query: str) -> list:
        if not query:
            return []
        return list(self.doc.load_page(page_index).search_for(query))

    def render(
        self,
        page_index: int,
        *,
        base_dpi: int = 192,           # v1.3.0: 144 -> 192
        scale: float = 1.0,
        rgba: bool = False,            # v1.3.1: 기본 RGB(종이 흰색 보존). 알파는 호출자 명시 시만
        dpi: int | None = None,        # 1.2.x 호환
    ) -> RenderedPage:
        """페이지를 픽스맵으로 렌더링."""
        if dpi is not None:
            effective_dpi = int(dpi)
        else:
            effective_dpi = round(base_dpi * scale)
        effective_dpi = max(72, min(600, effective_dpi))   # 안전 범위

        key = RenderKey(str(self.path), page_index, effective_dpi, rgba)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        page = self.doc.load_page(page_index)
        mat = fitz.Matrix(effective_dpi / 72, effective_dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=rgba, colorspace=fitz.csRGB)
        result = RenderedPage(
            width=pix.width,
            height=pix.height,
            samples=pix.samples,
            page_rect=tuple(page.rect),
            is_rgba=bool(rgba),
        )
        self.cache.put(key, result)
        return result

    def render_thumbnail(self, page_index: int, dpi: int = 48) -> RenderedPage:
        """저해상도 썸네일 (RGB888, 알파 없음)."""
        return self.render(page_index, dpi=dpi, rgba=False)

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
