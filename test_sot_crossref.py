# -*- coding: utf-8 -*-
"""261012-13(CLAUDE.md §4 의 7): SOT 전체 점검에서 **되풀이해 나온 어긋남**을 기계가 먼저 잡는다.

SOT 를 고친 뒤 전체 대조 점검(세 묶음)을 할 때마다 같은 종류가 수십 건씩 나왔다 — 없는 절을 가리키는 참조,
같은 번호의 절 둘, 코드에 없는 이름, 코드와 다른 상수 값, 낡은 '여섯 가지' 같은 개수, 빈 줄로 끊긴 표,
모듈 §0 에만 있고 마스터 §0 에 없는 작업 번호 등. 사람이 읽기 전에 이 검사가 먼저 걸러 낸다.

A. 절 참조 — 코드·SOT 의 '(이름) SOT §N'·'마스터 §N'·문서 안 맨 §N 이 실제 머리말로 있다
B. 절 번호 — 한 문서 안에 같은 번호가 둘 없고, 하위 절이 제 부모 아래 있다
C. 마스터 §14.5 U 번호가 하나씩만 정의되고, 가리키는 U 가 있다
D. 표·글 모양 — 머리 구분선 없이 시작하는 표, 파이썬 이어붙이기 조각(`" + `)이 없다
E. 낡는 숫자 — 'N 가지 의무', '`test_x_` N개' 를 쓰지 않는다
F. 이름 — SOT 본문(§0 밖)의 백틱 식별자가 코드에 있다 · CLAUDE.md 가 대는 SOT 파일이 있다
G. 값 — SOT 의 `상수 = 값`·`값(상수)` 이 코드와 같다 · 비밀 키 표 = SECRET_PREF_KEYS · signing.json 예시 키 · i18n 명령
H. 짝 — 최근 모듈 §0 행의 작업 번호가 마스터 §0 에도 있다 · QThread 직접 상속은 응답성 SOT §4.4 에 등재
I. 없어진·바뀐 화면 이름 — 패널 툴바 이름, 그리고 `RENAMED` 표의 옛 이름이 SOT 본문·검사 기대·화면 문구·도움말에 남지 않는다

SOT 문서는 공개 저장소 밖(부모 폴더)에 있다 — 없으면(CI) 건너뛴다.
"""
import os, re, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # Qt 는 쓰지 않는다 — §14.7 규약 검사용
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
# 261025-9: 새 검사가 '수정 전 문서로 실패하는지' 볼 때 옛 SOT 를 따로 꺼내 둔 폴더를 가리킨다(평소에는 비워 둔다)
SOT_DIR = Path(os.environ.get("POLYPDF_SOT_DIR") or ROOT.parent)
NL = "\n"
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def read(p):
    try:
        return Path(p).read_text(encoding="utf-8")
    except Exception:
        return ""


MASTER = "PolyPDF 뷰어 통합 작업 계획서.md"
SOTS = {p.name: read(p) for p in sorted(SOT_DIR.glob("*.md"))}
if MASTER not in SOTS:
    print("SKIP — SOT 문서가 없다(공개 저장소 단독)")
    sys.stdout.flush(); os._exit(0)
LIVE = {n: t for n, t in SOTS.items() if "아카이브" not in n}          # 지금 사양 — 아카이브는 이력
CODE_FILES = [p for p in list((ROOT / "viewer").rglob("*.py")) + list((ROOT / "scripts").glob("*.py"))
              + list(ROOT.glob("*.py")) if "__pycache__" not in p.parts]
CODE = {p: read(p) for p in CODE_FILES}
CODE_ALL = NL.join(CODE.values()) + read(ROOT / "build_ci.bat") + NL.join(
    read(p) for p in list((ROOT / ".github" / "workflows").glob("*.yml")) + list((ROOT / "installer").glob("*"))
    + list((ROOT / "scripts").glob("*.ps1")) if p.is_file())

# 문서 이름 → 파일. 긴 이름을 먼저 본다('단어학습' 이 '단어장' 보다, '화면 디자인' 이 '디자인' 보다)
ALIAS = [
    ("단어학습", "단어학습(OCR·어휘) 기능 작업계획서.md"), ("단어장", "단어장 작업 계획서.md"),
    ("텍스트 창", "텍스트 창 작업 계획서.md"), ("응답성", "응답성 작업 계획서.md"),
    ("검색창", "검색창 작업 계획서.md"), ("검색", "검색창 작업 계획서.md"),
    ("입력 장치", "입력 장치 작업 계획서.md"), ("입력", "입력 장치 작업 계획서.md"),
    ("스크린샷", "스크린샷 작업 계획서.md"), ("태그", "파일 태그·키워드 작업 계획서.md"),
    ("법령·고시", "법령·고시 작업 계획서.md"), ("법령", "법령·고시 작업 계획서.md"),
    ("영상·음성", "영상 및 음성 작업 계획서.md"), ("영상 및 음성", "영상 및 음성 작업 계획서.md"),
    ("번역·요약", "PDF 번역·요약 작업 계획서.md"), ("번역", "PDF 번역·요약 작업 계획서.md"),
    ("이미지→PDF", "이미지 PDF 변환 작업 계획서.md"), ("이미지 PDF", "이미지 PDF 변환 작업 계획서.md"),
    ("발표", "발표(전체화면) 작업 계획서.md"), ("화면 디자인", "화면 디자인 작업 계획서.md"),
    ("디자인", "화면 디자인 작업 계획서.md"), ("다국어", "다국어(언어팩) 작업 계획서.md"),
    ("릴리스", "릴리스 작업 계획서.md"), ("문서 보안", "문서 보안(암호·전자서명) 작업 계획서.md"),
    ("보안", "문서 보안(암호·전자서명) 작업 계획서.md"), ("마스터", MASTER), ("뷰어 명세", MASTER),
    # 261014-29: 개선 로드맵은 백업/ 으로 보관 — 본문에서 그 문서의 절(§)을 가리키지 않는다(항목 번호 P1-1 … 은 출처 표시로만)
    ("형식 변환", "형식 변환 작업 계획서.md"),          # 261014-10 신설
    ("가상 프린터", "가상 프린터 작업 계획서.md"),      # 261017 신설
    ("사진 보기", "사진 보기(PolyPix) 작업 계획서.md"),   # 261103-17 신설
    ("책갈피창·저장", "책갈피창·저장 작업 계획서.md"),   # 261108-1 신설(마스터 §4.7~§4.9)
    ("검사 작성", "검사 작성 작업 계획서.md"),          # 261108-1 신설(마스터 §14.6~§14.7.4)
    ("작업 절차", "작업 절차 계획서.md"),              # 261108-2 신설(CLAUDE.md §1.6·§4·§5 를 옮김)
    ("향후 추진", "향후 추진 계획서.md"),              # 261108-6: 모든 SOT 의 백로그·남은 후보가 여기로(옛 자리는 '→ 향후 추진 계획서 §N')
    ("CLAUDE.md", "CLAUDE.md"),
]
ALIAS_RE = "|".join(re.escape(a) for a, _ in sorted(ALIAS, key=lambda x: -len(x[0])))
ALIAS_MAP = dict(ALIAS)
FOREIGN = ("분할기", "SplitPDF", "PDF 책갈피 분할")       # 다른 저장소의 문서


def headings(txt):
    """[(줄 번호, 깊이, 번호)] — `## 4.7.15 …`, `### **U9**` 는 번호만."""
    out, fence = [], False
    for i, l in enumerate(txt.splitlines(), 1):
        if l.startswith("```"):
            fence = not fence
        if fence:
            continue
        m = re.match(r"^(#{2,5})\s+§?(\d+(?:\.(?:\d+[a-z]?|[A-Z]))*)[.\s]", l + " ")
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


HEADS = {n: {h[2] for h in headings(t)} for n, t in SOTS.items()}


