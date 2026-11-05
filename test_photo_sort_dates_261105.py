# -*- coding: utf-8 -*-
"""사진 모드 책갈피창 '수정일 순' — 날짜가 섞이지 않는다 (사진 보기 SOT §4.37, 261105-2 사용자 보고).

증상: 사진 모드 책갈피창이 '수정일 순' 인데 날짜가 섞인 목록으로 남는 때가 있었다.
원인: 정렬 값(촬영 시각)은 배경에서 읽어 붙이고 다 읽으면 한 번 다시 늘어놓는데, 읽는 도중 목록을 다시 그리면
      (폴더 감시·🔄·정렬 바꾸기 → filesListed → 날짜 읽기 다시 시작) 새 작업이 '새로 읽은 것 있음' 표시를 지우고,
      새 작업은 이미 기억한 값이라 아무것도 새로 읽지 않아 → 다시 늘어놓기를 건너뛰었다(파일 시각 순 그대로).
A. 그냥 폴더 열기 — 촬영 시각 내림차순(파일 시각과 반대로 만든 사진들)
B. 날짜를 읽은 직후·끝나기 전에 목록을 다시 그림(날짜 읽기 다시 시작) — 그래도 촬영 시각 내림차순
실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3). 각 경우는 따로 프로세스.
"""
import os, sys, subprocess
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
fails = []
N = 6


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def child(case):
    import time, tempfile, shutil
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, HERE)
    from PyQt6.QtCore import QStandardPaths, QCoreApplication
    QStandardPaths.setTestModeEnabled(True)
    from PyQt6.QtWidgets import QApplication
    from pathlib import Path
    app = QApplication(sys.argv[:1])
    QCoreApplication.setApplicationName("polypdf_photo_sortd_%s_%d" % (case, os.getpid()))
    import modal_guard
    modal_guard.install(echo=False)
    from PIL import Image
    tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_sortd_"))
    try:
        pix = tmp / "pix"; pix.mkdir()
        base = time.time() - 30 * 86400
        for i in range(N):                       # 촬영일은 i 가 클수록 최근, 파일 시각은 i 가 클수록 옛날
            ex = Image.Exif()
            ex[0x0132] = "2021:03:%02d 10:00:00" % (i + 1)
            f = pix / ("p%d.jpg" % i)
            Image.new("RGB", (64, 48), (i * 30, 90, 90)).save(f, "JPEG", exif=ex)
            t = base + (N - i) * 86400
            os.utime(f, (t, t))
        from viewer import settings_store
        settings_store.save({"preferences": {"picture": {"mode": "photo", "view_kind": "mixed"}, "startup_mode": "none"}})
        from viewer.app import MainWindow
        win = MainWindow()
        win._skip_save_on_close = True
        win.show()
        bt = win.bookmark_tree
        if case == "B":                          # 첫 날짜 묶음을 받은 직후 목록을 다시 그린 것처럼 — 날짜 읽기를 다시 시작
            orig = win._photo_dates_got
            state = {"n": 0}

            def got(d, w=None):
                orig(d, w)
                state["n"] += 1
                if state["n"] == 1:
                    win._photo_dates_start()
            win._photo_dates_got = got           # batch 연결의 람다가 부를 때마다 이 이름을 찾는다
        end = time.monotonic() + 2
        while time.monotonic() < end:
            app.processEvents(); time.sleep(0.01)
        win.open_folder(pix)
        end = time.monotonic() + 8
        while time.monotonic() < end:
            app.processEvents(); time.sleep(0.01)
        names = [Path(str(it.data(0, bt.DATA_FILE))).stem for it in bt._iter_file_nodes()]
        print("RESULT", case, int(win._photo_mode), bt._sort_combo.currentData(), ",".join(names), flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    os._exit(0)


if len(sys.argv) > 2 and sys.argv[1] == "--child":
    child(sys.argv[2])

want = ",".join("p%d" % i for i in reversed(range(N)))
for case, msg in (("A", "A 폴더 열기 — 촬영 시각 내림차순"),
                  ("B", "B 날짜를 읽는 도중 목록을 다시 그려도 — 촬영 시각 내림차순(파일 시각 순으로 남지 않는다)")):
    p = subprocess.run([sys.executable, "-u", os.path.abspath(__file__), "--child", case], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120, cwd=HERE)
    line = [l for l in p.stdout.splitlines() if l.startswith("RESULT")]
    if not line:
        print(p.stdout[-1500:], p.stderr[-1500:])
    r = line[0].split()[2:] if line else None
    chk(r is not None and r[0] == "1" and r[1] == "mtime" and r[2] == want, msg, str(r))

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
