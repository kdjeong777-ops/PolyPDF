# -*- coding: utf-8 -*-
"""261014-24: 썸네일 메모리 (마스터 §19.11 P-B, 개선 로드맵 P3-6).

실제 썸네일 패널(`PageThumbs`)에 400쪽 문서를 열고 스크롤바로 끝까지 내리며:
A. 썸네일 렌더는 전역 렌더 캐시(`GLOBAL_PAGE_CACHE`)에 들어가지 않는다 — 본문 렌더를 밀어내지 않는다
B. 그린 아이콘 수에 상한이 있다(`ICON_KEEP_MAX` 근처) — 화면 밖 아이콘은 비운다
C. 맨 위로 돌아오면 비웠던 아이콘을 다시 그린다
D. 셀 높이는 그대로 — 비워도 스크롤 범위가 같다
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "", flush=True)
    if not cond:
        fails.append(msg)


def settle(w, n=400):
    """렌더 타이머가 멈출 때까지 이벤트 처리(시간으로 끊긴 틱을 모두 돌린다)."""
    for _ in range(n):
        app.processEvents()
        if not w._render_timer.isActive():
            app.processEvents()
            if not w._render_timer.isActive():
                return
        w._render_visible()


root = Path(tempfile.mkdtemp(prefix="polypdf_thumbmem_test_"))
try:
    src = root / "Many.pdf"
    d = fitz.open()
    for i in range(400):
        d.new_page().insert_text((72, 100), f"Page {i + 1}", fontsize=20)
    d.save(str(src)); d.close()

    from viewer.pdf_doc import GLOBAL_PAGE_CACHE
    from viewer.widgets.thumbs_list import PageThumbs
    GLOBAL_PAGE_CACHE.clear()
    w = PageThumbs(); w.resize(220, 700); w.show(); app.processEvents()
    w.load_document(src); settle(w)
    sb = w.list.verticalScrollBar()
    top_max = sb.maximum()
    peak = len(w._iconed)
    # 스크롤 단위가 항목일 수도 픽셀일 수도 — 반 화면씩 내린다
    per_item = w.list.verticalScrollMode() == w.list.ScrollMode.ScrollPerItem
    step = 2 if per_item else max(1, w.list.viewport().height() // 2)
    v = 0
    while v < sb.maximum():
        v = min(sb.maximum(), v + step)
        sb.setValue(v); settle(w)
        peak = max(peak, len(w._iconed))
    last_icon = not w.list.item(w.list.count() - 1).icon().isNull()
    tags = {k.file_path for k in GLOBAL_PAGE_CACHE._items}
    chk(not any(str(src) in str(t) for t in tags) and GLOBAL_PAGE_CACHE._cur == 0,
        "A 썸네일은 전역 렌더 캐시에 넣지 않는다", f"{len(GLOBAL_PAGE_CACHE._items)} 개, {GLOBAL_PAGE_CACHE._cur} B")
    chk(last_icon and peak <= PageThumbs.ICON_KEEP_MAX + 60,
        "B 끝까지 내려도 그린 아이콘 수에 상한", f"peak={peak} max={PageThumbs.ICON_KEEP_MAX} last={last_icon}")
    chk(peak > PageThumbs.ICON_KEEP_MAX - 20, "B' 검사가 상한 근처까지 실제로 그렸다(헛 통과 막기)", f"peak={peak}")
    first_dropped = w.list.item(0).icon().isNull()
    sb.setValue(0); settle(w)
    chk(first_dropped and not w.list.item(0).icon().isNull(), "C 맨 위는 비웠다가 돌아오면 다시 그린다",
        f"{first_dropped}")
    chk(sb.maximum() == top_max or abs(sb.maximum() - top_max) < 50, "D 비워도 스크롤 범위가 같다",
        f"{top_max} → {sb.maximum()}")
    w.clear_document()
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