def has_sec(doc, num, moved=True):
    nums = HEADS.get(doc, set())
    if moved:
        tgt = moved_to(doc, num)
        if tgt:
            doc, nums = tgt, HEADS.get(tgt, set())
    if num in nums:
        return True
    # §14.5 처럼 위 절만 가리키는 것은 그 아래 절이 있으면 된다. §4 처럼 장 번호면 장이 있으면 된다
    return any(h.startswith(num + ".") for h in nums)


# 261108-1: 마스터에서 옮긴 절 — **번호 그대로** 새 문서에 있고, 마스터 옛 자리에는 이정표(`### 4.7 … → 책갈피창·저장 SOT §4.7`)만 남는다.
#   다른 문서·코드 주석의 '마스터 §4.7.5' 는 새 문서의 같은 절로 찾는다. 마스터 자신의 맨 `§4.7.5` 는 대응하지 않는다(문서 이름을 붙여 쓴다 — A2).
MOVED = {MASTER: [("4.7", "책갈피창·저장 작업 계획서.md"), ("4.8", "책갈피창·저장 작업 계획서.md"), ("4.9", "책갈피창·저장 작업 계획서.md"),
                  ("14.0", "릴리스 작업 계획서.md"), ("14.1", "릴리스 작업 계획서.md"), ("14.2", "릴리스 작업 계획서.md"),
                  ("14.3", "릴리스 작업 계획서.md"), ("14.4", "릴리스 작업 계획서.md"), ("14.5", "릴리스 작업 계획서.md"),
                  ("14.6", "검사 작성 작업 계획서.md"), ("14.7", "검사 작성 작업 계획서.md")]}


def moved_to(doc, num):
    for pfx, tgt in MOVED.get(doc, ()):
        if num == pfx or num.startswith(pfx + "."):
            return tgt
    return None


def body(txt):
    """§0 변경 이력 표를 뺀 본문 — 이력 행은 그때의 참조라 지금 절과 다를 수 있다."""
    return re.sub(r"^## 0\..*?(?=^## [1-9])", "", txt, flags=re.S | re.M)


SEC = r"§\s?(\d+(?:\.\d+)*)"
ARCHIVE_OF = {MASTER: ("뷰어 변경상세 아카이브.md",),
              "단어학습(OCR·어휘) 기능 작업계획서.md": ("단어학습 변경상세 아카이브.md",),
              "단어장 작업 계획서.md": ("단어학습 변경상세 아카이브.md",),
              "사진 보기(PolyPix) 작업 계획서.md": ("사진 보기 변경상세 아카이브.md",),   # 261104-16: 끝난 계획·기록(장 번호 유지)
              "텍스트 창 작업 계획서.md": ("텍스트 창 변경상세 아카이브.md",)}   # 261108-3: 그때의 보고·분석·실측(장 번호 유지)

# ── A. 절 참조 ─────────────────────────────────────────────────────────
print("=== A. 절 참조가 실제 머리말로 있다 ===")
bad = []
pat_code = re.compile(r"(" + ALIAS_RE + r")\s*(?:SOT|작업 계획서)?\s*" + SEC)
for p, src in CODE.items():
    for l in src.splitlines():
        if "SOT" not in l and "마스터" not in l:
            continue
        for m in pat_code.finditer(l):
            al, num = m.group(1), m.group(2).rstrip(".")
            if al not in ("마스터", "뷰어 명세") and "SOT" not in l[m.start():m.end() + 1]:
                continue                       # '검색 §4' 같은 일반 글은 SOT 를 붙여 쓴 것만 본다
            if any(f in l for f in FOREIGN):
                continue
            doc = ALIAS_MAP[al]
            # 261104-16: 아카이브로 옮긴 장은 번호를 그대로 둔다(장 번호 유지) — 코드 주석의 옛 장 번호는 그 문서의 아카이브에서 찾는다
            if not has_sec(doc, num) and not any(has_sec(a, num) for a in ARCHIVE_OF.get(doc, ())):
                bad.append("%s: %s §%s" % (p.name, al, num))
chk(not bad, "A1 코드 주석이 가리키는 SOT 절이 있다(옮긴 장은 그 아카이브에서)", str(sorted(set(bad))[:12]))

bad = []
near = re.compile(r"(" + ALIAS_RE + r")(?:\s*SOT|\s*작업 계획서(?:\.md)?|`?\]\([^)]*\))?\s*(?:의\s*)?$")
for name, txt in LIVE.items():
    if name == "CLAUDE.md":
        continue                                  # 길잡이 문서 — '그 문서 §N' 으로 앞 링크를 가리킨다
    fence, prev = False, ""
    for l in body(txt).splitlines():
        if l.startswith("```"):
            fence = not fence
        if fence or any(f in l for f in FOREIGN):
            prev = l
            continue
        before, prev = prev, l
        chain = None                                  # (앞 § 의 끝, 그 문서) — '검색 SOT §5.1·§5.2' 의 둘째 § 는 같은 문서다
        for m in re.finditer(SEC, l):
            num = m.group(1).rstrip(".")
            if num == "0":
                chain = None
                continue                              # §0 은 이력 표 — 마스터에 맡긴 문서는 없다
            # 261105-19: 이어 쓴 § 는 앞 § 의 문서에서만 찾는다 — 종전엔 줄의 다른 문서에서도 찾아 태그 SOT 의 검색 쪽 없는 절 참조가 지나갔다
            if chain and re.fullmatch(r"\s*[·/]\s*", l[chain[0]:m.start()]):
                cdoc = chain[1]
                chain = (m.end(), cdoc)
                if cdoc in SOTS and not has_sec(cdoc, num, moved=(cdoc != name)) and not any(has_sec(a, num) for a in ARCHIVE_OF.get(cdoc, ())) \
                        and not re.search(r"없다|없는|어디에도|존재하지", l):
                    bad.append("%s → %s §%s(이어 쓴 §: …%s)" % (name[:8], cdoc[:8], num, l[max(0, m.start() - 30):m.end()]))
                continue
            pre = l[max(0, m.start() - 40):m.start()]
            pre = re.split(r"[(（),;:.—]", pre)[-1]                # 괄호·쉼표·마침표 앞의 다른 문서 이름은 보지 않는다
            mm = None
            for mm in re.finditer(ALIAS_RE, pre):
                pass
            if mm is not None and re.match(r"^(?:\s*SOT|\s*작업 계획서|`?\]|`?\s*§|\s*의\s)", pre[mm.end():] + " ") \
                    and len(pre) - mm.end() <= 24:
                doc = ALIAS_MAP[mm.group(0)]
            else:
                doc = name
            tail = l[:m.start()]                      # 이어 쓸 문서 — § 바로 앞의 이름(`마스터 §7`·`검색창 계획서 §6`·`… 작업 계획서.md` §6)
            mt = re.search(r"(" + ALIAS_RE + r")\s*(?:SOT|작업 ?계획서|계획서)?\s*$", tail)
            mf = re.search(r"`([^`]+\.md)`\s*$", tail)
            chain = (m.end(), mf.group(1) if mf and mf.group(1) in SOTS else ALIAS_MAP[mt.group(1)] if mt else doc)
            if doc not in SOTS:
                continue
            if has_sec(doc, num, moved=(doc != name)):
                continue
            # 못 찾으면 — 같은 줄 앞쪽에 나온 다른 문서 이름(목록 '입력 SOT §2.2 · §2.3' 처럼 이어 쓴 것),
            #   또는 이 문서의 아카이브(번호를 그대로 둔 옛 장)에서 찾는다
            alts = [ALIAS_MAP[x] for x in re.findall(ALIAS_RE, before + " " + l[:m.start()])][::-1]   # 앞 줄에서 이어진 인용도 — 가까운 이름부터
            alts += [name] + [a for a in ARCHIVE_OF.get(name, ())]
            alts += [a for d in [doc] + alts for a in ARCHIVE_OF.get(d, ())]   # 261108-1: '마스터 §19.1' 처럼 가리킨 문서의 아카이브(번호 유지)도
            hit = [d for d in alts if has_sec(d, num, moved=(d != name))]
            if hit:
                chain = (m.end(), hit[0])
                continue
            if re.search(r"없다|없는|어디에도|존재하지", l):
                continue
            bad.append("%s → %s §%s" % (name[:8], doc[:8], num))
