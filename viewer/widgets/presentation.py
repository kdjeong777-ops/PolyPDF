"""260609-4 (D, Phase 1): 발표용 전체화면 보기 창 — 핵심.

- 쪽맞춤 전체화면, 검은 배경.
- 다음/이전: 마우스 좌클릭·→/Space/PageDown / ←/PageUp.
- 숫자패드(또는 숫자키)로 페이지 입력 후 Enter → 현재 파일의 해당 페이지로.
- ESC 또는 우클릭 '전체화면 보기 취소' → 닫기.

향후 단계(설계 여지): 사용자 포인터(2초 숨김), 상하 2분할(겹침), 파일경계
오버레이, 상단 호버 띠 + 하이퍼링크 버튼.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QEvent, QSize
from PyQt6.QtGui import (QImage, QPixmap, QPainter, QColor, QCursor, QPen,
                         QPalette, QTransform, QIcon)
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QMenu, QLineEdit

from viewer.pdf_doc import PdfDocument
from viewer.resources_path import resource_path
from viewer.widgets.main_view import smooth_polyline_path   # 260611-83: 자유곡선 부드럽게

# 260609-5: 발표 포인터 기본 프리셋(설정에서 이름/색/테두리 수정 가능)
DEFAULT_POINTERS = [
    {"name": "사용자 포인터 1", "fill": "#ff3030", "border": "#ffffff"},
    {"name": "사용자 포인터 2", "fill": "#3060ff", "border": "#ffffff"},
    {"name": "사용자 포인터 3", "fill": "#ffffff", "border": "#202020"},
]
POINTER_HIDE_MS = 2000          # 2초 무동작 시 포인터 숨김

# 260609-16(F3): 발표 펜(드래그 그리기) 기본 프리셋·단축키
DEFAULT_PENS = [
    {"name": "사용자선 1", "color": "#ff3030", "width": 3, "alpha": 100},
    {"name": "사용자선 2", "color": "#30a0ff", "width": 4, "alpha": 100},
    {"name": "사용자선 3", "color": "#ffd400", "width": 14, "alpha": 40},
]
DEFAULT_PEN_KEYS = ["Ctrl+1", "Ctrl+2", "Ctrl+3"]
DEFAULT_REC_KEYS = ["Ctrl+R", "Ctrl+Shift+R"]   # [녹화/재개, 중지]


class _PresThumbPanel(QWidget):
    """260609-24(I5): 발표 좌측 슬라이드 썸네일 패널(호버 표시, 폭 조절, 문고리 없음)."""

    pageSelected = pyqtSignal(int)

    def __init__(self, owner):
        super().__init__(owner)
        from PyQt6.QtWidgets import QHBoxLayout, QListWidget
        self._owner = owner
        self._width = 180
        self._aspect = 1.3          # 260611-97: 썸네일 세로/가로 비(페이지에서 계산)
        # 260611-98: 패널 배경 짙은 회색(스타일 배경이 실제로 칠해지도록 WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background:#2b2b2b;")
        # 260611-6: 슬라이드 패널 안에서는 일반(화살표) 포인터로 — 발표 커스텀/숨김 포인터가
        #   패널 위에서 안 보이던 문제 해소(자식 위젯 커서가 창 커서를 덮어씀)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 4, 0, 4); h.setSpacing(0)
        self.list = QListWidget()
        self.list.setCursor(Qt.CursorShape.ArrowCursor)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        # 260611-98: 아이콘 모드 = 썸네일 위 + 페이지번호 아래(한 줄). 단일 세로열.
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setFlow(QListWidget.Flow.TopToBottom)
        self.list.setWrapping(False)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setWordWrap(False)
        self.list.setSpacing(3)
        self.list.setUniformItemSizes(True)
        # 260611-98: 리스트 배경도 짙은 회색(투명이면 발표 화면이 비쳐 보임)
        self.list.setStyleSheet(
            "QListWidget{background:#2b2b2b;border:none;color:#ddd;}"
            "QListWidget::item{color:#ddd;}"
            "QListWidget::item:selected{background:rgba(21,101,192,0.6);}")
        self.list.itemClicked.connect(self._on_click)
        self.list.verticalScrollBar().valueChanged.connect(
            lambda _=0: self._render_visible())
        h.addWidget(self.list, 1)
        # 우측 폭 조절 그립(문고리 아님)
        self._grip = QWidget(); self._grip.setFixedWidth(6)
        self._grip.setCursor(Qt.CursorShape.SizeHorCursor)
        self._grip.setStyleSheet("background:rgba(255,255,255,0.18);")
        self._grip.installEventFilter(self)
        h.addWidget(self._grip)
        self._drag = None
        self.hide()

    def eventFilter(self, obj, ev):
        if obj is self._grip:
            if ev.type() == QEvent.Type.MouseButtonPress:
                self._drag = ev.globalPosition().toPoint().x()
                self._drag_w0 = self._width
                return True
            if ev.type() == QEvent.Type.MouseMove and self._drag is not None:
                dx = ev.globalPosition().toPoint().x() - self._drag
                self._set_width(self._drag_w0 + dx)
                return True
            if ev.type() == QEvent.Type.MouseButtonRelease:
                self._drag = None
                self._render_visible()
                return True
        return super().eventFilter(obj, ev)

    def _set_width(self, w):
        self._width = max(110, min(420, int(w)))
        self.setFixedWidth(self._width)
        self.setGeometry(0, 0, self._width, self._owner.height())
        iw = self._width - 18
        # 260611-97/98: 항목 높이를 실제 페이지 비율에 맞춰 — 가로(landscape) 슬라이드일 때
        #   고정 세로비(1.3)로 인한 위/아래 빈 공간(과도한 간격) 제거. +18 = 페이지번호 줄.
        ih = max(1, int(iw * self._aspect))
        cell = QSize(iw + 10, ih + 18)            # 아이콘모드 셀(썸네일 위 + 번호 아래)
        self.list.setIconSize(QSize(iw, ih))
        self.list.setGridSize(cell)
        for i in range(self.list.count()):
            self.list.item(i).setSizeHint(cell)

    def populate(self):
        self.list.clear()
        doc = self._owner._doc
        if doc is None:
            return
        hidden = set()
        try:
            if self._owner._hidden_resolver:
                hidden = self._owner._hidden_resolver(str(self._owner._path)) or set()
        except Exception:
            hidden = set()
        from PyQt6.QtWidgets import QListWidgetItem
        first = None
        for p in range(doc.page_count):
            if p in hidden:
                continue
            if first is None:
                first = p
            it = QListWidgetItem(f"{p + 1}")
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            self.list.addItem(it)
        # 260611-97: 첫 페이지 비율로 항목 높이 결정(가로/세로 슬라이드 모두 알맞게)
        if first is not None:
            try:
                rp = doc.render_thumbnail(int(first), dpi=24)
                if rp.width > 0:
                    self._aspect = max(0.2, min(3.0, rp.height / rp.width))
            except Exception:
                pass
        self._set_width(self._width)
        self._render_visible()

    def _render_visible(self):
        doc = self._owner._doc
        if doc is None:
            return
        vp = self.list.viewport().rect()
        iw = self.list.iconSize().width()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if not self.list.visualItemRect(it).intersects(vp):
                continue
            if not it.icon().isNull():
                continue
            p = it.data(Qt.ItemDataRole.UserRole)
            try:
                rp = doc.render_thumbnail(int(p), dpi=46)
                img = QImage(rp.samples, rp.width, rp.height, rp.width * 3,
                             QImage.Format.Format_RGB888)
                pm = QPixmap.fromImage(img).scaledToWidth(
                    iw, Qt.TransformationMode.SmoothTransformation)
                it.setIcon(QIcon(pm))
            except Exception:
                pass

    def _on_click(self, it):
        p = it.data(Qt.ItemDataRole.UserRole)
        if p is not None:
            self.pageSelected.emit(int(p))

    def slide_in(self):
        self.setGeometry(0, 0, self._width, self._owner.height())
        if self.list.count() == 0:
            self.populate()
        self.show(); self.raise_()
        self._select_current_page()        # 260618-2: 현재 페이지 썸네일이 보이도록
        self._render_visible()

    def _select_current_page(self):
        """260618-2: 현재 페이지 항목을 선택·중앙으로 스크롤(전체화면 썸네일 열 때)."""
        from PyQt6.QtWidgets import QAbstractItemView
        cur = getattr(self._owner, "_page", 0)
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == cur:
                self.list.setCurrentItem(it)
                self.list.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)
                break

    def slide_out(self):
        if self.isVisible():
            self.hide()


class _PageLineEdit(QLineEdit):
    """260609-19(H1·H2): 페이지 콤보 입력창 — 중앙 클릭도 풀다운, 좌/우 키 페이지 이동."""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            # 릴리스 시 표시 → 같은 클릭의 릴리스로 즉시 닫히는 문제 회피
            self._owner._tb_page.showPopup()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Left:
            self._owner._prev(); return
        if k == Qt.Key.Key_Right:
            self._owner._next(); return
        super().keyPressEvent(e)


class _DrawOverlay(QWidget):
    """발표 펜 그리기를 표시하는 투명 오버레이(마우스 이벤트는 통과)."""

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        strokes = list(self._owner._strokes.get(self._owner._page, []))
        if self._owner._cur_stroke is not None:
            strokes = strokes + [self._owner._cur_stroke]
        hl_op = int(getattr(self._owner, "_highlight_alpha", 35))
        # 260611-7: 상하2분할이면 '현재 보는 반쪽'에 그린 선만 표시(다른 반쪽엔 숨김)
        split = self._owner._page_is_split()
        cur_half = self._owner._split_half
        from PyQt6.QtCore import QRect as _QRect
        from PyQt6.QtCore import QPoint as _QPoint
        vis = [st for st in strokes
               if not (split and st.get("half", 0) != cur_half)
               and len(st.get("points", [])) >= 2]

        def _band(painter, st, color):
            hh = float(st.get("h", 0.0)); pts = st["points"]
            p0, p1 = pts[0], pts[-1]; yc = p0.y()
            top = _QPoint(min(p0.x(), p1.x()), int(yc - hh / 2.0))
            bot = _QPoint(max(p0.x(), p1.x()), int(yc + hh / 2.0))
            painter.fillRect(_QRect(top, bot).normalized(), color)

        def _line(painter, st, color):
            pen = QPen(color); pen.setWidth(int(st.get("width", 3)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(smooth_polyline_path(st["points"]))   # 260611-83: 부드러운 곡선

        # 260611-83: 투명 펜·하이라이트는 (색,투명도)별 레이어에 불투명으로 모아 1회 합성
        #   → 겹쳐도 누적(진해짐)되지 않아 밑 내용이 끝까지 보임(편집모드와 동일).
        flat = {}
        for st in vis:
            if st.get("hl"):
                flat.setdefault((st.get("color", "#ffd400"), max(1, min(99, hl_op))), []).append(("band", st))
            elif int(st.get("alpha", 100)) < 100:
                flat.setdefault((st.get("color", "#ff3030"), max(1, min(99, int(st.get("alpha", 100))))), []).append(("line", st))
        if flat:
            dpr = self.devicePixelRatioF() or 1.0
            for (chex, a), items in flat.items():
                layer = QImage(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)),
                               QImage.Format.Format_ARGB32_Premultiplied)
                layer.setDevicePixelRatio(dpr); layer.fill(0)
                lp = QPainter(layer); lp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                oc = QColor(chex); oc.setAlpha(255)
                for kind, st in items:
                    (_band if kind == "band" else _line)(lp, st, oc)
                lp.end()
                p.setOpacity(max(0.05, min(1.0, a / 100.0)))
                p.drawImage(0, 0, layer); p.setOpacity(1.0)
        # 불투명 선은 그 위에 부드럽게
        for st in vis:
            if st.get("hl") or int(st.get("alpha", 100)) < 100:
                continue
            col = QColor(st.get("color", "#ff3030")); col.setAlpha(255)
            _line(p, st, col)
        # 260611-19: 발표시간(준비내용 박스 / 시각 HUD) — 선 위에 표시
        try:
            self._owner._paint_timer(p)
        except Exception:
            pass
        p.end()

# 260609-10: 발표 우클릭 메뉴 가독성(전체화면 검은 배경에서도 보이게)
_MENU_CSS = (
    "QMenu{background:#2b2b2e;color:#f0f0f0;border:1px solid #555;}"
    "QMenu::item{padding:6px 26px 6px 20px;}"
    "QMenu::item:selected{background:#1565c0;color:#ffffff;}"
    "QMenu::separator{height:1px;background:#555;margin:4px 8px;}"
)


class PresentationWindow(QWidget):
    """현재 PDF를 전체화면으로 발표. Phase 1 = 핵심 탐색."""

    closed = pyqtSignal(int)        # 닫힐 때 현재 페이지(0-based) 전달 → 메인 동기화
    pointerChanged = pyqtSignal(int)            # 260609-5: 활성 포인터 인덱스 변경
    pointerSettingsRequested = pyqtSignal()     # 260609-5: '포인터 설정…'
    splitModeChanged = pyqtSignal(bool)         # 260609-6: 상하 2분할 토글
    hyperlinkActivated = pyqtSignal(object)     # 260609-8: 상단 띠 하이퍼링크 클릭(link dict)
    linkPlayRequested = pyqtSignal()            # 260611-85: '링크실행'(페이지 미디어 순차 재생)
    cropSettingsRequested = pyqtSignal()        # 260609-14: '크롭 설정…'
    penChanged = pyqtSignal(int)                # 260609-16(F3): 활성 펜 변경
    penSettingsRequested = pyqtSignal()         # 260609-16(F3): '선 설정…'
    recordToggleRequested = pyqtSignal()        # 260609-17(F4): ● 녹화/재개
    recordPauseRequested = pyqtSignal()         # 260609-17(F4): ‖ 일시정지
    recordStopRequested = pyqtSignal()          # 260609-17(F4): ■ 중지
    penStraightChanged = pyqtSignal(bool)       # 260609-18(G3): 옆으로 직선만 토글(호환)
    lineModeChanged = pyqtSignal(int)           # 260611-4: 선 종류 0=직선/1=하이라이트/2=자유
    applyDrawingsRequested = pyqtSignal(object, str)  # 260609-25(I4): (정규화 strokes{page:[..]}, file)
    timerConfigChanged = pyqtSignal(object)     # 260611-19: 발표시간 설정 변경(cfg dict)
    fileChanged = pyqtSignal(str)               # 260611-23: 발표 중 파일 전환(새 파일 경로)
    viewSettingsRequested = pyqtSignal()        # 260611-25: '보기 설정…'(상단띠+크롭)
    overlapChanged = pyqtSignal(int)            # 260611-26: 중앙겹침(%) 변경(메뉴 입력박스)

    def __init__(self, file_path, page0: int = 0, parent=None,
                 pointers=None, pointer_active: int = 0,
                 split_mode: bool = False, overlap_pct: int = 10,
                 sibling_resolver=None, hyperlink_resolver=None,
                 topbar_h: int = 64, bookmark_resolver=None,
                 crop_resolver=None, hidden_resolver=None, rotation_resolver=None,
                 pens=None, pen_active: int = 0, pen_keys=None, rec_keys=None,
                 pen_straight: bool = True, eraser_widths=None,
                 line_mode: int = 0, highlight_alpha: int = 35, timer_cfg=None):
        super().__init__(parent)
        self._doc = PdfDocument(str(file_path))
        self._path = Path(str(file_path))
        self._page = max(0, min(self._doc.page_count - 1, int(page0)))
        self._numbuf = ""
        # 260609-5: 포인터
        self._pointers = list(pointers) if pointers else list(DEFAULT_POINTERS)
        self._ptr_active = max(0, min(len(self._pointers) - 1, int(pointer_active)))
        self._ptr_hidden = False
        self._ptr_timer = QTimer(self)
        self._ptr_timer.setSingleShot(True)
        self._ptr_timer.setInterval(POINTER_HIDE_MS)
        self._ptr_timer.timeout.connect(self._hide_pointer)
        # 260609-6: 상하 2분할(세로 긴 페이지 가독성) — 상/하 + 중앙 겹침
        self._split_mode = bool(split_mode)
        self._split_half = 0                  # 0=상부, 1=하부
        self._overlap_frac = max(0.0, min(0.4, float(overlap_pct) / 100.0))
        # 260609-7: 파일 경계 50% 오버레이(다음/이전 파일 미리보기 → 재선택 시 전환)
        self._sibling_resolver = sibling_resolver
        self._armed = 0                       # 0=없음, +1=다음 파일, -1=이전 파일
        self._armed_path = None
        # 260609-8/12: 상단 호버 띠(이동 버튼 + 페이지 편집 + 하이퍼링크)
        self._hyperlink_resolver = hyperlink_resolver
        self._bookmark_resolver = bookmark_resolver
        self._hl_buttons = []
        self._topbar_h = max(40, int(topbar_h))   # D1: 띠 높이(설정)
        self._suppress_combo = False              # 페이지 콤보 시그널 가드
        self._autoshown_page = -1                 # D3: 자동표시한 페이지(중복 방지)
        self._autohide_timer = QTimer(self)       # D3: 링크 페이지 2초 후 자동 숨김
        self._autohide_timer.setSingleShot(True)
        self._autohide_timer.setInterval(2000)
        self._autohide_timer.timeout.connect(self._hide_topbar)
        # 260609-14: 크롭(D4)·숨김(D5)
        self._crop_resolver = crop_resolver
        self._hidden_resolver = hidden_resolver
        self._rotation_resolver = rotation_resolver
        # 260609-16(F3): 펜(드래그 그리기) — 사용자선 1~3
        self._pens = list(pens) if pens else list(DEFAULT_PENS)
        self._pen_active = max(0, min(len(self._pens) - 1, int(pen_active)))
        self._pen_keys = list(pen_keys) if pen_keys else list(DEFAULT_PEN_KEYS)
        self._rec_keys = list(rec_keys) if rec_keys else list(DEFAULT_REC_KEYS)
        self._strokes = {}            # {page0: [stroke]}, stroke={color,width,alpha,points}
        self._cur_stroke = None
        self._press_pos = None
        self._drag_moved = False
        # 260611-4: 본문과 동일한 3단계 선 종류(0=직선 1=하이라이트 2=자유곡선)
        #   line_mode 미지정 시 기존 pen_straight 로 폴백(True→직선, False→자유).
        self._line_mode = int(line_mode) % 3 if line_mode else (0 if pen_straight else 2)
        self._pen_straight = (self._line_mode == 0)   # 호환 유지(직선 여부)
        # 260609-20(I3): 도구 — 'pen'(그리기) / 'erase'(일부분 지우기)
        self._tool = "pen"
        ew = list(eraser_widths) if eraser_widths else [12, 30]
        self._eraser_widths = [int(x) for x in ew][:2] or [12, 30]
        self._erase_active = 0
        self._erase_width = self._eraser_widths[0]
        self._erasing = False
        self._highlight_alpha = int(highlight_alpha or 35)   # 260611-2: 공유 하이라이트 불투명도(%)
        self._apply_on_exit = False       # 260609-25(I4): 종료 시 본화면/PDF 적용 확인
        # 260611-19: 발표시간(프레젠테이션 타이머)
        from viewer.widgets.pres_timer import (PresTimerController, ToneEngine,
                                               merge_timer_cfg)
        self._timer_cfg = merge_timer_cfg(timer_cfg)
        self._timer_ctl = PresTimerController(self._timer_cfg)
        self._tone = ToneEngine()
        self._timer_qtimer = QTimer(self)
        self._timer_qtimer.setInterval(200)
        self._timer_qtimer.timeout.connect(self._timer_tick)
        self._timer_hidden = False        # 시계 숨기기(작동은 유지, 표시만 숨김)
        self._alarm_muted = False         # 전체 알람 끄기(설정 유지, 소리만 차단)
        # 시작 페이지가 숨김이면 보이는 페이지로 이동
        if self._is_hidden(self._page):
            vp = self._visible_step(self._page, +1)
            if vp is None:
                vp = self._visible_step(self._page, -1)
            if vp is not None:
                self._page = vp
        # 260611-26: 상하 2분할 기본값 = 페이지 가로>세로(가로 페이지)일 때만 ON.
        self._split_mode = self._orient_split_default()
        # 260615-2: ⑦ 화면 채움(비율 변경) / ⑧ 표시 모니터 선택
        self._fill_screen = False           # True=비율 무시하고 화면 꽉 채움(늘림)
        self._target_screen = None          # 표시할 QScreen(None=기본/현재)

        # 260609-9: 부모가 있어도 독립 최상위 창이어야 showFullScreen 이 동작.
        #           (부모 위젯의 자식이면 전체화면이 뜨지 않음)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle(f"발표 — {self._path.name}")
        # 260609-10: 배경을 stylesheet 대신 팔레트로 — stylesheet 가 QMenu 까지
        #            전파되어 우클릭 메뉴가 검은 배경·검은 글씨로 안 보이던 문제 방지.
        self.setAutoFillBackground(True)
        _pal = self.palette()
        _pal.setColor(QPalette.ColorRole.Window, QColor("#000000"))
        self.setPalette(_pal)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background:#000;")
        # 260609-10: 라벨이 마우스 이벤트를 가로채면 창의 mouseMoveEvent 가 안 와
        #            포인터 자동숨김 복귀·상단 띠 표시가 동작하지 않음 → 클릭 통과.
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label.setMouseTracking(True)
        lay.addWidget(self._label, 1)

        # 페이지 입력 안내(숫자 입력 중 표시)
        self._hint = QLabel(self)
        self._hint.setStyleSheet(
            "background:rgba(0,0,0,0.6);color:#fff;font-size:28px;"
            "padding:8px 16px;border-radius:8px;")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._hint.hide()

        self._build_topbar()
        # 260609-16(F3): 그리기 오버레이(투명, 마우스 통과 → 창이 드래그 수신)
        #   z-순서: 라벨 < 그리기 오버레이 < 상단 띠 < 힌트
        self._draw_overlay = _DrawOverlay(self)
        self._draw_overlay.setGeometry(0, 0, max(1, self.width()), max(1, self.height()))
        self._draw_overlay.show()
        # 260609-24(I5): 좌측 슬라이드 썸네일 패널
        self._thumb_panel = _PresThumbPanel(self)
        self._thumb_panel.pageSelected.connect(self._on_thumb_panel_select)
        self._topbar.raise_()
        self._hint.raise_()
        # 260611-7: 툴바 버튼·썸네일 리스트가 키보드 포커스를 가져가면 방향키가
        #   페이지 이동 대신 위젯 탐색에 쓰여 '방향키 이동'이 안 먹힌다.
        #   → 버튼/리스트를 NoFocus 로 두어 창이 항상 방향키를 받게 함.
        self._apply_nav_focus()

    def _apply_nav_focus(self):
        from PyQt6.QtWidgets import QPushButton, QListWidget
        try:
            for w in self.findChildren(QPushButton):
                w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            for w in self.findChildren(QListWidget):
                w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        except Exception:
            pass

    def _on_thumb_panel_select(self, page0):
        self._go(int(page0))
        self.setFocus()                # 260611-7: 썸네일 클릭 후에도 방향키가 창으로

    # --- 260609-8/12/15: 상단 띠 ---
    def _build_topbar(self):
        from PyQt6.QtWidgets import (QPushButton, QHBoxLayout, QVBoxLayout,
                                     QComboBox)
        self._topbar = QWidget(self)
        self._topbar.setStyleSheet("QWidget#tb{background:rgba(20,20,24,0.88);}")
        self._topbar.setObjectName("tb")
        self._topbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._topbar.setCursor(Qt.CursorShape.ArrowCursor)   # D1: 일반 포인터
        outer = QVBoxLayout(self._topbar)
        outer.setContentsMargins(12, 6, 12, 6)
        outer.setSpacing(4)

        nav_css = ("QPushButton{background:rgba(255,255,255,0.12);color:#fff;"
                   "border:none;border-radius:6px;padding:4px 14px;font-size:16px;"
                   "font-weight:bold;}QPushButton:hover{background:rgba(255,255,255,0.25);}")
        # 1행: [좌측 약간 띄움][❮ 콤보 ❯ (좌측정렬, 최대 1/3폭)]  …  [✕ 닫기(전체모드 종료)]
        row1 = QHBoxLayout(); row1.setSpacing(8)
        self._tb_navwrap = QWidget()
        nh = QHBoxLayout(self._tb_navwrap)
        nh.setContentsMargins(0, 0, 0, 0); nh.setSpacing(6)
        self._tb_prev = QPushButton("❮"); self._tb_prev.setStyleSheet(nav_css)
        self._tb_prev.clicked.connect(self._prev)
        self._tb_page = QComboBox()
        self._tb_page.setEditable(True)
        self._tb_page.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._tb_page.setMinimumWidth(160)
        _bf = self.font(); _bf.setPointSizeF(self.font().pointSizeF() * 1.5); _bf.setBold(True)
        self._tb_page.setFont(_bf)               # D3: 현재 페이지 1.5배
        self._tb_page.setStyleSheet(
            "QComboBox{background:rgba(255,255,255,0.14);color:#fff;border:none;"
            "border-radius:6px;padding:2px 8px;}"
            "QComboBox QAbstractItemView{background:#2b2b2e;color:#fff;"
            "selection-background-color:#1565c0;}")
        # H1·H2: 커스텀 입력창(중앙 클릭→풀다운, 좌/우 키→페이지 이동)
        self._tb_page.setLineEdit(_PageLineEdit(self))
        self._tb_page.activated.connect(self._on_page_combo_activated)
        self._tb_page.lineEdit().returnPressed.connect(self._on_page_combo_enter)
        # G5: 메뉴 2초 이탈 시 숨김
        self._combo_leave_timer = QTimer(self)
        self._combo_leave_timer.setSingleShot(True)
        self._combo_leave_timer.setInterval(2000)
        self._combo_leave_timer.timeout.connect(self._tb_page.hidePopup)
        self._tb_page.view().installEventFilter(self)
        self._tb_page.view().viewport().installEventFilter(self)
        self._tb_next = QPushButton("❯"); self._tb_next.setStyleSheet(nav_css)
        self._tb_next.clicked.connect(self._next)
        nh.addWidget(self._tb_prev); nh.addWidget(self._tb_page, 1); nh.addWidget(self._tb_next)
        row1.addSpacing(8)                       # 좌측에서 약간 띄움
        row1.addWidget(self._tb_navwrap)
        row1.addStretch(1)
        # 260609-16(F3): 펜(선) 선택 버튼 3종
        self._tb_pen_btns = []
        for i in range(len(self._pens)):
            pb = QPushButton(str(i + 1))
            pb.setFixedWidth(34)
            pb.setCursor(Qt.CursorShape.PointingHandCursor)
            pb.clicked.connect(lambda _=False, k=i: self._set_pen(k))
            row1.addWidget(pb)
            self._tb_pen_btns.append(pb)
        # 260611-4: 선 종류 3단계 순환 버튼(직선 ─ / 하이라이트 ▬ / 자유 〜) — 본문과 동일
        self._tb_mode = QPushButton(self._MODE_GLYPH[self._line_mode])
        self._tb_mode.setFixedWidth(40)
        self._tb_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tb_mode.clicked.connect(self._cycle_line_mode)
        row1.addWidget(self._tb_mode)
        self._update_mode_button()
        # 260609-20(I3): 일부분 지우기(얇게/두껍게) — 전체 청소 버튼 왼쪽
        self._tb_erasers = []
        for ei, ew in enumerate(self._eraser_widths):
            eb = QPushButton()
            # 260611-2: 본문과 동일 디자인 아이콘(얇게/두껍게), 없으면 기존 드로잉 아이콘
            _ep = resource_path("icon_eraser_thin.png" if ei == 0 else "icon_eraser_thick.png")
            eb.setIcon(QIcon(_ep) if _ep else self._make_part_eraser_icon(ew))
            eb.setCheckable(True); eb.setFixedWidth(38)
            eb.setToolTip(f"일부분 지우기 ({'얇게' if ei == 0 else '두껍게'}, 굵기 {ew})")
            eb.setCursor(Qt.CursorShape.PointingHandCursor)
            eb.clicked.connect(lambda _=False, k=ei: self._set_eraser(k))
            row1.addWidget(eb)
            self._tb_erasers.append(eb)
        # 260609-18(G4): 전체 청소 버튼 — 지우개 아이콘
        self._tb_erase = QPushButton()
        _bp = resource_path("icon_broom.png")     # 260611-2: 본문과 동일 청소 아이콘
        self._tb_erase.setIcon(QIcon(_bp) if _bp else self._make_eraser_icon())
        self._tb_erase.setFixedWidth(38)
        self._tb_erase.setToolTip("청소 — 현재 페이지의 선 모두 지우기")
        self._tb_erase.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.12);border:none;border-radius:6px;"
            "padding:4px;}QPushButton:hover{background:rgba(255,255,255,0.25);}")
        self._tb_erase.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tb_erase.clicked.connect(self._clear_drawings)
        row1.addWidget(self._tb_erase)
        self._update_tool_buttons()
        # 260609-25(I4): '본화면 적용' 토글(기본 꺼짐) — 나갈 때 선을 본화면/PDF에 적용 확인
        self._tb_apply = QPushButton("본화면 적용")
        self._tb_apply.setCheckable(True); self._tb_apply.setChecked(self._apply_on_exit)
        self._tb_apply.setToolTip("켜면 전체화면 종료 시 그린 선을 본화면/PDF에 적용할지 확인")
        self._tb_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tb_apply.toggled.connect(self._on_apply_toggled)
        row1.addWidget(self._tb_apply)
        self._update_apply_button()
        # 260611-85/86: '링크실행' — 페이지의 사진·동영상 링크를 전체화면으로 순서대로
        #   (미디어 링크 없는 페이지에선 비활성)
        self._tb_linkplay = QPushButton("링크실행")
        self._tb_linkplay.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.12);color:#fff;border:none;"
            "border-radius:6px;padding:4px 14px;font-size:16px;font-weight:bold;}"
            "QPushButton:hover{background:rgba(255,255,255,0.25);}"
            "QPushButton:disabled{color:#777;background:rgba(255,255,255,0.05);}")
        self._tb_linkplay.setToolTip("이 페이지의 사진·동영상 링크를 전체화면으로 보기 "
                                     "(클릭마다 다음 링크)")
        self._tb_linkplay.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tb_linkplay.setEnabled(False)
        self._tb_linkplay.clicked.connect(lambda: self.linkPlayRequested.emit())
        row1.addWidget(self._tb_linkplay)
        # 260611-22: 좌측 버튼과 구분되게 약간 띄움
        _gap_t = QWidget(); _gap_t.setFixedWidth(16); row1.addWidget(_gap_t)
        # 260611-19/20: 발표시간 표시 토글(시계 아이콘).
        #   눌림(체크) 시 배경을 붉은색으로 명확히 표시.
        self._tb_timer = QPushButton()
        self._tb_timer.setCheckable(True)
        self._tb_timer.setToolTip("발표시간 표시 (켜면 준비내용 → 다음 페이지에서 시간 시작)")
        _tic = resource_path("icon_pres_timer.png")
        if _tic:
            self._tb_timer.setIcon(QIcon(_tic)); self._tb_timer.setIconSize(QSize(24, 24))
        else:
            self._tb_timer.setText("⏱")
        timer_css = (nav_css
                     + "QPushButton:checked{background:rgba(220,40,40,0.95);}"
                       "QPushButton:checked:hover{background:rgba(235,60,60,1.0);}")
        self._tb_timer.setStyleSheet(timer_css)
        self._tb_timer.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tb_timer.toggled.connect(self._on_timer_toggle)
        row1.addWidget(self._tb_timer)
        # 260611-22: 시계 중지 버튼 — 시계 오른쪽. 누르면 멈춤(토글), 중지 중 0.5초 적색 블링크.
        self._tb_timer_stop = QPushButton("⏸")
        self._tb_timer_stop.setCheckable(True)
        self._tb_timer_stop.setToolTip("시계 중지/재개")
        self._tb_timer_stop_css = nav_css
        self._tb_timer_stop.setStyleSheet(self._tb_timer_stop_css)
        self._tb_timer_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tb_timer_stop.toggled.connect(self._on_timer_stop_toggle)
        row1.addWidget(self._tb_timer_stop)
        # 중지 블링크 타이머(0.5초)
        self._stop_blink_on = False
        self._stop_blink_timer = QTimer(self)
        self._stop_blink_timer.setInterval(500)
        self._stop_blink_timer.timeout.connect(self._toggle_stop_blink)
        # 260609-18(G6): 선/지우기 ↔ 녹화 버튼 사이 간격
        _gap = QWidget(); _gap.setFixedWidth(18); row1.addWidget(_gap)
        # 260609-17(F4): 녹화/일시정지/중지 (✕ 왼쪽)
        rec_css = ("QPushButton{background:rgba(255,255,255,0.12);color:#fff;border:none;"
                   "border-radius:6px;padding:4px 10px;font-size:15px;font-weight:bold;}"
                   "QPushButton:hover{background:rgba(255,255,255,0.25);}"
                   "QPushButton:disabled{color:#777;}")
        self._tb_rec = QPushButton("●"); self._tb_rec.setStyleSheet(rec_css)
        self._tb_rec.setToolTip("녹화/재개")
        self._tb_rec.clicked.connect(self.recordToggleRequested)
        self._tb_recpause = QPushButton("‖"); self._tb_recpause.setStyleSheet(rec_css)
        self._tb_recpause.setToolTip("일시정지")
        self._tb_recpause.clicked.connect(self.recordPauseRequested)
        self._tb_recstop = QPushButton("■"); self._tb_recstop.setStyleSheet(rec_css)
        self._tb_recstop.setToolTip("중지")
        self._tb_recstop.clicked.connect(self.recordStopRequested)
        for b in (self._tb_rec, self._tb_recpause, self._tb_recstop):
            row1.addWidget(b)
        self.set_recording_state(False, False)
        # 260611-86: 가운데 정렬 — 페이지 이동(좌)·닫기(우) 제외하고 중앙 그룹을 중앙에
        row1.addStretch(1)
        # 260609-19(H4): 녹화 버튼 ↔ ✕ 사이 간격
        _gap2 = QWidget(); _gap2.setFixedWidth(18); row1.addWidget(_gap2)
        self._tb_close = QPushButton("✕")
        self._tb_close.setToolTip("전체화면 보기 종료")
        self._tb_close.setStyleSheet(nav_css)
        self._tb_close.clicked.connect(self.close)   # D2: 전체모드 종료
        row1.addWidget(self._tb_close)
        outer.addLayout(row1)
        self._update_pen_buttons()

        # 2행+: 하이퍼링크(우측 정렬, 줄바꿈) — D5
        self._tb_hl_box = QVBoxLayout(); self._tb_hl_box.setSpacing(4)
        outer.addLayout(self._tb_hl_box)
        self._tb_page_items = []        # 콤보 인덱스 → page0(숨김 제외)
        self._topbar.hide()

    def set_recording_state(self, recording: bool, paused: bool):
        """260609-17(F4): 녹화 버튼 색/활성 상태 갱신."""
        rec = getattr(self, "_tb_rec", None)
        if rec is None:
            return
        base = ("QPushButton{{background:{bg};color:#fff;border:none;border-radius:6px;"
                "padding:4px 10px;font-size:15px;font-weight:bold;}}"
                "QPushButton:disabled{{color:#777;background:rgba(255,255,255,0.06);}}")
        if recording and not paused:
            self._tb_rec.setStyleSheet(base.format(bg="rgba(220,40,40,0.95)"))  # 빨간 녹화중
            self._tb_rec.setEnabled(False)
            self._tb_recpause.setEnabled(True)
            self._tb_recstop.setEnabled(True)
        elif recording and paused:
            self._tb_rec.setStyleSheet(base.format(bg="rgba(220,160,40,0.95)"))
            self._tb_rec.setEnabled(True)      # 재개
            self._tb_recpause.setEnabled(False)
            self._tb_recstop.setEnabled(True)
        else:
            self._tb_rec.setStyleSheet(base.format(bg="rgba(220,40,40,0.55)"))
            self._tb_rec.setEnabled(True)      # 시작
            self._tb_recpause.setEnabled(False)
            self._tb_recstop.setEnabled(False)

    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            # G5: 풀다운에서 마우스가 벗어나면 2초 후 숨김(다시 들어오면 취소)
            view = self._tb_page.view()
            if obj in (view, view.viewport()):
                if t == QEvent.Type.Leave:
                    self._combo_leave_timer.start()
                elif t in (QEvent.Type.Enter, QEvent.Type.MouseMove):
                    self._combo_leave_timer.stop()
        except Exception:
            pass
        return super().eventFilter(obj, ev)

    def _populate_page_combo(self):
        cb = self._tb_page
        cb.blockSignals(True)
        cb.clear()
        self._tb_page_items = []
        bm = {}
        if self._bookmark_resolver:
            try:
                for pg, title in (self._bookmark_resolver(str(self._path)) or []):
                    bm.setdefault(int(pg), str(title))
            except Exception:
                bm = {}
        n = self._doc.page_count
        width = len(str(n))
        for p in range(n):
            if self._is_hidden(p):           # D4: 숨김 페이지는 풀다운에서 제외
                continue
            num = str(p + 1).rjust(width)
            label = f"{num}  {bm[p]}" if p in bm else num
            cb.addItem(label)
            self._tb_page_items.append(p)
        cb.blockSignals(False)
        self._combo_page_count = n            # 재생성 판단용

    def _update_topbar(self):
        # 페이지 콤보(파일/숨김 변경 시 재생성) + 현재 선택
        if (self._tb_page.count() == 0
                or getattr(self, "_combo_page_count", -1) != self._doc.page_count):
            self._populate_page_combo()
        self._suppress_combo = True
        try:
            idx = self._tb_page_items.index(self._page)
        except ValueError:
            idx = min(range(len(self._tb_page_items)),
                      key=lambda i: abs(self._tb_page_items[i] - self._page)) \
                if self._tb_page_items else 0
        self._tb_page.setCurrentIndex(idx)
        self._suppress_combo = False

        # 하이퍼링크 버튼 — 우측 정렬·줄바꿈(D5)
        from PyQt6.QtWidgets import QPushButton, QHBoxLayout, QWidget as _QW
        while self._tb_hl_box.count():
            it = self._tb_hl_box.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._hl_buttons = []
        links = []
        if self._hyperlink_resolver:
            try:
                links = self._hyperlink_resolver(str(self._path), self._page) or []
            except Exception:
                links = []
        # 260611-86: '링크실행' 버튼은 페이지에 사진·동영상 링크가 있을 때만 활성화
        try:
            from viewer.widgets.media_overlay import IMAGE_EXT, VIDEO_EXT
            media = IMAGE_EXT | VIDEO_EXT
            has_media = any(ln.get("kind") == "file"
                            and Path(str(ln.get("target", ""))).suffix.lower() in media
                            for ln in links)
            if hasattr(self, "_tb_linkplay"):
                self._tb_linkplay.setEnabled(has_media)
        except Exception:
            pass
        if not links:
            return
        avail = max(120, self.width() - 40)
        spacing = 6
        rows = [[]]; cur_w = 0
        for ln in links:
            from viewer.widgets.main_view import _hyperlink_icon
            tag = _hyperlink_icon(ln)        # 260611-107: 사진/영상/유튜브/파일/링크 아이콘
            b = QPushButton(f"{tag} {ln.get('name', '링크')}")
            b.setStyleSheet(
                "QPushButton{background:rgba(21,101,192,0.95);color:#fff;border:none;"
                "border-radius:6px;padding:4px 12px;font-weight:bold;}"
                "QPushButton:hover{background:rgba(25,118,210,1.0);}")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, l=ln: self.hyperlinkActivated.emit(l))
            b.adjustSize()
            bw = b.sizeHint().width()
            if rows[-1] and cur_w + spacing + bw > avail:
                rows.append([]); cur_w = 0
            rows[-1].append(b); cur_w += (spacing if cur_w else 0) + bw
            self._hl_buttons.append(b)
        for row in rows:
            rw = _QW(); hl = QHBoxLayout(rw)
            hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(spacing)
            hl.addStretch(1)                 # 260611-86: 중앙 정렬(양쪽 stretch)
            for b in row:
                b.setParent(rw); hl.addWidget(b)
            hl.addStretch(1)
            self._tb_hl_box.addWidget(rw)

    def _on_page_combo_activated(self, idx):
        if self._suppress_combo:
            return
        if 0 <= idx < len(self._tb_page_items):
            self._go(self._tb_page_items[idx])

    def _on_page_combo_enter(self):
        cur = self._tb_page.currentText().strip()
        txt = cur.split()[0] if cur else ""
        try:
            self._go(int(txt) - 1)
        except Exception:
            pass

    def _page_has_links(self) -> bool:
        if not self._hyperlink_resolver:
            return False
        try:
            return bool(self._hyperlink_resolver(str(self._path), self._page))
        except Exception:
            return False

    def _maybe_autoshow_topbar(self):
        """260609-15(D3): 하이퍼링크 페이지는 처음 2초간 띠 표시 후 자동 숨김."""
        tb = getattr(self, "_topbar", None)
        if tb is None:
            return
        if self._page != self._autoshown_page and self._page_has_links():
            self._autoshown_page = self._page
            self._show_topbar(auto=True)

    def _position_topbar(self):
        tb = getattr(self, "_topbar", None)
        if tb is None:
            return
        # D4: 페이지 이동 콤보 그룹 최대 폭 = 전체 폭의 1/3
        nw = getattr(self, "_tb_navwrap", None)
        if nw is not None:
            nw.setMaximumWidth(max(160, self.width() // 3))
        tb.setFixedWidth(self.width())
        tb.move(0, 0)
        tb.adjustSize()
        # 최소 높이는 설정값, 내용(줄바꿈)이 많으면 그만큼 늘어남
        if tb.height() < self._topbar_h:
            tb.setFixedHeight(self._topbar_h)
            tb.setFixedWidth(self.width())

    def _show_topbar(self, auto: bool = False):
        tb = getattr(self, "_topbar", None)
        if tb is None:
            return
        self._update_topbar()
        self._position_topbar()
        tb.show()
        tb.raise_()
        # D3: 자동표시는 2초 후 숨김 / 호버 표시는 타이머 정지(머무름)
        if auto:
            self._autohide_timer.start()
        else:
            self._autohide_timer.stop()

    def _hide_topbar(self):
        tb = getattr(self, "_topbar", None)
        if tb is not None and tb.isVisible():
            tb.hide()

    # --- 표시 ---
    def _move_to_target_screen(self):
        """260615-2: ⑧ 선택한 모니터로 창을 옮긴 뒤 전체화면(없으면 현재 화면)."""
        scr = self._target_screen
        if scr is None:
            return
        try:
            self.setScreen(scr)
            self.setGeometry(scr.geometry())   # 전체화면 전 그 모니터로 이동
        except Exception:
            pass

    def set_target_screen(self, scr):
        """260615-2: 표시 모니터 변경 → 즉시 그 모니터로 전체화면 재표시."""
        self._target_screen = scr
        self.showNormal()
        self._move_to_target_screen()
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.showFullScreen()
        self.raise_(); self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._position_topbar(); self._render()

    def show_presentation(self):
        # 260609-9: 최상위 창으로 전체화면 표시 + 포커스(키 입력 수신)
        self._move_to_target_screen()           # 260615-2: ⑧ 지정 모니터로
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._position_topbar()
        self._render()
        self._apply_pointer()
        self._ptr_timer.start()

    # --- 260609-5: 포인터 ---
    def _make_pointer_cursor(self, preset) -> QCursor:
        """채움색+테두리색 원형 포인터 커서(중앙 핫스팟)."""
        d = 26
        pm = QPixmap(d, d)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            fill = QColor(preset.get("fill", "#ff3030"))
            border = QColor(preset.get("border", "#ffffff"))
        except Exception:
            fill, border = QColor("#ff3030"), QColor("#ffffff")
        p.setPen(QPen(border, 2))
        p.setBrush(fill)
        p.drawEllipse(4, 4, d - 8, d - 8)
        p.end()
        return QCursor(pm, d // 2, d // 2)

    def _apply_pointer(self):
        self._ptr_hidden = False
        try:
            preset = self._pointers[self._ptr_active]
        except Exception:
            preset = DEFAULT_POINTERS[0]
        self.setCursor(self._make_pointer_cursor(preset))

    def _hide_pointer(self):
        self._ptr_hidden = True
        self.setCursor(Qt.CursorShape.BlankCursor)

    def set_pointers(self, pointers, active: int = None):
        """앱이 설정 변경 후 호출 — 프리셋/활성 갱신·즉시 반영."""
        if pointers:
            self._pointers = list(pointers)
        if active is not None:
            self._ptr_active = max(0, min(len(self._pointers) - 1, int(active)))
        self._apply_pointer()
        self._ptr_timer.start()

    def _page_points(self):
        try:
            pg = self._doc.doc.load_page(self._page)
            r = pg.rect
            w, h = float(r.width), float(r.height)
            if self._rotation() in (90, 270):   # 260609-15(A1): 회전 시 폭/높이 스왑
                w, h = h, w
            return w, h
        except Exception:
            return 595.0, 842.0     # A4 fallback

    def _rotation(self) -> int:
        if self._rotation_resolver:
            try:
                return int(self._rotation_resolver(str(self._path), self._page)) % 360
            except Exception:
                return 0
        return 0

    def _render_pixmap(self, dpi):
        rp = self._doc.render(self._page, dpi=dpi)
        img = QImage(rp.samples, rp.width, rp.height,
                     rp.width * 3, QImage.Format.Format_RGB888)
        pm = QPixmap.fromImage(img)
        rot = self._rotation()          # 260609-15(A1)
        if rot:
            pm = pm.transformed(QTransform().rotate(rot),
                                Qt.TransformationMode.SmoothTransformation)
        return pm

    def _page_is_split(self):
        """260611-28: 상하 2분할이 켜져 있어도 '가로가 더 긴 페이지(세로<가로)'는 그 페이지만
        분할 해제. 토글 기본값은 진입/파일전환 시 페이지 방향(세로>가로)으로 결정."""
        if not self._split_mode:
            return False
        pw, ph = self._page_points()
        return ph >= pw

    def _orient_split_default(self):
        """260611-27: 페이지 세로길이>가로길이(세로 페이지)일 때만 분할 기본 ON."""
        try:
            pw, ph = self._page_points()
            return ph > pw
        except Exception:
            return False

    def _get_crop(self):
        """(top%, bottom%) — 페이지별 우선."""
        if self._crop_resolver:
            try:
                t, b = self._crop_resolver(str(self._path), self._page)
                return float(t), float(b)
            except Exception:
                return 0.0, 0.0
        return 0.0, 0.0

    def _render_cropped(self, dpi):
        """260609-14(D4): 렌더 후 상/하단 크롭(%) 적용한 픽스맵."""
        pm = self._render_pixmap(dpi)
        ct, cb = self._get_crop()
        if ct > 0 or cb > 0:
            H = pm.height()
            t = int(H * ct / 100.0)
            b = int(H * cb / 100.0)
            h2 = max(1, H - t - b)
            pm = pm.copy(0, min(t, H - 1), pm.width(), h2)
        return pm

    def _current_pixmap_fit(self, sw, sh):
        """현재 페이지(또는 분할 반쪽)를 화면맞춤 픽스맵으로 반환(크롭 반영)."""
        pw_pt, ph_pt = self._page_points()
        if pw_pt <= 0 or ph_pt <= 0:
            return None
        try:
            if self._page_is_split():
                dpi = max(72, min(400, int(sw * 72.0 / pw_pt)))   # 폭맞춤
                pm = self._render_cropped(dpi)    # 크롭된 화면 기준 재산정(D4)
                H = pm.height()
                ov = int(H * self._overlap_frac)
                mid = H // 2
                if self._split_half == 0:
                    pm = pm.copy(0, 0, pm.width(), min(H, mid + ov // 2))
                else:
                    y0 = max(0, mid - ov // 2)
                    pm = pm.copy(0, y0, pm.width(), H - y0)
                    # 260609-16(F2): 하단 볼 때, 상단에서 이미 본 겹침부를 반투명 띠로
                    if ov > 0:
                        _p = QPainter(pm)
                        _p.fillRect(0, 0, pm.width(), ov, QColor(0, 0, 0, 51))
                        _p.end()
            else:
                dpi = min(sw * 72.0 / pw_pt, sh * 72.0 / ph_pt)
                dpi = max(72, min(400, int(dpi)))
                pm = self._render_cropped(dpi)
            # 260615-2: ⑦ 화면 채움 — 비율 무시하고 sw×sh 로 늘려 전체 채움
            if self._fill_screen and not self._page_is_split():
                pm = pm.scaled(sw, sh, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            elif pm.width() > sw or pm.height() > sh:
                pm = pm.scaled(sw, sh, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            return pm
        except Exception:
            return None

    def _render(self):
        sw = max(1, self.width())
        sh = max(1, self.height())
        if self._armed:
            self._render_overlay(sw, sh)
        else:
            pm = self._current_pixmap_fit(sw, sh)
            if pm is not None:
                self._label.setPixmap(pm)
            else:
                self._label.setText("페이지를 표시할 수 없습니다.")
                self._label.setStyleSheet("color:#bbb;font-size:20px;background:#000;")
        # 새 페이지 도착 시 자동표시 재허용(D3) + 그리기 오버레이 갱신(F3)
        if getattr(self, "_rendered_page", -2) != self._page:
            self._rendered_page = self._page
            self._autoshown_page = -1
        if getattr(self, "_draw_overlay", None) is not None:
            self._draw_overlay.update()
        # 260609-8: 상단 띠가 보이면 페이지/링크 갱신
        if getattr(self, "_topbar", None) is not None and self._topbar.isVisible():
            self._update_topbar()
            self._position_topbar()
        # 260609-15(D3): 하이퍼링크 페이지는 2초 자동 표시
        self._maybe_autoshow_topbar()

    def _render_overlay(self, sw, sh):
        """260609-7: 다음/이전 파일 첫/마지막 페이지를 50%로 중앙 오버레이.
        기존 페이지는 흐리게, 상단에 '다음/이전으로 이동' 표시."""
        canvas = QPixmap(sw, sh)
        canvas.fill(QColor("#000"))
        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        base = self._current_pixmap_fit(sw, sh)
        if base is not None:
            p.drawPixmap((sw - base.width()) // 2, (sh - base.height()) // 2, base)
        p.fillRect(0, 0, sw, sh, QColor(0, 0, 0, 150))      # 흐리게(딤)
        # 형제 파일 미리보기(50%)
        try:
            d = PdfDocument(str(self._armed_path))
            pg = (d.page_count - 1) if self._armed < 0 else 0
            r = d.doc.load_page(pg).rect
            pw, ph = float(r.width), float(r.height)
            tw, th = sw * 0.5, sh * 0.5
            dpi = max(48, min(300, int(min(tw * 72.0 / pw, th * 72.0 / ph))))
            rp = d.render(pg, dpi=dpi)
            img = QImage(rp.samples, rp.width, rp.height,
                         rp.width * 3, QImage.Format.Format_RGB888)
            spm = QPixmap.fromImage(img)
            if spm.width() > tw or spm.height() > th:
                spm = spm.scaled(int(tw), int(th), Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            x = (sw - spm.width()) // 2
            y = (sh - spm.height()) // 2
            p.drawPixmap(x, y, spm)
            p.setPen(QPen(QColor("#ffffff"), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(x, y, spm.width(), spm.height())
            d.close()
        except Exception:
            pass
        # 상단 배너
        from pathlib import Path as _P
        nm = _P(str(self._armed_path)).name
        txt = (f"다음으로 이동  ▶   {nm}" if self._armed > 0
               else f"◀  이전으로 이동   {nm}")
        from PyQt6.QtGui import QFont as _QF
        f = _QF(); f.setPointSize(20); f.setBold(True); p.setFont(f)
        fm = p.fontMetrics()
        tw2 = fm.horizontalAdvance(txt) + 40
        bx = (sw - tw2) // 2
        p.fillRect(bx, 24, tw2, fm.height() + 16, QColor(21, 101, 192, 230))
        p.setPen(QColor("#ffffff"))
        p.drawText(bx, 24, tw2, fm.height() + 16,
                   Qt.AlignmentFlag.AlignCenter, txt)
        p.end()
        self._label.setPixmap(canvas)

    def set_split(self, on: bool):
        on = bool(on)
        if on != self._split_mode:
            self._armed = 0          # 분할 토글 시 경계 무장 해제
            self._armed_path = None
            self._split_mode = on
            self._split_half = 0
            self._render()
            self.splitModeChanged.emit(on)

    # --- 260609-7: 파일 경계 오버레이 ---
    def _arm_boundary(self, direction: int) -> bool:
        if not self._sibling_resolver:
            return False
        try:
            sib = self._sibling_resolver(str(self._path), direction)
        except Exception:
            sib = None
        if not sib:
            return False
        self._armed = direction
        self._armed_path = sib
        self._render()
        return True

    def _cancel_arm(self):
        if self._armed:
            self._armed = 0
            self._armed_path = None
            self._render()

    def _switch_file(self, path, to_end: bool):
        try:
            self._doc.close()
        except Exception:
            pass
        self._doc = PdfDocument(str(path))
        self._path = Path(str(path))
        self.setWindowTitle(f"발표 — {self._path.name}")
        self._strokes = {}            # 260609-25(I4): 파일 바뀌면 화면 선 초기화(파일별 적용)
        tp = getattr(self, "_thumb_panel", None)
        if tp is not None:
            tp.list.clear()           # 260609-24(I5): 새 파일 → 썸네일 재생성 예약
        self._armed = 0
        self._armed_path = None
        self._page = (self._doc.page_count - 1) if to_end else 0
        # 260609-14(D5): 진입 페이지가 숨김이면 보이는 페이지로
        if self._is_hidden(self._page):
            vp = self._visible_step(self._page, -1 if to_end else +1)
            if vp is None:
                vp = self._visible_step(self._page, +1 if to_end else -1)
            if vp is not None:
                self._page = vp
        # 260611-26: 새 파일의 방향(가로>세로)으로 상하 2분할 기본값 재계산
        self._split_mode = self._orient_split_default()
        # 다음→첫쪽 상부 / 이전→마지막쪽(세로 분할 페이지면 하부)
        self._split_half = 1 if (self._page_is_split() and to_end) else 0
        self._render()
        # 260611-19: 타이머 ON 중 파일 전환 — 앞으로(다음) 가면 준비내용 표시(다음에 리셋),
        #   뒤로 가면 연속 시계 유지(지나간 시간 감안)
        if self._timer_ctl.state != self._timer_ctl.OFF:
            self._set_stop_checked(False)        # 260611-22: 전환 시 중지 해제
            if to_end:
                self._timer_ctl.resume_running()
                self._start_timer_qtimer()
            else:
                self._timer_ctl.arm_standby()
                self._stop_timer_qtimer()
            self.update()
        # 260611-23: 파일 전환 통지(녹화 중이면 앱이 새 파일명으로 녹화 재시작)
        try:
            self.fileChanged.emit(str(self._path))
        except Exception:
            pass

    def refresh(self):
        """260609-14: 외부(크롭·숨김 변경) 후 현재 화면 재렌더."""
        if self._is_hidden(self._page):
            self._go(self._page)            # 현재가 숨겨졌으면 보이는 페이지로
        else:
            self._render()

    # --- 260609-14(D5): 숨김 페이지 ---
    def _is_hidden(self, page0) -> bool:
        if not self._hidden_resolver:
            return False
        try:
            return int(page0) in (self._hidden_resolver(str(self._path)) or set())
        except Exception:
            return False

    def _visible_step(self, start, direction):
        """start 에서 direction(+1/-1) 방향으로 첫 '보이는' 페이지. 없으면 None."""
        p = int(start) + direction
        n = self._doc.page_count
        while 0 <= p < n:
            if not self._is_hidden(p):
                return p
            p += direction
        return None

    # --- 탐색 ---
    def _go(self, page0: int):
        self._cancel_arm()
        page0 = max(0, min(self._doc.page_count - 1, int(page0)))
        if self._is_hidden(page0):           # 숨김이면 가까운 보이는 페이지로
            vp = self._visible_step(page0, +1)
            if vp is None:
                vp = self._visible_step(page0, -1)
            if vp is None:
                return
            page0 = vp
        if page0 != self._page or self._split_mode:
            self._page = page0
            self._split_half = 0           # 페이지 점프 → 상부부터
            self._render()

    def _next(self):
        # 260611-19: 준비(STANDBY)에서 '다음 페이지' → 지정시간으로 리셋·시작(페이지 이동 없음)
        if self._timer_ctl.state == self._timer_ctl.STANDBY:
            self._timer_ctl.start_running()
            self._start_timer_qtimer()
            # 260611-24: '발표시 녹화시작'은 준비내용이 아니라 그 이후(시간 시작)부터
            if self._timer_cfg.get("rec_on_start"):
                self.recordToggleRequested.emit()
            self.update()
            return
        # 무장 상태에서 한 번 더 → 실제 파일 전환
        if self._armed > 0:
            self._switch_file(self._armed_path, to_end=False)
            return
        if self._armed:
            self._cancel_arm()
        # 260609-6/18: 분할(세로 페이지)이면 상부→하부
        if self._page_is_split() and self._split_half == 0:
            self._split_half = 1
            self._render()
            return
        nv = self._visible_step(self._page, +1)   # 숨김 건너뜀
        if nv is not None:
            self._page = nv
            self._split_half = 0
            self._render()
            return
        # 마지막 보이는 뷰 → 다음 파일 경계 무장(있으면)
        self._arm_boundary(+1)

    def _prev(self):
        # 260611-19: 준비 화면에서 뒤로 → 연속 시계 재개(리셋 없이) 후 정상 이전 처리
        if self._timer_ctl.state == self._timer_ctl.STANDBY:
            self._timer_ctl.resume_running()
            self._start_timer_qtimer()
            self.update()
        if self._armed < 0:
            self._switch_file(self._armed_path, to_end=True)
            return
        if self._armed:
            self._cancel_arm()
        if self._page_is_split() and self._split_half == 1:
            self._split_half = 0
            self._render()
            return
        pv = self._visible_step(self._page, -1)   # 숨김 건너뜀
        if pv is not None:
            self._page = pv
            # 이전 페이지가 분할(세로)이면 하부부터
            self._split_half = 1 if self._page_is_split() else 0
            self._render()
            return
        # 첫 보이는 뷰 → 이전 파일 경계 무장(있으면)
        self._arm_boundary(-1)

    def _commit_numbuf(self):
        if self._numbuf:
            try:
                self._go(int(self._numbuf) - 1)
            except Exception:
                pass
        self._numbuf = ""
        self._hint.hide()

    def _update_hint(self):
        if self._numbuf:
            self._hint.setText(f"페이지 {self._numbuf} / {self._doc.page_count}")
            self._hint.adjustSize()
            self._hint.move((self.width() - self._hint.width()) // 2,
                            (self.height() - self._hint.height()) // 2)
            self._hint.show()
            self._hint.raise_()
        else:
            self._hint.hide()

    # --- 이벤트 ---
    def keyPressEvent(self, e):
        k = e.key()
        # 260609-16(F3): 펜 단축키(Ctrl+1/2/3 등) — 숫자 입력보다 우선
        if e.modifiers() != Qt.KeyboardModifier.NoModifier:
            from PyQt6.QtGui import QKeySequence
            try:
                pressed = QKeySequence(e.keyCombination()).toString()
            except Exception:
                pressed = ""
            if pressed:
                pl = pressed.lower()
                for i, ks in enumerate(self._pen_keys[:len(self._pens)]):
                    if ks and QKeySequence(ks).toString().lower() == pl:
                        self._set_pen(i)
                        return
                # 260609-17(F4): 녹화/중지 단축키
                rk = self._rec_keys
                if len(rk) >= 1 and rk[0] and QKeySequence(rk[0]).toString().lower() == pl:
                    self.recordToggleRequested.emit(); return
                if len(rk) >= 2 and rk[1] and QKeySequence(rk[1]).toString().lower() == pl:
                    self.recordStopRequested.emit(); return
        if k == Qt.Key.Key_Escape:
            if self._armed:
                self._cancel_arm()
            elif self._numbuf:
                self._numbuf = ""
                self._hint.hide()
            else:
                self.close()
            return
        if k in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self._commit_numbuf()
            return
        if Qt.Key.Key_0 <= k <= Qt.Key.Key_9:
            self._numbuf = (self._numbuf + chr(k))[:6]
            self._update_hint()
            return
        if k in (Qt.Key.Key_Backspace,):
            self._numbuf = self._numbuf[:-1]
            self._update_hint()
            return
        if k in (Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_PageDown,
                 Qt.Key.Key_Down):
            self._next()
            return
        if k in (Qt.Key.Key_Left, Qt.Key.Key_PageUp, Qt.Key.Key_Up):
            self._prev()
            return
        if k == Qt.Key.Key_Home:
            self._go(0)
            return
        if k == Qt.Key.Key_End:
            self._go(self._doc.page_count - 1)
            return
        if k == Qt.Key.Key_S:                 # 260609-6: 상하 2분할 토글
            self.set_split(not self._split_mode)
            return
        super().keyPressEvent(e)

    def _evt_pos(self, e):
        try:
            return e.position().toPoint()
        except Exception:
            return e.pos()

    def mouseMoveEvent(self, e):
        pos = self._evt_pos(e)
        if e.buttons() & Qt.MouseButton.LeftButton:
            sp = self._press_pos
            moved = (sp is not None and (abs(pos.x() - sp.x()) > 4 or abs(pos.y() - sp.y()) > 4))
            # 260609-20(I3): 일부분 지우기 드래그
            if self._tool == "erase" and self._erasing:
                if moved:
                    self._drag_moved = True
                self._erase_at(pos)
                super().mouseMoveEvent(e)
                return
            # 260611-4: 펜 드래그 → 그리기 (3단계: 직선/하이라이트/자유곡선)
            if self._cur_stroke is not None:
                from PyQt6.QtCore import QPoint
                if self._cur_stroke.get("hl"):
                    yc = self._cur_stroke["points"][0].y()
                    self._cur_stroke["points"] = [QPoint(sp.x(), yc), QPoint(pos.x(), yc)]
                elif self._line_mode == 0 and sp is not None:
                    self._cur_stroke["points"] = [sp, QPoint(pos.x(), sp.y())]
                else:
                    self._cur_stroke["points"].append(pos)
                if moved:
                    self._drag_moved = True
                self._draw_overlay.update()
                super().mouseMoveEvent(e)
                return
        # 260609-5: 움직이면 포인터 복귀 + 2초 타이머 재시작
        if self._ptr_hidden:
            self._apply_pointer()
        self._ptr_timer.start()
        # 260609-24(I5): 좌측 끝단 호버 → 슬라이드 썸네일 표시 / 벗어나면 숨김
        tp = getattr(self, "_thumb_panel", None)
        if tp is not None:
            if pos.x() <= 6:
                tp.slide_in()
            elif tp.isVisible() and pos.x() > tp.width():
                tp.slide_out()
        # 260609-8: 상단 근처면 호버 띠 표시, 벗어나면 숨김
        y = pos.y()
        if y <= max(48, int(self.height() * 0.10)):
            self._show_topbar()
        elif not self._autohide_timer.isActive():
            # 260609-16(F1): 자동표시(2초) 동안은 마우스가 움직여도 닫지 않음
            self._hide_topbar()
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pos = self._evt_pos(e)
            self._press_pos = pos
            self._drag_moved = False
            if self._tool == "erase":
                self._erasing = True          # 드래그면 지우기, 클릭이면 탐색
            else:
                pen = self._pens[self._pen_active] if self._pens else DEFAULT_PENS[0]
                st = {"color": pen.get("color", "#ff3030"),
                      "width": int(pen.get("width", 3)),
                      "alpha": int(pen.get("alpha", 100)),
                      "points": [pos],
                      # 260611-7: 상하2분할일 때 그린 반쪽 기록 → 다른 반쪽엔 안 보이게
                      "half": (self._split_half if self._page_is_split() else 0)}
                # 260611-4: 하이라이트 모드 — 누른 위치의 텍스트 줄 높이(화면 px 띠)
                if self._line_mode == 1:
                    from PyQt6.QtCore import QPoint
                    band = self._hl_band_screen(pos)
                    yc = int((band[0] + band[1]) / 2.0) if band else pos.y()
                    hh = (band[1] - band[0]) if band else max(8.0, self.height() * 0.02)
                    st["hl"] = True
                    st["h"] = float(hh)
                    st["points"] = [QPoint(pos.x(), yc), QPoint(pos.x(), yc)]
                self._cur_stroke = st
        super().mousePressEvent(e)

    def _hl_band_screen(self, pos):
        """260611-5: 발표 하이라이트 띠를 (top_y, bottom_y) 화면 px 로.

        전체화면은 크롭·상하2분할·상단띠 등으로 화면↔PDF 절대 위치 매핑이 어긋나
        '이상한 위치' 하이라이트가 생기던 문제가 있었다(편집모드는 정확). 위치 오류는
        치명적이므로 **항상 '찍은 위치'(pos.y) 에 중심**을 두고, 굵기만 그 페이지의
        **평균 글자 줄 높이**로 적용한다(텍스트 절대 위치에 의존하지 않음 → 빠르고 안전).
        """
        try:
            hh = self._avg_line_height_screen()
            yc = float(pos.y())
            return (yc - hh / 2.0, yc + hh / 2.0)
        except Exception:
            return None

    def _disp_px_per_pt(self):
        """260611-83: 현재 화면에 '실제로 표시된' 페이지의 픽셀/PDF포인트 배율.
        크롭·쪽맞춤·축소를 모두 반영(전체화면은 크롭으로 글자가 확대되므로 전 페이지
        기준 배율을 쓰면 하이라이트 띠가 실제 글자보다 작아진다 → 실측 배율 사용)."""
        pw, ph = self._page_points()
        if ph <= 0:
            return 1.0
        ct, cb = self._get_crop()
        vis = max(0.05, 1.0 - (ct + cb) / 100.0)
        try:
            if not self._page_is_split():
                pm = self._label.pixmap()
                if pm is not None and not pm.isNull():
                    return pm.height() / (ph * vis)   # 실제 표시 배율(크롭 반영)
        except Exception:
            pass
        sw, sh = max(1, self.width()), max(1, self.height())
        if self._page_is_split():
            dpi = max(72, min(400, int(sw * 72.0 / pw)))
        else:
            dpi = max(72, min(400, int(min(sw * 72.0 / pw, sh * 72.0 / ph))))
        return dpi / 72.0

    def _avg_line_height_screen(self):
        """260611-5/83: 현재 페이지 텍스트 줄 높이 중앙값(실표시 px). 폴백=화면 2%."""
        try:
            cache = getattr(self, "_avg_lh_cache", {})
            key = (self._page, round(self._disp_px_per_pt(), 3))   # 배율 바뀌면 재계산
            if key in cache:
                return cache[key]
            pg = self._doc.doc.load_page(self._page)
            hs = []
            for blk in pg.get_text("dict").get("blocks", []):
                for ln in blk.get("lines", []):
                    b = ln.get("bbox", (0, 0, 0, 0))
                    if b[3] > b[1]:
                        hs.append(b[3] - b[1])
            if hs:
                hs.sort()
                med = hs[len(hs) // 2]
                val = max(6.0, med * self._disp_px_per_pt())
            else:
                val = max(8.0, self.height() * 0.02)
            cache[key] = val
            self._avg_lh_cache = cache
            return val
        except Exception:
            return max(8.0, self.height() * 0.02)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            moved = self._drag_moved
            x = self._evt_pos(e).x()
            if self._tool == "erase":
                self._erasing = False
                if not moved:                 # 단순 클릭 → 탐색
                    (self._prev if x <= int(self.width() * 0.10) else self._next)()
            elif self._cur_stroke is not None:
                stroke = self._cur_stroke
                self._cur_stroke = None
                if moved and len(stroke["points"]) >= 2:
                    self._strokes.setdefault(self._page, []).append(stroke)
                    self._draw_overlay.update()
                else:
                    (self._prev if x <= int(self.width() * 0.10) else self._next)()
            self._press_pos = None
            self._drag_moved = False
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_CSS)        # 260609-10: 가독성(어두운 배경+흰 글씨)
        act_prev = menu.addAction("이전")
        act_next = menu.addAction("다음")
        menu.addSeparator()
        # 260609-5: 포인터 선택 + 설정
        pm = menu.addMenu("포인터")
        pm.setStyleSheet(_MENU_CSS)          # 260609-10: 하위메뉴도 가독성
        ptr_acts = []
        for i, pr in enumerate(self._pointers):
            a = pm.addAction(pr.get("name", f"포인터 {i+1}"))
            a.setCheckable(True)
            a.setChecked(i == self._ptr_active)
            ptr_acts.append(a)
        pm.addSeparator()
        act_ptr_set = pm.addAction("포인터 설정…")
        # 260609-16(F3): 펜(선) 선택 + 설정
        pn = menu.addMenu("선(펜)")
        pn.setStyleSheet(_MENU_CSS)
        pen_acts = []
        for i, pr in enumerate(self._pens):
            a = pn.addAction(pr.get("name", f"사용자선 {i+1}"))
            a.setCheckable(True); a.setChecked(i == self._pen_active)
            pen_acts.append(a)
        pn.addSeparator()
        # 260611-4: 선 종류 3단계
        mode_acts = []
        for mi, mn in enumerate(self._MODE_NAME):
            a = pn.addAction(mn)
            a.setCheckable(True); a.setChecked(mi == self._line_mode)
            mode_acts.append(a)
        pn.addSeparator()
        act_pen_set = pn.addAction("선 설정…")
        # 260611-26: '청소'→'선 지우기'
        act_clear = menu.addAction("선 지우기")
        menu.addSeparator()
        # 260611-26: 상하 2분할 보기 + 중앙겹침 입력박스(위젯 액션) — '선 지우기' 아래로 이동
        from PyQt6.QtWidgets import (QWidgetAction, QWidget, QHBoxLayout,
                                     QCheckBox, QSpinBox, QLabel)
        _sw = QWidget()
        _shb = QHBoxLayout(_sw); _shb.setContentsMargins(20, 4, 14, 4); _shb.setSpacing(8)
        cb_split = QCheckBox("상하 2분할 보기"); cb_split.setChecked(self._split_mode)
        cb_split.toggled.connect(self.set_split)
        _shb.addWidget(cb_split)
        _shb.addWidget(QLabel("중앙겹침"))
        sp_ov = QSpinBox(); sp_ov.setRange(0, 40); sp_ov.setSuffix(" %"); sp_ov.setFixedWidth(72)
        sp_ov.setValue(int(round(self._overlap_frac * 100)))
        sp_ov.valueChanged.connect(self._on_overlap_spin)
        _shb.addWidget(sp_ov); _shb.addStretch(1)
        _sw.setStyleSheet("QWidget{color:#fff;background:transparent;}"
                          "QCheckBox{color:#fff;} QLabel{color:#fff;}")
        _wa = QWidgetAction(menu); _wa.setDefaultWidget(_sw); menu.addAction(_wa)
        menu.addSeparator()
        # 260611-26: '발표 보기 설정'→'보기 설정'(상단 띠 높이 + 크롭)
        act_view_set = menu.addAction("보기 설정…")
        menu.addSeparator()
        # 260611-26: '발표시간'→'발표시간 설정', '발표시간 표시' 제거(상단 시계 아이콘으로 실행)
        tm = menu.addMenu("발표시간 설정")
        tm.setStyleSheet(_MENU_CSS)
        act_tm_hide = tm.addAction("시계 숨기기")
        act_tm_hide.setCheckable(True)
        act_tm_hide.setChecked(self._timer_hidden)
        act_tm_mute = tm.addAction("전체 알람 끄기")
        act_tm_mute.setCheckable(True)
        act_tm_mute.setChecked(self._alarm_muted)
        tm.addSeparator()
        act_tm_set = tm.addAction("발표시간 설정…")
        # 260611-28: 타이머 시작시 녹화시작(기본 체크) — '발표시간 설정' 바로 아래
        act_rec_on = menu.addAction("타이머 시작시 녹화시작")
        act_rec_on.setCheckable(True)
        act_rec_on.setChecked(bool(self._timer_cfg.get("rec_on_start", True)))
        menu.addSeparator()
        # 260615-2: ⑦ 화면 채움(비율 변경) + ⑧ 표시 모니터 선택
        dm = menu.addMenu("화면")
        dm.setStyleSheet(_MENU_CSS)
        act_fill = dm.addAction("화면 채움 (비율 변경)")
        act_fill.setCheckable(True); act_fill.setChecked(self._fill_screen)
        scr_acts = []
        try:
            from PyQt6.QtWidgets import QApplication
            screens = QApplication.screens()
            if len(screens) > 1:
                dm.addSeparator()
                cur = self.screen()
                for i, sc in enumerate(screens):
                    a = dm.addAction(f"모니터 {i+1}  ({sc.geometry().width()}×"
                                     f"{sc.geometry().height()})")
                    a.setCheckable(True); a.setChecked(sc is cur)
                    scr_acts.append((a, sc))
        except Exception:
            pass
        menu.addSeparator()
        act_quit = menu.addAction("전체화면 보기 취소")
        chosen = menu.exec(e.globalPos())
        if chosen is None:
            return
        if chosen == act_quit:
            self.close()
        elif chosen == act_fill:
            self._fill_screen = not self._fill_screen
            self._render()
        elif scr_acts and chosen in [a for a, _ in scr_acts]:
            sc = next(s for a, s in scr_acts if a is chosen)
            self.set_target_screen(sc)
        elif chosen == act_tm_hide:
            self._timer_hidden = not self._timer_hidden
            self.update()
        elif chosen == act_tm_mute:
            self._alarm_muted = not self._alarm_muted
        elif chosen == act_tm_set:
            self._open_timer_settings()
        elif chosen == act_rec_on:
            self._timer_cfg["rec_on_start"] = not self._timer_cfg.get("rec_on_start", True)
            self.timerConfigChanged.emit(self._timer_cfg)
        elif chosen == act_view_set:
            self.viewSettingsRequested.emit()
        elif chosen == act_clear:
            self._clear_drawings()
        elif chosen in mode_acts:
            self.set_line_mode(mode_acts.index(chosen), emit=True)
        elif chosen == act_pen_set:
            self.penSettingsRequested.emit()
        elif chosen in pen_acts:
            self._set_pen(pen_acts.index(chosen))
        elif chosen == act_next:
            self._next()
        elif chosen == act_prev:
            self._prev()
        elif chosen == act_ptr_set:
            self.pointerSettingsRequested.emit()
        elif chosen in ptr_acts:
            self._ptr_active = ptr_acts.index(chosen)
            self._apply_pointer()
            self._ptr_timer.start()
            self.pointerChanged.emit(self._ptr_active)

    def _make_eraser_icon(self):
        """260609-18(G4): 지우개 아이콘(분홍 몸체+파란 밴드+지운 자국)."""
        from PyQt6.QtGui import QIcon, QPolygon
        from PyQt6.QtCore import QPoint
        d = 22
        pm = QPixmap(d, d)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 기울어진 지우개 몸체(평행사변형)
        body = QPolygon([QPoint(4, 14), QPoint(12, 4), QPoint(18, 8), QPoint(10, 18)])
        p.setPen(QPen(QColor("#ffffff"), 1.2))
        p.setBrush(QColor("#f48fb1"))         # 분홍
        p.drawPolygon(body)
        # 파란 밴드
        p.setBrush(QColor("#5a8bd6"))
        band = QPolygon([QPoint(4, 14), QPoint(7, 11), QPoint(13, 15), QPoint(10, 18)])
        p.drawPolygon(band)
        # 지운 자국(밑줄)
        p.setPen(QPen(QColor("#bbbbbb"), 1.4))
        p.drawLine(3, 20, 16, 20)
        p.end()
        return QIcon(pm)

    def _make_straight_icon(self):
        """260609-19(H3): 옆으로 일직선 아이콘(가로 직선)."""
        from PyQt6.QtGui import QIcon
        d = 22
        pm = QPixmap(d, d)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#ffffff"), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(3, d // 2, d - 3, d // 2)
        # 양 끝점 강조(직선 끝)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(2, d // 2 - 2, 4, 4)
        p.drawEllipse(d - 6, d // 2 - 2, 4, 4)
        p.end()
        return QIcon(pm)

    def _make_part_eraser_icon(self, width):
        """260609-20(I3): 일부분 지우개 아이콘(굵기에 따라 원 크기)."""
        from PyQt6.QtGui import QIcon
        d = 22
        pm = QPixmap(d, d)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 지울 자국 선
        p.setPen(QPen(QColor("#cfcfcf"), 1.6))
        p.drawLine(3, 16, d - 3, 16)
        # 지우개 원(굵기 비례)
        r = max(4, min(9, int(width / 3) + 3))
        p.setPen(QPen(QColor("#ffffff"), 1.4))
        p.setBrush(QColor("#f48fb1"))
        cx, cy = d // 2, 9
        p.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
        p.end()
        return QIcon(pm)

    # 260611-4: 선 종류 3단계(본문과 동일 글리프/이름)
    _MODE_GLYPH = ("─", "▬", "〜")
    _MODE_NAME = ("직선", "하이라이트", "자유곡선")

    def _cycle_line_mode(self):
        self.set_line_mode((self._line_mode + 1) % 3, emit=True)

    def set_line_mode(self, mode, emit=False):
        self._line_mode = int(mode) % 3
        self._pen_straight = (self._line_mode == 0)   # 호환
        self._update_mode_button()
        if emit:
            self.lineModeChanged.emit(self._line_mode)
            self.penStraightChanged.emit(self._pen_straight)

    def _update_mode_button(self):
        b = getattr(self, "_tb_mode", None)
        if b is None:
            return
        b.setText(self._MODE_GLYPH[self._line_mode])
        b.setToolTip(f"선 종류: {self._MODE_NAME[self._line_mode]} (클릭해 전환)")
        b.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.14);color:#fff;border:none;"
            "border-radius:6px;padding:4px;font-weight:bold;}"
            "QPushButton:hover{background:rgba(255,255,255,0.28);}")
        b.style().unpolish(b); b.style().polish(b); b.update()

    # 260611-4: 외부(app)에서 본문과 동기화 — 직선 여부만 받던 옛 API 호환
    def set_pen_straight(self, on):
        self.set_line_mode(0 if on else 2)

    def _update_pen_buttons(self):
        pen_tool = (self._tool == "pen")
        for i, pb in enumerate(getattr(self, "_tb_pen_btns", [])):
            if i >= len(self._pens):
                continue
            pr = self._pens[i]
            col = pr.get("color", "#ff3030")
            sel = pen_tool and (i == self._pen_active)
            pb.setToolTip(f"{pr.get('name','선')} (굵기 {pr.get('width',3)})")
            border = "4px solid #ff7a00" if sel else "1px solid #888"   # 260611-5: 굵게·주황
            pb.setStyleSheet(
                f"QPushButton{{background:{col};color:#000;font-weight:bold;"
                f"border:{border};border-radius:6px;padding:2px;}}")

    def _update_tool_buttons(self):
        self._update_pen_buttons()
        erase_tool = (self._tool == "erase")
        for k, eb in enumerate(getattr(self, "_tb_erasers", [])):
            sel = erase_tool and (k == self._erase_active)
            bg = "rgba(40,160,80,0.95)" if sel else "rgba(255,255,255,0.12)"
            eb.setStyleSheet(
                f"QPushButton{{background:{bg};border:none;border-radius:6px;padding:4px;}}"
                "QPushButton:hover{background:rgba(255,255,255,0.25);}")
            eb.style().unpolish(eb); eb.style().polish(eb); eb.update()

    def _clear_drawings(self):
        self._strokes.pop(self._page, None)
        self._cur_stroke = None
        if getattr(self, "_draw_overlay", None) is not None:
            self._draw_overlay.update()

    def _on_apply_toggled(self, on):
        self._apply_on_exit = bool(on)
        self._update_apply_button()

    def _update_apply_button(self):
        b = getattr(self, "_tb_apply", None)
        if b is None:
            return
        on = self._apply_on_exit
        # 260611-84: hover 색도 상태를 반영(켜짐=초록) → 클릭 직후 커서가 위에 있어도 토글이 바로 보임
        base = "rgba(40,165,85,0.97)" if on else "rgba(255,255,255,0.12)"
        hover = "rgba(60,200,110,1.0)" if on else "rgba(255,255,255,0.28)"
        b.setText("본화면 적용 ✓" if on else "본화면 적용")
        b.setStyleSheet(
            f"QPushButton{{background:{base};color:#fff;border:none;border-radius:6px;"
            "padding:4px 10px;font-weight:bold;}"
            f"QPushButton:hover{{background:{hover};}}")
        b.style().unpolish(b); b.style().polish(b)
        b.repaint()       # 즉시 갱신(비동기 update 대신)

    def _page_norm_rect(self, page0):
        """페이지를 쪽맞춤으로 표시할 때 화면상 사각형(좌상x, 좌상y, w, h)."""
        sw, sh = max(1, self.width()), max(1, self.height())
        try:
            pg = self._doc.doc.load_page(page0)
            r = pg.rect
            pw, ph = float(r.width), float(r.height)
        except Exception:
            pw, ph = 595.0, 842.0
        if self._rotation_resolver:
            try:
                if int(self._rotation_resolver(str(self._path), page0)) % 360 in (90, 270):
                    pw, ph = ph, pw
            except Exception:
                pass
        scale = min(sw / pw, sh / ph)
        w, h = pw * scale, ph * scale
        return ((sw - w) / 2.0, (sh - h) / 2.0, w, h)

    def _normalized_strokes(self):
        """현재 파일의 화면 스트로크를 페이지 비율(0..1)로 변환 → {page0:[stroke]}."""
        out = {}
        for page0, strokes in self._strokes.items():
            x0, y0, w, h = self._page_norm_rect(page0)
            if w <= 0 or h <= 0:
                continue
            conv = []
            for st in strokes:
                pts = [[max(0.0, min(1.0, (p.x() - x0) / w)),
                        max(0.0, min(1.0, (p.y() - y0) / h))]
                       for p in st.get("points", [])]
                if len(pts) >= 2:
                    d = {"color": st.get("color", "#ff3030"),
                         "width": int(st.get("width", 3)),
                         "alpha": int(st.get("alpha", 100)),
                         "points": pts}
                    if st.get("hl"):     # 260611-4: 하이라이트 띠 높이도 정규화
                        d["hl"] = True
                        d["h"] = float(st.get("h", 0.0)) / h
                    conv.append(d)
            if conv:
                out[int(page0)] = conv
        return out

    def _set_pen(self, idx):
        self._tool = "pen"
        self._pen_active = max(0, min(len(self._pens) - 1, int(idx)))
        self.penChanged.emit(self._pen_active)
        if getattr(self, "_topbar", None) is not None:
            self._update_tool_buttons()

    def _set_eraser(self, k):
        """260609-20(I3): 일부분 지우기 도구 선택."""
        self._tool = "erase"
        self._erase_active = max(0, min(len(self._eraser_widths) - 1, int(k)))
        self._erase_width = self._eraser_widths[self._erase_active]
        if getattr(self, "_topbar", None) is not None:
            self._update_tool_buttons()

    def _erase_at(self, pos):
        """260611-6: 선 '중간'도 지워지도록 점이 아닌 선분(세그먼트) 거리로 판정.

        기존엔 스트로크의 꼭짓점만 검사해, 끝점 2개뿐인 직선/하이라이트는 중간을
        문질러도 안 지워졌다. 커서와 각 세그먼트의 최소 거리가 반경 이하면 제거,
        하이라이트 띠는 사각형 안에 들어오면 제거."""
        pg = self._strokes.get(self._page)
        if not pg:
            return
        r = max(8.0, float(self._erase_width))
        ex, ey = float(pos.x()), float(pos.y())
        split = self._page_is_split(); cur_half = self._split_half   # 260611-7

        def seg_dist(px, py, ax, ay, bx, by):
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            if L2 <= 1e-9:
                return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
            cx, cy = ax + t * dx, ay + t * dy
            return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

        def hit(st):
            if split and st.get("half", 0) != cur_half:   # 다른 반쪽 선은 보존
                return False
            pts = st.get("points", [])
            if len(pts) < 2:
                return False
            if st.get("hl"):
                hh = float(st.get("h", 0.0))
                p0, p1 = pts[0], pts[-1]; yc = p0.y()
                left, right = min(p0.x(), p1.x()), max(p0.x(), p1.x())
                top, bot = yc - hh / 2.0, yc + hh / 2.0
                return (left - r <= ex <= right + r and top - r <= ey <= bot + r)
            for i in range(1, len(pts)):
                if seg_dist(ex, ey, pts[i - 1].x(), pts[i - 1].y(),
                            pts[i].x(), pts[i].y()) <= r:
                    return True
            return False

        keep = [st for st in pg if not hit(st)]
        if len(keep) != len(pg):
            self._strokes[self._page] = keep
            if getattr(self, "_draw_overlay", None) is not None:
                self._draw_overlay.update()

    def set_pens(self, pens, active=None):
        if pens:
            self._pens = list(pens)
        if active is not None:
            self._pen_active = max(0, min(len(self._pens) - 1, int(active)))
        if getattr(self, "_topbar", None) is not None:
            self._update_pen_buttons()

    def set_eraser_widths(self, widths):
        """260611-2: 공유 지우개 면적 갱신."""
        if widths:
            self._eraser_widths = list(widths)

    def set_highlight_alpha(self, opacity):
        """260611-2: 공유 하이라이트 불투명도 갱신(발표 하이라이트 렌더용)."""
        self._highlight_alpha = int(opacity)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "_draw_overlay", None) is not None:
            self._draw_overlay.setGeometry(0, 0, self.width(), self.height())
        tp = getattr(self, "_thumb_panel", None)
        if tp is not None and tp.isVisible():
            tp.setGeometry(0, 0, tp.width(), self.height())
        self._position_topbar()
        self._render()
        self._update_hint()
        if getattr(self, "_topbar", None) is not None and self._topbar.isVisible():
            self._update_topbar()

    # ===== 260611-19: 발표시간(프레젠테이션 타이머) =====
    def _on_timer_toggle(self, on):
        if on:
            self._timer_ctl.arm_standby()       # 준비내용 표시(녹화는 준비 이후 시작)
            self._stop_timer_qtimer()
        else:
            # 260611-28: 카운트 중(또는 초과)에 끄려 하면 확인
            if self._timer_ctl.state in (self._timer_ctl.RUNNING, self._timer_ctl.OVERTIME):
                from PyQt6.QtWidgets import QMessageBox
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle("발표시간 종료")
                box.setText("발표시간을 끌까요?\n(녹화 중이면 저장됩니다)")
                box.addButton("끄기", QMessageBox.ButtonRole.AcceptRole)
                b_no = box.addButton("계속", QMessageBox.ButtonRole.RejectRole)
                box.setDefaultButton(b_no)
                box.exec()
                if box.clickedButton() is b_no:
                    self._tb_timer.blockSignals(True)
                    self._tb_timer.setChecked(True)     # 유지
                    self._tb_timer.blockSignals(False)
                    return
            self._timer_ctl.off()
            self._stop_timer_qtimer()
            self._set_stop_checked(False)       # 중지 상태도 해제
            try:
                self._tone.stop_all()
            except Exception:
                pass
            self.recordStopRequested.emit()     # 260611-28: 시계 종료 시 녹화 저장
        self.update()

    def _set_stop_checked(self, on):
        b = getattr(self, "_tb_timer_stop", None)
        if b is None:
            return
        b.blockSignals(True)
        b.setChecked(bool(on))
        b.blockSignals(False)
        if not on:
            self._stop_blink_timer.stop()
            self._stop_blink_on = False
            b.setStyleSheet(self._tb_timer_stop_css)

    def _on_timer_stop_toggle(self, on):
        """260611-22: 시계 중지(멈춤)/재개. 중지 중 0.5초 적색 블링크."""
        if on:
            self._timer_ctl.pause()
            if self._timer_ctl.is_paused():
                self._stop_blink_on = True
                self._stop_blink_timer.start()
                self._toggle_stop_blink()
            else:
                # 작동 중이 아니면 중지 의미 없음 → 체크 해제
                self._set_stop_checked(False)
        else:
            self._timer_ctl.resume()
            self._stop_blink_timer.stop()
            self._stop_blink_on = False
            self._tb_timer_stop.setStyleSheet(self._tb_timer_stop_css)
        self.update()

    def _toggle_stop_blink(self):
        self._stop_blink_on = not self._stop_blink_on
        if self._stop_blink_on:
            self._tb_timer_stop.setStyleSheet(
                self._tb_timer_stop_css
                + "QPushButton{background:rgba(220,40,40,0.95);}")
        else:
            self._tb_timer_stop.setStyleSheet(self._tb_timer_stop_css)

    def _start_timer_qtimer(self):
        if not self._timer_qtimer.isActive():
            self._timer_qtimer.start()

    def _stop_timer_qtimer(self):
        if self._timer_qtimer.isActive():
            self._timer_qtimer.stop()

    def _timer_tick(self):
        res = self._timer_ctl.tick()
        if not self._alarm_muted:               # 260611-22: 전체 알람 끄기면 소리 차단
            for snd, vol in res.get("fired", []):
                try:
                    self._tone.play(snd, vol)
                except Exception:
                    pass
        self.update()

    def set_timer_config(self, cfg):
        from viewer.widgets.pres_timer import merge_timer_cfg
        self._timer_cfg = merge_timer_cfg(cfg)
        self._timer_ctl.set_config(self._timer_cfg)
        self.update()

    def set_overlap_pct(self, pct):
        """260611-25: 상하 분할 중앙 겹침(%) 즉시 반영."""
        self._overlap_frac = max(0.0, min(0.4, float(pct) / 100.0))
        self._render()

    def _on_overlap_spin(self, val):
        """260611-26: 메뉴의 '중앙겹침' 입력 → 즉시 반영 + 영속."""
        self.set_overlap_pct(val)
        self.overlapChanged.emit(int(val))

    def set_topbar_height(self, px):
        """260611-25: 상단 띠 높이(px) 즉시 반영."""
        self._topbar_h = max(40, int(px))
        try:
            self._position_topbar()
        except Exception:
            pass

    def _open_timer_settings(self):
        from viewer.widgets.pres_timer import open_settings_dialog
        new_cfg = open_settings_dialog(self, self._timer_cfg)
        if new_cfg is not None:
            self.set_timer_config(new_cfg)
            self.timerConfigChanged.emit(new_cfg)

    def _paint_timer(self, p):
        st = self._timer_ctl.state
        if st == self._timer_ctl.OFF or self._timer_hidden:   # 260611-22: 시계 숨기기
            return
        W, H = self.width(), self.height()
        if st == self._timer_ctl.STANDBY:
            self._paint_standby(p, W, H)
        else:
            txt = self._timer_ctl.display()
            if txt:
                self._paint_time_hud(p, W, H, txt)

    def _paint_standby(self, p, W, H):
        from PyQt6.QtCore import QRectF, QRect
        from PyQt6.QtGui import QFont, QFontMetrics, QPen, QPainterPath
        sb = self._timer_cfg["standby"]
        bw = max(40, int(W * float(sb.get("w_frac", 0.5))))
        bh = max(40, int(H * float(sb.get("h_frac", 0.5))))
        x = (W - bw) // 2
        y = (H - bh) // 2
        alpha_pct = int(sb.get("bg_alpha", 50))
        is_round = sb.get("border") == "round"
        rr = min(bw, bh) * 0.12
        bg = QColor(sb.get("bg_color", "#000000"))
        bg.setAlpha(int(255 * alpha_pct / 100))
        p.save()
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(bg)
        if is_round:
            p.drawRoundedRect(QRectF(x, y, bw, bh), rr, rr)
        else:
            p.drawRect(QRect(x, y, bw, bh))
        # 260611-22: 첨부 배경 그림 — 박스 크기에 cover-crop(상하 또는 좌우 균등 크롭),
        #   박스 투명도를 그림 투명도로 적용.
        img_b64 = sb.get("image", "")
        if img_b64:
            from viewer.widgets.pres_timer import b64_to_pix
            pm = b64_to_pix(img_b64)
            if pm is not None and not pm.isNull():
                scaled = pm.scaled(bw, bh, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
                sx = max(0, (scaled.width() - bw) // 2)
                sy = max(0, (scaled.height() - bh) // 2)
                p.save()
                path = QPainterPath()
                if is_round:
                    path.addRoundedRect(QRectF(x, y, bw, bh), rr, rr)
                else:
                    path.addRect(QRectF(x, y, bw, bh))
                p.setClipPath(path)
                p.setOpacity(max(0.0, min(1.0, alpha_pct / 100.0)))
                p.drawPixmap(QRect(x, y, bw, bh), scaled, QRect(sx, sy, bw, bh))
                p.restore()
        lines = sb.get("lines") or []
        fonts = []
        total = 0
        for ln in lines:
            f = QFont(ln.get("font", "맑은 고딕"), int(ln.get("size", 40)))
            fm = QFontMetrics(f)
            fonts.append((f, fm.height(), ln.get("text", "")))
            total += fm.height()
        cy = y + (bh - total) // 2
        for f, lh, text in fonts:
            p.setFont(f)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRect(x, cy, bw, lh), Qt.AlignmentFlag.AlignCenter, text)
            cy += lh
        p.restore()

    def _paint_time_hud(self, p, W, H, txt):
        from PyQt6.QtGui import QFont, QFontMetrics, QPen, QPainterPath
        cfg = self._timer_cfg["font"]
        size = int(cfg.get("size", 0)) or max(16, H // 15)
        f = QFont(cfg.get("family", "돋움"), size)
        f.setBold(bool(cfg.get("bold", True)))
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(txt)
        th = fm.height()
        pad_pct = int(cfg.get("bg_pad_pct", 10))
        padx = int(tw * pad_pct / 100)
        pady = int(th * pad_pct / 100)
        box_w = tw + 2 * padx
        box_h = th + 2 * pady
        margin = int(self._timer_cfg.get("margin", 24))
        if self._timer_cfg.get("pos", "top-right") == "top-left":
            bx = margin
        else:
            bx = W - margin - box_w
        by = margin
        p.save()
        if cfg.get("bg", "none") == "color":
            bg = QColor(cfg.get("bg_color", "#ffffff"))
            bg.setAlpha(int(255 * int(cfg.get("bg_alpha", 50)) / 100))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(bx, by, box_w, box_h, 8, 8)
        col = QColor("#ffffff") if cfg.get("color", "auto") == "auto" else QColor(cfg.get("color"))
        path = QPainterPath()
        path.addText(bx + padx, by + pady + fm.ascent(), f, txt)
        p.setPen(QPen(QColor(0, 0, 0, 180), max(2, size // 16)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)               # 외곽선(가독성)
        p.fillPath(path, col)
        p.restore()

    def closeEvent(self, e):
        # 260611-22: 시계 작동 중이면 종료 전 확인
        try:
            if self._timer_ctl.state != self._timer_ctl.OFF and not getattr(self, "_timer_force_close", False):
                from PyQt6.QtWidgets import QMessageBox
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle("전체화면 종료")
                box.setText("발표시간이 작동 중입니다. 정말 전체화면을 나갈까요?")
                box.addButton("나가기", QMessageBox.ButtonRole.AcceptRole)
                b_no = box.addButton("계속", QMessageBox.ButtonRole.RejectRole)
                box.setDefaultButton(b_no)
                box.exec()
                if box.clickedButton() is b_no:
                    e.ignore()
                    return
        except Exception:
            pass
        # 260611-19: 타이머/소리 정리
        try:
            self._timer_ctl.off()
            self._stop_timer_qtimer()
            self._stop_blink_timer.stop()
            self._tone.stop_all()
        except Exception:
            pass
        # 260611-28: 전체화면 종료 시 녹화 중이면 저장(중지)
        try:
            self.recordStopRequested.emit()
        except Exception:
            pass
        # 260609-25(I4): 종료 시 '본화면 적용' 켜져 있고 그린 선이 있으면 앱에 전달
        try:
            if self._apply_on_exit:
                norm = self._normalized_strokes()
                if norm:
                    self.applyDrawingsRequested.emit(norm, str(self._path))
        except Exception:
            pass
        try:
            self.closed.emit(self._page)
        except Exception:
            pass
        try:
            self._doc.close()
        except Exception:
            pass
        super().closeEvent(e)
