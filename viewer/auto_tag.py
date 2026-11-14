"""태그·키워드 자동 생성 코어 — SOT: `파일 태그·키워드 작업 계획서.md`.

P1 범위(§11): 신호 수집(§4.1, 레이아웃 포함) · 전처리(§4.2) · L2 형식 분류기(§5.3)
· L1 주제 학습(§5.2) · 연도 추출(§9.4) · 2단 임계값 분류(§5.6).

원칙: Qt 비의존 순수 로직(오프스크린·무Qt 테스트), 완전 오프라인(§3.4),
결정적(랜덤·시간 의존 없음 — §12), 본문 재파싱 금지(§4.1 — 페이지 텍스트는
호출자가 index.db 에서 공급, 폴백만 fitz 앞 20p+뒤 5p).

튜닝 상수는 전부 `TUNING` 한 곳에 모은다(§9.3).
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# ── 튜닝(§9.3 — 품질 조정은 여기서만) ────────────────────────────────────
TUNING = {
    "AUTO_MIN": 0.55,          # §5.6 자동 부여 게이트
    "SUGGEST_MIN": 0.18,       # §5.6 제안 게이트(= L1 임계값 §5.2)
    "MAX_AUTO_TOPIC": 3,       # §5.6 주제 자동 상한
    "MAX_AUTO_FORMAT": 1,      # §5.6 형식 자동 상한
    "PROFILE_K": 60,           # §5.2 태그 프로파일 특징어 수
    "HDR_RATIO": 0.6,          # §4.2-1 머리말 반복 임계(페이지 비율)
    "HDR_MIN_PAGES": 4,        # 페이지가 이보다 적으면 머리말 판정 안 함
    "W_NAME": 3.0, "W_META": 2.0, "W_TOC": 2.0, "W_HEAD": 1.5, "W_BODY": 1.0,
    "HEAD_PAGES": 2,           # §4.1 앞부분 본문
    "FALLBACK_HEAD": 20, "FALLBACK_TAIL": 5,   # §7 미색인 폴백
    "LAYOUT_SAMPLE": 8,        # 레이아웃 표본 페이지 수(결정적 간격 — §12)
    "PRESENT_MIN_AR": 1.3, "PRESENT_MAX_AR": 1.9, "PRESENT_MAX_CHARS": 600,    # §5.3 발표자료(1.9 상한 — 261114-2)
    # 261114-10(§5.3 ③): 2단으로 빽빽한 가로 쪽 = 접지 설명서 — 쪽 그림 너비 600px, 잉크 < 200(스캔의 옅은 글씨),
    #   가운데 40~60% 의 가장 빈 띠 잉크가 양쪽 단 평균의 0.1 이하 + 두 단 모두 글 줄 15개 이상, 앞 3쪽의 절반 이상
    "TWOCOL_W": 600, "TWOCOL_INK": 200, "TWOCOL_GAP": 0.1, "TWOCOL_MIN_LINES": 15, "TWOCOL_PAGES": 0.5,
    "FORMAT_SIM_MIN": 0.30,    # §5.3.2 사람이 고친 종류와 비슷한 본문
    "BROCHURE_MAX_PAGES": 8, "BROCHURE_IMG_RATIO": 0.4,  # §5.3 브로셔
    "ARTICLE_MAX_PAGES": 4,    # §5.3 기사
    "REPORT_MIN_PAGES": 20,    # §5.3 보고서 기본값 조건
    "YEAR_MIN": 1990,          # §9.4 오탐 방어 ①
    "SCAN_MIN_CHARS": 40,      # 페이지당 이 미만이면 스캔(텍스트 레이어 없음) 판정
}

# ── PDF 자동 해시태그(§5.3·§5.3.1 — 261113-10 사용자 지시: 정해진 항목, 이름 고정, 켜고 끄기만) ──────
MANUAL = "제품설명서"            # 261114-14(사용자 지시): 종전 '설명서' — 기술 설명서는 뺀다(§5.3)
FORMAT_VOCAB = (MANUAL, "영수증", "공문", "견적서", "보고서", "발표자료", "논문")      # 형식(문서 종류) — 파일당 1개
RENAMED_FORMATS = {"설명서": MANUAL}   # 종전 이름 → 새 이름 — 붙은 태그를 한 번 옮긴다(§5.8 의 6, tag_rules PDF_AUTO_V 3)
PDF_ATTR_ITEMS = ("날짜", "한글", "영어", "스크린샷", "스캔문서", "텍스트문서")          # 속성(§5.3.1) — 갈래마다 0~1개
PDF_AUTO_ITEMS = PDF_ATTR_ITEMS + FORMAT_VOCAB                                          # 환경설정 차례(§5.8)
REMOVED_FORMATS = ("시험성적서", "브로셔", "기사", "지침", "시방서", "기준", "법령")    # 261113-10 에 뺀 종전 형식 — 한 번 정리(§5.8 의 6)
FORMAT_ALIAS = {   # 별칭 → 표준명(§5.3 '뭉쳐 두는 쪽')
    "세금계산서": "영수증", "거래명세서": "영수증", "계산서": "영수증", "invoice": "영수증",
    "견적": "견적서", "quotation": "견적서",
    "협조요청": "공문", "통보": "공문", "회신": "공문", "공람": "공문",
    "ppt": "발표자료", "보고자료": "발표자료", "프레젠테이션": "발표자료",
    "설명서": MANUAL,
}
_DATE_TAG = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# §4.2-2 불용어(문서 상투어 — 실측 보강은 §9.3 사다리)
_STOP_KO = {"그림", "페이지", "목차", "서론", "결론", "참고문헌", "작성", "제출",
            "붙임", "별표", "별첨", "부록", "제장", "제절", "및", "등", "것", "수",
            "표", "때", "년", "월", "일", "다음", "위", "아래", "경우", "관련",
            "내용", "사항", "기타", "이상", "이하"}
_STOP_EN = {"the", "and", "for", "with", "that", "this", "are", "was", "were",
            "from", "have", "has", "not", "but", "can", "which", "their", "its",
            "these", "those", "than", "then", "into", "such", "also", "been",
            "may", "will", "would", "should", "could", "each", "other", "more",
            "most", "some", "any", "all", "one", "two", "three", "per", "using",
            "used", "use", "based", "between", "within", "table", "figure",
            "fig", "page", "section", "chapter", "appendix", "abstract",
            "introduction", "conclusion", "references", "keywords"}


def axis_of(tag: str, rules: dict | None = None) -> str:
    """§5.1: 축은 저장하지 않고 유도 — PDF 속성(§5.3.1 — 날짜 꼴 포함)이면 '속성', 형식 어휘(별칭 포함)면 '형식'.
    261113-10: 형식 이름은 바꿀 수 없다 — 사용자 alias 의 값은 더는 형식으로 세지 않는다."""
    tl = (tag or "").strip().lower()
    if tl in {a.lower() for a in PDF_ATTR_ITEMS} or _DATE_TAG.match(tl):
        return "속성"
    fmt = {v.lower() for v in FORMAT_VOCAB} | {k.lower() for k in FORMAT_ALIAS}
    return "형식" if tl in fmt else "주제"


def load_rules(path=None) -> dict:
    """`tag_rules.json`(§5.3) — 없으면 내장 기본값(빈 dict)."""
    try:
        if path is None:
            from viewer.settings_store import settings_dir
            path = Path(settings_dir()) / "tag_rules.json"
        return json.loads(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════
# §4 — 신호 수집·전처리
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Features:
    path: str = ""
    stem: str = ""
    page_count: int = 0
    meta: dict = field(default_factory=dict)
    toc_titles: list = field(default_factory=list)
    head_text: str = ""            # 앞 1~2페이지(머리말 제거 후)
    full_text: str = ""            # 전처리 후 전체(표본) 텍스트
    struct_text: str = ""          # ★ 원문(제거 전) 앞 3p+뒤 2p — 형식 판정 전용
    scanned: bool = False          # 텍스트 레이어 없음(§4.2 각주)
    img_pages: list = field(default_factory=list)   # 앞 3쪽 [(그림 하나의 면적비, 짧은 변 px, 긴 변 px) | None] — 스크린샷(§5.3.1)
    aspect: float = 0.0            # 종횡비 중앙값(w/h)
    text_per_page: float = 0.0     # 페이지당 문자 수
    image_ratio: float = 0.0       # 이미지 면적비(표본)
    terms: Counter = field(default_factory=Counter)   # 가중 tf
    folder_names: list = field(default_factory=list)  # 상위 폴더명(연도 신호용)
    bigrams: dict = field(default_factory=dict)       # 261114-4: 재료에서 되살린 키워드용 두 낱말 묶음(본문 전체 대신, §8.2)
    twocol: float | None = None   # 261114-10: 앞 3쪽 중 '2단 빽빽' 쪽 비율 — 발표자료 후보 꼴에서만 잰다(None = 안 잼)


def _tokenize(text: str) -> list:
    """한/영 토큰(§4.2-3·5): 한글 2자+ 연속, 영문 소문자화+단복수 병합(§3.3.1-③)."""
    out = []
    for m in re.finditer(r"[가-힣]{2,20}|[A-Za-z][A-Za-z\-]{1,19}", text or ""):
        t = m.group(0)
        if re.match(r"[A-Za-z]", t):
            t = t.lower().strip("-")
            if len(t) < 3 or t in _STOP_EN:
                continue
            # 단복수 병합(§3.3.1-③) — 260830 교정: porous/class/analysis 처럼 s 가
            # 어미가 아닌 단어를 깎지 않는다(-ss/-us/-is 보호). boxes/churches 는
            # -es 계열만 2자 제거, 그 외(cases·mixtures)는 -s 1자 제거로 충분.
            if len(t) > 4 and t.endswith(("ches", "shes", "xes", "sses", "zes")):
                t = t[:-2]
            elif (len(t) > 3 and t.endswith("s")
                  and not t.endswith(("ss", "us", "is"))):
                t = t[:-1]
        else:
            if t in _STOP_KO:
                continue
        out.append(t)
    return out


def _etal_names(text: str) -> set:
    """§4.2-4 개인정보 — `et al.` 앞 토큰(저자 성)은 후보 제외."""
    return {m.group(1).lower() for m in
            re.finditer(r"([A-Za-z][A-Za-z\-]{2,})\s*,?\s+et\s+al", text or "")}


def strip_headers(pages: list) -> tuple:
    """§4.2-1 머리말·꼬리말 제거 — 전체 페이지의 HDR_RATIO 이상에 반복되는 줄 삭제.
    (번역 SOT §5.2 밴드 방식과 별개 구현이 의도 — 여기 입력엔 위치 정보가 없다.)
    반환: (정리된 페이지 리스트, 제거된 줄 set)."""
    pages = [p or "" for p in (pages or [])]
    if len(pages) < TUNING["HDR_MIN_PAGES"]:
        return pages, set()
    freq = Counter()
    for p in pages:
        for ln in {ln.strip() for ln in p.splitlines() if 2 < len(ln.strip()) < 120}:
            key = re.sub(r"\d+", "#", ln)          # 페이지번호 변형 흡수
            freq[key] += 1
    thresh = max(2, int(len(pages) * TUNING["HDR_RATIO"]))
    common = {k for k, n in freq.items() if n >= thresh}
    if not common:
        return pages, set()
    out, removed = [], set()
    for p in pages:
        keep = []
        for ln in p.splitlines():
            s = ln.strip()
            if s and re.sub(r"\d+", "#", s) in common:
                removed.add(s)
                continue
            keep.append(ln)
        out.append("\n".join(keep))
    return out, removed


def _fallback_pages(path) -> list:
    """미색인 시 fitz 앞 20p + 뒤 5p 만(§7 — 전체 파싱 금지)."""
    try:
        import fitz
        d = fitz.open(str(path))
        try:
            n = d.page_count
            idxs = list(range(min(n, TUNING["FALLBACK_HEAD"])))
            idxs += [i for i in range(max(0, n - TUNING["FALLBACK_TAIL"]), n)
                     if i not in idxs]
            return [d.load_page(i).get_text("text") for i in idxs]
        finally:
            d.close()
    except Exception:
        return []


def _layout_metrics(path, page_texts) -> tuple:
    """레이아웃 신호(§4.1) — 종횡비·페이지수·이미지 면적비·메타·TOC.
    표본은 결정적 간격(§12 — SOT 의 '무작위 3p' 대신 고정 스트라이드; 랜덤 금지)."""
    meta, toc, n, aspect, img_ratio, img_pages = {}, [], 0, 0.0, 0.0, []
    try:
        import fitz
        d = fitz.open(str(path))
        try:
            n = d.page_count
            meta = dict(d.metadata or {})
            # 261011-5(태그 SOT §9.2-6): '저장' 이 /Keywords 에 넣은 PolyPDF 태그를 저자 키워드로 다시 읽지 않는다(되먹임)
            try:
                from viewer import pdf_mirror as _pm
                meta["keywords"] = _pm.author_keywords(d)
            except Exception:
                pass
            toc = [t[1] for t in (d.get_toc() or [])][:80]
            step = max(1, n // TUNING["LAYOUT_SAMPLE"])
            idxs = list(range(0, n, step))[:TUNING["LAYOUT_SAMPLE"]]
            ars, irs = [], []
            for i in idxs:
                pg = d.load_page(i)
                r = pg.rect
                if r.height > 0:
                    ars.append(r.width / r.height)
                area = r.width * r.height or 1.0
                cov = 0.0
                try:
                    for info in pg.get_image_info():
                        bx = info.get("bbox")
                        if bx:
                            cov += max(0.0, (bx[2] - bx[0]) * (bx[3] - bx[1]))
                except Exception:
                    pass
                irs.append(min(1.0, cov / area))
            ars.sort()
            aspect = ars[len(ars) // 2] if ars else 0.0
            img_ratio = sum(irs) / len(irs) if irs else 0.0
            for i in range(min(3, n)):                 # 261113-10(§5.3.1): 쪽을 채운 그림 하나 — 스크린샷 판정
                img_pages.append(_one_image(d.load_page(i)))
        finally:
            d.close()
    except Exception:
        if page_texts:
            n = len(page_texts)
    return n, aspect, img_ratio, meta, toc, img_pages


def _one_image(pg):
    """쪽에 그림이 하나뿐이면 (쪽 면적 대비, 픽셀 짧은 변, 긴 변), 아니면 None."""
    try:
        infos = [x for x in pg.get_image_info() if x.get("bbox")]
        if len(infos) != 1:
            return None
        bx, r = infos[0]["bbox"], pg.rect
        cov = max(0.0, (bx[2] - bx[0]) * (bx[3] - bx[1])) / ((r.width * r.height) or 1.0)
        w, h = int(infos[0].get("width") or 0), int(infos[0].get("height") or 0)
        return (min(1.0, cov), min(w, h), max(w, h))
    except Exception:
        return None


def _ink_table() -> bytes:
    return bytes(1 if v < TUNING["TWOCOL_INK"] else 0 for v in range(256))


def _two_col_page(pg) -> bool:
    """§5.3 ③(261114-10) — 쪽 그림만으로: 가운데 빈 세로 띠 + 양쪽 단에 작은 글 줄이 빽빽(글자층 없는 스캔에도)."""
    import fitz
    z = TUNING["TWOCOL_W"] / max(1.0, pg.rect.width)
    pm = pg.get_pixmap(matrix=fitz.Matrix(z, z), colorspace=fitz.csGRAY, alpha=False)
    w, h, st = pm.width, pm.height, pm.stride
    if w < 50 or h < 50:
        return False
    ink = pm.samples.translate(_ink_table())
    col = [sum(ink[x:st * h:st]) for x in range(w)]
    band = max(2, int(w * 0.015))
    a, b = int(w * 0.40), int(w * 0.60)
    best = min(range(a, b - band), key=lambda x: sum(col[x:x + band]))
    mid = sum(col[best:best + band]) / band
    left = sum(col[:best]) / max(1, best)
    right = sum(col[best + band:]) / max(1, w - best - band)
    if min(left, right) <= 0 or mid / min(left, right) > TUNING["TWOCOL_GAP"]:
        return False

    def lines(x0, x1):
        thr = max(2, int(0.01 * (x1 - x0)))
        n, on = 0, False
        for y in range(h):
            v = sum(ink[y * st + x0:y * st + x1]) > thr
            if v and not on:
                n += 1
            on = v
        return n
    return min(lines(0, best), lines(best + band, w)) >= TUNING["TWOCOL_MIN_LINES"]


def two_col_ratio(path) -> float:
    """앞 3쪽 중 '2단 빽빽' 쪽 비율(못 열면 0)."""
    try:
        import fitz
        d = fitz.open(str(path))
        try:
            n = min(3, d.page_count)
            return (sum(1 for i in range(n) if _two_col_page(d.load_page(i))) / n) if n else 0.0
        finally:
            d.close()
    except Exception:
        return 0.0


def _present_shape(aspect, tpp) -> bool:
    """§5.3 ③ 발표자료 꼴 — 가로(1.3~1.9) + 쪽당 글자 적음."""
    return TUNING["PRESENT_MIN_AR"] <= (aspect or 0) <= TUNING["PRESENT_MAX_AR"] and (tpp or 0) < TUNING["PRESENT_MAX_CHARS"]


def needs_twocol(d: dict) -> bool:
    """261114-10: 그 전에 만든 재료(2단 값 없음)인데 발표자료 꼴이면 2단을 더 재야 한다(재료를 통째로 다시 만들지 않게)."""
    return "twocol" not in d and bool(d.get("page_count")) and _present_shape(d.get("aspect"), d.get("tpp"))


# ── 261114-4(태그 SOT §8.2): 태그 재료 — 색인 때 만들어 색인 DB `tagfeat` 에 둔다 ─────────────────
FEAT_VER = 1                     # 재료 모양·뽑는 법을 바꾸면 올린다(낡은 재료는 다시 만든다)
FEAT_TERMS_MAX, FEAT_BIGRAMS_MAX = 600, 300
FEAT_HEAD_MAX, FEAT_STRUCT_MAX = 4000, 20000      # 연도는 앞 4,000자·종류는 20,000자만 본다
_META_KEYS = ("title", "subject", "keywords", "author", "creationDate", "modDate")


def features_to_dict(f: "Features") -> dict:
    """본문 전체(`full_text`)는 두지 않는다 — 키워드가 쓰는 두 낱말 묶음 상위만(색인 DB 가 두 배가 되지 않게)."""
    bg = Counter(_bigrams(_token_seq(f.full_text))) if f.full_text and not f.scanned else Counter(f.bigrams or {})
    return {
        "v": FEAT_VER, "stem": f.stem, "page_count": f.page_count,
        "meta": {k: f.meta.get(k) for k in _META_KEYS if f.meta.get(k)},
        "toc": list(f.toc_titles)[:80], "head": f.head_text[:FEAT_HEAD_MAX], "struct": f.struct_text[:FEAT_STRUCT_MAX],
        "scanned": bool(f.scanned), "aspect": f.aspect, "tpp": f.text_per_page, "img": f.image_ratio,
        "img_pages": [list(x) if x else None for x in f.img_pages],
        "terms": dict(Counter(f.terms).most_common(FEAT_TERMS_MAX)),
        "bigrams": dict(bg.most_common(FEAT_BIGRAMS_MAX)),
        **({"twocol": f.twocol} if f.twocol is not None else {}),
    }


def features_from_dict(path, d: dict, folder_names=None) -> "Features":
    f = Features(path=str(path), stem=d.get("stem") or Path(path).stem, folder_names=list(folder_names or []))
    f.page_count = int(d.get("page_count") or 0)
    f.meta = dict(d.get("meta") or {})
    f.toc_titles = list(d.get("toc") or [])
    f.head_text = d.get("head") or ""
    f.struct_text = d.get("struct") or ""
    f.scanned = bool(d.get("scanned"))
    f.aspect, f.text_per_page, f.image_ratio = float(d.get("aspect") or 0), float(d.get("tpp") or 0), float(d.get("img") or 0)
    f.img_pages = [tuple(x) if x else None for x in d.get("img_pages") or []]
    f.terms = Counter(d.get("terms") or {})
    f.bigrams = dict(d.get("bigrams") or {})
    f.twocol = d.get("twocol")
    return f


def extract_features(path, page_texts=None, folder_names=None,
                     open_pdf: bool = True) -> Features:
    """§4.1 신호 수집 + §4.2 전처리. `page_texts` = index.db 페이지 텍스트(재파싱 금지);
    None 이면 fitz 폴백(앞 20p+뒤 5p). `open_pdf=False` 면 레이아웃·메타 생략(테스트용)."""
    f = Features(path=str(path), stem=Path(path).stem,
                 folder_names=list(folder_names or []))
    if page_texts is None and open_pdf:
        page_texts = _fallback_pages(path)
    page_texts = page_texts or []

    if open_pdf:
        (f.page_count, f.aspect, f.image_ratio, f.meta, f.toc_titles, f.img_pages) = \
            _layout_metrics(path, page_texts)
    if not f.page_count:
        f.page_count = len(page_texts)

    # ★ 스캔 판정·형식 판정은 머리말 제거 **전** 원문 기준(260829 보강).
    #   구조 토큰(수신·사업자등록번호·시험항목·판정)은 여러 페이지 성적서·공문 철에서
    #   모든 페이지에 정당하게 반복된다 — 제거 후 텍스트로 판정하면 그런 문서가
    #   미분류로 빠지고, 스캔 판정도 왜곡된다. 제거본은 특징어(TF-IDF) 전용.
    raw_chars = sum(len(p) for p in page_texts)
    f.scanned = (not page_texts) or raw_chars < \
        TUNING["SCAN_MIN_CHARS"] * max(1, len(page_texts))
    _n = len(page_texts)
    _idx = list(range(min(3, _n))) + [i for i in (_n - 2, _n - 1) if 3 <= i < _n]
    f.struct_text = "\n".join(page_texts[i] for i in _idx)   # 앞 3p + 뒤 2p(중복 없이)

    pages, _removed = strip_headers(page_texts)
    f.full_text = "\n".join(pages)
    f.head_text = "\n".join(pages[:TUNING["HEAD_PAGES"]])
    f.text_per_page = raw_chars / max(1, len(page_texts))
    if open_pdf and f.page_count and _present_shape(f.aspect, f.text_per_page):
        f.twocol = two_col_ratio(path)           # 261114-10: 발표자료 꼴일 때만(가로 문서만 쪽 그림을 그린다)

    # 가중 tf(§4.1 표) — 로그 포화는 점수 계산 시(§3.3.1-②)
    ban = _etal_names(f.full_text)
    def add(text, w):
        for t in _tokenize(text):
            if t not in ban:
                f.terms[t] += w
    add(f.stem, TUNING["W_NAME"])
    add(" ".join(str(f.meta.get(k) or "") for k in ("title", "subject", "keywords")),
        TUNING["W_META"])
    add(" ".join(f.toc_titles), TUNING["W_TOC"])
    add(f.head_text, TUNING["W_HEAD"])
    add(f.full_text, TUNING["W_BODY"])
    return f


# ═══════════════════════════════════════════════════════════════════════
# §5.3 — L2 자료 형식 분류기 (닫힌 13종, 파일당 1개)
# ═══════════════════════════════════════════════════════════════════════

# 제품설명서 이름 낱말 — 제품 단서(이것만으로 제품설명서)와 약한 낱말(기술 문서에도 쓰여, 제품 단서가 따로 있어야 — 261114-14)
_MANUAL_NAME_STRONG = ("설명서", "사용자", "사용법", "취급", "퀵", "quick start", "quickstart", "보증서")
_MANUAL_NAME_WEAK = ("매뉴얼", "메뉴얼", "manual", "mnl", "guide", "instruction", "_um_")
# 261114-14(사용자 결정 '기술 낱말이면 빼기'): 이름·제목·상위 폴더에 이 낱말이 있으면 본문 제품 낱말·2단 접지가 없는 한 제품설명서 아님
_TECH_WORDS = ("기술", "technical", "설계", "시공", "지침", "편람")
_EXPLICIT = [   # ① 파일명/표제 명시어 — 순서 = 판정 순서(261113-10: 지침·시방서·기준·법령·시험성적서는 뺐다, 견적서 더함)
    (MANUAL, _MANUAL_NAME_STRONG + _MANUAL_NAME_WEAK),   # 261114-2·-10 낱말 늘림(§5.3 표 — 'warranty' 는 포장 성능보증 문서에 걸려 뺐다)
    ("견적서", ("견적", "quotation")),
    ("영수증", ("영수증", "세금계산서", "거래명세서", "invoice")),
    ("공문", ("공문", "협조요청", "공람")),
]
# ①-3 폴더 이름(261114-2, 사용자 결정 '폴더 이름도 본다') — 파일 이름 낱말 + 폴더로 모으는 종류
_FOLDER_EXPLICIT = _EXPLICIT + [
    ("보고서", ("보고서", "report")),
    ("논문", ("논문", "paper")),
    ("발표자료", ("발표자료", "프레젠테이션", "ppt")),
]
FOLDER_DEPTH = 3
# ② 설명서 본문 낱말(261114-2) — 앞 3쪽·뒤 2쪽 원문
_MANUAL_BODY = ("사용설명서", "사용 설명서", "취급설명서", "취급 설명서", "제품 사양", "품질보증", "품질 보증",
                "user manual", "user's manual", "instruction manual", "operating instructions", "quick start guide",
                "보증서", "warranty card", "limited warranty")       # 261114-10
# 261114-10: A/S·고객 지원·고객센터·보증 기간·warranty·customer support 는 넣지 않는다 — _samples 실측에서
#   성능보증 보고서·논문·뉴스·장비 개요 6개를 설명서로 잘못 걸었다(둘 이상 조건으로도). §5.3 표


def folder_format(path: str):
    """상위 폴더 이름(가까운 것부터 `FOLDER_DEPTH` 단계)에 종류 낱말이 있으면 그 종류(§5.3 ①-3)."""
    try:
        parents = list(Path(path).parents)[:FOLDER_DEPTH]
    except Exception:
        return None
    for d in parents:
        nm = d.name.lower()
        if not nm:
            continue
        for tag, keys in _FOLDER_EXPLICIT:
            if any(k in nm for k in keys):
                return tag
    return None


def _tech_doc(f: Features, name: str) -> bool:
    """이름·제목·상위 폴더(`FOLDER_DEPTH` 단계)에 기술 낱말(§5.3, 261114-14)."""
    if any(k in name for k in _TECH_WORDS):
        return True
    try:
        return any(any(k in d.name.lower() for k in _TECH_WORDS) for d in list(Path(f.path).parents)[:FOLDER_DEPTH] if f.path)
    except Exception:
        return False


def classify_format(f: Features, rules: dict | None = None, learned: dict | None = None) -> str | None:
    """§5.3 판정 순서: ①명시어 ①-2 사람이 고친 폴더 ①-3 폴더 이름 ②구조(견적서▶영수증▶공문▶설명서 본문▶논문)
    ②-2 고친 문서와 비슷한 본문 ③레이아웃(발표자료) ④기본값.
    learned(§5.3.2) = {"dir": 그 폴더에서 사람이 고친 종류 | None, "sims": {종류: 유사도}} — 워커가 직접 태그로 만든다.
    확신 없으면 None(형식 태그 없음 — 틀린 형식보다 없는 편이 낫다 §3.5-A)."""
    rules = rules or {}
    learned = learned or {}
    name = (f.stem + " " + str(f.meta.get("title") or "")).lower()
    txt = f.struct_text[:20000].lower()      # ★ 원문 기준(위 보강) — 스캔이면 자연히 빈 문자열
    fmt = None

    # 261114-14: 제품 단서(본문 제품 낱말·2단 접지) · 기술 문서
    body_cue = bool(txt) and any(k in txt for k in _MANUAL_BODY) or (f.twocol or 0) >= TUNING["TWOCOL_PAGES"]
    tech = _tech_doc(f, name)

    # ① 명시어 — 사람이 이름에 써 둔 것이 가장 확실
    for tag, keys in _EXPLICIT:
        if any(k in name for k in keys):
            fmt = tag
            break
    if fmt == MANUAL and not body_cue:                # 기술 문서이거나 이름 단서가 약한 낱말뿐이면 아니다
        if tech or not any(k in name for k in _MANUAL_NAME_STRONG):
            fmt = None
    # ①-2 사람이 고친 종류(같은 폴더 2개 이상, §5.3.2) ①-3 폴더 이름(261114-2)
    if fmt is None and learned.get("dir") in FORMAT_VOCAB:
        fmt = learned["dir"]
    if fmt is None and f.path:
        fmt = folder_format(f.path)
        if fmt == MANUAL and tech and not body_cue:
            fmt = None

    # ② 강한 구조 신호 — 토큰이 특이한 순(§5.3 — ③보다 먼저: 짧은 문서 오분류 방지)
    if fmt is None and txt:
        if "견적서" in txt or ("견적" in txt and any(k in txt for k in ("견적금액", "공급가액", "합계"))):
            fmt = "견적서"              # 261113-10 — 영수증보다 먼저(둘 다 사업자등록번호·합계가 있다)
        elif "사업자등록번호" in txt and ("합계" in txt or "공급가액" in txt):
            fmt = "영수증"
        elif ("수신" in txt and ("발신" in txt or "참조" in txt
                                or re.search(r"제\s?\d{2,4}\s?[-–]\s?\d+\s?호", txt))):
            fmt = "공문"
        elif any(k in txt for k in _MANUAL_BODY):
            fmt = MANUAL                # 261114-2·-10
        elif (("abstract" in txt and "reference" in txt)
              or "doi:" in txt or "doi.org" in txt
              or re.search(r"\bet\s+al\b", txt)):
            fmt = "논문"

    # ②-2 사람이 고친 문서와 비슷한 본문(§5.3.2 — L1 과 같은 산식, 글자층 있을 때만)
    if fmt is None:
        sims = {t: sc for t, sc in (learned.get("sims") or {}).items() if t in FORMAT_VOCAB and sc >= TUNING["FORMAT_SIM_MIN"]}
        if sims:
            fmt = max(sims, key=sims.get)

    # ③ 레이아웃 신호(텍스트 불요 — 스캔 PDF 에도 동작 §4.2 각주). 261113-10: 브로셔·기사는 뺐다.
    #   261114-2(사용자 지시): 다단으로 옆으로 긴 쪽(종횡비 > PRESENT_MAX_AR)은 발표자료가 아니다
    #   261114-10(사용자 지시): 2단으로 작은 글씨가 빽빽한 가로 쪽은 발표자료가 아니라 접지 설명서(글자층 없는 스캔도 쪽 그림으로)
    if fmt is None and f.page_count:
        if _present_shape(f.aspect, f.text_per_page):
            fmt = MANUAL if (f.twocol or 0) >= TUNING["TWOCOL_PAGES"] else "발표자료"

    # ④ 기본값 — 보고서(조건 못 맞추면 형식 없음).
    #   260830 시정: SOT §5.3 의 '보고서 = 이름 + 목차 + ≥20p' 에서 **목차 조건이 구현에서
    #   빠져** 페이지수만으로 보고서를 찍었고, 텍스트 많은 가로 발표자료가 ③을 통과해
    #   #보고서로 오분류됐다(실사용 보고). 목차 필수 + 가로 문서 제외로 보수화 —
    #   틀린 형식보다 없는 편이 낫다(§3.5-A).
    if fmt is None:
        if "보고서" in name or "report" in name:
            fmt = "보고서"
        elif (f.page_count >= TUNING["REPORT_MIN_PAGES"] and not f.scanned
              and f.toc_titles                                # 목차 있어야(§5.3 표)
              and f.aspect < 1.2):                            # 가로 문서는 기본값 제외
            fmt = "보고서"

    if fmt is None or fmt in set(rules.get("format_off") or ()):     # §5.8 사용자가 끈 형식 — 형식 없음
        return None
    return fmt                                       # 261113-10: 이름은 고정(별칭 표로 바꾸지 않는다)


# ── §5.3.1 PDF 속성 — 날짜·한글/영어·스캔문서/텍스트문서·스크린샷 (261113-10) ──────────
ATTR_KO_MIN, ATTR_EN_MAX, ATTR_MIN_LETTERS = 0.30, 0.05, 100   # 한글 비율 ≥ → 한글, ≤ → 영어(글자 100개 이상)
ATTR_SCAN_IMG = 0.85            # 표본 쪽 평균 그림 면적 ≥ → 스캔문서(OCR 글자층을 얹은 스캔 포함)
ATTR_SHOT_COVER = 0.95          # 스크린샷: 쪽을 거의 채운 그림 하나


def pdf_date_tag(f: Features):
    """PDF 메타 만든 날(`D:YYYYMMDD…`) → 'YYYY-MM-DD'(사진 촬영일 태그와 같은 꼴). 1990년~오늘만."""
    import datetime as _dt
    m = re.match(r"D:((?:19|20)\d{2})(\d{2})(\d{2})", str(f.meta.get("creationDate") or ""))
    if not m:
        return None
    try:
        d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return d.isoformat() if _dt.date(1990, 1, 1) <= d <= _dt.date.today() else None


def pdf_lang_tag(f: Features):
    txt = f.struct_text or f.full_text or ""
    h = len(re.findall(r"[가-힣]", txt))
    l = len(re.findall(r"[A-Za-z]", txt))
    if h + l < ATTR_MIN_LETTERS:
        return None
    r = h / (h + l)
    return "한글" if r >= ATTR_KO_MIN else ("영어" if r <= ATTR_EN_MAX else None)


def pdf_is_screenshot(f: Features) -> bool:
    from viewer.photo_tags import _NAME_SHOT, SCREEN_SHORT
    if _NAME_SHOT.search(f.stem or "") or _NAME_SHOT.search(str(f.meta.get("title") or "")):
        return True
    if not f.page_count or f.page_count > 3 or not f.img_pages:
        return False
    for ip in f.img_pages:
        if not ip or ip[0] < ATTR_SHOT_COVER or ip[1] not in SCREEN_SHORT or not (1.3 <= ip[2] / max(1, ip[1]) <= 2.4):
            return False
    return True


def pdf_attr_tags(f: Features, rules: dict | None = None) -> list:
    """§5.3.1 — 날짜 → 언어 → 매체 → 스크린샷 차례. 끈 항목(`format_off`)은 뺀다."""
    off = set((rules or {}).get("format_off") or ())
    out = []
    if "날짜" not in off:
        d = pdf_date_tag(f)
        if d:
            out.append(d)
    lang = pdf_lang_tag(f)
    if lang and lang not in off:
        out.append(lang)
    if f.page_count:
        med = "스캔문서" if (f.scanned or f.image_ratio >= ATTR_SCAN_IMG) else "텍스트문서"
        if med not in off:
            out.append(med)
    if "스크린샷" not in off and pdf_is_screenshot(f):
        out.append("스크린샷")
    return out


# ═══════════════════════════════════════════════════════════════════════
# §5.2 — L1 기존 태그 학습 (전역 DF · 로그 포화 — §3.3.1 산식 공유)
# ═══════════════════════════════════════════════════════════════════════

def _tfidf_vec(terms: Counter, df: dict, n_docs: int, k: int) -> dict:
    n_docs = max(1, n_docs)
    vec = {}
    for t, tf in terms.items():
        idf = math.log(n_docs / (1 + df.get(t, 0))) + 1.0
        vec[t] = (1.0 + math.log(max(1.0, tf))) * idf     # §3.3.1-② 로그 포화
    top = sorted(vec.items(), key=lambda kv: -kv[1])[:k]
    return dict(top)


def build_profiles(tag_docs: dict, df: dict, n_docs: int) -> dict:
    """§5.2: 태그 t 가 붙은 파일들의 terms 로 프로파일 W(t) — TF-IDF 상위 K.
    tag_docs = {태그: [Counter, …]}. 태그당 파일 1개여도 동작."""
    prof = {}
    for tag, counters in (tag_docs or {}).items():
        agg = Counter()
        for c in counters:
            agg.update(c)
        if agg:
            prof[tag] = _tfidf_vec(agg, df, n_docs, TUNING["PROFILE_K"])
    return prof


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    num = sum(a[t] * b[t] for t in common)
    da = math.sqrt(sum(v * v for v in a.values()))
    db = math.sqrt(sum(v * v for v in b.values()))
    return num / (da * db) if da and db else 0.0


def topic_similarities(f: Features, profiles: dict, df: dict, n_docs: int) -> dict:
    """{태그: 유사도 0~1} — 산출 태그는 항상 기존 어휘(§5.2)."""
    dv = _tfidf_vec(f.terms, df, n_docs, TUNING["PROFILE_K"])
    return {tag: round(_cosine(dv, w), 4) for tag, w in (profiles or {}).items()}


# ── 프로파일 캐시(§5.2 — file_tags.json mtime 로 무효화) ────────────────
def load_profile_cache(cache_path, tags_mtime_ns: int) -> dict | None:
    try:
        d = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        if d.get("tags_mtime_ns") == tags_mtime_ns:
            return d.get("profiles") or {}
    except Exception:
        pass
    return None


def save_profile_cache(cache_path, tags_mtime_ns: int, profiles: dict):
    try:
        p = Path(cache_path)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"tags_mtime_ns": tags_mtime_ns,
                                   "profiles": profiles}, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
# §9.4 — 작성연도 추출 (태그가 아니다 §3.6)
# ═══════════════════════════════════════════════════════════════════════

def extract_year(f: Features, today_year: int) -> tuple:
    """(year|None, src, conf). 우선순위: 파일명 ▶ 폴더 YYMMDD ▶ 1페이지 ▶ meta.
    ★ 본문 전체를 훑지 않는다(참고문헌 오염). 못 찾으면 None(추측 금지).
    결정성(§12)을 위해 기준 연도는 인자로 받는다."""
    lo, hi = TUNING["YEAR_MIN"], today_year

    def _gate(ys):
        ys = [y for y in ys if lo <= y <= hi]
        return max(ys) if ys else None            # 같은 순위 안에서는 최신(§9.4-5)

    # ① 파일명 — v버전(v4212) 제거 후 4자리(§9.4 방어 ②), 2자리 미채택(방어 ③)
    s = re.sub(r"[vV]\.?\s?\d[\d.]*", " ", f.stem)
    y = _gate([int(m.group(1)) for m in
               re.finditer(r"(?<!\d)((?:19|20)\d{2})(?:\d{4})?(?!\d)", s)])
    if y:
        return y, "name", 0.9
    # ② 폴더 YYMMDD 접두(§5.4.1-② 재활용 — 230718바이오매스 → 2023)
    ys = []
    for name in f.folder_names:
        m = re.match(r"^\s*((?:19|20)\d{2})(\d{2})(\d{2})\b", name.strip()) \
            or re.match(r"^\s*(\d{2})(\d{2})(\d{2})(?!\d)", name.strip())
        if m:
            yy, mm, dd = m.group(1), int(m.group(2)), int(m.group(3))
            if 1 <= mm <= 12 and 1 <= dd <= 31:
                ys.append(int(yy) if len(yy) == 4 else 2000 + int(yy))
    y = _gate(ys)
    if y:
        return y, "folder", 0.8
    # ③ 1페이지 발행 패턴만(© · N년 · Month YYYY)
    p1 = f.head_text[:4000]
    pats = [r"©\s?((?:19|20)\d{2})", r"((?:19|20)\d{2})\s?년",
            r"(?:january|february|march|april|may|june|july|august|september|"
            r"october|november|december)\s+((?:19|20)\d{2})"]
    ys = []
    for p in pats:
        ys += [int(m.group(1)) for m in re.finditer(p, p1, re.I)]
    y = _gate(ys)
    if y:
        return y, "page1", 0.6
    # ④ meta.creationDate("D:YYYY…") — 재저장으로 바뀌므로 최후·저신뢰
    m = re.match(r"D:((?:19|20)\d{2})", str(f.meta.get("creationDate") or ""))
    if m:
        y = _gate([int(m.group(1))])
        if y:
            return y, "meta", 0.3
    return None, "", 0.0


# ═══════════════════════════════════════════════════════════════════════
# §5.6 — 순위 병합 + 2단 임계값
# ═══════════════════════════════════════════════════════════════════════

def suggest_tags(f: Features, profiles: dict, df: dict, n_docs: int,
                 known_tags=None, rules: dict | None = None,
                 extra=None, learned: dict | None = None) -> list:
    """제안 목록(§4 API): [{tag, score, kind, axis, why}]. extra 는 §5.5 확장점(항상 None).
    형식은 판정 서면 score 없이도 자동 대상(§5.6 표 1행) — score 는 표시용 1.0."""
    known = {t.lower() for t in (known_tags or [])}
    out = []
    for t in pdf_attr_tags(f, rules):                 # 261113-10 §5.3.1 — 점수 없이 자동
        out.append({"tag": t, "score": 1.0, "axis": "속성",
                    "kind": "existing" if t.lower() in known else "new", "why": "PDF 속성(§5.3.1)"})
    sims = {} if f.scanned else topic_similarities(f, profiles, df, n_docs)
    lr = learned or {}
    fmt = None
    if not lr.get("has_manual"):                     # §5.3.2 — 사람이 종류를 붙인 파일에는 자동 종류를 더 붙이지 않는다
        lr = {"dir": lr.get("dir"), "sims": {t: sc for t, sc in sims.items() if t in FORMAT_VOCAB}}
        fmt = classify_format(f, rules, lr)
    if fmt:
        out.append({"tag": fmt, "score": 1.0, "axis": "형식",
                    "kind": "existing" if fmt.lower() in known else "new",
                    "why": "형식 규칙(§5.3)"})
    # 주제 점수(§5.6): max(L1 유사도, 폴더명 일치 0.75) + 겹침 보너스 0.10
    folder_hit = set()
    known_low = {t.lower(): t for t in (known_tags or [])}
    for w in folder_candidates(f.folder_names):
        wl = w.lower()
        for kl, orig in known_low.items():
            if wl == kl or wl.startswith(kl) or kl.startswith(wl):
                folder_hit.add(orig)                 # §5.4.1 — 기존 어휘 확인 = 자동 대상
    topic_scores = {}
    for tag, sc in sims.items():
        if axis_of(tag, rules) == "주제":
            topic_scores[tag] = min(1.0, sc)
    for tag in folder_hit:
        if axis_of(tag, rules) != "주제":
            continue
        base = topic_scores.get(tag, 0.0)
        topic_scores[tag] = min(1.0, max(base, 0.75) + (0.10 if base > 0 else 0.0))
    for tag, sc in sorted(topic_scores.items(), key=lambda kv: -kv[1]):
        if sc >= TUNING["SUGGEST_MIN"]:
            why = []
            if sims.get(tag, 0) >= TUNING["SUGGEST_MIN"]:
                why.append(f"#{tag} 파일과 유사도 {sims[tag]:.2f}(§5.2)")
            if tag in folder_hit:
                why.append("폴더명 일치(§5.4.1)")
            out.append({"tag": tag, "score": round(sc, 4), "axis": "주제",
                        "kind": "existing", "why": " · ".join(why)})
    if extra is not None:                    # §5.5 — 현재 항상 None
        try:
            out += list(extra(f, sorted(known)) or [])
        except Exception:
            pass
    return out


def partition(suggestions: list) -> dict:
    """§5.6 2단 임계값: {'auto': [...], 'suggest': [...]}.
    자동 = 형식(판정 성립, 신규여도 §5.4-5 예외) + 주제 existing·score≥AUTO_MIN.
    상한: 형식 1 + 주제 3(따로 센다 — 주제가 찼다고 형식이 밀리지 않는다)."""
    auto, sugg = [], []
    n_fmt = n_topic = 0
    for s in sorted(suggestions, key=lambda x: -x["score"]):
        if s.get("axis") == "속성":                 # 261113-10 §5.3.1 — 갈래마다 하나, 판정 서면 자동
            auto.append(s)
        elif s.get("axis") == "형식":
            if n_fmt < TUNING["MAX_AUTO_FORMAT"]:
                auto.append(s)
                n_fmt += 1
            else:
                sugg.append(s)
        elif (s.get("kind") == "existing" and s["score"] >= TUNING["AUTO_MIN"]
              and n_topic < TUNING["MAX_AUTO_TOPIC"]):
            auto.append(s)
            n_topic += 1
        else:
            sugg.append(s)                   # kind=new(적립) 또는 게이트 미달(제안만)
    return {"auto": auto, "suggest": sugg}


# ═══════════════════════════════════════════════════════════════════════
# §9 — ② 내용 키워드 (함축, 최대 10) — P4
# ═══════════════════════════════════════════════════════════════════════

def _token_seq(text: str) -> list:
    """토큰 시퀀스(순서 보존) — 2-gram 생성용(§9.2-2)."""
    return _tokenize(text or "")


def _bigrams(tokens: list) -> Counter:
    """인접 토큰 2-gram(§9.2-2) — 한/영 모두 공백 결합('배수성 아스팔트')."""
    out = Counter()
    for a, b in zip(tokens, tokens[1:]):
        if a != b:
            out[a + " " + b] += 1
    return out


def _drop_contained(cands: list) -> list:
    """§4.2-6 포함관계 정리 — 짧은 쪽이 긴 쪽에 포함되면 짧은 쪽 탈락."""
    out = []
    for w, sc, ko in cands:
        if any(w != w2 and w in w2 for w2, _s, _k in cands):
            continue
        out.append((w, sc, ko))
    return out


def suggest_keywords(f: Features, df: dict, n_docs: int,
                     ko_lookup=None, top: int = None,
                     folder_common: set | None = None) -> list:
    """§9 키워드: [{word, score, ko}] 상위 top(기본 10).
    - 게이트 없음(§9.1 — 틀려도 검색 재현율을 해치지 않는다). 스캔이면 [].
    - 점수 = 로그 포화 TF(가중 포함) × 전역 IDF(§9.2-3). 위치 가중은 f.terms 에 내장.
    - `folder_common` = 대형 동질 폴더의 공통어(§9.2-3 필터 — 워커가 계산해 전달).
    - `metadata.keywords`(저자)는 무조건 상위(§9.2-6).
    - `ko_lookup(영문)` → 한글 대역이 있으면 병기(§9.2-5 — 치환하지 않는다)."""
    if f.scanned:
        return []
    top = top or MAX_KEYWORDS_SUGGEST
    n_docs = max(1, n_docs)
    cand = Counter(f.terms)
    cand.update(f.bigrams if (f.bigrams and not f.full_text) else _bigrams(_token_seq(f.full_text)))   # 261114-4 재료면 저장된 묶음
    fc = folder_common or set()

    scored = []
    for w, tf in cand.items():
        if w in fc:                                   # 폴더 공통어 제외(§9.2-3)
            continue
        if len(w) < 2 or len(w) > 40 or w.replace(" ", "").isdigit():
            continue
        idf = math.log(n_docs / (1 + df.get(w, 0))) + 1.0
        scored.append((w, (1.0 + math.log(max(1.0, tf))) * idf))
    scored.sort(key=lambda x: -x[1])

    # 저자 키워드 최우선(§9.2-6)
    author = []
    raw_kw = str(f.meta.get("keywords") or "")
    for w in re.split(r"[;,\n]+", raw_kw):
        w = w.strip()
        if 1 < len(w) <= 40:
            author.append(w)

    picked, seen = [], set()
    for w in author:
        if w.lower() not in seen:
            seen.add(w.lower())
            picked.append((w, 10.0, None))
    for w, sc in scored:
        if len(picked) >= top * 2:                    # 포함관계 정리 여유분
            break
        if w.lower() not in seen:
            seen.add(w.lower())
            picked.append((w, sc, None))
    picked = _drop_contained(picked)[:top]

    out = []
    for w, sc, _ in picked:
        ko = None
        if ko_lookup is not None and re.match(r"^[a-z][a-z \-]*$", w):
            try:
                ko = ko_lookup(w) or None             # 병기(치환 아님 — §9.2-5)
            except Exception:
                ko = None
        out.append({"word": w, "score": round(sc, 3), "ko": ko})
    return out


MAX_KEYWORDS_SUGGEST = 10      # §9.1 — store 의 MAX_KEYWORDS 와 동일 상한


# ═══════════════════════════════════════════════════════════════════════
# §5.4.1 — 폴더명 신호 + §5.4 L3 신규 태그 후보 — P5
# ═══════════════════════════════════════════════════════════════════════

_FOLDER_EXCLUDE = {"downloads", "documents", "desktop", "다운로드", "문서",
                   "바탕화면", "새 폴더", "temp", "tmp", "backup", "백업",
                   "첨부", "자료", "기타"}


def folder_candidates(folder_names: list, root_name: str = "") -> list:
    """§5.4.1: 상위 폴더명 → 정규화된 주제 후보들. 제외 규칙 통과분만.
    점유율 상한(30%)·깊이 제한은 호출자(워커) 몫 — 여기는 이름 하나의 정규화."""
    out, seen = [], set()
    for name in folder_names or []:
        s = (name or "").strip()
        if not s or s == root_name:
            continue
        low = s.lower()
        if low in _FOLDER_EXCLUDE:
            continue
        if low.endswith("_split"):        # ★ 분할기 산출 폴더 — 원본명 중복, 정보 0(§5.4.1-①2)
            continue
        s = re.sub(r"^\s*[\[\(]?\d+[\]\)]?[\s.\-_·]+", "", s)      # 선행 순번
        s = re.sub(r"^\s*(?:19|20)?\d{6}\s*", "", s)               # 선행 YYMMDD(연도는 §9.4 가 재활용)
        s = re.sub(r"^\s*\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}[^_]*_?", "", s)   # 날짜시각 접두
        s = re.sub(r"\([^)]*\)", " ", s)                           # 괄호 부가정보
        s = re.sub(r"(수정|최종|final|v)\s*\d*\s*$", "", s, flags=re.I)    # 후행 버전
        for part in re.split(r"[.·_,/]+", s):                      # 구분자 분해
            p = part.strip()
            if not (2 <= len(p) <= 12):
                continue
            if p.replace(" ", "").isdigit() or p.lower() in _FOLDER_EXCLUDE:
                continue
            if p.lower() in _STOP_KO or p.lower() == "수정":
                continue
            if p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
    return out


def new_tag_candidates(f: Features, df: dict, n_docs: int, known_tags,
                       ko_lookup=None, folder_names: list | None = None,
                       max_new: int = 3) -> list:
    """§5.4 L3: 신규 태그 후보 — 자동 부여하지 않고 적립용(§5.4-5).
    ① 폴더명 후보(사용자가 만든 분류 — 우선) ② 특징어 상위 중 일반성 있는 것
    (DF ≥ 2 — 여러 파일에 나타나는 상위 개념, §5.4-1: DF=1 은 키워드지 태그가 아니다).
    기존 어휘와 접두/포함 일치는 흡수(§5.4-3 — 어휘 폭발의 유일한 방어선)."""
    known_low = {t.lower() for t in (known_tags or [])}

    def absorbed(w: str) -> bool:
        wl = w.lower()
        return any(wl == k or wl.startswith(k) or k.startswith(wl)
                   for k in known_low)

    out, seen = [], set()
    for w in folder_candidates(folder_names or f.folder_names):
        if not absorbed(w) and axis_of(w) == "주제" and w.lower() not in seen:
            seen.add(w.lower())
            out.append({"tag": w, "score": 0.75, "kind": "new", "axis": "주제",
                        "why": "폴더명(§5.4.1 — 사용자가 만든 분류)"})
    if not f.scanned:
        dv = _tfidf_vec(f.terms, df, max(1, n_docs), 20)
        for w, sc in sorted(dv.items(), key=lambda kv: -kv[1]):
            if len(out) >= max_new:
                break
            if df.get(w, 0) < 2:                     # 일반성 조건(§5.4-1)
                continue
            if len(w) < 2 or len(w) > 12 or absorbed(w) or w.lower() in seen:
                continue
            ko = None
            if ko_lookup is not None and re.match(r"^[a-z][a-z \-]*$", w):
                try:
                    ko = ko_lookup(w) or None        # 영문 상위어 한글화(§5.4-2)
                except Exception:
                    ko = None
            tag = ko or w
            if absorbed(tag) or tag.lower() in seen:
                continue
            seen.add(tag.lower())
            out.append({"tag": tag, "score": 0.6, "kind": "new", "axis": "주제",
                        "why": "특징어 상위(§5.4)" + (f" — {w} 대역" if ko else "")})
    return out[:max_new]
