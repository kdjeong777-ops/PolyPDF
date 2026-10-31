"""테마 대응 단색(라인) 아이콘 — 화면 디자인 통일용 (260616-14).

규칙(작업계획서 '화면 디자인 작업 계획서.md' 참조):
- 모든 아이콘은 단색 라인 스타일로 통일.
- **다크 모드 = 밝은 회색(흰색 계열)**, 라이트 모드 = 짙은 회색.
- 리소스 PNG 의존 없이 QPainter 로 그려, 어떤 테마/배율에서도 또렷하게.

사용: `from viewer.widgets.icons import themed_icon` → `btn.setIcon(themed_icon("globe"))`.
새 아이콘은 `_DRAW` 에 그리기 함수를 추가하면 곧바로 themed_icon 으로 쓸 수 있다.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPolygonF


def fg_color(dark: bool | None = None) -> str:
    """현재(또는 지정) 테마의 아이콘 전경색."""
    if dark is None:
        try:
            from viewer import theme
            dark = theme.is_dark()
        except Exception:
            dark = False
    return "#e8e8e8" if dark else "#444444"


# --- 개별 그리기(16x16 캔버스, p=QPainter, c=QColor) -----------------------

def _search(p, c):
    p.setPen(QPen(c, 1.7))
    p.drawEllipse(QPointF(6.3, 6.3), 4.0, 4.0)
    p.drawLine(QPointF(9.4, 9.4), QPointF(14.0, 14.0))


def _globe(p, c):
    p.setPen(QPen(c, 1.4))
    p.drawEllipse(QPointF(8, 8), 6.2, 6.2)
    p.drawEllipse(QPointF(8, 8), 2.6, 6.2)      # 세로 자오선
    p.drawLine(QPointF(1.9, 8), QPointF(14.1, 8))
    p.drawLine(QPointF(3.0, 4.4), QPointF(13.0, 4.4))
    p.drawLine(QPointF(3.0, 11.6), QPointF(13.0, 11.6))


def _close(p, c):
    p.setPen(QPen(c, 1.8))
    p.drawLine(QPointF(4, 4), QPointF(12, 12))
    p.drawLine(QPointF(12, 4), QPointF(4, 12))


def _chevron_up(p, c):
    p.setPen(QPen(c, 1.8))
    p.drawLine(QPointF(4, 10), QPointF(8, 5.5))
    p.drawLine(QPointF(8, 5.5), QPointF(12, 10))


def _chevron_down(p, c):
    p.setPen(QPen(c, 1.8))
    p.drawLine(QPointF(4, 6), QPointF(8, 10.5))
    p.drawLine(QPointF(8, 10.5), QPointF(12, 6))


def _chevron_left(p, c):
    p.setPen(QPen(c, 1.8))
    p.drawLine(QPointF(10, 4), QPointF(5.5, 8))
    p.drawLine(QPointF(5.5, 8), QPointF(10, 12))


def _chevron_right(p, c):
    p.setPen(QPen(c, 1.8))
    p.drawLine(QPointF(6, 4), QPointF(10.5, 8))
    p.drawLine(QPointF(10.5, 8), QPointF(6, 12))


def _star(p, c):
    p.setPen(QPen(c, 1.3))
    import math
    pts = []
    cx, cy = 8.0, 8.4
    for k in range(10):
        r = 6.2 if k % 2 == 0 else 2.6
        a = -math.pi / 2 + k * math.pi / 5
        pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
    p.drawPolygon(QPolygonF(pts))


def _bookmark(p, c):
    p.setPen(QPen(c, 1.5))
    poly = QPolygonF([QPointF(4.5, 2.5), QPointF(11.5, 2.5),
                      QPointF(11.5, 13.5), QPointF(8, 10.3),
                      QPointF(4.5, 13.5)])
    p.drawPolygon(poly)


def _refresh(p, c):
    p.setPen(QPen(c, 1.5))
    p.drawArc(QRectF(3, 3, 10, 10), 60 * 16, 250 * 16)
    p.drawLine(QPointF(12.5, 3.5), QPointF(12.8, 7.0))
    p.drawLine(QPointF(12.8, 7.0), QPointF(9.4, 6.4))


def _folder(p, c):
    """260901-2: 책갈피 트리 폴더 그룹 행용 — 탭 달린 폴더 윤곽(디자인 §4.4: 1.4~1.8px 라인)."""
    p.setPen(QPen(c, 1.5))
    poly = QPolygonF([QPointF(2.2, 12.8), QPointF(2.2, 4.0), QPointF(6.3, 4.0),
                      QPointF(7.6, 5.6), QPointF(13.8, 5.6), QPointF(13.8, 12.8)])
    p.drawPolygon(poly)


def _file(p, c):
    """260902-5: 책갈피 트리 파일 행용 — 모서리 접힌 문서 윤곽(디자인 §4.4)."""
    p.setPen(QPen(c, 1.5))
    poly = QPolygonF([QPointF(4.0, 2.2), QPointF(9.6, 2.2), QPointF(12.2, 4.8),
                      QPointF(12.2, 13.8), QPointF(4.0, 13.8)])
    p.drawPolygon(poly)
    p.drawLine(QPointF(9.6, 2.2), QPointF(9.6, 4.8))
    p.drawLine(QPointF(9.6, 4.8), QPointF(12.2, 4.8))


# 261008: 편집모드 도형 버튼(직사각형/둥근 사각형/원) — 폰트 글리프(▭❒◯)는 크기·모양이
#   제각각이라(❒ 는 그림자 상자) 그린다. 직사각형·둥근 사각형은 같은 크기(모서리만 다름).
def _shape_rect(p, c):
    p.setPen(QPen(c, 1.6))
    p.drawRect(QRectF(0.8, 3.0, 14.4, 10.0))


def _shape_round(p, c):
    p.setPen(QPen(c, 1.6))
    p.drawRoundedRect(QRectF(0.8, 3.0, 14.4, 10.0), 3.2, 3.2)


def _shape_circle(p, c):
    p.setPen(QPen(c, 1.6))
    p.drawEllipse(QPointF(8, 8), 6.3, 6.3)


def _crop(p, c):
    """261010-7: 크롭 — 네모(왼·위 변) + 대각선 + 오른쪽 아래 재단 표시(오른 변·아래 변이 모서리 밖으로 나간다)."""
    p.setPen(QPen(c, 1.6))
    p.drawLine(QPointF(3, 1.5), QPointF(3, 12))       # 왼 변
    p.drawLine(QPointF(3, 3), QPointF(13, 3))         # 위 변
    p.drawLine(QPointF(13, 3), QPointF(13, 14.5))     # 오른 변 — 아래로 나간다
    p.drawLine(QPointF(1.5, 13), QPointF(14.5, 13))   # 아래 변 — 오른쪽으로 나간다
    p.drawLine(QPointF(3, 13), QPointF(13, 3))        # 대각선


def _sign(p, c):
    """261010-22(보안 SOT §3): 전자서명 — 아래 서명 줄 + 비스듬한 펜 + 줄 위 짧은 획."""
    p.setPen(QPen(c, 1.6))
    p.drawLine(QPointF(1.5, 14.5), QPointF(14.5, 14.5))   # 서명 줄
    p.drawLine(QPointF(7, 10), QPointF(13.5, 3.5))        # 펜대
    p.drawLine(QPointF(5.5, 11.5), QPointF(7, 10))        # 펜촉
    p.drawLine(QPointF(9.5, 6.5), QPointF(11.5, 8.5))     # 펜 손잡이 경계
    p.drawLine(QPointF(1.5, 12), QPointF(3.5, 10))        # 서명 획
    p.drawLine(QPointF(3.5, 10), QPointF(4.5, 12))


def _view_tree(p, c):
    """261011-4(디자인 SOT §2.8.5): 책갈피창 '트리' 보기 — 위 마디에서 세로 줄이 내려가 두 가지로 갈린다."""
    p.setPen(QPen(c, 1.5))
    p.drawRect(QRectF(2.5, 2.2, 4.0, 3.2))                 # 윗 마디(폴더)
    p.drawLine(QPointF(4.5, 5.4), QPointF(4.5, 12.0))      # 줄기
    p.drawLine(QPointF(4.5, 8.0), QPointF(8.0, 8.0))       # 가지 1
    p.drawLine(QPointF(4.5, 12.0), QPointF(8.0, 12.0))     # 가지 2
    p.drawLine(QPointF(9.5, 8.0), QPointF(13.8, 8.0))      # 아래 항목 1
    p.drawLine(QPointF(9.5, 12.0), QPointF(13.8, 12.0))    # 아래 항목 2


def _view_single(p, c):
    """261011-4(디자인 SOT §2.8.5): 책갈피창 '단일' 보기 — 같은 높이의 줄 넷(점 + 줄)."""
    p.setPen(QPen(c, 1.5))
    for y in (3.0, 6.3, 9.6, 12.9):
        p.drawPoint(QPointF(3.0, y))
        p.drawLine(QPointF(5.5, y), QPointF(13.8, y))


_DRAW = {
    "search": _search, "globe": _globe, "close": _close,
    "chevron_up": _chevron_up, "chevron_down": _chevron_down,
    "chevron_left": _chevron_left, "chevron_right": _chevron_right,
    "star": _star, "bookmark": _bookmark, "refresh": _refresh,
    "folder": _folder, "file": _file,
    "shape_rect": _shape_rect, "shape_round": _shape_round, "shape_circle": _shape_circle,
    "crop": _crop, "sign": _sign,
    "view_tree": _view_tree, "view_single": _view_single,
}


# --- 색 아이콘(채움) — 본문 도구 줄의 읽기 ▶/■·캡처 카메라 (261025-10, 디자인 SOT §4.5) ----------
#   글리프 ▶·■ 는 글꼴 기준선 탓에 단추 가운데보다 아래로 처졌다 — 16x16 캔버스 가운데에 그린다.
#   다크는 같은 색 계열을 밝게(어두운 바탕에서 또렷하게). 값은 이 표 하나.
ACCENT = {"play": {False: "#1565c0", True: "#5aa0f0"},
          "stop": {False: "#c0392b", True: "#e05545"}}
ACCENT["camera"] = ACCENT["play"]


def _play(p, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(QPolygonF([QPointF(4.0, 2.0), QPointF(4.0, 14.0), QPointF(14.0, 8.0)]))


def _stop(p, c):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(3.0, 3.0, 10.0, 10.0), 1.2, 1.2)


def _camera(p, c):
    """카메라 몸체(위 가운데 뷰파인더 턱) + 렌즈 고리 + 오른쪽 위 플래시 점 — 렌즈·플래시는 뚫어 바탕이 보인다."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(0.5, 4.0, 15.0, 10.5), 2.0, 2.0)
    p.drawPolygon(QPolygonF([QPointF(4.6, 4.5), QPointF(5.8, 1.8), QPointF(10.2, 1.8), QPointF(11.4, 4.5)]))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.drawEllipse(QPointF(8.0, 9.2), 3.9, 3.9)
    p.drawEllipse(QPointF(13.1, 6.4), 0.9, 0.9)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    p.drawEllipse(QPointF(8.0, 9.2), 2.5, 2.5)


