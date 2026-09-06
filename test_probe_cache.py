# -*- coding: utf-8 -*-
"""260906-4: 목록 조사(표식)는 한 번만 — 영구 캐시 + 진행 표시.

사용자 보고(260906): 인덱싱 창이 닫힌 뒤에도 한동안 책갈피창 휠이 버벅이는데
아무 표시가 없어 '작업이 없는데 느리다'로 보였다. 원인은 **목록 조사**(파일마다
`fitz.open` 으로 암호화·책갈피 유무 확인)가 계속 돌던 것. PyMuPDF 는 파일을 여는 동안
GIL 을 놓지 않아 워커로 돌려도 메인이 밀린다(실측 120개 13초 동안 20ms 하트비트가
652회 중 89회만 실행, 최대 3.06초 정지).

검사 대상:
  ① 인덱서 `probe_cache` — 기록/조회, 파일이 바뀌면 무효
  ② `index_file` 이 조사 값을 함께 적는다(인덱싱은 어차피 그 파일을 연다)
  ③ 트리는 아는 파일을 **다시 열지 않는다** — 정렬 변경·재개방·새 트리 모두
  ④ 조사 진행을 신호로 알린다(진행 창·상태바가 이것을 쓴다)
  ⑤ 스크롤 신호에서 즉시 걷지 않는다(되먹임 방지 — 휠이 굼뜨던 원인)
"""
import os, sys, time, tempfile, shutil
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
import test_fixtures as _fx
import viewer.workers as W
from viewer.indexer import PdfIndex
from viewer.widgets.bookmark_tree import BookmarkTree

# 워커가 실제로 연 파일 수를 센다
opened = {"n": 0}
_orig_run = W.ProbeWorker.run


def _counting_run(self):
    opened["n"] += len(self.paths)
    return _orig_run(self)


W.ProbeWorker.run = _counting_run

root = Path(tempfile.mkdtemp(prefix="polypdf_probe_"))
db = root / "index.db"
src = Path(_fx.text_pdf())          # 내부 책갈피(TOC) 12개짜리
files = []
for i in range(6):
    p = root / f"doc{i}.pdf"
    shutil.copy(src, p)
    files.append(p)


def settle(bt, sec=30):
    t = time.time() + sec
    while time.time() < t and (bt._probe_worker is not None or bt._probe_queue
                               or bt._fill_plan or bt._probe_scan_timer.isActive()):
        app.processEvents(); time.sleep(0.005)
    for _ in range(40):
        app.processEvents(); time.sleep(0.01)


def make_tree(idx):
    bt = BookmarkTree(); bt.resize(320, 700); bt.show()
    bt.probe_db_path = db
    bt.probe_provider = lambda p, sz, mt: idx.probe_get(p, sz, mt)
    return bt


