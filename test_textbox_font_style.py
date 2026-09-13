# -*- coding: utf-8 -*-
"""260913-7: 글쓰기 글꼴은 맑은 고딕 하나 — 굵게·기울임은 같은 글꼴로 흉내 (마스터 SOT §4.5.11).

  ① 옛 자료의 `family`(굴림)여도 화면 QFont·PDF 굽기 모두 맑은 고딕 하나
  ② 굵게 = 외곽선(render_mode 2) — 글꼴이 늘지 않고 잉크가 늘며 글이 추출된다
  ③ 기울임 = 줄마다 기울임 — 줄 수·기준선이 보통과 같고, 오른쪽으로 기운다
  ④ 설정 창 두 곳에 글꼴 선택이 없다
  ⑤ 줄바꿈 재기가 굵게를 반영한다
  ⑥ 굵게·기울임 박스를 저장한 파일에 다시 구워도 새 글이 남는다(§4.5.10 ②)
"""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
from viewer.edit_controller import EditMixin
from viewer import pdf_font as pf

if not pf.text_font_file() or "malgun" not in pf.text_font_file().lower():
    print("SKIP - 맑은 고딕(malgun.ttf) 없음")
    sys.stdout.flush(); os._exit(0)

root = Path(tempfile.mkdtemp(prefix="polypdf_fstyle_"))
TXT = "굵기 기울임 검사 IIII"


def bake(strokes, doc=None):
    doc = doc or fitz.open()
    if doc.page_count == 0:
        doc.new_page(width=595, height=842)
    EditMixin()._bake_drawings_into_doc(doc, {0: strokes})
    return doc


def box(**extra):
    s = {"text_box": True, "rect": [0.1, 0.1, 0.9, 0.3], "text": TXT, "size_pt": 28,
         "color": "#000000"}
    s.update(extra)
    return s


