# -*- coding: utf-8 -*-
"""261010-4: 릴리스 시험 등급 판정(`release_test.classify`)과 기준점 비교(`compare`) — 릴리스 SOT §3·§7.

git 없이 바뀐 파일 목록과 diff 글을 직접 넣어, 경로·줄 규칙이 등급을 바르게 내는지 본다.
"""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"        # O 의 시작 스크립트 시험이 Qt 를 쓴다(검사 작성 SOT §14.7)
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
chk(rt.version_order_problem("1.0.0-beta.3", TAGS + ["v1.0.0"]) != "", "H 정식 뒤 같은 번호의 베타는 낮다 — 멈춤(§2.3 나갈 정식 번호-beta.N)")
chk(rt.version_order_problem("1.1.0-beta.1", TAGS + ["v1.0.0"]) == "", "H 1.0.0 뒤 기능 묶음 베타 1.1.0-beta.1 은 통과")
chk(rt.version_order_problem("1.0.1", TAGS + ["v1.0.0"]) == "", "H 1.0.0 뒤 버그 수정 정식 1.0.1 은 통과(261026-3)")
chk(rt.version_order_problem("1.0.0", ["v0.45.0-beta.298", "v2.41.0"]) != "", "H 가장 가까운 태그가 아니라 가장 높은 태그와 견준다")

# H2. 261026(261025-12 보완): 견주는 목록은 updater 와 같은 **지금 있는 GitHub 릴리스**(초안 제외) — 6월 옛 체계의 `v2.41.0` 은
#   태그만 남고 릴리스는 지워져 앱 안 업데이트에 보이지 않는데, git 태그로 견주던 plan 이 1.0.0 을 '거꾸로' 로 멈췄다(오탐).
_gh, _git = rt.gh, rt.git
try:
    rt.git = lambda *a: "v0.45.0-beta.298\nv2.41.0\nv0.45.0-beta.297\n" if a[:2] == ("tag", "--list") else _git(*a)
    rt.gh = lambda *a: json.dumps([{"tagName": "v0.45.0-beta.298", "isDraft": False},
                                   {"tagName": "v0.45.0-beta.293", "isDraft": True},
                                   {"tagName": "v9.0.0", "isDraft": True},
                                   {"tagName": "components", "isDraft": False}])
    tags, src = rt.released_tags()
    chk("v2.41.0" not in tags and "v9.0.0" not in tags and src.startswith("GitHub"),
        "H2 릴리스 목록(초안 제외)으로 견준다 — 태그만 남은 v2.41.0·초안 v9.0.0 은 빠진다", (tags, src))
    chk(rt.version_order_problem("1.0.0", tags) == "", "H2 1.0.0 은 지금 있는 릴리스보다 높다 — 멈추지 않는다")

    def _fail(*a):
        raise SystemExit("gh 실패")
    rt.gh = _fail
    tags, src = rt.released_tags()
    chk("v2.41.0" in tags and src.startswith("git"), "H2 릴리스 목록을 못 받으면 git 태그로 물러선다(그때는 v2.41.0 이 멈춤 사유)", src)
finally:
    rt.gh, rt.git = _gh, _git

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
chk('not rec.get("regress")' in src.split("def main")[1].split("save_baseline(rec")[0],
    "I 회귀 의심이 있는 시험은 통과여도 기준점을 옮기지 않는다(261026-6 보완 — 느린 T6 결과가 기준점이 됐다)")

# J. 261025-12 보완(사용자 결정): 판정은 다른 무거운 프로세스로만 — 평소 부하(이 PC 37% 안팎)로 '보류' 하지 않는다.
#   실제 값: 설치 시험 2120 시작 전 45.7%·2201 46.8%, 대상마다 다른 무거운 프로세스 0 → 종전 규칙(40%)은 둘 다 보류(수정 전 실패).
#   빌드 시험 1607 은 다른 세션의 검사가 함께 돌았다 → 다른 python 이 한 코어 가까이 → 보류여야 한다.
_busy_orig = overlap.system_busy_pct
try:
    for name, busy in (("2120", 45.7), ("2201", 46.8)):
        overlap.system_busy_pct = lambda sec=1.0, b=busy: b
        w = overlap.Watch(root=20)
        w._others = lambda: {}
        w.start()
        w.check("T1"); w.check("T6")
        chk(not w.overlapped, "J 설치 시험 %s(시작 전 %.1f%%, 다른 무거운 프로세스 없음)는 보류가 아니다" % (name, busy), w.events)
    overlap.system_busy_pct = lambda sec=1.0: 13.3
    w = overlap.Watch(root=20)
    w._others = lambda: {30: ("python.exe", 0.0)}
    w.start()
    w._last = (_time.time() - 60, {30: ("python.exe", 0.0)})
    w._others = lambda: {30: ("python.exe", 55.0)}             # 60초에 55초 — 다른 세션의 검사
    chk(w.check("T5") and w.overlapped, "J 빌드 시험 1607 꼴(다른 python 이 한 코어 가까이)은 보류")
    chk(not hasattr(overlap, "CPU_BUSY_PCT"), "J 시스템 CPU 한도 상수가 없다(판정에 쓰지 않는다)")
