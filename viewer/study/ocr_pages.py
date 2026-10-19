# -*- coding: utf-8 -*-
"""261019-1: 책갈피 자동 생성이 쓰는 **쪽별 OCR 공급자** (단어학습 SOT §14.21 · 마스터 §4.4.2).

규칙
  - **이미 읽은 쪽은 다시 읽지 않는다.** `study.db`(+ 보류 저장소)에 그 쪽 OCR 이 있으면 그것을 쓴다 —
    텍스트 창 [OCR 다시 읽기]·단어장 만들기·지난 책갈피 생성이 읽은 것.
  - **새로 읽은 쪽은 텍스트 창과 같은 형식으로 남긴다** — 300 dpi, `force_ocr`, 워터마크 지우기, 표준 psm.
    그래서 책갈피를 만든 뒤 텍스트 창에 그 글이 바로 보인다. 남는 곳은 보류 저장소다([저장] 해야 확정).
  - 목차 쪽은 표준 psm 이 쪽 번호를 놓치는 일이 있어(실측: 점선 리더가 긴 쪽에서 오른쪽 숫자 열 전체) 흩어진 글
    모드(psm 11)를 **한 번 더** 읽어 줄마다 합친다(`toc_lines`). 이 추가 판독은 저장하지 않는다(목차 표에만).
Qt 비의존 — 워커 스레드에서 쓴다(응답성 SOT §4 ①: 문서는 이 객체가 따로 연다).
"""
from __future__ import annotations

import re
from pathlib import Path
from statistics import median
from typing import Callable, Optional

DPI = 300
TOC_PSM = 11                 # 흩어진 글 — 점선 리더 사이의 제목·쪽 번호를 따로 집는다


