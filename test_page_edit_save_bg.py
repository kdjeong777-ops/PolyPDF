# -*- coding: utf-8 -*-
"""260915-9: 쪽 편집 저장이 창을 세우지 않는다 (마스터 §4.7.9, 응답성 SOT §4.4).

사용자 지시: "쪽 편집 저장도 배경 스레드로 옮길 필요가 있는지 검토해" → 실측 최장 정지 1.1~3.0초(메인),
원본 바꿔치기 `os.replace` 가 백신 검사에 붙들려 2.6·21.4초 → "진행해".

A. `page_edit_build` — 이어진 구간 복사(호출 수)·쪽 순서·붙여넣기·책갈피(쪽 번호 옮김·지운 쪽 버림·'／'·펼침)·취소
B. 앱 — **느린 재구성·느린 바꿔치기**를 모사해도 하트비트가 끊기지 않는다(수정 전 코드로 실패 확인)
C. 진행창에서 취소 — 원본·편집 그대로, 임시 파일 없음, 오류창 없음
"""
import os, sys, time, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths, QTimer, QElapsedTimer
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(n=10, ms=30):
    for _ in range(n):
        app.processEvents(); QTest.qWait(ms)


def make_pdf(p, n, tag):
    d = fitz.open()
    for i in range(n):
        d.new_page().insert_text((72, 72), f"{tag}{i + 1}")
    d.set_toc([[1, "처음", 1], [2, "둘째/절", 2], [1, "셋째", 3], [1, "끝", n]])
    d.save(str(p)); d.close()


def texts(p):
    d = fitz.open(str(p)); out = [d[i].get_text().strip() for i in range(d.page_count)]; d.close(); return out