finally:
    overlap.system_busy_pct = _busy_orig

# K. 261026-4(릴리스 SOT §4.5.1): 끝자리 패치 정식판은 바뀐 곳에 맞춘 줄인 점검 — soak·프린터 설치·부하는 닿을 때만
chk(rt.is_stable_patch("1.0.1") and not rt.is_stable_patch("1.1.0") and not rt.is_stable_patch("1.0.1-beta.1")
    and not rt.is_stable_patch("1.0.0"), "K 끝자리 패치 정식 판별(1.0.1 예, 1.1.0·1.0.0·베타 아니오)")
pc = rt.patch_checks([("M", "viewer/convert/docx_writer.py", 30), ("A", "viewer/progress_text.py", 40)],
                     diff("viewer/convert/docx_writer.py", "+    doc.add_paragraph(t)"))
chk(pc == {"soak": "", "vprinter": "", "load": ""}, "K 변환 코드만 바뀐 패치 — soak·프린터·부하 건너뜀", pc)
pc = rt.patch_checks([("M", "viewer/convert_controller.py", 5)],
                     diff("viewer/convert_controller.py", "+        QTimer.singleShot(0, self._tick)"))
chk(pc["soak"] and pc["load"] and not pc["vprinter"], "K 타이머 줄을 바꾸면 soak·부하", pc)
pc = rt.patch_checks([("M", "installer/PolyPDF.iss", 2)], diff("installer/PolyPDF.iss", "+x"))
chk(pc["vprinter"] and not pc["soak"], "K 설치 프로그램을 바꾸면 프린터 설치 확인", pc)
pc = rt.patch_checks([("M", "viewer/app.py", 3)], diff("viewer/app.py", "+        x = 1", head="def closeEvent(self, e):"))
chk(pc["soak"] and not pc["load"], "K app.py 시작·종료 함수 → soak", pc)
pc = rt.patch_checks([("M", "viewer/widgets/bookmark_tree.py", 3)], diff("viewer/widgets/bookmark_tree.py", "+x"))
chk(pc["soak"] and pc["load"], "K 책갈피 트리 → soak·부하", pc)
_ch = rt._changes
try:
    rt._changes = lambda base: ([("M", "viewer/convert/docx_writer.py", 30)], diff("viewer/convert/docx_writer.py", "+x"))
    txt = "\n".join(rt.stable_lines("1.0.1", "v1.0.0"))
    chk("§4.5.1" in txt and "건너뜀" in txt and "checks --ui" in txt and "fresh" in txt,
        "K plan 이 패치 정식판에 줄인 점검 목록(늘 할 것 + 건너뛸 것)을 낸다", txt)
    chk("§4.5 전부" in "\n".join(rt.stable_lines("1.1.0", "v1.0.0")), "K 기능 묶음 정식은 §4.5 전부")
    chk("§4.5 전부" in "\n".join(rt.stable_lines("1.0.1", "")), "K 앞선 릴리스 태그가 없으면 전부")
    chk(rt.stable_lines("1.0.1-beta.1", "v1.0.0") == [], "K 베타는 정식판 목록을 내지 않는다")
finally:
    rt._changes = _ch

# L. 261026-4: 크래시 근거를 잡음과 가른다 — ① crash.log 는 faulthandler 가 처리되는 첫 기회 SEH(COM/RPC 0x8007xxxx)까지 적어
#   1.0.0 설치본 Word 변환 중 4건이 '치명' 으로 보였다 ② 검사가 ALL PASS 뒤 종료 때 Qt 소멸로 죽으면 종료 코드 0 이지만 오류 보고에 남는다
import stable_check  # noqa: E402
chk(not stable_check.is_fatal_line("Windows fatal exception: code 0x800706be")
    and not stable_check.is_fatal_line("Windows fatal exception: code 0x800706ba"),
    "L COM/RPC 첫 기회 예외(0x800706be·ba)는 치명이 아니다")
