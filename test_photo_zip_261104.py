# -*- coding: utf-8 -*-
"""사진이 든 zip (사진 보기 SOT 4.24, 결정 D19, 261104-4 조각 ③·④).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진 모드 목록에 사진이 든 zip 은 보이고 사진이 없는 zip 은 안 보인다(PDF 모드에는 zip 이 없다)
B. zip 줄을 누르면 안의 사진을 꺼내 썸네일 줄에 보이고 첫 장을 연다 — 넘김은 zip 안에서
C. zip 안 사진은 읽기 전용 — 공유용 사본·방향 저장을 하지 않는다, 원본 zip 그대로
D. 색인에 zip 안 사진이 들어가고(열쇠 = zip|안 이름), 검색하면 그 zip 을 열어 보인다
E. zip 밖 사진을 누르면 썸네일 줄은 다시 폴더 사진
F. 경로 탈출(../·드라이브·절대 경로) 이름은 캐시 폴더 밖에 쓰지 않는다, 압축 폭탄(풀린 크기 ÷ 압축 크기가 큰 항목)은 뺀다
G. 사진 색인 DB 가 손상되면 지우고 새로 만든다(캐시 — 마스터 §8.3.1)
"""
import os, sys, tempfile, shutil, time, zipfile, io
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
QCoreApplication.setApplicationName("polypdf_photo_zip_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 zip", echo=False)   # 마스터 §14.7.2 의 6
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


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_zip_"))
try:
    from PIL import Image
    import fitz
    Image.new("RGB", (300, 200), (30, 160, 60)).save(tmp / "밖.jpg", "JPEG")

    def jpg_bytes(color, size=(400, 300)):
        b = io.BytesIO(); Image.new("RGB", size, color).save(b, "JPEG"); return b.getvalue()
    with zipfile.ZipFile(tmp / "여행 사진.zip", "w") as z:
        z.writestr("여행/첫날 해변.jpg", jpg_bytes((200, 60, 60)))
        z.writestr("여행/둘째날 산.jpg", jpg_bytes((60, 60, 200), (300, 400)))
        z.writestr("메모.txt", "글")
    with zipfile.ZipFile(tmp / "문서만.zip", "w") as z:
        z.writestr("a.txt", "x")
    d = fitz.open(); d.new_page(); d.save(str(tmp / "보고서.pdf")); d.close()
    zp = str(tmp / "여행 사진.zip")
    zraw = Path(zp).read_bytes()

    from viewer.app import MainWindow
    from viewer import photo_zip, photo_index
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1200, 800); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 1)
    names = lambda: sorted(Path(str(it.data(0, bt.DATA_FILE))).name for it in bt._iter_file_nodes())
    chk(names() == ["보고서.pdf"], "A PDF 모드에는 zip 이 없다", str(names()))
    idx_done = []
    real_done = mw._photo_index_done
    mw._photo_index_done = lambda f, a, dd, n: (idx_done.append((a, dd, n)), real_done(f, a, dd, n))
    mw._set_photo_mode(True)
    chk(pump(lambda: names() == ["밖.jpg", "여행 사진.zip"]), "A 사진 모드 — 사진이 든 zip 만 보인다", str(names()))

    # B
    mw._on_bookmark_activated(zp, 0)
    strip = mw._photo_strip
    chk(pump(lambda: len(strip.paths()) == 2, timeout=10), "B zip 안 사진 2장이 썸네일 줄에", str(strip.paths()))
    cur = mw.main_view.current_file()
    chk(cur and photo_zip.is_cached(cur) and Path(cur).name == "둘째날 산.jpg", "B 첫 장(이름 차례)을 연다 — 꺼낸 사진", str(cur))
    mw._on_file_boundary(+1, mw._active_pane); pump(timeout=0.5)
    chk(Path(mw.main_view.current_file()).name == "첫날 해변.jpg", "B 넘김은 zip 안에서")

    # C
    before = set(os.listdir(Path(cur).parent))
    mw._photo_action("share_all", [mw.main_view.current_file()]); pump(timeout=1)
    chk(set(os.listdir(Path(cur).parent)) == before, "C 공유용 사본을 만들지 않는다(읽기 전용)")
    mw._photo_rotate(+90); pump(timeout=0.3)
    mw._photo_save_orientation(); pump(timeout=0.5)
    chk(Path(zp).read_bytes() == zraw, "C 원본 zip 그대로")

    # D
    chk(pump(lambda: bool(idx_done), timeout=15), "D 사진 색인 끝")
    con = photo_index.connect()
    keys = sorted(r[0] for r in con.execute("SELECT member FROM photos WHERE zip IS NOT NULL"))
    con.close()
    chk(keys == ["여행/둘째날 산.jpg", "여행/첫날 해변.jpg"], "D zip 안 사진이 색인에", str(keys))
    mw._on_bookmark_activated(str(tmp / "밖.jpg"), 0); pump(timeout=0.5)
    # E
    chk(sorted(Path(p).name for p in strip.paths()) == ["밖.jpg"], "E zip 밖 사진을 누르면 썸네일 줄은 폴더 사진", str(strip.paths()))
    mw.action_search("해변")
    chk(pump(lambda: any(Path(p).name == "첫날 해변.jpg" for p in strip.paths()), timeout=10), "D 검색 '해변' → 그 zip 을 열어 보인다",
        str(strip.paths()))
    # F
    evil = tmp / "위험.zip"
    with zipfile.ZipFile(evil, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("../../탈출.jpg", jpg_bytes((10, 10, 10)))
        z.writestr("C:/Windows/드라이브.jpg", jpg_bytes((20, 20, 20)))
        z.writestr("/abs/절대.jpg", jpg_bytes((30, 30, 30)))
        z.writestr("폭탄.jpg", b"\0" * (40 * 1024 * 1024))          # 40 MB 0 — 압축하면 수십 KB
    members = photo_zip.photo_members(evil)
    chk("폭탄.jpg" not in members and len(members) == 3, "F 압축 폭탄 항목은 뺀다", str(members))
    out = photo_zip.extract(evil)
    root = photo_zip.cache_dir_for(evil)
    chk(len(out) == 3 and all(photo_zip._inside(root, Path(o)) for o in out), "F 꺼낸 것은 모두 캐시 폴더 안", str(out))
    chk(not (tmp.parent / "탈출.jpg").exists() and not Path("C:/Windows/드라이브.jpg").exists(), "F 밖에 쓰지 않았다")

    # G
    dbp = photo_index.db_path()
    for suf in ("-wal", "-shm"):
        try:
            os.remove(str(dbp) + suf)
        except OSError:
            pass
    dbp.write_bytes(b"not a database" * 100)
    con = photo_index.connect()
    n = con.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    con.close()
    chk(n == 0, "G 손상된 사진 색인은 새로 만든다")
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
