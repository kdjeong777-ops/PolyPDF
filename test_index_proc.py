# -*- coding: utf-8 -*-
"""261009-19: 색인은 자식 프로세스에서 — 응답성 SOT §4 ③·§4.4 · 검색창 SOT §3.

같은 프로세스의 배경 스레드에서 색인하면 PyMuPDF 의 C 호출이 GIL 을 쥐어 창이 선다 — 그래서 점유율 상한(0.6)과
미리 읽기로 버텼고 첫 색인이 그만큼 느렸다. 자식 프로세스는 GIL 을 나누지 않아 쉬지 않고 색인한다(낮은 우선순위).

실제 `IndexWorker.run`(앱이 쓰는 그 길)으로:
A. 자식 프로세스에서 색인한다(`run_job` 이 True) — 결과(파일·쪽)는 이 프로세스에서 한 것과 같다
B. 텍스트 창에서 고친 글이 자식의 색인에도 들어간다(자식이 부모의 설정 폴더를 쓴다)
C. 취소하면 곧 끝나고(2초 안) 자식이 남지 않는다
D. 자식을 못 띄우면 이 프로세스의 배경 스레드로 종전대로 색인한다
E. 큰 파일을 색인하는 도중 부모가 `os._exit` 로 끝나도 자식이 2초 안에 끝난다(Job Object — 설치본 시험에서 자식이 남아 index.db 를 쥐었다)
"""
import os, sys, time, tempfile, shutil, threading, sqlite3, subprocess
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if len(sys.argv) > 2 and sys.argv[1] == "--parent-exit":
    # E 의 부모 역할: 큰 파일 색인을 자식에 맡기고 도중에 os._exit
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pathlib import Path
    from PyQt6.QtCore import QStandardPaths
    QStandardPaths.setTestModeEnabled(True)
    from viewer.workers import IndexWorker
    from viewer import index_proc as _ip
    _exe = os.environ.get("POLYPDF_TEST_CHILD_EXE")
    if _exe:                                                # 자식을 빌드본 PolyPDF.exe 로(설치본과 같은 자식)
        _ip._command = lambda a: [_exe, _ip.SERVER_ARG, a]
    big = Path(sys.argv[2])
    w = IndexWorker(big.parent / "e.db", big.parent, files=[big])
    started = threading.Event()
    from PyQt6.QtCore import Qt
    w.progress.connect(lambda d, t, n: started.set(),     # 자식이 그 파일 색인을 시작했다(직전에 보내는 진행)
                       Qt.ConnectionType.DirectConnection)  # 이벤트 루프가 없다 — 보내는 스레드에서 바로
    threading.Thread(target=w.run, daemon=True).start()
    started.wait(60)
    time.sleep(2.0)                                         # 자식은 지금 큰 파일 한가운데(C 호출)
    print("PARENT", os.getpid(), int(started.is_set()), flush=True)
    os._exit(0)

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_index_proc_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def counts(db):
    c = sqlite3.connect(db)
    try:
        return (c.execute("select count(*) from files where page_count>=0").fetchone()[0],
                c.execute("select count(*) from pages_fts").fetchone()[0])
    finally:
        c.close()


