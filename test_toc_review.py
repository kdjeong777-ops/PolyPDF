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
toc2 = d.new_page()                                                           # p3 = 차례 2쪽(머리글 없음·슬래시만)
y = 80
for ln in ["Appendix A / 9", "1 Tables / 9", "2 Figures / 9", "3 Notes / 9", "4 Index / 9"]:
    toc2.insert_text((60, y), ln); y += 22
body = {1: "Introduction\nOverview text", 2: "Scope of work", 3: "Terms and definitions", 4: "filler",
        5: "Methods\nDesign of study", 6: "filler", 7: "Analysis of results", 8: "filler", 9: "References list"}
for i in range(1, 10):                                                        # 본문 1..9 → PDF p4..p12 (오프셋 3)
    d.new_page().insert_text((60, 80), body[i])
d.save(str(pdf)); d.close()
_dd = fitz.open(str(pdf)); N = _dd.page_count; _dd.close()

rows = T.parse_toc_pages(pdf, [2])
titles = [r["title"] for r in rows]
chk(len(rows) == 8, "② 차례 1쪽 → 8행(장 제목 포함, 다중 항목 분리)", f"{titles}")
chk(rows[0]["title"].startswith("Chapter 1") and rows[0]["level"] == 0 and rows[0]["toc_page"] == 1,
    "② 장 제목 L0", f"{rows[0]}")
lv = {r["title"]: r["level"] for r in rows}
chk(lv.get("1. Overview") == 1 and lv.get("1)Scope") == 2 and lv.get("2)Terms") == 2,
    "② 번호 패턴 → 레벨 1/2 (레벨 1 '1 ' 은 파서가 '1.' 로 통일)", f"{lv}")
cands = T.suggest_offsets(pdf, rows, [2, 3])
chk(cands and cands[0][0] == 3, "② 오프셋 추정 = 3 (본문이 p4 부터)", f"{cands[:3]}")
T.apply_offset(rows, 3, N)
chk(all(r["page"] == r["toc_page"] + 3 for r in rows), "② 오프셋 적용 → 실제 쪽")
v = T.verify_rows(pdf, rows)
chk(sum(v.values()) >= 6, "② 제목 대조 — 대부분 ✓", f"{sum(v.values())}/{len(rows)}")
rows[1]["page"] = 11; rows[1]["manual"] = True
T.apply_offset(rows, 3, N, keep_manual=True)
chk(rows[1]["page"] == 11, "② 수동 고친 행은 오프셋 재적용에도 유지")
bms = T.to_bookmarks(rows)
chk(len(bms) == 8 and bms[0] == (rows[0]["title"], 4, 0), "② to_bookmarks (title, page, level)")
# 260904-2: 관대한 탐지기 — 머리글 없는 2쪽째(슬래시 항목만)도 이어 잡는다
chk(T.find_toc_pages(pdf) == [2, 3], "② find_toc_pages → [2, 3](2쪽째는 머리글 없음)", f"{T.find_toc_pages(pdf)}")
chk(T.format_page_spec([6]) == "6" and T.format_page_spec([6,7,8]) == "6-8" and T.format_page_spec([6,7,9]) == "6-7, 9",
    "② format_page_spec — 한 쪽은 '6'(6-6 아님)")

# ── ③ 검토 창 ───────────────────────────────────────────────────────────
app = QApplication.instance() or QApplication(sys.argv)
from viewer.widgets.toc_review_dialog import TocReviewDialog, COL_PAGE, COL_TITLE, COL_LEVEL, N_COLS
rows2 = T.parse_toc_pages(pdf, [2])
dlg = TocReviewDialog(pdf, rows2, offset=3, candidates=cands, method="toc", toc_pages=[2])
dlg.show(); app.processEvents()
chk(dlg.table.rowCount() == 8 and dlg.table.item(0, COL_PAGE).text() == "4", "③ 표 8행 + 오프셋 초기 적용(실제 쪽 4)")
scr = app.primaryScreen().availableGeometry()
# (오프스크린 화면 800×800 은 3/4=600 이 창 최소 폭보다 작아 폭은 최소치로 눌린다 — 높이로 판정)
chk(abs(dlg.height() - int(scr.height() * 0.75)) <= 2 and dlg.width() >= int(scr.width() * 0.75),
    "③ 창 크기 = 화면의 3/4(최소 폭 이상)", f"{dlg.width()}x{dlg.height()} / {scr.width()}x{scr.height()}")