try:
    idx = PdfIndex(db)

    # ── ① probe_cache 기록/조회 ──────────────────────────────────────────
    st = files[0].stat()
    chk(idx.probe_get(files[0], st.st_size, st.st_mtime) is None,
        "① 모르는 파일은 None")
    idx.probe_set(files[0], st.st_size, st.st_mtime, False, True, None)
    got = idx.probe_get(files[0], st.st_size, st.st_mtime)
    chk(got == (False, True, None), "① 적은 값을 그대로 돌려준다", str(got))
    chk(idx.probe_get(files[0], st.st_size + 1, st.st_mtime) is None,
        "① 크기가 다르면 무효(파일이 바뀐 것)")
    chk(idx.probe_get(files[0], st.st_size, st.st_mtime + 100) is None,
        "① 수정시각이 다르면 무효")

    # ── ② 인덱싱이 조사 값을 함께 적는다 ────────────────────────────────
    idx.index_file(files[1])
    st1 = files[1].stat()
    got = idx.probe_get(files[1], st1.st_size, st1.st_mtime)
    chk(got is not None and got[1] is True,
        "② 인덱싱한 파일은 조사 값이 함께 남는다(TOC 있음)", str(got))

    # ── ③ 아는 파일은 다시 열지 않는다 ──────────────────────────────────
    bt = make_tree(idx)
    opened["n"] = 0
    bt.load_folder(root); settle(bt)
    first = opened["n"]
    chk(first > 0, "③ 처음에는 모르는 파일을 연다", f"{first}개")

    bt._sort_combo.setCurrentText(bt.SORT_NAME); settle(bt)
    chk(opened["n"] == first, "③ 정렬을 바꿔도 다시 열지 않는다",
        f"누적 {opened['n']}")

    bt.load_folder(root); settle(bt)
    chk(opened["n"] == first, "③ 같은 폴더를 다시 열어도 열지 않는다",
        f"누적 {opened['n']}")

    idx2 = PdfIndex(db)                      # 새 실행처럼 새 연결·새 트리
    bt2 = make_tree(idx2)
    bt2.load_folder(root); settle(bt2)
    chk(opened["n"] == first, "③ 새 트리(다음 실행)도 열지 않는다 — 영구 캐시",
        f"누적 {opened['n']}")

    # ── ④ 진행 신호 ─────────────────────────────────────────────────────
    seen = {"prog": 0, "done": 0, "last": (0, 0)}
    bt3 = make_tree(PdfIndex(db))
    bt3.probeProgress.connect(lambda d, t, n: (seen.__setitem__("prog", seen["prog"] + 1),
                                               seen.__setitem__("last", (d, t))))
    bt3.probeFinished.connect(lambda: seen.__setitem__("done", seen["done"] + 1))
    fresh = root / "새파일.pdf"              # 캐시에 없는 파일 하나
    shutil.copy(src, fresh)
    bt3.load_folder(root); settle(bt3)
    chk(seen["prog"] > 0, "④ 조사 진행을 알린다(진행 창·상태바용)", f"{seen['prog']}회")
    chk(seen["done"] > 0, "④ 조사가 끝나면 알린다", f"{seen['done']}회")

    # ── ④-b 260906-5: 배경 작업 4가지 의무(마스터 SOT §5) ────────────────
    from viewer.workers import ProbeWorker
    from viewer.indexer import PdfIndex as _PI
    chk(ProbeWorker.YIELD_S > 0 and _PI.YIELD_S > 0,
        "④-b ② 파일마다 GIL 을 양보한다(양보 간격 > 0)",
        f"probe {ProbeWorker.YIELD_S}s / index {_PI.YIELD_S}s")
    chk(0 < ProbeWorker.MAX_MB <= 200,
        "④-b ③ 큰 파일은 배경에서 열지 않는다(상한 존재)", f"{ProbeWorker.MAX_MB}MB")
    big = root / "큰파일.pdf"
    with open(big, "wb") as f:                     # 상한을 넘는 더미(열리지 않아야 한다)
        f.write(b"%PDF-1.4" + b"\n" + b"0" * (ProbeWorker.MAX_MB * 1024 * 1024 + 1024))
    got = {"n": 0}
    w = ProbeWorker([str(big)])
    w.result.connect(lambda r: got.__setitem__("n", got["n"] + 1))
    w.run()
    chk(got["n"] == 0, "④-b ③ 상한을 넘는 파일은 결과도 내지 않는다(열지 않았다)")
    big.unlink()

    bt4 = make_tree(PdfIndex(db))
    bt4.set_probe_paused(True)
    bt4.load_folder(root)
    t_end = time.time() + 5
    while time.time() < t_end and bt4._fill_plan:
        app.processEvents(); time.sleep(0.005)
    bt4._probe_tick()                              # 멈춘 동안에는 워커를 띄우지 않는다
    chk(bt4._probe_worker is None,
        "④-b ① 인덱싱 중(일시정지)에는 조사를 시작하지 않는다")
    bt4.set_probe_paused(False)
    settle(bt4)
    chk(bt4._probe_worker is None and not bt4._probe_queue,
        "④-b ① 풀면 이어서 끝낸다")

    # ── ⑤ 스크롤 신호에서 즉시 걷지 않는다(되먹임 방지) ─────────────────
    chk(callable(getattr(bt3, "_schedule_visible_probes", None)),
        "⑤ 걷기 예약 진입점이 있다")
    chk(bt3._probe_scan_timer.isSingleShot() and bt3._probe_scan_timer.interval() >= 30,
        "⑤ 걷기는 모아서 1회(단발 타이머)",
        f"{bt3._probe_scan_timer.interval()}ms")
    calls = {"n": 0}
    _orig_scan = bt3._queue_visible_probes
    bt3._queue_visible_probes = lambda: (calls.__setitem__("n", calls["n"] + 1),
                                         _orig_scan())[1]
    sb = bt3.tree.verticalScrollBar()
    for i in range(20):
        sb.setValue(sb.value() + 3)          # 휠 대신 스크롤바를 20번 움직인다
        app.processEvents()
    chk(calls["n"] == 0, "⑤ 스크롤 도중에는 걷지 않는다(예약만)", f"{calls['n']}회")
finally:
    try:
        idx.close()
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
