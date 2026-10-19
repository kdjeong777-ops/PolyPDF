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


def _flat_char_rects(chars, qf: str) -> list:
    """[(글자, (x0,y0,x1,y1))] 에서 빈칸을 뺀 글자열로 `qf` 를 찾아 줄마다 묶은 사각형."""
    s = "".join(c for c, _b in chars).lower()
    out = []
    start = s.find(qf)
    while start >= 0 and qf:
        boxes = [b for _c, b in chars[start:start + len(qf)]]
        cur = None
        for b in boxes:
            if cur is not None and abs((b[1] + b[3]) / 2 - (cur[1] + cur[3]) / 2) <= max(2.0, (cur[3] - cur[1]) * 0.6):
                cur = [min(cur[0], b[0]), min(cur[1], b[1]), max(cur[2], b[2]), max(cur[3], b[3])]
            else:
                if cur is not None:
                    out.append(fitz.Rect(*cur))
                cur = list(b)
        if cur is not None:
            out.append(fitz.Rect(*cur))
        start = s.find(qf, start + len(qf))
    return out


def flat_hits(page, query: str, ocr=None, flat_txt=None) -> list:
    """261019-4(검색창 SOT §8): 빈칸·줄바꿈을 무시하고 맞은 자리 — 색인 비교(`indexer.flat_text`)와 같은 뜻.
    `search_for` 가 못 찾을 때만 부른다(질의와 본문의 띄어쓰기가 다를 때 · 스캔 쪽). 값싼 미리 거르기(쪽 글에 있나)를 먼저 한다.
    `ocr()` → (낱말[픽셀@dpi], dpi): 글자층이 없는 쪽은 저장된 우리 OCR 낱말로 자리를 찾는다."""
    import re as _re
    qf = _re.sub(r"\s+", "", query or "").lower()
    if not qf:
        return []
    if flat_txt is None:                          # 문서 전체 검색은 쪽 글을 기억해 둔 것을 준다(PdfDoc._flat_page)
        try:
            flat_txt = _re.sub(r"\s+", "", page.get_text("text") or "").lower()
        except Exception:
            flat_txt = ""
    if qf in flat_txt:
        chars = []
        try:
            for b in page.get_text("rawdict").get("blocks", []):
                for ln in b.get("lines", []):
                    for sp in ln.get("spans", []):
                        for ch in sp.get("chars", []):
                            c = ch.get("c", "")
                            if c and not c.isspace():
                                chars.append((c.lower() if len(c.lower()) == 1 else c, tuple(ch["bbox"])))
        except Exception:
            chars = []
        return _flat_char_rects(chars, qf)
    if ocr is not None:
        try:
            words, dpi = ocr()
        except Exception:
            words, dpi = [], 0
        if words:
            k = 72.0 / float(dpi) if dpi else 1.0
            chars = []
            for w in sorted(words, key=lambda w: (round(float(w["y0"]) / max(1.0, float(w["y1"]) - float(w["y0"]))), float(w["x0"]))):
                sfc = _re.sub(r"\s+", "", str(w.get("surface", "")))
                if not sfc:
                    continue
                x0, y0, x1, y1 = (float(w["x0"]) * k, float(w["y0"]) * k, float(w["x1"]) * k, float(w["y1"]) * k)
                step = (x1 - x0) / len(sfc)
                for j, c in enumerate(sfc):          # 낱말 상자를 글자 수로 고르게 나눈다(대략의 자리)
                    chars.append((c.lower() if len(c.lower()) == 1 else c, (x0 + j * step, y0, x0 + (j + 1) * step, y1)))
            return _flat_char_rects(chars, qf)
    return []


def page_hits(page, query: str, mode=None, ocr=None, flat_txt=None) -> list:
    """쪽 하나에서 질의가 맞은 사각형 — 검색 강조의 한 길(검색창 SOT §4.1, 261014-18).
    `mode` 가 없거나 둘 다 꺼짐 → `search_for`(종전) — 못 찾으면 빈칸 무시(`flat_hits`, 261019-4), 아니면 `search_match.match_rects`.
    틀린 정규식이면 빈 목록."""
    if not query:
        return []
    if not mode or not any(mode):
        hits = list(page.search_for(query))
        return hits or flat_hits(page, query, ocr, flat_txt)
    from viewer.search_match import Matcher, match_rects
    try:
        m = Matcher(query, case=mode[0], regex=mode[1])
    except Exception:
        return []
    return match_rects(page, m)


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


