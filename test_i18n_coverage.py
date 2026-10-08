"""다국어 SOT §9 — 화면 문구 감싸기 범위 (Phase 3, 261008-24)

`viewer/` 의 한글 문자열이 `tr()`·`trp()`·`trn()`·`tr_noop()` 밖에 있으면 실패한다. 예외는 셋뿐이다.
  - PENDING: 아직 감싸지 않은 모듈과 그 단계(한국 전용 Phase 4, 도움말 Phase 5, 업데이트 Phase 6)
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

PENDING = {
    # Phase 4 — 한국 전용(§7): 한국어가 아닌 언어에서는 숨긴다
    "viewer/study_controller.py": 4, "viewer/widgets/study_panel.py": 4,
    "viewer/widgets/study_edit_dialog.py": 4, "viewer/widgets/dict_manager_dialog.py": 4,
    "viewer/widgets/law_search_dialog.py": 4, "viewer/widgets/kipo_search_dialog.py": 4,
    "viewer/widgets/kcsc_search_dialog.py": 4, "viewer/side_panel_host.py": 4,
    "viewer/study/": 4,
    # Phase 5 — 도움말(언어별 리소스)
    "viewer/widgets/help_dialog.py": 5,
    # Phase 6 — 업데이트 창·받기
    "viewer/update_controller.py": 6, "viewer/widgets/update_dialog.py": 6, "viewer/updater.py": 6,
}
DATA = {
    "viewer/auto_tag.py", "viewer/toc_parse.py", "viewer/text_extract2.py", "viewer/indexer.py",
    "viewer/i18n.py", "viewer/_vendor/",
}
_FONTS = {"맑은 고딕", "굴림", "바탕", "돋움"}
ALLOW = {
    # 파일·폴더 이름(사용자 디스크에 남는 값 — 언어를 바꿔도 같아야 한다)
    "viewer/app.py": {"PolyPDF_특허", "_암호화.pdf", "클립보드.png", "화면캡처.png",
                      "기본값"},                                # 배포 기본값 프로필 이름
    "viewer/edit_controller.py": {"_일반뷰어용.pdf"},
    "viewer/print_controller.py": {"_다단.pdf", "_외", "_이미지.pdf", "_인쇄.pdf", "건", "스크린샷.pdf"},
    "viewer/twoup.py": {"(제목 없음)", "간지_샘플.docx", "목차", "목차_샘플.docx", "표지_샘플.docx",
                        "항목"},                               # 만든 PDF 안의 글 — Phase 5(§8)
    "viewer/page_edit_build.py": {"(제목 없음)"},             # 만든 PDF 의 책갈피 제목 — Phase 5
    "viewer/instance_link.py": {"응답 없음"},                 # 창 사이 통신 오류 값(로그)
    "viewer/settings_store.py": {"기본값"},
    "viewer/text_word.py": {"python-docx 없음: "},            # 예외 메시지
    # 장치 이름 짐작(실제 장치 이름과 맞춰 본다)
    "viewer/recorder.py": {"마이크", "믹스", "스테레오 믹스"},
    # 내부 키(값) — 표시할 때만 tr(값)
    "viewer/widgets/bookmark_tree.py": {"주제", "형식"},
    "viewer/widgets/main_view.py": {"본문", "쪽 맞춤", "2장 맞춤", "폭 맞춤", "수동 맞춤", "수동",
                                    "선 1", "선 2", "선 3", "선 4", "선 5"},
    "viewer/widgets/read_aloud.py": {"전체", "[가-힣]", "[가-힣A-Za-z]", "[^0-9A-Za-z가-힣]",
                                     "[0-9A-Za-z가-힣]+",
                                     r"(?<=[.!?。])\s+|\n+|(?<=다\.)\s*|(?<=요\.)\s*"},
    "viewer/widgets/thumbs_list.py": {"한"},                  # 글자 폭을 재는 표본
    # 사용자 데이터 기본 이름(설정에 저장돼 사용자가 고친다). 발표 포인터·펜·캡처 크기 기본 이름은
    #   tr_noop + 보여 줄 때 tr(이름)이라 여기 없다(사용자가 고친 이름은 번역이 없어 그대로 보인다)
    "viewer/widgets/merge_dialog.py": {"사용자 스크린샷"},
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


def bare_korean(path):
    t = ast.parse(open(path, encoding="utf-8").read())
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
        if _under(rel, PENDING) or _under(rel, DATA):
            continue
        scanned += 1
        allow = ALLOW.get(rel, set())
        for ln, s in bare_korean(os.path.join(HERE, rel)):
            if s in _FONTS:
                continue
            if s in allow:
                used.add((rel, s))
                continue
            bad.append("%s:%d %r" % (rel, ln, s[:40]))

chk(scanned > 60, "A 검사한 모듈 수", str(scanned))
chk(not bad, "A 감싸지 않은 한글 화면 문구가 없다(PENDING·DATA·ALLOW 제외)", "\n  " + "\n  ".join(bad[:30]))
stale = sorted("%s %r" % (f, s) for f, ss in ALLOW.items() for s in ss if (f, s) not in used)
chk(not stale, "B 허용 목록에 이제 없는 값이 남아 있지 않다(목록을 줄인다)", str(stale[:10]))
missing = [k for k in list(PENDING) + sorted(DATA) + list(ALLOW)
           if not os.path.exists(os.path.join(HERE, k))]
chk(not missing, "C 목록의 경로가 모두 있다", str(missing))

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
