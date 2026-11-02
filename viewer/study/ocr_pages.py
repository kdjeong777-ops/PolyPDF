# -*- coding: utf-8 -*-
"""261019-1: 책갈피 자동 생성이 쓰는 **쪽별 OCR 공급자** (단어학습 SOT §14.21 · 마스터 §4.4.2).

규칙
  - **이미 읽은 쪽은 다시 읽지 않는다.** `study.db`(+ 보류 저장소)에 그 쪽 OCR 이 있으면 그것을 쓴다 —
    텍스트 창 [OCR 다시 읽기]·단어장 만들기·지난 책갈피 생성이 읽은 것.
  - **새로 읽은 쪽은 텍스트 창과 같은 형식으로 남긴다** — 300 dpi, `force_ocr`, 워터마크 지우기, 표준 psm.
    그래서 책갈피를 만든 뒤 텍스트 창에 그 글이 바로 보인다. 남는 곳은 보류 저장소다([저장] 해야 확정).
  - 목차 쪽은 표준 psm 이 쪽 번호를 놓치는 일이 있어(실측: 점선 리더가 긴 쪽에서 오른쪽 숫자 열 전체) 흩어진 글
    모드(psm 11)를 **한 번 더** 읽어 줄마다 합친다(`toc_lines`). 이 추가 판독은 저장하지 않는다(목차 표에만).
    쪽 OCR(`build_page`)도 목차 쪽이면 같은 판독으로 놓친 쪽 번호·번호·줄을 채워 저장한다(`fix_toc_page`, 261102-2).
Qt 비의존 — 워커 스레드에서 쓴다(응답성 SOT §4 ①: 문서는 이 객체가 따로 연다).
"""
from __future__ import annotations

import re
from pathlib import Path
from statistics import median
from typing import Callable, Optional

from viewer.i18n import tr

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
        self._picker = _ocr.LangPicker(self.lang)   # 261101-1(단어학습 SOT §14.8.1)
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
        # 261026-2(디자인 SOT §2.7): 날 글 'OCR p.12' 대신
        self.progress(tr("OCR {pg}쪽 읽는 중…").format(pg=pno1))
        self.pace()
        res = self._picker.read(self.doc, pno1 - 1, dpi=DPI, force_ocr=True, drop_watermark_bg=True)
        ws = res.get("words") or []
        dpi = int(res.get("dpi") or DPI)
        self.ran += 1
        saved = False
        if self.store is not None:
            try:
                self.store.save_page(self.fkey, pno1 - 1, res.get("text") or "", dpi=dpi,
                                     engine=res.get("engine") or "tesseract",
                                     source=res.get("source") or "ocr",
                                     conf=float(res.get("conf") or 0.0), words=ws, lang=res.get("lang") or self.lang)
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
        extra, img = [], None
        if self.run_ocr and not self.should_cancel():
            self.pace()
            try:
                img, _r, _sz = self._ocr.render_page(self.doc, pno1 - 1, dpi=DPI, drop_watermark_bg=True)
                extra = (self._ocr.ocr_image(img, lang=self._picker.lang, psm=TOC_PSM, dpi=DPI).get("words") or [])
            except Exception:
                extra = []
        width = float(self.doc.load_page(pno1 - 1).rect.width) * dpi / 72.0
        a = [_toc_parts(ln, width) for ln in group_lines(std_ws, dpi, raw=True)]
        b = [_toc_parts(ln, width) for ln in group_lines(extra, DPI, raw=True)] if extra else []
        merged = _merge_toc_lines(a, b)
        if img is not None and int(dpi) == DPI and "kor" in str(self._picker.lang).split("+"):
            # 261102-2(단어학습 SOT §14.8.4): 목차 제목의 잡글 낱말(`Ds Fi`=`1. 서 론`, `OB`=`1.3`)을 `kor` 로 다시 읽는다
            for m in merged:
                if self.should_cancel():
                    break
                try:
                    fixed = reread_toc_title(self._ocr, img, m.get("ws") or [])
                except Exception:
                    fixed = None
                if fixed:
                    m["title"] = fixed
                try:
                    longer = extend_spaced_title(self._ocr, img, m["title"], m.get("ws") or [])
                except Exception:
                    longer = None
                if longer:
                    m["title"] = longer
                m["title"] = _tidy_toc_title(m["title"])
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
            # 261102-2: 글자 사이를 크게 벌린 짧은 제목(`1. 서   론`·`<부   록>`)은 잇는다 — 뒤가 한두 음절 한글이고 제목이 아직 짧을 때
            if not (len(title_ws) <= 3 and re.fullmatch(r"[가-힣]{1,2}[>)]?", s) and not _LEADER.match(s)):
                break                              # 점선 리더 자리의 큰 빈틈
        if title_ws and _LEADER.match(s) and float(w.get("conf", 1.0)) < 0.7:
            break
        title_ws.append(w); prev = w
    # 끝에 붙은 잡글자 낱말을 떼어 낸다('설계법 아 이' → '설계법')
    while title_ws and _LEADER.match(str(title_ws[-1]["surface"])) and len(title_ws) > 1:
        title_ws.pop()
    title = _join(title_ws) if title_ws else ""
    return {"x0": ln["x0"], "cy": ln["cy"], "h": h, "title": title.strip(), "page": page,
            "n": sum(len(re.sub(r"\W", "", str(w["surface"]))) for w in title_ws), "ws": title_ws}


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
        # 261102-2: 흩어진 글 판독이 줄 첫머리(번호 자리)를 놓친 제목은 고르지 않는다(`DVD 설계…` 대신 `설계…` 가 뽑혀 번호가 사라졌다)
        if lb["title"] and (not la["title"] or (lb["n"] > la["n"] and lb["x0"] <= la["x0"] + la["h"] * 72.0 / DPI)):
            m["title"], m["x0"], m["n"], m["ws"] = lb["title"], min(la["x0"], lb["x0"]), lb["n"], lb.get("ws")
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


