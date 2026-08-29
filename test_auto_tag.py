# -*- coding: utf-8 -*-
"""태그 SOT P0 회귀 테스트 — 스키마 v2 · 지문 재연결 · 원자적 쓰기 (§6·§6.1·§12).
Qt 불필요(순수 로직) — QApplication 없이 돈다."""
import json
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_fixtures import scanned_pdf, text_pdf  # noqa: E402
from viewer.tag_store import TagStore  # noqa: E402

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAIL += 1


WORK = tempfile.mkdtemp(prefix="polypdf_tagv2_")
STORE = os.path.join(WORK, "file_tags.json")
PDF = str(text_pdf())
PDF2 = str(scanned_pdf())


def fresh(data=None) -> TagStore:
    if data is None:
        try:
            os.remove(STORE)
        except OSError:
            pass
    else:
        with open(STORE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    return TagStore(STORE)


def key(p):
    return TagStore._key(p)


# ── §12-1) v1(list) 하위호환 — get() 계약 유지 (회귀 방지 1순위) ─────────
a = os.path.join(WORK, "a.pdf")
b = os.path.join(WORK, "b.pdf")
shutil.copy2(PDF, a)
shutil.copy2(PDF2, b)
st = fresh({key(a): ["논문", "아스팔트"], key(b): ["설명서"]})
check("v1 로드 → get() 동일", st.get(a) == ["논문", "아스팔트"] and st.get(b) == ["설명서"])
check("v1 all_tags/카운트", st.tag_counts() == {"논문": 1, "아스팔트": 1, "설명서": 1})

# v1 항목에 set() → 여전히 list 형태 유지(파일 최소 변경)
st.set(a, "논문 배수성")
raw = json.loads(open(STORE, encoding="utf-8").read())
check("v1 set() 후에도 list 유지", isinstance(raw[key(a)], list) and st.get(a) == ["논문", "배수성"])

# ── §12-2) set() 이 auto/rejected/keywords 를 보존 ───────────────────────
st.set_auto(a, ["순환"], conf={"순환": 0.7})
st.reject(a, ["포장"])
st.set_keywords(a, ["배수성 아스팔트", "공극률"])
st.set(a, "논문")                       # manual 만 교체
check("set() 후 auto 보존", st.get_auto(a) == ["순환"])
check("set() 후 rejected 보존", st.get_rejected(a) == ["포장"])
check("set() 후 keywords 보존", st.get_keywords(a) == ["배수성 아스팔트", "공극률"])
check("get() = manual+auto 합집합", st.get(a) == ["논문", "순환"])
check("is_auto 구분", st.is_auto(a, "순환") and not st.is_auto(a, "논문"))

# ── §12-3) rejected 는 재부여 금지 ───────────────────────────────────────
st.set_auto(a, ["포장", "배수성"])
check("rejected 재부여 금지", "포장" not in st.get(a) and "배수성" in st.get_auto(a))
check("manual 중복 자동 제외", "논문" not in st.get_auto(a))

# ── §12-19) promote — 승격 후 재계산이 못 건드림 ─────────────────────────
st.promote(a, ["배수성"])
check("promote → manual 이동", "배수성" in st.get_manual(a) and not st.is_auto(a, "배수성"))
st.set_auto(a, ["순환"])                # 재계산 시뮬 — manual 이 된 배수성은 그대로
check("promote 후 재계산 무영향", "배수성" in st.get_manual(a))

# ── §12-20) clear_auto_tag — 다른 태그·수동 보존 ─────────────────────────
st.set_auto(b, ["순환", "도로"])
st.clear_auto_tag("순환")
check("clear_auto_tag 선택 회수", st.get_auto(a) == [] and st.get_auto(b) == ["도로"])
check("clear_auto_tag 수동 보존", "논문" in st.get(a) and st.get(b)[0] == "설명서")

# §12-16) clear_auto — manual 바이트 무손실
before_manual = {k: st.get_manual(k) for k in (a, b)}
st.clear_auto()
check("clear_auto 후 auto 0", st.get_auto(a) == [] and st.get_auto(b) == [])
check("clear_auto 후 manual 무손실",
      {k: st.get_manual(k) for k in (a, b)} == before_manual)

# ── 키워드·연도 필드 ────────────────────────────────────────────────────
st.set_keywords(a, [f"kw{i}" for i in range(15)])
check("키워드 10개 상한", len(st.get_keywords(a)) == 10)
st.set_keywords(a, ["직접 수정"], edited=True)
check("kw_edited 플래그", st.kw_edited(a))
st.set_year(a, 2025, src="name", conf=0.9)
check("연도 필드 저장", st.get_year(a) == 2025 and st.get_year_info(a)[1] == "name")
check("★ 연도가 태그에 안 섞임(§3.6)",
      "2025" not in st.tag_counts() and 2025 not in st.tag_counts())

# ── §12-59) 원자적 쓰기 + §12-60) 일괄 저장 1회 ─────────────────────────
check("tmp 잔재 없음", not os.path.exists(STORE + ".tmp"))
orig_replace = os.replace
n_writes = {"n": 0}


def counting_replace(src, dst):
    n_writes["n"] += 1
    return orig_replace(src, dst)


os.replace = counting_replace
try:
    with st.bulk():
        for i in range(50):
            st.set(os.path.join(WORK, f"bulk{i}.pdf"), ["논문"])
finally:
    os.replace = orig_replace
check("★ 일괄 50건 = 디스크 쓰기 1회", n_writes["n"] == 1, f"writes={n_writes['n']}")
check("일괄 후 데이터 유효", TagStore(STORE).get(os.path.join(WORK, "bulk49.pdf")) == ["논문"])
with st.bulk():
    for i in range(50):
        st.set(os.path.join(WORK, f"bulk{i}.pdf"), [])   # 정리

# ── §12-39~41) 이동·이름변경 → 태그 유지 (지문 재연결) ───────────────────
mv_src = os.path.join(WORK, "mv_src.pdf")
shutil.copy2(PDF, mv_src)
st.set(mv_src, "논문 배수성")
fp = st.ensure_fp(mv_src)
check("지문 계산·저장", bool(fp) and (fp.startswith("id:") or fp.startswith("h64:")))
mv_dst = os.path.join(WORK, "sub_moved", "renamed.pdf")
os.makedirs(os.path.dirname(mv_dst), exist_ok=True)
os.replace(mv_src, mv_dst)                       # 이동+이름변경
r = st.rehome_missing(mv_dst)
check("★ 이동 → 태그 따라옴", r == "moved" and st.get(mv_dst) == ["논문", "배수성"])
check("옛 경로 항목 삭제(§12-44)", st.get(mv_src) == [] and key(mv_src) not in st._data)
check("경로 적중 시 지문 계산 없음", st.rehome_missing(mv_dst) == "exists")

# §12-41) /ID 없는 파일 → h64 폴백
noid = os.path.join(WORK, "noid.bin")            # PDF 아님 → id: 실패 → h64
with open(noid, "wb") as f:
    f.write(b"NOT-A-PDF" * 4000)
st.set(noid, "기타")
fp2 = st.ensure_fp(noid)
check("h64 폴백", fp2 is not None and fp2.startswith("h64:"))

# ── §12-42) 복사본은 상속하지 않는다 ─────────────────────────────────────
cp = os.path.join(WORK, "copyed.pdf")
shutil.copy2(mv_dst, cp)                         # 원본이 남아 있는 복사
r = st.rehome_missing(cp)
check("★ 복사본 미상속", r == "copy" and st.get(cp) == [])

# ── §12-57~58) 지문 충돌 가드 — /ID 를 공유하는 분할 형제 시뮬 ───────────
# 실제 시나리오: 분할 산출물들이 같은 /ID[0] 를 갖는다. monkeypatch 로
# '비강제 지문 = 항상 같은 id:' 를 만들고, h64(내용) 는 실제값을 쓴다.
sib1 = os.path.join(WORK, "sib1.pdf")
sib2 = os.path.join(WORK, "sib2.pdf")
shutil.copy2(PDF, sib1)                          # 내용 서로 다름(h64 상이)
shutil.copy2(PDF2, sib2)
st.set(sib1, "형제1")
st.set(sib2, "형제2")
_orig_fp = TagStore._fp_of


def _shared_id_fp(path, force_h64=False):
    if force_h64:
        return _orig_fp(path, True)
    return "id:deadbeef", os.path.getsize(path)  # /ID 공유 시뮬


TagStore._fp_of = staticmethod(_shared_id_fp)
try:
    st.ensure_fp(sib1)                           # id:deadbeef 등록
    st.ensure_fp(sib2)                           # ★ 가드 ② — 등록 시 충돌 감지 → 양쪽 h64 강등
    fp1 = st._data[key(sib1)]["fp"]
    fp2s = st._data[key(sib2)]["fp"]
    check("★ 등록 시 id 중복 → 양쪽 h64 강등",
          fp1.startswith("h64:") and fp2s.startswith("h64:") and fp1 != fp2s)
    sib1_moved = os.path.join(WORK, "sib1_moved.pdf")
    os.replace(sib1, sib1_moved)
    r = st.rehome_missing(sib1_moved)            # 이동 파일 지문은 id: → h64 2차 조회 필요
    check("★ 강등 후 이동 → h64 2차 조회로 재연결",
          r == "moved" and st.get(sib1_moved) == ["형제1"], f"r={r}")
    check("형제 태그 무영향", st.get(sib2) == ["형제2"])
finally:
    TagStore._fp_of = staticmethod(_orig_fp)

# 진짜 모호 — 바이트 동일 사본 2개(id·h64 전부 동일)가 모두 자리를 비운 경우
tw1 = os.path.join(WORK, "tw1.pdf")
tw2 = os.path.join(WORK, "tw2.pdf")
shutil.copy2(PDF, tw1)
shutil.copy2(PDF, tw2)
st.set(tw1, "쌍둥이1")
st.set(tw2, "쌍둥이2")
h64fp = TagStore._fp_of(tw1, force_h64=True)[0]
for _k in (tw1, tw2):
    st.ensure_fp(_k)
    st._data[key(_k)]["fp"] = h64fp              # 동일 내용 사본 시뮬
tw_moved = os.path.join(WORK, "tw_moved.pdf")
os.replace(tw1, tw_moved)
os.remove(tw2)
r = st.rehome_missing(tw_moved)
check("★ 진짜 모호 → 재연결 포기", r == "ambiguous" and st.get(tw_moved) == [], f"r={r}")

# ── §12-61) 삭제 → 항목 보존 → 복원 시 태그 생존 ─────────────────────────
dl = os.path.join(WORK, "del.pdf")
shutil.copy2(PDF, dl)
st.set(dl, "보존확인")
side = dl + ".trash"
os.replace(dl, side)                             # 휴지통 시뮬
check("삭제 후 항목 보존", key(dl) in st._data)
os.replace(side, dl)                             # 복원
check("복원 시 태그 생존", st.get(dl) == ["보존확인"])

# ── §12-62) prune_missing — 없는 것만, 개수 반환 ─────────────────────────
gone = os.path.join(WORK, "gone.pdf")
st.set(gone, "고아")
n_alive = len(st._data)
check("count_missing", st.count_missing() >= 1)
removed = st.prune_missing()
check("prune 는 없는 항목만", removed >= 1 and key(gone) not in st._data
      and st.get(dl) == ["보존확인"], f"removed={removed}")

# ── rehome(직접 이동, §8.6 용 — 지문 불요) ──────────────────────────────
dr = os.path.join(WORK, "direct.pdf")
shutil.copy2(PDF, dr)
st.set(dr, "직접이동")
dr2 = os.path.join(WORK, "direct2.pdf")
os.replace(dr, dr2)
st.rehome(dr, dr2)
check("rehome 직접 이동", st.get(dr2) == ["직접이동"] and st.get(dr) == [])

# ── 백업/복원 (§6·§8.5 되돌리기) ────────────────────────────────────────
snapshot = json.dumps(st._data, sort_keys=True, ensure_ascii=False)
check("backup 성공", st.backup())
st.set_auto(dl, ["오염태그"])
st.clear_auto_tag("직접이동")
check("restore 성공", st.restore_backup())
check("★ 복원 = 스냅샷과 완전 일치",
      json.dumps(st._data, sort_keys=True, ensure_ascii=False) == snapshot)

# ═════════════════════════ P1 — auto_tag.py (§4·§5.2·§5.3·§5.6·§9.4) ═════
import fitz  # noqa: E402
from collections import Counter  # noqa: E402

from viewer import auto_tag as AT  # noqa: E402
from viewer.auto_tag import (Features, build_profiles, classify_format,  # noqa: E402
                             extract_features, extract_year, partition,
                             strip_headers, suggest_tags, topic_similarities)


def _mk_pdf(name, pages, image_pages=()):
    """테스트 전용 소형 PDF 생성(§12 — 외부 파일 의존 금지).
    pages = [(w, h, text), ...]; image_pages 인덱스엔 전면 이미지 삽입."""
    p = os.path.join(WORK, name)
    d = fitz.open()
    pm = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60))
    pm.set_rect(pm.irect, (200, 60, 60))
    for i, (w, h, text) in enumerate(pages):
        pg = d.new_page(width=w, height=h)
        if text:
            pg.insert_textbox(fitz.Rect(30, 30, w - 30, h - 30), text, fontsize=10)
        if i in image_pages:
            pg.insert_image(fitz.Rect(5, 5, w - 5, h - 5), pixmap=pm)
    d.save(p)
    d.close()
    return p


