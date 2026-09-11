# -*- coding: utf-8 -*-
"""260908-9: **SOT 준수 검사** — 규칙을 글이 아니라 검사로 지킨다.

사용자 지시(260908): "모든 SOT 에 따라 프로그램이 적합한지 검토하고 ... 이후 업그레이드시
최적의 상태를 유지하기 위해 기존 기준을 통일되게 지키기 쉽도록 수정 보완해."

문제는 규칙이 없다는 것이 아니라 **규칙이 문서에만 있다**는 것이었다. 응답성 SOT 신설의
계기도 그랬다 — "규칙이 산문 한가운데 섞여 있어 새 기능을 넣는 사람이 읽지 않았다"
(응답성 §1). 감사(260908-9)에서 실제로 셋이 어긋나 있었다.

  ① `AutoTagWorker` 가 `dict.db` 를 `sqlite3.connect` 로 직접 열었다(대기 상한 기본 5초)
  ② 새 워커 `TextOcrPageWorker` 가 응답성 §4.4 감사표에 없었다
  ③ 새 검사가 **업무 문서 절대경로**를 하드코딩했다(공개 저장소·가짜 통과, CLAUDE.md §3)

이 파일은 그런 어긋남을 **다음부터는 검사가 잡게** 한다. 문서를 고치는 사람과 코드를
고치는 사람이 달라도, 스위트를 돌리면 어긋남이 드러난다.

※ 이 검사는 **규칙의 소유자가 아니다.** 규칙 본문은 각 SOT 가 갖는다. 여기서는
  '기계로 확인할 수 있는 형태'만 다시 적는다. 규칙이 바뀌면 SOT 를 먼저 고치고
  이 파일을 맞춘다(CLAUDE.md §4).
"""
import os, re, sys, subprocess

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path

ROOT = Path(HERE)
SOT_DIR = ROOT.parent                       # MPDF/ — SOT 문서가 있는 곳(비공개)
NL = chr(10)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


