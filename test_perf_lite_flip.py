# -*- coding: utf-8 -*-
"""261021-1·2: 가벼운 넘김(느린 컴퓨터) · 메뉴·패널 가운데 (응답성 SOT §4.7 · 디자인 SOT §2.9.3).

사용자 지시: "다른 노트북의 (최고의전력효율모드) 상태에서 2장 맞춤 보기시 잘 안넘어가고, 중간에 정지되는
경우가 있었어. 컴퓨터가 느릴경우에 대한 대응 방안을 만들어. 최소한 화면 넘김은 부드럽게 잘 넘어가야해."
"파일 등의 메뉴와 패널을 화면의 중앙에 보이게 해."

실제 MainView·MainWindow 에 실제 PDF(30쪽)를 열고 실제 넘김 경로(`_on_page_step`)로 잰다. 시험 프로필.
"""
import os, sys, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("POLYPDF_FAKE_POWER_SAVING", None)
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
QCoreApplication.setApplicationName("polypdf_test_lite_flip")

from viewer import perf_mode
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


# ── ① 판정 — 앱이 맡기 전에는 꺼짐, 시험 프로필은 자동 판정 없음, 설정·가짜 전원·실측 ──────────
perf_mode._reset_for_test()
chk(not perf_mode.is_lite(), "① 앱이 set_pref 하기 전에는 꺼짐(홀로 쓰는 MainView 는 종전대로)")
perf_mode.set_pref("auto")
chk(perf_mode.reason() == "", "① 시험 프로필에서는 전원 상태로 켜지지 않는다", perf_mode.reason())
for _ in range(perf_mode.SLOW_WINDOW):
    perf_mode.note_flip(perf_mode.SLOW_FLIP_MS * 3)
chk(not perf_mode.measured_slow(), "① 시험 프로필에서는 실측으로도 켜지지 않는다")
os.environ["POLYPDF_FAKE_POWER_SAVING"] = "1"
perf_mode._power.update(t=-1e9)
told = []
perf_mode.on_engaged(told.append)
chk(perf_mode.is_lite() and perf_mode.reason() == "efficiency", "① 절전(최고의 전력 효율)이면 켜진다", perf_mode.reason())
perf_mode.is_lite()
chk(told == ["efficiency"], "① 처음 켜질 때 **한 번만** 알린다", str(told))
perf_mode.set_pref("off")
chk(not perf_mode.is_lite(), "① 설정 '끄기' 는 절전이어도 끈다")
os.environ["POLYPDF_FAKE_POWER_SAVING"] = "0"
perf_mode._power.update(t=-1e9)
perf_mode.set_pref("auto")
perf_mode._flips.clear()
for _ in range(perf_mode.SLOW_WINDOW):
    perf_mode.note_flip(perf_mode.SLOW_FLIP_MS + 10)
chk(perf_mode.reason() == "slow", "① 넘김이 느리면(가운데 값 ≥ SLOW_FLIP_MS) 켜진다", perf_mode.reason())
perf_mode._flips.clear()
for _ in range(perf_mode.SLOW_WINDOW):
    perf_mode.note_flip(10)
chk(perf_mode.reason() == "", "① 넘김이 빠르면 auto 는 꺼짐")
perf_mode.set_pref("on")
chk(perf_mode.reason() == "on", "① 설정 '항상' 은 켠다")

# ── ② 뷰어 — 애니메이션 없음 · 잇단 넘김은 마지막만 · 멈추면 앞뒤 쪽을 미리 그린다 ─────────────
m = MainView()
m.resize(1400, 800)
m.show()
pump()
m.set_page_flip_anim(True)
m.load_document(PDF, 5)
m.cmb_fit.setCurrentIndex(m.cmb_fit.findData(MainView.FIT_PAGE_TWO))
pump(m.FLIP_HOLD_MIN_MS + 200)
pages = []
m.pageChanged.connect(pages.append)
m._on_page_step(+1)
chk(m.current_page() == 6, "② 첫 넘김은 곧바로 그린다", str(m.current_page()))
chk(not m._page_slide.isVisible(), "② 가벼운 넘김이면 넘김 애니메이션이 없다")
chk(m._flip_hold.isActive(), "② 넘긴 뒤 잠깐(_flip_hold) 들어오는 넘김은 모은다")
for _ in range(4):
    m._on_page_step(+1)                               # 사이에 이벤트를 돌리지 않는다 = 키를 누르고 있는 꼴
chk(m.current_page() == 6 and m._flip_pending == (10, False),
    "② 모으는 동안은 그리지 않고 마지막 쪽만 기억한다", "%s %s" % (m.current_page(), m._flip_pending))
pump(m.FLIP_HOLD_MIN_MS + 300)
chk(m.current_page() == 10 and m._flip_pending is None, "② 모은 넘김은 한 번에 마지막 쪽으로", str(m.current_page()))
chk(pages == [6, 10], "② 가운데 쪽(7·8·9)은 그리지도 알리지도 않는다", str(pages))
m._on_page_step(-1)                                   # 10 → 9 곧바로
m._on_page_step(-1)                                   # 모은다 → 8
chk(m._flip_pending == (8, True), "② 뒤로 모아도 '그 쪽의 아래끝' 규칙(at_bottom)은 그대로", str(m._flip_pending))
pump(m.FLIP_HOLD_MIN_MS + 300)
m.go_to_page(20)
chk(m._flip_pending is None, "② 책갈피·검색 같은 가기는 모아 둔 넘김을 버린다")
pump(m.PREFETCH_DELAY_MS + m.PREFETCH_GAP_MS * 8 + 400)
from viewer.pdf_doc import RenderKey
want = [(p, int(round(max(0.1, min(20.0, ps)) * 10000))) for p, ps in m._prefetch_targets()]
hit = [(p, q) for p, q in want if m._doc.cache.get(RenderKey(m._doc._cache_tag, p, q, False)) is not None]
chk(want and hit == want, "② 멈추면 다음·이전 넘김에 쓸 쪽이 렌더 캐시에 있다(넘기면 다시 그리지 않는다)",
    "%d/%d" % (len(hit), len(want)))