chk(not bad, "A2 SOT 본문(§0 밖)의 절 참조가 그 문서에 있다", "%d건 %s" % (len(set(bad)), sorted(set(bad))[:999 if "-v" in sys.argv else 15]))

# 261108-1: 옮긴 절의 대응이 살아 있다 — 마스터 옛 자리에 이정표(`→ ○○ SOT §x`), 새 문서에 같은 번호. 한쪽만 고치면 대응이 끊긴다.
bad = []
for src, pairs in MOVED.items():
    for pfx, tgt in pairs:
        if not has_sec(tgt, pfx, moved=False):
            bad.append("%s 에 §%s 가 없다" % (tgt[:8], pfx))
        stub = [l for l in SOTS[src].splitlines() if re.match(r"^#{3,4} %s " % re.escape(pfx), l)]
        if not stub or ("→ %s §%s" % (next(a for a, d in ALIAS if d == tgt), pfx)) not in stub[0] and ("SOT §%s" % pfx) not in stub[0]:
            bad.append("마스터 §%s 이정표 없음" % pfx)
        under = [h for ln, _d, h in headings(SOTS[src]) if h.startswith(pfx + ".")
                 and "SOT §" + h not in SOTS[src].splitlines()[ln - 1]]          # 아래 절도 이정표면 된다(§14.2.1)
        if under:
            bad.append("마스터에 §%s 아래 절이 남음 %s" % (pfx, sorted(under)[:3]))
chk(not bad, "A3 마스터에서 옮긴 절 — 옛 자리는 이정표 하나, 새 문서에 같은 번호", str(bad[:8]))

# ── B. 절 번호 ─────────────────────────────────────────────────────────
print(NL + "=== B. 절 번호 — 겹치지 않고 제 부모 아래 ===")
dup, orphan = [], []
for name, txt in LIVE.items():
    if name == "CLAUDE.md":
        continue
    hs = headings(txt)
    seen = {}
    for ln, d, num in hs:
        seen.setdefault(num, []).append(ln)
    dup += ["%s §%s" % (name[:8], k) for k, v in seen.items() if len(v) > 1]
    stack = []                                    # (깊이, 번호)
    for ln, d, num in hs:
        while stack and stack[-1][0] >= d:
            stack.pop()
        if stack and "." in num:
            parent = stack[-1][1]
            if not (num.startswith(parent + ".")) and num.rsplit(".", 1)[0] != parent:
                orphan.append("%s §%s(부모 §%s)" % (name[:8], num, parent))
        stack.append((d, num))
chk(not dup, "B1 한 문서 안에 같은 절 번호가 둘 없다", str(dup[:10]))
chk(not orphan, "B2 하위 절이 제 부모 절 아래에 있다", str(orphan[:10]))

# ── C. U 번호 ──────────────────────────────────────────────────────────
print(NL + "=== C. §14.5 U 번호(릴리스 SOT — 261108-1 에 마스터에서 옮김) ===")
mst = SOTS[MASTER]
rel = SOTS.get("릴리스 작업 계획서.md", "")
udefs = re.findall(r"^\|\s*(U\d+)\s*\|", rel, re.M) + re.findall(r"^>\s*\*\*★\s*(U\d+)\s*—", rel, re.M)
chk(not re.findall(r"^\|\s*(U\d+)\s*\|", mst, re.M), "C0 U 번호는 마스터가 아니라 릴리스 SOT §14.5 에 정의한다")
dups = sorted({u for u in udefs if udefs.count(u) > 1})
chk(not dups, "C1 U 번호가 하나씩만 정의된다", str(dups))
refs = set()
for t in list(SOTS.values()) + list(CODE.values()):
    refs |= set(re.findall(r"§14\.5\s*(U\d+)", t))
missing = sorted(refs - set(udefs), key=lambda u: int(u[1:]))
chk(not missing, "C2 '§14.5 U번호' 참조가 정의돼 있다", str(missing))

# ── D. 표·글 모양 ──────────────────────────────────────────────────────
print(NL + "=== D. 표·글 모양 ===")
broken, frag = [], []
for name, txt in SOTS.items():
    lines = txt.splitlines()
    fence = False
    for i, l in enumerate(lines):
        if l.startswith("```"):
            fence = not fence
        if fence:
            continue
        s = l.lstrip("> ").strip()
        prev = lines[i - 1].lstrip("> ").strip() if i else ""
        if s.startswith("|") and not prev.startswith("|"):
            nxt = lines[i + 1].lstrip("> ").strip() if i + 1 < len(lines) else ""
            if not re.match(r"^\|\s*:?-+\s*:?\|", nxt):
                broken.append("%s:%d" % (name[:8], i + 1))
        if any('" + ' in c or ' + "' in c for c in re.findall(r"`[^`]*`", l)):      # 코드 표기 안의 이어붙이기
            frag.append("%s:%d" % (name[:8], i + 1))
chk(not broken, "D1 표가 머리 구분선(| --- |) 없이 시작하지 않는다(빈 줄로 끊긴 표)", str(broken[:8]))

# 261025-9(SOT 점검): 인용문(`> | …`) 안의 표에 `> ` 없는 행이 끼면 표가 거기서 끊긴다 — 마스터 문서 지도에서 두 행이 그랬다.
#   D1 은 `> ` 를 벗기고 보므로 이것을 못 잡는다.
mixed = []
for name, txt in SOTS.items():
    lines = txt.splitlines()
    fence = False
    for i in range(1, len(lines)):
        if lines[i].startswith("```"):
            fence = not fence
        if fence:
            continue
        a, b = lines[i - 1].strip(), lines[i].strip()
        qa, qb = re.match(r"^>\s*\|", a), re.match(r"^>\s*\|", b)
        if (qa and b.startswith("|")) or (qb and a.startswith("|")):
            mixed.append("%s:%d" % (name[:8], i + 1))
chk(not mixed, "D3 인용문 안 표의 행이 모두 `> ` 로 시작한다(섞이면 표가 끊긴다)", str(mixed[:8]))
chk(not frag, "D2 SOT 에 파이썬 이어붙이기 조각(\" + …)이 없다", str(frag[:8]))

# ── E. 낡는 숫자 ───────────────────────────────────────────────────────
print(NL + "=== E. 낡는 숫자 ===")
dut = []
for name, txt in LIVE.items():
    dut += ["%s: %s" % (name[:8], m) for m in re.findall(r"(?:[0-9]+|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*가지 의무", body(txt))
            if not (name.startswith("응답성") and "의무" in m)]
dut += ["%s: %s" % (p.name, m) for p, s in CODE.items()
        for m in re.findall(r"(?:[0-9]+|여섯|일곱)\s*가지 의무", s)]
chk(not dut, "E1 응답성 §4 의무의 개수를 적지 않는다('§4 의무' 로 가리킨다)", str(dut[:6]))
cnt = []
for name, txt in LIVE.items():
    cnt += ["%s: %s" % (name[:8], m) for m in re.findall(r"`test_[a-z0-9_]+`\s*\*{0,2}\d+\s*개", body(txt))]
chk(not cnt, "E2 '`test_x_` N개' 처럼 검사 파일 수를 적지 않는다", str(cnt[:6]))

