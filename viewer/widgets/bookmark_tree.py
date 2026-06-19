"""좌측 1단 - 책갈피 트리 위젯.

bookmarks.json 또는 폴더의 PDF 파일 목록을 트리로 보여준다.
리프 클릭 시 bookmarkActivated(file_path, page) 시그널 emit.

v1.6.2: 각 PDF 파일 리프에 PDF 자체의 내부 책갈피(TOC)가 있으면 자식으로 펼쳐 표시.
폴더 로딩 시간을 위해 **lazy load** — 사용자가 갈매기(▸)를 처음 펼칠 때 PyMuPDF
`doc.get_toc()` 로 한 번만 읽어들인다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import re
import shutil
from typing import Optional as _Opt
import fitz
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QMessageBox,
    QComboBox,
    QFileDialog,
    QInputDialog,
    QApplication,
)


# v1.6.20: 휴지통 이동 — 미설치 환경에서도 import 자체는 깨지지 않게 보호
try:
    from send2trash import send2trash as _send2trash
    _HAS_TRASH = True
except Exception:
    _send2trash = None
    _HAS_TRASH = False


# 파일명 무효 문자 (Windows 기준)
_INVALID_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


# 페이지 배지 패턴: "  (p.10)" 또는 "  (p.10–12)" / "  (p.10-12)"
_PAGE_BADGE_RE = re.compile(r"\s*\(p\.\s*\d+(?:\s*[-–]\s*\d+)?\)\s*$")


# 260611-57: 암호화 표시용 데이터 역할(트리 위젯과 공유)
_ENC_ROLE = Qt.ItemDataRole.UserRole + 5
# 260618-1: 암호화 파일의 인증 상태 — "owner"(전체/암호열음·초록), "user"(제한암호·노랑),
#           "locked"(미인증·빨강). 색 원/삼각형 표식에 사용.
_AUTH_ROLE = Qt.ItemDataRole.UserRole + 6


class _EditableTree(QTreeWidget):
    """드래그 재배치(InternalMove) 발생 시 dropped 시그널 — 편집 '변경됨' 추적용(260606-4)."""
    dropped = pyqtSignal()
    delPressed = pyqtSignal()       # 260611-56: DEL 키 → 선택 삭제(휴지통)

    def dropEvent(self, e):
        super().dropEvent(e)
        self.dropped.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Delete:
            self.delPressed.emit(); e.accept(); return
        super().keyPressEvent(e)

    def drawBranches(self, painter, rect, index):
        """260611-57/260618-1: 암호화 파일은 펼침표시(삼각형)·원을 인증 상태별 색으로.
        초록=암호 열음(owner/전체), 노랑=제한 암호로 열음(user), 빨강=미인증."""
        item = self.itemFromIndex(index)
        if item is None or not item.data(0, _ENC_ROLE):
            super().drawBranches(painter, rect, index)
            return
        from PyQt6.QtGui import QColor, QPolygon
        from PyQt6.QtCore import QPoint
        auth = item.data(0, _AUTH_ROLE)
        if auth == "owner":
            col = QColor(34, 160, 70)        # 초록 — 암호 열음(전체 권한)
        elif auth == "user":
            col = QColor(235, 170, 0)        # 노랑 — 제한 암호로 열음
        else:
            col = QColor(214, 40, 40)        # 빨강 — 미인증(암호 미입력)
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(col)
        cx = rect.right() - 11
        cy = rect.center().y()
        if item.childCount() > 0:                    # 책갈피 있음 → 붉은 삼각형
            if self.isExpanded(index):
                pts = [QPoint(cx - 5, cy - 3), QPoint(cx + 5, cy - 3), QPoint(cx, cy + 4)]
            else:
                pts = [QPoint(cx - 3, cy - 5), QPoint(cx - 3, cy + 5), QPoint(cx + 4, cy)]
            painter.drawPolygon(QPolygon(pts))
        else:                                        # 책갈피 없음 → 붉은 원
            painter.drawEllipse(QPoint(cx, cy), 4, 4)
        painter.restore()


class BookmarkTree(QWidget):
    """책갈피 트리. bookmarkActivated(file_path, page_index) 시그널.

    v1.6.2: PDF 내부 책갈피(TOC) 를 파일 노드의 자식으로 lazy load.
    """

    bookmarkActivated = pyqtSignal(str, int)
    favoriteRequested = pyqtSignal()      # v1.6.1 F4 (책갈피창 — 현재 폴더를 즐겨찾기 등록)
    addFileFavoriteRequested = pyqtSignal(str)  # 260615-4: ⑫ 특정 파일을 즐겨찾기 등록
    bookmarksEdited = pyqtSignal(str, str)   # v1.6.18: (src_pdf, edited_pdf) 저장 완료
    editCancelled = pyqtSignal()             # 260611-9: 편집 취소(저장 전 수정 되돌리기)
    addBookmarkRequested = pyqtSignal(str)   # v1.6.20: 대상 파일 경로 — 앱이 페이지/제목 받아옴
    createBookmarksRequested = pyqtSignal(str)  # 260606-4: 파일 우클릭 '책갈피 생성'(자동생성 다이얼로그)
    createStudyRequested = pyqtSignal(str)      # 260606-5: 파일 우클릭 '단어장 생성'
    createStudyBookmarksRequested = pyqtSignal(str)  # 260606-11: '단어장·책갈피 동시 생성'
    mergeFilesRequested = pyqtSignal(list)      # 260606-13: 선택 파일들 병합(경로 리스트)
    filePasswordEntered = pyqtSignal(str)    # 260618-1: 우클릭 '암호 입력' 성공 — 앱이 재로드
    releaseFileRequested = pyqtSignal(str)   # v1.6.21: 파일 작업 직전 — 앱이 핸들 해제
    fileOpCompleted = pyqtSignal(str, str)   # v1.6.21: (old, new) new=="" 삭제, new==old 실패

    DATA_FILE = Qt.ItemDataRole.UserRole + 0
    DATA_PAGE = Qt.ItemDataRole.UserRole + 1
    DATA_TOC_LOADED = Qt.ItemDataRole.UserRole + 2   # v1.6.2: TOC lazy load 완료 플래그
    DATA_IS_TOC_PLACEHOLDER = Qt.ItemDataRole.UserRole + 3   # v1.6.2: 펼치기 유도용 더미 자식 표식
    DATA_ENCRYPTED = _ENC_ROLE                       # 260611-57: 암호화 파일 표식
    DATA_AUTH = _AUTH_ROLE                            # 260618-1: 인증 상태(owner/user/locked)

    SORT_BOOK = "책갈피 순"
    SORT_NAME = "이름 순"
    SORT_MTIME = "수정일 순"
    SORT_SIZE = "크기 순"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_dir: Optional[Path] = None
        self._edit_mode: bool = False               # v1.6.18
        self._mode: str = "none"                    # v1.6.19: none|json|flat|single
        self._pdfs_flat: list = []                  # v1.6.19: 평탄 모드 파일 캐시
        self._dirty: bool = False                   # 260606-4: 편집 변경 여부
        self._reload_fn = None                       # 260611-9: 편집 취소 시 원본 재로드용
        # 260611-18(A4): 저장 버튼이 page_meta(숨김/회전/선긋기/이미지/하이퍼링크)도 저장
        self._meta_is_dirty = None                   # () -> bool
        self._meta_commit = None                     # () -> None (디스크 저장 + 썸네일 반영)
        # 260611-61: 네비게이션 합치기 — 선택 클릭이 click+currentChanged 로 2번 발화하는 것을
        #   1회로 합치고, 트리 선택 하이라이트가 먼저 그려진 뒤(지연) 이동/암호창이 뜨게 함.
        self._pending_nav = None
        self._nav_scheduled = False
        # 260611-59: 암호화/책갈피 표식을 배경(점진)으로 검사 — 시작·폴더로딩 지연 방지
        self._probe_queue: list = []
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(0)
        self._probe_timer.timeout.connect(self._probe_tick)
        self._build_ui()

    def set_meta_hooks(self, is_dirty_fn, commit_fn):
        """260611-18(A4): app 이 page_meta 미저장 여부·커밋을 주입."""
        self._meta_is_dirty = is_dirty_fn
        self._meta_commit = commit_fn

    def set_merge_allowed(self, allowed: bool):
        """260618-1: 현재 문서 권한에 따라 병합 메뉴 허용 여부(앱이 주입)."""
        self._merge_allowed = bool(allowed)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # v1.6.1 F4: 검색 입력창 + 즐겨찾기 추가 버튼
        from PyQt6.QtWidgets import QHBoxLayout, QPushButton
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("목록 명칭 검색...")
        self.search_edit.textChanged.connect(self._on_filter)
        search_row.addWidget(self.search_edit, 1)

        self.btn_fav = QPushButton("⭐")
        self.btn_fav.setFixedWidth(28)
        self.btn_fav.setToolTip("현재 폴더를 즐겨찾기에 추가")
        self.btn_fav.clicked.connect(self.favoriteRequested.emit)
        search_row.addWidget(self.btn_fav)
        layout.addLayout(search_row)

        # v1.6.19: 파일 정렬 콤보
        sort_row = QHBoxLayout()
        sort_row.setContentsMargins(0, 0, 0, 0)
        sort_row.addWidget(QLabel("정렬:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems([self.SORT_BOOK, self.SORT_NAME,
                                   self.SORT_MTIME, self.SORT_SIZE])
        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self._sort_combo, 1)
        layout.addLayout(sort_row)

        # v1.6.18: 책갈피 편집 툴바 (260606-4추가: 연필 아이콘 적용)
        self.btn_edit = QPushButton(" 편집")
        self.btn_edit.setCheckable(True)
        self.btn_edit.setToolTip("책갈피 편집 모드")
        # 260611-9: 편집 아이콘 — 비선택=파란 연필, 선택(편집 중)=붉은 연필
        from PyQt6.QtGui import QIcon
        from PyQt6.QtCore import QSize
        from viewer.resources_path import resource_path
        self._ico_edit_blue = QIcon(resource_path("icon_edit_blue.png") or
                                    resource_path("icon_edit.png") or "")
        self._ico_edit_red = QIcon(resource_path("icon_edit_red.png") or
                                   resource_path("icon_edit.png") or "")
        self.btn_edit.setIconSize(QSize(18, 18))
        self._update_edit_icon()
        self.btn_edit.toggled.connect(self.set_edit_mode)
        edit_row = QHBoxLayout()
        edit_row.setContentsMargins(0, 0, 0, 0)
        edit_row.addWidget(self.btn_edit)
        # 260611-61: 새로고침(↻) — 편집모드가 아닐 때만 노출. 외부에서 파일 추가 시 트리 갱신.
        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setFixedWidth(30)
        self.btn_refresh.setToolTip("책갈피 새로고침 (외부에서 파일이 추가/변경된 경우)")
        self.btn_refresh.clicked.connect(self.refresh)
        edit_row.addWidget(self.btn_refresh)
        # 260611-9: 편집 ↔ 저장 사이에 '취소'(저장 전 수정 되돌리기). 편집모드에서만 표시.
        self.btn_cancel = QPushButton(" 취소")
        _cp = resource_path("icon_cancel.png")
        if _cp:
            self.btn_cancel.setIcon(QIcon(_cp)); self.btn_cancel.setIconSize(QSize(18, 18))
        else:
            self.btn_cancel.setText("✖ 취소")
        self.btn_cancel.setToolTip("편집 후 저장 전의 수정 사항을 모두 취소(되돌리기)")
        self.btn_cancel.clicked.connect(self._op_cancel)
        self.btn_cancel.setVisible(False)
        edit_row.addWidget(self.btn_cancel)
        # 260611-8: 저장을 편집 오른쪽으로 — 편집/저장 모두 '파일 전체'를 대상으로 하므로 묶음.
        #   (단일/다중은 책갈피에만 작동 → ➕페이지 옆으로 이동)
        self.btn_save = QPushButton(" 저장")
        try:
            from PyQt6.QtGui import QIcon
            from PyQt6.QtCore import QSize
            from viewer.resources_path import resource_path
            _sp = resource_path("icon_save.png")
            if _sp:
                self.btn_save.setIcon(QIcon(_sp)); self.btn_save.setIconSize(QSize(18, 18))
            else:
                self.btn_save.setText("💾 저장")
        except Exception:
            self.btn_save.setText("💾 저장")
        self.btn_save.setToolTip("_edited.pdf 로 저장")
        self.btn_save.clicked.connect(self._op_save)
        self.btn_save.setVisible(False)
        edit_row.addWidget(self.btn_save)
        edit_row.addStretch(1)
        # 260611-73: 편집모드에서 편집/취소/저장을 전체 폭으로 균등 분배 → 아래 [다중]행·[삭제]행과
        #   동일한 폭으로 정렬. 비편집모드에서는 편집+↻만 왼쪽 정렬(나머지 stretch).
        from PyQt6.QtWidgets import QSizePolicy as _QSP0
        for _b in (self.btn_edit, self.btn_cancel, self.btn_save):
            _b.setSizePolicy(_QSP0.Policy.Expanding, _QSP0.Policy.Fixed)
            _b.setMinimumWidth(0)
        self._edit_row = edit_row
        self._apply_edit_row_stretch(False)
        # 260611-8: 책갈피 선택 단일/다중 — 라디오 2개 → 토글 버튼 1개(클릭마다 전환)
        self._multi_sel = True

        # 260611-18(C1·C2): 편집 보조 버튼을 2줄로 — 각 줄을 패널 전체 폭(편집/취소/저장 줄과
        #   동일)으로 채워 정렬. 1행 [다중] ◀ ▶ ▲ ▼ [책갈피명수정] / 2행 🗑️ ⭐선택만 📋복사.
        from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout as _QVBox
        from PyQt6.QtGui import QIcon as _QIcon
        from PyQt6.QtCore import QSize as _QSize

        def _expand(b):
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setMinimumWidth(0)
            return b

        self.edit_ops = QWidget()
        eo = _QVBox(self.edit_ops)
        eo.setContentsMargins(0, 0, 0, 0); eo.setSpacing(3)

        # 단일/다중 토글 — 책갈피 선택 전용
        self.btn_sel_mode = QPushButton("다중")
        self.btn_sel_mode.setToolTip("책갈피 선택: 단일 ↔ 다중 (클릭마다 전환)")
        self.btn_sel_mode.clicked.connect(self._toggle_sel_mode)
        # 책갈피명 수정(단일 편집) — 첨부 아이콘
        self.btn_edit_single = QPushButton()
        _bep = resource_path("icon_bookmark_edit.png")
        if _bep:
            self.btn_edit_single.setIcon(_QIcon(_bep)); self.btn_edit_single.setIconSize(_QSize(18, 18))
        else:
            self.btn_edit_single.setText("✎")
        self.btn_edit_single.setToolTip("책갈피명 수정 (단일 편집: 제목·페이지)")
        self.btn_edit_single.clicked.connect(self._op_edit_single)

        # 1행: [다중] ◀ ▶ ▲ ▼ [책갈피명수정] — 전체 폭 균등 분배
        row1 = QWidget()
        r1 = QHBoxLayout(row1); r1.setContentsMargins(0, 0, 0, 0); r1.setSpacing(3)
        for b in (self.btn_sel_mode,
                  self._mk_btn("◀", "내어쓰기 (상위로)", self._op_outdent),
                  self._mk_btn("▶", "들여쓰기 (하위로)", self._op_indent),
                  self._mk_btn("▲", "위로 이동 (같은 부모 안)", self._op_move_up),
                  self._mk_btn("▼", "아래로 이동 (같은 부모 안)", self._op_move_down),
                  self.btn_edit_single):
            r1.addWidget(_expand(b), 1)

        # 2행: 🗑️삭제 ⭐선택만 📋복사 — 전체 폭 균등 분배
        row2 = QWidget()
        r2 = QHBoxLayout(row2); r2.setContentsMargins(0, 0, 0, 0); r2.setSpacing(3)
        for b in (self._mk_btn("🗑️ 삭제", "선택 삭제", self._op_delete),
                  self._mk_btn("⭐ 선택만", "선택만 남기고 나머지 삭제", self._op_keep_selected),
                  self._mk_btn("📋 복사", "선택 파일을 다른 폴더로 복사", self._op_copy_to)):
            r2.addWidget(_expand(b), 1)

        eo.addWidget(row1)
        eo.addWidget(row2)
        self.edit_ops.setVisible(False)
        layout.addLayout(edit_row)
        layout.addWidget(self.edit_ops)

        self.tree = _EditableTree()
        self.tree.setHeaderHidden(True)
        self.tree.itemActivated.connect(self._on_activated)
        self.tree.itemClicked.connect(self._on_activated)
        # 260611-60: 선택만 바뀌어도(키보드 ↑↓ 등) 해당 파일·페이지로 이동
        self.tree.currentItemChanged.connect(self._on_current_changed)
        # 260606-4: 더블클릭=편집 창, 우클릭=컨텍스트 메뉴, 드롭=변경됨 표시
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self.tree.dropped.connect(self._on_tree_dropped)
        self.tree.delPressed.connect(self._on_del_key)    # 260611-56: DEL=선택 삭제
        # v1.6.2: 갈매기(▸) 펼침 시 PDF 내부 TOC lazy load
        self.tree.itemExpanded.connect(self._on_item_expanded)
        layout.addWidget(self.tree, 1)

        self.info = QLabel()
        self.info.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.info)

    def _mk_btn(self, text: str, tip: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    def _update_edit_icon(self):
        """260611-9: 편집 비선택=파란 연필 / 선택(편집 중)=붉은 연필."""
        self.btn_edit.setIcon(self._ico_edit_red if self.btn_edit.isChecked()
                              else self._ico_edit_blue)

    def _op_cancel(self):
        """260611-9: 편집 후 저장 전의 모든 수정 사항 취소(되돌리기). 편집모드는 유지."""
        if QMessageBox.question(
                self, "편집 취소",
                "저장 전의 모든 수정 사항을 취소(되돌리기)할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        if self._dirty and self._reload_fn is not None:
            try:
                self._reload_fn()        # 원본(디스크) 책갈피로 트리 재로드 → 편집 되돌림
            except Exception:
                pass
        self._dirty = False
        self._sync_selection_mode()
        self.editCancelled.emit()        # app: 숨김/회전/선긋기/하이퍼링크 스냅샷 복원

    # --- 로드 -------------------------------------------------------------

    def refresh(self):
        """260611-61: 현재 로드 소스를 다시 읽어 트리 갱신(외부에서 파일 추가/변경 시).
        편집 중이면 무시(되돌림 방지)."""
        if self._edit_mode:
            return
        if callable(self._reload_fn):
            self._reload_fn()

    def load_folder(self, folder: str | Path) -> bool:
        """folder 안의 bookmarks.json 을 우선 사용. 없으면 PDF 파일 목록을 트리로."""
        self._root_dir = Path(folder)
        self._reload_fn = lambda f=Path(folder): self.load_folder(f)   # 260611-9: 취소 재로드
        self._reset_probe_queue()
        self.tree.clear()

        json_path = self._root_dir / "bookmarks.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception as e:
                self.info.setText(f"bookmarks.json 읽기 실패: {e}")
                return False
            self._mode = "json"          # v1.6.19
            self._pdfs_flat = []
            self._populate_from_json(data)
            self.info.setText(
                f"{data.get('source_pdf', '')} · {data.get('total_pages', '?')}p"
            )
            return True

        # 폴더 안의 PDF 파일들을 평면 트리로
        self._mode = "flat"             # v1.6.19
        self._pdfs_flat = list(self._root_dir.rglob("*.pdf"))
        self._render_flat()             # 정렬 콤보 반영
        return True

    def _render_flat(self):
        """v1.6.19: 평탄 모드 렌더 — 현재 정렬 콤보 적용."""
        self._reset_probe_queue()
        self.tree.clear()
        pdfs = self._sorted_flat()
        for pdf in pdfs:
            item = QTreeWidgetItem([pdf.stem])
            item.setData(0, self.DATA_FILE, str(pdf))
            item.setData(0, self.DATA_PAGE, 0)
            self._decorate_file_node(item, pdf)
            self.tree.addTopLevelItem(item)
        self.info.setText(f"{len(pdfs)}개 PDF (bookmarks.json 없음)")

    def _sorted_flat(self) -> list:
        mode = self._sort_combo.currentText() if hasattr(self, "_sort_combo") else self.SORT_BOOK
        lst = list(self._pdfs_flat)
        if mode == self.SORT_NAME or mode == self.SORT_BOOK:
            # JSON 없는 평탄 모드에서 '책갈피 순'은 의미가 없으므로 이름 순 폴백
            lst.sort(key=lambda p: p.stem.lower())
        elif mode == self.SORT_MTIME:
            lst.sort(key=lambda p: _stat(p).st_mtime, reverse=True)
        elif mode == self.SORT_SIZE:
            lst.sort(key=lambda p: _stat(p).st_size, reverse=True)
        return lst

    def _on_sort_changed(self, _text: str):
        """정렬 콤보 변경 — 평탄 모드에서만 재렌더."""
        if self._mode == "flat":
            self._render_flat()
        # json/single 모드는 무시 (JSON 순서/단일 파일 유지)

    def load_single_pdf(self, pdf_path: str | Path) -> bool:
        """v1.6.11 I1/I2: 단일 PDF 한 개만 트리에 표시 (내부 TOC lazy load)."""
        p = Path(pdf_path)
        self._root_dir = p.parent
        self._reload_fn = lambda pp=p: self.load_single_pdf(pp)   # 260611-9: 취소 재로드
        self._mode = "single"            # v1.6.19
        self._pdfs_flat = []
        self._reset_probe_queue()
        self.tree.clear()
        if not p.exists():
            self.info.setText(f"파일 없음: {p.name}")
            return False
        item = QTreeWidgetItem([p.stem])      # .pdf 제거 (M2)
        item.setData(0, self.DATA_FILE, str(p))
        item.setData(0, self.DATA_PAGE, 0)
        self._decorate_file_node(item, p)      # 암호화 표식 + 책갈피 있으면 ▸
        self.tree.addTopLevelItem(item)
        item.setExpanded(False)
        self.info.setText(f"{p.name} (단일 파일)")
        return True

    def all_file_paths(self) -> list:
        """260616-3: 현재 트리에 표시된 모든 PDF 파일 경로(중복 제거, 출현 순).
        검색 범위를 '책갈피 목록'으로 한정하는 데 사용(json/flat/single 모드 공통)."""
        out: list = []
        seen: set = set()

        def walk(item):
            for i in range(item.childCount()):
                ch = item.child(i)
                f = ch.data(0, self.DATA_FILE)
                if f and f not in seen:
                    seen.add(f)
                    out.append(f)
                walk(ch)

        walk(self.tree.invisibleRootItem())
        return out

    def _populate_from_json(self, data: dict):
        bookmarks = data.get("bookmarks", [])

        def add(parent_item, nodes):
            for node in nodes:
                # v1.5.0 M2: 표시 제목에서 .pdf 확장자 제거
                display_title = node["title"]
                if display_title.lower().endswith(".pdf"):
                    display_title = display_title[:-4]
                item = QTreeWidgetItem([display_title])
                full_path: Optional[Path] = None
                if node.get("file"):
                    full_path = self._root_dir / node["file"]
                    item.setData(0, self.DATA_FILE, str(full_path))
                    item.setData(0, self.DATA_PAGE, 0)
                    item.setIcon(0, self._leaf_icon())
                else:
                    item.setIcon(0, self._dir_icon())
                # 페이지 정보를 부가 표시
                if node.get("page_start") and node.get("page_end"):
                    if node["page_start"] == node["page_end"]:
                        item.setText(0, f"{display_title}  (p.{node['page_start']})")
                    else:
                        item.setText(0,
                            f"{display_title}  (p.{node['page_start']}–{node['page_end']})")
                if parent_item is None:
                    self.tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                add(item, node.get("children", []))
                # v1.6.2/260611-59: 파일 노드는 배경 검사 큐에 등록(암호화 표식 + 책갈피 있으면 ▸)
                #   json 자식이 있으면 _probe_tick 가 placeholder 는 부착하지 않음(childCount>0).
                if full_path is not None:
                    self._decorate_file_node(item, full_path)

        self._reset_probe_queue()
        add(None, bookmarks)
        self.tree.expandToDepth(0)

    # --- v1.6.2: PDF 내부 TOC -------------------------------------------
    def _probe_pdf(self, pdf_path):
        """260611-57/260618-1: (암호화여부, 책갈피보유, 인증상태) 반환. 결과 캐시(경로+크기+mtime).
        암호화+미인증이면 저장된 암호로 해제 시도, 실패하면 책갈피여부 None(미상).
        인증상태: None(암호화 아님) / "owner"(전체 권한) / "user"(제한 암호) / "locked"(미인증)."""
        p = Path(pdf_path)
        try:
            st = p.stat(); key = (str(p), int(st.st_size), int(st.st_mtime))
        except Exception:
            return (False, False, None)
        cache = getattr(self, "_probe_cache", None)
        if cache is None:
            cache = self._probe_cache = {}
        if key in cache:
            return cache[key]
        enc = False; has_toc = False; auth = None
        try:
            doc = fitz.open(str(p))
            try:
                enc = bool(doc.needs_pass)
                if enc:
                    auth = "locked"
                    try:
                        from viewer import secure_store
                        pw = secure_store.recall_any(str(p))
                    except Exception:
                        pw = None
                    lvl = doc.authenticate(pw) if pw else 0
                    if lvl:
                        # PyMuPDF authenticate: 4=owner(전체), 2=user(제한). 둘 다면 owner.
                        auth = "owner" if (lvl & 4) else "user"
                        has_toc = bool(doc.get_toc())
                    else:
                        has_toc = None          # 미상(잠김)
                else:
                    has_toc = bool(doc.get_toc())
            finally:
                doc.close()
        except Exception:
            enc = False; has_toc = False; auth = None
        cache[key] = (enc, has_toc, auth)
        return cache[key]

    def _decorate_file_node(self, item: QTreeWidgetItem, pdf_path: Path):
        """260611-57/59: 암호화·책갈피 검사를 '배경 큐'에 등록(시작 지연 방지).
        실제 표식(붉은 삼각형/원·펼침 placeholder)은 _probe_tick 에서 점진 적용."""
        self._probe_queue.append((item, str(pdf_path)))
        if not self._probe_timer.isActive():
            self._probe_timer.start()

    def _reset_probe_queue(self):
        """트리 재구성 시 이전 큐(이미 삭제된 항목 참조) 폐기."""
        self._probe_queue = []
        self._probe_timer.stop()

    def _probe_tick(self):
        """한 번에 소량만 검사해 UI 응답성 유지. 빈 큐면 타이머 정지."""
        if not self._probe_queue:
            self._probe_timer.stop()
            return
        for _ in range(6):
            if not self._probe_queue:
                break
            item, path = self._probe_queue.pop(0)
            try:
                enc, has_toc, auth = self._probe_pdf(Path(path))
                if enc:
                    item.setData(0, self.DATA_ENCRYPTED, True)
                    item.setData(0, self.DATA_AUTH, auth)
                    item.setToolTip(0, self._enc_tooltip(auth))
                if has_toc and item.childCount() == 0:   # json 자식 있으면 부착 안 함
                    self._attach_toc_placeholder(item, Path(path))
            except RuntimeError:
                continue        # 항목이 이미 삭제됨(트리 재구성)
            except Exception:
                continue
        if not self._probe_queue:
            self._probe_timer.stop()
        try:
            self.tree.viewport().update()
        except Exception:
            pass

    @staticmethod
    def _enc_tooltip(auth) -> str:
        """260618-1: 암호화 파일 인증 상태별 툴팁."""
        if auth == "owner":
            return "암호화 설정 파일 - 암호 열음"
        if auth == "user":
            return "암호화 설정 파일 - 제한 암호로 열음"
        return "암호화 설정 파일"

    def _prompt_file_password(self, item: QTreeWidgetItem, path: str):
        """260618-1: 우클릭 '암호 입력' — 마스터/제한 무관 새 암호로 잠금 해제.
        성공 시 세션 저장 + 표식(색·툴팁) 갱신 + filePasswordEntered 발행."""
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        pw, ok = QInputDialog.getText(
            self, "암호 입력",
            f"'{Path(path).name}'\n암호를 입력하세요 (마스터/제한 암호 모두 가능):",
            QLineEdit.EchoMode.Password)
        if not ok:
            return
        try:
            doc = fitz.open(path)
        except Exception as e:
            QMessageBox.warning(self, "암호 입력", f"파일을 열 수 없습니다:\n{e}")
            return
        try:
            lvl = doc.authenticate(pw or "")
        finally:
            doc.close()
        if not lvl:
            QMessageBox.warning(self, "암호 입력", "암호가 올바르지 않습니다.")
            return
        try:
            from viewer import secure_store
            secure_store.set_session(path, pw)
        except Exception:
            pass
        # 캐시 무효화 후 재검사 → 색·툴팁 즉시 반영
        cache = getattr(self, "_probe_cache", None)
        if cache:
            for k in [k for k in cache if k[0] == str(Path(path))]:
                cache.pop(k, None)
        try:
            enc, _has, auth = self._probe_pdf(Path(path))
            if enc:
                item.setData(0, self.DATA_ENCRYPTED, True)
                item.setData(0, self.DATA_AUTH, auth)
                item.setToolTip(0, self._enc_tooltip(auth))
        except Exception:
            pass
        try:
            self.tree.viewport().update()
        except Exception:
            pass
        self.filePasswordEntered.emit(path)

    def _attach_toc_placeholder(self, leaf_item: QTreeWidgetItem, pdf_path: Path):
        """리프(파일 노드)에 펼침 표시(▸) 유도용 더미 자식을 붙임.

        실제 TOC 는 사용자가 펼칠 때 `_on_item_expanded` 가 lazy load.
        TOC 가 없는 PDF 도 처음에는 갈매기가 보이지만, 펼치면 사라짐
        (UX 단순화 — 폴더 로딩 시 모든 PDF 를 열어보는 비용 회피).
        """
        ph = QTreeWidgetItem(["…"])
        ph.setData(0, self.DATA_IS_TOC_PLACEHOLDER, True)
        ph.setDisabled(True)
        leaf_item.addChild(ph)

    def _on_item_expanded(self, item: QTreeWidgetItem):
        # 이미 로드한 적 있으면 패스
        if item.data(0, self.DATA_TOC_LOADED):
            return
        # 자식 중 placeholder 가 있는지 확인
        ph_idx = -1
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, self.DATA_IS_TOC_PLACEHOLDER):
                ph_idx = i
                break
        if ph_idx < 0:
            return

        file_path = item.data(0, self.DATA_FILE)
        if not file_path or not Path(file_path).exists():
            item.takeChild(ph_idx)
            item.setData(0, self.DATA_TOC_LOADED, True)
            return

        # TOC 읽기 (암호화 파일은 저장된 암호로 해제 시도)
        toc: list = []
        try:
            doc = fitz.open(file_path)
            try:
                authed = True
                if doc.needs_pass:
                    try:
                        from viewer import secure_store
                        pw = secure_store.recall_any(file_path)
                    except Exception:
                        pw = None
                    authed = bool(pw and doc.authenticate(pw))
                if authed:
                    toc = doc.get_toc() or []
            finally:
                doc.close()
        except Exception:
            toc = []

        # placeholder 제거
        item.takeChild(ph_idx)
        item.setData(0, self.DATA_TOC_LOADED, True)

        if not toc:
            # 내부 책갈피 없음 → 펼침 표시 숨김 (자식이 없어지므로 자동)
            return

        # 평탄한 (level, title, page1based) 리스트 → 중첩 트리로
        stack = [item]
        levels = [0]
        for level, title, page in toc:
            while levels and levels[-1] >= level:
                stack.pop()
                levels.pop()
            if not stack:
                stack = [item]; levels = [0]
            child = QTreeWidgetItem([str(title).strip() or "(제목 없음)"])
            child.setData(0, self.DATA_FILE, file_path)
            # PyMuPDF TOC 페이지는 1-based, bookmarkActivated 는 0-based
            child.setData(0, self.DATA_PAGE, max(0, int(page) - 1))
            child.setData(0, self.DATA_TOC_LOADED, True)  # TOC 자식은 더 펼치지 않음
            stack[-1].addChild(child)
            stack.append(child)
            levels.append(level)

    def _leaf_icon(self):
        from PyQt6.QtGui import QIcon
        return QIcon()

    def _dir_icon(self):
        from PyQt6.QtGui import QIcon
        return QIcon()

    # --- 필터 -------------------------------------------------------------

    def _on_filter(self, text: str):
        text = text.lower().strip()

        def match(item: QTreeWidgetItem) -> bool:
            if not text or text in item.text(0).lower():
                ok = True
            else:
                ok = False
            child_match = False
            for i in range(item.childCount()):
                if match(item.child(i)):
                    child_match = True
            visible = ok or child_match
            item.setHidden(not visible)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            match(self.tree.topLevelItem(i))

    # --- 활성화 -----------------------------------------------------------

    def _on_activated(self, item: QTreeWidgetItem, _column: int = 0):
        if item is None or item.data(0, self.DATA_IS_TOC_PLACEHOLDER):
            return
        # 260611-9: 편집모드에서 Ctrl/Shift+클릭은 '다중 선택' 제스처 → 메인 이동을 하지 않음.
        #   (이동하면 select_for_page 가 setCurrentItem 으로 다중 선택을 깨뜨려 다중선택 실패)
        from PyQt6.QtWidgets import QApplication
        mods = QApplication.keyboardModifiers()
        if (self._edit_mode and (mods & (Qt.KeyboardModifier.ControlModifier
                                         | Qt.KeyboardModifier.ShiftModifier))):
            return
        path = item.data(0, self.DATA_FILE)
        # 260606-4: 편집 모드에서도 선택 시 해당 책갈피 위치로 메인 이동
        if self._edit_mode:
            if path:
                self._emit_nav(path, item.data(0, self.DATA_PAGE) or 0)
            return
        if not path:
            # 가지 노드면 펼치기/접기
            item.setExpanded(not item.isExpanded())
            return
        self._emit_nav(path, item.data(0, self.DATA_PAGE) or 0)

    def _emit_nav(self, path, page):
        """260611-61: 클릭의 이중 발화를 1회로 합치고, 선택 하이라이트가 먼저
        그려진 뒤 이동(+암호창)이 뜨도록 지연 발행."""
        self._pending_nav = (path, int(page or 0))
        if not self._nav_scheduled:
            self._nav_scheduled = True
            QTimer.singleShot(0, self._flush_nav)

    def _flush_nav(self):
        self._nav_scheduled = False
        nav = self._pending_nav
        self._pending_nav = None
        if nav:
            self.bookmarkActivated.emit(nav[0], int(nav[1]))

    def _on_current_changed(self, cur, _prev):
        """260611-60: 선택 항목 변경 시(키보드 이동 포함) 파일/페이지로 이동.
        편집모드의 Ctrl/Shift 다중선택 제스처와 프로그램적 선택(blockSignals)은 제외."""
        if cur is None:
            return
        from PyQt6.QtWidgets import QApplication
        mods = QApplication.keyboardModifiers()
        if self._edit_mode and (mods & (Qt.KeyboardModifier.ControlModifier
                                        | Qt.KeyboardModifier.ShiftModifier)):
            return
        path = cur.data(0, self.DATA_FILE)
        if path and not cur.data(0, self.DATA_IS_TOC_PLACEHOLDER):
            self._emit_nav(path, cur.data(0, self.DATA_PAGE) or 0)

    # ---- 260606-4: 더블클릭 편집 / 우클릭 메뉴 / 변경 추적 ----------------
    def _mark_dirty(self):
        self._dirty = True

    def _on_tree_dropped(self):
        if self._edit_mode:
            self._dirty = True

    def _edit_item(self, item: Optional[QTreeWidgetItem]):
        """항목 종류에 맞는 편집 창(파일명 / 책갈피 제목·페이지)."""
        if item is None or item.data(0, self.DATA_IS_TOC_PLACEHOLDER):
            return
        if item.parent() is None and item.data(0, self.DATA_FILE):
            self._edit_file_node(item)
            return
        target = self._target_file_item() or _top_of(item)
        if target is not None and target.data(0, self.DATA_FILE):
            self._edit_bookmark_node(item, target)
        else:
            QMessageBox.information(self, "안내", "대상 PDF 파일을 알 수 없습니다.")

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int = 0):
        if not self._edit_mode:
            return
        self._edit_item(item)

    def _on_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None or item.data(0, self.DATA_IS_TOC_PLACEHOLDER):
            return
        # 260606-13: 편집모드에서 여러 파일 선택 후 우클릭 → 병합 메뉴(선택 유지)
        sel_files = [it for it in self.tree.selectedItems()
                     if it.parent() is None and it.data(0, self.DATA_FILE)]
        if not (self._edit_mode and item.isSelected() and len(sel_files) >= 2):
            if not item.isSelected():
                self.tree.setCurrentItem(item)
            sel_files = []
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        act_merge = None
        if sel_files and getattr(self, "_merge_allowed", True):   # 260618-1: 권한 없으면 숨김
            act_merge = menu.addAction(f"선택 {len(sel_files)}개 파일 병합...")
            menu.addSeparator()
        # 260606-4: 파일(최상위) 노드면 (책갈피 생성, 책갈피 편집)도 제공
        is_file = item.parent() is None and bool(item.data(0, self.DATA_FILE))
        act_create = act_editmode = None
        act_study = act_study_bm = None
        act_password = None
        if is_file:
            # 260618-1: 암호화 파일이면 '암호 입력'(마스터/제한 무관 새 암호)
            if item.data(0, self.DATA_ENCRYPTED):
                act_password = menu.addAction("암호 입력")
                menu.addSeparator()
            act_create = menu.addAction("책갈피 생성")
            act_editmode = menu.addAction("책갈피 편집")
            act_study = menu.addAction("단어장 생성")
            act_study_bm = menu.addAction("단어장·책갈피 동시 생성")
            menu.addSeparator()
        # 260615-4: ⑫ 즐겨찾기 등록(현재 폴더 / 현재 파일)
        act_fav_folder = menu.addAction("현재 폴더를 즐겨찾기에 추가")
        act_fav_file = menu.addAction("현재 파일을 즐겨찾기에 추가") if is_file else None
        menu.addSeparator()
        act_rename = menu.addAction("이름 변경")
        act_delete = menu.addAction("삭제")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_merge:
            self.mergeFilesRequested.emit([it.data(0, self.DATA_FILE) for it in sel_files])
        elif act_password is not None and chosen == act_password:
            self._prompt_file_password(item, item.data(0, self.DATA_FILE))
        elif chosen == act_create:
            self.createBookmarksRequested.emit(item.data(0, self.DATA_FILE))
        elif chosen == act_editmode:
            self.set_edit_mode(True)
        elif chosen == act_study:
            self.createStudyRequested.emit(item.data(0, self.DATA_FILE))
        elif chosen == act_study_bm:
            self.createStudyBookmarksRequested.emit(item.data(0, self.DATA_FILE))
        elif chosen == act_fav_folder:
            self.favoriteRequested.emit()
        elif act_fav_file is not None and chosen == act_fav_file:
            self.addFileFavoriteRequested.emit(item.data(0, self.DATA_FILE))
        elif chosen == act_rename:
            self._edit_item(item)
        elif chosen == act_delete:
            self._op_delete()

    # ===== v1.6.18: 책갈피 편집 모드 ========================================
    def _apply_edit_row_stretch(self, on: bool):
        """260611-73: 편집/취소/저장 행 폭 분배.
        항목 인덱스: 0=편집 1=↻새로고침 2=취소 3=저장 4=trailing stretch.
        on=True  → 편집·취소·저장 균등(전체 폭, 아래 행들과 동일),
        on=False → 편집+↻만 왼쪽 정렬(뒤쪽 stretch)."""
        r = getattr(self, "_edit_row", None)
        if r is None:
            return
        r.setStretch(0, 1 if on else 0)   # 편집
        r.setStretch(2, 1 if on else 0)   # 취소
        r.setStretch(3, 1 if on else 0)   # 저장
        r.setStretch(4, 0 if on else 1)   # trailing stretch

    def is_edit_mode(self) -> bool:
        return self._edit_mode

    def set_edit_mode(self, on: bool):
        on = bool(on)
        # 260606-4: 편집 모드를 끌 때 변경분이 있으면 저장 여부 확인
        if not on and self._edit_mode and self._dirty:
            ret = QMessageBox.question(
                self, "편집 종료",
                "수정한 내용이 있습니다. 저장할까요?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if ret == QMessageBox.StandardButton.Cancel:
                # 편집 모드 유지
                self.btn_edit.blockSignals(True)
                self.btn_edit.setChecked(True)
                self.btn_edit.blockSignals(False)
                return
            if ret == QMessageBox.StandardButton.Save:
                self._op_save()
            self._dirty = False
        self._edit_mode = on
        if on:
            self._dirty = False
        self.edit_ops.setVisible(on)
        self.btn_save.setVisible(on)          # 260611-8: 저장은 편집모드에서만
        self.btn_cancel.setVisible(on)        # 260611-9: 취소도 편집모드에서만
        self.btn_refresh.setVisible(not on)   # 260611-61: 새로고침은 비편집모드에서만
        self._apply_edit_row_stretch(on)      # 260611-73: 편집모드=3버튼 전체폭 균등
        self.btn_edit.blockSignals(True)
        self.btn_edit.setChecked(on)
        self.btn_edit.blockSignals(False)
        self._update_edit_icon()              # 260611-9: 파랑↔빨강
        self._sync_selection_mode()
        # v1.6.19: 마우스 드래그 이동(편집 모드에서만)
        if on:
            self.tree.setDragEnabled(True)
            self.tree.setAcceptDrops(True)
            self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.tree.setDropIndicatorShown(True)
        else:
            self.tree.setDragEnabled(False)
            self.tree.setAcceptDrops(False)
            self.tree.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            self.tree.setDropIndicatorShown(False)

    def _toggle_sel_mode(self):
        """260611-8: 단일↔다중 토글(클릭마다 전환). 책갈피 선택 모드에만 영향."""
        self._multi_sel = not self._multi_sel
        self.btn_sel_mode.setText("다중" if self._multi_sel else "단일")
        self._sync_selection_mode()

    def _sync_selection_mode(self, *_):
        if not self._edit_mode:
            self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            return
        mode = (QAbstractItemView.SelectionMode.ExtendedSelection
                if self._multi_sel
                else QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSelectionMode(mode)

    # ---- target 파일 식별 -----------------------------------------------
    def _target_file_item(self) -> Optional[QTreeWidgetItem]:
        """편집 대상 파일 노드. 단일 PDF 모드면 그 파일, 폴더 모드면 선택 항목 기준."""
        n = self.tree.topLevelItemCount()
        sel = self.tree.selectedItems()
        # 1) 단일 PDF 트리
        roots_with_file = [self.tree.topLevelItem(i)
                           for i in range(n)
                           if self.tree.topLevelItem(i).data(0, self.DATA_FILE)]
        if len(roots_with_file) == 1:
            return roots_with_file[0]
        # 2) 선택의 최상위 조상
        if sel:
            # 모두 같은 최상위에 있어야 함
            def top_of(it: QTreeWidgetItem) -> QTreeWidgetItem:
                while it.parent() is not None:
                    it = it.parent()
                return it
            tops = {id(top_of(it)): top_of(it) for it in sel}
            if len(tops) == 1:
                t = next(iter(tops.values()))
                if t.data(0, self.DATA_FILE):
                    return t
        return None

    # ---- 선택 항목 수집 -------------------------------------------------
    def _selected_editable(self, target: QTreeWidgetItem) -> list:
        """target 자손인 선택 항목만(placeholder/플래그/파일노드 제외).

        조상-자손 관계 중복 제거 — 조상만 남김 (삭제·들여쓰기 일관 처리).
        """
        sel = [it for it in self.tree.selectedItems()
               if it is not target
               and not it.data(0, self.DATA_IS_TOC_PLACEHOLDER)
               and _is_descendant(it, target)]
        # 조상이 이미 선택에 있으면 자손은 제외
        sel_set = set(map(id, sel))
        result = []
        for it in sel:
            p = it.parent()
            skip = False
            while p is not None and p is not target:
                if id(p) in sel_set:
                    skip = True
                    break
                p = p.parent()
            if not skip:
                result.append(it)
        return result

    # ---- 들여쓰기 / 내어쓰기 -------------------------------------------
    def _op_indent(self):
        target = self._target_file_item()
        if target is None:
            QMessageBox.information(self, "안내", "편집할 PDF 파일을 트리에서 선택하세요.")
            return
        items = self._selected_editable(target)
        if not items:
            return
        # 트리 출현 순서대로
        items.sort(key=lambda it: _path_to(it, target))
        for it in items:
            parent = it.parent() or target
            idx = parent.indexOfChild(it)
            if idx <= 0:
                continue
            prev = parent.child(idx - 1)
            parent.takeChild(idx)
            prev.addChild(it)
            prev.setExpanded(True)
        self._mark_dirty()

    def _op_outdent(self):
        target = self._target_file_item()
        if target is None:
            QMessageBox.information(self, "안내", "편집할 PDF 파일을 트리에서 선택하세요.")
            return
        items = self._selected_editable(target)
        if not items:
            return
        # 역순(bottom-up)
        items.sort(key=lambda it: _path_to(it, target), reverse=True)
        for it in items:
            parent = it.parent()
            if parent is None or parent is target:
                continue        # 이미 최상위 (level 0) — 더 못 올림
            grand = parent.parent() or target
            p_idx = grand.indexOfChild(parent)
            parent.takeChild(parent.indexOfChild(it))
            grand.insertChild(p_idx + 1, it)
        self._mark_dirty()

    # ---- 삭제 / 선택만 남기기 ------------------------------------------
    def _on_del_key(self):
        """260611-56: 편집 모드에서 DEL 키 → 휴지통 버튼과 동일(선택 삭제)."""
        if self._edit_mode:
            self._op_delete()

    def _op_delete(self):
        """v1.6.20 K3: 파일 노드는 휴지통, 책갈피 노드는 트리에서 제거(혼합 허용)."""
        sel = [it for it in self.tree.selectedItems()
               if not it.data(0, self.DATA_IS_TOC_PLACEHOLDER)]
        if not sel:
            return
        files = [it for it in sel
                 if it.parent() is None and it.data(0, self.DATA_FILE)]
        bookmarks = [it for it in sel if it not in files]
        # 책갈피 노드는 target 자손인 것만
        if bookmarks:
            target = self._target_file_item()
            if target is not None:
                bookmarks = [it for it in bookmarks if _is_descendant(it, target)]
                # 조상 중복 제거
                sel_set = set(map(id, bookmarks))
                bookmarks = [it for it in bookmarks
                             if not any(id(_a) in sel_set
                                        for _a in _ancestors(it, target))]
            else:
                bookmarks = []

        if not files and not bookmarks:
            QMessageBox.information(self, "안내", "삭제할 항목이 없습니다.")
            return

        # 확인 메시지 구성
        msg_parts = []
        if files:
            if not _HAS_TRASH:
                QMessageBox.warning(self, "send2trash 필요",
                    "파일 삭제(휴지통)는 send2trash 모듈이 필요합니다.\n"
                    "  pip install send2trash")
                return
            msg_parts.append(f"PDF 파일 {len(files)}개를 휴지통으로 보냅니다.")
        if bookmarks:
            msg_parts.append(f"책갈피 {len(bookmarks)}개를 트리에서 제거합니다.")
        if QMessageBox.question(
            self, "삭제 확인", "\n".join(msg_parts) + "\n계속할까요?"
        ) != QMessageBox.StandardButton.Yes:
            return

        # 책갈피 제거 (선택만)
        for it in bookmarks:
            parent = it.parent() or self._target_file_item()
            if parent is not None:
                parent.takeChild(parent.indexOfChild(it))
        if bookmarks:
            self._mark_dirty()

        # 파일 삭제 (휴지통) — v1.6.21: 작업 직전 핸들 해제 핸드셰이크
        trashed = 0
        for it in files:
            p = Path(it.data(0, self.DATA_FILE))
            self.releaseFileRequested.emit(str(p))
            QApplication.processEvents()
            try:
                _send2trash(str(p))
                trashed += 1
                idx = self.tree.indexOfTopLevelItem(it)
                if idx >= 0:
                    self.tree.takeTopLevelItem(idx)
                # 평탄 모드 캐시 동기화
                if self._mode == "flat":
                    self._pdfs_flat = [q for q in self._pdfs_flat if q != p]
                self.fileOpCompleted.emit(str(p), "")        # 삭제 — 메인 비움 유지
            except Exception as e:
                QMessageBox.warning(self, "휴지통 이동 실패", f"{p.name}: {e}")
                self.fileOpCompleted.emit(str(p), str(p))    # revert → 원본 재로드
        if trashed:
            self.info.setText(f"파일 {trashed}개 휴지통으로 이동됨")

    def _op_copy_to(self):
        """v1.6.20 K4: 선택한 PDF 파일들을 다른 폴더로 복사."""
        sel = [it for it in self.tree.selectedItems()
               if it.parent() is None and it.data(0, self.DATA_FILE)]
        if not sel:
            QMessageBox.information(self, "안내", "복사할 PDF 파일(최상위 항목)을 선택하세요.")
            return
        start = str(self._root_dir) if self._root_dir else ""
        dst_dir = QFileDialog.getExistingDirectory(self, "복사 대상 폴더", start)
        if not dst_dir:
            return
        dst = Path(dst_dir)
        copied = 0
        errors = []
        for it in sel:
            src = Path(it.data(0, self.DATA_FILE))
            if not src.exists():
                errors.append(f"{src.name}: 원본 없음")
                continue
            target = _unique_path(dst / src.name)
            try:
                shutil.copy2(src, target)
                copied += 1
            except Exception as e:
                errors.append(f"{src.name}: {e}")
        msg = f"{copied}개 파일을 {dst} 로 복사했습니다."
        if errors:
            msg += "\n실패: " + ", ".join(errors[:5])
        QMessageBox.information(self, "복사 완료", msg)

    def _op_keep_selected(self):
        target = self._target_file_item()
        if target is None:
            return
        items = [it for it in self.tree.selectedItems()
                 if it is not target
                 and not it.data(0, self.DATA_IS_TOC_PLACEHOLDER)
                 and _is_descendant(it, target)]
        if not items:
            return
        keep = set()
        for it in items:
            cur = it
            while cur is not None and cur is not target:
                keep.add(id(cur))
                cur = cur.parent()
        # target 자손 중 keep 에 없는 노드 삭제 — bottom-up
        def prune(node: QTreeWidgetItem):
            for i in reversed(range(node.childCount())):
                ch = node.child(i)
                prune(ch)
                if id(ch) not in keep and not ch.data(0, self.DATA_IS_TOC_PLACEHOLDER):
                    node.takeChild(i)
        if QMessageBox.question(
            self, "확인", "선택한 항목과 그 조상만 남기고 나머지를 삭제할까요?"
        ) != QMessageBox.StandardButton.Yes:
            return
        prune(target)
        self._mark_dirty()

    # ---- 단일 편집 -------------------------------------------------------
    def _op_edit_single(self):
        sel = [it for it in self.tree.selectedItems()
               if not it.data(0, self.DATA_IS_TOC_PLACEHOLDER)]
        if len(sel) != 1:
            QMessageBox.information(self, "안내", "편집할 항목 1개를 선택하세요.")
            return
        it = sel[0]
        # v1.6.20: 최상위 파일 노드면 파일명 변경 다이얼로그
        if it.parent() is None and it.data(0, self.DATA_FILE):
            self._edit_file_node(it)
            return
        # 일반 책갈피 — 제목/페이지
        target = self._target_file_item() or _top_of(it)
        if target is None or not target.data(0, self.DATA_FILE):
            QMessageBox.information(self, "안내", "대상 PDF 파일을 알 수 없습니다.")
            return
        self._edit_bookmark_node(it, target)

    def _edit_bookmark_node(self, it: QTreeWidgetItem, target: QTreeWidgetItem):
        # 페이지 범위 — 가능하면 PDF 의 페이지수로
        max_page = 1
        try:
            d = fitz.open(target.data(0, self.DATA_FILE))
            try:
                max_page = max(1, d.page_count)
            finally:
                d.close()
        except Exception:
            max_page = 9999
        cur_title = _PAGE_BADGE_RE.sub("", it.text(0)).rstrip()
        cur_page = int(it.data(0, self.DATA_PAGE) or 0) + 1

        dlg = QDialog(self)
        dlg.setWindowTitle("책갈피 편집")
        dlg.setMinimumWidth(560)                    # v1.6.20 K1
        f = QFormLayout(dlg)
        ed_title = QLineEdit(cur_title)
        ed_title.setMinimumWidth(460)               # v1.6.20 K1
        f.addRow("제목:", ed_title)
        sp_page = QSpinBox()
        sp_page.setRange(1, max_page)
        sp_page.setValue(min(max_page, max(1, cur_page)))
        f.addRow("페이지:", sp_page)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_title = ed_title.text().strip() or "(제목 없음)"
        new_page = int(sp_page.value())
        it.setText(0, f"{new_title}  (p.{new_page})")
        it.setData(0, self.DATA_PAGE, new_page - 1)
        self._mark_dirty()

    def _edit_file_node(self, it: QTreeWidgetItem):
        """v1.6.20 K2: 파일 노드 단일 편집 → 디스크상 파일명 변경."""
        old_path = Path(it.data(0, self.DATA_FILE))
        cur_stem = old_path.stem

        dlg = QDialog(self)
        dlg.setWindowTitle("파일명 변경")
        dlg.setMinimumWidth(560)
        f = QFormLayout(dlg)
        ed_name = QLineEdit(cur_stem)
        ed_name.setMinimumWidth(460)
        f.addRow("파일명 (.pdf 제외):", ed_name)
        hint = QLabel("<small>변경 시 디스크상 파일이 함께 이름이 바뀝니다. "
                      "메인 뷰어에서 열려 있으면 잠시 다른 파일로 전환 후 시도하세요.</small>")
        hint.setStyleSheet("color:#666;"); hint.setWordWrap(True)
        f.addRow("", hint)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_stem = ed_name.text().strip()
        if not new_stem or _INVALID_FILENAME_RE.search(new_stem):
            QMessageBox.warning(self, "오류", "파일명에 사용할 수 없는 글자가 있습니다.")
            return
        new_path = old_path.with_name(new_stem + old_path.suffix)
        if new_path == old_path:
            return
        if new_path.exists():
            QMessageBox.warning(self, "오류", f"같은 이름의 파일이 이미 있습니다: {new_path.name}")
            return
        # v1.6.21: 메인 뷰어가 같은 파일을 열고 있으면 잠시 닫도록 알림
        self.releaseFileRequested.emit(str(old_path))
        QApplication.processEvents()
        try:
            old_path.rename(new_path)
        except Exception as e:
            QMessageBox.warning(self, "변경 실패",
                f"파일 이름 변경 실패: {e}\n"
                "다른 프로그램이 파일을 잡고 있을 수 있습니다.")
            self.fileOpCompleted.emit(str(old_path), str(old_path))   # revert → 원본 재로드
            return
        it.setText(0, new_path.stem)
        it.setData(0, self.DATA_FILE, str(new_path))
        self.fileOpCompleted.emit(str(old_path), str(new_path))       # 재로드 (성공)

    # ---- v1.6.20 K5: 메인 페이지로 책갈피 추가 -------------------------
    def _op_add_main_bookmark(self):
        target = self._target_file_item()
        if target is None or not target.data(0, self.DATA_FILE):
            QMessageBox.information(self, "안내",
                "책갈피를 추가할 PDF 파일을 트리에서 선택하거나 펼치세요.")
            return
        # 앱에 대상 파일 알림 → 앱이 메인 뷰어 페이지/제목을 받아 add_bookmark 호출
        self.addBookmarkRequested.emit(target.data(0, self.DATA_FILE))

    def add_bookmark(self, file_path: str, page_1based: int, title: str) -> None:
        """v1.6.20 K5: 트리의 대상 파일 노드 끝에 자식 책갈피 추가 (저장 시 반영)."""
        # 대상 파일 노드 찾기(경로 슬래시 차이에 견고하게 — resolve 비교)
        try:
            fp = Path(file_path).resolve()
        except Exception:
            fp = None
        target = None
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            d = top.data(0, self.DATA_FILE)
            if not d:
                continue
            if d == file_path or (fp is not None and Path(d).resolve() == fp):
                target = top
                break
        if target is None:
            return
        # placeholder 가 남아있으면 한 번 펼쳐서 lazy load 시키기
        if not target.data(0, self.DATA_TOC_LOADED):
            target.setExpanded(True)
        title = (title or "").strip() or "(제목 없음)"
        ch = QTreeWidgetItem([f"{title}  (p.{int(page_1based)})"])
        ch.setData(0, self.DATA_FILE, file_path)
        ch.setData(0, self.DATA_PAGE, max(0, int(page_1based) - 1))
        ch.setData(0, self.DATA_TOC_LOADED, True)
        target.addChild(ch)
        target.setExpanded(True)
        ch.setSelected(True)
        self.tree.scrollToItem(ch)
        self._mark_dirty()

    # ---- 260606-4: 책갈피 생성/편집 완료 후 새로고침(목록 유지) ----------
    def _refresh_file_toc(self, item: QTreeWidgetItem):
        """파일 노드의 내부 책갈피(TOC) 자식을 디스크에서 다시 읽어 갱신."""
        for i in reversed(range(item.childCount())):
            item.takeChild(i)
        item.setData(0, self.DATA_TOC_LOADED, False)
        fp = item.data(0, self.DATA_FILE)
        if fp:
            self._attach_toc_placeholder(item, Path(fp))
        item.setExpanded(False)
        item.setExpanded(True)        # itemExpanded → _on_item_expanded 가 lazy load

    def add_or_refresh_file(self, file_path: str):
        """기존 트리 목록을 유지한 채 해당 파일 노드를 추가하거나 책갈피를 갱신."""
        fp = Path(file_path)
        try:
            fpr = fp.resolve()
        except Exception:
            fpr = None
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            d = top.data(0, self.DATA_FILE)
            if d and (d == str(fp) or (fpr is not None and Path(d).resolve() == fpr)):
                self._refresh_file_toc(top)
                self.tree.setCurrentItem(top)
                self.tree.scrollToItem(top)
                return
        # 없으면 새 최상위 파일 노드로 추가(기존 목록은 그대로)
        item = QTreeWidgetItem([fp.stem])
        item.setData(0, self.DATA_FILE, str(fp))
        item.setData(0, self.DATA_PAGE, 0)
        self._attach_toc_placeholder(item, fp)
        self.tree.addTopLevelItem(item)
        if self._mode == "flat" and fp not in self._pdfs_flat:
            self._pdfs_flat.append(fp)
        item.setExpanded(True)
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    # ---- 260606-9: 활성 창 위치에 해당하는 책갈피 선택·스크롤 -------------
    def select_for_page(self, file_path: str, page0: int):
        """주어진 파일·페이지(0-based)에 해당하는 책갈피를 선택·스크롤(네비게이션 없음).
        260609-11: 편집 모드에서도 동작(요청). blockSignals 로 네비게이션은 발생 안 함."""
        if not file_path:
            return
        try:
            fpr = Path(file_path).resolve()
        except Exception:
            fpr = None
        top = None
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            d = it.data(0, self.DATA_FILE)
            if d and (d == str(file_path) or (fpr is not None and Path(d).resolve() == fpr)):
                top = it
                break
        if top is None:
            return
        if not top.data(0, self.DATA_TOC_LOADED):
            top.setExpanded(True)          # TOC lazy load
        best = [None, -1]                  # [item, page]

        def walk(node):
            for k in range(node.childCount()):
                ch = node.child(k)
                if ch.data(0, self.DATA_IS_TOC_PLACEHOLDER):
                    continue
                pg = ch.data(0, self.DATA_PAGE)
                if pg is not None and int(pg) <= page0 and int(pg) >= best[1]:
                    best[0] = ch
                    best[1] = int(pg)
                walk(ch)
        walk(top)
        # 260611-9: 다중 선택 중이면 동기화로 선택을 깨지 않음(다중선택 보존). 스크롤만.
        if len(self.tree.selectedItems()) > 1:
            if best[0] is not None:
                self.tree.scrollToItem(best[0])
            return
        target = best[0] or top
        # 260611-8: 같은 페이지에 책갈피가 여러 개여도, 현재 선택이 이미 그 페이지면 유지.
        #   (기존엔 동일 페이지의 '마지막' 책갈피로 옮겨가던 문제)
        cur = self.tree.currentItem()
        if cur is not None and best[0] is not None:
            cpg = cur.data(0, self.DATA_PAGE)
            if (cpg is not None and not cur.data(0, self.DATA_IS_TOC_PLACEHOLDER)
                    and int(cpg) == best[1]):
                node = cur                      # 현재 선택이 같은 파일(top) 소속일 때만 유지
                while node.parent() is not None:
                    node = node.parent()
                if node is top:
                    target = cur
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(target)
        self.tree.blockSignals(False)
        self.tree.scrollToItem(target)

    # ---- 위/아래 이동 (v1.6.19) -----------------------------------------
    def _op_move_up(self):
        self._move(-1)

    def _op_move_down(self):
        self._move(+1)

    def _move(self, direction: int):
        """다중 선택 일괄 이동. 같은 부모 안에서 한 칸씩. 부모 경계 존중."""
        items = [it for it in self.tree.selectedItems()
                 if not it.data(0, self.DATA_IS_TOC_PLACEHOLDER)]
        if not items:
            return
        # 부모별 그룹화
        groups: dict = {}
        for it in items:
            key = id(it.parent()) if it.parent() is not None else 0
            groups.setdefault(key, []).append(it)
        for grp in groups.values():
            parent = grp[0].parent()
            def idx_of(x):
                return (parent.indexOfChild(x) if parent is not None
                        else self.tree.indexOfTopLevelItem(x))
            grp.sort(key=idx_of, reverse=(direction > 0))    # 위로 = 오름차순, 아래로 = 내림차순
            n = parent.childCount() if parent is not None else self.tree.topLevelItemCount()
            for it in grp:
                idx = idx_of(it)
                new_idx = idx + direction
                if new_idx < 0 or new_idx >= n:
                    continue
                if parent is not None:
                    parent.takeChild(idx)
                    parent.insertChild(new_idx, it)
                else:
                    self.tree.takeTopLevelItem(idx)
                    self.tree.insertTopLevelItem(new_idx, it)
                it.setSelected(True)
        self._mark_dirty()

    # ---- 저장: 평탄화 → apply_bookmarks_to_pdf -------------------------
    def _op_save(self):
        # 260611-18(A4): 책갈피 변경이 없어도 개체/주석(page_meta) 변경이 있으면 저장.
        meta_dirty = bool(self._meta_is_dirty and self._meta_is_dirty())
        target = self._target_file_item()
        if target is None or not target.data(0, self.DATA_FILE):
            if meta_dirty:
                self._commit_meta()      # 개체만 삽입한 경우 — 트리 선택 없이도 저장
                return
            QMessageBox.information(self, "안내", "편집할 PDF 파일을 트리에서 선택하세요.")
            return
        src = Path(target.data(0, self.DATA_FILE))
        if not src.exists():
            QMessageBox.warning(self, "오류", f"원본 PDF 없음: {src}")
            return
        bookmarks_raw = []   # (title, page_1based, level)
        self._walk_collect(target, 0, bookmarks_raw)
        # 260606-13: 원본 PDF의 현재 책갈피(TOC)와 비교해 '실제 변경 여부'로 메시지 결정
        orig = self._read_orig_toc(src)
        if bookmarks_raw == orig:
            self._dirty = False
            self._commit_meta()          # 개체/주석 등 page_meta 변경은 저장
            if not meta_dirty:
                QMessageBox.information(self, "책갈피 저장", "변경 사항이 없습니다.")
            return
        if not bookmarks_raw:
            # 모든 책갈피 삭제(기존 대비 변경) → 책갈피 없는 PDF로 저장 확인
            if QMessageBox.question(
                self, "책갈피 저장",
                "모든 책갈피가 제거되었습니다.\n기존 책갈피를 지운 PDF로 저장할까요?"
            ) != QMessageBox.StandardButton.Yes:
                return
        # 벤더링된 pdf_bookmarker 사용
        try:
            from viewer import bookmarker_bridge as bridge
            if not bridge.is_available():
                raise RuntimeError(bridge.get_status())
            import pdf_bookmarker as pb  # alias 등록됨
            bms = [pb.Bookmark(title=t, page=p, level=l) for (t, p, l) in bookmarks_raw]
            dst = src.with_name(src.stem + "_edited.pdf")
            out = bridge.apply_to_pdf(src, dst, bms)
        except Exception as e:
            QMessageBox.warning(self, "저장 실패", str(e))
            return
        self._dirty = False
        self.bookmarksEdited.emit(str(src), str(out))
        self._commit_meta()              # 260611-18(A4): 책갈피+개체 동시 저장

    def _commit_meta(self):
        """260611-18(A4): page_meta 미저장 변경을 디스크에 저장(+썸네일 반영)."""
        if self._meta_commit:
            try:
                self._meta_commit()
            except Exception:
                pass

    def all_file_paths(self) -> list:
        """260606-15: 트리의 최상위 파일 노드 경로 목록(PDF 병합 좌측 리스트용)."""
        out = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            d = it.data(0, self.DATA_FILE)
            if d and str(d).lower().endswith(".pdf"):
                out.append(str(d))
        return out

    def ordered_pdf_files(self) -> list:
        """260609-28: 책갈피창 시각 순서(깊이우선 전위)대로 '구별되는' PDF 파일 경로 목록.

        분할본 bookmarks.json 은 챕터 그룹 아래 파일 리프가 **중첩**될 수 있어
        최상위만 보는 all_file_paths() 로는 파일 경계 이동이 동작하지 않는다.
        모든 깊이의 파일 리프(TOC 자식은 부모와 같은 경로 → 중복 제거)를
        순서대로 모은다 — 파일 단위 위/아래 이동의 기준 목록."""
        out, seen = [], set()

        def walk(item):
            for i in range(item.childCount()):
                ch = item.child(i)
                d = ch.data(0, self.DATA_FILE)
                if d and str(d).lower().endswith(".pdf"):
                    s = str(d)
                    if s not in seen:
                        seen.add(s); out.append(s)
                walk(ch)

        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            d = it.data(0, self.DATA_FILE)
            if d and str(d).lower().endswith(".pdf"):
                s = str(d)
                if s not in seen:
                    seen.add(s); out.append(s)
            walk(it)
        return out

    @staticmethod
    def _read_orig_toc(src) -> list:
        """원본 PDF의 현재 책갈피를 (title, page_1based, level) 리스트로(비교용)."""
        try:
            import fitz
            d = fitz.open(str(src))
            toc = d.get_toc(simple=True) or []      # [lvl, title, page(1based)]
            d.close()
            return [((t or "").strip() or "(제목 없음)", int(pg), int(lv) - 1)
                    for (lv, t, pg) in toc]
        except Exception:
            return []

    def _walk_collect(self, node: QTreeWidgetItem, level: int, out: list):
        for i in range(node.childCount()):
            ch = node.child(i)
            if ch.data(0, self.DATA_IS_TOC_PLACEHOLDER):
                continue
            page = ch.data(0, self.DATA_PAGE)
            if page is None:
                # 파일이지만 페이지 없음 — 스킵
                self._walk_collect(ch, level, out)
                continue
            title = _PAGE_BADGE_RE.sub("", ch.text(0)).rstrip() or "(제목 없음)"
            out.append((title, int(page) + 1, level))
            self._walk_collect(ch, level + 1, out)


# ─── 모듈 헬퍼 ──────────────────────────────────────────────────────
def _top_of(it: QTreeWidgetItem) -> QTreeWidgetItem:
    while it.parent() is not None:
        it = it.parent()
    return it


def _is_descendant(it: QTreeWidgetItem, ancestor: QTreeWidgetItem) -> bool:
    cur = it.parent()
    while cur is not None:
        if cur is ancestor:
            return True
        cur = cur.parent()
    return False


def _ancestors(it: QTreeWidgetItem, root: QTreeWidgetItem):
    """it 의 조상들(root 미포함) 위→아래 순으로 반환."""
    cur = it.parent()
    out = []
    while cur is not None and cur is not root:
        out.append(cur)
        cur = cur.parent()
    return out


def _unique_path(target: Path) -> Path:
    """target 이 존재하면 (1), (2), ... 접미사로 충돌 회피."""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    parent = target.parent
    i = 1
    while True:
        cand = parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def _stat(p: Path):
    """안전한 stat — 실패 시 0 으로 채운 더미."""
    try:
        return p.stat()
    except Exception:
        class _Z:
            st_mtime = 0.0
            st_size = 0
        return _Z()


def _path_to(it: QTreeWidgetItem, root: QTreeWidgetItem) -> tuple:
    """root 까지의 인덱스 경로(루트→리프). 정렬키로 사용 — 트리 출현 순서."""
    path: list = []
    cur = it
    while cur is not None and cur is not root:
        parent = cur.parent() or root
        path.append(parent.indexOfChild(cur))
        cur = cur.parent()
    return tuple(reversed(path))
