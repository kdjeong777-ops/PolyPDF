# -*- coding: utf-8 -*-
"""사진 모드 — 썸네일 줄·단추 켬/끔·모드별 즐겨찾기·최근·PDF 열면 PDF 모드·큰 폴더 (사진 보기 SOT 4.3·4.7·4.13·D1·D3·D9·§7 M2, 261104-2).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진을 열면 쪽 썸네일 자리에 **사진 썸네일 줄** — 그림이 배경에서 붙고, 사용자 데이터 폴더 캐시(`photo_thumbs`)에 남는다(사진 폴더에는 아무것도 쓰지 않는다)
B. 책갈피창에서 여럿 고르면 썸네일 줄은 고른 사진만, 하나면 폴더 전체(D3)
C. 사진 모드면 뜻 없는 명령(병합 등)이 꺼지고(OCR 은 사진 한 장 OCR 로 켜진다 — 261104-10), 설정 적용(`_gate_api_dependent_ui`)을 거쳐도 꺼진 채, PDF 모드로 오면 되살아난다
D. 즐겨찾기·최근 파일은 모드마다 따로 — 사진 것은 `picture` 묶음, 저장 내용의 `favorites` 는 PDF 것 그대로
E. 사진 모드에서 PDF 를 열면 PDF 모드로, 파일 인자 창(`_photo_force_pdf`)도 PDF 모드
F. `picture` 는 개인 항목 — 배포용 기본값에서 빠지고 초기화해도 남는다
G. 사진 3,000장 폴더: 모드 전환·폴더 열기·썸네일 만드는 동안 하트비트 최장 공백 < 1초(응답성 SOT §7.1)
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
QCoreApplication.setApplicationName("polypdf_photo_extras_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 모드 부가", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=20.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_extras_"))
try:
    from PIL import Image
    import fitz
    small = tmp / "작은"
    small.mkdir()
    for i in range(4):
        Image.new("RGB", (320, 240), (40 * i, 120, 200)).save(small / ("사진%d.jpg" % i), quality=85)
    d = fitz.open(); d.new_page(); d.save(str(small / "보고서.pdf")); d.close()

    from viewer.app import MainWindow
    from viewer.widgets import photo_strip
    from viewer import settings_store
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    pdf_favs_before = [dict(f) for f in mw._favorites]

    # C — 끄기 전 상태
    ocr = mw._cmds.get("tools.ocr")
    ocr_before = ocr.isEnabled() if ocr else None
    mrg = mw._cmds.get("tools.merge")                     # 261104-7: 발표는 이제 사진 슬라이드쇼로 켜진다 — 꺼지는 명령은 병합으로 본다
    pres_before = mrg.isEnabled()

    bt.load_folder(small); pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 1)
    mw._set_photo_mode(True)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 4), "사진 4장 목록")
    bt.set_sort_mode(bt.SORT_NAME); pump()

    # A
    mw._on_bookmark_activated(str(small / "사진1.jpg"), 0); pump()
    strip = mw._photo_strip
    chk(strip.isVisible() and not mw.page_thumbs.list.isVisible(), "A 쪽 썸네일 자리에 사진 썸네일 줄")
    chk(strip.count() == 4 and strip.currentItem() is not None and strip.currentItem().text().splitlines()[0] == "사진1", "A 줄에 4장, 지금 사진 선택",
        "%d %s" % (strip.count(), strip.currentItem().text() if strip.currentItem() else None))
    chk(pump(lambda: len(strip._done) == 4), "A 썸네일 그림이 배경에서 붙는다")
    cdir = photo_strip.cache_dir()
    cached = list(cdir.glob("*.jpg")) if cdir.is_dir() else []
    chk(len(cached) >= 4, "A 사용자 데이터 폴더 캐시에 남는다", str(cdir))
    chk(sorted(p.name for p in small.iterdir()) == ["보고서.pdf"] + ["사진%d.jpg" % i for i in range(4)],
        "A 사진 폴더에는 아무것도 쓰지 않는다", str(sorted(p.name for p in small.iterdir())))

    # B — 둘 고르기
    for it in bt._iter_file_nodes():
        it.setSelected(Path(it.data(0, bt.DATA_FILE)).name in ("사진0.jpg", "사진2.jpg"))
    mw._on_bookmark_activated(str(small / "사진2.jpg"), 0); pump()
    chk([Path(p).name for p in strip.paths()] == ["사진0.jpg", "사진2.jpg"], "B 여럿 고르면 고른 사진만", str(strip.paths()))
    for it in bt._iter_file_nodes():
        it.setSelected(Path(it.data(0, bt.DATA_FILE)).name == "사진3.jpg")
    mw._on_bookmark_activated(str(small / "사진3.jpg"), 0); pump()
    chk(len(strip.paths()) == 4, "B 하나면 폴더 전체")

    # C
    if ocr is not None and ocr_before:
        chk(ocr.isEnabled(), "C 사진 모드에서도 OCR 켜짐(사진 한 장 OCR — 261104-10 P4-a, 사진 보기 SOT 4.34)")
    chk(not mrg.isEnabled() and mw.act_present.isEnabled(), "C 병합 꺼짐·발표(F5)는 슬라이드쇼로 켜짐")
    mw._gate_api_dependent_ui(mw._prefs)
    chk(not mrg.isEnabled(), "C 설정 적용을 거쳐도 꺼진 채")

    # D — 사진 즐겨찾기·최근
    mw._favorites.append({"name": "사진 하나", "kind": "file", "file": str(small / "사진3.jpg"), "folder": str(small)})
    chk(any(Path(p).name == "사진3.jpg" for p in mw._recent_files), "D 사진의 최근 파일")
    payload = mw._build_settings_payload()
    chk(payload["favorites"] == pdf_favs_before, "D 저장 내용의 favorites 는 PDF 것 그대로")
    chk(any(f.get("name") == "사진 하나" for f in payload["preferences"]["picture"].get("favorites", [])),
        "D 사진 즐겨찾기는 picture 묶음에")
    chk(not any(str(p).lower().endswith(".jpg") for p in payload["recent_files"]), "D 저장 내용의 recent_files 에 사진 없음")

    # E — PDF 를 열면 PDF 모드
    mw.open_pdf(small / "보고서.pdf"); pump()
    chk(not mw._photo_mode, "E 사진 모드에서 PDF 를 열면 PDF 모드")
    chk(mrg.isEnabled() == pres_before and (ocr is None or ocr.isEnabled() == ocr_before),
        "C PDF 모드로 오면 꺼 둔 명령이 되살아난다")
    chk(mw._favorites == pdf_favs_before, "D PDF 모드 즐겨찾기 그대로")
    mw._set_photo_mode(True)
    chk(any(f.get("name") == "사진 하나" for f in mw._favorites), "D 사진 모드로 오면 사진 즐겨찾기")
    mw._photo_force_pdf()
    chk(not mw._photo_mode, "E 파일 인자 창은 PDF 모드")

    # F
    full = mw._build_settings_payload()
    dist = settings_store.extract_distributable_defaults(full)
    chk("picture" not in (dist.get("preferences") or {}), "F 배포용 기본값에 picture 없음")
    reset = settings_store.merge_reset(full, {"preferences": {}})
    chk("picture" in (reset.get("preferences") or {}), "F 초기화해도 picture 남음")

    # G — 3,000장
    big = tmp / "큰 폴더"
    big.mkdir()
    base = Image.new("RGB", (64, 48), (90, 120, 200))
    for i in range(3000):
        base.save(big / ("p%04d.jpg" % i), quality=60)
    beats = {"last": time.perf_counter(), "worst": 0.0}

    def beat():
        now = time.perf_counter()
        beats["worst"] = max(beats["worst"], now - beats["last"])
        beats["last"] = now
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(beat); hb.start()
    pump()
    beats["last"] = time.perf_counter(); beats["worst"] = 0.0
    mw._set_photo_mode(True); pump()                         # E 에서 PDF 모드로 돌려 두었다
    beats["last"] = time.perf_counter(); beats["worst"] = 0.0
    t0 = time.perf_counter()
    mw.open_folder(big)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3000, timeout=60), "G 3,000장 목록")
    t_list = time.perf_counter() - t0
    mw._on_bookmark_activated(str(big / "p0000.jpg"), 0)
    pump(lambda: len(mw._photo_strip._done) >= 200, timeout=60)
    mw._photo_strip.verticalScrollBar().setValue(mw._photo_strip.verticalScrollBar().maximum() // 2)
    pump(timeout=2.0)
    mw._set_photo_mode(False); pump(timeout=1.0)
    mw._set_photo_mode(True); pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3000, timeout=60)
    hb.stop()
    print("     3,000장 목록 %.2f초 · 하트비트 최장 공백 %.3f초 · 썸네일 %d장" % (t_list, beats["worst"], len(mw._photo_strip._done)))
    chk(beats["worst"] < 1.0, "G 큰 폴더 열기·썸네일·모드 전환 동안 최장 공백 < 1초", "%.3f초" % beats["worst"])
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
