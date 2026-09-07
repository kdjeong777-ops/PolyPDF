# -*- coding: utf-8 -*-
"""260907-3/4: 다른 기능을 고르면 그리기 도구를 끄고, **첫 드래그가 살아 있어야 한다**.

사용자 보고(260907, 두 번): 선긋기·하이라이트를 쓰던 중 '텍스트 복사'나 '블럭설정 후
텍스트 복사'를 골라도, 사진을 넣은 뒤에도 **아무 일도 일어나지 않는 것처럼** 보였다.

원인은 두 겹이었다.
  ① 도구가 켜진 채라 본문 드래그를 그 도구가 가로챘다(260907-3에서 `_cancel_draw_tools`).
  ② 도구를 껐어도 **골라 둔 사진이 남아 있으면 첫 클릭이 '선택 해제' 에 쓰이고 사라져**
     드래그가 시작되지 않았다(260907-4). 커서도 호버 처리가 십자를 지워, 블럭설정이
     안 걸린 것처럼 보였다.

검사 대상(마스터 SOT §4.5.9):
  ① 취소 진입점이 도구·선택을 모두 푼다
  ② 텍스트 선택이 열린다(`_text_sel_ok`)
  ③ **첫 누름이 먹히지 않는다** — 선긋기 뒤에도, 사진을 넣은 뒤에도
  ④ 블럭설정은 무장되고 커서(십자)가 유지된다
  ⑤ 사진을 넣으면 개체선택으로 넘어가고 곧바로 선택돼 있다
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QPixmap

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
app.setApplicationName("PolyPDF")
app.setOrganizationName("LocalTools")
import test_fixtures as _fx
from viewer.app import MainWindow

root = Path(tempfile.mkdtemp(prefix="polypdf_cancel_"))
pdf = root / "doc.pdf"
shutil.copy(Path(_fx.text_pdf()), pdf)

try:
    mw = MainWindow()
    mw._skip_save_on_close = True
    mw.resize(1000, 900)
    mw.show()
    mw.open_pdf(pdf)
    app.processEvents()
    mv = mw.main_view
    mv._img_edit = True                      # 편집모드(그리기 도구가 사는 조건)
    pr = mv._page_view_rect()
    chk(pr is not None, "페이지 사각형을 얻는다")
    ctr = pr.center()
    empty = pr.topLeft() + (ctr - pr.topLeft()) / 8      # 개체가 없는 지점

    def arm_pen():
        mv.set_draw_tool(("pen", 0))
        mv._draw_kind = "line"
        mv._apply_tool()

    def press(pos):
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(pos),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        return bool(mv.eventFilter(mv.view.viewport(), ev))

    # ── ① 취소 진입점 ────────────────────────────────────────────────────
    chk(callable(getattr(mw, "_cancel_draw_tools", None)), "① 취소 진입점이 있다")
    arm_pen()
    chk(mv._draw_tool is not None and not mv.view._text_sel_ok(),
        "① 선긋기 중에는 텍스트 선택이 막혀 있다(전제)", str(mv._draw_tool))
    mw._cancel_draw_tools()
    chk(mv._draw_tool is None and mv._draw_kind is None and mv._pen_idx is None,
        "① 취소하면 도구가 완전히 풀린다", str(mv._draw_tool))
    chk(mv._img_selected == -1 and mv._stroke_selected == -1,
        "① 골라 둔 사진·선도 함께 푼다(첫 클릭이 선택 해제로 사라지지 않게)")

    # ── ② 텍스트 선택이 열린다 ──────────────────────────────────────────
    chk(mv.view._text_sel_ok(), "② 취소 뒤에는 본문 텍스트 선택이 열린다")

    # ── ③ 첫 누름이 먹히지 않는다 ───────────────────────────────────────
    for name, with_image, block in (("선긋기 → 텍스트 복사", False, False),
                                    ("사진 삽입 → 텍스트 복사", True, False),
                                    ("선긋기 → 블럭설정", False, True),
                                    ("사진 삽입 → 블럭설정", True, True)):
        mv._img_objects = []
        mv._img_selected = -1
        arm_pen()
        if with_image:
            pm = QPixmap(40, 30); pm.fill()
            mv.add_image_from_pixmap(pm)
            arm_pen()                        # 다시 선긋기로 돌려 놓고
        mw._cancel_draw_tools()
        if block:
            mv.arm_text_selection()
        chk(press(empty) is False, f"③ '{name}' 뒤 첫 누름이 살아 있다")

    # ── ④ 블럭설정 무장·커서 유지 ───────────────────────────────────────
    arm_pen()
    mw._cancel_draw_tools()
    mv.arm_text_selection()
    chk(getattr(mv.view, "_block_armed", False) is True, "④ 블럭설정이 무장된다")
    cur_before = mv.view.viewport().cursor().shape()
    chk(cur_before == Qt.CursorShape.CrossCursor, "④ 커서가 십자로 바뀐다",
        str(cur_before))
    mv._img_update_hover_cursor(empty, pr)          # 마우스를 움직여도
    chk(mv.view.viewport().cursor().shape() == Qt.CursorShape.CrossCursor,
        "④ 호버 처리가 십자를 지우지 않는다",
        str(mv.view.viewport().cursor().shape()))

    # ── ⑤ 사진 삽입 → 개체선택 + 즉시 선택 ──────────────────────────────
    mv.view._block_armed = False
    arm_pen()
    pm = QPixmap(60, 50); pm.fill()
    n0 = len(mv._img_objects)
    mv.add_image_from_pixmap(pm)
    chk(len(mv._img_objects) == n0 + 1, "⑤ 사진이 들어간다")
    chk(mv._draw_tool == ("select", None),
        "⑤ 선긋기 중에 넣어도 개체선택으로 바뀐다", str(mv._draw_tool))
    chk(mv._img_selected == len(mv._img_objects) - 1,
        "⑤ 넣은 사진이 곧바로 선택돼 있다(바로 옮길 수 있다)")
    idx, _h = mv._img_hit(mv._page_view_rect().center(), mv._page_view_rect())
    chk(idx >= 0, "⑤ 가운데에 놓여 바로 집을 수 있다", f"idx={idx}")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
