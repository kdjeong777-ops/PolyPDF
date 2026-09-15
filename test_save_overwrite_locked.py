# -*- coding: utf-8 -*-
"""260915-1: 쪽 편집 저장이 원본에 들어가게 · 부득이 새 파일이면 책갈피창 갱신·그 파일로 (마스터 §4.7.5).

사용자 보고·지시
  "일부 페이지 이동/삭제/수정 시 동일 파일로 저장이 안되는 사유를 검토하고, 앞으로 그런일이
   발생하지 않도록 해. … 만일 어쩔수 없이 새로운 파일로 저장할 경우, 저장 후, 책갈피를
   리프레쉬하고, 새로 저장된 파일에 포커싱되도록 해."

원인: 배경 스레드(색인·목록 조사·텍스트 창 작업)가 원본을 읽는 중이면 UI 가 그 핸들을 닫을
수 없어 `os.replace` 가 거부되고 `_edited.pdf` 로 빠졌다. **실제 저장 경로**(`_op_save`)로 확인한다.
"""
import os, sys, time, ctypes, threading, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)          # 사용자 설정·색인을 건드리지 않는다
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def make_pdf(p, n=8):
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((72, 72), f"{p.stem} PAGE {i}")
    d.set_toc([[1, "ch1", 1], [1, "ch3", 3], [1, "ch6", 6]])
    d.save(str(p)); d.close()


def pages(p):
    d = fitz.open(str(p)); n = d.page_count; d.close(); return n


def spin(n=20, ms=40):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


