# -*- coding: utf-8 -*-
"""사진 모드 메뉴 — 책갈피창·썸네일 줄·본문 (사진 보기 SOT 4.20, 261104-3 사용자 지시).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3). 메뉴는 `QMenu.exec` 를 가로채 항목 글만 본다.
A. 사진 모드 책갈피창 사진 행 — 사진 항목(사진 복사·경로 복사·PDF 로 만들기·해시태그)이 있고, 뜻 없는 PDF 항목
   (병합·평탄화·변환·책갈피 생성·OCR·책갈피 펼치기)은 없다. 여러 장 고르면 '고른 사진 n장으로 PDF 만들기'
B. PDF 모드 PDF 행 메뉴는 종전 그대로(책갈피 생성·평탄화 …)
C. 경로 복사·사진 복사(배경 — 보기 회전까지 적용한 그림이 클립보드에)
D. 썸네일 줄 우클릭 메뉴 — 열기·돌리기·복사·탐색기·PDF 만들기·줄 전체로 PDF, 지금 사진이 아닌 칸도 돌릴 수 있고 그 썸네일이 돌아 보인다
E. 본문 사진 메뉴에 사진 복사·경로 복사·탐색기·사진 정보·PDF 로 만들기
F. 'PDF 로 만들기' 는 이미지 → PDF 창에 고른 사진을 넣어 연다
G. 썸네일 줄에서 Ctrl+클릭으로 여러 장 고른다 — 본문은 그대로, 고른 칸 위 우클릭은 고른 사진 모두에(PDF 만들기·돌리기)
   (261104-3 사용자 지시 '썸네일을 2개 이상 선택하는 게 안 돼' — 종전엔 한 장만 골랐다)
261105-16(사용자 지시 '썸네일 옵션 제일 위에도 인쇄 … 본화면 뷰어 옵션에서 쪽맞춤~원래크기 삭제, 인쇄를 사진복사 위에'):
D·G 썸네일 줄 메뉴 맨 위 '인쇄…'/'인쇄 (N장)…' → 사진 인쇄 길, E 본문 메뉴에 맞춤 없음·'인쇄…' 가 '사진 복사' 바로 위,
H 창 아래 맞춤 콤보에 사진 모드에만 '원래 크기'(사용자 결정 — 메뉴에서 빼면 닿을 길이 없어서)
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
QCoreApplication.setApplicationName("polypdf_photo_menus_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 메뉴", echo=False)   # 마스터 §14.7.2 의 6
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


seen = {"texts": [], "pick": None}
_orig_exec = QMenu.exec


def _all(menu):
    """하위(저장 ▸ 등)까지 — 하위를 여는 줄 자체는 빼고(261107-2)."""
    out = []
    for x in menu.actions():
        if x.isSeparator():
            continue
        if x.menu() is not None:
            out.extend(_all(x.menu()))
        else:
            out.append(x)
    return out


def fake_exec(self, *a, **k):
    acts = [x for x in self.actions() if not x.isSeparator()]
    seen["texts"] = [x.text().split("\t")[0] for x in acts]
    seen["all"] = [x.text().split("\t")[0] for x in _all(self)]
    pick = seen["pick"]
    seen["pick"] = None
    if pick:
        for x in _all(self):
            if x.text().split("\t")[0] == pick:
                return x                   # 메뉴(ctx_menu.CtxMenu.exec)가 눌러 준다
    return None


QMenu.exec = fake_exec

tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_menus_"))
try:
    from PIL import Image
    import fitz
    Image.new("RGB", (800, 400), (200, 60, 60)).save(tmp / "a 가로.jpg", "JPEG")
    Image.new("RGB", (600, 300), (60, 160, 60)).save(tmp / "b 가로.jpg", "JPEG")
    Image.new("RGB", (500, 250), (60, 60, 200)).save(tmp / "c3 가로.jpg", "JPEG")
    d = fitz.open(); d.new_page(); d.save(str(tmp / "c 문서.pdf")); d.close()
    a, b = str(tmp / "a 가로.jpg"), str(tmp / "b 가로.jpg")

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw.open_folder(tmp); pump(lambda: sum(1 for _ in bt._iter_file_nodes()) >= 1)

    def node(name):
        for it in bt._iter_file_nodes():
            if Path(str(it.data(0, bt.DATA_FILE))).name == name:
                return it
        return None

    def tree_menu(name):
        it = node(name)
        bt.tree.scrollToItem(it)
        bt._on_tree_context_menu(bt.tree.visualItemRect(it).center())
        return list(seen["texts"])

    # B — PDF 모드
    pump(lambda: node("c 문서.pdf") is not None)
    tx = tree_menu("c 문서.pdf")
    chk("책갈피 생성" in tx and "평탄화 사본" in seen["all"] and "사진 복사" not in tx, "B PDF 행 메뉴는 PDF 항목(평탄화 사본은 저장 ▸ 안, 261107-2)", str(tx))

    # A — 사진 모드
    mw._set_photo_mode(True)
    pump(lambda: node("a 가로.jpg") is not None and node("b 가로.jpg") is not None and node("c3 가로.jpg") is not None)
    bt.set_sort_mode(bt.SORT_NAME); pump()
    tx = tree_menu("a 가로.jpg")
    chk(tx[:1] == ["인쇄"], "A 사진 행 메뉴 맨 위 '인쇄'(261105-12 — 261107-2 '…' 뗌)", str(tx[:3]))
    for want in ("사진 복사", "해시태그 편집", "파일 탐색기 열기"):   # 261107-16: 경로 복사는 키로만
        chk(want in tx, "A 사진 행 메뉴에 '%s'" % want, str(tx))
    chk("PDF 만들기" in seen["all"], "A 사진 행 저장 ▸ 에 'PDF 만들기'(261107-2)", str(seen["all"]))
    for gone in ("다른 이름으로 저장", "평탄화해서 내보내기...", "책갈피 생성", "일괄 OCR", "책갈피 모두 펼치기", "용량 줄인 사본", "전달 묶음"):
        chk(gone not in seen["all"], "A 사진 행 메뉴에 '%s' 없음" % gone, str(seen["all"]))
    bt._edit_mode_saved = bt._edit_mode
    bt._edit_mode = True
    bt.tree.clearSelection()
    node("a 가로.jpg").setSelected(True); node("b 가로.jpg").setSelected(True)
    it = node("a 가로.jpg")
    bt._on_tree_context_menu(bt.tree.visualItemRect(it).center())
    tx = list(seen["texts"])
    chk("고른 사진 2장으로 PDF 만들기" in tx and not any("병합" in t for t in tx), "A 여러 장 — PDF 만들기(병합 없음)", str(tx))
    bt._edit_mode = bt._edit_mode_saved
    bt.tree.clearSelection()                       # 책갈피창 여러 장 고르기를 풀어 썸네일 줄이 폴더 전체(D3)

    # C
    mw._photo_action("copy_path", [a, b])
    chk(QApplication.clipboard().text() == a + "\n" + b, "C 경로 복사(여러 줄)")
    mw._on_bookmark_activated(a, 0); pump(timeout=0.5)
    mw._photo_rotate(+90); pump(timeout=0.5)
    QApplication.clipboard().clear()
    mw._photo_action("copy_image", [a])
    chk(pump(lambda: not QApplication.clipboard().image().isNull(), timeout=8), "C 사진 복사 — 클립보드에 그림")
    ci = QApplication.clipboard().image()
    chk((ci.width(), ci.height()) == (400, 800), "C 복사한 그림에 보기 회전 적용(400×800)", str((ci.width(), ci.height())))
    mw._photo_rotate(absolute=0); pump(timeout=0.5)

    # D
    strip = mw._photo_strip
    chk(pump(lambda: len(strip._done) >= 2, timeout=8), "D 썸네일 다 만듦")
    strip.menuRequested.emit(b, QPoint(10, 10)); pump()
    tx = list(seen["texts"])
    chk(tx[:2] == ["인쇄", "사진 복사"] and "열기" not in tx, "D 썸네일 줄 메뉴 맨 위 '인쇄'(261105-16), '열기' 없음(261107-2)", str(tx[:3]))
    printed = []
    _orig_pp = mw._photo_print
    mw._photo_print = lambda preset_scope=None, paths=None: printed.append(list(paths or []))
    seen["pick"] = "인쇄"
    strip.menuRequested.emit(b, QPoint(10, 10)); pump()
    chk(printed and printed[-1] == [b], "D 썸네일 '인쇄' — 누른 사진을 사진 인쇄 길로(_photo_print paths)", str(printed))
    for want in ("왼쪽 90° 회전", "오른쪽 90° 회전", "사진 복사", "파일 탐색기 열기", "PDF 만들기",
                 "줄의 사진 3장 모두로 PDF 만들기"):
        chk(want in seen["all"], "D 썸네일 줄 메뉴에 '%s'" % want, str(seen["all"]))
    seen["pick"] = "오른쪽 90° 회전"
    strip.menuRequested.emit(b, QPoint(10, 10))
    pump(lambda: b in strip._done, timeout=5); pump(timeout=0.5)
    st = mw._ensure_page_meta_store()
    chk(st.photo_rotation(b) == 90 and Path(mw.main_view.current_file()).name == "a 가로.jpg",
        "D 지금 사진이 아닌 칸도 돌린다(본문은 그대로)", str(st.photo_rotation(b)))
    def drawn_wh(it):
        """칸 그림 자리 안에서 실제 그림이 차지한 폭·높이(투명 여백 뺌 — photo_strip.boxed, 261104-8)."""
        im = it.icon().pixmap(strip.iconSize()).toImage()
        xs = [x for x in range(im.width()) if im.pixelColor(x, im.height() // 2).alpha() > 0]
        ys = [y for y in range(im.height()) if im.pixelColor(im.width() // 2, y).alpha() > 0]
        return (len(xs), len(ys))
    chk(pump(lambda: (lambda wh: wh[1] > wh[0])(drawn_wh(strip._items[b])), timeout=5),
        "D 그 썸네일이 돌아 보인다(세로)", str(drawn_wh(strip._items[b])))

    # E
    mw._photo_context_menu(QPoint(10, 10))
    tx = list(seen["texts"])
    for want in ("사진 복사", "파일 탐색기 열기", "사진 정보", "PDF 만들기", "왼쪽 90° 회전"):
        chk(want in seen["all"], "E 본문 사진 메뉴에 '%s'" % want, str(seen["all"]))
    for gone in ("쪽 맞춤", "폭 맞춤", "원래 크기 (100%)"):           # 261105-16 — 맞춤은 창 아래 콤보
        chk(gone not in tx, "E 본문 사진 메뉴에 '%s' 없음(261105-16)" % gone, str(tx))
    chk("인쇄" in tx and "사진 복사" in tx and tx.index("인쇄") + 1 == tx.index("사진 복사"),
        "E '인쇄' 가 '사진 복사' 바로 위(261105-16)", str(tx))

    # F
    got = []
    mw.action_image_to_pdf = lambda initial_paths=None: got.append(list(initial_paths or []))
    seen["pick"] = "줄의 사진 3장 모두로 PDF 만들기"
    strip.menuRequested.emit(a, QPoint(10, 10)); pump()
    chk(got and len(got[-1]) == 3, "F 줄 전체로 PDF 만들기 — 이미지 → PDF 창에 세 장", str(got))

    # G
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import Qt as _Qt
    c3 = str(tmp / "c3 가로.jpg")
    mw._on_bookmark_activated(a, 0); pump(timeout=0.5)

    def click(path, mod=_Qt.KeyboardModifier.NoModifier):
        it = strip._items[path]
        strip.scrollToItem(it)
        QTest.mouseClick(strip.viewport(), _Qt.MouseButton.LeftButton, mod, strip.visualItemRect(it).center())
        pump(timeout=0.4)
    click(b, _Qt.KeyboardModifier.ControlModifier)
    click(c3, _Qt.KeyboardModifier.ControlModifier)
    chk(sorted(strip.selected_paths()) == sorted([a, b, c3]), "G Ctrl+클릭으로 세 장 고름", str(strip.selected_paths()))
    chk(Path(mw.main_view.current_file()).name == "a 가로.jpg", "G Ctrl+클릭은 본문을 바꾸지 않는다", str(mw.main_view.current_file()))
    strip.menuRequested.emit(b, QPoint(10, 10)); pump()
    tx = list(seen["texts"])
    chk("고른 사진 3장으로 PDF 만들기" in tx and "오른쪽 90° 회전" in tx, "G 고른 칸 우클릭 — 고른 사진 모두에", str(tx))
    chk(tx[:1] == ["인쇄 (3장)"], "G 고른 칸 우클릭 맨 위 '인쇄 (3장)'(261105-16)", str(tx[:2]))
    seen["pick"] = "인쇄 (3장)"
    strip.menuRequested.emit(b, QPoint(10, 10)); pump()
    chk(printed and sorted(printed[-1]) == sorted([a, b, c3]), "G '인쇄 (3장)' — 고른 세 장을 사진 인쇄로", str(printed[-1:]))
    mw._photo_print = _orig_pp
    seen["pick"] = "고른 사진 3장으로 PDF 만들기"
    strip.menuRequested.emit(b, QPoint(10, 10)); pump()
    chk(got and sorted(got[-1]) == sorted([a, b, c3]), "G 고른 세 장으로 PDF 만들기", str(got[-1:]))
    seen["pick"] = "오른쪽 90° 회전"
    strip.menuRequested.emit(b, QPoint(10, 10)); pump(timeout=1.0)
    chk(st.photo_rotation(c3) == 90 and st.photo_rotation(a) == 90, "G 고른 사진 모두 돌린다", "%s %s" % (st.photo_rotation(a), st.photo_rotation(c3)))
    chk(len(strip.selected_paths()) == 3, "G 지금 사진을 다시 열어도 고른 것이 남는다", str(strip.selected_paths()))
    click(c3)
    chk(Path(mw.main_view.current_file()).name == "c3 가로.jpg" and len(strip.selected_paths()) == 1, "G 그냥 클릭은 그 사진을 열고 한 장만 고른다")

    # H — 창 아래 맞춤 콤보 '원래 크기'(사진 모드에만, 261105-16 사용자 결정)
    cmb, mv = mw.cmb_fit, mw.main_view
    i = cmb.findData("actual")
    chk(i == cmb.count() - 1 and cmb.itemText(i) == "원래 크기", "H 사진 모드 맞춤 콤보 끝에 '원래 크기'",
        str([cmb.itemText(k) for k in range(cmb.count())]))
    cmb.setCurrentIndex(i); pump(timeout=0.5)
    chk(mv._fit_mode == mv.FIT_NONE and abs(mv._zoom - 1.0) < 1e-6 and cmb.currentData() == "actual",
        "H '원래 크기' 를 고르면 100%·콤보는 '원래 크기'", str((mv._fit_mode, mv._zoom, cmb.currentData())))
    cmb.setCurrentIndex(cmb.findData(mv.FIT_PAGE)); pump(timeout=0.5)
    chk(mv._fit_mode == mv.FIT_PAGE, "H 다시 '쪽 맞춤' 은 본문 맞춤 그대로", str(mv._fit_mode))
    mw._set_photo_mode(False); pump(timeout=0.5)
    chk(mw.cmb_fit.findData("actual") < 0, "H PDF 모드 콤보에는 '원래 크기' 가 없다",
        str([cmb.itemText(k) for k in range(cmb.count())]))
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
