# -*- coding: utf-8 -*-
"""큰 사진 폴더의 '수정일 순' — 촬영일(없으면 파일 날짜), 클라우드에만 있는 사진은 내려받지 않는다 (사진 보기 SOT 4.37·4.24, 261105-10·-11).

사용자 폴더(8,985장, 그중 5,446장 클라우드에만)에서 날짜 읽기가 끝나지 않아 목록이 내내 파일 날짜 순이었다 — 그 흉내:
색인 행이 있는 2,000장(파일 시각은 촬영 순서와 거꾸로) + 색인 없는 300장(머리 읽기 느림) + 클라우드에만 있는 200장.
A. 색인에 있는 사진은 머리 읽기가 끝나기 전에(목록을 그린 뒤 몇 초 안) 촬영일 내림차순
B. 클라우드에만 있는 사진은 날짜 작업도 색인도 머리를 읽지 않는다 — 날짜는 파일 날짜(임시), 색인은 이름 행만(수정 시각 0)
C. 그 사진을 본문에 열어 받아지면(해독 끝) 그 한 장만 머리를 읽는다
D. 책갈피창 사진 줄 '기본' 꼴은 이름(+ 태그 꼬리) — 날짜를 읽었든 못 읽었든 같은 꼴(261105-11)
E. 메인 최장 공백(하트비트) < 1초(응답성 SOT)
F. 읽기만 하는 날짜 작업·사진 검색은 색인 훑기의 쓰기 트랜잭션 뒤에 서지 않는다(`photo_index.connect_read`)
실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3).
"""
import os, sys, tempfile, shutil, time, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_sort_taken_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 촬영일 순", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=15.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


