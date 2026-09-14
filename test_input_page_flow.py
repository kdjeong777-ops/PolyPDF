# -*- coding: utf-8 -*-
"""260914-1: 쪽 넘김 애니메이션 · 이어 보기 (입력 장치 SOT §2.9·§2.10).

사용자 지시: "1페이지씩 이동 시 위/아래 페이지가 부드럽게 넘어가는 액션을 넣을 수 있도록 해.
페이지를 위아래로 조금씩 이동(스크롤)할 수 있도록 선택할 수 있도록 해. 이 경우 위의 페이지와
아래 페이지 중간에 있을 때 텍스트 창에 문제없는지 검토해."

실제 MainView 에 실제 PDF(30쪽)를 열고, 실제 경로(휠 이벤트·스크롤 막대·누름 이벤트)로 잰다.
"""
import os, sys, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent
app = QApplication.instance() or QApplication([])

from viewer.widgets.main_view import MainView
from test_fixtures import text_pdf

PDF = text_pdf()


def pump(ms=0):
    end = time.perf_counter() + ms / 1000.0
    app.processEvents()
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def make(mode="page", anim=True, fit=MainView.FIT_PAGE, page=5):
    m = MainView()
    m.resize(900, 800)
    m.show()
    pump()
    m.set_page_flip_anim(anim)
    m.set_page_scroll_mode(mode)
    m.load_document(PDF, page)
    m.cmb_fit.setCurrentText(fit)
    pump()
    m._pages = []
    m.pageChanged.connect(m._pages.append)
    return m


# ── ① 설정은 저장 허용목록·환경설정에 있다 ─────────────────────────────────
import inspect
from viewer import app as app_mod
src_save = inspect.getsource(app_mod)
for key in ("page_flip_anim", "page_scroll_mode"):
    chk(src_save.count('"%s"' % key) >= 3, "① %s 가 기본값·불러오기·허용목록에 있다" % key)
from viewer.widgets import settings_dialog as sd_mod
sd_src = inspect.getsource(sd_mod)
chk('"page_flip_anim"' in sd_src and '"page_scroll_mode"' in sd_src,
    "① 환경설정 창이 두 값을 돌려준다")

# ── ② 한 쪽씩: 넘김 애니메이션이 두 장을 밀어 그리고 끝나면 사라진다 ──────────
m = make("page", anim=True)
slide = m._page_slide
m._on_page_step(+1)
chk(m.current_page() == 6, "② 쪽은 **곧바로** 바뀐다(애니메이션은 겉모습)", str(m.current_page()))
chk(slide.isVisible() and slide._old is not None and slide._new is not None,
    "② 넘기면 애니메이션이 뜬다(두 장을 떴다)")
chk(slide._dir == 1, "② 앞으로 넘기면 위로 민다", str(slide._dir))
chk(slide.geometry() == m._view_area_rect(), "② 본문 자리에 정확히 얹힌다")
chk(slide.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents),
    "② 도는 동안 입력은 새 쪽에 그대로 간다(마우스 통과)")
diff = slide._old.toImage() != slide._new.toImage()
chk(diff, "② 떠 둔 두 장이 실제로 다르다(앞 쪽 / 새 쪽)")
pump(slide.DURATION_MS * 0.4)
mid = slide.progress()
chk(0.0 < mid < 1.0 and slide.isVisible(), "② 중간에는 밀리는 중이다", "%.2f" % mid)
pump(slide.DURATION_MS + 150)
chk(not slide.isVisible() and slide._old is None, "② 끝나면 사라지고 그림을 놓는다")

m._on_page_step(-1)
chk(slide.isVisible() and slide._dir == -1, "② 뒤로 넘기면 아래로 민다", str(slide._dir))
m._on_page_step(-1)                                   # 도는 중에 또
chk(m.current_page() == 4 and slide.isVisible(), "② 도는 중에 또 넘기면 새로 시작한다",
    str(m.current_page()))
pump(slide.DURATION_MS + 150)
m._on_page_step(+10 ** 6)                             # End
chk(not slide.isVisible(), "② End(쪽 단위가 아닌 점프)에는 애니메이션이 없다")
m.go_to_page(3)
chk(not slide.isVisible(), "② 책갈피·검색 같은 가기에는 애니메이션이 없다")