def _fmt(path, texts=None, **kw):
    """★ 텍스트는 page_texts 로 직접 공급 — 프로덕션 경로(index.db 공급)와 동일.
    (테스트 PDF 의 기본 폰트가 한글을 '?' 로 렌더해 추출 텍스트를 쓸 수 없다.)"""
    return classify_format(extract_features(path, page_texts=texts), **kw)


os.makedirs(WORK, exist_ok=True)

# ── 형식 분류기 (§5.3 — §12-23~30) ──────────────────────────────────────
present = _mk_pdf("발표.pdf", [(960, 540, f"슬라이드 {i}") for i in range(12)])
check("§12-25 발표자료(가로+저텍스트)", _fmt(present) == "발표자료")

guide_land = _mk_pdf("포장 지침.pdf", [(960, 540, "요약") for _ in range(12)])
check("§12-23 명시어가 레이아웃을 이김", _fmt(guide_land) == "지침")

receipt = _mk_pdf("거래.pdf", [(595, 842,
    "공급자 (주)도로자재\n사업자등록번호 123-45-67890\n공급가액 1,200,000\n합계 1,320,000")])
_r_txt = ["공급자 (주)도로자재 사업자등록번호 123-45-67890 공급가액 1,200,000 합계 1,320,000"]
check("§12-25a 영수증 1p — 기사로 안 샘", _fmt(receipt, _r_txt) == "영수증")

