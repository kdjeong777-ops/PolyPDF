# -*- coding: utf-8 -*-
"""261107-36: 꾸미기 줄 손바닥 도구 — 끌어서 화면 옮기기 (입력 SOT §4.1, 마스터 §4.6.12).

사용자 지시(261107): "본화면 위 꾸미기 버튼에 화면을 잡고 원하는 부분으로 화면을 이동시키는 손바닥 아이콘 추가.
개체선택 버튼 오른쪽".
마우스는 실제 QMouseEvent 를 본문 뷰포트에 보낸다(MainView.eventFilter 가 받는 길 그대로, 마스터 §14.7.2).
"""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QKeyEvent

fails = []


def chk(cond, msg, extra=""):
    print(("PASS" if cond else "FAIL"), "-", msg, extra)
    if not cond:
        fails.append(msg)


app = QApplication.instance() or QApplication(sys.argv)
# 사용자 실제 설정 폴더를 쓰지 않는다 — 마스터 §14.7.2 의 3
from PyQt6.QtCore import QStandardPaths, QCoreApplication
QStandardPaths.setTestModeEnabled(True)
QCoreApplication.setApplicationName("polypdf_hand_pan_%d" % os.getpid())
import test_fixtures as _fx
from viewer.widgets.main_view import MainView

root = Path(tempfile.mkdtemp(prefix="polypdf_hand_"))
pdf = root / "doc.pdf"
shutil.copy(Path(_fx.text_pdf()), pdf)

L = Qt.MouseButton.LeftButton
NO = Qt.MouseButton.NoButton
NM = Qt.KeyboardModifier.NoModifier


def mouse(mv, kind, pt, button, buttons):
    vp = mv.view.viewport()
    QApplication.sendEvent(vp, QMouseEvent(kind, QPointF(pt), QPointF(vp.mapToGlobal(pt.toPoint())),
                                           button, buttons, NM))
    app.processEvents()


def drag(mv, dx, dy, steps=4):
    vp = mv.view.viewport()
    c = QPointF(vp.width() / 2, vp.height() / 2)
    mouse(mv, QEvent.Type.MouseButtonPress, c, L, L)
    for i in range(1, steps + 1):
        mouse(mv, QEvent.Type.MouseMove, QPointF(c.x() + dx * i / steps, c.y() + dy * i / steps), NO, L)
    mouse(mv, QEvent.Type.MouseButtonRelease, QPointF(c.x() + dx, c.y() + dy), L, NO)


def bars(mv):
    return mv.view.horizontalScrollBar().value(), mv.view.verticalScrollBar().value()


def cursor(mv):
    return mv.view.viewport().cursor().shape()


