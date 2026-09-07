# -*- coding: utf-8 -*-
"""260907-5: 선·박스 그리기 3건 (마스터 SOT §4.5.10).

사용자 요청(260907):
  ① 색상버튼이 하나도 안 눌린 상태에서 선·박스 버튼을 누르면 **마지막 쓴 색**을
     골라 준다. 쓴 적이 없으면 1번.
  ② '개체 선택' 에서 빈 곳을 좌상→우하로 끌면 그 범위의 **모든 개체**를 고른다.
  ③ 직선은 수평만이 아니라 **어느 각도로든** 그어진다. 단 90° 근처에서는 자석.
"""
import os, sys, tempfile, shutil, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
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
from viewer.widgets.main_view import MainView

root = Path(tempfile.mkdtemp(prefix="polypdf_draw_"))
pdf = root / "doc.pdf"
shutil.copy(Path(_fx.text_pdf()), pdf)

try:
    mv = MainView()
    mv.resize(1000, 900)
    mv.show()
    mv.load_document(pdf, 0)
    app.processEvents()
    mv.set_draw_mode(True)          # 편집모드(그리기 도구 사용 가능)
    mv._img_edit = True
    pr = mv._page_view_rect()
    chk(pr is not None, "페이지 사각형을 얻는다")

    # ── ① 색이 없으면 골라 준다 ─────────────────────────────────────────
    mv._pen_idx = None
    mv._last_pen_idx = None
    mv._draw_kind = None
    mv._toggle_line()
    chk(mv._pen_idx == 0 and mv._draw_tool == ("pen", 0),
        "① 쓴 색이 없으면 선 버튼이 1번 색을 쓴다", str(mv._draw_tool))
    mv._on_draw_pen(2)                          # 3번 색을 골라 쓴 뒤
    chk(mv._last_pen_idx == 2, "① 마지막으로 쓴 색을 기억한다", str(mv._last_pen_idx))
    mv._on_draw_pen(2)                          # 같은 버튼 재클릭 = 해제
    chk(mv._pen_idx is None, "① 같은 색을 다시 누르면 해제된다(전제)")
    mv._draw_kind = None
    mv._toggle_shape()
    chk(mv._pen_idx == 2 and mv._draw_tool == ("pen", 2),
        "① 색이 없으면 박스 버튼이 **마지막 쓴 색**을 되살린다", str(mv._draw_tool))
    mv._pen_idx = None
    mv._draw_kind = "line"
    mv._cycle_draw_mode()                       # 더블클릭(선 종류 변경)도 같다
    chk(mv._pen_idx is not None, "① 선 종류 변경(더블클릭)도 색을 골라 준다")

    # ── ③ 직선: 자유 각도 + 90° 자석 ────────────────────────────────────
    mv.set_draw_line_mode(0)                    # 0=직선
    mv._draw_kind = "line"; mv._pen_idx = 0; mv._apply_tool()
    ov = mv._draw_overlay
    ctr = pr.center()

    def drag_line(dx, dy, shift=False):
        mods = (Qt.KeyboardModifier.ShiftModifier if shift
                else Qt.KeyboardModifier.NoModifier)
        start = QPointF(ctr)
        ov.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        end = QPointF(ctr.x() + dx, ctr.y() + dy)
        ov.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton, mods))
        pts = list(ov._cur["points"]) if ov._cur else []
        ov._cur = None
        if len(pts) < 2:
            return None
        a = mv._norm_to_view(pts[0][0], pts[0][1], pr)
        b = mv._norm_to_view(pts[1][0], pts[1][1], pr)
        return math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x())) % 180.0

    ang = drag_line(0, 200)                     # 아래로만 끌기 = 수직
    chk(ang is not None and abs(ang - 90.0) < 1.0,
        "③ 아래로 끌면 **수직선**이 그어진다(종전에는 수평만 됐다)",
        f"{ang:.1f}도" if ang is not None else "없음")
    ang = drag_line(200, 200)                   # 대각선 45도
    chk(ang is not None and abs(ang - 45.0) < 2.0,
        "③ 대각선도 그대로 그어진다(자유 각도)", f"{ang:.1f}도")
    ang = drag_line(200, 12)                    # 수평에서 3.4도 → 자석
    chk(ang is not None and (abs(ang) < 0.5 or abs(ang - 180) < 0.5),
        "③ 수평 근처는 90° 자석으로 붙는다", f"{ang:.1f}도")
    ang = drag_line(200, 12, shift=True)        # Shift = 자석 해제
    chk(ang is not None and abs(ang) > 1.0,
        "③ Shift 를 누르면 자석이 풀린다(회전 핸들과 같은 규칙)", f"{ang:.1f}도")
    chk(mv.IMG_SNAP_DEG > 0, "③ 자석 임계각이 정해져 있다", f"±{mv.IMG_SNAP_DEG}도")

    # ── ② 개체선택: 범위(고무줄) 선택 ───────────────────────────────────
    mv._page_strokes = []
    mv._img_objects = []
    # 왼쪽 위에 선 2개 + 사진 1개, 오른쪽 아래에 선 1개
    mv._page_strokes.append({"color": "#f00", "width": 3, "alpha": 100,
                             "points": [[0.10, 0.10], [0.20, 0.15]]})
    mv._page_strokes.append({"color": "#f00", "width": 3, "alpha": 100,
                             "points": [[0.12, 0.20], [0.22, 0.25]]})
    mv._page_strokes.append({"color": "#f00", "width": 3, "alpha": 100,
                             "points": [[0.80, 0.80], [0.90, 0.85]]})
    mv._img_objects.append({"pix": QPixmap(20, 20), "data": None,
                            "rect": [0.15, 0.30, 0.10, 0.08],
                            "shape": "rect", "alpha": 100, "rot": 0.0})
    mv._draw_kind = "select"; mv._apply_tool()
    chk(mv._draw_tool == ("select", None), "② 개체선택 도구가 켜진다")

    box = QRectF(pr.left() + 0.05 * pr.width(), pr.top() + 0.05 * pr.height(),
                 0.30 * pr.width(), 0.40 * pr.height())
    n = mv._rubber_pick(box, pr)
    chk(n == 3, "② 범위 안의 선 2개 + 사진 1개를 모두 고른다", f"{n}개")
    chk(sorted(mv._multi_strokes) == [0, 1] and mv._multi_images == [0],
        "② 범위 밖(오른쪽 아래)의 선은 고르지 않는다",
        f"{mv._multi_strokes} / {mv._multi_images}")

    # 함께 이동
    x0 = mv._page_strokes[0]["points"][0][0]
    ix0 = mv._img_objects[0]["rect"][0]
    far = mv._page_strokes[2]["points"][0][0]
    mv._multi_translate(0.05, 0.0)
    chk(abs(mv._page_strokes[0]["points"][0][0] - (x0 + 0.05)) < 1e-6
        and abs(mv._img_objects[0]["rect"][0] - (ix0 + 0.05)) < 1e-6,
        "② 고른 것들이 함께 움직인다(선·사진 같이)")
    chk(abs(mv._page_strokes[2]["points"][0][0] - far) < 1e-6,
        "② 안 고른 것은 그대로 있다")

    # 고른 것 위를 누르면 함께 끌기, 빈 곳은 아니다
    hit = mv._norm_to_view(0.16, 0.12, pr)
    chk(mv._multi_hit(hit, pr) is True, "② 고른 것 위를 누르면 함께 끌기가 된다")
    chk(mv._multi_hit(mv._norm_to_view(0.60, 0.60, pr), pr) is False,
        "② 빈 곳은 함께 끌기가 아니다")

    # 함께 삭제
    n_before = len(mv._page_strokes) + len(mv._img_objects)
    mv._multi_delete()
    chk(len(mv._page_strokes) + len(mv._img_objects) == n_before - 3,
        "② Del 로 고른 것을 함께 지운다", f"{n_before} → "
        f"{len(mv._page_strokes) + len(mv._img_objects)}")
    chk(not mv._has_multi(), "② 지운 뒤에는 선택이 비워진다")

    # 하나만 걸리면 종전 단일 선택으로 넘긴다(핸들을 쓰기 위해)
    mv._page_strokes = [{"shape": "rect", "fill": "none", "color": "#f00",
                         "width": 2, "alpha": 100, "rot": 0.0,
                         "rect": [0.10, 0.10, 0.20, 0.20],
                         "cx": 0.15, "cy": 0.15, "r": 0.0}]
    mv._img_objects = []
    one = QRectF(pr.left() + 0.05 * pr.width(), pr.top() + 0.05 * pr.height(),
                 0.20 * pr.width(), 0.20 * pr.height())
    mv._rubber_pick(one, pr)
    chk(not mv._has_multi() and mv._stroke_selected == 0,
        "② 하나만 걸리면 종전 단일 선택으로 넘긴다(크기·회전 핸들 유지)")

    # 도구를 바꾸면 범위 선택이 풀린다
    mv._page_strokes.append({"color": "#f00", "width": 3, "alpha": 100,
                             "points": [[0.11, 0.11], [0.13, 0.13]]})
    mv._rubber_pick(one, pr)
    chk(mv._has_multi(), "② (전제) 둘이 걸려 범위 선택 상태")
    mv._draw_kind = "line"; mv._apply_tool()
    chk(not mv._has_multi(), "② 다른 도구로 바꾸면 범위 선택이 풀린다")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\n=== " + ("ALL PASS" if not fails else f"FAILURE ({len(fails)})") + " ===")
for m in fails:
    print(" -", m)
sys.stdout.flush()
os._exit(0 if not fails else 1)