sz = dlg._split.sizes()
chk(sz[1] > sz[0], "③ 미리보기(오른쪽)가 표보다 넓음", f"{sz}")
chk(dlg.rb_pv_toc.isChecked() and "목차" in dlg.lbl_pv_title.text() and "2쪽" in dlg.lbl_pv_title.text()
    and not dlg.btn_pv_set.isEnabled(), "③ 초기 보기 = 목차(출처 차례 쪽 2), 확정 버튼 비활성", dlg.lbl_pv_title.text())
QTest.qWait(50); app.processEvents()
pm = dlg.lbl_pv.pixmap(); vp = dlg.pv_scroll.viewport()
chk(pm is not None and (pm.width() >= vp.width() - 12 or pm.height() >= vp.height() - 12),
    "③ 처음 떴을 때 미리보기가 영역에 꽉 참(표시 후 재렌더)", f"pm={pm.width()}x{pm.height()} vp={vp.width()}x{vp.height()}")
dlg.rb_pv_body.setChecked(True); app.processEvents()
chk("내용" in dlg.lbl_pv_title.text() and dlg.btn_pv_set.isEnabled(), "③ 내용 보기 전환")
# 260904-7: 제목 열 위계 들여쓰기 — 표시만(델리게이트), 텍스트는 그대로
from viewer.widgets.toc_review_dialog import _IndentDelegate, INDENT_PX
_dg = dlg.table.itemDelegateForColumn(COL_TITLE)
_i2 = dlg.table.model().index(2, COL_TITLE)      # '1)Scope' = 레벨 2
chk(isinstance(_dg, _IndentDelegate) and _dg._indent(_i2) == 2 * INDENT_PX and _dg._indent(dlg.table.model().index(0, COL_TITLE)) == 0
    and not dlg.table.item(2, COL_TITLE).text().startswith(" "),
    "③ 제목 열은 레벨×14px 들여쓰기(표시만, 텍스트 오염 없음)", f"indent={_dg._indent(_i2)}")
chk(dlg.grp_offset.isVisible() and dlg.spin_offset.value() == 3, "③ 오프셋 컨트롤(목차 방식)")
chk(not dlg.lbl_pv.pixmap().isNull(), "③ 현재 행 실제 쪽 미리보기 렌더")
# 실제 쪽 직접 수정 → 수동 표시, 오프셋 재적용에도 유지
dlg.table.item(1, COL_PAGE).setText("11"); app.processEvents()
dlg.spin_offset.setValue(4); dlg._apply_offset(); app.processEvents()
chk(dlg.table.item(1, COL_PAGE).text() == "11" and dlg.table.item(0, COL_PAGE).text() == "5",
    "③ 수동 행 유지 + 나머지 오프셋 4 재적용")
dlg.spin_offset.setValue(3); dlg._apply_offset(); app.processEvents()
# 260904-6: 실제 쪽 수정 → 이후 행(다음 수동 행 전까지) 같은 양만큼 이동 (별도 인스턴스 — 뒤 검사의 수동 상태 보존)
dlg2 = TocReviewDialog(pdf, T.parse_toc_pages(pdf, [2]), offset=3, candidates=cands, method="toc", toc_pages=[2])
dlg2.show(); app.processEvents()
before = [dlg2.table.item(i, COL_PAGE).text() for i in range(dlg2.table.rowCount())]
dlg2.table.item(1, COL_PAGE).setText(str(int(before[1]) - 1)); app.processEvents()   # 1행 수동(−1) → 2행부터 −1
dlg2.table.item(2, COL_PAGE).setText(str(int(before[2]) - 1 - 1)); app.processEvents()   # 2행 다시 −1
after = [dlg2.table.item(i, COL_PAGE).text() for i in range(dlg2.table.rowCount())]
chk(after[0] == before[0] and int(after[1]) == int(before[1]) - 1 and all(int(after[i]) == int(before[i]) - 2 for i in range(2, len(after))),
    "③ 실제 쪽 수정(76→75) → 이후 행도 같은 양(80→79), 앞 행은 그대로", f"{before} → {after}")
