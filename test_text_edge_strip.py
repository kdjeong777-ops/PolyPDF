# -*- coding: utf-8 -*-
"""260913-2·260913-4: 세로 띠·머리말·꼬리말 거르기 (텍스트 창 SOT §3.5.2).

사용자 지시: **"세로 띠, 상단부 머리말, 하단부 꼬리말 등은 텍스트 창에서 제외하도록 해."**

**버리는 것보다 안 버리는 것이 어렵다.** 처음 규칙은 단의 마지막 줄과 표 칸까지
버렸다. 그래서 이 검사는 *버려야 할 것을 버리는지* 와 *본문을 지키는지* 를 같은
무게로 본다.
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

import fitz
from viewer import text_extract2 as tx

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def frags_of(page):
    out = []
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            t = "".join(sp.get("text", "") for sp in ln.get("spans", []))
            if t.strip():
                x0, y0, x1, y1 = ln["bbox"]
                out.append(((x0, y0, x1, y1), t.strip(), 10.0))
    return out


def kept_texts(page):
    fr = frags_of(page)
    keep, n = tx.drop_edge_frags(fr, page)
    return [t for _r, t, _s in keep], n


W, H = 595.0, 842.0
root = tempfile.mkdtemp(prefix="polypdf_edge_")
try:
    # ── 세로 띠 + 머리말/꼬리말이 있는 3쪽 문서 ───────────────────────
    dst = os.path.join(root, "edge.pdf")
    doc = fitz.open()
    for pi in range(3):
        pg = doc.new_page(width=W, height=H)
        pg.insert_text((80, 40), "RUNNING HEAD SAMPLE", fontsize=9)      # 머리말
        for i in range(12):                                             # 본문
            pg.insert_text((120, 140 + i * 26),
                           "body line %d of page %d here" % (i + 1, pi), fontsize=11)
        for i in range(20):                                             # 세로 띠
            pg.insert_text((30, 150 + i * 28), "x", fontsize=7)
        pg.insert_text((250, H - 40), "Page %d of 3" % (pi + 1), fontsize=9)  # 꼬리말
    doc.save(dst)
    doc.close()

    d = fitz.open(dst)
    pg = d[1]
    texts, n = kept_texts(pg)
    joined = " ".join(texts)
    chk(n > 0, "① 무언가는 버린다", str(n))
    chk(not any(t.strip() == "x" for t in texts),
        "① **세로 띠**를 버린다", str([t for t in texts if len(t) <= 2][:6]))
    chk("RUNNING HEAD SAMPLE" not in joined, "① **머리말**을 버린다")
    chk(not any(t.startswith("Page ") for t in texts), "① **꼬리말**을 버린다",
        str([t for t in texts if t.startswith("Page")]))
    chk(sum(1 for t in texts if t.startswith("body line")) == 12,
        "① 본문 12줄은 **하나도** 잃지 않는다",
        str(sum(1 for t in texts if t.startswith("body line"))))

    # ── ② 옆 쪽을 못 보면 버리지 않는다(한 쪽짜리) ────────────────────
    one = os.path.join(root, "one.pdf")
    doc = fitz.open()
    pg = doc.new_page(width=W, height=H)
    pg.insert_text((80, 40), "RUNNING HEAD SAMPLE", fontsize=9)
    for i in range(12):
        pg.insert_text((120, 140 + i * 26), "body line %d" % (i + 1), fontsize=11)
    pg.insert_text((250, H - 40), "Page 1 of 1", fontsize=9)
    doc.save(one)
    doc.close()
    d1 = fitz.open(one)
    t1, _n1 = kept_texts(d1[0])
    chk("RUNNING HEAD SAMPLE" in " ".join(t1),
        "② 옆 쪽이 없으면 머리말을 **버리지 않는다** — 자리만으로 가르지 않는다")
    d1.close()

    # ── ③ 쪽 가장자리의 **표 칸**은 지킨다 ────────────────────────────
    tbl = os.path.join(root, "tbl.pdf")
    doc = fitz.open()
    for pi in range(3):
        pg = doc.new_page(width=W, height=H)
        # 왼쪽 가장자리에 좁은 칸이 세로로 늘어서지만 **x 가 제각각**이다
        # 글꼴 탓에 한글이 점으로 찍히므로 라틴으로 둔다 — 여기서 보는 것은 **자리**다
        for i, lab in enumerate(("SIZE", "13mm", "10mm", "5mm", "50", "25",
                                 "12", "6", "3", "1")):
            pg.insert_text((26 + (i % 3) * 9, 150 + i * 52), lab, fontsize=8)
        for i in range(10):
            pg.insert_text((150, 150 + i * 52), "table row %d" % i, fontsize=11)
    doc.save(tbl)
    doc.close()
    d2 = fitz.open(tbl)
    t2, _n2 = kept_texts(d2[1])
    chk("SIZE" in t2 and "13mm" in t2 and "5mm" in t2,
        "③ 가장자리의 표 칸은 **지킨다**(한 줄기가 아니다)", str(t2[:6]))
    d2.close()

    # ── ④ 문턱값이 실측대로인가 ───────────────────────────────────────
    chk(abs(tx.SIDE_SPREAD - 0.02) < 1e-9,
        "④ 한 줄기 문턱 0.02 — 진짜 띠 0.015 / 표 칸 0.024 사이", str(tx.SIDE_SPREAD))
    chk(tx.SIDE_MIN_N >= 8 and tx.SIDE_SPAN >= 0.4, "④ 개수·높이 문턱")
    chk(tx.EDGE_PEERS >= 1, "④ 옆 쪽을 적어도 하나는 본다")

    # ── ⑤ 쪽 번호는 쪽마다 달라도 '되풀이' 로 본다 ────────────────────
    chk(tx._norm_edge("- 10 -") == tx._norm_edge("- 11 -"),
        "⑤ 쪽 번호만 다른 꼬리말은 같은 것으로 본다")
    chk(tx._norm_edge("Page 2 of 10") == tx._norm_edge("Page 7 of 10"),
        "⑤ `Page N of M` 도 마찬가지")
    chk(tx._norm_edge("real body sentence") != tx._norm_edge("Page 2 of 10"),
        "⑤ 본문과 꼬리말은 다르게 본다")

    # ── ⑥ OCR 이 쪽마다 조금씩 다르게 읽은 꼬리말 (260913-4, 사용자 보고 AASHTO) ──
    #   실측 꼬리말 셋 — 같은 글인데 글자가 밀리고 빈칸이 다르다.
    noisy = ["(c)2024 by the Amerlcan Association or Statc Highwav and Transportation",
             "(c)2()24 by 1he Amcrlc@n AssociKIIion of State HIghway and Tmnsportalion",
             "(c)2024 bV thc Amer]can Assoc iati on or St@te H ighway and Transportatlon"]
    dst6 = os.path.join(root, "noisy.pdf")
    doc = fitz.open()
    for pi in range(3):
        pg = doc.new_page(width=W, height=H)
        for i in range(12):
            pg.insert_text((120, 140 + i * 26), "body line %d of page %d here" % (i + 1, pi),
                           fontsize=11)
        pg.insert_text((80, H - 60), noisy[pi], fontsize=8)
        pg.insert_text((250, H - 45), "A A S H T O" if pi == 1 else "AASHTO", fontsize=8)
    doc.save(dst6)
    doc.close()
    d6 = fitz.open(dst6)
    t6, _n6 = kept_texts(d6[1])
    chk(not any("Association" in t or "AssociKIIion" in t for t in t6),
        "⑥ OCR 이 **조금씩 다르게** 읽은 꼬리말도 되풀이로 본다", str([t for t in t6 if "by" in t]))
    chk("A A S H T O" not in t6, "⑥ 빈칸만 다른 꼬리말(`A A S H T O` / `AASHTO`)도 같다")
    chk(sum(1 for t in t6 if t.startswith("body line")) == 12, "⑥ 본문 12줄은 그대로")
    old = tx._norm_edge(noisy[1])
    chk(sum(1 for x, y in zip(old, tx._norm_edge(noisy[0])) if x == y) / len(old) < tx.EDGE_SIM,
        "⑥ (자리마다 견주던 종전 방식으로는 못 알아본다 — 원인 재현)")
    chk(not tx._looks_repeated("demanding conditions.", [tx._norm_edge(x) for x in noisy]),
        "⑥ 꼬리말과 닮지 않은 단 끝 줄은 되풀이가 아니다")

    # ── ⑦ OCR 낱말 길 — 옆 쪽 OCR 낱말로 꼬리말을 거른다 ──────────────────
    def words_of(page_texts, y_foot):
        ws = []
        for i, t in enumerate(page_texts):
            x = 120.0
            for w in t.split():
                ws.append({"surface": w, "x0": x, "y0": 140 + i * 26 - 10,
                           "x1": x + 6 * len(w), "y1": 140 + i * 26 + 2})
                x += 6 * len(w) + 5
        return ws

    blank = os.path.join(root, "blank.pdf")
    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=W, height=H)
    doc.save(blank)
    doc.close()
    db = fitz.open(blank)

    def ocr_words(pi):
        body = ["body line %d of page %d here" % (i + 1, pi) for i in range(12)]
        ws = words_of(body, 0)
        x = 80.0
        for w in noisy[pi].split():
            ws.append({"surface": w, "x0": x, "y0": H - 68, "x1": x + 5 * len(w), "y1": H - 58})
            x += 5 * len(w) + 4
        return ws

    rows_np = tx.lines_from_words(ocr_words(1), dpi=0, page=db[1])
    rows_p = tx.lines_from_words(ocr_words(1), dpi=0, page=db[1],
                                 peer_words=[(ocr_words(0), 0), (ocr_words(2), 0)])
    chk(any("Association" in r["text"] or "Assoc" in r["text"] for r in rows_np),
        "⑦ 옆 쪽 낱말이 없으면 버리지 않는다(자리만으로 가르지 않는다)")
    chk(not any("Assoc" in r["text"] for r in rows_p),
        "⑦ 옆 쪽 OCR 낱말을 주면 꼬리말을 버린다", str([r["text"] for r in rows_p][-3:]))
    chk(sum(1 for r in rows_p if "body line" in r["text"]) == 12,
        "⑦ 낱말 길에서도 본문은 그대로")
    db.close()
    d6.close()
    d.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("=== ALL PASS ===" if not fails else "=== FAILURE (%d) ===" % len(fails))
for f in fails:
    print(" -", f)
sys.stdout.flush()
os._exit(1 if fails else 0)
