# -*- coding: utf-8 -*-
"""사진 일괄 작업 — 이름 바꾸기·크기 줄이기·형식 바꾸기 (사진 보기 SOT 4.30, §5.1 F7, 261104-7 B5).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 이름 바꾸기 — '<이름>_001' 꼴, 확장자 그대로, 책갈피창 줄·태그·보기 회전(사이드카)이 새 이름을 따른다(마스터 §4.7.14 한 길)
B. 바꿀 이름이 이미 있으면(고른 것 밖의 파일) 하나도 바꾸지 않는다
C. 크기 줄이기 — 새 파일 '<이름>_<N>px', 긴 변 N, 원본 그대로, 보기 회전·EXIF 방향 적용, GPS 없음
D. 형식 바꾸기 — PNG → JPEG 새 파일, 원본 그대로
E. 썸네일 줄 메뉴에 '일괄 작업...'
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QMenu
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_batch_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "일괄 작업", echo=False)   # 마스터 §14.7.2 의 6
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


menu_texts = []
_orig_exec = QMenu.exec
QMenu.exec = lambda self, *a, **k: (menu_texts.clear(), menu_texts.extend(x.text().split("\t")[0] for x in self.actions()), None)[-1]

tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_batch_"))
try:
    from PIL import Image
    ex = Image.Exif(); ex[0x8825] = {1: "N", 2: (37.0, 30.0, 0.0)}
    Image.new("RGB", (4000, 3000), (200, 60, 60)).save(tmp / "가.jpg", "JPEG", exif=ex.tobytes())
    Image.new("RGB", (800, 600), (60, 160, 60)).save(tmp / "나.jpg", "JPEG")
    Image.new("RGB", (400, 300), (60, 60, 200)).save(tmp / "다.png", "PNG")
    Image.new("RGB", (100, 100), (9, 9, 9)).save(tmp / "막는_001.jpg", "JPEG")
    P = lambda n: str(tmp / n)

    from viewer.app import MainWindow
    from viewer.tag_store import TagStore
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    names = lambda: sorted(Path(str(it.data(0, bt.DATA_FILE))).name for it in bt._iter_file_nodes())
    pump(lambda: len(names()) == 4)
    bt.set_sort_mode(bt.SORT_NAME); pump()

    # E
    mw._on_bookmark_activated(P("가.jpg"), 0); pump(timeout=1.0)
    mw._photo_strip.menuRequested.emit(P("가.jpg"), QPoint(5, 5)); pump()
    chk("일괄 작업..." in menu_texts, "E 썸네일 줄 메뉴에 '일괄 작업...'", str(menu_texts))

    # C (이름 바꾸기 전에 — 가.jpg 를 돌려 둔다)
    mw._photo_rotate(+90); pump(timeout=0.5)
    made = mw._photo_batch_convert([P("가.jpg")], "size", side=1000); pump(timeout=0.5)
    chk([Path(m).name for m in made] == ["가_1000px.jpg"], "C 새 파일 '<이름>_<N>px'", str(made))
    if made:
        with Image.open(made[0]) as im:
            chk(im.size == (750, 1000), "C 긴 변 1000·보기 회전 적용(세로)", str(im.size))
            chk(not im.getexif().get_ifd(0x8825), "C GPS 없음")
    with Image.open(P("가.jpg")) as im:
        chk(im.size == (4000, 3000), "C 원본 그대로")

    # D
    made = mw._photo_batch_convert([P("다.png")], "format", fmt="jpg"); pump(timeout=0.5)
    chk([Path(m).name for m in made] == ["다.jpg"] and Path(P("다.png")).exists(), "D PNG → JPEG 새 파일, 원본 그대로", str(made))

    # B
    n = mw._photo_batch_rename([P("나.jpg")], "막는", 1); pump()
    chk(n == 0 and Path(P("나.jpg")).exists(), "B 바꿀 이름이 이미 있으면 바꾸지 않는다")

    # A
    tags = bt._tags or TagStore()                          # 앱이 쓰는 태그 저장소(책갈피창의 것)
    tags.set(P("나.jpg"), ["여행"])
    st = mw._ensure_page_meta_store()
    n = mw._photo_batch_rename([P("가.jpg"), P("나.jpg")], "바다", 1); pump(timeout=1.0)
    chk(n == 2 and Path(P("바다_001.jpg")).exists() and Path(P("바다_002.jpg")).exists() and not Path(P("가.jpg")).exists(),
        "A '<이름>_001' 꼴로 바뀐다", str(sorted(os.listdir(tmp))))
    chk("바다_001.jpg" in names() and "가.jpg" not in names(), "A 책갈피창 줄도 새 이름", str(names()))
    chk(tags.get(P("바다_002.jpg")) == ["여행"], "A 태그가 새 이름을 따른다", str(tags.get(P("바다_002.jpg"))))
    chk(st.photo_rotation(P("바다_001.jpg")) == 90, "A 보기 회전(사이드카)도 새 이름을 따른다", str(st.photo_rotation(P("바다_001.jpg"))))
    # A — 고른 것끼리 이름이 엇갈려도
    n = mw._photo_batch_rename([P("바다_002.jpg"), P("바다_001.jpg")], "바다", 1); pump(timeout=1.0)
    chk(n == 2 and len([x for x in os.listdir(tmp) if x.startswith("바다_00")]) == 2 and not any("polypix-ren" in x for x in os.listdir(tmp)),
        "A 고른 것끼리 이름이 엇갈려도(임시 이름을 거쳐) 바뀐다", str(sorted(os.listdir(tmp))))
    chk(tags.get(P("바다_001.jpg")) == ["여행"], "A 엇갈린 뒤에도 태그가 따라간다(옛 바다_002 → 바다_001)")
    mw.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    QMenu.exec = _orig_exec
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)          # Qt 소멸 단계 충돌을 피한다(MainWindow 검사 관례)