m2 = make("page", anim=False)
m2._on_page_step(+1)
chk(not m2._page_slide.isVisible() and m2.current_page() == 6, "② 끄면 뜨지 않고 쪽만 바뀐다")

# ── ③ 이어 보기: 옆 쪽이 위아래에 붙는다 ───────────────────────────────────
c = make("continuous", anim=True)
sb = c.view.verticalScrollBar()
items = [it for it in c.scene.items() if it.__class__.__name__ == "QGraphicsPixmapItem"]
chk(len(items) == 3, "③ 지금 쪽 + 이전 + 다음 = 세 장", str(len(items)))
rect = c.scene.sceneRect()
chk(rect.top() < 0 and rect.bottom() > c._cont_cur_h, "③ 위에 이전 쪽, 아래에 다음 쪽",
    "%.0f..%.0f / cur_h %.0f" % (rect.top(), rect.bottom(), c._cont_cur_h))
chk(c._page_item.pos().y() == 0 and c._page_item.pos().x() == 0,
    "③ 지금 쪽은 원점 그대로(기존 좌표를 쓰는 기능이 흔들리지 않는다)")
chk(sb.value() == 0, "③ 처음엔 지금 쪽 맨 위", str(sb.value()))
c._on_page_step(+1)
chk(not c._page_slide.isVisible(), "③ 이어 보기에서는 넘김 애니메이션을 하지 않는다")
c.go_to_page(5)
pump()
c._pages.clear()

# ── ④ 조금씩 스크롤해 가운데가 넘어가면 지금 쪽이 바뀌고 보이는 자리는 그대로 ──
vp_h = c.view.viewport().height()
gap, hyst = c.CONT_GAP_PX, c.CONT_HYST_PX
edge_v = int(c._cont_cur_h + gap / 2.0 + hyst - vp_h / 2.0)
sb.setValue(edge_v - 4)                                # 되돌이 여유 안쪽
pump(30)
chk(c.current_page() == 5, "④ 되돌이 여유 안에서는 지금 쪽이 그대로다", str(c.current_page()))
before_img = c.view.viewport().grab().toImage()
sb.setValue(edge_v + 10)                               # 넘어섰다
shown_before = c.view.mapToScene(QPoint(0, 0)).y() - c._cont_cur_h - gap   # 다음 쪽 기준 위치
pump(30)
chk(c.current_page() == 6, "④ 가운데가 다음 쪽으로 넘어가면 지금 쪽이 다음 쪽", str(c.current_page()))
shown_after = c.view.mapToScene(QPoint(0, 0)).y()
chk(abs(shown_after - shown_before) <= 1.0, "④ 다시 붙여도 보이는 자리는 그대로다",
    "%.1f → %.1f" % (shown_before, shown_after))
chk(c.spin_page.value() == 7, "④ 쪽 번호 칸도 따라간다", str(c.spin_page.value()))
chk(c._pages == [], "④ pageChanged 는 **바로 보내지 않는다**(텍스트 창을 흔들지 않게)", str(c._pages))
# 반대로 조금 되돌려도(여유 안) 그대로
sb.setValue(sb.value() - hyst)
pump(30)
chk(c.current_page() == 6, "④ 경계에서 조금 흔들어도 오락가락하지 않는다", str(c.current_page()))
pump(c.CONT_SETTLE_MS + 150)
chk(c._pages == [6], "④ 멈추고 나서 **한 번** 알린다", str(c._pages))

