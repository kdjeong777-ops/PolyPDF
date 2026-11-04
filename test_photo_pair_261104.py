# -*- coding: utf-8 -*-
"""2분할 사진 비교 — 함께 움직이기 (사진 보기 SOT 4.28, §5.1 F3, 261104-7 B3).

실제 MainWindow 로(오프스크린, 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3).
A. 2분할에서 사진 우클릭 메뉴에 '2분할 함께 움직이기'(체크) — 2분할이 아니면 없다
B. 켜면 한 창의 맞춤·배율(원래 크기 100%)이 다른 창에도
C. 한 창을 스크롤하면 다른 창도 같은 비율 자리로
D. 한 창을 넘기면 다른 창도 제 목록에서 한 장
E. 끄면 따로 움직인다
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
QCoreApplication.setApplicationName("polypdf_photo_pair_%d" % os.getpid())
import modal_guard
modal_guard.install(label=lambda: "사진 2분할", echo=False)   # 마스터 §14.7.2 의 6
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

tmp = Path(tempfile.mkdtemp(prefix="polypdf_photo_pair_"))
try:
    from PIL import Image
    for i, n in enumerate(("1.jpg", "2.jpg", "3.jpg"), 1):
        Image.new("RGB", (3000, 2000), (40 * i, 90, 160)).save(tmp / n, "JPEG")
    P = lambda n: str(tmp / n)

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1400, 900); mw.show(); pump()
    bt = mw.bookmark_tree
    mw._prefs.setdefault("picture", {})["view_kind"] = "mixed"
    mw._photo_apply_view_kind()
    mw._set_photo_mode(True)
    mw.open_folder(tmp)
    pump(lambda: sum(1 for _ in bt._iter_file_nodes()) == 3)
    bt.set_sort_mode(bt.SORT_NAME); pump()
    mw._on_bookmark_activated(P("1.jpg"), 0); pump(timeout=1.5)

    mw._photo_context_menu(QPoint(5, 5))
    chk("2분할 함께 움직이기" not in menu_texts, "A 2분할이 아니면 메뉴에 없다")
    mw._view_as_split(); pump(timeout=1.5)
    mw._copy_pane_to(0, 1); pump(timeout=2.0)
    chk(getattr(mw, "_split_on", False), "2분할이 켜졌다")
    mv0, mv1 = mw._mv[0], mw._mv[1]
    chk(getattr(getattr(mv1, "_doc", None), "is_photo", False), "오른쪽 창에도 사진", str(mv1.current_file()))
    mw._set_active_pane(0); pump()
    mw._photo_context_menu(QPoint(5, 5))
    chk("2분할 함께 움직이기" in menu_texts, "A 2분할에서 메뉴에 '2분할 함께 움직이기'", str(menu_texts))

    # B
    mw._photo_pair_set(True); pump()
    mw._photo_zoom_actual(); pump(timeout=0.8)
    chk(mv1._fit_mode == mv0._fit_mode == mv0.FIT_NONE and abs(mv1._zoom - 1.0) < 1e-6, "B 원래 크기(100%)가 다른 창에도",
        "%s %s %.3f" % (mv0._fit_mode, mv1._fit_mode, mv1._zoom))

    # C
    s0, s1 = mv0.view.verticalScrollBar(), mv1.view.verticalScrollBar()
    s0.setValue((s0.maximum() + s0.minimum()) // 2); pump()
    f0 = (s0.value() - s0.minimum()) / max(1, s0.maximum() - s0.minimum())
    f1 = (s1.value() - s1.minimum()) / max(1, s1.maximum() - s1.minimum())
    chk(s1.maximum() > 0 and abs(f0 - f1) < 0.02, "C 스크롤이 같은 비율 자리로", "%.2f %.2f" % (f0, f1))

    # D
    rt = mw.bookmark_tree_right
    rt.set_sort_mode(rt.SORT_NAME); pump()                  # 오른쪽 창 목록도 이름 차례로(넘김은 그 창 목록을 따른다)
    mw._set_active_pane(0); pump()
    before = Path(mv1.current_file()).name
    mw._on_file_boundary(+1, 0); pump(timeout=1.5)
    chk(Path(mv0.current_file()).name == "2.jpg" and Path(mv1.current_file()).name == "2.jpg" and before == "1.jpg",
        "D 넘김을 함께(두 창 모두 다음 사진)", "%s %s" % (mv0.current_file(), mv1.current_file()))

    # E
    mw._photo_pair_set(False); pump()
    mw._set_active_pane(0)
    mw._on_file_boundary(+1, 0); pump(timeout=1.5)
    chk(Path(mv0.current_file()).name == "3.jpg" and Path(mv1.current_file()).name == "2.jpg", "E 끄면 따로", "%s %s" % (mv0.current_file(), mv1.current_file()))
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