cert = _mk_pdf("자재시험.pdf", [(595, 842,
    "시험항목: 압축강도\n시험결과: 32.5 MPa\n판정: 합격\n발급 수수료 20,000원"),
    (595, 842, "시험기관: 한국건설시험원 KS F 2405")])
_c_txt = ["시험항목: 압축강도 시험결과: 32.5 MPa 판정: 합격 발급 수수료 20,000원 "
          "시료명 아스팔트 혼합물 채취일 규격 밀도 안정도 흐름값 공극률 포화도",
          "시험기관: 한국건설시험원 주소 경기도 고양시 시험자 홍길동 심의자 김철수 "
          "시험일자 비고 본 성적서는 시험 시료에 한하며 무단 복제를 금합니다"]
check("§12-29b 시험성적서(수수료 금액 있어도)", _fmt(cert, _c_txt) == "시험성적서")

official = _mk_pdf("점검안내.pdf", [(595, 842,
    "수신 서울시설공단\n발신 안전보건실\n문서번호 제2025-123호\n합동점검을 안내합니다."),
    (595, 842, "붙임 1부. 끝.")])
_o_txt = ["수신 서울시설공단 발신 안전보건실 문서번호 제2025-123호 합동점검 안내 "
          "귀 기관의 무궁한 발전을 기원합니다 아래와 같이 점검 일정을 알려드리니 협조 바랍니다",
          "일시 장소 참석 대상 준비 서류 안전보건 관리 계획서 붙임 1부. 끝. "
          "담당자 연락처 문의 사항은 안전보건실로 연락 주시기 바랍니다"]