# ── 261102-2: 목차 제목의 잡글 낱말 다시 읽기 (단어학습 SOT §14.8.4) ───────────────────────
_HANGUL = re.compile(r"[가-힣]")
TOC_REREAD_CONF = 0.30       # 잡글 자리를 다시 읽은 글을 받는 평균 신뢰도(0~1)
TOC_CAPS_CONF = 0.80         # 대문자 4자 이상(`ALAR` — 진짜 약어 `AASHO`·`LTPP` 와 같은 꼴)을 한글로 바꾸는 신뢰도


def _toc_junk(s: str) -> bool:
    """목차 제목의 이 낱말이 잡글인가 — 한글·번호·문장부호·로마 숫자·영어 낱말(소문자 3자 이상, 대문자 4자 이상)은 아니다."""
    s = s.strip()
    if not s or _HANGUL.search(s):
        return False
    if re.fullmatch(r"[<(]?\d+(?:\.\d+)*\.?[>)]?|[^\w]+|[ivx]+\.?|[IVX]+\.?", s):   # 로마 숫자는 i·v·x 만(`DVD` 는 잡글)
        return False
    if re.search(r"[a-z]{3}", s) or re.match(r"[A-Z]{4,}", s):
        return False
    return True


def _num_like(s: str) -> bool:
    """점이 빠졌을 법한 번호(`31`·`(32`)."""
    return bool(re.fullmatch(r"[(]?\d{2,3}", s.strip()))


def _caps(s: str) -> bool:
    """대문자 3자 이상 — 진짜 약어(`BGT`·`TAT`·`AASHO`)와 같은 꼴이라 높은 신뢰도의 한글이거나 줄 첫 번호일 때만 바꾼다."""
    return bool(re.fullmatch(r"[A-Z]{3,}[,.]?", s.strip()))


def _keeps_number(orig: str, txt: str) -> bool:
    """원래 토막에 숫자가 있으면 다시 읽은 글이 그 숫자 모양을 지켜야 한다 — 뒤쪽이 같고(`A5.1`→`4.5.1`), 앞에 늘어난 숫자는
    원래 그 자리에 있던 영문 글자 수까지만(`/113`→`7113` 은 `/` 가 숫자가 된 것이라 받지 않는다), `-` 는 남아 있어야 한다(`6-2]`→`62` ✗)."""
    core = re.search(r"\d[\d.\-]*\d|\d", orig)
    if not core:
        return True
    oc = core.group(0)
    m = re.search(r"\d[\d.\-]*", txt)
    if not m or not m.group(0).rstrip(".").endswith(oc.rstrip(".")):
        return False
    extra = len(re.sub(r"\D", "", m.group(0))) - len(re.sub(r"\D", "", oc))
    return extra <= len(re.findall(r"[A-Za-z]", orig[:core.start()]))


def _tidy_toc_title(t: str) -> str:
    """번호 뒤 빈칸, 벌려 쓴 한 음절들(`서 론`·`부 록`)은 붙인다."""
    t = re.sub(r"^([<(]?\d+(?:\.\d+)*\.?)(?=[가-힣A-Za-z<(])", r"\1 ", t.strip())
    # 번호 뒤 제목 전체가 벌려 쓴 한 음절들일 때만(`1. 서 론`·`2.1.1 개 요`) — `및 석8` 같은 가운데 토막은 두다
    t = re.sub(r"^([<(]?\d+(?:\.\d+)*\.?\s+)([가-힣](?: [가-힣])+)$", lambda m: m.group(1) + m.group(2).replace(" ", ""), t)
    t = re.sub(r"<([가-힣 ]+)>", lambda m: "<" + m.group(1).replace(" ", "") + ">", t)   # `<참고문 헌>` → `<참고문헌>`
    return t


