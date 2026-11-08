# -*- coding: utf-8 -*-
"""구성요소 설치 창은 창을 세우지 않는다 (261107-11, 응답성 SOT §4.4 · 마스터 §14.5 U16).

종전: 설치 여부 확인(`tesseract --version`)과 내려받기를 메인에서 부르고 `processEvents` 로 버텼다 — 릴리스 목록 요청·
느린 조각 하나 동안 창이 섰고 [취소] 가 없었다. 실제 네트워크 대신 느린 가짜(`_assets` 1.5초·조각마다 0.15초·확인 1.5초).
A. 창이 바로 뜬다(모달 아님), 확인 중에는 '확인 중…' — 확인이 끝나면 상태 글(색은 디자인 토큰)
B. [다운로드] → 받는 동안 메인 최장 공백 < 1초, 작업 창에 오른다, 끝나면 파일이 생기고 작업이 내려간다
C. [중단] → 아무것도 쓰지 않는다, 작업이 내려간다
D. 받는 중 창을 닫아도 내려받기는 계속되고 끝나면 파일이 생긴다(상태 표시줄 알림)
"""
import os, sys, tempfile, time
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
QCoreApplication.setApplicationName("polypdf_ui_stall_components_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "구성요소 설치", echo=False)   # 마스터 §14.7.2 의 6
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


class Beat:
    """20ms 타이머 — 울린 사이 가장 긴 공백(메인이 선 시간)."""
    def __init__(self):
        self.t = QTimer(); self.t.setInterval(20); self.t.timeout.connect(self._tick)
        self.last = None; self.worst = 0.0

    def _tick(self):
        now = time.monotonic()
        if self.last is not None:
            self.worst = max(self.worst, now - self.last)
        self.last = now

    def start(self):
        self.last = None; self.worst = 0.0; self.t.start()

    def stop(self):
        self.t.stop()
        return self.worst


tmp = Path(tempfile.mkdtemp(prefix="polypdf_comp_"))
from viewer import components as comp
comp.install_dir = lambda: tmp
comp._assets = lambda repo, timeout=8.0: (time.sleep(1.5), {"ffmpeg.exe": "fake://ffmpeg", "tesseract.zip": "fake://t"})[1]


def fake_download(url, progress=None, timeout=60.0):
    total, done = 20 * 65536, 0
    for _ in range(20):
        time.sleep(0.15)                                # 느린 망 — 조각 하나
        done += 65536
        if progress is not None and progress(done, total) is False:
            return None
    return b"\0" * total


comp._download = fake_download
# 261108-12(U16): 받은 바이트는 고정 SHA-256 과 맞아야 설치된다 — 가짜 바이트의 해시로
import hashlib
comp.PINNED_SHA256["ffmpeg.exe"] = hashlib.sha256(b"\0" * (20 * 65536)).hexdigest()
comp.ffmpeg_installed = lambda: (time.sleep(1.5), (tmp / "ffmpeg.exe").exists())[1]
comp.tesseract_installed = lambda: False

try:
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    beat = Beat()

    # A
    beat.start()
    t0 = time.monotonic()
    mw._open_components_installer()
    took = time.monotonic() - t0
    dlg = getattr(mw, "_comp_dlg", None)
    chk(dlg is not None and dlg.isVisible() and not dlg.isModal() and took < 0.5, "A 창이 바로 뜬다(모달 아님)", "%.2f초" % took)
    rows = getattr(dlg, "_rows", {}) if dlg is not None else {}
    st, btn = rows.get("ffmpeg", (None, None))
    chk(st is not None and st.text() == "확인 중…", "A 확인 중에는 '확인 중…'", repr(st.text() if st else None))
    chk(pump(lambda: st is not None and st.text() == "미설치"), "A 확인이 끝나면 상태 글")
    from viewer.widgets import icons
    from viewer import theme
    chk(st is not None and icons.ACCENT["stop"][theme.is_dark()] in st.styleSheet(), "A 색은 디자인 토큰", st.styleSheet() if st else "")
    chk(beat.stop() < 1.0, "A 여는 동안 메인 최장 공백 < 1초", "%.2f초" % beat.worst)

    # B
    if btn is not None:
        beat.start()
        btn.click()
        pump(lambda: bool(getattr(mw, "_jobs", {})), timeout=2)
        chk(any(k.startswith("components:") for k in getattr(mw, "_jobs", {})), "B 작업 창에 오른다")
        chk(btn.text() == "중단", "B 받는 동안 단추는 '중단'", btn.text())
        chk(pump(lambda: (tmp / "ffmpeg.exe").exists() and getattr(mw, "_comp_worker", 1) is None, timeout=20),
            "B 끝나면 파일이 생긴다")
        chk(beat.stop() < 1.0, "B 받는 동안 메인 최장 공백 < 1초", "%.2f초" % beat.worst)
        chk(not any(k.startswith("components:") for k in mw._jobs), "B 끝나면 작업이 내려간다")
        pump(lambda: st.text() == "설치됨 ✓")

        # C
        (tmp / "ffmpeg.exe").unlink()
        pump(timeout=0.3)
        mw._comp_check(); pump(lambda: btn.isEnabled() and btn.text() == "다운로드")
        btn.click()
        pump(lambda: mw._comp_worker is not None and mw._comp_worker._last >= 10, timeout=10)
        btn.click()                                     # [중단]
        chk(pump(lambda: mw._comp_worker is None, timeout=10), "C 중단하면 곧 끝난다")
        chk(not (tmp / "ffmpeg.exe").exists() and not (tmp / "ffmpeg.exe.part").exists(), "C 중단하면 아무것도 쓰지 않는다")
        chk(not any(k.startswith("components:") for k in mw._jobs), "C 작업이 내려간다")
        chk("중단" in mw.status.currentMessage(), "C 상태 표시줄 알림", mw.status.currentMessage())

        # D
        pump(lambda: btn.isEnabled() and btn.text() == "다운로드")
        btn.click()
        pump(lambda: mw._comp_worker is not None, timeout=5)
        dlg.close(); pump(timeout=0.3)
        chk(mw._comp_worker is not None, "D 창을 닫아도 내려받기는 계속")
        chk(pump(lambda: (tmp / "ffmpeg.exe").exists() and mw._comp_worker is None, timeout=20), "D 끝나면 파일이 생긴다")
        chk("설치 완료" in mw.status.currentMessage(), "D 상태 표시줄 알림", mw.status.currentMessage())
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
