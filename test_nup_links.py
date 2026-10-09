# -*- coding: utf-8 -*-
"""261009-7: 다단 축소에서 하이퍼링크가 따라간다 (마스터 §4.7.13).

사용자 지시 '다단 축소에서 하이퍼링크 거동 측정해' → 실측 결과 **전부 사라졌다**
(URI 4 → 0, GOTO 1 → 0). 까닭은 `_place_page` 가 `show_pdf_page` 로 쪽을 넣기 때문이다 —
그건 쪽 내용을 Form XObject 로 **그리기만** 해 링크·주석을 옮기지 않는다. 이어 사용자가
'URI + GOTO 둘 다' 살리기로 결정했다.

고친 법: `_LinkPlan` 이 쪽을 놓을 때마다 '원본 → 시트' 변환을 적어 두고, 조립이 끝난 뒤
한 번에 다시 넣는다. **두 패스여야 하는 까닭은 GOTO** — 가는 쪽이 아직 놓이지 않았을 수 있다.

검사 대상
  ① 2-up 에서 URI·GOTO 가 **모두 남는다**(이 검사의 본령)
  ② 자리 — 축소 배율·칸 위치가 그대로 반영된다(계산값과 1pt 이내)
  ③ GOTO 가 **가는 쪽이 놓인 시트**를 가리킨다
  ④ ★ 맞쪽 인쇄(`facing_first`)로 맨 앞에 빈 쪽이 끼어도 쪽이 밀리지 않는다
  ⑤ ★ 표지·목차가 앞에 붙어도 제 쪽에 붙는다
  ⑥ 크롭·cover 로 잘려 나간 자리의 링크는 **버린다**(엉뚱한 곳에 남기지 않는다)
  ⑦ 여러 파일을 묶어도 파일마다 따라간다 — GOTO 는 **자기 파일 안**을 가리킨다
  ⑧ 4-up·stretch 에서도 남는다
  ⑨ 돌아간(/Rotate 90) 쪽에서도 자리가 맞는다
  ⑩ 링크가 없는 문서는 그대로(군더더기 없음)
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz

fails = []


def chk(ok, what, got=""):
    print(("PASS - " if ok else "FAIL - ") + what + (" " + str(got) if got else ""))
    if not ok:
        fails.append(what)


root = tempfile.mkdtemp(prefix="nuplinks_")


def links_of(path):
    d = fitz.open(path)
    try:
        return [(i, lk.get('kind'), lk.get('uri'), lk.get('page'),
                 fitz.Rect(lk['from']))
                for i in range(d.page_count) for lk in d[i].get_links()]
    finally:
        d.close()


def make_src(name, pages=4, rotate=0, link_y=120):
    """쪽마다 URI 하나, 1쪽에 2쪽(0-based)으로 가는 GOTO 하나."""
    p = os.path.join(root, name)
    d = fitz.open()
    for i in range(pages):
        pg = d.new_page(width=595, height=842)
        pg.insert_text((72, 100), "%s p%d" % (name, i + 1), fontsize=13)
        pg.insert_link({"kind": fitz.LINK_URI,
                        "from": fitz.Rect(72, link_y, 300, link_y + 20),
                        "uri": "https://example.com/%s/%d" % (name, i + 1)})
        if rotate:
            pg.set_rotation(rotate)
    if pages > 2:
        d[0].insert_link({"kind": fitz.LINK_GOTO, "page": 2,
                          "from": fitz.Rect(72, 200, 300, 220),
                          "to": fitz.Point(0, 0)})
    d.save(p)
    d.close()
    return p


def build(items, out, **over):
    from viewer.twoup import build_twoup
    s = {"make_cover": False, "make_toc": False}
    s.update(over)
    build_twoup(items, s, out, log=lambda *a, **k: True,
                progress=lambda *a, **k: True)
    return out


try:
    src = make_src("a.pdf", 4)

    # ── ① 2-up 에서 모두 남는다 ─────────────────────────────────────
    out1 = build([{"type": "pdf", "path": src, "name": "a"}],
                 os.path.join(root, "o1.pdf"))
    L = links_of(out1)
    uri = [e for e in L if e[1] == fitz.LINK_URI]
    goto = [e for e in L if e[1] == fitz.LINK_GOTO]
    chk(len(uri) == 4, "① URI 링크 4개가 모두 남는다", len(uri))
    chk(len(goto) == 1, "① GOTO 링크가 남는다", len(goto))
    chk(sorted(e[2] for e in uri) == ["https://example.com/a.pdf/%d" % i
                                      for i in range(1, 5)],
        "① 주소가 쪽마다 제 것으로 간다")

    # ── ② 자리 ─────────────────────────────────────────────────────
    d1 = fitz.open(out1); sheet = d1[0].rect; nsheet = d1.page_count; d1.close()
    chk(nsheet == 2, "② 4쪽이 2장으로 묶였다(다단이 실제로 돌았다)", nsheet)
    # 왼쪽 칸: ml=28, 폭 (W-28-28-16)/2, 높이 H-36-48-21 → contain 비율유지
    W, H = sheet.width, sheet.height
    cw = (W - 28 - 28 - 16) / 2.0
    ch = H - 36 - 48 - (11 + 10)
    k = min(cw / 595.0, ch / 842.0)
    x0 = 28 + (cw - 595 * k) / 2.0 + 72 * k
    y0 = 36 + (ch - 842 * k) / 2.0 + 120 * k
    first = sorted([e for e in uri if e[0] == 0], key=lambda e: e[4].x0)[0]
    chk(abs(first[4].x0 - x0) < 1 and abs(first[4].y0 - y0) < 1,
        "② 축소 배율·칸 위치가 그대로 반영된다",
        "(%.1f, %.1f) 기대 (%.1f, %.1f)" % (first[4].x0, first[4].y0, x0, y0))
    chk(abs(first[4].width - 228 * k) < 1,
        "② 폭도 같은 배율로 줄어든다",
        "%.1f 기대 %.1f" % (first[4].width, 228 * k))

    # ── ③ GOTO 목표 ────────────────────────────────────────────────
    # 원본 3쪽(0-based 2)은 둘째 시트(0-based 1)의 왼쪽 칸에 놓인다
    chk(goto[0][3] == 1, "③ GOTO 가 가는 쪽이 놓인 시트를 가리킨다", goto[0][3])
    chk(goto[0][0] == 0, "③ GOTO 는 원래 있던 쪽(첫 시트)에 남는다", goto[0][0])

    # ── ④ ★ 맞쪽 인쇄 — 앞에 빈 쪽이 끼어도 밀리지 않는다 ───────────
    out4 = build([{"type": "pdf", "path": src, "name": "a"}],
                 os.path.join(root, "o4.pdf"), facing_first=True)
    L4 = links_of(out4)
    d4 = fitz.open(out4); n4 = d4.page_count; blank = d4[0].get_text("text").strip(); d4.close()
    chk(n4 == 3 and blank == "", "④ 맨 앞에 빈 쪽이 끼었다", "%d쪽" % n4)
    g4 = [e for e in L4 if e[1] == fitz.LINK_GOTO]
    u4 = [e for e in L4 if e[1] == fitz.LINK_URI]
    chk(len(u4) == 4 and len(g4) == 1, "④ 링크 수는 그대로", "%d/%d" % (len(u4), len(g4)))
    chk(g4[0][0] == 1, "④ 링크가 밀린 **제 쪽**에 붙어 있다(빈 쪽이 아니다)", g4[0][0])
    chk(g4[0][3] == 2, "④ ★ GOTO 목표도 한 장 밀렸다(보정 없으면 1 이 된다)", g4[0][3])

    # ── ⑤ ★ 표지·목차가 앞에 붙어도 ────────────────────────────────
    out5 = build([{"type": "pdf", "path": src, "name": "a"}],
                 os.path.join(root, "o5.pdf"), make_cover=True, make_toc=True)
    d5 = fitz.open(out5); n5 = d5.page_count; d5.close()
    L5 = links_of(out5)
    u5 = [e for e in L5 if e[1] == fitz.LINK_URI]
    g5 = [e for e in L5 if e[1] == fitz.LINK_GOTO]
    chk(n5 > 2, "⑤ 표지·목차가 붙어 쪽이 늘었다", "%d쪽" % n5)
    chk(len(u5) == 4, "⑤ URI 4개가 그대로", len(u5))
    chk(len(g5) == 1 and g5[0][3] is not None and g5[0][3] > g5[0][0],
        "⑤ GOTO 가 뒤쪽 시트를 가리킨다(앞장만큼 밀려서)",
        "쪽%s → %s" % (g5[0][0], g5[0][3]))
    # 링크가 본문 시트에만 있다 — 표지·목차에 묻지 않았다
    chk(all(e[0] >= n5 - 2 for e in u5),
        "⑤ 링크가 본문 시트에만 있다(표지·목차에 안 묻었다)",
        sorted(set(e[0] for e in u5)))

    # ── ⑥ 잘려 나간 자리는 버린다 ──────────────────────────────────
    # 링크를 쪽 아래쪽(y=800)에 두고 위 40%만 남기는 크롭을 걸면 사라져야 한다
    low = make_src("low.pdf", 2, link_y=800)
    out6 = build([{"type": "pdf", "path": low, "name": "low"}],
                 os.path.join(root, "o6.pdf"),
                 crop_on=True, crop_top=0, crop_bottom=60, crop_left=0, crop_right=0)
    L6 = links_of(out6)
    out6b = build([{"type": "pdf", "path": low, "name": "low"}],
                  os.path.join(root, "o6b.pdf"))
    chk(len(links_of(out6b)) == 2, "⑥ 크롭이 없으면 둘 다 남는다", len(links_of(out6b)))
    chk(len(L6) == 0, "⑥ 잘려 나간 자리의 링크는 버린다(엉뚱한 곳에 안 남는다)", len(L6))

    # ── ⑦ 여러 파일 ────────────────────────────────────────────────
    srcb = make_src("b.pdf", 4)
    out7 = build([{"type": "pdf", "path": src, "name": "a"},
                  {"type": "pdf", "path": srcb, "name": "b"}],
                 os.path.join(root, "o7.pdf"))
    L7 = links_of(out7)
    u7 = [e for e in L7 if e[1] == fitz.LINK_URI]
    g7 = [e for e in L7 if e[1] == fitz.LINK_GOTO]
    chk(len(u7) == 8, "⑦ 두 파일의 URI 8개가 모두 남는다", len(u7))
    chk(len(g7) == 2, "⑦ 파일마다 GOTO 가 남는다", len(g7))
    chk(len(set(g7[0][3:4] + g7[1][3:4])) == 2,
        "⑦ ★ 두 GOTO 가 **서로 다른 쪽**(자기 파일 안)을 가리킨다",
        [e[3] for e in g7])
    byfile = {}
    for e in u7:
        byfile.setdefault(e[2].rsplit("/", 2)[-2], []).append(e[0])
    chk(len(byfile) == 2 and all(len(v) == 4 for v in byfile.values()),
        "⑦ 파일별로 4개씩 섞이지 않았다", {k: sorted(v) for k, v in byfile.items()})

    # ── ⑧ 4-up · stretch ───────────────────────────────────────────
    out8 = build([{"type": "pdf", "path": src, "name": "a"}],
                 os.path.join(root, "o8.pdf"), nup=4)
    L8 = links_of(out8)
    d8 = fitz.open(out8); n8 = d8.page_count; d8.close()
    chk(n8 == 1 and len([e for e in L8 if e[1] == fitz.LINK_URI]) == 4,
        "⑧ 4-up 한 장에 URI 4개", "%d쪽 / %d개" % (n8, len(L8)))
    out8b = build([{"type": "pdf", "path": src, "name": "a"}],
                  os.path.join(root, "o8b.pdf"), fit_mode="stretch")
    chk(len([e for e in links_of(out8b) if e[1] == fitz.LINK_URI]) == 4,
        "⑧ stretch(비율 무시)에서도 4개", len(links_of(out8b)))

    # ── ⑨ 돌아간 쪽 ────────────────────────────────────────────────
    rot = make_src("rot.pdf", 2, rotate=90)
    out9 = build([{"type": "pdf", "path": rot, "name": "rot"}],
                 os.path.join(root, "o9.pdf"))
    L9 = links_of(out9)
    chk(len(L9) == 2, "⑨ /Rotate 90 쪽에서도 링크가 남는다", len(L9))
    d9 = fitz.open(out9)
    sh9 = d9[0].rect
    inside = all(sh9.contains(e[4]) for e in L9)
    d9.close()
    chk(inside, "⑨ 그 자리가 시트 안에 있다(좌표가 뒤집히지 않았다)",
        [tuple(round(v) for v in e[4]) for e in L9])

    # ── ⑩ 링크 없는 문서 ───────────────────────────────────────────
    plain = os.path.join(root, "plain.pdf")
    dp = fitz.open()
    for i in range(2):
        dp.new_page(width=595, height=842).insert_text((72, 100), "x", fontsize=12)
    dp.save(plain); dp.close()
    out10 = build([{"type": "pdf", "path": plain, "name": "p"}],
                  os.path.join(root, "o10.pdf"))
    chk(len(links_of(out10)) == 0, "⑩ 링크 없는 문서에 링크를 만들지 않는다",
        len(links_of(out10)))

except Exception:
    import traceback
    traceback.print_exc()
    fails.append("예외")
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
if fails:
    print("=== FAILURE (%d) ===" % len(fails))
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("=== ALL PASS ===")
