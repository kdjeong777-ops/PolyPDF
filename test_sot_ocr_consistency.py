# -*- coding: utf-8 -*-
"""260912-1: OCR 규칙이 **한 곳에만** 적혀 있고, 그 값이 코드와 같은가.

사용자 지시: "OCR 관련 SOT 와 전체 SOT 를 검토해 상충되거나 나뉘어져 있는 것이
있는지 살펴보고, 앞으로 업그레이드시 통일성이 있게 SOT 를 수정 보완해."

같은 규칙을 두 문서에 풀어 쓰면 **한쪽이 반드시 낡는다.** 실제로 낡았다 —
텍스트 창 SOT 는 언어를 `pytesseract.get_languages()` 로 거른다고 적혀 있었으나
코드는 단어학습 SOT §14.16 이래 `available_langs()` 를 쓴다. 글로 "가리키기만 하자"
고 정해 두는 것으로는 막을 수 없어, **검사로 고정**한다(단어학습 SOT §14.A·§14.B).

검사 대상은 SOT 본문뿐이다 — `§0 변경 이력` 은 **그때의 기록**이라 옛 값이 남아
있는 것이 정상이므로 제외한다.
"""
import os, re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(os.path.dirname(os.path.abspath(__file__)))
SOT_DIR = HERE.parent
NL = "\n"

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def read(p):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


OCR_SOT = "단어학습(OCR·어휘) 기능 작업계획서.md"
TXT_SOT = "텍스트 창 작업 계획서.md"
NAMED = {
    "텍스트 창": TXT_SOT,
    "단어학습": OCR_SOT,
    "응답성": "응답성 작업 계획서.md",
    "검색창": "검색창 작업 계획서.md",
    "단어장": "단어장 작업 계획서.md",
    "화면 디자인": "화면 디자인 작업 계획서.md",
}
SOTS = {p.name: read(p) for p in sorted(SOT_DIR.glob("*.md"))}
HAVE = OCR_SOT in SOTS and TXT_SOT in SOTS


def body(name):
    """§0 변경 이력을 뺀 본문 — 이력의 옛 값은 검사하지 않는다."""
    txt = SOTS.get(name, "")
    m = re.search(r"^## 0\. ", txt, re.M)
    if not m:
        return txt
    nxt = re.search(r"^## (?!0\.)", txt[m.end():], re.M)
    return txt[:m.start()] + (txt[m.end() + nxt.start():] if nxt else "")


def code(rel):
    return read(HERE / rel)


if not HAVE:
    print("SKIP - SOT 문서를 찾을 수 없다(공개 저장소 단독 체크아웃)")
    sys.exit(0)

OCR_PY = code("viewer/study/ocr.py")
NOISE_PY = code("viewer/text_noise.py")


def const(src, name, pat=r"[-+0-9.\"'a-zA-Z_+]+"):
    m = re.search(r"^%s\s*=\s*(%s)" % (re.escape(name), pat), src, re.M)
    return m.group(1).strip("\"'") if m else None


# ── ① 문서끼리 가리키는 절이 실제로 있는가 ────────────────────────────
print("=== ① SOT 가 가리키는 절이 실제로 있다 ===")
# 코드→SOT 는 test_sot_compliance.py 가 본다. 여기서는 **SOT→SOT**.
ref = re.compile(r"(텍스트 창|단어학습|응답성|검색창|단어장|화면 디자인)\s*SOT\s*"
                 r"(§[0-9]+(?:\.[0-9A-Z]+)*)")
bad = []
for name in SOTS:
    if name not in NAMED.values() and name not in (OCR_SOT, TXT_SOT):
        continue
    for who, sec in ref.findall(body(name)):
        doc = SOTS.get(NAMED[who], "")
        num = re.escape(sec[1:])
        if not re.search(r"^#{2,4} " + num + r"[ .]", doc, re.M):
            bad.append("%s → %s %s" % (name[:8], who, sec))
chk(not bad, "① 문서가 가리키는 절이 모두 실재한다", str(sorted(set(bad))[:8]))

