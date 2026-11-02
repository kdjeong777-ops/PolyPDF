# -*- coding: utf-8 -*-
"""261101-2: 목차의 책 쪽 번호 → PDF 쪽 (마스터 §4.4.3 F1~F4, §4.4.2 ③).

스캐너가 빈 쪽을 지우거나 번호 없는 장 표지가 끼면 'PDF 쪽 − 책 쪽' 이 **구간마다 다르다**(실측 7구간·12구간).
그래서 오프셋 하나 대신 본문 쪽의 **인쇄된 쪽 번호**(머리말·꼬리말 띠의 숫자)를 읽어 구간별 차이를 추정한다.
  F1 `PrintedPages.folios`  — 쪽마다 띠 안의 1~3자리 숫자(뜻 있는 글자층 ▶ 띠 OCR). 표본 쪽만 읽고 경계는 반씩 좁힌다.
  F2 `fit_offsets`          — 차이를 상태로 둔 Viterbi(바뀔 때마다 벌점) → 쪽마다 차이·구간.
  F3 `map_rows` · `refine_chapter_pages` — 행 → PDF 쪽, 장 행은 앞 몇 쪽에서 장 제목 쪽으로 당긴다.
  F4 `map_rows_by_chapters` — 쪽 번호를 못 읽는 책(머리말·꼬리말에 장 제목만): 장 제목이 보이는 쪽으로 장의
     PDF 쪽을 찾고, 세부 항목은 '장 PDF 쪽 + (세부 목차 쪽 − 장 목차 쪽)'(사용자 지시).
Qt 비의존 — 워커 스레드에서 쓴다(응답성 SOT §4 ①: 문서는 이 객체가 따로 연다).
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from viewer.i18n import tr

BAND_TOP = 0.16          # 위 띠 높이(쪽 높이 비율) — 스캔본은 여백이 커 머리말이 15% 안팎에 있다(심리검사)
BAND_BOTTOM = 0.14       # 아래 띠
SAMPLE_STEP = 6          # 처음에는 이만큼 건너 읽는다
CHANGE_COST = 2.5        # 차이가 바뀔 때마다 벌점(F2)
MIN_EVIDENCE = 5         # 차이가 맞는 근거 쪽이 이보다 적으면 실패(오프셋 추정으로 폴백)
OFF_LIMIT = 80           # |차이| 상한
CHAPTER_BACK = 3         # 장 행: 앞으로 이만큼까지 장 제목 쪽을 찾는다(F3)
CHAPTER_WINDOW = 8       # F4: 앞 장에서 이어 짐작한 쪽의 앞뒤 이만큼에서 장 제목 쪽을 찾는다
MAX_REFINE = 12          # 경계 좁히기 반복 상한
SUB_AHEAD = 3            # F3': 세부 행 — 맞춘 쪽에 제목이 없으면 뒤로 이만큼까지 찾는다(원본 목차 쪽 숫자 틀림)
SUB_HEAD = 4             # F3': 대조할 제목 앞 글자 수(번호 뒤) — OCR 이 뒤쪽 글을 자주 깬다(`AC60O~70`)
SUB_GAP = 10             # F3': 번호와 제목 앞 글자 사이에 끼어도 되는 글자 수(본문 제목이 목차보다 길다)
# 띠 OCR 해상도·psm·언어는 단어학습 SOT §14.B '쪽 번호 띠' 가 소유한다
FOLIO_DPI = 150
FOLIO_PSM = 11
FOLIO_LANG = "eng"
BLANK_CHARS = 4          # 글자·숫자가 이보다 적은 쪽은 빈 쪽(F3·F4) — 장 표지는 'CHAPTER 1' 처럼 짧다
HEAD_PART = 0.5          # 장 제목 확인용으로 OCR 하는 쪽 위쪽 비율


def _norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s or "").lower()


def _is_blank(text: str) -> bool:
    """빈 쪽 — OCR 잡티(`. ' ,`)만 있으면 빈 쪽으로 본다."""
    return len(re.findall(r"[가-힣A-Za-z0-9]", text or "")) < BLANK_CHARS


class Estimate:
    """F2 결과 — 쪽마다 차이(path[p] = PDF 쪽 p 의 차이), 구간 [(from, to, 차이, 근거 쪽 수)]."""

    def __init__(self, first: int, last: int, path: dict, segs: list, evidence: int):
        self.first, self.last = first, last
        self.path = path
        self.segs = segs
        self.evidence = evidence

    def as_list(self) -> list:
        return [list(s) for s in self.segs]

    def seg_of(self, pdf_page: int) -> Optional[int]:
        for i, (a, b, _o, _e) in enumerate(self.segs):
            if a <= pdf_page <= b:
                return i
        return None

    def book_to_pdf(self, book: int) -> Optional[int]:
        return book_to_pdf(book, self.segs)


def book_to_pdf(book: int, segs: list) -> Optional[int]:
    """책 쪽 → PDF 쪽(F3). 그 책 쪽이 인쇄된 PDF 쪽(여럿이면 처음), 지워진 쪽이면 그다음 인쇄 쪽."""
    if not segs:
        return None
    hits = [book + o for a, b, o, *_ in segs if a <= book + o <= b]
    if hits:
        return min(hits)
    for a, _b, o, *_ in segs:                      # 지워진 쪽 — 그 뒤 첫 구간의 시작
        if a - o > book:
            return a
    return book + segs[-1][2]


def _score(nums, p: int, off: int) -> float:
    f = p - off
    if f < 1:
        return 0.0
    best = 0.0
    for n in nums:
        if n == f:
            best = max(best, 1.0 if n >= 10 else 0.5)
        elif n >= 0 and len(str(n)) < len(str(f)) and str(f).endswith(str(n)):
            best = max(best, 0.3)
    return best


def fit_offsets(folios: dict, first: int, last: int) -> Optional[Estimate]:
    """F2: {PDF 쪽: [숫자…]} → Estimate. 읽지 않은 쪽은 근거 0 으로 둔다."""
    offs = set()
    for p, nums in folios.items():
        for n in nums:
            if n >= 1 and abs(p - n) <= OFF_LIMIT:
                offs.add(p - n)
    if not offs:
        return None
    offs = sorted(offs)
    prev = {o: _score(folios.get(first, ()), first, o) for o in offs}
    back = []
    for p in range(first + 1, last + 1):
        nums = folios.get(p, ())
        bo = max(prev, key=prev.get)
        sw = prev[bo] - CHANGE_COST
        cur, bk = {}, {}
        for o in offs:
            if prev[o] >= sw:
                cur[o], bk[o] = prev[o] + _score(nums, p, o), o
            else:
                cur[o], bk[o] = sw + _score(nums, p, o), bo
        back.append(bk)
        prev = cur
    o = max(prev, key=prev.get)
    seq = [o]
    for bk in reversed(back):
        o = bk[o]
        seq.append(o)
    seq.reverse()
    path = {first + i: o for i, o in enumerate(seq)}
    segs, ev_total = [], 0
    for p in range(first, last + 1):
        o = path[p]
        ev = 1 if _score(folios.get(p, ()), p, o) >= 0.5 else 0
        ev_total += ev
        if segs and segs[-1][2] == o:
            segs[-1][1] = p; segs[-1][3] += ev
        else:
            segs.append([p, p, o, ev])
    # 근거 없는 구간(바뀐 차이를 하나도 뒷받침하지 못한 짧은 토막)은 앞 구간에 붙인다
    merged = []
    for s in segs:
        if merged and s[3] == 0:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    for i, s in enumerate(merged):
        for p in range(s[0], s[1] + 1):
            path[p] = s[2]
    if ev_total < MIN_EVIDENCE:
        return None
    return Estimate(first, last, path, [tuple(s) for s in merged], ev_total)


def _join_digits(words, H: float, W: float) -> list[int]:
    """띠 안 낱말 → 숫자(붙어 있는 숫자 낱말은 잇는다 — 글자층이 `1` `2` `4` 로 쪼갠 것)."""
    ws = sorted(words, key=lambda w: (round(w[1] / 4), w[0]))
    toks = []
    for x0, y0, x1, y1, t in ws:
        if toks and abs(toks[-1][1] - y0) < 4 and 0 <= x0 - toks[-1][2] < (y1 - y0) * 0.6 \
                and t.isdigit() and toks[-1][4].isdigit():
            a = toks[-1]
            toks[-1] = (a[0], a[1], x1, y1, a[4] + t)
        else:
            toks.append((x0, y0, x1, y1, t))
    return [int(t) for *_r, t in toks if re.fullmatch(r"\d{1,3}", t)]


class PrintedPages:
    """F1: 쪽마다 인쇄된 쪽 번호 후보 + 장 제목 확인용 글. 읽은 결과는 이 객체 안에만 둔다(저장하지 않는다)."""

    def __init__(self, pdf_path, *, ocr=None, should_cancel: Optional[Callable[[], bool]] = None,
                 progress: Optional[Callable[[str], None]] = None, pace: Optional[Callable[[], object]] = None):
        import fitz
        self.doc = fitz.open(str(pdf_path))
        self.page_count = self.doc.page_count
        self.ocr = ocr
        self.should_cancel = should_cancel or (lambda: False)
        self.progress = progress or (lambda _m: None)
        self.pace = pace or (lambda: None)
        self._fol, self._txt, self._layer_ok = {}, {}, {}
        self.ocr_read = 0

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ── 글자층 ──────────────────────────────────────────────────────
    def _is_scan(self, pno: int) -> bool:
        if self.ocr is not None:
            try:
                return bool(self.ocr.is_scan(pno))
            except Exception:
                pass
        try:
            from viewer.study import ocr as _o
            return _o.decide_source(self.doc.load_page(pno - 1))[0] == "ocr"
        except Exception:
            return False

    def _layer_usable(self, pno: int) -> bool:
        """디지털 쪽이거나, 스캔 쪽이라도 글자층이 뜻 있는 글이면(P8) 그 층을 쓴다."""
        if pno not in self._layer_ok:
            page = self.doc.load_page(pno - 1)
            text = page.get_text() or ""
            if not text.strip():
                ok = False
            elif not self._is_scan(pno):
                ok = True
            else:
                from viewer.toc_parse import layer_meaningful
                ok = layer_meaningful(text.splitlines())
            self._layer_ok[pno] = ok
        return self._layer_ok[pno]

    def _band_ocr(self, pno: int, clip, lang: str, psm: int) -> list:
        import fitz
        from PIL import Image
        from viewer.study import ocr as _o
        self.pace()
        page = self.doc.load_page(pno - 1)
        pix = page.get_pixmap(dpi=FOLIO_DPI, clip=clip, colorspace=fitz.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        self.ocr_read += 1
        return _o.ocr_image(img, lang=lang, psm=psm, dpi=FOLIO_DPI).get("words") or []

    # ── F1 ──────────────────────────────────────────────────────────
    def folios(self, pno: int) -> list[int]:
        if pno in self._fol:
            return self._fol[pno]
        import fitz
        page = self.doc.load_page(pno - 1)
        W, H = page.rect.width, page.rect.height
        top, bot = H * BAND_TOP, H * (1 - BAND_BOTTOM)
        nums = []
        try:
            if self._layer_usable(pno):
                ws = [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words") if w[3] < top or w[1] > bot]
                nums = _join_digits(ws, H, W)
            elif self._is_scan(pno) and not self.should_cancel():
                for clip in (fitz.Rect(0, 0, W, top), fitz.Rect(0, bot, W, H)):
                    for w in self._band_ocr(pno, clip, FOLIO_LANG, FOLIO_PSM):
                        s = str(w.get("surface", ""))
                        if re.fullmatch(r"\d{1,3}", s):
                            nums.append(int(s))
        except Exception:
            nums = []
        self._fol[pno] = nums
        return nums

    def estimate(self, first: int, last: int) -> Optional[Estimate]:
        """표본 쪽만 읽고(F1), 차이가 바뀌는 곳은 반씩 더 읽어 좁힌 뒤 F2."""
        last = min(last, self.page_count)
        if last - first < 2:
            return None
        pages = list(range(first, last + 1, SAMPLE_STEP))
        if pages[-1] != last:
            pages.append(last)
        for i, p in enumerate(pages):
            if self.should_cancel():
                return None
            if i % 10 == 0:
                self.progress(tr("인쇄된 쪽 번호 읽는 중… {pg}쪽").format(pg=p))
            self.folios(p)
        est = None
        for _ in range(MAX_REFINE):
            est = fit_offsets(self._fol, first, last)
            if est is None:
                return None
            ev = sorted(p for p, nums in self._fol.items() if _score(nums, p, est.path[p]) >= 0.5)
            todo = []
            for a, b in zip(ev, ev[1:]):
                if est.path[a] != est.path[b] and b - a > 1:
                    mids = sorted((q for q in range(a + 1, b) if q not in self._fol),
                                  key=lambda q: abs(q - (a + b) / 2))
                    if mids:
                        todo.append(mids[0])
            # 읽었는데 지금 차이와 어긋나는 두 자리 이상 숫자가 있는 쪽 — 새 구간의 시작일 수 있다(끝부분 부록 등) → 이웃을 더 읽는다
            for q, nums in list(self._fol.items()):
                if _score(nums, q, est.path[q]) >= 0.5:
                    continue
                if any(n >= 10 and 0 < abs((q - n) - est.path[q]) <= 15 for n in nums):
                    todo += [x for x in (q - 1, q + 1) if first <= x <= last and x not in self._fol][:2]
            todo = sorted(set(todo))
            if not todo:
                break
            for q in todo:
                if self.should_cancel():
                    return None
                self.folios(q)
        return est

    # ── 장 제목 확인용 글(F3·F4) ────────────────────────────────────
    def text_of(self, pno: int) -> str:
        """그 쪽 글(정규화 전) — 저장된 OCR ▶ 뜻 있는 글자층 ▶ 쪽 위쪽 OCR."""
        if pno in self._txt:
            return self._txt[pno]
        t = ""
        try:
            if self.ocr is not None and self.ocr.has_cached(pno):
                t = self.ocr.text(pno, run=False) or ""
            if not t and self._layer_usable(pno):
                t = self.doc.load_page(pno - 1).get_text() or ""
            if not t and self._is_scan(pno) and not self.should_cancel():
                import fitz
                from viewer.study import ocr as _o
                page = self.doc.load_page(pno - 1)
                clip = fitz.Rect(0, 0, page.rect.width, page.rect.height * HEAD_PART)
                lang = getattr(getattr(self.ocr, "_picker", None), "lang", None) or _o.default_lang()
                t = " ".join(str(w.get("surface", "")) for w in self._band_ocr(pno, clip, lang, FOLIO_PSM))
        except Exception:
            t = ""
        self._txt[pno] = t
        return t

    def known_text(self, pno: int) -> Optional[str]:
        """F3'(261103-1): 쪽 **전체** 글을 이미 알 때만 — 저장된 OCR ▶ 뜻 있는 글자층. 모르면 None(새로 OCR 하지 않는다)."""
        known = self.__dict__.setdefault("_known", {})
        if pno in known:
            return known[pno]
        t = None
        try:
            if self.ocr is not None and self.ocr.has_cached(pno):
                t = self.ocr.text(pno, run=False) or ""
            elif self._layer_usable(pno):
                t = self.doc.load_page(pno - 1).get_text() or ""
        except Exception:
            t = None
        known[pno] = t
        return t


