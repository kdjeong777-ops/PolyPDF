"""우측 '검색·단어' 탭의 단어학습 패널 (260603-수정 반영).

- 단어 볼드 표시, 좌측 색 아이콘만(난이도 텍스트 제거), '뜻:' 접두 제거
- 한글뜻/영어뜻/예시 표시 토글, 정렬(문장순서/가나다·ABC/빈도)
- 단어 음성 읽기(TTS) + 페이지 자동 읽기 옵션
- 선택(클릭/상하 이동키)하면 메인 뷰어에 자동 강조(wordSelected)
- 뜻·예시 편집(editRequested), Word 저장(exportRequested), 본문 강조 옵션(autoHighlightChanged)
"""
from __future__ import annotations

import re
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QEvent
from PyQt6.QtGui import QFont, QAction, QActionGroup
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton, QLabel,
    QTreeWidget, QTreeWidgetItem, QComboBox, QToolButton, QMenu,
    QStyledItemDelegate, QStyleOptionViewItem,
)


class _WrapDelegate(QStyledItemDelegate):
    """260615-11: 단어장 항목 텍스트를 창 폭에 맞춰 자동 줄바꿈 — '...' 생략 방지.
    기본 델리게이트는 한 줄로 생략(elide)하므로, 줄바꿈 그리기 + 줄바꿈 높이 계산을 직접 처리."""

    def _avail_width(self, option, index) -> tuple:
        """실제로 텍스트가 그려지는 폭 추정 — 컬럼폭에서 들여쓰기(깊이)·아이콘·여백 제외.
        반환: (텍스트가능폭, 컬럼폭)."""
        view = self.parent()
        try:
            col_w = view.columnWidth(index.column())
            if col_w <= 0:
                col_w = view.viewport().width()
        except Exception:
            col_w = max(120, int(option.rect.width()) or 240)
        depth = 0
        p = index.parent()
        while p.isValid():
            depth += 1
            p = p.parent()
        try:
            indent = view.indentation()
        except Exception:
            indent = 20
        deco = 0
        try:
            if not option.icon.isNull():
                deco = option.decorationSize.width() + 6
        except Exception:
            deco = 0
        avail = max(40, col_w - indent * (depth + 1) - deco - 10)
        return avail, col_w

    def sizeHint(self, option, index):
        from PyQt6.QtGui import QFontMetrics
        from PyQt6.QtCore import QSize, QRect
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text or ""
        avail, col_w = self._avail_width(option, index)
        fm = QFontMetrics(opt.font)
        r = fm.boundingRect(QRect(0, 0, avail, 1000000),
                            int(Qt.TextFlag.TextWordWrap), text)
        ih = int(opt.decorationSize.height()) if not opt.icon.isNull() else 0
        return QSize(col_w, max(ih, r.height()) + 8)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.features |= QStyleOptionViewItem.ViewItemFeature.WrapText
        opt.textElideMode = Qt.TextElideMode.ElideNone
        super().paint(painter, opt, index)

class _StayOpenMenu(QMenu):
    """260615-23: 체크형 항목을 클릭해도 메뉴가 닫히지 않고 토글 — 여러 출처를
    한 번에 연속 선택/해제할 수 있게. (체크 아닌 항목/하위메뉴는 기본 동작)"""

    def mouseReleaseEvent(self, e):
        act = self.activeAction()
        if act is not None and act.isEnabled() and act.isCheckable():
            act.setChecked(not act.isChecked())   # toggled 시그널 발신 → 핸들러 동작
            e.accept()
            return
        super().mouseReleaseEvent(e)


def _clean_markup(s) -> str:
    """260615-16: 뜻/예시의 HTML 엔티티(&#44; 등)·태그(<strong> 등) 제거 — 화면 정리.
    (이미 캐시된 인터넷 사전 정의도 표시 시점에 깨끗하게)"""
    import html as _html
    t = _html.unescape(str(s or ""))
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", t).strip()


