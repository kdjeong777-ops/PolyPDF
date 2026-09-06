# -*- coding: utf-8 -*-
"""260906-1: 폴더 열기가 창을 멈추지 않는다 — 비동기 스캔·점진 채우기·보이는 행만 검사.

배경(사용자 보고 260905): 마지막 폴더가 외장 드라이브 루트(PDF 28,954개)였던 설치본이
스플래시만 띄운 채 멈췄다. 원인은 셋 다 **메인 스레드**였다 —
  ① `rglob("*.pdf")` 로 목록 수집, ② 파일마다 `fitz.open` 표식 검사(평균 20ms),
  ③ 그 둘을 `MainWindow.__init__` 안에서(=창이 뜨기 전에) 실행.

검사 대상(마스터 SOT §5 '폴더 열기 3단 규칙' / '시작 복원은 창을 띄운 뒤'):
  ① `pathutil.iter_pdfs` — 재귀·대소문자 무시·취소
  ② 작은 폴더는 **종전대로 동기** 렌더(동작·기존 테스트 불변)
  ③ 큰 폴더는 `load_folder` 가 즉시 반환하고 목록이 나중에 찬다 + `filesListed`
  ④ 표식 검사 큐에는 **보이는 행만** 들어간다
  ⑤ 반복 타이머 간격 0 금지(WM_TIMER 굶김)
  ⑥ `MainWindow.__init__` 은 폴더를 열지 않는다 — `_restore_session_deferred` 가 연다
"""
import os, sys, io, json, time, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
from viewer.pathutil import iter_pdfs
from viewer.widgets.bookmark_tree import BookmarkTree

# ── 표본: 작은 폴더(루트 3 + sub 2) / 큰 폴더(10×60=600) ─────────────────
small = Path(tempfile.mkdtemp(prefix="polypdf_scan_s_"))
for rel in ["r1.pdf", "r2.pdf", "R3.PDF", "sub/a1.pdf", "sub/a2.pdf"]:
    p = small / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")                      # 스캔·목록만 보므로 내용은 필요 없다
(small / "sub" / "not_a_pdf.txt").write_bytes(b"")

big = Path(tempfile.mkdtemp(prefix="polypdf_scan_b_"))
# 규모는 '여러 덩이로 나뉘어 채워지는가'만 보면 되므로 작게 잡는다(FILL_CHUNK=100 × 6덩이).
#   임시 폴더에 파일을 많이 만드는 비용이 검사 자체보다 크다(백신 검사 대상 경로).
N_DIR, N_FILE = 10, 60
for d in range(N_DIR):
    sub = big / f"folder{d:02d}"
    sub.mkdir()
    for i in range(N_FILE):
        (sub / f"doc{i:04d}.pdf").write_bytes(b"")
BIG_N = N_DIR * N_FILE