# 날짜 붙은 장(`## 17. P2 … 구현 결과 (2026-06-03)`)은 구현 기록이 장으로 남은 것이다 — 지금 수보다 늘지 않게(줄이면 이 수도 줄인다).
#   (261012-17: 단어학습 §15~§22 는 규칙을 §15 로 올리고 아카이브로 옮겼다.) 법령·발표·태그의 1장은 사양 장에 착수일이 붙은 것.
DATED_MAX = {"발표(전체화면) 작업 계획서.md": 1,
             "법령·고시 작업 계획서.md": 1, "파일 태그·키워드 작업 계획서.md": 1}
over = []
for name, txt in LIVE.items():
    if name == "CLAUDE.md":
        continue
    c = len(re.findall(r"^## \d+\. .*\(20\d\d-\d\d-\d\d\)\s*$", txt, re.M))
    if c > DATED_MAX.get(name, 0):
        over.append("%s %d>%d" % (name[:10], c, DATED_MAX.get(name, 0)))
chk(not over, "E3 날짜 붙은 구현 기록 장이 늘지 않는다(새 기록은 §0·아카이브로)", str(over))

# ── F. 이름 ────────────────────────────────────────────────────────────
print(NL + "=== F. 이름이 코드·디스크에 있다 ===")
SKIP_LINE = re.compile(r"폐기|예정|미구현|없다|없앴|종전|옛 |옛\)|후보|제안|삭제|제거|바꿨|이었다|했다|대신|이름을 바|→|vs|아니라|금지|하지 않")
WORDS = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", CODE_ALL)) | {p.stem for p in ROOT.glob("*.py")}
NOTCODE = set("""PolyPDF PyQt6 PyMuPDF PyInstaller QtMultimedia QThread QTimer QWidget QDialog QMenu QLabel QPushButton
QTreeWidget QListWidget QTreeWidgetItem QDataStream QMimeData QShortcut QElapsedTimer QStandardPaths QGraphicsView
QMessageBox QApplication QPixmap QImage QColor QPainter QLineEdit QTextEdit QComboBox QCheckBox QSpinBox QScrollArea
FreeText GoToR GitHub Windows Acrobat Adobe JavaScript SQLite TrueType OpenType HarfBuzz DirectWrite WinRT FFmpeg
MuPDF pdfium NotoSans Malgun PowerShell WebView README DEPLOY TODO FIXME
IsSupportedAsync SpeechSynthesis layoutDirection en_core_web_sm kmCert kmPri get_svg_image _current_frames""".split())
# ★ 코드에 없어도 되는 이름(외부 라이브러리·OS API·파일 이름)은 위에 더한다 — 이유가 분명한 것만.
import builtins as _bi
NOTCODE |= set(dir(_bi))
unknown = {}
for name, txt in LIVE.items():
    if name == "CLAUDE.md":
        continue
    plan = False
    for l in body(txt).splitlines():
        if l.startswith("## "):                   # 확장 안내·백로그·로드맵은 아직 없는 이름을 적는 곳이다
            plan = bool(re.search(r"확장|백로그|Backlog|향후|로드맵|제안", l))
        if plan or SKIP_LINE.search(l):
            continue
        for tok in re.findall(r"`([A-Za-z_][A-Za-z0-9_.]*)(?:\(\))?`", l):
            last = tok.split(".")[-1]
            if len(last) < 5 or last in NOTCODE or last.isupper() and "_" not in last:
                continue
            if last.startswith("_") and last.endswith("_") or last.endswith("_") or len(last) > 32 \
                    or re.match(r"^Q[A-Z]", last) or (last.isupper() and last.startswith("SLICE")):
                continue                              # 접두·접미 표기(`test_x_`·`_debug`), Qt 클래스, 긴 파일 이름
            if not ("_" in last or re.search(r"[a-z][A-Z]", last)):
                continue
            if last.startswith("test_") and any(p.stem.startswith(last) for p in ROOT.glob("test_*.py")):
                continue                              # 소유 표의 접두(`test_pres`)
            if last not in WORDS:
                unknown.setdefault(name[:10], set()).add(last)
n_unknown = sum(len(v) for v in unknown.values())
chk(n_unknown == 0, "F1 SOT 본문(§0 밖)의 백틱 식별자가 코드에 있다(옛 이름은 '종전·폐기' 와 함께 적는다)",
    "%d개 %s" % (n_unknown, {k: sorted(v)[:8] for k, v in unknown.items()}))
claude = SOTS.get("CLAUDE.md", "")
named = {x for x in re.findall(r"`([^`/\\]+(?:작업 ?계획서|아카이브)\.md)`", claude) if "*" not in x}   # `*작업 계획서.md` 는 무시 규칙
gone = sorted(n for n in named if n not in SOTS)
chk(not gone, "F2 CLAUDE.md 가 대는 SOT 파일 이름이 실제로 있다", str(gone))
# 261105-19: 파일 꼴(`test_photo_*.py`)도 맞는 파일이 하나는 있어야 한다 — 사진 SOT 가 없는 꼴 `test_picture_*.py` 를 가리켰다
nomatch = set()
for name, txt in LIVE.items():
    for l in body(txt).splitlines():
        if SKIP_LINE.search(l):
            continue
        for pat in re.findall(r"`((?:[\w.-]+/)*[\w.-]*\*[\w.*-]*\.py)`", l):
            if not any(ROOT.glob(pat)) and not any(ROOT.glob("**/" + pat)):
                nomatch.add("%s: %s" % (name[:10], pat))
chk(not nomatch, "F3 SOT 본문이 대는 파일 꼴(`test_x_*.py`)에 맞는 파일이 있다", str(sorted(nomatch)))

# ── G. 값 ──────────────────────────────────────────────────────────────
print(NL + "=== G. SOT 의 값이 코드와 같다 ===")
consts = {}
for p, src in CODE.items():
    for m in re.finditer(r"^\s*([A-Z][A-Z0-9_]{2,})\s*(?::\s*\w+\s*)?=\s*(-?[0-9][0-9_]*(?:\.[0-9]+)?)\s*(?:#|$)", src, re.M):
        consts.setdefault(m.group(1), set()).add(float(m.group(2).replace("_", "")))
mism = []
for name, txt in LIVE.items():
    b = body(txt)
    pairs = [(m.group(1), m.group(2), "") for m in re.finditer(r"`([A-Z][A-Z0-9_]{2,})\s*=\s*(-?[0-9.]+)`", b)]
    pairs += [(m.group(3), m.group(1), m.group(2) or "") for m in re.finditer(
        r"(-?[0-9]+(?:\.[0-9]+)?)\s*(초|ms|px|%)?\s*\(\s*`([A-Z][A-Z0-9_]{2,})`\s*\)", b)]
    for cname, val, unit in pairs:
        if cname not in consts:
            continue
        try:
            v = float(val.rstrip("."))
        except ValueError:
            continue
        if unit == "초" and cname.endswith("_MS"):
            v *= 1000
        cand = [v] + ([v / 100, 1 - v / 100] if unit == "%" else [])   # 아래 12% = 0.88 처럼 쓴다
        if not any(abs(x - c) < 1e-9 for x in cand for c in consts[cname]):
            mism.append("%s: %s=%s%s (코드 %s)" % (name[:8], cname, val, unit, sorted(consts[cname])))
chk(not mism, "G1 SOT 의 `상수 = 값`·`값(상수)` 이 코드와 같다", str(mism[:8]))

# 261014-9: 코드 블록(```) 안의 `상수 = 값` 도 — 마스터 §7.5 의 `CURRENT_SCHEMA = 9` 가 코드 11 과 어긋난 채 남아 있었다
mism2 = []
for name, txt in LIVE.items():
    for blk in re.findall(r"```[a-z]*\n(.*?)```", body(txt), re.S):
        for m in re.finditer(r"^\s*([A-Z][A-Z0-9_]{2,})\s*=\s*(-?[0-9][0-9_]*(?:\.[0-9]+)?)\s*(?:#|$)", blk, re.M):
            cname, val = m.group(1), float(m.group(2).replace("_", ""))
            if cname in consts and not any(abs(val - c) < 1e-9 for c in consts[cname]):
                mism2.append("%s: %s=%s (코드 %s)" % (name[:8], cname, m.group(2), sorted(consts[cname])))
