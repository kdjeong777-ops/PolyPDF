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
    # 261108-18(단어학습 SOT §14.24): 판독은 `tess_run` 이 여러 그림을 한 번에 — 그림마다 위 대역으로
    from viewer.study import tess_run
    old = (ocr.ensure_tesseract, tess_run.data, tess_run.boxes)
    ocr.ensure_tesseract = lambda: {"ok": True}
    tess_run.data = lambda ims, lang, config="": [itd(im, lang=lang, config=config) for im in ims]
    tess_run.boxes = lambda ims, lang, config="": [itb(im, lang=lang, config=config) for im in ims]
    try:
        return ocr.ocr_image(Image.new("RGB", (1600, 600), "white"), lang="kor+eng", dpi=300)["text"]
    finally:
        ocr.ensure_tesseract, tess_run.data, tess_run.boxes = old


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


# ── ⑧ 목차 쪽 제목의 잡글 낱말(단어학습 SOT §14.8.4) — 사용자 보고 '_96 목차의 1. 서론을 인식하지 못함' ─────────────
from viewer.study import ocr_pages as opm


class FakeOcr:
    """`read_line_words` 흉내 — 상자 왼쪽 x 로 정해 둔 답을 준다(쪽 그림 좌표)."""
    def __init__(self, line=(), one=None, band=None):
        self.line, self.one, self.band = list(line), one or {}, band or []

    def read_line_words(self, img, box, lang, psm=7):
        if psm == 7 and box[0] > 300:                  # 오른쪽 띠(벌린 제목)
            return [dict(q) for q in self.band]
        if psm in (8, 10):
            return [dict(q) for q in self.one.get(int(box[0]) // 10, [])]
        return [dict(q) for q in self.line]


def Wd(s, x0, x1, conf=0.9, y0=440, y1=495):
    return {"surface": s, "x0": float(x0), "x1": float(x1), "y0": float(y0), "y1": float(y1), "conf": conf}


img = Image.new("RGB", (2400, 1200), "white")
rt = getattr(opm, "reread_toc_title", None)
RT = (lambda *a: rt(*a)) if rt else (lambda *a: "없음")                    # noqa: E731
ws = [Wd("DVD", 266, 376, 0.27), Wd("설계", 412, 493), Wd("법정립을", 560, 722), Wd("위한", 790, 880)]
got = RT(FakeOcr(line=[Wd("2.1.2", 266, 376, 0.43), Wd("설", 406, 446)]), img, ws)
chk(got == "2.1.2 설계 법정립을 위한", "⑧ 줄 첫 잡글(`DVD`)은 그 자리의 `kor` 번호로 — 나머지 낱말은 그대로", str(got))
ws = [Wd("2.2.5", 270, 370), Wd("Asphalt", 400, 560), Wd("Institute(", 570, 760), Wd("AL)", 770, 820, 0.4)]
chk(RT(FakeOcr(line=[Wd("1", 775, 815, 0.9)]), img, ws) is None, "⑧ 영어 문맥의 토막(`Institute( AL)`)은 한글·번호로 바꾸지 않는다")
ws = [Wd("2.2.2", 270, 370), Wd("AASHO", 400, 560, 0.9), Wd("설계법", 590, 700)]
chk(RT(FakeOcr(line=[]), img, ws) is None, "⑧ 영어 약어(`AASHO`)는 `kor` 가 글을 못 내면 그대로")
ws = [Wd("4.3.3", 270, 370), Wd("ALAR", 400, 560, 0.5)]
got = RT(FakeOcr(line=[Wd("시험시공", 400, 560, 0.91)]), img, ws)
chk(got == "4.3.3 시험시공", "⑧ 대문자 4자도 `kor` 가 높은 신뢰도의 한글이면 바꾼다", str(got))
ws = [Wd("31", 230, 280, 0.9), Wd("고무아스팔트", 300, 500)]
got = RT(FakeOcr(line=[Wd("3.1", 230, 280, 0.9), Wd("고무아스팔트", 300, 500)]), img, ws)
chk(got == "3.1 고무아스팔트", "⑧ 점 빠진 줄 첫 번호(`31`)는 숫자가 같을 때만 `3.1`", str(got))
ws = [Wd("OB", 195, 293, 0.31), Wd("연구", 319, 412)]
chk(RT(FakeOcr(line=[Wd("13", 195, 293, 0.0)], one={18: [Wd("18", 195, 293, 0.6)]}), img, ws) is None,
    "⑧ 점 없는 두 자리 수(`OB`→`18`)는 번호로 받지 않는다")
ws = [Wd("Ds", 180, 278, 0.15), Wd("Fi", 281, 305, 0.07)]
got = RT(FakeOcr(line=[Wd("1.", 180, 210, 0.92), Wd("서", 240, 275, 0.49)]), img, ws)
chk(got == "1. 서", "⑧ `Ds Fi` → `1. 서`(덮지 못한 `Fi` 는 한 낱말로 읽어도 글이 없으면 뺀다)", str(got))
ws = [Wd("단독상승9", 230, 420), Wd("/113", 470, 560, 0.4)]
chk(RT(FakeOcr(line=[Wd("7113", 470, 560, 0.8)]), img, ws) is None, "⑧ 숫자 토막의 `/` 가 숫자가 되면(`/113`→`7113`) 받지 않는다")
ws = [Wd("표", 230, 270), Wd("6-2]", 300, 380, 0.4), Wd("반응", 420, 500)]
chk(RT(FakeOcr(line=[Wd("62", 300, 380, 0.8)]), img, ws) is None, "⑧ 번호 모양이 바뀌면(`6-2]`→`62`) 받지 않는다")
ws = [Wd("그림", 230, 300), Wd("BGT", 340, 430, 0.5), Wd("도형", 470, 540)]
chk(RT(FakeOcr(line=[Wd("벼티", 340, 430, 0.6)]), img, ws) is None, "⑧ 대문자 3자 약어(`BGT`)는 낮은 신뢰도의 한글로 바꾸지 않는다")
es = getattr(opm, "extend_spaced_title", None)
got = es(FakeOcr(band=[Wd("론", 315, 360, 0.92)]), img, "1. 서", ws) if es else None
chk(got == "1. 서론", "⑧ 벌린 제목의 다음 음절을 오른쪽 띠에서 읽어 잇는다(`1. 서` → `1. 서론`)", str(got))
got = es(FakeOcr(band=[Wd("록>", 315, 360, 0.9)]), img, "<부", [Wd("<부", 200, 305)]) if es else None
chk(got == "<부록>", "⑧ `<부` → `<부록>`", str(got))
chk(es is not None and es(FakeOcr(band=[Wd("론", 315, 360, 0.92)]), img, "2.1 포장설계의 개념", ws) is None,
    "⑧ 끊기지 않은 제목은 늘이지 않는다")
td = getattr(opm, "_tidy_toc_title", lambda t: t)
chk(td("<참고문 헌>") == "<참고문헌>" and td("7. 결 론") == "7. 결론" and td("6. 자료분석 및 평가") == "6. 자료분석 및 평가",
    "⑧ 벌려 쓴 한 음절(`결 론`)·꺾쇠 속 빈칸만 붙인다 — `및` 같은 한 음절 낱말은 그대로")
la = {"x0": 60.0, "cy": 100.0, "h": 50.0, "title": "DVD 설계 법정립을", "page": 5, "n": 9, "ws": []}
lb = {"x0": 98.0, "cy": 101.0, "h": 50.0, "title": "설계 법정립을 위한 도로시험", "page": 5, "n": 13, "ws": []}
chk(opm._merge_toc_lines([la], [lb])[0]["title"].startswith("DVD"),
    "⑧ 두 판독을 합칠 때 줄 첫머리(번호 자리)를 놓친 제목은 고르지 않는다")


# ── ⑨ 목차 쪽 OCR 자체(build_page) — 사용자 보고 '텍스트 창 4쪽 OCR 다시 읽기에도 1. 서론이 안 된다' ─────────────
#   ⑧ 의 다시 읽기는 책갈피(`toc_lines`)에만 있었다 — 텍스트 창·글자층·검색이 읽는 쪽 OCR 도 같은 규칙을 거쳐야 한다
import fitz
from viewer.study import ocr as so


def toc_res():
    ws = [Wd("Ds", 180, 278, 0.15), Wd("Fi", 281, 305, 0.07), Wd("1", 2100, 2130)]
    for k in range(10):
        y = 600 + 80 * k
        ws += [Wd("2.%d" % (k + 1), 200, 290, 0.9, y, y + 50), Wd("포장", 320, 420, 0.9, y, y + 50),
               Wd("설계", 440, 540, 0.9, y, y + 50), Wd(str(4 + k), 2100, 2130, 0.9, y, y + 50)]
    text = "\n".join(" ".join(w["surface"] for w in ws[i:i + 4]) for i in range(3, len(ws), 4))
    return {"text": "Ds Fi 1\n" + text, "conf": 0.8, "words": ws}


fake = FakeOcr(line=[Wd("1.", 180, 210, 0.92), Wd("서", 240, 275, 0.49)], band=[Wd("론", 315, 360, 0.92)])
_orig = (so.ocr_image, so.render_page, so.read_line_words)
so.ocr_image = lambda img, lang="eng", psm=0, dpi=300: toc_res()
so.render_page = lambda doc, i, dpi=300, drop_watermark_bg=False: (img, None, None)
so.read_line_words = fake.read_line_words
try:
    _d = fitz.open()
    _d.new_page()
    r = so.build_page(_d, 0, lang="kor+eng", force_ocr=True)
    surf = [w["surface"] for w in r["words"]]
    chk(surf[:2] == ["1. 서", "론"] and "Ds" not in surf, "⑨ 목차 쪽 OCR(build_page)의 `Ds Fi` → `1. 서`(묶음 자리 한 낱말) + 띠의 `론`", str(surf[:4]))
    chk(r["text"].splitlines()[0].startswith("1. 서") and "Ds" not in r["text"], "⑨ 쪽 글(검색·단어장)도 고친 낱말로", r["text"][:30])
    chk(sum(1 for s in surf if s == "포장") == 10, "⑨ 잡글 없는 줄은 그대로")
    r = so.build_page(_d, 0, lang="eng", force_ocr=True)
    chk("Ds" in [w["surface"] for w in r["words"]], "⑨ `kor` 를 읽지 않는 쪽(`eng`)은 건드리지 않는다")
finally:
    so.ocr_image, so.render_page, so.read_line_words = _orig
body = [{"words": [Wd(s, 200, 300)]} for s in ["이", "그", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "또"]]
chk(not opm.looks_like_toc(body), "⑨ 번호 목록만 있는 본문 쪽(여러 단 번호 없음)은 목차로 보지 않는다")

# ── ⑩ 텍스트 창 줄 잇기 — 목차 쪽은 잇지 않는다(사용자 보고 '목차인데 줄을 중간에 붙여 제목 앞 번호가 없어진다') ──
#   _96 5쪽 실측 줄(pt): OCR 이 쪽 번호·점선을 못 읽어 제목 줄이 오른쪽까지 찬 문단처럼 보였다
from viewer import text_extract2 as te
_toc = [("3. 시험포장공법의 재료적 특성", 52, 57, 219, 68), ("3.1 고무아스팔트 시험포장 재료", 63, 81, 238, 92),
        ("(32 제강슬래그아스팔트 시험포장 재료,", 55, 97, 279, 118), ("3.3 폴리빌트아스팔트 시험포장 재료", 64, 129, 278, 141),
        ("3.4 AC60O~70 아스콘 시험포장 재료", 63, 153, 262, 165), ("3.5 개립도아스팔트 시험 포장 재료", 64, 177, 250, 188),
        ("4. 아스팔트포장 시험시공", 52, 248, 191, 264), ("4.1 고무아스팔트 시험포장", 63, 273, 209, 284),
        ("4.1.1 재료의 품질", 75, 297, 169, 308), ("4.1.2 배합설계", 75, 321, 151, 332), ("4.1.3 시험 시공", 75, 345, 152, 356),
        ("4.2 제강슬래그아스팔트 시험 포장", 63, 369, 244, 380), ("4.2.1 재료의 품질", 75, 393, 169, 404),
        ("4.4.3시험시공 아아나나 나나", 75, 632, 280, 646), ("4.5 개립도아스팔트 시험 포장", 63, 657, 220, 671),
        ("4.5.1 재료의 품질 아아에아아아", 75, 680, 279, 695), ("4.5.2 배합설계", 75, 699, 150, 716)]
_rows = [{"text": t, "style": "body", "kind": "text", "rect": (x0, y0, x1, y1), "size": y1 - y0, "ocr": True}
         for t, x0, y0, x1, y1 in _toc]
_out = [r["text"] for r in te.join_sentences(_rows)]
chk(_out == [t[0] for t in _toc], "⑩ 목차 쪽 줄은 잇지 않는다(`3.1 …` 뒤에 `3.2`·`3.3` 이 붙지 않음)", str(_out[:3]))
_para = [{"text": t, "style": "body", "kind": "text", "rect": (72, y, 520, y + 11), "size": 11.0, "ocr": True}
         for t, y in [("아스팔트 혼합물의 공용성은 골재의 입도와 결합재의 성질에 따라", 100),
                      ("크게 달라지며 시험포장으로 그 차이를 확인하였다.", 118)]]
chk(len(te.join_sentences(_para)) == 1, "⑩ 본문 쪽의 끊긴 문장은 그대로 잇는다")

# ── ⑪ 목차 쪽 OCR 이 놓친 쪽 번호·번호·줄을 흩어진 글 판독(psm 11)으로 채운다 — 사용자 보고 '5쪽 3.6 요약이 없다' ──
#   _96 5쪽 실측: 표준 판독은 쪽 번호를 하나도 못 읽고 `3.2`→`(32`, `3.6 요약` 줄은 통째로 없었다. psm 11 은 다 읽었다
def _ln(y, *ws):
    return [Wd(s, a, b, 0.9, y, y + 45) for s, a, b in ws]
_std, _sp = [], []
for k, (no, title, pg) in enumerate([("3.1", "고무", "43"), ("3.2", "제강", "45"), ("3.3", "폴리", "50"), ("3.4", "개립", "53"),
                                     ("3.5", "요약", "57"), ("3.6", "결론", "60"), ("4.1", "재료", "61"), ("4.2", "배합", "62"),
                                     ("4.3", "시공", "64"), ("4.4", "품질", "72"), ("4.5", "설계", "74")]):
    y = 200 + 100 * k
    _sp += _ln(y, (no, 264, 330), (title, 353, 450), ("eee", 1100, 1160), (pg, 2034, 2080))
    if no == "3.6":
        continue                                              # 표준 판독에 없는 줄
    _std += _ln(y, ("(32" if no == "3.2" else no, 255 if no == "3.2" else 264, 330), (title, 353, 450))
_orig2 = (so.ocr_image, so.render_page, so.read_line_words)
so.ocr_image = lambda img, lang="eng", psm=0, dpi=300: ({"text": "", "conf": 0.8, "words": [dict(w) for w in _sp]} if psm == opm.TOC_PSM
                                                         else {"text": "", "conf": 0.8, "words": [dict(w) for w in _std]})
so.render_page = lambda doc, i, dpi=300, drop_watermark_bg=False: (Image.new("RGB", (2480, 3508), "white"), None, None)
so.read_line_words = lambda *a, **k: []
try:
    r = so.build_page(_d, 0, lang="kor+eng", force_ocr=True)
finally:
    so.ocr_image, so.render_page, so.read_line_words = _orig2
_lines = [" ".join(w["surface"] for w in ln["words"]) for ln in opm.group_lines(r["words"], 300, raw=True)]
chk(_lines[0] == "3.1 고무 43" and _lines[-1] == "4.5 설계 74", "⑪ 못 읽은 쪽 번호를 채운다", str(_lines[:2]))
chk(_lines[1] == "3.2 제강 45", "⑪ 잘못 읽은 번호(`(32`)는 같은 숫자의 바른 번호(`3.2`)로", _lines[1])
chk("3.6 결론 60" in _lines, "⑪ 표준 판독에 없는 번호 줄을 더한다", str(_lines[4:7]))
chk(not any("eee" in t for t in _lines), "⑪ 점선 리더 잡글은 더하지 않는다")
# 텍스트 창 머리말·꼬리말(§3.5.2): 목차 쪽 맨 위·맨 아래 항목은 쪽 번호를 달아도 지우지 않는다
_pg = fitz.open()
_pg.new_page(width=595, height=842)
_toc_ws = []
for k in range(12):
    y = (30 if k == 0 else 120 + 50 * k) * 300 / 72
    _toc_ws += [Wd("3.%d" % k if k else "3.", 250, 330, 0.9, y, y + 45), Wd("제목", 353, 450, 0.9, y, y + 45),
                Wd(str(40 + k), 2034, 2080, 0.9, y, y + 45)]
_rows = te.lines_from_words(_toc_ws, dpi=300, page=_pg.load_page(0))
chk(len(_rows) == 12 and _rows[0]["text"].startswith("3. 제목"), "⑪ 목차 쪽 첫 항목(`3. 제목 40`)은 머리말로 지우지 않는다",
    str([x["text"] for x in _rows[:2]]))

# ── ⑫ 목차 쪽 OCR 의 남은 잡글·오인식 — 사용자 지시 '픽스 되지 않은 거 수정해'(_96 4~6쪽 실측 꼴) ──
_W = 2480.0
_L = lambda y, *ws: {"cy": y + 22.0, "h": 45.0, "x0": ws[0][1], "words": [Wd(s, a, b, c, y, y + 45) for s, a, b, c in ws]}  # noqa: E731
# 점선 리더 잡글을 빼고, 잡글이 붙은 쪽 번호(`아아아122`·`ll`)는 쪽 번호만
_ln1 = _L(200, ("5.1", 264, 330, .9), ("사후", 353, 450, .9), ("이", 1300, 1320, .4), ("아아아122", 1900, 2080, .6))
_t = opm._toc_parts(_ln1, _W)
_c = opm._clean_toc_rest([w for w in _ln1["words"] if w not in _t["ws"]], _ln1["words"][-1], _t["page"])
chk([w["surface"] for w in _c] == ["122"], "⑫ 점선 잡글(`이`)은 빼고 `아아아122` → `122`", str([w["surface"] for w in _c]))
_ln2 = _L(300, ("2.1.3", 264, 360, .9), ("변천", 400, 480, .9), ("ll", 2000, 2040, .7))
_t = opm._toc_parts(_ln2, _W)
_c = opm._clean_toc_rest([w for w in _ln2["words"] if w not in _t["ws"]], _ln2["words"][-1], _t["page"])
chk([w["surface"] for w in _c] == ["11"], "⑫ 쪽 번호 `ll` → `11`", str([w["surface"] for w in _c]))
# 흩어진 글 판독으로: 앞 줄 번호 다음(`1.2` 다음 `OB`/`(13` → `1.3`), 앞부분만 읽힌 제목(`평가기`/`평가기준치`),
#   신뢰도 낮은 영문(`NASHO` 0.51 / `AASHO` 0.91, `AC60O~70` 0.37 / 같은 쪽 `AC60~70` 0.89), 끝 쉼표(`재료,`), 꺾쇠 줄(`<참고문헌>`)
_std = [_L(100, ("1.2", 264, 330, .9), ("목적", 353, 450, .9), ("2", 2030, 2050, .9)),
        _L(200, ("OB", 264, 330, .31), ("범위", 353, 450, .9), ("2", 2030, 2050, .9)),
        _L(300, ("5.1.2", 264, 360, .7), ("평가기", 400, 560, .9), ("127", 2030, 2080, .9)),
        _L(400, ("2.2.2", 264, 360, .9), ("NASHO", 400, 560, .51), ("설계법", 600, 700, .9), ("15", 2030, 2060, .9)),
        _L(500, ("3.4", 264, 330, .9), ("AC60O~70", 353, 560, .37), ("재료,", 600, 700, .72), ("53", 2030, 2060, .9)),
        _L(600, ("4.4", 264, 330, .9), ("AC60~70", 353, 560, .89), ("53", 2030, 2060, .9))]
_spl = [_L(100, ("1.2", 264, 330, .9), ("목적", 353, 450, .9), ("2", 2030, 2050, .9)),
        _L(200, ("(13", 264, 330, .52), ("범위", 353, 450, .9), ("2", 2030, 2050, .9)),
        _L(300, ("5.1.2", 264, 360, .9), ("평가", 400, 500, .9), ("기준치", 510, 640, .9), ("127", 2030, 2080, .9)),
        _L(400, ("2.2.2", 264, 360, .9), ("AASHO", 400, 560, .91), ("설계법", 600, 700, .9), ("15", 2030, 2060, .9)),
        _L(500, ("3.4", 264, 330, .9), ("AC60~70", 353, 560, .69), ("재료", 600, 690, .9), ("53", 2030, 2060, .9)),
        _L(600, ("4.4", 264, 330, .9), ("AC60~70", 353, 560, .87), ("53", 2030, 2060, .9)),
        _L(700, ("<", 248, 270, .9), ("참고문헌", 290, 480, .9), (">", 486, 500, .9), ("168", 2030, 2080, .9))]
_ch, _ex = opm._fill_toc_from_sparse(_std, _spl, _W)
_got = [" ".join(w["surface"] for w in ln["words"]) for ln in _std + _ex]
chk(_got[1] == "1.3 범위 2", "⑫ `OB`(흩어진 글 `(13`) → 앞 줄 `1.2` 다음 번호 `1.3`", _got[1])
chk(_got[2] == "5.1.2 평가 기준치 127", "⑫ 앞부분만 읽힌 제목(`평가기`)은 흩어진 글 제목(`평가기준치`)으로", _got[2])
chk(_got[3] == "2.2.2 AASHO 설계법 15", "⑫ 신뢰도 낮은 `NASHO` → 같은 자리 높은 신뢰도 `AASHO`", _got[3])
chk(_got[4] == "3.4 AC60~70 재료 53", "⑫ `AC60O~70` → 같은 쪽에서 확실히 읽힌 `AC60~70`, 끝 쉼표 `재료,` → `재료`", _got[4])
chk(_got[-1] == "< 참고문헌 > 168", "⑫ 표준 판독에 없는 꺾쇠 줄(`<참고문헌>`)을 더한다", _got[-1])
# 쪽 안 낱말로: 한 번 나온 `샤후관` ↔ 세 번 나온 `사후관`(첫소리 같고 `샤` 는 거기뿐) — 두 번뿐이면 고치지 않는다(`포장상태`/`포장설계` 둘)
_v = [[Wd(s, 0, 1)] for s in ["5.1", "샤후관측", "사후관측", "사후관측항목", "사후관측조사", "포장상태", "포장설계의", "포장설계법"]]
opm._fix_by_page_vocab(_v)
_vs = [x[0]["surface"] for x in _v]
chk(_vs[1] == "사후관측", "⑫ 쪽에 세 번 나온 `사후관측` 으로 `샤후관측` 을 고친다", _vs[1])
chk(_vs[5] == "포장상태", "⑫ 두 번 나온 `포장설계` 로는 `포장상태` 를 바꾸지 않는다", _vs[5])

print()
print("FAIL", len(fails), fails) if fails else print("ALL PASS")
sys.exit(1 if fails else 0)
