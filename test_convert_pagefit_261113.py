# -*- coding: utf-8 -*-
"""261113-3: 변환 '편집 가능' = '모양 그대로' + 이어지는 문장 줄만 잇기, 두 방식 모두 원본 1쪽 = 결과 1쪽 (형식 변환 SOT §1·§1.2·§4.1 고침 8).

사용자 지시: "변환의 '편집가능'을 '모양 그대로'를 기반으로 하되, 연속된 문장만 줄 끝에서 이어붙이기를 적용 … 편집가능 / 모양 그대로 모두
기존 자료의 페이지를 최대한 지켜지도록 줄간격과 폰트 크기를 조정해.(word, hwpx)" — 종전 편집 가능은 A4 흐르는 문서(별첨4 37쪽 → HWPX 47·Word 69쪽),
Word 모양 그대로도 71쪽이었다.
  A  쪽 맞춤 계획 `layout.fit_plan` — 자간 → 줄 간격 → 글자 크기 차례, 하한(자간 −10 %·글자 85 %·7 pt), 들여쓰기 몫
  B  `layout.measure_fit` — 글꼴에 없는 글자는 전각으로 / `word_fit.resolve_font` — 설치 안 된 글꼴은 바탕·맑은 고딕, 망가진 이름도 찾는다
  C  HWPX 편집 가능(실제 `convert.run`) — 쪽마다 구역·원본 쪽 크기(모양 그대로 기반), 이은 문단은 줄을 꺾고(BREAK) 원본 줄 간격,
     제목·목록 줄은 따로, 그림·표 없이도 글이 한 번씩만
  D  Word 편집 가능(실제 `convert.run`, pdf2docx 자식 프로세스) — 쪽마다 구역(모양 그대로 기반), 이은 줄 사이에 줄 바꿈이 없고 빈칸으로,
     목록 줄은 따로, 줄 간격은 '정확히', 설치 안 된 글꼴 이름이 남지 않는다
  E  Word 머리글은 원본에 머리말이 있던 쪽의 구역에만 — 없던 쪽(표지)은 빈 머리글·거리 0(머리글이 본문을 밀어 쪽마다 넘쳤다), 구역 끝 빈 문단은 1 pt
  F  (Word 가 있을 때만) Word 로 연 쪽 수 = 원본 쪽 수 — 모양 그대로·편집 가능
  G  넘침 줄이기 B 안(사용자 결정) — Word 너비 어림 × 1.10(바꾼 글꼴·설치된 글꼴 둘 다), 표 칸 밖 문단 위 간격 90 %. **수정 전 코드로 실패**
픽스처는 `test_fixtures.paragraph_pdf()`(3쪽 한글 문단) — 업무 PDF 는 쓰지 않는다. **수정 전 코드로 C·D·E 실패.**
"""
import os, re, shutil, sys, tempfile, zipfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pathlib import Path
from PyQt6.QtCore import QStandardPaths
QStandardPaths.setTestModeEnabled(True)
import fitz
import test_fixtures
from viewer import convert
from viewer.convert import layout

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


try:
    from viewer.convert import word_fit
except ImportError as e:                       # 수정 전 코드 — A·B 는 실패로 남기고 C~F 를 본다
    word_fit = None
    chk(False, "A·B 쪽 맞춤·글꼴 함수가 있다", repr(e))


