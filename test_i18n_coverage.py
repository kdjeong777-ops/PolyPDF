"""다국어 SOT §9 — 화면 문구 감싸기 범위 (Phase 3, 261008-24 · Phase 4 에서 KOREA_ONLY, 261008-25)

`viewer/` 의 한글 문자열이 `tr()`·`trp()`·`trn()`·`tr_noop()` 밖에 있으면 실패한다. 예외는 넷뿐이다.
  - KOREA_ONLY: 한국어가 아니면 숨기는 기능의 모듈(§7) — 감싸지 않는다(사용자 결정 261008-25).
    그 안에서도 모든 언어가 쓰는 코드는 SHARED 로 따로 검사한다(본문 mp3·OCR 엔진)
  - PENDING: 아직 감싸지 않은 모듈과 그 단계 — Phase 6 으로 비었다(도움말은 Phase 5, 업데이트는 Phase 6 에 감쌌다)
  - DATA: 한국어 처리 자료·정규식이 본업인 모듈(태그 사전·목차 해석·글자층 추출·인덱스 SQL·언어 이름)
  - ALLOW: 감싸지 않기로 정한 값 — 파일·폴더 이름, 글꼴 이름, 사용자 데이터 기본 이름, 내부 키, 정규식
그 밖에 문서 설명(docstring)·로그·예외 메시지·비교식·첨자는 보지 않는다(§6 '감싸지 않는 것').
새 화면 문구를 감싸지 않고 넣으면 여기서 걸린다. 단계가 끝나면 PENDING 에서 빼고 ALLOW 를 줄인다.
"""
import ast, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
H = re.compile(r"[가-힣]")
TRF = {"tr", "trp", "trn", "tr_noop"}
SKIPF = {"debug", "info", "warning", "exception", "error", "critical", "print", "RuntimeError",
         "ValueError", "KeyError", "Exception", "TypeError", "OSError", "PermissionError",
         "FileNotFoundError"}

