# -*- coding: utf-8 -*-
"""사진 보기 회전·맞춤 (사진 보기 SOT 4.11 '보기 회전'·4.16, 입력 SOT §3.2.2, 261104-3).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 오른쪽으로 돌리면 쪽 자체가 돈다 — 800×400 사진의 쪽이 400×800, 그림의 위(빨강)가 오른쪽으로
B. 값은 폴더 사이드카 맨 위 `photo_rot` 묶음(디스크에 바로) — PDF 쪽 회전 대기값(`rotation`)에는 없다, 편집 저장 대기·쪽 편집 저장 대상 아님,
   다른 사진으로 갈 때 '저장하지 않은 편집' 을 묻지 않는다, 원본 사진은 그대로
C. 다른 사진을 갔다 와도 그 회전 그대로, 원래 방향이면 사이드카 키가 지워진다
D. 돌린 사진에서도 꾸밈이 사진과 함께 돌아 보이고(4.19), 그 위에서 고친 것은 회전 0 판 좌표로 되돌려 남는다 — 꾸미기 줄은 켜져 있다
E. 돌리기 키(Ctrl+] · Ctrl+[) — 사진이면 사진 회전, PDF 면 지금 쪽 회전(쪽 메뉴와 같은 길)
F. 사진 본문 우클릭은 사진 메뉴(돌리기·맞춤), 원래 크기(100%) = 사진 픽셀 그대로
"""
import os, sys, tempfile, shutil, time, json, hashlib
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication, Qt
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_rot_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 회전", echo=False)   # 마스터 §14.7.2 의 6
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