chk(all(stable_check.is_fatal_line(s) for s in ("Windows fatal exception: access violation",
                                                "Windows fatal exception: code 0xc0000409",
                                                "Fatal Python error: Segmentation fault")),
    "L 접근 위반·스택 버퍼·Fatal Python error 는 치명")
_tmp = Path(tempfile.mkdtemp()) / "crash.log"
_tmp.write_text("=== 시작 2026-10-26 03:33:13 pid=1\nWindows fatal exception: code 0x800706be\n"
                "=== 시작 2026-10-26 05:00:00 pid=2\nWindows fatal exception: access violation\n", encoding="utf-8")
chk(len(stable_check.crash_entries(_tmp, "2026-10-26 00:00:00")) == 1
    and len(stable_check.crash_entries(_tmp, "2026-10-26 00:00:00", fatal=False)) == 1,
    "L crash.log 를 치명 1·비치명 1 로 가른다")
RUNS = [("test_a.py", "2026-10-26 04:07:44", "2026-10-26 04:07:50", 0),
        ("test_b.py", "2026-10-26 04:08:00", "2026-10-26 04:08:09", 3221225477)]
EV = [("2026-10-26 04:07:45", "0xc0000005", "QtCore.pyd", "0x156d6a"),
      ("2026-10-26 04:08:05", "0xc0000005", "QtCore.pyd", "0x1"),
      ("2026-10-26 04:20:00", "0xc0000005", "x.dll", "0x2")]
cl = "\n".join(rt.crash_lines(RUNS, EV))
chk("판정 뒤" in cl and "test_a.py" in cl and "판정 전" in cl and "test_b.py" in cl and "밖의" in cl,
    "L 검사 시간에 맞춰 판정 뒤(종료 코드 0)·판정 전(죽음)·검사 밖을 가른다", cl)
chk(rt.NATIVE_RC.get(3221225477, "").startswith("0xC0000005"), "L 종료 코드 0xC0000005 를 네이티브 크래시로 이름 붙인다")

# M. 261026-4: 빌드·설치 시험의 정지 스택을 summary 에 옮긴다(종전에는 runs\ 파일에만 — 1.0.1 의 1.37초 정지를 summary 로는 몰랐다)
_runs = Path(tempfile.mkdtemp())
(_runs / "T1_small_stall1.txt").write_text(
    "Process 1: PolyPDF.exe x.pdf\nPython v3.14.3\n\nThread 20356 (active): \"MainThread\"\n"
    "    _attach_pending (study_store.py:116)\n    __init__ (study_store.py:105)\n    _study_read (app.py:3578)\n"
    "    _ocr_page_words (app.py:3592)\n    <lambda> (app.py:3552)\n    pick_ocr_words (text_extract2.py:2265)\n"
    "    _view_ocr_words (app.py:3550)\n\nThread 2 (idle): \"other\"\n    run (x.py:1)\n", encoding="utf-8")
st = rt.stall_tops(_runs, "T1_small")
chk(len(st) == 1 and st[0][2][0].startswith("_attach_pending") and len(st[0][2]) == rt.STALL_TOP and "run (x.py:1)" not in st[0][2],
    "M 정지 스택 파일에서 메인 스레드 맨 위 줄만 옮긴다", st)
chk(rt.stall_tops(_runs, "T2_HM") == [], "M 정지 파일이 없는 대상은 비어 있다")

# N. 261113-5(릴리스 SOT §4.1 의 2·3, 사용자 최신 결정): 베타는 속도를 설치본 전에 개발 코드로 한 번 — 부하 시험(늘) →
#   통과하면 태그·CI 설치본 → 설치 확인(설치·자가 시험·창 뜸·종료·도우미, 속도 비교 없음). 재기 전 전원 상태(261113-1: 배터리 탓 실패).
chk(callable(getattr(rt, "is_beta", None)) and rt.is_beta("1.1.0-beta.12") and not rt.is_beta("1.1.0")
    and not rt.is_beta("1.0.1"), "N 베타 판별(1.1.0-beta.12 예, 정식 아니오)")
