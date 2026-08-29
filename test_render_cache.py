# -*- coding: utf-8 -*-
"""전역 렌더 캐시 + 메모리 해제(§19.11 P-A/B/C) 오프스크린 회귀 테스트."""
import os
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setApplicationName("PolyPDF")
app.setOrganizationName("LocalTools")

from test_fixtures import scanned_pdf, text_pdf  # noqa: E402
from viewer.pdf_doc import GLOBAL_PAGE_CACHE, PdfDocument  # noqa: E402

FAIL = 0


def check(name, cond, detail=""):
    global FAIL
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAIL += 1


pdf = text_pdf()

# ── 1) render_scaled 캐시 적중 — 같은 페이지·배율 재요청은 항목이 늘지 않는다 ──
GLOBAL_PAGE_CACHE.clear()
doc = PdfDocument(str(pdf))
rp0 = doc.render_scaled(0, 1.2345)
n1 = len(GLOBAL_PAGE_CACHE._items)
rp0b = doc.render_scaled(0, 1.2345)
n2 = len(GLOBAL_PAGE_CACHE._items)
check("캐시 적중(같은 키 재요청)", n1 == 1 and n2 == 1 and rp0b is rp0)

# ── 2) 픽셀 동일성 — 적중 결과는 최초 렌더와 바이트 동일 ─────────────────
check("픽셀 동일성", rp0.samples == rp0b.samples and rp0.width == rp0b.width)

# ── 3) 배율 정수화 — 1e-4 이내 지터는 같은 키 ───────────────────────────
doc.render_scaled(0, 1.23454)          # round(12345.4)=12345 → 같은 키
check("배율 정수화(지터 흡수)", len(GLOBAL_PAGE_CACHE._items) == 1)
doc.render_scaled(0, 2.0)
check("다른 배율은 다른 키", len(GLOBAL_PAGE_CACHE._items) == 2)

# ── 4) 전역 예산 — 상한 초과 시 LRU 회수 ────────────────────────────────
GLOBAL_PAGE_CACHE.clear()
old_max = GLOBAL_PAGE_CACHE._max
GLOBAL_PAGE_CACHE._max = 2 * 1024 * 1024          # 2MB 로 조여서 회수 유도
for p in range(8):
    doc.render_scaled(p, 1.5)
check("전역 예산 준수", GLOBAL_PAGE_CACHE._cur <= GLOBAL_PAGE_CACHE._max,
      f"cur={GLOBAL_PAGE_CACHE._cur} max={GLOBAL_PAGE_CACHE._max}")
check("LRU 회수 동작", len(GLOBAL_PAGE_CACHE._items) < 8)
GLOBAL_PAGE_CACHE._max = old_max
GLOBAL_PAGE_CACHE.clear()

# ── 5) 문서 간 키 분리(전역 공유 안전) + mtime 태그 ──────────────────────
doc2 = PdfDocument(str(scanned_pdf()))
doc.render_scaled(0, 1.5)
doc2.render_scaled(0, 1.5)
check("문서 간 키 분리", len(GLOBAL_PAGE_CACHE._items) == 2)
tmp = os.path.join(os.path.dirname(str(pdf)), "_mtime_copy.pdf")
shutil.copy2(str(pdf), tmp)
da = PdfDocument(tmp)
tag_a = da._cache_tag
da.close()
time.sleep(0.05)
os.utime(tmp, None)                                # mtime 변경 = 파일 갱신 시뮬
db = PdfDocument(tmp)
check("mtime 변경 → 캐시 태그 변경", db._cache_tag != tag_a)
db.close()
os.remove(tmp)

# ── 6) 메인 뷰어 통합 — 페이지 왕복 시 재렌더 없음 ───────────────────────
from viewer.app import MainWindow  # noqa: E402

