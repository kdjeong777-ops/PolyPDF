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
    "PRESENT_MIN_AR": 1.3, "PRESENT_MAX_CHARS": 600,    # §5.3 발표자료
    "BROCHURE_MAX_PAGES": 8, "BROCHURE_IMG_RATIO": 0.4,  # §5.3 브로셔
    "ARTICLE_MAX_PAGES": 4,    # §5.3 기사
    "REPORT_MIN_PAGES": 20,    # §5.3 보고서 기본값 조건
    "YEAR_MIN": 1990,          # §9.4 오탐 방어 ①
    "SCAN_MIN_CHARS": 40,      # 페이지당 이 미만이면 스캔(텍스트 레이어 없음) 판정
}

# ── 형식 어휘(§5.3 — 닫힌 13종) + 별칭 ──────────────────────────────────
FORMAT_VOCAB = ("영수증", "시험성적서", "공문", "논문", "발표자료", "브로셔",
                "기사", "설명서", "지침", "시방서", "기준", "법령", "보고서")
FORMAT_ALIAS = {   # 별칭 → 표준명(§5.3 '뭉쳐 두는 쪽')
    "세금계산서": "영수증", "거래명세서": "영수증", "계산서": "영수증", "invoice": "영수증",
    "성적서": "시험성적서", "검사성적서": "시험성적서", "품질성적서": "시험성적서",
    "시험결과보고서": "시험성적서", "test report": "시험성적서",
    "협조요청": "공문", "통보": "공문", "회신": "공문", "공람": "공문",
    "ppt": "발표자료", "보고자료": "발표자료", "프레젠테이션": "발표자료",
}

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
    """§5.1: 축은 저장하지 않고 유도 — 형식 어휘(별칭·사용자 alias 포함) 소속이면 '형식'."""
    tl = (tag or "").strip().lower()
    fmt = {v.lower() for v in FORMAT_VOCAB} | {k.lower() for k in FORMAT_ALIAS}
    alias = (rules or {}).get("alias") or {}
    fmt |= {str(v).lower() for v in alias.values()}
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
    aspect: float = 0.0            # 종횡비 중앙값(w/h)
    text_per_page: float = 0.0     # 페이지당 문자 수
    image_ratio: float = 0.0       # 이미지 면적비(표본)
    terms: Counter = field(default_factory=Counter)   # 가중 tf
    folder_names: list = field(default_factory=list)  # 상위 폴더명(연도 신호용)


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
    meta, toc, n, aspect, img_ratio = {}, [], 0, 0.0, 0.0
    try:
        import fitz
        d = fitz.open(str(path))
        try:
            n = d.page_count
            meta = dict(d.metadata or {})
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
        finally:
            d.close()
    except Exception:
        if page_texts:
            n = len(page_texts)
    return n, aspect, img_ratio, meta, toc


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
        (f.page_count, f.aspect, f.image_ratio, f.meta, f.toc_titles) = \
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

_EXPLICIT = [   # ① 파일명/표제 명시어 — 순서 = 판정 순서
    ("지침", ("지침", "편람", "요령")),
    ("시방서", ("시방서", "specification")),
    ("기준", ("기준",)),
    ("법령", ("고시", "공고", "훈령", "예규", "법률", "시행령")),
    ("설명서", ("설명서", "매뉴얼", "사용자", "manual", "mnl", "guide", "_um_")),
    ("영수증", ("영수증", "세금계산서", "거래명세서", "invoice")),
    ("시험성적서", ("시험성적서", "성적서", "검사성적서", "test report")),
    ("공문", ("공문", "협조요청", "공람")),
]