root = Path(tempfile.mkdtemp(prefix="polypdf_pagesave_bg_"))
try:
    # ── A. 만들기 ───────────────────────────────────────────────────
    from viewer import page_edit_build as peb
    src = root / "S.pdf"; make_pdf(src, 30, "S")
    ext = root / "E.pdf"; make_pdf(ext, 5, "E")
    plan = [("own", i) for i in range(30) if i != 1]           # 2쪽 삭제
    plan[5:5] = [("ext", str(ext), 0), ("ext", str(ext), 1)]  # 붙여넣기 2쪽
    plan.insert(0, plan.pop(10))                              # 한 쪽을 맨 앞으로
    chk(len(peb.runs(plan, str(src))) <= 6, "A 이어진 쪽은 구간 하나로 묶는다", str(peb.runs(plan, str(src))))
    raw = [("처음", 1, 0), ("둘째／절", 2, 1), ("셋째", 3, 0), ("끝", 30, 0)]
    r = peb.build(src, plan, raw, root / "r.pdf", root / "b.pdf")
    want = []
    for e in plan:
        want.append(f"S{e[1] + 1}" if e[0] == "own" else f"E{e[2] + 1}")
    chk(texts(r["path"]) == want, "A 쪽 순서·붙여넣기 쪽이 계획대로", str(texts(r["path"])[:8]))
    chk(r["calls"] <= 6 and r["pages"] == len(plan), "A insert_pdf 호출이 쪽수가 아니라 구간 수", str(r))
    d = fitz.open(r["path"]); toc = d.get_toc(); full = d.get_toc(simple=False)
    counts = [d.xref_get_key(e[3]["xref"], "Count") for e in full]
    d.close()
    pos = {e[1]: i for i, e in enumerate(plan) if e[0] == "own"}
    chk([t[1] for t in toc] == ["처음", "셋째", "끝"], "A 지운 쪽(2쪽) 책갈피는 버리고 나머지는 남긴다", str(toc))
    chk([t[2] for t in toc] == [pos[0] + 1, pos[2] + 1, pos[29] + 1], "A 책갈피 쪽 번호가 새 위치로", str(toc))
    chk(all(e[3].get("bold") for e in full) and not any(v.startswith("-") for t, v in counts if t == "int"),
        "A 책갈피 모양 — 굵게·펼친 상태(종전 pdf_bookmarker 와 같게)", str(counts))
    r2 = peb.build(src, [("own", 0), ("own", 1)], [("둘째／절", 2, 0)], root / "r2.pdf", root / "b2.pdf")
    d = fitz.open(r2["path"]); t2 = d.get_toc(); d.close()
    chk(t2 and t2[0][1] == "둘째/절", "A 제목의 '／' 는 '/' 로(종전과 같다)", str(t2))
    n = [0]

    def cancel_second(done, total, label):
        n[0] += 1
        return n[0] < 2
    try:
        peb.build(src, plan, raw, root / "c.pdf", root / "cb.pdf", cancel_second); cancelled = False
    except peb.Cancelled:
        cancelled = True
    chk(cancelled and not (root / "c.pdf").exists() and not (root / "cb.pdf").exists(),
        "A 진행 콜백이 False 면 멈추고 임시 파일을 지운다")

    # ── B. 앱 — 느린 재구성·느린 바꿔치기에도 창이 산다 ─────────────────────
    msgs = []
    QMessageBox.warning = staticmethod(lambda *a, **k: msgs.append(("w", a[2])))
    QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(("i", a[2])))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1300, 850); mw.show(); app.processEvents()
    bt, pt = mw.bookmark_tree, mw.page_thumbs
    work = root / "W"; work.mkdir()
    doc_p = work / "D.pdf"; make_pdf(doc_p, 12, "D")
    mw.open_folder(work); spin(20)

    def node_of(p):
        for nd in bt._iter_file_nodes():
            if str(nd.data(0, bt.DATA_FILE)) == str(p):
                return nd

    def edit():
        mw._load_main(HistoryItem(str(doc_p), 0, "", "bookmark")); spin(10)
        if not mw._in_edit():
            bt.btn_edit.setChecked(True); spin(4)
        pt.list.clearSelection(); pt.list.item(1).setSelected(True); pt._delete_selected()
        bt.tree.setCurrentItem(node_of(doc_p)); spin(2)

    clock = QElapsedTimer(); clock.start()
    beats = []
    hb = QTimer(); hb.setInterval(40); hb.timeout.connect(lambda: beats.append(clock.elapsed()))
    spans = {}
    real_build, real_replace = peb.build, os.replace

    def slow_build(*a, **k):
        spans["b0"] = clock.elapsed(); time.sleep(1.5)
        try:
            return real_build(*a, **k)
        finally:
            spans["b1"] = clock.elapsed()

    def slow_replace(s, d_, *a, **k):
        if str(d_).endswith("D.pdf"):
            spans["r0"] = clock.elapsed(); time.sleep(1.5)
            try:
                return real_replace(s, d_, *a, **k)
            finally:
                spans["r1"] = clock.elapsed()
        return real_replace(s, d_, *a, **k)

    def worst_gap(a, b):
        inside = [y - x for x, y in zip(beats, beats[1:]) if y > spans.get(a, 0) and x < spans.get(b, 0)]
        return max(inside) if inside else 99999

    edit()
    peb.build, os.replace = slow_build, slow_replace
    hb.start()
    try:
        bt._op_save(); spin(10)
    finally:
        peb.build, os.replace = real_build, real_replace
        hb.stop()
    chk(len(texts(doc_p)) == 11 and not msgs, "B 느린 재구성·느린 바꿔치기여도 원본에 저장된다", str(msgs))
    chk(worst_gap("b0", "b1") < 700, "B 쪽 재구성 동안 창이 멈추지 않는다(하트비트)", "%dms" % worst_gap("b0", "b1"))
    chk(worst_gap("r0", "r1") < 700, "B 원본 바꿔치기(os.replace) 동안 창이 멈추지 않는다", "%dms" % worst_gap("r0", "r1"))

    # ── C. 진행창에서 취소 ─────────────────────────────────────────────
    before = doc_p.read_bytes()
    edit()
    msgs.clear()
    peb.build = slow_build

    def press_cancel():
        # ★ `QProgressDialog.cancel()` 은 창만 되돌리고 `canceled` 신호를 내지 않는다 — 사용자가 누르는 **취소 버튼**을 누른다
        from PyQt6.QtWidgets import QPushButton
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QProgressDialog) and w.isVisible():
                btns = [b for b in w.findChildren(QPushButton) if b.isVisible()]
                if btns:
                    btns[0].click()
                    return
        QTimer.singleShot(100, press_cancel)
    QTimer.singleShot(600, press_cancel)
    try:
        bt._op_save(); spin(10)
    finally:
        peb.build = real_build
    chk(doc_p.read_bytes() == before, "C 취소하면 원본은 그대로")
    chk(not [p.name for p in work.iterdir() if "_tmp" in p.name], "C 임시 파일이 남지 않는다",
        str([p.name for p in work.iterdir()]))
    chk(not [m for t, m in msgs if t == "w"] and mw._page_edits_dirty(), "C 오류창 없이, 편집은 남는다", str(msgs))
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