check("§12-26b 공문 2p — 브로셔 아님", _fmt(official, _o_txt) == "공문")

paper = _mk_pdf("study.pdf", [(595, 842,
    "Abstract\nPorous asphalt mixture performance."), (595, 842, "Method by Kim et al. 2020")]
    + [(595, 842, f"body {i}") for i in range(5)]
    + [(595, 842, "References\n[1] doi:10.1000/x")])
_topics = ["gradation design", "binder content", "compaction energy",
           "permeability testing", "rutting resistance", "field validation"]
_p_txt = (["Abstract Porous asphalt mixture performance study with detailed analysis."]
          + [f"Method by Kim et al. 2020 covering {t} with experimental data and results."
             for t in _topics]
          + ["References [1] doi:10.1000/x journal of pavement engineering"])
check("§12 논문(구조 신호)", _fmt(paper, _p_txt) == "논문")

brochure = _mk_pdf("홍보물.pdf", [(595, 842, "신제품") for _ in range(4)],
                   image_pages=(0, 1, 2, 3))
check("§12-26 브로셔(≤8p·이미지 비중)", _fmt(brochure) == "브로셔")

article = _mk_pdf("스크랩.pdf", [(595, 842,
    "도로신문 2024.03.15\n배수성 포장 확대" + " 본문" * 200) for _ in range(3)])
