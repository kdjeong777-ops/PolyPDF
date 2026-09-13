# -*- coding: utf-8 -*-
"""260908-2: 고친 글을 **OCR 텍스트층에 다시 적기** (텍스트 창 SOT §5.2).

스캔 PDF 는 그림 위에 **보이지 않는 글자**(render mode 3)가 얹혀 있다. 복사·검색은 그
글자를 읽는다. OCR 이 틀리게 읽었으면 그 글자만 바꿔 끼우면 **화면 모양은 그대로**이고
복사 결과만 고쳐진다.

절차
  1) 원본 백업 `<이름>.textfix.bak.pdf`
  2) 고친 줄의 사각형에 redact 를 걸어 **글자만** 지운다
     (`images=PDF_REDACT_IMAGE_NONE` — 그림은 건드리지 않는다)
  3) 같은 자리에 `render_mode=3`(보이지 않음)으로 고친 글을 적는다
  4) 저장은 마스터 §4.7.5 규칙(`finalize` 콜백 = 원본 덮어쓰기·실패 시 알림)
  260913-4: 고침이 있는 **모든 쪽**을 한 번에(`apply_fixes_by_page`), 글꼴은 쓴 글자만.
  260913-8: ★ 앱의 반영은 `TextLayerWorker` → `build_layer_pdf`(글자층 다시 쓰기, SOT §5.4) 한 길이다.
  위 `apply_fixes_by_page`·`apply_fixes_to_pdf` 는 앱이 부르지 않고 검사에서만 쓴다(SOT §5.2).

★ **텍스트층이 보이는 일반 PDF 에는 쓰지 않는다.** 그 글자는 곧 화면에 보이는 내용이라
  다시 적으면 글꼴이 바뀐다. 호출측(app)이 미리 가른다.
"""
from __future__ import annotations

from pathlib import Path

from viewer.pdf_font import fresh_font_name, subset_fonts_safely

BACKUP_SUFFIX = ".textfix.bak.pdf"
# 260913-6(SOT §5.4): 글자층 다시 쓰기 — 줄 높이 대비 글자 크기와 밑줄(글자 바닥) 자리
LAYER_FS = 0.9
LAYER_BASE = 0.18


def _korean_font_file():
    """한글이 들어간 글을 적을 때 쓸 글꼴 파일. 없으면 None(기본 글꼴)."""
    for p in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc",
              r"C:\Windows\Fonts\batang.ttc"):
        if Path(p).exists():
            return p
    return None


def _write_invisible(page, rect, text, fontfile, fontname: str = "krfix",
                     line_h: float = 0.0) -> bool:
    """사각형 안에 **보이지 않는 글자**를 적는다. 적었으면 True.

    260908-6(SOT §5.2): `insert_textbox` 는 글이 안 들어가면 **예외 없이 음수를 돌려주고
    아무것도 적지 않는다**. 종전 코드는 그 값을 보지 않아, 지우기만 되고 다시 적히지
    않은 줄이 생길 수 있었다(사용자 보고 '텍스트가 매칭이 안 된다'의 한 갈래).
    그래서 크기를 줄여 가며 다시 시도하고, 그래도 안 되면 한 줄로 적는다.

    260913-4(SOT §5.2): 글자 크기는 **원래 줄 높이**(`line_h`)에서 잡는다. 합친 줄의 사각형은
    여러 줄 높이라, 그 높이로 잡으면 글자가 몇 배로 커져 들어가지 않고 한 줄 적기로 떨어진 뒤
    **쪽 밖으로 넘쳐 잘렸다**(실측: `alpha first line p2 b`). 한 줄 적기도 폭에 맞춰 줄인다."""
    if not str(text):
        return True                              # 빈 줄 = 지우기(다시 적지 않는다)
    base = (line_h if line_h and line_h > 0 else rect.height) * 0.8
    size = max(3.0, min(72.0, base))
    kw0 = {"render_mode": 3}
    if fontfile:
        kw0.update(fontfile=fontfile, fontname=fontname)
    for _ in range(6):
        try:
            if page.insert_textbox(rect, text, fontsize=size, **kw0) >= 0:
                return True
        except Exception:
            break
        size *= 0.8
        if size < 3.0:
            break
    fs = max(3.0, min(72.0, base))
    try:                                         # 한 줄 적기 — 폭을 넘지 않게
        import fitz
        font = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font("helv")
        w1 = float(font.text_length(str(text), fontsize=1.0))
        if w1 > 0 and rect.width > 0:
            fs = max(1.0, min(fs, rect.width / w1))
    except Exception:
        pass
    try:
        page.insert_text((rect.x0, rect.y0 + fs), text, fontsize=fs, **kw0)
        return True
    except Exception:
        return False


