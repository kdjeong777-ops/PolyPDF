# -*- coding: utf-8 -*-
"""261008-5: 다단 양면 제본 여백을 종이 넘기는 축에 맞춘다 (마스터 §11.10.1, 사용자 결정).

사용자 결정: "양면 제본 여백은 종이 넘기는 방향으로 맞춰"

A. gutter_edge 표 — 세로 시트: 긴 쪽=좌우·짧은 쪽=위아래 / 가로 시트: 긴 쪽=위아래·짧은 쪽=좌우,
   좌우는 홀수 왼쪽·짝수 오른쪽, 위아래는 홀수 위·짝수 아래, 단면은 언제나 왼쪽, 옛 스타일(duplex:True)=긴 쪽
B. 실제 배치(_grid_layout) — 여백이 그 가장자리에서 칸을 밀어낸다(2-up 가로 시트, 4-up 세로 시트)
C. 실제 다단 PDF(build_twoup) — 2-up·양면(긴 쪽)·제본 여백이면 홀수 시트는 위, 짝수 시트는 아래가 비고
   좌우 여백은 그대로(종전: 좌우로 들어가 실제 묶음과 어긋났다)
"""
import os, sys, tempfile, shutil, faulthandler
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
faulthandler.dump_traceback_later(120, exit=True)
from pathlib import Path

import fitz

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = Path(tempfile.mkdtemp(prefix="polypdf_gutter_"))
try:
    from viewer.twoup import gutter_edge, _grid_layout, build_twoup
    P, L = (595, 842), (842, 595)                       # 세로 / 가로 시트
    S = lambda c: ({} if c == "none" else {"duplex": True, "duplex_side": c})
    want = {
        ("P", "long", 1): "left", ("P", "long", 2): "right",
        ("P", "short", 1): "top", ("P", "short", 2): "bottom",
        ("L", "long", 1): "top", ("L", "long", 2): "bottom",
        ("L", "short", 1): "left", ("L", "short", 2): "right",
    }
    got = {(o, c, n): gutter_edge(S(c), *(P if o == "P" else L), n) for (o, c, n) in want}
    chk(got == want, "A 시트 방향 × 긴/짧은 쪽 × 홀짝 → 넘기는 축의 가장자리", str({k: v for k, v in got.items() if v != want[k]}))
    chk(all(gutter_edge({}, *d, n) == "left" for d in (P, L) for n in (1, 2)), "A 단면은 언제나 왼쪽(종전 그대로)")
    chk(gutter_edge({"duplex": True}, *P, 2) == "right", "A 옛 스타일 duplex:True = 긴 쪽")

    # ── B. 실제 배치 ──
    src_p = fitz.Rect(0, 0, 595, 842)                   # 세로 원본 → 2-up 은 가로 시트
    G = 40.0

    def boxes(nup, side, sheet, g):
        s = {"nup": nup, "gutter": g}
        s.update(S(side))
        ow, oh, bx = _grid_layout(src_p, s, sheet)
        return ow, oh, bx

    for nup, side, orient in ((2, "long", "가로"), (2, "short", "가로"), (4, "long", "세로"), (4, "short", "세로")):
        for sheet in (1, 2):
            ow, oh, b0 = boxes(nup, side, sheet, 0)
            _o, _h, b1 = boxes(nup, side, sheet, G)
            edge = gutter_edge(S(side), ow, oh, sheet)
            x0d = b1[0].x0 - b0[0].x0; y0d = b1[0].y0 - b0[0].y0
            x1d = b1[-1].x1 - b0[-1].x1; y1d = b1[-1].y1 - b0[-1].y1
            moved = {"left": x0d > 0 and y0d == 0 and y1d == 0, "right": x1d < 0 and x0d == 0 and y0d == 0,
                     "top": y0d > 0 and x0d == 0 and x1d == 0, "bottom": y1d < 0 and y0d == 0 and x0d == 0}[edge]
            chk(moved, f"B {nup}-up({orient} 시트)·{side}·시트{sheet}: 여백이 '{edge}' 에서 칸을 밀어낸다",
                f"dx0={x0d:.1f} dy0={y0d:.1f} dx1={x1d:.1f} dy1={y1d:.1f}")

    # ── C. 실제 다단 PDF ──
    src = root / "원본.pdf"
    d = fitz.open()
    for i in range(8):
        d.new_page(width=595, height=842).insert_text((72, 72), f"p{i + 1}")
    d.save(str(src)); d.close()

    def first_cells(g, side):
        out = root / f"nup_{g}_{side}.pdf"
        s = {"nup": 2, "gutter": g, "make_cover": False, "make_toc": False, "footer_pos": "none"}
        s.update(S(side))
        build_twoup([{"type": "pdf", "path": str(src), "name": "원본"}], s, str(out),
                    log=lambda *a, **k: True, progress=lambda *a, **k: True)
        res = []
        with fitz.open(str(out)) as nd:
            for pg in nd:
                ims = pg.get_image_info() or []
                rects = [fitz.Rect(i["bbox"]) for i in ims]
                if not rects:                         # 벡터로 들어갔으면 글자 상자로
                    rects = [fitz.Rect(b[:4]) for b in pg.get_text("blocks")]
                r = fitz.Rect(rects[0])
                for x in rects[1:]:
                    r |= x
                res.append((pg.rect, r))
        return res

    base = first_cells(0, "long")
    withg = first_cells(G, "long")
    (pr1, a1), (pr2, a2) = base[0], base[1]
    (_q1, b1), (_q2, b2) = withg[0], withg[1]
    chk(pr1.width > pr1.height, "준비 — 2-up 은 가로 시트")
    # 칸 안 내용은 가운데 맞춤이라 칸이 줄면 내용도 조금 줄고 좌우로 움직인다 — 위아래 쏠림으로 판정한다
    chk(b1.y0 - a1.y0 > G / 4, "C 2-up·양면(긴 쪽) 홀수 시트: 내용이 아래로 밀린다(위에 제본 여백)", f"{a1} → {b1}")
    chk(b2.y0 - a2.y0 < 0.5, "C 짝수 시트: 내용이 아래로 밀리지 않는다(아래에 제본 여백)", f"{a2} → {b2}")
except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
