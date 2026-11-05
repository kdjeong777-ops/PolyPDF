# -*- coding: utf-8 -*-
"""사진 모드로 닫은 뒤의 시작 — 파일 인자·시작 폴더가 열린다 (사진 보기 SOT §6.1·D1, 261104-20 빌드본 측정 결함).

증상(빌드본 측정, 설정 picture.mode='photo'): 시작 경로 폴더가 열리지 않고(제목에 폴더 없음, 색인 0개),
명령줄 PDF 는 지난 사진·지난 PDF 를 먼저 연 뒤에야 열렸다(열림 9초대, 작업 집합 +250MB).
원인: 창을 만들 때 사진 모드 복원이 지난 사진을 본문에 열어 → 시작 복원이 '이미 열었다' 로 보고 시작 폴더를 건너뜀,
      파일 인자 창은 창을 만든 **뒤에** PDF 모드로 바꿔 그사이 사진 모드 일을 다 하고 지난 PDF 까지 열었다.
A. 파일 인자(main.py 순서 그대로 — 창 만들기 전 START_PDF) — 처음부터 PDF 모드, 본문에 연 것은 그 PDF 하나
B. 인자 없이 시작 경로 폴더(startup_mode=path) — 그 폴더가 열린다(사진 모드 그대로, 지난 사진을 먼저 열지 않는다)
C. 사진 모드 창에서 PDF 열기(가상 프린터·최근·끌어 놓기의 open_pdf) — PDF 모드로, 그 PDF 만 연다(지난 PDF 를 먼저 열지 않는다)
D. main.py 가 MainWindow() 보다 먼저 START_PDF 를 켠다
각 경우는 따로 프로세스(모듈 값·설정이 섞이지 않게). 실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3).
"""
import os, sys, subprocess
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def child(case):
    import time, tempfile, shutil
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, HERE)
    from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
    QStandardPaths.setTestModeEnabled(True)
    from PyQt6.QtWidgets import QApplication
    from pathlib import Path
    app = QApplication(sys.argv[:1])
    QCoreApplication.setApplicationName("polypdf_photo_start_%s_%d" % (case, os.getpid()))
    import modal_guard
    modal_guard.install(echo=False)
    from PIL import Image
    import fitz
    tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_start_"))
    try:
        pix = tmp / "pix"; pix.mkdir()
        for i in range(3):
            Image.new("RGB", (400, 300), (i * 60, 90, 90)).save(pix / ("p%d.jpg" % i), "JPEG")
        pdfs = tmp / "pdfs"; pdfs.mkdir()
        for n in ("arg.pdf", "old.pdf"):
            d = fitz.open(); d.new_page().insert_text((72, 72), n); d.save(str(pdfs / n)); d.close()
        from viewer import settings_store
        pref = {"picture": {"mode": "photo", "view_kind": "mixed", "recent_files": [str(pix / "p1.jpg")],
                            "recent_folders": [str(pix)]}}
        if case == "B":
            pref.update(startup_mode="path", startup_path=str(pdfs))
        settings_store.save({"preferences": pref, "last_folder": str(pix), "recent_files": [str(pdfs / "old.pdf")]})
        loads = []
        from viewer.app import MainWindow
        orig = MainWindow._load_main

        def spy(self, item, *a, **k):
            loads.append(Path(item.file_path).name)
            return orig(self, item, *a, **k)
        MainWindow._load_main = spy
        if case == "A":                                  # main.py 와 같은 순서: 창 만들기 전
            from viewer import photo_controller
            photo_controller.START_PDF = True
        win = MainWindow()
        win._skip_save_on_close = True
        init_mode = win._photo_mode
        if case == "A":
            win._startup_has_args = True
            win._photo_force_pdf()
        win.show()
        if case == "A":
            QTimer.singleShot(0, lambda: win.open_pdf(pdfs / "arg.pdf"))
        end = time.monotonic() + 5
        while time.monotonic() < end:
            app.processEvents(); time.sleep(0.01)
        if case == "C":                                  # 사진 모드 창에서 PDF 열기
            loads.clear()
            win.open_pdf(pdfs / "arg.pdf")
            end = time.monotonic() + 3
            while time.monotonic() < end:
                app.processEvents(); time.sleep(0.01)
        cur = win.main_view.current_file()
        print("RESULT", case, int(init_mode), int(win._photo_mode), Path(cur).name if cur else "-",
              "|".join(loads) or "-", int(str(pdfs) in win.windowTitle()), flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    os._exit(0)


if len(sys.argv) > 2 and sys.argv[1] == "--child":
    child(sys.argv[2])

res = {}
for case in ("A", "B", "C"):
    p = subprocess.run([sys.executable, "-u", os.path.abspath(__file__), "--child", case], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120, cwd=HERE)
    line = [l for l in p.stdout.splitlines() if l.startswith("RESULT")]
    if not line:
        print(p.stdout[-1500:], p.stderr[-1500:])
    res[case] = line[0].split()[2:] if line else None

a, b, c = res["A"], res["B"], res["C"]
chk(a is not None and a[0] == "0" and a[1] == "0", "A 파일 인자 창 — 처음부터 PDF 모드(사진 모드 복원을 하지 않는다)", str(a))
chk(a is not None and a[2] == "arg.pdf" and a[3] == "arg.pdf", "A 본문에 연 것은 그 PDF 하나(지난 사진·지난 PDF 를 먼저 열지 않는다)", str(a))
chk(b is not None and b[4] == "1", "B 사진 모드로 닫았어도 시작 경로 폴더가 열린다(제목에 폴더)", str(b))
chk(b is not None and b[3] == "-", "B 창을 만들 때 지난 사진을 열지 않는다", str(b))
chk(c is not None and c[1] == "0" and c[2] == "arg.pdf" and c[3] == "arg.pdf", "C 사진 모드에서 PDF 열기 — PDF 모드로 그 PDF 만", str(c))

src = open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
i_flag, i_win = src.find("_pc.START_PDF = True"), src.find("win = MainWindow()")
chk(0 < i_flag < i_win, "D main.py 가 MainWindow() 보다 먼저 START_PDF 를 켠다")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
