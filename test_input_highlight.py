# -*- coding: utf-8 -*-
"""260912-7: 하이라이트 세 가지 (입력 장치 SOT §2.5·§2.6·§2.7).

사용자 보고·지시
  ① "편집모드에서 하이라이트로 선택한 후 마우스로 끌어서 글자를 골랐는데,
     한 줄만 선택되고 아래 줄은 연이어서 선택되지 않음"      → §2.5
  ② "텍스트 창 선택시 본문을 강조하다가, 본문을 선택시에는 강조가 없어지도록" → §2.6
  ③ "텍스트 창에서 칠하면 본문에도 칠하는 옵션. 1번 색상을 적용"            → §2.7

**함수가 있는가로 보지 않는다** — 띠가 몇 개 생기는지, 무엇이 지워지고 무엇이
남는지를 실제로 센다.
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

import fitz
from PyQt6.QtWidgets import QApplication
from viewer.widgets import main_view as mv

app = QApplication.instance() or QApplication(sys.argv)
fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra if not cond else "")
    if not cond:
        fails.append(msg)


root = tempfile.mkdtemp(prefix="polypdf_hl_")
try:
    # 한 문단이 세 줄에 걸친 쪽
    src = os.path.join(root, "hl.pdf")
    doc = fitz.open()
    pg = doc.new_page(width=400, height=560)
    for i in range(3):
        pg.insert_text((40, 100 + i * 30), "line %d of the paragraph" % (i + 1),
                       fontsize=12)
    doc.save(src)
    doc.close()

    from viewer.app import MainWindow
    from viewer.history import HistoryItem
    mw = MainWindow(); mw.resize(1200, 800); mw.show(); app.processEvents()
    mw._load_main(HistoryItem(src, 0, "", "bookmark")); app.processEvents()
    m = mw.main_view

    # ── ① 여러 줄에 걸친 하이라이트 (§2.5) ────────────────────────────
    lines = m._hl_lines()
    chk(len(lines) >= 3, "① 글줄을 찾는다", "%d줄" % len(lines))
    (lx0, ly0, lx1, ly1) = lines[0]
    (mx0, my0, mx1, my1) = lines[1]
    (ex0, ey0, ex1, ey1) = lines[2]

    one = m._hl_bands_between((lx0 + 0.01, (ly0 + ly1) / 2),
                              (lx1 - 0.01, (ly0 + ly1) / 2))
    chk(len(one) == 1, "① 한 줄 안에서 끌면 띠 하나", "%d개" % len(one))

    two = m._hl_bands_between((lx0 + 0.01, (ly0 + ly1) / 2),
                              (mx0 + 0.05, (my0 + my1) / 2))
    chk(len(two) == 2, "① 두 줄에 걸치면 띠 둘", "%d개" % len(two))

    three = m._hl_bands_between((lx0 + 0.01, (ly0 + ly1) / 2),
                                (ex0 + 0.03, (ey0 + ey1) / 2))
    chk(len(three) == 3, "① 세 줄에 걸치면 띠 셋", "%d개" % len(three))
    chk(abs(three[0][1] - lx1) < 1e-6,
        "① 첫 줄은 **그 줄 오른끝까지** 칠한다", str(three[0]))
    chk(abs(three[1][0] - mx0) < 1e-6 and abs(three[1][1] - mx1) < 1e-6,
        "① 가운데 줄은 통째로", str(three[1]))
    chk(three[2][1] < ex1, "① 마지막 줄은 놓은 자리까지만", str(three[2]))

    up = m._hl_bands_between((ex0 + 0.03, (ey0 + ey1) / 2),
                             (lx0 + 0.01, (ly0 + ly1) / 2))
    chk(len(up) == 3 and up == three,
        "① 아래에서 위로 끌어도 같다", "%s" % (up,))

    # 옛 기록(띠 하나짜리)도 그대로 보인다
    oldst = {"hl": True, "h": 0.012, "points": [[0.1, 0.3], [0.6, 0.3]]}
    ob = mv.hl_bands(oldst)
    chk(ob == [(0.1, 0.6, 0.3, 0.012)],
        "① 옛 기록은 띠 하나로 그대로 보인다", str(ob))
    chk(mv.hl_bands({"hl": True, "bands": [[0, 1, 0.5, 0.01]]}) ==
        [(0.0, 1.0, 0.5, 0.01)], "① 새 기록은 띠 목록 그대로")

    # ① 진짜 끌기 — 누름→움직임 처리기를 그대로 태운다.
    #   사각형 계산만 보면 처리기가 망가져도 몰라 검사가 헛도는다(실제로 놓쳤다).
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import Qt as _Qt
    pr = m._page_view_rect()
    chk(pr is not None, "① (전제) 쪽 사각형을 얻는다")
    if pr is not None:
        m.set_draw_line_mode(1)                 # 1 = 하이라이트
        m._draw_kind = "line"; m._pen_idx = 0; m._apply_tool()
        ov = m._draw_overlay
        p0 = m._norm_to_view(lx0 + 0.02, (ly0 + ly1) / 2, pr)
        p1 = m._norm_to_view(ex0 + 0.03, (ey0 + ey1) / 2, pr)
        ov.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(p0), _Qt.MouseButton.LeftButton,
            _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier))
        ov.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, QPointF(p1), _Qt.MouseButton.NoButton,
            _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier))
        cur = ov._cur or {}
        nb = len(mv.hl_bands(cur)) if cur else 0
        chk(nb == 3, "① **끌기로** 세 줄을 지나면 띠 셋", "%d개" % nb)
        ov._cur = None
        m._draw_kind = None; m._pen_idx = None; m._apply_tool()

    # ── ② 본문을 누르면 텍스트 창 강조만 사라진다 (§2.6) ──────────────
    m.highlight_word_rects([(10, 10, 100, 24)], style="select", src="text_panel")
    chk(len(m._word_hl_groups) == 1, "② 텍스트 창이 강조를 건다")
    m._drop_panel_highlight()
    chk(not m._word_hl_groups, "② 본문을 누르면 그 강조가 사라진다",
        str(m._word_hl_groups))

    m.highlight_word_rects([(10, 10, 100, 24)], style="read", src="read_aloud")
    m._drop_panel_highlight()
    chk(len(m._word_hl_groups) == 1,
        "② **읽기가 건 강조는 남는다** — 본문을 눌렀다고 읽기가 끝난 것이 아니다",
        str(m._word_hl_groups))
    m.clear_word_highlights()

    # ── ③ 텍스트 창 → 본문 표시 옵션 (§2.7) ───────────────────────────
    tp = mw.text_panel
    chk(hasattr(tp, "cb_mark_pdf"), "③ '본문에도 표시' 체크상자가 있다")
    chk(tp.mark_pdf_enabled() is False, "③ 기본은 꺼짐 — 묻지 않고 자국을 남기지 않는다")
    chk(mw._prefs.get("text_hl_mark_pdf") is False,
        "③ **설정 기본값**도 꺼짐이다 — 여기가 진짜 소유자다",
        str(mw._prefs.get("text_hl_mark_pdf")))

    before = len(m._page_strokes)
    pgr = m._doc.doc.load_page(0)
    pw, ph = pgr.rect.width, pgr.rect.height
    mw._on_text_highlight_mark(0, [(40.0, 90.0, 300.0, 104.0),
                                   (40.0, 120.0, 300.0, 134.0)])
    chk(len(m._page_strokes) == before + 1,
        "③ 획 **하나**로 얹는다 — 한 번 칠한 것은 한 번에 지워져야 한다",
        "%d → %d" % (before, len(m._page_strokes)))
    st = m._page_strokes[-1]
    chk(st.get("hl") is True, "③ 하이라이트 획이다")
    chk(len(mv.hl_bands(st)) == 2, "③ 줄 수만큼 띠가 있다", str(mv.hl_bands(st)))
    from viewer.widgets.main_view import MV_DEFAULT_PENS
    pens = getattr(m, "_draw_pens", None) or MV_DEFAULT_PENS
    chk(m._pen_idx is None, "③ 지금은 색상버튼을 고르지 않은 상태다",
        str(m._pen_idx))
    chk(st.get("color") == pens[0].get("color"),
        "③ 색상버튼을 안 골랐으면 **선 1** 색",
        "%s != %s" % (st.get("color"), pens[0].get("color")))

    #   보충 지시(260912-7): 골랐으면 **그 색**을 쓴다
    m._pen_idx = 2
    mw._on_text_highlight_mark(0, [(40.0, 90.0, 300.0, 104.0)])
    st2 = m._page_strokes[-1]
    chk(st2.get("color") == pens[2].get("color"),
        "③ 색상버튼을 골랐으면 **그 색**을 쓴다",
        "%s != %s" % (st2.get("color"), pens[2].get("color")))
    chk(st2.get("color") != pens[0].get("color"),
        "③ 그때는 선 1 색이 아니다")
    m._pen_idx = None
    chk(all(0.0 <= b[0] <= 1.0 and 0.0 <= b[2] <= 1.0 for b in mv.hl_bands(st)),
        "③ 정규화 좌표로 저장한다", str(mv.hl_bands(st)))

    # 다른 쪽이면 얹지 않는다 — 자리가 어긋난다
    n2 = len(m._page_strokes)
    mw._on_text_highlight_mark(7, [(40.0, 90.0, 300.0, 104.0)])
    chk(len(m._page_strokes) == n2, "③ 다른 쪽이면 얹지 않는다")

    # 설정에 남는다
    chk("text_hl_mark_pdf" in mw._prefs, "③ 설정 값이 있다")
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("=== ALL PASS ===" if not fails else "=== FAILURE (%d) ===" % len(fails))
for f in fails:
    print(" -", f)
sys.stdout.flush()
os._exit(1 if fails else 0)