def classify_format(f: Features, rules: dict | None = None) -> str | None:
    """§5.3 판정 순서: ①명시어 ②구조(영수증▶시험성적서▶공문▶논문) ③레이아웃 ④기본값.
    확신 없으면 None(형식 태그 없음 — 틀린 형식보다 없는 편이 낫다 §3.5-A).
    반환은 alias(§5.3 사용자 어휘 접합) 적용 후 표시명."""
    rules = rules or {}
    name = (f.stem + " " + str(f.meta.get("title") or "")).lower()
    txt = f.struct_text[:20000].lower()      # ★ 원문 기준(위 보강) — 스캔이면 자연히 빈 문자열
    fmt = None

    # ① 명시어 — 사람이 이름에 써 둔 것이 가장 확실
    for tag, keys in _EXPLICIT:
        if any(k in name for k in keys):
            fmt = tag
            break
    if fmt is None and re.search(r"k[cd]s\s?\d{2}\s?\d{2}\s?\d{2}", name + " " + txt[:3000]):
        fmt = "기준"                    # KCS/KDS 6자리 코드(§5.3 결정적 신호)

    # ② 강한 구조 신호 — 토큰이 특이한 순(§5.3 — ③보다 먼저: 짧은 문서 오분류 방지)
    if fmt is None and txt:
        if "사업자등록번호" in txt and ("합계" in txt or "공급가액" in txt):
            fmt = "영수증"
        elif (("시험항목" in txt or "시험결과" in txt) and "판정" in txt):
            fmt = "시험성적서"
        elif ("수신" in txt and ("발신" in txt or "참조" in txt
                                or re.search(r"제\s?\d{2,4}\s?[-–]\s?\d+\s?호", txt))):
            fmt = "공문"
        elif (("abstract" in txt and "reference" in txt)
              or "doi:" in txt or "doi.org" in txt
              or re.search(r"\bet\s+al\b", txt)):
            fmt = "논문"

    # ③ 레이아웃 신호(텍스트 불요 — 스캔 PDF 에도 동작 §4.2 각주)
    if fmt is None and f.page_count:
        if (f.aspect >= TUNING["PRESENT_MIN_AR"]
                and f.text_per_page < TUNING["PRESENT_MAX_CHARS"]):
            fmt = "발표자료"
        elif (f.page_count <= TUNING["BROCHURE_MAX_PAGES"]
              and f.image_ratio >= TUNING["BROCHURE_IMG_RATIO"]
              and f.text_per_page < TUNING["PRESENT_MAX_CHARS"]):
            fmt = "브로셔"
        elif (f.page_count <= TUNING["ARTICLE_MAX_PAGES"] and txt
              and re.search(r"\d{4}\s?[.\-/년]\s?\d{1,2}\s?[.\-/월]", txt)):
            fmt = "기사"

    # ④ 기본값 — 보고서(조건 못 맞추면 형식 없음)
    if fmt is None:
        if "보고서" in name or "report" in name:
            fmt = "보고서"
        elif f.page_count >= TUNING["REPORT_MIN_PAGES"] and not f.scanned:
            fmt = "보고서"

    if fmt is None:
        return None
    alias = rules.get("alias") or {}
    return str(alias.get(fmt, fmt))


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
                 extra=None) -> list:
    """제안 목록(§4 API): [{tag, score, kind, axis, why}]. extra 는 §5.5 확장점(항상 None).
    형식은 판정 서면 score 없이도 자동 대상(§5.6 표 1행) — score 는 표시용 1.0."""
    known = {t.lower() for t in (known_tags or [])}
    out = []
    fmt = classify_format(f, rules)
    if fmt:
        out.append({"tag": fmt, "score": 1.0, "axis": "형식",
                    "kind": "existing" if fmt.lower() in known else "new",
                    "why": "형식 규칙(§5.3)"})
    # 주제 점수(§5.6): max(L1 유사도, 폴더명 일치 0.75) + 겹침 보너스 0.10
    sims = {} if f.scanned else topic_similarities(f, profiles, df, n_docs)
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
        if s.get("axis") == "형식":
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
    cand.update(_bigrams(_token_seq(f.full_text)))
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