def _needle(title: str) -> str:
    from viewer.toc_parse import _title_needle
    return _title_needle(title)


def map_rows(rows: list[dict], est: Estimate, page_count: int) -> int:
    """F3: toc_page 가 있는 행에 page·seg 를 채운다. 채운 수."""
    n = 0
    for r in rows:
        tp = r.get("toc_page")
        if not tp:
            continue
        p = est.book_to_pdf(int(tp))
        if p is None:
            continue
        r["page"] = max(1, min(page_count, int(p)))
        r["seg"] = est.seg_of(r["page"])
        n += 1
    return n


def refine_chapter_pages(rows: list[dict], text_of: Callable[[int], str], *, back: int = CHAPTER_BACK,
                         skip=()) -> int:
    """F3: 장 행(레벨 0) — 장 표지에는 쪽 번호가 없고 번호 없는 **빈 뒷면**이 끼기도 한다(성격심리: 표지 → 빈 쪽 → 번호 쪽).
    맞춘 쪽이 빈 쪽이면, 또는 장 쪽 번호가 없어 첫 하위 항목 쪽을 물려받았고 그 앞이 빈 쪽이면, 앞으로 빈 쪽을 거슬러
    **처음 글이 있는 쪽**(= 장 표지)으로 당긴다. 그 밖에(바로 앞이 빈 쪽, 물려받은 행) 당길 때는 그 쪽에 장 제목이 보일 때만.
    표지의 큰 제목은 OCR·글자층에서 자주 깨져(실측 3/6) 제목 대조만으로는 찾지 못한다. 당긴 수."""
    n = 0
    lo_of = lambda p: max(1, p - back)
    blank = lambda q: _is_blank(text_of(q))
    for r in rows:
        if int(r.get("level", 0)) != 0 or not r.get("page"):
            continue
        p = int(r["page"])
        pb = blank(p)
        if not (pb or r.get("toc_inherited") or (p > 1 and blank(p - 1))):
            continue
        q, skipped = p - 1, pb
        while q >= lo_of(p) and q not in skip and blank(q):
            q -= 1; skipped = True
        if q < lo_of(p) or q in skip:
            continue
        if not (pb or (skipped and r.get("toc_inherited"))):
            nd = _needle(r.get("title", ""))
            if len(nd) < 4 or nd not in _norm(text_of(q)):
                continue
        r["page"] = q
        n += 1
    return n