chk(sorted({p for p, _ in want}) == [19, 20, 21, 22], "② 2장 맞춤이면 넘긴 뒤 보일 두 쪽씩", str(sorted({p for p, _ in want})))
perf_mode.set_pref("off")
m._on_page_step(+1)
chk(m._page_slide.isVisible(), "② 끄면 넘김 애니메이션이 종전대로 돈다")
pump(400)

# ── ③ 앱 — 텍스트 창은 넘김이 멈춘 뒤 한 번 · 상태 표시줄 표시 · 설정 저장 ──────────────────
import inspect
from viewer import app as app_mod
src = inspect.getsource(app_mod)
chk(src.count('"lite_flip"') >= 3, "③ lite_flip 이 기본값·불러오기·허용목록에 있다")
from viewer.widgets import settings_dialog as sd_mod
chk('"lite_flip"' in inspect.getsource(sd_mod), "③ 환경설정 창이 lite_flip 을 돌려준다")

perf_mode._reset_for_test()
os.environ["POLYPDF_FAKE_POWER_SAVING"] = "1"
from viewer.app import MainWindow
mw = MainWindow()
mw._skip_save_on_close = True
mw.resize(1920, 900)
mw.show()
pump(500)
chk(perf_mode.pref() == "auto", "③ 앱이 설정값(auto)을 넣는다", perf_mode.pref())
mw.open_pdf(PDF)
pump(1500)
mw._vm_text()
pump(300)
calls = []
orig = mw._on_main_page_changed
mw._on_main_page_changed = lambda p: (calls.append(p), orig(p))
mv = mw.main_view
pump(mv.FLIP_HOLD_MIN_MS + 300)
mv._on_page_step(+1)
chk(calls == [] and mw._lite_follow.isActive(), "③ 넘긴 그 자리에서는 텍스트 창을 다시 뽑지 않는다", str(calls))
chk(mw.lite_badge.isVisible(), "③ 상태 표시줄에 '가벼운 넘김' 이 보인다")
pump(mw.LITE_FOLLOW_MS + 200)
chk(calls == [mv.current_page()], "③ 넘김이 멈추면 텍스트 창이 한 번 따라간다", str(calls))
told = []
mw.status.showMessage = lambda msg, ms=0: told.append(msg)
mw._lite_heavy_notice("OCR")
mw._lite_heavy_notice("OCR")
pump(50)
chk(len(told) == 1 and "OCR" in told[0], "③ 무거운 작업 알림은 작업마다 한 번", str(len(told)))

# ── ④ 메뉴·패널 가운데 (디자인 SOT §2.9.3) ─────────────────────────────────────────
tb = mw._panel_toolbar
bar = mw.menuBar()
for w in (1920, 1700):
    mw.resize(w, 900)
    pump(300)
    l, r = tb._span()
    c = (l + r) / 2.0
    s = mw.toolbar_search
    ok_c = abs(c - tb.width() / 2.0) <= 3 or (s.isVisible() and s.geometry().left() - r - 1 <= 16 + 3)
    chk(ok_c and tb.pad.width() > 0, "④ %dpx: 패널 묶음이 창 가운데(또는 검색창과 16px 띄운 데까지)" % w,
        "가운데 %.0f / 창 %.0f / 검색창까지 %d" % (c, tb.width() / 2.0, s.geometry().left() - r - 1))
    if s.isVisible():
        chk(s.geometry().left() - r - 1 >= 16, "④ %dpx: 검색창과 최소 16px" % w)
    rects = [bar.actionGeometry(a) for a in bar.actions() if a.isVisible()]
    mc = (min(x.left() for x in rects) + max(x.right() for x in rects)) / 2.0
    chk(abs(mc - bar.width() / 2.0) <= 3, "④ %dpx: 메뉴가 창 가운데" % w, "%.0f / %.0f" % (mc, bar.width() / 2.0))
mw.resize(1000, 900)
pump(300)
chk(tb.pad.width() == 0, "④ 좁으면 빈 칸을 없애 단추를 넘침(»)으로 밀지 않는다", str(tb.pad.width()))
chk(len(tb.groups) == 2 and [g[0].text() for g in tb.groups] == ["보기", "도구"],
    "④ 그룹 바탕은 '보기'·'도구' 두 묶음")
from viewer.widgets import center_bars
chk(center_bars.GROUP_BG[False] != center_bars.GROUP_BG[True], "④ 그룹 바탕색은 라이트·다크가 다르다")
mw.apply_theme("dark")
pump(100)
chk(tb.dark is True, "④ 다크로 바꾸면 그룹 바탕도 다크 색")

os.environ.pop("POLYPDF_FAKE_POWER_SAVING", None)
print("\n=== %s ===" % ("ALL PASS" if not fails else "FAIL %d" % len(fails)))
sys.stdout.flush()
os._exit(1 if fails else 0)
