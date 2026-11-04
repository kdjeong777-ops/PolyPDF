# -*- coding: utf-8 -*-
"""사진 정보 색인 (사진 보기 SOT 4.24, 결정 D19, 261104-4 조각 ①).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진 모드에서 폴더를 열면 하위 폴더까지 사진이 `photo_index.db` 에 들어간다 — PDF 는 들어가지 않는다
B. 행에 이름·보이는 크기(EXIF 방향 뒤)·촬영일·카메라·태그
C. 검색 — 이름·촬영일·카메라·태그(# 붙여도)로 찾는다, 폴더로 좁힌다
D. 다시 훑으면 바뀐 것만 — 그대로인 사진은 다시 읽지 않는다, 지운 사진은 행도 지운다
E. 사진 모드 검색창(조각 ②) — 결과가 썸네일 줄에 보이고 첫 사진이 열린다, 넘김은 결과 안에서, 빈 검색어면 폴더 전체로
"""
import os, sys, tempfile, shutil, time
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
QCoreApplication.setApplicationName("polypdf_photo_catalog_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 색인", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_catalog_"))
try:
    from PIL import Image
    import fitz
    ex = Image.Exif(); ex[0x0112] = 6; ex[0x010F] = "PolyCam"; ex[0x0110] = "Z9"
    ex.get_ifd(0x8769)[0x9003] = "2026:10:30 14:22:05"
    Image.new("RGB", (800, 400), (200, 60, 60)).save(tmp / "바다 노을.jpg", "JPEG", exif=ex.tobytes())
    (tmp / "하위").mkdir()
    Image.new("RGB", (300, 200), (30, 160, 60)).save(tmp / "하위" / "숲.png", "PNG")
    d = fitz.open(); d.new_page(); d.save(str(tmp / "문서.pdf")); d.close()

    from viewer import photo_index
    from viewer.tag_store import TagStore
    TagStore().set(str(tmp / "하위" / "숲.png"), ["여행", "가족"])

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump()
    done = []
    real_done = mw._photo_index_done

    def spy(folder, a, dd, n):
        done.append((a, dd, n))
        return real_done(folder, a, dd, n)
    mw._photo_index_done = spy
    mw.open_folder(tmp)
    chk(pump(lambda: bool(done), timeout=15), "A 사진 색인이 끝났다")

    con = photo_index.connect()
    rows = {r[0]: r for r in con.execute("SELECT name, width, height, taken, camera, tags FROM photos")}
    con.close()
    chk(set(rows) == {"바다 노을.jpg", "숲.png"}, "A 하위 폴더까지 사진만(PDF 없음)", str(sorted(rows)))
    r = rows.get("바다 노을.jpg")
    chk(r is not None and (r[1], r[2], r[3], r[4]) == (400, 800, "2026-10-30", "PolyCam Z9"), "B 보이는 크기·촬영일·카메라", str(r))
    chk("#여행" in (rows.get("숲.png") or ("",) * 6)[5], "B 태그", str(rows.get("숲.png")))

    # C
    names = lambda q, f=None: sorted(x["name"] for x in photo_index.search(q, folder=f))
    chk(names("바다") == ["바다 노을.jpg"], "C 이름으로", str(names("바다")))
    chk(names("2026-10") == ["바다 노을.jpg"], "C 촬영일로", str(names("2026-10")))
    chk(names("polycam") == ["바다 노을.jpg"], "C 카메라로(대소문자 무관)", str(names("polycam")))
    chk(names("#여행") == ["숲.png"] and names("여행") == ["숲.png"], "C 태그로(# 붙여도)", str(names("#여행")))
    chk(names("숲", tmp / "하위") == ["숲.png"] and names("바다", tmp / "하위") == [], "C 폴더로 좁힌다")

    # E
    Image.new("RGB", (320, 200), (90, 90, 90)).save(tmp / "다른.jpg", "JPEG")
    done.clear(); mw._photo_index_start(); pump(lambda: bool(done), timeout=10)
    mw.action_search("바다"); pump(timeout=0.8)
    strip = mw._photo_strip
    chk([Path(p).name for p in strip.paths()] == ["바다 노을.jpg"] and Path(mw.main_view.current_file()).name == "바다 노을.jpg",
        "E 검색 결과가 썸네일 줄에, 첫 사진이 열린다", str(strip.paths()))
    mw._on_file_boundary(+1, mw._active_pane); pump(timeout=0.5)
    chk(Path(mw.main_view.current_file()).name == "바다 노을.jpg", "E 넘김은 결과 안에서(한 장이라 그대로)")
    mw.action_search("없는낱말"); pump()
    chk([Path(p).name for p in strip.paths()] == ["바다 노을.jpg"], "E 찾은 것이 없으면 앞 결과 그대로(알림)")
    mw.action_search(""); pump(timeout=0.8)
    chk(len(strip.paths()) >= 2, "E 빈 검색어 → 폴더 전체", str([Path(p).name for p in strip.paths()]))

    # D
    done.clear()
    mw._photo_index_start()
    pump(lambda: bool(done), timeout=10)
    chk(done and done[-1][0] == 0 and done[-1][2] == 3, "D 그대로인 사진은 다시 읽지 않는다", str(done))
    (tmp / "하위" / "숲.png").unlink()
    done.clear()
    mw._photo_index_start()
    pump(lambda: bool(done), timeout=10)
    chk(done and done[-1][1] == 1 and names("숲") == [], "D 지운 사진은 행도 지운다", str(done))
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
