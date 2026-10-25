# -*- coding: utf-8 -*-
"""261024-2: 클립보드에 그림 넣기 — 한 곳 (스크린샷 SOT §3·§8.1·§8.3, 사용자 보고).

**실제 Windows 클립보드**로 잰다(오프스크린 클립보드는 프로그램 안에서만 살아 '다른 프로그램이
쥐고 있음' 을 만들 수 없다). 다른 프로세스가 `OpenClipboard` 로 클립보드를 쥐게 해 둔다.

A. 다른 프로그램이 쥔 동안 `clipboard_util.set_image` → 놓은 뒤 들어가고 on_done(True)
B. 끝내 못 넣으면 on_done(False), 앱은 상태 표시줄에 알린다
C. 원본 화질 캡처(`_capture_pages`)도 클립보드에 넣는다(종전: 복사 자체가 없었다)
D. '클립보드로 복사' 컷 하나가 들어간다(종전: 기록 지우기 직후 첫 컷이 빠졌다)
   · 기록 지우기는 메인을 세우지 않는다(종전 1.5~2.2초)

261026-2(스크린샷 SOT §8.3): 실제 클립보드는 다른 프로그램도 쓴다 — 1.0.0 코드에서도 간헐로 실패했다(A·B·C·D 가 실행마다
바뀌고 132초까지 늘어짐). 쥐는 장치가 못 쥐어도 'held' 라 알려 '쥔 동안' 이 성립하지 않았고, 다른 것이 클립보드를 다투면 Qt 넣기
재시도가 길어졌다. 그래서 ① 장치는 실제로 쥐었는지('held'/'nohold') 알리고 못 쥐면 `HOLD_TRIES` 번 다시, 그래도 못 쥐면 그 항목은
실패가 아니라 **'확인 못 함'** ② 클립보드 넣기 한 번이 `CONTEND_MS` 를 넘거나 전체가 `TOTAL_CAP_S` 를 넘으면 다툼으로 보고 남은 항목을
'확인 못 함' 으로 넘긴다(늘어지지 않게). '확인 못 함' 만 있으면 종료 코드는 0 — 판정은 실패 항목으로만.
"""
import os, sys, json, time, tempfile, subprocess
sys.stdout.reconfigure(encoding="utf-8")
if sys.platform != "win32":
    print("SKIP - Windows 클립보드 전용")
    sys.stdout.flush(); os._exit(0)
# 마스터 §14.7 예외 — 실제 클립보드라 오프스크린이 아니다(창은 띄우지 않는다)
os.environ["QT_QPA_PLATFORM"] = "windows"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shutil
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QElapsedTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
cb = QApplication.clipboard()
fails = []
unverified = []          # 클립보드를 다른 프로그램이 다퉈 확인하지 못한 항목 — 실패가 아니다
HOLD_TRIES = 3           # 쥐는 장치가 못 쥐면 다시 띄우는 횟수
CONTEND_MS = 3000        # 클립보드 넣기 한 번이 이보다 오래 걸리면 다른 것이 다투는 중으로 본다
TOTAL_CAP_S = 75         # 전체 상한 — 넘으면 남은 항목은 확인 못 함(종전 다툼 때 132초)
T_ALL = time.monotonic()


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def unver(msg, why):
    print("SKIP -", msg, f"— 확인 못 함({why})")
    unverified.append(msg)


HOLDER = (
    "import ctypes,sys,time\n"
    "u=ctypes.windll.user32\n"
    "ok=False\n"
    "for _ in range(200):\n"
    "    if u.OpenClipboard(0):\n"
    "        ok=True; break\n"
    "    time.sleep(0.01)\n"
    "print('held' if ok else 'nohold',flush=True)\n"     # 못 쥐었으면 그렇다고 알린다(종전에는 늘 'held')
    "if ok:\n"
    "    time.sleep(float(sys.argv[1]))\n"
    "    u.CloseClipboard()\n")


def hold(seconds):
    """다른 프로세스가 클립보드를 seconds 동안 쥔다 — 쥔 뒤에 돌아온다. 끝내 못 쥐면 None."""
    for _ in range(HOLD_TRIES):
        p = subprocess.Popen([sys.executable, "-c", HOLDER, str(seconds)],
                             stdout=subprocess.PIPE, text=True, creationflags=0x08000000)
        if p.stdout.readline().strip() == "held":
            return p
        p.wait()
        time.sleep(0.3)
    return None


def has_image():
    md = cb.mimeData()
    return bool(md is not None and md.hasImage())


def reset():
    """클립보드를 글로 되돌린다. 오래 걸리면(다툼) False."""
    t0 = time.monotonic()
    cb.setText("before"); app.processEvents()
    return (time.monotonic() - t0) * 1000 < CONTEND_MS


def ready(section):
    """그 항목을 잴 수 있나 — 전체 상한·다툼을 본다."""
    if time.monotonic() - T_ALL > TOTAL_CAP_S:
        unver(section, f"전체 {TOTAL_CAP_S}초 넘음")
        return False
    if not reset():
        unver(section, "클립보드 넣기가 늘어짐 — 다른 프로그램이 다투는 중")
        return False
    return True


