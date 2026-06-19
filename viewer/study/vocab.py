"""어휘 빌드 — 표제어화·난이도·뜻·예문 (계획서 P2).

ocr_page 텍스트(study.db) → 표제어 → vocab/vocab_page/vocab_def/vocab_example.
P0 검증 반영(§14.3): 줄바꿈 하이픈 복원·반복 머리말 제거·잡음(의성어/미수록) 필터.

난이도(zipf 밴딩, §3.3): zipf≥4.5 초급 / 3.0~4.5 중급 / <3.0 고급.
  - 영어: wordfreq(en) + WordNet 뜻·예문 (P0 완전 검증).
  - 한국어: wordfreq(ko)는 MeCab 필요(§15.2) → 우선 '등급별 어휘목록'(방안 A) 사용,
            없으면 wordfreq 시도, 둘 다 불가면 level='미정'. 뜻은 사전 없음(본문 예문만).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from viewer.study.ocr import dehyphenate, strip_repeated_lines

_WORD_EN = re.compile(r"[A-Za-z]{2,}")
_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")   # 개행도 분할(한국어 표/줄 예문 정리; 영어 OCR 은 개행 없음)

STOP_EN = set(
    "the a an and or of to in on at for is are was were be been being it this that "
    "these those i you he she we they my your his her our their as with by from up "
    "out so no not but if then than into over under can will would could should may "
    "might do does did have has had me him them what when where who how all any each "
    "one there here about which would your you're don't i'm it's".split())


def mend_ocr_hyphens_en(text: str) -> str:
    """OCR 줄바꿈이 공백이 된 'com- puter' 류 복원 (영어). 빈도로 안전 판정:
    왼쪽 조각이 드물고(zipf<2.5) 결합형이 흔하면(zipf≥3) 결합. 'well- being' 등은 보존."""
    try:
        from wordfreq import zipf_frequency
    except Exception:
        return text

    def repl(m):
        a, b = m.group(1), m.group(2)
        joined = a + b
        if (zipf_frequency(a.lower(), "en") < 2.5
                and zipf_frequency(joined.lower(), "en") >= 3.0):
            return joined
        return m.group(0)

    return re.sub(r"([A-Za-z]{2,})-\s+([A-Za-z]{2,})", repl, text)


def band(zipf: float) -> str:
    if zipf >= 4.5:
        return "초급"
    if zipf >= 3.0:
        return "중급"
    return "고급"


# --- 영어 ------------------------------------------------------------------
_LEMMATIZER = None
_WN_READY: Optional[bool] = None


def _ensure_nltk():
    global _LEMMATIZER, _WN_READY
    if _WN_READY is not None:
        return
    try:
        import sys, nltk
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bundled = str(Path(meipass) / "nltk_data")
            if bundled not in nltk.data.path:
                nltk.data.path.insert(0, bundled)
        from nltk.stem import WordNetLemmatizer
        from nltk.corpus import wordnet as wn
        wn.synsets("test")  # 데이터 로드 확인
        _LEMMATIZER = WordNetLemmatizer()
        _WN_READY = True
    except Exception:
        _WN_READY = False


def lemma_en(word: str) -> str:
    _ensure_nltk()
    if not _LEMMATIZER:
        return word
    n = _LEMMATIZER.lemmatize(word, "n")
    if n != word:
        return n
    return _LEMMATIZER.lemmatize(word, "v")


def _wn_synsets(lemma: str):
    _ensure_nltk()
    if not _WN_READY:
        return []
    from nltk.corpus import wordnet as wn
    return wn.synsets(lemma)


def is_noise_en(lemma: str, zipf: float, has_syn: bool) -> bool:
    """P0 잡음 필터: 의성어/미수록·짧음 제거. 단 흔한 단어(zipf≥3)는 사전 없어도 보존."""
    if len(lemma) < 3 or not lemma.isalpha() or lemma in STOP_EN:
        return True
    if re.search(r"(.)\1\1", lemma):          # 같은 글자 3연속(waaaait)
        return True
    if not has_syn and zipf < 3.0:            # 사전 미수록 + 희귀(pfft 2.96) = 잡음
        return True
    return False


# --- 한국어 ----------------------------------------------------------------
_KIWI = None
_KO_LEVELS: Optional[dict] = None
_KO_CONTENT = {"NNG", "NNP", "VV", "VA", "MAG"}


def _ensure_kiwi():
    global _KIWI
    if _KIWI is None:
        from kiwipiepy import Kiwi
        _KIWI = Kiwi()
    return _KIWI


def _load_ko_levels() -> dict:
    """방안 A: resources/ko_levels.csv (lemma,level) 동봉 시 로드. 없으면 빈 dict."""
    global _KO_LEVELS
    if _KO_LEVELS is not None:
        return _KO_LEVELS
    _KO_LEVELS = {}
    try:
        from viewer.resources_path import resource_path
        csv = Path(resource_path("ko_levels.csv"))
    except Exception:
        csv = Path(__file__).resolve().parents[2] / "resources" / "ko_levels.csv"
    if csv.exists():
        import csv as _csv
        with open(csv, encoding="utf-8") as f:
            for row in _csv.reader(f):
                if len(row) >= 2 and row[0].strip():
                    _KO_LEVELS[row[0].strip()] = row[1].strip()
    return _KO_LEVELS


_EN_KO: Optional[dict] = None


def _load_en_ko() -> dict:
    """영어→한국어 사전 (kengdic 역방향). resources/en_ko_dict.csv."""
    global _EN_KO
    if _EN_KO is not None:
        return _EN_KO
    _EN_KO = {}
    try:
        from viewer.resources_path import resource_path
        csv_p = Path(resource_path("en_ko_dict.csv"))
    except Exception:
        csv_p = Path(__file__).resolve().parents[2] / "resources" / "en_ko_dict.csv"
    if csv_p.exists():
        import csv as _csv
        with open(csv_p, encoding="utf-8") as f:
            for row in _csv.reader(f):
                if len(row) >= 2 and row[0].strip():
                    _EN_KO[row[0].strip()] = row[1].strip()
    return _EN_KO


def define_en_ko(lemma: str) -> Optional[str]:
    """영어 표제어의 한글 뜻(있으면 문자열)."""
    d = _load_en_ko()
    return d.get(lemma) if d else None


_KO_EN: Optional[dict] = None


def _load_ko_en() -> dict:
    """kengdic 기반 한영사전 (surface→영어뜻). resources/ko_en_dict.csv."""
    global _KO_EN
    if _KO_EN is not None:
        return _KO_EN
    _KO_EN = {}
    try:
        from viewer.resources_path import resource_path
        csv_p = Path(resource_path("ko_en_dict.csv"))
    except Exception:
        csv_p = Path(__file__).resolve().parents[2] / "resources" / "ko_en_dict.csv"
    if csv_p.exists():
        import csv as _csv
        with open(csv_p, encoding="utf-8") as f:
            for row in _csv.reader(f):
                if len(row) >= 2 and row[0].strip():
                    _KO_EN[row[0].strip()] = row[1].strip()
    return _KO_EN


def define_ko_en(lemma: str) -> list[str]:
    """한국어 표제어의 영어 뜻 목록(한영사전 kengdic). 용언은 다양한 형태로 조회."""
    d = _load_ko_en()
    if not d:
        return []
    base = lemma[:-1] if lemma.endswith("다") else lemma
    for key in (lemma, base, base + "다"):
        if key in d:
            return [g.strip() for g in d[key].split(";") if g.strip()][:3]
    # 합성어 폴백: 전체를 덮는 깔끔한 2분할(접두+접미 모두 사전 등재). 가장 긴 접두 우선.
    n = len(base)
    for pi in range(n - 2, 1, -1):              # 두 성분 모두 2글자 이상(1글자=다의 노이즈 방지)
        pre, suf = base[:pi], base[pi:]
        if len(suf) >= 2 and pre in d and suf in d:
            def first(g):  # 첫 뜻만(노이즈 축소)
                return g.split(";")[0].split(",")[0].strip()
            return [f"{first(d[pre])} + {first(d[suf])}"]
    return []


def level_ko(lemma: str) -> tuple[str, Optional[float]]:
    """한국어 난이도 — 등급목록(wordfreq 상위 ~25k 흔한 단어) 기반.
    목록에 있으면 그 등급(초/중급), **없으면 희귀어 → 고급**.
    목록이 없을 때만(개발) wordfreq(ko) 시도, 그마저 불가면 '미정'."""
    levels = _load_ko_levels()
    base = lemma[:-1] if lemma.endswith("다") else lemma
    if levels:
        if lemma in levels:
            return levels[lemma], None
        if base in levels:
            return levels[base], None
        return "고급", None          # 상위 흔한 단어 목록에 없음 = 희귀 = 고급
    # 등급목록 미동봉(개발 폴백)
    try:
        from wordfreq import zipf_frequency
        z = zipf_frequency(base, "ko")
        return band(z), z
    except Exception:
        return "미정", None


def tokens_ko(text: str) -> list[tuple[str, str]]:
    """(표제어, 품사) 내용어 목록."""
    kiwi = _ensure_kiwi()
    out = []
    for t in kiwi.tokenize(text):
        if t.tag in _KO_CONTENT and len(t.form) >= 2:
            lemma = t.form + ("다" if t.tag in ("VV", "VA") else "")
            out.append((lemma, t.tag))
    return out


# --- 빌드 ------------------------------------------------------------------
def build_vocab(store, file_key: str, lang: str = "eng",
                progress=None) -> dict:
    """study.db 의 ocr_page 텍스트로 어휘 테이블을 구축. 반환 요약 dict."""
    pages = list(store.iter_all_text(file_key))
    if not pages:
        return {"vocab": 0, "pages": 0, "note": "ocr_page 없음 — 먼저 P1 빌드"}

    page_idx = [p for p, _ in pages]
    texts = [t or "" for _, t in pages]
    ko = lang.startswith("kor") or lang == "ko"
    texts = strip_repeated_lines(texts)                 # 머리말/꼬리말 제거
    texts = [dehyphenate(t) for t in texts]             # 줄바꿈 하이픈 복원
    if not ko:
        texts = [mend_ocr_hyphens_en(t) for t in texts]  # OCR 공백-하이픈 보정

    book_freq: Counter = Counter()
    page_lemmas: dict[int, Counter] = defaultdict(Counter)
    surface_of: dict[str, str] = {}
    example_of: dict[str, str] = {}

    page_pos: dict = {}        # (pno, lemma) -> 첫 등장 순번(문장 순서 정렬용)
    for pno, text in zip(page_idx, texts):
        sents = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
        _i = 0
        if ko:
            pairs = tokens_ko(text)
            for lemma, _tag in pairs:
                book_freq[lemma] += 1
                page_lemmas[pno][lemma] += 1
                page_pos.setdefault((pno, lemma), _i)
                _i += 1
                surface_of.setdefault(lemma, lemma[:-1] if lemma.endswith("다") else lemma)
        else:
            for w in _WORD_EN.findall(text):
                wl = w.lower()
                lm = lemma_en(wl)
                book_freq[lm] += 1
                page_lemmas[pno][lm] += 1
                page_pos.setdefault((pno, lm), _i)
                _i += 1
                surface_of.setdefault(lm, wl)
        # 예문: 표제어 표면형이 든 첫 문장
        for lemma in list(page_lemmas[pno]):
            if lemma in example_of:
                continue
            key = surface_of.get(lemma, lemma)
            for s in sents:
                if key in s.lower() if not ko else key in s:
                    example_of[lemma] = s[:200]
                    break

    # 표제어별 난이도·뜻·예문
    vocab_rows, def_rows, ex_rows = [], [], []
    kept = set()
    for lemma, freq in book_freq.items():
        if ko:
            if len(lemma) < 2:
                continue
            level, z = level_ko(lemma)
            has_syn = False
        else:
            from wordfreq import zipf_frequency
            z = zipf_frequency(lemma, "en")
            syns = _wn_synsets(lemma)
            has_syn = bool(syns)
            if is_noise_en(lemma, z, has_syn):
                continue
            level = band(z)
        kept.add(lemma)
        vocab_rows.append({"lemma": lemma, "lang": lang, "level": level,
                           "zipf": z, "freq_in_book": freq})
        # 뜻: 영어=WordNet, 한국어=한영사전(kengdic) 영어 뜻
        if not ko:
            # 한글 뜻(영→한)을 sense 0 으로 우선 배치
            ko_mean = define_en_ko(lemma)
            sense = 0
            if ko_mean:
                def_rows.append({"lemma": lemma, "lang": lang, "sense": sense,
                                 "definition": ko_mean, "source": "en_ko"})
                sense += 1
            for syn in _wn_synsets(lemma)[:3]:
                def_rows.append({"lemma": lemma, "lang": lang, "sense": sense,
                                 "definition": syn.definition(), "source": "wordnet"})
                sense += 1
                for ex in syn.examples()[:1]:
                    ex_rows.append({"lemma": lemma, "lang": lang,
                                    "example": ex, "source": "wordnet"})
        else:
            for i, gloss in enumerate(define_ko_en(lemma)):
                def_rows.append({"lemma": lemma, "lang": lang, "sense": i,
                                 "definition": gloss, "source": "kengdic"})
        # 예문(본문)
        if lemma in example_of:
            ex_rows.append({"lemma": lemma, "lang": lang,
                            "example": example_of[lemma], "source": "book"})

    page_lemma_rows = [
        {"page": pno, "lemma": lm, "lang": lang, "count": c,
         "pos": page_pos.get((pno, lm), 0)}
        for pno, cnt in page_lemmas.items()
        for lm, c in cnt.items() if lm in kept]

    store.clear_vocab(file_key)
    store.save_vocab(file_key, vocab_rows)
    store.save_page_lemmas(file_key, page_lemma_rows)
    store.save_defs(def_rows)
    store.save_examples(ex_rows)
    return {"vocab": len(vocab_rows), "pages": len(pages),
            "defs": len(def_rows), "examples": len(ex_rows),
            "ko_levels_loaded": len(_load_ko_levels()) if ko else None}
