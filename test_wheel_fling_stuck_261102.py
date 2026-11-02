# -*- coding: utf-8 -*-
"""261102-4: 관성(`ScrollMomentum`) 표식이 남아 마우스 휠로 쪽이 영영 안 넘어가던 것 — 입력 장치 SOT §2.3.

사용자 보고(1.1.0-beta.2): 책갈피를 만든 뒤 **마우스 휠**로 본문이 안 움직였다 — 키보드 넘김은 됐고, 본문을 눌러도 그대로,
프로그램을 다시 켜야 됐다. `MainView.wheelEvent` 의 `_fling`(손을 뗀 뒤의 관성) 표식은 `ScrollBegin`·`Update`·`End` 로만
지워지고 **보통 마우스 휠(`NoScrollPhase`)로는 지워지지 않았다** — 트랙패드 관성의 `ScrollEnd` 가 끊기면(관성 도중 검토 표 같은
모달 창이 뜨거나·창이 멈추거나·다른 창으로 넘어가 버려지면) 그 뒤 모든 마우스 휠이 '관성' 으로 취급돼, 쪽 맞춤에서 쪽을 넘기지
않고 반대 방향은 '관성 취소' 로 버려졌다.

실제 휠 이벤트를 뷰포트에 보내서:
  A  관성이 끊긴 채 남은 뒤에도 마우스 휠(아래)로 쪽이 넘어간다 — 수정 전 코드는 실패
  B  반대 방향(위) 마우스 휠도 넘어간다 — 수정 전 코드는 '관성 취소' 로 버려 실패
  C  진짜 관성(손 뗀 뒤 `ScrollMomentum`)으로는 종전대로 쪽을 넘기지 않는다
"""
import os, sys, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)               # 마스터 §14.7.2 의 3
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QWheelEvent
app = QApplication.instance() or QApplication([])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def pump(ms=0):
    end = time.perf_counter() + ms / 1000.0
    app.processEvents()
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


from viewer.widgets.main_view import MainView
from test_fixtures import text_pdf

m = MainView()
m.resize(900, 800)
m.show(); pump()
m.set_page_flip_anim(False)
m.load_document(text_pdf(), 5)
if m.shown_fit() != MainView.FIT_PAGE:
    m.choose_fit(MainView.FIT_PAGE)
pump(100)
vp = m.view.viewport()


def wheel(dy, phase=Qt.ScrollPhase.NoScrollPhase, n=1, gap=220):
    for _ in range(n):
        ev = QWheelEvent(QPointF(200, 200), QPointF(vp.mapToGlobal(QPoint(200, 200))), QPoint(0, 0), QPoint(0, dy),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, phase, False)
        QApplication.sendEvent(vp, ev)
        pump(gap)


# 트랙패드로 아래로 밀다 손을 뗐다 — 관성이 오는 도중 끝(`ScrollEnd`)이 끊겼다
wheel(-120, Qt.ScrollPhase.ScrollBegin, gap=10)
wheel(-120, Qt.ScrollPhase.ScrollUpdate, gap=10)
wheel(-120, Qt.ScrollPhase.ScrollMomentum, gap=10)
pump(400)
p0 = m.current_page()
wheel(-120, n=3)
chk(m.current_page() > p0, "A 관성이 끊긴 채 남아도 마우스 휠(아래)로 쪽이 넘어간다", "%d → %d" % (p0, m.current_page()))
p1 = m.current_page()
wheel(+120, n=3)
chk(m.current_page() < p1, "B 반대 방향(위) 마우스 휠도 넘어간다", "%d → %d" % (p1, m.current_page()))

# C — 진짜 관성은 종전대로 넘기지 않는다
pump(400)
wheel(-120, Qt.ScrollPhase.ScrollBegin, gap=10)
wheel(-120, Qt.ScrollPhase.ScrollUpdate, gap=10)
p2 = m.current_page()
wheel(-480, Qt.ScrollPhase.ScrollMomentum, n=6, gap=60)
chk(m.current_page() == p2, "C 손 뗀 뒤의 관성으로는 쪽을 넘기지 않는다", "%d → %d" % (p2, m.current_page()))
wheel(0, Qt.ScrollPhase.ScrollEnd, gap=10)

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