dlg2.table.item(5, COL_PAGE).setText(str(int(after[5]) + 1)); app.processEvents()   # 5행 수동 확정(+1 → 6,7행 +1)
dlg2.table.item(3, COL_PAGE).setText(str(int(after[3]) + 2)); app.processEvents()   # 3행 +2 → 4행만 +2(5행 수동에서 멈춤)
now = [dlg2.table.item(i, COL_PAGE).text() for i in range(8)]
chk(int(now[4]) == int(after[4]) + 2 and int(now[5]) == int(after[5]) + 1 and int(now[6]) == int(after[6]) + 1,
    "③ 이동은 다음 수동 행 전까지만(수동 행과 그 이후는 그대로)", f"{after} → {now}")
dlg2.spin_offset.setValue(3); dlg2._apply_offset(); app.processEvents()
chk(dlg2.table.item(4, COL_PAGE).text() == before[4] and dlg2.table.item(3, COL_PAGE).text() == now[3],
    "③ 옮긴 행은 수동이 아니라 [오프셋 적용] 이 다시 계산, 직접 고친 행은 유지")
dlg2.close()
# 행 추가 / 레벨 / 이동 / 삭제
dlg.table.setCurrentCell(2, COL_TITLE); n0 = dlg.table.rowCount()
dlg.rb_pv_toc.setChecked(True); app.processEvents()
pv0 = dlg._pv_page; cnt = {"n": 0}
_orig_render = dlg._render_preview
dlg._render_preview = lambda pg, keep_scroll=False: (cnt.__setitem__("n", cnt["n"] + 1), _orig_render(pg, keep_scroll))
dlg._add_row(); app.processEvents()
chk(dlg.table.rowCount() == n0 + 1 and dlg.table.currentRow() == 3, "③ 행 추가(현재 행 아래)")
chk(dlg._pv_page == pv0 and cnt["n"] == 0 and dlg._row_dict(3)["src"] == dlg._row_dict(2)["src"],
    "③ 목차 보기에서 행 추가 → 미리보기 쪽 유지(재렌더 없음, 출처 쪽 상속)", f"{pv0}→{dlg._pv_page} renders={cnt['n']}")
dlg._render_preview = _orig_render
dlg.rb_pv_body.setChecked(True); app.processEvents()
dlg.table.item(3, COL_TITLE).setText("추가 항목"); dlg.table.item(3, COL_PAGE).setText("6"); app.processEvents()
dlg.table.selectRow(3); dlg._level(+1); chk(dlg.table.item(3, COL_LEVEL).text() == "3", "③ 레벨 ▶")
dlg._move(-1); chk(dlg.table.item(2, COL_TITLE).text() == "추가 항목", "③ ▲ 이동")
dlg.table.clearSelection(); dlg.table.selectRow(2); dlg._del_rows()
chk(dlg.table.rowCount() == n0, "③ 삭제")
dlg._verify(); app.processEvents()
oks = dlg.verify_marks()
chk(N_COLS == 4 and oks.count("ok") >= 6, "③ '확인' 열 없이 제목 셀 색으로 대조 표시", f"{oks}")
# 260904-3: 번호 채우기 / 가로 꽉 차게 / ◀▶ 중앙
rows_n = [{"title": "1 개관", "level": 1, "toc_page": 1, "page": 3},
          {"title": "심리검사는 어떻게 발전되어 왔는가", "level": 2, "toc_page": 1, "page": 3},
          {"title": "심리검사에는 어떤 것들이 있는가", "level": 2, "toc_page": 6, "page": 8},
          {"title": "3)검사반응에대한태도", "level": 2, "toc_page": 11, "page": 13},
          {"title": "戶 해석", "level": 1, "toc_page": 47, "page": 49},
          {"title": "1)양적분석", "level": 2, "toc_page": 48, "page": 50}]