chk(not mism2, "G1b SOT 코드 블록의 `상수 = 값` 이 코드와 같다", str(mism2[:8]))

ss = read(ROOT / "viewer" / "settings_store.py")
m = re.search(r"SECRET_PREF_KEYS\s*=\s*\{([^}]*)\}", ss)
code_keys = set(re.findall(r'"([a-z_]+)"', m.group(1))) if m else set()
row = next((l for l in mst.splitlines() if "anthropic_api_key" in l and l.startswith("|")), "")
doc_keys = set(re.findall(r"`(?:preferences\.)?([a-z_]+_(?:key|oc|signkey))`", row.split("|")[1] if row else ""))
chk(bool(code_keys) and doc_keys == code_keys, "G2 마스터 §8.2.0 비밀 값 표 = SECRET_PREF_KEYS",
    "문서만 %s / 코드만 %s" % (sorted(doc_keys - code_keys), sorted(code_keys - doc_keys)))

sec = SOTS.get("문서 보안(암호·전자서명) 작업 계획서.md", "")
st = read(ROOT / "viewer" / "sign_store.py")
me = re.search(r"def _empty\(\)(.*?)\n(?:def |class )", st, re.S)
ek = set(re.findall(r'"([a-z_]+)"\s*:', me.group(1))) if me else set()
s9 = sec[sec.find("## 9."):sec.find("## 10.")] if "## 9." in sec else ""
miss = sorted(k for k in ek if '"%s"' % k not in s9)
chk(bool(ek) and not miss, "G3 보안 SOT §9 signing.json 예시에 저장소 키가 모두 있다", str(miss))

i18n = read(ROOT / "scripts" / "i18n.py")
cmds = set(re.findall(r'cmd\s*==\s*"([a-z-]+)"', i18n))
lang = SOTS.get("다국어(언어팩) 작업 계획서.md", "")
miss = sorted(c for c in cmds if "`%s" % c not in lang and " %s`" % c not in lang and "i18n.py %s" % c not in lang)
chk(bool(cmds) and not miss, "G4 scripts/i18n.py 명령이 다국어 SOT 에 모두 있다", str(miss))

# ── H. 짝 ──────────────────────────────────────────────────────────────
print(NL + "=== H. 짝 ===")
m0 = mst[mst.find("## 0."):mst.find("## 1.")]
lost = []
for name, txt in LIVE.items():
    if name in (MASTER, "CLAUDE.md"):
        continue
    s0 = txt[txt.find("## 0"):]
    s0 = s0[:s0.find("\n## 1")] if "\n## 1" in s0 else s0
    for l in s0.splitlines():
        mm = re.match(r"^\|\s*(2026-(\d\d)-(\d\d))\s*\|\s*([^|]+)\|", l)
        if not mm or mm.group(4).strip() in ("—", "-") or (int(mm.group(2)), int(mm.group(3))) < (10, 12):
            continue
        for wid in re.findall(r"\b(\d{6}-\d+)", l.split("|")[3]):
            if wid not in m0:
                lost.append("%s %s" % (name[:8], wid))
chk(not lost, "H1 모듈 §0 의 작업 번호(2026-10-12 부터)가 마스터 §0 에도 있다", str(lost[:10]))

resp = SOTS.get("응답성 작업 계획서.md", "")
qt = sorted({m for p, s in CODE.items() if "viewer" in p.parts
             for m in re.findall(r"^class\s+(\w+)\(QThread\)", s, re.M)})
unreg = [c for c in qt if c not in resp]
chk(not unreg, "H2 QThread 를 직접 상속한 스레드가 응답성 SOT §4.4 에 등재돼 있다", str(unreg))
# 응답성 §4.3: 직접 상속은 **신규 금지** — 잔존 허용 목록 밖에 새로 생기면 실패(261012-16: 전자서명 셋을 워커로 옮겼다).
QT_KNOWN = {"OnlineDictFetchWorker", "_MergeThread", "_SearchWorker", "_DetailWorker", "_PdfWorker", "_CatalogWorker",
            "_ContentWorker", "_AntLoginWorker", "_KeyVerifyWorker", "_ConnTestWorker", "_CountWorker", "_TransWorker",
            "_BatchWorker"}            # 잔존 허용(260906 규칙 이전). 옮기면 여기서도 뺀다
new_qt = sorted(set(qt) - QT_KNOWN)
chk(not new_qt, "H3 새 QThread 직접 상속이 없다(응답성 SOT §4.3 — `run_in_thread` 를 쓴다)", str(new_qt))

# ── I. 없어진 화면 이름 ─────────────────────────────────────────────────────
# 261024-5(SOT 점검): 패널 툴바는 261024-1 에 메뉴 탭·`모음` 으로 바뀌었다. 점검에서 본문 열 곳 넘게 옛 이름('패널 단추'·
#   '도구 막대'·'툴바 `…`')이 지금 자리처럼 남아 있었다(디자인 SOT §2.9 'SOT 표기'). 경위를 말하는 줄('종전'·'옛'·'→')과 §0·코드 블록은 뺀다.
print(NL + "=== I. 없어진 화면 이름(패널 툴바) ===")
GONE = re.compile(r"패널 툴바|패널 단추|도구 툴바|도구 막대|툴바 `|패널 '도구'")   # 261025-9: 보안 SOT 의 패널 '도구' 단추
OK_CTX = ("종전", "옛 ", "→", "v1.6.23")
stale = []
for name, txt in LIVE.items():
    if name == "CLAUDE.md":
        continue
    fence = False
    for ln in body(txt).splitlines():
        if ln.startswith("```"):
            fence = not fence
        if fence or not GONE.search(ln) or any(k in ln for k in OK_CTX):
            continue
        stale.append("%s: %s" % (name[:8], GONE.search(ln).group(0)))
chk(not stale, "I1 SOT 본문이 없어진 패널 툴바 이름을 지금 자리처럼 쓰지 않는다('종전 …' 으로만)", str(stale[:8]))

