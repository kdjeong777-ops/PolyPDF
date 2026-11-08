# -*- coding: utf-8 -*-
"""메인 스레드가 처음 보는 PDF 를 `fitz.open` 하지 않는다 — 책갈피창·합치기 미리보기 (261108-17, 응답성 SOT §4.9).

백신은 막 보게 된 파일을 실시간 검사한다 — 그동안 `fitz.open` 이 1초 넘게 선다(책갈피창 주석 실측 '처음 여는 파일은 1초+',
beta.7 T3 1.24초도 막 연 파일). 정지 시간은 기계·백신마다 흔들려 판정에 못 쓴다 → **메인 스레드의 `fitz.open` 호출 수**로 본다
(261108-10 방식, 검사 작성 SOT §14.7.2 — 수정 전 코드로 S·X·E·M 이 실패한다).

S. 단일 파일 열기(`load_single_pdf`) — 메인 open 0(수정 전 1), 결과가 오면 책갈피 ▸(placeholder)·암호 표식이 붙는다
X. 파일 모드에서 아직 검사 안 된 행을 손으로 펼치기 — 메인 open 0(수정 전 2), 결과가 오면 책갈피가 달린다
E. '모두 펼치기' — 보이는 파일 책갈피 읽기를 메인에서 하지 않는다(수정 전 파일마다), 다 읽히면 펼쳐져 있다
K. 결과가 오기 전에 목록을 바꾸면(다른 파일 열기) 낡은 결과는 버린다 — 지운 행을 만지지 않는다
Y. 결과를 바로 써야 하는 편집 길(책갈피 넣기 `add_bookmark`)은 종전처럼 그 자리에서 읽는다 — 원래 책갈피 + 넣은 것
T. 열린 파일(toc_provider 가 목차를 줌)은 디스크를 열지 않는다(261024-4 유지)
M. 합치기 창 미리보기(`_Preview.show_pdf`) — 메인 open 0(수정 전 1), 결과가 오면 쪽 수·그림, 그 사이 다른 파일을 고르면 앞 결과는 버린다
B. 본문 열기(261108-22, `_load_main`·`open_pdf`·`_open_saved_file`) — 메인이 **데우지 않은** 파일을 `fitz.open` 0(수정 전 1),
   데우는 동안 '여는 중' 안내, 잇따라 열면 나중 것만, 암호 PDF·저장 뒤 다시 열기 같은 길, 모드가 바뀌면 버린다.
   (PyMuPDF 는 열기 중 GIL 을 쥐어 배경 `fitz.open` 도 메인을 세운다 — 데우기는 파이썬 `read`, `workers.warm_read`)
"""
import os, sys, time, tempfile, shutil, threading, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"          # 검사 작성 SOT §14.7
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(180, exit=True)

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)             # 검사 작성 SOT §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
from PyQt6.QtCore import QCoreApplication
QCoreApplication.setApplicationName("polypdf_firstopen_%d" % os.getpid())
import modal_guard
guard = modal_guard.install(label=lambda: "검사")
from pathlib import Path
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(ms=800, until=None):
    t = time.perf_counter()
    while (time.perf_counter() - t) * 1000 < ms:
        app.processEvents(); QTest.qWait(10)
        if until is not None and until():
            break


main_opens = []
_orig_open = fitz.open


def _spy_open(*a, **k):
    if threading.current_thread() is threading.main_thread() and a and isinstance(a[0], (str, os.PathLike)):
        main_opens.append(os.path.normcase(os.path.abspath(str(a[0]))))
    return _orig_open(*a, **k)


def n_main(path=None) -> int:
    if path is None:
        return len(main_opens)
    n = os.path.normcase(os.path.abspath(str(path)))
    return sum(1 for c in main_opens if c == n)


