# -*- coding: utf-8 -*-
"""261010-7: 쪽 크롭 — PDF 의 CropBox (마스터 §4.7.15).

A. 계산: 회전 0·90·180·270 × MediaBox 원점 0/0 아님 — '보이는 위' 여백을 자르면 보이는 위쪽 글자만 사라진다
   (PyMuPDF `set_cropbox` 는 원점이 0 이 아닌 쪽에서 어긋났다 — 수정 전 방식으로는 실패)
B. 흰 여백 자동 감지 · 홀짝 좌우 대칭 · 크롭 해제 · 이미 잘렸는지
C. 범위 해석 · 스타일 자동 배정(가로긴/세로긴) · 설정 스타일 읽기(기본 2개 늘 앞, 지울 수 없음)
D. 실제 MainWindow — 툴바 크롭 단추 → '적용' 은 저장 전 크롭(원본 그대로·본문은 잘린 모양·편집 모드) → [저장] 이 원본에
E. 썸네일 메뉴 '크롭…'·'크롭 해제', [취소] 로 저장 전 크롭 되돌리기
F. 평탄화해서 내보내기 — 새 파일로만(261011-2), 크롭 바깥을 실제로 지우고 쪽 크기를 줄인다(261010-13)
"""
import os, sys, tempfile, shutil, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog

app = QApplication.instance() or QApplication(sys.argv[:1])
QCoreApplication.setApplicationName("polypdf_crop_%d" % os.getpid())
from viewer import page_crop as pc

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def spin(sec=0.3):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents(); time.sleep(0.01)


def words(page):
    t = page.get_text()
    return {w for w in ("TOP", "BOTTOM", "LEFT", "RIGHT") if w in t}


def mk(rot, offset=False):
    d = fitz.open(); p = d.new_page(width=600, height=800)
    if offset:
        p.set_mediabox(fitz.Rect(10, 20, 610, 820))
    mb = p.rect                      # PyMuPDF 좌표(왼쪽 위) — 글자를 쪽 안쪽에 둔다
    p.insert_text((mb.x0 + 280, mb.y0 + 60), "TOP")
    p.insert_text((mb.x0 + 270, mb.y1 - 60), "BOTTOM")
    p.insert_text((mb.x0 + 20, mb.y0 + 400), "LEFT")
    p.insert_text((mb.x1 - 70, mb.y0 + 400), "RIGHT")
    p.set_rotation(rot)
    return d


# 회전 전 쪽의 어느 글자가 '보이는 위' 에 오나
SHOWN_TOP = {0: "TOP", 90: "LEFT", 180: "BOTTOM", 270: "RIGHT"}

# ── A ─────────────────────────────────────────────────────────────
for off in (False, True):
    for rot in (0, 90, 180, 270):
        d = mk(rot, off); p = d[0]
        before = words(p)
        pc.set_crop(p, pc.crop_box(p, [15, 0, 0, 0]))
        p = d[0]
        gone = before - words(p)
        chk(gone == {SHOWN_TOP[rot]}, "A 회전 %d·원점 %s — 보이는 위 15%% 만 잘린다" % (rot, "어긋남" if off else "0"),
            "사라진 것 %s, 처음 %s" % (sorted(gone), sorted(before)))
        w, h = pc.full_size_pt(p)
        chk(abs(p.rect.height - h * 0.85) < 1 and abs(p.rect.width - w) < 1,
            "A 회전 %d·원점 %s — 보이는 크기 = 높이 85%%" % (rot, "어긋남" if off else "0"), str(p.rect))
        d.close()

# ── B ─────────────────────────────────────────────────────────────
d = fitz.open(); p = d.new_page(width=500, height=700)
p.draw_rect(fitz.Rect(100, 140, 400, 560), color=(0, 0, 0), fill=(0, 0, 0))
m = pc.detect_margins(p)
exp = [20.0, 20.0, 20.0, 20.0]
chk(m is not None and all(abs(a - b) < 1.5 for a, b in zip(m, exp)), "B 흰 여백 감지 — 내용 경계(각 20%)", str(m))
d2 = fitz.open(); blank = d2.new_page()
chk(pc.detect_margins(blank) is None, "B 빈 쪽은 감지 결과 없음")
chk(pc.margins_for(blank, 0, {"margins": [1, 1, 1, 1], "auto": True}) is None, "B 자동 감지 스타일 — 빈 쪽은 자르지 않는다")
st = {"margins": [2, 2, 2, 2], "auto": True}
mm = pc.margins_for(p, 0, st)
chk(mm and all(abs(v - 18.0) < 1.5 for v in mm), "B 자동 감지 + 남길 여백 2% → 18%", str(mm))
mir = {"margins": [0, 0, 5, 10], "mirror": True}
chk(pc.margins_for(p, 0, mir)[2:] == [5, 10] and pc.margins_for(p, 1, mir)[2:] == [10, 5],
    "B 홀짝 대칭 — 짝수 쪽(2쪽)은 좌우를 바꾼다")
