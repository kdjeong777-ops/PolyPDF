# -*- coding: utf-8 -*-
"""261014-17: 남은 메인 정지 (개선 로드맵 P2-6, 응답성 SOT §4.4, 텍스트 창 SOT §3 규칙 7).

A. 응답하지 않는 다른 PolyPDF 창이 있어도 원본 덮어쓰기 저장(`_finalize_save`)이 메인을 1초 넘게 세우지 않는다
   — 다른 창 확인은 배경 스레드에서(종전 3.3초 정지)
B. 표 인식은 문서 전체 쪽 목록(pdfplumber `PDF.pages`)을 만들지 않고 그 쪽 하나만 만든다 — 결과는 종전 길과 같다
"""
import os, sys, tempfile, shutil, time, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, QTimer, QElapsedTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from PyQt6.QtNetwork import QLocalServer
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = Path(tempfile.mkdtemp(prefix="polypdf_stall_test_"))
reg = None
try:
    src = root / "A.pdf"
    d = fitz.open()
    for i in range(3):
        d.new_page().insert_text((72, 72), f"page {i}")
    d.save(str(src)); d.close()
    produced = root / "A_new.pdf"
    shutil.copy2(src, produced)

    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1000, 700); mw.show(); app.processEvents()

    # ── A. 응답하지 않는 다른 창 ────────────────────────────────────
    from viewer import instance_link as il
    stuck = QLocalServer()
    name = f"polypdf-stucktest-{os.getpid()}"
    QLocalServer.removeServer(name)
    chk(stuck.listen(name), "준비 — 응답하지 않는 창(연결은 받고 답하지 않는다)")
    reg = il._registry_dir() / f"{name}.json"
    reg.write_text(json.dumps({"server": name, "pid": os.getpid()}), encoding="utf-8")

    gaps = {"max": 0}
    clock = QElapsedTimer(); clock.start()
    last = {"t": clock.elapsed()}

    def beat():
        now = clock.elapsed()
        gaps["max"] = max(gaps["max"], now - last["t"])
        last["t"] = now
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(beat); hb.start()
    QTest.qWait(100)
    gaps["max"] = 0
    last["t"] = clock.elapsed()
    t0 = time.perf_counter()
    out = mw._finalize_save(str(src), str(produced))
    took = time.perf_counter() - t0
    beat()
    hb.stop()
    chk(Path(out) == src and not produced.exists(), "A 저장은 그대로 원본에", str(out))
    chk(took >= 2.5, "A (확인) 응답 없는 창을 정말 기다렸다(응답 상한 3초)", f"{took:.2f}s")
    chk(gaps["max"] < 1000, "A 기다리는 동안 메인 최장 정지 < 1초(종전 3.3초)", f"{gaps['max']} ms")

    # ── B. 표 인식은 쪽 하나만 ─────────────────────────────────────
    tp = root / "T.pdf"
    d = fitz.open()
    for i in range(30):
        pg = d.new_page(width=595 if i % 2 == 0 else 842, height=842 if i % 2 == 0 else 595)
        x0, y0, cw, rh = 60, 100, 120, 22
        for r in range(5):
            pg.draw_line((x0, y0 + r * rh), (x0 + 3 * cw, y0 + r * rh))
        for c in range(4):
            pg.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + 4 * rh))
        for r in range(4):
            for c in range(3):
                pg.insert_text((x0 + c * cw + 5, y0 + r * rh + 15), f"P{i}R{r}C{c}", fontsize=9)
        if i == 7:
            pg.set_rotation(90)
    d.save(str(tp)); d.close()
    import pdfplumber
    from viewer import text_extract2 as tx
    same, built = True, False
    for k in (3, 7, 20):
        pdf = pdfplumber.open(str(tp))
        new = tx._tables(str(tp), k, plumber=pdf)
        built = built or ("_pages" in pdf.__dict__)
        pdf.close()
        pdf2 = pdfplumber.open(str(tp))
        old = [(tuple(t.bbox), t.extract()) for t in pdf2.pages[k].find_tables()]
        pdf2.close()
        same = same and [(tuple(round(v, 2) for v in b), r) for b, r in new] == \
            [(tuple(round(v, 2) for v in b), r) for b, r in old] and len(new) == 1
    chk(not built, "B 표 인식이 문서 전체 쪽 목록을 만들지 않는다")
    chk(same, "B 결과는 종전 길과 같다(회전한 쪽 포함)")
finally:
    try:
        if reg is not None:
            reg.unlink(missing_ok=True)
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
