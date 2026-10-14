# -*- coding: utf-8 -*-
"""261014-23: 문서 비교 — 개정판 차이 (마스터 §4.11, 개선 로드맵 P3-3).

실제 처리기(책갈피창 신호 `compareFilesRequested` → `action_compare`)로:
A. 바뀜·지움·넣음을 찾는다(낱말 차이 `[-…-]{+…+}`)
B. 옛판은 수정 시각이 이른 파일 — 2단 보기 왼쪽, 새판 오른쪽
C. 두 창에 칠한다(옛판 지움=빨강, 새판 넣음=초록, 바뀜=노랑) — 실제 그린 화면의 색으로 확인
D. 변경 목록을 누르면 두 창이 함께 그 쪽으로
E. 목록 창을 닫으면 칠한 것이 지워진다
F. 같은 문서면 '같습니다' 알림, 2단 보기로 바꾸지 않는다
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def make(path, pages):
    d = fitz.open()
    for lines in pages:
        p = d.new_page()
        for i, t in enumerate(lines):
            p.insert_text((72, 100 + 30 * i), t, fontsize=12)
    d.save(str(path)); d.close()


root = Path(tempfile.mkdtemp(prefix="polypdf_compare_test_"))
try:
    same = [f"Common line number {i} stays here." for i in range(6)]
    old = root / "A_old.pdf"
    new = root / "B_new.pdf"
    make(old, [same, ["Second page first line.", "The fee is 100 won per page.", "This line is removed later.",
                      "Closing words of the old edition."]])
    make(new, [same, ["Second page first line.", "The fee is 250 won per page.",
                      "Closing words of the old edition.", "A brand new final clause."]])
    t = time.time()
    os.utime(old, (t - 3600, t - 3600))      # 옛판 = 더 이른 수정 시각
    os.utime(new, (t, t))

    infos = []
    QMessageBox.information = staticmethod(lambda *x, **k: infos.append(x[2] if len(x) > 2 else ""))
    QMessageBox.warning = staticmethod(lambda *x, **k: infos.append(x[2] if len(x) > 2 else ""))

    from viewer.app import MainWindow
    mw = MainWindow(); mw.resize(1400, 900); mw.show(); app.processEvents()
    mw.open_folder(root); QTest.qWait(400)
    # 신호는 (새판, 옛판) 순으로 — 순서와 무관하게 수정 시각으로 고르는지
    mw.bookmark_tree.compareFilesRequested.emit(str(new), str(old)); QTest.qWait(600)

    dlg = getattr(mw, "_compare_dlg", None)
    chk(dlg is not None and dlg.isVisible(), "준비 — 변경 목록 창이 뜬다(모달 아님)", str(infos))
    if dlg is not None:
        chk(not dlg.isModal(), "목록 창은 모달이 아니다")
        ch = dlg._changes
        kinds = [c["kind"] for c in ch]
        rep = [c for c in ch if c["kind"] == "replace"]
        chk("replace" in kinds and "delete" in kinds and "insert" in kinds
            and any("[-100-]" in c["text"] and "{+250+}" in c["text"] for c in rep),
            "A 바뀜·지움·넣음 + 낱말 차이", str([(c['kind'], c['text']) for c in ch]))
        mv0, mv1 = mw._mv
        chk(mw._split_on and Path(mv0.current_file()) == old and Path(mv1.current_file()) == new,
            "B 2단 보기 — 왼쪽 옛판·오른쪽 새판", f"{mw._split_on} {mv0.current_file()} {mv1.current_file()}")
        chk(mv0.current_page() == 1 and mv1.current_page() == 1, "D 처음 바뀐 곳(2쪽)으로 두 창 함께",
            f"{mv0.current_page()} {mv1.current_page()}")
        m0, m1 = mv0._marks_for_page(1), mv1._marks_for_page(1)
        cols0 = {c[:3] for _r, c in m0}
        cols1 = {c[:3] for _r, c in m1}
        chk((230, 60, 60) in cols0 and (240, 200, 40) in cols0 and (40, 170, 70) in cols1 and (240, 200, 40) in cols1
            and not mv0._marks_for_page(0), "C 옛판 빨강·노랑, 새판 초록·노랑, 같은 쪽은 칠하지 않음", f"{cols0} {cols1}")

        # 실제 그린 화면에서 칠한 색 — 새판 넣은 줄(마지막 줄) 자리 픽셀이 초록 기운
        from PyQt6.QtWidgets import QGraphicsRectItem
        greens = [it for it in mv1.scene.items() if isinstance(it, QGraphicsRectItem)
                  and it.brush().color().getRgb()[:3] == (40, 170, 70)]
        ok_px = False
        if greens:
            vp = mv1.view.mapFromScene(greens[0].sceneBoundingRect().center())
            img = mv1.view.viewport().grab().toImage()
            c = img.pixelColor(vp.x(), vp.y())
            ok_px = c.green() > c.red() + 20
        chk(ok_px, "C 화면에 실제로 초록이 그려진다", f"{len(greens)}")

        # D. 목록의 다른 줄(1쪽이 아닌 곳은 모두 2쪽이므로, 바뀜 → 첫 쪽 이동 뒤 다시 누르기)
        mv0.go_to_page(0); mv1.go_to_page(0); QTest.qWait(200)
        item = dlg.lst.item(kinds.index("insert"))
        dlg.lst.itemClicked.emit(item); QTest.qWait(400)
        chk(mv1.current_page() == 1, "D 목록을 누르면 그 쪽으로", f"{mv0.current_page()} {mv1.current_page()}")

        dlg.close(); QTest.qWait(200)
        chk(not mv0._marks_for_page(1) and not mv1._marks_for_page(1), "E 목록 창을 닫으면 칠한 것이 지워진다")

    # F. 같은 문서
    mw.act_split.setChecked(False); mw._toggle_split(False); QTest.qWait(200)
    same2 = root / "C_same.pdf"
    shutil.copy(old, same2)
    infos.clear()
    res = mw.action_compare(str(old), str(same2))
    chk(res == [] and infos and "같습니다" in infos[-1] and not mw._split_on, "F 같은 문서면 알림만", f"{res} {infos}")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
