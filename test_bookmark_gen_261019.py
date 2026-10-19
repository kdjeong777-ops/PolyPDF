# -*- coding: utf-8 -*-
"""261019-1(사용자 지시) 책갈피 창·책갈피 생성 보완 — 마스터 §4.4 · 단어학습 SOT §14.21 · 응답성 SOT §4.6.

A. 이름 변경 단축키(설정 `rename_item`, 기본 F2) — 책갈피창 목록에 포커스가 있을 때만, 우클릭 항목에 키 표기
B. 책갈피 검토 표 — Del 로 선택 행 삭제(제목을 고치는 중에는 글자만), [제목 수정] 단추
C. 보류 저장소 — OCR·어휘는 [저장] 전까지 study.db 에 들어가지 않고, 읽기는 보류 결과를 먼저 본다 / 저장·버리기
D. OCR 공급자 — 저장된 OCR 이 있으면 다시 읽지 않는다
E. 십진 목차 — OCR 이 떨어뜨린 점·잘못 읽은 번호를 앞뒤 번호로 되살린다, 깊이 → 레벨
F. 번호 제목 인식 + 줄 높이 = 중앙값(키 큰 상자 하나로 본문이 제목이 되지 않게)
G. 워커 중지 → phase=cancelled + 지금까지 찾은 행
H. 작업 창 — 진행 바 누르면 열리고 [중지] 가 작업의 중지 함수를 부른다
I. 책갈피 생성은 본문 문서를 닫지 않는다 — 검토 표를 취소해도 본문·썸네일 그대로(사용자 보고 '화면이 없어졌다')
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import fitz
from PyQt6.QtCore import Qt, QStandardPaths, QEvent, QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QMessageBox, QAbstractItemView, QPushButton
from PyQt6.QtTest import QTest

QStandardPaths.setTestModeEnabled(True)
fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c:
        fails.append(m)

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

app = QApplication.instance() or QApplication(sys.argv)
root = Path(tempfile.mkdtemp(prefix="polypdf_bmgen_"))

from viewer.study import study_store as ss
ss.enable_pending(True, root / "pend" / "study_pending_test.db")

# ── C. 보류 저장소 ─────────────────────────────────────────────────────
main_db = root / "study.db"
ss.enable_pending(False)
st0 = ss.StudyStore(main_db)
st0.save_page("k", 0, "저장본", dpi=300, engine="t", source="ocr", conf=1,
              words=[{"surface": "a", "x0": 0, "y0": 0, "x1": 1, "y1": 1}], lang="kor")
st0.close()
ss.enable_pending(True)
st = ss.StudyStore(main_db)
st.save_page("k", 0, "새 글", dpi=300, engine="t", source="ocr", conf=1,
             words=[{"surface": "b", "x0": 0, "y0": 0, "x1": 1, "y1": 1}], lang="kor")
st.save_page("k", 1, "둘째", dpi=300, engine="t", source="ocr", conf=1, words=[], lang="kor")
st.clear_vocab("k"); st.save_vocab("k", [{"lemma": "x", "lang": "kor", "level": "A"}])
chk(st.get_page_text("k", 0) == "새 글" and [w["surface"] for w in st.get_page_words("k", 0)] == ["b"]
    and st.done_pages("k") == {0, 1}, "C1 보류 중에도 읽기는 보류 결과(텍스트 창·이어하기)")
import sqlite3
raw = sqlite3.connect(main_db)
chk(raw.execute("select text from ocr_page where file_key='k' and page=0").fetchone()[0] == "저장본"
    and raw.execute("select count(*) from ocr_page where file_key='k'").fetchone()[0] == 1,
    "C2 [저장] 전에는 study.db 그대로")
st.discard_pending("k")
chk(st.get_page_text("k", 0) == "저장본" and st.get_page_text("k", 1) is None and st.pending_keys() == [],
    "C3 버리기 → 저장본으로 돌아감")
st.save_page("k", 1, "둘째", dpi=300, engine="t", source="ocr", conf=1, words=[], lang="kor")
chk(st.commit_pending("k") and st.pending_keys() == [], "C4 저장 → 보류 비움")
chk(raw.execute("select count(*) from ocr_page where file_key='k'").fetchone()[0] == 2, "C5 저장 뒤 study.db 에 들어감")
raw.close(); st.close()

# ── D. OCR 공급자: 저장된 OCR 재사용 ─────────────────────────────────────
import test_fixtures as _fx
scan = Path(_fx.scanned_pdf())
from viewer.study.ocr_pages import OcrPages
dstore = ss.StudyStore(root / "study_d.db")
fk = ss.file_key_for(str(scan))
dstore.save_page(fk, 0, "1. 서론", dpi=300, engine="t", source="ocr", conf=1,
                 words=[{"surface": "1.", "x0": 100, "y0": 100, "x1": 130, "y1": 140},
                        {"surface": "서론", "x0": 150, "y0": 100, "x1": 260, "y1": 140}], lang="kor")
with OcrPages(scan, store=dstore, run_ocr=False) as op:
    ws, dpi = op.words(1)
    lines = op.lines(1)
    chk(len(ws) == 2 and dpi == 300 and op.ran == 0 and op.reused >= 1, "D1 저장된 OCR 을 쓰고 다시 읽지 않는다",
        f"ran={op.ran} reused={op.reused}")
    chk(lines and lines[0][1].replace(" ", "") == "1.서론" and abs(lines[0][0] - 24.0) < 0.1,
        "D2 줄 = 낱말 간격으로 이음, x0 는 pt", f"{lines}")
    chk(op.words(2) == ([], 0) and op.ran == 0, "D3 run_ocr=False 면 없는 쪽은 비운다(읽지 않음)")
dstore.close()

# ── E. 십진 목차 ──────────────────────────────────────────────────────
from viewer import toc_parse as T
rows = [{"title": t, "toc_page": p} for t, p in [
    ("1. 서론", 1), ("11 연구 배경", 1), ("1.2 연구 목적", 2), ("OB AS 범위", 2), ("2. 포장 일반", 4),
    ("2.1 개념", 4), ("2.1.1 개요", 4), ("212 도로시험", 5), ("21.3 변천", 11), ("QA 평가방법", 30),
    ("DAL 기능적 측면", 30), ("2.4.2 구조적 측면", 35), ("A5.1 재료 품질", 40), ("45.2 배합설계", 41)]]
chk(T.fix_decimal_numbers(rows), "E1 십진 목차로 판정")
titles = [r["title"] for r in rows]
chk(titles[1] == "1.1 연구 배경" and titles[7] == "2.1.2 도로시험" and titles[8] == "2.1.3 변천",
    "E2 떨어진 점 되살림(11→1.1, 212→2.1.2, 21.3→2.1.3)", f"{titles}")
chk(titles[3] == "범위" and titles[9] == "평가방법" and titles[10] == "기능적 측면" and titles[12] == "재료 품질",
    "E3 번호 자리 잡글자(OB AS·QA·DAL·A5.1)는 떼어 낸다", f"{titles}")
chk([T.decimal_level(t) for t in ("1. 서론", "1.1 연구", "2.1.1 개요", "참고문헌")] == [0, 1, 2, -1], "E4 깊이 → 레벨")
gap = [{"title": "2.3.4 특수", "level": 2}, {"title": "평가방법", "level": 1}, {"title": "기능적 측면", "level": 2},
       {"title": "2.4.2 구조적", "level": 2}, {"title": "참고문헌", "level": 0}]
T.fill_decimal_gaps(gap)
chk([g["title"] for g in gap] == ["2.3.4 특수", "2.4 평가방법", "2.4.1 기능적 측면", "2.4.2 구조적", "참고문헌"],
    "E5 번호 없는 행은 앞뒤 번호 사이로 채우고, 장 급(참고문헌)은 그대로", f"{[g['title'] for g in gap]}")
chk(not T._is_successor([4, 5], [45, 2]) and T._is_successor([4, 5, 1], [4, 5, 2]), "E6 '45.2' 는 4.5 다음이 아니다")

# ── F. 번호 제목 + 줄 높이 중앙값 ─────────────────────────────────────────
from viewer.study import ocr_headings as OH
def W(s, x, y, h=40):
    return {"surface": s, "x0": x, "y0": y, "x1": x + 30 * len(s), "y1": y + h}
body = [W("본문", 100, 100 + 60 * i) for i in range(30)]
tall = [W("가", 100, 2000), W("나", 200, 1990, 120), W("다", 300, 2000)]     # 키 큰 상자 하나 섞인 본문 줄
head = [W("1.1", 100, 2200), W("연구의", 200, 2200), W("배경", 400, 2200)]
lines = OH._group_lines(body + tall + head)
tall_ln = [ln for ln in lines if ln["text"].startswith("가")][0]
chk(tall_ln["h"] == 40, "F1 줄 높이 = 낱말 높이 중앙값(키 큰 상자 하나에 흔들리지 않음)", f"{tall_ln['h']}")
bms = OH._bookmarks_from_page_lines({6: lines}, use_font_auto=True)
got_t = [(b.title, b.level) for b in bms]
chk(("1.1 연구의 배경" in [t for t, _ in got_t] or any(t.startswith("1.1") for t, _ in got_t))
    and not any(t.startswith("가") for t, _ in got_t), "F2 '1.1 연구의 배경' 은 제목, 키 큰 상자 섞인 본문 줄은 아님", f"{got_t}")
chk(OH.numbered_level("1. 시료를 채취한다.", 40, 40) is None and OH.numbered_level("1. 서론", 60, 40) == 0
    and OH.numbered_level("2.1.1 개요", 40, 40) == 2, "F3 문장·본문 크기 '1.' 은 제외, 큰 '1. 서론' 은 레벨 0")

# ── G. 워커 중지 ──────────────────────────────────────────────────────
from viewer.workers import BookmarkerWorker
txt = Path(_fx.text_pdf())
got = {}
wk = BookmarkerWorker(txt, {"mode": "font", "review": True, "save_txt": False})
wk.request_cancel()
wk.finished.connect(lambda r: got.update(r)); wk.error.connect(lambda e: got.update(err=e))
wk.run()
chk(got.get("phase") == "cancelled" and "rows" in got and not got.get("err"), "G1 중지 → phase=cancelled(+찾은 행)",
    f"{got.get('phase')} {got.get('err')}")
_d = fitz.open(str(txt)); _toc_before = _d.get_toc(); _d.close()

# ── 앱 ───────────────────────────────────────────────────────────────
from viewer.app import MainWindow
import viewer.app as _appmod
from viewer.widgets import toc_review_dialog as _trd
from viewer.history import HistoryItem
mw = MainWindow(); mw.show(); app.processEvents()
pdf = root / "doc.pdf"
import shutil
shutil.copy(txt, pdf)
mw.bookmark_tree.load_pdf_files([str(pdf)]); app.processEvents()
mw._load_main(HistoryItem(str(pdf), 2, "", "bookmark")); app.processEvents(); QTest.qWait(100)
chk(mw.main_view.current_file() and Path(mw.main_view.current_file()).name == "doc.pdf", "준비: 본문에 doc.pdf")

# A. F2
chk(mw._sc_defs.get("rename_item", (None, None))[1] == "F2", "A1 단축키 설정에 '파일·책갈피 이름 변경' = F2")
chk(mw._kt("x", "rename_item").endswith("\tF2"), "A2 우클릭 항목 오른쪽 칸에 F2")
called = []
bt = mw.bookmark_tree
_orig_edit = bt._edit_item
bt._edit_item = lambda it: called.append(it)
node = bt._file_node_for_path(str(pdf))
bt.tree.setCurrentItem(node)
mw.activateWindow(); bt.tree.setFocus(); app.processEvents()
QTest.keyClick(bt.tree, Qt.Key.Key_F2); app.processEvents()
chk(len(called) == 1 and called[0] is node, "A3 책갈피창 목록에서 F2 → 지금 행 이름 변경", f"{len(called)}")
called.clear()
mw.main_view.setFocus(); app.processEvents()
QTest.keyClick(mw.main_view, Qt.Key.Key_F2); app.processEvents()
chk(not called, "A4 다른 곳(본문)에서 F2 는 아무 일도 하지 않는다")
bt._edit_item = _orig_edit

# B. 검토 표 Del · [제목 수정]
rows_b = [{"title": t, "toc_page": None, "page": p, "level": 0, "src": "font"} for t, p in
          [("가", 1), ("나", 2), ("다", 3), ("라", 4)]]
dlg = _trd.TocReviewDialog(pdf, rows_b, method="font", parent=mw)
dlg.show(); app.processEvents()
dlg.table.setCurrentCell(1, 1); dlg.table.setFocus(); app.processEvents()
QTest.keyClick(dlg.table, Qt.Key.Key_Delete); app.processEvents()
chk([dlg.table.item(i, 1).text() for i in range(dlg.table.rowCount())] == ["가", "다", "라"],
    "B1 Del → 선택 행 삭제")
chk(dlg.table.currentRow() == 1, "B2 지운 자리의 다음 행으로(이어 누를 수 있게)")
btn = [b for b in dlg.findChildren(QPushButton) if b.text() == "제목 수정"]
chk(len(btn) == 1, "B3 [제목 수정] 단추")
btn[0].click(); app.processEvents()
chk(dlg.table.state() == QAbstractItemView.State.EditingState, "B4 [제목 수정] → 제목 칸 편집 상태")
ed = QApplication.focusWidget()
QTest.keyClick(ed, Qt.Key.Key_End); QTest.keyClick(ed, Qt.Key.Key_Delete); app.processEvents()
chk(dlg.table.rowCount() == 3, "B5 고치는 중 Del 은 글자만(행은 그대로)")
dlg.reject(); dlg.close()

# H. 작업 창
stopped = []
mw.job_add("t1", "시험 작업", lambda: stopped.append(1))
press = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5), Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(mw.progress, press); app.processEvents()
jd = mw._jobs_dlg
chk(jd is not None and jd.isVisible(), "H1 진행 바를 누르면 작업 창")
sb = jd.findChild(QPushButton, "job_stop_t1") if jd else None
chk(sb is not None and sb.isEnabled(), "H2 작업마다 [중지]")
if sb:
    sb.click(); app.processEvents()
chk(stopped == [1], "H3 [중지] → 작업의 중지 함수", f"{stopped}")
mw.job_done("t1"); app.processEvents()
chk(not mw._jobs_list(), "H4 끝나면 목록에서 빠짐")
jd.close()

# I. 책갈피 생성은 본문을 닫지 않는다 — 검토 표 취소에도 본문 그대로, 확인이면 책갈피창에 '저장 안 됨'
import viewer.widgets.bookmarker_dialog as _bmd

class _FakeBm:
    def __init__(self, *a, **k):
        pass
    DialogCode = _bmd.BookmarkerDialog.DialogCode

    def exec(self):
        return self.DialogCode.Accepted

    def result_options(self):
        return {"input_pdf": str(pdf), "toc_pages": [], "review": True, "mode": "existing",
                "ocr_font_auto": False, "offset": None, "save_txt": False, "out_dir": ""}
_RealBm = _bmd.BookmarkerDialog
_bmd.BookmarkerDialog = _FakeBm
_appmod.run_in_thread = lambda w, keep=None: w.run()
_shown = []
_trd.TocReviewDialog.exec = lambda self: (_shown.append(self.table.rowCount()), self.DialogCode.Rejected)[1]
mw.action_open_bookmarker(); app.processEvents(); QTest.qWait(100)
chk(_shown == [len(_toc_before)], "I0 검토 표가 떴다(기존 책갈피 수정 경로)", f"{_shown}")
chk(mw.main_view.current_file() and Path(mw.main_view.current_file()).name == "doc.pdf"
    and mw.page_thumbs.list.count() > 0, "I1 검토 표 취소 → 본문·썸네일 그대로(파일 선택 유지)")
chk(mw._bookmarker_worker is None and not bt._dirty, "I2 취소면 책갈피창도 그대로")
_trd.TocReviewDialog.exec = lambda self: self.DialogCode.Accepted
mw.action_open_bookmarker(); app.processEvents(); QTest.qWait(100)
node = bt._file_node_for_path(str(pdf))
_d = fitz.open(str(pdf)); n_disk = len(_d.get_toc()); _d.close()
chk(node is not None and node.childCount() > 0 and bt._dirty and bt.is_edit_mode() and n_disk == len(_toc_before),
    "I3 확인 → 책갈피창에 '저장 안 됨'(편집 모드), PDF 는 그대로",
    f"children={node.childCount() if node else None} dirty={bt._dirty} edit={bt.is_edit_mode()} disk={n_disk}/{len(_toc_before)}")
chk(mw.main_view.current_file() and Path(mw.main_view.current_file()).name == "doc.pdf", "I4 본문 그대로")
_bmd.BookmarkerDialog = _RealBm

# C6. [저장] 이 그 파일의 보류 OCR 도 확정한다
st = ss.StudyStore()
for _k in st.pending_keys():            # 앞(D)에서 남긴 보류는 비운다 — 이 항목만 본다
    st.discard_pending(_k)
fk2 = ss.file_key_for(str(pdf))
st.save_page(fk2, 0, "보류 글", dpi=300, engine="t", source="ocr", conf=1, words=[], lang="kor")
st.close()
mw._pending_refresh()                     # 배경에서 센다(응답성 SOT §4 ⑤) — 끝날 때까지 기다린다
for _ in range(50):
    app.processEvents(); QTest.qWait(50)
    if mw.btn_pending.isVisibleTo(mw):
        break
chk(mw.btn_pending.isVisibleTo(mw), "C6 저장 안 한 OCR 이 있으면 상태 표시줄 단추가 보인다(배경에서 센 뒤)")
bt._op_save(str(pdf)); app.processEvents(); QTest.qWait(200)
st = ss.StudyStore()
chk(fk2 not in st.pending_keys(), "C7 책갈피창 [저장] → 그 파일의 보류 OCR 확정")
st.close()
chk(not mw.btn_pending.isVisibleTo(mw), "C8 확정 뒤 단추 숨김")
# C9. [제목 대조] 는 스캔 쪽을 저장된 OCR 글로 본다(새로 읽지 않는다, 마스터 §4.4.3 V1)
scan2 = root / "scan2.pdf"
shutil.copy(scan, scan2)
st = ss.StudyStore()
st.save_page(ss.file_key_for(str(scan2)), 2, "Chapter Alpha 본문", dpi=300, engine="t", source="ocr", conf=1,
             words=[], lang="kor")
st.close()
dv = _trd.TocReviewDialog(scan2, [{"title": "Chapter Alpha", "toc_page": None, "page": 3, "level": 0, "src": "ocr"},
                                  {"title": "Chapter Beta", "toc_page": None, "page": 4, "level": 0, "src": "ocr"}],
                          method="ocr", parent=mw)
dv._verify(); app.processEvents()
chk(dv.verify_marks() == ["ok", "ng"], "C9 제목 대조 — 저장된 OCR 이 있는 스캔 쪽은 ✓, 없는 쪽은 ✗", f"{dv.verify_marks()}")
dv.close()

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
