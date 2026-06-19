# -*- coding: utf-8 -*-
"""260610: 파일 경계 이동 E2E 재현 — 모킹 없이 실제 트리/실제 이벤트로.

사용자 보고: 필터(전체/보임/꾸밈/숨김) 기능 추가 후 키보드·마우스 휠로
다른 파일 이동이 안 됨. 기존 test_cross_file_nav.py 는 ordered_pdf_files/
_on_bookmark_activated 를 모킹해 실제 경로는 검증 못 했음.
"""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
import fitz

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QWheelEvent, QKeyEvent

fails = []
def chk(c, m, extra=""):
    print(("PASS" if c else "FAIL"), "-", m, extra)
    if not c: fails.append(m)

# --- 테스트용 분할 폴더 생성: A/B/C 각 3페이지 -------------------------
tmp = Path(tempfile.mkdtemp(prefix="polypdf_e2e_"))
names = ["A.pdf", "B.pdf", "C.pdf"]
for n in names:
    d = fitz.open()
    for i in range(3):
        p = d.new_page(width=300, height=400)
        p.insert_text((50, 100), f"{n} page {i+1}")
    d.save(str(tmp / n)); d.close()
bm = {"version": 1, "bookmarks": [
    {"title": Path(n).stem, "file": n, "children": []} for n in names
]}
(tmp / "bookmarks.json").write_text(json.dumps(bm), encoding="utf-8")

app = QApplication.instance() or QApplication(sys.argv)
from viewer.app import MainWindow
mw = MainWindow(); mw.resize(1200, 800); mw.show(); app.processEvents()
mw._prefs["cross_file_nav"] = True
mw._active_pane = 0
mv = mw._mv[0]

mw.open_folder(tmp); app.processEvents()
files = mw.bookmark_tree.ordered_pdf_files()
chk(len(files) == 3, "트리 ordered_pdf_files = 3개", str(files))

# B 를 트리 활성화 경로 그대로 로드
mw._on_bookmark_activated(files[1], 0); app.processEvents()
chk(Path(mv.current_file() or "").name == "B.pdf", "B.pdf 로드", str(mv.current_file()))