chk(not pc.is_cropped(p), "B 처음엔 잘리지 않음")
pc.set_crop(p, pc.crop_box(p, [5, 5, 5, 5]))
chk(pc.is_cropped(d[0]), "B 자른 뒤 '잘림'")
pc.reset_crop(d[0])
chk(not pc.is_cropped(d[0]) and abs(d[0].rect.width - 500) < 0.5, "B 크롭 해제 — 쪽 전체로")

# ── C ─────────────────────────────────────────────────────────────
chk(pc.parse_range("1-3, 5 9-8, 99", 10) == [0, 1, 2, 4, 7, 8], "C 범위 '1-3, 5 9-8, 99' (뒤집힌 범위·넘는 번호)",
    str(pc.parse_range("1-3, 5 9-8, 99", 10)))
dm = fitz.open()
dm.new_page(width=595, height=842); dm.new_page(width=842, height=595)
r = dm.new_page(width=595, height=842); r.set_rotation(90)          # 세로 종이를 돌려 가로로 보이는 쪽
styles = pc.load_styles([{"id": "user1", "name": "책", "margins": [1, 2, 3, 4]}])
chk([s["id"] for s in styles] == ["portrait", "landscape", "user1"], "C 설정 스타일 — 기본 2개가 늘 앞",
    str([s["id"] for s in styles]))
a = pc.assign_styles(dm, [0, 1, 2], styles, {"on": True, "portrait": "user1", "landscape": "landscape"}, "portrait")
chk([a[i]["id"] for i in (0, 1, 2)] == ["user1", "landscape", "landscape"],
    "C 자동 적용 — 방향으로(돌린 세로 종이는 가로긴 쪽)", str([a[i]["id"] for i in (0, 1, 2)]))
a = pc.assign_styles(dm, [0, 1, 2], styles, {"on": False}, "user1")
chk({a[i]["id"] for i in (0, 1, 2)} == {"user1"}, "C 자동 끄면 고른 스타일 하나")