try:
    # ── ① iter_pdfs ──────────────────────────────────────────────────────
    got = sorted(p.name for p in iter_pdfs(small))
    chk(got == ["R3.PDF", "a1.pdf", "a2.pdf", "r1.pdf", "r2.pdf"],
        "① 재귀·대소문자 무시로 PDF 만 찾는다", str(got))
    seen = []
    for p in iter_pdfs(big, should_cancel=lambda: len(seen) >= 5):
        seen.append(p)
    chk(len(seen) < BIG_N, "① should_cancel 로 중간에 멈춘다", f"{len(seen)}개")

    # ── ② 작은 폴더 = 동기 (반환 시점에 이미 목록·트리가 있다) ───────────
    bt = BookmarkTree(); bt.resize(320, 600); bt.show()
    t0 = time.time()
    bt.load_folder(small)
    sync_ms = (time.time() - t0) * 1000
    chk(len(bt._pdfs_flat) == 5, "② 작은 폴더는 반환 즉시 목록이 찬다",
        f"{len(bt._pdfs_flat)}개 / {sync_ms:.0f}ms")
    chk(len(bt.all_file_paths()) == 5, "② 트리 행도 즉시 만들어진다",
        f"{len(bt.all_file_paths())}개")

    # ── ③ 큰 폴더 = 비동기 ───────────────────────────────────────────────
    bt2 = BookmarkTree(); bt2.resize(320, 600); bt2.show()
    bt2.SCAN_BUDGET_MS = 0                  # 예산 0 → 무조건 워커 경로(대형 폴더 재현)
    listed = {"n": 0}
    bt2.filesListed.connect(lambda: listed.__setitem__("n", listed["n"] + 1))
    t0 = time.time()
    bt2.load_folder(big)
    ret_ms = (time.time() - t0) * 1000
    chk(ret_ms < 300, "③ load_folder 가 즉시 반환한다(스캔을 기다리지 않음)",
        f"{ret_ms:.0f}ms")
    chk(len(bt2.all_file_paths()) == 0, "③ 이 시점에는 트리가 비어 있다")

    worst = 0.0
    deadline = time.time() + 60
    while time.time() < deadline and listed["n"] == 0:
        a = time.time()
        app.processEvents()
        worst = max(worst, time.time() - a)
        time.sleep(0.002)
    chk(listed["n"] == 1, "③ 다 차면 filesListed 를 **한 번** 낸다", f"{listed['n']}회")
    chk(len(bt2.all_file_paths()) == BIG_N, "③ 모든 파일이 트리에 들어온다",
        f"{len(bt2.all_file_paths())}/{BIG_N}")
    chk(worst < 0.5, "③ 채우는 동안 한 번에 멈추는 시간이 짧다", f"최장 {worst*1000:.0f}ms")

    # ── ④ 표식 검사 큐 = 보이는 행만 ─────────────────────────────────────
    #   종전에는 폴더의 모든 파일이 큐에 들어갔다(전량). 이제는 뷰포트 분량만.
    bt3 = bt2                               # 이미 다 채워진 트리를 그대로 쓴다
    bt3._probe_timer.stop()                 # 큐가 빠지지 않게 멈춘 뒤 센다
    bt3._probe_queue = []
    for it in bt3._iter_file_nodes():       # 이전에 매긴 검사 표식 초기화
        it.setData(0, bt3.DATA_PROBED, None)
    bt3._queue_visible_probes()
    n_q = len(bt3._probe_queue)
    chk(0 < n_q < 100, "④ 큐에는 보이는 행만 들어간다(전량 아님)",
        f"{n_q}개 / 전체 {BIG_N}개")
    chk(all(bt3._is_file_node(it) for it, _p in bt3._probe_queue),
        "④ 큐에 든 것은 모두 파일 행이다")
    before = n_q
    bt3._queue_visible_probes()             # 같은 화면에서 다시 불러도 늘지 않는다
    chk(len(bt3._probe_queue) == before, "④ 같은 행을 두 번 넣지 않는다(DATA_PROBED)")

    # ── ④-b 260906-2: 검사는 워커가 한다 — 메인 스레드에서 열지 않는다 ──
    #   큰 PDF 는 `fitz.open` 한 건이 수 초라, 보이는 행만 검사해도 메인에서 하면 멈춘다
    #   (실측 4.5초 '응답 없음'). `_probe_tick` 은 큐를 워커에 넘기고 즉시 돌아와야 한다.
    t0 = time.time()
    bt3._probe_tick()
    hand_ms = (time.time() - t0) * 1000
    chk(bt3._probe_worker is not None, "④-b 검사를 워커 스레드에 넘긴다")
    chk(hand_ms < 100, "④-b 넘기는 데 걸리는 시간이 짧다(메인에서 열지 않음)",
        f"{hand_ms:.0f}ms")
    chk(not bt3._probe_queue, "④-b 넘긴 큐는 비워진다")
    t_end = time.time() + 30
    while time.time() < t_end and bt3._probe_worker is not None:
        app.processEvents(); time.sleep(0.005)
    chk(bt3._probe_worker is None, "④-b 다 끝나면 워커를 놓는다")

    # ── ⑤ 반복 타이머 간격 0 금지 ────────────────────────────────────────
    chk(bt3._probe_timer.interval() >= 10, "⑤ 표식 검사 타이머 간격 ≥ 10ms",
        f"{bt3._probe_timer.interval()}ms")
    chk(bt3._fill_timer.interval() >= 10, "⑤ 트리 채우기 타이머 간격 ≥ 10ms",
        f"{bt3._fill_timer.interval()}ms")

    # ── ⑥ MainWindow.__init__ 은 폴더를 열지 않는다 ──────────────────────
    #   §14.7: 공유 설정을 건드리므로 스냅샷 → 원복.
    from viewer import settings_store
    SPATH = settings_store.settings_path("settings.json")
    orig = io.open(SPATH, encoding="utf-8").read() if SPATH.exists() else None
    try:
        d = json.loads(orig) if orig else {}
        # 260906-3: 전제를 **명시**한다(§14.7) — 시작 동작·기억한 대상 둘 다.
        #   앞선 테스트가 남긴 값에 기대면 스위트 순서에 따라 흔들린다(실측 재현).
        d["last_folder"] = str(small)
        d["last_open"] = {"kind": "folder", "path": str(small)}
        _p = d.setdefault("preferences", {})
        _p["restore_session"] = True
        _p["startup_mode"] = "last"
        io.open(SPATH, "w", encoding="utf-8", newline="\n").write(
            json.dumps(d, ensure_ascii=False, indent=2))

        from viewer.app import MainWindow
        mw = MainWindow()
        chk(mw._folder is None, "⑥ 생성만으로는 폴더를 열지 않는다", repr(mw._folder))
        chk(callable(getattr(mw, "_restore_session_deferred", None)),
            "⑥ 미뤄 둔 복원 진입점이 있다")
        mw._restore_session_deferred()      # 이벤트 루프가 부르는 것을 직접
        chk(mw._folder is not None and Path(mw._folder) == small,
            "⑥ 복원이 실행되면 마지막 폴더가 열린다", repr(mw._folder))
    finally:
        if orig is None:
            if SPATH.exists():
                SPATH.unlink()
        else:
            io.open(SPATH, "w", encoding="utf-8", newline="\n").write(orig)
finally:
    shutil.rmtree(small, ignore_errors=True)
    shutil.rmtree(big, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
