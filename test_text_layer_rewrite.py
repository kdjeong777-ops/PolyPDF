# -*- coding: utf-8 -*-
"""260913-6: 스캔 쪽은 우리 OCR 로 통일 · 보이지 않는 글자층 다시 쓰기 (텍스트 창 SOT §3.1·§5.1.4·§5.4).

사용자 결정: **"제안대로 우리 OCR로 통일해. 보이지않는 글자층을 다시 디자인해서 넣어"**

근거(§3.1.7): 스캔본의 원문 OCR 층은 사전 적중률 0.62~0.89, 우리 OCR 은 0.97~1.00.
**결과를 센다** — 다시 쓴 PDF 를 다시 뽑아 창과 같은 글·같은 자리인지, 화면 픽셀이 그대로인지,
두 번 반영해도 같은지, 안전하지 않은 쪽을 건드리지 않는지 실제로 확인한다.
"""
import os, sys, tempfile, shutil, inspect
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv[:1])
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


from viewer import text_extract2 as tx
from viewer import text_fix_store as tfs
from viewer import text_apply as ta

root = Path(tempfile.mkdtemp(prefix="polypdf_layer_"))
tfs._SINGLETON = tfs.TextFixStore(root / "text_fix.json")     # 사용자 설정을 건드리지 않는다
STORE = tfs._SINGLETON
W, H = 595.0, 842.0
GOOD = ["Fracture and Damage Performance", "of Asphalt Mixtures Journal",
        "Standard Terminology Relating", "to Materials for Roads"]
BAD = ["FracturcandDamagePerlbrmance", "orAsphaltMixtures Joumal",
       "StandardTe]minologyRelating", "toMatel.ialsfbrRoads"]


def scan_pdf(dst, pages=3, visible=False, rotate=0, link=False):
    """그림(글자를 그려 넣은 픽셀) 위에 **스캐너가 얹은 나쁜 OCR 층**이 있는 쪽들."""
    doc = fitz.open()
    for p in range(pages):
        page = doc.new_page(width=W, height=H)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, int(W), int(H)))
        pix.clear_with(255)
        for i in range(4):                      # 그림 속 '글자' 자리에 검은 띠
            pix.set_rect(fitz.IRect(60, 128 + i * 60, 360, 142 + i * 60), (0, 0, 0))
        page.insert_image(page.rect, pixmap=pix)
        for i, t in enumerate(BAD):
            page.insert_text((60, 142 + i * 60), "%s p%d" % (t, p + 1), fontsize=14,
                             render_mode=3)
        if visible:
            page.insert_text((60, 700), "VISIBLE STAMP", fontsize=12)
        if link:
            page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(60, 760, 200, 780),
                              "uri": "https://example.com/"})
        if rotate:
            page.set_rotation(rotate)
    doc.save(str(dst))
    doc.close()
    return dst


def our_words(p):
    """우리 OCR 낱말 — 좋은 글, 그림 속 글자 자리(pt, dpi 0)."""
    ws = []
    for i, t in enumerate(GOOD):
        x = 60.0
        for w in ("%s p%d" % (t, p + 1)).split():
            wd = 7.0 * len(w)
            ws.append({"surface": w, "x0": x, "y0": 128.0 + i * 60, "x1": x + wd,
                       "y1": 144.0 + i * 60})
            x += wd + 6.0
    return ws


def rows_for_factory(lookup, forced=()):
    def rows_for(doc, p):
        ws, dpi = tx.pick_ocr_words(doc, p, lookup, forced=(p in forced))
        return tx.page_lines(doc, doc.name, p, tables="off", join_lines=False,
                             ocr_words=ws or None, ocr_dpi=dpi)
    return rows_for


