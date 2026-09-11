# -*- coding: utf-8 -*-
"""260911-1: 글자층에 빈칸이 없는 PDF — 글자 자리로 띄어쓰기 되살리기 (텍스트 창 SOT §3.6.10).

사용자 보고: **아스팔트 지침개정 보고서의 텍스트 창 내용이 거의 대부분 한글 띄어쓰기가
하나도 없다.** 아래아한글이 빈칸 글자를 아예 넣지 않았기 때문이다.
여기서는 같은 성질의 PDF 를 직접 만들어 검사한다 — 업무 파일에 기대지 않는다(CLAUDE.md §3).
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

import fitz
from viewer import text_extract2 as tx

KRFONT = next((f for f in (r"C:\Windows\Fonts\malgun.ttf",
                           r"C:\Windows\Fonts\gulim.ttc") if os.path.exists(f)), None)

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


def ln(chars, size=11.0):
    """[(글자, x0, x1)] → `_line_text` 가 받는 줄 dict."""
    spans = [{"size": size, "text": "".join(c for c, _a, _b in chars),
              "chars": [{"c": c, "bbox": (x0, 0.0, x1, size)} for c, x0, x1 in chars]}]
    return {"spans": spans, "wmode": 0, "dir": (1.0, 0.0)}


def run(word_gap, text, size=11.0, kern=0.6):
    """낱말 사이만 `word_gap` 만큼 벌린 줄. `text` 의 빈칸이 낱말 경계다(그 자리가 지워진다)."""
    chars, x = [], 0.0
    for i, c in enumerate(text):
        if c == " ":
            x += word_gap
            continue
        if i and text[i - 1] != " ":
            x += kern
        chars.append((c, x, x + size))
        x += size
    return ln(chars, size)


# ── ① 빈칸이 지워진 한글 줄 ────────────────────────────────────
want = "기존 배수성 혼합물 지침 중 합성입도의 상한"
got = tx._line_text(run(5.5, want), True)
chk(got == want, "① 낱말 사이 빈틈으로 띄어쓰기가 돌아온다", got)
chk(tx._line_text(run(5.5, want), False) == want.replace(" ", ""),
    "① 되살리지 않을 때는 원래 그대로(빈칸 없음)")

# ── ② 문턱 — 0.25 × 글자크기 ───────────────────────────────────
chk(tx.SPACE_GAP == 0.25, "② 문턱은 글자크기의 0.25")
narrow = tx._line_text(run(2.0, "가나 다라"), True)      # 2.0 / 11 = 0.18 → 미달
chk(narrow == "가나다라", "② 문턱보다 좁은 빈틈은 낱말 경계가 아니다", narrow)
wide = tx._line_text(run(3.0, "가나 다라"), True)        # 3.0 / 11 = 0.27 → 넘음
chk(wide == "가나 다라", "② 문턱을 넘기면 빈칸을 넣는다", wide)

# ── ③ 자간 벌리기(균등분할)는 손대지 않는다 ────────────────────
spread = run(5.5, "품 질 관 리 실 장")        # 모든 빈틈이 후보
chk(tx._line_text(spread, True) == "품질관리실장",
    "③ 모든 글자가 벌어진 줄은 낱말 경계가 아니다 — 그대로 둔다",
    tx._line_text(spread, True))
chk(tx.SPACE_DENSE == 0.80, "③ 거르는 비율은 0.80")

# ── ④ 부호 앞뒤에는 넣지 않는다 ────────────────────────────────
pct = tx._line_text(run(5.5, "질량 %"), True)
chk(pct == "질량%", "④ 닫는 부호(%) 앞에는 빈칸을 넣지 않는다", pct)
par = tx._line_text(run(5.5, "( 가나"), True)
chk(par == "(가나", "④ 여는 부호 뒤에도 넣지 않는다", par)

# ── ⑤ 이미 빈칸이 있는 줄은 늘어나지 않는다 ────────────────────
lat = [("H", 0.0, 7.0), ("i", 7.0, 10.0), (" ", 10.0, 13.5),
       ("t", 13.5, 17.0), ("o", 17.0, 24.0)]
out = tx._line_text(ln(lat, 10.0), True)
chk(out == "Hi to", "⑤ 빈칸 글자가 있으면 그 자리는 건드리지 않는다", out)
chk(out.count(" ") == 1, "⑤ 빈칸이 둘로 늘지 않는다", out)

# ── ⑥ 세로쓰기·돌린 줄은 가로 빈틈이 뜻을 잃는다 ───────────────
vert = run(5.5, "가나 다라")
vert["wmode"] = 1
chk(tx._line_text(vert, True) == "가나다라", "⑥ 세로쓰기 줄은 건드리지 않는다")
rot = run(5.5, "가나 다라")
rot["dir"] = (0.0, 1.0)
chk(tx._line_text(rot, True) == "가나다라", "⑥ 돌린 줄도 건드리지 않는다")

# ── ⑦ rawdict 의 span 에는 `text` 가 없다 — 글이 사라지면 안 된다 ──
raw_only = run(5.5, "가나 다라")
for sp in raw_only["spans"]:
    sp.pop("text")
chk(tx._line_text(raw_only, False) == "가나다라",
    "⑦ 되살리기를 건너뛰어도 글은 돌려준다(이걸 놓쳐 OCR 쪽 줄이 통째로 사라졌다)",
    tx._line_text(raw_only, False))
chk(tx._line_text(raw_only, True) == "가나 다라", "⑦ 되살리면 물론 띄어쓴다")

# ── ⑧ 진짜 PDF 로 끝까지 ───────────────────────────────────────
root = tempfile.mkdtemp(prefix="polypdf_space_")
try:
    if not KRFONT:
        print("SKIP - ⑧ 한글 글꼴이 없어 PDF 검사를 건너뜀")
    else:
        WORDS = ["기존", "배수성", "혼합물", "지침", "합성입도의"]
        SIZE = 11.0

        def build(dst, invisible=False):
            doc = fitz.open()
            pg = doc.new_page(width=595, height=842)
            if invisible:            # OCR 층처럼 — 그림 위에 보이지 않는 글자
                pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 595, 842))
                pix.clear_with(255)
                pg.insert_image(pg.rect, pixmap=pix)
            x = 60.0
            for w in WORDS:          # 낱말 사이를 **빈칸 없이** 벌려 놓는다
                for c in w:
                    pg.insert_text((x, 120), c, fontsize=SIZE, fontfile=KRFONT,
                                   fontname="kr", render_mode=3 if invisible else 0)
                    x += SIZE
                x += SIZE * 0.5      # 0.5 × 글자크기 = 지워진 빈칸 자리
            doc.save(str(dst))
            doc.close()

        plain = os.path.join(root, "plain.pdf")
        build(plain)
        tx.set_table_cache_db(None)
        tx.close_cache()
        d = fitz.open(plain)
        chk(tx._is_ocr_layer(d.load_page(0)) is False, "⑧ 보이는 글자층이다")
        rows = tx.page_lines(d, plain, 0, tables="off", join_lines=False)
        d.close()
        line = rows[0]["text"] if rows else ""
        chk(line == " ".join(WORDS), "⑧ 텍스트 창 줄이 원문대로 띄어쓴다", repr(line))

        # OCR 글자층은 건너뛴다 — 그쪽은 §3.6.2 가 따로 맡는다
        scan = os.path.join(root, "scan.pdf")
        build(scan, invisible=True)
        tx.close_cache()
        d2 = fitz.open(scan)
        chk(tx._is_ocr_layer(d2.load_page(0)) is True, "⑧ 보이지 않는 OCR 층으로 알아본다")
        rows2 = tx.page_lines(d2, scan, 0, tables="off", join_lines=False)
        d2.close()
        joined = " ".join(r["text"] for r in rows2)
        chk(bool(joined.strip()), "⑧ OCR 층에서도 글이 사라지지 않는다", repr(joined))
        chk("".join(WORDS) in joined.replace(" ", ""),
            "⑧ OCR 층의 글자가 모두 남아 있다", repr(joined))
finally:
    tx.close_cache()
    shutil.rmtree(root, ignore_errors=True)

print()
print("=== ALL PASS ===" if not fails else "=== FAILURE (%d) ===" % len(fails))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
