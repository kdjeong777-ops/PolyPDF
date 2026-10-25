# -*- coding: utf-8 -*-
"""261010-4: 릴리스 시험 등급 판정(`release_test.classify`)과 기준점 비교(`compare`) — 릴리스 SOT §3·§7.

git 없이 바뀐 파일 목록과 diff 글을 직접 넣어, 경로·줄 규칙이 등급을 바르게 내는지 본다.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
import release_test as rt  # noqa: E402

fails = []


def chk(ok, msg, detail=""):
    print(("PASS - " if ok else "FAIL - ") + msg + (" " + str(detail) if detail and not ok else ""))
    if not ok:
        fails.append(msg)


def diff(path, *lines, head=""):
    return "\n".join(["diff --git a/%s b/%s" % (path, path), "--- a/" + path, "+++ b/" + path,
                      "@@ -1,1 +1,1 @@ " + head, *lines]) + "\n"


# A. 설치 관련 경로 → 설치 시험
c = rt.classify([("M", "installer/PolyPDF.iss", 3)], diff("installer/PolyPDF.iss", "+x"))
chk(c["level"] == "install", "A 설치 프로그램을 바꾸면 설치 시험", c)
c = rt.classify([("M", ".github/workflows/release.yml", 2)], "")
chk(c["level"] == "install", "A 릴리스 워크플로도 설치 시험", c)
# 261017-18 점검: 가상 프린터 설치 도구·동봉 파일은 설치 끝에 설치 프로그램이 부른다 — 빌드 시험으로 판정하던 빈칸
for p in ("viewer/vprinter.py", "printer/POLYPDF.PPD", "printer/monitor_src/monitor/portlist.cpp"):
    c = rt.classify([("M", p, 2)], diff(p, "+x"))
    chk(c["level"] == "install", "A 가상 프린터 설치 경로(%s)도 설치 시험" % p, c)

# B. 문서·검사·번역문만 → 생략 후보
c = rt.classify([("M", "README.md", 10), ("M", "test_foo.py", 50), ("M", "resources/locale/en/LC_MESSAGES/polypdf.po", 8)], "")
chk(c["level"] == "skip", "B 문서·검사·번역문만이면 생략 후보", c)

# C. 작은 UI 수정 → 생략 후보, 큰 수정 → 빌드 시험
c = rt.classify([("M", "viewer/widgets/search_panel.py", 6)], diff("viewer/widgets/search_panel.py", "+    btn.setText(tr('찾기'))"))
chk(c["level"] == "skip", "C 작은 화면 문구 수정은 생략 후보", c)
c = rt.classify([("M", "viewer/widgets/search_panel.py", rt.SMALL_LINES)], "")
chk(c["level"] == "build", "C 바뀐 줄이 SMALL_LINES 이상이면 빌드 시험", c)
c = rt.classify([("M", "viewer/a.py", 1), ("M", "viewer/b.py", 1), ("M", "viewer/c.py", 1), ("M", "viewer/d.py", 1)], "")
chk(c["level"] == "build", "C 코드 파일이 3개를 넘으면 빌드 시험", c)

# D. 필수 경로·새 모듈·배경 작업 줄·app.py 시작 함수 → 빌드 시험
c = rt.classify([("M", "viewer/index_proc.py", 2)], "")
chk(c["level"] == "build" and any("T5" in (k or "") for _, k in c["focus"]),
    "D 색인 자식을 바꾸면 빌드 시험 + T5·T6 항목", c)
c = rt.classify([("A", "viewer/new_mod.py", 5)], "")
chk(c["level"] == "build", "D 새 모듈은 빌드 시험", c)
c = rt.classify([("M", "viewer/widgets/strip.py", 2)], diff("viewer/widgets/strip.py", "+        QTimer.singleShot(0, self._x)"))
chk(c["level"] == "build", "D 타이머 줄을 더하면 빌드 시험", c)
c = rt.classify([("M", "viewer/app.py", 2)], diff("viewer/app.py", "+        self.x = 1", head="    def __init__(self):"))
chk(c["level"] == "build", "D app.py 의 __init__ 을 건드리면 빌드 시험", c)
c = rt.classify([("M", "viewer/app.py", 2)], diff("viewer/app.py", "+        self.x = 1", head="    def action_zoom(self):"))
chk(c["level"] == "skip", "D app.py 의 다른 처리기 작은 수정은 생략 후보", c)

# E. 저장 경로 줄 → 저장 손 확인 항목
c = rt.classify([("M", "viewer/app.py", 3)], diff("viewer/app.py", "+        self._finalize_save(p)", head="    def action_save(self):"))
chk(any("저장" in w for w, _ in c["focus"]), "E 저장 경로 줄이 있으면 저장 확인 항목", c["focus"])

# F. 기준점 비교 — 20% 넘게 나빠진 값만, 절대 하한 아래 잡음은 무시
base = {"runs": [{"name": "T1", "t_window": 3.0, "peak_ws_mb": 300, "indexed_files": 1000},
                 {"name": "T2", "t_window": 0.5, "peak_ws_mb": 300, "indexed_files": 100}]}
now = {"runs": [{"name": "T1", "t_window": 4.0, "peak_ws_mb": 320, "indexed_files": 700},
                {"name": "T2", "t_window": 0.8, "peak_ws_mb": 300, "indexed_files": 95}]}
r = rt.compare(now, base)
chk(any(x.startswith("T1 창") for x in r) and any(x.startswith("T1 색인한 파일") for x in r),
    "F 창 시간 +33%·색인 파일 -30% 는 회귀 의심", r)
chk(not any(x.startswith("T1 작업 집합") for x in r), "F 작업 집합 +7% 는 아니다", r)
chk(not any(x.startswith("T2") for x in r), "F 절대 하한 아래(0.3초·5개)는 잡음으로 본다", r)

# G. 261010-15: 비교는 같은 종류(build|install) 시험끼리 — 설치본을 빌드본과 견주면 '회귀 의심' 이 과했다
import json, tempfile
from pathlib import Path
_old = rt.BASELINE
try:
    rt.BASELINE = Path(tempfile.mkdtemp()) / "baseline.json"
    rt.save_baseline({"commit": "a", "version": "1", "mode": "build", "source": "local"}, Path("build_1"))
    rt.save_baseline({"commit": "b", "version": "2", "mode": "install", "source": "ci"}, Path("install_2"))
    bl = rt.load_baseline()
    chk(rt.compare_base(bl, "build") == "build_1" and rt.compare_base(bl, "install") == "install_2",
        "G 종류마다 마지막 통과 결과를 따로 둔다", str(bl.get("results")))
    chk(bl["commit"] == "b", "G 기준점 커밋은 마지막 통과(종류 무관)")
    chk(rt.compare_base({"mode": "build", "result": "build_0"}, "install") is None,
        "G 옛 기준점(종류별 기록 없음)은 다른 종류와 견주지 않는다")
finally:
    rt.BASELINE = _old

# H. 261025-12(릴리스 SOT §2.3): 새 버전이 이미 낸 가장 높은 태그보다 높지 않으면 plan 이 멈춘다 — 0.6·0.5 지시가 0.45.0-beta.N 보다 작았다
TAGS = ["v0.45.0-beta.297", "v0.45.0-beta.298", "components", "v0.45.0-beta.99"]
chk(rt.version_order_problem("0.5.0", TAGS) != "", "H 0.5.0 은 0.45.0-beta.298 보다 낮다 — 멈춤")
chk(rt.version_order_problem("0.6.0", TAGS) != "", "H 0.6.0 도 낮다(0.6 < 0.45)")
chk(rt.version_order_problem("0.45.0-beta.298", TAGS) != "", "H 이미 낸 번호와 같으면 멈춤")
chk(rt.version_order_problem("1.0.0", TAGS) == "", "H 1.0.0 은 통과")
chk(rt.version_order_problem("1.0.0-beta.3", TAGS + ["v1.0.0"]) != "", "H 정식 뒤 같은 번호의 베타는 낮다 — 멈춤(§2.3 다음 정식-beta.N)")
chk(rt.version_order_problem("1.1.0-beta.1", TAGS + ["v1.0.0"]) == "", "H 1.0.0 뒤 1.1.0-beta.1 은 통과")
chk(rt.version_order_problem("1.0.0", ["v0.45.0-beta.298", "v2.41.0"]) != "", "H 가장 가까운 태그가 아니라 가장 높은 태그와 견준다")

# I. 261025-12(릴리스 SOT §4.3 의 8): 측정이 다른 무거운 작업과 겹쳤는지 — 겹치면 판정 보류·기준점 그대로
import overlap  # noqa: E402
PS = [(1, 0, "claude.exe"), (10, 1, "powershell.exe"), (20, 10, "python.exe"),      # 20 = 이 측정
      (21, 20, "PolyPDF.exe"), (22, 21, "python.exe"),                                 # 잰 앱과 도우미
      (11, 1, "powershell.exe"), (30, 11, "python.exe")]                               # 30 = 같은 셸 아래 다른 세션의 검사
mine = overlap._tree(PS, 20)
chk({20, 21, 22, 10, 1} <= mine and 30 not in mine, "I 조상의 다른 자손(다른 세션의 검사)은 남으로 본다", sorted(mine))
w = overlap.Watch(root=20)
w._others = lambda: {30: ("python.exe", 0.0)}
w.start_busy, w._last = 5.0, (0.0, {30: ("python.exe", 0.0)})
import time as _time  # noqa: E402
w._last = (_time.time() - 10, {30: ("python.exe", 0.0)})
w._others = lambda: {30: ("python.exe", 8.0)}                  # 10초에 8초 = 0.8코어
chk(w.check("T5") and w.overlapped, "I 다른 무거운 프로세스가 OVERLAP_CORES 넘게 쓰면 겹침")
w2 = overlap.Watch(root=20)
w2.start_busy, w2._last = 5.0, (_time.time() - 10, {30: ("python.exe", 0.0)})
w2._others = lambda: {30: ("python.exe", 0.5)}                 # 0.05코어 — 쉬는 프로세스
chk(not w2.check("T5") and not w2.overlapped, "I 쉬는 다른 프로세스는 겹침이 아니다")
src = (ROOT / "scripts" / "release_test.py").read_text(encoding="utf-8")
chk('not rec.get("overlapped")' in src.split("def main")[1].split("save_baseline(rec")[0],
    "I 겹친 시험은 기준점을 옮기지 않는다(save_baseline 앞의 조건)")

print("\n=== ALL PASS ===" if not fails else "\n%d FAIL" % len(fails))
sys.exit(1 if fails else 0)