_LEVELS = ("초급", "중급", "고급", "전문용어")        # 260611-103(P4): 전문용어 등급
_BADGE = {"초급": "🟢", "중급": "🟡", "고급": "🔴", "미정": "⚪", "전문용어": "📘"}
_HANGUL = re.compile(r"[가-힣]")
SORT_ORDER = "문장 순서"
SORT_ALPHA = "가나다·ABC"
SORT_FREQ = "빈도순"
READ_ONCE = "1회"
READ_REPEAT = "연속"
READ_ALL_ONCE = "전체 1회"
READ_ALL_REPEAT = "전체 연속"
FILTER_ALL = "전체단어"
FILTER_SELECTED = "선택단어"
FILTER_ORIG = "초기"
RATES = [("느림", -4), ("보통", 0), ("빠름", 4), ("매우 빠름", 8)]
READ_MODES = [READ_ONCE, READ_REPEAT, READ_ALL_ONCE, READ_ALL_REPEAT]


class StudyPanel(QWidget):
    buildRequested = pyqtSignal()
    wordSelected = pyqtSignal(str, int)      # (lemma, page) — 선택/이동 시 자동 강조
    speakRequested = pyqtSignal(str, str)    # (text, lang)
    editRequested = pyqtSignal(str, str)     # (lemma, lang)
    addTermRequested = pyqtSignal()          # 260611-104(P5): ＋ 새 용어 등록
    exportRequested = pyqtSignal()
    mp3Requested = pyqtSignal()              # 재생내용 mp3 저장
    autoHighlightChanged = pyqtSignal(bool)  # 본문 전체 강조 옵션
    playToggled = pyqtSignal(bool)           # ▶/■ 단어장 자동읽기 시작/정지
    wordFilterChanged = pyqtSignal()         # 표시 필터(전체/선택/날짜/초기) 변경
    sourceToggled = pyqtSignal(str, bool)    # 260611-102(P2): 사전 출처 on/off
    markSelectedRequested = pyqtSignal()     # ▲ 선택단어 저장
    deleteWordRequested = pyqtSignal()       # ▼ 리스트에서 삭제
    speedChanged = pyqtSignal(int)           # 빠르기(본화면·단어장 공유)
    voiceChanged = pyqtSignal(str)           # 성우(공유)
    crossPageRequested = pyqtSignal(int)     # ↑ 첫 항목/↓ 마지막 항목 → 페이지 넘김(±1)

    DATA_LEMMA = Qt.ItemDataRole.UserRole + 0
    DATA_PAGE = Qt.ItemDataRole.UserRole + 1
    DATA_LANG = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._page = 0
        self._expanded = True        # 260606: 펼치기 기본
        self._programmatic = False   # 프로그램적 선택(호버/읽기) — wordSelected 억제
        self._playing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(3)

        # 260618-2: 상단 헤더 — 제목(좌) + 동작 버튼 5개(우상단)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("단어장"))
        hdr.addStretch(1)
        self.btn_add = QPushButton("＋")
        self.btn_add.setToolTip("새 용어 등록(사용자 사전)")
        self.btn_add.clicked.connect(self.addTermRequested.emit)
        from PyQt6.QtCore import QSize as _QSize
        self.btn_add.setFixedSize(_QSize(26, 26))
        self.btn_add.setStyleSheet("QPushButton{padding:0px;font-size:15px;font-weight:bold;}")
        hdr.addWidget(self.btn_add)
        self.btn_edit = QPushButton("✎")
        self.btn_edit.setToolTip("선택 단어/용어 편집(한글뜻·영어뜻·예시·참고문헌, 삭제)")
        self.btn_edit.clicked.connect(self._edit_current)
        hdr.addWidget(self.btn_edit)
        self.btn_word = QPushButton("Word")
        self.btn_word.setToolTip("전체 내용을 Word(.docx)로 저장")
        self.btn_word.clicked.connect(self.exportRequested.emit)
        hdr.addWidget(self.btn_word)
        self.btn_mp3 = QPushButton("mp3")
        self.btn_mp3.setToolTip("재생내용을 페이지별 mp3로 저장(폴더)")
        self.btn_mp3.clicked.connect(self.mp3Requested.emit)
        hdr.addWidget(self.btn_mp3)
        self.btn_build = QPushButton("단어장 생성")
        self.btn_build.setToolTip("이 PDF 를 OCR·분석해 단어장을 만듭니다 (1회).")
        self.btn_build.clicked.connect(self.buildRequested.emit)
        hdr.addWidget(self.btn_build)
        # 260611-66: 동작 버튼을 메인 툴바 버튼과 동일 크기(높이 26·아이콘 24)로 통일
        try:
            from PyQt6.QtGui import QIcon
            from PyQt6.QtCore import QSize
            from viewer.resources_path import resource_path
            for b, ic in ((self.btn_edit, "icon_edit.png"),
                          (self.btn_word, "icon_word.png"),
                          (self.btn_mp3, "icon_mp3.png"),
                          (self.btn_build, "icon_vocab_add.png")):
                b.setText("")
                b.setIcon(QIcon(resource_path(ic)))
                b.setIconSize(QSize(22, 22))           # 26 정사각 안에 들어가는 아이콘
                b.setFixedSize(QSize(26, 26))          # 메인 툴바 높이(26)와 동일 + 정사각형
                b.setStyleSheet("QPushButton{padding:0px;}")
        except Exception:
            pass
        root.addLayout(hdr)

        # 260618-2: 컨트롤(체크박스·버튼)을 폭에 따라 흐르듯 줄바꿈(FlowLayout)
        from viewer.widgets.flow_layout import FlowLayout
        self._ctrl_widget = QWidget()
        flow = FlowLayout(self._ctrl_widget, spacing=4, center=False)

        # 종류
        flow.addWidget(QLabel("종류"))
        self._chk: dict[str, QCheckBox] = {}
        _default_on = {"초급": False, "중급": True, "고급": True,
                       "전문용어": True}                          # 초급 기본 해제
        for lv in _LEVELS:
            cb = QCheckBox(lv)
            cb.setChecked(_default_on[lv])
            cb.stateChanged.connect(self._render)
            flow.addWidget(cb)
            self._chk[lv] = cb

        # 표시 토글 + 접기 + 출처 + 표시 필터 + 본문강조
        flow.addWidget(QLabel("표시"))
        self.chk_ko = QCheckBox("한글뜻"); self.chk_ko.setChecked(True)
        self.chk_en = QCheckBox("영어뜻"); self.chk_en.setChecked(True)
        self.chk_ex = QCheckBox("예시"); self.chk_ex.setChecked(True)
        self.chk_ref = QCheckBox("참고문헌")     # 260611-102(P2): 출처 표시/숨김
        self.chk_ref.setChecked(True)
        self.chk_ref.setToolTip("사전 뜻 끝에 출처(참고문헌)를 표시합니다.")
        self.chk_img = QCheckBox("그림")          # 260615-8(P10): 단어 그림 표시
        self.chk_img.setChecked(True)
        self.chk_img.setToolTip("사전에 그림이 있으면 단어 옆에 표시합니다.")
        for c in (self.chk_ko, self.chk_en, self.chk_ex, self.chk_ref, self.chk_img):
            c.stateChanged.connect(self._render)
            flow.addWidget(c)
        self.btn_expand = QPushButton("접기")     # 260606-2: 표시 오른쪽으로 이동
        self.btn_expand.setMaximumWidth(48)
        self.btn_expand.clicked.connect(self._toggle_expand)
        flow.addWidget(self.btn_expand)
        # 260611-102(P2): 사전 출처 선택(일반/○○지침/사용자 …) on/off
        self.btn_src = QToolButton()
        self.btn_src.setText("출처 ▾")
        self.btn_src.setToolTip("표시할 사전 출처를 켜고 끕니다(기본/사용자 용어집).")
        self.btn_src.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_src.setMenu(_StayOpenMenu(self.btn_src))   # 260615-23: 연속 토글
        flow.addWidget(self.btn_src)
        self.cmb_filter = QComboBox()        # 전체단어/선택단어/날짜/초기
        self.cmb_filter.setToolTip("표시할 단어 집합: 전체/선택단어/날짜별/초기")
        self._rebuild_filter([])
        self.cmb_filter.currentIndexChanged.connect(self._on_filter_changed)
        flow.addWidget(self.cmb_filter)
        self.chk_hl = QCheckBox("본문강조")
        self.chk_hl.setToolTip("이 페이지의 단어장 단어를 메인 뷰어에 옅게 강조합니다.")
        self.chk_hl.toggled.connect(self.autoHighlightChanged.emit)
        flow.addWidget(self.chk_hl)

        # 읽기 — ▶/■ 토글 + 재생구간 + 재생내용 + 선택시읽기
        flow.addWidget(QLabel("읽기"))
        self.btn_play = QToolButton()
        self.btn_play.setText("▶")
        self.btn_play.setToolTip("단어장 자동 읽기 시작/정지")
        self.btn_play.setStyleSheet("QToolButton{color:#1565c0;font-size:15px;font-weight:bold;}")
        self.btn_play.clicked.connect(self._on_play_clicked)
        flow.addWidget(self.btn_play)
        self._read_mode = READ_ALL_REPEAT     # 전체 연속 기본
        self.btn_readmode = self._make_readmode_button()
        self.btn_readmode.setText(self._read_mode + " ▾")
        flow.addWidget(self.btn_readmode)
        # 재생내용 풀다운(한글뜻/영어뜻/예시)
        self.btn_content = QToolButton()
        self.btn_content.setText("재생내용 ▾")
        self.btn_content.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        cm = QMenu(self.btn_content)
        self.act_play_ko = QAction("한글뜻", cm, checkable=True)
        self.act_play_en = QAction("영어뜻", cm, checkable=True)
        self.act_play_ex = QAction("예시", cm, checkable=True)
        for a in (self.act_play_ko, self.act_play_en, self.act_play_ex):
            cm.addAction(a)
        self.btn_content.setMenu(cm)
        flow.addWidget(self.btn_content)
        self.chk_speak_sel = QCheckBox("선택시읽기")
        self.chk_speak_sel.setChecked(True)
        self.chk_speak_sel.setToolTip("단어 선택(목록/본문)시 그 단어를 읽습니다.")
        flow.addWidget(self.chk_speak_sel)

        # 정렬 — '선택단어로 저장(▲)' 버튼 왼쪽으로(260618-2)
        flow.addWidget(QLabel("정렬"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems([SORT_ORDER, SORT_ALPHA, SORT_FREQ])
        self.sort_combo.currentIndexChanged.connect(self._render)
        flow.addWidget(self.sort_combo)
        self.btn_mark = QToolButton(); self.btn_mark.setText("▲")
        self.btn_mark.setToolTip("선택단어로 저장")
        self.btn_mark.clicked.connect(self.markSelectedRequested.emit)
        flow.addWidget(self.btn_mark)
        self.btn_del = QToolButton(); self.btn_del.setText("▼")
        self.btn_del.setToolTip("리스트에서 삭제(모든 페이지)")
        self.btn_del.clicked.connect(self.deleteWordRequested.emit)
        flow.addWidget(self.btn_del)

        root.addWidget(self._ctrl_widget)

        self.lbl_status = QLabel("단어장이 없습니다. [단어장 생성] 을 누르세요.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color:#666;")
        root.addWidget(self.lbl_status)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        # 260615-6: ② 뜻/예시가 한 줄을 넘으면 자동 줄바꿈(잘리지 않게)
        self.tree.setWordWrap(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.tree.setUniformRowHeights(False)
        self.tree.setItemDelegate(_WrapDelegate(self.tree))   # 260615-11: 자동 줄바꿈
        from PyQt6.QtCore import QSize as _QSz
        self.tree.setIconSize(_QSz(44, 44))    # 260615-8(P10): 단어 그림 썸네일 크기
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.tree.installEventFilter(self)     # ▲▼ 키 = 저장/삭제(플래시카드식 분류)
        root.addWidget(self.tree, 1)

        self._bold = QFont()
        self._bold.setBold(True)

    # --- 재생구간 메뉴(구간 | 빠르기 | 성우) — 빠르기/성우는 본화면과 공유 ---
    def _make_readmode_button(self) -> QToolButton:
        btn = QToolButton()
        btn.setText("재생구간 ▾")
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(btn)
        g = QActionGroup(menu); g.setExclusive(True)
        for label in READ_MODES:
            a = QAction(label, menu, checkable=True)
            a.setChecked(label == self._read_mode)
            a.triggered.connect(lambda _c, v=label: self._set_read_mode(v))
            g.addAction(a); menu.addAction(a)
        menu.addSeparator()
        rm = menu.addMenu("빠르기")
        gr = QActionGroup(rm); gr.setExclusive(True)
        for label, rate in RATES:
            a = QAction(label, rm, checkable=True); a.setChecked(rate == 0)
            a.triggered.connect(lambda _c, r=rate: self.speedChanged.emit(r))
            gr.addAction(a); rm.addAction(a)
        self._voice_menu = menu.addMenu("성우")
        self._voice_group = QActionGroup(self._voice_menu); self._voice_group.setExclusive(True)
        a0 = QAction("자동(언어별)", self._voice_menu, checkable=True); a0.setChecked(True)
        a0.triggered.connect(lambda: self.voiceChanged.emit(""))
        self._voice_group.addAction(a0); self._voice_menu.addAction(a0)
        btn.setMenu(menu)
        return btn

    def set_voices(self, names: list) -> None:
        """성우 목록 채움(빠르기/성우는 본화면과 공유)."""
        for n in names:
            a = QAction(n, self._voice_menu, checkable=True)
            a.triggered.connect(lambda _c, nm=n: self.voiceChanged.emit(nm))
            self._voice_group.addAction(a); self._voice_menu.addAction(a)

    def _set_read_mode(self, mode: str) -> None:
        self._read_mode = mode
        self.btn_readmode.setText(mode + " ▾")

    # --- 외부 API ----------------------------------------------------------
    def set_status(self, text: str) -> None:
        self.lbl_status.setText(text)

    def set_building(self, on: bool) -> None:
        self.btn_build.setEnabled(not on)
        self.btn_build.setText("⏳ 생성 중..." if on else "단어장 생성")

    def set_page(self, page: int) -> None:
        self._page = page

    def is_auto_read(self) -> bool:
        return self._playing

    def is_playing(self) -> bool:
        return self._playing

    def set_playing(self, on: bool) -> None:
        self._playing = bool(on)
        self.btn_play.setText("■" if on else "▶")
        self.btn_play.setStyleSheet(
            "QToolButton{color:%s;font-size:15px;font-weight:bold;}"
            % ("#c0392b" if on else "#1565c0"))

    def _on_play_clicked(self) -> None:
        self.set_playing(not self._playing)
        self.playToggled.emit(self._playing)

    def read_mode(self) -> str:
        return self._read_mode

    def read_continuous(self) -> bool:
        return self._read_mode in (READ_REPEAT, READ_ALL_REPEAT)

    def read_all_pages(self) -> bool:
        return self._read_mode in (READ_ALL_ONCE, READ_ALL_REPEAT)

    def is_speak_on_select(self) -> bool:
        return self.chk_speak_sel.isChecked()

    def content_read(self) -> dict:
        """재생 시 함께 읽을 내용."""
        return {"ko": self.act_play_ko.isChecked(), "en": self.act_play_en.isChecked(),
                "ex": self.act_play_ex.isChecked()}

    def current_lemma(self):
        top = self._top_of(self.tree.currentItem())
        return top.data(0, self.DATA_LEMMA) if top else None

    def current_row(self):
        """현재 선택 단어의 row dict(뜻·예시 포함, 없으면 None)."""
        lm = self.current_lemma()
        return next((r for r in self._rows if r["lemma"] == lm), None) if lm else None

    def shown_lemma_set(self) -> set:
        return {r["lemma"] for r in self._shown_rows()}

    # --- 표시 필터(전체/선택/날짜/초기) ---
    def _rebuild_filter(self, dates: list) -> None:
        cur = self.cmb_filter.currentText() if self.cmb_filter.count() else FILTER_ALL
        self.cmb_filter.blockSignals(True)
        self.cmb_filter.clear()
        self.cmb_filter.addItem(FILTER_ALL)
        self.cmb_filter.addItem(FILTER_SELECTED)
        for d in dates:
            self.cmb_filter.addItem(d)
        self.cmb_filter.addItem(FILTER_ORIG)
        idx = self.cmb_filter.findText(cur)
        self.cmb_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_filter.blockSignals(False)

    def set_filter_dates(self, dates: list) -> None:
        self._rebuild_filter(list(dates))

    def set_dict_sources(self, sources: list) -> None:
        """260611-102(P2)/260615-7(P9): '출처 ▾' 메뉴 — 구분(category)별 그룹.
        sources: [{source_id,name,category,kind,enabled,n_entries}]."""
        menu = self.btn_src.menu()
        # 260615-23: 메뉴가 열려 있는 동안(연속 토글 중)에는 재구성하지 않음(아이템 파괴 방지)
        if menu.isVisible():
            return
        menu.clear()
        self._src_submenus = []          # 하위메뉴 참조 유지(GC 방지)
        if not sources:
            a = menu.addAction("(사전 없음)"); a.setEnabled(False)
            return

        def _add(parent, s):
            tag = "👤" if s.get("kind") == "user" else "📘"
            a = QAction(f"{tag} {s.get('name', s['source_id'])}"
                        f"  ({s.get('n_entries', 0)})", parent, checkable=True)
            a.setChecked(bool(s.get("enabled", 1)))
            sid = s["source_id"]
            a.toggled.connect(lambda on, _sid=sid: self.sourceToggled.emit(_sid, on))
            parent.addAction(a)

        # 구분(category)별로 묶음. 구분 없으면 최상위에.
        cats = {}
        for s in sources:
            cats.setdefault((s.get("category") or "").strip(), []).append(s)
        for cat in sorted(k for k in cats if k):
            sub = _StayOpenMenu(f"📂 {cat}", menu)   # 하위메뉴도 연속 토글
            self._src_submenus.append(sub)
            menu.addMenu(sub)
            for s in cats[cat]:
                _add(sub, s)
        for s in cats.get("", []):       # 구분 미지정
            _add(menu, s)

    def word_filter(self) -> str:
        return self.cmb_filter.currentText() or FILTER_ALL

    def _on_filter_changed(self) -> None:
        self.wordFilterChanged.emit()

    # --- ↑/↓ 키 = 목록 이동(끝이면 이전/다음 페이지로 넘김) ---
    def eventFilter(self, obj, ev):
        # 260615-6: ② 패널 폭 변경 시 줄바꿈 높이 재계산(잘림/겹침 방지)
        if obj is self.tree and ev.type() == QEvent.Type.Resize:
            try:
                self.tree.doItemsLayout()
            except Exception:
                pass
        if obj is self.tree and ev.type() == QEvent.Type.KeyPress:
            k = ev.key()
            n = self.tree.topLevelItemCount()
            cur = self._top_of(self.tree.currentItem())
            idx = self.tree.indexOfTopLevelItem(cur) if cur else -1
            if k == Qt.Key.Key_Up and idx == 0:
                self.crossPageRequested.emit(-1); return True   # 첫 항목 → 이전 페이지
            if k == Qt.Key.Key_Down and idx == n - 1 and n > 0:
                self.crossPageRequested.emit(+1); return True   # 마지막 → 다음 페이지
        return super().eventFilter(obj, ev)

    def select_first(self) -> None:
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def select_last(self) -> None:
        n = self.tree.topLevelItemCount()
        if n:
            self.tree.setCurrentItem(self.tree.topLevelItem(n - 1))

    def select_next(self) -> None:
        """현재 항목 다음(없으면 첫)으로 선택 이동 — 분류 후 진행용."""
        n = self.tree.topLevelItemCount()
        if n == 0:
            return
        cur = self._top_of(self.tree.currentItem())
        idx = self.tree.indexOfTopLevelItem(cur) if cur else -1
        nxt = self.tree.topLevelItem(min(idx + 1, n - 1)) if idx >= 0 else self.tree.topLevelItem(0)
        if nxt:
            self.tree.setCurrentItem(nxt)

    # --- 설정 저장/복원(모든 선택 유지) ---
    def get_settings(self) -> dict:
        return {
            "levels": {lv: self._chk[lv].isChecked() for lv in _LEVELS},
            "show_ko": self.chk_ko.isChecked(), "show_en": self.chk_en.isChecked(),
            "show_ex": self.chk_ex.isChecked(), "show_ref": self.chk_ref.isChecked(),
            "show_img": self.chk_img.isChecked(),
            "sort": self.sort_combo.currentText(),
            "auto_highlight": self.chk_hl.isChecked(),
            "read_mode": self._read_mode,
            "speak_on_select": self.chk_speak_sel.isChecked(),
            "play_ko": self.act_play_ko.isChecked(),
            "play_en": self.act_play_en.isChecked(),
            "play_ex": self.act_play_ex.isChecked(),
            "word_filter": self.word_filter(),
            "expanded": self._expanded,
        }

    def apply_settings(self, d: dict) -> None:
        if not d:
            return
        lv = d.get("levels") or {}
        for k, cb in self._chk.items():
            if k in lv:
                cb.blockSignals(True); cb.setChecked(bool(lv[k])); cb.blockSignals(False)
        for key, cb in (("show_ko", self.chk_ko), ("show_en", self.chk_en),
                        ("show_ex", self.chk_ex), ("show_ref", self.chk_ref),
                        ("show_img", self.chk_img),
                        ("speak_on_select", self.chk_speak_sel)):
            if key in d:
                cb.setChecked(bool(d[key]))
        for key, a in (("play_ko", self.act_play_ko), ("play_en", self.act_play_en),
                       ("play_ex", self.act_play_ex)):
            if key in d:
                a.setChecked(bool(d[key]))
        if d.get("sort"):
            self.sort_combo.setCurrentText(d["sort"])
        if d.get("read_mode"):
            self._set_read_mode(d["read_mode"])
        if "auto_highlight" in d:
            self.chk_hl.setChecked(bool(d["auto_highlight"]))
        if d.get("word_filter"):
            i = self.cmb_filter.findText(d["word_filter"])
            if i >= 0:
                self.cmb_filter.setCurrentIndex(i)
        if "expanded" in d:
            self._expanded = bool(d["expanded"])
            self.btn_expand.setText("접기" if self._expanded else "펼치기")
        self._render()

    def is_auto_highlight(self) -> bool:
        return self.chk_hl.isChecked()

    def shown_lemmas(self) -> list[tuple[str, str]]:
        """현재 표시(필터·정렬 후) 단어 (lemma, lang) 목록."""
        return [(r["lemma"], r.get("lang", "eng")) for r in self._shown_rows()]

    def set_page_words(self, page: int, rows: list[dict]) -> None:
        self._page = page
        self._rows = rows or []
        self._render()

    def selected_levels(self) -> list[str]:
        return [lv for lv in _LEVELS if self._chk[lv].isChecked()]

    def _find_item(self, lemma: str):
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, self.DATA_LEMMA) == lemma:
                return it
        return None

    def select_lemma(self, lemma: str, to_top: bool = True) -> None:
        """트리에서 표제어를 선택·**상단 스크롤**(호버/읽는 단어 표시).
        프로그램적 선택이라 wordSelected(강조·읽기 재트리거)는 발신하지 않음."""
        from PyQt6.QtWidgets import QAbstractItemView
        it = self._find_item(lemma)
        if it is None:
            return
        self._programmatic = True
        try:
            if self.tree.currentItem() is not it:
                self.tree.setCurrentItem(it)
        finally:
            self._programmatic = False
        it = self._find_item(lemma)          # 새로고침으로 재생성됐을 수 있음 → 재취득
        if it is None:
            return
        hint = (QAbstractItemView.ScrollHint.PositionAtTop if to_top
                else QAbstractItemView.ScrollHint.EnsureVisible)
        self.tree.scrollToItem(it, hint)

    # --- 내부 --------------------------------------------------------------
    def _shown_rows(self) -> list[dict]:
        levels = set(self.selected_levels())
        rows = [r for r in self._rows if r.get("level") in levels
                or (r.get("level") == "미정" and "고급" in levels)]
        mode = self.sort_combo.currentText()
        if mode == SORT_ALPHA:
            rows = sorted(rows, key=lambda r: r["lemma"])
        elif mode == SORT_FREQ:
            rows = sorted(rows, key=lambda r: (-r.get("count", 1), r["lemma"]))
        else:  # 문장 순서
            rows = sorted(rows, key=lambda r: r.get("pos", 0))
        return rows

    def _render(self) -> None:
        self.tree.clear()
        shown = self._shown_rows()
        total = len(self._rows)
        if total == 0:
            self.lbl_status.setText(
                f"p{self._page+1}: 표시할 단어가 없습니다. (미생성이면 [단어장 생성])")
        else:
            self.lbl_status.setText(f"p{self._page+1}: {len(shown)}/{total} 단어")
        show_ko, show_en, show_ex = (self.chk_ko.isChecked(),
                                     self.chk_en.isChecked(), self.chk_ex.isChecked())
        show_ref = self.chk_ref.isChecked()

        def _add_def(top, d):
            txt = _clean_markup(d["definition"])
            src = d.get("source") or ""
            if show_ref and d.get("is_dict") and src:
                txt = f"{txt}  — {src}"
            child = QTreeWidgetItem(top, [txt])
            ref = d.get("ref") or ""
            if ref:
                child.setToolTip(0, ref)
            return child

        for r in shown:
            lv = r.get("level", "미정")
            cnt = r.get("count", 1)
            mark = "✎ " if r.get("user_edited") else ""
            badge = _BADGE.get(lv, "")
            if r.get("has_dict"):           # 사전(전문용어) 매칭 표시
                badge = "📘"
            top = QTreeWidgetItem([f"{badge} {mark}{r['lemma']}"
                                   + (f"   ×{cnt}" if cnt > 1 else "")])
            top.setFont(0, self._bold)
            top.setData(0, self.DATA_LEMMA, r["lemma"])
            top.setData(0, self.DATA_PAGE, self._page)
            top.setData(0, self.DATA_LANG, r.get("lang", "eng"))
            # 260615-8(P10): 사전 그림이 있으면 단어 아이콘으로 표시
            if self.chk_img.isChecked() and (r.get("image") or "").strip():
                try:
                    from viewer.study.image_fetch import image_path
                    from PyQt6.QtGui import QIcon, QPixmap
                    p = image_path(r["image"])
                    if p:
                        top.setIcon(0, QIcon(QPixmap(p)))
                except Exception:
                    pass
            defs = r.get("definitions") or []
            ko_defs = [d for d in defs if _HANGUL.search(d["definition"])]
            en_defs = [d for d in defs if not _HANGUL.search(d["definition"])]
            if show_ko:
                for d in ko_defs:
                    _add_def(top, d)
            if show_en:
                for d in en_defs:
                    _add_def(top, d)
            if show_ex:
                for e in (r.get("examples") or []):
                    txt = "예) " + _clean_markup(e["example"])
                    # 260615-10(P12): 참고문헌 토글 시 예문의 구분/출처명 표기
                    if show_ref and e.get("source") and e.get("source") != "book":
                        txt += f"  — {e['source']}"
                    QTreeWidgetItem(top, [txt])
            self.tree.addTopLevelItem(top)
        if self._expanded:
            self.tree.expandAll()

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self.tree.expandAll()
            self.btn_expand.setText("접기")
        else:
            self.tree.collapseAll()
            self.btn_expand.setText("펼치기")

    def _top_of(self, item) -> Optional[QTreeWidgetItem]:
        if item is None:
            return None
        return item if item.parent() is None else item.parent()

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        if item.parent() is None:
            item.setExpanded(not item.isExpanded())

    def _on_current_changed(self, cur, _prev) -> None:
        if getattr(self, "_programmatic", False):   # 호버/읽기 프로그램 선택 → 재트리거 금지
            return
        top = self._top_of(cur)
        if top is None:
            return
        lemma = top.data(0, self.DATA_LEMMA)
        if lemma:
            self.wordSelected.emit(lemma, int(top.data(0, self.DATA_PAGE) or 0))
            if self.chk_speak_sel.isChecked():    # 선택시 읽기
                self.speakRequested.emit(lemma, top.data(0, self.DATA_LANG) or "eng")

    def _current_word(self) -> Optional[tuple[str, str]]:
        top = self._top_of(self.tree.currentItem())
        if top is None:
            return None
        return top.data(0, self.DATA_LEMMA), (top.data(0, self.DATA_LANG) or "eng")

    def _speak_current(self) -> None:
        w = self._current_word()
        if w:
            self.speakRequested.emit(w[0], w[1])

    def _edit_current(self) -> None:
        w = self._current_word()
        if w:
            self.editRequested.emit(w[0], w[1])
