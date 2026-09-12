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

# ── ⑨ 뒤 글자에 덮인 빈칸은 지운다 (§3.6.10 ②) ─────────────────
#   구글 번역본 PDF 는 낱말 사이에 빈칸을 둘 찍는데, 둘째 것의 자리를 다음
#   글자가 그대로 덮는다 — 종이에는 한 칸으로 보인다.
dbl = [("근", 95.52, 103.21), (" ", 103.21, 105.09), (" ", 105.09, 106.96),
       ("몇", 105.09, 112.78)]
got = tx._line_text(ln(dbl, 8.37), True)
chk(got == "근 몇", "⑨ 덮인 빈칸은 지운다 — 한 칸만 남는다", repr(got))
chk(tx._line_text(ln(dbl, 8.37), False) == "근 몇",
    "⑨ 되살리기를 끄더라도 지운다 — 자리를 잰 사실이지 짐작이 아니다")
chk(tx.SPACE_COVERED == 0.5, "⑨ 파고드는 기준은 0.5pt")

#   일부러 넣은 두 칸은 겹치지 않으므로 남는다
wide = [("총", 0.0, 10.0), (" ", 10.0, 13.0), (" ", 13.0, 16.0), ("칙", 16.0, 26.0)]
keep = tx._line_text(ln(wide, 10.0), True)
chk(keep == "총  칙", "⑨ 겹치지 않는 두 칸은 그대로 둔다(`제1장 총  칙`)", repr(keep))

# ── ⑩ `\xa0` 도 빈칸이다 (§3.6.10 ③) ──────────────────────────
nb = [("성", 0.0, 10.0), ("\u00a0", 10.0, 13.0), ("힘", 13.0, 23.0)]
got = tx._line_text(ln(nb, 10.0), True)
chk(got == "성 힘", "⑩ NBSP 를 보통 빈칸으로 바꾼다", repr(got))
chk(" " in got and "\u00a0" not in got, "⑩ 바뀐 글에 NBSP 가 남지 않는다", repr(got))
chk("\u00a0" in tx._SPACE_LIKE and "\u202f" in tx._SPACE_LIKE,
    "⑩ 같은 부류의 빈칸도 함께 본다")
#   §3.7 이 '원문이 빈칸으로 끝났는가' 를 볼 수 있어야 한다 — 그래야 `성공에힘입어` 가 안 된다
tail = [("에", 0.0, 10.0), ("\u00a0", 10.0, 13.0)]
chk(tx._line_text(ln(tail, 10.0), True).endswith(" "),
    "⑩ 줄 끝의 NBSP 도 빈칸으로 남아 문장 잇기가 알아본다")

# ── ⑪ 도는 차례 — ③ → ② → ① (§3.6.10, 차례가 뒤집히면 여기서 드러난다) ──
#   NBSP 로 찍힌 두 칸 중 뒤엣것을 다음 글자가 덮는 줄. 세 단계가 제 차례로
#   돌아야만 `근 몇` 이 된다.
#     · ③ 이 늦으면  → `isspace()` 가 NBSP 를 놓쳐 덮인 칸이 안 지워진다
#     · ② 가 늦으면  → ① 이 없는 빈칸을 두고 빈틈을 재 낱말 경계를 잘못 잡는다
order = [("근", 95.52, 103.21), ("\u00a0", 103.21, 105.09),
         ("\u00a0", 105.09, 106.96), ("몇", 105.09, 112.78)]
got = tx._line_text(ln(order, 8.37), True)
chk(got == "근 몇", "⑪ 세 단계가 제 차례로 돈다(NBSP → 덮인 칸 → 되살리기)", repr(got))

#   ② 를 건너뛰면 실제로 달라지는지 — 차례가 뜻이 있다는 증거
raw = [(c if c != "\u00a0" else " ", x0, x1) for c, x0, x1 in order]
chars = [(c, (x0, 0.0, x1, 8.37), 8.37) for c, x0, x1 in raw]
chk(tx._restore_spaces(chars) != "근 몇",
    "⑪ 덮인 칸을 안 지우면 결과가 달라진다 — 차례가 규칙의 일부다",
    repr(tx._restore_spaces(chars)))
chk(tx._restore_spaces(tx._drop_covered_spaces(chars)) == "근 몇",
    "⑪ 지운 뒤 되살리면 맞는다")

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