def sidecar(folder):
    p = Path(folder) / "page_meta.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"files": {}}


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_rot_"))
try:
    from PIL import Image
    import fitz
    im = Image.new("RGB", (800, 400), (40, 60, 200))
    im.paste(Image.new("RGB", (800, 200), (220, 40, 40)), (0, 0))      # 위 절반 빨강
    im.save(tmp / "a 가로.jpg", "JPEG", quality=92)
    Image.new("RGB", (300, 200), (30, 160, 60)).save(tmp / "b 초록.jpg", "JPEG")
    d = fitz.open(); d.new_page(); d.new_page(); d.save(str(tmp / "c 문서.pdf")); d.close()
    a_path = str(tmp / "a 가로.jpg")
    a_hash = hashlib.sha1(Path(a_path).read_bytes()).hexdigest()

    from viewer.app import MainWindow
    from viewer.photo_doc import PhotoDocument
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 2), "사진 2장 목록")
    mv = mw.main_view
    mv._fit_mode = mv.FIT_PAGE
    mw._on_bookmark_activated(a_path, 0); pump(timeout=1.0)

    # D 준비 — 회전 0 판에 선 하나
    _st = mw._ensure_page_meta_store()                     # 저장된 꾸밈(편집 저장 대기 없이)
    _st.set_drawings(a_path, 0, [{"points": [[0.1, 0.1], [0.9, 0.1]], "pen": 0, "width": 3}])
    _st.save()
    mw._on_bookmark_activated(a_path, 0); pump(timeout=0.5)
    chk(len(mv._page_strokes) == 1, "D 준비 — 회전 0 에서 선 1개가 보인다")

    # A
    mw._photo_rotate(+90); pump(timeout=1.0)
    doc = mv._doc
    chk(isinstance(doc, PhotoDocument) and tuple(map(round, doc.doc[0].rect[2:])) == (400, 800),
        "A 쪽이 400×800 으로 돈다", str(doc.doc[0].rect if doc else None))
    img = mv._page_item.pixmap().toImage()
    right = img.pixelColor(img.width() * 3 // 4, img.height() // 2)
    left = img.pixelColor(img.width() // 4, img.height() // 2)
    chk(img.height() > img.width() and right.red() > 150 and left.blue() > 150,
        "A 그림의 위(빨강)가 오른쪽으로 — 시계 방향", "오른쪽 %s 왼쪽 %s" % (right.getRgb(), left.getRgb()))

    # B
    sc = sidecar(tmp)
    rec = sc["files"].get("a 가로.jpg", {})
    chk(sc.get("photo_rot") == {"a 가로.jpg": 90} and not rec.get("rotation"),
        "B 사이드카 photo_rot 묶음에 90(디스크에 바로), PDF 회전 대기값은 비어 있다", str(sc))
    chk(not getattr(mw, "_edit_dirty", False), "B 편집 저장 대기로 치지 않는다(다른 사진으로 갈 때 묻지 않는다)")
    chk(not mw._page_edits_dirty(), "B 쪽 편집 저장 대상이 아니다")
    chk(hashlib.sha1(Path(a_path).read_bytes()).hexdigest() == a_hash, "B 원본 사진은 그대로")

    # D
    pts = [[round(x, 4), round(y, 4)] for x, y in (mv._page_strokes[0]["points"] if mv._page_strokes else [])]
    chk(pts == [[0.9, 0.1], [0.9, 0.9]] and mv._draw_bar.isEnabled(),
        "D 돌린 사진에서 선이 함께 돈다((0.1,0.1)-(0.9,0.1) → (0.9,0.1)-(0.9,0.9)), 꾸미기 줄 켜짐", str(pts))
    shown = [dict(s) for s in mv._page_strokes]
    shown.append({"points": [[0.5, 0.25], [0.5, 0.75]], "pen": 1, "width": 3})          # 돌린 쪽 위에서 세로선 하나 더
    mw._set_drawings(a_path, 0, shown)
    saved = mw._ensure_page_meta_store().get_drawings(a_path, 0)
    back = [[[round(x, 4), round(y, 4)] for x, y in s["points"]] for s in saved]
    chk(back == [[[0.1, 0.1], [0.9, 0.1]], [[0.25, 0.5], [0.75, 0.5]]],
        "D 돌린 쪽 위에서 고친 것은 회전 0 판 좌표로 되돌려 남는다", str(back))
    mw._set_drawings(a_path, 0, mv._page_strokes[:1] or shown[:1])
    mw._commit_edit(); mw._edit_dirty = False              # 고친 꾸밈을 저장(다음 파일로 갈 때 묻지 않게)

    # C
    mw._on_bookmark_activated(str(tmp / "b 초록.jpg"), 0); pump(timeout=0.5)
    chk(mv._draw_bar.isEnabled(), "D 다른 사진에서도 꾸미기 줄이 켜져 있다")
    mw._on_bookmark_activated(a_path, 0); pump(timeout=0.5)
    chk(tuple(map(round, mv._doc.doc[0].rect[2:])) == (400, 800), "C 다른 사진을 갔다 와도 회전 그대로")
    mw._photo_rotate(absolute=0); pump(timeout=0.5)
    chk("photo_rot" not in sidecar(tmp) and tuple(map(round, mv._doc.doc[0].rect[2:])) == (800, 400), "C 원래 방향이면 키가 지워지고 쪽도 원래대로")
    chk(len(mv._page_strokes) >= 1 and mv._draw_bar.isEnabled(), "D 원래 방향이면 회전 0 판 그대로 보인다")

    # F
    mw._on_bookmark_activated(a_path, 0); pump(timeout=0.5)
    seen = []
    orig_menu = mw._photo_context_menu
    mw._photo_context_menu = lambda gp: seen.append(gp)
    mw._on_viewer_context_menu(mv.mapToGlobal(mv.rect().center()))
    mw._photo_context_menu = orig_menu
    chk(len(seen) == 1, "F 사진 본문 우클릭은 사진 메뉴")
    mw._photo_zoom_actual(); pump()
    pm = mv._page_item.pixmap()
    dpr = pm.devicePixelRatio()
    chk((round(pm.width() / dpr), round(pm.height() / dpr)) == (800, 400), "F 원래 크기 = 사진 픽셀 그대로",
        str((pm.width() / dpr, pm.height() / dpr)))
    mv._fit_mode = mv.FIT_PAGE; mv._render_current()
    # E — 키
    mw.activateWindow(); mv.view.setFocus(); pump()
    QTest.keyClick(mw, Qt.Key.Key_BracketRight, Qt.KeyboardModifier.ControlModifier); pump(timeout=0.5)
    chk(mw._photo_rot_for(a_path) == 90, "E Ctrl+] — 사진 오른쪽으로", str(mw._photo_rot_for(a_path)))
    QTest.keyClick(mw, Qt.Key.Key_BracketLeft, Qt.KeyboardModifier.ControlModifier); pump(timeout=0.5)
    chk(mw._photo_rot_for(a_path) == 0, "E Ctrl+[ — 사진 왼쪽으로(원래 방향)")
    mw._set_photo_mode(False); pump()
    pdf = str(tmp / "c 문서.pdf")
    mw._on_bookmark_activated(pdf, 1); pump(timeout=1.0)
    QTest.keyClick(mw, Qt.Key.Key_BracketRight, Qt.KeyboardModifier.ControlModifier); pump(timeout=1.0)
    st = mw._ensure_page_meta_store()
    chk(st.rotations(pdf) == {1: 90}, "E PDF 에서는 지금 쪽(2쪽) 회전 — 쪽 메뉴와 같은 길", str(st.rotations(pdf)))
    chk(st.photo_rotation(pdf) == 0, "E PDF 에는 사진 회전 값이 없다")
    mw._set_photo_mode(True); pump()

    mv._fit_mode = mv.FIT_PAGE
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
