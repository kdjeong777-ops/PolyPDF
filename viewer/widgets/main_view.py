"""중앙 메인 뷰어 — v1.5.0 (1.4.2 1:1 직접 렌더 + 2장 보기 모드 M3).

핵심 변경 (v1.4.2):
 - 고정 DPI 렌더 후 Qt 가 fitInView 로 스케일 → 흐림. 폐기.
 - 표시 영역에 맞는 픽셀 크기를 먼저 계산해 PyMuPDF 가 그 크기로 직접 rasterize.
 - 뷰 transform 은 항상 identity. resize/zoom 시 재렌더.
 - 결과: alPDF / Adobe 와 동등한 텍스트 선명도.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import fitz
from PyQt6.QtCore import Qt, QRect, QRectF, QPoint, QSize, QEvent, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QBrush, QIcon, QKeyEvent, QWheelEvent,
    QTransform,
)
from PyQt6.QtWidgets import (
    QGraphicsScene,
    QGraphicsView,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QToolButton,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QSpinBox,
    QScrollBar,
)

from viewer.pdf_doc import PdfDocument
from viewer.resources_path import resource_path


def _hyperlink_icon(ln: dict) -> str:
    """260611-107: 하이퍼링크 종류별 아이콘 — 사진/영상/유튜브/파일/링크."""
    target = str(ln.get("target", ""))
    if ln.get("kind") == "url":
        try:
            from viewer.widgets.media_overlay import is_youtube_url
            if is_youtube_url(target):
                return "▶️"          # 외부 영상(유튜브)
        except Exception:
            pass
        return "🔗"                  # 일반 웹링크
    # 파일 링크 — 확장자로 사진/영상 구분
    try:
        from viewer.widgets.media_overlay import media_kind
        k = media_kind(target)
        if k == "image":
            return "🖼️"             # 사진
        if k == "video":
            return "🎬"             # 영상
    except Exception:
        pass
    return "📄"                      # 일반 파일


# 260609-22(J3) / 260611-1: 본문 선긋기 기본 펜(본문 전용 5개, 발표와 분리)
MV_DEFAULT_PENS = [
    {"name": "선 1", "color": "#ff3030", "width": 3, "alpha": 100},
    {"name": "선 2", "color": "#30a0ff", "width": 4, "alpha": 100},
    {"name": "선 3", "color": "#ffd400", "width": 14, "alpha": 40},
    {"name": "선 4", "color": "#23c552", "width": 3, "alpha": 100},
    {"name": "선 5", "color": "#a050ff", "width": 14, "alpha": 40},
]

# 260611-74(Phase2): 글쓰기 텍스트 박스 스타일 프리셋(버튼 ▾ 풀다운에서 선택).
#   size = 페이지 높이 대비 글자 크기(정규화), bg/border = None 또는 색.
MV_TEXT_STYLES = [
    ("본문", {"size": 0.022, "color": "#111111", "bold": False, "italic": False,
              "bg": None, "border": None}),
    ("제목", {"size": 0.040, "color": "#0b3d91", "bold": True, "italic": False,
              "bg": None, "border": None}),
    ("메모", {"size": 0.020, "color": "#5a4500", "bold": False, "italic": False,
              "bg": "#fff7c0", "border": "#d9c25a"}),
    ("강조", {"size": 0.024, "color": "#c0143c", "bold": True, "italic": False,
              "bg": "#ffe2e8", "border": "#c0143c"}),
]
MV_TEXT_STYLE_MAP = {n: s for n, s in MV_TEXT_STYLES}
# 260611-74: 지시선 화살표 끝 모양
MV_LEADER_TIPS = ("arrow", "circle", "plain")


def smooth_polyline_path(pts):
    """260611-83: 자유곡선을 부드럽게 — 점들을 지나는 2차 베지어(중점) 곡선 경로.

    각 점을 제어점, 인접 점들의 중점을 분절 끝점으로 사용하면 꺾임이 사라지고
    원곡선처럼 부드럽게 보인다. 점이 2개면 직선. pts: QPoint/QPointF 시퀀스."""
    from PyQt6.QtGui import QPainterPath
    from PyQt6.QtCore import QPointF
    path = QPainterPath()
    n = len(pts)
    if n < 2:
        return path
    path.moveTo(QPointF(pts[0]))
    if n == 2:
        path.lineTo(QPointF(pts[1]))
        return path
    for i in range(1, n - 1):
        c = pts[i]; nx = pts[i + 1]
        mid = QPointF((c.x() + nx.x()) / 2.0, (c.y() + nx.y()) / 2.0)
        path.quadTo(QPointF(c), mid)
    path.lineTo(QPointF(pts[-1]))
    return path


class _MainDrawOverlay(QWidget):
    """260609-22(J3): 본화면 페이지 위 선긋기 오버레이(정규화 좌표 0..1).

    그리기 도구가 활성일 때만 마우스 캡처(아니면 통과). 점은 페이지 사각형 기준
    비율로 저장 → 줌/리사이즈에 무관하게 정렬 유지.
    """

    def __init__(self, owner):
        # 260611-2: 뷰포트가 아닌 self.view 의 자식(하이퍼링크 오버레이와 동일)으로 생성.
        #   QGraphicsView 뷰포트 자식 위젯은 실기기에서 씬 위에 합성이 안 돼 그림이 안 보였음
        #   (offscreen grab 으로 paint 자체는 정상 확인). _position_draw_overlay 가 뷰포트
        #   영역에 정확히 겹쳐 배치 → 오버레이 로컬좌표 = 뷰포트 좌표(_pr 과 일치).
        super().__init__(owner.view)
        self._owner = owner
        self._cur = None
        self._press = None
        self._moved = False
        self._erasing = False
        self._cursor_pt = None          # 260611-2: 지우개 미리보기 커서(뷰포트 px)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_active(self, on):
        # 260611-1: 오버레이는 항상 마우스 통과(페인트 전용). 입력은 MainView.eventFilter
        #   가 뷰포트에서 가로채 아래 핸들러로 전달한다(발표 모드와 동일 패턴).
        #   QGraphicsView 뷰포트 위 자식 위젯의 직접 마우스 캡처가 불안정해 라우팅으로 전환.
        self.raise_()

    def _pr(self):
        return self._owner._page_view_rect()

    def _to_view(self, fx, fy, pr):
        return QPoint(int(pr.left() + fx * pr.width()),
                      int(pr.top() + fy * pr.height()))

    def paintEvent(self, e):
        pr = self._pr()
        if pr is None or pr.width() <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_images(p, pr)          # 260611-15: 삽입 이미지(선긋기 아래)
        strokes = list(self._owner._page_strokes)
        if self._cur is not None:
            strokes = strokes + [self._cur]
        hl_op = self._owner._highlight_alpha()
        edit_idx = self._owner._text_edit_idx

        # 260611-81/82: 투명한 펜·하이라이트·도형(채움/윤곽)·박스배경은 (색,투명도)별 레이어에
        #   '불투명'으로 모아 그린 뒤 한 번만 그 투명도로 합성 → 아무리 겹쳐도 누적(진해짐)되지
        #   않아 밑 글자가 끝까지 보인다(강조 의도 유지). 불투명 요소는 그 위에 기존대로 렌더.
        flat = {}   # (color_hex, alpha%) -> [callable(layer_painter, opaque_color), ...]

        def _add(chex, a, fn):
            flat.setdefault((chex, max(1, min(99, int(round(a))))), []).append(fn)

        for st in strokes:
            if st.get("shape"):
                col = st.get("color", "#ff3030"); pa = int(st.get("alpha", 100))
                fk = st.get("fill", "none")
                if fk != "none":
                    fa = pa * (0.30 if fk == "semi" else 1.0)
                    if fa < 100:
                        _add(col, fa, lambda lp, oc, s=st: self._paint_shape(lp, s, pr, only="fill", force_color=oc))
                if pa < 100:
                    _add(col, pa, lambda lp, oc, s=st: self._paint_shape(lp, s, pr, only="stroke", force_color=oc))
            elif st.get("text_box") or st.get("leader"):
                bg = st.get("bg"); ba = int(st.get("bg_alpha", 100))
                if bg and ba < 100:
                    _add(bg, ba, lambda lp, oc, s=st: self._paint_textbg(lp, s, pr, force_color=oc))
            elif len(st.get("points", [])) >= 2:
                if st.get("hl"):
                    _add(st.get("color", "#ffd400"), hl_op,
                         lambda lp, oc, s=st: self._paint_line_geom(lp, s, pr, oc))
                elif int(st.get("alpha", 100)) < 100:
                    _add(st.get("color", "#ff3030"), int(st.get("alpha", 100)),
                         lambda lp, oc, s=st: self._paint_line_geom(lp, s, pr, oc))
        if flat:
            from PyQt6.QtGui import QImage
            dpr = self.devicePixelRatioF() or 1.0
            for (chex, a), fns in flat.items():
                layer = QImage(max(1, int(self.width() * dpr)),
                               max(1, int(self.height() * dpr)),
                               QImage.Format.Format_ARGB32_Premultiplied)
                layer.setDevicePixelRatio(dpr); layer.fill(0)
                lp = QPainter(layer)
                lp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                opaque = QColor(chex); opaque.setAlpha(255)
                for fn in fns:
                    fn(lp, opaque)
                lp.end()
                p.setOpacity(max(0.05, min(1.0, a / 100.0)))
                p.drawImage(0, 0, layer)
                p.setOpacity(1.0)

        for si_idx, st in enumerate(strokes):
            if st.get("shape"):
                # 투명 채움/윤곽은 평탄화에서 그렸으니 여기선 불투명 부분만
                pa = int(st.get("alpha", 100)); fk = st.get("fill", "none")
                if fk != "none" and pa * (0.30 if fk == "semi" else 1.0) >= 100:
                    self._paint_shape(p, st, pr, only="fill")
                if pa >= 100:
                    self._paint_shape(p, st, pr, only="stroke")
                continue
            bg = st.get("bg"); bg_trans = bool(bg) and int(st.get("bg_alpha", 100)) < 100
            if st.get("leader"):
                self._paint_leader(p, st, pr, with_box=(si_idx != edit_idx), skip_bg=bg_trans)
                continue
            if st.get("text_box"):
                if si_idx != edit_idx:    # 편집 중인 박스는 인라인 편집기가 표시
                    self._draw_text_box(p, st, pr, skip_bg=bg_trans)
                continue
            pts = st.get("points", [])
            if len(pts) < 2:
                continue
            # 투명(하이라이트/투명펜)은 위 평탄화 레이어에서 이미 그림 → 여기선 불투명만
            if st.get("hl") or int(st.get("alpha", 100)) < 100:
                continue
            col = QColor(st.get("color", "#ff3030")); col.setAlpha(255)
            pen = QPen(col); pen.setWidth(int(st.get("width", 3)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
            vp = [self._to_view(x, y, pr) for x, y in pts]
            p.drawPath(smooth_polyline_path(vp))   # 260611-83: 부드러운 곡선
        # 260611-2: 지우개 작동 면적 미리보기(반투명 옅은 회색 원)
        tool = self._owner._draw_tool
        if (self._cursor_pt is not None and tool is not None and tool[0] == "erase"):
            r = max(4, int(tool[1]) // 2)
            p.setPen(QPen(QColor(120, 120, 120, 170), 1))
            p.setBrush(QColor(150, 150, 150, 70))
            p.drawEllipse(self._cursor_pt, r, r)
        # 260611-74/77: 지시선 작도 라이브 미리보기
        #   drag/float = 선이 포인터를 따라감, aim = 끝점 고정 + 지나간 문자 하이라이트 누적
        ld = self._owner._leader_drag
        if ld is not None:
            o = self._to_view(ld["origin"][0], ld["origin"][1], pr)
            ph = ld.get("phase")
            if ph == "aim":
                end = ld.get("endpoint", ld["cur"])
                for r in ld.get("hl", []):
                    a = self._to_view(r[0], r[1], pr); b = self._to_view(r[2], r[3], pr)
                    p.fillRect(QRect(a, b).normalized(), QColor(255, 210, 0, 110))
                p.setPen(QPen(QColor("#1565c0"), 2)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawLine(o, end)
                p.setBrush(QColor("#1565c0")); p.setPen(QPen(QColor("#1565c0"), 1))
                p.drawEllipse(end, 4, 4)
            else:
                cur = ld["cur"]
                p.setPen(QPen(QColor("#1565c0"), 2, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush); p.drawLine(o, cur)
                p.setBrush(QColor("#1565c0")); p.setPen(QPen(QColor("#1565c0"), 1))
                p.drawEllipse(cur, 4, 4)
        # 260611-70/72/74: 선택된 선=점선박스 / 도형·텍스트·지시선=8핸들+회전핸들
        si = self._owner._stroke_selected
        if 0 <= si < len(self._owner._page_strokes):
            st = self._owner._page_strokes[si]
            if st.get("shape") or st.get("text_box") or st.get("leader"):
                from PyQt6.QtGui import QPolygonF
                pts = self._owner._shape_handle_points(st, pr)
                p.save(); p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor("#1565c0"), 2, Qt.PenStyle.DashLine))
                p.drawPolygon(QPolygonF([pts["tl"], pts["tr"], pts["br"], pts["bl"]]))
                p.setPen(QPen(QColor("#1565c0"), 1)); p.drawLine(pts["t"], pts["rot"])
                p.setBrush(QColor("#1565c0")); p.drawEllipse(pts["rot"], 5, 5)
                p.setBrush(QColor("#ffffff"))
                for name in ("tl", "tr", "bl", "br", "t", "b", "l", "r"):
                    hp = pts[name]; p.drawRect(int(hp.x()) - 4, int(hp.y()) - 4, 8, 8)
                p.restore()
            else:
                box = self._stroke_bbox_view(st, pr)
                if box is not None:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(QColor(255, 122, 0, 230), 1, Qt.PenStyle.DashLine))
                    p.drawRect(box.adjusted(-3, -3, 3, 3))
        p.end()

    def _stroke_bbox_view(self, st, pr):
        from PyQt6.QtCore import QRect
        if st.get("shape") == "circle":
            c = self._to_view(st.get("cx", 0.5), st.get("cy", 0.5), pr)
            r = int(float(st.get("r", 0.0)) * pr.width())
            return QRect(c.x() - r, c.y() - r, 2 * r, 2 * r)
        if st.get("shape"):
            rc = st.get("rect", [0, 0, 0, 0])
            tl = self._to_view(min(rc[0], rc[2]), min(rc[1], rc[3]), pr)
            br = self._to_view(max(rc[0], rc[2]), max(rc[1], rc[3]), pr)
            return QRect(tl, br).normalized()
        pts = st.get("points", [])
        if not pts:
            return None
        if st.get("hl"):
            (a0, yc), (a1, _y) = pts[0], pts[-1]
            bh = float(st.get("h", 0.0))
            tl = self._to_view(min(a0, a1), yc - bh / 2, pr)
            br = self._to_view(max(a0, a1), yc + bh / 2, pr)
            return QRect(tl, br).normalized()
        vp = [self._to_view(x, y, pr) for x, y in pts]
        xs = [q.x() for q in vp]; ys = [q.y() for q in vp]
        return QRect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    # 260611-15: 삽입 이미지(주석) 렌더 — 모양 마스크 + 투명도 + 선택 핸들
    def _img_rect_view(self, obj, pr):
        from PyQt6.QtCore import QRectF
        fx, fy, fw, fh = obj.get("rect", [0.1, 0.1, 0.3, 0.3])
        return QRectF(pr.left() + fx * pr.width(), pr.top() + fy * pr.height(),
                      fw * pr.width(), fh * pr.height())

    def _paint_images(self, p, pr):
        # 260611-18: 회전(중심 기준) + 모양 마스크 + 투명도. 선택 시 8핸들·회전 핸들.
        from PyQt6.QtGui import QPainterPath, QPolygonF
        from PyQt6.QtCore import QRectF
        objs = getattr(self._owner, "_img_objects", [])
        sel = getattr(self._owner, "_img_selected", -1)
        for idx, obj in enumerate(objs):
            pix = obj.get("pix")
            if pix is None or pix.isNull():
                continue
            cx, cy, hw, hh, rot = self._owner._img_geom(obj, pr)
            shape = obj.get("shape", "rect")
            alpha = max(0, min(100, int(obj.get("alpha", 100))))
            local = QRectF(-hw, -hh, 2 * hw, 2 * hh)
            p.save()
            p.translate(cx, cy)
            if rot:
                p.rotate(rot)
            p.setOpacity(alpha / 100.0)
            if shape in ("round", "circle"):
                path = QPainterPath()
                if shape == "circle":
                    path.addEllipse(local)
                else:
                    rr = min(local.width(), local.height()) * 0.18
                    path.addRoundedRect(local, rr, rr)
                p.setClipPath(path)
            p.drawPixmap(local.toRect(), pix)
            p.restore()
            if idx == sel:
                pts = self._owner._img_handle_points(obj, pr)
                p.save()
                # 회전된 선택 테두리(폴리곤)
                p.setPen(QPen(QColor("#1565c0"), 2, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(QPolygonF([pts["tl"], pts["tr"], pts["br"], pts["bl"]]))
                # 회전 핸들(상단 변 중앙에서 막대 + 원형 손잡이)
                p.setPen(QPen(QColor("#1565c0"), 1))
                p.drawLine(pts["t"], pts["rot"])
                p.setBrush(QColor("#1565c0"))
                p.drawEllipse(pts["rot"], 5, 5)
                # 크기 핸들 8개(모서리 + 변)
                p.setBrush(QColor("#ffffff"))
                for name in ("tl", "tr", "bl", "br", "t", "b", "l", "r"):
                    hp = pts[name]
                    p.drawRect(int(hp.x()) - 4, int(hp.y()) - 4, 8, 8)
                p.restore()

    def _norm(self, pos, pr):
        fx = (pos.x() - pr.left()) / max(1, pr.width())
        fy = (pos.y() - pr.top()) / max(1, pr.height())
        return [max(0.0, min(1.0, fx)), max(0.0, min(1.0, fy))]

    def _paint_shape(self, p, st, pr, only=None, force_color=None):
        """260611-69/82: 도형(직사각형/둥근/원형) 렌더 — 정규화 좌표.
        only: None=윤곽+채움 / 'stroke'=윤곽만 / 'fill'=채움만.
        force_color: 주어지면 불투명 그 색으로(평탄화 레이어용)."""
        from PyQt6.QtCore import QRect, QRectF, QPoint
        a = max(0.05, min(1.0, float(st.get("alpha", 100)) / 100.0))
        fill = st.get("fill", "none")
        # 윤곽(pen)
        if only == "fill":
            p.setPen(Qt.PenStyle.NoPen)
        else:
            if force_color is not None:
                line = QColor(force_color)
            else:
                line = QColor(st.get("color", "#ff3030")); line.setAlphaF(a)
            pen = QPen(line); pen.setWidth(int(st.get("width", 3)))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
        # 채움(brush)
        if only == "stroke" or fill == "none":
            p.setBrush(Qt.BrushStyle.NoBrush)
        elif force_color is not None:
            p.setBrush(QColor(force_color))
        else:
            fc = QColor(st.get("color", "#ff3030"))
            fc.setAlphaF(a * (0.30 if fill == "semi" else 1.0))
            p.setBrush(fc)
        kind = st.get("shape")
        if kind == "circle":
            c = self._to_view(st.get("cx", 0.5), st.get("cy", 0.5), pr)
            rpx = int(float(st.get("r", 0.0)) * pr.width())
            p.drawEllipse(QPoint(c.x(), c.y()), rpx, rpx)
        else:
            x0, y0, x1, y1 = st.get("rect", [0, 0, 0, 0])
            tl = self._to_view(min(x0, x1), min(y0, y1), pr)
            br = self._to_view(max(x0, x1), max(y0, y1), pr)
            rect = QRectF(QRect(tl, br).normalized())
            cx = rect.center().x(); cy = rect.center().y()
            hw = rect.width() / 2.0; hh = rect.height() / 2.0
            local = QRectF(-hw, -hh, 2 * hw, 2 * hh)
            rot = float(st.get("rot", 0.0))
            p.save(); p.translate(cx, cy)
            if rot:
                p.rotate(rot)
            if kind == "round":
                rr = min(hw, hh) * 0.36
                p.drawRoundedRect(local, rr, rr)
            else:
                p.drawRect(local)
            p.restore()

    def _paint_line_geom(self, painter, st, pr, color):
        """260611-81: 선/하이라이트 1개의 기하를 주어진 (불투명)색으로 그림 — 평탄화 레이어용."""
        pts = st.get("points", [])
        if len(pts) < 2:
            return
        if st.get("hl"):
            bh = float(st.get("h", 0.0))
            (x0, yc), (x1, _y) = pts[0], pts[-1]
            top = self._to_view(min(x0, x1), yc - bh / 2.0, pr)
            bot = self._to_view(max(x0, x1), yc + bh / 2.0, pr)
            painter.fillRect(QRect(top, bot).normalized(), color)
            return
        pen = QPen(color); pen.setWidth(int(st.get("width", 3)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
        vp = [self._to_view(x, y, pr) for x, y in pts]
        painter.drawPath(smooth_polyline_path(vp))   # 260611-83: 부드러운 곡선

    def _paint_textbg(self, p, st, pr, force_color=None):
        """260611-82: 텍스트/지시선 박스 배경만 — 평탄화 레이어용(불투명) 또는 직접."""
        from PyQt6.QtCore import QRectF
        if not st.get("bg"):
            return
        cx, cy, hw, hh, rot = self._owner._shape_geom(st, pr)
        local = QRectF(-hw, -hh, 2 * hw, 2 * hh)
        if force_color is not None:
            bc = QColor(force_color)
        else:
            bc = QColor(st.get("bg")); bc.setAlpha(int(round(float(st.get("bg_alpha", 100)) * 2.55)))
        p.save(); p.translate(cx, cy)
        if rot:
            p.rotate(rot)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(bc); p.drawRect(local)
        p.restore()

    def _draw_text_box(self, p, st, pr, skip_bg=False):
        """260611-74/76/82: 텍스트 박스 — 배경/박스선/여러 줄 텍스트. skip_bg=배경은 평탄화에서 처리."""
        from PyQt6.QtCore import QRectF
        cx, cy, hw, hh, rot = self._owner._shape_geom(st, pr)
        local = QRectF(-hw, -hh, 2 * hw, 2 * hh)
        p.save(); p.translate(cx, cy)
        if rot:
            p.rotate(rot)
        bg = st.get("bg")
        if bg and not skip_bg:
            bc = QColor(bg); bc.setAlpha(int(round(float(st.get("bg_alpha", 100)) * 2.55)))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(bc); p.drawRect(local)
        if st.get("box_line"):
            bdc = QColor(st.get("border_color", "#333333"))
            bdc.setAlpha(int(round(float(st.get("border_alpha", 100)) * 2.55)))
            pen = QPen(bdc); pen.setWidth(max(1, int(st.get("border_w", 1))))
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(local)
        f = self._owner._text_qfont(st, pr)
        p.setFont(f)
        p.setPen(QColor(st.get("color", "#111111")))
        align = (Qt.AlignmentFlag.AlignHCenter if st.get("align") == 1
                 else Qt.AlignmentFlag.AlignRight if st.get("align") == 2
                 else Qt.AlignmentFlag.AlignLeft)
        pad = 4
        p.drawText(QRectF(-hw + pad, -hh + pad, 2 * hw - 2 * pad, 2 * hh - 2 * pad),
                   int(align | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap),
                   st.get("text", ""))
        p.restore()

    def _paint_leader(self, p, st, pr, with_box=True, skip_bg=False):
        """260611-74/77: 지시선 — 가리키는 문자 하이라이트 + 박스→anchor 선 + 끝모양 + 박스."""
        import math
        from PyQt6.QtCore import QPointF
        # 지시선이 가리키는(드래그로 지나간) 문자 하이라이트
        for r in st.get("hl_rects", []):
            hc = QColor(st.get("line_color", "#ffcc00"))
            hc.setAlpha(int(round(float(st.get("line_alpha", 100)) * 2.55 * 0.40)))
            a = self._to_view(r[0], r[1], pr); b = self._to_view(r[2], r[3], pr)
            p.fillRect(QRect(a, b).normalized(), hc)
        cx, cy, hw, hh, rot = self._owner._shape_geom(st, pr)
        anchor = st.get("anchor", [0.5, 0.5])
        ax = pr.left() + anchor[0] * pr.width(); ay = pr.top() + anchor[1] * pr.height()
        # 박스 경계 위 시작점: 중심→anchor 방향에서 박스 변과 만나는 지점
        dx = ax - cx; dy = ay - cy
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            sx, sy = cx, cy
        else:
            tx = hw / abs(dx) if abs(dx) > 1e-6 else 1e9
            ty = hh / abs(dy) if abs(dy) > 1e-6 else 1e9
            t = min(tx, ty)
            sx, sy = cx + dx * t, cy + dy * t
        col = QColor(st.get("line_color", st.get("color", "#111111")))
        col.setAlpha(int(round(float(st.get("line_alpha", 100)) * 2.55)))
        pen = QPen(col); pen.setWidth(max(1, int(st.get("line_w", 2))))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(sx, sy), QPointF(ax, ay))
        tip = st.get("tip", "arrow")
        if tip == "circle":
            p.setBrush(col); p.drawEllipse(QPointF(ax, ay), 5, 5)
        elif tip == "arrow":
            ang = math.atan2(ay - sy, ax - sx)
            sz = 11.0
            for da in (math.radians(150), math.radians(-150)):
                p.drawLine(QPointF(ax, ay),
                           QPointF(ax + sz * math.cos(ang + da),
                                   ay + sz * math.sin(ang + da)))
        if with_box:
            self._draw_text_box(p, st, pr, skip_bg=skip_bg)

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self._owner._draw_tool is None:
            return super().mousePressEvent(e)
        pr = self._pr()
        if pr is None:
            return
        self._press = e.position().toPoint()
        self._moved = False
        tool = self._owner._draw_tool
        if tool[0] == "erase":
            self._erasing = True
            self._owner._erase_strokes_near(self._norm(self._press, pr))
            self.update()
        else:
            # 260611-5: 인덱스 안전 — 펜 데이터가 부족해도 마지막 펜으로 폴백(패닝 방지)
            pens = self._owner._draw_pens or MV_DEFAULT_PENS
            idx = max(0, min(len(pens) - 1, int(tool[1])))
            pen = pens[idx]
            sp = self._norm(self._press, pr)
            # 260611-71: 그리기 종류에 따라 — 도형/선만, 둘 다 비선택이면 그리지 않음
            dk = self._owner._draw_kind
            if dk == "shape" and self._owner._shape_kind:
                self._cur = {"shape": self._owner._shape_kind, "fill": self._owner._shape_fill,
                             "color": pen.get("color", "#ff3030"),
                             "width": int(pen.get("width", 3)),
                             "alpha": int(pen.get("alpha", 100)),
                             "rect": [sp[0], sp[1], sp[0], sp[1]],
                             "cx": sp[0], "cy": sp[1], "r": 0.0, "rot": 0.0}
                return
            if dk != "line":
                self._press = None
                return
            cur = {"color": pen.get("color", "#ff3030"),
                   "width": int(pen.get("width", 3)),
                   "alpha": int(pen.get("alpha", 100)),
                   "points": [sp]}
            # 260611-1: 모드 1=하이라이트 — 누른 위치의 텍스트 줄 높이(정규화 띠)
            if self._owner._draw_line_mode == 1:
                band = self._owner._hl_band_at(sp[0], sp[1])
                yc = (band[0] + band[1]) / 2.0 if band else sp[1]
                bh = (band[1] - band[0]) if band else self._owner._hl_default_h()
                cur["hl"] = True
                cur["h"] = bh
                cur["points"] = [[sp[0], yc], [sp[0], yc]]
            self._cur = cur

    def mouseMoveEvent(self, e):
        if self._owner._draw_tool is None:
            return
        pr = self._pr()
        if pr is None:
            return
        pos = e.position().toPoint()
        self._cursor_pt = pos          # 260611-2: 지우개 미리보기 위치
        held = bool(e.buttons() & Qt.MouseButton.LeftButton)
        tool = self._owner._draw_tool
        if not held:
            if tool[0] == "erase":
                self.update()          # 호버 시 지우개 원 위치 갱신
            return
        if self._press and (abs(pos.x() - self._press.x()) > 3
                            or abs(pos.y() - self._press.y()) > 3):
            self._moved = True
        if self._erasing:
            self._owner._erase_strokes_near(self._norm(pos, pr))
            self.update()
            return
        if self._cur is not None:
            cp = self._norm(pos, pr)
            if self._cur.get("shape"):
                sp = self._norm(self._press, pr)
                if self._cur["shape"] == "circle":
                    dx = pos.x() - self._press.x(); dy = pos.y() - self._press.y()
                    self._cur["cx"], self._cur["cy"] = sp[0], sp[1]
                    self._cur["r"] = ((dx * dx + dy * dy) ** 0.5) / max(1.0, pr.width())
                else:
                    self._cur["rect"] = [sp[0], sp[1], cp[0], cp[1]]
                self.update()
                return
            if self._cur.get("hl"):
                # 가로 구간만 확장(y=줄 중앙 고정), 띠 높이 유지
                yc = self._cur["points"][0][1]
                sp = self._norm(self._press, pr)
                self._cur["points"] = [[sp[0], yc], [cp[0], yc]]
            elif self._owner._draw_line_mode == 0 and self._press:
                # 모드 0=직선(시작 y 고정 수평선)
                sp = self._norm(self._press, pr)
                self._cur["points"] = [sp, [cp[0], sp[1]]]
            else:
                # 모드 2=자유곡선
                self._cur["points"].append(cp)
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self._erasing:
            self._erasing = False
            self._owner._save_page_strokes()
        elif self._cur is not None:
            st = self._cur; self._cur = None
            if st.get("shape"):              # 260611-69(Stage1): 도형 저장(최소 크기 이상)
                if st["shape"] == "circle":
                    ok = float(st.get("r", 0)) > 0.004
                else:
                    rc = st.get("rect", [0, 0, 0, 0])
                    ok = abs(rc[2] - rc[0]) > 0.006 or abs(rc[3] - rc[1]) > 0.006
                if ok:
                    self._owner._page_strokes.append(st)
                    self._owner._stroke_selected = len(self._owner._page_strokes) - 1  # 활성 유지
                    self._owner._save_page_strokes()
            elif self._moved and len(st["points"]) >= 2:
                self._owner._page_strokes.append(st)
                self._owner._save_page_strokes()
            self.update()
        self._press = None; self._moved = False

    def leaveEvent(self, e):
        self._cursor_pt = None
        self.update()
        super().leaveEvent(e)


class _DblTool(QToolButton):
    """260611-71/80: 단일 클릭=토글(singleClick) / 더블 클릭=종류 변경(doubleClick).

    260611-80: 지연 없이 단일 클릭을 '즉시' 처리(이전엔 더블클릭 간격만큼 기다려 느렸음).
    더블클릭이면 첫 클릭의 토글 위에 doubleClick(종류 변경+활성)이 덮어쓰고,
    더블클릭의 두 번째 릴리즈 clicked 는 무시한다."""
    singleClick = pyqtSignal()
    doubleClick = pyqtSignal()

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._ignore_click = False
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self):
        if self._ignore_click:               # 더블클릭의 두 번째 릴리즈 클릭 무시
            self._ignore_click = False
            return
        self.singleClick.emit()              # 즉시 반응

    def mouseDoubleClickEvent(self, e):
        self._ignore_click = True
        self.doubleClick.emit()
        e.accept()


class _PdfGraphicsView(QGraphicsView):
    """드래그 스크롤 + 휠/키보드 페이지 이동.

    줌은 부모(MainView)가 재렌더링으로 처리. 본 뷰의 transform 은 항상 identity.
    """
    zoomRequested = pyqtSignal(float)      # 부모에게 줌 변경 요청 (factor)
    pageStep = pyqtSignal(int)
    hoverWord = pyqtSignal(str)            # 260603: 단어장 단어 위 호버 (lemma)
    pageClicked = pyqtSignal(float, float) # 260606: 페이지 클릭 (PDF point x,y)
    contextMenuRequested = pyqtSignal(object)  # 260606-4: 우클릭 위치(전역 QPoint)
    viewActivated = pyqtSignal()           # 260606-8: 이 뷰를 클릭(활성 창 선택)
    regionSelected = pyqtSignal(object)    # 260616-21: 텍스트 영역(scene QRectF) 선택 완료
    viewResized = pyqtSignal()             # 260618-10: 뷰포트 크기 변경(빈 안내 라벨 재중앙)
    fitPageRequested = pyqtSignal()        # 260618-16: 더블클릭 → 쪽 맞춤
    pathDropped = pyqtSignal(str)          # 260618-23: 뷰어에 PDF/폴더 드롭 → 이 창에 열기

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.viewResized.emit()

    def mouseDoubleClickEvent(self, ev):
        from PyQt6.QtCore import Qt as _Qt
        if ev.button() == _Qt.MouseButton.LeftButton:
            self.fitPageRequested.emit()     # 뷰어 더블클릭 = 쪽 맞춤
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        # 260617-2: 좌측 드래그 = 텍스트 블럭 선택(패닝 아님). 세로 스크롤은 휠/스크롤바.
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)        # 버튼 없이 mouseMove 수신(호버)
        self.setAcceptDrops(True)          # 260611-15: 이미지 드래그&드롭 삽입
        self._owner = None                  # MainView (zoom 조회)
        self._hover_words = []              # [(x0,y0,x1,y1,lemma)] PDF point
        self._last_hover = None
        self._press_scene = None            # 260617-3: 좌드래그 시작(PDF 좌표)
        self._dragging = False
        self._block_armed = False           # 260617-5: 사각형 블럭 선택 1회 무장
        self._brb = None                    # 블럭 러버밴드
        self._brb_origin = None
        try:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)   # 텍스트 선택 포인터
        except Exception:
            pass

    def _editing(self) -> bool:
        return bool(getattr(self._owner, "_img_edit", False))

    def arm_block_select(self, on: bool = True):
        """260617-5: '블럭설정 후 텍스트 복사' — 다음 좌드래그를 사각형 블럭 선택으로(1회).
        좌상→우하 드래그 영역의 텍스트를 복사. 십자 포인터."""
        self._block_armed = bool(on)
        if self._owner is not None:
            self._owner.clear_text_selection()
        self.viewport().setCursor(
            Qt.CursorShape.CrossCursor if on else Qt.CursorShape.IBeamCursor)

    # 하위호환(앱에서 arm_text_select 호출 시 블럭 모드로)
    def arm_text_select(self, on: bool = True):
        self.arm_block_select(on)

    _IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")

    def _drop_ok(self, md):
        ownr = self._owner
        edit = bool(ownr is not None and getattr(ownr, "_img_edit", False))
        # 260618-27: PDF/폴더(뷰어에 열기)는 **편집모드와 무관하게 항상 허용** — 종전엔
        #   편집모드가 아니면 _drop_ok 가 False 라 dragEnter 가 거부되어 뷰어 드롭이
        #   아예 동작하지 않았다. 이미지(편집 삽입)는 편집모드에서만.
        if md.hasUrls():
            from pathlib import Path as _P
            for u in md.urls():
                if not u.isLocalFile():
                    continue
                lf = u.toLocalFile()
                if lf.lower().endswith(".pdf"):
                    return True
                try:
                    if _P(lf).is_dir():
                        return True
                except Exception:
                    pass
                if edit and lf.lower().endswith(self._IMG_EXT):
                    return True
        if edit and md.hasImage():
            return True
        return False

    def dragEnterEvent(self, e):
        if self._drop_ok(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._drop_ok(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        md = e.mimeData()
        ownr = self._owner
        # 260618-23: PDF/폴더 드롭 → 이 창에 열기(편집모드 무관). 이미지(편집모드)는 아래 삽입 처리.
        if md.hasUrls():
            from pathlib import Path as _P
            for u in md.urls():
                if not u.isLocalFile():
                    continue
                lf = u.toLocalFile()
                if lf.lower().endswith(".pdf") or _P(lf).is_dir():
                    self.pathDropped.emit(lf)
                    e.acceptProposedAction()
                    return
        if ownr is None or not getattr(ownr, "_img_edit", False):
            return super().dropEvent(e)
        from PyQt6.QtGui import QImage, QPixmap as _QPix
        if md.hasImage():
            img = md.imageData()
            if isinstance(img, QImage) and not img.isNull():
                ownr.add_image_from_pixmap(_QPix.fromImage(img))
                e.acceptProposedAction(); return
        if md.hasUrls():
            for u in md.urls():
                if u.isLocalFile() and u.toLocalFile().lower().endswith(self._IMG_EXT):
                    if ownr.add_image_from_file(u.toLocalFile()):
                        e.acceptProposedAction(); return
        super().dropEvent(e)

    def set_hover_words(self, items):
        self._hover_words = items or []
        if not self._hover_words:
            self._last_hover = None

    def mousePressEvent(self, event):
        self._press_pos = event.position().toPoint()
        try:
            self.viewActivated.emit()      # 260606-8: 클릭한 창을 활성으로
        except Exception:
            pass
        # 260617-5: 블럭설정(무장) → 사각형 러버밴드 시작(단어 선택보다 우선)
        if (self._block_armed and event.button() == Qt.MouseButton.LeftButton
                and not self._editing()):
            from PyQt6.QtWidgets import QRubberBand
            from PyQt6.QtCore import QRect, QSize
            self._brb_origin = self._press_pos
            if self._brb is None:
                self._brb = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
            self._brb.setGeometry(QRect(self._brb_origin, QSize()))
            self._brb.show()
            return
        # 260617-3: 비편집(보기) 모드 좌클릭 → 텍스트 선택 시작점 기록(드래그 시 단어 선택)
        if (event.button() == Qt.MouseButton.LeftButton and not self._editing()):
            z = getattr(self._owner, "_zoom", 1.0) or 1.0
            sp = self.mapToScene(self._press_pos)
            self._press_scene = (sp.x() / z, sp.y() / z)
            self._dragging = False
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # 260617-5: 블럭 선택 완료 → 영역 텍스트 복사 후 무장 해제
        if (self._brb is not None and self._brb.isVisible()
                and event.button() == Qt.MouseButton.LeftButton):
            from PyQt6.QtCore import QRectF
            rect = self._brb.geometry()
            self._brb.hide()
            self._block_armed = False
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
            try:
                if rect.width() > 3 and rect.height() > 3 and self._owner is not None:
                    tl = self.mapToScene(rect.topLeft())
                    br = self.mapToScene(rect.bottomRight())
                    self._owner.copy_block(QRectF(tl, br).normalized())
            except Exception:
                pass
            return
        # 260617-3: 텍스트 선택 종료 — 드래그면 선택 확정(유지), 클릭이면 해제 + 읽기 점프
        if (event.button() == Qt.MouseButton.LeftButton
                and self._press_scene is not None and not self._editing()):
            was_drag = self._dragging
            self._press_scene = None
            self._dragging = False
            if was_drag:
                if self._owner is not None:
                    self._owner._sel_end()
                return
            if self._owner is not None:
                self._owner.clear_text_selection()
            try:                              # 클릭 → 읽기 점프
                z = getattr(self._owner, "_zoom", 1.0) or 1.0
                sp = self.mapToScene(event.position().toPoint())
                self.pageClicked.emit(sp.x() / z, sp.y() / z)
            except Exception:
                pass
            return
        try:
            # 260606-4: 좌클릭만 페이지 클릭(읽기 점프)로 처리 — 우클릭은 메뉴용
            if event.button() == Qt.MouseButton.LeftButton:
                pp = getattr(self, "_press_pos", None)
                rp = event.position().toPoint()
                if pp is not None and (abs(rp.x() - pp.x()) + abs(rp.y() - pp.y())) <= 4:
                    z = getattr(self._owner, "_zoom", 1.0) or 1.0
                    sp = self.mapToScene(rp)
                    self.pageClicked.emit(sp.x() / z, sp.y() / z)   # PDF point
        except Exception:
            pass
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        # 260606-4: 우클릭 → 부모(MainView)·앱이 편집모드면 '책갈피 추가' 메뉴 구성
        try:
            self.contextMenuRequested.emit(event.globalPos())
        except Exception:
            pass

    def mouseMoveEvent(self, event):
        # 260617-5: 블럭 러버밴드 드래그 중 → 사각형 크기 갱신
        if (self._brb is not None and self._brb.isVisible() and self._brb_origin is not None
                and (event.buttons() & Qt.MouseButton.LeftButton)):
            from PyQt6.QtCore import QRect
            self._brb.setGeometry(
                QRect(self._brb_origin, event.position().toPoint()).normalized())
            return
        # 260617-3: 좌버튼 드래그 → 시작점~현재점 사이 단어를 선택(하이라이트)
        if ((event.buttons() & Qt.MouseButton.LeftButton)
                and self._press_scene is not None and self._owner is not None):
            rp = event.position().toPoint()
            pp = getattr(self, "_press_pos", rp)
            if not self._dragging:
                if (abs(rp.x() - pp.x()) + abs(rp.y() - pp.y())) <= 4:
                    return                    # 아직 클릭 수준 — 선택 시작 보류
                self._dragging = True
                self._owner._sel_begin(*self._press_scene)
            z = getattr(self._owner, "_zoom", 1.0) or 1.0
            sp = self.mapToScene(rp)
            self._owner._sel_update(sp.x() / z, sp.y() / z)
            return
        try:
            if self._hover_words and self._owner is not None:
                z = getattr(self._owner, "_zoom", 1.0) or 1.0
                sp = self.mapToScene(event.position().toPoint())
                px, py = sp.x() / z, sp.y() / z
                hit = None
                for (x0, y0, x1, y1, lemma) in self._hover_words:
                    if x0 <= px <= x1 and y0 <= py <= y1:
                        hit = lemma
                        break
                if hit:
                    self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    if hit != self._last_hover:
                        self._last_hover = hit
                        self.hoverWord.emit(hit)
                elif self._last_hover is not None:
                    self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
                    self._last_hover = None
        except Exception:
            pass
        super().mouseMoveEvent(event)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # v1.6.8 F1: 메인 PDF 는 내장 세로바 숨김(doc_scroll 이 대신 표시).
        #            load_document/load_image 에서 모드별로 정책 재설정.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._image_mode = False              # v1.6.8 F3: 이미지 모드면 휠=일반 스크롤

    def wheelEvent(self, event: QWheelEvent):
        # v1.6.9 G2: 이미지 모드도 PDF 와 동일 — 페이지(스크린샷)내 스크롤하다
        #            끝에서 한 번 더 굴리면 다음/이전 항목으로(_on_page_step 분기).
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.zoomRequested.emit(factor)
            event.accept()
            return

        # 일반 휠: 스크롤바 끝에서 한 번 더 굴리면 페이지 이동
        sb = self.verticalScrollBar()
        delta = event.angleDelta().y()
        if delta < 0 and sb.value() == sb.maximum():
            self.pageStep.emit(+1)
            event.accept()
            return
        if delta > 0 and sb.value() == sb.minimum():
            self.pageStep.emit(-1)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        k = event.key()
        # 260611-15: 편집모드에서 Ctrl+V → 클립보드 이미지 붙여넣기(선택 불필요)
        ownr = self._owner
        if (ownr is not None and getattr(ownr, "_img_edit", False)
                and (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                and k == Qt.Key.Key_V):
            if ownr.paste_image_from_clipboard():
                event.accept(); return
        # 260611-80: 편집모드 되돌리기(Ctrl+Z) / 다시실행(Ctrl+Y, Ctrl+Shift+Z)
        if ownr is not None and getattr(ownr, "_img_edit", False) \
                and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if k == Qt.Key.Key_Z and not shift:
                ownr.undo_strokes(); event.accept(); return
            if k == Qt.Key.Key_Y or (k == Qt.Key.Key_Z and shift):
                ownr.redo_strokes(); event.accept(); return
        # 260611-15: 선택된 삽입 이미지가 있으면 방향키=이동, Ctrl+상/하=불투명/투명, Del=삭제
        if (ownr is not None and getattr(ownr, "_img_edit", False)
                and ownr.has_selected_image()):
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            step = 1 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 3
            if ctrl and k == Qt.Key.Key_Up:
                ownr._img_opacity(+5); event.accept(); return     # 불투명도↑
            if ctrl and k == Qt.Key.Key_Down:
                ownr._img_opacity(-5); event.accept(); return     # 투명도↑
            if k == Qt.Key.Key_Left:
                ownr._img_nudge(-step, 0); event.accept(); return
            if k == Qt.Key.Key_Right:
                ownr._img_nudge(+step, 0); event.accept(); return
            if k == Qt.Key.Key_Up:
                ownr._img_nudge(0, -step); event.accept(); return
            if k == Qt.Key.Key_Down:
                ownr._img_nudge(0, +step); event.accept(); return
            if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                ownr._img_delete_selected(); event.accept(); return
        # 260611-70: 선택된 선/도형 — 방향키 이동 / Del 삭제
        if (ownr is not None and getattr(ownr, "_img_edit", False)
                and getattr(ownr, "_stroke_selected", -1) >= 0):
            step = (1 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 3)
            pr = ownr._page_view_rect()
            if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                ownr._stroke_delete_selected(); event.accept(); return
            if pr is not None and k in (Qt.Key.Key_Left, Qt.Key.Key_Right,
                                        Qt.Key.Key_Up, Qt.Key.Key_Down):
                dnx = ({Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(k, 0)) / max(1.0, pr.width())
                dny = ({Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(k, 0)) / max(1.0, pr.height())
                ownr._stroke_translate(ownr._stroke_selected, dnx, dny)
                ownr._save_page_strokes(); ownr._draw_overlay.update()
                event.accept(); return
        if k in (Qt.Key.Key_PageDown, Qt.Key.Key_Down):
            self.pageStep.emit(+1)
            event.accept()
            return
        if k in (Qt.Key.Key_PageUp, Qt.Key.Key_Up):
            self.pageStep.emit(-1)
            event.accept()
            return
        if k == Qt.Key.Key_Home:
            self.pageStep.emit(-10**6)
            event.accept()
            return
        if k == Qt.Key.Key_End:
            self.pageStep.emit(+10**6)
            event.accept()
            return
        super().keyPressEvent(event)


class MainView(QWidget):
    """1:1 직접 렌더링 메인 뷰어 (v1.4.2)."""
    pageChanged = pyqtSignal(int)
    matchPositionChanged = pyqtSignal(int, int)
    wordHovered = pyqtSignal(str)                # 260603: 단어장 단어 위 마우스 호버
    pageClicked = pyqtSignal(float, float)       # 260606: 페이지 클릭(PDF point)
    contextMenuRequested = pyqtSignal(object)    # 260606-4: 뷰어 우클릭(전역 QPoint)
    activated = pyqtSignal()                     # 260606-8: 이 메인뷰 활성화(클릭)
    textCopied = pyqtSignal(int)                 # 260616-21: 텍스트 복사됨(글자수)
    imageStepRequested = pyqtSignal(int)         # v1.6.4 C2: 이미지 모드 ◀▶ (±1)
    imageGotoRequested = pyqtSignal(int)         # v1.6.8 F2: 이미지 모드 페이지번호 입력 (0-based)
    fileBoundaryRequested = pyqtSignal(int)      # 260609-2: 마지막/첫 페이지 경계에서 다음/이전 파일 (±1)
    hyperlinkActivated = pyqtSignal(object)      # 260609-3: 페이지 하이퍼링크 버튼 클릭(link dict)
    drawModeChanged = pyqtSignal(int)            # 260611-4: 선 종류 순환(0/1/2) — 공유 동기

    _DOC_U = 1000                                # v1.6.8 F1: doc_scroll 페이지당 단위

    TOOLBAR_H = 26               # 260606-14: 툴바 위젯 통일 높이
    FIT_PAGE = "쪽 맞춤"
    FIT_PAGE_TWO = "2장 맞춤"     # v1.5.0 M3 (260606-19: 명칭 단축)
    FIT_WIDTH = "폭 맞춤"
    FIT_NONE = "수동 맞춤"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: Optional[PdfDocument] = None
        self._current_page = 0
        self._is_image = False                  # v1.6.4 C2: 스크린샷 이미지 표시 중 여부
        self._img_fit = self.FIT_PAGE           # v1.6.9 G1: 이미지 전용 fit (기본 쪽맞춤)
        self._img_idx0 = 0                       # v1.6.9 G2: 현재 스크린샷 인덱스(0-based)
        self._img_total = 1                      # v1.6.9 G2: 스크린샷 총수
        # _zoom 은 "PDF 포인트 → 논리 픽셀" 비율. 1.0 ≈ 72 DPI.
        # FIT 모드일 때는 렌더 시 자동 계산되어 마지막 값이 _zoom 에 저장됨.
        self._zoom = 1.5
        self._fit_mode = self.FIT_PAGE
        self._query = ""
        self._matches: list = []
        self._page_words: list = []     # 260617-3: 현재 페이지 단어 박스(PDF 좌표)
        self._sel_items: list = []      # 선택 하이라이트 QGraphicsRectItem
        self._sel_text = ""             # 선택된 텍스트
        self._copy_allowed = True        # 260618-1: 문서 복사 권한(없으면 복사 차단)
        self._sel_start = None          # 선택 시작점(PDF 좌표)
        self._current_match = -1
        # _base_dpi 는 호환을 위해 보존하나, 본 파이프라인에선 zoom 만 사용
        self._base_dpi = 192
        self._render_pending = False
        self._scroll_guard = False            # v1.6.8 F1: doc_scroll ↔ view 동기 재귀 방지

        self._build_ui()

        # v1.6.0 P3: resize 디바운스 — 연속 resize 입력 시 마지막 한 번만 재렌더
        self._resize_debounce = QTimer(self)
        self._resize_debounce.setSingleShot(True)
        self._resize_debounce.setInterval(150)
        self._resize_debounce.timeout.connect(self._render_current)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 260606-9: 툴바를 FlowLayout 으로 — 폭이 좁아지면 2단으로 자동 줄바꿈(창 폭 축소 가능)
        from viewer.widgets.flow_layout import FlowLayout
        self._toolbar_widget = QWidget()
        bar = FlowLayout(self._toolbar_widget, spacing=2)
        self._toolbar = bar                   # v1.6.10 H2: 외부 버튼 삽입용
        H = self.TOOLBAR_H                     # 260606-14: 모든 툴바 위젯 동일 높이
        # 260606-3/14: ‹ › 는 글자 크게·폭 좁게·동일 높이, 내용 중앙
        # 260606-30: ‹ › 글리프가 세로로 아래 치우쳐 보이던 문제 → 세로 중앙에 잘
        #            맞는 오너먼트 꺽쇠(❮ ❯)로 교체. font-size 13.
        self.btn_prev_page = QPushButton("❮")
        self.btn_next_page = QPushButton("❯")
        for b in (self.btn_prev_page, self.btn_next_page):
            b.setFixedSize(24, H)
            b.setStyleSheet(
                "QPushButton{font-size:13px;font-weight:bold;padding:0;text-align:center;}")
        # 260606-9: 페이지 번호 입력칸 최소화
        self.spin_page = QSpinBox()
        self.spin_page.setMinimum(1)
        self.spin_page.setFixedSize(46, H)
        self.spin_page.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_page_total = QLabel("/ 0")
        self.lbl_page_total.setFixedHeight(H)
        self.lbl_page_total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 260606-9: 보기 콤보 폭 최소화(내용에 맞춤)
        self.cmb_fit = QComboBox()
        self.cmb_fit.addItems([self.FIT_PAGE, self.FIT_PAGE_TWO, self.FIT_WIDTH, self.FIT_NONE])
        self.cmb_fit.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.cmb_fit.setMaximumWidth(86)
        self.cmb_fit.setFixedHeight(H)
        # 260606-3: -, + 줌 버튼 폭 좁게·동일 높이
        self.btn_zoom_in = QPushButton("+"); self.btn_zoom_in.setFixedSize(24, H)
        self.btn_zoom_out = QPushButton("−"); self.btn_zoom_out.setFixedSize(24, H)

        bar.addWidget(self.btn_prev_page)
        bar.addWidget(self.spin_page)
        bar.addWidget(self.lbl_page_total)
        bar.addWidget(self.btn_next_page)
        # 260606-19: MP3 등 외부 버튼과 보기콤보 사이 구분 여백
        _sep = QWidget(); _sep.setFixedSize(12, H)
        bar.addWidget(_sep)
        bar.addWidget(self.cmb_fit)
        bar.addWidget(self.btn_zoom_out)
        bar.addWidget(self.btn_zoom_in)
        # 260609-22(J3): 편집모드 전용 선긋기 도구 모음
        self._draw_bar = self._build_draw_bar(H)
        bar.addWidget(self._draw_bar)
        self._draw_bar.hide()
        layout.addWidget(self._toolbar_widget)

        self.scene = QGraphicsScene(self)
        self.view = _PdfGraphicsView(self)
        self.view.setScene(self.scene)
        # 260609-11(C8): 페이지 스크롤 시 하이퍼링크 오버레이 위치 추종
        self.view.verticalScrollBar().valueChanged.connect(
            lambda _=0: (self._position_hl_overlay(), self._update_hidden_band(),
                         self._position_draw_overlay()))
        self.view.horizontalScrollBar().valueChanged.connect(
            lambda _=0: (self._position_hl_overlay(), self._update_hidden_band(),
                         self._position_draw_overlay()))
        from viewer import theme as _theme
        self.apply_theme(_theme.is_dark())       # 260606-14: 배경 테마 대응

        # 260606-30: 빈 창(문서 없음) 안내 — 2단 보기에서 오른쪽 창이 비었을 때 중앙 표시
        # 260618-10: 뷰포트에 부모로 두어 좌/우·상/하 정확히 중앙에 오도록(프레임 오프셋 제거)
        self._empty_label = QLabel("이 창을 선택 후\n책갈피를 선택하세요",
                                   self.view.viewport() or self.view)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            "QLabel{color:#888;font-size:14px;background:transparent;}")
        self._empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._empty_label.show()
        self.view.viewResized.connect(self._update_empty_label)   # 260618-10: 뷰포트 변경 시 재중앙

        # 260609-11(C8): 페이지 하이퍼링크 버튼 오버레이 — 페이지 영역 안, 상단 약간
        #   아래(오프셋), 가운데 정렬, 페이지 폭 초과 시 다음 줄로 줄바꿈.
        self._hl_overlay = QWidget(self.view)
        self._hl_overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._hl_overlay.setStyleSheet("background:transparent;")
        _ov = QVBoxLayout(self._hl_overlay)
        _ov.setContentsMargins(0, 0, 0, 0)
        _ov.setSpacing(4)
        self._hl_buttons = []
        self._hl_links = []
        self._hl_top_offset = 10            # 상단에서 약간 아래(px) — 설정 가능
        self._hl_overlay.hide()

        # 260609-26: 썸네일 필터 → 뷰어 페이지 이동 제한(허용 페이지 목록, None=전체)
        self._nav_pages = None
        # 260609-22(J3): 본화면 선긋기
        self._draw_pens = list(MV_DEFAULT_PENS)
        # 260611-76: 모드(4버튼+지우개)와 스타일(색상버튼)을 분리.
        #   _draw_kind = 활성 모드(상호배타): 'line'/'shape'/'text'/'select'/'erase'/None
        #   _pen_idx   = 활성 색상버튼(스타일) 0..N 또는 None — 모드와 독립
        #   _draw_tool = 위 둘에서 파생(_apply_tool). 기존 소비자 호환용.
        self._draw_eraser_widths = [12, 30]
        self._pen_idx = None              # 활성 색상버튼(색·굵기·투명도 스타일)
        self._erase_k = 0                 # 활성 지우개(0=얇게/1=두껍게)
        self._draw_tool = None            # 파생: None/('pen',idx)/('erase',w)/('select',None)
        self._draw_line_mode = 0          # 260611-2: 0=직선 / 1=하이라이트 / 2=자유곡선
        self._draw_highlight_alpha = 35   # 260611-2: 하이라이트 전용 불투명도(%)
        self._draw_kind = "line"          # 기본 모드=선
        self._shape_kind = "rect"         # 도형 종류(항상 보유): rect/round/circle
        self._shape_fill = "none"         # none|semi|full (도형 채움 스타일)
        self._update_shape_button()
        self._update_line_button()
        self._update_text_button()
        self._page_strokes = []           # 현재 페이지 정규화 스트로크
        # 260611-80: 편집모드 되돌리기/다시실행 — 페이지별 스냅샷 스택(완료 동작 1개=1스텝)
        self._undo_stack = []
        self._redo_stack = []
        self._strokes_baseline = []       # 마지막 저장 상태(변경 감지 기준)
        self._restoring = False           # undo/redo 중 재push 방지
        self._draw_resolver = None        # (file,page0)->strokes
        self._draw_setter = None          # (file,page0,strokes)->None
        self._draw_overlay = None
        # 260611-15: 삽입 이미지(주석)
        self._img_objects = []            # [{pix,data,rect[fx,fy,fw,fh],shape,alpha,rot}]
        self._img_selected = -1
        # 260611-70: 그린 선/도형 선택·이동(개체선택 도구)
        self._stroke_selected = -1
        self._stroke_drag = None          # {"last": QPoint}
        # 260611-72: 활성 도형 변형(크기/회전/이동) — 이미지 핸들과 동일 방식
        self._shape_drag = None           # 'move'/'rot'/'tl'..'br'/'t'..'r'
        self._shape_press = None
        self._shape_press_geom = None
        # 260611-74(Phase2): 글쓰기(텍스트 박스) + 지시선
        self._text_kind = "text"          # 'text'(글쓰기) | 'leader'(지시선)
        self._text_style = "본문"          # 현재 적용 스타일 이름
        self._text_editor = None          # 인라인 QTextEdit(편집 중)
        self._text_edit_idx = -1          # 편집 중 _page_strokes 인덱스
        self._leader_drag = None          # {"origin":[fx,fy], "cur":QPoint} 지시선 끌기
        # 260611-77: 신규 박스 기본 스타일(우클릭 '…박스 설정'에서 편집). 테두리/선은 펜에서 별도.
        _base = {"family": "맑은 고딕", "size": 0.022, "color": "#111111",
                 "bold": False, "italic": False, "box_line": False,
                 "bg": None, "bg_alpha": 100, "align": 0}
        self._text_defaults = dict(_base)
        self._leader_defaults = dict(_base); self._leader_defaults["tip"] = "arrow"
        # 260611-78: 사용자 저장 스타일(앱이 set_text_styles 로 주입; 기본=본문/제목/메모/강조)
        self._text_styles = self._seed_text_styles()
        self._rebuild_text_menu()
        self._set_text_style(self._text_style)
        self._img_edit = False            # 편집모드일 때만 조작
        self._img_shape = "rect"          # 신규 삽입 기본 모양
        self._img_resolver = None         # (file,page0)->[img dict(data,rect,shape,alpha,rot)]
        self._img_setter = None
        # 260611-18: 핸들 8개(모서리 tl/tr/bl/br + 변 t/b/l/r) + 회전 'rot' + 'move'
        self._img_drag = None
        self._img_press = None
        self._img_press_rect = None
        self._img_press_geom = None       # (cx,cy,hw,hh,rot) — 조작 시작 시 기하
        self.IMG_ROT_OFFSET = 26          # 회전 핸들이 상단 변에서 떨어진 거리(px)
        self.IMG_SNAP_DEG = 7             # 90도 자석 스냅 임계각(±도)
        self.IMG_MIN_PX = 12              # 최소 크기(px)
        # 260609-15(A1): 페이지 회전 {page0: deg}
        self._rotations = {}
        # 260609-14(D5): 숨김 페이지 표시 — 페이지 우측 끝 회색 띠 '숨김'
        self._hidden_pages = set()
        self._hidden_band = QLabel("숨\n김", self.view)
        self._hidden_band.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hidden_band.setStyleSheet(
            "background:rgba(110,110,110,0.92);color:white;font-weight:bold;")
        self._hidden_band.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._hidden_band.hide()

        # 260609-22(J3): 선긋기 오버레이(뷰포트 전체, 페인트 전용)
        self._draw_overlay = _MainDrawOverlay(self)
        self._draw_overlay.show()
        # 260611-1: 그리기 입력은 뷰포트 eventFilter 로 가로채 오버레이 핸들러에 전달
        #   (QGraphicsView 뷰포트 위 자식 위젯 직접 캡처가 불안정 → 발표 모드와 동일 패턴)
        self.view.viewport().installEventFilter(self)

        # v1.6.8 F1: 뷰 우측에 '문서 전체 진행률' 세로 스크롤바
        self.doc_scroll = QScrollBar(Qt.Orientation.Vertical)
        self.doc_scroll.setVisible(False)     # 문서 로드 시 표시
        view_row = QHBoxLayout()
        view_row.setContentsMargins(0, 0, 0, 0)
        view_row.setSpacing(0)
        view_row.addWidget(self.view, 1)
        view_row.addWidget(self.doc_scroll)
        layout.addLayout(view_row, 1)

        self._page_item: Optional[QGraphicsPixmapItem] = None

        # 시그널
        self.view.fitPageRequested.connect(                       # 260618-16: 더블클릭=쪽 맞춤
            lambda: self.cmb_fit.setCurrentText(self.FIT_PAGE))
        self.btn_prev_page.clicked.connect(lambda: self._on_step_clicked(-1))
        self.btn_next_page.clicked.connect(lambda: self._on_step_clicked(+1))
        self.spin_page.editingFinished.connect(self._on_spin_edited)
        self.doc_scroll.valueChanged.connect(self._on_doc_scroll)
        vsb = self.view.verticalScrollBar()
        vsb.valueChanged.connect(self._on_view_scrolled)
        vsb.rangeChanged.connect(lambda *_: self._on_view_scrolled())
        self.cmb_fit.currentTextChanged.connect(self._set_fit_mode)
        self.btn_zoom_in.clicked.connect(lambda: self._zoom_by(1.15))
        self.btn_zoom_out.clicked.connect(lambda: self._zoom_by(1 / 1.15))

        self.view.zoomRequested.connect(self._zoom_by)
        self.view.pageStep.connect(self._on_page_step)
        # 260603: 호버 — 뷰가 zoom 조회용으로 owner 참조, hoverWord 재방출
        self.view._owner = self
        self.view.hoverWord.connect(self.wordHovered.emit)
        self.view.pageClicked.connect(self.pageClicked.emit)
        self.view.contextMenuRequested.connect(self.contextMenuRequested.emit)
        from PyQt6.QtGui import QShortcut, QKeySequence
        _sc_copy = QShortcut(QKeySequence.StandardKey.Copy, self.view,
                             activated=self.copy_selection)            # 260617-2 Ctrl+C
        _sc_copy.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.view.viewActivated.connect(self.activated.emit)

    def set_hover_words(self, items) -> None:
        """단어장 단어 호버 영역 설정. items=[(x0,y0,x1,y1,lemma)] (PDF point)."""
        self.view.set_hover_words(items)

    # --- 공개 API --------------------------------------------------------
    def _prompt_pdf_password(self, file_path, doc) -> bool:
        """암호 설정 PDF: 암호를 입력받아 doc 잠금 해제. 성공 True, 취소/실패 False.
        '암호 기억' 체크 시 Windows DPAPI 로 보호 저장(이 PC·계정 전용)."""
        from pathlib import Path as _P
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                     QLineEdit, QCheckBox, QPushButton, QMessageBox)
        from viewer import secure_store
        name = _P(str(file_path)).name
        for _attempt in range(3):
            dlg = QDialog(self); dlg.setWindowTitle("암호 입력")
            v = QVBoxLayout(dlg)
            v.addWidget(QLabel(f"'{name}'\n암호가 설정된 PDF입니다. 암호를 입력하세요:"))
            ed = QLineEdit(); ed.setEchoMode(QLineEdit.EchoMode.Password); v.addWidget(ed)
            chk = QCheckBox("이 파일의 암호 기억 (이 PC·계정에서만)")
            chk.setChecked(secure_store.available()); chk.setEnabled(secure_store.available())
            v.addWidget(chk)
            row = QHBoxLayout(); row.addStretch(1)
            ok_b = QPushButton("확인"); ca_b = QPushButton("취소")
            ok_b.setDefault(True); row.addWidget(ok_b); row.addWidget(ca_b)
            v.addLayout(row)
            ok_b.clicked.connect(dlg.accept); ca_b.clicked.connect(dlg.reject)
            ed.returnPressed.connect(dlg.accept)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return False
            pw = ed.text()
            if doc.authenticate(pw):
                secure_store.set_session(file_path, pw)     # 세션 공유(썸네일 등)
                if chk.isChecked():
                    secure_store.remember_password(file_path, pw)
                return True
            QMessageBox.warning(self, "암호 오류", "암호가 올바르지 않습니다.")
        return False

    def load_document(self, file_path, page_index: int = 0, query: str = "") -> bool:
        # 260611-64: 새 문서를 먼저 열고 인증까지 끝낸 뒤에야 기존 문서를 교체.
        #   암호 입력을 '취소'하면 기존 표시를 그대로 유지(빈 화면 방지). 반환 True=성공/False=취소.
        newdoc = PdfDocument(file_path)
        if newdoc.needs_password:
            from viewer import secure_store
            saved = secure_store.recall_any(file_path)
            if saved and newdoc.authenticate(saved):
                secure_store.set_session(file_path, saved)
            elif not self._prompt_pdf_password(file_path, newdoc):
                newdoc.close()
                return False                  # 취소 — 기존 self._doc / 화면 유지
        if self._doc is not None:
            self._doc.close()
        self._doc = newdoc
        self._is_image = False               # v1.6.4 C2: PDF 모드
        self._update_empty_label()           # 260606-30: 문서 로드 → 안내 숨김
        self._query = query or ""
        self._matches = self._doc.search(self._query) if self._query else []
        self._current_match = 0 if self._matches else -1

        # v1.6.8 F1: 메인 PDF 는 내장 세로바 숨김, doc_scroll(문서 진행률) 표시.
        self.view._image_mode = False
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.doc_scroll.setVisible(True)
        # v1.6.9 G1: 콤보를 PDF fit 으로 복귀 (이미지에서 돌아온 경우)
        self.cmb_fit.blockSignals(True)
        self.cmb_fit.setCurrentText(self._fit_mode)
        self.cmb_fit.blockSignals(False)

        self.spin_page.setMaximum(max(1, self._doc.page_count))
        self.lbl_page_total.setText(f"/ {self._doc.page_count}")
        # v1.6.0 M4: 2쪽 보기 모드는 다른 파일 열어도 유지. fit 모드 강제 리셋 안 함.
        # 260616-4: 검색 결과로 열렸으면 해당 페이지의 첫 매치를 '현재 매치'로 지정
        #   후 렌더(주황 강조 정확) → go_to_page → 매치로 중앙 스크롤(본문 즉시 표시).
        if self._matches:
            gi = self._first_global_match_index(page_index)
            if gi >= 0:
                self._current_match = gi
        self.go_to_page(page_index)
        if self._matches and self._current_match >= 0:
            self._scroll_to_current_match()
        return True

    def load_image(self, file_path):
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self._is_image = True                # v1.6.4 C2: 이미지 모드 → ◀▶ 가 리스트 순회
        self._update_empty_label()           # 260606-30: 이미지 로드 → 안내 숨김
        self._matches = []
        self._current_match = -1

        img = QImage(str(file_path))
        self.scene.clear()
        self._page_item = self.scene.addPixmap(QPixmap.fromImage(img))
        self.scene.setSceneRect(QRectF(img.rect()))
        self._image_size = img.size()

        # v1.6.9 G1/G2: 이미지 모드 — doc_scroll(리스트 진행률) 표시, 뷰 내장
        #               세로바 숨김(이미지내 스크롤은 그 값으로). 보기 옵션 작동.
        self.view._image_mode = True
        self.doc_scroll.setVisible(True)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 콤보를 이미지 전용 fit 으로 표시 (기본 쪽맞춤)
        self.cmb_fit.blockSignals(True)
        self.cmb_fit.setCurrentText(self._img_fit)
        self.cmb_fit.blockSignals(False)
        self._apply_image_fit()

        self.spin_page.setMaximum(1)
        self.spin_page.setValue(1)
        self.lbl_page_total.setText("/ 1")

    def _apply_image_fit(self):
        """v1.6.9 G1: 이미지에 _img_fit(쪽/폭/사용자비율) 적용."""
        if self._page_item is None:
            return
        mode = self._img_fit
        if mode in (self.FIT_PAGE, self.FIT_PAGE_TWO):
            self.view.resetTransform()
            self.view.fitInView(self.scene.sceneRect(),
                                Qt.AspectRatioMode.KeepAspectRatio)
        elif mode == self.FIT_WIDTH:
            self.view.resetTransform()
            vw = max(1, self.view.viewport().width())
            iw = max(1.0, self.scene.sceneRect().width())
            s = vw / iw
            if s > 0:
                self.view.scale(s, s)
        # FIT_NONE: 현재 transform 유지 (_zoom_by 가 증분 스케일)
        self.view.verticalScrollBar().setValue(0)
        self._update_doc_scroll()

    def set_image_position(self, idx: int, total: int):
        """v1.6.5 D1: 이미지 모드 페이지 바를 스크린샷 리스트 순번 i/N 으로."""
        total = max(1, int(total))
        idx = max(1, min(total, int(idx)))
        self._img_total = total                 # v1.6.9 G2
        self._img_idx0 = idx - 1
        self.spin_page.blockSignals(True)
        self.spin_page.setMinimum(1)
        self.spin_page.setMaximum(total)
        self.spin_page.setValue(idx)
        self.spin_page.blockSignals(False)
        self.lbl_page_total.setText(f"/ {total}")
        self._update_doc_scroll()               # v1.6.9 G2: 리스트 진행률 동기

    def add_main_button(self, btn):
        """v1.6.10 H2 / 260606-9: 페이지 바의 › 우측에 외부 버튼 삽입(FlowLayout)."""
        idx = self._toolbar.indexOf(self.btn_next_page)
        if idx < 0:
            self._toolbar.addWidget(btn)
            return
        self._toolbar.insertWidget(idx + 1, btn)

    def current_file(self):
        return str(self._doc.path) if self._doc else None

    def current_page(self) -> int:
        return self._current_page

    # ----- 260616-21/260617-2: 텍스트 블럭 선택·복사 -----
    def set_copy_allowed(self, allowed: bool):
        """260618-1: 문서 권한에 따른 복사 허용 여부(앱이 로드 후 설정)."""
        self._copy_allowed = bool(allowed)

    def arm_text_selection(self):
        """'블럭설정' — 선택 비우고 블럭설정 포인터로(우클릭 메뉴에서 호출)."""
        self.view.arm_text_select(True)

    def _region_text(self, scene_rect) -> str:
        """선택 사각 영역(scene QRectF) 안의 PDF 텍스트. 사용자 회전 페이지는 전체.
        내장 /Rotate 페이지는 표시→회전전(derotation) 변환해 정확히 클립."""
        if not self._doc:
            return ""
        z = self._zoom or 1.0
        urot = self._rotations.get(self._current_page, 0)
        try:
            page = self._doc.doc.load_page(self._current_page)
            if urot or scene_rect is None:
                return page.get_text("text")
            import fitz
            clip = fitz.Rect(scene_rect.left() / z, scene_rect.top() / z,
                             scene_rect.right() / z, scene_rect.bottom() / z)
            if page.rotation:                  # 표시 좌표 → 회전 전 좌표
                clip = clip * page.derotation_matrix
                clip.normalize()
            return page.get_text("text", clip=clip)
        except Exception:
            return ""

    def copy_block(self, scene_rect) -> int:
        """260617-5: 사각형 블럭(좌상→우하) 영역의 텍스트를 클립보드로."""
        from PyQt6.QtWidgets import QApplication
        if not self._doc:
            return 0
        if not self._copy_allowed:           # 260618-1: 복사 권한 없음
            self.textCopied.emit(-1); return 0
        txt = self._region_text(scene_rect)
        n = len((txt or "").strip())
        if n:
            QApplication.clipboard().setText(txt)
        self.textCopied.emit(n)
        return n

    def copy_page_text(self) -> int:
        """현재 페이지 전체 텍스트를 클립보드로. 반환: 글자수."""
        from PyQt6.QtWidgets import QApplication
        if not self._doc:
            return 0
        if not self._copy_allowed:           # 260618-1: 복사 권한 없음
            self.textCopied.emit(-1); return 0
        try:
            txt = self._doc.doc.load_page(self._current_page).get_text("text")
        except Exception:
            txt = ""
        n = len((txt or "").strip())
        if n:
            QApplication.clipboard().setText(txt)
        self.textCopied.emit(n)
        return n

    def copy_selection(self) -> int:
        """선택된 단어(드래그)의 텍스트를 복사. 선택이 없으면 현재 페이지 전체.
        (우클릭 '텍스트 복사' / Ctrl+C)"""
        from PyQt6.QtWidgets import QApplication
        if not self._doc:
            return 0
        if not self._copy_allowed:           # 260618-1: 복사 권한 없음
            self.textCopied.emit(-1); return 0
        txt = self._sel_text if (self._sel_text and self._sel_text.strip()) \
            else self._region_text(None)
        n = len((txt or "").strip())
        if n:
            QApplication.clipboard().setText(txt)
        self.textCopied.emit(n)
        return n

    # ----- 260617-3: 단어 단위 텍스트 선택(드래그 하이라이트) -----
    def _load_page_words(self):
        """현재 페이지의 단어 박스를 **표시 좌표**(내장 /Rotate 보정)로 적재. 읽기순.
        260617-4: get_text 좌표는 회전 전 공간이라 그대로 쓰면 하이라이트가 어긋남
        (단어장 하이라이트와 동일하게 `_disp_search_rect` 로 표시 좌표 변환).
        사용자 회전(_rotations) 페이지는 생략(페이지 텍스트 폴백)."""
        self._page_words = []
        if not self._doc:
            return
        if self._rotations.get(self._current_page, 0):
            return
        try:
            import fitz
            page = self._doc.doc.load_page(self._current_page)
            out = []
            for w in page.get_text("words", sort=True):
                r = self._disp_search_rect(page, fitz.Rect(w[0], w[1], w[2], w[3]))
                out.append((r.x0, r.y0, r.x1, r.y1, w[4], w[5], w[6]))
            self._page_words = out
        except Exception:
            self._page_words = []

    def _clear_sel_items(self):
        for it in getattr(self, "_sel_items", []):
            try:
                self.scene.removeItem(it)
            except Exception:
                pass
        self._sel_items = []

    def clear_text_selection(self):
        self._clear_sel_items()
        self._sel_text = ""
        self._sel_start = None

    def _word_index_near(self, px, py):
        best, bestd = -1, None
        for i, w in enumerate(self._page_words):
            x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
            dx = 0.0 if x0 <= px <= x1 else min(abs(px - x0), abs(px - x1))
            dy = 0.0 if y0 <= py <= y1 else min(abs(py - y0), abs(py - y1))
            d = dx * dx + (dy * 2.0) ** 2     # 같은 줄(y) 우선
            if bestd is None or d < bestd:
                bestd, best = d, i
        return best

    def _sel_begin(self, px, py):
        if not self._page_words:
            self._load_page_words()
        self._sel_start = (px, py)

    def _sel_update(self, px, py):
        if self._sel_start is None or not self._page_words:
            return
        i0 = self._word_index_near(*self._sel_start)
        i1 = self._word_index_near(px, py)
        if i0 < 0 or i1 < 0:
            return
        lo, hi = sorted((i0, i1))
        sel = self._page_words[lo:hi + 1]
        self._clear_sel_items()
        z = self._zoom or 1.0
        from PyQt6.QtWidgets import QGraphicsRectItem
        from PyQt6.QtGui import QBrush, QColor, QPen
        from PyQt6.QtCore import QRectF
        for w in sel:
            r = QRectF(w[0] * z, w[1] * z, (w[2] - w[0]) * z, (w[3] - w[1]) * z)
            it = QGraphicsRectItem(r)
            it.setBrush(QBrush(QColor(51, 153, 255, 80)))   # 반투명 파랑
            it.setPen(QPen(Qt.PenStyle.NoPen))
            self.scene.addItem(it)
            self._sel_items.append(it)
        out, last = "", None
        for w in sel:
            key = (w[5], w[6])               # (block, line)
            if last is None:
                out = w[4]
            elif key == last:
                out += " " + w[4]
            else:
                out += "\n" + w[4]
            last = key
        self._sel_text = out

    def _sel_end(self):
        pass                                 # 선택은 드래그 중 실시간 갱신됨

    def current_query(self) -> str:
        return self._query

    def grab_page(self) -> QPixmap:
        """v1.6.3 B2: 렌더된 페이지 영역만 캡처.

        `view` 전체를 grab 하면 항상 표시되는 세로 스크롤바(v1.5.2)와
        `#f5f5f5` 레터박스 여백이 PNG 에 박혀, 카드 재표시 시 검은 줄로 보임.
        현재 페이지 아이템의 화면 표시 사각형만 viewport 에서 잘라 grab 한다.
        페이지 아이템이 없으면 viewport 전체로 폴백.
        """
        vp = self.view.viewport()
        if self._page_item is not None:
            poly = self.view.mapFromScene(self._page_item.sceneBoundingRect())
            r = poly.boundingRect().intersected(QRect(0, 0, vp.width(), vp.height()))
            if r.width() > 0 and r.height() > 0:
                # 260615-3: ① 선긋기·하이퍼링크 오버레이까지 포함해 캡처 —
                #   vp.grab 은 페이지 픽스맵만 잡아 꾸밈/링크가 빠지므로 MainView 기준 grab.
                try:
                    off = vp.mapTo(self, QPoint(0, 0))
                    return self.grab(QRect(r.topLeft() + off, r.size()))
                except Exception:
                    return vp.grab(r)
        return vp.grab()

    def go_to_page(self, page_index: int):
        if not self._doc:
            return
        page_index = max(0, min(self._doc.page_count - 1, page_index))
        # 260609-26: 필터가 있으면 허용 페이지로 스냅(앞쪽 우선)
        if self._nav_pages and page_index not in set(self._nav_pages):
            fwd = [p for p in self._nav_pages if p >= page_index]
            page_index = fwd[0] if fwd else self._nav_pages[-1]
        self._current_page = page_index
        try:
            self.clear_text_selection()       # 260617-3: 페이지 바뀌면 텍스트 선택 해제
        except Exception:
            pass
        self._render_current()
        self._update_hidden_band()                           # 260609-14(D5): 페이지별 숨김 띠
        self._load_page_strokes()                            # 260609-22(J3): 페이지 선긋기 로드
        self._load_page_images()                             # 260611-15: 페이지 삽입 이미지 로드
        self.view.verticalScrollBar().setValue(0)            # 페이지 상단으로
        self.spin_page.blockSignals(True)
        self.spin_page.setValue(page_index + 1)
        self.spin_page.blockSignals(False)
        self.pageChanged.emit(page_index)
        self._update_match_counter()
        self._update_doc_scroll()             # v1.6.8 F1

    # --- v1.6.8 F1: 문서 전체 진행률 스크롤바 -----------------------------
    def _doc_units(self):
        """v1.6.9 G2: (총 항목수 N, 현재 인덱스 I). PDF=페이지, 이미지=스크린샷."""
        if self._is_image:
            return max(1, self._img_total), max(0, self._img_idx0)
        if self._doc:
            return max(1, self._doc.page_count), self._current_page
        return None

    def _update_doc_scroll(self):
        """항목/줌/스크롤 변경 시 doc_scroll 값을 전체 진행률로 동기."""
        if self._scroll_guard:
            return
        nu = self._doc_units()
        if nu is None:
            return
        n, i = nu
        U = self._DOC_U
        vsb = self.view.verticalScrollBar()
        frac = (vsb.value() / vsb.maximum()) if vsb.maximum() > 0 else 0.0
        val = int(i * U + frac * U)
        self._scroll_guard = True
        self.doc_scroll.setRange(0, max(0, n * U - 1))
        self.doc_scroll.setPageStep(U)
        self.doc_scroll.setSingleStep(max(1, U // 25))
        self.doc_scroll.setValue(max(0, min(n * U - 1, val)))
        self._scroll_guard = False

    def _on_doc_scroll(self, v: int):
        """사용자가 doc_scroll 을 움직임 → 해당 항목으로 점프 + 항목내 비율."""
        if self._scroll_guard:
            return
        nu = self._doc_units()
        if nu is None:
            return
        n, cur = nu
        U = self._DOC_U
        idx = max(0, min(n - 1, v // U))
        frac = (v - idx * U) / U
        if self._is_image:
            if idx != cur:
                self.imageGotoRequested.emit(idx)   # 앱이 해당 스크린샷 로드
        else:
            if idx != self._current_page:
                self.go_to_page(idx)
        vsb = self.view.verticalScrollBar()
        self._scroll_guard = True
        if vsb.maximum() > 0:
            vsb.setValue(int(frac * vsb.maximum()))
        self._scroll_guard = False
        self._update_doc_scroll()

    def _on_view_scrolled(self):
        """뷰 내장 세로 스크롤(휠/드래그/줌)이 바뀌면 doc_scroll 동기."""
        if self._scroll_guard:
            return
        if self._doc or self._is_image:
            self._update_doc_scroll()

    def _on_spin_edited(self):
        """페이지 번호 입력 — v1.6.8 F2: 이미지 모드면 스크린샷 이동."""
        v = self.spin_page.value() - 1
        if self._is_image:
            self.imageGotoRequested.emit(v)
        else:
            self.go_to_page(v)

    def set_query(self, query: str):
        self._query = query or ""
        self._matches = self._doc.search(self._query) if (self._doc and self._query) else []
        self._current_match = 0 if self._matches else -1
        self._render_current()
        self._update_match_counter()

    def go_next_match(self):
        if not self._matches:
            return
        total = sum(len(h.rects) for h in self._matches)
        if total == 0:
            return
        self._current_match = (self._current_match + 1) % total
        self._jump_to_match(self._current_match)

    def go_prev_match(self):
        if not self._matches:
            return
        total = sum(len(h.rects) for h in self._matches)
        if total == 0:
            return
        self._current_match = (self._current_match - 1) % total
        self._jump_to_match(self._current_match)

    def apply_theme(self, dark: bool):
        """260606-14: 메인 뷰어 배경(페이지 주변 여백)을 테마에 맞게."""
        if dark:
            self.scene.setBackgroundBrush(QColor(24, 24, 26))
            self.view.setBackgroundBrush(QColor(24, 24, 26))
        else:
            self.scene.setBackgroundBrush(QColor("white"))
            self.view.setBackgroundBrush(QColor("#f5f5f5"))
        # 260615-5: ④ 편집모드 도구(선종류/도형/글쓰기) 버튼 색을 테마에 맞춰 재적용
        for fn in ("_update_line_button", "_update_shape_button",
                   "_update_text_button"):
            try:
                getattr(self, fn)()
            except Exception:
                pass

    def set_fit_mode(self, mode: str):
        """settings 복원 등 외부에서 fit 모드 변경 (PDF 기준)."""
        if mode in (self.FIT_PAGE, self.FIT_PAGE_TWO, self.FIT_WIDTH, self.FIT_NONE):
            self._fit_mode = mode
            if not self._is_image:
                self.cmb_fit.blockSignals(True)
                self.cmb_fit.setCurrentText(mode)
                self.cmb_fit.blockSignals(False)
                self._render_current()

    def set_base_dpi(self, dpi: int):
        # 호환 유지용. 1:1 파이프라인에선 zoom 으로 통일.
        self._base_dpi = max(96, min(400, int(dpi)))

    # --- 내부: 줌/페이지 이벤트 ------------------------------------------
    def is_two_page_mode(self) -> bool:
        return self._fit_mode == self.FIT_PAGE_TWO

    # 260609-26: 썸네일 필터로 뷰어 페이지 이동 제한
    def set_nav_pages(self, pages):
        """허용 페이지 목록(정렬) 또는 None(전체). 현재 페이지가 빠지면 가까운 허용으로."""
        self._nav_pages = sorted(int(p) for p in pages) if pages is not None else None
        if (self._nav_pages is not None and self._doc and not self._is_image
                and self._current_page not in set(self._nav_pages)):
            self.go_to_page(self._current_page)   # go_to_page 가 스냅

    def _nav_step(self, cur, direction):
        """현재에서 direction(+1/-1) 방향 첫 허용 페이지. 없으면 None."""
        if not self._nav_pages:
            nxt = cur + direction
            return nxt if 0 <= nxt < self._doc.page_count else None
        if direction > 0:
            for p in self._nav_pages:
                if p > cur:
                    return p
        else:
            for p in reversed(self._nav_pages):
                if p < cur:
                    return p
        return None

    def _on_step_clicked(self, direction: int):
        """v1.6.4 C2: 이미지 모드면 스크린샷 리스트 순회, 아니면 페이지 이동.
        260609-2/26: 필터 허용 페이지만 순회, 경계면 파일 경계 신호."""
        if self._is_image:
            self.imageStepRequested.emit(direction)
            return
        if not self._doc:
            return
        nxt = self._nav_step(self._current_page, direction)
        if nxt is None:
            self.fileBoundaryRequested.emit(+1 if direction > 0 else -1)
            return
        self.go_to_page(nxt)

    def _on_page_step(self, delta: int):
        if self._is_image:                       # v1.6.9 G2: 스크린샷 리스트 순회
            self.imageStepRequested.emit(1 if delta > 0 else -1)
            return
        if not self._doc:
            return
        if delta == -10**6:
            self.go_to_page(self._nav_pages[0] if self._nav_pages else 0)
            return
        if delta == 10**6:
            self.go_to_page(self._nav_pages[-1] if self._nav_pages
                            else self._doc.page_count - 1)
            return
        nxt = self._nav_step(self._current_page, 1 if delta > 0 else -1)
        if nxt is None:
            self.fileBoundaryRequested.emit(+1 if delta > 0 else -1)
            return
        self.go_to_page(nxt)

    def _zoom_by(self, factor: float):
        # 사용자 비율로 전환
        self.cmb_fit.blockSignals(True)
        self.cmb_fit.setCurrentText(self.FIT_NONE)
        self.cmb_fit.blockSignals(False)
        if self._is_image:                       # v1.6.9 G1: 이미지 증분 줌
            self._img_fit = self.FIT_NONE
            self.view.scale(factor, factor)
            self._update_doc_scroll()
            return
        self._fit_mode = self.FIT_NONE
        self._zoom = max(0.1, min(20.0, self._zoom * factor))
        self._render_current()

    def _set_fit_mode(self, mode: str):
        if self._is_image:                       # v1.6.9 G1: 이미지 전용 fit
            self._img_fit = mode
            self._apply_image_fit()
            return
        self._fit_mode = mode
        self._render_current()

    # --- 핵심: 1:1 직접 렌더 ---------------------------------------------
    @staticmethod
    def _disp_search_rect(page_obj, r):
        """260611-99: search_for/텍스트 좌표(회전 전)를 표시 좌표로 — 내장 /Rotate 보정.

        PPT→PDF 등 /Rotate 90 페이지는 검색 결과가 '회전 전' 공간이라 그대로 쓰면
        하이라이트가 90° 어긋남. 페이지 회전행렬을 곱해 렌더(표시) 좌표로 변환."""
        if page_obj.rotation:
            r = r * page_obj.rotation_matrix
            r.normalize()
        return r

    def _render_current(self):
        if not self._doc:
            return

        # v1.5.0 M3: 2장 보기 분기
        if self._fit_mode == self.FIT_PAGE_TWO:
            self._render_two_pages()
            return

        page_obj = self._doc.doc.load_page(self._current_page)
        pdf_w = page_obj.rect.width
        pdf_h = page_obj.rect.height
        if pdf_w <= 0 or pdf_h <= 0:
            return
        # 260609-15(A1): 90/270 회전이면 맞춤 계산용 폭·높이 스왑
        _rot_fit = self._rotations.get(self._current_page, 0)
        if _rot_fit in (90, 270):
            pdf_w, pdf_h = pdf_h, pdf_w

        vp = self.view.viewport().size()
        vp_w = max(50, vp.width() - 4)
        vp_h = max(50, vp.height() - 4)

        # 표시 zoom 결정 (PDF 포인트 → 논리 픽셀)
        if self._fit_mode == self.FIT_PAGE:
            zoom = min(vp_w / pdf_w, vp_h / pdf_h)
        elif self._fit_mode == self.FIT_WIDTH:
            zoom = vp_w / pdf_w
        else:
            zoom = self._zoom

        zoom = max(0.1, min(20.0, zoom))
        self._zoom = zoom

        # 물리 픽셀 = 논리 * DPR. PyMuPDF 에 이 크기로 직접 요청.
        dpr = self.view.devicePixelRatioF() or 1.0
        physical_scale = zoom * dpr
        mat = fitz.Matrix(physical_scale, physical_scale)
        pix = page_obj.get_pixmap(matrix=mat, alpha=False)

        # samples 버퍼는 pix 의 수명에 묶여있으므로 QImage.copy() 로 분리
        img = QImage(
            pix.samples, pix.width, pix.height, pix.width * 3,
            QImage.Format.Format_RGB888,
        ).copy()
        qpix = QPixmap.fromImage(img)
        # 260609-15(A1): 페이지 회전 적용(렌더 후 픽스맵 회전)
        rot = self._rotations.get(self._current_page, 0)
        if rot:
            qpix = qpix.transformed(QTransform().rotate(rot),
                                    Qt.TransformationMode.SmoothTransformation)
        qpix.setDevicePixelRatio(dpr)

        self.scene.clear()
        self._page_item = self.scene.addPixmap(qpix)
        # 씬 좌표는 논리 픽셀(= 물리 / DPR). 이걸 1:1 로 표시.
        logical_w = qpix.width() / dpr
        logical_h = qpix.height() / dpr
        self.scene.setSceneRect(0, 0, logical_w, logical_h)

        # 하이라이트: PDF pt → 논리 px (= zoom 배). 회전 시 좌표 불일치 → 생략.
        if self._query and not rot:
            rects = page_obj.search_for(self._query)
            current_local = self._page_local_match_index()
            for i, r in enumerate(rects):
                r = self._disp_search_rect(page_obj, r)   # 260611-99: /Rotate 보정
                color = QColor(255, 165, 0, 110) if i == current_local else QColor(255, 235, 59, 90)
                pen = QPen(QColor(255, 140, 0)) if i == current_local else QPen(Qt.PenStyle.NoPen)
                rect = QRectF(r.x0 * zoom, r.y0 * zoom,
                              (r.x1 - r.x0) * zoom, (r.y1 - r.y0) * zoom)
                item = QGraphicsRectItem(rect)
                item.setBrush(QBrush(color))
                item.setPen(pen)
                self.scene.addItem(item)

        # 항상 1:1 로 표시 (Qt 스케일 transform 없음)
        self.view.resetTransform()

        # 260617-3: scene.clear() 로 선택 하이라이트도 사라짐 → 상태 초기화 + 단어 박스 재적재
        self._sel_items = []
        self._sel_text = ""
        self._sel_start = None
        self._load_page_words()
        # 단어학습 하이라이트 재적용(있으면) — 재렌더 후에도 유지
        # scene.clear() 가 이미 그래픽 아이템을 제거했으므로 리스트를 비우고 다시 그림(스테일 누적 방지)
        if getattr(self, "_word_hl_groups", None):
            self._word_hl_items = []
            self._draw_word_highlights()
        # 260611-107: 하이퍼링크 버튼은 렌더된 페이지 기준으로 위치 → 매 렌더 후 재배치
        #   (페이지 선택/이동 시 set_hyperlinks 가 렌더 전 호출돼 숨겨지던 문제 수정)
        self._position_hl_overlay()

    # --- 단어학습 하이라이트 (P4 / 260603) --------------------------------
    def clear_word_highlights(self):
        for it in getattr(self, "_word_hl_items", []):
            try:
                self.scene.removeItem(it)
            except Exception:
                pass
        self._word_hl_items = []
        self._word_hl_groups = []     # [(rects_pt, style)]

    # 스타일별 (배경, 테두리)
    _HL_STYLES = {
        "select":     (QColor(0, 180, 0, 70),  QColor(0, 140, 0)),     # 단어 클릭(초록)
        "all":        (QColor(255, 230, 0, 55), None),                 # 본문강조(옅은 노랑)
        "read":       (QColor(120, 180, 255, 80), None),               # 읽는 문장(옅은 파랑)
        "read_vocab": (QColor(255, 150, 0, 130), None),                # 읽는 문장 속 단어장 단어(주황)
    }

    def _draw_word_highlights(self):
        self._word_hl_items = getattr(self, "_word_hl_items", [])
        z = self._zoom
        for rects, style in getattr(self, "_word_hl_groups", []):
            bg, border = self._HL_STYLES.get(style, self._HL_STYLES["select"])
            brush = QBrush(bg)
            pen = QPen(border) if border is not None else QPen(Qt.PenStyle.NoPen)
            for (x0, y0, x1, y1) in rects:
                item = QGraphicsRectItem(QRectF(x0 * z, y0 * z, (x1 - x0) * z, (y1 - y0) * z))
                item.setBrush(brush)
                item.setPen(pen)
                self.scene.addItem(item)
                self._word_hl_items.append(item)

    def highlight_word_groups(self, groups, scroll: bool = True):
        """여러 묶음을 각자 스타일로 강조. groups=[(rects_pt, style), ...].
        scroll=True 면 첫 사각형이 보이도록 스크롤."""
        self.clear_word_highlights()
        self._word_hl_groups = [(list(r), s) for (r, s) in groups if r]
        if not self._word_hl_groups:
            return
        self._draw_word_highlights()
        if scroll:
            x0, y0, x1, y1 = self._word_hl_groups[0][0][0]
            z = self._zoom
            self.view.ensureVisible(QRectF(x0 * z, y0 * z, (x1 - x0) * z, (y1 - y0) * z))

    def highlight_word_rects(self, rects_pt: list, strong: bool = True,
                             style: str = None, scroll: bool = None):
        """단일 묶음 강조(호환). style 미지정 시 strong→select/all."""
        if style is None:
            style = "select" if strong else "all"
        if scroll is None:
            scroll = (style != "all")
        self.highlight_word_groups([(list(rects_pt or []), style)], scroll=scroll)


    def _render_two_pages(self):
        """v1.5.0 M3: 페이지 N과 N+1을 가로로 합쳐 한 화면에 표시."""
        from PyQt6.QtGui import QPainter as _QP
        n = self._doc.page_count
        idx_left = self._current_page
        idx_right = idx_left + 1 if (idx_left + 1) < n else None

        page_left = self._doc.doc.load_page(idx_left)
        pdf_w_l = page_left.rect.width
        pdf_h_l = page_left.rect.height
        page_right = self._doc.doc.load_page(idx_right) if idx_right is not None else None
        pdf_w_r = page_right.rect.width if page_right else 0
        pdf_h_r = page_right.rect.height if page_right else 0

        gap_pt = 8.0
        total_pdf_w = pdf_w_l + gap_pt + pdf_w_r
        total_pdf_h = max(pdf_h_l, pdf_h_r)
        if total_pdf_w <= 0:
            return

        vp = self.view.viewport().size()
        vp_w = max(50, vp.width() - 4)
        vp_h = max(50, vp.height() - 4)
        zoom = min(vp_w / total_pdf_w, vp_h / total_pdf_h)
        zoom = max(0.1, min(20.0, zoom))
        self._zoom = zoom

        dpr = self.view.devicePixelRatioF() or 1.0
        ps = zoom * dpr
        mat = fitz.Matrix(ps, ps)
        pix_l = page_left.get_pixmap(matrix=mat, alpha=False)
        pix_r = page_right.get_pixmap(matrix=mat, alpha=False) if page_right else None

        gap_px = int(gap_pt * ps)
        total_w_px = pix_l.width + gap_px + (pix_r.width if pix_r else 0)
        total_h_px = max(pix_l.height, pix_r.height if pix_r else 0)

        # 합성 캔버스
        canvas = QPixmap(total_w_px, total_h_px)
        canvas.fill(QColor("white"))
        painter = _QP(canvas)
        img_l = QImage(pix_l.samples, pix_l.width, pix_l.height,
                       pix_l.width * 3, QImage.Format.Format_RGB888).copy()
        painter.drawPixmap(0, 0, QPixmap.fromImage(img_l))
        if pix_r:
            img_r = QImage(pix_r.samples, pix_r.width, pix_r.height,
                           pix_r.width * 3, QImage.Format.Format_RGB888).copy()
            painter.drawPixmap(pix_l.width + gap_px, 0, QPixmap.fromImage(img_r))
        painter.end()
        canvas.setDevicePixelRatio(dpr)

        self.scene.clear()
        self._page_item = self.scene.addPixmap(canvas)
        self.scene.setSceneRect(0, 0, total_w_px / dpr, total_h_px / dpr)

        # 하이라이트 (현재 페이지 = 좌측)
        if self._query:
            for pg, off_pt_x in [(page_left, 0.0)]:
                rects = pg.search_for(self._query)
                for r in rects:
                    r = self._disp_search_rect(pg, r)        # 260611-99: /Rotate 보정
                    rect = QRectF((r.x0 + off_pt_x) * zoom, r.y0 * zoom,
                                  (r.x1 - r.x0) * zoom, (r.y1 - r.y0) * zoom)
                    item = QGraphicsRectItem(rect)
                    item.setBrush(QBrush(QColor(255, 235, 59, 90)))
                    item.setPen(QPen(Qt.PenStyle.NoPen))
                    self.scene.addItem(item)
            if page_right:
                off_x = pdf_w_l + gap_pt
                rects = page_right.search_for(self._query)
                for r in rects:
                    r = self._disp_search_rect(page_right, r)  # 260611-99: /Rotate 보정
                    rect = QRectF((r.x0 + off_x) * zoom, r.y0 * zoom,
                                  (r.x1 - r.x0) * zoom, (r.y1 - r.y0) * zoom)
                    item = QGraphicsRectItem(rect)
                    item.setBrush(QBrush(QColor(255, 235, 59, 90)))
                    item.setPen(QPen(Qt.PenStyle.NoPen))
                    self.scene.addItem(item)

        self.view.resetTransform()
        self._position_hl_overlay()        # 260609-11(C8): 페이지 위치 기준 버튼 재배치
        self._update_hidden_band()         # 260609-14(D5): 숨김 띠 위치/표시
        self._position_draw_overlay()      # 260609-22(J3): 선긋기 오버레이 위치

    def _update_empty_label(self):
        """260606-30: 문서/이미지 없을 때만 중앙 안내 라벨 표시·중앙 배치."""
        lab = getattr(self, "_empty_label", None)
        if lab is None:
            return
        empty = (self._doc is None) and (not self._is_image)
        lab.setVisible(empty)
        if empty:
            lab.adjustSize()
            vp = self.view.viewport().rect() if self.view.viewport() else self.view.rect()
            lab.move(vp.center().x() - lab.width() // 2,
                     vp.center().y() - lab.height() // 2)
            lab.raise_()

    def set_hyperlink_offset(self, px: int):
        """260609-11(C8): 페이지 상단에서 버튼까지의 오프셋(px) 설정."""
        self._hl_top_offset = max(0, int(px))
        self._relayout_hl()

    def set_hidden_pages(self, pages):
        """260609-14(D5): 숨김 페이지 집합 — 현재 페이지면 우측 띠 표시."""
        self._hidden_pages = set(int(p) for p in (pages or set()))
        self._update_hidden_band()

    def set_rotations(self, rotations):
        """260609-15(A1): {page0: deg} — 현재 페이지 회전 반영."""
        self._rotations = {int(k): int(v) % 360 for k, v in (rotations or {}).items()}
        if self._doc and not self._is_image:
            self._render_current()

    # ===== 260609-22(J3): 본화면 선긋기 ================================
    def _build_draw_bar(self, H):
        w = QWidget()
        hb = QHBoxLayout(w); hb.setContentsMargins(8, 0, 0, 0); hb.setSpacing(3)
        sep = QLabel("✏"); sep.setFixedHeight(H); hb.addWidget(sep)
        # 260611-1: 펜 1~5, 각 버튼 배경을 펜 색·투명도로 채움
        #   (_build_ui 가 _draw_pens 초기화보다 먼저 호출되므로 모듈 상수로 개수 결정)
        self._draw_pen_btns = []
        for i in range(len(MV_DEFAULT_PENS)):
            b = QPushButton(str(i + 1)); b.setFixedSize(24, H); b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=i: self._on_draw_pen(k))
            hb.addWidget(b); self._draw_pen_btns.append(b)
        # 260611-2: 선 종류 3단계 순환 — 0=직선(얇은) / 1=하이라이트(굵은) / 2=자유곡선
        # 260611-71: 선긋기 토글 — 클릭=선택/해제, 더블클릭=선 종류 변경
        self._draw_mode_btn = _DblTool()
        self._draw_mode_btn.setFixedSize(30, H)
        self._draw_mode_btn.setText(self._MODE_GLYPH[0])
        self._draw_mode_btn.setToolTip("선긋기 — 클릭:선택/해제, 더블클릭:선 종류 변경")
        self._draw_mode_btn.singleClick.connect(self._toggle_line)
        self._draw_mode_btn.doubleClick.connect(self._cycle_draw_mode)
        hb.addWidget(self._draw_mode_btn)
        # 260611-69/71: 도형 버튼 — 클릭=선택/해제, 더블클릭=종류 변경, 우측 풀다운=채움 스타일
        from PyQt6.QtWidgets import QMenu as _QMenu
        self._shape_btn = _DblTool()
        self._shape_btn.setFixedSize(46, H)        # 글리프+풀다운 화살표가 다 보이게 폭 확보
        self._shape_btn.setStyleSheet("QToolButton{font-size:17px;}")
        self._shape_btn.setText(self._SHAPE_GLYPH["rect"])
        self._shape_btn.setToolTip("도형 — 클릭:선택/해제, 더블클릭:종류 변경, ▾:채움")
        self._shape_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._shape_btn.singleClick.connect(self._toggle_shape)
        self._shape_btn.doubleClick.connect(self._cycle_shape_kind)
        sm = _QMenu(self._shape_btn)
        for key, label in (("none", "채움 없음"), ("semi", "반투명 채움"), ("full", "채움")):
            a = sm.addAction(label); a.setCheckable(True); a.setData(key)
            a.triggered.connect(lambda _=False, k=key: self._set_shape_fill(k))
        self._shape_menu = sm; self._shape_btn.setMenu(sm)
        hb.addWidget(self._shape_btn)
        # 260611-74(Phase2): 글쓰기 버튼 — 클릭=선택/해제, 더블클릭=글쓰기↔지시선, ▾=스타일
        self._text_btn = _DblTool()
        self._text_btn.setFixedSize(46, H)
        self._text_btn.setStyleSheet("QToolButton{font-size:15px;font-weight:bold;}")
        self._text_btn.setText(self._TEXT_GLYPH["text"])
        self._text_btn.setToolTip("글쓰기 — 클릭:선택/해제, 더블클릭:글쓰기↔지시선, ▾:스타일")
        self._text_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self._text_btn.singleClick.connect(self._toggle_text)
        self._text_btn.doubleClick.connect(self._cycle_text_kind)
        # 260611-78: 풀다운은 사용자 저장 스타일로 동적 구성(_rebuild_text_menu)
        self._text_menu = _QMenu(self._text_btn)
        self._text_btn.setMenu(self._text_menu)
        hb.addWidget(self._text_btn)
        # 260611-16: 개체선택 버튼(선 종류 버튼 오른쪽) — 눌러서 이미지 선택/이동/수정
        self._draw_select_btn = QPushButton("⤢"); self._draw_select_btn.setFixedSize(28, H)
        self._draw_select_btn.setCheckable(True)
        self._draw_select_btn.setToolTip("개체 선택(이미지 이동·크기·삭제)")
        self._draw_select_btn.clicked.connect(self._on_draw_select)
        hb.addWidget(self._draw_select_btn)
        # 260611-1: 지우개 2종(얇게/두껍게)·청소 — 첨부 아이콘 사용(없으면 글리프 폴백)
        self._draw_erase_btns = []
        _ico_sz = QSize(H - 4, H - 4)
        for k, t, fn, glyph in [(0, "지우개(얇게)", "icon_eraser_thin.png", "⌫"),
                                (1, "지우개(두껍게)", "icon_eraser_thick.png", "⌦")]:
            b = QPushButton(); b.setFixedSize(28, H); b.setCheckable(True)
            b.setToolTip(t)
            _ip = resource_path(fn)
            if _ip:
                b.setIcon(QIcon(_ip)); b.setIconSize(_ico_sz)
            else:
                b.setText(glyph)
            b.clicked.connect(lambda _=False, kk=k: self._on_draw_erase(kk))
            hb.addWidget(b); self._draw_erase_btns.append(b)
        bclr = QPushButton(); bclr.setFixedSize(30, H); bclr.setToolTip("청소(현재 페이지 선긋기 지움)")
        _bp = resource_path("icon_broom.png")
        if _bp:
            bclr.setIcon(QIcon(_bp)); bclr.setIconSize(_ico_sz)
        else:
            bclr.setText("청소")
        bclr.clicked.connect(self.clear_page_drawings)
        hb.addWidget(bclr)
        # 260611-80: 되돌리기 / 다시실행
        self._undo_btn = QPushButton("↶"); self._undo_btn.setFixedSize(28, H)
        self._undo_btn.setToolTip("되돌리기 (Ctrl+Z)")
        self._undo_btn.clicked.connect(self.undo_strokes)
        self._undo_btn.setEnabled(False)
        hb.addWidget(self._undo_btn)
        self._redo_btn = QPushButton("↷"); self._redo_btn.setFixedSize(28, H)
        self._redo_btn.setToolTip("다시실행 (Ctrl+Y)")
        self._redo_btn.clicked.connect(self.redo_strokes)
        self._redo_btn.setEnabled(False)
        hb.addWidget(self._redo_btn)
        self._restyle_pen_btns()
        return w

    @staticmethod
    def _pen_btn_css(pen, checked):
        """260611-1/5: 펜 색·투명도 배경 + 명도 대비 글자색 + 활성 테두리(굵게)."""
        c = QColor(pen.get("color", "#ff3030"))
        a = max(0.15, min(1.0, float(pen.get("alpha", 100)) / 100.0))
        # 명도(YIQ) 로 글자색 결정
        yiq = (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000.0
        fg = "#000000" if yiq >= 140 else "#ffffff"
        # 260611-5: 선택 테두리를 더 굵고 또렷하게(4px 주황) — 구분 쉽게
        bd = "4px solid #ff7a00" if checked else "1px solid #888"
        return (f"QPushButton{{background:rgba({c.red()},{c.green()},{c.blue()},{a:.2f});"
                f"color:{fg};border:{bd};border-radius:4px;font-weight:bold;}}")

    def _restyle_pen_btns(self):
        pens = getattr(self, "_draw_pens", MV_DEFAULT_PENS)
        for i, b in enumerate(getattr(self, "_draw_pen_btns", [])):
            if i < len(pens):
                b.setStyleSheet(self._pen_btn_css(pens[i], b.isChecked()))

    def set_draw_mode(self, on):
        """편집모드 진입/이탈 — 선긋기 도구 모음 표시·도구 해제."""
        self._draw_bar.setVisible(bool(on))
        if not on:
            self._pen_idx = None; self._draw_kind = "line"; self._shape_kind = "rect"
            self._stroke_selected = -1
            self._apply_tool()           # 260611-76: 편집 종료 시 모드/펜 해제·복귀
        self.set_image_edit(bool(on))      # 260611-15: 이미지 조작도 편집모드에서만
        # 260611-2: 도구바 표시로 뷰포트 크기가 바뀌므로 오버레이 위치 재동기
        from PyQt6.QtCore import QTimer as _QT
        _QT.singleShot(0, self._position_draw_overlay)

    def _on_draw_pen(self, idx):
        """260611-76: 색상버튼 = 스타일(색·굵기·투명도) 선택. 모드(선/도형/글쓰기)는 유지.
        같은 펜 재클릭 = 스타일 해제. 모드가 비어 있으면 기본 '선긋기'로 작동 시작."""
        self._pen_idx = None if self._pen_idx == idx else idx
        if self._pen_idx is not None and self._draw_kind in (None, "erase"):
            self._draw_kind = "line"      # 색상버튼만 누르면 자연스럽게 선긋기 시작
        self._apply_tool()

    def _on_draw_erase(self, k):
        """260611-76: 지우개 = 별도 모드. 4버튼과 상호배타. 같은 지우개 재클릭=해제."""
        if self._draw_kind == "erase" and self._erase_k == k:
            self._draw_kind = "line"
        else:
            self._draw_kind = "erase"; self._erase_k = k
        self._apply_tool()

    def _on_draw_select(self):
        """260611-76: 개체선택 모드 토글(4버튼 상호배타). 색상버튼 스타일은 보존."""
        self._draw_kind = None if self._draw_kind == "select" else "select"
        self._apply_tool()

    # 260611-2: 선 종류 3단계 — 글리프/이름
    _MODE_GLYPH = ("─", "▬", "〜")
    _MODE_NAME = ("직선", "하이라이트", "자유곡선")
    # 260611-69/71: 도형 글리프(크게 보이는 글자)
    _SHAPE_GLYPH = {"rect": "▭", "round": "❒", "circle": "◯"}
    _SHAPE_KIND_ORDER = ["rect", "round", "circle"]
    # 260611-74: 글쓰기 버튼 글리프 — 글쓰기=T, 지시선=T+지시(↘)
    _TEXT_GLYPH = {"text": "T", "leader": "T↘"}
    _TEXT_NAME = {"text": "글쓰기", "leader": "지시선 글쓰기"}
    # 클래스 기본값 — _build_ui→_update_text_button 이 __init__ 상태블록보다 먼저 호출됨
    _text_kind = "text"
    _text_style = "본문"

    def _sync_draw_buttons(self):
        """260611-74: 선/도형/글쓰기 버튼 활성 테두리 동기. 글쓰기 이탈 시 인라인 편집 커밋."""
        if self._draw_kind != "text":
            self._commit_text_editor()
            self._leader_drag = None
        self._update_line_button()
        self._update_shape_button()
        self._update_text_button()

    def _apply_tool(self):
        """260611-76: 모드(_draw_kind)+스타일(_pen_idx)→파생 _draw_tool 재계산 후 UI 동기.
        - erase                         → ('erase', width)
        - select                        → ('select', None)
        - line/shape/text + 펜 선택      → ('pen', idx)
        - 그 외(모드 없음/펜 없음)        → None
        4개 모드는 상호배타(_draw_kind 단일값), 색상버튼은 독립 스타일."""
        k = self._draw_kind
        if k == "erase":
            ew = self._draw_eraser_widths
            w = ew[self._erase_k] if self._erase_k < len(ew) else 16
            tool = ("erase", int(w))
        elif k == "select":
            tool = ("select", None)
        elif k in ("line", "shape", "text") and self._pen_idx is not None:
            tool = ("pen", self._pen_idx)
        else:
            tool = None
        self._draw_tool = tool
        if tool != ("select", None):
            self._stroke_drag = None
        ov = self._draw_overlay
        if ov is not None:
            ov.set_active(tool is not None)
        self._sync_draw_buttons()
        self._update_draw_buttons()

    def _toggle_line(self):
        """260611-71/76: 선긋기 단일 클릭 = 선택/해제 토글(4버튼 상호배타)."""
        self._draw_kind = None if self._draw_kind == "line" else "line"
        self._stroke_selected = -1
        self._apply_tool()

    def _cycle_draw_mode(self):
        """260611-2/71: 선긋기 더블 클릭 = 선 종류(직선→하이라이트→자유곡선) 변경(+선택)."""
        self._draw_kind = "line"
        self._stroke_selected = -1
        self.set_draw_line_mode((self._draw_line_mode + 1) % 3)
        self.drawModeChanged.emit(self._draw_line_mode)
        self._apply_tool()

    def _toggle_shape(self):
        """260611-71/76: 도형 단일 클릭 = 선택/해제 토글(4버튼 상호배타)."""
        self._draw_kind = None if self._draw_kind == "shape" else "shape"
        if self._draw_kind != "shape":
            self._stroke_selected = -1
        self._apply_tool()

    def _cycle_shape_kind(self):
        """260611-71: 도형 더블 클릭 = 종류(직사각형→둥근→원형) 변경(+선택)."""
        i = self._SHAPE_KIND_ORDER.index(self._shape_kind) if self._shape_kind in self._SHAPE_KIND_ORDER else 0
        self._shape_kind = self._SHAPE_KIND_ORDER[(i + 1) % len(self._SHAPE_KIND_ORDER)]
        self._draw_kind = "shape"
        self._apply_tool()

    def _set_shape_fill(self, kind):
        self._shape_fill = kind
        self._update_shape_button()

    def _update_line_button(self):
        if not hasattr(self, "_draw_mode_btn"):
            return
        on = self._draw_kind == "line"
        self._draw_mode_btn.setText(self._MODE_GLYPH[self._draw_line_mode])
        self._draw_mode_btn.setStyleSheet(self._dbl_css(on))

    @staticmethod
    def _dbl_css(on, font_px=None):
        """260611-80: 선/도형/글쓰기 토글 버튼 — 활성 시 배경+굵은 주황 테두리로 확실히 구분.
        260615-5: ④ 다크모드에서 비활성 버튼이 흰색으로 보이던 문제 → 테마별 색."""
        fp = ("font-size:%dpx;" % font_px) if font_px else ""
        if on:                       # 활성 = 주황 강조(양 테마 공통, 글자 어둡게)
            return ("QToolButton{%sbackground:#ffce99;border:3px solid #ff7a00;"
                    "border-radius:4px;font-weight:bold;color:#202020;}" % fp)
        from viewer import theme as _theme
        if _theme.is_dark():         # 다크 = 어두운 배경 + 밝은 글자
            return ("QToolButton{%sbackground:#3a3a3d;border:1px solid #666;"
                    "border-radius:4px;font-weight:bold;color:#e6e6e6;}" % fp)
        return ("QToolButton{%sbackground:#f3f3f3;border:1px solid #888;"
                "border-radius:4px;font-weight:bold;color:#202020;}" % fp)

    def _update_shape_button(self):
        if not hasattr(self, "_shape_btn"):
            return
        self._shape_btn.setText(self._SHAPE_GLYPH.get(self._shape_kind, "▭"))
        self._shape_btn.setStyleSheet(self._dbl_css(self._draw_kind == "shape", font_px=17))
        for a in self._shape_menu.actions():
            a.setChecked(a.data() == self._shape_fill)

    # ===== 260611-74(Phase2): 글쓰기 버튼 토글/스타일 =====
    def _toggle_text(self):
        """글쓰기 단일 클릭 = 선택/해제 토글(4버튼 상호배타)."""
        self._draw_kind = None if self._draw_kind == "text" else "text"
        if self._draw_kind != "text":
            self._stroke_selected = -1
        self._apply_tool()

    def _cycle_text_kind(self):
        """글쓰기 더블 클릭 = 글쓰기 ↔ 지시선 전환(+선택)."""
        self._commit_text_editor()
        self._text_kind = "leader" if self._text_kind == "text" else "text"
        self._draw_kind = "text"
        self._apply_tool()

    _STYLE_KEYS = ("family", "size", "color", "bold", "italic",
                   "box_line", "bg", "bg_alpha", "align")

    def _seed_text_styles(self):
        """260611-78: 기본 글쓰기 스타일(본문/제목/메모/강조)을 전체 필드 dict 로."""
        out = []
        for name, s in MV_TEXT_STYLES:
            out.append({"name": name, "family": "맑은 고딕", "size": float(s["size"]),
                        "color": s["color"], "bold": bool(s["bold"]),
                        "italic": bool(s.get("italic", False)),
                        "box_line": s["border"] is not None, "bg": s["bg"],
                        "bg_alpha": 100, "align": 0, "tip": "arrow"})
        return out

    def set_text_styles(self, styles):
        """260611-78/79: 저장 스타일 목록 주입 → 풀다운 재구성 + 현재 스타일을 즉시 재적용
        (스타일을 수정·저장하면 이후 작업에 바로 반영되도록 기본값을 갱신)."""
        self._text_styles = [dict(s) for s in (styles or [])] or self._seed_text_styles()
        names = [s.get("name") for s in self._text_styles]
        if self._text_style not in names:
            self._text_style = names[0] if names else "본문"
        self._rebuild_text_menu()
        self._set_text_style(self._text_style)   # 편집된 스타일 값을 기본값에 즉시 반영

    def _rebuild_text_menu(self):
        if not hasattr(self, "_text_menu"):
            return
        self._text_menu.clear()
        for s in getattr(self, "_text_styles", []):
            nm = s.get("name", "")
            a = self._text_menu.addAction(nm); a.setCheckable(True); a.setData(nm)
            a.triggered.connect(lambda _=False, n=nm: self._set_text_style(n))
        self._update_text_button()

    def _set_text_style(self, name):
        """풀다운 = 저장 스타일 적용 → 기본 스타일(글쓰기·지시선) + 선택 박스에 반영.
        글쓰기 모드에는 선 끝모양(tip)을 적용하지 않음(선이 없음)."""
        sd = next((s for s in getattr(self, "_text_styles", []) if s.get("name") == name), None)
        if sd is None:
            return
        self._text_style = name
        upd = {k: sd[k] for k in self._STYLE_KEYS if k in sd}
        self._text_defaults.update(upd)
        ldupd = dict(upd)
        if "tip" in sd:
            ldupd["tip"] = sd["tip"]
        self._leader_defaults.update(ldupd)
        box = self._selected_textbox()
        if box is not None:
            box.update(upd)
            if box.get("leader") and "tip" in sd:   # 지시선만 끝모양 적용
                box["tip"] = sd["tip"]
            self._save_page_strokes()
            if self._draw_overlay is not None:
                self._draw_overlay.update()
        self._update_text_button()

    # ===== 260611-77: 신규 박스 기본 스타일 get/set =====
    def text_defaults(self, leader):
        return dict(self._leader_defaults if leader else self._text_defaults)

    def set_text_defaults(self, leader, **fields):
        (self._leader_defaults if leader else self._text_defaults).update(fields)

    def _update_text_button(self):
        if not hasattr(self, "_text_btn"):
            return
        self._text_btn.setText(self._TEXT_GLYPH.get(self._text_kind, "T"))
        self._text_btn.setStyleSheet(self._dbl_css(self._draw_kind == "text", font_px=15))
        self._text_btn.setToolTip(
            f"{self._TEXT_NAME.get(self._text_kind,'글쓰기')} — 클릭:선택/해제, "
            f"더블클릭:글쓰기↔지시선, ▾:스타일({self._text_style})")
        if hasattr(self, "_text_menu"):
            for a in self._text_menu.actions():
                a.setChecked(a.data() == self._text_style)

    def set_draw_line_mode(self, mode):
        """260611-2: 0=직선 / 1=하이라이트 / 2=자유곡선. 버튼 글리프·툴팁 갱신."""
        self._draw_line_mode = int(mode) % 3
        if hasattr(self, "_draw_mode_btn"):
            self._draw_mode_btn.setText(self._MODE_GLYPH[self._draw_line_mode])
            self._draw_mode_btn.setToolTip(
                f"선 종류: {self._MODE_NAME[self._draw_line_mode]} (클릭해 전환)")

    def _highlight_alpha(self):
        """260611-2: 하이라이트 전용 불투명도(%) — 옵션값 또는 기본 35."""
        return int(getattr(self, "_draw_highlight_alpha", 35))

    def _update_draw_buttons(self):
        # 260611-76: 색상버튼=스타일(_pen_idx, 모드와 독립), 지우개/개체선택=모드(_draw_kind)
        for i, b in enumerate(getattr(self, "_draw_pen_btns", [])):
            b.setChecked(self._pen_idx == i)
        for k, b in enumerate(getattr(self, "_draw_erase_btns", [])):
            b.setChecked(self._draw_kind == "erase" and self._erase_k == k)
        sb = getattr(self, "_draw_select_btn", None)
        if sb is not None:
            sb.setChecked(self._draw_kind == "select")
        self._restyle_pen_btns()

    @staticmethod
    def _pad_pens(pens):
        """260611-5: 펜 개수를 버튼 수(MV_DEFAULT_PENS)만큼 채움 — 4·5 인덱스 오류 방지."""
        out = list(pens or [])
        while len(out) < len(MV_DEFAULT_PENS):
            out.append(dict(MV_DEFAULT_PENS[len(out)]))
        return out

    def set_main_pens(self, pens):
        """260611-1: 설정에서 5펜 갱신 — 버튼 배경 재적용(개수 부족분 보충)."""
        self._draw_pens = self._pad_pens(pens or self._draw_pens)
        self._restyle_pen_btns()

    def _hl_default_h(self):
        """260611-1: 줄 탐지 실패 시 폴백 띠 높이(정규화) — 페이지 높이의 소량."""
        return 0.018

    def _hl_band_at(self, fx, fy):
        """260611-1: 정규화 좌표(fx,fy)의 텍스트 줄 (y0n, y1n). 못 찾으면 None."""
        try:
            if not self._doc or self._is_image:
                return None
            page = self._doc.doc.load_page(self._current_page)
            pw, ph = page.rect.width, page.rect.height
            if pw <= 0 or ph <= 0:
                return None
            py = fy * ph
            best = None; bestd = ph * 0.5
            d = page.get_text("dict")
            for blk in d.get("blocks", []):
                for ln in blk.get("lines", []):
                    x0, y0, x1, y1 = ln.get("bbox", (0, 0, 0, 0))
                    if y1 <= y0:
                        continue
                    dist = 0.0 if y0 <= py <= y1 else min(abs(py - y0), abs(py - y1))
                    if dist < bestd:
                        bestd = dist; best = (y0 / ph, y1 / ph)
            return best
        except Exception:
            return None

    def set_draw_config(self, pens, line_mode, eraser_widths, highlight_alpha,
                        resolver, setter):
        """260611-2: 앱이 공유 펜/모드/지우개폭/하이라이트투명도/저장콜백을 주입."""
        self._draw_pens = self._pad_pens(pens or self._draw_pens)
        self.set_draw_line_mode(int(line_mode or 0))
        if eraser_widths:
            self._draw_eraser_widths = list(eraser_widths)
        self._draw_highlight_alpha = int(highlight_alpha or 35)
        self._draw_resolver = resolver
        self._draw_setter = setter
        self._restyle_pen_btns()
        self._load_page_strokes()

    def set_draw_tool(self, tool):
        """260611-76: 호환 API. None=전체 해제. ('pen',idx)/('erase',w)/('select',None)도
        새 모드/스타일 모델로 매핑(파생 _draw_tool 재계산)."""
        if tool is None:
            self._draw_kind = None; self._pen_idx = None; self._stroke_selected = -1
        elif isinstance(tool, tuple) and tool and tool[0] == "pen":
            self._pen_idx = int(tool[1])
            if self._draw_kind not in ("line", "shape", "text"):
                self._draw_kind = "line"
        elif isinstance(tool, tuple) and tool and tool[0] == "erase":
            self._draw_kind = "erase"
            try:
                self._erase_k = self._draw_eraser_widths.index(int(tool[1]))
            except ValueError:
                self._erase_k = 0
        elif tool == ("select", None):
            self._draw_kind = "select"
        self._apply_tool()

    def _load_page_strokes(self):
        self._commit_text_editor()        # 260611-74: 페이지 전환 전 편집 커밋
        self._leader_drag = None
        f = self.current_file()
        if self._draw_resolver and f and not self._is_image:
            try:
                self._page_strokes = [dict(s) for s in
                                      (self._draw_resolver(str(f), self._current_page) or [])]
            except Exception:
                self._page_strokes = []
        else:
            self._page_strokes = []
        self._stroke_selected = -1; self._stroke_drag = None   # 260611-70: 페이지 전환 시 해제
        # 260611-80: 페이지가 바뀌면 되돌리기/다시실행 스택 초기화 + 기준 상태 갱신
        import copy
        self._undo_stack = []; self._redo_stack = []
        self._strokes_baseline = copy.deepcopy(self._page_strokes)
        self._update_undo_buttons()
        if self._draw_overlay is not None:
            self._draw_overlay.update()

    # ===== 260611-80: 되돌리기 / 다시실행 =====
    UNDO_LIMIT = 30

    def _save_page_strokes(self):
        if not self._restoring:           # undo/redo 복원 중에는 스냅샷 push 안 함
            self._push_undo_if_changed()
        f = self.current_file()
        if self._draw_setter and f and not self._is_image:
            try:
                self._draw_setter(str(f), self._current_page, list(self._page_strokes))
            except Exception:
                pass

    def _push_undo_if_changed(self):
        import copy
        base = self._strokes_baseline
        if base == self._page_strokes:    # 실제 변경 없으면 스텝 생성 안 함
            return
        self._undo_stack.append(base)
        if len(self._undo_stack) > self.UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._strokes_baseline = copy.deepcopy(self._page_strokes)
        self._update_undo_buttons()

    def can_undo(self):
        return bool(self._undo_stack)

    def can_redo(self):
        return bool(self._redo_stack)

    def undo_strokes(self):
        import copy
        if not self._undo_stack:
            return False
        self._commit_text_editor()
        self._redo_stack.append(copy.deepcopy(self._page_strokes))
        self._page_strokes = self._undo_stack.pop()
        self._strokes_baseline = copy.deepcopy(self._page_strokes)
        self._stroke_selected = -1; self._stroke_drag = None
        self._restoring = True
        try:
            self._save_page_strokes()
        finally:
            self._restoring = False
        self._update_undo_buttons()
        if self._draw_overlay is not None:
            self._draw_overlay.update()
        return True

    def redo_strokes(self):
        import copy
        if not self._redo_stack:
            return False
        self._commit_text_editor()
        self._undo_stack.append(copy.deepcopy(self._page_strokes))
        self._page_strokes = self._redo_stack.pop()
        self._strokes_baseline = copy.deepcopy(self._page_strokes)
        self._stroke_selected = -1; self._stroke_drag = None
        self._restoring = True
        try:
            self._save_page_strokes()
        finally:
            self._restoring = False
        self._update_undo_buttons()
        if self._draw_overlay is not None:
            self._draw_overlay.update()
        return True

    def _update_undo_buttons(self):
        if hasattr(self, "_undo_btn"):
            self._undo_btn.setEnabled(bool(self._undo_stack))
        if hasattr(self, "_redo_btn"):
            self._redo_btn.setEnabled(bool(self._redo_stack))

    def _erase_strokes_near(self, norm_pt):
        """260611-2: 선 '중간'도 지워지도록 점이 아닌 선분(세그먼트) 거리로 판정.

        지우개 반경(px)을 뷰 좌표 기준으로 두고, 각 스트로크를 뷰 px 로 환산해
        지우개 중심과 모든 세그먼트의 최소 거리가 반경 이하면 그 선을 제거한다.
        하이라이트 띠는 사각형 안에 들어오면 제거."""
        if not self._page_strokes:
            return
        pr = self._page_view_rect()
        if pr is None:
            return
        w = self._draw_tool[1] if (self._draw_tool and self._draw_tool[0] == "erase") else 16
        rad = max(3.0, float(w) / 2.0)
        ex = pr.left() + norm_pt[0] * pr.width()
        ey = pr.top() + norm_pt[1] * pr.height()

        def to_view(p):
            return (pr.left() + p[0] * pr.width(), pr.top() + p[1] * pr.height())

        def seg_dist(px, py, ax, ay, bx, by):
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            if L2 <= 1e-9:
                return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
            cx, cy = ax + t * dx, ay + t * dy
            return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

        def hit(st):
            # 260611-80: 도형/텍스트/지시선도 지우개로 삭제 — 회전 고려한 박스(원은 반지름) 판정
            if st.get("shape") or st.get("text_box") or st.get("leader"):
                if st.get("shape") == "circle":
                    c = to_view((st.get("cx", 0.5), st.get("cy", 0.5)))
                    r = float(st.get("r", 0.0)) * pr.width()
                    d = ((ex - c[0]) ** 2 + (ey - c[1]) ** 2) ** 0.5
                    return d <= r + rad
                cx, cy, hw, hh, rot = self._shape_geom(st, pr)
                lx, ly = self._img_v2l(cx, cy, rot, ex, ey)   # 지우개 중심을 박스 로컬좌표로
                return (-hw - rad <= lx <= hw + rad and -hh - rad <= ly <= hh + rad)
            pts = st.get("points", [])
            if len(pts) < 2:
                return False
            vp = [to_view(p) for p in pts]
            if st.get("hl"):
                # 띠 사각형: x[min..max], yc±h/2
                bh = float(st.get("h", 0.0)) * pr.height()
                (x0, yc) = vp[0]; (x1, _y) = vp[-1]
                left, right = min(x0, x1), max(x0, x1)
                top, bot = yc - bh / 2.0, yc + bh / 2.0
                return (left - rad <= ex <= right + rad
                        and top - rad <= ey <= bot + rad)
            for i in range(1, len(vp)):
                if seg_dist(ex, ey, vp[i - 1][0], vp[i - 1][1],
                            vp[i][0], vp[i][1]) <= rad:
                    return True
            return False

        keep = [st for st in self._page_strokes if not hit(st)]
        if len(keep) != len(self._page_strokes):
            self._page_strokes = keep

    def clear_page_drawings(self):
        if self._page_strokes:
            self._page_strokes = []
            self._save_page_strokes()
            if self._draw_overlay is not None:
                self._draw_overlay.update()

    # ===== 260611-15: 삽입 이미지(주석) =================================
    @staticmethod
    def _pix_to_b64(pix) -> str:
        import base64
        from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
        ba = QByteArray(); buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pix.save(buf, "PNG"); buf.close()
        return base64.b64encode(bytes(ba)).decode("ascii")

    @staticmethod
    def _b64_to_pix(s):
        import base64
        pm = QPixmap()
        try:
            pm.loadFromData(base64.b64decode(s), "PNG")
        except Exception:
            pass
        return pm

    def set_image_config(self, resolver, setter):
        self._img_resolver = resolver
        self._img_setter = setter
        self._load_page_images()

    def set_image_edit(self, on):
        self._img_edit = bool(on)
        if not on:
            self._img_selected = -1
        if self._draw_overlay is not None:
            self._draw_overlay.update()

    def set_image_shape(self, shape):
        """신규 삽입 기본 모양 + 선택된 개체에도 즉시 적용."""
        if shape in ("rect", "round", "circle"):
            self._img_shape = shape
            if 0 <= self._img_selected < len(self._img_objects):
                self._img_objects[self._img_selected]["shape"] = shape
                self._save_page_images()
                self._draw_overlay.update()

    # ===== 260611-70: 그린 선/도형 선택·이동(개체선택 도구) =====
    def _norm_to_view(self, fx, fy, pr):
        from PyQt6.QtCore import QPoint
        return QPoint(int(pr.left() + fx * pr.width()), int(pr.top() + fy * pr.height()))

    @staticmethod
    def _pt_seg_dist(px, py, a, b):
        ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        cx, cy = ax + t * dx, ay + t * dy
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    def _stroke_hit_index(self, pos, pr):
        """클릭 위치(뷰 좌표)에 닿는 스트로크 인덱스(위에 그린 것 우선). 없으면 -1."""
        import math
        px, py = pos.x(), pos.y(); TH = 7
        for i in range(len(self._page_strokes) - 1, -1, -1):
            st = self._page_strokes[i]
            w = int(st.get("width", 3))
            if st.get("text_box") or st.get("leader"):
                cx, cy, hw, hh, rot = self._shape_geom(st, pr)
                lx, ly = self._img_v2l(cx, cy, rot, px, py)
                if -hw - TH <= lx <= hw + TH and -hh - TH <= ly <= hh + TH:
                    return i
                continue
            if st.get("shape"):
                if st["shape"] == "circle":
                    c = self._norm_to_view(st.get("cx", 0.5), st.get("cy", 0.5), pr)
                    r = float(st.get("r", 0.0)) * pr.width()
                    d = math.hypot(px - c.x(), py - c.y())
                    if (st.get("fill", "none") != "none" and d <= r + TH) or abs(d - r) <= TH + w:
                        return i
                else:
                    rc = st.get("rect", [0, 0, 0, 0])
                    tl = self._norm_to_view(min(rc[0], rc[2]), min(rc[1], rc[3]), pr)
                    br = self._norm_to_view(max(rc[0], rc[2]), max(rc[1], rc[3]), pr)
                    x0, y0, x1, y1 = tl.x(), tl.y(), br.x(), br.y()
                    inside = (x0 - TH <= px <= x1 + TH and y0 - TH <= py <= y1 + TH)
                    if st.get("fill", "none") != "none":
                        if inside:
                            return i
                    elif inside and (abs(px - x0) <= TH + w or abs(px - x1) <= TH + w
                                     or abs(py - y0) <= TH + w or abs(py - y1) <= TH + w):
                        return i
            else:
                pts = st.get("points", [])
                if st.get("hl") and len(pts) >= 2:
                    (a0, yc), (a1, _y) = pts[0], pts[-1]
                    t = self._norm_to_view(min(a0, a1), yc, pr)
                    b2 = self._norm_to_view(max(a0, a1), yc, pr)
                    bh = float(st.get("h", 0.0)) * pr.height()
                    if (min(t.x(), b2.x()) - TH <= px <= max(t.x(), b2.x()) + TH
                            and abs(py - t.y()) <= bh / 2 + TH):
                        return i
                elif len(pts) >= 2:
                    vp = [self._norm_to_view(x, y, pr) for x, y in pts]
                    for k in range(1, len(vp)):
                        if self._pt_seg_dist(px, py, vp[k - 1], vp[k]) <= TH + w / 2.0:
                            return i
        return -1

    def _stroke_translate(self, idx, dnx, dny):
        if not (0 <= idx < len(self._page_strokes)):
            return
        st = self._page_strokes[idx]
        if st.get("shape") == "circle":
            st["cx"] = st.get("cx", 0.5) + dnx; st["cy"] = st.get("cy", 0.5) + dny
        elif st.get("shape") or st.get("text_box") or st.get("leader"):
            rc = st.get("rect", [0, 0, 0, 0])
            st["rect"] = [rc[0] + dnx, rc[1] + dny, rc[2] + dnx, rc[3] + dny]
            if st.get("leader") and st.get("anchor"):
                a = st["anchor"]; st["anchor"] = [a[0] + dnx, a[1] + dny]
        else:
            st["points"] = [[x + dnx, y + dny] for x, y in st.get("points", [])]

    def _stroke_delete_selected(self):
        if 0 <= self._stroke_selected < len(self._page_strokes):
            self._page_strokes.pop(self._stroke_selected)
            self._stroke_selected = -1
            self._save_page_strokes(); self._draw_overlay.update()
            return True
        return False

    # ===== 260611-72: 활성 도형 변형(크기/회전/이동) — 이미지 핸들과 동일 방식 =====
    def _selected_shape(self):
        i = self._stroke_selected
        if 0 <= i < len(self._page_strokes) and self._page_strokes[i].get("shape"):
            return self._page_strokes[i]
        return None

    def _shape_geom(self, st, pr):
        if st.get("shape") == "circle":
            cx = pr.left() + st.get("cx", 0.5) * pr.width()
            cy = pr.top() + st.get("cy", 0.5) * pr.height()
            r = st.get("r", 0.0) * pr.width()
            return cx, cy, r, r, 0.0
        rc = st.get("rect", [0, 0, 0, 0])
        x0, y0 = min(rc[0], rc[2]), min(rc[1], rc[3])
        x1, y1 = max(rc[0], rc[2]), max(rc[1], rc[3])
        cx = pr.left() + (x0 + x1) / 2.0 * pr.width()
        cy = pr.top() + (y0 + y1) / 2.0 * pr.height()
        hw = (x1 - x0) / 2.0 * pr.width(); hh = (y1 - y0) / 2.0 * pr.height()
        return cx, cy, hw, hh, float(st.get("rot", 0.0))

    def _shape_set_geom(self, st, cx, cy, hw, hh, rot, pr):
        if st.get("shape") == "circle":
            st["cx"] = (cx - pr.left()) / max(1, pr.width())
            st["cy"] = (cy - pr.top()) / max(1, pr.height())
            st["r"] = hw / max(1, pr.width())
        else:
            st["rect"] = [(cx - hw - pr.left()) / max(1, pr.width()),
                          (cy - hh - pr.top()) / max(1, pr.height()),
                          (cx + hw - pr.left()) / max(1, pr.width()),
                          (cy + hh - pr.top()) / max(1, pr.height())]
            st["rot"] = float(rot)

    def _shape_handle_points(self, st, pr):
        cx, cy, hw, hh, rot = self._shape_geom(st, pr)
        L = self._img_l2v
        return {"tl": L(cx, cy, rot, -hw, -hh), "tr": L(cx, cy, rot, hw, -hh),
                "bl": L(cx, cy, rot, -hw, hh), "br": L(cx, cy, rot, hw, hh),
                "t": L(cx, cy, rot, 0, -hh), "b": L(cx, cy, rot, 0, hh),
                "l": L(cx, cy, rot, -hw, 0), "r": L(cx, cy, rot, hw, 0),
                "rot": L(cx, cy, rot, 0, -hh - self.IMG_ROT_OFFSET)}

    def _selected_xform(self):
        """260611-74: 핸들 변형 대상(도형 + 텍스트 박스 + 지시선)을 통합 반환."""
        i = self._stroke_selected
        if 0 <= i < len(self._page_strokes):
            st = self._page_strokes[i]
            if st.get("shape") or st.get("text_box") or st.get("leader"):
                return st
        return None

    def _shape_handle_at(self, pos, pr):
        """선택된 도형/텍스트의 핸들 적중: 'rot'/'tl'..'br'/'t'..'r'/'move'/None."""
        st = self._selected_xform()
        if st is None:
            return None
        px, py = pos.x(), pos.y()
        hpts = self._shape_handle_points(st, pr)
        rp = hpts["rot"]
        if abs(px - rp.x()) <= 9 and abs(py - rp.y()) <= 9:
            return "rot"
        for name in ("tl", "tr", "bl", "br", "t", "b", "l", "r"):
            hp = hpts[name]
            if abs(px - hp.x()) <= 8 and abs(py - hp.y()) <= 8:
                return name
        cx, cy, hw, hh, rot = self._shape_geom(st, pr)
        lx, ly = self._img_v2l(cx, cy, rot, px, py)
        if -hw <= lx <= hw and -hh <= ly <= hh:
            return "move"
        return None

    def _shape_transform_press(self, pos, pr, handle):
        st = self._selected_xform()
        if st is None:
            return
        self._shape_drag = handle
        self._shape_press = pos
        self._shape_press_geom = self._shape_geom(st, pr)
        # 260611-79: 글자 크기 스케일의 '기준값'을 누름 시점에 고정(매 이동마다 곱해 폭증→크래시 방지)
        self._xform_size0 = float(st.get("size", 0.022))

    def _shape_transform_move(self, pos, pr, shift=False):
        import math
        st = self._selected_xform()
        if st is None or self._shape_drag is None:
            return
        cx0, cy0, hw0, hh0, rot0 = self._shape_press_geom
        drag = self._shape_drag
        if drag == "move":
            self._shape_set_geom(st, cx0 + (pos.x() - self._shape_press.x()),
                                 cy0 + (pos.y() - self._shape_press.y()), hw0, hh0, rot0, pr)
            self._draw_overlay.update(); return
        if drag == "rot":
            ang = (math.degrees(math.atan2(pos.y() - cy0, pos.x() - cx0)) + 90.0) % 360.0
            if not shift:
                near = round(ang / 90.0) * 90.0
                if abs(((ang - near + 180) % 360) - 180) <= self.IMG_SNAP_DEG:
                    ang = near % 360.0
            self._shape_set_geom(st, cx0, cy0, hw0, hh0, ang, pr)
            self._draw_overlay.update(); return
        mlx, mly = self._img_v2l(cx0, cy0, rot0, pos.x(), pos.y())
        left, right, top, bottom = -hw0, hw0, -hh0, hh0
        if "l" in drag: left = mlx
        if "r" in drag: right = mlx
        if "t" in drag: top = mly
        if "b" in drag: bottom = mly
        nw = max(self.IMG_MIN_PX, right - left); nh = max(self.IMG_MIN_PX, bottom - top)
        if st.get("shape") == "circle":
            nw = nh = max(nw, nh)
        nhw, nhh = nw / 2.0, nh / 2.0
        ax = 1 if "l" in drag else (-1 if "r" in drag else 0)
        ay = 1 if "t" in drag else (-1 if "b" in drag else 0)
        a = math.radians(rot0); ca = math.cos(a); sa = math.sin(a)
        ox, oy = ax * hw0, ay * hh0
        anchor_x = cx0 + ox * ca - oy * sa; anchor_y = cy0 + ox * sa + oy * ca
        nx, ny = ax * nhw, ay * nhh
        c1x = anchor_x - (nx * ca - ny * sa); c1y = anchor_y - (nx * sa + ny * ca)
        self._shape_set_geom(st, c1x, c1y, nhw, nhh, rot0, pr)
        # 260611-79: 텍스트/지시선 박스 크기 조절 시 글자 크기도 세로 비율로 스케일.
        #   기준=누름 시점 크기(_xform_size0)로 계산(누적 곱 금지) + 범위 클램프(폭증·크래시 방지).
        if (st.get("text_box") or st.get("leader")) and hh0 > 1.0 and ay != 0:
            s0 = getattr(self, "_xform_size0", float(st.get("size", 0.022)))
            st["size"] = max(0.004, min(0.5, s0 * (nhh / hh0)))
        self._draw_overlay.update()

    # ===== 260611-74(Phase2): 글쓰기 텍스트 박스 + 지시선 엔진 =====
    def _view_to_norm(self, pos, pr):
        return [max(0.0, min(1.0, (pos.x() - pr.left()) / max(1, pr.width()))),
                max(0.0, min(1.0, (pos.y() - pr.top()) / max(1, pr.height())))]

    def _selected_textbox(self):
        i = self._stroke_selected
        if 0 <= i < len(self._page_strokes):
            st = self._page_strokes[i]
            if st.get("text_box") or st.get("leader"):
                return st
        return None

    def _active_pen(self):
        """260611-76: 현재 선택된 색상버튼의 스타일(색·굵기·투명도). 없으면 1번 펜."""
        pens = self._draw_pens or MV_DEFAULT_PENS
        idx = self._pen_idx if self._pen_idx is not None else 0
        idx = max(0, min(len(pens) - 1, int(idx)))
        return pens[idx]

    def _new_style_fields(self, name=None):
        """프리셋(글꼴 성격) → 글자색·크기·굵기·배경. 테두리/선은 색상버튼에서 별도."""
        s = MV_TEXT_STYLE_MAP.get(name or self._text_style, MV_TEXT_STYLE_MAP["본문"])
        return {"family": "맑은 고딕", "size": float(s["size"]), "color": s["color"],
                "bold": bool(s["bold"]), "italic": bool(s.get("italic", False)),
                "bg": s["bg"], "bg_alpha": 100,
                "box_line": s["border"] is not None, "style": name or self._text_style}

    def _pen_style_fields(self):
        """260611-76: 박스선/지시선의 색·굵기·투명도 = 선택된 색상버튼 스타일."""
        pen = self._active_pen()
        return {"border_color": pen.get("color", "#ff3030"),
                "border_w": int(pen.get("width", 3)),
                "border_alpha": int(pen.get("alpha", 100)),
                "line_color": pen.get("color", "#ff3030"),
                "line_w": max(1, int(pen.get("width", 2))),
                "line_alpha": int(pen.get("alpha", 100))}

    def _apply_text_style(self, st, name):
        """프리셋만 갱신(글자색·크기·배경·박스선 on/off). 테두리/선 스타일은 유지."""
        st.update(self._new_style_fields(name))

    def _new_text_box(self, fnorm):
        st = {"text_box": True, "text": "", "rot": 0.0, "style": self._text_style}
        st.update(self._text_defaults)
        st.update(self._pen_style_fields())
        st["rect"] = [fnorm[0], fnorm[1], fnorm[0] + 0.12, fnorm[1] + 0.04]
        self._page_strokes.append(st)
        return len(self._page_strokes) - 1

    def _new_leader(self, box_anchor, tip_anchor, hl_rects=None):
        """260611-76/77: box_anchor=글 시작점(=박스 하단-좌측), tip_anchor=화살표 끝,
        hl_rects=지시선이 가리키는(드래그로 지나간) 문자 하이라이트 정규화 사각형들."""
        bx, by = box_anchor
        st = {"leader": True, "text": "", "rot": 0.0, "style": self._text_style}
        st.update(self._leader_defaults)
        st.update(self._pen_style_fields())
        st["rect"] = [bx, by - 0.04, bx + 0.12, by]
        st["box_anchor"] = [bx, by]
        st["anchor"] = [tip_anchor[0], tip_anchor[1]]
        st["hl_rects"] = list(hl_rects or [])
        self._page_strokes.append(st)
        return len(self._page_strokes) - 1

    def _text_qfont(self, st, pr):
        from PyQt6.QtGui import QFont
        # 260611-79: 글자 픽셀 크기 상한(폰트엔진 폭주/크래시 방지)
        px = max(7, min(800, int(round(float(st.get("size", 0.022)) * pr.height()))))
        f = QFont(st.get("family", "맑은 고딕"))
        f.setPixelSize(px)
        f.setBold(bool(st.get("bold", False)))
        f.setItalic(bool(st.get("italic", False)))
        return f

    def _textbox_hit_index(self, pos, pr):
        """텍스트/지시선 박스 본문 적중 인덱스(위에 그린 것 우선). 없으면 -1."""
        px, py = pos.x(), pos.y()
        for i in range(len(self._page_strokes) - 1, -1, -1):
            st = self._page_strokes[i]
            if not (st.get("text_box") or st.get("leader")):
                continue
            cx, cy, hw, hh, rot = self._shape_geom(st, pr)
            lx, ly = self._img_v2l(cx, cy, rot, px, py)
            if -hw - 4 <= lx <= hw + 4 and -hh - 4 <= ly <= hh + 4:
                return i
        return -1

    # ---- 인라인 편집기(QTextEdit, auto-grow) ----
    def _begin_text_edit(self, idx, pr):
        from PyQt6.QtWidgets import QTextEdit
        from PyQt6.QtGui import QColor
        if not (0 <= idx < len(self._page_strokes)):
            return
        self._commit_text_editor()
        st = self._page_strokes[idx]
        # self.view 의 자식(오버레이와 동일) — 오버레이 위에 표시되도록 raise
        ed = QTextEdit(self.view)
        ed.setAcceptRichText(False)
        ed.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ed.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ed.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        ed.setFont(self._text_qfont(st, pr))
        c = QColor(st.get("color", "#111111"))
        bg = st.get("bg")
        ed.setStyleSheet(
            "QTextEdit{color:%s;background:%s;border:1px dashed #ff7a00;padding:2px;}"
            % (c.name(), (QColor(bg).name() if bg else "rgba(255,255,255,0.85)")))
        ed.setPlainText(st.get("text", ""))
        ed.installEventFilter(self)
        ed.textChanged.connect(self._on_text_changed)
        self._text_editor = ed
        self._text_edit_idx = idx
        self._text_edit_page = self._current_page   # 커밋 시 이 페이지로 저장
        self._text_edit_file = self.current_file()
        self._position_text_editor()
        ed.show(); ed.raise_(); ed.setFocus()
        cur = ed.textCursor(); cur.movePosition(cur.MoveOperation.End)
        ed.setTextCursor(cur)
        if self._draw_overlay is not None:
            self._draw_overlay.update()

    def _on_text_changed(self):
        """입력에 따라 박스를 오른쪽·아래로 auto-grow(정규화 rect 갱신)."""
        ed = self._text_editor
        idx = self._text_edit_idx
        if ed is None or not (0 <= idx < len(self._page_strokes)):
            return
        pr = self._page_view_rect()
        if pr is None:
            return
        st = self._page_strokes[idx]
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(ed.font())
        lines = ed.toPlainText().split("\n") or [""]
        tw = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
        th = fm.lineSpacing() * max(1, len(lines))
        pad = 8
        wv = tw + pad * 2 + 4
        hv = th + pad
        fw = wv / max(1, pr.width()); fh = hv / max(1, pr.height())
        if st.get("leader") and st.get("box_anchor"):
            # 지시선: 시작점(글 시작)=박스 하단-좌측 고정 → 위로·오른쪽으로 늘어남
            bx, by = st["box_anchor"]
            st["rect"] = [bx, by - fh, bx + fw, by]
        else:
            rc = st.get("rect", [0, 0, 0.1, 0.05])
            x0 = min(rc[0], rc[2]); y0 = min(rc[1], rc[3])
            st["rect"] = [x0, y0, x0 + fw, y0 + fh]
        st["text"] = ed.toPlainText()
        self._position_text_editor()
        if self._draw_overlay is not None:
            self._draw_overlay.update()

    def _position_text_editor(self):
        ed = self._text_editor
        idx = self._text_edit_idx
        if ed is None or not (0 <= idx < len(self._page_strokes)):
            return
        pr = self._page_view_rect()
        if pr is None:
            return
        st = self._page_strokes[idx]
        rc = st.get("rect", [0, 0, 0.1, 0.05])
        x0 = pr.left() + min(rc[0], rc[2]) * pr.width()
        y0 = pr.top() + min(rc[1], rc[3]) * pr.height()
        w = abs(rc[2] - rc[0]) * pr.width(); h = abs(rc[3] - rc[1]) * pr.height()
        # 오버레이(self.view 자식)와 같은 좌표계로 보정: pr 은 뷰포트 좌표 = 오버레이 로컬
        ox = self._draw_overlay.x() if self._draw_overlay is not None else 0
        oy = self._draw_overlay.y() if self._draw_overlay is not None else 0
        ed.setGeometry(int(ox + x0), int(oy + y0), max(40, int(w)), max(24, int(h)))

    def _commit_text_editor(self):
        ed = getattr(self, "_text_editor", None)
        if ed is None:
            return
        idx = self._text_edit_idx
        txt = ed.toPlainText()
        self._text_editor = None
        self._text_edit_idx = -1
        try:
            ed.removeEventFilter(self)
        except Exception:
            pass
        ed.hide(); ed.deleteLater()
        if 0 <= idx < len(self._page_strokes):
            st = self._page_strokes[idx]
            if txt.strip() == "":
                self._page_strokes.pop(idx)
                if self._stroke_selected == idx:
                    self._stroke_selected = -1
                elif self._stroke_selected > idx:
                    self._stroke_selected -= 1
            else:
                st["text"] = txt
            # 편집을 시작한 그 페이지/파일로 저장(페이지 이동 중 커밋되어도 안전)
            ef = getattr(self, "_text_edit_file", None)
            ep = getattr(self, "_text_edit_page", self._current_page)
            if ef is not None and ep == self._current_page and ef == self.current_file():
                self._save_page_strokes()
            elif self._draw_setter and ef is not None and not self._is_image:
                try:
                    self._draw_setter(str(ef), ep, list(self._page_strokes))
                except Exception:
                    pass
        if self._draw_overlay is not None:
            self._draw_overlay.update()

    def _page_words_norm(self):
        """260611-77: 현재 페이지 단어 bbox 목록(정규화). 지시선 하이라이트 적중용."""
        out = []
        try:
            if not self._doc or self._is_image:
                return out
            page = self._doc.doc.load_page(self._current_page)
            pw, ph = page.rect.width, page.rect.height
            if pw <= 0 or ph <= 0:
                return out
            for w in page.get_text("words"):
                out.append([w[0] / pw, w[1] / ph, w[2] / pw, w[3] / ph])
        except Exception:
            pass
        return out

    def _collect_word(self, ld, pos, pr):
        """커서가 지나간 단어를 ld['hl'] 에 누적(중복 제외)."""
        fx, fy = self._view_to_norm(pos, pr)
        for r in ld.get("words", []):
            if r[0] <= fx <= r[2] and r[1] <= fy <= r[3]:
                if r not in ld["hl"]:
                    ld["hl"].append(list(r))
                break

    def _text_event(self, t, ev, pr):
        """글쓰기 모드 마우스 라우터. True/False=소비, None=통과."""
        if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
            pos = ev.position().toPoint()
            # 지시선 float(선이 포인터 따라다님) 중 목표 누름 = 끝점 확정 + 하이라이트 수집 시작
            ld = self._leader_drag
            if (self._text_kind == "leader" and ld is not None
                    and ld.get("phase") == "float"):
                ld["phase"] = "aim"
                ld["endpoint"] = pos
                ld["endpoint_n"] = self._view_to_norm(pos, pr)
                ld["cur"] = pos
                ld["words"] = self._page_words_norm()
                ld["hl"] = []
                self._collect_word(ld, pos, pr)
                if self._draw_overlay is not None:
                    self._draw_overlay.update()
                return True
            try:
                self.activated.emit()
            except Exception:
                pass
            # 1) 활성 텍스트/지시선 박스의 핸들 → 변형(이동/크기/회전)
            if self._selected_textbox() is not None:
                h = self._shape_handle_at(pos, pr)
                if h is not None:
                    self._shape_transform_press(pos, pr, h)
                    self.view.setFocus(); return True
            # 2) 기존 박스 본문 클릭 → 편집
            hi = self._textbox_hit_index(pos, pr)
            if hi >= 0:
                self._stroke_selected = hi
                self._begin_text_edit(hi, pr); return True
            # 3) 빈 곳 — 색상버튼(스타일)이 있어야 작성 가능
            self._img_selected = -1
            if self._pen_idx is None:
                return True       # 색상 미선택 → 작성 안 함(패닝/그리기도 안 함)
            if self._text_kind == "leader":
                # 시작점 누름 = 박스 하단(글 시작) + 선 시작
                self._leader_drag = {"origin": self._view_to_norm(pos, pr),
                                     "cur": pos, "phase": "drag", "moved": False}
                if self._draw_overlay is not None:
                    self._draw_overlay.update()
                return True
            # 글쓰기(일반): 클릭 위치=박스 좌상단, 즉시 편집
            idx = self._new_text_box(self._view_to_norm(pos, pr))
            self._stroke_selected = idx
            self._begin_text_edit(idx, pr); return True
        if t == QEvent.Type.MouseMove:
            held = bool(ev.buttons() & Qt.MouseButton.LeftButton)
            if self._shape_drag is not None and held:
                self._shape_transform_move(
                    ev.position().toPoint(), pr,
                    bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                return True
            ld = self._leader_drag
            if ld is not None:
                ph = ld.get("phase")
                if ph == "aim":
                    # 끝점 고정, 누른 채 글 위 이동 = 지나간 문자 하이라이트 누적
                    ld["cur"] = ev.position().toPoint()
                    if held:
                        self._collect_word(ld, ld["cur"], pr)
                    if self._draw_overlay is not None:
                        self._draw_overlay.update()
                    return True
                if ph == "float" or held:
                    ld["cur"] = ev.position().toPoint()
                    if held and ph == "drag":
                        o = self._norm_to_view(ld["origin"][0], ld["origin"][1], pr)
                        if abs(ld["cur"].x() - o.x()) + abs(ld["cur"].y() - o.y()) > 5:
                            ld["moved"] = True
                    if self._draw_overlay is not None:
                        self._draw_overlay.update()
                    return True
            return None
        if t == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
            if self._shape_drag is not None:
                self._shape_drag = None; self._save_page_strokes(); return True
            ld = self._leader_drag
            if ld is not None:
                ph = ld.get("phase")
                if ph == "drag" and not ld.get("moved"):
                    # 시작점만 클릭(드래그 안 함) → 선이 포인터를 따라다니는 모드로 전환
                    ld["phase"] = "float"; ld["cur"] = ev.position().toPoint()
                    if self._draw_overlay is not None:
                        self._draw_overlay.update()
                    return True
                if ph == "aim":
                    # 끝점 = aim 누른 지점, 하이라이트 = 누적분
                    origin = ld["origin"]; anchor = ld["endpoint_n"]; hl = ld.get("hl", [])
                else:
                    # drag 끌어서 놓음 → 끝점 = 놓은 지점
                    origin = ld["origin"]
                    anchor = self._view_to_norm(ev.position().toPoint(), pr); hl = []
                self._leader_drag = None
                idx = self._new_leader(origin, anchor, hl)
                self._stroke_selected = idx
                self._begin_text_edit(idx, pr); return True
            return None
        return None

    def set_textbox_style(self, idx, **fields):
        """우클릭 스타일 대화상자에서 호출 — 선택 텍스트/지시선 박스 속성 갱신."""
        if 0 <= idx < len(self._page_strokes):
            st = self._page_strokes[idx]
            for k, v in fields.items():
                st[k] = v
            self._save_page_strokes()
            if self._draw_overlay is not None:
                self._draw_overlay.update()

    # ---- 공개 보조(앱 우클릭 메뉴/스타일 대화상자용) ----
    def has_selected_textbox(self):
        return self._selected_textbox() is not None

    def selected_text_index(self):
        return self._stroke_selected if self._selected_textbox() is not None else -1

    def selected_text_stroke(self):
        st = self._selected_textbox()
        return dict(st) if st is not None else None

    def set_leader_tip(self, tip):
        st = self._selected_textbox()
        if st is not None and st.get("leader") and tip in MV_LEADER_TIPS:
            st["tip"] = tip
            self._save_page_strokes()
            if self._draw_overlay is not None:
                self._draw_overlay.update()

    def delete_selected_stroke(self):
        return self._stroke_delete_selected()

    def _load_page_images(self):
        self._img_objects = []
        self._img_selected = -1
        f = self.current_file()
        if self._img_resolver and f and not self._is_image:
            try:
                for d in (self._img_resolver(str(f), self._current_page) or []):
                    pix = self._b64_to_pix(d.get("data", ""))
                    if pix.isNull():
                        continue
                    self._img_objects.append({
                        "pix": pix, "data": d.get("data", ""),
                        "rect": list(d.get("rect", [0.1, 0.1, 0.3, 0.3])),
                        "shape": d.get("shape", "rect"),
                        "alpha": int(d.get("alpha", 100)),
                        "rot": float(d.get("rot", 0.0))})
            except Exception:
                pass
        if self._draw_overlay is not None:
            self._draw_overlay.update()

    def _save_page_images(self):
        f = self.current_file()
        if self._img_setter and f and not self._is_image:
            out = [{"data": o["data"], "rect": [round(v, 5) for v in o["rect"]],
                    "shape": o["shape"], "alpha": int(o["alpha"]),
                    "rot": round(float(o.get("rot", 0.0)), 2)}
                   for o in self._img_objects]
            try:
                self._img_setter(str(f), self._current_page, out)
            except Exception:
                pass

    def add_image_from_pixmap(self, pix, shape=None):
        """클립보드/파일/드롭 이미지를 현재 페이지에 삽입(중앙, 비율 유지)."""
        if pix is None or pix.isNull() or self._is_image or self._doc is None:
            return
        # 너무 큰 이미지는 축소(JSON 비대화 방지)
        if pix.width() > 1200 or pix.height() > 1200:
            pix = pix.scaled(1200, 1200, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        pr = self._page_view_rect()
        fw = 0.35
        if (pr and pr.width() > 0 and pr.height() > 0 and pix.width() > 0):
            fh = fw * (pix.height() / pix.width()) * (pr.width() / pr.height())
        else:
            fh = 0.35
        fh = max(0.05, min(0.9, fh)); fw = max(0.05, min(0.9, fw))
        obj = {"pix": pix, "data": self._pix_to_b64(pix),
               "rect": [0.5 - fw / 2, 0.5 - fh / 2, fw, fh],
               "shape": shape or self._img_shape, "alpha": 100, "rot": 0.0}
        self._img_objects.append(obj)
        self._img_selected = len(self._img_objects) - 1
        self._save_page_images()
        if self._draw_overlay is not None:
            self._draw_overlay.update()
        try:
            self.activated.emit()
        except Exception:
            pass

    # ===== 260611-18: 회전 가능한 개체 기하 =====
    def _img_geom(self, obj, pr):
        """개체 중심(view px)·반폭·반높이(view px)·회전(deg)."""
        fx, fy, fw, fh = obj.get("rect", [0.1, 0.1, 0.3, 0.3])
        cx = pr.left() + (fx + fw / 2.0) * pr.width()
        cy = pr.top() + (fy + fh / 2.0) * pr.height()
        hw = fw * pr.width() / 2.0
        hh = fh * pr.height() / 2.0
        return cx, cy, hw, hh, float(obj.get("rot", 0.0))

    def _img_l2v(self, cx, cy, rot, lx, ly):
        """로컬(회전 전, 중심 기준) → view 좌표."""
        import math
        from PyQt6.QtCore import QPointF
        a = math.radians(rot); ca = math.cos(a); sa = math.sin(a)
        return QPointF(cx + lx * ca - ly * sa, cy + lx * sa + ly * ca)

    def _img_v2l(self, cx, cy, rot, px, py):
        """view → 로컬(회전 전) 좌표."""
        import math
        a = math.radians(rot); ca = math.cos(a); sa = math.sin(a)
        dx = px - cx; dy = py - cy
        return (dx * ca + dy * sa, -dx * sa + dy * ca)

    def _img_handle_points(self, obj, pr):
        """8개 크기 핸들 + 회전 핸들 'rot'(모두 view 좌표, 회전 반영)."""
        cx, cy, hw, hh, rot = self._img_geom(obj, pr)
        L = self._img_l2v
        return {
            "tl": L(cx, cy, rot, -hw, -hh), "tr": L(cx, cy, rot, hw, -hh),
            "bl": L(cx, cy, rot, -hw, hh), "br": L(cx, cy, rot, hw, hh),
            "t": L(cx, cy, rot, 0, -hh), "b": L(cx, cy, rot, 0, hh),
            "l": L(cx, cy, rot, -hw, 0), "r": L(cx, cy, rot, hw, 0),
            "rot": L(cx, cy, rot, 0, -hh - self.IMG_ROT_OFFSET),
        }

    def _img_hit(self, pos, pr):
        """(idx, handle) — 위 개체 우선. handle: None/'move'/'rot'/'tl'..'br'/'t'..'r'."""
        px, py = pos.x(), pos.y()
        sel = self._img_selected
        if 0 <= sel < len(self._img_objects):
            hpts = self._img_handle_points(self._img_objects[sel], pr)
            rp = hpts["rot"]
            if abs(px - rp.x()) <= 9 and abs(py - rp.y()) <= 9:
                return sel, "rot"
            for name in ("tl", "tr", "bl", "br", "t", "b", "l", "r"):
                hp = hpts[name]
                if abs(px - hp.x()) <= 8 and abs(py - hp.y()) <= 8:
                    return sel, name
        for idx in range(len(self._img_objects) - 1, -1, -1):
            cx, cy, hw, hh, rot = self._img_geom(self._img_objects[idx], pr)
            lx, ly = self._img_v2l(cx, cy, rot, px, py)
            if -hw <= lx <= hw and -hh <= ly <= hh:
                return idx, "move"
        return -1, None

    def _img_mouse_press(self, pos, pr):
        idx, handle = self._img_hit(pos, pr)
        if idx < 0:
            if self._img_selected != -1:
                self._img_selected = -1
                self._draw_overlay.update()
            return False
        self._img_selected = idx
        self._img_drag = handle
        self._img_press = pos
        self._img_press_rect = list(self._img_objects[idx]["rect"])
        self._img_press_geom = self._img_geom(self._img_objects[idx], pr)
        self._draw_overlay.update()
        return True

    def _img_mouse_move(self, pos, pr, shift=False):
        """이동/크기/회전. 모서리=비율고정(Shift=해제), 변=한 방향만, 'rot'=회전+90도 스냅."""
        import math
        if self._img_drag is None or not (0 <= self._img_selected < len(self._img_objects)):
            return
        obj = self._img_objects[self._img_selected]
        drag = self._img_drag
        cx0, cy0, hw0, hh0, rot0 = (self._img_press_geom or self._img_geom(obj, pr))

        if drag == "move":
            dx = (pos.x() - self._img_press.x()) / max(1, pr.width())
            dy = (pos.y() - self._img_press.y()) / max(1, pr.height())
            fx, fy, fw, fh = self._img_press_rect
            obj["rect"] = [fx + dx, fy + dy, fw, fh]
            self._draw_overlay.update()
            return

        if drag == "rot":
            ang = math.degrees(math.atan2(pos.y() - cy0, pos.x() - cx0)) + 90.0
            ang %= 360.0
            if not shift:                       # 90도 인근에서 자석 스냅
                near = round(ang / 90.0) * 90.0
                if abs(((ang - near + 180) % 360) - 180) <= self.IMG_SNAP_DEG:
                    ang = near % 360.0
            obj["rot"] = ang
            self._draw_overlay.update()
            return

        # ----- 크기 조절(로컬 좌표) -----
        mlx, mly = self._img_v2l(cx0, cy0, rot0, pos.x(), pos.y())
        left, right, top, bottom = -hw0, hw0, -hh0, hh0
        if "l" in drag:
            left = mlx
        if "r" in drag:
            right = mlx
        if "t" in drag:
            top = mly
        if "b" in drag:
            bottom = mly
        nw = max(self.IMG_MIN_PX, right - left)
        nh = max(self.IMG_MIN_PX, bottom - top)
        is_corner = drag in ("tl", "tr", "bl", "br")
        if is_corner and not shift:             # 비율 고정(원본 비율 유지)
            bw, bh = 2 * hw0, 2 * hh0
            rw = nw / bw if bw else 1.0
            rh = nh / bh if bh else 1.0
            s = rw if abs(rw - 1) >= abs(rh - 1) else rh
            s = max(s, self.IMG_MIN_PX / max(bw, bh, 1.0))
            nw, nh = bw * s, bh * s
        nhw, nhh = nw / 2.0, nh / 2.0
        # 고정(앵커) = 드래그하지 않은 반대편. 그 view 위치를 유지하며 새 중심 산출.
        ax = 1 if "l" in drag else (-1 if "r" in drag else 0)
        ay = 1 if "t" in drag else (-1 if "b" in drag else 0)
        a = math.radians(rot0); ca = math.cos(a); sa = math.sin(a)
        # 앵커의 원래 view 위치
        ox, oy = ax * hw0, ay * hh0
        anchor_x = cx0 + ox * ca - oy * sa
        anchor_y = cy0 + ox * sa + oy * ca
        # 새 로컬 앵커를 같은 view 위치에 맞추는 중심
        nx, ny = ax * nhw, ay * nhh
        rvx = nx * ca - ny * sa
        rvy = nx * sa + ny * ca
        c1x = anchor_x - rvx
        c1y = anchor_y - rvy
        fw = nw / max(1, pr.width())
        fh = nh / max(1, pr.height())
        fx = (c1x - pr.left()) / max(1, pr.width()) - fw / 2.0
        fy = (c1y - pr.top()) / max(1, pr.height()) - fh / 2.0
        obj["rect"] = [fx, fy, fw, fh]
        self._draw_overlay.update()

    def _img_mouse_release(self):
        if self._img_drag is not None:
            self._img_drag = None
            self._save_page_images()

    def _img_nudge(self, dx_px, dy_px):
        if not (0 <= self._img_selected < len(self._img_objects)):
            return False
        pr = self._page_view_rect()
        if pr is None:
            return False
        r = self._img_objects[self._img_selected]["rect"]
        r[0] += dx_px / max(1, pr.width())
        r[1] += dy_px / max(1, pr.height())
        self._save_page_images()
        self._draw_overlay.update()
        return True

    def _img_opacity(self, delta):
        if not (0 <= self._img_selected < len(self._img_objects)):
            return False
        o = self._img_objects[self._img_selected]
        o["alpha"] = max(10, min(100, int(o["alpha"]) + delta))
        self._save_page_images()
        self._draw_overlay.update()
        return True

    def _img_delete_selected(self):
        if 0 <= self._img_selected < len(self._img_objects):
            del self._img_objects[self._img_selected]
            self._img_selected = -1
            self._save_page_images()
            self._draw_overlay.update()
            return True
        return False

    def has_selected_image(self):
        return 0 <= self._img_selected < len(self._img_objects)

    def paste_image_from_clipboard(self):
        """260611-15: 클립보드 이미지를 현재 페이지에 삽입(Ctrl+V)."""
        if not self._img_edit:
            return False
        from PyQt6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        img = cb.image()
        if img is not None and not img.isNull():
            self.add_image_from_pixmap(QPixmap.fromImage(img))
            return True
        pm = cb.pixmap()
        if pm is not None and not pm.isNull():
            self.add_image_from_pixmap(pm)
            return True
        return False

    def add_image_from_file(self, path):
        """260611-15: 파일/드롭 이미지 삽입."""
        if not self._img_edit:
            return False
        pm = QPixmap(str(path))
        if pm.isNull():
            return False
        self.add_image_from_pixmap(pm)
        return True

    def _position_draw_overlay(self):
        ov = self._draw_overlay
        if ov is None:
            return
        # 260611-2: 오버레이를 뷰포트 영역에 정확히 겹쳐 배치(오버레이 로컬좌표=뷰포트 좌표)
        ov.setGeometry(self.view.viewport().geometry())
        ov.raise_()
        ov.update()

    def eventFilter(self, obj, ev):
        """260611-1: 선긋기 도구 활성 시 뷰포트 마우스를 가로채 오버레이로 전달.

        QGraphicsView(ScrollHandDrag) 뷰포트 위 자식 위젯의 직접 마우스 캡처가
        불안정해, 발표 모드처럼 입력을 뷰포트에서 받아 오버레이 핸들러에 넘긴다.
        도구가 없으면 통과(기존 패닝/호버 유지)."""
        try:
            ov = self._draw_overlay
            # 260611-74: 인라인 텍스트 편집기 — Esc/포커스아웃=커밋, Enter=줄바꿈(통과)
            if self._text_editor is not None and obj is self._text_editor:
                tt = ev.type()
                if tt == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
                    self._commit_text_editor(); return True
                if tt == QEvent.Type.FocusOut:
                    self._commit_text_editor(); return True
                return super().eventFilter(obj, ev)
            if ov is None or obj is not self.view.viewport():
                return super().eventFilter(obj, ev)
            t = ev.type()
            tool = self._draw_tool
            is_pen_erase = (tool is not None and tool[0] in ("pen", "erase"))
            is_select = (tool == ("select", None))

            # ===== 260611-16: 삽입 이미지 조작이 항상 우선 =====
            #   - 개체/핸들을 잡으면 선 작업을 무시하고 이미지 작업(요청1)
            #   - 활성 개체가 있는데 빈 곳을 누르면 '개체 비활성화'만(이 클릭으로 그리기 안 함)(요청1·3)
            #   - 개체선택 도구일 땐 빈 곳=패닝 허용, 그리기 없음(요청4)
            if self._img_edit and not self._is_image:
                pr = self._page_view_rect()
                if pr is not None:
                    # 260611-74: 글쓰기/지시선 모드 — 텍스트 작성·변형이 최우선
                    if self._draw_kind == "text":
                        r = self._text_event(t, ev, pr)
                        if r is not None:
                            return r
                    if t == QEvent.Type.MouseButtonPress \
                            and ev.button() == Qt.MouseButton.LeftButton:
                        pos = ev.position().toPoint()
                        try:
                            self.activated.emit()
                        except Exception:
                            pass
                        idx, _h = self._img_hit(pos, pr)
                        if idx >= 0:
                            self._img_mouse_press(pos, pr)   # 선택 + 이동/리사이즈 시작
                            self.view.setFocus()
                            return True                       # 이미지 우선 → 소비
                        # 빈 곳
                        if self._img_selected != -1:
                            self._img_selected = -1; ov.repaint()  # 260611-79: 즉시 갱신
                            return True                            # 이 클릭은 그리기 안 함
                        if is_select:
                            # 260611-70: 그린 선/도형을 클릭하면 선택+이동 시작
                            si = self._stroke_hit_index(pos, pr)
                            if si >= 0:
                                self._stroke_selected = si
                                self._stroke_drag = {"last": pos}
                                self.view.setFocus(); ov.repaint()  # 260611-79: 선택 즉시 표시
                                return True
                            if self._stroke_selected != -1:
                                self._stroke_selected = -1; ov.repaint()
                            return False                           # 빈 곳: 패닝 허용
                        # 개체 없음 + 펜/지우개면 아래 드로잉으로 진행
                    elif t == QEvent.Type.MouseMove \
                            and (ev.buttons() & Qt.MouseButton.LeftButton) \
                            and self._img_drag is not None:
                        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                        self._img_mouse_move(ev.position().toPoint(), pr, shift)
                        return True
                    elif t == QEvent.Type.MouseButtonRelease \
                            and ev.button() == Qt.MouseButton.LeftButton \
                            and self._img_drag is not None:
                        self._img_mouse_release()
                        return True
                    # 260611-70: 선택된 선/도형 이동
                    elif t == QEvent.Type.MouseMove \
                            and (ev.buttons() & Qt.MouseButton.LeftButton) \
                            and self._stroke_drag is not None:
                        cur = ev.position().toPoint(); last = self._stroke_drag["last"]
                        self._stroke_translate(
                            self._stroke_selected,
                            (cur.x() - last.x()) / max(1.0, pr.width()),
                            (cur.y() - last.y()) / max(1.0, pr.height()))
                        self._stroke_drag["last"] = cur; ov.update()
                        return True
                    elif t == QEvent.Type.MouseButtonRelease \
                            and ev.button() == Qt.MouseButton.LeftButton \
                            and self._stroke_drag is not None:
                        self._stroke_drag = None; self._save_page_strokes()
                        return True
                    elif t == QEvent.Type.MouseMove \
                            and not (ev.buttons() & Qt.MouseButton.LeftButton):
                        # 호버: 핸들/개체 위 커서 모양 변경(요청2)
                        self._img_update_hover_cursor(ev.position().toPoint(), pr)
                        # 소비하지 않음 — 펜 호버(지우개 원 등)도 계속

            # ===== 선긋기 라우팅(펜/지우개 도구일 때만) =====
            if is_pen_erase:
                pr2 = self._page_view_rect()
                if (t == QEvent.Type.MouseButtonPress
                        and ev.button() == Qt.MouseButton.LeftButton):
                    try:
                        self.activated.emit()
                    except Exception:
                        pass
                    # 260611-72: 도형 모드에서 활성 도형의 핸들/본체를 누르면 변형(드로잉 대신)
                    if (self._draw_kind == "shape" and pr2 is not None
                            and self._selected_shape() is not None):
                        h = self._shape_handle_at(ev.position().toPoint(), pr2)
                        if h is not None:
                            self._shape_transform_press(ev.position().toPoint(), pr2, h)
                            self.view.setFocus(); return True
                        self._stroke_selected = -1; ov.update()   # 빈 곳 → 해제(새 도형)
                    ov.mousePressEvent(ev)
                    return True
                if t == QEvent.Type.MouseMove:
                    held = bool(ev.buttons() & Qt.MouseButton.LeftButton)
                    is_erase = tool[0] == "erase"
                    if self._shape_drag is not None and held and pr2 is not None:
                        self._shape_transform_move(
                            ev.position().toPoint(), pr2,
                            bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                        return True
                    if held or is_erase:
                        ov.mouseMoveEvent(ev)
                        return True if (held or is_erase) else False
                if (t == QEvent.Type.MouseButtonRelease
                        and ev.button() == Qt.MouseButton.LeftButton):
                    if self._shape_drag is not None:
                        self._shape_drag = None; self._save_page_strokes()
                        return True
                    ov.mouseReleaseEvent(ev)
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, ev)

    def _img_update_hover_cursor(self, pos, pr):
        """260611-16/18: 모서리=대각, 변=가로/세로, 회전핸들=십자, 개체 위=이동 커서."""
        vp = self.view.viewport()
        idx, handle = self._img_hit(pos, pr)
        if handle == "rot":
            vp.setCursor(Qt.CursorShape.CrossCursor)
        elif handle in ("tl", "br"):
            vp.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif handle in ("tr", "bl"):
            vp.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif handle in ("l", "r"):
            vp.setCursor(Qt.CursorShape.SizeHorCursor)
        elif handle in ("t", "b"):
            vp.setCursor(Qt.CursorShape.SizeVerCursor)
        elif handle == "move":
            vp.setCursor(Qt.CursorShape.SizeAllCursor)
        elif self._draw_tool == ("select", None):
            vp.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            vp.unsetCursor()

    def _update_hidden_band(self):
        band = getattr(self, "_hidden_band", None)
        if band is None:
            return
        hidden = (not self._is_image) and (self._current_page in self._hidden_pages)
        band.setVisible(hidden)
        if hidden:
            pr = self._page_view_rect()
            if pr is None:
                band.hide(); return
            bw = 20
            band.setGeometry(pr.right() - bw, pr.top(), bw, pr.height())
            band.raise_()

    def set_hyperlinks(self, links):
        """260609-11(C8): 현재 페이지의 하이퍼링크 버튼 갱신(페이지 안·가운데·줄바꿈)."""
        self._hl_links = list(links or [])
        self._relayout_hl()

    def _page_view_rect(self):
        """렌더된 페이지의 뷰포트 좌표 사각형(없으면 None)."""
        it = getattr(self, "_page_item", None)
        if it is None:
            return None
        try:
            poly = self.view.mapFromScene(it.sceneBoundingRect())
            return poly.boundingRect()
        except Exception:
            return None

    def _make_hl_button(self, ln):
        from PyQt6.QtWidgets import QPushButton as _QPB
        name = str(ln.get("name", "")) or "링크"
        tag = _hyperlink_icon(ln)
        btn = _QPB(f"{tag} {name}", self._hl_overlay)
        btn.setToolTip(str(ln.get("target", "")))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton{background:rgba(21,101,192,0.92);color:white;"
            "border:none;border-radius:5px;padding:3px 9px;font-weight:bold;}"
            "QPushButton:hover{background:rgba(25,118,210,1.0);}")
        btn.clicked.connect(lambda _=False, l=ln: self.hyperlinkActivated.emit(l))
        return btn

    def _relayout_hl(self):
        """버튼들을 페이지 폭에 맞춰 가운데 정렬·줄바꿈으로 재배치하고 위치시킴."""
        ov = getattr(self, "_hl_overlay", None)
        if ov is None:
            return
        from PyQt6.QtWidgets import QHBoxLayout as _QHB, QWidget as _QW
        vlay = ov.layout()
        # 기존 행/버튼 제거
        while vlay.count():
            it = vlay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._hl_buttons = []

        pr = self._page_view_rect()
        if not self._hl_links or pr is None or pr.width() <= 0:
            ov.hide()
            return
        avail = max(80, pr.width() - 8)
        # 버튼 생성 후 폭 측정 → 행으로 패킹(가운데 정렬)
        spacing = 6
        rows = [[]]
        cur_w = 0
        for ln in self._hl_links:
            b = self._make_hl_button(ln)
            b.adjustSize()
            bw = b.sizeHint().width()
            if rows[-1] and cur_w + spacing + bw > avail:
                rows.append([])
                cur_w = 0
            rows[-1].append(b)
            cur_w += (spacing if cur_w else 0) + bw
            self._hl_buttons.append(b)
        for row in rows:
            rw = _QW(ov)
            hl = _QHB(rw)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(spacing)
            hl.addStretch(1)
            for b in row:
                b.setParent(rw)
                hl.addWidget(b)
            hl.addStretch(1)
            vlay.addWidget(rw)

        ov.setFixedWidth(pr.width())
        ov.adjustSize()
        ov.move(pr.left(), pr.top() + self._hl_top_offset)
        ov.show()
        ov.raise_()

    def _position_hl_overlay(self):
        # 페이지 위치/크기 변동 시 재배치(폭 변하면 줄바꿈도 갱신)
        self._relayout_hl()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_empty_label()            # 260606-30: 빈 창 안내 중앙 유지
        self._position_hl_overlay()           # 260609-3: 하이퍼링크 오버레이 우상단 유지
        self._position_draw_overlay()         # 260609-22(J3): 선긋기 오버레이
        # v1.6.0 P3: 즉시 렌더 → 150ms 디바운스. 연속 resize 시 CPU 절약
        if self._doc and self._fit_mode in (self.FIT_PAGE, self.FIT_PAGE_TWO, self.FIT_WIDTH):
            self._resize_debounce.start()
        elif self._is_image:                  # v1.6.9 G1: 이미지 fit 갱신
            self._apply_image_fit()

    # --- 매치 ------------------------------------------------------------
    def _page_local_match_index(self) -> int:
        if self._current_match < 0:
            return -1
        idx = self._current_match
        for hit in self._matches:
            if hit.page_index == self._current_page:
                count = len(hit.rects)
                if idx < count:
                    return idx
                idx -= count
            else:
                idx -= len(hit.rects)
                if idx < 0:
                    return -1
        return -1

    def _first_global_match_index(self, page_index: int) -> int:
        """260616-4: 주어진 페이지의 첫 매치에 해당하는 전역 매치 인덱스(없으면 -1)."""
        idx = 0
        for hit in self._matches:
            if hit.page_index == page_index:
                return idx
            idx += len(hit.rects)
        return -1

    def _scroll_to_current_match(self):
        """260616-4: 재렌더 없이 현재 매치로 중앙 스크롤(선긋기·삽입이미지 보존).
        go_to_page 직후 호출 — scene 을 건드리지 않고 view 만 스크롤한다."""
        li = self._page_local_match_index()
        if li < 0 or not (self._doc and self._query):
            return
        try:
            page_obj = self._doc.doc.load_page(self._current_page)
            rects = page_obj.search_for(self._query)
            if not rects or li >= len(rects):
                return
            r = self._disp_search_rect(page_obj, rects[li])   # /Rotate 보정
            cx = (r.x0 + r.x1) / 2 * self._zoom
            cy = (r.y0 + r.y1) / 2 * self._zoom
            self.view.centerOn(cx, cy)
        except Exception:
            pass

    def jump_to_search_result(self, page_index: int, query: str):
        """260616-4: 이미 열린 같은 문서에서 재오픈 없이 결과 페이지·매치로 이동.
        검색어가 같으면 매치 재계산도 생략(속도 개선)."""
        if not self._doc:
            return
        if (query or "") != self._query:
            self._query = query or ""
            self._matches = self._doc.search(self._query) if self._query else []
            self._current_match = 0 if self._matches else -1
        if self._matches:
            gi = self._first_global_match_index(page_index)
            if gi >= 0:
                self._current_match = gi
        self.go_to_page(page_index)
        if self._matches and self._current_match >= 0:
            self._scroll_to_current_match()

    def _jump_to_match(self, match_idx: int):
        idx = match_idx
        for hit in self._matches:
            if idx < len(hit.rects):
                target_page = hit.page_index
                rect = hit.rects[idx]
                if target_page != self._current_page:
                    self._current_page = target_page
                self._render_current()
                # 260611-99: 회전 PDF(/Rotate) 보정 후 중심 계산
                try:
                    rect = self._disp_search_rect(
                        self._doc.doc.load_page(target_page), rect)
                except Exception:
                    pass
                # zoom 은 _zoom (PDF pt → 논리 px). 좌표도 같은 배율로.
                center_x = (rect.x0 + rect.x1) / 2 * self._zoom
                center_y = (rect.y0 + rect.y1) / 2 * self._zoom
                self.view.centerOn(center_x, center_y)
                self.spin_page.blockSignals(True)
                self.spin_page.setValue(target_page + 1)
                self.spin_page.blockSignals(False)
                self.pageChanged.emit(target_page)
                self._update_match_counter()
                return
            idx -= len(hit.rects)

    def _update_match_counter(self):
        total = sum(len(h.rects) for h in self._matches)
        cur = self._current_match + 1 if self._current_match >= 0 else 0
        self.matchPositionChanged.emit(cur, total)