def wheel(view, dy):
    """실제 휠 이벤트를 뷰포트에 전달."""
    vp = view.viewport()
    pos = QPointF(vp.width() / 2, vp.height() / 2)
    ev = QWheelEvent(pos, view.mapToGlobal(QPoint(int(pos.x()), int(pos.y()))).toPointF()
                     if hasattr(view.mapToGlobal(QPoint(0, 0)), "toPointF")
                     else QPointF(0, 0),
                     QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(vp, ev)
    app.processEvents()

# --- 1) 필터 '전체' 상태: 휠로 B 마지막 → C ---------------------------
mv.go_to_page(2); app.processEvents()
chk(mv._current_page == 2, "B 마지막 페이지(2)로 이동")
wheel(mv.view, -120)
chk(Path(mv.current_file() or "").name == "C.pdf",
    "[전체] B 마지막에서 휠다운 → C.pdf", f"now={Path(mv.current_file() or '').name} page={mv._current_page}")
chk(mv._current_page == 0, "[전체] C 첫 페이지", f"page={mv._current_page}")

# --- 2) 휠로 C 첫 → B 마지막 -------------------------------------------
wheel(mv.view, +120)
chk(Path(mv.current_file() or "").name == "B.pdf",
    "[전체] C 첫에서 휠업 → B.pdf", f"now={Path(mv.current_file() or '').name}")
chk(mv._current_page == 2, "[전체] B 마지막 페이지로", f"page={mv._current_page}")

# --- 3) 키보드(뷰 포커스): B 마지막에서 ↓ → C --------------------------
mv.view.setFocus(); app.processEvents()
kev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(mv.view, kev); app.processEvents()
chk(Path(mv.current_file() or "").name == "C.pdf",
    "[전체] 키보드 ↓ → C.pdf", f"now={Path(mv.current_file() or '').name}")

# --- 4) 필터 버튼 실제 클릭('보임') 후 휠/키보드 ------------------------
mw._on_bookmark_activated(files[1], 0); app.processEvents()   # B 다시
tp = mw.page_thumbs
tp._filter_btns["visible"].click(); app.processEvents()        # 실제 버튼 클릭
chk(tp._filter == "visible", "필터 '보임' 클릭됨")
mv.go_to_page(2); app.processEvents()
wheel(mv.view, -120)
chk(Path(mv.current_file() or "").name == "C.pdf",
    "[보임] B 마지막에서 휠다운 → C.pdf", f"now={Path(mv.current_file() or '').name}")

# 키보드: 필터 버튼 클릭 직후 포커스가 어디 있는지 + ↓ 가 동작하는지
mw._on_bookmark_activated(files[1], 0); app.processEvents()
mv.go_to_page(2); app.processEvents()
tp._filter_btns["all"].click(); app.processEvents()
fw = QApplication.focusWidget()
print("  (info) 필터 클릭 후 focusWidget =", type(fw).__name__ if fw else None)
# 실제 사용자처럼 '현재 포커스 위젯'에 키를 보냄
target = fw or mv.view
kev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(target, kev); app.processEvents()
chk(Path(mv.current_file() or "").name == "C.pdf",
    "[필터버튼 클릭 직후] 키보드 ↓ → C.pdf",
    f"now={Path(mv.current_file() or '').name} focus={type(fw).__name__ if fw else None}")

# --- 5) 썸네일 리스트 위에서 휠: 목록 끝에서 한 번 더 → 다음/이전 파일 --
mw._on_bookmark_activated(files[1], 0); app.processEvents()
mv.go_to_page(2); app.processEvents()
sb = tp.list.verticalScrollBar()
sb.setValue(sb.maximum()); app.processEvents()
wheel(tp.list, -120)
chk(Path(mv.current_file() or "").name == "C.pdf",
    "[썸네일 휠] 목록 끝에서 휠다운 → C.pdf",
    f"now={Path(mv.current_file() or '').name}")

mw._on_bookmark_activated(files[1], 0); app.processEvents()    # B 다시
sb = tp.list.verticalScrollBar(); sb.setValue(sb.minimum()); app.processEvents()
wheel(tp.list, +120)
chk(Path(mv.current_file() or "").name == "A.pdf",
    "[썸네일 휠] 목록 처음에서 휠업 → A.pdf",
    f"now={Path(mv.current_file() or '').name}")
chk(mv._current_page == 2, "[썸네일 휠] A 마지막 페이지로", f"page={mv._current_page}")

# --- 6) 썸네일 리스트 키보드: ↓ 선택이동+뷰어 동기, 끝에서 → 다음 파일 --
def key_to(w, key):
    kev = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(w, kev); app.processEvents()

mw._on_bookmark_activated(files[1], 0); app.processEvents()    # B p0
tp.list.setCurrentRow(0); app.processEvents()
key_to(tp.list, Qt.Key.Key_Down)
chk(tp.list.currentRow() == 1 and mv._current_page == 1,
    "[썸네일 키] ↓ → 선택 1 + 뷰어 p1",
    f"row={tp.list.currentRow()} page={mv._current_page}")
key_to(tp.list, Qt.Key.Key_Down)
chk(tp.list.currentRow() == 2 and mv._current_page == 2, "[썸네일 키] ↓↓ → p2")
key_to(tp.list, Qt.Key.Key_Down)
chk(Path(mv.current_file() or "").name == "C.pdf",
    "[썸네일 키] 마지막에서 ↓ → C.pdf",
    f"now={Path(mv.current_file() or '').name}")

# --- 7) 필터 '보임'에서 숨김 페이지 건너뛰는 키 이동 + 경계 --------------
mw._on_bookmark_activated(files[1], 0); app.processEvents()    # B p0
tp.set_hidden_pages({1})
tp._filter_btns["visible"].click(); app.processEvents()        # 보임 필터
tp.list.setCurrentRow(0); app.processEvents()
key_to(tp.list, Qt.Key.Key_Down)
chk(tp.list.currentRow() == 2 and mv._current_page == 2,
    "[보임 키] ↓ → 숨김(p1) 건너뛰고 p2",
    f"row={tp.list.currentRow()} page={mv._current_page}")
key_to(tp.list, Qt.Key.Key_Down)
chk(Path(mv.current_file() or "").name == "C.pdf",
    "[보임 키] 끝 보이는 항목에서 ↓ → C.pdf",
    f"now={Path(mv.current_file() or '').name}")
tp._filter_btns["all"].click(); app.processEvents()

# --- 8) 필터 버튼이 키보드 포커스를 뺏지 않는지(NoFocus) -----------------
chk(all(b.focusPolicy() == Qt.FocusPolicy.NoFocus for b in tp._filter_btns.values()),
    "필터 버튼 4개 NoFocus(포커스 탈취 방지)")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
mw.close()
sys.exit(0 if not fails else 1)
