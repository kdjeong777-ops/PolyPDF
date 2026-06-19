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
                          QEventLoop, QObject)
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

from viewer import settings_store, __version__
# v1.6.2: 히스토리 패널 제거. HistoryItem 만 last_main 직렬화용으로 남김.
from viewer.history import HistoryItem


def _smooth_dense_norm(pn, steps=12):
    """260611-84: 자유곡선 베이크용 — 화면(2차 베지어 중점 스무딩)과 동일한 곡선을
    촘촘한 폴리라인으로 샘플링(정규화 좌표). pn: [[x,y],...], 점 3개 이상."""
    n = len(pn)
    if n < 3:
        return pn
    out = [list(pn[0])]
    start = pn[0]
    for i in range(1, n - 1):
        c = pn[i]
        e = ((pn[i][0] + pn[i + 1][0]) / 2.0, (pn[i][1] + pn[i + 1][1]) / 2.0)
        for s in range(1, steps + 1):
            t = s / steps; mt = 1.0 - t
            out.append([mt * mt * start[0] + 2 * mt * t * c[0] + t * t * e[0],
                        mt * mt * start[1] + 2 * mt * t * c[1] + t * t * e[1]])
        start = e
    out.append(list(pn[-1]))
    return out
from viewer.workers import (
    IndexWorker, SearchWorker, BookmarkerWorker, StudyBuildWorker, run_in_thread)
from viewer.widgets.bookmark_tree import BookmarkTree
from viewer.widgets.thumbs_list import PageThumbs
from viewer.widgets.main_view import MainView
from viewer.widgets.search_panel import SearchBar, SearchResults
from viewer.widgets.strip import MiniStrip
from viewer.widgets.settings_dialog import SettingsDialog
from viewer.widgets.screenshot_pdf_dialog import ScreenshotPdfDialog
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