def make(p, n_top=3, pages=6, enc=False):
    d = fitz.open()
    for _ in range(pages):
        d.new_page()
    toc = []
    for i in range(n_top):
        toc += [[1, f"장{i}", 1 + i % pages], [2, f"절{i}", 1 + i % pages]]
    if toc:
        d.set_toc(toc)
    if enc:
        d.save(p, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    else:
        d.save(p)
    d.close()
    return len(toc)


def kids(it):
    from viewer.widgets.bookmark_tree import BookmarkTree as B
    return [it.child(i) for i in range(it.childCount())
            if not it.child(i).data(0, B.DATA_IS_TOC_PLACEHOLDER)]


def has_ph(it):
    from viewer.widgets.bookmark_tree import BookmarkTree as B
    return any(it.child(i).data(0, B.DATA_IS_TOC_PLACEHOLDER) for i in range(it.childCount()))


root = tempfile.mkdtemp(prefix="polypdf_firstopen_")
fitz.open = _spy_open
try:
    from viewer.widgets.bookmark_tree import BookmarkTree as B
    files = []
    for i in range(6):
        p = os.path.join(root, f"f{i}.pdf")
        make(p)
        files.append(p)
    single = os.path.join(root, "single.pdf")
    make(single)
    locked = os.path.join(root, "locked.pdf")
    make(locked, enc=True)

    bt = B(); bt.resize(360, 600); bt.show(); spin(200)

    # S
    main_opens.clear()
    bt.load_single_pdf(single)
    chk(n_main(single) == 0, "S 단일 파일 열기 — 메인 fitz.open 0", "%d번" % n_main(single))
    top = bt.tree.topLevelItem(0)
    spin(3000, until=lambda: has_ph(top))
    chk(has_ph(top), "S 배경 결과로 책갈피 ▸(placeholder)가 붙는다")
    main_opens.clear()
    bt.load_single_pdf(locked)
    top = bt.tree.topLevelItem(0)
    spin(3000, until=lambda: bool(top.data(0, B.DATA_ENCRYPTED)))
    chk(n_main(locked) == 0, "S 암호 파일도 메인 fitz.open 0", "%d번" % n_main(locked))
    chk(bool(top.data(0, B.DATA_ENCRYPTED)) and top.data(0, B.DATA_AUTH) == "locked",
        "S 배경 결과로 암호 표식(잠김)", str(top.data(0, B.DATA_AUTH)))

    # X — 검사 큐가 돌기 전에(멈춤) 손으로 펼친다
    bt.set_probe_paused(True)
    bt.load_pdf_files(files)
    it = bt.tree.topLevelItem(4)
    main_opens.clear()
    it.setExpanded(True)
    chk(n_main(files[4]) == 0, "X 검사 전 행 펼치기 — 메인 fitz.open 0", "%d번" % n_main(files[4]))
    spin(3000, until=lambda: len(kids(it)) > 0)
    chk([c.text(0) for c in kids(it)][:1] == ["장0"] and not has_ph(it),
        "X 배경 결과로 책갈피가 달린다", str([c.text(0) for c in kids(it)]))
    chk(bool(it.data(0, B.DATA_TOC_LOADED)), "X 읽은 뒤 DATA_TOC_LOADED")
    bt.set_probe_paused(False)

    # K — 결과가 오기 전에 목록을 바꾼다
    bt.set_probe_paused(True)
    bt.load_pdf_files(files)
    it = bt.tree.topLevelItem(2)
    it.setExpanded(True)
    bt.load_single_pdf(single)                          # 목록이 통째로 바뀐다(옛 행은 지워진다)
    spin(1500)
    top = bt.tree.topLevelItem(0)
    chk(bt.tree.topLevelItemCount() == 1 and top.data(0, B.DATA_FILE) == single and not kids(top),
        "K 낡은 결과는 새 목록에 붙지 않는다", str([c.text(0) for c in kids(top)]))
    bt.set_probe_paused(False)

    # Y — 편집 길은 그 자리에서(종전 동작)
    bt.load_pdf_files(files)
    spin(100)
    it = bt.tree.topLevelItem(1)
    bt.add_bookmark(files[1], 2, "새 책갈피", level=1)
    names = [c.text(0) for c in kids(it)]
    chk(len(names) == 4 and any(n.startswith("새 책갈피") for n in names) and "장0" in names[0],
        "Y 책갈피 넣기 — 원래 최상위 책갈피 + 넣은 것이 바로 보인다", str(names))

    # T — 열린 파일은 디스크를 열지 않는다
    bt.toc_provider = lambda fp: [[1, "열린 문서 목차", 1]] if os.path.normcase(fp) == os.path.normcase(files[3]) else None
    bt.load_pdf_files(files)
    it = bt.tree.topLevelItem(3)
    main_opens.clear()
    it.setExpanded(True)
    chk(n_main(files[3]) == 0 and [c.text(0) for c in kids(it)] == ["열린 문서 목차"],
        "T 열린 파일 펼치기 — 디스크 열지 않고 열린 문서 목차", "%d번 %s" % (n_main(files[3]), [c.text(0) for c in kids(it)]))
    bt.toc_provider = None

    # E — 모두 펼치기
    bt.set_probe_paused(True)
    bt.load_pdf_files(files)
    spin(100)
    main_opens.clear()
    bt._op_expand_all(True)
    spin(3000, until=lambda: all(len(kids(bt.tree.topLevelItem(i))) > 0 for i in range(3)))
    chk(n_main() == 0, "E 모두 펼치기 — 메인 fitz.open 0", "%d번" % n_main())
    first = bt.tree.topLevelItem(0)
    chk(len(kids(first)) == 3 and first.isExpanded() and kids(first)[0].isExpanded(),
        "E 다 읽히면 책갈피가 펼쳐져 있다", "%d개 %s" % (len(kids(first)), first.isExpanded()))
    bt._op_expand_all(False)
    bt.set_probe_paused(False)
    bt.close(); bt.deleteLater(); spin(100)

    # M — 합치기 창 미리보기
    from viewer.widgets.merge_dialog import FilePreview as _Preview
    pv = _Preview(); pv.resize(400, 500); pv.show(); spin(100)
    main_opens.clear()
    pv.show_pdf(files[0])
    chk(n_main(files[0]) == 0, "M 미리보기 — 메인 fitz.open 0", "%d번" % n_main(files[0]))
    spin(3000, until=lambda: getattr(pv, "_count", 0) > 0)
    chk(getattr(pv, "_count", 0) == 6 and not pv.canvas.pixmap().isNull(),
        "M 배경 결과로 쪽 수·그림", str(getattr(pv, "_count", 0)))
    pv.show_pdf(files[1])
    pv.show_pdf(files[2])                               # 앞 결과가 오기 전에 바꾼다
    spin(3000, until=lambda: getattr(pv, "_doc", None) is not None)
    spin(300)
    chk(pv._key == ("pdf", str(files[2])) and pv._doc is not None and pv._doc.name.endswith("f2.pdf"),
        "M 나중에 고른 파일만 남는다", str(getattr(pv._doc, "name", None)))
    pv.show_pdf(locked)
    spin(3000, until=lambda: "암호" in pv.canvas.text())
    chk("암호" in pv.canvas.text(), "M 암호 문서는 종전 안내", pv.canvas.text())
    pv.clear(); pv.close()

    # B — 본문 열기(261108-22): `_load_main` → `load_document` → `PdfDocument` 의 첫 `fitz.open`
    from viewer import workers as _wk
    from viewer.history import HistoryItem
    from viewer.app import MainWindow
    from viewer import secure_store
    cold = []                                           # 메인에서 **데우지 않은** 파일을 연 것

    def _spy_cold(*a, **k):
        if (threading.current_thread() is threading.main_thread() and a and isinstance(a[0], (str, os.PathLike))
                and not _wk.is_warm(a[0])):
            cold.append(os.path.basename(str(a[0])))
        return _orig_open(*a, **k)
    fitz.open = _spy_cold

    def fresh(name, **kw):
        p = os.path.join(root, name)
        make(p, **kw)
        return p

    def body(w):
        return os.path.basename(w.main_view.current_file() or "")

    w = MainWindow(); w.resize(1100, 760); w.show(); spin(300)
    mv = w.main_view
    b1 = fresh("b1.pdf")
    cold.clear()
    w._load_main(HistoryItem(b1, 2, "", "bookmark"))
    hint = mv._empty_label.text() if mv._empty_label.isVisible() else ""
    chk(not cold, "B1 처음 보는 PDF 본문 열기 — 메인에서 데우지 않은 fitz.open 0", str(cold))
    chk("b1.pdf" in hint, "B1 데우는 동안 빈 본문에 '여는 중' 안내", repr(hint))
    spin(5000, until=lambda: body(w) == "b1.pdf")
    chk(body(w) == "b1.pdf" and mv.current_page() == 2 and mv._doc.page_count == 6,
        "B1 데운 뒤 그 쪽으로 열린다", "%s p%s" % (body(w), mv.current_page()))
    chk(not cold, "B1 연 뒤에도 데우지 않은 open 0", str(cold))
    # 다시 고르면(데운 파일) 곧바로 — 종전 동기 길
    w._load_main(HistoryItem(b1, 0, "", "bookmark"))
    chk(body(w) == "b1.pdf" and mv.current_page() == 0, "B1 데운 파일은 그 자리에서 연다", str(mv.current_page()))

    # B2 — 파일 열기(open_pdf) 둘을 잇따라: 나중 것만, 앞 것은 본문에 열리지 않는다
    b2a, b2b = fresh("b2a.pdf"), fresh("b2b.pdf")
    cold.clear(); main_opens.clear()
    w.open_pdf(Path(b2a))
    w.open_pdf(Path(b2b))
    spin(5000, until=lambda: body(w) == "b2b.pdf")
    spin(300)
    chk(not cold, "B2 파일 열기 — 메인에서 데우지 않은 fitz.open 0", str(cold))
    chk(body(w) == "b2b.pdf" and not any(c.endswith("b2a.pdf") for c in main_opens),
        "B2 나중에 연 파일만 본문에 — 앞 것은 버린다", "%s %s" % (body(w), [os.path.basename(c) for c in main_opens]))

    # B3 — 암호 PDF(기억한 암호) 도 같은 길
    b3 = fresh("b3.pdf", enc=True)
    secure_store.set_session(b3, "u")
    cold.clear()
    w._load_main(HistoryItem(b3, 0, "", "bookmark"))
    spin(5000, until=lambda: body(w) == "b3.pdf")
    chk(not cold and body(w) == "b3.pdf" and not mv._doc.needs_password, "B3 암호 PDF — 데운 뒤 기억한 암호로 열린다",
        "%s %s" % (cold, body(w)))

    # B4 — 저장 뒤 다시 열기(`_open_saved_file`): 바뀐 파일은 다시 데운다, 저장 길이 훑었으면 곧바로
    make(b1, n_top=1, pages=4)                          # 바뀐 파일(크기·시각이 다르다)
    cold.clear()
    w._open_saved_file(b1, page=1)
    spin(5000, until=lambda: body(w) == "b1.pdf" and mv._doc.page_count == 4)
    chk(not cold and body(w) == "b1.pdf" and mv._doc.page_count == 4 and mv.current_page() == 1,
        "B4 저장 뒤 다시 열기 — 데운 뒤 새 내용·그 쪽", "%s %s p%s" % (cold, body(w), mv.current_page()))
    w._load_main(HistoryItem(b3, 0, "", "bookmark"))   # 데운 파일 — 곧바로(b1 을 놓아 다시 쓸 수 있게, 실제 저장은 `_close_main_view_doc`)
    make(b1, n_top=1, pages=5)
    from viewer.app import _warm_read
    _warm_read(b1)                                      # `_finalize_save` 가 놓은 뒤 배경에서 훑는 것과 같다
    w._open_saved_file(b1, page=0)
    chk(mv._doc.page_count == 5, "B4 저장 길이 훑은 파일은 데우기 없이 곧바로 연다", str(mv._doc.page_count))

    # B5 — 데우는 동안 사진 모드로 바꾸면 버린다(사진 모드 본문에 PDF 를 열지 않는다)
    b5 = fresh("b5.pdf")
    w._load_main(HistoryItem(b5, 0, "", "bookmark"))
    w._photo_mode = True                                # 모드만 바뀐 것으로(사진 모드 진입 길은 이 검사 밖)
    spin(1500)
    chk(body(w) != "b5.pdf", "B5 데우는 사이 모드가 바뀌면 낡은 결과는 버린다", body(w))
    w._photo_mode = False
    w.close(); spin(200)
finally:
    fitz.open = _orig_open
    spin(200)
    shutil.rmtree(root, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILED %d: %s" % (len(fails), fails))
sys.stdout.flush()
os._exit(1 if fails else 0)                 # 261108-22: 창 검사 — Qt 소멸 때의 0xC0000409 가 판정을 덮지 않게(검사 작성 SOT §14.7)