n_changed = T.renumber_rows(rows_n)
chk([r["title"] for r in rows_n] == ["1. 개관", "1)심리검사는 어떻게 발전되어 왔는가", "2)심리검사에는 어떤 것들이 있는가",
                                   "3)검사반응에대한태도", "2. 해석", "1)양적분석"] and n_changed == 4,
    "③ 번호 채우기 — 빠진 번호는 형제 순번, 한자 번호('戶 해석')는 순번, 레벨1 '1 '→'1.'", f"{[r['title'] for r in rows_n]}")
rows_s = [{"title": "1 개관", "level": 1}, {"title": "실시", "level": 1}]
T.renumber_rows(rows_s, style="bare")
chk([r["title"] for r in rows_s] == ["1 개관", "2 실시"], "③ 번호 형식 지정('1') 존중", f"{[r['title'] for r in rows_s]}")
# 260904-4: 번호가 빠진 형제 — 번호 폭만큼만 더 들어간 줄은 같은 레벨
d2 = fitz.open(); tp2 = d2.new_page(); yy = 80
# (helv 기본 폰트는 한글을 못 그리므로 영문 제목으로 — 구조 검사에는 충분)
# (100, "Fourth") = 번호 패턴은 없지만 '1 First' 와 같은 x → 같은 레벨(260904-5, 표본 '戶 해석')
for x, ln in ((60, "Chapter 1 Overview"), (100, "1 First / 1"), (111, "Second / 3"), (111, "Third / 5"), (122, "1)Sub/5"),
              (100, "Fourth / 6"), (60, "References / 9"), (60, "Index / 9")):
    tp2.insert_text((x, yy), ln); yy += 22
for i in range(10): d2.new_page().insert_text((60, 80), f"body{i}")
pdf2 = root / "drop.pdf"; d2.save(str(pdf2)); d2.close()
rr = T.parse_toc_pages(pdf2, [1])
got_rr = [(r["title"], r["level"]) for r in rr]
chk(got_rr[:5] == [("Chapter 1 Overview", 0), ("1. First", 1), ("2. Second", 1), ("3. Third", 1), ("1)Sub", 2)],
    "③ 번호 빠진 형제(x +11pt) → 같은 레벨(1), 더 들어간 줄만 2 — 표를 만들 때 번호 자동 복원(260904-5)", f"{got_rr}")
chk(got_rr[5] == ("4. Fourth", 1), "③ 같은 x 의 앞선 번호 항목 → 같은 레벨 + 순번(표본 '戶 해석' → '5. 해석')", f"{got_rr[5:]}")
chk([t for t, _ in got_rr[6:]] == ["References", "Index"],
    "③ 번호 있는 형제가 없는 묶음(장 급 항목)은 자동 복원이 손대지 않음", f"{got_rr[6:]}")
chk(T.renumber_rows(rr) == 0, "③ 자동 복원 뒤 [번호 채우기] 는 바꿀 것이 없음(멱등)")
# 260904-6: 커서부터 + 있는 번호도 순서대로(레벨을 고친 뒤 남은 '6) 7)' → '1) 2)')
rows_c = [{"title": "1. A", "level": 1}, {"title": "2. B", "level": 1}, {"title": "7)임상척도", "level": 1},
          {"title": "6)단독상승1", "level": 2}, {"title": "7)1-2/2-1", "level": 2}, {"title": "8)1-3/3-1", "level": 2},
          {"title": "4. C", "level": 1}]
n_c, e_c = T.renumber_from(rows_c, 2)
chk([r["title"] for r in rows_c] == ["1. A", "2. B", "7. 임상척도", "1)단독상승1", "2)1-2/2-1", "3)1-3/3-1", "4. C"] and n_c == 4 and e_c == 7,
    "③ renumber_from — 같은 레벨은 있는 번호 유지·형식만('7)'→'7.'), 아래 2레벨 '6)7)8)' → '1)2)3)'",
    f"{[r['title'] for r in rows_c]} n={n_c} end={e_c}")