def part_ab():
    """A·B — 쪽 맞춤 계획·너비·글꼴(함수 단위)."""
    # ── A. 쪽 맞춤 계획 ─────────────────────────────────────────────
    p = layout.fit_plan(800, 2, 450, 12, 18)
    chk(p["shrink"] == 0 and p["scale"] == 1.0 and p["pitch"] == 18, "A 넉넉하면 그대로", str(p))
    p = layout.fit_plan(880, 2, 450, 12, 18)
    chk(-0.10 <= p["shrink"] < 0 and p["scale"] == 1.0 and p["pitch"] == 18 and p["rows"] <= 2, "A 조금 넘치면 자간만", str(p))
    p = layout.fit_plan(1000, 2, 450, 12, 18)
    chk(p["shrink"] == layout.FIT_SPACING_MIN and p["rows"] == 3 and abs(p["pitch"] - 12.0) < 0.01 and p["scale"] == 1.0,
        "A 자간 하한 뒤 줄 간격 — 어림 줄 수 × 줄 간격 = 원본 높이", str(p))
    p = layout.fit_plan(1500, 2, 450, 12, 18)
    chk(p["scale"] < 1.0 and p["scale"] >= layout.FIT_SIZE_K - 1e-9 and p["pitch"] >= 12 * p["scale"] * layout.FIT_LINE_MIN - 1e-6,
        "A 그래도 넘치면 글자 크기(하한 85 %), 줄 간격은 글자 크기 아래로 가지 않는다", str(p))
    p = layout.fit_plan(9000, 2, 450, 12, 18)
    chk(abs(p["scale"] - layout.FIT_SIZE_K) < 1e-9, "A 하한에 닿으면 넘친다(글을 버리지 않는다)", str(p))
    p = layout.fit_plan(9000, 2, 450, 7.5, 12)
    chk(p["scale"] * 7.5 >= layout.FIT_SIZE_MIN_PT - 1e-6, "A 글자 크기는 7 pt 아래로 줄이지 않는다", str(p))
    p = layout.fit_plan(470, 1, 450, 12)
    chk(p["pitch"] is None and p["shrink"] < 0 and p["scale"] == 1.0, "A 끊은 한 줄 — 자간으로 한 줄에", str(p))
    p = layout.fit_plan(600, 1, 450, 12)
    chk(p["shrink"] == layout.FIT_SPACING_MIN and p["scale"] < 1.0, "A 끊은 한 줄 — 자간 하한 뒤 글자 크기", str(p))
    a0 = layout.fit_plan(850, 2, 450, 12, 18)
    a1 = layout.fit_plan(850, 2, 450, 12, 18, indent=-25)
    chk(a1["shrink"] < a0["shrink"] or a1["rows"] > a0["rows"] or a1["pitch"] < a0["pitch"], "A 내어쓰기만큼 짧은 줄을 셈한다",
        f"{a0} {a1}")

    # ── B. 너비·글꼴 ─────────────────────────────────────────────────
    if layout.measure("가", 10, False) is not None:
        m0 = layout.measure("가나", 10, False)
        mf = layout.measure_fit("가나\u278a", 10, False)          # ➊ 는 맑은 고딕에 없다
        chk(mf is not None and mf >= m0 + 9.9, "B 글꼴에 없는 글자는 전각(글자 크기)으로 잰다", f"{m0} {mf}")
    face, inst = word_fit.resolve_font("H2hdrM", 0)
    chk(not inst and face in (layout.SANS_FACE, layout.SERIF_FACE), "B 설치 안 된 글꼴 → 바탕·맑은 고딕", f"{face} {inst}")
    face, inst = word_fit.resolve_font("HYwulM-Myeongjo", 0)
    chk(face == layout.SERIF_FACE or inst, "B 명조 갈래는 바탕으로", f"{face} {inst}")
    if Path(r"C:\Windows\Fonts\malgun.ttf").exists():
        face, inst = word_fit.resolve_font("ABCDEF+MalgunGothicBold", 0)
        chk(inst and face.lower().replace(" ", "") == "malgungothic", "B 망가진 이름(MalgunGothicBold)도 설치된 글꼴로", f"{face} {inst}")


if word_fit is not None and hasattr(layout, "fit_plan"):
    part_ab()