def reread_toc_title(ocr_mod, img, ws: list):
    """목차 줄 제목 낱말 중 잡글을 `kor` 로 다시 읽은 제목 → 새 제목 또는 None(바꿀 것 없음). 규칙은 `_reread_toc_words`."""
    new = _reread_toc_words(ocr_mod, img, ws)
    return (_tidy_toc_title(_join(new)) or None) if new is not None else None


def _reread_toc_words(ocr_mod, img, ws: list, drop_tail: bool = True):
    """목차 줄 제목 낱말(`ws`, 쪽 그림 픽셀) 중 잡글을 `kor` 한 줄 읽기로 바꾼다 → 새 낱말 목록 또는 None(바꿀 것 없음).

    `kor+eng` 판독은 가는 글씨 목차의 번호·한글을 영문 잡글로 읽는다(_96 보고서: `1.3`→`OB`, `2.1.2`→`DVD`,
    `4.5.1`→`A5.1`, `1. 서 론`→`Ds Fi`, `개 요`→`개 Go`, `4.3.3 시험시공`→`ABS ALAR`). 제목 자리를 `kor` 로 한 줄 읽으면
    맞게 나오지만 영어 낱말(`AASHO`·`Asphalt Institute`·`LTPP(Long …`)은 망가지므로, **잡글 낱말 자리만** 바꾼다.
      - 잇단 잡글 낱말은 한 묶음으로 — 그 자리에 가운데가 든 `kor` 한글·번호 낱말로(문장부호는 뺀다). 없으면 그 자리만 한 낱말로(psm 8)
      - 받는 조건: 평균 신뢰도 `TOC_REREAD_CONF` 이상. 대문자 4자 이상 묶음은 `TOC_CAPS_CONF` 이상의 한글일 때만
      - 줄 첫 번호(`31`)는 숫자가 같고 점이 더 많을 때만(단어학습 SOT §14.8.3 과 같은 규칙)
      - 끝에 남은 잡글(점선 리더 조각 `PoC`)은 `kor` 로도 글이 없으면 뗀다"""
    if not ws:
        return None
    flags = []
    for k, w in enumerate(ws):
        s = str(w["surface"])
        kind = ("caps" if _caps(s) else "junk") if _toc_junk(s) else ("num" if (k == 0 and _num_like(s)) else ("caps" if _caps(s) else ""))
        flags.append(kind)
    if not any(flags):
        return None
    groups, k = [], 0
    while k < len(ws):
        if flags[k]:
            j = k
            while j + 1 < len(ws) and flags[j + 1] and flags[j + 1] != "num":
                j += 1
            groups.append((k, j))
            k = j + 1
        else:
            k += 1
    W, H = img.size
    pad = 6
    box = (max(0, int(min(float(w["x0"]) for w in ws)) - pad), max(0, int(min(float(w["y0"]) for w in ws)) - pad),
           min(W, int(max(float(w["x1"]) for w in ws)) + pad), min(H, int(max(float(w["y1"]) for w in ws)) + pad))
    kor = [q for q in ocr_mod.read_line_words(img, box, "kor")                 # 점만 있는 낱말(티)은 뺀다
           if re.fullmatch(r"[가-힣0-9.<>()]+", q["surface"]) and not re.fullmatch(r"\.+", q["surface"])]
    new = list(ws)
    drop = set()
    changed = False
    for g0, g1 in groups:
        if g0 > 0 and re.search(r"[A-Za-z]{3}", str(ws[g0 - 1]["surface"])):
            continue                                   # 영어 문맥(`Asphalt Institute(AI)`)의 토막은 한글로 읽지 않는다
        a, b = float(ws[g0]["x0"]), float(ws[g1]["x1"])
        keep = [(float(ws[i]["x0"]), float(ws[i]["x1"])) for i in range(len(ws)) if not flags[i]]
        # 남기는 낱말 위에 놓인 `kor` 낱말은 쓰지 않는다(`Bel` + `형태의` → `형태형태의` 가 되지 않게)
        cover = [q for q in kor if a - pad <= (q["x0"] + q["x1"]) / 2.0 <= b + pad
                 and not any(k0 <= (q["x0"] + q["x1"]) / 2.0 <= k1 for k0, k1 in keep)]
        if not cover or sum(q["conf"] for q in cover) / len(cover) < TOC_REREAD_CONF:
            bx = (max(0, int(a) - pad), max(0, int(min(float(ws[i]["y0"]) for i in range(g0, g1 + 1))) - pad),
                  min(W, int(b) + pad), min(H, int(max(float(ws[i]["y1"]) for i in range(g0, g1 + 1))) + pad))
            one = [q for q in ocr_mod.read_line_words(img, bx, "kor", psm=8)
                   if re.fullmatch(r"[가-힣0-9.<>()]+", q["surface"])]
            if one and (not cover or sum(q["conf"] for q in one) / len(one) > sum(q["conf"] for q in cover) / len(cover)):
                cover = one
        if cover:
            for i in range(g0, g1 + 1):                # 묶음 안에서 `kor` 가 덮지 못한 낱말(`Ds Fi` 의 `Fi`=`론`)은 그 자리만
                wi = ws[i]
                if not any(float(wi["x0"]) - pad <= (q["x0"] + q["x1"]) / 2.0 <= float(wi["x1"]) + pad for q in cover):
                    bx = (max(0, int(float(wi["x0"])) - pad), max(0, int(float(wi["y0"])) - pad),
                          min(W, int(float(wi["x1"])) + pad), min(H, int(float(wi["y1"])) + pad))
                    cover += [q for q in ocr_mod.read_line_words(img, bx, "kor", psm=8)
                              if re.fullmatch(r"[가-힣]+", q["surface"]) and q["conf"] >= TOC_REREAD_CONF]
            cover.sort(key=lambda q: q["x0"])
        txt = " ".join(q["surface"] for q in cover)
        conf = (sum(q["conf"] for q in cover) / len(cover)) if cover else 0.0
        kinds = {flags[i] for i in range(g0, g1 + 1)}
        dotted = g0 == 0 and bool(re.match(r"\d+(?:\.\d+)+\.?", txt))     # 줄 첫 번호로 시작(`ABS ALAR`=`4.3.3 시험시공`)
        if kinds == {"caps"} and not dotted:           # 대문자 약어 꼴은 높은 신뢰도의 한글일 때만(줄 첫 번호 `DVD`=`2.1.2` 는 예외)
            ok = bool(txt) and conf >= TOC_CAPS_CONF and bool(_HANGUL.search(txt))
        else:
            ok = bool(txt) and conf >= TOC_REREAD_CONF
        orig = " ".join(str(ws[i]["surface"]) for i in range(g0, g1 + 1))
        if ok and "num" not in kinds and not _keeps_number(orig, txt.replace(" ", "")):
            ok = False
        if ok and g0 > 0 and not re.search(r"\d", orig) and re.search(r"\d", txt):
            ok = False                                 # 숫자 없던 줄 가운데 토막에 숫자가 생기면(`EAS`→`난독 상승 2`) 받지 않는다
        if ok and g0 == 0 and re.fullmatch(r"\d{2,}", txt.replace(" ", "")):
            ok = False                                 # 줄 첫머리의 점 없는 두 자리 수(`OB`→`18`)는 번호가 아니다 — 1.3 을 1.8 로 읽기도 한다
        if ok and "num" in kinds:
            txt = txt.replace(" ", "")
            digits = re.sub(r"\D", "", str(ws[g0]["surface"]))
            ok = bool(re.fullmatch(r"\d+(?:\.\d+)+\.?", txt)) and re.sub(r"\D", "", txt) == digits
        if ok:
            if re.match(r"\.+\d", txt):
                txt = txt.lstrip(".")
            new[g0] = dict(ws[g0], surface=txt, conf=conf, x1=ws[g1]["x1"])
            drop.update(range(g0 + 1, g1 + 1))
            changed = True
        elif drop_tail and not cover and g1 == len(ws) - 1 and g0 > 0 and kinds == {"junk"}:
            drop.update(range(g0, g1 + 1))            # 끝에 붙은 점선 리더 조각
            changed = True
    if not changed:
        return None
    return [w for i, w in enumerate(new) if i not in drop]