# 여러 쪽을 휠로 훑어 지나가도 pageChanged 는 멈춘 쪽 하나
c._pages.clear()
from PyQt6.QtGui import QWheelEvent
for i in range(60):
    ev = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(0, 0), QPoint(0, -120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    c.view.wheelEvent(ev)
    pump(5)
passed = c.current_page()
chk(passed >= 8, "④ 휠로 조금씩 굴려 여러 쪽을 지나간다", "p=%d" % passed)
pump(c.CONT_SETTLE_MS + 150)
chk(c._pages == [passed], "④ 훑어 지나간 쪽마다가 아니라 멈춘 쪽 하나만 알린다", str(c._pages))

# 위로도
c._pages.clear()
c.go_to_page(10)
pump()
c._pages.clear()
sb.setValue(int(-gap / 2.0 - hyst - vp_h / 2.0) - 10)
pump(30)
chk(c.current_page() == 9, "④ 위로 넘어가면 이전 쪽이 지금 쪽", str(c.current_page()))
top_y = c.view.mapToScene(QPoint(0, 0)).y()
chk(0 < top_y < c._cont_cur_h, "④ 새 지금 쪽(이전 쪽)의 아래쪽을 보고 있다(맨 위로 튀지 않는다)",
    "화면 위끝 y=%.0f / 쪽 높이 %.0f" % (top_y, c._cont_cur_h))

# ── ⑤ 옆 쪽을 누르면 그 쪽이 지금 쪽 ───────────────────────────────────────
c.go_to_page(12)
pump()
sb.setValue(int(c._cont_cur_h - vp_h / 2.0))          # 화면 아래 절반에 다음 쪽이 보인다
pump(30)
chk(c.current_page() == 12, "⑤ (준비) 아직 지금 쪽은 12", str(c.current_page()))
y_next = int(vp_h * 0.9)
press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(300, y_next), QPointF(300, y_next),
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
before = c.view.mapToScene(QPoint(300, y_next)).y() - c._cont_cur_h - gap
app.sendEvent(c.view.viewport(), press)
rel = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(300, y_next), QPointF(300, y_next),
                  Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                  Qt.KeyboardModifier.NoModifier)
app.sendEvent(c.view.viewport(), rel)
pump(30)
chk(c.current_page() == 13, "⑤ 다음 쪽 부분을 누르면 그 쪽이 지금 쪽", str(c.current_page()))
after = c.view.mapToScene(QPoint(300, y_next)).y()
chk(abs(after - before) <= 1.0, "⑤ 누른 자리는 그 쪽 좌표로 그대로 이어진다",
    "%.1f → %.1f" % (before, after))

# ── ⑥ 뒤로 가면 **지금 쪽의** 아래끝 (막대의 끝이 아니라) ─────────────────────
c.cmb_fit.setCurrentText(MainView.FIT_WIDTH)          # 폭 맞춤 — 쪽이 화면보다 길다
pump()
c.go_to_page(8)
c._on_page_step(-1)
lo, hi = c._page_span()
chk(c.current_page() == 7 and sb.value() == hi and hi < sb.maximum(),
    "⑥ 이전 쪽의 아래끝(다음 쪽 끝이 아니다)", "v=%d span=%d..%d max=%d"
    % (sb.value(), lo, hi, sb.maximum()))
chk(c._page_span() != (sb.minimum(), sb.maximum()), "⑥ 이어 보기의 쪽 범위는 막대 범위와 다르다")

# ── ⑦ 2쪽 보기는 한 쪽씩, 끄면 옆 쪽이 사라진다 ─────────────────────────────
c.cmb_fit.setCurrentText(MainView.FIT_PAGE_TWO)
pump()
chk(c.scene.sceneRect().top() == 0 and not c._cont_next, "⑦ 2쪽 보기에는 옆 쪽을 붙이지 않는다")
c.cmb_fit.setCurrentText(MainView.FIT_PAGE)
pump()
chk(c._cont_next, "⑦ 쪽 맞춤으로 돌아오면 다시 붙인다")
c.set_page_scroll_mode("page")
pump()
chk(c.scene.sceneRect().top() == 0 and not c._cont_next and c._page_span() ==
    (sb.minimum(), sb.maximum()), "⑦ 한 쪽씩으로 바꾸면 옆 쪽이 사라지고 범위도 막대와 같다")

# ── ⑧ 응답성 — 이어 보기에서 지금 쪽이 바뀌는 데 드는 시간 ─────────────────
c.set_page_scroll_mode("continuous")
c.go_to_page(15)
pump()
t0 = time.perf_counter()
c._cont_reanchor(16, c._cont_cur_h + gap)
dt_ms = (time.perf_counter() - t0) * 1000.0
chk(dt_ms < 1000.0, "⑧ 지금 쪽 다시 붙이기 < 1초(응답성 SOT)", "%.1f ms" % dt_ms)
print("   (실측) 다시 붙이기 %.1f ms" % dt_ms)

print()
print("=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for f in fails:
    print(" -", f)
sys.stdout.flush()
os._exit(0 if not fails else 1)