rows_c[2]["title"] = "5. 임상척도"
chk(T.renumber_from(rows_c, 2)[0] == 0 and rows_c[2]["title"] == "5. 임상척도", "③ renumber_from 멱등")
# 260904-8: [번호 수정] = 바로 위 같은 레벨 형제 + 1
rows_s = [{"title": "Ch", "level": 0}, {"title": "1. A", "level": 1}, {"title": "1)a", "level": 2}, {"title": "2)b", "level": 2},
          {"title": "7)임상척도", "level": 1}, {"title": "6)x", "level": 2}, {"title": "7)y", "level": 2}, {"title": "戶 z", "level": 2}]
chk(T.number_after_sibling(rows_s, 4) == "2. 임상척도" and T.number_after_sibling(rows_s, 5) == "1)x"
    and T.number_after_sibling(rows_s, 0) is None and T.number_after_sibling(rows_s, 1) == "1. A"
    and T.number_after_sibling(rows_s, 5, style="dot") == "1. x",
    "③ 번호 수정 — 위 형제(1. A)+1 → '2. 임상척도'; 새 묶음 첫 행 → '1)x'; 장 행은 제외; 형식 지정 존중")
n1 = T.renumber_siblings_from(rows_s, 4); n2 = T.renumber_siblings_from(rows_s, 5)
chk([r["title"] for r in rows_s][4:] == ["2. 임상척도", "1)x", "2)y", "3)z"] and n1 == 1 and n2 == 3,
    "③ 번호 수정 — 현재 행(위 형제+1) 뒤 같은 레벨 형제도 이어서 → 1) 2) 3)(한자 번호도)", f"{[r['title'] for r in rows_s]} {n1} {n2}")
chk(T.renumber_siblings_from(rows_s, 5) == 0, "③ 번호 수정 멱등")
# 260904-8: 목차 쪽 순서 정렬 — 자릿수 복원 / 순서 밖 행 이동 / 표·그림 목록 구간 분리
rows_p = [{"title": "Ch1", "level": 0, "toc_page": 1}, {"title": "1. A", "level": 1, "toc_page": 1},
          {"title": "2. B", "level": 1, "toc_page": 60}, {"title": "1)b1", "level": 2, "toc_page": 66},
          {"title": "3. C", "level": 1, "toc_page": 100}, {"title": "1)c1", "level": 2, "toc_page": 113},
          {"title": "2)late", "level": 2, "toc_page": 66}, {"title": "3)late2", "level": 2, "toc_page": 66},
          {"title": "4. D", "level": 1, "toc_page": 118}, {"title": "1)d1", "level": 2, "toc_page": 20},
          {"title": "2)d2", "level": 2, "toc_page": 305}, {"title": "3)d3", "level": 2, "toc_page": 31},
          {"title": "4)d4", "level": 2, "toc_page": 312},
          {"title": "[표 2-1] t", "level": 2, "toc_page": 21}, {"title": "[표 3-1] t", "level": 2, "toc_page": 62},
          {"title": "[그림 4-1] f", "level": 2, "toc_page": 131}, {"title": "(b) f2", "level": 2, "toc_page": 232}]
n_p = T.sort_by_toc_page(rows_p)
tp = [(r["title"], r["toc_page"]) for r in rows_p]
chk(tp[:6] == [("Ch1", 1), ("1. A", 1), ("2. B", 60), ("1)b1", 66), ("2)late", 66), ("3)late2", 66)]
    and rows_p[4].get("moved") and rows_p[5].get("moved"),
    "③ 쪽 순서 — 113 뒤의 66 행 2개가 66 행 뒤(제자리)로 이동(`moved`)", f"{tp[:8]}")
_d3 = next(r for r in rows_p if r["title"] == "3)d3")
chk(("1)d1", 120) in tp and 305 <= _d3["toc_page"] <= 312 and _d3.get("repaired")
    and next(r for r in rows_p if r["title"] == "1)d1").get("repaired"),
    "③ 쪽 순서 — 자릿수 누락 복원: 20→120, 31→31x(앞뒤 순서 안의 후보, `repaired`)", f"{tp[6:13]}")
