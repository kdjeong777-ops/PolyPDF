"""건설기준(KCSC) 본문 뷰어 — 국가건설기준센터 OPEN API (260618-37).

법령·고시 패널(law_search_dialog)과 동일한 사이드 패널 방식.
현재(CodeViewer 우선): **코드체계(KDS/KCS) + 코드번호 직접 입력 → 본문 표시**.
목록(CodeList) 검색은 API 형식 확정 후 추가 예정.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices, QShortcut, QKeySequence, QTextDocument
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QComboBox, QListWidget, QListWidgetItem, QTextBrowser, QWidget,
)

from viewer.study.kcsc_api import TYPES, TYPE_NAMES
from viewer.widgets.toggle_splitter import ToggleSplitter
from viewer.widgets.icons import themed_icon

_SITE = "https://www.kcsc.re.kr"


class _ContentWorker(QThread):
    done = pyqtSignal(str, list, list, dict)      # html, debug, arts, meta

    def __init__(self, key, ctype, code):
        super().__init__()
        self._key, self._ctype, self._code = key, ctype, code

    def run(self):
        try:
            from viewer.study.kcsc_api import fetch_content_debug
            html, dbg, arts, meta = fetch_content_debug(self._key, self._ctype, self._code)
            self.done.emit(html, dbg, arts, meta)
        except Exception as e:
            self.done.emit("", [f"ERR {type(e).__name__}: {e}"], [], {})


class KcscHostWindow(QWidget):
    """전체화면 팝아웃용 호스트 창(닫으면 closed → 내부화면 복귀)."""
    closed = pyqtSignal()

    def closeEvent(self, e):
        self.closed.emit()
        e.accept()


class KcscSearchPanel(QWidget):
    """건설기준(KCSC) 본문 패널. 메인 오른쪽 2단 임베드 / 전체화면 팝아웃."""
    closeRequested = pyqtSignal()
    fullscreenToggled = pyqtSignal()

    def __init__(self, key: str, win=None):
        super().__init__()
        self.setWindowTitle("건설기준(KCSC) 본문 보기")
        self._key = key
        self._win = win
        self._cworker = None
        self._workers: list = []           # 실행 중 스레드 보관(terminate 크래시 방지)
        self._arts: list = []

        self.setMinimumWidth(360)
        try:
            _f = self.font(); _f.setFamily("Malgun Gothic"); self.setFont(_f)
        except Exception:
            pass
        _esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        _esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        _esc.activated.connect(self._on_escape)

        v = QVBoxLayout(self)

        # --- 제목줄: '건설기준(KCSC)' + 전체화면 + 닫기 ---
        title_row = QHBoxLayout()
        title = QLabel("건설기준(KCSC)")
        tf = title.font(); tf.setBold(True); tf.setPointSize(max(11, tf.pointSize() + 2))
        title.setFont(tf)
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.btn_full = QPushButton("⛶ 전체화면")
        self.btn_full.setToolTip("전체화면(별도 창) ↔ 내부화면(메인 오른쪽)")
        self.btn_full.clicked.connect(self.fullscreenToggled.emit)
        title_row.addWidget(self.btn_full)
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(34, 28)
        self.btn_close.setToolTip("건설기준 닫기")
        self.btn_close.setStyleSheet(
            "QPushButton{color:#d11;font-weight:bold;border:1px solid #c0c0c0;"
            "border-radius:5px;background:#f2f2f2;}"
            "QPushButton:hover{background:#e81123;color:#fff;border-color:#e81123;}")
        self.btn_close.clicked.connect(self.closeRequested.emit)
        title_row.addWidget(self.btn_close)
        v.addLayout(title_row)

        # --- 입력줄: 코드체계(KDS/KCS) + 코드번호 + 보기 + 지구본 ---
        top = QHBoxLayout()
        self.cmb_type = QComboBox()
        for code_t, name_t in TYPES:
            self.cmb_type.addItem(f"{code_t} · {name_t}", code_t)
        self.ed = QLineEdit()
        self.ed.setPlaceholderText("코드번호 (예: 114010)")
        self.ed.returnPressed.connect(self._view)
        self.btn_view = QPushButton("보기")
        self.btn_view.clicked.connect(self._view)
        self.btn_globe = QPushButton()
        self.btn_globe.setIcon(themed_icon("globe"))
        self.btn_globe.setFixedWidth(36)
        self.btn_globe.setToolTip("국가건설기준센터 웹사이트 열기")
        self.btn_globe.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(_SITE)))
        top.addWidget(self.cmb_type)
        top.addWidget(self.ed, 1)
        top.addWidget(self.btn_view)
        top.addWidget(self.btn_globe)
        v.addLayout(top)

        self.info = QLabel("코드체계(KDS/KCS)와 코드번호를 입력하고 [보기]. (목록 검색은 추후 지원)")
        self.info.setStyleSheet("color:#888;")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        # --- 본문: 좌(절 목록) / 우(본문) ---
        self.split = ToggleSplitter(Qt.Orientation.Horizontal)
        self.split.setHandleWidth(8)
        self.sec_list = QListWidget()
        self.sec_list.itemClicked.connect(self._on_section)
        self.sec_list.currentItemChanged.connect(lambda *_: self._on_section(self.sec_list.currentItem()))
        self.split.addWidget(self.sec_list)
        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(True)
        self.viewer.setPlaceholderText("본문이 여기에 표시됩니다.")
        self.viewer.setStyleSheet("QTextBrowser{background:#ffffff;color:#1a1a1a;}")
        self.split.addWidget(self.viewer)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setCollapsible(0, True)
        self.split.setSizes([260, 740])
        v.addWidget(self.split, 1)

        # --- 본문 내 찾기 바(Ctrl+F) ---
        self.find_bar = QWidget()
        fb = QHBoxLayout(self.find_bar)
        fb.setContentsMargins(2, 2, 2, 2)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("내용에서 찾기")
        self.find_edit.returnPressed.connect(lambda: self._find(False))
        b_prev = QPushButton(); b_prev.setIcon(themed_icon("chevron_up"))
        b_prev.setFixedWidth(30); b_prev.clicked.connect(lambda: self._find(True))
        b_next = QPushButton(); b_next.setIcon(themed_icon("chevron_down"))
        b_next.setFixedWidth(30); b_next.clicked.connect(lambda: self._find(False))
        b_fclose = QPushButton(); b_fclose.setIcon(themed_icon("close"))
        b_fclose.setFixedWidth(30); b_fclose.clicked.connect(self._hide_find)
        fb.addWidget(self.find_edit, 1); fb.addWidget(b_prev); fb.addWidget(b_next); fb.addWidget(b_fclose)
        self.find_bar.setVisible(False)
        v.addWidget(self.find_bar)

        QShortcut(QKeySequence.StandardKey.Find, self, activated=self._show_find)
        QShortcut(QKeySequence("Esc"), self.find_edit, activated=self._hide_find)

        for b in self.findChildren(QPushButton):
            b.setAutoDefault(False); b.setDefault(False)
        self.ed.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)

    # ----- 레이아웃 -----
    def set_fullscreen(self, is_full: bool):
        self.btn_full.setText("▣ 내부화면" if is_full else "⛶ 전체화면")

    def _on_escape(self):
        if self.find_bar.isVisible():
            self.find_bar.hide()
        else:
            self.closeRequested.emit()

    # ----- 본문 조회 -----
    def _view(self):
        ctype = self.cmb_type.currentData()
        code = (self.ed.text() or "").strip()
        if not code:
            self.info.setText("코드번호를 입력하세요. (예: 114010)")
            return
        if not (self._key or "").strip():
            self.info.setText("설정 → '인터넷 사전'의 KCSC 키를 먼저 입력하세요.")
            return
        self.info.setText("불러오는 중…")
        self.sec_list.clear(); self.viewer.clear()
        w = _ContentWorker(self._key, ctype, code)
        self._workers.append(w)
        w.done.connect(self._on_content)
        w.finished.connect(lambda w=w: self._workers.remove(w) if w in self._workers else None)
        self._cworker = w
        w.start()

    def _on_content(self, html, dbg, arts, meta):
        if not html:
            self.info.setText("표시할 본문이 없습니다. " + (dbg[-1] if dbg else ""))
            return
        self._arts = arts or []
        self.viewer.setHtml(html)
        self.sec_list.clear()
        for label, anchor in self._arts:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, anchor)
            self.sec_list.addItem(it)
        name = meta.get("name") or ""
        ver = meta.get("version") or ""
        self.info.setText((f"{name}" + (f"  (v{ver})" if ver else "")) if name
                          else (dbg[-1] if dbg else ""))

    def _on_section(self, item):
        if item is None:
            return
        anchor = item.data(Qt.ItemDataRole.UserRole)
        if anchor:
            self.viewer.scrollToAnchor(anchor)

    # ----- 찾기 -----
    def _show_find(self):
        self.find_bar.setVisible(True)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def _hide_find(self):
        self.find_bar.hide()
        self.viewer.setFocus()

    def _find(self, backward: bool):
        q = self.find_edit.text()
        if not q:
            return
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if not self.viewer.find(q, flags):
            # 끝/처음으로 감아서 재시도
            cur = self.viewer.textCursor()
            cur.movePosition(cur.MoveOperation.End if backward else cur.MoveOperation.Start)
            self.viewer.setTextCursor(cur)
            self.viewer.find(q, flags)
