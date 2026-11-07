# -*- coding: utf-8 -*-
"""261107-20(디자인 SOT §2.7 '단추·메뉴 글 끝에 … 를 붙이지 않는다', 261107-12 결정의 재발 방지).

메뉴 항목·단추 글자가 '…' 또는 '...' 로 끝나면 실패한다. 261107-12 에 앱 전체에서 뗐는데도 점검(261107)에서
열몇 곳이 다시 나왔다 — 사람이 기억해서 막을 일이 아니라 검사로 고정한다.

검사 대상(소스 글 — 화면을 띄우지 않는다): `viewer/` 아래 .py 의 다음 호출의 **첫 인자 식 안의 글 상수**
  `addAction(` · `QAction(` · `QPushButton(` · `QToolButton(` · `addButton(` · `addMenu(` · `QMenu(`
  — 첫 인자가 글 상수(`"…"`) 그 자체이거나, 그 식 안의 `tr("…")`·`trp(문맥, "…")` 전부(조건식 `tr(a) if c else tr(b)` 의 두 갈래도).
  261107-24: 종전에는 첫 인자가 `tr(…)` 로 **시작할 때만** 봐 조건식 둘째 갈래('표지·목차·간지 Word 양식 샘플 저장…')를 놓쳤다.
규칙:
  ① 글이 '…'·'...' 로 **끝나면** 실패 — 문장 속 말줄임('…중… 기다림')은 끝이 아니므로 통과
  ② 진행 상태 글(끝이 '중…'·'중...', 예: '읽는 중…')은 단추·메뉴 이름이 아니라 상태 표시라 제외
  ③ 변수만 넘기는 꼴(`addAction(label)`)·목록에서 꺼내 쓰는 꼴은 보지 않는다(이 검사가 읽을 수 없다)
수정 전 코드(261107-20 앞)로 실패한다 — '사용자 크기 설정...' 등. 조건식 갈래는 261107-24 앞 코드로 실패한다.
"""
import io, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))

CALL = re.compile(r'(?:\.addAction|\bQAction|\bQPushButton|\bQToolButton|\.addButton|\.addMenu|\bQMenu)\(')
STR = r'(["\'])((?:(?!\1)[^\\\n]|\\.)*)\1'          # 무리 1 = 따옴표, 2 = 글
TR_LIT = re.compile(r'(?:\b(?:tr|_tr)\(|\btrp\(\s*"(?:[^"\\]|\\.)*"\s*,)\s*' + STR + r'\s*\)')
PLAIN = re.compile(r'^\s*' + STR + r'\s*$')


def first_arg(src, i):
    """`(` 바로 뒤 i 부터 첫 인자 식(최상위 `,` 또는 닫는 `)` 앞까지) — 글 상수 속 괄호·쉼표는 건너뛴다."""
    depth, j, q = 0, i, None
    while j < len(src):
        c = src[j]
        if q:
            if c == "\\":
                j += 2
                continue
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return src[i:j]
            depth -= 1
        elif c == "," and depth == 0:
            return src[i:j]
        j += 1
    return src[i:]


def labels(arg):
    m = PLAIN.match(arg)
    if m:
        return [m.group(2)]
    return [m.group(2) for m in TR_LIT.finditer(arg)]


class _M:                                    # scan() 이 쓰는 꼴 — (시작 자리, 글)
    def __init__(self, start, s):
        self._start, self._s = start, s

    def start(self):
        return self._start

    def group(self, _name):
        return self._s


def matches(src):
    for m in CALL.finditer(src):
        for s in labels(first_arg(src, m.end())):
            yield _M(m.start(), s)


def scan():
    bad = []
    for dp, _dn, fns in os.walk(os.path.join(ROOT, "viewer")):
        if "__pycache__" in dp or "_vendor" in dp:
            continue
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dp, fn)
            src = io.open(p, encoding="utf-8").read()
            for m in matches(src):
                s = m.group("s").rstrip()
                if not (s.endswith("…") or s.endswith("...")):
                    continue
                if re.search(r"중\s*(…|\.\.\.)$", s):                 # ② 진행 상태 글
                    continue
                line = src.count("\n", 0, m.start()) + 1
                bad.append("%s:%d %s" % (os.path.relpath(p, ROOT).replace("\\", "/"), line, s))
    return bad


bad = scan()
print(("PASS" if not bad else "FAIL"), "- 메뉴·단추 글 끝에 '…'·'...' 없음(디자인 SOT §2.7)", "" if not bad else "\n  " + "\n  ".join(bad))
# 검사가 정말 읽는지 — 알려진 꼴을 넣어 본다(정규식이 빈 검사가 되지 않게)
probe = ['a = m.addAction(tr("설정..."))', 'QPushButton("새 뜻…")', 'b.addButton(trp("메뉴", "열기…"), r)',
         'QPushButton(tr("하나") if x else tr("둘…"))']                     # 261107-24: 조건식 갈래
ok_probe = all(any(m.group("s").endswith(("…", "...")) for m in matches(t)) for t in probe)
print(("PASS" if ok_probe else "FAIL"), "- 검사 정규식이 알려진 꼴을 잡는다")
fails = (1 if bad else 0) + (0 if ok_probe else 1)
print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({fails})") + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
