# -*- coding: utf-8 -*-
"""디지털 PDF 에서 '문장 끝이 아닌데 줄 끝에서 끊겨 남은 곳' 을 센다 (261108-31, 텍스트 창 SOT §3.7.16).

    python scripts/join_gaps.py <PDF> [<PDF> …] [--show N] [--pages 0-49]

글자층이 쓸 만한 쪽(`has_text_layer`)만 본다. 그 쪽의 줄을 텍스트 창과 **같은 잇기**(`join_sentences`)에 태우고,
잇지 않은 이웃 줄 가운데 이어지는 글로 보이는 짝('끊김 후보')을 막은 조건(§3.7.2 ①~⑨)별로 센다.

끊김 후보(어림 — 정답이 아니라 손질할 곳을 찾는 그물):
  · 앞 줄이 문장 끝 부호(§3.7.2 ③)로 끝나지 않고, 뒷줄이 본문 글 줄이며 목록 표시로 시작하지 않는다
  · 그리고 ㄱ) 뒷줄이 라틴 소문자로 시작하거나 ㄴ) 앞 줄이 `,`·`(`·이음 낱말로 끝나거나
    ㄷ) 앞 줄이 한글로 끝나고 뒷줄이 한글로 시작하며 앞 줄이 12자 이상(제목·짧은 항목은 짧다)
읽기만 한다 — 파일을 바꾸지 않는다.
"""
import os, sys, re, argparse
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _end_core(t: str) -> str:
    from viewer import text_extract2 as tx
    return t.rstrip().rstrip(tx._CLOSERS)


def candidate(a: dict, b: dict) -> bool:
    from viewer import text_extract2 as tx
    ta = (a.get("_tail") or a.get("text") or "").rstrip()
    tb = (b.get("text") or "").lstrip()
    if not ta or not tb:
        return False
    if a.get("kind") != "text" or b.get("kind") != "text":
        return False
    if ta[-1] in tx.SENT_END or _end_core(ta)[-1:] in tx.SENT_END:
        return False
    if tx._starts_list(tb) or tx._is_caption(ta) or tx._is_caption(tb):
        return False
    if " | " in ta or " | " in tb:
        return False
    if re.match(r"[a-z]", tb):
        return True
    if ta[-1] in ",(-–" or re.search(r"\b(?:and|or|of|the|to|in|for|with|a|an)$", ta):
        return True
    if tx._is_cjk(ta[-1]) and tx._is_cjk(tb[0]) and len(ta) >= 12:
        return True
    return False


def measure(path, pages=None, show=0):
    import fitz
    from viewer import text_extract2 as tx
    doc = fitz.open(path)
    n_pages = n_join = n_seen = 0
    by = {}
    ex = {}
    rng = range(doc.page_count) if pages is None else [p for p in pages if p < doc.page_count]
    for p in rng:
        if not tx.has_text_layer(doc, p):
            continue
        n_pages += 1
        raw = tx.page_lines(doc, path, p, tables="lines", join_lines=False)
        why = []
        out = tx.join_sentences(raw, why_out=why)
        # 창과 같은 잇기 사슬 끝까지(단 넘김 `join_columns`·분철 `join_hyphens`) — 거기서 이어진 짝은 끊김이 아니다
        final = tx.join_hyphens(tx.join_columns(out))
        starts = {((r.get("line_texts") or [r.get("text") or ""])[0]).strip() for r in final}
        ends = {((r.get("line_texts") or [r.get("text") or ""])[-1]).strip() for r in final}
        n_join += max(0, len([r for r in raw if r.get("rect")]) - len([r for r in final if r.get("rect")]))
        for a, b, w in why:
            n_seen += 1
            if not candidate(a, b):
                continue
            if (b.get("text") or "").strip() not in starts:
                continue                                    # 뒤 단계에서 앞 줄에 이어졌다
            if (a.get("_tail") or a.get("text") or "").strip() not in ends:
                continue                                    # 앞 줄이 뒤 단계에서 다른 줄(다음 단 첫 줄)로 이어졌다
            k = w[0] if w else "?"
            by[k] = by.get(k, 0) + 1
            ex.setdefault(k, [])
            if len(ex[k]) < show:
                ex[k].append((p + 1, (a.get("_tail") or a.get("text"))[-40:], (b.get("text") or "")[:40]))

    doc.close()
    return {"pages": n_pages, "joins": n_join, "pairs": n_seen, "gaps": sum(by.values()), "by": by, "ex": ex}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", nargs="+")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--pages", default="")
    a = ap.parse_args()
    pages = None
    if a.pages:
        lo, _, hi = a.pages.partition("-")
        pages = list(range(int(lo), int(hi or lo) + 1))
    tot = {"pages": 0, "joins": 0, "gaps": 0}
    print("| 파일 | 글자층 쪽 | 이은 곳 | 끊김 후보 | 조건별 |")
    print("| --- | --- | --- | --- | --- |")
    allex = []
    for f in a.pdf:
        r = measure(f, pages, a.show)
        for k in tot:
            tot[k] += r[k]
        by = " · ".join("%s %d" % (k, v) for k, v in sorted(r["by"].items(), key=lambda x: -x[1]))
        print("| %s | %d | %d | %d | %s |" % (os.path.basename(f)[:28], r["pages"], r["joins"], r["gaps"], by or "—"))
        for k, items in r["ex"].items():
            for it in items:
                allex.append((os.path.basename(f)[:16], k) + it)
    print("| 합 | %d | %d | %d | |" % (tot["pages"], tot["joins"], tot["gaps"]))
    if allex:
        print()
        for e in allex:
            print("%s %s p%d  …%s ⏎ %s" % e)


if __name__ == "__main__":
    main()