def extend_spaced_title(ocr_mod, img, title: str, ws: list):
    """글자 사이를 크게 벌린 짧은 제목이 첫 음절에서 끊겼으면(`1. 서`·`7. 결`·`<부`) 오른쪽 띠를 `kor` 로 읽어 잇는다 → 새 제목 또는 None.

    판독이 `론`·`록>` 을 점선 리더 쪽 빈틈 너머로 두어 제목이 한 음절로 남았다(_96 보고서 목차 `1. 서 론`·`7. 결 론`·`<부 록>`).
    제목 끝에서 줄 높이의 `TOC_SPACED_BAND` 배까지만 본다 — 한두 음절 한글(필요하면 `>`)만 받는다."""
    q = _spaced_tail_word(ocr_mod, img, title, ws)
    return _tidy_toc_title((title or "").strip() + " " + q["surface"]) if q else None


def _spaced_tail_word(ocr_mod, img, title: str, ws: list):
    """`extend_spaced_title` 의 다음 음절 낱말(쪽 그림 좌표) → `{surface, x0, y0, x1, y1, conf}` 또는 None."""
    t = (title or "").strip()
    if not ws or not re.fullmatch(r"(?:[<(]?\d+(?:\.\d+)*\.?\s*[가-힣]|<[가-힣]{1,3})", t):
        return None
    W, H = img.size
    x1 = int(max(float(w["x1"]) for w in ws))
    y0 = int(min(float(w["y0"]) for w in ws))
    y1 = int(max(float(w["y1"]) for w in ws))
    h = max(1, y1 - y0)
    bx = (min(W - 1, x1 + 2), max(0, y0 - 6), min(W, x1 + int(TOC_SPACED_BAND * h)), min(H, y1 + 6))
    if bx[2] - bx[0] < h:
        return None
    m = hit = None
    for psm in (7, 10):                          # 띠가 점선 리더를 품으면 psm 7 이 비곤 한다 — 한 글자 모드로 한 번 더
        for hit in ocr_mod.read_line_words(img, bx, "kor", psm=psm):
            m = re.match(r"([가-힣]{1,2})(>?)", hit["surface"])
            if m and hit["conf"] >= TOC_REREAD_CONF:
                break
            m = None
        if m:
            break
    if not m:
        return None
    return dict(hit, surface=m.group(1) + (">" if t.startswith("<") else ""))