class OcrPages:
    def __init__(self, pdf_path, *, lang: str = "", store=None,
                 should_cancel: Optional[Callable[[], bool]] = None,
                 progress: Optional[Callable[[str], None]] = None,
                 run_ocr: bool = True, pace: Optional[Callable[[], object]] = None):
        import fitz
        from viewer.study import ocr as _ocr
        from viewer.study.study_store import StudyStore, file_key_for
        self.path = str(pdf_path)
        self._ocr = _ocr
        self.doc = fitz.open(self.path)
        self.page_count = self.doc.page_count
        self.lang = _ocr.resolve_lang(lang or _ocr.default_lang())
        self._own_store = store is None
        try:
            self.store = store if store is not None else StudyStore()
        except Exception:
            self.store = None
        self.fkey = file_key_for(self.path)
        self.should_cancel = should_cancel or (lambda: False)
        self.progress = progress or (lambda _m: None)
        self.run_ocr = bool(run_ocr)
        self.pace = pace or (lambda: None)   # 응답성 SOT §4 ②⑦ — 새로 읽는 쪽마다 메인에 양보(워커가 준다)
        self.ran = 0                 # 이번에 새로 읽은 쪽 수
        self.reused = 0              # 저장된 OCR 을 쓴 쪽 수
        self._src = {}
        self._mem = {}               # pno1 → (words, dpi) — 저장소를 못 쓸 때

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass
        if self._own_store and self.store is not None:
            try:
                self.store.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ── 쪽 판정 ─────────────────────────────────────────────────────
    def is_scan(self, pno1: int) -> bool:
        """이 쪽은 OCR 로 읽어야 하는가(단어학습 SOT §14.18 `decide_source`)."""
        if pno1 not in self._src:
            try:
                src, _ = self._ocr.decide_source(self.doc.load_page(pno1 - 1))
            except Exception:
                src = "layer"
            self._src[pno1] = (src == "ocr")
        return self._src[pno1]

    def has_cached(self, pno1: int) -> bool:
        if pno1 in self._mem:
            return True
        try:
            return bool(self.store is not None and self.store.is_page_done(self.fkey, pno1 - 1))
        except Exception:
            return False

    # ── 낱말 ────────────────────────────────────────────────────────
    def words(self, pno1: int, run: Optional[bool] = None) -> tuple[list, int]:
        """(낱말[픽셀@dpi], dpi). 저장된 것 ▶ (run 이면) 새로 읽고 보류 저장소에 남긴다."""
        run = self.run_ocr if run is None else run
        if pno1 in self._mem:
            return self._mem[pno1]
        if self.store is not None:
            try:
                if self.store.is_page_done(self.fkey, pno1 - 1):
                    ws = self.store.get_page_words(self.fkey, pno1 - 1) or []
                    dpi = int(self.store.get_page_dpi(self.fkey, pno1 - 1) or 0)
                    self.reused += 1
                    return ws, dpi
            except Exception:
                pass
        if not run or self.should_cancel():
            return [], 0
        self.progress(f"OCR p.{pno1}")
        self.pace()
        res = self._ocr.build_page(self.doc, pno1 - 1, lang=self.lang, dpi=DPI,
                                   force_ocr=True, drop_watermark_bg=True)
        ws = res.get("words") or []
        dpi = int(res.get("dpi") or DPI)
        self.ran += 1
        saved = False
        if self.store is not None:
            try:
                self.store.save_page(self.fkey, pno1 - 1, res.get("text") or "", dpi=dpi,
                                     engine=res.get("engine") or "tesseract",
                                     source=res.get("source") or "ocr",
                                     conf=float(res.get("conf") or 0.0), words=ws, lang=self.lang)
                saved = True
            except Exception:
                saved = False
        if not saved:
            self._mem[pno1] = (ws, dpi)
        return ws, dpi

    def lines(self, pno1: int, run: Optional[bool] = None) -> list[tuple[float, str]]:
        """[(x0 pt, 줄 글)] — 표준 판독의 줄."""
        ws, dpi = self.words(pno1, run)
        return [(ln["x0"], ln["text"]) for ln in group_lines(ws, dpi)]

    def text(self, pno1: int, run: bool = False) -> str:
        """쪽 글 — 저장된 OCR 글(`ocr_page.text`)이 있으면 그것, 없으면 낱말로 이은 줄."""
        if self.store is not None:
            try:
                t = self.store.get_page_text(self.fkey, pno1 - 1)
                if t:
                    return t
            except Exception:
                pass
        return "\n".join(t for _x, t in self.lines(pno1, run))

    # ── 목차 쪽: 두 판독을 줄마다 합친다 ─────────────────────────────
    def toc_lines(self, pno1: int) -> list[tuple[float, str]]:
        """목차 쪽 줄 [(x0 pt, '제목 …… 쪽')] — 표준 판독 + 흩어진 글 판독(psm 11)을 y 로 맞춰 합친다.

        제목은 글자가 더 많이 남은 쪽(점선 잡글자는 뺀 뒤)을, 쪽 번호는 오른쪽 끝 숫자를 둘 중
        읽힌 쪽에서 가져온다. 표본(1996 보고서 4~6쪽): 표준만으로는 5·6쪽의 쪽 번호가 하나도 없었다."""
        std_ws, dpi = self.words(pno1)
        dpi = dpi or DPI
        extra = []
        if self.run_ocr and not self.should_cancel():
            self.pace()
            try:
                img, _r, _sz = self._ocr.render_page(self.doc, pno1 - 1, dpi=DPI, drop_watermark_bg=True)
                extra = (self._ocr.ocr_image(img, lang=self.lang, psm=TOC_PSM, dpi=DPI).get("words") or [])
            except Exception:
                extra = []
        width = float(self.doc.load_page(pno1 - 1).rect.width) * dpi / 72.0
        a = [_toc_parts(ln, width) for ln in group_lines(std_ws, dpi, raw=True)]
        b = [_toc_parts(ln, width) for ln in group_lines(extra, DPI, raw=True)] if extra else []
        merged = _merge_toc_lines(a, b)
        out = []
        for m in merged:
            title = m["title"]
            if not title:
                continue
            out.append((m["x0"], f"{title} ……… {m['page']}" if m.get("page") else title))
        return out


# ── 줄 묶기 ──────────────────────────────────────────────────────────
def group_lines(words: list, dpi: int, raw: bool = False) -> list[dict]:
    """낱말(픽셀@dpi) → 줄 [{x0(pt), y0, y1, h(중앙값), text, words}] — 세로 가운데가 겹치면 같은 줄."""
    if not words:
        return []
    k = 72.0 / float(dpi or DPI) if dpi else 1.0
    ws = sorted(words, key=lambda w: ((float(w["y0"]) + float(w["y1"])) / 2, float(w["x0"])))
    hs = [max(1.0, float(w["y1"]) - float(w["y0"])) for w in ws]
    hmed = median(hs) if hs else 10.0
    lines: list[dict] = []
    for w in ws:
        cy = (float(w["y0"]) + float(w["y1"])) / 2
        if lines and abs(cy - lines[-1]["cy"]) <= 0.45 * hmed:
            ln = lines[-1]
            ln["words"].append(w)
            ln["cy"] = (ln["cy"] * (len(ln["words"]) - 1) + cy) / len(ln["words"])
        else:
            lines.append({"cy": cy, "words": [w]})
    out = []
    for ln in lines:
        ln["words"].sort(key=lambda w: float(w["x0"]))
        hh = [max(1.0, float(w["y1"]) - float(w["y0"])) for w in ln["words"]]
        d = {"x0": float(ln["words"][0]["x0"]) * k, "x0px": float(ln["words"][0]["x0"]),
             "y0": min(float(w["y0"]) for w in ln["words"]), "y1": max(float(w["y1"]) for w in ln["words"]),
             "cy": ln["cy"], "h": median(hh), "words": ln["words"]}
        if not raw:
            d["text"] = _join(ln["words"])
        out.append(d)
    return out


