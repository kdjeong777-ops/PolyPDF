"""260609-4 (D, Phase 1): 발표 전체화면 핵심 테스트 (offscreen)."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication
from viewer.widgets.presentation import PresentationWindow

PDF = r"C:\Claude\MPDF\24 아스팔트콘크리트포장시공지침.pdf"
app = QApplication.instance() or QApplication(sys.argv)

fails = []
def chk(c, m):
    print(("PASS" if c else "FAIL"), "-", m)
    if not c: fails.append(m)

def key(w, k, text=""):
    e = QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier, text)
    w.keyPressEvent(e)

w = PresentationWindow(PDF, 10)
w.resize(1280, 800)
w.show_presentation(); app.processEvents()
pc = w._doc.page_count
chk(w._page == 10, "시작 페이지 설정")
chk(w._label.pixmap() is not None and not w._label.pixmap().isNull(), "페이지 렌더됨")

key(w, Qt.Key.Key_Right);  chk(w._page == 11, "→ 다음 페이지")
key(w, Qt.Key.Key_Left);   chk(w._page == 10, "← 이전 페이지")
key(w, Qt.Key.Key_Space);  chk(w._page == 11, "Space 다음")
key(w, Qt.Key.Key_Home);   chk(w._page == 0, "Home 첫 페이지")
key(w, Qt.Key.Key_End);    chk(w._page == pc - 1, "End 마지막")

# 경계 클램프
key(w, Qt.Key.Key_Right);  chk(w._page == pc - 1, "마지막에서 다음 → 클램프(멈춤)")
key(w, Qt.Key.Key_Home)

# 숫자패드 입력 후 Enter
for d in (Qt.Key.Key_2, Qt.Key.Key_5):
    key(w, d, chr(d))
chk(w._numbuf == "25", "숫자 입력 버퍼")
key(w, Qt.Key.Key_Return)
chk(w._page == 24 and w._numbuf == "", "Enter → 25페이지(0-based 24)로 이동")

# 좌클릭(중앙/우측) → 다음  (좌측 10%는 D6에서 '이전')
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtCore import QPointF
w.resize(1000, 700)
def _click(win, x, y):
    win.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    win.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
before = w._page
_click(w, 600, 400)   # 260609-16: 이동은 release 에서
chk(w._page == before + 1, "좌클릭(중앙) → 다음 페이지")

# ESC 닫기 + closed 시그널(현재 페이지 전달)
got = []
w.closed.connect(lambda pg: got.append(pg))
cur = w._page
key(w, Qt.Key.Key_Escape); app.processEvents()
chk(got == [cur], f"ESC 닫기 + closed(현재페이지={cur})")

# ===== Phase 2: 사용자 포인터 =====
w2 = PresentationWindow(PDF, 0, pointers=[
    {"name": "빨강", "fill": "#ff0000", "border": "#ffffff"},
    {"name": "파랑", "fill": "#0000ff", "border": "#ffffff"},
    {"name": "흰색", "fill": "#ffffff", "border": "#000000"},
], pointer_active=1)
w2.resize(1000, 700); w2.show_presentation(); app.processEvents()
chk(w2._ptr_active == 1, "활성 포인터 인덱스 적용")
cur_shape_before = w2.cursor().shape()
chk(not w2._ptr_hidden, "초기 포인터 보임")
# 커서 픽스맵 생성(색 반영)
qc = w2._make_pointer_cursor(w2._pointers[0])
chk(not qc.pixmap().isNull(), "포인터 커서 픽스맵 생성")
# 2초 무동작 → 숨김
w2._hide_pointer()
chk(w2._ptr_hidden and w2.cursor().shape() == Qt.CursorShape.BlankCursor,
    "무동작 → 포인터 숨김(Blank)")
# 마우스 이동 → 복귀
from PyQt6.QtGui import QMouseEvent as _ME
mv = _ME(QEvent.Type.MouseMove, QPointF(50, 50),
         Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
         Qt.KeyboardModifier.NoModifier)
w2.mouseMoveEvent(mv)
chk(not w2._ptr_hidden, "이동 → 포인터 복귀")
# 프리셋 전환
pc_got = []
w2.pointerChanged.connect(lambda i: pc_got.append(i))
w2.set_pointers(None, 2)
chk(w2._ptr_active == 2, "set_pointers 활성 전환")
w2.close()

# 포인터 설정 다이얼로그 왕복
from viewer.widgets.pointer_settings_dialog import PointerSettingsDialog
dlg = PointerSettingsDialog([
    {"name": "A", "fill": "#112233", "border": "#445566"},
    {"name": "B", "fill": "#778899", "border": "#aabbcc"},
    {"name": "C", "fill": "#ddeeff", "border": "#000000"},
])
res = dlg.result_pointers()
chk(len(res) == 3 and res[0]["name"] == "A" and res[0]["fill"].lower() == "#112233",
    "포인터 설정 다이얼로그 결과 보존")

# ===== Phase 3: 상하 2분할 =====
w3 = PresentationWindow(PDF, 5, split_mode=True, overlap_pct=10)
w3.resize(1280, 720); w3.show_presentation(); app.processEvents()
chk(w3._split_mode and w3._split_half == 0, "분할 모드 시작 = 상부")
chk(w3._label.pixmap() is not None and not w3._label.pixmap().isNull(), "분할 렌더됨")
# 상부 → 하부(같은 페이지)
key(w3, Qt.Key.Key_Right)
chk(w3._page == 5 and w3._split_half == 1, "다음 → 같은 페이지 하부")
# 하부 → 다음 페이지 상부
key(w3, Qt.Key.Key_Right)
chk(w3._page == 6 and w3._split_half == 0, "다음 → 다음 페이지 상부")
# 이전 → 같은 페이지 하부? 현재 상부이므로 이전 페이지 하부
key(w3, Qt.Key.Key_Left)
chk(w3._page == 5 and w3._split_half == 1, "이전(상부) → 이전 페이지 하부")
# 이전 → 같은 페이지 상부
key(w3, Qt.Key.Key_Left)
chk(w3._page == 5 and w3._split_half == 0, "이전(하부) → 같은 페이지 상부")
# 'S'로 분할 해제
sc = []
w3.splitModeChanged.connect(lambda b: sc.append(b))
key(w3, Qt.Key.Key_S)
chk(not w3._split_mode and sc == [False], "S 키 → 분할 해제 + 시그널")
# 다시 켜기
key(w3, Qt.Key.Key_S)
chk(w3._split_mode and sc == [False, True], "S 키 → 분할 재설정")
# 숫자 점프는 상부로
key(w3, Qt.Key.Key_2, "2"); key(w3, Qt.Key.Key_0, "0"); key(w3, Qt.Key.Key_Return)
chk(w3._page == 19 and w3._split_half == 0, "분할 중 페이지 점프 → 상부")
w3.close()

# ===== Phase 4: 파일 경계 50% 오버레이 =====
# 형제 파일 리졸버: A(현재)→B(다음). 단순화: 두 경로를 같은 PDF로.
PDF_B = PDF   # 동일 PDF를 형제로 사용(경로만 다르게 시뮬레이션 어려우니 실제로 같은 파일)
def resolver(cur, direction):
    # 현재가 PDF면 다음=가짜경로 'NEXT', 이전=None
    if direction > 0:
        return PDF_B
    return None

w4 = PresentationWindow(PDF, 0, sibling_resolver=resolver)
w4.resize(1200, 800); w4.show_presentation(); app.processEvents()
last = w4._doc.page_count - 1
w4._go(last)                          # 마지막 페이지
chk(w4._armed == 0, "마지막 페이지(무장 전)")
key(w4, Qt.Key.Key_Right)             # 다음 → 경계 무장(오버레이)
chk(w4._armed == 1 and w4._armed_path == PDF_B, "마지막에서 다음 → 다음파일 경계 무장")
chk(w4._label.pixmap() is not None and not w4._label.pixmap().isNull(), "오버레이 렌더됨")
key(w4, Qt.Key.Key_Right)             # 다시 다음 → 실제 전환(첫 페이지)
chk(w4._armed == 0 and w4._page == 0, "재선택 → 다음 파일 첫 페이지로 전환")
# 무장 중 ESC → 취소(닫지 않음)
w4._go(last); key(w4, Qt.Key.Key_Right)
chk(w4._armed == 1, "재무장")
key(w4, Qt.Key.Key_Escape)
chk(w4._armed == 0 and w4.isVisible(), "무장 중 ESC → 취소(창 유지)")
# 이전 파일 없음 → 첫 페이지에서 이전은 무장 안 됨
w4._go(0); key(w4, Qt.Key.Key_Left)
chk(w4._armed == 0, "이전 파일 없으면 무장 안 함")
w4.close()

# ===== Phase 5: 상단 호버 띠 =====
hl_data = {0: [{"name": "영상", "kind": "url", "target": "https://youtu.be/x"},
               {"name": "자료", "kind": "file", "target": "a.pdf"}]}
def hl_resolver(path, page0):
    return hl_data.get(page0, [])

# 시작은 링크 없는 페이지(10) — D7 자동표시 영향 배제
w5 = PresentationWindow(PDF, 10, hyperlink_resolver=hl_resolver)
w5.resize(1280, 800); w5.show_presentation(); app.processEvents()
chk(not w5._topbar.isVisible(), "상단 띠 초기 숨김(링크 없는 페이지)")
# 상단으로 마우스 이동 → 표시
from PyQt6.QtGui import QMouseEvent as _ME2
from PyQt6.QtCore import QPointF as _PF
mv_top = _ME2(QEvent.Type.MouseMove, _PF(600, 5),
              Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
              Qt.KeyboardModifier.NoModifier)
w5.mouseMoveEvent(mv_top); app.processEvents()
chk(w5._topbar.isVisible(), "상단 근처 → 띠 표시")
chk(w5._tb_page.count() == w5._doc.page_count, "페이지 콤보 채워짐")
chk(len(w5._hl_buttons) == 0, "링크 없는 페이지 → 버튼 0")
# 링크 있는 페이지(0)로 → 버튼 2개
w5._go(0); app.processEvents()
chk(len(w5._hl_buttons) == 2, "페이지0 하이퍼링크 버튼 2개")
got_hl = []
w5.hyperlinkActivated.connect(lambda l: got_hl.append(l))
w5._hl_buttons[0].click()
chk(got_hl and got_hl[0]["name"] == "영상", "띠 하이퍼링크 클릭 → hyperlinkActivated")
# 아래로 이동 → 숨김(단, 링크 페이지는 자동표시되므로 링크 없는 페이지로 이동 후 확인)
w5._go(11); w5._autohide_timer.stop()   # 260609-16(F1): 자동표시 기간 종료 가정
mv_bot = _ME2(QEvent.Type.MouseMove, _PF(600, 600),
              Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
              Qt.KeyboardModifier.NoModifier)
w5.mouseMoveEvent(mv_bot); app.processEvents()
chk(not w5._topbar.isVisible(), "아래로 이동(링크 없는 페이지) → 띠 숨김")
# 띠의 다음 버튼 → 페이지 이동
w5._show_topbar()
p_before = w5._page
w5._tb_next.click()
chk(w5._page == p_before + 1, "띠 ❯ 버튼 → 다음 페이지")
w5.close()

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
