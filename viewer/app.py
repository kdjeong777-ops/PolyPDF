"""메인 윈도우 - v1.6.2.

레이아웃 (v1.6.2): [Tree | Thumbs | MainView | RightPanel]
RightPanel = QSplitter(Vertical) [SearchArea(상) / ShotStrip(하)]

v1.6.2 변경 (v1.6.1 → v1.6.2):
- 선택 목록 히스토리 / 검색 히스토리 패널 **삭제**.
- 검색결과 오른쪽이 아닌 **아래**에 스크린샷 패널 배치.
- 스크린샷 PDF 저장 시 원본 PDF 페이지 1:1 재렌더 (`export_pdf_from_meta`).
- 검색결과 일괄 캡쳐 시 결과 개수가 한도를 넘으면 자동으로 한도 확장.
- 검색바 < > 버튼이 검색결과 리스트 전체(파일 경계 넘어) 순회.
- 책갈피 트리: PDF 내부 책갈피(TOC)가 있으면 갈매기로 펼쳐 자식 표시.

이전(v1.5.0~v1.6.1) 의 핵심 동작은 유지: 1:1 직접 렌더, 2장 보기, 검색 인덱싱, 즐겨찾기.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (Qt, QSettings, QStandardPaths, QThread, pyqtSignal,
                          QEventLoop, QObject, QTimer)
from viewer import updater as _updater_preload   # 260618-11: PyInstaller 번들 포함 보장(지연 import 누락 방지)
from viewer import components as _components_preload  # 260618-12: 구성요소 설치 모듈 번들 포함 보장
from PyQt6.QtGui import QAction, QKeySequence, QShortcut, QCursor, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTabWidget,
    QFileDialog,
    QStatusBar,
    QMessageBox,
    QProgressBar,
    QMenu,
    QToolBar,
    QPushButton,
    QStyle,
)

from viewer import side_panel_host as _sp
from viewer.edit_controller import EditMixin
from viewer.present_controller import PresentMixin
from viewer.print_controller import PrintMixin
from viewer.study_controller import StudyMixin
from viewer.update_controller import UpdateMixin
from viewer import settings_store, __version__
# v1.6.2: 히스토리 패널 제거. HistoryItem 만 last_main 직렬화용으로 남김.
from viewer.history import HistoryItem


from viewer.workers import (
    IndexWorker, SearchWorker, BookmarkerWorker, StudyBuildWorker, run_in_thread)
from viewer.widgets.bookmark_tree import BookmarkTree
from viewer.widgets.thumbs_list import PageThumbs
from viewer.widgets.main_view import MainView
from viewer.widgets.search_panel import SearchBar, SearchResults
from viewer.widgets.strip import MiniStrip
from viewer.widgets.study_panel import StudyPanel
from viewer import screenshot as ss
from viewer.resources_path import resource_path


def _data_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


class _MergeThread(QThread):
    """260611-33: PDF 병합/2단 배치를 백그라운드 스레드에서 실행(UI '응답 없음' 방지).
    job(progress)=실제 작업. progress(done,total,label)->bool(계속). 취소는 cancel()."""
    progressed = pyqtSignal(int, int, str)
    failed = pyqtSignal(str)
    cancelledSig = pyqtSignal()
    okSig = pyqtSignal()

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self._job = job
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _progress(self, done, total, label):
        self.progressed.emit(int(done), int(total), str(label))
        return not self._cancel

    def run(self):
        from viewer.twoup import MergeCancelled
        try:
            self._job(self._progress)
        except MergeCancelled:
            self.cancelledSig.emit()
        except Exception as e:           # noqa: BLE001
            self.failed.emit(str(e))
        else:
            self.okSig.emit()


class _UpdateSignals(QObject):
    """260618-11: 업데이트 확인 스레드 → 메인 스레드 결과 전달."""
    done = pyqtSignal(object, bool)     # (info dict|None, manual)
    dl_done = pyqtSignal(str)           # 260618-24: 백그라운드 다운로드 완료(zip 경로|"")


class MainWindow(EditMixin, PresentMixin, PrintMixin, StudyMixin, UpdateMixin, QMainWindow):
    SETTINGS_FILE = "settings.json"
    MAX_RECENT_FOLDERS = 10

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PolyPDF  v{__version__}")
        self.resize(1700, 980)

        # v1.6.2: 히스토리 패널/모델 제거
        self._current_main: Optional[HistoryItem] = None
        self._folder: Optional[Path] = None
        self._hyperlinks = None              # 260609-3: 폴더별 HyperlinkStore
        self._page_meta = None               # 260609-14: 폴더별 PageMetaStore(크롭·숨김)
        self._edit_snap = None               # 260609-23(J2): 편집모드 진입 시 스냅샷
        self._edit_dirty = False             # 260609-23(J2): 미저장 변경 여부
        self._db_path = _data_dir() / "index.db"
        # 단어장 상태
        self._study_pdf: Optional[Path] = None
        self._study_store = None        # StudyStore (lazy)
        self._user_store = None         # UserStore (사용자 편집, lazy)
        self._dict_store = None         # DictStore (계층형 전문 용어사전, lazy) — P1
        self._spot_terms_cache = None   # P4: 다단어 용어 spotting 목록 캐시
        self._page_term_rects = {}      # P4: 현재 페이지 spotted 용어 → rects
        self._tts = None                # TTS (lazy)
        self._study_threads: list = []   # 빌드 워커/스레드 참조 보존
        self._last_read_page = -1        # 자동읽기 중복 방지
        self._ar_items: list = []        # 단어장 자동읽기: 현재 페이지 (lemma,lang)
        self._ar_idx = 0
        self._ar_advancing = False       # 리더가 페이지를 넘기는 중(사용자 이동과 구분)
        from PyQt6.QtCore import QTimer as _QTimer
        self._autoread_timer = _QTimer(self)
        self._autoread_timer.setInterval(180)
        self._autoread_timer.timeout.connect(self._on_autoread_tick)
        self._thread_keep: list = []
        self._index_workers: list = []      # 260611-89: 진행 중 인덱싱(폴더/파일 전환 시 취소)
        self._search_scope = None           # 260616-3: 검색 한정 파일 집합(책갈피 목록). None=전체
        self._last_results: list = []
        self._recent_folders: list = []
        self._pending_screenshot_after_load: bool = False
        self._current_shot_path = None        # v1.6.7 E1: 표시 중 스크린샷 카드 원본 path
        self._favorites: list = []
        self._law_favorites: list = []        # 260616-6: 법령·고시 즐겨찾기(메인 즐겨찾기 아래 별도)
        self._law_panel = None                # 260616-19: 임베드된 법령·고시 패널
        self._law_window = None               # 260616-19: 전체화면 팝아웃 창(없으면 임베드)
        self._law_saved = None                # 법령 패널 표시 전 메인 레이아웃 백업
        self._kcsc_panel = None               # 260618-37: 건설기준(KCSC) 패널(법령과 동일 슬롯)
        self._kcsc_window = None
        self._kcsc_saved = None
        self._kcsc_favorites: list = []       # 260618-39: 건설기준 즐겨찾기
        self._kipo_panel = None               # 260618-43: 특허(KIPO) 등록정보 패널(동일 슬롯)
        self._kipo_window = None
        self._kipo_saved = None
        self._content_panel = None            # 260623: 메인 검색바가 본문 검색할 우측 패널(없으면 PDF)
        self._content_query = ""              # 260623: 우측 패널 본문 검색어(◀▶ 이동용)
        self._kipo_favorites: list = []       # 260618-43: 특허 즐겨찾기
        self._prefs: dict = {
            "restore_session": True, "restore_last_page": True,
            "restore_screenshots": True, "screenshot_max": 30,
            "open_edit_mode": True,       # 260822: 시작 시 편집 모드(기본) / 보기 모드
            # v1.6.23: 상단 토글 툴바만 prefs 로 관리 (기본 숨김).
            # 패널(검색결과/스크린샷) 가시성은 panels_visible 로 저장·복원, 기본 True.
            "show_panel_toolbar": True,   # 260606-25: 패널 툴바 기본 보이기
            "cross_file_nav": True,       # 260609-2/28: 페이지 경계에서 다음/이전 파일 이동(기본 켜짐)
            # 260609-3: 하이퍼링크 URL 허용 도메인(youtube 등). 빈 값이면 모듈 기본 사용.
            "hyperlink_url_allowlist": [],
            # 260609-11(C8): 페이지 내 하이퍼링크 버튼의 상단 오프셋(px)
            "hyperlink_top_offset_px": 10,
            # 260609-5: 발표 포인터 프리셋(빈 값이면 모듈 기본)·활성 인덱스
            "presentation_pointers": [],
            "presentation_pointer_active": 0,
            # 260609-6: 발표 상하 2분할·중앙 겹침%
            "presentation_overlap_pct": 10,
            # 260609-12(D1): 발표 상단 띠 높이(px)
            "presentation_topbar_h": 64,
            # 260609-16(F3): 발표 펜(빈 값이면 모듈 기본)·활성·단축키
            "presentation_pens": [],
            "presentation_pen_active": 0,
            "presentation_pen_keys": [],
            "presentation_pen_straight": True,   # 260609-18(G3)
            "presentation_eraser_widths": [12, 30],  # 260609-20(I3)
            # 260611-2: 본문·발표 공유 선긋기 — 펜5(빈 값이면 MV 기본)·선종류·지우개폭·하이라이트투명도
            "draw_pens": [],
            "draw_line_mode": 0,                 # 0=직선 1=하이라이트 2=자유곡선
            "draw_eraser_widths": [12, 30],
            "draw_highlight_alpha": 35,          # 하이라이트 불투명도(%)
            "capture_global": False,             # 260611-3(6): 화면 캡처 전역 단축키 사용
            # 260609-17(F4): 녹화
            "recording_dir": "",
            "recording_audio_mode": "mic",   # none/mic/system/both
            "recording_mic": "",
            "recording_system": "",
            "recording_keys": [],            # [녹화/재개, 중지]
            "ffmpeg_path": "",
            "recording_test_ok": False,      # 260611-25: 녹화 테스트 합격 결과
        }

        self._build_ui()
        self._build_toolbar()
        self._build_menus()
        self._wire_signals()
        self._restore_settings()
        # 260628(FIX): API 키 미입력 게이팅을 **시작 시에도** 적용. 종전에는
        #   `_apply_prefs`(설정 확인 시)에서만 불려서, 키가 없어도 프로그램을 새로 켜면
        #   법령·건설기준·특허 버튼이 그대로 보이고 메뉴도 활성 상태였다.
        try:
            self._gate_api_dependent_ui(self._prefs)
        except Exception:
            pass
        self._update_right_panel_visibility()   # 260606-10: 패널 비면 메인 전체 폭
        # 260825: 검색 색인이 비어 있으면(트라이그램 마이그레이션 잔재 등) 자동 재인덱싱
        QTimer.singleShot(1200, self._startup_index_check)

        # 260618-11: 업데이트 — 스레드 결과를 메인 스레드로 전달하는 시그널 홀더
        self._update_sig = _UpdateSignals()
        self._update_sig.done.connect(self._on_update_result)
        self._update_sig.dl_done.connect(self._on_bg_dl_done)   # 260618-24
        self._pending_update = None    # 260618-24: 새 버전 info(있으면 종료 시 업그레이드 제안)
        self._pending_zip = None       # 260618-24: 미리 받아둔 업데이트 zip 경로
        self._dl_in_progress = False
        self._updating = False         # 260618-24: 업그레이드 진행 중(종료 시 재질문 방지)
        # 시작 시 자동 확인(배포 exe + 설정 켜짐) — 4초 뒤 백그라운드
        try:
            from viewer import updater as _upd
            if _upd.is_frozen() and self._prefs.get("auto_check_update", True):
                QTimer.singleShot(4000, lambda: self._check_for_updates(manual=False))
        except Exception:
            pass

    # ===== UI =========================================================
    def _build_ui(self):
        self.setAcceptDrops(True)             # v1.6.11 I2: PDF/폴더 드래그&드롭
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # v1.6.2: 4단 가로 분할 (이전 5단에서 히스토리 영역 삭제)
        # 260616-12: 손잡이 더블클릭으로 책갈피/썸네일 접기·펴기
        from viewer.widgets.toggle_splitter import ToggleSplitter
        self.splitter = ToggleSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(8)

        # 1단 책갈피 트리 — 260611-75: 기본 폭 좁게. 260618-19: 세로 스플리터로 래핑
        #   (상=현재 폴더 책갈피, 하=우측 2단 창이 '다른 폴더' 파일일 때 그 파일 표시).
        self.bookmark_tree = BookmarkTree()         # 상단 = 좌측 창 폴더 목록
        self.bookmark_tree.suggest_provider = self._autotag_suggest_single  # 260830 P3(§8.1)
        self.bookmark_tree.review_provider = self._autotag_review_candidates  # 260830 P5(§8.5)
        self.bookmark_tree.setMinimumWidth(150)
        self.bookmark_tree_right = BookmarkTree()   # 260618-22: 하단 = 우측 창 폴더 목록(2단·다른폴더)
        self.bookmark_tree_right.setMinimumWidth(150)
        self._bk_split = QSplitter(Qt.Orientation.Vertical)
        self._bk_split.addWidget(self.bookmark_tree)
        self._bk_split.addWidget(self.bookmark_tree_right)
        self._bk_split.setCollapsible(0, False)
        self._bk_split.setCollapsible(1, True)
        self.bookmark_tree_right.hide()             # 기본 숨김(같은 폴더/1단/우측 비었을 때)
        self._folder_right = None                   # 우측 창 폴더
        self.splitter.addWidget(self._bk_split)

        # 2단 페이지 썸네일
        self.page_thumbs = PageThumbs()
        self.page_thumbs.set_image_resolver(self._thumb_images_for)  # 260611-18(A5)
        self.splitter.addWidget(self.page_thumbs)

        # 3단 메인 뷰어 — 260606-8: 2분할(활성 창 라우팅). 기본 단일(오른쪽 숨김).
        from PyQt6.QtWidgets import QFrame
        self._mv = [MainView(), MainView()]
        self._active_pane = 0
        self._split_on = False               # 2분할 상태(가시성 대신 플래그로 추적)
        self._panel_in_drawer = False        # 260606-19: 우측 패널이 슬라이드 드로어에 있는지
        self._panes: list = []
        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        for _i, _mv in enumerate(self._mv):
            _fr = QFrame()
            _fr.setObjectName(f"pane{_i}")
            _pl = QVBoxLayout(_fr)
            _pl.setContentsMargins(0, 0, 0, 0)
            _pl.setSpacing(0)
            _pl.addWidget(_mv)
            self._panes.append(_fr)
            self.main_split.addWidget(_fr)
        self._panes[1].setVisible(False)         # 기본 단일
        self.main_split.setSizes([1000, 1000])
        self.splitter.addWidget(self.main_split)

        # 4단 우측 패널 = 검색결과(상) + 스크린샷(하) 세로 분할
        self.right_panel = self._build_right_panel()
        self.splitter.addWidget(self.right_panel)

        # 260603/.../260606-11: 본문 읽기 — 단일 컨트롤러(읽기 대상=클릭한 창),
        #   각 창(2분할 포함)에 읽기 ▶/■+풀다운+mp3+캡쳐 버튼을 둠(각 창에서만 동작).
        # 260606-17: 캡쳐 모드 상태(전체화면/지정/사용자크기1~5 + 복사크기)
        self._cap_mode = "full"
        self._cap_copy = "visible"
        self._cap_sizes = [{"name": f"사용자{i+1}", "w": 300, "h": 200}
                           for i in range(5)]
        self._cap_menus = []
        from viewer.widgets.read_aloud import ReadAloud
        self.read_aloud = ReadAloud(self)
        self._read_btns = [self._build_pane_controls(0),
                           self._build_pane_controls(1)]
        self.btn_read, self.btn_read_menu = self._read_btns[0]
        # 260606-12: ▶/■ 표시는 '그 창이 읽는 중'일 때만 — 두 창 동기화 버그 방지
        try:
            self.read_aloud.stateChanged.disconnect()   # make_read_buttons 의 기본 on_state 제거
        except Exception:
            pass
        self.read_aloud.stateChanged.connect(lambda _=False: self._update_read_buttons())
        # 단어장 재생구간 메뉴의 성우 목록 공유
        # 단어장 재생구간 메뉴의 성우 목록 공유
        try:
            self.study_panel.set_voices(self._study_get_tts().voice_names())
        except Exception:
            pass

        self.splitter.setSizes(self.DEFAULT_SPLITTER_SIZES)
        for i in (0, 1, 3):
            self.splitter.setCollapsible(i, True)
        # M1: 좌1을 좌우로 조절해도 좌2/우4 폭 유지, 메인 뷰어만 신축
        for i in range(self.splitter.count()):
            self.splitter.setStretchFactor(i, 1 if i == 2 else 0)
        layout.addWidget(self.splitter)

        # 상태바
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.status.addPermanentWidget(self.progress)

        self.setCentralWidget(central)
        self._central = central
        self._build_drawer(central)

    # ===== 260606-9: 2분할 시 검색·스크린샷 슬라이딩 드로어(오버레이) =======
    def _build_drawer(self, central):
        from PyQt6.QtWidgets import QToolButton as _TB, QVBoxLayout as _VB
        from PyQt6.QtCore import QPropertyAnimation
        self._drawer = QWidget(central)
        self._drawer.setObjectName("drawer")
        self._drawer.setAutoFillBackground(True)
        self._drawer.setStyleSheet(
            "QWidget#drawer{background:#f3f3f3; border-left:1px solid #aaa;}")
        _dl = _VB(self._drawer)
        _dl.setContentsMargins(0, 0, 0, 0)
        self._drawer_lay = _dl
        self._drawer.hide()
        self._drawer_open = False
        self._drawer_btn = _TB(central)
        self._drawer_btn.setToolTip("검색·단어장·스크린샷 패널 펼치기/접기")
        self._drawer_btn.setText("‹")
        self._drawer_btn.clicked.connect(self._toggle_drawer)
        self._drawer_btn.hide()
        self._drawer_anim = QPropertyAnimation(self._drawer, b"geometry", self)
        self._drawer_anim.setDuration(180)
        self._drawer_anim.finished.connect(self._on_drawer_anim_done)
        # 260606-13: 캡쳐 시 드로어를 잠깐 펼쳤다가 작업 없으면 1.5초 후 접기
        from PyQt6.QtCore import QTimer as _QTimer
        self._drawer_timer = _QTimer(self)
        self._drawer_timer.setSingleShot(True)
        self._drawer_timer.timeout.connect(self._on_drawer_idle_timeout)

        # 260829(§19.11 P-C): 창 비활성 15분 → 렌더 캐시 자발 해제(복귀 프리징 대책).
        #   활성화되면 changeEvent 가 stop — 실사용 중에는 절대 발화하지 않는다.
        self._idle_release_timer = _QTimer(self)
        self._idle_release_timer.setSingleShot(True)
        self._idle_release_timer.setInterval(15 * 60 * 1000)
        self._idle_release_timer.timeout.connect(self._release_render_memory)
        self._handle_offset = 0              # 260606-20: 손잡이 세로 비킴 오프셋
        self._last_scroll_val = 0
        for mv in self._mv:                  # 뷰어 스크롤 시 손잡이 위치 갱신
            try:
                mv.doc_scroll.valueChanged.connect(
                    lambda _v, m=mv: self._update_handle_for_scroll(m))
            except Exception:
                pass

    def _drawer_auto_show(self):
        """캡쳐 시 드로어를 슬라이드로 펼치고 1.5초 자동 접기 타이머 시작."""
        if not getattr(self, "_panel_in_drawer", False):
            return
        if not self._drawer_open:
            self._toggle_drawer()
        self._drawer_timer.start(1500)

    def _on_drawer_idle_timeout(self):
        if not self._panel_in_drawer or not self._drawer_open:
            return
        # 마우스가 드로어 위에 있으면(작업 중) 접지 않고 연장
        try:
            from PyQt6.QtGui import QCursor
            local = self._drawer.mapFromGlobal(QCursor.pos())
            if self._drawer.rect().contains(local):
                self._drawer_timer.start(1500)
                return
        except Exception:
            pass
        self._toggle_drawer()      # 접기

    def _drawer_width(self) -> int:
        return min(360, max(220, self._central.width() // 2))

    def _position_handle(self):
        W = self._central.width(); H = self._central.height()
        bw, bh = 20, 96
        dw = self._drawer_width()
        hx = (W - dw - bw) if self._drawer_open else (W - bw)
        # 260606-20: 스크롤바와 겹치면 손잡이를 위/아래로 비킴(_handle_offset)
        off = getattr(self, "_handle_offset", 0)
        hy = max(0, min(H - bh, (H - bh) // 2 + off))
        self._drawer_btn.setGeometry(max(0, hx), hy, bw, bh)
        self._drawer_btn.setText("›" if self._drawer_open else "‹")
        self._drawer_btn.raise_()

    def _update_handle_for_scroll(self, view):
        """260606-20: 닫힌 손잡이가 뷰어 스크롤 위치(중앙 부근)와 겹치면 스크롤 방향에
        따라 위/아래로 비킨다. 겹치지 않으면 중앙 복귀."""
        try:
            if not self._panel_in_drawer or self._drawer_open:
                return
            # 손잡이는 우측 가장자리 → 관련 창: 분할이면 오른쪽 창, 아니면 활성 창
            relevant = self._mv[1] if self._split_on else self.main_view
            if view is not relevant:
                return
            sb = view.doc_scroll
            mx = sb.maximum()
            val = sb.value()
            H = self._central.height()
            bh = 96
            frac = (val / mx) if mx > 0 else 0.0
            thumb_y = frac * H                 # 스크롤 썸 대략 위치(중앙 기준)
            center_y = H / 2.0
            overlap = abs(thumb_y - center_y) < (bh * 0.85)
            if overlap:
                down = val > getattr(self, "_last_scroll_val", 0)
                self._handle_offset = -bh if down else bh
            else:
                self._handle_offset = 0
            self._last_scroll_val = val
            self._position_handle()
        except Exception:
            pass

    def _position_drawer(self):
        W = self._central.width(); H = self._central.height()
        dw = self._drawer_width()
        x = (W - dw) if self._drawer_open else W
        self._drawer.setGeometry(x, 0, dw, H)
        self._position_handle()

    def _toggle_drawer(self):
        if not self._panel_in_drawer:
            return
        from PyQt6.QtCore import QRect
        self._drawer_open = not self._drawer_open
        W = self._central.width(); H = self._central.height()
        dw = self._drawer_width()
        self._drawer.show(); self._drawer.raise_()
        self._drawer_anim.stop()
        self._drawer_anim.setStartValue(self._drawer.geometry())
        self._drawer_anim.setEndValue(QRect((W - dw) if self._drawer_open else W, 0, dw, H))
        self._drawer_anim.start()
        self._position_handle()

    def _on_drawer_anim_done(self):
        if not self._drawer_open:
            self._drawer.hide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        try:
            if getattr(self, "_panel_in_drawer", False):
                self._position_drawer()
        except Exception:
            pass

    # ===== 260606-8: 2분할 메인 뷰어 (활성 창 라우팅) =====================
    @property
    def main_view(self):
        """기존 코드 호환: '활성 창'을 반환(거의 모든 기능이 활성 창에 작동)."""
        return self._mv[self._active_pane]

    def _build_pane_controls(self, idx: int):
        """260606-11: 한 메인 창(idx)의 툴바에 읽기 ▶/■+풀다운, mp3, 캡쳐 버튼을 구성.
        읽기/ mp3 는 '그 창'을 대상으로 동작. (좌→우: [캡쳐][▶ 전체▾][mp3])"""
        from viewer.widgets.read_aloud import make_read_buttons
        from PyQt6.QtWidgets import QWidget as _QW, QHBoxLayout as _HB, QToolButton as _TB
        from PyQt6.QtGui import QIcon as _QIcon
        from PyQt6.QtCore import QSize as _QSize
        mv = self._mv[idx]
        H = mv.TOOLBAR_H
        btn_read, btn_read_menu = make_read_buttons(self.read_aloud, self)
        btn_read.setFixedSize(26, H)
        btn_read_menu.setFixedSize(78, H)         # 260606-19: 폭 최소(전체연속 ▾)
        btn_read_menu.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        try:
            btn_read.clicked.disconnect()        # 기본 controller.toggle 해제
        except Exception:
            pass
        btn_read.clicked.connect(lambda _=False, i=idx: self._pane_read_toggle(i))
        grp = _QW()
        # 260606-18: 캡쳐 드롭다운과 읽기 ▶ 사이 구분 여백
        gl = _HB(grp); gl.setContentsMargins(10, 0, 0, 0); gl.setSpacing(1)
        gl.addWidget(btn_read); gl.addWidget(btn_read_menu)
        # mp3(이 창 대상)
        mp3 = _TB(self)
        mp3.setToolTip("이 창의 PDF를 책갈피 기준으로 나눠 mp3(+가사)로 저장")
        mp3.clicked.connect(lambda _=False, i=idx: self._on_main_mp3(view=self._mv[i]))
        mp3.setFixedHeight(H)
        try:
            mp3.setIcon(_QIcon(resource_path("icon_mp3.png")))
            mp3.setIconSize(_QSize(24, 24))     # 260611-31: 정사각 mp3 아이콘
        except Exception:
            mp3.setText("mp3")
        cap = self._make_capture_button(idx)
        cap_dd = self._make_capture_dropdown(idx)        # 260606-17: 캡쳐 모드 드롭다운
        cap_grp = _QW()
        # 260606-18: › 와 캡쳐 버튼 사이 구분 여백
        cgl = _HB(cap_grp); cgl.setContentsMargins(10, 0, 0, 0); cgl.setSpacing(1)
        cgl.addWidget(cap); cgl.addWidget(cap_dd)
        if idx == 0:
            self.btn_capture = cap
            self.btn_main_mp3 = mp3
        # add_main_button 은 ‹›바 우측 첫 칸에 끼움 → '오른쪽 먼저' 추가
        mv.add_main_button(mp3)
        mv.add_main_button(grp)
        mv.add_main_button(cap_grp)
        return btn_read, btn_read_menu

    def _update_read_buttons(self):
        """260606-12: 각 창의 ▶/■ 는 '그 창이 읽는 중'일 때만 ■(빨강)."""
        for i, (btn, _menu) in enumerate(getattr(self, "_read_btns", [])):
            on = (self.read_aloud.is_active()
                  and getattr(self.read_aloud, "_view", None) is self._mv[i])
            btn.setText("■" if on else "▶")
            btn.setStyleSheet(
                "QToolButton{color:%s;font-size:16px;font-weight:bold;}"
                % ("#c0392b" if on else "#1565c0"))

    def _pane_read_toggle(self, idx: int):
        """그 창(idx)의 읽기 시작/정지(다른 창이 읽는 중이면 멈추고 이 창으로)."""
        ra = self.read_aloud
        if ra.is_active() and getattr(ra, "_view", None) is self._mv[idx]:
            ra.stop()
            return
        if ra.is_active():
            ra.stop()
        self._set_active_pane(idx)
        ra.set_target(self._mv[idx], idx)
        if self._maybe_offer_ocr(self._mv[idx]):   # 읽을 내용 없으면 OCR 제안(아이템3)
            return
        ra.start()

    def _make_capture_button(self, idx: int):
        b = QPushButton()
        ico = resource_path("screenshot.png")
        if ico:
            b.setIcon(QIcon(ico))
        else:
            b.setText("📷")
        b.setToolTip("이 창 캡처 (활성 창은 Ctrl+Shift+S)")
        try:                                      # 260606-19: 캡쳐 글자 삭제·폭 최소
            b.setFixedSize(34, self._mv[idx].TOOLBAR_H)
        except Exception:
            b.setFixedWidth(34)
        b.clicked.connect(
            lambda _=False, i=idx: (self._set_active_pane(i),
                                    self._do_capture(self._mv[i])))
        return b

    # ===== 260606-17: 캡쳐 모드(전체화면/지정/사용자크기) + 복사크기 =========
    def _make_capture_dropdown(self, idx: int):
        from PyQt6.QtWidgets import QToolButton
        dd = QToolButton(self)
        dd.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        dd.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        try:
            dd.setFixedHeight(self._mv[idx].TOOLBAR_H)
        except Exception:
            pass
        self._cap_menus.append(dd)
        self._rebuild_capture_menu(dd)
        return dd

    def _capture_mode_label(self) -> str:
        m = self._cap_mode
        if m == "region":
            return "지정"
        if m.startswith("user"):
            i = int(m[4:])
            return self._cap_sizes[i]["name"] if 0 <= i < len(self._cap_sizes) else "전체"
        return "전체"

    def _rebuild_capture_menu(self, dd):
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QActionGroup
        m = QMenu(dd)
        grp = QActionGroup(m); grp.setExclusive(True)

        def addmode(key, label):
            a = m.addAction(label); a.setCheckable(True)
            a.setChecked(self._cap_mode == key)
            grp.addAction(a)
            a.triggered.connect(lambda _=False, k=key: self._set_cap_mode(k))
        addmode("full", "전체")
        addmode("region", "지정")
        for i in range(5):
            addmode(f"user{i}", self._cap_sizes[i]["name"])
        m.addSeparator()
        cm = m.addMenu("캡쳐 화질 설정")
        cg = QActionGroup(cm); cg.setExclusive(True)
        for key, label in (("visible", "보이는 화질"), ("original", "원본 화질")):
            a = cm.addAction(label); a.setCheckable(True)
            a.setChecked(self._cap_copy == key)
            cg.addAction(a)
            a.triggered.connect(lambda _=False, k=key: self._set_cap_copy(k))
        m.addSeparator()
        a = m.addAction("사용자 크기 설정...")
        a.triggered.connect(self._edit_capture_sizes)
        dd.setMenu(m)
        dd.setText(self._capture_mode_label() + " ▾")

    def _refresh_capture_labels(self):
        for dd in getattr(self, "_cap_menus", []):
            self._rebuild_capture_menu(dd)

    def _set_cap_mode(self, k):
        self._cap_mode = k
        self._refresh_capture_labels()
        try:
            self._save_settings_now()
        except Exception:
            pass

    def _set_cap_copy(self, k):
        self._cap_copy = k
        self._refresh_capture_labels()
        try:
            self._save_settings_now()
        except Exception:
            pass

    def _edit_capture_sizes(self):
        from viewer.widgets.capture_settings import CaptureSizesDialog
        d = CaptureSizesDialog(self._cap_sizes, self)
        if d.exec():
            self._cap_sizes = d.result_sizes()
            self._refresh_capture_labels()
            try:
                self._save_settings_now()
            except Exception:
                pass

    def _render_page_pixmap(self, view, page_index):
        """페이지를 픽스맵으로 렌더(원본=base_dpi, 보이는=150)."""
        try:
            import fitz
            from PyQt6.QtGui import QImage, QPixmap
            doc = view._doc.doc
            dpi = view._base_dpi if self._cap_copy == "original" else 150
            page = doc.load_page(int(page_index))
            z = dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
            fmt = (QImage.Format.Format_RGBA8888 if pix.alpha
                   else QImage.Format.Format_RGB888)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
            return QPixmap.fromImage(img.copy())
        except Exception:
            return None

    def _capture_pages(self, view, rows):
        """선택 페이지들(전체화면)을 각각 캡쳐해 스크린샷 패널에 추가."""
        cur = view.current_file()
        if not cur:
            return
        stem = Path(cur).stem
        name = Path(cur).name
        n = 0
        for pg in rows:
            pm = self._render_page_pixmap(view, pg)
            if pm is None or pm.isNull():
                continue
            saved = ss.save_screenshot(pm, source_name=name, suffix=f"_p{pg+1}")
            self.shot_strip.add_item(str(saved), kind="image", label=stem,
                                     src_pdf=cur, src_page=int(pg), prepend=False)
            n += 1
        if n:
            self.status.showMessage(f"{n}개 페이지 캡쳐", 4000)
            self._after_capture()

    def _capture_region(self, view, fixed_size):
        """'지정'/'사용자 크기' 영역 캡쳐 오버레이 실행."""
        from viewer.widgets.region_capture import RegionCaptureOverlay
        mode = "fixed" if fixed_size else "region"
        ov = RegionCaptureOverlay(mode=mode, fixed_size=fixed_size,
                                  copy_mode=self._cap_copy, parent=self)
        pm = ov.grab()
        if pm is None or pm.isNull():
            return
        cur = view.current_file()
        name = Path(cur).name if cur else "region.png"
        saved = ss.save_screenshot(pm, source_name=name, suffix="_R")
        try:
            QApplication.clipboard().setPixmap(pm)
        except Exception:
            pass
        self.shot_strip.add_item(str(saved), kind="image",
                                 label=Path(name).stem, prepend=False)
        self.status.showMessage("영역 캡쳐 저장", 4000)
        self._after_capture()

    def _after_capture(self):
        """캡처 직후 결과를 보여 준다.

        260628-14(회귀 수정): 드로어 **자동표시**(1.5초 뒤 접힘)는 원래 **2단 보기** 때문에
        패널을 화면 밖으로 비켜 둔 경우를 위한 것이다(260606-13). 그런데 시작 기본 상태가
        '패널 숨김'(§3.1.1)이 되면서 **평상시에도 드로어 모드**가 되어, 캡처 결과가 잠깐
        나타났다 사라져 **'캡처가 안 된다'로 보였다**(사용자 보고).
        → 2단 때만 자동표시를 쓰고, 그 외에는 스크린샷 패널을 **정식으로 펼친다**
          (`act_toggle_shot` → `_sync_right_layout` 이 컬럼 모드로 되돌린다).
        """
        if getattr(self, "_panel_in_drawer", False) and getattr(self, "_split_on", False):
            self._drawer_auto_show()
        else:
            self._ensure_shots_visible()

    def _on_clipboard_save(self):
        """260606-17: 클립보드 비우고 스크린샷들을 순서대로 클립보드(히스토리)에 복사.
        각 항목을 간격을 두고 복사 → Win+V 목록에 차례로 쌓임."""
        paths = []
        try:
            paths = [p for p in self.shot_strip.all_paths()
                     if p and Path(p).exists()
                     and str(p).lower().endswith((".png", ".jpg", ".jpeg"))]
        except Exception:
            paths = []
        if not paths:
            QMessageBox.information(self, "클립보드 저장", "복사할 스크린샷이 없습니다.")
            return
        # 클립보드 히스토리 비우기(베스트 에포트) + 현재 클립보드 클리어
        try:
            import subprocess
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Command Clear-Clipboard -ErrorAction SilentlyContinue | "
                 "ForEach-Object { Clear-Clipboard }; "
                 "try{[Windows.ApplicationModel.DataTransfer.Clipboard,Windows.ApplicationModel.DataTransfer,ContentType=WindowsRuntime]::ClearHistory()}catch{}"],
                creationflags=0x08000000, timeout=8)
        except Exception:
            pass
        try:
            QApplication.clipboard().clear()
        except Exception:
            pass
        from PyQt6.QtGui import QImage
        from PyQt6.QtCore import QTimer
        self._clip_queue = list(paths)
        self._clip_total = len(paths)

        def copy_next():
            if not self._clip_queue:
                self.status.showMessage(
                    f"클립보드 저장 완료: {self._clip_total}개 — Win+V 로 붙여넣기", 7000)
                return
            p = self._clip_queue.pop(0)
            try:
                img = QImage(p)
                if not img.isNull():
                    QApplication.clipboard().setImage(img)
            except Exception:
                pass
            QTimer.singleShot(350, copy_next)   # 간격 → 각각 히스토리 항목으로

        self.status.showMessage("클립보드 저장 중...", 3000)
        copy_next()

    def _do_capture(self, view):
        """캡쳐 버튼: 썸네일 다중선택→전체화면 multi, 아니면 현재 모드."""
        sel_rows = sorted({self.page_thumbs.list.row(it)
                           for it in self.page_thumbs.list.selectedItems()})
        is_pdf = bool(view.current_file() and str(view.current_file()).lower().endswith(".pdf"))
        if len(sel_rows) >= 2 and is_pdf:
            self._capture_pages(view, sel_rows)       # 다중선택 = 전체화면(모드 무시)
            return
        m = self._cap_mode
        if m == "full":
            if self._cap_copy == "original" and is_pdf:
                self._capture_pages(view, [view.current_page()])
            else:
                self.action_screenshot(view=view)
        elif m == "region":
            self._capture_region(view, None)
        elif m.startswith("user"):
            i = int(m[4:])
            sz = self._cap_sizes[i] if 0 <= i < len(self._cap_sizes) else None
            self._capture_region(view, (sz["w"], sz["h"]) if sz else None)

    def _set_active_pane(self, idx: int):
        if idx not in (0, 1):
            idx = 0
        if not self._split_on:
            idx = 0
        self._active_pane = idx
        dual = self._split_on
        for j, fr in enumerate(self._panes):
            if dual and j == idx:
                fr.setStyleSheet("QFrame#pane%d{border:2px solid #1565c0;}" % j)
            else:
                fr.setStyleSheet("QFrame#pane%d{border:0px;}" % j)
        # 썸네일·단어장 컨텍스트를 활성 창 기준으로 동기화
        try:
            mv = self._mv[idx]
            f = mv.current_file()
            if f and str(f).lower().endswith(".pdf"):
                cur = (str(self.page_thumbs._doc.path)
                       if getattr(self.page_thumbs, "_doc", None) else None)
                if cur != str(f):
                    self.page_thumbs.load_document(f)
                self.page_thumbs.select_page(mv.current_page())
                self._study_pdf = Path(f)
                if self.search_tabs.currentWidget() is self.study_panel:
                    self._refresh_study_panel(mv.current_page())
                self._sync_bookmark_to_active()
                self._refresh_page_hyperlinks(idx)   # 260609-3
                self._push_nav_filter()              # 260609-26
        except Exception:
            pass

    def _toggle_split(self, on: bool):
        on = bool(on)
        self._split_on = on
        self._panes[1].setVisible(on)
        if on:
            w = max(2, self.main_split.width())
            self.main_split.setSizes([w // 2, w // 2])     # 좌/우 동일 폭
            for mv in self._mv:                            # 두 창 '쪽 맞춤' 기본
                try:
                    mv.set_fit_mode(mv.FIT_PAGE)
                except Exception:
                    pass
        else:
            self._active_pane = 0
        self._sync_right_layout()                          # 260606-19: 드로어/컬럼 통합 동기화
        self._set_active_pane(self._active_pane if on else 0)
        self._sync_right_pane_bookmark()                   # 260618-19: 우측 다른폴더 파일 표시 갱신
        self._sync_split_menu_state()                      # 260618-25: 우클릭 1단/2단 라벨

    def _sync_split_menu_state(self):
        """260618-25: 책갈피 트리 우클릭 메뉴의 1단/2단 라벨용 상태 전달."""
        on = bool(getattr(self, "_split_on", False))
        for t in (getattr(self, "bookmark_tree", None),
                  getattr(self, "bookmark_tree_right", None)):
            try:
                if t is not None:
                    t.set_split_state(on)
            except Exception:
                pass

    def _view_as_split(self):
        """260618-26(우클릭 '2단창 보기'): 1단 → 2단. **2창(우측)에 기존 내용이 없을 때만**
        1창(좌측)에서 보던 화면(파일·페이지)과 책갈피를 2창에 복사한다. 우측에 이미 내용이
        있으면(이전 2단 작업분) 그대로 두고 2단으로만 전환한다."""
        if getattr(self, "_split_on", False):
            return
        left = self._mv[0]
        lf = left.current_file()
        lpg = left.current_page() if lf else 0
        self._toggle_split(True)
        try:
            self.act_split.setChecked(True)
        except Exception:
            pass
        right_empty = (self._mv[1].current_file() is None)
        if right_empty:
            # 2창 비어 있음 → 1창의 책갈피·화면을 우측에 복사
            if getattr(self, "_folder", None):
                self._set_pane_folder(1, self._folder)
            self._set_active_pane(1)
            if lf:
                self._load_main(HistoryItem(str(lf), lpg, "", "bookmark"))
        else:
            # 2창에 기존 내용 보존 → 우측 책갈피 갱신 후 우측 활성화
            self._set_active_pane(1)
            self._sync_right_pane_bookmark()
        self._sync_split_menu_state()

    def _view_as_single(self, *_a):
        """260618-26: 2단 → 1단(우측 숨김). 우측 내용을 좌측으로 가져온 뒤 단일 창.
        (현재 우클릭 메뉴에서는 사용 안 함 — 1단 전환은 툴바 2단 토글로. 호환용 유지.)"""
        if not getattr(self, "_split_on", False):
            return
        right = self._mv[1]
        rf = right.current_file()
        rpg = right.current_page() if rf else 0
        folder = getattr(self, "_folder_right", None)
        self._toggle_split(False)
        try:
            self.act_split.setChecked(False)
        except Exception:
            pass
        if rf:
            if folder:
                self._set_pane_folder(0, folder)
            self._set_active_pane(0)
            self._load_main(HistoryItem(str(rf), rpg, "", "bookmark"))
        self._sync_split_menu_state()

    def _copy_pane_to(self, src: int, dst: int):
        """260618-27: 2단에서 src 창의 화면(파일·페이지)과 책갈피(폴더)를 dst 창과 그
        책갈피창(상=1창/하=2창)에 복사. **2단 유지**.
        1창→2창='2창으로 복사', 2창→1창='1창으로 복사'(요청)."""
        if not getattr(self, "_split_on", False):
            return
        if src not in (0, 1) or dst not in (0, 1) or src == dst:
            return
        smv = self._mv[src]
        f = smv.current_file()
        pg = smv.current_page() if f else 0
        folder = self._folder if src == 0 else self._folder_right
        if folder:
            self._set_pane_folder(dst, folder)   # dst 책갈피창(상/하단)=src 폴더
        self._set_active_pane(dst)
        if f:
            self._load_main(HistoryItem(str(f), pg, "", "bookmark"))
        self._sync_split_menu_state()

    def _on_split_view_requested(self, want_dual: bool, from_pane: int = 0):
        """260618-27: 1단 → 2단 진입(책갈피/뷰어 우클릭 '2단 보기')."""
        if want_dual:
            self._view_as_split()

    def _on_copy_pane_requested(self, src: int):
        """260618-27: 책갈피 우클릭 '○창으로 복사' — 상단(src=0)=1창→2창, 하단(src=1)=2창→1창."""
        self._copy_pane_to(src, 1 - src)

    def _on_pane_page_changed(self, i: int, page: int):
        # 260618-29: 본문 읽는 중 그 창의 페이지가 (사용자에 의해) 바뀌면 그 페이지부터 다시 읽기.
        #   읽기 대상 창(_view) 기준으로 판단하므로 활성창 조기반환보다 먼저 처리.
        try:
            ra = self.read_aloud
            if ra.is_active() and getattr(ra, "_view", None) is self._mv[i]:
                ra.on_page_changed(page)
        except Exception:
            pass
        if i != self._active_pane:
            return
        self.page_thumbs.select_page(page)
        self._on_main_page_changed(page)
        self._on_study_page_changed(page)
        self._mv[i].clear_word_highlights()
        self._sync_bookmark_to_active()
        self._refresh_page_hyperlinks(i)          # 260609-3: 페이지 링크 버튼 갱신

    # ===== 260618-22: 2단 = 상단(좌측)·하단(우측) 독립 책갈피 트리 =====
    def _set_pane_folder(self, idx: int, folder):
        """창(0=좌/1=우)의 폴더를 설정하고 해당 책갈피 트리를 로드.
        우측은 좌측과 같은 폴더면 하단을 숨겨(중복 제거) 상단을 공유."""
        folder = Path(folder) if folder else None
        if idx == 0:
            self._folder = folder
            if folder:
                self.bookmark_tree.load_folder(folder)
        else:
            self._folder_right = folder
            if folder:
                self.bookmark_tree_right.load_folder(folder)
        self._sync_right_pane_bookmark()
        self._update_title()

    def _sync_right_pane_bookmark(self):
        """하단(우측) 책갈피 표시/숨김.
        260618-25: 2단 보기에서는 좌/우 폴더가 같아도 **항상 하단 책갈피창을 표시**(요청).
        우측 폴더가 비어 있으면 좌측 폴더로 미러링해 하단이 비지 않게 한다.
        (종전 v2.30.0: '좌측과 다를 때만 표시' → 본 요청으로 대체.)"""
        rt = getattr(self, "bookmark_tree_right", None)
        if rt is None:
            return
        if not getattr(self, "_split_on", False):
            rt.hide()
            return
        lf = getattr(self, "_folder", None)
        rf = getattr(self, "_folder_right", None)
        # 우측 폴더가 없으면 좌측과 동일하게(미러) — 2단이면 하단을 반드시 채움
        if rf is None and lf is not None:
            self._folder_right = lf
            try:
                self.bookmark_tree_right.load_folder(lf)
            except Exception:
                pass
            rf = lf
        if rf is None:
            rt.hide()           # 양쪽 모두 폴더 없음(표시할 책갈피 없음)
            return
        rt.show()
        try:
            sizes = self._bk_split.sizes()
            if len(sizes) == 2 and sizes[1] < 60:
                tot = sum(sizes) or 500
                self._bk_split.setSizes([int(tot * 0.55), int(tot * 0.45)])
        except Exception:
            pass

    def _update_title(self):
        """제목 — 2단이면 '좌측폴더 | 우측폴더'(우측 없으면 좌측만) + 현재 본문 파일명."""
        try:
            lf = getattr(self, "_folder", None)
            left = str(lf) if lf else ""
            if getattr(self, "_split_on", False) and getattr(self, "_folder_right", None) \
                    and (not lf or str(Path(self._folder_right)) != str(Path(lf))):
                base = f"{left}  |  {self._folder_right}"
            else:
                base = left
            parts = [p for p in (base,) if p]
            # 260825: 현재 본문 파일명도 표시(다른 파일 선택 시 제목 갱신)
            try:
                cur = self.main_view.current_file() if self.main_view else None
                if cur and str(cur).lower().endswith(".pdf"):
                    parts.append(Path(cur).name)
            except Exception:
                pass
            title = "  —  ".join(parts)
            self.setWindowTitle(f"PolyPDF  v{__version__}" + (f"  —  {title}" if title else ""))
        except Exception:
            pass

    def _update_right_panel_visibility(self):
        """호환 별칭 → 통합 레이아웃 동기화."""
        self._sync_right_layout()

    def _sync_right_layout(self):
        """260606-19: 우측 패널 배치 통합.
        - 2분할 ON 또는 (검색·스크린샷 모두 숨김) → 슬라이드 드로어(둘 다 보이게, 핸들로 접근).
        - 그 외 → splitter 4단 컬럼. 스크린샷만 보이면 그리드로 확장."""
        try:
            sv = self.act_toggle_search.isChecked()
            shv = self.act_toggle_shot.isChecked()
            use_drawer = self._split_on or (not sv and not shv)
            if use_drawer:
                self.search_tabs.setVisible(True)
                self.shot_strip.setVisible(True)
                self.shot_strip.set_expand(False)
                if not self._panel_in_drawer:
                    self._drawer_lay.addWidget(self.right_panel)
                    self.right_panel.setVisible(True)
                    self._panel_in_drawer = True
                    self._drawer_open = False
                    self._drawer.hide()
                    self._drawer_btn.show()
                    self._position_drawer()
            else:
                if self._panel_in_drawer:
                    self._drawer.hide()
                    self._drawer_btn.hide()
                    self._drawer_open = False
                    self.splitter.insertWidget(3, self.right_panel)
                    self.right_panel.setVisible(True)
                    self._panel_in_drawer = False
                self.search_tabs.setVisible(sv)
                self.shot_strip.setVisible(shv)
                only_shot = shv and not sv
                self.shot_strip.set_expand(only_shot)
                self.right_splitter.setStretchFactor(1, 1 if only_shot else 0)
        except Exception:
            pass
        self._sync_toolbar_search_visibility()

    def _sync_toolbar_search_visibility(self):
        """260628(UI): **검색창(검색 탭)이 보이면 상단 검색박스를 숨긴다** — 같은 기능이
        두 곳에 노출돼 혼동을 준다. 검색창이 숨겨졌을 때만 상단 입력칸을 제공한다.

        드로어 상태(2분할 등)에서는 검색 탭이 '보이는' 위젯이어도 드로어가 접혀 있어
        실제로는 안 보이므로, **드로어에 들어가 있으면 상단 검색박스를 유지**한다."""
        try:
            in_drawer = bool(getattr(self, "_panel_in_drawer", False))
            panel_shows_search = (not in_drawer) and self.act_toggle_search.isChecked()
            show_tb = not panel_shows_search
            for name in ("_tb_search_act", "_tb_search_spacer_act"):
                a = getattr(self, name, None)
                if a is not None:
                    a.setVisible(show_tb)
            if hasattr(self, "toolbar_search"):
                self.toolbar_search.setVisible(show_tb)
        except Exception:
            pass

    def _sync_bookmark_to_active(self):
        """260606-9/260618-23: 활성 창의 책갈피 트리(좌=상단/우=하단)를 그 창 파일·페이지에 맞춰 선택."""
        try:
            idx = self._active_pane
            mv = self._mv[idx]
            f = mv.current_file()
            if f and str(f).lower().endswith(".pdf"):
                tree = self.bookmark_tree if idx == 0 else self.bookmark_tree_right
                tree.select_for_page(f, mv.current_page())
        except Exception:
            pass

    def _on_pane_path_drop(self, idx: int, path: str):
        """260618-23: 뷰어 창에 PDF/폴더 드롭 → 그 창(idx)에 열기.
        폴더면 정렬순 첫 파일의 첫 페이지, 파일이면 그 파일 첫 페이지."""
        from pathlib import Path as _P
        p = _P(path)
        self._set_active_pane(idx if getattr(self, "_split_on", False) else 0)
        tgt = self._active_pane
        if p.is_dir():
            self.open_folder(p, pane=tgt)
            tree = self.bookmark_tree if tgt == 0 else self.bookmark_tree_right
            files = []
            try:
                files = tree.ordered_pdf_files() or tree.all_file_paths() or []
            except Exception:
                files = []
            if files:
                if tgt == 0:
                    self._on_bookmark_activated(str(files[0]), 0)
                else:
                    self._on_bookmark_activated_right(str(files[0]), 0)
        elif p.suffix.lower() == ".pdf":
            self.open_pdf(p)

    def _wire_pane_signals(self, mv, idx: int):
        mv.activated.connect(lambda i=idx: self._set_active_pane(i))
        mv.view.pathDropped.connect(lambda pth, i=idx: self._on_pane_path_drop(i, pth))  # 260618-23
        mv.contextMenuRequested.connect(
            lambda pos, i=idx: (self._set_active_pane(i),
                                self._on_viewer_context_menu(pos)))
        mv.pageChanged.connect(lambda pg, i=idx: self._on_pane_page_changed(i, pg))
        mv.textCopied.connect(                                       # 260616-21 / 260618-1
            lambda n: self.status.showMessage(
                "이 문서는 복사 권한이 없습니다." if n < 0
                else (f"텍스트 복사됨 ({n}자)" if n else "복사할 텍스트가 없습니다."), 3000))
        mv.wordHovered.connect(
            lambda lemma, i=idx: (i == self._active_pane)
            and self._on_main_word_hovered(lemma))
        mv.pageClicked.connect(
            lambda x, y, i=idx: (self.read_aloud.is_active()
                                 and getattr(self.read_aloud, "_view", None) is self._mv[i]
                                 and self.read_aloud.jump_to_point(x, y)))
        mv.matchPositionChanged.connect(
            lambda c, t, i=idx: (i == self._active_pane)
            and self.search_bar.set_match_position(c, t))
        mv.imageStepRequested.connect(
            lambda step, i=idx: (i == self._active_pane) and self._on_image_step(step))
        mv.imageGotoRequested.connect(
            lambda p, i=idx: (i == self._active_pane) and self._on_image_goto(p))
        mv.fileBoundaryRequested.connect(
            lambda d, i=idx: self._on_file_boundary(d, i))
        mv.hyperlinkActivated.connect(
            lambda link, i=idx: (i == self._active_pane) and self._launch_hyperlink(link))
        mv.drawModeChanged.connect(self._on_main_draw_mode_changed)   # 260611-4: 공유 동기

    def _build_search_area(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(4)
        self.search_bar = SearchBar()
        v.addWidget(self.search_bar)
        self.search_results = SearchResults()
        v.addWidget(self.search_results, 1)
        return wrap

    def _build_right_panel(self) -> QWidget:
        """v1.6.2: 우측 패널 = 검색 영역(상) + 스크린샷 스트립(하) 세로 분할."""
        # M7: 스크린샷 패널 헤더에 저장 버튼 (화면캡쳐 버튼은 260606-8: 각 메인뷰 툴바로)
        self.btn_save_pdf = QPushButton("💾 PDF 저장")
        self.btn_save_pdf.setToolTip("스크린샷 전체를 PDF로 (Ctrl+S)")
        self.btn_save_pdf.clicked.connect(self.action_save_screenshot_pdf)
        # 260606-17: 클립보드 저장(전체 스크린샷을 순서대로 클립보드 히스토리에)
        self.btn_clip = QPushButton(" 클립보드 저장")
        _cico = resource_path("icon_clipboard.png")
        if _cico:
            self.btn_clip.setIcon(QIcon(_cico))
        else:
            self.btn_clip.setText("📋 클립보드 저장")
        self.btn_clip.setToolTip("저장 후 'Win+v'로 여러 목록을 붙여넣으세요")
        self.btn_clip.clicked.connect(self._on_clipboard_save)

        self.shot_strip = MiniStrip(
            "🖼 스크린샷", max_items=int(self._prefs.get("screenshot_max", 30)),
            draggable=True,
            extra_widgets=[self.btn_clip, self.btn_save_pdf],
        )

        self.search_area = self._build_search_area()

        # 단어장 패널을 검색결과와 '탭'으로 합류 (계획 §10-5: 가로 4단 유지 — splitter 자식 수 불변)
        self.study_panel = StudyPanel()
        self.search_tabs = QTabWidget()
        self.search_tabs.setDocumentMode(True)     # 260606-7: 탭 프레임/여백 축소
        self.search_tabs.addTab(self.search_area, "🔎 검색")
        self.search_tabs.addTab(self.study_panel, "📖 단어장")

        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setHandleWidth(2)      # 260606-7: 분할 손잡이 폭 축소
        self.right_splitter.addWidget(self.search_tabs)
        self.right_splitter.addWidget(self.shot_strip)
        self.right_splitter.setSizes([700, 200])   # 260606-6: 스크린샷은 콘텐츠 높이에 맞춤
        self.right_splitter.setCollapsible(0, True)
        self.right_splitter.setCollapsible(1, True)
        # 검색 영역이 늘어나도록 (스크린샷은 자체 높이 유지)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 0)
        return self.right_splitter

    def _build_toolbar(self):
        """260606-25: 패널 툴바 = [뷰어모드] 1단/2단/검색/단어장/스크린샷
        + (띄움) + [기능] PDF병합/책갈피·단어장 동시/책갈피 생성/단어장 생성/스크린샷 PDF 저장.
        내부 상태 토글(act_toggle_search/shot)은 유지하되 툴바엔 노출하지 않음."""
        from PyQt6.QtWidgets import QToolButton, QLabel, QSizePolicy, QLineEdit
        self._panel_toolbar = QToolBar("패널", self)
        self._panel_toolbar.setMovable(False)
        self.addToolBar(self._panel_toolbar)
        self._panel_btns = []     # 260606-26: 테마 스타일 재적용 대상

        # 내부 가시성 상태(설정 메뉴·_sync_right_layout 가 사용; 툴바엔 미노출)
        self.act_toggle_search = QAction("🔎 검색·단어", self)
        self.act_toggle_search.setCheckable(True)
        self.act_toggle_search.setChecked(True)
        self.act_toggle_search.toggled.connect(
            lambda _=False: self._sync_right_layout())
        self.act_toggle_shot = QAction("🖼 스크린샷", self)
        self.act_toggle_shot.setCheckable(True)
        self.act_toggle_shot.setChecked(True)
        self.act_toggle_shot.toggled.connect(
            lambda _=False: self._sync_right_layout())

        def mk(text, tip, slot):
            b = QToolButton(self)
            b.setText(text)
            b.setProperty("panelBtn", True)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _=False, s=slot: s())
            # 260628(FIX): ★ QToolBar 에 넣은 위젯은 **`addWidget()` 가 돌려주는 QAction**
            #   으로만 숨길 수 있다. 위젯에 직접 `setVisible(False)` 를 해도 툴바가 액션
            #   가시성에 맞춰 다시 보여준다 → 키 미입력 시 버튼을 숨기려던 게이팅이
            #   전혀 동작하지 않았다. 액션을 위젯에 달아 두고 게이팅에서 사용한다.
            act = self._panel_toolbar.addWidget(b)
            b._tb_action = act
            self._panel_btns.append(b)
            return b

        def lab(txt):
            q = QLabel(txt)
            q.setObjectName("panelGroupLabel")
            q.setStyleSheet("color:#888;font-weight:bold;padding:0 4px;"
                            "background:transparent;border:none;")
            self._panel_toolbar.addWidget(q)

        # 260606-27: 좌측 정렬 / 260618-18: '뷰어'→'보기', '기능'→'도구', 법령/고시 보기 그룹으로
        lab("보기")
        mk("1단", "검색·단어장·스크린샷 숨김 (단일 보기)", self._vm_single)
        mk("2단", "2단 보기(쪽 맞춤)", self._vm_split)
        mk("검색", "검색·단어장 창 보이기 · 검색 탭", self._vm_search)
        mk("단어장", "검색·단어장 창 보이기 · 단어장 탭", self._vm_study)
        self._btn_shot = mk("스크린샷", "검색·단어장 숨김 · 스크린샷 보이기", self._vm_shot)
        self._btn_law = mk("법령/고시", "법제처 법령·고시 검색·본문 보기", self._action_law_search)  # 260618-18
        self._btn_kcsc = mk("건설기준", "국가건설기준센터(KCSC) KDS·KCS 본문 보기", self._action_kcsc_search)  # 260618-37
        self._btn_kipo = mk("특허", "특허청(KIPO) 특허 등록정보 조회", self._action_kipo_search)  # 260618-43
        mk("발표보기", "발표 전체화면 보기 (F5)", self._open_presentation)  # 260609-15(E1)/260618-8
        # 보기 ↔ 도구 사이 띄움
        _sp = QWidget(); _sp.setFixedWidth(20)
        self._panel_toolbar.addWidget(_sp)
        lab("도구")
        self._btn_merge = mk("PDF병합", "파일 → PDF 병합", lambda: self._on_merge_files(None))
        self._btn_img2pdf = mk("이미지→PDF", "이미지 파일 → PDF 변환",
                               lambda: self.action_image_to_pdf())  # 260825-13
        self._btn_tr = mk("번역", "PDF 번역 (목록 창)", lambda: self._action_translate_files())  # 260623
        mk("책갈피 생성", "파일 → 책갈피 자동 생성", self.action_open_bookmarker)
        mk("단어장 생성", "파일 → 단어장 생성", self._action_build_study)
        mk("암호화", "현재 PDF에 암호·권한 설정(암호화 저장)", self.action_encrypt_pdf)
        self._btn_shot_pdf = mk("스크린샷 PDF 저장", "스크린샷 전체를 PDF로", self.action_save_screenshot_pdf)

        # 260616-3: 패널 툴바 오른쪽 끝에 검색 입력창(돋보기 + '검색').
        #   Enter 시 검색 실행 + 검색창(검색 탭)이 숨겨져 있으면 보이게 함.
        _rsp = QWidget()
        _rsp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # 260628(UI): 검색 탭이 보이면 상단 검색박스를 숨긴다(같은 기능 중복 노출 방지).
        #   ★ 툴바 위젯은 `addWidget()` 반환 QAction 으로만 숨겨진다(SOT §11.12) →
        #     스페이서·입력칸의 액션을 모두 보관해 함께 껐다 켠다.
        self._tb_search_spacer_act = self._panel_toolbar.addWidget(_rsp)
        self.toolbar_search = QLineEdit()
        self.toolbar_search.setPlaceholderText("검색")
        self.toolbar_search.setClearButtonEnabled(True)
        self.toolbar_search.setFixedWidth(220)
        self.toolbar_search.setObjectName("toolbarSearch")
        from viewer.widgets.icons import themed_icon as _themed_icon
        self._search_lead_action = self.toolbar_search.addAction(
            _themed_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.toolbar_search.returnPressed.connect(self._on_toolbar_search)
        self._tb_search_act = self._panel_toolbar.addWidget(self.toolbar_search)

        from viewer import theme as _theme
        self._style_panel_toolbar(_theme.is_dark())
        self._panel_toolbar.setVisible(True)    # 260606-25: 패널 초기 보이기

    def _style_panel_toolbar(self, dark: bool):
        """260606-26: 패널 버튼 테두리/배경을 테마별로. 라이트=짙은 회색,
        다크=배경보다 옅은 회색. 너무 튀지 않게 은은한 대비."""
        if dark:
            css = (
                "QToolButton{background:#484848;border:1px solid #606060;"
                "border-radius:3px;padding:2px 8px;margin:1px;color:#e8e8e8;}"
                "QToolButton:hover{background:#555555;border-color:#707070;}"
                "QToolButton:pressed{background:#3c3c3c;}")
        else:
            css = (
                "QToolButton{background:#e2e2e2;border:1px solid #a8a8a8;"
                "border-radius:3px;padding:2px 8px;margin:1px;color:#222;}"
                "QToolButton:hover{background:#d4d4d4;border-color:#909090;}"
                "QToolButton:pressed{background:#c4c4c4;}")
        try:
            for b in getattr(self, "_panel_btns", []):
                b.setStyleSheet(css)
        except Exception:
            pass
        # 260616-3: 오른쪽 끝 검색창 테마 스타일(둥근 모서리)
        try:
            ts = getattr(self, "toolbar_search", None)
            if ts is not None:
                if dark:
                    ts.setStyleSheet(
                        "QLineEdit#toolbarSearch{background:#3a3a3d;color:#e8e8e8;"
                        "border:1px solid #5a5a5a;border-radius:13px;padding:3px 10px;}"
                        "QLineEdit#toolbarSearch:focus{border-color:#7a7a7a;}")
                else:
                    ts.setStyleSheet(
                        "QLineEdit#toolbarSearch{background:#ffffff;color:#222;"
                        "border:1px solid #b8b8b8;border-radius:13px;padding:3px 10px;}"
                        "QLineEdit#toolbarSearch:focus{border-color:#909090;}")
                from viewer.widgets.icons import themed_icon as _themed_icon
                self._search_lead_action.setIcon(_themed_icon("search", dark=dark))
        except Exception:
            pass

    def _on_toolbar_search(self):
        """260616-3: 툴바 검색창 Enter — 검색 실행.
        260708: 우측창(건설기준/법령/특허) 열려 있으면 왼쪽 검색패널을 띄우지 않고
        슬라이드 오버레이로만 그 본문을 검색."""
        text = self.toolbar_search.text().strip()
        if not text:
            return
        if self._content_panel is not None:
            self._open_content_find(text)
            return
        self._vm_search()                    # 검색 탭/패널을 보이게 함
        try:
            self.search_bar.edit.setText(text)   # 상단 검색바와 동기화
        except Exception:
            pass
        self.action_search(text)

    # ===== 260606-25: 뷰어 모드 프리셋 =====================================
    def _vm_single(self):
        if self.act_split.isChecked():
            self.act_split.setChecked(False)
        self.act_toggle_search.setChecked(False)
        self.act_toggle_shot.setChecked(False)
        self._sync_right_layout()

    def _vm_split(self):
        self.act_split.setChecked(True)

    def _vm_search(self):
        if self.act_split.isChecked():
            self.act_split.setChecked(False)
        self.act_toggle_search.setChecked(True)
        self.search_tabs.setCurrentWidget(self.search_area)
        self._sync_right_layout()

    def _vm_study(self):
        if self.act_split.isChecked():
            self.act_split.setChecked(False)
        self.act_toggle_search.setChecked(True)
        self.search_tabs.setCurrentWidget(self.study_panel)
        self._sync_right_layout()

    def _vm_shot(self):
        if self.act_split.isChecked():
            self.act_split.setChecked(False)
        self.act_toggle_search.setChecked(False)
        self.act_toggle_shot.setChecked(True)
        self._sync_right_layout()

    def _build_menus(self):
        bar = self.menuBar()
        m_file = bar.addMenu("파일(&F)")
        a_open = self._sc_act_open = QAction("폴더 열기...", self)
        a_open.triggered.connect(self.action_open_folder)
        m_file.addAction(a_open)

        # v1.6.11 I1: 단일 PDF 열기
        a_open_file = self._sc_act_open_file = QAction("파일 열기...", self)
        a_open_file.triggered.connect(self.action_open_pdf)
        m_file.addAction(a_open_file)

        # 260603-3: 인쇄
        a_print = self._sc_act_print = QAction("인쇄...", self)
        a_print.triggered.connect(self.action_print)
        m_file.addAction(a_print)

        # 260603: 최근 폴더를 '책갈피 자동 생성' 위로 이동
        m_file.addSeparator()
        self.menu_recent = QMenu("최근 폴더", self)
        m_file.addMenu(self.menu_recent)

        # 260618-8: (구 '파일' 메뉴의 도구 항목들은 '도구' 메뉴 상부로 이동 — 아래 _build_tools_menu)
        m_file.addSeparator()
        a_quit = self._sc_act_quit = QAction("종료", self)
        a_quit.triggered.connect(self.close)
        m_file.addAction(a_quit)

        # v1.6.1 F1: 즐겨찾기 메뉴 (파일 ↔ 보기 사이)
        self.menu_favorites = bar.addMenu("즐겨찾기(&V)")
        self._refresh_favorites_menu()

        # 260618-8: 보기 메뉴 — 패널 '뷰어' 버튼(1단/2단/검색/단어장/스크린샷/법령·고시/발표보기)과 동일 동작
        m_view = bar.addMenu("보기(&B)")
        for _label, _slot in (
                ("1단", self._vm_single), ("2단", self._vm_split),
                ("검색", self._vm_search), ("단어장", self._vm_study),
                ("스크린샷", self._vm_shot),
                ("법령/고시", self._action_law_search),
                ("건설기준(KCSC)", self._action_kcsc_search),
                ("특허(등록정보)", self._action_kipo_search),
                ("발표보기", self._open_presentation)):
            _a = QAction(_label, self)
            _a.triggered.connect(lambda _checked=False, s=_slot: s())
            m_view.addAction(_a)
            # 260621-P3: API 키 게이팅용 — 보기 메뉴의 외부 API 항목 저장
            if not hasattr(self, "_view_acts"):
                self._view_acts = {}
            self._view_acts[_label] = _a

        # 260825: 뷰어 옵션(우클릭) 메뉴를 단축키로 — 보기 메뉴에 노출(단축키 표시) + 설정 등록
        m_view.addSeparator()
        self._sc_act_option_menu = QAction("옵션 메뉴 (현재 페이지)", self)
        self._sc_act_option_menu.triggered.connect(self._show_viewer_option_menu)
        m_view.addAction(self._sc_act_option_menu)

        # 260606-8: 2분할 보기 상태 act (메뉴엔 표시 안 함 — 보기 메뉴/툴바로 제어, 상태 동기화용)
        self.act_split = QAction("🗗 2단 보기", self)
        self.act_split.setCheckable(True)
        self.act_split.setChecked(False)
        self.act_split.toggled.connect(self._toggle_split)
        # 260609-4 (D): 발표 보기 (F5) — 메뉴엔 '보기'로, 단축키 유지 위해 창에 등록
        self.act_present = QAction("📽 발표 보기", self)
        self.act_present.setShortcut("F5")
        self.act_present.triggered.connect(self._open_presentation)
        self.addAction(self.act_present)           # 메뉴에 없어도 F5 동작 유지

        # 260618-16: '도구' 메뉴 — 기능별 6개 구역으로 재배열(섹션 헤더 + 항목)
        m_tools = bar.addMenu("도구(&T)")

        def _act(text, slot):
            a = QAction(text, self)
            a.triggered.connect(slot)
            m_tools.addAction(a)
            return a

        # 📄 PDF 및 문서 작업
        m_tools.addSection("📄 PDF 및 문서 작업")
        a_merge = self._sc_act_merge = _act("PDF 병합...", lambda: self._on_merge_files(None))
        _act("이미지 → PDF 변환...", lambda: self.action_image_to_pdf())  # 260825-13
        _act("PDF 꾸밈 저장 (선·도형·글·하이퍼링크)...", self._action_save_decorated_pdf)

        # 🔖 책갈피 및 단어장 생성
        m_tools.addSection("🔖 책갈피 및 단어장 생성")
        _act("단어장·책갈피 동시 생성...", self._action_build_study_and_bookmarks)
        _act("책갈피 자동 생성...", self.action_open_bookmarker)
        _act("단어장 생성 (OCR·어휘)...", self._action_build_study)

        # 📖 사전 및 용어집 관리
        m_tools.addSection("📖 사전 및 용어집 관리")
        _act("단어장 관리 (출처·우선순위·폴더)...", self._action_dict_manager)
        _act("용어집 가져오기 (PDF·CSV)...", self._action_import_glossary)
        _act("사전 복원 (가져오기)...", self._action_restore_dict)
        _act("용어집 CSV 양식 예제 저장...", self._action_save_csv_sample)
        _act("인터넷 사전 보강 (이어하기)...", self._action_online_enrich)
        _act("사전 내보내기 (TBX·CSV)...", self._action_export_dict)
        _act("사전 백업 (내보내기)...", self._action_backup_dict)
        _act("사전 정리 (HTML 마크업 제거)", self._action_sanitize_dict)
        _act("온용어 다시 분류 (용어집별·재조회)...", self._action_reclassify_onterm)

        # 🌐 번역 (Claude)
        m_tools.addSection("🌐 번역 (Claude)")
        self._act_tr_files = _act("PDF번역", self._action_translate_files)

        # 🔍 검색 및 데이터 구축
        m_tools.addSection("🔍 검색 및 데이터 구축")
        self._act_law = _act("법령·고시 검색 (법제처)...", self._action_law_search)
        self._act_kcsc = _act("건설기준 (KCSC) 보기...", self._action_kcsc_search)
        self._act_kipo = _act("특허 등록정보 (KIPO)...", self._action_kipo_search)
        _act("인덱스 재구축", self.action_reindex)

        # 🏷️ 태그·키워드 (260829 P2 — 태그 SOT §8.2·§8.5)
        m_tools.addSection("🏷️ 태그 자동 부여")
        _act("태그 다시 계산", lambda: self._start_autotag_scan(force=True))
        _act("새 태그 후보 검토…", self._autotag_review_candidates)
        _act("직전 자동 부여 되돌리기", self._autotag_undo)
        _act("자동 태그 전체 삭제", self._autotag_clear_all)
        _act("없는 파일 항목 정리…", self._autotag_prune_missing)

        # ⚙️ 프로그램 환경설정
        m_tools.addSection("⚙️ 프로그램 환경설정")
        _act("환경설정...", self.action_open_settings)        # 260618-18: 환경설정을 단축키 위로
        _act("단축키 설정...", self._edit_shortcuts)
        _act("현재 설정을 기본값으로 저장(배포용)…", self._save_current_as_default)
        _act("설정 초기화(기본값으로 되돌리기)…", self._reset_to_defaults)

        # 💻 시스템 연동 및 설치
        m_tools.addSection("💻 시스템 연동 및 설치")
        _act("Windows 기본 PDF 앱으로 등록…", self._register_pdf_handler)
        _act("구성요소 설치(녹화·OCR)…", self._open_components_installer)

        m_help = bar.addMenu("도움말(&H)")
        # v1.6.1 G2: 사용법
        a_usage = QAction("사용법", self)
        a_usage.triggered.connect(self._show_usage)
        m_help.addAction(a_usage)
        # 260618-11: 업데이트 확인(GitHub Releases)
        a_update = QAction("업데이트 확인…", self)
        a_update.triggered.connect(lambda: self._check_for_updates(manual=True))
        m_help.addAction(a_update)
        # 260618-24(C): 업데이트 자동 다운로드(미리 받아두기) 체크박스 — 기본 켜짐
        a_autodl = QAction("업데이트 자동 다운로드", self)
        a_autodl.setCheckable(True)
        a_autodl.setChecked(bool(getattr(self, "_prefs", {}).get("auto_download_update", True)))
        a_autodl.toggled.connect(self._on_toggle_auto_download)
        m_help.addAction(a_autodl)
        self._act_auto_download = a_autodl
        # 260618-33: 베타(테스트) 업데이트 채널 — 켜면 -beta/-rc 등 프리릴리즈도 받음(기본 꺼짐=정식만)
        a_beta = QAction("베타(테스트) 버전도 받기", self)
        a_beta.setCheckable(True)
        # 260618-36: 1.0 이전(pre-stable)에는 빌드가 베타로만 나오므로 항상 베타 수신 → 체크·잠금.
        _pre10 = False
        try:
            from viewer import updater as _u0
            _pre10 = int((_u0.current_version().lstrip("vV").split(".")[0]) or "0") == 0
        except Exception:
            pass
        a_beta.setChecked(_pre10 or str(getattr(self, "_prefs", {}).get("update_channel", "stable")).lower() == "beta")
        if _pre10:
            a_beta.setEnabled(False)
            a_beta.setToolTip("1.0 이전에는 항상 베타(테스트) 버전을 받습니다.")
        a_beta.toggled.connect(self._on_toggle_update_channel)
        m_help.addAction(a_beta)
        self._act_update_beta = a_beta
        m_help.addSeparator()
        a_about = QAction("정보", self)
        a_about.triggered.connect(self._show_about)
        m_help.addAction(a_about)

        self._setup_shortcuts()

    # ===== 260606-19 / 260611-3: 단축키(그룹화) 설정·수정·복원 ============
    def _setup_shortcuts(self):
        from collections import OrderedDict
        # id → (라벨, 기본키, 그룹). 260611-3: 그룹화 + 선긋기/발표 단축키 신설·통일.
        self._sc_defs = OrderedDict([
            ("open_folder",   ("폴더 열기", "Ctrl+O", "파일")),
            ("open_file",     ("파일 열기", "Ctrl+Shift+O", "파일")),
            ("print",         ("인쇄", "Ctrl+P", "파일")),
            ("merge",         ("PDF 병합", "Ctrl+M", "파일")),
            ("search_focus",  ("검색바 포커스", "Ctrl+F", "탐색")),
            ("next_match",    ("다음 매치", "F3", "탐색")),
            ("prev_match",    ("이전 매치", "Shift+F3", "탐색")),
            ("option_menu",   ("옵션 메뉴(우클릭)", "Shift+F10", "탐색")),
            ("toggle_split",  ("2단 보기", "Ctrl+Shift+2", "보기")),
            ("present",       ("발표보기", "F5", "보기")),
            ("capture",       ("화면 캡처", "Ctrl+Shift+S", "캡처·저장")),
            ("save_shots_pdf", ("스크린샷 PDF 저장", "Ctrl+S", "캡처·저장")),
            ("clipboard_save", ("클립보드 저장", "Ctrl+Shift+C", "캡처·저장")),
            ("draw_pen_1",    ("선 1 선택", "Ctrl+1", "선긋기(편집모드)")),
            ("draw_pen_2",    ("선 2 선택", "Ctrl+2", "선긋기(편집모드)")),
            ("draw_pen_3",    ("선 3 선택", "Ctrl+3", "선긋기(편집모드)")),
            ("draw_pen_4",    ("선 4 선택", "Ctrl+4", "선긋기(편집모드)")),
            ("draw_pen_5",    ("선 5 선택", "Ctrl+5", "선긋기(편집모드)")),
            ("draw_mode",     ("선 종류 전환(직선/하이라이트/자유)", "Ctrl+`", "선긋기(편집모드)")),
            ("draw_erase_thin",  ("지우개(얇게)", "Ctrl+E", "선긋기(편집모드)")),
            ("draw_erase_thick", ("지우개(두껍게)", "Ctrl+Shift+E", "선긋기(편집모드)")),
            ("draw_clear",    ("현재 페이지 선 청소", "Ctrl+Shift+Backspace", "선긋기(편집모드)")),
            ("quit",          ("종료", "Ctrl+Q", "기타")),
        ])
        targets = {
            "open_folder": ("action", self._sc_act_open),
            "open_file": ("action", self._sc_act_open_file),
            "print": ("action", self._sc_act_print),
            "merge": ("action", self._sc_act_merge),
            "quit": ("action", self._sc_act_quit),
            "present": ("action", self.act_present),
            "search_focus": ("func", self._focus_search),
            "next_match": ("func", self._global_next_match),
            "prev_match": ("func", self._global_prev_match),
            "option_menu": ("action", self._sc_act_option_menu),
            "capture": ("func", lambda: self._do_capture(self.main_view)),
            "save_shots_pdf": ("func", self.action_save_screenshot_pdf),
            "clipboard_save": ("func", self._on_clipboard_save),
            "toggle_split": ("func", lambda: self.act_split.toggle()),
            "draw_pen_1": ("func", lambda: self._draw_sc_pen(0)),
            "draw_pen_2": ("func", lambda: self._draw_sc_pen(1)),
            "draw_pen_3": ("func", lambda: self._draw_sc_pen(2)),
            "draw_pen_4": ("func", lambda: self._draw_sc_pen(3)),
            "draw_pen_5": ("func", lambda: self._draw_sc_pen(4)),
            "draw_mode": ("func", self._draw_sc_mode),
            "draw_erase_thin": ("func", lambda: self._draw_sc_erase(0)),
            "draw_erase_thick": ("func", lambda: self._draw_sc_erase(1)),
            "draw_clear": ("func", self._draw_sc_clear),
        }
        self._sc_objs = {}
        overrides = (getattr(self, "_prefs", {}) or {}).get("shortcuts", {})
        for sid, (label, default, group) in self._sc_defs.items():
            seq = QKeySequence(overrides.get(sid, default))
            kind, ref = targets[sid]
            if kind == "action":
                ref.setShortcut(seq)
                self._sc_objs[sid] = ("action", ref)
            else:
                sh = QShortcut(seq, self)
                sh.activated.connect(ref)
                self._sc_objs[sid] = ("shortcut", sh)

    # 260611-3: 선긋기 단축키 — 편집모드의 활성 메인뷰에 적용
    def _draw_sc_pen(self, idx):
        if self._in_edit():
            mv = self.main_view
            if mv:
                mv._on_draw_pen(idx)

    def _draw_sc_mode(self):
        if self._in_edit() and self.main_view:
            self.main_view._cycle_draw_mode()

    def _draw_sc_erase(self, k):
        if self._in_edit() and self.main_view:
            self.main_view._on_draw_erase(k)

    def _draw_sc_clear(self):
        if self._in_edit() and self.main_view:
            self.main_view.clear_page_drawings()

    def _apply_shortcuts(self, overrides: dict):
        for sid, (label, default, group) in self._sc_defs.items():
            ks = QKeySequence(overrides.get(sid, default))
            kind, obj = self._sc_objs.get(sid, (None, None))
            if kind == "action":
                obj.setShortcut(ks)
            elif kind == "shortcut":
                obj.setKey(ks)

    def _draw_pen_keys(self):
        """260611-3: 발표창에 넘길 펜1~5 단축키(본문과 동일 키 공유)."""
        ov = (self._prefs or {}).get("shortcuts", {})
        out = []
        for i in range(5):
            sid = f"draw_pen_{i+1}"
            d = self._sc_defs.get(sid)
            out.append(ov.get(sid, d[1] if d else ""))
        return out

    def _edit_shortcuts(self):
        from viewer.widgets.shortcuts_dialog import ShortcutsDialog
        cur = (self._prefs or {}).get("shortcuts", {})
        d = ShortcutsDialog(self._sc_defs, cur, self,
                            capture_global=bool(self._prefs.get("capture_global", False)))
        if d.exec():
            self._prefs["shortcuts"] = d.result_shortcuts()
            self._prefs["capture_global"] = bool(d.result_capture_global())
            self._apply_shortcuts(self._prefs["shortcuts"])
            try:
                self._refresh_global_capture_hotkey(notify=True)  # 260611-3(6): 전역 핫키 갱신+알림
            except Exception:
                pass
            try:
                self._save_settings_now()
            except Exception:
                pass
            self.status.showMessage("단축키 저장됨", 3000)

    # ===== 260611-11: Windows 기본 PDF 앱 등록(연결 프로그램) ============
    def _register_pdf_handler(self):
        """HKCU 에 ProgID·연결 프로그램 등록 → PDF '다른 앱으로 열기' 목록에 PolyPDF.
        (Windows 보안상 '기본 앱' 최종 지정은 사용자 확인 필요 — 안내 표시.)"""
        import sys as _sys, os as _os
        if not getattr(_sys, "frozen", False):
            QMessageBox.information(
                self, "안내",
                "개발 실행(파이썬)에서는 등록할 수 없습니다.\n"
                "빌드된 PolyPDF.exe 에서 실행해 주세요.")
            return
        exe = _os.path.abspath(_sys.executable)
        try:
            import winreg
            prog = "PolyPDF.pdf"
            def setk(path, name, val, typ=winreg.REG_SZ):
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
                    winreg.SetValueEx(k, name, 0, typ, val)
            setk(rf"Software\Classes\{prog}", "", "PDF 문서 (PolyPDF)")
            setk(rf"Software\Classes\{prog}\DefaultIcon", "", f'"{exe}",0')
            setk(rf"Software\Classes\{prog}\shell\open\command", "", f'"{exe}" "%1"')
            setk(r"Software\Classes\.pdf\OpenWithProgids", prog, b"", winreg.REG_NONE)
            base = _os.path.basename(exe)
            setk(rf"Software\Classes\Applications\{base}\shell\open\command",
                 "", f'"{exe}" "%1"')
            setk(rf"Software\Classes\Applications\{base}", "FriendlyAppName", "PolyPDF")
            QMessageBox.information(
                self, "등록 완료",
                "PolyPDF 를 PDF '연결 프로그램' 목록에 등록했습니다.\n\n"
                "■ 기본 앱으로 지정하려면(둘 중 하나):\n"
                "  1) PDF 파일 우클릭 → '연결 프로그램' → '다른 앱 선택' → PolyPDF → '항상'\n"
                "  2) Windows 설정 → 앱 → 기본 앱 → '.pdf' 에서 PolyPDF 선택\n\n"
                "※ Windows 보안 정책상 기본 앱의 최종 지정은 사용자가 직접 확인해야 합니다.")
        except Exception as e:
            QMessageBox.warning(self, "등록 실패", str(e))

    # ===== 260611-3(6): 화면 캡처 전역 단축키 ============================
    def _capture_key(self) -> str:
        ov = (self._prefs or {}).get("shortcuts", {})
        d = self._sc_defs.get("capture")
        return ov.get("capture", d[1] if d else "Ctrl+Shift+S")

    def _setup_global_capture(self):
        if getattr(self, "_global_hotkey", None) is not None:
            return
        try:
            from viewer.global_hotkey import GlobalHotkey
            self._global_hotkey = GlobalHotkey(int(self.winId()), 0xB001,
                                               self._on_global_capture)
            QApplication.instance().installNativeEventFilter(self._global_hotkey)
        except Exception:
            self._global_hotkey = None

    def _refresh_global_capture_hotkey(self, notify: bool = False):
        """capture_global 토글/키 변경 시 전역 핫키 등록·해제 + 인앱 단축키 중복 방지.
        notify=True 면 등록 성공/실패를 상태바·메시지로 알림(설정 변경 직후)."""
        self._setup_global_capture()
        hk = getattr(self, "_global_hotkey", None)
        kind, obj = self._sc_objs.get("capture", (None, None))
        if self._prefs.get("capture_global") and hk is not None:
            ok = hk.register(self._capture_key())
            if ok and kind == "shortcut":
                obj.setKey(QKeySequence())          # 인앱 단축키 비활성(전역 핸들러가 전담)
            if not ok and kind == "shortcut":
                obj.setKey(QKeySequence(self._capture_key()))   # 실패 시 인앱은 유지
            if notify:
                key = self._capture_key()
                if ok:
                    self.status.showMessage(
                        f"전역 화면캡처 단축키 등록됨: {key} (다른 프로그램 위에서도 작동)", 5000)
                else:
                    QMessageBox.warning(
                        self, "전역 단축키 등록 실패",
                        f"'{key}' 를 전역 단축키로 등록하지 못했습니다.\n"
                        "다른 프로그램이 같은 조합을 이미 사용 중일 수 있습니다.\n"
                        "단축키 설정에서 '화면 캡처' 키를 다른 조합으로 바꿔 다시 시도하세요.")
        else:
            if hk is not None:
                hk.unregister()
            if kind == "shortcut":
                obj.setKey(QKeySequence(self._capture_key()))
            if notify:
                self.status.showMessage("전역 화면캡처 단축키 해제됨(앱 활성 시에만 작동)", 4000)

    def _foreground_is_self(self) -> bool:
        try:
            import ctypes
            fg = int(ctypes.windll.user32.GetForegroundWindow())
            return fg in (int(self.winId()), int(self.window().winId()))
        except Exception:
            return False

    def _cursor_in_viewer(self) -> bool:
        try:
            from PyQt6.QtGui import QCursor
            p = QCursor.pos()
            for mv in self._mv:
                vp = mv.view.viewport()
                if not vp.isVisible():
                    continue
                tl = vp.mapToGlobal(vp.rect().topLeft())
                br = vp.mapToGlobal(vp.rect().bottomRight())
                if tl.x() <= p.x() <= br.x() and tl.y() <= p.y() <= br.y():
                    return True
            return False
        except Exception:
            return False

    def _on_global_capture(self):
        """전역 핫키 발화 — 본 프로그램이 활성+커서가 뷰어 내부면 기존 방식,
        아니면 보이는 화면을 전역 캡처해 스크린샷 목록에 저장(설정 무시)."""
        # 260611-13: 한 번의 키 입력이 (드물게) 중복 처리돼 2장 저장되던 문제 → 250ms 디바운스
        try:
            from PyQt6.QtCore import QDateTime
            now = QDateTime.currentMSecsSinceEpoch()
            if now - getattr(self, "_last_gcap_ms", 0) < 250:
                return
            self._last_gcap_ms = now
        except Exception:
            pass
        try:
            if self._foreground_is_self() and self._cursor_in_viewer():
                self._do_capture(self.main_view)
                return
            # 260611-14: 전역 캡처도 PolyPDF 의 '캡처 모드'(전체/지정/사용자크기)를 반영.
            #   화면 전체 위에서 동작(RegionCaptureOverlay 는 화면을 잡아 선택/고정 박스 지원).
            #   크기는 항상 보이는 크기로 저장.
            pm = None
            mode = getattr(self, "_cap_mode", "full")
            copy = getattr(self, "_cap_copy", "visible")   # 260611-15: 기존 화질 선택도 반영
            if mode == "region":
                from viewer.widgets.region_capture import RegionCaptureOverlay
                pm = RegionCaptureOverlay(mode="region", copy_mode=copy,
                                          parent=self).grab()
            elif isinstance(mode, str) and mode.startswith("user"):
                from viewer.widgets.region_capture import RegionCaptureOverlay
                try:
                    i = int(mode[4:]); sz = self._cap_sizes[i]
                    fixed = (int(sz["w"]), int(sz["h"]))
                except Exception:
                    fixed = None
                pm = RegionCaptureOverlay(mode="fixed", fixed_size=fixed,
                                          copy_mode=copy, parent=self).grab()
            else:   # full — 보이는 화면 전체
                from PyQt6.QtGui import QCursor, QGuiApplication
                scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
                if scr is not None:
                    pm = scr.grabWindow(0)
            if pm is None or pm.isNull():
                return
            try:
                QApplication.clipboard().setPixmap(pm)
            except Exception:
                pass
            saved = ss.save_screenshot(pm, source_name="화면캡처.png")
            self.shot_strip.add_item(str(saved), kind="image",
                                     label=Path(saved).stem, prepend=False)
            try:
                self._ensure_shots_visible()
            except Exception:
                pass
            self.status.showMessage(f"전역 캡처 저장({mode}): {Path(saved).name}", 3000)
        except Exception:
            pass

    def _wire_signals(self):
        self.bookmark_tree.bookmarkActivated.connect(self._on_bookmark_activated)
        # 260618-22: 하단(우측) 책갈피 → 우측 창에 열기
        self.bookmark_tree_right.bookmarkActivated.connect(self._on_bookmark_activated_right)
        # 260618-25/27: 책갈피 우클릭 — 1단=‘2단 보기’, 2단=반대 창으로 복사
        self.bookmark_tree.set_pane_role(0)
        self.bookmark_tree_right.set_pane_role(1)
        self.bookmark_tree.splitViewRequested.connect(
            lambda want: self._on_split_view_requested(want, 0))
        self.bookmark_tree_right.splitViewRequested.connect(
            lambda want: self._on_split_view_requested(want, 1))
        self.bookmark_tree.copyPaneRequested.connect(
            lambda: self._on_copy_pane_requested(0))        # 상단(1창)→2창
        self.bookmark_tree_right.copyPaneRequested.connect(
            lambda: self._on_copy_pane_requested(1))        # 하단(2창)→1창
        # 260618-27: 외부 PDF/폴더를 상단(좌=1창)/하단(우=2창) 책갈피창에 드롭 → 해당 창에 등록.
        #   드롭 대상 창이 명확하므로 활성창 선택 없이 그 창으로 바로 연다.
        self.bookmark_tree.pathDropped.connect(lambda p: self._on_pane_path_drop(0, p))
        self.bookmark_tree_right.pathDropped.connect(lambda p: self._on_pane_path_drop(1, p))
        self.page_thumbs.pageActivated.connect(lambda pg: self.main_view.go_to_page(pg))
        self.page_thumbs.pageFilterChanged.connect(                # 260609-26
            lambda _=None: self._push_nav_filter())
        self.page_thumbs.fileBoundaryRequested.connect(            # 260610-1
            lambda d: self._on_file_boundary(d, self._active_pane))
        self.page_thumbs.addBookmarkAtPage.connect(self._on_thumb_add_bookmark)
        self.page_thumbs.registerHyperlinkAtPage.connect(
            lambda pg: self._open_hyperlink_dialog(
                self.main_view.current_file() if self.main_view else None, int(pg)))
        self.page_thumbs.setPagesHidden.connect(self._set_pages_hidden)  # 260609-14(D5)
        self.page_thumbs.rotatePages.connect(self._rotate_pages)         # 260609-15(A1)
        self.page_thumbs.printPagesRequested.connect(self._on_thumb_print_pages)        # 260616-21
        self.page_thumbs.screenshotPagesRequested.connect(self._on_thumb_screenshot_pages)
        # 260606-8: 두 메인 창의 시그널을 활성 창 기준으로 라우팅
        for _i, _mv in enumerate(self._mv):
            self._wire_pane_signals(_mv, _i)
            self._init_draw_config(_mv)          # 260609-22(J3): 선긋기 표시(뷰 모드도)
        self.study_panel.buildRequested.connect(self._action_build_study)
        # 260603: 선택(클릭/상하이동)→메인 강조, 읽기/편집/Word/본문강조
        self.study_panel.wordSelected.connect(self._on_study_word_activated)
        self.study_panel.speakRequested.connect(self._on_study_speak)
        self.study_panel.editRequested.connect(self._on_study_edit)
        self.study_panel.addTermRequested.connect(self._on_study_add_term)  # P5 ＋용어추가
        self.study_panel.exportRequested.connect(self._on_study_export)
        self.study_panel.autoHighlightChanged.connect(self._on_study_auto_highlight)
        self.study_panel.playToggled.connect(self._on_study_autoread)
        # 260606: 표시 필터 / 선택단어 저장·삭제 / mp3
        self.study_panel.wordFilterChanged.connect(
            lambda: self._refresh_study_panel(self.main_view.current_page()))
        self.study_panel.markSelectedRequested.connect(self._on_study_mark_selected)
        self.study_panel.deleteWordRequested.connect(self._on_study_delete_word)
        self.study_panel.mp3Requested.connect(self._on_study_mp3)
        self.study_panel.sourceToggled.connect(self._on_study_source_toggled)  # P2 출처 on/off
        # 260606-3/5: 스크린샷이 모두 삭제되면 창 숨김
        # rowsRemoved=개별 삭제(takeItem), modelReset/clearedAll='전체 삭제'(list.clear())
        self.shot_strip.list.model().rowsRemoved.connect(
            lambda *_: self._hide_shots_if_empty())
        self.shot_strip.list.model().modelReset.connect(
            lambda *_: self._hide_shots_if_empty())
        self.shot_strip.clearedAll.connect(self._hide_shots_if_empty)
        # 260606-2: ↑/↓ 페이지 넘김, 빠르기·성우(본화면 공유)
        self.study_panel.crossPageRequested.connect(self._on_study_cross_page)
        self.study_panel.speedChanged.connect(self.read_aloud.set_rate)
        self.study_panel.voiceChanged.connect(
            lambda name: self.read_aloud.set_voice(name or None))
        # 260603/260606-8: 호버·클릭·페이지변경·매치위치·이미지스텝은 _wire_pane_signals 에서
        #                   양쪽 창에 대해 활성 창 기준으로 연결됨.
        # 단어장 탭으로 전환 시 현재 페이지 단어 1회 갱신
        self.search_tabs.currentChanged.connect(
            lambda _i: self._refresh_study_panel(self.main_view.current_page())
            if self.search_tabs.currentWidget() is self.study_panel else None)

        self.search_bar.searchRequested.connect(self.action_search)
        self.search_bar.queryCleared.connect(lambda: self.main_view.set_query(""))
        # v1.6.2: 검색바 < > 는 검색결과 리스트 전체(파일 경계 넘어)를 순회
        self.search_bar.prevMatch.connect(self._global_prev_match)
        self.search_bar.nextMatch.connect(self._global_next_match)
        # M7: SearchBar 의 screenshot 시그널은 호환 보존
        self.search_bar.screenshotRequested.connect(self.action_screenshot)
        self.search_bar.screenshotPdfSaveRequested.connect(self.action_save_screenshot_pdf)
        # v1.6.1 F4: 즐겨찾기 추가 시그널
        self.search_bar.favoriteRequested.connect(self._add_current_search_favorite)
        self.bookmark_tree.favoriteRequested.connect(self._add_current_folder_favorite)
        self.bookmark_tree.addFileFavoriteRequested.connect(self._add_file_favorite)  # ⑫
        # v1.6.18: 책갈피 편집 저장 완료 → 새 _edited.pdf 자동 로드
        self.bookmark_tree.bookmarksEdited.connect(self._on_bookmarks_edited)
        # 260611-18(A4): '저장' 버튼이 page_meta(개체/주석 등)도 디스크에 저장하도록 훅 주입
        self.bookmark_tree.set_meta_hooks(lambda: bool(self._edit_dirty),
                                          self._save_meta_from_button)
        # 260821/260822: 썸네일 페이지 편집을 💾 저장에 통합 + 저장 목적지(덮어쓰기/Shift=_edited)
        self.bookmark_tree.set_page_edit_hooks(self._page_edits_dirty, self._page_edit_save,
                                               self._finalize_save)
        # 260822: 폴더 모드 → 파일 모드 전환 시 대상 = 현재 본문 파일
        self.bookmark_tree.set_current_file_getter(
            lambda: (self.main_view.current_file() if self.main_view else None))
        # 260611-9: 편집 취소 → 숨김/회전/선긋기/하이퍼링크도 스냅샷으로 되돌리기
        self.bookmark_tree.editCancelled.connect(self._on_edit_cancelled)
        # v1.6.20 K5: 메인 페이지로 책갈피 추가
        self.bookmark_tree.addBookmarkRequested.connect(self._on_add_bookmark_requested)
        self.bookmark_tree.createBookmarksRequested.connect(
            lambda f: self.action_open_bookmarker(default_file=f))
        self.bookmark_tree.createStudyRequested.connect(self._on_create_study_requested)
        self.bookmark_tree.createStudyBookmarksRequested.connect(
            lambda f: self._action_build_study_and_bookmarks(file_path=f))
        self.bookmark_tree.mergeFilesRequested.connect(self._on_merge_files)
        self.bookmark_tree.translateFileRequested.connect(self._action_translate_file)  # 260621-P0
        self.bookmark_tree.editGlossaryRequested.connect(self._action_edit_glossary)  # 260623
        self.bookmark_tree.translateFilesRequested.connect(self._action_translate_files)  # 260621-P0
        # 260606-22: 책갈피 편집모드 ↔ 썸네일 페이지 편집(삭제/이동) 동기화
        self.bookmark_tree.btn_edit.toggled.connect(self.page_thumbs.set_edit_mode)
        self.bookmark_tree.btn_edit.toggled.connect(self._on_edit_mode_toggled)  # 260609-22(J3)
        self.page_thumbs.applyPageEditsRequested.connect(self._on_apply_page_edits)
        # 260821: 썸네일 복사/붙여넣기(다른 PDF 로도)
        self._thumb_clip = None       # {"src": path, "pages": [0-based idx...]}
        self.page_thumbs.copyPagesRequested.connect(self._on_copy_pages)
        self.page_thumbs.pastePagesRequested.connect(self._on_paste_pages)
        self.page_thumbs._paste_available = (
            lambda: len(self._thumb_clip["pages"]) if self._thumb_clip else 0)
        # v1.6.21: 파일 작업 핸드셰이크 (메인이 열고 있는 파일도 작업 가능)
        self.bookmark_tree.releaseFileRequested.connect(self._on_release_file)
        self.bookmark_tree.fileOpCompleted.connect(self._on_file_op_completed)
        self.bookmark_tree.viewModeChanged.connect(self._on_view_mode_changed)  # 260825
        self.bookmark_tree.filePasswordEntered.connect(self._on_file_password_entered)  # 260618-1
        self._released_state = None    # (path, page_index) — 작업 직전 닫은 파일 기억

        self.search_results.resultActivated.connect(self._on_search_result_activated)
        self.search_results.exportRequested.connect(self.action_export_search_excel)
        # M6/S5: 검색결과 일괄 캡쳐 버튼
        self.search_results.screenshotForResultRequested.connect(
            self._on_search_screenshot_requested)

        # v1.6.2: 스크린샷 미니카드만 남음
        self.shot_strip.itemActivated.connect(
            lambda p, pg: self._on_screenshot_activated(p, pg)
        )
        # (이미지 모드 ◀▶·페이지입력은 _wire_pane_signals 에서 연결)

    # ===== 폴더 / 인덱스 =================================================
    def action_open_folder(self):
        last = str(self._folder) if self._folder else ""
        folder = QFileDialog.getExistingDirectory(self, "PDF 폴더 선택", last)
        if folder:
            self.open_folder(Path(folder))

    def action_open_pdf(self):
        """v1.6.11 I1: 단일 PDF 파일 열기."""
        start = str(self._folder) if self._folder else ""
        fn, _ = QFileDialog.getOpenFileName(self, "PDF 파일 열기", start, "PDF (*.pdf)")
        if fn:
            self.open_pdf(Path(fn))

    def open_pdf(self, pdf_path: Path):
        """v1.6.11 I1/I2: 단일 PDF 를 열고 그 파일만 인덱싱.
        260618-20: 2단 보기에서는 워크스페이스(다른 창·상단 책갈피·폴더)를 비우지 않고
        **활성 창에만** 로드 → 옆 창 내용 유지, 상단 책갈피 유지, 다른 폴더면 하단에 표시(#7)."""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
            self.status.showMessage(f"PDF 파일이 아닙니다: {pdf_path.name}")
            return
        if getattr(self, "_split_on", False):
            # 2단: 활성 창에만 로드(다른 창·폴더·반대편 책갈피 보존).
            #   260618-23: 단독 파일을 '열기'(드롭/즐겨찾기/파일열기)한 것이므로 그 창의 폴더를
            #   이 파일의 폴더로 설정(상=좌/하=우 트리에 반영). 책갈피 클릭은 _load_main 만 호출해 폴더 불변.
            self._load_main(HistoryItem(str(pdf_path), 0, "", "bookmark"))
            self._set_pane_folder(self._active_pane, pdf_path.parent)
            try:
                self._cancel_active_indexing()
                worker = IndexWorker(self._db_path, pdf_path.parent, single_file=pdf_path)
                worker.error.connect(lambda e: None)
                self._start_index_worker(worker)
            except Exception:
                pass
            return
        self._cancel_active_indexing()       # 260611-89: 이전 인덱싱 즉시 중단
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        try:
            self._clear_workspace()
            self._folder = pdf_path.parent     # index.db·즐겨찾기 경로 호환
            self.bookmark_tree.load_single_pdf(pdf_path)
            self.search_results.set_bookmark_order({})
            self._refresh_search_scope()        # 260616-3: 이 파일로만 검색 한정
            self.setWindowTitle(
                f"PolyPDF  v{__version__}  —  {pdf_path.name}")
            self.status.showMessage(f"파일 로드: {pdf_path}")
        finally:
            QApplication.restoreOverrideCursor()
        self._load_main(HistoryItem(str(pdf_path), 0, "", "bookmark"))
        # 해당 파일만 인덱싱 (폴더 전체 인덱싱 회피)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.showMessage("인덱싱 준비...")
        worker = IndexWorker(self._db_path, self._folder, single_file=pdf_path)
        worker.progress.connect(self._on_index_progress)
        worker.finished.connect(self._on_index_finished)
        worker.error.connect(lambda e: self.status.showMessage(f"인덱싱 오류: {e}"))
        self._start_index_worker(worker)

    # --- v1.6.11 I2: 드래그&드롭 ---------------------------------------
    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls():
            for u in md.urls():
                p = Path(u.toLocalFile())
                if p.is_dir() or p.suffix.lower() == ".pdf":
                    event.acceptProposedAction()
                    return
        event.ignore()

    def _pane_at_global(self, gpos) -> int:
        """260618-22: 전역 좌표가 속한 메인 뷰어 창 인덱스(2단). 못 찾으면 활성 창."""
        if not getattr(self, "_split_on", False):
            return 0
        try:
            for idx, fr in enumerate(self._panes):
                tl = fr.mapToGlobal(fr.rect().topLeft())
                br = fr.mapToGlobal(fr.rect().bottomRight())
                if tl.x() <= gpos.x() <= br.x() and tl.y() <= gpos.y() <= br.y():
                    return idx
        except Exception:
            pass
        return self._active_pane

    def dropEvent(self, event):
        # 260618-22: 드롭한 '창'을 대상으로 — 그 창을 활성화 후 열기
        try:
            gpos = self.mapToGlobal(event.position().toPoint())
            self._set_active_pane(self._pane_at_global(gpos))
        except Exception:
            pass
        for u in event.mimeData().urls():
            p = Path(u.toLocalFile())
            if p.is_dir():
                self.open_folder(p)
                event.acceptProposedAction()
                return
            if p.suffix.lower() == ".pdf":
                self.open_pdf(p)
                event.acceptProposedAction()
                return
        event.ignore()

    # --- v1.6.16: 책갈피 자동 생성 (외부 pdf_bookmarker) ----------------
    def action_open_bookmarker(self, checked: bool = False, default_file: str = None):
        """파일 → 책갈피 자동 생성... 메뉴 핸들러. default_file=트리 우클릭 등 지정 입력."""
        from viewer.widgets.bookmarker_dialog import BookmarkerDialog
        # 지정 파일 > 현재 메인 PDF 를 입력 기본값으로
        if default_file and str(default_file).lower().endswith(".pdf"):
            default_pdf = Path(default_file)
        else:
            cur = self.main_view.current_file() if self.main_view else None
            default_pdf = Path(cur) if cur and cur.lower().endswith(".pdf") else None
        dlg = BookmarkerDialog(default_pdf=default_pdf, prefs=self._prefs, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        opts = dlg.result_options()
        if not opts["input_pdf"]:
            QMessageBox.warning(self, "안내", "입력 PDF를 지정하세요.")
            return
        in_pdf = Path(opts["input_pdf"])
        if not in_pdf.exists() or in_pdf.suffix.lower() != ".pdf":
            QMessageBox.warning(self, "안내", f"PDF 파일이 아닙니다: {in_pdf.name}")
            return
        if not (opts["save_pdf"] or opts["save_txt"]):
            QMessageBox.warning(self, "안내", "출력 옵션을 최소 1개 선택하세요.")
            return

        # prefs 기본값 갱신
        self._prefs["bookmarker_path"] = opts.get("bookmarker_path", "")
        self._prefs["bookmarker_mode"] = opts.get("mode", "auto")
        self._prefs["bookmarker_ocr_font_auto"] = bool(opts.get("ocr_font_auto", True))
        self._prefs["bookmarker_save_pdf"] = bool(opts["save_pdf"])
        self._prefs["bookmarker_overwrite"] = bool(opts.get("overwrite"))
        self._prefs["bookmarker_save_txt"] = bool(opts["save_txt"])
        try:
            self._save_settings_now()
        except Exception:
            pass

        # 260606-4: '현재 PDF에 저장'이고 그 파일이 메인에 열려있으면 핸들 해제(덮어쓰기 가능)
        if opts.get("overwrite"):
            # 안전장치: 기존 책갈피가 있으면 '모두 대체됨'을 경고·확인
            try:
                import fitz
                _d = fitz.open(str(in_pdf))
                _toc = _d.get_toc() or []
                _d.close()
            except Exception:
                _toc = []
            if _toc:
                if QMessageBox.question(
                    self, "현재 PDF에 저장",
                    f"이 PDF에는 기존 책갈피 {len(_toc)}개가 있습니다.\n"
                    "현재 PDF에 저장하면 기존 책갈피는 모두 지워지고 "
                    "새로 만든 책갈피로 대체됩니다.\n"
                    "(되돌릴 수 없습니다. 원본을 보존하려면 '새 PDF로 저장'을 선택하세요.)\n\n"
                    "계속할까요?"
                ) != QMessageBox.StandardButton.Yes:
                    return
            cur = self.main_view.current_file() if self.main_view else None
            try:
                same = cur and Path(cur).resolve() == in_pdf.resolve()
            except Exception:
                same = False
            if same:
                self._close_main_view_doc()
                QApplication.processEvents()

        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.showMessage("책갈피 자동 생성 시작...")

        worker = BookmarkerWorker(in_pdf, opts)
        worker.progress.connect(lambda m: self.status.showMessage(m))
        worker.finished.connect(self._on_bookmarker_done)
        worker.error.connect(self._on_bookmarker_error)
        run_in_thread(worker, self._thread_keep)

    def _on_bookmarker_done(self, result: dict):
        self.progress.setVisible(False)
        parts = [f"방법={result.get('method')}", f"개수={result.get('count')}"]
        if result.get("offset") is not None:
            parts.append(f"오프셋={result['offset']}")
        if result.get("pdf_out"):
            parts.append(f"PDF: {Path(result['pdf_out']).name}")
        if result.get("txt_out"):
            parts.append(f"TXT: {Path(result['txt_out']).name}")
        self.status.showMessage("책갈피 생성 완료 — " + " · ".join(parts), 8000)
        # 260606-4: 자동 열기 옵션 폐지 → 항상 책갈피 새로고침(기존 목록 유지) + 메인 로드
        pdf_out = result.get("pdf_out")
        if pdf_out and Path(pdf_out).exists():
            try:
                self.bookmark_tree.add_or_refresh_file(pdf_out)
            except Exception:
                pass
            try:
                self._load_main(HistoryItem(str(pdf_out), 0, "", "bookmark"))
            except Exception:
                pass
            self._index_single_file(pdf_out)        # 새 PDF를 검색 인덱스에 포함

    def _on_bookmarker_error(self, msg: str):
        self.progress.setVisible(False)
        self.status.showMessage(f"책갈피 생성 오류: {msg}", 8000)
        QMessageBox.warning(self, "책갈피 생성 실패", msg)

    def _on_bookmarks_edited(self, src: str, dst: str):
        """v1.6.18: 책갈피 편집 저장 완료 → 260606-4: 목록 유지하며 새로고침 + 메인 로드."""
        self.status.showMessage(f"책갈피 저장: {Path(dst).name}", 6000)
        try:
            self.bookmark_tree.add_or_refresh_file(dst)
        except Exception:
            pass
        try:
            self._load_main(HistoryItem(str(dst), 0, "", "bookmark"))
        except Exception:
            pass
        self._index_single_file(dst)                # 편집본을 검색 인덱스에 포함

    # --- v1.6.21: 파일 작업 핸드셰이크 ----------------------------------
    def _close_main_view_doc(self):
        """메인 뷰어·페이지 썸네일의 PDF 핸들을 즉시 해제 (트리/검색결과는 유지).
        260606-8: 두 창 모두 해제(파일 잠금 방지)."""
        for mv in getattr(self, "_mv", []):
            try:
                if getattr(mv, "_doc", None) is not None:
                    try:
                        mv._doc.close()
                    except Exception:
                        pass
                    mv._doc = None
                mv._is_image = False
                mv.scene.clear()
                mv._page_item = None
                mv.spin_page.setMaximum(1)
                mv.lbl_page_total.setText("/ 0")
            except Exception:
                pass
        try:
            if getattr(self.page_thumbs, "_doc", None) is not None:
                try:
                    self.page_thumbs._doc.close()
                except Exception:
                    pass
                self.page_thumbs._doc = None
            self.page_thumbs.list.clear()
        except Exception:
            pass
        self._current_main = None

    def _on_release_file(self, path: str):
        """파일 시스템 작업 전 호출 — 같은 파일을 열고 있다면 핸들 해제."""
        self._released_state = None
        try:
            tgt = Path(path).resolve()
            files = [mv.current_file() for mv in self._mv]
            if any(f and Path(f).resolve() == tgt for f in files):
                page = self.main_view.current_page()
                self._released_state = (str(path), int(page))
                self._close_main_view_doc()
                QApplication.processEvents()
        except Exception:
            self._released_state = None

    def _on_file_op_completed(self, old: str, new: str):
        """파일 작업 결과에 따라 메인 뷰어를 다시 로드.

        규칙: new == ""    → 삭제(그대로 비움)
               new != old → 이름변경 성공 (새 경로 재로드)
               new == old → 실패 (원본 재로드)
        """
        rel = self._released_state
        self._released_state = None
        if not rel:
            return
        _old, page = rel
        target = new if new else None        # 삭제면 None
        try:
            if target and Path(target).exists():
                self._load_main(HistoryItem(target, int(page), "", "bookmark"))
        except Exception:
            pass

    def _on_add_bookmark_requested(self, target_file: str):
        """v1.6.20 K5: 메인 뷰어 현재 페이지로 책갈피 추가."""
        from PyQt6.QtWidgets import QInputDialog
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or Path(cur).resolve() != Path(target_file).resolve():
            QMessageBox.information(self, "안내",
                "대상 PDF 가 메인 뷰어에 열려있어야 현재 페이지를 알 수 있습니다.\n"
                f"먼저 트리에서 '{Path(target_file).name}' 를 열어 주세요.")
            return
        page = self.main_view.current_page() + 1  # 1-based
        title, ok = QInputDialog.getText(self, "책갈피 추가",
                                         f"현재 페이지(p.{page})에 추가할 책갈피 제목:")
        if not ok:
            return
        self.bookmark_tree.add_bookmark(target_file, page, title)
        self.status.showMessage(
            f"책갈피 추가됨: {title or '(제목 없음)'}  (p.{page}) — 저장(💾)을 눌러야 PDF 에 반영됩니다.",
            6000)

    def _prompt_add_bookmark(self, cur: str, page_1based: int):
        """제목 입력 → 트리 대상 파일에 책갈피 추가(저장은 편집모드 💾)."""
        from PyQt6.QtWidgets import QInputDialog
        title, ok = QInputDialog.getText(
            self, "책갈피 추가", f"p.{page_1based}에 추가할 책갈피 제목:")
        if not ok:
            return
        self.bookmark_tree.add_bookmark(cur, page_1based, title)
        self.status.showMessage(
            f"책갈피 추가됨: {title or '(제목 없음)'}  (p.{page_1based}) — "
            "책갈피창 편집(✏)에서 저장(💾)해야 PDF에 반영됩니다.", 6000)

    def _on_create_study_requested(self, file_path: str):
        """260606-5: 책갈피창 파일 우클릭 '단어장 생성' → 해당 파일을 열고 빌드."""
        p = Path(file_path)
        if not p.exists() or p.suffix.lower() != ".pdf":
            QMessageBox.information(self, "단어장", f"PDF 파일이 아닙니다: {p.name}")
            return
        cur = self.main_view.current_file() if self.main_view else None
        try:
            same = cur and Path(cur).resolve() == p.resolve()
        except Exception:
            same = False
        if not same:
            # 메인 로드 → _study_pdf 가 이 파일로 설정됨
            self._load_main(HistoryItem(str(p), 0, "", "bookmark"))
        self._action_build_study()

    def _action_build_study_and_bookmarks(self, checked: bool = False, file_path: str = None):
        """260606-11: 단어장·책갈피 동시 생성(OCR 1회 공유). 파일 메뉴/트리 우클릭/읽기 제안에서."""
        cur = self.main_view.current_file() if self.main_view else None
        p = Path(file_path) if file_path else (Path(cur) if cur else None)
        if not p or not p.exists() or p.suffix.lower() != ".pdf":
            QMessageBox.information(self, "단어장·책갈피", "먼저 PDF를 여세요.")
            return
        try:
            same = cur and Path(cur).resolve() == p.resolve()
        except Exception:
            same = False
        if not same:
            self._load_main(HistoryItem(str(p), 0, "", "bookmark"))
        self._action_build_study(also_bookmarks=True)

    def _maybe_offer_ocr(self, view) -> bool:
        """260606-11: 읽을 텍스트가 없고 스캔/이미지면 OCR(단어장+책갈피) 제안.
        실행하면 True(읽기 중단). 이미 단어장/텍스트가 있으면 False."""
        try:
            f = view.current_file()
            if not f or not str(f).lower().endswith(".pdf"):
                return False
            from viewer.study.study_store import file_key_for
            store = self._study_get_store()
            if store.vocab_count(file_key_for(f)) > 0:
                return False                      # 이미 단어장 있음
            txt = ""
            try:
                txt = (view._doc.extract_text(view.current_page()) or "")
                if len(txt.strip()) < 20:
                    txt = (view._doc.extract_text(0) or "")
            except Exception:
                txt = ""
            if len(txt.strip()) >= 20:
                return False                      # 텍스트 레이어로 읽기 가능
            ret = QMessageBox.question(
                self, "문서 인식(OCR)",
                "읽을 텍스트가 없습니다(스캔/이미지 문서).\n"
                "문서 인식(OCR)을 하여 단어장과 책갈피를 함께 만들까요?")
            if ret == QMessageBox.StandardButton.Yes:
                self._action_build_study_and_bookmarks(file_path=f)
                return True
            return False
        except Exception:
            return False

    def _page_edits_dirty(self) -> bool:
        """260821: 썸네일 페이지 삭제/이동 미저장 여부(💾 저장 통합용)."""
        try:
            pt = self.page_thumbs
            return bool(getattr(pt, "_doc", None)) and pt.is_page_dirty()
        except Exception:
            return False

    def _edit_save_dst(self, src, shift: bool):
        """저장 목적지 결정 — shift 없으면 원본 덮어쓰기, shift 면 `_edited`(충돌 시 (k)).
        (dst_path, overwrite) 반환."""
        from pathlib import Path as _P
        src = _P(src)
        if not shift:
            return src, True                         # 원본 덮어쓰기
        base = src.stem + "_edited"
        d = src.with_name(base + ".pdf")
        if not d.exists():
            return d, False
        for k in range(1, 1000):
            d = src.with_name(f"{base} ({k}).pdf")
            if not d.exists():
                return d, False
        return d, False

    def _finalize_save(self, src, produced, shift=None) -> str:
        """260822: 편집 저장 산출물(produced 임시 PDF)을 목적지에 배치.
        기본=원본 덮어쓰기(열린 핸들 닫고 교체), Shift+저장=`_edited`(충돌 시 (k)).
        최종 경로(str) 반환. 로드는 호출측이 수행."""
        from pathlib import Path as _P
        import os as _os
        if shift is None:
            shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        src = _P(src); produced = _P(produced)
        dst, overwrite = self._edit_save_dst(src, shift)
        try:
            if overwrite:
                self._close_main_view_doc()          # 원본 잠금 해제(뷰어·썸네일 핸들)
                QApplication.processEvents()
            _os.replace(str(produced), str(dst))
        except Exception:
            # 덮어쓰기 실패(잠금 등) → _edited 로 폴백
            fb, _ = self._edit_save_dst(src, True)
            _os.replace(str(produced), str(fb))
            dst = fb
        return str(dst)

    def _page_edit_save(self, src_str: str, bookmarks_raw):
        """260821/260822: 💾 저장 — 썸네일의 페이지 순서/삭제로 PDF 재구성 + 책갈피 remap.
        기본=원본 덮어쓰기, Shift+저장=`{이름}_edited.pdf`(충돌 시 (k)). 저장 후 로드."""
        from pathlib import Path as _P
        import os as _os
        pt = self.page_thumbs
        plan = pt.current_page_plan()          # ('own',idx) 또는 ('ext',src,page) 목록
        if not plan:
            QMessageBox.warning(self, "페이지 편집 저장", "최소 1쪽은 남겨야 합니다.")
            return
        src = _P(src_str)
        shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        recon = src.with_name(src.stem + "_recon_tmp.pdf")
        book_tmp = src.with_name(src.stem + "_book_tmp.pdf")
        produced = recon
        saved_n = 0
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        try:
            import fitz
            sdoc = fitz.open(str(src))
            ext_cache = {}                     # esrc -> fitz doc (붙여넣기 원본)
            odoc = fitz.open()
            ownpos = {}                        # 원본 페이지(0-based) → 새 위치(0-based)
            outc = 0
            try:
                for entry in plan:
                    if entry[0] == "own":
                        idx = entry[1]
                        if 0 <= idx < sdoc.page_count:
                            odoc.insert_pdf(sdoc, from_page=idx, to_page=idx)
                            ownpos[idx] = outc; outc += 1
                    else:                      # ('ext', esrc, epg) — 붙여넣기 페이지
                        esrc, epg = entry[1], entry[2]
                        ed = ext_cache.get(esrc)
                        if ed is None:
                            ed = sdoc if esrc == str(src) else fitz.open(esrc)
                            ext_cache[esrc] = ed
                        if 0 <= epg < ed.page_count:
                            odoc.insert_pdf(ed, from_page=epg, to_page=epg)
                            outc += 1
                if outc == 0:
                    raise RuntimeError("저장할 페이지가 없습니다.")
                odoc.save(str(recon), garbage=4, deflate=True)
                saved_n = outc
            finally:
                odoc.close()
                for ed in ext_cache.values():
                    if ed is not sdoc:
                        try:
                            ed.close()
                        except Exception:
                            pass
                sdoc.close()
            # 책갈피 remap: 삭제된 페이지 책갈피는 버리고, 남은 원본 페이지는 새 번호로
            bms = [(t, ownpos[p1 - 1] + 1, lv) for (t, p1, lv) in (bookmarks_raw or [])
                   if (p1 - 1) in ownpos]
            if bms:
                from viewer import bookmarker_bridge as bridge
                if bridge.is_available():
                    import pdf_bookmarker as pb
                    blist = [pb.Bookmark(title=t, page=p, level=lv) for (t, p, lv) in bms]
                    bridge.apply_to_pdf(recon, book_tmp, blist)
                    try:
                        _os.remove(str(recon))
                    except Exception:
                        pass
                    produced = book_tmp
            final = self._finalize_save(src, produced, shift)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            for t in (recon, book_tmp):
                try:
                    if t.exists():
                        _os.remove(str(t))
                except Exception:
                    pass
            QMessageBox.warning(self, "페이지 편집 저장 실패", str(e))
            return
        QApplication.restoreOverrideCursor()
        self.status.showMessage(f"페이지 편집 저장: {saved_n}쪽 → {_P(final).name}", 6000)
        try:
            self.bookmark_tree.add_or_refresh_file(final)
            self._load_main(HistoryItem(final, 0, "", "bookmark"))
            self._index_single_file(_P(final))
        except Exception:
            pass

    def _on_copy_pages(self, pages):
        """260821: 현재 PDF 썸네일에서 선택한 페이지(0-based)를 복사(다른 PDF 로 붙여넣기용)."""
        pt = self.page_thumbs
        doc = getattr(pt, "_doc", None)
        if not doc or not pages:
            return
        try:
            src = str(doc.path)
        except Exception:
            src = str(getattr(pt, "_doc_path", "") or "")
        if not src:
            return
        self._thumb_clip = {"src": src, "pages": [int(p) for p in pages]}
        self.status.showMessage(
            f"썸네일 {len(pages)}쪽 복사됨 — 다른 PDF 썸네일에서 붙여넣기(Ctrl+V)", 5000)

    def _on_paste_pages(self, after_row: int):
        """260822: 복사한 페이지를 현재 PDF 썸네일의 기준 행 '뒤'에 **스테이징 삽입**(미저장).
        자동 저장하지 않고 상태만 기억 → 💾 '저장'을 눌러야 실제 파일로 반영(편집모드만)."""
        clip = self._thumb_clip
        pt = self.page_thumbs
        doc = getattr(pt, "_doc", None)
        if not clip or not doc:
            return
        if not getattr(pt, "_edit_mode", False):      # 편집모드에서만 붙여넣기 허용
            self.status.showMessage("붙여넣기는 편집모드(✏)에서만 됩니다.", 4000)
            return
        src_pages = list(clip.get("pages") or [])
        if not src_pages:
            return
        n = pt.insert_external_pages(after_row, clip.get("src"), src_pages)
        self.status.showMessage(
            f"붙여넣기 {n}쪽 삽입(미저장) — 💾 ‘저장’을 눌러 반영하세요.", 6000)

    def _on_apply_page_edits(self):
        """260606-22: 썸네일에서 편집한 페이지 순서/삭제를 새 PDF로 저장."""
        pt = self.page_thumbs
        if not getattr(pt, "_doc", None):
            return
        src = Path(str(pt._doc.path))
        seq = pt.current_page_sequence()
        if not pt.is_page_dirty():
            QMessageBox.information(self, "페이지 편집", "변경 사항이 없습니다.")
            return
        if not seq:
            QMessageBox.warning(self, "페이지 편집", "최소 1쪽은 남겨야 합니다.")
            return
        from PyQt6.QtWidgets import QFileDialog
        default = str(src.with_name(src.stem + "_pages.pdf"))
        out, _ = QFileDialog.getSaveFileName(self, "페이지 편집 저장", default, "PDF (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        try:
            # 260606-23: fitz 로 페이지 재구성(손상 PDF 자동 복구)
            import fitz
            src_doc = fitz.open(str(src))
            out_doc = fitz.open()
            try:
                for idx in seq:
                    if 0 <= idx < src_doc.page_count:
                        out_doc.insert_pdf(src_doc, from_page=idx, to_page=idx)
                out_doc.save(out, garbage=4, deflate=True)
            finally:
                out_doc.close(); src_doc.close()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "페이지 편집 저장 실패", str(e))
            return
        QApplication.restoreOverrideCursor()
        self.status.showMessage(
            f"페이지 편집 저장: {len(seq)}쪽 → {Path(out).name}", 6000)
        try:
            self.bookmark_tree.add_or_refresh_file(out)
        except Exception:
            pass
        try:
            self._load_main(HistoryItem(str(out), 0, "", "bookmark"))
        except Exception:
            pass
        self._index_single_file(out)

    def _on_merge_files(self, preselected: list = None):
        """260606-15: PDF 병합 — 좌(전체)/우(대상) 다이얼로그. 스크린샷·드롭·정렬·자동생성."""
        all_files = []
        try:
            all_files = self.bookmark_tree.all_file_paths()
        except Exception:
            pass
        shots = []
        try:
            shots = [p for p in self.shot_strip.all_paths()
                     if p and str(p).lower().endswith((".png", ".jpg", ".jpeg"))]
        except Exception:
            pass
        pre = [p for p in (preselected or []) if p and str(p).lower().endswith(".pdf")]
        from viewer.widgets.merge_dialog import MergeFilesDialog
        dlg = MergeFilesDialog(all_files, pre, shots, self,
                               preset_api=self._merge_preset_api())
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        items = dlg.result_items()
        if not items:
            return
        auto = dlg.auto_build()
        from PyQt6.QtWidgets import QFileDialog
        base = next((Path(it["path"]) for it in items if it.get("type") == "pdf"), None)
        default = str((base.with_name(base.stem + "_merged.pdf")) if base
                      else (Path(self._folder) / "merged.pdf" if self._folder else "merged.pdf"))
        # 260611-35: 덮어쓰기 확인은 직접 처리(기존 파일은 (1),(2)로 보존 / 원본과 같으면 재확인)
        out, _ = QFileDialog.getSaveFileName(
            self, "병합 PDF 저장", default, "PDF (*.pdf)",
            options=QFileDialog.Option.DontConfirmOverwrite)
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        # 저장 이름이 '병합 대상 원본'과 같으면 덮어쓸지 한 번 더 확인, 그 외 기존 파일은 보존((1),(2))
        try:
            src_paths = {str(Path(it["path"]).resolve()) for it in items
                         if it.get("type") == "pdf" and it.get("path")}
        except Exception:
            src_paths = set()
        out_res = str(Path(out).resolve())
        if out_res in src_paths:
            if QMessageBox.question(
                self, "원본 덮어쓰기 확인",
                f"저장하려는 이름이 병합 대상 원본 파일과 같습니다:\n\n{Path(out).name}\n\n"
                "이 원본 파일을 덮어쓸까요?\n('아니오'를 누르면 (1)을 붙여 새 파일로 저장합니다.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                out = self._unique_save_path(out)
        elif Path(out).exists():
            out = self._unique_save_path(out)          # 기존 파일 보존
        # 260611-33: 병합을 백그라운드 스레드로 실행 → 큰 작업도 '응답 없음' 없이 진행·취소
        if dlg.twoup_enabled():
            from viewer.twoup import build_twoup
            settings = dlg.twoup_settings()
            job = (lambda progress, _s=settings:
                   build_twoup(items, _s, out,
                               gen_bookmarks_fn=self._gen_source_bookmarks,
                               progress=progress))
            title = "PDF 병합(2단 배치)"
        else:
            job = lambda progress: self._do_normal_merge(items, out, auto, progress)
            title = "PDF 병합"
        res = self._run_merge_job(job, title)
        if res.get("cancelled"):
            try:
                if Path(out).exists():
                    Path(out).unlink()
            except Exception:
                pass
            self.status.showMessage("병합을 취소했습니다.", 4000)
            return
        if res.get("err"):
            QMessageBox.warning(self, "병합 실패", res["err"])
            return
        self.status.showMessage(f"병합 완료 → {Path(out).name}", 6000)
        # 260611-34: 진행창이 사라진 다음 틱에 후처리(렌더·인덱싱·단어장) 실행 → 잔상/멈춤 방지
        from PyQt6.QtCore import QTimer

        def _post_merge():
            try:
                self.bookmark_tree.add_or_refresh_file(out)
            except Exception:
                pass
            self._index_single_file(out)        # 백그라운드
            # 260606-24: 책갈피는 병합 시 원본별로 이미 임베드 → auto면 '단어장'만 생성
            if auto:
                self._action_build_study()      # 백그라운드(확인창)
            # 260825-5: 생성 종료 후 '파일 열기(별도 새 창·기본)/폴더 열기' 선택
            self._after_pdf_created(out)
        QTimer.singleShot(0, _post_merge)

    def _run_merge_job(self, job, title):
        """260611-33: job(progress)을 _MergeThread 로 실행. 모달 진행창으로 응답성 유지.
        반환: {ok, err, cancelled}."""
        from PyQt6.QtWidgets import QProgressDialog
        prog = QProgressDialog("준비 중…", "취소", 0, 100, self)
        prog.setWindowTitle(title)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)
        prog.setAutoClose(False); prog.setAutoReset(False)
        prog.setValue(0)
        res = {"ok": False, "err": None, "cancelled": False}
        th = _MergeThread(job, self)

        # 260825-16/17: 하트비트 — tick 이 없는 긴 구간(예: 최종 PDF 저장)에도
        #   막대 애니메이션(|→||→|||→||)으로 '진행 중'을 계속 표시.
        #   (\ 는 한글 폰트에서 ₩ 로 보여 사용 안 함. 경과시간 표시 없음.)
        from PyQt6.QtCore import QTimer
        st = {"lbl": "준비 중…", "d": 0, "t": 1, "k": 0}
        _SPIN = ("|", "||", "|||", "||")

        def _render():
            sp = _SPIN[st["k"] % len(_SPIN)]
            prog.setLabelText(f"{st['lbl']}  ({st['d']}/{st['t']})   {sp}")

        def _on_prog(d, t, lbl):
            prog.setMaximum(max(1, t))
            prog.setValue(min(d, t))
            st.update(d=d, t=t, lbl=lbl)
            _render()

        def _beat():
            st["k"] += 1
            _render()
        hb = QTimer(self)
        hb.setInterval(250)
        hb.timeout.connect(_beat)
        hb.start()

        th.progressed.connect(_on_prog)
        th.failed.connect(lambda e: res.__setitem__("err", e))
        th.cancelledSig.connect(lambda: res.__setitem__("cancelled", True))
        th.okSig.connect(lambda: res.__setitem__("ok", True))
        prog.canceled.connect(th.cancel)
        loop = QEventLoop()
        th.finished.connect(loop.quit)
        th.start()
        loop.exec()                # 작업이 끝날 때까지 UI 이벤트 처리(응답성 유지)
        th.wait()
        hb.stop()
        # 진행창을 확실히 닫고 화면에서 즉시 제거(후처리로 인한 100% 잔상 방지)
        prog.reset()
        prog.hide()
        prog.close()
        prog.deleteLater()
        QApplication.processEvents()
        return res

    def _do_normal_merge(self, items, out, auto, progress):
        """260611-33: 일반 PDF 병합(스레드 실행). progress(done,total,label)->bool(계속)."""
        import fitz
        from viewer.twoup import MergeCancelled
        out_doc = fitz.open()
        merged_toc = []        # [level(1based), title, page(1based)]
        offset = 0
        total = max(1, len(items) + 1)
        try:
            for i, it in enumerate(items):
                if progress(i, total, f"병합 중: {it.get('name', '')}") is False:
                    raise MergeCancelled()
                if it.get("type") == "shots":
                    start = offset
                    for img in (it.get("paths") or []):
                        try:
                            pix = fitz.Pixmap(img)
                            page = out_doc.new_page(width=pix.width, height=pix.height)
                            page.insert_image(
                                fitz.Rect(0, 0, pix.width, pix.height), filename=img)
                            offset += 1
                        except Exception:
                            continue
                    merged_toc.append([1, it.get("name") or "사용자 스크린샷", start + 1])
                else:
                    path = str(it["path"])
                    src = fitz.open(path)
                    try:
                        n = src.page_count
                        emb = src.get_toc(simple=True) or []
                        if emb:                                   # 기존 책갈피 재사용
                            for lvl, title, pg in emb:
                                pp = offset + max(1, min(n, int(pg)))
                                merged_toc.append([max(1, int(lvl)), title, pp])
                        elif auto:                                # 없으면 생성
                            for title, pg, level in self._gen_source_bookmarks(path, src):
                                pp = offset + max(1, min(n, int(pg)))
                                merged_toc.append([int(level) + 1, title, pp])
                        out_doc.insert_pdf(src)
                        offset += n
                    finally:
                        src.close()
            progress(total, total, "저장 중…")
            if merged_toc:
                try:
                    out_doc.set_toc(self._normalize_toc(merged_toc))
                except Exception:
                    pass
            out_doc.save(out, garbage=4, deflate=True)
        finally:
            out_doc.close()

    # ===== 260611-36: 병합 배치 사용자 스타일(프리셋) =====
    def _merge_preset_api(self) -> dict:
        return {"get_presets": self._merge_get_presets,
                "save_preset": self._merge_save_preset,
                "delete_preset": self._merge_delete_preset}

    def _merge_get_presets(self) -> list:
        return list(self._prefs.get("merge_presets") or [])

    def _merge_save_preset(self, name, cfg):
        name = str(name).strip()
        if not name:
            return
        cfg = dict(cfg); cfg["name"] = name
        lst = [p for p in (self._prefs.get("merge_presets") or [])
               if p.get("name") != name]      # 같은 이름은 덮어쓰기
        lst.append(cfg)
        self._prefs["merge_presets"] = lst
        self._save_settings_now()

    def _merge_delete_preset(self, name):
        lst = [p for p in (self._prefs.get("merge_presets") or [])
               if p.get("name") != str(name)]
        self._prefs["merge_presets"] = lst
        self._save_settings_now()

    @staticmethod
    def _unique_save_path(path) -> str:
        """260611-35: 같은 이름이 있으면 'name (1).ext' … 로 보존.
        260628: 표준 `pathutil.unique_path` 위임(SOT §7.0)."""
        from viewer.pathutil import unique_path
        return str(unique_path(path))

    @staticmethod
    def _normalize_toc(toc: list) -> list:
        """fitz set_toc 유효 계층 보장: 첫 항목 level=1, 이후 level≤직전+1."""
        out = []
        prev = 0
        for entry in toc:
            lvl = max(1, int(entry[0]))
            title = str(entry[1]) or "(제목 없음)"
            pg = max(1, int(entry[2]))
            lvl = 1 if not out else min(lvl, prev + 1)
            out.append([lvl, title, pg])
            prev = lvl
        return out

    def _gen_source_bookmarks(self, path, doc=None) -> list:
        """260606-24: 책갈피 없는 원본의 책갈피를 생성 → [(title, page_1based, level0based)].
        디지털=폰트/텍스트(pdf_bookmarker), 스캔/이미지=OCR 헤딩."""
        # 1) 폰트/텍스트 기반(디지털 문서)
        try:
            from viewer import bookmarker_bridge as bridge
            if bridge.is_available():
                res = bridge.extract_auto(path, mode="auto")
                bms = res.get("bookmarks") or []
                if bms:
                    return [(b.title, int(b.page), int(b.level)) for b in bms]
        except Exception:
            pass
        # 2) 스캔/이미지 → OCR 헤딩
        try:
            from viewer.study.ocr_headings import extract_ocr_bookmarks
            bms = extract_ocr_bookmarks(path, use_font_auto=False)
            return [(b.title, int(b.page), int(b.level)) for b in bms]
        except Exception:
            pass
        return []

    def _on_thumb_add_bookmark(self, page_index: int):
        """260606-4: 썸네일 우클릭 → 현재 PDF의 해당 페이지로 책갈피 추가."""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or not str(cur).lower().endswith(".pdf"):
            QMessageBox.information(self, "안내", "먼저 PDF를 표시하세요.")
            return
        self._prompt_add_bookmark(cur, int(page_index) + 1)

    def _show_viewer_option_menu(self):
        """260825: 뷰어 옵션(우클릭) 메뉴를 단축키/메뉴로 표시 — 현재 뷰 중앙 위치."""
        mv = self.main_view
        if mv is None:
            return
        try:
            gp = mv.mapToGlobal(mv.rect().center())
        except Exception:
            from PyQt6.QtGui import QCursor as _QC
            gp = _QC.pos()
        self._on_viewer_context_menu(gp)

    def _on_viewer_context_menu(self, global_pos):
        """260606-4: 뷰어 우클릭 메뉴. 책갈피 추가(편집모드) + 하이퍼링크 등록(260609-3)."""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or not str(cur).lower().endswith(".pdf"):
            return
        page = self.main_view.current_page() + 1
        from PyQt6.QtWidgets import QMenu
        edit = self.bookmark_tree.is_edit_mode()
        menu = QMenu(self)
        # 260617-2: 텍스트 복사(블럭/페이지)·블럭설정·현재 페이지 인쇄(편집모드 무관)
        # 260618-1: 권한 없으면 비활성(복사 권한→복사·블럭, 인쇄 권한→현재 페이지 인쇄)
        can_copy = getattr(self, "_perm_can_copy", True)
        can_print = getattr(self, "_perm_can_print", True)
        act_copy = menu.addAction("텍스트 복사")          # 선택 블럭(없으면 페이지)
        act_copy.setEnabled(can_copy)
        act_sel = menu.addAction("블럭설정 후 텍스트 복사")  # 블럭설정 포인터로
        act_sel.setEnabled(can_copy)
        act_print1 = menu.addAction(f"현재 페이지 인쇄 (p.{page})")
        act_print1.setEnabled(can_print)
        menu.addSeparator()
        # 260618-27: 1단=‘2단 보기’(진입), 2단=현재 창 기준 ‘반대 창으로 복사’.
        #   1창(좌,active 0)→‘2창으로 복사’, 2창(우,active 1)→‘1창으로 복사’.
        act_to_dual = act_copy_other = None
        if getattr(self, "_split_on", False):
            act_copy_other = menu.addAction(
                "2창으로 복사" if self._active_pane == 0 else "1창으로 복사")
        else:
            act_to_dual = menu.addAction("2단 보기")
        menu.addSeparator()
        act_add = menu.addAction(f"책갈피 추가 (p.{page})") if edit else None
        # 260609-11(C1): 하이퍼링크 등록은 편집모드에서만
        act_hl = menu.addAction(f"하이퍼링크 등록… (p.{page})") if edit else None
        # 260609-14(D5): 편집모드 — 현재 페이지 숨김/해제
        act_hide = act_unhide = None
        if edit:
            st = self._ensure_page_meta_store()
            is_hidden = bool(st and st.is_hidden(cur, page - 1))
            if is_hidden:
                act_unhide = menu.addAction(f"페이지 숨김 해제 (p.{page})")
            else:
                act_hide = menu.addAction(f"페이지 숨김 (p.{page})")
        # 260611-78: 선/텍스트 통합 설정(아래 클립보드 삽입 밑에 배치)
        act_lt_cfg = None
        # 260611-15: 편집모드 — 이미지 삽입/모양/삭제
        act_img_del = None
        change_acts = {}
        _shapes = (("rect", "사각형"), ("round", "둥근 사각형"), ("circle", "원형"))
        if edit:
            menu.addSeparator()
            # 260611-73: 삽입 항목을 분할 컨트롤로 — 본문 클릭=현재 모양으로 즉시 삽입,
            #   오른쪽 ▼(옵션버튼=라디오) 클릭=삽입 모양 선택(툴버튼 MenuButtonPopup 과 동일 UX).
            self._add_insert_split(
                menu, "사진 파일 삽입",
                lambda: getattr(self, "_ins_file_shape", None)
                or getattr(self.main_view, "_img_shape", "rect") or "rect",
                lambda k: setattr(self, "_ins_file_shape", k),
                lambda: (setattr(self.main_view, "_img_shape",
                                 getattr(self, "_ins_file_shape", None)
                                 or getattr(self.main_view, "_img_shape", "rect") or "rect"),
                         self._insert_image_from_file()))
            self._add_insert_split(
                menu, "클립보드 삽입",
                lambda: getattr(self, "_ins_paste_shape", None)
                or getattr(self.main_view, "_img_shape", "rect") or "rect",
                lambda k: setattr(self, "_ins_paste_shape", k),
                lambda: (setattr(self.main_view, "_img_shape",
                                 getattr(self, "_ins_paste_shape", None)
                                 or getattr(self.main_view, "_img_shape", "rect") or "rect"),
                         self.main_view.paste_image_from_clipboard()))
            # 260611-78: '클립보드 삽입' 아래 — 선긋기/글쓰기 통합 설정(탭)
            act_lt_cfg = menu.addAction("선과 텍스트 입력 설정…")
            if self.main_view.has_selected_image():
                m_chg = menu.addMenu("선택 사진 모양 변경")
                for key, label in _shapes:
                    ca = m_chg.addAction(self._shape_icon(key), label)
                    ca.setCheckable(True)
                    change_acts[ca] = key
                act_img_del = menu.addAction("선택 이미지 삭제 (Del)")
        # 260611-78: 선택된 글상자 — 끝모양(지시선)·삭제만 (스타일 편집은 '선과 텍스트 입력 설정')
        act_txt_del = None
        tip_acts = {}
        sel = self.main_view.selected_text_stroke() if edit else None
        sel_is_leader = bool(sel and sel.get("leader"))
        if edit and sel is not None:
            menu.addSeparator()
            if sel_is_leader:
                m_tip = menu.addMenu("선택 지시선 끝 모양")
                for key, label in (("arrow", "뾰족한 화살표"), ("circle", "끝 원형"),
                                   ("plain", "일반 선")):
                    ta = m_tip.addAction(label); ta.setCheckable(True)
                    ta.setChecked(sel.get("tip", "arrow") == key)
                    tip_acts[ta] = key
            act_txt_del = menu.addAction("선택 글상자 삭제 (Del)")
        if menu.isEmpty():
            return
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        # 260618-27: 2단 보기 진입 / 반대 창으로 복사
        if act_to_dual is not None and chosen == act_to_dual:
            self._view_as_split(); return
        if act_copy_other is not None and chosen == act_copy_other:
            self._copy_pane_to(self._active_pane, 1 - self._active_pane); return
        # 260617-2: 텍스트 복사(블럭/페이지)·블럭설정·현재 페이지 인쇄
        if chosen == act_copy:
            self.main_view.copy_selection(); return
        if chosen == act_sel:
            self.main_view.arm_text_selection()
            self.status.showMessage(
                "블럭 좌상점을 누르고 우하점까지 드래그하면 그 영역 텍스트가 복사됩니다.", 5000)
            return
        if chosen == act_print1:
            self._print_pdf_pages(cur, [page - 1]); return
        if chosen is not None and chosen == act_lt_cfg:
            self._open_line_text_settings(); return
        if chosen in tip_acts:
            self.main_view.set_leader_tip(tip_acts[chosen]); return
        if chosen == act_txt_del:
            self.main_view.delete_selected_stroke(); return
        if chosen == act_add:
            self._prompt_add_bookmark(cur, page)
        elif chosen == act_hl:
            self._open_hyperlink_dialog(cur, page - 1)
        elif chosen is not None and chosen == act_hide:
            self._set_pages_hidden([page - 1], True)
        elif chosen is not None and chosen == act_unhide:
            self._set_pages_hidden([page - 1], False)
        elif chosen in change_acts:
            self.main_view.set_image_shape(change_acts[chosen])   # 선택 개체 모양 변경
        elif chosen is not None and chosen == act_img_del:
            self.main_view._img_delete_selected()

    def _add_insert_split(self, menu, text, get_shape, set_shape, do_insert):
        """260611-73: 컨텍스트 메뉴 안의 분할(삽입) 항목.
        본문(왼쪽) 클릭 = 현재 선택 모양으로 즉시 삽입,
        오른쪽 ▼ = 삽입 모양 옵션버튼(라디오: 사각형/둥근/원형) 선택.
        get_shape()->key, set_shape(key), do_insert() 를 콜백으로 받는다."""
        from PyQt6.QtWidgets import (QWidgetAction, QWidget, QHBoxLayout,
                                     QToolButton, QMenu, QSizePolicy)
        from PyQt6.QtGui import QActionGroup
        from PyQt6.QtCore import Qt as _Qt, QTimer
        _shapes = (("rect", "사각형"), ("round", "둥근 사각형"), ("circle", "원형"))
        cur = get_shape()
        wa = QWidgetAction(menu)
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 1, 6, 1); lay.setSpacing(2)
        main_btn = QToolButton(w)
        main_btn.setToolButtonStyle(_Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        main_btn.setText(text)
        main_btn.setIcon(self._shape_icon(cur))
        main_btn.setAutoRaise(True)
        main_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        main_btn.setToolTip(f"{text} — 클릭하면 선택된 모양으로 삽입 (모양은 오른쪽 ▼)")
        arrow = QToolButton(w)
        arrow.setText("▼")
        arrow.setAutoRaise(True)
        arrow.setToolTip("삽입 모양 선택")
        arrow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        sub = QMenu(arrow)
        grp = QActionGroup(sub); grp.setExclusive(True)
        for key, label in _shapes:
            a = sub.addAction(self._shape_icon(key), label)
            a.setCheckable(True); a.setChecked(key == cur)
            grp.addAction(a)

            def _pick(_chk=False, k=key):
                set_shape(k)
                main_btn.setIcon(self._shape_icon(k))
            a.triggered.connect(_pick)
        arrow.setMenu(sub)

        def _go():
            menu.close()                       # 컨텍스트 메뉴 닫고
            QTimer.singleShot(0, do_insert)    # 닫힌 뒤 삽입(파일 대화상자 등)
        main_btn.clicked.connect(_go)
        lay.addWidget(main_btn, 1)
        lay.addWidget(arrow, 0)
        wa.setDefaultWidget(w)
        menu.addAction(wa)
        return wa

    def _shape_icon(self, kind):
        """260611-15: 붙이는 모양 아이콘(사각형/둥근사각형/원형) 그려서 생성."""
        from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
        from PyQt6.QtCore import QRect, Qt as _Qt
        pm = QPixmap(20, 20); pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor("#333333"), 2)); p.setBrush(QColor(120, 170, 235))
        r = QRect(3, 3, 14, 14)
        if kind == "circle":
            p.drawEllipse(r)
        elif kind == "round":
            p.drawRoundedRect(r, 5, 5)
        else:
            p.drawRect(r)
        p.end()
        return QIcon(pm)

    def _open_text_style_dialog(self, idx=None, kind=None):
        """260611-76/77: 글쓰기/지시선 박스 설정 — 폰트·글자색·크기·박스선 on/off(스타일=색상버튼)·
        배경색(투명도)·정렬, 지시선이면 선 끝모양(화살표/원/직선, 아이콘).
        idx>=0 = 선택 박스 편집 / kind('text'|'leader') = 신규 박스 기본값 편집."""
        editing = idx is not None and idx >= 0
        if editing:
            st = self.main_view.selected_text_stroke()
            if st is None:
                return
            is_leader = bool(st.get("leader"))
        else:
            is_leader = (kind == "leader")
            st = self.main_view.text_defaults(is_leader)
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                                     QPushButton, QCheckBox, QDoubleSpinBox, QComboBox,
                                     QColorDialog, QDialogButtonBox, QSpinBox)
        from PyQt6.QtGui import QColor
        dlg = QDialog(self)
        _t = "지시선 글쓰기 박스" if is_leader else "글쓰기 박스"
        dlg.setWindowTitle(_t + (" 설정" if editing else " 기본 설정(신규)"))
        form = QFormLayout()
        state = {"color": st.get("color") or "#111111", "bg": st.get("bg") or "#fff7c0"}

        def _swatch(btn, col):
            c = QColor(col)
            yiq = (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000
            btn.setStyleSheet(f"background:{c.name()};color:{'#000' if yiq>=140 else '#fff'};")
            btn.setText(c.name())

        def _pick(key, btn):
            c = QColorDialog.getColor(QColor(state[key]), dlg, "색 선택")
            if c.isValid():
                state[key] = c.name(); _swatch(btn, state[key])

        # 폰트
        cmb_font = QComboBox(); cmb_font.addItems(["맑은 고딕", "굴림", "바탕", "돋움"])
        fam = st.get("family", "맑은 고딕")
        cmb_font.setCurrentIndex(max(0, cmb_font.findText(fam)))
        cb_bold = QCheckBox("굵게"); cb_bold.setChecked(bool(st.get("bold", False)))
        cb_italic = QCheckBox("기울임"); cb_italic.setChecked(bool(st.get("italic", False)))
        row_f = QHBoxLayout(); row_f.addWidget(cmb_font, 1)
        row_f.addWidget(cb_bold); row_f.addWidget(cb_italic)
        form.addRow("문자 폰트", self._wrap_row(row_f))

        # 글자색
        b_color = QPushButton(); _swatch(b_color, state["color"])
        b_color.clicked.connect(lambda: _pick("color", b_color))
        form.addRow("문자 색상", b_color)

        # 크기
        sp_size = QDoubleSpinBox(); sp_size.setRange(0.5, 15.0); sp_size.setSingleStep(0.2)
        sp_size.setSuffix(" %"); sp_size.setValue(float(st.get("size", 0.022)) * 100.0)
        form.addRow("문자 크기(페이지 대비)", sp_size)

        # 박스선 on/off (색·굵기·투명도는 색상버튼 스타일)
        cb_boxline = QCheckBox("적용 (색·굵기·투명도는 색상버튼 스타일)")
        cb_boxline.setChecked(bool(st.get("box_line", False)))
        form.addRow("텍스트 박스선", cb_boxline)

        # 배경색 + 투명도
        cb_bg = QCheckBox("적용"); cb_bg.setChecked(st.get("bg") is not None)
        b_bg = QPushButton(); _swatch(b_bg, state["bg"])
        b_bg.clicked.connect(lambda: _pick("bg", b_bg))
        sp_bga = QSpinBox(); sp_bga.setRange(0, 100); sp_bga.setSuffix(" %")
        sp_bga.setValue(int(st.get("bg_alpha", 100)))
        row_bg = QHBoxLayout(); row_bg.addWidget(cb_bg); row_bg.addWidget(b_bg, 1)
        row_bg.addWidget(sp_bga)
        form.addRow("텍스트 박스 배경", self._wrap_row(row_bg))

        # 정렬
        cmb_align = QComboBox(); cmb_align.addItems(["왼쪽", "가운데", "오른쪽"])
        cmb_align.setCurrentIndex(int(st.get("align", 0)))
        form.addRow("정렬", cmb_align)

        # 지시선 끝 모양 — 아이콘 토글 버튼
        tip_state = {"v": st.get("tip", "arrow")}
        tip_btns = {}
        if is_leader:
            row_tip = QHBoxLayout()

            def _set_tip(v):
                tip_state["v"] = v
                for k, b in tip_btns.items():
                    b.setChecked(k == v)
            for key, glyph, tipname in (("arrow", "→", "뾰족한 화살표"),
                                        ("circle", "●", "끝 원형"),
                                        ("plain", "—", "일반 선")):
                b = QPushButton(glyph); b.setCheckable(True); b.setFixedWidth(46)
                b.setToolTip(tipname)
                b.setChecked(tip_state["v"] == key)
                b.clicked.connect(lambda _=False, v=key: _set_tip(v))
                tip_btns[key] = b; row_tip.addWidget(b)
            row_tip.addStretch(1)
            form.addRow("선 끝모양", self._wrap_row(row_tip))

        lay = QVBoxLayout(dlg); lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        fields = {"family": cmb_font.currentText(), "color": state["color"],
                  "size": sp_size.value() / 100.0,
                  "bold": cb_bold.isChecked(), "italic": cb_italic.isChecked(),
                  "box_line": cb_boxline.isChecked(),
                  "bg": state["bg"] if cb_bg.isChecked() else None,
                  "bg_alpha": sp_bga.value(),
                  "align": cmb_align.currentIndex()}
        if is_leader:
            fields["tip"] = tip_state["v"]
        if editing:
            self.main_view.set_textbox_style(idx, **fields)
        else:
            self.main_view.set_text_defaults(is_leader, **fields)

    @staticmethod
    def _wrap_row(layout):
        from PyQt6.QtWidgets import QWidget
        w = QWidget(); layout.setContentsMargins(0, 0, 0, 0); w.setLayout(layout)
        return w

    def _insert_image_from_file(self):
        from PyQt6.QtWidgets import QFileDialog
        start = str(self._folder) if self._folder else ""
        fn, _ = QFileDialog.getOpenFileName(
            self, "삽입할 이미지 선택", start,
            "이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)")
        if fn:
            self.main_view.add_image_from_file(fn)

    def _clear_workspace(self, keep_panes: bool = False):
        """v1.6.0 G3: 새 폴더 로드 전 메인/검색결과 비우기.
        260618-21: keep_panes=True 면 두 뷰어 창과 썸네일을 **보존**(2단에서 다른 폴더를 열어도
        기존 창이 닫히지 않게) — 검색 결과만 비운다.
        """
        try:
            if not keep_panes:
                # 메인 뷰어 — 260606-8: 두 창 모두 비움
                for mv in self._mv:
                    if mv._doc is not None:
                        mv._doc.close()
                        mv._doc = None
                    mv.scene.clear()
                    mv._page_item = None
                    mv.spin_page.setMaximum(1)
                    mv.lbl_page_total.setText("/ 0")
                # 페이지 썸네일 — 260616-21: 리스트만 비우면 '동일 파일' 가드로 재채움이 안 됨 → 상태도 초기화.
                self.page_thumbs.list.clear()
                try:
                    if getattr(self.page_thumbs, "_doc", None) is not None:
                        self.page_thumbs._doc.close()
                except Exception:
                    pass
                self.page_thumbs._doc = None
                self.page_thumbs._doc_path = None
                self.page_thumbs._doc_mtime = None
                self._current_main = None
            # 검색 결과(폴더 바뀌면 항상 초기화)
            self.search_results.set_results("", [])
            self._last_results = []
        except Exception:
            pass

    def open_folder(self, folder: Path, pane: int = None):
        """260618-22: 폴더를 활성 창(2단)에 연다. 우측(pane 1)이면 하단 책갈피에 로드(좌측·패널 보존),
        좌측(pane 0)이면 기존처럼 상단 책갈피·워크스페이스 갱신."""
        folder = Path(folder)
        if pane is None:
            pane = self._active_pane if getattr(self, "_split_on", False) else 0
        self._cancel_active_indexing()
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        try:
            if pane == 1 and getattr(self, "_split_on", False):
                # 우측 창에 폴더 열기 — 좌측 창·상단 책갈피 보존, 하단에 로드
                self._set_active_pane(1)
                self._set_pane_folder(1, folder)      # 하단 트리 로드 + 표시 + 제목
                self.status.showMessage(f"우측 폴더 로드: {folder}", 2500)
                self._touch_recent_folder(str(folder))
                rfolder = folder
            else:
                self._clear_workspace(keep_panes=getattr(self, "_split_on", False))
                self._hyperlinks = None
                self._page_meta = None
                self._set_pane_folder(0, folder)      # 좌측/상단 트리 + 제목
                self.status.showMessage(f"폴더 로드: {folder}")
                order_map = self._build_bookmark_order(folder / "bookmarks.json")
                self.search_results.set_bookmark_order(order_map)
                self._refresh_search_scope()
                self._touch_recent_folder(str(folder))
                rfolder = folder
        finally:
            QApplication.restoreOverrideCursor()
        try:
            self._cancel_active_indexing()
            worker = IndexWorker(self._db_path, rfolder)
            worker.progress.connect(self._on_index_progress)
            worker.finished.connect(self._on_index_finished)
            worker.error.connect(lambda e: self.status.showMessage(f"인덱싱 오류: {e}"))
            self._start_index_worker(worker)
        except Exception:
            pass

    @staticmethod
    def _norm_path(p) -> str:
        """260616-3: 경로 비교용 정규화. 260628: 표준 `pathutil.norm_key` 위임(SOT §7.0)."""
        from viewer.pathutil import norm_key
        return norm_key(p)

    def _on_view_mode_changed(self, is_folder: bool, path: str) -> None:
        """260825: 책갈피창 파일↔폴더 모드 전환 시 검색 범위·인덱싱·제목 갱신.

        - 폴더 모드: 그 폴더 전체를 검색 범위로 확장하고 폴더를 인덱싱(폴더 전체 검색).
        - 파일 모드: 그 파일만 검색 범위·인덱싱.
        """
        try:
            p = Path(path)
            if is_folder:
                self._folder = p
                try:
                    order_map = self._build_bookmark_order(p / "bookmarks.json")
                    self.search_results.set_bookmark_order(order_map)
                except Exception:
                    pass
                self._refresh_search_scope()          # 트리=폴더 → 범위 확장
                try:
                    self._cancel_active_indexing()
                    worker = IndexWorker(self._db_path, p)
                    worker.progress.connect(self._on_index_progress)
                    worker.finished.connect(self._on_index_finished)
                    worker.error.connect(
                        lambda e: self.status.showMessage(f"인덱싱 오류: {e}"))
                    self._start_index_worker(worker)
                except Exception:
                    pass
            else:
                self._folder = p.parent
                self._refresh_search_scope()          # 트리=단일 → 그 파일만
                try:
                    self._cancel_active_indexing()
                    worker = IndexWorker(self._db_path, p.parent, single_file=p)
                    worker.error.connect(lambda e: None)
                    self._start_index_worker(worker)
                except Exception:
                    pass
            self._update_title()
        except Exception:
            pass

    def _startup_index_check(self) -> None:
        """260825: 시작 시 검색 색인이 비어 있으면(구 파괴적 마이그레이션 잔재) 재인덱싱.
        색인이 이미 채워져 있으면(정상) 아무 것도 하지 않음 — 불필요한 재인덱싱 회피."""
        try:
            from viewer.indexer import PdfIndex
            ix = PdfIndex(self._db_path)
            try:
                empty = ix.conn.execute("SELECT count(*) FROM pages_fts").fetchone()[0] == 0
            finally:
                ix.close()
            if not empty or not self._folder:
                return
            # 파일 모드면 그 파일만, 폴더 모드면 폴더 전체 재인덱싱
            file_mode = bool(getattr(self.bookmark_tree, "_is_file_mode", lambda: False)())
            if file_mode:
                cur = self.main_view.current_file() if self.main_view else None
                if cur and str(cur).lower().endswith(".pdf"):
                    w = IndexWorker(self._db_path, Path(cur).parent, single_file=Path(cur))
                    w.error.connect(lambda e: None)
                    self._start_index_worker(w)
            else:
                w = IndexWorker(self._db_path, self._folder)
                w.progress.connect(self._on_index_progress)
                w.finished.connect(self._on_index_finished)
                w.error.connect(lambda e: self.status.showMessage(f"인덱싱 오류: {e}"))
                self._start_index_worker(w)
        except Exception:
            pass

    def _refresh_search_scope(self) -> None:
        """260616-3: 검색 범위를 현재 책갈피 트리에 표시된 파일들로 한정.
        파일이 없으면 None(전체 인덱스 검색)."""
        try:
            paths = self.bookmark_tree.all_file_paths()
        except Exception:
            paths = []
        self._search_scope = {self._norm_path(p) for p in paths} if paths else None

    def _build_bookmark_order(self, json_path: Path) -> dict:
        if not json_path.exists():
            return {}
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        order: dict = {}
        idx = [0]

        def walk(nodes, base: Path):
            for n in nodes:
                f = n.get("file")
                if f:
                    full = str((base / f).resolve())
                    if full not in order:
                        order[full] = idx[0]
                        idx[0] += 1
                walk(n.get("children", []), base)

        walk(data.get("bookmarks", []), json_path.parent)
        return order

    def _touch_recent_folder(self, path_str: str):
        if path_str in self._recent_folders:
            self._recent_folders.remove(path_str)
        self._recent_folders.insert(0, path_str)
        self._recent_folders = self._recent_folders[: self.MAX_RECENT_FOLDERS]
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self.menu_recent.clear()
        if not self._recent_folders:
            a = QAction("(최근 폴더 없음)", self)
            a.setEnabled(False)
            self.menu_recent.addAction(a)
            return
        for p in self._recent_folders:
            act = QAction(p, self)
            act.triggered.connect(lambda _checked=False, pp=p: self.open_folder(Path(pp)))
            self.menu_recent.addAction(act)

    def _cancel_active_indexing(self):
        """260611-89: 진행 중인 모든 인덱싱 작업에 중단 요청(폴더/파일 전환 시)."""
        for w in list(self._index_workers):
            try:
                w.request_cancel()
            except Exception:
                pass
        self._index_workers = []

    def _start_index_worker(self, worker):
        """260611-89: 이전 인덱싱을 취소하고 새 인덱싱 시작(겹치지 않게)."""
        self._cancel_active_indexing()
        self._index_workers.append(worker)

        def _done(w=worker):
            if w in self._index_workers:
                self._index_workers.remove(w)
        worker.finished.connect(_done)
        run_in_thread(worker, self._thread_keep)

    def action_reindex(self):
        if not self._folder:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.showMessage("인덱싱 준비...")
        worker = IndexWorker(self._db_path, self._folder)
        worker.progress.connect(self._on_index_progress)
        worker.finished.connect(self._on_index_finished)
        worker.error.connect(lambda e: self.status.showMessage(f"인덱싱 오류: {e}"))
        self._start_index_worker(worker)

    def _on_index_progress(self, done, total, name):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        self.status.showMessage(f"인덱싱 {done}/{total} - {name}")

    def _on_index_finished(self):
        self.progress.setVisible(False)
        self.status.showMessage("인덱싱 완료", 3000)
        # 260829 P2(태그 SOT §8.2): 인덱싱 직후 자동 부여 — 본문이 index.db 에 막
        # 들어간 시점이라 추가 I/O 가 없다. 실패해도 인덱싱 결과에는 영향 없음.
        try:
            QTimer.singleShot(400, self._start_autotag_scan)
        except Exception:
            pass

    # ── 태그 자동 부여 파이프라인 (260829 P2 — 태그 SOT §8.2·§8.5) ─────────
    def _start_autotag_scan(self, force: bool = False):
        """전 파일 태그·연도 계산 워커 시작. force=메뉴 '다시 계산'(§3.5-C)."""
        if not self._prefs.get("auto_tag_enabled", True) and not force:
            return                                    # §3.5 각주 — 끄면 제안만(다이얼로그)
        if getattr(self, "_autotag_worker", None) is not None:
            # 260830 최종검토: 실행 중 새 요청(폴더 전환 등)은 버리지 않고 재큐잉 —
            # 끝나면 한 번 다시 돈다(새 폴더가 스캔에서 빠지는 틈 방지).
            self._autotag_rescan = True
            return
        store = getattr(self.bookmark_tree, "_tags", None)
        if store is None:
            return
        try:
            paths = [p for p in self.bookmark_tree.all_file_paths()
                     if str(p).lower().endswith(".pdf")]
        except Exception:
            paths = []
        if not paths:
            return
        # 스냅샷(워커는 store 를 만지지 않는다 — 스레드 경합 회피)
        tagged = {}
        fp_missing = set()
        for p in paths:
            k = store._key(p)
            v = store._data.get(k)
            if v is None:
                continue
            for t in store.get_manual(p):             # 프로파일 학습은 수동 태그만(§3.1 시범 표본 과적합 방지 완화)
                tagged.setdefault(t, []).append(str(p))
            if isinstance(v, dict) and not v.get("fp"):
                fp_missing.add(k)
        from datetime import date
        from viewer.auto_tag import load_rules
        from viewer.workers import AutoTagWorker, run_in_thread
        kw_skip = {store._key(p) for p in paths if store.kw_edited(p)}  # §9.1
        w = AutoTagWorker(self._db_path, paths, tagged,
                          known_tags=store.all_tags(), rules=load_rules(),
                          today_year=date.today().year,
                          store_keys=set(store._data.keys()),
                          fp_missing_keys=fp_missing, kw_skip_keys=kw_skip)
        self._autotag_worker = w
        w.progress.connect(lambda d, t, n: self.status.showMessage(
            f"태그 계산 {d}/{t}", 1500))
        w.finished.connect(self._on_autotag_finished)
        w.error.connect(self._on_autotag_error)
        run_in_thread(w, self._thread_keep)

    def _on_autotag_error(self, msg):
        self._autotag_worker = None
        self.status.showMessage(f"태그 계산 오류: {msg}", 4000)
        self._autotag_maybe_rescan()

    def _autotag_maybe_rescan(self):
        """실행 중 들어온 재요청 처리(폴더 전환 등 — 260830 최종검토)."""
        if getattr(self, "_autotag_rescan", False):
            self._autotag_rescan = False
            QTimer.singleShot(200, self._start_autotag_scan)

    def _on_autotag_finished(self, results, stats):
        """워커 결과를 UI 스레드에서 적용 — 재연결(§6.1)·자동 부여(§5.6)·연도(§9.4).
        ★ 일괄 적용 전 백업 필수(§6) — 실패하면 아무것도 쓰지 않는다."""
        w = self._autotag_worker
        self._autotag_worker = None
        # 260830 P3: 세션 제안 캐시(§8.1) — 편집 다이얼로그의 즉석 제안이 이걸 쓴다
        if w is not None and getattr(w, "profiles", None) is not None:
            self._autotag_ctx = (w.profiles, w.df, w.n_docs)
        store = getattr(self.bookmark_tree, "_tags", None)
        if store is None or not results:
            return
        if not store.backup():
            self.status.showMessage("태그 백업 실패 — 자동 부여를 건너뜀(§6)", 5000)
            return
        n_auto = n_moved = 0
        with store.bulk():
            for r in results:
                p = r["path"]
                if r.get("fp"):
                    st = store.rehome_missing(p, fp=r["fp"], size=r.get("size"))
                    if st == "moved":
                        n_moved += 1
                    elif st == "exists":
                        store.set_fp(p, r["fp"], r.get("size") or 0)
                if r["auto"]:
                    tags = [t for t, _ in r["auto"]]
                    store.set_auto(p, tags,
                                   conf={t: s for t, s in r["auto"]})
                    if store.get_auto(p):
                        n_auto += 1
                if r.get("year"):
                    store.set_year(p, r["year"], r.get("year_src", ""),
                                   r.get("year_conf", 0.0))
                if r.get("keywords") is not None:      # §9.1 — kw_edited 는 워커가 생략
                    store.set_keywords(p, r["keywords"])
        # §5.4-5: 신규 태그 후보 적립(붙이지 않는다 — 검토 화면에서 채택)
        try:
            from viewer.tag_store import merge_candidates
            if stats.get("candidates"):
                merge_candidates(stats["candidates"])
        except Exception:
            pass
        try:
            self.bookmark_tree.refresh_tag_labels()
        except Exception:
            pass
        msg = (f"태그 자동 부여: {stats.get('total', 0)}개 검토, "
               f"{n_auto}개 파일에 부여")
        if n_moved:
            msg += f", 이동 재연결 {n_moved}건"
        self.status.showMessage(msg, 5000)
        self._autotag_first_summary(stats, n_auto)
        self._autotag_maybe_rescan()

    def _autotag_first_summary(self, stats, n_auto):
        """§8.2 첫 실행 요약 — 1회 모달. 무엇을 '안 했는지'도 말한다(조용한 누락 금지)."""
        if self._prefs.get("autotag_summary_shown", False):
            return
        self._prefs["autotag_summary_shown"] = True
        try:
            self._save_settings_now()
        except Exception:
            pass
        try:
            box = QMessageBox(self)
            box.setWindowTitle("태그 자동 부여")
            box.setText(
                f"{stats.get('total', 0)}개 파일을 살펴봤습니다.\n\n"
                f"· {n_auto}개 파일에 태그를 붙였습니다"
                f" (기존 태그 {stats.get('known_tags', 0)}종 사용)\n"
                f"· 새 태그 후보 {stats.get('new_candidates', 0)}건은 붙이지 않았습니다\n\n"
                "자동 태그는 목록에 ·# 로 표시되며, 도구 메뉴에서 언제든 "
                "되돌리거나 전체 삭제할 수 있습니다.")
            undo = box.addButton("되돌리기", QMessageBox.ButtonRole.DestructiveRole)
            review = None
            if stats.get("new_candidates"):
                review = box.addButton("새 태그 후보 검토…",
                                       QMessageBox.ButtonRole.ActionRole)
            box.addButton("확인", QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            if box.clickedButton() is undo:
                self._autotag_undo()
            elif review is not None and box.clickedButton() is review:
                self._autotag_review_candidates()
        except Exception:
            pass

    def _autotag_review_candidates(self):
        """§8.5 새 태그 후보 검토 — 채택하면 근거 파일들에 auto 부여(어휘 편입),
        무시하면 전역 재적립 금지."""
        store = getattr(self.bookmark_tree, "_tags", None)
        if store is None:
            return
        try:
            from viewer.widgets.tag_batch_dialog import CandidateReviewDialog
            dlg = CandidateReviewDialog(store, self)
            dlg.exec()
            self.bookmark_tree.refresh_tag_labels()
        except Exception:
            pass

    def _autotag_suggest_single(self, path):
        """260830 P3(§8.1): 편집 다이얼로그의 즉석 제안 — 세션 캐시(프로파일·DF)로
        해당 파일 1개만 동기 계산(§7 1초 예산 내). 캐시 없으면 None(구획 숨김)."""
        ctx = getattr(self, "_autotag_ctx", None)
        if ctx is None:
            return None
        try:
            from viewer.auto_tag import extract_features, load_rules, suggest_tags
            from viewer.indexer import PdfIndex
            profiles, df, n_docs = ctx
            texts = None
            try:
                ix = PdfIndex(self._db_path)
                try:
                    texts = ix.page_texts(str(path)) or None
                finally:
                    ix.close()
            except Exception:
                pass
            f = extract_features(path, page_texts=texts)
            store = getattr(self.bookmark_tree, "_tags", None)
            known = store.all_tags() if store else []
            return suggest_tags(f, profiles, df, n_docs,
                                known_tags=known, rules=load_rules())
        except Exception:
            return None

    def _autotag_undo(self):
        """§8.5 직전 일괄 부여 되돌리기 — file_tags.bak.json 복원."""
        store = getattr(self.bookmark_tree, "_tags", None)
        if store is None:
            return
        ok = store.restore_backup()
        try:
            self.bookmark_tree.refresh_tag_labels()
        except Exception:
            pass
        self.status.showMessage("직전 자동 부여를 되돌렸습니다" if ok
                                else "되돌릴 백업이 없습니다", 4000)

    def _autotag_clear_all(self):
        """§8.5 자동 태그 전체 삭제 — manual 무손실."""
        store = getattr(self.bookmark_tree, "_tags", None)
        if store is None:
            return
        store.clear_auto()
        try:
            self.bookmark_tree.refresh_tag_labels()
        except Exception:
            pass
        self.status.showMessage("자동 태그를 전부 지웠습니다(수동 태그는 유지)", 4000)

    def _autotag_prune_missing(self):
        """§8.5·§6.1 없는 파일 항목 정리 — ★ 개수 확인 후에만(앱이 임의로 지우지 않는다)."""
        store = getattr(self.bookmark_tree, "_tags", None)
        if store is None:
            return
        n = store.count_missing()
        if n == 0:
            QMessageBox.information(self, "항목 정리", "없는 파일 항목이 없습니다.")
            return
        r = QMessageBox.question(
            self, "항목 정리",
            f"디스크에 없는 파일의 태그 항목 {n}건을 지울까요?\n"
            "(휴지통 복원 예정인 파일이 있다면 지우지 마세요 — 복원 시 태그가 살아납니다.)")
        if r == QMessageBox.StandardButton.Yes:
            removed = store.prune_missing()
            self.status.showMessage(f"{removed}건 정리", 4000)

    def _index_single_file(self, path) -> None:
        """260606-4: 새로 만든/편집한 PDF 1개를 백그라운드 인덱싱 → 검색에 포함."""
        try:
            p = Path(path)
            if not p.exists() or p.suffix.lower() != ".pdf":
                return
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            self.status.showMessage(f"인덱싱: {p.name} ...")
            worker = IndexWorker(self._db_path, p.parent, single_file=p)
            worker.progress.connect(self._on_index_progress)
            worker.finished.connect(self._on_index_finished)
            worker.error.connect(lambda e: self.status.showMessage(f"인덱싱 오류: {e}"))
            self._start_index_worker(worker)
        except Exception:
            pass

    # ===== 검색 ========================================================
    def _set_content_search(self, panel):
        """260623: 메인 검색바의 검색 대상을 우측 패널(건설기준/법령/특허) 본문으로 전환/복귀.
        panel=None 이면 PDF 내용 검색으로 복귀(플레이스홀더 원복)."""
        self._content_panel = panel
        self._content_query = ""
        try:
            label = getattr(panel, "CONTENT_LABEL", "") if panel is not None else ""
            self.search_bar.set_context_label(label)
        except Exception:
            pass
        if panel is None:                       # 우측창 닫힘 → 슬라이드 오버레이도 닫기
            ov = getattr(self, "_cf_overlay", None)
            if ov is not None and ov.isVisible():
                ov.close_overlay()

    def _focus_search(self):
        """260708: Ctrl+F — 우측 패널(건설기준/법령/특허) 열려 있으면 슬라이드 오버레이,
        아니면 PDF 검색바 포커스. 260825: 검색 영역이 숨겨져 있으면 먼저 표시."""
        if self._content_panel is not None:
            self._open_content_find()
            return
        try:
            if not self.search_bar.isVisible():
                self._vm_search()           # 검색 영역이 안 보이면 표시
        except Exception:
            pass
        self.search_bar.focus_search()

    def _open_content_find(self, seed=None):
        """우측 패널 본문 검색 오버레이(슬라이드)를 연다 — 검색 입력·개수·이동·결과 목록.
        우측창이 열려 있을 때의 유일한 검색 UI(왼쪽 검색패널은 띄우지 않음)."""
        if self._content_panel is None:
            return
        if getattr(self, "_cf_overlay", None) is None:
            from viewer.widgets.content_find_overlay import ContentFindOverlay
            self._cf_overlay = ContentFindOverlay(self.centralWidget() or self)
        q = seed if seed is not None else self.search_bar.current_query()
        self._cf_overlay.open_for(self._content_panel, seed_query=q)

    def action_search(self, query: str):
        # 260708: 우측 패널(건설기준/법령/특허) 열려 있으면 슬라이드 오버레이로만 그 본문 검색
        if self._content_panel is not None:
            self._content_query = query
            self._open_content_find(query)
            return
        if not self._folder:
            self.status.showMessage("폴더를 먼저 여세요.")
            return
        self.status.showMessage(f"검색 중: {query!r}")
        # 260828: 검색 범위(책갈피창 파일 목록)를 SQL 로 전달 — 영구(다중 폴더) 캐시에서
        #   LIMIT 이 다른 폴더 결과로 채워지지 않게. 없으면 전체.
        try:
            scope_paths = self.bookmark_tree.all_file_paths() or None
        except Exception:
            scope_paths = None
        worker = SearchWorker(self._db_path, query, paths=scope_paths)
        worker.finished.connect(self._on_search_finished)
        worker.error.connect(lambda e: self.status.showMessage(f"검색 오류: {e}"))
        run_in_thread(worker, self._thread_keep)
        self.main_view.set_query(query)

    def _on_search_finished(self, query: str, results: list):
        # 260616-3: 검색 결과를 현재 책갈피 목록(파일)으로 한정.
        if self._search_scope is not None:
            scope = self._search_scope
            results = [r for r in results
                       if self._norm_path(r.file_path) in scope]
        self._last_results = list(results)
        # 260827: 책갈피창 파일 시각 순서를 검색 결과 '책갈피 순' 정렬에 반영(폴더모드 포함)
        try:
            files = (self.bookmark_tree.ordered_pdf_files()
                     or self.bookmark_tree.all_file_paths() or [])
            self.search_results.set_bookmark_order({p: i for i, p in enumerate(files)})
        except Exception:
            pass
        self.search_results.set_results(query, results)
        self.status.showMessage(f"검색 완료: {len(results)}개 페이지", 3000)
        # 260827: 현재 파일의 현재 페이지 기준 '앞(이전 페이지)에서 가장 가까운' 결과를 선택·이동
        self._auto_select_search_result(results)

    def _auto_select_search_result(self, results: list) -> None:
        """검색 직후, 현재 본문 파일의 현재 페이지 기준으로 앞쪽(이전 페이지)에서 가장 가까운
        결과를 자동 선택하고 그 페이지로 이동. 현재 파일 결과가 없으면 표시 순서상 첫 결과."""
        if not results:
            return
        try:
            cur = self.main_view.current_file() if self.main_view else None
            cur_page = self.main_view.current_page() if self.main_view else 0
        except Exception:
            cur, cur_page = None, 0
        target = None
        if cur:
            ncur = self._norm_path(cur)
            same = [r for r in results if self._norm_path(r.file_path) == ncur]
            if same:
                before = [r for r in same if r.page_index <= cur_page]
                target = (max(before, key=lambda r: r.page_index) if before
                          else min(same, key=lambda r: r.page_index))
        if target is None:
            disp = self.search_results.get_displayed_results()
            target = disp[0] if disp else results[0]
        try:
            self.search_results.select_and_activate(target.file_path, target.page_index)
        except Exception:
            pass

    def action_export_search_excel(self):
        results = self.search_results.get_displayed_results()
        if not results:
            QMessageBox.information(self, "안내", "검색 결과가 없습니다.")
            return
        try:
            from openpyxl import Workbook
        except ImportError:
            QMessageBox.warning(self, "openpyxl 필요",
                "엑셀 내보내기에 openpyxl 패키지가 필요합니다.\npip install openpyxl")
            return
        # M5: 파일명에 datetime 접두
        prefix = _dt.datetime.now().strftime("%y%m%d_%H%M_")
        default = f"{prefix}search_results.xlsx"
        out, _ = QFileDialog.getSaveFileName(self, "엑셀로 저장", default, "Excel (*.xlsx)")
        if not out:
            return
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "검색결과"
            ws.append(["파일", "페이지", "매치수", "스니펫"])
            for r in results:
                ws.append([r.file_name, r.page_index + 1, r.match_count, r.snippet])
            for col, w in zip("ABCD", [40, 10, 10, 80]):
                ws.column_dimensions[col].width = w
            wb.save(out)
            self.status.showMessage(f"엑셀 저장: {out}", 4000)
        except Exception as e:
            QMessageBox.warning(self, "엑셀 저장 실패", str(e))

    def _on_search_screenshot_requested(self):
        """v1.6.1 S5 / v1.6.2: 검색결과 리스트의 모든 매치 페이지를 일괄 스크린샷.

        v1.6.2 변경:
         - 결과 개수가 `screenshot_max` 한도를 초과하면 한도를 자동으로 확장
           (현재 보유 카드 + 결과 개수 ≥ 한도가 되도록).
         - 직전 메인 push (히스토리) 로직 제거.
        """
        results = self.search_results.get_displayed_results()
        if not results:
            QMessageBox.information(self, "안내", "검색 결과가 없습니다.")
            return

        needed = self.shot_strip.list.count() + len(results)
        current_max = self.shot_strip.max_items()
        if needed > current_max:
            new_max = max(needed, current_max + len(results))
            self._prefs["screenshot_max"] = int(new_max)
            self.shot_strip.set_max_items(new_max)
            self.status.showMessage(
                f"스크린샷 한도를 {current_max} → {new_max} 로 자동 확장", 4000
            )

        ret = QMessageBox.question(
            self, "일괄 캡쳐",
            f"검색 결과 {len(results)} 페이지를 모두 스크린샷합니까?\n"
            "(시간이 걸릴 수 있습니다.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        self.status.showMessage(f"일괄 캡쳐 시작 ({len(results)} 페이지)")
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        # v1.6.6: 결과를 만든 실제 검색어를 전달해야 형광펜(D2/C1)이 적용됨.
        q = self.search_results.current_query()
        try:
            for i, r in enumerate(results, 1):
                item = HistoryItem(r.file_path, r.page_index, q, "search")
                self._load_main(item)
                # 렌더가 끝나길 잠시 기다리고 캡처
                QApplication.processEvents()
                self.action_screenshot()
                if i % 5 == 0:
                    self.status.showMessage(f"일괄 캡쳐 {i}/{len(results)}")
                    QApplication.processEvents()
            self.status.showMessage(f"일괄 캡쳐 완료: {len(results)} 장", 5000)
        finally:
            QApplication.restoreOverrideCursor()

    # ===== 메인 전환 (v1.6.2 — 히스토리 push 로직 제거) ================
    def _capture_main_state(self) -> Optional[HistoryItem]:
        """현재 메인 뷰어 상태를 HistoryItem 으로 스냅샷 (last_main 저장용)."""
        if self._current_main is None:
            return None
        cur_page = self.main_view.current_page() if self.main_view.current_file() else (
            self._current_main.page_index or 0)
        return HistoryItem(
            file_path=self._current_main.file_path,
            page_index=cur_page,
            query=self._current_main.query,
            origin=self._current_main.origin,
            label=self._current_main.label,
        )

    def _load_main(self, item: HistoryItem):
        """메인 뷰어에 항목 로드 (BusyCursor)."""
        # 260609-23(J2): 편집모드 미저장 변경 + 다른 파일 이동 → 저장 확인
        try:
            if self._in_edit() and self._edit_snap is not None and self._edit_dirty:
                cur = self.main_view.current_file() if self.main_view else None
                tgt = str(Path(item.file_path))
                if cur and str(Path(cur)) != tgt:
                    choice = self._confirm_edit_save(switching=True)
                    if choice == "cancel":
                        return                      # 이동 취소(현재 파일 유지)
                    if choice == "save":
                        self._commit_edit()
                    else:
                        self._restore_edit()
                    self._edit_snap = None
                    self._snapshot_edit()           # 새 파일 편집 기준 재설정
        except Exception:
            pass
        # 260606: 다른 파일을 열면 기존 읽기(본문/단어장 자동읽기) 중지
        try:
            new_path = str(Path(item.file_path))
            if self._study_pdf and str(self._study_pdf) != new_path:
                if getattr(self, "read_aloud", None) and self.read_aloud.is_active():
                    self.read_aloud.stop()
                if self.study_panel.is_playing():
                    self.study_panel.set_playing(False)
                    self._stop_autoread()
        except Exception:
            pass
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        self.status.showMessage(f"로딩 중: {Path(item.file_path).name}")
        try:
            path = Path(item.file_path)
            if path.suffix.lower() == ".pdf":
                ok = self.main_view.load_document(
                    path, page_index=item.page_index or 0, query=item.query
                )
                if ok is False:                  # 260611-64: 암호 입력 취소 → 기존 화면 유지
                    self.status.showMessage("암호 입력이 취소되었습니다.", 2500)
                    return
                self.page_thumbs.load_document(path)
                self._study_pdf = path           # 단어장 컨텍스트
                self._refresh_study_panel(item.page_index or 0)
            else:
                self.main_view.load_image(path)
                self.page_thumbs.list.clear()
                try:
                    self.page_thumbs.title.setText(self.page_thumbs._format_title(path.name))
                except Exception:
                    pass
            self._current_main = item
            self.status.showMessage(f"로드 완료: {path.name}", 2500)
            self._update_title()                               # 260825: 현재 파일명 제목 반영
            self._refresh_page_hyperlinks(self._active_pane)   # 260609-3
            if path.suffix.lower() == ".pdf":
                self._refresh_hidden_ui(str(path))             # 260609-14(D5)
                self._push_nav_filter()                        # 260609-26: 필터 페이지 제한
                # 260609-27: 책갈피가 필터 밖 페이지면 아래쪽 첫 보이는 페이지로 스냅(+책갈피 동기화)
                mv = self.main_view
                if (mv and mv._nav_pages
                        and mv._current_page not in set(mv._nav_pages)):
                    mv.go_to_page(mv._current_page)
            self._apply_doc_permissions()              # 260618-1: 권한 기반 UI 활성/비활성
            # 260618-23: 책갈피 트리(상=좌/하=우) 표시/숨김만 갱신. **폴더는 바꾸지 않음** —
            #   상단 트리에서 하위폴더 파일을 클릭해도 그 창의 폴더(=열었던 폴더)는 유지.
            #   폴더 변경은 '폴더/파일 열기'(open_folder/open_pdf)에서만 일어남.
            self._sync_right_pane_bookmark()
        finally:
            QApplication.restoreOverrideCursor()

    def _on_bookmark_activated(self, file_path: str, page_index: int):
        # 260618-22: 상단 책갈피 → 좌측 창(2단이면 좌측 활성화 후 로드)
        if getattr(self, "_split_on", False):
            self._set_active_pane(0)
        self._load_main(HistoryItem(file_path, page_index, "", "bookmark"))

    def _on_bookmark_activated_right(self, file_path: str, page_index: int):
        """260618-22: 하단 책갈피 → 우측 창에 열기."""
        self._set_active_pane(1)
        self._load_main(HistoryItem(file_path, page_index, "", "bookmark"))

    def _on_file_password_entered(self, file_path: str):
        """260618-1: 책갈피창 우클릭 '암호 입력' 성공 — 그 파일이 현재 열려 있으면
        새 암호(권한)로 다시 로드해 권한 기반 UI 활성/비활성을 갱신."""
        try:
            cur = self.main_view.current_file() if self.main_view else None
            if cur and str(Path(cur)) == str(Path(file_path)):
                page = self.main_view._current_page if self.main_view else 0
                self._load_main(HistoryItem(file_path, page, "", "bookmark"))
            else:
                self._apply_doc_permissions()
        except Exception:
            pass

    def _apply_doc_permissions(self):
        """260618-1: 현재 문서의 권한(permissions)에 따라 인쇄·편집·복사·스크린샷·병합 UI
        활성/비활성. 비암호화·전체권한 문서는 모두 허용. 권한 정보가 없으면 허용."""
        can_print = can_copy = can_modify = True
        try:
            mv = self.main_view
            cur = mv.current_file() if mv else None
            if cur and str(cur).lower().endswith(".pdf") and getattr(mv, "_doc", None) is not None:
                import fitz
                live = mv._doc.doc
                perm = int(getattr(live, "permissions", -1))
                if perm != -1:
                    can_print = bool(perm & fitz.PDF_PERM_PRINT)
                    can_copy = bool(perm & fitz.PDF_PERM_COPY)
                    can_modify = bool(perm & fitz.PDF_PERM_MODIFY)
        except Exception:
            can_print = can_copy = can_modify = True
        self._perm_can_print = can_print
        self._perm_can_copy = can_copy
        self._perm_can_modify = can_modify
        # 인쇄
        try:
            self._sc_act_print.setEnabled(can_print)
        except Exception:
            pass
        # 편집(책갈피 편집)
        try:
            self.bookmark_tree.btn_edit.setEnabled(can_modify)
            # 260822: 시작 시 1회 — 설정의 '시작 모드'가 편집이면 편집모드로 진입
            if (can_modify and not getattr(self, "_open_mode_applied", False)
                    and self._prefs.get("open_edit_mode", True)
                    and not self.bookmark_tree.is_edit_mode()):
                self._open_mode_applied = True
                self.bookmark_tree.btn_edit.setChecked(True)
            elif can_modify:
                self._open_mode_applied = True
        except Exception:
            pass
        # 스크린샷·스크린샷 PDF — 내용 복사(추출) 권한 기준
        for b in (getattr(self, "_btn_shot", None), getattr(self, "_btn_shot_pdf", None)):
            if b is not None:
                try:
                    b.setEnabled(can_copy)
                except Exception:
                    pass
        # PDF 병합 — 변경(조립) 권한 기준 (툴바 버튼 + 책갈피창 우클릭 병합)
        b = getattr(self, "_btn_merge", None)
        if b is not None:
            try:
                b.setEnabled(can_modify)
            except Exception:
                pass
        try:
            self.bookmark_tree.set_merge_allowed(can_modify)
        except Exception:
            pass
        # 텍스트 복사(Ctrl+C·우클릭) — 메인 뷰에 복사 허용 여부 전달
        try:
            if hasattr(self.main_view, "set_copy_allowed"):
                self.main_view.set_copy_allowed(can_copy)
        except Exception:
            pass

    def _on_file_boundary(self, direction: int, idx: int):
        """260609-2: 마지막/첫 페이지 경계에서 책갈피창의 다음/이전 파일로 이동.

        설정 `cross_file_nav` 가 켜졌을 때만 동작. 다음→새 파일 첫 페이지,
        이전→새 파일 마지막 페이지(과대 인덱스를 go_to_page 가 클램프).
        260609-28: 중첩 책갈피(챕터 그룹 밑 파일 리프)도 포함하도록
        ordered_pdf_files() 사용 — 최상위만 보던 all_file_paths() 는 중첩 분할본에서
        현재 파일을 못 찾아 경계 이동이 동작하지 않았다. 새 파일은 현재 필터 상태로
        열리고(_load_main→_push_nav_filter), 필터 밖 끝페이지는 보이는 페이지로 스냅된다.
        """
        if idx != self._active_pane:
            return
        if not self._prefs.get("cross_file_nav", False):
            return
        try:
            mv = self._mv[idx]
            cur = mv.current_file()
            if not cur:
                return
            files = self.bookmark_tree.ordered_pdf_files() or []
            if not files:
                return
            norm = [str(Path(f)) for f in files]
            cur_s = str(Path(cur))
            if cur_s not in norm:
                return
            j = norm.index(cur_s) + (1 if direction > 0 else -1)
            if j < 0 or j >= len(files):
                return
            target = files[j]
            page = 0 if direction > 0 else 10 ** 9   # 다음=첫장 / 이전=끝장(클램프)
            self._on_bookmark_activated(target, page)
            self.status.showMessage(
                f"{'다음' if direction > 0 else '이전'} 파일: {Path(target).name}", 2000)
        except Exception:
            pass

    # ===== 260609-4 (D): 발표 전체화면 보기 ==============================
    def _open_presentation(self):
        """현재 활성 창의 PDF·페이지를 전체화면 발표 창으로 연다(F5)."""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or not str(cur).lower().endswith(".pdf"):
            QMessageBox.information(self, "안내", "먼저 PDF를 표시하세요.")
            return
        # 260611-2: 편집모드면 '저장 여부 처리(저장/되돌리기/계속편집)' 후 곧바로 전체화면 실행.
        #   (기존: 처리만 하고 종료) — '계속 편집' 으로 취소되면 발표는 띄우지 않음.
        if self.bookmark_tree.is_edit_mode():
            try:
                self.bookmark_tree.btn_edit.setChecked(False)   # _on_edit_mode_toggled 가 저장 확인
            except Exception:
                pass
            if self.bookmark_tree.is_edit_mode():
                return                       # 사용자가 '계속 편집' 선택 → 발표 취소
        from viewer.widgets.presentation import PresentationWindow, DEFAULT_POINTERS
        page = self.main_view.current_page()
        pointers = self._prefs.get("presentation_pointers") or DEFAULT_POINTERS
        active = int(self._prefs.get("presentation_pointer_active", 0))
        overlap = int(self._prefs.get("presentation_overlap_pct", 10))
        topbar_h = int(self._prefs.get("presentation_topbar_h", 64))
        self._present = PresentationWindow(cur, page, self,
                                           pointers=pointers, pointer_active=active,
                                           overlap_pct=overlap,
                                           sibling_resolver=self._presentation_sibling,
                                           hyperlink_resolver=self._presentation_hyperlinks,
                                           topbar_h=topbar_h,
                                           bookmark_resolver=self._presentation_bookmarks,
                                           crop_resolver=self._crop_for,
                                           hidden_resolver=self._hidden_for,
                                           rotation_resolver=self._rotation_for,
                                           pens=self._draw_pens(),   # 260611-2: 본문과 공유 5펜
                                           pen_active=int(self._prefs.get("presentation_pen_active", 0)),
                                           pen_keys=self._draw_pen_keys(),   # 260611-3: 본문과 공유 펜 단축키

                                           rec_keys=(self._prefs.get("recording_keys") or None),
                                           pen_straight=bool(self._prefs.get("presentation_pen_straight", True)),
                                           eraser_widths=self._draw_eraser_widths(),   # 260611-2: 공유
                                           line_mode=int(self._prefs.get("draw_line_mode", 0)),   # 260611-4
                                           highlight_alpha=self._draw_highlight_alpha(),
                                           timer_cfg=self._prefs.get("presentation_timer"))  # 260611-19
        self._present.splitModeChanged.connect(self._on_present_split_changed)
        self._present.cropSettingsRequested.connect(self._on_crop_settings)
        self._present.penChanged.connect(self._on_pen_changed)
        self._present.penSettingsRequested.connect(self._on_pen_settings)
        self._present.penStraightChanged.connect(self._on_pen_straight_changed)
        self._present.lineModeChanged.connect(self._on_line_mode_changed)   # 260611-4: 공유
        self._present.applyDrawingsRequested.connect(self._on_apply_presentation_drawings)  # I4
        self._present.timerConfigChanged.connect(self._on_pres_timer_cfg)  # 260611-19
        self._present.fileChanged.connect(self._on_present_file_changed)   # 260611-23
        self._present.viewSettingsRequested.connect(self._on_present_view_settings)  # 260611-25
        self._present.overlapChanged.connect(self._on_present_overlap_changed)        # 260611-26
        # 260609-17(F4): 녹화
        self._present.recordToggleRequested.connect(self._on_record_toggle)
        self._present.recordPauseRequested.connect(self._on_record_pause)
        self._present.recordStopRequested.connect(self._on_record_stop)
        self._present.hyperlinkActivated.connect(self._launch_hyperlink)  # 260609-8
        self._present.linkPlayRequested.connect(self._on_present_link_play)  # 260611-85
        # 닫힐 때: 발표 중 이동한 파일·페이지를 메인 뷰에 반영
        self._present.closed.connect(lambda _pg: self._on_presentation_closed())
        # 260609-5: 포인터 선택/설정 영속
        self._present.pointerChanged.connect(self._on_pointer_changed)
        self._present.pointerSettingsRequested.connect(self._on_pointer_settings)
        self._present.show_presentation()

    def _on_pointer_changed(self, idx: int):
        self._prefs["presentation_pointer_active"] = int(idx)
        self._save_settings_now()

    def _on_present_split_changed(self, on: bool):
        # 260628(발표 SOT B5): 분할은 진입·파일전환 시 페이지 방향으로 자동 판정하는 것이 사양이라
        #   발표 중 토글은 **그 세션에만** 적용한다(저장하지 않음 — 저장해도 반영되지 않아 오해만 낳았다).
        pass

    def _on_pres_timer_cfg(self, cfg):
        """260611-19: 발표시간 설정 영속."""
        self._prefs["presentation_timer"] = cfg
        self._save_settings_now()

    def _on_present_overlap_changed(self, pct):
        """260611-26: 메뉴 '중앙겹침' 입력값 영속."""
        self._prefs["presentation_overlap_pct"] = int(pct)
        self._save_settings_now()

    def _on_present_view_settings(self):
        """260611-26: '보기 설정' — 상단 띠 높이 + 크롭(구 '크롭 설정' 내용 병합)."""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QGroupBox,
                                     QSpinBox, QCheckBox, QPushButton, QDialogButtonBox)
        w = getattr(self, "_present", None)
        par = w or self
        st = self._ensure_page_meta_store()
        dlg = QDialog(par)
        dlg.setWindowTitle("보기 설정")
        v = QVBoxLayout(dlg)
        # 상단 띠 높이
        grp_tb = QGroupBox("상단 띠")
        tf = QFormLayout(grp_tb)
        sp_tb = QSpinBox(); sp_tb.setRange(40, 240); sp_tb.setSuffix(" px")
        sp_tb.setValue(int(self._prefs.get("presentation_topbar_h", 64)))
        tf.addRow("상단 띠 높이:", sp_tb)
        v.addWidget(grp_tb)

        # 크롭(현재 발표 파일/페이지) — 상단 띠 높이 아래에 병합
        crop = None
        if w is not None and st is not None:
            path = str(w._path); page0 = int(w._page)
            g = st.get_global_crop(path); pg = st.get_crop(path, page0)
            has_pg = st.has_page_crop(path, page0)

            def _sp(val):
                s = QSpinBox(); s.setRange(0, 45); s.setSuffix(" %")
                s.setValue(int(round(float(val)))); return s
            grp_g = QGroupBox("크롭 — 전체 페이지(전역)")
            gf = QFormLayout(grp_g)
            sp_gt = _sp(g[0]); sp_gb = _sp(g[1])
            gf.addRow("상단 크롭:", sp_gt); gf.addRow("하단 크롭:", sp_gb)
            v.addWidget(grp_g)
            grp_p = QGroupBox(f"크롭 — 현재 페이지 p.{page0 + 1}")
            pf = QFormLayout(grp_p)
            chk_pg = QCheckBox("이 페이지에만 별도 적용"); chk_pg.setChecked(bool(has_pg))
            pf.addRow(chk_pg)
            sp_pt = _sp(pg[0]); sp_pb = _sp(pg[1])
            pf.addRow("상단 크롭:", sp_pt); pf.addRow("하단 크롭:", sp_pb)
            v.addWidget(grp_p)
            btn_reset = QPushButton("크롭 초기화(이 파일 전체)")
            v.addWidget(btn_reset)
            cstate = {"reset": False}
            btn_reset.clicked.connect(lambda: (cstate.__setitem__("reset", True), dlg.accept()))
            crop = (path, page0, sp_gt, sp_gb, chk_pg, sp_pt, sp_pb, cstate)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # 상단 띠 높이 저장·반영
        self._prefs["presentation_topbar_h"] = int(sp_tb.value())
        self._save_settings_now()
        if w is not None:
            try:
                w.set_topbar_height(sp_tb.value())
            except Exception:
                pass
        # 크롭 저장·반영
        if crop is not None and st is not None:
            path, page0, sp_gt, sp_gb, chk_pg, sp_pt, sp_pb, cstate = crop
            if cstate["reset"]:
                st.reset_crop(path)
            else:
                st.set_global_crop(path, sp_gt.value(), sp_gb.value())
                if chk_pg.isChecked():
                    st.set_page_crop(path, page0, sp_pt.value(), sp_pb.value())
                else:
                    st.clear_page_crop(path, page0)
            st.save()
            if w is not None:
                w.refresh()

    def _on_pen_changed(self, idx: int):
        self._prefs["presentation_pen_active"] = int(idx)
        self._save_settings_now()

    def _on_pen_straight_changed(self, on: bool):
        self._prefs["presentation_pen_straight"] = bool(on)
        self._save_settings_now()

    def _on_line_mode_changed(self, mode: int):
        """260611-4: 발표에서 바꾼 선 종류를 공유 설정·본문 두 메인뷰에 반영."""
        self._prefs["draw_line_mode"] = int(mode)
        for mv in self._mv:
            try:
                mv.set_draw_line_mode(int(mode))
            except Exception:
                pass
        self._save_settings_now()

    def _on_main_draw_mode_changed(self, mode: int):
        """260611-4: 본문에서 바꾼 선 종류를 공유 설정·다른 메인뷰·발표창에 반영."""
        self._prefs["draw_line_mode"] = int(mode)
        for mv in self._mv:
            try:
                if mv._draw_line_mode != int(mode):
                    mv.set_draw_line_mode(int(mode))
            except Exception:
                pass
        if getattr(self, "_present", None) is not None:
            try:
                self._present.set_line_mode(int(mode))
            except Exception:
                pass
        self._save_settings_now()

    # ===== 260609-17 (F4): 화면+음성 녹화 =================================
    def _ensure_hyperlink_store(self):
        """현재 폴더에 맞는 HyperlinkStore 보장(폴더 바뀌면 재생성)."""
        from viewer.hyperlinks import HyperlinkStore
        if not self._folder:
            self._hyperlinks = None
            return None
        allow = self._prefs.get("hyperlink_url_allowlist") or None
        st = self._hyperlinks
        if st is None or str(getattr(st, "base", "")) != str(self._folder):
            self._hyperlinks = HyperlinkStore(self._folder, url_allowlist=allow)
        else:
            st.url_allowlist = allow or st.url_allowlist
        return self._hyperlinks

    def _refresh_page_hyperlinks(self, idx: int):
        """활성 창의 현재 파일·페이지 링크를 우상단 버튼으로 갱신."""
        try:
            if idx != self._active_pane:
                return
            mv = self._mv[idx]
            cur = mv.current_file()
            st = self._ensure_hyperlink_store()
            if not st or not cur or not str(cur).lower().endswith(".pdf"):
                mv.set_hyperlinks([])
                return
            mv.set_hyperlinks(st.links_for(cur, mv.current_page()))
        except Exception:
            try:
                self._mv[idx].set_hyperlinks([])
            except Exception:
                pass

    def _open_hyperlink_dialog(self, file_path, page0: int):
        """우클릭 '하이퍼링크 등록' → 다이얼로그. 닫은 뒤 저장·갱신."""
        st = self._ensure_hyperlink_store()
        if not st:
            QMessageBox.information(self, "안내", "먼저 폴더(책갈피 목록)를 여세요.")
            return
        if not file_path or not str(file_path).lower().endswith(".pdf"):
            QMessageBox.information(self, "안내", "먼저 PDF를 표시하세요.")
            return
        from viewer.widgets.hyperlink_dialog import HyperlinkDialog
        dlg = HyperlinkDialog(st, file_path, page0, self._folder, self)
        dlg.exec()
        self._persist_meta(st)           # 260609-23(J2): 편집모드면 보류
        self._refresh_page_hyperlinks(self._active_pane)
        self._refresh_hidden_ui(str(file_path))      # 260609-21(J4): 꾸밈 갱신

    def _media_item(self, link):
        """260611-85: 링크가 사진/동영상 파일이면 {type,path,name} 반환, 아니면 None.

        (유튜브 URL 은 앱 내 오버레이가 아니라 _launch_hyperlink 에서 외부 브라우저
        전체화면으로 연다 — 260611-95.)
        """
        from viewer.hyperlinks import is_safe_to_open_file
        from viewer.widgets.media_overlay import media_kind
        if link.get("kind") != "file":
            return None
        abs_path = is_safe_to_open_file(self._folder, link.get("target", ""))
        if not abs_path:
            return None
        k = media_kind(abs_path)
        if k is None:
            return None
        return {"type": k, "path": str(abs_path),
                "name": link.get("name") or Path(str(abs_path)).name}

    def _media_items_for_page(self, path, page0):
        """260611-85: 해당 페이지 링크 중 사진·동영상만 링크 순서대로."""
        out = []
        try:
            for ln in (self._presentation_hyperlinks(path, page0) or []):
                it = self._media_item(ln)
                if it:
                    out.append(it)
        except Exception:
            pass
        return out

    def _show_media_overlay(self, items, idx=0):
        """260611-85: 전체화면 미디어 오버레이 표시(발표창 위, 없으면 메인 위)."""
        if not items:
            QMessageBox.information(self, "링크 실행",
                                    "이 페이지에 표시할 사진·동영상 링크가 없습니다.")
            return
        from viewer.widgets.media_overlay import MediaOverlay
        parent = self._present if getattr(self, "_present", None) is not None else self
        ov = MediaOverlay(parent)
        self._media_overlay = ov          # 참조 유지(GC 방지)
        ov.show_items(items, idx)

    def _on_present_link_play(self):
        """260611-85: 발표 상단띠 '링크실행' — 현재 페이지의 사진·동영상을 순서대로."""
        w = getattr(self, "_present", None)
        if w is None:
            return
        items = self._media_items_for_page(str(w._path), int(w._page))
        self._show_media_overlay(items, 0)

    def _launch_hyperlink(self, link):
        """링크 실행: 사진/동영상=전체화면 오버레이, 유튜브=외부 브라우저 전체화면,
        파일=OS 기본앱, 그 외 URL=브라우저."""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        from viewer.hyperlinks import is_safe_to_open_file, validate_url
        from viewer.widgets.media_overlay import is_youtube_url, open_youtube_external
        try:
            # 260611-85: 사진·동영상 링크는 앱 내 전체화면으로
            mi = self._media_item(link)
            if mi is not None:
                self._show_media_overlay([mi], 0)
                return
            kind = link.get("kind"); target = link.get("target", "")
            if kind == "file":
                abs_path = is_safe_to_open_file(self._folder, target)
                if not abs_path:
                    QMessageBox.warning(self, "열 수 없음",
                                        "파일이 없거나 보안 정책상 열 수 없습니다.")
                    return
                QDesktopServices.openUrl(QUrl.fromLocalFile(abs_path))
            elif kind == "url":
                # 260611-96: 유튜브는 기본 웹브라우저 watch 페이지로(임베드는 환경상 불가)
                if is_youtube_url(target):
                    open_youtube_external(target)
                    return
                allow = self._prefs.get("hyperlink_url_allowlist") or None
                ok, u = validate_url(target, allow)
                if not ok:
                    QMessageBox.warning(self, "열 수 없음", u)
                    return
                QDesktopServices.openUrl(QUrl(u))
        except Exception:
            QMessageBox.warning(self, "오류", "링크를 여는 중 문제가 발생했습니다.")

    def _on_search_result_activated(self, file_path: str, page_index: int, query: str):
        # 260616-4: 이미 같은 파일이 열려 있으면 재오픈(문서 open + 전체검색 +
        #   썸네일/단어장 재적재) 없이 페이지·매치로만 이동 → 결과 클릭이 즉시 반응.
        mv = self.main_view
        try:
            cur = mv.current_file()
            same = bool(cur) and self._norm_path(cur) == self._norm_path(file_path) \
                and mv._doc is not None and not getattr(mv, "_is_image", False)
        except Exception:
            same = False
        if same:
            mv.jump_to_search_result(page_index, query)
            self._current_main = HistoryItem(file_path, page_index, query, "search")
            return
        self._load_main(HistoryItem(file_path, page_index, query, "search"))

    def _on_screenshot_activated(self, path: str, page: int):
        """v1.6.2: 스크린샷 미니카드 클릭 — 메인 뷰어에 이미지 로드.

        v1.6.5 D2: 카드에 src_pdf/src_page/src_query 가 있으면 원본 페이지를
        형광펜 포함 재렌더한 PNG 를 표시(검색어 가시) — 이미지 모드 유지.
        D1: 표시 후 페이지 바를 스크린샷 리스트 순번 i/N 으로.
        """
        disp = path
        meta = next((m for m in self.shot_strip.all_meta()
                     if m.get("path") == path), None)
        if (meta and meta.get("src_pdf") and meta.get("src_page") is not None
                and meta.get("src_query")):
            try:
                disp = str(ss.render_page_png(
                    meta["src_pdf"], int(meta["src_page"]), meta["src_query"]))
            except Exception:
                disp = path
        # v1.6.7 E1: 표시는 임시 PNG 일 수 있으므로, ◀▶/순번 조회용으로
        #            카드 원본 path 를 별도 보관 (_current_main 은 disp 가 됨).
        self._current_shot_path = path
        self._load_main(HistoryItem(file_path=disp, page_index=0, origin="screenshot"))
        # D1: 리스트 순번/총수 (조회는 항상 카드 원본 path 기준)
        i = self.shot_strip.index_of_path(path)
        n = self.shot_strip.list.count()
        if i >= 0:
            self.main_view.set_image_position(i + 1, n)

    def _on_image_step(self, direction: int):
        """v1.6.4 C2: 스크린샷 표시 중 ◀▶ → 리스트 인접 카드 (끝에서 멈춤).

        v1.6.7 E1: _current_main.file_path 는 표시용 임시 PNG 일 수 있어
        카드와 불일치 → 별도 보관한 _current_shot_path(카드 원본)로 조회.
        """
        cur = getattr(self, "_current_shot_path", None)
        if not cur:
            return
        i = self.shot_strip.index_of_path(cur)
        if i < 0:
            return
        j = max(0, min(self.shot_strip.list.count() - 1, i + direction))
        if j != i:
            self.shot_strip.activate_index(j)

    def _on_image_goto(self, idx: int):
        """v1.6.8 F2: 이미지 모드 페이지번호 입력 → idx 스크린샷으로."""
        n = self.shot_strip.list.count()
        if n == 0:
            return
        self.shot_strip.activate_index(max(0, min(n - 1, int(idx))))

    def _on_main_page_changed(self, page: int):
        """페이지가 바뀐 직후, 보류 중인 자동 스크린샷이 있으면 캡처."""
        if self._pending_screenshot_after_load:
            self._pending_screenshot_after_load = False
            QApplication.processEvents()
            self.action_screenshot()

    # ===== 단어장 ====================================================
    def _law_oc_or_warn(self) -> str:
        oc = (self._prefs.get("law_oc") or "").strip()
        if not oc:
            QMessageBox.information(
                self, "법령·고시 검색",
                "설정 → '인터넷 사전'의 '법제처 OC'(국가법령정보 OPEN API 인증값, "
                "open.law.go.kr 에서 무료 신청)를 먼저 입력하세요.")
        return oc

    def _action_law_search(self, checked: bool = False):
        """260616-1/19: 법제처 법령·고시 검색·본문 패널. 기본은 메인창 오른쪽 2단(임베드),
        패널의 '전체화면' 토글로 별도 전체화면 창으로 팝아웃/복귀."""
        self._open_law()

    def _open_law(self, fav: dict | None = None):
        oc = self._law_oc_or_warn()
        if not oc:
            return
        if self._kcsc_panel is not None:       # 260618-37: 사이드 슬롯 공유 — 건설기준 먼저 닫기
            self._close_kcsc()
        if self._kipo_panel is not None:       # 260618-43
            self._close_kipo()
        if self._law_panel is not None:        # 이미 열려 있음
            if self._law_window is not None:
                self._law_window.raise_()
                self._law_window.activateWindow()
            if fav:
                self._law_panel.show_saved(fav)
            return
        from viewer.widgets.law_search_dialog import LawSearchPanel
        self._law_panel = LawSearchPanel(oc, self)
        self._law_panel.closeRequested.connect(self._close_law)
        self._law_panel.fullscreenToggled.connect(self._toggle_law_fullscreen)
        self._enter_law_layout()               # 메인 패널 슬라이드 + 오른쪽 2단 임베드
        self._set_content_search(self._law_panel)    # 검색바 → 법령/고시 본문 검색
        if fav:
            self._law_panel.show_saved(fav)

    # 260628(감사 D): 사이드 패널 호스팅 로직은 `viewer/side_panel_host.py` 공통
    #   구현으로 일반화(법령·건설기준·특허 3벌 → 1벌). 상태(_X_panel 등)는 종전과
    #   같은 MainWindow 속성에 그대로 두고 아래는 **얇은 위임** — 메뉴·시그널 연결
    #   등 호출부는 변경 없음. 새 API 패널은 SPECS 에 1항목만 추가하면 된다.
    def _enter_law_layout(self):
        _sp.enter_layout(self, _sp.SPECS['law'])

    def _apply_law_embed_sizes(self):
        _sp.apply_embed_sizes(self, _sp.SPECS['law'])

    def _toggle_law_fullscreen(self):
        _sp.toggle_fullscreen(self, _sp.SPECS['law'])

    def _embed_law_from_window(self):
        _sp.embed_from_window(self, _sp.SPECS['law'])

    def _close_law(self):
        _sp.close_panel(self, _sp.SPECS['law'])
    def _kcsc_key_or_warn(self) -> str:
        key = (self._prefs.get("kcsc_key") or "").strip()
        if not key:
            QMessageBox.information(
                self, "건설기준(KCSC)",
                "설정 → '인터넷 사전'의 'KCSC 키'(국가건설기준센터 OPEN API 인증키, "
                "www.kcsc.re.kr/support/api 에서 무료 발급)를 먼저 입력하세요.")
        return key

    def _action_kcsc_search(self, checked: bool = False):
        """260618-37: 국가건설기준센터(KDS/KCS) 본문 패널(메인 오른쪽 2단 임베드/전체화면)."""
        self._open_kcsc()

    def _open_kcsc(self, fav: dict | None = None):
        key = self._kcsc_key_or_warn()
        if not key:
            return
        if self._law_panel is not None:        # 사이드 슬롯 공유 — 법령 먼저 닫기
            self._close_law()
        if self._kipo_panel is not None:       # 260618-43
            self._close_kipo()
        if self._kcsc_panel is not None:
            if self._kcsc_window is not None:
                self._kcsc_window.raise_(); self._kcsc_window.activateWindow()
            if fav:
                self._kcsc_panel.show_saved(fav)
            return
        from viewer.widgets.kcsc_search_dialog import KcscSearchPanel
        self._kcsc_panel = KcscSearchPanel(key, self)
        self._kcsc_panel.closeRequested.connect(self._close_kcsc)
        self._kcsc_panel.fullscreenToggled.connect(self._toggle_kcsc_fullscreen)
        self._enter_kcsc_layout()
        self._set_content_search(self._kcsc_panel)   # 검색바 → 건설기준 본문 검색
        if fav:
            self._kcsc_panel.show_saved(fav)

    def _add_kcsc_favorite_entry(self, row: dict):
        """260618-39: 건설기준 항목을 KCSC 즐겨찾기에 추가(중복 방지)."""
        name = (row.get("name") or "").strip()
        code = str(row.get("code") or "").strip()
        if not (name or code):
            return
        for f in self._kcsc_favorites:
            if str(f.get("code")) == code and (f.get("ctype") or "") == (row.get("ctype") or ""):
                self.status.showMessage(f"이미 건설기준 즐겨찾기에 있음: {name}", 3000)
                return
        self._kcsc_favorites.append({
            "kind": "kcsc", "name": name, "code": code,
            "ctype": row.get("ctype", ""), "category": row.get("category", ""),
        })
        try:
            self._refresh_favorites_menu()
            self._save_settings_now()
        except Exception:
            pass
        self.status.showMessage(f"건설기준 즐겨찾기 추가: {name}", 3000)

    def _open_kcsc_favorite(self, fav: dict):
        self._open_kcsc(fav)

    def _manage_kcsc_favorites(self):
        from viewer.widgets.law_search_dialog import LawFavoritesManager
        dlg = LawFavoritesManager(self._kcsc_favorites, self)
        dlg.setWindowTitle("건설기준(KCSC) 즐겨찾기 관리")
        if dlg.exec():
            self._kcsc_favorites = dlg.result_favorites()
            try:
                self._save_settings_now()
            except Exception:
                pass

    def _enter_kcsc_layout(self):
        _sp.enter_layout(self, _sp.SPECS['kcsc'])

    def _apply_kcsc_embed_sizes(self):
        _sp.apply_embed_sizes(self, _sp.SPECS['kcsc'])

    def _toggle_kcsc_fullscreen(self):
        _sp.toggle_fullscreen(self, _sp.SPECS['kcsc'])

    def _embed_kcsc_from_window(self):
        _sp.embed_from_window(self, _sp.SPECS['kcsc'])

    def _close_kcsc(self):
        _sp.close_panel(self, _sp.SPECS['kcsc'])
    def _kipo_signkey_or_warn(self) -> str:
        key = (self._prefs.get("kipo_signkey") or "").strip()
        if not key:
            QMessageBox.information(
                self, "특허 검색(KIPRIS)",
                "설정 → '인터넷 사전'의 '특허(KIPRIS) 키'(KIPRIS Plus accessKey)를 "
                "먼저 입력하세요.")
        return key

    def _patent_save_dir(self) -> str:
        """260618-47: 특허(전자명세서) PDF 저장 폴더. 설정값 없으면 기본(문서\\PolyPDF_특허)."""
        d = (self._prefs.get("patent_save_dir") or "").strip()
        if not d:
            d = str(Path.home() / "Documents" / "PolyPDF_특허")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    def _action_kipo_search(self, checked: bool = False):
        self._open_kipo()

    def _open_kipo(self, fav: dict | None = None):
        key = self._kipo_signkey_or_warn()
        if not key:
            return
        if self._law_panel is not None:
            self._close_law()
        if self._kcsc_panel is not None:
            self._close_kcsc()
        if self._kipo_panel is not None:
            if self._kipo_window is not None:
                self._kipo_window.raise_(); self._kipo_window.activateWindow()
            if fav:
                self._kipo_panel.show_saved(fav)
            return
        from viewer.widgets.kipo_search_dialog import KipoSearchPanel
        self._kipo_panel = KipoSearchPanel(key, self)
        self._kipo_panel.closeRequested.connect(self._close_kipo)
        self._kipo_panel.fullscreenToggled.connect(self._toggle_kipo_fullscreen)
        self._enter_kipo_layout()
        self._set_content_search(self._kipo_panel)   # 검색바 → 특허 본문 검색
        if fav:
            self._kipo_panel.show_saved(fav)

    def _enter_kipo_layout(self):
        _sp.enter_layout(self, _sp.SPECS['kipo'])

    def _apply_kipo_embed_sizes(self):
        _sp.apply_embed_sizes(self, _sp.SPECS['kipo'])

    def _toggle_kipo_fullscreen(self):
        _sp.toggle_fullscreen(self, _sp.SPECS['kipo'])

    def _embed_kipo_from_window(self):
        _sp.embed_from_window(self, _sp.SPECS['kipo'])

    def _close_kipo(self):
        _sp.close_panel(self, _sp.SPECS['kipo'])

    def _add_kipo_favorite_entry(self, item: dict):
        """260618-44: 특허 검색 결과(항목)를 즐겨찾기에 추가(출원/등록번호 기준 중복 방지)."""
        appno = str(item.get("applicationNumber") or "").strip()
        regno = str(item.get("registerNumber") or "").strip()
        name = (item.get("inventionTitle") or "").strip()
        key = appno or regno or name
        if not key:
            return
        for f in self._kipo_favorites:
            if (f.get("appNo") or f.get("regNo") or f.get("name")) == key:
                self.status.showMessage(f"이미 특허 즐겨찾기에 있음: {name or key}", 3000)
                return
        self._kipo_favorites.append({"kind": "kipo", "name": name, "appNo": appno,
                                     "regNo": regno, "item": dict(item)})
        try:
            self._refresh_favorites_menu()
            self._save_settings_now()
        except Exception:
            pass
        self.status.showMessage(f"특허 즐겨찾기 추가: {name or key}", 3000)

    def _open_kipo_favorite(self, fav: dict):
        self._open_kipo(fav)

    def _manage_kipo_favorites(self):
        from viewer.widgets.law_search_dialog import LawFavoritesManager
        dlg = LawFavoritesManager(self._kipo_favorites, self)
        dlg.setWindowTitle("특허 등록정보 즐겨찾기 관리")
        if dlg.exec():
            self._kipo_favorites = dlg.result_favorites()
            try:
                self._save_settings_now()
            except Exception:
                pass

    def _add_law_favorite_entry(self, row: dict):
        """260616-6: 법령·고시 항목을 (메인 즐겨찾기와 분리된) 법령 즐겨찾기에 추가."""
        name = (row.get("name") or "").strip()
        if not name:
            return
        # 동일 항목(이름+target) 중복 방지
        key = (name, row.get("target"))
        for f in self._law_favorites:
            if (f.get("name"), f.get("target")) == key:
                self.status.showMessage(f"이미 법령 즐겨찾기에 있음: {name}", 3000)
                return
        self._law_favorites.append({
            "kind": "law",
            "name": name,
            "target": row.get("target", "law"),
            "category": row.get("category", ""),
            "kind_label": row.get("kind", ""),
            "agency": row.get("agency", ""),
            "date": row.get("date", ""),
            "link": row.get("link", ""),
            "ids": dict(row.get("ids") or {}),
        })
        self._refresh_favorites_menu()
        self._save_settings_now()
        self.status.showMessage(f"법령 즐겨찾기 추가: {name}", 3000)

    def _open_law_favorite(self, fav: dict):
        """260616-6/19: 법령 즐겨찾기 클릭 — 법령 패널을 열고 해당 본문 바로 표시."""
        self._open_law(fav)

    def _manage_law_favorites(self):
        """260616-20: 법령·고시 즐겨찾기 관리(이름변경/이동/삭제)."""
        from viewer.widgets.law_search_dialog import LawFavoritesManager
        dlg = LawFavoritesManager(self._law_favorites, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._law_favorites = dlg.result_favorites()
            self._refresh_favorites_menu()
            self._save_settings_now()

    def _content_match(self, backward: bool) -> bool:
        """우측 패널 본문 검색 이동(◀▶) — 슬라이드 오버레이가 열려 있으면 그쪽으로. 없으면 소비만."""
        if self._content_panel is None:
            return False
        ov = getattr(self, "_cf_overlay", None)
        if ov is not None and ov.isVisible():
            ov._nav(backward)
        elif (self._content_query or self.search_bar.current_query()):
            self._open_content_find(self._content_query or self.search_bar.current_query())
        return True

    def _global_next_match(self):
        """검색바 ▶: 우측 패널 활성 시 그 본문의 다음 매치, 아니면 PDF 매치 이동."""
        if self._content_match(False):
            return
        mv = self.main_view
        if mv._matches:
            total = sum(len(h.rects) for h in mv._matches)
            if total > 0 and mv._current_match < total - 1:
                mv.go_next_match()
                return
        self._jump_search_file(+1)

    def _global_prev_match(self):
        if self._content_match(True):
            return
        mv = self.main_view
        if mv._matches:
            if mv._current_match > 0:
                mv.go_prev_match()
                return
        self._jump_search_file(-1)

    def _jump_search_file(self, direction: int):
        """검색결과 표시 순서에 따라 다른 파일의 첫(또는 마지막) 매치로 이동."""
        results = self.search_results.get_displayed_results()
        if not results:
            return
        # 파일 등장 순서 (중복 제거, 표시 순서 보존)
        files_in_order: list = []
        seen = set()
        for r in results:
            if r.file_path not in seen:
                seen.add(r.file_path)
                files_in_order.append(r.file_path)
        if not files_in_order:
            return

        current_file = self.main_view.current_file()
        try:
            idx = files_in_order.index(current_file) if current_file else -1
        except ValueError:
            idx = -1

        if idx < 0:
            nxt = 0 if direction > 0 else len(files_in_order) - 1
        else:
            nxt = (idx + direction) % len(files_in_order)
        target_file = files_in_order[nxt]

        target_results = [r for r in results if r.file_path == target_file]
        if not target_results:
            return
        target = target_results[0] if direction > 0 else target_results[-1]
        query = self.main_view.current_query()
        item = HistoryItem(target.file_path, target.page_index, query, "search")
        self._load_main(item)

        # 다음 파일로 갔을 때 첫/마지막 매치로 위치 보정
        QApplication.processEvents()
        if direction < 0 and self.main_view._matches:
            total = sum(len(h.rects) for h in self.main_view._matches)
            if total > 0:
                self.main_view._current_match = total - 1
                self.main_view._jump_to_match(total - 1)
        # direction > 0 이면 main_view 가 이미 _current_match = 0 으로 시작

    # ===== 스크린샷 ====================================================
    # ===== 인쇄 (260603-3) =============================================
    def action_encrypt_pdf(self):
        """260611-57: 현재 PDF에 암호·권한을 설정해 암호화 사본으로 저장."""
        cur = self.main_view.current_file()
        if not (cur and str(cur).lower().endswith(".pdf") and self.main_view._doc is not None):
            QMessageBox.information(self, "암호화", "암호화할 PDF를 먼저 여세요.")
            return
        import fitz
        live = self.main_view._doc.doc
        from viewer.widgets.encrypt_dialog import EncryptDialog
        dlg = EncryptDialog(self, file_name=Path(cur).name)
        # 이미 암호화된 문서면 기존 암호·수준·권한 프리필 + 제한 상태면 잠금
        try:
            from viewer import secure_store
            meth = str((live.metadata or {}).get("encryption", "") or "")
            saved_pw = secure_store.recall_any(cur) or ""
            # 인증 후 is_encrypted/needs_pass 값이 달라지는 PyMuPDF 차이를 고려해
            # 메타데이터 암호화 문자열·저장암호 존재로도 암호화 여부를 판단
            is_enc = (bool(meth) or bool(getattr(live, "is_encrypted", False))
                      or bool(saved_pw))
            if is_enc:
                perm = int(getattr(live, "permissions", -1))
                is_128 = "128" in meth
                locked = (perm != -1) and not bool(perm & fitz.PDF_PERM_MODIFY)
                dlg.prefill(open_pw=saved_pw, is_128=is_128, perm=perm, locked=locked)
        except Exception:
            pass
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        args = dlg.result_args()
        from PyQt6.QtWidgets import QFileDialog
        default = str(Path(cur).with_name(Path(cur).stem + "_암호화.pdf"))
        out, _ = QFileDialog.getSaveFileName(self, "암호화 PDF 저장", default, "PDF 파일 (*.pdf)")
        if not out:
            return
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        if Path(out).resolve() == Path(cur).resolve():
            QMessageBox.warning(self, "암호화", "원본과 다른 경로로 저장하세요.")
            return
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        try:
            # 열려있는(인증된) 문서를 변형하지 않도록 새 문서로 복사 후 암호화 저장
            # (live.save(encryption=...) 는 메모리 문서를 바꿔 메인 썸네일이 하얗게 되는 문제)
            out_doc = fitz.open()
            out_doc.insert_pdf(live)
            try:
                out_doc.set_toc(live.get_toc() or [])
            except Exception:
                pass
            try:
                if live.metadata:
                    out_doc.set_metadata(live.metadata)
            except Exception:
                pass
            out_doc.save(
                out, encryption=args["encryption"], owner_pw=args["owner_pw"],
                user_pw=args["user_pw"], permissions=args["permissions"],
                garbage=4, deflate=True)
            out_doc.close()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "암호화", f"저장 실패: {e}")
            return
        QApplication.restoreOverrideCursor()
        # 방금 설정한 열기 암호를 새 파일에 대해 기억(선택)
        if args.get("open_pw"):
            try:
                from viewer import secure_store
                if secure_store.available() and QMessageBox.question(
                    self, "암호 기억",
                    "방금 설정한 열기 암호를 이 PC·계정에 안전하게 기억할까요?"
                ) == QMessageBox.StandardButton.Yes:
                    secure_store.remember_password(out, args["open_pw"])
            except Exception:
                pass
        # 260611-61: 같은 폴더에 새 파일이 생겼으면 책갈피창 새로고침
        try:
            root = getattr(self.bookmark_tree, "_root_dir", None)
            if root and Path(out).resolve().parent == Path(root).resolve():
                self.bookmark_tree.refresh()
        except Exception:
            pass
        QMessageBox.information(self, "암호화", f"암호화 저장 완료:\n{out}")

    def _on_thumb_screenshot_pages(self, pages):
        """260616-21: 썸네일 다중선택 → 선택 페이지를 스크린샷 스트립에 복사."""
        # 260618-1: 내용 복사(추출) 권한 없으면 차단
        if not getattr(self, "_perm_can_copy", True):
            self.status.showMessage("이 문서는 복사(스크린샷) 권한이 없습니다.", 3000)
            return
        cur = self._thumb_doc_path()
        pages = sorted({int(p) for p in (pages or []) if p is not None})
        if not cur or not pages:
            return
        from viewer import screenshot as ss
        added = 0
        for p in pages:
            try:
                png = ss.render_page_png(cur, p, "")
                self.shot_strip.add_item(
                    str(png), kind="image",
                    label=f"{Path(cur).stem} p.{p + 1}",
                    src_pdf=str(cur), src_page=p, prepend=False)
                added += 1
            except Exception:
                continue
        if added:
            try:
                self.act_toggle_shot.setChecked(True)
                self._sync_right_layout()
            except Exception:
                pass
            self.status.showMessage(f"스크린샷 {added}장 추가됨", 3000)

    def _ensure_shots_visible(self):
        """260603-3: 스크린샷 항목이 있으면 패널 자동 표시(기본은 숨김)."""
        if self.shot_strip.list.count() > 0 and not self.act_toggle_shot.isChecked():
            self.act_toggle_shot.setChecked(True)   # toggled→shot_strip.setVisible(True)

    def _hide_shots_if_empty(self):
        """260606-3: 스크린샷이 모두 삭제되면 창을 숨김."""
        if self.shot_strip.list.count() == 0 and self.act_toggle_shot.isChecked():
            self.act_toggle_shot.setChecked(False)

    def action_screenshot(self, checked: bool = False, view=None):
        """v1.5.0 M3 + M8 + v1.6.2: 캡처 시 원본 PDF + 페이지 메타 동봉.
        260606-8: view 인자로 특정 메인 창을 캡처(없으면 활성 창).

        PDF 저장 시 PNG 가 아닌 원본 PDF 페이지를 1:1 로 복사해
        품질 손실·좌우 배경 확장 없이 내보내기 위함.
        """
        view = view or self.main_view
        # v1.6.3 B2: view 전체(스크롤바·레터박스 포함) → 렌더된 페이지 영역만 캡처
        pix = view.grab_page()
        # 260606-5: 캡처 이미지를 클립보드에도 복사(다른 프로그램에 붙여넣기 용도)
        try:
            if pix is not None and not pix.isNull():
                QApplication.clipboard().setPixmap(pix)
        except Exception:
            pass
        cur = view.current_file()
        src_name = Path(cur).name if cur else "screenshot.pdf"
        is_pdf = bool(cur and cur.lower().endswith(".pdf"))
        cur_page = view.current_page() if is_pdf else None
        cur_query = view.current_query() if is_pdf else None   # v1.6.4 C3

        try:
            if view.is_two_page_mode():
                left, right = ss.split_pixmap_horizontally(pix)
                saved_l = ss.save_screenshot(left, source_name=src_name, suffix="_L")
                saved_r = ss.save_screenshot(right, source_name=src_name, suffix="_R")
                disp = Path(src_name).stem        # 260606-13: 라벨=파일명(확장자 제외)
                # 2장 보기: 좌 = N, 우 = N+1 (우측이 페이지 범위 밖이면 None)
                left_page = cur_page if is_pdf else None
                right_page = (cur_page + 1) if is_pdf and cur_page is not None else None
                if right_page is not None and view._doc is not None:
                    if right_page >= view._doc.page_count:
                        right_page = None   # 원본에 우측 페이지 없음 → PNG 폴백
                self.shot_strip.add_item(
                    str(saved_l), kind="image", label=disp,
                    thumb_pdf_path=cur if is_pdf else None,
                    src_pdf=cur if is_pdf else None,
                    src_page=left_page,
                    src_query=cur_query,
                    prepend=False,
                )
                # 우측 페이지가 존재할 때만 (홀수 페이지 끝일 수도 있음)
                if is_pdf and right_page is not None:
                    self.shot_strip.add_item(
                        str(saved_r), kind="image", label=disp,
                        thumb_pdf_path=cur,
                        src_pdf=cur, src_page=right_page,
                        src_query=cur_query,
                        prepend=False,
                    )
                else:
                    self.shot_strip.add_item(
                        str(saved_r), kind="image", label=disp,
                        prepend=False,
                    )
                self.status.showMessage(f"스크린샷 (좌/우): {saved_l.name}, {saved_r.name}", 4000)
            else:
                saved = ss.save_screenshot(pix, source_name=src_name)
                self.shot_strip.add_item(
                    str(saved), kind="image", label=Path(src_name).stem,
                    thumb_pdf_path=cur if is_pdf else None,
                    src_pdf=cur if is_pdf else None,
                    src_page=cur_page,
                    src_query=cur_query,
                    prepend=False,
                )
                self.status.showMessage(f"스크린샷 저장: {saved.name}", 4000)
            # 260606-19: 드로어에 있으면 슬라이드 표시(1.5초 자동 접기), 아니면 패널 표시
            if getattr(self, "_panel_in_drawer", False):
                self._drawer_auto_show()
            else:
                self._ensure_shots_visible()        # 캡처했으니 패널 표시
        except Exception as e:
            QMessageBox.warning(self, "스크린샷 실패", str(e))

    def action_save_screenshot_pdf(self):
        """v1.6.2: 카드 메타 기반으로 원본 PDF 페이지를 통째로 복사 (export_pdf_from_meta).

        원본 PDF 정보가 있는 카드는 fitz `insert_pdf` 로 페이지를 그대로 복사 →
        페이지 크기·텍스트·벡터 100% 보존, 좌우 배경 확장 없음.
        원본 정보 없는 카드(외부 이미지 등)는 PNG 폴백.
        """
        meta = self.shot_strip.all_meta()
        if not meta:
            QMessageBox.information(self, "안내", "저장할 스크린샷이 없습니다.")
            return
        # v1.6.4 C1: 저장 옵션 대화상자 (검색어 형광펜 / 상단 파일명 / 하단 페이지번호)
        from viewer.widgets.screenshot_pdf_dialog import ScreenshotPdfDialog  # 260825: 지연 임포트
        dlg = ScreenshotPdfDialog(self._prefs, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        opts = dlg.result_options()
        # 선택값을 prefs 에 기억 → 다음 저장의 기본값
        self._prefs["pdf_save_show_query"] = bool(opts["show_query"])
        self._prefs["pdf_save_show_filename"] = bool(opts["show_filename"])
        self._prefs["pdf_save_show_pageno"] = bool(opts["show_pageno"])
        self._save_settings_now()

        prefix = _dt.datetime.now().strftime("%y%m%d_%H%M_")
        default = f"{prefix}screenshots.pdf"
        out, _ = QFileDialog.getSaveFileName(self, "스크린샷 PDF 저장", default, "PDF (*.pdf)")
        if not out:
            return
        try:
            saved = ss.export_pdf_from_meta(
                meta, out,
                show_query=opts["show_query"],
                show_filename=opts["show_filename"],
                show_pageno=opts["show_pageno"],
            )
            self.status.showMessage(f"PDF 저장: {saved}", 4000)
        except Exception as e:
            QMessageBox.warning(self, "PDF 저장 실패", str(e))

    # ===== 설정 ========================================================
    # v1.6.2: 4단 기본값. 우측 패널 안쪽 세로 splitter 는 self.right_splitter.
    # 260611-75: 책갈피창(1단) 기본 폭 축소(240→185), 줄인 만큼 메인 뷰어(3단)로.
    DEFAULT_SPLITTER_SIZES = [185, 160, 815, 540]
    DEFAULT_RIGHT_SPLITTER_SIZES = [520, 380]

    def _restore_settings(self):
        qs = QSettings()
        geom = qs.value("geometry")
        if geom:
            self.restoreGeometry(geom)

        # v1.6.2: splitter 자식 4개. 이전 v1.6.x 의 5단 저장값은 길이가 안 맞아 폴백됨.
        ss_state = qs.value("splitter")
        restored = False
        # 260611-75: 책갈피창 기본 폭 축소를 1회 강제 적용(옛 240px 저장 폭 무시 → 새 기본).
        if not qs.value("layout_narrow_v1780"):
            qs.setValue("layout_narrow_v1780", "1")
            ss_state = None
        if ss_state:
            try:
                if self.splitter.restoreState(ss_state):
                    sizes = self.splitter.sizes()
                    if (len(sizes) == self.splitter.count()
                            and all(s >= 0 for s in sizes)
                            and sum(sizes) >= 200
                            and sizes[-1] >= 50):
                        restored = True
            except Exception:
                restored = False
        if not restored:
            self.splitter.setSizes(self.DEFAULT_SPLITTER_SIZES)

        # v1.6.2: 우측 세로 splitter 도 복원
        right_state = qs.value("right_splitter")
        right_restored = False
        if right_state:
            try:
                if self.right_splitter.restoreState(right_state):
                    rsz = self.right_splitter.sizes()
                    if (len(rsz) == 2 and all(s >= 0 for s in rsz)
                            and sum(rsz) >= 100):
                        right_restored = True
            except Exception:
                right_restored = False
        if not right_restored:
            self.right_splitter.setSizes(self.DEFAULT_RIGHT_SPLITTER_SIZES)

        data = settings_store.load(self.SETTINGS_FILE)

        # 환경설정 적용 (v1.6.2: history 관련 키 제거)
        self._prefs = dict(data.get("preferences", {}))
        self._prefs.setdefault("restore_session", True)
        self._prefs.setdefault("start_view_single", True)   # 260628-13: 시작 시 1단+쪽맞춤
        # 260830(사용자 결정): 태그 자동 부여는 **옵트인** — 환경설정에서 체크해야 동작.
        #   실사용 정확도 피드백(발표자료→보고서 오분류)으로 기본 꺼짐 전환(태그 SOT §3.5).
        self._prefs.setdefault("auto_tag_enabled", False)
        # ★ 1회 마이그레이션: beta.104 는 옵트인 UI 없이 기본 켜짐으로 나가
        #   settings.json 에 true 가 저장돼 있다 — 그것은 사용자의 명시적 선택이
        #   아니므로 한 번 강제로 끈다(이후에는 환경설정 체크가 유일한 켜는 길).
        if not self._prefs.get("auto_tag_optin_migrated", False):
            self._prefs["auto_tag_enabled"] = False
            self._prefs["auto_tag_optin_migrated"] = True
        self._prefs.setdefault("autotag_summary_shown", False)  # §8.2 첫 실행 요약 1회
        self._prefs.setdefault("restore_last_page", True)
        self._prefs.setdefault("restore_screenshots", True)
        self._prefs.setdefault("screenshot_max", 30)
        self._prefs.setdefault("pdf_save_show_query", False)      # v1.6.4
        self._prefs.setdefault("pdf_save_show_filename", False)   # v1.6.4
        self._prefs.setdefault("pdf_save_show_pageno", False)     # v1.6.4
        self._prefs.setdefault("bookmarker_path", "")             # v1.6.16
        self._prefs.setdefault("bookmarker_mode", "auto")         # v1.6.16
        self._prefs.setdefault("bookmarker_save_pdf", True)       # v1.6.16
        self._prefs.setdefault("bookmarker_overwrite", False)     # 260606-4
        self._prefs.setdefault("bookmarker_ocr_font_auto", True)  # v1.15.0/260606-4
        self._prefs.setdefault("bookmarker_save_txt", False)      # v1.6.16
        self._prefs.setdefault("bookmarker_open_after", True)     # v1.6.16
        self._prefs.setdefault("show_panel_toolbar", True)        # 260606-25: 기본 보이기
        # 260609-2/28: 페이지 경계에서 다음/이전 파일 이동 — 기본 켜짐.
        #   미설정(None 포함)이면 True 로(예전 null 저장본도 켜지도록).
        if self._prefs.get("cross_file_nav") is None:
            self._prefs["cross_file_nav"] = True
        self._prefs.setdefault("hyperlink_url_allowlist", [])     # 260609-3
        self._prefs.setdefault("presentation_pointers", [])       # 260609-5
        self._prefs.setdefault("presentation_pointer_active", 0)  # 260609-5
        self._prefs.setdefault("presentation_overlap_pct", 10)    # 260609-6
        self._prefs.setdefault("presentation_topbar_h", 64)       # 260609-12(D1)
        self._prefs.setdefault("presentation_pens", [])           # 260609-16(F3)
        self._prefs.setdefault("presentation_pen_active", 0)      # 260609-16(F3)
        self._prefs.setdefault("presentation_pen_keys", [])       # 260609-16(F3)
        self._prefs.setdefault("presentation_pen_straight", True) # 260609-18(G3)
        self._prefs.setdefault("presentation_eraser_widths", [12, 30])  # 260609-20(I3)
        # 260611-2: 본문·발표 공유 선긋기 — 옛 main_pens/presentation_pens 에서 1회 승계
        if not self._prefs.get("draw_pens"):
            self._prefs["draw_pens"] = (self._prefs.get("main_pens")
                                        or self._prefs.get("presentation_pens") or [])
        self._prefs.setdefault("draw_line_mode", 0)
        if not self._prefs.get("draw_eraser_widths"):
            self._prefs["draw_eraser_widths"] = (
                self._prefs.get("presentation_eraser_widths") or [12, 30])
        self._prefs.setdefault("draw_highlight_alpha", 35)
        self._prefs.setdefault("capture_global", False)           # 260611-3(6)
        self._prefs.setdefault("recording_dir", "")               # 260609-17(F4)
        self._prefs.setdefault("recording_audio_mode", "mic")     # 260609-17(F4)
        self._prefs.setdefault("recording_mic", "")               # 260609-17(F4)
        self._prefs.setdefault("recording_system", "")            # 260609-17(F4)
        self._prefs.setdefault("recording_keys", [])              # 260609-17(F4)
        self._prefs.setdefault("ffmpeg_path", "")                 # 260609-17(F4)
        self._prefs.setdefault("recording_test_ok", False)        # 260611-25
        self._prefs.setdefault("merge_presets", [])               # 260611-36
        self._prefs.setdefault("hyperlink_top_offset_px", 10)     # 260609-11(C8)
        self._prefs.setdefault("online_dict_enabled", True)       # 260615-9(P11)/260618-10: 기본 켜기
        self._prefs.setdefault("update_repo", "")                 # 260618-11: GitHub OWNER/REPO
        self._prefs.setdefault("auto_check_update", True)         # 260618-11: 시작 시 업데이트 확인
        self._prefs.setdefault("auto_download_update", True)      # 260618-24: 백그라운드 미리 다운로드
        # 260628-6(④): 기본값은 **stable**. 1.0 이전에는 어차피 update_controller 가
        #   채널을 beta 로 강제하므로 오늘 동작은 그대로이고, **1.0 이후** 설정을 만진 적 없는
        #   사용자가 계속 베타를 받는 고착만 막는다. 사용자가 메뉴로 고른 경우엔
        #   `update_channel_explicit=True` 가 찍히므로 그 선택을 존중한다.
        self._prefs.setdefault("update_channel", "stable")        # 260618-33/36, 260628-6
        self._prefs.setdefault("update_channel_explicit", False)  # 260628-6
        try:    # 1.0 전환 1회: 명시 선택이 아니면 stable 로 되돌린다.
            _major = int((__version__.lstrip("vV").split(".")[0]) or "0")
            if (_major >= 1 and not self._prefs.get("update_channel_explicit")
                    and str(self._prefs.get("update_channel", "")).lower() == "beta"):
                self._prefs["update_channel"] = "stable"
        except Exception:
            pass
        self._prefs.setdefault("stdict_key", "")
        self._prefs.setdefault("onterm_key", "")
        self._prefs.setdefault("law_oc", "")
        self._prefs.setdefault("kcsc_key", "")        # 260618-37: 국가건설기준센터 OPEN API 키
        self._prefs.setdefault("kipo_signkey", "")    # 260618-43: 특허(KIPRIS) ServiceKey
        self._prefs.setdefault("patent_save_dir", "")  # 260618-47: 특허 PDF 저장 폴더
        self._prefs.setdefault("translate_auth", "api")   # 260621-P0/P3: api|login(구독 OAuth)
        self._prefs.setdefault("anthropic_api_key", "")   # 260621-P0: 번역(Claude) API 키
        self._prefs.setdefault("translate_model", "claude-opus-4-8")  # 260621-P0
        self._prefs.setdefault("translate_consent", False)  # 260621-P0: 외부 전송 동의
        self._apply_prefs(self._prefs)
        # 260606-19: 단축키 오버라이드 적용
        try:
            self._apply_shortcuts((self._prefs or {}).get("shortcuts", {}))
        except Exception:
            pass
        # 260611-3(6): 화면 캡처 전역 단축키 등록(설정 켜진 경우)
        try:
            self._refresh_global_capture_hotkey()
        except Exception:
            pass

        self._recent_folders = list(data.get("recent_folders", []))
        self._refresh_recent_menu()

        dpi = int(data.get("render_dpi", 192))
        fit_mode = data.get("fit_mode", "쪽 맞춤")
        for mv in self._mv:                       # 260606-8: 두 창 모두 적용
            mv.set_base_dpi(dpi)
            if hasattr(mv, "set_fit_mode"):
                mv.set_fit_mode(fit_mode)

        # v1.6.23: 패널 가시성 — panels_visible 로 저장·복원, 기본 True.
        # panel_show_* prefs 키(v1.6.22 잔재)는 무시.
        legacy = data.get("panels_visible") or {}
        sv = bool(legacy.get("search_results", True))
        self.act_toggle_search.setChecked(sv)
        self.search_tabs.setVisible(sv)          # 260603: 명시 적용(기본 보이기)
        # 260603-3: 스크린샷 패널은 기본 숨김 — 캡처/복원으로 항목이 있으면 자동 표시
        self.act_toggle_shot.setChecked(False)
        self.shot_strip.setVisible(False)
        # 상단 토글 툴바 가시성 (기본 False)
        self._panel_toolbar.setVisible(bool(self._prefs.get("show_panel_toolbar", False)))

        # 즐겨찾기 로드 (세션 복원 여부와 무관)
        self._favorites = list(data.get("favorites", []))
        self._law_favorites = list(data.get("law_favorites", []))   # 260616-6
        self._kcsc_favorites = list(data.get("kcsc_favorites", []))  # 260618-39
        self._kipo_favorites = list(data.get("kipo_favorites", []))  # 260618-43
        self._refresh_favorites_menu()

        # 260603-4: 단어장·읽기 설정 복원(모든 선택 유지)
        try:
            self.study_panel.apply_settings(data.get("study_settings") or {})
            ra = data.get("read_aloud") or {}
            if ra.get("mode"):
                self.read_aloud.mode = ra["mode"]
            if ra.get("rate"):
                self.read_aloud.set_rate(int(ra["rate"]))
            if ra.get("voice"):
                self.read_aloud.set_voice(ra["voice"])
        except Exception:
            pass

        if not self._prefs.get("restore_session", True):
            return

        last = data.get("last_folder")
        if last and Path(last).exists():
            self.open_folder(Path(last))

        # v1.6.2: 스크린샷 복원 — 신규 screenshots_meta 우선, 폴백으로 옛 screenshots
        if self._prefs.get("restore_screenshots", True):
            meta_list = data.get("screenshots_meta")
            if meta_list:
                for m in meta_list:
                    sp = m.get("path", "")
                    if not sp or not Path(sp).exists():
                        continue
                    self.shot_strip.add_item(
                        sp, kind=m.get("kind", "image"),
                        label=Path(sp).stem,
                        page_index=int(m.get("page") or 0),
                        thumb_pdf_path=m.get("src_pdf"),
                        src_pdf=m.get("src_pdf"),
                        src_page=m.get("src_page"),
                        src_query=m.get("src_query"),
                        prepend=False,
                    )
            else:
                for sp in data.get("screenshots", []):
                    if Path(sp).exists():
                        self.shot_strip.add_item(
                            sp, kind="image", label=Path(sp).stem, prepend=False
                        )
        self._ensure_shots_visible()    # 260603-3: 복원된 스크린샷이 있으면 자동 표시

        # 260606-17: 캡쳐 모드/복사크기/사용자 크기 복원
        try:
            self._cap_mode = str(data.get("capture_mode", "full"))
            self._cap_copy = str(data.get("capture_copy", "visible"))
            cs = data.get("capture_sizes")
            if isinstance(cs, list) and cs:
                norm = []
                for i in range(5):
                    s = cs[i] if i < len(cs) else {}
                    norm.append({"name": str(s.get("name", f"사용자{i+1}")),
                                 "w": int(s.get("w", 300)), "h": int(s.get("h", 200))})
                self._cap_sizes = norm
            self._refresh_capture_labels()
        except Exception:
            pass

        # 마지막 메인 문서 복원
        last_main = data.get("last_main")
        if last_main and isinstance(last_main, dict):
            try:
                fp = last_main.get("file_path", "")
                if fp and Path(fp).exists():
                    pg = (last_main.get("page_index") or 0) if self._prefs.get("restore_last_page", True) else 0
                    item = HistoryItem(
                        file_path=fp,
                        page_index=pg,
                        query=last_main.get("query", ""),
                        origin=last_main.get("origin", "bookmark"),
                        label=last_main.get("label", ""),
                    )
                    self._load_main(item)
            except Exception:
                pass

        self._apply_start_view()      # 260628-13: 시작 보기 상태(1단 + 쪽 맞춤)

    def _apply_start_view(self):
        """260628-13(사용자 요청): 프로그램을 켜면 **'1단' + 쪽 맞춤**으로 시작한다.

        마지막 세션의 레이아웃을 그대로 복원하면 2단이거나 검색·스크린샷 패널이 열린 채
        떠서 첫 화면이 어수선했다. `_vm_single()` 은 패널 툴바의 '1단' 버튼과 **같은 동작**
        (2단 해제 + 검색·스크린샷 패널 숨김 + 우측 레이아웃 동기화)이라 별도 로직을 두지 않는다.

        ※ 세션 복원(`_load_main`)이 **끝난 뒤** 불러야 한다 — 문서를 열면서 맞춤 모드가
          다시 잡히므로, 먼저 부르면 덮어써진다.
        ※ 끄고 싶으면 `start_view_single=False` — 그러면 종전처럼 저장된 레이아웃을 따른다.
        """
        if not self._prefs.get("start_view_single", True):
            return
        try:
            self._vm_single()
        except Exception:
            pass
        for mv in getattr(self, "_mv", []):
            try:
                mv.set_fit_mode(mv.FIT_PAGE)      # 콤보 표시까지 함께 갱신된다
            except Exception:
                pass

    # ===== 설정 (v1.5.1) ===============================================
    def action_open_settings(self):
        # 260628(FIX): `SettingsDialog` 가 어디에서도 import 되지 않아 이 메서드를 호출하면
        #   NameError 로 **앱이 그대로 종료**됐다(설정 창을 못 여는 치명적 결함).
        #   같은 클래스의 `_open_recording_settings` 는 자기 안에서 지역 import 를 하고 있어
        #   문제가 없었고, 그 지역 import 는 이 메서드의 이름 해석에 아무 영향이 없다.
        #   ※ 배포본 beta.79(HEAD)에도 동일하게 존재하던 기존 결함(pyflakes 로 확인).
        from viewer.widgets.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._prefs, self, host=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            new_prefs = dlg.result_prefs()
            self._apply_prefs(new_prefs)
            # 즉시 settings.json 저장
            self._save_settings_now()
            self.status.showMessage("설정 저장됨", 3000)

    def _apply_prefs(self, prefs: dict):
        # v1.6.2: history 관련 키 제거. screenshot_max 만 한도로.
        # v1.6.4: SettingsDialog 가 모르는 pdf_save_* 키는 기존 self._prefs 에서 보존.
        old = dict(getattr(self, "_prefs", {}) or {})
        def _pdf(k):
            return bool(prefs.get(k, old.get(k, False)))
        self._prefs = {
            "restore_session": prefs.get("restore_session", True),
            # 260628-13: 허용목록 방식이라 여기 없으면 저장되지 않는다.
            "start_view_single": bool(prefs.get("start_view_single",
                                              old.get("start_view_single", True))),
            # 260829 P2: 태그 자동 부여 — 허용목록 미등재 시 조용히 유실(§14.2 함정)
            "auto_tag_enabled": bool(prefs.get("auto_tag_enabled",
                                               old.get("auto_tag_enabled", False))),
            "auto_tag_optin_migrated": bool(prefs.get("auto_tag_optin_migrated",
                                            old.get("auto_tag_optin_migrated", False))),
            "autotag_summary_shown": bool(prefs.get("autotag_summary_shown",
                                                    old.get("autotag_summary_shown", False))),
            "restore_last_page": prefs.get("restore_last_page", True),
            "restore_screenshots": prefs.get("restore_screenshots", True),
            "screenshot_max": int(prefs.get("screenshot_max", 30)),
            "pdf_save_show_query": _pdf("pdf_save_show_query"),
            "pdf_save_show_filename": _pdf("pdf_save_show_filename"),
            "pdf_save_show_pageno": _pdf("pdf_save_show_pageno"),
            # v1.6.16: 책갈피 자동 생성 옵션 (다이얼로그 기본값 — SettingsDialog 미관리)
            "bookmarker_path": str(prefs.get("bookmarker_path",
                                             old.get("bookmarker_path", ""))),
            "bookmarker_mode": str(prefs.get("bookmarker_mode",
                                             old.get("bookmarker_mode", "auto"))),
            "bookmarker_save_pdf": bool(prefs.get("bookmarker_save_pdf",
                                                  old.get("bookmarker_save_pdf", True))),
            "bookmarker_overwrite": bool(prefs.get("bookmarker_overwrite",
                                                   old.get("bookmarker_overwrite", False))),
            "bookmarker_ocr_font_auto": bool(prefs.get("bookmarker_ocr_font_auto",
                                                       old.get("bookmarker_ocr_font_auto", True))),
            "bookmarker_save_txt": bool(prefs.get("bookmarker_save_txt",
                                                  old.get("bookmarker_save_txt", False))),
            "bookmarker_open_after": bool(prefs.get("bookmarker_open_after",
                                                    old.get("bookmarker_open_after", True))),
            # v1.6.23: 패널 토글 툴바 가시성만 prefs 로 관리
            "show_panel_toolbar": bool(prefs.get(
                "show_panel_toolbar", old.get("show_panel_toolbar", True))),
            # 260609-2/28: 페이지 경계에서 다음/이전 파일로 이동 — 미설정이면 켜짐
            "cross_file_nav": (lambda v: True if v is None else bool(v))(
                prefs.get("cross_file_nav", old.get("cross_file_nav"))),
            # 260609-3: 하이퍼링크 URL 허용 도메인
            "hyperlink_url_allowlist": list(prefs.get(
                "hyperlink_url_allowlist",
                old.get("hyperlink_url_allowlist", []))),
            # 260609-11(C8): 페이지 내 하이퍼링크 버튼 상단 오프셋
            "hyperlink_top_offset_px": int(prefs.get(
                "hyperlink_top_offset_px",
                old.get("hyperlink_top_offset_px", 10))),
            # 260609-5: 발표 포인터
            "presentation_pointers": list(prefs.get(
                "presentation_pointers",
                old.get("presentation_pointers", []))),
            "presentation_pointer_active": int(prefs.get(
                "presentation_pointer_active",
                old.get("presentation_pointer_active", 0))),
            # 260609-6: 발표 겹침%(분할 여부는 260628 부터 자동 판정 — 설정 제거)
            "presentation_overlap_pct": int(prefs.get(
                "presentation_overlap_pct",
                old.get("presentation_overlap_pct", 10))),
            "presentation_topbar_h": int(prefs.get(
                "presentation_topbar_h",
                old.get("presentation_topbar_h", 64))),
            # 260609-16(F3): 발표 펜
            "presentation_pens": list(prefs.get(
                "presentation_pens", old.get("presentation_pens", []))),
            "presentation_pen_active": int(prefs.get(
                "presentation_pen_active", old.get("presentation_pen_active", 0))),
            "presentation_pen_keys": list(prefs.get(
                "presentation_pen_keys", old.get("presentation_pen_keys", []))),
            "presentation_pen_straight": bool(prefs.get(
                "presentation_pen_straight", old.get("presentation_pen_straight", True))),
            "presentation_eraser_widths": list(prefs.get(
                "presentation_eraser_widths", old.get("presentation_eraser_widths", [12, 30]))),
            # 260611-2: 본문·발표 공유 선긋기 설정
            "draw_pens": list(prefs.get("draw_pens", old.get("draw_pens", []))),
            "draw_line_mode": int(prefs.get("draw_line_mode", old.get("draw_line_mode", 0))),
            "draw_eraser_widths": list(prefs.get(
                "draw_eraser_widths", old.get("draw_eraser_widths", [12, 30]))),
            "draw_highlight_alpha": int(prefs.get(
                "draw_highlight_alpha", old.get("draw_highlight_alpha", 35))),
            "capture_global": bool(prefs.get(
                "capture_global", old.get("capture_global", False))),
            # 260609-17(F4): 녹화
            "recording_dir": str(prefs.get("recording_dir", old.get("recording_dir", ""))),
            "recording_audio_mode": str(prefs.get(
                "recording_audio_mode", old.get("recording_audio_mode", "mic"))),
            "recording_mic": str(prefs.get("recording_mic", old.get("recording_mic", ""))),
            "recording_system": str(prefs.get("recording_system", old.get("recording_system", ""))),
            "recording_keys": list(prefs.get("recording_keys", old.get("recording_keys", []))),
            "ffmpeg_path": str(prefs.get("ffmpeg_path", old.get("ffmpeg_path", ""))),
            # 260611-25: 녹화 테스트 합격 결과(테스트에서 직접 기록 → 여기선 보존)
            "recording_test_ok": bool(prefs.get("recording_test_ok",
                                                old.get("recording_test_ok", False))),
            # 260611-36: 병합 배치 사용자 스타일(SettingsDialog 미관리 → 보존)
            "merge_presets": list(prefs.get("merge_presets",
                                            old.get("merge_presets", []))),
            # 260606-13: 화면 스타일(테마)
            "theme": str(prefs.get("theme", old.get("theme", "auto"))),
            # 260615-9(P11): 인터넷 사전(단어장)
            "online_dict_enabled": bool(prefs.get("online_dict_enabled",
                                                  old.get("online_dict_enabled", True))),
            "stdict_key": str(prefs.get("stdict_key", old.get("stdict_key", ""))),
            "onterm_key": str(prefs.get("onterm_key", old.get("onterm_key", ""))),
            "law_oc": str(prefs.get("law_oc", old.get("law_oc", ""))),
            "kcsc_key": str(prefs.get("kcsc_key", old.get("kcsc_key", ""))),  # 260618-37
            "kipo_signkey": str(prefs.get("kipo_signkey", old.get("kipo_signkey", ""))),  # 260618-43
            "patent_save_dir": str(prefs.get("patent_save_dir", old.get("patent_save_dir", ""))),  # 260618-47
            # 260621-P0: 번역(Claude)
            "translate_auth": str(prefs.get("translate_auth", old.get("translate_auth", "api"))),
            "anthropic_api_key": str(prefs.get("anthropic_api_key", old.get("anthropic_api_key", ""))),
            "translate_model": str(prefs.get("translate_model", old.get("translate_model", "claude-opus-4-8"))),
            "translate_consent": bool(prefs.get("translate_consent", old.get("translate_consent", False))),
            # 260618-11: 업데이트(GitHub Releases)
            "update_repo": str(prefs.get("update_repo", old.get("update_repo", ""))),
            "auto_check_update": bool(prefs.get("auto_check_update",
                                                old.get("auto_check_update", True))),
            "auto_download_update": bool(prefs.get("auto_download_update",
                                                  old.get("auto_download_update", True))),
            "update_channel": str(prefs.get("update_channel",
                                            old.get("update_channel", "stable"))),  # 260618-33, 260628-6/36
            # 260628-6(④): 사용자가 메뉴로 직접 고른 값인지 — 1.0 전환 마이그레이션이 이 값을 보고
            #   덮어쓸지 정하므로 **반드시 함께 저장**한다(페이로드는 허용목록 방식이라 누락 시 유실).
            "update_channel_explicit": bool(prefs.get(
                "update_channel_explicit", old.get("update_channel_explicit", False))),
            # 260606-19: 단축키 오버라이드 보존
            "shortcuts": prefs.get("shortcuts", old.get("shortcuts", {})),
        }
        s = self._prefs["screenshot_max"]
        self.shot_strip.set_max_items(s)
        # 즉시 반영
        try:
            self._panel_toolbar.setVisible(self._prefs["show_panel_toolbar"])
        except Exception:
            pass
        self.apply_theme(self._prefs.get("theme", "auto"))
        # 260609-11(C8): 페이지 내 하이퍼링크 버튼 상단 오프셋 적용
        try:
            off = int(self._prefs.get("hyperlink_top_offset_px", 10))
            for mv in self._mv:
                mv.set_hyperlink_offset(off)
        except Exception:
            pass
        # 260621-P3: API 키 미입력 기능 게이팅
        try:
            self._gate_api_dependent_ui(self._prefs)
        except Exception:
            pass

    def _gate_api_dependent_ui(self, prefs: dict):
        """260621-P3: 외부 API 키가 없으면 관련 툴바 버튼은 숨기고 메뉴 항목은 비활성화.
        키가 입력되면 다시 보이게/활성화. (법령·고시/건설기준/특허/번역)"""
        p = prefs or {}
        has_law = bool(str(p.get("law_oc", "")).strip())
        has_kcsc = bool(str(p.get("kcsc_key", "")).strip())
        has_kipo = bool(str(p.get("kipo_signkey", "")).strip())
        has_tr = (str(p.get("translate_auth", "api")).strip() == "login"
                  or bool(str(p.get("anthropic_api_key", "")).strip()))
        va = getattr(self, "_view_acts", {}) or {}

        def _btn(name, on):
            # 260628(FIX): 툴바 위젯은 액션 가시성으로 제어해야 실제로 숨겨진다(위 mk 주석).
            b = getattr(self, name, None)
            if b is None:
                return
            act = getattr(b, "_tb_action", None)
            if act is not None:
                act.setVisible(on)
            b.setVisible(on)

        def _act_en(a, on):
            if a is not None:
                a.setEnabled(on)        # 메뉴 항목은 활성/비활성

        # 법령·고시
        _btn("_btn_law", has_law)
        _act_en(va.get("법령/고시"), has_law)
        _act_en(getattr(self, "_act_law", None), has_law)
        # 건설기준(KCSC)
        _btn("_btn_kcsc", has_kcsc)
        _act_en(va.get("건설기준(KCSC)"), has_kcsc)
        _act_en(getattr(self, "_act_kcsc", None), has_kcsc)
        # 특허(KIPO)
        _btn("_btn_kipo", has_kipo)
        _act_en(va.get("특허(등록정보)"), has_kipo)
        _act_en(getattr(self, "_act_kipo", None), has_kipo)
        # 번역(Claude) — 툴바 'PDF번역' 버튼 + 메뉴
        _btn("_btn_tr", has_tr)
        _act_en(getattr(self, "_act_tr_files", None), has_tr)

    def apply_theme(self, mode: str):
        """260606-13: 화면 스타일 적용 — light/dark/auto(시스템). Fusion+팔레트."""
        from PyQt6.QtWidgets import QApplication, QStyleFactory
        from PyQt6.QtGui import QPalette, QColor
        from PyQt6.QtCore import Qt as _Qt
        app = QApplication.instance()
        if app is None:
            return
        mode = (mode or "auto").lower()
        if mode == "auto":
            try:
                dark = app.styleHints().colorScheme() == _Qt.ColorScheme.Dark
            except Exception:
                dark = False
        else:
            dark = (mode == "dark")
        from viewer import theme as _theme
        _theme.set_dark(dark)
        app.setStyle(QStyleFactory.create("Fusion"))
        # 260618-16: Qt6.5+ 에서 시스템이 다크면 standardPalette() 가 다크를 반환 →
        #   '밝게'를 골라도 대부분 검게 보이던 문제. 라이트는 **명시적 라이트 팔레트** 강제.
        if not dark:
            try:
                app.styleHints().setColorScheme(_Qt.ColorScheme.Light)   # Qt6.8+(있으면)
            except Exception:
                pass
            lp = QPalette()
            win = QColor(240, 240, 240); base = QColor(255, 255, 255)
            txt = QColor(26, 26, 26); hl = QColor(38, 110, 200)
            lp.setColor(QPalette.ColorRole.Window, win)
            lp.setColor(QPalette.ColorRole.WindowText, txt)
            lp.setColor(QPalette.ColorRole.Base, base)
            lp.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
            lp.setColor(QPalette.ColorRole.Text, txt)
            lp.setColor(QPalette.ColorRole.Button, win)
            lp.setColor(QPalette.ColorRole.ButtonText, txt)
            lp.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 225))
            lp.setColor(QPalette.ColorRole.ToolTipText, txt)
            lp.setColor(QPalette.ColorRole.PlaceholderText, QColor(120, 120, 120))
            lp.setColor(QPalette.ColorRole.Highlight, hl)
            lp.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            lp.setColor(QPalette.ColorRole.Link, QColor(20, 90, 200))
            dis = QColor(150, 150, 150)
            for r in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                      QPalette.ColorRole.WindowText):
                lp.setColor(QPalette.ColorGroup.Disabled, r, dis)
            app.setPalette(lp)
            app.setStyleSheet("")
            self._apply_theme_widgets(False)
            return
        try:
            app.styleHints().setColorScheme(_Qt.ColorScheme.Dark)
        except Exception:
            pass
        p = QPalette()
        bg = QColor(45, 45, 48); base = QColor(30, 30, 32)
        txt = QColor(230, 230, 230); hl = QColor(38, 110, 200)
        p.setColor(QPalette.ColorRole.Window, bg)
        p.setColor(QPalette.ColorRole.WindowText, txt)
        p.setColor(QPalette.ColorRole.Base, base)
        p.setColor(QPalette.ColorRole.AlternateBase, bg)
        p.setColor(QPalette.ColorRole.Text, txt)
        p.setColor(QPalette.ColorRole.Button, bg)
        p.setColor(QPalette.ColorRole.ButtonText, txt)
        p.setColor(QPalette.ColorRole.ToolTipBase, base)
        p.setColor(QPalette.ColorRole.ToolTipText, txt)
        p.setColor(QPalette.ColorRole.Highlight, hl)
        p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        p.setColor(QPalette.ColorRole.Link, QColor(90, 160, 255))
        dis = QColor(130, 130, 130)
        for r in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                  QPalette.ColorRole.WindowText):
            p.setColor(QPalette.ColorGroup.Disabled, r, dis)
        app.setPalette(p)
        self._apply_theme_widgets(True)

    def _apply_theme_widgets(self, dark: bool):
        """260606-14: 팔레트로 안 잡히는 곳(메인뷰 배경·드로어·썸네일 카드)에 테마 반영."""
        # 260606-15: 스타일시트가 설정된 위젯은 팔레트 변경만으론 갱신 안 됨 → 재폴리시
        # 260606-27: 팔레트 의존(스타일시트 없는) 버튼/메뉴는 repaint 가 안 와서
        #            전환 직후 옛 색으로 남았다가 클릭해야 갱신되던 문제 → 전 위젯 update()
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            # 260611-10: 팔레트만 바꾸면 '뷰어 위 버튼' 등 일부 위젯이 클릭 전까지 옛 배경으로
            #   남던 문제 → 스타일시트 유무와 무관하게 **모든 위젯을 재폴리시**(팔레트 재적용)
            #   후 repaint. 테마 전환은 드물어 비용 허용.
            for w in app.allWidgets():
                try:
                    st = w.style()
                    st.unpolish(w)
                    st.polish(w)
                    w.update()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            for mv in getattr(self, "_mv", []):
                mv.apply_theme(dark)
        except Exception:
            pass
        try:
            if getattr(self, "_drawer", None) is not None:
                if dark:
                    self._drawer.setStyleSheet(
                        "QWidget#drawer{background:#2d2d30; border-left:1px solid #555;}")
                else:
                    self._drawer.setStyleSheet(
                        "QWidget#drawer{background:#f3f3f3; border-left:1px solid #aaa;}")
        except Exception:
            pass
        try:
            self.shot_strip.refresh_cards()
        except Exception:
            pass
        try:
            self._style_panel_toolbar(dark)   # 260606-26: 패널 버튼 테마색
        except Exception:
            pass
        try:
            self.page_thumbs._rerender_all()  # 260609-21(J4): 번호 띠 테마색 갱신
        except Exception:
            pass

    def _build_settings_payload(self) -> dict:
        """settings.json 저장 페이로드 (closeEvent / _save_settings_now 공용)."""
        return {
            "schema_version": settings_store.CURRENT_SCHEMA,
            "render_dpi": self.main_view._base_dpi,
            "fit_mode": self.main_view._fit_mode,
            "last_folder": str(self._folder) if self._folder else "",
            "recent_folders": self._recent_folders,
            # v1.6.2: history 키 제거. 옛 screenshots(PNG 경로만)는 호환을 위해 같이 저장.
            "screenshots": self.shot_strip.all_paths(),
            "screenshots_meta": self.shot_strip.all_meta(),
            "panels_visible": {
                "search_results": self.act_toggle_search.isChecked(),
                "screenshots": self.act_toggle_shot.isChecked(),
            },
            "last_main": (self._current_main.to_dict() if self._current_main else None),
            # 260606-17: 캡쳐 모드/복사크기/사용자 크기
            "capture_mode": getattr(self, "_cap_mode", "full"),
            "capture_copy": getattr(self, "_cap_copy", "visible"),
            "capture_sizes": getattr(self, "_cap_sizes", []),
            "preferences": self._prefs,
            "favorites": self._favorites,
            "law_favorites": self._law_favorites,
            "kcsc_favorites": self._kcsc_favorites,   # 260618-39
            "kipo_favorites": self._kipo_favorites,   # 260618-43
            # 260603-4: 단어장·읽기 모든 선택/설정 저장
            "study_settings": self.study_panel.get_settings(),
            "read_aloud": {
                "mode": self.read_aloud.mode,
                "rate": self.read_aloud.rate,
                "voice": self.read_aloud.voice_name or "",
            },
        }

    def _save_settings_now(self):
        settings_store.save(self._build_settings_payload(), self.SETTINGS_FILE)

    # ===== 즐겨찾기 (v1.6.1 F1~F7) =====================================
    def _save_current_as_default(self):
        """260611-91: 현재 설정·스타일을 배포용 기본값(default_settings.json)으로 저장.
        즐겨찾기·최근폴더·세션·머신 경로 등 개인 항목은 제외된다."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "기본값으로 저장(배포용)",
                                        "기본값 이름(배포 식별용):", text="내 기본값")
        if not ok:
            return
        data = settings_store.extract_distributable_defaults(
            self._build_settings_payload(), (name or "기본값").strip())
        p = settings_store.default_profile_path()
        try:
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "저장 실패", f"기본값을 저장하지 못했습니다.\n{e}")
            return
        QMessageBox.information(
            self, "기본값 저장 완료",
            "현재 설정·스타일을 기본값으로 저장했습니다.\n\n"
            f"파일: {p}\n\n"
            "• 이 파일을 프로그램 폴더에 함께 배포하면, 새 설치 시 이 설정으로 시작합니다.\n"
            "• '설정 초기화'를 누르면 이 기본값으로 되돌아갑니다.\n"
            "• 즐겨찾기·최근 폴더·세션·녹화/ffmpeg 경로 등 개인·머신 항목은 제외되었습니다.")

    def _reset_to_defaults(self):
        """260611-91: 설정·스타일을 기본값(동봉 프로파일, 없으면 공장값)으로 초기화.
        개인·머신 항목(즐겨찾기·최근폴더·세션·경로)은 유지. 적용 위해 재시작."""
        prof = settings_store.load_default_profile()
        src = (f"동봉된 기본값('{prof.get('profile_name', '기본값')}')"
               if prof else "공장 기본값")
        ret = QMessageBox.question(
            self, "설정 초기화",
            f"설정과 스타일을 {src}으로 되돌립니다.\n"
            "(즐겨찾기·최근 폴더·세션·녹화/ffmpeg 경로 등 개인 항목은 유지)\n\n"
            "적용을 위해 프로그램이 다시 시작됩니다. 계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        try:
            cur = settings_store.load(self.SETTINGS_FILE)
            merged = settings_store.merge_reset(cur, prof)
            settings_store.save(merged, self.SETTINGS_FILE)
        except Exception as e:
            QMessageBox.warning(self, "초기화 실패", f"설정 초기화에 실패했습니다.\n{e}")
            return
        self._skip_save_on_close = True       # 닫을 때 옛 메모리 상태로 덮어쓰지 않도록
        self._restart_app()

    def _restart_app(self):
        """260611-91: 앱 재시작(설정 초기화 적용)."""
        import sys
        from PyQt6.QtCore import QProcess
        try:
            if getattr(sys, "frozen", False):
                QProcess.startDetached(sys.executable)
            else:
                QProcess.startDetached(sys.executable, sys.argv)
        except Exception:
            pass
        self.close()

    def _app_base_dir(self) -> Path:
        """실행 파일(또는 개발 시 패키지) 기준 디렉터리 — 이동식 디스크 상대경로 해석 기준."""
        import sys
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[1]

    def _fav_rel(self, target) -> str:
        """target 이 실행 파일과 같은 드라이브면 실행 파일 기준 상대경로 반환(아니면 '')."""
        try:
            import os
            base = self._app_base_dir()
            t = Path(target).resolve()
            if t.drive.lower() == base.drive.lower():
                return os.path.relpath(str(t), str(base))
        except Exception:
            pass
        return ""

    def _fav_resolve(self, fav: dict):
        """즐겨찾기 대상 경로(폴더/파일)를 해석. 절대경로 우선, 없으면 실행파일 기준 상대경로로
        재해석(드라이브 문자 변경 대응). 존재하면 경로 문자열, 없으면 None.

        260618-6: kind 에 따라 대상을 구분 — file 즐겨찾기는 '파일'을, folder/search
        즐겨찾기는 '폴더'를 연다. (folder 즐겨찾기에 편의용 `file` 키가 함께 저장돼 있어도
        그것은 폴더를 연 뒤 이동할 파일일 뿐, 폴더 열기 대상이 아니다. 과거에는 file 을
        우선해 folder 즐겨찾기가 PDF 파일 경로로 open_folder 되어 책갈피창이 비던 버그.)"""
        if fav.get("kind", "folder") == "file":
            abs_p = fav.get("file") or fav.get("folder") or ""
        else:
            abs_p = fav.get("folder") or ""
        if abs_p and Path(abs_p).exists():
            return abs_p
        rel = fav.get("rel") or ""
        if rel:
            try:
                cand = (self._app_base_dir() / rel).resolve()
                if cand.exists():
                    return str(cand)
            except Exception:
                pass
        return None

    def _refresh_favorites_menu(self):
        from PyQt6.QtGui import QAction
        self.menu_favorites.clear()
        a_add_folder = QAction("현재 폴더를 즐겨찾기에 추가...", self)
        a_add_folder.triggered.connect(self._add_current_folder_favorite)
        self.menu_favorites.addAction(a_add_folder)

        a_add_file = QAction("현재 파일을 즐겨찾기에 추가...", self)
        a_add_file.triggered.connect(self._add_current_file_favorite)
        self.menu_favorites.addAction(a_add_file)

        a_add_search = QAction("현재 검색어를 즐겨찾기에 추가...", self)
        a_add_search.triggered.connect(self._add_current_search_favorite)
        self.menu_favorites.addAction(a_add_search)

        self.menu_favorites.addSeparator()
        a_manage = QAction("즐겨찾기 관리...", self)
        a_manage.triggered.connect(self._open_favorites_manager)
        self.menu_favorites.addAction(a_manage)

        if self._favorites:
            self.menu_favorites.addSeparator()
            for f in self._favorites:
                kind = f.get("kind", "folder")
                prefix = {"folder": "📁 ", "file": "📄 ", "search": "🔍 "}.get(kind, "📁 ")
                act = QAction(prefix + f.get("name", "?"), self)
                # 대상이 없으면(이동/삭제) 비활성화 표시
                if self._fav_resolve(f) is None:
                    act.setEnabled(False)
                    act.setText(prefix + f.get("name", "?") + "  (없음)")
                else:
                    act.triggered.connect(lambda _checked=False, ff=f: self._open_favorite(ff))
                self.menu_favorites.addAction(act)
        elif not self._law_favorites:
            placeholder = QAction("(아직 등록된 즐겨찾기 없음)", self)
            placeholder.setEnabled(False)
            self.menu_favorites.addAction(placeholder)

        # 260616-6: 법령·고시 즐겨찾기는 항상 전체 즐겨찾기 '아래'에 별도 구역으로.
        if self._law_favorites:
            self.menu_favorites.addSeparator()
            hdr = QAction("법령·고시 즐겨찾기", self)
            hdr.setEnabled(False)
            self.menu_favorites.addAction(hdr)
            for f in self._law_favorites:
                label = "⚖ " + f.get("name", "?")
                kl = f.get("kind_label") or f.get("category")
                if kl:
                    label += f"  ({kl})"
                act = QAction(label, self)
                act.triggered.connect(
                    lambda _checked=False, ff=f: self._open_law_favorite(ff))
                self.menu_favorites.addAction(act)

        # 260618-40: 건설기준(KCSC) 즐겨찾기 — 법령·고시 아래 별도 구역
        if self._kcsc_favorites:
            self.menu_favorites.addSeparator()
            hdr = QAction("건설기준(KCSC) 즐겨찾기", self)
            hdr.setEnabled(False)
            self.menu_favorites.addAction(hdr)
            for f in self._kcsc_favorites:
                label = "🏗 " + f.get("name", "?")
                cat = f.get("category")
                if cat:
                    label += f"  ({cat})"
                act = QAction(label, self)
                act.triggered.connect(
                    lambda _checked=False, ff=f: self._open_kcsc_favorite(ff))
                self.menu_favorites.addAction(act)

        # 260618-43: 특허(KIPO) 등록정보 즐겨찾기 — 별도 구역
        if self._kipo_favorites:
            self.menu_favorites.addSeparator()
            hdr = QAction("특허(KIPO) 즐겨찾기", self)
            hdr.setEnabled(False)
            self.menu_favorites.addAction(hdr)
            for f in self._kipo_favorites:
                label = "📄 " + (f.get("name") or f.get("appNo") or f.get("regNo") or "특허")
                act = QAction(label, self)
                act.triggered.connect(
                    lambda _checked=False, ff=f: self._open_kipo_favorite(ff))
                self.menu_favorites.addAction(act)

    def _add_current_folder_favorite(self):
        if not self._folder:
            QMessageBox.information(self, "안내", "먼저 폴더를 여세요.")
            return
        from viewer.widgets.favorites_dialog import AddFavoriteDialog, make_unique_name
        suggested = make_unique_name(self._folder.name, self._favorites)
        dlg = AddFavoriteDialog(suggested, "folder", self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.name():
            fav = {
                "name": dlg.name(),
                "kind": "folder",
                "folder": str(self._folder),
                "rel": self._fav_rel(self._folder),
            }
            # 260615-4: ⑩ 현재 열린 파일도 기록 → 즐겨찾기로 열면 폴더(책갈피)+그 파일 첫 페이지
            cur = self.main_view.current_file() if self.main_view else None
            if cur and str(cur).lower().endswith(".pdf"):
                fav["file"] = str(cur)
            self._favorites.append(fav)
            self._refresh_favorites_menu()
            self._save_settings_now()

    def _add_current_file_favorite(self):
        """260611-65: 현재 뷰어에 표시 중인 파일을 즐겨찾기에 추가."""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur:
            QMessageBox.information(self, "안내", "먼저 파일을 여세요.")
            return
        self._add_file_favorite(str(cur))

    def _add_file_favorite(self, file_path: str):
        """260615-4: ⑪⑫ 개별 파일을 즐겨찾기로 등록(열면 책갈피에 그 파일만 표시)."""
        from viewer.widgets.favorites_dialog import AddFavoriteDialog, make_unique_name
        p = Path(file_path)
        if not (p.exists() and p.suffix.lower() == ".pdf"):
            QMessageBox.information(self, "안내", "PDF 파일을 선택하세요.")
            return
        suggested = make_unique_name(p.stem, self._favorites)
        dlg = AddFavoriteDialog(suggested, "folder", self)   # 이름 입력 재사용
        dlg.setWindowTitle("현재 파일 즐겨찾기 추가")
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.name():
            self._favorites.append({
                "name": dlg.name(),
                "kind": "file",
                "file": str(p),
                "folder": str(p.parent),
                "rel": self._fav_rel(p),
            })
            self._refresh_favorites_menu()
            self._save_settings_now()

    def _add_current_search_favorite(self):
        q = self.search_bar.current_query()
        if not q:
            QMessageBox.information(self, "안내", "검색어가 비어있습니다.")
            return
        if not self._folder:
            QMessageBox.information(self, "안내", "검색은 폴더 컨텍스트에서만 등록됩니다.")
            return
        from viewer.widgets.favorites_dialog import AddFavoriteDialog, make_unique_name
        suggested = make_unique_name(q, self._favorites)
        dlg = AddFavoriteDialog(suggested, "search", self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.name():
            self._favorites.append({
                "name": dlg.name(),
                "kind": "search",
                "folder": str(self._folder),
                "rel": self._fav_rel(self._folder),
                "query": q,
            })
            self._refresh_favorites_menu()
            self._save_settings_now()

    def _open_favorites_manager(self):
        from viewer.widgets.favorites_dialog import FavoritesDialog
        dlg = FavoritesDialog(self._favorites, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._favorites = dlg.result_favorites()
            self._refresh_favorites_menu()
            self._save_settings_now()

    def _open_favorite(self, fav: dict):
        """즐겨찾기 항목 클릭 — 폴더/파일 열기 또는 폴더+검색 실행.
        절대경로가 없으면 실행파일 기준 상대경로로 재해석(이동식 디스크 드라이브 변경 대응)."""
        target = self._fav_resolve(fav)
        if target is None:
            QMessageBox.warning(self, "오류",
                                f"대상을 찾을 수 없습니다:\n{fav.get('file') or fav.get('folder')}")
            self._refresh_favorites_menu()
            return
        kind = fav.get("kind", "folder")
        if kind == "file":
            # 260615-4: ⑪ 개별 파일 즐겨찾기 → 단일 파일로 열어 책갈피에 그 파일만 표시
            self.open_pdf(Path(target))
            return
        self.open_folder(Path(target))
        # 260618-28: 폴더를 연 '그 창'(2단이면 활성=드롭/즐겨찾기 대상 창)에 파일을 로드해야 한다.
        #   종전엔 항상 _on_bookmark_activated(=좌측/1창)로 보내서, 2창에서 즐겨찾기로 폴더를
        #   바꾸면 하단 책갈피만 바뀌고 2창 뷰어는 그대로(파일이 1창에 열리는) 버그가 있었음.
        pane = self._active_pane if getattr(self, "_split_on", False) else 0

        def _open_in_pane(path, page=0):
            if pane == 1:
                self._on_bookmark_activated_right(str(path), page)
            else:
                self._on_bookmark_activated(str(path), page)

        # 260615-4: ⑩ 폴더 즐겨찾기에 파일이 기록돼 있으면 그 파일 첫 페이지로
        f = fav.get("file")
        if f and Path(f).exists():
            _open_in_pane(f, 0)
        elif kind == "folder":
            # 파일 미기록 폴더 즐겨찾기 → 그 창에 정렬순 첫 파일 첫 페이지(드롭과 동일 동작)
            tree = self.bookmark_tree_right if pane == 1 else self.bookmark_tree
            try:
                files = tree.ordered_pdf_files() or tree.all_file_paths() or []
            except Exception:
                files = []
            if files:
                _open_in_pane(files[0], 0)
        if kind == "search":
            q = fav.get("query", "")
            if q:
                self.search_bar.edit.setText(q)
                self.action_search(q)

    def closeEvent(self, event):
        # 260611-17: 편집모드에서 X(종료) 시 저장/저장 안 함/취소 선택
        if not self._confirm_close_edit():
            event.ignore()
            return

        # 260618-24(C): 새 버전이 준비돼 있으면 종료 시 업그레이드 후 종료 제안
        if getattr(self, "_pending_update", None) and not getattr(self, "_updating", False):
            info = self._pending_update
            ver = info.get("version", "")
            # 260618-36: 베타면 명시
            try:
                from viewer import updater as _u
                _kind = "베타(테스트) 버전" if _u.is_prerelease_tag(info.get("tag", "")) else "버전"
            except Exception:
                _kind = "버전"
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("업그레이드")
            box.setText(f"새 {_kind} v{ver} 이(가) 준비되어 있습니다.\n"
                        "업그레이드 후 종료할까요?")
            b_up = box.addButton("업그레이드 후 종료", QMessageBox.ButtonRole.AcceptRole)
            b_no = box.addButton("그냥 종료", QMessageBox.ButtonRole.DestructiveRole)
            b_cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(b_up)
            box.exec()
            clicked = box.clickedButton()
            if clicked is b_cancel:
                event.ignore()
                return
            if clicked is b_up:
                if not self._begin_upgrade():
                    QMessageBox.warning(self, "업그레이드",
                                        "업그레이드 시작에 실패했습니다. 그냥 종료합니다.")
            # b_no → 그냥 종료(업그레이드 안 함)

        # 260628(발표 SOT §9): ★ 종료 전 **녹화 안전 종료**. 이 처리가 없으면 발표 녹화 중
        #   앱을 닫았을 때 ffmpeg 가 'q'(정상 종료 신호)를 받지 못해 **MP4 moov 가 기록되지
        #   않아 녹화 파일이 깨지고**, ffmpeg 프로세스가 고아로 남는다(2026-08-28 실측 확인).
        #   발표창을 ESC 로 닫는 경로에는 이미 있었으나 앱 종료 경로에는 없었다.
        #   위치 주의: 위의 event.ignore() 분기(편집 저장 확인·업그레이드 취소)보다 **뒤**여야
        #   사용자가 종료를 취소했을 때 녹화가 끊기지 않는다.
        try:
            self._stop_rec_watch()          # 260628(B6): 의도된 종료 → 경고 안 띄움
            _r = getattr(self, "_rec", None)
            if _r is not None and _r.is_recording():
                self.status.showMessage("녹화를 마무리하는 중…")
                QApplication.processEvents()
                _r.stop()                      # stdin 'q' → moov 정상 마감(최대 8초 대기)
                self._rec = None
        except Exception:
            pass

        qs = QSettings()
        qs.setValue("geometry", self.saveGeometry())
        qs.setValue("splitter", self.splitter.saveState())
        qs.setValue("right_splitter", self.right_splitter.saveState())  # v1.6.2

        # 260611-91: 설정 초기화 재시작 중이면 옛 메모리 상태로 settings.json 을 덮어쓰지 않음
        if not getattr(self, "_skip_save_on_close", False):
            self._save_settings_now()
        # 260628-15: 종료를 `os._exit` 로 끝내 atexit 가 돌지 않으므로 여기서 직접 정리한다.
        try:
            self.cleanup_print_tmpdirs()
        except Exception:
            pass
        super().closeEvent(event)

    def _release_render_memory(self):
        """260829(§19.11 P-C): 렌더 캐시·fitz 스토어 자발 해제.

        메모리 압박 시 OS 가 워킹셋을 통째로 트림하면 복귀가 초 단위로 언다 —
        트림당하기 전에 스스로 비워 스왑 오염을 줄인다. 복귀 비용은 현재 페이지
        1회 재렌더(캐시 미스와 같은 경로)뿐이라 회귀가 없다."""
        try:
            from viewer.pdf_doc import GLOBAL_PAGE_CACHE
            GLOBAL_PAGE_CACHE.clear()
        except Exception:
            pass
        try:
            import fitz
            fitz.TOOLS.store_shrink(100)          # MuPDF 내부 스토어 비움
        except Exception:
            pass

    def changeEvent(self, event):
        """260829(§19.11 P-C): 최소화 즉시 + 비활성 15분 후 렌더 캐시 해제."""
        try:
            from PyQt6.QtCore import QEvent as _QEv
            et = event.type()
            if et == _QEv.Type.WindowStateChange and self.isMinimized():
                self._release_render_memory()
            elif et == _QEv.Type.ActivationChange:
                if self.isActiveWindow():
                    self._idle_release_timer.stop()
                else:
                    self._idle_release_timer.start()
        except Exception:
            pass
        super().changeEvent(event)

    def _confirm_close_edit(self) -> bool:
        """편집모드 + 미저장 변경이 있으면 저장/저장 안 함/취소를 묻는다.
        반환: True=종료 진행, False=종료 취소(창 유지)."""
        try:
            in_edit = self.bookmark_tree.is_edit_mode()
        except Exception:
            in_edit = False
        if not in_edit:
            return True
        meta_dirty = bool(self._edit_dirty)
        try:
            bm_dirty = bool(self.bookmark_tree._dirty)
        except Exception:
            bm_dirty = False
        if not (meta_dirty or bm_dirty):
            return True

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("편집 변경사항")
        box.setText("편집모드에서 저장하지 않은 변경사항이 있습니다.\n"
                    "종료하기 전에 어떻게 할까요?")
        b_save = box.addButton("저장 후 종료", QMessageBox.ButtonRole.AcceptRole)
        b_disc = box.addButton("저장 안 하고 종료", QMessageBox.ButtonRole.DestructiveRole)
        b_cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(b_save)
        box.exec()
        c = box.clickedButton()
        if c is b_cancel:
            return False                      # 종료 취소 — 편집모드 유지
        if c is b_save:
            try:
                if bm_dirty:
                    self.bookmark_tree._op_save()      # 책갈피 → _edited.pdf
            except Exception:
                pass
            try:
                if meta_dirty:
                    self._commit_edit()                # page_meta/하이퍼링크 디스크 저장
            except Exception:
                pass
        # '저장 안 하고 종료' = 보류 중 변경을 커밋하지 않은 채 종료(자동 폐기)
        self._edit_dirty = False
        return True

    # ===== 260618-11: 업데이트(GitHub Releases) =========================
    def _on_toggle_auto_download(self, checked: bool):
        """260618-24(C): 업데이트 자동 다운로드 설정 토글."""
        self._prefs["auto_download_update"] = bool(checked)
        try:
            self._save_settings_now()
        except Exception:
            pass
        # 방금 켰고 새 버전을 이미 인지했다면 바로 미리 받기 시작
        if checked and getattr(self, "_pending_update", None):
            self._start_bg_update_download(self._pending_update)

    def _on_toggle_update_channel(self, checked: bool):
        """260618-33: 베타(테스트) 채널 토글 — 켜면 -beta/-rc 등 프리릴리즈도 후보."""
        self._prefs["update_channel"] = "beta" if checked else "stable"
        # 260628-6(④): 사용자가 직접 고른 값임을 남겨 1.0 전환 마이그레이션이 덮지 않게 한다.
        self._prefs["update_channel_explicit"] = True
        try:
            self._save_settings_now()
        except Exception:
            pass
        # 채널을 바꾸면 즉시 한 번 재확인(수동 알림 없이)
        self._check_for_updates(manual=False)

    def _show_about(self):
        html = (
            "<h3>PolyPDF</h3>"
            "<p>버전 v" + __version__ + "</p>"
            "<p><b>개발자</b>: KD<br>"
            "<b>이메일</b>: "
            "<a href='mailto:kdjeong777@gmail.com'>kdjeong777@gmail.com</a></p>"
            "<hr>"
            "<p><b>오픈소스 고지</b><br>"
            "본 프로그램은 다음 오픈소스 라이브러리를 사용하며, 각 구성요소는 "
            "해당 라이선스를 따릅니다:</p>"
            "<ul>"
            "<li>PyQt6 — Riverbank Computing (GPL v3 / 상용)</li>"
            "<li>PyMuPDF (MuPDF) — Artifex (AGPL v3 / 상용)</li>"
            "<li>openpyxl (MIT)</li>"
            "<li>SQLite — Public Domain</li>"
            "<li>qpdf — Apache License 2.0 (PDF 분할기 동봉)</li>"
            "<li>Tesseract OCR — Apache 2.0 / pytesseract — Apache 2.0 (단어장)</li>"
            "<li>wordfreq (MIT) · NLTK·WordNet (무료) · kiwipiepy (MIT) (단어장)</li>"
            "<li>kengdic 한영사전 — CC BY-SA 3.0 (한국어 단어 영어뜻; "
            "© kengdic contributors, garfieldnate/kengdic)</li>"
            "</ul>"
            "<p>각 라이브러리의 저작권 및 라이선스 전문은 해당 프로젝트 "
            "배포물을 참조하십시오.</p>"
            "<hr>"
            "<p>본 프로그램은 오픈소스 라이선스를 준수합니다. 라이선스 규정에 "
            "따라 소스코드가 필요한 분은 개발자 이메일로 요청시 "
            "보내드리겠습니다.</p>"
        )
        box = QMessageBox(self)
        box.setWindowTitle("PolyPDF — 정보")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(html)
        box.setIcon(QMessageBox.Icon.Information)
        box.exec()

    def _show_usage(self):
        """v1.6.2: 사용법 다이얼로그 표시 (v1.6.1 G2 에서 누락되었던 메서드 보강)."""
        from viewer.widgets.help_dialog import HelpDialog
        dlg = HelpDialog(self)
        dlg.exec()
