# -*- coding: utf-8 -*-
"""260913-1: 본문과 텍스트 창이 같은 줄·낱말을 쓰는가 (입력 장치 SOT §2.8).

사용자 보고: **"스캔본의 경우 텍스트 창의 본문 위치 인식이 잘 되지만(2단에서도),
PDF 본문의 OCR 결과의 위치는 정확하지 않다."**

자리가 틀린 것이 아니라 **줄을 묶고 늘어놓는 방식**이 달랐다. 이 검사는 두 창의
줄이 **같은 목록인지**를 견주고, 우리 OCR 을 언제 쓰고 언제 쓰지 않는지를 고정한다.
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

import fitz
from PyQt6.QtWidgets import QApplication
from viewer import text_extract2 as tx

app = QApplication.instance() or QApplication(sys.argv)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = tempfile.mkdtemp(prefix="polypdf_src_")
try:
    # 2단 쪽 — 좌우 단이 y 로는 뒤섞이지만 읽는 차례는 좌측 단이 먼저다
    two = os.path.join(root, "two.pdf")
    doc = fitz.open()
    pg = doc.new_page(width=595, height=760)
    for i in range(6):
        pg.insert_text((60, 120 + i * 26), "left column line %d" % (i + 1), fontsize=11)
        pg.insert_text((330, 120 + i * 26), "right column line %d" % (i + 1), fontsize=11)
    doc.save(two)
    doc.close()

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1200, 800); mw.show(); app.processEvents()
    mw._load_main(HistoryItem(two, 0, "", "bookmark")); app.processEvents()
    m = mw.main_view

    # ── ① 본문 줄 = 텍스트 창 줄 ──────────────────────────────────────
    tx.set_table_cache_db(None); tx.close_cache()
    rows = tx.page_lines(m._doc.doc, two, 0, tables="off", join_lines=False)
    p0 = m._doc.doc.load_page(0)
    pw, ph = p0.rect.width, p0.rect.height
    want = []
    for r in rows:
        for rc in (r.get("rects") or ([r["rect"]] if r.get("rect") else [])):
            want.append((rc[0] / pw, rc[1] / ph, rc[2] / pw, rc[3] / ph))
    got = m._hl_lines()
    chk(got == want, "① 본문 줄 목록이 텍스트 창과 **똑같다**",
        "%d개 vs %d개" % (len(got), len(want)))

    # ── ② 2단은 좌측 단을 끝까지 먼저 ─────────────────────────────────
    xs = [round(l[0], 3) for l in got[:6]]
    chk(len(set(xs)) == 1, "② 2단에서 앞 6줄이 **한 단**에 모여 있다", str(xs))
    raw = []
    for b in p0.get_text("dict").get("blocks", []):
        for ln in b.get("lines", []):
            if "".join(sp.get("text", "") for sp in ln.get("spans", [])).strip():
                raw.append(round(ln["bbox"][0] / pw, 3))
    chk(len(set(raw[:6])) > 1,
        "② (전제) 날것 `get_text` 는 좌·우가 번갈아 나온다", str(raw[:6]))

    # ── ③ 쪽마다 한 번만 뽑는다 ───────────────────────────────────────
    c1 = m._view_src_cache
    m._hl_lines()
    chk(m._view_src_cache is c1, "③ 같은 쪽에서는 다시 뽑지 않는다")

    # ── ④ 우리 OCR 을 **언제** 쓰나 ───────────────────────────────────
    #   글자층이 멀쩡하고 다시 읽힌 적이 없으면 → 쓰지 않는다
    #   study.db 에 것이 **있더라도** 막는지 보아야 문지기가 된다
    _real_words = mw._ocr_page_words
    mw._ocr_page_words = lambda path, page: [
        dict(surface="잡음", x0=1, y0=1, x1=9, y1=9)]
    mw._ocr_page_dpi = lambda *a, **k: 72
    mw._text_force_ocr = set()
    ws, dpi = mw._view_ocr_words(two, 0)
    chk(not ws, "④ study.db 에 있어도 **멀쩡한 글자층**은 갈아 끼우지 않는다",
        str(len(ws)))
    mw._ocr_page_words = _real_words

    #   사용자가 그 쪽을 다시 읽혔다면 → 쓴다
    mw._text_force_ocr = {(str(two), 0)}
    called = {"n": 0}
    real = mw._ocr_page_words

    def fake(path, page):
        called["n"] += 1
        return [dict(surface="X", x0=10, y0=10, x1=20, y1=20)]

    mw._ocr_page_words = fake
    mw._ocr_page_dpi = lambda *a, **k: 72
    ws2, _d = mw._view_ocr_words(two, 0)
    chk(bool(ws2) and called["n"] == 1,
        "④ 다시 읽힌 쪽이면 우리 OCR 을 쓴다", "%s / %d" % (bool(ws2), called["n"]))
    mw._ocr_page_words = real
    mw._text_force_ocr = set()

    # ── ⑤ 한글 낱말 묶기 — 우리 OCR 에만 ──────────────────────────────
    ko = [dict(surface=c, x0=10 + i * 10.5, y0=10, x1=20 + i * 10.5, y1=22)
          for i, c in enumerate("심리검사")]
    merged = tx.merge_words_by_gap(ko)
    chk(len(merged) == 1 and merged[0]["surface"] == "심리검사",
        "⑤ 글자 하나씩 온 한글을 한 낱말로 묶는다", str([w["surface"] for w in merged]))

    far = [dict(surface="가", x0=10, y0=10, x1=20, y1=22),
           dict(surface="나", x0=50, y0=10, x1=60, y1=22)]
    chk(len(tx.merge_words_by_gap(far)) == 2,
        "⑤ 멀리 떨어진 것은 묶지 않는다")

    other = [dict(surface="가", x0=10, y0=10, x1=20, y1=22),
             dict(surface="나", x0=10, y0=40, x1=20, y1=52)]
    chk(len(tx.merge_words_by_gap(other)) == 2, "⑤ 다른 줄끼리는 묶지 않는다")

    #   PDF 글자층의 낱말은 이미 낱말이라 **묶지 않는다** — 본문이 그렇게 쓰는지 본다
    m._load_page_words()
    heads = [w[4] for w in m._page_words[:3]]
    chk(all(" " not in h for h in heads) and any(h == "left" for h in heads),
        "⑤ 글자층 낱말은 붙이지 않는다(영문이 통째로 붙으면 안 된다)", str(heads))

    # ── ⑥ 못 뽑으면 종전 길로 물러선다 ────────────────────────────────
    import viewer.widgets.main_view as mvmod
    real_pl = tx.page_lines
    try:
        tx.page_lines = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        m._view_src_cache = None
        back = m._hl_lines()
        ok = (len(back) >= 6 and all(
            isinstance(r, tuple) and len(r) == 4
            and 0.0 <= r[0] < r[2] <= 1.0 and 0.0 <= r[1] < r[3] <= 1.0
            for r in back))
        chk(ok, "⑥ 실패하면 **쓸 수 있는 줄**로 물러선다(빈 값·땜음이 아니라)",
            str(back[:2]))
    finally:
        tx.page_lines = real_pl
        m._view_src_cache = None
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("=== ALL PASS ===" if not fails else "=== FAILURE (%d) ===" % len(fails))
for f in fails:
    print(" -", f)
sys.stdout.flush()
os._exit(1 if fails else 0)
