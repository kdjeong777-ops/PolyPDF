# -*- coding: utf-8 -*-
"""261031-9: 도형·글쓰기 ▾ 에서 고르면 그 도구가 켜진다 (마스터 SOT §4.6.10).

사용자 지시(261031): 박스·텍스트 드롭다운 메뉴를 고르면 그 단추가 선택돼 본문에 바로 쓸 수 있게 —
도형을 쓰다가 글쓰기 ▾ 의 '제목' 을 고르면 글쓰기 단추가 켜진다.
메뉴 항목은 실제 QAction.trigger 로 누른다(처리기 직접 호출이 아니라 연결된 길로, 마스터 §14.7.2).
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
# 사용자 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_draw_dropdown_%d" % os.getpid())
import test_fixtures as _fx
from viewer.widgets.main_view import MainView

root = Path(tempfile.mkdtemp(prefix="polypdf_dropdown_"))
pdf = root / "doc.pdf"
shutil.copy(Path(_fx.text_pdf()), pdf)


def action(menu, data):
    return next((a for a in menu.actions() if a.data() == data), None)


try:
    mv = MainView()
    mv.resize(1000, 900)
    mv.show()
    mv.load_document(pdf, 0)
    app.processEvents()
    mv.set_draw_mode(True)
    app.processEvents()

    styles = [a.data() for a in mv._text_menu.actions()]
    chk(len(styles) >= 2, "글쓰기 ▾ 에 저장 스타일이 있다(전제)", str(styles))
    title = styles[1] if len(styles) > 1 else styles[0]

    # ── 글쓰기 ▾: 여러 도구 상태에서 고르면 글쓰기가 켜진다 ─────────────
    def to_shape():
        mv._draw_kind = None; mv._toggle_shape()

    def to_line():
        mv._draw_kind = None; mv._toggle_line()

    def to_select():
        mv._draw_kind = None; mv._on_draw_select()

    def to_erase():
        mv._draw_kind = None; mv._on_draw_erase(0)

    def to_none():
        mv._draw_kind = None; mv._apply_tool()

    for nm, setup in (("도형", to_shape), ("선긋기", to_line), ("개체선택", to_select),
                      ("지우개", to_erase), ("도구 없음", to_none)):
        setup()
        before = mv._draw_kind
        action(mv._text_menu, title).trigger()
        app.processEvents()
        chk(mv._draw_kind == "text" and mv._draw_tool is not None and mv._draw_tool[0] == "pen",
            f"글쓰기 ▾ '{title}' — {nm}({before}) 상태에서 글쓰기 도구가 켜진다",
            f"{mv._draw_kind} {mv._draw_tool}")
        chk(mv._text_style == title, f"글쓰기 ▾ — 스타일도 '{title}' 로 바뀐다({nm})", mv._text_style)
        chk("#ff7a00" in mv._text_btn.styleSheet(), f"글쓰기 단추가 켜진 모양이다({nm})")

    # 이미 켜진 글쓰기에서 다시 고르면 꺼지지 않는다
    action(mv._text_menu, styles[0]).trigger(); app.processEvents()
    chk(mv._draw_kind == "text", "글쓰기가 켜진 채 ▾ 를 다시 고르면 꺼지지 않는다", str(mv._draw_kind))

    # ── 도형 ▾ ────────────────────────────────────────────────────────
    mv._pen_idx = None; mv._last_pen_idx = None
    mv._draw_kind = None; mv._toggle_text()           # 글쓰기 사용 중
    chk(mv._draw_kind == "text", "글쓰기 사용 중(전제)")
    action(mv._shape_menu, "semi").trigger(); app.processEvents()
    chk(mv._draw_kind == "shape" and mv._draw_tool == ("pen", 0),
        "도형 ▾ '반투명 채움' — 글쓰기 중에도 도형 도구가 켜지고 색이 없으면 1번", str(mv._draw_tool))
    chk(mv._shape_fill == "semi", "도형 ▾ — 채움도 바뀐다", mv._shape_fill)
    chk("#ff7a00" in mv._shape_btn.styleSheet(), "도형 단추가 켜진 모양이다")
    action(mv._shape_menu, "full").trigger(); app.processEvents()
    chk(mv._draw_kind == "shape" and mv._shape_fill == "full",
        "도형이 켜진 채 ▾ 를 다시 고르면 꺼지지 않는다", str(mv._draw_kind))

    # ── 스타일 다시 적용(설정 저장 길)은 도구를 켜지 않는다 ────────────
    mv._draw_kind = None; mv._apply_tool()
    mv.set_text_styles(mv._text_styles)
    app.processEvents()
    chk(mv._draw_kind is None, "set_text_styles(스타일 다시 적용)는 도구를 켜지 않는다", str(mv._draw_kind))
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