# 261031-12(디자인 SOT §2.9.5·§4.5, 사용자 결정 '시안 C'): 즐겨찾기 탭 — 폴더·파일·검색어. 파랑은 ▶·카메라와 같은 값.
FAV_YELLOW = {False: ("#f0b429", "#ffcf4a"), True: ("#d99a12", "#f5bd2e")}     # 폴더 뒤판·앞판
FAV_FILE_FOLD = {False: "#9cc3f0", True: "#b8d6fa"}                              # 파일 접힌 모서리
FAV_ICON_PX = 13                                                                 # 즐겨찾기 탭 단추 아이콘 — 단추 폭이 늘지 않게 작게
for _k in ("fav_folder", "fav_file", "fav_search"):
    ACCENT[_k] = ACCENT["play"]


def _fav_folder(p, c, dark=False):
    """노란 폴더(탭·뒤판·앞판) + 오른쪽 아래 작은 파란 면(사용자가 보낸 그림의 파란 면)."""
    back, front = FAV_YELLOW[bool(dark)]
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(back))
    p.drawRoundedRect(QRectF(1.0, 2.5, 6.0, 3.0), 1.0, 1.0)
    p.drawRoundedRect(QRectF(1.0, 4.0, 14.0, 10.5), 1.4, 1.4)
    p.setBrush(QColor(front))
    p.drawRoundedRect(QRectF(1.0, 6.2, 14.0, 8.3), 1.4, 1.4)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(9.0, 7.6, 4.6, 5.6), 1.2, 1.2)