# 260829(§19.11 P-A): ★ 앱 전역 단일 렌더 캐시.
#   문서마다 PageCache 를 따로 가지면 2단·발표·썸네일이 각각 256MB 를 들고
#   최악 GB 대가 된다 → 전역 예산 하나로 통일. 키의 cache_tag(경로|mtime)가
#   문서를 구분하므로 공유해도 섞이지 않는다.
GLOBAL_PAGE_CACHE = PageCache(max_bytes=256 * 1024 * 1024)


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
        self.cache = cache or GLOBAL_PAGE_CACHE      # 260829: 기본 = 전역 캐시(§19.11)
        # 260829: 캐시 태그 — mtime 포함으로 파일 변경 시 낡은 픽셀 재사용 방지.
        try:
            self._cache_tag = f"{self.path}|{self.path.stat().st_mtime_ns}"
        except Exception:
            self._cache_tag = str(self.path)
        # 261010-13(마스터 §4.7.15): 저장 전 크롭을 덧입힌다(파일은 그대로) — 본문·썸네일·발표가 잘린 모양으로 보인다.
        #   캐시 태그에 크롭 판을 넣어 덧입히기 전 픽셀을 다시 쓰지 않게.
        # 261011-2(§4.7.16): '저장' 이 넣은 'PolyPDF' 레이어는 끈다(메모리에서만) — 옆 파일 꾸밈과 두 번 그려지지 않게
        try:
            from viewer import pdf_mirror as _pm
            _pm.hide_for_view(self.doc)
        except Exception:
            pass
        # 261011-2(§4.7.16): 저장 전 회전도 `/Rotate` 에 덧입힌다 — **크롭보다 먼저**(크롭 여백은 보이는 방향 기준이다)
        try:
            from viewer import page_rotate as _pr
            if _pr.has_pending(self.path):
                _pr.apply_pending(self.doc, self.path)
            self._cache_tag += "|rot%d" % _pr.version(self.path)
        except Exception:
            pass
        try:
            from viewer import page_crop as _pc
            if _pc.has_pending(self.path):
                _pc.apply_pending(self.doc, self.path)
            self._cache_tag += "|crop%d" % _pc.version(self.path)
        except Exception:
            pass

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

    def search(self, query: str, mode=None) -> list:
        """쪽마다 맞은 자리. `mode=(대소문자, 정규식)` 이면 `search_match`(검색창 SOT §4.1), 아니면 `search_for`."""
        if not query:
            return []
        hits: list = []
        for i in range(self.doc.page_count):
            page = self.doc.load_page(i)
            rects = page_hits(page, query, mode, flat_txt=self._flat_page(i, page))
            if rects:
                hits.append(SearchHit(page_index=i, rects=list(rects)))
        return hits

    def _flat_page(self, i: int, page=None) -> str:
        """261019-4: 쪽 글의 빈칸 없는 소문자 꼴 — 문서를 연 동안 기억한다(빈칸 무시 검색의 값싼 미리 거르기)."""
        cache = self.__dict__.setdefault("_flat_cache", {})
        if i not in cache:
            import re as _re
            try:
                pg = page if page is not None else self.doc.load_page(i)
                cache[i] = _re.sub(r"\s+", "", pg.get_text("text") or "").lower()
            except Exception:
                cache[i] = ""
        return cache[i]

    def search_page(self, page_index: int, query: str, mode=None) -> list:
        if not query:
            return []
        return list(page_hits(self.doc.load_page(page_index), query, mode))

    def render(
        self,
        page_index: int,
        *,
        base_dpi: int = 192,           # v1.3.0: 144 -> 192
        scale: float = 1.0,
        rgba: bool = False,            # v1.3.1: 기본 RGB(종이 흰색 보존). 알파는 호출자 명시 시만
        dpi: int | None = None,        # 1.2.x 호환
        cache: bool = True,
    ) -> RenderedPage:
        """페이지를 픽스맵으로 렌더링. `cache=False` 면 전역 캐시를 읽지도 쓰지도 않는다(썸네일 — §19.11 P-B)."""
        if dpi is not None:
            effective_dpi = int(dpi)
        else:
            effective_dpi = round(base_dpi * scale)
        effective_dpi = max(72, min(600, effective_dpi))   # 안전 범위

        key = RenderKey(self._cache_tag, page_index, effective_dpi, rgba)   # 260829: mtime 포함 태그
        cached = self.cache.get(key) if cache else None
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
        if cache:
            self.cache.put(key, result)
        return result

    def render_scaled(self, page_index: int, physical_scale: float) -> RenderedPage:
        """260829(§19.11 P-A): 물리 배율 지정 렌더 — 메인 뷰어(1:1 파이프라인) 전용.

        배율을 1e-4 단위로 정수화해 캐시 키로 쓴다(§19.9 백로그 구현) — 같은
        페이지·배율 재방문(페이지 왕복·유휴 복귀)은 재렌더 없이 캐시 적중.
        ※ 반환 samples 는 캐시 소유라 LRU 회수될 수 있다 — 호출자는 QImage 를
          반드시 .copy() 로 분리할 것(직접 참조 시 회수 타이밍에 크래시).
        """
        q = max(0.1, min(20.0, float(physical_scale)))
        scale_q = int(round(q * 10000))                 # 정수화(부동소수 지터 미스 방지)
        key = RenderKey(self._cache_tag, page_index, scale_q, False)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        page = self.doc.load_page(page_index)
        mat = fitz.Matrix(scale_q / 10000, scale_q / 10000)
        pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)
        result = RenderedPage(width=pix.width, height=pix.height,
                              samples=pix.samples, page_rect=tuple(page.rect))
        self.cache.put(key, result)
        return result

    def render_thumbnail(self, page_index: int, dpi: int = 48) -> RenderedPage:
        """저해상도 썸네일 (RGB888, 알파 없음). 전역 캐시를 쓰지 않는다 — 부르는 쪽이 아이콘으로 들고 있어
        캐시에 또 두면 같은 그림이 두 벌이 되고, 쪽 수만큼 본문 렌더를 밀어낸다(§19.11 P-B, 261014-24)."""
        return self.render(page_index, dpi=dpi, rgba=False, cache=False)

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
