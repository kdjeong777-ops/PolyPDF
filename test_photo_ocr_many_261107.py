# -*- coding: utf-8 -*-
"""261107-6: 사진 여러 장 OCR 로 읽기 — 배경 차례 읽기·작업 창·[중단]·사진마다 보류 저장소 (사진 보기 SOT §4.44, 응답성 SOT §4.4).

실제 MainWindow(오프스크린, 시험 프로필 — 마스터 §14.7.2 의 3). OCR 엔진은 가짜(`LangPicker.read_photo` — 한 장 0.4초,
읽는 동안 GIL 을 놓는 sleep)로 바꿔 Tesseract 없이도 같은 길을 잰다.
A. 썸네일 줄에서 셋 고르고 우클릭 → 도구 'OCR 로 읽기 (3장)' 이 켜져 있다(종전: 한 장만 — 꺼짐)
B. 누르면 작업 창에 '사진 OCR (3장)' 이 오르고, 끝나면 사진마다 보류 저장소에 낱말(`_photo_ocr_words`)·작업 창에서 내려간다
C. 도는 동안 메인 하트비트 공백 < 1초(응답성 SOT §2)
D. [중단](작업 창 cancel) — 읽던 사진이 끝난 뒤 멈추고 읽은 사진은 남는다, 다 읽지 않는다
E. 돌고 있으면 다시 눌러도 둘째 워커가 생기지 않는다
수정 전 코드로 실패한다(여러 장이면 'OCR 로 읽기' 가 꺼져 있고 `_photo_ocr_many` 가 없다).
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, QTimer
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_ocr_many_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 여러 장 OCR", echo=False)   # 마스터 §14.7.2 의 6
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(cond=None, timeout=10.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        app.processEvents()
        if cond is not None and cond():
            return True
        if cond is None and time.monotonic() - t > 0.3:
            return True
        time.sleep(0.01)
    return False


from viewer.study import ocr as _ocr
calls = []


def fake_read_photo(self, path, rot=0):
    calls.append(str(path))
    time.sleep(0.4)                                  # 엔진이 도는 동안(메인을 막지 않아야 한다)
    w = {"surface": "낱말", "lemma": "낱말", "x0": 10.0, "y0": 10.0, "x1": 60.0, "y1": 30.0, "conf": 90.0}
    return {"text": "낱말", "words": [w], "engine": "tesseract|" + _ocr.photo_sig(path), "conf": 90.0, "lang": "kor",
            "source": "ocr", "dpi": 72}


_ocr.LangPicker.read_photo = fake_read_photo

seen = {"menu": None, "pick": None}
_orig_exec = QMenu.exec


def fake_exec(self, *a, **k):
    seen["menu"] = self
    p, seen["pick"] = seen["pick"], None
    if p:
        for x in self.actions():
            if x.text().split("\t")[0] == p:
                return x
    return None


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_ocr_many_"))
try:
    from PIL import Image
    paths = []
    for i, col in enumerate(((200, 60, 60), (60, 160, 60), (60, 60, 200), (120, 120, 40), (40, 120, 120))):
        p = tmp / ("p%d.jpg" % i)
        Image.new("RGB", (400, 300), col).save(p, "JPEG")
        paths.append(str(p))
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw.open_folder(tmp)
    mw._set_photo_mode(True)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 5)
    mw._on_bookmark_activated(paths[0], 0); pump(timeout=0.8)
    strip = mw._photo_strip_widget()
    pump(lambda: len(strip.paths()) >= 5, timeout=8)
    QMenu.exec = fake_exec

    # A
    three = paths[:3]
    strip.clearSelection()
    for p in three:
        strip._items[p].setSelected(True)
    mw._photo_strip_menu(three[1], QPoint(5, 5))
    a_ocr = next((x for x in seen["menu"].actions() if x.text().split("\t")[0].startswith("OCR 로 읽기")), None) if seen["menu"] else None
    chk(a_ocr is not None and a_ocr.text().split("\t")[0] == "OCR 로 읽기 (3장)" and a_ocr.isEnabled(),
        "A 여러 장 — 'OCR 로 읽기 (3장)' 켜짐", a_ocr.text() if a_ocr else "없음")

    # B·C — 하트비트를 재며 돌린다
    beats = []
    hb = QTimer(); hb.setInterval(20); hb.timeout.connect(lambda: beats.append(time.monotonic())); hb.start()
    jobs_seen = []
    seen["pick"] = "OCR 로 읽기 (3장)"
    mw._photo_strip_menu(three[1], QPoint(5, 5))
    pump(lambda: bool(getattr(mw, "_jobs", {})), timeout=3)
    jobs_seen = [j["label"] for j in getattr(mw, "_jobs", {}).values()]
    chk(any(l == "사진 OCR (3장)" for l in jobs_seen), "B 작업 창에 '사진 OCR (3장)'", str(jobs_seen))
    done = pump(lambda: mw.__dict__.get("_photo_ocr_batch") is None and len(calls) >= 3, timeout=15)
    pump(timeout=0.3)
    hb.stop()
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    chk(done and sorted(calls) == sorted(three), "B 세 장을 차례로 읽었다", str([Path(c).name for c in calls]))
    chk(all(mw._photo_ocr_words(p) for p in three) and not mw._photo_ocr_words(paths[3]),
        "B 사진마다 보류 저장소에 낱말(고르지 않은 사진은 없음)")
    chk(not any(j["label"].startswith("사진 OCR") for j in getattr(mw, "_jobs", {}).values()), "B 끝나면 작업 창에서 내려간다")
    chk(gaps and max(gaps) < 1.0, "C 도는 동안 메인 공백 < 1초", "%.2f초" % (max(gaps) if gaps else -1))

    # D — [중단]
    calls.clear()
    two = paths[3:]
    strip.clearSelection()
    for p in two:
        strip._items[p].setSelected(True)
    mw._photo_ocr_many(two)
    pump(lambda: len(calls) >= 1, timeout=3)
    for j in list(getattr(mw, "_jobs", {}).values()):
        if j["label"].startswith("사진 OCR") and j.get("cancel"):
            j["cancel"]()
    # E — 도는 동안 다시
    w_before = mw.__dict__.get("_photo_ocr_batch")
    mw._photo_ocr_many(two)
    chk(w_before is not None and mw.__dict__.get("_photo_ocr_batch") is w_before, "E 돌고 있으면 둘째 워커를 만들지 않는다")
    pump(lambda: mw.__dict__.get("_photo_ocr_batch") is None, timeout=10)
    pump(timeout=0.3)
    chk(len(calls) == 1 and bool(mw._photo_ocr_words(calls[0])), "D [중단] — 읽던 한 장은 남고 다음은 읽지 않는다",
        str([Path(c).name for c in calls]))
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
