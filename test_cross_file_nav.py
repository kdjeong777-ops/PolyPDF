"""260609-2: 페이지 경계 파일 이동(B5) 테스트 (offscreen)."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication
from viewer.app import MainWindow

PDF = r"C:\Claude\MPDF\24 아스팔트콘크리트포장시공지침.pdf"
app = QApplication.instance() or QApplication(sys.argv)
mw = MainWindow(); mw.resize(1100, 800); mw.show(); app.processEvents()

fails = []
def chk(c, m):
    print(("PASS" if c else "FAIL"), "-", m)
    if not c: fails.append(m)

mv = mw._mv[0]
mv.load_document(PDF); app.processEvents()
pc = mv._doc.page_count

# 1) 경계 신호 발생 확인
got = []
mv.fileBoundaryRequested.connect(lambda d: got.append(d))

mv.go_to_page(5)              # 중간
got.clear(); mv._on_page_step(+1)
chk(got == [] and mv._current_page == 6, "중간에서 다음 → 일반 이동(경계 신호 없음)")

mv.go_to_page(pc - 1)        # 마지막
got.clear(); mv._on_page_step(+1)
chk(got == [+1], "마지막 페이지에서 다음 → fileBoundaryRequested(+1)")

mv.go_to_page(0)             # 첫
got.clear(); mv._on_page_step(-1)
chk(got == [-1], "첫 페이지에서 이전 → fileBoundaryRequested(-1)")

# 버튼(‹ ›) 경계도 동일
mv.go_to_page(pc - 1)
got.clear(); mv._on_step_clicked(+1)
chk(got == [+1], "마지막에서 › 버튼 → 경계(+1)")
mv.go_to_page(0)
got.clear(); mv._on_step_clicked(-1)
chk(got == [-1], "첫에서 ‹ 버튼 → 경계(-1)")

# 2) _on_file_boundary: 다음/이전 파일 로드
FILES = [r"C:\x\A.pdf", PDF, r"C:\x\C.pdf"]   # 현재=가운데(PDF)
mw.bookmark_tree.ordered_pdf_files = lambda: FILES
calls = []
mw._on_bookmark_activated = lambda f, p: calls.append((f, p))
mw._prefs["cross_file_nav"] = True
mw._active_pane = 0

calls.clear(); mw._on_file_boundary(+1, 0)
chk(calls == [(r"C:\x\C.pdf", 0)], "다음 경계 → 다음 파일 첫 페이지(page 0)")

calls.clear(); mw._on_file_boundary(-1, 0)
chk(calls and calls[0][0] == r"C:\x\A.pdf" and calls[0][1] >= 10**6,
    "이전 경계 → 이전 파일 마지막 페이지(큰 인덱스 클램프)")

# 설정 OFF면 동작 안 함
mw._prefs["cross_file_nav"] = False
calls.clear(); mw._on_file_boundary(+1, 0)
chk(calls == [], "설정 OFF → 파일 이동 안 함")

# 비활성 pane이면 무시
mw._prefs["cross_file_nav"] = True
calls.clear(); mw._on_file_boundary(+1, 1)   # active=0
chk(calls == [], "비활성 pane → 무시")

# 경계 밖(첫 파일에서 이전 없음)
mw.bookmark_tree.ordered_pdf_files = lambda: [PDF]
calls.clear(); mw._on_file_boundary(-1, 0)
chk(calls == [], "이전 파일 없음 → 동작 안 함")

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
mw.close()