_SUB_NUM = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){1,3})\.?\s*(.+)$")


def _sub_needle(title: str):
    """세부 행 대조 — 번호(점 뺀 숫자) 뒤 `SUB_GAP` 글자 안에 제목 앞 `SUB_HEAD` 글자(본문 제목이 목차보다 길기도 하다 —
    목차 '4.4 아스콘 시험 포장', 본문 '4.4 AC60~70 아스콘 시험포장'). 번호 없는 행·짧은 제목은 None(대조하지 않는다)."""
    m = _SUB_NUM.match(title or "")
    if not m:
        return None
    rest = _norm(m.group(2))
    if len(rest) < 2:
        return None
    return re.compile(re.escape(_norm(m.group(1))) + r".{0,%d}?" % SUB_GAP + re.escape(rest[:SUB_HEAD]))


def refine_sub_pages(rows: list[dict], text_of: Callable[[int], Optional[str]], *, ahead: int = SUB_AHEAD,
                     skip=(), page_count: int = 0) -> int:
    """F3'(261103-1): 세부 행(레벨 1~, 번호 있는 행) — 원본 목차의 쪽 숫자가 틀린 책이 있다(_96 목차 4.3.3=90·4.4=96,
    실제 인쇄 91·98). 맞춘 쪽에 '번호+제목'(`_sub_needle`)이 안 보이고 뒤 `ahead` 쪽 안에 보이면 처음 보이는 쪽으로 민다.
    맞춘 쪽에 보이거나 어디에도 안 보이면 그대로. `text_of` 는 **이미 아는 글만**(`PrintedPages.known_text` — 저장된 OCR·
    뜻 있는 글자층) 주고 모르면 None — 새로 OCR 하지 않는다(띠 OCR 로 재면 _96 에서 +250초). 옮긴 수."""
    n = 0
    for r in rows:
        if int(r.get("level", 0)) == 0 or not r.get("page") or r.get("manual"):
            continue
        nd = _sub_needle(r.get("title", ""))
        if nd is None:
            continue
        p = int(r["page"])
        t = text_of(p)
        if t is None or nd.search(_norm(t)):
            continue
        for q in range(p + 1, p + ahead + 1):
            if q in skip or (page_count and q > page_count):
                break
            tq = text_of(q)
            if tq is None:
                break
            if nd.search(_norm(tq)):
                r["page"] = q
                n += 1
                break
    return n


