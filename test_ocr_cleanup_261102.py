# -*- coding: utf-8 -*-
"""261102-2: beta.2 손 확인의 OCR·텍스트 창 지적 — 왼쪽 정렬 줄 잇기·본문 글꼴 하나·OCR 줄 크기·
번호의 점·한영 섞인 낱말·갈린 굵은 영문·표 제목 `<` (텍스트 창 SOT §3.4·§3.5.5·§3.7.14, 단어학습 SOT §14.8.3).

실제 문서(_96 건설부 시험시공 보고서 11·12·117쪽, NAPA_BMD 2·3쪽)로 잰 것은 SOT 에 있고, 이 검사는 **같은 성질을 갖춘
합성 입력**으로 규칙을 고정한다 — Tesseract 가 필요한 곳은 `image_to_data`·`image_to_boxes` 결과를 흉내 내어 실제 `ocr_image` 를 태운다.
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

import pytesseract
from PIL import Image
from viewer import text_extract2 as tx
from viewer import text_noise as tn
from viewer.study import ocr

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def page_data(words):
    """`(글, x, 폭, 높이, 신뢰도, 줄)` → `image_to_data` 사전(쪽 판독, psm 4)."""
    d = {k: [] for k in ("text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num")}
    for s, x, w, h, cf, ln in words:
        d["text"].append(s); d["left"].append(x); d["top"].append(100 * ln + (46 - h)); d["width"].append(w)
        d["height"].append(h); d["conf"].append(cf); d["block_num"].append(1); d["par_num"].append(1)
        d["line_num"].append(ln)
    return d


def run_ocr(page, kor_line=None, eng_chars=""):
    """흉내 낸 Tesseract 로 `ocr_image` 를 태운다 — 한 자리 다시 읽기(psm 7)는 `kor_line`(낱말·신뢰도·x)·`eng_chars`(글자·x)."""
    kor_line = kor_line or []

    def itd(im, lang="", config="", output_type=None):
        if "--psm 4" in config:
            return page
        if "--psm 7" in config and lang == "kor":
            return {"text": [t for t, _c, _x in kor_line], "conf": [c for _t, c, _x in kor_line],
                    "left": [x for _t, _c, x in kor_line], "top": [0] * len(kor_line), "height": [40] * len(kor_line)}
        return {"text": [], "conf": [], "left": [], "top": [], "height": []}

    def itb(im, lang="", config=""):
        return "\n".join(f"{ch} {x - 10} 5 {x + 10} 40 0" for ch, x in eng_chars)
    old = (ocr.ensure_tesseract, pytesseract.image_to_data, pytesseract.image_to_boxes)
    ocr.ensure_tesseract = lambda: {"ok": True}
    pytesseract.image_to_data, pytesseract.image_to_boxes = itd, itb
    try:
        return ocr.ocr_image(Image.new("RGB", (1600, 600), "white"), lang="kor+eng", dpi=300)["text"]
    finally:
        ocr.ensure_tesseract, pytesseract.image_to_data, pytesseract.image_to_boxes = old


# ── ① 줄 첫머리 번호의 점(§14.8.3) — `45.2 배합설계` 를 `kor` 로 다시 읽으면 `4.5.2` ───────────────
txt = run_ocr(page_data([("45.2", 100, 80, 46, 90, 1), ("배합설계", 200, 160, 46, 95, 1)]),
              kor_line=[("4.5.2", 88, 0)])
chk(txt.startswith("4.5.2"), "① 한글 줄 첫머리 `45.2` → `4.5.2`(숫자가 같고 점이 더 많을 때)", txt)
txt = run_ocr(page_data([("45.2", 100, 80, 46, 90, 1), ("배합설계", 200, 160, 46, 95, 1)]),
              kor_line=[("4.6.2", 88, 0)])
chk(txt.startswith("45.2"), "① 숫자가 달라지는 다시 읽기는 받지 않는다", txt)
txt = run_ocr(page_data([("45.2", 100, 80, 46, 90, 1), ("kg", 200, 60, 46, 95, 1)]), kor_line=[("4.5.2", 88, 0)])
chk(txt.startswith("45.2"), "① 한글이 없는 줄(표의 수)은 다시 읽지 않는다", txt)

# ── ② 한영 섞인 낱말(§14.8.3) — 영문 머리는 `eng` 글자, 한글 꼬리는 `kor` 낱말(한글이 시작하는 자리에서 가른다) ───
txt = run_ocr(page_data([("(1)", 100, 50, 46, 90, 1), ("COES]", 170, 150, 46, 40, 1), ("활주로", 380, 120, 46, 95, 1)]),
              kor_line=[("20,8", 0, 6), ("의", 91, 107)], eng_chars=[("C", 22), ("O", 56), ("E", 90), ("]", 126)])
chk("COE의 활주로" in txt and "COES]" not in txt, "② `COES]` → `COE의`", txt)
txt = run_ocr(page_data([("CBRAAYS", 100, 300, 46, 40, 1), ("결정하기", 420, 160, 46, 95, 1)]),
              kor_line=[("02", 0, 6), ("설", 0, 114), ("계", 90, 156), ("법", 93, 206), ("을", 96, 256)],
              eng_chars=[("C", 20), ("B", 54), ("R", 86), ("A", 126), ("I", 135), ("7", 170)])
chk("CBR설계법을" in txt, "② `CBRAAYS` → `CBR설계법을`(영문에 맞닿아 신뢰도 0 인 첫 음절도 가운데 값으로)", txt)
txt = run_ocr(page_data([("AASHO", 100, 180, 46, 92, 1), ("도로시험의", 330, 200, 46, 95, 1)]),
              kor_line=[("스스)", 0, 6)], eng_chars=[(c, 20 + 34 * k) for k, c in enumerate("AASHO")])
chk("AASHO 도로시험의" in txt, "② 바른 영문 약어(`AASHO`)는 그대로", txt)

# ── ③ 갈린 굵은 영문(§14.8.3) — `\4` `ㅅ` `980` 을 묶어 `eng` 로, 바로 뒤 한글 낱말과 겹친 꼬리는 뗀다 ─────────
txt = run_ocr(page_data([("(2)", 100, 50, 46, 90, 1), ("\\4", 170, 60, 46, 20, 1), ("ㅅ", 235, 30, 46, 20, 1),
                         ("980", 270, 60, 46, 20, 1), ("의도로", 340, 120, 46, 95, 1), ("실험", 470, 80, 46, 95, 1)]),
              kor_line=[("\\", 90, 0), ("ㅅ", 32, 42), ("910", 80, 79), ("의", 88, 179)],
              eng_chars=[("W", 20), ("A", 59), ("S", 90), ("H", 121), ("O", 158), ("2", 180), ("]", 200)])
chk("WASHO" in txt and "ㅅ" not in txt and "980" not in txt and "의의" not in txt,
    "③ `\\4 ㅅ 980 의도로` → `WASHO 의도로`(겹친 `의` 는 한 번만)", txt)

# ── ④ 표·그림 제목의 `<`(텍스트 창 SOT §3.5.5) ─────────────────────────────────────────
txt = run_ocr(page_data([("시험구간은", 100, 200, 46, 95, 1), ("그", 320, 40, 46, 93, 1), ("림", 365, 40, 46, 93, 1),
                         ("2-1>", 410, 80, 36, 89, 1), ("에서", 495, 60, 46, 92, 1)]))
chk("<그림2-1>" in txt, "④ 여는 `<` 가 아예 안 읽힌 `그림2-1>` → `<그림2-1>`", txt)
txt = run_ocr(page_data([("<", 100, 20, 46, 40, 1), ("표4-74>", 125, 150, 46, 92, 1), ("아스팔트의", 290, 200, 46, 95, 1)]))
chk(txt.startswith("<표4-74>") or txt.startswith("< 표4-74>"), "④ 낮은 신뢰도로 따로 읽힌 `<` 를 버리지 않는다", txt)
txt = run_ocr(page_data([("“", 100, 20, 46, 85, 1), ("도로", 125, 80, 46, 95, 1), ("실험", 220, 80, 46, 95, 1)]))
chk(txt.startswith("“"), "④ 낱말에 붙은 따옴표는 기호만이어도 남긴다", txt)
bo = getattr(tn, "bracket_ok", None)
chk(bool(bo) and bo("<", 0.92, 46, 46, 5) and not bo("<", 0.92, 46, 46, 200) and not bo("■", 0.92, 46, 46, 5)
    and not bo("<", 0.20, 46, 46, 5), "④ 괄호 남기기 — 옆 낱말과 떨어졌거나·괄호가 아니거나·신뢰도가 바닥이면 아니다")
txt = run_ocr(page_data([("성과는", 100, 120, 46, 95, 1), ("<표4-73>과", 230, 200, 46, 92, 1), ("같다.", 440, 90, 46, 95, 1)]))
chk("<<" not in txt, "④ 이미 `<` 가 있는 가리킴에는 더하지 않는다", txt)

# ── ⑤ OCR 줄의 크기는 낱말 높이의 중앙값(§3.4) — 몇 상자가 엉겨 커도 줄이 제목이 되지 않는다 ─────────────
fr = [((72, 100, 90, 111), "됐다.", 11.0), ((92, 100, 110, 111), "그", 11.0), ((112, 96, 170, 112.3), "로시험의결과", 16.3)]
got = tx._merge_rows(fr, cjk_gap=0.6)[0][2]
chk(abs(got - 11.0) < 0.5, "⑤ OCR 줄 크기 = 낱말 높이 중앙값(가장 긴 낱말의 높이가 아니다)", str(got))
chk(abs(tx._merge_rows(fr)[0][2] - 16.3) < 0.01, "⑤ 글자층 조각은 종전대로(가장 긴 조각의 글꼴 크기)")

# ── ⑥ 텍스트 창은 본문 글꼴 하나(§3.4) — 줄 판정의 `title` 은 남기되 창에는 본문으로 ─────────────
rows = [{"text": "2.1.2 설계법", "style": "title"}, {"text": "본문", "style": "body"}]
ab = getattr(tx, "as_body", None)
out = ab(rows) if ab else rows
chk([r["style"] for r in out] == ["body", "body"] and rows[0]["style"] == "title",
    "⑥ `as_body` — 창에 보낼 줄은 모두 본문, 원래 줄은 건드리지 않는다")
import inspect
from viewer import workers
chk("as_body(" in inspect.getsource(workers.TextPageWorker.run), "⑥ 텍스트 창(TextPageWorker)은 본문 글꼴 하나")


# ── ⑦ 왼쪽 정렬 단의 줄 잇기(§3.7.14) — 오른쪽이 들쭉날쭉해도 문단은 잇는다 ─────────────────────
def lay(t, y, x1, x0=72.0):
    return {"text": t, "style": "body", "kind": "text", "rect": (x0, y, x1, y + 10), "size": 10.0}


page = [lay("Balanced mix design is a procedure that uses", 100, 330),
        lay("the results of performance tests to verify and", 112, 345),
        lay("to adjust the design of asphalt mixtures so", 124, 320),
        lay("that the mix will resist rutting and cracking", 136, 352),
        lay("in the field over its whole service life.", 148, 300),
        lay("A second paragraph starts here and it goes on", 172, 340),
        lay("to the end of the column without a full stop", 184, 330),
        lay("as it is a left aligned column of body text", 196, 335),
        lay("that is wide enough to show the right margin.", 208, 400)]
rows = tx.join_sentences(page)
allt = [r["text"] for r in rows]
chk(any("procedure that uses the results" in t and "service life." in t for t in allt),
    "⑦ 왼쪽 정렬 단 — 다음 낱말이 들어갈 자리가 남아도 문단은 잇는다", str(allt[:3]))
# 같은 왼쪽 정렬 단에 섞인 목차 줄 — 너그러운 잇기를 숫자에는 걸지 않는다(종전 ④ 로 본다)
toc = page + [lay("연구의 주요 문제 39", 232, 200), lay("요약 49", 244, 140), lay("시험 결과는 다음 표와 같다", 256, 250),
              lay("12 34 56 78", 268, 160)]
allt = [r["text"] for r in tx.join_sentences(toc)]
chk(not any("39 요약" in t or "39요약" in t or "같다 12" in t for t in allt), "⑦ 숫자로 끝나거나 숫자로 시작하는 줄(목차·표의 수)은 잇지 않는다", str(allt))
chk(tx._starts_list("§ 3 시험 방법"), "⑦ `§` 는 목록 표시 — 앞 줄에 잇지 않는다")

print()
print("FAIL", len(fails), fails) if fails else print("ALL PASS")
sys.exit(1 if fails else 0)