# ── D: 실제 앱 — '적용' 은 저장 전 크롭, '저장' 이 원본에(261010-13) ──────────────
root = Path(tempfile.mkdtemp(prefix="polypdf_crop_"))
errs = []
sys.excepthook = lambda t, v, tb: errs.append("%s: %s" % (t.__name__, v))
try:
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    warns = []
    QMessageBox.warning = staticmethod(lambda *a, **k: warns.append(a[2] if len(a) > 2 else ""))
    src = root / "mixed.pdf"
    dd = fitz.open()
    for i in range(4):
        w, h = (842, 595) if i == 2 else (595, 842)
        pg = dd.new_page(width=w, height=h)
        pg.insert_text((80, 40), "OUTTOP%d" % (i + 1), fontsize=12)
        pg.insert_text((80, 300), "Page %d" % (i + 1), fontsize=18)
    dd.save(str(src)); dd.close()
    from viewer.app import MainWindow
    from viewer.widgets import crop_dialog as cd
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 850); mw.show(); spin(0.3)
    mw.open_folder(root); spin(0.8)
    mw.open_pdfs([src]); spin(1.0)
    mv = mw.main_view
    chk(mv.current_file() and Path(mv.current_file()).name == "mixed.pdf", "D 준비 — 본문에 열림", str(mv.current_file()))
    bar = mv._toolbar
    idx = {bar.itemAt(i).widget(): i for i in range(bar.count()) if bar.itemAt(i).widget() is not None}
    chk(mv.btn_crop in idx and idx[mv.btn_crop] == idx[mv.btn_zoom_in] + 1, "D 크롭 단추가 '+' 바로 오른쪽")
    chk(not mv.btn_crop.icon().isNull(), "D 크롭 단추에 그림")

    seen = {}

    def fake_exec(dlg):
        """사용자가 하는 그대로 — 세로긴 쪽 스타일 위 10%, 범위는 창이 받은 그대로."""
        seen["sel"] = dlg.rb_sel.isChecked()
        seen["pages"] = dlg.target_pages()
        dlg.cmb_style.setCurrentIndex(dlg.cmb_style.findData("portrait"))
        dlg.spins[0].setValue(10.0)
        dlg._accept_crop()
        return QDialog.DialogCode.Accepted
    cd.CropDialog.exec = fake_exec

    def disk_heights():
        o = fitz.open(str(src)); hs = [round(o[i].rect.height) for i in range(o.page_count)]; o.close()
        return hs
    mv.btn_crop.click(); spin(1.5)
    chk(disk_heights() == [842, 842, 595, 842], "D '적용' 만으로는 원본이 바뀌지 않는다(저장 전 크롭)", str(disk_heights()))
    chk(round(mw.main_view._doc.doc[0].rect.height) == round(842 * 0.9), "D 본문은 잘린 모양으로 보인다",
        str(mw.main_view._doc.doc[0].rect))
    chk(mw.bookmark_tree.is_edit_mode() and mw._page_edits_dirty(), "D 편집 모드로 들어가고 미저장 변경으로 잡힌다")
    chk(mw._prefs.get("crop_styles") and mw._prefs["crop_styles"][0]["margins"][0] == 10.0, "D 스타일 값이 설정에 남는다")
    # 편집 모드 '저장'(실제 단추) → 원본에
    sel = [n for n in mw.bookmark_tree._iter_file_nodes() if Path(str(n.data(0, mw.bookmark_tree.DATA_FILE))).name == "mixed.pdf"]
    if sel:
        mw.bookmark_tree.tree.setCurrentItem(sel[0])
    mw.bookmark_tree.btn_save.click(); spin(1.5)
    chk(disk_heights() == [round(842 * 0.9), round(842 * 0.9), 595, round(842 * 0.9)],
        "D [저장] → 세로긴 쪽만 위 10% 잘려 원본에(가로긴 쪽은 0%)", str(disk_heights()))
    chk(not pc.has_pending(src) and not mw._page_edits_dirty(), "D 저장 뒤 저장 전 크롭 없음")

    # 썸네일 메뉴 → 고른 쪽만, 그리고 '취소' 로 되돌리기
    mw.page_thumbs.cropPagesRequested.emit([1]); spin(1.5)
    chk(seen.get("sel") and seen.get("pages") == [1], "E 썸네일 메뉴 → 창은 '고른 쪽' 으로 열린다", str(seen))
    mw.page_thumbs.uncropPagesRequested.emit([0, 1]); spin(1.5)
    chk(pc.has_pending(src) and round(mw.main_view._doc.doc[0].rect.height) == 842, "E 크롭 해제도 저장 전 — 본문은 원래 크기")
    mw.bookmark_tree.btn_cancel.click(); spin(1.2)
    chk(not pc.has_pending(src) and round(mw.main_view._doc.doc[0].rect.height) == round(842 * 0.9),
        "E [취소] → 저장 전 크롭을 버리고 디스크 상태로", str(mw.main_view._doc.doc[0].rect))
    chk(disk_heights()[0] == round(842 * 0.9), "E 취소는 원본을 바꾸지 않는다")

    # 평탄화해서 내보내기 — 새 파일: 크롭 바깥 실제로 지움
    from PyQt6.QtWidgets import QFileDialog
    out_new = root / "flat.pdf"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out_new), "PDF (*.pdf)"))
    choose = {"label": None}
    _orig_exec = QMessageBox.exec

    def box_exec(box):
        for b in box.buttons():
            if b.text() == choose["label"]:
                box._clicked = b
                b.click()
                return 0
        return _orig_exec(box)
    QMessageBox.exec = box_exec
    from viewer.i18n import tr as _tr
    mw._action_save_decorated_pdf(); spin(0.5)      # 261011-2: 묻지 않고 새 파일로
    o = fitz.open(str(out_new))
    p0 = o[0]
    pc.set_crop(p0, [p0.mediabox.x0, p0.mediabox.y0, p0.mediabox.x1, p0.mediabox.y1])
    chk(out_new.exists() and "OUTTOP1" not in o[0].get_text() and "Page 1" in o[0].get_text(),
        "F 평탄화 새 파일 — 크롭 바깥 글자가 실제로 없다(쪽을 넓혀도)", repr(o[0].get_text()[:60]))
    chk(round(o[0].mediabox.height) == round(842 * 0.9), "F 쪽 크기(MediaBox)가 크롭 크기", str(o[0].mediabox))
    o.close()
    chk(disk_heights()[0] == round(842 * 0.9), "F 새 파일로 저장하면 원본은 그대로")
    # 261011-2(§4.7.16): 현재 파일에 굽기는 없앴다 — 같은 이름을 고르면 막고 원본은 그대로
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(src), "PDF (*.pdf)"))
    mw._action_save_decorated_pdf(); spin(0.5)
    with fitz.open(str(src)) as o:
        chk("OUTTOP1" in "".join(p.get_text() for p in o) or o[0].mediabox.height > round(842 * 0.9) - 1,
            "F 원본과 같은 이름으로는 내보내지 않는다(원본 그대로)")
    QMessageBox.exec = _orig_exec
    chk(not warns and not errs, "D~F 경고·예외 없음", str(warns[:2] + errs[:2]))
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
