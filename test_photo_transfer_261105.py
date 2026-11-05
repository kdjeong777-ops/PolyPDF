# -*- coding: utf-8 -*-
"""사진 폴더로 복사·이동 (사진 보기 SOT §4.41, 261105-5 사용자 결정).

A. 메뉴 — '폴더로 복사 ▸'·'폴더로 이동 ▸', 최근 폴더 + '다른 폴더…', zip·휴대 장치 사진은 이동이 꺼진다
B. 복사(연 폴더 밖) — 바이트 그대로, 원본 남음, 대상 폴더 사이드카에 크롭·회전·꾸밈, 사진 정보 색인 행(OCR 글) 복사, 최근 폴더 맨 앞
C. 같은 이름 — '이름 (2).확장자'(덮어쓰지 않는다)
D. 이동(연 폴더 밖, 보던 사진) — 원본 없어짐, 연 폴더 사이드카 옛 키 지움·대상 사이드카에, 색인 행 옮김(옛 키 없음), 태그 따라옴, 다음 사진을 연다
E. 이동(연 폴더 안 하위 폴더) — 사이드카 키가 새 경로로(마스터 §4.7.14 한 길)
F. 파일 작업은 메인 스레드가 아니다(응답성 SOT) · zip·휴대 장치 캐시 사진은 이동 거절
실제 설정 폴더를 쓰지 않는다(마스터 §14.7.2 의 3).
"""
import os
import sys
import time
import shutil
import tempfile
import threading
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


app = QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_xfer_%d" % os.getpid())
import modal_guard
modal_guard.install(echo=False)
from PIL import Image

tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_xfer_"))
try:
    pix = tmp / "pix"
    (pix / "sub").mkdir(parents=True)
    out = tmp / "out"
    out.mkdir()
    for nm, c in (("a.jpg", (200, 0, 0)), ("b.jpg", (0, 200, 0)), ("c.jpg", (0, 0, 200))):
        ex = Image.Exif()
        ex[0x0132] = "2021:03:01 10:00:00"
        Image.new("RGB", (64, 48), c).save(pix / nm, "JPEG", exif=ex)
    A, B, C = pix / "a.jpg", pix / "b.jpg", pix / "c.jpg"
    a_bytes = A.read_bytes()
    from viewer import settings_store
    settings_store.save({"preferences": {"picture": {"mode": "photo", "view_kind": "mixed"}, "startup_mode": "none"}})
    from viewer.app import MainWindow
    win = MainWindow()
    win._skip_save_on_close = True
    win.show()

    def spin(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
    spin(1)
    win.open_folder(pix)
    spin(2)
    win._on_bookmark_activated(str(A), 0)
    spin(1)
    has = bool(getattr(win, "_photo_transfer", None))
    chk(has, "A 폴더로 복사·이동 길(_photo_transfer)")
    if has:
        st = win._ensure_page_meta_store()
        win._photo_set_crop(str(A), (0.5, 0.0, 1.0, 0.5))
        st.set_photo_rotation(str(A), 90)
        st.set_drawings(str(A), 0, [{"points": [[0.1, 0.1], [0.2, 0.2]], "width": 2}])
        st.save()
        bt = win.bookmark_tree
        if bt._tags is not None:
            bt._tags.set(str(A), ["여행"])
        from viewer import photo_index
        con = photo_index.connect()
        with con:
            for p in (A, B):
                photo_index.upsert(con, os.path.normcase(os.path.abspath(str(p))), str(p), photo_index.norm_folder(p.parent),
                                   p.name, ".jpg", p.stat().st_size, p.stat().st_mtime_ns, {}, [], ocr="hello" if p == A else "")
        con.close()

        def irow(p):
            c = photo_index.connect()
            try:
                return c.execute("SELECT ocr FROM photos WHERE key=?", (os.path.normcase(os.path.abspath(str(p))),)).fetchone()
            finally:
                c.close()

        # A. 메뉴
        win._photo_prefs()["transfer_dirs"] = [str(out)]
        m = QMenu()
        win._photo_xfer_menu(m, [str(A)])
        subs = [a.menu() for a in m.actions() if a.menu() is not None]
        labels = [[x.text() for x in s.actions() if not x.isSeparator()] for s in subs]
        chk(len(subs) == 2 and labels[0] == ["out", "다른 폴더..."] and labels[1] == ["out", "다른 폴더..."],
            "A 복사·이동 하위 메뉴 — 최근 폴더 + 다른 폴더…", str([s.title() for s in subs]) + str(labels))
        _cached = win._photo_any_cached
        win._photo_any_cached = lambda ps: True
        m2 = QMenu()
        win._photo_xfer_menu(m2, [str(A)])
        subs2 = [a.menu() for a in m2.actions() if a.menu() is not None]
        chk(len(subs2) == 2 and subs2[0].isEnabled() and not subs2[1].isEnabled(), "A zip·휴대 장치 사진 — 이동 꺼짐, 복사는 됨")
        r = win._photo_transfer([str(A)], str(out), True)
        chk(r == [] and A.exists(), "F zip·휴대 장치 사진은 이동 거절")
        win._photo_any_cached = _cached

        # B. 복사 — 연 폴더 밖
        seen_threads = []
        _copy2 = shutil.copy2

        def spy_copy2(*a, **k):
            seen_threads.append(threading.current_thread() is threading.main_thread())
            return _copy2(*a, **k)
        shutil.copy2 = spy_copy2
        win._photo_prefs()["transfer_dirs"] = []
        r = win._photo_transfer([str(A)], str(out), False)
        shutil.copy2 = _copy2
        spin(0.5)
        oa = out / "a.jpg"
        chk(oa.exists() and oa.read_bytes() == a_bytes and A.exists(), "B 복사 — 바이트 그대로, 원본 남음")
        chk(seen_threads == [False], "F 복사는 메인 스레드가 아니다(배경 진행 창)", str(seen_threads))
        from viewer.page_meta import PageMetaStore
        os_ = PageMetaStore(out)
        chk(os_.photo_crop(str(oa)) == (0.5, 0.0, 1.0, 0.5) and os_.photo_rotation(str(oa)) == 90
            and bool(os_.get_drawings(str(oa), 0)), "B 대상 폴더 사이드카에 크롭·회전·꾸밈")
        chk(irow(oa) == ("hello",) and irow(A) == ("hello",), "B 사진 정보 색인 행 복사(OCR 글)", str((irow(oa), irow(A))))
        chk(win._photo_prefs().get("transfer_dirs", [None])[0] == str(out), "B 최근 폴더 맨 앞")
        chk(bt._tags is None or not bt._tags.get(str(oa)), "B 태그는 복사하지 않는다(PDF 복사와 같다)")

        # C. 같은 이름
        win._photo_transfer([str(A)], str(out), False)
        chk((out / "a (2).jpg").exists(), "C 같은 이름 — '이름 (2).확장자'")

        # D. 이동 — 연 폴더 밖, 보던 사진
        _q = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        win._on_bookmark_activated(str(A), 0)
        spin(0.5)
        r = win._photo_transfer([str(A)], str(out), True)
        spin(1)
        na = out / "a (3).jpg"
        chk(not A.exists() and na.exists() and na.read_bytes() == a_bytes, "D 이동 — 원본 없어짐, 바이트 그대로", str(r))
        st = win._ensure_page_meta_store()
        chk(st.export_entry(str(A)) is None, "D 연 폴더 사이드카 — 옛 키 지움")
        chk(PageMetaStore(out).photo_crop(str(na)) == (0.5, 0.0, 1.0, 0.5), "D 대상 폴더 사이드카에 크롭")
        chk(irow(na) == ("hello",) and irow(A) is None, "D 사진 정보 색인 — 행을 새 경로로", str((irow(na), irow(A))))
        # 261105-6: 사진 자동 태그(촬영일 등, 태그 SOT §5.7)도 함께 붙어 있다 — 사용자 태그로 본다
        chk(bt._tags is None or (bt._tags.get_manual(str(na)) == ["여행"] and not bt._tags.get(str(A))), "D 태그가 따라온다",
            str(bt._tags.get(str(na)) if bt._tags else None))
        cur = win.main_view.current_file()
        chk(cur is not None and Path(cur).parent == pix, "D 보던 사진이 밖으로 — 다음 사진을 연다", str(cur))

        # E. 이동 — 연 폴더 안(하위 폴더)
        win._photo_set_crop(str(B), (0.0, 0.0, 0.5, 0.5))
        r = win._photo_transfer([str(B)], str(pix / "sub"), True)
        spin(1)
        nb = pix / "sub" / "b.jpg"
        st = win._ensure_page_meta_store()
        chk(nb.exists() and not B.exists() and st.photo_crop(str(nb)) == (0.0, 0.0, 0.5, 0.5) and st.photo_crop(str(B)) is None,
            "E 연 폴더 안 — 사이드카 키가 새 경로로(한 길)", str(r))
        QMessageBox.question = _q
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.stdout.flush()
os._exit(1 if fails else 0)