# ── C·D·E·F 실제 변환 ───────────────────────────────────────────
ROOT = Path(tempfile.mkdtemp(prefix="convpagefit_test_"))
try:
    src = ROOT / "문단 문서.pdf"
    shutil.copy2(test_fixtures.paragraph_pdf(), str(src))
    n_src = fitz.open(str(src)).page_count
    line1 = "중대재해를 줄이기 위한"                     # 문단 첫 줄 머리
    tail1 = "제도이며 현장에"                            # 같은 문단의 다음 줄에 걸친 말

    # C. HWPX 편집 가능
    out = convert.run(str(src), "hwpx_edit")
    z = zipfile.ZipFile(str(out))
    secs = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n))
    xs = [z.read(n).decode("utf-8") for n in secs]
    full = "".join(xs)
    hdr = z.read("Contents/header.xml").decode("utf-8")
    sizes = re.findall(r'<hp:pagePr[^>]*width="(\d+)"[^>]*height="(\d+)"', full)
    chk(len(xs) == n_src and all(s == ("59500", "84200") for s in sizes), "C HWPX 편집 가능 — 쪽마다 구역·원본 쪽 크기(모양 그대로 기반)",
        f"{len(xs)} {sizes[:3]}")
    paras = re.findall(r'<hp:p [^>]*>(?:(?!<hp:p ).)*?</hp:p>', xs[0], re.S)
    joined = [q for q in paras if line1 in q and tail1 in re.sub(r"<[^>]+>", "", q)]
    chk(len(joined) >= 1, "C 이어지는 문장 줄은 한 문단으로", str(len(paras)))
    if joined:
        pid = re.search(r'paraPrIDRef="(\d+)"', joined[0]).group(1)
        mp = re.search(r'<hh:paraPr [^>]*\sid="%s"[^>]*>.*?</hh:paraPr>' % pid, hdr, re.S)
        pp = mp.group(0) if mp else ""
        chk('lineWrap="BREAK"' in pp, "C 이은 문단은 줄을 꺾는다(BREAK)")
        ls = [int(v) for v in re.findall(r'<hh:lineSpacing type="PERCENT" value="(\d+)"', pp)]
        chk(ls and all(130 <= v <= 160 for v in ls), "C 이은 문단의 줄 간격 = 원본 줄 간격(약 1.46 배)", str(ls))
    items = [q for q in paras if "목록 줄" in re.sub(r"<[^>]+>", "", q)]
    chk(len(items) == 3 and all(re.sub(r"<[^>]+>", "", q).count("목록 줄") == 1 for q in items),
        "C 목록 줄은 잇지 않는다(줄마다 문단)", str(len(items)))
    body0 = re.sub(r"<[^>]+>", "", re.sub(r"<hp:(header|footer) .*?</hp:\1>", "", xs[0], flags=re.S))
    want = re.sub(r"\s+", "", fitz.open(str(src))[0].get_text()).count(re.sub(r"\s+", "", line1))
    chk(re.sub(r"\s+", "", body0).count(re.sub(r"\s+", "", line1)) == want, "C 글은 한 번씩만(이은 문단과 원본 줄이 겹치지 않는다)",
        f"{body0.count(line1)} / 원본 {want}")

    # D. Word 편집 가능
    from docx import Document
    from docx.enum.section import WD_SECTION
    outw = convert.run(str(src), "docx_edit")
    dd = Document(str(outw))
    newpage = [s for i, s in enumerate(dd.sections) if i == 0 or s.start_type != WD_SECTION.CONTINUOUS]
    chk(len(newpage) == n_src, "D Word 편집 가능 — 쪽마다 구역(모양 그대로 기반 pdf2docx)", str(len(newpage)))
    texts = [p.text for p in dd.paragraphs]
    jw = [t for t in texts if line1 in t and tail1 in t]
    chk(jw and all("\n" not in t.split(tail1)[0][-30:] for t in jw), "D 이어지는 문장 줄은 한 문단, 줄 바꿈 없이", str([t[:60] for t in jw[:1]]))
    chk(jw and not re.search(r"사업장의유해|대책을세우고|지원을함께", jw[0]), "D 이은 줄 사이 빈칸(텍스트 창이 넣은 그대로)",
        jw[0][:120] if jw else "")
    lst = [t for t in texts if "목록 줄" in t]
    chk(lst and not any(re.search(r"목록 줄\s*○", t.replace("\n", "|")) for t in lst)
        and all(t.count("목록 줄") == t.count("\n") + 1 for t in lst if t.count("목록 줄") > 1),
        "D 목록 줄은 잇지 않는다(줄마다 끊음)", str(lst[:1]))
    x = dd.element.body.xml
    rules = re.findall(r'<w:spacing [^>]*w:lineRule="(\w+)"', x)
    chk(rules and rules.count("exact") >= len(rules) * 0.8, "D 줄 간격은 '정확히'(Word 글꼴의 줄 높이를 타지 않게)",
        f"{rules.count('exact')}/{len(rules)}")
    fonts = set(re.findall(r'w:eastAsia="([^"]+)"', x))
    inst = word_fit.installed_fonts() if word_fit is not None else {}
    bad = [f for f in fonts if f not in (layout.SERIF_FACE, layout.SANS_FACE)
           and f.lower().replace(" ", "").replace("-", "") not in inst]
    chk(not bad, "D 설치 안 된 글꼴 이름이 남지 않는다", str(bad))

    # E. Word 머리글 — 머리말이 있던 쪽에만
    hf = ROOT / "머리말 문서.pdf"
    d = fitz.open()
    for i in range(3):
        pg = d.new_page(width=595, height=842)
        if i:
            pg.insert_text((72, 40), "Asphalt Design Guide", fontsize=9, fontname="tiro")
        pg.insert_text((72, 60 if i == 0 else 100), f"Body line on page {i + 1} explains the method.", fontsize=11, fontname="tiro")
        for k in range(18):
            pg.insert_text((72, 140 + k * 16), f"Body line {k} on page {i + 1} explains the method in detail.", fontsize=11,
                           fontname="tiro")
    d.save(str(hf)); d.close()
    eh = convert.run(str(hf), "docx_shape")
    de = Document(str(eh))
    np_ = [s for i, s in enumerate(de.sections) if i == 0 or s.start_type != WD_SECTION.CONTINUOUS]
    h0 = "".join(p.text for p in np_[0].header.paragraphs) if np_ else "?"
    h1 = "".join(p.text for p in np_[1].header.paragraphs) if len(np_) > 1 else ""
    chk(len(np_) == 3 and not h0.strip() and not np_[0].header.is_linked_to_previous and np_[0].header_distance.pt < 1,
        "E 머리말 없던 쪽(표지)은 빈 머리글·거리 0 — 머리글이 본문을 밀지 않게", f"{len(np_)} '{h0}' {np_[0].header_distance.pt if np_ else None}")
    chk("Asphalt Design Guide" in h1, "E 머리말이 있던 쪽은 머리글", h1)
    ends = [p for p in de.paragraphs if p._p.pPr is not None and p._p.pPr.sectPr is not None and not p.text.strip()]
    chk(ends and all(p.paragraph_format.line_spacing is not None and abs(p.paragraph_format.line_spacing.pt - 1) < 0.01 for p in ends),
        "E 구역 끝 빈 문단은 1 pt(넘쳐 빈 쪽을 만들지 않게)", str(len(ends)))

    # G. 넘침 줄이기 B 안(§1.2 'Word 너비 여유'·'Word 문단 위 간격') — 너비는 × WIDTH_MARGIN, 표 칸 밖 문단 위 간격은 × BEFORE_K
    if word_fit is not None:
        mk = layout.measure_fit("가나다라마바사", 10, False)
        hw = word_fit.Hook({"mode": "shape"}).width("가나다라마바사", 10, "H2hdrM", 0, 50.0)
        chk(mk and abs(hw / mk - getattr(word_fit, "WIDTH_MARGIN", 1.0)) < 0.01 and getattr(word_fit, "WIDTH_MARGIN", 1.0) >= 1.10,
            "G Word 너비 어림 = 잰 너비 × 1.10(여유)", f"{hw} {mk}")
        hi = word_fit.Hook({"mode": "shape"}).width("abc", 10, "Malgun Gothic", 0, 50.0)
        chk(abs(hi - 50.0 * getattr(word_fit, "WIDTH_MARGIN", 1.0)) < 0.01 and hi > 50.0, "G 설치된 글꼴도 원본 너비 × 여유", str(hi))
        import logging
        logging.disable(logging.CRITICAL)
        from viewer._vendor.pdf2docx import Converter, polypdf_fit

        class _Flat(word_fit.Hook):
            before_k = 1.0
        befores = {}
        for tag, hook in (("B", word_fit.Hook({"mode": "shape"})), ("1", _Flat({"mode": "shape"}))):
            polypdf_fit.HOOK = hook
            dstg = ROOT / f"g_{tag}.docx"
            cv = Converter(str(src))
            cv.convert(str(dstg), **word_fit.MARGIN_SETTINGS)
            cv.close()
            xg = Document(str(dstg)).element.body.xml
            body_only = re.sub(r"<w:tbl>.*?</w:tbl>", "", xg, flags=re.S)
            befores[tag] = sum(int(v) for v in re.findall(r'<w:spacing [^>]*w:before="(\d+)"', body_only))
        polypdf_fit.HOOK = None
        ratio = befores["B"] / max(1, befores["1"])
        chk(0.85 <= ratio <= 0.95, "G 본문 문단 위 간격 = 90 %(표 칸 밖)", f"{befores} {ratio:.3f}")

    # F. Word 로 연 쪽 수
    from viewer.convert.word_com import word_installed
    if word_installed():
        outs = convert.run(str(src), "docx_shape")
        import win32com.client as w
        import pythoncom
        pythoncom.CoInitialize()
        app = w.DispatchEx("Word.Application"); app.Visible = False; app.DisplayAlerts = 0
        try:
            got = {}
            for key, path in (("모양 그대로", outs), ("편집 가능", outw), ("머리말", eh)):
                doc = app.Documents.Open(str(path), ReadOnly=True)
                got[key] = doc.ComputeStatistics(2)
                doc.Close(False)
        finally:
            app.Quit()
        chk(got["모양 그대로"] == n_src and got["편집 가능"] == n_src and got["머리말"] == 3,
            "F Word 로 연 쪽 수 = 원본 쪽 수", str(got))
    else:
        print("SKIP - F Word 가 없다")
finally:
    shutil.rmtree(ROOT, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(1 if fails else 0)
