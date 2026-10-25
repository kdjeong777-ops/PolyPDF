# -*- coding: utf-8 -*-
"""261025-11: 본문 매치 수집을 나눠서 — 검색창 SOT §8 · 응답성 SOT §4 ⑥.

정식판 점검의 오래 켜 두기 시험이 검색마다 1.1~1.9초 정지를 잡았다 — `set_query` 가 열린 문서의 모든 쪽을 메인 스레드에서
한 번에 훑었다. 이 검사는 쪽마다 찾기를 느리게 모사해(마스터 §14.7.2 의 7) 기계와 무관하게 잰다.

  A  set_query 가 바로 돌아오고, 모으는 동안 메인 정지(박동 간격) < 0.25초, 다 모으면 개수·현재 매치가 종전과 같다
  B  결과로 연 쪽(load_document(query=, page))의 첫 매치가 바로 현재 매치이고, 앞쪽 매치가 늦게 들어와도 그 자리를 지킨다
  C  모으는 중 새 검색어 → 앞 수집이 멈추고 새 검색어의 매치만 남는다 · 이미지 열기도 멈춘다
  D  모으는 중 ▶ 로 옮긴 자리는 수집이 끝나도 같은 (쪽, 차례)
  E  다 모으기 전에는 match_search_done() 이 False — 앱이 이 문서의 '마지막 매치' 로 보고 다음 파일로 넘기지 않게
"""
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QStandardPaths, QCoreApplication, QTimer
QStandardPaths.setTestModeEnabled(True)
app = QApplication.instance() or QApplication([])
QCoreApplication.setApplicationName("polypdf_search_sliced_%d" % os.getpid())

import fitz
from viewer.widgets.main_view import MainView

N = 240
HITS = {3: 2, 120: 1, 230: 1}           # 쪽 → 'needle' 개수
tmp = tempfile.mkdtemp(prefix="polypdf_sliced_")
PDF = os.path.join(tmp, "big.pdf")
d = fitz.open()
for i in range(N):
    pg = d.new_page()
    pg.insert_text((72, 72), "page %d filler text for search" % (i + 1))
    for k in range(HITS.get(i, 0)):
        pg.insert_text((72, 120 + 30 * k), "needle here")
    if i == 3:
        pg.insert_text((72, 300), "haystack")
d.save(PDF)
d.close()

# 쪽마다 찾기를 느리게 — 240쪽 × 6ms ≈ 1.4초(종전 코드는 이것을 메인에서 한 번에)
_orig = fitz.Page.search_for


def _slow(self, *a, **k):
    time.sleep(0.006)
    return _orig(self, *a, **k)


fitz.Page.search_for = _slow

beat = {"last": time.perf_counter(), "max": 0.0}


def tick():
    now = time.perf_counter()
    beat["max"] = max(beat["max"], now - beat["last"])
    beat["last"] = now


hb = QTimer()
hb.setInterval(10)
hb.timeout.connect(tick)
hb.start()


def pump_until(cond, limit=20.0):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < limit:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.002)
    return False


def total(m):
    return sum(len(h.rects) for h in m._matches)


m = MainView()
m.resize(900, 800)
m.show()
app.processEvents()
m.load_document(PDF, 0)
pump_until(lambda: False, 0.3)

# ── A ──
m.go_to_page(50)
app.processEvents()
beat["last"] = time.perf_counter(); beat["max"] = 0.0
t0 = time.perf_counter()
m.set_query("needle")
call = time.perf_counter() - t0
chk(call < 0.25, "A set_query 가 바로 돌아온다", "%.3fs" % call)
done = pump_until(lambda: m.match_search_done())
tick()
chk(done, "A 결국 다 모은다")
chk(beat["max"] < 0.25, "A 모으는 동안 메인 정지 < 0.25초", "최장 %.3fs" % beat["max"])
chk(total(m) == sum(HITS.values()), "A 개수가 문서 전체", "%d" % total(m))
chk(m._current_match == 0 and m._match_anchor() == (3, 0), "A 현재 매치는 종전처럼 문서의 첫 매치", repr(m._match_anchor()))

# ── B ──
m.load_document(PDF, 120, query="needle")
chk(m._match_anchor() == (120, 0), "B 결과로 연 쪽의 첫 매치가 바로 현재 매치", repr(m._match_anchor()))
pump_until(lambda: m.match_search_done())
chk(m._match_anchor() == (120, 0) and m._current_match == 2, "B 앞쪽 매치(3쪽 둘)가 들어와도 같은 자리", "%r %d" % (m._match_anchor(), m._current_match))

# ── C ──
m.set_query("needle")
app.processEvents()
m.set_query("haystack")
pump_until(lambda: m.match_search_done())
chk([h.page_index for h in m._matches] == [3], "C 새 검색어 → 앞 수집은 멈추고 새 것만", repr([h.page_index for h in m._matches]))
m.set_query("needle")
gen = m._search_gen
m.load_image(os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icon.png"))
pump_until(lambda: False, 0.5)
chk(m._search_gen != gen and not m._matches and m.match_search_done(), "C 이미지 열기도 앞 수집을 멈춘다")

# ── D·E ──
m.load_document(PDF, 0)
m.go_to_page(200)
m.set_query("needle")
chk(not m.match_search_done(), "E 다 모으기 전에는 match_search_done() 이 False")
pump_until(lambda: any(h.page_index == 120 for h in m._matches) or m.match_search_done())
if not m.match_search_done():
    m.go_next_match()
    moved = m._match_anchor()
    pump_until(lambda: m.match_search_done())
    chk(m._match_anchor() == moved, "D 모으는 중 ▶ 로 옮긴 자리를 지킨다", "%r → %r" % (moved, m._match_anchor()))
else:
    chk(False, "D 모으는 중에 ▶ 를 눌러 볼 수 있어야 한다(너무 빨리 끝남)")

fitz.Page.search_for = _orig
print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(0 if not fails else 1)