# 이번에 실제로 낡아 있던 두 곳 — 되돌아오면 바로 잡는다
chk("§14.18" in body(TXT_SOT), "① 텍스트 창이 스캔 감지를 §14.18 로 가리킨다")
chk("§14.3)" not in body(TXT_SOT),
    "① 스캔 감지·study.db 를 §14.3(P0 지적 목록)으로 가리키지 않는다")

# ── ② OCR 숫자는 한 SOT 에만 (§14.B) ──────────────────────────────────
print(NL + "=== ② OCR 숫자는 한 문서에만 적는다 (§14.B) ===")
OWNED = [
    # (이름, 본문에서 찾을 정규식, 소유 문서, 코드값)
    ("WM_KEEP_LUMA", r"WM_KEEP_LUMA\s*=\s*\d+", OCR_SOT, None),
    ("MIN_CONF", r"MIN_CONF\s*=\s*[0-9.]+", TXT_SOT, None),
]
for nm, pat, owner, _v in OWNED:
    where = [d for d in SOTS if re.search(pat, body(d))]
    chk(where == [owner], "② `%s` 값은 %s 에만 있다" % (nm, owner[:8]), str(where))

chk(re.search(r"WM_KEEP_LUMA\s*=\s*\d+", body(OCR_SOT)) is None
    or body(OCR_SOT).count("WM_KEEP_LUMA = ") <= 1,
    "② 소유 문서 안에서도 값은 한 번만 적는다")

# ── ③ 적어 둔 값이 코드와 같은가 ──────────────────────────────────────
print(NL + "=== ③ SOT 의 값이 코드와 같다 ===")
b14 = body(OCR_SOT)
psm = const(OCR_PY, "DEFAULT_PSM")
lang = const(OCR_PY, "DEFAULT_LANG")
back = const(OCR_PY, "FALLBACK_LANG")
luma = const(OCR_PY, "WM_KEEP_LUMA")
conf = const(NOISE_PY, "MIN_CONF")
chk(psm == "4" and ("psm %s" % psm) in b14, "③ psm 값이 코드와 같다", "code=%s" % psm)
chk(lang == "kor+eng" and ("`%s`" % lang) in b14, "③ 기본 언어가 코드와 같다", "code=%s" % lang)
chk(back == "eng" and ("`%s`" % back) in b14, "③ 대체 언어가 코드와 같다", "code=%s" % back)
chk(luma == "140" and ("WM_KEEP_LUMA = %s" % luma) in b14, "③ 워터마크 문턱값이 코드와 같다", "code=%s" % luma)
chk(conf is not None and ("MIN_CONF = %s" % conf) in body(TXT_SOT),
    "③ 낱말 신뢰도 문턱값이 코드와 같다", "code=%s" % conf)
chk("300 dpi" in b14 and "dpi: int = 300" in OCR_PY, "③ 렌더 해상도가 코드와 같다")

# ── ④ 언어 목록은 available_langs() 로만 (§14.19 ②) ───────────────────
print(NL + "=== ④ 언어 목록을 세는 길이 하나다 (§14.19 ②) ===")
bad_call = []
for p in sorted(HERE.glob("viewer/**/*.py")):
    if p.name == "ocr.py":
        continue                      # 합집합을 만드는 당사자
    if "get_languages(" in read(p):
        bad_call.append(p.name)
chk(not bad_call, "④ `get_languages()` 를 직접 부르는 곳이 없다", str(bad_call))
chk("def available_langs" in OCR_PY, "④ `available_langs()` 가 있다")
chk("glob(\"*.traineddata\")" in OCR_PY or "*.traineddata" in OCR_PY,
    "④ 폴더의 실제 파일도 함께 센다")