def _fav_file(p, c, dark=False):
    """파란 종이 — 접힌 모서리는 밝은 파랑, 흰 줄 셋."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(QPolygonF([QPointF(3, 1), QPointF(10, 1), QPointF(13.5, 4.5), QPointF(13.5, 15), QPointF(3, 15)]))
    p.setBrush(QColor(FAV_FILE_FOLD[bool(dark)]))
    p.drawPolygon(QPolygonF([QPointF(10, 1), QPointF(13.5, 4.5), QPointF(10, 4.5)]))
    p.setBrush(QColor("#ffffff" if not dark else "#f2f2f2"))
    for y in (7.0, 9.6, 12.2):
        p.drawRect(QRectF(5.0, y, 6.4, 1.2))


def _fav_search(p, c, dark=False):
    """파란 돋보기 — 굵은 고리 + 둥근 손잡이."""
    p.setPen(QPen(c, 2.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(6.6, 6.6), 4.4, 4.4)
    p.setPen(QPen(c, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(10.0, 10.0), QPointF(14.2, 14.2))


# 261031-13(디자인 SOT §2.9.7·§4.5, 사용자 결정 '열린 폴더+↑ / 플로피 / 문+→'): 파일 탭 그림
OK_GREEN = {False: "#2e9b4f", True: "#4cc06f"}       # 새 창 ⊕·인쇄 표시등
EXIT_RED = ACCENT["stop"]                             # 종료 → (정지 ■ 와 같은 빨강)
FILE_GRAY = {False: "#5f6b78", True: "#c4ccd6"}      # 인쇄 몸체·문 테
PAPER_WHITE = {False: "#ffffff", True: "#f2f2f2"}
for _k in ("open", "new_window", "save", "print", "exit"):
    ACCENT[_k] = ACCENT["play"]


def _open(p, c, dark=False):
    """열린 노란 폴더(앞판이 비스듬히) + 파란 ↑."""
    back, front = FAV_YELLOW[bool(dark)]
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(back))
    p.drawRoundedRect(QRectF(1.0, 2.5, 6.0, 3.0), 1.0, 1.0)
    p.drawRoundedRect(QRectF(1.0, 4.0, 12.5, 10.5), 1.4, 1.4)
    p.setBrush(QColor(front))
    p.drawPolygon(QPolygonF([QPointF(3.6, 7.0), QPointF(15.5, 7.0), QPointF(13.0, 14.5), QPointF(1.0, 14.5)]))
    p.setPen(QPen(c, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(11.5, 6.5), QPointF(11.5, 1.2))
    p.drawLine(QPointF(11.5, 1.2), QPointF(9.2, 3.5))
    p.drawLine(QPointF(11.5, 1.2), QPointF(13.8, 3.5))


def _new_window(p, c, dark=False):
    """흰 창 + 파란 제목줄 + 오른쪽 아래 초록 ⊕."""
    d = bool(dark)
    p.setPen(QPen(c, 1.2))
    p.setBrush(QColor(PAPER_WHITE[d]))
    p.drawRoundedRect(QRectF(1.0, 2.0, 12.0, 10.5), 1.2, 1.2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(1.0, 2.0, 12.0, 3.0), 1.2, 1.2)
    p.setBrush(QColor(OK_GREEN[d]))
    p.drawEllipse(QPointF(12.3, 12.3), 3.5, 3.5)
    p.setPen(QPen(QColor("#ffffff"), 1.5))
    p.drawLine(QPointF(12.3, 10.4), QPointF(12.3, 14.2))
    p.drawLine(QPointF(10.4, 12.3), QPointF(14.2, 12.3))


def _save(p, c, dark=False):
    """파란 플로피 — 흰 라벨(파란 셔터 창)·아래 흰 칸."""
    w = QColor(PAPER_WHITE[bool(dark)])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(QPolygonF([QPointF(1.5, 1.5), QPointF(12.5, 1.5), QPointF(14.5, 3.5), QPointF(14.5, 14.5), QPointF(1.5, 14.5)]))
    p.setBrush(w)
    p.drawRect(QRectF(4.0, 1.5, 7.0, 4.5))
    p.setBrush(c)
    p.drawRect(QRectF(8.4, 2.3, 1.6, 2.9))
    p.setBrush(w)
    p.drawRoundedRect(QRectF(3.5, 8.5, 9.0, 6.0), 0.8, 0.8)


def _print(p, c, dark=False):
    """회색 프린터 + 흰 종이(위·아래, 파란 글 줄) + 초록 표시등."""
    d = bool(dark)
    g, w = QColor(FILE_GRAY[d]), QColor(PAPER_WHITE[d])
    p.setPen(QPen(g, 1.0)); p.setBrush(w)
    p.drawRect(QRectF(4.0, 1.0, 8.0, 4.5))
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(g)
    p.drawRoundedRect(QRectF(1.0, 5.0, 14.0, 7.0), 1.5, 1.5)
    p.setPen(QPen(g, 1.0)); p.setBrush(w)
    p.drawRect(QRectF(4.0, 9.5, 8.0, 5.5))
    p.setPen(QPen(c, 1.0))
    p.drawLine(QPointF(5.5, 11.5), QPointF(10.5, 11.5))
    p.drawLine(QPointF(5.5, 13.3), QPointF(9.0, 13.3))
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(OK_GREEN[d]))
    p.drawEllipse(QPointF(12.6, 7.3), 0.9, 0.9)


def _exit(p, c, dark=False):
    """회색 문 테 + 밖으로 나가는 빨간 →."""
    d = bool(dark)
    p.setPen(QPen(QColor(FILE_GRAY[d]), 1.4)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(8.5, 4.0), QPointF(8.5, 1.5), QPointF(1.5, 1.5), QPointF(1.5, 14.5),
                              QPointF(8.5, 14.5), QPointF(8.5, 12.0)]))
    p.setPen(QPen(QColor(EXIT_RED[d]), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(5.0, 8.0), QPointF(14.5, 8.0))
    p.drawLine(QPointF(14.5, 8.0), QPointF(11.8, 5.3))
    p.drawLine(QPointF(14.5, 8.0), QPointF(11.8, 10.7))


_COLOR_DRAW = {"play": _play, "stop": _stop, "camera": _camera,
               "fav_folder": _fav_folder, "fav_file": _fav_file, "fav_search": _fav_search,
               "open": _open, "new_window": _new_window, "save": _save, "print": _print, "exit": _exit}
_COLOR_NEEDS_DARK = {"fav_folder", "fav_file", "fav_search", "open", "new_window", "save", "print", "exit"}   # 두 색 이상 — 테마도 넘긴다

# 261025-10(디자인 SOT §2.7): 글자 + 메뉴 단추의 드롭다운 표시는 **Qt 메뉴 화살표 하나**(오른쪽 아래) — 글자에 ▾ 를 붙이지 않는다.
#   글자가 화살표에 붙지 않게 오른쪽 안쪽 여백만 준다(바탕·테두리는 기본 스타일 그대로).
DROP_PAD_RIGHT = 10


def drop_button(btn) -> None:
    """메뉴가 달린 글자 단추(QToolButton) — 화살표 자리만큼 오른쪽 여백."""
    btn.setStyleSheet("QToolButton{padding-right:%dpx;}" % DROP_PAD_RIGHT)


def corner_arrow_rect(widget):
    """Qt 가 메뉴 단추(InstantPopup)에 그리는 작은 ▾ 의 자리 — QCommonStyle 의 CC_ToolButton 계산 그대로."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtWidgets import QStyle
    mbi = widget.style().pixelMetric(QStyle.PixelMetric.PM_MenuButtonIndicator, None, widget)
    r = widget.rect()
    return QRect(r.right() + 5 - mbi, r.height() - mbi + 4, mbi - 6, mbi - 6)


