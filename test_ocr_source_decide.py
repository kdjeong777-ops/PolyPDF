# -*- coding: utf-8 -*-
"""260912-2: 전면 그림 위의 **진짜 글**은 버리지 않는다 (단어학습 SOT §14.18·§14.18.1).

사용자 보고(사진): 구글 번역본 PDF 가 텍스트 창에서 `조 지 아 교 통 부 의` 처럼 글자마다
끊기고 본문이 큰 제목으로 나온다. 원인은 하나였다 — 이미지 점유율이 1.0 이라는 이유로
**멀쩡한 글자층을 버리고 배경 그림을 OCR** 하고 있었다.

가르는 신호는 '글자가 보이는가' 다. 스캐너가 얹은 OCR 층은 render mode 3(안 보임)이고,
번역본처럼 그려 넣은 글은 보인다. 표본 실측은 100% 대 0% 로 갈렸다.

여기서는 같은 성질의 PDF 를 직접 만들어 검사한다(CLAUDE.md §3 — 업무 파일 비의존).
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

import fitz
from viewer import text_extract2 as tx
from viewer.study import ocr as socr

KRFONT = next((f for f in (r"C:\Windows\Fonts\malgun.ttf",
                           r"C:\Windows\Fonts\gulim.ttc") if os.path.exists(f)), None)

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


LINES = ["조지아 교통부의 개방형 등급 마찰 코스 개발 진행 상황",
         "고속도로 운전자의 안전을 강화하기 위해 교통부는 최첨단 포장도로를",
         "지속적으로 사용해 왔습니다. 개구마찰층은 수막현상을 줄입니다.",
         "본 논문의 내용은 교통연구기록 1616에 실린 논문을 편집한 것입니다."]


def make(dst, invisible):
    """쪽 전체를 그림으로 깔고 그 위에 글을 얹은 PDF.

    `invisible=True` 면 스캐너가 덧씌운 OCR 층처럼 **안 보이게**(render mode 3),
    `False` 면 번역본처럼 **진짜로 그려 넣는다**.
    """
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 595, 842))
    pix.clear_with(245)                      # 전면 배경 그림 → 이미지 점유율 1.0
    pg.insert_image(pg.rect, pixmap=pix)
    for i, t in enumerate(LINES):
        pg.insert_text((60, 120 + i * 26), t, fontsize=11, fontfile=KRFONT,
                       fontname="kr", render_mode=3 if invisible else 0)
    doc.save(str(dst))
    doc.close()


root = tempfile.mkdtemp(prefix="polypdf_src_")
try:
    if not KRFONT:
        print("SKIP - 한글 글꼴이 없어 건너뜀")
        sys.exit(0)

    vis = os.path.join(root, "visible.pdf")     # 구글 번역본 꼴
    inv = os.path.join(root, "invisible.pdf")   # 스캔본 꼴
    make(vis, invisible=False)
    make(inv, invisible=True)

    dv, di = fitz.open(vis), fitz.open(inv)
    pv, pi = dv[0], di[0]

    # ── ① 둘 다 전면 그림이다 ─────────────────────────────────────
    cov_v = socr._image_coverage(pv)
    cov_i = socr._image_coverage(pi)
    chk(cov_v >= 0.6 and cov_i >= 0.6,
        "① 두 쪽 모두 이미지 점유율이 0.6 이상이다", "%.2f / %.2f" % (cov_v, cov_i))

    # ── ② 갈리는 신호는 '글자가 보이는가' ─────────────────────────
    chk(tx._is_ocr_layer(pv) is False, "② 그려 넣은 글은 '보이는 층' 이다")
    chk(tx._is_ocr_layer(pi) is True, "② 덧씌운 OCR 은 '보이지 않는 층' 이다")

    # ── ③ 판정 ────────────────────────────────────────────────────
    sv, wv = socr.decide_source(pv)
    si, wi = socr.decide_source(pi)
    chk(sv == "layer", "③ 보이는 글자층은 **버리지 않는다**", "%s %s" % (sv, wv))
    chk(si == "ocr", "③ 덧씌운 OCR 층은 종전대로 다시 읽는다", "%s %s" % (si, wi))
    chk(wi.get("reason") == "scanned-page", "③ 그 까닭이 'scanned-page' 다", str(wi))

    # ── ④ 글자가 아예 없는 전면 그림은 그대로 OCR ─────────────────
    blank = os.path.join(root, "blank.pdf")
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 595, 842))
    pix.clear_with(245)
    pg.insert_image(pg.rect, pixmap=pix)
    doc.save(blank)
    doc.close()
    db = fitz.open(blank)
    sb, wb = socr.decide_source(db[0])
    chk(sb == "ocr", "④ 글자가 없는 전면 그림은 여전히 OCR 이다", "%s %s" % (sb, wb))
    db.close()

    # ── ⑤ 텍스트 창이 그 글을 원문대로 보여 준다 ──────────────────
    tx.set_table_cache_db(None)
    tx.close_cache()
    rows = tx.page_lines(dv, vis, 0, tables="off", join_lines=False)
    got = [r["text"] for r in rows]
    chk(any(LINES[0] in g for g in got),
        "⑤ 제목 줄이 글자마다 끊기지 않고 원문 그대로다", str(got[:2]))
    chk(sum(1 for r in rows if r.get("style") == "title") <= 1,
        "⑤ 본문이 제목으로 뒤집히지 않는다",
        str([r["text"][:20] for r in rows if r.get("style") == "title"]))

    dv.close()
    di.close()
finally:
    tx.close_cache()
    shutil.rmtree(root, ignore_errors=True)

print()
print("=== ALL PASS ===" if not fails else "=== FAILURE (%d) ===" % len(fails))
for f in fails:
    print(" -", f)
sys.exit(1 if fails else 0)
