# -*- coding: utf-8 -*-
"""아이폰 등 휴대 장치의 사진 — 둘러보기 + 복사 (사진 보기 SOT 4.33, 261104-9 사용자 결정).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 장치는 **가짜**(`photo_device.BACKEND` 를 바꿔 끼움).
A. 사진 모드 책갈피창 맨 위에 장치 줄(파일 행 아님) — 아래에 사진 폴더 새것부터. 잠긴 장치를 누르면 알림만. PDF 모드에는 없다
B. 폴더 줄을 누르면 사진을 한 장씩 캐시로 받아 썸네일 줄에 더하고 첫 장을 연다 — 제목 '장치 › 폴더', 상태 막대 '장치 › 폴더 › 이름'
C. 받는 동안 메인이 멈추지 않는다(최장 공백 < 1초 — 응답성 SOT §2 기준, 261106-21), 읽기 전용(방향 저장·지우기 막힘)
D. 다시 열면 장치에서 다시 받지 않는다(캐시)
E. 'PC 로 복사' — 고른 폴더로, 같은 이름이면 번호
F. 받는 도중 연결이 끊기면 받은 것만 두고 알림
G. 책갈피창 트리(폴더) 보기 — 장치·사진 폴더가 폴더 줄 모양, 연 폴더 아래 사진 줄, 누르면 그 사진(사용자 지시)
H. 단일 보기 — 폴더 줄 없이 장치의 모든 사진 줄, 누르면 그 사진이 든 폴더를 그 사진부터 받아 연다(사용자 결정)
I. 썸네일 줄 끝에서 더 내리면(넘김·휠) 다음(더 오래된) 폴더를 이어 받는다 — 줄은 그대로 아래에 더한다(사용자 지시)
K. 장치 조사가 응답 없는 장치에 붙들려도 창 닫기는 기다리지 않는다(지휘 세션 확인 요청)
J. 상태 표시줄에 사진 일시 — 촬영 정보가 없으면 파일 날짜(장치 복사는 장치의 날짜가 남는다)(사용자 지시)
"""
import os, sys, tempfile, shutil, time, io
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_device_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "휴대 장치", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_device_"))
try:
    from PIL import Image
    from viewer import photo_device as pd

    def jpg(color):
        b = io.BytesIO(); Image.new("RGB", (240, 180), color).save(b, "JPEG"); return b.getvalue()

    class FakeBackend:
        """가짜 장치 — 'Apple iPhone'(폴더 둘), '잠긴 폰'(저장소 없음). 한 장 받는 데 0.05초."""
        def __init__(self):
            self.copies = 0
            self.break_after = None
            self.data = {"Internal Storage/202611_a": {"IMG_0001.JPG": jpg((200, 40, 40)), "IMG_0002.JPG": jpg((40, 200, 40)),
                                                      "IMG_0003.HEIC.mov": b"x", "IMG_0004.PNG": jpg((40, 40, 200))},
                         "Internal Storage/202610_a": {"IMG_0100.JPG": jpg((90, 90, 90))}}

        def devices(self):
            return ["Apple iPhone", "잠긴 폰"]

        def folders(self, dev):
            if dev == "잠긴 폰":
                raise pd.DeviceError("locked", dev)
            return sorted(self.data, key=lambda k: k.rsplit("/", 1)[-1], reverse=True)

        def open_folder(self, dev, folder):
            if dev not in self.devices():
                raise pd.DeviceError("gone", dev)
            return folder

        def photos(self, h):
            return sorted(n for n in self.data[h] if pd._is_photo(n))

        def copy(self, h, name, dest):
            if self.break_after is not None and self.copies >= self.break_after:
                raise pd.DeviceError("gone", name)
            time.sleep(0.05)
            self.copies += 1
            p = Path(dest) / name
            p.write_bytes(self.data[h][name])
            ts = time.mktime((2026, 7, 23, 14, 15, 0, 0, 0, -1))
            os.utime(p, (ts, ts))                # 셸 복사처럼 장치의 날짜가 남는다
            return p

    fake = FakeBackend()
    pd.BACKEND = fake
    Image.new("RGB", (300, 200), (30, 160, 60)).save(tmp / "폴더 사진.jpg", "JPEG")

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    tree = bt.tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 1)
    pump(timeout=0.5)
    devrows = lambda: [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                       if tree.topLevelItem(i).data(0, mw.DEVICE_ROLE)]

    # A
    chk(not devrows(), "A PDF 모드에는 장치 줄이 없다")
    bt.set_tree_view(True)                        # A~G 는 트리(폴더) 보기, H 는 단일 보기
    mw._set_photo_mode(True)
    chk(pump(lambda: len(devrows()) == 2, timeout=10), "A 사진 모드 — 장치 줄 둘", str([r.text(0) for r in devrows()]))
    chk([tree.topLevelItem(i).text(0) for i in range(2)] == ["Apple iPhone", "잠긴 폰"], "A 장치 줄은 책갈피창 맨 위(사용자 지시)",
        str([tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]))
    iph = next((r for r in devrows() if r.text(0) == "Apple iPhone"), None)
    IPH = lambda: next(r for r in devrows() if r.text(0) == "Apple iPhone")   # 목록을 다시 늘어놓으면 줄이 새로 생긴다 — 그때그때 찾는다
    kids = [iph.child(i).text(0) for i in range(iph.childCount())] if iph else []
    chk(kids == ["202611_a", "202610_a"], "A 아래에 사진 폴더 — 새것부터", str(kids))
    chk(all(n.data(0, bt.DATA_FILE) for n in bt._iter_file_nodes()) and
        [Path(str(n.data(0, bt.DATA_FILE))).name for n in bt._iter_file_nodes()] == ["폴더 사진.jpg"],
        "A 장치 줄은 파일 행이 아니다(파일 작업·색인이 닿지 않는다)")
    locked = next(r for r in devrows() if r.text(0) == "잠긴 폰")
    mw._photo_device_clicked(locked)
    chk("잠금을 풀고" in mw.status.currentMessage(), "A 잠긴 장치 — 알림만", mw.status.currentMessage())

    # B·C
    strip = mw._photo_strip
    gap, last = [0.0], [time.perf_counter()]

    def beat():
        now = time.perf_counter(); gap[0] = max(gap[0], now - last[0]); last[0] = now
    from PyQt6.QtCore import QTimer
    hb = QTimer(); hb.setInterval(10); hb.timeout.connect(beat); hb.start()
    mw._photo_device_clicked(IPH().child(0))
    names = lambda: [Path(p).name for p in strip.paths()]
    chk(pump(lambda: names() == ["IMG_0001.JPG", "IMG_0002.JPG", "IMG_0004.PNG"] and mw.__dict__.get("_photo_dev_worker") is None, timeout=10),
        "B 그 폴더 사진만 썸네일 줄에(사진 아닌 것은 빼고)", str(names()))
    hb.stop()
    cur = mw.main_view.current_file()
    chk(cur and Path(cur).name == "IMG_0001.JPG" and pd.is_cached(cur), "B 첫 장을 연다(캐시 사진)", str(cur))
    chk(mw.page_thumbs.title.text() == "Apple iPhone › 202611_a", "B 제목 '장치 › 폴더'", mw.page_thumbs.title.text())
    btn = mw._photo_info_btn
    chk(pump(lambda: "Apple iPhone › 202611_a › IMG_0001.JPG" in btn.text(), timeout=5), "B 상태 막대 '장치 › 폴더 › 이름'", btn.text())
    chk(gap[0] < 1.0, "C 받는 동안 메인 최장 공백 < 1초", "%.3f" % gap[0])
    raw = Path(cur).read_bytes()
    mw._photo_rotate(+90); pump(timeout=0.3)
    mw._photo_save_orientation(); pump(timeout=0.5)
    chk(Path(cur).read_bytes() == raw and "읽기 전용" in mw.status.currentMessage(), "C 읽기 전용 — 방향 저장 안 함", mw.status.currentMessage())
    chk(mw._photo_any_cached([cur]), "C 지우기·이름 바꾸기·일괄 작업 판정(읽기 전용)")
    mw._photo_rotate(-90); pump(timeout=0.2)

    # D
    before = fake.copies
    mw._photo_device_clicked(IPH().child(1)); pump(lambda: names() == ["IMG_0100.JPG"], timeout=5)
    mw._photo_device_clicked(IPH().child(0))
    pump(lambda: len(names()) == 3 and mw.__dict__.get("_photo_dev_worker") is None, timeout=5)
    chk(fake.copies == before + 1, "D 다시 열면 장치에서 다시 받지 않는다", "%d → %d" % (before, fake.copies))

    # E
    dest = tmp / "받은 곳"; dest.mkdir()
    from PyQt6.QtWidgets import QFileDialog
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(dest))
    mw._photo_copy_out(strip.paths()[:2]); pump(timeout=0.5)
    mw._photo_copy_out(strip.paths()[:1]); pump(timeout=0.5)
    got = sorted(os.listdir(dest))
    chk(got == ["IMG_0001 (2).JPG", "IMG_0001.JPG", "IMG_0002.JPG"], "E PC 로 복사 — 같은 이름이면 번호", str(got))

    # G — 트리(폴더) 보기
    from PyQt6.QtGui import QColor
    bt.set_tree_view(True)
    chk(pump(lambda: bool(devrows()) and next((r for r in devrows() if r.text(0) == "Apple iPhone"), None) is not None
             and next(r for r in devrows() if r.text(0) == "Apple iPhone").childCount() == 2, timeout=10), "G 트리 보기로 바꿔도 장치 줄")
    iph = next(r for r in devrows() if r.text(0) == "Apple iPhone")
    f0 = iph.child(0)
    yellow = QColor(bt.FOLDER_ROW_BG)
    chk(iph.isExpanded() and f0.background(0).color() == yellow and f0.font(0).bold(), "G 장치·사진 폴더가 폴더 줄 모양(펼침)")
    rows = [f0.child(i).text(0) for i in range(f0.childCount())]
    chk(f0.isExpanded() and rows == ["IMG_0001", "IMG_0002", "IMG_0004"], "G 연 폴더 아래 사진 줄", str(rows))
    chk([Path(str(n.data(0, bt.DATA_FILE))).name for n in bt._iter_file_nodes()] == ["폴더 사진.jpg"], "G 사진 줄도 파일 행이 아니다")
    mw._photo_device_clicked(f0.child(1)); pump(timeout=0.5)
    chk(Path(mw.main_view.current_file()).name == "IMG_0002.JPG" and len(names()) == 3, "G 사진 줄을 누르면 그 사진(줄은 그 폴더 그대로)")
    chk(bt.tree.currentItem() is f0.child(1), "G 본문 사진의 줄이 골라진다")
    mw._on_file_boundary(+1, mw._active_pane); pump(timeout=0.5)
    chk(bt.tree.currentItem() is f0.child(2), "G 넘기면 책갈피창도 그 사진 줄")
    bt.set_tree_view(False)
    pump(lambda: next((r for r in devrows() if r.text(0) == "Apple iPhone"), None) is not None, timeout=10)
    pump(timeout=0.5)
    iph = next(r for r in devrows() if r.text(0) == "Apple iPhone")
    # H — 단일 보기: 폴더 없이 장치의 모든 사진 줄(사용자 결정 '모든 사진을 파일 줄로')
    allrows = lambda: [iph.child(i).text(0) for i in range(iph.childCount())] if iph else []
    chk(pump(lambda: (lambda r: r == ["IMG_0001", "IMG_0002", "IMG_0004", "IMG_0100"])(
        [x.text(0) for x in [next(r for r in devrows() if r.text(0) == "Apple iPhone")] for _ in [0]] and
        [next(r for r in devrows() if r.text(0) == "Apple iPhone").child(i).text(0)
         for i in range(next(r for r in devrows() if r.text(0) == "Apple iPhone").childCount())]), timeout=10),
        "H 단일 보기 — 폴더 줄 없이 모든 사진 줄(새 폴더부터)", str(allrows()))
    iph = next(r for r in devrows() if r.text(0) == "Apple iPhone")
    chk(all(iph.child(i).childCount() == 0 and iph.child(i).background(0).color() != yellow for i in range(iph.childCount())),
        "H 폴더 줄 모양이 없다")
    chk([Path(str(n.data(0, bt.DATA_FILE))).name for n in bt._iter_file_nodes()] == ["폴더 사진.jpg"], "H 사진 줄도 파일 행이 아니다")
    r100 = next(iph.child(i) for i in range(iph.childCount()) if iph.child(i).text(0) == "IMG_0100")
    mw._photo_device_clicked(r100)
    chk(pump(lambda: mw.main_view.current_file() and Path(mw.main_view.current_file()).name == "IMG_0100.JPG"
             and names() == ["IMG_0100.JPG"] and mw.__dict__.get("_photo_dev_worker") is None, timeout=5),
        "H 다른 폴더 사진 줄을 누르면 그 폴더를 받아 그 사진을 연다", str(names()))
    chk(bt.tree.currentItem() is r100, "H 본문 사진의 줄이 골라진다")
    r2 = next(iph.child(i) for i in range(iph.childCount()) if iph.child(i).text(0) == "IMG_0002")
    shutil.rmtree(pd.cache_dir_for("Apple iPhone", "Internal Storage/202611_a"), ignore_errors=True)
    mw._photo_device_clicked(r2)
    chk(pump(lambda: mw.main_view.current_file() and Path(mw.main_view.current_file()).name == "IMG_0002.JPG", timeout=5)
        and pump(lambda: mw.__dict__.get("_photo_dev_worker") is None, timeout=5)
        and names() == ["IMG_0001.JPG", "IMG_0002.JPG", "IMG_0004.PNG"], "H 누른 사진부터 받아 열고, 줄은 이름 차례", str(names()))

    # I — 이어 받기(단일 보기, 202611_a 를 보는 중)
    pump(lambda: mw.__dict__.get("_photo_dev_worker") is None, timeout=5)
    mw._on_bookmark_activated(strip.paths()[-1], 0); pump(timeout=0.4)
    mw._on_file_boundary(+1, mw._active_pane)
    chk(pump(lambda: names() == ["IMG_0001.JPG", "IMG_0002.JPG", "IMG_0004.PNG", "IMG_0100.JPG"]
             and mw.main_view.current_file() and Path(mw.main_view.current_file()).name == "IMG_0100.JPG", timeout=5),
        "I 끝에서 넘기면 다음 폴더를 이어 받아 그 첫 장", str(names()))
    pump(lambda: mw.__dict__.get("_photo_dev_worker") is None, timeout=5)
    chk(mw.page_thumbs.title.text() == "Apple iPhone", "I 두 폴더를 이으면 제목은 장치 이름", mw.page_thumbs.title.text())
    hits = []
    strip.nearEnd.connect(lambda: hits.append(1))
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import Qt as _Qt
    strip.setCurrentRow(strip.count() - 1)
    QTest.keyClick(strip, _Qt.Key.Key_Down); pump(timeout=0.3)
    chk(len(hits) >= 1, "I 마지막 칸에서 ↓ 를 누르면 끝에 닿았다고 알린다")
    chk(mw.__dict__.get("_photo_dev_worker") is None and len(names()) == 4, "I 더 없으면 그대로")

    # J — 사진 일시
    chk(pump(lambda: "2026-07-23 14:15 (파일 날짜)" in btn.text(), timeout=5), "J 촬영 정보가 없는 사진 — 파일 날짜", btn.text())

    # F
    shutil.rmtree(pd.cache_dir_for("Apple iPhone", "Internal Storage/202611_a"), ignore_errors=True)
    fake.break_after = fake.copies + 1
    mw._photo_open_device("Apple iPhone", "Internal Storage/202611_a")
    chk(pump(lambda: mw.__dict__.get("_photo_dev_worker") is None, timeout=5) and names() == ["IMG_0001.JPG"]
        and "연결이 끊겼습니다" in mw.status.currentMessage(), "F 끊기면 받은 것만 두고 알림", f"{names()} {mw.status.currentMessage()}")
    # K — 장치 조사가 응답 없는 장치에 붙들려도 창 닫기는 기다리지 않는다(지휘 세션 확인 요청 — 닫은 뒤 main.py 가 곧바로 끝낸다)
    import threading
    hold = threading.Event()

    class StuckBackend(FakeBackend):
        def devices(self):
            hold.wait(20)                         # 응답 없는 장치
            return []
    pd.BACKEND = StuckBackend()
    mw._photo_devices_refresh(); pump(timeout=0.3)
    t0 = time.perf_counter()
    mw.close(); app.processEvents()
    chk(time.perf_counter() - t0 < 1.0, "K 장치 조사가 붙들려 있어도 창 닫기는 기다리지 않는다", "%.2f" % (time.perf_counter() - t0))
    hold.set()
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
