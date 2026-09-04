# -*- coding: utf-8 -*-
"""260904-1: 목차 쪽 지정 → 관대한 파서 → 오프셋 추정 → 검토 표 → 저장 (마스터 §4.4)."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

from viewer import toc_parse as T

# ── ① 줄 파서: 슬래시·다중 항목·OCR 숫자·장 제목·로마 숫자 ────────────────
chk(T.parse_line("1)검사점수/10 2)반응의내용과주제/ll") ==
    [{"title": "1)검사점수", "toc_page": 10}, {"title": "2)반응의내용과주제", "toc_page": 11}],
    "① 한 줄 두 항목 + OCR 'll'→11")
chk(T.parse_line("1 개관 / 13") == [{"title": "1 개관", "toc_page": 13}], "① '제목 / 쪽'")
chk(T.parse_line("제1장 총칙 ……… 15") == [{"title": "제1장 총칙", "toc_page": 15}], "① 점선 리더(기존 형식 호환)")
chk(T.parse_line("제 1 장 심리검사에 대한 개관") == [{"title": "제 1 장 심리검사에 대한 개관", "toc_page": None}],
    "① 쪽번호 없는 장 제목은 보류 행")
chk(T.parse_line("지은이의 말 / vi")[0].get("front") is True, "① 로마 숫자 쪽(앞 부속) 표식")
chk(T.parse_line("차 례") == [] and T.parse_line("顥\\式표구 냥훈") == [], "① 머리글·잡글자 무시")
chk(T.fix_ocr_number("3l9") == 319 and T.fix_ocr_number("1 63") == 163 and T.fix_ocr_number("lOO") == 100,
    "① OCR 숫자 교정")
chk(T.parse_page_spec("6-11, 14", 352) == [6, 7, 8, 9, 10, 11, 14] and T.parse_page_spec("400", 352) == [],
    "① 쪽 범위 표기 파싱(범위 밖 제거)")

# ── ② 표본 PDF: 차례 1쪽(슬래시 형식·다중 항목) + 본문 ─────────────────────
root = Path(tempfile.mkdtemp(prefix="polypdf_toc_"))
pdf = root / "book.pdf"
d = fitz.open()
d.new_page().insert_text((60, 80), "COVER")                                   # p1
toc = d.new_page()                                                            # p2 = 차례
y = 80
for ln in ["차 례", "Chapter 1 Introduction / 1", "1 Overview / 1", "1)Scope/2 2)Terms/3",
           "Chapter 2 Methods / 5", "1 Design / 5", "2 Analysis / 7", "References / 9"]:
    toc.insert_text((60 if not ln.startswith(("1)", "1 ", "2 ")) else 90, y), ln); y += 22
body = {1: "Introduction\nOverview text", 2: "Scope of work", 3: "Terms and definitions", 4: "filler",
        5: "Methods\nDesign of study", 6: "filler", 7: "Analysis of results", 8: "filler", 9: "References list"}
for i in range(1, 10):                                                        # 본문 1..9 → PDF p3..p11 (오프셋 2)
    d.new_page().insert_text((60, 80), body[i])
d.save(str(pdf)); d.close()
_dd = fitz.open(str(pdf)); N = _dd.page_count; _dd.close()

rows = T.parse_toc_pages(pdf, [2])
titles = [r["title"] for r in rows]
chk(len(rows) == 8, "② 차례 1쪽 → 8행(장 제목 포함, 다중 항목 분리)", f"{titles}")
chk(rows[0]["title"].startswith("Chapter 1") and rows[0]["level"] == 0 and rows[0]["toc_page"] == 1,
    "② 장 제목 L0", f"{rows[0]}")
lv = {r["title"]: r["level"] for r in rows}
chk(lv.get("1 Overview") == 1 and lv.get("1)Scope") == 2 and lv.get("2)Terms") == 2, "② 번호 패턴 → 레벨 1/2", f"{lv}")
cands = T.suggest_offsets(pdf, rows, [2])
chk(cands and cands[0][0] == 2, "② 오프셋 추정 = 2 (본문이 p3 부터)", f"{cands[:3]}")
T.apply_offset(rows, 2, N)
chk(all(r["page"] == r["toc_page"] + 2 for r in rows), "② 오프셋 적용 → 실제 쪽")
v = T.verify_rows(pdf, rows)
chk(sum(v.values()) >= 6, "② 제목 대조 — 대부분 ✓", f"{sum(v.values())}/{len(rows)}")
rows[1]["page"] = 11; rows[1]["manual"] = True
T.apply_offset(rows, 2, N, keep_manual=True)
chk(rows[1]["page"] == 11, "② 수동 고친 행은 오프셋 재적용에도 유지")
bms = T.to_bookmarks(rows)
chk(len(bms) == 8 and bms[0] == (rows[0]["title"], 3, 0), "② to_bookmarks (title, page, level)")

# ── ③ 검토 창 ───────────────────────────────────────────────────────────
app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.toc_review_dialog import TocReviewDialog, COL_PAGE, COL_TITLE, COL_LEVEL, COL_OK
rows2 = T.parse_toc_pages(pdf, [2])
dlg = TocReviewDialog(pdf, rows2, offset=2, candidates=cands, method="toc", toc_pages=[2])
dlg.show(); app.processEvents()
chk(dlg.table.rowCount() == 8 and dlg.table.item(0, COL_PAGE).text() == "3", "③ 표 8행 + 오프셋 초기 적용(실제 쪽 3)")
chk(dlg.grp_offset.isVisible() and dlg.spin_offset.value() == 2, "③ 오프셋 컨트롤(목차 방식)")
chk(not dlg.lbl_pv.pixmap().isNull(), "③ 현재 행 실제 쪽 미리보기 렌더")
# 실제 쪽 직접 수정 → 수동 표시, 오프셋 재적용에도 유지
dlg.table.item(1, COL_PAGE).setText("11"); app.processEvents()
dlg.spin_offset.setValue(3); dlg._apply_offset(); app.processEvents()
chk(dlg.table.item(1, COL_PAGE).text() == "11" and dlg.table.item(0, COL_PAGE).text() == "4",
    "③ 수동 행 유지 + 나머지 오프셋 3 재적용")
dlg.spin_offset.setValue(2); dlg._apply_offset(); app.processEvents()
# 행 추가 / 레벨 / 이동 / 삭제
dlg.table.setCurrentCell(2, COL_TITLE); n0 = dlg.table.rowCount()
dlg._add_row(); app.processEvents()
chk(dlg.table.rowCount() == n0 + 1 and dlg.table.currentRow() == 3, "③ 행 추가(현재 행 아래)")
dlg.table.item(3, COL_TITLE).setText("추가 항목"); dlg.table.item(3, COL_PAGE).setText("6"); app.processEvents()
dlg.table.selectRow(3); dlg._level(+1); chk(dlg.table.item(3, COL_LEVEL).text() == "3", "③ 레벨 ▶")
dlg._move(-1); chk(dlg.table.item(2, COL_TITLE).text() == "추가 항목", "③ ▲ 이동")
dlg.table.clearSelection(); dlg.table.selectRow(2); dlg._del_rows()
chk(dlg.table.rowCount() == n0, "③ 삭제")
dlg._verify(); app.processEvents()
oks = [dlg.table.item(i, COL_OK).text() for i in range(dlg.table.rowCount())]
chk(oks.count("✓") >= 6, "③ 제목 대조 표시 ✓/✗", f"{oks}")
# 미리보기 ◀▶ 후 '이 쪽으로 확정'
dlg.table.setCurrentCell(0, COL_TITLE); app.processEvents()
dlg._pv_step(+1); dlg._pv_confirm(); app.processEvents()
chk(dlg.table.item(0, COL_PAGE).text() == "4", "③ 미리보기 ▶ 후 '이 쪽으로 확정' → 실제 쪽 4(수동)")
out = dlg.result_bookmarks()
chk(len(out) == 8 and out[0][1] == 4 and out[1][1] == 11, "③ result_bookmarks 반영", f"{out[:2]}")
dlg.close()

# ── ④ 워커: 검토 단계 → 확정 저장 ─────────────────────────────────────────
from viewer.workers import BookmarkerWorker
got = {}
opts = {"input_pdf": str(pdf), "mode": "toc", "toc_pages": [2], "review": True, "offset": None,
        "save_pdf": True, "overwrite": False, "save_txt": False, "out_dir": str(root)}
w = BookmarkerWorker(pdf, opts); w.finished.connect(lambda r: got.update(r)); w.error.connect(lambda e: got.update(err=e))
w.run()
chk(got.get("phase") == "review" and len(got.get("rows", [])) == 8 and got.get("offset") == 2,
    "④ 워커 검토 단계 — rows·offset 반환, 파일은 쓰지 않음", f"phase={got.get('phase')} err={got.get('err')}")
chk(not (root / "book_bookmarked.pdf").exists(), "④ 검토 단계에서는 저장 없음")
got.clear()
w2 = BookmarkerWorker(pdf, {**opts, "review": False, "bookmarks": out, "method": "toc"})
w2.finished.connect(lambda r: got.update(r)); w2.error.connect(lambda e: got.update(err=e)); w2.run()
outp = root / "book_bookmarked.pdf"
chk(got.get("phase") == "done" and got.get("count") == 8 and outp.exists(),
    "④ 확정 저장 — 검토 결과 8개를 PDF 에 씀", f"{got}")
_do = fitz.open(str(outp)); tocs = _do.get_toc(); _do.close()   # Windows: 핸들 닫아야 삭제 가능
chk(len(tocs) == 8 and tocs[0][2] == 4 and tocs[1][2] == 11, "④ 저장된 책갈피 = 검토 표(수동 쪽 반영)", f"{tocs[:2]}")
# 목차 쪽 미지정 + toc 모드 + 탐지 실패 → 정직한 오류
got.clear()
w3 = BookmarkerWorker(pdf, {**opts, "toc_pages": [1], "review": True})   # 표지 쪽만 지정 → 항목 없음
w3.finished.connect(lambda r: got.update(r)); w3.error.connect(lambda e: got.update(err=e)); w3.run()
chk("읽지 못했습니다" in (got.get("err") or ""), "④ 목차 쪽이 틀리면 안내 오류", f"{got.get('err')}")

# ── ⑤ 대화상자 옵션 ────────────────────────────────────────────────────
from viewer.widgets.bookmarker_dialog import BookmarkerDialog
bd = BookmarkerDialog(default_pdf=pdf, prefs={"bookmarker_review": True})
bd.edit_toc_pages.setText("2"); o = bd.result_options()
chk(o["toc_pages"] == [2] and o["review"] is True, "⑤ result_options 에 toc_pages·review", f"{o['toc_pages']}")
bd._detect_toc_pages(); app.processEvents()
chk(bd.edit_toc_pages.text() in ("2", ""), "⑤ 자동 탐지 버튼(결과 채움 또는 안내)", f"'{bd.edit_toc_pages.text()}'")
bd.close()

# ── ⑥ 앱 연동: 검토 단계 → 창 → [저장] → 확정 저장 워커 ──────────────────
from viewer.app import MainWindow
import viewer.app as _appmod
from viewer.widgets import toc_review_dialog as _trd
mw = MainWindow(); mw.show(); app.processEvents()
mw._bookmarker_pdf = pdf
out6 = root / "out6"; out6.mkdir()
mw._bookmarker_opts = {**opts, "review": True, "out_dir": str(out6)}
review = {"phase": "review", "method": "toc", "rows": T.parse_toc_pages(pdf, [2]),
          "candidates": cands, "offset": 2, "toc_pages": [2]}
# 취소 → 저장 없음
_trd.TocReviewDialog.exec = lambda self: self.DialogCode.Rejected
mw._on_bookmarker_done(dict(review)); app.processEvents()
chk(not list(out6.glob("*.pdf")), "⑥ 검토 창에서 취소 → 파일 쓰지 않음")
# 저장 → 워커를 동기 실행하도록 run_in_thread 대체
_trd.TocReviewDialog.exec = lambda self: self.DialogCode.Accepted
_appmod.run_in_thread = lambda w, keep=None: w.run()
mw._on_bookmarker_done(dict(review)); app.processEvents(); QTest.qWait(200); app.processEvents()
outs = list(out6.glob("*.pdf"))
_d6 = fitz.open(str(outs[0])) if outs else None; n6 = len(_d6.get_toc()) if _d6 else 0
if _d6: _d6.close()
chk(len(outs) >= 1 and n6 == 8,
    "⑥ 검토 창 [저장] → 확정 저장 워커 → 책갈피 8개 PDF", f"{[o.name for o in outs]}")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