chk(tp[-4:] == [("[표 2-1] t", 21), ("[표 3-1] t", 62), ("[그림 4-1] f", 131), ("(b) f2", 232)] and n_p == 4,
    "③ 표·그림 목록은 쪽이 처음부터 — 구간을 나눠 그대로", f"{tp[-4:]} n={n_p}")
chk(T.sort_by_toc_page(rows_p) == 0, "③ 정렬 멱등")
rows_r = [{"title": "T", "level": 1}, {"title": "6)a", "level": 2}, {"title": "7)b", "level": 2}, {"title": "36)c", "level": 2},
          {"title": "2)d", "level": 2}, {"title": "4)e", "level": 2}]
T.renumber_from(rows_r, 0)
chk([r["title"] for r in rows_r][1:] == ["1)a", "2)b", "3)c", "2)d", "3)e"],
    "③ 깊은 레벨 재번호 중 원문 번호가 다시 작아지면(36)→2)) 새 묶음으로 보고 그 번호부터", f"{[r['title'] for r in rows_r]}")
rows_c2 = [{"title": "1)a", "level": 2}, {"title": "5)b", "level": 2}, {"title": "9)c", "level": 2}]
T.renumber_rows(rows_c2, start=1, reseq=True)
chk([r["title"] for r in rows_c2] == ["1)a", "2)b", "3)c"], "③ 커서 앞 행은 손대지 않고 그 번호에서 이어 센다")
rows_e = [{"title": "Ch1", "level": 0}, {"title": "1. A", "level": 1}, {"title": "7)x", "level": 2}, {"title": "8)y", "level": 2},
          {"title": "2. B", "level": 1}, {"title": "Ch2", "level": 0}, {"title": "5. Z", "level": 1}, {"title": "[fig 1]", "level": 2},
          {"title": "[fig 2]", "level": 2}]
n_e, e = T.renumber_from(rows_e, 1)                      # 커서 = '1. A'(L1) → 범위는 Ch2 전까지
chk(e == 5 and [r["title"] for r in rows_e] == ["Ch1", "1. A", "1)x", "2)y", "2. B", "Ch2", "5. Z", "[fig 1]", "[fig 2]"] and n_e == 2,
    "③ 범위 = 커서 행의 묶음 끝까지(상위 레벨 전) — 뒤 장·번호 없는 그림 목록은 그대로", f"end={e} {[r['title'] for r in rows_e]}")
chk(T.group_end(rows_e, 0) == 5 and T.group_end(rows_e, 6) == 9 and T.group_end(rows_e, 2) == 4,
    "③ 장 행에서는 다음 장 전까지, 마지막 묶음은 끝까지")
chk(T.renumber_from(rows_e, 6)[0] == 0 and rows_e[7]["title"] == "[fig 1]", "③ 번호 없는 하위 묶음은 그대로(첫 항목에 번호를 적어야 채움)")
rows_e[7]["title"] = "1)[fig 1]"
chk(T.renumber_from(rows_e, 6)[0] == 1 and rows_e[8]["title"] == "2)[fig 2]", "③ 첫 항목에 '1)' 을 적으면 나머지를 채움")
T.renumber_rows(rr, style="paren")
chk([r["title"] for r in rr][1:4] == ["1)First", "2)Second", "3)Third"] or [r["title"] for r in rr][1] == "1)First",
    "③ [번호 채우기] 형식 콤보로 재형식화", f"{[r['title'] for r in rr][1:4]}")
dlg.table.setCurrentCell(0, COL_TITLE); app.processEvents()
h0 = dlg.lbl_pv.pixmap().height(); w0 = dlg.lbl_pv.pixmap().width()
dlg.chk_fit_width.setChecked(True); app.processEvents()
h1 = dlg.lbl_pv.pixmap().height(); w1 = dlg.lbl_pv.pixmap().width()
chk(w1 >= w0 and h1 > h0 and w1 >= dlg.pv_scroll.viewport().width() - 8,
    "③ '가로 꽉 차게' → 폭 맞춤(세로는 스크롤)", f"{w0}x{h0} → {w1}x{h1} vp={dlg.pv_scroll.viewport().width()}")
