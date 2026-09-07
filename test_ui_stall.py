# -*- coding: utf-8 -*-
"""260906-7: 메인 스레드의 반복문은 '시간'으로 끊는다 (응답성 SOT §4 ⑥).

설치본을 스택 표본으로 잡아 보니, 창이 '(응답 없음)' 인 순간 마지막 지점은 워커가 아니라
**메인 스레드 자신**이었다.

    Thread (active+gil): "MainThread"
        fz_load_page (mupdf.py) <- render (pdf_doc.py) <- render_thumbnail
        <- _render_visible (thumbs_list.py)
    Thread (idle): rglob (pathlib.py) <- index_folder (indexer.py)

썸네일 한 장은 `fitz` 로 쪽을 여는 C 호출이라 중간에 이벤트를 처리할 수 없고, 배경
인덱싱이 GIL 을 나눠 쓰는 동안에는 한 장의 비용이 몇 배로 늘어난다. 보이는 항목이
열 몇 개여도 반복문 하나가 메시지 펌프를 5초 넘게 막는다.

검사 대상:
  ① 예산이 개수가 아니라 시간이다(`RENDER_SLICE_MS`)
  ② 한 장이 느려도 `_render_visible` 한 번은 짧게 끝나고, 남은 것은 타이머로 넘긴다
  ③ 끝까지 렌더는 된다(예산은 미루는 것이지 버리는 것이 아니다)
  ④ 배경 목록 수집은 취소 가능해야 한다 — `index_folder` 에 rglob 금지(§7.0)
  ④-b 태그 계산도 의무 ①(한 번에 하나만)·②(GIL 양보)를 지킨다
"""
import os, sys, time, inspect, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
import test_fixtures as _fx
from viewer.widgets.thumbs_list import PageThumbs
from viewer.indexer import PdfIndex

root = Path(tempfile.mkdtemp(prefix="polypdf_stall_"))
pdf = root / "doc.pdf"
shutil.copy(Path(_fx.text_pdf()), pdf)          # 30쪽

try:
    # ── ① 예산은 시간 ────────────────────────────────────────────────────
    chk(isinstance(getattr(PageThumbs, "RENDER_SLICE_MS", None), int)
        and 5 <= PageThumbs.RENDER_SLICE_MS <= 100,
        "① 썸네일 렌더 예산이 시간(ms)으로 정해져 있다",
        f"{getattr(PageThumbs, 'RENDER_SLICE_MS', None)}ms")

    pt = PageThumbs()
    pt.resize(160, 2000)            # 아주 길게 → 보이는 항목을 많이 만든다
    pt.show()
    pt.load_document(pdf)
    app.processEvents()

    # ── ② 한 장이 느려도 한 번은 짧게 끝난다 ─────────────────────────────
    #   실제 상황(배경 인덱싱이 GIL 을 나눠 가짐)을 '한 장 20ms' 로 흉내낸다.
    for i in range(pt.list.count()):
        pt.list.item(i).setIcon(__import__("PyQt6.QtGui", fromlist=["QIcon"]).QIcon())
    _orig = pt._doc.render_thumbnail
    calls = {"n": 0}

    def _slow(page_idx, dpi=None, **kw):
        calls["n"] += 1
        time.sleep(0.020)
        return _orig(page_idx, dpi=dpi) if dpi is not None else _orig(page_idx)

    pt._doc.render_thumbnail = _slow
    pt._render_timer.stop()
    t0 = time.time()
    pt._render_visible()
    one_ms = (time.time() - t0) * 1000
    chk(one_ms < 250, "② 한 번 호출이 짧게 끝난다(메시지 펌프로 돌아간다)",
        f"{one_ms:.0f}ms · {calls['n']}장")
    chk(pt._render_timer.isActive(), "② 남은 썸네일은 타이머에 넘긴다")

    # ── ③ 끝까지 렌더된다 ────────────────────────────────────────────────
    deadline = time.time() + 30
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
        done = sum(1 for i in range(pt.list.count())
                   if not pt.list.item(i).icon().isNull())
        if done >= min(6, pt.list.count()):
            break
    chk(done >= min(6, pt.list.count()),
        "③ 미룬 것도 결국 다 그려진다", f"{done}장")
    pt._doc.render_thumbnail = _orig

    # ── ④-b 260906-8: 태그 계산도 의무 ①② 를 지킨다 ────────────────────
    #   `extract_features` 는 색인에 없는 파일에서 fitz 로 폴백해 **파일을 연다**.
    #   인덱싱·목록 조사와 겹치면 메인이 받는 GIL 조각이 반으로 준다.
    from viewer.workers import AutoTagWorker
    chk(getattr(AutoTagWorker, "YIELD_S", 0) > 0,
        "④-b 태그 계산도 파일마다 GIL 을 양보한다",
        f"{getattr(AutoTagWorker, 'YIELD_S', None)}s")
    from viewer.app import MainWindow
    mw = MainWindow(); mw._skip_save_on_close = True
    mw._prefs["auto_tag_enabled"] = True
    mw._index_workers = [object()]              # 인덱싱이 도는 중인 척
    mw._autotag_worker = None
    mw._start_autotag_scan()
    chk(mw._autotag_worker is None,
        "④-b 인덱싱 중에는 태그 계산을 시작하지 않는다(뒤로 미룬다)")
    mw._index_workers = []
    mw._probe_busy = True                       # 목록 조사가 도는 중인 척
    mw._start_autotag_scan()
    chk(mw._autotag_worker is None,
        "④-b 목록 조사 중에도 시작하지 않는다")
    mw._probe_busy = False

    # ── ④ 목록 수집은 취소 가능 ──────────────────────────────────────────
    src = inspect.getsource(PdfIndex.index_folder)
    chk(".rglob(" not in src,
        "④ index_folder 가 rglob 을 호출하지 않는다(취소 가능한 iter_pdfs)")
    chk("iter_pdfs" in src, "④ 표준 목록 수집기를 쓴다(SOT §7.0)")
    db = root / "index.db"
    ix = PdfIndex(db)
    t0 = time.time()
    ix.index_folder(root, should_cancel=lambda: True)
    cancel_ms = (time.time() - t0) * 1000
    chk(cancel_ms < 500, "④ 취소 요청이면 곧바로 돌아온다", f"{cancel_ms:.0f}ms")
    chk(ix.conn.execute("SELECT count(*) FROM files").fetchone()[0] == 0,
        "④ 취소되면 아무것도 적지 않는다")
    ix.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