def deny_write_lock(path):
    """다른 프로그램(예: Acrobat)처럼 **쓰기를 막고** 연다 — 바꿔치기·제자리 쓰기 모두 막힌다."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    h = k32.CreateFileW(str(path), 0x80000000, 0x1, None, 3, 0x80, None)   # GENERIC_READ, SHARE_READ
    assert h not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    return lambda: k32.CloseHandle(ctypes.c_void_p(h))


root = Path(tempfile.mkdtemp(prefix="polypdf_save_lock_"))
try:
    # ── A. 제자리 덮어쓰기 — 단위 ─────────────────────────────────────────
    from viewer import file_overwrite as fo
    ua = root / "unit"; ua.mkdir()
    a1, a2 = ua / "u.pdf", ua / "u_new.pdf"
    make_pdf(a1, 5); make_pdf(a2, 3)
    h = fitz.open(str(a1)); h.load_page(0).get_text()
    try:
        try:
            os.replace(str(a2), str(a1)); replaced = True
        except OSError:
            replaced = False
        chk(not replaced, "A (원인 재현) 누가 원본을 읽고 있으면 바꿔치기가 거부된다")
        fo.overwrite_in_place(a2, a1)
    finally:
        h.close()
    chk(pages(a1) == 3 and not a2.exists() and not fo.backup_path(a1).exists(),
        "A 읽는 핸들이 있어도 **제자리로** 덮어쓴다 · 임시·백업을 남기지 않는다")
    make_pdf(a2, 4)
    before = a1.read_bytes()
    real = fo._write_into
    calls = []

    def broken(f, s):
        calls.append(s)
        if len(calls) == 1:
            f.seek(0); f.write(b"garbage"); raise OSError("디스크 오류 모사")
        return real(f, s)
    fo._write_into = broken
    try:
        try:
            fo.overwrite_in_place(a2, a1); raised = False
        except OSError:
            raised = True
    finally:
        fo._write_into = real
    chk(raised and a1.read_bytes() == before and a2.exists() and not fo.backup_path(a1).exists(),
        "A 쓰다가 실패하면 **원본을 되돌리고** 산출물은 남긴다")

    # ── B. 앱 — 배경 스레드가 원본을 읽는 중에 쪽 삭제·이동 저장 ───────────────
    for nm in ("A", "B", "C"):
        make_pdf(root / f"{nm}.pdf")
    src = root / "B.pdf"
    msgs = []
    QMessageBox.warning = staticmethod(lambda *a, **k: msgs.append(("w", a[2])))
    QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(("i", a[2])))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    bt, pt = mw.bookmark_tree, mw.page_thumbs
    lab = lambda: [bt.tree.topLevelItem(i).text(0) for i in range(bt.tree.topLevelItemCount())]

    def node_of(p):
        for n in bt._iter_file_nodes():
            if str(n.data(0, bt.DATA_FILE)) == str(p):
                return n

    def open_and_edit():
        mw._load_main(HistoryItem(str(src), 0, "", "bookmark")); spin(15)
        if not mw._in_edit():
            bt.btn_edit.setChecked(True); spin(5)
        pt.list.clearSelection(); pt.list.item(1).setSelected(True); pt._delete_selected()
        pt.list.clearSelection(); pt.list.item(4).setSelected(True); pt._move_selected(-1)
        bt.tree.setCurrentItem(node_of(src)); spin(3)

    mw.open_folder(root); spin(30)
    open_and_edit()
    stop = threading.Event()

    def holder():                                  # 색인·텍스트 창 작업 스레드와 같은 모양
        d = fitz.open(str(src)); d.load_page(0).get_text(); stop.wait(10); d.close()
    th = threading.Thread(target=holder); th.start(); time.sleep(0.3)
    try:
        t0 = time.time(); bt._op_save(); took = time.time() - t0; spin(10)
    finally:
        stop.set(); th.join()
    names = sorted(p.name for p in root.glob("*.pdf"))
    chk("B_edited.pdf" not in names, "B 배경 스레드가 읽고 있어도 `_edited.pdf` 로 빠지지 않는다", str(names))
    chk(pages(src) == 7, "B **원본에** 쪽 편집이 들어갔다(8→7쪽)", str(pages(src)))
    chk(not [m for t, m in msgs if t == "w"], "B 경고가 없다", str(msgs)[:160])
    chk(not list(root.glob("~*")) and not list(root.glob("*_tmp.pdf")), "B 임시·백업 파일이 남지 않는다",
        str([p.name for p in root.iterdir()]))
    chk(Path(mw.main_view.current_file()).name == "B.pdf", "B 본문은 원본을 다시 연다")
    # 단독 실행 약 1초, 전체 검사 중 부하에서 4.5초를 봤다 — 재시도가 길어지는 퇴행만 잡는다
    chk(took < 8.0, "B 저장이 오래 멈추지 않는다", "%.2fs" % took)

    # ── B2. 제자리 쓰기 동안 창이 멈추지 않는다(260915-8, 응답성 SOT §2·§4.4) ─────────
    #   실측 232MB 제자리 쓰기 3~7초 — 메인에서 하면 그대로 정지다. 느린 디스크를 **2초 지연**으로 흉내 내
    #   하트비트 최장 간격을 잰다(메인에서 쓰면 ≥2초, 배경 스레드면 짧다 — 수정 전 코드로 실패 확인).
    from PyQt6.QtCore import QTimer, QElapsedTimer
    from viewer import file_overwrite as _fo
    make_pdf(root / "SLOW.pdf")
    src_b = root / "SLOW.pdf"
    mw.open_folder(root); spin(20)
    mw._load_main(HistoryItem(str(src_b), 0, "", "bookmark")); spin(10)
    if not mw._in_edit():
        bt.btn_edit.setChecked(True); spin(4)
    pt.list.clearSelection(); pt.list.item(1).setSelected(True); pt._delete_selected()
    bt.tree.setCurrentItem(node_of(src_b)); spin(2)
    stop2 = threading.Event()

    def holder2():
        dd = fitz.open(str(src_b)); dd.load_page(0).get_text(); stop2.wait(30); dd.close()
    th2 = threading.Thread(target=holder2); th2.start(); time.sleep(0.3)
    real_ow = _fo.overwrite_in_place
    span = {}

    def slow_ow(new_file, dst):
        span["t0"] = clock.elapsed()
        time.sleep(2.0)                                  # 느린 디스크
        real_ow(new_file, dst)
        span["t1"] = clock.elapsed()
    gaps = []
    clock = QElapsedTimer(); clock.start()
    last = {"t": None}

    def beat():
        now = clock.elapsed()
        if last["t"] is not None:
            gaps.append((last["t"], now))
        last["t"] = now
    hb = QTimer(); hb.setInterval(50); hb.timeout.connect(beat); hb.start()
    _fo.overwrite_in_place = slow_ow
    try:
        bt._op_save()
    finally:
        _fo.overwrite_in_place = real_ow
        stop2.set(); th2.join(); hb.stop()
    spin(10)
    chk(pages(src_b) == 7 and "t1" in span, "B2 느린 디스크여도 제자리로 저장된다", str(pages(src_b)))
    inside = [b - a for a, b in gaps if "t0" in span and b > span["t0"] and a < span.get("t1", 0)]
    worst = max(inside) if inside else 99999
    chk(worst < 700, "B2 제자리 쓰기 동안 창이 멈추지 않는다(하트비트 최장 간격)", "%dms" % worst)

    # ── C. 부득이 새 파일 — 다른 프로그램이 쓰기를 막고 연 원본 ─────────────────
    msgs.clear()
    open_and_edit()
    bnode = node_of(src)
    bnode.setExpanded(True); spin(5)
    _d = fitz.open(str(src)); n_disk = len(_d.get_toc()); _d.close()
    kid = next(bnode.child(i) for i in range(bnode.childCount())
               if not bnode.child(i).data(0, bt.DATA_IS_TOC_PLACEHOLDER))
    bnode.removeChild(kid)                         # 트리에서 책갈피 하나 지운 편집
    n_before = pages(src)
    unlock = deny_write_lock(src)
    try:
        bt._op_save()
        chk(not [m for t, m in msgs if t == "w"],
            "C 경고는 책갈피창 갱신·이동 **뒤에** 뜬다(저장 도중엔 아직 없다)")
        spin(10)
    finally:
        unlock()
    new = root / "B_edited.pdf"
    chk(new.exists() and pages(new) == n_before - 1 and pages(src) == n_before,
        "C 원본은 그대로, 새 파일에 편집이 들어갔다")
    chk([m for t, m in msgs if t == "w"] and "B_edited.pdf" in [m for t, m in msgs if t == "w"][0],
        "C 새 이름으로 저장했다고 **알린다**")
    chk("B_edited" in lab() and lab().index("B_edited") == lab().index("B") + 1,
        "C 새 파일은 **원본 바로 아래** 들어간다", str(lab()))
    cur = bt.tree.currentItem()
    cur_file = cur and bt._file_node_of(cur)
    chk(cur_file is not None and cur_file.text(0) == "B_edited", "C 책갈피창 선택이 **새 파일**에 있다",
        cur.text(0) if cur else "")
    chk(Path(mw.main_view.current_file()).name == "B_edited.pdf", "C 본문도 **새 파일**을 연다")
    chk(Path(str(pt._doc.path)).name == "B_edited.pdf", "C 썸네일도 새 파일")
    bnode = node_of(src)
    bnode.setExpanded(True); spin(5)
    kids = [bnode.child(i) for i in range(bnode.childCount())
            if not bnode.child(i).data(0, bt.DATA_IS_TOC_PLACEHOLDER)]
    chk(len(kids) == n_disk, "C 원본 노드는 **디스크 책갈피로** 다시 읽는다(편집은 새 파일로 갔다)",
        "%d/%d" % (len(kids), n_disk))
    nnode = node_of(new)
    nnode.setExpanded(True); spin(5)
    chk(nnode.childCount() >= 1 and not nnode.child(0).data(0, bt.DATA_IS_TOC_PLACEHOLDER),
        "C 새 파일 노드의 책갈피가 읽혀 있다")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