dlg.chk_fit_width.setChecked(False); app.processEvents()
nav = dlg._nav      # ◀▶ 양옆에 stretch 가 있어 중앙에 온다
chk(nav.itemAt(0).spacerItem() is not None and nav.indexOf(dlg.btn_pv_prev) == 1
    and nav.itemAt(nav.indexOf(dlg.btn_pv_next) + 1).spacerItem() is not None,
    "③ ◀▶ 쪽 이동 버튼이 미리보기 폭 중앙(양옆 stretch)")
# 260904-8: 가로 꽉 차게에서 ▶ 는 다음 쪽 상단, ◀ 는 이전 쪽 하단
dlg.table.setCurrentCell(0, COL_TITLE); app.processEvents()
dlg.chk_fit_width.setChecked(True); app.processEvents()
sb = dlg.pv_scroll.verticalScrollBar(); sb.setValue(sb.maximum() // 2); app.processEvents()
dlg._pv_step(+1); app.processEvents(); app.processEvents()
v_next = sb.value()
dlg._pv_step(-1); app.processEvents(); app.processEvents()
v_prev, mx = sb.value(), sb.maximum()
chk(v_next == 0 and mx > 0 and v_prev == mx, "③ ▶ 다음 쪽 상단 / ◀ 이전 쪽 하단(가로 꽉 차게)", f"next={v_next} prev={v_prev}/{mx}")
dlg.chk_fit_width.setChecked(False); app.processEvents()
chk(dlg.btn_renumber.text() == "번호 수정", "③ 버튼 이름 '번호 수정'")
# 미리보기 ◀▶ 후 '이 쪽으로 확정'
dlg.table.setCurrentCell(0, COL_TITLE); app.processEvents()
dlg._pv_step(+1); dlg._pv_confirm(); app.processEvents()
chk(dlg.table.item(0, COL_PAGE).text() == "5", "③ 미리보기 ▶ 후 '이 쪽으로 확정' → 실제 쪽 5(수동)")
out = dlg.result_bookmarks()
chk(len(out) == 8 and out[0][1] == 5 and out[1][1] == 11, "③ result_bookmarks 반영", f"{out[:2]}")
dlg.close()

# ── ④ 워커: 검토 단계 → 확정 저장 ─────────────────────────────────────────
from viewer.workers import BookmarkerWorker
got = {}
opts = {"input_pdf": str(pdf), "mode": "toc", "toc_pages": [2], "review": True, "offset": None,
        "save_pdf": True, "overwrite": False, "save_txt": False, "out_dir": str(root)}
w = BookmarkerWorker(pdf, opts); w.finished.connect(lambda r: got.update(r)); w.error.connect(lambda e: got.update(err=e))
w.run()
chk(got.get("phase") == "review" and len(got.get("rows", [])) == 8 and got.get("offset") == 3,
    "④ 워커 검토 단계 — rows·offset 반환, 파일은 쓰지 않음", f"phase={got.get('phase')} err={got.get('err')}")
chk(not (root / "book_bookmarked.pdf").exists(), "④ 검토 단계에서는 저장 없음")
got.clear()
w2 = BookmarkerWorker(pdf, {**opts, "review": False, "bookmarks": out, "method": "toc"})
w2.finished.connect(lambda r: got.update(r)); w2.error.connect(lambda e: got.update(err=e)); w2.run()
outp = root / "book_bookmarked.pdf"
chk(got.get("phase") == "done" and got.get("count") == 8 and outp.exists(),
    "④ 확정 저장 — 검토 결과 8개를 PDF 에 씀", f"{got}")
_do = fitz.open(str(outp)); tocs = _do.get_toc(); _do.close()   # Windows: 핸들 닫아야 삭제 가능
chk(len(tocs) == 8 and tocs[0][2] == 5 and tocs[1][2] == 11, "④ 저장된 책갈피 = 검토 표(수동 쪽 반영)", f"{tocs[:2]}")
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
chk(bd.edit_toc_pages.text() == "2-3", "⑤ [자동 탐지] → '2-3'(관대한 탐지·표기)", f"'{bd.edit_toc_pages.text()}'")
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
          "candidates": cands, "offset": 3, "toc_pages": [2, 3]}
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
