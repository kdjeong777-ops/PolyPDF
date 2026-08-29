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