def map_rows_by_chapters(rows: list[dict], text_of: Callable[[int], str], page_count: int, *,
                         start_offset: int, window: int = CHAPTER_WINDOW, skip=(), back: int = CHAPTER_BACK,
                         should_cancel: Optional[Callable[[], bool]] = None) -> int:
    """F4(사용자 지시 — 머리말·꼬리말에 쪽 번호 없이 대목차만 있는 책): 장 행마다 '앞 장에서 이어 짐작한 쪽' 둘레
    `window` 안에서 장 제목이 보이는 **가장 앞 쪽**을 찾는다(머리말이 짝수 쪽에만 장 제목을 싣기도 해 이어 보이지 않는다).
    그 앞이 빈 쪽이면 빈 쪽을 거슬러 처음 글이 있는 쪽이 장 표지다(F3 와 같다). 세부 행의 쪽은
    '장 표지 쪽 + (세부 목차 쪽 − 장 목차 쪽) + 표지 뒤 빈 쪽 수'(번호 없는 빈 뒷면은 책 쪽을 먹지 않는다 — 성격심리 실측). 장을 못 찾으면 앞 차이를
    이어 쓴다. 장 행을 찾은 수."""
    should_cancel = should_cancel or (lambda: False)
    blank = lambda q: _is_blank(text_of(q))
    off, found, seg, floor = int(start_offset), 0, 0, 1
    for r in rows:
        if should_cancel():
            break
        tp = r.get("toc_page")
        if not tp:
            continue
        tp = int(tp)
        if int(r.get("level", 0)) == 0:
            nd = _needle(r.get("title", ""))
            guess = tp + off
            lo, hi = max(floor, guess - window), min(page_count, guess + window)
            hit = None
            if len(nd) >= 4:
                for q in range(lo, hi + 1):
                    if q not in skip and nd in _norm(text_of(q)):
                        hit = q
                        break
            if hit is not None:
                title, q = hit, hit - 1
                while q >= max(floor, hit - back) and q not in skip and blank(q):
                    q -= 1
                if q < hit - 1 and q >= max(floor, hit - back) and q not in skip:
                    title = q                      # 제목이 깨진 표지 — 빈 뒷면 앞의 글 있는 쪽
                extra = 0                          # 표지 뒤 번호 없는 빈 쪽은 책 쪽을 먹지 않는다
                while extra < back and title + 1 + extra <= page_count and blank(title + 1 + extra):
                    extra += 1
                off = title - tp + extra
                r["page"] = title
                r["seg"] = seg = seg + 1
                floor = hit + 1
                found += 1
                continue
        r["page"] = max(1, min(page_count, tp + off))
        r["seg"] = seg
    return found
