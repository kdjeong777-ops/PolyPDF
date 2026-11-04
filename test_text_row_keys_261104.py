# -*- coding: utf-8 -*-
"""텍스트 창 줄(dict)의 키는 한 뜻만 (261104-11, 텍스트 창 SOT §5.1.5).

261103-15 가 이은 줄의 '원래 줄마다의 글' 을 `parts` 에 넣었는데, 같은 이름이 고침 저장소·글자층 쓰기에서는 (자리, 글) 짝 목록이라
이은 줄이 있는 쪽의 [PDF 에 반영]·Word(모양 그대로)가 `too many values to unpack` 으로 실패했다. 글 목록은 `line_texts` 로.
A. 이은 줄 — `line_texts` 는 글 목록(상자 수만큼), 줄에 `parts` 가 있으면 늘 (자리, 글) 짝
B. 글자층 쓰기 계획(`text_apply.plan_layer_lines`)이 이은 줄에서도 깨지지 않는다
C. 고침 저장소가 합친 줄(`parts` 짝)도 그대로 계획된다
"""
import os, sys, tempfile, shutil
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = tempfile.mkdtemp(prefix="polypdf_rowkeys_")
try:
    import fitz
    from test_fixtures import KRFONT
    from viewer import text_extract2 as tx, text_apply
    src = os.path.join(root, "p.pdf")
    d = fitz.open()
    pg = d.new_page(width=500, height=700)
    kw = dict(fontsize=12, fontfile=KRFONT, fontname="kr") if KRFONT else dict(fontsize=12)
    LINES = ["Association) in 1952 published a manual", "Diagnostic and Statistical Manual of Mental",
             "Disorders and many other disorders were", "added and removed until the fifth edition."]
    for i, t in enumerate(LINES):
        pg.insert_text((60, 120 + i * 18), t, **kw)
    d.save(src); d.close()
    doc = fitz.open(src)
    rows = tx.page_lines(doc, src, 0, tables="off")
    doc.close()
    joined = max(rows, key=lambda r: len(r.get("rects") or []))

    # A
    lt = joined.get("line_texts") or []
    chk(len(lt) >= 2 and len(lt) == len(joined.get("rects") or []) and all(isinstance(t, str) for t in lt),
        "A 이은 줄의 원래 줄 글은 line_texts(글 목록)", repr(lt)[:120])
    bad = [r.get("parts") for r in rows if r.get("parts") is not None
           and not all(isinstance(p, (tuple, list)) and len(p) == 2 for p in r["parts"])]
    chk(not bad, "A 줄의 parts 는 늘 (자리, 글) 짝 — 한 키에 두 뜻을 두지 않는다", repr(bad)[:160])

    # B
    try:
        plan = text_apply.plan_layer_lines(rows)
        ok = bool(plan)
    except Exception as e:                # noqa: BLE001
        ok, plan = False, str(e)
    chk(ok, "B 글자층 쓰기 계획이 이은 줄에서 깨지지 않는다", str(plan)[:120])

    # C — 고침 저장소가 합친 줄(짝)
    merged = {"text": "Hello world", "rect": [60, 100, 300, 140],
              "parts": [((60, 100, 200, 118), "Hello"), ((60, 120, 300, 140), "world")]}
    try:
        plan = text_apply.plan_layer_lines([merged])
        ok = len(plan) == 2
    except Exception as e:                # noqa: BLE001
        ok, plan = False, str(e)
    chk(ok, "C 합친 고침 줄은 원래 자리로 나눠 계획", str(plan)[:120])
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("ALL PASS" if not fails else "FAILURES: %d" % len(fails))
sys.exit(1 if fails else 0)