try:
    mv = MainView()
    mv.resize(900, 700)
    mv.show()
    mv.load_document(pdf, 0)
    app.processEvents()
    mv.set_draw_mode(True)
    mv._zoom_by(3.0)                   # 가로·세로 모두 스크롤 자리가 생기게
    app.processEvents()
    hsb, vsb = mv.view.horizontalScrollBar(), mv.view.verticalScrollBar()
    chk(hsb.maximum() > 200 and vsb.maximum() > 200, "확대해서 가로·세로 스크롤 자리가 있다(전제)",
        f"h={hsb.maximum()} v={vsb.maximum()}")
    hsb.setValue(hsb.maximum() // 2); vsb.setValue(vsb.maximum() // 2)
    app.processEvents()

    # ── 단추 자리: 개체선택 바로 오른쪽 ────────────────────────────────
    pb = getattr(mv, "_draw_pan_btn", None)
    chk(pb is not None, "손바닥 단추가 있다")
    lay = mv._draw_select_btn.parentWidget().layout()
    idx = [lay.itemAt(i).widget() for i in range(lay.count())]
    chk(pb in idx and idx.index(pb) == idx.index(mv._draw_select_btn) + 1, "손바닥 단추는 개체선택 바로 오른쪽이다")
    chk(pb is not None and not pb.icon().isNull() and pb.text() == "", "손바닥 단추는 글자가 아니라 아이콘이다")

    # ── 꺼져 있으면 같은 끌기는 막대를 안 움직인다(대조) ──────────────
    b0 = bars(mv)
    drag(mv, 120, 90)
    chk(bars(mv) == b0, "손바닥이 꺼져 있으면 끌기가 화면을 옮기지 않는다(대조 — 글 선택 길)", f"{b0}→{bars(mv)}")
    mv.clear_text_selection()
    hovered = []
    mv.view.hoverWord.connect(hovered.append)
    mv.view.set_hover_words([(0, 0, 100000, 100000, "단어")])
    vp = mv.view.viewport()
    mouse(mv, QEvent.Type.MouseMove, QPointF(vp.width() / 2, vp.height() / 2), NO, NO)
    chk(hovered == ["단어"], "손바닥이 꺼져 있으면 단어 호버가 돈다(대조)", str(hovered))

    # ── 켜고 끌기 ──────────────────────────────────────────────────────
    pb.click(); app.processEvents()
    hovered.clear(); mv.view._last_hover = None
    mouse(mv, QEvent.Type.MouseMove, QPointF(vp.width() / 2 + 5, vp.height() / 2), NO, NO)
    chk(hovered == [], "손바닥이 켜져 있으면 단어 호버(포인터·행 고르기)가 돌지 않는다", str(hovered))
    hl = getattr(mv, "_hl_overlay", None)
    chk(hl is None or hl.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents),
        "손바닥이 켜져 있으면 하이퍼링크 단추는 마우스를 통과시킨다")
    mv.view.set_hover_words([])
    chk(mv._draw_kind == "pan" and mv._draw_tool == ("pan", None) and pb.isChecked(), "단추를 누르면 손바닥이 켜진다",
        f"{mv._draw_kind} {mv._draw_tool}")
    chk(cursor(mv) == Qt.CursorShape.OpenHandCursor, "켜지면 포인터가 펼친 손이다", str(cursor(mv)))
    n_strokes = len(mv._page_strokes)
    b0 = bars(mv)
    vp = mv.view.viewport()
    c = QPointF(vp.width() / 2, vp.height() / 2)
    mouse(mv, QEvent.Type.MouseButtonPress, c, L, L)
    chk(cursor(mv) == Qt.CursorShape.ClosedHandCursor, "누른 동안 포인터는 쥔 손이다", str(cursor(mv)))
    for i in range(1, 5):
        mouse(mv, QEvent.Type.MouseMove, QPointF(c.x() + 30 * i, c.y() + 20 * i), NO, L)
    mouse(mv, QEvent.Type.MouseButtonRelease, QPointF(c.x() + 120, c.y() + 80), L, NO)
    b1 = bars(mv)
    chk(b1 == (b0[0] - 120, b0[1] - 80), "오른쪽 아래로 120·80 끌면 화면이 그만큼 따라온다(막대 −120·−80)", f"{b0}→{b1}")
    chk(cursor(mv) == Qt.CursorShape.OpenHandCursor, "놓으면 다시 펼친 손", str(cursor(mv)))
    chk(not mv.view._dragging and mv.view._press_scene is None, "손바닥 끌기는 글 선택을 시작하지 않는다")
    chk(len(mv._page_strokes) == n_strokes, "손바닥 끌기는 그림을 만들지 않는다")
    drag(mv, -50, -40)
    chk(bars(mv) == (b1[0] + 50, b1[1] + 40), "반대로 끌면 반대로 옮겨진다", f"{b1}→{bars(mv)}")

    # ── 배타 ──────────────────────────────────────────────────────────
    mv._on_draw_select(); app.processEvents()
    chk(mv._draw_kind == "select" and not pb.isChecked() and mv._draw_select_btn.isChecked(),
        "개체선택을 누르면 손바닥이 꺼진다(배타)")
    chk(cursor(mv) != Qt.CursorShape.OpenHandCursor, "손바닥이 꺼지면 포인터가 돌아온다", str(cursor(mv)))
    pb.click(); app.processEvents()
    chk(mv._draw_kind == "pan" and not mv._draw_select_btn.isChecked(), "손바닥을 누르면 개체선택이 꺼진다(배타)")
    mv._toggle_line(); app.processEvents()
    chk(mv._draw_kind == "line" and not pb.isChecked(), "선긋기를 켜면 손바닥이 꺼진다(배타)")
    pb.click(); app.processEvents()
    pb.click(); app.processEvents()
    chk(mv._draw_kind is None and mv._draw_tool is None, "손바닥을 다시 누르면 꺼진다 — 도구 없음")

    # ── Esc ───────────────────────────────────────────────────────────
    pb.click(); app.processEvents()
    QApplication.sendEvent(mv.view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, NM))
    app.processEvents()
    chk(mv._draw_kind is None and mv._draw_tool is None and not pb.isChecked(), "Esc 를 누르면 손바닥이 꺼진다")

    # ── 편집 모드를 나가면 꺼진다 ─────────────────────────────────────
    pb.click(); app.processEvents()
    mv.set_draw_mode(False); app.processEvents()
    chk(mv._draw_tool is None, "편집 모드를 나가면 손바닥이 꺼진다")
    mv.set_draw_mode(True); app.processEvents()

    # ── 이어 보기: 아래로 계속 밀면(위로 끌면) 다음 쪽이 지금 쪽이 된다 ──
    cm = MainView()
    cm.resize(900, 700); cm.show()
    cm.set_page_scroll_mode("continuous")
    cm.load_document(pdf, 0)
    app.processEvents()
    cm.set_draw_mode(True)
    cm._on_draw_pan(); app.processEvents()
    p0 = cm.current_page()
    for _ in range(12):
        drag(cm, 0, -200, steps=2)
        app.processEvents()
        if cm.current_page() != p0:
            break
    chk(cm.current_page() == p0 + 1, "이어 보기에서 손바닥으로 위로 끌어 내려가면 다음 쪽이 지금 쪽이 된다",
        f"{p0}→{cm.current_page()}")

    # ── 단축키 표: draw_pan 이 있고 기본 키가 겹치지 않는다 ───────────
    import re
    src = (Path(__file__).parent / "viewer" / "app.py").read_text(encoding="utf-8")
    defs = re.findall(r'\("(\w+)",\s*\(tr\("[^"]*"\),\s*"([^"]+)"', src[src.index("self._sc_defs = OrderedDict"):])
    keys = dict(defs)
    chk(keys.get("draw_pan") == "Ctrl+H", "단축키 설정에 손바닥(draw_pan) Ctrl+H 가 있다", str(keys.get("draw_pan")))
    chk(list(keys.values()).count("Ctrl+H") == 1, "Ctrl+H 는 다른 기본 키와 겹치지 않는다")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)          # 종료 때 Qt 소멸 크래시를 피한다(다른 입력 검사와 같다)
