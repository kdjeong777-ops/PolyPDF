# -*- coding: utf-8 -*-
"""사진 모드 — 본문에 고른 사진 한 장·넘김 (사진 보기 SOT 4.4 (다)·4.12·§7 M3, 261104-2).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진 모드에서 책갈피창 사진을 고르면 본문 문서는 **사진 문서** — 경로는 원본 사진, 쪽 1, 쪽 크기 = EXIF 방향 적용 뒤 픽셀
B. 본문에 그림이 그려진다(빈 화면 아님)
C. PDF 전용 가드가 그대로 꺼 준다 — 쪽 편집 저장 대상 아님, 경로가 .pdf 가 아니다
D. 경계 넘김(휠·PageDown 의 파일 경계)은 **묻지 않고** 책갈피창 차례 다음 사진, 끝이면 그대로(상태 표시줄 알림)
E. 24 MP 사진을 열고 넘기는 동안 하트비트 최장 공백 < 1초(응답성 SOT §7.1) — 앞뒤 사진은 배경에서 미리 푼다
F. PDF 모드에서는 종전대로(그림은 스크린샷 보기 `load_image`) — 사진 문서를 쓰지 않는다
"""
import os, sys, tempfile, shutil, time
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
QCoreApplication.setApplicationName("polypdf_photo_view_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 본문", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_view_"))
try:
    from PIL import Image
    import fitz

    def photo(path, w, h, orient=None, noise=False):
        im = Image.new("RGB", (w, h), (40, 60, 200))
        im.paste(Image.new("RGB", (w, h // 2), (220, 40, 40)), (0, 0))
        if noise:
            nz = Image.merge("RGB", [Image.effect_noise((w, h), 60) for _ in range(3)])
            im = Image.blend(im, nz, 0.35)
        ex = Image.Exif()
        if orient:
            ex[0x0112] = orient
        im.save(path, "JPEG", quality=90, exif=ex.tobytes())

    photo(tmp / "1 세로.jpg", 800, 400, orient=6)
    photo(tmp / "2 큰 사진.jpg", 6000, 4000, noise=True)          # 24 MP 12MB 쯤
    photo(tmp / "3 큰 사진.jpg", 6000, 4000, noise=True)
    d = fitz.open(); d.new_page(); d.save(str(tmp / "보고서.pdf")); d.close()

    from viewer.app import MainWindow
    from viewer.photo_doc import PhotoDocument
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()

    # F — PDF 모드: 그림은 종전 길
    bt.load_folder(tmp); pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 1)
    mw._on_bookmark_activated(str(tmp / "1 세로.jpg"), 0); pump()
    chk(not isinstance(getattr(mw.main_view, "_doc", None), PhotoDocument), "F PDF 모드에서는 사진 문서를 쓰지 않는다")

    mw._set_photo_mode(True)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3), "사진 3장 목록")
    bt.set_sort_mode(bt.SORT_NAME); pump()                               # 넘김은 책갈피창 차례를 따른다 — 이름 순으로 두고 잰다

    # A·B·C
    mw._on_bookmark_activated(str(tmp / "1 세로.jpg"), 0); pump()
    doc = mw.main_view._doc
    chk(isinstance(doc, PhotoDocument), "A 본문 문서는 사진 문서")
    chk(str(mw.main_view.current_file()) == str(tmp / "1 세로.jpg"), "A 경로는 원본 사진")
    chk(doc is not None and doc.page_count == 1 and tuple(map(round, doc.doc[0].rect[2:])) == (400, 800),
        "A 쪽 1·크기는 방향 적용 뒤 픽셀(400×800)", str(doc.doc[0].rect if doc else None))
    item = getattr(mw.main_view, "_page_item", None)
    chk(item is not None and not item.pixmap().isNull() and item.pixmap().height() > item.pixmap().width(),
        "B 본문에 세로 그림이 그려진다")
    chk(not mw._page_edits_dirty() and not str(mw.main_view.current_file()).lower().endswith(".pdf"),
        "C PDF 전용 가드 그대로(쪽 편집 저장 대상 아님)")

    # D·E — 넘김 + 하트비트
    beats = {"last": time.perf_counter(), "worst": 0.0}

    def beat():
        now = time.perf_counter()
        beats["worst"] = max(beats["worst"], now - beats["last"])
        beats["last"] = now
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(beat); hb.start()
    pump()
    beats["last"] = time.perf_counter(); beats["worst"] = 0.0
    mw._on_file_boundary(+1, mw._active_pane); pump()
    chk(Path(mw.main_view.current_file()).name == "2 큰 사진.jpg", "D 다음 사진(묻지 않음)", str(mw.main_view.current_file()))
    pump(timeout=2.0)                                                      # 다음 사진 미리 풀기
    t0 = time.perf_counter()
    mw._on_file_boundary(+1, mw._active_pane); pump()
    t_next = time.perf_counter() - t0
    chk(Path(mw.main_view.current_file()).name == "3 큰 사진.jpg", "D 그다음 사진")
    mw._on_file_boundary(+1, mw._active_pane); pump()
    chk(Path(mw.main_view.current_file()).name == "3 큰 사진.jpg", "D 목록 끝이면 그대로(처음으로 돌지 않는다)")
    hb.stop()
    print("     하트비트 최장 공백 %.3f초 · 미리 푼 사진으로 넘김 %.3f초" % (beats["worst"], t_next))
    chk(beats["worst"] < 1.0, "E 24 MP 열기·넘김 동안 최장 공백 < 1초", "%.3f초" % beats["worst"])
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