def py_files():
    for p in sorted((ROOT / "viewer").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def read(p):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def strip_comments(src: str) -> str:
    """주석·독스트링 안의 '위반처럼 보이는 글'을 세지 않게 걷어낸다."""
    out = []
    for ln in src.splitlines():
        t = ln.split("#", 1)[0]
        out.append(t)
    s = NL.join(out)
    s = re.sub(r'"""(?:.|\n)*?"""', '""', s)
    s = re.sub(r"'''(?:.|\n)*?'''", "''", s)
    return s


CODE = {p: strip_comments(read(p)) for p in py_files()}
SOTS = {p.name: read(p) for p in sorted(SOT_DIR.glob("*.md"))}
SOT_ALL = NL.join(SOTS.values())
HAVE_SOT = bool(SOTS)

print("=== 응답성 SOT §4 ⑤ — SQLite 연결 표준 ===")
bad = [p for p, s in CODE.items()
       if "sqlite3.connect(" in s and p.name != "dbutil.py"]
chk(not bad, "⑤ `sqlite3.connect` 를 직접 부르는 곳이 없다(dbutil 만)",
    str([p.name for p in bad]))
users = [p for p, s in CODE.items() if "dbutil" in s or "_dbutil" in s or "_db." in s]
chk(len(users) >= 4, "⑤ DB 를 만지는 모듈이 표준 연결을 쓴다", str(len(users)) + "개")

print(NL + "=== 응답성 SOT §4 ⑦ — 양보는 점유율로 ===")
bad = [p for p, s in CODE.items() if "time.sleep(self.YIELD_S)" in s]
chk(not bad, "⑦ `time.sleep(self.YIELD_S)` 직접 호출이 없다(pacing.pace)",
    str([p.name for p in bad]))
wk = CODE.get(ROOT / "viewer" / "workers.py", "")
chk(wk.count("_pacing.pace(self)") >= 4, "⑦ 반복형 워커가 pace 를 쓴다",
    str(wk.count("_pacing.pace(self)")) + "곳")

print(NL + "=== 응답성 SOT §4 ⑥·§6 — 메인 스레드 ===")
bad = [p for p, s in CODE.items() if re.search(r"setInterval\(\s*0\s*\)", s)]
chk(not bad, "⑥ 간격 0 반복 타이머가 없다", str([p.name for p in bad]))
bad = []
for p, s in CODE.items():
    for m in re.finditer(r"\n(\s*)while\b[^\n]*:\n((?:\1\s+[^\n]*\n)+)", s):
        if "processEvents" in m.group(2) and "should_cancel" not in m.group(2):
            bad.append(p.name)
            break
chk(not bad, "§6 `while` 안에서 `processEvents()` 로 도는 곳이 없다", str(bad))
bad = [p for p, s in CODE.items()
       if re.search(r"\.rglob\(", s) and p.name not in ("pathutil.py",)]
chk(not bad, "§6 목록 수집은 `pathutil.iter_pdfs`(취소 가능) 로만", str([str(x) for x in bad]))

print(NL + "=== 응답성 SOT §4.4 — 워커는 감사표에 등재 ===")
worker_names = sorted(set(re.findall(r"^class\s+([A-Za-z_]*Worker)\(",
                                     read(ROOT / "viewer" / "workers.py"), re.M)))
chk(len(worker_names) >= 10, "§4.4 워커를 찾았다", str(len(worker_names)) + "개")
if HAVE_SOT:
    resp = SOTS.get("응답성 작업 계획서.md", "")
    miss = [w for w in worker_names if not w.startswith("_") and w not in resp]
    chk(not miss, "§4.4 모든 워커가 감사표에 있다", str(miss))
else:
    print("SKIP - SOT 문서를 찾을 수 없다(공개 저장소 단독 실행)")

print(NL + "=== 마스터 §14.7 — 검사 규약 ===")
tests = sorted(p for p in ROOT.glob("test_*.py") if p.name != "test_fixtures.py")
noqt = [p.name for p in tests if "QT_QPA_PLATFORM" not in read(p)
        and "PyQt6" in read(p)]
chk(not noqt, "§14.7 Qt 를 쓰는 검사는 모두 오프스크린", str(noqt))
# 업무 문서 절대경로 금지 — `test_ocr_bookmarks.py` 만 예외(SOT 에 명시된 사유)
SAMPLE_OK = {"test_ocr_bookmarks.py"}
bad = [p.name for p in tests
       if "_samples" in read(p) and p.name not in SAMPLE_OK
       and re.search(r"_samples[" + re.escape(chr(92)) + r"/]", read(p))]
chk(not bad, "§14.7 업무 문서 절대경로를 쓰는 검사가 없다(픽스처를 쓴다)", str(bad))
import test_fixtures as _fx
for name in ("text_pdf", "scanned_pdf", "ruled_table_pdf", "scanned_form_pdf"):
    chk(hasattr(_fx, name), "§14.7 픽스처 `%s()` 가 있다" % name)

print(NL + "=== 마스터 §14.7.1 — 검사 색인(이름 규칙으로 소유를 정한다) ===")
# ★ 이 표는 마스터 §14.7.1 의 표와 **같은 내용**이다. 한쪽만 고치지 말 것.
OWNER_RULES = [
    (("test_text_",), "텍스트 창"),
    (("test_study_", "test_vocab_", "test_ocr_", "test_dict_"), "단어장/단어학습"),
    (("test_present_", "test_pres_"), "발표"),
    (("test_tag_", "test_auto_tag"), "파일 태그·키워드"),
    (("test_search_", "test_index_", "test_db_lock", "test_nav_save_index",
      "test_probe_cache"), "검색창"),
    (("test_capture", "test_screenshot", "test_shot_", "test_global_capture_mode",
      "test_shortcuts_capture"), "스크린샷"),
    (("test_law_", "test_side_panels"), "법령·고시"),
    (("test_trans_", "test_translate"), "PDF 번역·요약"),
    (("test_img2pdf", "test_image_pdf"), "이미지 PDF 변환"),
    (("test_media_", "test_tts_", "test_record_"), "영상 및 음성"),
    (("test_folder_scan", "test_ui_stall", "test_perf_", "test_prefs_allowlist",
      "test_tool_cancel", "test_startup_open", "test_sot_"), "응답성"),
    (("test_theme_", "test_design_", "test_draw_tools"), "화면 디자인"),
]


def owner_of(name):
    for prefixes, owner in OWNER_RULES:
        if any(name.startswith(x) for x in prefixes):
            return owner
    return "마스터"


buckets = {}
for t in tests:
    buckets.setdefault(owner_of(t.name), []).append(t.name)
chk(all(owner_of(t.name) for t in tests), "모든 검사에 소유 SOT 가 정해진다")
print("     " + " / ".join("%s %d" % (k, len(v)) for k, v in sorted(buckets.items())))
if HAVE_SOT:
    idx = SOTS.get("PolyPDF 뷰어 통합 작업 계획서.md", "")
    chk("### 14.7.1" in idx, "§14.7.1 검사 색인이 마스터에 있다")
    # 모듈 SOT 가 소유한 검사는 그 SOT 의 §검증 표에도 이름이 있어야 한다
    NAMED = {
        "텍스트 창": "텍스트 창 작업 계획서.md",
        "응답성": "응답성 작업 계획서.md",
    }
    for owner, sot_name in NAMED.items():
        txt = SOTS.get(sot_name, "")
        miss = [n for n in buckets.get(owner, []) if n not in txt]
        chk(not miss, "%s 소유 검사가 그 SOT §검증 표에 있다" % owner, str(miss))

print(NL + "=== CLAUDE.md — 문서·저장소 규약 ===")
ver = read(ROOT / "viewer" / "__init__.py")
m = re.search(r'__version__\s*=\s*"([^"]+)"', ver)
chk(bool(m), "버전 문자열이 있다", m.group(1) if m else "")
chk(bool(m) and re.match(r"^\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$", m.group(1)),
    "버전이 SemVer 형식", m.group(1) if m else "")
if HAVE_SOT:
    ver_in_master = m and m.group(1) in SOTS.get("PolyPDF 뷰어 통합 작업 계획서.md", "")
    chk(bool(ver_in_master), "이 버전이 마스터 §0 연대기에 있다", m.group(1) if m else "")
    hdr = "| 날짜 | 버전 | 내용 |"
    # 자체 changelog 를 가진 문서는 3열 표 형식을 지킨다(마스터에 위임한 문서는 제외)
    delegated = ("버전 연대기(§0 changelog)는 마스터", "변경 이력(버전 한 줄)은 마스터")
    for name, txt in SOTS.items():
        # 아카이브는 이력을 담는 곳이라 자체 changelog 를 두지 않는다(260910)
        if name == "CLAUDE.md" or "아카이브" in name:
            continue
        if any(d in txt for d in delegated):
            continue
        chk(hdr in txt, "§0 changelog 가 3열 표 형식 — " + name)

print(NL + "=== CLAUDE.md §4 — 연대기는 §0 안에, 날짜 내림차순 (260910-7) ===")
# 마스터의 연대기 행 35개가 문서 앞머리 '문서 지도' 표(인용문 `>`) 안으로 새어 있었다.
#   `>` 없는 행이 인용문을 끊어 **문서 지도 표가 머리글만 남아 깨졌고**, 날짜가 가장
#   최근인 행이 문서 11번째 줄에 있어 다음 사람이 '§0 최상단' 을 찾으면 그 자리에 또
#   넣게 됐다 — beta.108 부터 beta.146 까지 실제로 그렇게 자랐다.
#   되돌리는 것만으로는 재발한다. 그래서 여기서 검사한다(이 파일 첫머리의 태도 그대로).
if HAVE_SOT:
    CROW = re.compile(r"^[|]\s*(20[0-9][0-9]-[0-9][0-9]-[0-9][0-9])\s*[|]")
    for name, txt in SOTS.items():
        if name == "CLAUDE.md" or "아카이브" in name:
            continue
        if any(d in txt for d in delegated):
            continue
        lines = txt.splitlines()
        h0 = next((i for i, l in enumerate(lines) if l.startswith("## 0.")), -1)
        if h0 < 0:
            continue
        # ⓐ §0 머리글 **앞**의 연대기 행 = 다른 표 안에 끼어든 것이다
        early = [i + 1 for i in range(h0) if CROW.match(lines[i])]
        chk(not early, "ⓐ 연대기 행이 §0 앞에 없다 — " + name,
            ("줄 " + str(early[:3]) + " 등 " + str(len(early)) + "행") if early else "")
        # ⓑ §0 표의 날짜가 내림차순 — 표 **한가운데** 잘못 끼우는 것까지 잡는다
        i = h0
        while i < len(lines) and not lines[i].startswith("| ---"):
            i += 1
        i += 1
        body = []
        while i < len(lines) and lines[i].startswith("|"):
            body.append(lines[i])
            i += 1
        ds = [CROW.match(l).group(1) for l in body if CROW.match(l)]
        rev = [k for k in range(1, len(ds)) if ds[k] > ds[k - 1]]
        chk(not rev, "ⓑ §0 연대기가 날짜 내림차순 — " + name,
            (str(len(rev)) + "곳 역행 "
             + str([ds[k - 1] + "->" + ds[k] for k in rev[:2]])) if rev
            else str(len(ds)) + "행")
# SOT 문서는 공개 저장소에 들어가지 않는다(패턴이 아니라 git 판정으로 확인)
if HAVE_SOT:
    names = [n for n in SOTS if n != "CLAUDE.md"] + ["CLAUDE.md"]
    leak = []
    for n in names:
        try:
            r = subprocess.run(["git", "check-ignore", "-q", n], cwd=str(ROOT),
                               capture_output=True, timeout=20)
            if r.returncode != 0:
                leak.append(n)
        except Exception:
            leak.append("(git 실행 불가) " + n)
    chk(not leak, "★ 모든 SOT 문서가 공개 저장소에서 무시된다", str(leak))

print(NL + "=== CLAUDE.md §4 — SOT 는 '지금 사양' 만 담는다 (260910) ===")
# 문서 절반이 연대기가 되면 '지금 무엇이 규칙인가' 를 이력에서 캐내야 한다.
#   실제로 마스터(§17·§18)와 단어학습(§23~§71, 52%)이 그렇게 됐다.
if HAVE_SOT:
    import re as _re
    # '연대기 장' = 번호 뒤에 **날짜나 '수정/Phase'** 가 오고 버전이 붙은 것.
    #   `## 6. 디렉터리 구조 (v1.6.2)` 처럼 사양 장에 버전만 붙은 것은 아니다.
    # '연대기 장' = 번호 뒤에 **날짜나 '수정N/Phase N'** 이 오고 버전이 붙은 것.
    #   `## 6. 디렉터리 구조 (v1.6.2)` 처럼 사양 장에 버전만 붙은 것은 아니다.
    _D = chr(92) + 'd'
    _ESC = chr(92)
    CHRON = _re.compile('^## ' + _D + '+[a-z]?' + _ESC + '. '
                        + '(?:' + _D + '{6}|.*수정' + _D + '|.*Phase ' + _D + ')'
                        + '.*' + _ESC + '(v' + _D + '+' + _ESC + '.' + _D + '+'
                        + _ESC + '.' + _D + '+' + _ESC + ')')
    for name, txt in SOTS.items():
        if '아카이브' in name or name == 'CLAUDE.md':
            continue        # 아카이브는 이력을 담는 곳이다
        bad_ch = [l for l in txt.splitlines() if CHRON.match(l)]
        chk(not bad_ch, '연대기 장이 SOT 본문에 남아 있지 않다 — ' + name,
            str(len(bad_ch)) + '장' if bad_ch else '')
    # 아카이브도 CLAUDE.md 에 등재돼 있어야 한다(어디에 무엇이 있는지 한곳에서 보이게)
    claude = SOTS.get('CLAUDE.md', '')
    arch = [n for n in SOTS if '아카이브' in n]
    miss = [n for n in arch if n not in claude]
    chk(not miss, '아카이브 문서가 CLAUDE.md §3 에 등재돼 있다', str(miss))
    # 모든 SOT 가 CLAUDE.md 에 이름이 있어야 한다
    miss2 = [n for n in SOTS if n != 'CLAUDE.md' and n not in claude]
    chk(not miss2, '모든 SOT 가 CLAUDE.md 에 등재돼 있다', str(miss2))

print(NL + "=== 문서가 가리키는 절이 실제로 있는가 (260910) ===")
# 코드 주석이 `단어학습 SOT §14.8` 처럼 가리키는데 그 절이 없으면, 다음 사람은
#   규칙의 근거를 찾지 못한다. 문서를 재구성할 때 가장 먼저 낡는 것이 이 참조다.
if HAVE_SOT:
    import re as _re2
    NAMED_SOT = {
        '텍스트 창': '텍스트 창 작업 계획서.md',
        '단어학습': '단어학습(OCR·어휘) 기능 작업계획서.md',
        '응답성': '응답성 작업 계획서.md',
        '검색창': '검색창 작업 계획서.md',
    }
    bad_ref = []
    pat = _re2.compile(r'(텍스트 창|단어학습|응답성|검색창)\s*SOT\s*(§[0-9]+(?:\.[0-9]+)*)')
    for f, src in CODE.items():
        for who, sec in pat.findall(read(f)):        # 주석까지 본다
            doc = SOTS.get(NAMED_SOT[who], '')
            num = sec[1:]
            if not _re2.search(r'^#{2,4} ' + _re2.escape(num) + r'[ .]', doc, _re2.M):
                bad_ref.append('%s: %s SOT %s' % (f.name, who, sec))
    chk(not bad_ref, '코드가 가리키는 SOT 절이 실제로 있다',
        str(sorted(set(bad_ref))[:6]))

print(NL + "=== 텍스트 창 SOT §3.5.1 — 잡음 판정의 단일 소유 ===")
owner = ROOT / "viewer" / "text_noise.py"
chk(owner.exists(), "판정 모듈이 있다")
bad = [p.name for p, s in CODE.items()
       if p.name not in ("text_noise.py",) and re.search(r"NOISE_MIN_H_PT\s*=\s*[0-9]", s)]
chk(not bad, "잡음 기준값을 딴 데서 새로 정하지 않는다", str(bad))
oc = CODE.get(ROOT / "viewer" / "study" / "ocr.py", "")
chk("keep_ocr_word" in oc, "OCR 경로가 같은 판정을 쓴다(단어장·검색까지 함께)")

print(NL + "=== 마스터 §7.0 — 경로 키 표준 ===")
pu = read(ROOT / "viewer" / "pathutil.py")
chk("def norm_key" in pu, "§7.0 `pathutil.norm_key` 가 표준 키")
chk("def iter_pdfs" in pu and "should_cancel" in pu,
    "§7.0 `iter_pdfs(should_cancel=)` 가 표준 수집기")

print(NL + "=== 빌드 — 새 모듈이 실행 파일에 들어가는가 ===")
bat = read(ROOT / "build_ci.bat")
chk("--collect-submodules viewer" in bat,
    "`viewer.*` 는 자동 포함 — 새 모듈에 별도 등재가 필요 없다")

print(NL + "=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for msg in fails:
    print(" -", msg)
sys.stdout.flush()
os._exit(0 if not fails else 1)
