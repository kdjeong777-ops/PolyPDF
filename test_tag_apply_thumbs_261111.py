# -*- coding: utf-8 -*-
"""해시태그 넣기 창 썸네일 — 칸 높이·보이는 칸만·큰 목록 응답성 (태그 SOT §8.7, 응답성 SOT §4, 261111-15 사용자 보고).

사용자 보고: 썸네일이 칸마다 위쪽 20px 쯤 가로 띠로만 그려지고 아래는 빈칸('고른 파일 1개 / 모두 8694개').
원인: setUniformItemSizes 가 첫 줄(아직 그림 없음)로 칸 크기를 재 글자 높이만큼만 잡았다.
A. 실제 창(보이게) — 썸네일 칸이 그림 높이(THUMB) 이상, 그림이 들어온다
B. 보이는 칸만 만든다(3,000장을 다 만들지 않는다), 끝까지 스크롤하면 끝 칸도
C. 3,000장 창 열기 1초 안·여는 동안 메인 최장 공백(응답성 SOT §5)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_tag_apply_thumbs_%d" % os.getpid())
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond, timeout=15.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_tagthumbs_"))
try:
    from PIL import Image
    from viewer.tag_store import TagStore
    from viewer.widgets.tag_apply_dialog import TagApplyDialog, THUMB
    Image.new("RGB", (800, 600), (30, 120, 200)).save(tmp / "p0000.jpg", "JPEG")
    raw = (tmp / "p0000.jpg").read_bytes()
    N = 3000
    for i in range(1, N):
        (tmp / ("p%04d.jpg" % i)).write_bytes(raw)
    paths = [str(tmp / ("p%04d.jpg" % i)) for i in range(N)]
    st = TagStore(tmp / "tags.json")
    keep = []
    gap, last = [0.0], [time.perf_counter()]

    def beat():
        now = time.perf_counter(); gap[0] = max(gap[0], now - last[0]); last[0] = now
    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat); hb.start()
    t0 = time.perf_counter()
    dlg = TagApplyDialog(st, paths, [paths[0]], keep=keep)
    dlg.resize(1100, 700); dlg.show()
    t_open = time.perf_counter() - t0
    w = dlg._thumber
    lw = dlg.lst_files
    blank_key = dlg._blank.cacheKey() if hasattr(dlg, "_blank") else None
    has_img = lambda i: (blank_key is None and not lw.item(i).icon().isNull()) or (blank_key is not None and lw.item(i).icon().cacheKey() != blank_key)
    chk(pump(lambda: has_img(0), 20), "A 첫 칸에 그림이 들어온다")
    h = lw.visualItemRect(lw.item(0)).height()
    chk(h >= THUMB, "A 썸네일 칸 높이가 그림 높이 이상(종전 글자 높이만큼 — 위 20px 띠)", "%d < %d" % (h, THUMB))
    pump(lambda: False, 1.0)
    made = getattr(w, "made", None)
    chk(made is not None and 0 < made < 600, "B 보이는 칸만 만든다(3,000장을 다 만들지 않는다)", str(made))
    lw.scrollToBottom(); pump(lambda: False, 0.2)
    chk(pump(lambda: has_img(N - 1), 20), "B 끝까지 스크롤하면 끝 칸도 그린다")
    hb.stop()
    print("   C 3,000장 창 열기 %.3f초, 메인 최장 공백 %.3f초" % (t_open, gap[0]))
    chk(t_open < 1.0, "C 3,000장 창 열기 1초 안", "%.3f" % t_open)
    chk(gap[0] < 1.0, "C 메인 최장 공백 1초 안(응답성 SOT §5)", "%.3f" % gap[0])
    dlg.reject()
    pump(lambda: False, 0.3)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