# ── 261102-2: 목차 쪽 OCR 자체를 고친다 — 텍스트 창·글자층·검색도 같은 글 (단어학습 SOT §14.8.4) ──────────
TOC_PAGE_MIN = 8             # 목차 쪽으로 볼 번호 줄(`2.1.1 …`·`1. …`) 수의 하한
TOC_PAGE_SHARE = 0.5         # … 그리고 쪽 줄 가운데 번호 줄의 몫
_TOC_NO = re.compile(r"[<(]?\d+(?:\.\d+)*\.?[>)]?")


def looks_like_toc(lines: list) -> bool:
    """줄(`group_lines`) 대부분이 절 번호로 시작하면 목차 쪽 — 본문의 번호 목록과 가르려고 여러 단 번호(`2.1`)도 셋 이상."""
    return toc_text_lines([" ".join(str(w["surface"]) for w in ln["words"]) for ln in lines if ln.get("words")])


def _toc_numbered(text) -> bool:
    """목차 번호 줄인가 — 첫 낱말이 절 번호(`2.1.1`·`1.`)이고 그 뒤에 제목 글자가 있다."""
    tok = str(text).split(None, 1)
    if not tok:
        return False
    s, rest = tok[0], (tok[1] if len(tok) > 1 else "")
    return bool((_TOC_NO.fullmatch(s) and re.search(r"\d\.\d", s) or re.fullmatch(r"\d{1,2}\.", s))
                and re.search(r"[가-힣A-Za-z]", rest))


def toc_text_lines(texts: list) -> bool:
    """줄 글 목록으로 목차 쪽인지 — `looks_like_toc` 의 판정. 텍스트 창 줄 잇기도 이것을 쓴다(텍스트 창 SOT §3.7.15).
    번호 줄은 절 번호 **뒤에 제목 글자**가 있어야 한다 — 수 표(`2.147 …`·`12.5`)를 목차로 보지 않게."""
    starts, num = 0, []
    for t in texts:
        tok = str(t).split(None, 1)
        if not tok:
            continue
        starts += 1
        if _toc_numbered(t):
            num.append(tok[0])
    deep = [s for s in num if re.search(r"\d\.\d", s)]
    return len(num) >= TOC_PAGE_MIN and len(num) >= TOC_PAGE_SHARE * starts and len(deep) >= 3


_SEC_NO = re.compile(r"\d+(?:\.\d+)+\.?|\d{1,2}\.")


def _overlaps(w, ws) -> bool:
    """낱말 상자 `w` 가 `ws` 의 어느 상자와 가로·세로 모두 겹치는가."""
    for q in ws:
        if (min(float(w["x1"]), float(q["x1"])) > max(float(w["x0"]), float(q["x0"]))
                and min(float(w["y1"]), float(q["y1"])) > max(float(w["y0"]), float(q["y0"]))):
            return True
    return False


