# -*- coding: utf-8 -*-
"""261026-6: 메인 스레드 모듈에서 DB 를 여는 곳(새 파일이 생길 수 있는 길)을 막는다 — 응답성 SOT §6 '메인에서 새 파일 만들기'.

1.0.1 빌드 시험 T1 1.37초: 본문 첫 쪽을 그리는 메인의 첫 `StudyStore()` 가 이 실행의 보류 DB 를 ATTACH 로 **처음 만들었고**
새 exe 가 만든 새 파일을 백신이 붙들었다. 고친 뒤 보류 DB 는 배경이 먼저 만든다(`study_store.start_pending_prep`).

  A  메인 스레드 모듈(`app.py`·`*_controller.py`·`widgets/`)에서 DB 를 여는 호출 — `StudyStore(`·`PdfIndex(`·`dbutil`/`sqlite3` 의
     `connect(`, SQL 글 `ATTACH` — 을 AST 로 찾아 `ALLOWED`(종류 — 까닭) 밖이면 실패, 목록에 있는데 사라진 것도 실패
  B  `StudyStore._attach_pending` 이 ATTACH **전에** `wait_pending_ready()` 를 부른다 — 수정 전 코드는 여기서 실패
     (메인의 첫 연결이 보류 파일을 스스로 만들었다)
  C  앱 진입점(`main.py`)이 보류 DB 준비(`start_pending_prep`)를 띄운다
종류: `배경`(안쪽 함수가 워커·`_file_op_bg` 에서) · `보류 DB 는 배경이 먼저`(StudyStore — B 가 지킨다) · `이미 있는 파일`(UI 대기 연결 —
첫 설치 첫 실행만 새로 만든다, 알려진 한계).
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
V = ROOT / "viewer"
MAIN_MODULES = [V / "app.py"] + sorted(V.glob("*_controller.py")) + sorted((V / "widgets").glob("*.py"))
KINDS = {"배경", "보류 DB 는 배경이 먼저", "이미 있는 파일"}

ALLOWED = {
    "viewer/app.py:MainWindow._study_read":
        "보류 DB 는 배경이 먼저 — 메인 전용 연결 하나(응답성 SOT §6), 메인이 아니면 그 스레드에서 새로",
    "viewer/study_controller.py:StudyMixin._study_get_store":
        "보류 DB 는 배경이 먼저 — 단어장 패널의 연결 하나",
    "viewer/widgets/toc_review_dialog.py:TocReviewDialog._verify":
        "보류 DB 는 배경이 먼저 — 책갈피 검토 창의 대조(저장된 OCR 만 읽음)",
    "viewer/jobs_controller.py:JobsMixin._pending_apply._fn":
        "배경 — `_file_op_bg` 에서 보류 확정·버림과 다시 색인",
    "viewer/jobs_controller.py:_pending_scan_now":
        "배경 — 워커 스레드에서 보류 목록 세기",
    "viewer/app.py:MainWindow._probe_info_cached":
        "이미 있는 파일 — index.db UI 대기 연결(`BUSY_MS_UI`), 한 번 만들어 다시 씀",
    "viewer/app.py:MainWindow._on_files_relocated":
        "이미 있는 파일 — index.db 경로만 고침(UI 대기)",
    "viewer/app.py:MainWindow._startup_index_check":
        "이미 있는 파일 — 시작 뒤 색인이 비었는지(색인 중이면 미룸)",
    "viewer/app.py:MainWindow._autotag_suggest_single":
        "이미 있는 파일 — 태그 제안의 글 읽기(UI 대기)",
}

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def scan(path: Path) -> dict:
    rel = path.relative_to(ROOT).as_posix()
    found = {}

    def visit(node, quals):
        for ch in ast.iter_child_nodes(node):
            q = quals + [ch.name] if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else quals
            what = None
            if isinstance(ch, ast.Call):
                f = ch.func
                nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                recv = ast.unparse(f.value) if isinstance(f, ast.Attribute) else ""
                if nm in ("StudyStore", "PdfIndex"):
                    what = nm + "("
                elif nm == "connect" and recv.split(".")[-1] in ("sqlite3", "dbutil", "_dbutil", "_db"):
                    what = recv + ".connect("
            elif isinstance(ch, ast.Constant) and isinstance(ch.value, str) and "ATTACH " in ch.value.upper():
                what = "ATTACH 글"
            if what:
                found.setdefault("%s:%s" % (rel, ".".join(quals)), []).append("%d %s" % (ch.lineno, what))
            visit(ch, q)
    visit(ast.parse(path.read_text(encoding="utf-8-sig")), [])
    return found


found = {}
for p in MAIN_MODULES:
    found.update(scan(p))
for k in sorted(found):
    print(("허용" if k in ALLOWED else "FAIL"), "-", k, " | ".join(found[k]))
chk(not (set(found) - set(ALLOWED)), "A 메인 스레드 모듈의 DB 열기는 허용 목록(종류 — 까닭)에 있다", sorted(set(found) - set(ALLOWED)))
chk(not (set(ALLOWED) - set(found)), "A 허용 목록에 있지만 이제 없는 곳은 목록에서 지운다", sorted(set(ALLOWED) - set(found)))
chk(all(why.split(" — ")[0] in KINDS for why in ALLOWED.values()), "A 까닭이 정해진 종류로 시작한다")

ss = (V / "study" / "study_store.py").read_text(encoding="utf-8-sig")
fn = next((n for n in ast.walk(ast.parse(ss)) if isinstance(n, ast.FunctionDef) and n.name == "_attach_pending"), None)
src = ast.unparse(fn) if fn else ""
chk("wait_pending_ready()" in src and src.find("wait_pending_ready()") < src.find("ATTACH"),
    "B _attach_pending 이 ATTACH 전에 배경 준비를 기다린다(메인이 보류 파일을 만들지 않게)")
chk("start_pending_prep()" in (ROOT / "main.py").read_text(encoding="utf-8-sig"), "C 앱 진입점이 보류 DB 준비를 띄운다")

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.exit(1 if fails else 0)