# 261025-9(SOT 점검, CLAUDE.md §4 의 1): 화면 이름을 바꾸면 옛 이름이 SOT·검사 기대·화면 문구·도움말에 남는다 — 261025 에만
#   이름 바꿈 뒤 검사 기대가 낡아 실패 2건, SOT 여러 곳. ★ 이름을 바꾸면 이 표에 한 줄을 더한다(옛 이름, 새 이름, 작업 번호).
#   옛 이름을 경위로 적는 줄('종전'·'옛 '·'→'·사용자 말 인용 *"…"*)과 §0·코드 블록은 보지 않는다 — 지금 이름처럼 쓴 곳만 잡는다.
RENAMED = [
    ("즐겨찾기 폴더", "등록 폴더", "261025-1"),
    ("변환해서 내보내기", "변환", "261025-5"), ("변환하여 내보내기", "변환", "261025-5"),
    ("화면 스타일", "스타일", "261025-6"),
    ("모음 메뉴 편집", "모음 메뉴 관리", "261025-5"),
    ("메뉴 탭 아래 세부 줄 보이기", "리본 메뉴 보이기", "261025-5"),
    ("디지털 ID...", "디지털 ID 관리...", "261031-1"),
    ("단어장·책갈피 동시 생성", "일괄 OCR", "261102-6"),
    # 261031-16(디자인 SOT §2.9.1): 도구 메뉴 이름 — '태그 자동 부여' 는 기능 이름으로도 쓰여 메뉴 꼴(▸)만 본다
    ("태그 자동 부여 ▸", "태그 ▸", "261031-16"), ("인덱스 재구축", "인덱스", "261031-16"),
    ("사전 및 용어집 관리", "사전 관리", "261031-16"),
    # 261107-12(디자인 SOT §2.14): 환경설정 재구성 — 따로 뜨던 창은 한 창의 항목으로
    ("고급 설정...", "외부 연결(환경설정 고급)", "261107-12"), ("발표화면 녹화 설정", "발표 녹화(환경설정 고급)", "261107-12"),
    ("시작 시 동작", "일반 › 시작", "261107-12"),
    ("단어장 관리 (출처·우선순위·폴더)", "단어장 관리 (적용 사전·스타일)", "261103-2"),
    # 261112-1(디자인 SOT §2.7): '#' 메뉴 끝 두 항목 글 끝 '…' 뗌
    ("해시태그 넣기…", "해시태그 넣기", "261112-1"), ("해시태그 폴더로 사본 저장…", "해시태그 폴더로 사본 저장", "261112-1"),
    # 261113-9·-10(태그 SOT §8.7·§5.8): 창·메뉴 이름, 환경설정 묶음 이름
    ("해시태그 넣기", "해시태그 수정", "261113-9"), ("형식 낱말 (PDF 자동 해시태그)", "자동 해시태그 (PDF 모드)", "261113-10"),
    ("사진 자동 해시태그 종류", "자동 해시태그 (사진 모드)", "261113-10"),
    # 261105-25·-28(응답성 SOT §4.6): 작업을 멈추는 단추 '중지' → '중단'. 녹화·재생·시계의 '중지' 는 다른 뜻이라
    #   단추 꼴([중지])·창 이름(…생성 중지)만 본다
    ("[중지]", "[중단]", "261105-28"), ("생성 중지", "생성 중단", "261105-28"),
    # 261107-2(디자인 SOT §2.9.8 의 5): 우클릭 메뉴 이름 — 창 제목·기능 이름으로도 쓰이는 '선과 텍스트 입력 설정' 은 넣지 않는다
    #   261108-2: '평탄화해서 내보내기' 는 261107-20 에 창 제목·안내 글도 '평탄화 사본' 이 되어 넣는다(디자인 SOT 바뀐 이름 표)
    ("평탄화해서 내보내기", "평탄화 사본", "261107-20"),
    ("왼쪽으로 90° 돌리기", "왼쪽 90° 회전", "261107-2"), ("오른쪽으로 90° 돌리기", "오른쪽 90° 회전", "261107-2"),
    ("180° 돌리기", "180° 회전", "261107-2"), ("용량 줄여 내보내기", "용량 줄인 사본", "261107-2"),
    ("개인정보 지우고 별도 저장", "개인정보 지운 사본", "261107-2"), ("공유용 사본 (정보 모두 지움)", "개인정보 지운 사본", "261107-2"),
    ("공유용 사본 (위치 지움)", "(메뉴에서 뺌)", "261107-2"), ("변경 적용 — 새 PDF로 저장", "다른 이름으로 저장", "261107-2"),
    ("방향 저장 (원본 JPEG)", "저장 ▸ 저장", "261107-2"), ("OCR로 글자층 생성", "OCR 로 글자층 생성", "261107-2"),
    ("파일 복사 (N개)", "폴더로 복사 (N개)", "261107-2"), ("파일 이동 (N개)", "폴더로 이동 (N개)", "261107-2"),
    ("기본 PDF 앱 등록", "기본 PDF 앱으로 설정", "261107-14"),
    ("기본 PDF 앱으로 설정", "기본 앱 설정", "261114-7"), ("기본 사진 앱으로 설정", "기본 앱 설정", "261114-7"),
    # 261107-13(단어장 SOT §11.1): 도구 탭 '사전 관리 ▾' 열 개 → 단추 하나 + 사전 관리 창(종전 단어장 관리 창)
    ("단어장 관리 (적용 사전·스타일)", "사전 관리", "261107-13"), ("단어장 관리 창", "사전 관리 창", "261107-13"),
    ("인터넷 사전 보강 (이어하기)", "인터넷 사전 보강", "261107-13"), ("용어집 가져오기 (PDF·CSV)", "가져오기", "261107-13"),
    ("사전 내보내기 (TBX·CSV)", "내보내기", "261107-13"), ("사전 백업 (내보내기)", "백업", "261107-13"),
    ("사전 복원 (가져오기)", "복원", "261107-13"), ("용어집 CSV 양식 예제 저장", "양식 CSV", "261107-13"),
    ("온용어 다시 분류 (용어집별·재조회)", "온용어 다시 분류", "261107-13"),
    ("사전 관리 창", "환경설정 고급 › 사전", "261107-17"),       # 261107-17: 창은 없어지고 환경설정 항목으로(단어장 SOT §11.1)
    ("등록·설치", "설치·설정", "261107-24"), ("PDF번역", "번역", "261107-24"),   # 261107-24(사용자 결정): 도구 탭 ▾ 묶음·번역 메뉴
    ("펼친 사진 저장 때 원본 백업 폴더", "원본 백업 폴더 (사진·PDF)", "261107-29"),   # 261107-29: 사진·PDF 공용, 일반 쪽으로(마스터 §4.7.5)
    ("이 PDF 사전", "사전", "261107-34"),       # 261107-34(단어장 SOT §11.1): 단어장 창 머리줄로, 이름 줄임
    # 261111-4(사용자 지시 'pdf 만들기 -> pdf 저장', 결정 '저장 ▸ 모두 + 사진 줄'): 맨 'PDF 만들기' 는 변환 창 제목·
    #   '고른 N개 병합해 PDF 만들기'·리본 묶음 이름으로 그대로 쓰여 메뉴 꼴만 본다
    ("저장 ▸ PDF 만들기", "저장 ▸ PDF 저장", "261111-4"), ("PDF 만들기 (N개 병합)", "PDF 저장 (N개 병합)", "261111-4"),
    ("고른 사진 N장으로 PDF 만들기", "고른 사진 N장으로 PDF 저장", "261111-4"),
    ("고른 사진 {n}장으로 PDF 만들기", "고른 사진 {n}장으로 PDF 저장", "261111-4"),
    ("줄의 사진 {n}장 모두로 PDF 만들기", "줄의 사진 {n}장 모두로 PDF 저장", "261111-4"),
    # 261111-24(사용자 결정 '둘 다 PDF 저장으로'): 인쇄 묶음 병합 줄도 저장 ▸ 와 같은 이름, 변환 창 제목도 'PDF 저장'
    ("고른 N개 병합해 PDF 만들기", "PDF 저장 (N개 병합)", "261111-24"),
    ("고른 {n}개 병합해 PDF 만들기", "PDF 저장 ({n}개 병합)", "261111-24"),
    # 261114-6(마스터 §1.1, 사용자 결정 'A안: 보이는 이름만'): 보이는 이름 PolyPDF → PolyPinax. 맨 'PolyPDF' 는 내부 ID 로도 쓰여
    #   (설정 폴더·ProgID·레이어 등) 화면에만 쓰이는 꼴만 적는다
    ("다른 PolyPDF 창", "다른 PolyPinax 창", "261114-6"), ("PolyPDF 전달 묶음", "PolyPinax 전달 묶음", "261114-6"),
    ("PolyPDF 프린터", "PolyPinax 프린터", "261114-6"), ("PolyPDF 업데이트", "PolyPinax 업데이트", "261114-6"),
    ("가상 프린터(PolyPDF)", "가상 프린터(PolyPinax)", "261114-6"), ("가상 프린터 'PolyPDF'", "가상 프린터 'PolyPinax'", "261114-6"),
    ("PolyPDF 시작 모드", "PolyPinax 시작 모드", "261114-6"), ("PolyPDF 에서 고르기", "PolyPinax 에서 고르기", "261114-6"),
    ("PolyPDF 에서 열기", "PolyPinax 에서 열기", "261114-6"), ("PolyPDF 언어", "PolyPinax 언어", "261114-6"),
]
# 화면 문구(tr("옛 이름…"))가 아직 남은 것 — 코드 결함으로 보고했고 고칠 세션이 이 줄을 지운다. 고쳤는데 남아 있으면 실패(목록은 줄기만).
RENAMED_CODE_PENDING = set()                   # 261025-9 보고분(ribbon.py 모음 창 제목)은 261025-5 보완에서 고쳤다
REN_OK = ("종전", "옛 ", "→", '*"', "개명", "이름이 바뀐")
ren_sot, ren_test, ren_code, ren_help = [], [], set(), []
for name, txt in LIVE.items():
    fence = False
    for ln in body(txt).splitlines():
        if ln.startswith("```"):
            fence = not fence
        if fence or any(k in ln for k in REN_OK):
            continue
        ren_sot += ["%s: %s" % (name[:8], o) for o, _n, _w in RENAMED if o in ln]
