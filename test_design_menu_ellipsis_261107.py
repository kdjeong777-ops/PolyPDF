# -*- coding: utf-8 -*-
"""261107-20(디자인 SOT §2.7 '단추·메뉴 글 끝에 … 를 붙이지 않는다', 261107-12 결정의 재발 방지).

메뉴 항목·단추 글자가 '…' 또는 '...' 로 끝나면 실패한다. 261107-12 에 앱 전체에서 뗐는데도 점검(261107)에서
열몇 곳이 다시 나왔다 — 사람이 기억해서 막을 일이 아니라 검사로 고정한다.

검사 대상(소스 글 — 화면을 띄우지 않는다): `viewer/` 아래 .py 의 다음 호출 **첫 인자**가 글 상수(`"…"`) 이거나 `tr("…")`·`trp(문맥, "…")` 일 때
  `addAction(` · `QAction(` · `QPushButton(` · `QToolButton(` · `addButton(` · `addMenu(` · `QMenu(`
규칙:
  ① 글이 '…'·'...' 로 **끝나면** 실패 — 문장 속 말줄임('…중… 기다림')은 끝이 아니므로 통과
  ② 진행 상태 글(끝이 '중…'·'중...', 예: '읽는 중…')은 단추·메뉴 이름이 아니라 상태 표시라 제외
  ③ 변수·f-글·글 이어 붙이기(`tr(a) + b`)처럼 첫 인자가 글 상수가 아니면 보지 않는다(이 검사가 읽을 수 없다)
수정 전 코드(261107-20 앞)로 실패한다 — '사용자 크기 설정...' 등.
"""
import io, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))

CALL = re.compile(r'(?:\.addAction|\bQAction|\bQPushButton|\bQToolButton|\.addButton|\.addMenu|\bQMenu)\(\s*'
                  r'(?:(?:tr|_tr)\(\s*|trp\(\s*"(?:[^"\\]|\\.)*"\s*,\s*)?'
                  r'(?P<q>["\'])(?P<s>(?:(?!(?P=q))[^\\\n]|\\.)*)(?P=q)\s*(?P<after>[),])')


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
            for m in CALL.finditer(src):
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
probe = ['a = m.addAction(tr("설정..."))', 'QPushButton("새 뜻…")', 'b.addButton(trp("메뉴", "열기…"), r)']
ok_probe = all(CALL.search(t) and CALL.search(t).group("s").endswith(("…", "...")) for t in probe)
print(("PASS" if ok_probe else "FAIL"), "- 검사 정규식이 알려진 꼴을 잡는다")
fails = (1 if bad else 0) + (0 if ok_probe else 1)
print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({fails})") + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