_ch = rt._changes
try:
    rt._changes = lambda base: ([("M", "viewer/convert/docx_writer.py", 30)], diff("viewer/convert/docx_writer.py", "+x"))
    bl = getattr(rt, "bundle_lines", lambda *a: [])("1.1.0-beta.12", "v1.1.0-beta.11")
    txt = "\n".join(bl)
    i_load, i_inst = txt.find("load_test"), txt.find("--check-only")
    chk("건너뜀" not in txt and 0 <= i_load < i_inst and "측정 묶음 전체" not in txt,
        "N 베타 — 변환 코드만 바뀌어도 부하 시험 늘, 설치본 전(부하 → 설치 확인 차례), 측정 묶음 없음", txt)
    txt = "\n".join(getattr(rt, "bundle_lines", lambda *a: [])("1.1.0", "v1.0.1"))
    chk("측정 묶음 전체" in txt and "**한다**" in txt and "--check-only" not in txt, "N 정식판은 측정 묶음 + 부하 시험(§4.5)", txt)
finally:
    rt._changes = _ch
chk(getattr(rt, "CHECK_ONLY_CMD", "").endswith("install --source ci --check-only"), "N 베타 설치 확인 명령")
_src = Path(rt.__file__).read_text(encoding="utf-8")
chk('"--check-only"' in _src and "judge_stall=False" in _src and "selftest(exe, out, rec)" in _src,
    "N install --check-only — 자가 시험 + 작은 대상 하나, 정지는 판정하지 않는다")
_bl_orig = rt.BASELINE
try:
    rt.BASELINE = Path(tempfile.mkdtemp()) / "baseline.json"
    rt.BASELINE.write_text(json.dumps({"commit": "old", "version": "1.1.0-beta.11", "mode": "install", "result": "install_A",
                                       "results": {"build": "build_B", "install": "install_A"}}), encoding="utf-8")
    _main = _src.split("def main")[1]
    chk("elif check_only:" in _main and "save_baseline" not in _main.split("elif check_only:")[1].split("return 1 if")[0],
        "N 베타 설치 확인은 기준점을 건드리지 않는다(릴리스 SOT §3.2 — 열기 속도 비교는 정식판에서만)")
finally:
    rt.BASELINE = _bl_orig
# N2. 261113-5(사용자 결정 ②): 부하 시험이 실패하면 실패한 항목만 한 번 더 — load_test --retry <결과 폴더>·--only
import load_test  # noqa: E402
_prev = Path(tempfile.mkdtemp())
(_prev / "result.json").write_text(json.dumps({"mem": [290.0, 275.0], "rows": [
    {"op": "정렬 2", "max_stall_s": 1.185, "err": ""}, {"op": "정렬 3", "max_stall_s": 0.4, "err": ""},
    {"op": "회전 되돌리기", "max_stall_s": 0.2, "err": "ValueError: x"}, {"op": "테마 40번 왕복", "max_stall_s": 0.3, "err": ""}]}),
    encoding="utf-8")
rk = getattr(load_test, "retry_keys", lambda p: [])(_prev)
chk(rk == ["정렬 2", "회전 되돌리기"], "N2 실패한 항목(정지 ≥ 1초·오류)만 다시 잰다 — 통과·누수 없는 테마 왕복은 빼고", rk)
(_prev / "result.json").write_text(json.dumps({"mem": [290.0, 320.0], "rows": [{"op": "테마 40번 왕복", "max_stall_s": 0.3, "err": ""}]}),
                                   encoding="utf-8")
chk(getattr(load_test, "retry_keys", lambda p: [])(_prev) == ["테마 40번 왕복"], "N2 누수가 한도를 넘으면 테마 왕복을 다시")
_ls = Path(load_test.__file__).read_text(encoding="utf-8")
chk('"--only"' in _ls and '"--retry"' in _ls and "need=True" in _ls, "N2 load_test --only·--retry, 준비 조작(폴더 열기)은 늘")
lv = getattr(rt, "beta_level", lambda ver, level, urgent: (level, ""))
chk(lv("1.1.0-beta.12", "build", False)[0] == "install" and "check-only" in lv("1.1.0-beta.12", "build", False)[1],
    "N 베타 묶음은 빌드 시험 대신 설치 확인(까닭 줄)")
chk(lv("1.1.0-beta.12", "build", True)[0] == "build" and lv("1.1.0", "build", False)[0] == "build"
    and lv("1.1.0-beta.12", "skip", False)[0] == "skip", "N 긴급·정식·생략 후보는 그대로")
pt = getattr(overlap, "power_text", None)
chk(pt is not None and "⚠" in pt(False, 55, "best_eff") and "⚠" in pt(False, 80, "balanced")
    and "⚠" in pt(True, 100, "best_eff") and "⚠" not in pt(True, 100, "best_perf") and "⚠" not in pt(True, -1, "?"),
    "N 전원 줄 — 배터리·절전 모드면 경고, 충전기·성능이면 경고 없음",
    [pt(*a) for a in ((False, 55, "best_eff"), (True, 100, "best_perf"))] if pt else None)
