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

print("\n=== ALL PASS ===" if not fails else "\n%d FAIL" % len(fails))
sys.exit(1 if fails else 0)