def _join(ws: list) -> str:
    try:
        from viewer.study.ocr import _join_words_by_gap
        return _join_words_by_gap(list(ws)).strip()
    except Exception:
        return " ".join(str(w.get("surface", "")) for w in ws).strip()


# 점선 리더를 OCR 이 읽은 잡글자: '아아아', '이 이', 'eee', '……', '·', 'ㅇ' 등
_LEADER = re.compile(r"^[\.…·•‥⋯,:;'`\"\-_~=ㅡㅇ아이야어여오우에애나니마미파피세가다라뒤며eErRTtcCsSoO]+$")
_PAGE_TAIL = re.compile(r"([0-9lIO|]{1,4})[\.,]?$")


def _toc_parts(ln: dict, width_px: float) -> dict:
    """줄 → {x0, cy, h, title, page}. 제목 = 첫 큰 빈틈·잡글자 전까지, 쪽 = 오른쪽 끝 숫자."""
    ws = ln["words"]
    h = max(1.0, ln["h"])
    page = None
    tail_idx = len(ws)
    last = ws[-1] if ws else None
    if last is not None and float(last["x0"]) >= 0.70 * width_px:
        m = _PAGE_TAIL.search(str(last["surface"]))
        if m:
            from viewer.toc_parse import fix_ocr_number
            page = fix_ocr_number(m.group(1))
            if page is not None:
                tail_idx = len(ws) - 1
    title_ws = []
    prev = None
    for w in ws[:tail_idx]:
        s = str(w["surface"])
        if prev is not None and float(w["x0"]) - float(prev["x1"]) > 3.0 * h:
            break                                  # 점선 리더 자리의 큰 빈틈
        if title_ws and _LEADER.match(s) and float(w.get("conf", 1.0)) < 0.7:
            break
        title_ws.append(w); prev = w
    # 끝에 붙은 잡글자 낱말을 떼어 낸다('설계법 아 이' → '설계법')
    while title_ws and _LEADER.match(str(title_ws[-1]["surface"])) and len(title_ws) > 1:
        title_ws.pop()
    title = _join(title_ws) if title_ws else ""
    return {"x0": ln["x0"], "cy": ln["cy"], "h": h, "title": title.strip(), "page": page,
            "n": sum(len(re.sub(r"\W", "", str(w["surface"]))) for w in title_ws)}


def _merge_toc_lines(a: list, b: list) -> list:
    """두 판독의 줄을 세로 위치로 맞춰 합친다. a=표준, b=흩어진 글. 순서 = 위에서 아래."""
    if not b:
        return a
    if not a:
        return b
    out, used = [], set()
    for la in a:
        best, bd = None, None
        for j, lb in enumerate(b):
            if j in used:
                continue
            d = abs(la["cy"] - lb["cy"])
            if d <= 0.6 * max(la["h"], lb["h"]) and (bd is None or d < bd):
                best, bd = j, d
        if best is None:
            out.append(la); continue
        used.add(best)
        lb = b[best]
        m = dict(la)
        if lb["title"] and (lb["n"] > la["n"] or not la["title"]):
            m["title"], m["x0"], m["n"] = lb["title"], min(la["x0"], lb["x0"]), lb["n"]
        if m.get("page") is None:
            m["page"] = lb.get("page")
        out.append(m)
    # 흩어진 글 판독에만 있는 줄(쪽 번호만 따로 줄이 된 것은 이웃 줄에 붙인다)
    for j, lb in enumerate(b):
        if j in used:
            continue
        if not lb["title"] and lb.get("page") is not None:
            near = min(out, key=lambda m: abs(m["cy"] - lb["cy"]), default=None)
            if near is not None and near.get("page") is None and abs(near["cy"] - lb["cy"]) <= 1.2 * lb["h"]:
                near["page"] = lb["page"]
            continue
        out.append(lb)
    out.sort(key=lambda m: m["cy"])
    return out
