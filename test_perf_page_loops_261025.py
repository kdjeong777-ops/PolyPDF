# -*- coding: utf-8 -*-
"""261025-12: 메인 스레드 모듈에서 문서 **모든 쪽**을 도는 반복을 막는다 — 응답성 SOT §4 ⑥ '쪽 수에 비례하는 일'.

261025-11: 본문 검색(`MainView.set_query` → `PdfDocument.search`)이 열린 문서의 모든 쪽을 메인 스레드에서 훑어 598쪽에서
검색마다 1~2초 섰다. 작은 시험 PDF 로는 안 보이고(쪽 수에 비례) 기능 검사는 통과했다. 같은 종류가 다시 들어오지 않게
메인 스레드 모듈(`MAIN_MODULES`)의 `for` 반복·내포를 AST 로 훑어, 쪽 수에 비례하는 것을 찾는다:
  - `range(...)` 의 인자에 `page_count` 가 있거나, 그 함수 안에서 `X = ….page_count` 로 받은 이름이 있음
  - 문서 객체를 그대로 도는 것(`for page in doc` — 이름이 doc·_doc·…doc 이거나 `.doc` 속성)
찾은 것은 `ALLOWED` 에 **까닭**과 함께 있어야 한다 — 새로 생기면 실패한다. 까닭의 종류는 응답성 SOT §4 ⑥ 의 표.
  보이는 쪽만 / 나눠서(`QTimer`·`_search_step`) / 배경 작업 안에서만 불림 / 쪽마다 값싼 일(목록 만들기·속성 읽기) / 사용자가 고른 일회성 작업(진행 창)
"""
import ast
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
V = ROOT / "viewer"
MAIN_MODULES = [V / "app.py"] + sorted(V.glob("*_controller.py")) + sorted((V / "widgets").glob("*.py"))
DOC_NAMES = {"doc", "_doc", "src_doc", "srcdoc", "newdoc", "pdf", "d"}

# "모듈 경로:함수" → 까닭(응답성 SOT §4 ⑥ 표의 다섯 종류로 시작)
ALLOWED = {
    "viewer/edit_controller.py:EditMixin._apply_drawings_to_pdf":
        "배경 — 안쪽 `_job` 이 `_run_merge_job`(`_MergeThread`)에서 돈다",
    "viewer/edit_controller.py:EditMixin._action_save_decorated_pdf":
        "일회성 작업 — '평탄화해서 내보내기' 를 누를 때 한 번, 쪽마다 크롭 상자만 견준다(598쪽 0.08초, 261025 실측)",
    "viewer/sign_controller.py:SignMixin._sigfield_make":
        "일회성 작업 — 빈 서명 칸을 만들 때 한 번, 쪽마다 양식 칸 이름만 모은다(598쪽 0.02초, 261025 실측)",
    "viewer/widgets/main_view.py:MainView._begin_match_search":
        "값싼 일 — 남은 쪽 번호 목록만 만든다(찾기는 `_search_step` 이 나눠서, 261025-11)",
    "viewer/widgets/presentation.py:PresentationWindow._populate_page_combo":
        "값싼 일 — 쪽 번호·책갈피 이름으로 풀다운 항목만(쪽을 열지 않는다)",
    "viewer/widgets/presentation.py:PresentationWindow._vis_list":
        "값싼 일 — 숨김을 뺀 쪽 번호 목록(파일마다 캐시)",
    "viewer/widgets/presentation.py:_PresThumbPanel.populate":
        "값싼 일 — 빈 목록 항목만, 그림은 첫 쪽 비율 하나만 렌더",
    "viewer/widgets/thumbs_list.py:PageThumbs.load_document":
        "값싼 일 — 빈 목록 항목만, 썸네일은 `_render_visible` 이 보이는 것만(응답성 SOT §4 ⑥)",
}


