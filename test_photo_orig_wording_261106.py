# -*- coding: utf-8 -*-
"""사진 원본 처리 안내 문구가 지금 규칙과 맞는다 (사진 보기 SOT §4.43·§4.17, 261106-22 재발 방지).

261106-15 에 펴기 [저장] 이 '원본 대체(원본은 백업 폴더로)' 로 바뀌었는데 크롭 창 (?) 도움말은 '새 사진으로 저장(원본은 그대로)' 로
남았다 — 규칙이 바뀌어도 문구를 보는 검사가 없었다. 원본을 바꾸는 사진 작업(방향 저장·모양 펴기 [저장]·원본으로 되돌리기)을 말하는
화면 문구에 '원본은 그대로' 가 있으면, 그것이 **어느 갈래**의 말인지(다른 이름·다른 폴더·새 파일·실패·취소) 함께 적혀 있어야 한다.
A. 사진 모듈의 tr() 문구 — 위 규칙
B. 크롭 창 모양 펴기 도움말 — [저장] 이 원본을 바꾸고 원본은 백업으로 간다고 알린다(사진 SOT §4.43 의 '[저장] = 원본 대체' 와 같게)
"""
import ast, os, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


OPS = ("펴기", "펼친", "펼쳐", "방향 저장", "방향을 저장", "되돌리")          # 원본을 바꾸는 사진 작업
KEPT = ("원본은 그대로", "원본 그대로")
BRANCH = ("다른 이름", "다른 폴더", "새 파일", "못", "취소")                   # 원본을 건드리지 않는 갈래·실패


def tr_strings(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) in ("tr", "trp", "trn", "tr_noop") and n.args:
            a = n.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                yield n.lineno, a.value


files = sorted(set((HERE / "viewer").glob("photo_*.py")) | set((HERE / "viewer" / "widgets").glob("photo_*.py")))
bad = []
for f in files:
    for ln, s in tr_strings(f):
        if any(k in s for k in OPS) and any(k in s for k in KEPT) and not any(k in s for k in BRANCH):
            bad.append("%s:%d %s" % (f.name, ln, s[:90]))
chk(files and not bad, "A 원본을 바꾸는 작업 문구의 '원본은 그대로' 는 갈래(다른 이름·다른 폴더·새 파일·실패·취소)를 함께 적는다",
    "\n  " + "\n  ".join(bad))

dlg = HERE / "viewer" / "widgets" / "photo_crop_dialog.py"
helps = [s for _ln, s in tr_strings(dlg) if s.startswith("꼭짓점(네모)")]
chk(helps and all("백업" in s and "[저장]" in s for s in helps), "B 크롭 창 모양 펴기 도움말 — [저장] 은 원본을 바꾸고 원본은 백업으로", str(helps))
sot = HERE.parent / "사진 보기(PolyPix) 작업 계획서.md"
if sot.exists():
    chk("**[저장] = 원본 대체**" in sot.read_text(encoding="utf-8"), "B 사진 SOT §4.43 규칙이 '[저장] = 원본 대체' 다(규칙이 바뀌면 이 검사도 함께)")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
