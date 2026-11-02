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


def toc_text_lines(texts: list) -> bool:
    """줄 글 목록으로 목차 쪽인지 — `looks_like_toc` 의 판정. 텍스트 창 줄 잇기도 이것을 쓴다(텍스트 창 SOT §3.7.15).
    번호 줄은 절 번호 **뒤에 제목 글자**가 있어야 한다 — 수 표(`2.147 …`·`12.5`)를 목차로 보지 않게."""
    starts, num = 0, []
    for t in texts:
        tok = str(t).split(None, 1)
        if not tok:
            continue
        starts += 1
        s, rest = tok[0], (tok[1] if len(tok) > 1 else "")
        if ((_TOC_NO.fullmatch(s) and re.search(r"\d\.\d", s) or re.fullmatch(r"\d{1,2}\.", s))
                and re.search(r"[가-힣A-Za-z]", rest)):
            num.append(s)
    deep = [s for s in num if re.search(r"\d\.\d", s)]
    return len(num) >= TOC_PAGE_MIN and len(num) >= TOC_PAGE_SHARE * starts and len(deep) >= 3


def fix_toc_page(ocr_mod, img, res: dict, dpi: int) -> bool:
    """`build_page` 결과(`res`, 쪽 그림 픽셀 낱말)가 목차 쪽이면 줄마다 제목의 잡글 낱말을 `kor` 로 다시 읽고 벌린 제목을 잇는다.
    `res` 의 `words`·`text` 를 바꾼다 → 바꿨으면 True. 책갈피의 `toc_lines` 와 같은 규칙(`_reread_toc_words`·`_spaced_tail_word`) —
    텍스트 창·글자층·검색·단어장이 모두 이 글을 쓴다(사용자 보고 '텍스트 창 4쪽 OCR 다시 읽기에도 1. 서론이 안 된다')."""
    words = list(res.get("words") or [])
    lines = group_lines(words, dpi, raw=True)
    if not lines or not looks_like_toc(lines):
        return False
    width = float(img.size[0])
    changed = False
    out = []
    for ln in lines:
        tp = _toc_parts(ln, width)
        tw = tp["ws"]
        new = None
        try:
            new = _reread_toc_words(ocr_mod, img, tw, drop_tail=False)    # 쪽 글은 지우지 않는다(점선 리더 조각은 책갈피 쪽이 뗀다)
        except Exception:
            new = None
        cur = list(new) if new is not None else list(tw)
        try:
            tail = _spaced_tail_word(ocr_mod, img, _join(cur), cur)
        except Exception:
            tail = None
        if tail is not None:
            cur.append(tail)
        # 벌린 음절은 붙이지 않는다 — Tesseract 는 한글을 음절마다 낱말로 내놓아, 붙임은 쪽 글 잇기(빈틈 규칙)가 정한다
        if new is not None or tail is not None:
            changed = True
            ids = {id(w) for w in tw}
            rest = [w for w in ln["words"] if id(w) not in ids]     # 쪽 번호·점선 리더는 그대로
            out.append(sorted(cur + rest, key=lambda w: float(w["x0"])))
        else:
            out.append(list(ln["words"]))
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