KOREA_ONLY = {
    "viewer/study_controller.py", "viewer/widgets/study_panel.py",
    "viewer/widgets/study_edit_dialog.py", "viewer/widgets/dict_manager_dialog.py",
    "viewer/widgets/law_search_dialog.py", "viewer/widgets/kipo_search_dialog.py",
    "viewer/widgets/kcsc_search_dialog.py", "viewer/side_panel_host.py", "viewer/study/",
}
# 한국 전용 모듈 안이지만 모든 언어가 쓰는 것 — 파일 전체 또는 함수 이름
SHARED = {
    "viewer/study/ocr.py": None,                 # OCR 엔진(텍스트 창·OCR 읽기·구성요소 설치)
    "viewer/study/ocr_headings.py": None,        # 책갈피 자동 생성의 스캔본 헤딩
    "viewer/study_controller.py": {"_on_main_mp3"},   # 본문 mp3 단추
}
PENDING = {
}
DATA = {
    "viewer/auto_tag.py", "viewer/toc_parse.py", "viewer/text_extract2.py", "viewer/indexer.py",
    "viewer/kiwi_space.py",                      # 261009-16: 띄어쓰기 도우미 — 한글은 kiwi 에 넘기는 글(데이터)
    "viewer/i18n.py", "viewer/_vendor/",
}
_FONTS = {"맑은 고딕", "굴림", "바탕", "돋움"}
_REGEX = re.compile(r"\\[sdbwSDW*]|\[[^\]]*가-힣|\(\?[:=!<]")   # \s·\*·[가-힣]·(?: 가 들면 정규식
# 다른 언어의 스크립트를 담은 상수 — 그 안의 한글은 주석뿐이고 화면 문구는 실행 때 채운다(test_i18n_installer E 가 확인)
SCRIPT_CONSTS = {"viewer/updater.py": {"_PS_INSTALLER"}}
ALLOW = {
    # 폴더 이름(사용자 디스크의 자리 — 언어를 바꿔도 같아야 한다). 저장 창에 **제안하는** 파일 이름
    #   (`_다단.pdf`·`스크린샷.pdf` 등)과 만든 PDF 안의 글(목차 제목 등)은 Phase 5 에서 만드는 때의 언어로 감쌌다(§8)
    "viewer/app.py": {"PolyPDF_특허",                         # 특허(한국 전용) 저장 폴더
                      "기본값"},                                # 배포 기본값 프로필 이름
    "viewer/instance_link.py": {"응답 없음"},                 # 창 사이 통신 오류 값(로그)
    "viewer/settings_store.py": {"기본값"},
    "viewer/text_word.py": {"python-docx 없음: "},            # 예외 메시지
    # 장치 이름 짐작(실제 장치 이름과 맞춰 본다)
    "viewer/recorder.py": {"마이크", "믹스", "스테레오 믹스"},
    # 내부 키(값) — 표시할 때만 tr(값)
    "viewer/widgets/bookmark_tree.py": {"주제", "형식"},
    "viewer/widgets/main_view.py": {"본문", "쪽 맞춤", "2장 맞춤", "폭 맞춤", "수동 맞춤", "수동",
                                    "선 1", "선 2", "선 3", "선 4", "선 5"},
    "viewer/widgets/read_aloud.py": {"전체"},                 # 읽기 구간 값(정규식은 _REGEX 가 거른다)
    "viewer/widgets/thumbs_list.py": {"한"},                  # 글자 폭을 재는 표본
    # 사용자 데이터 기본 이름(설정에 저장돼 사용자가 고친다). 발표 포인터·펜·캡처 크기 기본 이름은
    #   tr_noop + 보여 줄 때 tr(이름)이라 여기 없다(사용자가 고친 이름은 번역이 없어 그대로 보인다)
    "viewer/widgets/nup_preset.py": {"(이름없음)"},
    "viewer/widgets/twoup_dialog.py": {"(이름없음)"},
    "viewer/widgets/favorites_dialog.py": {"📁 폴더"},
    "viewer/widgets/pres_timer.py": {"준비"},
    "viewer/widgets/presentation.py": {"링크"},
}

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def bare_korean(path, funcs=None, script_consts=()):
    t = ast.parse(open(path, encoding="utf-8").read())
    if script_consts:                            # 다른 언어 스크립트 상수는 빼고 본다
        t.body = [n for n in t.body if not (isinstance(n, ast.Assign) and any(
            isinstance(g, ast.Name) and g.id in script_consts for g in n.targets))]
    if funcs:                                    # 그 함수들만 본다
        t = ast.Module(body=[n for n in ast.walk(t)
                             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in funcs],
                       type_ignores=[])
    skip = set()
    for n in ast.walk(t):
        if isinstance(n, ast.Call):
            fn = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            if fn in TRF or fn in SKIPF:
                skip.update(id(m) for m in ast.walk(n))
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module))
                and n.body and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant)):
            skip.add(id(n.body[0].value))
        if isinstance(n, ast.Compare):
            skip.update(id(m) for m in ast.walk(n))
        if isinstance(n, ast.Subscript):
            skip.update(id(m) for m in ast.walk(n.slice))
    return [(n.lineno, n.value) for n in ast.walk(t)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and H.search(n.value) and id(n) not in skip]


def _under(rel, table):
    return any(rel == k or (k.endswith("/") and rel.startswith(k)) for k in table)


bad, scanned, used = [], 0, set()
for root, _d, files in os.walk(os.path.join(HERE, "viewer")):
    for fn in files:
        if not fn.endswith(".py"):
            continue
        rel = os.path.relpath(os.path.join(root, fn), HERE).replace("\\", "/")
        funcs = None
        if _under(rel, KOREA_ONLY):
            if rel not in SHARED:
                continue
            funcs = SHARED[rel]
        if _under(rel, PENDING) or _under(rel, DATA):
            continue
        scanned += 1
        allow = ALLOW.get(rel, set())
        for ln, s in bare_korean(os.path.join(HERE, rel), funcs, SCRIPT_CONSTS.get(rel, ())):
            if s in _FONTS or _REGEX.search(s):        # 글꼴 이름·정규식(한국어 처리 자료)
                continue
            if s in allow:
                used.add((rel, s))
                continue
            bad.append("%s:%d %r" % (rel, ln, s[:40]))

chk(scanned > 60, "A 검사한 모듈 수", str(scanned))
chk(not bad, "A 감싸지 않은 한글 화면 문구가 없다(PENDING·DATA·ALLOW 제외)", "\n  " + "\n  ".join(bad[:30]))
stale = sorted("%s %r" % (f, s) for f, ss in ALLOW.items() for s in ss if (f, s) not in used)
chk(not stale, "B 허용 목록에 이제 없는 값이 남아 있지 않다(목록을 줄인다)", str(stale[:10]))
missing = [k for k in list(PENDING) + sorted(DATA) + list(ALLOW) + sorted(KOREA_ONLY) + list(SHARED)
           if not os.path.exists(os.path.join(HERE, k))]
chk(not missing, "C 목록의 경로가 모두 있다", str(missing))

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
