# -*- coding: utf-8 -*-
"""261101-1: OCR 결과 다듬기 — 줄 잇기·낱말 붙음·머리말·`|`→`I`·언어 좁히기 (텍스트 창 SOT §3.5.2·§3.5.3·§3.6.13·§3.7.11·§3.7.12,
단어학습 SOT §14.8.1).

사용자 보고(영문 소설 스캔본 HM): 줄마다 끊긴 문단, `mywillpower`·`lookofthat`, `| two plus two?`, `Can't say 1 like`,
본문 첫 줄로 들어온 머리말 `PROVECGCT HAIL MARY 5`. 실제 HM 으로 잰 것은 SOT 에 있고, 이 검사는 **같은 성질을 갖춘
합성 입력**으로 규칙을 고정한다(Tesseract 가 필요한 곳은 `image_to_data` 결과를 흉내 낸다).
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

import fitz
from viewer import text_extract2 as tx
from viewer import text_noise as tn
from viewer.study import ocr

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def W(s, x0, y0, x1, y1, conf=0.95):
    return {"surface": s, "x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1), "conf": conf}


def line_words(text, y, x=72.0, h=10.0, gap=2.0, cw=5.0, heights=None):
    """한 줄의 낱말 상자(pt). 낱말 사이 빈틈 `gap` — 양쪽 정렬된 소설처럼 좁다(높이의 0.2)."""
    out = []
    for i, w in enumerate(text.split()):
        hh = (heights[i % len(heights)] if heights else h)
        out.append(W(w, x, y + (h - hh), x + cw * len(w), y + h))
        x += cw * len(w) + gap
    return out


root = tempfile.mkdtemp(prefix="polypdf_ocrfix_")
try:
    # ── ① OCR 라틴 낱말은 붙이지 않는다(§3.6.13) — 빈틈이 높이의 0.2 ──────────────────
    ws = line_words("I summon all my willpower and inner strength", 100)
    rows = tx.lines_from_words(ws, dpi=0)
    t = rows[0]["text"] if rows else ""
    chk("my willpower" in t and "mywillpower" not in t, "① 줄 목록: OCR 라틴 낱말 사이는 빈칸", t)
    # 글자층 조각 길(`cjk_gap` 없음)은 종전 문턱 그대로 — 한 낱말이 두 조각으로 쪼개진 PDF
    fr = [((72, 100, 97, 110), "will", 10.0), ((97.5, 100, 122, 110), "power", 10.0)]
    chk(tx._merge_rows(fr)[0][1] == "willpower", "① 글자층 조각은 종전대로 붙인다", tx._merge_rows(fr)[0][1])
    # study.db 본문(검색·단어장)도 같은 규칙 — `image_to_data` 를 흉내 내어 실제 `ocr_image` 를 태운다
    import pytesseract
    seq = [("Can't", 3), ("say", 3), ("|", 3), ("like", 3), ("the", 3), ("look", 3), ("of", 3), ("that.", 3),
           ("Dang", 4), ("it.", 4), ("What's", 4), ("two?", 4)]
    data = {k: [] for k in ("text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num")}
    x = 100
    for s, ln in seq:
        if seq.index((s, ln)) == 8:
            x = 100
        w = 30 if s not in ("|",) else 4
        data["text"].append(s); data["left"].append(x); data["top"].append(ln * 50)
        data["width"].append(w); data["height"].append(30)
        data["conf"].append(5 if s == "What's" else 90)
        data["block_num"].append(1); data["par_num"].append(1); data["line_num"].append(ln)
        x += w + 7                                      # 빈틈 7px ÷ 높이 30 = 0.23 < 0.25(종전 문턱)
    _old = (ocr.ensure_tesseract, pytesseract.image_to_data)
    ocr.ensure_tesseract = lambda: {"ok": True}
    pytesseract.image_to_data = lambda *a, **k: data
    try:
        res = ocr.ocr_image(None, lang="eng", dpi=300)
    finally:
        ocr.ensure_tesseract, pytesseract.image_to_data = _old
    txt = res["text"]
    chk("look of that." in txt and "lookofthat" not in txt, "① study.db 본문도 OCR 라틴 낱말 사이는 빈칸", txt)
    # ── ② 문장 속 `|` → `I`, 낮은 신뢰도 사전 낱말은 남긴다(§3.5.3) ──────────────────
    chk("say I like" in txt, "② 문장 속 `|` 는 `I` 로 읽는다", txt)
    chk("What's" in txt, "② 신뢰도가 낮아도 사전 낱말(`What's`)은 남긴다", txt)
    chk(tn.keep_ocr_word("xqzvw", 0, 0, 100, 30, 0.05, scale=0.24) is False,
        "② 사전에 없는 낮은 신뢰도 낱말은 종전대로 버린다")
    chk(tn.keep_ocr_word("픔", 0, 0, 30, 30, 0.05, scale=0.24) is False, "② 한글 잡음은 살리지 않는다")
    fi = getattr(tn, "fix_i", None)                 # 수정 전 코드에는 없다 — 그때는 실패로 센다
    F = (lambda *a: fi(*a)) if fi else (lambda *a: "없음")                         # noqa: E731
    chk(F("12", "|", 4, 30, "45", 30) is None, "② 숫자 사이 `|`(표 괘선)는 `I` 가 아니다")
    chk(F("say", "|", 4, 80, "like", 30) is None, "② 글자보다 훨씬 긴 `|` 는 `I` 가 아니다")
    # 261101-1 보완(지휘 세션의 실제 경로 확인): HM 에서 실제로 나온 `I` 의 모양들
    chk(F("Ooh!", "I", 5, 53, "felt", 31) == "I", "② 위아래 글줄과 엉겨 높이 53 인 `I` 도 남긴다")
    chk(F("say.", "1", 1, 28, "keep", 31) == "I", "② 획 1px 인 `1` 은 `I`")
    chk(F("page", "1", 14, 28, "of", 31) is None, "② 폭이 있는 숫자 `1` 은 그대로")
    chk(F("it.", "[", 4, 28, "summon", 31) == "I", "② 좁은 `[` 는 `I`")
    chk(F("God.", "[can", 78, 28, "talk.", 31) == "I can", "② 낱말에 붙은 `[can` → `I can`")
    chk(F("am", "[?”", 39, 29, "]", 31) == "I?”" and F("[?”", "]", 8, 28, "say", 31) == "I",
        "② `am [?” ] say` → `am I?” I say`(이웃이 그 자신 `I` 후보여도)")
    chk(F(None, "Wait—t", 135, 28, "just", 31) == "Wait—I", "② 대시 뒤 `Wait—t` → `Wait—I`")
    chk(F("because", "|", 8, 28, None, 31) == "I", "② 줄 끝 `|` 도 앞이 영문이면 `I`")
    lig = getattr(tn, "fix_ligature", None)
    chk(bool(lig) and lig("satisfled.") == "satisfied." and lig("fled.") is None,
        "② `fi`↔`fl` 합자 — 사전에 없는 낱말만 고친다")
    chk(tx._dehyphen_ligature("satis", "fled.") == "fied." if hasattr(tx, "_dehyphen_ligature") else False,
        "② 분철을 이어야 드러나는 합자(`satis-` + `fled.`)도 고친다")
    # 표본 조사(HM_bm·성격심리 각 12쪽)에서 나온 것
    chk(F("least", "J", 5, 29, "didn’t", 31) == "I", "②s `At least J didn't` → `I`")
    chk(F(None, "[t", 20, 29, "would", 31) == "It", "②s `[t would` → `It would`")
    chk(F("easy.", "If]", 30, 29, "eat", 31) == "If I", "②s `If] eat` → `If I eat`")
    sg = getattr(tn, "small_glyph_ok", None)
    chk(bool(sg) and sg("을", 15, 0.96, 40) and not sg("을", 15, 0.20, 40) and sg("■", 15, 0.96, 40) is False,
        "②s 납작한 한글 낱자(`을` 15px, 신뢰도 0.96)는 진짜 글자 — 신뢰도 낮으면 아니다")
    rk = getattr(ocr, "_reread_kind", None)
    chk(bool(rk) and rk("SAS", "kor+eng") == "kor" and rk("Aro]", "kor+eng") == "kor" and rk("Adler", "kor+eng") == ""
        and rk("(0100010009'", "kor+eng") == "eng" and rk("(press)", "kor+eng") == "",
        "②s 다시 읽을 자리 고르기 — 대문자 잡글은 `kor`, 괄호 속 숫자 잡글은 `eng`, 이름·바른 영문은 그대로")
    # 실제 `ocr_image` 길 — 쪽 판독(psm 4)은 한글 줄에 `SAS`·납작한 `을` 을 내놓고, 그 자리를 `kor` 로 다시 읽으면 `음식을`
    from PIL import Image
    kd = {k: [] for k in ("text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num")}
    for s, x, w, h, cf in (("위해", 100, 60, 40, 95), ("SAS", 170, 70, 40, 60), ("찾는다.", 250, 90, 40, 95),
                           ("초점", 360, 60, 40, 95), ("을", 422, 25, 15, 96), ("두고", 455, 60, 40, 95)):
        kd["text"].append(s); kd["left"].append(x); kd["top"].append(100 + (40 - h)); kd["width"].append(w)
        kd["height"].append(h); kd["conf"].append(cf); kd["block_num"].append(1); kd["par_num"].append(1)
        kd["line_num"].append(1)

    def fake_itd(im, lang="", config="", output_type=None):
        if "--psm 4" in config:
            return kd
        if "--psm 7" in config and lang == "kor":
            return {"text": ["음", "식", "을"], "conf": [92, 93, 94], "top": [0, 0, 0], "height": [30] * 3, "left": [0, 20, 40]}
        return {"text": [], "conf": [], "top": [], "height": [], "left": []}
    _old = (ocr.ensure_tesseract, pytesseract.image_to_data)
    ocr.ensure_tesseract = lambda: {"ok": True}
    pytesseract.image_to_data = fake_itd
    try:
        txt = ocr.ocr_image(Image.new("RGB", (800, 300), "white"), lang="kor+eng", dpi=300)["text"]
    finally:
        ocr.ensure_tesseract, pytesseract.image_to_data = _old
    chk("음식을" in txt and "SAS" not in txt, "②s 한글 줄의 영문 잡글을 그 자리만 `kor` 로 다시 읽는다(§14.8.2)", txt)
    chk("초점" in txt and "을" in txt.split("초점", 1)[1][:3], "②s 납작한 `을` 이 사라지지 않는다", txt)
    chk(not tx._starts_list("1.00 g.") and tx._starts_list("【주2】소성") and tx._starts_list("1. 개요"),
        "②s `1.00 g` 은 목록이 아니고 `【주2】` 는 목록 표시")
    chk(tx._join_sep("We need at least twenty-", "six years.") == "", "②s `twenty-` + `six` → 붙임표를 남긴다")

    # ── 남은 과제 ① 홀로 선 한글 한 음절(§3.6.15) · ② 줄 첫머리 목록 기호(§3.5.4) ───────────
    fk = getattr(tx, "fix_ko_spacing", None)
    got = fk("가 족이나 권위적 대 상에 대한 불만") if fk else ""
    chk(got == "가족이나 권위적 대상에 대한 불만", "남① `가 족이나`·`대 상에` → 붙인다", got)
    got = fk("자신 및 사회와의 괴리, 실시 및 채점 요강과 기술") if fk else ""
    chk(got == "자신 및 사회와의 괴리, 실시 및 채점 요강과 기술", "남① 늘 띄어 쓰는 `및` 과 다른 빈칸은 그대로", got)
    got = fk("이 척도에서 측정하는 주요 대상이다.") if fk else ""
    chk(got == "이 척도에서 측정하는 주요 대상이다.", "남① 관형사 `이` 는 띄운 채로", got)
    ab = getattr(tn, "as_bullet", None)
    chk(bool(ab) and ab("ㆍ", 9, 10, True, True, 38) == "•" and ab("*", 17, 16, True, True, 38) == "■"
        and ab("■", 60, 60, True, False, 38) is None and ab("ㆍ", 9, 10, False, True, 38) is None,
        "남② 줄 첫머리의 작은 `ㆍ`→`•`, 네모 `*`→`■` — 홀로 있거나 줄 가운데면 아니다")
    bd = {k: [] for k in ("text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num")}
    for s, x, w, h, cf, ln in (("ㆍ", 100, 9, 10, 83, 1), ("사회적", 120, 90, 40, 95, 1), ("가치를", 235, 90, 40, 95, 1),
                               ("ㆍ", 100, 9, 10, 88, 2), ("화를", 115, 60, 40, 95, 2), ("낸다.", 200, 70, 40, 95, 2)):
        bd["text"].append(s); bd["left"].append(x); bd["top"].append(100 * ln + (40 - h) // 2); bd["width"].append(w)
        bd["height"].append(h); bd["conf"].append(cf); bd["block_num"].append(1); bd["par_num"].append(1)
        bd["line_num"].append(ln)
    _old = (ocr.ensure_tesseract, pytesseract.image_to_data)
    ocr.ensure_tesseract = lambda: {"ok": True}
    pytesseract.image_to_data = lambda *a, **k: bd
    try:
        res = ocr.ocr_image(None, lang="kor+eng", dpi=300)
    finally:
        ocr.ensure_tesseract, pytesseract.image_to_data = _old
    rows = tx.lines_from_words(res["words"], dpi=300)
    chk(res["text"].startswith("• 사회적") and "\n• 화를" in res["text"], "남② study.db 본문에 목록 기호가 남는다", res["text"])
    chk([r["text"][:5] for r in rows] == ["• 사회적", "• 화를 "[:5]], "남② 텍스트 창 줄에도 `• ` 로 남는다",
        str([r["text"] for r in rows]))

    # ── ③ OCR 줄은 ⑧(크기)로 끊지 않는다(§3.7.11) — 잉크 높이가 줄마다 다르다 ─────────
    body = ["The whiteness lessens My eyes are adjusting I start to see shapes and",
            "but nothing sensible yet Lets see can I move my hands No feet either",
            "The two brushed steel armatures hang from the ceiling Each one has an",
            "assortment of disturbingly penetration looking tools where hands go."]
    words = []
    for i, ln in enumerate(body):
        # 오름·내림 획이 없는 낱말만 든 줄처럼 잉크 높이를 7 / 10 으로 번갈아
        words += line_words(ln, 100 + i * 14, h=10.0, heights=[10.0] if i % 2 == 0 else [7.0], cw=4.6, gap=2.4)
    rows = tx.join_sentences(tx.lines_from_words(words, dpi=0))
    chk(len(rows) == 1, "③ 문단 한 덩이로 잇는다(잉크 높이 7/10 이 섞여도)", str([r["text"][:30] for r in rows]))
    # 글자층 줄은 ⑧ 그대로 — 크기가 다른 줄은 잇지 않는다
    lay = [{"text": "aaaa bbbb cccc dddd eeee", "style": "body", "kind": "text", "rect": (72, 100, 400, 110), "size": 10.0},
           {"text": "ffff gggg", "style": "body", "kind": "text", "rect": (72, 112, 200, 118), "size": 6.0}]
    for k in range(3):
        lay.append({"text": "hhhh iiii jjjj kkkk llll.", "style": "body", "kind": "text",
                    "rect": (72, 130 + k * 12, 400, 140 + k * 12), "size": 10.0})
    chk(len(tx.join_sentences(lay)) >= 2, "③ 글자층 줄은 ⑧ 을 그대로 본다")
    # 차례 — 두 줄 다 쪽 번호로 끝나면 잇지 않는다(OCR 줄)
    toc = []
    for i, ln in enumerate(["성격 연습 8 자극 추구 성격의 이해와 적용 165", "성격 연습 9 성실성 그리고 사회적 성격 167",
                            "성격 연습 10 개방성 그리고 다른 사람들 169", "성격 연습 11 친화성 그리고 대인 관계의 성격 171"]):
        toc += line_words(ln, 100 + i * 14, cw=8.0, gap=6.0)
    rows = tx.join_sentences(tx.lines_from_words(toc, dpi=0))
    chk(len(rows) == 4, "③ 차례 항목(쪽 번호로 끝남)은 잇지 않는다", str([r["text"] for r in rows]))

    # ── ④ 줄 끝 `-` — 합성어는 남기고 분철은 뗀다(§3.7.3·§3.7.11) ────────────────────
    chk(tx._join_sep("It's kind of oval-", "shaped.") == "", "④ `oval-` + `shaped` → 붙임표를 남긴다",
        tx._join_sep("It's kind of oval-", "shaped."))
    chk(tx._join_sep("the computer seems satis-", "fied.") == "-drop", "④ `satis-` + `fied` → 분철을 뗀다")

    # ── ⑤ 짝·홀수 쪽 머리말이 다른 책 — 옆 쪽 ±2 로 지운다(§3.5.2) ───────────────────
    dst = os.path.join(root, "book.pdf")
    doc = fitz.open()
    for _ in range(5):
        doc.new_page(width=432, height=648)
    doc.save(dst)
    doc.close()
    BODY = ["take another breath On purpose My mouth is sore My throat is sore But",
            "its my soreness I have control Im wearing a breathing mask Its tight to",
            "my face and connected to a hose that goes behind my head Can I get up",
            "No But I can move my head a little I look down at my body Im naked",
            "and connected to more tubes than I can count Theres one in each arm and"]
    heads = {0: "PROJECT HAIL MARY 3", 1: "4 ANDY WEIR", 2: "PROVECGCT HAIL MARY 5",
             3: "6 ANDY WEIR", 4: "PROJECT HAIL MARY 7"}
    pages = {}
    for p in range(5):
        w = line_words(heads[p], 18, x=150, h=7.0, cw=5.0, gap=4.0)
        for i, ln in enumerate(BODY):
            w += line_words(ln, 80 + i * 14, x=40, cw=4.6, gap=2.4)
        pages[p] = (w, 0)
    look = lambda k: pages.get(k, ([], 0))                                       # noqa: E731
    d = fitz.open(dst)
    rows = tx.page_lines(d, dst, 2, ocr_words=pages[2][0], ocr_dpi=0,
                         ocr_peer_words=tx._peer_words(look, 2, 5))
    d.close()
    allt = " ".join(r["text"] for r in rows)
    chk("HAIL" not in allt, "⑤ 짝·홀수 머리말이 다른 책에서 오인식된 머리말까지 지운다", allt[:60])
    chk("take another breath" in allt and "Theres one in each arm" in allt, "⑤ 본문은 잃지 않는다")
    # 261101-1 보완: 텍스트 창에서 **두 쪽만** OCR 한 상태 — 옆 쪽 낱말이 없어도 쪽 번호를 단 머리말은 지운다
    none = lambda k: ([], 0)                                                     # noqa: E731
    d = fitz.open(dst)
    rows = tx.page_lines(d, dst, 2, ocr_words=pages[2][0], ocr_dpi=0, ocr_peer_words=tx._peer_words(none, 2, 5))
    allt = " ".join(r["text"] for r in rows)
    chk("HAIL" not in allt and allt.startswith("take another breath"), "⑤ 옆 쪽 OCR 이 없어도 쪽 번호를 단 머리말은 지운다", allt[:60])
    # 쪽 번호가 없는 머리말은 되풀이를 확인할 길이 없어 남는다 — 그래도 **본문 첫 줄에 붙지 않는다**
    bw = []
    for i, ln in enumerate(BODY):                    # HM 처럼 머리말 바로 아래(줄 거리 하나)에서 본문이 시작한다
        bw += line_words(ln, 54 + i * 14, x=40, cw=4.6, gap=2.4)
    hw = line_words("PROJECT HAIL MARY", 40, x=150, h=7.0, cw=5.0, gap=4.0)
    dx = max(q["x1"] for q in bw) - max(q["x1"] for q in hw)     # HM 처럼 오른쪽 끝에 맞춘 머리말
    for q in hw:
        q["x0"] += dx; q["x1"] += dx
    w = hw + bw
    rows = tx.page_lines(d, dst, 2, ocr_words=w, ocr_dpi=0, ocr_peer_words=None)
    d.close()
    chk(rows and rows[0]["text"] == "PROJECT HAIL MARY", "⑤ 지우지 못한 머리말이 본문 첫 줄에 이어 붙지 않는다",
        rows[0]["text"][:60] if rows else "")
    chk(not tx._page_number_line("January 2025") if hasattr(tx, "_page_number_line") else False,
        "⑤ 네 자리 수(연도)는 쪽 번호로 보지 않는다")
    # 표본 조사(성격심리): 큰 쪽 번호로 머리말 아래끝이 8% 를 넘고, 본문과 줄 높이의 1.2배만 떨어졌다 · `30|`
    for head in ("3 제12장 머레이의 욕구 및 동기 이론", "3. 성격 발달 3|"):           # 합성 문서의 3번째 쪽
        hw = line_words(head, 40, x=40, h=16.0, cw=7.0, gap=12.0)      # 40~56 → 아래끝 0.086
        bw = []
        for i, ln in enumerate(BODY):
            bw += line_words(ln, 76 + i * 16, x=40, h=12.0, cw=4.6, gap=2.4)
        d = fitz.open(dst)
        rows = tx.page_lines(d, dst, 2, ocr_words=hw + bw, ocr_dpi=0, ocr_peer_words=None)
        d.close()
        chk(rows and rows[0]["text"].startswith("take another"), "⑤s 큰 쪽 번호 머리말(`%s`)도 지운다" % head[:8],
            rows[0]["text"][:40] if rows else "")
    try:
        ok = not tx._page_number_line("1, 설리반의 생애 270", 12) and tx._page_number_line("300 제12장 머레이", 301)
    except TypeError:                               # 수정 전 코드에는 쪽 순서 인자가 없다
        ok = False
    chk(ok, "⑤s 쪽 순서와 동떨어진 수(차례 항목 `…생애 270`, 12쪽)는 쪽 번호가 아니다")
    # 글자층 PDF 확인(NAPA_BMD, 사용자 지시): `1)` 은 목록 번호 — 15쪽 본문 줄이 꼬리말로 지워졌다. 괄호는 짝일 때만 쪽 번호
    try:
        ok = (not tx._page_number_line("1) materials, 2) production, and 3) testing.", 16)
              and tx._page_number_line("(16) BMD-001", 16) and tx._page_number_line("- 16 -", 16))
    except TypeError:
        ok = False
    chk(ok, "⑤s `1) materials…` 의 `1)` 은 쪽 번호가 아니다(괄호는 짝일 때만)")
    chk(tx._join_sep("Design, 24(3), 836–849. https://doi.org/10.1080/", "14680629.2022.2029548") == "",
        "⑤s 줄 끝에서 끊긴 웹 주소는 빈칸 없이 잇는다")

    # ── ③' 닫는 따옴표 앞 문장 끝 — 다음 문단을 붙이지 않는다(§3.7.2 ③) ─────────────────
    q = ["But I take a deep breath and speak slowly and carefully to the robot",
         "computer that hangs above my bed. Two times e to the two i pi.”",
         "“Incorrect. What is the cube root of eight asks the computer again",
         "and I sigh because it will not stop asking me that same question."]
    words = []
    for i, ln in enumerate(q):
        words += line_words(ln, 100 + i * 14, cw=4.6, gap=2.4)
    rows = tx.join_sentences(tx.lines_from_words(words, dpi=0))
    chk(len(rows) == 2 and rows[1]["text"].startswith("“Incorrect."), "③' `…pi.”` 다음 줄은 새 문단",
        str([r["text"][-20:] for r in rows]))

    # ── ③s 들여쓰기 문단(§3.7.13) — 문장 끝 + 들여쓰지 않은 다음 줄은 같은 문단, 들여쓴 줄은 새 문단 ─────
    para = [("I squeeze another shot of gravy goo into my mouth. Still delicious.", 52),
            ("I gobble it down. Soon the tube is empty and I hold it up for more", 40),
            ("food. The computer does not answer me and I sigh once again here.", 40),
            ("It makes sense. My digestive system is getting used to semi solid", 52),
            ("food right now. Best to take it easy and not eat too much at once.", 40),
            ("Give me more food! No one cares about the right thing when they are", 52),
            ("hungry right now and I am hungry too so give me some food please.", 40)]
    pw = []
    for i, (ln, x) in enumerate(para):
        ww = line_words(ln, 100 + i * 14, x=x, cw=4.6, gap=2.4)
        dx = 360 - ww[-1]["x1"]                           # 양쪽 정렬 — 오른쪽 끝을 맞춘다(마지막 줄 제외)
        if i not in (2, 4, 6):
            for k, q in enumerate(ww):
                sh = dx * k / max(1, len(ww) - 1)
                q["x0"] += sh; q["x1"] += sh
        pw += ww
    rows = tx.join_sentences(tx.lines_from_words(pw, dpi=0))
    chk(len(rows) == 3 and rows[0]["text"].endswith("sigh once again here."),
        "③s 들여쓰기 문단 책 — `…delicious.` 다음 들여쓰지 않은 줄은 같은 문단", str([r["text"][:25] for r in rows]))
    lay = [{"text": r["text"], "style": "body", "kind": "text", "rect": r["rect"], "size": r["size"]}
           for r in tx.lines_from_words(pw, dpi=0)]
    chk(len(tx.join_sentences(lay)) > 3, "③s 글자층 줄에는 걸지 않는다(참고문헌·주석이 붙었다)")

    # ── ③s 본문 쪽의 ` | ` 는 빈자리 — 빈칸으로(§3.6.14), 표 쪽은 그대로 ─────────────────
    pw = []
    for i in range(10):
        ww = line_words("the quick brown fox jumps over the lazy dog again and", 100 + i * 14, cw=4.6, gap=2.4)
        if i == 4:
            for q in ww[5:]:
                q["x0"] += 60; q["x1"] += 60               # 버려진 낱말 자리
        pw += ww
    allt = " ".join(r["text"] for r in tx.lines_from_words(pw, dpi=0))
    chk(" | " not in allt, "③s 본문 쪽의 빈자리는 ` | ` 가 아니라 빈칸", allt[:80])
    tw = []
    for i in range(10):
        tw += line_words("항목 값", 100 + i * 14, x=40, cw=8, gap=4) + line_words("12.5", 100 + i * 14, x=300, cw=8)
    allt = " ".join(r["text"] for r in tx.lines_from_words(tw, dpi=0))
    chk(allt.count(" | ") == 10, "③s 표 쪽(모든 행에 칸)은 ` | ` 를 그대로 둔다", allt[:60])

    # ── ⑥ 쪽을 넘어간 문장 — 여러 쪽 산출물에서만 잇는다(§3.7.12) ───────────────────
    carry = getattr(tx, "page_carry", None)
    a = [{"text": "I breathe a sigh of relief. Wait I just controlled my breathing. I", "style": "body",
          "kind": "text", "rect": (40, 300, 392, 310), "rects": [(40, 300, 392, 310)], "size": 10.0}]
    a_prev = [{"text": "x" * 70, "style": "body", "kind": "text", "rect": (40, 280, 392, 290), "size": 10.0}] + a
    b = [{"text": "take another breath. On purpose.", "style": "body", "kind": "text",
          "rect": (40, 80, 250, 90), "size": 10.0}]
    ok = bool(carry) and carry(a_prev, b)
    chk(ok and a_prev[-1]["text"].endswith("breathing. I take another breath. On purpose.") and not b,
        "⑥ 쪽 끝 문장을 다음 쪽 첫 줄과 잇는다", a_prev[-1]["text"][-50:])
    a2 = [{"text": "Thank God. I can talk.", "style": "body", "kind": "text", "rect": (40, 300, 392, 310), "size": 10.0}]
    b2 = [dict(b[0]) if b else {"text": "take another breath.", "style": "body", "kind": "text",
                                "rect": (40, 80, 250, 90), "size": 10.0}]
    chk(bool(carry) and carry(a2, b2) is False and len(b2) == 1, "⑥ 문장이 끝난 쪽은 잇지 않는다")

    # ── ⑦ `kor+eng` 인데 한글이 없으면 `eng` 로 좁히고, 한글이 보이면 되돌린다(§14.8.1) ────
    Picker = getattr(ocr, "LangPicker", None)
    calls = []
    EN = " ".join(["the computer asks what is two plus two and I answer"] * 5)
    # 성격심리 30쪽을 `eng` 로 읽은 실제 결과(한글이 이렇게 나온다)
    KO_AS_EN = "AAS St ol] AIS BAlst QS APA) Ae] st BAA BA oS Say Ach Was Abe 4} ete}, Ay Messe olzts] AA] AAS ES ABs " * 3

    def fake_build(doc, page_index, *, lang="eng", **kw):
        calls.append((page_index, lang))
        txt = EN if page_index < 4 else (KO_AS_EN if lang == "eng" else "성격의 이해 " * 20)
        return {"source": "ocr", "text": txt, "words": [], "dpi": 300, "conf": 0.9, "engine": "tesseract"}
    _ob, _al = ocr.build_page, ocr.available_langs
    ocr.build_page, ocr.available_langs = fake_build, (lambda: ["eng", "kor", "osd"])
    try:
        langs = []
        if Picker:
            pk = Picker("kor+eng")
            for p in range(6):
                langs.append(pk.read(None, p)["lang"])
            pk1 = Picker("kor")
            k1 = [pk1.read(None, p)["lang"] for p in range(4)]
        else:
            k1 = []
    finally:
        ocr.build_page, ocr.available_langs = _ob, _al
    # 261101-1 보완: 두 쪽만 읽어도 첫 쪽부터 — 한글 없는 쪽 **하나**면 그 쪽을 `eng` 로 다시 읽는다
    chk(langs[:4] == ["eng"] * 4, "⑦ 한글 없는 쪽이 나오면 그 쪽부터 `eng`", str(langs))
    chk(langs[4:] == ["kor+eng", "kor+eng"], "⑦ `eng` 로 읽은 쪽이 잡글이면 그 쪽을 다시 읽고 되돌린다", str(langs))
    chk(k1 == ["kor"] * 4, "⑦ `kor` 하나를 고른 것은 건드리지 않는다", str(k1))
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("FAILED:", len(fails)) if fails else print("ALL PASS")
sys.exit(1 if fails else 0)
