# -*- coding: utf-8 -*-
"""261024-4: 2장 맞춤의 쪽 원천 · 책갈피창 목차를 본문 문서에서 (마스터 §3·§15).

A. 끼운 흰 쪽(새 페이지 넣기, 저장 전)이 2장 맞춤에서 그려진다 — 왼쪽 쪽의 오른쪽 짝이 그 흰 쪽(넘김 차례와 같다),
   끼운 쪽으로 넘겨도 예외 없이 그린다(종전: 이 문서의 쪽만 읽어 `page not in document`)
B. 썸네일로 돌린(저장 전, `/Rotate` — 마스터 §4.7.16) 세로 쪽이 2장 맞춤에서 가로로 놓인다 — 실제 회전 길 `_rotate_pages`
C. 파일을 열어 책갈피창이 지금 쪽 책갈피를 고르며 펼칠 때 **그 파일을 다시 열지 않는다**(종전: 메인에서 fitz.open — 빌드 시험 T1 1.25초)
   — 목차는 그대로 달린다. 본문에 없는 파일을 펼치면 종전대로 연다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_FAKE_POWER_SAVING", "0")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_twostaged261024_%d" % os.getpid())

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.2):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def make_pdf(path, n, toc):
    d = fitz.open()
    for i in range(n):
        d.new_page(width=595, height=842).insert_text((72, 300), "%s P%d" % (path.stem, i + 1))
    d.set_toc(toc)
    d.save(str(path)); d.close()


root = Path(tempfile.mkdtemp(prefix="twostaged261024_"))
try:
    folder = root / "f"; folder.mkdir()
    a, b = folder / "a.pdf", folder / "b.pdf"
    make_pdf(a, 4, [[1, "A 하나", 1], [1, "A 둘", 3]])
    make_pdf(b, 2, [[1, "B 하나", 1]])

    import viewer.widgets.bookmark_tree as bt_mod
    opened = []

    class _FitzProxy:
        """책갈피 모듈의 fitz.open 만 센다(본문은 pdf_doc 의 fitz 를 쓴다)."""
        def __getattr__(self, k):
            return getattr(fitz, k)

        def open(self, *a_, **k):
            opened.append(str(a_[0]) if a_ else "")
            return fitz.open(*a_, **k)
    bt_mod.fitz = _FitzProxy()

    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1500, 900); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)

    # C — 파일을 열면 책갈피창이 그 파일을 펼치며 목차를 단다: 다시 열지 않는다
    opened.clear()
    #   261025-4: 배경 표식 검사가 아직 캐시를 못 채운 때(바쁜 기계 — 전체 검사에서만 실패했다)를 만든다
    _pc = getattr(mw.bookmark_tree, "_probe_cache", None) or {}
    mw.bookmark_tree._probe_cache = {k: v for k, v in _pc.items() if Path(k[0]).name != "a.pdf"}
    mw._on_bookmark_activated(str(a), 0); spin(1.0)
    bt = mw.bookmark_tree
    node = next(it for it in bt._iter_file_nodes() if Path(it.data(0, bt.DATA_FILE)).name == "a.pdf")
    titles = [node.child(i).text(0) for i in range(node.childCount())]
    chk(node.data(0, bt.DATA_TOC_LOADED) and titles == ["A 하나", "A 둘"], "C1 본문에 연 파일의 목차가 책갈피창에 달린다", str(titles))
    chk(not any(Path(p).name == "a.pdf" for p in opened), "C2 그때 책갈피창이 그 파일을 다시 열지 않는다(본문 문서의 목차)", str(opened))
    nb = next(it for it in bt._iter_file_nodes() if Path(it.data(0, bt.DATA_FILE)).name == "b.pdf")
    opened.clear()
    nb.setExpanded(True); spin(0.2)
    #   (표식 검사가 아직이면 검사와 목차 읽기로 두 번 연다 — 종전 그대로)
    chk(opened and {Path(p).name for p in opened} == {"b.pdf"} and nb.childCount() == 1, "C3 본문에 없는 파일을 펼치면 종전대로 연다",
        str((opened, nb.childCount())))

    # A — 끼운 흰 쪽이 2장 맞춤에서
    QMessageBox.question = staticmethod(lambda *a_, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a_, **k: None)
    mw._confirm_edit_save = lambda *a_, **k: "discard"
    if not bt.is_edit_mode():
        bt.btn_edit.setChecked(True); spin(0.4)
    mv, pt = mw.main_view, mw.page_thumbs
    mw._on_add_blank_page(0); spin(0.4)
    staged = int(mv.current_page())
    chk(mv._is_staged(staged), "A0 새 흰 쪽(끼운 쪽)이 생겼다", str(staged))
    mv.set_fit_mode(mv.FIT_PAGE_TWO); spin(0.2)
    err = None
    try:
        mv.go_to_page(0); spin(0.2)
    except Exception as e:                                   # noqa: BLE001
        err = e
    chk(err is None and mv._two_right(0) == staged, "A1 p.1 의 오른쪽 짝은 끼운 흰 쪽(넘김 차례와 같다)",
        "%r %r" % (err, mv._two_right(0)))
    pm = mv._page_item.pixmap() if mv._page_item is not None else None
    chk(pm is not None and pm.width() > pm.height(), "A2 두 쪽이 나란히 그려졌다", str(pm.size() if pm else None))
    err = None
    try:
        mv.go_to_page(staged); spin(0.2)
    except Exception as e:                                   # noqa: BLE001
        err = e
    chk(err is None and mv.current_page() == staged and mv._page_item is not None,
        "A3 끼운 쪽으로 넘겨도 예외 없이 그린다", repr(err))

    # B — 썸네일 회전(저장 전, 실제 길)한 쪽이 2장 맞춤에서 가로로
    mv.go_to_page(1); spin(0.2)
    w0 = mv._page_item.pixmap().width() / float(mv._page_item.pixmap().height())
    mw._rotate_pages([1], +90); spin(1.5)
    mv = mw.main_view
    if mv.current_page() != 1:
        mv.go_to_page(1); spin(0.3)
    w1 = mv._page_item.pixmap().width() / float(mv._page_item.pixmap().height())
    want0, want1 = (595 + 8 + 595) / 842.0, (842 + 8 + 595) / 842.0    # 세로+세로 / 돌린 가로+세로 (간격 TWO_PAGE_GAP_PT)
    chk(abs(w0 - want0) < 0.03 and abs(w1 - want1) < 0.03,
        "B1 90° 돌린 세로 쪽이 가로로 놓인다(합친 그림 비율 = 돌린 폭+간격+옆 쪽 폭)", "%.2f → %.2f (기대 %.2f → %.2f)" % (w0, w1, want0, want1))
    mw._rotate_pages([1], -90); spin(1.0)
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== %s ===" % ("ALL PASS" if not fails else "FAIL %d" % len(fails)))
sys.stdout.flush()
os._exit(1 if fails else 0)