N_IDX, N_RAW, N_CLOUD = 2000, 300, 200
tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_sort_taken_"))
try:
    from PIL import Image
    import io
    big = tmp / "사진"
    big.mkdir()
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (40, 120, 200)).save(buf, "JPEG")
    raw = buf.getvalue()
    base = time.mktime((2025, 10, 15, 12, 0, 0, 0, 0, -1))     # 모두 최근 파일 시각(아이클라우드가 받은 날)
    idx = []
    for i in range(N_IDX):                                      # i 가 클수록 촬영이 늦고 파일 시각은 이르다(거꾸로)
        p = big / ("i%04d.jpg" % i)
        p.write_bytes(raw)
        os.utime(p, (base - i * 60, base - i * 60))
        idx.append(p)
    for i in range(N_RAW):
        p = big / ("r%04d.jpg" % i)
        p.write_bytes(raw)
        os.utime(p, (base + i, base + i))
    cloud = []
    for i in range(N_CLOUD):
        p = big / ("c%04d.jpg" % i)
        p.write_bytes(raw + b"\0")
        os.utime(p, (base - 86400 * 3 - i, base - 86400 * 3 - i))
        cloud.append(p)
    from viewer import photo_index
    con = photo_index.connect()
    with con:
        for i, p in enumerate(idx):
            st = p.stat()
            d = time.localtime(time.mktime((2000, 1, 1, 0, 0, 0, 0, 0, -1)) + i * 86400)
            info = {"taken": time.strftime("%Y:%m:%d 10:00:00", d), "width": 64, "height": 48}
            photo_index.upsert(con, os.path.normcase(os.path.abspath(str(p))), str(p), photo_index.norm_folder(big),
                               p.name, ".jpg", st.st_size, st.st_mtime_ns, info, [])
    con.close()

    # F — 읽기만 하는 날짜 작업·검색은 색인 훑기의 쓰기 트랜잭션 뒤에 서지 않는다(연결마다 meta 를 쓰던 것)
    from viewer.photo_controller import PhotoDateWorker
    wcon = photo_index.connect()
    if not wcon.in_transaction:
        wcon.execute("BEGIN IMMEDIATE")
    wcon.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('probe', '1')")
    t0 = time.perf_counter()
    kn = PhotoDateWorker._known(photo_index.norm_folder(big)) if hasattr(PhotoDateWorker, "_known") else {}   # 수정 전 코드에는 없다
    t_known = time.perf_counter() - t0
    t0 = time.perf_counter()
    found = photo_index.search("i0001")
    t_search = time.perf_counter() - t0
    wcon.rollback()
    wcon.close()
    chk(len(kn) == N_IDX and t_known < 1.0, "F 날짜 작업의 색인 읽기는 쓰는 중에도 기다리지 않는다", "%d행 %.2f초" % (len(kn), t_known))
    chk(bool(found) and t_search < 1.0, "F 사진 검색(메인)도 쓰는 중에 기다리지 않는다", "%d건 %.2f초" % (len(found), t_search))

    # 느린 머리 읽기(클라우드·네트워크 흉내) + 어느 사진을 읽었는지
    from viewer import photo_io
    read_meta, read_info = [], []
    lock = threading.Lock()
    _meta, _info = photo_io.photo_meta, photo_io.photo_info
    cloud_names = {p.name for p in cloud}
    local_now = set()

    def slow_meta(path):
        with lock:
            read_meta.append(Path(str(path)).name)
        time.sleep(0.05)
        return _meta(path)

    def spy_info(path, *a, **k):
        with lock:
            read_info.append(Path(str(path)).name)
        return _info(path, *a, **k)
    photo_io.photo_meta = slow_meta
    photo_io.photo_info = spy_info
    chk(hasattr(photo_io, "cloud_only"), "B 클라우드에만 있는 파일 판정(photo_io.cloud_only)")
    cloud_size = len(raw) + 1                                   # stat 결과에는 이름이 없다 — 클라우드 사진은 1바이트 길게 해 가린다
    photo_io.cloud_only = lambda st: getattr(st, "st_size", 0) == cloud_size and getattr(st, "st_mtime_ns", 0) not in local_now

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    pump()
    gap, last = [0.0], [time.perf_counter()]

    def beat():
        now = time.perf_counter(); gap[0] = max(gap[0], now - last[0]); last[0] = now
    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat); hb.start()
    listed = []
    bt.filesListed.connect(lambda: listed.append(time.monotonic()))
    mw.open_folder(big)
    total = N_IDX + N_RAW + N_CLOUD
    pump(lambda: listed and sum(1 for _ in bt._iter_file_nodes()) == total, timeout=60)
    t_list = listed[0] if listed else time.monotonic()
    names = lambda: [Path(str(it.data(0, bt.DATA_FILE))).name for it in bt._iter_file_nodes()]
    want = ["i%04d.jpg" % i for i in reversed(range(N_IDX))]

    seen_at = [0.0]

    def idx_ok():                                   # 2,500 줄 훑기는 검사 쪽 일 — 0.2초마다만(하트비트를 검사가 막지 않게)
        if time.monotonic() - seen_at[0] < 0.2:
            return False
        seen_at[0] = time.monotonic()
        return [n for n in names() if n.startswith("i")] == want
    ok = pump(idx_ok, timeout=max(0.5, t_list + 6.0 - time.monotonic()))
    chk(ok, "A 색인에 있는 사진은 머리 읽기가 끝나기 전에 촬영일 순(목록 뒤 6초 안)",
        "%.1f초, 머리 읽기 %d장" % (time.monotonic() - t_list, len(read_meta)))
    chk(not any(n.startswith("i") for n in read_meta), "A 색인에 있는 사진은 머리를 다시 읽지 않는다", str([n for n in read_meta if n.startswith("i")][:5]))

    # 머리 읽기(색인 없는 300장)가 끝날 때까지 — 그 뒤 전체가 정렬 값 내림차순
    pump(lambda: mw.__dict__.get("_photo_dater") is None and mw.__dict__.get("_photo_indexer") is None, timeout=90)
    pump(lambda: not mw._photo_tree_out_of_order(bt), timeout=10)
    chk(not mw._photo_tree_out_of_order(bt), "A 다 읽은 뒤 모든 줄이 정렬 값(촬영일, 없으면 파일 시각) 내림차순")

    # B
    chk(not any(n in cloud_names for n in read_meta), "B 클라우드에만 있는 사진 — 날짜 작업이 머리를 읽지 않는다",
        str([n for n in read_meta if n in cloud_names][:5]))
    chk(not any(n in cloud_names for n in read_info), "B 클라우드에만 있는 사진 — 색인이 머리를 읽지 않는다",
        str([n for n in read_info if n in cloud_names][:5]))
    c0 = cloud[0]
    hit = mw._photo_date_cache.get(os.path.normcase(str(c0)))
    fdate = time.strftime("%Y-%m-%d", time.localtime(base - 86400 * 3))
    chk(bool(hit) and hit[1] == fdate and len(hit) > 6 and hit[6], "B 클라우드 사진 날짜는 파일 날짜(임시 값)", str(hit))
    c = photo_index.connect()
    try:
        row = c.execute("SELECT mtime_ns, taken FROM photos WHERE key=?", (os.path.normcase(os.path.abspath(str(c0))),)).fetchone()
    finally:
        c.close()
    chk(row is not None and row[0] == 0, "B 색인은 이름 행만(수정 시각 0)", str(row))

    # C — 본문에 열어 받아졌다
    local_now.add(c0.stat().st_mtime_ns)
    n0 = len(read_meta)
    mw._photo_on_decoded(str(c0), 0)
    pump(lambda: len(read_meta) > n0 and not (mw._photo_date_cache.get(os.path.normcase(str(c0))) or (0,) * 7)[6], timeout=10)
    hit = mw._photo_date_cache.get(os.path.normcase(str(c0)))
    chk(read_meta[n0:] == [c0.name] and hit is not None and not hit[6], "C 받아진 사진은 그 한 장만 머리를 읽는다", str((read_meta[n0:], hit)))

    # D — 기본 꼴은 이름(날짜를 읽은 줄·못 읽은 줄 모두)
    labels = {Path(str(it.data(0, bt.DATA_FILE))).name: it.text(0) for it in bt._iter_file_nodes()}
    bad = [(k, v) for k, v in labels.items() if not v.startswith(Path(k).stem)]
    chk(not bad, "D 사진 줄 기본 꼴은 이름(+ 태그 꼬리) — 줄마다 같다", str(bad[:4]))

    hb.stop()
    print("   메인 최장 공백 %.3f초" % gap[0])
    chk(gap[0] < 1.0, "E 메인 최장 공백 < 1초", "%.3f" % gap[0])
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
