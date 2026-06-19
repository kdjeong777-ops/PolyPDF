"""좌측 2단 - 페이지 썸네일 리스트.

v1.4.0 F3: 패널 폭 리사이즈 + 제목 ...뒷부분 표시 3줄.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSize, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap, QPainter, QColor, QPen, QTransform
from PyQt6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QWidget,
    QVBoxLayout,
    QLabel,
    QSizePolicy,
)

from viewer.pdf_doc import PdfDocument


class PageThumbs(QWidget):
    """전체 페이지 썸네일 세로 리스트."""
    pageActivated = pyqtSignal(int)
    addBookmarkAtPage = pyqtSignal(int)      # 260606-4: 썸네일 우클릭 → 책갈피 추가(0-based)
    applyPageEditsRequested = pyqtSignal()   # 260606-22: 페이지 삭제/이동 변경을 새 PDF로 적용
    registerHyperlinkAtPage = pyqtSignal(int)  # 260609-3: 썸네일 우클릭 → 하이퍼링크 등록(0-based)
    setPagesHidden = pyqtSignal(object, bool)  # 260609-14(D5): (pages, hidden)
    rotatePages = pyqtSignal(object, int)      # 260609-15(A1): (pages, delta±90)
    pageFilterChanged = pyqtSignal(str)        # 260609-21(J4): 필터 변경(all/visible/decorated/hidden)
    fileBoundaryRequested = pyqtSignal(int)    # 260610-1: 목록 끝 휠/↑↓ → 이전(-1)/다음(+1) 파일
    printPagesRequested = pyqtSignal(object)       # 260616-21: 선택 페이지 인쇄(0-based list)
    screenshotPagesRequested = pyqtSignal(object)  # 260616-21: 선택 페이지 스크린샷으로 복사

    THUMB_DPI = 48
    NUM_BAND = 18           # 260606-26: 썸네일 하단 페이지번호 띠 높이
    ITEM_MARGIN = 6         # 260611-12: 카드 위아래 여백(세로 간격) — 종횡비별 셀 높이에 가산

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: Optional[PdfDocument] = None
        self._thumb_size = QSize(120, 160)
        self._edit_mode = False              # 260606-22: 책갈피 편집모드와 동기
        self._orig_count = 0
        self._hidden_pages = set()           # 260609-14(D5): 숨김 페이지
        self._rotations = {}                 # 260609-15(A1): {page0: deg}
        self._decorated = set()              # 260609-21(J4): 꾸밈(하이퍼링크/선긋기) 페이지
        self._img_resolver = None            # 260611-18(A5): page0->[삽입 이미지 dict] (썸네일 베이킹)
        # 260606-28/29: 폭 치수(_build_ui 가 참조하므로 먼저 계산).
        #   폭 고정(리사이즈 불가) — 더 넓혀도 할 일이 없고, 번호가 하단으로 가며
        #   우측 여백이 과해진 문제도 함께 해소. 아이콘 캔버스 폭=뷰포트 가용폭(가운데 정렬용).
        self._fixed_w = self._thumb_size.width() + 30   # 150
        self._icon_w = self._fixed_w - 20               # 130 (세로 스크롤바·프레임 여유)
        self._build_ui()

        self.setFixedWidth(self._fixed_w)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(16)    # 260611-12: 80→16ms(한 프레임) — 더 빨리 표시
        self._render_timer.timeout.connect(self._render_visible)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.title = QLabel("페이지")
        self.title.setStyleSheet("padding: 4px; font-weight: bold;")
        self.title.setWordWrap(True)
        # 3줄 고정 (글자 크기에 따라 약간 다름)
        fm = self.title.fontMetrics()
        self.title.setMaximumHeight(fm.height() * 3 + 8)
        self.title.setMinimumHeight(fm.height() * 3 + 8)
        layout.addWidget(self.title)

        # 260609-21(J4): 필터 버튼 — 전체/보임/꾸밈/숨김
        from PyQt6.QtWidgets import QHBoxLayout as _QHB, QPushButton as _QPB
        self._filter = "all"
        self._filter_btns = {}
        fr = _QHB(); fr.setContentsMargins(2, 0, 2, 2); fr.setSpacing(2)
        for key, label in [("all", "전체"), ("visible", "보임"),
                           ("decorated", "꾸밈"), ("hidden", "숨김")]:
            b = _QPB(label); b.setCheckable(True); b.setChecked(key == "all")
            b.setFixedHeight(22)
            # 260610-1: 클릭해도 키보드 포커스를 뺏지 않게(뷰어 키 이동 유지)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            fr.addWidget(b)
            self._filter_btns[key] = b
        layout.addLayout(fr)

        self.list = QListWidget()
        # 260606-26/29: 번호 띠 포함 + 가운데 정렬용으로 아이콘 폭을 뷰포트 가용폭으로
        self.list.setIconSize(QSize(self._icon_w,
                                    self._thumb_size.height() + self.NUM_BAND))
        self.list.setSpacing(2)
        # 260611-12: 종횡비별로 셀 높이가 달라야 가로/세로 페이지 간격이 적절 → 균일크기 끔
        self.list.setUniformItemSizes(False)
        # 260606-28: 가로 스크롤바 제거(폭 고정이라 불필요), 우측 여백 최소화
        self.list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        # 260609-11: 휠 1노치에 썸네일 1개씩 이동(기존엔 3~4개). 항목 단위 스크롤 +
        #            뷰포트 휠 이벤트를 가로채 정확히 1칸 이동.
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerItem)
        self.list.viewport().installEventFilter(self)
        # 260603-3: 인쇄용 다중 선택(Ctrl/Shift). 단일 클릭 이동은 그대로.
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemActivated.connect(self._on_activated)
        self.list.itemClicked.connect(self._on_activated)
        # 260606-4: 썸네일 우클릭 → '책갈피 추가'
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_list_menu)
        self.list.verticalScrollBar().valueChanged.connect(
            lambda _: self._render_timer.start()
        )
        self.list.installEventFilter(self)   # 260606-22: 편집모드 상/하 이동키
        layout.addWidget(self.list, 1)

    # ===== 260606-22: 책갈피 편집모드 — 페이지 삭제/이동 =====
    def set_edit_mode(self, on: bool):
        self._edit_mode = bool(on)
        if on:
            self.list.setMovement(QListWidget.Movement.Snap)
            self.list.setDragEnabled(True)
            self.list.setAcceptDrops(True)
            self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
            self.list.setDropIndicatorShown(True)
        else:
            self.list.setMovement(QListWidget.Movement.Static)
            self.list.setDragEnabled(False)
            self.list.setAcceptDrops(False)
            self.list.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
            self.list.setDropIndicatorShown(False)

    def current_page_sequence(self) -> list:
        """현재 표시 순서의 원본 페이지 인덱스(0-based) 목록(삭제분 제외)."""
        out = []
        for i in range(self.list.count()):
            p = self.list.item(i).data(Qt.ItemDataRole.UserRole)
            if p is not None:
                out.append(int(p))
        return out

    def is_page_dirty(self) -> bool:
        seq = self.current_page_sequence()
        return seq != list(range(self._orig_count))

    def _move_selected(self, direction: int):
        rows = sorted(self.list.row(it) for it in self.list.selectedItems())
        if not rows:
            return
        if direction < 0:
            if rows[0] <= 0:
                return
            for r in rows:
                it = self.list.takeItem(r)
                self.list.insertItem(r - 1, it)
                it.setSelected(True)
        else:
            if rows[-1] >= self.list.count() - 1:
                return
            for r in reversed(rows):
                it = self.list.takeItem(r)
                self.list.insertItem(r + 1, it)
                it.setSelected(True)
        self._render_timer.start()

    def _delete_selected(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def eventFilter(self, obj, event):
        # 260611-12: 세로 스크롤바가 생기거나 사라져 뷰포트 폭이 바뀌면(가운데 정렬 기준 변경)
        #   아이콘 폭을 재동기화하고 카드를 다시 그려 '스크롤바 고려한 중앙 정렬' 유지.
        if obj is self.list.viewport() and event.type() == QEvent.Type.Resize:
            try:
                if self._sync_icon_width():
                    self._rerender_all()
            except Exception:
                pass
            return False
        # 260609-11: 휠 1노치 = 썸네일 1개 이동
        # 260610-1: 뷰어모드에선 목록 끝에서 한 번 더 굴리면 이전/다음 파일(메인 뷰어와 동일)
        if obj is self.list.viewport() and event.type() == QEvent.Type.Wheel:
            try:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    return False                       # Ctrl+휠은 기본(확대 등) 유지
                dy = event.angleDelta().y()
                if dy != 0:
                    sb = self.list.verticalScrollBar()
                    if not self._edit_mode:
                        if dy < 0 and sb.value() >= sb.maximum():
                            self.fileBoundaryRequested.emit(+1)
                            return True
                        if dy > 0 and sb.value() <= sb.minimum():
                            self.fileBoundaryRequested.emit(-1)
                            return True
                    sb.setValue(sb.value() + (-1 if dy > 0 else 1))  # ScrollPerItem=1칸
                    return True
            except Exception:
                return False
        if obj is self.list and event.type() == QEvent.Type.KeyPress:
            k = event.key()
            if self._edit_mode:
                if k == Qt.Key.Key_Up:
                    self._move_selected(-1); return True
                if k == Qt.Key.Key_Down:
                    self._move_selected(+1); return True
                if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    self._delete_selected(); return True
            elif event.modifiers() == Qt.KeyboardModifier.NoModifier:
                # 260610-1: 뷰어모드 ↑/↓·PgUp/PgDn = 보이는(필터 통과) 썸네일 이동
                #           + 뷰어 페이지 동기, 첫/끝에서 한 번 더 → 이전/다음 파일.
                #           Shift/Ctrl 조합은 기본(다중 선택 확장, 260603-3)에 위임.
                step = (+1 if k in (Qt.Key.Key_Down, Qt.Key.Key_PageDown)
                        else -1 if k in (Qt.Key.Key_Up, Qt.Key.Key_PageUp) else 0)
                if step:
                    nxt = self._next_visible_row(self.list.currentRow(), step)
                    if nxt is None:
                        self.fileBoundaryRequested.emit(step)
                    else:
                        self.list.setCurrentRow(nxt)
                        self.list.scrollToItem(self.list.item(nxt))
                        pg = self.list.item(nxt).data(Qt.ItemDataRole.UserRole)
                        if pg is not None:
                            self.pageActivated.emit(int(pg))
                    return True
        return super().eventFilter(obj, event)

    def _next_visible_row(self, row: int, step: int):
        """260610-1: row 에서 step(±1) 방향 첫 '보이는'(필터 통과) 행. 없으면 None."""
        n = self.list.count()
        if n == 0:
            return None
        i = (0 if step > 0 else n - 1) if row < 0 else row + step
        while 0 <= i < n:
            if not self.list.item(i).isHidden():
                return i
            i += step
        return None

    def _on_list_menu(self, pos):
        item = self.list.itemAt(pos)
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        page = item.data(Qt.ItemDataRole.UserRole) if item else None
        # 260616-21: 선택 페이지 인쇄 / 스크린샷으로 복사 (편집모드 무관, 항상)
        sel_print = sorted({int(it.data(Qt.ItemDataRole.UserRole))
                            for it in self.list.selectedItems()
                            if it.data(Qt.ItemDataRole.UserRole) is not None})
        if page is not None and not sel_print:
            sel_print = [int(page)]
        act_print = act_shot = None
        if self._doc is not None and sel_print:
            act_print = menu.addAction(f"선택 페이지 인쇄 ({len(sel_print)}쪽)")
            act_shot = menu.addAction(f"선택 페이지 스크린샷으로 복사 ({len(sel_print)}쪽)")
            menu.addSeparator()
        act_add = act_del = act_apply = None
        if self._edit_mode:
            n = len(self.list.selectedItems())
            act_del = menu.addAction(f"삭제 ({n}쪽)" if n else "삭제")
            act_del.setEnabled(n > 0)
            menu.addSeparator()
            if self.is_page_dirty():
                act_apply = menu.addAction("변경 적용 — 새 PDF로 저장...")
            menu.addSeparator()
        act_hl = act_hide = act_unhide = act_hreset = None
        act_rot_l = act_rot_r = None
        # 260609-14(D5): 편집모드 — 선택 페이지 숨김/해제
        if self._edit_mode:
            sel_pages = sorted({int(it.data(Qt.ItemDataRole.UserRole))
                                for it in self.list.selectedItems()
                                if it.data(Qt.ItemDataRole.UserRole) is not None})
            if page is not None and not sel_pages:
                sel_pages = [int(page)]
            if sel_pages:
                act_hide = menu.addAction(f"숨김 ({len(sel_pages)}쪽)")
                act_unhide = menu.addAction(f"숨김 해제 ({len(sel_pages)}쪽)")
            if self._hidden_pages:
                act_hreset = menu.addAction("숨김 전체 해제")
            menu.addSeparator()
            # 260609-15(A1): 회전
            if sel_pages:
                act_rot_l = menu.addAction(f"왼쪽 90° 회전 ({len(sel_pages)}쪽)")
                act_rot_r = menu.addAction(f"오른쪽 90° 회전 ({len(sel_pages)}쪽)")
            else:
                act_rot_l = act_rot_r = None
            menu.addSeparator()
        if self._edit_mode and page is not None:   # 책갈피·하이퍼링크는 편집모드만
            act_add = menu.addAction(f"책갈피 추가 (p.{int(page) + 1})")
            act_hl = menu.addAction(f"하이퍼링크 등록… (p.{int(page) + 1})")
        if menu.isEmpty():
            return
        chosen = menu.exec(self.list.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_print:                     # 260616-21
            self.printPagesRequested.emit(sel_print); return
        if chosen == act_shot:
            self.screenshotPagesRequested.emit(sel_print); return
        if chosen == act_del:
            self._delete_selected()
        elif chosen == act_apply:
            self.applyPageEditsRequested.emit()
        elif chosen == act_add and page is not None:
            self.addBookmarkAtPage.emit(int(page))
        elif chosen == act_hl and page is not None:
            self.registerHyperlinkAtPage.emit(int(page))
        elif chosen is not None and chosen == act_hide:
            self.setPagesHidden.emit(sel_pages, True)
        elif chosen is not None and chosen == act_unhide:
            self.setPagesHidden.emit(sel_pages, False)
        elif chosen is not None and chosen == act_hreset:
            self.setPagesHidden.emit(sorted(self._hidden_pages), False)
        elif chosen is not None and chosen == act_rot_l:
            self.rotatePages.emit(sel_pages, -90)
        elif chosen is not None and chosen == act_rot_r:
            self.rotatePages.emit(sel_pages, +90)

    def _format_title(self, name_with_ext: str) -> str:
        """v1.6.1 M2: 패널의 실제 폭 기준으로 한글 wrap + ... elide.

        QFontMetrics 로 픽셀 단위 측정 → 한 줄 들어가는 글자수 계산 → 3줄 분할.
        분할 기준이 폭에 동적이라 사용자가 패널을 좁히거나 넓히면 적절히 조정됨.
        """
        stem = Path(name_with_ext).stem
        if not stem:
            return ""
        fm = self.title.fontMetrics()
        avail_w = max(60, self.title.width() - 12)   # 좌우 여백
        # 한 줄 안에 들어갈 글자수 추정 (한글: 평균 ~12px, 영숫자 ~7px)
        avg = max(10, fm.horizontalAdvance("한") or 14)
        cpl = max(4, avail_w // avg)
        max_total = cpl * 3
        if len(stem) > max_total:
            return "..." + stem[-(max_total - 3):]
        return stem

    def _card_h_for(self, pw, ph):
        """260611-12: 페이지 종횡비(pw×ph)의 썸네일 카드 높이(썸네일 높이+번호띠)."""
        tw, th = self._thumb_size.width(), self._thumb_size.height()
        if pw <= 0 or ph <= 0:
            return th + self.NUM_BAND
        scale = min(tw / pw, th / ph)
        return int(round(ph * scale)) + self.NUM_BAND

    def load_document(self, file_path):
        path = Path(file_path)
        try:
            mt = path.stat().st_mtime
        except Exception:
            mt = 0
        # 260611-62: 같은 파일·버전이 이미 로드돼 있으면 재로드 생략(썸네일 2중 리프레시 방지).
        #   (책갈피 선택 시 활성창 동기화와 _load_main 이 같은 파일을 두 번 로드하던 문제)
        if (self._doc is not None and getattr(self, "_doc_path", None) == str(path)
                and getattr(self, "_doc_mtime", None) == mt):
            return
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self.list.clear()

        if not path.exists() or path.suffix.lower() != ".pdf":
            self.title.setText(self._format_title(path.name))
            self._doc_path = None; self._doc_mtime = None
            return
        self._doc_path = str(path); self._doc_mtime = mt

        self.title.setText(self._format_title(path.name))
        try:
            self._doc = PdfDocument(file_path)
            if self._doc.needs_password:        # 260611-61: 암호화 파일 썸네일 인증
                from viewer import secure_store
                pw = secure_store.recall_any(file_path)
                if pw:
                    self._doc.authenticate(pw)
        except Exception:
            return
        self._orig_count = self._doc.page_count      # 260606-22: 페이지 편집 기준
        # 260611-12: 0쪽 종횡비로 기본 셀 높이 산정(대부분 문서는 방향 동일).
        #   혼합 방향(세로 표지+가로 본문 등)은 렌더 시 항목별로 정확히 보정됨.
        try:
            r0 = self._doc.doc.load_page(0).rect
            default_h = self._card_h_for(r0.width, r0.height) + self.ITEM_MARGIN
        except Exception:
            default_h = self._thumb_size.height() + self.NUM_BAND + self.ITEM_MARGIN
        for i in range(self._doc.page_count):
            # 260606-26: 번호는 픽스맵 하단에 렌더 → 아이템 텍스트 비움(우측 표시 제거)
            it = QListWidgetItem("")
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setSizeHint(QSize(self._icon_w, default_h))
            self.list.addItem(it)
        self._sync_icon_width()       # 260606-30: 로드 직후 가운데 정렬 폭 반영
        self._apply_filter()          # 260609-21(J4): 현재 필터 반영
        # 260611-12: 첫 화면을 즉시 렌더(레이아웃 확정 후) — '늦게 뜨는' 체감 완화
        QTimer.singleShot(0, self._render_visible)

    def select_page(self, page_index: int):
        """260618-9: 메인뷰 페이지 동기 — 현재 페이지 표시.
        단, 사용자가 Shift/Ctrl 로 여러 썸네일을 선택 중이면 그 선택을 지우지 않고
        현재 항목(포커스)만 이동(NoUpdate). 과거 setCurrentRow 가 다중선택을 매번
        초기화해 Shift 연속선택이 풀리고 Ctrl 선택이 버벅이던 문제 수정."""
        if not (0 <= page_index < self.list.count()):
            return
        from PyQt6.QtCore import QItemSelectionModel
        self.list.blockSignals(True)
        if len(self.list.selectedItems()) > 1:
            idx = self.list.model().index(page_index, 0)
            self.list.selectionModel().setCurrentIndex(
                idx, QItemSelectionModel.SelectionFlag.NoUpdate)   # 선택 유지·포커스만 이동
        else:
            self.list.setCurrentRow(page_index)                    # 단일: 기존대로 현재 페이지 강조
        self.list.scrollToItem(self.list.item(page_index))
        self.list.blockSignals(False)

    def _render_visible(self):
        if not self._doc:
            return
        # 260611-12: 보이는 영역 + 한 화면 아래까지 미리 렌더 → 스크롤 시 '뒤늦게 뜸' 완화
        vr = self.list.viewport().rect()
        viewport = vr.adjusted(0, -vr.height(), 0, vr.height())
        for i in range(self.list.count()):
            item = self.list.item(i)
            rect = self.list.visualItemRect(item)
            if not rect.intersects(viewport):
                continue
            if not item.icon().isNull():
                continue
            page_idx = item.data(Qt.ItemDataRole.UserRole)
            try:
                rp = self._doc.render_thumbnail(page_idx, dpi=self.THUMB_DPI)
                qimg = QImage(rp.samples, rp.width, rp.height,
                              rp.width * 3, QImage.Format.Format_RGB888)
                pix = QPixmap.fromImage(qimg)
                # 260611-18(A5): 삽입 이미지(개체) 베이킹 — 회전 전(정규화 좌표) 합성
                if self._img_resolver is not None:
                    bp = QPainter(pix)
                    bp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    bp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                    self._paint_thumb_images(bp, page_idx, pix.width(), pix.height())
                    bp.end()
                rot = self._rotations.get(int(page_idx), 0)   # 260609-15(A1): 회전
                if rot:
                    pix = pix.transformed(QTransform().rotate(rot),
                                          Qt.TransformationMode.SmoothTransformation)
                pix = pix.scaled(
                    self._thumb_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                # 260606-26/29: 썸네일 아래 번호 띠 합성 + 패널 가운데 정렬.
                #   투명 캔버스(폭=아이콘 가용폭) 중앙에 흰 카드(썸네일+번호)를 배치.
                band = self.NUM_BAND
                card_w = pix.width()
                card_h = pix.height() + band
                # 260606-30: 캔버스 폭 = 실제 아이콘(=뷰포트 가용) 폭 → 정확한 가운데
                canvas_w = max(self.list.iconSize().width(), card_w)
                from PyQt6.QtCore import QRect
                bordered = QPixmap(canvas_w, card_h)
                bordered.fill(QColor(0, 0, 0, 0))            # 투명
                x0 = (canvas_w - card_w) // 2                # 가운데 정렬 오프셋
                # 260609-21(J4): 테마·꾸밈에 따른 번호 띠 색
                from viewer import theme as _theme
                dark = _theme.is_dark()
                deco = int(page_idx) in self._decorated
                if deco:
                    # 260611-18(B1): 다크모드 꾸밈 띠가 너무 진해 구분이 안 돼 → 더 연한 파랑
                    band_bg = QColor("#4f86c6") if dark else QColor("#cfe3ff")  # 다크: 밝은 파랑
                    band_fg = QColor("#ffffff") if dark else QColor("#0d3b66")
                    band_bd = QColor("#7aa8e0") if dark else QColor("#3a6ea5")
                elif dark:
                    band_bg = QColor("#000000"); band_fg = QColor("#ffffff"); band_bd = QColor("#888888")
                else:
                    band_bg = QColor("#ffffff"); band_fg = QColor("#333333"); band_bd = QColor("#bbbbbb")
                p = QPainter(bordered)
                p.fillRect(x0, 0, card_w, pix.height(), QColor("white"))  # 썸네일 영역(흰 종이)
                p.fillRect(x0, pix.height(), card_w, band, band_bg)       # 번호 띠
                p.drawPixmap(x0, 0, pix)
                p.setPen(QPen(band_bd))
                p.drawRect(x0, 0, card_w - 1, card_h - 1)
                p.drawLine(x0, pix.height(), x0 + card_w - 1, pix.height())
                p.setPen(band_fg)
                p.drawText(QRect(x0, pix.height(), card_w, band),
                           Qt.AlignmentFlag.AlignCenter,
                           str(int(page_idx) + 1))
                # 260609-14(D5): 숨김 페이지 — 흐리게 + 우측 회색 띠 '숨김'
                if int(page_idx) in self._hidden_pages:
                    p.fillRect(x0, 0, card_w, pix.height(), QColor(255, 255, 255, 150))
                    bw = 16
                    bx = x0 + card_w - bw
                    p.fillRect(bx, 0, bw, pix.height(), QColor(110, 110, 110, 230))
                    p.save()
                    p.translate(bx + bw // 2, pix.height() // 2)
                    p.rotate(90)
                    p.setPen(QColor("white"))
                    p.drawText(QRect(-pix.height() // 2, -bw // 2, pix.height(), bw),
                               Qt.AlignmentFlag.AlignCenter, "숨김")
                    p.restore()
                p.end()
                item.setIcon(QIcon(bordered))
                # 260611-12: 실제 카드 높이로 셀 높이 보정(가로/세로 페이지별 간격 적정)
                desired_h = bordered.height() + self.ITEM_MARGIN
                if item.sizeHint().height() != desired_h:
                    item.setSizeHint(QSize(self.list.iconSize().width(), desired_h))
            except Exception:
                pass

    def set_hidden_pages(self, pages):
        """260609-14(D5): 숨김 페이지 집합 갱신 → 아이콘 재렌더."""
        self._hidden_pages = set(int(p) for p in (pages or set()))
        self._rerender_all()

    def set_rotations(self, rotations):
        """260609-15(A1): {page0: deg} 회전 갱신 → 아이콘 재렌더."""
        self._rotations = {int(k): int(v) % 360 for k, v in (rotations or {}).items()}
        self._rerender_all()

    def set_image_resolver(self, fn):
        """260611-18(A5): page0->[이미지 dict] 해석기. 썸네일에 개체를 베이킹."""
        self._img_resolver = fn

    def _b64_to_pix(self, b64):
        from PyQt6.QtGui import QPixmap
        import base64
        pm = QPixmap()
        try:
            pm.loadFromData(base64.b64decode(b64), "PNG")
        except Exception:
            pass
        return pm

    def _paint_thumb_images(self, painter, page0, w, h):
        """260611-18(A5): 정규화 rect·shape·alpha·rot 로 개체를 썸네일에 합성(회전 전 좌표)."""
        from PyQt6.QtGui import QPainterPath
        from PyQt6.QtCore import QRectF
        try:
            objs = self._img_resolver(int(page0)) or []
        except Exception:
            return
        for d in objs:
            pm = self._b64_to_pix(d.get("data", ""))
            if pm is None or pm.isNull():
                continue
            fx, fy, fw, fh = d.get("rect", [0.1, 0.1, 0.3, 0.3])
            cx = (fx + fw / 2.0) * w; cy = (fy + fh / 2.0) * h
            hw = fw * w / 2.0; hh = fh * h / 2.0
            rot = float(d.get("rot", 0.0))
            alpha = max(0, min(100, int(d.get("alpha", 100))))
            shape = d.get("shape", "rect")
            local = QRectF(-hw, -hh, 2 * hw, 2 * hh)
            painter.save()
            painter.translate(cx, cy)
            if rot:
                painter.rotate(rot)
            painter.setOpacity(alpha / 100.0)
            if shape in ("round", "circle"):
                path = QPainterPath()
                if shape == "circle":
                    path.addEllipse(local)
                else:
                    rr = min(local.width(), local.height()) * 0.18
                    path.addRoundedRect(local, rr, rr)
                painter.setClipPath(path)
            painter.drawPixmap(local.toRect(), pm)
            painter.restore()

    def set_decorated_pages(self, pages):
        """260609-21(J4): 꾸밈(하이퍼링크/선긋기) 페이지 집합 → 색·필터 갱신."""
        self._decorated = set(int(p) for p in (pages or set()))
        self._rerender_all()
        if self._filter == "decorated":
            self._apply_filter()

    def page_visible_in_filter(self, page0) -> bool:
        if self._filter == "all":
            return True
        if self._filter == "visible":
            return page0 not in self._hidden_pages
        if self._filter == "hidden":
            return page0 in self._hidden_pages
        if self._filter == "decorated":
            return page0 in self._decorated
        return True

    def set_filter(self, key):
        """260609-21(J4): 썸네일 필터 변경 — 목록·선택 갱신, 신호 발생."""
        self._filter = key
        for k, b in self._filter_btns.items():
            b.blockSignals(True); b.setChecked(k == key); b.blockSignals(False)
        self._apply_filter(jump=True)        # 사용자 필터 변경 시에만 첫 보이는 페이지로
        self.pageFilterChanged.emit(key)

    def _apply_filter(self, jump=False):
        """260609-27: jump=True(사용자 필터 변경) 일 때만 첫 보이는 페이지로 이동.
        로드/메타 갱신 시(jump=False)에는 목록 숨김만 갱신하고 현재 페이지 유지."""
        first_visible = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            pg = it.data(Qt.ItemDataRole.UserRole)
            vis = pg is not None and self.page_visible_in_filter(int(pg))
            it.setHidden(not vis)
            if vis and first_visible is None:
                first_visible = i
        if jump:
            cur = self.list.currentRow()
            if (first_visible is not None
                    and (cur < 0 or self.list.item(cur).isHidden())):
                self.list.setCurrentRow(first_visible)
                pg = self.list.item(first_visible).data(Qt.ItemDataRole.UserRole)
                if pg is not None:
                    self.pageActivated.emit(int(pg))
        self._render_timer.start()

    def _rerender_all(self):
        for i in range(self.list.count()):
            self.list.item(i).setIcon(QIcon())   # 캐시 비우고 다시 렌더
        self._render_timer.start()

    def _on_activated(self, item: QListWidgetItem):
        page_idx = item.data(Qt.ItemDataRole.UserRole)
        if page_idx is not None:
            self.pageActivated.emit(int(page_idx))

    def _sync_icon_width(self):
        """260606-30: 아이콘/아이템 폭을 리스트 뷰포트 실제 폭에 맞춰 가운데 정렬을 정확히.

        세로 스크롤바 유무로 뷰포트 폭이 달라지므로 그 폭에 맞춰야 좌우 여백이 대칭이 됨.
        변경이 있을 때만 적용해 무한 재귀를 방지.
        """
        vw = self.list.viewport().width()
        if vw <= 0:
            return False
        # iconSize 높이는 최대(세로 페이지)로 유지 — 카드는 실제 높이로 그려져 가로 페이지도 OK.
        h = self._thumb_size.height() + self.NUM_BAND
        if self.list.iconSize().width() != vw:
            self.list.setIconSize(QSize(vw, h))
            # 260611-12: 폭만 갱신하고 각 항목의 높이(종횡비별)는 보존
            for i in range(self.list.count()):
                sh = self.list.item(i).sizeHint()
                self.list.item(i).setSizeHint(QSize(vw, sh.height()))
            return True
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_icon_width()       # 260606-30: 가운데 정렬 폭 동기화
        self._render_timer.start()
        # v1.6.1 M2: 패널 폭이 바뀌면 라벨 재포맷
        if self._doc is not None:
            full_name = Path(str(self._doc.path)).name
            self.title.setText(self._format_title(full_name))