try:
    # ── ① 원천 규칙은 한 함수 ────────────────────────────────────────────
    s1 = scan_pdf(root / "scan.pdf")
    d = fitz.open(str(s1))
    look = lambda p: (our_words(p), 0)
    chk(tx.has_text_layer(d, 0) is False, "① 스캐너 OCR 층만 있는 쪽은 '쓸 만한 층 없음'")
    ws, dpi = tx.pick_ocr_words(d, 0, look)
    chk(bool(ws), "① 스캔 쪽은 **우리 OCR** 을 쓴다")
    chk(tx.pick_ocr_words(d, 0, lambda p: ([], 0)) == ([], 0), "① 우리 OCR 이 없으면 빈 것(원문 층으로)")
    d.close()
    plain = root / "plain.pdf"
    dd = fitz.open()
    pg = dd.new_page(width=W, height=H)
    for i in range(20):
        pg.insert_text((60, 80 + i * 30), "digital text layer line number %d is fine" % i, fontsize=11)
    dd.save(str(plain)); dd.close()
    d = fitz.open(str(plain))
    chk(tx.pick_ocr_words(d, 0, look) == ([], 0), "① 쓸 만한 글자층이 있으면 우리 OCR 을 쓰지 않는다")
    chk(bool(tx.pick_ocr_words(d, 0, look, forced=True)[0]), "① 그 쪽을 [OCR 다시 읽기] 했으면 우리 OCR")
    d.close()
    from viewer.app import MainWindow
    from viewer import text_word
    vsrc = inspect.getsource(MainWindow._view_ocr_words)
    rsrc = inspect.getsource(MainWindow._reload_text_panel)
    chk("pick_ocr_words" in vsrc, "① 앱의 판단도 그 함수를 거친다(_view_ocr_words)")
    chk("_view_ocr_words(cur, page)" in rsrc and "in forced else" not in rsrc,
        "① 텍스트 창은 본문과 **같은 규칙**(종전: 다시 읽힌 쪽만 우리 OCR)")
    chk("words_lookup" in inspect.getsource(text_word.export_pages_to_docx)
        and "_view_ocr_words(cur, pg)" in inspect.getsource(MainWindow._on_text_export_word),
        "① Word 저장도 같은 원천")

    # ── ② 원천이 바뀌어도 옛 고침을 겹침으로 찾는다 ────────────────────────
    d = fitz.open(str(s1))
    layer_rows = tx.page_lines(d, str(s1), 0, tables="off", join_lines=False)
    ocr_rows = rows_for_factory(look)(d, 0)
    d.close()
    chk(len(layer_rows) == 4 and len(ocr_rows) == 4, "② 준비 — 층 4줄·우리 OCR 4줄",
        "%d/%d" % (len(layer_rows), len(ocr_rows)))
    chk(tuple(layer_rows[1]["rect"]) != tuple(ocr_rows[1]["rect"]), "② 두 원천의 줄 자리는 다르다")
    STORE.set_fix(str(s1), 0, 1, "of Asphalt Mixtures. Journal FIXED p1",
                  layer_rows[1]["text"], layer_rows[1]["rect"])
    st = {}
    got = STORE.apply_to_rows(str(s1), 0, ocr_rows, stats=st)
    chk(got[1]["text"] == "of Asphalt Mixtures. Journal FIXED p1" and st["unmatched"] == 0,
        "② 층에서 한 고침이 우리 OCR 줄에 **겹침으로** 붙는다", str([r["text"] for r in got]))
    STORE.set_fix(str(s1), 0, 7, "far away", "x", (400, 600, 500, 620))
    st = {}
    STORE.apply_to_rows(str(s1), 0, ocr_rows, stats=st)
    chk(st["unmatched"] == 1, "② 겹치는 줄이 없는 고침은 **못 찾았다고 센다**(버리지 않는다)")
    STORE.set_fix(str(s1), 0, 7, None)
    chk(abs(tfs.FIX_OVERLAP - 0.6) < 1e-9, "② 겹침 문턱 0.6")

    # ── ③ 다시 쓰기 — 창과 같은 글·자리, 화면 그대로 ──────────────────────
    s2 = scan_pdf(root / "rw.pdf", pages=2, link=True)
    pix0 = fitz.open(str(s2))[0].get_pixmap(dpi=40).samples
    STORE.set_fix(str(s2), 0, 0, "Fracture and Damage | Performance FIXED p1",
                  "", ocr_rows[0]["rect"])
    tmp, stats = ta.build_layer_pdf(
        str(s2), [0, 1], rows_for=rows_for_factory(look),
        fixes_for=lambda p, rows: STORE.apply_to_rows(str(s2), p, rows),
        items_for=lambda p: STORE.get_items(str(s2), p))
    chk(bool(tmp) and stats["rewritten"] == [0, 1], "③ 두 쪽을 다시 썼다", str(stats))
    o = fitz.open(tmp)
    t0 = " ".join(o[0].get_text().split())
    chk("Fracture and Damage Performance FIXED p1" in t0, "③ 고침이 들어갔다", t0[:160])
    chk("|" not in o[0].get_text(), "③ 창의 표시 ` | ` 는 적지 않는다")
    chk(not any(b in t0 for b in ("FracturcandDamagePerlbrmance", "Joumal")),
        "③ 스캐너의 나쁜 OCR 글은 **남지 않는다**(쪽 전체를 다시 썼다)")
    chk("of Asphalt Mixtures Journal p1" in t0 and "to Materials for Roads p1" in t0,
        "③ 고치지 않은 줄도 **우리 OCR** 글로 바뀌었다")
    again = tx.page_lines(o, tmp, 1, tables="off", join_lines=False)
    want = [r["text"] for r in rows_for_factory(look)(fitz.open(str(s2)), 1)]
    chk([r["text"] for r in again] == want, "③ 다시 뽑으면 **창과 같은 줄·같은 글**",
        str([r["text"] for r in again]))
    ious = []
    for r in rows_for_factory(look)(fitz.open(str(s2)), 1):
        R = fitz.Rect(r["rect"])
        best = max(((R & fitz.Rect(a["rect"])).get_area()
                    / max(1e-6, (R | fitz.Rect(a["rect"])).get_area())) for a in again)
        ious.append(best)
    chk(min(ious) >= 0.6, "③ 적은 줄이 원래 줄 자리에 겹친다(IoU ≥ 0.6)", str(ious))
    chk(o[0].get_pixmap(dpi=40).samples == pix0, "③ 화면 픽셀은 **그대로**(보이지 않는 층만 바뀐다)")
    chk(len(o[0].get_links()) == 1, "③ 쪽 전체 지우기로 사라지는 **하이퍼링크를 되살린다**")
    chk(len(o[0].search_for("Performance")) >= 1, "③ 새 글이 검색된다")
    o.close()
    shutil.move(tmp, str(s2))

    # 두 번 반영해도 같다 — 결과는 '원천 + 고침'
    tmp2, _st2 = ta.build_layer_pdf(
        str(s2), [0, 1], rows_for=rows_for_factory(look),
        fixes_for=lambda p, rows: STORE.apply_to_rows(str(s2), p, rows))
    a1 = fitz.open(str(s2)); a2 = fitz.open(tmp2)
    chk(all(a1[i].get_text() == a2[i].get_text() for i in range(2)),
        "③ **두 번 반영해도 같은 층**이 된다")
    a1.close(); a2.close()
    os.remove(tmp2)
    # 우리 OCR 이 없어 원천이 원문 층인 쪽도 — 새 층 + 고침이 다시 같은 결과
    no_look = lambda p: ([], 0)
    tmp3, _ = ta.build_layer_pdf(
        str(s2), [0], rows_for=rows_for_factory(no_look),
        fixes_for=lambda p, rows: STORE.apply_to_rows(str(s2), p, rows))
    a3 = fitz.open(tmp3)
    chk(" ".join(a3[0].get_text().split()) == " ".join(fitz.open(str(s2))[0].get_text().split()),
        "③ 원천이 원문 층이어도(우리 OCR 없음) 반영을 되풀이하면 같은 글", a3[0].get_text()[:120])
    a3.close()
    os.remove(tmp3)

    # ── ④ 합친 줄은 원래 줄에 도로 나눠 적는다 ────────────────────────────
    parts = ta.split_to_parts("Fracture and Damage Performance of Asphalt Mixtures. Journal",
                              ["FracturcandDamagePerlbrmance", "orAsphaltMixtures. Joumal"])
    chk(parts == ["Fracture and Damage Performance", "of Asphalt Mixtures. Journal"],
        "④ 원래 글과 순서로 맞춰 줄 경계를 옮긴다", str(parts))
    # 줄 폭이 글 길이와 비례하지 않는 경우(둘째 줄이 넓다) — 폭 비율로 나누면 틀린다
    chk(ta.split_to_parts("Fracture and Damage Performance of Asphalt",
                          ["FracturcandDamagePerlbrmance", "orAsphalt"], widths=[100, 400])
        == ["Fracture and Damage Performance", "of Asphalt"],
        "④ 폭이 아니라 **글의 순서**로 경계를 찾는다")
    chk(ta.split_to_parts("가열 아스팔트 혼합물 배합설계표", ["가열아스팔트혼합몰", "배합설겨l표"])
        == ["가열 아스팔트 혼합물", "배합설계표"], "④ 한글도 경계가 제자리")
    chk(len(ta.split_to_parts("완전히 다른 글입니다", ["zzzz", "qqqq"], widths=[1, 1])) == 2,
        "④ 맞출 수 없으면 폭 비율로 나눈다")
    s3 = scan_pdf(root / "merge.pdf", pages=1)
    d = fitz.open(str(s3))
    r3 = rows_for_factory(look)(d, 0)
    d.close()
    merged = "Fracture and Damage Performance MERGED of Asphalt Mixtures Journal p1"
    STORE.set_fix(str(s3), 0, 0, merged, "", (60, 128, 300, 204), [r3[0]["rect"], r3[1]["rect"]])
    rows_m = STORE.apply_to_rows(str(s3), 0, r3)
    plan = ta.plan_layer_lines(rows_m)
    chk(len(plan) == 4 and tuple(plan[0][0]) == tuple(r3[0]["rect"])
        and tuple(plan[1][0]) == tuple(r3[1]["rect"]),
        "④ 합친 고침은 원래 두 줄 자리에 **나눠** 적는다", str(plan[:2]))
    chk(" ".join(t for _r, t in plan[:2]) == merged, "④ 나눠도 글은 빠지지 않는다")

    # ── ⑤ 안전 조건 — 어긋나면 다시 쓰지 않는다 ───────────────────────────
    sv = scan_pdf(root / "visible.pdf", pages=1, visible=True)
    d = fitz.open(str(sv))
    chk(ta.layer_rewrite_blocker(d[0], [((60, 128, 300, 144), "x")]) == "보이는 글자가 있다",
        "⑤ 보이는 글자가 섞인 쪽은 다시 쓰지 않는다")
    chk(ta.layer_rewrite_blocker(d[0], []) == "적을 줄이 없다", "⑤ 적을 줄이 없으면 지우지 않는다")
    d.close()
    sr = scan_pdf(root / "rot.pdf", pages=1, rotate=90)
    d = fitz.open(str(sr))
    chk(ta.layer_rewrite_blocker(d[0], [((60, 128, 300, 144), "x")]) == "돌린 쪽",
        "⑤ 돌린 쪽은 다시 쓰지 않는다")
    d.close()
    # 보이는 글자가 섞인 쪽 + 고침 → 줄 바꿔 끼우기로 물러선다
    dv = fitz.open(str(sv))
    rv = tx.page_lines(dv, str(sv), 0, tables="off", join_lines=False)
    dv.close()
    tgt = next(r for r in rv if "FracturcandDamagePerlbrmance" in r["text"])
    STORE.set_fix(str(sv), 0, 0, "FALLBACK FIX", tgt["text"], tgt["rect"])
    tmpv, stv = ta.build_layer_pdf(
        str(sv), [0], rows_for=rows_for_factory(look),
        fixes_for=lambda p, rows: STORE.apply_to_rows(str(sv), p, rows),
        items_for=lambda p: STORE.get_items(str(sv), p))
    ov = fitz.open(tmpv)
    tv = ov[0].get_text()
    chk(stv["fallback"] == [0] and "VISIBLE STAMP" in tv and "FALLBACK FIX" in tv,
        "⑤ 그런 쪽은 **고친 줄만** 바꿔 끼우고 보이는 글은 지키다", str(stv))
    ov.close()
    os.remove(tmpv)
    tmpp, stp = ta.build_layer_pdf(str(plain), [0], rows_for=rows_for_factory(look),
                                   fixes_for=lambda p, rows: rows)
    chk(not tmpp and stp["skipped"] == [0], "⑤ 글자층이 있는 쪽은 건드리지 않는다")

    # ── ⑥ 반영 표시 ─────────────────────────────────────────────────────
    chk(STORE.pages_to_apply(str(s3)) == [0], "⑥ 반영 전: 반영할 쪽")
    STORE.mark_applied(str(s3), [0])
    chk(STORE.pages_to_apply(str(s3)) == [] and STORE.is_applied(str(s3), 0), "⑥ 반영 뒤: 없음")
    chk(STORE.pages_with_fixes(str(s3)) == [0], "⑥ 고침은 **남는다**")
    STORE.set_fix(str(s3), 0, 3, "later edit", "", r3[3]["rect"])
    chk(STORE.pages_to_apply(str(s3)) == [0], "⑥ 반영 뒤 다시 고치면 다시 '반영할 쪽'")

    # ── ⑦ 워커 — 스캔 쪽 전체 · 중지하면 원본 그대로 ──────────────────────
    from viewer.study.study_store import StudyStore, file_key_for
    from viewer.workers import TextLayerWorker
    dbp = root / "study.db"
    s4 = scan_pdf(root / "worker.pdf", pages=3)
    sst = StudyStore(dbp)
    for p in (0, 2):                              # 우리 OCR 은 1·3쪽에만
        sst.save_page(file_key_for(str(s4)), p, "x", dpi=0, engine="t", source="ocr",
                      conf=90.0, words=our_words(p), lang="eng")
    sst.close()
    got = {}
    w = TextLayerWorker(str(s4), [], scope="all", db_path=dbp)
    w.done.connect(lambda tmp, st, t: got.update(tmp=tmp, st=st))
    w.run()
    chk(got.get("tmp") and sorted(got["st"]["rewritten"]) == [0, 2],
        "⑦ '스캔 쪽 전체' 는 우리 OCR 이 있는 쪽을 모두 다시 쓴다", str(got.get("st")))
    ow = fitz.open(got["tmp"])
    chk("Fracture and Damage Performance p3" in " ".join(ow[2].get_text().split())
        and "FracturcandDamagePerlbrmance p2" in ow[1].get_text(),
        "⑦ 우리 OCR 이 없는 쪽(고침도 없음)은 그대로")
    ow.close()
    os.remove(got["tmp"])
    before = open(str(s4), "rb").read()
    got.clear()
    w2 = TextLayerWorker(str(s4), [], scope="all", db_path=dbp)
    w2.done.connect(lambda tmp, st, t: got.update(tmp=tmp, st=st))
    w2.request_cancel()
    w2.run()
    chk(got.get("tmp") == "" and got["st"].get("cancelled"), "⑦ 중지하면 임시 파일이 없다")
    chk(open(str(s4), "rb").read() == before, "⑦ 중지해도 원본은 그대로")
    chk(not list(root.glob("*_textlayer_tmp.pdf")), "⑦ 임시 파일이 남지 않는다")

    # ── ⑧ 글꼴 — 앱이 실제로 타는 길(TextLayerWorker → build_layer_pdf → rewrite_page_layer) ──
    #    규칙은 마스터 §4.5.10(① 쓴 글자만 ② 부분집합 이름 비켜 가기). 260913-8 감사: 종전 글꼴 검사
    #    (test_text_apply_multi C)는 **앱이 더는 부르지 않는** apply_fixes_by_page 길만 봤다.
    s8 = scan_pdf(root / "font.pdf", pages=1)
    sst = StudyStore(dbp)
    sst.save_page(file_key_for(str(s8)), 0, "x", dpi=0, engine="t", source="ocr",
                  conf=90.0, words=our_words(0), lang="eng")
    sst.close()
    d = fitz.open(str(s8))
    r8 = rows_for_factory(look)(d, 0)
    d.close()
    tx.close_cache()

    def run_worker(subset_impl=None):
        """앱과 같은 워커로 '고친 쪽만' 반영해 임시 파일을 만든다. subset_impl 로 부분집합을 바꿔 끼운다."""
        orig = fitz.Document.subset_fonts
        if subset_impl is not None:
            fitz.Document.subset_fonts = subset_impl
        res = {}
        try:
            wk = TextLayerWorker(str(s8), [0], scope="fixed", db_path=dbp)
            wk.done.connect(lambda tmp, st, t: res.update(tmp=tmp, st=st))
            wk.run()
        finally:
            fitz.Document.subset_fonts = orig
        return res.get("tmp") or "", res.get("st") or {}

    STORE.set_fix(str(s8), 0, 0, "첫 반영 가나다 Fracture p1", "", r8[0]["rect"])
    full8, _ = run_worker(lambda self, *a, **k: None)
    sz_full = os.path.getsize(full8) if full8 else 0
    if full8:
        os.remove(full8)
    tmp8, st8 = run_worker()
    sz_real = os.path.getsize(tmp8) if tmp8 else 0
    chk(bool(tmp8) and st8.get("rewritten") == [0], "⑧ 준비 — 워커가 그 쪽을 다시 썼다", str(st8))
    chk(sz_real and sz_real < sz_full / 5 and sz_full - sz_real > 3_000_000,
        "⑧ 다시 쓴 층에 글꼴 **전체**가 들어가지 않는다(부분집합 없이 저장한 것과 견줌)",
        "(%s → %s B)" % (format(sz_full, ","), format(sz_real, ",")))
    shutil.move(tmp8, str(s8))
    # 같은 쪽에 **새 글자**로 다시 반영 — 한 번 저장한 krfix 는 부분집합이라 이름을 비켜 가야 한다
    NEW8 = "둘째 반영 흙쫓뷁 휘몰아쳐"
    STORE.set_fix(str(s8), 0, 1, NEW8, "", r8[1]["rect"])
    tmp8b, _st = run_worker()
    o8 = fitz.open(tmp8b) if tmp8b else None
    t8 = o8[0].get_text() if o8 else ""
    names8 = sorted(f[4] for f in o8[0].get_fonts() if f[4].startswith("krfix")) if o8 else []
    hits8 = len(o8[0].search_for("흙쫓뷁")) if o8 else 0
    if o8:
        o8.close()
        os.remove(tmp8b)
    chk(NEW8 in t8 and "첫 반영 가나다" in t8,
        "⑧ 같은 쪽에 새 글자로 **다시** 반영해도 새 글·앞의 글이 모두 추출된다", repr(t8[:120]))
    chk(hits8 == 1, "⑧ 다시 반영한 새 글자도 검색된다")
    chk("krfix2" in names8, "⑧ 부분집합이 된 krfix 는 비켜 간다(krfix2)", str(names8))
finally:
    try:
        tx.close_cache()
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