def _next_nos(no: str) -> list:
    """앞 줄 절 번호 다음에 올 수 있는 번호 — `1.2` → `1.3`·`1.2.1`·`2.`, `2.` → `2.1`·`3.`."""
    try:
        p = [int(x) for x in no.rstrip(".").split(".")]
    except ValueError:
        return []
    if len(p) == 1:
        return [f"{p[0]}.1", f"{p[0] + 1}."]
    out = [".".join(map(str, p[:-1] + [p[-1] + 1])), no.rstrip(".") + ".1", f"{p[0] + 1}."]
    if len(p) >= 3:
        out.append(".".join(map(str, p[:-2] + [p[-2] + 1])))
    return out


TOC_SWAP_LOW = 0.6          # 표준 판독 낱말이 이보다 낮은 신뢰도이고
TOC_SWAP_HIGH = 0.8         # … 같은 자리 흩어진 글 판독이 이 이상이면 그 글로(`NASHO` 0.51 → `AASHO` 0.91, `ACGO-70` 0.31 → `AC60-70` 0.91)


def _fill_toc_from_sparse(lines: list, sparse: list, width: float) -> tuple:
    """목차 쪽 표준 판독 줄(`lines`, 제자리에서 고침)을 흩어진 글 판독 줄(`sparse`)로 채운다 → (바꿨나, 새 줄들).
    ① 쪽 번호를 못 읽은 줄에 쪽 번호 ② 번호를 잘못 읽은 줄(`(32`·`OB`)의 번호를 — 같은 숫자의 바른 번호, 또는 앞 줄 번호 다음에 올 번호 중
    숫자가 같은 것(`1.2` 다음 `(13` → `1.3`)으로 ③ 표준 판독에 통째로 없는 번호 줄(`3.6 요약`)·꺾쇠 줄(`<참고문헌>`)을 제목·쪽 번호만
    ④ 표준 제목이 흩어진 글 제목의 앞부분이면(`평가기` / `평가기준치`) 긴 쪽으로 ⑤ 신뢰도 낮은 영문·숫자 낱말은 같은 자리·같은 길이의
    높은 신뢰도 글, 또는 같은 쪽에서 높은 신뢰도로 읽힌 글로(`NASHO`→`AASHO`·`AC60O~70`→`AC60~70`), 제목 끝 쉼표(`재료,`)는 떼고.
    점선 리더 잡글은 더하지 않는다."""
    changed, used, all_ws = False, set(), [w for ln in lines for w in ln["words"]]
    prev_no = None
    sure = {str(w["surface"]) for w in all_ws if float(w.get("conf", 0.0)) >= TOC_SWAP_HIGH}
    for ln in lines:
        best, bd = None, None
        for j, sp in enumerate(sparse):
            d = abs(ln["cy"] - sp["cy"])
            if j not in used and d <= 0.6 * max(ln["h"], sp["h"]) and (bd is None or d < bd):
                best, bd = j, d
        ws = ln["words"]
        if best is not None:
            used.add(best)
            sw = sparse[best]["words"]
            tail = sw[-1]
            has_page = float(ws[-1]["x0"]) >= 0.70 * width and re.search(r"\d", str(ws[-1]["surface"]))
            if (not has_page and float(tail["x0"]) >= 0.70 * width and re.fullmatch(r"\d{1,4}", str(tail["surface"]))
                    and not _overlaps(tail, all_ws)):
                ws.append(dict(tail))                                                     # ①
                changed = True
            f0, s0 = str(ws[0]["surface"]), str(sw[0]["surface"])
            near = abs(float(ws[0]["x0"]) - float(sw[0]["x0"])) <= ln["h"]
            if not _SEC_NO.fullmatch(f0) and not _HANGUL.search(f0) and near:
                dg = re.sub(r"\D", "", f0) or re.sub(r"\D", "", s0)
                cand = ([s0] if _SEC_NO.fullmatch(s0) else []) + (_next_nos(prev_no) if prev_no else [])
                hit = next((c for c in cand if dg and re.sub(r"\D", "", c) == dg), None)
                if hit:
                    ws[0] = dict(ws[0], surface=hit)                                      # ②
                    changed = True
            for i, w in enumerate(ws):                                                    # ⑤
                s = str(w["surface"])
                if float(w["x0"]) >= 0.70 * width:
                    continue
                qs = [q for q in sw if _overlaps(q, [w])]
                if len(qs) != 1 or str(qs[0]["surface"]) == s:
                    continue
                q, qc = str(qs[0]["surface"]), float(qs[0].get("conf", 0.0))
                if q == s.rstrip(",") and qc >= TOC_SWAP_HIGH:
                    ok = True                       # 제목 끝에 붙은 쉼표(`재료,`) — 같은 자리 판독에는 없다
                else:
                    # 같은 자리 높은 신뢰도 글, 또는 같은 쪽에서 높은 신뢰도로 읽힌 글(`AC60O~70` 0.37 / 4.4 줄의 `AC60~70` 0.89)
                    ok = (not _HANGUL.search(s) and not _HANGUL.search(q) and float(w.get("conf", 1.0)) < TOC_SWAP_LOW
                          and abs(len(q) - len(s)) <= 1 and (qc >= TOC_SWAP_HIGH or q in sure))
                if ok:
                    ws[i] = dict(w, surface=q, conf=qc)
                    changed = True
            ta, tb = _toc_parts(ln, width), _toc_parts(sparse[best], width)
            a, b = re.sub(r"\s", "", ta["title"]), re.sub(r"\s", "", tb["title"])
            if len(a) >= 3 and len(b) > len(a) and b.startswith(a) and _HANGUL.search(b[len(a):]):
                ids = {id(w) for w in ta["ws"]}                                           # ④
                ln["words"] = ws = sorted([w for w in ws if id(w) not in ids] + [dict(w) for w in tb["ws"]],
                                          key=lambda w: float(w["x0"]))
                changed = True
        if _SEC_NO.fullmatch(str(ws[0]["surface"])):
            prev_no = str(ws[0]["surface"])
    extra = []
    for j, sp in enumerate(sparse):
        if j in used:
            continue
        tp = _toc_parts(sp, width)
        new = list(tp["ws"]) + ([sp["words"][-1]] if tp["page"] is not None else [])
        ok = _toc_numbered(tp["title"]) or (tp["title"].startswith("<") and tp["page"] is not None)
        if tp["ws"] and ok and not any(_overlaps(w, all_ws) for w in new):
            extra.append(dict(sp, words=[dict(w) for w in new]))                         # ③
    return changed or bool(extra), extra