_a_txt = ["도로신문 2024.03.15 배수성 포장 확대" + " 본문" * 200] * 3
check("§12-26 기사(≤4p+발행일)", _fmt(article, _a_txt) == "기사")

unknown = _mk_pdf("메모.pdf", [(595, 842, "회의 메모" + " 항목" * 300) for _ in range(3)])
_u_txt = ["회의 메모" + " 항목" * 300] * 3
check("§12-27 판정 불가 → 형식 없음", _fmt(unknown, _u_txt) is None)

plain25 = _mk_pdf("연구자료.pdf", [(595, 842, f"내용 {i}" + " 본문" * 300)
                                   for i in range(25)])
check("§12 기본값 보고서(≥20p)", _fmt(plain25) == "보고서")
check("§12-29 alias 매핑(보고서→외국보고서)",
      _fmt(plain25, rules={"alias": {"보고서": "외국보고서"}}) == "외국보고서")

alias_name = _mk_pdf("세금계산서_3월.pdf", [(595, 842, "내역")])
check("§12-29 별칭 파일명 → 영수증", _fmt(alias_name) == "영수증")

check("형식은 파일당 1개(§12-24) — 반환형 str",
      isinstance(_fmt(receipt, _r_txt), str))

# 스캔 PDF(§12-28): 텍스트 0 — 형식(파일명)·연도는 나오고 주제는 억제
scan_guide = os.path.join(WORK, "스캔 포장지침 2021.pdf")
shutil.copy2(PDF2, scan_guide)
sf = extract_features(scan_guide)
check("§12-28 스캔 감지", sf.scanned)
check("§12-28 스캔에도 형식(파일명)", classify_format(sf) == "지침")
sy, ssrc, _ = extract_year(sf, today_year=2026)
check("§12-28 스캔에도 연도(파일명)", sy == 2021 and ssrc == "name")
sugg = suggest_tags(sf, {"배수성": {"porous": 1.0}}, {}, 1)
check("§12-28 스캔 → 주제 억제", all(s["axis"] == "형식" for s in sugg))

# ── 260829 보강: 형식·스캔 판정은 머리말 제거 '전' 원문 기준 ─────────────
# 여러 페이지 성적서 철 — 구조 토큰(시험항목·판정)이 전 페이지에 정당하게 반복.
# 제거 후 텍스트로 판정하면 미분류로 빠지던 실결함의 회귀 테스트.
_book_pg = ("시험항목: 압축강도 시험결과: 32.5 MPa 판정: 합격 "
            "시험기관 한국건설시험원 시료 아스팔트 혼합물 공극률 밀도 안정도")
_book = [_book_pg] * 6                       # 6/6 페이지 반복 = 머리말 제거 대상
cert_book = _mk_pdf("성적서철.pdf", [(595, 842, t) for t in _book])
check("★ 반복 구조 성적서 철 → 시험성적서(원문 판정)",
      _fmt(cert_book, _book) == "시험성적서")
bf = extract_features(cert_book, page_texts=_book)
check("★ 반복 제거가 스캔 판정을 왜곡하지 않음", not bf.scanned)
check("특징어는 제거본 기준(머리말 반복어 소거)", bf.terms.get("시험항목") is None
      or bf.terms.get("시험항목", 0) <= AT.TUNING["W_NAME"])
check("SCAN_MIN_CHARS 가 TUNING 에 있음(§9.3)", "SCAN_MIN_CHARS" in AT.TUNING)

# ── 머리말 제거 (§12-6) ─────────────────────────────────────────────────
_words = ["개요", "재료", "배합", "시공", "다짐", "양생", "평가", "유지", "보수", "결언"]
hdr_pages = [f"대한도로학회 회보 제{i}호\n배수성 포장의 공극률 {_words[i]} 내용"
             for i in range(10)]
cleaned, removed = strip_headers(hdr_pages)
check("§12-6 머리말 반복 줄 제거", removed and all("회보" not in p for p in cleaned))
check("§12-6 본문은 보존", all("공극률" in p for p in cleaned))
short = ["머리말 없음"] * 3
check("§12-6 짧은 문서는 판정 안 함", strip_headers(short)[0] == short)

# ── L1 — §3.1-② 시나리오: 영문 논문 + #배수성 프로파일 (§12-4) ──────────
def _feat_txt(name, text):
    # 3페이지(<HDR_MIN_PAGES) — 동일 문장 반복이 머리말 제거에 걸리지 않게
    return extract_features(os.path.join(WORK, name), page_texts=[text] * 3,
                            open_pdf=False)