def lines(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = "".join(s["text"] for s in ln["spans"])
            if t.strip():
                out.append((t, ln["spans"][0]["origin"]))
    return out


def ink(page, clip=None):
    pix = page.get_pixmap(dpi=72, clip=clip, colorspace=fitz.csGRAY)
    return sum(1 for v in pix.samples if v < 128)


try:
    # ① 글꼴 하나 ─────────────────────────────────────────────────────
    d = bake([box(family="굴림"), box(rect=[0.1, 0.4, 0.9, 0.6], family="바탕", bold=True)])
    names = {f[3] for f in d[0].get_fonts()}
    chk(names and all("Malgun" in n for n in names), "① 옛 family(굴림·바탕)여도 PDF 글꼴은 맑은 고딕뿐", str(names))
    from viewer.widgets.main_view import MainView
    from PyQt6.QtCore import QRectF
    mv = MainView()
    f = mv._text_qfont({"family": "굴림", "size_pt": 18, "bold": True}, QRectF(0, 0, 595, 842))
    chk(f.family() == pf.TEXT_FAMILY and f.bold(), "① 화면 QFont 도 맑은 고딕(굵게 유지)", f.family())
    mv.deleteLater()

    # ② 굵게 ─────────────────────────────────────────────────────────
    plain, bold = bake([box()]), bake([box(bold=True)])
    chk(len(bold[0].get_fonts()) == len(plain[0].get_fonts()) == 1,
        "② 굵게가 글꼴을 추가하지 않는다", str([f[3] for f in bold[0].get_fonts()]))
    ip, ib = ink(plain[0]), ink(bold[0])
    chk(ib > ip * 1.15, "② 굵게는 잉크가 늘어난다", f"({ip} → {ib})")
    chk([t for t, _ in lines(bold[0])] == [t for t, _ in lines(plain[0])] and TXT in bold[0].get_text(),
        "② 굵게 글이 그대로 추출된다")

    # ③ 기울임 ───────────────────────────────────────────────────────
    two = "첫째 줄 IIII\n둘째 줄 IIII"
    p2, it2 = bake([box(text=two)]), bake([box(text=two, italic=True)])
    lp, li = lines(p2[0]), lines(it2[0])
    chk([t for t, _ in li] == [t for t, _ in lp] and len(li) == 2, "③ 기울임도 줄 수·글이 같다", str([t for t, _ in li]))
    chk(all(abs(a[1][0] - b[1][0]) < 0.6 and abs(a[1][1] - b[1][1]) < 0.6 for a, b in zip(lp, li)),
        "③ 줄마다 기준점이 보통과 같다(박스 전체가 밀리지 않음)", str([o for _, o in li]))
    # 기운 방향: 'IIII' 의 윗부분 잉크 중심이 아랫부분보다 오른쪽
    one = bake([box(text="IIII", italic=True, size_pt=80)])
    pix = one[0].get_pixmap(dpi=72, colorspace=fitz.csGRAY)
    W, H, sm = pix.width, pix.height, pix.samples
    ys = [y for y in range(H) if any(sm[y * W + x] < 128 for x in range(W))]
    top, bot = ys[: max(1, len(ys) // 4)], ys[-max(1, len(ys) // 4):]

    def cx(rows):
        xs = [x for y in rows for x in range(W) if sm[y * W + x] < 128]
        return sum(xs) / max(1, len(xs))
    chk(cx(top) > cx(bot) + 3, "③ 오른쪽으로 기운다(위가 아래보다 오른쪽)", f"(top {cx(top):.1f}, bottom {cx(bot):.1f})")
    chk(len(it2[0].get_fonts()) == 1, "③ 기울임도 글꼴을 추가하지 않는다")

    # ④ 설정 창 ──────────────────────────────────────────────────────
    import viewer.widgets.line_text_settings_dialog as _ltd
    dlg = _ltd.LineTextSettingsDialog([{"color": "#f00", "width": 3, "alpha": 100}] * 5, [10, 20, 30], 40, [])
    chk(not hasattr(dlg, "_cmb_font") and dlg._editor_to_style("x")["family"] == pf.TEXT_FAMILY,
        "④ 글쓰기 설정 창에 글꼴 선택이 없고 맑은 고딕을 내보낸다")
    dlg.deleteLater()
    here = Path(__file__).parent
    app_src = (here / "viewer" / "app.py").read_text("utf-8")
    chk('"굴림", "바탕", "돋움"' not in app_src and '"굴림", "바탕", "돋움"' not in
        (here / "viewer" / "widgets" / "line_text_settings_dialog.py").read_text("utf-8"),
        "④ 박스 설정 창(app)에도 글꼴 목록이 없다")

    # ⑤ 줄바꿈 재기가 굵게를 반영 ─────────────────────────────────────
    #   오프스크린 Qt 에는 실제 글꼴 파일이 없어 굵게여도 폭이 같다(실측) → 폭 비교 대신
    #   '재는 QFont 에 굵게·기울임을 켜는가' 와 '굽기가 그 값을 넘기는가' 를 본다.
    import inspect
    wsrc = inspect.getsource(EditMixin._wrap_like_screen)
    bsrc = inspect.getsource(EditMixin._bake_text_stroke)
    chk("setBold(bool(bold))" in wsrc and "setItalic(bool(italic))" in wsrc and "TEXT_FAMILY" in wsrc,
        "⑤ 줄바꿈을 잴 때 맑은 고딕에 굵게·기울임을 켠다")
    chk("_wrap_like_screen(txt, fs, box.width, bold=bold, italic=italic)" in bsrc,
        "⑤ 굽기가 굵게·기울임을 줄바꿈 재기에 넘긴다")
    s = "가나다라마바사아자차카타파하" * 6
    chk(EditMixin._wrap_like_screen(s, 20.0, 100.0, bold=True, italic=True).count("\n") >= 5,
        "⑤ 굵게·기울임으로도 줄바꿈이 된다")

    # ⑥ 다시 굽기 ────────────────────────────────────────────────────
    first = bake([box(bold=True, italic=True)])
    pf.subset_fonts_safely(first)
    p1 = root / "styled1.pdf"; first.save(p1, garbage=4, deflate=True); first.close()
    again = bake([box(rect=[0.1, 0.5, 0.9, 0.7], text="휘몰아쳐 뛟퓨", bold=True, italic=True)], fitz.open(p1))
    pf.subset_fonts_safely(again)
    p2 = root / "styled2.pdf"; again.save(p2, garbage=4, deflate=True); again.close()
    t2 = fitz.open(p2)[0].get_text()
    chk("휘몰아쳐" in t2 and "굵기" in t2, "⑥ 굵게·기울임 박스를 다시 구워도 새 글·옛 글이 남는다")
except Exception as e:                                   # noqa: BLE001
    import traceback; traceback.print_exc()
    chk(False, f"예외: {e}")

print("ALL PASS" if not fails else f"FAIL {len(fails)}: {fails}")
sys.stdout.flush()
os._exit(0 if not fails else 1)