def _cho(c: str) -> int:
    return (ord(c) - 0xAC00) // 588


TOC_VOCAB_MIN = 3            # 한 번 나온 세 음절을 고칠 때 맞는 쪽이 쪽 안에 나와야 하는 횟수 — 2 로는 `포장상태`→`포장설태`(`포장설계` 둘)·`저항의`→`저항인`(`적인 측면` 둘)이 났다


def _fix_by_page_vocab(lines_ws: list) -> bool:
    """목차 쪽 안에서 한 번만 나온 세 음절이 `TOC_VOCAB_MIN` 번 이상 나온 세 음절과 한 음절만 다르고, 그 음절의 첫소리가 같고 그 음절이 쪽에서 거기 하나뿐이면 그것으로
    (`5.1 샤후관측` ↔ `사후관측` 셋 — `샤` 는 신뢰도 0.86 이라 신뢰도로는 못 가른다). 쪽 번호는 보지 않는다. 줄마다 한 곳만."""
    from collections import Counter
    seqs = []
    for ws in lines_ws:
        seqs.append([(i, k, c) for i, w in enumerate(ws) if not re.fullmatch(r"\d+", str(w["surface"]))
                     for k, c in enumerate(str(w["surface"])) if "가" <= c <= "힣"])
    cnt = Counter("".join(c for *_x, c in seq[s:s + 3]) for seq in seqs for s in range(len(seq) - 2))
    syl = Counter(c for seq in seqs for *_x, c in seq)
    changed = False
    for li, seq in enumerate(seqs):
        for s in range(len(seq) - 2):
            win = "".join(c for *_x, c in seq[s:s + 3])
            if cnt[win] != 1:
                continue
            cands = [v for v, n in cnt.items() if n >= TOC_VOCAB_MIN and sum(x != y for x, y in zip(v, win)) == 1]
            if len(cands) != 1:
                continue
            v = cands[0]
            p = next(q for q in range(3) if v[q] != win[q])
            if _cho(v[p]) != _cho(win[p]) or syl[win[p]] > 1:
                continue
            i, k, _c = seq[s + p]
            w = lines_ws[li][i]
            t = str(w["surface"])
            lines_ws[li][i] = dict(w, surface=t[:k] + v[p] + t[k + 1:])
            changed = True
            break
    return changed


def _clean_toc_rest(rest: list, page_w, page) -> list:
    """목차 줄의 제목 뒤 낱말(`rest`)에서 점선 리더를 읽은 잡글(`아아아`·`ㅇ`·`eee`)을 빼고, 잡글이 붙은 쪽 번호(`아아아122`·`ll`)는
    쪽 번호(`122`·`11`)만 남긴다 — 같은 객체를 그대로 두면 바뀌지 않은 것(사용자 지시 '픽스 되지 않은 것 수정')."""
    out = []
    for w in rest:
        s = str(w["surface"])
        if w is page_w:
            out.append(w if s == str(page) else dict(w, surface=str(page)))
        elif not _LEADER.match(s):
            out.append(w)
    return out


