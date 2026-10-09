# -*- coding: utf-8 -*-
"""261009-21: 문서를 열 때 썸네일 다시 그리기가 메인을 세우지 않는다 — 응답성 SOT §4 ⑥·§4.5·§12.

빌드본 시험 T3(598쪽)에서 첫 열기 때 메인이 1.51초 섰다(`_load_main` → `_refresh_hidden_ui` → `set_decorated_pages` →
`_rerender_all`). 숨김·회전·꾸밈이 **전 항목**에 `setIcon` 을 불렀고(598×3), 사이드카 키가 부를 때마다 `Path.resolve()` 를 했다.
PyQt 는 C++ 호출마다 GIL 을 내려놓아, 다른 스레드가 바쁘면 호출마다 GIL 을 되찾느라 기다린다.

실제 MainWindow 로 600쪽 문서를 열고, **GIL 을 계속 원하는 스레드**를 함께 돌리며:
A. `_refresh_hidden_ui`(문서를 열 때 그 길) 세 번의 최장이 0.25초 미만(수정 전 0.9초대)
B. 꾸밈이 바뀐 쪽의 썸네일만 다시 그리고, 안 바뀐 쪽은 그대로 둔다(그린 그림이 같다)
C. 바뀐 쪽은 꾸밈 색 띠로 다시 그려진다(결과가 맞다)
"""
import os, sys, time, tempfile, shutil, threading
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_thumbs_rr_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.005)


tmp = Path(tempfile.mkdtemp(prefix="polypdf_thrr_"))
busy = {"run": True}
try:
    import fitz
    pdf = tmp / "big.pdf"
    d = fitz.open()
    for i in range(600):
        d.new_page(width=400, height=560).insert_text((40, 80), "page %d" % i)
    d.save(str(pdf)); d.close()
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True; mw.resize(1400, 900); mw.show()
    mw.open_pdf(pdf); pump(2.0)
    th = mw.page_thumbs

    def spin():
        x = 0
        while busy["run"]:
            x += 1                            # 순수 파이썬 — GIL 을 계속 원한다(동결 import 해제와 같은 꼴)
    threading.Thread(target=spin, daemon=True).start()

    # ── A ──
    worst = 0.0
    for _ in range(3):
        t = time.perf_counter(); mw._refresh_hidden_ui(pdf); worst = max(worst, time.perf_counter() - t)
        pump(0.2)
    chk(worst < 0.25, "A 600쪽 문서를 열 때 썸네일·사이드카 갱신이 바쁜 스레드가 있어도 0.25초 미만", "%.3fs" % worst)
    busy["run"] = False
    pump(0.8)

    # ── B·C ──
    items = {th.list.item(i).data(Qt.ItemDataRole.UserRole): th.list.item(i) for i in range(th.list.count())}
    drawn = [pg for pg, it in items.items() if isinstance(pg, int) and not it.icon().isNull()]
    chk(len(drawn) >= 2, "B 앞쪽 썸네일이 그려져 있다", str(len(drawn)))
    if len(drawn) >= 2:
        a, b = drawn[0], drawn[1]
        key_b = items[b].icon().cacheKey()
        img_a = items[a].icon().pixmap(120, 160).toImage()
        th.set_decorated_pages({a})
        pump(0.8)
        chk(items[b].icon().cacheKey() == key_b, "B 꾸밈이 안 바뀐 쪽은 다시 그리지 않는다")
        img_a2 = items[a].icon().pixmap(120, 160).toImage()
        chk(not items[a].icon().isNull() and img_a2 != img_a, "C 꾸밈이 바뀐 쪽은 꾸밈 띠로 다시 그려진다")
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    busy["run"] = False
    shutil.rmtree(str(tmp), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
