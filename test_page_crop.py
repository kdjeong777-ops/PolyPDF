# -*- coding: utf-8 -*-
"""261010-7: 쪽 크롭 — PDF 의 CropBox (마스터 §4.7.15).

A. 계산: 회전 0·90·180·270 × MediaBox 원점 0/0 아님 — '보이는 위' 여백을 자르면 보이는 위쪽 글자만 사라진다
   (PyMuPDF `set_cropbox` 는 원점이 0 이 아닌 쪽에서 어긋났다 — 수정 전 방식으로는 실패)
B. 흰 여백 자동 감지 · 홀짝 좌우 대칭 · 크롭 해제 · 이미 잘렸는지
C. 범위 해석 · 스타일 자동 배정(가로긴/세로긴) · 설정 스타일 읽기(기본 2개 늘 앞, 지울 수 없음)
D. 실제 MainWindow — 툴바 '+' 오른쪽 크롭 단추와 썸네일 메뉴 신호가 크롭 창을 거쳐 **원본 PDF 에 저장**하고
   다시 연다. 크롭 해제도. 크롭 창은 exec 만 바꿔 끼운다(값은 실제 위젯으로 고른다)
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

# ── D: 실제 앱 ────────────────────────────────────────────────────
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
        pg.insert_text((80, 120), "Page %d" % (i + 1), fontsize=18)
    dd.save(str(src)); dd.close()
    from viewer.app import MainWindow
    from viewer.widgets import crop_dialog as cd
    mw = MainWindow(); mw._skip_save_on_close = True
    mw.resize(1300, 850); mw.show(); spin(0.3)
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
    mv.btn_crop.click(); spin(1.5)
    out = fitz.open(str(src))
    hs = [round(out[i].rect.height) for i in range(4)]
    out.close()
    chk(hs == [round(842 * 0.9), round(842 * 0.9), 595, round(842 * 0.9)],
        "D 툴바 단추 → 전체에 자동 적용, 세로긴 쪽만 위 10% 잘려 **원본에** 저장(가로긴 쪽은 0%)", str(hs))
    chk(mw._prefs.get("crop_styles") and mw._prefs["crop_styles"][0]["margins"][0] == 10.0, "D 스타일 값이 설정에 남는다")
    spin(0.5)
    chk(mw.main_view.current_file() and Path(mw.main_view.current_file()).name == "mixed.pdf", "D 저장 뒤 다시 열림")

    # 썸네일 메뉴 → 고른 쪽만
    mw.page_thumbs.cropPagesRequested.emit([1]); spin(1.5)
    chk(seen.get("sel") and seen.get("pages") == [1], "D 썸네일 메뉴 → 창은 '고른 쪽' 으로 열린다", str(seen))
    mw.page_thumbs.uncropPagesRequested.emit([0, 1]); spin(1.5)
    out = fitz.open(str(src))
    hs = [round(out[i].rect.height) for i in range(4)]
    cropped = [pc.is_cropped(out[i]) for i in range(4)]
    out.close()
    chk(hs[:2] == [842, 842] and hs[3] == round(842 * 0.9) and cropped == [False, False, False, True],
        "D 썸네일 '크롭 해제' → 고른 쪽만 원래 크기", str((hs, cropped)))
    chk(not warns and not errs, "D 경고·예외 없음", str(warns[:2] + errs[:2]))
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
