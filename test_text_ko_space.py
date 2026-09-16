# -*- coding: utf-8 -*-
"""260916-1: OCR 한글 띄어쓰기와 줄 잇기 (텍스트 창 SOT §3.6.11·§3.6.12·§3.7.9·§3.7.10).

사용자 보고(성격심리.pdf): **단어 중간에 띄어쓰기가 있다** — `건전한 성 격 은건전한
정신 활 동 과`. 그리고 **문단 안에서 줄이 나뉜 채로 있다**.

세 군데가 겹쳐 있었다.

  ① `_by_column` 이 낱말을 줄 조각으로 묶어 놓고 **단이 하나일 때는 되돌리지 않았다**
     (§3.6.11). 그래서 조각 사이에 끼워 둔 빈칸이 그대로 나가, §3.6.2 의 간격 규칙이
     아예 돌지 못했다. 보통의 책 쪽이 전부 이 길로 간다.
  ② 한글 붙임 문턱 `0.45` 가 **문서마다 맞지 않았다**(§3.6.12) — 정답(`image_to_string`)
     으로 9,980곳을 재 보니 성격심리·심리검사 0.33 / 아스팔트지침 0.50 이상.
     이제 쪽마다 빈틈 분포의 골짜기에서 뽑는다.
  ③ §3.7 ⑥ 이 줄 사이 거리를 **글자 크기**로 쟀는데, `size` 가 글자층에서는 글꼴
     크기지만 OCR 에서는 잉크 높이라 1.3~1.4배 작다(§3.7.9). 그래서 성격심리는 본문
     줄이 하나도 문턱을 넘지 못해 문단이 통째로 끊겼다.
  ④ 이어 붙일 때 한글끼리는 **무조건 붙였다**(§3.7.7 의 한계) — 정렬된 한글 책은 줄이
     늘 꽉 차 보이기 때문이다. 이제 말뭉치에 묻는다(§3.7.10, 70.5% → 95.6%).

검사 대상
  ① 단이 하나인 쪽에서도 낱말이 되돌아온다 — 글자 사이에 빈칸이 끼지 않는다
  ② 쪽마다 문턱을 뽑고, 그 값이 정해 둔 범위 안이다
  ③ 표본이 적으면 뽑지 않는다(기본값)
  ④ 문턱이 좁은 문서·넓은 문서 둘 다 원문대로 띄어쓴다
  ⑤ 줄 사이 거리는 **그 쪽의 보통 줄 거리**로 잰다 — 잉크 높이로 재면 문단이 끊긴다
  ⑥ 성긴 쪽(발표자료·서식)은 종전 크기 기준으로 되돌아간다(§3.7.5 함정 3)
  ⑦ 한글끼리 이을 때 — 어절 경계는 띄우고 낱말 가운데는 붙인다
  ⑧ kiwi 를 못 쓰면 기하 규칙으로 물러선다
  ⑨ 본문(검색·단어장)도 **같은 글**이 된다(§3.6.2 가 요구하는 것)
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
from viewer import text_extract2 as tx

fails = []


def chk(ok, what, got=""):
    print(("PASS - " if ok else "FAIL - ") + what + (" " + str(got) if got else ""))
    if not ok:
        fails.append(what)


root = tempfile.mkdtemp(prefix="ko_space_")


def words(lines, *, x0=60.0, y0=100.0, em=10.0, h=10.0, pitch=26.0,
          inner=0.15, outer=0.60):
    """어절 목록 → **글자마다 하나씩**인 OCR 낱말 상자 (Tesseract 가 내놓는 모양).

    `inner`·`outer` 는 글자 사이 / 어절 사이 빈틈을 글자 높이에 대한 비로 준다.
    """
    out = []
    y = y0
    for ws in lines:
        x = x0
        for wi, w in enumerate(ws):
            if wi:
                x += h * outer
            for ci, ch in enumerate(w):
                if ci:
                    x += h * inner
                out.append({"surface": ch, "x0": x, "y0": y,
                            "x1": x + em, "y1": y + h, "conf": 0.95})
                x += em
        y += pitch
    return out


def blank_page(path, w=595.0, hgt=842.0):
    doc = fitz.open()
    doc.new_page(width=w, height=hgt)
    doc.save(str(path))
    doc.close()
    d = fitz.open(str(path))
    return d, d.load_page(0)


try:
    pdf = os.path.join(root, "blank.pdf")
    doc, page = blank_page(pdf)

    # ── ① 단이 하나인 쪽에서도 낱말이 되돌아온다 ─────────────────────
    LINES = [["건전한", "성격은", "건전한", "정신", "활동과", "건전한", "신체"],
             ["활동에서", "비롯된다.", "이", "책을", "공부하는", "모든", "사람이"],
             ["건전한", "정신", "및", "신체", "활동을", "통해", "건전한", "성격"],
             ["으로", "삶을", "영위할", "수", "있기를", "기원해", "본다."]]
    ws = words(LINES)
    rows = tx.lines_from_words(ws, dpi=0, page=page)
    got = [r["text"].rstrip() for r in rows]
    chk(all("성 격" not in t and "활 동" not in t for t in got),
        "① 글자 사이에 빈칸이 끼지 않는다", str(got[:1]))
    chk(got and got[0] == "건전한 성격은 건전한 정신 활동과 건전한 신체",
        "① 어절 사이에는 빈칸이 그대로 있다", repr(got[0] if got else None))

    # 되돌리기가 빠지면(§3.6.11 의 결함) 어떻게 되는지 — 조각에 빈칸이 박혀 나온다
    cols = tx._by_column([((0, 0, 0, 0), [
        ((w["x0"], w["y0"], w["x1"], w["y1"]), w["surface"], 10.0) for w in ws])],
        page, word_level=True)
    chk(all(len(f[1]) <= 2 for g in cols for f in g),
        "① `_by_column` 이 낱말 단위로 되돌려 준다",
        str(sorted({len(f[1]) for g in cols for f in g})))

    # ── ② 쪽마다 문턱을 뽑는다 ──────────────────────────────────────
    frags = [((w["x0"], w["y0"], w["x1"], w["y1"]), w["surface"], 10.0) for w in ws]
    thr = tx.cjk_gap_threshold(frags)
    chk(thr is not None and tx.CJK_GLUE_MIN <= thr <= tx.CJK_GLUE_MAX,
        "② 뽑은 문턱이 정해 둔 범위 안이다", thr)
    chk(thr is not None and 0.15 < thr < 0.60,
        "② 글자 사이(0.15)와 어절 사이(0.60) 사이에 있다", thr)

    # ── ③ 표본이 적으면 뽑지 않는다 ─────────────────────────────────
    chk(tx.cjk_gap_threshold(frags[:6]) is None,
        "③ 표본이 적으면 None — 부르는 쪽이 기본값을 쓴다")

    # ── ④ 문턱이 다른 두 문서를 둘 다 맞힌다 ────────────────────────
    for inner, outer, tag in ((0.10, 0.38, "좁은 문서"), (0.22, 0.85, "넓은 문서")):
        w2 = words(LINES, inner=inner, outer=outer)
        r2 = tx.lines_from_words(w2, dpi=0, page=page)
        chk(r2 and r2[0]["text"].rstrip() == "건전한 성격은 건전한 정신 활동과 건전한 신체",
            "④ %s 도 원문대로 띄어쓴다" % tag,
            repr(r2[0]["text"].rstrip() if r2 else None))
    # 종전 고정 0.45 로는 '넓은 문서' 의 글자 사이(0.22)가 붙고 '좁은 문서' 의
    # 어절 사이(0.38)가 붙어 버린다 — 그래서 쪽마다 뽑는 것이다.
    w3 = words(LINES, inner=0.10, outer=0.38)
    f3 = [((w["x0"], w["y0"], w["x1"], w["y1"]), w["surface"], 10.0) for w in w3]
    old = tx._merge_rows(f3)                      # 고정 기준(글자층 길)
    chk(old and "건전한성격은" in old[0][1],
        "④ 고정 0.45 였다면 어절이 붙었다(그래서 바꿨다)", repr(old[0][1][:20]))

    # ── ⑤ 줄 사이 거리는 그 쪽의 보통 줄 거리로 ─────────────────────
    rows = tx.lines_from_words(words(LINES), dpi=0, page=page)
    med = tx._median_pitch([r for r in rows if r.get("rect")])
    chk(24.0 <= med <= 28.0, "⑤ 그 쪽의 보통 줄 거리를 잰다", med)
    #   pitch 26 ÷ 잉크 높이 10 = 2.6 — 종전 기준(2.2)이면 하나도 못 잇는다
    chk(26.0 > 10.0 * tx.JOIN_PITCH,
        "⑤ 잉크 높이로 재면 종전 기준을 넘어 버린다", 26.0 / 10.0)
    joined = tx.join_sentences([dict(r) for r in rows])
    chk(len(joined) < len(rows), "⑤ 그래도 문단이 이어진다",
        "%d줄 → %d줄" % (len(rows), len(joined)))

    # ── ⑥ 성긴 쪽은 종전 크기 기준으로 ─────────────────────────────
    sparse = tx.lines_from_words(words(LINES, pitch=60.0), dpi=0, page=page)
    chk(len(tx.join_sentences([dict(r) for r in sparse])) == len(sparse),
        "⑥ 성긴 쪽(발표자료·서식)은 잇지 않는다(§3.7.5 함정 3)",
        "%d줄 → %d줄" % (len(sparse),
                        len(tx.join_sentences([dict(r) for r in sparse]))))

    # ── ⑦ 한글끼리 이을 때 ─────────────────────────────────────────
    for a, b, want, tag in (
            ("정체성이 분명한 성향적", "관점을 가장", " ", "어절 경계는 띄운다"),
            ("성격에 따라취사", "선택되어야 한다.", "", "낱말 가운데는 붙인다"),
            ("건설공사 의무사", "용대상 자재이다.", "", "낱말 가운데는 붙인다(2)"),
            ("요구에 부응해서", "개정판 작업을", " ", "어절 경계는 띄운다(2)"),
    ):
        chk(tx._join_sep(a, b, wrapped=False) == want, "⑦ %s" % tag,
            "%r + %r → %r" % (a[-6:], b[:6], tx._join_sep(a, b, wrapped=False)))
    chk(tx._join_sep("보완이 이루어졌다 ", "더불어서", False) == " ",
        "⑦ 원문이 빈칸으로 끝나면 그대로 빈칸(§3.7.3 이 먼저다)")

    # ── ⑧ kiwi 를 못 쓰면 기하로 물러선다 ──────────────────────────
    keep = tx._KIWI["bad"]
    tx._KIWI["bad"] = True
    try:
        chk(tx._join_sep("정체성이 분명한 성향적", "관점을 가장", False) == "",
            "⑧ kiwi 가 없으면 한글끼리는 종전대로 붙인다")
        chk(tx._join_sep("정체성이 분명한 성향적", "관점을 가장", True) == " ",
            "⑧ kiwi 가 없어도 어절이 안 들어가서 넘어갔으면 띄운다(§3.7.7)")
    finally:
        tx._KIWI["bad"] = keep

    # ── ⑨ 본문(검색·단어장)도 같은 글 ──────────────────────────────
    from viewer.study.ocr import _join_words_by_gap
    parts = []
    for i, w in enumerate(words(LINES)):
        parts.append(dict(w))
    # 줄이 바뀌는 자리에 개행 표시를 넣는다(Tesseract 가 주는 줄 정보와 같은 자리)
    withnl, seen = [], None
    for w in parts:
        if seen is not None and w["y0"] != seen:
            withnl.append(chr(10))
        withnl.append(w)
        seen = w["y0"]
    body = _join_words_by_gap(withnl).splitlines()
    chk(body and body[0] == "건전한 성격은 건전한 정신 활동과 건전한 신체",
        "⑨ 본문도 텍스트 창과 같은 글이 된다", repr(body[0] if body else None))

    doc.close()
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
if fails:
    print("=== FAILURE (%d) ===" % len(fails))
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("=== ALL PASS ===")