p1 = _feat_txt("p1.pdf", "porous asphalt OGFC drainage permeable void ratio")
p2 = _feat_txt("p2.pdf", "porous pavement OGFC permeable friction course drainage")
p3 = _feat_txt("p3.pdf", "open graded OGFC porous drainage stormwater")
manual_doc = _feat_txt("m1.pdf", "사용자 매뉴얼 설치 방법 화면 버튼 클릭 usb")
df = Counter()
for ft in (p1, p2, p3, manual_doc):
    df.update(set(ft.terms))
profiles = build_profiles({"배수성": [p1.terms, p2.terms, p3.terms],
                           "설명서": [manual_doc.terms]}, df, 4)
newdoc = _feat_txt("new.pdf",
                   "mix design of porous asphalt OGFC drainage layer permeable")
sims = topic_similarities(newdoc, profiles, df, 4)
check("§12-4 ★ 영문 porous 논문 → #배수성",
      sims.get("배수성", 0) >= AT.TUNING["SUGGEST_MIN"]
      and sims["배수성"] > sims.get("설명서", 0), f"sims={sims}")
sg = suggest_tags(newdoc, profiles, df, 4, known_tags=["배수성", "설명서"])
check("제안에 주제 태그 포함", any(s["tag"] == "배수성" and s["axis"] == "주제"
                                   for s in sg))

# ── 연도 추출 (§9.4 — §12-46~52) ────────────────────────────────────────
def _yr(stem="", folders=(), head="", meta=None):
    ft = Features(stem=stem, head_text=head, meta=meta or {},
                  folder_names=list(folders))
    return extract_year(ft, today_year=2026)

check("§12-46 파일명 YYYYMMDD", _yr("vpn 사용자 매뉴얼-20250818")[0] == 2025)
check("§12-47 ★ v버전 오탐 방지", _yr("mnl+om,kor,dc-v4212+#2+brand-kr,v1.0")[0] is None)
check("§12-48 ★ 미래 연도 거부", _yr("계획서 2027")[0] is None)
check("§12-49 2자리 연도 미채택", _yr("24 아스팔트콘크리트포장시공지침")[0] is None)
check("§9.4-② 폴더 YYMMDD", _yr("자료", folders=["230718바이오매스"]) == (2023, "folder", 0.8))
check("폴더 6자리 단독(250527)", _yr("자료", folders=["250527"])[0] == 2025)
check("폴더 순번 오탐 없음(10. 건축연구본부)", _yr("자료", folders=["10. 건축연구본부"])[0] is None)
check("§12 1페이지 ©연도", _yr("자료", head="© 2021 Korea Expressway") == (2021, "page1", 0.6))
check("§12-50 ★ 본문(참고문헌) 안 훑음 — head 밖 연도 무시",
      _yr("자료", head="")[0] is None)
check("meta 최후 폴백(저신뢰)", _yr("자료", meta={"creationDate": "D:20190402"})
      == (2019, "meta", 0.3))
check("§12-52 못 찾으면 None(추측 금지)", _yr("아스팔트 지침") == (None, "", 0.0))

# ── 2단 임계값·상한 (§5.6 — §12-14·15·22·30) ────────────────────────────
mk = lambda tag, sc, kind, ax: {"tag": tag, "score": sc, "kind": kind,
                                "axis": ax, "why": "t"}
res = partition([
    mk("발표자료", 1.0, "new", "형식"),            # 신규 형식 → 자동(§5.4-5 예외)
    mk("배수성", 0.70, "existing", "주제"),
    mk("순환", 0.60, "existing", "주제"),
    mk("아스팔트", 0.58, "existing", "주제"),
    mk("포장설계", 0.57, "existing", "주제"),      # 주제 4번째 → 상한 초과
    mk("바이오", 0.40, "existing", "주제"),        # 게이트 미달 → 제안만
    mk("공극률", 0.90, "new", "주제"),             # 신규 주제 → 점수 무관 미부여
])
auto_tags = [s["tag"] for s in res["auto"]]
check("§12-30 신규 형식 자동 부여", "발표자료" in auto_tags)
check("§12-14 게이트 미달 → 제안만", "바이오" not in auto_tags)
check("§12-15 ★ 신규 주제 점수 무관 미부여", "공극률" not in auto_tags)
check("§12-22 상한 형식1+주제3", len(auto_tags) == 4
      and "포장설계" not in auto_tags, f"auto={auto_tags}")
check("제안 목록에 잔여 보존", {s["tag"] for s in res["suggest"]}
      >= {"포장설계", "바이오", "공극률"})