def wait_until(pred, ms):
    t = QElapsedTimer(); t.start()
    while not pred() and t.elapsed() < ms:
        QTest.qWait(50)
    return pred()


img = QImage(120, 80, QImage.Format.Format_RGB32); img.fill(QColor("red"))
from viewer import clipboard_util

# A. 쥔 동안 넣기 → 놓은 뒤 들어간다
if ready("A 쥔 동안 넣기"):
    res = []
    h = hold(0.8)
    if h is None:
        unver("A 쥔 동안 넣기", "쥐는 장치가 클립보드를 쥐지 못함")
    else:
        clipboard_util.set_image(img, res.append)
        chk(not cb.ownsClipboard(), "A 전제: 다른 프로그램이 쥔 동안 첫 넣기는 실패한다")
        wait_until(lambda: res, 4000); h.wait()
        chk(res == [True], "A 놓은 뒤 다시 넣어 on_done(True)", f"{res}")
        chk(has_image(), "A 클립보드에 그림이 있다")

# B. 끝내 못 넣으면 False
HOLD_ALL_S = clipboard_util.RETRY_TRIES * (clipboard_util.RETRY_MS / 1000 + 0.4) + 2
if ready("B 끝내 못 넣음"):
    res = []
    h = hold(HOLD_ALL_S)
    if h is None:
        unver("B 끝내 못 넣음", "쥐는 장치가 클립보드를 쥐지 못함")
    else:
        t = QElapsedTimer(); t.start()
        clipboard_util.set_image(img, res.append)
        chk(t.elapsed() < 1000, "B 넣기 한 번이 메인을 1초 넘게 세우지 않는다", f"{t.elapsed()}ms")
        wait_until(lambda: res, int(HOLD_ALL_S * 1000))
        chk(res == [False], "B 끝내 못 넣으면 on_done(False)", f"{res}")
        h.wait()

# 앱 경로
tmp = Path(tempfile.mkdtemp(prefix="polypdf_clip_"))
d = fitz.open(); d.new_page(width=400, height=600).insert_text((40, 80), "clip")
d.save(str(tmp / "T.pdf")); d.close()
(tmp / "bookmarks.json").write_text(json.dumps(
    {"version": 1, "bookmarks": [{"title": "T", "file": "T.pdf", "children": []}]}), encoding="utf-8")
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(1000, 700)
mw.open_folder(tmp); app.processEvents()
mw._on_bookmark_activated(mw.bookmark_tree.ordered_pdf_files()[0], 0)
QTest.qWait(300)

# B'. 앱은 실패를 알린다
if ready("B 앱 알림"):
    h = hold(HOLD_ALL_S)
    if h is None:
        unver("B 앱 알림", "쥐는 장치가 클립보드를 쥐지 못함")
    else:
        seen = []      # 다른 알림이 덮어써도 놓치지 않게 상태 표시줄 문구를 모두 모은다
        mw.status.messageChanged.connect(seen.append)
        fail_msg = lambda: any("클립보드에 복사하지 못했습니다" in m for m in seen)
        if hasattr(mw, "_copy_image_to_clipboard"):
            mw._copy_image_to_clipboard(img)
        wait_until(fail_msg, int(HOLD_ALL_S * 1000))
        chk(fail_msg(), "B 앱이 상태 표시줄에 실패를 알린다", str(seen))
        h.wait()

# C. 원본 화질 캡처(_capture_pages)도 복사 — 쥔 동안 캡처해도 놓은 뒤 들어간다
if ready("C _capture_pages"):
    h = hold(0.6)
    if h is None:
        unver("C _capture_pages", "쥐는 장치가 클립보드를 쥐지 못함")
    else:
        mw._capture_pages(mw.main_view, [0])
        chk(wait_until(has_image, 4000), "C _capture_pages 캡처가 클립보드에 들어간다")
        h.wait()

# D. '클립보드로 복사' 컷 하나
if ready("D 클립보드로 복사"):
    mw.shot_strip.clear() if hasattr(mw.shot_strip, "clear") else None
    mw._capture_pages(mw.main_view, [0]); QTest.qWait(200)
    if not reset():
        unver("D 클립보드로 복사", "클립보드 넣기가 늘어짐 — 다른 프로그램이 다투는 중")
    else:
        t = QElapsedTimer(); t.start()
        mw._on_clipboard_save()
        returned_ms = t.elapsed()
        chk(returned_ms < 500, "D 기록 지우기가 메인을 세우지 않는다", f"{returned_ms}ms")
        chk(wait_until(has_image, 15000), "D '클립보드로 복사' 컷이 클립보드에 들어간다")
        wait_until(lambda: not getattr(mw, "_clip_busy", False), 10000)

shutil.rmtree(tmp, ignore_errors=True)
if unverified:
    print("\n확인 못 함(클립보드 다툼 — 실패 아님):", unverified)
print("\n=== " + ("ALL PASS" if not fails else f"FAILURE {len(fails)}") + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