# ── ⑤ §14 색인이 빠짐없는가 (§14.A) ───────────────────────────────────
print(NL + "=== ⑤ §14 색인이 모든 절을 덮는다 (§14.A) ===")
raw = SOTS[OCR_SOT]
heads = re.findall(r"^### (14\.[0-9]+)[ .]", raw, re.M)
i = raw.index("### 14.A")
j = raw.index("### 14.0")
index_txt = raw[i:j]
missing = [h for h in heads if ("§" + h) not in index_txt]
# 색인 표는 규칙 절만 낱낱이 적는다 — P0 실측(§14.0~§14.5)은 묶음으로 가리킨다
missing = [h for h in missing
           if not re.match(r"14\.[0-5]$", h)]
chk(not missing, "⑤ 규칙 절이 모두 §14.A·§14.B 에 적혀 있다", str(missing))
chk("§14.0~§14.5" in index_txt, "⑤ P0 실측 묶음도 색인에 있다")

# ── ⑥ 이력 절은 '지금 규칙' 을 참칭하지 않는다 ────────────────────────
print(NL + "=== ⑥ kor 사건 4건은 이력이고, 규칙은 §14.19 하나 ===")
for sec in ("14.13", "14.15", "14.16", "14.17"):
    m = re.search(r"^### " + sec.replace(".", r"\.") + r"[ .].*?(?=^### )", raw, re.M | re.S)
    seg = m.group(0) if m else ""
    chk("§14.19" in seg, "⑥ §%s 가 §14.19 를 가리킨다" % sec)

# ── ⑦ §14.18 표가 코드와 같은가 (260912-3) ────────────────────────────
print(NL + "=== ⑦ 스캔 감지 표가 코드와 어긋나지 않는다 (§14.18) ===")
# 1번 규칙에 '보이는 층' 조건을 넣었는데 표만 옛 문장으로 남으면, 다음 사람이
#   표를 믿고 코드를 '고쳐' 되돌린다 — 실제로 이 표가 하루 동안 그렇게 어긋나 있었다.
sec18 = re.search(r"^### 14\.18[ .].*?(?=^### |^## )", b14, re.M | re.S)
seg18 = sec18.group(0) if sec18 else ""
r18 = re.search(r"^\| 1 \|.*$", seg18, re.M)
row1 = r18.group(0) if r18 else ""
chk("안 보이는 층" in row1 or "_is_ocr_layer" in row1,
    "⑦ 1번 규칙에 '안 보이는 층' 조건이 적혀 있다", row1[:90])
chk("_overlaid_ocr_layer" in OCR_PY and "_is_ocr_layer" in OCR_PY,
    "⑦ 코드도 그 조건을 쓴다")
chk(re.search(r"cov >= 0\.6 and _overlaid_ocr_layer\(page\)", OCR_PY) is not None,
    "⑦ 두 조건을 **모두** 본다")
chk("§14.18.1" in b14, "⑦ 그 까닭(§14.18.1)이 문서에 있다")

# ── ⑧ 빈칸 손보기 문턱은 텍스트 창이 소유한다 ─────────────────────────
print(NL + "=== ⑧ 빈칸 손보기 값의 단일 소유 (§3.6.10) ===")
TX_PY = code("viewer/text_extract2.py")
for nm in ("SPACE_GAP", "SPACE_COVERED"):
    pat = r"%s\s*=\s*[0-9.]+" % nm
    where = [d for d in SOTS if re.search(pat, body(d))]
    chk(where in ([TXT_SOT], []), "⑧ `%s` 값은 텍스트 창 SOT 밖에 적히지 않는다" % nm, str(where))
    chk(re.search(r"^%s\s*=" % nm, TX_PY, re.M) is not None, "⑧ `%s` 가 코드에 있다" % nm)
chk("_SPACE_LIKE" in TX_PY and "\\u00a0" in TX_PY.replace("\u00a0", "\\u00a0"),
    "⑧ `_SPACE_LIKE` 가 코드에 있다")
chk("SPACE_COVERED" in body(OCR_SOT) and "텍스트 창" in body(OCR_SOT),
    "⑧ OCR SOT 는 값을 적지 않고 가리키기만 한다")

print(NL + ("=== ALL PASS ===" if not fails else "=== FAILURE (%d) ===" % len(fails)))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