for p, src in CODE.items():
    if p.name == "test_sot_crossref.py":
        continue                                        # 이 표 자체
    is_test = p.parent == ROOT and p.name.startswith("test_")
    for ln in src.splitlines():
        code = ln.split("#", 1)[0]                      # 주석은 경위라 보지 않는다
        for o, _n, _w in RENAMED:
            lit = re.search(r"([\"'])%s(?:\.\.\.|…)?\1" % re.escape(o), code)
            if not lit:
                continue
            if is_test and "not in" not in code and not any(k in ln for k in REN_OK):
                ren_test.append("%s: %s" % (p.name, o))   # 검사가 옛 이름을 기대한다
            if not is_test and re.search(r"\btr\(\s*[\"']%s" % re.escape(o), code):
                ren_code.add(o)
for hp in sorted((ROOT / "resources" / "help").glob("help_*.html")):
    h = read(hp)
    ren_help += ["%s: %s" % (hp.name, o) for o, _n, _w in RENAMED if o in h]
chk(not ren_sot, "I2 SOT 본문이 바뀐 화면 이름의 옛 이름을 지금 이름처럼 쓰지 않는다(RENAMED)", str(ren_sot[:8]))
chk(not ren_test, "I3 검사(test_*.py)가 바뀐 화면 이름의 옛 이름을 기대하지 않는다", str(ren_test[:8]))
chk(not (ren_code - RENAMED_CODE_PENDING), "I4 화면 문구 tr(…) 에 옛 이름이 없다", str(sorted(ren_code - RENAMED_CODE_PENDING)))
chk(not (RENAMED_CODE_PENDING - ren_code), "I4b 고친 화면 문구는 RENAMED_CODE_PENDING 에서 뺀다", str(sorted(RENAMED_CODE_PENDING - ren_code)))
chk(not ren_help, "I5 도움말(help_*.html)에 옛 이름이 없다", str(ren_help[:8]))

# ── J. §0 한 줄 도구 ───────────────────────────────────────────────────────
# 261025-9: `scripts/sot_row.py` 가 SOT §0 과 이력 아카이브 그 절에 같은 행을 넣는다(CLAUDE.md §4). 사본에서 돌려 본다 —
#   두 문서를 한 번에(뒤 절의 행을 보고 앞 절을 '이미 있음' 으로 건너뛰던 결함), 다시 돌리면 그대로, 날짜를 거스르면 거부.
print(NL + "=== J. §0 한 줄 도구(scripts/sot_row.py) ===")
import shutil, tempfile, importlib.util, contextlib, io
_spec = importlib.util.spec_from_file_location("sot_row", ROOT / "scripts" / "sot_row.py")
sot_row = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sot_row)
_tmp = Path(tempfile.mkdtemp(prefix="sot_row_"))
try:
    for p in SOT_DIR.glob("*.md"):
        shutil.copy2(p, _tmp / p.name)
    _old_env = os.environ.get("POLYPDF_SOT_DIR")
    os.environ["POLYPDF_SOT_DIR"] = str(_tmp)
    _args = ["add", "--date", "2099-12-31", "--ver", "9.9.9", "--title", "검사 행 (999999-1, 검사)",
             "--docs", "디자인,검색창", "--detail", "검사 원문"]
    with contextlib.redirect_stdout(io.StringIO()):
        rc1 = sot_row.main(_args)
        snap = {n: (_tmp / n).read_bytes() for n in ("화면 디자인 작업 계획서.md", "검색창 작업 계획서.md", sot_row.ARCHIVE)}
        rc2 = sot_row.main(_args)
        try:
            sot_row.main(["add", "--date", "2000-01-01", "--ver", "1", "--title", "옛 날짜 (999999-2, 검사)", "--docs", "디자인"])
            rej = False
        except SystemExit:
            rej = True
    row = sot_row.make_row("2099-12-31", "9.9.9", "검사 행 (999999-1, 검사)")
    both = all(sot_row.verify(sot_row.resolve(x, _tmp), row, _tmp) for x in ("디자인", "검색창"))
    same = all((_tmp / n).read_bytes() == b for n, b in snap.items())
    crlf = all((b"\r\n" in (SOT_DIR / n).read_bytes()) == (b"\r\n" in b) for n, b in snap.items())
    chk(rc1 == 0 and both, "J1 두 문서의 §0 과 아카이브 그 절에 모두 넣는다")
    chk(rc2 == 0 and same, "J2 다시 돌리면 아무것도 바꾸지 않는다")
    chk(rej, "J3 표 첫 행보다 이른 날짜는 거부한다(내림차순)")
    chk(crlf, "J4 파일의 줄 끝(CRLF/LF)을 그대로 둔다")
    chk(sot_row.MAXLEN == 220, "J5 sot_row.MAXLEN = test_sot_compliance 의 §0 행 길이(220)")
finally:
    if _old_env is None:
        os.environ.pop("POLYPDF_SOT_DIR", None)
    else:
        os.environ["POLYPDF_SOT_DIR"] = _old_env
    shutil.rmtree(_tmp, ignore_errors=True)

# ── K. 마스터 §9 신호 표 · §7 API ─────────────────────────────────────────
# 261025-9(SOT 점검): §9 에 261025-4 의 두 신호가 빠졌고, §7.6 에 없는 클래스(`FavoritesDialog`)·빠진 마이그레이션이 남아 있었다.
print(NL + "=== K. 마스터 §9 신호 표 · §7 API 가 코드와 같다 ===")
VIEWER = NL.join(s for p, s in CODE.items() if "viewer" in p.parts or p.name == "main.py")
s9 = mst[mst.find("## 9."):mst.find("## 10.")]
s9_rows = [l for l in s9.splitlines() if l.startswith("| ") and l.count("|") >= 5 and not l.startswith("| Source")]
tab_sigs, tab_emit = set(), set()
for l in s9_rows:
    c = l.split("|")
    tab_sigs |= set(re.findall(r"`(\w+)`", c[2]))
    tab_emit |= set(re.findall(r"[A-Z][A-Za-z]+", c[1]))
gone = sorted(s for s in tab_sigs if not re.search(r"\b%s\s*=\s*pyqtSignal|\.%s\.connect\(" % (s, s), VIEWER))
chk(not gone, "K1 §9 표의 신호가 코드에 있다(선언·연결)", str(gone))
cls_sigs = {}
for p, s in CODE.items():
    if "viewer" not in p.parts and p.name != "main.py":
        continue
    for m in re.finditer(r"^class (\w+)\(.*?(?=^class |\Z)", s, re.M | re.S):
        sg = re.findall(r"^    (\w+)\s*=\s*pyqtSignal\(", m.group(0), re.M)
        if sg:
            cls_sigs.setdefault(m.group(1), set()).update(sg)