def apply_fixes_to_pdf(src, page_index: int, rows: list, fixes,
                       finalize=None) -> tuple:
    """한 쪽만 반영 — `apply_fixes_by_page` 의 한 쪽짜리 모양(옛 호출 호환)."""
    return apply_fixes_by_page(src, {int(page_index): fixes},
                               rows_by_page={int(page_index): rows},
                               finalize=finalize)


def _targets(fitz, items, rows):
    """고침 → [(쓸 자리, 글, 지울 자리들)]. 자리를 모르는 것은 뺀다."""
    out = []
    items = (items if isinstance(items, list)
             else [{"line": i, "text": t, "rect": None} for i, t in items.items()])
    for it in items:
        rc = it.get("rect")
        if not rc:                               # 자리를 안 적어 둔 옛 기록만 줄 번호로
            i = int(it.get("line", -1))
            rc = rows[i].get("rect") if rows and 0 <= i < len(rows) else None
        if not rc:
            continue
        # 260910-11(SOT §5.1.2): 합친 줄은 **원래 자리들**을 지우고 합친 자리에 쓴다.
        #   합친 자리를 통째로 지우면 두 문단 사이에 있던 딴 글까지 사라진다.
        erase = [fitz.Rect(*r) for r in (it.get("rects") or []) if r] or [fitz.Rect(*rc)]
        out.append((fitz.Rect(*rc), str(it.get("text", "")), erase))
    return out