w3 = overlap.Watch()
w3.start_busy, w3.power = 5.0, (pt(False, 55, "balanced") if pt else "")
chk(any("⚠" in l and "배터리" in l for l in w3.lines()), "N summary(Watch.lines)에 배터리 경고 줄", w3.lines())

# O. 261113-7(릴리스 SOT §4.1, 검사 작성 SOT §14.7.6): 전체 검사 병렬 — '혼자' 판별·시작 스크립트·상한
_isolo = getattr(rt, "is_solo", None)
chk(_isolo is not None and _isolo(ROOT / "test_clipboard_formats_261112.py") and _isolo(ROOT / "test_i18n_core.py")
    and _isolo(ROOT / "test_vprinter_cli.py") and not _isolo(ROOT / "test_about_notice.py"),
    "O '혼자' 판별 — 실제 클립보드·SOLO_TESTS·가상 프린터는 혼자, 보통 검사는 병렬")
chk(getattr(rt, "CHECK_JOBS", 1) > 1 and rt.CHECK_TIMEOUT <= 300, "O 동시 개수 > 1 · 상한 ≤ 300초", (getattr(rt, "CHECK_JOBS", None), rt.CHECK_TIMEOUT))
_boot = ROOT / "scripts" / "check_boot.py"
_bs = _boot.read_text(encoding="utf-8") if _boot.exists() else ""
chk("TerminateProcess" in _bs and "os._exit = _hard_exit" in _bs and "setTestModeEnabled(True)" in _bs
    and "check_boot.py" in Path(rt.__file__).read_text(encoding="utf-8"),
    "O 시작 스크립트 — os._exit → TerminateProcess·검사마다 Qt 설정 폴더, 실행기가 그것으로 감싼다")
import subprocess as _sp  # noqa: E402
_t = Path(tempfile.mkdtemp()) / "test_boot_probe.py"
_t.write_text("import os,sys\nfrom PyQt6.QtCore import QCoreApplication as Q\nprint(Q.applicationName())\nsys.stdout.flush()\nos._exit(7)\n",
              encoding="utf-8")
if _boot.exists():
    _r = _sp.run([sys.executable, "-I", str(_boot), str(_t)], capture_output=True, text=True, timeout=60)
    chk(_r.returncode == 7 and _r.stdout.strip().startswith("polypdf_chk_test_boot_probe_"),
        "O 시작 스크립트로 돌린 검사 — 종료 코드 그대로(7)·제 설정 이름", (_r.returncode, _r.stdout.strip()[:60]))

# O2. 261113-7: 검사가 끝나면 그 자손도 끝난다(작업 개체) — 검사 H 의 읽기 자식이 고아로 남아 클립보드를 쥔 채 다음 실행을 막았다
if sys.platform == "win32" and hasattr(rt, "_kill_on_close_job"):
    import ctypes as _ct  # noqa: E402
    _par = ("import subprocess,sys\n"
            "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
            "print(c.pid,flush=True)\n")
    _pp = _sp.Popen([sys.executable, "-c", _par], stdout=_sp.PIPE, text=True)
    _job = rt._kill_on_close_job(_pp)
    _cpid = int((_pp.stdout.readline() or "0").strip() or 0)
    _pp.wait(30)
    _k = _ct.windll.kernel32
    _k.OpenProcess.restype = _ct.c_void_p
    _k.WaitForSingleObject.argtypes = [_ct.c_void_p, _ct.c_uint]
    _h = _k.OpenProcess(0x00100000, False, _cpid)          # SYNCHRONIZE
    _alive_before = bool(_h) and _k.WaitForSingleObject(_h, 0) == 0x102
    rt._close_job(_job)
    _gone = bool(_h) and _k.WaitForSingleObject(_h, 5000) == 0
    if _h:
        _k.CloseHandle(_ct.c_void_p(_h))
    chk(_job is not None and _alive_before and _gone, "O 검사 프로세스가 끝나도 남은 자식은 작업 개체를 닫으면 끝난다(고아 없음)",
        (_job is not None, _alive_before, _gone))
else:
    chk(sys.platform != "win32", "O 실행기에 작업 개체(_kill_on_close_job)가 있다")

print("\n=== ALL PASS ===" if not fails else "\n%d FAIL" % len(fails))
sys.exit(1 if fails else 0)
