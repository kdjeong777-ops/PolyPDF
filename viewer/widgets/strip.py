"""미니창 스트립 - 가로 스크롤 썸네일 카드 리스트.

v1.5.0:
 - 카드의 dedup 키 (file_path, page_index)
 - 썸네일은 클릭 당시 표시 페이지 (1페이지 고정 X)
 - itemActivated 시그널 = (path, page_index) 두 인자
 - 헤더에 추가 위젯 삽입 슬롯 (extra_widgets)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap, QAction, QFontMetrics, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QMessageBox,
)

import fitz


def _abbreviate(text: str, width_chars: int = 18) -> str:
    if len(text) <= width_chars * 2:
        return text
    return "..." + text[-(width_chars * 2 - 3):]


# v1.6.0 P2: 미니카드 썸네일 LRU 캐시 (가장 큰 성능 이득).
#   같은 (path, page) 조합이면 PyMuPDF 호출 없이 캐시된 QPixmap 재사용.
from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=512)
def _render_pdf_page_thumb_cached(pdf_path: str, page_index: int, w: int, h: int) -> QPixmap:
    try:
        doc = fitz.open(pdf_path)
        try:
            n = doc.page_count
            pi = max(0, min(n - 1, page_index))
            page = doc.load_page(pi)
            mat = fitz.Matrix(0.5, 0.5)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            qimg = QImage(pix.samples, pix.width, pix.height,
                          pix.width * 3, QImage.Format.Format_RGB888).copy()
            return QPixmap.fromImage(qimg).scaled(
                w, h, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        finally:
            doc.close()
    except Exception:
        p = QPixmap(w, h); p.fill(QColor("#ddd"))
        return p


def _render_pdf_page_thumb(pdf_path: str, page_index: int = 0, w: int = 96, h: int = 128) -> QPixmap:
    """v1.5.0: 임의 페이지 썸네일. v1.6.0: LRU 캐시(maxsize=512)."""
    return _render_pdf_page_thumb_cached(pdf_path, int(page_index), int(w), int(h))


@_lru_cache(maxsize=256)
def _render_image_thumb_cached(image_path: str, w: int, h: int) -> QPixmap:
    img = QImage(image_path)
    if img.isNull():
        pix = QPixmap(w, h); pix.fill(QColor("#ddd"))
        return pix
    return QPixmap.fromImage(img).scaled(
        w, h, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _render_image_thumb(image_path: str, w: int = 96, h: int = 128) -> QPixmap:
    """v1.6.0: LRU 캐시."""
    return _render_image_thumb_cached(image_path, int(w), int(h))


def make_card_pixmap(thumb: QPixmap, label: str, page_label: str = "",
                     w: int = 110, h: int = 180) -> QPixmap:
    """260606-23: [상단 파일명 2줄 띠] + [순수 썸네일](파일명 미표시).
    번호는 리스트 아이템 텍스트(카드 외부, 하단)로 표시."""
    # 260606-14: 다크모드면 카드 배경·글자색을 어둡게
    from viewer import theme as _theme
    dark = _theme.is_dark()
    card_bg = QColor(40, 40, 43) if dark else QColor("white")
    name_bg = QColor(54, 54, 58) if dark else QColor(244, 244, 246)
    text_col = QColor("#e6e6e6") if dark else QColor("#222")
    border_col = QColor("#555") if dark else QColor("#ccc")
    page_col = QColor("#aaa") if dark else QColor("#777")
    pix = QPixmap(w, h)
    pix.fill(card_bg)
    p = QPainter(pix)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)

    fm = QFontMetrics(p.font())
    line_h = fm.height()
    text_h = line_h * 2 + 6     # 260606-23: 상단 파일명 2줄 띠

    # 상단 파일명 띠 배경 + 구분선(별도의 줄로 분리)
    p.fillRect(0, 0, w, text_h, name_bg)

    cpl = 14   # 한 줄 글자 수 (한글 기준 대략값)
    if len(label) <= cpl:
        lines = [label, ""]
    elif len(label) <= cpl * 2:
        lines = [label[:cpl], label[cpl:]]
    else:                       # 2줄: 앞 cpl + (...뒤)
        tail_len = max(0, cpl - 3)
        lines = [label[:cpl], ("..." + label[-tail_len:]) if tail_len > 0 else "..."]
    p.setPen(QPen(text_col))
    for i, line in enumerate(lines):
        if line:
            lx = max(2, (w - fm.horizontalAdvance(line)) // 2)
            p.drawText(lx, fm.ascent() + 3 + i * line_h, line)
    p.setPen(QPen(border_col))
    p.drawLine(0, text_h, w, text_h)

    # 페이지 표시 (작게, 우상단)
    if page_label:
        p.setPen(QPen(page_col))
        small_font = p.font()
        small_font.setPointSize(max(7, p.font().pointSize() - 2))
        p.setFont(small_font)
        p.drawText(w - 35, fm.ascent() + 3, page_label)

    # 순수 썸네일(파일명 미표시)
    thumb_h = max(40, h - text_h - 4)
    scaled = thumb.scaled(w - 8, thumb_h, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    x = (w - scaled.width()) // 2
    y = text_h + 2 + (thumb_h - scaled.height()) // 2
    p.drawPixmap(x, y, scaled)

    p.setPen(QPen(border_col))
    p.drawRect(0, 0, w - 1, h - 1)
    p.end()
    return pix


class MiniStrip(QWidget):
    """가로 스크롤 미니창. v1.5.0: (path, page) 시그널.

    v1.6.2: 스크린샷 카드용 메타 (원본 PDF 경로 + 페이지) 추가 저장.
    PDF 저장 시 PNG 대신 원본 PDF 페이지를 다시 렌더링하여 품질 손실 없이 내보내기 위함.
    """
    itemActivated = pyqtSignal(str, int)        # v1.5.0: file_path, page_index
    itemRemoved   = pyqtSignal(str, int)
    clearedAll    = pyqtSignal()

    DATA_PATH = Qt.ItemDataRole.UserRole + 0
    DATA_KIND = Qt.ItemDataRole.UserRole + 1
    DATA_PAGE = Qt.ItemDataRole.UserRole + 2    # v1.5.0
    DATA_SRC_PDF  = Qt.ItemDataRole.UserRole + 3   # v1.6.2: 원본 PDF 절대경로 (str, optional)
    DATA_SRC_PAGE = Qt.ItemDataRole.UserRole + 4   # v1.6.2: 원본 PDF 페이지 (0-based int, optional)
    DATA_QUERY    = Qt.ItemDataRole.UserRole + 5   # v1.6.4: 캡처 당시 검색어 (str, optional)
    DATA_LABEL    = Qt.ItemDataRole.UserRole + 6   # 260606-14: 카드 라벨(테마 변경 재렌더용)

    CARD_W = 110
    CARD_H = 150            # 260606-6: 상하 여백 축소(기존 210 → 150)

    def __init__(self, title: str, *, max_items: int = 30,
                 draggable: bool = False,
                 extra_widgets: list = None,
                 parent=None):
        super().__init__(parent)
        self._title = title
        self._max = max_items
        self._draggable = draggable
        self._extra_widgets = extra_widgets or []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)    # 260606-7: 상하 여백 최소화
        layout.setSpacing(1)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(2)
        self.title_label = QLabel(self._title)
        self.title_label.setStyleSheet("font-weight: bold; padding: 0px 4px;")
        head.addWidget(self.title_label)
        head.addStretch(1)

        # v1.5.0 M7: 외부에서 추가 위젯(스크린샷 캡처/저장 버튼) 삽입 가능
        for w in self._extra_widgets:
            head.addWidget(w)

        self.count_label = QLabel("(0)")
        self.count_label.setStyleSheet("color: #888;")
        head.addWidget(self.count_label)

        self.clear_btn = QPushButton("🗑")
        self.clear_btn.setFixedWidth(28)
        self.clear_btn.setToolTip("전체 삭제")
        self.clear_btn.clicked.connect(self._on_clear_all)
        head.addWidget(self.clear_btn)
        layout.addLayout(head)

        self.list = QListWidget()
        self.list.setFlow(QListWidget.Flow.LeftToRight)
        self.list.setWrapping(False)
        self.list.setIconSize(QSize(self.CARD_W, self.CARD_H))
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(4)
        self.list.setHorizontalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setFixedHeight(self.CARD_H + 22 + 16)   # 260606-17: 번호 줄 여유

        if self._draggable:
            self.list.setMovement(QListWidget.Movement.Snap)
            self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        else:
            self.list.setMovement(QListWidget.Movement.Static)
            self.list.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
        # 260618-9: Shift(연속)·Ctrl(개별 토글) 다중 선택 — 여러 장 한 번에 삭제 등
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

        self.list.itemClicked.connect(self._on_clicked)
        self.list.itemActivated.connect(self._on_clicked)
        # 260606-17: 재정렬/삭제 시 번호 갱신
        self.list.model().rowsMoved.connect(lambda *_: self._renumber())
        self.list.model().rowsRemoved.connect(lambda *_: self._renumber())

        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_menu)

        layout.addWidget(self.list)

    # --- 항목 ----------------------------------------------------------
    def add_item(self, file_path: str, *, kind: str = "pdf",
                 label: Optional[str] = None,
                 page_index: int = 0,                # v1.5.0
                 thumb_pdf_path: Optional[str] = None,   # v1.6.1 H3
                 src_pdf: Optional[str] = None,           # v1.6.2: 원본 PDF (PDF 저장 시 1:1 재렌더)
                 src_page: Optional[int] = None,          # v1.6.2: 원본 PDF 페이지 (0-based)
                 src_query: Optional[str] = None,         # v1.6.4: 캡처 당시 검색어 (형광펜 재렌더)
                 prepend: bool = True):
        if not label:
            label = Path(file_path).stem

        # v1.6.3 B1: 스크린샷 카드(kind="image")는 캡처 PNG 자체를 썸네일로.
        # (v1.6.1 H3 의 "thumb_pdf_path → 원본 PDF 0페이지" 우선은 모든 카드가
        #  표지로 보여 식별 불가했으므로 폐기. thumb_pdf_path 는 호환용 잔존.)
        if kind == "image":
            thumb = _render_image_thumb(file_path)
            page_label = ""
        elif thumb_pdf_path:
            thumb = _render_pdf_page_thumb(thumb_pdf_path, 0)
            page_label = ""
        else:
            thumb = _render_pdf_page_thumb(file_path, page_index)
            page_label = f"p.{page_index + 1}"

        card = make_card_pixmap(thumb, label, page_label, self.CARD_W, self.CARD_H)

        item = QListWidgetItem()
        item.setIcon(QIcon(card))
        item.setData(self.DATA_PATH, file_path)
        item.setData(self.DATA_KIND, kind)
        item.setData(self.DATA_PAGE, int(page_index))
        item.setData(self.DATA_LABEL, label)
        # v1.6.2: 원본 PDF 메타 (스크린샷 카드 전용)
        if src_pdf:
            item.setData(self.DATA_SRC_PDF, str(src_pdf))
            item.setData(self.DATA_SRC_PAGE, int(src_page if src_page is not None else 0))
        if src_query:
            item.setData(self.DATA_QUERY, str(src_query))
        # v1.5.0 툴팁: 파일명(stem) + 페이지
        tip = Path(file_path).stem
        if kind == "pdf":
            tip += f"  (p.{page_index + 1})"
        elif src_pdf:
            tip += f"  ← {Path(src_pdf).stem} (p.{int(src_page or 0) + 1})"
        item.setToolTip(tip)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        item.setSizeHint(QSize(self.CARD_W + 8, self.CARD_H + 8 + 16))   # 260606-17: 번호 줄

        # v1.5.0 dedup 키 = (path, page)
        for i in range(self.list.count()):
            it = self.list.item(i)
            if (it.data(self.DATA_PATH) == file_path
                    and (it.data(self.DATA_PAGE) or 0) == int(page_index)):
                self.list.takeItem(i)
                break

        if prepend:
            self.list.insertItem(0, item)
        else:
            self.list.addItem(item)

        while self.list.count() > self._max:
            self.list.takeItem(self.list.count() - 1)
        self._update_count()
        self._renumber()

        # v1.6.1 H1: 새 항목이 끝(오른쪽)에 추가되면 자동으로 그 위치로 스크롤
        if not prepend and self.list.count() > 0:
            last = self.list.item(self.list.count() - 1)
            self.list.scrollToItem(last)

    def set_expand(self, on: bool):
        """260606-19: on이면 그리드로 펼쳐 세로 공간을 채움(스크린샷만 보일 때),
        off면 가로 한 줄 스트립(고정 높이)."""
        from PyQt6.QtWidgets import QSizePolicy
        if on:
            self.list.setWrapping(True)
            self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.list.setMinimumHeight(self.CARD_H + 38)
            self.list.setMaximumHeight(16777215)
            self.list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        else:
            self.list.setWrapping(False)
            self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.list.setMinimumHeight(0)
            self.list.setFixedHeight(self.CARD_H + 22 + 16)

    def _renumber(self):
        """260606-17: 썸네일 아래에 표시순서 번호를 갱신."""
        for i in range(self.list.count()):
            self.list.item(i).setText(str(i + 1))

    def refresh_cards(self):
        """260606-14: 테마 변경 시 모든 카드 픽스맵을 현재 색으로 재렌더."""
        for i in range(self.list.count()):
            it = self.list.item(i)
            kind = it.data(self.DATA_KIND)
            path = it.data(self.DATA_PATH)
            if not path:
                continue
            label = it.data(self.DATA_LABEL) or Path(path).stem
            page = int(it.data(self.DATA_PAGE) or 0)
            try:
                if kind == "image":
                    thumb = _render_image_thumb(path); page_label = ""
                else:
                    thumb = _render_pdf_page_thumb(path, page); page_label = f"p.{page + 1}"
                card = make_card_pixmap(thumb, label, page_label, self.CARD_W, self.CARD_H)
                it.setIcon(QIcon(card))
            except Exception:
                pass

    def remove_key(self, file_path: str, page_index: int):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if (it.data(self.DATA_PATH) == file_path
                    and (it.data(self.DATA_PAGE) or 0) == int(page_index)):
                self.list.takeItem(i)
                self._update_count()
                self.itemRemoved.emit(file_path, int(page_index))
                return

    def all_items(self) -> list:
        """list of (path, kind, page)."""
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            out.append((it.data(self.DATA_PATH),
                        it.data(self.DATA_KIND),
                        int(it.data(self.DATA_PAGE) or 0)))
        return out

    def all_paths(self) -> list:
        return [t[0] for t in self.all_items()]

    def all_meta(self) -> list:
        """v1.6.2: 스크린샷 PDF 저장용 — 카드별 풀 메타 리스트.

        각 dict 키: path (PNG), kind, page (카드 내부 페이지 인덱스),
        src_pdf (원본 PDF 경로, optional), src_page (원본 페이지 0-based, optional).
        """
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            out.append({
                "path": it.data(self.DATA_PATH),
                "kind": it.data(self.DATA_KIND),
                "page": int(it.data(self.DATA_PAGE) or 0),
                "src_pdf": it.data(self.DATA_SRC_PDF),
                "src_page": it.data(self.DATA_SRC_PAGE),
                "src_query": it.data(self.DATA_QUERY),
            })
        return out

    def index_of_path(self, path: str) -> int:
        """v1.6.4 C2: 주어진 경로를 가진 첫 카드의 인덱스 (없으면 -1)."""
        for i in range(self.list.count()):
            if self.list.item(i).data(self.DATA_PATH) == path:
                return i
        return -1

    def activate_index(self, idx: int) -> None:
        """v1.6.4 C2: idx 카드를 선택·스크롤하고 itemActivated 발신."""
        if idx < 0 or idx >= self.list.count():
            return
        item = self.list.item(idx)
        self.list.setCurrentItem(item)
        self.list.scrollToItem(item)
        self._on_clicked(item)


    def set_max_items(self, n: int):
        """v1.5.1: 한도 동적 변경. 줄이면 끝에서부터 제거."""
        self._max = max(1, int(n))
        while self.list.count() > self._max:
            self.list.takeItem(self.list.count() - 1)
        self._update_count()

    def max_items(self) -> int:
        return self._max

    def clear(self):
        self.list.clear()
        self._update_count()

    def _on_clear_all(self):
        if self.list.count() == 0:
            return
        ret = QMessageBox.question(
            self, "전체 삭제",
            f"{self._title} 의 {self.list.count()}개 항목을 모두 지울까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.clear()
            self.clearedAll.emit()

    def _update_count(self):
        self.count_label.setText(f"({self.list.count()}/{self._max})")

    def _on_clicked(self, item: QListWidgetItem):
        path = item.data(self.DATA_PATH)
        page = int(item.data(self.DATA_PAGE) or 0)
        if path:
            self.itemActivated.emit(path, page)

    def _show_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        # 260618-9: 우클릭한 항목이 다중 선택에 포함되면 선택분 전체 삭제
        sel = [it for it in self.list.selectedItems()]
        if item not in sel:
            sel = [item]
        menu = QMenu(self.list)
        if len(sel) > 1:
            act = QAction(f"선택 {len(sel)}개 삭제", menu)
            keys = [(it.data(self.DATA_PATH), int(it.data(self.DATA_PAGE) or 0))
                    for it in sel]
            act.triggered.connect(lambda: [self.remove_key(p, pg) for p, pg in keys])
        else:
            act = QAction("삭제", menu)
            path = item.data(self.DATA_PATH)
            page = int(item.data(self.DATA_PAGE) or 0)
            act.triggered.connect(lambda: self.remove_key(path, page))
        menu.addAction(act)
        menu.exec(self.list.mapToGlobal(pos))