# 축 유도(§5.1 — auto_axis 필드 없이)
check("axis_of 유도", AT.axis_of("논문") == "형식" and AT.axis_of("배수성") == "주제"
      and AT.axis_of("외국보고서", {"alias": {"보고서": "외국보고서"}}) == "형식")

# 프로파일 캐시(§5.2 — mtime 무효화)
cachep = os.path.join(WORK, "tag_profile.json")
AT.save_profile_cache(cachep, 111, profiles)
check("프로파일 캐시 적중", AT.load_profile_cache(cachep, 111) is not None)
check("프로파일 캐시 mtime 무효화", AT.load_profile_cache(cachep, 222) is None)

# ═════════════════════ P2 — 자동 부여 파이프라인 (§8.2·§8.3·§8.5) ═════════
# 여기부터는 Qt 필요(워커·트리 라벨) — 오프스크린.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication  # noqa: E402

_qapp = QApplication(sys.argv)
_qapp.setApplicationName("PolyPDF")
_qapp.setOrganizationName("LocalTools")

from viewer.workers import AutoTagWorker  # noqa: E402

P2DIR = os.path.join(WORK, "p2폴더")
os.makedirs(P2DIR, exist_ok=True)
# 시나리오 폴더: 지침(파일명)·발표(레이아웃)·영문 porous 논문 4건(3 태그 + 1 신규)
p2_files = {}
p2_files["지침"] = _mk_pdf(os.path.join("p2폴더", "포장 관리 지침.pdf"),
                           [(595, 842, "content page " + "word " * 30)] * 3)
p2_files["발표"] = _mk_pdf(os.path.join("p2폴더", "성과 발표.pdf"),
                           [(960, 540, f"slide {i}") for i in range(12)])
_eng = ("porous asphalt OGFC drainage permeable void ratio design "
        "mixture gradation performance evaluation test result")
for i in range(1, 5):
    p2_files[f"논문{i}"] = _mk_pdf(os.path.join("p2폴더", f"porous_{i}_2023.pdf"),
                                   [(595, 842, _eng + f" variant {i}")] * 3)

p2_store_path = os.path.join(WORK, "p2_tags.json")
st2 = TagStore(p2_store_path)
for i in range(1, 4):                          # 3건에 수동 태그(시범 입력 시뮬)
    st2.set(p2_files[f"논문{i}"], "배수성")
st2.reject(p2_files["논문4"], ["거부태그"])     # rejected 존중 확인용

_results = {}


def _collect(res, stats):
    _results["res"] = res
    _results["stats"] = stats


tagged = {"배수성": [p2_files[f"논문{i}"] for i in range(1, 4)]}
w = AutoTagWorker(db_path=os.path.join(WORK, "no_index.db"),
                  paths=list(p2_files.values()), tagged_docs=tagged,
                  known_tags=st2.all_tags(), rules={}, today_year=2026,
                  store_keys=set(st2._data.keys()), fp_missing_keys=set())
w.finished.connect(_collect)
w.error.connect(lambda e: _results.update(err=e))
w.run()                                        # 동기 실행(테스트 결정성)
check("P2 워커 완료(오류 없음)", "res" in _results and "err" not in _results,
      str(_results.get("err", "")))
res_by_path = {r["path"]: r for r in _results.get("res", [])}


def _auto_tags_of(key_):
    r = res_by_path.get(p2_files[key_], {})
    return [t for t, _ in r.get("auto", [])]


check("P2 형식 자동(지침·파일명)", "지침" in _auto_tags_of("지침"))
check("P2 형식 자동(발표자료·레이아웃)", "발표자료" in _auto_tags_of("발표"))
check("P2 ★ L1 주제 자동 — 4번째 porous 논문에 배수성",
      "배수성" in _auto_tags_of("논문4"), f"auto={_auto_tags_of('논문4')}")
check("P2 연도(파일명 2023)", res_by_path[p2_files["논문4"]]["year"] == 2023)
check("P2 신규 파일 지문 동봉", bool(res_by_path[p2_files["발표"]].get("fp")))

# 적용 단계 시뮬(§6 백업 → bulk 적용) — app._on_autotag_finished 와 같은 순서
assert st2.backup()
with st2.bulk():
    for r in _results["res"]:
        if r.get("fp"):
            s_ = st2.rehome_missing(r["path"], fp=r["fp"], size=r.get("size"))
            if s_ == "exists":
                st2.set_fp(r["path"], r["fp"], r.get("size") or 0)
        if r["auto"]:
            st2.set_auto(r["path"], [t for t, _ in r["auto"]],
                         conf={t: s for t, s in r["auto"]})
        if r.get("year"):
            st2.set_year(r["path"], r["year"], r["year_src"], r["year_conf"])
