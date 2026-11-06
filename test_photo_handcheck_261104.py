# -*- coding: utf-8 -*-
"""사진 모드 — 사용자 손 확인에서 나온 결함 (사진 보기 SOT 4.3·4.4·4.12·4.13, 261104-2).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 사진 썸네일 줄이 썸네일 칸 **레이아웃 안**에 들어가 칸을 채운다(종전: 칸을 부모로만 두어 왼쪽 위 100×30 에 떠 있었다)
B. 쪽 칸은 사진 목록 안 순번 i / N(종전 '1 / 1'), 쪽 칸에 번호를 적으면 그 사진으로
C. 사진을 연 뒤에도 PDF 명령(병합)이 꺼져 있다(종전: 문서 권한 적용이 다시 켰다)
D. 꺼진 리본 단추는 글 색이 다르다(종전: 글 색이 고정이라 꺼져도 켜진 것과 같아 보였다) — 실제 단추를 그려 비교
   (261106-4: 사진 모드에서 병합은 숨으므로 잠시 보이게 해 잰다)
E. 맞춤은 작은 사진을 원본보다 키우지 않는다(120×160 사진이 8배로 늘어 흐렸다), 2장 맞춤에서도 사진은 한 장
F. (지킴) 미리 풀지 않은 사진을 연 뒤 배경 해독이 끝나면 메인 스레드에서 다시 그려 실제 사진이 보인다 — 수정 전에도 통과(지키는 검사).
   A~E 는 수정 전 코드에서 8건 실패를 확인했다.
G. 사진 썸네일 줄에서 ↓ 키로 옮기면 본문도 그 사진(261104-3 사용자 보고 — 종전엔 클릭만 받았다), 포커스는 줄에 남아 이어서 누를 수 있다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)             # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication, QToolBar
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from pathlib import Path

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_photo_hand_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 손 확인", echo=False)   # 마스터 §14.7.2 의 6
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


def text_ink(w):
    """단추를 그려 가장 진한 글 픽셀의 밝기(0=검정)."""
    img = w.grab().toImage()
    best = 255
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            best = min(best, (c.red() + c.green() + c.blue()) // 3)
    return best


tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_hand_"))
try:
    from PIL import Image
    for i, (w, h) in enumerate(((120, 160), (800, 600), (640, 480)), 1):
        Image.new("RGB", (w, h), (40 * i, 90, 160)).save(tmp / ("사진%d.jpg" % i), "JPEG")

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    bt.load_folder(tmp)
    chk(pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3), "사진 3장 목록")
    bt.set_sort_mode(bt.SORT_NAME); pump()
    lst = mw._photo_tree_list()
    mv = mw.main_view
    mv._fit_mode = mv.FIT_PAGE
    mw._on_bookmark_activated(lst[1], 0); pump(timeout=1.5)

    # A
    s = mw._photo_strip
    pt = mw.page_thumbs
    chk(pt.layout().indexOf(s) >= 0, "A 썸네일 줄이 썸네일 칸 레이아웃 안에")
    chk(s.isVisible() and s.height() > pt.height() // 2 and s.width() > pt.width() // 2,
        "A 썸네일 줄이 칸을 채운다", "줄 %dx%d · 칸 %dx%d" % (s.width(), s.height(), pt.width(), pt.height()))

    # B
    chk(mv.lbl_page_total.text() == "/ 3" and mv.spin_page.value() == 2, "B 쪽 칸 = 사진 목록 순번 2 / 3",
        "%s %s" % (mv.spin_page.value(), mv.lbl_page_total.text()))
    mv.spin_page.setValue(3); mv._on_spin_edited(); pump(timeout=1.0)
    chk(Path(mv.current_file()).name == "사진3.jpg" and mv.spin_page.value() == 3, "B 쪽 칸에 3 → 세 번째 사진",
        str(mv.current_file()))

    # C
    merge = mw._cmds.get("tools.merge")
    chk(merge is not None and not merge.isEnabled(), "C 사진을 연 뒤에도 병합이 꺼져 있다")

    # D — 같은 리본 줄의 꺼진 단추와 켜진 단추 글 색. 261106-4 부터 사진 모드의 PDF 전용 명령은 숨는다(사진 보기 SOT §4.13) —
    #   글 색 규칙(디자인 SOT §2.9.3 `BTN_OFF_FG`)만 보려고 꺼진 병합을 잠시 보이게 한다(끝에 다시 숨긴다)
    merge.setVisible(True); pump(timeout=0.3)
    off_w = on_w = None
    for tb in mw.findChildren(QToolBar):
        for a in tb.actions():
            w = tb.widgetForAction(a)
            if w is None or not w.isVisible() or a.isSeparator() or not a.text():
                continue
            if a is merge:
                off_w = w
            elif a.isEnabled() and on_w is None and a.menu() is None and tb.isAncestorOf(w):
                on_w = (tb, w)
        if off_w is not None and on_w is not None and on_w[0].isAncestorOf(off_w):
            break
        off_w, on_w = None, None
    if off_w is None:                                   # 병합이 보이는 줄이 없으면 그 줄을 띄운다
        mw._ribbon.select("tools") if hasattr(mw._ribbon, "select") else None
        pump()
        for tb in mw.findChildren(QToolBar):
            w = tb.widgetForAction(merge)
            if w is not None and w.isVisible():
                off_w = w
                for a in tb.actions():
                    ww = tb.widgetForAction(a)
                    if ww is not None and ww.isVisible() and a.isEnabled() and a.text() and a.menu() is None and not a.isSeparator():
                        on_w = (tb, ww)
                        break
                break
    if off_w is not None and on_w is not None:
        ink_off, ink_on = text_ink(off_w), text_ink(on_w[1])
        chk(ink_off - ink_on >= 60, "D 꺼진 리본 단추 글이 켜진 것보다 옅다", "꺼짐 %d · 켜짐 %d" % (ink_off, ink_on))
    else:
        chk(False, "D 병합 단추를 리본에서 찾았다")
    merge.setVisible(False); pump(timeout=0.2)

    # E
    mw._on_bookmark_activated(lst[0], 0); pump(timeout=1.5)
    item = mv._page_item
    dpr = item.pixmap().devicePixelRatio() if item is not None else 1.0
    size = (round(item.pixmap().width() / dpr), round(item.pixmap().height() / dpr)) if item is not None else None
    chk(size == (120, 160), "E 쪽 맞춤에서 120×160 사진은 원본 크기", str(size))
    mv._fit_mode = mv.FIT_PAGE_TWO
    mv._render_current(); pump()
    item = mv._page_item
    size2 = (round(item.pixmap().width() / dpr), round(item.pixmap().height() / dpr)) if item is not None else None
    chk(size2 == (120, 160), "E 2장 맞춤에서도 사진 한 장·원본 크기", str(size2))
    mv._fit_mode = mv.FIT_PAGE

    # G
    mw._on_bookmark_activated(lst[0], 0); pump(timeout=1.0)
    s.setFocus(); pump()
    QTest.keyClick(s, Qt.Key.Key_Down); pump(timeout=0.6)
    chk(Path(mv.current_file()).name == Path(lst[1]).name, "G 썸네일 줄 ↓ → 본문 두 번째 사진", str(mv.current_file()))
    QTest.keyClick(s, Qt.Key.Key_Down); pump(timeout=0.6)
    chk(Path(mv.current_file()).name == Path(lst[2]).name and s.hasFocus(), "G 한 번 더 ↓ → 세 번째, 포커스는 줄에",
        "%s focus=%s" % (mv.current_file(), s.hasFocus()))

    # F
    import threading
    from viewer import photo_doc
    from viewer.pdf_doc import GLOBAL_PAGE_CACHE
    Image.new("RGB", (3000, 2000), (200, 60, 60)).save(tmp / "사진4 큰.jpg", "JPEG")
    calls = []
    orig = mv._render_current

    def spy():
        calls.append(threading.current_thread() is threading.main_thread())
        return orig()
    mv._render_current = spy
    photo_doc.forget_decoded(); GLOBAL_PAGE_CACHE.clear()
    big = str(tmp / "사진4 큰.jpg")
    mw._on_bookmark_activated(big, 0)
    pump(timeout=4.0)
    mv._render_current = orig
    chk(len(calls) >= 1 and all(calls), "F 배경 해독 뒤 다시 그리기는 메인 스레드에서", str(calls))
    img = mv._page_item.pixmap().toImage() if mv._page_item is not None else None
    c = img.pixelColor(img.width() // 2, img.height() // 2) if img is not None else None
    chk(c is not None and c.red() > 150 and c.green() < 120, "F 본문이 임시 회색이 아니라 실제 사진", str(c and (c.red(), c.green(), c.blue())))
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
