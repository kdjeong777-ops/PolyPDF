# -*- coding: utf-8 -*-
"""261108-31: 디지털 PDF 에서 문장 끝이 아닌데 줄 끝에서 끊긴 곳 — 텍스트 창·본문 읽기 (텍스트 창 SOT §3.7.16, 영상·음성 SOT §1.8 의 1).

사용자 지시: "디지털 pdf에서 문장의 끝이 아닌데 줄의 끝에서 끊어졌을 때 이것을 자연스럽게 읽을 수 있도록 텍스트창에서
보완하는 것을 검토해. … 원본의 깨짐이 없이, 원본의 글을 이을 수 있으면 그렇게 해도 되."
  A  본문 읽기가 창이 잇지 않은 줄을 이을 때 창의 규칙(§3.7.3) 그대로 — `취사` + `선택` 은 '취사선택'(종전 '취사 선택')
  B  `join_text` — 분철·한글·라틴·웹 주소가 `join_sentences` 와 같은 규칙
  C  2단 쪽의 보통 줄 거리는 단마다 잰다 — 왼쪽·오른쪽 단 줄이 번갈아 와도 본문 줄이 ⑥ 에 막히지 않는다(NAPA 1쪽 꼴)
  D  여러 단 항목 번호(`1.2.1 “…”라 함은`)의 내어쓴 둘째 줄을 잇는다 — 위 제목(`1.2 용어의 정의`)은 붙지 않는다
  E  Symbol 글꼴 글머리표(U+F0B7)의 내어쓴 둘째 줄을 잇는다 — 다음 글머리표 항목은 붙지 않는다
  F  점 하나짜리 값(`3.5 MPa …`)으로 시작하는 이어지는 줄은 여전히 잇는다(목록 표시로 보지 않는다)
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("POLYPDF_PROFILE", "test")
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fitz
from PyQt6.QtCore import QObject, QStandardPaths
from PyQt6.QtWidgets import QApplication
QStandardPaths.setTestModeEnabled(True)
app = QApplication.instance() or QApplication([])
from viewer import text_extract2 as tx

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def row(text, x0, y0, x1, size=10.7):
    return {"text": text, "style": "body", "kind": "text", "rect": (x0, y0, x1, y0 + size * 1.1), "size": size}


def joined(rows):
    return [r["text"] for r in tx.join_sentences(rows)]


# ── A: 본문 읽기 단위 ───────────────────────────────────────────────
FONT = next((p for p in (r"C:\Windows\Fonts\malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf") if os.path.exists(p)), None)
root = tempfile.mkdtemp(prefix="polypdf_joingap_")
try:
    if FONT:
        path = os.path.join(root, "ko.pdf")
        d = fitz.open()
        pg = d.new_page(width=595, height=842)
        # 두 줄 사이가 멀어(⑥) 창은 잇지 않는다 — 읽기는 문장부호로 끝나지 않은 줄을 다음 줄과 한 문장으로 잇는다
        pg.insert_text((72, 100), "이 지침의 내용은 현장 여건에 따라 취사", fontsize=11, fontfile=FONT, fontname="kr")
        pg.insert_text((72, 160), "선택되어야 한다.", fontsize=11, fontfile=FONT, fontname="kr")
        d.save(path); d.close()
        rows = tx.display_rows(path, 0)
        chk(len([r for r in rows if (r.get("text") or "").strip()]) == 2, "A 준비: 창은 두 줄을 잇지 않는다(⑥)",
            [r.get("text") for r in rows])
        from viewer.widgets import read_aloud as RA

        class _V:
            def current_file(self): return path

        class _MW(QObject):
            def _study_get_store(self): raise RuntimeError("no store")
        ra = RA.ReadAloud(_MW())
        ra.set_target(_V())
        units = ra._page_units(0)
        texts = [u[0] for u in units]
        chk(len(texts) == 1 and "취사선택" in texts[0].replace(" ", "") and "취사 선택" not in texts[0],
            "A 읽기 단위가 줄 끝에서 갈린 한글 낱말을 붙여 읽는다(종전 '취사 선택')", texts)
    else:
        print("SKIP - A 한글 글꼴 없음")
finally:
    shutil.rmtree(root, ignore_errors=True)

# ── B: join_text 는 §3.7.3 그대로 ────────────────────────────────────
chk(tx.join_text("the labora-", "tory is") == "the laboratory is", "B 분철을 떼고 붙인다", tx.join_text("the labora-", "tory is"))
chk(tx.join_text("design of", "asphalt") == "design of asphalt", "B 라틴 낱말 사이는 빈칸")
chk(tx.join_text("https://doi.org/10.1080/", "14680629") == "https://doi.org/10.1080/14680629", "B 끊긴 웹 주소는 붙인다")
chk(tx.join_text("Performance-", "Based") == "Performance-Based", "B 대문자로 이어지는 합성어는 붙임표를 남긴다")
k = tx.join_text("현장 여건에 따라 취사", "선택되어야 한다")
chk("취사선택" in k, "B 한글 낱말이 갈린 자리는 붙인다(말뭉치 §3.7.10, 못 물으면 붙임)", k)

# ── C: 2단 쪽 ────────────────────────────────────────────────────────
W = "word " * 9
left = [row(W + "goes on", 54, 300 + 13 * i, 300) for i in range(9)] + [row("end of left.", 54, 300 + 13 * 9, 200)]
right = [row(W + "keeps going", 317, 300.1 + 13 * i, 565) for i in range(9)] + [row("end of right.", 317, 300.1 + 13 * 9, 450)]
out = joined(left + right)
chk(len(out) == 2, "C 2단 쪽 — 단마다 한 문단(종전: 왼쪽·오른쪽 줄이 번갈아 보통 줄 거리가 작게 잡혀 줄마다 끊겼다)",
    "%d줄 · 보통 줄 거리 %.1f(단마다) / %.1f(쪽 전체)" % (len(out), tx._median_pitch(left + right, tx._column_extents(left + right)),
                                               tx._median_pitch(left + right)))

# ── D: 여러 단 항목 번호의 내어쓰기 ───────────────────────────────────
D = [row("1.2 용어의 정의", 74, 247, 155, 11.5),
     row("1.2.1 “감독자”라 함은 “건설기술진흥법 제49조”의 규정에 의하여 발주청장이 임명", 79, 274, 461),
     row("한 건설공사의 감독자를 말한다. 다만 건설사업관리를 하게 하는 공사에 있어서는", 104, 294, 461),
     row("당해 공사의 감리를 수행하는 책임건설사업관리기술자를 말한다.", 104, 314, 399),
     row("1.2.2 “건설기술용역업자”라 함은 “건설기술 진흥법 제2조”에 따른 건설기술용역(다", 79, 338, 466),
     row("른 사람의 위탁을 받아 건설기술에 관한 업무를 수행하는 것)을 영업으로 하는", 104, 358, 466),
     row("자로서 동법 제26조에 따라 등록한 자를 말한다.", 104, 378, 290)]
out = joined(D)
chk(len(out) == 3 and out[0] == "1.2 용어의 정의", "D 항목 번호 줄과 내어쓴 줄을 잇고 제목은 따로(3줄)", out)
chk(any(t.startswith("1.2.1") and t.endswith("말한다.") for t in out), "D 1.2.1 항목이 한 줄로", out)

# ── E: Symbol 글꼴 글머리표 ─────────────────────────────────────────
B = chr(0xF0B7)
E = [row(B + " Effectiveness of bond: For whitetoppings that rely on existing pavement", 72, 228, 543, 12),
     row("through bonding, properly achieved bond will promote monolithic behavior and", 90, 243, 543, 12),
     row("pavement) will carry the traffic load as one structure.", 90, 257, 348, 12),
     row(B + " Existing pavement condition: Since UTWs and TWTs rely on the existing", 72, 271, 543, 12),
     row("pavement to carry the load, its condition matters.", 90, 285, 330, 12)]
out = joined(E)
chk(len(out) == 2 and all(t.startswith(B) for t in out), "E 글머리표 항목마다 한 줄 — 내어쓴 줄은 잇고 다음 항목은 따로", out)
chk(tx._starts_list(B + " Loss of bond"), "E 사용자 영역 글머리표는 목록 표시(⑦)")

# ── F: 점 하나짜리 값으로 시작하는 줄 ────────────────────────────────
F = [row("the binder content shall not be less than the value of about", 54, 300, 540),
     row("3.5 MPa for the surface course and the base course mixtures.", 54, 313, 400),
     row("other body line here", 54, 326, 300), row("and one more line.", 54, 339, 260)]
out = joined(F)
chk(out[0].endswith("mixtures.") and "about 3.5 MPa" in out[0], "F `3.5 MPa …` 로 시작하는 줄은 이어지는 글", out)
chk(not tx._HANG_HEAD.match("3.5 MPa for") and tx._HANG_HEAD.match("1.2.1 “감독자”"), "F 항목 번호는 점 둘 이상만")

# ── G: 글머리표 조각이 커도 줄 크기는 본문 크기(⑧) ─────────────────────
gd = fitz.open()
gp = gd.new_page(width=595, height=842)
for k in range(6):                                   # 보통 줄 거리를 잡아 줄 본문
    gp.insert_text((80, 80 + 14 * k), "plain body text line number %d of the page for pitch" % k, fontsize=8.8)
gp.insert_text((72, 200), "•", fontsize=12)
gp.insert_text((80, 200), "Verify the continuous grade of the asphalt binder (including GRP and", fontsize=8.8)
gp.insert_text((80, 214), "phase angle at 10 MPa) received at the plant before start of production.", fontsize=8.8)
grows = tx.page_lines(gd, "g.pdf", 0, tables="off")
gt = [r["text"] for r in grows]
chk(any("including GRP and phase angle" in t for t in gt), "G 큰 글머리표 조각이 있어도 항목의 둘째 줄을 잇는다(⑧)", gt)
gd.close()

# ── H: 일반 논문 꼴(cao 표본) — 왼쪽 세로 띠 · 가로 줄로 두른 1단 초록 · 그 아래 2단 본문 · 단 넘김 ──────────────
LEFT_LINES = ["The conventional asphalt pavements have a low skid resistance",
              "according to statistics of more than thirty thousand cases of",
              "accidents collected from seven expressways in the country, and",
              "in wet pavement condition due to the existence of water film",
              "on its surface, which could result in hydroplaning and spray",
              "and the situation could be more severe in mountainous areas",
              "where the research and application of porous asphalt were sus-"]
RIGHT_LINES = ["pended for years. With the increasing needs for high quality",
               "freeways and the development of modified bitumen in recent",
               "years, porous asphalt became attractive and several research",
               "programs resumed. This paper deals with some important findings",
               "about material study of porous asphalt especially with respect",
               "to the relationships among gradation, air void and drainage",
               "efficiency, and the binder requirements for the pavement."]
hd = fitz.open()
hp = hd.new_page(width=612, height=792)
hp.draw_line((42, 150), (570, 150)); hp.draw_line((42, 300), (570, 300))         # 초록을 두른 전폭 가로 줄
for k in range(8):
    hp.insert_text((42, 170 + 13 * k), "Abstract line %d with many advantages such as high skid resistance, low noise, and less splash and spray in the rain" % k,
                   fontsize=9.5)
hp.insert_text((8, 690), "Downloaded from library.example.org by Some Institute of Civil Engineering and Building Technology on 10/24/24. Copyright reserved; for personal use only.",
               fontsize=8, rotate=90)                                             # 왼쪽 가장자리의 세로 글 한 줄
def justify(lines, n, last_too=False):
    """양쪽 정렬 — 고정폭 글꼴(cour)로 줄마다 정확히 n 글자(낱말 사이 빈칸을 늘려서). 논문 본문 꼴."""
    out = []
    for k, ln in enumerate(lines):
        w = ln.split()
        if (k == len(lines) - 1 and not last_too) or len(w) < 2:
            out.append(ln)
            continue
        gaps, extra = len(w) - 1, n - sum(len(x) for x in w)
        s = ""
        for i, x in enumerate(w[:-1]):
            s += x + " " * (extra // gaps + (1 if i < extra % gaps else 0))
        out.append(s + w[-1])
    return out


for k, t in enumerate(justify(LEFT_LINES, 56, last_too=True)):     # 왼쪽 단 마지막 줄도 끝까지 찼다(문장이 오른쪽 단으로 넘어감)
    hp.insert_text((42, 340 + 12 * k), t, fontsize=7.5, fontname="cour")
hp.insert_text((42, 640), "1Professor, Research Institute of Highway, Beijing, China.", fontsize=6.5)   # 각주
for k, t in enumerate(justify(RIGHT_LINES, 56)):
    hp.insert_text((317, 340 + 12 * k), t, fontsize=7.5, fontname="cour")
hpath = os.path.join(tempfile.mkdtemp(prefix="polypdf_cao_"), "paper.pdf")
hd.save(hpath); hd.close()
hrows = tx.display_rows(hpath, 0)
ht = [r.get("text") or "" for r in hrows]
chk(not any("Downloaded" in t.replace(" ", "") for t in ht), "H 왼쪽 가장자리 세로 글 한 줄은 뺀다(§3.5.2 (가-2))", ht)
chk(not any(" | " in t and ("skid" in t or "freeways" in t or "pavements" in t) for t in ht)
    and not any("conventional" in t and "freeways" in t and t.index("freeways") < t.index("sus") for t in ht if "sus" in t),
    "H 가로 줄 아래 2단 본문 — 좌·우 단 줄이 한 줄로 붙지 않는다", ht)
body_left = [t.replace(" ", "") for t in ht if t.startswith("The conventional")]   # 고정폭 양쪽 정렬 줄은 빈칸이 빠져 나온다 — 빈칸 없이 비교
chk(body_left and "mountainousareaswhere" in body_left[0] and "casesofaccidents" in body_left[0], "H 왼쪽 단 줄을 문장으로 잇는다(이웃 여백 — 전폭 초록과 같은 왼쪽 끝이어도)", ht)
chk(body_left and "suspendedforyears." in body_left[0], "H 왼쪽 단 끝 → 오른쪽 단 처음으로 넘어간 문장을 잇는다(사이에 각주)", ht)
chk(any(t.startswith("1Professor") for t in ht), "H 각주는 본문에 붙지 않는다", ht)
if FONT:
    from viewer.widgets import read_aloud as RA2

    class _V2:
        def current_file(self): return hpath

    class _MW2(QObject):
        def _study_get_store(self): raise RuntimeError("no store")
    ra2 = RA2.ReadAloud(_MW2()); ra2.set_target(_V2())
    said = " ".join(u[0] for u in ra2._page_units(0))
    chk("Downloaded" not in said.replace(" ", "") and "suspendedforyears" in said.replace(" ", ""), "H 읽기는 띠 글을 읽지 않고 단 넘김 문장을 한 문장으로", said[:200])

print("\n=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
sys.stdout.flush()
os._exit(1 if fails else 0)