app_conn = set(re.findall(r"\.(\w+)\.connect\(", read(ROOT / "viewer" / "app.py")))
undoc = set()
for c in tab_emit & set(cls_sigs):
    undoc |= (cls_sigs[c] & app_conn) - tab_sigs
# 표에 이미 나오는 위젯(BookmarkTree·PageThumbs·MainView …)의 신호 중 아직 표에 없는 것 — 260628 이후 쌓였다. **줄기만 한다**:
#   새로 연결한 신호는 표에 행을 넣는다(이 목록에 더하지 않는다). 표에 넣으면 여기서 뺀다.
SIG_KNOWN_UNDOC = {
    "activated", "addBlankPageRequested", "addBookmarkAtPage", "addFileFavoriteRequested", "addImagePagesRequested",
    "bookmarksChanged", "bookmarksEdited", "bookmarksReverted", "bookmarksUndoable", "clearedAll", "compareFilesRequested",
    "compressFilesRequested", "contextMenuRequested", "convertFilesRequested", "convertPagesRequested", "copyPagesRequested", "copyPaneRequested",
    "createBookmarksRequested", "createStudyBookmarksRequested", "createStudyRequested", "cropPagesRequested", "cropRequested", "dragHoverOpen",
    "drawModeChanged", "editCancelled", "editGlossaryRequested", "error", "fileOpCompleted", "filePasswordEntered",
    "filesRelocated", "flattenFileRequested", "hyperlinkActivated", "imageDropRefused", "imageGotoRequested", "imageStepRequested",
    "mergeFilesRequested", "modeChanged", "ocrLayerFilesRequested", "pageClicked", "pageDeleteRequested", "pageFilterChanged",
    "pagesDropped", "pastePagesRequested", "pathDropped", "printPagesRequested", "probeFinished", "probeProgress",
    "redactFileRequested", "registerHyperlinkAtPage", "releaseFileRequested", "rotatePages", "saveAsFileRequested", "saveRequested",
    "screenshotPagesRequested", "setPagesHidden", "signEditRequested", "signPanelRequested", "signRegionSelected", "signRequested",
    "splitViewRequested", "textCopied", "translateFileRequested", "translateFilesRequested", "uncropPagesRequested", "viewListModeChanged",
    "viewModeChanged", "wordHovered",
}
chk(not (undoc - SIG_KNOWN_UNDOC), "K2 §9 표에 나오는 위젯의 새 신호를 연결하면 표에도 행이 있다",
    str(sorted(undoc - SIG_KNOWN_UNDOC)))
chk(not (SIG_KNOWN_UNDOC - undoc), "K2b 표에 넣은(또는 없앤) 신호는 SIG_KNOWN_UNDOC 에서 뺀다", str(sorted(SIG_KNOWN_UNDOC - undoc)))
s7 = mst[mst.find("## 7."):mst.find("## 8.")]
api_cls, api_def = set(), set()
for blk in re.findall(r"```python\n(.*?)```", s7, re.S):
    api_def |= set(re.findall(r"^\s*def (\w+)\(", blk, re.M))
    for m in re.finditer(r"^([A-Z]\w+(?:\s*/\s*[A-Z]\w+)*)\s*[:(]", blk, re.M):
        api_cls |= set(re.findall(r"[A-Z]\w+", m.group(1)))
chk(not sorted(c for c in api_cls if not re.search(r"^\s*class %s\b" % c, VIEWER, re.M)),
    "K3 마스터 §7 API 블록의 클래스가 코드에 있다", str(sorted(c for c in api_cls if not re.search(r"^\s*class %s\b" % c, VIEWER, re.M))))
chk(not sorted(d for d in api_def if not re.search(r"def %s\(" % d, VIEWER)),
    "K4 마스터 §7 API 블록의 함수가 코드에 있다", str(sorted(d for d in api_def if not re.search(r"def %s\(" % d, VIEWER))))
ss_migs = set(re.findall(r"^def (_migrate_v\d+_to_v\d+)\(", read(ROOT / "viewer" / "settings_store.py"), re.M))
chk(ss_migs <= api_def, "K5 마스터 §7.5 마이그레이션 목록이 settings_store 의 것을 모두 담는다", str(sorted(ss_migs - api_def)))

# ── L. 디자인 SOT §2.9 `모음` 표 = ribbon.DEFAULT_COLLECTION ─────────────────
# 261025-9: 화면 자리의 원본은 코드(ribbon.py·app.py 메뉴)다. Qt 없이 볼 수 있는 기본 모음은 여기서, 탭 자리는 test_sot_ui_layout.py 가 실제 창으로 본다.
print(NL + "=== L. 디자인 SOT §2.9 모음 표 = DEFAULT_COLLECTION ===")
rb = read(ROOT / "viewer" / "widgets" / "ribbon.py")
mdc = re.search(r"^DEFAULT_COLLECTION = \((.*?)^\)", rb, re.S | re.M)
code_groups, cur = [], []
for tok in re.findall(r'"([a-z0-9_.]+)"|\bSEP\b', mdc.group(1) if mdc else ""):
    if tok:
        cur.append(tok)
    else:
        code_groups.append(cur); cur = []
code_groups.append(cur)
dz = SOTS.get("화면 디자인 작업 계획서.md", "")
seg = dz[dz.find("**`모음` 탭**"):]
seg = seg[:seg.find("\n\n", seg.find("| # |"))]
doc_groups, last = [], None
for l in seg.splitlines():
    m = re.match(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|[^|]*\|\s*`([a-z0-9_.]+)`\s*\|", l)
    if m:
        if m.group(1) != last:
            doc_groups.append([]); last = m.group(1)
        doc_groups[-1].append(m.group(2))
chk(bool(code_groups[0]) and doc_groups == code_groups, "L1 디자인 SOT §2.9 모음 표의 명령 id·그룹이 DEFAULT_COLLECTION 과 같다",
    "문서 %s / 코드 %s" % (doc_groups, code_groups))
n_doc = sum(len(g) for g in doc_groups)
m_n = re.search(r"기본값 — (\d+)개", seg)
chk(not m_n or int(m_n.group(1)) == n_doc, "L2 모음 표 앞 글의 개수가 표와 같다", str((m_n.group(1) if m_n else None, n_doc)))

# ── M. 마스터 §6 모듈 지도의 'Qt 없음' ─────────────────────────────────────
# 261111-23(SOT 점검): `photo_address.py` 를 '(Qt 없음)' 이라 적었는데 모듈 머리에서 PyQt6 를 가져와 배경 워커를 두었다.
#   'Qt 없음' 은 '배경 스레드·자식 프로세스에서 불러도 된다' 는 약속이라, 틀리면 그 모듈을 Qt 없는 곳에서 부르는 사람이 깨진다.
print(NL + "=== M. 마스터 §6 'Qt 없음' 모듈은 머리에서 PyQt6 를 가져오지 않는다 ===")
s6 = mst[mst.find("## 6."):mst.find("## 7.")]
bad = []
for m in re.finditer(r"^\|\s*`((?:viewer|widgets|study)/[A-Za-z0-9_/]+\.py)`\s*\|([^|\n]*)\|", s6, re.M):
    if "Qt 없음" not in m.group(2):
        continue
    rel = m.group(1) if m.group(1).startswith("viewer/") else "viewer/" + m.group(1)
    p = ROOT / rel
    if p.exists() and re.search(r"^(?:from PyQt6|import PyQt6)", read(p), re.M):
        bad.append(m.group(1))
chk(not bad, "M1 '(Qt 없음)' 이라 적은 모듈이 머리(들여쓰기 없는 줄)에서 PyQt6 를 가져오지 않는다", str(bad))

print(NL + "=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for msg in fails:
    print(" -", msg)
sys.stdout.flush()
os._exit(0 if not fails else 1)
