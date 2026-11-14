# -*- coding: utf-8 -*-
"""261112-20: 스크린샷 창의 컷을 누르면 2단 오른쪽 창에 (스크린샷 SOT §5, 사용자 지시·결정).

A. PDF 모드 1단 — 컷을 누르면 2단이 켜지고(2단 단추도 켜짐) 오른쪽 창에 컷, 왼쪽은 보던 PDF 그대로, 활성 창은 오른쪽
B. 다른 컷을 누르면 같은 오른쪽 창에서 바뀐다, 왼쪽 그대로, ◀▶(오른쪽 창)로 다음 컷
C. 이미 2단이고 오른쪽에 다른 PDF — 컷이 오른쪽을 바꾸고 왼쪽 그대로
D. 1단 단추로 1단 복귀
E. 사진 모드 — 왼쪽 사진 그대로, 오른쪽에 컷
수정 전 코드는 A·B·C·E 가 실패한다(보던 본문이 컷으로 바뀌고 1단 그대로).
"""
import os, sys, time, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import faulthandler
faulthandler.dump_traceback_later(180, exit=True)
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_shot_split_%d" % os.getpid())
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
import modal_guard
modal_guard.install(label=lambda: "스크린샷 2단", echo=False)
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


def key(p):
    return os.path.normcase(os.path.abspath(str(p))) if p else None


COL = {"red": (255, 0, 0), "blue": (0, 0, 255), "green": (0, 128, 0), "yellow": (255, 255, 0)}


def shown(mv):
    """창에 떠 있는 것 — PDF·사진 문서면 경로 키, 그림(컷)이면 그 색 이름(load_image 는 경로를 남기지 않는다)."""
    f = mv.current_file()
    if f:
        return key(f)
    it = getattr(mv, "_page_item", None)
    if it is None:
        return None
    try:
        c = it.pixmap().toImage().pixelColor(5, 5).getRgb()[:3]
    except Exception:
        return None
    return next((n for n, v in COL.items() if v == c), str(c))


tmp = Path(tempfile.mkdtemp(prefix="polypdf_shot_split_"))
try:
    pdfs = []
    for nm in ("a 문서.pdf", "b 문서.pdf"):
        d = fitz.open(); d.new_page(width=400, height=600).insert_text((40, 80), nm, fontsize=20)
        d.save(str(tmp / nm)); d.close(); pdfs.append(tmp / nm)
    shots_dir = tmp / "shots"; shots_dir.mkdir()
    shots = []
    for i, col in enumerate(("red", "blue", "green")):
        im = QImage(200, 150, QImage.Format.Format_RGB32); im.fill(QColor(col))
        p = shots_dir / f"컷{i + 1}.png"; im.save(str(p)); shots.append(p)
    photo = tmp / "사진.jpg"
    im = QImage(300, 200, QImage.Format.Format_RGB32); im.fill(QColor("yellow")); im.save(str(photo))

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 900); mw.show(); pump()
    mw.open_folder(tmp); pump(lambda: mw.bookmark_tree is not None)
    mw.open_pdfs([str(pdfs[0])]); pump(lambda: key(mw._mv[0].current_file()) == key(pdfs[0]))
    if getattr(mw, "_split_on", False):
        mw.act_split.setChecked(False); pump()
    st = mw.shot_strip
    for p in shots:
        st.add_item(str(p), kind="image", label=p.stem)
    pump()

    NAMES = ("red", "blue", "green")

    def click(i):
        """shots[i] 카드를 누른다(목록은 새 것이 위 — 경로로 찾는다)."""
        st.list.itemClicked.emit(st.list.item(st.index_of_path(str(shots[i])))); pump()

    def next_color(i):
        """shots[i] 다음 목록 칸(◀▶ +1)의 색."""
        j = min(st.list.count() - 1, st.index_of_path(str(shots[i])) + 1)
        p = st.list.item(j).data(st.DATA_PATH)
        return NAMES[[key(x) for x in shots].index(key(p))]

    # A
    chk(not mw._split_on, "A 준비 — 1단")
    click(0)
    chk(mw._split_on and mw.act_split.isChecked(), "A 컷을 누르면 2단이 켜진다(2단 단추도)", str(mw._split_on))
    chk(key(mw._mv[0].current_file()) == key(pdfs[0]), "A 왼쪽은 보던 PDF 그대로", str(mw._mv[0].current_file()))
    chk(shown(mw._mv[1]) == "red", "A 오른쪽 창에 컷", str(shown(mw._mv[1])))
    chk(mw._active_pane == 1, "A 활성 창은 오른쪽(◀▶ 넘김)", str(mw._active_pane))

    # B
    click(1)
    chk(shown(mw._mv[1]) == "blue", "B 다른 컷은 같은 오른쪽 창에서 바뀐다", str(shown(mw._mv[1])))
    chk(key(mw._mv[0].current_file()) == key(pdfs[0]), "B 왼쪽 그대로")
    mw._mv[1].imageStepRequested.emit(1); pump()
    chk(shown(mw._mv[1]) == next_color(1), "B 오른쪽 창 ◀▶ 로 다음 컷", str(shown(mw._mv[1])))

    # C
    mw._set_active_pane(1)
    mw._load_main(HistoryItem(str(pdfs[1]), 0, "", "bookmark")); pump(lambda: key(mw._mv[1].current_file()) == key(pdfs[1]))
    mw._set_active_pane(0); pump()
    click(0)
    chk(shown(mw._mv[1]) == "red" and shown(mw._mv[0]) == key(pdfs[0]),
        "C 2단·오른쪽 다른 PDF — 컷이 오른쪽을 바꾸고 왼쪽 그대로",
        f"{shown(mw._mv[0])} | {shown(mw._mv[1])}")

    # D
    mw.act_split.setChecked(False); pump()
    chk(not mw._split_on, "D 1단 단추로 1단 복귀")

    # E 사진 모드
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"; mw._photo_apply_view_kind()
    mw._set_photo_mode(True); pump(timeout=1.0)
    chk(mw._photo_mode, "E 준비 — 실제로 사진 모드(261114-20: 종전 기본 PDF 전용에서는 사진 모드가 켜지지 않아 E 가 PDF 모드를 쟀다)")
    mw._set_active_pane(0)
    mw._load_main(HistoryItem(str(photo), 0, "", "bookmark")); pump(lambda: shown(mw._mv[0]) in (key(photo), "yellow"))
    chk(shown(mw._mv[0]) in (key(photo), "yellow"), "E 준비 — 사진 모드 왼쪽에 사진", str(shown(mw._mv[0])))
    click(2)
    chk(mw._split_on, "E 사진 모드도 2단이 켜진다")
    chk(shown(mw._mv[0]) in (key(photo), "yellow"), "E 왼쪽 사진 그대로", str(shown(mw._mv[0])))
    # 사진 모드는 그림을 사진 문서(경로)로 연다 — 색 대신 그 컷의 경로면 같은 컷이다
    chk(shown(mw._mv[1]) in ("green", key(shots[2])), "E 오른쪽 창에 컷", str(shown(mw._mv[1])))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("\n=== " + ("ALL PASS" if not fails else f"FAILURE {len(fails)}") + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