class MainWindow(QMainWindow):
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
        self._prefs: dict = {
            "restore_session": True, "restore_last_page": True,
            "restore_screenshots": True, "screenshot_max": 30,
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
            "presentation_split": False,
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
        self._update_right_panel_visibility()   # 260606-10: 패널 비면 메인 전체 폭

        # 260618-11: 업데이트 — 스레드 결과를 메인 스레드로 전달하는 시그널 홀더
        self._update_sig = _UpdateSignals()
        self._update_sig.done.connect(self._on_update_result)
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
        if getattr(self, "_panel_in_drawer", False):
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

    def _on_pane_page_changed(self, i: int, page: int):
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
        """하단(우측) 책갈피 표시/숨김 — 2단이고 우측 폴더가 있으며 좌측과 다를 때만 표시."""
        rt = getattr(self, "bookmark_tree_right", None)
        if rt is None:
            return
        lf = getattr(self, "_folder", None)
        rf = getattr(self, "_folder_right", None)
        show = bool(getattr(self, "_split_on", False) and rf
                    and (lf is None or str(Path(rf)) != str(Path(lf))))
        if not show:
            rt.hide()
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
        """제목 — 2단이면 '좌측폴더 | 우측폴더'(우측 없으면 좌측만)."""
        try:
            lf = getattr(self, "_folder", None)
            left = str(lf) if lf else ""
            if getattr(self, "_split_on", False) and getattr(self, "_folder_right", None) \
                    and (not lf or str(Path(self._folder_right)) != str(Path(lf))):
                title = f"{left}  |  {self._folder_right}"
            else:
                title = left
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

    def _sync_bookmark_to_active(self):
        """260606-9: 책갈피 트리를 활성 창의 파일·페이지에 맞춰 선택·스크롤."""
        try:
            mv = self._mv[self._active_pane]
            f = mv.current_file()
            if f and str(f).lower().endswith(".pdf"):
                self.bookmark_tree.select_for_page(f, mv.current_page())
        except Exception:
            pass

    def _wire_pane_signals(self, mv, idx: int):
        mv.activated.connect(lambda i=idx: self._set_active_pane(i))
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
            self._panel_toolbar.addWidget(b)
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
        mk("법령/고시", "법제처 법령·고시 검색·본문 보기", self._action_law_search)  # 260618-18: 스크린샷 오른쪽
        mk("발표보기", "발표 전체화면 보기 (F5)", self._open_presentation)  # 260609-15(E1)/260618-8
        # 보기 ↔ 도구 사이 띄움
        _sp = QWidget(); _sp.setFixedWidth(20)
        self._panel_toolbar.addWidget(_sp)
        lab("도구")
        self._btn_merge = mk("PDF병합", "파일 → PDF 병합", lambda: self._on_merge_files(None))
        mk("책갈피 생성", "파일 → 책갈피 자동 생성", self.action_open_bookmarker)
        mk("단어장 생성", "파일 → 단어장 생성", self._action_build_study)
        mk("암호화", "현재 PDF에 암호·권한 설정(암호화 저장)", self.action_encrypt_pdf)
        self._btn_shot_pdf = mk("스크린샷 PDF 저장", "스크린샷 전체를 PDF로", self.action_save_screenshot_pdf)

        # 260616-3: 패널 툴바 오른쪽 끝에 검색 입력창(돋보기 + '검색').
        #   Enter 시 검색 실행 + 검색창(검색 탭)이 숨겨져 있으면 보이게 함.
        _rsp = QWidget()
        _rsp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._panel_toolbar.addWidget(_rsp)
        self.toolbar_search = QLineEdit()
        self.toolbar_search.setPlaceholderText("검색")
        self.toolbar_search.setClearButtonEnabled(True)
        self.toolbar_search.setFixedWidth(220)
        self.toolbar_search.setObjectName("toolbarSearch")
        from viewer.widgets.icons import themed_icon as _themed_icon
        self._search_lead_action = self.toolbar_search.addAction(
            _themed_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.toolbar_search.returnPressed.connect(self._on_toolbar_search)
        self._panel_toolbar.addWidget(self.toolbar_search)

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
        """260616-3: 툴바 검색창 Enter — 검색창을 보이게 하고 검색 실행."""
        text = self.toolbar_search.text().strip()
        if not text:
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
                ("발표보기", self._open_presentation)):
            _a = QAction(_label, self)
            _a.triggered.connect(lambda _checked=False, s=_slot: s())
            m_view.addAction(_a)

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
        _act("PDF 꾸밈 저장 (선·도형·글·하이퍼링크)...", self._action_save_decorated_pdf)

        # 🔖 책갈피 및 단어장 생성
        m_tools.addSection("🔖 책갈피 및 단어장 생성")
        _act("단어장·책갈피 동시 생성...", self._action_build_study_and_bookmarks)
        _act("책갈피 자동 생성...", self.action_open_bookmarker)
        _act("단어장 생성 (OCR·어휘)...", self._action_build_study)

        # 📖 사전 및 용어집 관리
        m_tools.addSection("📖 사전 및 용어집 관리")
        _act("용어집 가져오기 (PDF·CSV)...", self._action_import_glossary)
        _act("사전 복원 (가져오기)...", self._action_restore_dict)
        _act("용어집 CSV 양식 예제 저장...", self._action_save_csv_sample)
        _act("인터넷 사전 보강 (이어하기)...", self._action_online_enrich)
        _act("사전 내보내기 (TBX·CSV)...", self._action_export_dict)
        _act("사전 백업 (내보내기)...", self._action_backup_dict)
        _act("사전 정리 (HTML 마크업 제거)", self._action_sanitize_dict)
        _act("온용어 다시 분류 (용어집별·재조회)...", self._action_reclassify_onterm)

        # 🔍 검색 및 데이터 구축
        m_tools.addSection("🔍 검색 및 데이터 구축")
        _act("법령·고시 검색 (법제처)...", self._action_law_search)
        _act("인덱스 재구축", self.action_reindex)

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
            "search_focus": ("func", self.search_bar.focus_search),
            "next_match": ("func", self._global_next_match),
            "prev_match": ("func", self._global_prev_match),
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
        # 260606-22: 책갈피 편집모드 ↔ 썸네일 페이지 편집(삭제/이동) 동기화
        self.bookmark_tree.btn_edit.toggled.connect(self.page_thumbs.set_edit_mode)
        self.bookmark_tree.btn_edit.toggled.connect(self._on_edit_mode_toggled)  # 260609-22(J3)
        self.page_thumbs.applyPageEditsRequested.connect(self._on_apply_page_edits)
        # v1.6.21: 파일 작업 핸드셰이크 (메인이 열고 있는 파일도 작업 가능)
        self.bookmark_tree.releaseFileRequested.connect(self._on_release_file)
        self.bookmark_tree.fileOpCompleted.connect(self._on_file_op_completed)
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
            # 2단: 활성 창에만 로드(다른 창·폴더·상단 책갈피 보존). 인덱스는 폴더 인덱스에 추가만.
            self._load_main(HistoryItem(str(pdf_path), 0, "", "bookmark"))
            try:
                self._cancel_active_indexing()
                worker = IndexWorker(self._db_path, self._folder, single_file=pdf_path)
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

    @staticmethod
    def _images_to_pdf(image_paths: list, out_path: str) -> bool:
        """260606-15: 이미지들을 각 한 페이지로 하는 PDF 생성('사용자 스크린샷' 병합용)."""
        import fitz
        doc = fitz.open()
        try:
            n = 0
            for img in image_paths:
                try:
                    pix = fitz.Pixmap(img)
                    page = doc.new_page(width=pix.width, height=pix.height)
                    page.insert_image(fitz.Rect(0, 0, pix.width, pix.height), filename=img)
                    n += 1
                except Exception:
                    continue
            if n == 0:
                return False
            doc.save(out_path)
            return True
        finally:
            doc.close()

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
            try:
                self._load_main(HistoryItem(str(out), 0, "", "bookmark"))
            except Exception:
                pass
            self._index_single_file(out)        # 백그라운드
            # 260606-24: 책갈피는 병합 시 원본별로 이미 임베드 → auto면 '단어장'만 생성
            if auto:
                self._action_build_study()      # 백그라운드(확인창)
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

        def _on_prog(d, t, lbl):
            prog.setMaximum(max(1, t))
            prog.setValue(min(d, t))
            prog.setLabelText(f"{lbl}  ({d}/{t})")
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
        """260611-35: 같은 이름이 있으면 'name (1).ext', 'name (2).ext' … 로 보존."""
        p = Path(path)
        if not p.exists():
            return str(p)
        parent, stem, suf = p.parent, p.stem, p.suffix
        i = 1
        while True:
            cand = parent / f"{stem} ({i}){suf}"
            if not cand.exists():
                return str(cand)
            i += 1

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
        """260616-3: 경로 비교용 정규화(대소문자·구분자·.. 정리)."""
        return os.path.normcase(os.path.normpath(str(p)))

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
    def action_search(self, query: str):
        if not self._folder:
            self.status.showMessage("폴더를 먼저 여세요.")
            return
        self.status.showMessage(f"검색 중: {query!r}")
        worker = SearchWorker(self._db_path, query)
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
        self.search_results.set_results(query, results)
        self.status.showMessage(f"검색 완료: {len(results)}개 페이지", 3000)

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
            # 260618-22: 2단에서 로드한 창(활성)의 폴더를 그 창 책갈피 트리에 반영(상=좌/하=우).
            #   1단은 기존 흐름(open_folder/open_pdf)이 트리를 관리하므로 건드리지 않음.
            if path.suffix.lower() == ".pdf" and getattr(self, "_split_on", False):
                self._set_pane_folder(self._active_pane, path.parent)
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
        split = bool(self._prefs.get("presentation_split", False))
        overlap = int(self._prefs.get("presentation_overlap_pct", 10))
        topbar_h = int(self._prefs.get("presentation_topbar_h", 64))
        self._present = PresentationWindow(cur, page, self,
                                           pointers=pointers, pointer_active=active,
                                           split_mode=split, overlap_pct=overlap,
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
        self._prefs["presentation_split"] = bool(on)
        self._save_settings_now()

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

    def _on_apply_presentation_drawings(self, norm, file_path):
        """260609-25(I4): 발표에서 그린 선을 본화면(page_meta)·새 PDF에 적용."""
        # 발표 종료 흐름 중이므로 약간 미뤄 실행
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._apply_presentation_drawings_now(norm, file_path))

    def _apply_presentation_drawings_now(self, norm, file_path):
        if not norm:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("선긋기 적용")
        box.setText(f"전체화면에서 그린 선을 적용할까요?\n({len(norm)}개 페이지)")
        b_main = box.addButton("본화면에 적용", QMessageBox.ButtonRole.AcceptRole)
        b_pdf = box.addButton("PDF로 저장", QMessageBox.ButtonRole.ActionRole)
        b_both = box.addButton("둘 다", QMessageBox.ButtonRole.ActionRole)
        box.addButton("적용 안 함", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c not in (b_main, b_pdf, b_both):
            return
        if c in (b_main, b_both):
            self._apply_drawings_to_meta(norm, file_path)
        if c in (b_pdf, b_both):
            self._apply_drawings_to_pdf(norm, file_path)

    def _apply_drawings_to_meta(self, norm, file_path):
        st = self._ensure_page_meta_store()
        if not st:
            return
        for page0, strokes in norm.items():
            existing = st.get_drawings(file_path, page0)
            st.set_drawings(file_path, page0, list(existing) + list(strokes))
        st.save()
        self._refresh_hidden_ui(str(file_path))
        try:
            for mv in self._mv:
                if mv.current_file() and str(Path(mv.current_file())) == str(Path(file_path)):
                    mv._load_page_strokes()
        except Exception:
            pass
        self.status.showMessage("선긋기를 본화면에 적용했습니다.", 3000)

    def _bake_drawings_into_doc(self, doc, norm):
        """260615-3: 정규화 선긋기(선·도형·텍스트박스·지시선·하이라이트)를 열린 doc 에 베이크.
        norm: {page0: [stroke, ...]}. (인쇄/PDF꾸밈저장 공용)"""
        import fitz
        from PyQt6.QtGui import QColor
        for page0, strokes in norm.items():
            if page0 < 0 or page0 >= doc.page_count:
                continue
            page = doc[page0]
            pw, ph = page.rect.width, page.rect.height
            for stk in strokes:
                qc = QColor(stk.get("color", "#ff3030"))
                rgb = (qc.redF(), qc.greenF(), qc.blueF())
                op = max(0.1, min(1.0, float(stk.get("alpha", 100)) / 100.0))
                # 260611-69(Stage1): 도형(직사각형/둥근/원형) 베이크
                if stk.get("shape"):
                    lw = max(0.6, int(stk.get("width", 3)) * 0.6)
                    fk = stk.get("fill", "none")
                    f_rgb = rgb if fk != "none" else None
                    f_op = op * (0.30 if fk == "semi" else 1.0)
                    kind = stk.get("shape")
                    try:
                        if kind == "circle":
                            cx = stk.get("cx", 0.5) * pw; cy = stk.get("cy", 0.5) * ph
                            r = stk.get("r", 0.0) * pw
                            sh = page.new_shape()
                            sh.draw_oval(fitz.Rect(cx - r, cy - r, cx + r, cy + r))
                            sh.finish(color=rgb, width=lw, fill=f_rgb,
                                      fill_opacity=f_op, stroke_opacity=op)
                            sh.commit()
                        else:
                            rc = stk.get("rect", [0, 0, 0, 0])
                            rot = float(stk.get("rot", 0.0))
                            kw = dict(color=rgb, width=lw, fill=f_rgb,
                                      fill_opacity=f_op, stroke_opacity=op)
                            if rot:     # 회전 도형 → 회전한 사각형 폴리곤
                                import math
                                cx = (rc[0] + rc[2]) / 2 * pw; cy = (rc[1] + rc[3]) / 2 * ph
                                hw = abs(rc[2] - rc[0]) / 2 * pw; hh = abs(rc[3] - rc[1]) / 2 * ph
                                a = math.radians(rot); ca = math.cos(a); sa = math.sin(a)
                                pts = [fitz.Point(cx + lx * ca - ly * sa, cy + lx * sa + ly * ca)
                                       for lx, ly in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
                                sh = page.new_shape(); sh.draw_polyline(pts + [pts[0]])
                                sh.finish(color=rgb, width=lw, fill=f_rgb,
                                          fill_opacity=f_op, stroke_opacity=op, closePath=True)
                                sh.commit()
                            else:
                                rect = fitz.Rect(min(rc[0], rc[2]) * pw, min(rc[1], rc[3]) * ph,
                                                 max(rc[0], rc[2]) * pw, max(rc[1], rc[3]) * ph)
                                if kind == "round":
                                    page.draw_rect(rect, radius=0.18, **kw)
                                else:
                                    page.draw_rect(rect, **kw)
                    except Exception:
                        pass
                    continue
                # 260611-74(Phase2): 텍스트 박스 / 지시선 베이크
                if stk.get("text_box") or stk.get("leader"):
                    try:
                        self._bake_text_stroke(fitz, QColor, page, stk, pw, ph)
                    except Exception:
                        pass
                    continue
                pn = stk.get("points", [])
                if len(pn) < 2:
                    continue
                # 260611-1: 하이라이트 = 텍스트 줄 높이만큼 채운 사각형
                if stk.get("hl"):
                    bh = float(stk.get("h", 0.0)) * ph
                    (x0, yc), (x1, _y) = pn[0], pn[-1]
                    rect = fitz.Rect(min(x0, x1) * pw, yc * ph - bh / 2.0,
                                     max(x0, x1) * pw, yc * ph + bh / 2.0)
                    try:
                        page.draw_rect(rect, color=None, fill=rgb, fill_opacity=op)
                    except Exception:
                        page.draw_rect(rect, fill=rgb)
                    continue
                # 260611-84: 자유곡선(점 3개 이상)은 화면과 동일하게 부드러운 곡선으로 저장
                pn2 = _smooth_dense_norm(pn) if len(pn) > 2 else pn
                pts = [fitz.Point(fx * pw, fy * ph) for fx, fy in pn2]
                wpt = max(0.6, int(stk.get("width", 3)) * 0.6)
                try:
                    page.draw_polyline(pts, color=rgb, width=wpt, stroke_opacity=op,
                                       linecap=1, linejoin=1)
                except Exception:
                    page.draw_polyline(pts, color=rgb, width=wpt)

    def _decorations_norm_for(self, file_path):
        """260615-3: 파일의 모든 페이지 선긋기(꾸밈) {page0: strokes} — 인쇄/저장 공용."""
        norm = {}
        st = self._ensure_page_meta_store()
        if st:
            for p in st.pages_with_drawings(file_path):
                dr = st.get_drawings(file_path, p)
                if dr:
                    norm[int(p)] = dr
        return norm

    def _apply_drawings_to_pdf(self, norm, file_path, *, with_hyperlinks: bool = True):
        src = Path(file_path)
        from PyQt6.QtWidgets import QFileDialog
        out, _ = QFileDialog.getSaveFileName(
            self, "PDF 꾸밈 저장 — 새 PDF로 저장",
            str(src.with_name(src.stem + "_꾸밈.pdf")), "PDF (*.pdf)")
        if not out:
            return
        try:
            import fitz
            from PyQt6.QtGui import QColor
            doc = fitz.open(str(src))
            self._bake_drawings_into_doc(doc, norm)
            # 260615-3: ② 하이퍼링크도 함께 PDF 에 베이크(꾸밈 저장)
            if with_hyperlinks:
                try:
                    self._bake_hyperlinks_into_doc(doc, file_path)
                except Exception:
                    pass
            doc.save(out, garbage=4, deflate=True)
            doc.close()
            self.status.showMessage(f"PDF 꾸밈 저장: {Path(out).name}", 4000)
            QMessageBox.information(self, "저장 완료",
                                   f"선·도형·글·하이퍼링크를 삽입한 PDF를 저장했습니다.\n{out}")
        except Exception as e:
            QMessageBox.warning(self, "저장 실패", str(e))

    # 260611-76: 글꼴 이름 → Windows TTF/TTC 경로
    _FONT_FILES = {
        "맑은 고딕": [r"C:\Windows\Fonts\malgun.ttf"],
        "굴림": [r"C:\Windows\Fonts\gulim.ttc"],
        "바탕": [r"C:\Windows\Fonts\batang.ttc"],
        "돋움": [r"C:\Windows\Fonts\dotum.ttc", r"C:\Windows\Fonts\gulim.ttc"],
    }

    def _korean_fontfile(self, family=None):
        """260611-74/76: 글꼴 이름에 맞는 TTF/TTC 경로. 없으면 맑은고딕→폴백."""
        import os
        cands = list(self._FONT_FILES.get(family or "맑은 고딕", []))
        cands += [r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc",
                  r"C:\Windows\Fonts\batang.ttc", r"C:\Windows\Fonts\NanumGothic.ttf"]
        for c in cands:
            if os.path.exists(c):
                return c
        return None

    def _bake_text_stroke(self, fitz, QColor, page, stk, pw, ph):
        """260611-74/76: 텍스트 박스/지시선 굽기 — 배경(투명도)·박스선·지시선(색상버튼 스타일)·텍스트."""
        import math

        def _rgb_op(color, alpha_pct):
            q = QColor(color)
            return (q.redF(), q.greenF(), q.blueF()), max(0.05, min(1.0, float(alpha_pct) / 100.0))

        rc = stk.get("rect", [0, 0, 0.1, 0.05])
        x0 = min(rc[0], rc[2]) * pw; y0 = min(rc[1], rc[3]) * ph
        x1 = max(rc[0], rc[2]) * pw; y1 = max(rc[1], rc[3]) * ph
        rect = fitz.Rect(x0, y0, x1, y1)
        trgb, _ = _rgb_op(stk.get("color", "#111111"), 100)
        bg = stk.get("bg")
        if bg:
            brgb, bop = _rgb_op(bg, stk.get("bg_alpha", 100))
            page.draw_rect(rect, color=None, fill=brgb, fill_opacity=bop)
        if stk.get("box_line"):
            drgb, dop = _rgb_op(stk.get("border_color", "#333333"), stk.get("border_alpha", 100))
            page.draw_rect(rect, color=drgb, width=max(0.6, int(stk.get("border_w", 1)) * 0.7),
                           stroke_opacity=dop)
        if stk.get("leader"):
            # 지시선이 가리키는 문자 하이라이트(반투명, 선 색상)
            hrgb, _ = _rgb_op(stk.get("line_color", "#ffcc00"), 100)
            hop = max(0.05, min(1.0, float(stk.get("line_alpha", 100)) / 100.0) * 0.40)
            for r in stk.get("hl_rects", []):
                try:
                    page.draw_rect(fitz.Rect(r[0] * pw, r[1] * ph, r[2] * pw, r[3] * ph),
                                   color=None, fill=hrgb, fill_opacity=hop)
                except Exception:
                    pass
            an = stk.get("anchor", [0.5, 0.5]); ax = an[0] * pw; ay = an[1] * ph
            cx = (x0 + x1) / 2; cy = (y0 + y1) / 2
            hw = (x1 - x0) / 2; hh = (y1 - y0) / 2
            dx = ax - cx; dy = ay - cy
            if abs(dx) < 1e-6 and abs(dy) < 1e-6:
                sx, sy = cx, cy
            else:
                tt = min(hw / abs(dx) if abs(dx) > 1e-6 else 1e9,
                         hh / abs(dy) if abs(dy) > 1e-6 else 1e9)
                sx, sy = cx + dx * tt, cy + dy * tt
            lrgb, lop = _rgb_op(stk.get("line_color", stk.get("color", "#111111")),
                                stk.get("line_alpha", 100))
            lw = max(0.6, int(stk.get("line_w", 2)) * 0.7)
            page.draw_line(fitz.Point(sx, sy), fitz.Point(ax, ay), color=lrgb, width=lw,
                           stroke_opacity=lop)
            tip = stk.get("tip", "arrow")
            if tip == "circle":
                page.draw_circle(fitz.Point(ax, ay), 5, color=lrgb, fill=lrgb,
                                 stroke_opacity=lop, fill_opacity=lop)
            elif tip == "arrow":
                ang = math.atan2(ay - sy, ax - sx); sz = 11
                for da in (math.radians(150), math.radians(-150)):
                    page.draw_line(fitz.Point(ax, ay),
                                   fitz.Point(ax + sz * math.cos(ang + da),
                                              ay + sz * math.sin(ang + da)),
                                   color=lrgb, width=lw, stroke_opacity=lop)
        txt = stk.get("text", "")
        if not txt.strip():
            return
        fs = max(5.0, float(stk.get("size", 0.022)) * ph)
        ff = self._korean_fontfile(stk.get("family"))
        kw = dict(fontsize=fs, color=trgb, align=int(stk.get("align", 0)))
        if ff:
            kw.update(fontfile=ff, fontname="krfont")
        pad = 2
        box = fitz.Rect(x0 + pad, y0 + pad, x1 - pad, y1 - pad)
        try:
            rcv = page.insert_textbox(box, txt, **kw)
            if rcv < 0:   # 안 들어가면 박스를 넉넉히 넓혀 재시도
                big = fitz.Rect(x0, y0, x0 + (x1 - x0) * 3 + fs * len(txt),
                                y0 + (y1 - y0) * 3 + fs * 4)
                page.insert_textbox(big, txt, **kw)
        except Exception:
            try:
                page.insert_textbox(box, txt, fontsize=fs, color=trgb)
            except Exception:
                pass

    # ===== 260609-17 (F4): 화면+음성 녹화 =================================
    def _recording_out_path(self):
        import time as _t
        d = self._prefs.get("recording_dir") or (str(self._folder) if self._folder else "")
        if not d:
            d = str(Path.home())
        name = "polypdf_rec_" + _t.strftime("%Y%m%d_%H%M%S") + ".mp4"
        return str(Path(d) / name)

    def _present_record_path(self, path=None):
        """260611-23: 녹화 파일명 = <PDF 파일명>_YYYYMMDD_HHMM_SS.mp4 (발표 파일 기준)."""
        import time as _t
        d = self._prefs.get("recording_dir") or (str(self._folder) if self._folder else "")
        if not d:
            d = str(Path.home())
        if path is None and getattr(self, "_present", None) is not None:
            try:
                path = str(self._present._path)
            except Exception:
                path = None
        stem = Path(path).stem if path else "polypdf_rec"
        name = f"{stem}_{_t.strftime('%Y%m%d_%H%M_%S')}.mp4"
        return str(Path(d) / name)

    def _on_present_file_changed(self, path):
        """260611-23: 발표 중 다른 파일 시작 → 현재 녹화 종료 후 새 파일로 녹화 재시작."""
        r = getattr(self, "_rec", None)
        if r is None or not r.is_recording():
            return
        try:
            r.stop()
        except Exception:
            pass
        self._rec = None
        out = self._present_record_path(path)
        self._rec, ff = self._make_recorder(out)
        if not ff:
            self._rec = None
            self._update_rec_buttons()
            return
        ok, _msg = self._rec.start()
        if not ok:
            self._rec = None
        else:
            self.status.showMessage(f"녹화 전환: {Path(out).name}", 3000)
        self._update_rec_buttons()

    def _make_recorder(self, out_path):
        from viewer.recorder import find_ffmpeg, ScreenRecorder
        ff = find_ffmpeg(self._prefs.get("ffmpeg_path", ""))
        return ScreenRecorder(
            ff, out_path,
            audio_mode=self._prefs.get("recording_audio_mode", "mic"),
            mic=self._prefs.get("recording_mic", ""),
            system=self._prefs.get("recording_system", ""),
            fps=30, crf=23, abitrate="192k"), ff

    def _update_rec_buttons(self):
        if getattr(self, "_present", None) is not None:
            r = getattr(self, "_rec", None)
            self._present.set_recording_state(
                bool(r and r.is_recording()), bool(r and r.is_paused()))

    def _on_record_toggle(self):
        r = getattr(self, "_rec", None)
        if r is not None and r.is_recording():
            if r.is_paused():
                r.resume()
            self._update_rec_buttons()
            return
        # 260611-25: '녹화 테스트' 합격 결과가 없으면 확인(녹화없이 진행/설정진행/취소)
        if not self._prefs.get("recording_test_ok"):
            choice = self._ask_rec_test_gate()
            if choice == "settings":
                self._open_recording_settings()
                return
            if choice != "proceed":          # cancel · 녹화없이 진행 → 녹화 안 함
                return
        # 260611-23: 발표 중이면 파일명 기반(<파일>_날짜_시각)으로 저장
        out = (self._present_record_path() if getattr(self, "_present", None)
               else self._recording_out_path())
        self._rec, ff = self._make_recorder(out)
        if not ff:
            QMessageBox.warning(self, "녹화 불가",
                                "ffmpeg 를 찾을 수 없습니다. 설정에서 ffmpeg 경로를 지정하세요.")
            self._rec = None
            return
        ok, msg = self._rec.start()
        if not ok:
            QMessageBox.warning(self, "녹화 실패", msg)
            self._rec = None
            return
        self.status.showMessage(f"녹화 시작: {Path(out).name}", 3000)
        self._update_rec_buttons()

    def _ask_rec_test_gate(self):
        """260611-25: 녹화 테스트 합격 결과 없을 때 — 녹화없이 진행/설정진행/취소."""
        par = getattr(self, "_present", None) or self
        box = QMessageBox(par)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("녹화 확인")
        box.setText("'녹화 테스트' 합격 결과가 없습니다.\n어떻게 할까요?")
        b_no = box.addButton("녹화 없이 진행", QMessageBox.ButtonRole.AcceptRole)
        b_set = box.addButton("녹화 설정", QMessageBox.ButtonRole.ActionRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c is b_set:
            return "settings"
        if c is b_no:
            return "noproceed"      # 녹화 없이 시계만 사용
        return "cancel"

    def _open_recording_settings(self):
        """260611-25: '화면+음성 녹화' 설정 화면(녹화 테스트 포함)을 띄움."""
        from viewer.widgets.settings_dialog import SettingsDialog
        par = getattr(self, "_present", None) or self
        dlg = SettingsDialog(self._prefs, par, host=self)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, dlg.focus_recording)
        if dlg.exec() == dlg.DialogCode.Accepted:
            new_prefs = dlg.result_prefs()
            self._apply_prefs(new_prefs)
            self._save_settings_now()
            self.status.showMessage("설정 저장됨", 3000)

    def _on_record_pause(self):
        r = getattr(self, "_rec", None)
        if r is not None and r.is_recording() and not r.is_paused():
            r.pause()
            self._update_rec_buttons()

    def _on_record_stop(self):
        r = getattr(self, "_rec", None)
        if r is not None:
            out = r.out_path
            r.stop()
            self._rec = None
            self.status.showMessage(f"녹화 저장: {Path(out).name}", 4000)
        self._update_rec_buttons()

    def _test_recording(self, parent=None):
        """260609-17(F4)/260618-14: 3초 테스트 녹화 — 실패 시 ffmpeg 실제 오류·종료코드 표시.
        출력이 비면 백신(Defender)의 ffmpeg 실행 차단을 의심해 안내(조용한 실패 방지)."""
        import tempfile, subprocess
        from viewer.recorder import (find_ffmpeg, build_command, CREATE_NO_WINDOW)
        ff = find_ffmpeg(self._prefs.get("ffmpeg_path", ""))
        if not ff:
            return False, "ffmpeg 를 찾을 수 없습니다. (구성요소 설치 또는 설정에서 경로 지정)"
        out = Path(tempfile.gettempdir()) / "polypdf_rectest.mp4"
        try:
            if out.exists():
                out.unlink()
        except Exception:
            pass
        am = self._prefs.get("recording_audio_mode", "mic")
        cmd = build_command(ff, str(out), audio_mode=am,
                            mic=self._prefs.get("recording_mic", ""),
                            system=self._prefs.get("recording_system", ""), duration=3)
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=30,
                               creationflags=CREATE_NO_WINDOW)
            rc = p.returncode
            err = (p.stderr or b"").decode("utf-8", "replace").strip()
        except FileNotFoundError:
            return False, ("ffmpeg 실행 파일이 없습니다(백신이 삭제·격리했을 수 있음).\n"
                           "Windows 보안에서 ffmpeg.exe 를 허용/복원하거나 다시 설치하세요.")
        except subprocess.TimeoutExpired:
            return False, "테스트 시간 초과(녹화가 정상 종료되지 않음)."
        except OSError as e:
            return False, ("ffmpeg 을 실행할 수 없습니다(백신 차단 의심): %s\n"
                           "설치 폴더의 ffmpeg.exe 를 Windows 보안 예외에 추가하세요." % e)
        if not out.exists() or out.stat().st_size < 1024:
            tail = "\n".join(err.splitlines()[-6:]) if err else ""
            msg = "녹화 파일이 생성되지 않았습니다 (ffmpeg 종료코드 %s)." % rc
            if tail:
                msg += "\n\n[ffmpeg 오류]\n" + tail
            else:
                msg += ("\n\nffmpeg 출력이 전혀 없습니다 — 백신(Windows Defender)이 ffmpeg 실행을 "
                        "차단했을 수 있습니다. 설치 폴더의 ffmpeg.exe 를 보안 예외에 추가한 뒤 다시 시도하세요.")
            return False, msg
        # 오디오 스트림 유무 확인
        try:
            pr = subprocess.run([ff, "-hide_banner", "-i", str(out)],
                                capture_output=True, creationflags=CREATE_NO_WINDOW)
            has_audio = "Audio:" in (pr.stderr or b"").decode("utf-8", "replace")
        except Exception:
            has_audio = False
        if am != "none" and not has_audio:
            return True, ("화면 녹화는 정상입니다. 단, 선택한 오디오가 녹음되지 않았습니다.\n"
                          "장치 선택을 확인하세요(시스템 소리는 Stereo Mix/가상 오디오 필요).")
        return True, "테스트 성공 — 화면" + ("·소리 모두" if am != "none" else "") + " 정상 녹화됩니다."

    def _on_pen_settings(self):
        # 260611-2: 발표 펜 설정도 본문과 공유되는 동일 다이얼로그 사용 → 양쪽 동시 반영
        self._open_main_pen_settings()

    def _presentation_sibling(self, cur_path: str, direction: int):
        """260609-7: 발표 파일경계용 — 책갈피창 순서의 다음/이전 파일 경로."""
        try:
            files = self.bookmark_tree.all_file_paths() or []
            if not files:
                return None
            norm = [str(Path(f)) for f in files]
            cs = str(Path(cur_path))
            if cs not in norm:
                return None
            j = norm.index(cs) + (1 if direction > 0 else -1)
            if 0 <= j < len(files):
                return files[j]
        except Exception:
            pass
        return None

    def _bake_hyperlinks_into_doc(self, doc, cur):
        """260615-3: 등록 하이퍼링크를 열린 doc 에 라벨 버튼+링크 주석으로 삽입.
        외부 리더에서도 클릭 동작(파일=Launch, URL=URI)."""
        import fitz
        st = self._ensure_hyperlink_store()
        if not st:
            return
        off_pt = float(self._prefs.get("hyperlink_top_offset_px", 10))
        fs = 9.0
        pad_x, gap, btn_h = 6.0, 6.0, fs + 8.0
        for p0 in sorted(st.pages_with_links(cur)):
            if p0 < 0 or p0 >= doc.page_count:
                continue
            page = doc[p0]
            pw = page.rect.width
            links = st.links_for(cur, p0)
            items = []
            for ln in links:
                label = str(ln.get("name", "") or "링크")
                tw = fitz.get_text_length(label, fontsize=fs) + 2 * pad_x
                items.append((label, min(tw, pw - 20), ln))
            avail = pw - 20
            rows, cur_w = [[]], 0.0
            for it in items:
                w = it[1]
                if rows[-1] and cur_w + gap + w > avail:
                    rows.append([]); cur_w = 0.0
                rows[-1].append(it); cur_w += (gap if cur_w else 0) + w
            y = 10.0 + off_pt
            for row in rows:
                total = sum(w for _, w, _ in row) + gap * (len(row) - 1)
                x = (pw - total) / 2.0
                for label, w, ln in row:
                    rect = fitz.Rect(x, y, x + w, y + btn_h)
                    page.draw_rect(rect, color=(1, 1, 1), fill=(0.08, 0.40, 0.75),
                                   width=0.5, radius=0.2)
                    page.insert_textbox(rect, label, fontsize=fs,
                                        color=(1, 1, 1), align=fitz.TEXT_ALIGN_CENTER)
                    if ln.get("kind") == "url":
                        page.insert_link({"kind": fitz.LINK_URI, "from": rect,
                                          "uri": str(ln.get("target", ""))})
                    else:
                        page.insert_link({"kind": fitz.LINK_LAUNCH, "from": rect,
                                          "file": str(ln.get("target", ""))})
                    x += w + gap
                y += btn_h + 4

    def _action_save_decorated_pdf(self):
        """260615-3: ② 'PDF 꾸밈 저장' — 선·도형·텍스트박스·지시선 + 하이퍼링크를
        새 PDF 에 삽입 저장. (구 '하이퍼링크 삽입 저장' 확장)"""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or not str(cur).lower().endswith(".pdf"):
            QMessageBox.information(self, "안내", "먼저 PDF를 표시하세요.")
            return
        # 이 파일의 모든 페이지 꾸밈(선긋기) 수집
        norm = self._decorations_norm_for(cur)
        st_hl = self._ensure_hyperlink_store()
        has_hl = bool(st_hl and st_hl.pages_with_links(cur))
        if not norm and not has_hl:
            QMessageBox.information(self, "안내",
                                   "이 파일에 저장할 꾸밈(선·도형·글)이나 하이퍼링크가 없습니다.")
            return
        self._apply_drawings_to_pdf(norm, cur, with_hyperlinks=True)

    # ===== 260609-14 (D4·D5): 페이지 메타(크롭·숨김) =====================
    def _ensure_page_meta_store(self):
        from viewer.page_meta import PageMetaStore
        if not self._folder:
            self._page_meta = None
            return None
        st = self._page_meta
        if st is None or str(getattr(st, "base", "")) != str(self._folder):
            self._page_meta = PageMetaStore(self._folder)
        return self._page_meta

    def _crop_for(self, path, page0):
        st = self._ensure_page_meta_store()
        return st.get_crop(path, page0) if st else (0.0, 0.0)

    def _hidden_for(self, path):
        st = self._ensure_page_meta_store()
        return st.hidden_pages(path) if st else set()

    def _rotation_for(self, path, page0):
        st = self._ensure_page_meta_store()
        return st.get_rotation(path, page0) if st else 0

    # ===== 260609-22(J3): 본화면 선긋기 =================================
    def _drawings_for(self, path, page0):
        st = self._ensure_page_meta_store()
        return st.get_drawings(path, page0) if st else []

    def _set_drawings(self, path, page0, strokes):
        st = self._ensure_page_meta_store()
        if not st:
            return
        st.set_drawings(path, page0, strokes)
        self._persist_meta(st)               # 260609-23(J2): 편집모드면 보류
        self._refresh_hidden_ui(path)        # 꾸밈 갱신(썸네일 색·필터)

    # 260611-15: 삽입 이미지(주석) page_meta 연동
    def _images_for(self, path, page0):
        st = self._ensure_page_meta_store()
        return st.get_images(path, page0) if st else []

    def _thumb_images_for(self, page0):
        """260611-18(A5): 썸네일 베이킹용 — 현재 표시 파일의 page0 삽입 이미지."""
        try:
            f = self.main_view.current_file() if self.main_view else None
        except Exception:
            f = None
        if not f or not str(f).lower().endswith(".pdf"):
            return []
        return self._images_for(str(f), int(page0))

    def _set_images(self, path, page0, images):
        st = self._ensure_page_meta_store()
        if not st:
            return
        st.set_images(path, page0, images)
        self._persist_meta(st)
        self._refresh_hidden_ui(path)        # 꾸밈 갱신(이미지 있는 페이지도 꾸밈)

    # ===== 260611-2: 본문·발표 공유 선긋기 설정 =========================
    def _draw_pens(self):
        from viewer.widgets.main_view import MV_DEFAULT_PENS
        pens = list(self._prefs.get("draw_pens") or MV_DEFAULT_PENS)
        while len(pens) < len(MV_DEFAULT_PENS):     # 260611-5: 5개로 보충
            pens.append(dict(MV_DEFAULT_PENS[len(pens)]))
        return pens

    def _draw_eraser_widths(self):
        return self._prefs.get("draw_eraser_widths") or [12, 30]

    def _draw_highlight_alpha(self):
        return int(self._prefs.get("draw_highlight_alpha", 35))

    def _init_draw_config(self, mv):
        # 260611-2: 본문·발표 공유 5펜 + 선 종류(직선/하이라이트/자유) + 지우개폭 + 하이라이트 투명도
        mv.set_draw_config(
            self._draw_pens(),
            int(self._prefs.get("draw_line_mode", 0)),
            self._draw_eraser_widths(),
            self._draw_highlight_alpha(),
            self._drawings_for, self._set_drawings)
        mv.set_image_config(self._images_for, self._set_images)   # 260611-15
        try:
            mv.set_text_styles(self._text_styles())               # 260611-78
        except Exception:
            pass

    def _apply_draw_config_all(self):
        """260611-2: 공유 펜/지우개/하이라이트 설정을 두 메인뷰·발표창에 즉시 반영."""
        for mv in self._mv:
            try:
                mv.set_main_pens(self._draw_pens())
                mv._draw_eraser_widths = list(self._draw_eraser_widths())
                mv._draw_highlight_alpha = self._draw_highlight_alpha()
            except Exception:
                pass
        if getattr(self, "_present", None) is not None:
            try:
                self._present.set_pens(self._draw_pens())
                self._present.set_eraser_widths(self._draw_eraser_widths())
                self._present.set_highlight_alpha(self._draw_highlight_alpha())
            except Exception:
                pass

    def _open_main_pen_settings(self):
        """260611-2: 공유 선긋기 설정(5펜 색·굵기·투명도 + 지우개 면적) → 저장·전체 반영."""
        from viewer.widgets.pen_settings_dialog import MainDrawSettingsDialog
        dlg = MainDrawSettingsDialog(self._draw_pens(), self,
                                     eraser_widths=self._draw_eraser_widths(),
                                     highlight_alpha=self._draw_highlight_alpha())
        if dlg.exec():
            self._prefs["draw_pens"] = dlg.result_pens()
            self._prefs["draw_eraser_widths"] = dlg.result_eraser_widths()
            self._prefs["draw_highlight_alpha"] = dlg.result_highlight_alpha()
            self._apply_draw_config_all()
            self._save_settings_now()

    def _text_styles(self):
        """260611-78: 저장된 사용자 글쓰기 스타일. 없으면 기본(본문/제목/메모/강조)."""
        styles = self._prefs.get("text_styles")
        if not styles:
            try:
                styles = self._mv[0]._seed_text_styles()
            except Exception:
                styles = []
        return styles

    def _open_line_text_settings(self):
        """260611-78: '선과 텍스트 입력 설정' — 선긋기 + 글쓰기(사용자 스타일) 통합 설정."""
        from viewer.widgets.line_text_settings_dialog import LineTextSettingsDialog
        dlg = LineTextSettingsDialog(self._draw_pens(), self._draw_eraser_widths(),
                                     self._draw_highlight_alpha(), self._text_styles(), self)
        if dlg.exec():
            self._prefs["draw_pens"] = dlg.result_pens()
            self._prefs["draw_eraser_widths"] = dlg.result_eraser_widths()
            self._prefs["draw_highlight_alpha"] = dlg.result_highlight_alpha()
            self._prefs["text_styles"] = dlg.result_styles()
            self._apply_draw_config_all()
            for mv in self._mv:
                try:
                    mv.set_text_styles(self._text_styles())
                except Exception:
                    pass
            self._save_settings_now()

    # ===== 260609-23(J2): 편집모드 트랜잭션 =============================
    def _in_edit(self) -> bool:
        try:
            return self.bookmark_tree.is_edit_mode()
        except Exception:
            return False

    def _persist_meta(self, store):
        """편집모드면 디스크 저장을 보류하고 dirty 표시, 아니면 즉시 저장."""
        if store is None:
            return
        if self._in_edit():
            self._edit_dirty = True
        else:
            store.save()

    def _snapshot_edit(self):
        import copy
        if self._edit_snap is not None:
            return                       # 이미 세션 진행 중(계속 편집 등)
        self._edit_dirty = False
        pm = self._ensure_page_meta_store()
        hl = self._ensure_hyperlink_store()
        self._edit_snap = {
            "pm": copy.deepcopy(pm._data) if pm else None,
            "hl": copy.deepcopy(hl._data) if hl else None,
        }

    def _restore_edit(self):
        import copy
        snap = self._edit_snap or {}
        pm = self._page_meta
        hl = self._hyperlinks
        if pm is not None and snap.get("pm") is not None:
            pm._data = copy.deepcopy(snap["pm"])
        if hl is not None and snap.get("hl") is not None:
            hl._data = copy.deepcopy(snap["hl"])
        self._refresh_all_meta_ui()

    def _commit_edit(self):
        if self._page_meta is not None:
            self._page_meta.save()
        if self._hyperlinks is not None:
            self._hyperlinks.save()

    def _save_meta_from_button(self):
        """260611-18(A4·A5): '저장' 버튼 — 편집모드 page_meta 변경을 디스크에 저장하고
        썸네일(개체 베이킹 포함)을 갱신. 편집모드는 유지하되 저장된 상태를 새 기준으로."""
        if not self._edit_dirty:
            return
        self._commit_edit()
        self._edit_dirty = False
        # 저장된 상태를 새 스냅샷 기준으로(이후 '취소'는 저장 시점으로 되돌림)
        self._edit_snap = None
        try:
            self._snapshot_edit()
        except Exception:
            pass
        # 썸네일 재렌더 → 삽입 개체가 썸네일에 반영(A5)
        try:
            cur = self.main_view.current_file() if self.main_view else None
            if cur:
                self._refresh_hidden_ui(str(cur))
        except Exception:
            pass
        try:
            self.status.showMessage("편집 내용을 저장했습니다.", 3000)
        except Exception:
            pass

    def _on_edit_cancelled(self):
        """260611-9: 책갈피 '취소' — 편집모드 유지한 채 미저장 수정(숨김/회전/선긋기/
        하이퍼링크)을 스냅샷으로 되돌리고, 이후 편집을 위해 스냅샷을 새로 찍는다."""
        try:
            if self._edit_snap is not None:
                self._restore_edit()
        except Exception:
            pass
        self._edit_snap = None
        self._edit_dirty = False
        try:
            self._snapshot_edit()        # 되돌린 상태를 새 기준으로
        except Exception:
            pass
        try:
            self.status.showMessage("편집 수정 사항을 취소(되돌리기)했습니다.", 3000)
        except Exception:
            pass

    def _refresh_all_meta_ui(self):
        cur = self.main_view.current_file() if self.main_view else None
        if cur and str(cur).lower().endswith(".pdf"):
            self._refresh_hidden_ui(str(cur))
            self._refresh_page_hyperlinks(self._active_pane)
            try:
                for mv in self._mv:
                    if mv.current_file() and str(Path(mv.current_file())) == str(Path(cur)):
                        mv._load_page_strokes()
                        mv._load_page_images()      # 260611-15: 취소 시 이미지도 복원
            except Exception:
                pass

    def _confirm_edit_save(self, switching=False) -> str:
        """미저장 변경 확인. 반환: 'save'/'discard'/'cancel'."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("편집 변경사항")
        box.setText("저장하지 않은 편집 변경사항이 있습니다.\n"
                    + ("다른 파일로 이동하기 전에 어떻게 할까요?" if switching
                       else "편집을 종료하기 전에 어떻게 할까요?"))
        b_save = box.addButton("저장", QMessageBox.ButtonRole.AcceptRole)
        b_disc = box.addButton("되돌리기(저장 안 함)", QMessageBox.ButtonRole.DestructiveRole)
        b_keep = box.addButton("계속 편집", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c is b_save:
            return "save"
        if c is b_disc:
            return "discard"
        return "cancel"

    def _on_edit_mode_toggled(self, on: bool):
        if on:
            self._snapshot_edit()
        else:
            # 종료 시 미저장 변경 처리
            if self._edit_snap is not None and self._edit_dirty:
                choice = self._confirm_edit_save(switching=False)
                if choice == "cancel":
                    # 편집 유지 — 버튼 다시 켜기(정상 toggled 로 모든 핸들러 복원)
                    self.bookmark_tree.btn_edit.setChecked(True)
                    return
                if choice == "save":
                    self._commit_edit()
                else:
                    self._restore_edit()
            self._edit_snap = None
            self._edit_dirty = False
        for mv in self._mv:
            try:
                self._init_draw_config(mv)
                mv.set_draw_mode(bool(on))
            except Exception:
                pass

    def _rotations_for(self, path):
        st = self._ensure_page_meta_store()
        return st.rotations(path) if st else {}

    def _rotate_pages(self, pages, delta):
        """260609-15(A1): 썸네일 선택 페이지 90° 회전 — 저장 + 갱신."""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or not str(cur).lower().endswith(".pdf") or not pages:
            return
        st = self._ensure_page_meta_store()
        if not st:
            return
        st.rotate_pages(cur, pages, delta)
        self._persist_meta(st)           # 260609-23(J2)
        self._refresh_hidden_ui(cur)

    def _on_crop_settings(self):
        """발표 우클릭 '크롭 설정…' → 다이얼로그 → 저장·재렌더."""
        w = getattr(self, "_present", None)
        st = self._ensure_page_meta_store()
        if not w or not st:
            return
        path = str(w._path); page0 = int(w._page)
        from viewer.widgets.crop_dialog import CropDialog
        g = st.get_global_crop(path)
        pg = st.get_crop(path, page0)
        dlg = CropDialog(page0 + 1, g, pg, st.has_page_crop(path, page0), w)
        if not dlg.exec():
            return
        r = dlg.result()
        if r["reset"]:
            st.reset_crop(path)
        else:
            st.set_global_crop(path, *r["global"])
            if r["page_enabled"]:
                st.set_page_crop(path, page0, *r["page"])
            else:
                st.clear_page_crop(path, page0)
        st.save()
        w.refresh()

    def _set_pages_hidden(self, pages, hidden: bool):
        """260609-14(D5): 페이지 숨김/해제 — 저장 + 썸네일·뷰어·발표 갱신."""
        cur = self.main_view.current_file() if self.main_view else None
        if not cur or not str(cur).lower().endswith(".pdf"):
            return
        st = self._ensure_page_meta_store()
        if not st:
            return
        st.set_hidden(cur, pages, hidden)
        self._persist_meta(st)           # 260609-23(J2): 편집모드면 보류
        self._refresh_hidden_ui(cur)

    def _reset_hidden(self):
        cur = self.main_view.current_file() if self.main_view else None
        if not cur:
            return
        st = self._ensure_page_meta_store()
        if st and st.clear_hidden(cur):
            self._persist_meta(st)       # 260609-23(J2)
            self._refresh_hidden_ui(cur)

    def _push_nav_filter(self):
        """260609-26: 썸네일 필터(보임/꾸밈/숨김)를 활성 뷰어 페이지 이동에 반영."""
        mv = self.main_view
        try:
            if not mv or mv._is_image or mv._doc is None:
                if mv:
                    mv.set_nav_pages(None)
                return
            tp = self.page_thumbs
            if getattr(tp, "_filter", "all") == "all":
                mv.set_nav_pages(None)
                return
            n = mv._doc.page_count
            pages = [p for p in range(n) if tp.page_visible_in_filter(p)]
            if not pages:
                pages = [mv._current_page]   # 빈 필터 → 현재 페이지에 고정
            mv.set_nav_pages(pages)
        except Exception:
            pass

    def _decorated_for(self, file_path):
        """260609-21/22(J4·J3): 꾸밈 페이지 = 하이퍼링크 ∪ 선긋기 페이지."""
        deco = set()
        try:
            st = self._ensure_hyperlink_store()
            if st and str(file_path).lower().endswith(".pdf"):
                deco |= set(st.pages_with_links(file_path))
        except Exception:
            pass
        try:
            pm = self._ensure_page_meta_store()
            if pm:
                deco |= set(pm.pages_with_drawings(file_path))
                deco |= set(pm.pages_with_images(file_path))   # 260611-15
        except Exception:
            pass
        return deco

    def _refresh_hidden_ui(self, file_path):
        hidden = self._hidden_for(file_path)
        rots = self._rotations_for(file_path)              # 260609-15(A1)
        deco = self._decorated_for(file_path)              # 260609-21(J4)
        try:
            self.page_thumbs.set_hidden_pages(hidden)
            self.page_thumbs.set_rotations(rots)
            self.page_thumbs.set_decorated_pages(deco)
            # 260609-28: 새 파일의 숨김/꾸밈 메타 기준으로 필터 재적용(목록만, 이동 없음)
            #   → 보임/꾸밈/숨김 필터가 파일을 바꿔도 동일 상태로 유지됨
            if getattr(self.page_thumbs, "_filter", "all") != "all":
                self.page_thumbs._apply_filter(jump=False)
        except Exception:
            pass
        self._push_nav_filter()      # 260609-26: 숨김/꾸밈 변동 → 필터 페이지 갱신
        try:
            for mv in self._mv:
                if mv.current_file() and str(Path(mv.current_file())) == str(Path(file_path)):
                    mv.set_hidden_pages(hidden)
                    mv.set_rotations(rots)
        except Exception:
            pass
        if getattr(self, "_present", None) is not None:
            try:
                self._present.refresh()
            except Exception:
                pass

    def _presentation_bookmarks(self, path: str):
        """260609-12(D3): 발표 상단 페이지 풀다운용 — (page0, 책갈피명) 목록."""
        try:
            import fitz
            d = fitz.open(str(path))
            toc = d.get_toc(simple=True)
            d.close()
            return [(int(p) - 1, str(t)) for (lvl, t, p) in toc if int(p) >= 1]
        except Exception:
            return []

    def _presentation_hyperlinks(self, path: str, page0: int):
        """260609-8: 발표 상단 띠용 — 해당 파일·페이지의 하이퍼링크 목록."""
        try:
            st = self._ensure_hyperlink_store()
            if st and str(path).lower().endswith(".pdf"):
                return st.links_for(path, page0)
        except Exception:
            pass
        return []

    def _on_presentation_closed(self):
        """발표 창을 닫으면 마지막 파일·페이지를 메인 뷰에 동기화."""
        # 260609-17(F4): 녹화 중이면 안전 종료(파일 마감)
        r = getattr(self, "_rec", None)
        if r is not None and r.is_recording():
            try:
                r.stop()
            except Exception:
                pass
            self._rec = None
        w = getattr(self, "_present", None)
        if not w or not self.main_view:
            return
        try:
            path = str(w._path)
            page = int(w._page)
            cur = self.main_view.current_file()
            if not cur or str(Path(cur)) != str(Path(path)):
                self._on_bookmark_activated(path, page)   # 파일이 바뀌었으면 로드
            else:
                self.main_view.go_to_page(page)
        except Exception:
            pass

    def _on_pointer_settings(self):
        from viewer.widgets.pointer_settings_dialog import PointerSettingsDialog
        from viewer.widgets.presentation import DEFAULT_POINTERS
        cur = self._prefs.get("presentation_pointers") or DEFAULT_POINTERS
        dlg = PointerSettingsDialog(cur, self._present or self)
        if dlg.exec():
            pts = dlg.result_pointers()
            self._prefs["presentation_pointers"] = pts
            self._save_settings_now()
            if self._present is not None:
                self._present.set_pointers(pts)

    # ===== 260609-3 (C): 페이지 외부 하이퍼링크 ==========================
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
    def _study_get_store(self):
        if self._study_store is None:
            from viewer.study.study_store import StudyStore
            self._study_store = StudyStore()      # settings_dir()/study.db
        return self._study_store

    def _study_get_user(self):
        if self._user_store is None:
            from viewer.study.study_store import UserStore
            self._user_store = UserStore()        # settings_dir()/user_study.db
        return self._user_store

    def _study_get_dict(self):
        """260611-100(P1): 계층형 전문 용어사전(dict.db) — Base/User 항목.
        260611-101(P3): 최초 생성 시 동봉 기본 용어집(resources/dict/*.json) 시드."""
        if getattr(self, "_dict_store", None) is None:
            from viewer.study.dict_store import DictStore
            self._dict_store = DictStore()        # settings_dir()/dict.db
            try:
                from viewer.study.glossary_import import load_bundled_glossaries
                seeded = load_bundled_glossaries(self._dict_store)
                if seeded:
                    self.status.showMessage(
                        "기본 용어집 적재: " + ", ".join(seeded), 4000)
            except Exception:
                pass
        return self._dict_store

    def _study_get_tts(self):
        if self._tts is None:
            from viewer.study.tts import get_tts
            self._tts = get_tts()
        return self._tts

    def _detect_study_lang(self, path: Path) -> str:
        """간단 언어 감지 — 첫 몇 페이지에 한글이 많으면 kor, 아니면 eng."""
        try:
            import fitz, re
            doc = fitz.open(path)
            sample = "".join(doc.load_page(i).get_text("text")
                             for i in range(min(5, doc.page_count)))
            doc.close()
            hangul = len(re.findall(r"[가-힣]", sample))
            latin = len(re.findall(r"[A-Za-z]", sample))
            return "kor" if hangul > latin else "eng"
        except Exception:
            return "eng"

    @staticmethod
    def _dict_src_label(h: dict) -> str:
        """260615-7(P9): 출처 표시 = '구분 / 출처명'(구분 없으면 출처명만)."""
        nm = h.get("src_name") or ""
        cat = (h.get("src_category") or "").strip()
        return f"{cat} / {nm}" if cat else nm

    def _enrich_rows_with_dict(self, rows):
        """260611-102(P2): 각 단어를 계층형 사전(User▶Base)에서 조회해 뜻·예시·참고문헌
        을 우선 적용. 자동(Auto) 뜻은 아래에 유지. 텍스트 기준 중복 제거."""
        try:
            dic = self._study_get_dict()
        except Exception:
            return rows
        for r in rows:
            lemma = (r.get("lemma") or "").strip()
            if not lemma:
                continue
            try:
                hits = dic.lookup(lemma)
            except Exception:
                hits = []
            if not hits:
                continue
            ddefs, dex = [], []
            if any(h.get("src_kind") == "user" for h in hits):
                r["user_edited"] = True       # P5: 사용자 사전 항목 있음(✎ 표시)
            # 260611-105(P6): 전문 용어집(termbase)에 있는 단어는 '전문용어' 등급으로
            #   (빈도 낮다고 무조건 '고급'으로 몰리던 문제 해결). '일반' 사전은 제외.
            if any(h.get("src_is_termbase") for h in hits):
                r["level"] = "전문용어"
            # 260615-8(P10): 그림(첫 매칭 항목의 이미지) 부착
            img = next((h.get("image") for h in hits if (h.get("image") or "").strip()), "")
            if img:
                r["image"] = img
            for h in hits:
                src = self._dict_src_label(h)        # 260615-7(P9): 구분 / 출처명
                ref = (h.get("reference") or h.get("src_reference") or "").strip()
                for fld in ("def_ko", "def_en"):
                    t = (h.get(fld) or "").strip()
                    if t:
                        ddefs.append({"definition": t, "source": src, "ref": ref,
                                      "is_dict": True, "kind": h.get("src_kind")})
                for ex in (h.get("examples") or "").split("\n"):
                    ex = ex.strip()
                    if ex:
                        dex.append({"example": ex, "source": src})
            if not ddefs:
                continue
            r["has_dict"] = True
            # 사전 뜻 먼저 + 기존 자동 뜻, 텍스트 기준 중복 제거
            seen, merged = set(), []
            for d in ddefs + (r.get("definitions") or []):
                key = (d.get("definition") or "").strip()
                if key and key not in seen:
                    seen.add(key); merged.append(d)
            r["definitions"] = merged
            if dex:
                seen_e, merged_e = set(), []
                for e in dex + (r.get("examples") or []):
                    key = (e.get("example") or "").strip()
                    if key and key not in seen_e:
                        seen_e.add(key); merged_e.append(e)
                r["examples"] = merged_e
        return rows

    def _accumulate_and_merge_examples(self, rows):
        """260615-10(P12): 문서 예문(source='book')을 사용자 사전에 축적(구분='내 문서',
        출처명=문서명)하고, 같은 단어의 누적 예문(타 문서 포함)을 병합해 표시.
        예시의 '구분/출처명'은 참고문헌 토글로 표시/숨김."""
        if not self._study_pdf:
            return rows
        try:
            dic = self._study_get_dict()
            doc = Path(self._study_pdf).stem
        except Exception:
            return rows
        cat = "내 문서"
        for r in rows:
            lemma = r.get("lemma", "")
            ex_list = r.get("examples") or []
            book = [(e.get("example") or "").strip() for e in ex_list
                    if e.get("source") == "book"]
            book = [x for x in book if x]
            if book:
                dic.add_examples([{"lemma": lemma, "example": x,
                                   "category": cat, "source": doc} for x in book])
            merged, seen = [], set()
            # 사전(entry) 예문(이미 출처 라벨 있음) 우선
            for e in ex_list:
                if e.get("source") == "book":
                    continue
                t = (e.get("example") or "").strip()
                if t and t not in seen:
                    seen.add(t); merged.append(e)
            # 누적 예문(구분/출처 라벨)
            for a in dic.examples_for(lemma):
                t = (a.get("example") or "").strip()
                if t and t not in seen:
                    seen.add(t)
                    label = (f"{a['category']} / {a['source']}"
                             if a.get("category") else a.get("source", ""))
                    merged.append({"example": t, "source": label})
            if merged:
                r["examples"] = merged
        return rows

    def _maybe_online_enrich(self, rows, page):
        """260615-13(P11b): '인터넷 사전 포함'이 켜져 있으면, 현재 페이지 단어 중
        아직 조회 안 한 것을 백그라운드로 조회·캐시(dict.db)해 패널에 자동 표시."""
        if not self._prefs.get("online_dict_enabled"):
            return
        try:
            dic = self._study_get_dict()
        except Exception:
            return
        todo, seen = [], set()
        for r in rows:
            lm = (r.get("lemma") or "").strip()
            if not lm or lm in seen:
                continue
            seen.add(lm)
            try:
                # 260617-4: 전체 자료(dict.db) 우선 — 보유 자료 있으면 인터넷 조회 생략
                if dic.is_online_fetched(lm) or dic.lookup(lm):
                    continue
            except Exception:
                continue
            todo.append((lm, r.get("lang", "eng")))
        if not todo:
            return
        todo = todo[:30]                  # 페이지당 상한(과도한 호출 방지)
        from viewer.workers import OnlineDictFetchWorker
        w = OnlineDictFetchWorker(todo, dict(self._prefs))
        self._online_worker = w           # GC 방지

        def on_done(results):
            new = self._write_online_results(dic, results)
            if new and self.search_tabs.currentWidget() is self.study_panel \
                    and self.main_view.current_page() == page:
                self._spot_terms_cache = None
                self._refresh_study_panel(page)
        w.done.connect(on_done)
        w.start()

    def _write_online_results(self, dic, results) -> bool:
        """260615-20: 인터넷 조회 결과(제공처별)를 dict.db 에 저장. (지연/재분류 공용)"""
        new = False
        for lemma, lang, provs in results:
            try:
                dic.mark_online_fetched(lemma)
            except Exception:
                pass
            for p in (provs or []):
                try:
                    dic.ensure_online_provider(p["source_id"], p["name"],
                                               p["is_termbase"])
                    kw = {"source_id": p["source_id"], "reference": p["name"],
                          "def_ko": "\n".join(p.get("def_ko", [])),
                          "def_en": "\n".join(p.get("def_en", [])),
                          "examples": "\n".join(e.get("text", "")
                                                for e in p.get("examples", [])),
                          "hanja": p.get("hanja", "")}
                    if str(lang).startswith("ko"):
                        kw["term_ko"] = lemma
                    else:
                        kw["term_en"] = lemma
                    dic.add_entry(**kw); new = True
                except Exception:
                    pass
        return new

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
        if fav:
            self._law_panel.show_saved(fav)

    def _enter_law_layout(self):
        """260616-19: 법령 패널을 메인 splitter 오른쪽 끝에 임베드(2단). 썸네일/우측패널은
        슬라이드 숨김, 책갈피는 유지. 닫을 때 복원하도록 상태 저장."""
        try:
            self._law_saved = {
                "splitter": self.splitter.saveState(),
                "search": self.act_toggle_search.isChecked(),
                "shot": self.act_toggle_shot.isChecked(),
                "split": self.act_split.isChecked(),       # 260618-8: 2단(PDF) 상태 복원용
                "handle": self.splitter.handleWidth(),
            }
            self.act_toggle_search.setChecked(False)
            self.act_toggle_shot.setChecked(False)
            # 260618-18: 책갈피·썸네일·뷰어(1단)·법령 표시 — 2단(PDF 분할)만 끔(뷰어 1단)
            if self.act_split.isChecked():
                self.act_split.setChecked(False)
            self._sync_right_layout()          # 우측 검색/스크린샷 패널 → 드로어(숨김)
            self.splitter.addWidget(self._law_panel)   # 오른쪽 끝(2단)
            self.splitter.setHandleWidth(8)
            for i in range(self.splitter.count()):
                self.splitter.setCollapsible(i, True)
            # 법령 패널은 접힘 방지(수직선을 끝까지 끌어도 버튼이 사라지지 않게)
            il = self.splitter.indexOf(self._law_panel)
            if 0 <= il < self.splitter.count():
                self.splitter.setCollapsible(il, False)
            self._law_panel.set_fullscreen(False)
            self._apply_law_embed_sizes()
        except Exception:
            pass

    def _apply_law_embed_sizes(self):
        """260618-18: 책갈피 | 썸네일 | 뷰어(1단) | 법령 순으로 표시.
        (우측 검색/스크린샷 패널만 숨김 — 책갈피·썸네일은 보이게.)"""
        try:
            n = self.splitter.count()
            total = sum(self.splitter.sizes()) or max(1100, self.width())
            bk, th = 170, 120
            im = self.splitter.indexOf(self.main_split)
            il = self.splitter.indexOf(self._law_panel)
            ith = self.splitter.indexOf(self.page_thumbs)
            rest = max(420, total - bk - th)
            vw = rest // 2
            lw = rest - vw
            sizes = [0] * n
            sizes[0] = bk                          # 책갈피
            if 0 <= ith < n:
                sizes[ith] = th                    # 썸네일
            if 0 <= im < n:
                sizes[im] = vw                     # 뷰어(1단)
            if 0 <= il < n:
                sizes[il] = lw                     # 법령
            self.splitter.setSizes(sizes)
        except Exception:
            pass

    def _toggle_law_fullscreen(self):
        """260616-19: 임베드 ↔ 전체화면(별도 창) 전환."""
        if self._law_panel is None:
            return
        from viewer.widgets.law_search_dialog import LawHostWindow
        if self._law_window is None:
            # 임베드 → 전체화면 팝아웃 (현재 임베드 크기 기억해 복귀 시 복원)
            self._law_embed_sizes = self.splitter.sizes()
            self._law_window = LawHostWindow()
            self._law_window.setWindowTitle("법령/고시 (전체화면)")
            from PyQt6.QtWidgets import QVBoxLayout
            lay = QVBoxLayout(self._law_window)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self._law_panel)     # splitter 에서 분리·재부모화
            self._law_window.closed.connect(self._embed_law_from_window)
            self._law_panel.set_fullscreen(True)
            self._law_window.showMaximized()
        else:
            # 전체화면 → 임베드 복귀
            self._embed_law_from_window()

    def _embed_law_from_window(self):
        """전체화면 창의 패널을 메인 오른쪽 2단으로 복귀."""
        if self._law_panel is None:
            return
        win = self._law_window
        self._law_window = None
        try:
            self.splitter.addWidget(self._law_panel)   # 재부모화(임베드)
            self._law_panel.set_fullscreen(False)
            # 전체화면 전 임베드 크기 복원(원래 화면 크기 유지)
            saved = getattr(self, "_law_embed_sizes", None)
            if saved and len(saved) == self.splitter.count():
                self.splitter.setSizes(saved)
            else:
                self._apply_law_embed_sizes()
            self._law_panel.show()
        except Exception:
            pass
        if win is not None:
            try:
                win.closed.disconnect()
            except Exception:
                pass
            win.deleteLater()

    def _close_law(self):
        """260616-19: 법령 패널을 닫고 메인 레이아웃 복원."""
        panel = self._law_panel
        win = self._law_window
        self._law_panel = None
        self._law_window = None
        try:
            if panel is not None:
                panel.setParent(None)          # splitter/창에서 제거
                panel.deleteLater()
            if win is not None:
                try:
                    win.closed.disconnect()
                except Exception:
                    pass
                win.close()
                win.deleteLater()
        except Exception:
            pass
        # 메인 레이아웃 복원
        s = getattr(self, "_law_saved", None) or {}
        try:
            if "handle" in s:
                self.splitter.setHandleWidth(s["handle"])
            if "search" in s:
                self.act_toggle_search.setChecked(s["search"])
            if "shot" in s:
                self.act_toggle_shot.setChecked(s["shot"])
            if "split" in s:                          # 260618-8: 2단(PDF) 상태 복원
                self.act_split.setChecked(s["split"])
            self._sync_right_layout()
            if s.get("splitter"):
                self.splitter.restoreState(s["splitter"])
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

    def _action_reclassify_onterm(self, checked: bool = False):
        """260615-20: 온용어 캐시 비우고 다시 분류(재조회) — 용어집(glossary)별로 재저장."""
        dic = self._study_get_dict()
        terms = dic.onterm_cached_terms()
        if not terms:
            QMessageBox.information(self, "온용어 다시 분류",
                                   "재분류할 온용어 캐시가 없습니다.")
            return
        if not (self._prefs.get("onterm_key") or "").strip():
            QMessageBox.information(self, "온용어 다시 분류",
                                   "설정에 온용어 인증키를 먼저 입력하세요.")
            return
        if QMessageBox.question(
                self, "온용어 다시 분류(재조회)",
                f"기존 온용어 캐시({len(terms)}개 단어)를 비우고 인터넷에서 다시 받아\n"
                "용어집(glossary)별로 분류합니다. (인터넷 사용)\n계속할까요?") \
                != QMessageBox.StandardButton.Yes:
            return
        dic.clear_onterm_cache(terms)
        op = {"online_dict_enabled": True,
              "urimalsaem_key": self._prefs.get("urimalsaem_key", ""),
              "stdict_key": self._prefs.get("stdict_key", ""),
              "onterm_key": self._prefs.get("onterm_key", "")}
        from viewer.workers import OnlineDictFetchWorker
        self.progress.setVisible(True); self.progress.setRange(0, 0)
        self.status.showMessage(f"온용어 재조회 중... ({len(terms)}개)")
        w = OnlineDictFetchWorker(terms, op)
        self._onterm_recl_worker = w

        def on_done(results):
            self.progress.setVisible(False)
            n = self._write_online_results(dic, results)
            self._spot_terms_cache = None
            self._refresh_study_panel(self.main_view.current_page())
            QMessageBox.information(self, "온용어 다시 분류",
                                   f"완료: {len(terms)}개 단어를 용어집별로 재분류했습니다.")
        w.done.connect(on_done)
        w.start()

    def _on_study_source_toggled(self, source_id: str, enabled: bool):
        """260611-102(P2): 사전 출처 on/off → 저장 후 패널 갱신."""
        try:
            self._study_get_dict().set_source_enabled(source_id, enabled)
        except Exception:
            pass
        self._spot_terms_cache = None     # 출처 변경 → spotting 목록 무효화
        self._refresh_study_panel(self.main_view.current_page())

    def _get_spot_terms(self):
        """260611-103(P4): 활성 사전의 다단어 표제어 [(norm, entry)] 캐시."""
        if self._spot_terms_cache is not None:
            return self._spot_terms_cache
        from viewer.study.dict_store import normalize_key
        terms = []
        try:
            for e in self._study_get_dict().all_terms():
                tko = (e.get("term_ko") or "").strip()
                ten = (e.get("term_en") or "").strip()
                if " " in tko:
                    terms.append((normalize_key(tko), e))
                if " " in ten:
                    terms.append((normalize_key(ten), e))
        except Exception:
            terms = []
        self._spot_terms_cache = terms
        return terms

    def _spot_page_terms(self, page: int):
        """260611-103(P4): 페이지 본문에서 다단어 전문용어 인식 → (term_rows, rects_map).

        rects_map: {term_key: [(x0,y0,x1,y1), ...]} (표시 좌표; 회전/ dpi 보정 포함)."""
        terms = self._get_spot_terms()
        if not terms or not self._study_pdf:
            return [], {}
        try:
            from viewer.study.study_store import file_key_for
            from viewer.study.term_spotter import spot
            store = self._study_get_store()
            fkey = file_key_for(self._study_pdf)
            words = store.get_page_words(fkey, page)
            if not words:
                return [], {}
            dpi = store.get_page_dpi(fkey, page)
            rot, rmat = (self._study_page_rotation(page)
                         if not (dpi and dpi > 0) else (0, None))
            surfaces = [w.get("surface", "") for w in words]
            matches = spot(surfaces, terms)
            # 더 긴 매칭에 완전히 포함된 짧은(하위구) 매칭은 억제 — 가장 구체적 용어 우선
            spans = [(w0, w1) for _e, w0, w1 in matches]
            def _contained(a0, a1):
                return any((b0 <= a0 and b1 >= a1 and (b1 - b0) > (a1 - a0))
                           for (b0, b1) in spans)
            matches = [(e, w0, w1) for (e, w0, w1) in matches if not _contained(w0, w1)]
            groups = {}
            for entry, w0, w1 in matches:
                x0 = y0 = 1e18
                x1 = y1 = -1e18
                for wi in range(w0, w1 + 1):
                    rx0, ry0, rx1, ry1 = self._study_disp_rect(words[wi], dpi, rot, rmat)
                    x0 = min(x0, rx0); y0 = min(y0, ry0)
                    x1 = max(x1, rx1); y1 = max(y1, ry1)
                key = (entry.get("term_ko") or entry.get("term_en") or "").strip()
                if not key:
                    continue
                g = groups.setdefault(key, {"entry": entry, "rects": [], "first": w0})
                g["rects"].append((x0, y0, x1, y1))
                g["first"] = min(g["first"], w0)
            rows, rects_map = [], {}
            for key, g in groups.items():
                e = g["entry"]
                src = self._dict_src_label(e)        # 260615-7(P9): 구분 / 출처명
                ref = (e.get("reference") or e.get("src_reference") or "").strip()
                ddefs = []
                for fld in ("def_ko", "def_en"):
                    t = (e.get(fld) or "").strip()
                    if t:
                        ddefs.append({"definition": t, "source": src, "ref": ref,
                                      "is_dict": True, "kind": e.get("src_kind")})
                ex = [{"example": x.strip(), "source": src}
                      for x in (e.get("examples") or "").split("\n") if x.strip()]
                lang = "kor" if (e.get("term_ko") or "").strip() else "eng"
                rows.append({"lemma": key, "lang": lang, "level": "전문용어",
                             "count": len(g["rects"]), "pos": g["first"],
                             "has_dict": True, "is_term": True,
                             "image": (e.get("image") or ""),
                             "definitions": ddefs, "examples": ex})
                rects_map[key] = g["rects"]
            rows.sort(key=lambda r: r["pos"])
            return rows, rects_map
        except Exception:
            return [], {}

    def _refresh_study_panel(self, page: int):
        """현재 PDF·페이지의 학습단어를 패널에 표시 (데이터 있으면)."""
        if not self._study_pdf:
            return
        try:
            from viewer.study.study_store import file_key_for
            store = self._study_get_store()
            fkey = file_key_for(self._study_pdf)
            if store.vocab_count(fkey) == 0:
                self.study_panel.set_page(page)
                self.study_panel.set_page_words(page, [])
                self.study_panel.set_status(
                    "이 PDF 의 단어장이 없습니다. [단어장 생성] 을 누르세요.")
                return
            # 260611-104(P5): 사용자 편집은 계층형 사전(dict user)에서 적용 → 여기선 자동만
            rows = store.get_page_study(fkey, page)
            rows = self._apply_word_filter(fkey, rows)        # 표시 필터(전체/선택/날짜/초기)
            rows = self._enrich_rows_with_dict(rows)          # 260611-102(P2): 사전(User▶Base) 적용
            rows = self._accumulate_and_merge_examples(rows)  # 260615-10(P12): 예시 누적·병합
            # 260611-103(P4): 다단어 전문용어 인식 → 별도 행으로 앞에 추가
            term_rows, term_rects = self._spot_page_terms(page)
            self._page_term_rects = term_rects
            rows = term_rows + rows
            self.study_panel.set_filter_dates(self._study_get_user().event_dates(fkey))
            try:
                self.study_panel.set_dict_sources(self._study_get_dict().list_sources())
            except Exception:
                pass
            self.study_panel.set_page_words(page, rows)
            self._maybe_online_enrich(rows, page)   # 260615-13(P11b): 인터넷 사전 자동 보강
            # 호버 영역 설정(메인 뷰어에서 단어 위 → 포인터 변경 + 패널 선택)
            rects = self._compute_word_rects(page, rows)
            # P4: 다단어 용어 영역도 호버/강조에 포함(키=용어 표제어)
            term_hover = [(x0, y0, x1, y1, key)
                          for key, rs in term_rects.items() for (x0, y0, x1, y1) in rs]
            rects = rects + term_hover
            self.main_view.set_hover_words(rects)
            # 본문 강조 옵션 — 단, 읽기 모드에서는 카라오케와 충돌하므로 적용하지 않음
            reading = getattr(self, "read_aloud", None) and self.read_aloud.is_active()
            if self.study_panel.is_auto_highlight() and not reading:
                self.main_view.highlight_word_rects([r[:4] for r in rects], style="all")
            # 자동 읽기: 리더가 넘긴 페이지가 아니고(사용자 이동) 새 페이지면 그 페이지부터 읽기 시작
            if (self.study_panel.is_auto_read() and not self._ar_advancing
                    and page != self._last_read_page):
                self._last_read_page = page
                self._ar_start_page(from_selection=False)
        except Exception as e:
            self.study_panel.set_status(f"단어 조회 오류: {e}")

    def _on_study_page_changed(self, page: int):
        # 단어장 탭이 활성일 때만 갱신(비용 절약). 탭 전환 시에도 1회 갱신됨.
        if self.search_tabs.currentWidget() is self.study_panel:
            self._refresh_study_panel(page)

    # --- 음성 읽기 / 편집 / 내보내기 / 본문강조 (260603) -------------------
    def _ar_start_page(self, from_selection: bool = True) -> None:
        """단어장 자동읽기 — 현재 페이지의 단어를 한 개씩(정렬 순서) 읽기 시작.
        from_selection=True 이고 선택 단어가 있으면 그 위치부터."""
        tts = self._study_get_tts()
        if not tts.available():
            return
        self._ar_items = self.study_panel.shown_lemmas()   # 정렬·필터 반영 순서
        if not self._ar_items:
            self._autoread_timer.stop()
            return
        self._ar_idx = 0
        if from_selection:
            sel = self.study_panel.current_lemma()
            if sel:
                for k, (lm, _l) in enumerate(self._ar_items):
                    if lm == sel:
                        self._ar_idx = k
                        break
        self._ar_speak_current()
        self._autoread_timer.start()

    def _ar_speak_current(self) -> None:
        """현재 인덱스 단어: 단어장 상단으로 + 메인 강조 + (재생내용 포함) 음성."""
        if not (0 <= self._ar_idx < len(self._ar_items)):
            return
        lemma, lang = self._ar_items[self._ar_idx]
        self.study_panel.select_lemma(lemma, to_top=True)   # 단어장 상단 표시
        self._highlight_vocab_word(lemma)                    # 메인 뷰어 강조
        row = next((r for r in self.study_panel._rows if r["lemma"] == lemma), None)
        segs = self._study_read_text_for(row) if row else [(lemma, lang)]
        tts = self._study_get_tts()
        for i, (text, lg) in enumerate(segs):
            tts.speak(text, lg, queue=(i > 0))               # 단어→뜻→예시 순차

    def _highlight_vocab_word(self, lemma: str) -> None:
        """단어장 단어를 메인 뷰어에서 강조(주황). 현재 페이지를 보여줌."""
        page = self.main_view.current_page()
        rects = [r[:4] for r in self._compute_word_rects(page,
                 self.study_panel._shown_rows()) if r[4] == lemma]
        if rects:
            self.main_view.highlight_word_rects(rects, style="read_vocab")

    def _on_autoread_tick(self) -> None:
        if not self.study_panel.is_auto_read():
            self._autoread_timer.stop()
            return
        tts = self._study_get_tts()
        if tts.is_speaking():
            return
        self._ar_idx += 1
        if self._ar_idx < len(self._ar_items):
            self._ar_speak_current()
            return
        # 현재 페이지 단어 끝 → 모드별 처리
        mode = self.study_panel.read_mode()
        from viewer.widgets.study_panel import (
            READ_ONCE, READ_REPEAT, READ_ALL_ONCE, READ_ALL_REPEAT)
        if mode == READ_REPEAT:                  # 현재 페이지 반복
            self._ar_idx = 0
            self._ar_speak_current()
        elif mode in (READ_ALL_ONCE, READ_ALL_REPEAT):
            nxt = self._next_vocab_page(self.main_view.current_page(),
                                        wrap=(mode == READ_ALL_REPEAT))
            if nxt is None:
                self._stop_autoread()
            else:
                self._ar_advancing = True
                self.main_view.go_to_page(nxt)   # 메인 화면=읽는 페이지
                self._refresh_study_panel(nxt)   # 패널 갱신(리더 주도)
                self._ar_advancing = False
                self._last_read_page = nxt
                self._ar_start_page(from_selection=False)
        else:                                    # 1회
            self._stop_autoread()

    def _next_vocab_page(self, cur: int, wrap: bool):
        """cur 다음으로 어휘가 있는 페이지. 없으면 wrap 시 첫 어휘 페이지, 아니면 None."""
        try:
            from viewer.study.study_store import file_key_for
            store = self._study_get_store()
            pages = store.vocab_pages(file_key_for(self._study_pdf))
        except Exception:
            return None
        later = [p for p in pages if p > cur]
        if later:
            return later[0]
        return pages[0] if (wrap and pages) else None

    def _stop_autoread(self) -> None:
        self._autoread_timer.stop()
        try:
            self._study_get_tts().stop()
        except Exception:
            pass
        self.study_panel.set_playing(False)     # ▶ 로 복귀

    def _on_study_autoread(self, on: bool) -> None:
        if on:
            self._last_read_page = self.main_view.current_page()
            self._ar_start_page(from_selection=True)   # 선택 단어부터
        else:                       # 끄면 즉시 정지
            self._stop_autoread()

    def _on_main_word_hovered(self, lemma: str) -> None:
        self.study_panel.select_lemma(lemma)        # 단어장에서 선택(배경 강조)
        if self.study_panel.is_speak_on_select():   # 260606: 본 화면 선택시 읽기
            row = next((r for r in self.study_panel._rows if r["lemma"] == lemma), None)
            lang = row.get("lang", "eng") if row else "eng"
            self._study_get_tts().speak(lemma, lang)

    # --- 표시 필터 / 선택단어 / mp3 (260606) ----------------------------
    def _apply_word_filter(self, fkey: str, rows: list) -> list:
        from viewer.widgets.study_panel import (FILTER_ALL, FILTER_SELECTED, FILTER_ORIG)
        f = self.study_panel.word_filter()
        user = self._study_get_user()
        if f == FILTER_ORIG:
            return rows                                    # 초기: 원본 전체
        if f == FILTER_SELECTED:
            sel = user.selected_set(fkey)
            return [r for r in rows if r["lemma"] in sel]
        if f == FILTER_ALL:
            dele = user.deleted_set(fkey)                  # 현재 삭제 반영
            return [r for r in rows if r["lemma"] not in dele]
        # 날짜 D: 그 날짜까지의 삭제 반영(스냅샷)
        dele = user.deleted_set(fkey, upto_date=f)
        return [r for r in rows if r["lemma"] not in dele]

    def _on_study_cross_page(self, direction: int) -> None:
        """단어장 목록 끝에서 ↑/↓ → 이전/다음 어휘 페이지로, 위치는 마지막/첫 단어."""
        if not self._study_pdf:
            return
        cur = self.main_view.current_page()
        if direction < 0:
            nxt = self._prev_vocab_page(cur)
        else:
            nxt = self._next_vocab_page(cur, wrap=False)
        if nxt is None:
            return
        self.main_view.go_to_page(nxt)
        self._refresh_study_panel(nxt)
        if direction < 0:
            self.study_panel.select_last()      # 위 페이지 → 마지막 단어
        else:
            self.study_panel.select_first()     # 아래 페이지 → 첫 단어

    def _prev_vocab_page(self, cur: int):
        try:
            from viewer.study.study_store import file_key_for
            pages = self._study_get_store().vocab_pages(file_key_for(self._study_pdf))
        except Exception:
            return None
        earlier = [p for p in pages if p < cur]
        return earlier[-1] if earlier else None

    def _on_study_mark_selected(self) -> None:
        lm = self.study_panel.current_lemma()
        if not lm or not self._study_pdf:
            return
        from viewer.study.study_store import file_key_for
        self._study_get_user().add_event(file_key_for(self._study_pdf), lm, "select")
        self.status.showMessage(f"'{lm}' 선택단어로 저장", 2000)
        self.study_panel.select_next()

    def _on_study_delete_word(self) -> None:
        lm = self.study_panel.current_lemma()
        if not lm or not self._study_pdf:
            return
        from viewer.study.study_store import file_key_for
        self._study_get_user().add_event(file_key_for(self._study_pdf), lm, "delete")
        self.status.showMessage(f"'{lm}' 리스트에서 삭제(모든 페이지)", 2000)
        self._refresh_study_panel(self.main_view.current_page())   # 즉시 사라짐

    def _study_read_text_for(self, row: dict) -> list:
        """재생내용 옵션을 반영한 (text,lang) 세그먼트: 단어 + 한/영뜻 + 예시."""
        import re as _re
        lang = row.get("lang", "eng")
        segs = [(row["lemma"], lang)]
        c = self.study_panel.content_read()
        defs = row.get("definitions") or []
        ko = [d["definition"] for d in defs if _re.search(r"[가-힣]", d["definition"])]
        en = [d["definition"] for d in defs if not _re.search(r"[가-힣]", d["definition"])]
        if c["ko"] and ko:
            segs.append((ko[0], "kor"))
        if c["en"] and en:
            segs.append((en[0], "eng"))
        if c["ex"] and row.get("examples"):
            ex = row["examples"][0]["example"]
            segs.append((ex, "kor" if _re.search(r"[가-힣]", ex) else "eng"))
        return segs

    def _on_study_mp3(self) -> None:
        """전체 페이지 단어장을 페이지별 mp3(+가사 lrc)로 폴더에 저장."""
        if not self._study_pdf:
            QMessageBox.information(self, "mp3", "먼저 단어장을 생성하세요.")
            return
        from viewer.study.study_store import file_key_for
        store = self._study_get_store()
        fkey = file_key_for(self._study_pdf)
        if store.vocab_count(fkey) == 0:
            QMessageBox.information(self, "mp3", "단어장이 없습니다.")
            return
        # 읽는 중이면 중지(끊김 방지)
        if getattr(self, "read_aloud", None) and self.read_aloud.is_active():
            self.read_aloud.stop()
        if self.study_panel.is_playing():
            self.study_panel.set_playing(False); self._stop_autoread()

        from PyQt6.QtWidgets import QFileDialog
        stem = Path(self._study_pdf).stem
        parent = QFileDialog.getExistingDirectory(
            self, "mp3 저장 폴더 선택", str(Path(self._study_pdf).parent))
        if not parent:
            return
        from viewer.study.mp3_export import unique_dir
        base = Path(parent) / f"{stem}_MP3"
        resume = False
        if base.exists() and any(base.glob("*.mp3")):
            ret = QMessageBox.question(
                self, "이어서 저장",
                f"'{base.name}' 폴더에 mp3 가 있습니다.\n"
                "기존 폴더에 이어서 저장할까요?\n(예=이미 있는 페이지는 건너뜀, 아니오=새 폴더)")
            if ret == QMessageBox.StandardButton.Yes:
                out_dir, resume = base, True
            else:
                out_dir = unique_dir(base)
        else:
            out_dir = base
        out_dir.mkdir(parents=True, exist_ok=True)

        # 페이지별 세그먼트 구성(현재 표시필터·재생내용 반영)
        try:
            total_pages = self.main_view._doc.page_count
        except Exception:
            total_pages = 999
        width = max(2, len(str(total_pages)))
        overrides = self._study_get_user().all_words()
        jobs = []
        for p in store.vocab_pages(fkey):
            rows = store.get_page_study(fkey, p, user_overrides=overrides)
            rows = self._apply_word_filter(fkey, rows)
            segs = []
            for r in rows:
                segs.extend(self._study_read_text_for(r))
            if not segs:
                continue
            name = f"{stem}_{p + 1:0{width}d}"
            jobs.append((str(out_dir / f"{name}.mp3"), str(out_dir / f"{name}.lrc"), segs))
        if not jobs:
            QMessageBox.information(self, "mp3", "저장할 내용이 없습니다.")
            return

        from viewer.workers import StudyMp3Worker
        self.progress.setVisible(True); self.progress.setRange(0, len(jobs))
        worker = StudyMp3Worker(jobs, rate=self.read_aloud.rate,
                                voice_name=getattr(self.read_aloud, "voice_name", None),
                                resume=resume)

        def on_prog(i, n, msg):
            self.progress.setValue(i); self.status.showMessage(f"mp3: {msg}")

        def on_fin(res):
            self.progress.setVisible(False)
            if res.get("error"):
                QMessageBox.warning(self, "mp3 저장 실패", res["error"])
            else:
                self.status.showMessage(
                    f"mp3 저장 완료: {res.get('saved')}/{res.get('total')} 페이지 → "
                    f"{out_dir.name}", 6000)

        worker.progress.connect(on_prog)
        worker.finished.connect(on_fin)
        run_in_thread(worker, self._study_threads)

    # ===== 260606-3: 메인창 mp3(현재 PDF를 책갈피 기준 분할 저장) =====
    @staticmethod
    def _safe_name(s: str, fallback: str) -> str:
        import re as _re
        s = _re.sub(r'[\\/:*?"<>|]+', "_", (s or "").strip())
        s = _re.sub(r"\s+", " ", s).strip(" .")
        return s[:80] if s else fallback

    @staticmethod
    def _seg_lang(s: str) -> str:
        import re as _re
        return "ko" if _re.search(r"[가-힣]", s or "") else "en"

    def _doc_sections(self, doc, level: int):
        """get_toc 를 기준으로 (제목, 시작페이지0based, 끝페이지exclusive) 구간 목록.
        분할점 = level 이하 책갈피. 책갈피 없으면 전체 1개 구간."""
        try:
            toc = doc.get_toc(simple=True)      # [lvl, title, page(1based)]
        except Exception:
            toc = []
        total = doc.page_count
        pts = []
        for lv, title, pg in toc:
            if lv <= level:
                p0 = max(0, min(total - 1, int(pg) - 1))
                pts.append((p0, title))
        if not pts:
            return None      # 책갈피 없음 → 전체
        # 시작페이지 정렬·병합(같은 페이지 다중 책갈피는 첫 제목 사용)
        pts.sort(key=lambda x: x[0])
        secs = []
        for i, (p0, title) in enumerate(pts):
            end = pts[i + 1][0] if i + 1 < len(pts) else total
            if end <= p0:
                end = p0 + 1
            secs.append((title, p0, end))
        return secs

    def _on_main_mp3(self, checked: bool = False, view=None) -> None:
        view = view or self.main_view
        path = view.current_file()
        if not path or not str(path).lower().endswith(".pdf"):
            QMessageBox.information(self, "mp3", "먼저 PDF를 표시하세요.")
            return
        try:
            doc = view._doc.doc
        except Exception:
            QMessageBox.information(self, "mp3", "PDF 문서를 찾을 수 없습니다.")
            return

        # 책갈피 위계 선택(존재하는 깊이까지만)
        try:
            toc = doc.get_toc(simple=True)
        except Exception:
            toc = []
        maxlv = min(3, max((lv for lv, *_ in toc), default=0))
        level = 1
        if maxlv >= 1:
            from PyQt6.QtWidgets import QInputDialog
            opts = [f"{i}단계 책갈피 기준" for i in range(1, maxlv + 1)]
            sel, ok = QInputDialog.getItem(
                self, "mp3 분할 기준", "어느 위계의 책갈피로 나눌까요?",
                opts, 0, False)
            if not ok:
                return
            level = opts.index(sel) + 1
        # (책갈피 없으면 전체 1개)

        # 읽는 중이면 중지 + 텍스트 추출 대상을 이 창으로
        if getattr(self, "read_aloud", None) and self.read_aloud.is_active():
            self.read_aloud.stop()
        self.read_aloud.set_target(view)

        from PyQt6.QtWidgets import QFileDialog
        stem = Path(path).stem
        parent = QFileDialog.getExistingDirectory(
            self, "mp3 저장 폴더 선택", str(Path(path).parent))
        if not parent:
            return
        from viewer.study.mp3_export import unique_dir
        base = Path(parent) / f"{stem}_MP3"
        resume = False
        if base.exists() and any(base.glob("*.mp3")):
            ret = QMessageBox.question(
                self, "이어서 저장",
                f"'{base.name}' 폴더에 mp3 가 있습니다.\n"
                "기존 폴더에 이어서 저장할까요?\n(예=이미 있는 파일은 건너뜀, 아니오=새 폴더)")
            if ret == QMessageBox.StandardButton.Yes:
                out_dir, resume = base, True
            else:
                out_dir = unique_dir(base)
        else:
            out_dir = base
        out_dir.mkdir(parents=True, exist_ok=True)

        # 구간 → 세그먼트
        from viewer.widgets.read_aloud import sentences_of
        secs = self._doc_sections(doc, level)
        if secs is None:
            secs = [(stem, 0, doc.page_count)]
        width = max(2, len(str(len(secs))))
        jobs = []
        for i, (title, p0, p1) in enumerate(secs):
            segs = []
            for p in range(p0, p1):
                txt = self.read_aloud._page_text(p)
                for s in sentences_of(txt):
                    segs.append((s, self._seg_lang(s)))
            if not segs:
                continue
            nm = f"{i + 1:0{width}d}_{self._safe_name(title, stem)}"
            jobs.append((str(out_dir / f"{nm}.mp3"),
                         str(out_dir / f"{nm}.lrc"), segs))
        if not jobs:
            QMessageBox.information(self, "mp3", "읽을 본문을 찾지 못했습니다.")
            return

        from viewer.workers import StudyMp3Worker
        self.progress.setVisible(True); self.progress.setRange(0, len(jobs))
        worker = StudyMp3Worker(jobs, rate=self.read_aloud.rate,
                                voice_name=getattr(self.read_aloud, "voice_name", None),
                                resume=resume)

        def on_prog(i, n, msg):
            self.progress.setValue(i); self.status.showMessage(f"mp3: {msg}")

        def on_fin(res):
            self.progress.setVisible(False)
            if res.get("error"):
                QMessageBox.warning(self, "mp3 저장 실패", res["error"])
            else:
                self.status.showMessage(
                    f"mp3 저장 완료: {res.get('saved')}/{res.get('total')} 구간 → "
                    f"{out_dir.name}", 6000)

        worker.progress.connect(on_prog)
        worker.finished.connect(on_fin)
        run_in_thread(worker, self._study_threads)

    def _on_study_speak(self, lemma: str, lang: str) -> None:
        tts = self._study_get_tts()
        if not tts.available():
            self.status.showMessage("음성(SAPI)을 사용할 수 없습니다.", 3000)
            return
        tts.speak(lemma, lang)

    def _on_study_edit(self, lemma: str, lang: str) -> None:
        """260611-104(P5): 선택 단어/용어 편집 → 사용자 사전(dict_entry user) 등록/수정/삭제."""
        self._open_term_editor(lemma=lemma, lang=lang)

    def _on_study_add_term(self) -> None:
        """260611-104(P5): 빈 양식으로 새 용어 등록(＋)."""
        self._open_term_editor(lemma="", lang="kor")

    def _open_term_editor(self, *, lemma: str, lang: str) -> None:
        from viewer.widgets.study_edit_dialog import StudyEditDialog
        dic = self._study_get_dict()
        # 기존 사용자 항목 찾기(있으면 수정, 없으면 base/auto 로 초기값 채워 새로 생성)
        entry, eid = {}, None
        if lemma:
            hits = dic.lookup(lemma)
            uhit = next((h for h in hits if h.get("src_kind") == "user"), None)
            if uhit:
                eid = uhit["entry_id"]
                entry = dict(uhit)
            else:
                base = hits[0] if hits else None
                if base:                       # base 정의를 초기값으로(저장 시 user 로 복제)
                    entry = {"term_ko": base.get("term_ko", ""),
                             "term_en": base.get("term_en", ""),
                             "hanja": base.get("hanja", ""),
                             "def_ko": base.get("def_ko", ""),
                             "def_en": base.get("def_en", ""),
                             "examples": base.get("examples", ""),
                             "reference": base.get("reference", ""),
                             "image": base.get("image", ""),
                             "image_ref": base.get("image_ref", "")}
                else:                          # 사전에 없으면 표제어만 채움 + 자동 뜻 가져오기
                    if str(lang).startswith("ko"):
                        entry["term_ko"] = lemma
                    else:
                        entry["term_en"] = lemma
                    entry.update(self._auto_def_for(lemma))
        online = None
        if self._prefs.get("online_dict_enabled"):
            def online(ko, en):
                from viewer.study.online_dict import lookup_all
                return lookup_all(ko, en, prefs=self._prefs)
        dlg = StudyEditDialog(entry, related_provider=self._dict_related,
                              online_provider=online,
                              allow_delete=(eid is not None),
                              title=("용어 편집 — " + lemma) if lemma else "용어 추가",
                              parent=self)
        if not dlg.exec():
            return
        if dlg.is_deleted() and eid is not None:
            dic.delete_entry(eid)
            self.status.showMessage("용어 삭제(사용자 사전)", 2500)
        else:
            v = dlg.values()
            if eid is not None:
                dic.update_entry(eid, **v)
            else:
                from viewer.study.dict_store import USER_SOURCE_ID
                dic.add_entry(source_id=USER_SOURCE_ID, **v)
            self.status.showMessage(
                f"'{v.get('term_ko') or v.get('term_en')}' 저장(사용자 사전)", 2500)
        self._spot_terms_cache = None
        self._refresh_study_panel(self.main_view.current_page())

    def _dict_related(self, query: str) -> list:
        """편집기 '관련 단어' 공급자 — 사전 부분일치(중복 entry 표제어 1회씩)."""
        try:
            rows = self._study_get_dict().search(query, limit=60)
        except Exception:
            return []
        seen, out = set(), []
        for r in rows:
            key = (r.get("term_ko") or r.get("term_en") or "").strip()
            if key and key not in seen:
                seen.add(key); out.append(r)
        return out

    def _auto_def_for(self, lemma: str) -> dict:
        """자동(study.db) 뜻/예시를 편집 초기값으로 — 한글/영어 칸 자동 배치."""
        out = {}
        try:
            from viewer.study.study_store import file_key_for
            store = self._study_get_store()
            fkey = file_key_for(self._study_pdf) if self._study_pdf else ""
            page = self.main_view.current_page()
            import re as _re
            for r in store.get_page_study(fkey, page):
                if r["lemma"] != lemma:
                    continue
                ko = [d["definition"] for d in (r.get("definitions") or [])
                      if _re.search(r"[가-힣]", d["definition"])]
                en = [d["definition"] for d in (r.get("definitions") or [])
                      if not _re.search(r"[가-힣]", d["definition"])]
                if ko:
                    out["def_ko"] = "\n".join(ko)
                if en:
                    out["def_en"] = "\n".join(en)
                if r.get("examples"):
                    out["examples"] = "\n".join(e["example"] for e in r["examples"])
                break
        except Exception:
            pass
        return out

    def _on_study_export(self) -> None:
        if not self._study_pdf:
            QMessageBox.information(self, "단어장", "먼저 PDF 를 열고 단어장을 생성하세요.")
            return
        from PyQt6.QtWidgets import QFileDialog
        from viewer.study.study_store import file_key_for
        store = self._study_get_store()
        fkey = file_key_for(self._study_pdf)
        if store.vocab_count(fkey) == 0:
            QMessageBox.information(self, "단어장", "단어장이 없습니다. [단어장 생성] 먼저.")
            return
        default = str(Path(self._study_pdf).with_suffix("")) + "_단어장.docx"
        out, _ = QFileDialog.getSaveFileName(self, "Word 저장", default,
                                             "Word 문서 (*.docx)")
        if not out:
            return
        sp = self.study_panel
        opts = {
            "title": Path(self._study_pdf).stem + " 단어장",
            "levels": sp.selected_levels(),                 # 현재 난이도 필터
            "user_overrides": self._study_get_user().all_words(),
            "sort": sp.sort_combo.currentText(),            # 현재 정렬
            "show_ko": sp.chk_ko.isChecked(),
            "show_en": sp.chk_en.isChecked(),
            "show_ex": sp.chk_ex.isChecked(),
        }
        # 백그라운드 저장(대용량에서 UI 멈춤 방지)
        from viewer.workers import StudyExportWorker
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        worker = StudyExportWorker(store.db_path, fkey, out, opts)

        def on_prog(i, n, _m):
            if n:
                self.progress.setRange(0, n)
                self.progress.setValue(i)

        def on_fin(res):
            self.progress.setVisible(False)
            if res.get("error"):
                QMessageBox.warning(self, "Word 저장 실패", res["error"])
            else:
                self.status.showMessage(f"Word 저장 완료: {Path(out).name}", 4000)

        worker.progress.connect(on_prog)
        worker.finished.connect(on_fin)
        run_in_thread(worker, self._study_threads)

    def _on_study_auto_highlight(self, on: bool) -> None:
        if on:
            self._refresh_study_panel(self.main_view.current_page())
        else:
            self.main_view.clear_word_highlights()

    def _study_page_rotation(self, page: int):
        """260611-99: 메인뷰에 렌더되는 해당 페이지의 (회전각, 회전행렬).

        PPT→PDF 는 슬라이드를 세로 MediaBox + /Rotate 90 로 저장하는 경우가 많아,
        텍스트 레이어 좌표(get_text)는 '회전 전' 공간이지만 페이지는 회전되어 렌더된다.
        레이어 단어 좌표를 표시 공간으로 옮기기 위한 회전행렬을 돌려준다."""
        try:
            mv = getattr(self, "main_view", None)
            doc = mv._doc.doc if (mv is not None and getattr(mv, "_doc", None)) else None
            if doc is None:
                return 0, None
            p = doc.load_page(int(page))
            return p.rotation, p.rotation_matrix
        except Exception:
            return 0, None

    def _study_disp_rect(self, w, dpi, rot, rmat):
        """단어 저장좌표 → 메인뷰 표시 좌표(PDF point).
        OCR(dpi>0): 렌더 픽셀(회전 반영됨) → 72/dpi 스케일. 레이어(dpi=0): 회전 보정."""
        if dpi and dpi > 0:
            s = 72.0 / dpi
            return (w["x0"] * s, w["y0"] * s, w["x1"] * s, w["y1"] * s)
        if rot and rmat is not None:
            import fitz
            r = fitz.Rect(w["x0"], w["y0"], w["x1"], w["y1"]) * rmat
            r.normalize()
            return (r.x0, r.y0, r.x1, r.y1)
        return (w["x0"], w["y0"], w["x1"], w["y1"])

    def _compute_word_rects(self, page: int, rows: list) -> list:
        """페이지의 단어장 단어 영역 [(x0,y0,x1,y1,lemma)] (PDF point). 호버·본문강조 공용."""
        if not self._study_pdf:
            return []
        try:
            import re as _re
            from viewer.study.study_store import file_key_for
            from viewer.study.vocab import lemma_en
            store = self._study_get_store()
            fkey = file_key_for(self._study_pdf)
            lemset = {r["lemma"] for r in rows}
            ko = any(r.get("lang", "eng").startswith("ko") for r in rows)
            words = store.get_page_words(fkey, page)
            dpi = store.get_page_dpi(fkey, page)
            rot, rmat = (self._study_page_rotation(page) if not (dpi and dpi > 0)
                         else (0, None))
            out = []
            for w in words:
                s = (w.get("surface") or "")
                clean = _re.sub(r"[^0-9a-z가-힣]", "", s.lower())
                if not clean:
                    continue
                lemma = None
                if clean in lemset:
                    lemma = clean
                elif lemma_en(clean) in lemset:
                    lemma = lemma_en(clean)
                elif ko:
                    lemma = next((lm for lm in lemset if len(lm) >= 2 and lm in clean), None)
                if lemma:
                    out.append((*self._study_disp_rect(w, dpi, rot, rmat), lemma))
            return out
        except Exception:
            return []

    def _highlight_all_page_words(self, page: int, rows: list) -> None:
        """페이지의 단어장 단어 전체를 메인 뷰어에 옅게 강조(본문강조 옵션)."""
        rects = self._compute_word_rects(page, rows)
        self.main_view.highlight_word_rects([r[:4] for r in rects], style="all")

    def _on_study_word_activated(self, lemma: str, page: int):
        """단어 클릭 → 현재 페이지에서 해당 표제어 위치를 하이라이트.
        260611-103(P4): 다단어 전문용어면 미리 계산된 영역(rects)으로 강조."""
        if not self._study_pdf:
            return
        # P4: 다단어 용어(spotted)면 캐시된 rects 로 바로 강조
        tr = (self._page_term_rects or {}).get(lemma)
        if tr:
            if self.main_view.current_page() != page:
                self.main_view.go_to_page(page)
            self.main_view.highlight_word_rects([r[:4] for r in tr])
            self.status.showMessage(f"'{lemma}' {len(tr)}곳 표시", 2500)
            return
        try:
            from viewer.study.study_store import file_key_for
            from viewer.study.vocab import lemma_en
            store = self._study_get_store()
            fkey = file_key_for(self._study_pdf)
            # 현재 메인 페이지가 다르면 이동
            if self.main_view.current_page() != page:
                self.main_view.go_to_page(page)
            words = store.get_page_words(fkey, page)
            dpi = store.get_page_dpi(fkey, page)
            # 260611-99: 레이어(회전 PDF) 좌표 보정 — PPT→PDF /Rotate 대응
            rot, rmat = (self._study_page_rotation(page) if not (dpi and dpi > 0)
                         else (0, None))
            import re as _re
            base = lemma[:-1] if lemma.endswith("다") else lemma
            rects = []
            for w in words:
                s = (w.get("surface") or "")
                # OCR surface 의 따옴표·문장부호 제거 후 비교
                clean = _re.sub(r"[^0-9a-z가-힣]", "", s.lower())
                if not clean:
                    continue
                hit = (clean == lemma or lemma_en(clean) == lemma
                       or (base and base in clean))
                if hit:
                    rects.append(self._study_disp_rect(w, dpi, rot, rmat))
            self.main_view.highlight_word_rects(rects)
            if rects:
                self.status.showMessage(f"'{lemma}' {len(rects)}곳 표시", 2500)
        except Exception as e:
            self.status.showMessage(f"하이라이트 오류: {e}", 3000)

    def _action_import_glossary(self, checked: bool = False):
        """260611-101(P3): 용어집(PDF/CSV) 가져오기 → 전문 용어사전 보강.

        PDF: 'Ÿ' 불릿 `한글명(English)` 형식. CSV: 첫 행 헤더(term_ko/term_en/def_ko/
        def_en/examples/reference/level) 자동 매핑. 기본/사용자 출처로 적재(멱등)."""
        from PyQt6.QtWidgets import QFileDialog, QInputDialog
        fn, _ = QFileDialog.getOpenFileName(
            self, "용어집 파일 선택", "",
            "용어집 (*.pdf *.csv *.tsv *.txt);;모든 파일 (*.*)")
        if not fn:
            return
        name, ok = QInputDialog.getText(
            self, "용어집 이름", "사전(출처) 표시명:",
            text=Path(fn).stem)
        if not ok or not name.strip():
            return
        ref, _ = QInputDialog.getText(
            self, "참고문헌", "참고문헌/출처 인용 (선택):", text=name.strip())
        kind_label, ok = QInputDialog.getItem(
            self, "사전 구분", "어느 사전으로 넣을까요?",
            ["기본 사전(Base)", "내 사전(User)"], 0, False)
        if not ok:
            return
        kind = "user" if kind_label.startswith("내") else "base"
        tb_label, ok = QInputDialog.getItem(
            self, "사전 종류", "용어 난이도 분류:",
            ["전문 용어집(전문용어로 분류)", "일반 사전(난이도 분류 안 함)"], 0, False)
        if not ok:
            return
        is_termbase = tb_label.startswith("전문")
        # 260615-7(P9): 구분(일반/도로/IT 등) — 기존 구분 목록 + 새로 입력
        try:
            cats = sorted({(s.get("category") or "").strip()
                           for s in self._study_get_dict().list_sources()
                           if (s.get("category") or "").strip()})
        except Exception:
            cats = []
        cat_label, ok = QInputDialog.getItem(
            self, "구분", "구분(분류) — 선택하거나 새로 입력:",
            (cats + ["(구분 없음)"]) or ["(구분 없음)"], 0, True)
        if not ok:
            return
        category = "" if cat_label.strip() in ("", "(구분 없음)") else cat_label.strip()
        import re as _re
        sid = _re.sub(r"[^0-9a-z]+", "_", Path(fn).stem.lower()).strip("_") or "glossary"
        try:
            from viewer.study.glossary_import import import_glossary_file
            store = self._study_get_dict()
            mapping = {f: f for f in ("term_ko", "term_en", "def_ko", "def_en",
                                      "examples", "reference", "level", "hanja", "image")}
            n = import_glossary_file(store, fn, source_id=sid, name=name.strip(),
                                     reference=ref.strip(), kind=kind,
                                     csv_mapping=mapping, is_termbase=is_termbase,
                                     category=category)
            self._spot_terms_cache = None      # 용어 추가 → spotting 목록 무효화
            QMessageBox.information(
                self, "용어집 가져오기",
                f"'{name.strip()}' — {n}개 용어를 {kind_label} 에 적재했습니다.")
            self.status.showMessage(f"용어집 적재: {name.strip()} ({n}개)", 4000)
            self._refresh_study_panel(self.main_view.current_page())
        except Exception as e:
            QMessageBox.warning(self, "용어집 가져오기", f"실패: {e}")

    def _action_save_csv_sample(self, checked: bool = False):
        """260615-6: ⑦ 사용자 CSV 사전 양식 예제를 저장(헤더+예시 행)."""
        from PyQt6.QtWidgets import QFileDialog
        from viewer.resources_path import resource_path
        import shutil
        src = resource_path("dict/sample_glossary.csv")
        out, _ = QFileDialog.getSaveFileName(
            self, "용어집 CSV 양식 예제 저장", "용어집_양식_예제.csv", "CSV (*.csv)")
        if not out:
            return
        try:
            if src:
                shutil.copyfile(src, out)
            else:   # 동봉본이 없으면 헤더만이라도 기록
                Path(out).write_text(
                    "term_ko,term_en,def_ko,def_en,examples,reference,level,hanja\n",
                    encoding="utf-8-sig")
            QMessageBox.information(
                self, "CSV 양식 예제",
                f"양식 예제를 저장했습니다.\n{out}\n\n"
                "열: term_ko(한글표제어), term_en(영문표제어), def_ko(한글뜻), "
                "def_en(영어뜻), examples(예시), reference(참고문헌), level(난이도), hanja(한자)\n"
                "엑셀에서 편집 후 '용어집 가져오기'로 불러오세요.")
        except Exception as e:
            QMessageBox.warning(self, "CSV 양식 예제", f"저장 실패: {e}")

    def _action_sanitize_dict(self, checked: bool = False):
        """260615-17: 사전(dict.db)의 HTML 마크업(&#44;·<strong> 등) 일괄 제거."""
        try:
            n = self._study_get_dict().sanitize_markup()
            self._spot_terms_cache = None
            self._refresh_study_panel(self.main_view.current_page())
            QMessageBox.information(self, "사전 정리",
                                   f"HTML 마크업을 정리했습니다. (변경 {n}개 항목)")
        except Exception as e:
            QMessageBox.warning(self, "사전 정리", f"실패: {e}")

    def _action_backup_dict(self, checked: bool = False):
        """260615-15: 사전 백업 — dict.db + dict_images/ 를 zip 으로(여러 PC 이전·동기화)."""
        from PyQt6.QtWidgets import QFileDialog
        import zipfile
        from viewer.study.dict_store import default_db_path
        from viewer.study.image_fetch import dict_images_dir
        out, _ = QFileDialog.getSaveFileName(
            self, "사전 백업 저장", "PolyPDF_사전백업.zip", "ZIP (*.zip)")
        if not out:
            return
        # dict.db 일관성 위해 연결 닫기(이후 지연 재오픈)
        try:
            if getattr(self, "_dict_store", None) is not None:
                self._dict_store.close(); self._dict_store = None
        except Exception:
            pass
        try:
            dbp = default_db_path()
            imgs = dict_images_dir()
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                if dbp.exists():
                    z.write(str(dbp), "dict.db")
                for f in imgs.glob("*"):
                    if f.is_file():
                        z.write(str(f), f"dict_images/{f.name}")
            QMessageBox.information(self, "사전 백업",
                                   f"사전(용어·그림·인터넷 캐시)을 백업했습니다.\n{out}\n\n"
                                   "다른 PC에서 '사전 복원'으로 불러오세요.")
        except Exception as e:
            QMessageBox.warning(self, "사전 백업", f"실패: {e}")

    def _action_restore_dict(self, checked: bool = False):
        """260615-15: 사전 복원 — 백업 zip 의 dict.db + dict_images/ 로 교체(기존은 .bak)."""
        from PyQt6.QtWidgets import QFileDialog
        import zipfile, shutil
        from viewer.study.dict_store import default_db_path
        from viewer.study.image_fetch import dict_images_dir
        fn, _ = QFileDialog.getOpenFileName(
            self, "사전 백업 파일 선택", "", "ZIP (*.zip)")
        if not fn:
            return
        if QMessageBox.question(
                self, "사전 복원",
                "현재 사전(용어·그림·인터넷 캐시)을 백업 내용으로 교체할까요?\n"
                "(기존 dict.db 는 dict.db.bak 으로 보관)") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            if getattr(self, "_dict_store", None) is not None:
                self._dict_store.close(); self._dict_store = None
        except Exception:
            pass
        try:
            dbp = default_db_path()
            imgs = dict_images_dir()
            if dbp.exists():
                shutil.copyfile(str(dbp), str(dbp) + ".bak")
            with zipfile.ZipFile(fn, "r") as z:
                names = z.namelist()
                if "dict.db" in names:
                    with z.open("dict.db") as src, open(dbp, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                for nm in names:
                    if nm.startswith("dict_images/") and not nm.endswith("/"):
                        target = imgs / Path(nm).name
                        with z.open(nm) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
            self._spot_terms_cache = None
            self._refresh_study_panel(self.main_view.current_page())
            QMessageBox.information(self, "사전 복원",
                                   "사전을 복원했습니다. (기존 dict.db → dict.db.bak)")
        except Exception as e:
            QMessageBox.warning(self, "사전 복원", f"실패: {e}")

    def _action_online_enrich(self, checked: bool = False):
        """260615-15: 인터넷 사전 보강(이어하기) — 재OCR 없이 현재 PDF 단어를 온라인 조회·캐시.
        중간에 끊겨도 online_fetched 로 이미 받은 단어는 건너뜀."""
        if not self._study_pdf or not Path(self._study_pdf).exists():
            QMessageBox.information(self, "인터넷 사전 보강", "먼저 단어장이 있는 PDF 를 여세요.")
            return
        from viewer.study.study_store import file_key_for
        store = self._study_get_store()
        if store.vocab_count(file_key_for(self._study_pdf)) == 0:
            QMessageBox.information(self, "인터넷 사전 보강",
                                   "이 PDF 의 단어장이 없습니다. 먼저 [단어장 생성].")
            return
        # 옵션이 꺼져 있어도 이 동작은 명시적이므로 강제로 켜서 조회
        op = {"online_dict_enabled": True,
              "urimalsaem_key": self._prefs.get("urimalsaem_key", ""),
              "stdict_key": self._prefs.get("stdict_key", ""),
              "onterm_key": self._prefs.get("onterm_key", "")}
        path = Path(self._study_pdf)
        self.study_panel.set_building(True)
        self.progress.setVisible(True); self.progress.setRange(0, 0)
        worker = StudyBuildWorker(path, lang=self._detect_study_lang(path),
                                  online_prefs=op, online_only=True)
        self._study_worker = worker

        def on_prog(done, total, m):
            if total:
                self.progress.setRange(0, total); self.progress.setValue(done)
            self.status.showMessage(m)

        def on_done(summary):
            self.study_panel.set_building(False)
            self.progress.setVisible(False)
            if summary.get("error"):
                QMessageBox.warning(self, "인터넷 사전 보강", f"실패: {summary['error']}")
                return
            self._spot_terms_cache = None
            self._refresh_study_panel(self.main_view.current_page())
            self.status.showMessage(
                f"인터넷 사전 보강 완료: {summary.get('online', 0)}개 추가", 6000)

        worker.progress.connect(on_prog)
        worker.finished.connect(on_done)
        worker.error.connect(lambda e: self.status.showMessage(f"인터넷 사전 보강 오류: {e}", 5000))
        run_in_thread(worker, self._study_threads)

    def _action_export_dict(self, checked: bool = False):
        """260611-106(P7): 사전(사용자/기본) → TBX·CSV 내보내기(상호운용)."""
        from PyQt6.QtWidgets import QFileDialog, QInputDialog
        try:
            dic = self._study_get_dict()
            srcs = dic.list_sources()
        except Exception as e:
            QMessageBox.warning(self, "사전 내보내기", f"사전 열기 실패: {e}")
            return
        if not srcs:
            QMessageBox.information(self, "사전 내보내기", "내보낼 사전이 없습니다.")
            return
        # 출처 선택(전체 + 개별)
        labels = ["전체"] + [f"{s.get('name', s['source_id'])} ({s.get('n_entries', 0)})"
                             for s in srcs]
        pick, ok = QInputDialog.getItem(self, "내보낼 사전", "출처:", labels, 0, False)
        if not ok:
            return
        source_id = None if pick == "전체" else srcs[labels.index(pick) - 1]["source_id"]
        fmt, ok = QInputDialog.getItem(
            self, "형식", "내보내기 형식:",
            ["TBX (ISO 30042)", "CSV (엑셀)"], 0, False)
        if not ok:
            return
        is_tbx = fmt.startswith("TBX")
        ext = "tbx" if is_tbx else "csv"
        default = str(Path(self._study_pdf).with_suffix("")) + f"_용어사전.{ext}" \
            if self._study_pdf else f"용어사전.{ext}"
        out, _ = QFileDialog.getSaveFileName(
            self, "사전 내보내기", default,
            ("TBX (*.tbx)" if is_tbx else "CSV (*.csv)"))
        if not out:
            return
        try:
            from viewer.study import dict_export
            n = (dict_export.export_tbx(dic, out, source_id=source_id) if is_tbx
                 else dict_export.export_csv(dic, out, source_id=source_id))
            QMessageBox.information(self, "사전 내보내기",
                                   f"{n}개 항목을 내보냈습니다.\n{out}")
            self.status.showMessage(f"사전 내보내기 완료: {Path(out).name} ({n}개)", 4000)
        except Exception as e:
            QMessageBox.warning(self, "사전 내보내기", f"실패: {e}")

    def _action_build_study(self, checked: bool = False, also_bookmarks: bool = False):
        """현재 PDF 를 OCR·어휘 분석해 study.db 생성 (백그라운드).
        also_bookmarks=True 면 같은 OCR 결과(study.db)를 재사용해 책갈피까지 동시 생성."""
        if not self._study_pdf or not Path(self._study_pdf).exists():
            QMessageBox.information(self, "단어장", "먼저 PDF 를 여세요.")
            return
        path = Path(self._study_pdf)
        lang = self._detect_study_lang(path)
        what = "단어장·책갈피 동시 생성" if also_bookmarks else "단어장 생성"
        extra = ("\n(OCR 1회로 단어장과 책갈피를 함께 만듭니다 — 따로 만드는 것보다 빠릅니다.)"
                 if also_bookmarks else "")
        # 260615-6: ① 이미 단어장이 있으면 '다시 만들기' 를 묻고, 예 → 기존 캐시 삭제 후 재생성
        from viewer.study.study_store import file_key_for
        store = self._study_get_store()
        fkey = file_key_for(path)
        already = store.vocab_count(fkey) > 0 or len(store.done_pages(fkey)) > 0
        if already:
            msg = (f"'{path.name}' 의 단어장이 이미 있습니다.\n"
                   f"기존 내용을 삭제하고 다시 만들까요?\n(감지 언어: {lang}){extra}")
            if QMessageBox.question(self, what + " — 다시 만들기", msg) \
                    != QMessageBox.StandardButton.Yes:
                return
            store.clear_file(fkey)        # 재생성 위해 기존 OCR·어휘 캐시 삭제
        else:
            msg = (f"'{path.name}' 을(를) OCR·분석합니다.\n"
                   f"감지 언어: {lang}.  분량에 따라 수 분 걸릴 수 있습니다.{extra}\n계속할까요?")
            if QMessageBox.question(self, what, msg) != QMessageBox.StandardButton.Yes:
                return
        self.study_panel.set_building(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)        # busy until first progress
        # 260615-14: 인터넷 사전 포함 옵션이면 빌드 시 각 단어를 온라인 조회·캐시
        online_prefs = {k: self._prefs.get(k) for k in
                        ("online_dict_enabled", "urimalsaem_key", "stdict_key",
                         "onterm_key")}
        worker = StudyBuildWorker(path, lang=lang, online_prefs=online_prefs)
        self._study_worker = worker

        def on_prog(done, total, m):
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(done)
            self.status.showMessage(f"{what}: {m} ({done}/{total})")

        def on_done(summary):
            self.study_panel.set_building(False)
            self.progress.setVisible(False)
            if summary.get("error"):
                QMessageBox.warning(self, "단어장", f"실패: {summary['error']}")
                self.status.showMessage("단어장 생성 실패", 4000)
                return
            v = (summary.get("vocab") or {}).get("vocab", 0)
            nb = 0
            if also_bookmarks:
                nb = self._build_bookmarks_from_study(path)   # 재OCR 없이 책갈피
            self.search_tabs.setCurrentWidget(self.study_panel)
            self._refresh_study_panel(self.main_view.current_page())
            tail = f", 책갈피 {nb}개" if also_bookmarks else ""
            on = summary.get("online") or 0
            on_tail = f", 인터넷 사전 {on}개" if on else ""
            self.status.showMessage(
                f"{what} 완료: {summary.get('done')}p, 어휘 {v}{tail}{on_tail}", 6000)

        worker.progress.connect(on_prog)
        worker.finished.connect(on_done)
        worker.error.connect(lambda e: self.status.showMessage(f"단어장 오류: {e}", 5000))
        run_in_thread(worker, self._study_threads)

    def _build_bookmarks_from_study(self, path) -> int:
        """260606-11(시간단축): 방금 만든 study.db 의 OCR 단어좌표를 재사용해
        책갈피(헤딩)를 추출 → 책갈피 트리에 추가(재OCR 없음). 추가 개수 반환."""
        try:
            import fitz
            from viewer.study.study_store import file_key_for
            from viewer.study.ocr_headings import extract_headings_from_store
            store = self._study_get_store()
            fk = file_key_for(path)
            doc = fitz.open(str(path))
            try:
                total = doc.page_count
            finally:
                doc.close()
            bms = extract_headings_from_store(store, fk, total, use_font_auto=False)
            for b in bms:
                self.bookmark_tree.add_bookmark(str(path), b.page, b.title)
            if bms:
                self.status.showMessage(
                    f"책갈피 {len(bms)}개 추가됨 — 책갈피창 편집(✏)에서 저장(💾)하면 PDF에 반영", 7000)
            return len(bms)
        except Exception:
            return 0

    # ===== 전역 매치 < > 순회 (v1.6.2) ==================================
    def _global_next_match(self):
        """검색바 ▶: 현재 파일 매치가 남았으면 다음으로, 아니면 다음 파일 첫 매치."""
        mv = self.main_view
        if mv._matches:
            total = sum(len(h.rects) for h in mv._matches)
            if total > 0 and mv._current_match < total - 1:
                mv.go_next_match()
                return
        self._jump_search_file(+1)

    def _global_prev_match(self):
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

    def action_print(self):
        cur = self.main_view.current_file()
        is_pdf = bool(cur and str(cur).lower().endswith(".pdf"))
        pc = (self.main_view._doc.page_count
              if (is_pdf and self.main_view._doc is not None) else 0)
        cur_page = self.main_view.current_page()
        n_thumb = len(self.page_thumbs.list.selectedItems())
        n_shot = len(self.shot_strip.list.selectedItems())
        if not is_pdf and self.shot_strip.list.count() == 0:
            QMessageBox.information(self, "인쇄", "인쇄할 문서가 없습니다.")
            return
        from viewer.widgets.print_dialog import PrintScopeDialog
        dlg = PrintScopeDialog(max(pc, 1), cur_page, n_thumb, n_shot, self,
                               preset_api=self._merge_preset_api(),
                               sample=(str(cur) if is_pdf else None))
        if not dlg.exec():
            return
        spec = dlg.result_spec()
        to_pdf = dlg.to_pdf()
        if spec["mode"] == "shot":
            shots = self._shot_paths_to_print()
            if to_pdf:
                dst = self._save_pdf_dialog("스크린샷.pdf")
                if dst and self._export_images_pdf(shots, dst):
                    self.status.showMessage(f"PDF 저장: {dst}", 4000)
            else:
                self._print_images(shots)
            return
        if not is_pdf:
            QMessageBox.information(self, "인쇄", "현재 메인 문서가 PDF 가 아닙니다.")
            return
        if spec["mode"] == "all":
            pages = list(range(pc))
        elif spec["mode"] == "current":
            pages = [cur_page]
        elif spec["mode"] == "range":
            pages = list(range(spec["from"], spec["to"] + 1))
        else:  # thumb
            pages = sorted({self.page_thumbs.list.row(it)
                            for it in self.page_thumbs.list.selectedItems()})
        pages = [p for p in pages if 0 <= p < pc]
        if not pages:
            QMessageBox.information(self, "인쇄", "인쇄할 페이지가 없습니다.")
            return
        if dlg.nup_enabled():               # 260611-37/54: 다단 인쇄(표지만, 목차 제외)
            out_nup = self._build_nup_pdf(cur, pages, dlg.nup_settings())
            if not out_nup:
                return
            if to_pdf:
                dst = self._save_pdf_dialog(Path(cur).stem + "_다단.pdf")
                if dst and self._copy_pdf(out_nup, dst):
                    self.status.showMessage(f"PDF 저장: {dst}", 4000)
                return
            import fitz
            nd = fitz.open(out_nup); npages = list(range(nd.page_count)); nd.close()
            self._print_pdf_pages(out_nup, npages)
            return
        if to_pdf:
            dst = self._save_pdf_dialog(Path(cur).stem + "_인쇄.pdf")
            if dst and self._export_pages_pdf(cur, pages, dst):
                self.status.showMessage(f"PDF 저장: {dst}", 4000)
            return
        self._print_pdf_pages(cur, pages)

    def _save_pdf_dialog(self, default_name):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "PDF로 저장", default_name, "PDF 파일 (*.pdf)")
        if path and not path.lower().endswith(".pdf"):
            path += ".pdf"
        return path

    def _copy_pdf(self, src, dst):
        import shutil
        try:
            shutil.copyfile(src, dst); return True
        except Exception as e:
            QMessageBox.warning(self, "PDF로 인쇄", f"저장 실패: {e}")
            return False

    def _export_pages_pdf(self, src, pages, out_path):
        import fitz
        self.status.showMessage("PDF 생성 중…")           # 260617-6
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        QApplication.processEvents()
        try:
            sd = fitz.open(src); td = fitz.open()
            for p in pages:
                td.insert_pdf(sd, from_page=p, to_page=p)
            sd.close(); td.save(out_path); td.close()
            return True
        except Exception as e:
            QMessageBox.warning(self, "PDF로 인쇄", f"저장 실패: {e}")
            return False
        finally:
            QApplication.restoreOverrideCursor()

    def _export_images_pdf(self, paths, out_path):
        import fitz
        d = fitz.open()
        for p in (paths or []):
            try:
                pix = fitz.Pixmap(p)
                pg = d.new_page(width=pix.width, height=pix.height)
                pg.insert_image(fitz.Rect(0, 0, pix.width, pix.height), filename=p)
            except Exception:
                continue
        ok = d.page_count > 0
        if ok:
            try:
                d.save(out_path)
            except Exception as e:
                ok = False; QMessageBox.warning(self, "PDF로 인쇄", f"저장 실패: {e}")
        d.close()
        if not ok:
            QMessageBox.information(self, "PDF로 인쇄", "내보낼 이미지가 없습니다.")
        return ok

    def _build_nup_pdf(self, cur, pages, settings):
        """260611-37/54: 선택 페이지를 다단(N-up)으로 구성(목차 제외). 출력 PDF 경로 반환(실패 None)."""
        import fitz, tempfile
        from viewer.twoup import build_twoup
        tmpdir = Path(tempfile.mkdtemp(prefix="polypdf_nupprint_"))
        src_sub = str(tmpdir / "sub.pdf"); out_nup = str(tmpdir / "nup.pdf")
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        # 260617-6: 진행 표시(하단 상태바) — 동기 작업 중 멈춘 듯 보이지 않게 processEvents
        self.status.showMessage("다단 PDF 생성 중…")
        QApplication.processEvents()

        def _tick(*a, **k):
            msg = next((str(x) for x in a if isinstance(x, str)), "")
            self.status.showMessage(f"다단 PDF 생성 중… {msg}".strip())
            QApplication.processEvents()
            return True                       # progress 가 falsy면 취소로 간주되므로
        try:
            sd = fitz.open(cur); td = fitz.open()
            for p in pages:
                td.insert_pdf(sd, from_page=p, to_page=p)
            sd.close(); td.save(src_sub); td.close()
            build_twoup([{"type": "pdf", "path": src_sub, "name": Path(cur).stem}],
                        settings, out_nup, log=_tick, progress=_tick)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "인쇄", f"다단 구성 실패: {e}")
            return None
        QApplication.restoreOverrideCursor()
        import fitz as _f
        nd = _f.open(out_nup); n = nd.page_count; nd.close()
        if not n:
            QMessageBox.information(self, "인쇄", "구성된 페이지가 없습니다.")
            return None
        return out_nup

    def _shot_paths_to_print(self) -> list:
        metas = self.shot_strip.all_meta()
        sel = [self.shot_strip.list.row(it)
               for it in self.shot_strip.list.selectedItems()]
        rows = sel if sel else list(range(len(metas)))
        return [metas[r].get("path") for r in rows
                if 0 <= r < len(metas) and metas[r].get("path")]

    def _print_render(self, count: int, draw_fn) -> None:
        """QPrinter 설정 + 페이지별 draw_fn(painter, target_rect, index) 호출."""
        from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
        from PyQt6.QtGui import QPainter
        if count <= 0:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted:
            return
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "인쇄", "프린터를 열 수 없습니다.")
            return
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BusyCursor))
        try:
            for i in range(count):
                if i > 0:
                    printer.newPage()
                draw_fn(painter, painter.viewport(), i)
                if i % 3 == 0:
                    self.status.showMessage(f"인쇄 중 {i+1}/{count}")
                    QApplication.processEvents()
            painter.end()
            self.status.showMessage(f"인쇄 완료: {count} 페이지", 4000)
        finally:
            QApplication.restoreOverrideCursor()

    def _draw_image_fit(self, painter, target, img) -> None:
        from PyQt6.QtCore import QRect
        if img.isNull():
            return
        scaled = img.scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        x = target.x() + (target.width() - scaled.width()) // 2
        y = target.y() + (target.height() - scaled.height()) // 2
        painter.drawImage(QRect(x, y, scaled.width(), scaled.height()), scaled)

    def _thumb_doc_path(self):
        """260616-21: 썸네일이 표시 중인 PDF 경로(없으면 활성 뷰 파일)."""
        p = getattr(self.page_thumbs, "_doc_path", None)
        if not p:
            cur = self.main_view.current_file() if self.main_view else None
            p = cur if (cur and str(cur).lower().endswith(".pdf")) else None
        return p

    def _on_thumb_print_pages(self, pages):
        """260616-21: 썸네일 다중선택 → 선택 페이지 인쇄."""
        cur = self._thumb_doc_path()
        pages = sorted({int(p) for p in (pages or []) if p is not None})
        if not cur or not pages:
            return
        self._print_pdf_pages(cur, pages)

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

    def _print_pdf_pages(self, pdf_path, pages: list) -> None:
        # 260618-1: 현재 문서 인쇄 권한 없으면 차단
        if not getattr(self, "_perm_can_print", True):
            self.status.showMessage("이 문서는 인쇄 권한이 없습니다.", 3000)
            return
        import fitz
        from PyQt6.QtGui import QImage
        doc = fitz.open(pdf_path)
        # 260615-3: ① 인쇄에도 꾸밈(선·도형·글)+하이퍼링크 포함
        try:
            self._bake_drawings_into_doc(doc, self._decorations_norm_for(pdf_path))
            self._bake_hyperlinks_into_doc(doc, pdf_path)
        except Exception:
            pass

        def draw(painter, target, i):
            page = doc.load_page(pages[i])
            zoom = 200 / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.width * 3,
                         QImage.Format.Format_RGB888).copy()
            self._draw_image_fit(painter, target, img)
        try:
            self._print_render(len(pages), draw)
        finally:
            doc.close()

    def _print_images(self, paths: list) -> None:
        from PyQt6.QtGui import QImage
        paths = [p for p in paths if p and Path(p).exists()]
        if not paths:
            QMessageBox.information(self, "인쇄", "인쇄할 스크린샷이 없습니다.")
            return

        def draw(painter, target, i):
            self._draw_image_fit(painter, target, QImage(str(paths[i])))
        self._print_render(len(paths), draw)

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
        self._prefs.setdefault("presentation_split", False)       # 260609-6
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
        self._prefs.setdefault("urimalsaem_key", "")
        self._prefs.setdefault("stdict_key", "")
        self._prefs.setdefault("onterm_key", "")
        self._prefs.setdefault("law_oc", "")
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

    # ===== 설정 (v1.5.1) ===============================================
    def action_open_settings(self):
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
            # 260609-6: 발표 상하 2분할·겹침%
            "presentation_split": bool(prefs.get(
                "presentation_split", old.get("presentation_split", False))),
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
            "urimalsaem_key": str(prefs.get("urimalsaem_key",
                                            old.get("urimalsaem_key", ""))),
            "stdict_key": str(prefs.get("stdict_key", old.get("stdict_key", ""))),
            "onterm_key": str(prefs.get("onterm_key", old.get("onterm_key", ""))),
            "law_oc": str(prefs.get("law_oc", old.get("law_oc", ""))),
            # 260618-11: 업데이트(GitHub Releases)
            "update_repo": str(prefs.get("update_repo", old.get("update_repo", ""))),
            "auto_check_update": bool(prefs.get("auto_check_update",
                                                old.get("auto_check_update", True))),
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
        # 260615-4: ⑩ 폴더 즐겨찾기에 파일이 기록돼 있으면 그 파일 첫 페이지로
        f = fav.get("file")
        if f and Path(f).exists():
            self._on_bookmark_activated(str(f), 0)
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

        qs = QSettings()
        qs.setValue("geometry", self.saveGeometry())
        qs.setValue("splitter", self.splitter.saveState())
        qs.setValue("right_splitter", self.right_splitter.saveState())  # v1.6.2

        # 260611-91: 설정 초기화 재시작 중이면 옛 메모리 상태로 settings.json 을 덮어쓰지 않음
        if not getattr(self, "_skip_save_on_close", False):
            self._save_settings_now()
        super().closeEvent(event)

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
    def _check_for_updates(self, manual: bool = False):
        """최신 릴리스를 백그라운드로 확인(결과는 _on_update_result). manual=True 면
        저장소 미설정 시 입력받고, 최신/실패도 알림."""
        from viewer import updater
        # 260618-11: 설정값이 있으면 우선, 없으면 기본 저장소(고정) — 입력 불필요.
        repo = (self._prefs.get("update_repo") or "").strip() or updater.DEFAULT_REPO
        if not updater.valid_repo(repo):
            if not manual:
                return
            from PyQt6.QtWidgets import QInputDialog
            txt, ok = QInputDialog.getText(
                self, "업데이트 저장소 설정",
                "GitHub 저장소를 'OWNER/REPO' 형식으로 입력하세요:", text=repo)
            if not ok or not updater.valid_repo((txt or "").strip()):
                return
            repo = txt.strip()
            self._prefs["update_repo"] = repo
            try:
                self._save_settings_now()
            except Exception:
                pass
        if manual:
            self.status.showMessage("업데이트 확인 중…", 3000)
        import threading
        sig = self._update_sig

        def work():
            info = updater.check_latest(repo)
            try:
                sig.done.emit(info, bool(manual))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _on_update_result(self, info, manual):
        from viewer import updater
        cur = updater.current_version()
        if not info:
            if manual:
                QMessageBox.information(
                    self, "업데이트",
                    "업데이트 정보를 가져오지 못했습니다.\n인터넷 연결과 저장소 설정을 확인하세요.")
            return
        latest = info.get("version") or ""
        if not updater.is_newer(latest, cur):
            if manual:
                QMessageBox.information(self, "업데이트", f"현재 최신 버전입니다. (v{cur})")
            return
        notes = (info.get("notes") or "").strip()
        if len(notes) > 1200:
            notes = notes[:1200] + " …"
        if not updater.is_frozen():
            QMessageBox.information(
                self, "업데이트",
                f"새 버전 v{latest} 이 있습니다(현재 v{cur}).\n"
                f"개발(소스) 실행 중에는 자동 교체가 적용되지 않습니다.\n{info.get('html_url','')}")
            return
        if not info.get("asset_url"):
            QMessageBox.information(
                self, "업데이트",
                f"새 버전 v{latest} 이 있으나 배포 zip 자산을 찾지 못했습니다.\n{info.get('html_url','')}")
            return
        msg = (f"새 버전이 있습니다.\n\n현재: v{cur}\n최신: v{latest}\n\n"
               + (notes + "\n\n" if notes else "") + "지금 다운로드해 업데이트할까요?")
        ret = QMessageBox.question(
            self, "업데이트", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if ret == QMessageBox.StandardButton.Yes:
            self._download_and_apply(info)

    def _download_and_apply(self, info):
        from viewer import updater
        from PyQt6.QtWidgets import QProgressDialog
        dlg = QProgressDialog("업데이트 다운로드 중…", "취소", 0, 100, self)
        dlg.setWindowTitle("업데이트")
        dlg.setAutoClose(False)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)

        def prog(done, total):
            if dlg.wasCanceled():
                return False
            if total > 0:
                dlg.setValue(int(done * 100 / total))
                dlg.setLabelText(
                    f"업데이트 다운로드 중… {done // 1048576}/{total // 1048576} MB")
            QApplication.processEvents()
            return True

        path = updater.download_asset(info["asset_url"], progress=prog)
        dlg.close()
        if not path:
            QMessageBox.information(self, "업데이트", "다운로드가 취소되었거나 실패했습니다.")
            return
        if updater.apply_update(path):
            QMessageBox.information(
                self, "업데이트",
                "다운로드 완료. 프로그램을 종료하고 업데이트를 적용합니다.\n"
                "잠시 후 자동으로 다시 시작됩니다.")
            self.close()        # 종료 → 도우미가 파일 교체 후 재실행
        else:
            QMessageBox.warning(self, "업데이트", "업데이트 적용에 실패했습니다.")

    def _open_components_installer(self):
        """260618-12: 녹화(ffmpeg)·OCR(Tesseract) 구성요소를 릴리스에서 설치 폴더로 받기."""
        from viewer import components
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                      QPushButton, QProgressBar)
        repo = (self._prefs.get("update_repo") or "").strip() or components.DEFAULT_REPO
        dlg = QDialog(self)
        dlg.setWindowTitle("구성요소 설치 (녹화·OCR)")
        dlg.resize(460, 200)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("필요한 기능의 구성요소를 설치 폴더에 내려받습니다.\n"
                           "(녹화=ffmpeg, OCR=Tesseract · 재시작 불필요)"))
        bar = QProgressBar(); bar.setRange(0, 100); bar.setValue(0); bar.setVisible(False)

        rows = {}

        def make_row(key, title, installed_fn, install_fn):
            row = QHBoxLayout()
            lab = QLabel(title)
            st = QLabel()
            btn = QPushButton()
            row.addWidget(lab, 1)
            row.addWidget(st)
            row.addWidget(btn)
            v.addLayout(row)
            rows[key] = (st, btn)

            def refresh():
                ok = installed_fn()
                st.setText("설치됨 ✓" if ok else "미설치")
                st.setStyleSheet("color:#2a7;" if ok else "color:#c33;")
                btn.setText("재설치" if ok else "다운로드")

            def do():
                bar.setVisible(True); bar.setValue(0)
                for _s, b in rows.values():
                    b.setEnabled(False)

                def prog(done, total):
                    if total > 0:
                        bar.setValue(int(done * 100 / total))
                    QApplication.processEvents()
                    return True
                ok, info = install_fn(repo, prog)
                bar.setVisible(False)
                for _s, b in rows.values():
                    b.setEnabled(True)
                if ok:
                    QMessageBox.information(dlg, "구성요소 설치", f"{title} 설치 완료.")
                else:
                    QMessageBox.warning(dlg, "구성요소 설치", f"{title} 설치 실패:\n{info}")
                refresh()

            btn.clicked.connect(do)
            refresh()

        make_row("ffmpeg", "녹화 (ffmpeg)",
                 components.ffmpeg_installed, components.install_ffmpeg)
        make_row("tess", "OCR (Tesseract)",
                 components.tesseract_installed, components.install_tesseract)
        v.addWidget(bar)
        v.addStretch(1)
        close = QPushButton("닫기"); close.clicked.connect(dlg.accept)
        h = QHBoxLayout(); h.addStretch(1); h.addWidget(close)
        v.addLayout(h)
        dlg.exec()

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
