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

SOT 문서는 공개 저장소 밖(부모 폴더)에 있다 — 없으면(CI) 건너뛴다.
"""
import os, re, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # Qt 는 쓰지 않는다 — §14.7 규약 검사용
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
SOT_DIR = ROOT.parent
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


def has_sec(doc, num):
    nums = HEADS.get(doc, set())
    if num in nums:
        return True
    # §14.5 처럼 위 절만 가리키는 것은 그 아래 절이 있으면 된다. §4 처럼 장 번호면 장이 있으면 된다
    return any(h.startswith(num + ".") for h in nums)


def body(txt):
    """§0 변경 이력 표를 뺀 본문 — 이력 행은 그때의 참조라 지금 절과 다를 수 있다."""
    return re.sub(r"^## 0\..*?(?=^## [1-9])", "", txt, flags=re.S | re.M)


SEC = r"§\s?(\d+(?:\.\d+)*)"
ARCHIVE_OF = {MASTER: ("뷰어 변경상세 아카이브.md",),
              "단어학습(OCR·어휘) 기능 작업계획서.md": ("단어학습 변경상세 아카이브.md",),
              "단어장 작업 계획서.md": ("단어학습 변경상세 아카이브.md",)}

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
            if not has_sec(doc, num):
                bad.append("%s: %s §%s" % (p.name, al, num))
chk(not bad, "A1 코드 주석이 가리키는 SOT 절이 있다", str(sorted(set(bad))[:12]))

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
        for m in re.finditer(SEC, l):
            num = m.group(1).rstrip(".")
            if num == "0":
                continue                              # §0 은 이력 표 — 마스터에 맡긴 문서는 없다
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
            if doc not in SOTS:
                continue
            if has_sec(doc, num):
                continue
            # 못 찾으면 — 같은 줄 앞쪽에 나온 다른 문서 이름(목록 '입력 SOT §2.2 · §2.3' 처럼 이어 쓴 것),
            #   또는 이 문서의 아카이브(번호를 그대로 둔 옛 장)에서 찾는다
            alts = [ALIAS_MAP[x] for x in re.findall(ALIAS_RE, before + " " + l[:m.start()])]   # 앞 줄에서 이어진 인용도
            alts += [name] + [a for a in ARCHIVE_OF.get(name, ())]
            if any(has_sec(d, num) for d in alts):
                continue
            if re.search(r"없다|없는|어디에도|존재하지", l):
                continue
            bad.append("%s → %s §%s" % (name[:8], doc[:8], num))
chk(not bad, "A2 SOT 본문(§0 밖)의 절 참조가 그 문서에 있다", "%d건 %s" % (len(set(bad)), sorted(set(bad))[:999 if "-v" in sys.argv else 15]))

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
print(NL + "=== C. 마스터 §14.5 U 번호 ===")
mst = SOTS[MASTER]
udefs = re.findall(r"^\|\s*(U\d+)\s*\|", mst, re.M) + re.findall(r"^>\s*\*\*★\s*(U\d+)\s*—", mst, re.M)
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

print(NL + "=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for msg in fails:
    print(" -", msg)
sys.stdout.flush()
os._exit(0 if not fails else 1)