def _make_corner_combo():
    from PyQt6.QtWidgets import QComboBox, QStyle, QStyleOption, QStyleOptionComboBox, QStylePainter

    class CornerArrowComboBox(QComboBox):
        """261025-10(디자인 SOT §2.7, 사용자 지시): 콤보의 ▾ 를 드롭다운 단추와 같은 모양으로 — 오른쪽 아래 작은 화살표.
        Fusion 의 큰 화살표(SC_ComboBoxArrow)는 빼고 그리고, 메뉴 단추와 같은 자리·같은 그림(PE_IndicatorArrowDown)을 얹는다."""

        def paintEvent(self, _ev):
            p = QStylePainter(self)
            opt = QStyleOptionComboBox()
            self.initStyleOption(opt)
            opt.subControls &= ~QStyle.SubControl.SC_ComboBoxArrow
            p.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
            p.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt)
            a = QStyleOption()
            a.initFrom(self)
            a.rect = corner_arrow_rect(self)
            p.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorArrowDown, a)

    return CornerArrowComboBox


CornerArrowComboBox = _make_corner_combo()


def color_icon(name: str, dark: bool | None = None, size: int = 16, *, dpr: float = 2.0) -> QIcon:
    """이름으로 테마별 색 아이콘(채움) — `ACCENT` 표의 색. 없는 이름이면 빈 아이콘."""
    fn = _COLOR_DRAW.get(name)
    if fn is None:
        return QIcon()
    if dark is None:
        try:
            from viewer import theme
            dark = theme.is_dark()
        except Exception:
            dark = False
    c = QColor(ACCENT[name][bool(dark)])
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.scale(size / 16.0, size / 16.0)
        if name in _COLOR_NEEDS_DARK:
            fn(p, c, bool(dark))
        else:
            fn(p, c)
    finally:
        p.end()
    return QIcon(pm)


def themed_icon(name: str, dark: bool | None = None, size: int = 16, *,
                pad_right: int = 0, dpr: float = 1.0) -> QIcon:
    """이름으로 테마색 단색 아이콘 생성. 없는 이름이면 빈 아이콘.

    pad_right: 오른쪽에 둘 빈 폭(px) — 가운데 정렬 버튼에서 그림을 왼쪽으로 비킬 때
    (도형 버튼이 ▾ 풀다운 영역과 붙지 않게). dpr: 고해상도 렌더 배율."""
    fn = _DRAW.get(name)
    if fn is None:
        return QIcon()
    c = QColor(fg_color(dark))
    pm = QPixmap(int((size + pad_right) * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if size != 16:
            p.scale(size / 16.0, size / 16.0)
        fn(p, c)
    finally:
        p.end()
    return QIcon(pm)
