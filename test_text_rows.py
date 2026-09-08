# -*- coding: utf-8 -*-
"""260908-7: 한 줄에 있는 조각을 잇는다 (텍스트 창 SOT §3.6 · §3.3 개정).

사용자 보고(260908): "`[ㅇㅇㅇㅇ ]` 에서 뒤의 `]` 만 아랫줄에 표시된다. 표 한 행에 칸이
여럿이면 칸 안의 내용 순서가 앞뒤로 바뀌거나 한 줄이 아니라 여러 줄로 표시된다."

원인: PyMuPDF 는 가로로 벌어진 글을 **각각 다른 `line`** 으로 준다. 종전에는 그것을
블록 순서대로 늘어놓기만 해서, 한 줄이 둘로 갈라지고 표 한 행의 칸이 흩어졌다.

검사 대상
  ① 같은 줄에 있는 조각은 **한 줄**로 이어진다 (`[ … ]` 가 갈라지지 않는다)
  ② 한 줄 안의 순서는 **왼쪽 → 오른쪽** (블록 순서가 아니다)
  ③ 넓게 벌어진 칸은 ` | ` 로 잇는다(표 한 행 = 한 줄, §3.3 과 같은 표기)
  ④ 좁게 벌어진 것은 공백 하나, 붙어 있는 것은 붙여 쓴다
  ⑤ **2단 쪽은 잇지 않는다** — 좌·우가 한 줄에 섞이면 안 된다
  ⑥ 표·서식을 2단으로 오해하지 않는다 — 가르는 기준은 **왼쪽 끝 정렬**
  ⑦ 표를 못 찾아도 한 행이 한 줄로 나온다(스캔본은 pdfplumber 가 표를 못 찾는다)
  ⑧ pdfplumber 가 칸을 잘못 뽑아도 **글을 잃지 않는다**(줄을 갈아 끼우지 않는다)
  ⑨ 대표 크기는 그 줄에서 글자가 가장 많은 조각의 것(제목/내용 판정, §3.4)
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


import fitz
from viewer import text_extract2 as tx

root = Path(tempfile.mkdtemp(prefix="polypdf_rows_"))
KRFONT = r"C:\Windows\Fonts\malgun.ttf"
SAMPLE_GUIDE = Path(r"C:\Claude\MPDF\_samples\24 아스팔트콘크리트포장시공지침.pdf")
SAMPLE_SCAN = Path(r"C:\Claude\MPDF\_samples\260908-인성배합설계.pdf.textfix.bak.pdf")


def make(name, draw, w=595, h=842):
    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    draw(page)
    dst = root / name
    doc.save(str(dst))
    doc.close()
    return dst


try:
    tx.set_table_cache_db(None)

    # ── ①②③④ 한 줄 잇기 ────────────────────────────────────────
    def draw_row(page):
        page.insert_text((60, 100), "[ Hot Asphalt Paving Mixture", fontsize=14)
        page.insert_text((250, 100), "]", fontsize=14)          # 같은 줄, 살짝 떨어짐
        # 표 한 행 — 넓게 벌어진 세 칸을 **오른쪽부터** 그려 블록 순서를 뒤집는다
        kr = dict(fontsize=10, fontfile=KRFONT, fontname="kr")
        page.insert_text((400, 200), "기 준", **kr)
        page.insert_text((240, 200), "시험방법", **kr)
        page.insert_text((70, 200), "항 목", **kr)
        page.insert_text((70, 240), "WC", **kr)
        page.insert_text((84, 240), "-3", **kr)                 # 붙어 있음
        page.insert_text((108, 240), "잔골재", **kr)             # 좁게 벌어짐(1.4배)

    one = make("one.pdf", draw_row)
    tx.close_cache()
    d = fitz.open(str(one))
    rows = tx.page_lines(d, str(one), 0, tables="off")
    d.close()
    texts = [r["text"] for r in rows]
    chk(any(t.startswith("[ Hot Asphalt") and t.rstrip().endswith("]") for t in texts),
        "① 같은 줄의 조각이 한 줄로 이어진다", str(texts[:1]))
    row2 = [t for t in texts if "항 목" in t]
    chk(len(row2) == 1, "② 표 한 행이 한 줄이 된다", str(row2))
    chk(bool(row2) and row2[0].index("항 목") < row2[0].index("시험방법")
        < row2[0].index("기 준"),
        "② 순서가 왼쪽 → 오른쪽 (그린 순서가 아니다)", str(row2))
    chk(bool(row2) and row2[0].count(" | ") == 2,
        "③ 넓게 벌어진 칸은 ' | ' 로 잇는다", str(row2))
    row3 = [t for t in texts if "WC" in t]
    chk(bool(row3) and "WC-3" in row3[0],
        "④ 붙어 있는 조각은 붙여 쓴다", str(row3))
    chk(bool(row3) and "WC-3 잔골재" in row3[0],
        "④ 좁게 벌어진 것은 공백 하나", str(row3))

    # ── ⑨ 대표 크기 ─────────────────────────────────────────────
    def draw_size(page):
        page.insert_text((70, 300), "이 줄은 본문 크기의 긴 문장입니다", fontsize=10,
                         fontfile=KRFONT, fontname="kr")
        page.insert_text((450, 300), "9", fontsize=30)      # 쪽수처럼 큰 한 글자

    sz = make("size.pdf", draw_size)
    tx.close_cache()
    d = fitz.open(str(sz))
    r = tx.page_lines(d, str(sz), 0, tables="off")
    d.close()
    line = [x for x in r if "긴 문장" in x["text"]]
    chk(len(line) == 1, "⑨ 한 줄로 이어졌다", str([x["text"] for x in r]))
    chk(bool(line) and line[0]["style"] == "body",
        "⑨ 대표 크기는 글자가 많은 쪽 — 큰 글자 하나에 끌려 제목이 되지 않는다",
        str(line[0]["style"]) if line else "")

    # ── ⑤ 2단 쪽 ────────────────────────────────────────────────
    def draw_2col(page):
        page.insert_text((60, 60), "A Full Width Title Across Columns", fontsize=18)
        for i in range(12):
            page.insert_text((60, 100 + i * 20), "left column line %d" % i, fontsize=10)
            page.insert_text((320, 100 + i * 20), "right column line %d" % i, fontsize=10)

    two = make("two.pdf", draw_2col)
    tx.close_cache()
    d = fitz.open(str(two))
    rows = tx.page_lines(d, str(two), 0, tables="off")
    d.close()
    t2 = [r["text"] for r in rows]
    chk(len(rows) == 25, "⑤ 2단 쪽은 좌·우를 잇지 않는다(25줄)", str(len(rows)) + "줄")
    chk(not any("left" in t and "right" in t for t in t2),
        "⑤ 한 줄에 두 단이 섞이지 않는다")
    chk(t2.index("left column line 11") < t2.index("right column line 0"),
        "⑤ 왼쪽 단을 먼저 다 읽고 오른쪽 단으로 간다")

    # ── ⑥ 표·서식을 2단으로 오해하지 않는다 ────────────────────────
    def draw_form(page):
        # 가운데가 비어 보이지만 **왼쪽 끝이 제각각**인 서식
        cells = [(52, 100, "제품종류"), (155, 100, "일반아스팔트혼합물"),
                 (330, 100, "구 분"), (440, 100, "요약표"),
                 (52, 130, "제품규격"), (200, 130, "WC-3"),
                 (330, 130, "작성자"), (470, 130, "홍길동"),
                 (52, 160, "작성일자"), (185, 160, "2026년 2월"),
                 (330, 160, "확인자"), (469, 160, "김철수"),
                 (52, 190, "골재종류"), (139, 190, "20mm 13mm"),
                 (335, 190, "믹서용량"), (455, 190, "2.0 Ton")]
        for x, y, t in cells:
            page.insert_text((x, y), t, fontsize=10,
                             fontfile=KRFONT, fontname="kr")

    form = make("form.pdf", draw_form)
    tx.close_cache()
    d = fitz.open(str(form))
    rows = tx.page_lines(d, str(form), 0, tables="off")
    d.close()
    tf = [r["text"] for r in rows]
    chk(len(rows) == 4, "⑥ 서식은 4행 = 4줄 (2단으로 오해하지 않는다)",
        str(len(rows)) + "줄")
    chk(all(t.count(" | ") == 3 for t in tf),
        "⑥ 한 행에 네 칸이 순서대로 들어간다", str(tf[:1]))

    # ── ⑦⑧ 실제 문서 ───────────────────────────────────────────
    if SAMPLE_GUIDE.exists():
        tx.close_cache()
        d = fitz.open(str(SAMPLE_GUIDE))
        rows = tx.page_lines(d, str(SAMPLE_GUIDE), 40, tables="lines")
        d.close()
        tg = [r["text"] for r in rows]
        chk(any("모래당량" in t and "KS F 2340" in t and "50 이상" in t for t in tg),
            "⑧ pdfplumber 가 칸을 놓쳐도 한 행이 온전히 남는다",
            str([t for t in tg if "모래당량" in t]))
        chk(any("항" in t and "시 험 방 법" in t and "기" in t for t in tg),
            "⑧ 머리행도 한 줄")
        chk(any(r["kind"] == "table" for r in rows),
            "⑧ 표 사각형 안의 줄에는 표시가 붙는다")
    else:
        print("SKIP - 지침 샘플 없음")

    if SAMPLE_SCAN.exists():
        tx.close_cache()
        d = fitz.open(str(SAMPLE_SCAN))
        chk(len(tx._tables(str(SAMPLE_SCAN), 1)) == 0,
            "⑦ 스캔본은 pdfplumber 가 표를 못 찾는다(괘선이 그림)")
        rows = tx.page_lines(d, str(SAMPLE_SCAN), 1, tables="lines")
        d.close()
        ts = [r["text"] for r in rows]
        chk(any("제품종튜" in t and "구 분" in t for t in ts),
            "⑦ 그래도 한 행이 한 줄로 나온다", str([t for t in ts if "제품종튜" in t]))
        chk(len(rows) < 60, "⑦ 조각 248개가 40여 줄로 모인다", str(len(rows)) + "줄")
        tx.close_cache()
        d = fitz.open(str(SAMPLE_SCAN))
        p1 = [r["text"] for r in tx.page_lines(d, str(SAMPLE_SCAN), 0, tables="off")]
        d.close()
        chk(any(t.strip().startswith("[ Hot Asphalt") and t.strip().endswith("]")
                for t in p1),
            "① 사용자가 본 그 줄 — '[ … ]' 가 한 줄이 된다", str(p1))
    else:
        print("SKIP - 스캔 샘플 없음")

finally:
    try:
        tx.close_cache()
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print(chr(10) + "=== " + ("ALL PASS" if not fails else "FAILURE (" + str(len(fails)) + ")") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
