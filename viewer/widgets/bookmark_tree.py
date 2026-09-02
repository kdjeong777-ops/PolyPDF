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
    """드래그 재배치(InternalMove) 발생 시 dropped 시그널 — 편집 '변경됨' 추적용(260606-4).
    260618-27: 외부에서 PDF/폴더를 드롭하면 pathDropped 로 알림(이 트리=해당 창에 등록).
    드래그가 이 트리 위에 올라오면 테두리 강조(상/하단 영역 구분)."""
    dropped = pyqtSignal()
    delPressed = pyqtSignal()       # 260611-56: DEL 키 → 선택 삭제(휴지통)
    pathDropped = pyqtSignal(str)   # 260618-27: 외부 PDF/폴더 드롭(이 창에 열기)

    @staticmethod
    def _ext_paths(md):
        """드롭 가능한 외부 경로(PDF/폴더)만 추출."""
        out = []
        if md is not None and md.hasUrls():
            from pathlib import Path as _P
            for u in md.urls():
                if not u.isLocalFile():
                    continue
                lf = u.toLocalFile()
                try:
                    if lf.lower().endswith(".pdf") or _P(lf).is_dir():
                        out.append(lf)
                except Exception:
                    pass
        return out

    def _set_drop_hl(self, on: bool):
        if on:
            if not hasattr(self, "_base_ss"):
                self._base_ss = self.styleSheet()
            self.setStyleSheet((self._base_ss or "")
                               + "\nQTreeWidget{border:2px solid #1565c0; background:rgba(21,101,192,0.08);}")
        else:
            self.setStyleSheet(getattr(self, "_base_ss", ""))

    def dragEnterEvent(self, e):
        if self._ext_paths(e.mimeData()):
            e.acceptProposedAction(); self._set_drop_hl(True); return
        super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._ext_paths(e.mimeData()):
            e.acceptProposedAction(); return
        super().dragMoveEvent(e)

    def dragLeaveEvent(self, e):
        self._set_drop_hl(False)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        paths = self._ext_paths(e.mimeData())
        if paths:
            self._set_drop_hl(False)
            self.pathDropped.emit(paths[0])     # 첫 항목(정렬순 첫 파일/폴더)
            e.acceptProposedAction()
            return
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
    translateFileRequested = pyqtSignal(str)    # 260621-P0: 파일 우클릭 '번역'(단일)
    translateFilesRequested = pyqtSignal(list)  # 260621-P0: 선택 파일들 번역(경로 리스트)
    editGlossaryRequested = pyqtSignal(str)      # 260623: 그 PDF 번역 용어집 교정
    filePasswordEntered = pyqtSignal(str)    # 260618-1: 우클릭 '암호 입력' 성공 — 앱이 재로드
    releaseFileRequested = pyqtSignal(str)   # v1.6.21: 파일 작업 직전 — 앱이 핸들 해제
    fileOpCompleted = pyqtSignal(str, str)   # v1.6.21: (old, new) new=="" 삭제, new==old 실패
    splitViewRequested = pyqtSignal(bool)    # 260618-25: 1단→2단 진입(True)
    pathDropped = pyqtSignal(str)            # 260618-27: 외부 PDF/폴더 드롭 → 이 창에 열기
    copyPaneRequested = pyqtSignal()         # 260618-27: 이 책갈피창 기준 반대 창으로 복사
    viewModeChanged = pyqtSignal(bool, str)  # 260825: (is_folder, 폴더|파일 경로) — 파일↔폴더 전환
    filesRelocated = pyqtSignal(list)        # 260901-2: [[old, new], ...] 파일 복사/이동 완료
    viewListModeChanged = pyqtSignal(bool)   # 260901-3: 사용자가 목록 보기를 바꿈(True=트리)

    DATA_FILE = Qt.ItemDataRole.UserRole + 0
    DATA_PAGE = Qt.ItemDataRole.UserRole + 1
    DATA_TOC_LOADED = Qt.ItemDataRole.UserRole + 2   # v1.6.2: TOC lazy load 완료 플래그
    DATA_IS_TOC_PLACEHOLDER = Qt.ItemDataRole.UserRole + 3   # v1.6.2: 펼치기 유도용 더미 자식 표식
    DATA_ENCRYPTED = _ENC_ROLE                       # 260611-57: 암호화 파일 표식
    DATA_AUTH = _AUTH_ROLE                            # 260618-1: 인증 상태(owner/user/locked)
    DATA_BASELABEL = Qt.ItemDataRole.UserRole + 7    # 260623: 해시태그 접미 적용 전 원본 라벨
    DATA_IS_FOLDER = Qt.ItemDataRole.UserRole + 8    # 260901-2: 트리 보기의 폴더 그룹 행

    # 260901-2: 폴더 그룹 행 색 — 디자인 SOT §2.5(테마 무관, 밝은 노랑+어두운 글자)
    FOLDER_ROW_BG = "#fdf3c0"
    FOLDER_ROW_FG = "#1a1a1a"
    TREE_INDENT = 12        # 260902-1: 계층 들여쓰기(px) — 디자인 SOT §2.8

    SORT_BOOK = "책갈피 순"
    SORT_NAME = "이름 순"
    SORT_MTIME = "수정일 순"
    SORT_SIZE = "크기 순"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_dir: Optional[Path] = None
        self._edit_mode: bool = False               # v1.6.18
        self._split_on: bool = False                # 260618-25: 우클릭 1단/2단 라벨용
        self._pane_idx: int = 0                      # 260618-27: 0=상단(1창)/1=하단(2창)
        self._mode: str = "none"                    # v1.6.19: none|json|flat|single
        self._pdfs_flat: list = []                  # v1.6.19: 평탄 모드 파일 캐시
        # 260901-2: False=단일(평탄) / True=트리(폴더 그룹). **기본은 트리**(사용자 지정) —
        #   하위 폴더가 없으면 트리여도 평탄 목록과 같은 모양이라 기본값으로 안전하다.
        self._view_tree: bool = True
        self._single_file: Optional[Path] = None    # 260822: 파일 모드로 연 단일 PDF
        self._current_file_getter = None            # 260822: 앱이 현재 본문 파일 경로 제공
        self._dirty: bool = False                   # 260606-4: 편집 변경 여부
        self._reload_fn = None                       # 260611-9: 편집 취소 시 원본 재로드용
        # 260611-18(A4): 저장 버튼이 page_meta(숨김/회전/선긋기/이미지/하이퍼링크)도 저장
        self._meta_is_dirty = None                   # () -> bool
        self._meta_commit = None                     # () -> None (디스크 저장 + 썸네일 반영)
        self._page_edit_dirty = None                 # 260821: () -> bool (썸네일 페이지 삭제/이동)
        self._page_edit_save = None                  # 260821: (src, bookmarks_raw) -> None (앱 재구성 저장)
        self._finalize_save = None                   # 260822: (src, produced) -> final_path (덮어쓰기/_edited)
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

    def set_page_edit_hooks(self, dirty_fn, save_fn, finalize_fn=None):
        """260821/260822: app 이 썸네일 페이지 편집 여부·재구성 저장·저장 목적지 배치를 주입."""
        self._page_edit_dirty = dirty_fn
        self._page_edit_save = save_fn
        self._finalize_save = finalize_fn

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

        # 260623: 즐겨찾기 별 버튼 삭제 → 해시태그(#) 필터 버튼. (폴더 즐겨찾기는 우클릭 메뉴로)
        from PyQt6.QtWidgets import QMenu
        self.btn_tag = QPushButton("#")
        self.btn_tag.setFixedWidth(28)
        self.btn_tag.setToolTip("해시태그로 검색 — 등록된 태그 보기/선택")
        self._tag_menu = QMenu(self)
        self._tag_menu.aboutToShow.connect(self._rebuild_tag_menu)
        self.btn_tag.setMenu(self._tag_menu)
        search_row.addWidget(self.btn_tag)
        layout.addLayout(search_row)

        try:
            from viewer.tag_store import TagStore
            self._tags = TagStore()
        except Exception:
            self._tags = None

        # v1.6.19: 파일 정렬 콤보 + 260822: 파일/폴더 모드 전환 버튼(정렬 콤보 오른쪽)
        sort_row = QHBoxLayout()
        sort_row.setContentsMargins(0, 0, 0, 0)
        sort_row.addWidget(QLabel("정렬:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems([self.SORT_BOOK, self.SORT_NAME,
                                   self.SORT_MTIME, self.SORT_SIZE])
        self._sort_combo.setCurrentText(self.SORT_MTIME)   # 초기 정렬 = 수정일순(내림차순)
        self._sort_combo.setMaximumWidth(96)               # 폭 줄여 모드 버튼 자리 확보
        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self._sort_combo)
        self.btn_mode = QPushButton("📁 폴더")
        self.btn_mode.setToolTip("파일 모드 ↔ 폴더 모드 전환\n"
                                 "· 파일 모드: 현재 파일만 표시\n"
                                 "· 폴더 모드: 그 폴더의 PDF 전체 표시")
        self.btn_mode.clicked.connect(self._toggle_view_mode)
        sort_row.addWidget(self.btn_mode, 1)
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
        # 260902-1(사용자 요청): 뷰어 모드에서도 목록 보기(트리/단일)를 바꿀 수 있게 —
        #   편집 버튼 오른쪽. 편집모드에서는 edit_ops 1행의 같은 버튼이 대신하므로 숨긴다.
        #   두 버튼의 라벨은 set_tree_view 가 함께 갱신한다.
        self.btn_view_mode_v = QPushButton("트리" if self._view_tree else "단일")
        self.btn_view_mode_v.setFixedWidth(44)
        self.btn_view_mode_v.setToolTip("목록 보기: 단일 ↔ 트리 (클릭마다 전환)")
        self.btn_view_mode_v.clicked.connect(self._toggle_tree_view)
        edit_row.addWidget(self.btn_view_mode_v)
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
        # 260901-2: '다중/단일' 토글 폐지 — 선택은 **항상 다중 가능**(ExtendedSelection)으로 통일.
        #   종전 토글은 편집모드에서만 단일 선택으로 되돌리는 용도였는데, 보기 모드는 이미
        #   상시 다중이라 모드에 따라 제스처가 달라지는 혼란만 남았다. 그 자리에는 보기 전환
        #   버튼(단일/트리)을 둔다.
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

        # 260901-2: 단일/트리 보기 토글 — 라벨 = **현재 보기**(클릭마다 전환).
        #   단일: 하위 폴더와 무관하게 모든 PDF 를 한 위계로. 트리: 폴더 그룹 아래로 묶어 표시.
        self.btn_view_mode = QPushButton("트리" if self._view_tree else "단일")
        self.btn_view_mode.setToolTip(
            "목록 보기: 단일 ↔ 트리 (클릭마다 전환)\n"
            "단일 = 하위 폴더 구분 없이 모든 PDF 를 한 위계로\n"
            "트리 = 폴더명 아래에 그 폴더의 파일을 묶어서")
        self.btn_view_mode.clicked.connect(self._toggle_tree_view)
        # 책갈피명 수정(단일 편집) — 첨부 아이콘
        self.btn_edit_single = QPushButton()
        _bep = resource_path("icon_bookmark_edit.png")
        if _bep:
            self.btn_edit_single.setIcon(_QIcon(_bep)); self.btn_edit_single.setIconSize(_QSize(18, 18))
        else:
            self.btn_edit_single.setText("✎")
        self.btn_edit_single.setToolTip("책갈피명 수정 (단일 편집: 제목·페이지)")
        self.btn_edit_single.clicked.connect(self._op_edit_single)

        # 1행: [단일/트리] ◀ ▶ ▲ ▼ [책갈피명수정] — 전체 폭 균등 분배
        row1 = QWidget()
        r1 = QHBoxLayout(row1); r1.setContentsMargins(0, 0, 0, 0); r1.setSpacing(3)
        for b in (self.btn_view_mode,
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
        # 260902-1(사용자 요청, 디자인 §2.8): 계층 들여쓰기 20→12px — 폴더>파일>책갈피 3단이
        #   쌓이면 좁은 패널에서 글자가 거의 안 보였다. 긴 이름은 '…' 로 자르지 않고 열 폭을
        #   내용에 맞춰 가로 스크롤로 끝까지 볼 수 있게(탐색기 관례).
        self.tree.setIndentation(self.TREE_INDENT)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.tree.header().setStretchLastSection(False)
        from PyQt6.QtWidgets import QHeaderView as _QHV
        self.tree.header().setSectionResizeMode(0, _QHV.ResizeMode.ResizeToContents)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 260901-2: 생성 시점부터 다중 선택 가능(종전엔 편집모드 전환 때 비로소 적용됐다).
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
        # 260618-27: 외부 PDF/폴더 드롭 → 이 책갈피창(=해당 메인 창)에 등록. 비편집 모드에서도
        #   외부 드롭은 받도록 acceptDrops 상시 ON(내부 재배치 드래그는 편집모드에서만).
        self.tree.setAcceptDrops(True)
        self.tree.pathDropped.connect(self.pathDropped.emit)
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
            self._update_mode_button()
            return True

        # 폴더 안의 PDF 파일들을 평면 트리로
        self._mode = "flat"             # v1.6.19
        self._pdfs_flat = list(self._root_dir.rglob("*.pdf"))
        self._render_flat()             # 정렬 콤보 반영
        self._update_mode_button()
        return True

    # ----- 260901-2: 행 종류 판별 · 파일 노드 순회 (★ 트리 보기 필수 계약) -----
    #   트리 보기에서 파일 노드는 폴더 그룹 행의 **자식**이 되므로, 종전 관용구
    #   `it.parent() is None and it.data(0, DATA_FILE)` 는 전부 거짓이 된다.
    #   새 코드는 반드시 아래 헬퍼를 쓴다(마스터 SOT §7.6).
    def _is_folder_node(self, it) -> bool:
        return bool(it is not None and it.data(0, self.DATA_IS_FOLDER))

    def _is_file_node(self, it) -> bool:
        """파일 노드 = DATA_FILE 이 있고, 폴더 행이 아니며, **부모가 파일/책갈피가 아닌** 행.

        260902-1(결함 수정): 책갈피(TOC) 자식도 DATA_FILE 을 갖는다(페이지 이동용). 종전
        판정이 그것을 파일로 오판해 '책갈피명 수정'이 파일명 수정으로 가고, 우클릭 메뉴가
        책갈피에 파일 메뉴를 띄웠다. 부모 조건이 종전 `parent() is None` 의 본뜻이다."""
        if it is None or not it.data(0, self.DATA_FILE) or it.data(0, self.DATA_IS_FOLDER):
            return False
        par = it.parent()
        return par is None or not par.data(0, self.DATA_FILE)

    def _iter_file_nodes(self):
        """보기 모드와 무관하게 트리의 모든 파일 노드를 트리 출현 순서로 순회.
        폴더 행·(JSON 모드의) 그룹 행처럼 DATA_FILE 이 없는 행은 안으로 내려간다."""
        for i in range(self.tree.topLevelItemCount()):
            yield from self._iter_folder_files(self.tree.topLevelItem(i), _self_ok=True)

    def _iter_folder_files(self, node, _self_ok=False):
        """node 아래(또는 node 자신)의 파일 노드. 파일 노드 아래(책갈피)로는 내려가지 않는다."""
        if _self_ok and self._is_file_node(node):
            yield node
            return
        if node.data(0, self.DATA_FILE):          # 파일/책갈피 — 그 아래는 책갈피뿐
            return
        for i in range(node.childCount()):
            yield from self._iter_folder_files(node.child(i), _self_ok=True)

    def _file_node_of(self, it):
        """임의 행 → 소속 파일 노드(자기 자신 포함). 폴더 행이면 None."""
        cur = it
        while cur is not None:
            if self._is_file_node(cur):
                return cur
            if self._is_folder_node(cur):
                return None
            cur = cur.parent()
        return None

    def _selected_file_nodes(self) -> list:
        """선택된 파일 노드(트리 순서·중복 제거). 폴더 행을 골랐으면 그 아래 파일 전체."""
        out, seen = [], set()

        def add(node):
            p = node.data(0, self.DATA_FILE)
            if p and p not in seen:
                seen.add(p); out.append(node)

        for it in self.tree.selectedItems():
            if self._is_folder_node(it):
                for f in self._iter_folder_files(it):
                    add(f)
            else:
                f = self._file_node_of(it)
                if f is not None:
                    add(f)
        return out

    # ----- 렌더 -----------------------------------------------------------
    def is_tree_view(self) -> bool:
        """260901-2: True=트리(폴더 그룹) 보기 / False=단일(평탄) 보기."""
        return bool(self._view_tree)

    def set_tree_view(self, on: bool):
        """260901-2: 보기 모드 전환. 평탄 모드(bookmarks.json 없음)에서만 의미가 있다."""
        on = bool(on)
        if on == self._view_tree:
            return
        self._view_tree = on
        for b in (getattr(self, "btn_view_mode", None), getattr(self, "btn_view_mode_v", None)):
            if b is not None:
                b.setText("트리" if on else "단일")
        if self._mode == "flat":
            cur = self._current_selected_file()
            self._render_flat()
            if cur:
                self._select_top_file(cur)
            self._on_filter(self.search_edit.text())

    def _toggle_tree_view(self):
        if self._mode != "flat":
            QMessageBox.information(
                self, "안내",
                "단일/트리 보기는 폴더를 연 목록에서만 동작합니다.\n"
                "(bookmarks.json 이 있는 분할 폴더·단일 파일 보기는 그 구조를 그대로 유지합니다.)")
            return
        self.set_tree_view(not self._view_tree)
        # 260901-3: **사용자가 직접 바꾼 경우에만** 알린다(프로그램적 set_tree_view 는 조용히)
        #   — 앱이 이 신호로 설정을 저장하고 반대편 트리에 반영하는데, set_tree_view 에서
        #     발신하면 반영이 다시 신호를 낳아 되먹임이 된다.
        self.viewListModeChanged.emit(self._view_tree)

    def _render_flat(self):
        """v1.6.19: 평탄 모드 렌더 — 현재 정렬 콤보 적용.
        260901-2: 트리 보기면 폴더 그룹으로 묶어 렌더."""
        self._reset_probe_queue()
        self.tree.clear()
        pdfs = self._sorted_flat()
        if self._view_tree:
            self._render_tree_grouped(pdfs)
        else:
            for pdf in pdfs:
                self.tree.addTopLevelItem(self._make_file_node(pdf))
        self.info.setText(f"{len(pdfs)}개 PDF")   # 260618-27: '(bookmarks.json 없음)' 표기 삭제

    def _make_file_node(self, pdf: Path) -> QTreeWidgetItem:
        item = QTreeWidgetItem([pdf.stem])
        item.setData(0, self.DATA_FILE, str(pdf))
        item.setData(0, self.DATA_PAGE, 0)
        self._decorate_file_node(item, pdf)
        return item

    def _render_tree_grouped(self, pdfs: list):
        """260901-2: 루트 기준 상대 폴더 계층으로 묶어 렌더.

        배치(디자인 §2.8): **폴더 그룹 먼저(이름 순) → 루트 직속 파일**(정렬 콤보 순).
        하위 폴더는 계층 그대로 중첩하고, 파일은 자기 폴더 행의 자식(한 단계 들여쓰기)."""
        root = self._root_dir
        groups = {}          # rel_parts(tuple) -> [Path, ...]  (루트 직속은 ())
        for pdf in pdfs:
            try:
                rel = pdf.parent.relative_to(root) if root else Path(".")
                parts = tuple(p for p in rel.parts if p not in (".", ""))
            except Exception:
                parts = ()   # 루트 밖(방어) — 루트 직속으로
            groups.setdefault(parts, []).append(pdf)

        folder_items = {}    # rel_parts -> QTreeWidgetItem

        def folder_item(parts: tuple) -> QTreeWidgetItem:
            """폴더 행을 만들거나 재사용(상위 폴더가 없으면 함께 생성)."""
            if parts in folder_items:
                return folder_items[parts]
            it = QTreeWidgetItem([parts[-1]])
            self._style_folder_node(it, (root / Path(*parts)) if root else Path(*parts))
            if len(parts) == 1:
                self.tree.addTopLevelItem(it)
            else:
                folder_item(parts[:-1]).addChild(it)
            it.setExpanded(True)
            folder_items[parts] = it
            return it

        for parts in sorted((k for k in groups if k), key=lambda t: [s.lower() for s in t]):
            parent = folder_item(parts)
            for pdf in groups[parts]:
                parent.addChild(self._make_file_node(pdf))
        for pdf in groups.get((), []):          # 루트 직속 파일은 폴더 그룹 아래에
            self.tree.addTopLevelItem(self._make_file_node(pdf))

    def _style_folder_node(self, item: QTreeWidgetItem, folder: Path):
        """260901-2: 폴더 그룹 행 — 옅은 노랑 배경 + 굵게 + 폴더 아이콘(디자인 §2.5)."""
        from PyQt6.QtGui import QBrush, QColor, QFont
        item.setData(0, self.DATA_IS_FOLDER, True)
        item.setData(0, self.DATA_PAGE, None)
        item.setBackground(0, QBrush(QColor(self.FOLDER_ROW_BG)))
        item.setForeground(0, QBrush(QColor(self.FOLDER_ROW_FG)))
        f = QFont(item.font(0)); f.setBold(True); item.setFont(0, f)
        try:
            from viewer.widgets.icons import themed_icon
            # 배경이 테마 무관 밝은 노랑 → 아이콘 전경도 라이트로 강제(디자인 §2.5 각주)
            item.setIcon(0, themed_icon("folder", dark=False))
        except Exception:
            pass
        item.setToolTip(0, str(folder))

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

    # ----- 260822: 파일/폴더 모드 -----
    def set_current_file_getter(self, fn):
        """앱이 현재 본문 파일 경로를 제공(폴더→파일 전환 시 대상 파일)."""
        self._current_file_getter = fn

    def _is_file_mode(self) -> bool:
        return self._mode == "single"

    def _update_mode_button(self):
        """모드 버튼 라벨을 현재 모드에 맞게 — 파일 모드면 '폴더 모드로', 폴더면 '파일 모드로'."""
        if not hasattr(self, "btn_mode"):
            return
        if self._is_file_mode():
            self.btn_mode.setText("📄 파일")   # 현재=파일, 클릭 시 폴더로
        else:
            self.btn_mode.setText("📁 폴더")   # 현재=폴더, 클릭 시 파일로

    def _current_selected_file(self):
        """트리에서 선택된 최상위 파일(없으면 앱 제공 현재 파일)."""
        it = self.tree.currentItem()
        while it is not None and not it.data(0, self.DATA_FILE):
            it = it.parent()
        if it is not None and it.data(0, self.DATA_FILE):
            return Path(it.data(0, self.DATA_FILE))
        if callable(self._current_file_getter):
            try:
                f = self._current_file_getter()
                if f and str(f).lower().endswith(".pdf"):
                    return Path(f)
            except Exception:
                pass
        return None

    def _toggle_view_mode(self):
        """파일 모드 ↔ 폴더 모드 전환."""
        if self._is_file_mode():
            # 파일 → 폴더: 현재 파일이 있는 폴더의 PDF 전체 표시, 그 파일 선택
            f = self._single_file or self._current_selected_file()
            folder = (f.parent if f else self._root_dir)
            if not folder or not Path(folder).exists():
                self.info.setText("폴더를 찾을 수 없습니다.")
                return
            self.load_folder(folder)
            if f:
                self._select_top_file(f)
            self.viewModeChanged.emit(True, str(folder))
        else:
            # 폴더 → 파일: 선택(또는 현재 본문) 파일만 표시
            f = self._current_selected_file()
            if not f or not f.exists():
                self.info.setText("파일 모드로 볼 파일을 먼저 선택하세요.")
                return
            self.load_single_pdf(f)
            self.viewModeChanged.emit(False, str(f))

    def _select_top_file(self, path):
        """최상위 파일 노드 중 path 를 선택·스크롤.
        260628: 비교 키를 표준 `pathutil.norm_key` 로 통일(app·검색결과와 동일 키; SOT §7.0).
        구 `Path.resolve().lower()` 는 파일시스템을 타서 느리고 없는 파일에서 예외."""
        from viewer.pathutil import norm_key
        key = norm_key(path)
        for it in self._iter_file_nodes():          # 260901-2: 트리 보기 포함
            d = it.data(0, self.DATA_FILE)
            try:
                if d and norm_key(d) == key:
                    par = it.parent()                  # 폴더 그룹 안이면 펼쳐서 보이게
                    while par is not None:
                        par.setExpanded(True); par = par.parent()
                    self.tree.setCurrentItem(it)
                    self.tree.scrollToItem(it)
                    return
            except Exception:
                pass

    def load_single_pdf(self, pdf_path: str | Path) -> bool:
        """v1.6.11 I1/I2: 단일 PDF 한 개만 트리에 표시 (내부 TOC lazy load)."""
        p = Path(pdf_path)
        self._root_dir = p.parent
        self._single_file = p            # 260822: 파일 모드 → 폴더 모드 전환 기준
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
        self._update_mode_button()
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
        self._apply_tag_label(item, str(pdf_path))
        self._probe_queue.append((item, str(pdf_path)))
        if not self._probe_timer.isActive():
            self._probe_timer.start()

    # --- 해시태그(파일 분류) -------------------------------------------------
    def _apply_tag_label(self, item: QTreeWidgetItem, path: str):
        """파일명 뒤에 ` #태그` 접미를 붙여 표시(원본 라벨은 DATA_BASELABEL 에 보존)."""
        if self._tags is None:
            return
        base = item.data(0, self.DATA_BASELABEL)
        if base is None:
            base = item.text(0)
            item.setData(0, self.DATA_BASELABEL, base)
        tags = self._tags.get(path)
        # 260829 P2(태그 SOT §8.3·디자인 §2.11): 자동 태그는 `·#` 중점 접두로 구분 —
        # 표시 구분은 장식이 아니라 자동 부여의 안전장치다(확인을 대신한다).
        def _chip(t):
            return ("·#" if self._tags.is_auto(path, t) else "#") + t
        suffix = ("   " + "  ".join(_chip(t) for t in tags)) if tags else ""
        item.setText(0, base + suffix)
        tip = path
        try:
            y = self._tags.get_year(path)
            kws = self._tags.get_keywords(path)
            extra = [x for x in ([f"작성연도 {y}"] if y else [])
                     + (["키워드: " + " · ".join(kws)] if kws else [])]
            if extra:
                tip = path + "\n" + "\n".join(extra)
        except Exception:
            pass
        item.setToolTip(0, tip)

    def refresh_tag_labels(self):
        """260829 P2: 자동 부여/되돌리기 후 전체 파일 라벨·필터 갱신(§8.5)."""
        if self._tags is None:
            return
        try:
            self._tags._load()                      # 다른 경로(백업 복원)로 바뀐 파일 재읽기
        except Exception:
            pass
        for it in self._iter_file_nodes():          # 260901-2: 트리 보기 포함
            p = it.data(0, self.DATA_FILE)
            if p:
                self._apply_tag_label(it, p)
        self._on_filter(self.search_edit.text())

    def _rebuild_tag_menu(self):
        """'#' 버튼 — 체크형 패널 풀다운(검색 SOT §5.1, 260830 P4).

        ★ 풀다운은 입력 수단일 뿐, 진실은 검색박스 텍스트다: 체크/해제 =
        `#태그` 토큰 추가/제거와 완전히 같은 행위(양방향 — 열 때 토큰으로 체크 복원).
        체크해도 닫히지 않는다(QWidgetAction). 개수 = tag_counts(연도 불포함 §3.6)."""
        self._tag_menu.clear()
        tags = self._tags.all_tags() if self._tags else []
        if not tags:
            a = self._tag_menu.addAction("(등록된 해시태그 없음 — 파일 우클릭 → 해시태그 편집)")
            a.setEnabled(False)
            return
        from PyQt6.QtWidgets import (QCheckBox, QLabel as _QL, QScrollArea,
                                     QVBoxLayout, QWidget, QWidgetAction)
        try:
            from viewer.auto_tag import axis_of
        except Exception:
            def axis_of(_t):
                return "주제"
        counts = {}
        try:
            counts = self._tags.tag_counts()
        except Exception:
            pass
        active = {c.lstrip("#").lower() for c in self.search_edit.text().split()
                  if c.startswith("#")}
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)
        groups = {"형식": [], "주제": []}
        for t in tags:
            groups[axis_of(t) if axis_of(t) in groups else "주제"].append(t)
        for gname in ("형식", "주제"):
            if not groups[gname]:
                continue
            hd = _QL(f"<b>{gname}</b>")
            lay.addWidget(hd)
            for t in groups[gname]:
                cb = QCheckBox(f"#{t}  ({counts.get(t, 0)})")
                cb.setChecked(t.lower() in active)
                cb.toggled.connect(
                    lambda on, tag=t: (self._add_tag_to_search(tag) if on
                                       else self._remove_tag_from_search(tag)))
                lay.addWidget(cb)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(panel)
        area.setMaximumHeight(320)
        area.setMinimumWidth(200)
        wa = QWidgetAction(self._tag_menu)
        wa.setDefaultWidget(area)
        self._tag_menu.addAction(wa)
        self._tag_menu.addSeparator()
        clr_tags = self._tag_menu.addAction("모두 해제")
        clr_tags.triggered.connect(self._clear_tag_tokens)
        clr = self._tag_menu.addAction("검색 비우기")
        clr.triggered.connect(lambda: self.search_edit.clear())
        # 260829 P2(태그 SOT §8.5): 한 태그가 잘못 퍼졌을 때 그것만 회수
        auto_ts = []
        try:
            auto_ts = self._tags.auto_tag_set()
        except Exception:
            pass
        if auto_ts:
            sub = self._tag_menu.addMenu("자동 부여 취소")
            for t in auto_ts[:30]:
                act = sub.addAction("·#" + t)
                act.triggered.connect(lambda _=False, tag=t: self._revoke_auto_tag(tag))
        if callable(getattr(self, "review_provider", None)):
            rv = self._tag_menu.addAction("새 태그 후보 검토…")    # §8.5
            rv.triggered.connect(lambda: self.review_provider())

    def _revoke_auto_tag(self, tag: str):
        """§8.5 '이 태그의 자동 부여만 취소' — 수동·다른 태그는 그대로."""
        if self._tags is None:
            return
        self._tags.clear_auto_tag(tag)
        self.refresh_tag_labels()

    def _add_tag_to_search(self, tag: str):
        cur = self.search_edit.text().split()
        if ("#" + tag).lower() not in [c.lower() for c in cur]:
            self.search_edit.setText((self.search_edit.text() + " #" + tag).strip())

    def _remove_tag_from_search(self, tag: str):
        """§5.1 체크 해제 = 토큰 제거(진실은 검색박스 텍스트)."""
        keep = [c for c in self.search_edit.text().split()
                if not (c.startswith("#") and c.lstrip("#").lower() == tag.lower())]
        self.search_edit.setText(" ".join(keep))

    def _clear_tag_tokens(self):
        keep = [c for c in self.search_edit.text().split() if not c.startswith("#")]
        self.search_edit.setText(" ".join(keep))

    def _edit_file_tags(self, path: str):
        """파일 해시태그 편집 다이얼로그 → 저장 후 라벨/필터 갱신.

        260829 P3(§8.1): 입력줄은 **수동만**, 자동 태그는 칩(✕거절/📌승격)으로 분리.
        ★ P2 잠복 결함 수정 — 기존엔 get() 합집합을 입력줄에 넣어 확인만 눌러도
        자동 태그 전부가 manual 로 저장(무단 승격)됐다."""
        if self._tags is None or not path:
            return
        from viewer.widgets.tag_edit_dialog import TagEditDialog
        auto = self._tags.get_auto(path)
        conf = {}
        try:
            v = self._tags._data.get(self._tags._key(path))
            if isinstance(v, dict):
                conf = dict(v.get("auto_conf") or {})
        except Exception:
            pass
        sugg = None
        if callable(getattr(self, "suggest_provider", None)):
            try:
                sugg = self.suggest_provider(path)       # 세션 캐시 기반(§8.1) — 없으면 None
            except Exception:
                sugg = None
        dlg = TagEditDialog(Path(path).stem, self._tags.get_manual(path),
                            self._tags.all_tags(), self,
                            auto_tags=auto, auto_conf=conf, suggestions=sugg)
        if dlg.exec():
            # ★ 순서 고정: set(수동 교체) → promote(auto→manual 추가) → reject.
            #   promote 를 set 앞에 두면 입력줄이 manual 을 덮어써 승격이 사라진다.
            self._tags.set(path, dlg.tags())
            pro = dlg.promoted_tags()
            if pro:
                self._tags.promote(path, pro)            # 📌 만 승격(§8.1 — 확인은 승격 아님)
            rej = dlg.rejected_tags()
            if rej:
                self._tags.reject(path, rej)             # 영구 — 다시 붙지 않음(§1-⑤)
            # 같은 파일의 모든 노드 라벨 갱신
            for it in self._iter_file_nodes():      # 260901-2: 트리 보기 포함
                if it.data(0, self.DATA_FILE) == path:
                    self._apply_tag_label(it, path)
            self._on_filter(self.search_edit.text())

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
        toks = (text or "").strip().split()
        tagq = [t[1:].lower() for t in toks if t.startswith("#") and len(t) > 1]
        textq = " ".join(t for t in toks if not t.startswith("#")).lower().strip()
        # 260830 P4(검색 SOT §5.1): 버튼에 활성 태그 수 표시(#N + 강조 — 디자인 §2.11)
        try:
            self.btn_tag.setText(f"#{len(tagq)}" if tagq else "#")
            self.btn_tag.setStyleSheet(
                "QPushButton{background:#e3efff;font-weight:bold;}" if tagq else "")
        except Exception:
            pass

        def text_match(item: QTreeWidgetItem) -> bool:
            ok = (not textq) or (textq in item.text(0).lower())
            child = any(text_match(item.child(i)) for i in range(item.childCount()))
            return ok or child

        def file_has_tags(path) -> bool:
            if not tagq:
                return True
            ftags = [t.lower() for t in (self._tags.get(path) if (self._tags and path) else [])]
            return all(any(ft == q or ft.startswith(q) for ft in ftags) for q in tagq)

        def file_text_match(item, path) -> bool:
            """260830 P4(태그 SOT §8.4): 파일 항목은 키워드·연도도 일반 텍스트 검색에
            포함 — 별도 토큰(kw:·year:) 없이 '2023' 을 치면 그 해 자료가 걸린다."""
            if text_match(item):
                return True
            if not textq or self._tags is None:
                return False
            try:
                if textq in " ".join(self._tags.get_keywords(path)).lower():
                    return True
                y = self._tags.get_year(path)
                if y and textq in str(y):
                    return True
            except Exception:
                pass
            return False

        def apply_row(it) -> bool:
            """행 하나를 거르고 가시성을 반환. 260901-2: 폴더 행은 '보이는 자식이 있으면' 보인다."""
            if self._is_folder_node(it):
                any_visible = False
                for c in range(it.childCount()):
                    if apply_row(it.child(c)):
                        any_visible = True
                it.setHidden(not any_visible)
                return any_visible
            path = it.data(0, self.DATA_FILE)
            is_file = bool(path)
            # 해시태그 필터는 파일에만 적용. 텍스트는 파일명/자식(책갈피)+키워드·연도에 적용.
            vis = (file_has_tags(path) and file_text_match(it, path)) if is_file \
                else text_match(it)
            it.setHidden(not vis)
            # 자식(책갈피) 가시성: 부모 보일 때 텍스트로 거름
            if vis:
                for c in range(it.childCount()):
                    self._filter_text_recursive(it.child(c), textq)
            return vis

        for i in range(self.tree.topLevelItemCount()):
            apply_row(self.tree.topLevelItem(i))

    def _filter_text_recursive(self, item: QTreeWidgetItem, textq: str) -> bool:
        ok = (not textq) or (textq in item.text(0).lower())
        child = False
        for i in range(item.childCount()):
            if self._filter_text_recursive(item.child(i), textq):
                child = True
        vis = ok or child
        item.setHidden(not vis)
        return vis

    # --- 활성화 -----------------------------------------------------------

    def _on_activated(self, item: QTreeWidgetItem, _column: int = 0):
        if item is None or item.data(0, self.DATA_IS_TOC_PLACEHOLDER):
            return
        # 260611-9: 편집모드에서 Ctrl/Shift+클릭은 '다중 선택' 제스처 → 메인 이동을 하지 않음.
        #   (이동하면 select_for_page 가 setCurrentItem 으로 다중 선택을 깨뜨려 다중선택 실패)
        from PyQt6.QtWidgets import QApplication
        mods = QApplication.keyboardModifiers()
        # 260825-5: Ctrl/Shift+클릭 = 다중 선택 제스처 → 메인 이동 안 함(보기·편집 공통).
        if (mods & (Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.ShiftModifier)):
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
        # 260825-5: Ctrl/Shift 다중선택 제스처는 이동 제외(보기·편집 공통).
        if (mods & (Qt.KeyboardModifier.ControlModifier
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
        if self._is_file_node(item):
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
                     if self._is_file_node(it)]
        if not (self._edit_mode and item.isSelected() and len(sel_files) >= 2):
            if not item.isSelected():
                # 260902-3(사용자 보고 — 편집모드 우클릭 무반응·'2단 보기'로 튐): 종전
                #   setCurrentItem 이 currentItemChanged → 네비게이션(파일 열기)을 일으켜,
                #   **메뉴가 떠 있는 동안** 다른 PDF 가 로드됐다. 큰 파일이면 메뉴 아래에서
                #   로딩이 돌다 팝업이 닫히고(무반응), 그 사이 한 번 더 누르면 첫 항목
                #   '2단 보기'가 눌렸다. 우클릭은 **선택만** 바꾼다 — 이동은 좌클릭/Enter 의 몫.
                self.tree.blockSignals(True)
                try:
                    self.tree.clearSelection()
                    self.tree.setCurrentItem(item)
                    item.setSelected(True)
                finally:
                    self.tree.blockSignals(False)
                self._pending_nav = None            # 직전에 예약된 이동도 취소
            sel_files = []
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        # 260618-27: 1단=‘2단 보기’(진입), 2단=이 창 기준 반대 창으로 복사
        #   상단(1창)='2창으로 복사', 하단(2창)='1창으로 복사'.
        if self._split_on:
            act_split_view = menu.addAction(
                "1창으로 복사" if self._pane_idx == 1 else "2창으로 복사")
            _is_copy = True
        else:
            act_split_view = menu.addAction("2단 보기")
            _is_copy = False
        menu.addSeparator()
        act_merge = None
        act_translate_sel = None
        if sel_files and getattr(self, "_merge_allowed", True):   # 260618-1: 권한 없으면 숨김
            act_merge = menu.addAction(f"선택 {len(sel_files)}개 파일 병합...")
            act_translate_sel = menu.addAction(f"선택 {len(sel_files)}개 파일 번역...")  # 260621-P0
            menu.addSeparator()
        # 260901-2: 편집모드 — 선택한 파일들을 폴더로 복사/이동(대상: 선택된 폴더·하위 폴더·새 폴더)
        xfer_files = self._selected_file_nodes() if self._edit_mode else []
        if item.isSelected() is False and self._edit_mode:
            f = self._file_node_of(item)
            xfer_files = ([f] if f is not None
                          else (list(self._iter_folder_files(item))
                                if self._is_folder_node(item) else []))
        if xfer_files:
            n = len(xfer_files)
            # 항목은 각자 triggered 로 처리 — 아래 chosen 분기와 겹치지 않는다.
            try:
                self._add_transfer_submenu(menu, f"파일 복사 ({n}개)", xfer_files, False)
                self._add_transfer_submenu(menu, f"파일 이동 ({n}개)", xfer_files, True)
                menu.addSeparator()
            except Exception:
                pass                       # 260902-1: 서브메뉴 실패가 메뉴 전체를 막지 않게
        # 260901-3: 폴더 행 우클릭 — 폴더 이름 변경 / 삭제(빈 폴더만)
        act_fold_new = act_fold_ren = act_fold_del = None
        if self._edit_mode and self._is_folder_node(item):
            act_fold_new = menu.addAction("이 폴더 안에 새 폴더...")
            act_fold_ren = menu.addAction("폴더 이름 변경...")
            act_fold_del = menu.addAction("폴더 삭제")
            menu.addSeparator()
        # 260606-4: 파일(최상위) 노드면 (책갈피 생성, 책갈피 편집)도 제공
        is_file = self._is_file_node(item)
        act_create = act_editmode = None
        act_study = act_study_bm = None
        act_translate = None
        act_edit_gloss = None
        act_tags = None
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
            act_tags = menu.addAction("해시태그 편집...")   # 260623: 파일 분류 태그
            act_translate = menu.addAction("번역...")   # 260621-P0: 단일 파일 번역
            act_edit_gloss = menu.addAction("번역 용어집 교정...")  # 260623: 오역 용어 수정
            try:                                         # 용어집 사이드카 없으면 비활성화
                from viewer.study.export_translation import resolve_glossary_sidecar
                if not resolve_glossary_sidecar(item.data(0, self.DATA_FILE)):
                    act_edit_gloss.setEnabled(False)
                    act_edit_gloss.setToolTip("이 PDF 의 번역 용어집이 없습니다(먼저 번역).")
            except Exception:
                pass
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
        if chosen == act_split_view:
            if _is_copy:
                self.copyPaneRequested.emit()
            else:
                self.splitViewRequested.emit(True)
            return
        if act_fold_new is not None and chosen in (act_fold_new, act_fold_ren, act_fold_del):
            folder = Path(item.toolTip(0))          # 폴더 행은 툴팁에 실제 경로를 담는다
            if chosen == act_fold_new:
                if self._ask_new_folder(base=folder):
                    self._sync_after_transfer(folder)
            elif chosen == act_fold_ren:
                self._rename_folder(folder)
            else:
                self._delete_folder(folder)
            return
        if chosen == act_merge:
            self.mergeFilesRequested.emit([it.data(0, self.DATA_FILE) for it in sel_files])
        elif act_translate_sel is not None and chosen == act_translate_sel:
            self.translateFilesRequested.emit([it.data(0, self.DATA_FILE) for it in sel_files])
        elif act_translate is not None and chosen == act_translate:
            # 'PDF번역' 창을 열고 이 파일을 우측(번역 대상)에 담는다
            self.translateFilesRequested.emit([item.data(0, self.DATA_FILE)])
        elif act_edit_gloss is not None and chosen == act_edit_gloss:
            self.editGlossaryRequested.emit(item.data(0, self.DATA_FILE))
        elif act_tags is not None and chosen == act_tags:
            self._edit_file_tags(item.data(0, self.DATA_FILE))
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
        # 260902-1: 인덱스 고정(0/2/3/4)이던 것을 위젯 기준으로 — 행에 버튼(트리/단일)을
        #   끼워 넣자 번호가 밀려 취소/저장 대신 엉뚱한 항목이 늘어나던 것을 방지.
        for b in (self.btn_edit, self.btn_cancel, self.btn_save):
            r.setStretchFactor(b, 1 if on else 0)
        r.setStretch(r.count() - 1, 0 if on else 1)   # trailing stretch(마지막 항목)

    def is_edit_mode(self) -> bool:
        return self._edit_mode

    def set_split_state(self, on: bool) -> None:
        """260618-25: 현재 1단/2단 상태(우클릭 메뉴 라벨 결정용)."""
        self._split_on = bool(on)

    def set_pane_role(self, idx: int) -> None:
        """260618-27: 이 책갈피창의 창 인덱스(0=상단/1창, 1=하단/2창)."""
        self._pane_idx = 1 if idx == 1 else 0

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
        self.btn_view_mode_v.setVisible(not on)  # 260902-1: 뷰어 모드 전용(편집모드는 edit_ops)
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
            # 260618-27: 비편집 모드에서도 외부 PDF/폴더 드롭은 받도록 DropOnly 유지
            #   (내부 재배치 드래그만 비활성).
            self.tree.setDragEnabled(False)
            self.tree.setAcceptDrops(True)
            self.tree.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
            self.tree.setDropIndicatorShown(False)

    def _sync_selection_mode(self, *_):
        # 260825-5: 보기 모드에서도 Ctrl/Shift+클릭으로 여러 파일 선택 가능(인쇄 등).
        #   평범한 클릭은 단일 선택+이동, Ctrl/Shift 클릭은 다중 선택(이동 안 함).
        # 260901-2: 편집모드도 동일 — '다중/단일' 토글을 없애고 **항상 ExtendedSelection**.
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    # ---- target 파일 식별 -----------------------------------------------
    def _target_file_item(self) -> Optional[QTreeWidgetItem]:
        """편집 대상 파일 노드. 단일 PDF 모드면 그 파일, 폴더 모드면 선택 항목 기준."""
        sel = self.tree.selectedItems()
        # 1) 단일 PDF 트리
        # 260901-2: 트리 보기에서는 파일이 폴더 행의 자식이므로 최상위가 아니라 파일 노드로 센다.
        files = list(self._iter_file_nodes())
        if len(files) == 1:
            return files[0]
        # 2) 선택 항목이 속한 파일 노드(모두 같은 파일이어야 함)
        if sel:
            tops = {}
            for it in sel:
                f = self._file_node_of(it)
                if f is not None:
                    tops[id(f)] = f
            if len(tops) == 1:
                return next(iter(tops.values()))
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
                 if self._is_file_node(it)]
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
                self._take_node(it)          # 260901-2: 트리 보기(폴더 자식)도 제거
                # 평탄 모드 캐시 동기화
                if self._mode == "flat":
                    self._pdfs_flat = [q for q in self._pdfs_flat if q != p]
                self.fileOpCompleted.emit(str(p), "")        # 삭제 — 메인 비움 유지
            except Exception as e:
                QMessageBox.warning(self, "휴지통 이동 실패", f"{p.name}: {e}")
                self.fileOpCompleted.emit(str(p), str(p))    # revert → 원본 재로드
        if trashed:
            self.info.setText(f"파일 {trashed}개 휴지통으로 이동됨")

    def _take_node(self, it: QTreeWidgetItem):
        """260901-2: 트리에서 노드 제거 — 최상위/폴더 자식 어느 쪽이든.

        종전 `indexOfTopLevelItem` 만 쓰던 코드는 트리 보기에서 파일이 폴더 행의 자식이라
        인덱스가 -1 이 되어 **삭제해도 목록에 남아 있었다**."""
        par = it.parent()
        if par is not None:
            par.takeChild(par.indexOfChild(it))
            if self._is_folder_node(par) and par.childCount() == 0:
                self._take_node(par)          # 빈 폴더 행은 함께 정리
            return
        idx = self.tree.indexOfTopLevelItem(it)
        if idx >= 0:
            self.tree.takeTopLevelItem(idx)

    # ---- 260901-2: 파일 복사 / 이동 -------------------------------------
    def _subfolders(self) -> list:
        """루트 아래 하위 폴더(상대경로 순). 숨김·`__`·`.git` 류는 제외."""
        root = self._root_dir
        if not root or not Path(root).exists():
            return []
        # 260902-1: 종전 `rglob("*")` 는 파일까지 전부 훑어, 다운로드 폴더처럼 항목이 많은
        #   곳에서 우클릭 메뉴가 수 초~수십 초 뒤에 떠 '메뉴가 안 뜬다'로 보였다.
        #   → 폴더만, 깊이 4 까지, 최대 200개. 정렬은 상대경로 기준(대소문자 무시).
        out = []
        root = Path(root)
        try:
            import os
            for cur, dirs, _files in os.walk(root, topdown=True):
                rel_depth = len(Path(cur).relative_to(root).parts)
                dirs[:] = sorted((d for d in dirs
                                  if not d.startswith(".") and not d.startswith("__")),
                                 key=str.lower)
                if rel_depth >= 4:            # 너무 깊은 곳은 메뉴에서 생략(직접 선택으로)
                    dirs[:] = []
                    continue
                for d in dirs:
                    out.append(Path(cur) / d)
                    if len(out) >= 200:
                        return out
        except Exception:
            pass
        return out

    def _source_folder_of(self, paths: list):
        """260901-4: 선택한 파일들이 있는 폴더(모두 같은 폴더일 때). 섞였으면 첫 파일 기준.

        '새 폴더 만들기'·'다른 폴더 선택'의 **기준 위치**다 — 정리하려는 자료가 있는
        세부 폴더에서 시작해야 옮길 곳을 루트부터 다시 찾지 않는다."""
        folders = []
        for p in paths:
            d = Path(p).parent
            if d not in folders:
                folders.append(d)
        if folders:
            return folders[0]
        return self._root_dir

    def _add_transfer_submenu(self, menu, title: str, file_items: list, move: bool):
        """260901-2: '파일 복사/이동' 서브메뉴 — 대상 폴더 후보를 나열.

        260901-4(사용자 요청) 순서: ① 새 폴더 만들기 ② 다른 폴더 선택 ③ 트리에서 선택한 폴더
        ④ 루트 아래 하위 폴더. ①②를 맨 위에 두는 이유는 하위 폴더가 많을 때 목록 끝까지
        내려가야 닿던 문제를 없애기 위함이고, 둘 다 **선택한 파일이 있는 세부 폴더**를
        기준으로 연다(`_source_folder_of`).
        각 항목은 자체 `triggered` 로 실행한다(바깥 chosen 분기와 무관)."""
        from PyQt6.QtWidgets import QMenu
        sub = QMenu(title, menu)
        paths = [Path(it.data(0, self.DATA_FILE)) for it in file_items]
        src = self._source_folder_of(paths)

        def add(label, folder):
            a = sub.addAction(label)
            a.triggered.connect(lambda _=False, d=folder: self._transfer_files(paths, d, move))

        a_new = sub.addAction("새 폴더 만들기...")     # ①
        a_new.triggered.connect(
            lambda _=False: self._transfer_files(paths, self._ask_new_folder(base=src), move))
        a_pick = sub.addAction("다른 폴더 선택...")    # ②
        a_pick.triggered.connect(
            lambda _=False: self._transfer_files(paths, self._ask_pick_folder(move, start=src),
                                                move))
        sub.addSeparator()

        picked = [it for it in self.tree.selectedItems() if self._is_folder_node(it)]
        seen = set()
        for it in picked:                      # ③ 선택된 폴더 행
            d = Path(it.toolTip(0))
            if str(d) not in seen:
                seen.add(str(d)); add(f"📂 {d.name}  (선택한 폴더)", d)
        subs = [d for d in self._subfolders() if str(d) not in seen]
        if subs:
            if seen:
                sub.addSeparator()
            root = self._root_dir
            for d in subs[:40]:                # ④ 하위 폴더
                add(str(d.relative_to(root)).replace("\\", " / "), d)
        menu.addMenu(sub)
        return sub

    def _ask_new_folder(self, base=None):
        """루트(또는 선택·지정 폴더) 아래에 새 폴더를 만들고 그 경로를 반환. 취소면 None."""
        from PyQt6.QtWidgets import QInputDialog
        if base is None:
            base = self._root_dir
            for it in self.tree.selectedItems():
                if self._is_folder_node(it):
                    base = Path(it.toolTip(0)); break
        if not base:
            QMessageBox.information(self, "안내", "먼저 폴더를 열어 주세요.")
            return None
        name, ok = QInputDialog.getText(
            self, "새 폴더 만들기", f"{base} 아래에 만들 폴더 이름:")
        name = (name or "").strip()
        if not ok or not name:
            return None
        if _INVALID_FILENAME_RE.search(name):
            QMessageBox.warning(self, "오류", "폴더 이름에 사용할 수 없는 글자가 있습니다.")
            return None
        d = Path(base) / name
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, "폴더 만들기 실패", f"{name}: {e}")
            return None
        return d

    def _rename_folder(self, folder: Path):
        """260901-3: 폴더 이름 변경 — 안에 든 PDF 의 태그도 새 경로로 함께 옮긴다.

        폴더를 통째로 rename 하면 그 아래 모든 파일의 경로가 바뀌므로, 태그 저장소의
        키(경로)도 같이 갱신해야 태그가 끊기지 않는다(태그 SOT §6.1)."""
        from PyQt6.QtWidgets import QInputDialog
        folder = Path(folder)
        if not folder.is_dir():
            QMessageBox.warning(self, "오류", f"폴더가 없습니다: {folder}")
            return
        name, ok = QInputDialog.getText(self, "폴더 이름 변경", "새 폴더 이름:", text=folder.name)
        name = (name or "").strip()
        if not ok or not name or name == folder.name:
            return
        if _INVALID_FILENAME_RE.search(name):
            QMessageBox.warning(self, "오류", "폴더 이름에 사용할 수 없는 글자가 있습니다.")
            return
        new = folder.with_name(name)
        if new.exists():
            QMessageBox.warning(self, "오류", f"같은 이름의 폴더가 이미 있습니다: {name}")
            return
        inside = sorted(folder.rglob("*.pdf"))
        for p in inside:                      # 열려 있으면 핸들 해제(v1.6.21 규약)
            self.releaseFileRequested.emit(str(p))
        QApplication.processEvents()
        try:
            folder.rename(new)
        except Exception as e:
            QMessageBox.warning(self, "이름 변경 실패",
                                f"{folder.name}: {e}\n다른 프로그램이 폴더 안 파일을 "
                                "잡고 있을 수 있습니다.")
            return
        pairs = []
        for old_p in inside:
            new_p = new / old_p.relative_to(folder)
            self._after_move(old_p, new_p)    # 태그 승계
            pairs.append([str(old_p), str(new_p)])
        self._sync_after_transfer(new)
        if pairs:
            self.filesRelocated.emit(pairs)   # 인덱스·메인뷰 갱신
        self.info.setText(f"폴더 이름 변경: {folder.name} → {name}")

    def _delete_folder(self, folder: Path):
        """260901-3: 폴더 삭제 — **비어 있을 때만**.

        안에 파일이 있으면 지우지 않는다(대량 유실 방지). 파일부터 옮기거나 지우게 안내한다."""
        folder = Path(folder)
        if not folder.is_dir():
            QMessageBox.warning(self, "오류", f"폴더가 없습니다: {folder}")
            return
        rest = [p for p in folder.rglob("*") if p.is_file()]
        if rest:
            QMessageBox.information(
                self, "삭제할 수 없음",
                f"'{folder.name}' 안에 파일이 {len(rest)}개 있습니다.\n\n"
                "먼저 파일을 다른 폴더로 옮기거나 삭제한 뒤 폴더를 지워 주세요.\n"
                "(실수로 자료가 통째로 사라지지 않도록 빈 폴더만 삭제합니다.)")
            return
        if QMessageBox.question(
                self, "폴더 삭제",
                f"빈 폴더를 삭제할까요?\n\n{folder}") != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(folder)             # 빈 폴더(하위 빈 폴더 포함)
        except Exception as e:
            QMessageBox.warning(self, "삭제 실패", f"{folder.name}: {e}")
            return
        self._sync_after_transfer(folder.parent)
        self.info.setText(f"폴더 삭제됨: {folder.name}")

    def _ask_pick_folder(self, move: bool, start=None):
        """260901-4: 시작 위치 = 선택한 파일이 있는 세부 폴더(없으면 루트)."""
        base = start if start is not None else self._root_dir
        d = QFileDialog.getExistingDirectory(
            self, "이동 대상 폴더" if move else "복사 대상 폴더",
            str(base) if base else "")
        return Path(d) if d else None

    def _transfer_files(self, paths: list, dst, move: bool):
        """260901-2: 파일들을 dst 로 복사/이동.

        이동은 되돌리기 어려우므로 ① 확인을 받고 ② 뷰어 핸들을 먼저 풀고(`releaseFileRequested`)
        ③ 성공한 것만 태그를 새 경로로 옮긴 뒤(`TagStore.rehome` — 태그 SOT §6.1)
        ④ `filesRelocated` 로 앱에 알려 인덱스·메인뷰를 갱신하게 한다."""
        if dst is None:
            return
        dst = Path(dst)
        paths = [Path(p) for p in paths]
        if not paths:
            return
        if not dst.is_dir():
            QMessageBox.warning(self, "오류", f"대상 폴더가 없습니다: {dst}")
            return
        word = "이동" if move else "복사"
        # 대상이 원본과 같은 폴더면 이동은 무의미(복사는 사본 생성이라 허용)
        if move:
            paths = [p for p in paths if p.parent.resolve() != dst.resolve()]
            if not paths:
                QMessageBox.information(self, "안내", "이미 그 폴더에 있는 파일입니다.")
                return
            if QMessageBox.question(
                    self, "파일 이동",
                    f"{len(paths)}개 파일을 아래 폴더로 이동할까요?\n\n{dst}\n\n"
                    "디스크상 파일이 실제로 옮겨집니다.") != QMessageBox.StandardButton.Yes:
                return
        done, pairs, errors = 0, [], []
        for src in paths:
            if not src.exists():
                errors.append(f"{src.name}: 원본 없음")
                continue
            target = _unique_path(dst / src.name)
            try:
                if move:
                    self.releaseFileRequested.emit(str(src))   # v1.6.21 핸들 해제 규약
                    QApplication.processEvents()
                    shutil.move(str(src), str(target))
                    self._after_move(src, target)
                    pairs.append([str(src), str(target)])
                else:
                    shutil.copy2(src, target)
                    pairs.append(["", str(target)])
                done += 1
            except Exception as e:
                errors.append(f"{src.name}: {e}")
        if pairs:
            self._sync_after_transfer(dst)
            self.filesRelocated.emit(pairs)
        msg = f"{done}개 파일을 {dst} 로 {word}했습니다."
        if errors:
            msg += "\n실패: " + ", ".join(errors[:5])
        self.info.setText(f"파일 {done}개 {word}됨")
        QMessageBox.information(self, f"{word} 완료", msg)

    def _after_move(self, src: Path, dst: Path):
        """이동한 파일의 해시태그·키워드를 새 경로로 승계(태그 SOT §6.1)."""
        if self._tags is None:
            return
        try:
            self._tags.rehome(str(src), str(dst))
        except Exception:
            pass

    def _sync_after_transfer(self, dst: Path):
        """복사/이동 후 목록 재구성 — 루트 안의 변화만 반영(편집 중 책갈피는 건드리지 않음)."""
        if self._mode != "flat" or not self._root_dir:
            return
        try:
            cur = self._current_selected_file()
            self._pdfs_flat = list(Path(self._root_dir).rglob("*.pdf"))
            self._render_flat()
            if cur and Path(cur).exists():
                self._select_top_file(cur)
            self._on_filter(self.search_edit.text())
        except Exception:
            pass

    def _op_copy_to(self):
        """v1.6.20 K4: 선택한 PDF 파일들을 다른 폴더로 복사.
        260901-2: 대상 선택·실행은 우클릭 '파일 복사'와 같은 구현을 쓴다."""
        sel = self._selected_file_nodes()
        if not sel:
            QMessageBox.information(self, "안내", "복사할 PDF 파일을 선택하세요.")
            return
        paths = [Path(it.data(0, self.DATA_FILE)) for it in sel]
        # 260901-4: 선택한 파일이 있는 세부 폴더에서 열기(우클릭 '다른 폴더 선택'과 동일)
        self._transfer_files(paths, self._ask_pick_folder(
            False, start=self._source_folder_of(paths)), False)

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
        if self._is_file_node(it):
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
        for top in self._iter_file_nodes():         # 260901-2: 트리 보기 포함
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
        for top in self._iter_file_nodes():         # 260901-2: 트리 보기 포함
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
        # 260829(§19.11 P-D): Path.resolve() 는 항목마다 디스크 syscall(_getfinalpathname)을
        #   부른다 — 페이지 이동마다 파일 수만큼 반복돼(실측 732회/페이지, 127ms) 유휴 복귀
        #   프리징의 주범이었다. 프로젝트 표준 norm_key(normcase+normpath, 순수 문자열)로 교체.
        try:
            from viewer.pathutil import norm_key
            fpk = norm_key(file_path)
        except Exception:
            fpk = str(file_path).lower()
            def norm_key(p):  # 폴백 — 동일 규칙 근사
                return str(p).lower()
        top = None
        for it in self._iter_file_nodes():          # 260901-2: 트리 보기 포함
            d = it.data(0, self.DATA_FILE)
            if d and (d == str(file_path) or norm_key(d) == fpk):
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
                # 260902-1: 트리 보기에서는 최상위 조상이 **폴더 행**이라 `top` 과 달라져
                #   '같은 파일' 판정이 항상 실패 → 파일 노드를 클릭해도 첫 책갈피로 튀고,
                #   같은 페이지의 여러 책갈피 중 마지막만 골라지던 결함. 소속 파일 노드로 비교.
                if self._file_node_of(cur) is top:
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
        # 260821: 썸네일에서 페이지 삭제/이동이 있으면 앱이 페이지 재구성 + 책갈피 remap 으로 저장.
        #   (기존엔 페이지 편집이 이 저장 경로에 없어 '변경 사항이 없습니다'로 저장 안 되던 버그)
        if self._page_edit_dirty and self._page_edit_dirty() and self._page_edit_save:
            self._page_edit_save(str(src), bookmarks_raw)
            self._dirty = False
            self._commit_meta()
            return
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
            # 260822: 임시로 생성 후 목적지 배치(기본=원본 덮어쓰기, Shift=_edited(충돌 시 (k)))
            tmp = src.with_name(src.stem + "_book_savetmp.pdf")
            out = bridge.apply_to_pdf(src, tmp, bms)
            if self._finalize_save is not None:
                out = self._finalize_save(str(src), str(out))
            else:
                _dst = src.with_name(src.stem + "_edited.pdf")
                import os as _os
                _os.replace(str(out), str(_dst)); out = str(_dst)
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
        for it in self._iter_file_nodes():          # 260901-2: 트리 보기 포함
            d = it.data(0, self.DATA_FILE)
            if d and str(d).lower().endswith(".pdf"):
                out.append(str(d))
        return out

    def selected_file_paths(self) -> list:
        """260825: 선택된 PDF 파일 노드 경로(트리 순서·중복 제거) — 여러 파일 인쇄용.

        QTreeWidgetItem 은 unhashable 이라 set 에 넣으면 예외 → item.isSelected() 로 판정."""
        out, seen = [], set()

        def walk(item):
            for i in range(item.childCount()):
                ch = item.child(i)
                d = ch.data(0, self.DATA_FILE)
                if ch.isSelected() and d and str(d).lower().endswith(".pdf"):
                    s = str(d)
                    if s not in seen:
                        seen.add(s); out.append(s)
                walk(ch)

        walk(self.tree.invisibleRootItem())
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
    """target 이 존재하면 (1), (2), ... 접미사로 충돌 회피.
    260628: 표준 `pathutil.unique_path` 위임(SOT §7.0)."""
    from viewer.pathutil import unique_path
    return unique_path(target)


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