def _replace_lines(fitz, page, targets, ff) -> int:
    """줄 바꿔 끼우기(§5.2) — 고친 줄의 자리만 지우고 다시 적는다. 못 적은 줄 수를 돌려준다."""
    for _rect, _t, erase in targets:
        for e in erase:
            page.add_redact_annot(e)
    # 그림은 건드리지 않는다 — 스캔본의 본 모습이 그림이다
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    # 260913-4(마스터 §4.5.10 ②): 한 번 반영한 쪽의 `krfix` 는 이미 **부분집합**이다.
    #   같은 이름으로 새 글자를 적으면 추출·검색에서 빠진다 → 비켜 간 이름을 쓴다.
    fname = fresh_font_name(page, "krfix")
    bad = 0
    for rect, text, erase in targets:
        lh = sorted(e.height for e in erase)[len(erase) // 2] if erase else 0.0
        if not _write_invisible(page, rect, text, ff, fname, lh):
            bad += 1
    return bad


# ── 260913-6(SOT §5.4): 보이지 않는 글자층 다시 쓰기 ─────────────────────────
def split_to_parts(text: str, parts, widths=None) -> list:
    """합친·이은 줄의 글을 **원래 줄들에 도로 나눈다** (SOT §5.4 2단계).

    원래 줄 글(`parts`)을 줄바꿈으로 이은 것과 고친 글을 순서로 맞춰(`difflib`) 줄 경계를
    옮긴다 — 오타 몇 자를 고친 정도면 경계가 제자리에 온다. 너무 달라 맞출 수 없으면
    줄 폭(`widths`, 없으면 글 길이) 비율로 나눈다. 경계는 가까운 빈칸으로 붙인다."""
    import difflib
    parts = [str(p or "") for p in (parts or [])]
    text = str(text or "")
    n = len(parts)
    if n <= 1:
        return [text]
    joined = "\n".join(parts)
    bounds, pos = [], 0
    for t in parts[:-1]:
        pos += len(t)
        bounds.append(pos)
        pos += 1
    sm = difflib.SequenceMatcher(None, joined, text, autojunk=False)
    cuts = []
    if sm.ratio() >= 0.3:
        ops = sm.get_opcodes()
        for b in bounds:
            j = len(text)
            for tag, i1, i2, j1, j2 in ops:
                if i1 <= b < i2 or (i1 == i2 == b):
                    j = j1 + (b - i1) if tag == "equal" else \
                        j1 + int(round((b - i1) * (j2 - j1) / max(1, i2 - i1)))
                    break
            cuts.append(j)
    else:
        ws = [float(w) for w in widths] if widths and len(widths) == n else [len(p) or 1 for p in parts]
        tot, acc = sum(ws) or 1.0, 0.0
        for w in ws[:-1]:
            acc += w
            cuts.append(int(round(len(text) * acc / tot)))
    out_cuts, prev = [], 0
    for c in cuts:
        c = max(prev, min(len(text), c))
        if 0 < c < len(text) and not text[c].isspace() and not text[c - 1].isspace():
            for d in (1, -1, 2, -2, 3, -3, 4, -4):     # 가까운 빈칸으로
                k = c + d
                if prev < k < len(text) and text[k].isspace():
                    c = k
                    break
        out_cuts.append(c)
        prev = c
    edges = [0] + out_cuts + [len(text)]
    return [text[a:b].strip() for a, b in zip(edges[:-1], edges[1:])]


def plan_layer_lines(rows) -> list:
    """창의 줄(고침 얹은 것) → 적을 `[(자리, 글)]` — **원래 줄 단위**, 읽는 차례 그대로.

    ` | ` 는 창의 표시라 적지 않는다(빈칸 하나로). 합친 줄은 `parts` 로 도로 나눈다."""
    out = []
    for r in rows or []:
        t = str(r.get("text") or "").replace(" | ", " ")
        parts = r.get("parts") or []
        if len(parts) >= 2 and all(p[0] for p in parts):
            texts = split_to_parts(t, [str(pt or "").replace(" | ", " ") for _rc, pt in parts],
                                   widths=[p[0][2] - p[0][0] for p in parts])
            for (rc, _pt), tt in zip(parts, texts):
                if tt.strip():
                    out.append((tuple(float(v) for v in rc), tt))
            continue
        if t.strip() and r.get("rect"):
            out.append((tuple(float(v) for v in r["rect"]), t))
    return out


def layer_rewrite_blocker(page, lines) -> str:
    """다시 써도 안전한가 — 안전하면 빈 문자열, 아니면 그 까닭(SOT §5.4 안전 조건)."""
    if not lines:
        return "적을 줄이 없다"
    try:
        if int(page.rotation or 0) != 0:
            return "돌린 쪽"
    except Exception:
        return "쪽 정보를 못 읽음"
    try:
        for tr in page.get_texttrace():
            if tr.get("type") != 3 and tr.get("chars"):
                return "보이는 글자가 있다"
    except Exception:
        return "글자층을 못 읽음"
    if not _korean_font_file():
        return "글꼴 파일이 없다"
    return ""


def rewrite_page_layer(fitz, page, lines, fontfile, font=None) -> int:
    """그 쪽의 글자를 모두 지우고 `lines` 를 **보이지 않게, 줄마다 제자리에 늘여** 적는다.

    부르기 전에 `layer_rewrite_blocker` 로 안전을 확인한다. 적은 줄 수를 돌려준다.
    쪽 전체 지우기는 **하이퍼링크까지** 지우므로(실측) 먼저 받아 두었다가 되살린다."""
    links = []
    try:
        links = [dict(l) for l in page.get_links()]
    except Exception:
        links = []
    page.add_redact_annot(page.rect)
    try:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    except TypeError:                            # 옛 PyMuPDF — graphics 인자가 없다
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    for ln in links:
        try:
            ln.pop("xref", None)
            ln.pop("id", None)
            page.insert_link(ln)
        except Exception:
            pass
    font = font or fitz.Font(fontfile=fontfile)
    fname = fresh_font_name(page, "krfix")       # 마스터 §4.5.10 ②
    n = 0
    for (x0, y0, x1, y1), text in lines:
        h, w = y1 - y0, x1 - x0
        if h <= 0.5 or w <= 0.5 or not text.strip():
            continue
        fs = h * LAYER_FS
        tl = float(font.text_length(text, fontsize=fs))
        if tl <= 0:
            continue
        sx = max(0.05, min(20.0, w / tl))
        pt = fitz.Point(x0, y1 - h * LAYER_BASE)
        try:
            page.insert_text(pt, text, fontsize=fs, fontname=fname, fontfile=fontfile,
                             render_mode=3, morph=(pt, fitz.Matrix(sx, 1)))
            n += 1
        except Exception:
            continue
    return n


def build_layer_pdf(src, pages, *, rows_for, fixes_for, items_for=None,
                    progress=None, cancelled=None) -> tuple:
    """고른 쪽들의 보이지 않는 글자층을 다시 써 **임시 파일**을 만든다 (SOT §5.4).

    원본 덮어쓰기는 부르는 쪽(메인)이 한다 — 핸들을 쥔 곳이 메인이다.
      `rows_for(doc, 쪽) -> 줄목록`   원천(§3.1)으로 뽑은 **원래 줄**
      `fixes_for(쪽, 줄목록) -> 줄목록` 고침 얹기(`TextFixStore.apply_to_rows`)
      `items_for(쪽) -> 고침목록`       물러설 길(줄 바꿔 끼우기)에 쓸 고침
    반환 `(임시 파일, 통계)` — 통계 `{rewritten, fallback, skipped, lines, unwritten, cancelled}`.
    중지되거나 바꾼 쪽이 없으면 임시 파일을 지우고 `""`."""
    import fitz
    src = Path(src)
    stats = {"rewritten": [], "fallback": [], "skipped": [], "lines": 0,
             "unwritten": 0, "cancelled": False, "reasons": {}}
    tmp = src.with_name(src.stem + "_textlayer_tmp.pdf")
    ff = _korean_font_file()
    font = None
    doc = fitz.open(str(src))
    try:
        from viewer import text_extract2 as tx
        total = len(pages)
        for k, pno in enumerate(pages):
            if cancelled is not None and cancelled():
                stats["cancelled"] = True
                break
            if progress is not None:
                progress(k, total, pno)
            if not (0 <= pno < doc.page_count) or tx.has_text_layer(doc, pno):
                stats["skipped"].append(pno)
                continue
            rows = fixes_for(pno, rows_for(doc, pno) or [])
            lines = plan_layer_lines(rows)
            page = doc.load_page(pno)
            why = layer_rewrite_blocker(page, lines)
            if not why:
                if font is None:
                    font = fitz.Font(fontfile=ff)
                stats["lines"] += rewrite_page_layer(fitz, page, lines, ff, font)
                stats["rewritten"].append(pno)
                continue
            stats["reasons"][pno] = why
            targets = _targets(fitz, (items_for(pno) if items_for else []) or [], None)
            if targets:
                stats["unwritten"] += _replace_lines(fitz, page, targets, ff)
                stats["fallback"].append(pno)
            else:
                stats["skipped"].append(pno)
        if progress is not None:
            progress(total, total, -1)
        if stats["cancelled"] or not (stats["rewritten"] or stats["fallback"]):
            return "", stats
        subset_fonts_safely(doc)                 # 마스터 §4.5.10 ①
        doc.save(str(tmp), garbage=3, deflate=True)
    finally:
        doc.close()
    try:
        bak = src.with_name(src.name + BACKUP_SUFFIX)
        if not bak.exists():
            import shutil
            shutil.copy2(str(src), str(bak))
    except Exception:
        pass
    return str(tmp), stats


def apply_fixes_by_page(src, fixes_by_page: dict, *, rows_by_page=None,
                        finalize=None) -> tuple:
    """여러 쪽의 고침을 **한 번에** 텍스트층에 반영. 반환 (결과 경로, 알림 문자열).

    `fixes_by_page` 는 `{쪽: [{"line","text","rect","rects"}]}` 다(`TextFixStore.get_items`).
    260913-4(SOT §5.2, 사용자 지시): 종전에는 지금 쪽만 반영해 다른 쪽의 고침이 잊혔다.
    백업 한 번·저장 한 번으로 모든 쪽을 넣는다. 자리를 모르는 쪽은 건너뛰고 알린다."""
    try:
        import fitz
    except Exception as e:                       # noqa: BLE001
        return "", f"PyMuPDF 없음: {e}"
    src = Path(src)
    if not src.exists():
        return "", f"원본이 없습니다: {src}"
    fixes_by_page = {int(k): v for k, v in (fixes_by_page or {}).items() if v}
    if not fixes_by_page:
        return str(src), ""
    try:
        bak = src.with_name(src.name + BACKUP_SUFFIX)
        if not bak.exists():
            import shutil
            shutil.copy2(str(src), str(bak))
    except Exception:
        pass                                     # 백업 실패가 반영을 막지는 않는다

    tmp = src.with_name(src.stem + "_textfix_tmp.pdf")
    unwritten = 0
    no_place = []
    try:
        doc = fitz.open(str(src))
        try:
            ff = _korean_font_file()
            done = 0
            for pno in sorted(fixes_by_page):
                if not (0 <= pno < doc.page_count):
                    continue
                rows = (rows_by_page or {}).get(pno)
                targets = _targets(fitz, fixes_by_page[pno], rows)
                if not targets:
                    no_place.append(pno + 1)
                    continue
                unwritten += _replace_lines(fitz, doc.load_page(pno), targets, ff)
                done += 1
            if not done:
                return "", "고친 줄의 위치를 알 수 없습니다(OCR 좌표 없음)."
            # 260913-4(SOT §5.2): 한글을 적으려 넣은 글꼴이 **통째로** 들어간다(실측 4.10MB →
            #   11.59MB). 쓴 글자만 남긴다 — 규칙은 마스터 §4.5.10 ①(실패해도 저장은 한다).
            subset_fonts_safely(doc)
            doc.save(str(tmp), garbage=3, deflate=True)
        finally:
            doc.close()
    except Exception as e:                       # noqa: BLE001
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return "", str(e)

    notes = []
    if unwritten:
        notes.append(f"{unwritten}줄은 자리가 좁아 다시 적지 못했습니다(그 줄의 옛 글자는 지워졌습니다).")
    if no_place:
        notes.append("위치를 몰라 건너뛴 쪽: " + ", ".join(str(p) for p in no_place))
    warn = chr(10).join(notes)
    if finalize is not None:
        try:
            return str(finalize(str(src), str(tmp))), warn
        except Exception as e:                   # noqa: BLE001
            return "", str(e)
    import os as _os
    _os.replace(str(tmp), str(src))
    return str(src), warn
