# -*- coding: utf-8 -*-
"""261031-3(디자인 SOT §2.9 '처리기 인자'): `triggered`·`clicked`·`toggled` 에 **선택 인자를 가진 처리기**를 바로 잇지 않는다.

이 신호들은 `checked`(bool)를 넘긴다. 처리기의 첫 인자에 기본값이 있으면(`action_sign_pdf(self, at_scene=None)`) PyQt 가 그
자리에 `False` 를 넣는다 — 261031-1 도구 메뉴·리본 '전자서명 ▸ 서명...' 이 `QRectF(False, False)` TypeError 로 아무것도 안 했다
(error.log 4회). 받는 쪽은 `lambda: self.f()`·`app._no_checked(f)` 로 감싸거나, 첫 인자를 `checked` 로 받는다.

정적 검사(AST) — 실제 연결을 따라간다: `x.triggered.connect(self.f)` 뿐 아니라 반복문 튜플(`for cid, text, slot in (…)`)의 자리와
지역 도우미(`def _act(text, slot, …): a.triggered.connect(slot)` 의 호출 `_act(…, self.f, …)`)까지 본다.
처리기 첫 인자(self 다음)가 기본값을 가지고 이름이 `checked`·`on` 류가 아니면 위반. 까닭이 있는 예외는 `ALLOW` 에 적는다.
"""
import ast, os, sys
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

ROOT = Path(os.environ.get("POLYPDF_CODE_ROOT") or os.path.dirname(os.path.abspath(__file__)))   # 수정 전 코드로 돌릴 때 바꾼다
SIGNALS = {"triggered", "clicked", "toggled"}
OK_NAMES = {"checked", "_checked", "on", "state", "flag", "enabled", "visible", "checked_", "_", "_c", "_on", "c", "b", "val", "value"}
# (파일 이름, 처리기 이름): 까닭 — 기본값 인자를 일부러 checked 로 받는 것
ALLOW = {}
# 찾았지만 그 파일을 다른 세션이 고치는 중이라 아직 못 고친 것 — 고치면 여기서 뺀다(남아 있는데 고쳐졌으면 실패, 목록은 줄기만).
#   app.py 인쇄: checked(False) 가 preset_scope 로 — 지금은 'current'·'thumb' 가 아니라 None 처럼 동작(261031-3 보고, 서명 세션 몫)
PENDING = {("app.py", "action_print")}
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


files = [p for p in (ROOT / "viewer").rglob("*.py") if "__pycache__" not in p.parts and "_vendor" not in p.parts]
trees = {p: ast.parse(p.read_text(encoding="utf-8"), str(p)) for p in files}

# 메서드·함수 색인: 이름 → [(파일, 첫 인자 이름, 기본값 있음)]
defs = {}
for p, t in trees.items():
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            pos = a.posonlyargs + a.args
            is_method = bool(pos) and pos[0].arg in ("self", "cls")
            ps = pos[1:] if is_method else pos
            if not ps:
                defs.setdefault(n.name, []).append((p.name, None, False))
                continue
            n_def = len(a.defaults)
            first_has_default = (len(pos) - n_def) <= pos.index(ps[0])
            defs.setdefault(n.name, []).append((p.name, ps[0].arg, first_has_default))


def bad_target(name):
    """그 이름의 정의가 모두 '첫 인자 기본값·checked 아닌 이름' 이면 위반(정의가 없으면 모른다 — 넘어간다)."""
    ds = defs.get(name) or []
    return bool(ds) and all(has and arg not in OK_NAMES for _f, arg, has in ds), ds


def self_attr(e):
    return e.attr if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == "self" else None


def candidates(expr, func, outer):
    """연결 인자 → 처리기 이름 후보. self.f · 반복문 튜플 자리 · 지역 도우미의 매개변수(바깥 함수의 호출 인자)."""
    a = self_attr(expr)
    if a:
        return [a]
    if isinstance(expr, ast.Name):
        v, out = expr.id, []
        params = [x.arg for x in func.args.args]

        def call_args(pname):
            """지역 도우미 func 의 매개변수 pname 에 들어온 호출 인자들(바깥 함수에서)."""
            if outer is None or pname not in params:
                return []
            k, got = params.index(pname), []
            for c in ast.walk(outer):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == func.name:
                    if k < len(c.args):
                        got.append(c.args[k])
                    got += [kw.value for kw in c.keywords if kw.arg == pname]
            return got

        for n in ast.walk(func):                                   # for (…, v, …) in ((…, self.f, …), …)
            if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple):
                names = [x.id if isinstance(x, ast.Name) else None for x in n.target.elts]
                if v not in names:
                    continue
                i = names.index(v)
                seqs = [n.iter] if isinstance(n.iter, (ast.Tuple, ast.List)) else []
                if isinstance(n.iter, ast.Name):                    # for _t, _s in items — items 는 도우미의 매개변수(_sub)
                    seqs += [x for x in call_args(n.iter.id) if isinstance(x, (ast.Tuple, ast.List))]
                for seq in seqs:
                    for row in seq.elts:
                        if isinstance(row, (ast.Tuple, ast.List)) and i < len(row.elts):
                            out += [x for x in [self_attr(row.elts[i])] if x]
        if v in params and outer is not None:                       # def _act(text, slot, …) 의 slot
            i = params.index(v)
            for n in ast.walk(outer):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == func.name:
                    if i < len(n.args):
                        out += [x for x in [self_attr(n.args[i])] if x]
                    for kw in n.keywords:
                        if kw.arg == v:
                            out += [x for x in [self_attr(kw.value)] if x]
        return out
    return []


bad, pending_seen = [], set()
for p, t in trees.items():
    def visit(node, outer=None):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scan(ch, node if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None)
                visit(ch, ch)
            else:
                visit(ch, outer)

    def scan(func, outer):
        for n in ast.walk(func):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "connect" and n.args):
                continue
            sig = n.func.value
            if not (isinstance(sig, ast.Attribute) and sig.attr in SIGNALS):
                continue
            for name in candidates(n.args[0], func, outer):
                isbad, ds = bad_target(name)
                if isbad and (p.name, name) not in ALLOW:
                    if (p.name, name) in PENDING:
                        pending_seen.add((p.name, name))
                        continue
                    bad.append("%s:%d %s.%s → %s(%s=…)" % (p.name, n.lineno, sig.attr, "connect", name, ds[0][1]))
    visit(t)

bad = sorted(set(bad))
for b in bad:
    print("   ", b)
chk(not bad, "triggered·clicked·toggled 에 첫 인자가 기본값인 처리기를 바로 잇지 않는다(lambda·_no_checked 로)", "%d건" % len(bad))
chk(all(isinstance(v, str) and v for v in ALLOW.values()), "ALLOW 에는 까닭을 적는다")
chk(not (PENDING - pending_seen), "고친 것은 PENDING 에서 뺀다", str(sorted(PENDING - pending_seen)))

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