check("P2 적용 — manual 무손실", st2.get_manual(p2_files["논문1"]) == ["배수성"])
check("P2 적용 — 자동 태그 저장+conf",
      st2.is_auto(p2_files["논문4"], "배수성")
      and st2._data[key(p2_files["논문4"])]["auto_conf"].get("배수성", 0) > 0)
check("P2 적용 — rejected 존중(재부여 안 됨)",
      "거부태그" not in st2.get(p2_files["논문4"]))
check("P2 적용 — 연도는 태그 아님", "2023" not in st2.tag_counts())
assert st2.restore_backup()
check("P2 되돌리기 — 자동 부여 전으로", st2.get_auto(p2_files["논문4"]) == [])

# ── 트리 표시 구분(§8.3 — MainWindow 통합) ──────────────────────────────
from viewer.app import MainWindow  # noqa: E402

mw = MainWindow()
mw._skip_save_on_close = True
tree = mw.bookmark_tree
# ★ 실사용 store 를 건드리지 않는다 — 임시 store 로 교체(§13 게이트: 원본은 사본으로만)
tstore = TagStore(os.path.join(WORK, "ui_tags.json"))
tree._tags = tstore
tree_pdf = os.path.join(WORK, "표시확인.pdf")
shutil.copy2(PDF, tree_pdf)
tstore.set(tree_pdf, "수동태그")
tstore.set_auto(tree_pdf, ["자동태그"])
tstore.set_year(tree_pdf, 2024, "name", 0.9)
tstore.set_keywords(tree_pdf, ["키워드하나"])
from PyQt6.QtWidgets import QTreeWidgetItem  # noqa: E402

it = QTreeWidgetItem(["표시확인"])
it.setData(0, tree.DATA_FILE, tree_pdf)
tree.tree.addTopLevelItem(it)
tree._apply_tag_label(it, tree_pdf)
lbl = it.text(0)
check("§8.3 표시 — 수동 #·자동 ·# 구분", "#수동태그" in lbl and "·#자동태그" in lbl
      and "#자동태그" != lbl, f"lbl={lbl!r}")
check("§8.3 연도·키워드는 접미 아님·툴팁", "2024" not in lbl
      and "2024" in it.toolTip(0) and "키워드하나" in it.toolTip(0))
check("§8.5 자동 취소 어휘", "자동태그" in tstore.auto_tag_set())
tree._revoke_auto_tag("자동태그")
check("§8.5 이 태그만 회수", not tstore.is_auto(tree_pdf, "자동태그")
      and tstore.get_manual(tree_pdf) == ["수동태그"])
# 정리 — 실제 사용자 store 에 넣은 테스트 항목 제거
tstore.set(tree_pdf, [])
tstore.set_year(tree_pdf, None)
tstore.set_keywords(tree_pdf, [])

# 설정 키 회귀(§14.2 허용목록 함정)
check("P2 설정 기본값", mw._prefs.get("auto_tag_enabled") is True)
mw._prefs["auto_tag_enabled"] = False
check("P2 끔 → 스캔 미시작", mw._start_autotag_scan() is None
      and getattr(mw, "_autotag_worker", None) is None)
mw._prefs["auto_tag_enabled"] = True

# ── 머지 게이트 3·5: 실제 file_tags.json 사본 하위호환 ───────────────────
real = os.path.expandvars(r"%APPDATA%\LocalTools\PolyPDF\file_tags.json")
if os.path.exists(real):
    real_copy = os.path.join(WORK, "real_tags.json")
    shutil.copy2(real, real_copy)
    orig = json.loads(open(real, encoding="utf-8").read())
    rst = TagStore(real_copy)
    ok_all = all(rst.get(k) == v for k, v in orig.items() if isinstance(v, list))
    check(f"★ 실데이터 사본({len(orig)}건) 전량 보존", ok_all)
    ok_manual = all(rst.get_manual(k) == v for k, v in orig.items()
                    if isinstance(v, list))
    check("★ 실데이터 manual 무손실", ok_manual)
else:
    print("SKIP  실데이터 사본(파일 없음 — CI)")

shutil.rmtree(WORK, ignore_errors=True)
print()
print("결과:", "ALL PASS" if FAIL == 0 else f"FAIL {FAIL}건")
sys.stdout.flush()
os._exit(0 if FAIL == 0 else 1)