mw = MainWindow()
mw._skip_save_on_close = True
mv = mw._mv[0]
GLOBAL_PAGE_CACHE.clear()
mv.load_document(str(pdf))
app.processEvents()
mv.go_to_page(1); app.processEvents()
n_after_two = len(GLOBAL_PAGE_CACHE._items)
mv.go_to_page(0); app.processEvents()              # 왕복 — 캐시 적중이어야 함
check("뷰어 페이지 왕복 = 캐시 적중", len(GLOBAL_PAGE_CACHE._items) == n_after_two,
      f"items={len(GLOBAL_PAGE_CACHE._items)}")
check("캐시 실사용(적중 0 회귀 방지)", n_after_two >= 2 and GLOBAL_PAGE_CACHE._cur > 0)

# 2쪽 보기 경로 — 캐시를 비우고 확인(높이 제약 뷰포트에선 단일 페이지와 배율이
# 일치해 적중=무증가가 정상이므로, 비운 뒤 '캐시에 들어가는가'를 본다)
GLOBAL_PAGE_CACHE.clear()
mv._fit_mode = mv.FIT_PAGE_TWO
mv._render_current(); app.processEvents()
check("2쪽 보기 캐시 경유", len(GLOBAL_PAGE_CACHE._items) >= 2,
      f"items={len(GLOBAL_PAGE_CACHE._items)}")
mv._fit_mode = mv.FIT_PAGE
mv._render_current(); app.processEvents()

# ── 7) P-C: 자발 해제 + 타이머 배선 ─────────────────────────────────────
check("해제 전 캐시 있음", GLOBAL_PAGE_CACHE._cur > 0)
mw._release_render_memory()
check("자발 해제 → 캐시 0", GLOBAL_PAGE_CACHE._cur == 0 and not GLOBAL_PAGE_CACHE._items)
t = mw._idle_release_timer
check("유휴 해제 타이머 배선", t.isSingleShot() and t.interval() == 15 * 60 * 1000
      and not t.isActive())
mv._render_current(); app.processEvents()          # 해제 후 재렌더 정상(복귀 경로)
check("해제 후 재렌더 정상", GLOBAL_PAGE_CACHE._cur > 0)

# ── 8) P-B: 그리기 이미지 b64 지연 생성 ─────────────────────────────────
from PyQt6.QtGui import QColor, QPixmap  # noqa: E402

pm = QPixmap(60, 40)
pm.fill(QColor("red"))
mv.add_image_from_pixmap(pm)
obj = mv._img_objects[-1]
check("추가 시 b64 없음(지연)", obj["data"] is None)
saved = {}
mv._img_setter = lambda f, p, out: saved.update({"out": out})
mv._save_page_images()
check("저장 시 b64 생성", bool(saved.get("out")) and bool(saved["out"][-1]["data"]))
mv._img_objects.clear()

# ── 9) P-B: _ext_docs LRU 상한 4 ────────────────────────────────────────
tl = mw.thumbs if hasattr(mw, "thumbs") else None
if tl is None:
    for attr in ("thumbs_list", "_thumbs", "thumb_panel"):
        tl = getattr(mw, attr, None)
        if tl is not None:
            break
if tl is None or not hasattr(tl, "_ext_doc"):
    from viewer.widgets.thumbs_list import PageThumbs
    tl = PageThumbs()
srcs = []
for i in range(6):
    p = os.path.join(os.path.dirname(str(pdf)), f"_ext_{i}.pdf")
    shutil.copy2(str(pdf), p)
    srcs.append(p)
    tl._ext_doc(p)
check("_ext_docs 상한 4", len(tl._ext_docs) <= 4, f"len={len(tl._ext_docs)}")
first_alive = srcs[0] in tl._ext_docs
check("가장 오래된 원본 회수", not first_alive)
for _d in list(tl._ext_docs.values()):
    try:
        if _d:
            _d.close()
    except Exception:
        pass
for p in srcs:
    try:
        os.remove(p)
    except Exception:
        pass

print()
print("결과:", "ALL PASS" if FAIL == 0 else f"FAIL {FAIL}건")
sys.stdout.flush()
os._exit(0 if FAIL == 0 else 1)