tmp = Path(tempfile.mkdtemp(prefix="polypdf_iproc_"))
try:
    import fitz
    from test_fixtures import text_pdf
    from viewer import index_proc
    from viewer.workers import IndexWorker
    src = Path(text_pdf())
    files = []
    for i in range(6):
        f = tmp / ("doc%d.pdf" % i); shutil.copy(src, f); files.append(f)

    # 고친 글 하나(B)
    d = fitz.open(str(files[0])); words = d[0].get_text("words"); d.close()
    orig = next(w[4] for w in words if len(w[4]) >= 4)
    from viewer.text_fix_store import store
    st = store(); st.set_fix(files[0], 0, 0, "고친낱말XYZ", orig=orig); st.save()

    seen = {}
    real_run_job = index_proc.run_job

    def spy(job, on_progress, should_cancel):
        r = real_run_job(job, on_progress, should_cancel)
        seen["r"] = r
        return r
    index_proc.run_job = spy

    # ── A·B ──
    db1 = tmp / "child.db"
    w = IndexWorker(db1, tmp, files=files); errs = []
    w.error.connect(lambda e: errs.append(e))
    w.run()
    chk(seen.get("r") is True and not errs, "A 자식 프로세스에서 색인한다", "%r %r" % (seen, errs))
    index_proc.ENABLED = False
    db2 = tmp / "thread.db"
    IndexWorker(db2, tmp, files=files).run()
    index_proc.ENABLED = True
    chk(counts(db1) == counts(db2) and counts(db1)[1] > 0, "A 결과(파일·쪽)는 이 프로세스에서 한 것과 같다",
        "%r vs %r" % (counts(db1), counts(db2)))
    c = sqlite3.connect(db1)
    hit = c.execute("select count(*) from pages_fts where text like ?", ("%고친낱말XYZ%",)).fetchone()[0]; c.close()
    chk(hit >= 1, "B 텍스트 창에서 고친 글이 자식의 색인에도 들어간다", "orig=%r" % orig)

    # ── C: 취소 ──
    many = []
    for i in range(40):
        f = tmp / "many" / ("m%02d.pdf" % i); f.parent.mkdir(exist_ok=True); shutil.copy(src, f); many.append(f)
    db3 = tmp / "cancel.db"
    w3 = IndexWorker(db3, tmp / "many", files=many)
    th = threading.Thread(target=w3.run); th.start()
    time.sleep(1.5)
    t0 = time.perf_counter(); w3.request_cancel(); th.join(10)
    dt = time.perf_counter() - t0
    chk(not th.is_alive() and dt < 2.5, "C 취소하면 곧 끝난다", "%.2fs" % dt)
    time.sleep(0.5)
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*--index-server*' -and $_.ParentProcessId -eq %d }).Count" % os.getpid()],
                         capture_output=True, text=True).stdout.strip()
    chk(out in ("", "0"), "C 취소 뒤 자식이 남지 않는다", out)

    # ── D: 못 띄우면 종전대로 ──
    keep = index_proc._command
    index_proc._command = lambda a: [str(tmp / "no_such.exe"), a]
    seen.clear()
    db4 = tmp / "fallback.db"
    IndexWorker(db4, tmp, files=files).run()
    index_proc._command = keep
    chk(seen.get("r") is None and counts(db4) == counts(db2), "D 자식을 못 띄우면 이 프로세스에서 종전대로 색인한다",
        "%r %r" % (seen, counts(db4)))

    # ── E: 부모가 도중에 끝나도 자식이 남지 않는다 ──
    # 한 파일 색인이 20초 넘게 걸리게(부모가 4초에 끝날 때 자식은 그 파일 한가운데 — C 호출 안이라 파이프를 못 본다)
    (tmp / "e").mkdir(exist_ok=True)
    d = fitz.open()
    txt = ("시험 본문 텍스트 page body text 한글 " * 40 + "\n") * 12
    d.new_page(width=600, height=800).insert_textbox(fitz.Rect(20, 20, 580, 780), txt, fontsize=6)
    big = tmp / "e" / "p0.pdf"; d.save(str(big)); d.close()
    for k in range(14):                                  # 두 배씩 — 16,384쪽(자식 혼자 수십 초)
        a1 = fitz.open(str(big)); b1 = fitz.open(str(big)); a1.insert_pdf(b1); b1.close()
        nxt = tmp / "e" / ("p%d.pdf" % (k + 1)); a1.save(str(nxt)); a1.close(); big.unlink(); big = nxt
    # ★ 자식은 **빌드본 PolyPDF.exe** 로 띄운다 — 파이썬 자식(개발 실행)은 이 환경에서 부모와 함께 끝나 Job Object 가 없어도
    #   결함이 안 보였다(실측 5회). 설치본에서 남은 것은 PolyPDF.exe 자식이었다. 빌드본이 없으면(CI) E 는 건너뛴다.
    import site
    dist_exe = Path(os.path.dirname(os.path.abspath(__file__))) / "dist" / "PolyPDF" / "PolyPDF.exe"
    if not dist_exe.exists():
        print("SKIP - E 빌드본(dist\\PolyPDF\\PolyPDF.exe)이 없어 건너뜀")
        raise StopIteration
    base = getattr(sys, "_base_executable", sys.executable)
    env = dict(os.environ, POLYPDF_TEST_CHILD_EXE=str(dist_exe),
               PYTHONPATH=os.pathsep.join([os.path.dirname(os.path.abspath(__file__))] + site.getsitepackages()))
    r = subprocess.run([base, os.path.abspath(__file__), "--parent-exit", str(big)],
                       capture_output=True, text=True, timeout=180, env=env)
    pl = next((l.split() for l in r.stdout.splitlines() if l.startswith("PARENT")), [])
    ppid = pl[1] if len(pl) > 2 and pl[2] == "1" else ""
    time.sleep(2.0)
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "@(Get-CimInstance Win32_Process -Filter \"Name='PolyPDF.exe'\" | Where-Object { $_.CommandLine -like '*--index-server*' -and $_.ParentProcessId -eq %s }).Count" % (ppid or 0)],
                         capture_output=True, text=True).stdout.strip()
    chk(ppid != "" and out in ("", "0"), "E 큰 파일 색인 도중 부모가 끝나도 자식이 2초 안에 끝난다", "ppid=%s 남은 %s %s" % (ppid, out, r.stderr[-200:]))
except StopIteration:
    pass
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(tmp), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