def fix_toc_page(ocr_mod, img, res: dict, dpi: int, lang: str = "kor+eng") -> bool:
    """`build_page` 결과(`res`, 쪽 그림 픽셀 낱말)가 목차 쪽이면 줄마다 제목의 잡글 낱말을 `kor` 로 다시 읽고 벌린 제목을 잇는다.
    `res` 의 `words`·`text` 를 바꾼다 → 바꿨으면 True. 책갈피의 `toc_lines` 와 같은 규칙(`_reread_toc_words`·`_spaced_tail_word`) —
    텍스트 창·글자층·검색·단어장이 모두 이 글을 쓴다(사용자 보고 '텍스트 창 4쪽 OCR 다시 읽기에도 1. 서론이 안 된다').
    표준 판독이 놓친 쪽 번호·번호·줄은 흩어진 글 판독(psm 11) 한 번으로 채운다(`_fill_toc_from_sparse`, 사용자 보고 '5쪽 3.6 요약이 없다')."""
    words = list(res.get("words") or [])
    lines = group_lines(words, dpi, raw=True)
    if not lines or not looks_like_toc(lines):
        return False
    width = float(img.size[0])

    def reread(ln) -> bool:
        """줄의 제목 잡글 낱말을 `kor` 로 다시 읽고 벌린 제목 끝 음절을 더한다 — `ln["words"]` 를 바꾼다."""
        tw = _toc_parts(ln, width)["ws"]
        try:
            new = _reread_toc_words(ocr_mod, img, tw, drop_tail=False)    # 지우는 것은 아래 `_clean_toc_rest` 가 제목 뒤에서만
        except Exception:
            new = None
        cur = list(new) if new is not None else list(tw)
        try:
            tail = _spaced_tail_word(ocr_mod, img, _join(cur), cur)
        except Exception:
            tail = None
        if tail is not None:
            cur.append(tail)
        if new is None and tail is None:
            return False
        # 벌린 음절은 붙이지 않는다 — Tesseract 는 한글을 음절마다 낱말로 내놓아, 붙임은 쪽 글 잇기(빈틈 규칙)가 정한다
        ids = {id(w) for w in tw}
        ln["words"] = sorted(cur + [w for w in ln["words"] if id(w) not in ids], key=lambda w: float(w["x0"]))
        return True

    changed = False
    for ln in lines:                    # 먼저 `kor` 다시 읽기 — 흩어진 글 판독의 번호 고침이 `Ds Fi`(=`1. 서 론`)의 `Ds` 만 `1.` 로 바꾸지 않게
        ln["words"] = list(ln["words"])
        changed = reread(ln) or changed
    try:
        sparse = group_lines(ocr_mod.ocr_image(img, lang=lang, psm=TOC_PSM, dpi=dpi).get("words") or [], dpi, raw=True)
    except Exception:
        sparse = []
    filled, extra = _fill_toc_from_sparse(lines, sparse, width) if sparse else (False, [])
    for ln in extra:
        reread(ln)
    changed = changed or filled
    out = []
    for ln in sorted(lines + extra, key=lambda ln: ln["cy"]):
        tp = _toc_parts(ln, width)
        ids = {id(w) for w in tp["ws"]}
        rest = [w for w in ln["words"] if id(w) not in ids]
        clean = _clean_toc_rest(rest, ln["words"][-1] if tp["page"] is not None else None, tp["page"])
        if clean != rest:
            changed = True
            out.append(sorted(list(tp["ws"]) + clean, key=lambda w: float(w["x0"])))
        else:
            out.append(list(ln["words"]))
    if _fix_by_page_vocab(out):
        changed = True
    if not changed:
        return False
    res["words"] = [w for ws in out for w in ws]
    parts = []                                   # 쪽 하나로 잇는다 — 한글 붙임 문턱은 쪽의 빈틈 분포에서(텍스트 창 SOT §3.6.12)
    for ws in out:
        if parts:
            parts.append("\n")
        parts.extend(ws)
    res["text"] = ocr_mod._join_words_by_gap(parts)
    return True


TOC_SPACED_BAND = 2.0       # 벌린 제목의 다음 음절을 찾는 띠 폭(줄 높이의 배) — 넓히면 점선 리더가 들어 판독이 빈다(실측 `론` 0.92 → 없음)