def _src(node, text):
    # ast.get_source_segment 는 부를 때마다 파일 전체를 줄로 나눠 이 검사가 47초 걸렸다 — 식을 다시 쓰는 것으로 충분하다
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def full_doc_funcs() -> set:
    """메인 밖 모듈(`viewer/` — `_vendor` 제외)에서 문서 모든 쪽을 도는 함수 이름 — 메인에서 문서 객체로 부르면 같은 정지다
    (261025-11 은 반복이 `pdf_doc.py` 의 `search` 에 있었고 메인은 `self._doc.search(...)` 한 줄이었다)."""
    out = set()
    main = {p.resolve() for p in MAIN_MODULES}
    for p in V.rglob("*.py"):
        if "_vendor" in p.parts or p.resolve() in main:
            continue
        text = p.read_text(encoding="utf-8")
        for fn in ast.walk(ast.parse(text)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "range" and \
                        "page_count" in " ".join(_src(x, text) for x in n.args):
                    out.add(fn.name)
                    break
                if isinstance(n, ast.For) and isinstance(n.iter, (ast.Name, ast.Attribute)) and \
                        (getattr(n.iter, "id", None) or getattr(n.iter, "attr", None)) in DOC_NAMES:
                    out.add(fn.name)
                    break
    return out


FULL_DOC = set()


def scan(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    found = {}
    rel = path.relative_to(ROOT).as_posix()

    def visit_func(fn, qual):
        for n in ast.walk(fn):           # 문서 전체를 도는 함수를 문서 객체로 부름(`self._doc.search(q)`)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in FULL_DOC:
                recv = _src(n.func.value, text)
                if "doc" in recv.lower():
                    found.setdefault("%s:%s" % (rel, qual), []).append("%d: %s.%s(…) 부름" % (n.lineno, recv[:40], n.func.attr))
        pc_names = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and "page_count" in _src(n.value, text):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        pc_names.add(t.id)
        for n in ast.walk(fn):
            iters = []
            if isinstance(n, (ast.For, ast.AsyncFor)):
                iters.append(n.iter)
            elif isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                iters += [g.iter for g in n.generators]
            for it in iters:
                s = _src(it, text)
                hit = False
                if isinstance(it, ast.Call) and getattr(it.func, "id", "") == "range":
                    a = " ".join(_src(x, text) for x in it.args)
                    names = {x.id for x in ast.walk(it) if isinstance(x, ast.Name)}
                    hit = "page_count" in a or bool(names & pc_names)
                elif isinstance(it, ast.Name) and it.id in DOC_NAMES:
                    hit = True
                elif isinstance(it, ast.Attribute) and (it.attr in DOC_NAMES):
                    hit = True
                if hit:
                    found.setdefault("%s:%s" % (rel, qual), []).append("%d: %s" % (it.lineno, s[:70]))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for f in node.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_func(f, "%s.%s" % (node.name, f.name))
    top = [f for f in tree.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for f in top:
        visit_func(f, f.name)
    return found


def main() -> int:
    FULL_DOC.update(full_doc_funcs())
    found = {}
    for p in MAIN_MODULES:
        found.update(scan(p))
    fails = []
    for k in sorted(found):
        tag = "허용" if k in ALLOWED else "FAIL"
        print("%s - %s  %s" % (tag, k, " | ".join(found[k])))
        if k not in ALLOWED:
            fails.append(k)
    for k in sorted(set(ALLOWED) - set(found)):
        print("FAIL - 허용 목록에 있지만 이제 없는 반복(목록에서 지운다): %s" % k)
        fails.append(k)
    bad = [k for k, why in ALLOWED.items() if not why.split(" — ")[0] in KINDS]
    for k in bad:
        print("FAIL - 까닭이 응답성 SOT §4 ⑥ 의 종류로 시작하지 않는다: %s" % k)
    fails += bad
    print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
    return 1 if fails else 0


KINDS = {"보이는 쪽만", "나눠서", "배경", "값싼 일", "일회성 작업"}

if __name__ == "__main__":
    sys.exit(main())
