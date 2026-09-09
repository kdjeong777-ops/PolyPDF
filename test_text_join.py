# -*- coding: utf-8 -*-
"""260910: 끊긴 문장 잇기 (텍스트 창 SOT §3.7).

사용자 요청: "PDF 에서 원래 이어지는 문장인데 아랫줄로 끊겨 있는 경우 텍스트 창에서
이어서 쓰게 하는 규칙을 만들 수 있는지 검토해. 문장은 `.` `?` `!` 로 끝나지만
제목·표 제목·그림 제목은 그렇게 끝나지 않으므로 이를 고려해."

문장부호만으로는 안 된다 — 제목·캡션도 부호로 끝나지 않는다. 가장 강한 신호는
**줄이 오른쪽 여백까지 찼는가** 다(실측: 이어지는 본문 1.00, 제목·문단 마지막 줄 0.28~0.94).

검사 대상
  ① 오른쪽까지 찬 줄 + 부호 없이 끝남 → 잇는다
  ② 문장 끝 부호로 끝나면 잇지 않는다
  ③ 오른쪽이 안 찬 줄(제목·표 제목·그림 제목·문단 마지막 줄)은 잇지 않는다
  ④ 제목 스타일·표 줄(`" | "`)은 잇지 않는다
  ⑤ 목록 표시로 시작하는 줄은 앞에 붙이지 않는다
  ⑥ 내어쓰기(`(3) …` 다음 줄이 들여써진 것)는 허용한다
  ⑦ 잇는 법 — 원문이 빈칸으로 끝나면 빈칸, 한글끼리는 붙임, 영문 분철은 `-` 를 뗀다
  ⑧ 이은 줄은 **원래 줄들의 사각형을 모두** 갖는다
  ⑨ 끄면 종전대로 줄 단위
  ⑩ ★ 함정 둘 — 합친 사각형/다듬은 글로 다음 조건을 재지 않는다
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

fails = []
NL = chr(10)


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


import fitz
import test_fixtures as _fx
from viewer import text_extract2 as tx

root = Path(tempfile.mkdtemp(prefix="polypdf_join_"))
KR = _fx.KRFONT
tx.set_table_cache_db(None)


def row(text, x0, y0, x1, y1, style="body", kind="text", size=10.0):
    return {"text": text, "rect": (x0, y0, x1, y1), "style": style,
            "kind": kind, "size": size}


try:
    M = 400.0                       # 오른쪽 여백
    # 한 문단(세 줄) + 제목 + 표 줄을 손으로 만들어 조건을 하나씩 본다
    def para(lines, **kw):
        out = []
        y = 100.0
        for t, x1 in lines:
            out.append(row(t, 60.0, y, x1, y + 10.0, **kw))
            y += 12.0
        return out

    # ── ① 오른쪽까지 찬 줄은 잇는다 ─────────────────────────────
    r = tx.join_sentences(para([("첫째 줄이길게이어지고", M), ("둘째 줄로이어진다.", 300.0)]))
    chk(len(r) == 1, "① 오른쪽까지 찬 줄은 다음 줄과 이어진다", str([x["text"] for x in r]))
    chk(r[0]["text"] == "첫째 줄이길게이어지고둘째 줄로이어진다.",
        "⑦ 한글끼리는 붙여 쓴다", repr(r[0]["text"]))

    # ── ② 문장 끝 부호 ─────────────────────────────────────────
    for end in (".", "?", "!", "。"):
        r = tx.join_sentences(para([("앞 문장이끝났다" + end, M), ("새 문장이시작한다.", 300.0)]))
        chk(len(r) == 2, "② %r 로 끝나면 잇지 않는다" % end, str(len(r)))

    # ── ③ 오른쪽이 안 찬 줄 ────────────────────────────────────
    r = tx.join_sentences(para([("표 1 잔골재의 품질", 250.0), ("항목이이어진다.", 300.0)]))
    chk(len(r) == 2, "③ 짧은 줄(표 제목·그림 제목)은 잇지 않는다",
        str([x["text"] for x in r]))

    # ── ④ 제목·표 줄 ───────────────────────────────────────────
    rows = para([("제목처럼큰줄이길게", M)], style="title") + \
        para([("본문이이어진다.", 300.0)])
    rows[1]["rect"] = (60.0, 112.0, 300.0, 122.0)
    chk(len(tx.join_sentences(rows)) == 2, "④ 제목 줄은 잇지 않는다")
    rows = para([("가 | 나 | 다", M)]) + para([("본문이이어진다.", 300.0)])
    rows[1]["rect"] = (60.0, 112.0, 300.0, 122.0)
    chk(len(tx.join_sentences(rows)) == 2, "④ 표 줄(' | ')은 잇지 않는다")
    rows = para([("표 안의줄이길게이어지고", M)], kind="table") + \
        para([("본문이이어진다.", 300.0)], kind="table")
    rows[1]["rect"] = (60.0, 112.0, 300.0, 122.0)
    chk(len(tx.join_sentences(rows)) == 2, "④ 표 사각형 안의 줄은 잇지 않는다")

    # ── ⑤ 목록 표시 ────────────────────────────────────────────
    for head in ("1. 다음 항목", "가. 다음 항목", "① 다음 항목", "• 다음 항목",
                 "(1) 다음 항목", "- 다음 항목"):
        r = tx.join_sentences(para([("앞줄이길게이어지고", M), (head, 300.0)]))
        chk(len(r) == 2, "⑤ 목록으로 시작하면 앞에 붙이지 않는다 — %r" % head[:6],
            str(len(r)))

    # ── ⑥ 내어쓰기 ─────────────────────────────────────────────
    rows = [row("(3) 잔골재의 입도 분포가 문제가 없다면 사용하여야 ", 68.0, 100.0, M, 110.0),
            row("하며, 자연 모래는 사용하지 않는다.", 86.8, 112.0, 300.0, 122.0)]
    r = tx.join_sentences(rows)
    chk(len(r) == 1, "⑥ 목록 항목의 이어지는 줄이 들여써져 있어도 잇는다", str(len(r)))
    chk(r[0]["text"] == "(3) 잔골재의 입도 분포가 문제가 없다면 사용하여야 하며, 자연 모래는 사용하지 않는다.",
        "⑦ 원문이 빈칸으로 끝나면 빈칸 하나로 잇는다", repr(r[0]["text"]))
    rows = [row("앞줄이길게이어지고", 60.0, 100.0, M, 110.0),
            row("들여쓴새문단이다.", 120.0, 112.0, 300.0, 122.0)]
    chk(len(tx.join_sentences(rows)) == 2,
        "⑥ 목록이 아닌데 들여썼으면 새 문단으로 본다")

    # ── ⑦ 영문 분철 ────────────────────────────────────────────
    rows = [row("this is a long line with com-", 60.0, 100.0, M, 110.0),
            row("puter science inside.", 60.0, 112.0, 300.0, 122.0)]
    r = tx.join_sentences(rows)
    chk(r[0]["text"] == "this is a long line with computer science inside.",
        "⑦ 영문 분철은 '-' 를 떼고 붙인다", repr(r[0]["text"]))
    rows = [row("this is a long latin line", 60.0, 100.0, M, 110.0),
            row("that continues here.", 60.0, 112.0, 300.0, 122.0)]
    chk(tx.join_sentences(rows)[0]["text"] ==
        "this is a long latin line that continues here.",
        "⑦ 라틴끼리는 빈칸 하나")

    # ── ⑧ 사각형 ───────────────────────────────────────────────
    r = tx.join_sentences(para([("첫째 줄이길게이어지고", M), ("둘째 줄로이어진다.", 300.0)]))
    chk(len(r[0]["rects"]) == 2, "⑧ 원래 줄들의 사각형을 모두 갖는다",
        str(r[0].get("rects")))
    chk(r[0]["rect"] == (60.0, 100.0, M, 122.0), "⑧ 사각형은 그것들을 감싼다",
        str(r[0]["rect"]))

    # ── ⑩ 함정 — 합친 사각형으로 다음 조건을 재지 않는다 ─────────
    #   1·2줄은 오른쪽까지 찼고, 3줄은 짧다(문단 마지막). 4줄은 새 문단이다.
    rows = para([("가나다라마바사아자차카", M), ("타파하가나다라마바사아", M),
                 ("짧게끝나는마지막줄", 250.0), ("새 문단이시작한다.", 300.0)])
    r = tx.join_sentences(rows)
    chk(len(r) == 2, "⑩ 문단 마지막 줄에서 멈춘다(합친 사각형으로 재면 안 멈춘다)",
        str([x["text"][:14] for x in r]))
    chk(len(r[0]["rects"]) == 3, "⑩ 앞 문단은 세 줄", str(len(r[0]["rects"])))

    # ── ⑨ 끄면 줄 단위 ─────────────────────────────────────────
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    for i, t in enumerate(("이 문서의 첫 문단은 오른쪽 여백까지 이어지는 긴 줄이고",
                           "다음 줄로 계속 이어져서 한 문장을 이룬다.")):
        pg.insert_text((60, 120 + i * 20), t, fontsize=11, fontfile=KR, fontname="kr")
    src = root / "join.pdf"
    doc.save(str(src))
    doc.close()
    d = fitz.open(str(src))
    a = tx.page_lines(d, str(src), 0, tables="off", join_lines=False)
    b = tx.page_lines(d, str(src), 0, tables="off", join_lines=True)
    d.close()
    chk(len(a) == 2, "⑨ 끄면 종전대로 줄 단위", str(len(a)))
    chk(len(b) <= len(a), "⑨ 켜면 줄이 줄거나 같다", "%d → %d" % (len(a), len(b)))
    # 글자는 사라지지 않는다
    ca = "".join(x["text"] for x in a).replace(" ", "")
    cb = "".join(x["text"] for x in b).replace(" ", "")
    chk(ca == cb, "⑨ 이어도 글은 하나도 사라지지 않는다")

    # ── 창의 체크상자 ──────────────────────────────────────────
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from viewer.widgets.text_panel import TextPanel
    tp = TextPanel()
    chk(hasattr(tp, "cb_join") and tp.join_lines() is True,
        "⑨ 창에 '문장 잇기' 체크상자가 있고 기본이 켬")

finally:
    try:
        tx.close_cache()
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

print(NL + "=== " + ("ALL PASS" if not fails else "FAILURE (%d)" % len(fails)) + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
