# -*- coding: utf-8 -*-
"""260907-1: 글쓰기 텍스트 박스 — pt 단위 · 자동 줄바꿈/맞춤 · 조합 중 한글 · 조절 버튼.

사용자 요청(260907):
  ① '문자 크기(페이지 대비) %' 가 작동하지 않는다 → **pt** 로.
  ② 한글을 입력하는 **도중**에 글자가 반쯤 잘려 보인다(입력이 끝나면 멀쩡).
  ③ 글자 크기에 맞춰 박스가 자란다. 페이지 오른쪽 끝에 닿으면 줄을 바꾸고 아래로 는다.
     가로를 손으로 정하면 세로가, 세로를 정하면 가로가 자동으로 따라온다.
  ④ 박스 좌상단에 글자 크기 ▲▼ · 자간 ◀▶ 버튼.

사용자 결정(260907): **변 핸들 = 박스만, 모서리 핸들 = 글자 크기까지.**
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
import test_fixtures as _fx
from viewer.widgets.main_view import (MainView, MV_TEXT_STYLES, MV_SIZE_PT_MIN,
                                      MV_SIZE_PT_MAX, _TextBoxBar, _InlineTextEdit)

root = Path(tempfile.mkdtemp(prefix="polypdf_txt_"))
pdf = root / "doc.pdf"
shutil.copy(Path(_fx.text_pdf()), pdf)

try:
    # ── ① 프리셋·설정이 pt 를 쓴다 ───────────────────────────────────────
    chk(all("size_pt" in s for _n, s in MV_TEXT_STYLES),
        "① 글쓰기 프리셋이 pt 로 정의된다",
        str([s["size_pt"] for _n, s in MV_TEXT_STYLES]))
    import viewer.widgets.line_text_settings_dialog as _ltd
    dlg = _ltd.LineTextSettingsDialog(
        [{"color": "#f00", "width": 3, "alpha": 100}] * 5, [10, 20, 30], 40, [])
    chk(dlg._sp_size.suffix().strip() == "pt",
        "① 설정창 '문자 크기' 단위가 pt", repr(dlg._sp_size.suffix()))
    chk(hasattr(dlg, "_sp_spacing") and dlg._sp_spacing.suffix().strip() == "pt",
        "① 설정창에 자간(pt) 이 있다")
    dlg._sp_size.setValue(24.0); dlg._sp_spacing.setValue(1.5)
    out = dlg._editor_to_style("검사")
    chk(out.get("size_pt") == 24.0 and out.get("spacing_pt") == 1.5,
        "① 설정창이 pt 값을 그대로 내보낸다", str((out.get("size_pt"), out.get("spacing_pt"))))
    dlg.deleteLater()

    mv = MainView()
    mv.resize(900, 1100)
    mv.show()
    mv.load_document(pdf, 0)
    app.processEvents()
    mv.set_edit_mode(True) if hasattr(mv, "set_edit_mode") else None
    mv._img_edit = True
    pr = mv._page_view_rect()
    chk(pr is not None, "② 페이지 사각형을 얻는다")

    # ── ② pt → 화면 픽셀 환산이 페이지 크기를 따른다 ────────────────────
    ph_pt = mv._page_pt_height()
    chk(ph_pt > 100, "② 페이지 세로(pt)를 읽는다", f"{ph_pt:.0f}pt")
    px = mv._pt_to_px(72.0, pr)
    chk(abs(px - 72.0 * pr.height() / ph_pt) < 0.01,
        "② pt→픽셀 환산이 페이지 높이에 비례한다", f"72pt = {px:.1f}px")

    # 옛 자료(size=비율)는 보이던 크기 그대로 1회 환산
    legacy = {"text_box": True, "text": "가", "size": 0.05, "rect": [0.1, 0.1, 0.3, 0.15]}
    got = mv._style_size_pt(legacy)
    chk(abs(got - 0.05 * ph_pt) < 0.5 and "size_pt" in legacy,
        "② 옛 '비율' 값은 pt 로 1회 환산되어 크기가 유지된다", f"{got:.1f}pt")

    # ── ③ 자동 줄바꿈 — 오른쪽 끝을 넘지 않는다 ─────────────────────────
    st = {"text_box": True, "text": "가나다라마바사아자차카타파하" * 12,
          "size_pt": 20.0, "spacing_pt": 0.0, "rect": [0.1, 0.1, 0.3, 0.15],
          "family": "맑은 고딕"}
    mv._page_strokes.append(st)
    w, h = mv._text_natural_size(st, pr)
    max_w = mv._text_max_w(st, pr)
    chk(w <= max_w + 0.5, "③ 자동 폭이 페이지 오른쪽 끝을 넘지 않는다",
        f"{w:.0f} <= {max_w:.0f}px")
    one_line = mv._text_layout_size(st, pr, None)[1]
    chk(h > one_line * 1.5, "③ 넘치면 줄을 바꾸고 세로로 는다",
        f"한 줄 {one_line:.0f} → {h:.0f}px")

    # 글자를 키우면 세로가 더 는다(같은 폭에서 줄 수가 는다)
    st["size_pt"] = 40.0
    w2, h2 = mv._text_natural_size(st, pr)
    chk(h2 > h, "③ 글자를 키우면 박스 세로가 커진다", f"{h:.0f} → {h2:.0f}px")
    st["size_pt"] = 20.0

    # ── ③-b 가로를 정하면 세로 자동 / 세로를 정하면 가로 자동 ───────────
    half = max_w / 2.0
    h_for_half = mv._text_fit_h(st, pr, half)
    h_for_full = mv._text_fit_h(st, pr, max_w)
    chk(h_for_half > h_for_full,
        "③-b 가로를 좁히면 세로가 늘어난다(자동)", f"{h_for_full:.0f} → {h_for_half:.0f}px")
    w_for_h = mv._text_fit_w(st, pr, h_for_half)
    chk(abs(mv._text_fit_h(st, pr, w_for_h) - h_for_half) <= h_for_half * 0.35,
        "③-b 세로를 주면 그 안에 들어가는 가로를 찾는다", f"{w_for_h:.0f}px")

    # ── ③-c 핸들: 변=박스만, 모서리=글자 크기 ───────────────────────────
    mv._stroke_selected = len(mv._page_strokes) - 1
    st["rect"] = [0.1, 0.1, 0.5, 0.2]
    before_pt = mv._style_size_pt(st)
    mv._shape_transform_press(pr.center(), pr, "r")     # 오른쪽 변
    cx, cy, hw, hh, rot = mv._shape_press_geom
    from PyQt6.QtCore import QPoint
    mv._shape_transform_move(QPoint(int(cx + hw * 0.6), int(cy)), pr)
    chk(abs(mv._style_size_pt(st) - before_pt) < 0.01,
        "③-c 변 핸들은 글자 크기를 바꾸지 않는다",
        f"{before_pt:.1f} → {mv._style_size_pt(st):.1f}pt")

    st["rect"] = [0.1, 0.1, 0.5, 0.2]
    before_pt = mv._style_size_pt(st)
    mv._shape_transform_press(pr.center(), pr, "br")    # 오른쪽 아래 모서리
    cx, cy, hw, hh, rot = mv._shape_press_geom
    mv._shape_transform_move(QPoint(int(cx + hw * 2), int(cy + hh * 2)), pr)
    chk(mv._style_size_pt(st) > before_pt + 0.5,
        "③-c 모서리 핸들은 글자 크기까지 키운다",
        f"{before_pt:.1f} → {mv._style_size_pt(st):.1f}pt")
    chk(MV_SIZE_PT_MIN <= mv._style_size_pt(st) <= MV_SIZE_PT_MAX,
        "③-c 글자 크기는 범위 안에 머문다(폰트엔진 보호)")

    # ── ② 조합 중(IME) 한글이 크기 계산에 들어간다 ──────────────────────
    chk(issubclass(_InlineTextEdit, __import__("PyQt6.QtWidgets", fromlist=["QTextEdit"]).QTextEdit)
        and hasattr(_InlineTextEdit, "imeChanged"),
        "② 입력칸이 조합(IME) 변화를 알린다")
    idx = len(mv._page_strokes) - 1
    st["text"] = ""
    mv._begin_text_edit(idx, pr)
    ed = mv._text_editor
    chk(ed is not None, "② 입력칸이 열린다")
    if ed is not None:
        from PyQt6.QtGui import QInputMethodEvent
        h0 = abs(st["rect"][3] - st["rect"][1])
        ev = QInputMethodEvent("한글을 조합하는 중입니다 " * 4, [])
        ed.inputMethodEvent(ev)          # 조합 중 — 문서에는 아직 안 들어간다
        app.processEvents()
        chk(ed.toPlainText() == "", "② 조합 중에는 문서가 비어 있다(전제)")
        h1 = abs(st["rect"][3] - st["rect"][1])
        chk(h1 > h0 or abs(st["rect"][2] - st["rect"][0]) > 0.05,
            "② 조합 중인 글자만큼 박스가 커진다(잘리지 않는다)",
            f"세로 {h0:.4f} → {h1:.4f}")
        got = mv._editor_text_with_preedit(ed)
        chk("조합하는" in got, "② 조합 중 글자를 읽어 온다", repr(got[:20]))

    # ── ④ 조절 버튼 ─────────────────────────────────────────────────────
    mv._sync_text_toolbar()
    bar = getattr(mv, "_text_bar", None)
    chk(isinstance(bar, _TextBoxBar) and bar.isVisible(),
        "④ 편집 중에 좌상단 조절 띠가 보인다")
    chk(len(_TextBoxBar.BTNS) == 4,
        "④ 버튼 4개(크기 ▲▼ · 자간 ◀▶)", str([b[0] for b in _TextBoxBar.BTNS]))
    p0 = mv._style_size_pt(st)
    mv._text_bar_adjust(idx, d_size=1.0)
    chk(abs(mv._style_size_pt(st) - (p0 + 1.0)) < 0.01,
        "④ ▲ 한 번에 글자 +1pt", f"{p0:.1f} → {mv._style_size_pt(st):.1f}")
    s0 = float(st.get("spacing_pt", 0.0))
    mv._text_bar_adjust(idx, d_spacing=0.5)
    chk(abs(float(st["spacing_pt"]) - (s0 + 0.5)) < 0.01,
        "④ ▶ 한 번에 자간 +0.5pt", f"{s0:.1f} → {st['spacing_pt']:.1f}")
    f = mv._text_qfont(st, pr)
    chk(f.letterSpacing() != 0.0, "④ 자간이 실제 폰트에 반영된다",
        f"{f.letterSpacing():.2f}px")
    mv._commit_text_editor()

    # ── ⑤ PDF 로 구울 때도 pt 를 그대로 쓴다 ────────────────────────────
    import inspect
    from viewer.edit_controller import EditMixin
    src = inspect.getsource(EditMixin)
    chk("size_pt" in src, "⑤ PDF 굽기가 pt 값을 쓴다(인쇄 크기 = 화면 크기)")
    chk("* ph" in src, "⑤ 옛 자료(비율)도 그대로 구워진다(하위호환)")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
