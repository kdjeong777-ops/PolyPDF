# -*- coding: utf-8 -*-
"""261012-2: 쪽 크롭 50% 넘게 · 쪽 나누기(1쪽 → 2쪽·4쪽) (마스터 §4.7.15).

A. 크롭 한 변 최대 95%·마주 보는 두 변 합 ≤ 95% — 60% 자르기가 그대로 들어간다(종전 45% 에서 잘렸다)
B. 나누기 계산 — 좌우·위아래·4쪽·오른쪽부터, 크롭 뒤 영역 기준, 나눔선 위치, 회전한 쪽(보이는 방향), 글자는 그대로
C. 실제 MainWindow — 크롭 창 '좌우 2쪽' → 썸네일에 조각이 스테이징 쪽으로(원본 그대로) → [저장] 이 원본에 쪽 수·차례·책갈피
D. [취소] 로 나누기 되돌리기 · 크롭 창 나눔선 끌기(실제 마우스)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QPoint, Qt
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_split_%d" % os.getpid())
from viewer import page_crop as pc, page_split as ps

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def quad_page(d, rot=0, w=600, h=800):
    """네 귀퉁이에 TL·TR·BL·BR 글자 — 회전 전 쪽 기준으로 두고, 보이는 방향 글자는 SHOWN 으로 본다."""
    p = d.new_page(width=w, height=h)
    p.insert_text((40, 60), "QTL"); p.insert_text((w - 90, 60), "QTR")
    p.insert_text((40, h - 40), "QBL"); p.insert_text((w - 90, h - 40), "QBR")
    p.set_rotation(rot)
    return p


root = Path(tempfile.mkdtemp(prefix="split_"))
try:
    # ── A. 크롭 50% 넘게 ───────────────────────────────────────
    chk(pc.CROP_MAX >= 95 and pc.clamp_margins([60, 50, 0, 0]) == [60, 35, 0, 0],
        "A1 한 변 95% 까지 · 위+아래 합은 95% 로 묶는다(아래를 줄임)", str(pc.clamp_margins([60, 50, 0, 0])))
    chk(pc.clamp_margins([60, 50, 0, 0], keep=1) == [45, 50, 0, 0], "A2 끄는 변(keep)은 두고 맞은편을 줄인다")
    d = fitz.open(); quad_page(d)
    p0 = d[0]
    pc.apply_margins(p0, [0, 0, 60, 0])                 # 왼쪽 60%
    chk(abs(p0.rect.width - 600 * 0.4) < 0.5 and "QTR" in p0.get_text() and "QTL" not in p0.get_text(),
        "A3 왼쪽 60% 크롭이 그대로(종전 45% 에서 잘렸다)", str(p0.rect))
    st = pc.norm_style({"id": "x", "margins": [70, 0, 0, 0]})
    chk(st["margins"][0] == 70, "A4 스타일 값도 50% 넘게 남는다", str(st["margins"]))
    d.close()

    # ── B. 나누기 계산 ───────────────────────────────────────────
    chk(ps.parts({"mode": "v"}) == [(0, 0, .5, 1), (.5, 0, 1, 1)] and ps.parts({"mode": "v", "rtl": True})[0][0] == .5,
        "B1 좌우 — 왼→오, '오른쪽부터' 면 오→왼")
    chk([f[:2] for f in ps.parts({"mode": "4"})] == [(0, 0), (.5, 0), (0, .5), (.5, .5)], "B2 4쪽 — 위 줄 먼저 왼→오")
    chk(ps.part_margins([10, 10, 20, 0], (0.5, 0, 1, 1)) == [10, 10, 60.0, 0.0],
        "B3 크롭 뒤 영역 기준 — 왼 20%·남은 폭 80% 의 오른쪽 반 = 왼 60%", str(ps.part_margins([10, 10, 20, 0], (0.5, 0, 1, 1))))
    src = root / "q.pdf"
    d = fitz.open()
    quad_page(d, 0); quad_page(d, 90)
    d.set_toc([[1, "첫 쪽", 1], [1, "둘째 쪽", 2]])
    d.save(str(src)); d.close()
    out = root / "parts.pdf"
    got = ps.build_parts(src, [0, 1], {0: None, 1: None}, {"mode": "4"}, out, with_pending_rotation=False)
    o = fitz.open(str(out))
    # 글자는 잘린 쪽 안의 것만 — get_text 의 clip 은 회전 전 쪽 좌표라 보이는 쪽 사각형을 되돌려 준다
    def _clip(pg):
        r = pg.rect * pg.derotation_matrix
        r.normalize()
        return r
    words = [sorted(w for w in ("QTL", "QTR", "QBL", "QBR") if w in o[i].get_text("text", clip=_clip(o[i]))) for i in range(o.page_count)]
    chk(got == {0: [0, 1, 2, 3], 1: [4, 5, 6, 7]} and words[:4] == [["QTL"], ["QTR"], ["QBL"], ["QBR"]],
        "B4 4쪽 — 조각마다 그 귀퉁이 글자만 보인다(글자는 그대로 남은 쪽 내용)", str((got, words[:4])))
    # 회전 90 쪽: 보이는 왼쪽 위 = 회전 전 왼쪽 아래(QBL)
    chk(words[4:] == [["QBL"], ["QTL"], ["QBR"], ["QTR"]], "B5 회전한 쪽은 보이는 방향으로 나눈다", str(words[4:]))
    chk(all(abs(o[i].rect.width - 300) < 1 and abs(o[i].rect.height - 400) < 1 for i in range(4)), "B6 조각 크기 = 반·반")
    o.close()
    out2 = root / "parts2.pdf"
    ps.build_parts(src, [0], {0: [0, 0, 0, 0]}, {"mode": "v", "x": 30}, out2, with_pending_rotation=False)
    o = fitz.open(str(out2))
    chk(abs(o[0].rect.width - 180) < 1 and abs(o[1].rect.width - 420) < 1, "B7 나눔선 위치 30% — 조각 폭 180·420",
        str((o[0].rect, o[1].rect)))
    o.close()

    # ── C. 실제 MainWindow ────────────────────────────────────────
    folder = root / "folder"; folder.mkdir()
    doc_path = folder / "책.pdf"
    d = fitz.open()
    for i in range(3):
        p = d.new_page(width=842, height=595)            # 두 쪽이 한 장에 찍힌 스캔처럼
        p.insert_text((100, 300), "LEFT%d" % (i + 1)); p.insert_text((520, 300), "RIGHT%d" % (i + 1))
    d.set_toc([[1, "1장", 1], [1, "2장", 2], [1, "3장", 3]])
    d.save(str(doc_path)); d.close()
    orig = doc_path.read_bytes()
    from viewer.app import MainWindow
    from viewer.widgets import crop_dialog as cd
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 850); mw.show(); spin(0.3)
    mw.open_folder(str(folder)); spin(0.8)
    mw.open_pdfs([str(doc_path)]); spin(1.0)
    mv = mw.main_view
    warns = []
    QMessageBox.warning = staticmethod(lambda *a, **k: warns.append(a[2] if len(a) > 2 else ""))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    seen = {}

    def fake_exec(dlg):
        dlg.rb_all.setChecked(True)
        dlg.cmb_split.setCurrentIndex(dlg.cmb_split.findData("v"))
        seen["ok"] = dlg.btn_ok.text(); seen["reset"] = dlg.btn_reset.isEnabled()
        # D2 — 미리보기의 나눔선을 실제 마우스로 끌어 40% 로
        cv = dlg.canvas
        cv.resize(400, 500)
        r = cv._img_rect(); c = cv._crop_rect(r)
        x50 = int(c.left() + c.width() * 0.5); y = int(c.center().y())
        QTest.mousePress(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x50, y))
        QTest.mouseMove(cv, QPoint(int(c.left() + c.width() * 0.45), y))
        QTest.mouseMove(cv, QPoint(int(c.left() + c.width() * 0.40), y))
        QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(c.left() + c.width() * 0.40), y))
        seen["sx"] = dlg.spin_sx.value()
        dlg.spin_sx.setValue(50.0)
        seen["plan"] = dlg.result_plan()
        dlg._accept_crop()
        return QDialog.DialogCode.Accepted
    cd.CropDialog.exec = fake_exec
    mv.btn_crop.click(); spin(2.0)
    chk(seen.get("ok") == "나누기" and seen.get("reset") is False and abs(seen.get("sx", 0) - 40) < 2,
        "D2 나누기를 고르면 [나누기] 단추 · 해제 끔 · 나눔선을 끌면 % 칸이 따라온다", str(seen.get("sx")))
    pt = mw.page_thumbs
    plan = pt.current_page_plan()
    chk(doc_path.read_bytes() == orig and len(plan) == 6 and all(e[0] == "ext" for e in plan),
        "C1 '나누기' 는 저장 전 — 원본 그대로, 썸네일은 3쪽 → 6쪽(스테이징)", str(plan[:2]))
    chk(mw.bookmark_tree.is_edit_mode() and mw._page_edits_dirty(), "C2 편집 모드 · 미저장 변경")
    chk(mv.current_page() >= pt.STAGED_BASE, "C3 본문이 첫 조각을 보인다", str(mv.current_page()))
    it = mw.main_view._page_item
    ar = (it.boundingRect().width() / max(1.0, it.boundingRect().height())) if it is not None else 0
    chk(it is not None and abs(ar - 421.0 / 595.0) < 0.03,
        "C3a 본문이 조각을 **실제로 그린다**(종전: 끼운 쪽 렌더가 예외로 빠져 앞 쪽 그림이 남았다)", "%.3f" % ar)
    sel = [n for n in mw.bookmark_tree._iter_file_nodes() if Path(str(n.data(0, mw.bookmark_tree.DATA_FILE))).name == "책.pdf"]
    if sel:
        mw.bookmark_tree.tree.setCurrentItem(sel[0])
    spin(0.6)                                            # 행을 고른 뒤의 미뤄 둔 이동이 끝나게(사용자는 누른 뒤 저장한다)
    plan_after_nav = len(mw.page_thumbs.current_page_plan())
    mw.bookmark_tree.btn_save.click(); spin(2.0)
    o = fitz.open(str(doc_path))
    texts = [o[i].get_text("text", clip=o[i].rect).strip() for i in range(o.page_count)]
    toc = [(t, p) for _l, t, p in o.get_toc()]
    o.close()
    chk(plan_after_nav == 6, "C3b 같은 파일 행을 눌러도 나눈 조각(스테이징)은 남는다", str(plan_after_nav))
    chk(len(texts) == 6 and texts[0].startswith("LEFT1") and texts[1].startswith("RIGHT1") and texts[4].startswith("LEFT3"),
        "C4 [저장] → 원본이 6쪽, 왼→오 차례", str(texts))
    chk(toc == [("1장", 1), ("2장", 3), ("3장", 5)], "C5 책갈피는 나눈 첫 조각으로", str(toc))
    chk(not mw._page_edits_dirty(), "C6 저장 뒤 미저장 변경 없음")

    # D1 — 나누기 뒤 [취소] 로 되돌리기
    mw.open_pdfs([str(doc_path)]); spin(0.8)
    before = doc_path.read_bytes()
    cd.CropDialog.exec = fake_exec
    mw.main_view.btn_crop.click(); spin(2.0)
    n_staged = len(mw.page_thumbs.current_page_plan())
    mw.bookmark_tree.btn_cancel.click(); spin(1.2)
    chk(n_staged == 12 and doc_path.read_bytes() == before and len(mw.page_thumbs.current_page_plan()) == 6
        and not mw._page_edits_dirty(), "D1 [취소] → 나누기를 버리고 6쪽 그대로", str(n_staged))
    chk(not warns, "C~D 경고 없음", str(warns[:2]))
    mw.close(); spin(0.2)
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(str(root), ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
